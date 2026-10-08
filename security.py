"""Request protections shared by the admin and guest applications."""
import hashlib
import hmac
import secrets
import time
from datetime import timedelta
from urllib.parse import urlsplit

from flask import current_app, jsonify, request, session


def csrf_token():
    """Return a session-bound token for forms and JSON requests."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']


def safe_next_url(value):
    """Permit local admin redirects only."""
    value = value or '/admin'
    if not isinstance(value, str) or any(ord(c) < 32 for c in value) or '\\' in value:
        return '/admin'
    try:
        parsed = urlsplit(value)
    except ValueError:
        return '/admin'
    if parsed.scheme or parsed.netloc or not (parsed.path == '/admin' or parsed.path.startswith('/admin/')):
        return '/admin'
    return value


def allow_request(bucket, limit=20, window=900):
    """Apply a cross-worker fixed-window limit without storing raw addresses."""
    from runtime_config import data_path
    from storage import update_json
    if current_app.config.get('TESTING') and not current_app.config.get('TEST_RATE_LIMITS'):
        return True
    key = hashlib.sha256(f'{bucket}:{request.remote_addr}'.encode()).hexdigest()
    now = time.time()
    allowed = False

    def update(data):
        nonlocal allowed
        for old_key in list(data):
            if data[old_key]['until'] <= now:
                del data[old_key]
        entry = data.setdefault(key, {'count': 0, 'until': now + window})
        allowed = entry['count'] < limit
        entry['count'] += 1
        return data

    update_json(data_path('rate_limits.json'), update, {})
    return allowed


def init_security(app):
    """Install CSRF, secure cookies, cache policy, and response headers."""
    app.config.setdefault('CSRF_ENABLED', True)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=12))
    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def protect_forms():
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and app.config['CSRF_ENABLED']:
            expected = session.get('_csrf_token', '')
            supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
                if request.is_json or request.headers.get('X-CSRF-Token'):
                    return jsonify(error='Your session expired. Reload the page and try again.'), 400
                return 'Your session expired. Reload the page and try again.', 400

    @app.after_request
    def response_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://www.googletagmanager.com; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: https://www.google-analytics.com; "
            "connect-src 'self' https://*.google-analytics.com https://*.analytics.google.com "
            "https://www.googletagmanager.com; frame-src 'self'; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
        )
        if app.config.get('SESSION_COOKIE_SECURE'):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if not request.path.startswith(('/static/', '/media/')):
            response.headers['Cache-Control'] = 'no-store'
        return response

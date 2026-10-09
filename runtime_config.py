"""Runtime configuration shared by the web app, stores, and release tooling."""
import os
import re
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent


def data_dir():
    """Return the persistent data root; production never defaults to the checkout."""
    configured = os.environ.get('RSVP_DATA_DIR')
    if configured:
        return Path(configured).expanduser().resolve()
    if os.environ.get('RSVP_ENV') == 'production':
        raise RuntimeError('Production requires an explicit RSVP_DATA_DIR outside the release directory.')
    return PROJECT_ROOT / 'data'


def data_path(relative):
    """Resolve a data filename without allowing traversal outside the data root."""
    root = data_dir()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Data paths must stay within RSVP_DATA_DIR.')
    return path


def configure_app(app):
    """Load development config, environment overrides, and strict production checks."""
    app.config.from_pyfile('config.py', silent=True)
    environment = os.environ.get('RSVP_ENV', 'development')
    if environment not in {'development', 'test', 'production'}:
        raise RuntimeError('RSVP_ENV must be development, test, or production.')
    defaults = {
        'SECRET_KEY': 'development-only-change-before-production',
        'SENDER_EMAIL': '',
        'CONTACT_EMAIL': '',
        'ADMIN_PASSWORD': '',
        'WEBAUTHN_RP_NAME': 'Party Mail',
        'PUBLIC_URL': 'https://partymail.app' if environment == 'production' else 'http://localhost:5000',
        'GA_MEASUREMENT_ID': '',
        'APPLE_TEAM_ID': '2FZS79QCFD',
        'ANDROID_SHA256_CERT_FINGERPRINTS': '',
    }
    for key, default in defaults.items():
        app.config.setdefault(key, default)
    # Flask supplies SECRET_KEY=None itself, so setdefault alone cannot fill it.
    if not app.config.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = defaults['SECRET_KEY']
    for key in (*defaults, 'WEBAUTHN_RP_ID', 'WEBAUTHN_ORIGIN'):
        value = os.environ.get('RSVP_' + key)
        if value is not None:
            app.config[key] = value
    public_url = urlparse(app.config['PUBLIC_URL'])
    app.config['PUBLIC_BASE_URL'] = app.config['PUBLIC_URL'].rstrip('/')
    app.config['EMAIL_ENABLED'] = os.environ.get('RSVP_EMAIL_ENABLED', 'true' if environment == 'production' else 'false').lower() in {'true', '1', 'yes'}
    app.config['TRUST_PROXY'] = os.environ.get('RSVP_TRUST_PROXY', 'false').lower() in {'true', '1', 'yes'}
    if app.config['TRUST_PROXY']:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0, x_prefix=0)
    app.config['CREDENTIALS_FILE'] = str(data_path('credentials.json'))
    app.config['TOKEN_FILE'] = str(data_path('token.json'))
    release_file = PROJECT_ROOT / 'RELEASE_ID'
    app.config['RELEASE_ID'] = os.environ.get('RSVP_RELEASE_ID') or (release_file.read_text().strip() if release_file.exists() else 'development')
    app.config.setdefault('WEBAUTHN_RP_ID', public_url.hostname or 'localhost')
    app.config.setdefault('WEBAUTHN_ORIGIN', app.config['PUBLIC_URL'].rstrip('/'))
    app.config.update(
        RSVP_ENV=environment,
        RSVP_DATA_DIR=str(data_dir()),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
    )
    if environment == 'test':
        app.config.update(TESTING=True, SECRET_KEY='test-only-secret-key', ADMIN_PASSWORD='test')
    if environment == 'production':
        validate_production(app.config)
        app.config.update(SESSION_COOKIE_SECURE=True, TRUSTED_HOSTS=[public_url.hostname])


def validate_production(config):
    """Fail startup before serving requests against an unsafe or empty data location."""
    errors = []
    root = data_dir()
    raw_root = os.environ.get('RSVP_DATA_DIR', '')
    if not Path(raw_root).is_absolute() or root.is_relative_to(PROJECT_ROOT):
        errors.append('RSVP_DATA_DIR must be an absolute directory outside the release checkout')
    if not root.is_dir() or not (root / '.rsvp-data').is_file():
        errors.append('RSVP_DATA_DIR must exist and contain the .rsvp-data marker (run scripts/migrate_data.py)')
    elif not os.access(root, os.R_OK | os.W_OK | os.X_OK):
        errors.append('RSVP_DATA_DIR must be readable and writable by the service user')
    secret = str(config.get('SECRET_KEY', ''))
    if not os.environ.get('RSVP_SECRET_KEY') or len(secret) < 32 or secret.startswith(('REPLACE_', 'development-', 'test-')):
        errors.append('RSVP_SECRET_KEY must be set to a random secret of at least 32 characters')
    public = urlparse(config.get('PUBLIC_URL', ''))
    if public.scheme != 'https' or not public.hostname or public.path not in {'', '/'} or public.query or public.fragment:
        errors.append('RSVP_PUBLIC_URL must be the HTTPS origin, for example https://partymail.app')
    origin = config.get('WEBAUTHN_ORIGIN', '').rstrip('/')
    if origin != config.get('PUBLIC_URL', '').rstrip('/'):
        errors.append('RSVP_WEBAUTHN_ORIGIN must equal RSVP_PUBLIC_URL')
    if config.get('WEBAUTHN_RP_ID') != public.hostname:
        errors.append('RSVP_WEBAUTHN_RP_ID must match the public hostname')
    contact = str(config.get('CONTACT_EMAIL', ''))
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', contact):
        errors.append('RSVP_CONTACT_EMAIL must be the address /privacy and /terms give for questions and removal requests')
    if errors:
        raise RuntimeError('Unsafe production configuration: ' + '; '.join(errors))

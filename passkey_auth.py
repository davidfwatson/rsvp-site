"""Passkey accounts and one-use administrator access links.

Credentials are retained when moving the data directory. Never change the
production RP ID or origin without a deliberate passkey migration.
"""
import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, session, url_for
from webauthn import (
    generate_registration_options, verify_registration_response,
    generate_authentication_options, verify_authentication_response, options_to_json,
)
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, ResidentKeyRequirement,
    UserVerificationRequirement, PublicKeyCredentialDescriptor,
)
from runtime_config import data_path
from storage import read_json, write_json, update_json

passkey_bp = Blueprint('passkey', __name__)
ADMINS_FILE = str(data_path('admins.json'))
INVITE_EXPIRY_DAYS = 7
SIGNIN_EXPIRY_MINUTES = 30
CHALLENGE_TTL_SECONDS = 300
_DEFAULT = {'admins': [], 'invites': [], 'signin_links': [], 'challenges': {}}


class AccountError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load_data():
    return read_json(ADMINS_FILE, _DEFAULT)


def _save_data(data):
    """Compatibility helper; use _update_data for read-modify-write operations."""
    write_json(ADMINS_FILE, data)


def _update_data(mutator):
    def update(data):
        for key, default in _DEFAULT.items():
            data.setdefault(key, default.copy())
        mutator(data)
    return update_json(ADMINS_FILE, update, _DEFAULT)


def _expires(item, minutes=None):
    try:
        value = item.get('expires_at')
        if value:
            expiry = datetime.fromisoformat(value)
        else:
            expiry = datetime.fromisoformat(item['created_at']) + timedelta(
                minutes=minutes if minutes is not None else INVITE_EXPIRY_DAYS * 24 * 60)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry <= datetime.now(timezone.utc)
    except (ValueError, TypeError, KeyError):
        return True


def _clean_expired_invites(data):
    data['invites'] = [item for item in data.get('invites', []) if not _expires(item)]
    data['signin_links'] = [item for item in data.get('signin_links', [])
                            if not _expires(item, SIGNIN_EXPIRY_MINUTES)]
    data['challenges'] = {key: value for key, value in data.get('challenges', {}).items()
                          if time.time() - value.get('issued_at', 0) < CHALLENGE_TTL_SECONDS}


def safe_admin_next(value):
    """Only permit navigation to this site's admin area after sign-in."""
    if not isinstance(value, str) or '\\' in value or any(ord(c) < 32 for c in value):
        return url_for('admin_dashboard')
    try:
        parsed = urlsplit(value)
    except ValueError:
        return url_for('admin_dashboard')
    if parsed.scheme or parsed.netloc or not (parsed.path == '/admin' or parsed.path.startswith('/admin/')):
        return url_for('admin_dashboard')
    return value


def get_admin_by_id(admin_id):
    return next((a for a in _load_data()['admins'] if a['id'] == admin_id), None)


def get_current_admin():
    admin_id = session.get('admin_id')
    if not admin_id:
        return None
    admin = get_admin_by_id(admin_id)
    if not admin or session.get('admin_auth_version', 0) != admin.get('auth_version', 0):
        session.clear()
        return None
    return admin


def establish_admin_session(admin):
    """Rotate the entire pre-authentication session, including its CSRF token."""
    session.clear()
    session['admin_id'] = admin['id']
    session['admin_auth_version'] = admin.get('auth_version', 0)
    session.permanent = True


def bootstrap_owner():
    """Atomically find/create the owner for the configured legacy password."""
    result = {}
    def create(data):
        owner = next((a for a in data['admins'] if a.get('is_owner')), None)
        if not owner:
            owner = {'id': str(uuid.uuid4()), 'name': 'Owner', 'is_owner': True,
                     'credentials': [], 'created_at': _now(), 'auth_version': 0}
            data['admins'].append(owner)
        owner['last_login_at'] = _now()
        result.update(owner)
    _update_data(create)
    return result


def _api_request():
    return request.path.startswith('/api/') or request.is_json or request.path.endswith(('/options', '/verify')) or request.path in (
        '/admin/passkey/list', '/admin/invites', '/admin/accounts')


def admin_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not get_current_admin():
            if _api_request():
                return jsonify(success=False, error='Please sign in again.'), 401
            return redirect(url_for('admin_login', next=request.full_path.rstrip('?')))
        return function(*args, **kwargs)
    return wrapped


def owner_required(function):
    @wraps(function)
    @admin_required
    def wrapped(*args, **kwargs):
        if not get_current_admin().get('is_owner'):
            if _api_request():
                return jsonify(success=False, error='Only the owner can manage administrator access.'), 403
            abort(403)
        return function(*args, **kwargs)
    return wrapped


def _get_rp_id():
    return current_app.config.get('WEBAUTHN_RP_ID', 'localhost')


def _get_rp_name():
    return current_app.config.get('WEBAUTHN_RP_NAME', 'Party Mail')


def _get_origin():
    from mobile_api import android_origins
    return [current_app.config.get('WEBAUTHN_ORIGIN', 'http://localhost:5000'),
            *android_origins(current_app.config)]


def _body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise AccountError('A JSON object is required.')
    return body


def _name(value, fallback=None):
    if value is None and fallback:
        return fallback
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
        raise AccountError('Enter a name between 1 and 80 characters.')
    return value.strip()


def _error(message, status=400):
    return jsonify(success=False, error=message), status


@passkey_bp.errorhandler(AccountError)
def account_error(error):
    return _error(str(error))


@passkey_bp.before_request
def limit_public_auth_requests():
    from security import allow_request
    endpoint = (request.endpoint or '').removeprefix('passkey.')
    if endpoint in {'auth_options', 'auth_verify', 'invite_register_options', 'invite_register_verify', 'signin_link', 'invite_page'}:
        limit = 30 if request.method == 'POST' else 90
        if not allow_request('account-' + endpoint, limit=limit, window=900):
            response, status = _error('Too many attempts. Please try again in 15 minutes.', 429)
            response.headers['Retry-After'] = '900'
            return response, status


@passkey_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def _issue_challenge(options, purpose, subject=None, **extra):
    challenge_id = secrets.token_urlsafe(32)
    def issue(data):
        _clean_expired_invites(data)
        data['challenges'][challenge_id] = {'challenge': bytes_to_base64url(options.challenge),
                                          'purpose': purpose, 'subject': subject,
                                          'issued_at': time.time(), **extra}
    _update_data(issue)
    session['webauthn_challenge_id'] = challenge_id
    return options_to_json(options), 200, {'Content-Type': 'application/json'}


def _consume_challenge(purpose, subject=None):
    challenge_id = session.pop('webauthn_challenge_id', None)
    result = {}
    def consume(data):
        challenge = data['challenges'].pop(challenge_id, None)
        if challenge:
            result.update(challenge)
        _clean_expired_invites(data)
    _update_data(consume)
    if (not result or result.get('purpose') != purpose or result.get('subject') != subject
            or time.time() - result.get('issued_at', 0) >= CHALLENGE_TTL_SECONDS):
        raise AccountError('This request expired. Please try again.')
    return result


def _registration_options(admin_id, name, exclude=()):
    return generate_registration_options(
        rp_id=_get_rp_id(), rp_name=_get_rp_name(), user_id=admin_id.encode(),
        user_name=name, user_display_name=name,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c['credential_id'])) for c in exclude],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED),
    )


def _verify_registration(body, challenge):
    try:
        return verify_registration_response(
            credential=body, expected_challenge=base64url_to_bytes(challenge['challenge']),
            expected_rp_id=_get_rp_id(), expected_origin=_get_origin(), require_user_verification=True)
    except Exception:
        current_app.logger.info('Passkey registration verification failed')
        raise AccountError('The passkey could not be verified. Please try again.')


def _credential(verification, name):
    return {'credential_id': bytes_to_base64url(verification.credential_id),
            'public_key': bytes_to_base64url(verification.credential_public_key),
            'sign_count': verification.sign_count, 'name': name, 'created_at': _now()}


def _unique_credential(data, credential):
    if any(c['credential_id'] == credential['credential_id']
           for a in data['admins'] for c in a.get('credentials', [])):
        raise AccountError('This passkey is already registered.')


@passkey_bp.route('/admin/passkey/register/options', methods=['POST'])
@admin_required
def register_options():
    admin = get_current_admin()
    return _issue_challenge(_registration_options(admin['id'], admin['name'], admin.get('credentials', [])),
                            'register', admin['id'], auth_version=admin.get('auth_version', 0))


@passkey_bp.route('/admin/passkey/register/verify', methods=['POST'])
@admin_required
def register_verify():
    admin_id = session['admin_id']
    challenge = _consume_challenge('register', admin_id)
    body = _body()
    credential = _credential(_verify_registration(body, challenge), _name(body.get('name'), 'Passkey'))
    def add(data):
        admin = next((a for a in data['admins'] if a['id'] == admin_id), None)
        if not admin or admin.get('auth_version', 0) != challenge.get('auth_version', 0):
            raise AccountError('This account no longer has access. Please sign in again.')
        _unique_credential(data, credential)
        admin.setdefault('credentials', []).append(credential)
    _update_data(add)
    return jsonify(success=True, message='Passkey added.')


@passkey_bp.route('/admin/passkey/auth/options', methods=['POST'])
def auth_options():
    # Keep older non-discoverable credentials usable after this upgrade.
    credentials = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(c['credential_id']))
                   for admin in _load_data()['admins'] for c in admin.get('credentials', [])]
    options = generate_authentication_options(rp_id=_get_rp_id(), allow_credentials=credentials or None,
        user_verification=UserVerificationRequirement.REQUIRED)
    return _issue_challenge(options, 'authenticate')


@passkey_bp.route('/admin/passkey/auth/verify', methods=['POST'])
def auth_verify():
    challenge = _consume_challenge('authenticate')
    body = _body()
    result = {}
    def authenticate(data):
        for admin in data['admins']:
            credential = next((c for c in admin.get('credentials', []) if c['credential_id'] == body.get('id')), None)
            if not credential:
                continue
            try:
                verification = verify_authentication_response(
                    credential=body, expected_challenge=base64url_to_bytes(challenge['challenge']),
                    expected_rp_id=_get_rp_id(), expected_origin=_get_origin(),
                    credential_public_key=base64url_to_bytes(credential['public_key']),
                    credential_current_sign_count=credential['sign_count'], require_user_verification=True)
            except Exception:
                current_app.logger.info('Passkey authentication verification failed')
                raise AccountError('The passkey could not be verified. Please try again.')
            credential['sign_count'] = verification.new_sign_count
            credential['last_used_at'] = _now()
            admin['last_login_at'] = _now()
            result.update(admin)
            return
        raise AccountError('This passkey does not have administrator access.')
    _update_data(authenticate)
    establish_admin_session(result)
    return jsonify(success=True, redirect=safe_admin_next(body.get('next')))


@passkey_bp.route('/admin/passkey/list')
@admin_required
def list_passkeys():
    admin = get_current_admin()
    return jsonify(passkeys=[{key: c.get(key) for key in ('credential_id', 'name', 'created_at', 'last_used_at')}
                             for c in admin.get('credentials', [])])


@passkey_bp.route('/admin/passkey/delete', methods=['POST'])
@admin_required
def delete_passkey():
    credential_id = _body().get('credential_id')
    admin_id = session['admin_id']
    def remove(data):
        admin = next(a for a in data['admins'] if a['id'] == admin_id)
        credentials = admin.get('credentials', [])
        if not any(c['credential_id'] == credential_id for c in credentials):
            raise AccountError('Passkey not found.')
        if len(credentials) <= 1:
            raise AccountError('Add another passkey before removing your last one.')
        admin['credentials'] = [c for c in credentials if c['credential_id'] != credential_id]
    _update_data(remove)
    return jsonify(success=True)


@passkey_bp.route('/admin/settings')
@admin_required
def admin_settings():
    return render_template('admin_settings.html', admin=get_current_admin())


@passkey_bp.route('/admin/accounts')
@owner_required
def list_accounts():
    data = _load_data()
    return jsonify(accounts=[{'id': a['id'], 'name': a['name'], 'is_owner': a.get('is_owner', False),
                              'created_at': a.get('created_at'), 'last_login_at': a.get('last_login_at'),
                              'passkey_count': len(a.get('credentials', []))} for a in data['admins']],
                   signin_links=[{k: link.get(k) for k in ('id', 'admin_id', 'created_at', 'expires_at')}
                                 for link in data.get('signin_links', []) if not _expires(link, SIGNIN_EXPIRY_MINUTES)])


@passkey_bp.route('/admin/accounts/update', methods=['POST'])
@admin_required
def update_account():
    body = _body()
    current = get_current_admin()
    target_id = body.get('admin_id') or current['id']
    if target_id != current['id'] and not current.get('is_owner'):
        return _error('Only the owner can edit other administrators.', 403)
    name = _name(body.get('name'))
    def update(data):
        target = next((a for a in data['admins'] if a['id'] == target_id), None)
        if not target:
            raise AccountError('Administrator not found.')
        target['name'] = name
    _update_data(update)
    return jsonify(success=True, name=name)


@passkey_bp.route('/admin/accounts/revoke', methods=['POST'])
@owner_required
def revoke_account():
    target_id = _body().get('admin_id')
    def revoke(data):
        target = next((a for a in data['admins'] if a['id'] == target_id), None)
        if not target:
            raise AccountError('Administrator not found.')
        if target.get('is_owner'):
            raise AccountError('The owner account cannot be removed.')
        data['admins'] = [a for a in data['admins'] if a['id'] != target_id]
        data['signin_links'] = [link for link in data['signin_links'] if link['admin_id'] != target_id]
        data['challenges'] = {key: challenge for key, challenge in data['challenges'].items()
                              if challenge.get('subject') != target_id}
    _update_data(revoke)
    return jsonify(success=True)


@passkey_bp.route('/admin/accounts/sessions/revoke', methods=['POST'])
@admin_required
def revoke_sessions():
    current = get_current_admin()
    target_id = _body().get('admin_id') or current['id']
    if target_id != current['id'] and not current.get('is_owner'):
        return _error('Only the owner can sign out other administrators.', 403)
    def revoke(data):
        target = next((a for a in data['admins'] if a['id'] == target_id), None)
        if not target:
            raise AccountError('Administrator not found.')
        target['auth_version'] = target.get('auth_version', 0) + 1
        data['signin_links'] = [link for link in data['signin_links'] if link['admin_id'] != target_id]
    _update_data(revoke)
    if target_id == current['id']:
        session.clear()
    return jsonify(success=True, signed_out=target_id == current['id'])


@passkey_bp.route('/admin/invites')
@owner_required
def list_invites():
    data = _load_data()
    return jsonify(invites=[item for item in data['invites'] if not _expires(item)])


@passkey_bp.route('/admin/invites/create', methods=['POST'])
@owner_required
def create_invite():
    body = _body()
    name = _name(body.get('name'), 'New administrator')
    token = secrets.token_urlsafe(32)
    invite = {'token': token, 'created_by': session['admin_id'], 'created_at': _now(), 'name': name,
              'expires_at': (datetime.now(timezone.utc) + timedelta(days=INVITE_EXPIRY_DAYS)).isoformat()}
    def create(data):
        _clean_expired_invites(data)
        data['invites'].append(invite)
    _update_data(create)
    return jsonify(success=True, token=token, url=url_for('passkey.invite_page', token=token, _external=True))


@passkey_bp.route('/admin/invites/delete', methods=['POST'])
@owner_required
def delete_invite():
    token = _body().get('token')
    def remove(data):
        data['invites'] = [item for item in data['invites'] if item['token'] != token]
    _update_data(remove)
    return jsonify(success=True)


@passkey_bp.route('/admin/invite/<token>')
def invite_page(token):
    invite = next((item for item in _load_data()['invites'] if item['token'] == token and not _expires(item)), None)
    return render_template('admin_invite.html', token=token, invite=invite,
        error=None if invite else 'This invitation expired or was already used. Ask the owner for a new link.'), 200 if invite else 410


@passkey_bp.route('/admin/invite/<token>/register/options', methods=['POST'])
def invite_register_options(token):
    invite = next((item for item in _load_data()['invites'] if item['token'] == token and not _expires(item)), None)
    if not invite:
        raise AccountError('This invitation expired or was already used.')
    name = _name(_body().get('name'))
    admin_id = str(uuid.uuid4())
    return _issue_challenge(_registration_options(admin_id, name), 'invite', token, admin_id=admin_id, name=name)


@passkey_bp.route('/admin/invite/<token>/register/verify', methods=['POST'])
def invite_register_verify(token):
    challenge = _consume_challenge('invite', token)
    body = _body()
    credential = _credential(_verify_registration(body, challenge), _name(body.get('name'), 'Passkey'))
    admin = {'id': challenge['admin_id'], 'name': challenge['name'], 'is_owner': False,
             'credentials': [credential], 'created_at': _now(), 'last_login_at': _now(), 'auth_version': 0}
    def enroll(data):
        _clean_expired_invites(data)
        if not any(item['token'] == token for item in data['invites']):
            raise AccountError('This invitation expired or was already used.')
        _unique_credential(data, credential)
        data['admins'].append(admin)
        data['invites'] = [item for item in data['invites'] if item['token'] != token]
    _update_data(enroll)
    establish_admin_session(admin)
    return jsonify(success=True, redirect=url_for('admin_dashboard'), message='Account created.')


@passkey_bp.route('/admin/signin-links/create', methods=['POST'])
@owner_required
def create_signin_link():
    admin_id = _body().get('admin_id')
    token = secrets.token_urlsafe(32)
    link = {'id': str(uuid.uuid4()), 'admin_id': admin_id, 'token_hash': hashlib.sha256(token.encode()).hexdigest(),
            'created_by': session['admin_id'], 'created_at': _now(),
            'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=SIGNIN_EXPIRY_MINUTES)).isoformat()}
    def create(data):
        _clean_expired_invites(data)
        if not any(a['id'] == admin_id for a in data['admins']):
            raise AccountError('Administrator not found.')
        data['signin_links'].append(link)
    _update_data(create)
    return jsonify(success=True, id=link['id'], expires_at=link['expires_at'],
                   url=url_for('passkey.signin_link', token=token, _external=True))


@passkey_bp.route('/admin/signin-links/delete', methods=['POST'])
@owner_required
def delete_signin_link():
    link_id = _body().get('id')
    def remove(data):
        data['signin_links'] = [link for link in data['signin_links'] if link['id'] != link_id]
    _update_data(remove)
    return jsonify(success=True)


def _find_signin_link(data, token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return next((link for link in data.get('signin_links', [])
                 if hmac.compare_digest(link['token_hash'], token_hash)
                 and not _expires(link, SIGNIN_EXPIRY_MINUTES)), None)


@passkey_bp.route('/admin/signin/<token>', methods=['GET', 'POST'])
def signin_link(token):
    # GET is a confirmation page so link previews/scanners cannot consume access.
    if request.method == 'GET':
        data = _load_data()
        link = _find_signin_link(data, token)
        admin = next((a for a in data['admins'] if link and a['id'] == link['admin_id']), None)
        return render_template('admin_login.html', signin_link=True, link_admin=admin,
                               link_error=None if admin else 'This sign-in link expired or was already used.'), 200 if admin else 410
    result = {}
    def consume(data):
        link = _find_signin_link(data, token)
        admin = next((a for a in data['admins'] if link and a['id'] == link['admin_id']), None)
        if not admin:
            raise AccountError('This sign-in link expired or was already used.')
        admin['last_login_at'] = _now()
        result.update(admin)
        data['signin_links'] = [item for item in data['signin_links'] if item['id'] != link['id']]
    try:
        _update_data(consume)
    except AccountError:
        return render_template('admin_login.html', signin_link=True,
                               link_error='This sign-in link expired or was already used.'), 410
    establish_admin_session(result)
    return redirect(url_for('passkey.admin_settings'))

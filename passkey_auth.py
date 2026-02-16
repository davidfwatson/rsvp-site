import json
import os
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, current_app, jsonify, request, session, redirect, url_for, render_template, flash
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes

passkey_bp = Blueprint('passkey', __name__)

ADMINS_FILE = os.path.join(os.path.dirname(__file__), 'admins.json')
INVITE_EXPIRY_DAYS = 7


def _load_data():
    """Load admins.json, returning default structure if missing."""
    if not os.path.exists(ADMINS_FILE):
        return {"admins": [], "invites": []}
    with open(ADMINS_FILE, 'r') as f:
        return json.load(f)


def _save_data(data):
    """Atomically save admins.json."""
    temp_file = ADMINS_FILE + '.tmp'
    with open(temp_file, 'w') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_file, ADMINS_FILE)


def get_admin_by_id(admin_id):
    """Look up an admin by their UUID."""
    data = _load_data()
    for admin in data['admins']:
        if admin['id'] == admin_id:
            return admin
    return None


def get_current_admin():
    """Return the current logged-in admin, or None."""
    admin_id = session.get('admin_id')
    if not admin_id:
        return None
    return get_admin_by_id(admin_id)


def admin_required(f):
    """Decorator requiring a logged-in admin (passkey or password-bootstrapped)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_id'):
            return redirect(url_for('admin_login', next=request.url))
        # Verify admin still exists
        if not get_admin_by_id(session['admin_id']):
            session.pop('admin_id', None)
            return redirect(url_for('admin_login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def owner_required(f):
    """Decorator requiring the owner admin."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        admin = get_current_admin()
        if not admin or not admin.get('is_owner'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


def _get_rp_id():
    return current_app.config.get('WEBAUTHN_RP_ID', 'localhost')


def _get_rp_name():
    return current_app.config.get('WEBAUTHN_RP_NAME', 'RSVP Site')


def _get_origin():
    return current_app.config.get('WEBAUTHN_ORIGIN', 'http://localhost:5000')


def _all_credentials():
    """Return a flat list of (admin_id, credential) tuples across all admins."""
    data = _load_data()
    result = []
    for admin in data['admins']:
        for cred in admin.get('credentials', []):
            result.append((admin['id'], cred))
    return result


def _clean_expired_invites(data):
    """Remove invites older than INVITE_EXPIRY_DAYS."""
    cutoff = datetime.utcnow() - timedelta(days=INVITE_EXPIRY_DAYS)
    data['invites'] = [
        inv for inv in data['invites']
        if datetime.fromisoformat(inv['created_at']) > cutoff
    ]


# --- Registration routes (logged-in admin adding a passkey) ---

@passkey_bp.route('/admin/passkey/register/options', methods=['POST'])
@admin_required
def register_options():
    """Generate WebAuthn registration options for the current admin."""
    admin = get_current_admin()
    exclude = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(c['credential_id']))
        for c in admin.get('credentials', [])
    ]

    options = generate_registration_options(
        rp_id=_get_rp_id(),
        rp_name=_get_rp_name(),
        user_id=admin['id'].encode(),
        user_name=admin['name'],
        user_display_name=admin['name'],
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    session['webauthn_challenge'] = bytes_to_base64url(options.challenge)
    return options_to_json(options), 200, {'Content-Type': 'application/json'}


@passkey_bp.route('/admin/passkey/register/verify', methods=['POST'])
@admin_required
def register_verify():
    """Verify and store a new passkey for the current admin."""
    challenge = session.pop('webauthn_challenge', None)
    if not challenge:
        return jsonify({'success': False, 'error': 'No challenge in session'})

    try:
        verification = verify_registration_response(
            credential=request.get_json(),
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=_get_rp_id(),
            expected_origin=_get_origin(),
        )

        data = _load_data()
        admin = next(a for a in data['admins'] if a['id'] == session['admin_id'])
        admin['credentials'].append({
            'credential_id': bytes_to_base64url(verification.credential_id),
            'public_key': bytes_to_base64url(verification.credential_public_key),
            'sign_count': verification.sign_count,
            'name': request.get_json().get('name', 'Passkey'),
        })
        _save_data(data)

        return jsonify({'success': True, 'message': 'Passkey registered'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# --- Authentication routes (public, passkey login) ---

@passkey_bp.route('/admin/passkey/auth/options', methods=['POST'])
def auth_options():
    """Generate WebAuthn authentication options."""
    all_creds = _all_credentials()
    allow = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(cred['credential_id']))
        for _, cred in all_creds
    ]

    options = generate_authentication_options(
        rp_id=_get_rp_id(),
        allow_credentials=allow if allow else None,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    session['webauthn_challenge'] = bytes_to_base64url(options.challenge)
    return options_to_json(options), 200, {'Content-Type': 'application/json'}


@passkey_bp.route('/admin/passkey/auth/verify', methods=['POST'])
def auth_verify():
    """Verify passkey authentication and create session."""
    challenge = session.pop('webauthn_challenge', None)
    if not challenge:
        return jsonify({'success': False, 'error': 'No challenge in session'})

    body = request.get_json()
    credential_id = body.get('id', '')

    # Find matching credential across all admins
    all_creds = _all_credentials()
    matched_admin_id = None
    matched_cred = None
    for admin_id, cred in all_creds:
        if cred['credential_id'] == credential_id:
            matched_admin_id = admin_id
            matched_cred = cred
            break

    if not matched_cred:
        return jsonify({'success': False, 'error': 'Unknown credential'})

    try:
        verification = verify_authentication_response(
            credential=body,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=_get_rp_id(),
            expected_origin=_get_origin(),
            credential_public_key=base64url_to_bytes(matched_cred['public_key']),
            credential_current_sign_count=matched_cred['sign_count'],
        )

        # Update sign count
        data = _load_data()
        for admin in data['admins']:
            if admin['id'] == matched_admin_id:
                for cred in admin['credentials']:
                    if cred['credential_id'] == credential_id:
                        cred['sign_count'] = verification.new_sign_count
                        break
                break
        _save_data(data)

        session['admin_id'] = matched_admin_id
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# --- Passkey management (logged-in admin) ---

@passkey_bp.route('/admin/passkey/list')
@admin_required
def list_passkeys():
    """List the current admin's passkeys."""
    admin = get_current_admin()
    return jsonify({'passkeys': [
        {'credential_id': c['credential_id'], 'name': c.get('name', 'Passkey')}
        for c in admin.get('credentials', [])
    ]})


@passkey_bp.route('/admin/passkey/delete', methods=['POST'])
@admin_required
def delete_passkey():
    """Delete one of the current admin's passkeys."""
    cred_id = request.json.get('credential_id', '')
    data = _load_data()
    admin = next(a for a in data['admins'] if a['id'] == session['admin_id'])
    admin['credentials'] = [c for c in admin['credentials'] if c['credential_id'] != cred_id]
    _save_data(data)
    return jsonify({'success': True})


# --- Admin settings page ---

@passkey_bp.route('/admin/settings')
@admin_required
def admin_settings():
    """Admin settings page with passkey management and invite links."""
    admin = get_current_admin()
    return render_template('admin_settings.html', admin=admin)


# --- Invite management (owner only) ---

@passkey_bp.route('/admin/invites')
@owner_required
def list_invites():
    """Return current invites as JSON."""
    data = _load_data()
    _clean_expired_invites(data)
    _save_data(data)
    return jsonify({'invites': data['invites']})


@passkey_bp.route('/admin/invites/create', methods=['POST'])
@owner_required
def create_invite():
    """Generate a one-time invite token."""
    data = _load_data()
    _clean_expired_invites(data)

    name = request.json.get('name', '') if request.is_json else ''
    token = str(uuid.uuid4())
    data['invites'].append({
        'token': token,
        'created_by': session['admin_id'],
        'created_at': datetime.utcnow().isoformat(),
        'name': name,
    })
    _save_data(data)

    invite_url = url_for('passkey.invite_page', token=token, _external=True)
    return jsonify({'success': True, 'token': token, 'url': invite_url})


@passkey_bp.route('/admin/invites/delete', methods=['POST'])
@owner_required
def delete_invite():
    """Delete an invite token."""
    token = request.json.get('token', '')
    data = _load_data()
    data['invites'] = [inv for inv in data['invites'] if inv['token'] != token]
    _save_data(data)
    return jsonify({'success': True})


# --- Invite landing page (public) ---

@passkey_bp.route('/admin/invite/<token>')
def invite_page(token):
    """Public invite landing page where invitee registers a passkey."""
    data = _load_data()
    _clean_expired_invites(data)
    _save_data(data)

    invite = next((inv for inv in data['invites'] if inv['token'] == token), None)
    if not invite:
        return render_template('admin_invite.html', error='This invite link is invalid or has expired.')

    return render_template('admin_invite.html', token=token, invite=invite)


@passkey_bp.route('/admin/invite/<token>/register/options', methods=['POST'])
def invite_register_options(token):
    """Generate registration options for an invitee."""
    data = _load_data()
    _clean_expired_invites(data)

    invite = next((inv for inv in data['invites'] if inv['token'] == token), None)
    if not invite:
        return jsonify({'success': False, 'error': 'Invalid or expired invite'}), 400

    body = request.get_json() or {}
    invitee_name = body.get('name', 'Admin')

    # Generate a temporary user ID for registration
    user_id = str(uuid.uuid4())
    session['invite_user_id'] = user_id
    session['invite_user_name'] = invitee_name
    session['invite_token'] = token

    options = generate_registration_options(
        rp_id=_get_rp_id(),
        rp_name=_get_rp_name(),
        user_id=user_id.encode(),
        user_name=invitee_name,
        user_display_name=invitee_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    session['webauthn_challenge'] = bytes_to_base64url(options.challenge)
    return options_to_json(options), 200, {'Content-Type': 'application/json'}


@passkey_bp.route('/admin/invite/<token>/register/verify', methods=['POST'])
def invite_register_verify(token):
    """Verify invitee's passkey and create their admin account."""
    challenge = session.pop('webauthn_challenge', None)
    if not challenge:
        return jsonify({'success': False, 'error': 'No challenge in session'})

    if session.get('invite_token') != token:
        return jsonify({'success': False, 'error': 'Token mismatch'})

    data = _load_data()
    _clean_expired_invites(data)
    invite = next((inv for inv in data['invites'] if inv['token'] == token), None)
    if not invite:
        return jsonify({'success': False, 'error': 'Invalid or expired invite'})

    try:
        verification = verify_registration_response(
            credential=request.get_json(),
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=_get_rp_id(),
            expected_origin=_get_origin(),
        )

        admin_id = session.pop('invite_user_id')
        admin_name = session.pop('invite_user_name', 'Admin')
        session.pop('invite_token', None)

        # Create new admin
        new_admin = {
            'id': admin_id,
            'name': admin_name,
            'is_owner': False,
            'credentials': [{
                'credential_id': bytes_to_base64url(verification.credential_id),
                'public_key': bytes_to_base64url(verification.credential_public_key),
                'sign_count': verification.sign_count,
                'name': request.get_json().get('name', 'Passkey'),
            }],
            'created_at': datetime.utcnow().isoformat(),
        }
        data['admins'].append(new_admin)

        # Consume the invite token
        data['invites'] = [inv for inv in data['invites'] if inv['token'] != token]
        _save_data(data)

        # Log in the new admin
        session['admin_id'] = admin_id
        return jsonify({'success': True, 'message': 'Account created'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

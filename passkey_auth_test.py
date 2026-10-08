"""Account access guarantees that do not need a physical authenticator."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import passkey_auth as auth
from app import app


@pytest.fixture
def client(monkeypatch):
    app.config.update(TESTING=True, CSRF_ENABLED=False, SECRET_KEY='test-only-secret-key')
    auth._save_data({'admins': [
        {'id': 'owner', 'name': 'Owner', 'is_owner': True, 'credentials': [], 'auth_version': 0},
        {'id': 'member', 'name': 'Member', 'is_owner': False, 'credentials': [
            {'credential_id': 'a2V5', 'public_key': 'cHVibGlj', 'sign_count': 0, 'name': 'Phone'}], 'auth_version': 0},
    ], 'invites': [], 'signin_links': [], 'challenges': {}})
    with app.test_client() as client:
        yield client


def sign_in(client, admin_id='owner', version=0):
    with client.session_transaction() as session:
        session['admin_id'] = admin_id
        session['admin_auth_version'] = version


def test_non_owner_cannot_manage_other_accounts(client):
    sign_in(client, 'member')
    assert client.get('/admin/accounts').status_code == 403
    assert client.post('/admin/accounts/update', json={'admin_id': 'owner', 'name': 'Changed'}).status_code == 403
    assert client.post('/admin/invites/create', json={'name': 'New'}).status_code == 403
    assert client.post('/admin/signin-links/create', json={'admin_id': 'member'}).status_code == 403
    assert auth.get_admin_by_id('owner')['name'] == 'Owner'


def test_owner_can_rename_and_revoke_member(client):
    sign_in(client)
    response = client.post('/admin/accounts/update', json={'admin_id': 'member', 'name': 'New name'})
    assert response.json['success']
    assert auth.get_admin_by_id('member')['name'] == 'New name'
    assert client.post('/admin/accounts/revoke', json={'admin_id': 'owner'}).status_code == 400
    assert client.post('/admin/accounts/revoke', json={'admin_id': 'member'}).json['success']
    sign_in(client, 'member')
    assert client.get('/admin/passkey/list').status_code == 401


def test_session_revocation_invalidates_existing_cookie(client):
    sign_in(client, 'member')
    old_cookie = client.get_cookie('session').value
    assert client.post('/admin/accounts/sessions/revoke', json={}).json['signed_out']
    client.set_cookie('session', old_cookie)
    assert client.get('/admin/passkey/list').status_code == 401


def test_last_passkey_is_protected(client):
    sign_in(client, 'member')
    response = client.post('/admin/passkey/delete', json={'credential_id': 'a2V5'})
    assert response.status_code == 400
    assert len(auth.get_admin_by_id('member')['credentials']) == 1
    auth._update_data(lambda data: data['admins'][1]['credentials'].append(
        {'credential_id': 'YmFja3Vw', 'name': 'Backup', 'public_key': 'cHVibGlj', 'sign_count': 0}))
    assert client.post('/admin/passkey/delete', json={'credential_id': 'a2V5'}).json['success']
    assert len(auth.get_admin_by_id('member')['credentials']) == 1


def test_signin_link_is_hashed_one_use_and_get_does_not_consume(client):
    sign_in(client)
    result = client.post('/admin/signin-links/create', json={'admin_id': 'member'}).json
    path = result['url'].replace('http://localhost', '')
    token = path.rsplit('/', 1)[1]
    links = auth._load_data()['signin_links']
    assert 'token' not in links[0]
    assert links[0]['token_hash'] != token
    assert token not in str(links)
    # Viewing does not consume the token (email link scanners may follow GET).
    assert client.get(path).status_code == 200
    assert client.get(path).status_code == 200
    assert len(auth._load_data()['signin_links']) == 1
    response = client.post(path)
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session['admin_id'] == 'member'
    assert not auth._load_data()['signin_links']
    assert client.post(path).status_code == 410


def test_signin_link_revocation_and_expiry(client):
    sign_in(client)
    result = client.post('/admin/signin-links/create', json={'admin_id': 'member'}).json
    path = result['url'].replace('http://localhost', '')
    assert client.post('/admin/signin-links/delete', json={'id': result['id']}).json['success']
    assert client.post(path).status_code == 410
    sign_in(client)
    result = client.post('/admin/signin-links/create', json={'admin_id': 'member'}).json
    path = result['url'].replace('http://localhost', '')
    auth._update_data(lambda data: data['signin_links'][0].update(
        expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()))
    assert client.post(path).status_code == 410


def test_invite_revoked_during_registration_cannot_enroll(client, monkeypatch):
    sign_in(client)
    token = client.post('/admin/invites/create', json={'name': 'New member'}).json['token']
    assert client.post(f'/admin/invite/{token}/register/options', json={'name': 'New member'}).status_code == 200
    assert client.post('/admin/invites/delete', json={'token': token}).json['success']
    monkeypatch.setattr(auth, 'verify_registration_response', Mock(return_value=SimpleNamespace(
        credential_id=b'new-credential', credential_public_key=b'public', sign_count=0)))
    assert client.post(f'/admin/invite/{token}/register/verify', json={'name': 'Phone'}).status_code == 400
    assert len(auth._load_data()['admins']) == 2


def test_invite_enrollment_is_atomic_and_one_use(client, monkeypatch):
    sign_in(client)
    token = client.post('/admin/invites/create', json={'name': 'New member'}).json['token']
    assert client.post(f'/admin/invite/{token}/register/options', json={'name': 'New member'}).status_code == 200
    cookie = client.get_cookie('session').value
    verifier = Mock(return_value=SimpleNamespace(credential_id=b'new-credential', credential_public_key=b'public', sign_count=0))
    monkeypatch.setattr(auth, 'verify_registration_response', verifier)
    assert client.post(f'/admin/invite/{token}/register/verify', json={'name': 'Phone'}).json['success']
    assert verifier.call_args.kwargs['require_user_verification'] is True
    assert not auth._load_data()['invites']
    client.set_cookie('session', cookie)
    assert client.post(f'/admin/invite/{token}/register/verify', json={'name': 'Phone'}).status_code == 400
    assert len(auth._load_data()['admins']) == 3
    assert verifier.call_count == 1


def test_auth_challenge_expiry_and_type_binding(client, monkeypatch):
    sign_in(client, 'member')
    assert client.post('/admin/passkey/register/options', json={}).status_code == 200
    verifier = Mock()
    monkeypatch.setattr(auth, 'verify_authentication_response', verifier)
    assert client.post('/admin/passkey/auth/verify', json={'id': 'a2V5'}).status_code == 400
    verifier.assert_not_called()
    assert client.post('/admin/passkey/auth/options', json={}).status_code == 200
    auth._update_data(lambda data: next(iter(data['challenges'].values())).update(issued_at=0))
    assert client.post('/admin/passkey/auth/verify', json={'id': 'a2V5'}).status_code == 400
    verifier.assert_not_called()


def test_auth_challenge_cannot_replay_signed_cookie(client, monkeypatch):
    assert client.post('/admin/passkey/auth/options', json={}).status_code == 200
    cookie = client.get_cookie('session').value
    verifier = Mock(return_value=SimpleNamespace(new_sign_count=1))
    monkeypatch.setattr(auth, 'verify_authentication_response', verifier)
    response = client.post('/admin/passkey/auth/verify', json={'id': 'a2V5', 'next': 'https://attacker.example/'})
    assert response.json['success']
    assert response.json['redirect'] == '/admin'
    assert verifier.call_args.kwargs['require_user_verification'] is True
    assert auth.get_admin_by_id('member')['credentials'][0]['sign_count'] == 1
    client.set_cookie('session', cookie)
    assert client.post('/admin/passkey/auth/verify', json={'id': 'a2V5'}).status_code == 400
    assert verifier.call_count == 1


@pytest.mark.parametrize('next_url', ['//attacker.example', 'https://attacker.example', '/\\attacker.example', '/admin\n', '/somewhere', 'http://[', '//[', None])
def test_redirect_rejects_external_or_non_admin_destinations(next_url):
    with app.test_request_context():
        assert auth.safe_admin_next(next_url) == '/admin'


def test_redirect_accepts_local_admin_url():
    with app.test_request_context():
        assert auth.safe_admin_next('/admin/event?tab=guests') == '/admin/event?tab=guests'


def test_csrf_rejects_authenticated_account_mutation(client):
    sign_in(client)
    app.config['CSRF_ENABLED'] = True
    try:
        response = client.post('/admin/accounts/update', json={'name': 'Forged'})
        assert response.status_code == 400
        assert auth.get_admin_by_id('owner')['name'] == 'Owner'
    finally:
        app.config['CSRF_ENABLED'] = False


@pytest.mark.parametrize('origin,verified_user,valid_signature,expected_status', [
    ('http://localhost:5000', True, True, 200),
    ('https://attacker.example', True, True, 400),
    ('http://localhost:5000', False, True, 400),
    ('http://localhost:5000', True, False, 400),
])
def test_real_webauthn_assertions_require_origin_uv_and_signature(client, origin, verified_user, valid_signature, expected_status):
    import hashlib
    import json
    import cbor2
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    numbers = private_key.public_key().public_numbers()
    cose_key = cbor2.dumps({1: 2, 3: -7, -1: 1,
                           -2: numbers.x.to_bytes(32, 'big'), -3: numbers.y.to_bytes(32, 'big')})
    auth._update_data(lambda data: data['admins'][1]['credentials'][0].update(public_key=auth.bytes_to_base64url(cose_key)))
    options = client.post('/admin/passkey/auth/options', json={}).json
    client_data = json.dumps({'type': 'webauthn.get', 'challenge': options['challenge'], 'origin': origin}).encode()
    authenticator_data = hashlib.sha256(b'localhost').digest() + bytes([5 if verified_user else 1]) + (1).to_bytes(4, 'big')
    signer = private_key if valid_signature else ec.generate_private_key(ec.SECP256R1())
    signature = signer.sign(authenticator_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
    body = {'id': 'a2V5', 'rawId': 'a2V5', 'type': 'public-key', 'response': {
        'clientDataJSON': auth.bytes_to_base64url(client_data),
        'authenticatorData': auth.bytes_to_base64url(authenticator_data),
        'signature': auth.bytes_to_base64url(signature)}}
    response = client.post('/admin/passkey/auth/verify', json=body)
    assert response.status_code == expected_status
    assert auth.get_admin_by_id('member')['credentials'][0]['sign_count'] == (1 if expected_status == 200 else 0)
    with client.session_transaction() as session:
        assert session.get('admin_id') == ('member' if expected_status == 200 else None)


def test_legacy_non_discoverable_credentials_remain_allowed(client):
    options = client.post('/admin/passkey/auth/options', json={}).json
    assert options['allowCredentials'][0]['id'] == 'a2V5'
    assert options['userVerification'] == 'required'


def test_new_passkeys_require_discovery_and_device_verification(client):
    sign_in(client)
    options = client.post('/admin/passkey/register/options', json={}).json
    assert options['authenticatorSelection']['residentKey'] == 'required'
    assert options['authenticatorSelection']['userVerification'] == 'required'


def test_owner_bootstrap_is_atomic_under_concurrent_requests(client):
    from concurrent.futures import ThreadPoolExecutor
    auth._save_data({'admins': [], 'invites': [], 'signin_links': [], 'challenges': {}})
    with ThreadPoolExecutor(max_workers=4) as executor:
        owners = list(executor.map(lambda _: auth.bootstrap_owner(), range(12)))
    assert len({owner['id'] for owner in owners}) == 1
    assert len(auth._load_data()['admins']) == 1


def test_concurrent_signin_link_consumption_only_signs_in_once(client):
    from concurrent.futures import ThreadPoolExecutor
    sign_in(client)
    result = client.post('/admin/signin-links/create', json={'admin_id': 'member'}).json
    path = result['url'].replace('http://localhost', '')
    def consume(_):
        with app.test_client() as another_client:
            return another_client.post(path).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(consume, range(2)))
    assert sorted(statuses) == [302, 410]
    assert not auth._load_data()['signin_links']


def test_settings_and_login_render_the_shared_csrf_contract(client):
    assert b'name="csrf-token"' in client.get('/admin/login').data
    assert b'Owner recovery' in client.get('/admin/login').data
    sign_in(client)
    response = client.get('/admin/settings')
    assert response.status_code == 200
    assert b'Workspace members' in response.data
    assert b'All changes saved' in response.data
    sign_in(client, 'member')
    response = client.get('/admin/settings')
    assert response.status_code == 200
    assert b'Workspace members' not in response.data


def test_csrf_token_rotates_after_successful_authentication(client, monkeypatch):
    app.config['CSRF_ENABLED'] = True
    try:
        client.get('/admin/login')
        with client.session_transaction() as session:
            token = session['_csrf_token']
            session['pre_auth_data'] = 'must-not-survive'
        headers = {'X-CSRF-Token': token}
        assert client.post('/admin/passkey/auth/options', json={}, headers=headers).status_code == 200
        monkeypatch.setattr(auth, 'verify_authentication_response', Mock(return_value=SimpleNamespace(new_sign_count=1)))
        assert client.post('/admin/passkey/auth/verify', json={'id': 'a2V5'}, headers=headers).json['success']
        with client.session_transaction() as session:
            assert session['admin_id'] == 'member'
            assert 'pre_auth_data' not in session
            assert '_csrf_token' not in session
        assert client.post('/admin/accounts/update', json={'name': 'Forged'}, headers=headers).status_code == 400
        client.get('/admin/settings')
        with client.session_transaction() as session:
            fresh_token = session['_csrf_token']
        assert fresh_token != token
        assert client.post('/admin/accounts/update', json={'name': 'New name'}, headers={'X-CSRF-Token': fresh_token}).json['success']
    finally:
        app.config['CSRF_ENABLED'] = False

"""Native app regression tests against real isolated event/account stores."""
import base64
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

import app as web
import passkey_auth as auth
from event_config import get_event_config, save_event_config
from mobile_api import android_origins


EVENT = dict(id='native123', slug='garden-party', name='Garden party', date='2027-06-12',
             start_time='6:00 PM', end_time='9:00 PM', location='The garden',
             description='Come **celebrate**.', max_guests_per_invite=5, color_scheme='pink',
             private_metadata='not-public', version=0, show_attendees=True)
GUEST = dict(name='Alex Guest', email='alex@example.test', attending='yes',
             num_adults=2, num_children=1, dietary_restrictions='Private diet', comment='Private note')
PREFIX = '/api/mobile'


@pytest.fixture
def client(monkeypatch):
    """Exercise real CSRF even though legacy fixtures disable it by default."""
    monkeypatch.setitem(web.app.config, 'CSRF_ENABLED', True)
    monkeypatch.setitem(web.app.config, 'ADMIN_PASSWORD', 'test-mobile-password')
    monkeypatch.setitem(web.app.config, 'ANDROID_SHA256_CERT_FINGERPRINTS', '')
    save_event_config([dict(EVENT)])
    return web.app.test_client()


def csrf(client):
    """Bootstrap the same native session endpoint used by both apps."""
    return {'X-CSRF-Token': client.get(PREFIX + '/session').json['csrf_token']}


def login(client):
    """Use owner recovery to exercise real account creation and cookie rotation."""
    result = client.post(PREFIX + '/login', json={'password': 'test-mobile-password'}, headers=csrf(client))
    assert result.status_code == 200
    return {'X-CSRF-Token': result.json['csrf_token']}


def test_session_bootstrap_and_login_rotate_csrf_and_exclude_credentials(client):
    headers = csrf(client)
    assert client.get(PREFIX + '/session').json['admin'] is None
    assert client.post(PREFIX + '/login', json={'password': 'test-mobile-password'}).status_code == 400
    result = client.post(PREFIX + '/login', json={'password': 'test-mobile-password'}, headers=headers)
    assert result.status_code == 200 and result.json['admin']['is_owner']
    assert result.json['csrf_token'] != headers['X-CSRF-Token']
    assert 'credentials' not in result.json['admin']
    assert client.post(PREFIX + '/logout', json={}, headers=headers).status_code == 400
    assert client.post(PREFIX + '/logout', json={}, headers=csrf(client)).json['admin'] is None
    assert client.get(PREFIX + '/events').status_code == 401


def test_mobile_host_paths_always_require_auth_and_return_json(client):
    for path in ('/events', '/events/garden-party', '/events/garden-party/export'):
        result = client.get(PREFIX + path)
        assert result.status_code == 401 and result.is_json
    for path in ('/events/garden-party/invite', '/events/garden-party/upload'):
        assert client.post(PREFIX + path, json={}, headers=csrf(client)).status_code == 401


def test_development_hostname_fallback_cannot_disclose_an_invitation(client):
    """A guessed localhost prefix is not a public invitation address."""
    for path in ('/localhost-guess', PREFIX + '/invitations/localhost-guess'):
        result = client.get(path)
        assert result.status_code == 404 and b'Garden party' not in result.data
    login(client)
    assert client.get(PREFIX + '/events/localhost-guess').status_code == 404


def test_host_create_edit_conflict_archive_restore_and_immutable_metadata(client):
    headers = login(client)
    events = client.get(PREFIX + '/events').json['events']
    assert events[0]['start_time'] == '18:00' and events[0]['end_time'] == '21:00'
    assert 'private_metadata' not in events[0]
    result = client.post(PREFIX + '/events', json=dict(name='New picnic', date='2027-08-01',
                        start_time='17:00', location='The park'), headers=headers)
    assert result.status_code == 201 and result.json['event']['slug'] == 'new-picnic'
    patch = dict(version=0, name='Garden dinner', id='attack', slug='attack', archived=True)
    changed = client.patch(PREFIX + '/events/garden-party', json=patch, headers=headers)
    assert changed.status_code == 200
    event = get_event_config('garden-party')
    assert event['id'] == EVENT['id'] and event['slug'] == EVENT['slug']
    assert event['private_metadata'] == 'not-public' and event['version'] == 1
    assert client.patch(PREFIX + '/events/garden-party', json=patch, headers=headers).status_code == 409
    assert client.get(PREFIX + '/invitations/garden-party').status_code == 404
    assert client.post(PREFIX + '/events/garden-party/invite', json={'email': 'a@example.test'}, headers=headers).status_code == 400
    assert client.patch(PREFIX + '/events/garden-party', json={'version': 1, 'archived': False}, headers=headers).status_code == 200
    assert client.get(PREFIX + '/invitations/garden-party').status_code == 200


def test_legacy_human_readable_dates_and_times_are_normalized(client):
    save_event_config([dict(EVENT, date='June 12, 2027', start_time='6pm')])
    result = client.get(PREFIX + '/invitations/garden-party').json['event']
    assert result['date'] == '2027-06-12' and result['start_time'] == '18:00'


@pytest.mark.parametrize('values', [[], None, {'version': True}, {'version': 0.5}, {'version': -1},
                                  {'version': 0, 'max_guests_per_invite': 1.8},
                                  {'version': 0, 'background_image': 'https://evil.test/a.png'}])
def test_bad_event_edits_never_change_data(client, values):
    headers = login(client)
    assert client.patch(PREFIX + '/events/garden-party', json=values, headers=headers).status_code == 400
    assert get_event_config('garden-party')['version'] == 0


def test_new_and_duplicate_guest_responses_preserve_private_edit_capability(client):
    headers = csrf(client)
    first = client.post(PREFIX + '/invitations/garden-party/rsvp', json=GUEST, headers=headers)
    assert first.status_code == 201 and first.json['email_delivered'] is False
    token = first.json['response']['token']
    assert first.json['update_url'].endswith('/garden-party/update-rsvp/' + token)
    duplicate = client.post(PREFIX + '/invitations/garden-party/rsvp', json={**GUEST, 'name': 'Attacker', 'attending': 'no'}, headers=headers)
    assert duplicate.json == {'check_email': True, 'email_delivered': False}
    assert token not in duplicate.get_data(as_text=True) and 'Private diet' not in duplicate.get_data(as_text=True)
    path = PREFIX + '/invitations/garden-party/responses/' + token
    assert client.get(path).json['response']['name'] == GUEST['name']
    updated = client.patch(path, json={'attending': 'no'}, headers=headers)
    assert updated.json['response']['num_adults'] == 0
    assert updated.json['response']['token'] == token
    assert client.get(PREFIX + '/invitations/garden-party/responses/forged').status_code == 404
    assert client.get(PREFIX + '/invitations/garden-party/responses/%C3%A9').status_code == 404


def test_public_list_host_list_and_export_do_not_disclose_edit_tokens(client):
    created = client.post(PREFIX + '/invitations/garden-party/rsvp', json=GUEST, headers=csrf(client)).json
    token = created['response']['token']
    public = client.get(PREFIX + '/invitations/garden-party')
    assert public.json['attendees'] == [dict(first_name='Alex', last_initial='G', guest_info=' +2')]
    assert 'stats' not in public.json['event']
    assert 'alex@example.test' not in public.get_data(as_text=True) and token not in public.get_data(as_text=True)
    login(client)
    host = client.get(PREFIX + '/events/garden-party')
    assert host.json['event']['stats']['attending'] == 3
    assert host.json['rsvps'][0]['email'] == GUEST['email'] and token not in host.get_data(as_text=True)
    export = client.get(PREFIX + '/events/garden-party/export')
    assert export.status_code == 200 and token not in export.get_data(as_text=True)


def test_legacy_responses_have_all_native_required_fields(client):
    web.save_rsvps(EVENT['id'], [dict(name='Legacy guest', email='legacy@example.test', attending='yes', token='private-key')])
    login(client)
    response = client.get(PREFIX + '/events/garden-party').json['rsvps'][0]
    assert response['num_adults'] == 1 and response['num_children'] == 0
    assert response['dietary_restrictions'] == '' and response['comment'] == ''
    assert 'token' not in response


def test_response_email_collision_rejected_and_numeric_counts_not_truncated(client):
    headers = csrf(client)
    one = client.post(PREFIX + '/invitations/garden-party/rsvp', json=GUEST, headers=headers).json
    client.post(PREFIX + '/invitations/garden-party/rsvp', json={**GUEST, 'email': 'two@example.test'}, headers=headers)
    path = PREFIX + '/invitations/garden-party/responses/' + one['response']['token']
    assert client.patch(path, json={'email': 'two@example.test'}, headers=headers).status_code == 400
    assert client.post(PREFIX + '/invitations/garden-party/rsvp', json={**GUEST, 'num_adults': 1.1}, headers=headers).status_code == 400
    assert client.get(path).json['response']['email'] == GUEST['email']


def test_mobile_signin_is_csrf_protected_single_use_and_revocable(client):
    headers = login(client)
    owner = client.get(PREFIX + '/session').json['admin']['id']
    created = client.post('/admin/signin-links/create', json={'admin_id': owner}, headers=headers).json
    token = created['url'].rsplit('/', 1)[-1]
    client.post(PREFIX + '/logout', json={}, headers=headers)
    assert client.get(PREFIX + '/signin?token=' + token).status_code == 405
    assert len(auth._load_data()['signin_links']) == 1
    assert client.post(PREFIX + '/signin', json={'token': token}).status_code == 400
    result = client.post(PREFIX + '/signin', json={'token': token}, headers=csrf(client))
    assert result.status_code == 200 and result.json['admin']['id'] == owner
    assert client.post(PREFIX + '/signin', json={'token': token}, headers=csrf(client)).status_code == 400
    old_cookie = client.get_cookie('session').value
    client.post('/admin/accounts/sessions/revoke', json={}, headers=csrf(client))
    client.set_cookie('session', old_cookie)
    assert client.get(PREFIX + '/events').status_code == 401


def test_mobile_image_upload_and_email_failure_are_real_results(client):
    headers = login(client)
    buffer = BytesIO()
    Image.new('RGB', (12, 12), 'red').save(buffer, 'PNG')
    image = client.post(PREFIX + '/events/garden-party/upload', data={'image': (BytesIO(buffer.getvalue()), 'party.png')}, headers=headers)
    assert image.status_code == 200
    assert client.get(image.json['url']).status_code == 200
    assert client.post(PREFIX + '/events/garden-party/invite', json={'email': 'a@example.test'}, headers=headers).status_code == 503


def test_association_documents_match_release_identity_and_never_guess_android_cert(client, monkeypatch):
    aasa = client.get('/.well-known/apple-app-site-association')
    assert aasa.status_code == 200 and aasa.is_json
    assert aasa.json['webcredentials']['apps'] == ['2FZS79QCFD.com.davidfwatson.partymail']
    assert client.get('/.well-known/assetlinks.json').json == []
    fingerprint = '12' * 32
    monkeypatch.setitem(web.app.config, 'ANDROID_SHA256_CERT_FINGERPRINTS', fingerprint)
    dal = client.get('/.well-known/assetlinks.json').json[0]
    assert dal['target']['package_name'] == 'com.davidfwatson.partymail'
    assert dal['target']['sha256_cert_fingerprints'] == [':'.join(['12'] * 32)]
    assert android_origins(web.app.config) == ['android:apk-key-hash:' + base64.urlsafe_b64encode(bytes.fromhex(fingerprint)).decode().rstrip('=')]
    with pytest.raises(ValueError):
        android_origins({'ANDROID_SHA256_CERT_FINGERPRINTS': 'not-a-fingerprint'})


def test_passkey_verification_trusts_exact_configured_android_origin(client, monkeypatch):
    headers = login(client)
    owner = auth._load_data()['admins'][0]['id']
    auth._update_data(lambda data: data['admins'][0]['credentials'].append(
        dict(credential_id='a2V5', public_key='cHVibGlj', sign_count=0, name='Phone')))
    fingerprint = 'AB' * 32
    monkeypatch.setitem(web.app.config, 'ANDROID_SHA256_CERT_FINGERPRINTS', fingerprint)
    verifier = Mock(return_value=SimpleNamespace(new_sign_count=1))
    monkeypatch.setattr(auth, 'verify_authentication_response', verifier)
    client.post('/admin/passkey/auth/options', json={}, headers=headers)
    result = client.post('/admin/passkey/auth/verify', json={'id': 'a2V5'}, headers=headers)
    assert result.status_code == 200
    assert verifier.call_args.kwargs['expected_origin'] == ['http://localhost:5000', *android_origins(web.app.config)]
    assert client.get(PREFIX + '/session').json['admin']['id'] == owner


def test_api_responses_and_private_paths_have_no_cache_or_analytics(client):
    for path in ('/session', '/invitations/garden-party', '/events'):
        result = client.get(PREFIX + path)
        assert result.headers['Cache-Control'] == 'no-store'
        assert result.headers['Referrer-Policy'] == 'no-referrer'
        assert b'googletagmanager' not in result.data

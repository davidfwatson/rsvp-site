"""Regression coverage for the editor, uploads, privacy, and guest authorization."""
from io import BytesIO
import json

import pytest
from PIL import Image

import app as app_module
from event_config import get_event_config, save_event_config
from export_rsvps import generate_rsvps_csv

EVENT = dict(domain='partymail.app', id='safe123', slug='summer-supper', name='Summer supper', date='2027-06-12', start_time='6:00 PM', end_time='9:00 PM', location='The garden', description='Come celebrate **together**.', max_guests_per_invite=5, color_scheme='pink', custom_metadata='preserved')


@pytest.fixture
def client():
    save_event_config([dict(EVENT)])
    return app_module.app.test_client()


@pytest.fixture
def admin_client(client, monkeypatch):
    import passkey_auth
    monkeypatch.setattr(passkey_auth, '_load_data', lambda: dict(admins=[dict(id='test-admin', name='Test host', is_owner=True)], invites=[]))
    with client.session_transaction() as session:
        session['admin_id'] = 'test-admin'
    return client


def test_autosave_preserves_metadata_and_rejects_stale_window(admin_client):
    """A stale editor must never overwrite newer server data."""
    payload = {**EVENT, 'version': 0, 'name': 'A new name', 'id': 'overwrite-attempt'}
    first = admin_client.post('/admin/summer-supper/save', json=payload)
    assert first.status_code == 200
    assert first.json['version'] == 1
    event = get_event_config('summer-supper')
    assert event['id'] == EVENT['id'] and event['custom_metadata'] == 'preserved'
    stale = admin_client.post('/admin/summer-supper/save', json={**payload, 'name': 'Stale overwrite'})
    assert stale.status_code == 409
    assert get_event_config('summer-supper')['name'] == 'A new name'


@pytest.mark.parametrize('change', [dict(max_guests_per_invite=-1), dict(accent_color='red;display:none'), dict(cover_image='https://example.com/image'), dict(name=''), dict(background_style='malicious')])
def test_editor_invalid_input_does_not_write(admin_client, change):
    """Invalid drafts leave the persisted event intact."""
    response = admin_client.post('/admin/summer-supper/save', json={**EVENT, 'version': 0, **change})
    assert response.status_code == 400
    assert get_event_config('summer-supper')['name'] == EVENT['name']


def test_preview_is_sanitized_and_does_not_write(admin_client):
    """Preview renders the guest page without persisting or loading analytics."""
    response = admin_client.post('/admin/summer-supper/preview', json={**EVENT, 'description': '<script>alert(1)</script>\n[Click](javascript:alert(1))', 'name': 'Preview name'})
    assert response.status_code == 200
    assert b'Preview name' in response.data
    assert b'<script>alert(1)</script>' not in response.data
    assert b'href="javascript:' not in response.data
    assert b'analytics-config' not in response.data
    assert b'data-preview="true"' in response.data
    assert get_event_config('summer-supper')['name'] == EVENT['name']


def test_image_upload_is_validated_reencoded_and_metadata_stripped(admin_client):
    """Uploaded images become bounded WebP files with no EXIF data."""
    buffer = BytesIO()
    original = Image.new('RGB', (80, 50), 'orange')
    exif = Image.Exif(); exif[270] = 'private metadata'
    original.save(buffer, 'JPEG', exif=exif)
    response = admin_client.post('/admin/summer-supper/upload', data={'image': (BytesIO(buffer.getvalue()), '../../photo.jpg')})
    assert response.status_code == 200 and response.json['url'].startswith('/media/')
    image_response = admin_client.get(response.json['url'])
    with Image.open(BytesIO(image_response.data)) as cleaned:
        assert cleaned.format == 'WEBP' and not cleaned.getexif()
    bad = admin_client.post('/admin/summer-supper/upload', data={'image': (BytesIO(b'<svg onload="alert(1)"></svg>'), 'picture.png')})
    assert bad.status_code == 400
    assert admin_client.get('/media/private.json').status_code == 404


def test_csrf_required_for_editor_and_upload(admin_client, monkeypatch):
    """Both JSON mutations and multipart uploads require the session CSRF token."""
    monkeypatch.setitem(app_module.app.config, 'CSRF_ENABLED', True)
    assert admin_client.post('/admin/summer-supper/save', json={**EVENT, 'version': 0}).status_code == 400
    admin_client.get('/admin/summer-supper')
    with admin_client.session_transaction() as session:
        token = session['_csrf_token']
    assert admin_client.post('/admin/summer-supper/save', json={**EVENT, 'version': 0}, headers={'X-CSRF-Token': token}).status_code == 200
    assert admin_client.post('/admin/summer-supper/upload', data={'image': (BytesIO(b'bad'), 'a.jpg')}).status_code == 400


def test_repeat_email_cannot_overwrite_or_disclose_existing_rsvp(client):
    """Only possession of the private edit link authorizes an RSVP change."""
    guest = dict(name='Private Guest', email='private@example.com', attending='yes', num_adults='2', num_children='1', dietary_restrictions='private diet')
    first = client.post('/summer-supper/rsvp', data=guest)
    assert first.location.endswith('/summer-supper/thank-you') and '?' not in first.location
    stored = app_module.load_rsvps(EVENT['id'])[0]
    forged = client.post('/summer-supper/rsvp', data={**guest, 'name': 'Attacker', 'attending': 'no'})
    assert forged.status_code == 302
    assert app_module.load_rsvps(EVENT['id'])[0] == stored
    html = client.get(forged.location).get_data(as_text=True)
    assert 'Private Guest' not in html and 'private diet' not in html
    updated = client.post('/summer-supper/update-rsvp/' + stored['token'], data=dict(attending='no'))
    assert updated.status_code == 302
    assert app_module.load_rsvps(EVENT['id'])[0]['attending'] == 'no'


@pytest.mark.parametrize('changes', [dict(attending='maybe'), dict(num_adults='0'), dict(num_children='-1'), dict(num_adults='99'), dict(num_adults='not-a-number'), dict(email='invalid')])
def test_invalid_rsvp_never_writes(client, changes):
    response = client.post('/summer-supper/rsvp', data={**dict(name='Guest', email='a@example.com', attending='yes', num_adults='1', num_children='0'), **changes})
    assert response.status_code == 400
    assert app_module.load_rsvps(EVENT['id']) == []


def test_analytics_never_runs_on_private_admin_preview_or_update_pages(admin_client, monkeypatch):
    monkeypatch.setitem(app_module.app.config, 'GA_MEASUREMENT_ID', 'G-52ZJ7PXYEC')
    public = admin_client.get('/summer-supper?email=private@example.com&token=private').get_data(as_text=True)
    assert 'analytics-config' in public
    assert 'private@example.com' not in public and 'token=private' not in public
    for path in ['/admin', '/admin/summer-supper', '/admin/settings', '/admin/summer-supper/preview']:
        assert 'analytics-config' not in admin_client.get(path).get_data(as_text=True)
    app_module.save_rsvps(EVENT['id'], [dict(name='Guest', email='a@example.com', token='secret-token', attending='yes', num_adults=1, num_children=0)])
    assert 'analytics-config' not in admin_client.get('/summer-supper/update-rsvp/secret-token').get_data(as_text=True)


def test_csv_excludes_private_tokens_and_neutralizes_formula_values():
    csv = generate_rsvps_csv([dict(name='=HYPERLINK("evil")', email='a@example.com', comment='  @malicious', token='private-edit-key')])
    assert 'Token' not in csv and 'private-edit-key' not in csv
    assert "'=HYPERLINK" in csv and "'  @malicious" in csv


def test_email_oauth_requires_owner_session_and_state(client, admin_client):
    """An unsolicited callback cannot install sending credentials."""
    response = admin_client.get('/oauth2callback?state=forged&code=forged')
    assert response.status_code == 400


def test_malformed_and_unicode_requests_fail_cleanly(client, admin_client, monkeypatch):
    """User-supplied Unicode and nonobject JSON must never cause server errors."""
    assert client.post('/admin/login', data=dict(password='é')).status_code == 200
    assert admin_client.post('/admin/summer-supper/preview', json=['invalid']).status_code == 400
    assert client.get('/summer-supper/update-rsvp/%C3%A9').status_code == 404
    monkeypatch.setitem(app_module.app.config, 'CSRF_ENABLED', True)
    admin_client.get('/admin/summer-supper')
    assert admin_client.post('/admin/summer-supper/save', json={**EVENT, 'version': 0}, headers={'X-CSRF-Token':'é'}).status_code == 400


def test_private_update_cannot_collide_with_another_response(client):
    """Email deduplication survives changes through authorized edit links."""
    responses = [dict(name='One', email='one@example.com', token='one-token', attending='yes', num_adults=1, num_children=0), dict(name='Two', email='two@example.com', token='two-token', attending='yes', num_adults=1, num_children=0)]
    app_module.save_rsvps(EVENT['id'], responses)
    assert client.post('/summer-supper/update-rsvp/one-token', data=dict(email='two@example.com',attending='yes')).status_code == 400
    assert app_module.load_rsvps(EVENT['id']) == responses


@pytest.mark.parametrize('bad_image', [0, False, {}, []])
def test_editor_requires_string_image_paths(admin_client, bad_image):
    assert admin_client.post('/admin/summer-supper/save', json={**EVENT, 'version': 0, 'cover_image':bad_image}).status_code == 400


def test_transparent_upload_retains_alpha(admin_client):
    buffer = BytesIO()
    Image.new('RGBA', (20, 20), (255, 0, 0, 0)).save(buffer, 'PNG')
    result = admin_client.post('/admin/summer-supper/upload', data={'image':(BytesIO(buffer.getvalue()), 'transparent.png')})
    assert result.status_code == 200
    with Image.open(BytesIO(admin_client.get(result.json['url']).data)) as image:
        assert 'A' in image.getbands() and image.getpixel((0,0))[-1] == 0


def test_policy_pages_are_public_and_linked_from_the_landing_page(client, monkeypatch):
    """Google's consent screen links to these; they must load without a session."""
    monkeypatch.setitem(app_module.app.config, 'CONTACT_EMAIL', 'hello@example.test')
    landing = client.get('/').get_data(as_text=True)
    assert 'href="/privacy"' in landing and 'href="/terms"' in landing
    privacy = client.get('/privacy')
    assert privacy.status_code == 200
    text = privacy.get_data(as_text=True)
    assert 'gmail.send' in text and 'Limited Use' in text and 'mailto:hello@example.test' in text
    terms = client.get('/terms')
    assert terms.status_code == 200 and 'Terms of Service' in terms.get_data(as_text=True)


def test_policy_pages_win_over_an_event_with_the_same_slug(client):
    """A host cannot shadow the policy by naming an event 'privacy'."""
    save_event_config([dict(EVENT, slug='privacy', name='Shadow party')])
    text = client.get('/privacy').get_data(as_text=True)
    assert 'Privacy Policy' in text and 'Shadow party' not in text


def test_policy_pages_fall_back_to_the_host_when_no_contact_is_configured(client, monkeypatch):
    """An unset contact address must not render an empty mailto link."""
    monkeypatch.setitem(app_module.app.config, 'CONTACT_EMAIL', '')
    for path in ('/privacy', '/terms'):
        text = client.get(path).get_data(as_text=True)
        assert 'mailto:' not in text and 'the host who invited you' in text
        assert 'googletagmanager' not in text and 'analytics-config' not in text


def test_new_events_cannot_take_a_site_route_as_their_slug():
    """An event named after a top-level route gets a different slug or is refused."""
    from event_config import add_new_event, get_all_events
    details = dict(date='2027-06-12', start_time='6:00 PM', location='The garden', description='', max_guests_per_invite=2)
    add_new_event(dict(details, name='Privacy'))
    assert 'privacy' not in get_all_events()
    with pytest.raises(ValueError):
        add_new_event(dict(details, name='Terms party', slug='terms'))

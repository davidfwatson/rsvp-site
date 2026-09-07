"""Tests for archived events: hidden from the public site, kept in the admin panel."""
import pytest

import app as app_module
from event_config import save_event_config


ACTIVE_EVENT = {
    "domain": "partymail.app",
    "id": "active01",
    "slug": "active-party",
    "name": "Active Party",
    "date": "2026-12-01",
    "start_time": "6:00 PM",
    "end_time": "9:00 PM",
    "location": "Home",
    "description": "Come celebrate!",
    "max_guests_per_invite": 5,
    "color_scheme": "pink",
}

ARCHIVED_EVENT = {
    "domain": "partymail.app",
    "id": "archived1",
    "slug": "old-party",
    "name": "Old Party",
    "date": "2024-01-01",
    "start_time": "2:00 PM",
    "end_time": "",
    "location": "Home",
    "description": "This one already happened.",
    "max_guests_per_invite": 5,
    "color_scheme": "blue",
    "archived": True,
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask test client with two events loaded and the CWD pointed at tmp_path.

    The RSVP files live next to the app as rsvps_<id>.json, so chdir keeps the
    tests from reading or writing prod's.
    """
    monkeypatch.chdir(tmp_path)
    save_event_config([dict(ACTIVE_EVENT), dict(ARCHIVED_EVENT)])
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as client:
        yield client


def test_active_event_page_is_public(client):
    """A non-archived event still renders its public page."""
    response = client.get('/active-party')
    assert response.status_code == 200
    assert b'Active Party' in response.data


def test_archived_event_page_is_404(client):
    """An archived event's public page is gone."""
    response = client.get('/old-party')
    assert response.status_code == 404


def test_archived_event_rsvp_is_rejected(client):
    """No new RSVPs can be submitted against an archived event."""
    response = client.post('/old-party/rsvp', data={
        'name': 'Someone', 'email': 'someone@example.com', 'attending': 'yes',
        'num_adults': '1', 'num_children': '0',
    })
    assert response.status_code == 404


@pytest.mark.parametrize('path', [
    '/old-party/thank-you',
    '/old-party/update-rsvp/some-token',
    '/old-party/calendar/google',
    '/old-party/calendar/ics',
])
def test_archived_event_public_subroutes_are_404(client, path):
    """Every public-facing route for an archived event is closed, not just the page."""
    assert client.get(path).status_code == 404


def test_active_event_calendar_links_still_work(client):
    """The archive guard doesn't break the calendar links on live events."""
    assert client.get('/active-party/calendar/google').status_code == 302
    assert client.get('/active-party/calendar/ics').status_code == 200


@pytest.fixture
def admin_client(client, monkeypatch):
    """Logged-in admin client.

    admin_required checks session['admin_id'] against admins.json, so stub the
    admin store rather than the decorator — the decorator is applied at import
    time, so patching the name afterwards would not affect the routes.
    """
    import passkey_auth
    monkeypatch.setattr(passkey_auth, '_load_data',
                        lambda: {"admins": [{"id": "test-admin", "is_owner": True}], "invites": []})
    with client.session_transaction() as sess:
        sess['admin_id'] = 'test-admin'
    return client


def test_admin_dashboard_lists_archived_events_separately(admin_client):
    """The dashboard keeps archived events, under their own heading."""
    html = admin_client.get('/admin').get_data(as_text=True)
    assert 'Active Party' in html
    assert 'Old Party' in html
    assert 'Past Events' in html
    # the live event is in the top list, the archived one below the heading
    assert html.index('Active Party') < html.index('Past Events') < html.index('Old Party')


def test_admin_dashboard_validation_still_sees_archived_slugs(admin_client):
    """Archiving an event must not free its name or slug for accidental reuse."""
    html = admin_client.get('/admin').get_data(as_text=True)
    assert '"old party"' in html
    assert '"old-party"' in html


def test_admin_can_still_open_an_archived_event(admin_client):
    """The archived event's own admin page — and its guest list — still load."""
    response = admin_client.get('/admin/old-party')
    assert response.status_code == 200
    assert b'Old Party' in response.data


def test_archive_flag_survives_an_admin_edit(admin_client):
    """Editing an archived event through the real form keeps it archived.

    This goes through the admin route rather than update_event_config, because
    the route rebuilds the config dict field by field from request.form — that
    reconstruction is exactly where the flag could be dropped.
    """
    from event_config import get_event_config
    response = admin_client.post('/admin/old-party', data={
        'update_event': '1',
        'name': 'Old Party',
        'date': '2024-01-01',
        'start_time': '2:00 PM',
        'end_time': '',
        'location': 'Somewhere else',
        'description': 'This one already happened.',
        'max_guests_per_invite': '5',
        'color_scheme': 'blue',
        'archived': 'on',
    }, follow_redirects=False)
    assert response.status_code == 302

    event = get_event_config('old-party')
    assert event['archived'] is True
    assert event['location'] == 'Somewhere else'
    assert admin_client.get('/old-party').status_code == 404


def test_admin_can_unarchive_an_event(admin_client):
    """Clearing the checkbox brings the public page back."""
    from event_config import get_event_config
    admin_client.post('/admin/old-party', data={
        'update_event': '1',
        'name': 'Old Party',
        'date': '2024-01-01',
        'start_time': '2:00 PM',
        'end_time': '',
        'location': 'Home',
        'description': 'This one already happened.',
        'max_guests_per_invite': '5',
        'color_scheme': 'blue',
        # no 'archived' key at all — that is what an unchecked box submits
    })

    assert get_event_config('old-party')['archived'] is False
    assert admin_client.get('/old-party').status_code == 200


def test_admin_can_archive_a_live_event(admin_client):
    """And ticking the box on a live event takes its public page down."""
    from event_config import get_event_config
    assert admin_client.get('/active-party').status_code == 200

    admin_client.post('/admin/active-party', data={
        'update_event': '1',
        'name': 'Active Party',
        'date': '2026-12-01',
        'start_time': '6:00 PM',
        'end_time': '9:00 PM',
        'location': 'Home',
        'description': 'Come celebrate!',
        'max_guests_per_invite': '5',
        'color_scheme': 'pink',
        'archived': 'on',
    })

    assert get_event_config('active-party')['archived'] is True
    assert admin_client.get('/active-party').status_code == 404


def test_editing_a_past_event_is_allowed(admin_client):
    """A past event is a record to correct, so its date isn't rejected as stale."""
    from event_config import get_event_config
    response = admin_client.post('/admin/old-party', data={
        'update_event': '1',
        'name': 'Old Party (corrected)',
        'date': '2024-01-01',
        'start_time': '2:00 PM',
        'end_time': '',
        'location': 'Home',
        'description': 'This one already happened.',
        'max_guests_per_invite': '5',
        'color_scheme': 'blue',
        'archived': 'on',
    }, follow_redirects=True)
    assert b'Event details updated successfully!' in response.data
    assert get_event_config('old-party')['name'] == 'Old Party (corrected)'


def test_creating_a_past_event_is_still_rejected(admin_client):
    """Relaxing the date check on edits must not relax it on creation."""
    from event_config import get_existing_slugs
    response = admin_client.post('/admin/new_event', data={
        'name': 'Party In The Past',
        'slug': 'party-in-the-past',
        'date': '2024-01-01',
        'start_time': '2:00 PM',
        'end_time': '',
        'location': 'Home',
        'description': 'Should not be created.',
        'max_guests_per_invite': '5',
        'color_scheme': 'pink',
    }, follow_redirects=True)
    assert b'must be in the future' in response.data
    assert 'party-in-the-past' not in get_existing_slugs()

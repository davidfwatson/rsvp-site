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


def test_archived_event_still_visible_to_admin(client, monkeypatch):
    """The admin panel keeps archived events — that's the whole point of keeping them."""
    monkeypatch.setattr(app_module, 'admin_required', lambda f: f)
    from event_config import get_all_events
    events = get_all_events()
    assert 'old-party' in events
    assert events['old-party']['archived'] is True


def test_archive_flag_survives_an_admin_edit(client):
    """Re-saving an archived event through update_event_config keeps it archived."""
    from event_config import get_event_config, update_event_config
    event = dict(get_event_config('old-party'))
    event['location'] = 'Somewhere else'
    update_event_config('old-party', event)
    assert get_event_config('old-party')['archived'] is True
    assert client.get('/old-party').status_code == 404

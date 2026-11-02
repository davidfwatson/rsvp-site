"""The public "Who's coming" list: on by default, abbreviated, and hideable."""
import pytest

import app as web
from event_config import save_event_config
from event_editor import public_attendees
from storage import write_json


EVENT = dict(id='guests123', slug='porch-party', name='Porch party', date='2030-06-12',
             start_time='6:00 PM', end_time='9:00 PM', location='The porch',
             description='', max_guests_per_invite=5, color_scheme='pink', version=0)
RESPONSES = [
    dict(name='Alex Guest', email='alex@example.test', attending='yes', num_adults=2, num_children=1),
    dict(name='Sam Lee', email='sam@example.test', attending='yes', num_adults=1, num_children=0),
    dict(name='Pat No', email='pat@example.test', attending='no', num_adults=1, num_children=0),
    dict(name='  ', email='blank@example.test', attending='yes', num_adults=1, num_children=0),
]


@pytest.fixture
def client():
    """Serve a pre-rewrite event (no show_attendees key) with real RSVPs on disk."""
    save_event_config([dict(EVENT)])
    write_json(web.rsvp_path(EVENT['id']), RESPONSES)
    return web.app.test_client()


def test_public_attendees_abbreviates_confirmed_guests_only():
    """Only "yes" responses with a name appear, as first name + last initial."""
    assert public_attendees(EVENT, RESPONSES) == [
        dict(first_name='Alex', last_initial='G', guest_info=' +2'),
        dict(first_name='Sam', last_initial='L', guest_info=''),
    ]


def test_public_attendees_respects_host_opt_out():
    """A host who turns the list off shows nobody."""
    assert public_attendees({**EVENT, 'show_attendees': False}, RESPONSES) == []


def test_event_page_shows_guest_list_for_events_without_the_flag(client):
    """Events saved before the toggle existed show the list, as they did before the rewrite."""
    page = client.get('/porch-party').get_data(as_text=True)
    assert "Who's coming" in page
    assert '4 guests so far' in page
    assert 'Alex G.' in page and 'Sam L.' in page
    assert 'Pat' not in page
    assert 'alex@example.test' not in page


def test_event_page_hides_guest_list_when_turned_off(client):
    """The admin toggle still hides the list."""
    save_event_config([{**EVENT, 'show_attendees': False}])
    page = client.get('/porch-party').get_data(as_text=True)
    assert "Who's coming" not in page and 'Alex G.' not in page


def test_mobile_invitation_returns_guest_list_by_default(client):
    """The native apps get the same default as the web page."""
    attendees = client.get('/api/mobile/invitations/porch-party').json['attendees']
    assert [a['first_name'] for a in attendees] == ['Alex', 'Sam']


@pytest.fixture
def admin_client(client, monkeypatch):
    """Signed-in host, stubbing the admin store as archived_events_test does."""
    import passkey_auth
    monkeypatch.setattr(passkey_auth, '_load_data',
                        lambda: {"admins": [{"id": "test-admin", "is_owner": True}], "invites": []})
    with client.session_transaction() as sess:
        sess['admin_id'] = 'test-admin'
    return client


def test_response_stats_split_adults_and_children():
    """Hosts get people, adults and children counted from "yes" replies only."""
    assert web.response_stats(RESPONSES) == dict(responses=4, attending=5, adults=4, children=1,
                                                accepted=3, declined=1)


def test_host_guest_list_labels_people_and_replies_plainly(admin_client):
    """The stat tiles say what they count, and party sizes read naturally."""
    page = admin_client.get('/admin/porch-party').get_data(as_text=True)
    assert 'People coming' in page and '4 adults · 1 child' in page
    assert 'Replies saying yes' in page and 'Reply saying no' in page
    assert 'Accepted' not in page
    assert '2 adults · 1 child<' in page and '1 adult · 0 children' in page
    assert 'data-label="Party size"' in page

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


DROPOFF = dict(name='Pat Lane', email='pat.lane@example.test', attending='yes', num_adults='0', num_children='1')


def test_zero_adults_rejected_unless_dropoffs_allowed():
    """Without the setting a party still needs an adult; with it, kids alone are fine."""
    with web.app.test_request_context():
        with pytest.raises(ValueError, match='at least one adult'):
            web.validate_guest(DROPOFF, EVENT)
        assert web.validate_guest(DROPOFF, {**EVENT, 'allow_dropoff': True})['num_adults'] == 0
        with pytest.raises(ValueError, match='how many people'):
            web.validate_guest({**DROPOFF, 'num_children': '0'}, {**EVENT, 'allow_dropoff': True})


def test_dropoff_shows_as_kids_on_public_list(client):
    """A kids-only reply reads "Pat L.'s kid" and counts only the kids."""
    save_event_config([{**EVENT, 'allow_dropoff': True}])
    write_json(web.rsvp_path(EVENT['id']), RESPONSES[:2] + [
        dict(name='Pat Lane', email='p@example.test', attending='yes', num_adults=0, num_children=2)])
    assert public_attendees(EVENT, [dict(name='Pat Lane', attending='yes', num_adults=0, num_children=1)]) == [
        dict(first_name='Pat', last_initial='L', guest_info="'s kid", dropoff_kids=1)]
    page = client.get('/porch-party').get_data(as_text=True)
    assert 'Pat L.&#39;s 2 kids' in page
    assert '6 guests so far' in page


def test_dropoff_rsvp_flow_confirms_kids_only(client):
    """The form allows 0 adults, and the thank-you page and email don't call it 1 adult."""
    save_event_config([{**EVENT, 'allow_dropoff': True}])
    assert 'min="0"' in client.get('/porch-party').get_data(as_text=True)
    sent = []
    import app as app_module
    original = app_module.deliver_email
    app_module.deliver_email = lambda to, subject, body: sent.append(body) or True
    try:
        response = client.post('/porch-party/rsvp', data=DROPOFF, follow_redirects=True)
    finally:
        app_module.deliver_email = original
    page = response.get_data(as_text=True)
    assert '1 child confirmed for drop-off' in page and 'adult' not in page.split('confirmed-party')[1][:80]
    assert '**1 child (drop-off)**' in sent[0] and 'welcome your kids' in sent[0]


def test_dropoff_setting_saves_from_admin(admin_client):
    """The host toggle round-trips through the event editor."""
    page = admin_client.get('/admin/porch-party').get_data(as_text=True)
    assert 'Drop-offs allowed' in page and 'id="allow_dropoff"' in page
    from event_config import get_event_config
    form = {k: EVENT[k] for k in ('name', 'date', 'start_time', 'end_time', 'location', 'description')}
    form.update(update_event='1', max_guests_per_invite='5', color_scheme='pink', show_attendees='on')
    admin_client.post('/admin/porch-party', data={**form, 'allow_dropoff': 'on'})
    assert get_event_config('porch-party')['allow_dropoff'] is True
    admin_client.post('/admin/porch-party', data=form)
    assert get_event_config('porch-party')['allow_dropoff'] is False

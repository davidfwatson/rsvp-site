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
                                                accepted=3, declined=1, maybe=0, maybe_people=0)


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


@pytest.mark.parametrize('rsvp, expected', [
    (None, '1'), (dict(attending='yes'), '1'), (dict(num_adults=0), '0'), (dict(num_adults=3), '3'),
    (dict(num_adults=''), '1'),
])
def test_adults_field_keeps_zero_and_defaults_legacy_responses_to_one(rsvp, expected):
    """A saved 0 stays 0; a response saved before num_adults existed still shows 1."""
    import re
    from flask import render_template_string
    with web.app.test_request_context():
        html = render_template_string(
            "{% from '_rsvp_fields.html' import attendance_fields %}{{ attendance_fields(event, rsvp) }}",
            event={**EVENT, 'allow_dropoff': True}, rsvp=rsvp)
    assert re.search(r'id="num_adults"[^>]*value="([^"]*)"', html).group(1) == expected


MAYBE = dict(name='Mo Bee', email='mo@example.test', attending='maybe', num_adults='2', num_children='1')


def test_maybe_is_on_by_default_and_can_be_turned_off():
    """Events without the setting accept "maybe"; a host can switch it off."""
    with web.app.test_request_context():
        assert web.validate_guest(MAYBE, EVENT)['num_adults'] == 2
        with pytest.raises(ValueError, match='whether you can attend'):
            web.validate_guest(MAYBE, {**EVENT, 'allow_maybe': False})
        existing = dict(name='Mo Bee', email='mo@example.test', attending='maybe')
        assert web.validate_guest(MAYBE, {**EVENT, 'allow_maybe': False}, existing)['attending'] == 'maybe'


def test_maybe_counts_separately_and_stays_off_the_public_list(client):
    """Maybes aren't in the headcount or "Who's coming", but hosts see how many might come."""
    responses = RESPONSES + [dict(MAYBE, num_adults=2, num_children=1)]
    stats = web.response_stats(responses)
    assert (stats['attending'], stats['maybe'], stats['maybe_people']) == (5, 1, 3)
    assert public_attendees(EVENT, responses) == public_attendees(EVENT, RESPONSES)


def test_event_page_offers_maybe_only_when_allowed(client):
    """The radio appears by default and disappears when the host turns it off."""
    assert 'value="maybe"' in client.get('/porch-party').get_data(as_text=True)
    save_event_config([{**EVENT, 'allow_maybe': False}])
    assert 'value="maybe"' not in client.get('/porch-party').get_data(as_text=True)


def test_maybe_rsvp_flow(client):
    """A maybe reply is saved with its party size and confirmed as tentative."""
    sent = []
    import app as app_module
    original = app_module.deliver_email
    app_module.deliver_email = lambda to, subject, body: sent.append(body) or True
    try:
        page = client.post('/porch-party/rsvp', data=MAYBE, follow_redirects=True).get_data(as_text=True)
    finally:
        app_module.deliver_email = original
    assert 'might join' in page and '2 adults &amp; 1 child if you can make it' in page
    assert '**2 adults and 1 child, if you can make it**' in sent[0] and "once you're sure" in sent[0]
    saved = [r for r in web.load_rsvps(EVENT['id']) if r['email'] == 'mo@example.test']
    assert saved[0]['attending'] == 'maybe' and saved[0]['num_children'] == 1


def test_host_sees_maybe_tile_and_toggle(admin_client):
    """The guest list shows a maybe tile and badge; the toggle round-trips."""
    write_json(web.rsvp_path(EVENT['id']), RESPONSES + [dict(MAYBE, num_adults=2, num_children=1)])
    page = admin_client.get('/admin/porch-party').get_data(as_text=True)
    assert 'Reply saying maybe' in page and '3 people<' in page and 'badge-maybe' in page
    assert 'id="allow_maybe"' in page and 'checked' in page.split('id="allow_maybe"')[1][:60]
    from event_config import get_event_config
    form = {k: EVENT[k] for k in ('name', 'date', 'start_time', 'end_time', 'location', 'description')}
    form.update(update_event='1', max_guests_per_invite='5', color_scheme='pink', show_attendees='on')
    admin_client.post('/admin/porch-party', data=form)
    assert get_event_config('porch-party')['allow_maybe'] is False
    admin_client.post('/admin/porch-party', data={**form, 'allow_maybe': 'on'})
    assert get_event_config('porch-party')['allow_maybe'] is True


def test_saved_maybe_survives_a_failed_update_when_maybe_is_off(client):
    """A guest who said maybe keeps the option after an invalid edit, even with maybe turned off."""
    save_event_config([{**EVENT, 'allow_maybe': False}])
    write_json(web.rsvp_path(EVENT['id']), [dict(MAYBE, num_adults=1, num_children=0, token='tok')])
    page = client.post('/porch-party/update-rsvp/tok', data=dict(MAYBE, attending='yes', num_adults='99'))
    assert page.status_code == 400 and 'value="maybe"' in page.get_data(as_text=True)

"""Versioned native-app access to the same events, accounts and guest responses.

Native clients use session cookies and CSRF just like the website. No parallel
account store or bearer-token bypass is introduced.
"""
import base64
import hmac
import re
from datetime import datetime
from io import BytesIO

from dateutil.parser import parse as parse_datetime
from flask import Blueprint, current_app, jsonify, request, send_file, session

from event_config import EventConflictError, add_new_event, get_all_events, get_event_config
from event_editor import prepare_event, validate_event
from export_rsvps import generate_rsvps_csv, get_csv_filename
from passkey_auth import (
    AccountError, _find_signin_link, _now, _update_data, admin_required,
    bootstrap_owner, establish_admin_session, get_current_admin,
)
from runtime_config import data_path
from security import allow_request, csrf_token
from storage import json_lock, write_json


EVENT_FIELDS = (
    'id', 'slug', 'version', 'name', 'date', 'start_time', 'end_time', 'location',
    'description', 'max_guests_per_invite', 'color_scheme', 'background_style',
    'background_color', 'accent_color', 'background_image', 'cover_image',
    'font_style', 'envelope_style', 'show_attendees', 'archived',
)
RESPONSE_FIELDS = (
    'name', 'email', 'attending', 'num_adults', 'num_children',
    'dietary_restrictions', 'comment', 'timestamp', 'updated_at',
)


def android_fingerprints(config):
    """Validate explicit signing certificates; never trust the SDK debug key."""
    result = []
    for raw in config.get('ANDROID_SHA256_CERT_FINGERPRINTS', '').split(','):
        if not raw.strip():
            continue
        value = raw.strip().replace(':', '').upper()
        if not re.fullmatch(r'[A-F0-9]{64}', value):
            raise ValueError('RSVP_ANDROID_SHA256_CERT_FINGERPRINTS must contain SHA-256 hex fingerprints.')
        if value not in result:
            result.append(value)
    return result


def android_origins(config):
    """Derive exact WebAuthn native origins from the very same DAL certificates."""
    return ['android:apk-key-hash:' + base64.urlsafe_b64encode(bytes.fromhex(value)).decode().rstrip('=')
            for value in android_fingerprints(config)]


def _body():
    """Require a JSON object and keep numeric fields unambiguous."""
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        raise ValueError('A JSON object is required.')
    for field in ('num_adults', 'num_children', 'max_guests_per_invite'):
        value = values.get(field)
        if field in values and (isinstance(value, bool) or isinstance(value, (float, list, dict))):
            raise ValueError('Guest counts and limits must be whole numbers.')
    return values


def _time(value):
    """Normalize legacy 12-hour times for native date/time controls."""
    if not value:
        return ''
    try:
        return parse_datetime(value, default=datetime(2000, 1, 1)).strftime('%H:%M')
    except (ValueError, TypeError, OverflowError):
        return value


def _date(value):
    """Keep human-readable legacy dates usable in native date controls."""
    try:
        return parse_datetime(value, default=datetime(2000, 1, 15)).strftime('%Y-%m-%d')
    except (ValueError, TypeError, OverflowError):
        return value or ''


def _response(response, private=False):
    """Do not expose edit tokens to the host or someone with an email address."""
    result = dict(name='', email='', attending='no', num_adults=0, num_children=0,
                  dietary_restrictions='', comment='')
    result.update({key: response[key] for key in RESPONSE_FIELDS if key in response})
    if 'num_adults' not in response and result['attending'] == 'yes':
        result['num_adults'] = 1
    if private:
        result['token'] = response['token']
    return result


def register_mobile_api(app, services):
    """Bind shared web operations without importing a second Flask app instance."""
    bp = Blueprint('mobile', __name__, url_prefix='/api/mobile')
    android_fingerprints(app.config)  # Fail startup on a malformed trust anchor.

    def event_payload(event, host=False):
        prepared = prepare_event({'color_scheme': 'pink', 'description': '', 'max_guests_per_invite': 5, **event})
        result = {key: prepared[key] for key in EVENT_FIELDS if key in prepared}
        result.setdefault('version', 0)
        result.setdefault('archived', False)
        result['date'] = _date(result.get('date', ''))
        result['start_time'] = _time(result.get('start_time', ''))
        result['end_time'] = _time(result.get('end_time', ''))
        result['public_url'] = services['public_url'](event['slug'])
        if host:
            result['stats'] = services['response_stats'](services['load_rsvps'](event['id']))
        return result

    def session_payload():
        admin = get_current_admin()
        return dict(csrf_token=csrf_token(),
                    admin={key: admin.get(key, False) for key in ('id', 'name', 'is_owner')} if admin else None,
                    public_url=current_app.config['PUBLIC_URL'],
                    email_enabled=current_app.config.get('EMAIL_ENABLED', False),
                    email_connected=data_path('token.json').is_file())

    def require_event(slug, public=False):
        event = services['get_public_event'](slug) if public else get_event_config(slug)
        if not event or event.get('slug') != slug:
            from werkzeug.exceptions import NotFound
            raise NotFound('Event not found.')
        return event

    @bp.errorhandler(ValueError)
    def bad_input(error):
        return jsonify(error=str(error)), 400

    @bp.errorhandler(404)
    def not_found(error):
        return jsonify(error=error.description), 404

    @bp.route('/session')
    def get_session():
        return jsonify(session_payload())

    @bp.route('/login', methods=['POST'])
    def login():
        values = _body()
        password = values.get('password', '')
        if not isinstance(password, str) or len(password) > 1024:
            raise ValueError('Enter a valid owner recovery password.')
        if not allow_request('password-login', limit=10):
            return jsonify(error='Too many attempts. Try again in 15 minutes.'), 429
        expected = current_app.config.get('ADMIN_PASSWORD', '')
        if not expected or not hmac.compare_digest(password.encode(), expected.encode()):
            return jsonify(error='Invalid owner recovery password.'), 401
        establish_admin_session(bootstrap_owner())
        return jsonify(session_payload())

    @bp.route('/signin', methods=['POST'])
    def signin():
        token = _body().get('token')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,200}', token):
            raise ValueError('This sign-in link is invalid.')
        if not allow_request('signin-link', limit=20):
            return jsonify(error='Too many attempts. Try again later.'), 429
        result = {}

        def consume(data):
            link = _find_signin_link(data, token)
            admin = next((a for a in data['admins'] if link and a['id'] == link['admin_id']), None)
            if not admin:
                raise AccountError('This sign-in link expired or was already used.')
            admin['last_login_at'] = _now()
            result.update(admin)
            data['signin_links'] = [item for item in data['signin_links'] if item['id'] != link['id']]

        _update_data(consume)
        establish_admin_session(result)
        return jsonify(session_payload())

    @bp.route('/logout', methods=['POST'])
    def logout():
        _body()
        session.clear()
        return jsonify(session_payload())

    @bp.route('/events', methods=['GET', 'POST'])
    @admin_required
    def events():
        if request.method == 'GET':
            return jsonify(events=[event_payload(e, host=True) for e in get_all_events().values()])
        values = _body()
        event = validate_event(values, require_future=True)
        slug = values.get('slug', '')
        if not isinstance(slug, str):
            raise ValueError('Choose a valid invitation address.')
        event['slug'] = slug.strip().lower()
        if any(e['name'].casefold() == event['name'].casefold() for e in get_all_events().values()):
            raise ValueError('An event with this name already exists.')
        event_id = add_new_event(event)
        created = next(e for e in get_all_events().values() if e['id'] == event_id)
        return jsonify(event=event_payload(created, host=True)), 201

    @bp.route('/events/<slug>', methods=['GET', 'PATCH'])
    @admin_required
    def host_event(slug):
        event = require_event(slug)
        if request.method == 'PATCH':
            values = _body()
            if type(values.get('version')) is not int or values['version'] < 0:
                raise ValueError('Reload this event to get its latest version.')
            try:
                event = services['save_event_values'](event, values, values['version'])
            except EventConflictError:
                return jsonify(error='This event changed on another device. Reload it before saving.'), 409
            return jsonify(event=event_payload(event, host=True))
        return jsonify(event=event_payload(event, host=True),
                       rsvps=[_response(r) for r in services['load_rsvps'](event['id'])])

    @bp.route('/events/<slug>/invite', methods=['POST'])
    @admin_required
    def invite(slug):
        event = require_event(slug)
        email = _body().get('email', '')
        if event.get('archived'):
            raise ValueError('Restore this event before sending invitations.')
        if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email.strip()):
            raise ValueError('Enter a valid email address.')
        from flask import render_template
        delivered = services['deliver_email'](email.strip(), f"You're invited: {event['name']}",
                                              services['generate_invitation_email_body'](event),
                                              render_template('email_invitation.html', event=prepare_event(event)))
        if not delivered:
            return jsonify(error='Email is not connected or delivery failed. Share the invitation link instead.'), 503
        return jsonify(success=True)

    @bp.route('/events/<slug>/upload', methods=['POST'])
    @admin_required
    def upload(slug):
        return services['upload_image'](slug)

    @bp.route('/events/<slug>/export')
    @admin_required
    def export(slug):
        event = require_event(slug)
        csv = generate_rsvps_csv(services['load_rsvps'](event['id'])) or ''
        return send_file(BytesIO(csv.encode('utf-8-sig')), mimetype='text/csv',
                         as_attachment=True, download_name=get_csv_filename(event['name']))

    @bp.route('/invitations/<slug>')
    def invitation(slug):
        event = require_event(slug, public=True)
        attendees = []
        if event.get('show_attendees'):
            for response in services['load_rsvps'](event['id']):
                names = response.get('name', '').split()
                if response.get('attending') != 'yes' or not names:
                    continue
                guests = response.get('num_adults', 1) + response.get('num_children', 0) - 1
                attendees.append(dict(first_name=names[0], last_initial=names[-1][0].upper(),
                                      guest_info=f' +{guests}' if guests > 0 else ''))
        return jsonify(event=event_payload(event), attendees=attendees)

    @bp.route('/invitations/<slug>/rsvp', methods=['POST'])
    def rsvp(slug):
        event = require_event(slug, public=True)
        values = _body()
        if not allow_request('rsvp', limit=30):
            return jsonify(error='Too many responses. Please try again later.'), 429
        response = services['validate_guest'](values, event)
        path = services['rsvp_path'](event['id'])
        with json_lock(path):
            responses = services['load_rsvps'](event['id'])
            existing = next((r for r in responses if r.get('email', '').strip().lower() == response['email']), None)
            if existing:
                response = existing
            else:
                import secrets
                response.update(timestamp=services['now'](), token=secrets.token_urlsafe(32))
                responses.append(response)
                write_json(path, responses)
        update_url = services['public_url'](slug) + '/update-rsvp/' + response['token']
        delivered = services['deliver_email'](response['email'], f"Your RSVP for {event['name']}",
                                              services['generate_confirmation_email_body'](event, response, update_url))
        if existing:
            return jsonify(check_email=True, email_delivered=delivered)
        services['notify'](f"New RSVP for {event['name']}: {response['name']} / {response['attending']}")
        return jsonify(response=_response(response, private=True), update_url=update_url,
                       email_delivered=delivered), 201

    @bp.route('/invitations/<slug>/responses/<token>', methods=['GET', 'PATCH'])
    def guest_response(slug, token):
        event = require_event(slug, public=True)
        response = next((r for r in services['load_rsvps'](event['id'])
                         if hmac.compare_digest(r.get('token', '').encode(), token.encode())), None)
        if not response:
            from werkzeug.exceptions import NotFound
            raise NotFound('RSVP not found.')
        if request.method == 'PATCH':
            values = _body()
            path = services['rsvp_path'](event['id'])
            with json_lock(path):
                responses = services['load_rsvps'](event['id'])
                index = next((i for i, r in enumerate(responses) if r.get('token') == token), None)
                if index is None:
                    from werkzeug.exceptions import NotFound
                    raise NotFound('RSVP not found.')
                response = services['validate_guest']({**responses[index], **values}, event, responses[index])
                if any(i != index and r.get('email', '').strip().lower() == response['email'] for i, r in enumerate(responses)):
                    raise ValueError('Another response already uses this email address.')
                response['updated_at'] = services['now']()
                responses[index] = response
                write_json(path, responses)
            services['notify'](f"RSVP updated for {event['name']}: {response['name']}")
        return jsonify(event=event_payload(event), response=_response(response, private=True))

    app.register_blueprint(bp)

    @app.route('/.well-known/apple-app-site-association')
    def apple_association():
        app_id = current_app.config['APPLE_TEAM_ID'] + '.com.davidfwatson.partymail'
        return jsonify(webcredentials=dict(apps=[app_id]),
                       applinks=dict(apps=[], details=[dict(appID=app_id, paths=[
                           'NOT /api/*', 'NOT /.well-known/*', 'NOT /media/*', 'NOT /static/*',
                           'NOT /*/calendar/*', 'NOT /*/thank-you',
                           '/admin/signin/*', '/admin/invite/*', 'NOT /admin*',
                           'NOT /privacy', 'NOT /terms', 'NOT /healthz', '/*',
                       ])]))

    @app.route('/.well-known/assetlinks.json')
    def android_association():
        fingerprints = android_fingerprints(current_app.config)
        if not fingerprints:
            return jsonify([])
        return jsonify([dict(relation=['delegate_permission/common.handle_all_urls',
                                      'delegate_permission/common.get_login_creds'],
                             target=dict(namespace='android_app', package_name='com.davidfwatson.partymail',
                                         sha256_cert_fingerprints=[':'.join(v[i:i+2] for i in range(0, 64, 2))
                                                                   for v in fingerprints]))])

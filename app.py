"""PartyMail invitation publishing and host workspace."""
import hmac
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from io import BytesIO

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import RequestEntityTooLarge

from calendar_utils import generate_google_calendar_url, generate_ics_file
from email_content import generate_confirmation_email_body, generate_invitation_email_body
from email_handler import send_email
from event_config import EventConflictError, add_new_event, format_event_time, get_all_events, get_event_config, update_event_config
from event_editor import prepare_event, validate_event
from export_rsvps import generate_rsvps_csv, get_csv_filename
from notifications import notify_phone
from passkey_auth import admin_required, get_current_admin, passkey_bp
from runtime_config import configure_app, data_path
from security import allow_request, init_security
from storage import json_lock, read_json, write_json

app = Flask(__name__)
configure_app(app)
init_security(app)
app.register_blueprint(passkey_bp)
app.jinja_env.filters['format_time'] = format_event_time


def now():
    """Timestamp stored changes unambiguously."""
    return datetime.now(timezone.utc).isoformat()


def public_url(slug):
    """Use the configured canonical origin for invitation links."""
    return app.config['PUBLIC_URL'].rstrip('/') + url_for('event_page', slug=slug)


@app.context_processor
def workspace_context():
    """Supply the shell and validated analytics configuration."""
    measurement = app.config.get('GA_MEASUREMENT_ID', '')
    if not re.fullmatch(r'G-[A-Z0-9]+', measurement):
        measurement = ''
    return dict(current_admin=get_current_admin(), ga_measurement_id=measurement, public_url=public_url)


def get_public_event(slug):
    """Archived invitations remain available only to hosts."""
    event = get_event_config(slug)
    return event if event and not event.get('archived') else None


def rsvp_path(event_id):
    """Resolve responses by immutable event ID."""
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', event_id):
        raise ValueError('Invalid event ID')
    return data_path(f'rsvps_{event_id}.json')


def load_rsvps(event_id):
    """Corrupt stores fail closed instead of appearing empty."""
    return read_json(rsvp_path(event_id), [])


def save_rsvps(event_id, responses):
    """Compatibility helper; request mutations hold a lock around read and write."""
    with json_lock(rsvp_path(event_id)):
        write_json(rsvp_path(event_id), responses)


def deliver_email(destination, subject, body, html_body=None):
    """Mail failure never rolls back an already saved response."""
    if not app.config.get('EMAIL_ENABLED') or app.config.get('TESTING'):
        return False
    try:
        return send_email(destination, subject, body, html_body)
    except Exception:
        app.logger.exception('Email delivery failed')
        return False


def notify(message):
    """Only production may send real notifications."""
    if app.config.get('RSVP_ENV') == 'production' and not app.config.get('TESTING'):
        try:
            notify_phone(message)
        except Exception:
            app.logger.exception('Phone notification failed')


def validate_guest(values, event, existing=None):
    """Validate guest fields before changing persistent responses."""
    result = dict(existing or {})
    for field, maximum in [('name', 160), ('email', 254), ('comment', 2000), ('dietary_restrictions', 2000)]:
        value = values.get(field, result.get(field, ''))
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError('Please shorten your response and try again.')
        result[field] = value.strip()
    result['email'] = result['email'].lower()
    if not result['name'] or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', result['email']):
        raise ValueError('Please enter your name and a valid email address.')
    attending = values.get('attending')
    if attending not in ('yes', 'no'):
        raise ValueError('Please choose whether you can attend.')
    result['attending'] = attending
    try:
        adults = int(values.get('num_adults', 1)) if attending == 'yes' else 0
        children = int(values.get('num_children', 0)) if attending == 'yes' else 0
    except (ValueError, TypeError):
        raise ValueError('Please enter whole numbers for your guest counts.') from None
    if attending == 'yes' and (adults < 1 or children < 0 or adults + children > event['max_guests_per_invite']):
        raise ValueError(f"Your party can include up to {event['max_guests_per_invite']} guests, including you.")
    result.update(num_adults=adults, num_children=children)
    return result


def confirm_response(event, response, email_delivery_failed=False):
    """Keep personal details out of redirect URLs."""
    session['rsvp_confirmation'] = {k: response.get(k, '') for k in ('name', 'attending', 'num_adults', 'num_children', 'dietary_restrictions')}
    session['rsvp_confirmation']['slug'] = event['slug']
    session['rsvp_confirmation']['email_delivery_failed'] = email_delivery_failed
    return redirect(url_for('thank_you', slug=event['slug']))


@app.route('/')
def index():
    return render_template('landing.html')


@app.route('/privacy')
def privacy():
    """Public policy page; the Google OAuth consent screen links here."""
    return render_template('privacy.html', contact_email=app.config.get('CONTACT_EMAIL'))


@app.route('/terms')
def terms():
    """Public terms page; the Google OAuth consent screen links here."""
    return render_template('terms.html', contact_email=app.config.get('CONTACT_EMAIL'))


@app.route('/<slug>')
def event_page(slug):
    event = get_public_event(slug)
    if not event:
        return 'Event not found', 404
    attendees = []
    if event.get('show_attendees', False):
        for response in load_rsvps(event['id']):
            names = response.get('name', '').split()
            if response.get('attending') != 'yes' or not names:
                continue
            guests = response.get('num_adults', 1) + response.get('num_children', 0) - 1
            attendees.append(dict(first_name=names[0], last_initial=names[-1][0].upper(), guest_info=f' +{guests}' if guests > 0 else ''))
    return render_template('index.html', event=prepare_event(event), attendees=attendees)


@app.route('/<slug>/rsvp', methods=['POST'])
def rsvp(slug):
    event = get_public_event(slug)
    if not event:
        return 'Event not found', 404
    if request.form.get('website'):
        return redirect(url_for('thank_you', slug=slug))
    if not allow_request('rsvp', limit=30):
        return 'Too many responses. Please try again later.', 429
    try:
        response = validate_guest(request.form, event)
    except ValueError as error:
        return render_template('index.html', event=prepare_event(event), attendees=[], error=str(error)), 400
    with json_lock(rsvp_path(event['id'])):
        responses = load_rsvps(event['id'])
        existing = next((r for r in responses if r.get('email', '').strip().lower() == response['email']), None)
        if existing:
            response = existing
        else:
            response.update(timestamp=now(), token=secrets.token_urlsafe(32))
            responses.append(response)
            write_json(rsvp_path(event['id']), responses)
    update_url = app.config['PUBLIC_URL'].rstrip('/') + url_for('update_rsvp', slug=slug, token=response['token'])
    delivered = deliver_email(response['email'], f"Your RSVP for {event['name']}", generate_confirmation_email_body(event, response, update_url))
    if existing:
        # An email address alone cannot authorize viewing or overwriting a response.
        session['rsvp_confirmation'] = dict(slug=slug, name='', attending='', check_email=True, email_delivery_failed=not delivered)
        return redirect(url_for('thank_you', slug=slug))
    notify(f"New RSVP for {event['name']}: {response['name']} / {response['attending']}")
    return confirm_response(event, response, email_delivery_failed=not delivered)


@app.route('/<slug>/thank-you')
def thank_you(slug):
    event = get_public_event(slug)
    if not event:
        return 'Event not found', 404
    details = session.get('rsvp_confirmation', {})
    if details.get('slug') != slug:
        details = {}
    return render_template('thank_you.html', event=prepare_event(event), name=details.get('name', ''), attending=details.get('attending', ''),
        num_adults=details.get('num_adults', 0), num_children=details.get('num_children', 0), dietary_restrictions=details.get('dietary_restrictions', ''), check_email=details.get('check_email', False), email_delivery_failed=details.get('email_delivery_failed', False))


@app.route('/<slug>/update-rsvp/<token>', methods=['GET', 'POST'])
def update_rsvp(slug, token):
    event = get_public_event(slug)
    if not event:
        return 'Event not found', 404
    response = next((r for r in load_rsvps(event['id']) if hmac.compare_digest(r.get('token', '').encode(), token.encode())), None)
    if not response:
        return 'RSVP not found', 404
    if request.method == 'POST':
        try:
            with json_lock(rsvp_path(event['id'])):
                responses = load_rsvps(event['id'])
                index = next(i for i, r in enumerate(responses) if r.get('token') == token)
                response = validate_guest(request.form, event, responses[index])
                if any(i != index and r.get('email','').strip().lower() == response['email'] for i, r in enumerate(responses)):
                    raise ValueError('Another response already uses this email address.')
                response['updated_at'] = now()
                responses[index] = response
                write_json(rsvp_path(event['id']), responses)
        except ValueError as error:
            return render_template('update_rsvp.html', event=prepare_event(event), rsvp=response, error=str(error)), 400
        notify(f"RSVP updated for {event['name']}: {response['name']}")
        return confirm_response(event, response)
    return render_template('update_rsvp.html', event=prepare_event(event), rsvp=response)


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    from passkey_auth import bootstrap_owner, establish_admin_session, safe_admin_next
    if request.method == 'POST':
        if not allow_request('password-login', limit=10):
            return render_template('admin_login.html', error='Too many attempts. Try again in 15 minutes.'), 429
        expected = app.config.get('ADMIN_PASSWORD', '')
        if expected and hmac.compare_digest(request.form.get('password', '').encode(), expected.encode()):
            establish_admin_session(bootstrap_owner())
            return redirect(safe_admin_next(request.args.get('next')))
        flash('Invalid password', 'error')
    return render_template('admin_login.html')


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))


def response_stats(responses):
    """Count households and people consistently."""
    attending = [r for r in responses if r.get('attending') == 'yes']
    return dict(responses=len(responses), attending=sum(r.get('num_adults', 1) + r.get('num_children', 0) for r in attending),
        accepted=len(attending), declined=sum(r.get('attending') == 'no' for r in responses))


@app.route('/admin')
@admin_required
def admin_dashboard():
    events = get_all_events()
    active = {s: e for s, e in events.items() if not e.get('archived')}
    archived = {s: e for s, e in events.items() if e.get('archived')}
    stats = {s: response_stats(load_rsvps(e['id'])) for s, e in events.items()}
    return render_template('admin_dashboard.html', events=events, active_events=active, archived_events=archived, stats=stats)


@app.route('/admin/new_event', methods=['POST'])
@admin_required
def new_event():
    try:
        values = validate_event(request.form, require_future=True)
        values['slug'] = request.form.get('slug', '').strip().lower()
        if any(e['name'].casefold() == values['name'].casefold() for e in get_all_events().values()):
            raise ValueError('An event with this name already exists.')
        event_id = add_new_event(values)
        created = next(e for e in get_all_events().values() if e['id'] == event_id)
        flash('Your event is ready. Make it yours below.', 'success')
        return redirect(url_for('admin', slug=created['slug']))
    except ValueError as error:
        flash(f'Error: {error}', 'error')
        return redirect(url_for('admin_dashboard'))


def save_event_values(event, values, expected_version=None):
    """Preserve noneditable metadata during autosave."""
    updated = validate_event(values, existing=event)
    if any(e['slug'] != event['slug'] and e['name'].casefold() == updated['name'].casefold() for e in get_all_events().values()):
        raise ValueError('Another event already uses this name.')
    return update_event_config(event['slug'], updated, expected_version=expected_version)


@app.route('/admin/<slug>', methods=['GET', 'POST'])
@admin_required
def admin(slug):
    event = get_event_config(slug)
    if not event:
        return 'Event not found', 404
    if request.method == 'POST':
        if 'update_event' in request.form:
            try:
                values = request.form.to_dict()
                values['archived'] = 'archived' in request.form
                values['show_attendees'] = 'show_attendees' in request.form
                version = int(values['version']) if 'version' in values else None
                save_event_values(event, values, version)
                flash('Event details updated successfully!', 'success')
            except (ValueError, EventConflictError) as error:
                flash(str(error), 'error')
            return redirect(url_for('admin', slug=slug))
        if 'send_invitation' in request.form:
            recipient = request.form.get('email', '').strip()
            if event.get('archived'):
                flash('Restore this event before sending invitations.', 'error')
            elif not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', recipient):
                flash('Enter a valid email address.', 'error')
            elif deliver_email(recipient, f"You're invited: {event['name']}", generate_invitation_email_body(event), render_template('email_invitation.html', event=prepare_event(event))):
                flash('Invitation sent successfully!', 'success')
            else:
                flash('Email is not connected or delivery failed. You can copy the invitation link instead.', 'error')
            return redirect(url_for('admin', slug=slug))
    responses = load_rsvps(event['id'])
    return render_template('admin_event.html', event=prepare_event(event), rsvps=responses, stats=response_stats(responses), slug=slug)


@app.route('/admin/<slug>/save', methods=['POST'])
@admin_required
def autosave_event(slug):
    event = get_event_config(slug)
    if not event:
        return jsonify(error='Event not found'), 404
    values = request.get_json(silent=True)
    if not isinstance(values, dict) or not isinstance(values.get('version'), int):
        return jsonify(error='Reload the editor to get the latest event version.'), 400
    try:
        saved = save_event_values(event, values, values['version'])
        return jsonify(success=True, version=saved.get('version', 0), saved_at=now())
    except EventConflictError:
        return jsonify(error='This event changed in another window. Reload to review those changes before saving.'), 409
    except ValueError as error:
        return jsonify(error=str(error)), 400


@app.route('/admin/<slug>/preview', methods=['GET', 'POST'])
@admin_required
def preview_event(slug):
    event = get_event_config(slug)
    if not event:
        return 'Event not found', 404
    if request.method == 'POST':
        try:
            values = request.get_json(silent=True)
            if not isinstance(values, dict):
                raise ValueError('A JSON object is required.')
            event = validate_event(values, event)
        except ValueError as error:
            return jsonify(error=str(error)), 400
    return render_template('index.html', event=prepare_event(event), attendees=[], preview=True,
                           preview_view='opening' if request.args.get('view') == 'opening' else None)


@app.route('/admin/<slug>/upload', methods=['POST'])
@admin_required
def upload_image(slug):
    if not get_event_config(slug):
        return jsonify(error='Event not found'), 404
    uploaded = request.files.get('image')
    if not uploaded:
        return jsonify(error='Choose an image first.'), 400
    raw = uploaded.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        return jsonify(error='Choose an image smaller than 8 MB.'), 413
    try:
        with Image.open(BytesIO(raw)) as original:
            if original.format not in ('JPEG', 'PNG', 'WEBP') or original.width * original.height > 24000000:
                raise ValueError('Choose a smaller JPEG, PNG, or WebP.')
            original.load()
            cleaned = ImageOps.exif_transpose(original).convert('RGBA' if 'A' in original.getbands() or 'transparency' in original.info else 'RGB')
            cleaned.thumbnail((2400, 2400))
            buffer = BytesIO()
            cleaned.save(buffer, format='WEBP', quality=88)
        name = uuid.uuid4().hex + '.webp'
        target = data_path('uploads/' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with json_lock(data_path('uploads/.uploads')):
            with target.open('xb') as output:
                output.write(buffer.getvalue())
                output.flush()
                os.fsync(output.fileno())
        return jsonify(success=True, url=url_for('media', name=name))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return jsonify(error='Choose a valid JPEG, PNG, or WebP image under 24 megapixels.'), 400


@app.route('/media/<name>')
def media(name):
    if not re.fullmatch(r'[a-f0-9]{32}\.webp', name):
        return 'Image not found', 404
    return send_from_directory(data_path('uploads'), name, max_age=31536000)


@app.route('/admin/<slug>/export')
@admin_required
def export_rsvps(slug):
    event = get_event_config(slug)
    if not event:
        return 'Event not found', 404
    csv_data = generate_rsvps_csv(load_rsvps(event['id']))
    if not csv_data:
        flash('No RSVPs to export', 'error')
        return redirect(url_for('admin', slug=slug))
    return send_file(BytesIO(csv_data.encode('utf-8-sig')), mimetype='text/csv', as_attachment=True, download_name=get_csv_filename(event['name']))


@app.route('/admin/system')
@admin_required
def admin_system():
    return render_template('admin_system.html', environment=app.config['RSVP_ENV'], analytics=app.config.get('GA_MEASUREMENT_ID'),
        email_enabled=app.config.get('EMAIL_ENABLED', False), email_connected=data_path('token.json').exists(),
        release=app.config.get('RELEASE_ID', 'local'), protected_data=app.config['RSVP_ENV'] == 'production')


@app.route('/admin/email/connect')
@admin_required
def connect_email():
    if not get_current_admin().get('is_owner'):
        return 'Owner access required', 403
    if not app.config.get('EMAIL_ENABLED'):
        flash('Set RSVP_EMAIL_ENABLED=true and add Gmail credentials to connect email.', 'error')
        return redirect(url_for('admin_system'))
    from google_auth_oauthlib.flow import Flow
    try:
        flow = Flow.from_client_secrets_file(str(data_path('credentials.json')), scopes=['https://www.googleapis.com/auth/gmail.send'],
            redirect_uri=app.config['PUBLIC_URL'].rstrip('/') + url_for('oauth2callback'))
        auth_url, state = flow.authorization_url(prompt='consent', access_type='offline')
        session['gmail_oauth_state'] = state
        return redirect(auth_url)
    except (FileNotFoundError, ValueError):
        flash('Add credentials.json to the persistent data directory first.', 'error')
        return redirect(url_for('admin_system'))


@app.route('/oauth2callback')
@admin_required
def oauth2callback():
    if not get_current_admin().get('is_owner'):
        return 'Owner access required', 403
    state = session.pop('gmail_oauth_state', '')
    if not state or not hmac.compare_digest(state.encode(), request.args.get('state', '').encode()):
        return 'Invalid OAuth state. Start the connection again from settings.', 400
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(str(data_path('credentials.json')), scopes=['https://www.googleapis.com/auth/gmail.send'], state=state,
        redirect_uri=app.config['PUBLIC_URL'].rstrip('/') + url_for('oauth2callback'))
    try:
        flow.fetch_token(authorization_response=request.url)
        write_json(data_path('token.json'), json.loads(flow.credentials.to_json()))
        flash('Google email connected.', 'success')
    except Exception:
        app.logger.exception('Gmail authorization failed')
        flash('Could not connect Google email. Try connecting again.', 'error')
    return redirect(url_for('admin_system'))


@app.route('/<slug>/calendar/google')
def generate_google_calendar_link(slug):
    event = get_public_event(slug)
    return redirect(generate_google_calendar_url(event)) if event else ('Event not found', 404)


@app.route('/<slug>/calendar/ics')
def download_ics_file(slug):
    event = get_public_event(slug)
    if not event:
        return 'Event not found', 404
    return Response(generate_ics_file(event), mimetype='text/calendar', headers={'Content-Disposition': f'attachment;filename={slug}.ics'})


@app.route('/healthz')
def healthz():
    """Verify the promoted process serves the expected release."""
    return jsonify(status='ok', release=app.config.get('RELEASE_ID', 'local'))


@app.errorhandler(RequestEntityTooLarge)
def too_large(error):
    return jsonify(error='Upload is too large. Choose an image smaller than 8 MB.'), 413


if __name__ == '__main__':
    app.run(port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('RSVP_DEBUG') == '1')

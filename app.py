import json
import os
import pickle
import re
import uuid
from datetime import datetime
import markdown
import logging
from export_rsvps import generate_rsvps_csv, get_csv_filename
from flask import send_file, Response
from io import BytesIO
from calendar_utils import generate_google_calendar_url, generate_ics_file
from date_validation import validate_date_time

from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session
from google_auth_oauthlib.flow import Flow

from event_config import get_event_config, get_all_events, update_event_config, add_new_event, format_event_time
from email_handler import send_email
from email_content import generate_confirmation_email_body, generate_invitation_email_body
from notifications import notify_phone
from passkey_auth import passkey_bp, admin_required, get_current_admin

app = Flask(__name__)

# Load configuration
try:
    app.config.from_pyfile('config.py')
except FileNotFoundError:
    raise FileNotFoundError("config.py file not found. Please create it with the required configuration.")

app.secret_key = app.config['SECRET_KEY']

# Register passkey blueprint
app.register_blueprint(passkey_bp)

# Register template filter for formatting event time
app.jinja_env.filters['format_time'] = format_event_time

def load_rsvps(slug):
    try:
        with open(f'rsvps_{slug}.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_rsvps(slug, rsvps):
    # Write to temp file first, then atomically rename to avoid data loss
    temp_file = f'rsvps_{slug}.json.tmp'
    target_file = f'rsvps_{slug}.json'

    with open(temp_file, 'w') as f:
        json.dump(rsvps, f, indent=2)
        f.flush()
        os.fsync(f.fileno())  # Ensure data is written to disk

    # Atomic rename - if this succeeds, we never have a corrupt/empty file
    os.replace(temp_file, target_file)


@app.route('/admin/<path:slug>/export')
@admin_required
def export_rsvps(slug):
    event_config = get_event_config(slug)
    if not event_config:
        return "Event not found", 404
        
    rsvps = load_rsvps(event_config['id'])
    csv_data = generate_rsvps_csv(rsvps)
    
    if not csv_data:
        flash('No RSVPs to export', 'error')
        return redirect(url_for('admin', slug=slug))
    
    si = BytesIO()
    si.write(csv_data.encode('utf-8-sig'))  # utf-8-sig adds BOM for Excel compatibility
    si.seek(0)
    
    filename = get_csv_filename(event_config['name'])
    
    return send_file(
        si,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


@app.before_request
def before_request():
    app.logger.debug(f"Session: {session}")
    app.logger.debug(f"Request path: {request.path}")

@app.route('/<slug>')
def event_page(slug):
    app.logger.info(f"Attempting to load event with slug: {slug}")
    event_config = get_event_config(slug)
    if not event_config:
        return "Event not found", 404
    
    # Convert Markdown description to HTML
    event_config['description_html'] = markdown.markdown(event_config['description'])
    
    rsvps = load_rsvps(event_config['id'])
    attendees = [
        {
            'first_name': rsvp['name'].split()[0],
            'last_initial': rsvp['name'].split()[-1][0].upper(),
            'guest_info': f" +{rsvp.get('num_adults', 1) + rsvp.get('num_children', 0) - 1}" 
                if (rsvp.get('num_adults', 1) + rsvp.get('num_children', 0)) > 1 
                else ""
        }
        for rsvp in rsvps if rsvp.get('attending') == 'yes'
    ]

    return render_template('index.html', event=event_config, attendees=attendees)

# Landing page route
@app.route('/')
def index():
    return render_template('landing.html')

@app.route('/<slug>/rsvp', methods=['POST'])
def rsvp(slug):
    event_config = get_event_config(slug)
    if not event_config:
        return "Event not found", 404
        
    # Check honeypot field - if it's filled out, it's probably a bot
    if request.form.get('website', ''):
        # Silently redirect to thank you page without saving the RSVP
        # This way bots don't know they were detected
        bot_info = f"Bot detected: {request.form.get('name')} / {request.form.get('email')}"
        app.logger.warning(f"Bot submission detected for event {event_config['name']}: {bot_info}")
        
        # Send phone notification about bot submission
        notify_phone(f"BOT RSVP for {event_config['name']}: {bot_info}")
        
        return redirect(url_for('thank_you', slug=event_config['slug'], 
                               attending=request.form.get('attending', 'no')))

    rsvps = load_rsvps(event_config['id'])
    rsvp_token = str(uuid.uuid4())
    new_rsvp = {
        'timestamp': datetime.now().isoformat(),
        'name': request.form['name'],
        'email': request.form['email'],
        'attending': request.form['attending'],
        'num_adults': int(request.form['num_adults']),
        'num_children': int(request.form['num_children']),
        'dietary_restrictions': request.form.get('dietary_restrictions', ''),
        'comment': request.form.get('comment', ''),
        'token': rsvp_token,
    }
    rsvps.append(new_rsvp)
    save_rsvps(event_config['id'], rsvps)
    
    # Send confirmation email
    update_url = url_for('update_rsvp', slug=event_config['slug'], token=rsvp_token, _external=True)
    subject = f"RSVP Confirmation for {event_config['name']}"
    body = generate_confirmation_email_body(event_config, new_rsvp, update_url)
    try:
      send_email(new_rsvp['email'], subject, body)
    except Exception as e:
      app.logger.error(f"Failed to send confirmation email: {e}")
    
    # Notify about legitimate RSVP
    rsvp_info = f"{new_rsvp['name']} / {new_rsvp['attending']}"
    notify_phone(f"New RSVP for {event_config['name']}: {rsvp_info}")
    
    return redirect(url_for('thank_you', slug=event_config['slug'], **new_rsvp))

@app.route('/<slug>/thank-you')
def thank_you(slug):
    event_config = get_event_config(slug)
    if not event_config:
        return "Event not found", 404
    
    # Convert Markdown description to HTML
    event_config['description_html'] = markdown.markdown(event_config['description'])
    
    return render_template('thank_you.html', event=event_config, **request.args)

@app.route('/<slug>/update-rsvp/<token>', methods=['GET', 'POST'])
def update_rsvp(slug, token):
    event_config = get_event_config(slug)
    if not event_config:
        return "Event not found", 404

    rsvps = load_rsvps(event_config['id'])
    rsvp_entry = next((r for r in rsvps if r.get('token') == token), None)
    if not rsvp_entry:
        return "RSVP not found", 404

    if request.method == 'POST':
        new_attending = request.form['attending']
        rsvp_entry['attending'] = new_attending
        if new_attending == 'no':
            rsvp_entry['num_adults'] = 0
            rsvp_entry['num_children'] = 0
        elif new_attending == 'yes':
            rsvp_entry['num_adults'] = int(request.form.get('num_adults', 1))
            rsvp_entry['num_children'] = int(request.form.get('num_children', 0))
            rsvp_entry['dietary_restrictions'] = request.form.get('dietary_restrictions', '')
        rsvp_entry['updated_at'] = datetime.now().isoformat()
        save_rsvps(event_config['id'], rsvps)

        notify_phone(f"RSVP updated for {event_config['name']}: {rsvp_entry['name']} → {new_attending}")

        return redirect(url_for('thank_you', slug=slug, name=rsvp_entry['name'], attending=new_attending))

    event_config['description_html'] = markdown.markdown(event_config['description'])
    return render_template('update_rsvp.html', event=event_config, rsvp=rsvp_entry)

@app.route('/static/<path:file>')
def serve_static(file):
    return send_from_directory('static', file)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['password'] == app.config['ADMIN_PASSWORD']:
            # Password login: find or create the owner admin
            from passkey_auth import _load_data, _save_data
            data = _load_data()
            owner = next((a for a in data['admins'] if a.get('is_owner')), None)
            if not owner:
                # Bootstrap: create owner admin on first password login
                import uuid as _uuid
                owner = {
                    'id': str(_uuid.uuid4()),
                    'name': 'Owner',
                    'is_owner': True,
                    'credentials': [],
                    'created_at': datetime.now().isoformat(),
                }
                data['admins'].append(owner)
                _save_data(data)
            session['admin_id'] = owner['id']
            next_page = request.args.get('next')
            return redirect(next_page or url_for('admin_dashboard'))
        else:
            flash('Invalid password', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    events = get_all_events()
    return render_template('admin_dashboard.html', events=events)

@app.route('/admin/new_event', methods=['POST'])
@admin_required
def new_event():
    if request.method == 'POST':
        # Validate event name
        event_name = request.form.get('name', '').strip()
        if not event_name:
            flash('Error: Event name cannot be empty', 'error')
            return redirect(url_for('admin_dashboard'))

        # Check for duplicate event names
        existing_events = get_all_events()
        for slug, event in existing_events.items():
            if event['name'].lower() == event_name.lower():
                flash(f'Error: An event named "{event_name}" already exists', 'error')
                return redirect(url_for('admin_dashboard'))

        # Validate date and time
        date_str = request.form['date']
        start_time_str = request.form['start_time']
        end_time_str = request.form.get('end_time', '').strip()

        is_valid, error_message = validate_date_time(date_str, start_time_str, end_time_str or None)

        if not is_valid:
            flash(f'Error: {error_message}', 'error')
            return redirect(url_for('admin_dashboard'))

        event_data = {
            'name': event_name,
            'slug': request.form.get('slug', '').strip(),
            'date': date_str,
            'start_time': start_time_str,
            'end_time': end_time_str,
            'location': request.form['location'],
            'description': request.form['description'],
            'max_guests_per_invite': request.form['max_guests_per_invite'],
            'color_scheme': request.form.get('color_scheme', 'pink')
        }
        try:
            add_new_event(event_data)
            flash('New event created successfully!', 'success')
        except Exception as e:
            flash(f'Error creating new event: {str(e)}', 'error')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/<path:slug>', methods=['GET', 'POST'])
@admin_required
def admin(slug):
    event_config = get_event_config(slug)
    if not event_config:
        return "Event not found", 404

    rsvps = load_rsvps(event_config['id'])

    if request.method == 'POST':
        if 'update_event' in request.form:
            # Validate date and time
            date_str = request.form['date']
            start_time_str = request.form['start_time']
            end_time_str = request.form.get('end_time', '').strip()

            is_valid, error_message = validate_date_time(date_str, start_time_str, end_time_str or None)

            if not is_valid:
                flash(f'Error: {error_message}', 'error')
                return redirect(url_for('admin', slug=slug))

            # Update event configuration
            new_config = {
                "domain": "partymail.app",  # Keep the original domain
                "id": event_config['id'],  # Keep the original ID
                "slug": slug,
                "name": request.form['name'],
                "date": date_str,
                "start_time": start_time_str,
                "end_time": end_time_str,
                "location": request.form['location'],
                "description": request.form['description'],
                "max_guests_per_invite": int(request.form['max_guests_per_invite']),
                "color_scheme": request.form['color_scheme']  # Add color scheme
            }
            update_event_config(slug, new_config)
            flash('Event details updated successfully!', 'success')
            return redirect(url_for('admin', slug=slug))
        elif 'send_invitation' in request.form:
            # Existing invitation sending logic
            email = request.form['email']
            subject = f"RSVP Request for {event_config['name']}"
            body = generate_invitation_email_body(event_config)
            html_body = render_template('email_invitation.html', event=event_config)
            
            if send_email(email, subject, body, html_body):
                flash('Invitation sent successfully!', 'success')
            else:
                flash('Failed to send invitation.', 'error')

    return render_template('admin_event.html', event=event_config, rsvps=rsvps, slug=slug)

@app.route('/oauth2callback')
def oauth2callback():
    # This route will handle the OAuth callback
    flow = Flow.from_client_secrets_file(
        'credentials.json',
        scopes=['https://www.googleapis.com/auth/gmail.send'],
        redirect_uri=url_for('oauth2callback', _external=True)
    )
    
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    
    # Save the credentials for future use
    with open('token.pickle', 'wb') as token:
        pickle.dump(credentials, token)
    
    flash('Successfully authenticated with Google', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/<slug>/calendar/google')
def generate_google_calendar_link(slug):
    """Generate a Google Calendar event link"""
    event_config = get_event_config(slug)
    if not event_config:
        return "Event not found", 404
        
    calendar_url = generate_google_calendar_url(event_config)
    return redirect(calendar_url)

@app.route('/<slug>/calendar/ics')
def download_ics_file(slug):
    """Generate and download an ICS file for Apple Calendar, Outlook, etc."""
    event_config = get_event_config(slug)
    if not event_config:
        return "Event not found", 404
        
    ics_content = generate_ics_file(event_config)
    
    # Return ICS file
    return Response(
        ics_content,
        mimetype="text/calendar",
        headers={"Content-Disposition": f"attachment;filename={event_config['slug']}.ics"}
    )

if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # To allow OAuth on http://localhost
    app.run(port=5000, debug=True)
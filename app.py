import json
import os
import pickle
from datetime import datetime
from functools import wraps
import markdown
import logging
from export_rsvps import generate_rsvps_csv, get_csv_filename
from flask import send_file
from io import BytesIO

from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session
from google_auth_oauthlib.flow import Flow

from event_config import get_event_config, get_all_events, update_event_config, add_new_event
from email_handler import send_email
from email_content import generate_confirmation_email_body, generate_invitation_email_body

app = Flask(__name__)

# Load configuration
try:
    app.config.from_pyfile('config.py')
except FileNotFoundError:
    raise FileNotFoundError("config.py file not found. Please create it with the required configuration.")

app.secret_key = app.config['SECRET_KEY']

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def load_rsvps(slug):
    try:
        with open(f'rsvps_{slug}.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_rsvps(slug, rsvps):
    with open(f'rsvps_{slug}.json', 'w') as f:
        json.dump(rsvps, f, indent=2)


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

# Modify the index route to handle both domain and slug
@app.route('/')
def index():
    return event_page("ariana4th")

@app.route('/<slug>/rsvp', methods=['POST'])
def rsvp(slug):
    event_config = get_event_config(slug)
    if not event_config:
        return "Event not found", 404

    rsvps = load_rsvps(event_config['id'])
    new_rsvp = {
        'timestamp': datetime.now().isoformat(),
        'name': request.form['name'],
        'email': request.form['email'],
        'attending': request.form['attending'],
        'num_adults': int(request.form['num_adults']),
        'num_children': int(request.form['num_children']),
        'dietary_restrictions': request.form.get('dietary_restrictions', ''),
    }
    rsvps.append(new_rsvp)
    save_rsvps(event_config['id'], rsvps)
    
    # Send confirmation email
    subject = f"RSVP Confirmation for {event_config['name']}"
    body = generate_confirmation_email_body(event_config, new_rsvp)
    try:
      send_email(new_rsvp['email'], subject, body)
    except Exception as e:
      app.logger.error(f"Failed to send confirmation email: {e}")
    
    return redirect(url_for('thank_you', slug=event_config['slug'], **new_rsvp))

@app.route('/<slug>/thank-you')
def thank_you(slug):
    events = get_all_events()
    event_config = next((event for event in events.values() if event['slug'] == slug), None)
    if not event_config:
        return "Event not found", 404
    
    # Convert Markdown description to HTML
    event_config['description_html'] = markdown.markdown(event_config['description'])
    
    return render_template('thank_you.html', event=event_config, **request.args)

@app.route('/static/<path:file>')
def serve_static(file):
    return send_from_directory('static', file)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['password'] == app.config['ADMIN_PASSWORD']:
            session['admin_logged_in'] = True
            next_page = request.args.get('next')
            return redirect(next_page or url_for('admin_dashboard'))
        else:
            flash('Invalid password', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
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
        domain = request.form['domain']
        event_data = {
            'name': request.form['name'],
            'date': request.form['date'],
            'time': request.form['time'],
            'location': request.form['location'],
            'description': request.form['description'],
            'max_guests_per_invite': request.form['max_guests_per_invite']
        }
        try:
            add_new_event(domain, event_data)
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
            # Update event configuration
            new_config = {
                "domain": "partymail.app",  # Keep the original domain
                "id": event_config['id'],  # Keep the original ID
                "slug": slug,
                "name": request.form['name'],
                "date": request.form['date'],
                "time": request.form['time'],
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

if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # To allow OAuth on http://localhost
    app.run(port=5000, debug=True)
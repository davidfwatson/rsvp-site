import json
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session
from datetime import datetime
from event_config import get_event_config, get_all_events
from email_handler import send_email, get_credentials
from email_content import generate_confirmation_email_body, generate_invitation_email_body
from functools import wraps
from google_auth_oauthlib.flow import Flow
import os
import pickle

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

def load_rsvps(event_id):
    try:
        with open(f'rsvps_{event_id}.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_rsvps(event_id, rsvps):
    with open(f'rsvps_{event_id}.json', 'w') as f:
        json.dump(rsvps, f, indent=2)

@app.route('/')
def index():
    event_config = get_event_config(request.host)
    if not event_config:
        return "Event not found", 404
    return render_template('index.html', event=event_config)

@app.route('/rsvp', methods=['POST'])
def rsvp():
    event_config = get_event_config(request.host)
    if not event_config:
        return "Event not found", 404

    rsvps = load_rsvps(event_config['id'])
    new_rsvp = {
        'timestamp': datetime.now().isoformat(),
        'name': request.form['name'],
        'email': request.form['email'],
        'attending': request.form['attending'],
        'num_guests': int(request.form['num_guests']),
    }
    rsvps.append(new_rsvp)
    save_rsvps(event_config['id'], rsvps)
    
    # Send confirmation email
    subject = f"RSVP Confirmation for {event_config['name']}"
    body = generate_confirmation_email_body(event_config, new_rsvp)
    send_email(new_rsvp['email'], subject, body)
    
    return redirect(url_for('thank_you', **new_rsvp))

@app.route('/thank-you')
def thank_you():
    event_config = get_event_config(request.host)
    if not event_config:
        return "Event not found", 404

    name = request.args.get('name', 'Guest')
    attending = request.args.get('attending', 'yes')
    num_guests = request.args.get('num_guests', 1)
    return render_template('thank_you.html', event=event_config, name=name, attending=attending, num_guests=num_guests)

@app.route('/static/<file>')
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

@app.route('/admin/<path:event_domain>', methods=['GET', 'POST'])
@admin_required
def admin(event_domain):
    event_config = get_event_config(event_domain)
    if not event_config:
        return "Event not found", 404

    rsvps = load_rsvps(event_config['id'])

    if request.method == 'POST':
        email = request.form['email']
        subject = f"RSVP Request for {event_config['name']}"
        body = generate_invitation_email_body(event_config, event_domain)
        html_body = render_template('email_invitation.html', event=event_config)
        
        if send_email(email, subject, body, html_body):
            flash('Invitation sent successfully!', 'success')
        else:
            flash('Failed to send invitation.', 'error')

    return render_template('admin_event.html', event=event_config, rsvps=rsvps)


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
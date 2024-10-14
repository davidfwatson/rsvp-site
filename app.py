import json
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session
from datetime import datetime
from event_config import get_event_config
from email_handler import send_email
from functools import wraps

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

@app.route('/<event_id>')
def index(event_id):
    event_config = get_event_config(event_id)
    if not event_config:
        return "Event not found", 404
    return render_template('index.html', event=event_config)

@app.route('/<event_id>/rsvp', methods=['POST'])
def rsvp(event_id):
    event_config = get_event_config(event_id)
    if not event_config:
        return "Event not found", 404

    rsvps = load_rsvps(event_id)
    new_rsvp = {
        'timestamp': datetime.now().isoformat(),
        'name': request.form['name'],
        'email': request.form['email'],
        'attending': request.form['attending'],
        'num_guests': int(request.form['num_guests']),
    }
    rsvps.append(new_rsvp)
    save_rsvps(event_id, rsvps)
    
    # Send confirmation email
    subject = f"RSVP Confirmation for {event_config['name']}"
    body = generate_email_body(event_config, new_rsvp)
    send_email(new_rsvp['email'], subject, body)
    
    return redirect(url_for('thank_you', event_id=event_id, **new_rsvp))

@app.route('/<event_id>/thank-you')
def thank_you(event_id):
    event_config = get_event_config(event_id)
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
    events = list(get_event_config().keys())
    return render_template('admin_dashboard.html', events=events)

@app.route('/<event_id>/admin', methods=['GET', 'POST'])
@admin_required
def admin(event_id):
    event_config = get_event_config(event_id)
    if not event_config:
        return "Event not found", 404

    rsvps = load_rsvps(event_id)

    if request.method == 'POST':
        email = request.form['email']
        subject = f"RSVP Request for {event_config['name']}"
        body = generate_invitation_email_body(event_config)
        html_body = render_template('email_invitation.html', event=event_config)
        
        if send_email(email, subject, body, html_body):
            flash('Invitation sent successfully!', 'success')
        else:
            flash('Failed to send invitation.', 'error')

    return render_template('admin.html', event=event_config, rsvps=rsvps)

def generate_email_body(event, rsvp):
    # ... (same as before)

def generate_invitation_email_body(event):
    # ... (same as before)

if __name__ == '__main__':
    app.run(debug=True)
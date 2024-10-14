import json
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
from datetime import datetime
from event_config import get_event_config
from email_handler import send_email

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a real secret key

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

@app.route('/<event_id>/admin', methods=['GET', 'POST'])
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
    if rsvp['attending'] == 'yes':
        body = f"""
# Thank you for your RSVP, {rsvp['name']}!

We're excited that you'll be joining us for **{event['name']}**!

## Event Details:
- **Date:** {event['date']} at {event['time']}
- **Location:** {event['location']}

{event['description']}

We have you down for **{rsvp['num_guests']}** guest(s) total.

If you need to make any changes to your RSVP, please contact us.

We look forward to seeing you there!
"""
    else:
        body = f"""
# Thank you for your RSVP, {rsvp['name']}

We're sorry to hear that you won't be able to join us for **{event['name']}**, but we appreciate you letting us know.

If your plans change and you're able to attend, please let us know.

We hope to see you another time!
"""
    return body

def generate_invitation_email_body(event):
    return f"""
You're invited to {event['name']}!

Join us for a special event:

Date: {event['date']} at {event['time']}
Location: {event['location']}

{event['description']}

Please RSVP by visiting: {url_for('index', event_id=event['id'], _external=True)}

We hope to see you there!
"""

if __name__ == '__main__':
    app.run(debug=True)
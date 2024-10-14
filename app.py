import json
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from datetime import datetime
from event_config import get_event_config

app = Flask(__name__)

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
        'attending': request.form['attending'],
        'num_guests': int(request.form['num_guests']),
        # Add any additional fields here in the future
    }
    rsvps.append(new_rsvp)
    save_rsvps(event_id, rsvps)
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

@app.route('/<event_id>/admin')
def admin(event_id):
    event_config = get_event_config(event_id)
    if not event_config:
        return "Event not found", 404

    rsvps = load_rsvps(event_id)
    return render_template('admin.html', event=event_config, rsvps=rsvps)

if __name__ == '__main__':
    app.run(debug=True)
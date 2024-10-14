import json
from flask import Flask, render_template, request, redirect, send_from_directory
from datetime import datetime

app = Flask(__name__)

def load_rsvps():
    try:
        with open('rsvps.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_rsvps(rsvps):
    with open('rsvps.json', 'w') as f:
        json.dump(rsvps, f, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/rsvp', methods=['POST'])
def rsvp():
    rsvps = load_rsvps()
    new_rsvp = {
        'timestamp': datetime.now().isoformat(),
        'name': request.form['name'],
        'attending': request.form['attending'],
        # Add any additional fields here in the future
    }
    rsvps.append(new_rsvp)
    save_rsvps(rsvps)
    return redirect('/thank-you')

@app.route('/thank-you')
def thank_you():
    return 'Thank you for your RSVP!'

@app.route('/static/<file>')
def serve_static(file):
    return send_from_directory('static', file)

@app.route('/admin')
def admin():
    rsvps = load_rsvps()
    return render_template('admin.html', rsvps=rsvps)

if __name__ == '__main__':
    app.run(debug=True)
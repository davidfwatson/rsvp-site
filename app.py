from flask import Flask, render_template, request, redirect, send_from_directory


app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/rsvp', methods=['POST'])
def rsvp():
    name = request.form['name']
    attending = request.form['attending']
    # Here, you'd save the RSVP to a database or file
    with open('rsvp.txt', 'a') as f:
        f.write(f'{name} - Attending: {attending}\n')
    return redirect('/thank-you')

@app.route('/thank-you')
def thank_you():
    return 'Thank you for your RSVP!'

@app.route('/static/<file>')
def serve_static(file):
    print(f'Serving static file: {file}')
    return send_from_directory('static', file)

if __name__ == '__main__':
    app.run()

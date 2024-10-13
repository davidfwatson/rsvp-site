# rsvp-site



These were the original instructions I used to set up the site.
---

### **Setup Instructions for `rsvp-site` Flask Application**

#### 1. **Create a Separate Flask App for `rsvp-site`:**
   - Set up a new Flask app directory for the RSVP site. You can create a directory like `/home/david/webserver/rsvp-site/`.

   - Inside this directory, create a basic Flask app:

     ```bash
     mkdir -p /home/david/webserver/rsvp-site
     cd /home/david/webserver/rsvp-site
     nano app.py
     ```

     Here’s an example `app.py`:

     ```python
     from flask import Flask, render_template, request, redirect

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

     if __name__ == '__main__':
         app.run()
     ```

#### 2. **Create the HTML Templates:**
   - Create a `templates` directory and an `index.html` file for the invite form:

     ```bash
     mkdir templates
     nano templates/index.html
     ```

     Example content for `index.html`:

     ```html
     <!DOCTYPE html>
     <html lang="en">
     <head>
         <meta charset="UTF-8">
         <meta name="viewport" content="width=device-width, initial-scale=1.0">
         <title>RSVP for the Event</title>
     </head>
     <body>
         <h1>You're Invited!</h1>
         <form action="/rsvp" method="POST">
             <label for="name">Your Name:</label>
             <input type="text" id="name" name="name" required><br><br>
             <label for="attending">Will you attend?</label>
             <input type="radio" id="yes" name="attending" value="yes" required>
             <label for="yes">Yes</label>
             <input type="radio" id="no" name="attending" value="no" required>
             <label for="no">No</label><br><br>
             <button type="submit">Submit RSVP</button>
         </form>
     </body>
     </html>
     ```

#### 3. **Set Up uWSGI for the Flask App:**
   - Create a `uwsgi` configuration file for this app:

     ```bash
     nano /home/david/webserver/rsvp-site/rsvp-site.ini
     ```

     Example content:

     ```ini
    [uwsgi]
    module = app:app
    master = true
    process = 5
    socket = /home/david/webserver/rsvp-site/rsvp-site.sock
    chmod-socket = 660
    vacuum = true
    die-on-term = true
     ```

#### 4. **Configure Nginx for the Flask App:**
   - Modify `/etc/nginx/sites-available/test-davidfwatson` to proxy requests to the new Flask app.

     Update the location block to use uWSGI for the Flask app:

     ```nginx
server {
    server_name test.davidfwatson.com;
    
    location ~ /.well-known {
        root /etc/letsencrypt/verification;
    }

    listen 443 ssl; # managed by Certbot
    
    # Proxy to uWSGI for Flask app
    location / {
        include uwsgi_params;
        uwsgi_pass unix:/home/david/webserver/rsvp-site/rsvp-site.sock;  # Path to the uWSGI socket for rsvp-site
    }

    client_max_body_size 100M;

    ssl_certificate /etc/letsencrypt/live/test.davidfwatson.com/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/test.davidfwatson.com/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}

server {
    if ($host = test.davidfwatson.com) {
        return 301 https://$host$request_uri;
    } # managed by Certbot

    listen 80;
    server_name test.davidfwatson.com;
    return 404; # managed by Certbot
}

     ```

#### 5. **Set Up a Systemd Service for the Flask App:**
   - Create a new systemd service file to manage the `rsvp-site` Flask app.

     ```bash
     sudo nano /etc/systemd/system/rsvp-site.service
     ```

     Example content:

     ```ini
[Unit]
Description=uWSGI instance to serve rsvp-site
After=network.target

[Service]
User=david
Group=www-data
WorkingDirectory=/home/david/webserver/rsvp-site
Environment="PATH=/home/david/webserver/rsvp-site/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/david/webserver/rsvp-site/venv/bin/uwsgi --ini rsvp-site.ini

[Install]
WantedBy=multi-user.target
     ```

   - Reload systemd and start the service:

     ```bash
     sudo systemctl daemon-reload
     sudo systemctl start rsvp-site
     sudo systemctl enable rsvp-site
     ```

#### 6. **Test the Setup:**
   - After starting the service, restart Nginx:
     ```bash
     sudo systemctl restart nginx
     ```

   - Visit `https://test.davidfwatson.com` and you should see your RSVP form. Submissions will be saved to a text file (`rsvp.txt`), or you can modify it to store the data in a database.

---

### Summary:
- **Project Name**: `rsvp-site`
- **Directory**: `/home/david/webserver/rsvp-site`
- **Flask app**: Handles the form submission and RSVP storage
- **Nginx**: Configured to proxy requests to the uWSGI instance running the Flask app
- **Systemd Service**: Manages the uWSGI instance

With these instructions saved, you can easily adapt this setup for other RSVP-style sites or expand it further as needed.
import os
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from base64 import urlsafe_b64encode
import markdown as md
from flask import current_app, url_for

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

CREDENTIALS_FILE_PATH = "credentials.json"
TOKEN_FILE_PATH = "token.pickle"

def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE_PATH):
        with open(TOKEN_FILE_PATH, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = Flow.from_client_secrets_file(
                CREDENTIALS_FILE_PATH,
                scopes=SCOPES,
                redirect_uri=url_for('oauth2callback', _external=True)
            )
            auth_url, _ = flow.authorization_url(prompt='consent')
            print(f"Please visit this URL to authorize the application: {auth_url}")
            
            # In a real application, you'd redirect the user to auth_url
            # and handle the callback in the oauth2callback route
            # For now, we'll use a simple input to simulate the process
            code = input("Enter the authorization code: ")
            flow.fetch_token(code=code)
            creds = flow.credentials

        with open(TOKEN_FILE_PATH, 'wb') as token:
            pickle.dump(creds, token)
    return creds

def build_message(destination, subject, body, html_body=None):
    message = MIMEMultipart('alternative')
    message['to'] = destination
    message['from'] = current_app.config['SENDER_EMAIL']
    message['subject'] = subject
    
    message.attach(MIMEText(body, 'plain'))
    if html_body:
        message.attach(MIMEText(html_body, 'html'))
    else:
        message.attach(MIMEText(md.markdown(body), 'html'))
    
    return {'raw': urlsafe_b64encode(message.as_bytes()).decode()}

def send_email(destination, subject, body, html_body=None):
    creds = get_credentials()
    try:
        service = build('gmail', 'v1', credentials=creds)
        message = build_message(destination, subject, body, html_body)
        sent_message = service.users().messages().send(userId="me", body=message).execute()
        print(f"Message Id: {sent_message['id']}")
        return True
    except HttpError as error:
        print(f'An error occurred: {error}')
        return False
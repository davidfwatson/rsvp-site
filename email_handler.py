import os
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from base64 import urlsafe_b64encode
import markdown as md
from flask import current_app

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
]

CREDENTIALS_FILE_PATH = "credentials.json"
TOKEN_FILE_PATH = "token.pickle"

def get_credentials():
    # ... (same as before)

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
    # ... (same as before)
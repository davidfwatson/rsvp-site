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

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
]

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
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE_PATH, 'wb') as token:
            pickle.dump(creds, token)
    return creds

def build_message(destination, subject, body):
    message = MIMEMultipart('alternative')
    message['to'] = destination
    message['from'] = "your-email@gmail.com"  # Replace with your email
    message['subject'] = subject
    
    # Convert Markdown to HTML
    html_body = md.markdown(body)
    
    # Attach both plain text and HTML versions
    message.attach(MIMEText(body, 'plain'))
    message.attach(MIMEText(html_body, 'html'))
    
    return {'raw': urlsafe_b64encode(message.as_bytes()).decode()}

def send_email(destination, subject, body):
    creds = get_credentials()
    try:
        service = build('gmail', 'v1', credentials=creds)
        message = build_message(destination, subject, body)
        sent_message = service.users().messages().send(userId="me", body=message).execute()
        print(f"Message Id: {sent_message['id']}")
        return True
    except HttpError as error:
        print(f'An error occurred: {error}')
        return False
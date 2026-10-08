"""Noninteractive Gmail delivery using credentials outside release code."""
import json
from base64 import urlsafe_b64encode
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import bleach
import markdown
import httplib2
from flask import current_app
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from runtime_config import data_path
from storage import json_lock, read_json, write_json

SCOPES = ['https://www.googleapis.com/auth/gmail.send']


def get_credentials():
    """Read JSON tokens; OAuth setup is explicit in the owner connections page."""
    path = data_path('token.json')
    with json_lock(path):
        info = read_json(path, None)
        if not info:
            raise RuntimeError('Connect Google email in Connections first.')
        credentials = Credentials.from_authorized_user_info(info, SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(lambda *args, **kwargs: Request()(*args, **{**kwargs, 'timeout': 15}))
            write_json(path, json.loads(credentials.to_json()))
        if not credentials.valid:
            raise RuntimeError('Google email needs to be reconnected.')
    return credentials


def build_message(destination, subject, body, html_body=None):
    """Build multipart mail with safe Markdown fallback."""
    message = MIMEMultipart('alternative')
    message['to'] = destination
    message['from'] = current_app.config['SENDER_EMAIL']
    message['subject'] = subject
    message.attach(MIMEText(body, 'plain', 'utf-8'))
    if html_body is None:
        html_body = bleach.clean(markdown.markdown(body), tags=['p','strong','em','h1','h2','h3','ul','li','a','br'], attributes={'a':['href']}, strip=True)
    message.attach(MIMEText(html_body, 'html', 'utf-8'))
    return {'raw': urlsafe_b64encode(message.as_bytes()).decode()}


def send_email(destination, subject, body, html_body=None):
    """Send through Gmail; return false on delivery errors."""
    try:
        http = AuthorizedHttp(get_credentials(), http=httplib2.Http(timeout=15))
        service = build('gmail', 'v1', http=http, cache_discovery=False)
        service.users().messages().send(userId='me', body=build_message(destination, subject, body, html_body)).execute()
        return True
    except HttpError:
        current_app.logger.exception('Gmail delivery failed')
        return False

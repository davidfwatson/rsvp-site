#!/usr/bin/python3

import http.client
import urllib
import sys
import logging
import datetime

def notify_phone(message:str="Hello World", url=None):
    """
    Send a push notification to phone using Pushover API.
    
    Args:
        message: The notification message
        url: Optional URL to include in the notification
    """
    if 'unittest' in sys.modules.keys():
        logging.error(f"Skip Notify Phone in Tests: {message}")
        return
        
    conn = http.client.HTTPSConnection("api.pushover.net:443")
    
    payload = {
        "token": "ag736guuyi6uqvb6udugvdjn1p5zv9",
        "user": "u4qmnr2hzb7ime2cg6751brue1wd4d",
        "message": message
    }
    
    if url:
        payload["url"] = url
        
    conn.request(
        "POST", 
        "/1/messages.json",
        urllib.parse.urlencode(payload), 
        {"Content-type": "application/x-www-form-urlencoded"}
    )
    
    response = conn.getresponse()
    return response.status == 200

if __name__ == "__main__":
    # When run directly, send a test notification
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = notify_phone(f"Test notification from RSVP site at {timestamp}")
    
    if result:
        print("✅ Notification sent successfully!")
    else:
        print("❌ Failed to send notification.")
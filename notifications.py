#!/usr/bin/python3
"""Compatibility shim — forwards to notify-service.

The Pushover token + outbound HTTPS call live in the notify-service
microservice (https://github.com/davidfwatson/notify-service). This
module keeps the legacy notify_phone(message, url=None) signature so
app.py callers don't change.
"""

import datetime
import logging
import sys

from notify_service.client import NotifyClient


_client = NotifyClient()


def notify_phone(message: str = "Hello World", url=None):
  """Send a push notification to phone via notify-service.

  Returns True on success, False on failure (matches legacy behavior of
  returning a bool that callers ignore in practice).
  """
  if "unittest" in sys.modules.keys():
    logging.error(f"Skip Notify Phone in Tests: {message}")
    return True

  try:
    status, body = _client.phone(message=message, url=url)
    return bool(body and body.get("ok"))
  except Exception as e:
    logging.warning("notify_phone failed: %s (msg=%r)", e, str(message)[:80])
    return False


if __name__ == "__main__":
  timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  result = notify_phone(f"Test notification from RSVP site at {timestamp}")
  print("Notification sent successfully!" if result else "Failed to send notification.")

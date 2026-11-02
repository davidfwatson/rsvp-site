from flask import current_app, url_for
from event_config import format_event_time


def generate_confirmation_email_body(event, rsvp, update_url=None):
  update_info = ""
  if update_url:
    update_info = f"\n\n[Update your RSVP]({update_url}) if your plans change."

  if rsvp['attending'] in ('yes', 'maybe'):
    adults, children = rsvp['num_adults'], rsvp['num_children']
    parts = []
    if adults > 0:
      parts.append(f"{adults} adult{'s' if adults != 1 else ''}")
    if children > 0:
      parts.append(f"{children} child{'ren' if children != 1 else ''}")
    guest_details = " and ".join(parts) + ("" if adults else " (drop-off)")
    welcome = "We're excited that you'll be joining us for" if adults else "We're excited to welcome your kids to"
    closing = "We look forward to seeing you there!"
    if rsvp['attending'] == 'maybe':
      welcome = "We hope you'll be able to join us for"
      closing = "Let us know once you're sure."
      guest_details += ", if you can make it"

    dietary_info = ""
    if rsvp.get('dietary_restrictions'):
      dietary_info = f"\n\nYou've noted the following dietary restrictions:\n{rsvp['dietary_restrictions']}"

    event_time = format_event_time(event)
    body = f"""
# Thank you for your RSVP, {rsvp['name']}!

{welcome} **{event['name']}**!

## Event Details:
- **Date:** {event['date']} at {event_time}
- **Location:** {event['location']}

{event['description']}

We have you down for **{guest_details}**.{dietary_info}

{closing}{update_info}
"""
  else:
    body = f"""
# Thank you for your RSVP, {rsvp['name']}!

We're sorry you won't be able to join us for **{event['name']}**, but we appreciate you letting us know.

We hope to see you another time!{update_info}
"""

  return body


def generate_invitation_email_body(event):
  event_time = format_event_time(event)
  return f"""
You're invited to {event['name']}!

Join us for a special event:

Date: {event['date']} at {event_time}
Location: {event['location']}

{event['description']}

Please RSVP by visiting: {current_app.config['PUBLIC_URL'].rstrip('/')}{url_for('event_page', slug=event['slug'])}

We hope to see you there!
"""

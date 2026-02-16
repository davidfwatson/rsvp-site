from flask import url_for
from event_config import format_event_time


def generate_confirmation_email_body(event, rsvp, update_url=None):
  update_info = ""
  if update_url:
    update_info = f"\n\n[Update your RSVP]({update_url}) if your plans change."

  if rsvp['attending'] == 'yes':
    guest_details = f"{rsvp['num_adults']} adult{'s' if rsvp['num_adults'] != 1 else ''}"
    if rsvp['num_children'] > 0:
      guest_details += f" and {rsvp['num_children']} child{'ren' if rsvp['num_children'] != 1 else ''}"

    dietary_info = ""
    if rsvp.get('dietary_restrictions'):
      dietary_info = f"\n\nYou've noted the following dietary restrictions:\n{rsvp['dietary_restrictions']}"

    event_time = format_event_time(event)
    body = f"""
# Thank you for your RSVP, {rsvp['name']}!

We're excited that you'll be joining us for **{event['name']}**!

## Event Details:
- **Date:** {event['date']} at {event_time}
- **Location:** {event['location']}

{event['description']}

We have you down for **{guest_details}**.{dietary_info}

We look forward to seeing you there!{update_info}
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

Please RSVP by visiting: https://partymail.app/{event['slug']}

We hope to see you there!
"""

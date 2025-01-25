from flask import url_for


def generate_confirmation_email_body(event, rsvp):
  if rsvp['attending'] == 'yes':
    guest_details = f"{rsvp['num_adults']} adult{'s' if rsvp['num_adults'] != 1 else ''}"
    if rsvp['num_children'] > 0:
      guest_details += f" and {rsvp['num_children']} child{'ren' if rsvp['num_children'] != 1 else ''}"

    dietary_info = ""
    if rsvp.get('dietary_restrictions'):
      dietary_info = f"\n\nYou've noted the following dietary restrictions:\n{rsvp['dietary_restrictions']}"

    body = f"""
# Thank you for your RSVP, {rsvp['name']}!

We're excited that you'll be joining us for **{event['name']}**!

## Event Details:
- **Date:** {event['date']} at {event['time']}
- **Location:** {event['location']}

{event['description']}

We have you down for **{guest_details}**.{dietary_info}

If you need to make any changes to your RSVP, please contact us.

We look forward to seeing you there!
"""
  else:
    body = f"""
# Thank you for your RSVP, {rsvp['name']}!

We're sorry you won't be able to join us for **{event['name']}**, but we appreciate you letting us know.

If your plans change and you'd like to attend, please contact us.

We hope to see you another time!
"""

  return body

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
    return body

def generate_invitation_email_body(event, host):
    return f"""
You're invited to {event['name']}!

Join us for a special event:

Date: {event['date']} at {event['time']}
Location: {event['location']}

{event['description']}

Please RSVP by visiting: https://{host}/{event['slug']}

We hope to see you there!
"""
from flask import url_for

def generate_confirmation_email_body(event, rsvp):
    if rsvp['attending'] == 'yes':
        body = f"""
# Thank you for your RSVP, {rsvp['name']}!

We're excited that you'll be joining us for **{event['name']}**!

## Event Details:
- **Date:** {event['date']} at {event['time']}
- **Location:** {event['location']}

{event['description']}

We have you down for **{rsvp['num_guests']}** guest(s) total.

If you need to make any changes to your RSVP, please contact us.

We look forward to seeing you there!
"""
    else:
        body = f"""
# Thank you for your RSVP, {rsvp['name']}

We're sorry to hear that you won't be able to join us for **{event['name']}**, but we appreciate you letting us know.

If your plans change and you're able to attend, please let us know.

We hope to see you another time!
"""
    return body

def generate_invitation_email_body(event, host):
    return f"""
You're invited to {event['name']}!

Join us for a special event:

Date: {event['date']} at {event['time']}
Location: {event['location']}

{event['description']}

Please RSVP by visiting: https://{host}

We hope to see you there!
"""
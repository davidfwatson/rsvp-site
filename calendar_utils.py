import urllib.parse
from datetime import datetime, timedelta
from flask import Response, redirect
import dateutil.parser


def parse_event_datetime(date_str, start_time_str, end_time_str=None):
    """
    Parse event date and time into datetime objects using dateutil.parser

    Args:
        date_str: Date string (e.g., "November 15, 2024" or "2024-01-01")
        start_time_str: Start time string (e.g., "7:00 PM" or "14:00")
        end_time_str: End time string (optional)

    Returns:
        tuple: (start_datetime, end_datetime)
    """
    try:
        # Handle month-year format by adding a default day
        if ',' in date_str and len(date_str.split(',')) == 2:
            # Check if there's no day specified (e.g., "November, 2024")
            month_part = date_str.split(',')[0].strip()
            if not any(char.isdigit() for char in month_part):
                # Add the 15th as default day
                month, year = date_str.split(',')
                date_str = f"{month.strip()} 15, {year.strip()}"

        # Parse start time
        start_datetime_str = f"{date_str} {start_time_str}"
        start_date = dateutil.parser.parse(start_datetime_str)

        # Parse end time if provided, otherwise default to 2 hours later
        if end_time_str:
            end_datetime_str = f"{date_str} {end_time_str}"
            end_date = dateutil.parser.parse(end_datetime_str)
        else:
            end_date = start_date + timedelta(hours=2)

    except Exception as e:
        # Use a future date if parsing fails
        print(f"Error parsing date '{date_str}' and time '{start_time_str}': {e}")
        start_date = datetime.now() + timedelta(days=30)
        end_date = start_date + timedelta(hours=2)

    return start_date, end_date


def generate_google_calendar_url(event_config):
    """
    Generate Google Calendar URL for an event

    Args:
        event_config: Dictionary with event details

    Returns:
        str: Google Calendar URL
    """
    start_date, end_date = parse_event_datetime(
        event_config['date'],
        event_config['start_time'],
        event_config.get('end_time') or None
    )

    # Format dates for Google Calendar
    start_str = start_date.strftime("%Y%m%dT%H%M%S")
    end_str = end_date.strftime("%Y%m%dT%H%M%S")

    # Create Google Calendar URL
    calendar_url = "https://calendar.google.com/calendar/render"
    params = {
        "action": "TEMPLATE",
        "text": event_config['name'],
        "dates": f"{start_str}/{end_str}",
        "details": event_config['description'],
        "location": event_config['location'],
    }

    return f"{calendar_url}?{urllib.parse.urlencode(params)}"


def generate_ics_file(event_config):
    """
    Generate ICS file content for an event

    Args:
        event_config: Dictionary with event details

    Returns:
        str: ICS file content
    """
    start_date, end_date = parse_event_datetime(
        event_config['date'],
        event_config['start_time'],
        event_config.get('end_time') or None
    )

    # Format dates for ICS
    start_str = start_date.strftime("%Y%m%dT%H%M%S")
    end_str = end_date.strftime("%Y%m%dT%H%M%S")
    now_str = datetime.now().strftime("%Y%m%dT%H%M%S")

    # Generate a unique identifier
    uid = f"{event_config['id']}@{event_config['slug']}.partymail.app"

    # Replace newlines in description with spaces
    description = event_config['description'].replace('\n', ' ')

    # Create ICS content
    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//PartyMail App//EN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{now_str}
DTSTART:{start_str}
DTEND:{end_str}
SUMMARY:{event_config['name']}
DESCRIPTION:{description}
LOCATION:{event_config['location']}
END:VEVENT
END:VCALENDAR
"""

    return ics_content

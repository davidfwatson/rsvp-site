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


def _escape_ics_text(value):
    """Keep event text inside one RFC 5545 TEXT property value."""
    return (value.replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n')
            .replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,'))


def _fold_ics_line(line):
    """Fold at 75 UTF-8 octets without splitting a character (RFC 5545 3.1)."""
    lines, current, octets = [], '', 0
    for character in line:
        size = len(character.encode('utf-8'))
        if octets + size > 75:
            lines.append(current)
            current, octets = ' ', 1
        current += character
        octets += size
    lines.append(current)
    return '\r\n'.join(lines)


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

    # RFC 5545 TEXT encoding prevents content from becoming extra properties or
    # components. Escape before folding; consumers unfold before parsing values.
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//PartyMail App//EN',
        'BEGIN:VEVENT',
        'UID:' + _escape_ics_text(uid),
        f'DTSTAMP:{now_str}',
        f'DTSTART:{start_str}',
        f'DTEND:{end_str}',
        'SUMMARY:' + _escape_ics_text(event_config['name']),
        'DESCRIPTION:' + _escape_ics_text(event_config['description']),
        'LOCATION:' + _escape_ics_text(event_config['location']),
        'END:VEVENT',
        'END:VCALENDAR',
    ]
    return '\r\n'.join(_fold_ics_line(line) for line in lines) + '\r\n'

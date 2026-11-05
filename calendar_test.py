import pytest
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from calendar_utils import generate_ics_file, parse_event_datetime
from event_editor import validate_event
from app import app


@pytest.fixture
def client():
    """Create a test client for the Flask application."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_parse_event_datetime_month_year():
    """Test parsing date in 'Month, Year' format."""
    date_str = "November, 2024"
    start_time_str = "7:00 PM"

    start_date, end_date = parse_event_datetime(date_str, start_time_str)
    
    assert start_date.year == 2024
    assert start_date.month == 11
    assert start_date.hour == 19  # 7 PM
    assert start_date.minute == 0
    
    # Check that end_date is 2 hours later
    assert (end_date - start_date).total_seconds() == 7200  # 2 hours in seconds


def test_parse_event_datetime_iso_format():
    """Test parsing date in ISO format."""
    date_str = "2024-07-04"
    start_time_str = "2:30 PM"

    start_date, end_date = parse_event_datetime(date_str, start_time_str)
    
    assert start_date.year == 2024
    assert start_date.month == 7
    assert start_date.day == 4
    assert start_date.hour == 14  # 2 PM
    assert start_date.minute == 30
    
    # Check that end_date is 2 hours later
    assert (end_date - start_date).total_seconds() == 7200  # 2 hours in seconds


def test_google_calendar_link(client, monkeypatch):
    """Test the Google Calendar link generation."""
    # Mock the get_event_config function to return test data
    def mock_get_event_config(slug):
        return {
            'slug': 'test-event',
            'name': 'Test Event',
            'date': '2024-07-04',
            'start_time': '2:30 PM',
            'end_time': '5:30 PM',
            'location': 'Test Location',
            'description': 'Test Description'
        }
    
    # Apply the monkeypatch
    monkeypatch.setattr('app.get_event_config', mock_get_event_config)
    
    # Make a request to the calendar link endpoint
    response = client.get('/test-event/calendar/google')
    
    # Check redirection
    assert response.status_code == 302
    
    # Parse the URL to verify parameters
    parsed_url = urlparse(response.location)
    assert parsed_url.netloc == 'calendar.google.com'
    
    query_params = parse_qs(parsed_url.query)
    assert query_params['action'][0] == 'TEMPLATE'
    assert query_params['text'][0] == 'Test Event'
    assert 'location' in query_params
    assert 'details' in query_params
    assert 'dates' in query_params


def test_ics_file_download(client, monkeypatch):
    """Test the ICS file download."""
    # Mock the get_event_config function to return test data
    def mock_get_event_config(slug):
        return {
            'id': 'test123',
            'slug': 'test-event',
            'name': 'Test Event',
            'date': '2024-07-04',
            'start_time': '2:30 PM',
            'end_time': '5:30 PM',
            'location': 'Test Location',
            'description': 'Test Description'
        }
    
    # Apply the monkeypatch
    monkeypatch.setattr('app.get_event_config', mock_get_event_config)
    
    # Make a request to the ICS file endpoint
    response = client.get('/test-event/calendar/ics')
    
    # Check response
    assert response.status_code == 200
    assert 'text/calendar' in response.content_type
    assert 'attachment' in response.headers.get('Content-Disposition', '')
    
    # Check ICS content
    content = response.data.decode('utf-8')
    assert 'BEGIN:VCALENDAR' in content
    assert 'VERSION:2.0' in content
    assert 'BEGIN:VEVENT' in content
    assert 'SUMMARY:Test Event' in content
    assert 'LOCATION:Test Location' in content
    assert 'END:VEVENT' in content
    assert 'END:VCALENDAR' in content


@pytest.mark.parametrize('field,property_name', [
    ('name', 'SUMMARY'), ('location', 'LOCATION'), ('description', 'DESCRIPTION'),
])
@pytest.mark.parametrize('newline', ['\r\n', '\r', '\n'])
def test_ics_download_keeps_calendar_injection_as_text(client, monkeypatch, field, property_name, newline):
    """Host-supplied text must not add calendar events, alarms, or attendees."""
    values = dict(name='Test Event', location='Park', description='Bring a picnic.',
                  date='2099-07-04', start_time='14:00')
    values[field] = newline.join([
        'Picnic', 'ATTENDEE:mailto:extra@example.com', 'END:VEVENT',
        'BEGIN:VEVENT', 'BEGIN:VALARM', 'ACTION:DISPLAY', 'END:VALARM',
    ])
    event = validate_event(values)
    event.update(id='test123', slug='test-event')
    monkeypatch.setattr('app.get_event_config', lambda slug: event)

    response = client.get('/test-event/calendar/ics')

    assert response.status_code == 200
    # Calendar parsers remove folded continuations before interpreting lines.
    content = response.get_data(as_text=True).replace('\r\n ', '')
    lines = content.split('\r\n')
    assert [line for line in lines if line.startswith(('BEGIN:', 'END:'))] == [
        'BEGIN:VCALENDAR', 'BEGIN:VEVENT', 'END:VEVENT', 'END:VCALENDAR',
    ]
    assert not any(line.startswith(('ATTENDEE:', 'ACTION:')) for line in lines)
    assert property_name + (
        ':Picnic\\nATTENDEE:mailto:extra@example.com\\nEND:VEVENT\\nBEGIN:VEVENT'
        '\\nBEGIN:VALARM\\nACTION:DISPLAY\\nEND:VALARM'
    ) in lines


def test_ics_text_escaping_and_utf8_folding():
    """Preserve text delimiters and Unicode while keeping physical lines valid."""
    event = dict(id='test123', slug='test-event', date='2099-07-04', start_time='14:00',
                 name='Picnic, friends; family \\ games', location='Park',
                 description='Café 🧺 ' * 100 + '\r\nBring lunch.\rSee you!\nThanks.')

    content = generate_ics_file(event)

    assert content.endswith('\r\n')
    physical_lines = content[:-2].split('\r\n')
    assert all(len(line.encode('utf-8')) <= 75 for line in physical_lines)
    assert '\r' not in content.replace('\r\n', '')
    assert '\n' not in content.replace('\r\n', '')
    assert any(line.startswith(' ') for line in physical_lines)
    unfolded = content.replace('\r\n ', '')
    assert 'SUMMARY:Picnic\\, friends\\; family \\\\ games\r\n' in unfolded
    assert 'DESCRIPTION:' + 'Café 🧺 ' * 100 + '\\nBring lunch.\\nSee you!\\nThanks.\r\n' in unfolded

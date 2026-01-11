import pytest
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from calendar_utils import parse_event_datetime
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
import pytest
from unittest.mock import patch, MagicMock
import json
from event_config import (
    get_existing_slugs,
    add_new_event,
    get_event_config,
    events,
    save_event_config,
    _instance
)

# Test data
SAMPLE_EVENTS = [
    {
        "domain": "test.example.com",
        "id": "abc123",
        "slug": "birthday-party",
        "name": "Birthday Party",
        "date": "2024-01-01",
        "time": "14:00",
        "location": "Home",
        "description": "Come celebrate!",
        "max_guests_per_invite": 5,
        "color_scheme": "pink"
    },
    {
        "domain": "test2.example.com",
        "id": "def456",
        "slug": "wedding-ceremony",
        "name": "Wedding Ceremony",
        "date": "2024-02-01",
        "time": "15:00",
        "location": "Church",
        "description": "Join us for our special day!",
        "max_guests_per_invite": 2,
        "color_scheme": "blue"
    }
]

@pytest.fixture
def mock_events():
    # Save original events
    original_events = events.copy()
    # Set test events
    events.clear()
    events.extend(SAMPLE_EVENTS)
    yield events
    # Restore original events
    events.clear()
    events.extend(original_events)
    
def test_get_existing_slugs(mock_events):
    """Test getting existing slugs"""
    expected_slugs = {"birthday-party", "wedding-ceremony"}
    assert get_existing_slugs() == expected_slugs

def test_add_new_event(mock_events):
    """Test adding new event with slug generation"""
    new_event_data = {
        "name": "Summer Picnic",
        "date": "2024-07-01",
        "time": "12:00",
        "location": "Park",
        "description": "Annual summer picnic",
        "max_guests_per_invite": "3",
        "color_scheme": "blue"
    }

    with patch('uuid.uuid4', return_value=MagicMock(hex='12345678' * 4)):
        event_id = add_new_event(new_event_data)

        # Check if event was added
        added_event = next((e for e in events if e["id"] == event_id), None)
        assert added_event is not None
        assert added_event["slug"] == "summer-picnic"
        assert added_event["domain"] == "partymail.app"

def test_add_new_event_duplicate_slug(mock_events):
    """Test adding new event with duplicate slug"""
    new_event_data = {
        "name": "Birthday Party",  # This will create a duplicate slug
        "date": "2024-07-01",
        "time": "12:00",
        "location": "Park",
        "description": "Another birthday party",
        "max_guests_per_invite": "3",
        "color_scheme": "blue"
    }

    with patch('uuid.uuid4', return_value=MagicMock(hex='12345678' * 4)):
        with patch('random.choices', return_value=['x', 'y', 'z', 'w']):
            event_id = add_new_event(new_event_data)

            # Check if event was added with modified slug
            added_event = next((e for e in events if e["id"] == event_id), None)
            assert added_event is not None
            assert added_event["slug"] == "birthday-party-xyzw"

def test_get_event_config_by_domain(mock_events):
    """Test getting event by domain"""
    event = get_event_config("test.example.com")
    assert event is not None
    assert event["domain"] == "test.example.com"
    assert event["slug"] == "birthday-party"

def test_get_event_config_by_slug(mock_events):
    """Test getting event by slug"""
    event = get_event_config("wedding-ceremony")
    assert event is not None
    assert event["slug"] == "wedding-ceremony"
    assert event["domain"] == "test2.example.com"

def test_get_event_config_not_found(mock_events):
    """Test getting non-existent event"""
    assert get_event_config("non-existent-event") is None

def test_get_event_config_localhost(mock_events):
    """Test getting event for localhost"""
    event = get_event_config("localhost:5000")
    assert event is not None
    assert event == mock_events[-1]


def test_save_event_config(temp_json_file, mock_events):
    """Test saving events to JSON file"""
    # Temporarily change the config file of the singleton instance
    with patch.object(_instance, 'config_file', temp_json_file):
        save_event_config(mock_events)

        # Read the file and verify contents
        with open(temp_json_file, 'r') as f:
            saved_events = json.load(f)
            assert saved_events == SAMPLE_EVENTS

def test_add_new_event_with_manual_slug(mock_events):
    """Test adding new event with a manually specified slug"""
    new_event_data = {
        "name": "Tech Conference",
        "slug": "techconf2024",
        "date": "2024-09-01",
        "time": "09:00",
        "location": "Convention Center",
        "description": "Annual tech conference",
        "max_guests_per_invite": "1",
        "color_scheme": "blue"
    }

    with patch('uuid.uuid4', return_value=MagicMock(hex='12345678' * 4)):
        event_id = add_new_event(new_event_data)

        # Check if event was added with the manual slug
        added_event = next((e for e in events if e["id"] == event_id), None)
        assert added_event is not None
        assert added_event["slug"] == "techconf2024"
        assert added_event["name"] == "Tech Conference"

def test_add_new_event_with_invalid_manual_slug(mock_events):
    """Test adding new event with an invalid manual slug"""
    new_event_data = {
        "name": "Tech Conference",
        "slug": "Invalid Slug!",  # Contains spaces and special characters
        "date": "2024-09-01",
        "time": "09:00",
        "location": "Convention Center",
        "description": "Annual tech conference",
        "max_guests_per_invite": "1",
        "color_scheme": "blue"
    }

    with pytest.raises(ValueError, match="Invalid slug"):
        add_new_event(new_event_data)

def test_add_new_event_with_duplicate_manual_slug(mock_events):
    """Test adding new event with a duplicate manual slug"""
    new_event_data = {
        "name": "Another Event",
        "slug": "birthday-party",  # This slug already exists
        "date": "2024-09-01",
        "time": "09:00",
        "location": "Convention Center",
        "description": "Another event",
        "max_guests_per_invite": "1",
        "color_scheme": "blue"
    }

    with pytest.raises(ValueError, match="already in use"):
        add_new_event(new_event_data)


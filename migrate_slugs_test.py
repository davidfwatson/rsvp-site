from unittest.mock import patch
import json
from migrate_slugs import migrate_events

# Integration test for the migration script
def test_migrate_slugs(temp_json_file):
    """Test the migration script for adding slugs to existing events"""
    # Create test events without slugs
    events_without_slugs = [
        {
            "domain": "test.example.com",
            "id": "abc123",
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
            "name": "Wedding Ceremony",
            "date": "2024-02-01",
            "time": "15:00",
            "location": "Church",
            "description": "Join us for our special day!",
            "max_guests_per_invite": 2,
            "color_scheme": "blue"
        }
    ]
    
    # Write events without slugs to temp file
    with open(temp_json_file, 'w') as f:
        json.dump(events_without_slugs, f)
    
    # Run migration with the temp file path
    from migrate_slugs import migrate_events
    migrate_events(temp_json_file)  # We need to modify migrate_events to accept a file path
    
    # Verify migration results
    with open(temp_json_file, 'r') as f:
        migrated_events = json.load(f)
        
        # Check each event has a slug
        for i, event in enumerate(migrated_events):
            assert 'slug' in event, f"Event {i} is missing a slug field: {event}"
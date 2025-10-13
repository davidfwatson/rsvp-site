import json
import os
import uuid
from event_slug import generate_unique_slug, validate_slug

class EventConfig:
    def __init__(self, config_file='event_config.json'):
        self.config_file = config_file
        self._events = self._load_config()

    def _load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                data = json.load(f)
                if isinstance(data, list) and all(isinstance(event, dict) for event in data):
                    return data
        return self._create_default_event()

    def _save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self._events, f, indent=2)

    def _create_default_event(self):
        return [{
            "domain": "test.davidfwatson.com",
            "id": "anita_6th",
            "name": "Anita's 6th Birthday Party",
            "date": "November, 2024",
            "time": "7:00 PM",
            "location": "1787 Montecito Ave, Mountain View",
            "description": "We're having grilled cheese and mac and cheese.",
            "max_guests_per_invite": 5,
            "color_scheme": "pink"
        }]

    def get_event_config(self, domain_or_slug):
        for event in self._events:
            if isinstance(event, dict):
                if event.get('domain') == domain_or_slug:
                    return event
                if event.get('slug') == domain_or_slug:
                    return event
        
        if domain_or_slug.startswith(('127.0.0.1', 'localhost')):
            return self._events[-1] if self._events else None
            
        return None

    def get_all_events(self):
        return {event['slug']: event for event in self._events if isinstance(event, dict)}

    def get_existing_slugs(self):
        return {event.get('slug') for event in self._events if isinstance(event, dict)}

    def update_event_config(self, slug, new_config):
        for i, event in enumerate(self._events):
            if isinstance(event, dict) and event.get('slug') == slug:
                self._events[i] = new_config
                self._save_config()
                return
        self._events.append(new_config)
        self._save_config()

    def add_new_event(self, event_data):
        event_id = str(uuid.uuid4())[:8]

        # Use manual slug if provided, otherwise auto-generate
        if 'slug' in event_data and event_data['slug']:
            slug = event_data['slug'].strip().lower()

            # Validate slug format
            is_valid, error_message = validate_slug(slug)
            if not is_valid:
                raise ValueError(f"Invalid slug: {error_message}")

            # Check for duplicate slugs
            existing_slugs = self.get_existing_slugs()
            if slug in existing_slugs:
                raise ValueError(f"Slug '{slug}' is already in use")
        else:
            # Auto-generate slug from name
            slug = generate_unique_slug(event_data['name'], self.get_existing_slugs())

        new_event = {
            "domain": "partymail.app",
            "id": event_id,
            "slug": slug,
            "name": event_data['name'],
            "date": event_data['date'],
            "time": event_data['time'],
            "location": event_data['location'],
            "description": event_data['description'],
            "max_guests_per_invite": int(event_data['max_guests_per_invite']),
            "color_scheme": event_data.get('color_scheme', 'pink')
        }
        self._events.append(new_event)
        self._save_config()
        return event_id

# Create a singleton instance
_instance = EventConfig()

# Export the instance methods as module-level functions
get_event_config = _instance.get_event_config
get_all_events = _instance.get_all_events
update_event_config = _instance.update_event_config
add_new_event = _instance.add_new_event
get_existing_slugs = _instance.get_existing_slugs

# Define save_event_config for testing
def save_event_config(events_list):
    global events
    _instance._events = events_list
    events = _instance._events
    _instance._save_config()

# Export events list for testing
events = _instance._events
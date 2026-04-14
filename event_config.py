import json
import os
import uuid
from event_slug import generate_unique_slug, validate_slug

DEFAULT_EVENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data', 'events'))


class EventConfig:
    def __init__(self, events_dir=None):
        self.events_dir = events_dir if events_dir is not None else DEFAULT_EVENTS_DIR
        self._events = self._load_config()

    def _load_config(self):
        if not os.path.isdir(self.events_dir):
            return []
        events = []
        for filename in sorted(os.listdir(self.events_dir)):
            if not filename.endswith('.json'):
                continue
            path = os.path.join(self.events_dir, filename)
            try:
                with open(path, 'r') as f:
                    event = json.load(f)
                if isinstance(event, dict):
                    events.append(event)
            except (json.JSONDecodeError, OSError):
                continue
        return events

    def _assert_safe_write(self):
        if os.environ.get('PYTEST_CURRENT_TEST') and os.path.abspath(self.events_dir) == DEFAULT_EVENTS_DIR:
            raise RuntimeError(
                "event_config: refusing to write to prod events_dir during pytest. "
                "conftest.py's autouse _isolate_event_config fixture must be active."
            )

    def _event_path(self, slug):
        return os.path.join(self.events_dir, f'{slug}.json')

    def _save_event(self, event):
        self._assert_safe_write()
        os.makedirs(self.events_dir, exist_ok=True)
        slug = event.get('slug')
        if not slug:
            raise ValueError("Event must have a slug")
        target = self._event_path(slug)
        tmp = target + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(event, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)

    def _delete_event_file(self, slug):
        self._assert_safe_write()
        path = self._event_path(slug)
        if os.path.exists(path):
            os.remove(path)

    def _save_config(self):
        # Batch save: write every in-memory event to its own file.
        for event in self._events:
            if isinstance(event, dict) and event.get('slug'):
                self._save_event(event)

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
        new_slug = new_config.get('slug', slug)
        for i, event in enumerate(self._events):
            if isinstance(event, dict) and event.get('slug') == slug:
                self._events[i] = new_config
                self._save_event(new_config)
                if new_slug != slug:
                    self._delete_event_file(slug)
                return
        self._events.append(new_config)
        self._save_event(new_config)

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
            "start_time": event_data['start_time'],
            "end_time": event_data.get('end_time', ''),
            "location": event_data['location'],
            "description": event_data['description'],
            "max_guests_per_invite": int(event_data['max_guests_per_invite']),
            "color_scheme": event_data.get('color_scheme', 'pink')
        }
        self._events.append(new_event)
        self._save_event(new_event)
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

def format_event_time(event):
    """Format start_time and end_time for display."""
    start = event.get('start_time', '')
    end = event.get('end_time', '')
    if end:
        return f"{start} - {end}"
    return start

import json
import os
import uuid
from event_slug import generate_unique_slug

EVENT_CONFIG_FILE = 'event_config.json'


def load_event_config():
  if os.path.exists(EVENT_CONFIG_FILE):
    with open(EVENT_CONFIG_FILE, 'r') as f:
      data = json.load(f)
      # Ensure the loaded data is a list of dictionaries
      if isinstance(data, list) and all(
          isinstance(event, dict) for event in data):
        return data
  return []


def save_event_config(events):
  with open(EVENT_CONFIG_FILE, 'w') as f:
    json.dump(events, f, indent=2)


def create_default_event():
    return [{
        "domain": "test.davidfwatson.com",
        "id": "anita_6th",
        "name": "Anita's 6th Birthday Party",
        "date": "November, 2024",
        "time": "7:00 PM",
        "location": "1787 Montecito Ave, Mountain View",
        "description": "We're having grilled cheese and mac and cheese.",
        "max_guests_per_invite": 5,
        "color_scheme": "pink"  # Add default color scheme
    }]


events = load_event_config()

# Check if events is empty, if so, create the default event
if not events:
  events = create_default_event()
  save_event_config(events)

def get_event_config(domain_or_slug):
    # First try to find by domain
    for event in events:
        if isinstance(event, dict):
            if event.get('domain') == domain_or_slug:
                return event
            # Then try to find by slug
            if event.get('slug') == domain_or_slug:
                return event
    
    # For local development
    if domain_or_slug.startswith('127.0.0.1') or domain_or_slug.startswith('localhost'):
        return events[-1] if events else None
    
    return None
    

def get_all_events():
  return {event['domain']: event for event in events if isinstance(event, dict)}


def get_existing_slugs():
    """
    Get a set of all existing slugs from the events.
    """
    return {event.get('slug') for event in events if isinstance(event, dict)}


def update_event_config(domain, new_config):
  for i, event in enumerate(events):
    if isinstance(event, dict) and event.get('domain') == domain:
      events[i] = new_config
      save_event_config(events)
      return
  # If the event doesn't exist, add it
  events.append(new_config)
  save_event_config(events)


def add_new_event(domain, event_data):
    event_id = str(uuid.uuid4())[:8]
    
    # Generate unique slug for the event
    existing_slugs = get_existing_slugs()
    slug = generate_unique_slug(event_data['name'], existing_slugs)
    
    new_event = {
        "domain": domain,
        "id": event_id,
        "slug": slug,  # Add the slug
        "name": event_data['name'],
        "date": event_data['date'],
        "time": event_data['time'],
        "location": event_data['location'],
        "description": event_data['description'],
        "max_guests_per_invite": int(event_data['max_guests_per_invite']),
        "color_scheme": event_data.get('color_scheme', 'pink') # Add color scheme with default
    }
    events.append(new_event)
    save_event_config(events)
    return event_id


# Debugging: Print the contents of events
print("Current events:", events)

import json
import os

EVENT_CONFIG_FILE = 'event_config.json'

def load_event_config():
    if os.path.exists(EVENT_CONFIG_FILE):
        with open(EVENT_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_event_config(events):
    with open(EVENT_CONFIG_FILE, 'w') as f:
        json.dump(events, f, indent=2)

def create_default_event():
    return {
        "test.davidfwatson.com": {
            "id": "anita_6th",
            "name": "Anita's 6th Birthday Party",
            "date": "November, 2024",
            "time": "7:00 PM",
            "location": "1787 Montecito Ave, Mountain View",
            "description": "We're having grilled cheese and mac and cheese.",
            "max_guests_per_invite": 5
        }
    }

events = load_event_config()

# Check if events is empty, if so, create the default event
if not events:
    events = create_default_event()
    save_event_config(events)

# Mapping of alternative domains to main domains
domain_aliases = {
    "127.0.0.1:5000": "test.davidfwatson.com",
}

def get_event_config(domain):
    # Check if the domain is an alias, and if so, use the main domain
    main_domain = domain_aliases.get(domain, domain)
    return events.get(main_domain, {})

def get_all_events():
    return events

def update_event_config(domain, new_config):
    events[domain] = new_config
    save_event_config(events)
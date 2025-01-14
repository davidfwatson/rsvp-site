import json
from event_slug import generate_unique_slug

def migrate_events(config_file='event_config.json'):  # Add parameter with default
    # Read current events
    with open(config_file, 'r') as f:
        events = json.load(f)
    
    # Keep track of used slugs
    existing_slugs = set()
    
    # Add slugs to each event that doesn't have one
    for event in events:
        if isinstance(event, dict) and 'slug' not in event:
            # Generate a unique slug based on the event name
            slug = generate_unique_slug(event['name'], existing_slugs)
            event['slug'] = slug
            existing_slugs.add(slug)
    
    # Save updated events
    with open(config_file, 'w') as f:
        json.dump(events, f, indent=2)

if __name__ == '__main__':
    migrate_events()
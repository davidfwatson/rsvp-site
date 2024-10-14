events = {
    "birthday_party": {
        "name": "Anita's 6th Birthday Party",
        "date": "November, 2024",
        "time": "7:00 PM",
        "location": "1787 Montecito Ave, Mountain View",
        "description": "We're having grilled cheese and mac and cheese.",
        "max_guests_per_invite": 5
    },
    # You can add more events here in the future
}

def get_event_config(event_id):
    return events.get(event_id, {})
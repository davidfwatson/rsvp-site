events = {
    "test.davidfwatson.com": {
        "id": "anita_6th",
        "name": "Anita's 6th Birthday Party",
        "date": "November, 2024",
        "time": "7:00 PM",
        "location": "1787 Montecito Ave, Mountain View",
        "description": "We're having grilled cheese and mac and cheese.",
        "max_guests_per_invite": 5
    },
    # You can add more events here in the future
}


# Mapping of alternative domains to main domains
domain_aliases = {
    "127.0.0.1:5000": "test.davidfwatson.com",
    # Add more aliases as needed, e.g.:
    # "localhost:5000": "test.davidfwatson.com",
}

def get_event_config(domain):
    # Check if the domain is an alias, and if so, use the main domain
    main_domain = domain_aliases.get(domain, domain)
    return events.get(main_domain, {})

def get_all_events():
    return events
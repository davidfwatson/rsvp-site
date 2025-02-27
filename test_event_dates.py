import json
import dateutil.parser
from calendar_utils import parse_event_datetime
from date_validation import validate_date_time

def test_event_config_dates():
    # Load event config
    with open('event_config.json', 'r') as f:
        events = json.load(f)
    
    print("\nTesting date/time parsing for events in event_config.json:")
    print("=" * 70)
    
    for i, event in enumerate(events):
        date_str = event['date']
        time_str = event['time']
        
        print(f"\nEvent {i+1}: {event['name']}")
        print(f"Date: '{date_str}', Time: '{time_str}'")
        
        # Test validation but don't require future dates
        is_valid, error = validate_date_time(date_str, time_str, require_future=False)
        if is_valid:
            print(f"✅ Format validation: Valid date/time format")
        else:
            print(f"❌ Format validation failed: {error}")
        
        # Test parsing
        try:
            start_date, end_date = parse_event_datetime(date_str, time_str)
            print(f"✅ Parsed dates: {start_date} to {end_date}")
        except Exception as e:
            print(f"❌ Parsing error: {str(e)}")

if __name__ == "__main__":
    test_event_config_dates()
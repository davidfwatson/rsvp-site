import re
from datetime import datetime
import dateutil.parser

def validate_date_time(date_str, time_str, require_future=True):
    """
    Validate if the date and time strings can be parsed into a valid date.
    
    Args:
        date_str: Date string
        time_str: Time string
        require_future: Whether to require the date to be in the future
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not date_str or not time_str:
        return False, "Date and time are required."
    
    try:
        # Handle month-year format by adding a default day
        if ',' in date_str and len(date_str.split(',')) == 2:
            # Check if there's no day specified (e.g., "November, 2024")
            month_part = date_str.split(',')[0].strip()
            if not any(char.isdigit() for char in month_part):
                # Add the 15th as default day
                month, year = date_str.split(',')
                date_str = f"{month.strip()} 15, {year.strip()}"
        
        # Combine date and time for parsing
        datetime_str = f"{date_str} {time_str}"
        
        # Try parsing with dateutil
        parsed_date = dateutil.parser.parse(datetime_str)
        
        # Make sure we have a valid future date if required
        if require_future and parsed_date < datetime.now():
            return False, "Event date must be in the future."
            
        return True, None
        
    except Exception as e:
        # Provide clear error message based on the type of error
        if "day is out of range for month" in str(e):
            return False, "Invalid day for the specified month."
        elif "month must be in 1..12" in str(e):
            return False, "Invalid month specified."
        else:
            return False, f"Invalid date or time format: {str(e)}"


def date_format_examples():
    """Return examples of valid date formats"""
    return [
        "November 15, 2024",
        "2024-11-15",
        "11/15/2024",
        "15 November 2024"
    ]


def time_format_examples():
    """Return examples of valid time formats"""
    return [
        "7:00 PM",
        "19:00",
        "7:30 AM",
        "14:30"
    ]
from typing import Dict, List, Optional, Any, Set
import csv
from io import StringIO
from datetime import datetime


def format_rsvp_for_export(rsvp: Dict[str, Any]) -> Dict[str, Any]:
  """
    Format a single RSVP record for CSV export.
    
    Args:
        rsvp: Dictionary containing RSVP data
        
    Returns:
        Dictionary with formatted RSVP data, with keys converted to Title Case
    """
  formatted_rsvp: Dict[str, Any] = {}

  # Process each key in the original RSVP
  for key, value in rsvp.items():
    # Special handling for timestamp
    if key == 'timestamp':
      try:
        value = datetime.fromisoformat(value).strftime('%Y-%m-%d %H:%M:%S')
      except (ValueError, TypeError):
        pass  # Keep original if parsing fails

    # Convert key from snake_case to Title Case for header
    header = key.replace('_', ' ').title()
    formatted_rsvp[header] = value

  return formatted_rsvp


def generate_rsvps_csv(rsvps: List[Dict[str, Any]]) -> Optional[str]:
  """
    Generate a CSV string from RSVP data.
    
    Args:
        rsvps: List of dictionaries containing RSVP data
        
    Returns:
        String containing CSV data, or None if no RSVPs exist
    """
  if not rsvps or len(rsvps) == 0:
    return None

  # Collect all possible fields from all RSVPs
  fieldnames: Set[str] = set()
  for rsvp in rsvps:
    formatted = format_rsvp_for_export(rsvp)
    fieldnames.update(formatted.keys())

  # Sort fieldnames to ensure consistent column order
  # Put certain important fields first if they exist
  priority_fields: List[str] = [
      'Timestamp', 'Name', 'Email', 'Attending', 'Num Guests'
  ]
  fieldnames_list: List[str] = sorted(list(fieldnames))
  for field in reversed(priority_fields):
    if field in fieldnames_list:
      fieldnames_list.remove(field)
      fieldnames_list.insert(0, field)

  # Create a string buffer to write CSV to
  output = StringIO()
  writer = csv.DictWriter(output, fieldnames=fieldnames_list)

  # Write header and data
  writer.writeheader()
  for rsvp in rsvps:
    writer.writerow(format_rsvp_for_export(rsvp))

  return output.getvalue()


def get_csv_filename(event_name: str) -> str:
  """
    Generate a filename for the CSV export.
    
    Args:
        event_name: Name of the event
        
    Returns:
        String containing a sanitized filename with timestamp
    """
  timestamp: str = datetime.now().strftime('%Y%m%d_%H%M%S')
  # Clean event name to make it filename-safe
  safe_event_name: str = "".join(
      c for c in event_name if c.isalnum() or c in (' ', '-', '_')).strip()
  safe_event_name = safe_event_name.replace(' ', '_')
  return f'rsvps_{safe_event_name}_{timestamp}.csv'

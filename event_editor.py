"""Validation and safe rendering for invitation customization."""
import re

import bleach
import markdown

from date_validation import validate_date_time

DESIGN_DEFAULTS = {
    'background_style': 'linen', 'background_color': '#f4efe7',
    'accent_color': '#95604b', 'background_image': '', 'cover_image': '',
    'font_style': 'serif', 'envelope_style': 'classic', 'show_attendees': False,
}
CHOICES = {
    'color_scheme': ('pink', 'blue', 'red', 'black'),
    'background_style': ('linen', 'gradient', 'solid', 'image'),
    'font_style': ('serif', 'sans'), 'envelope_style': ('classic', 'minimal'),
}


def prepare_event(event):
    """Copy event metadata and render safe Markdown for a guest or preview."""
    prepared = {**DESIGN_DEFAULTS, **event}
    html = markdown.markdown(prepared.get('description', ''))
    prepared['description_html'] = bleach.clean(
        html, tags=['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'a', 'h2', 'h3', 'blockquote'],
        attributes={'a': ['href', 'title']}, protocols=['https', 'http', 'mailto'], strip=True,
    )
    return prepared


def validate_event(values, existing=None, require_future=False):
    """Merge editable fields without dropping preserved event metadata."""
    result = {**DESIGN_DEFAULTS, **(existing or {})}
    for field, maximum in [('name', 160), ('date', 80), ('start_time', 30),
                           ('end_time', 30), ('location', 500), ('description', 20000)]:
        value = values.get(field, result.get(field, ''))
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError(f'{field.replace("_", " ").title()} is too long.')
        result[field] = value.strip()
    if not result['name'] or not result['location']:
        raise ValueError('Event name and location are required.')
    valid, message = validate_date_time(result['date'], result['start_time'],
                                        result['end_time'] or None, require_future=require_future)
    if not valid:
        raise ValueError(message)
    try:
        guests = int(values.get('max_guests_per_invite', result.get('max_guests_per_invite', 5)))
    except (ValueError, TypeError):
        raise ValueError('Guest limit must be a whole number.') from None
    if not 1 <= guests <= 100:
        raise ValueError('Guest limit must be between 1 and 100.')
    result['max_guests_per_invite'] = guests
    for field, choices in CHOICES.items():
        value = values.get(field, result.get(field, choices[0]))
        if value not in choices:
            raise ValueError(f'Choose a valid {field.replace("_", " ")}.')
        result[field] = value
    for field in ('background_color', 'accent_color'):
        value = values.get(field, result[field])
        if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            raise ValueError('Colors must use six-digit hex values.')
        result[field] = value.lower()
    for field in ('background_image', 'cover_image'):
        value = values.get(field, result[field])
        if not isinstance(value, str) or (value and not re.fullmatch(r'/media/[a-f0-9]{32}\.webp', value)):
            raise ValueError('Choose an uploaded image.')
        result[field] = value
    for field in ('archived', 'show_attendees'):
        value = values.get(field, result.get(field, False))
        result[field] = value is True or value in ('on', 'true', '1')
    return result

import re
from unidecode import unidecode
import random
import string

def generate_slug(name):
    """
    Generate a URL-friendly slug from a string.
    Convert to lowercase, replace spaces with hyphens, remove non-alphanumeric characters.
    """
    # Convert to ASCII, lowercase, and replace spaces with hyphens
    slug = unidecode(name).lower()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '-', slug).strip('-')
    return slug

def validate_slug(slug):
    """
    Validate that a slug meets the required format:
    - Only lowercase letters, numbers, and hyphens
    - Cannot start or end with a hyphen
    - Must be between 1 and 50 characters

    Returns: (is_valid, error_message)
    """
    if not slug:
        return False, "Slug cannot be empty"

    if len(slug) > 50:
        return False, "Slug is too long (max 50 characters)"

    # Check format: lowercase letters, numbers, and hyphens only
    # Cannot start or end with hyphen
    if not re.match(r'^[a-z0-9]+(-[a-z0-9]+)*$', slug):
        return False, "Slug must contain only lowercase letters, numbers, and hyphens (no spaces, no special characters, cannot start/end with hyphen)"

    return True, ""

def generate_unique_slug(name, existing_slugs):
    """
    Generate a unique slug by appending random characters if necessary.
    """
    base_slug = generate_slug(name)
    slug = base_slug

    # If slug exists, append random characters until unique
    while slug in existing_slugs:
        # Generate 4 random alphanumeric characters
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
        slug = f"{base_slug}-{random_suffix}"

    return slug


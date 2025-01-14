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


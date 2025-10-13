from unittest.mock import patch
from event_slug import (
    generate_slug,
    generate_unique_slug,
    validate_slug,
)

def test_generate_slug_basic():
    """Test basic slug generation"""
    assert generate_slug("Hello World") == "hello-world"
    assert generate_slug("Birthday Party!") == "birthday-party"
    assert generate_slug("My Cool Event 2024") == "my-cool-event-2024"

def test_generate_slug_special_characters():
    """Test slug generation with special characters"""
    assert generate_slug("Hello & Goodbye!") == "hello-goodbye"
    assert generate_slug("münchen") == "munchen"
    assert generate_slug("École d'été") == "ecole-dete"

def test_generate_slug_multiple_spaces():
    """Test slug generation with multiple spaces and dashes"""
    assert generate_slug("Hello   World") == "hello-world"
    assert generate_slug("Hello---World") == "hello-world"
    assert generate_slug(" Hello World ") == "hello-world"

def test_generate_unique_slug():
    """Test unique slug generation"""
    existing_slugs = {"hello-world", "test-event"}

    # Should return original slug if not in existing_slugs
    assert generate_unique_slug("New Event", existing_slugs) == "new-event"

    # Should append random string if slug exists
    with patch('random.choices', return_value=['a', 'b', 'c', 'd']):
        assert generate_unique_slug("Hello World", existing_slugs) == "hello-world-abcd"

def test_validate_slug_valid():
    """Test validation of valid slugs"""
    valid, msg = validate_slug("hello-world")
    assert valid is True
    assert msg == ""

    valid, msg = validate_slug("event-2024")
    assert valid is True

    valid, msg = validate_slug("my-awesome-party")
    assert valid is True

    valid, msg = validate_slug("test123")
    assert valid is True

def test_validate_slug_invalid_format():
    """Test validation of invalid slug formats"""
    # Empty slug
    valid, msg = validate_slug("")
    assert valid is False
    assert "empty" in msg.lower()

    # Contains uppercase
    valid, msg = validate_slug("Hello-World")
    assert valid is False

    # Contains spaces
    valid, msg = validate_slug("hello world")
    assert valid is False

    # Contains special characters
    valid, msg = validate_slug("hello@world")
    assert valid is False

    valid, msg = validate_slug("hello_world")
    assert valid is False

    # Starts with hyphen
    valid, msg = validate_slug("-hello")
    assert valid is False

    # Ends with hyphen
    valid, msg = validate_slug("hello-")
    assert valid is False

    # Double hyphens
    valid, msg = validate_slug("hello--world")
    assert valid is False

def test_validate_slug_length():
    """Test slug length validation"""
    # Too long (over 50 characters)
    long_slug = "a" * 51
    valid, msg = validate_slug(long_slug)
    assert valid is False
    assert "long" in msg.lower()

    # Max length (50 characters)
    max_slug = "a" * 50
    valid, msg = validate_slug(max_slug)
    assert valid is True

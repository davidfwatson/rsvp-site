from unittest.mock import patch
from event_slug import (
    generate_slug,
    generate_unique_slug,
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

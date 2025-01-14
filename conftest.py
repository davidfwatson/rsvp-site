import pytest

@pytest.fixture
def temp_json_file(tmp_path):
    """Fixture to create a temporary JSON file for testing"""
    json_file = tmp_path / "test_event_config.json"
    return str(json_file)
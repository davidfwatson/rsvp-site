import pytest


@pytest.fixture
def temp_json_file(tmp_path):
    """Fixture to create a temporary JSON file for testing"""
    json_file = tmp_path / "test_event_config.json"
    return str(json_file)


@pytest.fixture(autouse=True)
def _isolate_event_config(tmp_path, monkeypatch):
    """Redirect the EventConfig singleton to a tmp dir for every test.

    The prod events directory holds live event definitions. Without this,
    a test that calls add_new_event / update_event_config / save_event_config
    would write real files into prod (this has happened before).
    """
    from event_config import _instance
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    monkeypatch.setattr(_instance, 'events_dir', str(events_dir))
    yield

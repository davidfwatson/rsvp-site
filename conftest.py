import os

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
    import event_config
    from event_config import _instance
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    monkeypatch.setattr(_instance, 'events_dir', str(events_dir))

    # The EventConfig singleton's event list is process-wide, so a test that
    # loads its own events would otherwise leak them into every test that runs
    # after it. Snapshot the contents and restore them afterwards.
    #
    # Mutate in place, never rebind: event_config.events is the same list
    # object, and tests reach the singleton's state through both names.
    saved_events = list(_instance._events)
    _instance._events.clear()
    try:
        yield
    finally:
        _instance._events[:] = saved_events
        event_config.events = _instance._events


_TEMP_CONFIG = None


def pytest_configure(config):
    """app.py loads config.py at import time, but config.py is gitignored.

    On a checkout that has no config.py (a fresh clone, CI), write a throwaway
    one before collection imports the app. An existing config.py — prod's,
    notably — is left completely alone.
    """
    global _TEMP_CONFIG
    path = os.path.join(os.path.dirname(__file__), 'config.py')
    if os.path.exists(path):
        return
    with open(path, 'w') as f:
        f.write(
            'SENDER_EMAIL = "test@example.com"\n'
            'ADMIN_PASSWORD = "test"\n'
            'SECRET_KEY = "test-secret-key"\n'
            'WEBAUTHN_RP_ID = "localhost"\n'
            'WEBAUTHN_RP_NAME = "Test"\n'
            'WEBAUTHN_ORIGIN = "http://localhost"\n'
        )
    _TEMP_CONFIG = path


def pytest_unconfigure(config):
    if _TEMP_CONFIG and os.path.exists(_TEMP_CONFIG):
        os.remove(_TEMP_CONFIG)

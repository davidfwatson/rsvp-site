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


# Values used only when the checkout has no config.py of its own.
_TEST_CONFIG = {
    'SENDER_EMAIL': 'test@example.com',
    'ADMIN_PASSWORD': 'test',
    'SECRET_KEY': 'test-secret-key',
    'WEBAUTHN_RP_ID': 'localhost',
    'WEBAUTHN_RP_NAME': 'Test',
    'WEBAUTHN_ORIGIN': 'http://localhost',
}


def pytest_configure(config):
    """app.py loads config.py at import time, but config.py is gitignored.

    On a checkout that has no config.py (a fresh clone, CI) the suite could not
    even be collected. Rather than writing a config.py — a file left behind by
    a hard crash would be a real config.py holding test credentials, which a
    later app start in that directory would happily load — teach from_pyfile to
    fall back to in-memory defaults for the missing file. Nothing touches disk,
    and a checkout that has its own config.py (prod's, notably) is unaffected:
    from_pyfile finds it and this fallback never fires.
    """
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'config.py')):
        return

    from flask import Config

    original_from_pyfile = Config.from_pyfile

    def from_pyfile_with_test_defaults(self, filename, silent=False):
        try:
            return original_from_pyfile(self, filename, silent=silent)
        except FileNotFoundError:
            if os.path.basename(filename) != 'config.py':
                raise
            self.update(_TEST_CONFIG)
            return True

    Config.from_pyfile = from_pyfile_with_test_defaults

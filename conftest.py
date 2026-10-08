"""Force isolation before collection imports the app or any persistent store."""
from copy import deepcopy
import os
import sys
import tempfile

import pytest


# Fixtures execute after collection imports. Override inherited production
# configuration immediately, including when tests run on the production host.
_session_data = tempfile.TemporaryDirectory(prefix='rsvp-pytest-')
os.environ['RSVP_ENV'] = 'test'
os.environ['RSVP_DATA_DIR'] = _session_data.name
os.environ['RSVP_TEST_DATA_ROOT'] = _session_data.name
os.environ['RSVP_EMAIL_ENABLED'] = 'false'
os.environ['RSVP_SECRET_KEY'] = 'test-only-secret-key'
os.environ['RSVP_PUBLIC_URL'] = 'http://localhost:5000'
os.environ['RSVP_WEBAUTHN_RP_ID'] = 'localhost'
os.environ['RSVP_WEBAUTHN_ORIGIN'] = 'http://localhost:5000'


@pytest.fixture
def temp_json_file(tmp_path):
    return str(tmp_path / 'test_event_config.json')


@pytest.fixture(autouse=True)
def _isolate_event_config(tmp_path, monkeypatch):
    """Give each test fresh event/account/RSVP data with no production state."""
    import event_config
    from event_config import _instance

    root = tmp_path / 'data'
    root.mkdir()
    monkeypatch.setenv('RSVP_DATA_DIR', str(root))
    monkeypatch.setenv('RSVP_TEST_DATA_ROOT', str(tmp_path))
    monkeypatch.setenv('RSVP_ENV', 'test')
    events_dir = root / 'events'
    events_dir.mkdir()
    saved_events = deepcopy(_instance._events)
    saved_snapshot = _instance._disk_snapshot
    monkeypatch.setattr(_instance, 'events_dir', str(events_dir))
    _instance._events.clear()
    _instance._disk_snapshot = _instance._signature()
    if 'passkey_auth' in sys.modules:
        monkeypatch.setattr(sys.modules['passkey_auth'], 'ADMINS_FILE', str(root / 'admins.json'))
    if 'app' in sys.modules:
        application = sys.modules['app'].app
        for key, value in {'RSVP_DATA_DIR': str(root), 'EMAIL_ENABLED': False, 'TESTING': True, 'CSRF_ENABLED': False}.items():
            monkeypatch.setitem(application.config, key, value)
    try:
        yield
    finally:
        _instance._events[:] = saved_events
        _instance._disk_snapshot = saved_snapshot
        event_config.events = _instance._events

"""Safety boundaries that matter when tests and deployments share a host."""
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tarfile

from flask import Flask
from flask import request
import pytest

from event_config import EventConfig, EventConflictError
from runtime_config import configure_app, data_path
from scripts.deploy_release import candidate_health, extract_artifact, promote_release
from scripts.migrate_data import migrate
from storage import StorageError, read_json, update_json, write_json


def _increment(path, count):
    for _ in range(count):
        update_json(path, lambda document: document.update(count=document['count'] + 1), {'count': 0})


def test_processes_do_not_lose_json_updates(tmp_path):
    """Independent web workers lock their entire JSON transaction."""
    path = tmp_path / 'counter.json'
    context = multiprocessing.get_context('spawn')
    processes = [context.Process(target=_increment, args=(path, 12)) for _ in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    assert read_json(path, {})['count'] == 48
    assert len(list((tmp_path / '.backups/counter.json').glob('*.bak'))) == 20


def test_replacement_failure_preserves_current_json(tmp_path, monkeypatch):
    path = tmp_path / 'events.json'
    write_json(path, {'name': 'Original'})
    replace = os.replace

    def fail_replace(source, destination):
        if Path(destination) == path:
            raise OSError('simulated failed promotion')
        return replace(source, destination)

    monkeypatch.setattr(os, 'replace', fail_replace)
    with pytest.raises(OSError):
        write_json(path, {'name': 'Changed'})
    assert read_json(path, {}) == {'name': 'Original'}
    assert not list(tmp_path.glob('*.tmp'))
    assert json.loads(next((tmp_path / '.backups/events.json').glob('*.bak')).read_text()) == {'name': 'Original'}


def test_corrupt_json_cannot_be_emptied_by_save(tmp_path):
    path = tmp_path / 'admins.json'
    path.write_text('{unfinished')
    with pytest.raises(StorageError):
        read_json(path, {'admins': []})
    with pytest.raises(StorageError):
        write_json(path, {'admins': []})
    assert path.read_text() == '{unfinished'


def test_invalid_event_document_fails_visibly(tmp_path):
    root = tmp_path / 'events'
    root.mkdir()
    (root / 'party.json').write_text('null')
    with pytest.raises(ValueError, match='Invalid event document'):
        EventConfig(root)


def test_pytest_write_guard_blocks_outside_isolated_root(tmp_path):
    with pytest.raises(RuntimeError, match='live data is protected'):
        write_json(tmp_path.parent / 'unsafe-events.json', {})


def test_event_workers_refresh_and_reject_stale_editor(tmp_path):
    first, second = EventConfig(tmp_path / 'events'), EventConfig(tmp_path / 'events')
    event = {'id': 'one', 'slug': 'party', 'name': 'Original'}
    saved = first.update_event_config('party', event, expected_version=0)
    assert second.get_event_config('party') == saved
    saved['name'] = 'First editor'
    first.update_event_config('party', saved, expected_version=1)
    with pytest.raises(EventConflictError):
        second.update_event_config('party', {**saved, 'name': 'Stale editor'}, expected_version=1)
    assert second.get_event_config('party')['name'] == 'First editor'
    assert second.get_event_config('party')['version'] == 2


def test_unsafe_event_slug_never_becomes_a_path(tmp_path):
    store = EventConfig(tmp_path / 'events')
    with pytest.raises(ValueError, match='Invalid slug'):
        store.update_event_config('../outside', {'id': 'one', 'slug': '../outside'})
    assert not (tmp_path / 'outside.json').exists()


def test_runtime_paths_are_independent_of_working_directory(tmp_path, monkeypatch):
    expected = data_path('rsvps_abc.json')
    monkeypatch.chdir(tmp_path)
    assert data_path('rsvps_abc.json') == expected
    with pytest.raises(ValueError):
        data_path('../outside.json')


def test_proxy_headers_only_apply_when_explicitly_trusted(tmp_path, monkeypatch):
    def create_app(trusted):
        monkeypatch.setenv('RSVP_TRUST_PROXY', 'true' if trusted else 'false')
        application = Flask('proxy-test', root_path=str(tmp_path))
        configure_app(application)
        application.add_url_rule('/', view_func=lambda: {'scheme': request.scheme, 'remote': request.remote_addr})
        return application

    headers = {'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '198.51.100.4'}
    assert create_app(False).test_client().get('/', headers=headers).json == {'scheme': 'http', 'remote': '127.0.0.1'}
    assert create_app(True).test_client().get('/', headers=headers).json == {'scheme': 'https', 'remote': '198.51.100.4'}


def test_production_requires_external_initialized_data_and_strong_secret(tmp_path, monkeypatch):
    monkeypatch.setenv('RSVP_ENV', 'production')
    monkeypatch.setenv('RSVP_SECRET_KEY', 'weak')
    monkeypatch.setenv('RSVP_PUBLIC_URL', 'https://partymail.app')
    monkeypatch.setenv('RSVP_WEBAUTHN_RP_ID', 'partymail.app')
    monkeypatch.setenv('RSVP_WEBAUTHN_ORIGIN', 'https://partymail.app')
    application = Flask('runtime-test', root_path=str(tmp_path))
    with pytest.raises(RuntimeError, match='Unsafe production'):
        configure_app(application)
    root = Path(os.environ['RSVP_DATA_DIR'])
    (root / '.rsvp-data').touch()
    monkeypatch.setenv('RSVP_SECRET_KEY', 'a' * 64)
    configure_app(application)
    assert application.config['SESSION_COOKIE_SECURE'] is True
    assert application.config['PUBLIC_BASE_URL'] == 'https://partymail.app'
    monkeypatch.delenv('RSVP_DATA_DIR')
    with pytest.raises(RuntimeError, match='explicit RSVP_DATA_DIR'):
        configure_app(application)


def test_collection_redirects_inherited_production_before_any_app_import(tmp_path):
    production = tmp_path / 'production-data'
    production.mkdir()
    (production / 'sentinel').write_text('never touch')
    env = {**os.environ, 'RSVP_ENV': 'production', 'RSVP_DATA_DIR': str(production)}
    script = "import conftest; import event_config, passkey_auth; from runtime_config import data_path; import os; assert os.environ['RSVP_ENV'] == 'test'; assert str(data_path('events')) != os.environ['PROTECTED_EVENTS']; event_config.update_event_config('probe', {'id':'p','slug':'probe','name':'Probe'}); passkey_auth._save_data({'admins':[]})"
    env['PROTECTED_EVENTS'] = str(production / 'events')
    subprocess.run([sys.executable, '-c', script], env=env, cwd=Path(__file__).parent, check=True)
    assert list(production.iterdir()) == [production / 'sentinel']
    assert (production / 'sentinel').read_text() == 'never touch'


def test_production_candidate_health_boots_without_writing_data(tmp_path):
    """Real gunicorn boot checks the public host and release without data writes."""
    root = Path(__file__).resolve().parent
    release = tmp_path / 'candidate'
    (release / 'venv').mkdir(parents=True)
    (release / 'venv/bin').symlink_to(Path(sys.executable).parent)
    (release / 'app.py').symlink_to(root / 'app.py')
    persistent = tmp_path / 'production-data'
    persistent.mkdir()
    (persistent / '.rsvp-data').write_text('initialized')
    environment = {
        **os.environ, 'RSVP_ENV': 'production', 'RSVP_DATA_DIR': str(persistent),
        'RSVP_PUBLIC_URL': 'https://partymail.app', 'RSVP_SECRET_KEY': 'a' * 64,
        'RSVP_WEBAUTHN_RP_ID': 'partymail.app', 'RSVP_WEBAUTHN_ORIGIN': 'https://partymail.app',
        'RSVP_RELEASE_ID': 'candidate-sha', 'RSVP_EMAIL_ENABLED': 'false', 'PYTHONPATH': str(root),
    }
    candidate_health(release, environment, 'candidate-sha')
    assert sorted(path.name for path in persistent.iterdir()) == ['.rsvp-data']


def test_migration_copies_without_overwriting_and_keeps_source(tmp_path):
    source, destination = tmp_path / 'old', tmp_path / 'persistent'
    (source / 'data/events').mkdir(parents=True)
    event = source / 'data/events/party.json'
    event.write_text('{"slug":"party","id":"one"}')
    accounts = source / 'admins.json'
    accounts.write_text('{"admins":[{"id":"owner","credentials":[{"credential_id":"existing"}]}]}')
    assert migrate(source, destination) == 2
    assert (destination / 'events/party.json').read_bytes() == event.read_bytes()
    assert (destination / 'admins.json').read_bytes() == accounts.read_bytes()
    assert (destination / '.rsvp-data').is_file()
    assert migrate(source, destination) == 2
    (destination / 'events/party.json').write_text('{"name":"newer"}')
    with pytest.raises(ValueError, match='Refusing to overwrite'):
        migrate(source, destination)
    assert json.loads((destination / 'events/party.json').read_text())['name'] == 'newer'
    assert event.is_file() and accounts.is_file()


def _archive(path, entries):
    with tarfile.open(path, 'w:gz') as archive:
        for name, contents in entries.items():
            content = contents.encode()
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('unsafe', ['../escape', '/absolute', 'data/events/party.json', 'admins.json', 'config.py', 'rsvps_live.json', 'token.json', 'token.pickle'])
def test_release_artifact_rejects_data_and_unsafe_paths(tmp_path, unsafe):
    artifact = tmp_path / 'artifact.tar.gz'
    checksum = _archive(artifact, {'app.py': '', 'requirements-runtime.txt': '', unsafe: 'private'})
    with pytest.raises(ValueError):
        extract_artifact(artifact, tmp_path / 'release', checksum)
    assert not (tmp_path / 'release').exists()


def test_release_artifact_integrity_and_success(tmp_path):
    artifact = tmp_path / 'artifact.tar.gz'
    checksum = _archive(artifact, {'app.py': 'app', 'requirements-runtime.txt': 'Flask'})
    with pytest.raises(ValueError, match='checksum'):
        extract_artifact(artifact, tmp_path / 'release', '0' * 64)
    extract_artifact(artifact, tmp_path / 'release', checksum)
    assert (tmp_path / 'release/app.py').read_text() == 'app'


def test_failed_release_health_rolls_back_pointer_and_restarts(tmp_path):
    root = tmp_path / 'deployment'
    first, second = root / 'releases/first', root / 'releases/second'
    first.mkdir(parents=True)
    second.mkdir()
    (root / 'current').symlink_to(first)
    restarts = []
    with pytest.raises(RuntimeError, match='previous release was restored'):
        promote_release(root, second, lambda: restarts.append(True), lambda identity: identity == 'first')
    assert (root / 'current').resolve() == first
    assert restarts == [True, True]


def test_successful_release_retains_previous_for_manual_rollback(tmp_path):
    root = tmp_path / 'deployment'
    first, second = root / 'releases/first', root / 'releases/second'
    first.mkdir(parents=True)
    second.mkdir()
    (root / 'current').symlink_to(first)
    promote_release(root, second, lambda: None, lambda identity: identity == 'second')
    assert (root / 'current').resolve() == second
    assert (root / 'previous').resolve() == first

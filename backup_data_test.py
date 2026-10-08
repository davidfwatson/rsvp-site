"""Backups operate on isolated fixtures and never contact a remote repository."""
import json
from pathlib import Path
import threading

import pytest

from scripts import backup_data
from scripts.backup_data import run_backup, snapshot_data, verify_snapshot
from storage import json_lock, update_json, write_json


@pytest.fixture
def backup_source(tmp_path):
    data = tmp_path / 'persistent'
    (data / 'events').mkdir(parents=True)
    (data / 'uploads').mkdir()
    (data / '.rsvp-data').write_text('initialized')
    write_json(data / 'events/party.json', {'id': 'one', 'slug': 'party', 'version': 1})
    write_json(data / 'admins.json', {'admins': [{'id': 'owner', 'credential_id': 'existing'}]})
    write_json(data / 'rsvps_one.json', [{'name': 'Guest', 'token': 'private-token'}])
    environment = tmp_path / 'production.env'
    environment.write_text('RSVP_SECRET_KEY=private-application-secret\n')
    return data, environment


def test_local_snapshot_keeps_data_credentials_and_manifest(backup_source, tmp_path):
    data, environment = backup_source
    destination = tmp_path / 'snapshot'
    manifest = snapshot_data(data, environment, destination)
    assert (destination / 'production.env').read_bytes() == environment.read_bytes()
    assert json.loads((destination / 'data/rsvps_one.json').read_text())[0]['token'] == 'private-token'
    assert json.loads((destination / 'data/admins.json').read_text())['admins'][0]['credential_id'] == 'existing'
    assert verify_snapshot(destination) == len(manifest['files'])
    assert destination.stat().st_mode & 0o777 == 0o700
    assert not list(destination.rglob('*.lock'))
    for lock in data.rglob('*.lock'):
        assert (lock.stat().st_uid, lock.stat().st_gid) == (data.stat().st_uid, data.stat().st_gid)
    (destination / 'data/admins.json').write_text('{}')
    with pytest.raises(ValueError, match='integrity'):
        verify_snapshot(destination)


def test_snapshot_blocks_first_rsvp_write_and_upload_until_local_copy_finishes(backup_source, tmp_path, monkeypatch):
    data, environment = backup_source
    (data / 'rsvps_one.json').unlink()
    entered_copy, release_copy, writer_finished = threading.Event(), threading.Event(), threading.Event()
    original_copy = backup_data.shutil.copy2
    errors = []

    def paused_copy(source, destination):
        if Path(source).name == '.rsvp-data':
            entered_copy.set()
            assert release_copy.wait(timeout=5)
        return original_copy(source, destination)

    monkeypatch.setattr(backup_data.shutil, 'copy2', paused_copy)

    def snapshot():
        try:
            snapshot_data(data, environment, tmp_path / 'snapshot')
        except Exception as exc:
            errors.append(exc)

    def first_response():
        try:
            update_json(data / 'rsvps_one.json', lambda _: [{'name': 'New Guest'}], [])
            with json_lock(data / 'uploads/.uploads'):
                (data / 'uploads/image.webp').write_bytes(b'image')
            writer_finished.set()
        except Exception as exc:
            errors.append(exc)

    copier = threading.Thread(target=snapshot)
    copier.start()
    assert entered_copy.wait(timeout=5)
    writer = threading.Thread(target=first_response)
    writer.start()
    assert not writer_finished.wait(timeout=0.1)
    release_copy.set()
    copier.join(timeout=5)
    writer.join(timeout=5)
    assert not errors and writer_finished.is_set()
    assert not (tmp_path / 'snapshot/data/rsvps_one.json').exists()
    assert not (tmp_path / 'snapshot/data/uploads/image.webp').exists()
    assert (data / 'rsvps_one.json').exists()


def test_restic_runs_after_app_locks_release_and_applies_scoped_retention(backup_source, tmp_path):
    data, environment = backup_source
    password = tmp_path / 'restic-password'
    password.write_text('private-repository-password')
    env = {'RESTIC_REPOSITORY': 's3:https://example.test/offsite/partymail', 'RESTIC_PASSWORD_FILE': str(password)}
    calls, writer_done = [], threading.Event()

    def runner(command, cwd, passed_environment):
        calls.append(command)
        assert passed_environment == env
        assert (cwd / 'manifest.json').is_file()
        if command[1] == 'backup':
            # A writer in another thread must proceed while remote transfer runs.
            def mutate():
                with json_lock(data / 'events/.events'):
                    write_json(data / 'admins.json', {'admins': []})
                writer_done.set()
            writer = threading.Thread(target=mutate)
            writer.start()
            assert writer_done.wait(timeout=5)
            writer.join(timeout=5)
            assert json.loads((cwd / 'data/admins.json').read_text())['admins'][0]['id'] == 'owner'
            return b'{"message_type":"summary","snapshot_id":"abcdef1234567890"}\n'
        return b''

    work = tmp_path / 'backup-work'
    status = run_backup(data, environment, work, env, runner)
    assert [command[1] for command in calls] == ['backup', 'forget', 'check']
    assert '--prune' in calls[1] and '--tag' in calls[1] and 'host,tags' in calls[1]
    assert status['snapshot_id'] == 'abcdef1234567890'
    assert (work / 'last-success.json').is_file()
    assert not list(work.glob('snapshot-*'))


def test_failed_remote_backup_skips_retention_and_does_not_record_success(backup_source, tmp_path):
    data, environment = backup_source
    password = tmp_path / 'password'
    password.write_text('private')
    calls = []

    def fail(command, cwd, passed_environment):
        calls.append(command)
        raise RuntimeError('simulated backend failure')

    work = tmp_path / 'backup-work'
    with pytest.raises(RuntimeError):
        run_backup(data, environment, work, {'RESTIC_REPOSITORY': 's3:https://example.test/bucket', 'RESTIC_PASSWORD_FILE': str(password)}, fail)
    assert [command[1] for command in calls] == ['backup']
    assert not (work / 'last-success.json').exists()
    assert not list(work.glob('snapshot-*'))


def test_backup_refuses_local_destination_and_symlink_sources(backup_source, tmp_path):
    data, environment = backup_source
    with pytest.raises(ValueError, match='separate'):
        snapshot_data(data, environment, data / 'backup')
    (data / 'linked-secret').symlink_to(environment)
    with pytest.raises(ValueError, match='regular files'):
        snapshot_data(data, environment, tmp_path / 'snapshot')

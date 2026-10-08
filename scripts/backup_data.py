#!/usr/bin/env python3
"""Take a consistent local data copy, release app locks, then send it to restic."""
import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import assert_safe_write, atomic_write, json_lock


KNOWN_STORES = ('admins.json', 'token.json', 'credentials.json', 'rate_limits.json')


def _ensure_service_lock(path, owner):
    """Root backups must not create lock files that the app cannot reopen."""
    path = Path(path)
    assert_safe_write(path)
    if not path.parent.exists():
        raise ValueError('Initialize persistent events and uploads directories as the service user before enabling backups.')
    if path.parent.is_symlink():
        raise ValueError('Persistent store directories must not be symlinks.')
    lock = Path(str(path) + '.lock')
    if lock.exists():
        if lock.is_symlink() or not lock.is_file():
            raise ValueError('Persistent store locks must be regular files.')
        return
    descriptor, temporary = tempfile.mkstemp(prefix='.backup-lock-', suffix='.tmp', dir=path.parent)
    try:
        if (os.fstat(descriptor).st_uid, os.fstat(descriptor).st_gid) != owner:
            os.fchown(descriptor, *owner)
        # Publish an already service-owned inode. Do not replace a lock another
        # worker created meanwhile, or expose a briefly root-owned live lock.
        try:
            os.link(temporary, lock)
        except FileExistsError:
            if lock.is_symlink() or not lock.is_file():
                raise ValueError('Persistent store locks must be regular files.')
    finally:
        os.close(descriptor)
        os.unlink(temporary)


def snapshot_data(data_dir, app_environment, destination):
    """Copy all persistent files with every current application mutation locked."""
    data_dir, app_environment, destination = map(Path, (data_dir, app_environment, destination))
    data_dir, destination = data_dir.resolve(), destination.resolve()
    if not (data_dir / '.rsvp-data').is_file():
        raise ValueError('Refusing to back up an uninitialized persistent data directory.')
    if destination.is_relative_to(data_dir) or data_dir.is_relative_to(destination):
        raise ValueError('Snapshot must be separate from the live data directory.')
    if not app_environment.is_file() or app_environment.is_symlink():
        raise ValueError('The application environment must be an existing regular file.')
    assert_safe_write(destination)
    destination.mkdir(parents=True, mode=0o700, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError('Snapshot destination must be empty; existing backups are never overwritten.')
    destination.chmod(0o700)
    owner = (data_dir.stat().st_uid, data_dir.stat().st_gid)
    with ExitStack() as locks:
        event_lock = data_dir / 'events/.events'
        _ensure_service_lock(event_lock, owner)
        locks.enter_context(json_lock(event_lock))
        # Lock every event's RSVP file, even before its first response is written.
        # Holding the event collection lock prevents new IDs during enumeration.
        paths = {data_dir / name for name in KNOWN_STORES}
        paths.update(path for path in data_dir.rglob('*.json') if path.is_file())
        for event_path in (data_dir / 'events').glob('*.json'):
            event = json.loads(event_path.read_bytes())
            event_id = event.get('id') if isinstance(event, dict) else None
            if not isinstance(event_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', event_id):
                raise ValueError('Event has an invalid ID; inspect the data before backing it up.')
            paths.add(data_dir / f'rsvps_{event_id}.json')
        # Image uploads use a collection lock; copying cannot catch a partial image.
        paths.add(data_dir / 'uploads/.uploads')
        for path in sorted(paths):
            if not path.resolve().is_relative_to(data_dir):
                raise ValueError('Persistent stores must not link outside the data root.')
            _ensure_service_lock(path, owner)
            locks.enter_context(json_lock(path))
        copied_data = destination / 'data'
        copied_data.mkdir(mode=0o700)
        for directory, directories, filenames in os.walk(data_dir):
            current = Path(directory)
            for name in directories:
                if (current / name).is_symlink():
                    raise ValueError('Persistent data may not contain symlink directories.')
            relative = current.relative_to(data_dir)
            target_directory = copied_data / relative
            target_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            for name in filenames:
                if name.endswith(('.lock', '.tmp')):
                    continue
                source = current / name
                if source.is_symlink() or not source.is_file():
                    raise ValueError('Persistent data may only contain regular files.')
                shutil.copy2(source, target_directory / name)
        shutil.copy2(app_environment, destination / 'production.env')
    # The app resumes here. Hashing and all remote IO use only this private copy.
    manifest = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'files': {}}
    for path in sorted(destination.rglob('*')):
        if path.is_file():
            contents = path.read_bytes()
            manifest['files'][str(path.relative_to(destination))] = {
                'size': len(contents), 'sha256': hashlib.sha256(contents).hexdigest(),
            }
    atomic_write(destination / 'manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
    return manifest


def verify_snapshot(snapshot):
    """Verify a restored snapshot without displaying guest data or secrets."""
    snapshot = Path(snapshot).resolve()
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    if manifest.get('schema_version') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('Unsupported snapshot manifest.')
    for relative, expected in manifest['files'].items():
        path = (snapshot / relative).resolve()
        if not path.is_relative_to(snapshot) or not path.is_file():
            raise ValueError('Snapshot has a missing or unsafe file.')
        contents = path.read_bytes()
        if len(contents) != expected['size'] or hashlib.sha256(contents).hexdigest() != expected['sha256']:
            raise ValueError('Snapshot integrity verification failed.')
    return len(manifest['files'])


def _restic(command, cwd, environment):
    result = subprocess.run(command, cwd=cwd, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        # Backend errors may include credential-bearing URLs; keep logs generic.
        raise RuntimeError(f'Restic {command[1]} failed with exit {result.returncode}; inspect the backup repository using its private configuration.')
    return result.stdout


@contextmanager
def backup_lock(work_dir):
    """Serialize timer/manual runs and keep private snapshots out of public dirs."""
    work_dir = Path(work_dir)
    assert_safe_write(work_dir)
    work_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    work_dir.chmod(0o700)
    with open(work_dir / '.backup.lock', 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def run_backup(data_dir, app_environment, work_dir, environment=None, runner=None):
    """Back up offsite, then apply retention only after a successful new backup."""
    environment = dict(os.environ if environment is None else environment)
    runner = runner or _restic
    repository = environment.get('RESTIC_REPOSITORY', '')
    if not repository or 'REPLACE' in repository or not repository.startswith(('s3:', 'sftp:', 'rest:', 'b2:', 'azure:', 'gs:', 'rclone:')):
        raise ValueError('Configure a remote RESTIC_REPOSITORY in /etc/rsvp-backup.env.')
    password_file = environment.get('RESTIC_PASSWORD_FILE', '')
    if not password_file or not Path(password_file).is_file():
        raise ValueError('Set RESTIC_PASSWORD_FILE to the private repository password file.')
    identity = environment.get('RSVP_BACKUP_HOST', 'partymail-production')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', identity):
        raise ValueError('RSVP_BACKUP_HOST must contain letters, numbers, underscores, or hyphens.')
    executable = environment.get('RSVP_RESTIC_BINARY', '/usr/bin/restic')
    work_dir = Path(work_dir)
    with backup_lock(work_dir):
        with tempfile.TemporaryDirectory(prefix='snapshot-', dir=work_dir) as temporary:
            snapshot = Path(temporary)
            manifest = snapshot_data(data_dir, app_environment, snapshot)
            output = runner([executable, 'backup', '--json', '--host', identity, '--tag', 'partymail-production',
                '--group-by', 'host,tags', 'data', 'production.env', 'manifest.json'], snapshot, environment)
            snapshot_id = ''
            for line in output.decode().splitlines():
                message = json.loads(line)
                if message.get('message_type') == 'summary':
                    snapshot_id = message.get('snapshot_id', '')
            if not re.fullmatch(r'[a-f0-9]{8,64}', snapshot_id):
                raise RuntimeError('Restic did not confirm a completed snapshot; retention was skipped.')
            # Restrict retention to this app's tag and host, ignoring temporary paths.
            runner([executable, 'forget', '--host', identity, '--tag', 'partymail-production', '--group-by', 'host,tags',
                '--keep-last', '3', '--keep-daily', '14', '--keep-weekly', '8', '--keep-monthly', '12', '--prune'], snapshot, environment)
            runner([executable, 'check'], snapshot, environment)
            status = {'completed_at': datetime.now(timezone.utc).isoformat(), 'snapshot_id': snapshot_id,
                'files': len(manifest['files']), 'host': identity}
            atomic_write(work_dir / 'last-success.json', (json.dumps(status, indent=2) + '\n').encode())
            return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('RSVP_BACKUP_DATA_DIR', '/var/lib/rsvp-site')))
    parser.add_argument('--app-env', type=Path, default=Path(os.environ.get('RSVP_BACKUP_APP_ENV', '/etc/rsvp-site.env')))
    parser.add_argument('--work-dir', type=Path, default=Path(os.environ.get('RSVP_BACKUP_WORK_DIR', '/var/lib/rsvp-backup')))
    parser.add_argument('--snapshot-only', type=Path, help='Create a local private snapshot without any restic/network calls.')
    parser.add_argument('--verify', type=Path, help='Verify files against a restored snapshot manifest.')
    args = parser.parse_args()
    try:
        if args.verify:
            count = verify_snapshot(args.verify)
            print(f'Snapshot integrity verified: {count} files.')
        elif args.snapshot_only:
            result = snapshot_data(args.data_dir, args.app_env, args.snapshot_only)
            print(f'Local private snapshot ready: {len(result["files"])} files. No remote backup was run.')
        else:
            result = run_backup(args.data_dir, args.app_env, args.work_dir)
            print(f'Encrypted offsite backup complete: snapshot {result["snapshot_id"]}.')
    except (ValueError, RuntimeError, OSError) as exc:
        # Do not print source-file contents, environment values, or backend stderr.
        parser.exit(1, f'Backup failed: {exc}\n')


if __name__ == '__main__':
    main()

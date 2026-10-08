"""Durable JSON storage with process/thread locks and recoverable previous values."""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid


class StorageError(RuntimeError):
    """A store is unreadable; callers must not turn corruption into an empty store."""


_locks = {}
_locks_guard = threading.Lock()
_held = threading.local()


def assert_safe_write(path):
    """Test processes may only write under the root assigned before collection."""
    if os.environ.get('RSVP_ENV') == 'test' or 'pytest' in sys.modules or os.environ.get('PYTEST_CURRENT_TEST'):
        root = os.environ.get('RSVP_TEST_DATA_ROOT')
        if not root or not Path(path).resolve().is_relative_to(Path(root).resolve()):
            raise RuntimeError('Refusing test write outside RSVP_TEST_DATA_ROOT; live data is protected.')


@contextmanager
def json_lock(path):
    """Hold a reentrant thread and advisory process lock for a file or collection."""
    path = Path(path).resolve()
    assert_safe_write(path)
    with _locks_guard:
        lock = _locks.setdefault(str(path), threading.RLock())
    with lock:
        held = getattr(_held, 'paths', {})
        _held.paths = held
        if str(path) in held:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(path) + '.lock', 'a', encoding='utf-8') as handle:
            os.chmod(handle.name, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            held[str(path)] = handle
            try:
                yield
            finally:
                held.pop(str(path), None)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_json(path, default):
    """Read complete JSON, treating missing files differently from corrupt files."""
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except FileNotFoundError:
        return deepcopy(default)
    except (OSError, ValueError) as exc:
        raise StorageError(f'Cannot read JSON store {path}; preserve the file and restore a backup.') from exc


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path, contents):
    """Replace a file with complete bytes; sync both data and directory metadata."""
    path = Path(path)
    assert_safe_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def backup_file(path):
    """Keep the last 20 previous revisions, outside the set of active JSON files."""
    path = Path(path)
    if not path.exists():
        return
    contents = path.read_bytes()
    backups = path.parent / '.backups' / path.name
    assert_safe_write(backups)
    backups.mkdir(parents=True, exist_ok=True)
    stamp = f'{time.time_ns():020d}-{uuid.uuid4().hex}.bak'
    atomic_write(backups / stamp, contents)
    for old in sorted(backups.glob('*.bak'))[:-20]:
        old.unlink()


def write_json(path, data):
    """Atomically replace one JSON document and back up its previous value."""
    serialized = (json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    with json_lock(path):
        # A corrupt store should never be silently overwritten with an empty one.
        if Path(path).exists():
            read_json(path, None)
        backup_file(path)
        atomic_write(path, serialized)
    return data


def update_json(path, mutator, default):
    """Lock the complete read-modify-write; return the committed JSON document."""
    with json_lock(path):
        data = read_json(path, default)
        replacement = mutator(data)
        if replacement is not None:
            data = replacement
        return write_json(path, data)

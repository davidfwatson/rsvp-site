#!/usr/bin/env python3
"""Verify an uploaded artifact, test it, and promote with health-checked rollback."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
from urllib.request import urlopen
import uuid


def load_environment(path):
    """Read KEY=value without executing a shell or interpreting substitutions."""
    env = os.environ.copy()
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, raw = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise ValueError('Environment file must contain KEY=value entries.')
        values = shlex.split(raw, comments=True)
        if len(values) > 1:
            raise ValueError(f'Quote values containing spaces: {key}')
        env[key] = values[0] if values else ''
    if env.get('RSVP_ENV') != 'production':
        raise ValueError('Release activation requires RSVP_ENV=production in the environment file.')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def extract_artifact(artifact, destination, checksum):
    """Check integrity and reject runtime data, path traversal, or archive links."""
    actual = hashlib.sha256(Path(artifact).read_bytes()).hexdigest()
    if not re.fullmatch(r'[a-f0-9]{64}', checksum) or actual != checksum:
        raise ValueError('Artifact checksum does not match.')
    forbidden = {'data', 'config.py', 'admins.json', 'credentials.json', 'token.pickle', 'token.json', '.git', '.env', '.claude', 'venv'}
    with tarfile.open(artifact, 'r:gz') as archive:
        for item in archive.getmembers():
            path = Path(item.name)
            if path.is_absolute() or '..' in path.parts or not path.parts:
                raise ValueError('Unsafe artifact path.')
            if path.parts[0] in forbidden or path.name.startswith('rsvps_') and path.suffix == '.json':
                raise ValueError(f'Artifact must not include runtime data: {item.name}')
            if not (item.isfile() or item.isdir()):
                raise ValueError('Artifact links and special files are not allowed.')
        archive.extractall(destination, filter='data')
    if not (Path(destination) / 'app.py').is_file() or not (Path(destination) / 'requirements-runtime.txt').is_file():
        raise ValueError('Artifact is missing application or runtime requirements.')


def atomic_symlink(target, link):
    """Replace a release pointer atomically on the same filesystem."""
    link = Path(link)
    temporary = link.with_name('.' + link.name + '-' + uuid.uuid4().hex)
    try:
        temporary.symlink_to(Path(target).resolve(), target_is_directory=True)
        os.replace(temporary, link)
        descriptor = os.open(link.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def check_health(url, release_id, timeout=40):
    """Require the expected release, not an old worker's successful response."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                result = json.load(response)
            if result.get('status') == 'ok' and result.get('release') == release_id:
                return True
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    return False


def promote_release(root, release, restart, healthy):
    """Switch code only; failed restart/health restores the previous release."""
    root, release = Path(root), Path(release).resolve()
    releases = (root / 'releases').resolve()
    if not release.is_relative_to(releases) or not release.is_dir():
        raise ValueError('Can only activate an existing release beneath releases/.')
    current = root / 'current'
    previous = current.resolve() if current.is_symlink() else None
    if current.exists() and not current.is_symlink():
        raise ValueError('current must be a symlink, never a directory to overwrite.')
    if previous and not previous.is_relative_to(releases):
        raise ValueError('Existing current pointer is outside releases/.')
    atomic_symlink(release, current)
    try:
        restart()
        if not healthy(release.name):
            raise RuntimeError('Promoted release failed its health check.')
    except Exception as exc:
        if previous:
            atomic_symlink(previous, current)
            try:
                restart()
                restored = healthy(previous.name)
            except Exception:
                restored = False
            if not restored:
                raise RuntimeError('Deployment failed; previous pointer restored but rollback health failed. Inspect the service.') from exc
        else:
            current.unlink(missing_ok=True)
        raise RuntimeError('Deployment failed; the previous release was restored.' if previous else 'First deployment failed; no release was activated.') from exc
    if previous and previous != release:
        atomic_symlink(previous, root / 'previous')


@contextmanager
def deployment_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / '.deploy.lock', 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def candidate_health(release, environment, release_id):
    """Boot the actual production artifact on a private socket before promotion."""
    with socket.socket() as listener, tempfile.TemporaryFile() as logs:
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        descriptor = listener.fileno()
        process = subprocess.Popen(
            [str(release / 'venv/bin/gunicorn'), '--bind', f'fd://{descriptor}', '--workers', '1', '--access-logfile', '-', 'app:app'],
            cwd=release, env=environment, pass_fds=(descriptor,), stdout=logs, stderr=subprocess.STDOUT,
        )
        try:
            host = environment.get('RSVP_PUBLIC_URL', 'https://partymail.app').split('://', 1)[-1].rstrip('/')
            # TRUSTED_HOSTS enforces the public host even over the private socket.
            from urllib.request import Request
            request = Request(f'http://127.0.0.1:{port}/healthz', headers={'Host': host})
            if not check_health(request, release_id):
                logs.seek(0)
                # Logs contain startup diagnostics, never environment values.
                raise RuntimeError('Candidate startup/health failed:\n' + logs.read().decode(errors='replace')[-4000:])
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def deploy(args):
    # Release code must be readable by the separate, unprivileged service user.
    os.umask(0o022)
    root = args.root.resolve()
    environment = load_environment(args.env_file)
    data = Path(environment.get('RSVP_DATA_DIR', '')).resolve()
    if data.is_relative_to(root):
        raise ValueError('Persistent data must live outside the deployment root.')
    with deployment_lock(root):
        releases = root / 'releases'
        releases.mkdir(exist_ok=True)
        release = releases / args.release
        if release.exists():
            raise ValueError('Release already exists. Use --rollback to activate it; never rebuild a tested release.')
        stage = Path(tempfile.mkdtemp(prefix='.' + args.release + '-', dir=releases))
        try:
            extract_artifact(args.artifact, stage, args.sha256)
            (stage / 'RELEASE_ID').write_text(args.release + '\n')
            # Move before venv creation: venv executable shebangs retain this path.
            stage.rename(release)
            release.chmod(0o755)
            subprocess.run([args.python, '-m', 'venv', str(release / 'venv')], check=True)
            python = str(release / 'venv/bin/python')
            subprocess.run([python, '-m', 'pip', 'install', '-r', 'requirements-dev.txt'], cwd=release, check=True)
            # conftest overrides production env before importing any app module.
            subprocess.run([python, '-m', 'pytest', '-q'], cwd=release, env=environment, check=True)
            environment['RSVP_RELEASE_ID'] = args.release
            candidate_health(release, environment, args.release)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            shutil.rmtree(release, ignore_errors=True)
            raise
        (release / '.verified').write_text(args.sha256 + '\n')
        # Test tooling remains on disk for auditing; it never runs in the service.
        restart = lambda: subprocess.run(['sudo', '-n', 'systemctl', 'restart', args.service], check=True)
        promote_release(root, release, restart, lambda identity: check_health(args.health_url, identity))
        print(f'Activated tested release {args.release}. Persistent data was not replaced.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/srv/rsvp'))
    parser.add_argument('--env-file', type=Path, default=Path('/etc/rsvp-site.env'))
    parser.add_argument('--service', default='rsvp-site.service')
    parser.add_argument('--health-url', default='https://partymail.app/healthz')
    parser.add_argument('--python', default='python3.12')
    parser.add_argument('--artifact', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--release')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    if args.rollback:
        with deployment_lock(args.root):
            previous = args.root / 'previous'
            if not previous.is_symlink() or not (previous.resolve() / '.verified').is_file():
                parser.error('No previously verified release is available.')
            restart = lambda: subprocess.run(['sudo', '-n', 'systemctl', 'restart', args.service], check=True)
            promote_release(args.root, previous.resolve(), restart, lambda identity: check_health(args.health_url, identity))
        print('Previous verified release activated. Persistent data retained.')
    else:
        if not args.artifact or not args.sha256 or not re.fullmatch(r'[a-f0-9]{40}', args.release or ''):
            parser.error('--artifact, --sha256, and a full 40-character Git SHA --release are required.')
        deploy(args)


if __name__ == '__main__':
    main()

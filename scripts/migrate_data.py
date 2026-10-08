#!/usr/bin/env python3
"""Copy legacy data into an external root without overwriting any existing data."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import atomic_write


def migrate(source, destination, init_empty=False):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.is_relative_to(source):
        raise ValueError('Choose a destination outside the source checkout.')
    candidates = []
    for path in sorted((source / 'data').rglob('*')):
        if path.is_file() and not path.name.endswith(('.lock', '.tmp')):
            candidates.append((path, path.relative_to(source / 'data')))
    for pattern in ('rsvps_*.json', 'admins.json', 'credentials.json', 'token.pickle', 'token.json'):
        candidates.extend((path, Path(path.name)) for path in sorted(source.glob(pattern)) if path.is_file())
    generated = []
    legacy = source / 'event_config.json'
    if not any(str(relative).startswith('events/') for _, relative in candidates) and legacy.is_file():
        events = json.loads(legacy.read_text())
        if not isinstance(events, list):
            raise ValueError('Legacy event_config.json must contain a list.')
        from event_slug import validate_slug
        for event in events:
            if not isinstance(event, dict) or not validate_slug(event.get('slug', ''))[0]:
                raise ValueError('Migrate missing/invalid legacy slugs before copying data.')
            generated.append((Path('events') / (event['slug'] + '.json'), (json.dumps(event, indent=2) + '\n').encode()))
    if not candidates and not generated and not init_empty:
        raise ValueError('No legacy data found. Use --init-empty only for a new installation.')
    contents = [(relative, path.read_bytes()) for path, relative in candidates] + generated
    seen = {}
    # Validate everything before the first write, including duplicate old/new files.
    for relative, value in contents:
        if relative in seen and seen[relative] != value:
            raise ValueError(f'Conflicting source files for {relative}; choose the authoritative copy first.')
        seen[relative] = value
        if relative.suffix == '.json':
            json.loads(value)
        target = destination / relative
        if target.exists() and target.read_bytes() != value:
            raise ValueError(f'Refusing to overwrite existing destination {relative}.')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'events').mkdir(exist_ok=True)
    (destination / 'uploads').mkdir(exist_ok=True)
    for relative, value in seen.items():
        target = destination / relative
        if not target.exists():
            atomic_write(target, value)
    marker = destination / '.rsvp-data'
    if not marker.exists():
        atomic_write(marker, b'Party Mail persistent data; never replace during deployment.\n')
    return len(seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--init-empty', action='store_true')
    args = parser.parse_args()
    try:
        count = migrate(args.source, args.destination, args.init_empty)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Migration stopped: {exc}\n')
    print(f'Copied/verified {count} files. Original source files were retained.')


if __name__ == '__main__':
    main()

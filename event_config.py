"""Event definitions persisted independently from application releases."""
from copy import deepcopy
import os
from pathlib import Path
import uuid

from event_slug import generate_unique_slug, validate_slug
from runtime_config import data_path
from storage import backup_file, json_lock, read_json, write_json


# Top-level routes in app.py; an event with one of these slugs could never be opened.
RESERVED_SLUGS = frozenset({'admin', 'healthz', 'media', 'oauth2callback', 'privacy', 'static', 'terms'})
DEFAULT_EVENTS_DIR = str(data_path('events'))


class EventConflictError(ValueError):
    """An editor attempted to save an older version of an event."""


class EventConfig:
    def __init__(self, events_dir=None):
        self.events_dir = str(events_dir) if events_dir is not None else DEFAULT_EVENTS_DIR
        self._events = self._load_config()
        self._disk_snapshot = self._signature()

    def _signature(self):
        root = Path(self.events_dir)
        if not root.is_dir():
            return ()
        result = []
        for path in sorted(root.glob('*.json')):
            try:
                stat = path.stat()
                result.append((path.name, stat.st_mtime_ns, stat.st_size, stat.st_ino))
            except FileNotFoundError:
                continue
        return tuple(result)

    def _load_config(self):
        events = []
        for path in sorted(Path(self.events_dir).glob('*.json')):
            if not path.exists():
                continue
            event = read_json(path, None)
            if isinstance(event, dict) and event.get('slug'):
                events.append(event)
            else:
                raise ValueError(f'Invalid event document: {path}')
        return events

    def _refresh(self):
        snapshot = self._signature()
        if snapshot != self._disk_snapshot:
            # Preserve the public alias and permit legacy fixtures to inject
            # events when disk contents have not changed.
            self._events[:] = self._load_config()
            self._disk_snapshot = snapshot

    def _assert_safe_write(self):
        from storage import assert_safe_write
        assert_safe_write(Path(self.events_dir) / '.events')

    def _event_path(self, slug):
        valid, error = validate_slug(slug)
        if not valid:
            raise ValueError(f'Invalid slug: {error}')
        return Path(self.events_dir) / f'{slug}.json'

    def _save_event(self, event):
        self._assert_safe_write()
        if not event.get('slug'):
            raise ValueError('Event must have a slug')
        write_json(self._event_path(event['slug']), event)
        self._disk_snapshot = self._signature()

    def _delete_event_file(self, slug):
        self._assert_safe_write()
        path = self._event_path(slug)
        if path.exists():
            backup_file(path)
            path.unlink()
        self._disk_snapshot = self._signature()

    def _save_config(self):
        with json_lock(Path(self.events_dir) / '.events'):
            for event in self._events:
                if isinstance(event, dict) and event.get('slug'):
                    self._save_event(event)

    def get_event_config(self, domain_or_slug):
        self._refresh()
        for event in self._events:
            if isinstance(event, dict) and (event.get('domain') == domain_or_slug or event.get('slug') == domain_or_slug):
                # Rendering adds derived HTML fields; isolate them from storage.
                return deepcopy(event)
        if domain_or_slug.startswith(('127.0.0.1', 'localhost')):
            return deepcopy(self._events[-1]) if self._events else None
        return None

    def get_all_events(self):
        self._refresh()
        return {event['slug']: deepcopy(event) for event in self._events if isinstance(event, dict)}

    def get_existing_slugs(self):
        self._refresh()
        return {event.get('slug') for event in self._events if isinstance(event, dict)}

    def update_event_config(self, slug, new_config, expected_version=None):
        """Commit an event while rejecting a stale editor's expected version."""
        with json_lock(Path(self.events_dir) / '.events'):
            self._refresh()
            current = next((e for e in self._events if e.get('slug') == slug), None)
            version = int(current.get('version', 0)) if current else 0
            if expected_version is not None and int(expected_version) != version:
                raise EventConflictError('This event was changed in another tab. Reload before saving.')
            updated = deepcopy(new_config)
            updated.setdefault('slug', slug)
            new_slug = updated['slug']
            self._event_path(new_slug)
            if new_slug != slug and new_slug in self.get_existing_slugs() | RESERVED_SLUGS:
                raise ValueError(f"Slug '{new_slug}' is already in use")
            if current and updated.get('id') != current.get('id'):
                raise ValueError('An event ID cannot be changed.')
            updated['version'] = version + 1
            self._save_event(updated)
            if new_slug != slug:
                self._delete_event_file(slug)
            if current:
                self._events[self._events.index(current)] = updated
            else:
                self._events.append(updated)
            return deepcopy(updated)

    def add_new_event(self, event_data):
        with json_lock(Path(self.events_dir) / '.events'):
            self._refresh()
            event_id = str(uuid.uuid4())[:8]
            existing = self.get_existing_slugs() | RESERVED_SLUGS
            if event_data.get('slug'):
                slug = event_data['slug'].strip().lower()
                self._event_path(slug)
                if slug in existing:
                    raise ValueError(f"Slug '{slug}' is already in use")
            else:
                slug = generate_unique_slug(event_data['name'], existing)
            new_event = {
                'domain': 'partymail.app', 'id': event_id, 'slug': slug,
                'name': event_data['name'], 'date': event_data['date'],
                'start_time': event_data['start_time'], 'end_time': event_data.get('end_time', ''),
                'location': event_data['location'], 'description': event_data['description'],
                'max_guests_per_invite': int(event_data['max_guests_per_invite']),
                'color_scheme': event_data.get('color_scheme', 'pink'), 'version': 1,
            }
            # Import lazily: presentation defaults should not gate storage imports.
            try:
                from event_editor import DESIGN_DEFAULTS
            except ImportError:
                DESIGN_DEFAULTS = {}
            new_event.update({key: event_data.get(key, value) for key, value in DESIGN_DEFAULTS.items()})
            for key in ('background_color', 'background_image', 'cover_image', 'card_style', 'font_style', 'envelope_color', 'accent_color', 'invitation_style'):
                if key in event_data:
                    new_event[key] = event_data[key]
            self._save_event(new_event)
            self._events.append(new_event)
            return event_id


_instance = EventConfig()
get_event_config = _instance.get_event_config
get_all_events = _instance.get_all_events
update_event_config = _instance.update_event_config
add_new_event = _instance.add_new_event
get_existing_slugs = _instance.get_existing_slugs
events = _instance._events


def save_event_config(events_list):
    """Legacy fixture helper; production changes use versioned per-event updates."""
    if os.environ.get('RSVP_ENV') == 'production':
        raise RuntimeError('Batch event replacement is disabled in production.')
    _instance._events[:] = deepcopy(list(events_list))
    _instance._save_config()


def format_event_time(event):
    start, end = event.get('start_time', ''), event.get('end_time', '')
    return f'{start} - {end}' if end else start

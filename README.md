# Party Mail

A Flask invitation and RSVP app with a responsive administrator workspace,
passkey accounts, one-use access links, invitation customization, and a guest
list for each event.

## Development

Use Python 3.12:

```bash
python3.12 -m venv venv
source venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
RSVP_ADMIN_PASSWORD=local-development-only python app.py
```

Local `config.py` is optional and gitignored. Environment variables override
its values. Development data defaults to `data/`; use `RSVP_DATA_DIR` to choose
another directory. Development and tests default to email delivery disabled.
The optional private `notify-service` integration is kept out of the public
runtime requirements so a clean clone can install and test without SSH access
to another repository.

Open `http://localhost:5000/admin/login`, expand **Owner recovery**, and use
`local-development-only` for the command above. Add your first passkey in
**People & access**. Use localhost for local passkey testing; an IP address is
not a valid WebAuthn relying-party domain. The example password is for local
development only; production uses its separate environment configuration.

## Configuration

| Variable | Purpose |
| --- | --- |
| `RSVP_ENV` | `development` (default), `test`, or `production` |
| `RSVP_DATA_DIR` | Persistent data root, required outside the checkout in production |
| `RSVP_SECRET_KEY` | Random Flask session/CSRF signing secret, required in production |
| `RSVP_PUBLIC_URL` | Canonical origin, e.g. `https://partymail.app` |
| `RSVP_WEBAUTHN_RP_ID` | Passkey hostname; keep `partymail.app` for existing accounts |
| `RSVP_WEBAUTHN_ORIGIN` | Matching HTTPS public origin |
| `RSVP_WEBAUTHN_RP_NAME` | Account/passkey display name |
| `RSVP_SENDER_EMAIL` | Authorized Gmail sender |
| `RSVP_EMAIL_ENABLED` | Enable real mail delivery; false for development/tests |
| `RSVP_GA_MEASUREMENT_ID` | Google Analytics property; empty disables tracking |
| `RSVP_ADMIN_PASSWORD` | Optional owner bootstrap/emergency password |
| `RSVP_TRUST_PROXY` | Enable only behind the documented single trusted nginx proxy |

`deploy/production.env.example` supplies a concrete production configuration.
The previously hardcoded Google Analytics property is `G-52ZJ7PXYEC`; verify
its ownership and web stream before reusing it. Guest tracking is configured
centrally and requires consent; admin and private link pages are excluded.

## Storage and production

Events are versioned JSON files under `<data root>/events`; accounts, RSVPs,
uploads, and Gmail credentials also stay inside the data root. Storage uses
process locks, atomic replacement, directory fsync, and 20 recoverable prior
revisions. Corrupt data fails visibly. Event saves reject stale versions, and
workers pick up edits made by other workers.

Tests override inherited production settings before importing app or storage
modules. Every test gets fresh temporary data, and storage refuses writes
outside its temporary test root. Do not point ad hoc scripts at production
unless they explicitly implement a reviewed migration.

The production workflow tests each main commit, uploads a source artifact,
checks it again on the server, starts a candidate privately, and promotes a
release symlink only after health succeeds. Failed promotion restores the
previous code. Persistent data is never replaced by deployment.

Follow [the production and recovery runbook](docs/production.md) for the
one-time data copy, systemd/nginx setup, CI secrets, merge deployment, backups,
and rollback. `/healthz` reports the running release for deployment checks.
Ready-to-install nightly restic backup units make a consistent local copy
under app locks, then encrypt it and upload it to snowblind over SFTP after
releasing those locks. A failed run sends a push through notify-service.

The existing `requirements.txt` and `rsvp-site.ini` remain for legacy setups;
new release deployments use `requirements-runtime.txt` and gunicorn.

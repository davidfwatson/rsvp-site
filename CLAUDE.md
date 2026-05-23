# RSVP Site Development Guide

## Commands
- Run app locally: `python3.10 app.py`
- Run all tests: `python3.10 -m pytest -v`
- Run specific test: `python3.10 -m pytest -v event_config_test.py::test_function_name`
- Run tests with coverage: `python3.10 -m pytest --cov=. --cov-report=term`
- Activate virtual environment: `source venv/bin/activate`

## Code Style Guidelines
- Import order: standard library → third-party → local modules
- Naming: snake_case for functions/variables, PascalCase for classes
- Tests: name files `*_test.py` and test functions `test_*`
- Docstrings: use for all functions, particularly tests
- Error handling: use try/except with specific exceptions
- Patterns: flask route functions, singleton for config
- Templates: Jinja2 in /templates, static assets in /static

## Project Structure
- Flask app routes in app.py
- Configuration management in event_config.py
- Email handling in email_handler.py
- Event slug generation in event_slug.py
- Tests with fixtures in conftest.py
- Template styling via static/invitation.css

## Deployment
- Production runs on a cloud Linode instance (accessible via SSH)
- Local development on the developer's machine

---

## TODO: passkey auth — NOT a migration candidate (different domain)

Other davidfwatson.com apps (gobble, forward-mail/DMARC dashboard,
manifold-monitor) now share a single passkey file at
[`~/webserver/server-ops/passkeys.json`](https://github.com/davidfwatson/server-ops/blob/main/passkeys.json)
with `RP_ID = davidfwatson.com` (apex), so one passkey works on every
subdomain. **This app does NOT join that pool** — its `RP_ID` is
`partymail.app` (see `config.py`), a completely different domain and
security boundary. Mixing partymail.app credentials with
davidfwatson.com ones would be a category error.

**What to do instead if you stand up a second partymail.app app:**
create a parallel shared `passkeys.json` for that domain — either in a
new `partymail-ops` repo, or as a sibling
`server-ops/passkeys-partymail.json`. Then both apps point at it the
same way davidfwatson.com apps point at the existing one. The shared
`passkey_auth.py` library in server-ops works fine for any domain —
the data file just has to match the RP_ID scope.

**Existing data:** `admins.json` has 2 users (Owner + Pardis) with
passkeys scoped to `partymail.app`. Leave them alone.

Full canonical recipe + per-app status:
https://github.com/davidfwatson/server-ops/blob/main/docs/passkey-migration.md
#!/usr/bin/env python3
"""An isolated Party Mail demo server. Never uses the checkout's live data.

    venv/bin/python scripts/mobile_fixture.py
    venv/bin/python scripts/mobile_fixture.py --smoke

The owner password is the public test credential `test`. Restarting discards
all mutations. Email, notifications and analytics are disabled.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def configure_fixture(data_root: Path, port: int) -> None:
    """Set isolation BEFORE importing application modules with store paths."""
    os.environ.update(
        RSVP_ENV="test", RSVP_DATA_DIR=str(data_root),
        RSVP_TEST_DATA_ROOT=str(data_root), RSVP_EMAIL_ENABLED="false",
        RSVP_PUBLIC_URL=f"http://127.0.0.1:{port}",
        RSVP_ADMIN_PASSWORD="test", RSVP_SECRET_KEY="mobile-fixture-only",
        RSVP_GA_MEASUREMENT_ID="", RSVP_TRUST_PROXY="false",
        RSVP_CONTACT_EMAIL="fixture@example.invalid",
        RSVP_WEBAUTHN_RP_ID="localhost", RSVP_WEBAUTHN_ORIGIN=f"http://127.0.0.1:{port}",
    )
    # The fixture must not inherit notification or native association settings.
    for name in ("RSVP_ANDROID_APP_ORIGINS", "RSVP_ANDROID_SHA256_CERT_FINGERPRINTS"):
        os.environ.pop(name, None)


def seed_fixture(data_root: Path) -> None:
    events_root = data_root / "events"
    events_root.mkdir(parents=True)
    event = {
        "id": "demo-party", "slug": "demo-party", "name": "Garden Party",
        "date": (date.today() + timedelta(days=14)).isoformat(), "start_time": "17:00",
        "end_time": "20:00", "location": "123 Example Lane",
        "description": "Join us for **dinner in the garden**. Bring a favorite dessert!",
        "max_guests_per_invite": 5, "color_scheme": "pink", "version": 1,
        "background_style": "linen", "background_color": "#f4efe7",
        "accent_color": "#95604b", "background_image": "", "cover_image": "",
        "font_style": "serif", "envelope_style": "classic",
        "show_attendees": True, "archived": False,
    }
    archived = dict(event, id="past-party", slug="past-party", name="Last Year's Dinner",
                    date=(date.today() - timedelta(days=30)).isoformat(), archived=True,
                    color_scheme="blue")
    for item in (event, archived):
        (events_root / f"{item['slug']}.json").write_text(json.dumps(item))
    responses = [
        {"name": "Alex Example", "email": "alex@example.invalid", "attending": "yes",
         "num_adults": 2, "num_children": 1, "dietary_restrictions": "Vegetarian",
         "comment": "We will bring cake.", "timestamp": "2026-01-01T12:00:00+00:00",
         "updated_at": "2026-01-01T12:00:00+00:00", "token": "demo-update-token-0123456789abcdef"},
        {"name": "Sam Sample", "email": "sam@example.invalid", "attending": "no",
         "num_adults": 0, "num_children": 0, "dietary_restrictions": "", "comment": "See you next time!",
         "timestamp": "2026-01-02T12:00:00+00:00", "token": "demo-decline-token-0123456789abcdef"},
    ]
    (data_root / "rsvps_demo-party.json").write_text(json.dumps(responses))
    (data_root / "admins.json").write_text(json.dumps({
        "admins": [{"id": "demo-owner", "name": "Demo Host", "is_owner": True,
                    "credentials": [], "created_at": "2026-01-01T12:00:00+00:00", "auth_version": 0}],
        "invites": [], "signin_links": [], "challenges": {},
    }))


def smoke(app) -> None:
    """Exercise the same cookie/CSRF API contract as the apps without networking."""
    client = app.test_client()
    session = client.get("/api/mobile/session")
    assert session.status_code == 200, session.status_code
    csrf = {"X-CSRF-Token": session.json["csrf_token"]}
    login = client.post("/api/mobile/login", json={"password": "test"}, headers=csrf)
    assert login.status_code == 200, login.status_code
    assert login.json["admin"]["name"] == "Demo Host"
    csrf = {"X-CSRF-Token": login.json["csrf_token"]}
    events = client.get("/api/mobile/events")
    assert events.status_code == 200 and len(events.json["events"]) == 2
    detail = client.get("/api/mobile/events/demo-party")
    assert detail.status_code == 200 and len(detail.json["rsvps"]) == 2
    event = detail.json["event"]
    patched = client.patch("/api/mobile/events/demo-party", json={"version": event["version"], "name": "Updated Garden Party"}, headers=csrf)
    assert patched.status_code == 200, patched.status_code
    stale = client.patch("/api/mobile/events/demo-party", json={"version": event["version"], "name": "Stale edit"}, headers=csrf)
    assert stale.status_code == 409, stale.status_code
    exported = client.get("/api/mobile/events/demo-party/export")
    assert exported.status_code == 200 and b"Alex Example" in exported.data
    invite = client.post("/api/mobile/events/demo-party/invite", json={"email": "new@example.invalid"}, headers=csrf)
    assert invite.status_code == 503, invite.status_code
    assert client.post("/api/mobile/logout", json={}, headers=csrf).status_code == 200
    assert client.get("/api/mobile/events").status_code == 401
    assert client.get("/api/mobile/invitations/demo-party").status_code == 200
    assert client.get("/api/mobile/invitations/past-party").status_code == 404
    csrf = {"X-CSRF-Token": client.get("/api/mobile/session").json["csrf_token"]}
    response = client.post("/api/mobile/invitations/demo-party/rsvp", headers=csrf, json={
        "name": "Smoke Guest", "email": "smoke@example.invalid", "attending": "yes",
        "num_adults": 1, "num_children": 0, "dietary_restrictions": "", "comment": "",
    })
    assert response.status_code == 201, response.status_code
    assert response.json["email_delivered"] is False
    token = response.json["response"]["token"]
    updated = client.patch(f"/api/mobile/invitations/demo-party/responses/{token}", headers=csrf, json={
        "name": "Smoke Guest", "email": "smoke@example.invalid", "attending": "no",
    })
    assert updated.status_code == 200, updated.status_code
    print("✓ mobile fixture smoke: session, login, events, editing/conflict, CSV, disabled email, logout, guest RSVP/update")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1")
    parser.add_argument("--smoke", action="store_true", help="run an isolated API integration check and exit")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    with tempfile.TemporaryDirectory(prefix="partymail-mobile-") as temporary:
        data_root = Path(temporary)
        configure_fixture(data_root, args.port)
        seed_fixture(data_root)
        sys.path.insert(0, str(ROOT))
        from app import app
        app.config.update(TESTING=True, EMAIL_ENABLED=False, GA_MEASUREMENT_ID="", ADMIN_PASSWORD="test")
        @app.after_request
        def identify_fixture(response):
            # Readiness must never mistake an existing local service for this
            # isolated server (macOS can reserve port 5000 for AirPlay).
            response.headers["X-PartyMail-Fixture"] = "isolated"
            return response
        if args.smoke:
            smoke(app)
        else:
            # Invitation paths contain private tokens; never print HTTP access logs.
            logging.getLogger("werkzeug").setLevel(logging.ERROR)
            print(f"Party Mail fixture: http://127.0.0.1:{args.port}; owner password: test; invitation: /demo-party", flush=True)
            print("Data is temporary. Email, notifications and analytics are disabled.", flush=True)
            app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Minimal App Store Connect API client — only what the deploy needs:

* confirm the app record exists (the ASC API can't *create* apps — that's
  web-only — so a missing record is a fast, clear failure before a long build),
* find the latest uploaded build number, so the next upload gets a unique,
  monotonically increasing build.

Needs `pyjwt`, `cryptography`, `requests` (deploy/requirements.txt). This is only
imported on the `--auto-build` path; the upload itself goes through `altool`,
which does its own key auth, so the zero-dependency build+upload path never
touches this module.

CLI:
    python asc.py apps                 # list visible app records
    python asc.py latest-build         # latest build number for the configured app
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from urllib.parse import parse_qs, urlparse


# Load this app's configuration by path; both platforms contain _config.py.
# This avoids cross-platform imports in one pytest process or watcher interpreter.
import importlib.util
_spec = importlib.util.spec_from_file_location("_partymail_ios_config", Path(__file__).with_name("_config.py"))
assert _spec and _spec.loader
cfg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cfg)

API = "https://api.appstoreconnect.apple.com/v1"


def _token() -> str:
    import jwt
    key = cfg.asc_key_path().read_text()
    now = int(time.time())
    return jwt.encode(
        {"iss": cfg.ASC_ISSUER_ID, "iat": now, "exp": now + 600, "aud": "appstoreconnect-v1"},
        key,
        algorithm="ES256",
        headers={"kid": cfg.ASC_KEY_ID, "typ": "JWT"},
    )


def _get(path: str, **params) -> dict:
    import requests
    resp = requests.get(
        f"{API}{path}", params=params,
        headers={"Authorization": f"Bearer {_token()}"}, timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _post(path: str, body: dict) -> None:
    import requests
    resp = requests.post(
        f"{API}{path}", json=body,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()  # the relationship endpoints return 204 No Content


def list_apps() -> list[dict]:
    return _get("/apps", **{"limit": 200}).get("data", [])


def app_id(bundle_id: str | None = None) -> str | None:
    bundle_id = bundle_id or cfg.BUNDLE_ID
    for app in list_apps():
        if app["attributes"].get("bundleId") == bundle_id:
            return app["id"]
    return None


def latest_build(bundle_id: str | None = None) -> int:
    """Highest build number already uploaded for the app, or 0 if none / unknown."""
    aid = app_id(bundle_id)
    if not aid:
        return 0
    data = _get("/builds", **{"filter[app]": aid, "limit": 1, "sort": "-version"}).get("data", [])
    if not data:
        return 0
    try:
        return int(data[0]["attributes"].get("version") or 0)
    except (TypeError, ValueError):
        return 0


# --- TestFlight distribution ----------------------------------------------
#
# A new upload reaches internal testers only once the build is added to an
# internal beta group whose `hasAccessToAllBuilds` is false (which is how this
# app's "Internal" group is configured). altool uploads the binary but never
# touches groups, so without this the build processes to VALID and then just
# sits there, invisible on testers' devices. These helpers let the deploy attach
# the build right after upload.

def internal_group_ids(app_id_: str) -> list[str]:
    """Internal beta groups for the app (testers in these get builds with no
    beta review). External groups are intentionally excluded."""
    data = _get("/betaGroups", **{
        "filter[app]": app_id_, "limit": 200,
        "fields[betaGroups]": "name,isInternalGroup",
    }).get("data", [])
    return [g["id"] for g in data if g["attributes"].get("isInternalGroup")]


def find_build_id(app_id_: str, version: int | str) -> str | None:
    """The build record's id for a given build number, or None if it hasn't
    been ingested yet (the record can lag a minute or two behind the upload)."""
    data = _get("/builds", **{
        "filter[app]": app_id_, "filter[version]": str(version), "limit": 1,
    }).get("data", [])
    return data[0]["id"] if data else None


def wait_for_build(app_id_: str, version: int | str,
                   timeout: float = 360.0, interval: float = 15.0) -> str | None:
    """Poll until the build record appears (ingest lags the altool upload), or
    None on timeout. A build can be added to a group while still PROCESSING."""
    deadline = time.time() + timeout
    while True:
        bid = find_build_id(app_id_, version)
        if bid or time.time() >= deadline:
            return bid
        time.sleep(interval)


# --- Platform-flavoured helpers, for the auto-ship watcher --------------------
#
# server-ops ios-autoship gates and verifies through these names, which come from
# CityTransit's copy of this client (it ships iOS *and* Mac Catalyst, so its build
# namespace is per platform). PartyMail is iOS only, so these wrap the helpers above
# rather than reimplementing them.

def latest_build_for_platform(platform: str, bundle_id: str | None = None,
                              aid: str | None = None) -> int:
    """Latest build number on `platform`.

    Anything but iOS raises rather than returning 0: a 0 reads as "that number is
    free", which is the answer that lets a caller ship a number already taken."""
    if platform.upper() != "IOS":
        raise ValueError(f"PartyMail ships iOS only; no build namespace for {platform!r}")
    return latest_build(bundle_id)


def find_build_for_platform(app_id_: str, version: int | str, platform: str,
                            train: str | None = None) -> tuple[str | None, dict]:
    """(build_id, attributes) for a build number, or (None, {}) when App Store
    Connect has not ingested it yet. `train` is accepted for interface parity;
    this app's find_build_id does not filter by marketing version."""
    if platform.upper() != "IOS":
        return None, {}
    bid = find_build_id(app_id_, version)
    return (bid, {}) if bid else (None, {})


def group_build_ids(group_id: str) -> set[str]:
    """Every build id attached to `group_id`, following pagination.

    Apple caps this relationship at 200 per page; reading only the first page
    would report a freshly attached build as absent once the group holds more,
    so a caller verifying an attach would retry against a build already there."""
    ids: set[str] = set()
    path: str | None = f"/betaGroups/{group_id}/relationships/builds"
    params: dict = {"limit": 200}
    while path:
        page = _get(path, **params)
        ids.update(row["id"] for row in page.get("data", []))
        nxt = (page.get("links") or {}).get("next")
        if not nxt:
            break
        # `next` is absolute and carries the cursor; strip the base so _get's own
        # prefixing doesn't double it.
        parsed = urlparse(nxt)
        path = parsed.path.replace("/v1", "", 1)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    return ids


def build_in_group(group_id: str, build_id: str) -> bool:
    """Whether `build_id` is attached to `group_id` — so an attach can be
    *verified* rather than assumed, and a resume-attach can no-op."""
    return build_id in group_build_ids(group_id)


def attach_build_to_group(group_id: str, build_id: str) -> None:
    """Add the build to a beta group so its testers receive it (idempotent —
    re-adding an already-attached build is a no-op 204)."""
    _post(f"/betaGroups/{group_id}/relationships/builds",
          {"data": [{"type": "builds", "id": build_id}]})


def attach_to_internal(version: int | str, bundle_id: str | None = None) -> bool:
    """Wait for the just-uploaded build to register, then attach it to every
    internal beta group so it reaches testers. Our "Internal" group has
    hasAccessToAllBuilds=off, so a build is invisible until attached — altool
    doesn't do this. Prints progress; returns True on success. Best-effort: the
    caller treats a False as "finish it by hand", never as a fatal deploy error.
    """
    try:
        aid = app_id(bundle_id)
        groups = internal_group_ids(aid) if aid else []
        if not groups:
            print("⚠ no internal beta group found — add the build to a group in"
                  " App Store Connect ▸ TestFlight to send it to testers.")
            return False
        print(f"· waiting for build {version} to register in App Store Connect…")
        bid = wait_for_build(aid, version)
        if not bid:
            print(f"⚠ build {version} hasn't registered yet — once it does, add it"
                  " to the Internal group in App Store Connect ▸ TestFlight.")
            return False
        for gid in groups:
            attach_build_to_group(gid, bid)
            if not build_in_group(gid, bid):
                print(f"⚠ build {version} was not confirmed in group {gid}; retry attach after processing.")
                return False
        print(f"✓ attached build {version} to {len(groups)} internal"
              f" group{'s' if len(groups) != 1 else ''} — available to testers.")
        return True
    except Exception as e:  # noqa: BLE001 — caller must not let this mask a good upload
        print(f"⚠ auto-attach failed ({e}); add build {version} to the Internal"
              " group manually in App Store Connect ▸ TestFlight.")
        return False


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="App Store Connect query helper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("apps", help="list visible app records")
    lb = sub.add_parser("latest-build", help="latest uploaded build number")
    lb.add_argument("--bundle", default=cfg.BUNDLE_ID)
    at = sub.add_parser("attach", help="attach a build to the internal beta group(s)")
    at.add_argument("--build", required=True, help="build number to attach")
    at.add_argument("--bundle", default=cfg.BUNDLE_ID)
    args = parser.parse_args(argv)

    if args.cmd == "apps":
        for app in list_apps():
            at = app["attributes"]
            print(f"{at.get('bundleId'):32} {at.get('name'):28} id={app['id']}")
    elif args.cmd == "latest-build":
        print(latest_build(args.bundle))
    elif args.cmd == "attach":
        return 0 if attach_to_internal(args.build, args.bundle) else 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))

#!/usr/bin/env python3
"""Build the Android app and ship it to Play internal testing, headless.

The Android analogue of ios/deploy/testflight.py. It builds a signed release
**App Bundle** (.aab) with a fresh versionCode, then uploads it to the Play
**internal testing** track via the Google Play Developer API v3 (service-account
auth) and rolls the release out — so David's Pixel updates over the air, no cable.

Typical use (ships the committed appVersionCode from android/gradle.properties):

    python deploy/play.py

Options:

    (no flag)           versionCode = the committed appVersionCode
    --next              versionCode = max(committed, highest on Play + 1)
    --auto-build        legacy time-based code; refuses if not above the committed one
    --version-code N    force the versionCode (must exceed every prior upload)
    --set-version X.Y   also set the user-facing versionName
    --track NAME        Play track (default: internal)
    --skip-upload       build the .aab only (leaves it for inspection)
    --validate          run the edit through :validate instead of :commit (dry run)
    --aab PATH          override the built-bundle path

Signing: the release build reads the UPLOAD keystore from PARTYMAIL_UPLOAD_* (sourced
from ~/keys/partymail-upload.env by _config.py) — the same key the sideload build uses.
Play App Signing then RE-SIGNS the delivered APK with Google's key, so the app the
Pixel installs carries the *Play app-signing* cert, NOT the upload cert. Its
fingerprint must be in static/.well-known/assetlinks.json + the server's
ANDROID_APP_ORIGINS or passkeys break on the OTA build (see deploy/README.md).

Needs the deploy venv (pyjwt/cryptography/requests) for the upload; --skip-upload
builds on Gradle alone. No google-api-python-client — plain REST, matching the
project's AndroidX/stdlib-only posture.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import shutil
import sys
from pathlib import Path

# Load this app's configuration by path; both platforms contain _config.py.
# This avoids cross-platform imports in one pytest process or watcher interpreter.
import importlib.util
_spec = importlib.util.spec_from_file_location("_partymail_android_config", Path(__file__).with_name("_config.py"))
assert _spec and _spec.loader
cfg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cfg)

ANDROIDPUBLISHER = "https://androidpublisher.googleapis.com"
# The COMMITTED appVersionCode in android/gradle.properties is authoritative: a
# bare run ships exactly the number on the branch, which is what makes "merging a
# bump IS the ship" true and lets the autoship watcher trigger on it.
#
# --auto-build is the legacy path: SECONDS since this instant, monotonic without
# an API round-trip. Every upload before 2026-09-21 used it, so Play's codes are
# ~8.5e7 and the committed counter had to start above them (86000000). That
# inverts the old caveat -- a time-based code is now BELOW the committed one, so
# --auto-build would silently go backwards. It refuses instead; see auto_code().
VERSION_EPOCH = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
GRADLE_PROPERTIES = cfg.ANDROID_DIR / "gradle.properties"
# Play's documented ceiling, and its floor: a versionCode must be a positive
# int32 no greater than this.
PLAY_MAX_VERSION_CODE = 2_100_000_000
# Digits only, on purpose. It must accept EXACTLY what build.gradle.kts accepts,
# or the two readers of gradle.properties disagree and one of them silently
# reinterprets the number that reaches the Play Store. Python's int() would take
# "3000000000" (Kotlin's toIntOrNull overflows Int and refuses), "1_000" (Kotlin
# has no underscore parsing), "+5" and "-5"; none of those are valid here.
_VERSION_CODE_RE = re.compile(r"[0-9]+")
# Kotlin's String.trim() uses Char.isWhitespace(), i.e. Java's, which
# DELIBERATELY excludes the non-breaking spaces (U+00A0, U+2007, U+202F).
# Python's str.strip() removes them. So a pasted NBSP made play.py read
# 86000000 while a bare `./gradlew` build of the same tree refused it --
# measured 2026-09-21. Stripping an explicit ASCII set instead keeps the two
# agreeing on every input anyone will actually type; anything more exotic is
# left for the digits regex to reject, which is the stricter, fail-safe side.
_PROP_WHITESPACE = " \t\r\n\f\v"


def die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"\n✗ {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], cwd: str | None = None) -> None:
    print("· " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


# --- versionCode -----------------------------------------------------------

def auto_version_code() -> int:
    return int((dt.datetime.now(dt.timezone.utc) - VERSION_EPOCH).total_seconds())


class UnparseableVersionCode(ValueError):
    """appVersionCode is present in gradle.properties but is not an integer."""


def committed_version_code() -> int | None:
    """appVersionCode from android/gradle.properties; None if the key is absent.

    Deliberately mirrors Java .properties semantics, because Gradle is the other
    reader of this file and the two must not disagree:

      * '#' starts a comment only at the START of a line. Everything after '='
        is kept verbatim, so `appVersionCode=123 # note` really is the string
        "123 # note" -- NOT 123. That raises rather than returning None, so the
        error can say so; returning None would report "no appVersionCode" about
        a line that is plainly right there.
      * A repeated key is LAST-wins, so the scan does not stop at the first hit.
    """
    try:
        text = GRADLE_PROPERTIES.read_text(encoding="utf-8")
    except OSError:
        return None
    found: str | None = None
    for line in text.splitlines():
        # ASCII-only here too: a bare .strip() would eat a trailing NBSP off the
        # LINE before the value was ever read, re-introducing the divergence the
        # value-level strip is guarding against.
        line = line.strip(_PROP_WHITESPACE)
        if line.startswith(("#", "!")) or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.strip() == "appVersionCode":
            found = val.strip(_PROP_WHITESPACE)   # last wins, as Java does
    if found is None:
        return None
    if not _VERSION_CODE_RE.fullmatch(found):
        raise UnparseableVersionCode(found)
    value = int(found)
    if not 1 <= value <= PLAY_MAX_VERSION_CODE:
        raise UnparseableVersionCode(found)
    return value


def resolve_version_code(auto: bool) -> int:
    """Pick the versionCode to build, preferring the committed one.

    Refusing a backwards --auto-build is the point: Play would reject the upload
    anyway, but only after a full release build and an API round-trip, with an
    error about a used versionCode that says nothing about WHY. Better to fail
    here, naming both numbers.
    """
    try:
        committed = committed_version_code()
    except UnparseableVersionCode as e:
        die(f'appVersionCode in {GRADLE_PROPERTIES} is not usable: "{e.args[0]}".\n'
            f"It must be digits only, 1..{PLAY_MAX_VERSION_CODE} (Play's ceiling) — the same\n"
            f"form build.gradle.kts accepts, so the two cannot disagree.\n"
            f"Java .properties also keeps everything after '=' verbatim, including anything\n"
            f"that looks like a trailing # comment — put comments on their own line.")
    if not auto:
        if committed is None:
            die(f"no appVersionCode in {GRADLE_PROPERTIES} — commit one, or pass\n"
                f"  --version-code N / --auto-build explicitly.")
        return committed
    code = auto_version_code()
    if committed is not None and code <= committed:
        die(f"--auto-build would go BACKWARDS: its time-based code {code} is not above\n"
            f"the committed appVersionCode {committed}, and Play's codes are forever\n"
            f"monotonic. The committed number is authoritative now — drop --auto-build\n"
            f"to ship it, or bump it in {GRADLE_PROPERTIES}.")
    return code


# --- Build -----------------------------------------------------------------

def build_bundle(version_code: int, version_name: str | None) -> Path:
    validate_version(version_code, version_name)
    if not cfg.UPLOAD_KEYSTORE:
        die("PARTYMAIL_UPLOAD_KEYSTORE is not set — the release AAB would be unsigned and\n"
            "  Play rejects it. Source your upload key first:\n"
            "      source ~/keys/partymail-upload.env\n"
            "  (or set PLAY_SERVICE_ACCOUNT_JSON / PARTYMAIL_UPLOAD_* in deploy/.env).")
    if not Path(cfg.UPLOAD_KEYSTORE).expanduser().exists():
        die(f"upload keystore not found: {cfg.UPLOAD_KEYSTORE}")
    if not cfg.UPLOAD_PASSWORD:
        die("PARTYMAIL_UPLOAD_PASSWORD is not set; release signing requires the upload key password.")

    gradlew = cfg.ANDROID_DIR / "gradlew"
    args = [str(gradlew), "--no-daemon", "--console=plain",
            f"{cfg.GRADLE_MODULE}:bundleRelease",
            f"-PappVersionCode={version_code}"]
    if version_name:
        args.append(f"-PappVersionName={version_name}")
    print(f"▶ building release bundle — versionCode {version_code}"
          f"{f' versionName {version_name}' if version_name else ''}\n")
    run(args, cwd=str(cfg.ANDROID_DIR))

    aab = Path(cfg.AAB_PATH)
    if not aab.exists():
        die(f"bundle not produced at {aab} (build succeeded but the .aab is missing?)")
    print(f"✓ built {aab.name} ({aab.stat().st_size // 1024} KiB)")
    return aab


# --- Play Developer API ----------------------------------------------------

def _lazy_http():
    """Import the API deps only on the upload path so --skip-upload stays stdlib."""
    try:
        import jwt  # PyJWT
        import requests
    except ImportError:
        die("upload needs the deploy venv (pyjwt/cryptography/requests). Create it:\n"
            "      python3 -m venv android/deploy/.venv\n"
            "      android/deploy/.venv/bin/pip install -r android/deploy/requirements.txt\n"
            "  then re-run with android/deploy/.venv/bin/python, or use --skip-upload.")
    return jwt, requests


def access_token(jwt, requests) -> str:
    sa_path = cfg.service_account_path()
    if not sa_path.exists():
        die(f"Play service-account key not found: {sa_path}\n"
            "  Create one in the Google Cloud console for the project linked to Play,\n"
            "  grant it release access in Play Console ▸ Users and permissions, and\n"
            "  save the JSON there (or set PLAY_SERVICE_ACCOUNT_JSON). See deploy/README.md.")
    sa = json.loads(sa_path.read_text())
    if sa.get("type") != "service_account":
        die(f"{sa_path} is not a service-account key (type={sa.get('type')!r}). Download the\n"
            "  JSON *key* for the service account, not an OAuth client secret.")
    # Warn on an over-permissive key file (a Play deploy key is a credential).
    try:
        import stat
        mode = sa_path.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            print(f"⚠ {sa_path} is group/world-accessible — run `chmod 600 {sa_path}`.")
    except OSError:
        pass
    import time
    now = int(time.time())
    token_uri = sa.get("token_uri", "https://oauth2.googleapis.com/token")
    assertion = jwt.encode(
        {"iss": sa["client_email"],
         "scope": "https://www.googleapis.com/auth/androidpublisher",
         "aud": token_uri, "iat": now, "exp": now + 3600},
        sa["private_key"], algorithm="RS256")
    r = requests.post(token_uri, timeout=30, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion})
    if r.status_code != 200:
        die(f"OAuth token request failed ({r.status_code}): {r.text}")
    return r.json()["access_token"]


def highest_version_code() -> int:
    """The highest versionCode Play has EVER been given for this package.

    Read from edits.bundles.list, not from the tracks: Play's monotonicity is
    per package and counts every bundle ever uploaded, including one that was
    uploaded and never assigned to a track. This package has exactly such a
    case -- a draft on the `main` track (80119264, 2026-07-16) -- so numbering
    from the tracks alone could reuse a code Play has already consumed.

    Creates a transient edit and deletes it; that publishes nothing.
    """
    jwt, requests = _lazy_http()
    hdr = {"Authorization": f"Bearer {access_token(jwt, requests)}"}
    base = f"{ANDROIDPUBLISHER}/androidpublisher/v3/applications/{cfg.PACKAGE_NAME}"
    r = requests.post(f"{base}/edits", headers=hdr, timeout=30)
    if r.status_code >= 400:
        die(f"could not open a Play edit to read version codes "
            f"({r.status_code}): {r.text[:300]}")
    edit_id = r.json()["id"]
    try:
        b = requests.get(f"{base}/edits/{edit_id}/bundles", headers=hdr, timeout=30)
        if b.status_code >= 400:
            die(f"bundles.list failed ({b.status_code}): {b.text[:300]}")
        codes = [int(x["versionCode"]) for x in (b.json().get("bundles") or [])]
        return max(codes) if codes else 0
    finally:
        # Best effort: an abandoned edit expires on its own, and failing to
        # delete it must not fail a ship.
        try:
            requests.delete(f"{base}/edits/{edit_id}", headers=hdr, timeout=30)
        except Exception:
            pass


def next_version_code() -> int:
    """max(committed floor, highest-on-Play + 1).

    This is what TRIGGER=paths shipping uses: a merge is the ship, so nobody has
    to remember a bump, and the committed appVersionCode is a FLOOR you can raise
    deliberately rather than a number that must be maintained every time. Taking
    the max (not simply Play+1) is what lets a deliberate bump still win.
    """
    try:
        floor = committed_version_code() or 0
    except UnparseableVersionCode as e:
        die(f'appVersionCode in {GRADLE_PROPERTIES} is not usable: "{e.args[0]}".\n'
            f"It must be digits only, 1..{PLAY_MAX_VERSION_CODE}.")
    nxt = max(floor, highest_version_code() + 1)
    if nxt > PLAY_MAX_VERSION_CODE:
        die(f"next versionCode {nxt} exceeds Play's ceiling {PLAY_MAX_VERSION_CODE}.")
    return nxt


def upload(aab: Path, expected_version_code: int | None, track: str, validate: bool) -> None:
    jwt, requests = _lazy_http()
    token = access_token(jwt, requests)
    hdr = {"Authorization": f"Bearer {token}"}
    base = f"{ANDROIDPUBLISHER}/androidpublisher/v3/applications/{cfg.PACKAGE_NAME}"

    def check(r, what):
        if r.status_code // 100 != 2:
            die(f"{what} failed ({r.status_code}): {r.text}")
        return r

    # 1. Open an edit.
    edit = check(requests.post(f"{base}/edits", headers=hdr, timeout=30), "edits.insert").json()
    edit_id = edit["id"]
    print(f"· edit {edit_id}")

    # Discard the edit on ANY early exit — a failure OR a --validate dry run — so a
    # half-built edit never lingers on the app (Play keeps uncommitted edits ~7 days,
    # and a stale one blocks nothing but is noise). die() raises SystemExit, which
    # still runs this finally. Only a successful :commit consumes the edit, so we skip
    # the delete then.
    committed = False
    try:
        # 2. Upload the bundle (media upload endpoint).
        up = check(requests.post(
            f"{ANDROIDPUBLISHER}/upload/androidpublisher/v3/applications/"
            f"{cfg.PACKAGE_NAME}/edits/{edit_id}/bundles?uploadType=media",
            headers={**hdr, "Content-Type": "application/octet-stream"},
            data=aab.read_bytes(), timeout=600), "bundles.upload").json()
        vc = up["versionCode"]
        print(f"· uploaded bundle versionCode {vc}")
        # When WE built the bundle, a versionCode mismatch means the artifact we
        # uploaded isn't the one we built — FATAL, not a warning. (A prebuilt --aab
        # passes expected=None, so there's nothing to check against.)
        if expected_version_code is not None and vc != expected_version_code:
            die(f"Play recorded versionCode {vc}, expected {expected_version_code} — the built and\n"
                "  uploaded artifacts diverge. Refusing to ship.")

        # 3. Assign it to the track as a completed rollout. versionCodes are int64 sent
        #    as STRINGS per the API schema. NB: tracks.update REPLACES the track's whole
        #    release list — intended for a dedicated internal track; do NOT point --track
        #    at production/beta without adapting this.
        check(requests.put(
            f"{base}/edits/{edit_id}/tracks/{track}", headers=hdr, timeout=30,
            json={"track": track,
                  "releases": [{"versionCodes": [str(vc)], "status": "completed"}]}),
            f"tracks.update({track})")
        print(f"· assigned versionCode {vc} to the {track} track")

        # 4. Commit (or validate for a dry run). :validate does NOT auto-discard, so we
        #    delete the edit ourselves in the finally.
        verb = "validate" if validate else "commit"
        check(requests.post(f"{base}/edits/{edit_id}:{verb}", headers=hdr, timeout=60),
              f"edits.{verb}")
        committed = not validate
        if validate:
            print(f"✓ validated (dry run) — discarding edit {edit_id}, nothing published.")
        else:
            print(f"✓ committed — versionCode {vc} is live on the {track} track."
                  " The Pixel updates once Play finishes processing (~minutes).")
    finally:
        if not committed:
            try:
                requests.delete(f"{base}/edits/{edit_id}", headers=hdr, timeout=30)
            except Exception:
                pass   # best-effort cleanup; never mask the real error


# --- Main ------------------------------------------------------------------

def validate_version(code: int, name: str | None = None) -> None:
    if not 1 <= code <= PLAY_MAX_VERSION_CODE:
        die(f"versionCode must be 1..{PLAY_MAX_VERSION_CODE}")
    if name is not None and not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", name):
        die("versionName must contain one to three numeric components, for example 1.0")


def preflight(*, skip_upload: bool) -> None:
    """Check paths/toolchain and environment without reading credential contents."""
    cfg.validate_target()
    if not (cfg.ANDROID_DIR / "gradlew").is_file():
        die("Gradle wrapper is missing")
    if not shutil.which("java") and not os.environ.get("JAVA_HOME"):
        die("JDK is missing; use JDK 17 or 21 and set JAVA_HOME")
    if not (os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or (cfg.ANDROID_DIR / "local.properties").is_file()):
        die("Android SDK is missing; set ANDROID_HOME or android/local.properties")
    code = resolve_version_code(False)
    validate_version(code)
    if not cfg.UPLOAD_KEYSTORE or not Path(cfg.UPLOAD_KEYSTORE).is_file() or not cfg.UPLOAD_PASSWORD:
        die("Set PARTYMAIL_UPLOAD_KEYSTORE and PARTYMAIL_UPLOAD_PASSWORD for a signed release bundle")
    if not skip_upload and not cfg.service_account_path().is_file():
        die(f"Play service account key missing: {cfg.service_account_path()}")
    print(f"✓ local preflight: {cfg.PACKAGE_NAME}, versionCode {code}; no store request was made")

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--auto-build", action="store_true",
                     help="legacy time-based versionCode; refuses if not above the committed one")
    grp.add_argument("--version-code", type=int, help="force the versionCode")
    grp.add_argument("--next", action="store_true", dest="next_code",
                     help="versionCode = max(committed appVersionCode, highest on Play + 1); "
                          "what the autoship watcher uses")
    ap.add_argument("--set-version", help="also set the user-facing versionName, e.g. 0.2")
    ap.add_argument("--track", default=cfg.TRACK, help=f"Play track (default: {cfg.TRACK})")
    ap.add_argument("--skip-upload", action="store_true", help="build the .aab only")
    ap.add_argument("--preflight", action="store_true", help="check local prerequisites only; no build/upload")
    ap.add_argument("--validate", action="store_true",
                    help="run :validate instead of :commit (dry run; nothing is published)")
    ap.add_argument("--aab", default=None,
                    help="upload this PREBUILT .aab instead of building (skips the Gradle build)")
    args = ap.parse_args(argv)

    try:
        cfg.validate_target()
    except ValueError as exc:
        die(str(exc))
    if args.preflight:
        preflight(skip_upload=args.skip_upload)
        return 0
    if args.track != "internal":
        ap.error("Party Mail's deployment pipeline only replaces the internal testing track")

    print(f"▶ {cfg.PACKAGE_NAME} — Play {args.track} track\n")

    if args.aab:
        # Ship an existing bundle without building. We can't know its versionCode ahead
        # of the upload, so there's nothing to cross-check (expected=None).
        aab = Path(args.aab).expanduser()
        if not aab.exists():
            die(f"prebuilt bundle not found: {aab}")
        expected_vc: int | None = None
        print(f"· using prebuilt bundle {aab.name} (skipping build)")
        if args.skip_upload:
            print("\n(nothing to do: --aab is a prebuilt bundle and --skip-upload skips the upload)")
            return 0
    else:
        # A bare run ships the COMMITTED number; --auto-build keeps the legacy
        # time-based one but refuses to go backwards past it.
        if args.version_code is not None:
            expected_vc = args.version_code
        elif args.next_code:
            expected_vc = next_version_code()
            print(f"· next versionCode: {expected_vc}")
        else:
            expected_vc = resolve_version_code(args.auto_build)
        # Upload EXACTLY what we just built + validated (build_bundle returns that path),
        # never a stale --aab — the two must not diverge.
        aab = build_bundle(expected_vc, args.set_version)
        if args.skip_upload:
            print("\n✓ Built; skipping upload (--skip-upload).")
            return 0

    upload(aab, expected_vc, args.track, args.validate)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except subprocess.CalledProcessError as e:
        die(f"command failed (exit {e.returncode}): {' '.join(map(str, e.cmd))}")

#!/usr/bin/env python3
"""Build the iOS app and ship it to TestFlight, headless.

This automates the flow documented (the hard way) in deploy/README.md: archive
Release for device, package the IPA **manually** (a re-sign + zip — Xcode's
`-exportArchive` fails on this Mac, see the README gotcha), then upload via
`altool`. Defaults target Party Mail only. Local deploy/.env and TF_*/ASC_* settings
select signing credentials; unrelated app targets are refused.

Typical use (auto-pick the next build number from App Store Connect):

    python deploy/testflight.py --auto-build

Other options:

    --build N           force the build number (CURRENT_PROJECT_VERSION)
    --set-version X.Y   also set MARKETING_VERSION (the user-facing version)
    --skip-upload       archive + package only (leaves the .ipa for inspection)
    --unsigned-archive  archive without Xcode account signing; manually sign IPA
    --archive-path P    default /tmp/<App>.xcarchive
    --ipa P             default /tmp/<App>.ipa

`--auto-build` needs the deploy venv (pyjwt/cryptography/requests) to pick the
next number; `--build N` sets the number on stdlib alone. Either way the deploy
auto-attaches the build to the internal beta group at the end — and since that
step needs the API deps, the `--build N` path re-execs it via `.venv/bin/python`
(so it still happens, as long as the deploy venv exists).
"""
from __future__ import annotations

import argparse
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import os
import time
from datetime import datetime, timezone
from pathlib import Path

# Load this app's configuration by path; both platforms contain _config.py.
# This avoids cross-platform imports in one pytest process or watcher interpreter.
import importlib.util
_spec = importlib.util.spec_from_file_location("_partymail_ios_config", Path(__file__).with_name("_config.py"))
assert _spec and _spec.loader
cfg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cfg)

PBXPROJ = Path(cfg.PROJECT) / "project.pbxproj"

# Where Xcode drops managed provisioning profiles.
PROFILE_DIRS = [
    Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles",
    Path.home() / "Library/MobileDevice/Provisioning Profiles",
]


def die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"\n✗ {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], cwd: str | None = None) -> None:
    print("· " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def capture(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


# --- Version stamping ------------------------------------------------------

def read_build_number() -> int:
    values = set(re.findall(r"CURRENT_PROJECT_VERSION = (\d+);", PBXPROJ.read_text()))
    if len(values) != 1 or int(next(iter(values))) < 1:
        die("CURRENT_PROJECT_VERSION must be one consistent positive integer in every build configuration.")
    return int(next(iter(values)))


def set_build_number(n: int) -> None:
    if n < 1:
        die("build number must be a positive integer")
    text = PBXPROJ.read_text()
    new = re.sub(r"CURRENT_PROJECT_VERSION = \d+;", f"CURRENT_PROJECT_VERSION = {n};", text)
    if new == text and not re.search(r"CURRENT_PROJECT_VERSION = \d+;", text):
        die("project has no CURRENT_PROJECT_VERSION to update")
    PBXPROJ.write_text(new)
    print(f"· CURRENT_PROJECT_VERSION → {n}")


def set_marketing_version(v: str) -> None:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", v):
        die("marketing version must contain one to three numeric components, for example 1.0")
    text = PBXPROJ.read_text()
    new = re.sub(r"MARKETING_VERSION = [^;]+;", f"MARKETING_VERSION = {v};", text)
    PBXPROJ.write_text(new)
    print(f"· MARKETING_VERSION → {v}")


# --- Archive ---------------------------------------------------------------

def archive(archive_path: Path, *, unsigned: bool = False) -> None:
    if archive_path.exists():
        shutil.rmtree(archive_path)
    cmd = [
        "xcodebuild", "-project", cfg.PROJECT, "-scheme", cfg.SCHEME,
        "-configuration", "Release", "-sdk", "iphoneos",
        "-destination", "generic/platform=iOS",
        "-archivePath", str(archive_path),
    ]
    if unsigned:
        # The packaging step signs the app and extensions with their own App
        # Store profiles, so Xcode need not refresh development profiles.
        cmd += ["CODE_SIGNING_ALLOWED=NO", "archive"]
    else:
        cmd += [
            "archive",
            # The Admin API key lets xcodebuild refresh the App Store provisioning
            # profile non-interactively if it's missing/stale.
            "-allowProvisioningUpdates",
            "-authenticationKeyPath", str(cfg.asc_key_path()),
            "-authenticationKeyID", cfg.ASC_KEY_ID,
            "-authenticationKeyIssuerID", cfg.ASC_ISSUER_ID,
        ]
    run(cmd)


# --- Provisioning profile + manual IPA packaging ---------------------------

def _decode_profile(path: Path) -> dict | None:
    try:
        return plistlib.loads(capture(["security", "cms", "-D", "-i", str(path)]).encode("utf-8", "surrogateescape"))
    except Exception:
        return None


def find_store_profile(bundle_id: str | None = None) -> Path:
    """The App Store distribution profile for a bundle id: it grants
    `<TEAM>.<BUNDLE>` and has no `ProvisionedDevices` (development / ad-hoc
    profiles list devices; App Store ones don't). Newest unexpired profile wins.
    Each embedded extension is a separate app ID and needs its own profile."""
    want = f"{cfg.TEAM_ID}.{bundle_id or cfg.BUNDLE_ID}"
    matches: list[tuple[float, Path]] = []
    for d in PROFILE_DIRS:
        for p in d.glob("*.mobileprovision"):
            info = _decode_profile(p)
            if not info:
                continue
            ent = info.get("Entitlements", {})
            expiry = info.get("ExpirationDate")
            if (ent.get("application-identifier") == want
                    and "ProvisionedDevices" not in info
                    and not info.get("ProvisionsAllDevices")
                    and not ent.get("get-task-allow")
                    and (not expiry or (expiry.replace(tzinfo=timezone.utc)
                                        if expiry.tzinfo is None else expiry)
                         > datetime.now(timezone.utc))):
                created = info.get("CreationDate")
                matches.append((created.timestamp() if created else 0.0, p))
    if not matches:
        die(f"no App Store provisioning profile for {want} found in {[str(d) for d in PROFILE_DIRS]}.\n"
            "  Run an archive once with -allowProvisioningUpdates (this script does) to fetch it.")
    return max(matches, key=lambda t: t[0])[1]


# Entitlements whose value comes from the distribution profile, never from the
# bundle's own declaration (which may reflect a development signature).
MANAGED_ENTITLEMENTS = {"application-identifier", "com.apple.developer.team-identifier",
                        "aps-environment", "keychain-access-groups", "get-task-allow"}


def build_signing_entitlements(profile: Path, declared: dict | None = None,
                               output_dir: Path | None = None) -> Path:
    """Entitlements to re-sign one bundle: profile grants plus its own concrete
    capabilities. For the app, `declared` defaults to PartyMail.entitlements; for
    an extension it comes from the archived extension's signed entitlements.

    A provisioning profile carries *placeholder* entitlements — notably
    `com.apple.developer.associated-domains = "*"` (a wildcard) and
    `keychain-access-groups = <TEAM>.*`. Signing with the profile's values
    verbatim ships that `*` wildcard, which is honored for development but **not**
    for App Store / TestFlight distribution — so passkeys fail at runtime with
    "application … is not associated with domain …". Overlaying the app's real
    entitlements (`PartyMail.entitlements`) restores the concrete
    `webcredentials:partymail.app`, matching what the dev/archive build had.
    The dev-only `get-task-allow` is dropped (distribution must not ship it)."""
    info = _decode_profile(profile) or die(f"could not decode profile {profile}")
    ent = dict(info.get("Entitlements") or {})
    if not ent:
        die(f"profile {profile} has no Entitlements")

    if declared is None:
        app_path = Path(cfg.APP_ENTITLEMENTS)
        if not app_path.exists():
            die(f"app entitlements not found: {app_path} (set TF_APP_ENTITLEMENTS)")
        declared = plistlib.loads(app_path.read_bytes())

    # An App Group must be granted by this bundle's own distribution profile.
    # A profile for the containing app does not grant it to the extension.
    groups = declared.get("com.apple.security.application-groups") or []
    granted = ent.get("com.apple.security.application-groups") or []
    if not set(groups).issubset(granted):
        die(f"App Groups {groups!r} are not granted by App Store profile {profile}. "
            "Enable the capability for this bundle ID and refresh its profile.")

    # Every capability the bundle declares must be one this profile grants.
    # Signing with an entitlement the profile lacks produces an IPA that looks
    # fine here and is rejected at upload, so stop before the long build's
    # output is wasted. A profile regenerated before a capability was enabled
    # (they are invalidated by every capability change) is how this happens.
    ungranted = sorted(k for k in declared if k not in MANAGED_ENTITLEMENTS and k not in ent)
    if ungranted:
        die(f"entitlements {ungranted!r} are not granted by App Store profile {profile}. "
            "Enable the capability for this bundle ID and refresh its profile.")

    # The bundle's concrete capabilities win over the profile's placeholders.
    # Identity, APNs environment and keychain groups come from the distribution
    # profile, not an archive which may have been signed for development.
    ent.update({k: v for k, v in declared.items() if k not in MANAGED_ENTITLEMENTS})
    ent.pop("get-task-allow", None)

    fd, name = tempfile.mkstemp(suffix="-entitlements.plist", dir=output_dir)
    with os.fdopen(fd, "wb") as fh:
        fh.write(plistlib.dumps(ent))
    out = Path(name)
    return out


def _signed_entitlements(bundle: Path) -> dict:
    """Read a bundle's actual signature, including concrete extension groups.

    The archive may have been signed with a development profile; its signature
    is still the source of the extension's *declared* capabilities. Distribution
    identity and managed values are taken from the store profile when we re-sign.
    """
    proc = subprocess.run(["codesign", "-d", "--entitlements", "-", "--xml", str(bundle)],
                          capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        die(f"could not read signed entitlements from {bundle}: {proc.stderr}")
    try:
        return plistlib.loads(proc.stdout.encode("utf-8", "surrogateescape"))
    except (ValueError, TypeError) as e:
        die(f"invalid signed entitlements in {bundle}: {e}")


def _unsigned_extension_entitlements(bundle_id: str) -> dict:
    """Read an unsigned extension's concrete capabilities from its source plist.

    Refuse unknown extensions: signing with only a profile's wildcard values
    could silently drop a required App Group or other concrete entitlement.
    """
    configured = cfg.UNSIGNED_EXTENSION_ENTITLEMENTS.get(bundle_id)
    if not configured:
        die(f"no entitlements plist configured for unsigned extension {bundle_id}; "
            "set TF_UNSIGNED_EXTENSION_ENTITLEMENTS to bundleID=/path/to/file")
    path = Path(configured).expanduser()
    try:
        declared = plistlib.loads(path.read_bytes())
    except (OSError, ValueError, TypeError) as e:
        die(f"could not read entitlements for unsigned extension {bundle_id} "
            f"from {path}: {e}")
    if not isinstance(declared, dict):
        die(f"invalid entitlements plist for unsigned extension {bundle_id}: {path}")
    return declared


def _bundle_id(bundle: Path) -> str:
    try:
        value = plistlib.loads((bundle / "Info.plist").read_bytes())["CFBundleIdentifier"]
    except (OSError, ValueError, KeyError) as e:
        die(f"could not read bundle ID from {bundle}: {e}")
    if not isinstance(value, str) or not value:
        die(f"invalid bundle ID in {bundle}: {value!r}")
    return value


def verify_codesign(bundle: Path, bundle_id: str | None = None,
                    declared: dict | None = None, *, deep: bool = False) -> None:
    """Reject a bad distribution signature, identity, profile or capability."""
    bundle_id = bundle_id or cfg.BUNDLE_ID
    if declared is None:
        declared = plistlib.loads(Path(cfg.APP_ENTITLEMENTS).read_bytes())
    verify_cmd = ["codesign", "--verify", "--strict", "--verbose=2"]
    if deep:
        verify_cmd.append("--deep")
    checked = subprocess.run(verify_cmd + [str(bundle)], capture_output=True, text=True)
    if checked.returncode:
        die(f"codesign verification failed for {bundle}:\n{checked.stderr}")

    # `codesign -dvvv` writes to stderr. Check the authority line so an
    # incidental mention of Apple Distribution elsewhere cannot pass.
    details = subprocess.run(["codesign", "-dvvv", str(bundle)],
                             capture_output=True, text=True)
    if details.returncode or not re.search(r"^Authority=Apple Distribution:",
                                           details.stderr, re.MULTILINE):
        die(f"{bundle} is not signed by Apple Distribution:\n{details.stderr}")

    signed = _signed_entitlements(bundle)
    profile_path = bundle / "embedded.mobileprovision"
    profile = _decode_profile(profile_path)
    wanted_id = f"{cfg.TEAM_ID}.{bundle_id}"
    if (not profile or (profile.get("Entitlements") or {}).get("application-identifier")
            != wanted_id):
        die(f"{bundle} does not embed the App Store profile for {wanted_id}")
    if signed.get("application-identifier") != wanted_id:
        die(f"{bundle} has wrong signed application-identifier: "
            f"{signed.get('application-identifier')!r} (expected {wanted_id!r})")
    if signed.get("get-task-allow"):
        die(f"{bundle} has get-task-allow=true — refusing to upload")
    # Every capability the bundle declares must have survived the re-sign with
    # its concrete value, not the profile's placeholder and not dropped.
    for capability, want in sorted(declared.items()):
        if capability in MANAGED_ENTITLEMENTS:
            continue
        if signed.get(capability) != want:
            die(f"{bundle} has wrong signed {capability}: "
                f"{signed.get(capability)!r} (expected {want!r})")
    print(f"✓ codesign: {bundle_id}, Apple Distribution, correct profile and capabilities")


def package_ipa(archive_path: Path, ipa_path: Path, *, unsigned_archive: bool = False) -> None:
    app_src = archive_path / "Products" / "Applications" / f"{cfg.APP_NAME}.app"
    if not app_src.exists():
        die(f"app not found in archive: {app_src}")
    if _bundle_id(app_src) != cfg.BUNDLE_ID:
        die(f"archive app has bundle ID {_bundle_id(app_src)!r}; expected {cfg.BUNDLE_ID!r}")
    profile = find_store_profile(cfg.BUNDLE_ID)
    print(f"· store profile for {cfg.BUNDLE_ID}: {profile.name}")

    with tempfile.TemporaryDirectory(prefix="tf-ipa-") as tmp:
        work = Path(tmp)
        payload = work / "Payload"
        payload.mkdir()
        app_dst = payload / f"{cfg.APP_NAME}.app"
        shutil.copytree(app_src, app_dst, symlinks=True)

        # Every .appex is its own executable and app ID. Sign the leaves first;
        # changing an extension after signing the app invalidates the seal on
        # the containing app. A signed archive supplies each extension's exact
        # capabilities through its signature; an unsigned archive uses its
        # checked-in entitlements plist. The extension's *own* App Store profile
        # supplies the distribution identity and managed entitlements.
        extensions = sorted((app_dst / "PlugIns").glob("*.appex"))
        present_ids = {_bundle_id(extension) for extension in extensions}
        missing_ids = set(cfg.REQUIRED_EXTENSION_IDS) - present_ids
        if missing_ids:
            die(f"archive is missing required extension(s) {sorted(missing_ids)!r}; "
                "check scheme Embed App Extensions before uploading")
        for extension in extensions:
            extension_id = _bundle_id(extension)
            declared = (_unsigned_extension_entitlements(extension_id)
                        if unsigned_archive else _signed_entitlements(extension))
            extension_profile = find_store_profile(extension_id)
            print(f"· store profile for {extension_id}: {extension_profile.name}")
            shutil.copy(extension_profile, extension / "embedded.mobileprovision")
            extension_entitlements = build_signing_entitlements(
                extension_profile, declared, work)
            run(["codesign", "--force", "--timestamp", "--generate-entitlement-der",
                 "--sign", cfg.DIST_IDENTITY, "--entitlements",
                 str(extension_entitlements), str(extension)])
            verify_codesign(extension, extension_id, declared)

        shutil.copy(profile, app_dst / "embedded.mobileprovision")
        app_declared = plistlib.loads(Path(cfg.APP_ENTITLEMENTS).read_bytes())
        app_entitlements = build_signing_entitlements(profile, app_declared, work)
        run(["codesign", "--force", "--timestamp", "--generate-entitlement-der",
             "--sign", cfg.DIST_IDENTITY, "--entitlements", str(app_entitlements),
             str(app_dst)])
        verify_codesign(app_dst, cfg.BUNDLE_ID, app_declared, deep=True)

        ipa_path = ipa_path.resolve()
        if ipa_path.exists():
            ipa_path.unlink()
        run(["/usr/bin/zip", "-qry", str(ipa_path), "Payload"], cwd=str(work))
    print(f"✓ packaged {ipa_path} ({ipa_path.stat().st_size // 1024} KiB)")


def upload(ipa_path: Path) -> None:
    """Upload the IPA, and trust only altool's explicit success marker.

    altool's exit code is unreliable: it exits 0 even when App Store Connect
    rejects the binary — seen live on the per-app daily upload cap's 409 "Upload
    limit reached", where the build is silently dropped while the script prints
    success. bw-pod and CityTransit already guard this; it matters more here now,
    because the next step records provenance that the auto-ship watcher reads as
    proof the upload landed. A false record sends every retry into attach-only
    mode, so the release strands — or worse, an older build with that number gets
    attached and the new commit is marked shipped."""
    cmd = [
        "xcrun", "altool", "--upload-app", "-f", str(ipa_path), "-t", "ios",
        "--apiKey", cfg.ASC_KEY_ID, "--apiIssuer", cfg.ASC_ISSUER_ID,
    ]
    print("·", " ".join(cmd))
    # altool searches for AuthKey_<key ID>.p8 in its configured key directory.
    # Respect ASC_KEY_PATH without copying a private key into the build tree.
    upload_env = os.environ.copy()
    upload_env["API_PRIVATE_KEYS_DIR"] = str(cfg.asc_key_path().parent)
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, env=upload_env)
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.returncode != 0 or "UPLOAD SUCCEEDED" not in proc.stdout:
        die("altool did not report UPLOAD SUCCEEDED"
            f" (exit {proc.returncode}) — treating this upload as failed."
            " Apple rejects while exiting 0 (e.g. the daily upload cap's 409),"
            " and shipping on from here would record an upload that never"
            " happened.")


def _provenance_log() -> Path | None:
    """Where to record build -> commit. The auto-ship watcher reads a line here as
    proof the upload landed, and attaches on a retry instead of re-uploading — a
    re-upload supersedes a build still waiting to attach and strands it."""
    raw = os.environ.get("TF_PROVENANCE_LOG",
                         "~/.claude/locks/rsvp-site-build-provenance.tsv")
    try:
        path = Path(raw).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        return None


def shipped_head() -> str | None:
    """The commit this checkout is on, or None if it can't be read."""
    try:
        return capture(["git", "-C", str(PBXPROJ.parent.parent.parent), "rev-parse", "HEAD"]).strip() or None
    except Exception:  # noqa: BLE001 — provenance must never fail a good upload
        return None


def record_provenance(build_number: int, platform: str, train: str | None,
                      head: str | None) -> None:
    """Append "<ts> <platform> build <n> <train> <short> <full sha>".

    Best-effort for the deploy, load-bearing for the watcher, so it is written
    BEFORE the attach — the attach is the step that can fail or time out. Never a
    silent success: a missing line is what makes a retry re-upload."""
    sha = head or ""
    line = (f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')}\t{platform}\tbuild {build_number}\t"
            f"{train or ''}\t{sha[:8]}\t{sha}\n")
    path = _provenance_log()
    written = False
    if path is not None:
        try:
            with open(path, "a") as f:
                f.write(line)
            written = True
        except OSError as e:
            print(f"⚠ could not write the provenance ledger ({e})")
    if written and sha:
        print(f"· provenance: build {build_number} ({platform}) ← {sha[:8]}")
    else:
        print(f"⚠ build {build_number} ({platform}) uploaded but NOT recorded in the"
              f" provenance ledger{' (no commit sha)' if not sha else ''};"
              " a retry cannot tell the upload landed.")


def attach_to_internal_groups(build_number: int, train: str | None = None,
                              platform: str = "IOS") -> bool:
    """Add the just-uploaded build to the app's internal beta group(s) so it
    actually reaches testers.

    `train` and `platform` exist so the auto-ship watcher can call every app's
    deploy the same way (CityTransit ships two platforms). PartyMail is iOS only, so
    a different platform is a caller bug and says so rather than attaching the
    wrong build; without the parameters at all, an attach retry died with a
    TypeError and the build stayed invisible (bw-pod#1031). Our "Internal" group has hasAccessToAllBuilds=off,
    so a build is invisible until attached — altool doesn't do this.

    Runs by DEFAULT on every deploy (both `--auto-build` and `--build N`). The
    attach needs the API deps (requests/pyjwt), which live in the deploy venv —
    so when this script is invoked under a plain stdlib python (the `--build N`
    path), we re-exec the attach via `.venv/bin/python asc.py attach` rather than
    skipping it. Best-effort: the upload already succeeded, so a failure here
    never fails the deploy — but we RETURN whether the attach actually landed so
    the caller doesn't print a false "it's in TestFlight" message.
    """
    if platform.upper() != "IOS":
        raise ValueError("Party Mail ships iOS only")
    try:
        import jwt
        import requests
        import asc  # already importable when run under the venv (e.g. --auto-build)
    except ImportError:
        venv_py = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
        asc_py = Path(__file__).resolve().parent / "asc.py"
        if not venv_py.exists():
            print(f"⚠ skipping auto-attach (deploy venv not found at {venv_py};"
                  " create it from requirements.txt, or add the build to the"
                  " Internal group in App Store Connect ▸ TestFlight).")
            return False
        # asc.py's `attach` exits 0 on success, 1 on any failure.
        return subprocess.run([str(venv_py), str(asc_py), "attach",
                               "--build", str(build_number)], check=False).returncode == 0
    return asc.attach_to_internal(build_number)


# --- Main ------------------------------------------------------------------

def preflight(*, skip_upload: bool, archive_only: bool = False) -> None:
    """Inspect local prerequisites without reading signing keys or contacting stores."""
    cfg.validate_target()
    for name in ("xcodebuild", "xcrun"):
        if not shutil.which(name):
            die(f"{name} is missing; install Xcode and select its developer directory")
    if not PBXPROJ.is_file():
        die(f"Xcode project missing: {PBXPROJ}")
    read_build_number()
    if not Path(cfg.APP_ENTITLEMENTS).is_file():
        die(f"app entitlements missing: {cfg.APP_ENTITLEMENTS}")
    if not archive_only:
        find_store_profile()
    if not skip_upload and not cfg.asc_key_path().is_file():
        die(f"App Store Connect key missing: {cfg.asc_key_path()} (set ASC_KEY_PATH)")
    if not skip_upload:
        if cfg.asc_key_path().name != f"AuthKey_{cfg.ASC_KEY_ID}.p8":
            die("altool requires ASC_KEY_PATH to name AuthKey_<ASC_KEY_ID>.p8")
        probe = subprocess.run(["xcrun", "altool", "--help"], capture_output=True, text=True)
        if probe.returncode != 0 or "upload" not in (probe.stdout + probe.stderr).lower():
            die("Xcode's altool uploader could not run in this command environment. "
                "Try a normal Terminal or approved permissions outside the restricted command sandbox; "
                "if it still fails, check the selected Xcode or use Apple's Transporter app.")
    print(f"✓ local preflight: {cfg.BUNDLE_ID}, team {cfg.TEAM_ID}, build {read_build_number()}")
    print("  Store app record and tester groups are checked only during release; no API request was made.")

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--auto-build", action="store_true",
                     help="set the build number to (latest on App Store Connect)+1")
    grp.add_argument("--build", type=int, help="force the build number (CURRENT_PROJECT_VERSION)")
    ap.add_argument("--set-version", help="also set MARKETING_VERSION, e.g. 0.2")
    ap.add_argument("--skip-upload", action="store_true", help="archive + package only")
    ap.add_argument("--preflight", action="store_true", help="check local prerequisites only; no build/upload")
    ap.add_argument("--archive-only", action="store_true", help="with --skip-upload, produce an unsigned archive without an IPA/profile")
    ap.add_argument("--unsigned-archive", action="store_true",
                    help="archive without Xcode signing, then sign the IPA with installed App Store profiles")
    # Accepted so one auto-ship watcher drives every app the same way. PartyMail is
    # iOS only; the flag is explicitness, not a choice.
    ap.add_argument("--platform", choices=["ios"], default="ios",
                    help="which platform to ship (PartyMail is iOS only)")
    # The watcher archives the commit it gated on, which master may have moved
    # past. This script has no tree-freshness guard to waive — the watcher pins
    # the tree it builds — so the flag is accepted and recorded, not enforced.
    ap.add_argument("--allow-behind", action="store_true",
                    help="acknowledge shipping a commit master has moved past")
    ap.add_argument("--archive-path", default=f"/tmp/{cfg.APP_NAME}.xcarchive")
    ap.add_argument("--ipa", default=f"/tmp/{cfg.APP_NAME}.ipa")
    args = ap.parse_args(argv)

    try:
        cfg.validate_target()
    except ValueError as exc:
        die(str(exc))
    if args.archive_only and not args.skip_upload:
        ap.error("--archive-only requires --skip-upload")
    if args.preflight:
        preflight(skip_upload=args.skip_upload, archive_only=args.archive_only)
        return 0

    archive_path = Path(args.archive_path)
    ipa_path = Path(args.ipa)

    if args.set_version:
        set_marketing_version(args.set_version)

    if args.auto_build:
        import asc  # lazy: only this path needs the API deps
        nxt = asc.latest_build() + 1
        set_build_number(nxt)
    elif args.build is not None:
        set_build_number(args.build)
    else:
        print(f"· using existing build number {read_build_number()} "
              "(pass --auto-build or --build N to change it)")

    train = re.search(r"MARKETING_VERSION = ([^;]+);", PBXPROJ.read_text()).group(1).strip()
    # Captured BEFORE archiving: re-reading HEAD after the upload can name a
    # different commit (the checkout moved) or fail and record none.
    head = shipped_head()
    if args.allow_behind and head:
        print(f"· --allow-behind: shipping {head[:8]} deliberately, though the branch"
              " may have moved past it")

    print(f"\n▶ {cfg.SCHEME} {cfg.BUNDLE_ID} — build {read_build_number()}"
          f" (version {train})\n")

    archive(archive_path, unsigned=args.unsigned_archive or args.archive_only)
    if args.archive_only:
        print(f"\n✓ Unsigned device archive: {archive_path}. No signing, packaging or upload was attempted.")
        return 0
    package_ipa(archive_path, ipa_path, unsigned_archive=args.unsigned_archive)
    if args.skip_upload:
        print("\n✓ Built and packaged; skipping upload (--skip-upload).")
        return 0
    upload(ipa_path)
    print("\n✓ Uploaded to App Store Connect. TestFlight processing takes ~5–15 min.")
    build_no = read_build_number()
    record_provenance(build_no, "IOS", train, head)
    if attach_to_internal_groups(build_no, train):
        print("  Once processing finishes it appears for internal testers.")
    else:
        # Upload succeeded but the build is NOT attached — say so plainly (the whole
        # point of this step) and give the one-liner to finish it by hand.
        print("  ⚠ Upload succeeded, but auto-attach did NOT complete — the build will"
              " sit on App Store Connect unattached (invisible to testers). Finish it:\n"
              f"      ios/deploy/.venv/bin/python ios/deploy/asc.py attach --build {build_no}\n"
              "    (or add it to the Internal group in App Store Connect ▸ TestFlight).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except subprocess.CalledProcessError as e:
        die(f"command failed (exit {e.returncode}): {' '.join(e.cmd)}")

"""Offline tests for manual IPA packaging with an embedded WidgetKit extension."""
from __future__ import annotations

import plistlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import testflight  # noqa: E402


TEAM = "2FZS79QCFD"
APP_ID = "com.davidfwatson.partymail"
WIDGET_ID = APP_ID + ".AgenticWidget"
GROUP = "group.com.davidfwatson.partymail"


def profile_info(bundle_id: str, *, groups: bool = True) -> dict:
    # As a real App Store profile carries them: associated domains is a
    # wildcard placeholder that the bundle's concrete list replaces.
    ent = {"application-identifier": f"{TEAM}.{bundle_id}",
           "get-task-allow": False,
           "aps-environment": "production",
           "com.apple.developer.associated-domains": "*"}
    if groups:
        ent["com.apple.security.application-groups"] = [GROUP]
    return {"Entitlements": ent, "CreationDate": datetime(2026, 9, 1),
            "ExpirationDate": datetime(2027, 9, 1)}


def archive_fixture(tmp_path: Path, *, with_widget: bool = True):
    archive = tmp_path / "PartyMail.xcarchive"
    app = archive / "Products" / "Applications" / "PartyMail.app"
    app.mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": APP_ID}))
    widget = app / "PlugIns" / "AgenticWidgetExtension.appex"
    if with_widget:
        widget.mkdir(parents=True)
        (widget / "Info.plist").write_bytes(
            plistlib.dumps({"CFBundleIdentifier": WIDGET_ID}))
    return archive, app, widget


def test_packager_signs_widget_with_own_profile_before_app(tmp_path, monkeypatch):
    archive, _, _ = archive_fixture(tmp_path)
    app_profile = tmp_path / "app.mobileprovision"
    widget_profile = tmp_path / "widget.mobileprovision"
    app_profile.write_text("app profile")
    widget_profile.write_text("widget profile")
    profiles = {APP_ID: app_profile, WIDGET_ID: widget_profile}
    decoded = {app_profile: profile_info(APP_ID),
               widget_profile: profile_info(WIDGET_ID)}
    app_ent_path = tmp_path / "PartyMail.entitlements"
    app_ent = {"com.apple.developer.associated-domains":
               ["webcredentials:partymail.app"],
               "com.apple.security.application-groups": [GROUP]}
    app_ent_path.write_bytes(plistlib.dumps(app_ent))
    monkeypatch.setattr(testflight.cfg, "APP_ENTITLEMENTS", str(app_ent_path))
    monkeypatch.setattr(testflight.cfg, "APP_NAME", "PartyMail")
    monkeypatch.setattr(testflight.cfg, "BUNDLE_ID", APP_ID)
    monkeypatch.setattr(testflight.cfg, "TEAM_ID", TEAM)
    monkeypatch.setattr(testflight.cfg, "REQUIRED_EXTENSION_IDS", (WIDGET_ID,))
    monkeypatch.setattr(testflight, "find_store_profile", lambda bundle_id: profiles[bundle_id])
    monkeypatch.setattr(testflight, "_decode_profile", lambda path: decoded.get(path))

    archive_widget_ent = {
        "application-identifier": f"{TEAM}.{WIDGET_ID}",
        "get-task-allow": True,
        "aps-environment": "development",
        "com.apple.security.application-groups": [GROUP],
    }
    monkeypatch.setattr(testflight, "_signed_entitlements", lambda bundle: archive_widget_ent)

    signs = []
    verifies = []

    def fake_run(cmd, cwd=None):
        if cmd[0] == "codesign":
            bundle = Path(cmd[-1])
            ent = plistlib.loads(Path(cmd[cmd.index("--entitlements") + 1]).read_bytes())
            profile = (bundle / "embedded.mobileprovision").read_text()
            signs.append((bundle.suffix, ent, profile))
        elif cmd[0] == "/usr/bin/zip":
            Path(cmd[2]).write_bytes(b"offline IPA")
        else:
            pytest.fail(f"unexpected command: {cmd}")

    monkeypatch.setattr(testflight, "run", fake_run)
    monkeypatch.setattr(testflight, "verify_codesign",
                        lambda bundle, bundle_id, declared, **kw:
                        verifies.append((bundle.suffix, bundle_id, declared, kw)))

    ipa = tmp_path / "PartyMail.ipa"
    testflight.package_ipa(archive, ipa)

    assert [s[0] for s in signs] == [".appex", ".app"]
    assert signs[0][2] == "widget profile"
    assert signs[1][2] == "app profile"
    assert signs[0][1]["application-identifier"] == f"{TEAM}.{WIDGET_ID}"
    assert signs[0][1]["com.apple.security.application-groups"] == [GROUP]
    assert signs[0][1]["aps-environment"] == "production"
    assert "get-task-allow" not in signs[0][1]
    assert signs[1][1]["com.apple.developer.associated-domains"] == app_ent[
        "com.apple.developer.associated-domains"]
    assert [v[1] for v in verifies] == [WIDGET_ID, APP_ID]
    assert verifies[-1][3] == {"deep": True}
    assert ipa.read_bytes() == b"offline IPA"


def unsigned_packaging_fixture(tmp_path, monkeypatch, *, missing_group_for=None):
    archive, _, _ = archive_fixture(tmp_path)
    app_profile = tmp_path / "app.mobileprovision"
    widget_profile = tmp_path / "widget.mobileprovision"
    app_profile.write_text("app profile")
    widget_profile.write_text("widget profile")
    profiles = {APP_ID: app_profile, WIDGET_ID: widget_profile}
    decoded = {path: profile_info(bundle_id, groups=bundle_id != missing_group_for)
               for bundle_id, path in profiles.items()}
    app_ent_path = tmp_path / "PartyMail.entitlements"
    widget_ent_path = tmp_path / "AgenticWidgetExtension.entitlements"
    app_ent_path.write_bytes(plistlib.dumps({
        "com.apple.developer.associated-domains": ["webcredentials:partymail.app"],
        "com.apple.security.application-groups": [GROUP],
    }))
    widget_ent_path.write_bytes(plistlib.dumps({
        "com.apple.security.application-groups": [GROUP],
    }))
    monkeypatch.setattr(testflight.cfg, "APP_ENTITLEMENTS", str(app_ent_path))
    monkeypatch.setattr(testflight.cfg, "APP_NAME", "PartyMail")
    monkeypatch.setattr(testflight.cfg, "BUNDLE_ID", APP_ID)
    monkeypatch.setattr(testflight.cfg, "TEAM_ID", TEAM)
    monkeypatch.setattr(testflight.cfg, "REQUIRED_EXTENSION_IDS", (WIDGET_ID,))
    monkeypatch.setattr(testflight.cfg, "UNSIGNED_EXTENSION_ENTITLEMENTS",
                        {WIDGET_ID: str(widget_ent_path)})
    monkeypatch.setattr(testflight, "find_store_profile", lambda bundle_id: profiles[bundle_id])
    monkeypatch.setattr(testflight, "_decode_profile", lambda path: decoded.get(path))
    monkeypatch.setattr(testflight, "_signed_entitlements",
                        lambda bundle: pytest.fail("unsigned archive has no signature"))
    return archive


def test_unsigned_packager_uses_widget_plist_and_signs_both_bundles(tmp_path, monkeypatch):
    archive = unsigned_packaging_fixture(tmp_path, monkeypatch)
    signs = []
    verifies = []

    def fake_run(cmd, cwd=None):
        if cmd[0] == "codesign":
            bundle = Path(cmd[-1])
            ent = plistlib.loads(Path(cmd[cmd.index("--entitlements") + 1]).read_bytes())
            signs.append((bundle.suffix, ent))
        elif cmd[0] == "/usr/bin/zip":
            Path(cmd[2]).write_bytes(b"unsigned archive IPA")
        else:
            pytest.fail(f"unexpected command: {cmd}")

    monkeypatch.setattr(testflight, "run", fake_run)
    monkeypatch.setattr(testflight, "verify_codesign",
                        lambda bundle, bundle_id, declared, **kw:
                        verifies.append((bundle_id, declared, kw)))
    ipa = tmp_path / "PartyMail.ipa"
    testflight.package_ipa(archive, ipa, unsigned_archive=True)

    assert [bundle for bundle, _ in signs] == [".appex", ".app"]
    assert signs[0][1]["com.apple.security.application-groups"] == [GROUP]
    assert signs[1][1]["com.apple.security.application-groups"] == [GROUP]
    assert [bundle_id for bundle_id, _, _ in verifies] == [WIDGET_ID, APP_ID]
    assert verifies[0][1] == {"com.apple.security.application-groups": [GROUP]}
    assert verifies[1][2] == {"deep": True}
    assert ipa.read_bytes() == b"unsigned archive IPA"


@pytest.mark.parametrize("missing_group_for", [APP_ID, WIDGET_ID])
def test_unsigned_packager_rejects_profile_without_group(
        tmp_path, monkeypatch, missing_group_for):
    archive = unsigned_packaging_fixture(
        tmp_path, monkeypatch, missing_group_for=missing_group_for)
    monkeypatch.setattr(testflight, "run", lambda *a, **k: None)
    monkeypatch.setattr(testflight, "verify_codesign", lambda *a, **k: None)
    ipa = tmp_path / "PartyMail.ipa"
    with pytest.raises(SystemExit):
        testflight.package_ipa(archive, ipa, unsigned_archive=True)
    assert not ipa.exists()


def test_unsigned_packager_rejects_unknown_extension_entitlements(tmp_path, monkeypatch):
    archive = unsigned_packaging_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(testflight.cfg, "UNSIGNED_EXTENSION_ENTITLEMENTS", {})
    monkeypatch.setattr(testflight, "run", lambda *a, **k: pytest.fail("must not sign"))
    with pytest.raises(SystemExit):
        testflight.package_ipa(archive, tmp_path / "PartyMail.ipa", unsigned_archive=True)


def test_unsigned_archive_disables_xcode_signing_and_account_refresh(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(testflight, "run", lambda cmd, cwd=None: commands.append(cmd))
    testflight.archive(tmp_path / "PartyMail.xcarchive", unsigned=True)
    cmd = commands[0]
    assert "CODE_SIGNING_ALLOWED=NO" in cmd
    assert "-allowProvisioningUpdates" not in cmd
    assert "-authenticationKeyPath" not in cmd


def test_packager_rejects_widget_profile_without_its_app_group(tmp_path, monkeypatch):
    archive, _, _ = archive_fixture(tmp_path)
    app_profile = tmp_path / "app.mobileprovision"
    widget_profile = tmp_path / "widget.mobileprovision"
    app_profile.write_text("app")
    widget_profile.write_text("widget")
    app_ent_path = tmp_path / "PartyMail.entitlements"
    app_ent_path.write_bytes(plistlib.dumps({"com.apple.security.application-groups": [GROUP]}))
    monkeypatch.setattr(testflight.cfg, "APP_ENTITLEMENTS", str(app_ent_path))
    monkeypatch.setattr(testflight.cfg, "APP_NAME", "PartyMail")
    monkeypatch.setattr(testflight.cfg, "BUNDLE_ID", APP_ID)
    monkeypatch.setattr(testflight.cfg, "TEAM_ID", TEAM)
    monkeypatch.setattr(testflight.cfg, "REQUIRED_EXTENSION_IDS", (WIDGET_ID,))
    monkeypatch.setattr(testflight, "find_store_profile",
                        lambda bundle_id: {APP_ID: app_profile, WIDGET_ID: widget_profile}[bundle_id])
    monkeypatch.setattr(testflight, "_decode_profile", lambda path: {
        app_profile: profile_info(APP_ID), widget_profile: profile_info(WIDGET_ID, groups=False)
    }.get(path))
    monkeypatch.setattr(testflight, "_signed_entitlements",
                        lambda bundle: {"com.apple.security.application-groups": [GROUP]})
    monkeypatch.setattr(testflight, "run", lambda *a, **k: pytest.fail("must not sign"))
    with pytest.raises(SystemExit):
        testflight.package_ipa(archive, tmp_path / "PartyMail.ipa")


def test_packager_rejects_archive_missing_required_widget(tmp_path, monkeypatch):
    archive, _, _ = archive_fixture(tmp_path, with_widget=False)
    profile = tmp_path / "app.mobileprovision"
    profile.write_text("profile")
    monkeypatch.setattr(testflight.cfg, "APP_NAME", "PartyMail")
    monkeypatch.setattr(testflight.cfg, "BUNDLE_ID", APP_ID)
    monkeypatch.setattr(testflight.cfg, "REQUIRED_EXTENSION_IDS", (WIDGET_ID,))
    monkeypatch.setattr(testflight, "find_store_profile", lambda bundle_id: profile)
    monkeypatch.setattr(testflight, "run", lambda *a, **k: pytest.fail("must not sign"))
    with pytest.raises(SystemExit):
        testflight.package_ipa(archive, tmp_path / "PartyMail.ipa")


def test_find_store_profile_matches_each_bundle_and_skips_expired(tmp_path, monkeypatch):
    paths = [tmp_path / f"{name}.mobileprovision" for name in ("app", "old-widget", "widget")]
    for p in paths:
        p.write_text("profile")
    old = profile_info(WIDGET_ID)
    old["ExpirationDate"] = datetime.now(timezone.utc) - timedelta(days=1)
    infos = {paths[0]: profile_info(APP_ID), paths[1]: old,
             paths[2]: profile_info(WIDGET_ID)}
    monkeypatch.setattr(testflight, "PROFILE_DIRS", [tmp_path])
    monkeypatch.setattr(testflight, "_decode_profile", lambda p: infos[p])
    monkeypatch.setattr(testflight.cfg, "TEAM_ID", TEAM)
    assert testflight.find_store_profile(APP_ID) == paths[0]
    assert testflight.find_store_profile(WIDGET_ID) == paths[2]


def test_verify_codesign_checks_widget_signature_profile_and_group(tmp_path, monkeypatch):
    widget = tmp_path / "AgenticWidgetExtension.appex"
    widget.mkdir()
    (widget / "embedded.mobileprovision").write_text("profile")
    declared = {"com.apple.security.application-groups": [GROUP]}
    signed = {"application-identifier": f"{TEAM}.{WIDGET_ID}",
              "com.apple.security.application-groups": [GROUP]}
    calls = []

    def fake_subprocess(cmd, **kwargs):
        calls.append(cmd)
        if "-dvvv" in cmd:
            return SimpleNamespace(returncode=0, stdout="",
                                   stderr=f"Authority=Apple Distribution: David Watson ({TEAM})\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(testflight.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(testflight, "_signed_entitlements", lambda bundle: signed)
    monkeypatch.setattr(testflight, "_decode_profile", lambda path: profile_info(WIDGET_ID))
    monkeypatch.setattr(testflight.cfg, "TEAM_ID", TEAM)
    testflight.verify_codesign(widget, WIDGET_ID, declared)
    assert any("--verify" in call and "--strict" in call for call in calls)

    signed["com.apple.security.application-groups"] = ["group.wrong"]
    with pytest.raises(SystemExit):
        testflight.verify_codesign(widget, WIDGET_ID, declared)


TIME_SENSITIVE = "com.apple.developer.usernotifications.time-sensitive"


def test_signing_refuses_an_entitlement_the_profile_does_not_grant(tmp_path, monkeypatch):
    """A profile generated before a capability was enabled lacks it. Signing
    with it anyway yields an IPA that is only rejected at upload."""
    profile = tmp_path / "app.mobileprovision"
    profile.write_text("profile")
    info = profile_info(APP_ID)
    monkeypatch.setattr(testflight, "_decode_profile", lambda path: info)
    declared = {"com.apple.security.application-groups": [GROUP],
                "aps-environment": "development",
                TIME_SENSITIVE: True}

    with pytest.raises(SystemExit):
        testflight.build_signing_entitlements(profile, declared, tmp_path)

    info["Entitlements"][TIME_SENSITIVE] = True
    out = testflight.build_signing_entitlements(profile, declared, tmp_path)
    signed = plistlib.loads(out.read_bytes())
    assert signed[TIME_SENSITIVE] is True
    assert signed["aps-environment"] == "production"   # the profile's, not the bundle's


def test_verify_codesign_checks_every_declared_capability(tmp_path, monkeypatch):
    app = tmp_path / "PartyMail.app"
    app.mkdir()
    (app / "embedded.mobileprovision").write_text("profile")
    declared = {"com.apple.security.application-groups": [GROUP],
                "aps-environment": "development",
                TIME_SENSITIVE: True}
    signed = {"application-identifier": f"{TEAM}.{APP_ID}",
              "aps-environment": "production",
              "com.apple.security.application-groups": [GROUP],
              TIME_SENSITIVE: True}

    def fake_subprocess(cmd, **kwargs):
        stderr = (f"Authority=Apple Distribution: David Watson ({TEAM})\n"
                  if "-dvvv" in cmd else "")
        return SimpleNamespace(returncode=0, stdout="", stderr=stderr)

    monkeypatch.setattr(testflight.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(testflight, "_signed_entitlements", lambda bundle: signed)
    monkeypatch.setattr(testflight, "_decode_profile", lambda path: profile_info(APP_ID))
    monkeypatch.setattr(testflight.cfg, "TEAM_ID", TEAM)
    # aps-environment differs on purpose: it is the profile's to decide.
    testflight.verify_codesign(app, APP_ID, declared)

    del signed[TIME_SENSITIVE]
    with pytest.raises(SystemExit):
        testflight.verify_codesign(app, APP_ID, declared)

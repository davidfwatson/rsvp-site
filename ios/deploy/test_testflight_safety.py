"""Party Mail release safety and first-install paths; entirely offline."""
import importlib.util
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asc
import testflight


def test_party_mail_defaults_have_no_inherited_widget():
    assert testflight.cfg.BUNDLE_ID == "com.davidfwatson.partymail"
    assert testflight.cfg.APP_NAME == testflight.cfg.SCHEME == "PartyMail"
    assert testflight.cfg.REQUIRED_EXTENSION_IDS == ()
    assert testflight.cfg.UNSIGNED_EXTENSION_ENTITLEMENTS == {}


def test_unrelated_target_is_refused_before_archive(monkeypatch):
    monkeypatch.setattr(testflight.cfg, "BUNDLE_ID", "com.davidfwatson.utils")
    monkeypatch.setattr(testflight, "archive", lambda *a, **k: pytest.fail("unsafe target archived"))
    with pytest.raises(SystemExit):
        testflight.main(["--skip-upload"])


def test_archive_only_never_packages_or_uploads(tmp_path, monkeypatch):
    project = tmp_path / "project.pbxproj"
    project.write_text("CURRENT_PROJECT_VERSION = 1; MARKETING_VERSION = 1.0;")
    monkeypatch.setattr(testflight, "PBXPROJ", project)
    monkeypatch.setattr(testflight, "shipped_head", lambda: "a" * 40)
    calls = []
    monkeypatch.setattr(testflight, "archive", lambda path, **kw: calls.append(kw))
    monkeypatch.setattr(testflight, "package_ipa", lambda *a, **k: pytest.fail("archive-only packaged"))
    monkeypatch.setattr(testflight, "upload", lambda *a: pytest.fail("archive-only uploaded"))
    assert testflight.main(["--archive-only", "--skip-upload"]) == 0
    assert calls == [{"unsigned": True}]


def test_archive_only_requires_skip_upload():
    with pytest.raises(SystemExit):
        testflight.main(["--archive-only"])


@pytest.mark.parametrize("value", [0, -2])
def test_build_numbers_must_be_positive(value):
    with pytest.raises(SystemExit):
        testflight.set_build_number(value)


def test_inconsistent_build_numbers_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "project.pbxproj"
    path.write_text("CURRENT_PROJECT_VERSION = 1; CURRENT_PROJECT_VERSION = 2;")
    monkeypatch.setattr(testflight, "PBXPROJ", path)
    with pytest.raises(SystemExit):
        testflight.read_build_number()


def test_invalid_marketing_version_is_not_written():
    with pytest.raises(SystemExit):
        testflight.set_marketing_version("1.0; injected-setting")


def test_attach_verifies_group_membership(monkeypatch):
    monkeypatch.setattr(asc, "app_id", lambda *a: "app")
    monkeypatch.setattr(asc, "internal_group_ids", lambda *a: ["internal"])
    monkeypatch.setattr(asc, "wait_for_build", lambda *a: "build")
    monkeypatch.setattr(asc, "attach_build_to_group", lambda *a: None)
    monkeypatch.setattr(asc, "build_in_group", lambda *a: False)
    assert asc.attach_to_internal(1) is False
    monkeypatch.setattr(asc, "build_in_group", lambda *a: True)
    assert asc.attach_to_internal(1) is True


def test_preflight_archive_only_needs_no_profile_or_key(tmp_path, monkeypatch):
    project = tmp_path / "project.pbxproj"
    project.write_text("CURRENT_PROJECT_VERSION = 1;")
    entitlements = tmp_path / "PartyMail.entitlements"
    entitlements.write_text("fixture")
    monkeypatch.setattr(testflight, "PBXPROJ", project)
    monkeypatch.setattr(testflight.cfg, "APP_ENTITLEMENTS", str(entitlements))
    monkeypatch.setattr(testflight.shutil, "which", lambda *a: "/usr/bin/xcodebuild")
    monkeypatch.setattr(testflight, "find_store_profile", lambda *a: pytest.fail("profile requested"))
    monkeypatch.setattr(testflight.cfg, "asc_key_path", lambda: pytest.fail("key requested"))
    testflight.preflight(skip_upload=True, archive_only=True)


def test_stdlib_attach_uses_venv_when_api_dependency_missing(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, "jwt", None)
    monkeypatch.setattr(Path, "exists", lambda *a: True)
    commands = []
    monkeypatch.setattr(testflight.subprocess, "run", lambda command, **kw: commands.append(command) or SimpleNamespace(returncode=0))
    assert testflight.attach_to_internal_groups(42) is True
    assert commands[0][0].endswith("ios/deploy/.venv/bin/python")
    assert commands[0][-3:] == ["attach", "--build", "42"]

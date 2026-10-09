"""Party Mail package boundaries, signing checks and version validation."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import play


def test_party_mail_package_default():
    assert play.cfg.PACKAGE_NAME == "com.davidfwatson.partymail"


def test_unrelated_package_is_refused_before_build(monkeypatch):
    monkeypatch.setattr(play.cfg, "PACKAGE_NAME", "com.davidfwatson.utils")
    monkeypatch.setattr(play, "build_bundle", lambda *a: pytest.fail("unsafe package built"))
    with pytest.raises(SystemExit):
        play.main(["--skip-upload"])


def test_other_track_is_refused_before_build(monkeypatch):
    monkeypatch.setattr(play, "build_bundle", lambda *a: pytest.fail("unexpected build"))
    with pytest.raises(SystemExit):
        play.main(["--track", "production"])


@pytest.mark.parametrize("value", [0, -1, 2_100_000_001])
def test_explicit_version_codes_are_bounded(value):
    with pytest.raises(SystemExit):
        play.validate_version(value)


def test_invalid_version_name_is_refused():
    with pytest.raises(SystemExit):
        play.validate_version(1, "1.0\nother-property")


def test_missing_upload_password_stops_before_gradle(tmp_path, monkeypatch):
    keystore = tmp_path / "upload.keystore"
    keystore.touch()
    monkeypatch.setattr(play.cfg, "UPLOAD_KEYSTORE", str(keystore))
    monkeypatch.setattr(play.cfg, "UPLOAD_PASSWORD", None)
    monkeypatch.setattr(play, "run", lambda *a, **k: pytest.fail("unsigned build attempted"))
    with pytest.raises(SystemExit):
        play.build_bundle(1, None)


def test_skip_upload_does_not_contact_play(tmp_path, monkeypatch):
    aab = tmp_path / "app-release.aab"
    aab.touch()
    monkeypatch.setattr(play, "resolve_version_code", lambda *a: 1)
    monkeypatch.setattr(play, "build_bundle", lambda *a: aab)
    monkeypatch.setattr(play, "upload", lambda *a: pytest.fail("skip-upload contacted Play"))
    assert play.main(["--skip-upload"]) == 0

"""Tests for the seams the auto-ship watcher drives (server-ops ios-autoship).

Merging a PR that bumps the committed CURRENT_PROJECT_VERSION is what ships this
app now; a LaunchAgent does the archive/upload/attach. Three things it needs from
here, each pinned below because getting one wrong ships or strands a build:

* `record_provenance` writes the line the watcher reads as PROOF THE UPLOAD
  LANDED. After it exists, a retry attaches instead of re-uploading — and a
  re-upload supersedes a build still waiting to attach, stranding it. So it is
  written after the upload and before the attach, carries the commit that was
  archived, and never reports success it did not achieve.
* `attach_to_internal_groups` takes the `train`/`platform` the watcher passes.
  Without them an attach retry died with a TypeError and the build stayed
  invisible to testers (bw-pod#1031).
* the platform-flavoured `asc` helpers the watcher gates and verifies through.

Offline, stdlib + pytest only (nothing archives, uploads or talks to Apple):
    python3 -m pytest ios/deploy/test_testflight_autoship.py
"""
import inspect
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import asc  # noqa: E402
import testflight  # noqa: E402


def test_provenance_line_carries_platform_build_and_commit(tmp_path, monkeypatch, capsys):
    log = tmp_path / "prov.tsv"
    monkeypatch.setenv("TF_PROVENANCE_LOG", str(log))
    sha = "a" * 40
    testflight.record_provenance(110, "IOS", "0.1", sha)
    fields = log.read_text().rstrip("\n").split("\t")
    assert fields[1] == "IOS"
    assert fields[2] == "build 110"
    assert fields[3] == "0.1"
    assert fields[5] == sha, "the full commit is what makes the line ours"
    assert "provenance" in capsys.readouterr().out


def test_an_unwritable_log_is_survivable_but_never_silent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TF_PROVENANCE_LOG", str(tmp_path / "nope" / "x.tsv"))
    monkeypatch.setattr(pathlib.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    testflight.record_provenance(1, "IOS", None, "c" * 40)   # must not raise
    out = capsys.readouterr().out
    assert "NOT recorded" in out and "⚠" in out


def test_a_missing_commit_is_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TF_PROVENANCE_LOG", str(tmp_path / "prov.tsv"))
    testflight.record_provenance(7, "IOS", "0.1", None)
    assert "NOT recorded" in capsys.readouterr().out


def test_the_upload_records_provenance_before_attaching():
    """Order is the point: the attach is the step that fails or times out."""
    src = pathlib.Path(testflight.__file__).read_text()
    upload_at = src.index("\n    upload(ipa_path)")
    prov_at = src.index("record_provenance(build_no", upload_at)
    attach_at = src.index("attach_to_internal_groups(build_no", upload_at)
    assert upload_at < prov_at < attach_at


def test_provenance_records_the_commit_that_was_archived():
    src = pathlib.Path(testflight.__file__).read_text()
    call = src[src.index("record_provenance(build_no"):][:120]
    assert "shipped_head()" not in call, "must use the head captured before archiving"


def test_attach_accepts_the_train_and_platform_the_watcher_passes():
    sig = inspect.signature(testflight.attach_to_internal_groups)
    assert "train" in sig.parameters and "platform" in sig.parameters


def test_upload_requires_altools_success_marker(monkeypatch, tmp_path):
    """altool exits 0 even when Apple rejects the binary (the daily upload cap's
    409). Provenance is written straight after this, and the watcher reads that
    line as proof the upload landed — so a false success strands the release."""
    import subprocess as sp

    class Result:
        def __init__(self, rc, out):
            self.returncode, self.stdout = rc, out

    rejected = ("2026-09-17 ... UPLOAD FAILED\n"
                "Error: Upload limit reached for app ... (409)\n")
    monkeypatch.setattr(sp, "run", lambda *a, **k: Result(0, rejected))
    with pytest.raises(SystemExit):
        testflight.upload(tmp_path / "x.ipa")

    monkeypatch.setattr(sp, "run", lambda *a, **k: Result(0, "UPLOAD SUCCEEDED with no errors\n"))
    testflight.upload(tmp_path / "x.ipa")   # must not raise


def test_latest_build_for_platform_refuses_a_namespace_it_cannot_see(monkeypatch):
    """0 would read as 'that number is free' — the answer that ships a taken one."""
    monkeypatch.setattr(asc, "latest_build", lambda bundle_id=None: 109)
    assert asc.latest_build_for_platform("IOS") == 109
    with pytest.raises(ValueError):
        asc.latest_build_for_platform("MAC_OS")


def test_find_build_for_platform_returns_a_pair(monkeypatch):
    monkeypatch.setattr(asc, "find_build_id", lambda a, v: "bid-1")
    assert asc.find_build_for_platform("app", 110, "IOS")[0] == "bid-1"
    monkeypatch.setattr(asc, "find_build_id", lambda a, v: None)
    assert asc.find_build_for_platform("app", 110, "IOS") == (None, {})
    assert asc.find_build_for_platform("app", 110, "MAC_OS") == (None, {})


def test_group_build_ids_follows_pagination(monkeypatch):
    """Apple caps the relationship at 200 per page; one page would report a
    freshly attached build as absent once the group passes 200."""
    pages = {
        "/betaGroups/g/relationships/builds": {
            "data": [{"id": f"b{i}"} for i in range(200)],
            "links": {"next": "https://api.appstoreconnect.apple.com/v1/betaGroups/g/"
                              "relationships/builds?cursor=NEXT&limit=200"},
        },
        "/betaGroups/g/relationships/builds?cursor=NEXT": {"data": [{"id": "b200"}]},
    }

    def fake_get(path, **params):
        return pages[path + ("?cursor=NEXT" if params.get("cursor") == "NEXT" else "")]

    monkeypatch.setattr(asc, "_get", fake_get)
    ids = asc.group_build_ids("g")
    assert "b200" in ids and len(ids) == 201
    assert asc.build_in_group("g", "b200")

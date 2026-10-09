"""Unit tests for the Play deploy script's non-Gradle logic.

Run: `python3 -m unittest` from android/deploy (or `python3 test_play.py`). Covers
the API upload sequence, versionCode scheme, and the fatal-mismatch / edit-discard
behavior — the parts a wrong edit could ship the wrong bundle from. The Gradle build
+ the real network are not exercised (they're the untestable I/O seam).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import play  # noqa: E402
cfg = play.cfg


class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeRequests:
    """Records every call and returns canned responses for the edit flow."""
    def __init__(self, upload_vc=555, fail_on=None):
        self.calls = []          # list of (method, url, json_body)
        self.upload_vc = upload_vc
        self.fail_on = fail_on    # substring → return a 500 for that URL

    def _resp(self, url, payload):
        if self.fail_on and self.fail_on in url:
            return FakeResp(500, {}, "boom")
        return FakeResp(200, payload)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw.get("json")))
        if url.endswith("/edits"):
            return self._resp(url, {"id": "edit1"})
        if "uploadType=media" in url:
            return self._resp(url, {"versionCode": self.upload_vc})
        return self._resp(url, {})   # :commit / :validate

    def put(self, url, **kw):
        self.calls.append(("PUT", url, kw.get("json")))
        return self._resp(url, {})

    def delete(self, url, **kw):
        self.calls.append(("DELETE", url, None))
        return FakeResp(200, {})


def _tmp_aab():
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".aab")
    f.write(b"PK\x03\x04bundle"); f.close()
    return Path(f.name)


class VersionCodeTest(unittest.TestCase):
    def test_monotonic_positive_and_bounded(self):
        a = play.auto_version_code()
        b = play.auto_version_code()
        self.assertGreaterEqual(b, a)                 # never regresses
        self.assertGreater(a, 63_000_000)             # seconds since 2024 → well past 2026
        self.assertLess(a, 2_100_000_000)             # under Play's ceiling


class CommittedVersionCodeTest(unittest.TestCase):
    """The committed appVersionCode is the ship trigger, so its parse and the
    backwards-guard are worth pinning: a wrong answer here either ships the wrong
    build or blocks every ship."""

    def _props(self, body: str):
        d = tempfile.mkdtemp()
        f = Path(d) / "gradle.properties"
        f.write_text(body, encoding="utf-8")
        return f

    def _with(self, body: str):
        return unittest.mock.patch.object(play, "GRADLE_PROPERTIES", self._props(body))

    def test_reads_the_committed_value(self):
        with self._with("org.gradle.jvmargs=-Xmx3g\nappVersionCode=86000000\n"):
            self.assertEqual(play.committed_version_code(), 86000000)

    def test_ignores_comments_and_whitespace(self):
        body = "# appVersionCode=1\n\n  appVersionCode = 86000123  \n"
        with self._with(body):
            self.assertEqual(play.committed_version_code(), 86000123)

    def test_absent_key_is_none(self):
        with self._with("appVersionName=0.2\n"):
            self.assertIsNone(play.committed_version_code())

    def test_present_but_unparseable_raises_not_none(self):
        # None would make the error say "no appVersionCode" about a line that is
        # plainly there. The value is carried so the message can quote it.
        with self._with("appVersionCode=not-a-number\n"):
            with self.assertRaises(play.UnparseableVersionCode) as cm:
                play.committed_version_code()
            self.assertEqual(cm.exception.args[0], "not-a-number")

    def test_inline_comment_is_not_stripped(self):
        # The measured Gradle bug this guards: Java .properties keeps everything
        # after '=' verbatim, so this is the string "86000000 # seed", and the old
        # `?.toIntOrNull() ?: 1` in build.gradle.kts silently shipped versionCode 1.
        with self._with("appVersionCode=86000000 # seed\n"):
            with self.assertRaises(play.UnparseableVersionCode):
                play.committed_version_code()

    def test_bang_comment_lines_are_ignored(self):
        with self._with("! appVersionCode=1\nappVersionCode=86000000\n"):
            self.assertEqual(play.committed_version_code(), 86000000)

    def test_duplicate_key_is_last_wins_like_java(self):
        with self._with("appVersionCode=1\nappVersionCode=86000000\n"):
            self.assertEqual(play.committed_version_code(), 86000000)

    def test_rejects_every_form_build_gradle_also_rejects(self):
        """The two readers of gradle.properties must agree exactly.

        Each of these was VERIFIED rejected by a real Gradle probe. Python's
        int() would otherwise take 3000000000 (Kotlin overflows Int), 1_000
        (Kotlin has no underscore parsing), and +5/-5; a value one reader
        silently reinterprets is how a wrong versionCode reaches Play.
        """
        for bad in ["3000000000", "-5", "0", "1_000", "+5", "2100000001",
                    "", "   ", "86000000 # seed", "8.6e7", "0x52", "86000000abc"]:
            with self.subTest(bad=bad), self._with(f"appVersionCode={bad}\n"):
                with self.assertRaises(play.UnparseableVersionCode):
                    play.committed_version_code()

    def test_non_breaking_space_is_rejected_like_gradle_does(self):
        """Kotlin's trim() is Java's isWhitespace(), which excludes NBSP; Python's
        strip() does not. Measured: a pasted NBSP made play.py read 86000000 while
        Gradle refused the same file. Both must reject it."""
        for nbsp in ["86000000\u00a0", "\u00a086000000", "86000000\u202f"]:
            with self.subTest(raw=nbsp), self._with(f"appVersionCode={nbsp}\n"):
                with self.assertRaises(play.UnparseableVersionCode):
                    play.committed_version_code()

    def test_ordinary_whitespace_is_still_stripped(self):
        for raw in ["86000000 ", " 86000000", "86000000\t", "86000000\r"]:
            with self.subTest(raw=raw), self._with(f"appVersionCode={raw}\n"):
                self.assertEqual(play.committed_version_code(), 86000000)

    def test_accepts_the_boundaries(self):
        for good, want in [("1", 1), ("86000000", 86000000),
                           ("2100000000", 2100000000), ("86000000\t", 86000000)]:
            with self.subTest(good=good), self._with(f"appVersionCode={good}\n"):
                self.assertEqual(play.committed_version_code(), want)

    def test_resolve_surfaces_the_unparseable_value(self):
        with self._with("appVersionCode=86000000 # seed\n"):
            with self.assertRaises(SystemExit):
                play.resolve_version_code(False)
            with self.assertRaises(SystemExit):
                play.resolve_version_code(True)

    def test_missing_file_is_none_not_a_crash(self):
        with unittest.mock.patch.object(play, "GRADLE_PROPERTIES",
                                        Path("/nonexistent/gradle.properties")):
            self.assertIsNone(play.committed_version_code())

    def test_bare_run_uses_the_committed_code(self):
        with self._with("appVersionCode=86000000\n"):
            self.assertEqual(play.resolve_version_code(False), 86000000)

    def test_bare_run_without_a_committed_code_refuses(self):
        with self._with("appVersionName=0.2\n"):
            with self.assertRaises(SystemExit):
                play.resolve_version_code(False)

    def test_auto_build_refuses_to_go_backwards(self):
        # The real case: every pre-2026-09-21 upload was time-based (~8.5e7), so
        # the committed counter starts above them and --auto-build now trails it.
        with self._with("appVersionCode=2100000000\n"):
            with self.assertRaises(SystemExit):
                play.resolve_version_code(True)

    def test_auto_build_allowed_when_it_is_still_ahead(self):
        with self._with("appVersionCode=1\n"):
            self.assertEqual(play.resolve_version_code(True), play.auto_version_code())

    def test_auto_build_with_no_committed_code_is_unconstrained(self):
        with self._with("appVersionName=0.2\n"):
            self.assertEqual(play.resolve_version_code(True), play.auto_version_code())


class NextVersionCodeTest(unittest.TestCase):
    """TRIGGER=paths numbering: max(committed floor, highest on Play + 1).

    Taking the max, not simply Play+1, is what lets a deliberate bump still win;
    using the floor alone is what would re-upload a consumed code.
    """

    def _props(self, body: str):
        d = tempfile.mkdtemp()
        f = Path(d) / "gradle.properties"
        f.write_text(body, encoding="utf-8")
        return f

    def _run(self, committed: str, highest: int) -> int:
        with unittest.mock.patch.object(play, "GRADLE_PROPERTIES",
                                        self._props(f"appVersionCode={committed}\n")), \
             unittest.mock.patch.object(play, "highest_version_code",
                                        lambda: highest):
            return play.next_version_code()

    def test_floor_wins_when_it_is_ahead(self):
        # The real first-ship case: floor 86000000 vs Play's 85863573.
        self.assertEqual(self._run("86000000", 85863573), 86000000)

    def test_play_plus_one_wins_once_the_floor_is_passed(self):
        # Every merge after the first, with nobody touching the floor.
        self.assertEqual(self._run("86000000", 86000000), 86000001)
        self.assertEqual(self._run("86000000", 86000123), 86000124)

    def test_a_deliberate_bump_above_play_is_honoured(self):
        self.assertEqual(self._run("86500000", 86000123), 86500000)

    def test_equal_floor_and_next_does_not_reuse_a_code(self):
        # floor == highest must NOT ship the floor: that code is consumed.
        self.assertEqual(self._run("86000001", 86000001), 86000002)

    def test_empty_play_uses_the_floor(self):
        self.assertEqual(self._run("86000000", 0), 86000000)

    def test_refuses_past_plays_ceiling(self):
        with self.assertRaises(SystemExit):
            self._run("2100000000", 2100000000)

    def test_unparseable_floor_is_fatal_not_silently_zero(self):
        with self.assertRaises(SystemExit):
            self._run("86000000 # seed", 85863573)


class AccessTokenTest(unittest.TestCase):
    def _sa_file(self, sa_type="service_account"):
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
        json.dump({"type": sa_type, "client_email": "svc@proj.iam", "private_key": "KEY",
                   "token_uri": "https://oauth2.googleapis.com/token"}, f)
        f.close()
        os.environ["PLAY_SERVICE_ACCOUNT_JSON"] = f.name
        return f.name

    def tearDown(self):
        os.environ.pop("PLAY_SERVICE_ACCOUNT_JSON", None)

    def test_builds_correct_jwt_claims(self):
        self._sa_file()
        captured = {}

        class FakeJwt:
            @staticmethod
            def encode(payload, key, algorithm):
                captured.update(payload=payload, key=key, alg=algorithm)
                return "ASSERTION"

        class FakeReq:
            @staticmethod
            def post(url, timeout=None, data=None):
                captured["token_url"] = url
                captured["grant"] = data["grant_type"]
                captured["assertion"] = data["assertion"]
                return FakeResp(200, {"access_token": "AT"})

        tok = play.access_token(FakeJwt, FakeReq)
        self.assertEqual(tok, "AT")
        self.assertEqual(captured["alg"], "RS256")
        self.assertEqual(captured["payload"]["iss"], "svc@proj.iam")
        self.assertEqual(captured["payload"]["scope"],
                         "https://www.googleapis.com/auth/androidpublisher")
        self.assertEqual(captured["payload"]["aud"], "https://oauth2.googleapis.com/token")
        self.assertLess(captured["payload"]["iat"], captured["payload"]["exp"])
        self.assertEqual(captured["grant"], "urn:ietf:params:oauth:grant-type:jwt-bearer")

    def test_rejects_non_service_account_key(self):
        self._sa_file(sa_type="authorized_user")
        with self.assertRaises(SystemExit):
            play.access_token(object(), object())


class UploadFlowTest(unittest.TestCase):
    def setUp(self):
        self._orig_lazy = play._lazy_http
        self._orig_token = play.access_token
        play.access_token = lambda j, r: "tok"

    def tearDown(self):
        play._lazy_http = self._orig_lazy
        play.access_token = self._orig_token

    def _run(self, fr, expected_vc, validate=False):
        play._lazy_http = lambda: (None, fr)
        aab = _tmp_aab()
        play.upload(aab, expected_vc, "internal", validate)

    def test_commit_sequence_and_string_versioncodes(self):
        fr = FakeRequests(upload_vc=555)
        self._run(fr, 555, validate=False)
        methods = [c[0] for c in fr.calls]
        # insert → upload → track PUT → commit; a committed edit is NOT deleted.
        self.assertEqual(methods, ["POST", "POST", "PUT", "POST"])
        self.assertTrue(fr.calls[3][1].endswith(":commit"))
        put = next(c for c in fr.calls if c[0] == "PUT")
        self.assertEqual(put[2]["releases"][0]["versionCodes"], ["555"])   # strings per schema
        self.assertEqual(put[2]["releases"][0]["status"], "completed")

    def test_validate_discards_the_edit(self):
        fr = FakeRequests(upload_vc=555)
        self._run(fr, 555, validate=True)
        methods = [c[0] for c in fr.calls]
        self.assertTrue(fr.calls[3][1].endswith(":validate"))
        self.assertEqual(methods[-1], "DELETE")           # dry run cleans up its edit

    def test_versioncode_mismatch_is_fatal_and_discards(self):
        fr = FakeRequests(upload_vc=999)   # Play recorded something else than we built
        with self.assertRaises(SystemExit):
            self._run(fr, 555, validate=False)            # expected 555 ≠ 999 → die
        self.assertIn("DELETE", [c[0] for c in fr.calls])  # finally still discards the edit

    def test_prebuilt_expected_none_skips_mismatch_check(self):
        fr = FakeRequests(upload_vc=42)
        self._run(fr, None, validate=False)               # None → no cross-check, commits fine
        self.assertTrue(fr.calls[-1][1].endswith(":commit"))


if __name__ == "__main__":
    unittest.main()

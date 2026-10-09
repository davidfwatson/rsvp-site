#!/usr/bin/env bash
# Local checks. No store API calls, credentials or release uploads.
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$task_root"
task_python="${PARTYMAIL_PYTHON:-$task_root/venv/bin/python}"
if [[ ! -x "$task_python" ]]; then
  task_python="python3"
fi
"$task_python" -m pytest -q ios/deploy/test_testflight_autoship.py ios/deploy/test_testflight_packaging.py ios/deploy/test_testflight_safety.py android/deploy/test_play.py android/deploy/test_play_safety.py
"$task_python" scripts/mobile_fixture.py --smoke
if [[ "${1:-}" == "--all" || "${1:-}" == "--ios" ]]; then
  fixture_port="${PARTYMAIL_FIXTURE_PORT:-5059}"
  fixture_log="${TMPDIR:-/tmp}/PartyMail-verify-fixture-$$.log"
  "$task_python" -u scripts/mobile_fixture.py --port "$fixture_port" > "$fixture_log" 2>&1 &
  fixture_pid=$!
  cleanup_fixture() {
    task_status=$?
    if [[ "$task_status" != 0 ]]; then
      echo "Isolated fixture startup/runtime log: $fixture_log"
      tail -100 "$fixture_log" || true
    fi
    kill "$fixture_pid" 2>/dev/null || true
    wait "$fixture_pid" 2>/dev/null || true
  }
  trap cleanup_fixture EXIT
  export PARTYMAIL_TEST_BASE_URL="http://127.0.0.1:$fixture_port"
  export TEST_RUNNER_PARTYMAIL_TEST_BASE_URL="$PARTYMAIL_TEST_BASE_URL"
  "$task_python" scripts/wait_mobile_fixture.py --base-url "$PARTYMAIL_TEST_BASE_URL" --pid "$fixture_pid"
  xcodebuild -project ios/PartyMail.xcodeproj -scheme PartyMail -sdk iphonesimulator \
    -destination "${PARTYMAIL_IOS_DESTINATION:-platform=iOS Simulator,name=iPhone 17}" \
    -derivedDataPath /tmp/PartyMail-verify CODE_SIGNING_ALLOWED=NO test
fi
if [[ "${1:-}" == "--all" || "${1:-}" == "--android" ]]; then
  (cd android && ./gradlew --no-daemon --console=plain :app:testDebugUnitTest :app:lintDebug :app:assembleDebug)
fi

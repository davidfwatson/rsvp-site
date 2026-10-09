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
  xcodebuild -project ios/PartyMail.xcodeproj -scheme PartyMail -sdk iphonesimulator \
    -destination "${PARTYMAIL_IOS_DESTINATION:-platform=iOS Simulator,name=iPhone 17}" \
    -derivedDataPath /tmp/PartyMail-verify CODE_SIGNING_ALLOWED=NO test
fi
if [[ "${1:-}" == "--all" || "${1:-}" == "--android" ]]; then
  (cd android && ./gradlew --no-daemon --console=plain :app:testDebugUnitTest :app:lintDebug :app:assembleDebug)
fi

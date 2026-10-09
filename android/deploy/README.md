# Party Mail Play internal testing

The pipeline is adapted from `../personal-site/android/deploy`: signed release
AAB, monotonic `appVersionCode`, service-account REST upload, internal-track
assignment, edit validation/commit and cleanup on failure. It only targets
`com.davidfwatson.partymail` and the internal testing track. Party Mail uses
`PARTYMAIL_UPLOAD_*`, with no automatic loading of the Likes upload key.

See [the complete mobile release guide](../../docs/mobile-release.md) for first
setup, store metadata, app links, fixtures, CI and optional merge watchers.

```bash
# No signing credentials or Play account required:
cd android
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
cd ..

# Configure a dedicated upload key first; no upload:
PARTYMAIL_UPLOAD_ENV="$HOME/keys/partymail-upload.env" python3 android/deploy/play.py --preflight --skip-upload
PARTYMAIL_UPLOAD_ENV="$HOME/keys/partymail-upload.env" python3 android/deploy/play.py --skip-upload

# After creating Party Mail in Play and granting service-account access:
python3 -m venv android/deploy/.venv
android/deploy/.venv/bin/pip install -r android/deploy/requirements.txt
PARTYMAIL_UPLOAD_ENV="$HOME/keys/partymail-upload.env" android/deploy/.venv/bin/python android/deploy/play.py --next
```

Copy `.env.example` to the local `.env`. `PARTYMAIL_UPLOAD_KEYSTORE` is expanded
before Gradle receives it. `PARTYMAIL_UPLOAD_PASSWORD` is used for both store
and key passwords; `PARTYMAIL_UPLOAD_ALIAS` defaults to `upload`. The
`PARTYMAIL_UPLOAD_ENV` file is loaded only when explicitly selected. A service
account key may be reused with a Party Mail-specific grant; its default path is
`~/keys/play-service-account.json`, or set `PLAY_SERVICE_ACCOUNT_JSON`.

A bare release uses the committed `android/gradle.properties` `appVersionCode`.
`--next` selects `max(committed, highest uploaded + 1)` and passes it to Gradle.
`--version-code N` explicitly overrides it; `--set-version 1.0` overrides
`appVersionName`. These Gradle overrides do not edit `gradle.properties`.
`--validate` still uploads a bundle to a temporary Play edit; it validates and
discards that edit. For entirely offline build validation use `--skip-upload`.
`--aab PATH` uploads a prebuilt AAB. All upload error paths discard uncommitted
edits and a built/uploaded version mismatch stops the release.

Play App Signing re-signs the app delivered to testers. Set the **Play app
signing certificate** SHA-256 on the backend to support OTA app links/passkeys;
the dedicated upload certificate alone covers sideloaded release APKs.

```bash
venv/bin/python -m pytest -q android/deploy/test_play.py android/deploy/test_play_safety.py
```

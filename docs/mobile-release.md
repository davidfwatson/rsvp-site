# Party Mail iOS and Android release

Party Mail has native SwiftUI and Jetpack Compose apps backed by the same events,
guest responses and administrator accounts as `https://partymail.app`. Both use
`com.davidfwatson.partymail`; neither deployment tool can target DFW Utils.
The pipelines follow `../personal-site/ios/deploy` and `android/deploy`, including
manual verified IPA signing and Play internal-track edit handling. Store account
creation, first signing setup and tester enrollment are the morning handoff.
No mobile upload or autoship watcher is installed by preparing the source.

## Morning setup

1. Ensure the backend release containing `mobile_api.py` is live. Fetch
   `https://partymail.app/api/mobile/session` and confirm HTTP 200 with
   `csrf_token`, `admin`, `public_url`, `email_enabled` and `email_connected`.
2. In Apple Developer, register explicit bundle ID
   `com.davidfwatson.partymail` for team `2FZS79QCFD`; enable Associated Domains.
   In App Store Connect create **Party Mail**, iOS, this bundle ID, SKU
   `partymail-ios`. Create an internal TestFlight group and add yourself.
   Install an Apple Distribution identity/private key and an unexpired App Store
   distribution profile for this bundle. Xcode's account provisioning can fetch
   the profile; a profile must grant the app's associated-domains capability.
3. Keep the existing App Store Connect Admin API key outside the repository.
   Defaults are key ID `572KA8836R`, issuer
   `69a6de71-90ce-47e3-e053-5b8c7c11a4d1`, key path
   `~/private_keys/AuthKey_572KA8836R.p8`. Set `ASC_KEY_PATH` if it lives elsewhere.
   Create `ios/deploy/.venv`, install its requirements, then release:

   ```bash
   ios/deploy/.venv/bin/python ios/deploy/testflight.py --preflight
   ios/deploy/.venv/bin/python ios/deploy/testflight.py --auto-build
   ```

   The selected Xcode uploader is ready: `xcrun altool --help` and its version
   check passed in an ordinary shell on October 9, reporting **27.0.5 (2.1)**.
   Run upload/preflight from a normal Terminal outside the restricted command
   sandbox. Apple's Transporter app is an optional alternative: use
   `--skip-upload`, upload the signed IPA there, then run
   `ios/deploy/.venv/bin/python ios/deploy/asc.py attach --build N`. No store
   account request or upload was made during these uploader checks.

4. In Play Console create **Party Mail**, app, free, package
   `com.davidfwatson.partymail`, and enroll it in Play App Signing. A dedicated
   Party Mail upload key has already been prepared at
   `~/keys/partymail-upload.keystore`, with protected signing settings at
   `~/keys/partymail-upload.env`. The local `android/deploy/.env` explicitly
   selects that env file. Securely back up **both** files; losing the key/env
   prevents signing future uploads without a Play upload-key reset. Never commit
   either file. The checked-in public upload certificate fingerprint is
   `android/deploy/upload-certificate.sha256`:

   ```text
   EA:3E:38:ED:38:37:39:DB:33:80:28:A5:91:94:15:98:9B:A0:F7:1A:24:70:2E:25:42:70:2C:AB:DE:8E:B2:36
   ```

   For a future rebuild where that existing key is deliberately unavailable,
   this interactive command creates a key and prompts for its password. Do not
   run it over the prepared key:

   ```bash
   mkdir -p ~/keys
   keytool -genkeypair -keystore ~/keys/partymail-upload.keystore -alias upload -keyalg RSA -keysize 2048 -validity 10000
   ```

   The prepared env file stores `PARTYMAIL_UPLOAD_KEYSTORE`, `PARTYMAIL_UPLOAD_PASSWORD` and
   `PARTYMAIL_UPLOAD_ALIAS=upload` in `~/keys/partymail-upload.env`; use `chmod 600`
   on key/env files. `PARTYMAIL_UPLOAD_ENV` selects that path, or put the values
   in gitignored `android/deploy/.env`. `PARTYMAIL_UPLOAD_PASSWORD` must match
   both the keystore and key password.
5. Enable the Google Play Android Developer API for the Google Cloud project,
   grant the deployment service account access to **Party Mail** and internal
   testing releases in Play Console. Put its JSON key outside the repo at
   `~/keys/play-service-account.json`, or set `PLAY_SERVICE_ACCOUNT_JSON`.
   Create `android/deploy/.venv` and install its requirements. Build the first AAB:

   ```bash
   PARTYMAIL_UPLOAD_ENV="$HOME/keys/partymail-upload.env" python3 android/deploy/play.py --preflight --skip-upload
   PARTYMAIL_UPLOAD_ENV="$HOME/keys/partymail-upload.env" python3 android/deploy/play.py --version-code 1 --skip-upload
   ```

   Upload that AAB manually to the first internal test release if Play has not
   accepted this package before. Configure the internal testers list, finish the
   release and open the opt-in link on the device. Subsequent releases:

   ```bash
   PARTYMAIL_UPLOAD_ENV="$HOME/keys/partymail-upload.env" android/deploy/.venv/bin/python android/deploy/play.py --next
   ```

6. The upload certificate is ready for production trust configuration with the
   backend release. Add the **Google Play app-signing certificate** to that
   existing trust list in the morning; preserve the upload certificate for
   sideloaded release builds. Restart the server,
   verify app links/passkeys below, then test on both physical devices. Apple
   processing, beta review when needed, and Play first-app Console gates remain
   store-controlled steps.

## Domain association and passkeys

Production configuration:

```dotenv
RSVP_PUBLIC_URL=https://partymail.app
RSVP_APPLE_TEAM_ID=2FZS79QCFD
RSVP_ANDROID_SHA256_CERT_FINGERPRINTS=<PLAY_APP_SIGNING_SHA256>,<OPTIONAL_UPLOAD_SHA256>
```

The server serves `/.well-known/apple-app-site-association` with app ID
`2FZS79QCFD.com.davidfwatson.partymail` for universal links and webcredentials.
iOS entitlements declare `applinks:partymail.app` and
`webcredentials:partymail.app`. Verify the association endpoint returns JSON
over HTTPS with no redirect. Team/bundle settings must agree with the signed app.

The server serves `/.well-known/assetlinks.json` using the configured Android
SHA-256 fingerprints for both app links and Credential Manager passkeys, and
derives the WebAuthn Android origins from the same certificates. Use the
certificate under Play Console's App integrity/App signing page, **App signing
key certificate**, for the app installed from Play. Colon-separated or compact
hex fingerprints are accepted; multiple certificates use commas. Add the
upload certificate only to support deliberate release sideloads. The backend
does not trust an SDK debug key by default. [Android's verification guide](https://developer.android.com/training/app-links/verify-applinks)
describes domain verification and device commands.

```bash
adb shell pm verify-app-links --re-verify com.davidfwatson.partymail
adb shell pm get-app-links com.davidfwatson.partymail
```

Test event `/<slug>`, RSVP edit `/<slug>/update-rsvp/<token>`, administrator
sign-in `/admin/signin/<token>` and enrollment `/admin/invite/<token>` links.
An administrator sign-in link is consumed only after confirmation. Test custom
`partymail://` links too. Use a private test event; never paste real response or
administrator tokens into shared test reports.

## Local development and repeatable validation

```bash
venv/bin/python scripts/mobile_fixture.py
```

The server binds `127.0.0.1:5000`. Each run creates temporary demo data, with
owner password **test**, active invitation **demo-party**, an archived event,
and two seeded responses. Email, phone notifications and analytics are disabled;
all changes disappear on exit. No production store is opened.

iOS debug launch environment: `PARTYMAIL_BASE_URL=http://127.0.0.1:5000`.
Android emulator debug build:

```bash
cd android
./gradlew :app:assembleDebug -PpartyMailBaseUrl=http://10.0.2.2:5000
```

Release builds always use `https://partymail.app`. A physical debug device needs
a reachable development origin; the fixture allows explicit `--host 0.0.0.0`
for that purpose. Native passkeys require the production domain association and
device credential providers; use password recovery for the local fixture.

```bash
bash scripts/verify_mobile.sh
bash scripts/verify_mobile.sh --all
python3 ios/deploy/testflight.py --preflight --archive-only --skip-upload
python3 ios/deploy/testflight.py --archive-only --skip-upload
```

`verify_mobile.sh` runs offline deployment regressions and the fixture API smoke.
`--all` additionally runs iOS simulator tests and Android tests/lint/debug build;
`--ios` or `--android` selects one platform. Override
`PARTYMAIL_IOS_DESTINATION` with a local simulator destination. CI chooses an
available iPhone, tests the actual Xcode scheme, tests/lints/builds Android, and
retains simulator app/result bundles plus the debug APK, unsigned release AAB
and reports for 14 days.
The iOS CI job and local `--ios`/`--all` verification start their own isolated
Python fixture on port 5059, check its identity/readiness, and exercise
the actual simulator guest RSVP/update flow as well as unit tests. Its fixture
uses temporary data and is terminated when the test step exits. This avoids
macOS services that can occupy port 5000. `PARTYMAIL_FIXTURE_PORT` overrides the
local verification port. Fixture startup/runtime logs are printed on failure;
CI includes them in its artifact. `TEST_RUNNER_PARTYMAIL_TEST_BASE_URL` forwards
the fixture origin into the XCTest runner before it launches the app.
Simulator builds/unsigned device archives are suitable for validation; a signed
IPA/AAB is produced after signing setup. CI never uploads to either store.

Default artifact locations:

| Artifact | Location |
| --- | --- |
| Android installable debug APK | `android/app/build/outputs/apk/debug/app-debug.apk` |
| Android signed sideload release APK | `android/app/build/outputs/apk/release/app-release.apk` (when `:app:assembleRelease` is run with upload-key settings) |
| Android signed release AAB | `android/app/build/outputs/bundle/release/app-release.aab` |
| iOS unsigned device archive | `/tmp/PartyMail.xcarchive` |
| iOS signed distribution IPA | `/tmp/PartyMail.ipa` |
| iOS local verification simulator app | `/tmp/PartyMail-verify/Build/Products/Debug-iphonesimulator/PartyMail.app` |

The signed Android release APK and AAB were built locally with the dedicated
Party Mail upload key, and their certificate was verified against the public
fingerprint above. The CI AAB is deliberately unsigned because CI has no upload
credentials; use the local signed AAB for the first Play Console release.

The unsigned archive does not require store credentials:
`python3 ios/deploy/testflight.py --archive-only --skip-upload --archive-path /tmp/PartyMail.xcarchive`.
After provisioning exists, use `--build N --skip-upload` to create the signed
IPA, or `--unsigned-archive --build N --skip-upload` if Xcode's account refresh
fails but the Apple Distribution identity and App Store profile are installed.

Before releasing, check host password/passkey login, create/edit/style an event,
upload an image, archive/restore, share invitation/send email, inspect guests,
CSV export, administrator access management, guest RSVP/change, duplicate-email
privacy, calendar links, network errors, and stale editor conflict recovery.
Confirm production email is connected separately; disabled email in the fixture
returns a clear share-link fallback.

## Store copy and review access

Suggested name: **Party Mail**. Subtitle/short description:
**Invitations and RSVPs made simple**. Category: Lifestyle. Description:

> Bring people together with a personal invitation. Create an event, choose its
> look, share the invitation, and keep every reply in one place. Guests can RSVP,
> add their party size and dietary needs, and update their answer. Hosts can see
> attendance, manage invitations, and export the guest list. Party Mail works
> with your existing Party Mail events and host account.

Privacy URL: `https://partymail.app/privacy`. Terms URL:
`https://partymail.app/terms`. Support URL: `https://partymail.app/privacy`
(it provides the configured contact email/removal route). Use the same public
support email configured by `RSVP_CONTACT_EMAIL`. Add phone/tablet screenshots
from a demo event; screenshots must contain no real guest information.

For review, provide a dedicated, persistent reviewer host and demo invitation
on the production domain. A one-use, 30-minute sign-in URL is unsuitable as the
only reviewer credential. Do not provide the production owner password. Explain
how to view a guest invitation, submit an RSVP, create/edit an event and review
guest replies. Provide a stable review passkey/account mechanism or a separately
hosted persistent review environment before requesting external review; temporary
local fixtures are not reachable by store reviewers. Current host enrollment is
invitation-based and native clients do not sell accounts or take payments.

## Privacy form preparation

The native clients contain no advertising or analytics SDK. API calls store data
on the Party Mail server. The website's consent-based Google Analytics is a
separate web behavior; if it runs in an app-controlled web surface, include that
collection when completing store forms. Confirm the shipped app's actual behavior
before submitting declarations. [Apple's privacy definitions](https://developer.apple.com/app-store/app-privacy-details/)
cover data from third-party code as well as the app. [Google's Data safety guide](https://support.google.com/googleplay/android-developer/answer/10787469)
includes controlled webviews and distinguishes service-provider transfers and
user-initiated sharing from other sharing.

Based on [the existing Party Mail policy](https://partymail.app/privacy), prepare:

| App data | Proposed purpose/handling |
| --- | --- |
| Host and RSVP names, RSVP email addresses | App functionality/account management; linked to user/event; needed for replies and confirmations |
| Host account ID, public passkey credential | Account management/security; linked to host; private passkey never leaves device |
| Event description/location, guest counts, notes | User-generated content for app functionality; linked to event/responding guest |
| Uploaded invitation images | Photos/user-generated content for app functionality; user selected |
| Dietary restrictions/allergies entered by guests | Optional health-related information and/or other user content, for host planning; linked to guest |

Do not declare “no data collected.” Names/emails and stored event/response
content leave the device. Do not declare precise device location, contacts,
HealthKit, advertising identifier or device tracking: clients do not request
those sources. Event location is text entered by a host, and dietary needs are
text entered by a guest. No data is sold or used for advertising; release API
traffic uses HTTPS. Gmail sends invitations/confirmations, existing APNs/Pushover
host notifications carry the RSVP name/answer, and the existing encrypted backup
is retained for up to twelve months. Public attendee lists expose first name,
last initial and party size only when enabled. Data-removal requests go through
the host or the configured privacy contact. Declare collection and any sharing
according to the provider/user-directed exceptions that apply; do not blanket
answer “no sharing” without reviewing those transfers. Internal-only Play tests
are exempt from the Data safety section; complete it before wider distribution.

## Optional merge autoship

The existing `../server-ops` LaunchAgent infrastructure supports these scripts.
Templates are checked in at `ios/deploy/autoship.conf.example` and
`android/deploy/autoship.conf.example`; they use dedicated build trees and
Party Mail labels, branch `main`, path-based triggers (`ios` / `android`) and
the Party Mail iOS provenance ledger. Backend-only changes do not ship a binary.
Store app records/tester groups/first Play release must exist before installation.

After a successful first manual release, add each template as
`apps/partymail.conf` in the respective `server-ops` autoship directory, review
and merge that server-ops change, then run from its current default branch:

```bash
../server-ops/ios-autoship/install.sh --app partymail
../server-ops/ios-autoship/install.sh --app partymail --check
../server-ops/android-autoship/install.sh --app partymail
../server-ops/android-autoship/install.sh --app partymail --check
```

Installation seeds the watchers at the branch tip; the next qualifying merge
ships. Each watcher pins the commit it builds and verifies the build on its
store before marking success. `[skip ship]` suppresses deliberate qualifying
commits. A hand upload after autoship is enabled needs care around pending
watcher state and already-consumed build numbers. Keep Java/Android SDK paths in
the Android config because launchd has a minimal environment; keep the signing
env file explicit. No sibling repository or installed LaunchAgent is changed
by this mobile implementation.

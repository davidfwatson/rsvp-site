# Party Mail for Android

Native Jetpack Compose app, package `com.davidfwatson.partymail`, Android 9+
(API 28), target/compile SDK 36. Dependency versions and Gradle wrapper follow
`../personal-site/android`; the apps use distinct package IDs and signing keys.

The host app creates and edits all event details/design fields, uploads raw
invitation artwork and background photos, shares/emails invitations, shows
response statistics and guest details, exports CSV, archives/restores events,
and manages administrators, invites, one-use sign-in links, passkeys and sessions.
Guests open invitations, RSVP, update their response and add calendars without
an administrator account. Archived events remain visible to hosts only.

`PartyApi` calls the shared Flask mobile API and existing account endpoints.
The session cookie and remembered RSVP tokens are AES-GCM encrypted with a
non-exportable Android Keystore key. Backups/device transfers are disabled.
Every mutation carries CSRF, authentication refreshes session/CSRF, and mutation
requests are never automatically retried. Expired authentication returns to
sign-in; an event version conflict requires reloading its current version.

Credential Manager handles native passkey assertions and registrations. The
production backend must trust the certificate used to sign the installed app;
see the [release guide](../docs/mobile-release.md). The development debug
certificate is deliberately not authorized on production. Owner recovery and
one-use links provide alternative access. Opening a one-use link displays an
explicit confirmation and does not consume it until the user continues.

The native editor and guest screens remain native. A host design preview uses
server-rendered HTML fetched through the authenticated API client. Its isolated
WebView has no session cookies, JS bridge, file/content access or navigation;
only same-origin static/media GET resources are permitted. This retains the
site's invitation artwork proportions, transparency and envelope animations.

## Build and test

Use JDK 21, installed Android SDK 36/build tools, and point `local.properties`
(untracked) at the SDK. This Mac uses
`/opt/homebrew/share/android-commandlinetools`.

```sh
cd android
JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home ./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:bundleRelease
```

Debug builds use production by default. For the isolated fixture server:

```sh
./gradlew :app:assembleDebug -PpartyMailBaseUrl=http://10.0.2.2:5000
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -a android.intent.action.VIEW -d 'partymail:///demo-party' com.davidfwatson.partymail
```

A release always targets `https://partymail.app`, regardless of debug overrides,
and never permits cleartext. Provide `PARTYMAIL_UPLOAD_KEYSTORE`,
`PARTYMAIL_UPLOAD_PASSWORD` and `PARTYMAIL_UPLOAD_ALIAS` to sign it; without those
variables `bundleRelease` is intentionally unsigned. Versions come from
`gradle.properties`, with strict code validation and Gradle property overrides.
APK: `app/build/outputs/apk/debug/app-debug.apk`. Release AAB:
`app/build/outputs/bundle/release/app-release.aab`.

The unit suite checks deep-link origin/path/token boundaries, event validation,
RSVP party-size rules and public/duplicate-response deserialization. Local
emulator smoke tests use an isolated backend, never production event data.
TestFlight/Play account setup and store release steps are in the
[mobile release guide](../docs/mobile-release.md) and [Play tooling guide](deploy/README.md).

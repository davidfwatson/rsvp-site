# Party Mail for iPhone and iPad

Native SwiftUI app, iOS 17+, bundle `com.davidfwatson.partymail`, shared Xcode scheme
`PartyMail`, Apple team `2FZS79QCFD`. Open `PartyMail.xcodeproj`; no package manager
or project generator is required. Release builds always use `https://partymail.app`.

The Host tab supports event creation and editing (including every invitation
design field, optional event code, transparent invitation artwork, and background
photos), guest statistics and responses, CSV export, email invitations, sharing,
rendered HTML preview, archive, and restore. The Invitations tab supports public
event links/codes, RSVP and private response updates, attendee lists, and Google
or Apple calendar links. The Account tab supports profile names, native passkey
registration/removal, session revocation, administrator invitations, member
management, one-use sign-in links, and legal pages.

## Run against an isolated development server

From the repository root:

```sh
python3 scripts/mobile_fixture.py --port 5000
```

Set the scheme's Run environment variable `PARTYMAIL_BASE_URL` to
`http://127.0.0.1:5000` in Xcode. This override exists only in Debug builds. Fixture
owner recovery password: `test`; invitation: `demo-party`; private response link:
`partymail:///demo-party/update-rsvp/demo-update-token-0123456789abcdef`.

```sh
xcodebuild -project ios/PartyMail.xcodeproj -scheme PartyMail \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  -derivedDataPath /tmp/partymail-ios-build CODE_SIGNING_ALLOWED=NO test

xcodebuild -project ios/PartyMail.xcodeproj -scheme PartyMail \
  -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/partymail-ios-device CODE_SIGNING_ALLOWED=NO build
```

The full test suite uses the fixture server; override its address with
`PARTYMAIL_TEST_BASE_URL`. Unit-only tests can run without a server using
`-only-testing:PartyMailTests`. UI tests clear this app's fixture-origin Keychain
entries before launching, exercise guest RSVP/update and host
login/create/preview/archive/restore, and retain screenshots in the `.xcresult`.

## Links and credentials

Associated domains include `applinks:partymail.app` and
`webcredentials:partymail.app`; the site serves the matching Apple association.
Universal Links and the `partymail` URL scheme support event, RSVP-update,
administrator enrollment, and sign-in-link routes. Opening a one-use sign-in
link presents an explicit confirmation before consuming it.

Native passkeys use AuthenticationServices with the production relying party
`partymail.app`. Actual Face ID/Touch ID enrollment and sign-in require a signed
app with the associated-domain entitlement and a reachable production
association. The localhost fixture deliberately cannot issue production-domain
passkeys. Those final device checks follow Apple's app/signing setup.

Session cookies and RSVP-update tokens live in device-only Keychain entries,
isolated by origin. API traffic uses an ephemeral session without disk caches;
requests are serialized so Flask session-cookie rotations cannot race. Requests
carry CSRF tokens, authentication refreshes the session, expired sessions recover
without automatically replaying mutations, and host views never receive RSVP
update tokens. Account changes erase the previous user's private access links.
Host previews fetch authenticated HTML and render it in a nonpersistent WKWebView.
The native app has no analytics SDK; the privacy manifest declares functional
account, RSVP, location, optional dietary, and artwork data.

## TestFlight

Use the deployment workflow adapted from `../personal-site` in
[`deploy/README.md`](deploy/README.md). Version `1.0`, committed build `1` is ready
for the initial App Store Connect app record and provisioning profile. Preflight
checks run with `python3 ios/deploy/testflight.py --preflight`; signing/export and
upload use the same script after those accounts are configured.

Verified on the installed iPhone 17 simulator: all nine unit regressions and both
end-to-end UI tests pass. The unsigned Release device build also succeeds.

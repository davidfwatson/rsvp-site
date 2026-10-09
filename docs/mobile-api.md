# Party Mail mobile API

The SwiftUI and Kotlin apps use `https://partymail.app`, bundle/package
`com.davidfwatson.partymail`. All endpoints use the existing Flask session cookie.
GET `/api/mobile/session` bootstraps `{csrf_token, admin: null | {id,name,is_owner},
public_url, email_enabled, email_connected}`. Send `X-CSRF-Token` on every mutation.
Refresh session after authentication because login rotates the CSRF token. Do not
blindly retry mutations. Errors are `{error: string}` with HTTP 400/401/403/404/409/429.

## Authentication

- POST `/api/mobile/login` `{password}` (owner recovery), returns session payload.
- POST `/api/mobile/signin` `{token}` consumes a one-use admin sign-in link only
  after explicit confirmation. Returns session payload.
- POST `/api/mobile/logout` `{}` clears session.
- Native passkeys use existing POST `/admin/passkey/auth/options` `{}` and
  `/admin/passkey/auth/verify` with standard WebAuthn credential JSON; registration
  uses `/admin/passkey/register/options` `{name}` and `/admin/passkey/register/verify`.
- Administrator invitation enrollment uses existing
  `/admin/invite/<token>/register/options` `{name}` and `/register/verify`.
- People/access endpoints remain `/admin/accounts`, `/admin/accounts/update`
  `{admin_id,name}`, `/admin/accounts/revoke` `{admin_id}`,
  `/admin/accounts/sessions/revoke` `{admin_id}`, `/admin/invites`,
  `/admin/invites/create` `{name}`, `/admin/invites/delete` `{token}`,
  `/admin/signin-links/create` `{admin_id}`, `/admin/signin-links/delete` `{id}`,
  `/admin/passkey/list`, `/admin/passkey/delete` `{credential_id}`.

## Host events

- GET `/api/mobile/events` -> `{events: [event...]}` including archived events.
- POST `/api/mobile/events` -> `{event}` HTTP 201. Input editable fields below.
- GET `/api/mobile/events/<slug>` -> `{event, rsvps: [response...]}`.
- PATCH `/api/mobile/events/<slug>` -> `{event}` requires integer `version`;
  stale versions get HTTP 409. Partial fields accepted; archive/restore via `archived`.
- POST `/api/mobile/events/<slug>/invite` `{email}` -> `{success:true}` or 503
  if email disabled/fails. Archived events return 400.
- POST `/api/mobile/events/<slug>/upload` multipart field `image` -> `{success,url}`.
- GET `/api/mobile/events/<slug>/export` -> UTF-8 CSV attachment (even if empty).
- Preview/rendered invitation: `/<slug>` (or `/admin/<slug>/preview` for archived).

An event has `id, slug, version, name, date` (YYYY-MM-DD), `start_time` (HH:mm),
`end_time` (HH:mm or empty), `location, description` (Markdown),
`max_guests_per_invite` (1..100), `color_scheme` (pink/blue/red/black),
`background_style` (linen/gradient/solid/image), `background_color, accent_color`
(#RRGGBB), `background_image, cover_image` (empty or `/media/<hex>.webp`),
`font_style` (serif/sans), `envelope_style` (classic/minimal), `show_attendees,
archived`, `public_url`, `stats: {responses,attending,accepted,declined}`.
Creating requires `name,date,start_time,location`; optional `slug`. Creation
requires a future date; editing past events is supported. Metadata is immutable.
Host responses omit the secret RSVP token. Fields: `name,email,attending` (yes/no),
`num_adults,num_children,dietary_restrictions,comment,timestamp,updated_at`.

## Guest invitations

- GET `/api/mobile/invitations/<slug>` -> `{event, attendees: [{first_name,
  last_initial,guest_info}]}`. Public event has no host stats. Archived gives 404.
- POST `/api/mobile/invitations/<slug>/rsvp` with response fields -> `{response,
  update_url, email_delivered}` HTTP 201 for a new response. Save the update token
  securely for the new responder. Duplicate email returns only
  `{check_email:true,email_delivered}` HTTP 200, never an existing response/token.
- GET `/api/mobile/invitations/<slug>/responses/<token>` -> `{response,event}`.
- PATCH same URL with response fields -> `{response,event}`; secret token required.
- Calendars: `/<slug>/calendar/google` and `/<slug>/calendar/ics`.

Universal/app links support `/<slug>`, `/<slug>/update-rsvp/<token>`,
`/admin/signin/<token>`, `/admin/invite/<token>`; custom scheme `partymail` uses
the same paths. Only accept the configured origin and validate path components.
Private tokens must not appear in logs, shared event lists, or analytics.

## Development

Override origin only in debug builds: iOS launch environment `PARTYMAIL_BASE_URL`,
Android Gradle property `partyMailBaseUrl` (default emulator `http://10.0.2.2:5000`
when explicitly set). Release builds always use HTTPS production. Fixture server
will run on port 5000 with isolated demo data and email disabled.

# Validation

The implementation was checked against isolated sample data. No production
server, production data, remote backup repository, or external recipient was
changed during development.

## Automated coverage

The Python suite covers the existing event/archive/calendar behavior plus:

- Atomic storage, process/thread locking, corrupt-file rejection, independent
  workers, safe migration, external production data, and test isolation before
  application imports.
- Stale editor conflicts, validation, preview sanitization, image decoding,
  transparency, metadata stripping, and CSRF on JSON/multipart mutations.
- Private RSVP changes, email collision protection, guest count limits,
  token-free redirects and CSV exports, and spreadsheet formula protection.
- Passkey verification using signed assertions, origin/signature/device
  verification failures, replay/expiry protection, member and session
  revocation, one-use access links, and concurrent account operations.
- Artifact verification, promotion rollback, real gunicorn candidate startup
  with production configuration, and preservation of persistent data.
- Consistent backup snapshots, manifest verification, writer exclusion during
  local copying, unlocked remote transfer, and successful-backup-only retention.

Run `python -m pytest -q` with `requirements-dev.txt` installed. The final
integrated suite passed 124 tests.

## Browser checks

Chromium was run against temporary development stores. Desktop (1440px) and
mobile (390px) checks covered the dashboard, editor, design controls, guest
search, account management layout, navigation, envelope opening, and guest
RSVP submission. No page JavaScript errors or mobile horizontal overflow
were found in those flows.

The editor was tested offline and then reconnected; its unsaved draft persisted
once the connection returned. Two editor windows were tested against the same
event; the older window reported a conflict and did not overwrite the newer
save. WebAuthn registration and login were also verified in the browser using
a virtual authenticator on a valid localhost origin.

Envelope collision fixes were checked in WebKit and Chromium on the isolated
tailnet preview. Frame samples verified that the card stays inside while the
flap moves, the flap is fully open before the card lifts, and its front face
stays hidden above the extracted card. Checks also covered repeated replay
taps, long titles, reduced motion, guest content appearing after the opening,
and artwork clearance at widths from 280px to 1440px. The 26 productionization
tests passed again after the template changes.

The Design tab's inline envelope animation was checked in both browsers at
280–1440px, including mobile draft updates, color changes, replay controls,
tab navigation, and reduced motion. The inline pane remains animation-only
after updates; the header Preview button opens the full invitation separately.
Browser test saves were blocked; the sample events were unchanged.

All four envelope palettes were checked in WebKit and Chromium in classic
and matte finishes. Rendered paper pixels confirmed their distinct hues, and
picker swatches shared the envelope pigment. Change-only color selections
during emulated slow saves reached both the preview and final save payload;
the checks did not modify event data.

Uploaded invitation artwork was checked using the supplied portrait birthday
card on the isolated tailnet demo. The complete image is used in the envelope,
the full invitation, and the dashboard thumbnail. Browser geometry checks at
280–1440px verified preserved proportions, full extraction above the envelope
front, readable full-width artwork, and no horizontal overflow. Square,
landscape, panoramic, extremely tall/wide, and transparent star-shaped fixtures
also passed; failed image loads retained the generated text card. Replay was
checked across a resize, with sizing applied after the opening completed.
Dashboard fixtures passed in WebKit and Chromium, including long event titles.
The isolated Python suite passed all 129 tests after integrating the latest
privacy-page changes. Only a new sample event
and its uploaded artwork were added to the temporary demo data.

Real Gmail sending, live Analytics collection, SSH deployment, and offsite
restic transfer require the operator setup in `production.md`. The application
and workflow are prepared for those integrations; development checks did not
send real email, analytics events, or backups.

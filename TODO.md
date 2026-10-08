# Production activation

- [ ] Follow `docs/production.md` to copy existing events, RSVPs, and passkeys into the external data directory and configure the release service.
- [ ] Add verified SSH deployment secrets and enable the GitHub production workflow.
- [ ] Reconnect Gmail to create `token.json`; verify real invitation and confirmation delivery.
- [ ] Verify ownership of Analytics property `G-52ZJ7PXYEC`, disable enhanced measurement, and set the measurement ID.
- [ ] Configure the encrypted backup repository and enable the nightly backup timer; test a restore.

# Implemented

- [x] Passkey accounts, one-use enrollment and sign-in links, user and session management.
- [x] Responsive admin workspace, invitation design controls, autosave status and live preview.
- [x] Image upload, custom backgrounds, CSS 3D envelope and card opening.
- [x] Guest RSVP changes through private links, comments, attendance counts and CSV export.
- [x] Isolated tests, durable storage, stale-editor protection, and health-checked release deployments.

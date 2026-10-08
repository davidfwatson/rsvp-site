# Production deployment and recovery

Party Mail serves code from `/srv/rsvp/current`, a symlink to a tested release
under `/srv/rsvp/releases/<commit>`. It keeps all events, RSVPs, accounts,
uploads, and Gmail credentials in `/var/lib/rsvp-site`. Deployment never copies
or replaces that directory. Secrets live in `/etc/rsvp-site.env`.

The app refuses production startup without an explicit absolute external data
directory, its `.rsvp-data` marker, an environment secret of at least 32
characters, and matching HTTPS origin/passkey hostname. Keep the existing
`partymail.app` RP ID so existing passkeys continue to work.

## One-time server setup

Use the existing host and TLS certificate. These are operator setup commands,
not commands automatically run by CI. The supplied unit and deploy script both use the dedicated `rsvp` account.
Python 3.12, its venv package, nginx, and systemd must already be installed.

```bash
sudo useradd --system --create-home --home /home/rsvp --shell /bin/bash rsvp
sudo install -d -o rsvp -g rsvp -m 755 /srv/rsvp /srv/rsvp/releases /srv/rsvp/incoming
sudo install -d -o rsvp -g rsvp -m 700 /var/lib/rsvp-site
sudo install -o root -g rsvp -m 640 deploy/production.env.example /etc/rsvp-site.env
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

Put the generated secret and real sender address in `/etc/rsvp-site.env`.
The example includes the site's existing Analytics property `G-52ZJ7PXYEC`;
verify ownership and its web stream in Google Analytics before enabling it.
In the web stream settings, disable **Enhanced measurement** so automatic
events cannot capture private navigation URLs; the app sends explicit page
views with cleaned public paths after consent. Leave advertising signals off.
An empty `RSVP_GA_MEASUREMENT_ID` disables tracking. `RSVP_EMAIL_ENABLED=false`
is useful until Gmail has been authorized. Gmail credentials and token are
stored outside releases alongside event data.

Stop the old service before copying data so the copy includes its last write.
First take a timestamped backup of the old checkout's `data/`, `admins.json`,
`rsvps_*.json`, `credentials.json`, `token.json`, and `token.pickle` wherever those exist.
Then run the explicit copy migration as the service user:

```bash
sudo systemctl stop rsvp-site
sudo -u rsvp python3 scripts/migrate_data.py \
  --source /home/david/webserver/rsvp-site \
  --destination /var/lib/rsvp-site
```

If the old checkout is unreadable to `rsvp`, run the migration as the old
owner, then `sudo chown -R rsvp:rsvp /var/lib/rsvp-site`. The migration validates
all JSON before writing, preserves source files, and refuses to overwrite a
different destination file. It is safe to rerun when both copies agree. A new
installation with no legacy data may use `--init-empty`; never use that option
to recover a missing production data directory.

Gmail now uses `token.json` rather than loading executable pickle data. The
migration preserves an old `token.pickle` as a backup without deserializing it.
Reconnect Gmail through the owner settings after migration to issue a new
`token.json`; the old file is not read by the application. Existing passkey
credentials in `admins.json` are copied unchanged and need no reenrollment.

Install `deploy/rsvp-site.service` as `/etc/systemd/system/rsvp-site.service`.
It runs gunicorn as `rsvp`, restricts filesystem writes to the data directory,
and logs to journald. Replace the old nginx uWSGI location with the contents of
`deploy/nginx.conf` inside the existing HTTPS server block. It proxies to
loopback port 8087, caps uploads at 10 MiB, and avoids logging private invite
URLs. Preserve your existing TLS and ACME settings. Run `sudo nginx -t` before
reloading nginx, then `sudo systemctl daemon-reload`.

Install the CI public key in `/home/rsvp/.ssh/authorized_keys` with the
`restrict` option and owner-only permissions; disable password login for this
account. Set `RSVP_DEPLOY_USER=rsvp` in GitHub. The deployment process runs as
that account so its candidate can read production data, which remains
owner-only. The web process is confined by the systemd unit even though CI uses
the same Linux account. Do not reuse a personal or broadly privileged SSH key.

Give `rsvp` passwordless permission for **only**
`/usr/bin/systemctl restart rsvp-site.service`, using a validated sudoers drop-in
(check with `visudo -cf`). The deploy account controls application code and is
trusted with this service's data; no generic sudo permission is needed. If you
use a different account or path, adjust the service, ownership, and workflow
together instead of broadening the data directory's permissions.

## Automatic deployment after merges

`.github/workflows/ci-deploy.yml` runs tests for pull requests and pushes to
`main`. Protect `main` with the `test` check and require review to ensure pushes
represent approved merges. The production job is opt-in until host setup is
complete: create a GitHub **production** environment and set:

| Setting | Value |
| --- | --- |
| Repository variable `RSVP_DEPLOY_ENABLED` | `true` |
| Secret `RSVP_DEPLOY_HOST` | Your SSH hostname |
| Secret `RSVP_DEPLOY_USER` | The trusted deployment account |
| Secret `RSVP_DEPLOY_PORT` | Optional; defaults to `22` |
| Secret `RSVP_DEPLOY_KEY` | Private SSH key scoped to the deployment account |
| Secret `RSVP_DEPLOY_KNOWN_HOSTS` | Verified SSH host-key entry, including port syntax when needed |

Verify the host key through your existing trusted SSH connection. CI enforces
host-key verification and never uses `StrictHostKeyChecking=no`. Environment
reviewers can provide an additional approval gate if desired.

The workflow installs `requirements-dev.txt`, tests the checkout, and creates a
source archive from the exact commit. It uploads the archive and checksum. On
the server `scripts/deploy_release.py`:

1. Holds a deployment lock so two releases cannot interleave.
2. Verifies the checksum, archive paths, and absence of production data/secrets.
3. Creates a new release directory and its own virtualenv, then reruns the
   complete tests with fresh temporary stores before importing the app.
4. Starts that release privately with production configuration and requires
   `/healthz` to report its exact commit SHA.
5. Atomically switches `current`, restarts the service, and checks the public
   health endpoint for the same SHA. If this fails it restores the old pointer
   and restarts the old release. The previous verified release remains available.

Production is served from the release directory, with no Git checkout or Git
pull in the running application's directory. There is no `rsync --delete`
against the data root. Tests override inherited production settings at conftest
import, before collection imports any stores; storage also refuses test writes
outside the temporary root.

The default public health URL is `https://partymail.app/healthz`. For a different
host, pass `--health-url` to the deploy script and update the workflow command.
The configured loopback port must be unused by other services.

## Rollback and backups

Roll back application code to the previous verified release:

```bash
python3.12 /srv/rsvp/current/scripts/deploy_release.py --rollback
sudo journalctl -u rsvp-site -n 100 --no-pager
```

Rollback preserves current event/account/RSVP data. Do not restore old data
merely because an application release was rolled back. Do not remove the
`current` or `previous` release directories when pruning old releases.

JSON updates take a process lock for the whole read-modify-write, write a
unique temporary file, fsync it, atomically replace the target, and fsync its
directory. Each document retains up to 20 previous revisions under
`.backups/<filename>/`. Malformed JSON fails visibly instead of becoming an
empty store. Event autosaves carry a version so a stale tab cannot overwrite
a newer editor; workers refresh event files when disk contents change.

Install the nightly offsite backup described below. Revision copies help with
accidental edits but do not survive a lost disk. Protect backups as account and
guest data, and periodically restore one into a separate directory to verify
the complete recovery path.

For recovery of one document, stop the service, preserve the current file,
copy a verified `.bak` revision into its original location with the same owner
and permissions, then restart and check `/healthz`. A failed migration or
startup must be investigated rather than replacing data with an empty store.

## Nightly encrypted offsite backups

`deploy/rsvp-backup.service` and `.timer` are ready to install; they are **not
enabled until you configure a real off-host repository, its access credentials,
and its encryption password**. Install restic through the server's package
manager and confirm `restic version`. Select an S3-compatible bucket in an
independent account/location or another supported off-host restic backend.
Use credentials limited to that repository/bucket prefix; retention requires
permission to delete old backup objects. Keep the encryption password in your
password manager or another independent recovery location.

The root backup service must never execute code writable by the web account.
Install fixed root-owned copies of the helper and its storage library:

```bash
sudo install -d -o root -g root -m 755 /usr/local/lib/rsvp-backup
sudo install -o root -g root -m 644 scripts/backup_data.py storage.py /usr/local/lib/rsvp-backup/
sudo install -o root -g root -m 600 deploy/backup.env.example /etc/rsvp-backup.env
sudo install -o root -g root -m 644 deploy/rsvp-backup.service deploy/rsvp-backup.timer /etc/systemd/system/
sudo install -d -o root -g root -m 700 /var/lib/rsvp-backup
sudo install -d -o rsvp -g rsvp -m 700 /var/lib/rsvp-site/events /var/lib/rsvp-site/uploads
sudo sh -c 'umask 077; python3 -c "import secrets; print(secrets.token_hex(32))" > /etc/rsvp-backup.password'
```

Update `/etc/rsvp-backup.env` with the real remote repository and bucket access
credentials. The example includes a `RESTIC_PASSWORD_FILE`; do not put the
password in Git or a command line. Do not regenerate this password after
initializing the repository. Initialize the new repository once using its
private configuration:

```bash
sudo bash -c 'set -a; source /etc/rsvp-backup.env; set +a; exec restic init'
```

The helper takes a local private copy while holding the event collection lock,
all current JSON document locks, each event's RSVP lock even before its first
response exists, and the upload collection lock. It copies data, revision
backups, images, Gmail/account credentials, and `/etc/rsvp-site.env`, and adds
a SHA-256 manifest. This briefly pauses mutations while files copy locally.
It releases all application locks before contacting the remote repository.
Root-created lock files retain the service user's ownership, so the next app
request can reopen them.

Restic encrypts the remote snapshot. The helper then keeps the last 3 backups,
14 daily, 8 weekly, and 12 monthly snapshots, pruning only snapshots tagged
`partymail-production` for the configured backup host. It runs `restic check`
afterward and records the last complete success in
`/var/lib/rsvp-backup/last-success.json`. A failed upload skips retention.
Private temporary snapshots are removed after either success or failure; a
machine crash may leave a root-only `snapshot-*` directory to remove manually.
See restic's [backup documentation](https://restic.readthedocs.io/en/stable/040_backup.html)
and [retention documentation](https://restic.readthedocs.io/en/stable/060_forget.html).

Test the configured service before enabling the schedule:

```bash
sudo systemctl daemon-reload
sudo systemctl start rsvp-backup.service
sudo systemctl status rsvp-backup.service --no-pager
sudo cat /var/lib/rsvp-backup/last-success.json
sudo systemctl enable --now rsvp-backup.timer
sudo systemctl list-timers rsvp-backup.timer
```

The timer runs at 03:15 in the server's timezone with up to 30 minutes of
random delay. `Persistent=true` catches up after downtime. The service exits
unsuccessfully if snapshot/upload/prune/check fails; inspect
`sudo journalctl -u rsvp-backup.service`. Connect your existing host monitoring
to failed units and stale `last-success.json` (for example, over 48 hours old).
No alert delivery integration is assumed. Update the installed root-owned
helper/library manually when changing their code; release deployment never
replaces privileged backup executables.

For a local snapshot without any network call, specify an empty root-only
directory outside the live data:

```bash
sudo python3 /usr/local/lib/rsvp-backup/backup_data.py \
  --snapshot-only /var/lib/rsvp-backup/manual-check
sudo python3 /usr/local/lib/rsvp-backup/backup_data.py \
  --verify /var/lib/rsvp-backup/manual-check
```

Remove that private test copy afterward. This check does not replace a remote
backup or restore drill.

## Restore drill and full recovery

Restore a snapshot into a fresh directory **before** considering a production
replacement. Restic restores overwrite files at their target, so use a new
directory outside the live data root. The snapshot contains relative `data/`,
`production.env`, and `manifest.json` paths:

```bash
sudo install -d -o root -g root -m 700 /var/lib/rsvp-backup/restore-check
sudo bash -c 'set -a; source /etc/rsvp-backup.env; set +a; exec restic restore latest --tag partymail-production --host "$RSVP_BACKUP_HOST" --target /var/lib/rsvp-backup/restore-check'
sudo python3 /usr/local/lib/rsvp-backup/backup_data.py \
  --verify /var/lib/rsvp-backup/restore-check
```

This downloads/decrypts the backup and verifies every file against its manifest
without displaying secrets or guest details. Inspect the expected events,
account count, and RSVP counts in the isolated copy; delete it after a drill.
Periodically run `restic check --read-data` through the same private env to
verify remote data contents as well as metadata, allowing for backend download
costs. See the [restic restore guide](https://restic.readthedocs.io/en/stable/050_restore.html).

For an actual incident, stop `rsvp-site` and the backup timer, preserve the
current data directory under another name, and install the verified restored
`data/` as `/var/lib/rsvp-site`. Set ownership recursively to `rsvp:rsvp`,
directories to `700`, and data files to `600`. Restore `production.env` only
when required, with root ownership, group `rsvp`, and mode `640`; preserve
current credentials and signing secrets when they are still authoritative.
Start the app, verify `/healthz`, sign in with an existing passkey, and verify
event/guest records before reenabling the timer. Application rollback alone
does not call for a data restore.

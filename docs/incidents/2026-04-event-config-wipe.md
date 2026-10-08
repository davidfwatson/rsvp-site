# Event config wipe (found April 2026) and the partial recovery

Last updated 2026-10-07. Status: open. One event is still missing from the
server and three restored events carry placeholder text.

## Summary

Until April 13, 2026 every event definition lived in a single
`event_config.json` in the app directory on the Linode. A pytest run on the
server overwrote that file with test fixtures. Every event definition was
lost. Only David's 38th was put back at the time. The guest responses live in
separate `rsvps_<id>.json` files, and most of those survived, but the file for
Ariana's 4th birthday is gone as well.

Event data is gitignored (`data/`, `rsvps_*.json`), so it has never been in
git. It exists only on the server, and nothing backs it up on a schedule.

## Timeline

- 2024-10: app created. A seed event, "Anita's 6th Birthday Party", is
  hardcoded in the first multi-event commit (`c5e2ca7`).
- 2025-01 to 2025-02: Ariana's 4th birthday (slug `ariana4th`) and a second,
  family event (id `891d4849`) collect RSVPs.
- 2026-01 to 2026-02: Ariana's 5th birthday (id `ariana5th`) collects 17 RSVPs.
- Between 2026-02-03 and 2026-04-13: the config file is overwritten. The date
  is inferred. The last Ariana's 5th RSVP is February 3, and the backup taken
  on April 13 already holds one event.
- 2026-04-13: commit `226d97b` moves events to `data/events/<slug>.json` and
  adds the test guards. Its message is the only first-hand record of the wipe.
- 2026-09-07: a Claude session restores four events as archived (PR #3).
- 2026-10-07: a second pass finds Ariana's 4th in the Wayback Machine and
  finds that the September restore had missed it.

## Cause

`save_event_config` rewrote the whole events list to one file, and the tests
used the same file as production. Running the suite in the server's app
directory replaced the real list with fixtures. The stale `event_config.json`
in the old Mac checkout holds the same fixture data, dated February 2025, so
the same thing had already happened locally a year earlier.

What stops a repeat: an autouse fixture in `conftest.py` points every test at
a temp directory, `EventConfig._assert_safe_write` raises if a test tries to
write to the real directory, and writes go through a temp file and
`os.replace`.

Not known: who ran the suite, on what day, and why only David's 38th was
restored in April.

## State of each event

| Event | Definition | RSVPs |
|---|---|---|
| David's 38th (`c9bd7076`) | Original, never lost for long | 9, intact |
| Anita's 8th (`305f1d8c`) | Created 2026-09-07, after the wipe | n/a |
| yimby event (`3be062f9`) | Description recovered from confirmation emails. Date, time and location were placeholder strings in the original | 5, intact |
| Anita's 6th (`anita_6th`) | The seed event from the code, restored verbatim. The real party was run through Evite and a Google Form and held on 2024-11-17 | 1 test submission |
| Family event (`891d4849`) | Lost. Name, date and location unknown. Currently labelled "Unidentified event (January 2025)" | 13, intact, 2025-01-23 to 2025-02-10 |
| Ariana's 5th (`ariana5th`) | Lost. Only the name is known. Email shows the party was the weekend of 2026-02-07 | 17, intact |
| Ariana's 4th (`ariana4th`) | Lost on the server and not restored. Recoverable from the Wayback Machine: 2025-02-08, 10:30 AM to 2:30 PM, with the full description | File missing from the server. The archived page lists 38 "Who's Going" entries as first name, last initial and party size, a few of them bot spam |

## Errors in the September restore

The restore wrote explanatory notes into the `description` field of each
restored event. For Ariana's 5th and the family event the whole description
is that note, written by the session. It is not recovered text, and it reads
as if it were the invitation.

It reported that no RSVP data was lost. That was wrong. It never learned that
Ariana's 4th existed, because neither its definition nor its RSVP file was on
the server.

It did not check the Wayback Machine or the git history of `app.py`, which
between January and October 2025 routed the front page to `ariana4th`.

## Where recovered evidence lives

- Wayback Machine captures of `https://partymail.app/` on 2025-03-16 and
  2025-03-26. These are the Ariana's 4th invitation page.
- Gmail: the yimby confirmation emails, and the 2024-10-14 "RSVP Request for
  Anita's 6th Birthday Party" test email.
- Server: `~/rsvp-site-backup-20260907-123511`, a copy of the data taken
  before the September restore.

## Still to do

- Add `ariana4th` as an archived event from the Wayback capture, with its
  partial guest list.
- Replace the placeholder descriptions with real text or leave them empty,
  and keep restore notes out of the description field.
- Get the real details for Ariana's 5th and the family event from David or
  Pardis.
- Archive David's 38th, which is past but still public.
- Set up a scheduled off-server backup of `data/` and `rsvps_*.json`.

# Keeping this current

## How it works now (live sync)

`data/clinicians.json` is rebuilt automatically, weekdays, by a GitHub
Actions workflow (`.github/workflows/sync-capacity.yml`). It pulls the
Roster and Capacity tabs from the Google Sheet via a **private, read-only**
Google service account, joins them, geocodes suburbs, and commits the
result if anything changed. GitHub Pages redeploys on that commit.

You should almost never need to run anything manually. Day to day:

- **New clinician joins:** add a row to the Roster tab (name — matching
  Cliniko exactly — discipline, suburb, postcode, status `Active`).
- **Clinician leaves:** set their Roster `status` to `Inactive`.
- **Clinician on extended leave** (parental leave, long-term illness, etc):
  set their Roster `status` to `Leave`. Short-term day-to-day leave doesn't
  need this — Jarvis reads that straight from Cliniko into the Capacity
  tab's `on_leave` column automatically.
- **Address change:** edit their suburb/postcode in the Roster tab.

None of the above needs a repo change, a script run, or a redeploy — the
next scheduled sync (weekdays, ~6:30am AEST) picks it up.

## Why not "Publish to web" as a public CSV?

An earlier version of this doc suggested publishing the Sheet as a public
CSV and having the map fetch it

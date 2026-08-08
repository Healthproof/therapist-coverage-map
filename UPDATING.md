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
CSV and having the map fetch it directly in the browser. That's been
deliberately avoided: the Sheet contains clinician names and home suburbs,
and a "Publish to web" CSV is accessible to anyone with the link, with no
authentication. The service-account approach keeps the same "no manual
rebuild" convenience without exposing that data publicly — the Sheet stays
private, and only the read-only service account (and Jarvis's separate
write-access account) can see it.

## If something's not updating

1. Check the **Actions** tab in the GitHub repo — find the "Sync capacity
   data from Google Sheet" workflow and see if the latest run failed.
2. Check `data/match-report.json` in the repo after a successful run — it
   lists:
   - `geocode_failures` — a suburb/postcode the lookup couldn't place
   - `no_capacity_row` — a Roster name with no matching Capacity row (often
     a name-mismatch against Cliniko — see the capacity feed handoff doc)
   - `capacity_rows_with_no_roster_match` — Jarvis has data for someone not
     yet added to the Roster tab
3. If the workflow itself is failing (not just producing a report with
   issues), it's most likely the `GOOGLE_SHEETS_CREDENTIALS` secret expired
   or was revoked, or the service account lost Viewer access to the Sheet —
   check both in that order.

## Suburb lookup

`data/nsw-suburbs.json` almost never needs touching — it's the suburb name
to lat/lon lookup, and NSW suburbs don't move. Only re-run
`scripts/build_suburb_lookup.py` if a new clinician's suburb shows up in
`geocode_failures` in the match report.

## Running it manually (rare — debugging only)

```
export GOOGLE_SHEETS_CREDENTIALS="$(cat path/to/service-account-key.json)"
export SHEET_ID="1DAwxaGtHBZkxUnCaSxUzqZht4onqC98B2p5Qb85Vsag"
pip install -r requirements.txt
python3 scripts/build_clinicians.py
```

You'd need your own copy of the service account key for this — don't ask
for the one stored in GitHub Secrets to be shared around; generate a
separate key if you need to run this locally.

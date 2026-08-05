# Keeping this current

## Right now (v1)

`data/clinicians.json` is a static snapshot, built once from the address CSV
and capacity ODS you uploaded on 3–4 Aug 2026. To refresh it with the same
manual files, drop new exports in as `data/clinician-addresses-raw.csv` and
`data/capacity-raw.ods` (same column layout) and re-run:

```
python3 scripts/build_clinicians.py
```

Commit and push `data/clinicians.json` — that's the only file that needs to
change day to day.

`data/nsw-suburbs.json` almost never needs touching — it's the suburb name
to lat/lon lookup, and NSW suburbs don't move. Only re-run
`scripts/build_suburb_lookup.py` if a therapist is based somewhere the map
can't find (check `data/match-report.json` for geocode failures after a
build).

## Recommended next step: a live Google Sheet

Editing a CSV/ODS and re-running a script and pushing to GitHub is more
friction than reception needs for a fortnightly update. The better long-term
setup:

1. Put the roster in a Google Sheet with one row per clinician: name,
   discipline, suburb, postcode, status (active / leave / departed),
   1–2wk capacity, 3–4wk capacity.
2. File → Share → Publish to web → CSV. Google gives you a public CSV URL.
3. Swap `index.html`'s `loadData()` to fetch that CSV URL instead of
   `data/clinicians.json`, and parse it into the same shape the map already
   expects (same field names as above).

Once that's wired up, updating the map is just editing the Sheet — no repo,
no script, no redeploy. New starters are a new row, leavers get deleted or
marked "departed", leave is a status flag, address changes are one cell.

I can build this swap whenever you're ready — happy to do it as a follow-up
once you've got the Sheet set up the way reception wants it, since the exact
column layout is worth agreeing on first.

# Healthproof therapist coverage map

Internal tool for reception/admin. Search a suburb (or click the map) to see
which mobile therapists are within range, their discipline, and their
current fortnightly booking capacity.

No backend, no build step to view it — it's a static site (HTML/CSS/JS) that
reads two JSON files. Runs entirely in the browser.

## Running it locally

Browsers block `fetch()` of local files opened directly (`file://...`), so
you need a tiny local server — this is normal for any static site with data
files, not specific to this project:

```
python3 -m http.server 8000
```

Then open `http://localhost:8000` in your browser.

## Deploying to GitHub Pages

1. Push this repo to GitHub.
2. Repo Settings → Pages → Deploy from branch → `main` → `/ (root)`.
3. GitHub gives you a URL like `https://<your-username>.github.io/<repo-name>/`.

No GitHub Action needed for this version — it's plain static files, so Pages
serves it as-is. Every time you push a change to `data/clinicians.json`, the
live site picks it up automatically (may take a minute or two to propagate).

## What's in here

```
index.html                     the whole app — map, search, filters
data/clinicians.json           the roster the map reads (name, suburb, lat/lon, capacity)
data/nsw-suburbs.json          static NSW suburb -> lat/lon lookup (~10,700 entries)
data/clinician-addresses-raw.csv   your source export, kept for reference
data/capacity-raw.ods          your source fortnightly capacity sheet, kept for reference
data/match-report.json         anything the merge script couldn't match cleanly
scripts/build_suburb_lookup.py builds data/nsw-suburbs.json (rarely needs re-running)
scripts/build_clinicians.py    builds data/clinicians.json from the two source files
```

## How the map works

- **Search a suburb** — autocomplete against the NSW suburb list, centres the
  map and filters the sidebar to therapists within the radius slider
  (default 25km), sorted nearest-first, with straight-line distance shown.
- **Click the map** — drops a pin anywhere and searches from that point
  instead (useful for an address that isn't a suburb centre).
- **25km coverage circles** — toggle on/off. Shows every active therapist's
  approximate service radius at once, for a quick "where are our gaps" view.
- **Discipline filter chips** and **hide staff on leave** — narrow the list
  further.
- Each result shows current 1–2wk / 3–4wk booking capacity from the fortnightly
  sheet, or "on leave" / "no capacity data" where relevant. The max
  appointment load (10/day, based on 30min appointments + 15min travel) is
  shown as a reference note in each popup — it isn't calculated from
  anything, just context for whoever's reading it.

## Known gaps in this v1 (see also match-report.json)

Five clinicians didn't have a row in this fortnight's capacity sheet
(mostly Podiatry, which isn't tracked in that sheet at all currently, plus
one OT and one PT contractor). They still appear on the map with their
location, flagged "no capacity data" rather than guessed at.

## Updating the roster

See `docs/UPDATING.md`.

## Branding

Uses the actual Healthproof brand palette (`assets/Healthproof_Brand_Colour_Guidelines.odt`):
primary blue `#26a4ff`, black `#0d0f11`, light blue `#eff8ff`, grey `#efefef`, accent orange `#ff8127`.
Logo lives at `assets/logo.png`.

Each discipline has its own distinct marker/circle colour so they're visually
separable on the map at a glance:

- Physio — blue (`#26a4ff`, brand primary)
- OT — teal green (`#1fb187`)
- Speech — orange (`#ff8127`, brand accent)
- Dietetics — purple (`#8a5fd6`)
- Podiatry — coral (`#e8556f`)

## LGA highlighting

When you search a suburb, the map looks up which NSW Local Government Area
contains that point and draws its boundary (dashed outline) with the name
shown in the sidebar. Boundary data: `data/lga-boundaries.json`, simplified
from Geoscape/data.gov.au LGA boundaries (sourced via UNSW City Futures
Research Centre's City Data portal) — simplified from ~5.7MB to ~84KB so it
loads fast, at a level of detail appropriate for suburb/city zoom, not
property-line precision.

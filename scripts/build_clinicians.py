"""
Builds data/clinicians.json from the live Google Sheet.

Data flow:
  Cliniko --(Jarvis/OpenClaw, weekdays 6am)--> Capacity tab
  Reception --(manual, rare)-------------------> Roster tab
  This script --(GitHub Action, weekdays)------> data/clinicians.json --> map

Auth: a read-only Google service account. Its JSON key is expected in the
GOOGLE_SHEETS_CREDENTIALS environment variable (set as a GitHub Actions
secret — see .github/workflows/sync-capacity.yml). Never commit the key
itself to the repo.

The service account must be shared on the Sheet as Viewer. It should have
no other permissions — it only ever reads.

Output: data/clinicians.json (used by the map)
        data/match-report.json (anything that needs a human look)

Usage (locally, for testing):
    export GOOGLE_SHEETS_CREDENTIALS="$(cat path/to/service-account-key.json)"
    export SHEET_ID="1DAwxaGtHBZkxUnCaSxUzqZht4onqC98B2p5Qb85Vsag"
    python3 scripts/build_clinicians.py
"""
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent.parent
SUBURB_LOOKUP = ROOT / "data" / "nsw-suburbs.json"
OUT_CLINICIANS = ROOT / "data" / "clinicians.json"
OUT_REPORT = ROOT / "data" / "match-report.json"

SHEET_ID = os.environ.get("SHEET_ID", "1DAwxaGtHBZkxUnCaSxUzqZht4onqC98B2p5Qb85Vsag")
ROSTER_RANGE = "Roster!A2:E"
# Extended from A2:F to A2:H to pick up Jarvis's rolling_utilisation and
# target_utilisation columns:
#   practitioner_name | next_available_date | slots_available_1_2wk |
#   slots_available_3_4wk | on_leave | last_updated | rolling_utilisation |
#   target_utilisation
CAPACITY_RANGE = "Capacity!A2:H"

# A capacity row older than this is treated as stale rather than current —
# shown as "no data" (blank/null) rather than presented as today's answer.
# Jarvis runs on weekdays at 6am, so a normal same-day/next-business-day
# row is always well within this; anything older usually means the feed
# hasn't run for that person recently (e.g. a Cliniko practitioner-type
# filter skipping them) rather than genuinely fresh data.
STALE_AFTER_HOURS = 48

DISCIPLINE_CODE = {
    "physio": "PT",
    "ot": "OT",
    "speech": "Speech",
    "dietetics": "Dietetics",
    "podiatry": "Podiatry",
}
DISCIPLINE_JOB_TITLE = {
    "PT": "Physiotherapist",
    "OT": "Occupational Therapist",
    "Speech": "Speech Pathologist",
    "Dietetics": "Dietitian",
    "Podiatry": "Podiatrist",
}


def norm_suburb(s: str) -> str:
    s = s.upper().strip()
    s = re.sub(r"[^A-Z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


def load_suburb_lookup():
    with open(SUBURB_LOOKUP, encoding="utf-8") as f:
        return json.load(f)


def geocode(suburb: str, postcode: str, lookup: dict):
    key = f"{norm_suburb(suburb)}|{postcode}"
    if key in lookup:
        hit = lookup[key]
        return hit["lat"], hit["lon"], "postcode+suburb"
    key2 = norm_suburb(suburb)
    if key2 in lookup:
        hit = lookup[key2]
        return hit["lat"], hit["lon"], "suburb only"
    return None, None, "no match"


def get_sheets_service():
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_json:
        print("ERROR: GOOGLE_SHEETS_CREDENTIALS is not set.", file=sys.stderr)
        sys.exit(1)
    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    return build("sheets", "v4", credentials=creds)


def fetch_rows(service, range_name):
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SHEET_ID, range=range_name)
        .execute()
    )
    return result.get("values", [])


def load_roster(service):
    rows = fetch_rows(service, ROSTER_RANGE)
    roster = {}
    for row in rows:
        row = row + [""] * (5 - len(row))
        name, discipline, suburb, postcode, status = [c.strip() for c in row[:5]]
        if not name:
            continue
        status_norm = status.strip().lower()
        if status_norm not in ("active", "leave"):
            continue
        roster[norm_name(name)] = {
            "name": name,
            "discipline_code": DISCIPLINE_CODE.get(discipline.strip().lower()),
            "suburb": suburb,
            "postcode": postcode,
            "extended_leave": status_norm == "leave",
        }
    return roster


# Text Jarvis (or the original manual setup) may leave in a cell before
# real data has ever been written for that row. Treated as "no data yet",
# never as a genuine "zero capacity" signal — a literal "0" only means
# something once we know the feed has actually run for that clinician.
# "-" covers the rolling_utilisation column's own placeholder for
# clinicians without enough logged hours to compute a rolling average yet.
PLACEHOLDER_VALUES = {"", "pending first run", "n/a", "tbd", "-"}


def clean_capacity_field(v):
    return None if v.strip().lower() in PLACEHOLDER_VALUES else v.strip()


def parse_utilisation_pct(raw):
    """'60.50%' -> 60.5. Placeholder/blank/unparseable -> None."""
    cleaned = clean_capacity_field(raw)
    if cleaned is None:
        return None
    try:
        return float(cleaned.rstrip("%").strip())
    except ValueError:
        return None


def parse_last_updated(raw):
    cleaned = clean_capacity_field(raw)
    if cleaned is None:
        return None
    # Jarvis writes "YYYY-MM-DD HH:MM" (24h, no timezone marker — treat as
    # local Sydney time, close enough for a staleness check at this
    # resolution; we're comparing hours-old, not seconds-old).
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def load_capacity(service):
    rows = fetch_rows(service, CAPACITY_RANGE)

    # Jarvis's feed can carry duplicate rows for the same practitioner
    # (e.g. a stale row from a previous run that didn't get cleared). Keep
    # only the row with the most recent last_updated per person — never
    # "whichever row happens to be last in the sheet".
    by_name = {}
    stale_duplicates = []

    for row in rows:
        row = row + [""] * (8 - len(row))
        name, next_avail, cap12, cap34, on_leave, last_updated, rolling_util, target_util = [
            c.strip() for c in row[:8]
        ]
        if not name:
            continue

        key = norm_name(name)
        parsed_updated = parse_last_updated(last_updated)

        candidate_raw = {
            "name": name,
            "next_available_date": next_avail,
            "capacity_1_2wk": cap12,
            "capacity_3_4wk": cap34,
            "on_leave": on_leave,
            "last_updated_raw": last_updated,
            "last_updated_parsed": parsed_updated,
            "rolling_utilisation_raw": rolling_util,
            "target_utilisation_raw": target_util,
        }

        existing = by_name.get(key)
        if existing is None:
            by_name[key] = candidate_raw
            continue

        # Duplicate row for this person — keep whichever has the newer
        # last_updated (treating an unparseable/missing timestamp as
        # older than any real one, so it never wins over real data).
        existing_dt = existing["last_updated_parsed"]
        candidate_dt = candidate_raw["last_updated_parsed"]
        existing_wins = existing_dt is not None and (candidate_dt is None or existing_dt >= candidate_dt)
        winner, loser = (existing, candidate_raw) if existing_wins else (candidate_raw, existing)
        by_name[key] = winner
        stale_duplicates.append({
            "name": name,
            "kept_last_updated": winner["last_updated_raw"] or None,
            "discarded_last_updated": loser["last_updated_raw"] or None,
        })

    now = datetime.now()
    capacity = {}
    stale_rows = []

    for key, c in by_name.items():
        last_updated_clean = clean_capacity_field(c["last_updated_raw"])
        parsed_updated = c["last_updated_parsed"]

        is_stale = (
            parsed_updated is not None
            and (now - parsed_updated).total_seconds() / 3600 > STALE_AFTER_HOURS
        )
        if is_stale:
            stale_rows.append({
                "name": c["name"],
                "last_updated": last_updated_clean,
                "hours_old": round((now - parsed_updated).total_seconds() / 3600, 1),
            })

        if last_updated_clean is None or is_stale:
            # Never trust capacity_1_2wk/3_4wk/next_available/utilisation
            # from a row that either has no confirmed feed run, or whose
            # confirmed run is too old to still call "current".
            capacity[key] = {
                "next_available_date": None,
                "capacity_1_2wk": None,
                "capacity_3_4wk": None,
                "on_leave": c["on_leave"].strip().upper() == "TRUE",
                "last_updated": last_updated_clean,
                "rolling_utilisation": None,
                "target_utilisation": None,
            }
        else:
            capacity[key] = {
                "next_available_date": c["next_available_date"] or None,
                "capacity_1_2wk": clean_capacity_field(c["capacity_1_2wk"]),
                "capacity_3_4wk": clean_capacity_field(c["capacity_3_4wk"]),
                "on_leave": c["on_leave"].strip().upper() == "TRUE",
                "last_updated": last_updated_clean,
                "rolling_utilisation": parse_utilisation_pct(c["rolling_utilisation_raw"]),
                "target_utilisation": clean_capacity_field(c["target_utilisation_raw"]),
            }

    return capacity, stale_duplicates, stale_rows


def main():
    lookup = load_suburb_lookup()
    service = get_sheets_service()

    roster = load_roster(service)
    capacity, stale_duplicates, stale_rows = load_capacity(service)

    clinicians = []
    unmatched_geo = []
    unmatched_capacity = []
    unmatched_roster_row = []  # capacity rows with no matching roster row

    for key, r in roster.items():
        lat, lon, match_type = None, None, "no address"
        if r["suburb"] and r["postcode"]:
            lat, lon, match_type = geocode(r["suburb"], r["postcode"], lookup)
        if lat is None:
            unmatched_geo.append({"name": r["name"], "suburb": r["suburb"], "postcode": r["postcode"]})

        cap = capacity.get(key)
        if cap is None:
            unmatched_capacity.append({"name": r["name"], "reason": "no matching row in Capacity tab — check the name matches Cliniko exactly"})

        on_leave = r["extended_leave"] or (cap["on_leave"] if cap else False)

        clinicians.append({
            "name": r["name"],
            "job_title": DISCIPLINE_JOB_TITLE.get(r["discipline_code"], r["discipline_code"] or "Unspecified"),
            "suburb": r["suburb"],
            "postcode": r["postcode"],
            "state": "NSW",
            "lat": lat,
            "lon": lon,
            "geocode_match": match_type,
            "discipline_code": r["discipline_code"],
            "next_available_date": cap["next_available_date"] if cap else None,
            "capacity_1_2wk": cap["capacity_1_2wk"] if cap else None,
            "capacity_3_4wk": cap["capacity_3_4wk"] if cap else None,
            "on_leave": on_leave,
            "last_updated": cap["last_updated"] if cap else None,
            "utilisation_pct": cap["rolling_utilisation"] if cap else None,
            "utilisation_target": cap["target_utilisation"] if cap else None,
            "status": "active",
        })

    roster_keys = set(roster.keys())
    for key, c in capacity.items():
        if key not in roster_keys:
            unmatched_roster_row.append({"capacity_tab_name": key})

    OUT_CLINICIANS.write_text(json.dumps(clinicians, indent=1), encoding="utf-8")

    report = {
        "total_clinicians": len(clinicians),
        "geocode_failures": unmatched_geo,
        "no_capacity_row": unmatched_capacity,
        "capacity_rows_with_no_roster_match": unmatched_roster_row,
        "stale_capacity_rows": stale_rows,
        "duplicate_capacity_rows": stale_duplicates,
    }
    OUT_REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    print(f"Wrote {len(clinicians)} clinicians to {OUT_CLINICIANS}")
    print(f"Geocode failures: {len(unmatched_geo)}")
    print(f"No capacity row (name mismatch or feed hasn't run for them yet): {len(unmatched_capacity)}")
    for u in unmatched_capacity:
        print(f"  - {u['name']}")
    if unmatched_roster_row:
        print(f"Capacity rows with no roster match: {len(unmatched_roster_row)} (likely someone not yet added to Roster tab)")
    if stale_duplicates:
        print(f"Duplicate capacity rows resolved by most-recent last_updated: {len(stale_duplicates)}")
        for d in stale_duplicates:
            print(f"  - {d['name']}: kept {d['kept_last_updated']}, discarded {d['discarded_last_updated']}")
    if stale_rows:
        print(f"Stale capacity rows (>{STALE_AFTER_HOURS}h old, treated as no data): {len(stale_rows)}")
        for s in stale_rows:
            print(f"  - {s['name']}: last updated {s['last_updated']} ({s['hours_old']}h ago)")


if __name__ == "__main__":
    main()

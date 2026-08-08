"""
Builds data/clinicians.json from the live Google Sheet (Roster + Capacity
tabs), replacing the old manual CSV/ODS workflow.

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
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent.parent
SUBURB_LOOKUP = ROOT / "data" / "nsw-suburbs.json"
OUT_CLINICIANS = ROOT / "data" / "clinicians.json"
OUT_REPORT = ROOT / "data" / "match-report.json"

SHEET_ID = os.environ.get("SHEET_ID", "1DAwxaGtHBZkxUnCaSxUzqZht4onqC98B2p5Qb85Vsag")
ROSTER_RANGE = "Roster!A2:E"
CAPACITY_RANGE = "Capacity!A2:F"

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


def load_capacity(service):
    rows = fetch_rows(service, CAPACITY_RANGE)
    capacity = {}
    for row in rows:
        row = row + [""] * (6 - len(row))
        name, next_avail, cap12, cap34, on_leave, last_updated = [c.strip() for c in row[:6]]
        if not name:
            continue
        capacity[norm_name(name)] = {
            "next_available_date": next_avail or None,
            "capacity_1_2wk": cap12 or None,
            "capacity_3_4wk": cap34 or None,
            "on_leave": on_leave.strip().upper() == "TRUE",
            "last_updated": last_updated or None,
        }
    return capacity


def main():
    lookup = load_suburb_lookup()
    service = get_sheets_service()

    roster = load_roster(service)
    capacity = load_capacity(service)

    clinicians = []
    unmatched_geo = []
    unmatched_capacity = []
    unmatched_roster_row = []

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
    }
    OUT_REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    print(f"Wrote {len(clinicians)} clinicians to {OUT_CLINICIANS}")
    print(f"Geocode failures: {len(unmatched_geo)}")
    print(f"No capacity row (name mismatch or feed hasn't run for them yet): {len(unmatched_capacity)}")
    for u in unmatched_capacity:
        print(f"  - {u['name']}")
    if unmatched_roster_row:
        print(f"Capacity rows with no roster match: {len(unmatched_roster_row)} (likely someone not yet added to Roster tab)")


if __name__ == "__main__":
    main()

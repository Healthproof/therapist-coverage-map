"""
Builds data/clinicians.json from:
  - data/clinician-addresses-raw.csv   (name, discipline, suburb, postcode)
  - data/capacity-raw.ods              (fortnightly 1-2wk / 3-4wk capacity, per clinician)
  - data/nsw-suburbs.json              (static suburb -> lat/lon lookup)

This is a ONE-TIME starter build from the files you gave me. Going forward,
the plan is for this same join to happen client-side in the browser against
a published Google Sheet CSV (see docs/UPDATING.md) — this script exists so
you have a working v1 today, and so you can re-run it later if you ever want
a fresh static snapshot instead.

Output: data/clinicians.json (used by the map)
        data/match-report.json (anything that needs a human look)

Usage:
    python3 scripts/build_clinicians.py
"""
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ADDR_CSV = ROOT / "data" / "clinician-addresses-raw.csv"
CAPACITY_ODS = ROOT / "data" / "capacity-raw.ods"
SUBURB_LOOKUP = ROOT / "data" / "nsw-suburbs.json"
OUT_CLINICIANS = ROOT / "data" / "clinicians.json"
OUT_REPORT = ROOT / "data" / "match-report.json"


def norm_suburb(s: str) -> str:
    s = s.upper().strip()
    s = re.sub(r"[^A-Z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def norm_lastname(s: str) -> str:
    # Strip accents/curly apostrophes etc so "Qi'En" vs "Qi’En" style
    # differences don't break matching.
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z]", "", s)
    return s.lower()


def load_suburb_lookup():
    with open(SUBURB_LOOKUP, encoding="utf-8") as f:
        return json.load(f)


def geocode(suburb: str, postcode: str, lookup: dict):
    key = f"{norm_suburb(suburb)}|{postcode}"
    if key in lookup:
        hit = lookup[key]
        return hit["lat"], hit["lon"], "postcode+suburb"
    # fall back to suburb name alone
    key2 = norm_suburb(suburb)
    if key2 in lookup:
        hit = lookup[key2]
        return hit["lat"], hit["lon"], "suburb only"
    return None, None, "no match"


def load_capacity():
    df = pd.read_excel(CAPACITY_ODS, engine="odf", sheet_name="Sheet1")
    df = df[["Discipline", "Clinician ", "1-2 week capacity ", "3-4 week Capacity"]]
    df = df.dropna(subset=["Clinician "])
    by_lastname = {}
    for _, row in df.iterrows():
        full_name = str(row["Clinician "]).strip()
        last = norm_lastname(full_name.split()[-1])
        by_lastname[last] = {
            "discipline_code": str(row["Discipline"]).strip(),
            "capacity_1_2wk": str(row["1-2 week capacity "]).strip(),
            "capacity_3_4wk": str(row["3-4 week Capacity"]).strip(),
            "on_leave": "leave" in str(row["1-2 week capacity "]).strip().lower()
            or "leave" in str(row["3-4 week Capacity"]).strip().lower(),
            "source_name": full_name,
        }
    return by_lastname


def main():
    lookup = load_suburb_lookup()
    capacity_by_lastname = load_capacity()

    clinicians = []
    unmatched_capacity = []
    unmatched_geo = []

    with open(ADDR_CSV, encoding="utf-8-sig") as f:
        import csv

        reader = csv.DictReader(f)
        for row in reader:
            first = row["First name"].strip()
            last = row["Last name"].strip()
            full_name = f"{first} {last}"
            job_title = row["Job title"].strip()
            suburb = row["Employee address suburb"].strip()
            postcode = row["Employee address postcode"].strip()
            state = row["Employee address state"].strip()

            lat, lon, match_type = geocode(suburb, postcode, lookup)
            if lat is None:
                unmatched_geo.append({"name": full_name, "suburb": suburb, "postcode": postcode})

            cap = capacity_by_lastname.get(norm_lastname(last))
            if cap is None:
                unmatched_capacity.append(
                    {"name": full_name, "job_title": job_title, "reason": "no row in this fortnight's capacity sheet"}
                )

            clinicians.append(
                {
                    "name": full_name,
                    "job_title": job_title,
                    "suburb": suburb,
                    "postcode": postcode,
                    "state": state,
                    "lat": lat,
                    "lon": lon,
                    "geocode_match": match_type,
                    "discipline_code": cap["discipline_code"] if cap else None,
                    "capacity_1_2wk": cap["capacity_1_2wk"] if cap else None,
                    "capacity_3_4wk": cap["capacity_3_4wk"] if cap else None,
                    "on_leave": cap["on_leave"] if cap else False,
                    "status": "active",
                }
            )

    OUT_CLINICIANS.write_text(json.dumps(clinicians, indent=1), encoding="utf-8")

    report = {
        "total_clinicians": len(clinicians),
        "geocode_failures": unmatched_geo,
        "no_capacity_row_this_fortnight": unmatched_capacity,
    }
    OUT_REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    print(f"Wrote {len(clinicians)} clinicians to {OUT_CLINICIANS}")
    print(f"Geocode failures: {len(unmatched_geo)}")
    print(f"No capacity row this fortnight: {len(unmatched_capacity)}")
    for u in unmatched_capacity:
        print(f"  - {u['name']} ({u['job_title']})")


if __name__ == "__main__":
    main()

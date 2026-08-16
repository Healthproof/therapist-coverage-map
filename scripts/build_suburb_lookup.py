"""
Builds data/nsw-suburbs.json — a static lookup of NSW suburb + postcode -> lat/lon.

Source: matthewproctor/australianpostcodes (public, MIT-licensed dataset of
Australian postcodes, derived from Australia Post data).

This only needs to be re-run if the source dataset is refreshed, or if the
team starts operating in a suburb that genuinely isn't covered (very unlikely
for greater Sydney / NSW). It is NOT part of the fortnightly update — that
happens in the Google Sheet, see docs/UPDATING.md.

Usage:
    python3 scripts/build_suburb_lookup.py
"""
import csv
import json
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent / "australian_postcodes.csv"
OUT = Path(__file__).resolve().parent / "nsw-suburbs.json"


def norm(s: str) -> str:
    """Normalise a suburb name for matching: uppercase, strip punctuation/whitespace."""
    s = s.upper().strip()
    s = re.sub(r"[^A-Z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def main():
    lookup = {}
    skipped = 0
    excluded_po_box = 0
    with open(SRC, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["state"] != "NSW":
                continue
            # Exclude non-residential postcode types — these aren't places
            # anyone lives or works, they just share a locality name with the
            # real delivery-area postcode:
            #   - "Post Office Boxes" (e.g. Castle Hill 1765 vs the real 2154)
            #   - "LVR" / Large Volume Receiver — corporate/government mail
            #     codes (e.g. Parramatta 1740/1741/2123 vs the real 2150)
            if row["type"] in ("Post Office Boxes", "LVR"):
                excluded_po_box += 1
                continue
            try:
                lat = float(row["lat"])
                lon = float(row["long"])
            except (ValueError, TypeError):
                skipped += 1
                continue
            if lat == 0 or lon == 0:
                skipped += 1
                continue

            suburb = row["locality"].strip()
            postcode = row["postcode"].strip()
            key = f"{norm(suburb)}|{postcode}"

            # A given suburb+postcode can appear more than once in the source
            # (delivery areas, etc). Keep the first — good enough for centroid use.
            if key not in lookup:
                lookup[key] = {
                    "suburb": suburb,
                    "postcode": postcode,
                    "lat": lat,
                    "lon": lon,
                }

            # Also index by suburb name alone (first NSW postcode wins) so the
            # search box can work off a typed suburb with no postcode.
            suburb_only_key = norm(suburb)
            if suburb_only_key not in lookup:
                lookup[suburb_only_key] = {
                    "suburb": suburb,
                    "postcode": postcode,
                    "lat": lat,
                    "lon": lon,
                }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(lookup, f, indent=1)

    print(f"Wrote {len(lookup)} entries to {OUT}")
    print(f"Skipped {skipped} rows with missing/zero coordinates")
    print(f"Excluded {excluded_po_box} PO-Box-only rows")


if __name__ == "__main__":
    main()

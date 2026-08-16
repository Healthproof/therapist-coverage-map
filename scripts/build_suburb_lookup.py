"""
Builds data/nsw-suburbs.json — a static lookup of Greater Sydney suburb +
postcode -> lat/lon, restricted to the region clinicians actually operate
in (so a Sydney suburb name never collides with an unrelated regional NSW
town that happens to share the name).

Source: matthewproctor/australianpostcodes (public, MIT-licensed dataset of
Australian postcodes, derived from Australia Post data).

This only needs to be re-run if the source dataset is refreshed, or if the
team starts operating in a suburb that genuinely isn't covered. It is NOT
part of the fortnightly update — that happens in the Google Sheet, see
docs/UPDATING.md.

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
    excluded_non_residential = 0
    excluded_non_sydney = 0
    with open(SRC, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["state"] != "NSW":
                continue

            postcode = row["postcode"].strip()

            # Exclude non-residential postcodes — these aren't places anyone
            # lives or works, they just share a locality name with the real
            # delivery-area postcode:
            #   - "Post Office Boxes" / "LVR" (Large Volume Receiver) — the
            #     source's own "type" tag, where it's populated
            #   - ANY postcode in the 1000-1999 range — by Australia Post's
            #     own numbering, this range is always reserved for LVR/PO
            #     Box codes, never a real delivery area. This catches rows
            #     where "type" itself is blank in the source data (e.g.
            #     Woollahra 1350, Kogarah 1485 both had no type tag at all,
            #     so the type-only check missed them).
            if row["type"] in ("Post Office Boxes", "LVR") or postcode.startswith("1"):
                excluded_non_residential += 1
                continue

            # Restrict to Greater Sydney (SA4 regions starting "Sydney - ")
            # AND the "R1 - Major City" remoteness classification. SA4 name
            # alone isn't quite enough — e.g. a "Dural" postcode (2330) is
            # tagged under the Sydney SA4 but is actually R3 (outer
            # regional), a genuinely different, distant locality that just
            # shares a name and an odd SA4 boundary quirk with the real
            # Dural (2158, R1) in northwest Sydney.
            if not row["sa4name"].startswith("Sydney") or row["region"] != "R1":
                excluded_non_sydney += 1
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

            # Also index by suburb name alone (first Sydney postcode wins) so
            # the search box can work off a typed suburb with no postcode.
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
    print(f"Excluded {excluded_non_residential} non-residential (PO Box/LVR/1xxx) rows")
    print(f"Excluded {excluded_non_sydney} rows outside Greater Sydney")


if __name__ == "__main__":
    main()


#!/usr/bin/env python
"""Build ``data/us_places.json``: a US place -> centroid lookup used to resolve start and
finish locations **offline**, so a typical "City, ST" request needs no geocoding call at all.

Source: the US Census Gazetteer ``place`` + ``county subdivision`` national files (public
domain, one download each).  Run once:

    python scripts/build_us_places.py
"""

from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from routing.services.place_names import US_STATES, normalize_place  # noqa: E402

OUT = ROOT / "data" / "us_places.json"
BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer"
USER_AGENT = "spotter-fuel-route/1.0 (gazetteer build)"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def main() -> None:
    places: dict[str, list[float]] = {}

    for kind in ("place", "cousubs"):
        blob = None
        for year in ("2024", "2023", "2022"):
            try:
                blob = fetch(f"{BASE}/{year}_Gazetteer/{year}_Gaz_{kind}_national.zip")
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {kind} {year}: {exc}")
        if blob is None:
            raise SystemExit(f"could not download the {kind} gazetteer")

        inner = zipfile.ZipFile(io.BytesIO(blob))
        member = next(n for n in inner.namelist() if n.lower().endswith(".txt"))
        text = inner.read(member).decode("utf-8", "replace")

        for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
            record = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            state = record.get("USPS", "").upper()
            raw_name = record.get("NAME", "")
            city = normalize_place(raw_name)
            if state not in US_STATES or not city:
                continue
            try:
                coords = [
                    round(float(record["INTPTLAT"].replace("+", "")), 6),
                    round(float(record["INTPTLONG"].split()[0]), 6),
                ]
            except (KeyError, ValueError):
                continue
            places.setdefault(f"{city}|{state}", coords)
            # Consolidated city-county names ("Nashville-Davidson metropolitan ...") are
            # colloquially just the first half, so index that too.
            if "-" in raw_name:
                alias = normalize_place(raw_name.split("-")[0])
                if alias:
                    places.setdefault(f"{alias}|{state}", coords)

        print(f"  + {kind}: {len(places)} places so far")

    OUT.write_text(json.dumps(places, separators=(",", ":"), sort_keys=True))
    print(f"wrote {OUT.name}: {len(places)} places, {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

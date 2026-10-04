#!/usr/bin/env python
"""Build ``data/place_coords.json``: coordinates for every (city, state) in the fuel CSV.

Sources, both free and keyless:

1. **US Census Gazetteer** (public domain) - "place" and "county subdivision" national
   files, one HTTP download each.  Covers ~95%+ of the truck-stop towns.
2. **Nominatim** (OpenStreetMap) - fallback for the small remainder, rate limited to
   1 request/second per the OSM usage policy and cached in ``data/nominatim_cache.json``
   so re-runs and CI cost zero network calls.

Run once (or whenever the CSV changes)::

    python scripts/build_place_coords.py

The generated file is committed so that the Django app itself never needs network
access to resolve a fuel station's position.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "fuel-prices-for-be-assessment.csv"
DATA_DIR = ROOT / "data"
OUT_PATH = DATA_DIR / "place_coords.json"
CACHE_PATH = DATA_DIR / "nominatim_cache.json"

GAZETTEER_BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "spotter-fuel-route/1.0 (gazetteer build)"
REQUESTS_TIMEOUT = 120
NOMINATIM_DELAY_SECONDS = 1.1

# The project root is put on the path so this standalone script and the Django app share
# exactly one definition of place-name normalisation.
sys.path.insert(0, str(ROOT))

from routing.services.place_names import US_STATES  # noqa: E402
from routing.services.place_names import normalize_place as normalize  # noqa: E402


def http_get(url: str, params: dict | None = None) -> bytes:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUESTS_TIMEOUT) as response:
        return response.read()


def load_csv_pairs() -> list[tuple[str, str, str]]:
    """Return (normalized_city, STATE, raw_city) for every US row in the CSV."""
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    seen: dict[tuple[str, str], str] = {}
    for row in rows:
        state = row["State"].strip().upper()
        raw_city = row["City"].strip()
        if state not in US_STATES:
            continue
        seen.setdefault((normalize(raw_city), state), raw_city)
    return [(key[0], key[1], raw) for key, raw in seen.items()]


def gazetteer_coords() -> dict[tuple[str, str], list[float]]:
    """Merge the Census place + county-subdivision gazetteers into one lookup."""
    coords: dict[tuple[str, str], list[float]] = {}
    for kind in ("place", "cousubs"):
        text = None
        for year in ("2024", "2023", "2022"):
            url = f"{GAZETTEER_BASE}/{year}_Gazetteer/{year}_Gaz_{kind}_national.zip"
            try:
                blob = http_get(url)
            except Exception as exc:  # noqa: BLE001 - try the next year
                print(f"  ! {kind} {year} download failed: {exc}")
                continue
            inner = zipfile.ZipFile(io.BytesIO(blob))
            member = next(n for n in inner.namelist() if n.lower().endswith(".txt"))
            text = inner.read(member).decode("utf-8", "replace")
            print(f"  + {kind} {year}: {len(blob):,} bytes")
            break
        if text is None:
            raise SystemExit(f"could not download {kind} gazetteer")
        for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
            rec = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            state = rec.get("USPS", "").upper()
            if state not in US_STATES:
                continue
            key = (normalize(rec.get("NAME", "")), state)
            if not key[0]:
                continue
            try:
                lat = float(rec["INTPTLAT"].replace("+", ""))
                lon = float(rec["INTPTLONG"].split()[0])
            except (KeyError, ValueError):
                continue
            # first writer wins: place file before cousub, larger names first within a file
            coords.setdefault(key, [round(lat, 6), round(lon, 6)])
    return coords


def nominatim_lookup(city: str, state: str, cache: dict) -> list[float] | None:
    key = f"{city}|{state}"
    if key in cache:
        return cache[key]
    try:
        blob = http_get(
            NOMINATIM_URL,
            {
                "q": f"{city}, {state}, USA",
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "us",
            },
        )
        hits = json.loads(blob)
    except Exception as exc:  # noqa: BLE001
        print(f"    - nominatim failed for {city}, {state}: {exc}")
        hits = []
    time.sleep(NOMINATIM_DELAY_SECONDS)  # OSM usage policy
    result = (
        [round(float(hits[0]["lat"]), 6), round(float(hits[0]["lon"]), 6)]
        if hits
        else None
    )
    cache[key] = result
    return result


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    pairs = load_csv_pairs()
    print(f"US (city, state) pairs to resolve: {len(pairs)}")

    coords = gazetteer_coords()
    resolved = sum(1 for city, state, _ in pairs if (city, state) in coords)
    print(f"  -> gazetteer resolved {resolved}/{len(pairs)}")

    cache: dict = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    missing = [(c, s, raw) for c, s, raw in pairs if (c, s) not in coords]
    print(f"  -> resolving {len(missing)} remaining via Nominatim (cached: {len(cache)})")

    for index, (city, state, raw) in enumerate(missing, start=1):
        hit = nominatim_lookup(raw, state, cache)
        if hit:
            coords[(city, state)] = hit
        print(f"    [{index}/{len(missing)}] {raw}, {state} -> {hit}", flush=True)

    CACHE_PATH.write_text(json.dumps(cache, indent=0, sort_keys=True))
    payload = {
        f"{city}|{state}": coords[(city, state)]
        for city, state, _ in pairs
        if (city, state) in coords
    }
    OUT_PATH.write_text(json.dumps(payload, indent=0, sort_keys=True))
    ratio = 100 * len(payload) / len(pairs)
    print(f"\nwrote {OUT_PATH}  ({len(payload)}/{len(pairs)} = {ratio:.1f}% coverage)")


if __name__ == "__main__":
    main()

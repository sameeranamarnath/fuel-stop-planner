"""Import the OPIS truck-stop price CSV into the ``FuelStation`` table.

Coordinates come from ``data/place_coords.json`` (built offline by
``scripts/build_place_coords.py``), so this command needs **no network access**::

    python manage.py load_fuel_prices
    python manage.py load_fuel_prices --csv other.csv --coords other.json

Rows outside the USA, or whose city could not be resolved to coordinates, are skipped
and reported.  Where the same ``OPIS Truckstop ID`` appears more than once, the lowest
listed retail price wins.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from routing.models import FuelStation
from routing.services.place_names import US_STATES, coord_key
from routing.services.planner import reset_station_cache

DEFAULT_CSV_NAME = "fuel-prices-for-be-assessment.csv"

UPDATE_FIELDS = [
    "name", "address", "city", "state", "rack_id", "price", "latitude", "longitude",
]


class Command(BaseCommand):
    help = "Load truck stop fuel prices from the OPIS CSV into the database."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=None, help="Path to the OPIS price CSV.")
        parser.add_argument(
            "--coords", default=None, help="Path to place_coords.json."
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv"] or settings.BASE_DIR / DEFAULT_CSV_NAME)
        coords_path = Path(
            options["coords"] or settings.SPOTTER["PLACE_COORDS_PATH"]
        )

        if not csv_path.exists():
            raise CommandError(f"Price CSV not found: {csv_path}")
        if not coords_path.exists():
            raise CommandError(
                f"Coordinate file not found: {coords_path}. "
                "Run 'python scripts/build_place_coords.py' first."
            )

        coordinates = json.loads(coords_path.read_text())
        stations, stats = self._read(csv_path, coordinates)

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(
                [FuelStation(**record) for record in stations.values()],
                batch_size=1000,
            )

        reset_station_cache()

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(stations)} fuel stations "
                f"(skipped {stats['non_us']} non-US rows, "
                f"{stats['no_coords']} rows without coordinates, "
                f"{stats['duplicates']} duplicate prices, "
                f"{stats['bad_price']} unparsable)."
            )
        )

    def _read(self, csv_path: Path, coordinates: dict) -> tuple[dict, dict]:
        stats = {"non_us": 0, "no_coords": 0, "duplicates": 0, "bad_price": 0}
        stations: dict[str, dict] = {}

        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                state = (row.get("State") or "").strip().upper()
                city = (row.get("City") or "").strip()
                if state not in US_STATES:
                    stats["non_us"] += 1
                    continue

                pair = coordinates.get(coord_key(city, state))
                if not pair:
                    stats["no_coords"] += 1
                    continue

                opis_id = (row.get("OPIS Truckstop ID") or "").strip()
                if not opis_id:
                    continue
                try:
                    price = float(row.get("Retail Price") or "")
                except ValueError:
                    stats["bad_price"] += 1
                    continue

                current = stations.get(opis_id)
                if current is not None:
                    stats["duplicates"] += 1
                    if current["price"] <= price:
                        continue

                stations[opis_id] = {
                    "opis_id": opis_id,
                    "name": (row.get("Truckstop Name") or "").strip()[:255],
                    "address": (row.get("Address") or "").strip()[:255],
                    "city": city[:120],
                    "state": state,
                    "rack_id": (row.get("Rack ID") or "").strip()[:32],
                    "price": price,
                    "latitude": float(pair[0]),
                    "longitude": float(pair[1]),
                }

        return stations, stats

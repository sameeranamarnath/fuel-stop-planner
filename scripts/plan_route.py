#!/usr/bin/env python
"""Run one fuel plan end-to-end and print a human-readable summary.

    python scripts/demo_plan.py "New York, NY" "Los Angeles, CA"
    python scripts/demo_plan.py 40.7128 -74.006 34.0522 -118.2437   # coords, no geocoding

Handy as a CLI sanity check - the HTTP API is the actual deliverable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from routing.exceptions import PlannerError  # noqa: E402
from routing.services.planner import build_fuel_plan  # noqa: E402


def parse(arguments: list[str]):
    if len(arguments) == 2:
        return arguments[0], arguments[1]
    if len(arguments) == 4:
        lat1, lon1, lat2, lon2 = (float(value) for value in arguments)
        return {"lat": lat1, "lon": lon1}, {"lat": lat2, "lon": lon2}
    raise SystemExit(
        f'usage: {sys.argv[0]} "Start, ST" "Finish, ST"   |   lat lon lat lon'
    )


def main() -> None:
    start, finish = parse(sys.argv[1:])
    try:
        plan = build_fuel_plan(start, finish)
    except PlannerError as error:
        print(f"{error.code}: {error.detail}")
        return
    summary = plan["summary"]
    calls = plan["external_api_calls"]
    vehicle = plan["vehicle"]

    print(f"Route     : {plan['start']['label']}  ->  {plan['finish']['label']}")
    print(
        f"Distance  : {summary['total_distance_miles']} mi "
        f"({plan['route']['duration_hours']} h drive, via {plan['route']['provider']})"
    )
    print(
        f"Vehicle   : {vehicle['max_range_miles']:.0f} mi range, {vehicle['mpg']:.0f} MPG, "
        f"{vehicle['tank_capacity_gallons']:.0f} gal tank"
    )
    print(
        f"API calls : {calls['external_calls_total']} "
        f"(geocoding {calls['geocoding_calls']}, routing {calls['routing_calls']}) "
        f"in {plan['elapsed_ms']} ms"
    )
    print()

    if plan["fuel_stops"]:
        print(f"{'#':>2}  {'mile':>6}  {'price':>6}  {'gal':>6}  {'cost':>8}  station")
        for stop in plan["fuel_stops"]:
            print(
                f"{stop['sequence']:>2}  {stop['distance_from_start_miles']:>6.0f}  "
                f"{stop['price_per_gallon']:>6.3f}  {stop['gallons_purchased']:>6.1f}  "
                f"{stop['cost_usd']:>8.2f}  {stop['name']} "
                f"({stop['city']}, {stop['state']})"
            )
        print()
    else:
        print("No refuelling needed - the initial full tank covers this trip.\n")

    print(f"Fuel consumed  : {summary['total_gallons_consumed']} gal")
    print(
        f"Fuel purchased : {summary['total_gallons_purchased']} gal"
        + (
            f" @ avg ${summary['average_price_per_gallon']}"
            if summary["average_price_per_gallon"]
            else ""
        )
    )
    print(f"TOTAL FUEL COST: ${summary['total_fuel_cost_usd']}")


if __name__ == "__main__":
    main()

"""End-to-end fuel planning: resolve locations -> route -> match stations -> optimise.

This module is the only place that talks to the outside world, and it does so at most
once per unique origin/destination pair.  Everything else (spatial matching, the cost
optimiser, geometry) runs locally against the pre-loaded station table.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from django.conf import settings

from routing.exceptions import RequestValidationError, RouteInfeasible
from routing.models import FuelStation, GeocodeCache, RouteCache
from routing.services import gazetteer, geo, matching, providers
from routing.services.optimizer import FuelPlan, optimize_fuel_stops
from routing.services.providers import Place

logger = logging.getLogger(__name__)

# Generous bounding box covering the lower 48, Alaska and Hawaii.
US_BOUNDS = {"min_lat": 18.0, "max_lat": 72.0, "min_lon": -180.0, "max_lon": -65.0}


@dataclass
class CallCounter:
    """Tracks how many *upstream* calls a single request had to make."""

    geocoding: int = 0
    routing: int = 0
    geocoding_cache_hits: int = 0
    routing_cache_hits: int = 0

    def as_dict(self) -> dict:
        return {
            "geocoding_calls": self.geocoding,
            "routing_calls": self.routing,
            "geocoding_cache_hits": self.geocoding_cache_hits,
            "routing_cache_hits": self.routing_cache_hits,
            "external_calls_total": self.geocoding + self.routing,
        }


_STATION_CACHE: tuple[dict, ...] | None = None


def all_stations() -> tuple[dict, ...]:
    """Load the full station table once and keep it in memory (~6.6k small rows).

    Returned as a tuple so a caller cannot reorder or corrupt the shared cache.
    """
    global _STATION_CACHE
    if _STATION_CACHE is None:
        _STATION_CACHE = tuple(
            FuelStation.objects.values(
                "id", "name", "address", "city", "state", "price",
                "latitude", "longitude",
            )
        )
        logger.info("Loaded %d fuel stations into memory", len(_STATION_CACHE))
    return _STATION_CACHE


def reset_station_cache() -> None:
    """Drop the in-memory station cache (used after re-importing prices and in tests)."""
    global _STATION_CACHE
    _STATION_CACHE = None


def _validate_coordinates(latitude: float, longitude: float, label: str) -> None:
    if not (US_BOUNDS["min_lat"] <= latitude <= US_BOUNDS["max_lat"]):
        raise RequestValidationError(f"{label} latitude {latitude} is outside the USA.")
    if not (US_BOUNDS["min_lon"] <= longitude <= US_BOUNDS["max_lon"]):
        raise RequestValidationError(f"{label} longitude {longitude} is outside the USA.")


def resolve_place(spec, counter: CallCounter, role: str) -> dict:
    """Turn a request location into ``{latitude, longitude, label}``.

    Accepts either an explicit ``{"lat": .., "lon": ..}`` pair - which costs **zero** API
    calls - or a free-text US place name that is geocoded once and then cached.
    """
    if isinstance(spec, dict):
        try:
            latitude = float(spec["lat"])
            longitude = float(spec["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RequestValidationError(
                f"{role} coordinates must be given as {{'lat': <float>, 'lon': <float>}}."
            ) from exc
        _validate_coordinates(latitude, longitude, role)
        return {
            "latitude": latitude,
            "longitude": longitude,
            "label": spec.get("label") or f"{latitude:.4f}, {longitude:.4f}",
            "source": "coordinates",
        }

    query = str(spec or "").strip()
    if not query:
        raise RequestValidationError(f"{role} location must not be empty.")
    cache_key = " ".join(query.lower().split())

    # 1. Bundled gazetteer.  "City, ST" resolves locally, so the whole request needs no
    #    geocoding call at all - it is then served by the single routing call.
    local = gazetteer.lookup(query)
    if local is not None:
        _validate_coordinates(local.latitude, local.longitude, role)
        return {
            "latitude": local.latitude,
            "longitude": local.longitude,
            "label": local.label,
            "source": "gazetteer",
        }

    # 2. Anything already geocoded by the provider on an earlier request.
    if settings.SPOTTER["CACHE_ENABLED"]:
        cached = GeocodeCache.objects.filter(query=cache_key).first()
        if cached:
            counter.geocoding_cache_hits += 1
            return {
                "latitude": cached.latitude,
                "longitude": cached.longitude,
                "label": cached.label or query,
                "source": "cache",
            }

    counter.geocoding += 1
    geocoder = providers.get_geocoder()
    place = geocoder.geocode(query)
    _validate_coordinates(place.latitude, place.longitude, role)

    if settings.SPOTTER["CACHE_ENABLED"]:
        GeocodeCache.objects.update_or_create(
            query=cache_key,
            defaults={
                "label": place.label,
                "latitude": place.latitude,
                "longitude": place.longitude,
                "provider": geocoder.name,
            },
        )
    return {
        "latitude": place.latitude,
        "longitude": place.longitude,
        "label": place.label or query,
        "source": "provider",
    }


def _route_cache_key(origin: dict, destination: dict, provider_name: str) -> str:
    return (
        f"{provider_name}:{origin['latitude']:.4f},{origin['longitude']:.4f}"
        f"->{destination['latitude']:.4f},{destination['longitude']:.4f}"
    )


def load_route(origin: dict, destination: dict, counter: CallCounter) -> dict:
    """Return the route polyline, from the cache whenever possible.

    This is the *single* upstream routing call made per unique origin/destination pair.
    """
    router = providers.get_router()
    key = _route_cache_key(origin, destination, router.name)

    if settings.SPOTTER["CACHE_ENABLED"]:
        cached = RouteCache.objects.filter(key=key).first()
        if cached:
            counter.routing_cache_hits += 1
            return {
                "points": cached.geometry,
                "distance_meters": cached.distance_meters,
                "duration_seconds": cached.duration_seconds,
                "provider": cached.provider,
            }

    counter.routing += 1
    result = router.route(
        Place(origin["latitude"], origin["longitude"], origin["label"]),
        Place(destination["latitude"], destination["longitude"], destination["label"]),
    )
    raw_points = result.points
    points, _ = geo.resample(
        raw_points,
        geo.cumulative_miles(raw_points),
        settings.SPOTTER["GEOMETRY_SPACING_MILES"],
    )

    if settings.SPOTTER["CACHE_ENABLED"]:
        RouteCache.objects.update_or_create(
            key=key,
            defaults={
                "origin_label": origin["label"][:255],
                "destination_label": destination["label"][:255],
                "distance_meters": result.distance_meters,
                "duration_seconds": result.duration_seconds,
                "provider": result.provider,
                "geometry": points,
            },
        )

    return {
        "points": points,
        "distance_meters": result.distance_meters,
        "duration_seconds": result.duration_seconds,
        "provider": result.provider,
    }


def assumptions() -> list[str]:
    """Human-readable statement of every modelling assumption baked into the result."""
    config = settings.SPOTTER
    tank_gallons = config["MAX_RANGE_MILES"] / config["MPG"]
    statements = [
        f"Vehicle range is {config['MAX_RANGE_MILES']:.0f} miles on a full "
        f"{tank_gallons:.0f}-gallon tank at {config['MPG']:.0f} MPG.",
        "The vehicle departs with a full tank; the fuel already on board when the trip "
        "starts is treated as a sunk cost and is not part of the trip spend.",
        f"Fuel is only bought at OPIS truck stops within "
        f"{config['STATION_OFFSET_MILES']:.0f} miles of the route.",
        "Where a truckstop id appears more than once in the price file, the lowest "
        "listed retail price is kept.",
        "Distances are geodesic lengths along the routing provider's polyline.",
    ]
    if config["MIN_PRICE_ADVANTAGE_PER_GALLON"] > 0:
        statements.append(
            "A station is only treated as cheaper when it beats the current price by at "
            f"least ${config['MIN_PRICE_ADVANTAGE_PER_GALLON']:.2f} per gallon, which "
            "keeps the plan free of sub-gallon top-ups."
        )
    return statements


def _optimise(
    points: list[list[float]],
    cumulative: list[float],
    total_miles: float,
    config: dict,
) -> tuple[FuelPlan, int]:
    """Match the station catalogue to the route and pick the cheapest refuelling plan.

    Also returns how many stations the route passed within range of, which the response
    reports so a caller can sanity-check the coverage behind the plan.
    """
    matched = matching.match_stations_to_route(
        points, cumulative, all_stations(), config["STATION_OFFSET_MILES"]
    )
    # Adjacent stops compete for the same purchase, and chasing the cheapest of them
    # produces sub-gallon top-ups.  Collapse each stretch of the route to its cheapest
    # station first: near-identical cost, far fewer stops.
    on_route = matching.thin_candidates(
        matched,
        config["MIN_STATION_SPACING_MILES"],
        max_gap_miles=config["MAX_RANGE_MILES"],
    )
    # The matcher reports the route mile-marker as "route_mile"; the optimiser consumes the
    # generic "mile" key and carries the rest of the station dict through untouched.
    candidates = [{**station, "mile": station["route_mile"]} for station in on_route]
    plan = optimize_fuel_stops(
        candidates=candidates,
        total_miles=total_miles,
        max_range_miles=config["MAX_RANGE_MILES"],
        mpg=config["MPG"],
        initial_fuel_fraction=config["INITIAL_FUEL_FRACTION"],
        min_price_advantage=config["MIN_PRICE_ADVANTAGE_PER_GALLON"],
    )
    if not plan.feasible:
        raise RouteInfeasible(
            plan.reason, extra={"route_distance_miles": round(total_miles, 1)}
        )
    return plan, len(matched)


def _stop_record(sequence: int, stop: FuelStop) -> dict:
    """Shape one optimiser stop into the flat record the API returns."""
    station = stop.station
    return {
        "sequence": sequence,
        "truckstop_id": station.get("id"),
        "name": station.get("name"),
        "city": station.get("city"),
        "state": station.get("state"),
        "address": station.get("address"),
        "price_per_gallon": round(stop.price, 3),
        "distance_from_start_miles": round(stop.route_mile, 1),
        "distance_to_route_miles": station.get("offset_miles"),
        "latitude": station.get("latitude"),
        "longitude": station.get("longitude"),
        "gallons_purchased": stop.gallons,
        "cost_usd": stop.cost,
        "tank_after_gallons": stop.tank_after_gallons,
    }


def _stop_feature(record: dict) -> dict | None:
    """GeoJSON point for a stop, or ``None`` when the station has no usable coordinates."""
    if record["latitude"] is None or record["longitude"] is None:
        return None
    return {
        "type": "Feature",
        "properties": {key: value for key, value in record.items() if key != "sequence"},
        "geometry": {
            "type": "Point",
            "coordinates": [record["longitude"], record["latitude"]],
        },
    }


def _summary(plan: FuelPlan, total_miles: float, stops: list[dict], considered: int) -> dict:
    """Trip totals, including the blended price actually paid per gallon."""
    purchased = plan.total_gallons_purchased
    return {
        "total_distance_miles": round(total_miles, 1),
        "total_gallons_consumed": round(plan.total_gallons_consumed, 2),
        "total_gallons_purchased": round(purchased, 2),
        "total_fuel_cost_usd": round(plan.total_cost, 2),
        "average_price_per_gallon": (
            round(plan.total_cost / purchased, 3) if purchased > 0 else None
        ),
        "number_of_fuel_stops": len(stops),
        "stations_considered_on_route": considered,
        "feasible": True,
    }


def _payload(
    origin: dict,
    destination: dict,
    route: dict,
    points: list[list[float]],
    cumulative: list[float],
    total_miles: float,
    plan: FuelPlan,
    considered: int,
    config: dict,
) -> dict:
    """Assemble the response body from the pipeline's results."""
    # Keep the response small: a very long route gets a coarser output polyline rather than
    # thousands of vertices.  Station matching has already run against the fine polyline, so
    # this only affects what the map draws.
    output_spacing = max(
        config["OUTPUT_GEOMETRY_SPACING_MILES"],
        total_miles / max(1.0, config["MAX_OUTPUT_GEOMETRY_POINTS"]),
    )
    output_points, _ = geo.resample(points, cumulative, output_spacing)
    # Serialised once and shared by the route block and the FeatureCollection below, rather
    # than building the same LineString twice.
    linestring = geo.to_geojson_linestring(output_points)

    stops = [
        _stop_record(sequence, stop) for sequence, stop in enumerate(plan.stops, start=1)
    ]
    features = [_stop_feature(record) for record in stops]

    return {
        "start": origin,
        "finish": destination,
        "vehicle": {
            "max_range_miles": config["MAX_RANGE_MILES"],
            "mpg": config["MPG"],
            "tank_capacity_gallons": round(config["MAX_RANGE_MILES"] / config["MPG"], 2),
            "initial_fuel_fraction": config["INITIAL_FUEL_FRACTION"],
        },
        "route": {
            "provider": route["provider"],
            "distance_miles": round(total_miles, 1),
            "provider_distance_miles": round(
                route["distance_meters"] / geo.METERS_PER_MILE, 1
            ),
            "duration_hours": round(route["duration_seconds"] / 3600.0, 2),
            "geometry": linestring,
            "bounds": geo.bounds(output_points),
            "polyline_points": len(output_points),
        },
        "fuel_stops": stops,
        "summary": _summary(plan, total_miles, stops, considered),
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"kind": "route"},
                    "geometry": linestring,
                },
                *(feature for feature in features if feature is not None),
            ],
        },
    }


def build_fuel_plan(start_spec, finish_spec) -> dict:
    """Run the full pipeline for one request and return the API payload."""
    started = time.perf_counter()
    counter = CallCounter()
    config = settings.SPOTTER

    origin = resolve_place(start_spec, counter, "start")
    destination = resolve_place(finish_spec, counter, "finish")

    route = load_route(origin, destination, counter)
    points = route["points"]
    cumulative = geo.cumulative_miles(points)
    total_miles = cumulative[-1] if cumulative else 0.0
    if total_miles < 1e-6:
        raise RequestValidationError("Start and finish resolve to the same point.")

    plan, considered = _optimise(points, cumulative, total_miles, config)

    payload = _payload(
        origin,
        destination,
        route,
        points,
        cumulative,
        total_miles,
        plan,
        considered,
        config,
    )
    payload["assumptions"] = assumptions()
    payload["external_api_calls"] = counter.as_dict()
    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return payload


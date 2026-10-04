"""Match fuel stations to a route polyline using a spatial hash grid.

The naive "every station against every route vertex" comparison is O(S x R) and, for a
cross-country route, tens of millions of distance calculations.  Instead the route is
bucketed into a grid whose cell size is derived from the allowed offset, so each station
only ever compares against the handful of route vertices in its own cell and its eight
neighbours.  That makes matching effectively linear in the number of stations.

Two details keep the inner loop cheap:

* the comparison uses :func:`geo.chord_term`, which orders candidates exactly as the
  great-circle distance does but needs no trigonometry, so only the winning vertex is
  measured properly; and
* the grid is sized from the route's own latitude span, because a degree of longitude
  shrinks from ~53 miles at 40N to ~21 at Anchorage.  Sizing it from a fixed constant
  either over-scans in the south or (worse) misses stations in the far north.
"""

from __future__ import annotations

import math

from routing.services import geo

# A degree of longitude is never treated as smaller than this many miles, which keeps the
# grid finite in pathological inputs.  The real value is ~21 miles at 72N.
MIN_MILES_PER_DEGREE_LON = 1.0


def _cell(latitude: float, longitude: float, size: float) -> tuple[int, int]:
    return int(math.floor(latitude / size)), int(math.floor(longitude / size))


def _grid_scale(points: list[list[float]]) -> tuple[float, float]:
    """Degrees-per-mile on the latitude and longitude axes, worst case for this route.

    The worst case is the most extreme latitude the route reaches, where a degree of
    longitude is shortest.
    """
    extreme_latitude = max(abs(point[0]) for point in points)
    longitude_scale = geo.MILES_PER_DEGREE_LAT * math.cos(math.radians(extreme_latitude))
    return geo.MILES_PER_DEGREE_LAT, max(MIN_MILES_PER_DEGREE_LON, longitude_scale)


def match_stations_to_route(
    route_points: list[list[float]],
    route_cum: list[float],
    stations: list[dict],
    max_offset_miles: float,
) -> list[dict]:
    """Return ``stations`` annotated with the mile-marker of their closest route point.

    Stations further than ``max_offset_miles`` from the route are dropped.  The result is
    sorted by ``route_mile`` so the optimiser can consume it directly.
    """
    if not route_points or not stations:
        return []

    latitude_scale, longitude_scale = _grid_scale(route_points)
    # A cell must span at least `max_offset` miles on the tighter axis.  Otherwise a
    # station sitting near a cell edge could be more than one cell away from a route
    # vertex it is genuinely within range of, and the 3x3 neighbourhood would miss it.
    cell_size = max(max_offset_miles, 0.5) / longitude_scale
    latitude_pad = max_offset_miles / latitude_scale
    longitude_pad = max_offset_miles / longitude_scale

    latitudes = [point[0] for point in route_points]
    longitudes = [point[1] for point in route_points]
    min_latitude = min(latitudes) - latitude_pad
    max_latitude = max(latitudes) + latitude_pad
    min_longitude = min(longitudes) - longitude_pad
    max_longitude = max(longitudes) + longitude_pad

    # These depend only on the route, so they are computed once for the whole request
    # rather than once per station comparison.
    vertex_terms = [geo.trig_terms(lat, lon) for lat, lon in route_points]

    grid: dict[tuple[int, int], list[int]] = {}
    for index, (lat, lon) in enumerate(route_points):
        grid.setdefault(_cell(lat, lon, cell_size), []).append(index)

    matches: list[dict] = []
    for station in stations:
        latitude = station["latitude"]
        longitude = station["longitude"]
        if not (
            min_latitude <= latitude <= max_latitude
            and min_longitude <= longitude <= max_longitude
        ):
            continue

        station_terms = geo.trig_terms(latitude, longitude)
        base_row, base_column = _cell(latitude, longitude, cell_size)
        best_index = None
        best_term = math.inf
        for row in (base_row - 1, base_row, base_row + 1):
            for column in (base_column - 1, base_column, base_column + 1):
                for index in grid.get((row, column), ()):  # empty tuple == nothing to do
                    term = geo.chord_term(station_terms, vertex_terms[index])
                    if term < best_term:
                        best_term = term
                        best_index = index
        if best_index is None:
            continue

        # chord_term only ranks the candidates, so measure the winner for real.
        nearest = route_points[best_index]
        offset_miles = geo.haversine_miles(latitude, longitude, nearest[0], nearest[1])
        if offset_miles <= max_offset_miles:
            matches.append(
                {
                    **station,
                    "route_mile": route_cum[best_index],
                    "offset_miles": round(offset_miles, 3),
                }
            )

    matches.sort(key=lambda match: match["route_mile"])
    return matches



def thin_candidates(
    matches: list[dict],
    spacing_miles: float,
    max_gap_miles: float | None = None,
) -> list[dict]:
    """Keep only the cheapest station in each ``spacing_miles`` stretch of the route.

    Truck stops cluster - it is common to find three within twenty miles.  Left alone,
    the optimiser buys a gallon or two at each of them to shave fractions of a cent off
    the bill, which is technically cost-optimal but produces an unusable itinerary.
    Collapsing each stretch to its cheapest station removes those micro-stops (and shrinks
    the optimiser's input) for a negligible change in total cost.

    If thinning would leave a gap longer than ``max_gap_miles`` the original list is
    returned untouched, so this step can never invalidate the vehicle's range.
    """
    if spacing_miles <= 0 or len(matches) < 2:
        return list(matches)

    def rank(station: dict) -> tuple[float, float]:
        """Cheapest wins; an exact price tie goes to the earlier mile-marker."""
        return station["price"], station["route_mile"]

    cheapest: dict[int, dict] = {}
    for station in matches:
        bucket = int(station["route_mile"] // spacing_miles)
        current = cheapest.get(bucket)
        if current is None or rank(station) < rank(current):
            cheapest[bucket] = station

    thinned = sorted(cheapest.values(), key=lambda station: station["route_mile"])
    if max_gap_miles is not None and _leaves_a_gap(thinned, max_gap_miles):
        return list(matches)
    return thinned


def _leaves_a_gap(stations: list[dict], max_gap_miles: float) -> bool:
    """True when two neighbouring stations are further apart than ``max_gap_miles``."""
    return any(
        later["route_mile"] - earlier["route_mile"] > max_gap_miles
        for earlier, later in zip(stations, stations[1:])
    )


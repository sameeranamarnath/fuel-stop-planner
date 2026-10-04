"""Spherical geometry helpers.

Deliberately dependency-free (no NumPy, no GDAL/GeoDjango): the whole matching problem is
solved with a spatial hash grid, which keeps the Docker image small and the request path
fast without needing a spatial database.
"""

from __future__ import annotations

import math

EARTH_RADIUS_MILES = 3958.7613
METERS_PER_MILE = 1609.344
MILES_PER_DEGREE_LAT = 69.0548

# Decimal places kept on coordinates that leave the API.  6 dp is ~0.1 m, far below the
# accuracy of the underlying data, and it keeps the payload compact.
COORDINATE_PRECISION = 6


def trig_terms(latitude: float, longitude: float) -> tuple[float, float, float, float, float]:
    """Half-angle terms for :func:`chord_term`.

    ``haversine_miles`` needs four trigonometric calls.  Computing these once per point
    instead lets a whole batch of distance *comparisons* run without evaluating any
    trigonometry at all, which is what makes the station matcher fast.
    """
    lat_radians = math.radians(latitude)
    lon_radians = math.radians(longitude)
    return (
        math.sin(lat_radians / 2.0),
        math.cos(lat_radians / 2.0),
        math.cos(lat_radians),
        math.sin(lon_radians / 2.0),
        math.cos(lon_radians / 2.0),
    )


def chord_term(terms_a, terms_b) -> float:
    """``sin^2(angle / 2)`` between two points, from their :func:`trig_terms`.

    This is exactly the ``a`` that the haversine formula takes the arcsine of, so it is a
    strictly increasing function of the great-circle distance and therefore *orders*
    candidate points identically - for the price of five multiplications.  Nearest-point
    searches compare this and then measure the winner once with :func:`distance_from_chord`
    (or :func:`haversine_miles`), which is bit-for-bit the same answer for a fraction of
    the work.
    """
    sin_half_lat_a, cos_half_lat_a, cos_lat_a, sin_half_lon_a, cos_half_lon_a = terms_a
    sin_half_lat_b, cos_half_lat_b, cos_lat_b, sin_half_lon_b, cos_half_lon_b = terms_b
    delta_lat = sin_half_lat_b * cos_half_lat_a - cos_half_lat_b * sin_half_lat_a
    delta_lon = sin_half_lon_b * cos_half_lon_a - cos_half_lon_b * sin_half_lon_a
    return delta_lat * delta_lat + cos_lat_a * cos_lat_b * delta_lon * delta_lon


def distance_from_chord(term: float) -> float:
    """The great-circle distance, in miles, for a value from :func:`chord_term`."""
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(term)))


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in statute miles."""
    return distance_from_chord(chord_term(trig_terms(lat1, lon1), trig_terms(lat2, lon2)))



def cumulative_miles(points: list[list[float]]) -> list[float]:
    """Distance from the first point to each point, in miles.

    Each point's terms are built once and shared by the two segments that touch it, which
    is about half the work of measuring every segment with :func:`haversine_miles`.
    """
    if not points:
        return [0.0]

    cumulative = [0.0]
    total = 0.0
    previous = trig_terms(points[0][0], points[0][1])
    for point in points[1:]:
        current = trig_terms(point[0], point[1])
        total += distance_from_chord(chord_term(previous, current))
        cumulative.append(total)
        previous = current
    return cumulative


def resample(
    points: list[list[float]], cum: list[float], spacing_miles: float
) -> tuple[list[list[float]], list[float]]:
    """Re-space a polyline to roughly ``spacing_miles`` between points.

    Keeps the first and last vertices exactly.  Used to bound the size of both the
    persisted route geometry and the API response.
    """
    if not points or spacing_miles <= 0:
        return [list(p) for p in points], list(cum)

    out_points: list[list[float]] = [list(points[0])]
    out_cum: list[float] = [0.0]
    target = spacing_miles
    final_cum = cum[-1]

    for index in range(1, len(points)):
        seg_start, seg_end = cum[index - 1], cum[index]
        seg_len = seg_end - seg_start
        if seg_len <= 0:
            continue
        while target <= seg_end:
            t = (target - seg_start) / seg_len
            out_points.append(
                [
                    points[index - 1][0] + t * (points[index][0] - points[index - 1][0]),
                    points[index - 1][1] + t * (points[index][1] - points[index - 1][1]),
                ]
            )
            out_cum.append(target)
            target += spacing_miles

    if out_cum[-1] < final_cum - 1e-6:
        out_points.append(list(points[-1]))
        out_cum.append(final_cum)
    return out_points, out_cum


def to_geojson_coordinates(points: list[list[float]]) -> list[list[float]]:
    """Rounded GeoJSON coordinates: ``[[lat, lon], ...]`` becomes ``[[lon, lat], ...]``."""
    return [
        [round(lon, COORDINATE_PRECISION), round(lat, COORDINATE_PRECISION)]
        for lat, lon in points
    ]


def bounds(points: list[list[float]]) -> list[list[float]]:
    """GeoJSON-style bounding box ``[[min_lon, min_lat], [max_lon, max_lat]]``.

    Carries the same rounding as :func:`to_geojson_linestring`, so the box encloses
    exactly the coordinates the client was given; a viewport fitted to it cannot clip the
    line it is drawing.
    """
    coordinates = to_geojson_coordinates(points)
    longitudes = [coordinate[0] for coordinate in coordinates]
    latitudes = [coordinate[1] for coordinate in coordinates]
    return [[min(longitudes), min(latitudes)], [max(longitudes), max(latitudes)]]


def to_geojson_linestring(points: list[list[float]]) -> dict:
    """Convert ``[[lat, lon], ...]`` into a GeoJSON LineString (lon/lat order)."""
    return {"type": "LineString", "coordinates": to_geojson_coordinates(points)}


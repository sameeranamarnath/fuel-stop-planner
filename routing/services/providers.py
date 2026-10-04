"""External geocoding and routing clients.

Two providers ship out of the box, both free and key-less:

* **OSRM** public demo server for routing   - ``router.project-osrm.org``
* **Nominatim** (OpenStreetMap) for geocoding - ``nominatim.openstreetmap.org``

OpenRouteService is supported as an alternative for either role and only needs
``ORS_API_KEY`` to be set.

The planner calls these at most once per unique origin/destination pair; every other step
(station matching, optimiser) is computed locally, which is what keeps the request path
fast and the upstream call count at one.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings

from routing.exceptions import LocationNotFound, RoutingProviderError


class ProviderError(RoutingProviderError):
    """Raised when an upstream provider misbehaves; surfaces to clients as HTTP 502."""


@dataclass(frozen=True)
class Place:
    """A resolved location."""

    latitude: float
    longitude: float
    label: str = ""


@dataclass(frozen=True)
class RouteResult:
    """A routed path plus its summary statistics."""

    points: list[list[float]]  # [[lat, lon], ...] ordered from origin to destination
    distance_meters: float
    duration_seconds: float
    provider: str


def _headers() -> dict:
    return {
        "User-Agent": settings.SPOTTER["USER_AGENT"],
        "Accept": "application/json",
    }


def _get(url: str, *, params: dict, headers: dict | None = None, timeout: float):
    try:
        response = requests.get(
            url, params=params, headers=headers or _headers(), timeout=timeout
        )
    except requests.RequestException as exc:
        raise ProviderError(f"Request to {url} failed: {exc}") from exc
    if response.status_code >= 400:
        raise ProviderError(
            f"{url} returned HTTP {response.status_code}",
            extra={"body": response.text[:500]},
        )
    return response


class NominatimGeocoder:
    """OpenStreetMap Nominatim geocoder (free, no key, US-restricted)."""

    name = "nominatim"

    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def geocode(self, query: str) -> Place:
        response = _get(
            f"{self.base_url}/search",
            params={
                "q": query,
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "us",
                "addressdetails": 0,
            },
            timeout=self.timeout,
        )
        hits = response.json()
        if not hits:
            raise LocationNotFound(f"Could not find a US location for '{query}'.")
        top = hits[0]
        return Place(
            latitude=float(top["lat"]),
            longitude=float(top["lon"]),
            label=top.get("display_name", query),
        )


class OrsGeocoder:
    """OpenRouteService Pelias geocoder (free tier, requires ``ORS_API_KEY``)."""

    name = "ors"

    def __init__(self, base_url: str, api_key: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def geocode(self, query: str) -> Place:
        if not self.api_key:
            raise ProviderError("ORS_API_KEY is not configured for the ORS geocoder.")
        response = _get(
            f"{self.base_url}/geocode/search",
            params={
                "api_key": self.api_key,
                "text": query,
                "size": 1,
                "boundary.country": "US",
            },
            timeout=self.timeout,
        )
        features = response.json().get("features", [])
        if not features:
            raise LocationNotFound(f"Could not find a US location for '{query}'.")
        feature = features[0]
        longitude, latitude = feature["geometry"]["coordinates"]

class OsrmRouter:
    """OSRM public demo server (free, no key).  Full-resolution GeoJSON geometry."""

    name = "osrm"

    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def route(self, origin: Place, destination: Place) -> RouteResult:
        coordinates = (
            f"{origin.longitude},{origin.latitude};"
            f"{destination.longitude},{destination.latitude}"
        )
        response = _get(
            f"{self.base_url}/route/v1/driving/{coordinates}",
            params={
                "overview": "full",
                "geometries": "geojson",
                "steps": "false",
                "alternatives": "false",
            },
            timeout=self.timeout,
        )
        payload = response.json()
        if payload.get("code") != "Ok" or not payload.get("routes"):
            raise RoutingProviderError(
                f"OSRM could not route between the two points ({payload.get('code')}).",
                extra={"code": payload.get("code")},
            )
        route = payload["routes"][0]
        points = [[lat, lon] for lon, lat in route["geometry"]["coordinates"]]
        return RouteResult(
            points=points,
            distance_meters=float(route["distance"]),
            duration_seconds=float(route["duration"]),
            provider=self.name,
        )


class OrsRouter:
    """OpenRouteService directions endpoint (free tier, requires ``ORS_API_KEY``)."""

    name = "ors"

    def __init__(self, base_url: str, api_key: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def route(self, origin: Place, destination: Place) -> RouteResult:
        if not self.api_key:
            raise ProviderError("ORS_API_KEY is not configured for the ORS router.")
        url = f"{self.base_url}/v2/directions/driving-car/geojson"
        body = {
            "coordinates": [
                [origin.longitude, origin.latitude],
                [destination.longitude, destination.latitude],
            ],
            "instructions": False,
        }
        headers = {**_headers(), "Authorization": self.api_key}
        try:
            response = requests.post(url, json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"Request to {url} failed: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderError(
                f"{url} returned HTTP {response.status_code}",
                extra={"body": response.text[:500]},
            )
        features = response.json().get("features", [])
        if not features:
            raise RoutingProviderError("ORS returned no route for the two points.")
        feature = features[0]
        points = [[lat, lon] for lon, lat in feature["geometry"]["coordinates"]]
        summary = feature.get("properties", {}).get("summary", {})
        return RouteResult(
            points=points,
            distance_meters=float(summary.get("distance", 0.0)),
            duration_seconds=float(summary.get("duration", 0.0)),
            provider=self.name,
        )


def get_geocoder():
    """Build the geocoder selected by ``SPOTTER["GEOCODING_PROVIDER"]``."""
    config = settings.SPOTTER
    if config["GEOCODING_PROVIDER"] == "ors":
        return OrsGeocoder(
            config["ORS_BASE_URL"], config["ORS_API_KEY"], config["HTTP_TIMEOUT_SECONDS"]
        )
    return NominatimGeocoder(
        config["NOMINATIM_BASE_URL"], config["HTTP_TIMEOUT_SECONDS"]
    )


def get_router():
    """Build the router selected by ``SPOTTER["ROUTING_PROVIDER"]``."""
    config = settings.SPOTTER
    if config["ROUTING_PROVIDER"] == "ors":
        return OrsRouter(
            config["ORS_BASE_URL"], config["ORS_API_KEY"], config["HTTP_TIMEOUT_SECONDS"]
        )
    return OsrmRouter(config["OSRM_BASE_URL"], config["HTTP_TIMEOUT_SECONDS"])

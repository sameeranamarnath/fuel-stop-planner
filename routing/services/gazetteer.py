"""Offline resolution of a US ``"City, ST"`` string to coordinates.

Backed by the bundled Census Gazetteer extraction (``data/us_places.json``), so the common
``"New York, NY"`` request costs **zero** geocoding calls and the request is served by the
routing call alone.

Anything the gazetteer cannot resolve (an address, a landmark, an ambiguous bare city name)
falls through to the configured geocoding provider.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from django.conf import settings

from routing.services.place_names import US_STATES, normalize_place
from routing.services.providers import Place

logger = logging.getLogger(__name__)

STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}

_places: dict[str, list[float]] | None = None


def _load() -> dict[str, list[float]]:
    global _places
    if _places is None:
        path = Path(settings.SPOTTER["US_PLACES_PATH"])
        try:
            _places = json.loads(path.read_text(encoding="utf-8"))
            logger.info("Loaded %d US places for offline geocoding", len(_places))
        except Exception as exc:  # noqa: BLE001 - degrade to the provider, never fail
            logger.warning("Could not load %s (%s); will use the geocoding provider", path, exc)
            _places = {}
    return _places


def reset_cache() -> None:
    """Drop the in-memory gazetteer (used by tests)."""
    global _places
    _places = None


def state_code(text: str) -> str | None:
    """Accept either a two-letter code or a full state name."""
    cleaned = text.strip()
    if len(cleaned) == 2 and cleaned.upper() in US_STATES:
        return cleaned.upper()
    return STATE_NAMES.get(cleaned.lower())


def lookup(query: str) -> Place | None:
    """Resolve ``"New York, NY"`` locally, or return ``None`` if we cannot."""
    city_part, comma, state_part = query.rpartition(",")
    if not comma or not city_part.strip():
        return None
    code = state_code(state_part)
    if code is None:
        return None
    coords = _load().get(f"{normalize_place(city_part)}|{code}")
    if not coords:
        return None
    return Place(
        latitude=coords[0],
        longitude=coords[1],
        label=f"{city_part.strip()}, {code}",
    )

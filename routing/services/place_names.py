"""Shared place-name normalisation.

Used by both the offline coordinate builder (``scripts/build_place_coords.py``) and the
CSV importer, so the two sides are guaranteed to produce identical keys.

The Census gazetteers append a descriptor to every name (``Abbeville city``,
``Barrington town``, ``Abanda CDP``), and the price CSV contains a handful of non-US
entries, so both need the same folding rules.
"""

from __future__ import annotations

import unicodedata

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}

# Trailing descriptor tokens the Census appends to place / subdivision names.
LSAD_SUFFIX_TOKENS = {
    "city", "town", "village", "cdp", "borough", "municipality", "township",
    "plantation", "comunidad", "zona", "urbana", "purchase", "gore", "grant",
    "location", "island", "station", "county", "metro", "unified", "government",
    "balance", "corporation", "reservation", "precinct", "utilities", "authority",
    "acres", "poquoson", "metropolitan", "urban",
}


def normalize_place(name: str) -> str:
    """Fold a place name to a comparable, case-insensitive key."""
    ascii_name = (
        unicodedata.normalize("NFKD", name or "")
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    text = ascii_name.lower().replace("(balance)", " ")
    for character in ".-'/":
        text = text.replace(character, " ")
    parts = text.split()
    while parts and parts[-1] in LSAD_SUFFIX_TOKENS:
        parts.pop()
    return " ".join(parts)


def coord_key(city: str, state: str) -> str:
    """Build the ``"<normalised city>|<STATE>"`` key used in ``data/place_coords.json``."""
    return f"{normalize_place(city)}|{(state or '').strip().upper()}"

"""Data model for the fuel-route planner.

Three tables:

* ``FuelStation``  - the OPIS truck-stop price list, enriched with coordinates that
  were derived offline from public Census/Nominatim data (see
  ``scripts/build_place_coords.py``).  Coordinates live locally so the API never has to
  geocode a fuel station at request time.
* ``GeocodeCache`` - memoises start/finish lookups so repeated requests cost 0 API calls.
* ``RouteCache``   - memoises routing results keyed by rounded origin/destination.

The two caches keep the request path to a single upstream call: the first request for a pair
makes it, and every later request is served from the database.
"""

from django.db import models


class FuelStation(models.Model):
    """A truck stop from the OPIS price list, with resolved coordinates."""

    opis_id = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.CharField(max_length=32, blank=True, default="")
    price = models.FloatField(help_text="Retail price in USD per gallon")
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        ordering = ("price", "name")
        indexes = [
            models.Index(fields=["latitude", "longitude"]),
            models.Index(fields=["city", "state"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.name} ({self.city}, {self.state}) ${self.price:.3f}"


class GeocodeCache(models.Model):
    """Normalised place string -> coordinates, so a place is geocoded at most once."""

    query = models.CharField(max_length=255, unique=True)
    label = models.CharField(max_length=255, blank=True, default="")
    latitude = models.FloatField()
    longitude = models.FloatField()
    provider = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.query} -> ({self.latitude}, {self.longitude})"


class RouteCache(models.Model):
    """A routed origin/destination pair, resolved and ready to re-plan offline.

    ``geometry`` holds the (already decimated) polyline as ``[[lat, lon], ...]`` so the
    planner can rebuild cumulative distances without touching the network again.
    """

    key = models.CharField(max_length=160, unique=True)
    origin_label = models.CharField(max_length=255, blank=True, default="")
    destination_label = models.CharField(max_length=255, blank=True, default="")
    distance_meters = models.FloatField()
    duration_seconds = models.FloatField()
    provider = models.CharField(max_length=32, blank=True, default="")
    geometry = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.key} ({self.distance_meters / 1609.344:.0f} mi)"

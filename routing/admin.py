"""Django admin registrations - useful for eyeballing the loaded price list."""

from django.contrib import admin

from routing.models import FuelStation, GeocodeCache, RouteCache


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "price", "latitude", "longitude")
    list_filter = ("state",)
    search_fields = ("name", "city", "opis_id", "rack_id")
    ordering = ("state", "city", "price")


@admin.register(GeocodeCache)
class GeocodeCacheAdmin(admin.ModelAdmin):
    list_display = ("query", "latitude", "longitude", "provider", "created_at")
    search_fields = ("query", "label")


@admin.register(RouteCache)
class RouteCacheAdmin(admin.ModelAdmin):
    list_display = ("key", "distance_meters", "duration_seconds", "provider", "created_at")
    search_fields = ("key", "origin_label", "destination_label")

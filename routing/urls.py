"""URL routes for the routing app.  Mounted under ``/api/v1/`` by ``config.urls``."""

from django.urls import path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from routing import views

app_name = "routing"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("ready/", views.ready, name="ready"),
    path("fuel-plan/", views.fuel_plan, name="fuel-plan"),
    path("stations/", views.stations, name="stations"),
    # OpenAPI 3 schema + interactive docs
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="routing:schema"), name="docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="routing:schema"), name="redoc"),
]


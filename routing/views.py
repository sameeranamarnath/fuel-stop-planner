"""HTTP layer: the fuel-plan endpoint plus supporting endpoints."""

from urllib.parse import urlencode

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from routing.exceptions import RequestValidationError
from routing.models import FuelStation
from routing.serializers import FuelPlanRequestSerializer, FuelStationSerializer
from routing.services import planner

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

ERROR_RESPONSES = {
    400: OpenApiTypes.OBJECT,
    409: OpenApiTypes.OBJECT,
    422: OpenApiTypes.OBJECT,
    502: OpenApiTypes.OBJECT,
}


@extend_schema(
    summary="Plan a route and choose the cost-optimal fuel stops",
    description=(
        "Returns the driving route as GeoJSON, the cost-optimal fuel stops for a vehicle "
        "with a 500-mile range doing 10 MPG, and the total money spent on fuel.\n\n"
        "`start`/`finish` accept a US place name (\"City, ST\") or an explicit "
        "`{\"lat\": .., \"lon\": ..}` pair. Place names are resolved from a bundled US "
        "gazetteer, so a request makes **one** upstream routing call and that is all; a "
        "repeat of the same pair is served entirely from the database with zero calls.\n\n"
        "Response headers: `X-Upstream-Calls`, `X-Cache` (`HIT`/`MISS`), `X-Latency-Ms`."
    ),
    parameters=[
        OpenApiParameter("start", str, OpenApiParameter.QUERY,
                         description="Start location, for GET convenience."),
        OpenApiParameter("finish", str, OpenApiParameter.QUERY,
                         description="Finish location, for GET convenience."),
    ],
    request=FuelPlanRequestSerializer,
    responses={200: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
    tags=["fuel-plan"],
)
@api_view(["POST", "GET"])
def fuel_plan(request):
    """Return the route geometry and the cost-optimal fuel stops along it.

    ``POST`` body (JSON)::

        {"start": "New York, NY", "finish": "Los Angeles, CA"}

    A ``GET`` with ``?start=..&finish=..`` is supported for quick demos.
    """
    if request.method == "GET":
        payload = {
            "start": request.query_params.get("start"),
            "finish": request.query_params.get("finish"),
        }
    else:
        payload = request.data

    serializer = FuelPlanRequestSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    validated = serializer.validated_data

    result = planner.build_fuel_plan(validated["start"], validated["finish"])
    result["map_url"] = request.build_absolute_uri(
        "/api/v1/map/?"
        + urlencode(
            {
                "start": result["start"]["label"],
                "finish": result["finish"]["label"],
                "auto": 1,
            }
        )
    )

    calls = result["external_api_calls"]
    response = Response(result)
    response["X-Upstream-Calls"] = str(calls["external_calls_total"])
    response["X-Cache"] = "HIT" if calls["routing_cache_hits"] else "MISS"
    response["X-Latency-Ms"] = f"{result['elapsed_ms']:.1f}"
    return response


@extend_schema(
    summary="Liveness probe",
    description="Process is up, plus the configuration the planner is running with.",
    responses={200: OpenApiTypes.OBJECT},
    tags=["ops"],
)
@api_view(["GET"])
def health(request):
    config = settings.SPOTTER
    return Response(
        {
            "status": "ok",
            "fuel_stations_loaded": FuelStation.objects.count(),
            "routing_provider": config["ROUTING_PROVIDER"],
            "geocoding_provider": config["GEOCODING_PROVIDER"],
            "offline_geocoding": True,
            "vehicle": {
                "max_range_miles": config["MAX_RANGE_MILES"],
                "mpg": config["MPG"],
                "tank_capacity_gallons": config["MAX_RANGE_MILES"] / config["MPG"],
            },
            "caching_enabled": config["CACHE_ENABLED"],
        }
    )


@extend_schema(
    summary="Readiness probe",
    description="503 until the fuel-price catalogue has been loaded.",
    responses={200: OpenApiTypes.OBJECT, 503: OpenApiTypes.OBJECT},
    tags=["ops"],
)
@api_view(["GET"])
def ready(request):
    count = FuelStation.objects.count()
    if count == 0:
        return Response(
            {
                "status": "not_ready",
                "detail": "Run 'python manage.py load_fuel_prices' first.",
                "fuel_stations_loaded": 0,
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({"status": "ready", "fuel_stations_loaded": count})


def _station_filters(request) -> dict:
    """Translate the catalogue query string into ORM keyword filters.

    An unparseable ``max_price`` is reported as a client error rather than ignored - a
    filter that silently does nothing is worse than no filter at all.
    """
    filters: dict = {}

    state = request.query_params.get("state", "").strip()
    if state:
        filters["state"] = state.upper()

    city = request.query_params.get("city", "").strip()
    if city:
        filters["city__iexact"] = city

    maximum_price = request.query_params.get("max_price", "").strip()
    if maximum_price:
        try:
            filters["price__lte"] = float(maximum_price)
        except ValueError as exc:
            raise RequestValidationError(
                f"'max_price' must be a number (got '{maximum_price}')."
            ) from exc

    return filters


def _page_size(request) -> int:
    """Page size from ``?limit=``, clamped to ``1..MAX_PAGE_SIZE``."""
    try:
        requested = int(request.query_params.get("limit", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return max(1, min(requested, MAX_PAGE_SIZE))


@extend_schema(
    summary="Browse the loaded truck stops",
    description="Handy for spot-checking prices; filter by state, city or maximum price.",
    parameters=[
        OpenApiParameter("state", str, description="Two-letter state code, e.g. TX."),
        OpenApiParameter("city", str, description="City name (case-insensitive)."),
        OpenApiParameter("max_price", float, description="Only stations at or below this price."),
        OpenApiParameter("limit", int, description="Page size, 1-500 (default 50)."),
    ],
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    tags=["catalogue"],
)
@api_view(["GET"])
def stations(request):
    """Browse the loaded truck stops (handy for spot-checking prices)."""
    queryset = FuelStation.objects.filter(**_station_filters(request))
    limit = _page_size(request)
    page = queryset.order_by("price", "name")[:limit]
    return Response(
        {
            "count": queryset.count(),
            "returned": len(page),
            "results": FuelStationSerializer(page, many=True).data,
        }
    )

"""Domain errors and the DRF exception handler that renders them as JSON."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class PlannerError(Exception):
    """Base class for every error the API reports to clients."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Unable to build a fuel plan."
    code = "planner_error"

    def __init__(self, detail: str | None = None, *, extra: dict | None = None):
        self.detail = detail or self.default_detail
        self.extra = extra or {}
        super().__init__(self.detail)


class RequestValidationError(PlannerError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "validation_error"
    default_detail = "Invalid request payload."


class LocationNotFound(PlannerError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "location_not_found"
    default_detail = "Could not resolve a location to coordinates."


class RoutingProviderError(PlannerError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "routing_provider_error"
    default_detail = "The routing provider could not compute a route."


class RouteInfeasible(PlannerError):
    status_code = status.HTTP_409_CONFLICT
    code = "route_infeasible"
    default_detail = "The route cannot be completed with the configured vehicle range."


def api_exception_handler(exc, context):
    """Return a consistent ``{"error": {...}}`` body for domain errors."""
    if isinstance(exc, PlannerError):
        payload: dict = {"error": {"code": exc.code, "detail": str(exc.detail)}}
        if exc.extra:
            payload["error"]["context"] = exc.extra
        return Response(payload, status=exc.status_code)
    return drf_exception_handler(exc, context)

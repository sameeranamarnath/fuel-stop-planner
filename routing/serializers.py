"""Request serializers for the fuel-plan API."""

from rest_framework import serializers

from routing.models import FuelStation


def _validate_location(value, role: str):
    """Accept either a free-text place name or an explicit ``{lat, lon}`` pair."""
    if isinstance(value, dict):
        if "lat" not in value or "lon" not in value:
            raise serializers.ValidationError(
                f"'{role}' must contain both 'lat' and 'lon'."
            )
        try:
            float(value["lat"])
            float(value["lon"])
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError(
                f"'{role}' 'lat' and 'lon' must be numbers."
            ) from exc
        return value
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise serializers.ValidationError(
        f"'{role}' must be a US place name (\"City, ST\") or an object "
        f"like {{\"lat\": 40.71, \"lon\": -74.01}}."
    )


class FuelPlanRequestSerializer(serializers.Serializer):
    """Body of ``POST /api/v1/fuel-plan/``."""

    start = serializers.JSONField()
    finish = serializers.JSONField()

    def validate_start(self, value):  # noqa: D102
        return _validate_location(value, "start")

    def validate_finish(self, value):  # noqa: D102
        return _validate_location(value, "finish")


class FuelStationSerializer(serializers.ModelSerializer):
    """Read-only representation used by the station catalogue endpoint."""

    class Meta:
        model = FuelStation
        fields = (
            "id", "opis_id", "name", "address", "city", "state",
            "rack_id", "price", "latitude", "longitude",
        )

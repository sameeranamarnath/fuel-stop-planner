"""Tests for offline place resolution and the operational surface."""

from django.test import SimpleTestCase, TestCase

from routing.models import FuelStation
from routing.services import gazetteer


class GazetteerTests(SimpleTestCase):
    """Offline "City, ST" resolution - the reason a request needs one upstream call."""

    def test_resolves_city_and_two_letter_state(self):
        place = gazetteer.lookup("New York, NY")
        self.assertIsNotNone(place)
        self.assertTrue(40.0 < place.latitude < 41.5)
        self.assertTrue(-75.0 < place.longitude < -73.0)

    def test_resolves_a_full_state_name(self):
        self.assertIsNotNone(gazetteer.lookup("New York, New York"))
        self.assertIsNotNone(gazetteer.lookup("Los Angeles, California"))

    def test_resolves_consolidated_city_county_names(self):
        # "Nashville-Davidson metropolitan government (balance)" is colloquially Nashville.
        self.assertIsNotNone(gazetteer.lookup("Nashville, TN"))
        self.assertIsNotNone(gazetteer.lookup("Louisville, KY"))

    def test_is_case_and_spacing_insensitive(self):
        self.assertIsNotNone(gazetteer.lookup("  new york ,  ny "))

    def test_unknown_place_returns_none_so_the_provider_is_used(self):
        self.assertIsNone(gazetteer.lookup("Nowhere At All, TX"))

    def test_ambiguous_bare_city_returns_none(self):
        self.assertIsNone(gazetteer.lookup("Springfield"))

    def test_state_code_accepts_codes_and_names(self):
        self.assertEqual(gazetteer.state_code("tx"), "TX")
        self.assertEqual(gazetteer.state_code("Texas"), "TX")
        self.assertIsNone(gazetteer.state_code("Zzz"))


class OpsEndpointTests(TestCase):
    def test_readiness_is_503_until_the_catalogue_is_loaded(self):
        response = self.client.get("/api/v1/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")

    def test_readiness_is_200_once_loaded(self):
        FuelStation.objects.create(
            opis_id="1", name="One", city="A", state="TX", price=3.0,
            latitude=30.0, longitude=-100.0,
        )
        payload = self.client.get("/api/v1/ready/").json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["fuel_stations_loaded"], 1)

    def test_health_reports_offline_geocoding(self):
        self.assertTrue(self.client.get("/api/v1/health/").json()["offline_geocoding"])

    def test_openapi_schema_documents_the_endpoints(self):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        self.assertEqual(schema["info"]["title"], "Spotter Fuel Route Planner API")
        self.assertIn("/api/v1/fuel-plan/", schema["paths"])
        self.assertIn("/api/v1/ready/", schema["paths"])

    def test_schema_docs_and_redoc_are_served(self):
        for name in ("schema", "docs", "redoc"):
            response = self.client.get(f"/api/v1/{name}/")
            self.assertEqual(response.status_code, 200, name)

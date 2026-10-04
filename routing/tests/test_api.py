"""End-to-end API tests.  Upstream providers are stubbed, so this runs fully offline."""

from unittest import mock

from django.test import TestCase

from routing.exceptions import LocationNotFound
from routing.models import FuelStation
from routing.services import planner
from routing.services.providers import Place, RouteResult

START_LAT = 30.0
MILES_PER_DEGREE_LAT = 69.0548


def latitude_for_mile(mile: float) -> float:
    return START_LAT + mile / MILES_PER_DEGREE_LAT


# A straight north-bound route on the -100 meridian: 30.0N to 44.5N (~1001 miles).
ROUTE_MILES = 14.5 * MILES_PER_DEGREE_LAT
ROUTE_POINTS = [[30.0 + index * 0.05, -100.0] for index in range(291)]

START_COORDS = {"lat": START_LAT, "lon": -100.0}
FINISH_COORDS = {"lat": latitude_for_mile(ROUTE_MILES), "lon": -100.0}


class FakeRouter:
    name = "fake"

    def __init__(self, points=None):
        self.points = points or ROUTE_POINTS
        self.calls = 0

    def route(self, origin, destination):
        self.calls += 1
        return RouteResult(
            points=[list(point) for point in self.points],
            distance_meters=ROUTE_MILES * 1609.344,
            duration_seconds=20 * 3600.0,
            provider=self.name,
        )


class FakeGeocoder:
    name = "fake"

    def __init__(self, places=None, error=None):
        self.places = places or {}
        self.error = error
        self.calls = 0

    def geocode(self, query):
        self.calls += 1
        if self.error:
            raise self.error
        return self.places[query]


def make_stations(count=3):
    """Create ``count`` stations priced 2.00, 3.00, 4.00 ... for catalogue tests."""
    FuelStation.objects.bulk_create(
        [
            FuelStation(
                opis_id=str(index),
                name="Cheap" if index == 0 else f"Stop {index}",
                city="A",
                state="TX",
                price=2.0 + index,
                latitude=30.0,
                longitude=-100.0,
            )
            for index in range(count)
        ]
    )


class FuelPlanApiTests(TestCase):
    def setUp(self):
        planner.reset_station_cache()
        FuelStation.objects.bulk_create(
            [
                FuelStation(opis_id="1", name="Pricy Plaza", city="Alpha", state="TX",
                            price=4.00, latitude=latitude_for_mile(150.0),
                            longitude=-100.0),
                FuelStation(opis_id="2", name="Cheap Corner", city="Beta", state="TX",
                            price=2.00, latitude=latitude_for_mile(400.0),
                            longitude=-100.0),
                FuelStation(opis_id="3", name="Mid Stop", city="Gamma", state="TX",
                            price=3.00, latitude=latitude_for_mile(700.0),
                            longitude=-100.0),
            ]
        )

    def post(self, start=START_COORDS, finish=FINISH_COORDS):
        return self.client.post(
            "/api/v1/fuel-plan/",
            data={"start": start, "finish": finish},
            content_type="application/json",
        )

    def test_coordinate_request_makes_exactly_one_routing_call(self):
        router = FakeRouter()
        with mock.patch("routing.services.providers.get_router", return_value=router):
            response = self.post()

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["external_api_calls"]["routing_calls"], 1)
        self.assertEqual(payload["external_api_calls"]["geocoding_calls"], 0)
        self.assertEqual(router.calls, 1)

    def test_response_exposes_call_and_latency_headers(self):
        with mock.patch(
            "routing.services.providers.get_router", return_value=FakeRouter()
        ):
            response = self.post()

        self.assertEqual(response["X-Upstream-Calls"], "1")
        self.assertEqual(response["X-Cache"], "MISS")
        self.assertTrue(float(response["X-Latency-Ms"]) >= 0)
        self.assertIn("auto=1", response.json()["map_url"])

    def test_second_request_reports_a_cache_hit_header(self):
        with mock.patch(
            "routing.services.providers.get_router", return_value=FakeRouter()
        ):
            self.post()
            response = self.post()

        self.assertEqual(response["X-Upstream-Calls"], "0")
        self.assertEqual(response["X-Cache"], "HIT")

    def test_route_summary_is_consistent(self):
        with mock.patch(
            "routing.services.providers.get_router", return_value=FakeRouter()
        ):
            payload = self.post().json()

        summary = payload["summary"]
        self.assertAlmostEqual(summary["total_distance_miles"], ROUTE_MILES, delta=2.0)
        self.assertAlmostEqual(
            summary["total_gallons_consumed"], ROUTE_MILES / 10.0, delta=0.5
        )
        self.assertAlmostEqual(
            summary["total_gallons_purchased"], ROUTE_MILES / 10.0 - 50.0, delta=0.5
        )
        self.assertEqual(
            round(sum(stop["cost_usd"] for stop in payload["fuel_stops"]), 2),
            summary["total_fuel_cost_usd"],
        )
        self.assertIsNotNone(summary["average_price_per_gallon"])

    def test_chooses_the_cheapest_stations_and_keeps_legs_within_range(self):
        with mock.patch(
            "routing.services.providers.get_router", return_value=FakeRouter()
        ):
            payload = self.post().json()

        stops = payload["fuel_stops"]
        miles = [stop["distance_from_start_miles"] for stop in stops]
        self.assertEqual(len(stops), 2)
        self.assertAlmostEqual(miles[0], 400.0, delta=2.0)  # the $2.00 stop
        self.assertAlmostEqual(miles[1], 700.0, delta=2.0)  # the $3.00 stop
        self.assertEqual([stop["price_per_gallon"] for stop in stops], [2.0, 3.0])

        markers = [0.0] + miles + [payload["summary"]["total_distance_miles"]]
        self.assertLessEqual(max(b - a for a, b in zip(markers, markers[1:])), 500.0)

    def test_response_carries_a_usable_geojson_map(self):
        with mock.patch(
            "routing.services.providers.get_router", return_value=FakeRouter()
        ):
            payload = self.post().json()

        features = payload["geojson"]["features"]
        self.assertEqual(payload["geojson"]["type"], "FeatureCollection")
        self.assertEqual(features[0]["geometry"]["type"], "LineString")
        self.assertEqual(features[0]["properties"]["kind"], "route")
        point_features = [f for f in features if f["geometry"]["type"] == "Point"]
        self.assertEqual(len(point_features), len(payload["fuel_stops"]))
        self.assertEqual(len(payload["route"]["bounds"]), 2)

    def test_repeat_request_is_served_entirely_from_cache(self):
        router = FakeRouter()
        with mock.patch("routing.services.providers.get_router", return_value=router):
            first = self.post().json()
            second = self.post().json()

        self.assertEqual(first["external_api_calls"]["routing_calls"], 1)
        self.assertEqual(second["external_api_calls"]["routing_calls"], 0)
        self.assertEqual(second["external_api_calls"]["routing_cache_hits"], 1)
        self.assertEqual(router.calls, 1)  # upstream was only hit once

    def test_text_locations_are_geocoded_once_then_cached(self):
        geocoder = FakeGeocoder(
            {
                "Testville, TX": Place(30.0, -100.0, "Testville, TX, USA"),
                "Far City, TX": Place(
                    latitude_for_mile(ROUTE_MILES), -100.0, "Far City, TX, USA"
                ),
            }
        )
        body = {"start": "Testville, TX", "finish": "Far City, TX"}
        with mock.patch(
            "routing.services.providers.get_router", return_value=FakeRouter()
        ), mock.patch(
            "routing.services.providers.get_geocoder", return_value=geocoder
        ):
            first = self.client.post(
                "/api/v1/fuel-plan/", data=body, content_type="application/json"
            ).json()
            second = self.client.post(
                "/api/v1/fuel-plan/", data=body, content_type="application/json"
            ).json()

        self.assertEqual(first["external_api_calls"]["geocoding_calls"], 2)
        self.assertEqual(second["external_api_calls"]["geocoding_calls"], 0)
        self.assertEqual(second["external_api_calls"]["geocoding_cache_hits"], 2)
        self.assertEqual(geocoder.calls, 2)

    def test_missing_location_is_a_400(self):
        response = self.client.post(
            "/api/v1/fuel-plan/",
            data={"start": START_COORDS},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_unresolvable_location_is_a_422(self):
        geocoder = FakeGeocoder(error=LocationNotFound("nope"))
        with mock.patch("routing.services.providers.get_geocoder", return_value=geocoder):
            response = self.post(start="Nowhere, ZZ", finish="Also Nowhere, ZZ")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "location_not_found")

    def test_unreachable_route_is_a_409(self):
        # A ~4,000-mile route whose only stations cluster in the first 700 miles.
        long_points = [[30.0 + index * 0.2, -100.0] for index in range(291)]
        with mock.patch(
            "routing.services.providers.get_router",
            return_value=FakeRouter(points=long_points),
        ):
            response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "route_infeasible")

    def test_place_names_resolve_offline_so_no_geocoding_call_is_made(self):
        """The headline claim: a "City, ST" request is paid for by the routing call alone."""
        with mock.patch(
            "routing.services.providers.get_router", return_value=FakeRouter()
        ), mock.patch("routing.services.providers.get_geocoder") as geocoder:
            response = self.client.post(
                "/api/v1/fuel-plan/",
                data={"start": "New York, NY", "finish": "Los Angeles, CA"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        geocoder.assert_not_called()
        calls = response.json()["external_api_calls"]
        self.assertEqual(calls["geocoding_calls"], 0)
        self.assertEqual(calls["routing_calls"], 1)
        self.assertEqual(calls["external_calls_total"], 1)

    def test_an_unknown_place_falls_back_to_the_geocoding_provider(self):
        geocoder = FakeGeocoder(
            {"Nowhere Special, TX": Place(30.0, -100.0, "Nowhere Special, TX, USA")}
        )
        with mock.patch(
            "routing.services.providers.get_router", return_value=FakeRouter()
        ), mock.patch(
            "routing.services.providers.get_geocoder", return_value=geocoder
        ):
            response = self.client.post(
                "/api/v1/fuel-plan/",
                data={"start": "Nowhere Special, TX", "finish": FINISH_COORDS},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["external_api_calls"]["geocoding_calls"], 1)
        self.assertEqual(geocoder.calls, 1)


class SupportEndpointTests(TestCase):
    def test_health_reports_loaded_station_count(self):
        FuelStation.objects.create(
            opis_id="1", name="One", city="A", state="TX", price=3.0,
            latitude=30.0, longitude=-100.0,
        )
        payload = self.client.get("/api/v1/health/").json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["fuel_stations_loaded"], 1)
        self.assertEqual(payload["vehicle"]["max_range_miles"], 500.0)

    def test_station_catalogue_filters_by_state(self):
        FuelStation.objects.create(
            opis_id="1", name="One", city="A", state="TX", price=3.0,
            latitude=30.0, longitude=-100.0,
        )
        FuelStation.objects.create(
            opis_id="2", name="Two", city="B", state="OK", price=2.0,
            latitude=31.0, longitude=-99.0,
        )
        payload = self.client.get("/api/v1/stations/?state=OK").json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["state"], "OK")

    def test_station_catalogue_is_ordered_by_price(self):
        make_stations()
        results = self.client.get("/api/v1/stations/").json()["results"]
        prices = [station["price"] for station in results]
        self.assertEqual(prices, sorted(prices))

    def test_station_catalogue_filters_by_max_price(self):
        make_stations()  # priced 2.00, 3.00, 4.00
        payload = self.client.get("/api/v1/stations/?max_price=3.00").json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            [station["name"] for station in payload["results"]], ["Cheap", "Stop 1"]
        )

    def test_station_catalogue_rejects_an_unparseable_max_price(self):
        """A filter that silently does nothing is worse than no filter at all."""
        response = self.client.get("/api/v1/stations/?max_price=cheap")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_station_catalogue_clamps_the_page_size(self):
        make_stations()
        self.assertEqual(self.client.get("/api/v1/stations/?limit=2").json()["returned"], 2)
        self.assertEqual(self.client.get("/api/v1/stations/?limit=999").json()["returned"], 3)
        # A nonsensical limit falls back to the default rather than erroring.
        self.assertEqual(
            self.client.get("/api/v1/stations/?limit=oops").json()["returned"], 3
        )

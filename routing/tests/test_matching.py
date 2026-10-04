"""Unit tests for the spatial station-to-route matcher."""

from django.test import SimpleTestCase

from routing.services import geo
from routing.services.matching import match_stations_to_route, thin_candidates

MAX_OFFSET = 5.0

# A north-bound line at 61N, where one degree of longitude is only ~33 miles rather than
# the ~45 that holds across the northern states.  This is the geometry that exposes a grid
# sized from a single fixed degrees-per-mile constant.
ALASKA_ROUTE = [[60.0 + index * 0.05, -150.63] for index in range(41)]


class MatchingTests(SimpleTestCase):
    def setUp(self):
        # A straight north-bound meridian from 30.0N to 40.0N (0.1 degrees per vertex,
        # so vertex i sits ~6.905 miles from the origin).
        self.route = [[30.0 + index * 0.1, -90.0] for index in range(101)]
        self.cumulative = geo.cumulative_miles(self.route)

    def station(self, identifier, latitude, longitude, price=3.0):
        return {
            "id": identifier,
            "latitude": latitude,
            "longitude": longitude,
            "price": price,
        }

    def test_matches_stations_near_the_line(self):
        stations = [
            self.station(1, 35.0, -90.0),
            self.station(2, 32.0, -90.02),
        ]
        matched = match_stations_to_route(
            self.route, self.cumulative, stations, MAX_OFFSET
        )
        self.assertEqual([m["id"] for m in matched], [2, 1])
        self.assertAlmostEqual(matched[1]["route_mile"], 345.0, delta=3.0)
        self.assertAlmostEqual(matched[0]["route_mile"], 138.0, delta=3.0)
        for match in matched:
            self.assertLessEqual(match["offset_miles"], MAX_OFFSET)

    def test_drops_stations_far_from_the_line(self):
        # 0.5 degrees of longitude at 35N is ~28 miles east of the route.
        stations = [self.station(9, 35.0, -90.5)]
        self.assertEqual(
            match_stations_to_route(self.route, self.cumulative, stations, MAX_OFFSET),
            [],
        )

    def test_drops_stations_outside_the_route_bounding_box(self):
        stations = [self.station(9, 20.0, -90.0)]
        self.assertEqual(
            match_stations_to_route(self.route, self.cumulative, stations, MAX_OFFSET),
            [],
        )

    def test_results_are_sorted_by_route_mile(self):
        stations = [
            self.station(1, 39.0, -90.0),
            self.station(2, 31.0, -90.0),
            self.station(3, 35.0, -90.0),
        ]
        matched = match_stations_to_route(
            self.route, self.cumulative, stations, MAX_OFFSET
        )
        self.assertEqual([m["id"] for m in matched], [2, 3, 1])

    def test_empty_inputs_are_safe(self):
        self.assertEqual(
            match_stations_to_route([], [], [self.station(1, 30.0, -90.0)], MAX_OFFSET),
            [],
        )
        self.assertEqual(
            match_stations_to_route(self.route, self.cumulative, [], MAX_OFFSET), []
        )

    def test_original_station_fields_are_preserved(self):
        stations = [self.station(7, 35.0, -90.0, price=2.75)]
        matched = match_stations_to_route(
            self.route, self.cumulative, stations, MAX_OFFSET
        )
        self.assertEqual(matched[0]["price"], 2.75)
        self.assertIn("route_mile", matched[0])

    def test_matches_a_station_a_short_hop_east_at_high_latitude(self):
        cumulative = geo.cumulative_miles(ALASKA_ROUTE)
        # 0.64 degrees east of the route at 61N is ~21 miles: inside the 25-mile corridor.
        matched = match_stations_to_route(
            ALASKA_ROUTE, cumulative, [self.station(1, 61.0, -149.99)], 25.0
        )
        self.assertEqual([match["id"] for match in matched], [1])
        self.assertAlmostEqual(matched[0]["offset_miles"], 21.4, delta=0.3)

    def test_still_drops_what_lies_outside_the_corridor_at_high_latitude(self):
        cumulative = geo.cumulative_miles(ALASKA_ROUTE)
        # 0.9 degrees east of the route at 61N is ~30 miles: beyond the corridor.
        matched = match_stations_to_route(
            ALASKA_ROUTE, cumulative, [self.station(1, 61.0, -149.73)], 25.0
        )
        self.assertEqual(matched, [])


def candidate(identifier, route_mile, price):
    return {"id": identifier, "route_mile": route_mile, "price": price}


class ThinCandidatesTests(SimpleTestCase):
    def test_keeps_only_the_cheapest_station_per_stretch(self):
        matches = [
            candidate(1, 10.0, 3.50),
            candidate(2, 14.0, 3.10),  # same 25-mile bucket, cheaper, so it wins
            candidate(3, 20.0, 3.40),
            candidate(4, 40.0, 2.90),  # next bucket
        ]
        thinned = thin_candidates(matches, 25.0)
        self.assertEqual([station["id"] for station in thinned], [2, 4])

    def test_output_is_sorted_by_route_mile(self):
        matches = [candidate(1, 60.0, 3.0), candidate(2, 10.0, 3.0)]
        thinned = thin_candidates(matches, 25.0)
        self.assertEqual([station["id"] for station in thinned], [2, 1])

    def test_zero_spacing_is_a_no_op(self):
        matches = [candidate(1, 10.0, 3.5), candidate(2, 12.0, 3.4)]
        self.assertEqual(thin_candidates(matches, 0), matches)

    def test_falls_back_when_thinning_would_break_the_range(self):
        matches = [
            candidate(1, 10.0, 3.0),
            candidate(2, 26.0, 3.0),
            candidate(3, 27.0, 3.0),
        ]
        # A 5-mile ceiling is violated by the thinned list, so the full list is kept;
        # a realistic ceiling leaves the list thinned.
        self.assertEqual(len(thin_candidates(matches, 25.0, max_gap_miles=5.0)), 3)
        self.assertEqual(len(thin_candidates(matches, 25.0, max_gap_miles=500.0)), 2)

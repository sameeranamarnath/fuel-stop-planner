"""Unit tests for the geometry helpers."""

import random

from django.test import SimpleTestCase

from routing.services import geo


class GeoTests(SimpleTestCase):
    def test_haversine_matches_a_known_pair(self):
        # New York, NY -> Los Angeles, CA is ~2446 statute miles great-circle.
        distance = geo.haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
        self.assertAlmostEqual(distance, 2446, delta=20)

    def test_haversine_is_zero_and_symmetric(self):
        self.assertEqual(geo.haversine_miles(30.0, -90.0, 30.0, -90.0), 0.0)
        self.assertAlmostEqual(
            geo.haversine_miles(30.0, -90.0, 40.0, -80.0),
            geo.haversine_miles(40.0, -80.0, 30.0, -90.0),
        )

    def test_one_degree_of_latitude_is_about_69_miles(self):
        self.assertAlmostEqual(
            geo.haversine_miles(30.0, -90.0, 31.0, -90.0), 69.05, delta=0.6
        )

    def test_cumulative_miles_is_monotonic(self):
        points = [[30.0, -90.0], [31.0, -90.0], [32.0, -90.0]]
        cumulative = geo.cumulative_miles(points)
        self.assertEqual(len(cumulative), 3)
        self.assertEqual(cumulative[0], 0.0)
        self.assertLess(cumulative[0], cumulative[1])
        self.assertLess(cumulative[1], cumulative[2])

    def test_resample_keeps_endpoints_and_honours_spacing(self):
        points = [[30.0, -90.0], [40.0, -90.0]]  # ~690 miles, 2 vertices
        cumulative = geo.cumulative_miles(points)
        resampled, new_cumulative = geo.resample(points, cumulative, 10.0)

        self.assertEqual(resampled[0], points[0])
        self.assertEqual(resampled[-1], points[-1])
        self.assertAlmostEqual(new_cumulative[-1], cumulative[-1])
        gaps = [b - a for a, b in zip(new_cumulative, new_cumulative[1:])]
        self.assertLessEqual(max(gaps), 10.0 + 1e-6)
        self.assertGreater(len(resampled), 60)

    def test_resample_with_zero_spacing_is_a_no_op(self):
        points = [[30.0, -90.0], [31.0, -90.0]]
        cumulative = geo.cumulative_miles(points)
        self.assertEqual(geo.resample(points, cumulative, 0), (points, cumulative))

    def test_geojson_uses_lon_lat_order(self):
        linestring = geo.to_geojson_linestring([[30.5, -90.25]])
        self.assertEqual(linestring["type"], "LineString")
        self.assertEqual(linestring["coordinates"], [[-90.25, 30.5]])

    def test_bounds(self):
        self.assertEqual(
            geo.bounds([[30.0, -95.0], [35.0, -90.0]]),
            [[-95.0, 30.0], [-90.0, 35.0]],
        )

    def test_bounds_covers_every_emitted_coordinate(self):
        """A viewport fitted to `bounds` must not clip the rounded line it was handed."""
        points = [[30.0, -95.1234567], [35.0, -90.7654321]]
        (min_lon, min_lat), (max_lon, max_lat) = geo.bounds(points)
        for lon, lat in geo.to_geojson_linestring(points)["coordinates"]:
            self.assertLessEqual(min_lon, lon)
            self.assertLessEqual(lon, max_lon)
            self.assertLessEqual(min_lat, lat)
            self.assertLessEqual(lat, max_lat)

    def test_chord_term_reproduces_a_known_distance(self):
        # The same NY -> LA pair, measured through the term the matcher sorts on.
        here = geo.trig_terms(40.7128, -74.0060)
        there = geo.trig_terms(34.0522, -118.2437)
        self.assertAlmostEqual(
            geo.distance_from_chord(geo.chord_term(here, there)), 2446, delta=20
        )

    def test_chord_term_is_zero_for_identical_points_and_is_symmetric(self):
        here = geo.trig_terms(30.0, -90.0)
        there = geo.trig_terms(41.0, -87.0)
        self.assertEqual(geo.chord_term(here, here), 0.0)
        self.assertAlmostEqual(
            geo.chord_term(here, there), geo.chord_term(there, here), places=12
        )

    def test_chord_term_orders_candidates_like_the_distance(self):
        """The station matcher relies on this: ranking by term == ranking by distance."""
        rng = random.Random(20260101)
        origin_lat, origin_lon = 39.5, -98.35
        origin = geo.trig_terms(origin_lat, origin_lon)
        samples = [
            (rng.uniform(25.0, 49.0), rng.uniform(-124.0, -70.0)) for _ in range(500)
        ]

        ranked_by_term = sorted(
            samples,
            key=lambda point: geo.chord_term(origin, geo.trig_terms(point[0], point[1])),
        )
        distances = [
            geo.haversine_miles(origin_lat, origin_lon, point[0], point[1])
            for point in ranked_by_term
        ]
        self.assertEqual(distances, sorted(distances))

"""Unit tests for the fuel-stop optimiser.

The hand-calculated cases pin the *actual optimum* for small instances, which is a much
stronger guarantee than simply asserting the code runs.
"""

import random

from django.test import SimpleTestCase

from routing.services.optimizer import optimize_fuel_stops

RANGE = 500.0
MPG = 10.0


def candidate(mile: float, price: float) -> dict:
    return {"mile": mile, "price": price}


class OptimizerTests(SimpleTestCase):
    def test_short_trip_needs_no_refuelling(self):
        plan = optimize_fuel_stops([candidate(100, 1.99)], 300.0, RANGE, MPG, 1.0)
        self.assertTrue(plan.feasible)
        self.assertEqual(plan.stops, [])
        self.assertEqual(plan.total_cost, 0.0)
        self.assertEqual(plan.total_gallons_consumed, 30.0)

    def test_gap_beyond_range_is_infeasible(self):
        plan = optimize_fuel_stops([candidate(100, 2.0)], 1200.0, RANGE, MPG, 1.0)
        self.assertFalse(plan.feasible)
        self.assertIn("No fuel station within", plan.reason)

    def test_prefers_the_cheapest_reachable_station(self):
        # Cheapest fuel is at mile 300 ($1), so as much as possible is bought there.
        plan = optimize_fuel_stops(
            [candidate(100, 3.0), candidate(300, 1.0), candidate(700, 2.0)],
            1000.0, RANGE, MPG, 1.0,
        )
        self.assertTrue(plan.feasible)
        self.assertEqual(plan.total_cost, 70.0)
        self.assertEqual([round(s.route_mile) for s in plan.stops], [300, 700])
        self.assertAlmostEqual(plan.total_gallons_purchased, 50.0, places=3)

    def test_multi_stop_plan_matches_hand_calculation(self):
        plan = optimize_fuel_stops(
            [candidate(250, 2.0), candidate(700, 4.0), candidate(1100, 3.0)],
            1200.0, RANGE, MPG, 1.0,
        )
        self.assertTrue(plan.feasible)
        self.assertEqual(plan.total_cost, 220.0)
        self.assertEqual([round(s.route_mile) for s in plan.stops], [250, 700, 1100])
        self.assertAlmostEqual(plan.total_gallons_purchased, 70.0, places=3)

    def test_carries_surplus_forward_from_a_cheap_station(self):
        # A naive "arrive empty at every stop" DP would pay for 5 gal at the $5 stop.
        # The optimum tops up the tank at the $1 stop instead: 5 gal + 5 gal.
        plan = optimize_fuel_stops(
            [candidate(50, 1.0), candidate(200, 5.0)], 600.0, RANGE, MPG, 1.0
        )
        self.assertEqual(plan.total_cost, 30.0)
        self.assertEqual([round(s.route_mile) for s in plan.stops], [50, 200])

    def test_no_fill_when_the_initial_tank_suffices(self):
        plan = optimize_fuel_stops(
            [candidate(10, 0.99), candidate(400, 0.99)], 450.0, RANGE, MPG, 1.0
        )
        self.assertEqual(plan.stops, [])
        self.assertEqual(plan.total_cost, 0.0)

    def test_min_price_advantage_stops_the_solver_chasing_cents(self):
        """A stop only counts as worth diverting to when it beats the current price by the
        configured margin; otherwise the tank is filled where the vehicle already is."""
        stations = [candidate(100, 3.00), candidate(400, 2.99)]

        chased = optimize_fuel_stops(stations, 800.0, RANGE, MPG, 1.0, 0.0)
        padded = optimize_fuel_stops(stations, 800.0, RANGE, MPG, 1.0, 0.02)

        # A cent cheaper justifies the detour, so every gallon comes from mile 400.
        self.assertEqual([round(stop.route_mile) for stop in chased.stops], [400])
        # Two cents does not, so the first purchase happens at mile 100 instead.
        self.assertIn(100, [round(stop.route_mile) for stop in padded.stops])
        # Buying in two places instead of one is never the cheaper plan.
        self.assertLessEqual(chased.total_cost, padded.total_cost)

    def test_stations_at_or_beyond_the_destination_are_ignored(self):
        plan = optimize_fuel_stops(
            [candidate(0.0, 1.0), candidate(500.0, 1.0)], 400.0, RANGE, MPG, 1.0
        )
        self.assertEqual(plan.stops, [])

    def test_invariants_hold_on_random_instances(self):
        rng = random.Random(20260101)
        for _ in range(200):
            total = rng.uniform(900.0, 4000.0)
            miles = [rng.uniform(1.0, total - 1.0) for _ in range(rng.randint(6, 25))]
            # guarantee coverage so the instance is always feasible
            miles += [i * 450.0 for i in range(1, int(total // 450) + 1)]
            miles = sorted(m for m in miles if 0.0 < m < total)
            candidates = [candidate(m, round(rng.uniform(2.5, 5.5), 3)) for m in miles]

            plan = optimize_fuel_stops(candidates, total, RANGE, MPG, 1.0)
            self.assertTrue(plan.feasible)

            # conservation: a full tank is free, so we buy exactly what we burn minus it
            self.assertAlmostEqual(
                plan.total_gallons_purchased, total / MPG - 50.0, places=3
            )

            # never a leg longer than the vehicle's range
            markers = [0.0] + [s.route_mile for s in plan.stops] + [total]
            longest = max(b - a for a, b in zip(markers, markers[1:]))
            self.assertLessEqual(longest, RANGE + 1e-6)

            # purchased gallons are sane, and cost is consistent with price x gallons
            for stop in plan.stops:
                self.assertGreaterEqual(stop.gallons, 0.0)
                self.assertLessEqual(stop.gallons, 50.0 + 1e-6)
                self.assertAlmostEqual(stop.cost, stop.gallons * stop.price, places=2)

    def test_matches_exhaustive_search_on_small_instances(self):
        """Greedy must never be beaten by a brute-force search over feasible plans."""
        instances = [
            [candidate(50, 1.0), candidate(200, 5.0)],
            [candidate(250, 2.0), candidate(700, 4.0), candidate(1100, 3.0)],
            [candidate(120, 3.7), candidate(310, 2.2), candidate(640, 4.9)],
            [candidate(90, 4.4), candidate(480, 1.8), candidate(760, 3.3)],
        ]
        for stations, total in zip(instances, (600.0, 1200.0, 900.0, 1000.0)):
            plan = optimize_fuel_stops(stations, total, RANGE, MPG, 1.0)
            self.assertTrue(plan.feasible)
            best = _exhaustive_min_cost(stations, total, RANGE, MPG, step=1.0)
            self.assertIsNotNone(best)
            # optimal <= any feasible plan found by brute force
            self.assertLessEqual(plan.total_cost, best + 1e-6)
            # ...and not worse by more than the brute force's 1-gallon grid resolution
            self.assertLessEqual(best - plan.total_cost, 6.0)


def _exhaustive_min_cost(stations, total, range_miles, mpg, step):
    """Reference solver: enumerate purchase amounts on a fixed grid.

    Only used to cross-check the greedy on tiny instances; it is exponential and
    deliberately excluded from the production code path.
    """
    capacity = range_miles / mpg
    gallons_per_mile = 1.0 / mpg
    nodes = [{"mile": 0.0, "price": None}]
    nodes += [
        {"mile": s["mile"], "price": s["price"]}
        for s in sorted(stations, key=lambda s: s["mile"])
        if 0.0 < s["mile"] < total
    ]
    nodes.append({"mile": total, "price": None})

    for earlier, later in zip(nodes, nodes[1:]):
        if later["mile"] - earlier["mile"] > range_miles + 1e-9:
            return None

    best = float("inf")

    def recurse(index, fuel, cost):
        nonlocal best
        if cost >= best:
            return
        if index == len(nodes) - 1:
            best = cost
            return
        here = nodes[index]
        leg = nodes[index + 1]["mile"] - here["mile"]
        if here["price"] is None:
            purchases = [0.0]
        else:
            room = capacity - fuel
            purchases = [i * step for i in range(int(room // step) + 1)]
        for buy in purchases:
            remaining = fuel + buy - leg * gallons_per_mile
            if remaining < -1e-9:
                continue
            recurse(index + 1, max(0.0, remaining), cost + buy * (here["price"] or 0.0))

    recurse(0, capacity, 0.0)
    return best


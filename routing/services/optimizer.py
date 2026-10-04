"""Cost-optimal fuel-stop selection along a fixed route.

Model
-----
* Tank capacity  = ``max_range_miles / mpg``  (500 mi / 10 mpg = 50 gal).
* The vehicle departs with ``initial_fuel_fraction`` of a tank (default: full).  Fuel
  already in the tank on departure is a sunk cost and is *not* part of the trip spend.
* Fuel can only be bought at truck stops matched to the route.
* Objective: minimise money spent on fuel while never running the tank dry.

Algorithm
---------
The classic optimal greedy for the "gas station problem" with a finite tank:

At each stop, look forward within one tank of range for the **nearest** station that is
strictly cheaper than the current price (the destination always counts as a valid
target).  If one exists, buy just enough to reach it and arrive empty.  If none exists,
no cheaper fuel is reachable, so fill the tank before moving on.

This is optimal because fuel bought at a cheaper station always dominates fuel that would
otherwise have to be bought earlier at a higher price; carrying surplus only ever forces
you to forgo a cheaper future purchase.

The look-ahead is a linear scan of the stops inside one tank of range.  That is bounded
and small in practice - the caller has already thinned the candidates down to one station
per 25-mile stretch - so the whole solver stays well under a millisecond.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

EPSILON = 1e-9


@dataclass
class FuelStop:
    """A single purchase made at a truck stop."""

    route_mile: float
    price: float
    gallons: float
    cost: float
    tank_before_gallons: float
    tank_after_gallons: float
    station: dict = field(default_factory=dict)


@dataclass
class FuelPlan:
    """Outcome of the optimisation."""

    stops: list[FuelStop]
    total_cost: float
    total_gallons_purchased: float
    total_gallons_consumed: float
    feasible: bool = True
    reason: str | None = None


@dataclass
class _Node:
    """A point on the route where the tank may be topped up.

    The two endpoints are nodes too, so the solver never needs a special case for them.
    Neither is purchasable: the origin carries an infinite price (so any real station beats
    it) and the destination carries zero (so it is always worth driving to).
    """

    mile: float
    price: float
    station: dict = field(default_factory=dict)



def _build_nodes(candidates: list[dict], total_miles: float) -> list[_Node]:
    """Sort the purchasable stops between the two endpoints, dropping any off the route."""
    nodes = [_Node(mile=0.0, price=math.inf)]
    for candidate in sorted(candidates, key=lambda candidate: candidate["mile"]):
        mile = float(candidate["mile"])
        if EPSILON < mile < total_miles - EPSILON:
            nodes.append(_Node(mile=mile, price=float(candidate["price"]), station=candidate))
    nodes.append(_Node(mile=float(total_miles), price=0.0))
    return nodes


def _first_unreachable_gap(
    nodes: list[_Node], max_range_miles: float
) -> tuple[float, float] | None:
    """The first pair of neighbouring nodes further apart than the tank allows, if any."""
    for previous, current in zip(nodes, nodes[1:]):
        if current.mile - previous.mile > max_range_miles + EPSILON:
            return previous.mile, current.mile
    return None


def _next_target(
    nodes: list[_Node], index: int, max_range_miles: float, min_price_advantage: float
) -> int | None:
    """Index of the nearest node within one tank that is worth driving to.

    A node qualifies when it beats the current price by at least ``min_price_advantage``,
    or when it is the destination - reaching the destination is the entire point of the
    trip, so it counts even though its sentinel price makes it look expensive.

    ``None`` means nothing cheaper is within reach, which tells the caller to fill up.
    """
    here = nodes[index]
    destination = len(nodes) - 1
    for ahead in range(index + 1, len(nodes)):
        if nodes[ahead].mile - here.mile > max_range_miles + EPSILON:
            return None
        if ahead == destination or nodes[ahead].price < here.price - min_price_advantage:
            return ahead
    return None


def _buy_fuel(node: _Node, gallons: float, fuel_before: float, fuel_after: float) -> FuelStop:
    """Record a purchase of ``gallons`` made at ``node``."""
    return FuelStop(
        route_mile=round(node.mile, 3),
        price=round(node.price, 4),
        gallons=round(gallons, 4),
        cost=round(gallons * node.price, 4),
        tank_before_gallons=round(fuel_before, 4),
        tank_after_gallons=round(fuel_after, 4),
        station=node.station,
    )


def optimize_fuel_stops(
    candidates: list[dict],
    total_miles: float,
    max_range_miles: float,
    mpg: float,
    initial_fuel_fraction: float = 1.0,
    min_price_advantage: float = 0.0,
) -> FuelPlan:
    """Choose the cheapest set of fuel stops for a route of ``total_miles``.

    ``candidates`` is an iterable of ``{"mile": float, "price": float, ...}``; any extra
    keys are carried through onto the resulting :class:`FuelStop` objects.

    ``min_price_advantage`` is the smallest per-gallon saving (USD) that justifies
    diverting to a station.  With ``0.0`` the solver chases every fraction of a cent and
    can produce dozens of tiny purchases; a few cents keeps the plan practical without
    materially changing the cost.
    """
    if mpg <= 0:
        raise ValueError("mpg must be positive")
    capacity = max_range_miles / mpg
    gallons_per_mile = 1.0 / mpg
    total_consumed = total_miles * gallons_per_mile
    nodes = _build_nodes(candidates, total_miles)

    gap = _first_unreachable_gap(nodes, max_range_miles)
    if gap is not None:
        return FuelPlan(
            stops=[],
            total_cost=0.0,
            total_gallons_purchased=0.0,
            total_gallons_consumed=round(total_consumed, 4),
            feasible=False,
            reason=(
                f"No fuel station within the {max_range_miles:.0f}-mile range between "
                f"mile {gap[0]:.0f} and mile {gap[1]:.0f}."
            ),
        )

    fuel = capacity * max(0.0, min(1.0, initial_fuel_fraction))
    cost = 0.0
    purchased = 0.0
    stops: list[FuelStop] = []
    index = 0
    last = len(nodes) - 1

    while index < last:
        here = nodes[index]
        target = _next_target(nodes, index, max_range_miles, min_price_advantage)

        if target is None:
            # No cheaper fuel is within reach, so leave the stop with a full tank.
            gallons = capacity - fuel
            if gallons > EPSILON:
                cost += gallons * here.price
                purchased += gallons
                stops.append(_buy_fuel(here, gallons, fuel, capacity))
                fuel = capacity
            fuel -= (nodes[index + 1].mile - here.mile) * gallons_per_mile
            index += 1
            continue

        # Cheaper fuel is reachable: buy only enough to arrive there empty.
        leg_miles = nodes[target].mile - here.mile
        gallons = leg_miles * gallons_per_mile - fuel
        if gallons > EPSILON:
            cost += gallons * here.price
            purchased += gallons
            stops.append(_buy_fuel(here, gallons, fuel, fuel + gallons))
            fuel += gallons
        fuel -= leg_miles * gallons_per_mile
        index = target

    return FuelPlan(
        stops=stops,
        total_cost=round(cost, 2),
        total_gallons_purchased=round(purchased, 4),
        total_gallons_consumed=round(total_consumed, 4),
    )

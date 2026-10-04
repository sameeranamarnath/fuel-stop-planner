# Spotter — Fuel Route Planner

Give the API a start and a finish in the USA and it returns the driving route as GeoJSON, the
cost-optimal set of fuel stops for a vehicle with a 500-mile range doing 10 MPG, and the total
money spent on fuel.

Stations come from the supplied OPIS price file. The backend is Django 5.2 + DRF, the client is
React + Vite. A request makes one upstream routing call; a repeat of the same pair is served
from the database.

Live: <https://spotter-fuel-route-web.vercel.app> (client) and
<https://spotter-fuel-route.vercel.app> (API, which redirects `/` to the API docs).

## Layout

| path | what |
| --- | --- |
| `config/` | Django project — settings, URLs, WSGI/ASGI entrypoints |
| `routing/` | the API app: models, views, serializers, `services/` |
| `web/` | React client |
| `data/` | bundled US gazetteer and truck-stop coordinates |
| `scripts/` | data builds, load test, CLI, deploy |
| `postman/` | Postman collection |

## Run it

**API, with Docker:**

```bash
docker compose up --build
curl -s -X POST http://127.0.0.1:8000/api/v1/fuel-plan/ \
  -H 'Content-Type: application/json' \
  -d '{"start": "New York, NY", "finish": "Los Angeles, CA"}'
```

**API, without Docker:**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py load_fuel_prices
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

**Client:**

```powershell
cd web
npm install
npm run dev
```

It expects the API on `http://127.0.0.1:8000`. Point it elsewhere with `VITE_API_BASE_URL` in
`web/.env`, and add that origin to `DJANGO_CORS_ALLOWED_ORIGINS` on the API.

## API

| method | path | what |
| --- | --- | --- |
| POST | `/api/v1/fuel-plan/` | plan a route and choose the cost-optimal fuel stops |
| GET | `/api/v1/fuel-plan/?start=..&finish=..` | the same, for quick checks |
| GET | `/api/v1/stations/` | browse the catalogue — `state`, `city`, `max_price`, `limit` |
| GET | `/api/v1/health/` | liveness plus the configuration the planner is running with |
| GET | `/api/v1/ready/` | 503 until the price file has been loaded |
| GET | `/api/v1/docs/`, `/api/v1/redoc/`, `/api/v1/schema/` | OpenAPI 3 schema and viewers |

Request:

```json
{"start": "New York, NY", "finish": "Los Angeles, CA"}
```

`start` and `finish` each take either a US place name (`"City, ST"`) or an explicit
`{"lat": 40.71, "lon": -74.01}`.

Response, abridged:

```json
{
  "start":  {"latitude": 40.7128, "longitude": -74.006, "label": "New York, NY", "source": "gazetteer"},
  "finish": {"latitude": 34.0522, "longitude": -118.2437, "label": "Los Angeles, CA", "source": "gazetteer"},
  "vehicle": {"max_range_miles": 500.0, "mpg": 10.0, "tank_capacity_gallons": 50.0},
  "route": {
    "provider": "osrm",
    "distance_miles": 2774.7,
    "duration_hours": 49.8,
    "geometry": {"type": "LineString", "coordinates": [[-74.006, 40.7128], "..."]},
    "bounds": [[-122.5, 33.9], [-73.9, 40.8]]
  },
  "fuel_stops": [
    {
      "sequence": 1, "name": "SPEEDWAY #1439", "city": "Mc Calla", "state": "AL",
      "price_per_gallon": 2.902, "distance_from_start_miles": 382.0,
      "latitude": 33.3, "longitude": -87.0,
      "gallons_purchased": 38.2, "cost_usd": 110.86
    }
  ],
  "summary": {
    "total_distance_miles": 2774.7, "total_gallons_consumed": 277.5,
    "total_gallons_purchased": 227.5, "total_fuel_cost_usd": 681.41,
    "average_price_per_gallon": 3.0, "number_of_fuel_stops": 12,
    "stations_considered_on_route": 812, "feasible": true
  },
  "geojson": {"type": "FeatureCollection", "features": ["..."]},
  "external_api_calls": {"geocoding_calls": 0, "routing_calls": 1, "external_calls_total": 1},
  "elapsed_ms": 1350.8
}
```

`geojson` is a ready `FeatureCollection` — one `LineString` for the route plus one `Point` per
stop — so a map client can render it without transformation.

Errors are always `{"error": {"code": "...", "detail": "..."}}`:

| status | code | when |
| --- | --- | --- |
| 400 | `validation_error` | missing or malformed `start` / `finish` |
| 422 | `location_not_found` | the place name could not be resolved |
| 409 | `route_infeasible` | no station within range at some point on the route |
| 502 | `routing_provider_error` | the upstream routing provider failed |

Every plan response carries `X-Upstream-Calls`, `X-Cache` (`HIT`/`MISS`) and `X-Latency-Ms`.

## How a plan is produced

1. **Resolve the endpoints.** `"City, ST"` is looked up in a bundled US Census gazetteer
   (50,533 places), so a normal request makes no geocoding call at all. Anything that misses
   falls back to the provider.
2. **Route once.** A single OSRM call returns the geometry, distance and duration. The result is
   cached against the endpoint pair, so a repeat costs nothing.
3. **Match stations to the route.** The polyline is resampled to ~1-mile steps and each station
   is tested against the corridor (`SPOTTER_STATION_OFFSET_MILES`, default 25 miles).
4. **Choose the stops.** Fuel is a minimum-cost problem, not a shortest-path one. The solver
   walks the stops with a 500-mile horizon: at each station it buys just enough to reach the
   first cheaper station within range, or fills the tank if none is. That is optimal for a fixed
   tank and consumption, and `routing/tests/test_optimizer.py` verifies it against an exhaustive
   search.
5. **Total it up.** Gallons are miles / MPG over each leg, priced at the stop's rate.
   `SPOTTER_INITIAL_FUEL_FRACTION` (default 1.0) means the truck departs full and that fuel is a
   sunk cost, so it is not billed.

## Configuration

Every value is environment-driven with a working default; see `.env.example`.

| variable | default | notes |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | dev value | set a real one in production |
| `DJANGO_DEBUG` | `True` | `False` in production |
| `DJANGO_ALLOWED_HOSTS` | `*` | comma-separated |
| `DJANGO_CORS_ALLOWED_ORIGINS` | empty | the web client's origin |
| `SPOTTER_MPG` | `10` | vehicle economy |
| `SPOTTER_MAX_RANGE_MILES` | `500` | usable range on a full tank |
| `SPOTTER_INITIAL_FUEL_FRACTION` | `1.0` | 1.0 = depart with a full tank |
| `SPOTTER_STATION_OFFSET_MILES` | `25` | corridor half-width for station matching |
| `SPOTTER_ROUTING_PROVIDER` | `osrm` | `osrm` or `ors` |
| `SPOTTER_GEOCODING_PROVIDER` | `nominatim` | `nominatim` or `ors` |
| `ORS_API_KEY` | empty | only needed for the `ors` providers |
| `SPOTTER_MIN_STATION_SPACING_MILES` | `25` | keeps only the cheapest stop per stretch |
| `SPOTTER_CACHE_ENABLED` | `True` | cache resolved routes and geocodes in the database |

## Tests

```powershell
.\.venv\Scripts\python.exe manage.py test routing
```

70 tests covering the optimizer (including a brute-force cross-check), station matching, offline
place resolution, the API contract and the error paths.

## Deploy

The API and the client are two Vercel projects, deployed with the CLI.

```bash
vercel deploy --prod --yes             # API, from the repository root
cd web && vercel deploy --prod --yes   # client
```

Set `VITE_API_BASE_URL` on the client project to the API origin, and add that origin to
`DJANGO_CORS_ALLOWED_ORIGINS` on the API.

Vercel Functions serve a read-only bundle with a writable `/tmp`, and the planner caches
geocodes and routes in the database, so `config/bootstrap.py` stages the database into `/tmp` on
the first request of each instance. Vercel reads either `WSGI_APPLICATION` or `ASGI_APPLICATION`
and this project declares both, so the staging runs from both entrypoints.

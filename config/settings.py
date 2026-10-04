"""Django settings for the Spotter fuel-route API.

All tunables are environment-overridable so the container/CI can change behaviour
without touching code (see ``.env.example``).
"""

import os
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return default


# Vercel Functions boot from a read-only bundle with a small writable /tmp, and the platform
# exports VERCEL=1 so the app can tell where it is running.
ON_VERCEL = _env_bool("VERCEL", False)


# --------------------------------------------------------------------------
# Core Django
# --------------------------------------------------------------------------
SECRET_KEY = _env("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me")
DEBUG = _env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    host.strip()
    for host in _env("DJANGO_ALLOWED_HOSTS", "*").split(",")
    if host.strip()
]
# Vercel tells each deployment its own hostname; adding it keeps generated domains working
# even when ALLOWED_HOSTS has been locked down.
if os.environ.get("VERCEL_URL"):
    ALLOWED_HOSTS.append(os.environ["VERCEL_URL"])

if ON_VERCEL:
    # The platform terminates TLS and forwards the scheme, so this is what makes
    # request.is_secure() - and therefore cookie handling - correct behind it.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "routing.apps.RoutingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Locally the database sits next to the code, and the Vercel build writes it there too by
# exporting SPOTTER_DB_PATH (see vercel.json).  At run time Vercel serves from a read-only
# bundle and does not set that variable, so the database is staged into the writable /tmp
# instead - see config/bootstrap.py.
DB_PATH = Path(_env("SPOTTER_DB_PATH", str(BASE_DIR / "db.sqlite3")))
if ON_VERCEL and not os.environ.get("SPOTTER_DB_PATH"):
    DB_PATH = Path(tempfile.gettempdir()) / "spotter.sqlite3"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DB_PATH,
        "OPTIONS": {
            # Parallel instances can briefly contend for the write lock; wait for it
            # instead of failing the request with "database is locked".
            "timeout": 20,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
if ON_VERCEL:
    # There is no writable directory in the bundle for collectstatic output to rely on, so
    # let WhiteNoise resolve the app's static files straight from the finders.
    WHITENOISE_USE_FINDERS = True
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "routing.exceptions.api_exception_handler",
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Spotter Fuel Route Planner API",
    "VERSION": "1.0.0",
    "DESCRIPTION": (
        "Given a start and finish inside the USA, returns the driving route as GeoJSON, "
        "the cost-optimal fuel stops for a vehicle with a 500-mile range doing 10 MPG, and "
        "the total money spent on fuel.\n\n"
        "Exactly one upstream routing call is made per origin/destination pair (zero when "
        "cached); geocoding is resolved from a bundled US gazetteer, and station matching, "
        "the optimiser and the cost total all run locally."
    ),
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
}

# --------------------------------------------------------------------------
# Domain configuration (vehicle, matching, providers, caching)
# --------------------------------------------------------------------------
SPOTTER = {
    # Vehicle
    "MPG": _env_float("SPOTTER_MPG", 10.0),
    "MAX_RANGE_MILES": _env_float("SPOTTER_MAX_RANGE_MILES", 500.0),
    # 1.0 == depart with a full tank (its cost is not part of the trip spend)
    "INITIAL_FUEL_FRACTION": _env_float("SPOTTER_INITIAL_FUEL_FRACTION", 1.0),
    # How far off the route a truck stop may sit and still count as "on the route".  Stop
    # positions are city centroids rather than forecourts, so the corridor is generous.
    "STATION_OFFSET_MILES": _env_float("SPOTTER_STATION_OFFSET_MILES", 25.0),
    # Optional: require a station to beat the current price by this much before it is
    # worth diverting to.  Default 0 keeps the solver at the true cost optimum; the
    # station-thinning step below is what removes the impractical micro-stops.
    "MIN_PRICE_ADVANTAGE_PER_GALLON": _env_float(
        "SPOTTER_MIN_PRICE_ADVANTAGE_PER_GALLON", 0.0
    ),
    # Truck stops cluster; only the cheapest one in each stretch of this length is
    # considered as a purchase point.
    "MIN_STATION_SPACING_MILES": _env_float("SPOTTER_MIN_STATION_SPACING_MILES", 25.0),
    # Providers: "osrm"/"ors" for routing, "nominatim"/"ors" for geocoding
    "ROUTING_PROVIDER": _env("SPOTTER_ROUTING_PROVIDER", "osrm"),
    "GEOCODING_PROVIDER": _env("SPOTTER_GEOCODING_PROVIDER", "nominatim"),
    "ORS_API_KEY": _env("ORS_API_KEY", ""),
    "HTTP_TIMEOUT_SECONDS": _env_float("SPOTTER_HTTP_TIMEOUT_SECONDS", 20.0),
    "OSRM_BASE_URL": _env("SPOTTER_OSRM_BASE_URL", "https://router.project-osrm.org"),
    "NOMINATIM_BASE_URL": _env(
        "SPOTTER_NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"
    ),
    "ORS_BASE_URL": _env("SPOTTER_ORS_BASE_URL", "https://api.openrouteservice.org"),
    "USER_AGENT": _env("SPOTTER_USER_AGENT", "spotter-fuel-route/1.0"),
    # Persisted so repeat requests make zero external calls
    "CACHE_ENABLED": _env_bool("SPOTTER_CACHE_ENABLED", True),
    # Geometry resolution (miles between consecutive points).  The persisted polyline is
    # also what station matching runs against, so it is kept fine enough to be accurate
    # and coarse enough to stay fast.
    "GEOMETRY_SPACING_MILES": _env_float("SPOTTER_GEOMETRY_SPACING_MILES", 1.0),
    "OUTPUT_GEOMETRY_SPACING_MILES": _env_float("SPOTTER_OUTPUT_GEOMETRY_SPACING_MILES", 2.0),
    # Ceiling on the response polyline.  A coast-to-coast route at 2-mile spacing would be
    # ~1,400 vertices (~80 KB); capping keeps the payload small without visibly changing
    # the shape on a map.  Matching still runs against the finer polyline.
    "MAX_OUTPUT_GEOMETRY_POINTS": _env_float("SPOTTER_MAX_OUTPUT_GEOMETRY_POINTS", 600),
    # Data artefacts generated offline by the scripts/ directory (committed to the repo)
    "PLACE_COORDS_PATH": _env(
        "SPOTTER_PLACE_COORDS_PATH", str(BASE_DIR / "data" / "place_coords.json")
    ),
    "US_PLACES_PATH": _env(
        "SPOTTER_US_PLACES_PATH", str(BASE_DIR / "data" / "us_places.json")
    ),
}

# The web client is served from its own origin, so the API has to name it.
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _env("DJANGO_CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": _env("DJANGO_LOG_LEVEL", "INFO")},
}

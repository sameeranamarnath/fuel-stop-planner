"""ASGI entrypoint for the Spotter fuel-route API.

Vercel reads ``ASGI_APPLICATION`` from the settings and will serve this callable in
preference to the WSGI one, so the database staging has to happen here too - see
``config.bootstrap``.  Off Vercel, ``prepare_environment`` does nothing.

https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

from config.bootstrap import prepare_environment

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()

prepare_environment()


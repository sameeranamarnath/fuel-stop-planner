"""WSGI entrypoint for the Spotter fuel-route API.

``get_wsgi_application`` builds the callable that gunicorn and Vercel both serve.  Vercel
hands the app a read-only bundle, so the database is staged into the writable ``/tmp``
before the first request is handled; everywhere else that step is skipped entirely.

https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

from config.bootstrap import prepare_environment

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

prepare_environment()


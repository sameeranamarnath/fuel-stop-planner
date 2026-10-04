FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SECRET_KEY=container-demo-secret \
    DJANGO_ALLOWED_HOSTS=*

WORKDIR /app

# Dependencies first, so application edits do not invalidate the layer cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake the schema and the fuel catalogue into the image.  Import reads the committed CSV
# plus data/place_coords.json, so this needs no network and the container is ready to serve
# as soon as it starts - no setup step for the reviewer.
RUN python manage.py migrate --noinput \
 && python manage.py load_fuel_prices \
 && python manage.py collectstatic --noinput

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/',timeout=4)" || exit 1

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-"]

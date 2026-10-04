"""Make the database usable on a read-only, ephemeral host (Vercel Functions).

The bundle Vercel boots from is read-only and the only writable directory is ``/tmp``.
SQLite needs a writable directory for its journal, and this planner *persists* every
geocode and route it resolves, so the database cannot be used straight out of the bundle.

On the first request of a new instance the build-time database is copied into ``/tmp``.
If the build produced none - a build that never ran the ``buildCommand``, or a bundle that
left it behind - the database is created here with the same two commands the README uses,
so the instance still comes up serving real fuel prices rather than 500ing.

Nothing here runs outside Vercel; ``config.wsgi`` calls it only when ``ON_VERCEL`` is set.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

BUNDLED_DB = Path(__file__).resolve().parent.parent / "db.sqlite3"

# Vercel can serve several requests through one instance, so two of them could reach this
# module at the same moment.  A plain lock is enough: each instance has its own /tmp, so
# there is no cross-process race to worry about.
_PREPARE_LOCK = threading.Lock()


def ensure_database(target: Path) -> None:
    """Guarantee that ``target`` holds a usable database before anything queries it."""
    if target.exists():
        return

    with _PREPARE_LOCK:
        if target.exists():  # another request prepared it while we waited
            return
        if BUNDLED_DB.exists():
            _copy(BUNDLED_DB, target)
            logger.info("staged the bundled database at %s", target)
            return
        logger.warning("%s is absent; building a database at %s", BUNDLED_DB, target)
        _build(target)


def prepare_environment() -> None:
    """Stage the database when the app is running on Vercel.

    Called from *both* entrypoints (``config.wsgi`` and ``config.asgi``) because Vercel picks
    whichever one the project declares through ``WSGI_APPLICATION`` /
    ``ASGI_APPLICATION``, and this app declares both.  Off Vercel it does nothing.
    """
    from django.conf import settings

    if settings.ON_VERCEL:
        ensure_database(settings.DB_PATH)


def _copy(source: Path, target: Path) -> None:
    """Copy via a temporary file so a concurrent reader never sees a partial database."""
    source.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f"{target.name}.{os.getpid()}.staged")
    shutil.copyfile(source, staged)
    os.replace(staged, target)


def _build(target: Path) -> None:
    from django.core.management import call_command

    target.parent.mkdir(parents=True, exist_ok=True)
    call_command("migrate", interactive=False, verbosity=0)
    call_command("load_fuel_prices", verbosity=0)

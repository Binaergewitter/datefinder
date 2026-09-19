"""CLI entry points for the datefinder application."""

import os
import sys


def _automigrate_sqlite() -> None:
    """Create the schema for the zero-config SQLite fallback before serving.

    `nix run`/`datefinder-server` has no separate migrate step, so without
    this every request 500s with "no such table" on a fresh state dir.
    Postgres deployments migrate via the systemd ExecStartPre instead;
    touching an external DB silently at boot would be surprising there.
    """
    import django
    from django.conf import settings
    from django.core.management import call_command

    django.setup()

    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
        return
    call_command("migrate", "--noinput", verbosity=0)
    # ready() generated the iCal file against a pre-migrate (or empty) DB;
    # regenerate now that the schema exists so /export/calendar.ics is served.
    import logging

    from calendar_app import ical

    try:
        ical.generate_ical_file()
    except Exception:
        logging.getLogger(__name__).warning("Failed to generate iCal file after automigrate", exc_info=True)


def server():
    """Run the daphne ASGI server."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'datefinder.settings')

    host = os.environ.get('HOST', '0.0.0.0')
    port = os.environ.get('PORT', '8000')

    _automigrate_sqlite()

    from daphne.cli import CommandLineInterface

    sys.argv = ['daphne', '-b', host, '-p', port, 'datefinder.asgi:application']
    CommandLineInterface.entrypoint()


def manage():
    """Run Django management commands."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'datefinder.settings')

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)

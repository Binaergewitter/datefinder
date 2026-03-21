"""CLI entry points for the datefinder application."""

import os
import sys


def server():
    """Run the daphne ASGI server."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'datefinder.settings')

    host = os.environ.get('HOST', '0.0.0.0')
    port = os.environ.get('PORT', '8000')

    from daphne.cli import CommandLineInterface

    sys.argv = ['daphne', '-b', host, '-p', port, 'datefinder.asgi:application']
    CommandLineInterface.entrypoint()


def manage():
    """Run Django management commands."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'datefinder.settings')

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)

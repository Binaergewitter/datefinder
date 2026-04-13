from django.apps import AppConfig


class CalendarAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "calendar_app"
    verbose_name = "Calendar App"

    def ready(self):
        """
        Called when the app is ready.
        Generates the initial iCal file.
        """
        import sys

        # Skip iCal generation during migrate/test commands - tables may not exist yet
        if len(sys.argv) >= 2 and sys.argv[1] in ("migrate", "test", "makemigrations"):
            return

        from . import ical

        try:
            ical.generate_ical_file()
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to generate initial iCal file: {e}")

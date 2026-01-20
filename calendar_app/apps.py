from django.apps import AppConfig


class CalendarAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'calendar_app'
    verbose_name = 'Calendar App'

    def ready(self):
        """
        Called when the app is ready.
        Generates the initial iCal file.
        """
        from . import ical
        try:
            ical.generate_ical_file()
        except Exception as e:
            # Log the error, but don't prevent startup
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to generate initial iCal file on startup: {e}", exc_info=True)
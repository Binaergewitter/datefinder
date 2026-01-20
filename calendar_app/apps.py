from django.apps import AppConfig


class CalendarAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'calendar_app'
    verbose_name = 'Calendar App'

    def ready(self):
        """Called when the app is ready. Generate iCal file on startup."""
        # Import here to avoid circular imports
        from .ical import generate_ical_file
        import logging
        
        logger = logging.getLogger(__name__)
        try:
            generate_ical_file()
            logger.info("iCal file generated on startup")
        except Exception as e:
            logger.error(f"Failed to generate iCal file on startup: {e}")

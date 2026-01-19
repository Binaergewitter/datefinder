from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings


class CustomAccountAdapter(DefaultAccountAdapter):
    """Custom adapter to control registration availability."""

    def is_open_for_signup(self, request):
        """Return True if registration is enabled, False otherwise."""
        return getattr(settings, 'REGISTRATION_ENABLED', True)

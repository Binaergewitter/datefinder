from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings


class CustomAccountAdapter(DefaultAccountAdapter):
    """Custom adapter to control registration availability."""

    def is_open_for_signup(self, request):
        """Return True if registration is enabled, False otherwise.
        
        This only affects regular form-based signup, not social login.
        """
        return getattr(settings, 'REGISTRATION_ENABLED', False)


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom social account adapter to always allow social login signup."""

    def is_open_for_signup(self, request, sociallogin):
        """Always allow signup via social providers (Keycloak, etc.)."""
        return True

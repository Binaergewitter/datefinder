from django.conf import settings

from datefinder import __version__


def app_version(request):
    """Expose the application version to every template (shown in the header)."""
    return {"app_version": __version__}


def registration_settings(request):
    """Make registration settings available in templates."""
    return {
        'registration_enabled': getattr(settings, 'REGISTRATION_ENABLED', False),
        'local_login_enabled': getattr(settings, 'LOCAL_LOGIN_ENABLED', True),
    }

from django.conf import settings


def registration_settings(request):
    """Make registration settings available in templates."""
    return {
        'registration_enabled': getattr(settings, 'REGISTRATION_ENABLED', True),
    }

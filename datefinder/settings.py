"""
Django settings for datefinder project.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
PACKAGE_DIR = Path(__file__).resolve().parent  # datefinder/ package directory
BASE_DIR = PACKAGE_DIR.parent
STATEDIR = Path(os.getenv("STATEDIR", "/tmp")).resolve()  # there is no reliable way to use Path.cwd()


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable must be set")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DEBUG", "").lower() == "true"
if DEBUG and not os.getenv("DEBUG"):
    DEBUG = False

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",")
if not ALLOWED_HOSTS and not DEBUG:
    raise ValueError("ALLOWED_HOSTS must be set in production")

# Security headers (enabled when not in debug mode)
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Reverse proxy configuration
# Set SITE_URL to the external URL when running behind a reverse proxy
# e.g., SITE_URL=https://plan.binaergewitter.de
SITE_URL = os.getenv("SITE_URL", "")

# Trust the X-Forwarded-Host header from the reverse proxy
USE_X_FORWARDED_HOST = os.getenv("USE_X_FORWARDED_HOST", "False").lower() == "true"

# Trust the X-Forwarded-Proto header to detect HTTPS
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https") if os.getenv("TRUST_PROXY_HEADERS", "False").lower() == "true" else None
)

# CSRF trusted origins - required for HTTPS behind a reverse proxy
# Automatically add SITE_URL if configured
_csrf_origins = os.getenv("CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in _csrf_origins.split(",") if origin.strip()]
if SITE_URL and SITE_URL not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(SITE_URL)

# Application definition
INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    # Allauth
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
    # Channels
    "channels",
    # Our apps
    "calendar_app",
    "health",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "datefinder.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [PACKAGE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "calendar_app.context_processors.registration_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "datefinder.wsgi.application"
ASGI_APPLICATION = "datefinder.asgi.application"

# Channels layer configuration
REDIS_URL = os.getenv("REDIS_URL", "")
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [REDIS_URL],
            },
        },
    }
else:
    # Use in-memory channel layer for development
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Database configuration
# Supports DATABASE_URL for PostgreSQL: postgres:///dbname (unix socket) or postgres://user:pass@host:port/dbname
# Falls back to SQLite via DATABASE_PATH if DATABASE_URL is not set
DATABASE_URL = os.getenv("DATABASE_URL", "")

if DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")):
    _db_url = urlparse(DATABASE_URL)
    _db_conf: dict[str, object] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _db_url.path.lstrip("/"),
        "USER": _db_url.username or "",
        "PASSWORD": _db_url.password or "",
    }
    if _db_url.hostname:
        _db_conf["HOST"] = _db_url.hostname
        _db_conf["PORT"] = str(_db_url.port or 5432)
    else:
        # Unix socket connection
        _db_conf["HOST"] = os.getenv("DATABASE_SOCKET_DIR", "/run/postgresql")

    DATABASES = {"default": _db_conf}
else:
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(STATEDIR / "db.sqlite3"))
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATABASE_PATH,
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = STATEDIR / "staticfiles"
STATICFILES_DIRS = [PACKAGE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"
WHITENOISE_USE_FINDERS = True

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Sites framework
SITE_ID = 1

# Authentication backends
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# Allauth settings
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_AUTHENTICATION_METHOD = "username_email"
LOGIN_REDIRECT_URL = "/calendar/"
LOGOUT_REDIRECT_URL = "/"
LOGIN_URL = "/accounts/login/"

# Registration settings
REGISTRATION_ENABLED = os.getenv("REGISTRATION_ENABLED", "false").lower() == "true"
LOCAL_LOGIN_ENABLED = os.getenv("LOCAL_LOGIN_ENABLED", "true").lower() == "true"
ACCOUNT_ADAPTER = "calendar_app.adapters.CustomAccountAdapter"
SOCIALACCOUNT_ADAPTER = "calendar_app.adapters.CustomSocialAccountAdapter"

# Keycloak OIDC Provider Configuration
KEYCLOAK_SERVER_URL = os.getenv("KEYCLOAK_SERVER_URL", "")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")

SOCIALACCOUNT_PROVIDERS = {
    "openid_connect": {
        "APPS": [
            {
                "provider_id": "keycloak",
                "name": "Keycloak",
                "client_id": KEYCLOAK_CLIENT_ID,
                "secret": KEYCLOAK_CLIENT_SECRET,
                "settings": {
                    "server_url": f"{KEYCLOAK_SERVER_URL}realms/{KEYCLOAK_REALM}/.well-known/openid-configuration",
                },
            }
        ],
        "OAUTH_PKCE_ENABLED": True,
    }
}

# Allauth socialaccount settings
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = True

# Apprise notification settings
# Configure notification URLs (e.g., 'slack://...', 'discord://...', 'mailto://...')
# See https://github.com/caronc/apprise for supported services
APPRISE_URLS = [url.strip() for url in os.getenv("APPRISE_URLS", "").split(",") if url.strip()]

# Jinja2 templates for notification messages
# Available variables: date, date_formatted, description, confirmed_by, site_url
APPRISE_CONFIRM_TEMPLATE = os.getenv("APPRISE_CONFIRM_TEMPLATE", "{{ description }}")
APPRISE_UNCONFIRM_TEMPLATE = os.getenv("APPRISE_UNCONFIRM_TEMPLATE", "⛈️ BGT {{ date_formatted }} wurde abgesagt")

# iCal export settings
# Path where the iCal file will be written (default: <cwd>/calendar.ics)
ICAL_EXPORT_PATH = os.getenv("ICAL_EXPORT_PATH", str((STATEDIR / "calendar.ics")))
# Timezone for iCal events (default: Europe/Berlin)
ICAL_TIMEZONE = os.getenv("ICAL_TIMEZONE", "Europe/Berlin")

# Logging configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {module} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG" if DEBUG else "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "calendar_app": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}

# Debug: Log apprise configuration at startup if DEBUG is enabled
if DEBUG and APPRISE_URLS:
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"APPRISE_URLS configured with {len(APPRISE_URLS)} URL(s)")
    for idx, url in enumerate(APPRISE_URLS):
        # Mask sensitive parts
        masked = url.split("://")[0] + "://***" if "://" in url else "***"
        logger.info(f"  URL {idx + 1}: {masked}")

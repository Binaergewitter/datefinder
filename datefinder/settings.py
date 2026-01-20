"""
Django settings for datefinder project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
CWD = Path.cwd()

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Reverse proxy configuration
# Set SITE_URL to the external URL when running behind a reverse proxy
# e.g., SITE_URL=https://plan.binaergewitter.de
SITE_URL = os.getenv('SITE_URL', '')

# Trust the X-Forwarded-Host header from the reverse proxy
USE_X_FORWARDED_HOST = os.getenv('USE_X_FORWARDED_HOST', 'False').lower() == 'true'

# Trust the X-Forwarded-Proto header to detect HTTPS
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if os.getenv('TRUST_PROXY_HEADERS', 'False').lower() == 'true' else None

# CSRF trusted origins - required for HTTPS behind a reverse proxy
# Automatically add SITE_URL if configured
_csrf_origins = os.getenv('CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in _csrf_origins.split(',') if origin.strip()]
if SITE_URL and SITE_URL not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(SITE_URL)

# Application definition
INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    # Allauth
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.openid_connect',
    # Channels
    'channels',
    # Our app
    'calendar_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'datefinder.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'calendar_app.context_processors.registration_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'datefinder.wsgi.application'
ASGI_APPLICATION = 'datefinder.asgi.application'

# Channels layer configuration
REDIS_URL = os.getenv('REDIS_URL', '')
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
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer"
        }
    }

# Database - use DATABASE_PATH env var for Nix deployments, otherwise use local db.sqlite3
DATABASE_PATH = os.getenv('DATABASE_PATH', str(CWD / 'db.sqlite3'))
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATABASE_PATH,
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Sites framework
SITE_ID = 1

# Authentication backends
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Allauth settings
ACCOUNT_EMAIL_VERIFICATION = 'none'
ACCOUNT_AUTHENTICATION_METHOD = 'username_email'
LOGIN_REDIRECT_URL = '/calendar/'
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/accounts/login/'

# Registration settings
REGISTRATION_ENABLED = os.getenv('REGISTRATION_ENABLED', 'false').lower() == 'true'
LOCAL_LOGIN_ENABLED = os.getenv('LOCAL_LOGIN_ENABLED', 'true').lower() == 'true'
ACCOUNT_ADAPTER = 'calendar_app.adapters.CustomAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'calendar_app.adapters.CustomSocialAccountAdapter'

# Keycloak OIDC Provider Configuration
KEYCLOAK_SERVER_URL = os.getenv('KEYCLOAK_SERVER_URL', '')
KEYCLOAK_REALM = os.getenv('KEYCLOAK_REALM', '')
KEYCLOAK_CLIENT_ID = os.getenv('KEYCLOAK_CLIENT_ID', '')
KEYCLOAK_CLIENT_SECRET = os.getenv('KEYCLOAK_CLIENT_SECRET', '')

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
APPRISE_URLS = [url.strip() for url in os.getenv('APPRISE_URLS', '').split(',') if url.strip()]

# Jinja2 templates for notification messages
# Available variables: date, date_formatted, description, confirmed_by, site_url
APPRISE_CONFIRM_TEMPLATE = os.getenv(
    'APPRISE_CONFIRM_TEMPLATE',
    '{{ description }}'
)
APPRISE_UNCONFIRM_TEMPLATE = os.getenv(
    'APPRISE_UNCONFIRM_TEMPLATE', 
    '⛈️ BGT {{ date_formatted }} wurde abgesagt'
)

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG' if DEBUG else 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'calendar_app': {
            'handlers': ['console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
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
        masked = url.split('://')[0] + '://***' if '://' in url else '***'
        logger.info(f"  URL {idx + 1}: {masked}")
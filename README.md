# Podcast Date Finder

A Django web application that helps a group of friends find a common meeting date for recording a podcast.

100% vibe-coded by Claude Opus 4.5

## Features

- **Keycloak OAuth2 Authentication**: Secure login via Keycloak identity provider
- **Interactive Calendar**: Full-size calendar view for selecting availability
- **Three-state Availability**:
  - Click once: Mark as **Available** (green)
  - Click twice: Mark as **Tentatively Available** (yellow)
  - Click again: Remove marker
- **Real-time Updates**: Changes are instantly visible to all users via WebSockets
- **Group Visibility**: See other users' availability with their names
  - Dark green labels for available users
  - Orange labels for tentatively available users
- **Star Indicator**: Dates with 3+ people available are marked with a ⭐
- **Configurable Registration**: User registration can be enabled/disabled via environment variable (disabled by default)
- **Date Confirmation**: Confirm dates with 1+ availabilities as official podcast recording dates
- **Notifications**: Send notifications via Apprise when dates are confirmed/unconfirmed
- **iCal Export**: Public iCal feed for subscribing to confirmed podcast dates

## Setup

### Prerequisites

- Python 3.10+
- Redis (optional, for production WebSocket support)
- Keycloak server (for OAuth2 authentication)

### Installation

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy the environment example file and configure:
   ```bash
   cp .env.example .env
   ```

4. Edit `.env` with your Keycloak configuration:
   ```
   KEYCLOAK_SERVER_URL=https://your-keycloak-server.com/auth/
   KEYCLOAK_REALM=your-realm
   KEYCLOAK_CLIENT_ID=your-client-id
   KEYCLOAK_CLIENT_SECRET=your-client-secret
   SECRET_KEY=your-django-secret-key
   DEBUG=false
   ```

5. Run migrations:
   ```bash
   python manage.py migrate
   ```

6. Create a superuser (optional, for admin access):
   ```bash
   python manage.py createsuperuser
   ```

7. Configure the Sites framework:
   ```bash
   python manage.py shell
   ```
   ```python
   from django.contrib.sites.models import Site
   site = Site.objects.get(id=1)
   site.domain = 'localhost:8000'  # or your domain
   site.name = 'Podcast Date Finder'
   site.save()
   ```

### Keycloak Configuration

1. Create a new client in your Keycloak realm
2. Set the client to "Confidential" access type
3. Add valid redirect URIs:
   - `http://localhost:8000/accounts/openid_connect/keycloak/login/callback/`
   - `https://yourdomain.com/accounts/openid_connect/keycloak/login/callback/`
4. Copy the client ID and client secret to your `.env` file

### Running the Application

#### Development (without Redis):
```bash
python manage.py runserver
```

The in-memory channel layer works for single-server development but doesn't support real-time updates across multiple browser sessions.

#### Development with Redis (full WebSocket support):
```bash
# Start Redis
docker run -p 6379:6379 redis:alpine

# Update .env
REDIS_URL=redis://localhost:6379/0

# Run with Daphne
daphne -b 0.0.0.0 -p 8000 datefinder.asgi:application
```

#### Production:
```bash
# Collect static files
python manage.py collectstatic

# Run with Daphne behind a reverse proxy (nginx, etc.)
daphne -b 127.0.0.1 -p 8000 datefinder.asgi:application
```

### Reverse Proxy Configuration

When running behind a reverse proxy (e.g., nginx) with HTTPS, configure these environment variables:

```bash
# The external URL where the app is accessible
SITE_URL=https://plan.binaergewitter.de

# Add the domain to allowed hosts
ALLOWED_HOSTS=plan.binaergewitter.de,localhost,127.0.0.1

# Trust proxy headers for proper HTTPS detection
USE_X_FORWARDED_HOST=true
TRUST_PROXY_HEADERS=true

# Additional CSRF trusted origins (SITE_URL is added automatically)
# CSRF_TRUSTED_ORIGINS=https://other-domain.com

# Enable user registration (disabled by default)
REGISTRATION_ENABLED=true

# Show local username/password login form (enabled by default)
# Set to false to only allow social login (Keycloak)
LOCAL_LOGIN_ENABLED=true
```

### Database and State Configuration

```bash
# Directory for storing state files (database, iCal export)
# Default: /tmp
STATEDIR=/var/lib/datefinder

# Path to SQLite database file
# Default: <STATEDIR>/db.sqlite3
DATABASE_PATH=/var/lib/datefinder/db.sqlite3

# Path where the iCal export file will be written
# Default: <STATEDIR>/calendar.ics
ICAL_EXPORT_PATH=/var/lib/datefinder/calendar.ics
```

### Additional Configuration

```bash
# Enable Django debug mode (for development only!)
# Default: false
DEBUG=false

# Django secret key (required for production)
# Generate with: python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
SECRET_KEY=your-random-secret-key
```

### Notification Configuration (Apprise)

The application can send notifications when podcast dates are confirmed or unconfirmed using the [Apprise](https://github.com/caronc/apprise) library. Apprise supports 90+ notification services including Slack, Discord, Telegram, Email, and more.

#### Environment Variables

```bash
# Comma-separated list of Apprise notification URLs
# See https://github.com/caronc/apprise/wiki for all supported services
APPRISE_URLS=slack://tokenA/tokenB/tokenC,discord://webhook_id/webhook_token

# Optional: Jinja2 template for confirm notification message
# Available variables: date, date_formatted, description, confirmed_by, site_url
APPRISE_CONFIRM_TEMPLATE={{ description }}

# Optional: Jinja2 template for unconfirm notification message
# Available variables: date, date_formatted
APPRISE_UNCONFIRM_TEMPLATE=Date {{ date_formatted }} has been unconfirmed.
```

#### Example Notification URLs

| Service | URL Format |
|---------|------------|
| Slack | `slack://tokenA/tokenB/tokenC` |
| Discord | `discord://webhook_id/webhook_token` |
| Telegram | `tgram://bot_token/chat_id` |
| Email (SMTP) | `mailto://user:pass@gmail.com` |
| Gotify | `gotify://hostname/token` |
| Ntfy | `ntfy://topic` |
| Matrix | `matrix://user:pass@hostname/#room` |

For the complete list of supported services, see the [Apprise Wiki](https://github.com/caronc/apprise/wiki).

#### Custom Notification Templates

You can customize the notification message using Jinja2 templates. Available variables:

| Variable | Description |
|----------|-------------|
| `date` | ISO format date (e.g., `2026-01-25`) |
| `date_formatted` | Human-readable date (e.g., `Sunday, January 25, 2026`) |
| `description` | The description entered when confirming |
| `confirmed_by` | Username of the person who confirmed |
| `site_url` | The configured SITE_URL |

Example template:
```bash
APPRISE_CONFIRM_TEMPLATE=🎙️ Podcast scheduled: {{ description }} on {{ date_formatted }} (confirmed by {{ confirmed_by }})
```

Example nginx configuration:
```nginx
server {
    listen 443 ssl;
    server_name plan.binaergewitter.de;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;

        # WebSocket support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## Usage

1. Navigate to `http://localhost:8000`
2. You'll be redirected to the login page
3. Click "Login with Keycloak" (or use the social login button)
4. After authentication, you'll see the calendar
5. Click on future dates to toggle your availability:
   - First click → Available (green border)
   - Second click → Tentatively available (yellow border)
   - Third click → Remove marker
6. See other users' availability displayed on each date
7. Look for the ⭐ indicator on dates where 3+ people are available
8. Visit the **Confirm** page to officially confirm dates with 2+ availabilities
9. Confirmed dates appear in blue on the calendar
10. Subscribe to the iCal feed at `/calendar/export/calendar.ics`

## Project Structure

```
date-finder/
├── datefinder/           # Main Django project
│   ├── settings.py       # Django settings with Keycloak config
│   ├── urls.py           # Main URL routing
│   ├── asgi.py           # ASGI config for WebSockets
│   └── wsgi.py           # WSGI config
├── calendar_app/         # Calendar application
│   ├── models.py         # Availability model
│   ├── views.py          # HTTP views and API endpoints
│   ├── urls.py           # App URL routing
│   ├── consumers.py      # WebSocket consumer
│   ├── routing.py        # WebSocket routing
│   └── admin.py          # Admin configuration
├── templates/            # HTML templates
│   └── calendar_app/
│       └── calendar.html # Main calendar template
├── static/               # Static files
├── requirements.txt      # Python dependencies
├── manage.py             # Django management script
└── .env.example          # Environment variables template
```

## License

MIT

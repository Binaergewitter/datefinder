# Podcast Date Finder

A Django web application that helps a group of friends find a common meeting date for recording a podcast.

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

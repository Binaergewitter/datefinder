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

- Python 3.10+ (or NixOS/Nix for declarative deployment)
- Redis (optional, for production WebSocket support)
- Keycloak server (for OAuth2 authentication)

### Installation

#### Quick Run with Nix

If you have Nix installed, you can run datefinder directly without any setup:

```bash
nix run github:Binaergewitter/datefinder
```

This starts the server on `http://localhost:8000` using SQLite. For a declarative NixOS deployment, see [NixOS Deployment](#nixos-deployment) below.

#### Manual Installation

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

# PostgreSQL via unix socket (used by NixOS module)
DATABASE_URL=postgres:///datefinder

# PostgreSQL via TCP
DATABASE_URL=postgres://user:password@localhost:5432/datefinder

# Unix socket directory (default: /run/postgresql)
DATABASE_SOCKET_DIR=/run/postgresql

# Path where the iCal export file will be written
# Default: <STATEDIR>/calendar.ics
ICAL_EXPORT_PATH=/var/lib/datefinder/calendar.ics

# Timezone for iCal events (times are converted to UTC)
# Default: Europe/Berlin
ICAL_TIMEZONE=Europe/Berlin
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

## NixOS Deployment

The datefinder flake provides a NixOS module at `services.datefinder` for declarative deployment. It handles systemd service setup, PostgreSQL integration, database migrations, and static file serving out of the box.

### Quick Start with Flake

Add the flake input to your NixOS configuration:

```nix
# flake.nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    datefinder.url = "github:Binaergewitter/datefinder";
  };

  outputs = { nixpkgs, datefinder, ... }: {
    nixosConfigurations.myhost = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        datefinder.nixosModules.datefinder
        {
          services.datefinder = {
            enable = true;
            settings.allowedHosts = [ "plan.example.com" "localhost" ];
            database = {
              type = "postgres";
              createLocally = true;
            };
            environmentFile = "/run/secrets/datefinder";
          };
        }
      ];
    };
  };
}
```

### PostgreSQL Integration

When `database.type = "postgres"` and `database.createLocally = true` (the default), the module automatically:

- Enables and configures PostgreSQL
- Creates the `datefinder` database and user
- Grants database ownership to the service user
- Uses unix socket (peer) authentication — no password needed
- Ensures the datefinder service starts after PostgreSQL

The generated `DATABASE_URL` is `postgres:///datefinder` with the socket directory set to `/run/postgresql`.

### External PostgreSQL

To connect to an existing PostgreSQL server, disable local creation and provide the connection details:

```nix
services.datefinder = {
  enable = true;
  database = {
    type = "postgres";
    createLocally = false;
    host = "db.example.com";
    port = 5432;
    name = "datefinder";
    user = "datefinder";
  };
  # Put the password in DATABASE_URL inside the environmentFile:
  # DATABASE_URL=postgres://datefinder:secretpass@db.example.com:5432/datefinder
  environmentFile = "/run/secrets/datefinder";
};
```

When `host` is `null` (the default), the module uses unix socket authentication via `socketDir` instead of TCP.

### Secrets Management

Never put secrets directly in Nix configuration — they end up in the world-readable Nix store. Instead, use `environmentFile` to point to a file containing secrets:

```bash
# /run/secrets/datefinder (or managed by sops-nix/agenix)
SECRET_KEY=your-random-django-secret-key
KEYCLOAK_CLIENT_SECRET=your-keycloak-client-secret
APPRISE_URLS=slack://tokenA/tokenB/tokenC,ntfy://topic
```

The `environmentFile` is loaded by systemd as an `EnvironmentFile`, so it uses `KEY=VALUE` format (no `export`, no quotes needed).

### All Module Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable` | bool | `false` | Enable the datefinder service |
| `package` | package | `self.packages.*.default` | The datefinder package to use |
| `port` | port | `8000` | Port to listen on |
| `host` | string | `"127.0.0.1"` | Bind address for the server |
| `stateDir` | string | `"/var/lib/datefinder"` | Directory for persistent state |
| `user` | string | `"datefinder"` | System user to run as |
| `group` | string | `"datefinder"` | System group to run as |
| `environmentFile` | null or path | `null` | Path to systemd EnvironmentFile with secrets |
| **settings** | | | |
| `settings.secretKey` | null or string | `null` | Django secret key (prefer environmentFile) |
| `settings.debug` | bool | `false` | Enable Django debug mode |
| `settings.allowedHosts` | list of string | `["localhost" "127.0.0.1"]` | Django ALLOWED_HOSTS |
| `settings.siteUrl` | null or string | `null` | External URL for reverse proxy setups |
| `settings.useXForwardedHost` | bool | `false` | Trust X-Forwarded-Host header |
| `settings.trustProxyHeaders` | bool | `false` | Trust X-Forwarded-Proto for HTTPS detection |
| `settings.csrfTrustedOrigins` | list of string | `[]` | CSRF trusted origins |
| `settings.registrationEnabled` | bool | `false` | Allow new user registration |
| `settings.localLoginEnabled` | bool | `true` | Allow local username/password login |
| `settings.redisUrl` | null or string | `null` | Redis URL for Django Channels |
| `settings.icalTimezone` | string | `"Europe/Berlin"` | Timezone for iCal exports |
| **database** | | | |
| `database.type` | enum: sqlite, postgres | `"sqlite"` | Database backend |
| `database.name` | string | `"datefinder"` | Database name |
| `database.user` | string | `"datefinder"` | PostgreSQL user |
| `database.host` | null or string | `null` | Database host (null = unix socket) |
| `database.port` | port | `5432` | Database port for TCP connections |
| `database.socketDir` | string | `"/run/postgresql"` | PostgreSQL unix socket directory |
| `database.createLocally` | bool | `true` | Auto-configure local PostgreSQL |
| **keycloak** | | | |
| `keycloak.serverUrl` | null or string | `null` | Keycloak server URL |
| `keycloak.realm` | null or string | `null` | Keycloak realm name |
| `keycloak.clientId` | null or string | `null` | Keycloak OIDC client ID |

### Complete NixOS Deployment Example

A full example with PostgreSQL, Keycloak OIDC, reverse proxy settings, and nginx:

```nix
# flake.nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    datefinder.url = "github:Binaergewitter/datefinder";
  };

  outputs = { nixpkgs, datefinder, ... }: {
    nixosConfigurations.podcast-server = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        datefinder.nixosModules.datefinder
        ({ pkgs, ... }: {
          # Datefinder service
          services.datefinder = {
            enable = true;
            host = "127.0.0.1";
            port = 8000;

            settings = {
              allowedHosts = [ "plan.binaergewitter.de" "localhost" ];
              siteUrl = "https://plan.binaergewitter.de";
              useXForwardedHost = true;
              trustProxyHeaders = true;
              csrfTrustedOrigins = [ "https://plan.binaergewitter.de" ];
              registrationEnabled = false;
              localLoginEnabled = false;  # Keycloak only
              icalTimezone = "Europe/Berlin";
            };

            database = {
              type = "postgres";
              createLocally = true;
            };

            keycloak = {
              serverUrl = "https://keycloak.binaergewitter.de/";
              realm = "binaergewitter";
              clientId = "datefinder";
            };

            # Secrets: SECRET_KEY, KEYCLOAK_CLIENT_SECRET, APPRISE_URLS
            environmentFile = "/run/secrets/datefinder";
          };

          # nginx reverse proxy with HTTPS
          services.nginx = {
            enable = true;
            recommendedProxySettings = true;
            recommendedTlsSettings = true;

            virtualHosts."plan.binaergewitter.de" = {
              enableACME = true;
              forceSSL = true;

              locations."/" = {
                proxyPass = "http://127.0.0.1:8000";
                proxyWebsockets = true;
              };
            };
          };

          # ACME (Let's Encrypt) for TLS certificates
          security.acme = {
            acceptTerms = true;
            defaults.email = "admin@binaergewitter.de";
          };

          networking.firewall.allowedTCPPorts = [ 80 443 ];
        })
      ];
    };
  };
}
```

### Running the NixOS VM Test

The flake includes a NixOS VM test that validates the full stack (PostgreSQL, migrations, HTTP endpoints, user registration):

```bash
nix build .#checks.x86_64-linux.nixos-test
```

The test verifies:
- PostgreSQL and datefinder services start successfully
- Web interface responds (login page, redirects)
- Database migrations create the expected tables
- Static files are served correctly
- iCal export endpoint works
- User registration and login flow completes

### Migrating from SQLite to PostgreSQL

If you started with the default SQLite backend and want to switch to PostgreSQL, use the included management command to transfer all data (users, availability, confirmed dates, reminders):

```bash
# Set DATABASE_URL to point to the new PostgreSQL database
export DATABASE_URL=postgres:///datefinder

# Run Django migrations on the new database first
datefinder-manage migrate

# Import data from the old SQLite file
datefinder-manage migrate_from_sqlite --sqlite-path /var/lib/datefinder/db.sqlite3
```

The command is idempotent — re-running it skips rows that already exist in the target database. User passwords and timestamps are preserved.

On NixOS, run the command as the `datefinder` user with the service environment:

```bash
sudo -u datefinder env \
  DATABASE_URL=postgres:///datefinder \
  DATABASE_SOCKET_DIR=/run/postgresql \
  STATEDIR=/var/lib/datefinder \
  SECRET_KEY=... \
  datefinder-manage migrate_from_sqlite --sqlite-path /path/to/old/db.sqlite3
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

# Repository Guidelines

## Project Overview

**datefinder** — Django 5.2 + Channels app for coordinating podcast recording dates (Binärgewitter). Keycloak OIDC login via django-allauth, three-state availability calendar, WebSocket realtime updates, confirm/unconfirm with Apprise notifications, public iCal export, health checks with OTel output. Deployed via Nix flake + NixOS module.

Everything runs through Nix: there is no bare-python workflow. The sandboxed build copies only git-tracked files, so:

- After adding/removing any file run `git add -AN` or it is invisible to `nix build`.
- Never run `manage.py` bare; use `nix develop -c python manage.py <cmd>`.
- After any change run `nix build`; finalize a work session with `nix build .#test`.
- Every change to the underlying structure must add a new integration-testable test case.

## Architecture & Data Flow

Three Django packages: `datefinder/` (project config), `calendar_app/` (domain), `health/` (ops endpoint).

Request flow:
1. `datefinder/urls.py` mounts `admin/`, `accounts/` (allauth), `calendar/` (calendar_app.urls), `.health` (no trailing slash), `''` → redirect `/calendar/`.
2. Templates (`datefinder/templates/calendar_app/*.html`) call JSON APIs under `/calendar/api/*` via inline `fetch()` with `X-CSRFToken` header; API responses follow `{success, data}` / `{error}` shape.
3. Mutating views write models, then broadcast with `async_to_sync(get_channel_layer().group_send)("calendar_updates", {"type": "<handler>", ...})`; `calendar_app/consumers.py:CalendarConsumer` relays `availability_update` / `confirmation_update` to WebSocket clients (`/ws/calendar/`, 3s client reconnect).
4. Confirm/unconfirm additionally fan out to `calendar_app/hooks.py:HOOK_REGISTRY` — `LoggingHook`, `AppriseHook`, `ICalExportHook`. Side effects are best-effort: runners catch per-hook exceptions and log; HTTP response never breaks.
5. iCal: single source `calendar_app/ical.py:generate_ical_content()` (hand-rolled VCALENDAR, CRLF, no icalendar lib); pre-generated to `ICAL_EXPORT_PATH` at `AppConfig.ready()` (skipped for `migrate`/`test`/`makemigrations`), on hooks, and on reminder mutations. `export_ical` serves the file off disk unauthenticated (nginx caches it).

Settings are 12-factor: `datefinder/settings.py` reads everything via `os.getenv` (`load_dotenv()` on `.env`): `STATEDIR`, `DATABASE_URL` (postgres, else SQLite at `STATEDIR/db.sqlite3`), `REDIS_URL` (→ channels_redis layer, else InMemoryChannelLayer — how tests work without Redis), `KEYCLOAK_*`, `APPRISE_URLS`/`APPRISE_*_TEMPLATE`, `ICAL_*`, `REGISTRATION_ENABLED`, `LOCAL_LOGIN_ENABLED`. New config = env var in settings.py with a sensible default.

Auth: contrib `User` (swappable, not custom model); allauth `openid_connect` provider keyed `keycloak`; signup gated by `calendar_app/adapters.py` (`REGISTRATION_ENABLED`; social signup always open). Everything requires login except `export/calendar.ics` and `.health`.

## Key Directories

- `calendar_app/` — models, views, consumer, hooks, ical, adapters, management commands, migrations
- `health/` — `checks.py` (database SELECT 1 / redis via CHANNEL_LAYERS / disk writability; statuses `healthy|unhealthy|skipped`), `views.py` (`/.health` JSON 200/503, `?format=otel` or Accept header → OTel text gauges)
- `datefinder/` — `settings.py`, `asgi.py` (ProtocolTypeRouter: http + `AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(...)))`), `cli.py`, `templates/`, `static/` (only vendored Pico CSS)
- `nixos/` — `package.nix` (buildPythonApplication; checkPhase runs `ruff check .` + `ty check`), `module.nix` (`services.datefinder.*`: port 8000, user `datefinder`, systemd unit with `ExecStartPre=…-manage migrate --noinput`), `test*.nix` (NixOS VM tests)
- `.github/prompts/` — feature plan files (`*.prompt.md`); new features are specced here first.

## Development Commands

```bash
nix build                          # package + ruff/ty checkPhase
nix build .#test                   # unit/integration tests (SQLite)
nix develop -c python manage.py migrate
nix develop -c python manage.py test calendar_app health -v 2
nix develop -c python manage.py runserver      # in-memory channel layer
nix run . # or: nix run .#default               # daphne via datefinder-server
nix build .#checks.x86_64-linux.nixos-test       # VM test (also: nixos-test-migration, nixos-test-websocket)
nix flake check                    # all three VM checks (slow)
```

Installed console scripts (from `datefinder/cli.py`): `datefinder-server` (daphne on `HOST`/`PORT`, default 0.0.0.0:8000, serves `datefinder.asgi:application`), `datefinder-manage` / `datefinder` (Django manage).

## Developer Workflow (Branch & PR)

1. **Status check**: `git status` — start from a clean state.
2. **Branching**: no direct commits to `main`; create `feat/` or `fix/` branches.
3. **Develop**: use `nix develop` for the environment; keep logic modular.
4. **Verify**: `nix build` (reproducibility, runs ruff/ty) and `nix build .#test` (integration + unit tests).
5. **Commit & push**: `git commit -m "type: description"` (Linux-kernel style, explain WHY), then `git push origin <branch>`.
6. **PR**: open a pull request against `main`.

## Code Conventions & Common Patterns

- **Views:** function-based only (sole CBV: `health.HealthView`). Stack `@login_required` + `@require_POST`. APIs return `JsonResponse({'success': True, ...})` or `{'error': msg}` with explicit status (400/404/502/503).
- **URLs:** `app_name = 'calendar_app'`; names match view names; `api/` prefix for JSON endpoints, `<str:date>` ISO dates, `<int:pk>`. Template JS hardcodes absolute API paths — URL changes must be mirrored in `calendar.html`/`confirm.html`/`reminders.html` inline JS.
- **Hooks/extension:** register side effects by appending an instance to `HOOK_REGISTRY` in `calendar_app/hooks.py`; subclass the `PostActionHook` ABC (`on_confirm(date, description, confirmed_by)` / `on_unconfirm(date)`); hooks must tolerate failure — callers wrap per-hook try/except with `logger.error(..., exc_info=True)`.
- **Async bridge:** never call the channel layer directly from sync views; `async_to_sync(group_send)`, and the event `type` must match the consumer handler method name.
- **Models:** `DateField` + `auto_now_add`/`auto_now` timestamps; FK `SET_NULL` for attribution users, `CASCADE` for owned rows; `unique_together`/`unique=True` guards; `ordering = ['date']`. `Availability.toggle_availability` implements the None→available→tentative→delete cycle.
- **Error handling:** broad try/except around integrations (apprise, external blog fetch in `get_next_podcast_number`, file writes) — log, never propagate. Lazy/optional imports inside functions to dodge circular imports (`models` in `ical.py`; `apprise`, `jinja2`, `opentelemetry`). `CommandError` in management commands.
- **Logging:** `logger = logging.getLogger(__name__)` per module, f-string messages.
- **Templates:** dirs at `datefinder/templates/` (base.html → calendar_app/base.html → pages). No JS framework: inline vanilla `<script>` in `{% block extra_js %}`, `const csrfToken = '{{ csrf_token }}'`, fetch + `X-CSRFToken`, `data.success` checks. Styling: vendored Pico CSS only.
- **Formatting:** ruff, line-length 120, rules `E,F,W,I` (E501 ignored; migrations exempt). Type checks: `ty` (Django-metaclass false positives silenced in pyproject). Both run in the nix package checkPhase, not the devShell.

## Important Files

- `datefinder/settings.py` — all env-driven config; single place to add settings
- `datefinder/urls.py`, `calendar_app/urls.py`, `calendar_app/routing.py` — HTTP/WS routing
- `calendar_app/views.py` — all page + API views; `calendar_app/dav.py` — CalDAV backend (auth, XML, iCal round-trip)
- `calendar_app/hooks.py` — `HOOK_REGISTRY`; `calendar_app/ical.py` — iCal generation
- `calendar_app/consumers.py` + `routing.py` — WebSocket path `ws/calendar/`
- `nixos/module.nix` — deployment options; `flake.nix` — all build/test targets
- `.env.example` — env keys (`KEYCLOAK_*`, `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `REDIS_URL`)

## Runtime/Tooling Preferences

- Python via nixpkgs (`pkgs.python3`, `requires-python >= 3.11`); Django/channels versions come from the pinned nixos-unstable lock.
- Deps are declared in three places that can drift: `pyproject.toml` (authoritative; test-only deps go under `[project.optional-dependencies] test`), `nixos/package.nix` + `flake.nix` `pythonDeps` (nix build; adds `psycopg2`, `redis`, `channels-redis`), and `requirements.txt` (legacy venv path; `python-keycloak` there is unused — auth is allauth OIDC). Add runtime deps to pyproject **and** both nix dep lists. Test-only deps (e.g. `caldav`) stay out of `package.nix` `dependencies`: they live in `pythonTestDeps` there (nativeCheckInputs + ty shell) and in flake `pythonDeps` (used by `.#test`/devShell); the nix test target has no pip-install step, so the flake list is what keeps them importable.
- No pytest config exists: tests are Django-native (`manage.py test`); pytest/pytest-django in devShell are vestigial.
- Prefer nixpkgs for Python deps; no pip installs into the shell.

## Testing & QA

- Framework: `django.test.TestCase`/`TransactionTestCase` + `unittest.mock`; WebSocket tests use `channels.testing.WebsocketCommunicator` over `calendar_app.routing.websocket_urlpatterns` (async test methods). Inventory: `calendar_app/tests.py` (model/integration/WebSocket/view/reminder/CalDAV classes), `calendar_app/tests_caldav_client.py` (real `caldav` client against `LiveServerTestCase`, needs the test-only `caldav` dep), `health/tests.py` (check + endpoint classes).
- Unit/integration run: `nix build .#test` (migrate on SQLite, then `manage.py test calendar_app.tests.IntegrationTest`, then full `calendar_app health`), or interactively `nix develop -c python manage.py test <app>`.
- Integration/VM: `nix build .#checks.x86_64-linux.{nixos-test,nixos-test-migration,nixos-test-websocket}` — real services (daphne :8000, `redis-datefinder` :6379, postgres), curl/psql/websockets assertions, login flow, iCal + health endpoints, SQLite→Postgres `migrate_from_sqlite` idempotency.
- No coverage tooling. Every structural change ⇒ new test case (see rules above); management command `migrate_from_sqlite --sqlite-path PATH` is exercised by `nixos-test-migration.nix`.

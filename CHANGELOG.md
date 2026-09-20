# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is the application version declared in `datefinder/__init__.py`, `pyproject.toml` and `nixos/package.nix`.

## [1.1.0] - 2026-09-20

### Added

- CalDAV backend (`/dav/`) with per-user calendar keys: availability dates round-trip as VEVENTs so external calendar clients can subscribe and write back; management UI under the "Sync" page.
- Security hardening: `SECRET_KEY` and `ALLOWED_HOSTS` are now enforced at startup, HTTPS security headers added.
- Automatic SQLite migrations on server start (`datefinder-server` automigrate fallback when no `DATABASE_URL` is configured).
- GitHub Actions CI: Nix-based workflow running the package build (ruff + ty checkPhase) and the SQLite unit/integration test suite on every push/PR.
- Application version displayed in the page header (served to templates via `calendar_app.context_processors.app_version`).

### [1.1.0]: https://github.com/Binaergewitter/datefinder/releases/tag/v1.1.0

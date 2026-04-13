import os
import time
from typing import Any

from django.conf import settings
from django.db import connection


def check_database() -> dict[str, Any]:
    """Check database connectivity. Returns dict with status and latency_ms."""
    start = time.monotonic()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        latency = (time.monotonic() - start) * 1000
        return {"status": "healthy", "latency_ms": round(latency, 2)}
    except Exception:
        latency = (time.monotonic() - start) * 1000
        return {"status": "unhealthy", "latency_ms": round(latency, 2)}


def check_redis() -> dict[str, Any] | None:
    """Check Redis connectivity if configured. Returns dict or None if not configured."""
    redis_url = getattr(settings, "REDIS_URL", None)
    if not redis_url:
        # Try to extract from CHANNEL_LAYERS config
        channel_layers = getattr(settings, "CHANNEL_LAYERS", {})
        hosts = channel_layers.get("default", {}).get("CONFIG", {}).get("hosts", [])
        redis_url = hosts[0] if hosts else None

    if not redis_url:
        return None

    start = time.monotonic()
    try:
        import redis as redis_lib  # ty: ignore[unresolved-import]

        if isinstance(redis_url, str):
            r = redis_lib.from_url(redis_url)
        elif isinstance(redis_url, (list, tuple)) and len(redis_url) >= 2:
            r = redis_lib.Redis(host=redis_url[0], port=redis_url[1])
        else:
            r = redis_lib.Redis()
        r.ping()
        latency = (time.monotonic() - start) * 1000
        return {"status": "healthy", "latency_ms": round(latency, 2)}
    except ImportError:
        return {"status": "skipped", "reason": "redis package not installed"}
    except Exception:
        latency = (time.monotonic() - start) * 1000
        return {"status": "unhealthy", "latency_ms": round(latency, 2)}


def check_disk() -> dict[str, Any] | None:
    """Check if iCal export path is writable."""
    export_path = getattr(settings, "ICAL_EXPORT_PATH", None)
    if not export_path:
        return None

    directory = os.path.dirname(export_path) or "."
    writable = os.access(directory, os.W_OK)
    return {
        "status": "healthy" if writable else "unhealthy",
        "writable": writable,
    }


def run_all_checks() -> dict[str, Any]:
    """Run all health checks and return aggregated result."""
    checks: dict[str, dict[str, Any]] = {}

    checks["database"] = check_database()

    redis_result = check_redis()
    if redis_result is not None:
        checks["redis"] = redis_result

    disk_result = check_disk()
    if disk_result is not None:
        checks["disk"] = disk_result

    overall = "healthy" if all(c.get("status") in ("healthy", "skipped") for c in checks.values()) else "unhealthy"

    return {"status": overall, "checks": checks}

"""
Tests for the health check endpoint.

Unit tests for individual checks (database, redis, disk) and
integration tests for the /.health HTTP endpoint (JSON + OpenTelemetry formats).
"""

import tempfile
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

# ---------------------------------------------------------------------------
# Unit tests for health.checks
# ---------------------------------------------------------------------------


class CheckDatabaseTest(TestCase):
    """Tests for check_database()."""

    def test_check_database_healthy(self):
        """Normal DB connection returns healthy status with latency."""
        from health.checks import check_database

        result = check_database()
        self.assertEqual(result["status"], "healthy")
        self.assertIn("latency_ms", result)
        self.assertIsInstance(result["latency_ms"], float)
        self.assertGreaterEqual(result["latency_ms"], 0)

    def test_check_database_unhealthy(self):
        """DB failure returns unhealthy status with error detail."""
        from health.checks import check_database

        with patch("django.db.connection.cursor", side_effect=Exception("connection refused")):
            result = check_database()

        self.assertEqual(result["status"], "unhealthy")
        self.assertIn("error", result)
        self.assertIn("connection refused", result["error"])
        self.assertIn("latency_ms", result)


class CheckRedisTest(TestCase):
    """Tests for check_redis()."""

    @override_settings(REDIS_URL="")
    def test_check_redis_not_configured(self):
        """When no REDIS_URL is set, check_redis returns None (skipped)."""
        from health.checks import check_redis

        result = check_redis()
        self.assertIsNone(result)

    @override_settings(REDIS_URL="redis://localhost:6379/0")
    def test_check_redis_healthy(self):
        """Successful Redis ping returns healthy status."""
        from health.checks import check_redis

        mock_redis_mod = MagicMock()
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis_mod.from_url.return_value = mock_client

        with patch.dict("sys.modules", {"redis": mock_redis_mod}):
            result = check_redis()

        self.assertEqual(result["status"], "healthy")
        self.assertIn("latency_ms", result)

    @override_settings(REDIS_URL="redis://localhost:6379/0")
    def test_check_redis_unhealthy(self):
        """Failed Redis connection returns unhealthy status."""
        from health.checks import check_redis

        mock_redis_mod = MagicMock()
        mock_redis_mod.from_url.side_effect = Exception("Connection refused")

        with patch.dict("sys.modules", {"redis": mock_redis_mod}):
            result = check_redis()

        self.assertEqual(result["status"], "unhealthy")
        self.assertIn("error", result)

    @override_settings(REDIS_URL="redis://localhost:6379/0")
    def test_check_redis_import_error(self):
        """When redis package is not available, returns skipped."""
        import builtins
        import sys

        from health.checks import check_redis

        real_import = builtins.__import__
        # Remove redis from sys.modules if cached, and block import
        saved = sys.modules.pop("redis", None)

        def fake_import(name, *args, **kwargs):
            if name == "redis":
                raise ImportError("No module named 'redis'")
            return real_import(name, *args, **kwargs)

        try:
            with patch.object(builtins, "__import__", side_effect=fake_import):
                result = check_redis()
        finally:
            if saved is not None:
                sys.modules["redis"] = saved

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "skipped")


class CheckDiskTest(TestCase):
    """Tests for check_disk()."""

    @override_settings(ICAL_EXPORT_PATH="")
    def test_check_disk_not_configured(self):
        """When no ICAL_EXPORT_PATH, returns None (skipped)."""
        from health.checks import check_disk

        result = check_disk()
        self.assertIsNone(result)

    def test_check_disk_writable(self):
        """Writable directory returns healthy status."""
        from health.checks import check_disk

        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = f"{tmpdir}/calendar.ics"
            with self.settings(ICAL_EXPORT_PATH=export_path):
                result = check_disk()

        self.assertEqual(result["status"], "healthy")

    def test_check_disk_not_writable(self):
        """Non-writable directory returns unhealthy status."""
        from health.checks import check_disk

        with self.settings(ICAL_EXPORT_PATH="/nonexistent/path/calendar.ics"):
            with patch("os.access", return_value=False):
                result = check_disk()

        self.assertEqual(result["status"], "unhealthy")
        self.assertFalse(result["writable"])


class RunAllChecksTest(TestCase):
    """Tests for run_all_checks()."""

    def test_run_all_checks_all_healthy(self):
        """Overall status is healthy when all checks pass."""
        from health.checks import run_all_checks

        with (
            patch("health.checks.check_database", return_value={"status": "healthy", "latency_ms": 1.0}),
            patch("health.checks.check_redis", return_value=None),
            patch("health.checks.check_disk", return_value=None),
        ):
            result = run_all_checks()

        self.assertEqual(result["status"], "healthy")
        self.assertIn("checks", result)

    def test_run_all_checks_one_unhealthy(self):
        """Overall status is unhealthy when any check fails."""
        from health.checks import run_all_checks

        with (
            patch(
                "health.checks.check_database",
                return_value={"status": "unhealthy", "error": "down", "latency_ms": 0.0},
            ),
            patch("health.checks.check_redis", return_value=None),
            patch("health.checks.check_disk", return_value=None),
        ):
            result = run_all_checks()

        self.assertEqual(result["status"], "unhealthy")


# ---------------------------------------------------------------------------
# Integration tests for health.views
# ---------------------------------------------------------------------------


class HealthEndpointTest(TestCase):
    """Integration tests for the /.health HTTP endpoint."""

    def test_health_json_default(self):
        """GET /.health returns JSON with status, checks, uptime_seconds."""
        response = self.client.get("/.health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("checks", data)
        self.assertIn("uptime_seconds", data)

    def test_health_json_explicit(self):
        """GET /.health?format=json returns JSON."""
        response = self.client.get("/.health?format=json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        data = response.json()
        self.assertIn("status", data)

    def test_health_otel_query_param(self):
        """GET /.health?format=otel returns OpenTelemetry text format."""
        response = self.client.get("/.health?format=otel")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        content = response.content.decode()
        self.assertIn("health.status", content)

    def test_health_otel_accept_header(self):
        """GET /.health with Accept: application/opentelemetry returns otel format."""
        response = self.client.get("/.health", HTTP_ACCEPT="application/opentelemetry")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("health.status", content)

    def test_health_no_auth_required(self):
        """Unauthenticated request to /.health succeeds (no login redirect)."""
        response = self.client.get("/.health")
        # Should NOT redirect to login
        self.assertNotEqual(response.status_code, 302)
        self.assertIn(response.status_code, [200, 503])

    def test_health_returns_503_when_unhealthy(self):
        """Mock DB failure causes HTTP 503."""
        with patch("health.checks.check_database") as mock_db:
            mock_db.return_value = {"status": "unhealthy", "error": "down", "latency_ms": 0.0}
            response = self.client.get("/.health")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "unhealthy")

    def test_health_returns_200_when_healthy(self):
        """Normal state returns HTTP 200."""
        response = self.client.get("/.health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")

    def test_health_json_structure(self):
        """Validate JSON response has expected top-level keys."""
        response = self.client.get("/.health")
        data = response.json()
        expected_keys = {"status", "checks", "uptime_seconds"}
        self.assertTrue(expected_keys.issubset(data.keys()), f"Missing keys: {expected_keys - data.keys()}")
        self.assertIsInstance(data["checks"], dict)
        self.assertIn("database", data["checks"])
        self.assertIsInstance(data["uptime_seconds"], (int, float))

    def test_health_otel_contains_metrics(self):
        """OTel output contains expected metric names."""
        response = self.client.get("/.health?format=otel")
        content = response.content.decode()
        self.assertIn("health.status", content)
        self.assertIn("health.uptime_seconds", content)
        self.assertIn("health.check.database.status", content)

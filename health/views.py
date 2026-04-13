import time

from django.http import HttpResponse, JsonResponse
from django.views import View

from health.checks import run_all_checks

_start_time = time.monotonic()


class HealthView(View):
    """Health endpoint supporting JSON and OpenTelemetry exposition formats."""

    def get(self, request):  # noqa: ANN001
        fmt = request.GET.get("format", "json")
        accept = request.META.get("HTTP_ACCEPT", "")

        if fmt == "otel" or "application/opentelemetry" in accept:
            return self._otel_response()
        return self._json_response()

    def _json_response(self) -> JsonResponse:
        result = run_all_checks()
        result["uptime_seconds"] = round(time.monotonic() - _start_time, 1)
        status_code = 200 if result["status"] == "healthy" else 503
        return JsonResponse(result, status=status_code)

    def _otel_response(self) -> HttpResponse:
        """Return metrics in OpenTelemetry text format."""
        try:
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        except ImportError:
            return HttpResponse(
                "OpenTelemetry SDK not installed",
                status=501,
                content_type="text/plain",
            )

        reader = InMemoryMetricReader()
        provider = MeterProvider(metric_readers=[reader])
        meter = provider.get_meter("datefinder.health")

        result = run_all_checks()

        overall_gauge = meter.create_gauge("health.status")
        overall_gauge.set(1 if result["status"] == "healthy" else 0)

        uptime_gauge = meter.create_gauge("health.uptime_seconds")
        uptime_gauge.set(round(time.monotonic() - _start_time, 1))

        for check_name, check_result in result["checks"].items():
            status_gauge = meter.create_gauge(f"health.check.{check_name}.status")
            status_gauge.set(1 if check_result.get("status") == "healthy" else 0)

            if "latency_ms" in check_result:
                latency_gauge = meter.create_gauge(f"health.check.{check_name}.latency_ms")
                latency_gauge.set(check_result["latency_ms"])

        metrics_data = reader.get_metrics_data()
        lines = []
        if metrics_data is None:
            provider.shutdown()
            return HttpResponse("", content_type="text/plain; charset=utf-8", status=200)
        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    for data_point in metric.data.data_points:
                        value = getattr(data_point, "value", 0)
                        lines.append(f"{metric.name} {value}")

        provider.shutdown()

        return HttpResponse(
            "\n".join(lines) + "\n",
            content_type="text/plain; charset=utf-8",
            status=200 if result["status"] == "healthy" else 503,
        )

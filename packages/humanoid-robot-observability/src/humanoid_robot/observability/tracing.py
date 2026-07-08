"""OpenTelemetry tracing setup with an OTLP HTTP exporter."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(
    *,
    service: str,
    environment: str = "prod",
    otlp_endpoint: str = "http://127.0.0.1:4318/v1/traces",
    enabled: bool = True,
) -> None:
    """Install a tracer provider that exports OTLP over HTTP.

    Callers get a no-op tracer when `enabled=False` (useful in tests).
    """
    if not enabled:
        return

    resource = Resource.create(
        {
            "service.name": service,
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    trace.set_tracer_provider(provider)

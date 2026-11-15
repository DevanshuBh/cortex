"""OpenTelemetry setup. Spans go to an OTLP endpoint when one is configured (Grafana LGTM locally, ADOT on AWS)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from cortex.config import get_settings

_configured = False


def setup_tracing(component: str) -> None:
    global _configured
    if _configured:
        return
    s = get_settings()
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": f"{s.service_name}-{component}", "deployment.environment": s.env}
        )
    )
    if s.otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{s.otlp_endpoint}/v1/traces"))
        )
    trace.set_tracer_provider(provider)
    _configured = True
    logging.getLogger(__name__).info("tracing configured for %s (otlp=%s)", component, s.otlp_endpoint)


tracer = trace.get_tracer("cortex")


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    with tracer.start_as_current_span(name) as sp:
        for k, v in attributes.items():
            if v is not None:
                sp.set_attribute(f"cortex.{k}", v if isinstance(v, (str, int, float, bool)) else str(v))
        yield sp

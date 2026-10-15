import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


propagator = TraceContextTextMapPropagator()


def setup_tracing(service_name):
    endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "http://jaeger.tracing.svc.cluster.local:4318/v1/traces",
    )

    provider = TracerProvider(
        resource=Resource.create({
            "service.name": service_name,
        })
    )

    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        timeout=5,
    )

    provider.add_span_processor(
        BatchSpanProcessor(exporter)
    )

    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


def inject_kafka_headers():
    carrier = {}
    propagator.inject(carrier)

    return [
        (key, value.encode("ascii"))
        for key, value in carrier.items()
    ]


def extract_kafka_context(headers):
    carrier = {}

    for key, value in headers or []:
        if key.lower() not in ("traceparent", "tracestate"):
            continue

        try:
            carrier[key.lower()] = (
                value.decode("ascii")
                if isinstance(value, bytes)
                else value
            )
        except (UnicodeDecodeError, AttributeError):
            continue

    return propagator.extract(carrier)

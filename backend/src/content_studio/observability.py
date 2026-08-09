from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from content_studio.config import Settings

# Traces and metrics both flow through the OTel Collector (see
# infra/docker-compose/otel/otel-collector-config.yaml) rather than talking
# to Prometheus directly — this is the one non-Postgres piece of the
# observability stack the spec mandates by name (OpenTelemetry, Prometheus,
# Grafana), so it's wired independently of any single backend's storage
# choice.


def configure_observability(app: FastAPI, settings: Settings) -> None:
    resource = Resource.create({SERVICE_NAME: "content-studio-backend"})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint, insecure=True))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=settings.otel_exporter_endpoint, insecure=True)
    )
    metrics_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(metrics_provider)

    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)

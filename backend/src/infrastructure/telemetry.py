import os
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

def setup_telemetry(app: FastAPI, service_name: str = "osw-gateway") -> None:
    """
    Initializes OpenTelemetry distributed tracing and registers FastAPI instrumentation wrapper.
    """
    # 1. Initialize tracer provider
    provider = TracerProvider()
    
    # 2. Configure stdout console exporter for local development logging
    processor = SimpleSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)
    
    # Set global trace provider
    trace.set_tracer_provider(provider)
    
    # 3. Instrument FastAPI application automatically
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

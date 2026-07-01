import pytest
from fastapi import FastAPI
from opentelemetry import trace
from src.infrastructure.telemetry import setup_telemetry

def test_telemetry_setup_and_span_creation():
    app = FastAPI()
    setup_telemetry(app, "test-service")
    
    # Get tracer
    tracer = trace.get_tracer("test-tracer")
    
    # Assert we can start a trace span and record attributes
    with tracer.start_as_current_span("test-operation") as span:
        span.set_attribute("test-attribute", "value")
        assert span.is_recording() is True

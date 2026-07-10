"""RNF-004: sandbox execution must emit an OpenTelemetry span carrying its
stdout/exit_code, with ERROR status on failure. Verified with an in-memory
exporter -- no collector required.
"""
import subprocess
import types

import src.infrastructure.sandbox.gvisor_driver as gv
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from src.infrastructure.sandbox.gvisor_driver import GVisorSandboxDriver


def _tracer_with_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def test_sandbox_execution_emits_span_with_stdout(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    tracer, exporter = _tracer_with_exporter()

    GVisorSandboxDriver(tracer=tracer).execute_bash("echo hi")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "sandbox.execute"
    assert "sandbox.stdout" in spans[0].attributes
    assert spans[0].attributes["sandbox.exit_code"] == 0
    assert spans[0].status.status_code != StatusCode.ERROR


def test_sandbox_failure_sets_error_status(monkeypatch):
    monkeypatch.setenv("CI", "true")

    def fake_run(argv, **kwargs):
        raise subprocess.CalledProcessError(returncode=2, cmd=argv, stderr="boom")

    monkeypatch.setattr(gv.subprocess, "run", fake_run)
    tracer, exporter = _tracer_with_exporter()

    GVisorSandboxDriver(tracer=tracer).execute_bash("false")

    spans = exporter.get_finished_spans()
    assert spans[0].status.status_code == StatusCode.ERROR
    assert spans[0].attributes["sandbox.exit_code"] == 2


def test_no_span_emitted_when_no_tracer(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    _, exporter = _tracer_with_exporter()

    # Driver without a tracer must not create sandbox spans.
    GVisorSandboxDriver().execute_bash("echo hi")

    assert exporter.get_finished_spans() == ()

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

logger = logging.getLogger(__name__)


def _patch_route_details_for_included_router_compat() -> None:
    """
    Compatibility shim for a real upstream bug triggered by the specific
    dependency versions this project is pinned to (see `uv.lock`):
    `opentelemetry-instrumentation-fastapi==0.63b1`, held there by an exact-
    version transitive chain (`mcp` -> `fastmcp-slim` -> `pydantic-ai-slim`
    -> `logfire` -> `opentelemetry-instrumentation-httpx==0.63b1`, which pins
    `opentelemetry-instrumentation`/`opentelemetry-semantic-conventions`/
    `opentelemetry-util-http` to that exact release). A newer
    `opentelemetry-instrumentation-fastapi` (>= `0.65b0`) already fixes the
    bug this works around, but adopting it here would break that unrelated
    `pip check`-clean dependency graph -- well out of scope for this phase.

    The bug: FastAPI >= ~0.137 represents routes added via
    `app.include_router(...)` internally as `fastapi.routing._IncludedRouter`
    (see `.venv/Lib/site-packages/fastapi/routing.py`), which has no `.path`
    attribute. `opentelemetry.instrumentation.fastapi._get_route_details`
    (private, module-level) already guards against a missing `.path` on a
    `Match.FULL` result (`try/except AttributeError: route =
    scope.get("path")`) -- but is missing the SAME guard on its
    `Match.PARTIAL` branch. `Match.PARTIAL` is hit whenever a request's path
    matches a registered route but its HTTP method doesn't -- exactly what a
    CORS preflight `OPTIONS` request looks like (see `CORSMiddleware` in
    `presentation/main.py`). Left unpatched, ANY cross-origin preflight to
    this API raises an uncaught `AttributeError` deep inside OTel's ASGI
    middleware once instrumentation is active -- a real production outage for
    the frontend (every authenticated cross-origin request is preceded by a
    preflight), not just a test artifact.

    This monkeypatches ONLY that one private function, adding the identical
    fallback the library's own `Match.FULL` branch already uses -- it mirrors
    the fix already shipped upstream in `opentelemetry-instrumentation-fastapi
    >= 0.65b0` (which flattens `_IncludedRouter` via FastAPI's own
    `iter_route_contexts` helper). Once this project can adopt that version
    (or a newer `logfire`/`mcp`/`fastmcp-slim` chain stops pinning the older
    one), this function becomes a redundant no-op and can be deleted.
    """
    import opentelemetry.instrumentation.fastapi as _otel_fastapi
    from starlette.routing import Match, Route

    def _patched_get_route_details(scope):
        app = scope["app"]
        route = None
        for starlette_route in app.routes:
            match, _ = (
                Route.matches(starlette_route, scope)
                if isinstance(starlette_route, Route)
                else starlette_route.matches(scope)
            )
            if match == Match.FULL:
                try:
                    route = starlette_route.path
                except AttributeError:
                    # Routes added via host routing (or FastAPI's newer
                    # `_IncludedRouter` wrapper) won't have a `.path`.
                    route = scope.get("path")
                break
            if match == Match.PARTIAL:
                try:
                    route = starlette_route.path
                except AttributeError:
                    route = scope.get("path")
        return route

    # `_get_default_span_details` (in the same module) calls `_get_route_details`
    # as a bare global name, resolved from the module's `__dict__` at CALL time
    # -- so reassigning this module attribute is sufficient to redirect every
    # future call, even though `FastAPIInstrumentor.instrument_app` already
    # captured a reference to `_get_default_span_details` itself.
    _otel_fastapi._get_route_details = _patched_get_route_details


def setup_telemetry(app: FastAPI, service_name: str = "osw-gateway") -> None:
    """
    Initializes OpenTelemetry distributed tracing and registers FastAPI instrumentation wrapper.

    Must be called at module import time in `presentation/main.py`, immediately
    after the app's last `add_middleware(...)` call -- NOT from inside the
    `lifespan()` context manager. See the comment directly above the
    `setup_telemetry(app)` call site in `main.py` for the full reasoning
    (Starlette caches its middleware stack on the very first ASGI call, which
    is the `lifespan.startup` message itself, before any `lifespan()` code
    runs).
    """
    # 1. Initialize tracer provider
    provider = TracerProvider()

    # 2. Configure stdout console exporter for local development logging
    processor = SimpleSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)

    # Set global trace provider
    trace.set_tracer_provider(provider)

    # Work around the `_IncludedRouter`/`Match.PARTIAL` bug described above
    # BEFORE instrumenting, so every request (including this app's very first
    # CORS preflight) benefits from the fix.
    _patch_route_details_for_included_router_compat()

    # 3. Instrument FastAPI application automatically
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


def get_tracer(name: str = "osw-sandbox"):
    """Returns a tracer from the globally-configured provider (RNF-004).

    Used to instrument non-HTTP work such as sandbox execution, which the
    FastAPI auto-instrumentation does not cover."""
    return trace.get_tracer(name)

"""
Security response headers middleware (Fase 2 - security middleware).

Adds a standard set of defensive HTTP headers to every response. Registered as the
outermost middleware in `presentation/main.py` (added last via `app.add_middleware`)
so it wraps every other middleware and route -- including error responses generated
by the JWT/rate-limit layers (401s, 429s) -- guaranteeing these headers are present
on literally every response the app returns, not just the "happy path".
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# `Strict-Transport-Security` only has a real effect over HTTPS, but setting it
# unconditionally is common/harmless practice (browsers simply ignore it on plain
# HTTP) and avoids forgetting it when the app is later fronted by TLS.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Stamps a fixed set of hardening headers onto every outgoing response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value
        return response

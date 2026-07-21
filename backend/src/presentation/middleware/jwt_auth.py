"""
JWT bearer-token verification middleware (Fase 2 - security middleware).

This module implements an API-gateway-style verification layer: it does NOT
itself decide *who* is trustworthy, it only verifies a bearer token's
signature/expiry once minted. Token issuance lives in
`presentation/routes/auth.py` (a minimal dev-mode/demo endpoint added in Fase 5
-- see `docs/planning/execution_plan_gap_closure.md` -- appropriate for a BYOK
internal tool, not a production multi-tenant login system). Tests mint tokens
directly via the `create_access_token` helper below instead of going through
HTTP.

Design notes:
- Applied globally via `app.add_middleware(JWTAuthMiddleware)` in
  `presentation/main.py`, not per-route, so every request is covered by default
  and a route cannot accidentally be left unauthenticated by omission.
- An explicit allowlist (`UNAUTHENTICATED_PATHS`) carves out FastAPI's
  auto-generated documentation routes, plus `/health` and `/ready` (see
  `presentation/routes/health.py`) -- orchestrator health probes have no
  bearer token to present.
- On success, the decoded claims dict (including `iam_role`) is attached to
  `request.state.user` so downstream route handlers/tests can read it.

JWT_SECRET-missing tradeoff (see `_resolve_signing_secret` docstring below for the
full reasoning): fails loudly at startup in production, falls back to a random
per-process ephemeral secret (with a logged warning) everywhere else so the local
dev server and test suite keep working without requiring a `.env` file.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional, Tuple, Union
from uuid import UUID

import jwt
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.infrastructure.config import settings

logger = logging.getLogger(__name__)

# Paths that never require a bearer token. Kept intentionally minimal: FastAPI's
# built-in interactive docs / schema routes, so `TestClient`/browsers can reach them
# without a token, PLUS the dev-mode token issuance endpoint itself
# (`presentation/routes/auth.py`) -- a chicken-and-egg exception: a client cannot
# be required to already hold a bearer token in order to obtain its first one --
# PLUS the liveness/readiness probes (`presentation/routes/health.py`): a k8s
# kubelet/Docker healthcheck has no bearer token to present and must not be
# rejected with a 401.
# Do NOT add any other application route here -- auth must apply globally.
UNAUTHENTICATED_PATHS: Tuple[str, ...] = (
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/v1/auth/token",
    "/health",
    "/ready",
)


def _resolve_signing_secret() -> str:
    """
    Resolve the HMAC secret used to sign/verify access tokens.

    - If `settings.JWT_SECRET` is configured (via `.env`/environment, as expected in
      staging & production), it is always used.
    - If it is NOT configured:
        - In production (`settings.ENV == "production"`), fail loudly at import time
          by raising `RuntimeError`. Silently disabling auth enforcement, or silently
          minting a throwaway secret, in a real deployment would be a far worse
          failure mode than refusing to boot: it would look like the API is
          "protected" while every token is actually forgeable/ephemeral.
        - Otherwise (local development, CI, the test suite -- i.e. `settings.ENV`
          defaults to `"development"`), generate a random, per-process secret via
          `secrets.token_urlsafe` and log a loud warning. This is deliberately NOT
          "skip enforcement in dev": the auth code path (missing/invalid/expired ->
          401, valid -> claims attached) stays fully exercised in dev/tests, which is
          both more realistic and lets this middleware's own tests run against real
          enforcement. The tradeoff is that tokens minted by one process are not
          valid in any other process/worker or after a restart -- acceptable for a
          scaffold with no login endpoint yet, where `create_access_token` (below)
          and the middleware always run in the same process during tests/dev.
    """
    if settings.JWT_SECRET:
        return settings.JWT_SECRET

    if settings.ENV == "production":
        raise RuntimeError(
            "settings.JWT_SECRET is not configured but settings.ENV=='production'. "
            "Refusing to start with an undefined/ephemeral JWT signing secret in a "
            "production deployment. Set JWT_SECRET in the environment/.env file."
        )

    ephemeral_secret = secrets.token_urlsafe(64)
    logger.warning(
        "settings.JWT_SECRET is not set; falling back to a random, per-process "
        "ephemeral secret for JWT signing/verification because settings.ENV=%r "
        "(!= 'production'). This is intended for local development/tests ONLY -- "
        "tokens minted in this process are NOT valid after a restart or in any "
        "other process/worker. Set JWT_SECRET explicitly before deploying for real.",
        settings.ENV,
    )
    return ephemeral_secret


# Resolved once at import time (module-level singleton, mirroring the `settings`
# singleton pattern used elsewhere in this codebase -- see
# `infrastructure/persistence/database.py`). This guarantees `create_access_token`
# and `JWTAuthMiddleware` agree on the same effective secret for the lifetime of the
# process, even when `settings.JWT_SECRET` is `None`.
_SIGNING_SECRET: str = _resolve_signing_secret()


def create_access_token(
    user_id: Union[str, UUID],
    iam_role: str = "scientist",
    *,
    expires_minutes: Optional[int] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
    secret: Optional[str] = None,
    algorithm: Optional[str] = None,
) -> str:
    """
    Mint a signed JWT access token carrying `sub` (user id) and `iam_role` claims.

    There is no login/auth endpoint in this codebase yet (out of scope for this
    phase). This helper lets tests -- and, later, an external auth service or a
    Fase 5 login endpoint -- mint tokens this middleware will accept, mirroring an
    API-gateway pattern where tokens are issued elsewhere and merely verified here.
    """
    now = datetime.now(timezone.utc)
    expire_minutes = (
        expires_minutes if expires_minutes is not None else settings.JWT_EXPIRE_MINUTES
    )
    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "iam_role": iam_role,
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(
        payload,
        secret or _SIGNING_SECRET,
        algorithm=algorithm or settings.JWT_ALGORITHM,
    )


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    Verifies `Authorization: Bearer <token>` on every request except paths listed in
    `UNAUTHENTICATED_PATHS`, attaching decoded claims to `request.state.user` on
    success. Missing, malformed, invalid, or expired tokens all get a `401` with a
    small JSON error body (never a raw 500/crash).
    """

    def __init__(self, app: ASGIApp, allowlist: Iterable[str] = UNAUTHENTICATED_PATHS) -> None:
        super().__init__(app)
        self._allowlist = tuple(allowlist)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._allowlist:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return self._unauthorized("Missing or malformed Authorization header.")

        token = auth_header[len("Bearer "):].strip()
        if not token:
            return self._unauthorized("Missing or malformed Authorization header.")

        try:
            claims = jwt.decode(token, _SIGNING_SECRET, algorithms=[settings.JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return self._unauthorized("Access token has expired.")
        except jwt.InvalidTokenError:
            return self._unauthorized("Access token is invalid.")

        request.state.user = claims
        return await call_next(request)

    @staticmethod
    def _unauthorized(message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error_code": 4010, "message": message},
        )

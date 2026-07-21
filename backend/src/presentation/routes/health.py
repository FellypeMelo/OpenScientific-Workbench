"""
Liveness/readiness probes (production hardening).

- `GET /health` (liveness): confirms the process is up and able to handle an
  HTTP request at all. Deliberately makes NO downstream calls (no DB, no
  Redis) -- k8s/Docker use a liveness failure to *kill and restart* the
  container, which fixes nothing if the actual problem is a downstream
  Postgres/Redis outage (restarting the API pod in a loop while the database
  is down is pure self-harm, and would just as likely restart-loop every
  replica at once). See `backend/Dockerfile`'s `HEALTHCHECK` and
  `k8s/backend-deployment.yaml`'s `livenessProbe`.
- `GET /ready` (readiness): actually exercises the two hard dependencies this
  API cannot serve real traffic without -- Postgres (`SELECT 1`) and Redis
  (`PING`) -- each bounded by a short timeout so a hung dependency can't hang
  this probe (and therefore the pod's readiness state) forever. k8s uses a
  readiness failure to pull the pod out of the Service's endpoint list (stop
  routing traffic to it) WITHOUT restarting it -- the correct reaction to "a
  downstream dependency is temporarily unreachable". A 503 response names
  which dependency failed, in `failed_dependencies`, to make on-call
  debugging trivial without needing to correlate log timestamps. See
  `k8s/backend-deployment.yaml`'s `readinessProbe`.

Both routes are allowlisted in `JWTAuthMiddleware.UNAUTHENTICATED_PATHS` (see
`presentation/middleware/jwt_auth.py`) -- an orchestrator's health probe has no
bearer token to present, and must not be rejected with a 401.
"""
import asyncio
import logging
from typing import List

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.config import settings
from src.infrastructure.persistence.database import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Bounds each individual dependency check so one hung backend can't hang the
# whole readiness probe (and therefore the orchestrator's view of pod health)
# indefinitely.
_CHECK_TIMEOUT_SECONDS = 2.0


def get_redis_client() -> "redis.Redis":
    """
    Constructs a fresh async Redis client bound to `settings.REDIS_URL`.

    Mirrors `RateLimitMiddleware._get_client`'s lazy-construction pattern (see
    `presentation/middleware/rate_limit.py`): `redis.from_url(...)` does not
    open a socket until the first command is sent, so building one per request
    here is cheap and side-effect-free at construction time. Exposed as its
    own FastAPI dependency (rather than inlined in `ready`) so tests can
    override it via `app.dependency_overrides` to simulate a Redis outage
    without a real server.
    """
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


@router.get("/health")
async def health() -> dict:
    """Liveness probe. Always 200 if the process can answer HTTP at all."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(
    db_session: AsyncSession = Depends(get_db_session),
    redis_client: "redis.Redis" = Depends(get_redis_client),
) -> JSONResponse:
    """Readiness probe: 200 only if both Postgres and Redis answer within budget."""
    failed_dependencies: List[str] = []

    try:
        await asyncio.wait_for(db_session.execute(text("SELECT 1")), timeout=_CHECK_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("Readiness check: database dependency failed.", exc_info=True)
        failed_dependencies.append("database")

    try:
        await asyncio.wait_for(redis_client.ping(), timeout=_CHECK_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("Readiness check: redis dependency failed.", exc_info=True)
        failed_dependencies.append("redis")
    finally:
        # Tear down the connection pool this request-scoped client opened.
        # Never let a close-time failure mask the actual check result
        # computed above -- a probe response is more valuable than a
        # perfectly clean connection teardown.
        try:
            await redis_client.aclose()
        except Exception:
            pass

    if failed_dependencies:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "failed_dependencies": failed_dependencies},
        )

    return JSONResponse(status_code=200, content={"status": "ready"})

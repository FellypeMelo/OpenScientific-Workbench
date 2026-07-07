from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from src.infrastructure.persistence.database import engine, init_models
from src.presentation.middleware.jwt_auth import JWTAuthMiddleware
from src.presentation.middleware.rate_limit import RateLimitMiddleware
from src.presentation.middleware.security_headers import SecurityHeadersMiddleware
from src.presentation.routes.sessions import router as sessions_router
from src.presentation.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure the ORM tables exist. There is no Alembic migration tool wired
    # up yet (Fase 1 scope is limited to fiar Postgres na aplicação), so `create_all`
    # is used to bootstrap a fresh SQLite/Postgres database for local dev and tests.
    await init_models()
    yield
    # Shutdown: dispose the engine's connection pool cleanly.
    await engine.dispose()


app = FastAPI(
    title="OpenScientific-Workbench API Gateway",
    description="Zero-Trust secure agent gateway for executing remote bioinformatics workflows.",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware registration order (Fase 2 - security middleware).
#
# Starlette/FastAPI treat middleware as a stack: the LAST one added via
# `add_middleware` becomes the OUTERMOST layer, so it runs first on the request path
# and last on the response path (https://fastapi.tiangolo.com/tutorial/middleware/).
# Adding them in this order therefore yields, on the request path:
#   SecurityHeadersMiddleware -> JWTAuthMiddleware -> RateLimitMiddleware -> route
# and the exact reverse on the response path.
#
# - `JWTAuthMiddleware` runs BEFORE `RateLimitMiddleware` (not after, as a naive
#   "throttle auth attempts" instinct might suggest). This gateway has no
#   login/password endpoint to brute-force yet (tokens are issued externally --
#   see the module docstring in `middleware/jwt_auth.py`), so a stateless HS256
#   decode+signature check is O(1) and cheap, not the kind of expensive operation
#   (e.g. bcrypt password hashing) that classic "rate-limit before auth" advice is
#   protecting. Running JWT first instead lets `RateLimitMiddleware` key its
#   counter by the authenticated `sub` claim (`request.state.user`) when present,
#   which is fairer than a pure-IP limit (it doesn't let many legitimate users
#   behind one NAT/corporate IP starve each other) and still falls back to IP-based
#   limiting for anonymous/rejected requests. Unauthenticated floods still pay a
#   bounded, cheap cost per request (an immediate 401, no Redis round trip, no
#   route execution), so this ordering does not reopen a volumetric-abuse hole.
# - `SecurityHeadersMiddleware` is outermost (added last) so it wraps every
#   response -- including the 401s/429s raised by the two layers above -- and never
#   misses stamping the hardening headers just because a request was rejected
#   upstream.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(JWTAuthMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


# Global Error Handler (Matches error_catalog.md guidelines)
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    error_msg = str(exc)
    
    # 1. Catch Path Traversal Violations
    if "traversal" in error_msg or "blocked" in error_msg:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error_code": 4001, "message": "Access Denied: Path traversal detected."}
        )
        
    # 2. Catch Critical Numeric Divergences (Float Hallucination)
    elif "ERR_NUMERIC_DIVERGENCE" in error_msg:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error_code": 4002, "message": "Numerical Divergence error: Exceeds precision bounds (1e-5)."}
        )
        
    # 3. Catch Token Exhaustion Errors
    elif "FATAL_LLM_BUDGET_EXCEEDED" in error_msg:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"error_code": 4003, "message": "Token budget exhausted: MCTS loop terminated."}
        )
        
    # Default fallback
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error_code": 4000, "message": error_msg}
    )

# Mount Routes under /api/v1 prefix
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")

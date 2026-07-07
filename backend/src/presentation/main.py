from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from src.infrastructure.persistence.database import engine, init_models
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

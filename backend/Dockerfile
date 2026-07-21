# syntax=docker/dockerfile:1
#
# Multi-stage build for the OSW FastAPI backend.
#
# Stage 1 ("builder"): installs the project's runtime dependencies (declared in
# `pyproject.toml`'s `[project.dependencies]`) into an isolated virtualenv. The
# `[dependency-groups].dev` group (pytest, mypy, ruff, ...) is intentionally
# NEVER installed here -- `pip install .` only ever resolves the base
# `dependencies` list, so the dev toolchain never reaches the runtime image.
#
# Stage 2 ("runtime"): a fresh slim image containing only the built virtualenv
# plus a clean copy of `src/` (application code) -- no `.venv`, no `.git`, no
# `tests/`, no build tooling. Runs as a non-root user.

FROM python:3.12-slim AS builder

# Keep pip quiet/deterministic and prevent .pyc write races during install.
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Isolated virtualenv so stage 2 can copy it wholesale without dragging in
# system site-packages or pip/setuptools themselves.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# `pyproject.toml`'s `readme = "README.md"` makes this file a required input to
# the build backend (setuptools refuses to build metadata if it is missing) --
# copy it alongside `pyproject.toml` before the dependency-only install layer so
# this rarely-changing layer stays cached across `src/` edits.
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip && pip install .

# ---------------------------------------------------------------------------

FROM python:3.12-slim AS runtime

# Non-root runtime user (defense in depth -- see docker-compose.prod.yml /
# k8s manifests for the rest of the hardening story: read-only root FS,
# dropped capabilities, etc. are applied at the orchestrator level).
RUN groupadd --system --gid 1000 osw && \
    useradd --system --uid 1000 --gid osw --no-create-home --shell /usr/sbin/nologin osw

WORKDIR /app

# `WORKDIR /app` + `PYTHONPATH=/app` is what lets `uvicorn src.presentation.main:app`
# resolve `src` as an importable package regardless of whether the CMD below is
# invoked as a console-script entry point or via `python -m` (only the latter
# would otherwise add the current directory to `sys.path` automatically).
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv
# Clean copy of application code only (no tests/, no .venv, no .git, no
# .egg-info build leftovers -- see backend/.dockerignore).
COPY src ./src

RUN chown -R osw:osw /app
USER osw

EXPOSE 8000

# Used by `docker-compose.prod.yml` / plain `docker run` deployments (k8s uses
# its own separate readiness+liveness probes instead, see
# `k8s/backend-deployment.yaml`). Hits `/health` -- the liveness-only probe
# (see `presentation/routes/health.py`'s module docstring): no downstream
# Postgres/Redis calls, so a database outage never causes Docker to
# kill-and-restart an otherwise-healthy container. `/health` is allowlisted
# unauthenticated in `presentation/middleware/jwt_auth.py`. Implemented with
# the stdlib (`urllib`) rather than curl/wget, neither of which exists in the
# `python:3.12-slim` runtime image.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

# Exec form: signals (SIGTERM on `docker stop` / k8s pod termination) reach
# uvicorn directly instead of a shell process.
CMD ["uvicorn", "src.presentation.main:app", "--host", "0.0.0.0", "--port", "8000"]

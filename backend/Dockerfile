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

# ---------------------------------------------------------------------------
# Stage "sandbox-toolkit": builds the SEPARATE conda/micromamba environment
# that sandboxed research scripts (python3/bash/Rscript, run inside
# `BubblewrapSandboxDriver`'s bwrap jail -- see
# `src/infrastructure/sandbox/bubblewrap_driver.py`) see on PATH. Deliberately
# NOT the app's own `/opt/venv` below -- an untrusted/LLM-generated script
# must never be able to import this app's own dependencies (DB credential
# helpers, JWT signing code, ...) even by accident. Runs in parallel with the
# "builder" stage (independent, no shared inputs) under BuildKit.
#
# Uses micromamba (a single static binary, no separate conda bootstrap image
# needed) against `backend/sandbox/environment.yml` -- see that file's header
# comment for why some bioconda package names there are unverified (never
# solved/built before this stage existed). If this stage fails to solve, fix
# the offending package name in `environment.yml`, not here.
FROM mambaorg/micromamba:1.5-bookworm-slim AS sandbox-toolkit

COPY --chown=$MAMBA_USER:$MAMBA_USER sandbox/environment.yml /tmp/environment.yml
RUN micromamba create -y -p /opt/sandbox-env -f /tmp/environment.yml && \
    micromamba clean --all --yes

COPY --chown=$MAMBA_USER:$MAMBA_USER sandbox/requirements-pip.txt /tmp/requirements-pip.txt
RUN /opt/sandbox-env/bin/pip install --no-cache-dir -r /tmp/requirements-pip.txt

# ---------------------------------------------------------------------------

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

# Non-root runtime user (defense in depth -- see docker-compose.yml /
# k8s manifests for the rest of the hardening story: read-only root FS,
# dropped capabilities, etc. are applied at the orchestrator level).
RUN groupadd --system --gid 1000 osw && \
    useradd --system --uid 1000 --gid osw --no-create-home --shell /usr/sbin/nologin osw

# Bubblewrap (bwrap) -- unprivileged Linux sandboxing for code execution,
# replacing the earlier gVisor/runsc design (see
# `src/infrastructure/sandbox/`). No Docker socket exposure and no second
# privileged container needed: `bwrap` runs as a regular subprocess using
# user namespaces. Installed here so it's on PATH in the runtime image; the
# Python adapter that actually shells out to it lives in
# `infrastructure/sandbox/bubblewrap_driver.py`.
RUN apt-get update && \
    apt-get install -y --no-install-recommends bubblewrap && \
    rm -rf /var/lib/apt/lists/*

# The sandbox toolkit (biopython/scanpy/RDKit/samtools/R/... -- see
# `sandbox/environment.yml`) that sandboxed scripts actually run against.
# `bubblewrap_driver.py::_RO_BIND_EXTRA_DIRS` binds this path read-only into
# the bwrap jail and puts it first on the jailed PATH, so `python3`/`Rscript`/
# CLI tools here resolve before anything under `/usr` -- this is intentional:
# the sandbox toolkit takes precedence over any incidental system Python/R.
COPY --from=sandbox-toolkit /opt/sandbox-env /opt/sandbox-env

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
# `scripts/run_worker.py` -- the RQ worker entrypoint for the local
# (HPC_BACKEND=local, default) job queue backend, run by `docker-compose.yml`'s
# `worker` service instead of uvicorn. See that script's module docstring for
# why it exists instead of the bare `rq worker osw-jobs` CLI command.
COPY scripts ./scripts
# Alembic migration sources (see `backend/migrations/`). NOT run automatically by
# the CMD below -- `presentation/main.py`'s `lifespan` only bootstraps tables via
# `create_all` when `ENV != production` (see that module). This same image is what
# a deploy runs `alembic upgrade head` against instead, as a separate init step,
# before any replica starts serving traffic (`docker compose run --rm backend
# alembic upgrade head`; see `backend/README.md` for the exact command).
COPY alembic.ini ./
COPY migrations ./migrations

RUN chown -R osw:osw /app
USER osw

EXPOSE 8000

# Used by `docker-compose.yml` / plain `docker run` deployments (k8s uses
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

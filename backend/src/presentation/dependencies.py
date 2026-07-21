"""
FastAPI dependency providers wiring the Protocol-based domain ports
(`src/domain/ports/`) to their real Postgres-pattern adapter implementations
(`src/infrastructure/persistence/`), each constructed with the request-scoped
`AsyncSession` supplied by `get_db_session`.

Routes should depend on these providers (e.g. `Depends(get_user_repository)`)
instead of importing repository implementations directly, keeping the
presentation layer decoupled from the concrete persistence adapter in use.
"""
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.artifact_repository import ArtifactRepositoryPort
from src.domain.ports.hpc_job_dispatcher import HPCJobDispatcherPort
from src.domain.ports.mcp_router import MCPRouterPort
from src.domain.ports.node_executor import NodeExecutorPort
from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.ports.user_repository import UserRepositoryPort
from src.domain.ports.vram_checker import VRAMCheckerPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.infrastructure.config import settings
from src.infrastructure.hpc.local_job_dispatcher import LocalJobDispatcher
from src.infrastructure.hpc.nvidia_vram_checker import NvidiaVRAMChecker
from src.infrastructure.hpc.slurm_dispatcher import SlurmSSHDispatcher
from src.infrastructure.mcp.bio_direct_adapters import register_direct_bio_tools
from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.persistence.database import get_db_session
from src.infrastructure.persistence.postgres_artifact_repo import PostgresArtifactRepository
from src.infrastructure.persistence.postgres_session_repo import PostgresSessionRepository
from src.infrastructure.persistence.postgres_user_repo import PostgresUserRepository
from src.infrastructure.persistence.postgres_workspace_repo import PostgresWorkspaceRepository
from src.infrastructure.sandbox.bubblewrap_driver import BubblewrapSandboxDriver
from src.infrastructure.sandbox.sandbox_node_executor import SandboxNodeExecutor
from src.infrastructure.security.vault_client import VaultClient
from src.infrastructure.skills.skill_registration import register_skills
from src.infrastructure.telemetry import get_tracer

logger = logging.getLogger(__name__)


def get_current_user_id(request: Request) -> str:
    """
    Resolve the authenticated caller's user id from the JWT claims that
    `JWTAuthMiddleware` (see `presentation/middleware/jwt_auth.py`) attaches to
    `request.state.user` on every non-allowlisted request, BEFORE any route
    handler runs.

    Security note (IDOR fix): route handlers MUST derive "who is asking" from
    this dependency, never from a client-supplied `user_id`/`owner_id` field in
    a request body or path parameter. Trusting a client-supplied identifier
    there is exactly an Insecure Direct Object Reference hole -- it lets any
    authenticated caller act as, or read data belonging to, an arbitrary other
    user simply by naming their id. This dependency is the single place that
    trust boundary is enforced.

    Defensive-only 401 branch: in practice this is unreachable in normal
    operation -- `JWTAuthMiddleware` always either sets `request.state.user` on
    a valid token or short-circuits the request with its own 401 response
    before any route (and therefore this dependency) ever runs. It exists so a
    route that is accidentally left out of the middleware's coverage (or a
    test app that mounts a route without the middleware) fails loudly with a
    401 instead of silently trusting a forged/absent identity.
    """
    user = getattr(request.state, "user", None)
    if not isinstance(user, dict) or not user.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return str(user["sub"])


def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserRepositoryPort:
    return PostgresUserRepository(session)


def get_workspace_repository(
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceRepositoryPort:
    return PostgresWorkspaceRepository(session)


def get_session_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SessionRepositoryPort:
    return PostgresSessionRepository(session)


def get_artifact_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ArtifactRepositoryPort:
    return PostgresArtifactRepository(session)


def get_sandbox_driver() -> BubblewrapSandboxDriver:
    """Constructs the real sandbox isolation driver (RF-005/RNF-001/RNF-002).

    Branches on `settings.SANDBOX_RUNTIME` ("bubblewrap" by default -- real
    isolation; "subprocess"/"mock" for hosts that genuinely cannot run bwrap,
    e.g. this project's Windows dev sandbox). Unlike every other real-vs-mock
    adapter in this codebase, sandboxed code execution does NOT silently
    degrade when misconfigured: constructing this with
    `SANDBOX_RUNTIME=bubblewrap` on a host missing (or with a non-functional)
    `bwrap` binary raises `SandboxUnavailableError` loudly instead --
    sandboxing is a security boundary, not a nice-to-have (see
    `infrastructure/sandbox/bubblewrap_driver.py`'s module docstring).

    Callable both as a FastAPI `Depends(get_sandbox_driver)` and directly
    (e.g. `get_node_executor(get_sandbox_driver())`) when a route needs to
    resolve it conditionally/lazily instead of unconditionally on every
    request -- see `presentation/routes/tasks.py`.

    `tracer=get_tracer()` (RNF-004) wires this driver's real construction site
    to the globally-configured OpenTelemetry provider `setup_telemetry()` boots
    in `presentation/main.py`, so every `execute_*` call opens a real
    `sandbox.execute` span (see `BubblewrapSandboxDriver.__init__`'s `tracer`
    param and its usage in `execute_bash`/etc.) instead of the constructor's
    `tracer=None` default silently emitting no spans at all.
    """
    return BubblewrapSandboxDriver(runtime=settings.SANDBOX_RUNTIME, tracer=get_tracer())


def get_node_executor(
    driver: BubblewrapSandboxDriver = Depends(get_sandbox_driver),
) -> NodeExecutorPort:
    return SandboxNodeExecutor(driver)


def get_credential_provider() -> Optional[VaultClient]:
    """Returns a real `VaultClient` when `settings.VAULT_TOKEN` is configured,
    else `None` (RNF-003 gap closure).

    Only matters for the optional `HPC_BACKEND=slurm` path below --
    `SlurmSSHDispatcher.credential_provider`, when set, fetches a Vault
    ephemeral SSH OTP instead of using the static `SLURM_SSH_KEY_PATH` key
    file per-connection. The default `HPC_BACKEND=local` path never touches
    Vault at all. Mirrors the same "real infra not configured -> `None`/mock,
    never crash" gating every other Fase 4 adapter in this codebase uses
    (`VaultClient` itself already falls back to a mock token internally when
    unconfigured; this just decides whether to construct one at all).
    """
    if not settings.VAULT_TOKEN:
        return None
    return VaultClient()


def get_hpc_dispatcher(
    credential_provider: Optional[VaultClient] = Depends(get_credential_provider),
) -> HPCJobDispatcherPort:
    """Selects the HPC job dispatcher backend per `settings.HPC_BACKEND`
    (RF-006/RNF-008 gap closure):

    - "local" (default): `LocalJobDispatcher` -- a Redis-backed RQ queue
      consumed by `scripts/run_worker.py` / `docker-compose.yml`'s `worker`
      service, reusing the same real sandbox isolation DAG-node execution
      uses (RF-005). Matches this project's locked single-local-server
      architecture; needs no cluster or Vault.
    - "slurm": `SlurmSSHDispatcher` -- real SSH dispatch to an actual Slurm
      cluster, with `credential_provider` (Vault, see `get_credential_provider`
      above) wired in so real ephemeral-OTP SSH auth (RNF-003) is actually
      reachable outside of tests, not just constructible.

    `HPC_BACKEND` is fixed per-deployment (an operator sets one value and
    restarts, not a per-request choice), so both `LocalJobDispatcher` and
    `SlurmSSHDispatcher` are cheap, effectively stateless adapters over an
    external store (Redis / an SSH+Slurm cluster) -- constructing a fresh
    instance per request (the same pattern every other `Depends()` factory in
    this module already uses) is correct and keeps `dispatch()` and a later
    `poll_status()` call always talking to the SAME configured backend, with
    no cross-backend ambiguity to resolve.
    """
    if settings.HPC_BACKEND == "slurm":
        return SlurmSSHDispatcher(credential_provider=credential_provider)
    return LocalJobDispatcher()


def get_vram_checker() -> VRAMCheckerPort:
    """Constructs the real VRAM availability checker (RNF-008), shelling out
    to `nvidia-smi`. Safe to construct unconditionally -- it does not touch
    the GPU until `available_vram_gb()` is actually awaited, and reports
    `0.0` (not an error) on a host with no NVIDIA GPU (see
    `infrastructure/hpc/nvidia_vram_checker.py`)."""
    return NvidiaVRAMChecker()


# Process-wide MCP tool registry singleton (RF-004/RF-009 gap closure).
#
# Unlike every other provider in this module, `MCPServerRegistry` is NOT
# constructed fresh per request: it is a plain in-memory `Dict[str, Callable]`
# (see `infrastructure/mcp/server_registry.py`) whose whole purpose is to hold
# a set of routable tool handlers that only ever need to be assembled once per
# process, not re-registered on every single request. A lazily-populated
# module-level singleton (mirroring `jwt_auth.py`'s `_SIGNING_SECRET` pattern,
# just lazy instead of eager) is the simplest correct shape for that -- this
# codebase has no `app.state`-based DI precedent to follow instead.
_mcp_registry: Optional[MCPServerRegistry] = None


def get_mcp_registry() -> MCPRouterPort:
    """Returns the process-wide `MCPServerRegistry`, constructing and
    populating it on first call:

    - Direct bio-tool adapters (RF-004: real UniProt/RCSB PDB/STRING REST API
      calls, see `infrastructure/mcp/bio_direct_adapters.py`) are ALWAYS
      registered -- they are free, public, unauthenticated APIs that need no
      configuration, unlike every other config-gated adapter in this
      codebase.
    - Compiled Skills (RF-009, see `infrastructure/skills/skill_registration.py`)
      are registered from `settings.SKILLS_ROOT`, guarded in try/except: a
      missing/empty/malformed skills directory must never break the first
      request that resolves this dependency (or app startup, if a caller
      warms it eagerly). As of this writing no real scientific `SKILL.md`
      content exists in this repo yet (see `infrastructure/config.py`'s
      `SKILLS_ROOT` docstring), so this registers zero skills today -- that
      is expected, not a bug.

    Callable both as a FastAPI `Depends(get_mcp_registry)` and directly.
    """
    global _mcp_registry
    if _mcp_registry is None:
        registry = MCPServerRegistry()
        register_direct_bio_tools(registry)
        try:
            register_skills(registry, settings.SKILLS_ROOT)
        except Exception:
            logger.warning(
                "register_skills() failed for SKILLS_ROOT=%r; continuing with "
                "zero skills registered (bio tools remain available).",
                settings.SKILLS_ROOT,
                exc_info=True,
            )
        _mcp_registry = registry
    return _mcp_registry

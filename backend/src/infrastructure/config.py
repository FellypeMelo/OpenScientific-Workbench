"""
Centralized application configuration, loaded from environment variables and/or a
local `.env` file via `pydantic-settings`.

Design notes:
- Every field has either a safe local-dev default or is `Optional[...] = None`. This
  guarantees that `Settings()` never raises at import time, even in a fresh checkout
  or CI runner where no `.env` file exists yet. Modules that import `settings` (e.g.
  `src.presentation.main`) must therefore stay importable without any environment
  configured.
- Secrets (`NEO4J_PASSWORD`, `VAULT_TOKEN`, `JWT_SECRET`, LLM provider API keys) have
  NO insecure hardcoded default (no "changeme"/"secret" fallback). They default to
  `None` instead. Call sites that require a real value (the Fase 2 JWT middleware, the
  Fase 3 LLM provider clients, etc.) are responsible for validating/raising close to
  the point of use if the resolved value is `None` outside of local development.
"""
from pathlib import Path
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolved once at import time (same rationale as `jwt_auth.py`'s
# `_SIGNING_SECRET`): `config.py` lives at
# `<repo_root>/backend/src/infrastructure/config.py`, so `parents[3]` from
# this file is `<repo_root>` -- `[0]=infrastructure, [1]=src, [2]=backend,
# [3]=<repo_root>`. Verified by actually walking `Path(__file__).resolve()`
# rather than guessed.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application-wide configuration values."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Runtime environment (Fase 2 - middleware) ---
    # Drives safety-critical branching in the JWT middleware (see
    # `presentation/middleware/jwt_auth.py`): a missing `JWT_SECRET` is tolerated
    # (with a loud warning + ephemeral fallback) everywhere except `"production"`,
    # where it instead raises at startup. Real deployments MUST set
    # `ENV=production` explicitly via the environment; the default here is the
    # permissive one on purpose so a fresh checkout / CI runner / local dev server
    # boots without any `.env` file.
    #
    # Constrained to a `Literal` (not a bare `str`) so a typo'd deployment value
    # (e.g. `ENV=prod` instead of `ENV=production`) fails LOUDLY at `Settings()`
    # construction time -- `pydantic-settings` raises a `ValidationError` before
    # the app ever finishes importing -- instead of silently falling through to
    # `jwt_auth.py`'s permissive "not production" dev branch (ephemeral JWT
    # secret, etc.) while the operator believes they configured a real
    # production deployment.
    ENV: Literal["development", "staging", "production"] = "development"

    # --- Logging (production hardening) ---
    # Consumed by `logging.config.dictConfig` in `presentation/main.py` to set the
    # root logger level. Kept a permissive `str` (not a `Literal`) since it is
    # passed straight through to the stdlib `logging` module, which already
    # validates level names itself.
    LOG_LEVEL: str = "INFO"

    # --- Relational persistence (Fase 1 - Postgres wiring) ---
    # Defaults to a local SQLite file (via aiosqlite) so the app and test suite can
    # boot without a running Postgres instance. Override with a
    # `postgresql+asyncpg://...` URL in staging/production.
    DATABASE_URL: str = "sqlite+aiosqlite:///./osw_dev.db"

    # --- Cache / rate limiting (Fase 2 - middleware) ---
    REDIS_URL: str = "redis://localhost:6379/0"
    # Fixed-window request budget enforced by `presentation/middleware/rate_limit.py`.
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # --- Knowledge graph (Fase 4 - GraphRAG) ---
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: Optional[str] = None

    # --- Vector store ---
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # --- Secrets manager (Fase 4 - Vault) ---
    VAULT_ADDR: str = "http://localhost:8200"
    VAULT_TOKEN: Optional[str] = None
    # Name of the Vault SSH secrets engine role (see `vault write ssh/roles/<name>`)
    # used to request ephemeral, one-time-password SSH credentials. Not a secret
    # itself (just an identifier), so it gets a safe non-`None` default like
    # `NEO4J_USER` above.
    VAULT_SSH_ROLE: str = "hpc-ssh-role"

    # --- HPC job dispatch backend selection (RF-006/RNF-003/RNF-008 gap closure) ---
    # Which `HPCJobDispatcherPort` adapter `presentation/dependencies.py`'s
    # `get_hpc_dispatcher()` constructs:
    #   - "local" (default): `LocalJobDispatcher` (see
    #     `infrastructure/hpc/local_job_dispatcher.py`) -- a Redis-backed RQ
    #     queue ("osw-jobs") consumed by `scripts/run_worker.py` /
    #     `docker-compose.yml`'s `worker` service. Matches this project's
    #     locked architecture (single local Linux server, no external
    #     cluster) and needs no extra infra beyond the Redis instance every
    #     other adapter here already uses.
    #   - "slurm": `SlurmSSHDispatcher` (see
    #     `infrastructure/hpc/slurm_dispatcher.py`) -- real SSH dispatch to an
    #     actual Slurm cluster, for operators who have one. Dormant by
    #     default; only reachable by explicitly setting this to "slurm" (and,
    #     for real dispatch rather than its own mock fallback, the
    #     `SLURM_SSH_*` settings below).
    # Constrained to a `Literal` for the same reason as `ENV` above: a typo'd
    # value fails loudly at `Settings()` construction instead of silently
    # falling through to a default nobody chose on purpose.
    HPC_BACKEND: Literal["local", "slurm"] = "local"

    # --- HPC / Slurm dispatch (Fase 4 - paramiko SSH) ---
    # Real `sbatch` dispatch over SSH (see `infrastructure/hpc/slurm_dispatcher.py`)
    # is only attempted when ALL THREE of these are configured. Any one of them
    # missing means "no real HPC gateway is reachable from here" (a fresh
    # checkout, CI runner, or local dev machine), so the dispatcher falls back to
    # its deterministic mock job id instead of failing or silently doing nothing.
    # Only relevant when HPC_BACKEND=="slurm" above.
    SLURM_SSH_HOST: Optional[str] = None
    SLURM_SSH_USER: Optional[str] = None
    SLURM_SSH_KEY_PATH: Optional[str] = None

    # --- Workspace storage (RNF-007 - Btrfs CoW forking) ---
    # Enables real `btrfs subvolume snapshot` O(1) forks. Defaults to False so
    # dev/CI (and any non-Btrfs host) uses the recursive-copy fallback; set to
    # True on a Linux host with a Btrfs-formatted workspace volume. The manager
    # additionally self-disables off Linux, so enabling it is always safe.
    USE_BTRFS: bool = False

    # --- Workspace file upload (RF-005 gap closure) ---
    # Hard cap on a single `POST /workspaces/{id}/files` upload, enforced via
    # bounded chunked reads (see `presentation/routes/workspaces.py`) so a
    # malicious/oversized upload can't exhaust disk before being rejected.
    MAX_UPLOAD_MB: int = 50

    # --- Sandboxed code execution (RF-005/RNF-001/RNF-002 - bubblewrap) ---
    # Which isolation backend `SandboxNodeExecutor` (see
    # `infrastructure/sandbox/sandbox_node_executor.py`) runs DAG-node
    # `language`/`command` pairs through:
    #   - "bubblewrap" (default, REAL isolation): shells out to `bwrap` with a
    #     locked-down profile (read-only system binds, isolated tmpfs
    #     workspace, no network, resource limits). This is the only backend
    #     that provides an actual security boundary.
    #   - "subprocess": runs the command directly via `subprocess.run`, no
    #     isolation at all. Fast for unit tests; NEVER use for untrusted code.
    #   - "mock": no execution happens at all; a deterministic canned result is
    #     returned. For hosts that genuinely cannot run bwrap (e.g. this
    #     project's Windows dev sandbox).
    #
    # Deliberately NOT config-gated to a silent mock fallback like the other
    # adapters in this codebase (Neo4j/Vault/Slurm/etc): sandboxed code
    # execution is a security boundary, not a nice-to-have. If this stays
    # "bubblewrap" (the real default) and the `bwrap` binary is missing or
    # non-functional on this host, `BubblewrapSandboxDriver` raises
    # `SandboxUnavailableError` LOUDLY at construction time instead of
    # silently falling back to unsandboxed execution -- an operator must
    # either install bubblewrap or explicitly opt into "subprocess"/"mock".
    SANDBOX_RUNTIME: Literal["bubblewrap", "subprocess", "mock"] = "bubblewrap"

    # --- Auth (Fase 2 - JWT middleware) ---
    # No insecure default is supplied on purpose. Left `Optional`/`None` so importing
    # this module never crashes in dev/CI where no `.env` exists yet; the JWT
    # middleware MUST fail fast if it resolves `settings.JWT_SECRET` as `None` outside
    # of local development, rather than silently falling back to a hardcoded secret.
    JWT_SECRET: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 30

    # --- LLM providers (BYOK - Fase 3 streaming) ---
    DEEPSEEK_API_KEY: Optional[str] = None
    GLM_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None

    # --- MCP tool routing / Skills (RF-004/RF-009 gap closure) ---
    # Filesystem root `infrastructure/skills/skill_registration.py::register_skills`
    # walks for `*/SKILL.md` directories to compile and register as routable MCP
    # tools (see `presentation/dependencies.py::get_mcp_registry`). Defaults to
    # `<repo_root>/skills` -- a directory that does not exist in this repo yet
    # (only unrelated coding-agent skills live under `.agents/skills`), so out of
    # the box this registers zero skills. That is expected: `register_skills`
    # already no-ops safely on a missing/empty directory (`Path.glob` on a
    # nonexistent path yields no matches rather than raising), and the call site
    # additionally wraps it in try/except as defense in depth. Override via the
    # `SKILLS_ROOT` env var once real scientific Skill content is authored.
    SKILLS_ROOT: str = str(_REPO_ROOT / "skills")

    # --- CORS (Fase 5 - frontend gap closure) ---
    # The Next.js frontend (`frontend/`) runs on its own origin (`next dev`
    # defaults to `http://localhost:3000`), distinct from this API's origin --
    # without `CORSMiddleware` (see `presentation/main.py`), every browser
    # fetch from it would be blocked, and any request carrying a custom header
    # (this API requires `Authorization: Bearer <token>` on nearly every
    # route) triggers a CORS preflight `OPTIONS` request that has no bearer
    # token at all. Comma-separated so multiple deployed frontend origins can
    # be configured without code changes.
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]


# Module-level singleton. `Settings()` instantiation must never raise (see class
# docstring above), so importing `settings` is safe anywhere in the codebase.
settings = Settings()

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
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    ENV: str = "development"

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

    # --- HPC / Slurm dispatch (Fase 4 - paramiko SSH) ---
    # Real `sbatch` dispatch over SSH (see `infrastructure/hpc/slurm_dispatcher.py`)
    # is only attempted when ALL THREE of these are configured. Any one of them
    # missing means "no real HPC gateway is reachable from here" (a fresh
    # checkout, CI runner, or local dev machine), so the dispatcher falls back to
    # its deterministic mock job id instead of failing or silently doing nothing.
    SLURM_SSH_HOST: Optional[str] = None
    SLURM_SSH_USER: Optional[str] = None
    SLURM_SSH_KEY_PATH: Optional[str] = None

    # --- Workspace storage (RNF-007 - Btrfs CoW forking) ---
    # Enables real `btrfs subvolume snapshot` O(1) forks. Defaults to False so
    # dev/CI (and any non-Btrfs host) uses the recursive-copy fallback; set to
    # True on a Linux host with a Btrfs-formatted workspace volume. The manager
    # additionally self-disables off Linux, so enabling it is always safe.
    USE_BTRFS: bool = False

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

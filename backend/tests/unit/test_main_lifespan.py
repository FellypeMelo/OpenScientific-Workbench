"""
Regression tests for the `lifespan()` ORM-bootstrap gating in `presentation/main.py`.

`Base.metadata.create_all` (via `init_models()`) is a dev/test convenience only --
production schema changes must go through Alembic (`backend/migrations/`), applied
via a separate `alembic upgrade head` init step before the app process starts. These
tests assert that `lifespan()` calls `init_models()` for every non-production `ENV`
value and skips it entirely when `ENV == "production"`, mocking only `init_models`
itself (the actual DB-bootstrap operation) -- never the branching logic under test.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.presentation.main import app, lifespan


@pytest.mark.asyncio
@pytest.mark.parametrize("env_value", ["development", "staging"])
async def test_lifespan_bootstraps_tables_outside_production(env_value):
    with patch("src.presentation.main.settings") as mock_settings, patch(
        "src.presentation.main.init_models", new_callable=AsyncMock
    ) as mock_init_models, patch(
        "src.presentation.main.engine", new_callable=MagicMock
    ) as mock_engine:
        mock_settings.ENV = env_value
        mock_engine.dispose = AsyncMock()

        async with lifespan(app):
            pass

        mock_init_models.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_skips_create_all_in_production():
    with patch("src.presentation.main.settings") as mock_settings, patch(
        "src.presentation.main.init_models", new_callable=AsyncMock
    ) as mock_init_models, patch(
        "src.presentation.main.engine", new_callable=MagicMock
    ) as mock_engine:
        mock_settings.ENV = "production"
        mock_engine.dispose = AsyncMock()

        async with lifespan(app):
            pass

        mock_init_models.assert_not_awaited()


@pytest.mark.asyncio
async def test_lifespan_always_disposes_engine_regardless_of_env():
    with patch("src.presentation.main.settings") as mock_settings, patch(
        "src.presentation.main.init_models", new_callable=AsyncMock
    ), patch(
        "src.presentation.main.engine", new_callable=MagicMock
    ) as mock_engine:
        mock_settings.ENV = "production"
        mock_engine.dispose = AsyncMock()

        async with lifespan(app):
            pass

        mock_engine.dispose.assert_awaited_once()

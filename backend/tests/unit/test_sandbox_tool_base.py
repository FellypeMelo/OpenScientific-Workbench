"""Unit tests for the shared `run_in_sandbox` helper (Fase 5 foundation) --
see `infrastructure/tools/_sandbox_tool_base.py`'s module docstring for why
this is the ONLY layer Fase 5 tools' own tests can exercise for real (the
`script_body` strings import packages that only exist in the sandbox
toolkit's conda env, never in this repo's own pytest venv)."""
import json

import pytest

from src.infrastructure.tools._sandbox_tool_base import (
    FakeSandboxDriver,
    NotSupportedError,
    SandboxToolError,
    run_in_sandbox,
)


def test_run_in_sandbox_round_trips_args_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"answer": 42})

    result = run_in_sandbox(
        driver,
        script_body="print(_json.dumps({'answer': _args['x'] + 1}))",
        args={"x": 41},
    )

    assert result == {"answer": 42}
    assert driver.last_args() == {"x": 41}


def test_run_in_sandbox_raises_on_nonzero_exit():
    driver = FakeSandboxDriver()
    driver.exit_code = 1
    driver.stdout = "Traceback: boom"

    with pytest.raises(SandboxToolError, match="exit 1"):
        run_in_sandbox(driver, script_body="raise RuntimeError('boom')", args={})


def test_run_in_sandbox_raises_on_unparseable_stdout():
    driver = FakeSandboxDriver()
    driver.stdout = "not json at all"

    with pytest.raises(SandboxToolError, match="not valid JSON"):
        run_in_sandbox(driver, script_body="print('not json at all')", args={})


def test_run_in_sandbox_takes_last_line_when_script_prints_extra_noise():
    driver = FakeSandboxDriver()
    driver.stdout = "some warning from a library\n{\"ok\": true}"

    result = run_in_sandbox(driver, script_body="print(_json.dumps({'ok': True}))", args={})

    assert result == {"ok": True}


def test_not_supported_error_is_a_notimplementederror():
    with pytest.raises(NotImplementedError):
        raise NotSupportedError("TxGNN checkpoint not bundled; see docs/tools/UNSUPPORTED.md")

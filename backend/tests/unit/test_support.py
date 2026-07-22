"""Unit tests for `infrastructure/tools/support.py` (Fase 5, "Categoria:
Support tools"). Per `_sandbox_tool_base.py`'s "TESTING REALITY" docstring
section, `run_python_repl`'s sandboxed `script_body` is verified at the
WIRING layer only (argument validation, `args` JSON round-tripping via
`FakeSandboxDriver`) -- it never actually executes here.
`read_function_source_code` runs fully in-process (no sandbox involved), so
its tests exercise the real allowlist/reflection logic end to end."""
import json

import pytest
from pydantic import ValidationError

from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.tools._sandbox_tool_base import FakeSandboxDriver
from src.infrastructure.tools.support import (
    FunctionSourceAccessError,
    read_function_source_code,
    register_support_tools,
    run_python_repl,
)


@pytest.fixture
def driver(tmp_path):
    return FakeSandboxDriver(workspace_root=str(tmp_path / "workspace_fake_tools"))


# --- run_python_repl -------------------------------------------------------


def test_run_python_repl_valid_args_round_trip(driver):
    driver.stdout = json.dumps({"stdout": "2\n", "stderr": "", "error": None})

    result = run_python_repl({"command": "print(1 + 1)"}, driver)

    assert driver.last_args() == {"command": "print(1 + 1)"}
    assert result == {"stdout": "2\n", "stderr": "", "error": None}


def test_run_python_repl_missing_command_raises_before_sandbox(driver):
    with pytest.raises(ValidationError):
        run_python_repl({}, driver)

    assert driver.calls == []


def test_run_python_repl_rejects_whitespace_only_command(driver):
    with pytest.raises(ValidationError):
        run_python_repl({"command": "   "}, driver)

    assert driver.calls == []


def test_run_python_repl_reports_a_canned_error_result(driver):
    driver.stdout = json.dumps({"stdout": "", "stderr": "", "error": "ZeroDivisionError: division by zero"})

    result = run_python_repl({"command": "1 / 0"}, driver)

    assert result["error"] == "ZeroDivisionError: division by zero"


def test_run_python_repl_command_never_appears_literally_in_script_source(driver):
    """The command text must travel as sandboxed JSON *data*
    (`_args["command"]`), never spliced into the generated script's own
    source -- otherwise a command containing e.g. a triple-quote could break
    out of the wrapper script entirely."""
    driver.stdout = json.dumps({"stdout": "", "stderr": "", "error": None})

    run_python_repl({"command": "print('hello \"\"\" world')"}, driver)

    script_source, _ = driver.calls[-1]
    assert "hello" not in script_source
    assert "_args[\"command\"]" in script_source or "_args['command']" in script_source


# --- read_function_source_code ---------------------------------------------


def test_read_function_source_code_allows_infrastructure_tools_module():
    result = read_function_source_code(
        {"function_name": "src.infrastructure.tools._sandbox_tool_base.run_in_sandbox"}
    )

    assert result["function_name"] == "src.infrastructure.tools._sandbox_tool_base.run_in_sandbox"
    assert result["module"] == "src.infrastructure.tools._sandbox_tool_base"
    assert "def run_in_sandbox(" in result["source_code"]


def test_read_function_source_code_allows_infrastructure_mcp_module():
    result = read_function_source_code(
        {"function_name": "src.infrastructure.mcp.server_registry.MCPServerRegistry"}
    )

    assert "class MCPServerRegistry" in result["source_code"]


def test_read_function_source_code_rejects_module_outside_allowlist():
    with pytest.raises(FunctionSourceAccessError, match="outside the allowlisted"):
        read_function_source_code(
            {"function_name": "src.domain.services.path_guard.ensure_safe_relative_path"}
        )


def test_read_function_source_code_rejects_name_with_no_module_component():
    with pytest.raises(FunctionSourceAccessError, match="fully-qualified"):
        read_function_source_code({"function_name": "os"})


def test_read_function_source_code_rejects_nonexistent_attribute():
    with pytest.raises(FunctionSourceAccessError):
        read_function_source_code(
            {"function_name": "src.infrastructure.tools._sandbox_tool_base.this_does_not_exist"}
        )


def test_read_function_source_code_rejects_reflection_laundered_through_allowlisted_module():
    """`immunology.py` (allowlisted) imports `ensure_safe_relative_path` from
    `src.domain.services.path_guard` (NOT allowlisted) at module scope --
    asking for it BY the allowlisted module's own dotted name must still be
    refused, since the function is actually DEFINED outside the allowlist."""
    with pytest.raises(FunctionSourceAccessError, match="actually defined in module"):
        read_function_source_code(
            {"function_name": "src.infrastructure.tools.immunology.ensure_safe_relative_path"}
        )


def test_read_function_source_code_missing_function_name_raises_validation_error():
    with pytest.raises(ValidationError):
        read_function_source_code({})


def test_read_function_source_code_rejects_empty_function_name():
    with pytest.raises(ValidationError):
        read_function_source_code({"function_name": "   "})


def test_function_source_access_error_is_a_value_error():
    assert issubclass(FunctionSourceAccessError, ValueError)


# --- register_support_tools -------------------------------------------------


def test_register_support_tools_registers_both_tool_names():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()

    registered = register_support_tools(registry, driver)

    assert set(registered) == {"run_python_repl", "read_function_source_code"}
    for tool_name in registered:
        assert tool_name in registry.registry
        assert callable(registry.registry[tool_name])


def test_register_support_tools_run_python_repl_uses_the_given_driver():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"stdout": "ok\n", "stderr": "", "error": None})

    register_support_tools(registry, driver)
    handler = registry.registry["run_python_repl"]

    result = handler({"command": "print('ok')"})

    assert result == {"stdout": "ok\n", "stderr": "", "error": None}
    assert driver.calls  # the FakeSandboxDriver passed to register_* was actually used


def test_register_support_tools_read_function_source_code_needs_no_driver():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()

    register_support_tools(registry, driver)
    handler = registry.registry["read_function_source_code"]

    result = handler(
        {"function_name": "src.infrastructure.tools._sandbox_tool_base.run_in_sandbox"}
    )

    assert "def run_in_sandbox(" in result["source_code"]
    assert driver.calls == []  # never touched the sandbox

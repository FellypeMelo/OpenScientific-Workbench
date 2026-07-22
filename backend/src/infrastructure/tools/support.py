"""Support tools (Fase 5, "Categoria: Support tools" of
`backend/docs/tools/action_tool_catalog.md`).

Two very different tools live here, deliberately NOT following the usual
"validate -> path-guard -> sandbox" shape uniformly:

- ``run_python_repl`` -- a directly-callable MCP tool that runs arbitrary
  Python *inside the bwrap sandbox*, via the SAME mechanism every other
  action tool uses (`run_in_sandbox`, itself a thin wrapper around
  `driver.execute_python_script` -- the exact call
  `SandboxNodeExecutor._materialize_python_script`/`simulate()` makes for a
  ``language == "python"`` DAG node, see
  `infrastructure/sandbox/sandbox_node_executor.py`). This is not a new
  execution path, just that same mechanism exposed as a tool an LLM can call
  directly instead of only reachable via a DAG node. The caller-supplied
  ``command`` text is NEVER interpolated into the generated script's source
  -- it travels as JSON *data* (`_args["command"]`, read back inside the
  sandbox) and is only ever `exec()`'d there, inside the jail, never in this
  trusted backend process.
- ``read_function_source_code`` -- pure in-process `inspect.getsource`
  reflection, no sandbox involved (there is nothing to execute, it only
  reads already-loaded backend source). This is the one genuinely dangerous
  tool in the whole Fase 5 catalog if left unguarded: unlike every sandboxed
  action tool, an unguarded version of this one would let an LLM read ANY
  importable backend source straight out of the trusted process, including
  DB credential helpers and JWT signing code. It is therefore hard-allowlisted
  to modules under `src.infrastructure.tools.*` / `src.infrastructure.mcp.*`
  (the action-tool and DB/bio-adapter modules), and -- defense in depth --
  also re-checks the resolved object's OWN `__module__` after attribute
  lookup, so a caller can't launder a disallowed function's source by asking
  for it through an allowlisted module's re-exported/imported name for it
  (e.g. `src.infrastructure.tools.immunology.ensure_safe_relative_path`,
  which is imported at the top of that module but actually defined in
  `src.domain.services.path_guard`, outside the allowlist).

Neither tool takes a file-path-shaped argument, so `ensure_safe_relative_path`
is not used in this module.
"""
import functools
import importlib
import inspect
from typing import Any, List

from pydantic import BaseModel, Field, field_validator

from src.infrastructure.tools._sandbox_tool_base import run_in_sandbox

# ---------------------------------------------------------------------------
# run_python_repl
# ---------------------------------------------------------------------------


class RunPythonReplArgs(BaseModel):
    """Args for `run_python_repl`."""

    command: str = Field(..., min_length=1)

    @field_validator("command")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("command must be a non-empty string")
        return value


# Fixed, hand-written script -- `_args["command"]` (the only caller-influenced
# value) is only ever read as DATA and passed to `exec()`, never spliced into
# this source text itself. Both stdout and stderr from the executed command
# are captured and reported; an exception during execution is caught and
# reported as `error` rather than making the whole tool call fail opaquely
# (mirrors a real REPL: a failing command is a normal, informative result).
_RUN_PYTHON_REPL_SCRIPT = """
import contextlib
import io

_stdout_buffer = io.StringIO()
_stderr_buffer = io.StringIO()
_exec_globals = {"__name__": "__main__"}
_error = None
try:
    with contextlib.redirect_stdout(_stdout_buffer), contextlib.redirect_stderr(_stderr_buffer):
        exec(compile(_args["command"], "<run_python_repl>", "exec"), _exec_globals)
except Exception as exc:  # noqa: BLE001 -- REPL semantics: report the error, don't crash the wrapper
    _error = type(exc).__name__ + ": " + str(exc)

print(_json.dumps({
    "stdout": _stdout_buffer.getvalue(),
    "stderr": _stderr_buffer.getvalue(),
    "error": _error,
}))
"""


def run_python_repl(arguments: dict, driver) -> dict:
    """Executes literal Python `command` text inside the bwrap sandbox via
    `run_in_sandbox` (the same underlying mechanism `SandboxNodeExecutor`
    uses for `language == "python"` DAG nodes -- `driver.execute_python_script`
    -- not a new execution path), returning captured stdout/stderr and any
    exception raised while running it. `command` is passed as sandboxed JSON
    *data*, never interpolated into the executed script's source text."""
    validated = RunPythonReplArgs.model_validate(arguments or {})
    return run_in_sandbox(
        driver, script_body=_RUN_PYTHON_REPL_SCRIPT, args={"command": validated.command}
    )


# ---------------------------------------------------------------------------
# read_function_source_code
# ---------------------------------------------------------------------------

# Security allowlist (see module docstring): only these two package prefixes
# may ever be reflected into by this tool -- the action-tool modules
# (`infrastructure/tools/*.py`, this file's own siblings) and the DB/bio
# adapter modules (`infrastructure/mcp/*.py`, e.g. `bio_direct_adapters.py`).
# Anything else (domain services, security/auth code, credential helpers,
# persistence models, ...) is categorically out of reach through this tool.
_ALLOWED_MODULE_PREFIXES: tuple = (
    "src.infrastructure.tools.",
    "src.infrastructure.mcp.",
)


class FunctionSourceAccessError(ValueError):
    """Raised when `read_function_source_code` is asked to reflect into a
    module outside its allowlist, or the requested name can't be resolved to
    something with retrievable source. A `ValueError` subclass so it is
    handled by the same "bad tool input" path as Pydantic's own
    `ValidationError` (see `presentation/routes/mcp.py`), never surfaced as
    an unhandled 500."""


class ReadFunctionSourceCodeArgs(BaseModel):
    """Args for `read_function_source_code`."""

    function_name: str = Field(..., min_length=1)

    @field_validator("function_name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("function_name must be a non-empty string")
        return value


def _is_allowlisted_module(module_name: str) -> bool:
    """True iff `module_name` is, or is nested under, one of the
    allowlisted package prefixes above."""
    dotted = module_name + "."
    return any(dotted.startswith(prefix) for prefix in _ALLOWED_MODULE_PREFIXES)


def read_function_source_code(arguments: dict) -> dict:
    """`inspect.getsource` for a fully-qualified dotted name (e.g.
    `src.infrastructure.tools.immunology.isolate_purify_immune_cells`), hard
    -allowlisted (see module docstring) to modules under
    `src.infrastructure.tools.*` / `src.infrastructure.mcp.*`. Runs
    in-process -- there is nothing to execute, only already-loaded backend
    source to read -- so this tool takes no `driver` and is registered
    unbound (see `register_support_tools`)."""
    validated = ReadFunctionSourceCodeArgs.model_validate(arguments or {})
    function_name = validated.function_name

    if "." not in function_name:
        raise FunctionSourceAccessError(
            f"function_name must be a fully-qualified 'module.attribute' dotted name "
            f"(got {function_name!r})."
        )

    module_name, _, attr_path = function_name.rpartition(".")
    if not _is_allowlisted_module(module_name):
        raise FunctionSourceAccessError(
            f"Refusing to read source for {function_name!r}: module {module_name!r} is "
            "outside the allowlisted src.infrastructure.tools.* / src.infrastructure.mcp.* "
            "packages. This tool must never reflect into arbitrary application internals "
            "(e.g. DB credential helpers, JWT signing code)."
        )

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise FunctionSourceAccessError(
            f"Could not import module {module_name!r}: {exc}"
        ) from exc

    obj: Any = module
    for part in attr_path.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError as exc:
            raise FunctionSourceAccessError(
                f"{function_name!r} does not resolve to an attribute of module "
                f"{module_name!r}: {exc}"
            ) from exc

    # Defense in depth: `module_name` only proves the LOOKUP path was
    # allowlisted -- `obj` itself might be a name imported into that module
    # from somewhere else entirely (e.g. a helper imported at the top of an
    # `infrastructure/tools/*.py` file but actually defined in
    # `src.domain.services.*`). Re-check the resolved object's OWN
    # `__module__` before ever returning its source.
    defining_module = getattr(obj, "__module__", None)
    if not isinstance(defining_module, str) or not _is_allowlisted_module(defining_module):
        raise FunctionSourceAccessError(
            f"Refusing to read source for {function_name!r}: it resolves to something "
            f"actually defined in module {defining_module!r}, which is outside the "
            "allowlisted src.infrastructure.tools.* / src.infrastructure.mcp.* packages."
        )

    try:
        source_code = inspect.getsource(obj)
    except (OSError, TypeError) as exc:
        raise FunctionSourceAccessError(
            f"Could not retrieve source for {function_name!r}: {exc}"
        ) from exc

    return {
        "function_name": function_name,
        "module": module_name,
        "source_code": source_code,
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_support_tools(registry, driver) -> List[str]:
    """Registers both Support-tools handlers into `registry`.

    `run_python_repl` is bound to `driver`'s sandbox (`functools.partial`,
    same convention every other Fase 5 category uses). `read_function_source_code`
    takes no `driver` at all -- it never touches the sandbox -- so it is
    registered directly, unbound. Returns the registered tool names."""
    registry.register_server("run_python_repl", functools.partial(run_python_repl, driver=driver))
    registry.register_server("read_function_source_code", read_function_source_code)
    return ["run_python_repl", "read_function_source_code"]

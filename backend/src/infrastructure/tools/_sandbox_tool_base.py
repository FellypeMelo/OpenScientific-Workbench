"""Shared execution helper for sandboxed action-tool MCP handlers (Fase 5).

Design (see the plan's "Decisoes de arquitetura" item 3): every action tool,
regardless of tier (A/B/C/D, see `action_tool_catalog.md`), executes inside
the SAME `BubblewrapSandboxDriver` jail that DAG-node code execution uses --
never in-process in the trusted backend. This is deliberate defense in depth:
even a "just curve-fits with scipy" Tier B tool takes LLM-influenced
arguments, and the sandbox toolkit (biopython/rdkit/samtools/...) lives in a
conda env this process's own venv never imports, so there is no in-process
fast path to accidentally reach for instead.

Each handler in a sibling module (`cloning.py`, etc.) is thin:
1. Validate arguments with a Pydantic model (raises `ValueError`/pydantic's
   own `ValidationError` on bad input -- caught by the MCP route the same way
   `bio_direct_adapters.py`'s adapters' `ValueError`s are, see
   `presentation/routes/mcp.py`).
2. Tier D tools skip the sandbox entirely and raise `NotSupportedError`
   directly (see that class's docstring) -- there is nothing to execute.
3. Tier A/B/C tools build a short, hand-written `script_body` (real
   biopython/scipy/rdkit/... calls -- NOT a template that stringifies
   arbitrary code) and call `run_in_sandbox(driver, script_body=..., args=...)`.

TESTING REALITY (read this before writing a test for a new tool): the
`script_body` strings import packages (scipy, biopython, rdkit, ...) that
only exist in the sandbox toolkit's OWN conda env (`backend/sandbox/
environment.yml`), never in this repo's own `backend/.venv` that `pytest`
runs under. That means this repo's fast unit test suite CANNOT execute a
tool's real scientific logic and assert on a recovered numeric result --
there is no scipy/rdkit to import here to even write such an assertion
against, by design (see this module's docstring above). Unit tests here
therefore verify the WIRING and VALIDATION layer only: Pydantic argument
validation, correct `args` JSON round-tripping, correct tool registration,
and Tier D's explicit `NotSupportedError` -- using `FakeSandboxDriver` below,
which never actually interprets `script_body`, just records it and returns a
canned stdout. Real numerical/scientific correctness of a `script_body` can
only be verified by actually building the sandbox-toolkit image and running
the tool for real (see `backend/docs/tools/UNSUPPORTED.md`'s sibling
verification notes and the plan's "Verificacao" section) -- this mirrors how
`test_bubblewrap_driver.py` itself only ever mocks `subprocess.run` and the
REAL bwrap isolation proof lives in a separate, environment-gated integration
test (`tests/integration/test_bubblewrap_sandbox_escape.py`).
"""
import json
import os
import uuid
from typing import Any, Dict, List, Tuple


class SandboxToolError(RuntimeError):
    """Raised when a sandboxed action-tool script exits non-zero, or prints
    something other than exactly one trailing line of JSON to stdout."""


class NotSupportedError(NotImplementedError):
    """Raised directly (never via the sandbox) by a Tier D tool -- one that
    needs a proprietary/huge pretrained checkpoint (TxGNN, UCE, DiffDock,
    cryoSPARC) or a GPU cluster this single-local-server deployment does not
    have. Message MUST name exactly what's missing and point at
    `backend/docs/tools/UNSUPPORTED.md`. Returning a fabricated result from
    an untrained/absent model would be actively dangerous in a biomedical
    tool -- see the plan's "Honestidade de escopo" section -- so this is
    always a hard failure, never a mocked success.
    """


def run_in_sandbox(driver, *, script_body: str, args: Dict[str, Any]) -> Any:
    """Runs a real, hand-written ``script_body`` inside ``driver``'s bwrap
    sandbox, with ``args`` made available to it as the parsed dict ``_args``
    (loaded from a JSON file written into the sandbox workspace -- arguments
    are DATA, written to a file and read back, never interpolated into the
    script source as a literal, so a value can never be mistaken for code).

    ``script_body`` MUST end by printing exactly one line of JSON to stdout
    (the tool's result) and MUST NOT itself define ``_args`` or read
    ``sys.argv`` -- both are handled by this wrapper. Raises
    ``SandboxToolError`` on a non-zero exit or unparseable stdout.
    """
    workspace_root = getattr(driver, "workspace_root", "osw_workspace")
    os.makedirs(workspace_root, exist_ok=True)
    call_id = uuid.uuid4().hex[:12]
    args_filename = f"_tool_args_{call_id}.json"
    script_filename = f"_tool_script_{call_id}.py"

    with open(os.path.join(workspace_root, args_filename), "w", encoding="utf-8") as fh:
        json.dump(args, fh)

    full_script = (
        "import json as _json\n"
        f"with open('/workspace/{args_filename}', encoding='utf-8') as _fh:\n"
        "    _args = _json.load(_fh)\n"
        "\n"
        f"{script_body}\n"
    )
    with open(os.path.join(workspace_root, script_filename), "w", encoding="utf-8") as fh:
        fh.write(full_script)

    stdout, exit_code = driver.execute_python_script(script_filename)
    if exit_code != 0:
        raise SandboxToolError(f"Sandboxed tool script failed (exit {exit_code}): {stdout}")

    lines = [line for line in stdout.strip().splitlines() if line.strip()]
    if not lines:
        raise SandboxToolError(f"Sandboxed tool script produced no output: {stdout!r}")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise SandboxToolError(
            f"Sandboxed tool script's last line was not valid JSON: {lines[-1]!r}"
        ) from exc


class FakeSandboxDriver:
    """Test double for `run_in_sandbox` -- records every
    `(script_body, args)` pair it receives (via `execute_python_script`,
    called the same way the real `BubblewrapSandboxDriver` is) and returns a
    canned `(stdout, exit_code)`, WITHOUT interpreting `script_body` at all.
    See this module's "TESTING REALITY" docstring section for why that's the
    correct boundary for this repo's unit test suite.
    """

    def __init__(self, workspace_root: str = "workspace_fake_tools"):
        # NOTE: the default matches the `workspace_*/` glob already in
        # `.gitignore` (see repo root) -- if you override this in a test,
        # either pass pytest's `tmp_path` fixture or pick a name matching
        # that same glob, so a test run never leaves scratch files for git
        # to notice.
        self.workspace_root = workspace_root
        self.calls: List[Tuple[str, str]] = []  # (script_source, relative_path)
        self.stdout = '{"ok": true}'
        self.exit_code = 0

    def execute_python_script(self, relative_script_path: str) -> Tuple[str, int]:
        path = os.path.join(self.workspace_root, relative_script_path)
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        self.calls.append((source, relative_script_path))
        return self.stdout, self.exit_code

    def last_args(self) -> Dict[str, Any]:
        """Convenience for tests: parses the JSON args file written for the
        most recent `run_in_sandbox` call."""
        assert self.calls, "no run_in_sandbox call recorded yet"
        # `run_in_sandbox` names the script/args files `_tool_script_<id>.py`
        # / `_tool_args_<id>.json` from the SAME `call_id` -- derive the args
        # filename from the script filename directly rather than scraping it
        # back out of the script source text.
        _, script_filename = self.calls[-1]
        args_filename = script_filename.replace("_tool_script_", "_tool_args_").replace(
            ".py", ".json"
        )
        with open(os.path.join(self.workspace_root, args_filename), encoding="utf-8") as fh:
            return json.load(fh)

"""Real bubblewrap sandbox-escape smoke test (RF-005/RNF-001/RNF-002).

`test_security_sandbox_escape.py` only exercises the pure-Python
path-traversal GUARD (no real isolation required to pass). This test is
different: it requires an ACTUAL, working `bwrap` binary and asserts real
kernel-level containment -- a payload that tries to read a real host file
outside the sandboxed workspace, or reach the network, must actually be
denied by bwrap's namespaces, not merely rejected by a string check.

Skipped everywhere `bwrap` is not on PATH -- this project's Windows dev
sandbox, and the main `backend-test` CI job (which does not install it). See
`.github/workflows/ci.yml`'s dedicated `sandbox-escape-smoke` job, which DOES
install bubblewrap on `ubuntu-latest` and is the only place this test suite
actually executes for real.

UNVERIFIED IN THIS WINDOWS DEV SANDBOX: bwrap cannot run here at all, so
these assertions have not been observed to pass against a real bwrap
process. A human must confirm the `sandbox-escape-smoke` CI job goes green on
an actual GitHub Actions `ubuntu-latest` runner (and that unprivileged user
namespaces aren't blocked there -- see that job's comments) before relying on
this as a verified security boundary.
"""
import shutil

import pytest

from src.infrastructure.sandbox.bubblewrap_driver import BubblewrapSandboxDriver

pytestmark = pytest.mark.skipif(
    shutil.which("bwrap") is None,
    reason=(
        "bubblewrap (bwrap) is not installed on this host; see "
        ".github/workflows/ci.yml's sandbox-escape-smoke job, the only place "
        "this suite runs for real."
    ),
)


def test_bwrap_blocks_reading_a_real_host_secret_file(tmp_path):
    secret = tmp_path.parent / f"osw_sandbox_escape_secret_{tmp_path.name}.txt"
    secret.write_text("TOP_SECRET_HOST_DATA")
    try:
        driver = BubblewrapSandboxDriver(workspace_root=str(tmp_path), runtime="bubblewrap")
        stdout, _exit_code = driver.execute_bash(f"cat {secret} 2>&1 || echo BLOCKED")
        # The secret file lives outside the ro-bound system dirs / bound
        # workspace, so the sandboxed process must not be able to read it.
        assert "TOP_SECRET_HOST_DATA" not in stdout
    finally:
        secret.unlink(missing_ok=True)


def test_bwrap_blocks_network_access_by_default(tmp_path):
    driver = BubblewrapSandboxDriver(workspace_root=str(tmp_path), runtime="bubblewrap")
    stdout, _exit_code = driver.execute_bash(
        "curl -s -m 3 http://example.com >/dev/null 2>&1 && echo REACHED || echo BLOCKED"
    )
    assert "REACHED" not in stdout


def test_bwrap_still_enforces_the_path_traversal_guard(tmp_path):
    driver = BubblewrapSandboxDriver(workspace_root=str(tmp_path), runtime="bubblewrap")
    with pytest.raises(PermissionError, match="Path traversal or absolute access blocked"):
        driver.execute_python_script("../../etc/passwd")


def test_bwrap_actually_executes_a_real_python_script(tmp_path):
    """Positive control: real sandboxed execution must still WORK for a
    legitimate script inside the bound workspace, not just block escapes."""
    (tmp_path / "add.py").write_text("print(2 + 2)")
    driver = BubblewrapSandboxDriver(workspace_root=str(tmp_path), runtime="bubblewrap")
    stdout, exit_code = driver.execute_python_script("add.py")
    assert exit_code == 0
    assert "4" in stdout

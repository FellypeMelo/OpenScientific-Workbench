"""RF-005: the sandbox must run bash and R, not just (stubbed) Python.

Subprocess is patched so the CI-branch behaviour is asserted deterministically
without requiring bash/Rscript to be installed in the test environment.

`GVisorSandboxDriver`'s public `execute_*` methods return `(stdout, exit_code)`
tuples (RF-005 gap-closure phase: the sandbox subsystem moved to
`BubblewrapSandboxDriver` as the real default, and this dormant driver's
public wrapper was fixed to stop collapsing `_execute`'s already-3-tuple
result down to just the stdout string -- see `gvisor_driver.py`), not a bare
string -- these assertions unpack that tuple.
"""
import types

import src.infrastructure.sandbox.gvisor_driver as gv
from src.infrastructure.sandbox.gvisor_driver import GVisorSandboxDriver


def test_execute_bash_mock_when_not_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    out, exit_code = GVisorSandboxDriver().execute_bash("echo hi")
    assert "Mock execution output" in out
    assert exit_code == 0


def test_execute_r_script_mock_when_not_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    out, exit_code = GVisorSandboxDriver().execute_r_script("print('hi')")
    assert "Mock execution output" in out
    assert exit_code == 0


def test_execute_bash_invokes_bash_under_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return types.SimpleNamespace(stdout="hi\n", stderr="", returncode=0)

    monkeypatch.setattr(gv.subprocess, "run", fake_run)

    out, exit_code = GVisorSandboxDriver().execute_bash("echo hi")

    assert "hi" in out
    assert exit_code == 0
    assert captured["argv"][:2] == ["bash", "-c"]
    assert captured["argv"][2] == "echo hi"


def test_execute_r_script_invokes_rscript_under_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return types.SimpleNamespace(stdout='[1] "hi"\n', stderr="", returncode=0)

    monkeypatch.setattr(gv.subprocess, "run", fake_run)

    GVisorSandboxDriver().execute_r_script("print('hi')")

    assert captured["argv"][:2] == ["Rscript", "-e"]


def test_execute_bash_returns_error_on_failure_under_ci(monkeypatch):
    import subprocess

    monkeypatch.setenv("CI", "true")

    def fake_run(argv, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=argv, stderr="boom")

    monkeypatch.setattr(gv.subprocess, "run", fake_run)

    out, exit_code = GVisorSandboxDriver().execute_bash("false")
    assert "Execution error" in out and "boom" in out
    assert exit_code == 1

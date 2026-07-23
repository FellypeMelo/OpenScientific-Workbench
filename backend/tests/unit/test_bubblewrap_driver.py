"""Unit tests for `BubblewrapSandboxDriver` (RF-005/RNF-001/RNF-002).

`subprocess.run`/`shutil.which` are the actual transport boundary here (real
process execution / PATH lookup), so those are what get mocked -- everything
else (runtime validation, argv construction, path-traversal guard, resource
limit wiring, telemetry) is real driver logic under test, mirroring the style
of `test_sandbox_multilang.py`/`test_sandbox_telemetry.py` for the (dormant)
gVisor driver.
"""
import subprocess
import types

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

import src.infrastructure.sandbox.bubblewrap_driver as bw
from src.infrastructure.sandbox.bubblewrap_driver import (
    BubblewrapSandboxDriver,
    SandboxUnavailableError,
)


def _tracer_with_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


# --- construction / fail-loud behaviour ------------------------------------


def test_mock_runtime_never_touches_bwrap_lookup(monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: (_ for _ in ()).throw(AssertionError("should not be called")))
    driver = BubblewrapSandboxDriver(runtime="mock")
    assert driver.runtime == "mock"


def test_subprocess_runtime_never_touches_bwrap_lookup(monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: (_ for _ in ()).throw(AssertionError("should not be called")))
    driver = BubblewrapSandboxDriver(runtime="subprocess")
    assert driver.runtime == "subprocess"


def test_bubblewrap_runtime_missing_binary_raises_loud(monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: None)
    with pytest.raises(SandboxUnavailableError, match="bwrap"):
        BubblewrapSandboxDriver(runtime="bubblewrap")


def test_bubblewrap_runtime_non_functional_binary_raises_loud(monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: "/usr/bin/bwrap")

    def fake_run(argv, **kwargs):
        raise OSError("Operation not permitted")

    monkeypatch.setattr(bw.subprocess, "run", fake_run)

    with pytest.raises(SandboxUnavailableError, match="non-functional|failed to run"):
        BubblewrapSandboxDriver(runtime="bubblewrap")


def test_bubblewrap_runtime_probe_nonzero_exit_raises_loud(monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(
        bw.subprocess,
        "run",
        lambda argv, **kwargs: types.SimpleNamespace(returncode=1, stderr=b"denied"),
    )

    with pytest.raises(SandboxUnavailableError):
        BubblewrapSandboxDriver(runtime="bubblewrap")


def test_bubblewrap_runtime_functional_binary_constructs_cleanly(monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(
        bw.subprocess,
        "run",
        lambda argv, **kwargs: types.SimpleNamespace(returncode=0, stderr=b""),
    )
    driver = BubblewrapSandboxDriver(runtime="bubblewrap")
    assert driver.runtime == "bubblewrap"


def test_unknown_runtime_rejected():
    with pytest.raises(ValueError, match="Unknown SANDBOX_RUNTIME"):
        BubblewrapSandboxDriver(runtime="docker")


def test_defaults_to_settings_sandbox_runtime(monkeypatch):
    monkeypatch.setattr(bw.settings, "SANDBOX_RUNTIME", "mock")
    driver = BubblewrapSandboxDriver()
    assert driver.runtime == "mock"


# --- path traversal ----------------------------------------------------


def test_execute_python_script_blocks_path_traversal():
    driver = BubblewrapSandboxDriver(runtime="mock")
    with pytest.raises(PermissionError, match="Path traversal or absolute access blocked"):
        driver.execute_python_script("../../etc/passwd")


def test_execute_python_script_blocks_absolute_path():
    driver = BubblewrapSandboxDriver(runtime="mock")
    with pytest.raises(PermissionError, match="Path traversal or absolute access blocked"):
        driver.execute_python_script("/etc/shadow")


def test_execute_python_script_blocks_windows_drive_letter():
    driver = BubblewrapSandboxDriver(runtime="mock")
    with pytest.raises(PermissionError, match="Path traversal or absolute access blocked"):
        driver.execute_python_script("C:\\Windows\\System32\\config\\SAM")


# --- mock runtime --------------------------------------------------------


def test_mock_runtime_returns_deterministic_result_without_subprocess(monkeypatch):
    def fail(*a, **k):  # pragma: no cover - only invoked if the bug regresses
        raise AssertionError("subprocess.run should not be called in mock mode")

    monkeypatch.setattr(bw.subprocess, "run", fail)

    driver = BubblewrapSandboxDriver(runtime="mock")
    out, exit_code = driver.execute_bash("echo hi")
    assert "Mock execution output" in out
    assert exit_code == 0


# --- subprocess runtime (no bwrap wrapping) -------------------------------


def test_subprocess_runtime_runs_bare_argv(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return types.SimpleNamespace(stdout="hi\n", stderr="", returncode=0)

    monkeypatch.setattr(bw.subprocess, "run", fake_run)

    driver = BubblewrapSandboxDriver(runtime="subprocess")
    out, exit_code = driver.execute_bash("echo hi")

    assert out == "hi\n"
    assert exit_code == 0
    assert captured["argv"] == ["bash", "-c", "echo hi"]


def test_subprocess_runtime_execute_r_script(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return types.SimpleNamespace(stdout='[1] "hi"\n', stderr="", returncode=0)

    monkeypatch.setattr(bw.subprocess, "run", fake_run)

    driver = BubblewrapSandboxDriver(runtime="subprocess")
    driver.execute_r_script("print('hi')")

    assert captured["argv"] == ["Rscript", "-e", "print('hi')"]


def test_subprocess_runtime_nonzero_exit_reports_stderr(monkeypatch):
    monkeypatch.setattr(
        bw.subprocess,
        "run",
        lambda argv, **kwargs: types.SimpleNamespace(stdout="", stderr="boom", returncode=1),
    )

    driver = BubblewrapSandboxDriver(runtime="subprocess")
    out, exit_code = driver.execute_bash("false")

    assert exit_code == 1
    assert "Execution error" in out and "boom" in out


def test_subprocess_runtime_timeout_reports_error(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 30))

    monkeypatch.setattr(bw.subprocess, "run", fake_run)

    driver = BubblewrapSandboxDriver(runtime="subprocess", timeout_seconds=5)
    out, exit_code = driver.execute_bash("sleep 100")

    assert exit_code == -1
    assert "timed out" in out


def test_subprocess_runtime_execute_python_script_uses_host_path(tmp_path, monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return types.SimpleNamespace(stdout="42\n", stderr="", returncode=0)

    monkeypatch.setattr(bw.subprocess, "run", fake_run)

    driver = BubblewrapSandboxDriver(runtime="subprocess", workspace_root=str(tmp_path))
    out, exit_code = driver.execute_python_script("script.py")

    assert exit_code == 0
    assert captured["argv"][0] == "python3"
    assert captured["argv"][1].endswith("script.py")
    assert str(tmp_path) in captured["argv"][1]


# --- bubblewrap runtime: argv construction --------------------------------


def test_bubblewrap_runtime_wraps_argv_with_isolation_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: "/usr/bin/bwrap")

    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["/usr/bin/bwrap", "--version"]:
            return types.SimpleNamespace(returncode=0, stderr=b"")
        return types.SimpleNamespace(stdout="hi\n", stderr="", returncode=0)

    monkeypatch.setattr(bw.subprocess, "run", fake_run)

    driver = BubblewrapSandboxDriver(runtime="bubblewrap", workspace_root=str(tmp_path))
    out, exit_code = driver.execute_bash("echo hi")

    assert out == "hi\n"
    assert exit_code == 0

    real_call = calls[-1]
    assert real_call[0] == "bwrap"
    assert "--unshare-net" in real_call
    assert "--die-with-parent" in real_call
    assert "--new-session" in real_call
    assert "--unshare-pid" in real_call
    # The actual guest command is appended, unmodified, after the `--` sentinel.
    assert real_call[-3:] == ["bash", "-c", "echo hi"]
    assert "--" in real_call


def test_bubblewrap_runtime_allow_network_omits_unshare_net(tmp_path, monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: "/usr/bin/bwrap")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["/usr/bin/bwrap", "--version"]:
            return types.SimpleNamespace(returncode=0, stderr=b"")
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(bw.subprocess, "run", fake_run)

    driver = BubblewrapSandboxDriver(
        runtime="bubblewrap", workspace_root=str(tmp_path), allow_network=True
    )
    driver.execute_bash("echo hi")

    assert "--unshare-net" not in calls[-1]


def test_bubblewrap_runtime_python_script_uses_sandboxed_path(tmp_path, monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: "/usr/bin/bwrap")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["/usr/bin/bwrap", "--version"]:
            return types.SimpleNamespace(returncode=0, stderr=b"")
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(bw.subprocess, "run", fake_run)

    driver = BubblewrapSandboxDriver(runtime="bubblewrap", workspace_root=str(tmp_path))
    driver.execute_python_script("nested/script.py")

    assert calls[-1][-2:] == ["python3", "/workspace/nested/script.py"]


# --- telemetry (RNF-004 parity with GVisorSandboxDriver) -------------------


def test_sandbox_execution_emits_span_with_stdout_and_exit_code():
    tracer, exporter = _tracer_with_exporter()
    driver = BubblewrapSandboxDriver(runtime="mock", tracer=tracer)

    driver.execute_bash("echo hi")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "sandbox.execute"
    assert spans[0].attributes["sandbox.exit_code"] == 0
    assert "sandbox.stdout" in spans[0].attributes
    assert spans[0].status.status_code != StatusCode.ERROR


def test_sandbox_failure_sets_error_status(monkeypatch):
    monkeypatch.setattr(
        bw.subprocess,
        "run",
        lambda argv, **kwargs: types.SimpleNamespace(stdout="", stderr="boom", returncode=2),
    )
    tracer, exporter = _tracer_with_exporter()
    driver = BubblewrapSandboxDriver(runtime="subprocess", tracer=tracer)

    driver.execute_bash("false")

    spans = exporter.get_finished_spans()
    assert spans[0].status.status_code == StatusCode.ERROR
    assert spans[0].attributes["sandbox.exit_code"] == 2


def test_no_span_emitted_when_no_tracer():
    _, exporter = _tracer_with_exporter()
    BubblewrapSandboxDriver(runtime="mock").execute_bash("echo hi")
    assert exporter.get_finished_spans() == ()


# --- resource limits (RNF-001) ---------------------------------------------


def test_preexec_fn_applies_cpu_and_memory_limits(monkeypatch):
    calls = []

    class _FakeResource:
        RLIMIT_CPU = "CPU"
        RLIMIT_AS = "AS"

        @staticmethod
        def setrlimit(which, limits):
            calls.append((which, limits))

    monkeypatch.setattr(bw, "resource", _FakeResource)

    driver = BubblewrapSandboxDriver(runtime="mock", cpu_seconds=7, memory_bytes=123)
    preexec = driver._preexec_fn()
    assert preexec is not None
    preexec()

    assert ("CPU", (7, 7)) in calls
    assert ("AS", (123, 123)) in calls


def test_preexec_fn_none_when_resource_module_unavailable(monkeypatch):
    monkeypatch.setattr(bw, "resource", None)
    driver = BubblewrapSandboxDriver(runtime="mock")
    assert driver._preexec_fn() is None


# --- sandbox toolkit / data lake binds (Fase 1/3 wiring) -------------------


def test_sandbox_toolkit_bound_and_put_first_on_path_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(bw.subprocess, "run", lambda argv, **kwargs: types.SimpleNamespace(returncode=0, stderr=b""))
    monkeypatch.setattr(bw.os.path, "isdir", lambda p: p == bw.SANDBOX_TOOLKIT_DIR or p == str(tmp_path))

    driver = BubblewrapSandboxDriver(runtime="bubblewrap", workspace_root=str(tmp_path))
    argv = driver._bwrap_argv()

    assert "--ro-bind" in argv
    idx = argv.index(bw.SANDBOX_TOOLKIT_DIR)
    assert argv[idx - 1] == "--ro-bind"
    assert argv[idx + 1] == bw.SANDBOX_TOOLKIT_DIR
    path_idx = argv.index("--setenv")
    assert argv[path_idx + 1] == "PATH"
    assert argv[path_idx + 2].startswith(f"{bw.SANDBOX_TOOLKIT_DIR}/bin:")


def test_sandbox_toolkit_absent_falls_back_to_system_path(tmp_path, monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(bw.subprocess, "run", lambda argv, **kwargs: types.SimpleNamespace(returncode=0, stderr=b""))
    monkeypatch.setattr(bw.os.path, "isdir", lambda p: p == str(tmp_path))

    driver = BubblewrapSandboxDriver(runtime="bubblewrap", workspace_root=str(tmp_path))
    argv = driver._bwrap_argv()

    assert bw.SANDBOX_TOOLKIT_DIR not in argv
    path_idx = argv.index("--setenv")
    assert argv[path_idx + 2] == "/usr/bin:/bin"


def test_data_lake_bound_read_only_when_configured_and_present(tmp_path, monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(bw.subprocess, "run", lambda argv, **kwargs: types.SimpleNamespace(returncode=0, stderr=b""))
    data_lake = str(tmp_path / "datalake")
    monkeypatch.setattr(bw.os.path, "isdir", lambda p: p in (str(tmp_path), data_lake))

    driver = BubblewrapSandboxDriver(
        runtime="bubblewrap", workspace_root=str(tmp_path), data_lake_root=data_lake,
    )
    argv = driver._bwrap_argv()

    idx = argv.index(data_lake)
    assert argv[idx - 1] == "--ro-bind"
    assert argv[idx + 1] == "/datalake"


def test_data_lake_not_bound_when_directory_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(bw.subprocess, "run", lambda argv, **kwargs: types.SimpleNamespace(returncode=0, stderr=b""))
    monkeypatch.setattr(bw.os.path, "isdir", lambda p: p == str(tmp_path))

    driver = BubblewrapSandboxDriver(
        runtime="bubblewrap", workspace_root=str(tmp_path), data_lake_root="/nonexistent-datalake",
    )
    argv = driver._bwrap_argv()

    assert "/datalake" not in argv


def test_workspace_bound_read_write_so_action_tools_can_write_output(tmp_path, monkeypatch):
    """Regression test: the workspace mount MUST be writable (`--bind`, not
    `--ro-bind`) -- every sandboxed action tool (infrastructure/tools/*.py)
    writes its declared output file/dir under /workspace/<output_dir> (see
    run_in_sandbox), which would raise "Read-only file system" on every
    single call if this mount were read-only, as it originally was before
    those tools existed."""
    monkeypatch.setattr(bw.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(bw.subprocess, "run", lambda argv, **kwargs: types.SimpleNamespace(returncode=0, stderr=b""))
    monkeypatch.setattr(bw.os.path, "isdir", lambda p: p == str(tmp_path))

    driver = BubblewrapSandboxDriver(runtime="bubblewrap", workspace_root=str(tmp_path))
    argv = driver._bwrap_argv()

    workspace_abs = bw.os.path.realpath(str(tmp_path))
    idx = argv.index(workspace_abs)
    assert argv[idx - 1] == "--bind"
    assert argv[idx + 1] == "/workspace"


def test_data_lake_root_defaults_from_settings(monkeypatch):
    monkeypatch.setattr(bw.settings, "DATA_LAKE_ROOT", "/configured-datalake")
    driver = BubblewrapSandboxDriver(runtime="mock")
    assert driver.data_lake_root == "/configured-datalake"

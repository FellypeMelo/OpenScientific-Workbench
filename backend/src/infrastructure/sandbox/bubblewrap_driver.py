"""Bubblewrap (bwrap) sandbox driver -- the REAL sandbox isolation mechanism
for this project (RF-005/RNF-001/RNF-002), replacing gVisor per the locked
architecture decision (single local Linux server, Docker Compose, no Docker
socket exposure -- `bwrap` needs no privileged container runtime at all).

Isolation profile (see ``_bwrap_argv``):
- read-only bind of the interpreter/system dirs the language runtime needs
  (``/usr``, ``/bin``, ``/lib``, ``/lib64``, ``/etc``) so the guest can run
  ``bash`` at all, but cannot modify the host filesystem outside its own
  workspace;
- read-only bind of ``/opt/sandbox-env`` (the micromamba environment built
  from ``backend/sandbox/environment.yml`` -- see ``backend/Dockerfile``'s
  ``sandbox-toolkit`` stage), put FIRST on the jailed ``PATH`` via
  ``--setenv``. This is what actually provides ``python3``/``Rscript`` plus
  every bioinformatics CLI/library inside the jail -- neither the app's own
  ``/opt/venv`` nor the base image's ``/usr/local`` Python are bound in, so
  without this bind ``execute_python_script``/``execute_r_script`` would fail
  with "command not found" for every guest process;
- read-only bind of ``settings.DATA_LAKE_ROOT`` at ``/datalake``, when that
  directory exists on the host, for tools that read bundled reference
  datasets (see ``backend/data_lake/MANIFEST.md``);
- the caller's workspace directory is bound READ-ONLY at ``/workspace``
  inside the sandbox (this driver only ever needs to *read* an
  already-materialized script/data from it -- see ``execute_python_script``);
- an isolated ``tmpfs`` at ``/tmp`` for scratch space the guest process can
  actually write to;
- network isolation by default (``--unshare-net``) -- untrusted code should
  not be able to exfiltrate data or reach internal services;
- ``--die-with-parent`` so an orphaned bwrap process cannot outlive this
  Python process;
- ``--new-session`` to detach from the controlling terminal (defense against
  TIOCSTI-style terminal injection);
- CPU-time and address-space ``RLIMIT_*`` caps applied via a ``preexec_fn``
  (the stdlib ``resource`` module) so a runaway/malicious script cannot
  exhaust host resources. ``resource`` is POSIX-only; on a non-POSIX host
  (e.g. this project's Windows dev sandbox) the limits are skipped rather
  than raising an ImportError at module load time -- this only ever matters
  in practice on the real Linux deployment target, where ``resource`` is
  always available.

Security posture (see repo-wide ground rules): sandboxed code execution is a
security boundary, not a nice-to-have. Unlike every other real-vs-mock
adapter in this codebase (Neo4j/Vault/Slurm/etc, which quietly fall back to a
mock when their config is simply absent), this driver FAILS LOUD --
``SandboxUnavailableError`` -- when ``SANDBOX_RUNTIME=bubblewrap`` (the
default) is configured but the ``bwrap`` binary is missing or non-functional
on this host, instead of silently downgrading to unsandboxed execution. An
operator must either install bubblewrap or explicitly opt into
``SANDBOX_RUNTIME=subprocess`` (dev/test only, NOT isolated) or
``SANDBOX_RUNTIME=mock`` (no real execution at all).
"""
import os
import shutil
import subprocess
from typing import List, Optional, Tuple

from opentelemetry.trace import Status, StatusCode

from src.domain.services.path_guard import PathTraversalError, ensure_safe_relative_path
from src.infrastructure.config import settings

try:  # POSIX-only stdlib module; absent on Windows.
    import resource
except ImportError:  # pragma: no cover - exercised on the Windows dev sandbox
    resource = None  # type: ignore[assignment]


class SandboxUnavailableError(RuntimeError):
    """Raised when ``SANDBOX_RUNTIME=bubblewrap`` is configured but ``bwrap``
    cannot actually provide isolation on this host (binary missing, or present
    but non-functional -- e.g. unprivileged user namespaces disabled).

    Deliberately loud: sandboxing is a security boundary, so this refuses to
    silently fall back to unsandboxed execution. Callers (see
    ``presentation/routes/tasks.py``) turn this into a clean 503, not a raw
    500 or -- far worse -- a silent bypass.
    """


_VALID_RUNTIMES = ("bubblewrap", "subprocess", "mock")

_DEFAULT_CPU_SECONDS = 30
_DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024  # 512 MiB
_DEFAULT_TIMEOUT_SECONDS = 30

# Host directories read-only bound into the sandbox so the guest's shell
# (bash) can resolve its own binaries/libs.
_RO_SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")

# The sandbox toolkit (biopython/scanpy/RDKit/samtools/R/... -- see
# `backend/sandbox/environment.yml`), built by `backend/Dockerfile`'s
# `sandbox-toolkit` stage. Bound read-only and put first on the jailed PATH
# (see `_bwrap_argv`) -- this, not `/usr`, is what provides `python3`/
# `Rscript` inside the jail.
SANDBOX_TOOLKIT_DIR = "/opt/sandbox-env"


class BubblewrapSandboxDriver:
    """Adapter running (simulated) research-agent code inside a locked-down
    ``bwrap`` sandbox. Public methods mirror ``GVisorSandboxDriver``'s
    interface -- ``execute_python_script``/``execute_bash``/``execute_r_script``
    -- each returning ``(stdout, exit_code)`` so a caller (``SandboxNodeExecutor``)
    has something to compute a >=0/<0 reward from.
    """

    def __init__(
        self,
        workspace_root: str = "osw_workspace",
        tracer=None,
        runtime: Optional[str] = None,
        allow_network: bool = False,
        cpu_seconds: int = _DEFAULT_CPU_SECONDS,
        memory_bytes: int = _DEFAULT_MEMORY_BYTES,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        data_lake_root: Optional[str] = None,
    ):
        self.workspace_root = workspace_root
        self.tracer = tracer
        self.allow_network = allow_network
        self.cpu_seconds = cpu_seconds
        self.memory_bytes = memory_bytes
        self.timeout_seconds = timeout_seconds
        # Bound read-only at /datalake when set AND present on the host (see
        # `backend/data_lake/MANIFEST.md`) -- defaults to
        # `settings.DATA_LAKE_ROOT`, which itself defaults to unset (no bind)
        # since the actual reference datasets are an operator-run download
        # step (`backend/scripts/fetch_data_lake.py`), never bundled.
        self.data_lake_root = data_lake_root if data_lake_root is not None else settings.DATA_LAKE_ROOT

        resolved = (runtime if runtime is not None else settings.SANDBOX_RUNTIME) or "bubblewrap"
        self.runtime = resolved.strip().lower()
        if self.runtime not in _VALID_RUNTIMES:
            raise ValueError(
                f"Unknown SANDBOX_RUNTIME {resolved!r}: expected one of {_VALID_RUNTIMES}."
            )

        if self.runtime == "bubblewrap":
            self._assert_bwrap_functional()

    @staticmethod
    def _assert_bwrap_functional() -> None:
        """Fail loud (``SandboxUnavailableError``) unless ``bwrap`` is both
        present on PATH AND actually runs (``bwrap --version``)."""
        bwrap_path = shutil.which("bwrap")
        if bwrap_path is None:
            raise SandboxUnavailableError(
                "SANDBOX_RUNTIME=bubblewrap is configured but the 'bwrap' "
                "binary was not found on PATH. Sandboxed code execution is a "
                "security boundary; refusing to silently fall back to "
                "unsandboxed execution. Install bubblewrap (e.g. `apt-get "
                "install bubblewrap` on Debian/Ubuntu) on this host, or "
                "explicitly set SANDBOX_RUNTIME=subprocess (dev/test only, "
                "NOT isolated) or SANDBOX_RUNTIME=mock (no real execution) if "
                "this host genuinely cannot run bwrap."
            )
        try:
            probe = subprocess.run(
                [bwrap_path, "--version"], capture_output=True, timeout=5
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SandboxUnavailableError(
                f"SANDBOX_RUNTIME=bubblewrap is configured and 'bwrap' is on "
                f"PATH ({bwrap_path}), but it failed to run: {exc}. This "
                "usually means unprivileged user namespaces are disabled on "
                "this host (a common kernel/AppArmor hardening default). "
                "Fix the host, or explicitly set SANDBOX_RUNTIME=subprocess "
                "or SANDBOX_RUNTIME=mock."
            ) from exc
        if probe.returncode != 0:
            raise SandboxUnavailableError(
                f"SANDBOX_RUNTIME=bubblewrap is configured and 'bwrap' is on "
                f"PATH ({bwrap_path}), but `bwrap --version` exited "
                f"{probe.returncode}: {probe.stderr!r}. Sandboxing is a "
                "security boundary; refusing to silently fall back to "
                "unsandboxed execution."
            )

    # -- public execution surface, mirrors GVisorSandboxDriver -------------

    def execute_python_script(self, relative_script_path: str) -> Tuple[str, int]:
        try:
            resolved_path = ensure_safe_relative_path(relative_script_path)
        except PathTraversalError as exc:
            raise PermissionError(
                "FATAL_SANDBOX_PATH_VIOLATION: Path traversal or absolute access blocked."
            ) from exc

        if self.runtime == "bubblewrap":
            target = f"/workspace/{resolved_path}"
        else:
            target = os.path.join(self.workspace_root, resolved_path)
        return self._run_or_mock(["python3", target])

    def execute_bash(self, command: str) -> Tuple[str, int]:
        """Runs a bash command in the sandbox (RF-005)."""
        return self._run_or_mock(["bash", "-c", command])

    def execute_r_script(self, code: str) -> Tuple[str, int]:
        """Runs an R snippet in the sandbox (RF-005)."""
        return self._run_or_mock(["Rscript", "-e", code])

    # -- internals -----------------------------------------------------------

    def _bwrap_argv(self) -> List[str]:
        """Builds the fixed bwrap isolation prefix (see module docstring)."""
        workspace_abs = os.path.realpath(self.workspace_root)
        os.makedirs(workspace_abs, exist_ok=True)

        argv: List[str] = ["bwrap"]
        for host_dir in _RO_SYSTEM_DIRS:
            if os.path.isdir(host_dir):
                argv += ["--ro-bind", host_dir, host_dir]

        # Sandbox toolkit (python3/Rscript/samtools/RDKit/...) -- see module
        # docstring. Bound at the same path inside the jail as on the host so
        # no path-rewriting is needed, and put first on PATH so it always
        # wins over any binary of the same name under /usr.
        jailed_path = "/usr/bin:/bin"
        if os.path.isdir(SANDBOX_TOOLKIT_DIR):
            argv += ["--ro-bind", SANDBOX_TOOLKIT_DIR, SANDBOX_TOOLKIT_DIR]
            jailed_path = f"{SANDBOX_TOOLKIT_DIR}/bin:{jailed_path}"

        if self.data_lake_root and os.path.isdir(self.data_lake_root):
            argv += ["--ro-bind", self.data_lake_root, "/datalake"]

        argv += [
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--ro-bind", workspace_abs, "/workspace",
            "--chdir", "/workspace",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
            "--die-with-parent",
            "--new-session",
            "--setenv", "PATH", jailed_path,
        ]
        if not self.allow_network:
            argv.append("--unshare-net")
        argv.append("--")
        return argv

    def _preexec_fn(self):
        """Returns a ``preexec_fn`` closure applying CPU-time/memory
        ``RLIMIT_*`` caps, or ``None`` when the ``resource`` module is
        unavailable (non-POSIX host)."""
        if resource is None:
            return None

        cpu_seconds = self.cpu_seconds
        memory_bytes = self.memory_bytes

        def _apply_limits() -> None:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))

        return _apply_limits

    def _run_or_mock(self, argv: List[str]) -> Tuple[str, int]:
        """Runs ``argv`` (real subprocess, wrapped in bwrap when
        ``runtime == "bubblewrap"``) or returns a deterministic mock, per
        ``self.runtime``. When a tracer is configured, the run is wrapped in a
        'sandbox.execute' span carrying stdout/exit_code (RNF-004), mirroring
        ``GVisorSandboxDriver``.
        """
        if self.tracer is None:
            output, exit_code, _ok = self._execute(argv)
            return output, exit_code

        with self.tracer.start_as_current_span("sandbox.execute") as span:
            span.set_attribute("sandbox.command", argv[0])
            output, exit_code, ok = self._execute(argv)
            span.set_attribute("sandbox.exit_code", exit_code)
            span.set_attribute("sandbox.stdout", output[:2000])
            if not ok:
                span.set_status(Status(StatusCode.ERROR))
            return output, exit_code

    def _execute(self, argv: List[str]) -> Tuple[str, int, bool]:
        """Returns ``(output, exit_code, ok)``. Never raises for a failed
        guest command (that is a normal <0 reward outcome, not a driver
        error) -- only a genuine transport failure (timeout, exec failure) is
        turned into an error-shaped ``(output, -1, False)`` result."""
        if self.runtime == "mock":
            return "Mock execution output: 42", 0, True

        full_argv = self._bwrap_argv() + list(argv) if self.runtime == "bubblewrap" else list(argv)
        try:
            result = subprocess.run(
                full_argv,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                preexec_fn=self._preexec_fn(),
            )
        except subprocess.TimeoutExpired:
            return (
                f"Execution error: sandbox timed out after {self.timeout_seconds}s",
                -1,
                False,
            )
        except OSError as exc:
            return f"Execution error: {exc}", -1, False

        ok = result.returncode == 0
        output = result.stdout if ok else f"Execution error: {result.stderr}"
        return output, result.returncode, ok

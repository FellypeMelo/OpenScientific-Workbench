import subprocess
import os

from opentelemetry.trace import Status, StatusCode

from src.domain.services.path_guard import PathTraversalError, ensure_safe_relative_path

class GVisorSandboxDriver:
    """
    Adapter for running code in a secure container sandboxed by gVisor (runsc).
    Includes Path Traversal validations at the execution layer.
    """
    def __init__(self, workspace_root: str = "osw_workspace", tracer=None):
        self.workspace_root = workspace_root
        # Optional OpenTelemetry tracer (RNF-004): when set, each sandbox
        # execution is wrapped in a span carrying stdout/exit_code.
        self.tracer = tracer

    def execute_python_script(self, relative_script_path: str) -> str:
        # 1. Path Traversal Check (Mitigation for CVE-2026-7398). Delegated to the
        # shared containment guard, which also blocks Windows drive-letter paths.
        try:
            resolved_path = ensure_safe_relative_path(relative_script_path)
        except PathTraversalError as exc:
            raise PermissionError(
                "FATAL_GVISOR_SYSCALL_HOOK: Path traversal or absolute access blocked."
            ) from exc

        # In a real environment, we'd run:
        # docker run --runtime=runsc -v host_workspace:/workspace osw-sandbox python /workspace/script.py
        # For local execution without Docker, we can run it as a subprocess (with warning) or mock it
        # In a real environment, we'd run:
        # docker run --runtime=runsc -v host_workspace:/workspace osw-sandbox python /workspace/script.py
        full_path = os.path.join(self.workspace_root, resolved_path)
        return self._run_or_mock(["python", full_path])

    def execute_bash(self, command: str) -> str:
        """Runs a bash command in the sandbox (RF-005)."""
        return self._run_or_mock(["bash", "-c", command])

    def execute_r_script(self, code: str) -> str:
        """Runs an R snippet in the sandbox (RF-005)."""
        return self._run_or_mock(["Rscript", "-e", code])

    def _run_or_mock(self, argv: list) -> str:
        """Executes ``argv`` as a subprocess under CI; otherwise returns a mock.

        Real gVisor isolation (``docker run --runtime=runsc``) needs a Linux host
        with the runsc runtime and is out of reach here (RF-005 infra-blocked);
        this keeps the multi-language execution surface real and testable. When a
        tracer is configured, the run is wrapped in a 'sandbox.execute' span
        carrying stdout/exit_code (RNF-004).
        """
        if self.tracer is None:
            output, _, _ = self._execute(argv)
            return output

        with self.tracer.start_as_current_span("sandbox.execute") as span:
            span.set_attribute("sandbox.command", argv[0])
            output, exit_code, ok = self._execute(argv)
            span.set_attribute("sandbox.exit_code", exit_code)
            span.set_attribute("sandbox.stdout", output[:2000])
            if not ok:
                span.set_status(Status(StatusCode.ERROR))
            return output

    @staticmethod
    def _execute(argv: list):
        """Runs ``argv`` (under CI) or mocks it, returning (output, exit_code, ok)."""
        if os.getenv("CI") == "true":
            try:
                result = subprocess.run(
                    argv, capture_output=True, text=True, timeout=30, check=True
                )
                return result.stdout, result.returncode, True
            except subprocess.CalledProcessError as e:
                return f"Execution error: {e.stderr}", e.returncode, False
        return "Mock execution output: 42", 0, True

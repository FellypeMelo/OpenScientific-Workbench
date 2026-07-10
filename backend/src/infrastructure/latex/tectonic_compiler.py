"""Tectonic-backed LaTeX -> PDF compiler (RF-008).

Tectonic is a single static binary (no full TeXLive), so this is a lightweight
local dependency rather than heavy infra. When the binary is absent it raises a
clear error; the compile path itself is unit-tested with a mocked subprocess.
"""
import shutil
import subprocess


class TectonicNotAvailableError(RuntimeError):
    """Raised when the tectonic binary is not installed on the host/CI image."""


class TectonicCompiler:
    def __init__(self, binary: str = "tectonic"):
        self.binary = binary

    def compile(self, latex_source: str) -> bytes:
        """Compiles LaTeX source to PDF bytes (reads stdin, writes PDF to stdout)."""
        if shutil.which(self.binary) is None:
            raise TectonicNotAvailableError(
                f"Tectonic binary {self.binary!r} not found on PATH; install it to compile manuscripts."
            )

        result = subprocess.run(
            [self.binary, "-", "--outfmt", "pdf"],
            input=latex_source.encode("utf-8"),
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Tectonic compilation failed: {result.stderr.decode('utf-8', errors='replace').strip()}"
            )
        return result.stdout

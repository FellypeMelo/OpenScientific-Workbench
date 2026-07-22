"""Unit tests for `NvidiaVRAMChecker` (RNF-008).

`subprocess.run` is the actual transport boundary (a real `nvidia-smi`
invocation) -- mocked here, mirroring `test_bubblewrap_driver.py`'s style for
`BubblewrapSandboxDriver`. This test host (a Windows dev sandbox with no
NVIDIA GPU) genuinely cannot run `nvidia-smi` for real, so every branch below
is exercised via the fake.
"""
import subprocess
import types

import pytest

import src.infrastructure.hpc.nvidia_vram_checker as nvidia_vram_checker_module
from src.infrastructure.hpc.nvidia_vram_checker import NvidiaVRAMChecker


@pytest.mark.asyncio
async def test_missing_nvidia_smi_binary_returns_zero(monkeypatch):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("nvidia-smi not found")

    monkeypatch.setattr(nvidia_vram_checker_module.subprocess, "run", fake_run)

    result = await NvidiaVRAMChecker().available_vram_gb()

    assert result == 0.0


@pytest.mark.asyncio
async def test_subprocess_error_returns_zero(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=10)

    monkeypatch.setattr(nvidia_vram_checker_module.subprocess, "run", fake_run)

    result = await NvidiaVRAMChecker().available_vram_gb()

    assert result == 0.0


@pytest.mark.asyncio
async def test_nonzero_exit_code_returns_zero(monkeypatch):
    monkeypatch.setattr(
        nvidia_vram_checker_module.subprocess,
        "run",
        lambda argv, **kwargs: types.SimpleNamespace(returncode=1, stdout="", stderr="no devices"),
    )

    result = await NvidiaVRAMChecker().available_vram_gb()

    assert result == 0.0


@pytest.mark.asyncio
async def test_unparseable_output_returns_zero(monkeypatch):
    monkeypatch.setattr(
        nvidia_vram_checker_module.subprocess,
        "run",
        lambda argv, **kwargs: types.SimpleNamespace(returncode=0, stdout="not-a-number\n", stderr=""),
    )

    result = await NvidiaVRAMChecker().available_vram_gb()

    assert result == 0.0


@pytest.mark.asyncio
async def test_single_gpu_reports_free_vram_in_gb(monkeypatch):
    # 24576 MiB free -> exactly 24 GiB.
    monkeypatch.setattr(
        nvidia_vram_checker_module.subprocess,
        "run",
        lambda argv, **kwargs: types.SimpleNamespace(returncode=0, stdout="24576\n", stderr=""),
    )

    result = await NvidiaVRAMChecker().available_vram_gb()

    assert result == pytest.approx(24.0)


@pytest.mark.asyncio
async def test_multi_gpu_reports_maximum_not_sum(monkeypatch):
    monkeypatch.setattr(
        nvidia_vram_checker_module.subprocess,
        "run",
        lambda argv, **kwargs: types.SimpleNamespace(
            returncode=0, stdout="1024\n8192\n4096\n", stderr=""
        ),
    )

    result = await NvidiaVRAMChecker().available_vram_gb()

    assert result == pytest.approx(8.0)


def test_correct_nvidia_smi_argv_used(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return types.SimpleNamespace(returncode=0, stdout="0\n", stderr="")

    monkeypatch.setattr(nvidia_vram_checker_module.subprocess, "run", fake_run)

    NvidiaVRAMChecker()._query_sync()

    assert captured["argv"] == [
        "nvidia-smi",
        "--query-gpu=memory.free",
        "--format=csv,noheader,nounits",
    ]

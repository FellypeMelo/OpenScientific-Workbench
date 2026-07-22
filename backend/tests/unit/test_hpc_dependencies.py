"""Unit tests for the HPC dispatcher/credential-provider factories added to
`presentation/dependencies.py` (RF-006/RNF-003 gap closure): backend
selection driven by `settings.HPC_BACKEND`, and Vault wiring driven by
`settings.VAULT_TOKEN`.
"""
from src.infrastructure.hpc.local_job_dispatcher import LocalJobDispatcher
from src.infrastructure.hpc.slurm_dispatcher import SlurmSSHDispatcher
from src.infrastructure.security.vault_client import VaultClient
from src.presentation import dependencies


def test_get_credential_provider_returns_none_when_vault_token_unset(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "VAULT_TOKEN", None)
    assert dependencies.get_credential_provider() is None


def test_get_credential_provider_returns_vault_client_when_configured(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "VAULT_TOKEN", "s.some-real-token")
    provider = dependencies.get_credential_provider()
    assert isinstance(provider, VaultClient)


def test_get_hpc_dispatcher_defaults_to_local(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "HPC_BACKEND", "local")
    dispatcher = dependencies.get_hpc_dispatcher(credential_provider=None)
    assert isinstance(dispatcher, LocalJobDispatcher)


def test_get_hpc_dispatcher_selects_slurm_when_configured(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "HPC_BACKEND", "slurm")
    dispatcher = dependencies.get_hpc_dispatcher(credential_provider=None)
    assert isinstance(dispatcher, SlurmSSHDispatcher)
    assert dispatcher.credential_provider is None


def test_get_hpc_dispatcher_wires_credential_provider_into_slurm(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "HPC_BACKEND", "slurm")
    fake_provider = VaultClient(vault_token="s.fake")

    dispatcher = dependencies.get_hpc_dispatcher(credential_provider=fake_provider)

    assert isinstance(dispatcher, SlurmSSHDispatcher)
    assert dispatcher.credential_provider is fake_provider


def test_get_vram_checker_returns_nvidia_checker():
    from src.infrastructure.hpc.nvidia_vram_checker import NvidiaVRAMChecker

    assert isinstance(dependencies.get_vram_checker(), NvidiaVRAMChecker)

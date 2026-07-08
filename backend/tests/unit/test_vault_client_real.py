"""
Real-path tests for `VaultClient` (Fase 4). The `hvac.Client` transport is
mocked so these tests exercise the *real* Vault SSH secrets engine (OTP mode)
call path -- `client.secrets.ssh.generate_ssh_credentials(...)` -- without
requiring a live Vault server, which does not exist in this sandbox.
"""
import pytest
from unittest.mock import MagicMock

from src.infrastructure.security import vault_client as vault_client_module
from src.infrastructure.security.vault_client import VaultClient


def _make_fake_hvac_client(response: dict):
    client = MagicMock(name="hvac_client")
    client.secrets.ssh.generate_ssh_credentials.return_value = response
    return client


@pytest.mark.asyncio
async def test_vault_client_real_returns_otp_from_ssh_engine(monkeypatch):
    fake_response = {
        "data": {"key": "1a7145ed-otp-value", "key_type": "otp", "port": 22, "username": "scientist"}
    }
    fake_client = _make_fake_hvac_client(fake_response)
    monkeypatch.setattr(vault_client_module.hvac, "Client", MagicMock(return_value=fake_client))

    client = VaultClient(vault_url="http://vault.internal:8200", vault_token="real-token", ssh_role="hpc-role")
    assert bool(client.vault_token) is True

    token = await client.get_ephemeral_ssh_token("scientist", target_ip="10.0.0.5")

    assert token == "1a7145ed-otp-value"
    vault_client_module.hvac.Client.assert_called_once_with(
        url="http://vault.internal:8200", token="real-token"
    )
    fake_client.secrets.ssh.generate_ssh_credentials.assert_called_once_with(
        name="hpc-role", username="scientist", ip="10.0.0.5"
    )


@pytest.mark.asyncio
async def test_vault_client_real_missing_otp_key_raises(monkeypatch):
    fake_client = _make_fake_hvac_client({"data": {}})
    monkeypatch.setattr(vault_client_module.hvac, "Client", MagicMock(return_value=fake_client))

    client = VaultClient(vault_url="http://vault.internal:8200", vault_token="real-token")

    with pytest.raises(RuntimeError, match="did not return an OTP"):
        await client.get_ephemeral_ssh_token("scientist")


@pytest.mark.asyncio
async def test_vault_client_real_defaults_to_zero_address_ip(monkeypatch):
    fake_response = {"data": {"key": "otp-zero-addr"}}
    fake_client = _make_fake_hvac_client(fake_response)
    monkeypatch.setattr(vault_client_module.hvac, "Client", MagicMock(return_value=fake_client))

    client = VaultClient(vault_url="http://vault.internal:8200", vault_token="real-token", ssh_role="hpc-role")
    token = await client.get_ephemeral_ssh_token("scientist")

    assert token == "otp-zero-addr"
    fake_client.secrets.ssh.generate_ssh_credentials.assert_called_once_with(
        name="hpc-role", username="scientist", ip=""
    )

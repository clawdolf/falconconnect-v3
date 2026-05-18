"""Credential resolution precedence for the live audit.

The audit must prefer FC pydantic-settings values over raw env vars so that
secrets configured via the Render env-var panel (or /etc/secrets/.env) are
honoured without requiring the caller to re-export them.
"""

import sys
import types

import pytest

from services import lead_hygiene_collect as collect


def _install_fake_config(close_key: str = "", ghl_key: str = ""):
    """Install a fake `config` module exposing the same get_settings() API."""
    fake = types.ModuleType("config")

    class _S:
        close_api_key = close_key
        ghl_api_key = ghl_key

    fake.get_settings = lambda: _S()  # type: ignore[attr-defined]
    sys.modules["config"] = fake


@pytest.fixture(autouse=True)
def _restore_config():
    saved = sys.modules.get("config")
    yield
    if saved is not None:
        sys.modules["config"] = saved
    else:
        sys.modules.pop("config", None)


def test_close_key_prefers_fc_settings_over_env(monkeypatch):
    _install_fake_config(close_key="from-fc-settings")
    monkeypatch.setenv("CLOSE_API_KEY", "from-env-should-lose")
    assert collect._resolve_close_api_key() == "from-fc-settings"


def test_close_key_falls_back_to_env_when_settings_blank(monkeypatch):
    _install_fake_config(close_key="")
    monkeypatch.setenv("CLOSE_API_KEY", "from-env")
    assert collect._resolve_close_api_key() == "from-env"


def test_close_key_falls_back_to_env_when_config_import_fails(monkeypatch):
    sys.modules.pop("config", None)
    # Block re-importing config.
    monkeypatch.setitem(sys.modules, "config", None)
    monkeypatch.setenv("CLOSE_API_KEY", "from-env-only")
    assert collect._resolve_close_api_key() == "from-env-only"


def test_close_key_empty_when_no_source_has_it(monkeypatch):
    _install_fake_config(close_key="")
    monkeypatch.delenv("CLOSE_API_KEY", raising=False)
    assert collect._resolve_close_api_key() == ""


def test_ghl_key_uses_fc_settings_first(monkeypatch):
    _install_fake_config(ghl_key="ghl-from-settings")
    monkeypatch.setenv("GHL_API_KEY", "ghl-from-env")
    assert collect._resolve_ghl_api_key() == "ghl-from-settings"


def test_ghl_key_falls_back_to_env(monkeypatch):
    _install_fake_config(ghl_key="")
    monkeypatch.setenv("GHL_API_KEY", "ghl-from-env")
    assert collect._resolve_ghl_api_key() == "ghl-from-env"

"""Choix du modèle Bedrock par type d'agent."""

import pytest

from invest_agents.models import model_id_for
from invest_agents.runtime import get_runtime_settings


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch):
    for name in ("MODEL_STRONG", "MODEL_FAST", "MODEL_PEPITE"):
        monkeypatch.delenv(name, raising=False)
    get_runtime_settings.cache_clear()
    yield
    get_runtime_settings.cache_clear()


def test_defaults_pepite_sonnet_others_opus():
    assert model_id_for("pepite") == "global.anthropic.claude-sonnet-5-5"
    assert model_id_for("strong") == "global.anthropic.claude-opus-5-5"
    assert model_id_for("fast") == "global.anthropic.claude-opus-5-5"


def test_env_override(monkeypatch):
    monkeypatch.setenv("MODEL_PEPITE", "global.anthropic.claude-opus-5-5")
    get_runtime_settings.cache_clear()
    assert model_id_for("pepite") == "global.anthropic.claude-opus-5-5"


def test_pepite_agent_uses_pepite_kind():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src/invest_agents/workflow/pepite.py").read_text(encoding="utf-8")
    assert 'label="Pépite", step="4", kind="pepite"' in src

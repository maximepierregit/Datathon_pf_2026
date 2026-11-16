"""Enregistrement et restauration d'une conversation MonPort dans AgentCore Memory (client simulé)."""

import asyncio
from datetime import datetime, timezone

import pytest

from invest_agents import memory
from invest_agents.schemas import InvestorForm, Portfolio
from invest_agents.workflow.session import SESSIONS, SessionStore


class FakeMemory:
    def __init__(self):
        self.events = []

    def create_event(self, **kw):
        self.events.append({**kw, "eventTimestamp": kw["eventTimestamp"]})
        return {"event": {"eventId": str(len(self.events))}}

    def list_events(self, memoryId, actorId, sessionId, includePayloads, maxResults, **_):
        return {"events": [e for e in self.events if e["sessionId"] == sessionId and e["actorId"] == actorId]}


def _form():
    fields = InvestorForm.model_fields
    sample = {"age": 35, "investment_amount_cad": 10000, "horizon_years": 12, "risk_tolerance": 3,
              "max_acceptable_loss_pct": 20, "objective": "balanced", "experience": "intermediate",
              "liquidity_needs": "low"}
    return InvestorForm.model_validate({k: v for k, v in sample.items() if k in fields})


@pytest.fixture
def fake(monkeypatch):
    client = FakeMemory()
    monkeypatch.setenv("MEMORY_ID", "mem-test")
    monkeypatch.setattr(memory, "_client", lambda: client)
    return client


def _session(store):
    s = store.create({"age": 35}, {"vehicles": "tous"}, _form(), ["facteurs"], market=None)
    s.portfolios["equilibre"] = Portfolio(id="equilibre", mandate="Variante fidèle", mandate_description="test")
    s.winner, s.justification, s.version, s.adjust_steps = "equilibre", "La fidèle gagne.", 3, 1
    return s


def test_roundtrip(fake):
    s = _session(SessionStore())
    memory.save(s)
    restored = memory.from_state(memory.load(s.id), market="M")
    assert restored.id == s.id and restored.market == "M"
    assert restored.portfolios["equilibre"].mandate == "Variante fidèle"
    assert (restored.winner, restored.justification, restored.adjust_steps) == ("equilibre", "La fidèle gagne.", 1)
    assert restored.shown_version == restored.version == 3  # pas de réaffichage inutile
    assert restored.pepite is None and restored.workers == {}  # les agents repartent à neuf


def test_contribution_survives_a_restore(fake):
    """Les ajouts prévus servent à la projection: une session restaurée doit les retrouver (sans jamais les donner aux agents)."""
    s = _session(SessionStore())
    s.contribution = {"frequency": "mensuelle", "amount": 150.0}
    memory.save(s)
    restored = memory.from_state(memory.load(s.id), market="M")
    assert restored.contribution == {"frequency": "mensuelle", "amount": 150.0}
    assert "contribution" not in str(restored.form.model_dump())  # le formulaire envoyé aux agents n'en contient pas


def test_latest_event_wins(fake):
    s = _session(SessionStore())
    memory.save(s)
    s.justification = "Nouvelle décision"
    memory.save(s)
    fake.events[0]["eventTimestamp"] = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert memory.load(s.id)["justification"] == "Nouvelle décision"


def test_store_restores_missing_session(fake):
    s = _session(SessionStore())
    memory.save(s)
    store = SessionStore()  # microVM neuve: rien en mémoire du processus
    restored = asyncio.run(store.get_or_restore(s.id, market="M"))
    assert restored is not None and restored.winner == "equilibre"
    assert store.get(s.id) is restored


def test_disabled_or_invalid_id(monkeypatch, fake):
    assert asyncio.run(SessionStore().get_or_restore("../pas-un-id", market=None)) is None
    monkeypatch.delenv("MEMORY_ID")
    assert asyncio.run(SessionStore().get_or_restore("a" * 32, market=None)) is None
    memory.save(_session(SessionStore()))
    assert fake.events == []


def test_errors_never_raise(monkeypatch):
    class Broken:
        def create_event(self, **_):
            raise RuntimeError("throttled")

        def list_events(self, **_):
            raise RuntimeError("throttled")

    monkeypatch.setenv("MEMORY_ID", "mem-test")
    monkeypatch.setattr(memory, "_client", lambda: Broken())
    s = _session(SESSIONS)
    memory.save(s)
    assert memory.load(s.id) is None

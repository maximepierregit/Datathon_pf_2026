"""État d'une conversation MonPort.

Les agents (Pépite, gestionnaires, agents Risque, juge) restent en mémoire avec leur historique: c'est ce qui permet
à Pépite de leur demander plus tard « pourquoi ce portefeuille? ». L'état vit dans le processus. AgentCore Runtime
route toutes les requêtes d'une même session vers la même instance; si elle disparaît, `flow.py` repart des données
que le frontend renvoie (questionnaire et vérification) et les agents perdent seulement leur mémoire.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from ..agents.base import AgentHandle
from ..agents.portfolio_manager import PMWorker
from ..market import Market
from ..events import EventBus
from ..monport import SLOTS, Translator, assess
from ..schemas import (
    Constraint,
    InvestorForm,
    InvestorProfile,
    JudgeDecision,
    JudgeVerdict,
    PepiteCheck,
    PepiteReview,
    Portfolio,
    RiskReport,
)

from .. import memory

logger = logging.getLogger(__name__)

MAX_SESSIONS = 200
SESSION_ID_RE = re.compile(r"[0-9a-f]{32}")  # uuid4().hex, comme `SessionStore.create`
SESSION_TTL_SECONDS = 2 * 3600


def review_of(check: PepiteCheck) -> PepiteReview:
    """Le texte et la cohérence d'une vérification (le profil de risque, lui, se recalcule)."""
    return PepiteReview(**check.model_dump(include={"summary", "key_points", "flags", "coherent", "issues", "questions"}))


@dataclass
class Session:
    id: str
    profile: dict
    prefs: dict
    form: InvestorForm
    skipped: list[str]
    market: Market
    review: Optional[PepiteReview] = None

    # Profil de risque: le code le calcule, Pépite le déplace au plus de ±2 crans (`adjust_risk_position`).
    adjust_steps: int = 0
    risk_computed: bool = False
    facts_read: bool = False

    # Contraintes envoyées aux gestionnaires (slot -> (consigne, contraintes)), après validation par le code.
    profiles: dict[str, tuple[str, list[Constraint]]] = field(default_factory=dict)
    notes: dict[str, list[str]] = field(default_factory=dict)
    universe: Optional[tuple[int, int]] = None

    # Les agents et ce qu'ils ont produit
    pepite: Optional[AgentHandle] = None
    workers: dict[str, PMWorker] = field(default_factory=dict)
    risk_agents: dict[str, AgentHandle] = field(default_factory=dict)
    judge: Optional[AgentHandle] = None
    investors: dict[str, InvestorProfile] = field(default_factory=dict)
    portfolios: dict[str, Portfolio] = field(default_factory=dict)
    reports: dict[str, RiskReport] = field(default_factory=dict)
    verdicts: dict[str, JudgeVerdict] = field(default_factory=dict)
    decision: Optional[JudgeDecision] = None
    winner: Optional[str] = None
    justification: str = ""
    reoptimize: dict[str, str] = field(default_factory=dict)  # slot -> consigne, à traiter par Pépite

    # Suivi
    build_round: int = 0  # nombre de passes de construction
    judged_round: int = -1  # passe que le juge a vue en dernier
    rebuilds_left: int = 0
    # Tour en cours: "check", "build", "chat" (aucune construction possible) ou "rebuild".
    phase: str = "check"
    # Changements convenus dans le chat, en attente de la confirmation du client, puis ceux déjà appliqués.
    pending_request: str = ""
    requests: list[str] = field(default_factory=list)
    version: int = 0  # augmente quand les portefeuilles changent: le frontend en reçoit alors une nouvelle version
    shown_version: int = -1
    bus: Optional[EventBus] = None
    translator: Optional[Translator] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    touched: float = field(default_factory=time.monotonic)

    @property
    def coherent(self) -> bool:
        return bool(self.review and self.review.coherent)

    @property
    def check(self) -> PepiteCheck:
        """Le profil de risque courant: texte de Pépite et chiffres du code, avec l'ajustement en cours."""
        if self.review is None:
            raise RuntimeError("La vérification du questionnaire n'a pas eu lieu.")
        return assess(self.profile, self.review, self.adjust_steps)

    def built(self) -> list[Portfolio]:
        return [p for s in SLOTS if (p := self.portfolios.get(s)) and p.status == "ok"]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def _purge(self) -> None:
        now = time.monotonic()
        for sid in [k for k, s in self._sessions.items() if now - s.touched > SESSION_TTL_SECONDS and not s.lock.locked()]:
            del self._sessions[sid]
        while len(self._sessions) >= MAX_SESSIONS:  # la plus ancienne d'abord
            oldest = min((s for s in self._sessions.values() if not s.lock.locked()), key=lambda s: s.touched, default=None)
            if oldest is None:
                break
            del self._sessions[oldest.id]

    def create(self, profile: dict, prefs: dict, form: InvestorForm, skipped: list[str], market: Market) -> Session:
        self._purge()
        session = Session(id=uuid.uuid4().hex, profile=profile, prefs=prefs, form=form, skipped=skipped, market=market)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: object) -> Optional[Session]:
        session = self._sessions.get(session_id) if isinstance(session_id, str) else None
        if session:
            session.touched = time.monotonic()
        return session

    async def get_or_restore(self, session_id: object, market: Market) -> Optional[Session]:
        """La session en mémoire du processus, sinon celle enregistrée dans AgentCore Memory (microVM recyclée)."""
        session = self.get(session_id)
        if session or not (isinstance(session_id, str) and SESSION_ID_RE.fullmatch(session_id) and memory.enabled()):
            return session
        state = await asyncio.to_thread(memory.load, session_id)
        if state is None:
            return None
        try:
            session = memory.from_state(state, market)
        except Exception:  # noqa: BLE001
            logger.exception("Session %s illisible dans la mémoire", session_id)
            return None
        self._purge()
        self._sessions[session.id] = session
        logger.info("Session %s restaurée depuis AgentCore Memory", session.id)
        return session


async def persist(session: Session) -> None:
    """Enregistre la session dans AgentCore Memory sans retarder le client (sans MEMORY_ID: rien)."""
    if memory.enabled():
        await asyncio.to_thread(memory.save, session)


SESSIONS = SessionStore()

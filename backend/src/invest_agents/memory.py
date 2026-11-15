"""Conversations MonPort dans AgentCore Memory (mémoire à court terme), pour survivre au recyclage d'une microVM.

AgentCore Runtime garde une conversation dans la même microVM, au plus 8 h et 1 h sans activité. Après la
vérification et chaque nouvelle version des portefeuilles, l'état de la session est enregistré comme événement
(questionnaire, revue de Pépite, profils de contraintes, portefeuilles, verdicts, gagnant). Si une requête arrive sur
une microVM qui ne connaît pas la session, elle est restaurée depuis la mémoire: les agents repartent sans historique,
mais Pépite reçoit l'état complet et les justifications restent disponibles (`get_justifications`).

Sans MEMORY_ID, rien n'est enregistré. Une erreur de la mémoire n'interrompt jamais le parcours.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import zlib
from datetime import datetime, timezone
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

import boto3

if TYPE_CHECKING:
    from .workflow.session import Session

logger = logging.getLogger(__name__)

ACTOR = "monport"
FORMAT = 1
# AgentCore Memory relit un blob objet comme une map Java en texte ({clé=valeur}): on enregistre donc une chaîne.
PREFIX = f"monport-session:v{FORMAT}:"


def enabled() -> bool:
    return bool(os.getenv("MEMORY_ID"))


@lru_cache(maxsize=1)
def _client():
    return boto3.client("bedrock-agentcore", region_name=os.getenv("AWS_REGION") or "us-east-1")


def _dump(m):
    return m.model_dump(mode="json") if m is not None else None


def to_state(s: "Session") -> dict:
    """Ce qui suffit à reprendre la conversation (pas les agents ni le marché, recréés à la demande)."""
    return {
        "format": FORMAT,
        "id": s.id, "profile": s.profile, "prefs": s.prefs, "form": _dump(s.form), "skipped": s.skipped,
        "review": _dump(s.review), "adjust_steps": s.adjust_steps,
        "profiles": {k: [text, [_dump(c) for c in cs]] for k, (text, cs) in s.profiles.items()},
        "notes": s.notes, "universe": list(s.universe) if s.universe else None,
        "investors": {k: _dump(v) for k, v in s.investors.items()},
        "portfolios": {k: _dump(v) for k, v in s.portfolios.items()},
        "reports": {k: _dump(v) for k, v in s.reports.items()},
        "verdicts": {k: _dump(v) for k, v in s.verdicts.items()},
        "decision": _dump(s.decision), "winner": s.winner, "justification": s.justification,
        "reoptimize": s.reoptimize, "build_round": s.build_round, "judged_round": s.judged_round,
        "pending_request": getattr(s, "pending_request", ""), "requests": list(getattr(s, "requests", [])),
        "version": s.version,
    }


def from_state(d: dict, market) -> "Session":
    from .schemas import (Constraint, InvestorForm, InvestorProfile, JudgeDecision, JudgeVerdict, PepiteReview,
                          Portfolio, RiskReport)
    from .workflow.session import Session

    s = Session(id=d["id"], profile=d["profile"], prefs=d["prefs"], form=InvestorForm.model_validate(d["form"]),
                skipped=d["skipped"], market=market)
    s.review = PepiteReview.model_validate(d["review"]) if d.get("review") else None
    s.adjust_steps = d.get("adjust_steps", 0)
    s.risk_computed = s.facts_read = True
    s.profiles = {k: (text, [Constraint.model_validate(c) for c in cs]) for k, (text, cs) in d["profiles"].items()}
    s.notes = d.get("notes", {})
    s.universe = tuple(d["universe"]) if d.get("universe") else None
    s.investors = {k: InvestorProfile.model_validate(v) for k, v in d["investors"].items()}
    s.portfolios = {k: Portfolio.model_validate(v) for k, v in d["portfolios"].items()}
    s.reports = {k: RiskReport.model_validate(v) for k, v in d["reports"].items()}
    s.verdicts = {k: JudgeVerdict.model_validate(v) for k, v in d["verdicts"].items()}
    s.decision = JudgeDecision.model_validate(d["decision"]) if d.get("decision") else None
    s.winner, s.justification = d.get("winner"), d.get("justification", "")
    s.reoptimize = d.get("reoptimize", {})
    s.build_round, s.judged_round = d.get("build_round", 0), d.get("judged_round", -1)
    s.pending_request, s.requests = d.get("pending_request", ""), list(d.get("requests", []))
    s.version = s.shown_version = d.get("version", 0)  # le client a déjà vu cette version
    return s


def _pack(state: dict) -> str:
    raw = zlib.compress(json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode(), 9)
    return PREFIX + base64.b64encode(raw).decode()


def _unpack(blob: str) -> dict:
    return json.loads(zlib.decompress(base64.b64decode(blob[len(PREFIX):])))


def save(session: "Session") -> None:
    """Enregistre l'état courant (appel bloquant: à lancer dans un thread)."""
    if not enabled():
        return
    try:
        _client().create_event(
            memoryId=os.environ["MEMORY_ID"], actorId=ACTOR, sessionId=session.id,
            eventTimestamp=datetime.now(timezone.utc), payload=[{"blob": _pack(to_state(session))}],
        )
    except Exception:  # noqa: BLE001
        logger.exception("Mémoire: enregistrement de la session %s en échec", session.id)


def load(session_id: str) -> Optional[dict]:
    """Le dernier état enregistré de la session, ou None."""
    if not enabled():
        return None
    try:
        events, token = [], None
        while True:
            kwargs = {"nextToken": token} if token else {}
            resp = _client().list_events(memoryId=os.environ["MEMORY_ID"], actorId=ACTOR, sessionId=session_id,
                                         includePayloads=True, maxResults=100, **kwargs)
            events += resp.get("events", [])
            token = resp.get("nextToken")
            if not token:
                break
        for event in sorted(events, key=lambda e: e["eventTimestamp"], reverse=True):
            for item in event.get("payload", []):
                blob = item.get("blob")
                if isinstance(blob, str) and blob.startswith(PREFIX):
                    return _unpack(blob)
    except Exception:  # noqa: BLE001
        logger.exception("Mémoire: lecture de la session %s en échec", session_id)
    return None

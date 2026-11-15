"""Points d'entrée MonPort (appelés par `main.py`), tous menés par Pépite.

    {"mode": "monport_check", "profile": {...}, "constraints": {...}}
        Pépite lit le questionnaire, juge sa cohérence et pose des questions s'il y a une incohérence
        -> {"type": "check", "check": PepiteCheck, "session": id}

    {"mode": "monport", "profile": ..., "constraints": ..., "check": PepiteCheck, "adjustment": "texte libre",
     "session": id (optionnel)}
        Pépite écrit les 3 profils de contraintes, lance les 3 gestionnaires (chacun avec son agent Risque), fait
        juger, relance au besoin -> {"type": "portfolios", "portfolios": {...}, "session": id}

    {"mode": "monport_chat", "session": id, "message": "texte libre"}
        Pépite répond au client. Pour un pourquoi, elle interroge les gestionnaires, les agents Risque et le juge.
        Pour un changement, elle pose des questions jusqu'à ce qu'il soit clair, puis le récapitule
        -> {"type": "pepite", "text": ..., "final": true, "ready": true, "request": "les changements convenus"}

    {"mode": "monport_rebuild", "session": id}
        Le client a confirmé les changements convenus dans le chat: Pépite réécrit les profils et relance toute la
        construction -> les mêmes événements que `monport`.

Les événements restent ceux de `PipelineEvent` (frontend/src/types.ts); `session` est un champ ajouté.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from pydantic import ValidationError

from ..agents.base import AgentError
from ..runtime import get_runtime_settings
from ..market import get_market
from ..monport import (
    MAX_ADJUSTMENT,
    SLOTS,
    TRIO,
    WINNER_NAME,
    Translator,
    _questionnaire,
    _stream,
    blend,
    coherence_facts,
    fallback_check,
    front,
    pepite,
    status,
    to_form,
    to_portfolio,
)
from .. import gateway
from ..guardrail import screen
from ..schemas import PepiteCheck
from .pepite import build_turn, chat_turn, check_turn, rebuild_turn
from .session import SESSIONS, Session, persist, review_of
from .workers import apply_plan, build_slots, judge_round, names_for

logger = logging.getLogger(__name__)


def _bind(session: Session, bus, translator: Translator) -> None:
    session.bus, session.translator = bus, translator
    translator.slots = {name: slot for slot, name in names_for(session).items()} if session.review else {}


async def _verify(session: Session, bus) -> None:
    """La vérification du questionnaire par Pépite. Le code l'oblige à passer par les deux outils déterministes."""
    facts = coherence_facts(session.profile, session.prefs)
    try:
        review = await check_turn(session, bus)
        if not (session.risk_computed and session.facts_read):
            logger.warning("Pépite n'a pas appelé les outils obligatoires, nouvelle demande")
            review = await check_turn(session, bus)
    except AgentError:
        logger.exception("Vérification de Pépite en échec, repli sur les règles du code")
        review = review_of(fallback_check(session.profile, facts))
    # Le code calcule le profil de risque de toute façon (`assess`): si Pépite ne l'a pas demandé, il reste valide.
    session.risk_computed = session.facts_read = True
    session.review = review


async def check_questionnaire(payload: dict, bus, translator: Translator) -> None:
    profile, prefs = _questionnaire(payload)
    gateway.prewarm()  # les outils seront prêts quand les gestionnaires en auront besoin
    market = await asyncio.to_thread(get_market)
    form, skipped = to_form(profile, prefs, market)  # valide le profil avant d'appeler le modèle
    session = SESSIONS.create(profile, prefs, form, skipped, market)
    async with session.lock:
        _bind(session, bus, translator)
        await _verify(session, bus)
        check = session.check
    front(bus, {"type": "check", "check": check.model_dump(mode="json"), "session": session.id})
    await persist(session)
    front(bus, {"type": "done"})


# --------------------------------------------------------------------------- #
# Le filet de sécurité: ce que le code garantit même si Pépite saute une étape
# --------------------------------------------------------------------------- #
async def ensure_pipeline(session: Session) -> None:
    """Complète ce que Pépite n'a pas fait: profils écrits par le code, portefeuilles manquants, jugement, et les
    relances que le juge exige tant qu'il en reste. Le résultat présenté est donc toujours complet et jugé."""
    if not session.profiles:
        logger.warning("Aucun plan de Pépite, profils écrits par le code")
        await apply_plan(session, None)
    missing = [s for s in SLOTS if s not in session.portfolios]
    if missing:
        await build_slots(session, missing, {})
    if not session.built():
        return
    if session.judged_round != session.build_round:
        await judge_round(session)
        # Le juge vient de parler sur ces portefeuilles: ses demandes de réoptimisation sont à traiter.
        while session.reoptimize and session.rebuilds_left > 0:
            session.rebuilds_left -= 1
            slots = [s for s in session.reoptimize if s in session.portfolios]
            front(session.bus, status("pepite", "running", "Le juge demande de reconstruire : " +
                                      ", ".join(session.portfolios[s].mandate for s in slots)))
            await build_slots(session, slots, session.reoptimize)
            await judge_round(session)


def _warnings_for(session: Session, target: str, sources: list[str]) -> list[dict]:
    seen, out = set(), []
    for slot in sources:
        report = session.reports.get(slot)
        for w in report.warnings if report else []:
            if w.title not in seen:
                seen.add(w.title)
                out.append({**w.model_dump(mode="json"), "portfolio_id": target})
    return out


def present(session: Session, bus) -> bool:
    """Émet l'événement `portfolios`. Même présentation qu'avant: un gagnant (profil cohérent) ou trois propositions."""
    built = session.built()
    if not built:
        front(bus, {"type": "error", "message": "Aucun portefeuille n’a pu être construit. Réessaie dans un instant."})
        return False
    check, market = session.check, session.market
    by = {p.id: p for p in built}
    if session.coherent:
        winner = by.get(session.winner or "") or built[0]
        presented = [(winner, session.verdicts.get(winner.id), WINNER_NAME, session.justification, [winner.id])]
    else:
        presented = []
        for slot, p, sources in (
            ("prudent", blend(market, "prudent", by.get("prudent"), by.get("conviction")), ["prudent", "conviction"]),
            ("equilibre", by.get("equilibre"), ["equilibre"]),
            ("conviction", blend(market, "conviction", by.get("conviction"), by.get("prudent")), ["conviction", "prudent"]),
        ):
            if p is not None:
                p = p.model_copy(update={"mandate": TRIO[slot][0]})
                # Le juge a vérifié les bases; seul « Tes contraintes » est présenté tel quel.
                presented.append((p, session.verdicts.get(slot) if slot == "equilibre" else None, *TRIO[slot], sources))
        front(bus, status("pepite", "done", "Mélanges 80/20 prêts : profil d’abord, préférences d’abord."))
    front(bus, {"type": "portfolios", "session": session.id, "portfolios": {
        p.id: to_portfolio(p, v, market, {"warnings": _warnings_for(session, p.id, sources)}, check.risk_position,
                           session.skipped, session.notes.get(p.id, []), name, tagline)
        for p, v, name, tagline, sources in presented
    }})
    session.shown_version = session.version
    return True


def _reset_results(session: Session) -> None:
    """Un nouveau lancement repart de zéro. Les agents gardent leur mémoire, les résultats non."""
    session.profiles, session.notes, session.universe = {}, {}, None
    session.portfolios, session.reports, session.verdicts = {}, {}, {}
    session.decision, session.winner, session.justification, session.reoptimize = None, None, "", {}
    session.build_round, session.judged_round = 0, -1


async def build_portfolios(payload: dict, bus, translator: Translator) -> None:
    profile, prefs = _questionnaire(payload)
    gateway.prewarm()
    market = await asyncio.to_thread(get_market)
    session = await SESSIONS.get_or_restore(payload.get("session"), market)
    if session and (session.profile != profile or session.prefs != prefs):
        session = None  # le client a changé son questionnaire depuis la vérification: nouvelle conversation
    if session is None:  # pas de session (ou perdue): on repart du questionnaire et de la vérification renvoyés
        form, skipped = to_form(profile, prefs, market)
        session = SESSIONS.create(profile, prefs, form, skipped, market)
        try:
            session.review = review_of(PepiteCheck.model_validate(payload.get("check")))
        except ValidationError:
            session.review = None
    if session.lock.locked():
        front(bus, {"type": "error", "message": "Une demande est déjà en cours pour cette conversation."})
        return
    async with session.lock:
        _bind(session, bus, translator)
        if session.review is None:
            await _verify(session, bus)
            _bind(session, bus, translator)
        _reset_results(session)
        adjustment = str(payload.get("adjustment") or "").strip()[:MAX_ADJUSTMENT]
        refusal = await asyncio.to_thread(screen, adjustment)
        if refusal:  # l'ajustement est écarté, la construction continue avec le questionnaire seul
            front(bus, pepite(refusal + " Je construis tes portefeuilles avec ton questionnaire seulement."))
            adjustment = ""
        session.rebuilds_left = get_runtime_settings().max_pm_retries

        front(bus, pepite("C’est parti! J’écris les consignes de tes trois gestionnaires."))
        front(bus, status("pepite", "running", "Je prépare la construction…"))
        reply: Optional[str] = None
        try:
            reply = (await build_turn(session, bus, adjustment)).message
        except AgentError:
            logger.exception("Pépite en échec pendant la construction, le code termine le travail")
        _bind(session, bus, translator)  # Pépite a pu réviser la cohérence: les noms des gestionnaires changent
        await ensure_pipeline(session)
        front(bus, status("pepite", "done", "Portefeuilles prêts."))
        if present(session, bus):
            front(bus, pepite(reply or ("Voilà! Ton portefeuille t’attend." if session.coherent
                                        else "Voilà! Trois propositions t’attendent. C’est toi qui choisis.")))
            await persist(session)
    front(bus, {"type": "done"})


async def chat(payload: dict, bus, translator: Translator) -> None:
    market = await asyncio.to_thread(get_market)
    session = await SESSIONS.get_or_restore(payload.get("session"), market)
    message = str(payload.get("message") or "").strip()[:MAX_ADJUSTMENT]
    if session is None or not session.portfolios:
        front(bus, {"type": "error", "message": "Cette conversation a expiré. Relance la construction de tes portefeuilles."})
        return
    if not message:
        front(bus, {"type": "error", "message": "Ton message est vide."})
        return
    if session.lock.locked():
        front(bus, {"type": "error", "message": "Une demande est déjà en cours pour cette conversation."})
        return
    refusal = await asyncio.to_thread(screen, message)
    if refusal:
        front(bus, {**pepite(refusal), "final": True})
        front(bus, {"type": "done"})
        return
    async with session.lock:
        _bind(session, bus, translator)
        try:
            answer = await chat_turn(session, bus, message)
            reply, request = answer.message, answer.rebuild_request.strip() if answer.ready_to_rebuild else ""
        except AgentError:
            logger.exception("Pépite en échec pendant le chat")
            reply, request = "Je n’ai pas réussi à répondre à ta question. Peux-tu la reformuler?", ""
        # La reconstruction attend la confirmation du client (mode monport_rebuild).
        session.pending_request = request[:MAX_ADJUSTMENT]
        front(bus, status("pepite", "done", "Réponse prête."))
        front(bus, {**pepite(reply), "final": True, **({"ready": True, "request": request} if request else {})})
        await persist(session)
    front(bus, {"type": "done"})


async def rebuild(payload: dict, bus, translator: Translator) -> None:
    market = await asyncio.to_thread(get_market)
    session = await SESSIONS.get_or_restore(payload.get("session"), market)
    if session is None or not session.portfolios:
        front(bus, {"type": "error", "message": "Cette conversation a expiré. Relance la construction de tes portefeuilles."})
        return
    if not session.pending_request:
        front(bus, {"type": "error", "message": "Je n’ai aucun changement à appliquer. Dis-moi dans le chat ce que tu veux changer."})
        return
    if session.lock.locked():
        front(bus, {"type": "error", "message": "Une demande est déjà en cours pour cette conversation."})
        return
    async with session.lock:
        request, session.pending_request = session.pending_request, ""
        _bind(session, bus, translator)
        _reset_results(session)
        session.rebuilds_left = get_runtime_settings().max_pm_retries

        front(bus, pepite("C’est parti! Je relance mes agents avec tes changements."))
        front(bus, status("pepite", "running", "Je réécris les consignes des gestionnaires…"))
        reply: Optional[str] = None
        try:
            reply = (await rebuild_turn(session, bus, request)).message
        except AgentError:
            logger.exception("Pépite en échec pendant la reconstruction, le code termine le travail")
        _bind(session, bus, translator)
        await ensure_pipeline(session)
        session.requests.append(request)
        front(bus, status("pepite", "done", "Portefeuilles prêts."))
        if present(session, bus):
            front(bus, pepite(reply or "Voilà! Tes portefeuilles tiennent compte de tes changements."))
            await persist(session)
    front(bus, {"type": "done"})


def stream_check(payload: dict) -> AsyncIterator[dict]:
    translator = Translator()
    return _stream(lambda bus: check_questionnaire(payload, bus, translator), translator)


def stream_monport(payload: dict) -> AsyncIterator[dict]:
    translator = Translator()
    return _stream(lambda bus: build_portfolios(payload, bus, translator), translator)


def stream_chat(payload: dict) -> AsyncIterator[dict]:
    translator = Translator()
    return _stream(lambda bus: chat(payload, bus, translator), translator)


def stream_rebuild(payload: dict) -> AsyncIterator[dict]:
    translator = Translator()
    return _stream(lambda bus: rebuild(payload, bus, translator), translator)

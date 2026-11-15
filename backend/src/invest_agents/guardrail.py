"""Bedrock Guardrails sur le texte libre du client (chat avec Pépite, ajustement avant la construction).

Seul le texte écrit par le client passe par le guardrail, avant d'atteindre Pépite: le JSON d'état que reçoivent les
agents (poids, montants) n'est jamais évalué, ce qui évite les faux positifs. Sans GUARDRAIL_ID, rien n'est filtré.
Si le service ne répond pas, le message passe (le parcours reste disponible) et l'incident est journalisé.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

DEFAULT_BLOCKED = "Je ne peux pas t’aider avec ça. Je suis là pour parler de ton portefeuille et de tes placements."


@lru_cache(maxsize=1)
def _client():
    return boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION") or "us-east-1")


def screen(text: str) -> Optional[str]:
    """Le message de refus si le guardrail bloque `text`, sinon None."""
    gid, version = os.getenv("GUARDRAIL_ID"), os.getenv("GUARDRAIL_VERSION")
    if not (gid and version and text.strip()):
        return None
    try:
        resp = _client().apply_guardrail(guardrailIdentifier=gid, guardrailVersion=version, source="INPUT",
                                         content=[{"text": {"text": text}}])
    except Exception:  # noqa: BLE001
        logger.exception("Guardrail indisponible, message transmis sans filtrage")
        return None
    if resp.get("action") != "GUARDRAIL_INTERVENED":
        return None
    logger.info("Guardrail: message du client bloqué")
    outputs = resp.get("outputs") or []
    return (outputs[0].get("text") if outputs else None) or DEFAULT_BLOCKED

"""Agent Extraction (étape 3b): traduit un message libre en contraintes du catalogue.

L'agent propose. La validation est faite par `constraints.validate_all`: toute cible hors catalogue est
refusée et transformée en question de clarification.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..constraints import catalog_prompt, describe, validate_all
from ..data import Market
from ..events import EventBus
from ..schemas import Constraint, ConstraintRef, ExtractionResult
from ..tools import make_extraction_tools
from .base import run_agent

SYSTEM_TEMPLATE = """Tu es l'agent Extraction. L'investisseur écrit un message libre pour ajouter, modifier ou retirer des
contraintes sur ses portefeuilles. Tu transformes ce message en contraintes structurées du catalogue ci-dessous.

{catalog}

RÈGLES
- Une contrainte par exigence. Convertis les pourcentages en fractions (« 10 % » devient 0.10).
- Utilise exactement les libellés du catalogue pour les cibles. Pour un nom d'entreprise, appelle `search_universe`
  et utilise le symbole retourné. Si plusieurs entreprises correspondent, pose une question de clarification.
- `hard` vaut true par défaut. Mets false seulement pour une préférence (« idéalement », « si possible »).
- `source` vaut "chat". Dans `note`, recopie le passage du message qui justifie la contrainte.
- Si l'utilisateur demande de retirer ou d'assouplir une contrainte existante, mets-la dans `removals`; pour un
  assouplissement chiffré, émets plutôt la nouvelle valeur dans `constraints` (elle remplace l'ancienne).
- Si une demande est vague (« plus prudent », « moins risqué ») ou ne correspond à aucun type du catalogue, ne
  l'invente pas: place le passage dans `unmatched` et ajoute une question précise dans `clarification_questions`
  (ex.: proposer une volatilité maximale).
- Ne crée aucune contrainte qui n'est pas demandée."""


@dataclass
class ExtractionOutcome:
    constraints: list[Constraint]
    removals: list[ConstraintRef]
    unmatched: list[str]
    questions: list[str] = field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.questions)


async def run_extraction_agent(
    bus: EventBus, market: Market, message: str, current: list[Constraint]
) -> ExtractionOutcome:
    current_text = "\n".join(f"- {describe(c)}" for c in current if c.source != "profile") or "(aucune)"
    result = await run_agent(
        bus=bus,
        label="Extraction",
        step="3b",
        kind="fast",
        system_prompt=SYSTEM_TEMPLATE.format(catalog=catalog_prompt(market.allowed_values())),
        user_prompt=f"Contraintes actuelles:\n{current_text}\n\nMessage de l'investisseur:\n« {message} »",
        schema=ExtractionResult,
        tools=make_extraction_tools(market),
        start_text="Lecture de votre demande et rapprochement avec les contraintes disponibles",
        done_text="Demande analysée",
    )

    valid, errors = validate_all(result.constraints, market.allowed_values())
    questions = list(result.clarification_questions) + errors
    if result.unmatched and not questions:
        questions = [f"Je n'ai pas pu appliquer: « {u} ». Pouvez-vous préciser?" for u in result.unmatched]
    return ExtractionOutcome(valid, result.removals, result.unmatched, questions)

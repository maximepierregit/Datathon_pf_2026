"""Juge final (MonPort, profil cohérent): les 3 gestionnaires se font concurrence, un seul portefeuille est présenté.

Le modèle choisit et justifie. Le code garde le dernier mot sur la conformité: voir `monport.pick_winner`.
"""

from __future__ import annotations

import json

from ..events import EventBus
from ..schemas import FinalPick, InvestorProfile, JudgeVerdict, Portfolio
from .base import run_agent

SYSTEM = """Tu es le juge final de MonPort. Trois gestionnaires ont construit chacun un portefeuille pour le même client,
à partir de trois variantes de ses contraintes. Un seul sera présenté au client: tu désignes le meilleur pour lui.

1. La conformité fournie fait foi. Un portefeuille non conforme ne peut gagner que si aucun ne l'est.
2. Compare l'adéquation au profil (niveau de risque, horizon, objectif), la diversification et le rendement
   espéré par unité de risque. Les avis des juges de chaque portefeuille t'aident.
3. `justification`: deux ou trois phrases tutoyées, en français québécois, qui expliquent au client pourquoi ce
   portefeuille l'emporte. Le client débute peut-être: jamais les mots Sharpe, volatilité, écart-type, drawdown ni
   ratio; dis plutôt « le meilleur rendement pour le risque pris » ou « des variations plus douces ». Pas de chiffre
   à plus d'une décimale, et seulement des chiffres fournis."""


async def run_final_judge(
    bus: EventBus,
    profile: InvestorProfile,
    portfolios: list[Portfolio],
    verdicts: dict[str, JudgeVerdict],
) -> FinalPick:
    payload = {
        "profil": {"resume": profile.assessment.summary, "libelle": profile.assessment.risk_label,
                   "horizon_annees": profile.form.horizon_years, "objectif": profile.form.objective},
        "portefeuilles": [
            {
                "slot": p.id,
                "variante": p.mandate,
                "indicateurs": p.metrics.model_dump(exclude={"hhi"}) if p.metrics else None,
                "conforme": verdicts[p.id].compliant if p.id in verdicts else None,
                "note_du_juge": verdicts[p.id].fit_score if p.id in verdicts else None,
                "avis_du_juge": verdicts[p.id].comment if p.id in verdicts else None,
            }
            for p in portfolios
        ],
    }
    return await run_agent(
        bus=bus, label="Juge final", step="8", kind="fast", system_prompt=SYSTEM,
        user_prompt="Désigne le meilleur portefeuille.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        schema=FinalPick, start_text="Comparaison des 3 portefeuilles", done_text="Gagnant désigné",
    )

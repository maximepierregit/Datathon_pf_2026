"""Agent Chief Risk Officer (étape 9): incohérences du profil et mises en garde sur les portefeuilles."""

from __future__ import annotations

import json

from ..events import EventBus
from ..schemas import InvestorProfile, JudgeVerdict, Portfolio, RiskReport
from .base import run_agent

SYSTEM = """Tu es le Chief Risk Officer (CRO) d'un service de conseil en placement canadien. Tu relis le travail de l'équipe
avant sa présentation à l'investisseur. Tu cherches ce qui pourrait lui nuire s'il n'en est pas averti.

1. `profile_inconsistencies`: incohérences internes du profil (ex.: tolérance déclarée très élevée mais perte acceptée
   très faible; horizon court avec objectif de croissance agressive; contraintes qui se contredisent en pratique).
2. `warnings`: mises en garde sur les portefeuilles, avec `portfolio_id`. Appuie-toi sur les indicateurs fournis et sur
   les `diagnostics` calculés par le système (concentration, perte maximale historique comparée à la perte acceptée,
   volatilité, préférences non respectées).
3. `summary`: synthèse courte et directe.

RÈGLES
- Dans le texte, désigne les portefeuilles par le nom de leur mandat (Défensif, Équilibré, Croissance), jamais par leur id.
- Chaque point cite un fait chiffré tiré du contexte. N'invente aucun chiffre.
- Les rendements et risques sont historiques. Ils ne garantissent pas les résultats futurs. Rappelle-le une fois dans le résumé.
- Sois sobre: pas d'alarmisme, pas de recommandation d'achat. Gravité `high` seulement si le problème peut conduire
  l'investisseur à une perte supérieure à ce qu'il accepte ou à un portefeuille inadapté à son horizon.
- S'il n'y a rien à signaler, retourne des listes vides."""


def diagnostics(profile: InvestorProfile, portfolio: Portfolio) -> list[str]:
    """Faits calculés par le code. Le CRO les interprète."""
    m = portfolio.metrics
    if m is None:
        return []
    out = []
    loss = profile.form.max_acceptable_loss_pct
    if loss is not None and abs(m.max_drawdown) * 100 > loss:
        out.append(
            f"La perte maximale historique ({abs(m.max_drawdown):.1%}) dépasse la perte annuelle acceptée ({loss:.0f} %)."
        )
    if loss is not None and m.volatility * 2 * 100 > loss:
        out.append(f"Une baisse de deux écarts-types ({m.volatility * 2:.1%}) dépasse la perte acceptée ({loss:.0f} %).")
    if m.effective_n < 8:
        out.append(f"Diversification limitée: {m.effective_n:.1f} positions effectives sur {m.n_positions}.")
    top_sector, top_w = next(iter(m.sector_weights.items()), (None, 0.0))
    if top_sector and top_w > 0.35:
        out.append(f"Concentration sectorielle: {top_sector} pèse {top_w:.0%}.")
    top_country, top_c = next(iter(m.country_weights.items()), (None, 0.0))
    if top_country and top_c > 0.70:
        out.append(f"Concentration géographique: {top_country} pèse {top_c:.0%}.")
    crypto = sum(w for k, w in m.asset_class_weights.items() if "crypto" in k.lower())
    if crypto > 0.05:
        out.append(f"Exposition aux cryptomonnaies de {crypto:.0%}.")
    if profile.form.horizon_years < 3 and m.volatility > 0.15:
        out.append(f"Horizon de {profile.form.horizon_years} an(s) avec une volatilité de {m.volatility:.1%}.")
    return out


async def run_cro(
    bus: EventBus,
    profile: InvestorProfile,
    portfolios: list[Portfolio],
    verdicts: dict[str, JudgeVerdict],
) -> RiskReport:
    payload = {
        "profil": {
            "formulaire": profile.form.model_dump(mode="json", exclude={"constraints"}),
            "evaluation": profile.assessment.model_dump(),
            "contraintes": [c.model_dump(mode="json") for c in profile.constraints],
        },
        "portefeuilles": [
            {
                "id": p.id,
                "mandat": p.mandate,
                "indicateurs": p.metrics.model_dump() if p.metrics else None,
                "conforme": verdicts[p.id].compliant if p.id in verdicts else None,
                "ecarts": [c.message + " - " + c.label for c in verdicts[p.id].checks if not c.passed]
                if p.id in verdicts else [],
                "avis_du_juge": verdicts[p.id].comment if p.id in verdicts else None,
                "diagnostics": diagnostics(profile, p),
            }
            for p in portfolios
            if p.status == "ok"
        ],
    }
    return await run_agent(
        bus=bus, label="CRO", step="9", kind="strong", system_prompt=SYSTEM,
        user_prompt="Produis ton rapport de risque.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        schema=RiskReport, start_text="Revue des risques et des incohérences du profil", done_text="Rapport de risque prêt",
    )

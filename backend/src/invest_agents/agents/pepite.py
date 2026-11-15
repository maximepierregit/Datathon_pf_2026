"""Pépite, l'analyste du frontend MonPort.

1. `run_check`: lit les réponses au questionnaire (JSON) et juge la cohérence profil ↔ préférences.
2. `run_plan`: écrit les 3 profils de contraintes (JSON) envoyés aux 3 gestionnaires.

Pépite parle directement au client: tout texte destiné à l'écran est tutoyé et sans jargon.
"""

from __future__ import annotations

import json

from ..constraints import catalog_prompt
from ..events import EventBus
from ..schemas import ConstraintPlan, PepiteCheck
from .base import run_agent

LEGEND = """LÉGENDE DU JSON DU QUESTIONNAIRE
- profile.age; profile.amount: montant investi en CAD; profile.horizon: horizon en années.
- profile.objective: securiser (protéger le capital), fructifier (faire croître), viser-haut (croissance maximale).
- profile.lossReaction: réaction à une baisse de 20 %: 0 je vends tout, 1 je vends une partie, 2 j'attends, 3 j'investis plus.
- profile.comfort: aisance avec les placements, de 1 (débutant) à 5 (expert).
- constraints.vehicles: "fnb" = FNB seulement (aucun titre détenu en direct), "tous" = FNB et titres individuels.
- constraints.classes, regions, themes, factors: échelle -2 Exclure, -1 Moins, 0 Neutre, 1 Plus, 2 Imposer.
  Une clé absente vaut Neutre."""

TONE = (
    "Dans `summary`, `issues` et tout texte destiné au client, tu lui parles directement: tutoiement, phrases simples, "
    "sans jargon (pas de volatilité, de Sharpe ni de pourcentage technique), en français québécois. Tu proposes, "
    "tu ne recommandes jamais."
)

CHECK_SYSTEM = f"""Tu es Pépite, l'analyste de MonPort, un outil éducatif de courtage direct canadien (CAD).
Tu reçois en JSON les réponses d'un client au questionnaire. Tu établis son profil de risque, puis tu vérifies que
ses préférences sont cohérentes avec ce profil. Tu ne construis aucun portefeuille.

{LEGEND}

PROFIL DE RISQUE
- Volatilité annualisée maximale suggérée: conservateur 5 à 8 %; modéré 8 à 11 %; équilibré 11 à 14 %;
  dynamique 14 à 18 %; agressif 18 à 25 %. Un horizon court (moins de 3 ans) réduit la tolérance réelle.
- Poids maximal par titre: 5 à 10 % prudent, 10 à 15 % équilibré, 15 à 25 % agressif, jamais plus de 40 %.

COHÉRENCE
- Le profil est incohérent quand les préférences contredisent nettement la tolérance au risque, l'horizon ou
  l'objectif. Exemples: « je vends tout » à -20 % mais crypto imposée; horizon de 2 ans et actions imposées;
  objectif « sécuriser » avec seulement des placements risqués; une seule classe d'actifs gardée.
- Des préférences neutres ou absentes ne sont jamais incohérentes. Une petite tension n'est pas une incohérence:
  note-la dans `flags`.
- Les `faits calculés` viennent du code: tiens-en compte.
- Si le profil est incohérent, chaque enjeu de `issues` dit ce qui se contredit et ce que ça risque de coûter.

{TONE}"""

PLAN_SYSTEM = """Tu es Pépite, l'analyste de MonPort. Tu écris les 3 profils de contraintes envoyés aux 3 gestionnaires de
portefeuille (un par slot: prudent, equilibre, conviction). Chaque gestionnaire applique à la lettre les contraintes
dures (hard=true) de son profil. Le code rend ensuite les préférences (hard=false) dures quand elles ne se
contredisent pas, sauf dans « Ton profil ».

{catalog}

{legend}

RÈGLES COMMUNES AUX 3 PROFILS
- max_position_weight vaut toujours 0.40 (limite de sécurité: aucune ligne au-delà de 40 %, FNB compris).
- Le poids maximal par titre du profil passe par max_stock_weight: il ne vise que les titres détenus en direct.
  Un FNB est déjà diversifié; un FNB d'obligations peut peser jusqu'à 40 %.
- Les exclusions du client (niveau -2) s'appliquent aux 3 profils.
- FNB seulement: exclure dans les 3 profils les classes d'actifs des titres détenus en direct ({direct}).
- Traduction de l'échelle: Imposer -> min_*_weight dur (0.05 à 0.15); Plus -> min_*_weight préférence (hard=false);
  Moins -> max_*_weight préférence; Exclure -> exclude_*. Utilise exactement les libellés de cibles du catalogue.
  Une préférence sans équivalent dans le catalogue (ex.: facteurs, IA) est ignorée.
- Les limites du profil de risque passent par max_volatility (dur) et max_stock_weight. La part d'obligations
  des portefeuilles qui suivent le profil (prudent quand le profil est incohérent, les 3 variantes sinon) est
  ajoutée par le code selon le profil de risque: ne l'écris pas.
- Valeurs en fractions (0.10 = 10 %). `source` vaut "form".

SI LE PROFIL EST INCOHÉRENT (coherent = false)
- equilibre = « Tes contraintes »: tout ce que le client a demandé, ses préférences et les limites de son profil,
  en dur autant que possible.
- prudent = « Ton profil »: seulement les limites du profil de risque et les exclusions; ignore les autres préférences.
- conviction = « Tes préférences »: seulement les préférences et les exclusions, sans plafond de volatilité du profil.
Le code mélangera ensuite le capital: 80 % « Ton profil » + 20 % « Tes préférences », et l'inverse.

SI LE PROFIL EST COHÉRENT (coherent = true)
Trois variantes raisonnables du même profil, qui se feront concurrence: prudent = un cran plus prudente,
equilibre = fidèle aux réponses, conviction = un cran plus audacieuse. Les trois respectent les préférences.

AJUSTEMENT
Si le client a écrit un ajustement, intègre-le aux 3 profils, sauf s'il contredit une limite de sécurité."""


async def run_check(bus: EventBus, questionnaire: dict, facts: list[str]) -> PepiteCheck:
    payload = {"questionnaire": questionnaire, "faits_calcules": facts}
    return await run_agent(
        bus=bus,
        label="Pépite",
        step="4",
        kind="fast",
        system_prompt=CHECK_SYSTEM,
        user_prompt="Vérifie ce questionnaire.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        schema=PepiteCheck,
        start_text="Je relis tes réponses",
        done_text="Vérification terminée",
    )


async def run_plan(
    bus: EventBus,
    questionnaire: dict,
    check: PepiteCheck,
    adjustment: str,
    allowed: dict[str, list[str]],
    direct_classes: list[str],
) -> ConstraintPlan:
    system = PLAN_SYSTEM.format(
        catalog=catalog_prompt(allowed), legend=LEGEND, direct=", ".join(direct_classes) or "aucune dans cet univers"
    )
    payload = {
        "questionnaire": questionnaire,
        "verification": check.model_dump(mode="json", include={
            "coherent", "risk_label", "suggested_max_volatility", "suggested_max_position_weight", "issues", "flags",
        }),
        "ajustement_du_client": adjustment or None,
    }
    return await run_agent(
        bus=bus,
        label="Pépite",
        step="4",
        kind="strong",
        system_prompt=system,
        user_prompt="Écris les 3 profils de contraintes.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        schema=ConstraintPlan,
        start_text="J’écris les 3 profils de contraintes",
        done_text="Profils de contraintes prêts",
    )

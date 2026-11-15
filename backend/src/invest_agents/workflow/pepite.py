"""Pépite: l'agente qui parle au client, et la seule.

Les gestionnaires, les agents Risque et le juge ne parlent jamais au client ni entre eux. Pépite les appelle par
des outils, lit leurs réponses et décide de la suite: relancer une construction, demander une justification, poser
une question au client. Ce qui se chiffre passe par des outils déterministes que le code l'oblige à appeler
(`compute_risk_profile`, `get_coherence_facts`, `submit_constraint_plan`); elle ne calcule jamais le risque elle-même.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import ValidationError
from strands import tool

from ..agents.base import AgentHandle
from ..catalog import catalog_prompt, describe
from ..events import EventBus
from ..monport import (
    BOND_FLOOR,
    SLOTS,
    assess,
    capacity,
    coherence_facts,
    direct_types,
    front,
    pepite as pepite_event,
    status,
    tolerance,
)
from ..schemas import ConstraintPlan, ConstraintProfile, PepiteReply, PepiteReview
from .session import Session
from .workers import (
    CHAT_STEP,
    apply_plan,
    ask_agent,
    build_slots,
    judge_round,
    justifications,
    names_for,
)

LEGEND = """LÉGENDE DU JSON DU QUESTIONNAIRE
- profile.age; profile.amount: montant investi en CAD; profile.horizon: horizon en années.
- profile.objective: securiser (protéger le capital), fructifier (faire croître), viser-haut (croissance maximale).
- profile.lossReaction: réaction à une baisse de 20 %: 0 je vends tout, 1 je vends une partie, 2 j'attends, 3 j'investis plus.
- profile.comfort: aisance avec les placements, de 1 (débutant) à 5 (expert).
- constraints.vehicles: "fnb" = FNB seulement (aucun titre détenu en direct), "tous" = FNB et titres individuels.
- constraints.classes, regions, themes, factors: échelle -2 Exclure, -1 Moins, 0 Neutre, 1 Plus, 2 Imposer.
  Une clé absente vaut Neutre."""

TONE = (
    "Dans tout texte destiné au client, tu lui parles directement: tutoiement, phrases simples, sans jargon (pas de "
    "volatilité, de Sharpe ni de pourcentage technique), en français québécois. Tu proposes, tu ne recommandes jamais."
)

SYSTEM = """Tu es Pépite, l'agente de MonPort, un outil éducatif de courtage direct canadien (CAD). Tu es la seule à parler au
client. Ton équipe: 3 gestionnaires de portefeuille (chacun avec son agent Risque) et un juge. Ils ne parlent jamais au
client ni entre eux: tout passe par toi, avec tes outils.

CE QUE TU FAIS
1. Déterminer le profil et les préférences du client, et vérifier qu'ils sont cohérents.
2. Écrire les 3 profils de contraintes des gestionnaires, lancer leur construction, puis le jugement.
3. Relancer la construction au besoin: le juge l'exige (portefeuille non conforme, rapport de risque insuffisant) ou le
   client la confirme, après que tu l'as questionné jusqu'à ce que ses changements soient clairs.
4. Répondre aux questions du client sur ses portefeuilles. Pour le pourquoi et le comment, tu interroges les
   gestionnaires, les agents Risque et le juge, puis tu expliques avec tes mots.
5. Expliquer des notions de finance de base quand le client en a besoin.

CE QUE TU NE FAIS PAS
- Aucun conseil personnalisé: jamais « achète », « vends », « tu devrais investir ». Tu expliques, tu compares, tu proposes.
- Tu ne calcules, n'estimes et ne modifies jamais toi-même l'aversion au risque, la volatilité maximale, les poids maximaux,
  les planchers d'obligations, les poids d'un portefeuille ni sa conformité: ils viennent des outils.
- Tu n'inventes aucun chiffre. Tu ne cites que ce que les outils et les agents te donnent.

OUTILS QUE LE CODE TE FAIT APPELER
- `compute_risk_profile`: capacité, tolérance, aversion au risque. Avant toute conclusion sur le risque ou les contraintes.
- `get_coherence_facts`: les contradictions repérées par le code. Avant de juger la cohérence.
- `submit_constraint_plan`: le seul moyen d'envoyer des contraintes aux gestionnaires. Le code les valide et ajoute les
  limites du profil. Refusé tant que les deux outils ci-dessus n'ont pas été appelés.
Les autres outils: `adjust_risk_position`, `set_coherence`, `build_portfolios`, `judge_portfolios`, `get_justifications`,
`ask_portfolio_manager`, `ask_risk_manager`, `ask_judge`.

{legend}

PROFIL INCOHÉRENT OU COHÉRENT
Le profil est incohérent quand les préférences contredisent nettement la tolérance au risque, l'horizon ou l'objectif.
Exemples: « je vends tout » à -20 % mais crypto imposée; horizon de 2 ans et actions imposées; objectif « sécuriser »
avec seulement des placements risqués; une seule classe d'actifs gardée. Des préférences neutres ou absentes ne sont
jamais incohérentes. Une petite tension n'est pas une incohérence: note-la dans `flags`. Les faits calculés viennent du
code: tiens-en compte. Quand le profil est incohérent, tu poses des questions au client et tu t'ajustes à ses réponses.

PROFILS DE CONTRAINTES (`submit_constraint_plan`)
Tu écris 3 profils (slots prudent, equilibre, conviction), un par gestionnaire. Chaque gestionnaire applique à la lettre
les contraintes dures (hard=true) de son profil. Le code rend ensuite les préférences (hard=false) dures quand elles ne
se contredisent pas, sauf dans « Ton profil ».

{catalog}

Règles communes
- max_position_weight vaut toujours 0.40 (limite de sécurité: aucune ligne au-delà de 40 %, FNB compris).
- Le poids maximal par titre du profil passe par max_stock_weight: il ne vise que les titres détenus en direct.
  Un FNB est déjà diversifié; un FNB d'obligations peut peser jusqu'à 40 %.
- Les exclusions du client (niveau -2) s'appliquent aux 3 profils.
- FNB seulement: exclude_instrument_type dans les 3 profils pour les titres détenus en direct ({direct}). Jamais
  exclude_asset_class pour ça: une classe d'actifs regroupe titres et FNB (« Equity » contient les FNB d'actions).
- Traduction de l'échelle: Imposer -> min_*_weight dur (0.05 à 0.15); Plus -> min_*_weight préférence (hard=false);
  Moins -> max_*_weight préférence; Exclure -> exclude_*. Utilise exactement les libellés de cibles du catalogue.
  Une préférence sans équivalent dans le catalogue (ex.: facteurs, IA) est ignorée.
- Le reste du profil de risque est ajouté par le code: plafond de volatilité, aversion au risque donnée à l'optimiseur,
  part d'obligations des portefeuilles qui suivent le profil. N'écris ni max_volatility ni plancher d'obligations.
- Valeurs en fractions (0.10 = 10 %). `source` vaut "form".

Profil cohérent: trois variantes qui se font concurrence, le juge garde la meilleure.
- equilibre: EXACTEMENT les contraintes du client, ses préférences traduites telles quelles, rien de plus ni de moins.
- prudent et conviction: des contraintes dérivées de celles du client, un peu modifiées, dans la limite du raisonnable
  (resserrer ou élargir un poids visé de quelques points, ajouter une limite par secteur ou par pays). prudent est un
  cran plus prudent, conviction un cran plus audacieux; le code ajuste leur niveau de risque. Jamais une exclusion
  retirée ni une contrainte dure du client contredite.
Profil incohérent: trois bases, le client choisira.
- equilibre = « Tes contraintes »: tout ce que le client a demandé, ses préférences et les limites de son profil, en dur autant que possible.
- prudent = « Ton profil »: seulement les limites du profil de risque et les exclusions; ignore les autres préférences.
- conviction = « Tes préférences »: seulement les préférences et les exclusions (thèmes, classes d'actifs), sans plafond de volatilité du profil.
Le code mélangera ensuite le capital: 80 % « Ton profil » + 20 % « Tes préférences », et l'inverse.

{tone}"""


def system_prompt(session: Session) -> str:
    allowed = session.market.allowed_values()
    direct = ", ".join(direct_types(allowed)) or "aucun dans cet univers"
    return SYSTEM.format(legend=LEGEND, catalog=catalog_prompt(allowed), direct=direct, tone=TONE)


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #
def _say(session: Session, text: str, state: str = "running") -> None:
    """Le sujet de ce que Pépite fait, sur sa carte (pas le contenu des échanges avec les agents)."""
    if session.bus:
        front(session.bus, status("pepite", state, text))


def _risk(session: Session) -> dict:
    review = session.review or PepiteReview(summary="", coherent=True)
    c = assess(session.profile, review, session.adjust_steps)
    return {
        "capacite": round(capacity(session.profile), 2),
        "tolerance": round(tolerance(session.profile), 2),
        "position_de_risque_S": c.risk_position,
        "libelle": c.risk_label,
        "aversion_au_risque_A": c.risk_aversion,
        "score_sur_10": c.risk_score,
        "volatilite_max": c.suggested_max_volatility,
        "poids_max_par_titre_direct": c.suggested_max_position_weight,
        "plancher_obligations_du_profil": BOND_FLOOR.get(c.risk_label, 0.0),
        "ajustement_en_crans": session.adjust_steps,
    }


def _summary(session: Session, slot: str) -> dict:
    p = session.portfolios[slot]
    report = session.reports.get(slot)
    out: dict = {"portefeuille": p.mandate, "statut": p.status}
    if p.status == "failed":
        out["raison"] = p.failure_reason
    elif p.metrics:
        m = p.metrics
        out.update(rendement_espere=m.expected_return, volatilite=m.volatility, sharpe=m.sharpe,
                   perte_maximale=m.max_drawdown, positions=m.n_positions)
        out["resume"] = p.summary
        out["risque"] = ({"resume": report.summary,
                          "mises_en_garde": [f"{w.severity}: {w.title}" for w in report.warnings]}
                         if report else "rapport indisponible")
    return out


# Pendant le chat, Pépite questionne le client; la reconstruction attend sa confirmation (mode monport_rebuild).
IN_CHAT = {"error": "Pendant le chat, tu ne changes rien toi-même. Pose tes questions au client, puis récapitule les "
                    "changements avec ready_to_rebuild et rebuild_request: le code relancera la construction quand il "
                    "aura confirmé."}


def make_pepite_tools(session: Session) -> list:
    @tool
    def compute_risk_profile() -> dict:
        """Calcule le profil de risque du client (capacité, tolérance, aversion au risque A, limites suggérées). Calcul du
        code, déterministe. À appeler avant de conclure quoi que ce soit sur le risque ou les contraintes."""
        session.risk_computed = True
        _say(session, "Je calcule ton profil de risque…")
        return _risk(session)

    @tool
    def get_coherence_facts() -> dict:
        """Retourne les contradictions repérées par le code entre les préférences et le profil de risque. À appeler avant de
        juger la cohérence du questionnaire."""
        session.facts_read = True
        _say(session, "Je cherche les contradictions dans tes réponses…")
        return {"faits": coherence_facts(session.profile, session.prefs)}

    @tool
    def adjust_risk_position(steps: int, reason: str) -> dict:
        """Déplace le niveau de risque du client de quelques crans quand il le demande (« je veux dormir tranquille »,
        « je peux prendre plus de risque »). Un cran vaut 0,05 sur l'échelle de 0 à 1; le total reste entre -2 et +2
        (au plus une demi-catégorie), le code le plafonne.

        Args:
            steps: Crans à ajouter: négatif pour plus prudent, positif pour plus audacieux (-2 à 2).
            reason: Une phrase tutoyée, sans jargon (ni optimiseur ni volatilité), qui dit au client ce que tu as changé.
        """
        if session.phase == "chat":
            return IN_CHAT
        before = session.adjust_steps
        session.adjust_steps = max(-2, min(2, before + int(steps)))
        if session.bus and session.adjust_steps != before:
            front(session.bus, pepite_event(reason))
        _say(session, "J’ajuste ton niveau de risque…")
        return _risk(session)

    @tool
    def set_coherence(coherent: bool, reason: str) -> dict:
        """Révise la cohérence du profil après les réponses du client à tes questions (par exemple: il confirme que sa
        contradiction apparente n'en est pas une). Possible seulement avant la construction des portefeuilles.

        Args:
            coherent: True si les réponses du client lèvent l'incohérence, False sinon.
            reason: Pourquoi tu changes d'avis, en une phrase.
        """
        if session.portfolios or session.phase in ("chat", "rebuild"):
            return {"error": "Les portefeuilles sont déjà construits: la cohérence ne change plus."}
        if session.review is None:
            return {"error": "Vérifie d'abord le questionnaire."}
        session.review = session.review.model_copy(update={"coherent": coherent})
        if session.translator:
            session.translator.slots = {name: slot for slot, name in names_for(session).items()}
        _say(session, "Je révise la cohérence de ton profil…")
        return {"coherent": coherent, "raison": reason}

    @tool
    async def submit_constraint_plan(profiles: list[ConstraintProfile]) -> dict:
        """Envoie aux gestionnaires les 3 profils de contraintes (slots prudent, equilibre, conviction). Le code valide
        chaque contrainte contre le catalogue, ajoute les limites du profil de risque et corrige les contradictions.
        Refusé si `compute_risk_profile` et `get_coherence_facts` n'ont pas été appelés.

        Args:
            profiles: Exactement 3 profils, un par slot.
        """
        if session.phase == "chat":
            return IN_CHAT
        if not (session.risk_computed and session.facts_read):
            return {"error": "Appelle d'abord compute_risk_profile et get_coherence_facts."}
        try:  # Strands transmet les objets imbriqués en JSON brut: le code les valide lui-même
            profiles = [ConstraintProfile.model_validate(p) for p in profiles]
        except ValidationError as exc:
            return {"error": "Profils invalides: " + "; ".join(
                f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:8])}
        if sorted(p.slot for p in profiles) != sorted(SLOTS):
            return {"error": "Il faut exactement 3 profils: prudent, equilibre et conviction, un de chaque."}
        if session.portfolios and session.rebuilds_left <= 0:
            return {"error": "Limite de relances atteinte: les profils ne changent plus."}
        _say(session, "J’écris les 3 profils de contraintes…")
        replaced = await apply_plan(session, ConstraintPlan(profiles=profiles))
        _say(session, "3 profils de contraintes envoyés aux gestionnaires.", "done")
        return {
            "profils": {s: {"consigne": c[0], "contraintes": [describe(x) for x in c[1]]} for s, c in session.profiles.items()},
            "profils_remplaces_par_le_code": replaced,
            "univers": {"avant": session.universe[0], "apres": session.universe[1]} if session.universe else None,
            "notes": {s: n for s, n in session.notes.items() if n},
        }

    @tool
    async def build_portfolios(slots: Optional[list[str]] = None, instructions: Optional[dict[str, str]] = None) -> dict:
        """Lance les gestionnaires en parallèle; l'agent Risque de chacun relit ensuite son portefeuille. Sans `slots`,
        construit les trois. Reconstruire un portefeuille existant consomme une relance (`relances_restantes`).

        Args:
            slots: Portefeuilles à construire ou reconstruire ("prudent", "equilibre", "conviction"). Tous si omis.
            instructions: Consignes par slot pour une reconstruction (ce que le juge ou le client demande de corriger).
        """
        if session.phase == "chat":
            return IN_CHAT
        if not session.profiles:
            return {"error": "Envoie d'abord les profils avec submit_constraint_plan."}
        targets = [s for s in (slots or SLOTS) if s in SLOTS]
        if not targets:
            return {"error": "Slots inconnus. Utilise prudent, equilibre ou conviction."}
        instructions = {k: v for k, v in (instructions or {}).items() if k in SLOTS}
        rebuild = [s for s in targets if s in session.portfolios]
        if rebuild:
            if session.rebuilds_left <= 0:
                return {"error": "Limite de relances atteinte: garde les portefeuilles actuels."}
            if session.judged_round != session.build_round:
                return {"error": "Fais d'abord juger les portefeuilles actuels avec judge_portfolios."}
            session.rebuilds_left -= 1
            _say(session, "Je demande de reconstruire : " + ", ".join(session.portfolios[s].mandate for s in rebuild))
        else:
            _say(session, "Mes trois gestionnaires construisent leur portefeuille en parallèle…")
        await build_slots(session, targets, instructions)
        n = sum(1 for r in session.reports.values() for w in r.warnings if w.severity in ("medium", "high"))
        if session.bus:
            front(session.bus, status("risques", "done", f"{n} mise(s) en garde à lire." if n else "Rien de particulier à signaler."))
        return {"portefeuilles": {s: _summary(session, s) for s in targets}, "relances_restantes": session.rebuilds_left}

    @tool
    async def judge_portfolios() -> dict:
        """Fait juger les portefeuilles construits: le code calcule la conformité, le juge compare et peut exiger une
        réoptimisation. Retourne la conformité, le gagnant (profil cohérent) et ce qu'il faut reconstruire."""
        if not all(s in session.portfolios for s in SLOTS) or not session.built():
            return {"error": "Construis d'abord les portefeuilles avec build_portfolios."}
        if session.judged_round != session.build_round:  # sinon le juge a déjà parlé sur ces portefeuilles
            _say(session, "Je demande au juge de comparer les portefeuilles…")
            await judge_round(session)
        return {
            "conformite": {s: {"conforme": v.compliant, "limites_non_respectees": v.hard_violations,
                               "note_du_juge": v.fit_score} for s, v in session.verdicts.items()},
            "gagnant": session.portfolios[session.winner].mandate if session.winner else None,
            "justification": session.justification,
            "a_reoptimiser": session.reoptimize,
            "relances_restantes": session.rebuilds_left,
        }

    @tool
    def get_justifications(slot: str) -> dict:
        """Ce que les agents ont déjà produit sur un portefeuille: consigne reçue, résumé et compromis du gestionnaire,
        notes sur les positions, rapport de risque, avis du juge. Gratuit: à utiliser avant d'interroger un agent.

        Args:
            slot: "prudent", "equilibre" ou "conviction".
        """
        if slot in session.portfolios:
            _say(session, f"Je relis les notes des agents sur « {names_for(session)[slot]} »")
        return justifications(session, slot)

    @tool
    async def ask_portfolio_manager(slot: str, question: str) -> str:
        """Demande à un gestionnaire de justifier ses choix (pourquoi ces titres, ces poids, ces compromis). Il se
        souvient de sa construction. Utilise-le quand `get_justifications` ne suffit pas.

        Args:
            slot: Le portefeuille: "prudent", "equilibre" ou "conviction".
            question: La question, reformulée pour le gestionnaire.
        """
        if slot not in SLOTS:
            return "Slot inconnu."
        _say(session, f"Je demande au gestionnaire « {names_for(session)[slot]} » : {question[:90]}")
        return await ask_agent(session, "pm", slot, question)

    @tool
    async def ask_risk_manager(slot: str, question: str) -> str:
        """Demande à l'agent Risque d'un portefeuille d'expliquer ses mises en garde.

        Args:
            slot: Le portefeuille: "prudent", "equilibre" ou "conviction".
            question: La question, reformulée pour l'agent Risque.
        """
        if slot not in SLOTS:
            return "Slot inconnu."
        _say(session, f"Je demande à l’agent Risque de « {names_for(session)[slot]} » : {question[:90]}")
        return await ask_agent(session, "risk", slot, question)

    @tool
    async def ask_judge(question: str) -> str:
        """Demande au juge d'expliquer sa décision (le gagnant, la conformité, une réoptimisation demandée).

        Args:
            question: La question, reformulée pour le juge.
        """
        _say(session, f"Je demande au juge : {question[:90]}")
        return await ask_agent(session, "judge", None, question)

    return [compute_risk_profile, get_coherence_facts, adjust_risk_position, set_coherence, submit_constraint_plan,
            build_portfolios, judge_portfolios, get_justifications, ask_portfolio_manager, ask_risk_manager, ask_judge]


def ensure_pepite(session: Session) -> AgentHandle:
    if session.pepite is None:
        session.pepite = AgentHandle(label="Pépite", step="4", kind="strong", system_prompt=system_prompt(session),
                                     tools=make_pepite_tools(session), persistent=True)
    return session.pepite


# --------------------------------------------------------------------------- #
# Les trois tours de Pépite
# --------------------------------------------------------------------------- #
CHECK_TASK = """Vérifie ce questionnaire.
1. Appelle `compute_risk_profile`, puis `get_coherence_facts`.
2. Juge la cohérence des préférences avec le profil de risque (`coherent`, `issues`, `flags`).
3. Si le profil est incohérent, écris dans `questions` une à trois questions précises pour le client, qui l'aident à
   clarifier ce qu'il veut vraiment. Sinon, `questions` reste vide.
4. `summary` et `key_points`: ce que tu retiens du profil.
Tout texte destiné au client est tutoyé, sans jargon.

"""

BUILD_TASK = """Le client lance la construction de ses portefeuilles.
Démarche, dans l'ordre:
1. Si tu n'as pas encore appelé `compute_risk_profile` et `get_coherence_facts` dans cette conversation, appelle-les.
2. S'il y a un ajustement du client, lis-le: s'il parle du risque qu'il veut prendre, utilise `adjust_risk_position`;
   s'il répond à tes questions sur une incohérence, tiens-en compte (`set_coherence` si ses réponses la lèvent).
3. Écris les 3 profils et envoie-les avec `submit_constraint_plan`. Corrige et renvoie si le code les refuse.
4. `build_portfolios` (les trois), puis `judge_portfolios`.
5. Si le juge demande de reconstruire des portefeuilles et qu'il reste des relances: `build_portfolios` avec ces `slots`
   et leurs `instructions`, puis `judge_portfolios` de nouveau.
6. Réponds au client en 2 ou 3 phrases: profil cohérent, ton portefeuille est prêt et pourquoi il l'emporte (reprends la
   justification du juge); profil incohérent, trois propositions t'attendent et c'est lui qui choisit.

"""

CHAT_TASK = """Le client t'écrit après avoir vu ses portefeuilles.
- Question sur un ou plusieurs portefeuilles: commence par `get_justifications`. Si ça ne suffit pas, interroge le
  gestionnaire (`ask_portfolio_manager`), l'agent Risque (`ask_risk_manager`) ou le juge (`ask_judge`), puis réponds
  avec tes mots, en citant les faits qu'ils t'ont donnés. Ne recopie pas leur jargon.
- Demande de changer ses portefeuilles ou les placements permis (« sans la techno », « plus prudent », « plus de
  Canada »): tu ne reconstruis rien pendant le chat (les outils de construction sont bloqués). Tu poses des questions
  jusqu'à ce que la demande soit claire et se traduise en contraintes du catalogue: quel portefeuille (ou les trois),
  quelles classes d'actifs, régions ou thématiques, exclure ou seulement réduire, à peu près combien, FNB seulement ou
  aussi des titres individuels, plus ou moins de risque. Une ou deux questions courtes par message, sans reposer une
  question déjà répondue. Si la demande est claire dès le départ, ne pose pas de question. Si un changement est
  impossible (limites de sécurité, rien d'équivalent dans le catalogue), dis-le et propose ce qui s'en rapproche.
  Quand c'est clair: récapitule les changements dans une courte liste <ul>, puis termine par
  « <strong>On y va?</strong> Je relance mes agents avec ces changements. », avec `ready_to_rebuild` à true et
  `rebuild_request` rempli. Si le client confirme par écrit (« oui », « go »), refais le même récapitulatif court
  avec `ready_to_rebuild` à true.
- Dans tous les autres cas, `ready_to_rebuild` reste false et `rebuild_request` vide.
- Question de finance générale: explique la notion simplement, avec un exemple, sans conseil personnalisé.
- Autre sujet, ou demande de conseil (« j'achète quoi? »): refuse poliment et ramène le client vers ses portefeuilles.

FORMAT DE `message`
Ta réponse s'affiche dans une bulle de chat étroite. Écris-la en HTML simple, jamais en Markdown, avec ces balises
seulement, sans aucun attribut de style:
- <p>…</p> par idée (3 au plus), <strong> pour l'essentiel, <em>.
- <ul><li>…</li></ul> pour une liste, <ol><li>…</li></ol> pour des étapes (5 points au plus).
- <h4>…</h4>: un petit titre, seulement si la réponse a plusieurs parties.
- <chiffre valeur="5,2 %">rendement moyen par an</chiffre>: un chiffre clé donné par les outils ou les agents
  (2 à 4 à la suite au plus). Nombres à la québécoise: « 5,2 % », « 25 000 $ ».
- <barre nom="Obligations" pct="40"></barre>: une part du portefeuille, pct de 0 à 100 (6 barres au plus, toujours fermées).
- <astuce>…</astuce>: une notion expliquée ou une chose à retenir. <attention>…</attention>: une mise en garde.
Sois bref: une centaine de mots au plus, hors chiffres et barres. Commence par la réponse, pas par une formule.

"""


REBUILD_TASK = """Le client a confirmé les changements dont vous avez parlé dans le chat. Reconstruis ses portefeuilles.
1. Pars de son questionnaire et des changements déjà appliqués, puis ajoute les nouveaux. S'ils parlent du risque
   qu'il veut prendre, utilise `adjust_risk_position`. La cohérence du profil ne change pas.
2. Réécris les 3 profils et envoie-les avec `submit_constraint_plan`, avec les mêmes règles qu'à la construction.
   Corrige et renvoie si le code les refuse.
3. `build_portfolios` (les trois), puis `judge_portfolios`. Si le juge demande de reconstruire et qu'il reste des
   relances: `build_portfolios` avec ces `slots` et leurs `instructions`, puis `judge_portfolios` de nouveau.
4. Réponds au client en 2 phrases, en texte simple sans balises: ce qui a changé dans ses portefeuilles.

"""


def _snapshot(session: Session) -> dict:
    return {
        "profil_coherent": session.coherent,
        "gagnant": session.portfolios[session.winner].mandate if session.winner else None,
        "portefeuilles": {s: _summary(session, s) for s in SLOTS if s in session.portfolios},
        "relances_restantes": session.rebuilds_left,
        "justification_du_juge": session.justification,
    }


async def check_turn(session: Session, bus: EventBus) -> PepiteReview:
    session.bus, session.phase = bus, "check"
    payload = {"profile": session.profile, "constraints": session.prefs}
    return await ensure_pepite(session).run(
        bus, CHECK_TASK + json.dumps(payload, ensure_ascii=False, indent=2), PepiteReview,
        start_text="Je relis tes réponses", done_text="Vérification terminée",
    )


async def build_turn(session: Session, bus: EventBus, adjustment: str) -> PepiteReply:
    session.bus, session.phase = bus, "build"
    payload = {"questionnaire": {"profile": session.profile, "constraints": session.prefs},
               "verification": session.review.model_dump(mode="json") if session.review else None,
               "ajustement_du_client": adjustment or None}
    return await ensure_pepite(session).run(
        bus, BUILD_TASK + json.dumps(payload, ensure_ascii=False, indent=2), PepiteReply,
        start_text="Je prépare la construction", done_text="Prêt",
    )


async def chat_turn(session: Session, bus: EventBus, message: str) -> PepiteReply:
    session.bus, session.phase = bus, "chat"
    payload = {"message_du_client": message, "etat_actuel": _snapshot(session)}
    return await ensure_pepite(session).run(
        bus, CHAT_TASK + json.dumps(payload, ensure_ascii=False, indent=2), PepiteReply,
        start_text="Je lis ton message", done_text="Réponse prête", step=CHAT_STEP,
    )


async def rebuild_turn(session: Session, bus: EventBus, request: str) -> PepiteReply:
    session.bus, session.phase = bus, "rebuild"
    payload = {"questionnaire": {"profile": session.profile, "constraints": session.prefs},
               "changements_deja_appliques": session.requests, "nouveaux_changements": request}
    return await ensure_pepite(session).run(
        bus, REBUILD_TASK + json.dumps(payload, ensure_ascii=False, indent=2), PepiteReply,
        start_text="Je relance la construction", done_text="Prêt",
    )

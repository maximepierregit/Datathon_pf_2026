# CLAUDE.md

Ce fichier guide les agents de code qui travaillent dans `backend/`. Il décrit ce qui existe, pourquoi, et les règles à ne pas casser. Le `CLAUDE.md` de la racine décrit le produit (MonPort), le ton et le frontend.

## Projet

Pipeline multi-agents qui propose 3 portefeuilles (Prudent, Équilibré, Conviction) au frontend MonPort. Stack: **Strands Agents** + **Amazon Bedrock** (Claude), hébergé sur **Bedrock AgentCore Runtime**. Le frontend (`../frontend`, servi par nginx sur EC2) envoie un JSON et reçoit un flux SSE.

**Le contrat du frontend fait foi**: `../frontend/src/types.ts` (`Profile`, `Constraints`, `Portfolio`, `PipelineEvent`, `AdjustProposal`). Le backend s'y adapte, pas l'inverse. Détail complet dans `README.md`, section « Contrat du frontend ».

## Commandes

```bash
# Installation (Python 3.12 en local; le runtime AgentCore utilise 3.13)
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .

# Dataset synthétique (le vrai dataset n'est pas dans le repo; backend/data/ est ignoré par git)
.venv/bin/python scripts/make_sample_dataset.py

# Contrat du frontend en local (appelle Bedrock)
.venv/bin/python scripts/run_web.py                                    # pipeline, ~70 s
.venv/bin/python scripts/run_web.py --adjust "pas de pétrole"          # ajustement, ~45 s (lit data/last_web_result.json)
.venv/bin/python scripts/run_web.py --portfolio conviction --adjust "plus de crypto"
.venv/bin/python scripts/run_web.py --raw                              # PipelineEvent bruts

# Contrat interne (formulaire InvestorForm, relance conversationnelle)
.venv/bin/python scripts/run_local.py

# Serveur AgentCore local. Le port 8080 est pris par l'IDE dans cet environnement: utiliser PORT.
PORT=8091 .venv/bin/python main.py
curl -sN localhost:8091/invocations -H "Content-Type: application/json" -d '{"mode":"pipeline","profile":{...},"constraints":{...}}'

# Paquet de déploiement (arm64, Python 3.13) -> build/deployment_package.zip (~127 Mo, limite 250 Mo)
./scripts/build_package.sh
```

Aucune suite de tests. La validation se fait avec `run_web.py` et des scripts ponctuels sur `contract.mandate_constraints`, `contract.make_feasible` et `optimizer.optimize` (rapides, sans LLM).

## Architecture

```
main.py                       Point d'entrée AgentCore; aiguille selon `mode`
src/invest_agents/
  web_pipeline.py             mode "pipeline": flux du frontend + traduction en PipelineEvent
  web_adjust.py               mode "adjust": agent Pépite (texte -> patch de préférences) + 1 portefeuille recalculé
  contract.py                 Modèles du frontend, risk_score, préférences -> contraintes, faisabilité, sortie Portfolio
  classify.py                 Classe, région, thèmes, facteurs, frais de chaque actif
  mandates.py                 Prudent, Équilibré, Conviction (id = PortfolioId du frontend)
  selection.py                Sélection déterministe (repli des PM, test de faisabilité)
  orchestrator.py             modes "initial"/"refine": contrat interne (InvestorForm, extraction, clarification)
  agents/base.py              run_agent(): Agent Strands + sortie structurée + statuts start/done/error
  agents/profile.py           Formulaire -> ProfileAssessment (vol max et poids max suggérés)
  agents/portfolio_manager.py Sélection des titres via outils; l'optimiseur calcule les poids
  agents/judge.py             Un juge par portefeuille; conformité recalculée par le code
  agents/cro.py               Incohérences du profil + mises en garde; diagnostics() calculés par le code
  agents/extraction.py        Texte libre -> contraintes du catalogue (contrat interne)
  constraints.py              Catalogue, validation, fusion, conflits, evaluate() (code pur)
  optimizer.py                Moyenne-variance sous contraintes (scipy SLSQP)
  tools.py                    Outils Strands, liés par closure au contexte de chaque agent
  data.py                     Chargement Parquet (local ou s3://), Market.members/groups, moments, métriques
  events.py                   EventBus (asyncio.Queue) + callback handler Strands
  models.py, schemas.py, config.py
```

### Flux du mode "pipeline"

```
Éclaireur    Profil (agent, en cache par profil) ▶ exclusions globales ▶ universe {before, after}
Compositeur  pour chaque mandat: mandate_constraints() ▶ make_feasible() ▶ PM (3 en parallèle)
Vérificateur 3 Juges ▶ rerun + nouvel essai des non conformes (MAX_PM_RETRIES) ▶ CRO ▶ warning
             ▶ portfolios ▶ pepite ▶ done
```

`to_frontend_event()` traduit les événements internes: `step` donne l'agent du frontend (`4` Éclaireur, `5` Compositeur, `8`/`9` Vérificateur). Les fins d'agents individuels restent `running`; seule la fin d'étape émise par le pipeline passe à `done`. `dedupe()` retire les statuts répétés. Les événements propres au frontend passent par `bus.emit("fe", event={...})`.

## Règles de conception (invariants)

1. **Les agents proposent, le code garantit.** Poids, métriques et conformité viennent de `optimizer.optimize`, `Market.portfolio_metrics` et `constraints.evaluate`. Ne jamais faire produire un chiffre par un modèle.
2. **Une contrainte dure est intouchable par un agent.** Les outils PM reçoivent les contraintes par closure (`PMState`); le modèle ne choisit que des symboles. L'optimiseur revérifie son résultat avec `evaluate()`.
3. **`JudgeVerdict.compliant` est calculé par le code**, jamais par le modèle.
4. **Les contraintes `source="safety"` ne sont jamais assouplies**: ligne ≤ 40 %, au moins 3 placements, crypto ≤ 20 %, chaque action individuelle ≤ plafond du profil. Elles reprennent les limites du `CLAUDE.md` racine.
5. **Aucun état serveur.** Le frontend renvoie profil et préférences à chaque appel. Seul le résultat de l'agent Profil est mis en cache dans le processus (`web_pipeline._ASSESSMENTS`), car il ne dépend que du profil.
6. **Le pipeline ne plante pas sur un agent.** PM en échec: `fallback_selection()`. Juge en échec: verdict calculé par le code. CRO en échec: pas de mises en garde du CRO, le reste continue.
7. **Le texte client suit le ton du produit**: `LANGUAGE_RULE` (agents/base.py) impose français québécois, tutoiement, « proposition, pas une recommandation ». Les textes fixes (`pepite`, `agent_status`, notes) suivent la typographie du `CLAUDE.md` racine (`’`, « », pas d'espace avant `?` et `!`).

## Copies du frontend à garder synchronisées

| Backend | Frontend |
|---|---|
| `contract.risk_score` | `riskScore` (lib/engine.ts) |
| `contract.strategic_weights` | `classWeights` sans préférences (lib/engine.ts) |
| `contract.coherence_warnings` | `coherenceWarnings` (lib/engine.ts) |
| `mandates.MANDATES` (`name`, `tagline`, `score_shift`) | `PORTFOLIO_META`, décalages de `classWeights` |
| `contract.CLASS_LABELS`, `REGION_LABELS`, `THEME_LABELS`, `FACTOR_LABELS` | `CLASS_LABELS`, `BLOCKS` (data/catalog.ts) |
| `classify.CLASS_PRIOR_MU` | `CLASS_ASSUMPTIONS[*].mu` (data/catalog.ts) |
| Formules `worstYear`, `var95`, `es95` dans `to_frontend_portfolio` | `metricsOf` (lib/engine.ts) |
| `RISK_FREE_RATE=0.025` | `0.025` dans `metricsOf` et `KpiRow` |

## Préférences -> contraintes (`contract.py`)

- Classes: bande `[0,8 ; 1,2] × répartition stratégique du mandat` (source `mandate`). Moins: plafond abaissé. Plus/Imposer: plancher relevé (`_CLASS_PLUS`, `_CLASS_IMPOSE`). Prudent ignore Plus/Imposer sur les classes risquées et l'écrit dans les notes.
- Régions, thèmes, facteurs: `_GROUP_LEVELS[mandat][niveau]` donne le poids minimal (Plus, Imposer) ou maximal (Moins).
- Exclure (−2) et `vehicles: "fnb"`: `global_exclusions()`, communes aux 3 mandats.
- Prudent ajoute un plancher de rendement (`rf + 1 %`), sinon `min_volatility` retient des placements qui ne rapportent rien.
- `make_feasible()`: test avec `default_selection()` + `optimize()`. Si impossible, assouplit (passe en `hard=False`) dans l'ordre: source (`_RELAX_ORDER`), minimums avant plafonds, facteurs → thèmes → régions → classes → rendement. Puis rétablit chaque contrainte assouplie qui n'était pas nécessaire. Dernier recours: retire le plafond de volatilité du mandat.

## Mandats

| id | Objectif | Plafond de vol. | `score_shift` |
|---|---|---|---|
| prudent | `min_volatility` + plancher de rendement | aucun | −20 |
| equilibre | `max_sharpe` | 1,0 × vol max du profil | 0 |
| conviction | `max_return` | 1,3 × vol max du profil | +10 |

## Classement de l'univers (`classify.py`)

- `Market.assets["asset_class"]` contient les classes **du frontend** (actions, obligations, immobilier, or, crypto, liquidites). La classe brute du notebook est dans `asset_class_raw`.
- `region`: canada, usa, europe, asie, emergents, ou `monde` (FNB mondiaux) / `aucune` (hors actions et immobilier). Ces deux valeurs ne sont pas des groupes (`NOT_A_GROUP`).
- `themes` et `factors` sont des ensembles encodés `|a|b|`; `Market.members()` gère l'appartenance.
- `CASH-CAD` est ajouté au marché (rendement = taux sans risque, vol nulle).
- Toute dimension de contrainte passe par `Market.members(dimension, target)` et `Market.groups(dimension)`. Ne pas comparer des colonnes à la main.

## Contraintes

- Types dans `schemas.ConstraintType`; métadonnées dans `constraints.SPECS`. Ajouter un type = l'ajouter aux deux, puis gérer son cas dans `evaluate()`, `optimize()` et `describe()`.
- Valeurs en **fractions** (0.10 = 10 %). `hard=False`: préférence, évaluée seulement.
- `source`: `form`, `chat`, `profile` (contrat interne), `preference`, `mandate`, `safety` (contrat du frontend).
- Cible `*`: « chaque secteur / pays / région » pour les plafonds.
- `MAX_INSTRUMENT_LINE_WEIGHT` est appliqué dans les bornes de l'optimiseur, pas comme contrainte de groupe.

## Optimiseur et données

- Objectifs: `min_volatility`, `max_sharpe`, `max_return` (exige un plafond de vol.). Chaque ligne ≥ 1 %. Taille max `MAX_ASSETS_PER_PORTFOLIO` (40).
- Rendement espéré: `(1 − MU_SHRINK) × historique + MU_SHRINK × hypothèse de la classe` (0,5 par défaut). Le dataset réel couvre 2026-01-01 → 2026-11-10: la moyenne historique seule est trop bruitée.
- Covariance annualisée, projetée semi-définie positive. `np.diag()` d'un DataFrame est en lecture seule: copier avant `fill_diagonal`.
- Le résidu d'arrondi est placé là où il reste de la marge sous le plafond.
- `DATASET_PATH`: défaut `data/universe.parquet`, accepte `s3://`. **Le dataset actuel est synthétique** (`make_sample_dataset.py`: mêmes FNB et cryptos que le notebook, actions `SYN*`, prix inventés).

## Modèles Bedrock

- `MODEL_STRONG` (PM, CRO): `global.anthropic.claude-sonnet-5-5`. `MODEL_FAST` (Profil, Pépite, Extraction, Juge): `global.anthropic.claude-haiku-5-5`. Région `us-east-1`.
- Réflexion: `{"thinking": {"type": "adaptive", "display": "summarized"}}`. Sans `display: "summarized"`, les blocs arrivent vides.
- Sortie structurée: `agent.invoke_async(prompt, structured_output_model=Schema)`. L'outil interne porte le nom du schéma; il est filtré du flux via `ignore_tools`.

## Déploiement AgentCore

- Déploiement par code (zip), **arm64 uniquement**, Python 3.13, point d'entrée `main.py`, réseau `PUBLIC`.
- `main.py` ajoute `src/` au `sys.path`: ne pas déplacer le paquet sans adapter ce chemin.
- Rôle d'exécution: `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`, `s3:GetObject` si dataset sur S3.
- Pas encore déployé. Restent à écrire: le relais sur l'EC2 (`location /api/` déjà prévu dans `deploy/nginx.conf`, avec `proxy_buffering off`) et le branchement de `frontend/src/api.ts`.

## Ce que le frontend doit encore faire

- Ajouter à `PipelineEvent` les types `portfolios`, `adjust`, `thinking`, `error`, `heartbeat`.
- `Pipeline.tsx`: stocker `portfolios` au lieu d'appeler `state.build()`; gérer `error` (sinon l'écran attend `done` indéfiniment). Le message de `rerun` y est codé en dur pour « Conviction »: utiliser `e.portfolio`.
- `AdjustPanel`: à « Appliquer », remplacer le portefeuille par `proposal.portfolio` au lieu de le recalculer avec engine.ts.

## Limites

- Classement de l'univers en partie par mots du nom; les FNB d'allocation (AOA, AOK…) sont classés en actions.
- Pas d'or physique ni de marché monétaire dans le dataset réel.
- La réflexion arrive surtout en anglais malgré la consigne.
- Parcours ~70 s, ajustement ~45 s (dont ~9 s d'agent Profil si le cache est froid).

# CLAUDE.md

Ce fichier guide les agents de code qui travaillent dans `backend/`. Il décrit ce qui existe, pourquoi, et les règles à ne pas casser.

## Projet

Pipeline multi-agents qui crée un profil d'investisseur et propose 3 portefeuilles. Stack: **Strands Agents** + **Amazon Bedrock** (Claude), hébergé sur **Bedrock AgentCore Runtime**. Le frontend (hébergé sur EC2, dépôt séparé) envoie un JSON et reçoit un flux SSE.

Schéma de référence: `../architecture-workflow.md`. Les numéros d'étape (`step`) du code correspondent à ce schéma.

## Commandes

```bash
# Installation (Python 3.12 en local; le runtime AgentCore utilise 3.13)
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .

# Dataset réel depuis S3 (pas dans le repo), ou une copie locale dans data/universe.parquet:
export DATASET_PATH=s3://monport-datasets-381491955506/universe/universe.parquet

# Pipeline complet en local (appelle Bedrock, ~1 min)
.venv/bin/python scripts/run_local.py
.venv/bin/python scripts/run_local.py --refine "exclus la techno"   # relance depuis data/last_result.json
.venv/bin/python scripts/run_local.py --raw                         # événements JSON bruts

# Serveur AgentCore local. Le port 8080 est pris par l'IDE dans cet environnement: utiliser PORT.
PORT=8091 .venv/bin/python main.py
curl -sN -X POST localhost:8091/invocations -H "Content-Type: application/json" -d '{"mode":"initial","form":{...}}'

# Paquet de déploiement (arm64, Python 3.13) -> build/deployment_package.zip (~127 Mo, limite 250 Mo)
./scripts/build_package.sh
```

Aucune suite de tests n'existe encore. La validation se fait avec `run_local.py` et des scripts ponctuels sur `optimizer.optimize` et `constraints.evaluate`.

## Architecture

```
main.py                     Point d'entrée AgentCore (@app.entrypoint, générateur async -> SSE)
src/invest_agents/
  orchestrator.py           Flux déterministe (pas d'agent superviseur)
  agents/base.py            run_agent(): Agent Strands + sortie structurée + statuts start/done/error
  agents/extraction.py      3b  Texte libre -> contraintes du catalogue (relance seulement)
  agents/profile.py         4   Formulaire -> ProfileAssessment; assemble_profile() ajoute les défauts
  agents/portfolio_manager.py 5 Sélection des titres via outils; l'optimiseur calcule les poids
  agents/judge.py           8   Un juge par portefeuille; conformité recalculée par le code
  agents/cro.py             9   Incohérences du profil + mises en garde; diagnostics() calculés par le code
  mandates.py               Les 3 mandats PM (Défensif, Équilibré, Croissance)
  constraints.py            Catalogue, validation, fusion, conflits, evaluate() (code pur)
  optimizer.py              Moyenne-variance sous contraintes (scipy SLSQP)
  tools.py                  Outils Strands, liés par closure au contexte de chaque agent
  data.py                   Chargement Parquet (local ou s3://), moments, métriques
  events.py                 EventBus (asyncio.Queue) + callback handler Strands
  models.py                 Fabrique BedrockModel (strong/fast, réflexion adaptive)
  schemas.py                Tous les contrats Pydantic
  config.py                 Variables d'environnement (voir .env.example)
```

### Flux

```
initial: form ─────────────────────────────▶ Profil (4)
refine : message ▶ Extraction (3b) ▶ Fusion (3c) ▶ Profil (4)
puis   : 3 PM en parallèle (5) ▶ 3 Juges en parallèle (8)
         ▶ si aucun conforme: nouvel essai des PM avec les écarts (MAX_PM_RETRIES, défaut 1)
         ▶ CRO (9) seulement si au moins un portefeuille est conforme ▶ result (10)
```

Une ambiguïté (extraction) ou un conflit (fusion, ou contraintes du formulaire) émet `clarification` et **arrête** le pipeline.

## Règles de conception (invariants)

1. **Les agents proposent, le code garantit.** Poids, métriques et conformité viennent de `optimizer.optimize`, `Market.portfolio_metrics` et `constraints.evaluate`. Ne jamais faire produire un chiffre par un modèle. `PMNarrative`, `JudgeOpinion` et `RiskReport` ne contiennent que du texte et des scores qualitatifs.
2. **Une contrainte dure de l'utilisateur est intouchable par un agent.** Les outils PM reçoivent les contraintes par closure (`PMState`); le modèle ne peut que choisir des symboles. L'optimiseur revérifie son propre résultat avec `evaluate()` et retourne `infeasible` en cas d'écart.
3. **`JudgeVerdict.compliant` est calculé par le code**, jamais par le modèle. Le juge fournit seulement `fit_score`, `comment` et `suggested_fixes`.
4. **Tout passe par le catalogue.** Une contrainte extraite est validée par `validate_constraint()` contre les valeurs réelles du dataset (`Market.allowed_values()`). Une cible inconnue devient une question de clarification, avec suggestions difflib.
5. **Aucun état serveur.** Le frontend renvoie `result.data.context` (formulaire + contraintes utilisateur) à chaque relance. Les contraintes `source="profile"` ne sont pas dans `context`: elles sont recalculées.
6. **Le pipeline ne plante pas sur un agent.** Un PM en échec utilise `fallback_selection()`; un juge en échec donne un verdict calculé par le code (`fit_score=0`); un CRO en échec émet un `warning` et `risk_report=null`.

## Contraintes

- `max_stock_weight` plafonne seulement les titres détenus en direct (`instrument_type` différent de `ETF`, voir `constraints.is_fund`): un FNB est diversifié par nature. MonPort s'en sert pour le poids par titre du profil et garde `max_position_weight` à 0,40.
- Types dans `schemas.ConstraintType`; métadonnées dans `constraints.SPECS` (`dimension`, `kind`, `direction`). Ajouter un type = l'ajouter aux deux, puis gérer son cas dans `evaluate()`, `optimize()` et `describe()`.
- Valeurs en **fractions** (0.10 = 10 %), comptes en entiers.
- `hard=True`: imposée par l'optimiseur. `hard=False`: préférence, évaluée seulement.
- `source`: `form`, `chat` ou `profile`. Les défauts du profil (`MAX_VOLATILITY`, `MAX_POSITION_WEIGHT`) sont des préférences; `promote_profile_defaults()` les rend dures pour les PM tant qu'elles ne créent pas de conflit.
- Cible `*` (`constraints.ANY`): « chaque secteur » ou « chaque pays », pour `max_sector_weight` et `max_country_weight` seulement. Le groupe `Non classé` (ETF, crypto) est ignoré par ce plafond.
- Fusion (`merge_constraints`): clé `(type, target)`; la nouvelle valeur remplace l'ancienne; `removals` retire.
- Tolérances: `WTOL = 2e-4` sur les poids (arrondis à 4 décimales), `TOL = 1e-3` sur volatilité et rendement.

## Optimiseur

- Objectifs: `min_volatility`, `max_sharpe`, `max_return`, `mean_variance`. `max_return` exige un `vol_cap`, sinon il concentre. `mean_variance` maximise μᵀw − (A/2)·wᵀΣw et exige `risk_aversion` (A, de 1 très audacieux à 25 très prudent); c'est l'objectif des gestionnaires MonPort, A étant calculé par `monport.risk_aversion`.
- Chaque titre retenu pèse au moins `MIN_POSITION_WEIGHT = 1 %`. Taille max: `MAX_ASSETS_PER_PORTFOLIO` (40) et `max_positions`.
- Statuts: `optimal`, `feasible` (non convergé mais valide), `infeasible`, `invalid_selection`. Les messages sont en français et rédigés pour que le PM puisse corriger sa sélection.
- Le résidu d'arrondi est placé là où il reste de la marge sous le plafond (sinon un titre dépasse sa limite de 0,01 %).
- Covariance: annualisée, NaN remplacés, projetée semi-définie positive. `np.diag()` d'un DataFrame est en lecture seule: copier avant `fill_diagonal`.

## Mandats

| id | Nom | Objectif | `vol_cap_factor` |
|---|---|---|---|
| pm1 | Défensif | `min_volatility` | aucun |
| pm2 | Équilibré | `max_sharpe` | 0.85 × vol max du profil |
| pm3 | Croissance | `max_return` | 1.0 × vol max du profil |

Le facteur 0.85 évite que Équilibré et Croissance convergent vers le même portefeuille (observé avant ce réglage).

## Streaming (contrat avec le frontend)

Chaque événement: `{"type", "step", "agent", ...}`. Types: `status` (`state`: start, done, retry, warning, error, skipped), `thinking`, `tool`, `profile`, `clarification` (`questions`, `understood`), `result`, `error` (`code`, `message`, `details`), `heartbeat` (toutes les 10 s sans activité).

- `AgentStreamHandler` regroupe la réflexion (`reasoningText`) par blocs de ~160 caractères et émet un `tool` au premier événement de chaque `toolUseId`.
- L'outil interne de sortie structurée porte le nom du schéma Pydantic; il est filtré via `ignore_tools={schema.__name__}`.
- Les erreurs sont émises dans le flux, car les en-têtes HTTP sont déjà partis.

Changer le format d'un événement casse le frontend: mettre à jour le README en même temps.

## Modèles Bedrock

- `MODEL_STRONG` (PM, CRO): `global.anthropic.claude-sonnet-5-5`. `MODEL_FAST` (Profil, Extraction, Juge): `global.anthropic.claude-haiku-5-5`. Région `us-east-1`.
- Réflexion: `{"thinking": {"type": "adaptive", "display": "summarized"}}`. Sans `display: "summarized"`, les blocs de réflexion arrivent vides.
- Sortie structurée: `agent.invoke_async(prompt, structured_output_model=Schema)`, lecture via `result.structured_output`. Elle fonctionne avec les outils et la réflexion.
- `LANGUAGE_RULE` (dans `agents/base.py`) est ajoutée à tous les prompts système: français, aucun chiffre inventé.

## Données

- `DATASET_PATH`: défaut `data/universe.parquet`; accepte `s3://bucket/key` (téléchargé une fois dans /tmp, sous un nom qui inclut le VersionId S3). Dataset réel (801 actifs chargés, jours ouvrables depuis 2021): `s3://monport-datasets-381491955506/universe/universe.parquet`, produit et publié par `../data-prep/build_universe.py --upload s3://monport-datasets-381491955506 [--upload-only]`.
- Format long issu de `create_opt_inputs` (`../Universe_Cleaned.ipynb`). Obligatoires: `date`, `symbol`, `total_return_cad`. Optionnelles: `name`, `sector`, `industry`, `country`, `currency`, `asset_class`, `instrument_type`, `market`, `is_included_universe`.
- Actifs avec moins de 120 observations écartés. Secteur, pays et classe manquants deviennent `Non classé`.
- `get_market()` est en cache (`lru_cache`); appelé via `asyncio.to_thread` dans l'orchestrateur.
- Le dataset réel (S3, 1,2 M lignes) est lu par `_read_dataset`: seulement les colonnes utiles, métadonnées texte en catégories. Pic mémoire ~440 Mo au lieu de ~850 Mo avec `pd.read_parquet`, utile sur l'EC2 (t3.small, 2 Go).
- `asset_class` est normalisée par `build_universe.normalize_asset_class`: `Equity`, `Fixed Income`, `Multi-Asset`, `Real Estate`, `Commodities`, `Alternative` (crypto et BITW). Le détail d'un FNB reste dans `category_group` / `category`.

## Déploiement AgentCore

- Déploiement par code (zip), **arm64 uniquement**, Python 3.13, point d'entrée `main.py`, réseau `PUBLIC`.
- `build_package.sh` installe les wheels `aarch64-manylinux2014`, copie `src/` (et le dataset seulement avec `EMBED_DATASET=1`), fixe les permissions (644/755) et retire `__pycache__`.
- `main.py` ajoute `src/` au `sys.path`: ne pas déplacer le paquet sans adapter ce chemin.
- Rôle d'exécution: `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream` (profils d'inférence + modèles sous-jacents), politique gérée `MonPortDatasetRead` (`s3:GetObject` sur `universe/*`) si dataset sur S3.
- Pas encore déployé. Le backend EC2 (appel `invoke_agent_runtime` avec le rôle d'instance, relais SSE, `proxy_buffering off` dans nginx) reste à écrire.

## Conventions

- Prompts, messages d'erreur et libellés en **français**. Code et identifiants en anglais.
- Toute sortie d'agent passe par un modèle Pydantic de `schemas.py`; les descriptions de champs font partie du prompt, les rédiger avec soin.
- Les outils Strands se créent par fabriques (`make_*_tools`) qui ferment sur le contexte; ne pas exposer de paramètre permettant au modèle de changer les contraintes ou l'objectif.
- Nouveau traitement chiffré: l'écrire en code pur testable sans LLM, puis l'exposer par un outil.

## Limites et pistes

- Rendements et volatilités historiques (moyenne et covariance de la période). Pas de modèle prospectif.
- Défensif peut avoir un rendement nul ou négatif: envisager un plancher `min_expected_return` propre au mandat.
- La réflexion arrive surtout en anglais malgré la consigne.
- Le nouvel essai cible les PM, pas l'agent Profil (le schéma dessine un retour au Profil: à harmoniser).
- Les champs de `InvestorForm` sont une proposition à aligner avec le formulaire du frontend.
- AgentCore Gateway (MCP) n'est pas utilisé: les outils sont locaux. Les fonctions pures de `tools.py` peuvent passer derrière une Lambda sans changer de signature.

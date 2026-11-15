# CLAUDE.md

Ce fichier guide les agents de code qui travaillent dans `backend/`. Il décrit ce qui existe, pourquoi, et les règles à ne pas casser.

## Projet

Pipeline multi-agents MonPort: Pépite vérifie le questionnaire, écrit 3 profils de contraintes et pilote 3 gestionnaires, 3 agents Risque et un juge final. Stack: **Strands Agents** + **Amazon Bedrock** (Claude), hébergé sur **Bedrock AgentCore Runtime**, outils derrière **AgentCore Gateway** (MCP). Le frontend (`../frontend`) envoie un JSON et reçoit un flux SSE.

Schéma de référence: `../docs/architecture-workflow.md` (v4).

## Commandes

```bash
# Installation (Python 3.12 en local; le runtime AgentCore utilise 3.13)
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .

# Dataset réel depuis S3 (pas dans le repo):
export MONPORT_UNIVERSE_PARQUET_URI=s3://monport-datasets-381491955506/universe/universe.parquet
# ou synthétique, sans AWS:
.venv/bin/python scripts/make_sample_dataset.py

# Parcours MonPort complet en local (appelle Bedrock, 2 à 4 min)
.venv/bin/python scripts/run_local.py
.venv/bin/python scripts/run_local.py --chat "Pourquoi autant d'obligations?"
.venv/bin/python scripts/run_local.py --check-only --raw            # vérification seule, événements JSON bruts
# Outils par la Gateway en ligne plutôt que dans le processus:
TOOLS_BACKEND=gateway GATEWAY_URL=$(cat ../deploy/state/gateway-url) .venv/bin/python scripts/run_local.py

# Tests (sans Bedrock) et tests de fumée en ligne
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke_runtime.py [--url https://<cloudfront>/api/invocations] [--restore]
.venv/bin/python scripts/smoke_gateway.py

# Serveur AgentCore local. Le port 8080 est pris par l'IDE dans cet environnement: utiliser PORT.
PORT=8091 .venv/bin/python main.py
curl -sN -X POST localhost:8091/invocations -H "Content-Type: application/json" -d '{"mode":"monport_check","profile":{...},"constraints":{...}}'
PORT=8000 .venv/bin/python mcp_server/main.py                      # serveur MCP des outils, en local

# Paquets de déploiement (arm64, Python 3.13, ~140 Mo, limite 250 Mo): agents, puis serveur MCP
./scripts/build_package.sh
ENTRY=mcp_server/main.py OUT=build/tools_package.zip ./scripts/build_package.sh
```

Tests pytest (`tests/`, sans Bedrock): config, contraintes, données, optimiseur, modèles, outils sans état et Gateway (client simulé), guardrail, mémoire.

## Architecture

```
main.py                     Point d'entrée AgentCore (@app.entrypoint): monport_check, monport, monport_chat
mcp_server/main.py          Serveur MCP des outils (runtime monport_tools, derrière AgentCore Gateway)
src/invest_agents/
  workflow/flow.py          Les 3 parcours; ensure_pipeline() complète ce que Pépite n'a pas fait
  workflow/pepite.py        Pépite et ses outils (risque, cohérence, plan, construction, jugement, questions)
  workflow/workers.py       Gestionnaires, agents Risque, juge final, ask_agent()
  workflow/session.py       État d'une conversation (en mémoire du processus, restauré depuis AgentCore Memory)
  agents/base.py            AgentHandle: Agent Strands réutilisable, sortie structurée, statuts start/done/error
  agents/portfolio_manager.py Sélection des titres via outils; l'optimiseur calcule les poids
  monport.py                Profil de risque, profils de contraintes, mélanges 80/20, traduction des événements
  tool_core.py              Outils métier sans état (univers, filtre, optimiseur, vérificateur, macro), en JSON
  gateway.py                gateway.run(): Gateway MCP signée SigV4 si TOOLS_BACKEND=gateway, sinon local; repli local
  tools.py                  Closures Strands vues par les modèles: ajoutent le contexte imposé, puis gateway.run()
  guardrail.py              Bedrock Guardrails sur le texte libre du client (GUARDRAIL_ID)
  memory.py                 Enregistrement et restauration des sessions dans AgentCore Memory (MEMORY_ID)
  diagnostics.py            Faits de risque calculés par le code, lus par les agents Risque
  mandates.py, catalog.py, constraints.py, allocator.py, optimizer.py, market.py, data.py, macro.py
  events.py, models.py, schemas.py, config.py, runtime.py
```

## Règles de conception (invariants)

1. **Les agents proposent, le code garantit.** Poids, métriques et conformité viennent de `optimizer.optimize`, `Market.portfolio_metrics` et `constraints.evaluate`. Ne jamais faire produire un chiffre par un modèle. `PMNarrative`, `JudgeOpinion` et `RiskReport` ne contiennent que du texte et des scores qualitatifs.
2. **Une contrainte dure de l'utilisateur est intouchable par un agent.** Les outils PM reçoivent les contraintes par closure (`PMState`); le modèle ne peut que choisir des symboles. L'optimiseur revérifie son propre résultat avec `evaluate()` et retourne `infeasible` en cas d'écart.
3. **`JudgeVerdict.compliant` est calculé par le code**, jamais par le modèle. Le juge fournit seulement `fit_score`, `comment` et `suggested_fixes`.
4. **Tout passe par le catalogue.** Une contrainte extraite est validée par `validate_constraint()` contre les valeurs réelles du dataset (`Market.allowed_values()`). Une cible inconnue devient une question de clarification, avec suggestions difflib.
5. **L'état d'une conversation vit dans la microVM AgentCore** (`workflow/session.py`), routée par `runtimeSessionId`. Il est enregistré dans AgentCore Memory après chaque étape et restauré si la microVM change. Si tout est perdu, `monport` repart du questionnaire et de la vérification que le frontend renvoie.
6. **Le pipeline ne plante pas sur un agent.** Un PM en échec utilise `fallback_selection()` (meilleurs actifs de chaque groupe à poids minimal, 10 actifs les plus calmes sous un plafond de volatilité, actions qui respectent les contraintes de facteurs, puis les meilleurs ratios de Sharpe: sur l'univers réel, les 15 meilleurs Sharpe sont tous des actions et ne tiennent pas un plancher d'obligations); un juge en échec donne un verdict calculé par le code (`fit_score=0`); un CRO en échec émet un `warning` et `risk_report=null`.

## Contraintes

- `max_stock_weight` plafonne seulement les titres détenus en direct (`instrument_type` différent de `ETF`, voir `constraints.is_fund`): un FNB est diversifié par nature. MonPort s'en sert pour le poids par titre du profil et garde `max_position_weight` à 0,40.
- Types dans `schemas.ConstraintType`; métadonnées dans `constraints.SPECS` (`dimension`, `kind`, `direction`). Ajouter un type = l'ajouter aux deux, puis gérer son cas dans `evaluate()`, `optimize()` et `describe()`.
- Valeurs en **fractions** (0.10 = 10 %), comptes en entiers.
- `hard=True`: imposée par l'optimiseur. `hard=False`: préférence, évaluée seulement.
- `source`: `form`, `chat` ou `profile`. Les défauts du profil (`MAX_VOLATILITY`, `MAX_POSITION_WEIGHT`) sont des préférences; `promote_profile_defaults()` les rend dures pour les PM tant qu'elles ne créent pas de conflit.
- Parts de la poche actions (`min/max_sector_share`, `min/max_country_share`, `catalog.SHARE_TYPES`): 0.45 = 45 % des actions en direct et FNB d'actions; seules les actions en direct du groupe comptent au numérateur (un FNB n'a ni secteur ni pays). Contrainte linéaire `poids du groupe − p × poids de la poche`. Cible: un ou plusieurs libellés séparés par `|` (une région = plusieurs pays). Une base limitée aux actions en direct a été écartée: l'optimiseur gardait 0 action et satisfaisait la part à vide.
- Cible `*` (`constraints.ANY`): « chaque secteur » ou « chaque pays », pour `max_sector_weight` et `max_country_weight` seulement. Le groupe `Non classé` (ETF, crypto) est ignoré par ce plafond.
- Fusion (`merge_constraints`): clé `(type, target)`; la nouvelle valeur remplace l'ancienne; `removals` retire.
- Tolérances: `WTOL = 2e-4` sur les poids (arrondis à 4 décimales), `TOL = 1e-3` sur volatilité et rendement.

## Optimiseur

- Objectifs: `min_volatility`, `max_sharpe`, `max_return`, `mean_variance`. `max_return` exige un `vol_cap`, sinon il concentre. `mean_variance` maximise μᵀw − (A/2)·wᵀΣw et exige `risk_aversion` (A, de 1 très audacieux à 25 très prudent); c'est l'objectif des gestionnaires MonPort, A étant calculé par `monport.risk_aversion`. Sur le dataset synthétique, A = 25 donne environ 4 % de volatilité et A = 1 environ 15 %.
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

- `MODEL_PEPITE` (Pépite): `global.anthropic.claude-sonnet-5-5`. `MODEL_STRONG` (gestionnaires, agents Risque, juge final): `global.anthropic.claude-opus-5-5`, effort `MODEL_EFFORT=high`. Région `us-east-1`.
- Réflexion: `{"thinking": {"type": "adaptive", "display": "summarized"}}`. Sans `display: "summarized"`, les blocs de réflexion arrivent vides.
- Sortie structurée: `agent.invoke_async(prompt, structured_output_model=Schema)`, lecture via `result.structured_output`. Elle fonctionne avec les outils et la réflexion.
- `LANGUAGE_RULE` (dans `agents/base.py`) est ajoutée à tous les prompts système: français, aucun chiffre inventé.

## Données

- `MONPORT_UNIVERSE_PARQUET_URI`: défaut le chemin de `config.DEFAULT_PARQUET_PATH`; accepte `s3://bucket/key` (lu en mémoire via boto3, sans cache disque). Dataset réel (801 actifs chargés, jours ouvrables depuis 2021): `s3://monport-datasets-381491955506/universe/universe.parquet`, produit et publié par `../data-prep/build_universe.py --upload s3://monport-datasets-381491955506 [--upload-only]`.
- Format long issu de `create_opt_inputs` (`../Universe_Cleaned.ipynb`). Obligatoires: `date`, `symbol`, `total_return_cad`. Optionnelles: `name`, `sector`, `industry`, `country`, `currency`, `asset_class`, `instrument_type`, `market`, `is_included_universe`.
- Actifs avec moins de 120 observations écartés. Secteur, pays et classe manquants deviennent `Non classé`.
- `get_market()` est en cache (`lru_cache`); appelé via `asyncio.to_thread` dans `workflow/flow.py`.
- Le dataset réel (S3, 1,2 M lignes) est lu par `_read_dataset`: seulement les colonnes utiles, métadonnées texte en catégories. Pic mémoire ~440 Mo au lieu de ~850 Mo avec `pd.read_parquet`, utile sur l'EC2 (t3.small, 2 Go). Le jeu synthétique (`make_sample_dataset.py`, symboles `SYN*`, `SETF*`, `SCRY*`) reste pour le développement sans AWS; ses chiffres n'ont aucune valeur réelle. Il ne se charge plus tel quel (colonne `close_price_cad` absente, classes d'actifs d'avant `data.py`, pas de références CAPM comme SPY). Pour tester sur données réelles sans S3: `../data-prep/build_universe.py` écrit `data/universe.parquet`.
- Table macro: `MONPORT_MACRO_PARQUET_URI` (défaut `data/macro_long_z.parquet`; référence `s3://monport-datasets-381491955506/macro/macro_long_z.parquet`), issue de `../../macro_long_z.csv`. Format long: `date`, `country` (US, CA), `metric` (`yield_10y`, `yield_2y`, `spread_10y_2y`, `policy_rate`, `inflation_yoy`, `unemployment_rate`, en %), `metric_value`, `z_5y`, `z_full`, `history_start_date`, `ref_period`. Chargée au premier appel puis gardée en mémoire (`macro.get_macro`). Exposée par `tools.make_macro_tools()` (`get_latest_macro_snapshot`, `get_macro_history`) aux gestionnaires, aux agents Risque/CRO et aux juges, avec la consigne `tools.MACRO_PROMPT`. Une source indisponible donne `{"error": ...}`: l'agent continue sans contexte macro.
- Scores de facteurs: `MONPORT_FACTORS_PARQUET_URI` (défaut `data/factor_scores.parquet`; référence `s3://monport-datasets-381491955506/factors/factor_scores.parquet`, voir `../data-prep/FACTORS.md`). `factors.py` les charge une fois; `size` y devient `small_cap` (signe inversé). Source absente: table vide, `allowed_values()["factor"]` vide, préférences de facteurs ignorées. Contraintes: `catalog._factor_groups` (Σ wᵢ·(zᵢ − seuil) ≥ 0, marge de 0,01 pour l'arrondi des poids, plancher de 10 % en actions notées `FACTOR_SLEEVE_MIN`); vérification dans `evaluate()` (tolérance `FTOL` = 0,01). Une contrainte de facteur infaisable rend un message qui renvoie le PM vers `screen_factor`.
- Dans l'univers réel, un FNB d'actions a la classe `Equity`, comme une action (autres classes de FNB: `Fixed Income`, `Multi-Asset`, `Commodities`, `Real Estate`, `Alternative`); les 2 cryptos sont `Alternative`. Seul `instrument_type` (`Stock`, `ETF`, `Cryptocurrency`) distingue un titre détenu en direct d'un FNB: « FNB seulement » passe donc par `exclude_instrument_type` (Stock, Cryptocurrency), jamais par `exclude_asset_class`. Le jeu synthétique compte 6 FNB d'obligations: un profil prudent doit tenir sous la limite de 40 % par ligne.

## Déploiement AgentCore

- Scripts dans `../deploy/` (voir `../docs/architecture-workflow.md`): `deploy-agentcore.sh` (agents), `deploy-gateway.sh` (serveur MCP, Gateway, cible), `deploy-guardrail.sh`, `deploy-memory.sh`, `deploy-proxy.sh`, `deploy-cloudfront.sh`. Identifiants dans `../deploy/state/`.
- Déploiement par code (zip), **arm64 uniquement**, Python 3.13, point d'entrée `opentelemetry-instrument main.py` (traces ADOT), réseau `PUBLIC`.
- `build_package.sh` installe les wheels `aarch64-manylinux2014` (avec l'extra `otel`), copie `src/` et fixe les permissions (644/755).
- `main.py` et `mcp_server/main.py` ajoutent `src/` au `sys.path`: ne pas déplacer le paquet sans adapter ce chemin.
- Rôles d'exécution (`../deploy/agentcore/*-policy.json`): modèles Anthropic, guardrail, Gateway `monport-tools-*`, mémoire `monport_conversations-*`, logs et traces pour les agents; lecture S3 de `universe/*` et `macro/*` seulement pour le serveur MCP.

## Conventions

- Prompts, messages d'erreur et libellés en **français**. Code et identifiants en anglais.
- Toute sortie d'agent passe par un modèle Pydantic de `schemas.py`; les descriptions de champs font partie du prompt, les rédiger avec soin.
- Les outils Strands se créent par fabriques (`make_*_tools`) qui ferment sur le contexte; ne pas exposer de paramètre permettant au modèle de changer les contraintes ou l'objectif. Un nouvel outil métier va dans `tool_core.py`, est publié par `mcp_server/main.py` (puis `deploy-gateway.sh`, qui resynchronise la cible) et ajouté à `gateway.TOOLS`.
- Nouveau traitement chiffré: l'écrire en code pur testable sans LLM, puis l'exposer par un outil.

## Limites et pistes

- Rendements et volatilités historiques (moyenne et covariance de la période). Pas de modèle prospectif.
- Défensif peut avoir un rendement nul ou négatif: envisager un plancher `min_expected_return` propre au mandat.
- La réflexion arrive surtout en anglais malgré la consigne.
- Le nouvel essai cible les PM, pas l'agent Profil (le schéma dessine un retour au Profil: à harmoniser).
- Les champs de `InvestorForm` sont une proposition à aligner avec le formulaire du frontend.
- Un appel d'outil par la Gateway prend 0,5 s une fois la session MCP ouverte, environ 25 s à froid (microVM et dataset): `gateway.prewarm()` l'ouvre pendant la vérification.

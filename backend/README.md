# Backend - Pipeline multi-agents de profil d'investisseur

Strands Agents + Amazon Bedrock, hébergé sur Bedrock AgentCore Runtime, outils derrière AgentCore Gateway. Voir `../docs/architecture-workflow.md` pour le schéma et le rôle de chaque service AWS.

## Démarrage local

```bash
cd backend
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .
cp .env.example .env            # puis exporter les variables (ou laisser les valeurs par défaut)

# Dataset, au choix:
# a) réel, depuis S3 (exige des identifiants AWS avec s3:GetObject, ex. WSParticipantRole):
#   export MONPORT_UNIVERSE_PARQUET_URI=s3://monport-datasets-381491955506/universe/universe.parquet
# b) réel, reconstruit en local depuis la racine du dépôt (Wikipedia + yfinance, cache dans data-prep/data/raw/):
#   pip install -r data-prep/requirements.txt && python data-prep/build_universe.py
# (le jeu SYNTHÉTIQUE de scripts/make_sample_dataset.py ne se charge plus tel quel: colonnes et classes d'avant data.py)

.venv/bin/python scripts/run_local.py                          # vérification puis construction (appelle Bedrock)
.venv/bin/python scripts/run_local.py --chat "exclus la techno"   # puis un message à Pépite
.venv/bin/python -m pytest -q                                   # tests, sans Bedrock
PORT=8091 .venv/bin/python main.py                             # serveur AgentCore local (POST /invocations)
```

Colonnes lues dans le dataset: `date`, `symbol`, `total_return_cad` (obligatoires), puis `name`, `sector`, `industry`,
`country`, `currency`, `asset_class`, `instrument_type`, `market`, `is_included_universe` (si présentes).

## Structure

| Fichier | Rôle |
|---|---|
| `main.py` | Point d'entrée AgentCore (`@app.entrypoint`, générateur asynchrone, SSE) |
| `workflow/` | Parcours MonPort (`flow.py`), Pépite (`pepite.py`), gestionnaires, agents Risque et juge final (`workers.py`), sessions (`session.py`) |
| `agents/` | `AgentHandle` (`base.py`) et gestionnaire de portefeuille |
| `tool_core.py`, `gateway.py` | Outils métier sans état; appel par AgentCore Gateway (MCP, SigV4) ou dans le processus |
| `mcp_server/main.py` | Serveur MCP des outils (runtime `monport_tools`) |
| `guardrail.py`, `memory.py` | Bedrock Guardrails sur le texte du client; sessions dans AgentCore Memory |
| `mandates.py` | Les 3 mandats des PM (Défensif, Équilibré, Croissance) |
| `catalog.py` | Catalogue de contraintes des agents (validation, fusion, conflits, vérification) et pont vers `constraints.py` |
| `constraints.py` | Moteur de contraintes: univers admissible, contradictions, plan de contraintes linéaires, validation des poids (code pur) |
| `allocator.py` | Optimisation vue par les agents (Markowitz sur tout l'univers, relance avec limites assouplies), au-dessus de `optimizer.py` |
| `optimizer.py` | Optimisation moyenne-variance sous contraintes (SLSQP) |
| `factors.py` | Scores de facteurs des actions (`data-prep/factors_model.ipynb`) et exposition d'un portefeuille |
| `macro.py` | Contexte macro US et Canada (table `macro_long_z`) |
| `diagnostics.py`, `evidence.py` | Faits de risque et preuves chiffrées calculés par le code, cités par les agents Risque |
| `backtest.py`, `projection.py` | Backtest avec rééquilibrage, VaR/ES, et projection sur 10 ans avec les ajouts prévus (code pur) |
| `tools.py` | Outils Strands liés au contexte de chaque agent |
| `data.py` | Chargement, validation et matrices de rendements du Parquet (local ou `s3://`), sans estimation |
| `market.py` | `Market`: catalogue d'actifs, rendements espérés et covariance (méthodes de `config.py`), métriques de portefeuille |
| `config.py` | Réglages financiers (source du Parquet, méthodes de rendement, covariance, contraintes, profils base/agent) |
| `runtime.py` | Réglages d'exécution (Bedrock, modèles, relances) lus dans l'environnement |
| `events.py` | Bus d'événements pour le streaming (réflexion, outils, statuts) |
| `schemas.py` | Contrats Pydantic (formulaire, contraintes, portefeuilles, rapport) |
| `monport.py` | Parcours du frontend MonPort: vérification par Pépite, profils de contraintes, gestionnaires, juges, mélanges 80/20 ou juge final |

## Contrat d'entrée

```jsonc
// Frontend MonPort (seuls modes acceptés): Profile et Constraints de frontend/src/types.ts. Les événements renvoyés sont ceux de
// `PipelineEvent` (check, agent_status, pepite, universe, portfolios, error, done), pas ceux décrits plus bas.
{"mode": "monport_check", "profile": { /* Profile */ }, "constraints": { /* Constraints */ }}
{"mode": "monport", "profile": {}, "constraints": {}, "check": { /* PepiteCheck reçu */ }, "adjustment": "texte libre", "session": "id"}
{"mode": "monport_chat", "session": "id", "message": "texte libre"}
{"mode": "monport_rebuild", "session": "id"}   // applique la reconstruction que Pépite a fait confirmer dans le chat
```

## Contrat de sortie (SSE, un JSON par événement)

Les événements reçus par le frontend sont ceux de `PipelineEvent` (`frontend/src/types.ts`): `check`, `agent_status`,
`pepite`, `universe`, `rerun`, `warning`, `portfolios`, `error`, `done`. En interne, les agents émettent sur l'`EventBus`
(`status`, `thinking`, `tool`, `heartbeat`), traduits par `monport.Translator`.

## Déploiement sur AWS

Tout passe par les scripts de `../deploy/` (idempotents, AWS CLI). Ordre pour un compte vide:

```bash
./deploy/deploy-gateway.sh      # serveur MCP (runtime monport_tools), Gateway monport-tools, cible
./deploy/deploy-guardrail.sh    # guardrail de Pépite
./deploy/deploy-memory.sh       # mémoire des conversations
echo gateway > deploy/state/tools-backend
./deploy/deploy-agentcore.sh    # runtime monport_agents (lit deploy/state/*)
./deploy/deploy-proxy.sh        # Lambda Function URL en streaming
./deploy/deploy-cloudfront.sh   # front HTTPS + WAF
```

Les rôles d'exécution sont créés par les scripts (`../deploy/agentcore/*-policy.json`), avec le minimum de droits.
Réglages lus dans l'environnement du runtime: `MODEL_PEPITE`, `MODEL_STRONG`, `MODEL_EFFORT`, `TOOLS_BACKEND`,
`GATEWAY_URL`, `GUARDRAIL_ID`, `GUARDRAIL_VERSION`, `MEMORY_ID`, `MONPORT_UNIVERSE_PARQUET_URI`, `MONPORT_MACRO_PARQUET_URI`.
Sans les quatre du milieu, le backend se comporte comme en local (outils dans le processus, pas de filtre, pas de mémoire).

## Dataset sur S3

Bucket `monport-datasets-381491955506` (us-east-1): privé (Block Public Access), chiffré SSE-S3, TLS obligatoire,
versionné (versions remplacées expirées après 30 jours, 3 gardées). Un dossier par table:

```text
universe/universe.parquet                                 lu par le backend (MONPORT_UNIVERSE_PARQUET_URI)
raw/{catalog,prices,fx,prices_missing}/<table>.parquet    couches brutes de data-prep, pour la traçabilité
```

Publication (depuis la racine du dépôt): `python data-prep/build_universe.py --upload s3://monport-datasets-381491955506`
(ajouter `--upload-only` pour publier les fichiers existants sans reconstruire). Le backend télécharge le fichier une fois
par démarrage dans `/tmp`, sous un nom qui inclut la version S3: un nouvel objet est pris en compte au prochain
redémarrage, sans redéployer. `WSParticipantRole` (local, EC2) lit déjà le bucket.

## Principes de conception

- Les agents proposent, le code garantit. Poids, métriques et conformité sont calculés par `optimizer.py` et
  `constraints.evaluate`. Le texte des agents ne contient aucun chiffre qui n'en vienne pas.
- Une contrainte dure de l'utilisateur ne peut pas être modifiée par un agent: elle est appliquée par l'optimiseur et
  revérifiée indépendamment par le Juge.
- Les défauts du profil (volatilité maximale, poids maximal par titre) sont des préférences. L'optimiseur les applique
  tant qu'ils n'entrent pas en conflit avec les contraintes de l'utilisateur.
- L'état d'une conversation reste dans sa microVM AgentCore et dans AgentCore Memory (7 jours), jamais ailleurs.

## Limites connues

- Rendements et volatilités sont historiques (moyenne et covariance sur la période du dataset).
- La réflexion du modèle est résumée et arrive surtout en anglais malgré la consigne en français.
- Un nouvel essai (`MAX_PM_RETRIES`) ne se déclenche que si aucun portefeuille n'est conforme.

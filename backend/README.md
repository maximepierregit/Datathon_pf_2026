# Backend - Pipeline multi-agents de profil d'investisseur

Strands Agents + Amazon Bedrock, hébergé sur Bedrock AgentCore Runtime. Voir `../architecture-workflow.md` pour le schéma.

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
# c) SYNTHÉTIQUE, pour le développement:
.venv/bin/python scripts/make_sample_dataset.py

.venv/bin/python scripts/run_local.py                          # parcours initial (appelle Bedrock)
.venv/bin/python scripts/run_local.py --refine "exclus la techno"  # relance
PORT=8091 .venv/bin/python main.py                             # serveur AgentCore local (POST /invocations)
```

Colonnes lues dans le dataset: `date`, `symbol`, `total_return_cad` (obligatoires), puis `name`, `sector`, `industry`,
`country`, `currency`, `asset_class`, `instrument_type`, `market`, `is_included_universe` (si présentes).

## Structure

| Fichier | Rôle |
|---|---|
| `main.py` | Point d'entrée AgentCore (`@app.entrypoint`, générateur asynchrone, SSE) |
| `orchestrator.py` | Flux déterministe: extraction, fusion, profil, 3 PM, 3 juges, nouvel essai, CRO, résultat |
| `agents/` | Profil, Extraction, PM, Juge, CRO (prompts et sorties structurées) |
| `mandates.py` | Les 3 mandats des PM (Défensif, Équilibré, Croissance) |
| `constraints.py` | Catalogue de contraintes, validation, fusion, conflits, vérification (code pur) |
| `optimizer.py` | Optimisation moyenne-variance sous contraintes (SLSQP) |
| `tools.py` | Outils Strands liés au contexte de chaque agent |
| `data.py` | Chargement, validation et matrices de rendements du Parquet (local ou `s3://`), sans estimation |
| `market.py` | `Market`: catalogue d'actifs, rendements espérés et covariance (méthodes de `config.py`), métriques de portefeuille |
| `config.py` | Réglages financiers (source du Parquet, méthodes de rendement, covariance, contraintes, profils base/agent) |
| `runtime.py` | Réglages d'exécution (Bedrock, modèles, relances) lus dans l'environnement |
| `events.py` | Bus d'événements pour le streaming (réflexion, outils, statuts) |
| `schemas.py` | Contrats Pydantic (formulaire, contraintes, portefeuilles, rapport) |
| `monport.py` | Parcours du frontend MonPort: vérification par Pépite, profils de contraintes, gestionnaires, juges, mélanges 80/20 ou juge final |
| `agents/pepite.py` | Pépite, l'analyste: cohérence du questionnaire, puis les 3 profils de contraintes (MonPort) |
| `agents/final_judge.py` | Juge final: garde un seul portefeuille quand le profil est cohérent (MonPort) |

## Contrat d'entrée

```jsonc
// Premier passage
{"mode": "initial", "form": { /* InvestorForm, voir schemas.py */ }}

// Relance: `context` est copié tel quel depuis le dernier événement `result`
{"mode": "refine", "message": "texte libre", "context": { /* result.data.context */ }}

// Frontend MonPort: Profile et Constraints de frontend/src/types.ts. Les événements renvoyés sont ceux de
// `PipelineEvent` (check, agent_status, pepite, universe, portfolios, error, done), pas ceux décrits plus bas.
{"mode": "monport_check", "profile": { /* Profile */ }, "constraints": { /* Constraints */ }}
{"mode": "monport", "profile": {}, "constraints": {}, "check": { /* PepiteCheck reçu */ }, "adjustment": "texte libre"}
```

## Contrat de sortie (SSE, un JSON par événement)

Tous les événements ont `type`, `step` et `agent`.

| `type` | Contenu | Usage frontend |
|---|---|---|
| `status` | `state` (start, done, retry, warning, error, skipped), `text` | Ligne de statut par agent |
| `thinking` | `text` (réflexion du modèle, par blocs) | Panneau repliable |
| `tool` | `name` | « Outil en cours » |
| `profile` | `data`, `labels` | Affichage anticipé du profil |
| `clarification` | `questions`, `understood` | Afficher les questions dans le chat; le parcours s'arrête |
| `result` | `data` (profil, portefeuilles + verdicts, rapport CRO, `context`) | Visualisation finale |
| `error` | `code`, `message`, `details` | Message d'erreur; le flux s'arrête |
| `heartbeat` | rien | Ignorer |

`step`: `3` orchestrateur, `3b` extraction, `3c` fusion, `4` profil, `5` PM, `8` juges, `9` CRO, `10` assemblage.

## Déploiement sur AgentCore Runtime (déploiement par code, arm64)

```bash
./scripts/build_package.sh        # produit build/deployment_package.zip (~130 Mo, limite 250 Mo)
```

Puis créer le runtime (console, CLI `agentcore` ou `create_agent_runtime`, voir la
[documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html)).
Point d'entrée `main.py`, runtime `PYTHON_3_13`, réseau `PUBLIC`. Variables d'environnement: `MODEL_STRONG`, `MODEL_FAST`,
`MONPORT_UNIVERSE_PARQUET_URI=s3://monport-datasets-381491955506/universe/universe.parquet`. Le zip n'inclut le dataset qu'avec
`EMBED_DATASET=1 ./scripts/build_package.sh`.

Le rôle d'exécution doit autoriser `bedrock:InvokeModel` et `bedrock:InvokeModelWithResponseStream` sur les profils
d'inférence utilisés (et sur les modèles sous-jacents dans les régions concernées). Pour le dataset, attacher la politique
gérée `arn:aws:iam::381491955506:policy/MonPortDatasetRead` (`s3:GetObject` sur `universe/*` seulement). Pour l'appel
depuis l'EC2: `bedrock-agentcore:InvokeAgentRuntime` sur l'ARN du runtime.

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
- Aucune donnée n'est conservée côté serveur. Le frontend renvoie `context` à chaque relance.

## Limites connues

- Le dataset fourni par `make_sample_dataset.py` est synthétique. Les résultats chiffrés n'ont aucune valeur réelle.
- Rendements et volatilités sont historiques (moyenne et covariance sur la période du dataset).
- La réflexion du modèle est résumée et arrive surtout en anglais malgré la consigne en français.
- Un nouvel essai (`MAX_PM_RETRIES`) ne se déclenche que si aucun portefeuille n'est conforme.

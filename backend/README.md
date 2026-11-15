# Backend - Pipeline multi-agents de MonPort

Strands Agents + Amazon Bedrock, hébergé sur Bedrock AgentCore Runtime. Schéma: `../docs/architecture-workflow.md`.
Le contrat avec le frontend est celui de `frontend/src/types.ts` (section « Contrat du frontend » ci-dessous).

## Démarrage local

```bash
cd backend
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .
cp .env.example .env            # puis exporter les variables (ou laisser les valeurs par défaut)

# Dataset réel (805 tickers, rendements en CAD depuis 2021): data-prep/build_universe.py, depuis la racine du dépôt
#   pip install -r data-prep/requirements.txt && python data-prep/build_universe.py   (cache dans backend/data/raw/)
# ou un jeu SYNTHÉTIQUE pour le développement:
.venv/bin/python scripts/make_sample_dataset.py

.venv/bin/python scripts/run_web.py                                  # contrat du frontend (appelle Bedrock, ~70 s)
.venv/bin/python scripts/run_web.py --adjust "pas de pétrole"        # chat d'ajustement (~45 s)
PORT=8091 .venv/bin/python main.py                                   # serveur AgentCore local (POST /invocations)
```

Colonnes lues dans le dataset: `date`, `symbol`, `total_return_cad` (obligatoires), puis `name`, `currency`,
`asset_class`, `instrument_type`, `sector`, `industry`, `country`, `category_group`, `category`, `market_cap`,
`expense_ratio`, `theme`, `is_included_universe` (si présentes). `sector`, `industry` et `country` ne concernent
que les actions (`Non classé` ailleurs). `theme` contient des identifiants séparés par `;` (`tech;ia`), issus de
`data-prep/themes.csv`; quand la colonne existe, elle fait foi pour tech, ia, robotique, energie-propre, esg,
armement et vice, et les heuristiques de `classify.py` ajoutent les autres thématiques.

## Contrat du frontend

### Requêtes (`POST /invocations`, JSON)

```jsonc
// Construction des 3 portefeuilles (page /construction)
{"mode": "pipeline", "profile": Profile, "constraints": Constraints}

// Chat « Ajuster avec Pépite »
{"mode": "adjust", "portfolio": "equilibre", "message": "plus de tech",
 "profile": Profile, "constraints": Constraints,   // préférences en vigueur pour ce portefeuille
 "current": Portfolio}                              // portefeuille affiché, pour les valeurs « avant »
```

`Profile` et `Constraints` sont exactement ceux de `types.ts`. `Contribution` n'est jamais envoyé. Le score de risque
est recalculé par le backend avec la même formule que `riskScore` (engine.ts).

### Événements (SSE, une ligne `data: {json}` par événement)

| `type` | Champs | Émis par |
|---|---|---|
| `agent_status` | `agent` (eclaireur, compositeur, verificateur), `status`, `message` | Tous les agents |
| `pepite` | `text` | Début et fin |
| `universe` | `before`, `after` | Éclaireur |
| `rerun` | `portfolio`, `reason` | Vérificateur, quand un portefeuille ne respecte pas ses limites |
| `warning` | `text` | Vérificateur (incohérences profil ↔ préférences) |
| `portfolios` | `portfolios` (`Record<PortfolioId, Portfolio>`) | **Nouveau.** Juste avant `done` |
| `adjust` | `proposal` (`AdjustProposal` + `portfolio: Portfolio \| null`) | **Nouveau.** Mode `adjust` |
| `thinking` | `agent`, `source`, `text` | **Nouveau.** Réflexion des modèles (facultatif à afficher) |
| `error` | `code`, `message` | **Nouveau.** Le flux s'arrête sans `done` |
| `heartbeat` | rien | **Nouveau.** Toutes les 10 s sans activité, à ignorer |
| `done` | rien | Fin |

Les types marqués « Nouveau » ne sont pas encore dans `PipelineEvent`. Le frontend actuel les ignore sans erreur.

### Correspondance des agents

| Frontend | Backend |
|---|---|
| Éclaireur | Agent Profil + exclusions de l'univers (FNB seulement, « Exclure ») |
| Compositeur | Traduction des préférences en contraintes + 3 gestionnaires en parallèle |
| Vérificateur | 3 Juges, nouvel essai des portefeuilles non conformes, Chief Risk Officer |

### Traduction des préférences (`contract.py`)

- **Exclure (−2)**: exclusion dure dans les 3 portefeuilles. `vehicles: "fnb"` exclut les titres individuels.
- **Classes d'actifs**: chaque portefeuille part de la répartition de `classWeights` (engine.ts), avec une bande
  de ±20 %. « Moins » abaisse le plafond, « Plus » et « Imposer » relèvent le plancher. Prudent met de côté les
  demandes de plus de risque (actions, immobilier, or, crypto) et l'écrit dans `agentNotes`.
- **Régions, thèmes, facteurs**: poids minimal (Plus, Imposer) ou maximal (Moins), plus fort pour Conviction.
- **Sécurité, jamais assouplie**: aucune ligne au-delà de 40 %, au moins 3 placements, crypto ≤ 20 %, chaque
  action individuelle ≤ plafond du profil (5 à 15 %).
- **Faisabilité**: si la combinaison est impossible, le code assouplit d'abord les facteurs, puis les thèmes, les
  régions et les classes (Conviction assouplit la répartition du mandat avant les préférences). Chaque préférence
  assouplie est signalée dans `agentNotes`.

### Classement de l'univers (`classify.py`)

Le dataset ne contient pas les catégories du frontend. Elles sont déduites:
- **classe**: `asset_class`/`category_group` du notebook (Equities, Fixed Income, Alternative, Commodities), puis mots
  du nom (bond, gold, REIT, money market…);
- **région**: pays, mots du nom (Emerging, EAFE, S&P 500…), suffixe boursier (`.TO`, `.PA`). Les FNB mondiaux sont
  « monde » et les préférences régionales ne les touchent pas;
- **thèmes**: secteur et mots du nom. **Facteurs**: `market_cap`, mots du nom, et momentum calculé (tiers supérieur
  du rendement cumulé);
- **liquidités**: une ligne d'encaisse `CASH-CAD` (rendement = taux sans risque, volatilité nulle) est ajoutée;
- **frais**: `expense_ratio` si la colonne existe, sinon une estimation (FNB 0,20 %, crypto 0,40 %, action 0 %).

### Métriques (`Portfolio.metrics`)

`expectedReturn` mélange la moyenne historique et l'hypothèse de la classe (`CLASS_ASSUMPTIONS` du frontend), à 50/50
par défaut (`MU_SHRINK`), car le dataset couvre moins d'un an. `volatility` vient de la covariance historique.
`worstYear`, `var95` et `es95` utilisent les mêmes formules que `metricsOf` (engine.ts). `maxDrawdown` est historique.

## Contrat interne (scripts de développement)

`{"mode": "initial", "form": InvestorForm}` et `{"mode": "refine", "message", "context"}` restent disponibles
(`scripts/run_local.py`). Ils renvoient les événements internes (`status`, `thinking`, `tool`, `result`…).

## Structure

| Fichier | Rôle |
|---|---|
| `main.py` | Point d'entrée AgentCore, aiguillage par `mode` |
| `web_pipeline.py` | Pipeline du frontend et traduction des événements en `PipelineEvent` |
| `web_adjust.py` | Chat d'ajustement (agent Pépite, puis un seul portefeuille recalculé) |
| `contract.py` | Modèles du frontend, `risk_score`, préférences → contraintes, faisabilité, `Portfolio` |
| `classify.py` | Classes, régions, thèmes, facteurs, frais de chaque actif |
| `mandates.py` | Prudent, Équilibré, Conviction |
| `selection.py` | Sélection déterministe (repli des PM, test de faisabilité) |
| `orchestrator.py` | Pipeline du contrat interne |
| `agents/` | Profil, Extraction, PM, Juge, CRO |
| `constraints.py`, `optimizer.py` | Catalogue, vérification, optimisation (code pur) |
| `tools.py`, `data.py`, `events.py`, `schemas.py` | Outils Strands, données, bus d'événements, contrats Pydantic |

## Déploiement sur AgentCore Runtime (déploiement par code, arm64)

```bash
./scripts/build_package.sh        # produit build/deployment_package.zip (~130 Mo, limite 250 Mo)
```

Puis créer le runtime (console, CLI `agentcore` ou `create_agent_runtime`, voir la
[documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html)).
Point d'entrée `main.py`, runtime `PYTHON_3_13`, réseau `PUBLIC`. Variables d'environnement: `MODEL_STRONG`, `MODEL_FAST`,
`DATASET_PATH` (par défaut `data/universe.parquet`, inclus dans le zip si présent).

Le rôle d'exécution doit autoriser `bedrock:InvokeModel` et `bedrock:InvokeModelWithResponseStream` sur les profils
d'inférence utilisés (et sur les modèles sous-jacents dans les régions concernées), ainsi que `s3:GetObject` si le dataset
est lu depuis S3. Pour l'appel depuis l'EC2: `bedrock-agentcore:InvokeAgentRuntime` sur l'ARN du runtime.

## Principes de conception

- Les agents proposent, le code garantit. Poids, métriques et conformité viennent de `optimizer.py` et
  `constraints.evaluate`. Le texte des agents ne contient aucun chiffre qui n'en vienne pas.
- Une contrainte dure ne peut pas être modifiée par un agent: elle est appliquée par l'optimiseur et revérifiée
  indépendamment par le Juge.
- Aucune donnée n'est conservée côté serveur. Le frontend renvoie profil et préférences à chaque appel.

## Limites connues

- Le dataset de `make_sample_dataset.py` est synthétique (mêmes FNB que le notebook, prix inventés). Le vrai
  dataset vient de `data-prep/build_universe.py`.
- Les actifs cotés depuis moins de 120 jours (FDXF, HONA, VYLR à la construction) sont écartés au chargement.
- Le classement de l'univers repose en partie sur le nom des placements. Les FNB d'allocation (AOA, AOK…) sont
  classés en actions alors qu'ils contiennent des obligations.
- Le dataset réel ne contient ni or physique ni marché monétaire: « Or » se limite à COMT (matières premières) et
  les liquidités à l'encaisse ajoutée par le backend.
- La réflexion du modèle arrive surtout en anglais malgré la consigne.
- Un parcours complet prend environ 70 s et un ajustement environ 45 s.

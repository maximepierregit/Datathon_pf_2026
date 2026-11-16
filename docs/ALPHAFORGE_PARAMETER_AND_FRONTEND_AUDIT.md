# AlphaForge / MonPort — Audit des paramètres et des calculs front-end

> **Nature du document.** Analyse en lecture seule du dépôt `datathon-pf-2026`. Aucun code, paramètre ni formule n'a été modifié.
> **Date de l'analyse :** 2026-11-16.
> **Langue :** français.

## Table des matières

0. [Périmètre, méthode et conventions](#0-périmètre-méthode-et-conventions)
1. [Partie 1 — Cartographie des paramètres (backend)](#partie-1--cartographie-des-paramètres-backend)
   - [1.A Rendements espérés et CAPM](#1a-rendements-espérés-et-capm)
   - [1.B Matrice de covariance](#1b-matrice-de-covariance)
   - [1.C Aversion au risque et profils](#1c-aversion-au-risque-et-profils-investisseur)
   - [1.D Agent, sentiment et ajustements](#1d-agent-sentiment-et-ajustements)
   - [1.E Optimisation de portefeuille](#1e-optimisation-de-portefeuille)
   - [1.F Autres paramètres](#1f-autres-paramètres)
   - [1.G Section spéciale : profils et aversion au risque](#1g-section-spéciale--profils-et-aversion-au-risque)
2. [Partie 2 — Audit des calculs du front-end](#partie-2--audit-des-calculs-du-front-end)
3. [Partie 3 — Synthèse consolidée](#partie-3--synthèse-consolidée)
   - [3.A Inventaire maître](#3a-inventaire-maître-des-paramètres)
   - [3.B Matrice de responsabilités front vs backend](#3b-matrice-de-responsabilités-front-vs-backend)
   - [3.C Constats prioritaires](#3c-constats-prioritaires)
4. [Éléments non vérifiés](#4-éléments-non-vérifiés)

---

## 0. Périmètre, méthode et conventions

### 0.1 Périmètre retenu (décisions de l'utilisateur)

| Décision | Application |
|---|---|
| Langue | Français |
| Code déployé seulement | Les chemins actifs depuis `backend/main.py` sont documentés. Le code inactif n'apparaît que lorsqu'il crée un doublon ou une valeur en conflit avec le chemin actif. Il est alors étiqueté **legacy**. |
| Tests, `data-prep/`, dossiers générés | **Exclus** (`backend/tests/`, `data-prep/`, `.venv`, `node_modules`, `dist`, `build`, caches). La consigne « Prend les pas en compte » a été lue comme « ne les prends pas en compte ». |

### 0.2 Chemin actif (vérifié par lecture des imports)

- Point d'entrée : `backend/main.py` (l.22 à 44) associe les modes `monport_check`, `monport`, `monport_chat`, `monport_rebuild` aux flux de `workflow/flow.py` (l.294 à 311).
- Chaîne : `workflow/flow.py` → `monport.py` (profils, S, A, contraintes) → `workflow/workers.py` → `agents/portfolio_manager.py` → `allocator.py` (`optimize_with_relaxation`, `optimize_universe`, `select_holdings`) → `optimizer.py` (`_linear_lp`, `_solve_slsqp`, `optimize_weights`) ; `catalog.py` (`settings_for`, `plan_for`, `agent_request`) → `config.get_agent_settings` ; `market.py` (`get_market`, `estimate_expected_returns`, `universe_covariance`) ; `backtest.py`, `projection.py`, `factors.py`, `guardrail.py`, `runtime.py`.
- **Mode agent actif.** `catalog.settings_for` (`catalog.py:604`) appelle `get_agent_settings`, donc `CONSTRAINTS` est la base en production, pas `BASE_CONSTRAINTS`.
- Point d'entrée distinct : `backend/mcp_server/main.py` → `tool_core.py`. Il utilise `allocator.optimize` (legacy pour le workflow principal, voir 0.3).

### 0.3 Code legacy ou inerte (signalé pour éviter les faux positifs)

| Élément | Où | Statut | Preuve |
|---|---|---|---|
| `BASE_CONSTRAINTS`, `BASE_PROFILE`, `get_base_settings` | `config.py:464`, `:573` | Simulation et CLI `optimizer.main` seulement | `settings_for` n'utilise que le mode agent |
| `CANDIDATES`, `constraints.select_candidates` | `config.py:291` | Inutilisé par MonPort (« MonPort n'en a plus besoin ») | Commentaire `config.py:~287` |
| `optimizer.estimate_expected_returns`, `optimizer.estimate_covariance` | `optimizer.py:174`, `:276` | Pipeline autonome (`optimize_portfolio`, CLI). Doublons de `market.estimate_expected_returns` | `build_market` appelle `market.py:439` |
| `MANDATES` (`mandates.py:26-61`) | `mandates.py` | Non référencé. Le workflow construit ses `Mandate` avec `vol_cap_factor=None` (`workers.py:191`) | `vol_cap_for` renvoie toujours `None` |
| `allocator.optimize` | `allocator.py:183` | Hors sélection du workflow. Reste actif via `_raise_volatility_cap` (`monport.py:742`) et `mcp_server` | |
| `BOND_SHIFT` | `monport.py:138` | Tout à 0.0, non utilisé | |
| `config.BACKTEST`, `config.REGIMES` | `config.py:418`, `:430` | `enabled: False`, sans lien avec `backtest.py` | |

### 0.4 Légende

- **Type** : *Constante en dur* (littéral dans une fonction ou un module), *Réglage configurable* (clé de `config.py`), *Argument de fonction*, *Paramètre dérivé*, *Entrée utilisateur dynamique*, *Estimé* (calculé sur les données, non choisi).
- **Lignes** : numéros relevés par `grep -n` sur les fichiers du dépôt. Un `~` signale une valeur approximative.
- **non vérifié** : je n'ai pas pu confirmer l'information dans le code.
- Les chemins sont relatifs à `backend/src/invest_agents/` (abrégé **`ia/`**), sauf indication contraire. Le front-end est sous `frontend/src/`.
- Les tableaux fusionnent certaines des 13 colonnes demandées pour rester lisibles : *Composant et Catégorie* ensemble, *Objectif et Formule* ensemble, *Dépendances et Configurabilité* ensemble.

---

# Partie 1 — Cartographie des paramètres (backend)

## 1.A Rendements espérés et CAPM

Formules (`ia/market.py:47-115`, méthode active ; `ia/optimizer.py:174` est son doublon legacy) :

- Historique : `μ = moyenne(rendements quotidiens) × periods_per_year`.
- EWMA : poids `0.5^(âge / demi-vie)`, `μ = moyenne pondérée × periods_per_year`.
- CAPM avec rétrécissement : `μ = α·(rf + β·ERP) + (1−α)·μ_hist`. β = cov(titre, SPY) / var(SPY) sur les dates communes.
- Repli : si β est indisponible (historique commun trop court), `μ = μ_hist` et la méthode est notée `historical_fallback` (`market.py`, log « repli sur la méthode historique »).

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `RF_ANNUAL` | `0.035` | `Market.risk_free_rate`, `build_market`, `_best_sharpe`, `backtest()` | `ia/config.py:94` ; lu `ia/market.py:293`, `:438` ; `ia/allocator.py:119` | Config / Returns | Réglage configurable (défini une seule fois) | Taux sans risque. Cible CAPM `rf + β·ERP`, et Sharpe `(μ−rf)/σ` | Hausse : cible CAPM plus haute, Sharpe plus bas | Copié dans `capm_shrinkage.rf_annual` (l.132) et `capm_benchmark_shrinkage.rf_annual` (l.141). Modifiable en éditant `config.py` seulement. Hypothèse de démonstration (commentaire l.92-93) |
| `ESTIMATION.mode` | `"by_asset_class"` | `get_return_method` | `ia/config.py:99` ; `:746` | Config / Returns | Réglage configurable | Sélection de la méthode par classe, type ou symbole | Change la formule de μ par titre | `single_method` (l.100, `"historical"`) ne s'applique que si `mode == "single_method"` |
| `method_by_asset_class` | Equity→`capm_shrinkage` ; Fixed Income, Multi-Asset, Real Estate, Commodities, Alternative→`historical` | `get_return_method` | `ia/config.py:104-111` | Config / Returns | Réglage configurable | Règle de choix de méthode | Les obligations ont un μ purement historique. Les ETF d'actions passent aussi par le CAPM (ils sont `Equity`) | Priorité : symbole > type d'instrument > classe (non relu ligne à ligne : non vérifié) |
| `method_by_instrument_type` | `{"Cryptocurrency": "ewma"}` | idem | `ia/config.py:114` | Config / Returns | Réglage configurable | EWMA pour la crypto directe | | |
| `method_by_symbol` | `{"BITW": "ewma"}` | idem | `ia/config.py:115` | Config / Returns | Réglage configurable | EWMA pour l'ETP crypto | | |
| `historical.lookback_observations` | `None` (tout l'historique du titre) | `_historical_mu` | `ia/config.py:119` ; `ia/market.py:47` | Config / Returns | Réglage configurable | Fenêtre de μ historique | Une fenêtre plus courte rend μ plus réactif et plus bruité | « avant : 1260 » (commentaire). μ n'exige pas de dates communes |
| `historical.min_observations` | `120` | `_historical_mu` | `ia/config.py:120` | Config / Returns | Réglage configurable | Seuil d'historique minimal. Sinon `ValueError` | Hausse : plus de titres exclus | Aussi utilisé pour `historical_lookback` du CAPM (`market.py`) |
| `ewma.half_life_observations` | `90` | `_ewma_mu` | `ia/config.py:124` ; `ia/market.py:53` | Config / Returns | Réglage configurable | Poids `0.5^(âge/90)` | Baisse : μ plus réactif, plus volatil | `ewma.min_observations = 120` (l.125), `ewma.lookback_observations = None` (l.123) |
| `capm_shrinkage.market_proxy` | `"SPY"` | `estimate_expected_returns` | `ia/config.py:131` | Config / Returns | Réglage configurable | Benchmark unique du CAPM actif | Change β de tous les titres `Equity` | Un seul proxy : le même pour actions canadiennes, européennes, etc. |
| `capm_shrinkage.erp_annual` | `0.05` | idem | `ia/config.py:133` | Config / Returns | Réglage configurable (hypothèse) | Prime de risque actions dans `rf + β·ERP` | Hausse : cible CAPM plus haute, μ des actions plus haut | Commentaire : « hypothèse illustrative, pas une donnée live » |
| `capm_shrinkage.alpha` | `0.50` | idem | `ia/config.py:134` | Config / Returns | Réglage configurable | Poids de la cible CAPM : `μ = α·CAPM + (1−α)·hist` | Hausse : μ plus proche du CAPM, moins de la performance passée | Même valeur dans `capm_benchmark_shrinkage.alpha` (l.142) |
| `capm_shrinkage.min_paired_observations` | `120` | `_beta` | `ia/config.py:130` ; `ia/market.py:62` | Config / Returns | Réglage configurable | Dates communes minimales pour β. Sinon repli historique | Hausse : plus de replis | |
| `capm_shrinkage.lookback_observations` | `None` | `_beta` | `ia/config.py:129` | Config / Returns | Réglage configurable | Fenêtre de β | | « avant : 756 » |
| `capm_shrinkage.historical_lookback_observations` | `None` | `_historical_mu` | `ia/config.py:135` | Config / Returns | Réglage configurable | Fenêtre de la composante historique | | « avant : 1260 » |
| β | Estimé (cov/var avec SPY) | `_beta` | `ia/market.py:62-72` | Backend / Returns | **Estimé** (non choisi) | Sensibilité au marché | | `None` si variance du benchmark ≤ 0 |
| `capm_benchmark_shrinkage.*` | `alpha 0.50`, `min_paired_observations 120`, `erp_annual_by_benchmark {}`, `missing_premium_policy "error"`, `missing_benchmark_policy "error"` | `estimate_expected_returns` | `ia/config.py:137-148` | Config / Returns | Réglage configurable | Méthode CAPM par benchmark | **Aucune classe ne la sélectionne** : inactive en production | `erp_annual_by_benchmark` est vide : l'activer sans la remplir lève une erreur |
| `BENCHMARKS.single_market_proxy` | `"SPY"` | `get_capm_benchmark` | `ia/config.py:157+` | Config / Returns | Réglage configurable | Proxy global | | Utilisé seulement par `capm_benchmark_shrinkage` (inactive) |
| `BENCHMARKS.symbol_overrides` | `{"NVDA": "SMH"}` | `get_capm_benchmark` | `ia/config.py:163` | Config / Returns | Réglage configurable | Benchmark individuel | | Inactif en production (méthode inactive) |
| `BENCHMARKS.etf_overrides` | 13 paires (SPY↔IYY, QQQ→SPY, XLK→SPY, VGT→SPY, SMH→SPY, XIU.TO↔XIC.TO, EFA→ACWX, EEM→ACWX, EWQ/EWG/EWU→VGK) | idem | `ia/config.py:~168-184` | Config / Returns | Réglage configurable | Mapping ETF → benchmark | | Inactif en production |
| `BENCHMARKS.stock_country_sector` | 17 clés (« United States\|Information Technology »→XLK, … « Canada\|Financials »→XFN.TO, …) | idem | `ia/config.py:~187-204` | Config / Returns | Réglage configurable | Mapping pays et secteur → ETF | | Inactif en production |
| `DATA.periods_per_year` | `252` | `_historical_mu`, `_ewma_mu`, `build_market` | `ia/config.py:40` ; `ESTIMATION.periods_per_year` l.98 | Config / Returns | Réglage configurable | Annualisation de μ et de `ann_vol` | Mal calibré : biais proportionnel de μ | Validé identique entre DATA, ESTIMATION et COVARIANCE (`validate_settings`, `config.py:911`). **Autre valeur : voir 1.B (annualisation de Σ)** |
| `ESTIMATION.forecast_horizon_years` | `1` | non vérifié | `ia/config.py:97` | Config / Returns | Réglage configurable | Horizon de prévision | non vérifié | Usage non confirmé |

**Constats de la section A**

- La méthode CAPM active n'utilise qu'**un seul benchmark (SPY)** pour toutes les actions. Les mappings sectoriels et pays de `BENCHMARKS` ne servent pas en production.
- Les ETF d'actions (classe `Equity`) reçoivent aussi le CAPM sur SPY (SPY lui-même obtient β = 1). Le commentaire de `config.py` (l.~101-103) signale que le look-through des ETF reste à gérer avant d'activer un CAPM personnalisé.
- `rf = 0.035` est défini une seule fois. Le cash (1 %) est volontairement distinct (voir 1.E).

## 1.B Matrice de covariance

Formules (`ia/market.py:119-322`, active) :

- Σ_quotidienne = estimateur Ledoit-Wolf, cible `μ·I` (`μ = trace/p`), intensité `β/δ` estimée.
- Univers d'optimisation : rendements **synchronisés** sur les dates communes (indice de rendement total par titre, jours fériés absorbés dans un rendement de plusieurs jours).
- `Σ_annuelle = Σ_quotidienne × periods_per_year_effective`, avec `periods_per_year_effective = observations_communes / années` et `années = jours / 365.25`.

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `COVARIANCE.method` | `"ledoit_wolf"` | `estimate_covariance`, `ledoit_wolf_universe` | `ia/config.py:227` ; `ia/market.py:119`, `:262` | Config / Covariance | Réglage configurable | Choix de l'estimateur (`sample` en alternative) | `sample` : pas de rétrécissement, matrice potentiellement mal conditionnée | `COVARIANCE_HISTORY.method` (l.267) répète « ledoit_wolf » |
| Intensité de rétrécissement Ledoit-Wolf | Estimée (`shrinkage = β/δ`) | `_ledoit_wolf`, `LedoitWolf.fit` | `ia/market.py:~155-165`, `:~280` | Backend / Covariance | **Estimé** | Rétrécit Σ vers `μ·I` | Plus de rétrécissement : variances et corrélations tirées vers la moyenne | Rapporté dans `shrinkage_coefficient` du diagnostic (`market.universe_covariance`) |
| `ledoit_wolf.target` | `"scaled_identity"` | non lu par le code actif | `ia/config.py:243` | Config / Covariance | Réglage informatif | Cible du rétrécissement | | Le code actif utilise toujours `μ·I` (non vérifié qu'il lise cette clé) |
| `ledoit_wolf.shrinkage_intensity` | `"auto"` | non vérifié | `ia/config.py:~244` | Config / Covariance | Réglage informatif | | | Non lu dans `market.py` (non vérifié) |
| `ledoit_wolf.assume_centered` | `False` | `ledoit_wolf_universe` | `ia/config.py:244` ; `ia/market.py:~277` | Config / Covariance | Réglage configurable | Centrage des données | `True` ignore la moyenne : Σ légèrement plus grande | |
| `ledoit_wolf.block_size` | `1000` | `optimizer.estimate_covariance` (legacy) | `ia/config.py:245` | Config / Covariance | Réglage configurable | Taille de bloc sklearn | Aucun effet numérique | Non utilisé par `market.py` (non vérifié) |
| `COVARIANCE.lookback_observations` | `None` | `joint_window`, `build_market` | `ia/config.py:230` ; `ia/market.py:~128`, `:440` | Config / Covariance | Réglage configurable | Fenêtre de Σ (et de `ann_vol`) | | « avant : 1260 » |
| `COVARIANCE.min_observations_per_asset` | `120` (dérivé de `DATA`) | `optimizer.estimate_covariance` (legacy) | `ia/config.py:231` | Config / Covariance | Paramètre dérivé | | | |
| `COVARIANCE.min_joint_observations` | `120` | `joint_window`, `ledoit_wolf_universe` | `ia/config.py:235` ; `ia/market.py:~126`, `:~270` | Config / Covariance | Réglage configurable | Dates communes minimales. Sinon erreur | Hausse : exclut plus de portefeuilles | |
| `COVARIANCE.missing_policy_for_ledoit_wolf` | `"complete_cases_after_selection"` | `optimizer.estimate_covariance` (legacy) | `ia/config.py:233` | Config / Covariance | Réglage configurable | Aucun remplissage des NaN | | `never_fill_missing_returns True` (`DATA`, l.44) |
| `sample.min_pairwise_observations` | `60` | `market.estimate_covariance` | `ia/config.py:237` | Config / Covariance | Réglage configurable | Observations minimales par paire (méthode `sample`) | | Inactif tant que la méthode est `ledoit_wolf` |
| `sample.repair_psd` | `True` | idem | `ia/config.py:238` | Config / Covariance | Réglage configurable | Réparation PSD | | Inactif |
| `sample.eigenvalue_floor` | `1e-10` | idem | `ia/config.py:239` ; `ia/market.py:~148` | Config / Covariance | Réglage configurable | Plancher de valeur propre | | Inactif |
| `COVARIANCE_HISTORY.start_date` | `"2021-01-01"` | `history_filter` | `ia/config.py:265` ; `ia/market.py:~179` | Config / Covariance | Réglage configurable | Début de l'horizon. Un titre sans rendement à cette date est exclu de l'univers d'optimisation | Reculer la date : plus de titres admissibles, historique commun plus long | **Paramètre structurant** pour la taille de l'univers |
| `COVARIANCE_HISTORY.require_full_horizon` | `True` | `history_filter` | `ia/config.py:266` | Config / Covariance | Réglage configurable | Exige l'historique complet | `False` : n'exclut plus aucun titre | |
| `COVARIANCE_HISTORY.max_start_delay_business_days` | `5` | `history_filter` | `ia/config.py:268` ; `ia/market.py:~190` | Config / Covariance | Réglage configurable | Tolérance de calendrier | Hausse : accepte des titres plus récents | Borné à 0-10 par `validate_settings` (`config.py:911`) |
| `periods_per_year_effective` | Estimé : `n_communes / (jours/365.25)` | `synchronized_returns`, `Market.universe_covariance` | `ia/market.py:250`, `:257`, `:312` | Backend / Covariance | **Estimé** (dérivé) | Annualise Σ | Une période effective ≠ 252 change la volatilité de tous les titres | **Incohérence : voir ci-dessous** |
| Tolérance PSD (optimiseur) | `-1e-8` | `optimize_weights` | `ia/optimizer.py:478` | Backend / Covariance | Constante en dur | Refuse Σ non semi-définie positive | | |
| Symétrisation | `(Σ+Σᵀ)/2` | `ledoit_wolf_universe`, `optimize_weights` | `ia/market.py:~286` ; `ia/optimizer.py:477` | Backend / Covariance | Constante en dur (opération) | | | |
| Tolérances PSD legacy | `-1e-10`, floor `sample.eigenvalue_floor` | `optimizer.estimate_covariance` | `ia/optimizer.py:349` | Backend / Covariance | Constante en dur (legacy) | | | Pipeline autonome seulement |

**Incohérence d'annualisation (constat vérifié dans le code)**

- μ et `ann_vol` annualisent avec **252** (`DATA.periods_per_year`).
- Σ de l'univers annualise avec `periods_per_year_effective` (`n / (jours/365.25)`), qui n'est pas forcément 252 (`market.py:312` : `info["periods_per_year_effective"] or float(252)`).
- Conséquence : `ann_vol` (écrans, tri, Sharpe de screening) et `sqrt(diag Σ)` (volatilité du portefeuille) ne sont pas calculés avec la même base. L'écart dépend du nombre de dates communes retenues. Je n'ai pas exécuté le code, donc l'ampleur de l'écart n'est **pas vérifiée**.
- `market.moments` utilise `estimate_covariance` (LW non synchronisé, annualisé à 252) pour tout symbole **hors** de l'univers d'optimisation (`market.py:~383`).

## 1.C Aversion au risque et profils investisseur

Détail complet des formules en [1.G](#1g-section-spéciale--profils-et-aversion-au-risque). Ce tableau liste les valeurs.

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `RISK_AVERSION.min` / `.max` | `1.0` / `25.0` | `apply_portfolio_request`, `catalog.agent_request` | `ia/config.py:310-311` ; `ia/catalog.py:573-575` | Config / Risk Aversion | Réglage configurable | Plage permise de A | | **Dupliqué** : `allocator.A_MIN, A_MAX = 1.0, 25.0` (`allocator.py:45`) et `PepiteCheck.risk_aversion` ge=1, le=25 (`ia/schemas.py:318`) |
| `RISK_AVERSION.default` | `5.0` | `apply_portfolio_request` | `ia/config.py:312` | Config / Risk Aversion | Réglage configurable | A si aucun A fourni. Écrasé par `risk_aversion_A` de la requête | | `catalog.agent_request` envoie 5.0 si A est `None` |
| `RISK_AVERSION.bands` | très audacieux ≤ 1.5, audacieux ≤ 3.5, équilibré ≤ 7.0, prudent ≤ 14.0, très prudent ≤ 25.0 | **usage non vérifié** | `ia/config.py:~313-319` | Config / Risk Aversion | Réglage informatif | Étiquettes de bandes de A | | Aucun appelant confirmé |
| `AVERSION_ANCHORS` | `(0,25) (0.2,14) (0.4,7) (0.6,3.5) (0.8,1.5) (1,1)` | `risk_aversion` | `ia/monport.py:151` | Backend / Risk Aversion | Constante en dur | Ancres de l'interpolation log S → A | Modifie la pente de A le long de S | **Dupliqué** dans `frontend/src/lib/engine.ts:69` |
| `VOL_ANCHORS` | `(0,0.06) (0.2,0.08) (0.4,0.11) (0.6,0.14) (0.8,0.18) (1,0.25)` | `assess`, `slot_volatility` | `ia/monport.py:152` | Backend / Risk Aversion | Constante en dur | Plafond de volatilité par S (filet de sécurité) | Hausse : portefeuilles plus volatils permis | **Dupliqué** dans `engine.ts:92-101` |
| `STOCK_ANCHORS` | `(0,0.07) (0.2,0.09) (0.4,0.11) (0.6,0.13) (0.8,0.17) (1,0.22)` | `assess`, `build_profiles` | `ia/monport.py:153` | Backend / Risk Aversion | Constante en dur | Plafond par action détenue en direct | | **Dupliqué** dans `engine.ts` |
| `BOND_FLOOR` | conservateur 0.80, modéré 0.60, équilibré 0.40, dynamique 0.20, agressif 0.0 | `follow_profile` | `ia/monport.py:137` | Backend / Risk Aversion | Constante en dur | Plancher d'obligations par catégorie | Hausse : plus d'obligations imposées | **Dupliqué** dans `engine.ts:92-101` |
| `NO_CRYPTO` | `{conservateur, modéré}` | `follow_profile` | `ia/monport.py:141` | Backend / Risk Aversion | Constante en dur | Exclut crypto et « Alternative » pour les profils prudents | | **Dupliqué** dans `engine.ts` |
| `BOND_SHIFT` | tous à `0.0` | non utilisé | `ia/monport.py:138` | Backend / Risk Aversion | Constante en dur (inerte) | | | Legacy : « plus de décalage : seul A distingue les variantes » |
| `SLOT_SHIFT` | `prudent −0.1`, `equilibre 0.0`, `conviction +0.1` | `slot_position` | `ia/monport.py:157` | Backend / Risk Aversion | Constante en dur | Décalage de S par portefeuille (profil cohérent) | Plus grand : variantes plus écartées | **Dupliqué** dans `engine.ts:104-107` |
| `RISK_LABELS` | conservateur, modéré, équilibré, dynamique, agressif | `risk_label` | `ia/monport.py:154` | Backend / Risk Aversion | Constante en dur | Découpage de S en 5 bandes de 0.2 | | Libellés différents côté front (`engine.ts:44`) |
| `OBJECTIVE_TOLERANCE` | `securiser 0.0`, `fructifier 0.5`, `viser-haut 1.0` | `tolerance` | `ia/monport.py:147` | Backend / Risk Aversion | Constante en dur | Contribution de l'objectif à la tolérance T | | **Dupliqué** `engine.ts:43` |
| `CAPACITY_MARGIN` | `0.125` | `risk_position` | `ia/monport.py:148` | Backend / Risk Aversion | Constante en dur | La tolérance ne dépasse pas la capacité de plus de 0.125 | Hausse : la tolérance peut tirer S plus haut | **Dupliqué** `engine.ts:46` |
| `ADJUSTMENT_STEP` | `0.05` | `risk_position` | `ia/monport.py:149` | Backend / Sentiment | Constante en dur | Valeur d'un cran d'ajustement de Pépite | | **Absent du front** |
| Pondérations de la capacité C | `0.6` (horizon), `0.4` (âge) | `capacity` | `ia/monport.py:344` | Backend / Risk Aversion | Constante en dur | `C = 0.6·h + 0.4·a` | | **Dupliqué** `engine.ts:55` et `RiskNotebook.tsx:125-126` |
| Pondérations de la tolérance T | `0.5` (réaction), `0.3` (objectif), `0.2` (confort) | `tolerance` | `ia/monport.py:352` | Backend / Risk Aversion | Constante en dur | `T = 0.5·r + 0.3·o + 0.2·c` | | **Dupliqué** `engine.ts:56` et `RiskNotebook.tsx` |
| Plafond d'horizon | `20` ans | `capacity` | `ia/monport.py:341-343` | Backend / Risk Aversion | Constante en dur | `h = (min(horizon,20) − 1)/19` | | |
| Âge de référence | `75`, diviseur `50` | `capacity` | `ia/monport.py:343` | Backend / Risk Aversion | Constante en dur | `a = (75 − âge)/50` | | |
| `LOSS_BY_REACTION` | `{0:10.0, 1:15.0, 2:25.0, 3:35.0}` (points de %) | `to_form` | `ia/monport.py:128` | Backend / Risk Aversion | Constante en dur | Perte acceptée selon la réaction. Sert au formulaire des agents, pas à S | | **Dupliqué** en fractions `engine.ts:303` |
| `LINE_CAP` | `0.40` | `validate_profile`, `build_profiles`, `_limits` | `ia/monport.py:132` ; `ia/evidence.py:27` ; `engine.ts:9` | Backend / Constraints | Constante en dur | Plafond par ligne, jamais assoupli | | Triple duplication (backend ×2, front) |
| `JUDGE_RELAUNCH_PENALTY` | `3` | juge final | `ia/config.py:288` | Config / Risk Aversion | Réglage configurable | Points (sur 10) retirés à un portefeuille relancé avec contraintes assouplies | | Usage dans le code du juge : non relu (non vérifié) |
| `PepiteCheck.risk_aversion` | ge 1, le 25 | schéma | `ia/schemas.py:318` | Backend / Risk Aversion | Contrainte de schéma | | | Doublon de la plage de `config` |

## 1.D Agent, sentiment et ajustements

**Résultat de la vérification : il n'existe aucun mécanisme de « sentiment », de `ΔS` de sentiment ni de règle `S+1` / `S−1` codés dans le backend.** Un seul mécanisme d'ajustement existe : les **crans de Pépite** (agent LLM), décrits ci-dessous. Aucune règle de code ne convertit une préférence qualitative en nombre de crans : le LLM choisit lui-même la valeur, le code ne fait que la borner.

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `adjust_steps` (cumul des crans) | borné à `[−2, +2]` | `adjust_risk_position` | `ia/workflow/pepite.py:231`, `:243` : `max(-2, min(2, before + int(steps)))` | Agent / Sentiment | **Entrée dynamique** (décidée par le LLM) | Cumul des crans demandés. Chaque cran vaut `ADJUSTMENT_STEP` | ±2 crans = ±0.10 de S, soit une demi-catégorie | Désactivé en phase « chat » (message `IN_CHAT`, `pepite.py:240-241`). Bornage codé en dur |
| `ADJUSTMENT_STEP` | `0.05` | `risk_position` | `ia/monport.py:149`, utilisé `:355-359` | Backend / Sentiment | Constante en dur | `S = clamp(min((C+T)/2, C+0.125) + 0.05·clamp(adj,−2,2), 0, 1)` | Hausse : chaque cran déplace plus S | Le plafond de capacité est appliqué **avant** l'ajustement : la marge `CAPACITY_MARGIN` ne limite donc pas les crans |
| Décision de « combien de crans » | Décidée par le LLM | prompts `BUILD_TASK`, `REBUILD_TASK` | `ia/workflow/pepite.py:~428-431`, `:~474-475` | Agent / Sentiment | Entrée dynamique | Le prompt dit d'utiliser `adjust_risk_position` si le client parle du risque qu'il veut prendre | Non reproductible : dépend du modèle et du texte du client | Aucun seuil ni poids numérique côté code |
| `MAX_ADJUSTMENT` | `1000` caractères | `stream_monport` | `ia/monport.py:133` ; `ia/workflow/flow.py:~201` | Backend / Autre | Constante en dur | Tronque le texte libre d'ajustement | | |
| `session.adjust_steps` → `assess` | passé en 3ᵉ argument | `Session.check` | `ia/workflow/session.py:106-111` ; `ia/monport.py:528-536` | Backend / Sentiment | Paramètre dérivé | Recalcule S, A, plafond de vol., plafond par titre | | |
| `coherent` | booléen décidé par Pépite | `set_coherence`, `fallback_check` | `ia/workflow/pepite.py:250-266` ; `ia/monport.py:539-542` | Agent / Sentiment | Entrée dynamique | Détermine « profil cohérent » ou non, donc la construction des 3 portefeuilles | Bascule la structure entière (voir 1.G) | Repli sans LLM : `coherent = not facts` avec `facts = coherence_facts` (`monport.py:424-443`) |
| Seuils de `coherence_facts` | score < 40 et crypto demandée ; score < 40 et actions ≥ 0.7 ; score > 65 et actions exclues ou ≤ 0.3 ; score < 77 et `vehicles == "titres"` ; une seule classe gardée | `coherence_facts` | `ia/monport.py:424-443` | Backend / Sentiment | Constantes en dur | Détecte une contradiction entre profil et préférences | Modifie la cohérence, donc la structure des 3 portefeuilles | **Dupliqué** dans `engine.ts:306-323` (mêmes seuils 40, 0.7, 65, 0.3, 77) |
| `preference_contradictions` | somme des % de classes ou régions > `1 + 1e-9` | `preference_contradictions` | `ia/monport.py:~388-418` | Backend / Contraintes | Constante en dur | | | |
| `RULES` du front (regex) | tech→`themes.tech 30`, pétrole/fossile→exclusion, crypto/bitcoin→`classes.crypto 10`, prudent/moins de risque→`riskShift −15` | `proposeAdjustment` | `frontend/src/api.ts:~248-296` | Front-end / Sentiment | Constantes en dur (mock) | Simule la réponse de Pépite hors ligne | | **Équivalent backend : aucun** (LLM). Échelle différente (±15 points de score contre ±0.05 sur S par cran) |

**Conséquence.** Les « poids de sentiment » demandés par la consigne n'existent pas. L'influence du texte libre du client sur S passe par un jugement de LLM, borné à ±0.10 de S. C'est un point de calibration et de reproductibilité (voir 3.C).

## 1.E Optimisation de portefeuille

Objectif (`ia/optimizer.py:397-402`) : maximiser `U = μᵀw − (A/2)·wᵀΣw`, avec gradient analytique `−μ + AΣw` (le code minimise `−U`).

### Contraintes et plafonds

| Paramètre | Valeur actuelle (production) | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `CONSTRAINTS.max_weight_per_asset` | `None` | `apply_portfolio_request`, `build_constraint_plan` | `ia/config.py:340` | Config / Constraints | Réglage configurable | Plafond par actif. **Aucun plafond global en production** | | Le plafond effectif vient de `MAX_POSITION_WEIGHT` (0.40) ajouté par `monport.validate_profile` et de `MAX_STOCK_WEIGHT` |
| `BASE_CONSTRAINTS.max_weight_per_asset` | `0.10` | | `ia/config.py:481` | Config / Constraints | Réglage configurable | **Mode BASE seulement (inactif)** | | **Conflit de défaut** : 0.10 (BASE) contre `None` (production) |
| `MAX_POSITION_WEIGHT` (`LINE_CAP`) | `0.40` | `validate_profile`, `_limits`, `agent_request` | `ia/monport.py:132`, `:666-681`, `:564-568` ; `ia/catalog.py:562` | Backend / Constraints | Constante en dur | Plafond par ligne, FNB compris. Jamais assoupli par `RELAXATION_STEPS` | | |
| `MAX_STOCK_WEIGHT` | `min(STOCK_ANCHORS(S), 0.40)` | `build_profiles`, `validate_profile` | `ia/monport.py:781-783`, `:~675` | Backend / Constraints | Paramètre dérivé | Plafond par action en direct | | Non appliqué à « Tes préférences » du profil incohérent (`monport.py:781`) |
| `min_held_weight` | `0.01` | `_active_set_plan`, `restrict_plan`, `_weights` | `ia/config.py:334`, `:280`, `:471` ; `ia/allocator.py:44` | Config / Constraints | Réglage configurable (**4 copies**) | « 0 ou au moins 1 % » | Hausse : moins de positions | **Dupliqué** : `CONSTRAINTS` (l.334), `PORTFOLIO_HOLDINGS` (l.280), `BASE_CONSTRAINTS` (l.471), `allocator.MIN_POSITION_WEIGHT` (l.44) et textes « 1 % » en dur (`constraints.py:~814`, `~934`) |
| `minimum_holding_max_iterations` | `30` | `optimize_weights` | `ia/config.py:336` | Config / Solver | Réglage configurable | Itérations de la méthode prune/reoptimize | | Le code lit une boucle bornée par le nombre d'actifs (non vérifié que cette clé est lue) |
| `minimum_holding_tolerance` | `1e-8` | `optimize_weights` | `ia/config.py:337` | Config / Solver | Réglage configurable | Tolérance de micro-position | | Distinct de `constraint_tolerance` |
| `min_cash_weight` / `max_cash_weight` | `0.0` / `1.0` | `settings_for` | `ia/config.py:348-349` | Config / Constraints | Réglage configurable | **Neutralisé en production** : `settings["cash"]["enabled"]=False` et `min_cash_weight=0.0` | | `ia/catalog.py:605-606`. `max_cash_weight` n'est jamais transmis par `agent_request` |
| `CASH.annual_expected_return` | `0.01` | `optimize_weights` | `ia/config.py:394` ; `ia/optimizer.py:467` | Config / Returns | Réglage configurable (hypothèse) | μ du cash synthétique | | **Inactif en production** (cash désactivé) |
| `CASH.annual_volatility` | `0.0` | `optimize_weights` | `ia/config.py:395` | Config / Covariance | Réglage configurable | | | Un cash non nul en volatilité lève une erreur (`optimizer.py:471-472`) |
| `group_limits` (`CONSTRAINTS`) | tous vides | `apply_portfolio_request` | `ia/config.py:~353-363` | Config / Constraints | Réglage configurable | Plafonds de groupe vides. Les groupes viennent des contraintes du client (`MIN_ASSET_CLASS_WEIGHT`, parts) | | `BASE_CONSTRAINTS.group_limits` (l.519-549) est **inactif** : Alternative 0.05, Commodities 0.10, Real Estate 0.15, Cryptocurrency 0.05, IT 0.25, Financials 0.30, Energy 0.20, emergents 0.15 |
| `unknown_exposure_policy` | `"strict"` (défaut `constraints.py`, mode agent) ; `"flag"` (BASE) | `filter_eligible_universe` | `ia/constraints.py:~360` ; `ia/config.py:563` | Config / Constraints | Réglage configurable | Traitement d'un ETF à exposition inconnue face à un plafond | | |
| `instrument_selection` | `"mixed"` par défaut | `apply_portfolio_request` | `ia/config.py:~342` ; `INSTRUMENT_SELECTION` | Config / Constraints | Réglage configurable | etf_only, mixed, stocks_only | | |
| `FACTOR_SLEEVE_MIN` | `0.10` | `plan_for`, `_factor_groups` | `ia/catalog.py:156` | Backend / Constraints | Constante en dur | Au moins 10 % en actions notées si un facteur est contraint | | |
| `FACTOR_MARGIN` | `0.01` | idem | `ia/catalog.py:157` | Backend / Constraints | Constante en dur | L'optimiseur vise 1 point au-delà du seuil | | |
| `FACTOR_LEVELS` | `{2:0.5, 1:0.2, −1:−0.2, −2:−0.5}` | `preference_constraints` | `ia/monport.py:113` | Backend / Constraints | Constante en dur | Niveau du questionnaire → exposition cible (écarts-types) | | **Dupliqué** `frontend/src/data/catalog.ts:160` |
| `FTOL` / `EXACT_TOL` / `SCORE_RANGE` | `0.01` / `1e-3` / `3.0` | `evaluate`, `audit` | `ia/catalog.py:158`, `:154`, `:155` | Backend / Constraints | Constantes en dur | Tolérances et bornes des contraintes | | |
| `TOL` / `WTOL` / `HELD` | `1e-3` / `2e-4` / `5e-4` | `evaluate`, `audit` | `ia/catalog.py:67-69` | Backend / Constraints | Constantes en dur | Tolérances volatilité, poids, seuil « détenu » | | Autres seuils « détenu » : `1e-7` (`optimizer.py:73`), `1e-9` (`constraints.TOL`, `:36`), `0.005` (`allocator._weights`) |
| `RELAXATION_STEPS` | liste d'assouplissements | `optimize_with_relaxation` | `ia/allocator.py:~560-575`, `:~597-642` | Backend / Constraints | Constante en dur | Ordre d'assouplissement après échec : pourcentages visés, plafonds, exclusions | Détermine ce qui est sacrifié en premier | `MAX_POSITION_WEIGHT` jamais assoupli (`allocator.py:~582`) |
| Cap de volatilité relevé | `ceil((vol_min + 0.003) × 100) / 100` | `_raise_volatility_cap` | `ia/monport.py:745` | Backend / Constraints | Constante en dur | Marge de 0.3 point sur la volatilité minimale atteignable | | |

### Nombre de positions et sélection

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `PORTFOLIO_HOLDINGS.min_count` | `25` | `optimize_universe`, `select_holdings` | `ia/config.py:278` ; `ia/allocator.py:~461-471`, `:339` | Config / Constraints | Réglage configurable | Minimum de positions détenues | | Surchargé par `MIN_POSITIONS` dur du client |
| `PORTFOLIO_HOLDINGS.max_count` | `70` | idem | `ia/config.py:279` | Config / Constraints | Réglage configurable | Maximum de positions | | Surchargé par `MAX_POSITIONS` du client. La docstring de `portfolio_manager.py:4` dit « 25 à 60 (cible 50) » : périmée |
| `PORTFOLIO_HOLDINGS.max_marginal_utility_cost` | `0.0001` | `select_holdings` | `ia/config.py:283` ; `ia/allocator.py:~395-410` | Config / Constraints | Réglage configurable | 1 point de base d'utilité par position ajoutée au-delà du minimum | Hausse : plus de positions | Lots d'ajout de 10 (minimum) et de 5 (diversification) en dur (`allocator.py:~376`, `~409`) |
| `MAX_ASSETS_PER_PORTFOLIO` | `40` (env) | `_check_selection`, `_raise_volatility_cap` | `ia/runtime.py:49` ; `ia/allocator.py:~87` ; `ia/monport.py:740` | Config / Autre | Variable d'environnement | Plafond de titres d'une sélection | | Autre usage : `min(15, …)` dans `tools.py:270`, `:292` |
| `A_LADDER` | `(1.0, 1.5, 2.0, 3.0, 4.5, 7.0, 10.0, 14.0, 18.0, 25.0)` | `_best_sharpe`, `_under_cap` | `ia/allocator.py:47` | Backend / Solver | Constante en dur | Échelle de A parcourue pour max_sharpe et plafond de volatilité | Plus fine : portefeuille plus près de l'optimum | |
| `CAP_REFINEMENTS` | `6` | `_under_cap` | `ia/allocator.py:48` | Backend / Solver | Constante en dur | Pas de dichotomie pour coller au plafond | | |
| `POSITIVE` | `1e-6` | `select_holdings` | `ia/allocator.py:260` | Backend / Solver | Constante en dur | Poids « positif » de la solution continue | | |
| `A_MIN`, `A_MAX` | `1.0`, `25.0` | `_solve`, `optimize_universe` | `ia/allocator.py:45` | Backend / Solver | Constante en dur (**doublon**) | Borne le A passé au solveur | | Doublon de `RISK_AVERSION` |
| A initial `aversion0` | `A_MAX` si `min_volatility` ; `A_MIN` si `max_return` ; sinon `risk_aversion or A_MAX/5` (= 5.0) | `optimize_universe` | `ia/allocator.py:490` | Backend / Risk Aversion | Constante en dur (règle) | A de l'optimum continu et de `select_holdings` | | **Doublon legacy** : `allocator.optimize` utilise `A_MAX/2` (= 12.5) (`allocator.py:216`) |
| Seuil des guides | A ≥ 7 → style « min_volatility » ; A ≥ 3.5 → « max_sharpe » ; sinon « max_return » | `guidance_for` | `ia/monport.py:650-654` | Backend / Autre | Constante en dur | Texte seulement | | |

### Solveur

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `OPTIMIZATION.solver` | `"SLSQP"` | `optimize_weights` | `ia/config.py:~403` | Config / Solver | Réglage configurable | Toute autre valeur lève une erreur | | |
| `solver_options.maxiter` | `2000` | `_solve_slsqp` | `ia/config.py:407` ; `ia/optimizer.py:~412` | Config / Solver | Réglage configurable | Itérations maximales de SLSQP | | `options=dict(cfg["optimization"]["solver_options"])` |
| `solver_options.ftol` | `1e-9` | idem | `ia/config.py:408` | Config / Solver | Réglage configurable | Tolérance de convergence | | |
| `constraint_tolerance` | `1e-7` | `validate_weights` | `ia/config.py:411` | Config / Solver | Réglage configurable | | | |
| `sum_weights_tolerance` | `1e-7` | `validate_weights` | `ia/config.py:412` | Config / Solver | Réglage configurable | | | |
| Seuil de faisabilité LP | `1e-10`, `1e-9` | `_linear_lp` | `ia/optimizer.py:380-381` | Backend / Solver | Constante en dur | Cohérence des bornes | | |
| Micro-position | `tol < w < min_held − tol` | `optimize_weights` | `ia/optimizer.py:~493` | Backend / Solver | Constante en dur (règle) | Déclenche la boucle prune/reoptimize | | |
| `risk_free_rate` du Sharpe | `0.035` | `_best_sharpe`, `portfolio_metrics` | `ia/allocator.py:119` ; `ia/market.py:416` | Backend / Solver | Dérivé de `RF_ANNUAL` | `(μ−rf)/σ` | | |

## 1.F Autres paramètres

### Backtest, projection, risque affiché

| Paramètre | Valeur | Fonction | Fichier : lignes | Type | Objectif et impact |
|---|---|---|---|---|---|
| `LOOKBACK_YEARS` | `6` | `backtest` | `ia/backtest.py:26` | Constante en dur | Fenêtre du backtest. Retourne `None` si l'historique commun fait moins de 252 jours |
| `YEAR` | `252` | `summarize` | `ia/backtest.py:27` | Constante en dur | Annualisation du backtest. **Indépendant** de `DATA.periods_per_year` |
| `BIWEEKLY`, `SAMPLE_EVERY` | `10`, `5` | `rebalance_mask`, `summarize` | `ia/backtest.py:28-29` | Constantes en dur | Rééquilibrage aux deux semaines (10 séances) ; un point de série par semaine |
| `DAILY_STEP`, `DAILY_LIMIT` | `0.5`, `5.0` | `daily_distribution` | `ia/backtest.py:30-31` | Constantes en dur | Tranches de la distribution (points de %), bornées à ±5 % |
| `FREQUENCIES` | deux-semaines, mensuelle, annuelle, aucune | `backtest` | `ia/backtest.py:25` | Constante en dur | Fréquences simulées |
| Quantile VaR/ES | `0.05` | `summarize` | `ia/backtest.py:~106` | Constante en dur | VaR et ES historiques à 1 jour |
| `rf` du backtest | `market.risk_free_rate` | `to_portfolio` | `ia/monport.py:~996` | Dérivé de `RF_ANNUAL` | Sharpe réalisé du backtest |
| `PER_YEAR` | 26, 12, 1, 12 | `project` | `ia/projection.py:20` | Constante en dur | Versements par an. `aucune` composé sur 12 périodes |
| `PATHS` | `1000` | `project` | `ia/projection.py:21` | Constante en dur | Nombre de trajectoires simulées |
| `SEED` | `7` | `project` | `ia/projection.py:22` | Constante en dur | Graine fixe : résultat reproductible |
| `MAX_AMOUNT` | `10 000 000` | `clean_contribution` | `ia/projection.py:23` | Constante en dur | Montant maximal accepté |
| Horizon et centiles | 10 ans ; 5, 25, 75, 95 | `project` | `ia/projection.py:39` ; docstring | Constantes en dur | Cônes probable (25-75) et large (5-95) |
| `BLEND` | `0.8` | `blend` | `ia/monport.py:56` | Constante en dur | Mélange 80/20 des portefeuilles du profil incohérent |
| `FEES` | `{"ETF": 0.002}` | `to_portfolio` | `ia/monport.py:131` | Constante en dur | Frais 0.20 % par FNB, 0 pour un titre direct |
| `worstYear` | `μ − 2.33σ` | `to_portfolio` | `ia/monport.py:989` | Constante en dur | VaR paramétrique 99 % à 1 an, loi normale. `WORST_YEAR_Z = 2.33` dupliqué (`ia/evidence.py:28`) |
| `var95`, `es95` annuels | `−(μ − 1.645σ)`, `−(μ − 2.063σ)` | `to_portfolio` | `ia/monport.py:993-994` | Constantes en dur | Quantile et ES normaux |
| `monthlyVolatility` | `σ/√12` | `to_portfolio` | `ia/monport.py:988` | Constante en dur | |
| `MAX_CITED` | `3` | `evidence.cite` | `ia/evidence.py:29` | Constante en dur | Preuves citées par avertissement |
| Seuils de `diagnostics` | drawdown > perte acceptée ; 2σ > perte acceptée ; `effective_n` < 8 ; secteur > 35 % ; pays > 70 % ; crypto > 5 % ; horizon < 3 ans et volatilité > 15 % | `diagnostics.py` | `ia/diagnostics.py:14-33` (relevés par un sous-agent, non revérifiés) | Constantes en dur | Génèrent les avertissements de risque |

### Agents LLM et exécution (`ia/runtime.py:32-48`)

| Paramètre | Valeur | Source |
|---|---|---|
| `AWS_REGION` | `us-east-1` | variable d'env. |
| `MODEL_STRONG`, `MODEL_FAST` | `global.anthropic.claude-opus-5-5` | variable d'env. |
| `MODEL_PEPITE` | `global.anthropic.claude-sonnet-5-5` | variable d'env. |
| `MODEL_EFFORT` | `high` | variable d'env. |
| `MODEL_MAX_TOKENS` | `16000` | variable d'env. |
| `ENABLE_THINKING` | `True` | variable d'env. |
| `MAX_PM_RETRIES` | `1` | variable d'env. Les demandes de réoptimisation du juge sont ignorées (`workers.py:~310-314`), la boucle ne s'exécute donc pas |
| `GUARDRAIL_ID` | non défini par défaut | Sans identifiant, aucun filtrage ; si le service échoue, le message passe (`ia/guardrail.py:77-92`) |

### Données (`ia/data.py`, `ia/config.py` DATA)

| Paramètre | Valeur | Fichier : lignes | Type | Note |
|---|---|---|---|---|
| `DATA.min_observations` | `120` | `config.py:39` | Réglage configurable | Passé à `prepare_optimizer_data` (`market.get_market`) |
| `min_observations` (défaut de fonction) | `120` | `data.py:426`, CLI `:524` | Argument de fonction | Doublon (la production passe la valeur de `DATA`) |
| `DATA.as_of`, `start_date` | `None`, `None` | `config.py:41-42` | Réglage configurable | Aucune borne |
| `strict_validation`, `never_fill_missing_returns` | `True`, `True` | `config.py:43-44` | Réglage configurable | `validate_settings` lève une erreur si `never_fill_missing_returns` est faux |
| Rendement impossible | `< −1` (−100 %) | `data.py:240` | Constante en dur | Validation |
| FX CAD | `atol 1e-9` ; prix `rtol 1e-6`, `atol 1e-8` ; recalcul `rtol 1e-5`, `atol 1e-7` | `data.py:253`, `:205`, `:261`, `:272` | Constantes en dur | Contrôles de cohérence |
| `macro` | `COUNTRIES (US, CA)`, `MAX_ROWS 1000` | `ia/macro.py:31`, `:36` | Constantes en dur | |
| `factors` | 5 facteurs ; NaN remplacés par `0.0` | `ia/factors.py:33`, `:~52` | Constantes en dur | Le remplissage à 0.0 d'un facteur manquant est une hypothèse implicite (non vérifiée en détail) |
| Poids de score de candidats | `4.0`, `2.0`, `1.0`, `0.5` divisés par `(1 + compte)` | `ia/constraints.py:621-624` | Constantes en dur (**legacy**) | `select_candidates` inactif en production |

---

## 1.G Section spéciale : profils et aversion au risque

Tout ce qui suit est vérifié dans `ia/monport.py` (actif). Les trois portefeuilles ne sont **pas** trois « profils investisseur » prudent / équilibré / agressif prédéfinis avec un A fixe. Ce sont trois **variantes calculées à partir d'un seul score S**, propre à chaque client.

### 1.G.1 Ce qu'on appelle « les trois profils »

- `SLOTS = ["prudent", "equilibre", "conviction"]` (`monport.py:48`).
- Le nom affiché dépend de la cohérence du profil du client (`coherent`, fixée par Pépite) :
  - **Cohérent** : « Variante prudente », « Variante fidèle », « Variante audacieuse » (`VARIANT_NAMES`, `monport.py:63`). Un seul portefeuille est ensuite présenté : le gagnant (`pick_winner`, `:828-836`, « Ton portefeuille »).
  - **Incohérent** : « Ton profil », « Tes contraintes », « Tes préférences » (`BASE_NAMES`, `:54`). Le front présente un mélange 80/20 (`BLEND = 0.8`).

### 1.G.2 Formule du score de risque S (valeurs et lignes exactes)

Entrées : `profile` (âge, horizon, montant, `objective`, `lossReaction`, `comfort`) et `adjustment` (crans de Pépite).

| Étape | Formule | Source |
|---|---|---|
| Horizon normalisé | `h = (min(horizon, 20) − 1) / 19`, borné à [0,1]. Défaut : horizon 10 | `monport.py:340-344` |
| Âge normalisé | `a = (75 − âge) / 50`, borné à [0,1]. Défaut : âge 35 | idem |
| **Capacité** | `C = 0.6·h + 0.4·a` | `:344` |
| Réaction | `r = lossReaction / 3`. Défaut : 2 | `:347-352` |
| Objectif | `o = OBJECTIVE_TOLERANCE[objectif]` = securiser 0.0, fructifier 0.5, viser-haut 1.0. Défaut : 0.5 | `:147` |
| Confort | `c = (comfort − 1) / 4`. Défaut : 3 | `:347-352` |
| **Tolérance** | `T = 0.5·r + 0.3·o + 0.2·c` | `:352` |
| **Position S** | `S = clamp( min((C+T)/2, C + 0.125) + 0.05·clamp(adj, −2, +2), 0, 1 )` | `:355-359` |
| Étiquette | `risk_label(S) = RISK_LABELS[min(4, int(clamp(S)/0.2))]` | `:375-376` |
| Score front | `front_score(S) = floor(5 + 90·S + 0.5)` | `:384-385` |
| Score 1 à 10 (`assess`) | `max(1, min(10, round(1 + 9·S)))` | `:528-536` |

### 1.G.3 Formule de A

- `risk_aversion(S) = round(_interpolate(S, AVERSION_ANCHORS, log=True), 2)` (`monport.py:370-372`).
- Ancres : `S=0 → 25`, `0.2 → 14`, `0.4 → 7`, `0.6 → 3.5`, `0.8 → 1.5`, `1.0 → 1`.
- Interpolation entre deux ancres `(s0,v0)`, `(s1,v1)` : `v0·(v1/v0)^t` avec `t = (S−s0)/(s1−s0)` (`_interpolate`, `:362-367`).
- Valeurs de A aux bornes de bande : S=0.1 → ≈ 18.7 ; S=0.3 → ≈ 9.9 ; S=0.5 → ≈ 4.95 ; S=0.7 → ≈ 2.29 ; S=0.9 → ≈ 1.22. (Calculs à la main à partir des ancres, **non exécutés**.)
- Bornes : aucun `clamp` dans `risk_aversion` ; elles viennent des ancres (1 et 25). Les clamps [1, 25] existent aussi dans `PepiteCheck.risk_aversion` (`schemas.py:318`), `catalog.agent_request` (`:573-575`) et `allocator._solve` (`:111`).

### 1.G.4 A et plafonds selon le portefeuille

| Cas / portefeuille | Position utilisée | Objectif et A | Ce qui est modifié |
|---|---|---|---|
| **Cohérent, prudent** | `S_slot = clamp(S − 0.1)` | `mean_variance`, `A = risk_aversion(S_slot)` | **A seulement.** Même univers, mêmes contraintes, même plafond de volatilité, même plancher d'obligations (calculé sur S non décalé) |
| Cohérent, équilibre | `S_slot = S` | `mean_variance`, `A(S)` | idem |
| Cohérent, conviction | `S_slot = clamp(S + 0.1)` | `mean_variance`, `A(S+0.1)` | idem |
| **Incohérent, « Ton profil »** (prudent) | `S` | `mean_variance`, `A(S)` | Ne garde que les exclusions du client et les limites du profil : plancher d'obligations `BOND_FLOOR[label]`, interdiction de crypto si label ∈ `NO_CRYPTO`, `MAX_STOCK_WEIGHT`, plafond de volatilité. Ignore les pourcentages du questionnaire (`follows = False`, `monport.py:772`) |
| Incohérent, « Tes contraintes » (équilibre) | `S` | `mean_variance`, `A(S)` | Toutes les préférences + limites du profil (plafond de volatilité, `MAX_STOCK_WEIGHT`). **Pas** de plancher d'obligations (`bond_floors` ne renvoie que le slot prudent, `:657-663`) |
| Incohérent, « Tes préférences » (conviction) | `None` | `max_sharpe`, A balayé sur `A_LADDER` | Préférences et exclusions, `MAX_POSITION_WEIGHT 0.40`, **sans** plafond de volatilité ni `MAX_STOCK_WEIGHT` (`monport.py:781`) |

Dans tous les cas : **μ et Σ sont identiques** pour les trois portefeuilles (`allocator.py:487-488`, `Market.universe_covariance`). Ni S ni A ne les modifient. Le cash est désactivé (`catalog.py:605-606`).

### 1.G.5 Plafond de volatilité : levier caché sur A

- `slot_volatility(check, slot)` = `round(_interpolate(S, VOL_ANCHORS), 3)` (même plafond pour les trois variantes d'un profil cohérent).
- `_under_cap` (`allocator.py:133-164`) monte A le long de `A_LADDER` (au-dessus du A courant), puis jusqu'à `A_MAX`, jusqu'à ce que la volatilité passe sous le plafond. Il affine ensuite par dichotomie (6 pas).
- Si même `A = 25` ne suffit pas, le résultat est rejeté par `evaluate` (statut `infeasible`).
- **Conséquence : le A effectif peut être supérieur au A du profil.** Les diagnostics exposent `A_requested`, `A_initial_optimization`, `A_effective` (`allocator.py:~532`).

### 1.G.6 Chaîne d'exécution complète

```
Profil (questionnaire)                       frontend → POST /api/invocations {mode:'monport', profile, constraints,...}
  │                                          (le front n'envoie PAS de score ni de A)
  ▼
S de base   = risk_position(profile)         ia/monport.py:340-359
  │   + 0.05 · adjust_steps (−2…+2, LLM)     ia/workflow/pepite.py:243 ; session.py:106-111
  ▼
assess(): S, A(S), label, vol. max, poids max par action        ia/monport.py:528-536
  ▼
Cohérence (Pépite, repli coherence_facts)    ia/workflow/pepite.py:250-266 ; ia/monport.py:424-443
  ▼
Pour chaque slot : S_slot, objectif, A_slot  slot_position (:545) ; objective_for (:642)
  ▼
Contraintes : build_profiles (:750) → follow_profile (:571) → plafond vol. (slot_volatility :552)
              → validate_profile (:666, LINE_CAP) → ensure_feasible (:711)
  ▼
Mandate(risk_aversion=A_slot, vol_cap_factor=None)   ia/workflow/workers.py:181-214 (l.191)
  ▼
optimize_with_relaxation → optimize_universe         ia/allocator.py:597 → :443
   catalog.settings_for → get_agent_settings → apply_portfolio_request (A écrit dans risk_aversion.default)
   A0 (:490) → _continuous → select_holdings (:339) → réoptimisation (:507-514)
   → max_sharpe : _best_sharpe (:115)  |  plafond vol. : _under_cap (:133)
  ▼
Objectif : max  U = μᵀw − (A/2)·wᵀΣw   (SLSQP)          ia/optimizer.py:397-402
  ▼
Poids : _weights (:167) → portfolio_metrics (market.py:394) → evaluate + audit
  ▼
Juge (workers.py:279-330) → pick_winner / blend 0.8 → to_portfolio (monport.py:930) → SSE 'portfolios' → front
```

### 1.G.7 Ce que le profil modifie ou non

| Élément | Modifié par le profil / S / A ? |
|---|---|
| A | **Oui** (S → A, décalage par slot, relèvement par le plafond de volatilité) |
| Plafond de volatilité | **Oui** (`VOL_ANCHORS(S)`) |
| Plancher d'obligations, interdiction crypto, plafond par action | **Oui** (par label, via `follow_profile`) |
| Cash | **Non** (désactivé en production) |
| Sélection d'actifs | **Oui indirectement** (exclusions du client, contraintes, `select_holdings` au A du slot) |
| μ (rendements espérés) | **Non** |
| Σ (covariance) | **Non** |
| Univers | **Non** (même univers filtré par historique et exclusions du client) |

### 1.G.8 Code actif et code legacy dans cette chaîne

- **Actif** : `monport.py` (S, A, ancres, `build_profiles`, `follow_profile`, `blend`), `workflow/*`, `allocator.optimize_universe` et ses aides, `catalog.settings_for`.
- **Legacy** : `MANDATES` (`mandates.py:26-61`), `BOND_SHIFT`, `allocator.optimize` (hors `_raise_volatility_cap`), `BASE_PROFILE` (A = 5.0, `config.py:573-576`).
- **Moteur hors ligne du front** (`frontend/src/lib/engine.ts`) : reproduit S, A, limites et `SLOT_SHIFT`. Voir la partie 2.

---

# Partie 2 — Audit des calculs du front-end

Chemins relatifs à `frontend/src/`. Backend : `backend/src/invest_agents/` (**`ia/`**).

## 2.0 Verdict

**Oui, il reste des calculs financiers et des règles métier dans le front-end.** Ils sont de deux natures :

1. **Un moteur d'exemple complet** (`lib/engine.ts` et `data/catalog.ts`) qui construit des portefeuilles, des métriques et des preuves sans backend. Il est actif lorsque le backend est injoignable ou qu'aucun portefeuille n'est reçu.
2. **Une réplique des règles de profil** (score de risque S, A, limites, cohérence), utilisée **en usage normal** pendant le questionnaire, avant et pendant l'appel au backend.

**Avec un backend qui répond**, les portefeuilles, métriques, backtest, projection, montants, répartitions et facteurs viennent du backend sans transformation économique (`setPortfolios`, `store.ts:164-170`). Le front ne ré-optimise pas ces résultats, **sauf dans un cas** : `withAdjustments` (voir 2.3, constat F1).

## 2.1 Flux de données vérifié

```
Saisie (Profile.tsx, Preferences.tsx, inputs.tsx)
   │  état zustand `useApp`, persisté en sessionStorage (clé `bas-de-laine`)      store.ts
   │  calculs locaux : riskScore, riskLabel, riskBreakdown, profileLimits,
   │                   coherenceWarnings (affichage + avertissements en direct)    lib/engine.ts
   ▼
POST  PIPELINE_URL = VITE_API_URL || '/api/invocations'  (SSE, en-tête X-Session-Id)   api.ts:12, :73
   │  monport_check    {mode, profile, constraints}              (le `score` n'est PAS envoyé : api.ts:129)
   │  monport          {mode, profile, constraints, contribution, check, adjustment, session}   api.ts:162-168
   │  monport_chat     {mode, session, message}                  api.ts:174-179
   │  monport_rebuild  {mode, session}                           api.ts:185-192
   ▼
Backend : flow.py → Pépite → monport.py → allocator.py → optimizer.py → to_portfolio
   ▼
SSE événements : check, agent_status, pepite, universe, rerun, warning, portfolios, error, done   api.ts:37
   ▼
store.setPortfolios : `{...PORTFOLIO_META[id], ...p, warnings: p.warnings.map(riskNote)}`   store.ts:164-170
   │  les champs du backend écrasent les métadonnées ; `riskNote` découpe seulement « Titre. Détail »
   ▼
Affichage : Dashboard, Views, parts, charts, Factors, Evidence
```

Le front n'envoie **aucun** score, aucune aversion et aucun poids au backend. Le backend recalcule S, A et les limites seul.

## 2.2 Provenance des métriques affichées (mode backend)

| Métrique affichée | Où | Source backend | Transformation front |
|---|---|---|---|
| `expectedReturn` | `pages/dashboard/Views.tsx:127`, `Dashboard.tsx` | `m.expected_return` (optimiseur) via `to_portfolio` (`monport.py:~984`) | Aucune (format) |
| `volatility` | `Views.tsx:134` | `m.volatility` (optimiseur) | Aucune |
| `sharpe` | `Views.tsx:130` | `m.sharpe` = `(μ−rf)/σ` (`market.py:416`) | `toFixed(2)` et virgule |
| `worstYear` | `Views.tsx:57`, `:147` | `μ − 2.33σ` (`monport.py:989`) | Aucune |
| `var95` / `es95` annuels | champs de `Metrics` (`types.ts`) | `monport.py:993-994` | Non affichés dans les vues lues |
| VaR / ES 1 jour | `Views.tsx:149`, `:237-238` | `backtest.stats.var95/es95` (perte positive : `ia/backtest.py:~108`) | `signedPct(−var95)` : inversion de signe pour afficher une perte négative. **Cohérent** avec le backend (vérifié) |
| `maxDrawdown` | `Views.tsx:139` | `s?.maxDrawdown ?? m.maxDrawdown` : backtest en priorité, sinon optimiseur | Choix de source côté front (voir F8) |
| Projection | `ProjectionChart`, `Views.tsx:155-200` | `p.projection` (`projection.py`) | `wide: [p05, p95]`, `likely: [p25, p75]` (mise en forme) |
| Backtest | `PerformanceTab`, `Views.tsx:~270-300` | `p.backtest.runs[freq]` | Aucune |
| Montants | `Views.tsx` | `p.amounts`, `holdings[].amount` | Aucune |

## 2.3 Inventaire des calculs du front

Classification : **[F]** calcul financier · **[M]** logique métier · **[U]** transformation UI · **[Fmt]** formatage.

### 2.3.1 `lib/engine.ts` (moteur d'exemple et réplique des règles de profil)

| # | Calcul | Fonction | Lignes | Formule / logique | Entrée | Sortie | Équivalent backend | Classe | Recommandation |
|---|---|---|---|---|---|---|---|---|---|
| E1 | Décomposition du risque | `riskBreakdown` | `engine.ts:49-61` | `C = 0.6·h + 0.4·a`, `T = 0.5·r + 0.3·o + 0.2·c`, `s = clamp(min((C+T)/2, C+0.125))` | Saisie (profil) | `{capacity, tolerance, capped, s, …}` | `capacity`, `tolerance`, `risk_position` (`monport.py:340-359`) | [F]/[M] | **Dédupliquer** : le backend ajoute les crans de Pépite (`ADJUSTMENT_STEP·adj`), pas le front. Exposer S dès `monport_check` (le champ `risk_position` existe déjà dans `types.ts`) |
| E2 | Position S | `riskPosition` | `:64-66` | `riskBreakdown(p).s` | Saisie | S | `risk_position` | [F] | Idem |
| E3 | Aversion A | `riskAversion` | `:72-80` | Interpolation géométrique sur `AVERSION_ANCHORS` (`:69`), valeurs identiques au backend | S | A (non arrondi) | `risk_aversion` (`monport.py:370`, arrondi à 2 décimales) | [F] | Dédupliquer. `RiskNotebook.tsx:33` préfère déjà `check.risk_aversion ?? riskAversion(s)` |
| E4 | Interpolation linéaire par palier | `lerp` | `:82-86` | `x = clamp(s)/0.2`, `i = min(4, floor(x))` | S | valeur | `_interpolate(log=False)` (`monport.py:362`) | [F] | Dédupliquer |
| E5 | Limites du profil | `profileLimits` | `:92-101` | `bondFloor [0.8,0.6,0.4,0.2,0][band]`, `noCrypto band<=1`, `maxVolatility lerp(…[.06,.08,.11,.14,.18,.25])`, `maxStock min(0.4, lerp(…[.07,.09,.11,.13,.17,.22]))`, `lineCap 0.4` | S | Garde-fous affichés | `BOND_FLOOR`, `NO_CRYPTO`, `VOL_ANCHORS`, `STOCK_ANCHORS`, `LINE_CAP` (`monport.py:132-153`) ; `choices_breakdown` (`:457-483`) existe, non branché ici | [F]/[M] | **Déplacer** : lire les limites du backend |
| E6 | Position par portefeuille | `slotPosition` | `:104-107` | Incohérent : `conviction → null`. Cohérent : `clamp(s + SLOT_SHIFT[id])` avec −0.1 / 0 / +0.1 | S, cohérence | S_slot | `slot_position` (`monport.py:545`) | [F]/[M] | Dédupliquer. Équivalence **vérifiée** |
| E7 | Score de risque | `riskScore` | `:110-112` | `round(5 + 90·riskPosition)` | Saisie | 5 à 95 | `front_score(S)` = `floor(5+90S+0.5)` (`monport.py:384`) | [F] | **Écart** : le front ignore les crans de Pépite ; le backend les inclut (`to_portfolio` : `riskScore: front_score(position)`) |
| E8 | Étiquette de risque | `riskLabel` | `:114-116` | `RISK_LABELS[min(4, floor(clamp((score−5)/90)/0.2))]` | Score | Libellé | `risk_label` (`monport.py:375`), libellés internes différents | [M]/[U] | La reconversion `(score−5)/90` repart d'un score arrondi : imprécis aux frontières (non vérifié) |
| E9 | Répartition de poids | `fill` | `:127-141` | « exclure » → 0 ; % saisi → `s·total` ; neutres → part restante au prorata de `base` | Contraintes | poids | Contraintes de l'optimiseur | [F] | **Fallback seulement** |
| E10 | Poids par classe (mock) | `classWeights` | `:143-176` | `s = clamp(score + (−20 prudent \| +10 conviction \| 0))` ; `eq = 0.15 + 0.7·s/100` ; immobilier `0.04`, or `0.03`, crypto `0`, liquidités `max(0.03, 0.12 − 0.001·s)`, obligations = reste | Score, contraintes | poids par classe | Optimiseur (`allocator`), `follow_profile` | [F] | **Fallback** : les décalages −20/+10 points ne correspondent pas à ±0.1 sur S (≈ ±9 points). Marquer « démo » ou isoler |
| E11 | Lignes (mock) | `lineWeights` | `:178-247` | `scale {prudent 0.5, equilibre 1, conviction 1.8}` ; tilt de facteurs `exp(0.7·scale·Σ niveau·score)` ; poche actions `eqLeft·(titres ? 1 : 0.35)` ; régions de base `{canada .3, usa .4, europe .15, asie .08, emergents .07}` ; splits `OBL-GV .6/OBL-SO .4`, `BTC .7/ETH .3` ; plafond 40 % redistribué en une passe | Contraintes | liste de lignes | Optimiseur | [F] | **Fallback**. La redistribution du plafond n'est pas itérative : une ligne pourrait théoriquement rester > 40 % (non vérifié par test) |
| E12 | Allocation | `allocationOf` | `:249-253` | Somme des poids par classe | Lignes | allocation | `allocation` dans `to_portfolio` | [F] | Fallback |
| E13 | **Métriques (mock)** | `metricsOf` | `:255-276` | `μ = Σ a_k·mu_k` ; `σ² = ΣΣ a_i a_j σ_i σ_j ρ`, **ρ = 0.3** si i≠j ; `worstYear = μ − 2.33σ` ; **`sharpe = (μ − 0.025)/σ`** ; **`maxDrawdown = −min(0.9, 2.2σ)`** ; `var95 = −(μ − 1.645σ)` ; `es95 = −(μ − 2.063σ)` | Hypothèses de classe | `Metrics` | `portfolio_metrics` (`market.py:394`) et `to_portfolio` | [F] | **Isoler ou masquer en production.** `rf = 0.025` contre `0.035` au backend ; `maxDrawdown` est un proxy sans historique ; ρ = 0.3 est un coefficient inventé |
| E14 | Preuves (mock) | `evidenceOf` | `:281-300` | `hhi = Σw²`, `diversification = 1/hhi`, `top` = plus grosse ligne, perte acceptée = `−LOSS_BY_REACTION[lossReaction]` | Portefeuille | `Evidence` | `portfolio_evidence` (`ia/evidence.py:88`) | [F] | Fallback. `reduce` sans valeur initiale : échec possible sur une liste vide (non vérifié) |
| E15 | `LOSS_BY_REACTION` | constante | `:303` | `[0.1, 0.15, 0.25, 0.35]` | | | `monport.py:128` (`{10,15,25,35}`) | [M] | Dédupliquer |
| E16 | **Avertissements de cohérence** | `coherenceWarnings` | `:306-323` | `score<40 && crypto%>0` ; `score<40 && actions≥0.7` ; `score>65 && (actions exclues \|\| actions≤0.3)` ; `score<77 && vehicles==='titres'` ; une seule classe gardée | Score front, contraintes | `RiskNote[]` | `coherence_facts` (`monport.py:424-443`) et décision de Pépite | [M] | **Actif en production** (`Preferences.tsx:61`). Mêmes seuils que le backend mais calculés sur le score **sans crans**. Déplacer ou parité testée |
| E17 | Assemblage mock | `buildPortfolio`, `buildAll` | `:325-345` | `warnings = id==='prudent' ? [] : coherenceWarnings(…)` ; message « Le juge confirme que ce portefeuille respecte tes limites. » **écrit en dur** (`:~339`) | Score, contraintes | `Portfolio` | Chaîne complète backend | [F]/[M] | **Fallback**. L'affirmation du juge est inventée en mode démo |

### 2.3.2 `store.ts`

| # | Calcul | Fonction | Lignes | Logique | Équivalent backend | Classe | Recommandation |
|---|---|---|---|---|---|---|---|
| S1 | Ajustement simulé | `withAdjustments` | `store.ts:93-105` | `shift = Σ riskShift` ; `rebuilt = buildAll(min(95, max(5, score + shift)), patched)[id]` ; retourne `{...rebuilt, name, tagline}` | `adjust_risk_position` (`pepite.py:231`), échelle ±0.05 sur S par cran | [F]/[M] | **Revoir en priorité** (F1) |
| S2 | Construction de repli | `build()` | `store.ts:158-163` | `buildAll(riskScore(profile), constraints)` ; si `check.coherent` → seul `equilibre` | Workflow backend | [F]/[M] | Fallback |
| S3 | Niveau de tableau de bord | `defaultDashboardLevel` | `store.ts:82-84` | `comfort ≤ 2 → débutant`, `3 → intermédiaire`, `≥ 4 → avancé` | Aucun | [M]/[U] | Garder (UI) |
| S4 | Fusion de contraintes | `merge` | `store.ts:86-90` | Fusion superficielle, `vehicles` ignoré | Aucun | [U] | Garder |
| S5 | Véhicules | `setVehicles` | `store.ts:134-150` | Hors FNB : seules `shownClasses` sont gardées ; pourcentages retirés quand `vehicles === 'fnb'` | `shown_classes` (`monport.py:~234`) | [M] | Garder, vérifier la parité |
| S6 | Valeurs par défaut du profil | `DEFAULT_PROFILE` | `store.ts:7-14` | âge 35, montant 10 000, objectif `fructifier`, horizon 12, `lossReaction 2`, `comfort 3` | `capacity`/`tolerance` défauts : horizon 10, âge 35 | [M] | **Écart** : horizon par défaut 12 (front) contre 10 (backend), pertinent si un champ manque |

### 2.3.3 `api.ts`

| # | Calcul | Fonction | Lignes | Logique | Classe | Recommandation |
|---|---|---|---|---|---|---|
| A1 | Contrôle de repli | `exampleCheck` | `:108-115` | Cohérent si `coherenceWarnings(score, c).length === 0` | [M] | Fallback |
| A2 | Script d'événements fictif | `runScript` | `:194-232` | `after = UNIVERSE.length*7 − excluded*9 − classesOut*6` ; `before = UNIVERSE.length*7` ; message « Toutes tes limites sont respectées. » | [U] | **Chiffres inventés** : afficher « exemple » ou retirer |
| A3 | Règles de chat | `RULES`, `proposeAdjustment` | `:234-296` | Regex : tech → `themes.tech 30` ; pétrole/fossile → exclusion ; crypto/bitcoin → `classes.crypto 10` (avertit si `score < 50`) ; prudent/moins de risque → exclut la crypto et `riskShift −15` ; `changes` = diff avant/après filtré à `\|Δ\| ≥ 0.001` | [M]/[F] | Fallback. Aucun équivalent backend codé (LLM) |

### 2.3.4 `data/catalog.ts` (hypothèses en dur)

| # | Élément | Lignes | Contenu | Classe | Recommandation |
|---|---|---|---|---|---|
| C1 | `CLASS_ASSUMPTIONS` | `:263` | μ/σ en dur : actions 7 % / 16 %, obligations 3,5 % / 6 %, immobilier 5,5 % / 18 %, or 4 % / 15 %, crypto 15 % / 70 %, liquidités 2,5 % / 1 % | [F] (mock) | Isoler en démo |
| C2 | `UNIVERSE` | `:230-260` | 26 lignes fictives (« exemple »), frais en %, scores de facteurs en dur | [F]/[M] (mock) | Isoler en démo |
| C3 | `FACTOR_TARGETS` | `:160` | `{2: .5, 1: .2, −1: −.2, −2: −.5}` | [M] | **Dupliqué** (`monport.py:113`) : test de parité |
| C4 | `shareTotal`, `sharesValid` | `:163-172` | `total = round(Σ·10)/10` ; valide si `total ≤ 100 && (free>0 \|\| entered===0 \|\| total===100)` | [M] | Validation UI. Le backend revalide (`validate_profile`, `monport.py:666`) |
| C5 | `shownClasses` | `:46-48` | `titres → ['actions','crypto']`, sinon 5 classes | [M] | Parité avec `shown_classes` |
| C6 | `PERIODS_PER_YEAR` | `:300` | `{deux-semaines 26, mensuelle 12, annuelle 1, aucune 12}` | [F] | **Probablement inutilisé** : la vue lit `proj.periodsPerYear` du backend (`Views.tsx:~198`). Non vérifié par recherche exhaustive |
| C7 | `THEME_PRESETS` | `:185-216` | Modèles de thématiques en dur (ex. tech 35 %, IA 25 %) | [M] | Garder (UI) |

### 2.3.5 Pages et composants

| # | Calcul | Fichier : lignes | Logique | Classe | Recommandation |
|---|---|---|---|---|---|
| P1 | Utilité marginale du risque | `pages/RiskNotebook.tsx:269` | `extra = (A/2)·(0.15² − 0.10²)·100` (rendement demandé pour passer de 10 % à 15 % de volatilité) | [F] (pédagogique) | Garder si libellé « illustration » ; dépend de A (backend si disponible) |
| P2 | Échelle log de A | `RiskNotebook.tsx:270` | `pos = log(25/v)/log(25)·100` | [U] | Garder |
| P3 | Tolérance de bande | `RiskNotebook.tsx:317` | `TOLERANCE = 2` points, « comme `SHARE_TOLERANCE` de `monport.py` » (définition backend non relue) | [M] | Parité à tester |
| P4 | Plancher d'obligations affiché | `RiskNotebook.tsx:342-343` | `room = 1 − Σ_classes fixées max(0, v − TOLERANCE)/100` ; `bondFloor = max(0, min(lim.bondFloor, room))` | [F]/[M] | **Approximation locale** de `follow_profile` (`monport.py:571`) : le backend fait foi |
| P5 | Poids de la capacité / tolérance | `RiskNotebook.tsx:125-141` | `0.6/0.4` et `0.5/0.3/0.2` recopiés à la main | [F] | **Triple duplication** (`engine.ts:55-56`, `monport.py:344,352`) |
| P6 | Score recalculé en ligne | `RiskNotebook.tsx:253`, `:291` | `riskLabel(Math.round(5 + 90·s))` au lieu de `riskScore` | [F]/[U] | Dédupliquer |
| P7 | Seuil d'explication | `RiskNotebook.tsx:108` | `b.capacity > b.tolerance + 0.15` | [U] | Garder (texte) |
| P8 | Bandes de facteurs | `pages/dashboard/Factors.tsx` | `RANGE = 1.5`, `NEUTRAL = 0.1` ; intensité `<0.1 Neutre`, `<0.3 Légère`, `<0.6 Nette`, sinon `Forte` ; jauge `(clamp(v, −1.5, 1.5) + 1.5)/3·100` ; `strong = \|v\| > 0.18` | [U] | Garder. Le test « cible atteinte » (`met`) n'a pas été lu (non vérifié) |
| P9 | Parts de risque | `Views.tsx:~390` | Texte explicatif de la contribution au risque. Le calcul est côté backend (`risk_contribution`) | [U] | Garder |
| P10 | Barres, largeurs | `charts.tsx:75`, `parts.tsx:25`, `Evidence.tsx:25-34` | `poids·100 %`, `scale = max(v, l)·1.15`, `over` | [U] | Garder |
| P11 | Pré-remplissage de pourcentage | `inputs.tsx:208` | `max(0, round((100 − total)/max(1, free)))` | [U]/[M] | Garder |
| P12 | Contenu LLM comme barre | `RichText.tsx:152-158` | `clamp(parseFloat(pct), 0, 100)` | [U] | Chiffre venant du texte écrit par l'agent, non recalculé (non vérifié côté backend) |
| P13 | Libellé « Pire recul (backtest) » | `Views.tsx:139` | `s?.maxDrawdown ?? m.maxDrawdown` | [U] | **Libellé trompeur** quand la valeur vient de `m.maxDrawdown` (proxy du mode démo) |

### 2.3.6 `lib/format.ts` (formatage, pas de calcul financier)

`pct` (×100), `signedPct`, `money`, `signedMoney`, `percentPoints`, `points` (`round(v·1000)/10`), `contribution`, `evidenceValue`, `share`. Aucune modification du sens économique. Seule précaution : `pct(v)` multiplie par 100, ce qui suppose que le backend renvoie des **fractions**, comme le décrit `types.ts`.

### 2.3.7 Fichiers sans calcul financier repéré

`App.tsx`, `main.tsx`, `Layout`, `Splash`, `Disclaimer`, `FactorModel`, `Home`, `Profile` (hors lecture d'un paramètre d'URL via `Number(raw)`). Ils n'ont pas tous été relus ligne à ligne (voir section 4).

## 2.4 Réponses aux questions d'architecture

1. **Calculé par le backend** : positions et poids, métriques (`μ`, `σ`, Sharpe, drawdown), avertissements, facteurs (`factor_view`), backtest, projection, montants, répartitions et contribution au risque, preuves. Le docstring de `to_portfolio` précise que le front ne fait qu'afficher.
2. **Calculé indépendamment par le front** : S, A, étiquette de risque, limites du profil, avertissements de cohérence (en usage normal), et, en mode démo ou hors ligne, tout le portefeuille et ses métriques.
3. **Simple affichage ou formatage** : toutes les vues du tableau de bord, y compris `signedPct(−VaR)` qui réaffiche en perte négative une valeur positive du backend.
4. **Doublons** : oui. Pour les constantes et formules de profil, voir le tableau 3.B. Aucun test de parité n'a été trouvé (je n'ai pas exploré les tests du front).
5. **Le front modifie-t-il les résultats de l'optimiseur ?** Oui, dans un seul chemin : `withAdjustments` (F1).
6. **Mock et fallback actifs** : oui. Déclencheur : échec du `fetch`, statut non OK ou type de contenu non SSE (`api.ts:79-87`), puis `signalDemo(true)` (bandeau de démonstration).
7. **Les métriques correspondent-elles exactement au backend ?** En mode backend, oui (aucun recalcul). En mode démo, non : les chiffres viennent de `metricsOf`.

## 2.5 Constats du front

| Réf. | Constat | Preuve | Gravité |
|---|---|---|---|
| **F1** | `withAdjustments` écrase un portefeuille **du backend** par un portefeuille du moteur d'exemple, et perd `backtest`, `projection`, `breakdown`, `amounts`, `factors` | `store.ts:93-105` ; `{...rebuilt, name, tagline}` ne copie pas ces champs. Déclenché si `applyAdjustment` ou `previewAdjustment` est appelé (`store.ts:171-182`). Ces appels viennent de `decide()` (`AdjustPanel.tsx:~125`), à partir d'une proposition `msg.proposal`, qui n'existe qu'en mode simulé. Risque si la session expire (`/expiré/`) ou si le backend tombe en cours de chat | Élevée |
| **F2** | `riskScore` du front ne contient pas les crans de Pépite | `engine.ts:110` contre `monport.py:355-359` et `to_portfolio` | Moyenne |
| **F3** | Avertissements de cohérence calculés en continu côté front sur le score sans crans | `Preferences.tsx:61` | Moyenne |
| **F4** | Métriques de démo à `rf = 0.025`, `ρ = 0.3`, `maxDrawdown = −min(0.9, 2.2σ)`, frais `0.2` par défaut | `engine.ts:261`, `:271`, `:272`, `:265` | Moyenne (si la démo est montrée au jury) |
| **F5** | Constantes de profil dupliquées sans test de parité | 12 constantes, voir 3.B | Élevée (dérive silencieuse) |
| **F6** | `riskAversion` du front non arrondi, backend arrondi à 2 décimales | `engine.ts:72-80` ; `monport.py:372` | Faible |
| **F7** | `DEFAULT_PROFILE.horizon = 12` contre défaut backend `10` ; décalage de score par slot du mock `−20/+10` points contre `±0.1` sur S | `store.ts:7-14` ; `engine.ts:144` ; `monport.py:157` | Faible |
| **F8** | `Views.tsx:139` : libellé « Pire recul (backtest) » avec repli sur `m.maxDrawdown` | `Views.tsx:139` | Faible |
| **F9** | `PERIODS_PER_YEAR` probablement mort | `catalog.ts:300` | Faible |

---

# Partie 3 — Synthèse consolidée

## 3.A Inventaire maître des paramètres

Les lignes sont vérifiées par `grep -n`, sauf mention `~`. « Config » = clé de `config.py` modifiable en éditant ce fichier. « Constante » = littéral dans le code. « Env » = variable d'environnement. « Estimé » = calculé sur les données, non choisi.

### Rendements (A)

| Paramètre | Valeur | Fichier : ligne | Configurabilité |
|---|---|---|---|
| `RF_ANNUAL` | 0.035 | `config.py:94` | Config (une seule définition) |
| `ESTIMATION.mode` / `single_method` | `by_asset_class` / `historical` | `config.py:99-100` | Config |
| Méthode Equity | `capm_shrinkage` | `config.py:105` | Config |
| Méthode Fixed Income et autres classes | `historical` | `config.py:106-110` | Config |
| Crypto / BITW | `ewma` | `config.py:114-115` | Config |
| `historical.min_observations` | 120 | `config.py:120` | Config |
| `ewma.half_life_observations` | 90 | `config.py:124` | Config |
| `ewma.min_observations` | 120 | `config.py:125` | Config |
| `capm_shrinkage.market_proxy` | SPY | `config.py:131` | Config |
| `capm_shrinkage.erp_annual` | 0.05 | `config.py:133` | Config |
| `capm_shrinkage.alpha` | 0.50 | `config.py:134` | Config |
| `capm_shrinkage.min_paired_observations` | 120 | `config.py:130` | Config |
| Tous les `lookback_observations` de μ | `None` | `config.py:119`, `:123`, `:129`, `:135`, `:138`, `:140` | Config |
| β | estimé | `market.py:62-72` | Estimé |
| `capm_benchmark_shrinkage.*` | inactif | `config.py:137-148` | Config (aucune classe ne l'utilise) |
| `DATA.periods_per_year` | 252 | `config.py:40` | Config |

### Covariance (B)

| Paramètre | Valeur | Fichier : ligne | Configurabilité |
|---|---|---|---|
| `COVARIANCE.method` | `ledoit_wolf` | `config.py:227` | Config |
| Intensité LW | estimée | `market.py` (`_ledoit_wolf`, `ledoit_wolf_universe`) | Estimé |
| `lookback_observations` | `None` | `config.py:230` | Config |
| `min_joint_observations` | 120 | `config.py:235` | Config |
| `assume_centered` | `False` | `config.py:244` | Config |
| `COVARIANCE_HISTORY.start_date` | `2021-01-01` | `config.py:265` | Config |
| `require_full_horizon` | `True` | `config.py:266` | Config |
| `max_start_delay_business_days` | 5 (borné 0-10) | `config.py:268` | Config |
| `periods_per_year_effective` | estimé | `market.py:250-257`, `:312` | Estimé |
| `sample.min_pairwise_observations`, `repair_psd`, `eigenvalue_floor` | 60, `True`, `1e-10` | `config.py:237-239` | Config (inactifs) |
| Tolérance PSD optimiseur | `−1e-8` | `optimizer.py:478` | Constante |

### Aversion au risque et profils (C)

| Paramètre | Valeur | Fichier : ligne | Configurabilité |
|---|---|---|---|
| `RISK_AVERSION.min/max/default` | 1.0 / 25.0 / 5.0 | `config.py:310-312` | Config (doublon `allocator.py:45`, `schemas.py:318`) |
| `AVERSION_ANCHORS` | voir 1.C | `monport.py:151` ; `engine.ts:69` | Constante ×2 |
| `VOL_ANCHORS`, `STOCK_ANCHORS` | voir 1.C | `monport.py:152-153` ; `engine.ts:92-101` | Constante ×2 |
| `BOND_FLOOR`, `NO_CRYPTO` | voir 1.C | `monport.py:137`, `:141` ; `engine.ts:92-101` | Constante ×2 |
| `SLOT_SHIFT` | −0.1 / 0 / +0.1 | `monport.py:157` ; `engine.ts:104-107` | Constante ×2 |
| Poids de C et de T | 0.6/0.4 et 0.5/0.3/0.2 | `monport.py:344`, `:352` ; `engine.ts:55-56` ; `RiskNotebook.tsx:125-141` | Constante ×3 |
| `OBJECTIVE_TOLERANCE` | 0 / 0.5 / 1 | `monport.py:147` ; `engine.ts:43` | Constante ×2 |
| `CAPACITY_MARGIN` | 0.125 | `monport.py:148` ; `engine.ts:46` | Constante ×2 |
| `ADJUSTMENT_STEP` | 0.05 | `monport.py:149` | Constante |
| Plafond de crans | ±2 | `workflow/pepite.py:243` | Constante |
| `LINE_CAP` | 0.40 | `monport.py:132` ; `evidence.py:27` ; `engine.ts:9` | Constante ×3 |
| `LOSS_BY_REACTION` | 10/15/25/35 | `monport.py:128` ; `engine.ts:303` | Constante ×2 |
| `BLEND` | 0.8 | `monport.py:56` | Constante |
| `JUDGE_RELAUNCH_PENALTY` | 3 | `config.py:288` | Config |

### Optimisation (E)

| Paramètre | Valeur | Fichier : ligne | Configurabilité |
|---|---|---|---|
| Objectif | `U = μᵀw − (A/2)wᵀΣw` | `optimizer.py:397-402` | Constante |
| `CONSTRAINTS.max_weight_per_asset` | `None` (production) | `config.py:340` | Config |
| `BASE_CONSTRAINTS.max_weight_per_asset` | 0.10 (inactif) | `config.py:481` | Config |
| `min_held_weight` | 0.01 | `config.py:334`, `:280`, `:471` ; `allocator.py:44` | Config ×3 + constante |
| `PORTFOLIO_HOLDINGS` | 25 / 70 / 0.01 / 0.0001 | `config.py:278-283` | Config |
| `MAX_ASSETS_PER_PORTFOLIO` | 40 | `runtime.py:49` | Env |
| `A_LADDER` | 10 valeurs de 1.0 à 25.0 | `allocator.py:47` | Constante |
| `CAP_REFINEMENTS` | 6 | `allocator.py:48` | Constante |
| Lots de sélection | 10 (minimum), 5 (diversification) | `allocator.py:~376`, `~409` | Constante |
| `CASH` | rendement 0.01, volatilité 0.0, **désactivé en production** | `config.py:394-395` ; `catalog.py:605-606` | Config / Constante |
| `OPTIMIZATION.solver_options` | `maxiter 2000`, `ftol 1e-9` | `config.py:407-408` | Config |
| `constraint_tolerance`, `sum_weights_tolerance` | `1e-7`, `1e-7` | `config.py:411-412` | Config |
| `minimum_holding_tolerance` | `1e-8` | `config.py:337` | Config |
| Tolérances `catalog` | `TOL 1e-3`, `WTOL 2e-4`, `HELD 5e-4`, `EXACT_TOL 1e-3`, `FTOL 0.01`, `FACTOR_SLEEVE_MIN 0.10`, `FACTOR_MARGIN 0.01` | `catalog.py:67-69`, `:154-158` | Constante |
| `FACTOR_LEVELS` | ±0.2 / ±0.5 | `monport.py:113` ; `catalog.ts:160` | Constante ×2 |

### Autres (F)

| Paramètre | Valeur | Fichier : ligne | Configurabilité |
|---|---|---|---|
| `LOOKBACK_YEARS`, `YEAR`, `BIWEEKLY`, `SAMPLE_EVERY`, `DAILY_STEP`, `DAILY_LIMIT` | 6, 252, 10, 5, 0.5, 5.0 | `backtest.py:26-31` | Constante |
| `PATHS`, `SEED`, `MAX_AMOUNT`, `PER_YEAR` | 1000, 7, 10 000 000, 26/12/1/12 | `projection.py:20-23` | Constante |
| `FEES` | `{"ETF": 0.002}` | `monport.py:131` | Constante |
| VaR/ES normaux | 2.33, 1.645, 2.063 | `monport.py:989-994` ; `evidence.py:28` ; `engine.ts:269-274` | Constante ×3 |
| `MAX_CITED` | 3 | `evidence.py:29` | Constante |
| Modèles et jetons LLM | voir 1.F | `runtime.py:32-48` | Env |

## 3.B Matrice de responsabilités front vs backend

| Calcul ou règle | Propriétaire actuel | Doublon dans l'autre couche | Cohérence | Manque ou écart |
|---|---|---|---|---|
| μ, Σ, estimation | Backend (`market.py`) | Non | n/a | Annualisation de Σ ≠ μ (voir 1.B) |
| Optimisation de portefeuille | Backend (`allocator.py`, `optimizer.py`) | **Oui, en démo** : `classWeights`, `lineWeights` | Heuristique différente | Fallback à isoler |
| Métriques (μ, σ, Sharpe, drawdown) | Backend (`portfolio_metrics`) | **Oui, en démo** : `metricsOf` (`rf 0.025`, `ρ 0.3`) | Diverge | Marquer « exemple » |
| VaR / ES / pire année | Backend (`to_portfolio`) | Oui : `metricsOf` | Mêmes constantes (2.33, 1.645, 2.063) | OK, mais triple définition (`evidence.py`, `monport.py`, `engine.ts`) |
| Backtest, projection, montants | Backend | Non | n/a | Vides en démo (`NeedsBackend`) |
| Score de risque S | Backend (avec crans) | **Oui** : `riskBreakdown` | Identique sans crans | Le front ignore les crans |
| Aversion A | Backend (`risk_aversion`) | **Oui** : `riskAversion` | Identique, arrondi différent | `RiskNotebook` préfère le backend |
| Limites du profil (vol., plafond action, plancher d'obligations, crypto) | Backend (`monport.py`) | **Oui** : `profileLimits` | Mêmes valeurs | `choices_breakdown` existe mais n'est pas branché |
| `SLOT_SHIFT` | Backend | **Oui** : `slotPosition` | Identique | |
| Cohérence profil/préférences | Backend (Pépite, `coherence_facts`) | **Oui** : `coherenceWarnings` | Mêmes seuils, score différent | Actif en usage normal |
| Ajustements de risque | Backend (crans LLM) | **Oui** : `riskShift`, `RULES` | Échelles différentes | `withAdjustments` écrase le résultat backend |
| Validation de parts et contraintes | Backend (`validate_profile`, `evaluate`) | Oui : `sharesValid`, `shareTotal` | Probable | Validation UI de confort |
| Taux sans risque | Backend (`RF_ANNUAL = 0.035`) | Oui : `0.025` dans `metricsOf` | **Diverge** | Démo seulement |
| Frais | Backend (`FEES 0.002`) | Oui : `fee ?? 0.2` | Équivalent (0.2 %) | |

## 3.C Constats prioritaires

Classés par importance architecturale, puis par impact sur les portefeuilles.

### Priorité 1 — Impact direct sur les résultats

1. **Annualisation de Σ ≠ annualisation de μ.** `periods_per_year_effective` (`n / (jours/365.25)`, `market.py:250-257`, `:312`) annualise Σ ; μ et `ann_vol` utilisent 252. La volatilité des portefeuilles et les `ann_vol` d'écran ne reposent donc pas sur la même base. À mesurer sur le Parquet avant le Datathon (commande de contrôle : exécuter `python -m invest_agents.market`, qui affiche `periods_per_year_effective`).
2. **A effectif ≠ A du profil.** Le plafond de volatilité relève A jusqu'à 25 (`allocator._under_cap`, `:133-164`). Le A affiché (`risk_aversion(S)`) peut donc différer du A réellement optimisé (`A_effective`). Les trois variantes d'un profil cohérent partagent le même plafond (seul A les distingue), si bien que ce relèvement peut faire converger leurs A effectifs.
3. **Pas de plafond par actif en production** (`max_weight_per_asset = None`, `config.py:340`, contre `0.10` dans BASE, inactif). Le seul plafond est `LINE_CAP = 0.40` et `MAX_STOCK_WEIGHT`. À calibrer explicitement ; la concentration en dépend.
4. **Influence du sentiment : un LLM, non reproductible.** Les crans (±2, soit ±0.10 de S) sont décidés par Pépite sans règle numérique (`pepite.py:231-247`). C'est le seul canal du « sentiment » : à documenter, à tester sur des exemples, ou à encadrer par une table de règles.
5. **Paramètres de rendement structurants à calibrer** : `erp_annual = 0.05`, `alpha = 0.50`, `RF_ANNUAL = 0.035` (hypothèses de démonstration, le code le dit) ; SPY pour toutes les actions, y compris les titres non américains ; méthode historique pure pour les obligations (la moyenne historique sur l'échantillon peut s'écarter de la période courante).
6. **`COVARIANCE_HISTORY.start_date = 2021-01-01`** : détermine quels titres sont admissibles. Un titre coté après cette date (plus 5 séances) n'entre jamais dans l'optimisation, quel que soit son historique.

### Priorité 2 — Architecture et duplication

7. **`withAdjustments` écrase un portefeuille backend** par le mock et perd backtest, projection, montants, breakdown, facteurs (F1, `store.ts:93-105`).
8. **Douze constantes dupliquées front/backend sans test de parité** (F5) : ancres A/vol/actions, plancher d'obligations, `SLOT_SHIFT`, pondérations de C et T, `OBJECTIVE_TOLERANCE`, `CAPACITY_MARGIN`, `LOSS_BY_REACTION`, `LINE_CAP`, `FACTOR_LEVELS`.
9. **Le front calcule S et les limites avant le backend** et ignore les crans (F2, F3). Exposer ces valeurs depuis `monport_check` et retirer les formules du front.
10. **Valeurs `min_held_weight = 0.01` et A ∈ [1, 25] définies à 4 endroits** (voir 1.E, 1.C).
11. **Seuil « position détenue » défini 5 fois** : `1e-7`, `1e-9`, `2e-4`, `5e-4`, `0.005`.

### Priorité 3 — Hygiène, démo, documentation

12. **Fallback et mock actifs** : métriques de démo à `rf 0.025`, `ρ 0.3`, `maxDrawdown = −min(0.9, 2.2σ)` ; message « Le juge confirme… » écrit en dur ; chiffres du script `runScript` inventés (F4, A2, E17). Isoler derrière un indicateur de démonstration.
13. **Code inerte et documentation périmée** : `BASE_*`, `CANDIDATES`, `MANDATES`, `BOND_SHIFT`, `PERIODS_PER_YEAR`, `RISK_AVERSION.bands`, docstring « 25 à 60 positions (cible 50) » (`portfolio_manager.py:4`) contre `25 à 70` (`config.py:278-279`).
14. **Trois définitions de la pire année à 2.33** (`monport.py:989`, `evidence.py:28`, `engine.ts:269`).
15. **Défauts divergents** : horizon 12 (front) contre 10 (backend) ; A par défaut 5.0 (`config`), `A_MAX/5` (`allocator.py:490`, actif) et `A_MAX/2` (`allocator.py:216`, legacy).

---

## 4. Éléments non vérifiés

- `deploy/*.sh`, `nginx.conf` et `pyproject.toml` n'ont pas été lus : le caractère « déployé » repose sur les imports depuis `backend/main.py` et sur `catalog.settings_for`.
- Les numéros de ligne précédés de `~` sont approximatifs. Les valeurs, elles, ont été relues dans le code.
- Non relus en détail : `constraints.py` (hors constantes), `evidence.py` (hors constantes), `guardrail.py`, `workflow/session.py`, `workflow/flow.py` (hors lignes citées), `agents/*`, `diagnostics.py` (seuils relevés par un sous-agent), `catalog.preference_constraints` et `choices_breakdown`.
- Non vérifié : usage de `RISK_AVERSION.bands`, usage des clés `ledoit_wolf.target`, `ledoit_wolf.shrinkage_intensity`, `ledoit_wolf.block_size`, `minimum_holding_max_iterations` et `ESTIMATION.forecast_horizon_years` par le code actif ; usage du poids `JUDGE_RELAUNCH_PENALTY` dans le juge ; définition backend de `SHARE_TOLERANCE`.
- Front : `Home`, `Profile`, `Splash`, `Layout`, `Disclaimer`, `FactorModel`, `App.tsx`, début de `RiskNotebook.tsx` et `Pipeline.tsx` (lignes 60 à 160) relus partiellement ; condition `met` de `Factors.tsx` non lue ; tests du front non explorés.
- Aucun code n'a été exécuté : les valeurs de A citées en 1.G.3 sont calculées à la main à partir des ancres, et l'écart d'annualisation de Σ n'est pas mesuré.

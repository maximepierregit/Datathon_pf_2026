# AlphaForge / MonPort — Audit des paramètres et des calculs front-end

> **Nature du document.** Analyse en lecture seule du dépôt `datathon-pf-2026`. Aucun code, paramètre ni formule n'a été modifié.
> **Version 3** (2026-11-16), recalée sur le code du commit `9729f50`. Elle conserve la version 2 (Volume I, parties 1 à 4) et ajoute le **Volume II** : référence financière, factorielle, macroéconomique et défense méthodologique (chapitres M0 à M11, à la fin du document).
> **Langue :** français.
> **Où trouver quoi.** Volume I : paramètres par catégorie, audit du front-end, inventaire maître. Volume II : théories, facteurs, macro, contraintes par profil, backtest, simulations, cartographie backend vers front-end, calibration, fiches pour les juges. Début du Volume II : [M0](#m0-synthèse-exécutive-et-mode-demploi).

### Ce qui a changé par rapport à la version 1

| Changement du code | Effet sur le document |
|---|---|
| **Deux pénalités souples sur l'utilité** (`REGULARIZATION` : `diversification_penalty` λ_D et `high_volatility_penalty` λ_V, plus un seuil de volatilité), qui s'appuient sur la diagonale de la matrice de covariance Σ | Nouvelle section [1.B.2](#1b2-pénalités-de-régularisation-liées-à-σ-deux-pénalités), mises à jour de 1.E, 1.G, 3.A et 3.C |
| Le mélange 80/20 (`blend`) applique désormais « 0 ou au moins 1 % », des plafonds par titre et une plage de positions (`enforce_minimum`, `position_range`, `stock_cap`) | 1.F et 1.G.4 |
| Relance avec limites assouplies : pénalité de note du juge (`JUDGE_RELAUNCH_PENALTY = 3`) appliquée par le code (`workers._penalty`), notes pénalisées dans `pick_winner` | 1.E et 1.G.4 |
| Numéros de ligne décalés dans `config.py` (après `CASH`), `optimizer.py`, `allocator.py`, `monport.py`, `workers.py` | Toutes les références ont été relevées à nouveau par `grep -n` |
| Demande : pour chaque concept applicable, indiquer où il s'affiche dans le front-end | Nouvelle section [2.6](#26-où-chaque-concept-saffiche-dans-le-front-end), ligne ajoutée au tableau 2.2 et ligne P9 corrigée |

## Table des matières

0. [Périmètre, méthode et conventions](#0-périmètre-méthode-et-conventions)
1. [Partie 1 — Cartographie des paramètres (backend)](#partie-1--cartographie-des-paramètres-backend)
   - [1.A Rendements espérés et CAPM](#1a-rendements-espérés-et-capm)
   - [1.B Matrice de covariance](#1b-matrice-de-covariance) et [1.B.2 Pénalités liées à Σ](#1b2-pénalités-de-régularisation-liées-à-σ-deux-pénalités)
   - [1.C Aversion au risque et profils](#1c-aversion-au-risque-et-profils-investisseur)
   - [1.D Agent, sentiment et ajustements](#1d-agent-sentiment-et-ajustements)
   - [1.E Optimisation de portefeuille](#1e-optimisation-de-portefeuille)
   - [1.F Autres paramètres](#1f-autres-paramètres)
   - [1.G Section spéciale : profils et aversion au risque](#1g-section-spéciale--profils-et-aversion-au-risque)
2. [Partie 2 — Audit des calculs du front-end](#partie-2--audit-des-calculs-du-front-end)
   - [2.6 Où chaque concept s'affiche dans le front-end](#26-où-chaque-concept-saffiche-dans-le-front-end)
3. [Partie 3 — Synthèse consolidée](#partie-3--synthèse-consolidée)
   - [3.A Inventaire maître](#3a-inventaire-maître-des-paramètres)
   - [3.B Matrice de responsabilités front vs backend](#3b-matrice-de-responsabilités-front-vs-backend)
   - [3.C Constats prioritaires](#3c-constats-prioritaires)
4. [Éléments non vérifiés](#4-éléments-non-vérifiés)

**Volume II — Référence méthodologique et défense devant le jury**

- [M0 Synthèse exécutive et mode d'emploi](#m0-synthèse-exécutive-et-mode-demploi)
- [M1 Architecture financière réellement exécutée](#m1-architecture-financière-réellement-exécutée)
- [M2 Théories financières utilisées](#m2-théories-financières-utilisées)
- [M3 Facteurs d'investissement](#m3-facteurs-dinvestissement-et-calibration)
- [M4 Indicateurs macroéconomiques](#m4-indicateurs-macroéconomiques)
- [M5 Contraintes et limites financières](#m5-inventaire-des-contraintes-et-limites-financières)
- [M6 Backtest](#m6-backtesting--méthodologie-et-limitations)
- [M7 Simulations de patrimoine](#m7-simulations-de-patrimoine-projection-sur-10-ans)
- [M8 Cartographie backend vers front-end](#m8-cartographie-backend--frontend)
- [M9 Limitations, calibration et sensibilité](#m9-limitations-calibration-et-analyses-de-sensibilité)
- [M10 Fiches de préparation aux questions des juges](#m10-préparation-aux-questions-des-juges)
- [M11 Éléments non vérifiés et corrections de la version 2](#m11-éléments-non-vérifiés-et-corrections)

---

## 0. Périmètre, méthode et conventions

### 0.1 Périmètre retenu (décisions de l'utilisateur)

| Décision | Application |
|---|---|
| Langue | Français |
| Code déployé seulement | Les chemins actifs depuis `backend/main.py` sont documentés. Le code inactif n'apparaît que lorsqu'il crée un doublon ou une valeur en conflit avec le chemin actif. Il est alors étiqueté **legacy**. |
| Tests, `data-prep/`, dossiers générés | **Exclus** (`backend/tests/`, `data-prep/`, `.venv`, `node_modules`, `dist`, `build`, caches). La consigne « Prend les pas en compte » a été lue comme « ne les prends pas en compte ». Le fichier `backend/tests/test_regularization.py` existe pour les nouvelles pénalités ; il n'a pas été utilisé comme source de valeurs. |

### 0.2 Chemin actif (vérifié par lecture des imports)

- Point d'entrée : `backend/main.py` (l.22 à 44) associe les modes `monport_check`, `monport`, `monport_chat`, `monport_rebuild` aux flux de `workflow/flow.py` (`stream_check` l.305, `stream_monport` l.310, `stream_chat` l.315, `stream_rebuild` l.320).
- Chaîne : `workflow/flow.py` → `monport.py` (profils, S, A, contraintes) → `workflow/workers.py` → `agents/portfolio_manager.py` → `allocator.py` (`optimize_with_relaxation`, `optimize_universe`, `select_holdings`) → `optimizer.py` (`_linear_lp`, `_solve_slsqp`, `optimize_weights`) ; `catalog.py` (`settings_for`, `plan_for`, `agent_request`) → `config.get_agent_settings` ; `market.py` (`get_market`, `estimate_expected_returns`, `universe_covariance`) ; `backtest.py`, `projection.py`, `factors.py`, `guardrail.py`, `runtime.py`.
- **Mode agent actif.** `catalog.settings_for` (`catalog.py:604`) appelle `get_agent_settings`, donc `CONSTRAINTS` est la base en production, pas `BASE_CONSTRAINTS`. `REGULARIZATION` est copiée dans les réglages par `config.py:652` (clé `regularization`), donc elle est active dans les deux modes.
- Point d'entrée distinct : `backend/mcp_server/main.py` → `tool_core.py`. Il utilise `allocator.optimize` (legacy pour le workflow principal, voir 0.3).

### 0.3 Code legacy ou inerte (signalé pour éviter les faux positifs)

| Élément | Où | Statut | Preuve |
|---|---|---|---|
| `BASE_CONSTRAINTS`, `BASE_PROFILE`, `get_base_settings` | `config.py:474`, `:583` | Simulation et CLI `optimizer.main` seulement | `settings_for` n'utilise que le mode agent |
| `CANDIDATES`, `constraints.select_candidates` | `config.py:291` | Inutilisé par MonPort (« MonPort n'en a plus besoin ») | Commentaire `config.py:~287` |
| `optimizer.estimate_expected_returns`, `optimizer.estimate_covariance` | `optimizer.py:174`, `:276` | Pipeline autonome (`optimize_portfolio`, CLI). Doublons de `market.estimate_expected_returns` | `build_market` appelle `market.py:439` |
| `MANDATES` (`mandates.py:26-61`) | `mandates.py` | Non référencé. Le workflow construit ses `Mandate` avec `vol_cap_factor=None` (`workers.py:191`) | `vol_cap_for` renvoie toujours `None` |
| `allocator.optimize` | `allocator.py:183` | Hors sélection du workflow. Reste actif via `_raise_volatility_cap` (`monport.py:720-745`) et `mcp_server` | |
| `BOND_SHIFT` | `monport.py:138` | Tout à 0.0, non utilisé | |
| `config.BACKTEST`, `config.REGIMES` | `config.py:428`, `:440` | `enabled: False`, sans lien avec `backtest.py` | |

### 0.4 Légende

- **Type** : *Constante en dur* (littéral dans une fonction ou un module), *Réglage configurable* (clé de `config.py`), *Argument de fonction*, *Paramètre dérivé*, *Entrée utilisateur dynamique*, *Estimé* (calculé sur les données, non choisi).
- **Lignes** : numéros relevés par `grep -n` sur le code du commit `9729f50`. Un `~` signale une valeur approximative.
- **non vérifié** : je n'ai pas pu confirmer l'information dans le code.
- Les chemins sont relatifs à `backend/src/invest_agents/` (abrégé **`ia/`**), sauf indication contraire. Le front-end est sous `frontend/src/`.
- Les tableaux fusionnent certaines des 13 colonnes demandées pour rester lisibles : *Composant et Catégorie* ensemble, *Objectif et Formule* ensemble, *Dépendances et Configurabilité* ensemble.

---

# Partie 1 — Cartographie des paramètres (backend)

## 1.A Rendements espérés et CAPM

Formules (`ia/market.py:48-127`, méthode active ; `ia/optimizer.py:174` est son doublon legacy) :

- Historique : `μ = moyenne(rendements quotidiens) × periods_per_year`.
- EWMA : poids `0.5^(âge / demi-vie)`, `μ = moyenne pondérée × periods_per_year`.
- CAPM avec rétrécissement : `μ = α·(rf + β·ERP) + (1−α)·μ_hist`. β = cov(titre, SPY) / var(SPY) sur les dates communes.
- Repli : si β est indisponible (historique commun trop court), `μ = μ_hist` et la méthode est notée `historical_fallback` (`market.py`, log « repli sur la méthode historique »).

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `RF_ANNUAL` | `0.035` | `Market.risk_free_rate`, `build_market`, `_best_sharpe`, `backtest()` | `ia/config.py:94` ; lu `ia/market.py:293`, `:438` ; `ia/allocator.py:119` | Config / Returns | Réglage configurable (défini une seule fois) | Taux sans risque. Cible CAPM `rf + β·ERP`, et Sharpe `(μ−rf)/σ` | Hausse : cible CAPM plus haute, Sharpe plus bas | Copié dans `capm_shrinkage.rf_annual` (l.132) et `capm_benchmark_shrinkage.rf_annual` (l.141). Modifiable en éditant `config.py` seulement. Hypothèse de démonstration (commentaire l.92-93) |
| `ESTIMATION.mode` | `"by_asset_class"` | `get_return_method` | `ia/config.py:99` ; `:757` | Config / Returns | Réglage configurable | Sélection de la méthode par classe, type ou symbole | Change la formule de μ par titre | `single_method` (l.100, `"historical"`) ne s'applique que si `mode == "single_method"` |
| `method_by_asset_class` | Equity→`capm_shrinkage` ; Fixed Income, Multi-Asset, Real Estate, Commodities, Alternative→`historical` | `get_return_method` | `ia/config.py:104-111` | Config / Returns | Réglage configurable | Règle de choix de méthode | Les obligations ont un μ purement historique. Les ETF d'actions passent aussi par le CAPM (ils sont `Equity`) | Priorité : symbole > type d'instrument > classe (non relu ligne à ligne : non vérifié) |
| `method_by_instrument_type` | `{"Cryptocurrency": "ewma"}` | idem | `ia/config.py:114` | Config / Returns | Réglage configurable | EWMA pour la crypto directe | | |
| `method_by_symbol` | `{"BITW": "ewma"}` | idem | `ia/config.py:115` | Config / Returns | Réglage configurable | EWMA pour l'ETP crypto | | |
| `historical.lookback_observations` | `None` (tout l'historique du titre) | `_historical_mu` | `ia/config.py:119` ; `ia/market.py:48` | Config / Returns | Réglage configurable | Fenêtre de μ historique | Une fenêtre plus courte rend μ plus réactif et plus bruité | « avant : 1260 » (commentaire). μ n'exige pas de dates communes |
| `historical.min_observations` | `120` | `_historical_mu` | `ia/config.py:120` | Config / Returns | Réglage configurable | Seuil d'historique minimal. Sinon `ValueError` | Hausse : plus de titres exclus | Aussi utilisé pour `historical_lookback` du CAPM (`market.py`) |
| `ewma.half_life_observations` | `90` | `_ewma_mu` | `ia/config.py:124` ; `ia/market.py:55` | Config / Returns | Réglage configurable | Poids `0.5^(âge/90)` | Baisse : μ plus réactif, plus volatil | `ewma.min_observations = 120` (l.125), `ewma.lookback_observations = None` (l.123) |
| `capm_shrinkage.market_proxy` | `"SPY"` | `estimate_expected_returns` | `ia/config.py:131` | Config / Returns | Réglage configurable | Benchmark unique du CAPM actif | Change β de tous les titres `Equity` | Un seul proxy : le même pour actions canadiennes, européennes, etc. |
| `capm_shrinkage.erp_annual` | `0.05` | idem | `ia/config.py:133` | Config / Returns | Réglage configurable (hypothèse) | Prime de risque actions dans `rf + β·ERP` | Hausse : cible CAPM plus haute, μ des actions plus haut | Commentaire : « hypothèse illustrative, pas une donnée live » |
| `capm_shrinkage.alpha` | `0.50` | idem | `ia/config.py:134` | Config / Returns | Réglage configurable | Poids de la cible CAPM : `μ = α·CAPM + (1−α)·hist` | Hausse : μ plus proche du CAPM, moins de la performance passée | Même valeur dans `capm_benchmark_shrinkage.alpha` (l.142) |
| `capm_shrinkage.min_paired_observations` | `120` | `_beta` | `ia/config.py:130` ; `ia/market.py:66` | Config / Returns | Réglage configurable | Dates communes minimales pour β. Sinon repli historique | Hausse : plus de replis | |
| `capm_shrinkage.lookback_observations` | `None` | `_beta` | `ia/config.py:129` | Config / Returns | Réglage configurable | Fenêtre de β | | « avant : 756 » |
| `capm_shrinkage.historical_lookback_observations` | `None` | `_historical_mu` | `ia/config.py:135` | Config / Returns | Réglage configurable | Fenêtre de la composante historique | | « avant : 1260 » |
| β | Estimé (cov/var avec SPY) | `_beta` | `ia/market.py:66-77` | Backend / Returns | **Estimé** (non choisi) | Sensibilité au marché | | `None` si variance du benchmark ≤ 0 |
| `capm_benchmark_shrinkage.*` | `alpha 0.50`, `min_paired_observations 120`, `erp_annual_by_benchmark {}`, `missing_premium_policy "error"`, `missing_benchmark_policy "error"` | `estimate_expected_returns` | `ia/config.py:137-148` | Config / Returns | Réglage configurable | Méthode CAPM par benchmark | **Aucune classe ne la sélectionne** : inactive en production | `erp_annual_by_benchmark` est vide : l'activer sans la remplir lève une erreur |
| `BENCHMARKS.single_market_proxy` | `"SPY"` | `get_capm_benchmark` | `ia/config.py:157+` ; fonction `:782` | Config / Returns | Réglage configurable | Proxy global | | Utilisé seulement par `capm_benchmark_shrinkage` (inactive) |
| `BENCHMARKS.symbol_overrides` | `{"NVDA": "SMH"}` | `get_capm_benchmark` | `ia/config.py:163` | Config / Returns | Réglage configurable | Benchmark individuel | | Inactif en production (méthode inactive) |
| `BENCHMARKS.etf_overrides` | 13 paires (SPY↔IYY, QQQ→SPY, XLK→SPY, VGT→SPY, SMH→SPY, XIU.TO↔XIC.TO, EFA→ACWX, EEM→ACWX, EWQ/EWG/EWU→VGK) | idem | `ia/config.py:~168-184` | Config / Returns | Réglage configurable | Mapping ETF → benchmark | | Inactif en production |
| `BENCHMARKS.stock_country_sector` | 17 clés (« United States\|Information Technology »→XLK, … « Canada\|Financials »→XFN.TO, …) | idem | `ia/config.py:~187-204` | Config / Returns | Réglage configurable | Mapping pays et secteur → ETF | | Inactif en production |
| `DATA.periods_per_year` | `252` | `_historical_mu`, `_ewma_mu`, `build_market` | `ia/config.py:40` ; `ESTIMATION.periods_per_year` l.98 | Config / Returns | Réglage configurable | Annualisation de μ et de `ann_vol` | Mal calibré : biais proportionnel de μ | Validé identique entre DATA, ESTIMATION et COVARIANCE (`validate_settings`, `config.py:922`). **Autre valeur : voir 1.B (annualisation de Σ)** |
| `ESTIMATION.forecast_horizon_years` | `1` | non vérifié | `ia/config.py:97` | Config / Returns | Réglage configurable | Horizon de prévision | non vérifié | Usage non confirmé |

**Constats de la section A**

- La méthode CAPM active n'utilise qu'**un seul benchmark (SPY)** pour toutes les actions. Les mappings sectoriels et pays de `BENCHMARKS` ne servent pas en production.
- Les ETF d'actions (classe `Equity`) reçoivent aussi le CAPM sur SPY (SPY lui-même obtient β = 1). Le commentaire de `config.py` (l.~101-103) signale que le look-through des ETF reste à gérer avant d'activer un CAPM personnalisé.
- `rf = 0.035` est défini une seule fois. Le cash (1 %) est volontairement distinct (voir 1.E).

## 1.B Matrice de covariance

Formules (`ia/market.py:129-322`, active) :

- Σ_quotidienne = estimateur Ledoit-Wolf, cible `μ·I` (`μ = trace/p`), intensité `β/δ` estimée.
- Univers d'optimisation : rendements **synchronisés** sur les dates communes (indice de rendement total par titre, jours fériés absorbés dans un rendement de plusieurs jours).
- `Σ_annuelle = Σ_quotidienne × periods_per_year_effective`, avec `periods_per_year_effective = observations_communes / années` et `années = jours / 365.25`.

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `COVARIANCE.method` | `"ledoit_wolf"` | `estimate_covariance`, `ledoit_wolf_universe` | `ia/config.py:227` ; `ia/market.py:164`, `:262` | Config / Covariance | Réglage configurable | Choix de l'estimateur (`sample` en alternative) | `sample` : pas de rétrécissement, matrice potentiellement mal conditionnée | `COVARIANCE_HISTORY.method` (l.267) répète « ledoit_wolf » |
| Intensité de rétrécissement Ledoit-Wolf | Estimée (`shrinkage = β/δ`) | `_ledoit_wolf`, `LedoitWolf.fit` | `ia/market.py:145-162`, `:~280` | Backend / Covariance | **Estimé** | Rétrécit Σ vers `μ·I` | Plus de rétrécissement : variances et corrélations tirées vers la moyenne | Rapporté dans `shrinkage_coefficient` du diagnostic (`market.universe_covariance`) |
| `ledoit_wolf.target` | `"scaled_identity"` | non lu par le code actif | `ia/config.py:243` | Config / Covariance | Réglage informatif | Cible du rétrécissement | | Le code actif utilise toujours `μ·I` (non vérifié qu'il lise cette clé) |
| `ledoit_wolf.shrinkage_intensity` | `"auto"` | non vérifié | `ia/config.py:~244` | Config / Covariance | Réglage informatif | | | Non lu dans `market.py` (non vérifié) |
| `ledoit_wolf.assume_centered` | `False` | `ledoit_wolf_universe` | `ia/config.py:244` ; `ia/market.py:~277` | Config / Covariance | Réglage configurable | Centrage des données | `True` ignore la moyenne : Σ légèrement plus grande | |
| `ledoit_wolf.block_size` | `1000` | `optimizer.estimate_covariance` (legacy) | `ia/config.py:245` | Config / Covariance | Réglage configurable | Taille de bloc sklearn | Aucun effet numérique | Non utilisé par `market.py` (non vérifié) |
| `COVARIANCE.lookback_observations` | `None` | `joint_window`, `build_market` | `ia/config.py:230` ; `ia/market.py:~129-135`, `:440` | Config / Covariance | Réglage configurable | Fenêtre de Σ (et de `ann_vol`) | | « avant : 1260 » |
| `COVARIANCE.min_observations_per_asset` | `120` (dérivé de `DATA`) | `optimizer.estimate_covariance` (legacy) | `ia/config.py:231` | Config / Covariance | Paramètre dérivé | | | |
| `COVARIANCE.min_joint_observations` | `120` | `joint_window`, `ledoit_wolf_universe` | `ia/config.py:235` ; `ia/market.py:~131`, `:~270` | Config / Covariance | Réglage configurable | Dates communes minimales. Sinon erreur | Hausse : exclut plus de portefeuilles | |
| `COVARIANCE.missing_policy_for_ledoit_wolf` | `"complete_cases_after_selection"` | `optimizer.estimate_covariance` (legacy) | `ia/config.py:233` | Config / Covariance | Réglage configurable | Aucun remplissage des NaN | | `never_fill_missing_returns True` (`DATA`, l.44) |
| `sample.min_pairwise_observations` | `60` | `market.estimate_covariance` | `ia/config.py:237` | Config / Covariance | Réglage configurable | Observations minimales par paire (méthode `sample`) | | Inactif tant que la méthode est `ledoit_wolf` |
| `sample.repair_psd` | `True` | idem | `ia/config.py:238` | Config / Covariance | Réglage configurable | Réparation PSD | | Inactif |
| `sample.eigenvalue_floor` | `1e-10` | idem | `ia/config.py:239` ; `ia/market.py:~175-180` | Config / Covariance | Réglage configurable | Plancher de valeur propre | | Inactif |
| `COVARIANCE_HISTORY.start_date` | `"2021-01-01"` | `history_filter` | `ia/config.py:265` ; `ia/market.py:~208` | Config / Covariance | Réglage configurable | Début de l'horizon. Un titre sans rendement à cette date est exclu de l'univers d'optimisation | Reculer la date : plus de titres admissibles, historique commun plus long | **Paramètre structurant** pour la taille de l'univers |
| `COVARIANCE_HISTORY.require_full_horizon` | `True` | `history_filter` | `ia/config.py:266` | Config / Covariance | Réglage configurable | Exige l'historique complet | `False` : n'exclut plus aucun titre | |
| `COVARIANCE_HISTORY.max_start_delay_business_days` | `5` | `history_filter` | `ia/config.py:268` ; `ia/market.py:~210` | Config / Covariance | Réglage configurable | Tolérance de calendrier | Hausse : accepte des titres plus récents | Borné à 0-10 par `validate_settings` (`config.py:922`) |
| `periods_per_year_effective` | Estimé : `n_communes / (jours/365.25)` | `synchronized_returns`, `Market.universe_covariance` | `ia/market.py:250`, `:257`, `:312` | Backend / Covariance | **Estimé** (dérivé) | Annualise Σ | Une période effective ≠ 252 change la volatilité de tous les titres | **Incohérence : voir ci-dessous** |
| Tolérance PSD (optimiseur) | `-1e-8` | `optimize_weights` | `ia/optimizer.py:519` | Backend / Covariance | Constante en dur | Refuse Σ non semi-définie positive | | |
| Symétrisation | `(Σ+Σᵀ)/2` | `ledoit_wolf_universe`, `optimize_weights` | `ia/market.py:~274` ; `ia/optimizer.py:~518` | Backend / Covariance | Constante en dur (opération) | | | |
| Tolérances PSD legacy | `-1e-10`, floor `sample.eigenvalue_floor` | `optimizer.estimate_covariance` | `ia/optimizer.py:349` | Backend / Covariance | Constante en dur (legacy) | | | Pipeline autonome seulement |

**Incohérence d'annualisation (constat vérifié dans le code)**

- μ et `ann_vol` annualisent avec **252** (`DATA.periods_per_year`).
- Σ de l'univers annualise avec `periods_per_year_effective` (`n / (jours/365.25)`), qui n'est pas forcément 252 (`market.py:312` : `info["periods_per_year_effective"] or float(252)`).
- Conséquence : `ann_vol` (écrans, tri, Sharpe de screening) et `sqrt(diag Σ)` (volatilité du portefeuille, et seuil des pénalités de 1.B.2) ne sont pas calculés avec la même base. L'écart dépend du nombre de dates communes retenues. Je n'ai pas exécuté le code, donc l'ampleur de l'écart n'est **pas vérifiée**.
- `market.moments` utilise `estimate_covariance` (LW non synchronisé, annualisé à 252) pour tout symbole **hors** de l'univers d'optimisation (`market.py:391`).

## 1.B.2 Pénalités de régularisation liées à Σ (deux pénalités)

**Nouveauté.** Deux pénalités souples sont ajoutées à l'utilité de Markowitz. Elles ne sont pas des contraintes. Elles lisent la **diagonale de Σ** (la variance de chaque titre dans la matrice annualisée de l'optimiseur). Elles sont définies dans `config.REGULARIZATION` (`config.py:405-409`) et calculées par trois fonctions de `optimizer.py`.

### Formule

```
U = wᵀμ − (A/2)·wᵀΣw − λ_D · Σᵢ wᵢ² − λ_V · Σᵢ qᵢ·wᵢ²
qᵢ = max(0, Σᵢᵢ − seuil²)        (Σᵢᵢ = variance annualisée du titre i ; seuil = σ maximal toléré)
```

- **λ_D** (`diversification_penalty`) : pénalise la somme des carrés des poids, donc la concentration (indice de Herfindahl), de façon uniforme.
- **λ_V** (`high_volatility_penalty`) : pénalise les gros poids dans les titres dont la volatilité dépasse `volatility_threshold`. Les titres sous le seuil ont `q = 0` et ne sont pas pénalisés.
- Gradient : `∇pénalité = 2·λ_D·w + 2·λ_V·(q ⊙ w)`. Le gradient de l'utilité vaut donc `μ − A·Σw − 2·λ_D·w − 2·λ_V·(q ⊙ w)`.

**Équivalence mathématique (dérivée à la main, non présente dans le code).** `U = wᵀμ − ½·wᵀ(A·Σ + 2λ_D·I + 2λ_V·diag(q))·w`. Les deux pénalités reviennent donc à **ajouter un terme diagonal à Σ** (un « ridge ») : `Σ_eff = Σ + (2λ_D/A)·I + (2λ_V/A)·diag(q)`. Les corrélations ne changent pas, seules les variances propres des titres sont gonflées. À λ_D = λ_V = 0, l'optimiseur est identique à celui d'avant.

### Paramètres

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `REGULARIZATION.diversification_penalty` (λ_D) | `0.0` | `regularization_coefficients`, `regularization_penalty`, `regularization_gradient` | `ia/config.py:406` ; `ia/optimizer.py:391-422` | Config / Covariance (pénalité) | Réglage configurable (**non calibré**, commentaire `config.py:~402-404`) | `λ_D·Σ wᵢ²` | Hausse : portefeuille plus dispersé. Exemple à la main : poids 0.5 sur un seul titre → pénalité `λ_D·0.25` ; deux titres à 0.25 → `λ_D·0.125` | Validé fini et ≥ 0 (`config.py:1057-1060`). **Absent des champs autorisés de `apply_portfolio_request`** (`config.py:1091-1098`) : ni l'agent ni le client ne peuvent le changer. Modifiable en éditant `config.py` |
| `REGULARIZATION.high_volatility_penalty` (λ_V) | `0.0` | idem | `ia/config.py:407` | Config / Covariance (pénalité) | Réglage configurable (**non calibré**) | `λ_V·Σ qᵢ·wᵢ²` | Hausse : réduit les poids des titres très volatils. Exemple à la main : titre à σ = 40 %, seuil 25 % → `q = 0.16 − 0.0625 = 0.0975` ; poids 0.5 → pénalité `λ_V·0.0975·0.25 ≈ λ_V·0.0244` | Idem. Interagit avec A (voir ci-dessus) |
| `REGULARIZATION.volatility_threshold` | `0.25` (25 % annualisé) | `excess_variance` | `ia/config.py:408` ; `ia/optimizer.py:398-401` | Config / Covariance (pénalité) | Réglage configurable (hypothèse) | Seuil de `qᵢ` | Hausse : moins de titres pénalisés. `0.25` coïncide avec le dernier ancrage de `VOL_ANCHORS` (0.25), sans lien dans le code | Compare `√Σᵢᵢ` de **l'optimiseur** (annualisé avec `periods_per_year_effective`, voir ci-dessus), pas `ann_vol` de `market.py`. Défaut du code si la clé manque : `0.25` (`optimizer.py:392-396`) |
| `qᵢ` (variance en excès) | Calculé : `max(0, Σᵢᵢ − seuil²)` | `excess_variance` | `ia/optimizer.py:398-401` | Backend / Covariance | **Paramètre dérivé** | Mesure par titre de l'excès de variance | | Calculé une fois par résolution (`_solve_slsqp`, `optimizer.py:435`) et une fois dans `select_holdings` (`allocator.py:377`). Le cash (variance 0) a `q = 0` |
| Clé `regularization` des réglages | `REGULARIZATION` | `_get_engine_defaults` | `ia/config.py:652` | Config / Autre | Réglage configurable | Transmet la section à l'optimiseur | | `cfg.get("regularization") or {}` : absente → pénalités nulles (`optimizer.py:393`). Validation tolérante à une ancienne configuration (`config.py:1057`) |
| Formule de l'objectif | `U = … − λ_D·Σw² − λ_V·Σq·w²` | `OPTIMIZATION["formula"]` | `ia/config.py:413` | Config / Solver | Texte informatif | Documentation | | Texte, non évalué |

### Propagation : où les pénalités agissent

| Étape | Fonction | Fichier : lignes | Effet |
|---|---|---|---|
| Résolution continue | `_solve_slsqp` | `ia/optimizer.py:424-455` | La fonction à minimiser (`negative_utility`, l.437-439) et son gradient (`derivative`, l.441-442) incluent les pénalités |
| Optimum continu global | `_continuous` | `ia/allocator.py:302` | Appelle `_solve_slsqp` avec les réglages (donc pénalisé) |
| Optimum sur la sélection | `_floored` → `_continuous` | `ia/allocator.py:324` | Idem |
| Résolution finale sur la sélection | `_solve` → `optimize_weights` → `_solve_slsqp` | `ia/allocator.py:108` ; `ia/optimizer.py:471` | Idem. Pour `max_sharpe`, `_best_sharpe` (l.115) parcourt `A_LADDER` avec des poids pénalisés |
| Utilité reportée | `optimize_weights` | `ia/optimizer.py:569-576` | `PortfolioResult.utility = μ·w − ½·A·w'Σw − pénalité` (utilité pénalisée) |
| Utilité de référence | `_utility` | `ia/allocator.py:339-344` | Remplace l'ancien calcul. Sert à `u0` (l.517), à la comparaison de `select_holdings` et à `utility_final` du diagnostic |
| Gain marginal de sélection | `marginal` dans `select_holdings` | `ia/allocator.py:379-382` | `μ − A·Σw − 2λ_D·w − 2λ_V·(q ⊙ w)` : classe les titres à ajouter en tenant compte des pénalités |

**Ce que les pénalités ne modifient pas.**

- `portfolio_metrics` (`market.py:394`) : `expected_return`, `volatility`, Sharpe et drawdown affichés sont calculés sur les poids finaux **sans** pénalité. La pénalité n'agit que sur les poids.
- Le calcul du Sharpe dans `_best_sharpe` : il utilise `run.expected_return_annual` et `run.volatility_annual`, non pénalisés. Seul le choix des poids est affecté.
- `_under_cap` : le plafond de volatilité est vérifié sur `run.volatility_annual` non pénalisé.
- μ, Σ, le cash, les contraintes et les trois variantes : **les mêmes** λ_D et λ_V s'appliquent aux trois portefeuilles (commentaire `config.py:401`). Ils ne dépendent ni du profil, ni de S, ni de A.

**Incidences à retenir.**

1. Avec les valeurs actuelles (0.0), l'effet est nul. Rien n'est calibré.
2. λ_D et λ_V jouent comme une hausse de A *sur la diagonale seulement* (voir l'équivalence). Elles s'ajoutent à A sans que le diagnostic `A_effective` (`allocator.py:552`) en rende compte.
3. Le seuil de 25 % s'applique à `√Σᵢᵢ` de la matrice Ledoit-Wolf rétrécie. Une variance rétrécie vers la moyenne peut placer un titre sous ou sur le seuil par rapport à son écart-type brut.
4. La base d'annualisation de Σ (252 contre `periods_per_year_effective`) déplace directement l'ensemble des titres au-dessus ou en dessous du seuil.
5. Pour le profil incohérent, le mélange 80/20 (`blend`) est recalculé par le code après coup (`enforce_minimum`) et ne repasse pas par l'optimiseur : les pénalités ne s'appliquent donc pas au mélange lui-même, mais seulement à ses bases.

## 1.C Aversion au risque et profils investisseur

Détail complet des formules en [1.G](#1g-section-spéciale--profils-et-aversion-au-risque). Ce tableau liste les valeurs.

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `RISK_AVERSION.min` / `.max` | `1.0` / `25.0` | `apply_portfolio_request`, `catalog.agent_request` | `ia/config.py:310-311` ; `ia/catalog.py:573-575` | Config / Risk Aversion | Réglage configurable | Plage permise de A | | **Dupliqué** : `allocator.A_MIN, A_MAX = 1.0, 25.0` (`allocator.py:45`) et `PepiteCheck.risk_aversion` ge=1, le=25 (`ia/schemas.py:318`) |
| `RISK_AVERSION.default` | `5.0` | `apply_portfolio_request` | `ia/config.py:312` | Config / Risk Aversion | Réglage configurable | A si aucun A fourni. Écrasé par `risk_aversion_A` de la requête | | `catalog.agent_request` envoie 5.0 si A est `None`. **Autre défaut : `PepiteCheck.risk_aversion` vaut `7.0` par défaut** (`schemas.py:318`) |
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
| Pondérations de la tolérance T | `0.5` (réaction), `0.3` (objectif), `0.2` (confort) | `tolerance` | `ia/monport.py:352` | Backend / Risk Aversion | Constante en dur | `T = 0.5·r + 0.3·o + 0.2·c` | | **Dupliqué** `engine.ts:56` et `RiskNotebook.tsx:139-141` |
| Plafond d'horizon | `20` ans | `capacity` | `ia/monport.py:341-343` | Backend / Risk Aversion | Constante en dur | `h = (min(horizon,20) − 1)/19` | | |
| Âge de référence | `75`, diviseur `50` | `capacity` | `ia/monport.py:343` | Backend / Risk Aversion | Constante en dur | `a = (75 − âge)/50` | | |
| `LOSS_BY_REACTION` | `{0:10.0, 1:15.0, 2:25.0, 3:35.0}` (points de %) | `to_form` | `ia/monport.py:128` | Backend / Risk Aversion | Constante en dur | Perte acceptée selon la réaction. Sert au formulaire des agents, pas à S | | **Dupliqué** en fractions `engine.ts:303` |
| `LINE_CAP` | `0.40` | `validate_profile`, `build_profiles`, `_limits`, `blend` | `ia/monport.py:132` ; `ia/evidence.py:27` ; `engine.ts:9` | Backend / Constraints | Constante en dur | Plafond par ligne, jamais assoupli | | Triple duplication (backend ×2, front) |
| `JUDGE_RELAUNCH_PENALTY` | `3` | `_penalty` | `ia/config.py:288` ; `ia/workflow/workers.py:271-273` | Config / Risk Aversion | Réglage configurable | Points retirés à la note du juge d'un portefeuille relancé avec limites assouplies. Appliqué seulement si `session.coherent and p.relaunch_reason` | Hausse : un portefeuille relancé gagne moins souvent | Utilisé par `JudgeVerdict.ranked_score = max(0, fit_score − penalty)` (`schemas.py:246-248`) et par `pick_winner` (`monport.py:894`) |
| `PepiteCheck.risk_aversion` | ge 1, le 25, défaut `7.0` | schéma | `ia/schemas.py:318` | Backend / Risk Aversion | Contrainte de schéma | | | Doublon de la plage de `config` ; défaut différent |

## 1.D Agent, sentiment et ajustements

**Résultat de la vérification : il n'existe aucun mécanisme de « sentiment », de `ΔS` de sentiment ni de règle `S+1` / `S−1` codés dans le backend.** Un seul mécanisme d'ajustement existe : les **crans de Pépite** (agent LLM), décrits ci-dessous. Aucune règle de code ne convertit une préférence qualitative en nombre de crans : le LLM choisit lui-même la valeur, le code ne fait que la borner.

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `adjust_steps` (cumul des crans) | borné à `[−2, +2]` | `adjust_risk_position` | `ia/workflow/pepite.py:231`, `:243` : `max(-2, min(2, before + int(steps)))` | Agent / Sentiment | **Entrée dynamique** (décidée par le LLM) | Cumul des crans demandés. Chaque cran vaut `ADJUSTMENT_STEP` | ±2 crans = ±0.10 de S, soit une demi-catégorie | Désactivé en phase « chat » (message `IN_CHAT`, `pepite.py:208`, `:241`, `:278`). Bornage codé en dur |
| `ADJUSTMENT_STEP` | `0.05` | `risk_position` | `ia/monport.py:149`, utilisé `:355-359` | Backend / Sentiment | Constante en dur | `S = clamp(min((C+T)/2, C+0.125) + 0.05·clamp(adj,−2,2), 0, 1)` | Hausse : chaque cran déplace plus S | Le plafond de capacité est appliqué **avant** l'ajustement : la marge `CAPACITY_MARGIN` ne limite donc pas les crans |
| Décision de « combien de crans » | Décidée par le LLM | prompts `BUILD_TASK`, `REBUILD_TASK` | `ia/workflow/pepite.py:425`, `:471` (consigne `adjust_risk_position` vers `:428`) | Agent / Sentiment | Entrée dynamique | Le prompt dit d'utiliser `adjust_risk_position` si le client parle du risque qu'il veut prendre | Non reproductible : dépend du modèle et du texte du client | Aucun seuil ni poids numérique côté code |
| `MAX_ADJUSTMENT` | `1000` caractères | `build_portfolios`, `chat`, `rebuild` | `ia/monport.py:133` ; `ia/workflow/flow.py:212`, `:239`, `:263` | Backend / Autre | Constante en dur | Tronque le texte libre d'ajustement | | |
| `session.adjust_steps` → `assess` | passé en 3ᵉ argument | `Session.check` | `ia/workflow/session.py:63`, `:107-111` ; `ia/monport.py:528-536` | Backend / Sentiment | Paramètre dérivé | Recalcule S, A, plafond de vol., plafond par titre | | |
| `coherent` | booléen décidé par Pépite | `set_coherence`, `fallback_check` | `ia/workflow/pepite.py:250` ; `ia/monport.py:539-542` | Agent / Sentiment | Entrée dynamique | Détermine « profil cohérent » ou non, donc la construction des 3 portefeuilles | Bascule la structure entière (voir 1.G) | Repli sans LLM : `coherent = not facts` avec `facts = coherence_facts` (`monport.py:424-443`) |
| Seuils de `coherence_facts` | score < 40 et crypto demandée ; score < 40 et actions ≥ 0.7 ; score > 65 et actions exclues ou ≤ 0.3 ; score < 77 et `vehicles == "titres"` ; une seule classe gardée | `coherence_facts` | `ia/monport.py:424-443` | Backend / Sentiment | Constantes en dur | Détecte une contradiction entre profil et préférences | Modifie la cohérence, donc la structure des 3 portefeuilles | **Dupliqué** dans `engine.ts:306-323` (mêmes seuils 40, 0.7, 65, 0.3, 77) |
| `preference_contradictions` | somme des % de classes ou régions > `1 + 1e-9` | `preference_contradictions` | `ia/monport.py:388-422` | Backend / Contraintes | Constante en dur | | | |
| `RULES` du front (regex) | tech→`themes.tech 30`, pétrole/fossile→exclusion, crypto/bitcoin→`classes.crypto 10`, prudent/moins de risque→`riskShift −15` | `proposeAdjustment` | `frontend/src/api.ts:252-299` | Front-end / Sentiment | Constantes en dur (mock) | Simule la réponse de Pépite hors ligne | | **Équivalent backend : aucun** (LLM). Échelle différente (±15 points de score contre ±0.05 sur S par cran) |

**Conséquence.** Les « poids de sentiment » demandés par la consigne n'existent pas. L'influence du texte libre du client sur S passe par un jugement de LLM, borné à ±0.10 de S. C'est un point de calibration et de reproductibilité (voir 3.C).

## 1.E Optimisation de portefeuille

Objectif (`ia/optimizer.py:437-442`, `ia/allocator.py:339-344`), **version avec pénalités** : maximiser `U = μᵀw − (A/2)·wᵀΣw − λ_D·Σwᵢ² − λ_V·Σqᵢwᵢ²`. Le code minimise `−U`, avec le gradient analytique `−μ + AΣw + 2λ_D·w + 2λ_V·(q ⊙ w)`. À λ_D = λ_V = 0 (valeurs actuelles), l'objectif redevient `U = μᵀw − (A/2)·wᵀΣw`. Détail en [1.B.2](#1b2-pénalités-de-régularisation-liées-à-σ-deux-pénalités).

### Contraintes et plafonds

| Paramètre | Valeur actuelle (production) | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `CONSTRAINTS.max_weight_per_asset` | `None` | `apply_portfolio_request`, `build_constraint_plan` | `ia/config.py:340` | Config / Constraints | Réglage configurable | Plafond par actif. **Aucun plafond global en production** | | Le plafond effectif vient de `MAX_POSITION_WEIGHT` (0.40) ajouté par `monport.validate_profile` et de `MAX_STOCK_WEIGHT` |
| `BASE_CONSTRAINTS.max_weight_per_asset` | `0.10` | | `ia/config.py:491` | Config / Constraints | Réglage configurable | **Mode BASE seulement (inactif)** | | **Conflit de défaut** : 0.10 (BASE) contre `None` (production) |
| `MAX_POSITION_WEIGHT` (`LINE_CAP`) | `0.40` | `validate_profile`, `_limits`, `agent_request` | `ia/monport.py:132`, `:666-681`, `:564-568` ; `ia/catalog.py:562` | Backend / Constraints | Constante en dur | Plafond par ligne, FNB compris. Jamais assoupli par `RELAXATION_STEPS` (`allocator.py:579`, `:602`) | | |
| `MAX_STOCK_WEIGHT` | `min(STOCK_ANCHORS(S), 0.40)` | `build_profiles`, `validate_profile`, `stock_cap` | `ia/monport.py:781-783`, `:~675`, `:811-814` | Backend / Constraints | Paramètre dérivé | Plafond par action en direct. `stock_cap` renvoie le plus petit `MAX_STOCK_WEIGHT` dur, sinon `LINE_CAP` | | Non appliqué à « Tes préférences » du profil incohérent (`monport.py:781`) |
| `min_held_weight` | `0.01` | `_active_set_plan`, `restrict_plan`, `_weights`, `enforce_minimum` | `ia/config.py:334`, `:280`, `:481` ; `ia/allocator.py:44` ; `ia/monport.py:817` (`MIN_POSITION_WEIGHT`) | Config / Constraints | Réglage configurable (**plusieurs copies**) | « 0 ou au moins 1 % » | Hausse : moins de positions | **Dupliqué** : `CONSTRAINTS` (l.334), `PORTFOLIO_HOLDINGS` (l.280), `BASE_CONSTRAINTS` (voir `config.py:474+`), `allocator.MIN_POSITION_WEIGHT` (l.44) et textes « 1 % » en dur (`constraints.py:~814`, `~934`) |
| `minimum_holding_max_iterations` | `30` | `optimize_weights` | `ia/config.py:336` | Config / Solver | Réglage configurable | Itérations de la méthode prune/reoptimize | | Le code lit une boucle bornée par le nombre d'actifs (non vérifié que cette clé est lue) |
| `minimum_holding_tolerance` | `1e-8` | `optimize_weights` | `ia/config.py:337` | Config / Solver | Réglage configurable | Tolérance de micro-position | | Distinct de `constraint_tolerance` |
| `min_cash_weight` / `max_cash_weight` | `0.0` / `1.0` | `settings_for` | `ia/config.py:348-349` | Config / Constraints | Réglage configurable | **Neutralisé en production** : `settings["cash"]["enabled"]=False` et `min_cash_weight=0.0` | | `ia/catalog.py:605-606`. `max_cash_weight` n'est jamais transmis par `agent_request` |
| `CASH.annual_expected_return` | `0.01` | `optimize_weights`, `_continuous` | `ia/config.py:394` ; `ia/optimizer.py:508` ; `ia/allocator.py:307` | Config / Returns | Réglage configurable (hypothèse) | μ du cash synthétique | | **Inactif en production** (cash désactivé) |
| `CASH.annual_volatility` | `0.0` | `optimize_weights` | `ia/config.py:395` | Config / Covariance | Réglage configurable | | | Un cash non nul en volatilité lève une erreur (`optimizer.py:512-513`) |
| `group_limits` (`CONSTRAINTS`) | tous vides | `apply_portfolio_request` | `ia/config.py:~353-363` | Config / Constraints | Réglage configurable | Plafonds de groupe vides. Les groupes viennent des contraintes du client (`MIN_ASSET_CLASS_WEIGHT`, parts) | | `BASE_CONSTRAINTS.group_limits` (l.529-559) est **inactif** : Alternative 0.05, Commodities 0.10, Real Estate 0.15, Cryptocurrency 0.05, IT 0.25, Financials 0.30, Energy 0.20, emergents 0.15 |
| `unknown_exposure_policy` | `"strict"` (défaut `constraints.py`, mode agent) ; `"flag"` (BASE) | `filter_eligible_universe` | `ia/constraints.py:~360` ; `ia/config.py:573` | Config / Constraints | Réglage configurable | Traitement d'un ETF à exposition inconnue face à un plafond | | |
| `instrument_selection` | `"mixed"` par défaut | `apply_portfolio_request` | `ia/config.py:~342` ; `INSTRUMENT_SELECTION` | Config / Constraints | Réglage configurable | etf_only, mixed, stocks_only | | |
| `FACTOR_SLEEVE_MIN` | `0.10` | `plan_for`, `_factor_groups` | `ia/catalog.py:156` | Backend / Constraints | Constante en dur | Au moins 10 % en actions notées si un facteur est contraint | | |
| `FACTOR_MARGIN` | `0.01` | idem | `ia/catalog.py:157` | Backend / Constraints | Constante en dur | L'optimiseur vise 1 point au-delà du seuil | | |
| `FACTOR_LEVELS` | `{2:0.5, 1:0.2, −1:−0.2, −2:−0.5}` | `preference_constraints` | `ia/monport.py:113` | Backend / Constraints | Constante en dur | Niveau du questionnaire → exposition cible (écarts-types) | | **Dupliqué** `frontend/src/data/catalog.ts:160` |
| `FTOL` / `EXACT_TOL` / `SCORE_RANGE` | `0.01` / `1e-3` / `3.0` | `evaluate`, `audit` | `ia/catalog.py:158`, `:154`, `:155` | Backend / Constraints | Constantes en dur | Tolérances et bornes des contraintes | | |
| `TOL` / `WTOL` / `HELD` | `1e-3` / `2e-4` / `5e-4` | `evaluate`, `audit` | `ia/catalog.py:67-69` | Backend / Constraints | Constantes en dur | Tolérances volatilité, poids, seuil « détenu » | | Autres seuils « détenu » : `1e-7` (`optimizer.py:73`), `1e-9` (`constraints.TOL`, `:36`), `0.005` (`allocator._weights`, l.169) |
| `RELAXATION_STEPS` | 3 familles : pourcentages visés, plafonds, exclusions | `optimize_with_relaxation`, `_soften` | `ia/allocator.py:580-596`, `:598-607`, `:617` | Backend / Constraints | Constante en dur | Ordre d'assouplissement après échec. Une contrainte assouplie devient une préférence (`hard=False`). Le plafond de volatilité du mandat tombe avec « plafonds » | Détermine ce qui est sacrifié en premier | `MAX_POSITION_WEIGHT` jamais assoupli (`allocator.py:602`) |
| Cap de volatilité relevé | `ceil((vol_min + 0.003) × 100) / 100` | `_raise_volatility_cap` | `ia/monport.py:745` | Backend / Constraints | Constante en dur | Marge de 0.3 point sur la volatilité minimale atteignable | | |

### Nombre de positions et sélection

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `PORTFOLIO_HOLDINGS.min_count` | `25` | `holdings_range`, `select_holdings` | `ia/config.py:278` ; `ia/allocator.py:458-470`, `:347` | Config / Constraints | Réglage configurable | Minimum de positions détenues | | Surchargé par `MIN_POSITIONS` dur du client (`holdings_range`). Le mélange 80/20 utilise la même plage (`position_range`, `monport.py:802-808`) |
| `PORTFOLIO_HOLDINGS.max_count` | `70` | idem | `ia/config.py:279` | Config / Constraints | Réglage configurable | Maximum de positions | | Surchargé par `MAX_POSITIONS` du client. La docstring de `portfolio_manager.py:4` dit « 25 à 60 (cible 50) » : périmée |
| `PORTFOLIO_HOLDINGS.max_marginal_utility_cost` | `0.0001` | `select_holdings` | `ia/config.py:283` ; `ia/allocator.py:364`, `:430` | Config / Constraints | Réglage configurable | 1 point de base d'utilité par position ajoutée au-delà du minimum. **L'utilité comparée est désormais pénalisée** (`_utility`) | Hausse : plus de positions | Lots d'ajout de 10 (minimum, l.391) et de 5 (diversification, l.426) en dur |
| `MAX_ASSETS_PER_PORTFOLIO` | `40` (env) | `_check_selection`, `_raise_volatility_cap` | `ia/runtime.py:49` ; `ia/allocator.py:87` ; `ia/monport.py:740` | Config / Autre | Variable d'environnement | Plafond de titres d'une sélection | | Autre usage : `min(15, …)` dans `tools.py:270`, `:292` |
| `A_LADDER` | `(1.0, 1.5, 2.0, 3.0, 4.5, 7.0, 10.0, 14.0, 18.0, 25.0)` | `_best_sharpe`, `_under_cap` | `ia/allocator.py:47` | Backend / Solver | Constante en dur | Échelle de A parcourue pour max_sharpe et plafond de volatilité | Plus fine : portefeuille plus près de l'optimum | |
| `CAP_REFINEMENTS` | `6` | `_under_cap` | `ia/allocator.py:48` | Backend / Solver | Constante en dur | Pas de dichotomie pour coller au plafond | | |
| `POSITIVE` | `1e-6` | `select_holdings`, `optimize_universe` | `ia/allocator.py:260` | Backend / Solver | Constante en dur | Poids « positif » de la solution continue | | |
| `A_MIN`, `A_MAX` | `1.0`, `25.0` | `_solve`, `optimize_universe` | `ia/allocator.py:45`, `:111` | Backend / Solver | Constante en dur (**doublon**) | Borne le A passé au solveur | | Doublon de `RISK_AVERSION` |
| A initial `aversion0` | `A_MAX` si `min_volatility` ; `A_MIN` si `max_return` ; sinon `risk_aversion or A_MAX/5` (= 5.0) | `optimize_universe` | `ia/allocator.py:510` | Backend / Risk Aversion | Constante en dur (règle) | A de l'optimum continu et de `select_holdings` | | **Doublon legacy** : `allocator.optimize` utilise `A_MAX/2` (= 12.5) (`allocator.py:216`) |
| Seuil des guides | A ≥ 7 → style « min_volatility » ; A ≥ 3.5 → « max_sharpe » ; sinon « max_return » | `guidance_for` | `ia/monport.py:649-654` | Backend / Autre | Constante en dur | Texte seulement | | |
| `λ_D`, `λ_V`, seuil | `0.0`, `0.0`, `0.25` | `_solve_slsqp`, `_utility`, `select_holdings` | `ia/config.py:405-408` | Config / Solver | Réglage configurable | Voir [1.B.2](#1b2-pénalités-de-régularisation-liées-à-σ-deux-pénalités) | | |

### Solveur

| Paramètre | Valeur actuelle | Fonction | Fichier : lignes | Comp. / Cat. | Type | Objectif et formule | Impact | Dépendances et configurabilité |
|---|---|---|---|---|---|---|---|---|
| `OPTIMIZATION.solver` | `"SLSQP"` | `optimize_weights` | `ia/config.py:~414` ; `ia/optimizer.py:493` | Config / Solver | Réglage configurable | Toute autre valeur lève une erreur | | |
| `solver_options.maxiter` | `2000` | `_solve_slsqp` | `ia/config.py:417` ; `ia/optimizer.py:446-448` | Config / Solver | Réglage configurable | Itérations maximales de SLSQP | | `options=dict(cfg["optimization"]["solver_options"])` |
| `solver_options.ftol` | `1e-9` | idem | `ia/config.py:418` | Config / Solver | Réglage configurable | Tolérance de convergence | | |
| `constraint_tolerance` | `1e-7` | `validate_weights` | `ia/config.py:421` | Config / Solver | Réglage configurable | | | Validé > 0 (`config.py:1055`) |
| `sum_weights_tolerance` | `1e-7` | `validate_weights` | `ia/config.py:422` | Config / Solver | Réglage configurable | | | |
| Seuil de faisabilité LP | `1e-10`, `1e-9` | `_linear_lp` | `ia/optimizer.py:380-381` | Backend / Solver | Constante en dur | Cohérence des bornes | | |
| Micro-position | `tol < w < min_held − tol` | `optimize_weights` | `ia/optimizer.py:534` | Backend / Solver | Constante en dur (règle) | Déclenche la boucle prune/reoptimize | | |
| `risk_free_rate` du Sharpe | `0.035` | `_best_sharpe`, `portfolio_metrics` | `ia/allocator.py:119` ; `ia/market.py:401` | Backend / Solver | Dérivé de `RF_ANNUAL` | `(μ−rf)/σ` | | |

## 1.F Autres paramètres

### Mélange 80/20 du profil incohérent (nouveau comportement)

| Paramètre | Valeur | Fonction | Fichier : lignes | Type | Objectif et impact |
|---|---|---|---|---|---|
| `BLEND` | `0.8` | `blend` | `ia/monport.py:56`, `:856-891` | Constante en dur | 80 % du poids du cœur, 20 % du satellite : `w = 0.8·w_cœur + 0.2·w_satellite` |
| Minimum d'un mélange | `MIN_POSITION_WEIGHT` (0.01) | `enforce_minimum` | `ia/monport.py:817-853` | Constante (importée) | Les positions sous 1 % sont retirées. S'il en reste moins que `min_count`, les plus grosses des retirées sont gardées à exactement 1 %. Plus que `max_count` : les plus petites sont retirées |
| Plafond d'un titre en direct dans le mélange | `0.8·cap_cœur + 0.2·cap_satellite` | `blend` | `ia/monport.py:872-874`, `:811-814` | Paramètre dérivé | `cap(slot)` = `stock_cap` du profil (`MAX_STOCK_WEIGHT` dur, sinon `LINE_CAP`). Un FNB est limité à `LINE_CAP` (0.40) |
| Plage de positions du mélange | 25 à 70 par défaut | `position_range` | `ia/monport.py:802-808` ; appel `ia/workflow/flow.py:153-158` | Dérivé de `PORTFOLIO_HOLDINGS` | Ajustée aux `min/max_positions` durs des deux profils |
| Redistribution | jusqu'à 100 itérations, tolérance `1e-9` | `enforce_minimum` | `ia/monport.py:817-853` | Constantes en dur | Redistribue le poids libéré au prorata, sous les plafonds, sans descendre sous 1 % |
| Héritage de la relance assouplie | `relaunch_reason`, `relaxed` | `blend` | `ia/monport.py:889-890` ; `ia/schemas.py:219-220` | Dérivé | Le mélange hérite de la relance de l'une ou l'autre de ses bases |
| Pénalité de note | `JUDGE_RELAUNCH_PENALTY` = 3 | `_penalty`, `pick_winner` | `ia/workflow/workers.py:271-273` ; `ia/monport.py:894-910` | Réglage configurable | Profil cohérent seulement |

**Conséquence pour les pénalités de 1.B.2.** Le mélange n'est **pas** réoptimisé : les pénalités s'appliquent aux portefeuilles de base, pas au résultat 80/20, dont les poids sont recalculés par `enforce_minimum`.

### Backtest, projection, risque affiché

| Paramètre | Valeur | Fonction | Fichier : lignes | Type | Objectif et impact |
|---|---|---|---|---|---|
| `LOOKBACK_YEARS` | `6` | `backtest` | `ia/backtest.py:26` | Constante en dur | Fenêtre du backtest. Retourne `None` si l'historique commun fait moins de 252 jours |
| `YEAR` | `252` | `summarize` | `ia/backtest.py:27` | Constante en dur | Annualisation du backtest. **Indépendant** de `DATA.periods_per_year` |
| `BIWEEKLY`, `SAMPLE_EVERY` | `10`, `5` | `rebalance_mask`, `summarize` | `ia/backtest.py:28-29` | Constantes en dur | Rééquilibrage aux deux semaines (10 séances) ; un point de série par semaine |
| `DAILY_STEP`, `DAILY_LIMIT` | `0.5`, `5.0` | `daily_distribution` | `ia/backtest.py:30-31` | Constantes en dur | Tranches de la distribution (points de %), bornées à ±5 % |
| `FREQUENCIES` | deux-semaines, mensuelle, annuelle, aucune | `backtest` | `ia/backtest.py:25` | Constante en dur | Fréquences simulées |
| Quantile VaR/ES | `0.05` | `summarize` | `ia/backtest.py:106-107` | Constante en dur | VaR et ES historiques à 1 jour, renvoyés en perte positive (`round(-q, 4)`) |
| `rf` du backtest | `market.risk_free_rate` | `to_portfolio` | `ia/monport.py:1065` | Dérivé de `RF_ANNUAL` | Sharpe réalisé du backtest |
| `PER_YEAR` | 26, 12, 1, 12 | `project` | `ia/projection.py:20` | Constante en dur | Versements par an. `aucune` composé sur 12 périodes |
| `PATHS` | `1000` | `project` | `ia/projection.py:21` | Constante en dur | Nombre de trajectoires simulées |
| `SEED` | `7` | `project` | `ia/projection.py:22` | Constante en dur | Graine fixe : résultat reproductible |
| `MAX_AMOUNT` | `10 000 000` | `clean_contribution` | `ia/projection.py:23` | Constante en dur | Montant maximal accepté |
| Horizon et centiles | 10 ans ; 5, 25, 75, 95 | `project` | `ia/projection.py:39` ; docstring | Constantes en dur | Cônes probable (25-75) et large (5-95) |
| `FEES` | `{"ETF": 0.002}` | `to_portfolio` | `ia/monport.py:131` | Constante en dur | Frais 0.20 % par FNB, 0 pour un titre direct |
| `worstYear` | `μ − 2.33σ` | `to_portfolio` | `ia/monport.py:1055` | Constante en dur | VaR paramétrique 99 % à 1 an, loi normale. `WORST_YEAR_Z = 2.33` dupliqué (`ia/evidence.py:28`) |
| `var95`, `es95` annuels | `−(μ − 1.645σ)`, `−(μ − 2.063σ)` | `to_portfolio` | `ia/monport.py:1059-1060` | Constantes en dur | Quantile et ES normaux |
| `monthlyVolatility` | `σ/√12` | `to_portfolio` | `ia/monport.py:1054` | Constante en dur | |
| `MAX_CITED` | `3` | `evidence.cite` | `ia/evidence.py:29` | Constante en dur | Preuves citées par avertissement |
| Seuils de `diagnostics` | drawdown > perte acceptée ; 2σ > perte acceptée ; `effective_n` < 8 ; secteur > 35 % ; pays > 70 % ; crypto > 5 % ; horizon < 3 ans et volatilité > 15 % | `diagnostics.py` | `ia/diagnostics.py:14-33` | Constantes en dur | Génèrent les avertissements de risque (relu dans cette version) |

### Agents LLM et exécution (`ia/runtime.py:32-48`)

| Paramètre | Valeur | Source |
|---|---|---|
| `AWS_REGION` | `us-east-1` | variable d'env. |
| `MODEL_STRONG`, `MODEL_FAST` | `global.anthropic.claude-opus-5-5` | variable d'env. |
| `MODEL_PEPITE` | `global.anthropic.claude-sonnet-5-5` | variable d'env. |
| `MODEL_EFFORT` | `high` | variable d'env. |
| `MODEL_MAX_TOKENS` | `16000` | variable d'env. |
| `ENABLE_THINKING` | `True` | variable d'env. |
| `MAX_PM_RETRIES` | `1` | variable d'env. Les demandes de réoptimisation du juge sont ignorées (bloc « Plus de relance » de `judge_round`, `workers.py:294+`) : le Markowitz global est déterministe |
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
  - **Cohérent** : « Variante prudente », « Variante fidèle », « Variante audacieuse » (`VARIANT_NAMES`, `monport.py:63`). Un seul portefeuille est ensuite présenté : le gagnant (`pick_winner`, `:894`, « Ton portefeuille », `WINNER_NAME` `:64`).
  - **Incohérent** : « Ton profil », « Tes contraintes », « Tes préférences » (`BASE_NAMES`, `:54`). Le code présente deux mélanges 80/20 et « Tes contraintes » tel quel (`flow.present`, `workflow/flow.py:139-178`).

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
- Valeurs de A aux milieux de bande : S=0.1 → ≈ 18.7 ; S=0.3 → ≈ 9.9 ; S=0.5 → ≈ 4.95 ; S=0.7 → ≈ 2.29 ; S=0.9 → ≈ 1.22. (Calculs à la main à partir des ancres, **non exécutés**.)
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
| **Présentation du profil incohérent** | | | Deux mélanges `blend(prudent, conviction)` et `blend(conviction, prudent)` à 80/20 (`flow.py:153-158`), après `enforce_minimum` (voir 1.F). Seul « Tes contraintes » garde son verdict du juge ; les mélanges n'en ont pas (`flow.py:168`) |

Dans tous les cas : **μ et Σ sont identiques** pour les trois portefeuilles (`allocator.py:507-508`, `Market.universe_covariance`). Ni S ni A ne les modifient. Le cash est désactivé (`catalog.py:605-606`). **Les pénalités λ_D et λ_V de 1.B.2 sont identiques pour les trois** : elles ne dépendent pas du profil.

### 1.G.5 Plafond de volatilité : levier caché sur A

- `slot_volatility(check, slot)` = `round(_interpolate(S, VOL_ANCHORS), 3)` (même plafond pour les trois variantes d'un profil cohérent).
- `_under_cap` (`allocator.py:133-164`) monte A le long de `A_LADDER` (au-dessus du A courant), puis jusqu'à `A_MAX`, jusqu'à ce que la volatilité passe sous le plafond. Il affine ensuite par dichotomie (6 pas).
- Si même `A = 25` ne suffit pas, le résultat est rejeté par `evaluate` (statut `infeasible`).
- **Conséquence : le A effectif peut être supérieur au A du profil.** Les diagnostics exposent `A_requested`, `A_initial_optimization`, `A_effective` (`allocator.py:552`).

### 1.G.6 Relance avec limites assouplies et notes du juge (modifié)

1. Si `optimize_universe` échoue sur les contraintes dures, `optimize_with_relaxation` (`allocator.py:617`) relance en transformant des contraintes dures en préférences (`_soften`, `:598`). D'abord celles que le calcul a enfreintes, puis les familles de `RELAXATION_STEPS` (`:580`) : pourcentages visés, plafonds, exclusions. `MAX_POSITION_WEIGHT` n'est jamais assouplie.
2. Le portefeuille porte `relaunch_reason` et `relaxed` (`schemas.py:219-220`).
3. `workers._penalty` (`workers.py:271-273`) retourne `JUDGE_RELAUNCH_PENALTY` (3) **si le profil est cohérent et le portefeuille relancé**, sinon 0.
4. `JudgeVerdict.ranked_score = max(0, fit_score − penalty)` (`schemas.py:246-248`) sert au classement. `pick_winner` (`monport.py:894-910`) garde le choix du juge sauf si ce choix est pénalisé et qu'un autre portefeuille a un meilleur rang `(conforme, note pénalisée)`.
5. `to_portfolio` ajoute l'avertissement « Calcul relancé avec des limites assouplies » (`monport.py:1030+`). Pour le profil incohérent, aucune pénalité de note n'est appliquée.

### 1.G.7 Chaîne d'exécution complète

```
Profil (questionnaire)                       frontend → POST /api/invocations {mode:'monport', profile, constraints,...}
  │                                          (le front n'envoie PAS de score ni de A)
  ▼
S de base   = risk_position(profile)         ia/monport.py:340-359
  │   + 0.05 · adjust_steps (−2…+2, LLM)     ia/workflow/pepite.py:243 ; session.py:107-111
  ▼
assess(): S, A(S), label, vol. max, poids max par action        ia/monport.py:528-536
  ▼
Cohérence (Pépite, repli coherence_facts)    ia/workflow/pepite.py:250 ; ia/monport.py:424-443
  ▼
Pour chaque slot : S_slot, objectif, A_slot  slot_position (:545) ; objective_for (:642)
  ▼
Contraintes : build_profiles (:750) → follow_profile (:571) → plafond vol. (slot_volatility :552)
              → validate_profile (:666, LINE_CAP) → ensure_feasible (:711)
  ▼
Mandate(risk_aversion=A_slot, vol_cap_factor=None)   ia/workflow/workers.py:182-214 (l.191)
  ▼
optimize_with_relaxation → optimize_universe         ia/allocator.py:617 → :473
   catalog.settings_for → get_agent_settings → apply_portfolio_request (A écrit dans risk_aversion.default ;
                                                REGULARIZATION copiée dans les réglages, config.py:652)
   A0 (:510) → _continuous (:302) → select_holdings (:347) → réoptimisation (:528-534)
   → max_sharpe : _best_sharpe (:115)  |  plafond vol. : _under_cap (:133)
  ▼
Objectif : max  U = μᵀw − (A/2)·wᵀΣw − λ_D·Σw² − λ_V·Σq·w²   (SLSQP)     ia/optimizer.py:424-455
  ▼
Poids : _weights (:167) → portfolio_metrics (market.py:394, sans pénalité) → evaluate + audit
  ▼
Relance assouplie si échec (allocator.py:617) → juge (workers.py:294) avec pénalité (workers.py:271)
  ▼
pick_winner (monport.py:894)  |  blend 0.8 + enforce_minimum (monport.py:817, :856)
  ▼
to_portfolio (monport.py:996) → SSE 'portfolios' (flow.py:139-178) → front
```

### 1.G.8 Ce que le profil modifie ou non

| Élément | Modifié par le profil / S / A ? |
|---|---|
| A | **Oui** (S → A, décalage par slot, relèvement par le plafond de volatilité) |
| Plafond de volatilité | **Oui** (`VOL_ANCHORS(S)`) |
| Plancher d'obligations, interdiction crypto, plafond par action | **Oui** (par label, via `follow_profile`) |
| Cash | **Non** (désactivé en production) |
| Pénalités λ_D, λ_V et seuil de volatilité | **Non** (globales, identiques pour les trois variantes) |
| Sélection d'actifs | **Oui indirectement** (exclusions du client, contraintes, `select_holdings` au A du slot) |
| μ (rendements espérés) | **Non** |
| Σ (covariance) | **Non** (mais les pénalités agissent comme un terme diagonal ajouté à Σ dans l'objectif) |
| Univers | **Non** (même univers filtré par historique et exclusions du client) |

### 1.G.9 Code actif et code legacy dans cette chaîne

- **Actif** : `monport.py` (S, A, ancres, `build_profiles`, `follow_profile`, `blend`, `enforce_minimum`), `workflow/*`, `allocator.optimize_universe` et ses aides, `catalog.settings_for`.
- **Legacy** : `MANDATES` (`mandates.py:26-61`), `BOND_SHIFT`, `allocator.optimize` (hors `_raise_volatility_cap`), `BASE_PROFILE` (A = 5.0, `config.py:583-586`).
- **Moteur hors ligne du front** (`frontend/src/lib/engine.ts`) : reproduit S, A, limites et `SLOT_SHIFT`. Voir la partie 2.

---

# Partie 2 — Audit des calculs du front-end

Chemins relatifs à `frontend/src/`. Backend : `backend/src/invest_agents/` (**`ia/`**). Le front ne contient **aucune référence** aux pénalités de régularisation (recherche de « regulariz » dans `frontend/src` : aucun résultat).

## 2.0 Verdict

**Oui, il reste des calculs financiers et des règles métier dans le front-end.** Ils sont de deux natures :

1. **Un moteur d'exemple complet** (`lib/engine.ts` et `data/catalog.ts`) qui construit des portefeuilles, des métriques et des preuves sans backend. Il est actif lorsque le backend est injoignable ou qu'aucun portefeuille n'est reçu.
2. **Une réplique des règles de profil** (score de risque S, A, limites, cohérence), utilisée **en usage normal** pendant le questionnaire, avant et pendant l'appel au backend.

**Avec un backend qui répond**, les portefeuilles, métriques, backtest, projection, montants, répartitions et facteurs viennent du backend sans transformation économique (`setPortfolios`, `store.ts:164-170`). Le front ne ré-optimise pas ces résultats, **sauf dans un cas** : `withAdjustments` (voir 2.5, constat F1).

## 2.1 Flux de données vérifié

```
Saisie (Profile.tsx, Preferences.tsx, inputs.tsx)
   │  état zustand `useApp`, persisté en sessionStorage (clé `bas-de-laine`)      store.ts
   │  calculs locaux : riskScore, riskLabel, riskBreakdown, profileLimits,
   │                   coherenceWarnings (affichage + avertissements en direct)    lib/engine.ts
   ▼
POST  PIPELINE_URL = VITE_API_URL || '/api/invocations'  (SSE, en-tête X-Session-Id)   api.ts:12, :73
   │  monport_check    {mode, profile, constraints}              (le `score` n'est PAS envoyé : api.ts:129)
   │  monport          {mode, profile, constraints, contribution, check, adjustment, session}   api.ts:162-165
   │  monport_chat     {mode, session, message}                  api.ts:174-175
   │  monport_rebuild  {mode, session}                           api.ts:185-188
   ▼
Backend : flow.py → Pépite → monport.py → allocator.py → optimizer.py (utilité pénalisée) → to_portfolio
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
| `expectedReturn` | `pages/dashboard/Views.tsx:127`, `Dashboard.tsx` | `m.expected_return` via `to_portfolio` (`monport.py:1051+`), calculé **sans** pénalité de régularisation | Aucune (format) |
| `volatility` | `Views.tsx:134` | `m.volatility`, idem | Aucune |
| `sharpe` | `Views.tsx:130` | `m.sharpe` = `(μ−rf)/σ` (`market.py:~416`) | `toFixed(2)` et virgule |
| `worstYear` | `Views.tsx:57`, `:147` | `μ − 2.33σ` (`monport.py:1055`) | Aucune |
| `var95` / `es95` annuels | champs de `Metrics` (`types.ts`) | `monport.py:1059-1060` | Non affichés dans les vues lues |
| VaR / ES 1 jour | `Views.tsx:149`, `:237-238` | `backtest.stats.var95/es95` (perte positive : `backtest.py:107`) | `signedPct(−var95)` : inversion de signe pour afficher une perte négative. **Cohérent** avec le backend (vérifié) |
| `maxDrawdown` | `Views.tsx:139` | `s?.maxDrawdown ?? m.maxDrawdown` : backtest en priorité, sinon optimiseur | Choix de source côté front (voir F8) |
| Projection | `ProjectionChart`, `Views.tsx:155-200` | `p.projection` (`projection.py`) | `wide: [p05, p95]`, `likely: [p25, p75]` (mise en forme) |
| Backtest | `PerformanceTab`, `Views.tsx:~270-300` | `p.backtest.runs[freq]` | Aucune |
| Montants | `Views.tsx:52-55`, `:61-64` ; `parts.tsx:107` | `p.amounts`, `holdings[].amount` | Aucune |
| Contribution au risque | `Views.tsx:376-421` (`RiskTab`, onglet « Risque » du niveau Avancé) | `p.riskContribution` : `risk_by_class` (`monport.py:1095`), basé sur la même Σ que l'optimiseur | Aucune. Largeurs de barres `pct(poids)` et `pct(risque)` seulement |

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
| E13 | **Métriques (mock)** | `metricsOf` | `:255-276` | `μ = Σ a_k·mu_k` ; `σ² = ΣΣ a_i a_j σ_i σ_j ρ`, **ρ = 0.3** si i≠j (l.261) ; `worstYear = μ − 2.33σ` ; **`sharpe = (μ − 0.025)/σ`** (l.271) ; **`maxDrawdown = −min(0.9, 2.2σ)`** (l.272) ; `var95 = −(μ − 1.645σ)` ; `es95 = −(μ − 2.063σ)` | Hypothèses de classe | `Metrics` | `portfolio_metrics` (`market.py:394`) et `to_portfolio` | [F] | **Isoler ou masquer en production.** `rf = 0.025` contre `0.035` au backend ; `maxDrawdown` est un proxy sans historique ; ρ = 0.3 est un coefficient inventé. **Ces métriques ne contiennent pas les pénalités de régularisation** |
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
| S5 | Véhicules | `setVehicles` | `store.ts:134-150` | Hors FNB : seules `shownClasses` sont gardées ; pourcentages retirés quand `vehicles === 'fnb'` | `shown_classes` (`monport.py:234`) | [M] | Garder, vérifier la parité |
| S6 | Valeurs par défaut du profil | `DEFAULT_PROFILE` | `store.ts:7-14` | âge 35, montant 10 000, objectif `fructifier`, horizon 12, `lossReaction 2`, `comfort 3` | `capacity`/`tolerance` défauts : horizon 10, âge 35 | [M] | **Écart** : horizon par défaut 12 (front) contre 10 (backend), pertinent si un champ manque |

### 2.3.3 `api.ts`

| # | Calcul | Fonction | Lignes | Logique | Classe | Recommandation |
|---|---|---|---|---|---|---|
| A1 | Contrôle de repli | `exampleCheck` | `:108-115` | Cohérent si `coherenceWarnings(score, c).length === 0` | [M] | Fallback |
| A2 | Script d'événements fictif | `runScript` | `:194-236` | `after = UNIVERSE.length*7 − excluded*9 − classesOut*6` ; `before = UNIVERSE.length*7` ; messages « Toutes tes limites sont respectées. » et « Rien de particulier à signaler. » écrits en dur. Dernière modification : l'ordre des étapes suit désormais le backend (gestionnaires, agents Risque, juge) | [U] | **Chiffres inventés** : afficher « exemple » ou retirer |
| A3 | Règles de chat | `RULES`, `proposeAdjustment` | `:252-299` | Regex : tech → `themes.tech 30` ; pétrole/fossile → exclusion ; crypto/bitcoin → `classes.crypto 10` (avertit si `score < 50`) ; prudent/moins de risque → exclut la crypto et `riskShift −15` ; `changes` = diff avant/après filtré à `\|Δ\| ≥ 0.001` | [M]/[F] | Fallback. Aucun équivalent backend codé (LLM) |

### 2.3.4 `data/catalog.ts` (hypothèses en dur)

| # | Élément | Lignes | Contenu | Classe | Recommandation |
|---|---|---|---|---|---|
| C1 | `CLASS_ASSUMPTIONS` | `:263` | μ/σ en dur : actions 7 % / 16 %, obligations 3,5 % / 6 %, immobilier 5,5 % / 18 %, or 4 % / 15 %, crypto 15 % / 70 %, liquidités 2,5 % / 1 % | [F] (mock) | Isoler en démo |
| C2 | `UNIVERSE` | `:230-260` | 26 lignes fictives (« exemple »), frais en %, scores de facteurs en dur | [F]/[M] (mock) | Isoler en démo |
| C3 | `FACTOR_TARGETS` | `:160` | `{2: .5, 1: .2, −1: −.2, −2: −.5}` | [M] | **Dupliqué** (`monport.py:113`) : test de parité |
| C4 | `shareTotal`, `sharesValid` | `:163-172` | `total = round(Σ·10)/10` ; valide si `total ≤ 100 && (free>0 \|\| entered===0 \|\| total===100)` | [M] | Validation UI. Le backend revalide (`validate_profile`, `monport.py:666`) |
| C5 | `shownClasses` | `:46-48` | `titres → ['actions','crypto']`, sinon 5 classes | [M] | Parité avec `shown_classes` (`monport.py:234`) |
| C6 | `PERIODS_PER_YEAR` | `:300` | `{deux-semaines 26, mensuelle 12, annuelle 1, aucune 12}` | [F] | **Probablement inutilisé** : la vue lit `proj.periodsPerYear` du backend (`Views.tsx:~198`). Non vérifié par recherche exhaustive |
| C7 | `THEME_PRESETS` | `:185-216` | Modèles de thématiques en dur (ex. tech 35 %, IA 25 %) | [M] | Garder (UI) |

### 2.3.5 Pages et composants

| # | Calcul | Fichier : lignes | Logique | Classe | Recommandation |
|---|---|---|---|---|---|
| P1 | Utilité marginale du risque | `pages/RiskNotebook.tsx:269` | `extra = (A/2)·(0.15² − 0.10²)·100` (rendement demandé pour passer de 10 % à 15 % de volatilité) | [F] (pédagogique) | Garder si libellé « illustration ». Cette formule suppose l'utilité **sans** pénalité de régularisation ; si λ_D ou λ_V deviennent non nuls, l'explication ne les inclut pas |
| P2 | Échelle log de A | `RiskNotebook.tsx:270` | `pos = log(25/v)/log(25)·100` | [U] | Garder |
| P3 | Tolérance de bande | `RiskNotebook.tsx:317` | `TOLERANCE = 2` points, « comme `SHARE_TOLERANCE` de `monport.py` » (définition backend non relue) | [M] | Parité à tester |
| P4 | Plancher d'obligations affiché | `RiskNotebook.tsx:342-343` | `room = 1 − Σ_classes fixées max(0, v − TOLERANCE)/100` ; `bondFloor = max(0, min(lim.bondFloor, room))` | [F]/[M] | **Approximation locale** de `follow_profile` (`monport.py:571`) : le backend fait foi |
| P5 | Poids de la capacité / tolérance | `RiskNotebook.tsx:125-126`, `:139-141` | `0.6/0.4` et `0.5/0.3/0.2` recopiés à la main | [F] | **Triple duplication** (`engine.ts:55-56`, `monport.py:344,352`) |
| P6 | Score recalculé en ligne | `RiskNotebook.tsx:253`, `:291` | `riskLabel(Math.round(5 + 90·s))` au lieu de `riskScore` | [F]/[U] | Dédupliquer |
| P7 | Seuil d'explication | `RiskNotebook.tsx:108` | `b.capacity > b.tolerance + 0.15` | [U] | Garder (texte) |
| P8 | Bandes de facteurs | `pages/dashboard/Factors.tsx` | `RANGE = 1.5`, `NEUTRAL = 0.1` ; intensité `<0.1 Neutre`, `<0.3 Légère`, `<0.6 Nette`, sinon `Forte` ; jauge `(clamp(v, −1.5, 1.5) + 1.5)/3·100` ; `strong = \|v\| > 0.18` | [U] | Garder. Le test « cible atteinte » (`met`) n'a pas été lu (non vérifié) |
| P9 | Contribution au risque | `Views.tsx:376-421` (voir 2.6, ligne « Contribution au risque ») | Le front affiche `p.riskContribution` (poids et risque par classe) et une infobulle explicative. Le calcul est côté backend : `risk_by_class` (`monport.py:1095`) s'appuie sur `risk_contribution` (`backtest.py:141`). **Ne pas confondre** avec `allocator._risk_contributions` (l.445), qui ne sert qu'aux diagnostics | [U] | Garder |
| P10 | Barres, largeurs | `charts.tsx:75`, `parts.tsx:25`, `Evidence.tsx:25-34` | `poids·100 %`, `scale = max(v, l)·1.15`, `over` | [U] | Garder |
| P11 | Pré-remplissage de pourcentage | `inputs.tsx:208` | `max(0, round((100 − total)/max(1, free)))` | [U]/[M] | Garder |
| P12 | Contenu LLM comme barre | `RichText.tsx:152-158` | `clamp(parseFloat(pct), 0, 100)` | [U] | Chiffre venant du texte écrit par l'agent, non recalculé (non vérifié côté backend) |
| P13 | Libellé « Pire recul (backtest) » | `Views.tsx:139` | `s?.maxDrawdown ?? m.maxDrawdown` | [U] | **Libellé trompeur** quand la valeur vient de `m.maxDrawdown` (proxy du mode démo) |
| P14 | Description des étapes du pipeline | `pages/Pipeline.tsx` (`stepsFor`) | Texte : « Une variante recalculée avec des limites assouplies perd des points » ; titre d'alerte « Limites assouplies » | [U] | Aligné sur `JUDGE_RELAUNCH_PENALTY` (backend). Le nombre de points (3) n'est pas affiché |

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
7. **Les métriques correspondent-elles exactement au backend ?** En mode backend, oui (aucun recalcul). En mode démo, non : les chiffres viennent de `metricsOf`. **Les pénalités de régularisation ne sont pas visibles à l'écran** : elles modifient les poids, pas les indicateurs affichés.

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
| **F10** | L'explication pédagogique de l'utilité (`extra`) ignore les pénalités de régularisation (aujourd'hui nulles) | `RiskNotebook.tsx:269` | Faible (à surveiller si λ ≠ 0) |

## 2.6 Où chaque concept s'affiche dans le front-end

Cette section répond, concept par concept, à la question « où est-ce visualisé dans l'interface ? ». Les lignes ont été relevées par `grep -n` sur `frontend/src` (commit `9729f50`).

**Structure des écrans du tableau de bord.** `Dashboard.tsx:39` choisit la vue selon le niveau de l'utilisateur : `Beginner` (`Views.tsx:32`), `Intermediate` (`Views.tsx:249`) ou `Advanced` (`Views.tsx:434`). `Advanced` contient deux onglets, « Performance » (`PerformanceTab`, `Views.tsx:277`) et « Risque » (`RiskTab`, `Views.tsx:376`). Les mises en garde du responsable des risques (`RiskNotes`) sont montées à `Dashboard.tsx:101`, dans une colonne latérale visible dans les trois niveaux.

**Légende de la colonne « Calcul »** : *Backend* = le front ne fait que lire et afficher la valeur reçue. *Front* = la valeur est calculée dans le navigateur.

### Indicateurs du portefeuille

| Concept | Écran (niveau) | Composant : lignes | Donnée lue | Calcul |
|---|---|---|---|---|
| **Rendement attendu** (μ du portefeuille) | Débutant : « Une année normale » | `Views.tsx:50-51` ; montant en dollars `:52-55` | `p.metrics.expectedReturn`, `p.amounts.expectedGain` | Backend |
| | Intermédiaire et Avancé : carte « Rendement attendu » | `KpiRow`, `Views.tsx:128-134` (monté l.252 et l.438) | `m.expectedReturn` | Backend |
| | Sélecteur de portefeuille (haut de page) | `Dashboard.tsx:80` | `q.metrics.expectedReturn` | Backend |
| | Note sous la projection | `Views.tsx:200` | `p.metrics.expectedReturn` | Backend |
| **Volatilité** | Intermédiaire et Avancé : carte « Volatilité » | `KpiRow`, `Views.tsx:135-147` | `m.volatility` | Backend |
| Volatilité mensuelle | Avancé seulement | `Views.tsx:142` | `m.monthlyVolatility` (σ/√12, `monport.py:1054`) | Backend |
| **Sharpe** (portefeuille) | Avancé : sous « Rendement attendu » | `Views.tsx:132` | `m.sharpe` | Backend |
| | Avancé, onglet Performance : tableau « Statistiques » | `Views.tsx:297` | `s.sharpe` (Sharpe réalisé du backtest) | Backend |
| **Pire année** (μ − 2,33σ) | Débutant : « Une mauvaise année » ; en dollars | `Views.tsx:59-64` | `p.metrics.worstYear`, `a.worstYearValue`, `a.worstYearLoss` | Backend |
| | Intermédiaire et Avancé : carte « Pire année (estimation) » | `Views.tsx:148-153` | `m.worstYear` | Backend |
| **VaR et ES 95 % (1 jour)** | Avancé : sous « Pire année » | `Views.tsx:151` | `s.var95`, `s.es95` (backtest) | Backend, signe inversé à l'affichage |
| | Intermédiaire, Avancé : texte sous le graphique de distribution | `DistributionChart`, `Views.tsx:239-240` ; monté l.261 et l.387 | `r.run.stats.var95`, `.es95` | Backend, signe inversé à l'affichage |
| **Pire recul** (max drawdown) | Avancé : sous « Volatilité » ; tableau « Statistiques » | `Views.tsx:141` ; `:298` | `s?.maxDrawdown ?? m.maxDrawdown` | Backend. Libellé « backtest » trompeur si repli (F8) |
| Nombre de placements | Avancé : sous « Rendement attendu » | `Views.tsx:132` | `p.holdings.length` | Front (comptage) |

### Analyses historiques et projections

| Concept | Écran (niveau) | Composant : lignes | Donnée lue | Calcul |
|---|---|---|---|---|
| **Backtest** (courbe, drawdown, statistiques, pire et meilleure période de 12 mois, fréquence de rééquilibrage) | Avancé, onglet « Performance » | `PerformanceTab`, `Views.tsx:277-375` ; sélecteur de fréquence `:311-314` | `p.backtest.runs[fréquence]` | Backend (`backtest.py`) |
| **Projection sur 10 ans** (cônes 5-95 et 25-75) | **Intermédiaire seulement** (pas dans Avancé) | `ProjectionChart`, `Views.tsx:157-203` ; monté l.260 | `p.projection.rows` | Backend (`projection.py`). Le front assemble `wide` et `likely` pour le graphique |
| **Distribution des rendements quotidiens** | Intermédiaire ; Avancé, onglet « Risque » | `DistributionChart`, `Views.tsx:206-246` ; monté l.261 et l.387 | `r.run.distribution` | Backend |
| **Contribution au risque** | **Avancé, onglet « Risque »** | `RiskTab`, `Views.tsx:376` : lit `p.riskContribution` (l.377) ; titre « Contribution au risque » (l.391) ; infobulle « Comment c'est calculé ? » (l.392-396) ; liste « poids vs risque » par classe (l.400-417) ; repli `NeedsBackend` (l.~418) | `p.riskContribution` (`{assetClass, weight, risk}[]`) | Backend (`risk_by_class`, `monport.py:1095`, contributions d'Euler sommées par classe). Le front ne fait que l'afficher |

### Composition du portefeuille

| Concept | Écran (niveau) | Composant : lignes | Donnée lue | Calcul |
|---|---|---|---|---|
| **Allocation par classe d'actifs** (barre et légende) | Débutant | `AllocationBar`, `parts.tsx:20` (monté `Views.tsx:39`) ; `Legend`, `parts.tsx:33` | `p.allocation` | Backend |
| Allocation par classe (liste des familles) | Débutant : « Ce que tu achètes » | `Views.tsx:92-100` | `p.allocation[k]` | Backend |
| **Répartition par classe, région, secteur** | Débutant (région, secteur) ; Intermédiaire ; Avancé, onglet « Risque » | `Breakdown`, `charts.tsx:99-102` ; monté `Views.tsx:87`, `:255`, `:382` | `p.breakdown` | Backend (`breakdowns`, `monport.py:1079`) |
| **Positions : code, placement, type et secteur, classe, poids, montant** | Intermédiaire ; Avancé, onglet « Risque » (colonne « Classe » en plus) | `HoldingsTable`, `parts.tsx:70-115` (colonnes l.86-91 ; poids l.106 ; montant l.107) ; monté `Views.tsx:265`, `:424` | `p.holdings` | Backend |
| **Exposition aux facteurs** | Avancé, onglet « Risque » | `FactorExposure`, `Factors.tsx:214` (titre « Exposition aux facteurs » l.220 ; cartes l.247) ; monté `Views.tsx:385` | `p.factors` | Backend (`factor_view`). Seuils d'intensité et jauge calculés côté front (P8, mise en forme) |

### Risque, avertissements et agents

| Concept | Écran (niveau) | Composant : lignes | Donnée lue | Calcul |
|---|---|---|---|---|
| **Mises en garde et preuves du responsable des risques** | Tous les niveaux, colonne latérale | `RiskNotes`, `RiskNotes.tsx:9` ; `Note`, `:43` ; `EvidenceCard`, `Evidence.tsx:5` ; monté `Dashboard.tsx:101` | `p.warnings`, `sources` | Backend. **Exception :** en démo, `evidenceOf` calcule les preuves dans le navigateur (`RiskNotes.tsx:13`, `engine.ts:281`) |
| **Notes des agents** | Intermédiaire : « Notes des agents » ; Avancé : « Journal des agents » | `AgentNotes`, `parts.tsx:117` ; `Views.tsx:268-269`, `:427-428` | `p.agentNotes` | Backend |
| **Relance avec limites assouplies** | Écran de construction (Pipeline) ; colonne `RiskNotes` | Alerte « Limites assouplies » `Pipeline.tsx:223` ; texte « …perd des points » `Pipeline.tsx:49` ; l'avertissement « Calcul relancé avec des limites assouplies » arrive dans `p.warnings` (`monport.py:1030`) | événement `warning`, `p.warnings` | Backend. Le nombre de points (3, `JUDGE_RELAUNCH_PENALTY`) n'est **pas** affiché |
| **Discussion et ajustements avec Pépite** | Volet latéral | `AdjustPanel.tsx:40` | messages SSE ; en démo, `proposeAdjustment` (`api.ts:285`) | Backend, ou **front** en démo (F1) |

### Profil, risque et aversion A (écrans de questionnaire)

| Concept | Écran | Composant : lignes | Donnée lue | Calcul |
|---|---|---|---|---|
| **Étiquette de risque du profil** (« Ton profil est … ») | Transition | `Transition.tsx:31` | `riskLabel(riskScore(profile))` | **Front** (`engine.ts:110-116`) |
| | Construction (Pipeline) | `Pipeline.tsx:169` | `riskLabel(score)`, `score = riskScore(profile)` (l.81) | **Front** |
| **Score S et niveau** | Vérification, « carnet » de Pépite | `RiskNotebook.tsx:253` | `check.risk_position ?? b.s` (l.32) | Backend si fourni, sinon **front** (`riskBreakdown`) |
| **Aversion au risque A** | Vérification : « A = … » | `RiskNotebook.tsx:290` ; curseur d'essai `:267`, `:307` | `check.risk_aversion ?? riskAversion(s)` (l.33) | Backend si fourni, sinon **front** (`engine.ts:72`) |
| A par gestionnaire (variantes) | Vérification | `RiskNotebook.tsx:467` | `riskAversion(slotPosition(…))` | **Front** |
| Utilité marginale « passer de 10 % à 15 % de risque » | Vérification | `RiskNotebook.tsx:269-270` | `(A/2)·(0,15² − 0,10²)·100` | **Front** (illustration) |
| **Garde-fous du profil** (plancher d'obligations, crypto, plafond par ligne, par action, volatilité max, minimum 1 %) | Vérification | `RiskNotebook.tsx:411-418` (`Guard`) | `profileLimits(s)` (l.337), `bondFloor` (l.343) | **Front** (`engine.ts:92`) |
| **Avertissements de cohérence** (profil contre préférences) | Page des préférences, classes d'actifs | `Preferences.tsx:61` | `coherenceWarnings(riskScore(profile), c)` | **Front** (`engine.ts:306`) |

### Paramètres et calculs **sans aucun affichage** dans l'interface

| Élément | Constat |
|---|---|
| Pénalités de régularisation λ_D, λ_V et seuil de volatilité | Aucune référence dans `frontend/src`. Elles modifient les poids, jamais un chiffre affiché |
| Frais (`metrics.fees`) | Aucun composant ne lit `.fees` hors du moteur d'exemple (`engine.ts:265`) |
| μ et σ individuels par titre, β, covariance Σ, intensité Ledoit-Wolf, `periods_per_year_effective` | Non affichés. `HoldingsTable` ne montre que code, nom, type, classe, poids et montant (`parts.tsx:86-91`) |
| `effective_n`, indice de concentration (`hhi`), `A_effective`, utilité pénalisée | Non affichés |
| Taux sans risque (`RF_ANNUAL`) | Utilisé dans le Sharpe, jamais montré |
| Points de pénalité du juge (`JUDGE_RELAUNCH_PENALTY`) | Non affichés (texte qualitatif seulement) |

**Lecture rapide.** Tous les indicateurs financiers du tableau de bord (rendement, volatilité, Sharpe, VaR, ES, drawdown, backtest, projection, contribution au risque, répartitions, positions, facteurs) sont lus du backend sans recalcul. Les seuls calculs réellement faits dans le navigateur en usage normal se trouvent dans les écrans de questionnaire : étiquette de risque, score S (secours), A (secours), garde-fous du profil, avertissements de cohérence et utilité marginale illustrée.

---

# Partie 3 — Synthèse consolidée

## 3.A Inventaire maître des paramètres

> Pour savoir **où chaque indicateur est affiché** dans l'interface (composant et lignes), voir [2.6](#26-où-chaque-concept-saffiche-dans-le-front-end).

Les lignes sont vérifiées par `grep -n` sur le commit `9729f50`, sauf mention `~`. « Config » = clé de `config.py` modifiable en éditant ce fichier. « Constante » = littéral dans le code. « Env » = variable d'environnement. « Estimé » = calculé sur les données, non choisi.

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
| β | estimé | `market.py:66-77` | Estimé |
| `capm_benchmark_shrinkage.*` | inactif | `config.py:137-148` | Config (aucune classe ne l'utilise) |
| `DATA.periods_per_year` | 252 | `config.py:40` | Config |

### Covariance et pénalités liées à Σ (B)

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
| Tolérance PSD optimiseur | `−1e-8` | `optimizer.py:519` | Constante |
| **`REGULARIZATION.diversification_penalty` (λ_D)** | **0.0** | **`config.py:406`** | **Config, hors du contrat agent** |
| **`REGULARIZATION.high_volatility_penalty` (λ_V)** | **0.0** | **`config.py:407`** | **Config, hors du contrat agent** |
| **`REGULARIZATION.volatility_threshold`** | **0.25** | **`config.py:408`** | **Config** |
| `qᵢ = max(0, Σᵢᵢ − seuil²)` | calculé | `optimizer.py:398-401` | Dérivé de Σ |

### Aversion au risque et profils (C)

| Paramètre | Valeur | Fichier : ligne | Configurabilité |
|---|---|---|---|
| `RISK_AVERSION.min/max/default` | 1.0 / 25.0 / 5.0 | `config.py:310-312` | Config (doublon `allocator.py:45`, `schemas.py:318`) |
| `PepiteCheck.risk_aversion` défaut | 7.0 | `schemas.py:318` | Constante |
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
| `JUDGE_RELAUNCH_PENALTY` | 3 | `config.py:288` ; `workers.py:271-273` | Config |

### Optimisation (E)

| Paramètre | Valeur | Fichier : ligne | Configurabilité |
|---|---|---|---|
| Objectif | `U = μᵀw − (A/2)wᵀΣw − λ_D·Σw² − λ_V·Σq·w²` | `optimizer.py:437-442` ; `allocator.py:339-344` | Constante (λ en config) |
| `CONSTRAINTS.max_weight_per_asset` | `None` (production) | `config.py:340` | Config |
| `BASE_CONSTRAINTS.max_weight_per_asset` | 0.10 (inactif) | `config.py:491` | Config |
| `min_held_weight` | 0.01 | `config.py:334`, `:280`, `:481` ; `allocator.py:44` | Config ×3 + constante |
| `PORTFOLIO_HOLDINGS` | 25 / 70 / 0.01 / 0.0001 | `config.py:278-283` | Config |
| `MAX_ASSETS_PER_PORTFOLIO` | 40 | `runtime.py:49` | Env |
| `A_LADDER` | 10 valeurs de 1.0 à 25.0 | `allocator.py:47` | Constante |
| `CAP_REFINEMENTS` | 6 | `allocator.py:48` | Constante |
| Lots de sélection | 10 (minimum), 5 (diversification) | `allocator.py:391`, `:426` | Constante |
| `CASH` | rendement 0.01, volatilité 0.0, **désactivé en production** | `config.py:394-395` ; `catalog.py:605-606` | Config / Constante |
| `OPTIMIZATION.solver_options` | `maxiter 2000`, `ftol 1e-9` | `config.py:417-418` | Config |
| `constraint_tolerance`, `sum_weights_tolerance` | `1e-7`, `1e-7` | `config.py:421-422` | Config |
| `minimum_holding_tolerance` | `1e-8` | `config.py:337` | Config |
| Tolérances `catalog` | `TOL 1e-3`, `WTOL 2e-4`, `HELD 5e-4`, `EXACT_TOL 1e-3`, `FTOL 0.01`, `FACTOR_SLEEVE_MIN 0.10`, `FACTOR_MARGIN 0.01` | `catalog.py:67-69`, `:154-158` | Constante |
| `FACTOR_LEVELS` | ±0.2 / ±0.5 | `monport.py:113` ; `catalog.ts:160` | Constante ×2 |
| `RELAXATION_STEPS` | 3 familles | `allocator.py:580-596` | Constante |

### Autres (F)

| Paramètre | Valeur | Fichier : ligne | Configurabilité |
|---|---|---|---|
| `LOOKBACK_YEARS`, `YEAR`, `BIWEEKLY`, `SAMPLE_EVERY`, `DAILY_STEP`, `DAILY_LIMIT` | 6, 252, 10, 5, 0.5, 5.0 | `backtest.py:26-31` | Constante |
| `PATHS`, `SEED`, `MAX_AMOUNT`, `PER_YEAR` | 1000, 7, 10 000 000, 26/12/1/12 | `projection.py:20-23` | Constante |
| `FEES` | `{"ETF": 0.002}` | `monport.py:131` | Constante |
| VaR/ES normaux | 2.33, 1.645, 2.063 | `monport.py:1055-1060` ; `evidence.py:28` ; `engine.ts:269-274` | Constante ×3 |
| `MAX_CITED` | 3 | `evidence.py:29` | Constante |
| Modèles et jetons LLM | voir 1.F | `runtime.py:32-48` | Env |

## 3.B Matrice de responsabilités front vs backend

| Calcul ou règle | Propriétaire actuel | Doublon dans l'autre couche | Cohérence | Manque ou écart |
|---|---|---|---|---|
| μ, Σ, estimation | Backend (`market.py`) | Non | n/a | Annualisation de Σ ≠ μ (voir 1.B) |
| **Pénalités λ_D, λ_V** | Backend (`optimizer.py`, `allocator.py`, `config.py`) | Non | n/a | Hors contrat agent et hors front ; valeurs à 0.0, non calibrées |
| Optimisation de portefeuille | Backend (`allocator.py`, `optimizer.py`) | **Oui, en démo** : `classWeights`, `lineWeights` | Heuristique différente | Fallback à isoler |
| Mélange 80/20 | Backend (`blend`, `enforce_minimum`) | Non (le front affiche seulement) | n/a | Non réoptimisé : les pénalités n'y agissent pas |
| Métriques (μ, σ, Sharpe, drawdown) | Backend (`portfolio_metrics`) | **Oui, en démo** : `metricsOf` (`rf 0.025`, `ρ 0.3`) | Diverge | Marquer « exemple ». Les métriques backend ignorent les pénalités |
| VaR / ES / pire année | Backend (`to_portfolio`) | Oui : `metricsOf` | Mêmes constantes (2.33, 1.645, 2.063) | OK, mais triple définition (`evidence.py`, `monport.py`, `engine.ts`) |
| Backtest, projection, montants | Backend | Non | n/a | Vides en démo (`NeedsBackend`) |
| Score de risque S | Backend (avec crans) | **Oui** : `riskBreakdown` | Identique sans crans | Le front ignore les crans |
| Aversion A | Backend (`risk_aversion`) | **Oui** : `riskAversion` | Identique, arrondi différent | `RiskNotebook` préfère le backend |
| Limites du profil (vol., plafond action, plancher d'obligations, crypto) | Backend (`monport.py`) | **Oui** : `profileLimits` | Mêmes valeurs | `choices_breakdown` existe mais n'est pas branché |
| `SLOT_SHIFT` | Backend | **Oui** : `slotPosition` | Identique | |
| Cohérence profil/préférences | Backend (Pépite, `coherence_facts`) | **Oui** : `coherenceWarnings` | Mêmes seuils, score différent | Actif en usage normal |
| Ajustements de risque | Backend (crans LLM) | **Oui** : `riskShift`, `RULES` | Échelles différentes | `withAdjustments` écrase le résultat backend |
| Pénalité de relance du juge | Backend (`workers._penalty`) | Non (texte seulement dans `Pipeline.tsx`) | n/a | Le « 3 » n'est pas exposé au front |
| Validation de parts et contraintes | Backend (`validate_profile`, `evaluate`) | Oui : `sharesValid`, `shareTotal` | Probable | Validation UI de confort |
| Taux sans risque | Backend (`RF_ANNUAL = 0.035`) | Oui : `0.025` dans `metricsOf` | **Diverge** | Démo seulement |
| Frais | Backend (`FEES 0.002`) | Oui : `fee ?? 0.2` | Équivalent (0.2 %) | |

## 3.C Constats prioritaires

Classés par importance architecturale, puis par impact sur les portefeuilles.

### Priorité 1 — Impact direct sur les résultats

1. **Annualisation de Σ ≠ annualisation de μ.** `periods_per_year_effective` (`n / (jours/365.25)`, `market.py:250-257`, `:312`) annualise Σ ; μ et `ann_vol` utilisent 252. La volatilité des portefeuilles et les `ann_vol` d'écran ne reposent donc pas sur la même base. **Nouveau :** le seuil de volatilité des pénalités (25 %) compare `√Σᵢᵢ`, donc la même base que Σ, si bien que cette incohérence déplace aussi l'ensemble des titres pénalisés. À mesurer sur le Parquet avant le Datathon (`python -m invest_agents.market` affiche `periods_per_year_effective`).
2. **Pénalités λ_D et λ_V : nulles et non calibrées.** À 0.0, rien ne change. Dès qu'on les augmente, elles agissent comme un terme diagonal `(2λ_D/A)·I + (2λ_V/A)·diag(q)` ajouté à Σ, identique pour les trois variantes, et **s'ajoutent à A sans apparaître dans `A_effective`**. Elles n'entrent pas dans les métriques affichées. Elles ne sont pas pilotables par le questionnaire. Calibrer (a) l'échelle de λ par rapport à A (1 à 25) et à des variances annuelles de 0.01 à 0.16, (b) le seuil de 25 %, (c) le lien éventuel avec le profil.
3. **A effectif ≠ A du profil.** Le plafond de volatilité relève A jusqu'à 25 (`allocator._under_cap`, `:133-164`). Le A affiché (`risk_aversion(S)`) peut donc différer du A réellement optimisé (`A_effective`). Les trois variantes d'un profil cohérent partagent le même plafond (seul A les distingue), si bien que ce relèvement peut faire converger leurs A effectifs.
4. **Pas de plafond par actif en production** (`max_weight_per_asset = None`, `config.py:340`, contre `0.10` dans BASE, inactif). Le seul plafond est `LINE_CAP = 0.40` et `MAX_STOCK_WEIGHT`. À calibrer explicitement ; la concentration en dépend. λ_D est l'autre levier contre la concentration (non utilisé aujourd'hui).
5. **Influence du sentiment : un LLM, non reproductible.** Les crans (±2, soit ±0.10 de S) sont décidés par Pépite sans règle numérique (`pepite.py:231-247`). C'est le seul canal du « sentiment » : à documenter, à tester sur des exemples, ou à encadrer par une table de règles.
6. **Paramètres de rendement structurants à calibrer** : `erp_annual = 0.05`, `alpha = 0.50`, `RF_ANNUAL = 0.035` (hypothèses de démonstration, le code le dit) ; SPY pour toutes les actions, y compris les titres non américains ; méthode historique pure pour les obligations (la moyenne historique sur l'échantillon peut s'écarter de la période courante).
7. **`COVARIANCE_HISTORY.start_date = 2021-01-01`** : détermine quels titres sont admissibles. Un titre coté après cette date (plus 5 séances) n'entre jamais dans l'optimisation, quel que soit son historique.
8. **Relance assouplie et notes du juge.** `JUDGE_RELAUNCH_PENALTY = 3` ne s'applique qu'au profil cohérent (`workers.py:271-273`). Un portefeuille relancé avec limites assouplies peut donc être mieux classé en profil incohérent qu'en profil cohérent. La valeur 3 (sur 10) est un choix non calibré.

### Priorité 2 — Architecture et duplication

9. **`withAdjustments` écrase un portefeuille backend** par le mock et perd backtest, projection, montants, breakdown, facteurs (F1, `store.ts:93-105`).
10. **Douze constantes dupliquées front/backend sans test de parité** (F5) : ancres A/vol/actions, plancher d'obligations, `SLOT_SHIFT`, pondérations de C et T, `OBJECTIVE_TOLERANCE`, `CAPACITY_MARGIN`, `LOSS_BY_REACTION`, `LINE_CAP`, `FACTOR_LEVELS`.
11. **Le front calcule S et les limites avant le backend** et ignore les crans (F2, F3). Exposer ces valeurs depuis `monport_check` et retirer les formules du front.
12. **`min_held_weight = 0.01` et A ∈ [1, 25] définis à plusieurs endroits** (voir 1.E, 1.C), et un défaut de A à 7.0 dans `PepiteCheck` (`schemas.py:318`) contre 5.0 dans `config.py:312`.
13. **Seuil « position détenue » défini 5 fois** : `1e-7`, `1e-9`, `2e-4`, `5e-4`, `0.005`.

### Priorité 3 — Hygiène, démo, documentation

14. **Fallback et mock actifs** : métriques de démo à `rf 0.025`, `ρ 0.3`, `maxDrawdown = −min(0.9, 2.2σ)` ; message « Le juge confirme… » écrit en dur ; chiffres du script `runScript` inventés (F4, A2, E17). Isoler derrière un indicateur de démonstration.
15. **Code inerte et documentation périmée** : `BASE_*`, `CANDIDATES`, `MANDATES`, `BOND_SHIFT`, `PERIODS_PER_YEAR`, `RISK_AVERSION.bands`, docstring « 25 à 60 positions (cible 50) » (`portfolio_manager.py:4`) contre `25 à 70` (`config.py:278-279`).
16. **Trois définitions de la pire année à 2.33** (`monport.py:1055`, `evidence.py:28`, `engine.ts:269`).
17. **Défauts divergents** : horizon 12 (front) contre 10 (backend) ; A par défaut 5.0 (`config`), 7.0 (`PepiteCheck`), `A_MAX/5` (`allocator.py:510`, actif) et `A_MAX/2` (`allocator.py:216`, legacy).

---

## 4. Éléments non vérifiés

- `deploy/*.sh`, `nginx.conf` et `pyproject.toml` n'ont pas été lus : le caractère « déployé » repose sur les imports depuis `backend/main.py` et sur `catalog.settings_for`.
- Les numéros de ligne précédés de `~` sont approximatifs. Les valeurs, elles, ont été relues dans le code.
- Non relus en détail : `constraints.py` (hors constantes), `evidence.py` (hors constantes), `guardrail.py`, `workflow/session.py`, `workflow/flow.py` (hors lignes citées), `agents/*`, `catalog.preference_constraints` et `choices_breakdown`.
- Non vérifié : usage de `RISK_AVERSION.bands`, usage des clés `ledoit_wolf.target`, `ledoit_wolf.shrinkage_intensity`, `ledoit_wolf.block_size`, `minimum_holding_max_iterations` et `ESTIMATION.forecast_horizon_years` par le code actif ; définition backend de `SHARE_TOLERANCE`.
- **Pénalités de régularisation** : leur effet numérique n'a pas été mesuré (valeurs à 0.0). L'équivalence « terme diagonal ajouté à Σ » est une dérivation mathématique à partir de la formule du code, non un comportement observé. Le front-end ne mentionne pas ces pénalités (recherche textuelle sans résultat). Je n'ai pas vérifié si `backend/tests/test_regularization.py` (hors périmètre) passe.
- Front : `Home`, `Profile`, `Splash`, `Layout`, `Disclaimer`, `FactorModel`, `App.tsx`, début de `RiskNotebook.tsx` et `Pipeline.tsx` (lignes 60 à 160) relus partiellement ; condition `met` de `Factors.tsx` non lue ; tests du front non explorés.
- Aucun code n'a été exécuté : les valeurs de A citées en 1.G.3 et les exemples de pénalités de 1.B.2 sont calculés à la main, et l'écart d'annualisation de Σ n'est pas mesuré.


---
---

# VOLUME II — RÉFÉRENCE MÉTHODOLOGIQUE ET DÉFENSE DEVANT LE JURY

> Ce volume complète le Volume I sans le remplacer. Les numéros de ligne sont ceux du commit `9729f50` (relevés par `grep -n` ; `~` = approximatif). Chemins backend relatifs à `backend/src/invest_agents/` (**`ia/`**), front-end relatifs à `frontend/src/`.

## M0. Synthèse exécutive et mode d'emploi

### M0.1 Ce que fait le système (en six phrases)

1. Un client répond à un questionnaire de 7 questions. Le code en tire un score de risque **S** (0 à 1) et une aversion au risque **A** (1 à 25).
2. Un agent LLM (Pépite) vérifie la cohérence du questionnaire et rédige des profils de contraintes. Le code valide, complète et impose les limites chiffrées.
3. Le code construit un univers admissible (exclusions du client, historique depuis 2021), estime μ (rendements espérés) et Σ (covariance Ledoit-Wolf), puis maximise une utilité moyenne-variance par SLSQP.
4. Le code choisit entre 25 et 70 positions, chacune à 1 % au moins, puis recalcule les poids. Si les limites dures sont impossibles à tenir, il les assouplit dans un ordre fixe.
5. Des agents LLM expliquent, signalent les risques et jugent. Les chiffres ne viennent jamais d'un modèle (principe de conception, `backend/CLAUDE.md`, règle 1).
6. Le front-end affiche ce que le backend a calculé (backtest, projection, répartitions, contribution au risque, facteurs). Il garde une réplique des règles de profil pour le questionnaire, et un moteur d'exemple hors ligne.

### M0.2 Classification obligatoire des paramètres

| Étiquette | Définition | Exemple |
|---|---|---|
| **HARDCODED** | Valeur inscrite manuellement dans le code (constante de module ou littéral dans une fonction) | `VOL_ANCHORS`, `LINE_CAP`, `PATHS = 1000` |
| **CONFIGURABLE** | Valeur centralisée dans `config.py` (ou variable d'environnement), modifiable sans toucher à la logique | `RF_ANNUAL`, `erp_annual`, `PORTFOLIO_HOLDINGS` |
| **ESTIMATED** | Valeur calculée automatiquement à partir des données | β, intensité de rétrécissement Ledoit-Wolf, `periods_per_year_effective`, μ et σ historiques |
| **DYNAMIC** | Valeur qui dépend du questionnaire, du profil ou d'un agent | S, A, plafond de volatilité du client, crans de Pépite |

**Règle.** Un paramètre CONFIGURABLE reste une **hypothèse choisie à la main** s'il n'est pas estimé sur des données. Être centralisé dans `config.py` n'est pas une calibration statistique. Dans ce volume, tous les paramètres de profil, de rendement (ERP, α, rf) et de contraintes sont des hypothèses, sauf ceux étiquetés ESTIMATED.

**Trois niveaux de justification** utilisés partout :

- **DOCUMENTÉE** : écrite dans le dépôt (commentaire, docstring, `CLAUDE.md`, `FACTORS.md`), avec la référence.
- **PROPOSÉE** : explication financière que je suggère. Elle n'est **pas** un motif historiquement prouvé et n'a pas été validée empiriquement.
- **AUCUNE** : aucune justification trouvée dans le dépôt.

Les affirmations sont marquées **[Fait]** (vérifié dans le code), **[Interprétation]** (lecture financière) ou **[Reco]** (recommandation).

### M0.3 Douze constats à connaître avant le jury

| # | Constat | Référence |
|---|---|---|
| 1 | Toutes les ancres de profil (S→A, S→volatilité, S→plafond par action, planchers d'obligations) sont des **hypothèses manuelles**. Les seules justifications écrites sont des commentaires courts (« filet de sécurité », « une catégorie par tranche de 0,2 de S »). Aucune calibration empirique n'est documentée. | `monport.py:137-157` |
| 2 | Le plafond de volatilité du profil **n'est pas une contrainte du solveur SLSQP**. Il est appliqué en relevant A (échelle `A_LADDER` puis dichotomie), puis vérifié a posteriori. Si A = 25 ne suffit pas, le portefeuille est refusé puis relancé avec limites assouplies. | `allocator.py:133-164`, `catalog.py:832` |
| 3 | Pour un profil cohérent, les **trois variantes ne diffèrent que par A** (S−0,1 / S / S+0,1). Même univers, μ, Σ, contraintes et plafond de volatilité. | `monport.py:552-562`, `:750-800` |
| 4 | Les **pénalités de régularisation** (λ_D, λ_V) sont codées et branchées dans le solveur, mais valent **0,0**. Aucun effet aujourd'hui. | `config.py:405-408`, `optimizer.py:391-455` |
| 5 | Le **backtest est rétrospectif** : les poids viennent d'un optimiseur qui a vu les mêmes données (μ historique complet, Σ depuis 2021). Le projet le signale à l'écran (« flatteur »). Ce n'est pas un test hors échantillon. | `backtest.py:1-15`, `monport.py:1065` |
| 6 | La **projection sur 10 ans** est une simulation Monte Carlo gaussienne i.i.d. au niveau du portefeuille (μ, σ uniques). Sans frais, sans corrélation entre actifs, sans queues épaisses. | `projection.py:38-56` |
| 7 | Les **données macro** n'influencent ni les rendements, ni les contraintes, ni S. Elles servent aux analyses qualitatives des agents et aux « preuves » affichées au client. | `tools.py:30-76`, `evidence.py:131-160` |
| 8 | Il existe 5 **scores de facteurs** (z-scores par titre, photo yfinance du jour). Ils servent à des **contraintes d'exposition** demandées par le client, pas à un modèle de rendement ou de covariance. | `factors.py`, `catalog.py:636-673` |
| 9 | **L'annualisation de Σ** (`periods_per_year_effective`) diffère de celle de μ et de `ann_vol` (252). Écart non mesuré. | `market.py:250-257`, `:312` |
| 10 | En dernier recours, le code peut **assouplir les exclusions du client** (3ᵉ famille de `RELAXATION_STEPS`). La limite de 40 % par ligne n'est jamais assouplie. | `allocator.py:580-607` |
| 11 | Le **plafond par action en direct** (`STOCK_ANCHORS`) est écrit par Pépite (qui reçoit la valeur) ; le code ne l'ajoute qu'en son absence. Le plafond de volatilité, lui, est toujours écrit par le code. | `monport.py:782-784`, `:792-795` |
| 12 | Le front-end contient une **réplique** des formules de profil (S, A, limites, cohérence) et un moteur d'exemple hors ligne. `CLAUDE.md` liste les paires à garder synchronisées ; je n'ai pas trouvé de test automatique qui les compare. | `engine.ts`, `CLAUDE.md` (« À garder synchronisé ») |

### M0.4 Correspondance avec la demande d'audit

| Partie demandée | Où la lire |
|---|---|
| 1. Architecture financière globale | M1 |
| 2. Théories (rendements, covariance, optimisation) | M2 |
| 3. Facteurs et calibration | M3 |
| 4. Macroéconomie | M4 |
| 5. Contraintes et limites (5.1 à 5.6) | M5 |
| 6. Backtest | M6 |
| 7. Monte Carlo et patrimoine | M7 |
| 8. Cartographie backend vers front-end | M8 |
| 9. Limitations et sensibilité | M9 |
| 10. Questions des juges | M10 |
| 11. Contrôle de complétude, éléments non vérifiés | M11 |

---

## M1. Architecture financière réellement exécutée

### M1.1 Pipeline vérifié (ordre réel du code)

Le diagramme proposé dans la demande (« … Optimisation → Positions → Analyse des risques → **Backtest → Projections** → Agents et juge → Frontend ») doit être **corrigé** : le backtest, la projection, les facteurs et la contribution au risque sont calculés **à la présentation** (`to_portfolio`), **après** le juge. Les agents Risque et le juge ne lisent pas la sortie de `backtest.py` ni de `projection.py`.

```
 FRONT  Profile.tsx / Preferences.tsx  ── état Zustand (store.ts)
   │      calculs locaux d'affichage : riskScore, riskLabel, profileLimits, coherenceWarnings (engine.ts)
   ▼
 POST /api/invocations  {mode:'monport_check', profile, constraints}            api.ts:129
   ▼
 1. Vérification (workflow/flow.py:71-103, pepite.check_turn)
      monport.assess()  ─ S = risk_position(profil, crans)                      monport.py:355, :528
                          A = risk_aversion(S) ; vol max = interp(VOL_ANCHORS)   monport.py:370, :552
                          poids max par action = interp(STOCK_ANCHORS)           monport.py:528-536
      Pépite (LLM) : cohérence (coherent), texte ; repli : coherence_facts()     monport.py:424, :539
   ▼
 POST {mode:'monport', profile, constraints, contribution, check, adjustment}   api.ts:162-165
   ▼
 2. Construction (flow.build_portfolios l.188 → Pépite build_turn)
      crans d'ajustement ±2 (LLM)  adjust_risk_position                          pepite.py:231-247
      profils de contraintes écrits par Pépite (submit_constraint_plan)
   ▼
 3. apply_plan (workers.py:63)
      build_profiles : cohérence → 3 profils ; plancher d'obligations, interdiction
        crypto, plafond de volatilité (code), plafond par action (LLM sinon code)   monport.py:750-800
      ensure_feasible : retire les planchers impossibles ; relève le plafond de vol. monport.py:711-747
   ▼
 4. Par gestionnaire (build_slots workers.py:182 → run_pm_worker portfolio_manager.py:112)
      objective_for : mean_variance avec A_slot, ou max_sharpe (« Tes préférences »)
      optimize_with_relaxation (allocator.py:617) → optimize_universe (allocator.py:473) :
         a. universe_symbols : exclusions du client + historique depuis 2021        allocator.py:263
         b. market.universe_covariance : Σ Ledoit-Wolf synchronisée                 market.py:304
            μ : Market.assets["ann_return"] (méthode par classe)                    market.py:79
         c. catalog.plan_for : contraintes → bornes et groupes linéaires ; LP       catalog.py:676
         d. _continuous : optimum SLSQP continu (utilité pénalisée)                 allocator.py:302
         e. select_holdings : 25 à 70 positions                                     allocator.py:347
         f. réoptimisation avec plancher de 1 % : _solve / _best_sharpe             allocator.py:108-130
         g. _under_cap : relève A jusqu'à passer sous le plafond de volatilité      allocator.py:133
         h. _weights → portfolio_metrics → evaluate + audit                         allocator.py:167, market.py:394
         i. si échec : relance avec limites assouplies (RELAXATION_STEPS)           allocator.py:580-660
      PM (LLM) : explication seulement                                              portfolio_manager.py
   ▼
 5. Agents Risque (workers.run_risk l.153) : diagnostics() + preuves + outils macro  workers.py:133-175
   ▼
 6. Juge (workers.judge_round l.294) : conformité calculée par le code, note LLM,
      pénalité de relance, pick_winner                                              monport.py:894
   ▼
 7. Présentation (flow.present l.139) : gagnant ou mélanges 80/20 (blend + enforce_minimum)
      to_portfolio (monport.py:996) calcule alors :
         metrics, backtest (backtest.py:121), projection (projection.py:59),
         montants, répartitions, facteurs (factor_view), contribution au risque
   ▼
 SSE 'portfolios' → store.setPortfolios → Views.tsx / RiskNotes.tsx (Partie 2.6, M8)
```

### M1.2 Rôle de chaque module demandé

| Module | Rôle exact | Statut |
|---|---|---|
| `config.py` | Réglages (rendements, covariance, contraintes, solveur, pénalités) et `apply_portfolio_request` | ACTIF (mode agent) ; `BASE_*` LEGACY |
| `data.py` | Chargement, normalisation et validation du Parquet ; matrice de rendements | ACTIF |
| `market.py` | μ par méthode, filtre d'historique, rendements synchronisés, Σ Ledoit-Wolf, `portfolio_metrics` | ACTIF |
| `factors.py` | Scores de facteurs, expositions de portefeuille | ACTIF (contraintes et affichage) |
| `macro.py` | Lecture de la table macro, instantané et historique | ACTIF (agents et preuves), sans effet quantitatif |
| `monport.py` | S, A, ancres, profils de contraintes, mélange 80/20, `to_portfolio` | ACTIF |
| `catalog.py` | Validation des contraintes, `agent_request`, `plan_for`, `evaluate`, `audit` | ACTIF |
| `constraints.py` | Plan de bornes et groupes, faisabilité LP, `validate_weights` | ACTIF (`select_candidates` LEGACY) |
| `allocator.py` | Markowitz global, sélection des positions, A effectif, relance assouplie | ACTIF (`optimize` : partiellement) |
| `optimizer.py` | SLSQP, LP initial, pénalités, prune/reoptimize | ACTIF (`optimize_portfolio` et CLI : LEGACY) |
| `backtest.py` | Backtest, VaR/ES, distribution, contribution d'Euler | ACTIF (à la présentation) |
| `projection.py` | Projection à 10 ans et cônes | ACTIF (à la présentation) |
| `diagnostics.py` | 7 faits de risque lus par les agents Risque | ACTIF (texte pour LLM, non affiché tel quel) |
| `evidence.py` | Preuves chiffrées (pertes, concentration, macro) citées par les agents | ACTIF |
| Agents (`workflow/*`, `agents/*`) | Pépite, gestionnaires, agents Risque, juge | ACTIFS ; ils rédigent, ils ne calculent pas |

### M1.3 Statut des fonctionnalités

| Statut | Fonctionnalités |
|---|---|
| **Active en production** | Score S et A ; contraintes du profil ; Markowitz global SLSQP ; Ledoit-Wolf synchronisée ; sélection 25-70 positions ; plancher 1 % ; relance assouplie ; pénalité du juge ; backtest ; projection ; contribution au risque ; facteurs ; contexte macro pour les agents ; mélange 80/20 |
| **Implémentée mais désactivée ou inerte** | Pénalités λ_D et λ_V (valeur 0,0) ; cash synthétique `CASH-CAD` (forcé à `enabled=False`, `catalog.py:605`) ; méthode `capm_benchmark_shrinkage` (aucune classe ne la sélectionne ; `erp_annual_by_benchmark` vide) ; covariance `sample` ; `BACKTEST` et `REGIMES` de `config.py` (`enabled False`, non lus par `backtest.py`) |
| **Code legacy** | `BASE_CONSTRAINTS`, `BASE_PROFILE` ; `CANDIDATES` et `constraints.select_candidates` ; `optimizer.estimate_expected_returns`, `estimate_covariance`, `optimize_portfolio` ; `mandates.MANDATES` ; `BOND_SHIFT` |
| **Simulée dans le front-end** | `engine.ts` (poids, métriques, preuves), `UNIVERSE` et `CLASS_ASSUMPTIONS` de `catalog.ts`, `runScript`, `proposeAdjustment` (voir Partie 2) |
| **Proposée mais non implémentée** | Backtest walk-forward ; modèle factoriel de rendement ou de covariance ; μ conditionné à la macro ; frais dans la projection et le backtest ; recalibration des ancres ; coûts de transaction. `config.BACKTEST` annonce une méthode `walk_forward`, sans code correspondant |

**[Fait]** `CLAUDE.md` indique « Pas de frais affichés : le dataset n'en a pas », alors que `FEES = {"ETF": 0.002}` (`monport.py:131`) est calculé dans `to_portfolio` et transmis (`metrics.fees`). Il n'est jamais affiché ni utilisé dans le backtest ou la projection.


---

## M2. Théories financières utilisées

### M2.1 Estimation des rendements espérés μ

#### Méthodes réellement utilisées par classe (priorité : symbole > type d'instrument > classe)

Règle de choix : `get_return_method` (`ia/config.py:757-776`) ; réglages dans `ESTIMATION` (`config.py:96-150`) ; calcul dans `Market` (`market.py:79-127`, via `build_market`, `market.py:439`).

| Actif | Méthode | Réglage | Étiquette |
|---|---|---|---|
| Actions et FNB d'actions (classe `Equity`) | `capm_shrinkage` | `method_by_asset_class["Equity"]`, `config.py:105` | CONFIGURABLE |
| FNB d'obligations (`Fixed Income`) | `historical` | `config.py:106` | CONFIGURABLE |
| `Multi-Asset`, `Real Estate`, `Commodities`, `Alternative` (hors crypto) | `historical` | `config.py:107-110` | CONFIGURABLE |
| Cryptomonnaies directes (type `Cryptocurrency`) | `ewma` | `method_by_instrument_type`, `config.py:114` | CONFIGURABLE |
| `BITW` (ETP crypto) | `ewma` | `method_by_symbol`, `config.py:115` | CONFIGURABLE |
| `capm_benchmark_shrinkage` | **jamais sélectionnée** | `config.py:137-148` | INERTE |

**Pourquoi cette répartition ? [Fait]** Le dépôt donne deux éléments :

- En tête de `config.py` : « VERSION V4 — ETF obligataires : moyenne historique uniquement. Suppression complète des paramètres de modèles obligataires (duration, convexité, spreads et défauts) ». Les obligations utilisent donc la moyenne historique par **simplification** assumée.
- `config.py:101-103` : « Baseline opérationnelle ; les choix seront comparés hors échantillon ». Cette comparaison n'est pas dans le dépôt.

Je n'ai trouvé **aucune justification écrite pour l'EWMA des cryptos** (`DOCUMENTÉE` : aucune).

**Justification PROPOSÉE.** (i) Actions : la moyenne historique d'un titre est très bruitée (l'erreur-type d'une moyenne annuelle sur ~5 ans est de l'ordre de σ/√5, soit plusieurs points pour un titre à 30 % de volatilité) ; mélanger avec une cible CAPM stable (rf + β·ERP) réduit la variance de l'estimateur, au prix d'un biais vers le marché. (ii) Obligations : les FNB d'obligations ont une volatilité faible et un rendement lié au taux courant ; la moyenne historique est simple, transparente, et évite d'introduire un modèle de taux non calibré. (iii) Crypto : rendement et volatilité non stationnaires ; l'EWMA pondère les observations récentes. **Ces trois raisons sont mon interprétation, pas un motif documenté.**

#### Formules (code : `market.py`)

Rendements : `total_return_cad` quotidiens simples, en CAD, dividendes réinvestis (`config.DATA.return_column`, `config.py:33` ; source Yahoo Finance, `evidence.py:22`). Annualisation : `periods_per_year = 252` (`config.py:40`).

| Méthode | Formule | Fonction | Lignes |
|---|---|---|---|
| Moyenne historique | `μ = 252 × (1/N) Σ rₜ` sur tout l'historique du titre ; erreur si N < 120 | `_historical_mu` | `market.py:48-53` |
| EWMA | `μ = 252 × Σ ωₜ rₜ / Σ ωₜ`, `ωₜ = 0,5^(âge/90)` ; erreur si N < 120 | `_ewma_mu` | `market.py:55-64` |
| β | `β = Cov(rᵢ, r_SPY) / Var(r_SPY)` sur les dates communes ; `None` si < 120 dates ou variance nulle | `_beta` | `market.py:66-77` |
| CAPM avec rétrécissement | `μ = α (rf + β·ERP) + (1−α) μ_hist`, `α = 0,50` | `estimate_expected_returns` | `market.py:79-127` |
| Repli | si β est `None` : `μ = μ_hist`, méthode notée `historical_fallback` | idem | `market.py:~113-121` |

Paramètres (tous des **hypothèses**, sauf β et les moyennes) :

| Paramètre | Valeur | Étiquette | Nature |
|---|---|---|---|
| `RF_ANNUAL` | 3,5 % | CONFIGURABLE (`config.py:94`) | Hypothèse. Le code dit : « Hypothèse de démonstration, et NON un taux CAD/US universel ou un taux live » (`config.py:92-93`) |
| `erp_annual` | 5 % | CONFIGURABLE (`config.py:133`) | Hypothèse. « Illustrative, pas une donnée live » |
| `alpha` | 0,50 | CONFIGURABLE (`config.py:134`) | Hypothèse. Aucune justification dans le dépôt |
| `market_proxy` | SPY | CONFIGURABLE (`config.py:131`) | Hypothèse. « Baseline unique, pas un CAPM multi-classe » |
| `half_life_observations` | 90 séances | CONFIGURABLE (`config.py:124`) | Hypothèse |
| `min_observations`, `min_paired_observations` | 120 | CONFIGURABLE (`config.py:120`, `:125`, `:130`) | Hypothèse (≈ 6 mois) |
| `lookback_observations` | `None` (tout l'historique) | CONFIGURABLE | Hypothèse. Les commentaires « avant : 1260 », « avant : 756 » montrent que les fenêtres ont déjà changé |
| β | estimé | **ESTIMATED** | Calculé sur les données |
| Moyenne historique, pondérations EWMA | estimées | **ESTIMATED** | Calculées sur les données |

**Exemple chiffré (calculé à la main, illustratif).** Une action avec β = 1,2 et μ_hist = 20 % : cible CAPM = 3,5 % + 1,2 × 5 % = 9,5 % ; μ = 0,5 × 9,5 % + 0,5 × 20 % = **14,75 %**. Le rétrécissement ramène 20 % vers 14,75 %.

**Limites.** (a) La moyenne arithmétique ×252 surestime le rendement composé (écart ≈ σ²/2). (b) β est calculé sur des rendements bruts, pas sur des rendements excédentaires de rf. (c) SPY est utilisé pour toutes les actions, y compris canadiennes et européennes (β mesuré en CAD contre un indice américain). (d) Les FNB d'actions sont aussi traités par le CAPM sur SPY. (e) Le dataset commence en 2021 : l'historique « maximal » est court et contient des régimes particuliers (aucune analyse de régime dans le code). (f) L'optimisation moyenne-variance est très sensible aux erreurs sur μ.

**Affichage front.** Aucun μ par titre. Seul le rendement du portefeuille s'affiche (Partie 2.6 : `Views.tsx:128-134`, `:51`).

### M2.2 Covariance Σ et Ledoit-Wolf

#### Théorie

Variance d'un titre `σᵢ² = Var(rᵢ)` ; volatilité `σᵢ = √σᵢ²` ; corrélation `ρᵢⱼ = Cov(rᵢ,rⱼ)/(σᵢσⱼ)`. La variance du portefeuille est `wᵀΣw`. Avec p ≈ 700 titres et ≈ 1 500 dates, la covariance empirique est mal conditionnée. Ledoit-Wolf la remplace par une moyenne pondérée de la matrice empirique S et d'une cible structurée :

`Σ̂ = (1 − ρ) S + ρ m I`, avec `m = tr(S)/p` (la cible `scaled_identity`), et `ρ = min(β̂, δ̂)/δ̂` estimé sur les données.

Implémentation maison identique à `sklearn.covariance.LedoitWolf` (`market.py:145-162`, `_ledoit_wolf`) et appel direct de `sklearn` pour l'univers (`market.py:262-283`). `δ̂ = ‖S − mI‖²/p`, `β̂ = (1/(p n²)) Σₖ ‖xₖxₖᵀ − S‖²`.

**Intensité automatique [Fait].** `shrinkage_intensity: "auto"` (`config.py:243`) : ρ est calculé par la formule ci-dessus à chaque chargement (ESTIMATED). Il est rapporté dans les diagnostics (`shrinkage_coefficient`, `market.py:~280`) mais n'est pas affiché dans l'interface.

#### Chaîne de calcul de l'univers (code actif)

| Étape | Fonction | Lignes | Valeur / règle | Étiquette |
|---|---|---|---|---|
| Filtre d'historique | `history_filter` | `market.py:204-235` | début 2021-01-01 ; un titre doit avoir un rendement au début de l'horizon, à 5 séances ouvrables près ; sinon exclu de l'univers d'optimisation (raison tracée) | CONFIGURABLE (`config.py:265-268`) |
| Synchronisation | `synchronized_returns` | `market.py:237-260` | chaque titre est recomposé en indice de rendement total sur ses propres séances ; le rendement est celui de l'indice entre deux dates **communes** consécutives. Un jour férié devient un rendement sur plusieurs jours, il n'est pas supprimé | HARDCODED (méthode) |
| Annualisation | `synchronized_returns`, `universe_covariance` | `market.py:250-257`, `:312` | `periods_per_year_effective = n_communes / (jours/365,25)` ; repli sur 252 | **ESTIMATED** |
| Estimation | `ledoit_wolf_universe` | `market.py:262-283` | `LedoitWolf(assume_centered=False)` ; `Σ_annuelle = Σ_quotidienne × periods` ; symétrisée | CONFIGURABLE (`config.py:244`) |
| Minimum de dates communes | `ledoit_wolf_universe` | `market.py:~270` | 120 (`min_joint_observations`) | CONFIGURABLE (`config.py:235`) |
| Semi-définie positive | `optimize_weights` | `optimizer.py:519` | refus si valeur propre minimale < −1e-8 | HARDCODED |

#### Deux calculs de volatilité à ne pas confondre

| | (1) Volatilité historique individuelle | (2) `√Σᵢᵢ` de la matrice Ledoit-Wolf |
|---|---|---|
| Où | `ann_vol = std(rendements) × √252` (`market.py:440`) | `Market.universe_covariance` (`market.py:304`), utilisée par l'optimiseur |
| Données | Tout l'historique du titre, rendements quotidiens individuels | Rendements synchronisés depuis 2021, titres éligibles seulement |
| Estimateur | Écart-type d'échantillon (n−1) | Ledoit-Wolf (diviseur n, rétrécissement vers `m·I`) |
| Annualisation | 252 | `n_communes / années` |
| Usage | Écrans de tri, `screen_assets`, Sharpe de présélection, `_raise_volatility_cap` | Volatilité du portefeuille, `portfolio_metrics`, contribution au risque, seuil des pénalités |

**Pourquoi elles diffèrent [Fait + Interprétation].** (i) Le rétrécissement tire les variances extrêmes vers la moyenne des variances. (ii) Les rendements synchronisés couvrent parfois plusieurs jours, donc leur variance moyenne par période est plus grande ; l'annualisation par `n/années` en tient compte, 252 non. (iii) Les fenêtres diffèrent (historique complet contre depuis 2021). (iv) Les diviseurs diffèrent. Les deux ne sont donc pas comparables ligne à ligne. **L'écart n'a pas été mesuré** (aucune exécution). **[Reco]** : le mesurer avec `python -m invest_agents.market`, qui imprime les diagnostics.

**Limites.** Cible `m·I` : suppose des variances égales et aucune corrélation en l'absence de signal. Pas de modèle factoriel. Sensible aux épisodes extrêmes d'une fenêtre courte (environ 6 ans : 1 527 jours selon `docs/documentation-technique.md`). Σ est supposée stable dans le temps.

**Affichage front.** Σ n'est jamais affichée. Visible indirectement : volatilité du portefeuille (`Views.tsx:135-147`) et contribution au risque (`Views.tsx:376-421`).

### M2.3 Optimisation de Markowitz avec régularisation

#### Objectif (code : `optimizer.py:424-455`, `allocator.py:339-344`)

`U(w) = wᵀμ − (A/2) wᵀΣw − λ_D Σᵢ wᵢ² − λ_V Σᵢ qᵢ wᵢ²`, avec `qᵢ = max(0, Σᵢᵢ − 0,25²)`.

Contraintes : `Σᵢ wᵢ = 1`, `wᵢ ≥ 0` (long uniquement), bornes par titre, groupes linéaires (classes, parts régionales ou sectorielles, facteurs). Le problème continu est un programme quadratique **concave** (Σ semi-définie positive, pénalités convexes) : l'optimum est unique en l'absence de contraintes de cardinalité. La règle « 0 ou ≥ 1 % » et le nombre de positions le rendent non convexe : le code utilise donc des heuristiques sans garantie d'optimum global (docstring de `select_holdings`, `allocator.py:347-362`).

**Intuition.** `wᵀμ − (A/2)wᵀΣw` est l'équivalent certain moyenne-variance. A mesure la compensation exigée par point de variance : A = 25 (très prudent) demande beaucoup de rendement pour chaque unité de risque, A = 1 presque aucun. Dérivée : l'utilité marginale d'un titre est `μᵢ − A(Σw)ᵢ − 2λ_D wᵢ − 2λ_V qᵢ wᵢ` (`select_holdings.marginal`, `allocator.py:379-382`). Elle classe les titres à ajouter : un titre peu corrélé au portefeuille a un `(Σw)ᵢ` faible et gagne en utilité marginale même avec un μ modeste.

**Contribution au risque d'Euler** (`backtest.risk_contribution`, `backtest.py:141`) : `RCᵢ = wᵢ (Σw)ᵢ / wᵀΣw`, somme égale à 1. Les contributions par classe sont celles du front (`risk_by_class`, `monport.py:1095`).

#### Pénalités de régularisation (code actif, valeurs nulles)

| Élément | Valeur | Étiquette | Lignes |
|---|---|---|---|
| λ_D `diversification_penalty` | **0,0** | CONFIGURABLE, non calibré | `config.py:406` |
| λ_V `high_volatility_penalty` | **0,0** | CONFIGURABLE, non calibré | `config.py:407` |
| `volatility_threshold` | 0,25 (25 % annualisé) | CONFIGURABLE | `config.py:408` |
| `qᵢ` | calculé | ESTIMATED (dérive de Σᵢᵢ) | `optimizer.py:398-401` |

**[Fait]** Les deux pénalités sont **codées et branchées** dans le solveur (`_solve_slsqp`), dans l'utilité de référence (`_utility`) et dans le gain marginal de sélection. Avec 0,0 elles n'ont aucun effet ; l'optimiseur se comporte exactement comme avant leur ajout (commentaire `config.py:401-404`). Elles ne sont pas modifiables par le questionnaire ni par l'agent (`apply_portfolio_request` ne les accepte pas, `config.py:1091-1098`).

**Régularisation L2 / ridge.** `λ_D Σwᵢ²` est une pénalité L2 sur les poids (indice de Herfindahl). **[Dérivation à la main]** `U = wᵀμ − ½ wᵀ(AΣ + 2λ_D I + 2λ_V diag(q)) w` : elles équivalent à gonfler la diagonale de Σ, `Σ_eff = Σ + (2λ_D/A) I + (2λ_V/A) diag(q)`. Les corrélations ne changent pas.

**Interactions** (tableau, toutes déduites du code et de la formule ci-dessus) :

| Avec | Effet |
|---|---|
| A | Le terme ajouté à la diagonale vaut `2λ/A`. À λ fixé, il est **plus grand quand A est petit** : un profil audacieux est davantage régularisé qu'un profil prudent. Comme `_under_cap` relève A, la pénalité relative diminue quand le plafond de volatilité est actif |
| Plafond par ligne (0,40) et par action (7 à 22 %) | Bornes sur les poids. λ_D réduit la concentration à l'intérieur de ces bornes ; il ne la remplace pas |
| Plafond de volatilité | λ_V diminue les poids des titres > 25 % de volatilité et peut éviter de relever A. Le plafond reste vérifié sur le portefeuille réel |
| « 0 ou ≥ 1 % » | `prune_reoptimize` réoptimise avec la même fonction pénalisée ; les positions sous 1 % sont retirées |
| Pourcentages exacts et facteurs | Les égalités dominent ; la pénalité ne redistribue que le reste |
| `max_sharpe` (« Tes préférences ») | `_best_sharpe` parcourt `A_LADDER` avec des poids pénalisés ; le Sharpe est calculé sans pénalité |
| Affichage | Les indicateurs (μ, σ, Sharpe) sont calculés sans pénalité. `PortfolioResult.utility` (pénalisée) n'est pas affiché |

**Résolution SLSQP [Fait].** `scipy.optimize.minimize(method="SLSQP")`, gradient analytique, `maxiter = 2000`, `ftol = 1e-9` (`config.py:417-418`). Point de départ : solution du programme linéaire HiGHS faisable (`_linear_lp`, `optimizer.py:369-389`). `prune_reoptimize` pour la règle de 1 % (`optimizer.py:534-560`). Le nombre de positions est choisi par `select_holdings` (`allocator.py:347-440`) : part des titres détenus par l'optimum continu, complète jusqu'à 25 par lots de 10 selon l'utilité marginale, ajoute par lots de 5 tant que le coût d'utilité moyen d'une position reste ≤ 1 point de base (0,0001), plafond 70.

**Limites.** Optimum local pour la cardinalité ; sensibilité de A aux erreurs sur μ ; pas de coûts de transaction ; pas de contrainte de turnover.


---

## M3. Facteurs d'investissement et calibration

### M3.1 Ce qui existe réellement

Le système contient **5 scores de facteurs par action**, un calcul d'**exposition de portefeuille** et des **contraintes d'exposition** demandées par le client. Il ne contient **ni modèle factoriel de rendement, ni modèle factoriel de covariance** (voir M3.4).

| Élément | Où | Statut |
|---|---|---|
| Calcul des scores (hors ligne) | `data-prep/factors_model.ipynb`, décrit dans `data-prep/FACTORS.md` | Préparation des données, pas du code de production |
| Chargement et expositions | `ia/factors.py` | ACTIF |
| Contraintes d'exposition | `ia/catalog.py:636-673` (`_factor_groups`), `ia/monport.py:238-255` (`factor_constraints`) | ACTIF seulement si le client règle un facteur |
| Outil de présélection | `tools.screen_factor` (`tools.py:137`), `factor_fits` (`tools.py:295`) | ACTIF (agents gestionnaires) |
| Affichage | `Factors.tsx`, `FactorModel.tsx`, `RiskNotebook.tsx` | ACTIF (niveau Avancé, onglet Risque) |

**Provenance et chargement.** Fichier `factor_scores.parquet` (721 actions) produit par le notebook à partir de `universe.parquet` et des fondamentaux **yfinance `Ticker().info`**, publié sur `s3://monport-datasets-381491955506/factors/factor_scores.parquet`. En production, `MONPORT_FACTORS_PARQUET_URI` pointe vers ce fichier (`deploy/monport-backend.service:17`, `deploy-agentcore.sh:24`, `deploy-gateway.sh:18`). **[Fait]** Par défaut en local, `factors.py:30` cherche `backend/data/factor_scores.parquet`, qui **n'existe pas** dans le dépôt (le fichier est dans `data-prep/data/`). Sans fichier, `get_scores` renvoie une table vide et les préférences de facteurs sont **ignorées sans erreur** (`factors.py:59-73`).

### M3.2 Inventaire des facteurs

Orientation commune : **plus haut = meilleur** (`FACTORS.md`). Échelle : z-score, 0 = moyenne de la cellule (marché de cotation × secteur GICS), +1 = un écart-type mieux.

| Facteur (identifiant moteur / front) | Définition financière | Variables yfinance | Interprétation d'un score élevé | Score faible |
|---|---|---|---|---|
| `momentum` / `momentum` | Persistance des performances récentes des cours | `fiftyTwoWeekChangePercent` (variation sur 12 mois) ; `twoHundredDayAverageChangePercent` (écart à la moyenne mobile 200 jours) | A mieux performé que ses pairs de la cellule | A sous-performé |
| `quality` / `qualite` | Rentabilité et solidité financière | `returnOnAssets` ; `operatingMargins` ; −`debtToEquity` ; `freeCashflow / totalRevenue` | Rentable, peu endetté, bon flux de trésorerie libre | Faible rentabilité ou fort endettement |
| `value` / `value` | Bon marché relatif (inverses des multiples) | 1/`forwardPE` ; ratio B/P ; ratio S/P (`priceToSalesTrailing12Months`) ; EBITDA/VE (`enterpriseToEbitda`) | Bon marché par rapport à ses pairs | Cher |
| `growth` / `croissance` | Croissance des revenus et des bénéfices | `revenueGrowth` ; `earningsGrowth` ; `forwardEps/trailingEps − 1` (si BPA passé > 0) | Croissance supérieure | Croissance inférieure |
| `small_cap` / `taille` | Prime de petite capitalisation (score de taille **inversé**) | `log(marketCap)`, z-score dans le marché de cotation seulement ; `small_cap = −size` (`factors.py:51`) | **Petite** entreprise | Grande entreprise |

**Intuition économique (PROPOSÉE, littérature classique).** Momentum : autocorrélation des rendements à 12 mois. Value : primes pour les titres décotés. Quality : rentabilité durable. Growth : anticipation de la croissance des bénéfices. Taille : prime historique des petites capitalisations. **Aucune prime de risque associée n'est estimée ni utilisée dans le projet.**

**Calcul (notebook, section 4 et suivantes) [Fait].**

1. Chaque mesure est **winsorisée** aux percentiles 1 et 99 sur tout l'échantillon (`WINSOR = (0.01, 0.99)`).
2. Chaque mesure est transformée en **z-score dans sa cellule** (`CELL = ["market","sector"]`). Une cellule de moins de 5 valeurs retombe sur le marché entier (`MIN_CELL = 5`, `FALLBACK = ["market"]`).
3. Un facteur est la **moyenne simple (1/n)** des z-scores de ses mesures disponibles, puis **re-standardisé** dans la même cellule.
4. La taille est `log(marketCap)` standardisé dans le **marché** seulement.
5. Données manquantes : la moyenne se fait sur les mesures présentes ; sans aucune mesure, le facteur vaut **0** (neutre). `prepare_scores` applique en plus `fillna(0.0)` (`factors.py:52`).
6. Cas particuliers : capitaux propres négatifs (36 actions) reçoivent la **pire** valeur d'endettement ; BPA ou valeur comptable négatifs gardent un E/P ou B/P négatif (donc cher).

**Contrôles documentés.** Couverture ≥ 89 % par mesure. Corrélations entre facteurs |ρ| ≤ 0,30 (value contre taille −0,30). Les meilleurs noms paraissent plausibles (qualité : MA, V ; taille : AAPL, NVDA, MSFT).

**Fonctions Python.** `prepare_scores` (`factors.py:43-52`), `get_scores` (`:59`), `scores_for` (`:76`), `available_factors` (`:82`), `meets` (`:87`), `exposure` (`:96`), `exposures` (`:106`).

### M3.3 Du score à la contrainte et au portefeuille

**Exposition agrégée (B).** `b = Σᵢ wᵢ zᵢ / Σᵢ wᵢ` sur les seules actions détenues en direct et notées (`factors.exposure`, `factors.py:96-103`). Les FNB et les cryptos n'ont pas de score ; la part couverte est rapportée (`coverage`).

**Du questionnaire à la contrainte.**

| Étape | Fonction | Lignes | Détail |
|---|---|---|---|
| Choix du client | `Preferences.tsx` | `:47-48`, `:117` | L'étape « facteurs » n'apparaît que si l'aisance est ≥ 4 ; échelle Exclure −2, Moins −1, Neutre 0, Plus +1, Imposer +2 (`catalog.ts:9`) |
| Traduction | `factor_constraints` | `monport.py:238-255` | niveau > 0 : `MIN_FACTOR_EXPOSURE` ; niveau < 0 : `MAX_FACTOR_EXPOSURE` ; seuil `FACTOR_LEVELS[niveau]` ; **dure seulement si \|niveau\| = 2**. Ignoré avec « FNB seulement » |
| Promotion | `promote_preferences` | `monport.py:601` | « Moins » et « Plus » deviennent durs un à un tant qu'ils ne créent pas de conflit, dans les profils qui suivent les préférences |
| Linéarisation | `_factor_groups` | `catalog.py:636-673` | `b ≥ s ⟺ Σ wᵢ (zᵢ − s) ≥ 0` ; la cible vise `s + 0,01` (min) ou `s − 0,01` (max) ; plancher de 10 % en actions notées (sinon un portefeuille sans action notée respecterait toute contrainte, 0 ≥ 0) |
| Faisabilité | `_factor_groups` | `catalog.py:659-668` | erreur claire si aucune action de la sélection ne peut atteindre le seuil |
| Vérification | `evaluate` | `catalog.py:846-847` | tolérance `FTOL = 0,01` |
| Présélection | `screen_factor`, `factor_fits`, `factors.meets` | `tools.py:137`, `:295`, `factors.py:87` | actions qui respectent chaque seuil à elles seules, les moins volatiles d'abord (utile car les mieux notées sont souvent très volatiles, `CLAUDE.md`) |

**Influence sur le portefeuille.** Un facteur imposé (≥ +0,5) force au moins 10 % du portefeuille dans des actions notées et un tilt moyen d'au moins +0,5 écart-type de cellule. Sans demande du client, **aucun facteur n'influence l'optimisation** (μ et Σ ne dépendent pas des scores).

### M3.4 Constantes de calibration des facteurs

| Constante | Valeur | Fichier:ligne | Origine | Justification | Conséquence d'un changement |
|---|---|---|---|---|---|
| `FACTOR_LEVELS` | 2→+0,5 ; 1→+0,2 ; −1→−0,2 ; −2→−0,5 (en écarts-types) | `monport.py:113` | HARDCODED | DOCUMENTÉE (commentaire : « Plus/Moins = légère inclinaison, Imposer/Exclure = nette (dure) »). Pas de calibration | Hausse : contraintes plus serrées, plus de risque d'infaisabilité, tilt plus marqué |
| `FACTOR_SLEEVE_MIN` | 0,10 | `catalog.py:156` | HARDCODED | DOCUMENTÉE (« sinon 0 action la respecte ») | Hausse : davantage d'actions notées imposées ; baisse : la contrainte peut être satisfaite par un très petit bloc d'actions |
| `FACTOR_MARGIN` | 0,01 | `catalog.py:157` | HARDCODED | DOCUMENTÉE (arrondi des poids à 4 décimales) | Hausse : l'optimiseur vise plus au-delà du seuil |
| `SCORE_RANGE` | 3,0 | `catalog.py:155`, utilisée `:280` | HARDCODED | DOCUMENTÉE (« au-delà de ±3 écarts-types n'a pas de sens ») | Valide la saisie de seuil |
| `FTOL` | 0,01 | `catalog.py:158` | HARDCODED | DOCUMENTÉE (tolérance d'exposition) | Hausse : plus de portefeuilles jugés conformes |
| `FACTOR_TOP` | 8 | `monport.py:1114` | HARDCODED (affichage) | AUCUNE | Nombre d'actions détaillées à l'écran |
| `MIN_CELL`, `WINSOR`, `CELL`, `FALLBACK` | 5 ; (1 %, 99 %) ; marché × secteur ; marché | `factors_model.ipynb` (section 4) | HARDCODED (notebook) | DOCUMENTÉE (`FACTORS.md`) pour le choix des cellules ; AUCUNE pour 5 et 1 %/99 % | Hausse de `MIN_CELL` : plus de cellules retombent sur le marché entier |
| Poids des mesures | 1/n égaux | notebook | HARDCODED | DOCUMENTÉE comme limite : « aucune optimisation ni backtest derrière ce choix » (`FACTORS.md`) | Changer les poids déplace les scores |
| Valeur par défaut | 0 | `factors.py:52` ; notebook | HARDCODED | DOCUMENTÉE (neutre) | Une action sans donnée est traitée comme moyenne de sa cellule |
| Signe de la taille | `small_cap = −size` | `factors.py:51` | HARDCODED | DOCUMENTÉE (commentaire `factors.py:31-32`) | Inverse le sens de « Plus » pour la taille |
| `RANGE`, `NEUTRAL`, seuils d'intensité | 1,5 ; 0,1 ; 0,3 et 0,6 ; 0,18 | `Factors.tsx:10-11`, `:39` | HARDCODED (front, affichage) | AUCUNE | Échelle de la jauge et libellés « Neutre / Légère / Nette / Forte » |

**Calibration disponible : aucune.** Il n'y a ni test de stabilité temporelle, ni vérification qu'une exposition à un score produit un rendement. `FACTORS.md` ajoute : instantané du jour (**impropre au backtest sans biais d'anticipation**), données Yahoo gratuites avec trous, momentum sur les cours seuls (inclut le dernier mois), cellules parfois très petites, ratios peu pertinents pour les banques.

### M3.5 Trois concepts à ne pas confondre

| Concept | Existe ? | Détail |
|---|---|---|
| **A. Score factoriel d'un titre** | **Oui** | Z-score par cellule, 5 facteurs, `factor_scores.parquet` |
| **B. Exposition factorielle agrégée d'un portefeuille** | **Oui** | Moyenne pondérée des z-scores (`factors.exposure`), affichée et contrainte à la demande du client |
| **C. Modèle factoriel de rendement ou de covariance** | **Non** | μ vient de l'historique/CAPM sur SPY, Σ de Ledoit-Wolf. Les scores n'entrent ni dans μ ni dans Σ. Ne pas présenter le CAPM sur SPY comme un modèle multifactoriel : c'est un modèle à un facteur de marché |

### M3.6 Affichage dans le front-end

| Concept | Composant : lignes | Niveau |
|---|---|---|
| Exposition par facteur (jauge et repère de la demande, « pas atteinte ») | `FactorCard`, `Factors.tsx:54-113` ; monté via `FactorExposure` (`:214`, `Views.tsx:385`) | Avancé, onglet « Risque » |
| Part du portefeuille en actions notées (`coverage`) | `Factors.tsx:231-241` | idem |
| Contributions par action | `Factors.tsx:132-175` | idem |
| « Comment on calcule les scores ? » | `FactorModel.tsx:20`, données `FACTOR_MODEL` (`catalog.ts:114`) | idem |
| Réglage du client | `Preferences.tsx:47-48`, `:117` ; libellés `FACTOR_VIEW` (`catalog.ts:101`) | Questionnaire (aisance ≥ 4) |
| Seuils des niveaux | `FACTOR_TARGETS` (`catalog.ts:160`), `RiskNotebook.tsx:382` | Carnet de Pépite |

**[Fait]** `FACTOR_TARGETS` (front) duplique `FACTOR_LEVELS` (backend).

---

## M4. Indicateurs macroéconomiques

### M4.1 Provenance et préparation (vérifiées dans `data-prep/Macro.ipynb`)

Source des séries : notebook `data-prep/Macro.ipynb` (téléchargement HTTP direct, sans clé API visible), exporté en `data/macro_long_z.csv` puis en Parquet (`backend/data/macro_long_z.parquet`, S3 `s3://monport-datasets-381491955506/macro/macro_long_z.parquet`). Chargé par `macro.get_macro` (`macro.py:69-80`) via `MONPORT_MACRO_PARQUET_URI`.

| Pays | Indicateur (`metric`) | Série source | Fournisseur | Fréquence | Transformation |
|---|---|---|---|---|---|
| US | `yield_10y` | FRED `DGS10` | Réserve fédérale de St. Louis | Quotidienne | Niveau (%) |
| US | `yield_2y` | FRED `DGS2` | idem | Quotidienne | Niveau (%) |
| US | `policy_rate` | FRED `DFF` | idem | Quotidienne | Niveau (%) |
| US | `inflation_yoy` | FRED `CPIAUCSL` (IPC, corrigé) | idem | Mensuelle | `pct_change(12) × 100` |
| US | `unemployment_rate` | FRED `UNRATE` | idem | Mensuelle | Niveau (%) |
| CA | `yield_10y` | BoC `BD.CDN.10YR.DQ.YLD` | Banque du Canada (API Valet) | Quotidienne | Niveau (%) |
| CA | `yield_2y` | BoC `BD.CDN.2YR.DQ.YLD` | idem | Quotidienne | Niveau (%) |
| CA | `policy_rate` | BoC `V39079` (cible du taux à un jour) | idem | Quotidienne | Niveau (%) |
| CA | `inflation_yoy` | BoC `V41690973` (IPC, tous articles) | idem | Mensuelle | `pct_change(12) × 100` |
| CA | `unemployment_rate` | FRED `LRUNTTTTCAM156S` | OCDE, via FRED | Mensuelle | Niveau (%) |
| US, CA | `spread_10y_2y` | dérivé | — | Quotidienne | Ligne de calcul non relue ; présumée `yield_10y − yield_2y` (**non vérifié**) |

**Décalages de publication (anti-anticipation) [Fait, notebook].** Toutes les séries : +1 jour (`daily_lag = 1`). Inflation : début du mois suivant + 21 jours + 1. Chômage : + 8 jours + 1 (`release_lag`). La colonne `ref_period` garde la période décrite par la valeur.

**Z-scores [Fait].** `z_5y` : fenêtre glissante de 1 826 jours, passé seulement, `min_periods` 48 (mensuel) ou 1 000 (quotidien). `z_full` : fenêtre croissante depuis le début, `min_periods` 24 (mensuel) ou 250 (quotidien). Sans anticipation.

**Historique et taille.** Début de téléchargement 1950-01-01 ; chaque série garde son propre début (`history_start_date`) ; dernière date du fichier : 2026-11-13 (sortie du notebook) ; environ 95 000 lignes (`macro.py:6`).

### M4.2 Fonctions et usage

| Fonction | Lignes | Rôle |
|---|---|---|
| `latest_snapshot` | `macro.py:101` | Dernière ligne par (pays, indicateur), avec `days_stale` |
| `history` | `macro.py:109` | Historique filtré (mensuel ou natif ; au plus 1 000 lignes, 600 par défaut) |
| `make_macro_tools` | `tools.py:41-76` | Outils `get_latest_macro_snapshot`, `get_macro_history` |
| `MACRO_PROMPT` | `tools.py:30` | Consigne aux agents (citer la fenêtre du z-score) |
| `macro_evidence` | `evidence.py:131-160` | 7 preuves montrées au client : taux directeur CA et US, inflation CA et US, taux 10 ans CA, écart 10-2 ans CA, chômage CA |

### M4.3 À quoi servent-elles vraiment ?

| Usage possible | Réponse | Preuve |
|---|---|---|
| 1. Modifier quantitativement les rendements μ | **Non** | `market.py:79-127` n'utilise aucune donnée macro ; `ESTIMATION` n'a pas de paramètre macro |
| 2. Modifier les contraintes ou S | **Non** | Aucune lecture de `macro` dans `monport.py`, `catalog.py`, `constraints.py`, `allocator.py` (recherche `get_macro` : seuls `tool_core.py`, `evidence.py`, `macro.py`) |
| 3. Influencer les analyses qualitatives des agents | **Oui** | Outils exposés aux gestionnaires (`portfolio_manager.py:106`), aux agents Risque (`workers.py:130`, `:160`) et au juge (`workers.py:254`, `:291`) ; non exposés à Pépite |
| 4. Informer l'utilisateur | **Oui** | Preuves `EvidenceCard` (valeur, moyenne sur 5 ans, série) citées dans les mises en garde |

**Intuition économique (PROPOSÉE).** Les taux et la pente de la courbe (10 ans − 2 ans) influencent la valorisation des obligations et des actions ; l'inflation érode le rendement réel ; le chômage reflète le cycle. Ces liens sont **présentés au client comme contexte**, pas utilisés pour recalculer le portefeuille.

**Pas de pondération par la macro.** Aucun indicateur de crédit ou de croissance (PIB, écarts de crédit) n'existe dans la table. **Ne pas en affirmer.**

**Affichage.** `RiskNotes.tsx:9`, `Evidence.tsx:5` (preuves macro avec moyenne sur 5 ans en pointillé, `CLAUDE.md`).

**Limites.** Pays limités à US et CA ; pas de zone euro alors que l'univers inclut des titres français et européens. Source d'inflation et de chômage retardée de 1 à 2 mois. **[Reco]** Une intégration quantitative (ex. régime de taux comme variable de contrainte) serait défendable seulement après une étude hors échantillon (voir M9.6).


---

## M5. Inventaire des contraintes et limites financières

> **Priorité du chapitre.** Ces valeurs sont des **hypothèses manuelles** (HARDCODED). Aucune n'est estimée sur des données. Les justifications DOCUMENTÉES se limitent à de courts commentaires ; les justifications PROPOSÉES sont les miennes et n'ont pas été validées empiriquement.

### M5.1 Contraintes selon le profil investisseur

#### Vue d'ensemble par bande de score S

`risk_label(S)` découpe S en 5 bandes de 0,2 (`monport.py:375-376`, `RISK_LABELS` `:154`). Les valeurs aux bornes de bande sont celles des ancres ; entre deux ancres l'interpolation est décrite plus bas.

| Bande | S | Score affiché (5+90S) | A (début → fin de bande) | Volatilité max (début → fin) | Plafond par action en direct | Plancher d'obligations | Crypto et « Alternative » | Plafond par ligne | Min. par position | Positions |
|---|---|---|---|---|---|---|---|---|---|---|
| conservateur | [0 ; 0,2[ | 5 → 23 | 25 → 14 | 6 % → 8 % | 7 % → 9 % | **80 %** | **exclues** | 40 % | 1 % | 25 à 70 |
| modéré | [0,2 ; 0,4[ | 23 → 41 | 14 → 7 | 8 % → 11 % | 9 % → 11 % | **60 %** | **exclues** | 40 % | 1 % | 25 à 70 |
| équilibré | [0,4 ; 0,6[ | 41 → 59 | 7 → 3,5 | 11 % → 14 % | 11 % → 13 % | **40 %** | permises | 40 % | 1 % | 25 à 70 |
| dynamique | [0,6 ; 0,8[ | 59 → 77 | 3,5 → 1,5 | 14 % → 18 % | 13 % → 17 % | **20 %** | permises | 40 % | 1 % | 25 à 70 |
| agressif | [0,8 ; 1,0] | 77 → 95 | 1,5 → 1 | 18 % → 25 % | 17 % → 22 % | **0 %** | permises | 40 % | 1 % | 25 à 70 |

**Lecture [Fait].** (a) A, la volatilité maximale et le plafond par action sont **continus** en S (interpolation entre ancres). Le plancher d'obligations et l'interdiction de crypto sont des **fonctions en escalier** : à S = 0,399 le plancher vaut 60 %, à S = 0,401 il vaut 40 %. (b) Pour un profil cohérent, A utilise `S_slot` (décalé de ±0,1), alors que le plafond de volatilité, le plafond par action, le plancher d'obligations et la crypto utilisent le **S non décalé** du profil. (c) Le plancher d'obligations est réduit à la place que laissent les pourcentages de classes fixés par le client (`follow_profile`, `monport.py:584-588`).

#### Ancres de volatilité (`VOL_ANCHORS`) : vérification et fiche

**Valeurs vérifiées dans le code actuel** (`ia/monport.py:152`) :

```python
VOL_ANCHORS = [(0.0, 0.06), (0.2, 0.08), (0.4, 0.11), (0.6, 0.14), (0.8, 0.18), (1.0, 0.25)]  # filet de sécurité
```

| Ancre | Score S | Volatilité max (annualisée) | Pente jusqu'à l'ancre suivante | Bande qui commence | Interprétation de la valeur |
|---|---|---|---|---|---|
| 1 | 0,0 | **6 %** | +2 pts par 0,2 de S | conservateur | Très prudent |
| 2 | 0,2 | **8 %** | +3 pts | modéré | |
| 3 | 0,4 | **11 %** | +3 pts | équilibré | Exemple demandé : un client à S = 0,4 est limité à 11 % |
| 4 | 0,6 | **14 %** | +4 pts | dynamique | |
| 5 | 0,8 | **18 %** | +7 pts | agressif | |
| 6 | 1,0 | **25 %** | — | agressif | Très audacieux |

**Caractéristiques communes à toutes les ancres.**

| Question | Réponse vérifiée |
|---|---|
| Fonction qui interpole | `_interpolate(s, VOL_ANCHORS)` (`monport.py:362-367`), appelée par `assess` (`:528-536`), `slot_volatility` (`:552-562`) et `choices_breakdown` (`:479`) |
| Type d'interpolation | **Linéaire** par segment : `v = v0 + (v1 − v0)·t`, `t = (S − s0)/(s1 − s0)` (`log=False`) |
| Arrondi | `round(·, 3)` (`slot_volatility`, `assess`) |
| Quel S est utilisé ? | `check.risk_position` du profil **non décalé** pour un profil cohérent (donc le même plafond pour les 3 variantes) ; S du slot pour un profil incohérent (`monport.py:560`) |
| Quand devient-elle une contrainte ? | `assess` ne fait que la **calculer** (champ `suggested_max_volatility`, lu par Pépite). Le code la **pose** ensuite : `build_profiles` retire toute `MAX_VOLATILITY` de Pépite et ajoute `Constraint(MAX_VOLATILITY, hard=True, note="Limite du profil")` (`monport.py:792-795`). `ensure_feasible` peut la relever (`monport.py:720-747`) |
| Est-ce une contrainte du solveur SLSQP ? | **Non.** Elle n'est pas dans le plan linéaire (`catalog.agent_request` la laisse « à l'optimiseur », `catalog.py:515-524`). `optimize_universe` lit `_volatility_cap` (`allocator.py:100-105`), puis `_under_cap` (`allocator.py:133-164`) **augmente A** le long de `A_LADDER` jusqu'à passer sous le plafond, puis affine par 6 pas de dichotomie. `evaluate` vérifie `σ ≤ plafond + 0,001` (`catalog.py:832`, `TOL`) |
| Que se passe-t-il si même A = 25 échoue ? | Résultat `infeasible` ; `optimize_with_relaxation` relance et **lève le plafond** à l'étape « plafonds » (`allocator.py:651-660`) ; avertissement au client |
| Pas de pénalité du juge pour le dépassement ? | La conformité du juge est recalculée sur les limites d'origine, donc un dépassement sera signalé comme limite non respectée |
| Étiquette | **HARDCODED** (valeurs) ; **DYNAMIC** (valeur retenue pour un client donné) |
| Dupliquée dans le front ? | Oui : `profileLimits` (`engine.ts:92-101`), valeurs `[.06,.08,.11,.14,.18,.25]`, et `RiskNotebook.tsx:417` (affichage) |

**Conséquence si une valeur augmente ou diminue.** Hausse : le profil tolère un portefeuille plus volatil, A est moins souvent relevé, le portefeuille se rapproche de l'optimum non plafonné (plus de rendement espéré, plus de risque). Baisse : A est relevé plus tôt (jusqu'à 25), le portefeuille se déplace vers les obligations et les titres à faible volatilité ; si l'univers ne permet pas de descendre assez bas, `_raise_volatility_cap` relève le plafond de `lowest + 0,003` arrondi au point supérieur (`monport.py:745`).

**Justification DOCUMENTÉE.** (1) Commentaire « filet de sécurité » (`monport.py:152`). (2) `RiskNotebook.tsx:417` : « de variations par an : un filet de sécurité sous A ». (3) Le prompt de Pépite parle de « plafond de variations » parmi les garde-fous (`pepite.py:104`). **Aucune justification chiffrée** : le dépôt n'explique pas pourquoi 11 % à S = 0,4.

**Justification PROPOSÉE (non prouvée).** Les plafonds forment une échelle croissante d'un portefeuille très défensif (~6 %) à un portefeuille actions-majoritaire (~25 %). À titre d'ordre de grandeur général (non mesuré sur nos données) : un portefeuille 60 % actions / 40 % obligations a historiquement une volatilité annuelle de l'ordre de 10 %, ce qui est cohérent avec ~11 % pour un profil « équilibré » (plancher d'obligations de 40 %) ; un portefeuille 100 % actions diversifié se situe autour de 15 à 20 % ; 25 % à S = 1 autorise des titres plus volatils. Les pentes croissantes (+2, +3, +3, +4, +7) laissent davantage de place aux profils audacieux.

**Limites.** (a) Aucune calibration sur l'univers réel ni sur une enquête de tolérance. (b) La volatilité réalisée dépend de Σ (rétrécie, annualisation estimée), pas de la volatilité « de marché ». (c) Le plafond est une limite sur σ annualisé, pas sur la perte maximale. (d) Le plancher d'obligations (en escalier) et le plafond de volatilité (linéaire) peuvent entrer en tension près des bornes de bande. (e) L'accroissement de A pour respecter le plafond rend le portefeuille plus prudent que A(S), donc que la variante demandée.

**Comment calibrer.** Voir M9.4 : comparer, pour chaque S, la volatilité réalisée du portefeuille optimal à A(S) sans plafond sur l'univers réel ; choisir des plafonds au-dessus de cette valeur pour que le plafond serve de filet et non de contrainte active ; valider hors échantillon.

**Exemple chiffré (demandé).** Pour S = 0,773 : entre les ancres 0,6 (14 %) et 0,8 (18 %), `t = (0,773 − 0,6)/0,2 = 0,865`, donc `14 % + 0,865 × 4 % = 17,46 % ≈ 17,5 %`. Calculé par `assess` et `slot_volatility`, ajouté comme contrainte dure « Volatilité annualisée ≤ 17,5 % » par `build_profiles`, identique pour les trois variantes d'un profil cohérent. L'optimiseur la respecte en augmentant A jusqu'à 25 si nécessaire (`allocator._under_cap`). (Valeurs vérifiées par lecture du code, calcul à la main.)

#### Ancres d'aversion au risque (`AVERSION_ANCHORS`)

`ia/monport.py:151` : `[(0.0, 25.0), (0.2, 14.0), (0.4, 7.0), (0.6, 3.5), (0.8, 1.5), (1.0, 1.0)]`.

| S | A | Rapport A(s₀)/A(s₁) du segment qui suit | Quelle bande |
|---|---|---|---|
| 0,0 | 25 | 1,79 | conservateur |
| 0,2 | 14 | 2,00 | modéré |
| 0,4 | 7 | 2,00 | équilibré |
| 0,6 | 3,5 | 2,33 | dynamique |
| 0,8 | 1,5 | 1,50 | agressif |
| 1,0 | 1 | — | |

| Question | Réponse |
|---|---|
| Fonction | `risk_aversion(S) = round(_interpolate(S, AVERSION_ANCHORS, log=True), 2)` (`monport.py:370-372`) |
| Type | **Logarithmique** (géométrique) : `A = A₀ (A₁/A₀)^t` |
| Quand devient-elle un paramètre du solveur ? | `objective_for` → `Mandate.risk_aversion` (`workers.py:189-191`) → `optimize_with_relaxation(risk_aversion=…)` (`portfolio_manager.py:135`) → `aversion0` (`allocator.py:510`) → `_solve_slsqp` (A dans `−wᵀμ + ½A wᵀΣw`, `optimizer.py:437-442`). Écrit dans `risk_aversion.default` par `apply_portfolio_request` et borné à [1 ; 25] (`allocator.py:45`, `:111`) |
| Hausse d'une valeur | Portefeuille plus prudent pour les S proches |
| Baisse | Plus audacieux |
| Dupliquée | `engine.ts:69` |
| Justification DOCUMENTÉE | Commentaire : « Une catégorie par tranche de 0,2 de S, bornes de A du tableau des profils (interpolation logarithmique) » (`monport.py:149-150`). Le « tableau des profils » **n'est pas dans le dépôt** (non vérifié). `backend/CLAUDE.md` : sur le dataset **synthétique**, A = 25 donne environ 4 % de volatilité et A = 1 environ 15 % |
| Justification PROPOSÉE | La plage 1 à 25 couvre un facteur 25 entre le profil le plus audacieux et le plus prudent. L'interpolation géométrique assure que A **diminue d'un facteur à peu près constant par bande** (≈ 2). Une interpolation linéaire donnerait presque la même valeur de A pour tous les profils audacieux (de 3,5 à 1 sur 40 % de l'échelle) et trop de poids aux profils prudents |
| Heuristique de calibration (illustration, non mesurée) | Pour un portefeuille risqué de Sharpe SR combiné à un actif sans risque, la volatilité optimale est `σ* ≈ SR/A`. Avec SR ≈ 0,4 (hypothèse), A = 7 donne ≈ 6 %, A = 3,5 ≈ 11 %, A = 1,5 ≈ 27 %. Cette relation n'est qu'approximative ici (portefeuille intégralement investi) ; elle suggère de vérifier la cohérence A ↔ plafond de volatilité (M9.4) |
| Limite | Le A d'un profil dépend aussi de μ et de Σ estimés : « le même A » ne donne pas la même volatilité d'un univers à l'autre |

#### Plafond par action en direct (`STOCK_ANCHORS`)

`ia/monport.py:153` : `[(0.0, 0.07), (0.2, 0.09), (0.4, 0.11), (0.6, 0.13), (0.8, 0.17), (1.0, 0.22)]`. Interpolation **linéaire**, arrondie à 3 décimales (`assess`, `monport.py:528-536`).

| Question | Réponse |
|---|---|
| Chemin | `assess` calcule `suggested_max_position_weight` ; Pépite le reçoit (`pepite.py:183`) et écrit `max_stock_weight` ; si elle l'oublie, `build_profiles` ajoute `min(suggested, 0,40)` (`monport.py:782-784`) ; `validate_profile` conserve le plus petit plafond < 0,40 (`:673-678`) ; `plan_for` applique la borne supérieure **aux titres hors FNB** (`catalog.py:709-712`) |
| Statut | **DYNAMIC** : la valeur retenue passe par le LLM. Le code la garantit seulement si elle est absente. Je n'ai pas vérifié si Pépite peut proposer une autre valeur que celle reçue |
| Ne s'applique pas à | Un FNB (limité seulement par la limite par ligne de 40 %) ; « Tes préférences » du profil incohérent |
| Hausse | Autorise plus de concentration sur un seul titre |
| Baisse | Plus de titres, ou plus de FNB |
| Dupliquée | `engine.ts:92-101` |
| Justification DOCUMENTÉE | Aucune en dehors de l'intention (« un FNB est déjà diversifié », `pepite.py:124-126`) |
| Justification PROPOSÉE | Limiter le risque spécifique d'un seul émetteur ; le plafond croît avec l'appétit pour le risque. Avec 25 à 70 positions, 7 % à 22 % laissent la place à une vraie diversification |
| Limite | Rien ne relie ces valeurs à une mesure de risque spécifique ou de liquidité |

#### Plancher d'obligations (`BOND_FLOOR`) et interdiction de crypto (`NO_CRYPTO`)

| Constante | Valeurs | Fichier:ligne |
|---|---|---|
| `BOND_FLOOR` | conservateur 0,80 ; modéré 0,60 ; équilibré 0,40 ; dynamique 0,20 ; agressif 0,0 | `monport.py:137` |
| `NO_CRYPTO` | {conservateur, modéré} | `monport.py:141` |
| `CRYPTO_TARGETS`, `BOND_TARGETS` | ("Crypto", "Alternative") ; ("Fixed Income", "Bonds") | `monport.py:139-140` |

| Question | Réponse |
|---|---|
| Fonctions | `bond_floors(check)` (`:657-663`) ; `follow_profile` (`:571-598`) |
| Contrainte posée | `MIN_ASSET_CLASS_WEIGHT` sur « Fixed Income », `value = round(plancher, 2)`, **dure**, note « Répartition du profil » (`:595`). Pour la crypto : `EXCLUDE_ASSET_CLASS` sur « Alternative » (qui contient BTC, ETH et BITW) (`:592-593`) |
| Qui y est soumis | Profil **cohérent** : les 3 variantes (même plancher, calculé sur le S non décalé). Profil **incohérent** : « Ton profil » seulement |
| Exceptions | Obligations exclues par le client, ou classe dont le client a fixé le pourcentage : le plancher est annulé ou réduit (`:581-588`). Pourcentage de crypto fixé par le client : l'emporte sur « pas de crypto » |
| Où devient-elle une contrainte du solveur | `agent_request` → `group_limits["asset_class"]` du moteur (`catalog.py:567`, `:592`) → groupe linéaire de `build_constraint_plan` (`constraints.py:770`) |
| Assouplissable | Oui, famille « pourcentages visés » (`MIN_ASSET_CLASS_WEIGHT`, `allocator.py:582-587`) ; l'exclusion de crypto l'est à l'étape « exclusions » |
| Justification DOCUMENTÉE | Commentaire : « Répartition stratégique du profil (portefeuilles modèles 20/80 … 100/0) » (`monport.py:136`) ; pour la crypto : « pas de crypto dans un portefeuille qui suit un profil prudent » (`:141`) ; texte de cohérence : « la crypto peut perdre la moitié de sa valeur en quelques mois » (`:430`) |
| Justification PROPOSÉE | Portefeuilles modèles classiques actions/obligations (20/80, 40/60, 60/40, 80/20, 100/0). Les obligations amortissent les baisses pour un horizon court ou une faible capacité de risque. La crypto est exclue des profils prudents à cause de sa volatilité et de ses pertes extrêmes |
| Limite | Escalier : 20 points d'écart entre deux S voisins. « Alternative » inclut aussi `BITW` et d'autres titres selon le dataset. Aucun test que le plancher produit la volatilité attendue |

#### Autres constantes de profil (même logique de fiche)

| Constante | Valeur | Fichier:ligne | Rôle | DOCUMENTÉE | PROPOSÉE | Limite |
|---|---|---|---|---|---|---|
| `LINE_CAP` | 0,40 | `monport.py:132` ; `evidence.py:27` ; `engine.ts:9` | Poids maximal d'une ligne, FNB compris, jamais assoupli | Commentaire : « limite de sécurité » ; `CLAUDE.md` : « limites réglementaires… aucune ligne au-delà de 40 % ». **Aucune référence réglementaire citée** | Évite la concentration sur un seul placement ; permet à un FNB d'obligations de peser 40 % pour un profil à 80 % d'obligations (au moins 2 FNB) | Le 40 % est présenté comme réglementaire sans citation ; vérifier la source avant de l'affirmer |
| `CAPACITY_MARGIN` | 0,125 | `monport.py:148` | `S = min((C+T)/2, C + 0,125)`, soit `T ≤ C + 0,25` avant plafonnement | Commentaire : « la tolérance ne dépasse pas la capacité de plus de 3 crans sur 24 » | Principe d'adéquation : on n'investit pas bien au-delà de ce que la situation permet | Ici un « cran » vaut 1/24 ; pour Pépite, un cran vaut 0,05 (1/20) : **deux définitions du mot** |
| `OBJECTIVE_TOLERANCE` | sécuriser 0 ; fructifier 0,5 ; viser haut 1 | `monport.py:147` | Contribution de l'objectif à T | Aucune | Trois niveaux équidistants | Défaut 0,5 si l'objectif est inconnu |
| `LOSS_BY_REACTION` | 10, 15, 25, 35 (points de %) | `monport.py:128` | **Ne sert pas à S.** Définit la perte annuelle acceptée de `InvestorForm` (diagnostics, preuves « Baisse que tu acceptes ») | Commentaire : « baisse de 20 % : je vends tout … j'investis plus » | Traduit une réaction qualitative en perte acceptée | S utilise `lossReaction/3` (ordinal), pas ces pourcentages |
| `SLOT_SHIFT` | −0,1 ; 0 ; +0,1 | `monport.py:157` | Décalage de S par variante (profil cohérent) | Commentaire : « à une demi-catégorie l'une de l'autre » | ±0,1 = ±½ bande de 0,2 : trois profils distincts sans quitter la catégorie | Voir M5.3 |
| `ADJUSTMENT_STEP` | 0,05 ; ±2 crans | `monport.py:149` ; `pepite.py:243` | Ajustement de S par Pépite | Commentaire : « un cran… au plus 2 crans, une demi-catégorie » | Évite qu'un texte libre déplace S de plus d'une demi-bande | Décidé par le LLM sans règle numérique |

### M5.2 Calcul du score S et pondérations choisies

#### Questions et variables (code : `monport.py:340-359` ; `Profile.tsx` pour les bornes)

| Question | Variable | Plage de saisie (front) | Normalisation | Entre dans |
|---|---|---|---|---|
| Âge | `age` | 18 à 85 (`Profile.tsx:33`) | `a = clamp((75 − âge)/50)` : ≤ 25 ans → 1 ; ≥ 75 ans → 0 | Capacité C |
| Horizon | `horizon` | 1 à 30 ans (`Profile.tsx:84`) | `h = clamp((min(horizon,20) − 1)/19)` : 1 an → 0 ; ≥ 20 ans → 1 | Capacité C |
| Réaction à une baisse de 20 % | `lossReaction` (0 à 3) | 4 choix | `r = lossReaction/3` | Tolérance T |
| Objectif | `objective` | sécuriser / fructifier / viser haut | `o ∈ {0 ; 0,5 ; 1}` | Tolérance T |
| Aisance | `comfort` (1 à 5) | échelle de 5 | `c = (comfort − 1)/4` | Tolérance T |
| Montant, ajouts prévus | `amount`, `contribution` | — | **Ne servent pas à S** | Montants et projection seulement |

`C = 0,6 h + 0,4 a` ; `T = 0,5 r + 0,3 o + 0,2 c` ; `S = clamp(min((C + T)/2, C + 0,125) + 0,05 · clamp(adj, −2, +2), 0, 1)`. Valeurs par défaut si un champ manque : horizon 10, âge 35, `lossReaction` 2, objectif 0,5, aisance 3 (`monport.py:340-352`). **Saturation [Fait dérivé]** : un client de 75 ans ou plus a `a = 0` ; un horizon de 20 ans ou plus a `h = 1`.

**Plafond de capacité.** `S = (C+T)/2` sauf si `T > C + 0,25` ; dans ce cas `S = C + 0,125`. Le plafond ne s'applique **pas** aux crans de Pépite (ajoutés après).

#### Justification de chaque coefficient

| Coefficient | Valeur | Justification DOCUMENTÉE | Justification PROPOSÉE (non prouvée) |
|---|---|---|---|
| Horizon dans C | 0,6 | `RiskNotebook.tsx:121` : « Plus ton horizon est long et plus tu es jeune, plus tu as le temps de te remettre d'une baisse » (le texte ne donne pas les poids) | L'horizon détermine le temps de récupération après une baisse ; il compte plus que l'âge, qui n'en est qu'un indicateur |
| Âge dans C | 0,4 | idem | L'âge approxime le capital humain restant et l'horizon de vie ; recoupe en partie l'horizon, d'où un poids moindre |
| Réaction dans T | 0,5 | `RiskNotebook.tsx:135` : « Ta réaction à une baisse compte le plus » | La réaction à une perte est le meilleur indicateur de tolérance **révélée**, moins sujet aux biais d'optimisme que l'objectif déclaré |
| Objectif dans T | 0,3 | Aucune | Préférence déclarée, souvent aspirationnelle |
| Aisance dans T | 0,2 | Aucune | Familiarité avec les placements ; poids le plus faible |
| Marge 0,125 | 0,125 | Commentaire « 3 crans sur 24 » | La capacité plafonne la tolérance (principe d'adéquation) |
| Moyenne (C+T)/2 | 1/2 chacun | Aucune | Capacité et tolérance traitées symétriquement |
| Âge 75 ; diviseur 50 ; horizon 20 | 75 ; 50 ; 20 | Aucune | Bornes arbitraires de normalisation |
| ±2 crans, 0,05 | — | Commentaire « demi-catégorie » | Limite l'effet d'un texte libre sur le profil |

**Écart à signaler.** `RiskNotebook.tsx:125-141` recopie les pondérations à la main (0,6 / 0,4 / 0,5 / 0,3 / 0,2). Voir la liste « À garder synchronisé » de `CLAUDE.md`.

**Exemples chiffrés (calculés à la main).**

*Profil par défaut du front* (âge 35, horizon 12, `lossReaction` 2, « fructifier », aisance 3) : `h = 11/19 = 0,579`, `a = 0,8`, `C = 0,667` ; `r = 0,667`, `o = 0,5`, `c = 0,5`, `T = 0,583` ; `(C+T)/2 = 0,625` < `C + 0,125 = 0,792` donc `S = 0,625` → bande « dynamique ». A ≈ 3,14 ; plafond de volatilité ≈ 14,5 % ; plafond par action ≈ 13,5 % ; plancher d'obligations 20 % ; crypto permise. Variantes : A ≈ 4,53 (S = 0,525) ; A ≈ 3,14 (S = 0,625) ; A ≈ 2,06 (S = 0,725).

*Exemple de l'utilisateur* (S = 0,773) : A ≈ 1,68 ; variantes A ≈ 2,57 (S = 0,673) et A ≈ 1,29 (S = 0,873) ; plafond de volatilité 17,5 % ; plafond par action ≈ 16,5 % ; plancher d'obligations 20 % (bande dynamique).

### M5.3 Les trois variantes

```
S_prudent = clamp(S − 0,10, 0, 1)    S_fidèle = S    S_audacieux = clamp(S + 0,10, 0, 1)
```

(`slot_position`, `monport.py:545-550` ; `SLOT_SHIFT`, `:157`.) Aux extrêmes, le décalage est tronqué : à S = 0,95, la variante audacieuse a S = 1,0 (A = 1) et la fidèle A ≈ 1,11.

**Profil cohérent [Fait].** Les trois variantes partagent le **même univers, μ, Σ, plafond de volatilité, plafond par action, plancher d'obligations, pourcentages du client** (`build_profiles` : le profil « fidèle » de Pépite sert aux trois ; `bond_floors` renvoie le même plancher ; `slot_volatility` utilise le S non décalé). **Seul A diffère.** Si le plafond de volatilité est actif, `_under_cap` relève A jusqu'à 25 pour les variantes qui le dépassent : les A effectifs peuvent alors converger.

**Profil incohérent.** « Ton profil » et « Tes contraintes » ont le **même A(S)** ; elles diffèrent par leurs contraintes (voir 1.G.4). « Tes préférences » utilise `max_sharpe` (A balayé sur `A_LADDER`), sans plafond de volatilité ni plafond par action du profil. La présentation finale est composée de deux mélanges 80/20 et de « Tes contraintes ».

**Pourquoi ±0,10.** DOCUMENTÉ : « une demi-catégorie » (`monport.py:155-156`). PROPOSÉ : assez large pour que les trois A diffèrent nettement (rapport de 1,4 à 1,5 entre variantes voisines sur la plupart des segments : par exemple 4,53 / 3,14 / 2,06), assez petit pour ne pas changer de bande. `CLAUDE.md` indique que le plancher d'obligations n'a plus de décalage : « seul A distingue les variantes » (`BOND_SHIFT`, `monport.py:138`, tout à 0).

**Ce que change réellement A dans le portefeuille.** A modifie le compromis rendement-variance de l'optimum continu et le classement des titres à ajouter (utilité marginale `μᵢ − A(Σw)ᵢ`). Un A plus grand donne plus d'obligations et de titres peu volatils, sous les mêmes contraintes.

#### Les cinq grandeurs à ne pas confondre

| Grandeur | Définition | Où la lire |
|---|---|---|
| **A demandé par le profil** | `risk_aversion(S_slot)` ; `None` pour « Tes préférences » | `objective_for` (`monport.py:642-646`) ; carnet de Pépite (`RiskNotebook.tsx:290`, `:467`) |
| **A effectivement utilisé par le solveur** | A initial, puis A relevé par `_under_cap`, ou A de `_best_sharpe` | `Portfolio.diagnostics` : `A_requested`, `A_initial_optimization`, `A_effective` (`allocator.py:552`) ; **non affiché** dans l'interface (`schemas.py:222` : « jamais envoyée au frontend ») |
| **Volatilité cible** | Plafond du profil, interpolé sur `VOL_ANCHORS` (éventuellement relevé par `ensure_feasible`) | contrainte `MAX_VOLATILITY` dure ; `check.suggested_max_volatility` |
| **Volatilité réalisée** | `√(wᵀΣw)` du portefeuille final | `metrics.volatility` (`market.py:394`), affichée par `Views.tsx:135-147` |
| **Contraintes actives** | `active_bounds` : titres au plafond ; `constraints_satisfied` ; liste `relaxed` | `diagnostics` (`allocator.py:552-556`) ; `Portfolio.relaxed` |


### M5.4 Contraintes de composition du portefeuille

**Distinction essentielle.** Une contrainte **filtre l'univers** (titres retirés avant l'optimisation) ou **impose une pondération** (borne ou égalité linéaire dans le solveur). La colonne « Type » les sépare.

| Contrainte (nom technique) | Valeur actuelle | Nature | Origine | Fichier : fonction : lignes | Formulation | Type | Raison financière (PROPOSÉE sauf mention) | Assouplissement / infaisabilité |
|---|---|---|---|---|---|---|---|---|
| Budget | Σ wᵢ = 1 | Stricte | HARDCODED (structure) | `constraints.py:861-872` (`scipy_constraints`), `:875-902` (`check_linear_feasibility`) | `1ᵀw = 1` | Pondération | Portefeuille entièrement investi (le cash est désactivé) | Jamais ; erreur si somme des minima > 100 % ou des maxima < 100 % |
| Positions longues seulement | wᵢ ≥ 0 | Stricte | HARDCODED (bornes basses à 0, `constraints.py:~790`) | `build_constraint_plan` `:770` | `wᵢ ≥ 0` | Pondération | Pas de vente à découvert ni de levier (`CLAUDE.md` : « pas de levier »). Les clés `long_only`, `fully_invested` de `config.py:331-332` valent `True` mais **je n'ai pas vérifié qu'elles soient lues** | Jamais |
| Plafond par ligne (`max_position_weight`) | **0,40** | Stricte | HARDCODED (`LINE_CAP`) | `validate_profile` `monport.py:666-681` → `agent_request` `catalog.py:562` → `build_constraint_plan` | `wᵢ ≤ 0,40` | Pondération | Limite de concentration, FNB compris (DOCUMENTÉE : « limite de sécurité ») | **Jamais assouplie** (`allocator.py:602`) |
| Plafond par action en direct (`max_stock_weight`) | 7 % à 22 % selon S | Stricte, **dynamique** | DYNAMIC (LLM, sinon code) | `plan_for` `catalog.py:709-712` ; `build_profiles` `monport.py:782-784` | `wᵢ ≤ cap` pour i hors FNB | Pondération | Risque spécifique d'un émetteur | Assouplissable (famille « plafonds ») |
| Plancher d'obligations | 0 à 80 % | Stricte, conditionnelle au profil | HARDCODED (`BOND_FLOOR`) | `follow_profile` `monport.py:571-598` | `Σ_{i ∈ Fixed Income} wᵢ ≥ f(label)` | Pondération | Amortir les baisses (profils prudents) | Assouplissable (« pourcentages visés ») ; annulé si le client exclut les obligations ou fixe leur part |
| Interdiction de crypto | profils conservateur et modéré | Stricte, conditionnelle | HARDCODED (`NO_CRYPTO`) | `follow_profile` `:592-593` | `wᵢ = 0` pour la classe « Alternative » | **Filtre** | Volatilité et pertes extrêmes | Assouplissable à l'étape « exclusions » |
| Pourcentage exact de classe ou de type | saisi par le client | Stricte (égalité) | DYNAMIC (questionnaire) | `preference_constraints` `monport.py:272` → `catalog.agent_request` `:515` → `constraints._exact_groups` `:318` | `e_gᵀw = p` (tolérance d'évaluation `EXACT_TOL` 1e-3) | Pondération | Respecter le choix du client | Assouplissable (« pourcentages visés ») |
| Part régionale, thématique, sectorielle | saisi (poche actions) | Stricte (égalité) | DYNAMIC | `plan_for` `catalog.py:716-722` | `(e_g − p·e_actions)ᵀ w = 0`, avec au moins une action du groupe détenue ; seules les **actions en direct** comptent au numérateur | Pondération | Part d'une poche actions (un FNB n'a ni pays ni secteur dans le dataset) | Assouplissable |
| Exclusions (classe, type, secteur, pays, thème, symbole, facteur « Exclure ») | saisi | Stricte | DYNAMIC | `agent_request` `catalog.py:515-593`, `excluded_mask` `:621`, `universe_symbols` `allocator.py:263` | `wᵢ = 0` | **Filtre** | Valeurs du client | Assouplissable **en dernier recours** |
| Types d'instruments admissibles | mixte / FNB seulement / titres seulement | Stricte | DYNAMIC | `INSTRUMENT_SELECTION` `config.py:~65-69` ; `catalog.agent_request` | filtre par type | **Filtre** | « FNB seulement » = exclure `Stock` et `Cryptocurrency` | Assouplissable (exclusions) |
| Exposition factorielle | ±0,2 ; ±0,5 | Dure si \|niveau\| = 2 | DYNAMIC | `_factor_groups` `catalog.py:636` | `Σ wᵢ(zᵢ − s) ≥ 0` et ≥ 10 % en actions notées | Pondération | Voir M3 | Assouplissable (« pourcentages visés ») |
| Minimum par position détenue | **1 %** (0 ou ≥ 1 %) | Stricte, disjonctive | CONFIGURABLE (`min_held_weight`) | `optimize_weights` `optimizer.py:534-560` (prune/reoptimize) ; `restrict_plan` `allocator.py:284` ; `enforce_minimum` `monport.py:817` | `wᵢ = 0 ∨ wᵢ ≥ 0,01` | Pondération | Éviter les « miettes » (texte UI : « pas de miettes ») | Jamais assouplie ; si impossible : `ConstraintInfeasibleError` |
| Nombre de positions | 25 à 70 | Souple (heuristique) | CONFIGURABLE ; le `min/max_positions` du client prime | `holdings_range` `allocator.py:458-470` ; `select_holdings` `:347` | `25 ≤ card{wᵢ>0} ≤ 70` | Pondération | Diversification (voir M10) | Descend sous 25 si l'univers est trop petit ou si les 1 % sont infaisables ; note de diagnostic. `MIN/MAX_POSITIONS` assouplissables |
| Plafond de volatilité | 6 % à 25 % selon S | Dure mais **hors solveur** | HARDCODED + DYNAMIC | voir fiche M5.1 | `√(wᵀΣw) ≤ cap` | Pondération indirecte (via A) | Filet de sécurité | Relevé par `ensure_feasible` ; levé par la famille « plafonds » |
| Rendement minimal | saisi | Dure ou souple | DYNAMIC | `catalog.evaluate` ; type `MIN_EXPECTED_RETURN` | `μᵀw ≥ r` | Évaluée, non linéarisée | Aucune question du questionnaire actuel ne le produit (non vérifié) | Assouplissable |
| Cash | désactivé | — | HARDCODED (`catalog.py:605-606`) | `settings_for` | — | — | Absent du Parquet ; `Market.moments` ne saurait pas l'estimer | n/a |
| Plafonds de groupe par défaut (classes) | **aucun** en production ; `BASE_CONSTRAINTS` : alternatifs 5 %, matières premières 10 %, immobilier 15 %, crypto 5 %, TI 25 %, financières 30 %, énergie 20 %, émergents 15 % | — | `CONSTRAINTS.group_limits` vides (`config.py:~353-363`) ; BASE **inactif** (`config.py:529-559`) | — | — | — | Valeurs de simulation | n/a |
| Politique d'exposition inconnue | `strict` (mode agent) | — | CONFIGURABLE | `constraints.py:358`, `filter_eligible_universe` `:398` | rejeter les ETF dont le secteur ou le pays est inconnu face à un plafond du moteur | **Filtre** | En production, `ENGINE_DIMENSIONS = {"asset_class"}` (`catalog.py:193`) : les plafonds de secteur et de pays sont traités par `plan_for`. La politique n'a donc probablement pas d'objet ici (**déduction, non vérifié**) | — |

### M5.5 Faisabilité et assouplissements

**1. Contrôles préalables (avant l'optimisation).**

| Contrôle | Fonction | Lignes | Effet |
|---|---|---|---|
| Conflits entre contraintes dures (exclu et minimum, min > max, etc.) | `detect_conflicts` | `catalog.py:319-366` | Retire d'abord les poids minimaux (`validate_profile`, `monport.py:~676-680`) |
| Contradictions du questionnaire | `preference_contradictions` | `monport.py:388-422` | **Signalées, jamais contournées** (encadré de Pépite) |
| Poids minimaux inatteignables | `drop_unreachable_floors` | `monport.py:691-709` | Retire le plancher et note : « je n'ai pas pu en garantir une part » |
| Plafond de volatilité inatteignable | `_raise_volatility_cap` | `monport.py:720-747` | Calcule la volatilité minimale atteignable (`min_volatility` sur ≤ 40 titres) ; si elle dépasse le plafond, nouveau plafond `ceil((σ_min + 0,003) × 100)/100` |
| Faisabilité linéaire | `check_linear_feasibility` | `constraints.py:875-902` | Programme linéaire HiGHS ; sinon `ConstraintInfeasibleError` |
| Univers vide | `optimize_universe` | `allocator.py:~490-500` | Message mentionnant les titres écartés par le filtre d'historique |

**2. Relance avec limites assouplies (`optimize_with_relaxation`, `allocator.py:617-662`).**

| Étape | Contenu | Lignes |
|---|---|---|
| 0 | Seulement les contraintes que le calcul a **enfreintes** (quand il avait trouvé des poids) | `:646-650` |
| 1 « pourcentages visés » | Pourcentages exacts, minima par secteur / pays / classe / titre, parts minimales, expositions de facteurs, rendement minimal, nombre de positions | `allocator.py:581-587` |
| 2 « plafonds » | Plafonds de secteur / pays / classe / titre, parts maximales, **plafond par action**, **plafond de volatilité** ; le plafond de volatilité du **mandat** tombe aussi | `:588-592`, `:651-658` |
| 3 « exclusions » | Exclusions de secteur, pays, classe, type, titre, thème | `:593-596` |

Les étapes sont **cumulatives** (chaque relance garde les assouplissements précédents) et s'arrêtent au premier succès. `_soften` (`allocator.py:599-608`) fait passer `hard=True` à `hard=False` : l'optimiseur n'impose plus la contrainte mais `evaluate` la mesure toujours. **Jamais assouplis :** la limite par ligne (`MAX_POSITION_WEIGHT`, `allocator.py:602`), le budget, la positivité des poids, la règle de 1 %.

**Quelles limites peuvent être violées ?** Toute contrainte des familles 0 à 3, **y compris, en dernier recours, les exclusions du client**. C'est le point à connaître : `CLAUDE.md` affirme « Les exclusions du client s'appliquent aux 3 profils », ce qui est vrai tant que le premier calcul ou les relances précédentes réussissent. Si tout échoue, le portefeuille final est « Aucun portefeuille possible, même avec des limites assouplies » (`portfolio_manager.py:147`) et les autres gestionnaires continuent.

**Comment est-ce communiqué au client ?**

| Canal | Détail | Lignes |
|---|---|---|
| Écran de construction | Événement `warning`, texte « Le portefeuille « X » n'a pas pu respecter toutes tes limites… », affiché sous le titre « Limites assouplies » | `portfolio_manager.py:143`, `:187-191` ; `Pipeline.tsx:220-226` |
| Tableau de bord, mises en garde | Avertissement de gravité **haute** « Calcul relancé avec des limites assouplies », avec la liste des contraintes devenues préférences | `monport.py:1030-1037` ; `RiskNotes.tsx:9` |
| Explication du gestionnaire | Le prompt impose de le dire dans les compromis | `portfolio_manager.py:153-156` |
| Conformité | `JudgeVerdict.compliant` est calculé par le code sur les **limites d'origine** ; une limite non respectée donne l'avertissement « Certaines de tes limites ne sont pas respectées » | `monport.py:~1039-1045` ; `backend/CLAUDE.md`, règle 3 |
| Note du juge | Profil cohérent seulement : `−JUDGE_RELAUNCH_PENALTY` (3 points sur 10) ; justification de la décision ; `pick_winner` utilise la note pénalisée | `workers.py:271-273`, `:341-343` ; `monport.py:894` ; `schemas.py:243-248` |
| Plafond de volatilité relevé | Note : « L'univers de placements ne permet pas un risque aussi bas que demandé… » | `monport.py:742` |

**Comportement en cas d'infaisabilité totale.** Statut `infeasible`, `Portfolio.status = "failed"` avec `failure_reason`, carte fermée sur « Aucun portefeuille possible… ». Le pipeline ne plante pas (`backend/CLAUDE.md`, règle 6).

**Limite pour le jury.** Le 3 de `JUDGE_RELAUNCH_PENALTY` est un choix non calibré. Il ne s'applique pas au profil incohérent.

### M5.6 Tableau maître des valeurs hardcodées

Légende : **D** = documentée dans le dépôt (voir M5.1 à M5.3), **P** = proposée, **A** = aucune. Une valeur **dupliquée** est marquée ⧉ avec son autre emplacement. « Calibration » : méthode empirique envisageable (détails en M9).

| Paramètre | Valeur | Fonction | Fichier.py:ligne | Rôle financier | Justif. documentée | Justif. proposée | Hausse | Baisse | Calibration possible |
|---|---|---|---|---|---|---|---|---|---|
| Poids horizon dans C | 0,6 | `capacity` | `monport.py:344` ⧉ `engine.ts:55`, `RiskNotebook.tsx:125` | Capacité de risque | A (texte d'intro seulement) | Horizon = temps de récupération | S plus sensible à l'horizon | Moins | Régresser un jugement de conseiller sur un jeu de profils-types |
| Poids âge dans C | 0,4 | idem | idem | Capacité | A | Capital humain | idem | idem | idem |
| Âge de référence 75, diviseur 50, horizon plafonné à 20 | 75 ; 50 ; 20 | `capacity` | `monport.py:341-343` ⧉ `engine.ts` | Normalisation | A | Bornes de lecture | Décale la saturation | idem | Étudier la distribution des clients |
| Poids T (réaction/objectif/aisance) | 0,5 ; 0,3 ; 0,2 | `tolerance` | `monport.py:352` ⧉ `engine.ts:56`, `RiskNotebook.tsx:139-141` | Tolérance | D partielle (« réaction compte le plus ») | Tolérance révélée > déclarée | | | Idem |
| `OBJECTIVE_TOLERANCE` | 0 ; 0,5 ; 1 | `tolerance` | `monport.py:147` ⧉ `engine.ts:43` | Objectif | A | Équidistant | | | Idem |
| `CAPACITY_MARGIN` | 0,125 | `risk_position` | `monport.py:148` ⧉ `engine.ts:46` | Plafond de tolérance | D | Adéquation | Tolérance moins bridée | Plus bridée | Mesurer la fréquence où il plafonne |
| `ADJUSTMENT_STEP` et ±2 | 0,05 ; 2 | `risk_position`, `adjust_risk_position` | `monport.py:149` ; `pepite.py:243` | Ajustement par texte libre | D | Demi-bande max | Texte libre plus influent | Moins | Tester la stabilité du LLM sur des textes-types |
| `SLOT_SHIFT` | ±0,1 | `slot_position` | `monport.py:157` ⧉ `engine.ts:104` | Écart entre variantes | D | Demi-bande | Variantes plus éloignées | Plus proches | Mesurer l'écart de volatilité entre variantes |
| `AVERSION_ANCHORS` | 25, 14, 7, 3,5, 1,5, 1 | `risk_aversion` | `monport.py:151` ⧉ `engine.ts:69` | S → A | D partielle | Géométrique ≈ ÷2 par bande | Plus prudent | Plus audacieux | A ↔ volatilité réalisée (M9.4) |
| `VOL_ANCHORS` | 6 à 25 % | `assess`, `slot_volatility` | `monport.py:152` ⧉ `engine.ts:92` | Plafond de σ | D (« filet ») | 60/40 ≈ 10 % | Plus de risque permis | A relevé plus tôt | Distribution de σ réalisée ; stress |
| `STOCK_ANCHORS` | 7 à 22 % | `assess` | `monport.py:153` ⧉ `engine.ts:92` | Plafond par action | A | Risque spécifique | Concentration | Plus de titres | Contribution au risque par titre |
| `BOND_FLOOR` | 0,8 ; 0,6 ; 0,4 ; 0,2 ; 0 | `follow_profile` | `monport.py:137` ⧉ `engine.ts:92` | Plancher d'obligations | D (« 20/80 … 100/0 ») | Portefeuilles modèles | Plus d'obligations | Moins | Frontière efficiente par bande |
| `NO_CRYPTO` | 2 bandes | `follow_profile` | `monport.py:141` ⧉ `engine.ts:92` | Pas de crypto | D | Pertes extrêmes | — | — | Scénarios de crise |
| `LINE_CAP` | 0,40 | `validate_profile` | `monport.py:132` ⧉ `evidence.py:27`, `engine.ts:9` | Concentration | D | Concentration | Plus de concentration | Plus de lignes | Nombre minimal de FNB nécessaires par bande |
| `LOSS_BY_REACTION` | 10 ; 15 ; 25 ; 35 % | `to_form` | `monport.py:128` ⧉ `engine.ts:303` | Perte acceptée (diagnostics) | D | Traduction | Seuils plus lâches | Plus stricts | Enquête de clientèle |
| Seuils de cohérence | 40 ; 65 ; 77 ; 0,7 ; 0,3 | `coherence_facts` | `monport.py:424-443` ⧉ `engine.ts:306-323` | Détecter les incohérences | A | Garde-fous de bon sens | | | Cas-types annotés |
| `RISK_AVERSION` min/max | 1 ; 25 | `apply_portfolio_request` | `config.py:310-311` ⧉ `allocator.py:45`, `schemas.py:318` | Bornes de A | A | Étendue de l'échelle | | | Cohérence avec les ancres |
| `MIN_POSITION_WEIGHT` / `min_held_weight` | 0,01 | `optimize_weights`, `enforce_minimum` | `allocator.py:44` ⧉ `config.py:280`, `:334` | Pas de miettes | D | Frais fixes, lisibilité | Moins de positions | Plus de petites lignes | Coût d'utilité par position |
| `PORTFOLIO_HOLDINGS` | 25 ; 70 ; 0,0001 | `select_holdings` | `config.py:278-283` | Nombre de positions | **D empirique** (« mesuré sur un univers synthétique de 769 titres : ≈ 28 titres par Markowitz seul, arrêt vers 45 à 50 ») | — | Plus de positions | Moins | Refaire sur l'univers réel |
| Lots de sélection | 10 ; 5 | `select_holdings` | `allocator.py:391`, `:426` | Pas de recherche | A | Vitesse | | | Sensibilité |
| `A_LADDER` | 10 valeurs | `_best_sharpe`, `_under_cap` | `allocator.py:47` | Grille de A | A | Grille géométrique | Plus fin | Plus grossier | Comparer à une résolution continue |
| `CAP_REFINEMENTS` | 6 | `_under_cap` | `allocator.py:48` | Précision du plafond | D | 2⁻⁶ du segment | | | — |
| Marge de relèvement du plafond | +0,003 | `_raise_volatility_cap` | `monport.py:745` | Marge d'arrondi | A | Tolérance | | | — |
| SLSQP | maxiter 2000 ; ftol 1e-9 | `_solve_slsqp` | `config.py:417-418` | Précision | A | Standard | | | — |
| Tolérances | 1e-7 ; 1e-8 ; 1e-9 ; 2e-4 ; 1e-3 ; 5e-4 | divers | `config.py:421-422`, `catalog.py:67-69`, `:154` | Numérique | D (commentaires) | — | | | — |
| `MAX_ASSETS_PER_PORTFOLIO` | 40 | `_check_selection` | `runtime.py:49` | Taille de sélection | A | Temps de calcul | | | — |
| `JUDGE_RELAUNCH_PENALTY` | 3 pts sur 10 | `_penalty` | `config.py:289` | Pénalise l'assouplissement | D | Équité entre variantes | | | Sensibilité du choix du gagnant |
| `BLEND` | 0,8 | `blend` | `monport.py:56` | Mélange cœur-satellite | A | Cœur-satellite classique | | | — |
| `λ_D`, `λ_V`, seuil | 0 ; 0 ; 25 % | `_solve_slsqp` | `config.py:406-408` | Régularisation | D (nulles) | Ridge | | | M9.3 |
| `RF_ANNUAL` | 3,5 % | `market.py` | `config.py:94` ⧉ copies `:132`, `:141` | Taux sans risque | D (démonstration) | Taux CAD court terme | | | Courbe de taux de la Banque du Canada |
| `erp_annual` | 5 % | `estimate_expected_returns` | `config.py:133` | Prime de risque | D (illustrative) | Ordre de grandeur de la prime historique | | | Sources académiques ; historique |
| `alpha` | 0,50 | idem | `config.py:134` ; `:142` | Rétrécissement | A | Moyenne équipondérée | | | Validation hors échantillon |
| `market_proxy` | SPY | idem | `config.py:131` | Benchmark | D (« baseline unique ») | Indice liquide | | | Benchmarks par région |
| `half_life_observations` | 90 | `_ewma_mu` | `config.py:124` | Mémoire EWMA | A | ≈ 4 mois | | | Validation croisée |
| `min_observations` | 120 | plusieurs | `config.py:39`, `:120`, `:125`, `:130`, `:235` ; `data.py:426` | Seuil d'historique | A | ≈ 6 mois | | | — |
| `periods_per_year` | 252 | plusieurs | `config.py:40` ⧉ `backtest.py:27` | Annualisation | A | Séances | | | — |
| `COVARIANCE_HISTORY` | 2021-01-01 ; 5 jours | `history_filter` | `config.py:265-268` | Univers admissible | D opérationnelle (Σ sinon limitée à quelques mois) | Historique commun | | | Sensibilité à la date |
| `LOOKBACK_YEARS` | 6 | `backtest` | `backtest.py:26` | Fenêtre | A | Historique disponible | | | — |
| `YEAR` ; `BIWEEKLY` ; `SAMPLE_EVERY` | 252 ; 10 ; 5 | backtest | `backtest.py:27-29` | Annualisation, fréquence, échantillonnage | A | — | | | — |
| `DAILY_STEP`, `DAILY_LIMIT` | 0,5 ; 5,0 | `daily_distribution` | `backtest.py:30-31` | Histogramme | D (commentaires) | — | | | — |
| Quantile VaR/ES | 5 % | `summarize` | `backtest.py:106` | Risque de queue | A | Convention 95 % | | | — |
| `PATHS`, `SEED` | 1000 ; 7 | `project` | `projection.py:21-22` | Simulation | D (« reproductible ») | — | | | M7 |
| Horizon, percentiles | 10 ans ; 5, 25, 75, 95 | `project` | `projection.py:38`, `:67` | Cônes | D (docstring : ±0,67 σ et ±1,645 σ) | — | | | — |
| Z de la pire année | 2,33 ; 1,645 ; 2,063 | `to_portfolio` | `monport.py:1054-1060` ⧉ `evidence.py:28`, `engine.ts:269-274` | VaR et ES normaux | D (« 1 chance sur 100 ») | Quantiles normaux | | | Comparer à l'historique |
| `FEES` | 0,002 (FNB) | `to_portfolio` | `monport.py:131` | Frais | D (« faute de donnée ») | — | | | Frais réels des FNB |
| Seuils de `diagnostics` | 35 % ; 70 % ; 5 % ; 8 ; 15 % | `diagnostics` | `diagnostics.py` | Faits pour agents Risque | A | Conventions | | | — |
| Constantes de facteurs | voir M3.4 | — | `catalog.py:154-158`, `monport.py:113` | Facteurs | D partielle | — | | | M9.5 |

**Doublons à signaler.** Backend et front-end : `AVERSION_ANCHORS`, `VOL_ANCHORS`, `STOCK_ANCHORS`, `BOND_FLOOR`, `NO_CRYPTO`, `SLOT_SHIFT`, `OBJECTIVE_TOLERANCE`, `CAPACITY_MARGIN`, `LOSS_BY_REACTION`, `LINE_CAP`, poids de C et T, seuils de cohérence, `FACTOR_LEVELS`, constantes de VaR. Seulement dans le backend : `min_held_weight` (4 copies), bornes de A (3), seuil « position détenue » (5 valeurs). `CLAUDE.md` (« À garder synchronisé ») liste ces paires comme **synchronisées à la main**.


---

## M6. Backtesting : méthodologie et limitations

**Fichier :** `ia/backtest.py`. **Appel :** `to_portfolio` → `backtest(market.returns, {symbole: poids}, market.risk_free_rate)` (`monport.py:1065`), après le juge. Les agents Risque et le juge ne reçoivent pas ces résultats.

### M6.1 Méthode (vérifiée ligne par ligne)

| Élément | Implémentation | Lignes |
|---|---|---|
| Historique | `Market.returns` : rendements quotidiens simples `total_return_cad` en CAD (dividendes réinvestis), par titre. Fenêtre : les `LOOKBACK_YEARS = 6` dernières années avant la date maximale, puis début à la première date avec au moins un rendement | `backtest.py:121-131` |
| Historique minimum | Moins de 252 jours (`YEAR`) : le backtest renvoie `None` | `backtest.py:129-130` |
| Poids | **Poids finaux du portefeuille** (arrondis à 4 décimales), appliqués dès le premier jour, normalisés à 100 % | `backtest.py:133-134` |
| Rendement du portefeuille | `Σ wᵢ rᵢ` par jour ; les poids dérivent : `w ← w(1+r)/(1+r_p)` | `simulate`, `backtest.py:51-67` |
| Rééquilibrage | `deux-semaines` : un jour sur 10 ; `mensuelle` : premier jour de chaque mois ; `annuelle` : premier jour de chaque année ; `aucune` : jamais. Toujours le premier jour. 4 simulations par appel | `rebalance_mask`, `:34-48` |
| Titre pas encore coté | Son poids est réparti au prorata sur les autres, avec un rééquilibrage le jour de sa première cotation | `:131-132`, `simulate` `:55-58` |
| Données manquantes | `fillna(0.0)` : un jour sans cours d'un titre déjà coté (férié de son marché) compte comme **rendement nul** ; aucun remplissage avant la première cotation (masque `listed`) | `backtest.py:131-132`, `:135`, docstring `:10-11` |
| Valeur cumulée | `100 × Π(1 + r_p)` | `summarize` `:86` |
| Rendement annualisé | **Géométrique** : `(V_fin/100)^(252/n) − 1` | `:88-89` |
| Volatilité réalisée | `std(r_p, ddof=1) × √252` | `:90` |
| Sharpe réalisé | `(rendement annualisé géométrique − rf) / volatilité`, `rf = 3,5 %` | `:99` |
| Pire recul | `min(V / max cumulé − 1)` quotidien | `:91-92` |
| Pire et meilleure période de 12 mois | `V / V.shift(252) − 1` (rendements glissants) | `:93`, `:110` |
| VaR historique 95 % (1 jour) | `−quantile(r_p, 5 %)` | `:106-107` |
| Expected Shortfall 95 % | `−moyenne des r_p tels que r_p ≤ q` | `:107` |
| Distribution | Histogramme des rendements quotidiens, tranches de 0,5 point entre −5 % et +5 % (extrêmes dans les tranches des bouts) ; tranche de la VaR et inférieures marquées `tail` | `daily_distribution` `:70-81` |
| Série pour le graphique | Un point par semaine (`SAMPLE_EVERY = 5`) : valeur, rendement cumulé, recul | `:112-118` |
| Dates | `start` et `end` renvoyés au front | `:137-138` |
| Frais, coûts de transaction, taxes | **Aucun** | — |

### M6.2 Paramètres choisis manuellement (HARDCODED)

| Paramètre | Valeur | Ligne | Justification |
|---|---|---|---|
| `LOOKBACK_YEARS` | 6 | `backtest.py:26` | AUCUNE. Le dataset commence en 2021 (`CLAUDE.md` backend : « jours ouvrables depuis 2021 ») ; la fenêtre de 6 ans ne tronque probablement presque rien (**non vérifié**, dépend de la dernière date) |
| `YEAR` | 252 | `:27` | Convention de séances ; indépendant de `DATA.periods_per_year` |
| `BIWEEKLY` | 10 séances | `:28` | « Aux deux semaines » ≈ 10 séances ; approximation (ne suit pas le calendrier) |
| `FREQUENCIES` | 4 fréquences | `:25` | Alignées sur celles des ajouts du client (`ContributionFrequency`, `types.ts`) |
| `SAMPLE_EVERY` | 5 | `:29` | Un point hebdomadaire pour alléger le graphique |
| `DAILY_STEP`, `DAILY_LIMIT` | 0,5 ; 5,0 | `:30-31` | Largeur des tranches et bornes de l'histogramme |
| Quantile | 5 % | `:106` | Convention VaR/ES 95 % |
| `rf` | 3,5 % | `RF_ANNUAL` | Hypothèse de démonstration |

### M6.3 Les poids sont-ils calculés ex ante ou ex post ? — **Ex post**

**[Fait]** Les poids appliqués au premier jour du backtest sont ceux d'un portefeuille optimisé avec **toute** l'information disponible : μ historique sur tout l'historique de chaque titre, Σ depuis 2021 sur les mêmes dates, scores de facteurs d'aujourd'hui (si demandés), et univers (titres encore cotés aujourd'hui, avec 1 527 jours d'historique). Le backtest réapplique ces poids sur la même période. **Il y a donc un biais d'anticipation (look-ahead) et un biais d'optimisation sur l'échantillon** : le résultat est **rétrospectif**, pas une performance qu'un investisseur aurait pu obtenir en temps réel.

**[Fait]** Le projet le reconnaît à l'écran : `BacktestWarning` (`charts.tsx:141-155`) : « Simulé sur des données passées, avec un historique limité : les résultats peuvent être biaisés » ; `BacktestNote` (`charts.tsx:132-139`) donne la période ; `CLAUDE.md` dit que chaque graphique « rappelle qu'il est flatteur (placements choisis avec ces mêmes données) ».

**Autres biais probables.**

- **Survie** : l'univers est bâti à partir de listes actuelles (Wikipédia + yfinance, `CLAUDE.md`, commandes) ; les titres disparus n'y sont pas. **Non vérifié** ligne par ligne dans `build_universe.py`.
- **Facteurs** : photo d'aujourd'hui (`FACTORS.md` : « ne peuvent pas servir à un backtest historique sans anticipation »).
- **Période courte** (~6 ans) : peu de régimes, forte influence de 2021-2026.
- **Pas de frais ni de transaction**, `FEES` n'étant pas utilisé.
- **Sharpe non comparable** : le Sharpe du backtest (rendement **géométrique** réalisé) diffère du Sharpe du portefeuille affiché dans la carte « Rendement attendu » (`μ` **arithmétique estimé** sur `σ` de Σ). L'interface affiche les deux (`Views.tsx:132`, `:297`) sans les distinguer.

### M6.4 Comment implémenter un vrai backtest walk-forward (sans modifier le code ici)

1. Fixer des dates de rééquilibrage `t₁ < t₂ < … < t_K` (par exemple mensuelles).
2. À chaque `t_k`, **n'utiliser que les données ≤ t_k** : construire l'univers (titres existants à `t_k`), estimer μ et Σ (`market.estimate_expected_returns`, `ledoit_wolf_universe`) sur une fenêtre passée uniquement, avec les contraintes et le S **du client à cette date**.
3. Optimiser (`allocator.optimize_universe`) et fixer les poids.
4. Tenir les poids de `t_k` à `t_{k+1}` et enregistrer les rendements **suivants** (hors échantillon).
5. Chaîner les rendements hors échantillon, puis calculer les mêmes indicateurs (`summarize`).
6. Ajouter frais et coûts de transaction, comparer à un indice de référence et à un portefeuille équipondéré.
7. Pour les facteurs : utiliser des scores **datés** (point-in-time).
8. Valider les hyperparamètres (α, demi-vie, ancres) par validation croisée emboîtée, jamais sur la période d'évaluation.

Coût : chaque optimisation prend des secondes (diagnostics `seconds_total`), un walk-forward mensuel sur 5 ans demande environ 60 optimisations par portefeuille.

---

## M7. Simulations de patrimoine (projection sur 10 ans)

**Fichier :** `ia/projection.py`. **Appel :** `to_portfolio` → `projection_view(montant, contribution, μ, σ)` (`monport.py:1069`), où μ = `metrics.expected_return` et σ = `metrics.volatility` du portefeuille (optimiseur).

### M7.1 Méthode exacte (`project`, `projection.py:38-56`)

Pour chaque période `n` (= versements par an : 26, 12, 1 ; 12 si aucun ajout) et chaque année :

```
drift  = μ / n
spread = σ / √n
valeur_trajectoire ← valeur × (1 + drift + spread × Z) + versement,   Z ~ N(0, 1)
valeur_attendue    ← valeur_attendue × (1 + drift) + versement
```

| Élément | Valeur |
|---|---|
| Génération aléatoire | `numpy.random.default_rng(seed)` ; `rng.standard_normal(paths)` à chaque période (`projection.py:46`, `:54`) |
| Nombre de trajectoires | `PATHS = 1000` (`:21`) |
| Graine | `SEED = 7` (`:22`) : résultat reproductible ; les trois portefeuilles utilisent les **mêmes** tirages (graine identique) |
| Horizon | `years = 10` (`project`, `:38`) |
| Percentiles | 5, 25, 75, 95 (`np.percentile`, `:67`) ; le front les nomme « fourchette probable (50 %) » (25-75) et « fourchette large (90 %) » (5-95) |
| Versements | ajoutés en fin de période, après la croissance ; fréquence et montant validés par `clean_contribution` (montant ≤ 10 000 000, `:23`) |
| Fréquences | `PER_YEAR = {deux-semaines 26, mensuelle 12, annuelle 1, aucune 12}` (`:20`) |
| Distribution | **Normale** i.i.d. par période, μ et σ **constants** et **uniques au niveau du portefeuille** |
| Dépendance temporelle | Aucune (rendements indépendants d'une période à l'autre) |
| Corrélations | Non modélisées : la corrélation entre titres est déjà dans σ du portefeuille (via Σ), mais aucune trajectoire par titre n'est simulée |
| Frais, inflation, impôt | **Aucun** (`FEES` n'est pas utilisé) |
| Incertitude sur μ et σ | **Aucune** : les paramètres sont traités comme connus |
| Annualisation | μ et σ annuels divisés par `n` et `√n` (hypothèse d'indépendance) |

**Est-ce du Monte Carlo ? Oui.** Il y a une génération aléatoire de trajectoires (`rng.standard_normal`) et des centiles sur les trajectoires. C'est un Monte Carlo **paramétrique gaussien**, non historique.

### M7.2 Pourquoi ces choix sont raisonnables, et discutables

| Choix | Raisonnable parce que (PROPOSÉ) | Discutable parce que |
|---|---|---|
| 1 000 trajectoires | Assez pour des centiles centraux stables à l'écran ; reproductible | L'erreur d'échantillonnage du 5ᵉ centile est d'environ ±0,7 point de probabilité (`√(0,05·0,95/1000)`) ; environ 10 trajectoires seulement dans la queue de 1 %. Les événements extrêmes ne sont pas bien représentés. De toute façon, la loi normale supprime les queues épaisses |
| Graine 7 | Résultat identique pour un même client ; comparaisons cohérentes entre portefeuilles | Un seul tirage : l'erreur de simulation n'est pas visible. L'impression de précision vient de la graine fixe |
| Horizon 10 ans | Horizon de lisibilité pour le client | Fixe, quel que soit l'horizon déclaré du client |
| Percentiles 5-25-75-95 | Les quantiles sont simples à lire | Aucune probabilité de ruine ni de perte en capital n'est calculée |
| Normale i.i.d. | Standard pour une projection grand public | Ignore la volatilité stochastique, les queues épaisses, l'autocorrélation, la dépendance entre μ et σ |
| μ et σ constants | Simplicité | Le μ est estimé avec beaucoup d'erreur (M2.1) ; sur 10 ans, l'incertitude sur μ domine souvent celle du bruit annuel |
| Pas de frais | Pas de donnée de frais | Les frais d'un FNB réduisent le rendement net ; ils ne sont pas inclus alors qu'ils sont calculés |

**Écart entre la ligne « rendement moyen » et le centre du cône.** La ligne « Rendement moyen » est la **moyenne** (capitalisation de μ). Pour une loi log-normale, la **médiane** est plus basse que la moyenne à cause de l'effet de la volatilité (`≈ σ²/2` par an). Exemple analytique (calculé à la main, non issu du code) : μ = 7 %, σ = 12 %, 10 ans, sans versement. Moyenne : 1,07¹⁰ ≈ 1,97. Médiane ≈ exp((0,07 − 0,0072) × 10) ≈ 1,87. 5ᵉ centile ≈ exp(0,628 − 1,645 × 0,12 × √10) ≈ 1,00. Le docstring affirme que « le cône est centré sur le rendement attendu » : c'est vrai en espérance, pas pour la médiane.

### M7.3 Affichage front-end

`ProjectionChart` (`Views.tsx:157-203`) : zones « Fourchette large (90 %) » et « Fourchette probable (50 %) », ligne « Rendement moyen », ligne « Montant versé », texte « Dans 10 ans : ≈ … ». Montée seulement dans le niveau **Intermédiaire** (`Views.tsx:260`) ; **absente du niveau Avancé**. Sans backend : `NeedsBackend` (« Calculé par le serveur »).

---

## M8. Cartographie backend → frontend

**Légende de la colonne « Visible ? »** : **V** = visible, calculé par le backend ; **V-F** = visible mais **recalculé ou dupliqué** dans le front ; **D** = visible seulement en mode démonstration ; **U** = utilisé par le code mais non affiché ; **G** = présent seulement dans les diagnostics.

| Concept | Paramètre | Fonction Python | Fichier backend | Donnée API | Composant front | Écran / niveau | Visible ? |
|---|---|---|---|---|---|---|---|
| Questionnaire | âge, horizon, réaction, objectif, aisance, montant, ajouts | `to_form` | `monport.py:314` | requête `profile`, `contribution` (`api.ts:129`, `:165`) | `Profile.tsx:33-110` | Questionnaire | V (saisie) |
| Score S | S | `risk_position`, `assess` | `monport.py:355`, `:528` | `check.risk_position` | `RiskNotebook.tsx:32`, `:253` ; secours `riskBreakdown` | Vérification | V-F |
| Capacité C | C | `capacity` | `monport.py:340` | non transmise (Pépite l'explique via `risk_breakdown`) | `RiskNotebook.tsx:119-131` | Vérification | V-F (calcul front) |
| Tolérance T | T | `tolerance` | `monport.py:347` | idem | `RiskNotebook.tsx:133-147` | Vérification | V-F |
| Aversion au risque A | A | `risk_aversion` | `monport.py:370` | `check.risk_aversion` | `RiskNotebook.tsx:290`, `:467`, `:267` | Vérification | V-F |
| Étiquette de risque | `risk_label` | `risk_label`, `front_score` | `monport.py:375`, `:384` | non transmise | `Transition.tsx:31`, `Pipeline.tsx:169`, `engine.ts:114` | Transition, Construction | V-F (calcul front seulement) |
| Limite de volatilité | `VOL_ANCHORS` | `assess`, `slot_volatility` | `monport.py:528`, `:552` | `check.suggested_max_volatility` (champ générique, **non lu** par le front) | `RiskNotebook.tsx:417` via `profileLimits` | Vérification | V-F |
| Plafond par action | `STOCK_ANCHORS` | `assess` | `monport.py:528` | `check.suggested_max_position_weight` (non lu) | `RiskNotebook.tsx:416` via `profileLimits` | Vérification | V-F |
| Plancher d'obligations | `BOND_FLOOR` | `bond_floors`, `follow_profile` | `monport.py:657`, `:571` | non transmis | `RiskNotebook.tsx:343`, `:412` (approximation locale) | Vérification | V-F |
| Interdiction de crypto | `NO_CRYPTO` | `follow_profile` | `monport.py:571` | non transmise | `RiskNotebook.tsx:414` | Vérification | V-F |
| Contraintes choisies | pourcentages, exclusions | `preference_constraints` | `monport.py:272` | requête `constraints` | `Preferences.tsx`, `RiskNotebook.tsx:336-389` | Préférences, Vérification | V (saisie) |
| Cohérence profil/préférences | seuils 40, 65, 77 | `coherence_facts` | `monport.py:424` | `check.coherent`, `issues` | `Preferences.tsx:61` (front), `Verification.tsx` (backend) | Préférences, Vérification | V-F |
| Rendement espéré | `metrics.expectedReturn` | `portfolio_metrics`, `to_portfolio` | `market.py:394`, `monport.py:996` | `metrics.expectedReturn` | `Views.tsx:51`, `:128-134`, `Dashboard.tsx:80` | Tous niveaux | V |
| Volatilité | `metrics.volatility` | idem | idem | `metrics.volatility` | `Views.tsx:135-147` | Intermédiaire, Avancé | V |
| Volatilité mensuelle | σ/√12 | `to_portfolio` | `monport.py:1054` | `metrics.monthlyVolatility` | `Views.tsx:142` | Avancé | V |
| Sharpe (optimiseur) | `metrics.sharpe` | `portfolio_metrics` | `market.py:~416` | `metrics.sharpe` | `Views.tsx:132` | Avancé | V |
| Sharpe (backtest) | `stats.sharpe` | `summarize` | `backtest.py:99` | `backtest.runs[f].stats.sharpe` | `Views.tsx:297` | Avancé, Performance | V |
| Pire année | μ − 2,33σ | `to_portfolio` | `monport.py:1055` | `metrics.worstYear` | `Views.tsx:59-64`, `:148-153` | Tous niveaux | V |
| Allocation | `allocation` | `front_allocation` | `monport.py:983` | `allocation` | `AllocationBar`, `parts.tsx:20` | Débutant | V |
| Positions | `holdings` | `holding_meta` | `monport.py:964` | `holdings[]` | `HoldingsTable`, `parts.tsx:70` | Intermédiaire, Avancé | V |
| Expositions sectorielles et régionales | `breakdown` | `breakdowns` | `monport.py:1079` | `breakdown` | `Breakdown`, `charts.tsx:99` | Tous niveaux | V |
| Facteurs | `factors` | `factor_view` | `monport.py:1117` | `factors` | `FactorExposure`, `Factors.tsx:214` | Avancé, Risque | V |
| Contribution au risque | `riskContribution` | `risk_by_class` | `monport.py:1095` | `riskContribution` | `RiskTab`, `Views.tsx:376` | Avancé, Risque | V |
| Backtest | `backtest` | `backtest` | `backtest.py:121` | `backtest.runs[f]` | `PerformanceTab`, `Views.tsx:277` | Avancé, Performance | V |
| Distribution des rendements | `distribution` | `daily_distribution` | `backtest.py:70` | `backtest.runs[f].distribution` | `DistributionChart`, `Views.tsx:206` | Intermédiaire, Avancé | V |
| VaR et ES 95 % (1 jour) | `var95`, `es95` | `summarize` | `backtest.py:106-107` | `stats.var95`, `stats.es95` | `Views.tsx:151`, `:239-240` | Intermédiaire, Avancé | V (signe inversé à l'affichage) |
| VaR et ES annuels normaux | `metrics.var95`, `es95` | `to_portfolio` | `monport.py:1059-1060` | `metrics.var95`, `es95` | **non affichés** dans les vues lues | — | U |
| Maximum drawdown | `maxDrawdown` | `summarize`, `portfolio_metrics` | `backtest.py:92`, `market.py:394` | `stats.maxDrawdown`, `metrics.maxDrawdown` | `Views.tsx:141`, `:298` | Avancé | V |
| Simulations et projections | `projection` | `projection_view` | `projection.py:59` | `projection.rows` | `ProjectionChart`, `Views.tsx:157` | Intermédiaire | V |
| Montants | `amounts` | `amounts_view` | `monport.py:1073` | `amounts` | `Views.tsx:52-55`, `:61-64` ; `parts.tsx:107` | Tous niveaux | V |
| Rapports des agents | `agentNotes` | `to_portfolio` | `monport.py:1027-1031` | `agentNotes` | `AgentNotes`, `parts.tsx:117` | Intermédiaire, Avancé | V |
| Avertissements du responsable des risques | `warnings` | `evidence_for`, `to_portfolio` | `monport.py:992`, `:1030+` | `warnings[]`, `sources` | `RiskNotes.tsx:9` ; `Evidence.tsx:5` | Tous niveaux | V |
| Preuves macroéconomiques | `sources` (macro) | `macro_evidence` | `evidence.py:131` | `warnings[].sources` | `Evidence.tsx:5` | Tous niveaux | V (si citées) |
| Relance avec limites assouplies | `relaunch_reason`, `relaxed` | `optimize_with_relaxation` | `allocator.py:617` | événement `warning`, `warnings[]` | `Pipeline.tsx:220-226`, `RiskNotes.tsx` | Construction, Tableau de bord | V |
| Pénalités λ_D et λ_V | `REGULARIZATION` | `regularization_penalty` | `optimizer.py:404` | — | — | — | **U** (nulles) |
| A effectif, volatilité visée | `A_effective` | `optimize_universe` | `allocator.py:552` | non envoyé (`schemas.py:222`) | — | — | **G** |
| Frais | `metrics.fees` | `to_portfolio` | `monport.py:1051+` | `metrics.fees` | aucun composant ne le lit | — | U |
| μ, σ individuels ; Σ ; β | estimations | `estimate_expected_returns` | `market.py:79` | — | — | — | U |
| Note du juge, pénalité | `fit_score`, `penalty` | `_verdict`, `pick_winner` | `workers.py:257`, `monport.py:894` | `justification` (texte) | non vérifié | Tableau de bord (cohérent) | U (chiffres non affichés) |
| Mode démonstration | métriques d'exemple | — | — | — | `engine.ts:255-276`, `catalog.ts:230-270` | Hors ligne | **D** |

**Valeurs affichées seulement en mode démonstration :** `metricsOf` (`rf 0,025`, `ρ 0,3`, drawdown `−min(0,9 ; 2,2σ)`), preuves d'exemple (`evidenceOf`), script d'événements (`runScript`), règles de chat (`proposeAdjustment`). **Calculs front dupliquant le backend :** voir Partie 2, tableau 3.B.

**Synchronisation documentée mais non testée automatiquement.** `CLAUDE.md` (« À garder synchronisé ») liste les paires backend/front. J'ai trouvé des tests backend pour le backtest, la projection, les répartitions et les facteurs (`backend/tests/test_backtest.py`, `test_dashboard_numbers.py` selon `CLAUDE.md`), mais **pas de test de parité** des constantes de profil entre `monport.py` et `engine.ts` (le dossier de tests du front n'a pas été exploré).


---

## M9. Limitations, calibration et analyses de sensibilité

> **Statut.** Toute cette section est **[Reco]** : ce sont des propositions de tests, non des résultats. Aucun résultat empirique n'est avancé. Les tests supposent l'accès au dataset réel (`universe.parquet`).

### M9.1 Rendements espérés

**Limitation actuelle.** Une méthode par **classe** (CAPM rétréci pour les actions, moyenne historique pour le reste, EWMA pour la crypto), choisie à la main. Le commentaire `config.py:101-103` annonce une comparaison hors échantillon qui n'est pas dans le dépôt.

**Pistes de choix titre par titre.** Longueur de l'historique (peu d'observations : plus de rétrécissement), volatilité (forte : rétrécir davantage), stabilité des rendements, sensibilité au marché (β proche de 0 : CAPM peu informatif), nature de l'instrument, régime récent (EWMA).

**Protocole proposé (sans présumer qu'une méthode gagne).**

1. Rolling-origin : à chaque date `t`, estimer μ par chaque méthode avec les données ≤ `t`.
2. Comparer à l'horizon 12 mois : corrélation de rang (Spearman) entre μ prévu et rendement réalisé, erreur quadratique, et utilité réalisée d'un portefeuille optimisé avec chaque μ.
3. Faire varier α dans {0 ; 0,25 ; 0,5 ; 0,75 ; 1}, la demi-vie dans {30 ; 60 ; 90 ; 180}, ERP dans {3 % ; 4 % ; 5 % ; 6 %}.
4. Inclure une référence « aucune information sur μ » (μ égal pour tous) pour voir si le μ estimé aide réellement.

**Réserve.** Avec ~6 ans de données, la puissance statistique est faible.

### M9.2 Covariance

| Sujet | Test proposé |
|---|---|
| Horizon | Comparer Σ estimée sur tout l'historique, 2021+ (actuel), les 3 dernières années. Évaluer la variance prévue contre réalisée d'un portefeuille à variance minimale sur la période suivante |
| Ledoit-Wolf | Comparer à la covariance brute, à un rétrécissement vers corrélation constante, à une méthode OAS ; mesurer le conditionnement et la perte de Frobenius hors échantillon |
| Annualisation | Mesurer `periods_per_year_effective` (diagnostic existant) et comparer `√Σᵢᵢ` à `ann_vol` titre par titre ; décider d'une convention unique |
| Observations extrêmes | Estimer avec rendements winsorisés (ex. 1 %/99 %) et comparer aux plafonds de volatilité atteints |
| Robustesse hors échantillon | Comparer la volatilité prédite et réalisée de chaque portefeuille construit à des dates passées (walk-forward) ; biais = prédite / réalisée |

### M9.3 Pénalités de régularisation

| Question | Protocole |
|---|---|
| Calibrer λ_D | Grille de λ_D sur un échelle logarithmique (ex. 10⁻⁴ à 10⁻¹). Pour un jeu de profils-types et chaque A, mesurer : nombre effectif de positions (1/HHI), poids des 5 premières positions, rendement espéré perdu (`Δμ`), volatilité, turnover. Choisir λ_D tel que le nombre effectif augmente d'une cible donnée pour un `Δμ` borné |
| Calibrer λ_V | Idem, avec la part de portefeuille dans les titres de volatilité > seuil |
| Seuil de 25 % | Tester {15 ; 20 ; 25 ; 30 %} ; vérifier la fraction de l'univers pénalisée (selon la base d'annualisation de Σ, voir M2.2) |
| Interaction avec A | Rappeler que le terme ajouté est `2λ/A` : comparer à A fixe et à plafond de volatilité actif |
| Concentration effective et contributions au risque | Suivre `effective_n` et la contribution d'Euler par classe avant/après |
| Dégradation du rendement | Mesurer `Δμ` et Sharpe réalisé ex ante |

### M9.4 Profils et contraintes hardcodées

| Valeur | Test de sensibilité | Méthode empirique possible |
|---|---|---|
| S → A (`AVERSION_ANCHORS`) | Pour S ∈ {0 ; 0,1 ; … ; 1}, optimiser sans plafond et rapporter la volatilité obtenue | Vérifier que la volatilité décroît de façon régulière avec A et que A=1 reste réaliste (A=1 donne presque la frontière à rendement maximal) |
| S → volatilité max (`VOL_ANCHORS`) | Comparer `VOL_ANCHORS(S)` à la volatilité du portefeuille optimal à `A(S)` **sans** plafond | Idéal : plafond légèrement **au-dessus** de cette valeur pour que le plafond agisse en filet, pas en contrainte active. Mesurer la fréquence de relèvement de A par `_under_cap` |
| S → plafond par action (`STOCK_ANCHORS`) | Fréquence des titres au plafond (`active_bounds`) ; contribution au risque du plus gros titre | Choisir le plafond pour limiter la contribution d'un titre à X % de la variance |
| `BOND_FLOOR` | Frontière efficiente par bande : volatilité, rendement et perte maximale avec et sans plancher | Remplacer l'escalier par une interpolation pour supprimer la discontinuité à S = 0,2 / 0,4 / 0,6 / 0,8 |
| `SLOT_SHIFT` ±0,10 | Écart de volatilité et de rendement entre variantes ; vérifier que `_under_cap` ne les fait pas converger | Choisir le décalage pour obtenir une volatilité distincte de ≥ 1 point |
| Poids du questionnaire (0,6/0,4 ; 0,5/0,3/0,2) | Simulation : tirer des profils aléatoires, mesurer la sensibilité de S à chaque réponse (±1 cran) et la distribution des bandes | Calibrer sur des profils annotés par des conseillers, ou sur un questionnaire de tolérance au risque validé |
| `CAPACITY_MARGIN` | Fréquence à laquelle il plafonne S (`capped`) | Aucune justification : mesurer l'impact sur la distribution de S |
| Nombre de positions 25–70 | Courbe utilité contre nombre de positions sur l'univers réel (le commentaire de `config.py` vient du jeu synthétique) | Refaire la mesure : 1 point de base de coût marginal |
| Plafonds de concentration | Contribution au risque de la ligne maximale | Fixer par contribution plutôt que par poids |

### M9.5 Facteurs

Tests de stabilité temporelle (autocorrélation des rangs d'un score entre deux dates), de pouvoir prédictif (coefficient d'information : corrélation de rang entre score et rendement suivant, avec scores **datés**), de sensibilité à la winsorisation (1 %/99 % contre 2,5 %/97,5 %), à `MIN_CELL` (3, 5, 10), aux pondérations des mesures (1/n contre pondérations par variance), et du lien entre seuils (±0,2 ; ±0,5) et la composition obtenue (distribution des expositions des portefeuilles construits).

### M9.6 Macroéconomie

Une intégration quantitative n'est défendable qu'après un test walk-forward : par exemple, faire dépendre μ d'un indicateur de pente de courbe, ou l'ERP d'un régime de taux. Risque principal : sur-ajustement avec ~6 ans de données et peu de régimes. À traiter comme **exploratoire**. Les z-scores existants sont construits sans anticipation (notebook), ce qui facilite un test propre.

### M9.7 Backtest et Monte Carlo

Implémenter le walk-forward de M6.4 ; comparer à un indice et à un portefeuille équipondéré ; tester des simulations plus robustes : bootstrap par blocs des rendements historiques du portefeuille, loi de Student, incertitude sur μ et σ (tirer μ dans son intervalle de confiance), et scénarios défavorables (chocs de volatilité, périodes de crise du dataset). Comparer `PATHS = 1000` à 10 000 pour mesurer la stabilité des centiles.

### M9.8 Tableau de priorisation

« Nature » : **OBSERVÉE** = faiblesse constatée dans le code ou la documentation du dépôt ; **EXPLORATOIRE** = idée sans faiblesse constatée.

| Amélioration | Limitation actuelle | Test proposé | Impact attendu | Complexité | Priorité | Nature |
|---|---|---|---|---|---|---|
| Aligner et documenter l'annualisation de Σ | Σ annualisée avec `periods_per_year_effective`, μ et `ann_vol` avec 252 | Mesurer l'écart via `python -m invest_agents.market` | Cohérence des volatilités et du seuil de pénalité | Faible | **Haute** | OBSERVÉE |
| Justifier ou calibrer `VOL_ANCHORS` et `AVERSION_ANCHORS` | Valeurs sans justification chiffrée | M9.4 | Réponse défendable au jury | Moyenne | **Haute** | OBSERVÉE |
| Backtest walk-forward | Backtest rétrospectif (poids ex post) | M6.4 | Résultats honnêtes hors échantillon | Élevée | **Haute** | OBSERVÉE |
| Test de parité front/back | 12 constantes dupliquées sans test | Test qui compare `monport.py` et `engine.ts` | Évite la dérive silencieuse | Faible | **Haute** | OBSERVÉE |
| Comparer les méthodes de μ hors échantillon | Choix manuel par classe, comparaison annoncée mais absente | M9.1 | μ plus fiable | Moyenne | Haute | OBSERVÉE |
| Source du « 40 % réglementaire » | Présenté comme réglementaire sans citation | Chercher la source ou reformuler | Éviter une affirmation fausse | Faible | Haute | OBSERVÉE |
| Plafond par action garanti par le code | Écrit par le LLM, ajouté par le code seulement s'il manque | Vérifier la valeur de Pépite ; forcer `min(valeur, STOCK_ANCHORS(S))` | Contrainte déterministe | Faible | Moyenne | OBSERVÉE |
| Exposer A effectif et σ visé | A effectif et diagnostics non envoyés au front | Ajouter ces champs à `to_portfolio` | Transparence de la relance de A | Faible | Moyenne | OBSERVÉE |
| Confirmation avant d'assouplir les exclusions | Les exclusions sont assouplies en dernier recours | Revue produit | Respect des valeurs du client | Moyenne | Moyenne | OBSERVÉE |
| Frais dans projection et backtest | `FEES` calculé mais inutilisé | Appliquer les frais aux rendements | Chiffres nets | Faible | Moyenne | OBSERVÉE |
| Interpoler le plancher d'obligations | Escalier de 20 points | Comparer frontières avec et sans | Moins de discontinuités | Faible | Moyenne | OBSERVÉE |
| Calibrer λ_D et λ_V | Nulles, non calibrées | M9.3 | Concentration maîtrisée | Moyenne | Moyenne | OBSERVÉE |
| Projection plus robuste | Normale i.i.d., sans incertitude de paramètres | M9.7 | Cônes plus réalistes | Moyenne | Moyenne | OBSERVÉE |
| 1 000 → 10 000 trajectoires | Erreur d'échantillonnage du 5ᵉ centile | Comparer les centiles | Centiles stables | Faible | Basse | OBSERVÉE |
| Normaliser les deux Sharpe affichés | Géométrique réalisé contre arithmétique estimé | Libellé ou calcul commun | Clarté | Faible | Moyenne | OBSERVÉE |
| Tests IC des facteurs | Scores sans validation de pouvoir prédictif | M9.5 | Facteurs défendables | Moyenne | Basse | EXPLORATOIRE |
| Macro dans μ ou les contraintes | Macro non quantitative | M9.6 | Inconnu | Élevée | Basse | EXPLORATOIRE |

---

## M10. Préparation aux questions des juges

**Mode d'emploi.** Chaque fiche contient : la question, la valeur actuelle, l'emplacement dans le code, la justification **existante** (dans le dépôt), une justification **défendable** (PROPOSÉE, à présenter comme hypothèse), la limite à reconnaître et une méthode de calibration. **Ne jamais présenter une valeur comme « calibrée » si elle ne l'est pas** : dire « hypothèse de départ, à calibrer ».

**Réponse transversale à garder en tête.** « Les chiffres viennent du code, jamais d'un modèle de langage (`backend/CLAUDE.md`, règle 1). Les profils sont des hypothèses de conception, centralisées et documentées, que nous proposons de calibrer sur l'univers réel. »

### Fiche 0 — « Pourquoi un investisseur avec S = 0,4 est-il limité à 11 % de volatilité ? »

- **Valeur actuelle.** 11 % annualisé (ancre n° 3 de `VOL_ANCHORS`).
- **Code.** `VOL_ANCHORS`, `monport.py:152` ; `assess` (`:528`), `slot_volatility` (`:552`), `build_profiles` (`:792-795`) ; vérification `catalog.evaluate` (`:832`).
- **Justification existante.** Commentaire « filet de sécurité ». Aucun calcul.
- **Justification défendable.** À S = 0,4 le profil est « équilibré » (plancher d'obligations 40 %, soit un portefeuille de type 60/40 dont la volatilité historique se situe en ordre de grandeur autour de 10 %). Le plafond de 11 % fait de cette limite un filet cohérent avec ce portefeuille modèle ; il augmente avec S pour laisser plus de place aux profils audacieux.
- **Limite.** Valeur choisie à la main ; pas de mesure sur notre univers ni de lien démontré avec A = 7.
- **Calibration.** M9.4 (volatilité du portefeuille optimal sans plafond à A = 7 ; fixer le plafond au-dessus).

### Fiche 1 — Pourquoi CAPM avec rétrécissement et α = 0,50 ?

- **Valeur.** `alpha = 0,50` ; `μ = 0,5 (rf + β·ERP) + 0,5 μ_hist`.
- **Code.** `config.py:134` ; `market.py:79-127`.
- **Existant.** Aucune justification. Commentaire : « poids de la cible CAPM ».
- **Défendable.** La moyenne historique d'un titre est très bruitée ; une cible économique stable réduit la variance de l'estimation. 0,5 est le choix neutre entre les deux sources.
- **Limite.** Pas de validation de α. Le CAPM sur SPY ne reflète pas les titres non américains.
- **Calibration.** M9.1 : grille de α hors échantillon.

### Fiche 2 — Pourquoi SPY comme benchmark ?

- **Valeur.** `market_proxy = "SPY"`.
- **Code.** `config.py:131`.
- **Existant.** « Baseline unique, pas un CAPM multi-classe » (commentaire). Les mappings par secteur et par pays (`BENCHMARKS`) existent mais ne servent qu'à la méthode inactive.
- **Défendable.** Indice large, liquide, disponible dans l'univers, coté en dollars US mais utilisé sur des rendements en CAD.
- **Limite.** Mauvais benchmark pour le Canada, l'Europe et les ETF obligataires ou thématiques.
- **Calibration.** Activer `capm_benchmark_shrinkage` avec primes par benchmark documentées et comparer.

### Fiche 3 — Pourquoi une prime de risque de 5 % ?

- **Valeur.** `erp_annual = 0,05`.
- **Code.** `config.py:133`.
- **Existant.** « Hypothèse illustrative, pas une donnée live ».
- **Défendable.** Ordre de grandeur couramment utilisé pour la prime de risque actions. À présenter comme hypothèse.
- **Limite.** Non estimée ; varie selon la source et la période.
- **Calibration.** Fourchette 3-6 % en sensibilité ; sources académiques (à citer par l'équipe).

### Fiche 4 — Pourquoi utiliser les rendements depuis 2021 ?

- **Valeur.** `COVARIANCE_HISTORY.start_date = 2021-01-01` ; dataset « jours ouvrables depuis 2021 ».
- **Code.** `config.py:265-268` ; `market.py:204`.
- **Existant.** `config.py:261-263` : un titre récent réduirait l'échantillon commun de Σ à quelques mois.
- **Défendable.** Garantit un échantillon commun long et une matrice stable pour tous les titres de l'univers.
- **Limite.** Période courte, avec un régime de hausse des taux (2022) ; exclut les titres plus récents ; μ historique influencé par ce régime.
- **Calibration.** Sensibilité à la date de début ; comparaison avec d'autres fenêtres (M9.2).

### Fiche 5 — Pourquoi Ledoit-Wolf plutôt que la covariance brute ?

- **Valeur.** `COVARIANCE.method = "ledoit_wolf"`.
- **Code.** `config.py:227` ; `market.py:145`, `:262`.
- **Existant.** La covariance `sample` existe comme alternative inactive (`config.py:237-239`). Aucune comparaison chiffrée.
- **Défendable.** Avec environ 700 titres et 1 500 dates, la covariance empirique est bruitée et mal conditionnée ; Ledoit-Wolf réduit l'erreur d'estimation en tirant vers une cible simple (`m·I`) avec un poids estimé.
- **Limite.** La cible suppose des variances égales ; pas de test hors échantillon dans le projet.
- **Calibration.** M9.2.

### Fiche 6 — Pourquoi l'intensité de Ledoit-Wolf est-elle automatique ?

- **Valeur.** `shrinkage_intensity: "auto"`.
- **Code.** `config.py:243` ; `market.py:145-162`.
- **Existant.** Aucune.
- **Défendable.** Elle est estimée par la formule de Ledoit-Wolf, qui minimise l'erreur quadratique attendue ; cela évite d'ajouter un paramètre choisi à la main.
- **Limite.** Optimale pour la norme de Frobenius, pas forcément pour la variance du portefeuille final.
- **Calibration.** Comparer à une intensité fixe.

### Fiche 7 — Pourquoi σ maximum varie-t-il avec S ?

Voir fiche 0. Réponse courte : plus S est élevé, plus la capacité et la tolérance sont grandes ; la limite sert de filet qui croît avec le risque accepté (6 % à 25 %).

### Fiche 8 — Pourquoi A varie-t-il entre 1 et 25 ?

- **Valeur.** Bornes 1 et 25 (`RISK_AVERSION`, `AVERSION_ANCHORS`).
- **Code.** `config.py:310-311` ; `monport.py:151` ; `allocator.py:45`.
- **Existant.** Commentaire : « bornes de A du tableau des profils » (tableau non présent). `backend/CLAUDE.md` : sur le jeu synthétique, A = 25 donne environ 4 % de volatilité et A = 1 environ 15 %.
- **Défendable.** La plage couvre un facteur 25 entre le profil le plus audacieux (rendement presque seul) et le plus prudent. Les valeurs de la littérature pour l'aversion relative au risque se situent souvent entre 1 et 10 ; 25 sert de borne prudente.
- **Limite.** Le sens de A dépend de l'échelle de μ et Σ ; A = 1 à 25 n'a pas été comparé aux préférences réelles.
- **Calibration.** M9.4 (relation A ↔ volatilité).

### Fiche 9 — Pourquoi l'interpolation de A est-elle logarithmique ?

- **Valeur.** `_interpolate(…, log=True)` (`monport.py:362-372`).
- **Existant.** Commentaire : « interpolation logarithmique ».
- **Défendable.** A couvre un ordre de grandeur ; une interpolation géométrique donne une décroissance proportionnelle (≈ ÷2 par bande), ce qui répartit les profils de façon plus uniforme en termes de risque accepté qu'une interpolation linéaire.
- **Limite.** Choix de forme non testé.
- **Calibration.** Comparer à une interpolation linéaire sur la volatilité obtenue.

### Fiche 10 — Pourquoi S est-il déplacé de ±0,10 ?

- **Valeur.** `SLOT_SHIFT = {−0,1 ; 0 ; +0,1}`.
- **Code.** `monport.py:157`, `:545-550`.
- **Existant.** « une demi-catégorie l'une de l'autre » (commentaire).
- **Défendable.** Trois variantes distinctes sans changer de catégorie ; un rapport de A de 1,4 à 1,5 entre variantes voisines.
- **Limite.** Seul A change (même plafond de volatilité, mêmes contraintes) ; si le plafond est actif, `_under_cap` peut rapprocher les A effectifs.
- **Calibration.** M9.4.

### Fiche 11 — Pourquoi 60/40 et 50/30/20 dans le questionnaire ?

- **Valeur.** `C = 0,6h + 0,4a` ; `T = 0,5r + 0,3o + 0,2c`.
- **Code.** `monport.py:344`, `:352`.
- **Existant.** `RiskNotebook.tsx:135` : « Ta réaction à une baisse compte le plus ». Pas de justification chiffrée.
- **Défendable.** L'horizon prime sur l'âge pour la capacité ; la réaction réelle à une perte est plus fiable qu'un objectif déclaré.
- **Limite.** Pondérations non estimées sur des données de clients.
- **Calibration.** Annotation par des conseillers ou questionnaire validé (M9.4).

### Fiche 12 — Pourquoi imposer des planchers d'obligations ?

- **Valeur.** 80 % / 60 % / 40 % / 20 % / 0 %.
- **Code.** `BOND_FLOOR`, `monport.py:137` ; `follow_profile`.
- **Existant.** « Répartition stratégique du profil (portefeuilles modèles 20/80 … 100/0) ».
- **Défendable.** Portefeuilles modèles actions/obligations classiques ; les obligations amortissent les baisses.
- **Limite.** Escalier discontinu ; rendement historique des obligations de l'échantillon très influencé par 2022.
- **Calibration.** Frontières efficientes par bande.

### Fiche 13 — Pourquoi certains profils excluent-ils la crypto ?

- **Valeur.** Bandes conservateur et modéré.
- **Code.** `NO_CRYPTO`, `monport.py:141` ; `follow_profile`.
- **Existant.** « Pas de crypto dans un portefeuille qui suit un profil prudent » ; texte de cohérence : « la crypto peut perdre la moitié de sa valeur en quelques mois ».
- **Défendable.** Volatilité et pertes extrêmes incompatibles avec une faible tolérance.
- **Limite.** Le client peut fixer un pourcentage de crypto : il l'emporte sur l'interdiction.
- **Calibration.** Scénarios de crise.

### Fiche 14 — Pourquoi un plafond de 40 % par ligne ?

- **Valeur.** `LINE_CAP = 0,40`.
- **Code.** `monport.py:132`.
- **Existant.** « Limite de sécurité » ; `CLAUDE.md` parle de « limites réglementaires » sans citer de source.
- **Défendable.** Évite de concentrer tout le portefeuille sur un placement ; 40 % permet à un FNB d'obligations de porter un plancher de 80 % avec 2 FNB.
- **Limite.** **Ne pas affirmer qu'il est réglementaire** sans source.
- **Calibration.** Nombre de FNB nécessaires par profil.

### Fiche 15 — Pourquoi un minimum de 1 % par position ?

- **Valeur.** `min_held_weight = 0,01`.
- **Code.** `allocator.py:44` ; `config.py:280`, `:334` ; `monport.py:817`.
- **Existant.** « 0 ou au moins 1 % » ; texte UI « pas de miettes » ; docstring de `enforce_minimum` : un mélange 80/20 créerait des positions à 0,2 %.
- **Défendable.** Évite les micro-positions (frais, lisibilité).
- **Limite.** Règle non convexe : l'optimisation devient heuristique.
- **Calibration.** Coût d'utilité par position.

### Fiche 16 — Pourquoi 25 à 70 positions ?

- **Valeur.** `PORTFOLIO_HOLDINGS` : min 25, max 70, coût marginal 0,0001.
- **Code.** `config.py:278-283` ; `allocator.py:347-440`.
- **Existant.** **Documenté empiriquement** : « mesuré sur un univers synthétique de 769 titres : environ 28 titres par Markowitz seul, arrêt vers 45 à 50 ».
- **Défendable.** Diversification presque gratuite jusqu'à 1 point de base d'utilité par position.
- **Limite.** Mesure sur un jeu **synthétique** ; à refaire sur le réel. « Cible de diversification » : il n'existe pas de cible fixe (la docstring le dit).
- **Calibration.** Courbe utilité contre nombre de positions sur l'univers réel.

### Fiche 17 — Pourquoi ces seuils de facteurs (±0,2, ±0,5) ?

- **Valeur.** `FACTOR_LEVELS`.
- **Code.** `monport.py:113`.
- **Existant.** « Plus/Moins = légère inclinaison, Imposer/Exclure = nette (dure) ». `FACTORS.md` : « équipondéré, sans optimisation ni backtest ».
- **Défendable.** Un z-score de cellule de 0,5 correspond à une action nettement mieux placée que ses pairs ; 0,2 à une légère inclinaison.
- **Limite.** Aucune validation prédictive ; scores instantanés (yfinance).
- **Calibration.** M9.5.

### Fiche 18 — D'où viennent les données macroéconomiques ?

- **Réponse.** FRED (Réserve fédérale de St. Louis) pour les États-Unis et le chômage canadien (série OCDE) ; Banque du Canada (API Valet) pour les taux, l'IPC et le taux directeur canadiens. Préparées dans `data-prep/Macro.ipynb`, avec décalages de publication et z-scores sans anticipation.
- **Usage.** Contexte pour les agents et preuves affichées ; **aucun effet quantitatif** sur μ, Σ ou les contraintes.
- **Limite.** Pays : États-Unis et Canada seulement.

### Fiche 19 — Comment le backtest évite-t-il le biais d'anticipation ?

- **Réponse honnête.** **Il ne l'évite pas.** Les poids viennent d'un optimiseur qui a vu toute la période (M6.3). Le front l'affiche : « résultats possiblement biaisés ». Un walk-forward est proposé (M6.4).

### Fiche 20 — Comment les trajectoires simulées sont-elles générées ?

- **Réponse.** Monte Carlo gaussien i.i.d. au niveau du portefeuille : `V ← V(1 + μ/n + σ/√n·Z) + versement`, 1 000 trajectoires, graine 7, centiles 5/25/75/95 (M7.1).

### Fiche 21 — Pourquoi 1 000 simulations ?

- **Valeur.** `PATHS = 1000`.
- **Code.** `projection.py:21`.
- **Existant.** Aucune.
- **Défendable.** Suffisant pour des centiles centraux stables à l'écran, pour un coût de calcul négligeable.
- **Limite.** Erreur d'échantillonnage du 5ᵉ centile d'environ ±0,7 point de probabilité ; peu d'information sur les queues.
- **Calibration.** Comparer à 10 000.

### Fiche 22 — Pourquoi 25 % comme seuil de pénalisation des titres volatils ?

- **Valeur.** `volatility_threshold = 0,25`.
- **Code.** `config.py:408` ; `optimizer.py:398-401`.
- **Existant.** « 25 % de volatilité annualisée » ; **les deux pénalités sont à 0,0** : le seuil n'a pas d'effet aujourd'hui.
- **Défendable.** Au-delà de 25 %, un titre dépasse nettement la volatilité d'un indice actions (ordre de grandeur 15 à 20 %).
- **Limite.** Compare `√Σᵢᵢ` rétrécie, annualisée avec `periods_per_year_effective` ; non calibré.
- **Calibration.** Fraction de l'univers pénalisée selon le seuil (M9.3).

### Fiche 23 — Comment calibrer λ_D et λ_V ?

- **Valeur.** 0,0 et 0,0.
- **Réponse.** Voir M9.3 : grille, mesure du nombre effectif de positions, de la perte de rendement espéré et de la volatilité ; choisir la valeur qui atteint une cible de concentration pour une perte de rendement bornée ; relation `2λ/A` à rappeler.

### Fiche 24 — « Le A utilisé par l'optimiseur est-il celui du profil ? »

- **Réponse.** Pas toujours. Si le plafond de volatilité est dépassé, `_under_cap` relève A jusqu'à 25 (`allocator.py:133`). `A_effective` est tracé dans les diagnostics mais pas affiché. Pour « Tes préférences », A est choisi par balayage (`_best_sharpe`).

### Fiche 25 — « Vos exclusions sont-elles toujours respectées ? »

- **Réponse.** Elles le sont tant qu'un portefeuille est possible avec les limites dures. Si le calcul échoue, le code assouplit d'abord les pourcentages, puis les plafonds, puis **les exclusions** ; le client est averti (« Calcul relancé avec des limites assouplies »). La limite de 40 % par ligne n'est jamais assouplie.

---

## M11. Éléments non vérifiés et corrections

### M11.1 Non vérifié

- Le fichier « tableau des profils » dont parle le commentaire de `AVERSION_ANCHORS` (`monport.py:149-150`) n'est pas dans le dépôt.
- La source réglementaire du plafond de 40 % (`CLAUDE.md` parle de « limites réglementaires »).
- Que les clés `long_only`, `fully_invested` de `config.py:331-332` soient lues.
- La ligne de calcul de `spread_10y_2y` dans `Macro.ipynb` (présumé `yield_10y − yield_2y`).
- Si Pépite peut proposer un `max_stock_weight` différent de la valeur reçue ; le chemin exact de l'écriture de cette contrainte par le LLM.
- Les effets numériques : écart d'annualisation de Σ, valeur de `A_effective`, volatilité réalisée par profil, importance de `CAPACITY_MARGIN`. Aucun code n'a été exécuté.
- Survie de l'univers (`build_universe.py`) et ampleur du biais du backtest.
- Les tests du front-end ; l'existence d'un test de parité des constantes de profil.
- L'affichage du texte de justification du juge et de la pénalité côté front.
- Le contenu de `deploy/*.sh` au-delà des variables d'environnement citées.

### M11.2 Corrections de la version 2 découvertes pendant ce travail

| Sujet | Version 2 | Correction |
|---|---|---|
| Lignes de `market.py` | Plusieurs références décalées (par exemple `_beta` à `:62`, `estimate_covariance` à `:119`) | Lignes réelles : `_historical_mu` `:48`, `_ewma_mu` `:55`, `_beta` `:66`, `estimate_expected_returns` `:79`, `joint_window` `:129`, `_ledoit_wolf` `:145`, `estimate_covariance` `:164`, `history_filter` `:204`, `synchronized_returns` `:237`, `ledoit_wolf_universe` `:262`, `Market` `:286`, `moments` `:381`, `portfolio_metrics` `:394`, `build_market` `:426` |
| Intensité Ledoit-Wolf | `config.py:244` | `config.py:243` (`assume_centered` : `:244`) |
| Test de parité front/back | « aucun test de parité trouvé » | Une liste de synchronisation manuelle est documentée dans `CLAUDE.md` ; je n'ai pas trouvé de test automatique correspondant (tests du front non explorés) |
| Frais | Noté comme non affichés | `CLAUDE.md` confirme : « Pas de frais affichés » ; `FEES` est toutefois calculé et transmis |
| Justification des paramètres | Présentés sans distinction | Ce volume sépare justification documentée, proposée et absente |

from __future__ import annotations

# VERSION V4 — ETF obligataires : moyenne historique uniquement.
# Suppression complète des paramètres de modèles obligataires (duration, convexité, spreads et défauts).
# Les ETF "Fixed Income" utilisent ESTIMATION["method_by_asset_class"]["Fixed Income"]
# = "historical", sauf si un override explicitement configuré prend priorité.
# Les modes BASE/AGENT, Rf CAPM 3,5 %, EWMA historique complet, cash 0 %,
# max cash 100 % et la source KIRO/S3 sont conservés.
# Aucun Parquet n'est ouvert à l'import.


import argparse
import copy
import json
import math
import os
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# 1. SOURCE DES DONNÉES — POINT D'INTÉGRATION KIRO / S3
# ---------------------------------------------------------------------------

# Chemin local du dépôt KIRO. Une URI S3 peut le remplacer via MONPORT_UNIVERSE_PARQUET_URI.
DEFAULT_PARQUET_PATH = "/workshop/datathon-pf-2026/backend/data/universe.parquet"
PARQUET_ENV_VAR = "MONPORT_UNIVERSE_PARQUET_URI"

# Valeur de référence issue de UNIVERSE.md ; l'extracteur peut être mis à jour.
DATA = {
    "default_parquet_path": DEFAULT_PARQUET_PATH,
    "parquet_env_var": PARQUET_ENV_VAR,
    "base_currency": "CAD",
    "return_column": "total_return_cad",
    "price_column": "close_price_cad",
    "forward_return_column": "total_return_cad_fwd_1d",  # jamais un input d'estimation
    "date_column": "date",
    "symbol_column": "symbol",
    "inclusion_column": "is_included_universe",
    "min_observations": 120,
    "periods_per_year": 252,  # séances ; la crypto a déjà été réduite aux jours ouvrables
    "as_of": None,          # None = dernière date contenue dans le fichier
    "start_date": None,     # None = aucune borne supplémentaire
    "strict_validation": True,
    "never_fill_missing_returns": True,
    "keep_excluded_history": True,
    "region_overrides": {},
}

VALID_RETURN_METHODS = frozenset({
    "historical", "ewma", "capm_shrinkage", "capm_benchmark_shrinkage",
})
VALID_COVARIANCE_METHODS = frozenset({"sample", "ledoit_wolf"})
VALID_ASSET_CLASSES = frozenset({
    "Equity", "Fixed Income", "Multi-Asset", "Real Estate",
    "Commodities", "Alternative",
})
VALID_INSTRUMENT_TYPES = frozenset({"Stock", "ETF", "Cryptocurrency"})
# Exposition inconnue (ETF sans look-through...) face à un plafond de secteur/région/pays :
# "strict" = l'instrument est rejeté (défaut, mode AGENT) ; "flag" = plafond appliqué aux
# expositions connues, instrument conservé et signalé (mode BASE).
UNKNOWN_EXPOSURE_POLICIES = frozenset({"strict", "flag"})
# Réponses du questionnaire : Exclure (0 % exactement), Neutre (aucune contrainte), pourcentage exact.
# Forme interne d'une préférence : {"mode": "exclude" | "neutral" | "exact", "weight": None | fraction}.
PREFERENCE_MODES = frozenset({"exclude", "neutral", "exact"})
PREFERENCE_DIMENSIONS = frozenset({
    "asset_class", "instrument_type", "region", "country",
    "sector", "industry", "theme", "symbol",
})
# Dimensions des questions 3 et 4 (géographie, secteurs, thématiques) : seules les actions détenues en direct
# (instrument_type == "Stock") y sont comptées. Un FNB ou une crypto y a un coefficient nul, même si un
# look-through existe : il n'est ni exclu par ces préférences, ni utilisable pour les satisfaire.
STOCK_ONLY_PREFERENCE_DIMENSIONS = frozenset({"region", "country", "sector", "industry", "theme"})
# Sur ces dimensions, un pourcentage exact est une PART DE LA POCHE ACTIONS (ce que dit le questionnaire) :
#   Σ actions en direct du groupe = p × Σ instruments de classe Equity (actions en direct + FNB d'actions).
# Les FNB d'actions comptent dans la poche (dénominateur), jamais dans le groupe (numérateur).
EQUITY_SLEEVE_CLASSES = frozenset({"Equity"})
# Un groupe de préférence peut réunir plusieurs libellés : « Consumer Staples|Consumer Discretionary ».
PREFERENCE_GROUP_SEPARATOR = "|"
# Question 1 : instruments admissibles. Le cash synthétique reste permis dans les trois modes.
INSTRUMENT_SELECTION = {
    "etf_only": frozenset({"ETF"}),
    "mixed": frozenset({"ETF", "Stock", "Cryptocurrency"}),
    "stocks_only": frozenset({"Stock", "Cryptocurrency"}),
}


# ---------------------------------------------------------------------------
# 2. PRÉVISIONS DE RENDEMENT — LES QUATRE MÉTHODES
# ---------------------------------------------------------------------------

# HYPOTHÈSE COMMUNE AU MOTEUR (BASE + AGENT) : taux sans risque CAPM = 3,5 %.
# Hypothèse de démonstration, et NON un taux CAD/US universel ou un taux live.
RF_ANNUAL = 0.035

ESTIMATION = {
    "forecast_horizon_years": 1,
    "periods_per_year": DATA["periods_per_year"],
    "mode": "by_asset_class",    # ou "single_method"
    "single_method": "historical",
    # Baseline opérationnelle ; les choix seront comparés hors échantillon.
    # Les ETF d'actions sont aussi dans Equity ; leur look-through sera à gérer
    # par les métadonnées/overrides avant d'activer le CAPM personnalisé.
    "method_by_asset_class": {
        "Equity": "capm_shrinkage",
        "Fixed Income": "historical",
        "Multi-Asset": "historical",
        "Real Estate": "historical",
        "Commodities": "historical",
        "Alternative": "historical",
    },
    # L'instrument Cryptocurrency est distingué de l'ETF BITW, même si les
    # deux peuvent avoir asset_class='Alternative'.
    "method_by_instrument_type": {"Cryptocurrency": "ewma"},
    "method_by_symbol": {"BITW": "ewma"},  # ETP de crypto (Bitwise 10)
    # Fenêtres de mu : historique individuel MAXIMAL de chaque titre (None = tout ce qui est disponible jusqu'à
    # la date d'estimation). mu n'exige jamais de dates communes avec les autres titres.
    "historical": {
        "lookback_observations": None,  # avant : 1260 (~5 ans) ; tout l'historique du titre
        "min_observations": 120,
    },
    "ewma": {
        "lookback_observations": None,  # None = tout l'historique disponible
        "half_life_observations": 90,    # observations anciennes déjà dépondérées
        "min_observations": 120,
    },
    "capm_shrinkage": {
        # Bêta sur les dates communes au titre et à SPY seulement (pas à tout l'univers), tout l'historique.
        "lookback_observations": None,   # avant : 756 (~3 ans)
        "min_paired_observations": 120,
        "market_proxy": "SPY",        # baseline unique, pas un CAPM multi-classe
        "rf_annual": RF_ANNUAL,  # taux CAPM commun = 3,5 %, hypothèse
        "erp_annual": 0.05,        # hypothèse illustrative, pas une donnée live
        "alpha": 0.50,            # poids de la cible CAPM
        "historical_lookback_observations": None,  # avant : 1260 ; toute la période du titre
    },
    "capm_benchmark_shrinkage": {
        "lookback_observations": None,  # bêta ; avant : 756 ; historique intégral commun titre/benchmark
        "min_paired_observations": 120,
        "historical_lookback_observations": None,  # avant : 1260
        "rf_annual": RF_ANNUAL,
        "alpha": 0.50,
        # Ne PAS appliquer mécaniquement la prime SPY à tous les benchmarks.
        # Les primes, dans une même convention CAD, sont à renseigner et
        # justifier avant d'activer cette méthode.
        "erp_annual_by_benchmark": {},
        "missing_premium_policy": "error",  # pas de prime inventée
        "missing_benchmark_policy": "error",  # ne jamais deviner
    },
}


# ---------------------------------------------------------------------------
# 3. BENCHMARKS : EXPOSITION ÉCONOMIQUE, NON PLACE DE COTATION
# ---------------------------------------------------------------------------

BENCHMARKS = {
    # Benchmark unique de la baseline CAPM ; à ne pas appliquer aveuglément
    # aux obligations, crypto ou ETF multi-actifs.
    "single_market_proxy": "SPY",
    # Priorité la plus élevée : cas traités individuellement.
    "symbol_overrides": {
        "NVDA": "SMH",            # sensibilité aux semi-conducteurs (option)
    },
    # Mapping explicite pour les ETF : le pays de cotation ne suffit PAS.
    # Les benchmarks sont des propositions initiales et non un look-through
    # vérifié ; ne jamais utiliser un ETF comme son propre benchmark.
    "etf_overrides": {
        "SPY": "IYY",
        "IYY": "SPY",
        "QQQ": "SPY",
        "XLK": "SPY",
        "VGT": "SPY",
        "SMH": "SPY",
        "XIU.TO": "XIC.TO",
        "XIC.TO": "XIU.TO",
        "EFA": "ACWX",
        "EEM": "ACWX",
        "EWQ": "VGK",
        "EWG": "VGK",
        "EWU": "VGK",
    },
    # Clef : pays de domiciliation de l'action | secteur GICS.
    # Les ETF n'utilisent PAS automatiquement ce mapping, faute de données
    # d'expositions sous-jacentes dans le Parquet actuel.
    "stock_country_sector": {
        "United States|Information Technology": "XLK",
        "United States|Financials": "XLF",
        "United States|Energy": "XLE",
        "United States|Health Care": "XLV",
        "United States|Industrials": "XLI",
        "United States|Consumer Discretionary": "XLY",
        "United States|Consumer Staples": "XLP",
        "United States|Utilities": "XLU",
        "United States|Materials": "XLB",
        "United States|Real Estate": "XLRE",
        "United States|Communication Services": "XLC",
        "Canada|Financials": "XFN.TO",
        "Canada|Energy": "XEG.TO",
        "Canada|Information Technology": "XIT.TO",
        "Canada|Utilities": "XUT.TO",
        "Canada|Materials": "XMA.TO",
        "Canada|Real Estate": "XRE.TO",
    },
    # Repli pour les actions dont le secteur n'a pas de proxy approprié.
    "stock_country": {
        "United States": "SPY",
        "Canada": "XIU.TO",
        "France": "EWQ",
        "Germany": "EWG",
        "United Kingdom": "EWU",
        "Japan": "EWJ",
    },
    "fallback_for_unknown_stock": None,
    "fallback_for_unknown_etf": None,
    "require_available_returns": True,
    "avoid_self_benchmark": True,
}



# ---------------------------------------------------------------------------
# 4. COVARIANCE : UNE SEULE MATRICE JOINTE (TOUTES CLASSES)
# ---------------------------------------------------------------------------

COVARIANCE = {
    "method": "ledoit_wolf",       # alternative : "sample"
    "periods_per_year": DATA["periods_per_year"],
    # None = tout l'échantillon commun depuis le début de l'horizon (voir COVARIANCE_HISTORY) ; avant : 1260.
    "lookback_observations": None,
    "min_observations_per_asset": DATA["min_observations"],
    # IMPORTANT : pré-sélectionner les candidats avant de supprimer les
    # lignes NaN, sinon les titres fraîchement listés éliminent l'historique.
    "missing_policy_for_ledoit_wolf": "complete_cases_after_selection",
    "min_joint_observations": 120,
    "sample": {
        "min_pairwise_observations": 60,
        "repair_psd": True,
        "eigenvalue_floor": 1e-10,
    },
    "ledoit_wolf": {
        "target": "scaled_identity",   # cible de sklearn.covariance.LedoitWolf
        "shrinkage_intensity": "auto",
        "assume_centered": False,
        "block_size": 1000,
        "on_insufficient_common_history": "error",
    },
    "diagnostics": {
        "check_symmetry": True,
        "check_psd": True,
        "report_condition_number": True,
    },
}


# ---------------------------------------------------------------------------
# 5. CANDIDATS ET DIVERSIFICATION : UNIVERS ≠ TITRES DÉTENUS
# ---------------------------------------------------------------------------

# Univers d'optimisation de MonPort : un titre n'y entre que si son historique remonte au début de l'horizon.
# Sinon un seul titre récent réduirait l'échantillon commun de Sigma (Ledoit-Wolf) à quelques mois.
# Le début effectif est la première date du panel >= start_date (le 1er janvier 2021 n'est pas une séance) ;
# max_start_delay_business_days absorbe seulement les calendriers boursiers et l'initialisation des rendements.
COVARIANCE_HISTORY = {
    "start_date": "2021-01-01",
    "require_full_horizon": True,
    "method": "ledoit_wolf",
    "max_start_delay_business_days": 5,
}

# Positions réellement DÉTENUES par chaque portefeuille de MonPort (pas des candidats). Aucune cible fixe:
# l'optimiseur part des titres que Markowitz détient, complète jusqu'à min_count, puis ajoute des titres tant que
# chacun coûte au plus max_marginal_utility_cost d'utilité annuelle (diversification presque gratuite), sans
# dépasser max_count. Le nombre final dépend donc de A, des rendements, des covariances et des contraintes.
# Cas extrêmes: un nombre de positions demandé par le client (min/max_positions), ou un univers admissible trop
# petit (ex.: tout exclu sauf la crypto), l'emporte sur cette plage; le diagnostic le signale.
PORTFOLIO_HOLDINGS = {
    "min_count": 25,
    "max_count": 70,
    "min_held_weight": 0.01,
    # 1 point de base d'utilité annuelle par position ajoutée au-delà de min_count. Mesuré sur un univers synthétique
    # de 769 titres (mu de 2 % à 14 %): environ 28 titres détenus par Markowitz seul, arrêt vers 45 à 50.
    "max_marginal_utility_cost": 0.0001,
}

# Juge final, profil cohérent: points retirés (sur 10) à la note d'un portefeuille qui a dû être relancé avec des
# contraintes assouplies (`allocator.optimize_with_relaxation`). Le gagnant se départage sur la note pénalisée.
JUDGE_RELAUNCH_PENALTY = 3

# Présélection du pipeline autonome (optimizer.run_pipeline) ; MonPort n'en a plus besoin (Markowitz global).
CANDIDATES = {
    "enabled": True,
    "target_count": 50,  # cible indicative, ajustable ; non forcée à 50
    "min_count": 25,
    "max_count": 60,
    "preserve_required_symbols": True,
    "preserve_benchmark_history": True,
    "avoid_near_duplicate_exposures": True,
    "near_duplicate_correlation_threshold": 0.98,
    "selection_method": "rules_then_diversification",  # à coder dans l'optimiseur
}


# ---------------------------------------------------------------------------
# 6. AVERSION AU RISQUE A : QUESTIONNAIRE / AGENT
# ---------------------------------------------------------------------------

RISK_AVERSION = {
    "parameter_name": "A",
    "min": 1.0,
    "max": 25.0,
    "default": 5.0,  # si questionnaire absent ; pas un A calculé pour l'utilisateur
    "derive_from_questionnaire": True,
    # Chaque intervalle est ouvert à gauche sauf le premier.
    "bands": [
        {"name": "tres_audacieux", "upper": 1.5},
        {"name": "audacieux", "upper": 3.5},
        {"name": "equilibre", "upper": 7.0},
        {"name": "prudent", "upper": 14.0},
        {"name": "tres_prudent", "upper": 25.0},
    ],
    "do_not_infer_from_age_alone": True,
}


# ---------------------------------------------------------------------------
# 7. CONTRAINTES DYNAMIQUES : CHIFFRES NON DÉCIDÉS = None
# ---------------------------------------------------------------------------

CONSTRAINTS = {
    "long_only": True,
    "fully_invested": True,
    # 0 ou >= 1 % : PAS une borne min de 1 % sur tous les 804 candidats.
    "min_held_weight": 0.01,
    "minimum_holding_method": "prune_reoptimize",
    "minimum_holding_max_iterations": 30,
    "minimum_holding_tolerance": 1e-8,
    "minimum_holding_global_optimality_guaranteed": False,
    # Le plafond par actif est une AUTRE contrainte, encore à calibrer.
    "max_weight_per_asset": None,
    "max_weight_by_instrument_type": {},
    "max_weight_by_asset_class": {},
    "excluded_symbols": [],
    "required_symbols": [],   # présence obligatoire ; min_held_weight si détenu
    "required_symbol_min_weights": {},
    # Voir INSTRUMENT_SELECTION ; liquidités autorisées dans les trois modes.
    "instrument_selection": "mixed",
    "min_cash_weight": 0.0,  # le questionnaire peut imposer davantage
    "max_cash_weight": 1.0,  # 100 % exprimé en fraction (NE PAS écrire 100.0)
    "excluded_asset_classes": [],
    "excluded_instrument_types": [],
    "excluded_sectors": [],
    "excluded_countries": [],
    "excluded_regions": [],
    "excluded_themes": [],
    "excluded_factors": [],
    # Dimensions à contraintes groupées (min/max) ; vides au départ.
    "group_limits": {
        "asset_class": {},
        "instrument_type": {},
        "sector": {},
        "country": {},
        "region": {},
        "theme": {},
        "factor": {},
    },
    "cash_is_exception_to_etf_only": True,
    "reject_conflicting_hard_constraints": True,
}

PREFERENCES = {
    "modes": sorted(PREFERENCE_MODES),
    # Exclure et Exact sont des contraintes d'égalité strictes ; Neutre n'ajoute rien.
    "meaning": {
        "exclude": "hard_zero",            # e_g @ w == 0
        "neutral": "no_extra_constraint",  # Markowitz décide
        # Classes, types, symboles : e_g @ w == weight (fraction du portefeuille total, cash inclus).
        # Régions, pays, secteurs, thématiques : (e_g - weight × equity) @ w == 0 (part de la poche actions).
        "exact": "hard_equality",
    },
    "stock_only_base": "equity_sleeve",
    "available_dimensions": sorted(PREFERENCE_DIMENSIONS),
    "stock_only_dimensions": sorted(STOCK_ONLY_PREFERENCE_DIMENSIONS),
}


# ---------------------------------------------------------------------------
# 8. CASH, UTILITÉ MARKOWITZ ET SOLVEUR
# ---------------------------------------------------------------------------

CASH = {
    "enabled": True,
    "symbol": "CASH-CAD",          # actif synthétique : absent du Parquet
    "annual_expected_return": 0.01,  # MODIFIABLE : hypothèse de cash CAD à 1 % (distincte du Rf CAPM=3,5 %)
    "annual_volatility": 0.0,       # approximation de cash nominal sans risque
    "zero_covariance_assumption": True,
    "exclude_from_min_held_weight": True,
    "permitted_with_etf_only": True,
}

# Pénalités souples ajoutées à l'utilité de Markowitz (pas des contraintes), identiques pour les 3 variantes:
#   U = w'mu - A/2 w'Sigma w - lambda_D * sum(w_i^2) - lambda_V * sum(q_i * w_i^2),
#   q_i = max(0, sigma_i^2 - seuil^2), sigma_i = sqrt(Sigma_ii) de la covariance annualisée de l'optimiseur.
# À 0,0, l'optimiseur se comporte exactement comme avant (coefficients non calibrés).
REGULARIZATION = {
    "diversification_penalty": 0.0,   # lambda_D: décourage les poids concentrés, uniformément
    "high_volatility_penalty": 0.0,   # lambda_V: décourage les gros poids dans les titres au-delà du seuil
    "volatility_threshold": 0.25,     # 25 % de volatilité annualisée
}

OPTIMIZATION = {
    "objective": "maximize_mean_variance_utility",
    "formula": "U = expected_return - 0.5 * A * variance - lambda_D * sum(w^2) - lambda_V * sum(q * w^2)",
    "risk_aversion_parameter": "A",
    "solver": "SLSQP",           # scipy.optimize.minimize (continu)
    "solver_options": {
        "maxiter": 2000,
        "ftol": 1e-9,
        "disp": False,
    },
    "constraint_tolerance": 1e-7,
    "sum_weights_tolerance": 1e-7,
    "on_infeasible": "raise_diagnostic",
    "validate_weights_after_solving": True,
    "prefer_explainable_results": True,
}

BACKTEST = {
    "enabled": False,
    "method": "walk_forward",
    "rebalance_frequency": "monthly",
    "benchmark_method": "blended_benchmark",
    "benchmark_weights": {},     # choix ex ante, avant les rendements réalisés
    "allow_forward_return_column_in_estimation": False,
    "include_transaction_costs": False,
    "transaction_costs_by_instrument": {},  # données non présentes
    "metrics": ["annual_return", "annual_volatility", "sharpe", "max_drawdown", "turnover"],
}

REGIMES = {
    "enabled": False,
    "method": "rule_based_or_probabilistic",
    "allow_agent_to_delete_history_without_rules": False,
    "macro_data_source": None,
}


# ============================================================
# BASE_CONSTRAINTS — SIMULATIONS MANUELLES UNIQUEMENT
# ============================================================
# Source UNIQUE de toutes les contraintes du mode BASE : modifier les valeurs
# ici pour tester l'optimiseur. get_settings(mode="base") copie ce dictionnaire
# dans settings["constraints"].
#
# Le mode AGENT n'utilise JAMAIS ce dictionnaire : il part de CONSTRAINTS
# (plus haut), complété par les contraintes du questionnaire.
#
# Tous les poids sont des fractions : 0.05 = 5 %, 0.10 = 10 %, 1.0 = 100 %.
#
# NOMENCLATURE RÉELLE (vérifiée sur universe.parquet, 801 actifs) :
#   asset_class      : Equity, Fixed Income, Multi-Asset, Real Estate, Commodities, Alternative
#   instrument_type  : Stock, ETF, Cryptocurrency
#   sector (actions) : Information Technology, Financials, Energy, Industrials, Materials,
#                      Health Care, Consumer Discretionary, Consumer Staples, Utilities,
#                      Real Estate, Communication Services
#   region (actions) : usa, canada, europe, asie  (+ "emergents" : nom du frontend et de
#                      monport.py, aucun titre du Parquet n'y est rattaché aujourd'hui)
#
# LIMITES AGRÉGÉES ET ETF : le Parquet n'a PAS de look-through. Pour un ETF,
# secteur et pays valent « Non classé » ; une limite de secteur ou de région ne
# s'applique donc qu'aux expositions CONNUES (actions, ou look-through fourni
# explicitement). Les ETF et cryptos à exposition inconnue restent investissables,
# ne sont PAS comptés dans ces plafonds et sont signalés (voir unknown_exposure_policy).
BASE_CONSTRAINTS = {
    # --------------------------------------------------------
    # 1. RÈGLES FONDAMENTALES
    # --------------------------------------------------------
    "long_only": True,
    "fully_invested": True,
    # Un actif doit peser 0 % ou au moins 1 %.
    "min_held_weight": 0.01,
    "minimum_holding_method": "prune_reoptimize",
    "minimum_holding_max_iterations": 30,
    "minimum_holding_tolerance": 1e-8,
    "minimum_holding_global_optimality_guaranteed": False,
    # --------------------------------------------------------
    # 2. CONCENTRATION INDIVIDUELLE
    # --------------------------------------------------------
    # Maximum 10 % du portefeuille par titre ou ETF (le cash n'est pas concerné :
    # il est borné par max_cash_weight).
    "max_weight_per_asset": 0.10,
    # Les limites agrégées sont définies dans group_limits.
    "max_weight_by_instrument_type": {},
    "max_weight_by_asset_class": {},
    # --------------------------------------------------------
    # 3. TITRES OBLIGATOIRES / EXCLUS
    # --------------------------------------------------------
    "excluded_symbols": [],
    "required_symbols": [],
    "required_symbol_min_weights": {},
    # "mixed" = actions, ETF et crypto autorisés ("etf_only", "stocks_only" : voir INSTRUMENT_SELECTION).
    "instrument_selection": "mixed",
    # --------------------------------------------------------
    # 4. CASH — VARIABLE D'AJUSTEMENT
    # --------------------------------------------------------
    # Aucun minimum obligatoire.
    "min_cash_weight": 0.0,
    # Jusqu'à 100 % si les contraintes ou l'optimisation rendent préférable
    # une forte allocation au cash.
    "max_cash_weight": 1.0,
    # --------------------------------------------------------
    # 5. EXCLUSIONS STRICTES
    # --------------------------------------------------------
    "excluded_asset_classes": [],
    "excluded_instrument_types": [],
    "excluded_sectors": [],
    "excluded_countries": [],
    "excluded_regions": [],
    "excluded_themes": [],
    "excluded_factors": [],
    # --------------------------------------------------------
    # 6. LIMITES AGRÉGÉES DE DIVERSIFICATION (somme des poids du groupe)
    # --------------------------------------------------------
    "group_limits": {
        "asset_class": {
            # Maximum 5 % en actifs alternatifs. Dans cet univers, la classe
            # Alternative = BTC-CAD, ETH-CAD (crypto directe) + BITW (ETP crypto) :
            # c'est donc le plafond TOTAL crypto, directe et ETP confondues.
            "Alternative": {"max": 0.05},
            # Maximum 10 % en matières premières.
            "Commodities": {"max": 0.10},
            # Maximum 15 % en FNB immobiliers. ATTENTION : les 45 actions du secteur
            # « Real Estate » sont classées Equity et ne sont PAS dans ce groupe ;
            # voir group_limits["sector"] pour les plafonner.
            "Real Estate": {"max": 0.15},
            # Pas de plafond Equity / Fixed Income : Markowitz décide.
        },
        "instrument_type": {
            # Maximum 5 % en cryptomonnaies directes (BTC et ETH combinés).
            # Imbriqué dans Alternative ci-dessus : BITW est compté UNE seule fois,
            # dans Alternative. Ne jamais cumuler ces deux plafonds (5 % + 5 %).
            "Cryptocurrency": {"max": 0.05},
        },
        "sector": {
            # Plafonds appliqués aux ACTIONS (secteur connu) ; les ETF ne sont pas comptés.
            "Information Technology": {"max": 0.25},
            "Financials": {"max": 0.30},
            "Energy": {"max": 0.20},
            # Autres secteurs : pas de plafond supplémentaire pour les simulations.
        },
        "country": {},
        "region": {
            # Maximum 15 % en marchés émergents. « emergents » est le nom du frontend
            # (catalog.ts) et de monport.py ; « Emerging Markets » n'existe pas dans
            # les métadonnées. AUCUN titre du Parquet n'est rattaché à cette région
            # (aucune action émergente ; 7 ETF ont category = "Emerging Markets" mais
            # sans look-through) : ce plafond est inerte tant qu'aucune exposition n'est
            # fournie (exposure_overrides) et il est signalé comme tel.
            "emergents": {"max": 0.15},
        },
        # Thèmes : aucun plafond automatique (ils traversent plusieurs secteurs).
        "theme": {},
        "factor": {},
    },
    # --------------------------------------------------------
    # 7. RÈGLES DE VALIDATION
    # --------------------------------------------------------
    "cash_is_exception_to_etf_only": True,
    "reject_conflicting_hard_constraints": True,
    # "flag" : les plafonds de secteur/région/pays s'appliquent aux expositions
    # connues ; les instruments à exposition inconnue (ETF, crypto) sont conservés
    # et signalés. "strict" (défaut de constraints.py, et mode AGENT) : ils sont rejetés.
    "unknown_exposure_policy": "flag",
}
# ---------------------------------------------------------------------------
# VERSION 1 — PROFIL BASE : SIMULATIONS MANUELLES / TESTS (HARDCODÉ ET ÉDITABLE)
# ---------------------------------------------------------------------------
# Ne contient QUE ce qui n'est pas une contrainte : l'aversion au risque A et les
# préférences. TOUTES les contraintes (cash, plafonds, exclusions, group_limits...)
# sont dans BASE_CONSTRAINTS : aucune clé de contrainte ne doit être dupliquée ici
# (get_settings(mode="base") lève une erreur si c'est le cas).
# Aucune de ces valeurs ne doit servir de profil implicite d'un client réel.
BASE_PROFILE = {
    "risk_aversion_A": 5.0,
    # Forme : {"theme": {"tech": {"mode": "exact", "weight": 0.20}}} ; vide = tout est neutre.
    "preferences": {},
}
BASE_PROFILE_ALLOWED_KEYS = frozenset({"risk_aversion_A", "preferences"})

# ---------------------------------------------------------------------------
# VERSION 2 — PROFIL AGENT : INPUT DYNAMIQUE DU QUESTIONNAIRE UTILISATEUR
# ---------------------------------------------------------------------------
# Modèle de CONTRAT (documentation), pas un second jeu de poids hardcodés.
# L'agent transmet un dict similaire via get_settings(mode="agent", agent_request=...).
# Au minimum, l'agent doit fournir "risk_aversion_A" calculé par le questionnaire.
# Chaque champ facultatif absent conserve la règle NEUTRE du moteur.
# Ne pas remplir ce modèle dans config.py pour les utilisateurs réels.
AGENT_REQUEST_TEMPLATE = {
    "risk_aversion_A": None,   # OBLIGATOIRE dans la requête réelle
    "instrument_selection": None,  # "etf_only" | "mixed" | "stocks_only"
    "min_cash_weight": None,
    "max_cash_weight": None,
    "max_weight_per_asset": None,
    "excluded_symbols": None,
    "required_symbols": None,
    "required_symbol_min_weights": None,
    "excluded_asset_classes": None,
    "excluded_instrument_types": None,
    "excluded_sectors": None,
    "excluded_countries": None,
    "excluded_regions": None,
    "excluded_themes": None,
    "excluded_factors": None,
    "group_limits": None,
    "preferences": None,
}

VALID_EXECUTION_MODES = frozenset({"base", "agent"})

# ---------------------------------------------------------------------------
# 9. API DE CONFIGURATION — AUCUNE DÉPENDANCE À PANDAS / AU PARQUET
# ---------------------------------------------------------------------------


def get_parquet_source() -> str:
    """Résoudre la source locale/S3 au moment de l'appel (et non de l'import)."""
    source = os.getenv(PARQUET_ENV_VAR, DEFAULT_PARQUET_PATH).strip()
    if not source:
        raise ValueError("Le chemin du Parquet ne peut pas être vide.")
    if source.startswith("s3://"):
        remainder = source[5:]
        if "/" not in remainder or not remainder.split("/", 1)[0] or not remainder.split("/", 1)[1]:
            raise ValueError("Chemin S3 invalide ; format attendu : s3://bucket/key")
    return source


def _get_engine_defaults() -> dict[str, Any]:
    """Construire les réglages financiers COMMUNS, sans profil utilisateur."""
    return copy.deepcopy({
        "data": {**DATA, "parquet_source": get_parquet_source()},
        "estimation": ESTIMATION,
        "benchmarks": BENCHMARKS,
        "covariance": COVARIANCE,
        "covariance_history": COVARIANCE_HISTORY,
        "portfolio_holdings": PORTFOLIO_HOLDINGS,
        "candidates": CANDIDATES,
        "risk_aversion": RISK_AVERSION,
        "constraints": CONSTRAINTS,
        "preferences": PREFERENCES,
        "cash": CASH,
        "optimization": OPTIMIZATION,
        "regularization": REGULARIZATION,
        "backtest": BACKTEST,
        "regimes": REGIMES,
        "agent_preferences": {},
        "execution_mode": None,
    })


def get_settings(
    mode: str = "base",
    *,
    agent_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fournir une configuration ISOLÉE pour un run de simulation ou utilisateur.

    MODE BASE  : contraintes = BASE_CONSTRAINTS (source unique), aversion A et
                 préférences = BASE_PROFILE ; valeurs modifiables ici.
    MODE AGENT : part de CONSTRAINTS (jamais de BASE_CONSTRAINTS) et utilise
                 UNIQUEMENT la requête utilisateur reçue à l'exécution;
                 requiert risk_aversion_A pour éviter tout repli implicite
                 sur le profil BASE. Ne modifie jamais les constantes globales.

    Un agent questionnaire ne peut pas écraser les méthodes de marché, les
    rendements futurs, le taux Rf, le solveur ni la politique minimum 1 %.
    """
    if mode not in VALID_EXECUTION_MODES:
        raise ValueError(f"Mode d'exécution inconnu : {mode!r}")
    cfg = _get_engine_defaults()
    if mode == "base":
        if agent_request is not None:
            raise ValueError("Le mode BASE n'accepte pas de requête agent.")
        _check_base_sources()
        # Seule source des contraintes BASE : le mode AGENT, lui, garde CONSTRAINTS.
        cfg["constraints"] = copy.deepcopy(BASE_CONSTRAINTS)
        profile_request = BASE_PROFILE
    else:
        if not isinstance(agent_request, Mapping):
            raise ValueError("Mode AGENT : une requête du questionnaire est obligatoire.")
        if "risk_aversion_A" not in agent_request:
            raise ValueError("Mode AGENT : risk_aversion_A doit venir du questionnaire.")
        profile_request = agent_request
    cfg = apply_portfolio_request(profile_request, settings=cfg)
    cfg["execution_mode"] = mode
    return cfg


def _check_base_sources() -> None:
    """Garantir que BASE_CONSTRAINTS est la SEULE source des contraintes du mode BASE.

    - BASE_PROFILE ne peut contenir que l'aversion A et les préférences ;
    - BASE_CONSTRAINTS a au moins toutes les clés de CONSTRAINTS (aucune oubliée,
      donc aucun repli silencieux) et aucune clé inconnue (faute de frappe) ;
    - les noms de classes d'actifs / types d'instruments des limites existent.
    """
    duplicated = sorted(set(BASE_PROFILE) - BASE_PROFILE_ALLOWED_KEYS)
    if duplicated:
        raise ValueError(
            f"BASE_PROFILE ne doit contenir aucune contrainte : {duplicated}. "
            "Les déplacer dans BASE_CONSTRAINTS (source unique du mode BASE).")
    missing = sorted(set(CONSTRAINTS) - set(BASE_CONSTRAINTS))
    if missing:
        raise ValueError(f"BASE_CONSTRAINTS incomplet, clés absentes : {missing}")
    unknown = sorted(set(BASE_CONSTRAINTS) - set(CONSTRAINTS) - {"unknown_exposure_policy"})
    if unknown:
        raise ValueError(f"Clés inconnues dans BASE_CONSTRAINTS : {unknown}")
    limits = BASE_CONSTRAINTS["group_limits"]
    unknown_dims = sorted(set(limits) - set(CONSTRAINTS["group_limits"]))
    if unknown_dims:
        raise ValueError(f"Dimensions de group_limits inconnues dans BASE_CONSTRAINTS : {unknown_dims}")
    for dimension, valid in (("asset_class", VALID_ASSET_CLASSES), ("instrument_type", VALID_INSTRUMENT_TYPES)):
        valid_keys = {v.casefold() for v in valid}
        bad = sorted(g for g in limits.get(dimension, {}) if str(g).strip().casefold() not in valid_keys)
        if bad:
            raise ValueError(f"group_limits.{dimension} : groupes inexistants {bad} (valides : {sorted(valid)}).")


def _validate_group_limits(group_limits: Mapping[str, Any]) -> None:
    """Structure des plafonds agrégés : bornes min/max dans [0, 1], min <= max."""
    if not isinstance(group_limits, Mapping):
        raise TypeError("group_limits doit être un mapping par dimension.")
    for dimension, groups in group_limits.items():
        if dimension not in CONSTRAINTS["group_limits"]:
            raise ValueError(f"Dimension de limite inconnue : {dimension}")
        if not isinstance(groups, Mapping):
            raise TypeError(f"group_limits.{dimension} doit être un mapping.")
        for group, bounds in groups.items():
            if not str(group).strip() or not isinstance(bounds, Mapping) or not bounds:
                raise ValueError(f"Limites invalides : {dimension}/{group}.")
            if set(bounds) - {"min", "max"}:
                raise ValueError(f"Bornes inconnues : {dimension}/{group}.")
            values = {k: _weight(v, f"group_limits.{dimension}.{group}.{k}") for k, v in bounds.items()}
            if "min" in values and "max" in values and values["min"] > values["max"]:
                raise ValueError(f"Min > max pour {dimension}/{group}.")


def get_base_settings() -> dict[str, Any]:
    """Alias explicite pour tests, simulations et démo manuelle."""
    return get_settings(mode="base")


def get_agent_settings(agent_request: Mapping[str, Any]) -> dict[str, Any]:
    """Entrée à utiliser dans le pipeline réel, après validation agent."""
    return get_settings(mode="agent", agent_request=agent_request)


def get_return_method(
    asset_class: str,
    instrument_type: str,
    *,
    symbol: str | None = None,
    settings: Mapping[str, Any] | None = None,
) -> str:
    """Choisir une des quatre méthodes : symbole > instrument > classe."""
    config = settings if settings is not None else get_settings()
    model = config["estimation"]
    if model["mode"] == "single_method":
        method = model["single_method"]
    else:
        ticker = str(symbol or "").strip().upper()
        method = (
            model["method_by_symbol"].get(ticker)
            or model["method_by_instrument_type"].get(instrument_type)
            or model["method_by_asset_class"].get(asset_class)
            or model["single_method"]
        )
    if method not in VALID_RETURN_METHODS:
        raise ValueError(f"Méthode de rendement inconnue : {method!r}")
    return method


def get_capm_benchmark(
    symbol: str,
    metadata: Mapping[str, Any],
    *,
    available_symbols: set[str] | None = None,
    settings: Mapping[str, Any] | None = None,
) -> str | None:
    """Choisir un ETF de référence selon l'exposition économique observable.

    Actions : ticker spécifique, puis combinaison pays/secteur, puis pays.
    ETF : exclusivement un mapping explicite de sous-jacent, PAS le pays
    de cotation ni un pays 'Non classé'. Crypto : pas de benchmark CAPM.

    Renvoie None si aucune correspondance fiable n'est configurée.
    """
    config = settings if settings is not None else get_settings()
    rules = config["benchmarks"]
    ticker = str(symbol).strip().upper()
    kind = str(metadata.get("instrument_type", "")).strip()

    if not ticker:
        raise ValueError("Symbol vide.")
    if kind == "Cryptocurrency":
        return None

    benchmark = rules["symbol_overrides"].get(ticker)
    if benchmark is None and kind == "ETF":
        benchmark = rules["etf_overrides"].get(ticker)
        if benchmark is None:
            benchmark = rules["fallback_for_unknown_etf"]
    elif benchmark is None and kind == "Stock":
        country = str(metadata.get("country") or "").strip()
        sector = str(metadata.get("sector") or "").strip()
        benchmark = rules["stock_country_sector"].get(f"{country}|{sector}")
        if benchmark is None:
            benchmark = rules["stock_country"].get(country)
        if benchmark is None:
            benchmark = rules["fallback_for_unknown_stock"]

    if benchmark is None:
        return None
    benchmark = str(benchmark).strip().upper()
    if rules["avoid_self_benchmark"] and benchmark == ticker:
        raise ValueError(f"Benchmark auto-référent interdit : {ticker}")
    if available_symbols is not None and rules["require_available_returns"]:
        if benchmark not in available_symbols:
            raise ValueError(f"Benchmark {benchmark} indisponible pour {ticker}")
    return benchmark


def get_risk_band(
    A: float,
    *,
    settings: Mapping[str, Any] | None = None,
) -> str:
    """Nom indicatif de la tranche de A (sans définir l'allocation)."""
    config = settings if settings is not None else get_settings()
    limits = config["risk_aversion"]
    value = _finite_number(A, "A")
    if not limits["min"] <= value <= limits["max"]:
        raise ValueError(f"A doit appartenir à [{limits['min']}, {limits['max']}].")
    for band in limits["bands"]:
        if value <= band["upper"]:
            return band["name"]
    raise ValueError("Aucun intervalle de risque ne correspond à A.")


def _finite_number(value: Any, name: str) -> float:
    """Éviter booléens, NaN, inf et valeurs non numériques."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} doit être un nombre réel.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} doit être fini.")
    return result


def _weight(value: Any, name: str, *, allow_none: bool = False) -> float | None:
    """Vérifier un poids exprimé en fraction de capital entre 0 et 1."""
    if value is None and allow_none:
        return None
    number = _finite_number(value, name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} doit appartenir à [0, 1].")
    return number


def normalize_preference(value: Any, name: str) -> dict[str, Any]:
    """Une réponse du questionnaire, sous la forme {"mode", "weight"}.

    "exact" exige une fraction finie dans [0, 1] (0.45 = 45 %) : un pourcentage brut comme 45 est refusé,
    jamais lu comme 45 fois le capital. "exclude" et "neutral" n'ont pas de poids. Les chaînes
    "exclude" et "neutral" sont acceptées comme raccourcis ; les anciens niveaux less/more/require sont refusés.
    """
    if isinstance(value, str):
        value = {"mode": value, "weight": None}
    if not isinstance(value, Mapping) or set(value) - {"mode", "weight"} or "mode" not in value:
        raise ValueError(f"{name} : préférence attendue sous la forme {{'mode': ..., 'weight': ...}}.")
    mode = str(value["mode"]).strip().lower()
    if mode not in PREFERENCE_MODES:
        raise ValueError(f"{name} : mode {value['mode']!r} inconnu (valides : {sorted(PREFERENCE_MODES)}).")
    weight = value.get("weight")
    if mode != "exact":
        if weight is not None:
            raise ValueError(f"{name} : le mode {mode!r} n'accepte pas de poids.")
        return {"mode": mode, "weight": None}
    if weight is None:
        raise ValueError(f"{name} : le mode 'exact' exige un poids.")
    number = _finite_number(weight, f"{name}.weight")
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name}.weight doit être une fraction dans [0, 1] (45 % = 0.45), reçu {number}.")
    return {"mode": "exact", "weight": number}


def _normalize_preferences(preferences: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """Préférences par dimension et par groupe ; les neutres sont retirées (elles n'ajoutent rien)."""
    if not isinstance(preferences, Mapping):
        raise TypeError("preferences doit être un dictionnaire par dimension.")
    normalized: dict[str, dict[str, dict[str, Any]]] = {}
    for dimension, values in preferences.items():
        if dimension not in PREFERENCE_DIMENSIONS:
            raise ValueError(f"Dimension de préférence inconnue : {dimension}")
        if not isinstance(values, Mapping):
            raise TypeError(f"La dimension {dimension} doit être un mapping.")
        output: dict[str, dict[str, Any]] = {}
        for key, raw in values.items():
            parts = [p.strip() for p in str(key).split(PREFERENCE_GROUP_SEPARATOR)]
            if not all(parts):
                raise ValueError(f"Groupe vide dans la dimension {dimension} : {key!r}.")
            item = PREFERENCE_GROUP_SEPARATOR.join(parts)
            if dimension == "symbol":
                item = item.upper()
            pref = normalize_preference(raw, f"preferences.{dimension}.{item}")
            if pref["mode"] != "neutral":
                output[item] = pref
        if output:
            normalized[dimension] = output
    return normalized


def validate_settings(settings: Mapping[str, Any] | None = None) -> None:
    """Vérifier la cohérence interne ; n'ouvre aucun fichier de données."""
    cfg = settings if settings is not None else get_settings()
    data, est, cov = cfg["data"], cfg["estimation"], cfg["covariance"]
    constraints, cash = cfg["constraints"], cfg["cash"]
    risk, optim = cfg["risk_aversion"], cfg["optimization"]

    if not isinstance(data["min_observations"], int) or isinstance(data["min_observations"], bool) or data["min_observations"] < 2:
        raise ValueError("data.min_observations doit être >= 2.")
    if not isinstance(data["periods_per_year"], int) or data["periods_per_year"] <= 0:
        raise ValueError("data.periods_per_year doit être un entier > 0.")
    if data["return_column"] == data["forward_return_column"]:
        raise ValueError("Le rendement futur ne peut pas être l'input des estimations.")
    if not data["never_fill_missing_returns"]:
        raise ValueError("Ne jamais fabriquer de rendements manquants (zero-fill/ffill).")
    if est["periods_per_year"] != data["periods_per_year"] or cov["periods_per_year"] != data["periods_per_year"]:
        raise ValueError("Annualisation incohérente entre données, mu et Sigma.")
    if est["mode"] not in {"by_asset_class", "single_method"}:
        raise ValueError("estimation.mode invalide.")
    methods = [est["single_method"], *est["method_by_asset_class"].values(),
               *est["method_by_instrument_type"].values(), *est["method_by_symbol"].values()]
    if any(m not in VALID_RETURN_METHODS for m in methods):
        raise ValueError("Méthode d'estimation non reconnue.")
    if any(k not in VALID_ASSET_CLASSES for k in est["method_by_asset_class"]):
        raise ValueError("Classe inconnue dans method_by_asset_class.")
    if any(k not in VALID_INSTRUMENT_TYPES for k in est["method_by_instrument_type"]):
        raise ValueError("Instrument inconnu dans method_by_instrument_type.")

    for method in VALID_RETURN_METHODS:
        params = est[method]
        key = "min_paired_observations" if method.startswith("capm") else "min_observations"
        minimum = params[key]
        lookback = params["lookback_observations"]
        if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 2:
            raise ValueError(f"Minimum d'observations invalide pour {method}.")
        # None = utiliser toutes les observations historiques disponibles,
        # avec une fenêtre propre à chaque actif ou paire actif-benchmark.
        if lookback is not None and (
            not isinstance(lookback, int) or isinstance(lookback, bool) or lookback < minimum
        ):
            raise ValueError(f"Fenêtre d'estimation trop courte pour {method}.")
        if method.startswith("capm"):
            hist_lookback = params["historical_lookback_observations"]
            if hist_lookback is not None and (
                not isinstance(hist_lookback, int)
                or isinstance(hist_lookback, bool)
                or hist_lookback < 2
            ):
                raise ValueError(f"Fenêtre historique du CAPM invalide pour {method}.")
            _weight(params["alpha"], f"{method}.alpha")
            _finite_number(params["rf_annual"], f"{method}.rf_annual")
        if method == "ewma" and params["half_life_observations"] <= 0:
            raise ValueError("Demi-vie EWMA invalide.")
    _finite_number(est["capm_shrinkage"]["erp_annual"], "capm_shrinkage.erp_annual")
    for bench, premium in est["capm_benchmark_shrinkage"]["erp_annual_by_benchmark"].items():
        if not bench or not str(bench).strip():
            raise ValueError("Ticker de benchmark ERP invalide.")
        _finite_number(premium, f"erp_annual_by_benchmark.{bench}")
    if est["capm_benchmark_shrinkage"]["missing_premium_policy"] != "error":
        raise ValueError("Les primes de benchmarks manquantes doivent déclencher une erreur.")

    if cov["method"] not in VALID_COVARIANCE_METHODS:
        raise ValueError("Méthode de covariance inconnue.")
    if cov["min_joint_observations"] < 2 or (
            cov["lookback_observations"] is not None and cov["lookback_observations"] < cov["min_joint_observations"]):
        raise ValueError("Historique joint insuffisant pour Ledoit-Wolf.")
    history = cfg["covariance_history"]
    if history["method"] != "ledoit_wolf" or not isinstance(history["require_full_horizon"], bool):
        raise ValueError("covariance_history : méthode ledoit_wolf et require_full_horizon booléen attendus.")
    delay = history["max_start_delay_business_days"]
    if not isinstance(delay, int) or isinstance(delay, bool) or not 0 <= delay <= 10:
        raise ValueError("max_start_delay_business_days doit être un entier entre 0 et 10 (calendriers seulement).")
    holdings = cfg["portfolio_holdings"]
    counts = [holdings[k] for k in ("min_count", "max_count")]
    if any(not isinstance(n, int) or isinstance(n, bool) or n < 1 for n in counts) or counts != sorted(counts):
        raise ValueError("portfolio_holdings : entiers min_count <= max_count attendus.")
    if _finite_number(holdings["max_marginal_utility_cost"], "max_marginal_utility_cost") < 0:
        raise ValueError("portfolio_holdings.max_marginal_utility_cost doit être >= 0.")
    held = _weight(holdings["min_held_weight"], "portfolio_holdings.min_held_weight")
    if not 0 < held or held * holdings["min_count"] > 1:
        raise ValueError("portfolio_holdings : min_count positions à min_held_weight dépassent 100 %.")
    if cov["sample"]["min_pairwise_observations"] < 2:
        raise ValueError("min_pairwise_observations doit être >= 2.")
    if cov["ledoit_wolf"]["target"] != "scaled_identity":
        raise ValueError("La cible Ledoit-Wolf prévue est scaled_identity.")
    if not cov["ledoit_wolf"]["shrinkage_intensity"] == "auto":
        raise ValueError("La méthode Ledoit-Wolf doit estimer automatiquement le shrinkage.")

    if risk["parameter_name"] != "A" or optim["risk_aversion_parameter"] != "A":
        raise ValueError("Le coefficient d'aversion utilisé doit être A.")
    a_min = _finite_number(risk["min"], "risk_aversion.min")
    a_max = _finite_number(risk["max"], "risk_aversion.max")
    a_default = _finite_number(risk["default"], "risk_aversion.default")
    if not 0 < a_min <= a_default <= a_max:
        raise ValueError("Intervalle d'aversion au risque incohérent.")
    uppers = [band["upper"] for band in risk["bands"]]
    if not uppers or uppers != sorted(uppers) or uppers[-1] != a_max:
        raise ValueError("Bornes des profils A incohérentes.")

    floor = _weight(constraints["min_held_weight"], "min_held_weight")
    if not 0 < floor < 1:
        raise ValueError("Le minimum par actif détenu doit appartenir à ]0,1[.")
    cap = _weight(constraints["max_weight_per_asset"], "max_weight_per_asset", allow_none=True)
    if cap is not None and cap < floor:
        raise ValueError("Le poids maximum par titre est inférieur au minimum détenu.")
    if constraints.get("unknown_exposure_policy", "strict") not in UNKNOWN_EXPOSURE_POLICIES:
        raise ValueError(f"unknown_exposure_policy doit valoir {sorted(UNKNOWN_EXPOSURE_POLICIES)}.")
    _validate_group_limits(constraints["group_limits"])
    min_cash = _weight(constraints["min_cash_weight"], "min_cash_weight")
    max_cash = _weight(constraints["max_cash_weight"], "max_cash_weight")
    if min_cash > max_cash:
        raise ValueError("Minimum de cash supérieur au maximum de cash.")
    if not constraints["long_only"] or not constraints["fully_invested"]:
        raise ValueError("Cette configuration prévoit un portefeuille long-only et investi à 100 %.")
    if constraints["minimum_holding_method"] != "prune_reoptimize":
        raise ValueError("Méthode de minimum par titre non reconnue.")
    if not isinstance(constraints["minimum_holding_max_iterations"], int) or constraints["minimum_holding_max_iterations"] < 1:
        raise ValueError("Nombre d'itérations de l'heuristique invalide.")
    if cash["symbol"] in constraints["required_symbols"] or cash["symbol"] in constraints["excluded_symbols"]:
        raise ValueError("Traiter le cash séparément des obligations sur titres.")
    if not cash["enabled"] and constraints["min_cash_weight"] > 0:
        raise ValueError("Cash désactivé malgré un minimum de liquidité positif.")
    _finite_number(cash["annual_expected_return"], "cash.annual_expected_return")
    if _finite_number(cash["annual_volatility"], "cash.annual_volatility") < 0:
        raise ValueError("La volatilité cash ne peut pas être négative.")
    if set(constraints["required_symbols"]) & set(constraints["excluded_symbols"]):
        raise ValueError("Un titre ne peut pas être requis et exclu simultanément.")
    for sym, weight in constraints["required_symbol_min_weights"].items():
        _weight(weight, f"required_symbol_min_weights.{sym}")
        if weight < floor:
            raise ValueError(f"Le titre {sym} requis a un plancher inférieur au minimum détenu.")
    if optim["solver"] != "SLSQP":
        raise ValueError("Solveur non couvert par la configuration actuelle.")
    if optim["constraint_tolerance"] <= 0 or optim["sum_weights_tolerance"] <= 0:
        raise ValueError("Les tolérances d'optimisation doivent être positives.")
    reg = cfg.get("regularization", REGULARIZATION)  # absente d'une ancienne configuration: pénalités nulles
    for key in ("diversification_penalty", "high_volatility_penalty", "volatility_threshold"):
        if _finite_number(reg[key], f"regularization.{key}") < 0:
            raise ValueError(f"regularization.{key} doit être fini et non négatif.")
    if "etf_only" in constraints:
        raise ValueError("etf_only est remplacé par instrument_selection (etf_only | mixed | stocks_only).")
    if constraints["instrument_selection"] not in INSTRUMENT_SELECTION:
        raise ValueError(f"instrument_selection doit valoir {sorted(INSTRUMENT_SELECTION)}.")
    if set(cfg["preferences"]["modes"]) != PREFERENCE_MODES:
        raise ValueError("Les modes de préférence doivent être exactement exclude, neutral et exact.")
    prefs = cfg.get("agent_preferences", {})
    if _normalize_preferences(prefs) != {d: g for d, g in prefs.items() if g}:
        raise ValueError("agent_preferences n'est pas sous forme normalisée {mode, weight}.")


def apply_portfolio_request(
    request: Mapping[str, Any],
    *,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fusion limitée d'une requête agent avec les réglages du portefeuille.

    L'agent ne peut pas modifier les modèles de marché, les fenêtres, les
    benchmarks ou les paramètres solveur par cette fonction.

    Champs reconnus : risk_aversion_A, min_cash_weight, max_cash_weight,
    max_weight_per_asset, instrument_selection (etf_only accepté comme
    alias booléen), excluded_symbols, required_symbols,
    required_symbol_min_weights, excluded_asset_classes, excluded_* autres,
    group_limits, preferences ({dimension: {groupe: {mode, weight}}}).
    """
    if not isinstance(request, Mapping):
        raise TypeError("request doit être un mapping/dictionnaire.")
    cfg = copy.deepcopy(settings) if settings is not None else get_settings()
    allowed = {
        "risk_aversion_A", "min_cash_weight", "max_cash_weight",
        "max_weight_per_asset", "instrument_selection", "etf_only", "excluded_symbols",
        "required_symbols", "required_symbol_min_weights", "preferences",
        "excluded_asset_classes", "excluded_instrument_types", "excluded_sectors",
        "excluded_countries", "excluded_regions", "excluded_themes", "excluded_factors",
        "group_limits",
    }
    unknown = set(request) - allowed
    if unknown:
        raise ValueError(f"Paramètres non autorisés dans la requête agent : {sorted(unknown)}")

    if "risk_aversion_A" in request:
        value = _finite_number(request["risk_aversion_A"], "risk_aversion_A")
        if not cfg["risk_aversion"]["min"] <= value <= cfg["risk_aversion"]["max"]:
            raise ValueError("Aversion au risque A hors plage configurée.")
        cfg["risk_aversion"]["default"] = value

    c = cfg["constraints"]
    for field in ("min_cash_weight", "max_cash_weight", "max_weight_per_asset"):
        if field in request:
            c[field] = _weight(request[field], field, allow_none=field == "max_weight_per_asset")
    selection = request.get("instrument_selection")
    if selection is not None:
        selection = str(selection).strip().lower()
        if selection not in INSTRUMENT_SELECTION:
            raise ValueError(f"instrument_selection doit valoir {sorted(INSTRUMENT_SELECTION)}, reçu {selection!r}.")
    if "etf_only" in request:  # alias de l'ancien contrat booléen
        if not isinstance(request["etf_only"], bool):
            raise TypeError("etf_only doit être un booléen.")
        alias = "etf_only" if request["etf_only"] else "mixed"
        if selection is not None and selection != alias:
            raise ValueError(f"etf_only={request['etf_only']} contredit instrument_selection={selection!r}.")
        selection = alias
    if selection is not None:
        c["instrument_selection"] = selection
    for field in ("excluded_symbols", "required_symbols"):
        if field in request:
            values = request[field]
            if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple, set)):
                raise TypeError(f"{field} doit être une liste de tickers.")
            clean = [str(v).strip().upper() for v in values]
            if any(not s for s in clean):
                raise ValueError(f"{field} contient un ticker vide.")
            c[field] = sorted(set(clean))
    if "required_symbol_min_weights" in request:
        overrides = request["required_symbol_min_weights"]
        if not isinstance(overrides, Mapping):
            raise TypeError("required_symbol_min_weights doit être un dictionnaire.")
        c["required_symbol_min_weights"] = {
            str(s).strip().upper(): _weight(w, f"required_symbol_min_weights.{s}")
            for s, w in overrides.items()
        }
        if any(not s for s in c["required_symbol_min_weights"]):
            raise ValueError("Ticker requis vide.")
        c["required_symbols"] = sorted(set(c["required_symbols"]) | set(c["required_symbol_min_weights"]))

    # Exclusions d'univers : l'agent ne peut exclure qu'à travers ce contrat.
    for field in (
        "excluded_asset_classes", "excluded_instrument_types", "excluded_sectors",
        "excluded_countries", "excluded_regions", "excluded_themes", "excluded_factors",
    ):
        if field in request:
            values = request[field]
            if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple, set)):
                raise TypeError(f"{field} doit être une liste.")
            clean = [str(v).strip() for v in values]
            if any(not item for item in clean):
                raise ValueError(f"{field} contient une valeur vide.")
            c[field] = sorted(set(clean))

    if "group_limits" in request:
        limits = request["group_limits"]
        if not isinstance(limits, Mapping):
            raise TypeError("group_limits doit être un mapping par dimension.")
        for dimension, groups in limits.items():
            if dimension not in c["group_limits"]:
                raise ValueError(f"Dimension de limite inconnue : {dimension}")
            if not isinstance(groups, Mapping):
                raise TypeError(f"group_limits.{dimension} doit être un mapping.")
            normalized_groups = {}
            for group_name, bounds in groups.items():
                label = str(group_name).strip()
                if not label or not isinstance(bounds, Mapping):
                    raise ValueError(f"Limites invalides : {dimension}/{group_name}.")
                unexpected_bounds = set(bounds) - {"min", "max"}
                if unexpected_bounds or not bounds:
                    raise ValueError(f"Bornes inconnues/absentes : {dimension}/{group_name}.")
                normalized_bounds = {
                    key: _weight(value, f"group_limits.{dimension}.{label}.{key}")
                    for key, value in bounds.items()
                }
                if ("min" in normalized_bounds and "max" in normalized_bounds
                        and normalized_bounds["min"] > normalized_bounds["max"]):
                    raise ValueError(f"Min > max pour {dimension}/{label}.")
                normalized_groups[label] = normalized_bounds
            c["group_limits"][dimension] = normalized_groups

    if "preferences" in request:
        cfg["agent_preferences"] = _normalize_preferences(request["preferences"])

    validate_settings(cfg)
    return cfg


def main() -> None:
    """Vérifier la configuration sans télécharger le Parquet ni utiliser AWS."""
    parser = argparse.ArgumentParser(description="Configuration MonPort / Datathon 2026")
    parser.add_argument("--show", action="store_true", help="Afficher toutes les sections en JSON")
    parser.add_argument("--mode", choices=sorted(VALID_EXECUTION_MODES), default="base")
    parser.add_argument(
        "--request-json", default=None,
        help='JSON de requête agent, obligatoire pour --mode agent ; ex: {"risk_aversion_A":8}',
    )
    args = parser.parse_args()
    request = json.loads(args.request_json) if args.request_json is not None else None
    config = get_settings(mode=args.mode, agent_request=request)
    validate_settings(config)
    print("CONFIG OK")
    print("Mode d'exécution :", config["execution_mode"].upper())
    print("Parquet :", config["data"]["parquet_source"])
    print("Rendements :", ", ".join(sorted(VALID_RETURN_METHODS)))
    print("Covariance :", config["covariance"]["method"])
    print("Aversion A :", config["risk_aversion"]["min"], "à", config["risk_aversion"]["max"])
    print("Minimum par actif détenu :", f"{config['constraints']['min_held_weight']:.0%}")
    print("Aversion A du run :", config["risk_aversion"]["default"])
    print("Rf CAPM :", f"{config['estimation']['capm_shrinkage']['rf_annual']:.1%}")
    print("Lookback EWMA :", config["estimation"]["ewma"]["lookback_observations"])
    if args.show:
        print(json.dumps(config, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

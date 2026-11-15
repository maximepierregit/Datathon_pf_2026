"""Classement de l'univers dans les catégories du frontend (classes, régions, thèmes, facteurs).

Le dataset de `create_opt_inputs` ne garde souvent que le nom, la devise, le type d'instrument et la
classe brute. On déduit donc les catégories à partir de toutes les colonnes disponibles (secteur,
industrie, pays, catégorie du FNB) et, à défaut, des mots du nom et du suffixe boursier.

Les identifiants correspondent à `frontend/src/data/catalog.ts` et `frontend/src/types.ts`.
"""

from __future__ import annotations

import logging
import re

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ASSET_CLASSES = ["actions", "obligations", "immobilier", "or", "crypto", "liquidites"]
REGIONS = ["canada", "usa", "europe", "asie", "emergents"]
THEMES = [
    "tech", "ia", "robotique", "sante", "energie-propre", "esg", "fossiles", "finance",
    "immobilier", "consommation", "industrie", "armement", "vice",
]
# Thématiques étiquetées à la main (colonne `theme` du dataset, issue de data-prep/themes.csv). Quand le
# dataset fournit cette colonne, elle fait foi pour ces thématiques; les heuristiques ne servent qu'aux autres.
CURATED_THEMES = {"tech", "ia", "robotique", "energie-propre", "esg", "armement", "vice"}
THEME_SEP_IN = ";"  # séparateur de la colonne `theme` du dataset
FACTORS = ["taille", "qualite", "momentum", "value"]
INSTRUMENTS = ["Stock", "ETF", "Cryptocurrency", "Cash"]

NO_REGION = "aucune"  # classes hors actions/immobilier: les préférences régionales ne s'y appliquent pas
WORLD = "monde"  # FNB mondiaux ou multirégions

# Hypothèses par classe, identiques à CLASS_ASSUMPTIONS (frontend/src/data/catalog.ts).
CLASS_PRIOR_MU = {"actions": 0.07, "obligations": 0.035, "immobilier": 0.055, "or": 0.04, "crypto": 0.15, "liquidites": 0.025}

CASH_SYMBOL = "CASH-CAD"
CASH_NAME = "Liquidités (encaisse en CAD)"
SEP = "|"


def _text(row: pd.Series) -> str:
    parts = [row.get(c) for c in ("name", "category_group", "category", "sector", "industry", "asset_class_raw")]
    return " " + " ".join(str(p) for p in parts if isinstance(p, str)).lower() + " "


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def instrument_of(row: pd.Series) -> str:
    raw = str(row.get("instrument_type") or "").lower()
    if "crypto" in raw:
        return "Cryptocurrency"
    if raw in ("etf", "fund", "fnb"):
        return "ETF"
    if raw == "cash":
        return "Cash"
    if raw in ("stock", "equity"):
        return "Stock"
    return "ETF" if " etf" in _text(row) else "Stock"


def asset_class_of(row: pd.Series, instrument: str) -> str:
    t = _text(row)
    raw = str(row.get("asset_class_raw") or "").lower()
    if instrument == "Cash":
        return "liquidites"
    if instrument == "Cryptocurrency" or raw in ("alternative", "crypto", "cryptocurrency") or _has(t, "bitcoin", " ether", "crypto"):
        return "crypto"
    if instrument == "Stock":
        # Une action se classe par son secteur, pas par les mots de son nom (« Goldman » n'est pas de l'or,
        # une minière aurifère reste une action).
        return "immobilier" if str(row.get("sector") or "") == "Real Estate" else "actions"
    if raw == "fixed income" or _has(t, " bond", "obligation", "treasury", "fixed income", "t-bill"):
        return "obligations"
    if raw in ("money market", "cash") or _has(t, "money market", "marché monétaire", "high interest savings", "cash management"):
        return "liquidites"
    if raw == "real estate" or str(row.get("sector") or "") == "Real Estate" or _has(t, "reit", "real estate", "real asset", "immobili"):
        return "immobilier"
    if raw == "commodities" or _has(t, "gold", "commodit", "precious metal", "silver"):
        return "or"
    return "actions"


_COUNTRY_REGION = {
    "canada": "canada",
    "united states": "usa",
    "france": "europe", "netherlands": "europe", "germany": "europe", "belgium": "europe", "luxembourg": "europe",
    "united kingdom": "europe", "switzerland": "europe", "italy": "europe", "spain": "europe", "ireland": "europe",
    "japan": "asie", "australia": "asie", "south korea": "asie", "hong kong": "asie", "singapore": "asie",
    "china": "emergents", "india": "emergents", "brazil": "emergents", "mexico": "emergents", "taiwan": "emergents",
}
_SUFFIX_REGION = {".TO": "canada", ".V": "canada", ".NE": "canada", ".PA": "europe", ".AS": "europe", ".DE": "europe",
                  ".L": "europe", ".SW": "europe", ".T": "asie", ".HK": "asie", ".AX": "asie"}


def region_of(symbol: str, row: pd.Series, asset_class: str, instrument: str) -> str:
    if asset_class not in ("actions", "immobilier"):
        return NO_REGION
    # Une action a un pays connu: il prime sur les mots du nom (« Philip Morris International » n'est pas mondial).
    country = str(row.get("country") or "").lower()
    if instrument == "Stock" and country in _COUNTRY_REGION:
        return _COUNTRY_REGION[country]
    t = _text(row)
    if _has(t, "emerging", "émergent", "latin america", "china", "india", "brazil"):
        return "emergents"
    if _has(t, "europe", "euro stoxx", "eurozone"):
        return "europe"
    if _has(t, "asia", "pacific", "japan", "korea", "australia"):
        return "asie"
    if _has(t, "global", "world", "international", "ex u.s", "ex-u.s", "eafe", "acwi", "developed markets", "mondial"):
        return WORLD
    if _has(t, "canada", "canadian", "tsx"):
        return "canada"
    if _has(t, "s&p 500", "russell", "u.s.", " us ", "american", "nasdaq"):
        return "usa"
    country = str(row.get("country") or "").lower()
    if country in _COUNTRY_REGION:
        return _COUNTRY_REGION[country]
    if instrument == "ETF":
        return WORLD if "." not in symbol else _SUFFIX_REGION.get(symbol[symbol.rfind("."):], WORLD)
    for suffix, region in _SUFFIX_REGION.items():
        if symbol.endswith(suffix):
            return region
    return "usa" if "." not in symbol else WORLD


def themes_of(row: pd.Series, asset_class: str) -> set[str]:
    t = _text(row)
    sector = str(row.get("sector") or "")
    out: set[str] = set()
    if sector in ("Information Technology", "Technology") or _has(t, "technolog", "software", "semiconductor"):
        out.add("tech")
    if re.search(r"\bai\b|artificial intelligence|intelligence artificielle|robotic", t):
        out |= {"ia", "tech"}
    if sector == "Health Care" or _has(t, "health", "santé", "pharma", "biotech"):
        out.add("sante")
    if _has(t, "clean energy", "renewable", "solar", "wind energy", "hydrogen", "énergie propre"):
        out.add("energie-propre")
    if sector == "Energy" or _has(t, "oil", " gas", "petrol", "pétrol", "pipeline", "énergie traditionnelle"):
        out.add("fossiles")
    if sector == "Financials" or _has(t, "bank", "banque", "insurance", "assurance"):
        out.add("finance")
    if asset_class == "immobilier":
        out.add("immobilier")
    if sector.startswith("Consumer") or _has(t, "consumer", "consommation", "retail"):
        out.add("consommation")
    if sector in ("Industrials", "Utilities") or _has(t, "infrastructure", "industri"):
        out.add("industrie")
    if _has(t, "aerospace & defense", "defense", "defence", "armement"):
        out.add("armement")
    if _has(t, "tobacco", "brewer", "distiller", "alcohol", "spirits", "wine", "tabac", "alcool", "cannabis",
            "casino", "gambling"):
        out.add("vice")
    return out


def curated_themes(row: pd.Series) -> set[str] | None:
    """Thématiques de la colonne `theme` (« tech;ia »). None si la colonne est absente ou vide pour ce symbole."""
    raw = row.get("theme")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return {x.strip().lower() for x in raw.split(THEME_SEP_IN) if x.strip()}


def factors_of(row: pd.Series, asset_class: str) -> set[str]:
    if asset_class != "actions":
        return set()
    t = _text(row)
    cap = str(row.get("market_cap") or "").lower()
    out: set[str] = set()
    if cap in ("small cap", "micro cap", "nano cap") or _has(t, "small cap", "small-cap", "russell 2000", "petites cap"):
        out.add("taille")
    if _has(t, "quality", "qualité"):
        out.add("qualite")
    if _has(t, " value", "dividend", "dividende"):
        out.add("value")
    if _has(t, "momentum"):
        out.add("momentum")
    return out


def classify(meta: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    """Ajoute instrument_type, asset_class (classes du frontend), region, themes, factors et fee."""
    meta = meta.copy()
    # Le dataset porte des thématiques étiquetées: elles font foi pour CURATED_THEMES (un symbole sans
    # étiquette n'en a donc aucune), les heuristiques complètent les autres (santé, finance, etc.).
    has_curated = "theme" in meta.columns and meta["theme"].notna().any()
    unknown: set[str] = set()
    instruments, classes, regions, themes, factors = [], [], [], [], []
    for symbol, row in meta.iterrows():
        inst = instrument_of(row)
        cls = asset_class_of(row, inst)
        instruments.append(inst)
        classes.append(cls)
        regions.append(region_of(str(symbol), row, cls, inst))
        tags = themes_of(row, cls)
        if has_curated:
            curated = curated_themes(row) or set()
            unknown |= curated - set(THEMES)
            tags = (tags - CURATED_THEMES) | (curated & set(THEMES))
        themes.append(tags)
        factors.append(factors_of(row, cls))
    if unknown:
        logger.warning("Thématiques inconnues ignorées dans la colonne `theme`: %s", sorted(unknown))

    # Momentum: le tiers des actions au meilleur rendement cumulé sur la période (calculé, pas déduit du nom).
    cumulative = (1 + returns.fillna(0.0)).prod() - 1
    equities = [s for s, c in zip(meta.index, classes) if c == "actions" and s in cumulative.index]
    if len(equities) >= 6:
        threshold = cumulative[equities].quantile(2 / 3)
        for i, s in enumerate(meta.index):
            if s in equities and cumulative[s] >= threshold:
                factors[i].add("momentum")

    meta["instrument_type"] = instruments
    meta["asset_class"] = classes
    meta["region"] = regions
    meta["themes"] = [SEP + SEP.join(sorted(x)) + SEP if x else "" for x in themes]
    meta["factors"] = [SEP + SEP.join(sorted(x)) + SEP if x else "" for x in factors]

    # Frais annuels estimés (fraction). Une colonne `expense_ratio` en %, si elle existe, a priorité.
    default_fee = {"ETF": 0.0020, "Stock": 0.0, "Cryptocurrency": 0.0040, "Cash": 0.0}
    fee = meta["instrument_type"].map(default_fee).astype(float)
    if "expense_ratio" in meta.columns:
        known = pd.to_numeric(meta["expense_ratio"], errors="coerce") / 100
        fee = known.where(known.notna(), fee)
    meta["fee"] = fee.fillna(0.0)
    return meta


def cash_series(index: pd.DatetimeIndex, annual_rate: float) -> pd.Series:
    """Rendement quotidien constant de l'encaisse (volatilité nulle)."""
    return pd.Series(np.full(len(index), annual_rate / 252), index=index, name=CASH_SYMBOL)

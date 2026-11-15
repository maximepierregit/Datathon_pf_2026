"""Preuves du responsable des risques: des faits chiffrés calculés par le code, jamais par le modèle.

Chaque preuve porte un identifiant stable (`pire_baisse`, `crypto`, `inflation_ca`…). L'agent Risque reçoit la liste
et cite des identifiants sous chaque mise en garde; le code les résout ensuite sur le portefeuille présenté (un
mélange 80/20 a ses propres chiffres). Le frontend affiche la valeur, le repère, la source et la série
(`Evidence` de frontend/src/types.ts).
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from .macro import get_macro, latest_snapshot
from .market import UNKNOWN, Market, joint_window
from .schemas import ConstraintCheck, InvestorForm, Portfolio

logger = logging.getLogger(__name__)

PRICES = "Cours quotidiens en CAD, dividendes réinvestis (Yahoo Finance)"
MODEL = "Moyenne et variations estimées sur ces cours par l’optimiseur MonPort"
HOLDINGS = "Composition calculée par l’optimiseur MonPort"
CATEGORIES = "Secteurs et pays des titres (Yahoo Finance)"
CHECKS = "Vérification du juge, recalculée par le code"
LINE_CAP = 0.40
WORST_YEAR_Z = 2.33  # même « pire année » que metricsOf() du frontend: 1 chance sur 100
MAX_CITED = 3

# Indicateurs macro montrés au client: (pays, indicateur) -> (identifiant, libellé, source)
MACRO = {
    ("CA", "policy_rate"): ("taux_directeur_ca", "Taux directeur au Canada", "Banque du Canada"),
    ("CA", "inflation_yoy"): ("inflation_ca", "Inflation sur un an au Canada", "Banque du Canada (IPC)"),
    ("CA", "yield_10y"): ("taux_10ans_ca", "Taux des obligations à 10 ans au Canada", "Banque du Canada"),
    ("CA", "spread_10y_2y"): ("ecart_10_2_ca", "Écart entre les taux à 10 ans et à 2 ans au Canada", "Banque du Canada"),
    ("CA", "unemployment_rate"): ("chomage_ca", "Chômage au Canada", "OCDE, via FRED (Réserve fédérale de St. Louis)"),
    ("US", "policy_rate"): ("taux_directeur_us", "Taux directeur aux États-Unis", "FRED (Réserve fédérale de St. Louis)"),
    ("US", "inflation_yoy"): ("inflation_us", "Inflation sur un an aux États-Unis", "FRED (Réserve fédérale de St. Louis)"),
}

# Repli quand l'agent ne cite rien de valide: un mot de sa mise en garde -> la preuve qui l'appuie.
KEYWORDS = [
    ("crypto", "crypto"), ("baisse", "pire_baisse"), ("perte", "pire_baisse"), ("chute", "pire_baisse"),
    ("mauvaise année", "mauvaise_annee"), ("secteur", "secteur"), ("techno", "secteur"), ("pays", "pays"),
    ("canada", "pays"), ("états-unis", "pays"), ("diversif", "diversification"), ("concentr", "ligne_max"),
    ("inflation", "inflation_ca"), ("taux", "taux_directeur_ca"), ("obligation", "obligations"),
    ("action", "actions"), ("horizon", "horizon"), ("bouge", "volatilite"), ("agité", "volatilite"),
]


def _item(id: str, label: str, value: float, unit: str, source: str, *, limit: Optional[tuple[str, float]] = None,
          period: Optional[tuple[str, str]] = None, series: Optional[pd.Series] = None,
          span: Optional[tuple[str, str]] = None) -> dict:
    out: dict = {"id": id, "label": label, "value": round(float(value), 4), "unit": unit, "source": source}
    if limit is not None:
        out["limit"] = {"label": limit[0], "value": round(float(limit[1]), 4)}
    if period is not None:
        out["period"] = list(period)
    if series is not None and len(series):
        out["series"] = [{"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 4)} for d, v in series.items()]
    if span is not None:
        out["span"] = list(span)
    return out


def _day(d) -> str:
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def value_curve(market: Market, weights: dict[str, float]) -> pd.Series:
    """Valeur du portefeuille (base 100) sur les dates communes, comme la perte maximale de `portfolio_metrics`."""
    symbols = [s for s, w in weights.items() if w > 0]
    total = sum(weights[s] for s in symbols)
    window = joint_window(market.returns[symbols], market.settings["covariance"])
    daily = window @ pd.Series({s: weights[s] / total for s in symbols})
    return 100 * (1 + daily).cumprod()


def drawdown(curve: pd.Series) -> tuple[float, str, str]:
    """Pire baisse d'un sommet à un creux, avec les dates du sommet et du creux."""
    dd = curve / curve.cummax() - 1
    trough = dd.idxmin()
    peak = curve.loc[:trough].idxmax()
    return float(dd.min()), _day(peak), _day(trough)


def portfolio_evidence(market: Market, p: Portfolio, form: InvestorForm, allocation: dict[str, float]) -> dict[str, dict]:
    """Les preuves d'un portefeuille: pertes historiques, répartition, concentration, horizon."""
    m = p.metrics
    if m is None or not p.positions:
        return {}
    out: dict[str, dict] = {}
    loss = form.max_acceptable_loss_pct
    accepted = ("Baisse que tu acceptes", -loss / 100) if loss is not None else None
    try:
        curve = value_curve(market, {x.symbol: x.weight for x in p.positions})
        worst, peak, trough = drawdown(curve)
        period = (_day(curve.index[0]), _day(curve.index[-1]))
        weekly = curve.resample("W-FRI").last().dropna()
        out["pire_baisse"] = _item("pire_baisse", "Pire baisse de ce portefeuille dans le passé", worst, "pct", PRICES,
                                   limit=accepted, period=period, series=weekly, span=(peak, trough))
    except (KeyError, ValueError):  # historique commun insuffisant: pas de courbe, la perte des indicateurs reste
        logger.exception("Courbe de valeur indisponible pour %s", p.id)
        period = None
        out["pire_baisse"] = _item("pire_baisse", "Pire baisse de ce portefeuille dans le passé", m.max_drawdown,
                                   "pct", PRICES, limit=accepted)
    out["mauvaise_annee"] = _item("mauvaise_annee", "Une très mauvaise année (1 chance sur 100)",
                                  m.expected_return - WORST_YEAR_Z * m.volatility, "pct", MODEL, limit=accepted,
                                  period=period)
    out["volatilite"] = _item("volatilite", "Variation typique en un an, à la hausse comme à la baisse", m.volatility,
                              "pct", MODEL, period=period)
    top = max(p.positions, key=lambda x: x.weight)
    out["ligne_max"] = _item("ligne_max", f"Plus grosse ligne : {top.name}", top.weight, "pct", HOLDINGS,
                             limit=("Limite par ligne", LINE_CAP))
    out["diversification"] = _item("diversification", "Placements qui comptent vraiment (diversification)",
                                   m.effective_n, "nombre", HOLDINGS, limit=("Lignes au total", m.n_positions))
    for key, groups, label in (("secteur", m.sector_weights, "Plus gros secteur"),
                               ("pays", m.country_weights, "Plus gros pays")):
        named = [(k, w) for k, w in groups.items() if k != UNKNOWN]
        if named:
            name, w = max(named, key=lambda kv: kv[1])
            out[key] = _item(key, f"{label} : {name}", w, "pct", CATEGORIES)
    for cls, label in (("actions", "Part en actions"), ("obligations", "Part en obligations"),
                       ("crypto", "Part en crypto-actifs")):
        out[cls] = _item(cls, label, allocation.get(cls, 0.0), "pct", HOLDINGS)
    out["horizon"] = _item("horizon", "Ton horizon de placement", form.horizon_years, "ans", "Ta réponse au questionnaire")
    return out


def macro_evidence() -> dict[str, dict]:
    """Les derniers chiffres macro, comparés à leur moyenne sur 5 ans. Source indisponible: aucune preuve macro."""
    try:
        macro = get_macro()
        rows = latest_snapshot(macro)["rows"]
    except Exception:  # noqa: BLE001 - le contexte macro est facultatif
        logger.info("Preuves macro indisponibles")
        return {}
    out: dict[str, dict] = {}
    frame = macro.frame
    for row in rows:
        spec = MACRO.get((row["country"], row["metric"]))
        if spec is None:
            continue
        id, label, source = spec
        at = pd.Timestamp(row["date"])
        hist = frame[(frame["country"] == row["country"]) & (frame["metric"] == row["metric"])
                     & (frame["date"] > at - pd.DateOffset(years=5))].set_index("date")["metric_value"]
        monthly = hist.resample("ME").last().dropna() / 100
        out[id] = _item(id, label, row["metric_value"] / 100, "pct", source,
                        limit=("Moyenne sur 5 ans", float(hist.mean()) / 100), period=(_day(hist.index[0]), row["date"]),
                        series=monthly)
    return out


def check_evidence(checks: list[ConstraintCheck]) -> list[dict]:
    """Les limites du client que le juge a trouvées dépassées, chiffre et limite."""
    out = []
    for i, c in enumerate(x for x in checks if not x.passed and x.actual is not None and x.limit is not None):
        kind = c.constraint.type.value if hasattr(c.constraint.type, "value") else str(c.constraint.type)
        unit = "nombre" if "positions" in kind or "factor" in kind else "pct"
        out.append(_item(f"limite_{i}", c.label, c.actual, unit, CHECKS, limit=("Ta limite", c.limit)))
    return out


def brief(e: dict) -> str:
    """Une preuve en une ligne, pour le prompt de l'agent Risque."""
    def fmt(v: float) -> str:
        return {"pct": f"{v:.1%}", "ans": f"{v:g} ans"}.get(e["unit"], f"{v:g}")
    text = f"{e['label']}: {fmt(e['value'])}"
    if "limit" in e:
        text += f" (repère: {e['limit']['label'].lower()} {fmt(e['limit']['value'])})"
    if "span" in e:
        text += f", du {e['span'][0]} au {e['span'][1]}"
    elif "period" in e and e["unit"] == "pct" and e["id"] in {m[0] for m in MACRO.values()}:
        text += f", au {e['period'][1]}"
    return text


def cite(ids: list[str], available: dict[str, dict], text: str) -> list[dict]:
    """Les preuves d'une mise en garde: celles que l'agent cite, sinon celles que ses mots désignent."""
    found = [available[i] for i in dict.fromkeys(ids) if i in available]
    if not found:
        low = text.lower()
        found = [available[i] for i in dict.fromkeys(i for word, i in KEYWORDS if word in low) if i in available]
    return found[:MAX_CITED]

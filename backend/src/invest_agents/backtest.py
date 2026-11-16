"""Backtest d'un portefeuille sur l'historique du dataset, avec rééquilibrage périodique. Code pur, sans LLM.

Principe: les poids de l'optimiseur sont appliqués au premier jour, puis dérivent avec les rendements quotidiens
(wᵢ ← wᵢ·(1 + rᵢ) / (1 + r_p)) jusqu'à la prochaine date de rééquilibrage, où l'on revient aux poids cibles.
Le rendement du portefeuille d'un jour est Σ wᵢ·rᵢ. `Market.returns` contient `total_return_cad` à la date t, soit
`total_return_cad_fwd_1d` à la date t − 1: c'est le même calcul que poids × rendement du lendemain.

Fenêtre: les `LOOKBACK_YEARS` dernières années. Un titre qui n'était pas encore coté (ex.: une scission récente) voit
son poids réparti sur les autres, au prorata, jusqu'à sa première cotation; on rééquilibre aussi ce jour-là. Un jour sans
cours pour un titre déjà coté (férié de son marché) compte comme un rendement nul.

Risque: la VaR et l'ES à 95 % (horizon d'un jour) et la distribution viennent des rendements QUOTIDIENS du portefeuille
(Σ poids × rendement de chaque titre), rangés par tranches de `DAILY_STEP` points de pourcentage entre ±`DAILY_LIMIT` %
(au-delà, dans les tranches des extrémités). La pire et la meilleure période de 12 mois restent des rendements glissants.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# Mêmes identifiants que ContributionFrequency (frontend/src/types.ts). « aucune » = acheter et conserver.
FREQUENCIES = ("deux-semaines", "mensuelle", "annuelle", "aucune")
LOOKBACK_YEARS = 6
YEAR = 252  # jours de bourse
BIWEEKLY = 10
SAMPLE_EVERY = 5  # un point par semaine pour le graphique
DAILY_STEP = 0.5  # largeur d'une tranche de la distribution, en points de pourcentage
DAILY_LIMIT = 5.0  # la distribution va de −5 % à +5 % par jour; les extrêmes vont dans les tranches des bouts


def rebalance_mask(index: pd.DatetimeIndex, frequency: str) -> np.ndarray:
    """Jours où l'on revient aux poids cibles (toujours le premier jour)."""
    mask = np.zeros(len(index), dtype=bool)
    if len(index):
        mask[0] = True
    if frequency == "deux-semaines":
        mask[::BIWEEKLY] = True
    elif frequency == "mensuelle":
        mask[1:] = index.month[1:] != index.month[:-1]
    elif frequency == "annuelle":
        mask[1:] = index.year[1:] != index.year[:-1]
    elif frequency != "aucune":
        raise ValueError(f"Fréquence de rééquilibrage inconnue: {frequency!r}")
    mask[0] = True
    return mask


def simulate(returns: pd.DataFrame, target: np.ndarray, frequency: str, listed: Optional[np.ndarray] = None) -> pd.Series:
    """Rendements quotidiens du portefeuille. `returns` (dates × titres) sans NaN; `listed` (même forme, booléen) dit
    si chaque titre était coté ce jour-là (tous par défaut)."""
    r = returns.to_numpy(dtype=float)
    live = np.ones_like(r, dtype=bool) if listed is None else listed
    mask = rebalance_mask(returns.index, frequency)
    mask[1:] |= (live[1:] != live[:-1]).any(axis=1)  # un titre fait son entrée: on rééquilibre
    w = target.astype(float).copy()
    out = np.empty(len(r))
    for t in range(len(r)):
        if mask[t]:
            w = np.where(live[t], target, 0.0).astype(float)
            w = w / w.sum() if w.sum() > 0 else w
        rp = float(w @ r[t])
        out[t] = rp
        w = w * (1.0 + r[t]) / (1.0 + rp)
    return pd.Series(out, index=returns.index)


def daily_distribution(daily: pd.Series, threshold: float) -> list[dict]:
    """Distribution des rendements quotidiens par tranches de `DAILY_STEP` points (de −DAILY_LIMIT à +DAILY_LIMIT).

    `bucket` est le centre de la tranche en points de pourcentage (−0,5 = autour de −0,5 %), `share` la part des jours
    (0 à 1) et `tail` vrai pour la tranche qui contient la VaR (`threshold`, un rendement négatif) et celles en dessous.
    """
    steps = int(round(DAILY_LIMIT / DAILY_STEP))
    clipped = np.clip(daily.to_numpy(dtype=float) * 100.0, -DAILY_LIMIT, DAILY_LIMIT)
    counts = np.bincount(np.round(clipped / DAILY_STEP).astype(int) + steps, minlength=2 * steps + 1)
    cut = int(round(np.clip(threshold * 100.0, -DAILY_LIMIT, DAILY_LIMIT) / DAILY_STEP))  # indice de la tranche de la VaR
    return [{"bucket": round((i - steps) * DAILY_STEP, 2), "share": round(float(c) / len(daily), 4), "tail": (i - steps) <= cut}
            for i, c in enumerate(counts)]


def summarize(daily: pd.Series, rf: float) -> dict:
    """Indicateurs, série (valeur base 100, rendement cumulé et recul, un point par semaine) et distribution quotidienne."""
    value = 100.0 * (1.0 + daily).cumprod()
    n = len(daily)
    years = n / YEAR
    annual = float((value.iloc[-1] / 100.0) ** (1.0 / years) - 1.0) if years > 0 else 0.0
    vol = float(daily.std() * np.sqrt(YEAR)) if n > 1 else 0.0
    underwater = value / value.cummax() - 1.0  # recul depuis le dernier sommet, jour par jour
    drawdown = float(underwater.min())
    rolling = (value / value.shift(YEAR) - 1.0).dropna()

    stats: dict = {
        "annualReturn": round(annual, 4),
        "cumulativeReturn": round(float(value.iloc[-1] / 100.0 - 1.0), 4),
        "volatility": round(vol, 4),
        "sharpe": round((annual - rf) / vol, 3) if vol > 0 else 0.0,
        "maxDrawdown": round(drawdown, 4),
        "finalValue": round(float(value.iloc[-1]), 2),
        "var95": None, "es95": None, "worst12m": None, "best12m": None,
    }
    distribution: list[dict] = []
    if n > 1:
        q = float(daily.quantile(0.05))  # le 5e centile des rendements quotidiens (négatif en général)
        stats.update(var95=round(-q, 4), es95=round(-float(daily[daily <= q].mean()), 4))
        distribution = daily_distribution(daily, q)
    if len(rolling):
        stats.update(worst12m=round(float(rolling.min()), 4), best12m=round(float(rolling.max()), 4))

    sampled = value.iloc[::SAMPLE_EVERY]
    if sampled.index[-1] != value.index[-1]:
        sampled = pd.concat([sampled, value.iloc[[-1]]])
    series = [{"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 2), "cumulative": round(float(v) / 100.0 - 1.0, 4),
               "drawdown": round(float(underwater.loc[d]), 4)}
              for d, v in sampled.items()]
    return {"stats": stats, "series": series, "distribution": distribution}


def backtest(returns: pd.DataFrame, weights: dict[str, float], rf: float) -> Optional[dict]:
    """Backtest pour chaque fréquence de rééquilibrage. None si l'historique commun fait moins d'un an."""
    symbols = [s for s, w in weights.items() if w > 0 and s in returns.columns]
    if not symbols:
        return None
    window = returns[symbols]
    window = window[window.index >= window.index.max() - pd.DateOffset(years=LOOKBACK_YEARS)]
    window = window.loc[window.notna().any(axis=1).idxmax():] if window.notna().any().any() else window.iloc[0:0]
    if len(window) < YEAR:
        return None
    first = window.apply(lambda s: s.first_valid_index())
    listed = np.column_stack([window.index >= first[s] for s in symbols])
    target = np.array([weights[s] for s in symbols], dtype=float)
    target = target / target.sum()
    data = window.fillna(0.0)
    runs = {f: summarize(simulate(data, target, f, listed), rf) for f in FREQUENCIES}
    return {"start": window.index[0].strftime("%Y-%m-%d"), "end": window.index[-1].strftime("%Y-%m-%d"),
            "bucketStep": DAILY_STEP, "runs": runs}


def risk_contribution(cov: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Part de chaque titre dans la variance du portefeuille (contribution d'Euler): wᵢ·(Σw)ᵢ / wᵀΣw. Somme = 1."""
    total = float(weights @ cov @ weights)
    if total <= 0:
        return np.zeros_like(weights)
    return weights * (cov @ weights) / total


__all__ = ["FREQUENCIES", "backtest", "daily_distribution", "rebalance_mask", "risk_contribution", "simulate", "summarize"]

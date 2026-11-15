"""Sélection déterministe de titres: repli des PM et test de faisabilité des contraintes."""

from __future__ import annotations

import pandas as pd

from .config import get_settings
from .constraints import SPECS, excluded_mask
from .data import Market
from .optimizer import Objective
from .schemas import Constraint, ConstraintType as T


def _rank(df: pd.DataFrame, objective: Objective) -> pd.DataFrame:
    if objective == "min_volatility":
        return df.sort_values("ann_vol")
    if objective == "max_return":
        return df.sort_values("ann_return", ascending=False)
    return df.sort_values("sharpe", ascending=False)


def default_selection(market: Market, constraints: list[Constraint], objective: Objective, size: int = 25) -> list[str]:
    """Sélection couvrant chaque groupe exigé (poids minimal) et chaque classe d'actifs, puis complétée par
    les meilleurs actifs selon l'objectif."""
    s = get_settings()
    hard = [c for c in constraints if c.hard]
    caps = [int(c.value) for c in hard if c.type is T.MAX_POSITIONS and c.value]
    size = min([size, s.max_assets_per_portfolio] + caps)
    eligible = market.assets[~excluded_mask(market, hard)]
    chosen: list[str] = []

    def take(df: pd.DataFrame, n: int) -> None:
        for sym in _rank(df, objective).index:
            if n <= 0 or len(chosen) >= size:
                return
            if sym not in chosen:
                chosen.append(sym)
                n -= 1

    for c in hard:
        spec = SPECS[c.type]
        if spec.direction == "min" and spec.dimension and spec.kind == "fraction" and (c.value or 0) > 0:
            members = market.members(spec.dimension, c.target or "")
            take(eligible[members.reindex(eligible.index).fillna(False)], 4 if (c.value or 0) >= 0.2 else 3)
    # Le reste: seulement des classes sans plafond très bas (chaque titre retenu pèse au moins 1 %).
    small_cap = {c.target for c in hard if c.type is T.MAX_ASSET_CLASS_WEIGHT and (c.value or 0) < 0.06}
    take(eligible[~eligible["asset_class"].isin(small_cap)], size)
    return chosen

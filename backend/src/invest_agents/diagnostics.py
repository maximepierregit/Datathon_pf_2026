"""Faits de risque calculés par le code sur un portefeuille. Les agents Risque les interprètent."""

from __future__ import annotations

from .schemas import InvestorProfile, Portfolio


def diagnostics(profile: InvestorProfile, portfolio: Portfolio) -> list[str]:
    """Faits calculés par le code. Le CRO les interprète."""
    m = portfolio.metrics
    if m is None:
        return []
    out = []
    loss = profile.form.max_acceptable_loss_pct
    if loss is not None and abs(m.max_drawdown) * 100 > loss:
        out.append(
            f"La perte maximale historique ({abs(m.max_drawdown):.1%}) dépasse la perte annuelle acceptée ({loss:.0f} %)."
        )
    if loss is not None and m.volatility * 2 * 100 > loss:
        out.append(f"Une baisse de deux écarts-types ({m.volatility * 2:.1%}) dépasse la perte acceptée ({loss:.0f} %).")
    if m.effective_n < 8:
        out.append(f"Diversification limitée: {m.effective_n:.1f} positions effectives sur {m.n_positions}.")
    top_sector, top_w = next(iter(m.sector_weights.items()), (None, 0.0))
    if top_sector and top_w > 0.35:
        out.append(f"Concentration sectorielle: {top_sector} pèse {top_w:.0%}.")
    top_country, top_c = next(iter(m.country_weights.items()), (None, 0.0))
    if top_country and top_c > 0.70:
        out.append(f"Concentration géographique: {top_country} pèse {top_c:.0%}.")
    crypto = sum(w for k, w in m.asset_class_weights.items() if "crypto" in k.lower())
    if crypto > 0.05:
        out.append(f"Exposition aux cryptomonnaies de {crypto:.0%}.")
    if profile.form.horizon_years < 3 and m.volatility > 0.15:
        out.append(f"Horizon de {profile.form.horizon_years} an(s) avec une volatilité de {m.volatility:.1%}.")
    return out

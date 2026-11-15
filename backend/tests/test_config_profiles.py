"""Tests des deux modes de config.py (à placer dans backend/src/tests/).

Lancer depuis backend :
    PYTHONPATH=src .venv/bin/python -m pytest -v src/tests/test_config_profiles.py
"""

import copy

import pytest

from invest_agents import config


def test_base_mode_ready():
    cfg = config.get_settings(mode="base")
    assert cfg["execution_mode"] == "base"
    assert cfg["risk_aversion"]["default"] == config.BASE_PROFILE["risk_aversion_A"]
    assert cfg["constraints"]["min_held_weight"] == 0.01


def test_base_alias_matches():
    assert config.get_base_settings() == config.get_settings(mode="base")


def test_agent_mode_input():
    cfg = config.get_settings(mode="agent", agent_request={
        "risk_aversion_A": 8.5,
        "min_cash_weight": 0.10,
        "excluded_symbols": ["nvda", " NVDA "],
        "excluded_themes": ["vice"],
        "preferences": {"theme": {"ia": {"mode": "exact", "weight": 0.20}}},
        "group_limits": {"asset_class": {"Equity": {"max": 0.65}}},
    })
    assert cfg["execution_mode"] == "agent"
    assert cfg["risk_aversion"]["default"] == 8.5
    assert cfg["constraints"]["min_cash_weight"] == 0.10
    assert cfg["constraints"]["excluded_symbols"] == ["NVDA"]
    assert cfg["constraints"]["excluded_themes"] == ["vice"]
    assert cfg["agent_preferences"]["theme"]["ia"] == {"mode": "exact", "weight": 0.20}
    assert cfg["constraints"]["group_limits"]["asset_class"]["Equity"]["max"] == 0.65


def test_agent_alias():
    assert config.get_agent_settings({"risk_aversion_A": 11}) == config.get_settings(
        mode="agent", agent_request={"risk_aversion_A": 11})


@pytest.mark.parametrize("payload", [None, {}, {"min_cash_weight": 0.1}])
def test_agent_requires_risk_A(payload):
    with pytest.raises(ValueError):
        config.get_settings(mode="agent", agent_request=payload)


def test_base_rejects_agent_payload():
    with pytest.raises(ValueError):
        config.get_settings(mode="base", agent_request={"risk_aversion_A": 8})


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        config.get_settings(mode="production")


def test_agent_settings_do_not_leak_to_other_runs():
    original = config.get_base_settings()
    agent_cfg = config.get_agent_settings({"risk_aversion_A": 20, "excluded_symbols": ["AAPL"]})
    agent_cfg["constraints"]["excluded_symbols"].append("MSFT")
    assert config.get_base_settings() == original
    assert config.get_agent_settings({"risk_aversion_A": 2})["constraints"]["excluded_symbols"] == []


def test_required_excluded_conflict():
    with pytest.raises(ValueError):
        config.get_agent_settings({"risk_aversion_A": 5,
                                   "required_symbols": ["AAPL"],
                                   "excluded_symbols": ["AAPL"]})


@pytest.mark.parametrize("bad_a", [-1, 0, 26, 100])
def test_invalid_A(bad_a):
    with pytest.raises(ValueError):
        config.get_agent_settings({"risk_aversion_A": bad_a})


def test_unexpected_financial_parameter_rejected():
    with pytest.raises(ValueError):
        config.get_agent_settings({"risk_aversion_A": 5, "rf_annual": 0.99})


def test_invalid_group_bounds_rejected():
    with pytest.raises(ValueError):
        config.get_agent_settings({
            "risk_aversion_A": 5,
            "group_limits": {"theme": {"ia": {"min": 0.9, "max": 0.1}}},
        })


def test_rf_is_35_for_both_capm_variants():
    cfg = config.get_base_settings()
    assert cfg["estimation"]["capm_shrinkage"]["rf_annual"] == 0.035
    assert cfg["estimation"]["capm_benchmark_shrinkage"]["rf_annual"] == 0.035


def test_cash_rate_is_separate_cad_assumption():
    cfg = config.get_base_settings()
    # Hypothèse de cash CAD de config.py (1 %), distincte du Rf CAPM de 3,5 %.
    assert cfg["cash"]["annual_expected_return"] == pytest.approx(0.01)
    assert cfg["cash"]["annual_expected_return"] != cfg["estimation"]["capm_shrinkage"]["rf_annual"]


def test_ewma_full_history_and_capm_window():
    """mu utilise l'historique individuel maximal de chaque titre: aucune fenêtre ne le tronque."""
    cfg = config.get_base_settings()
    assert cfg["estimation"]["ewma"]["lookback_observations"] is None
    assert cfg["estimation"]["capm_shrinkage"]["lookback_observations"] is None
    assert cfg["estimation"]["capm_shrinkage"]["historical_lookback_observations"] is None
    assert cfg["estimation"]["historical"]["lookback_observations"] is None


def test_capm_full_history_is_valid_option():
    cfg = config.get_base_settings()
    cfg["estimation"]["capm_shrinkage"]["lookback_observations"] = None
    cfg["estimation"]["capm_benchmark_shrinkage"]["lookback_observations"] = None
    config.validate_settings(cfg)


def test_invalid_ewma_lookback_rejected():
    cfg = config.get_base_settings()
    cfg["estimation"]["ewma"]["lookback_observations"] = 2
    with pytest.raises(ValueError):
        config.validate_settings(cfg)


def test_baseline_return_method():
    cfg = config.get_base_settings()
    assert config.get_return_method("Equity", "Stock", symbol="AAPL", settings=cfg) == "capm_shrinkage"
    assert config.get_return_method("Alternative", "Cryptocurrency", symbol="BTC-CAD", settings=cfg) == "ewma"


def test_configuration_not_mutated_by_bad_request():
    before = copy.deepcopy(config.get_base_settings())
    with pytest.raises(ValueError):
        config.apply_portfolio_request({"foo": "bar"}, settings=before)
    assert before == config.get_base_settings()


def test_max_cash_at_100_percent_is_fraction():
    cfg = config.get_base_settings()
    assert cfg["constraints"]["max_cash_weight"] == 1.0


def test_reject_max_cash_as_100_instead_of_1():
    cfg = config.get_base_settings()
    cfg["constraints"]["max_cash_weight"] = 100.0
    with pytest.raises(ValueError):
        config.validate_settings(cfg)


def test_v3_parquet_environment_override(monkeypatch):
    monkeypatch.setenv("MONPORT_UNIVERSE_PARQUET_URI", "s3://my-bucket/path/universe.parquet")
    assert config.get_parquet_source() == "s3://my-bucket/path/universe.parquet"
    assert config.get_base_settings()["data"]["parquet_source"] == "s3://my-bucket/path/universe.parquet"


def test_no_bond_forecast_configuration():
    """No unsupported yield/duration/convexity forecast is configured."""
    cfg = config.get_base_settings()
    assert "bond_forecasts" not in cfg
    assert not hasattr(config, "BOND_FORECASTS")


def test_fixed_income_etfs_use_historical_mean():
    """Bond ETFs are estimated with the ordinary historical method."""
    cfg = config.get_base_settings()
    assert config.get_return_method("Fixed Income", "ETF", symbol="BND", settings=cfg) == "historical"
    assert config.get_return_method("Fixed Income", "ETF", symbol="AGG", settings=cfg) == "historical"

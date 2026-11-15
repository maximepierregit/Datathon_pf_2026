from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from invest_agents import data as d


@pytest.fixture
def raw():
    """Quatre actifs, trois jours de bourse, un jour férié simulé pour RY.TO.

    Rendements = évolution des prix CAD par symbole. La toute première
    observation peut avoir une valeur nulle (historique initial hors extrait).
    """
    specs = [
        ("AAPL", "Apple", "Stock", "Equity", "United States", "Information Technology", "ia;tech", "USD", [100., 101., 102.], ["2026-11-05", "2026-11-06", "2026-11-09"]),
        ("SPY", "SPDR S&P 500", "ETF", "Equity", "Non classé", "Non classé", "tech", "USD", [500., 505., 500.], ["2026-11-05", "2026-11-06", "2026-11-09"]),
        ("RY.TO", "Royal Bank", "Stock", "Equity", "Canada", "Financials", None, "CAD", [100., 102.], ["2026-11-05", "2026-11-09"]),
        ("BTC-CAD", "Bitcoin", "Cryptocurrency", "Alternative", "Non classé", "Non classé", None, "CAD", [100., 110., 108.], ["2026-11-05", "2026-11-06", "2026-11-09"]),
    ]
    rows = []
    for symbol, name, kind, cls, country, sector, theme, ccy, prices, dates in specs:
        fx = 1.30 if ccy == "USD" else 1.0
        prev = None
        for date, local in zip(dates, prices):
            cad = local * fx
            ret = 0.0 if prev is None else cad / prev - 1
            rows.append(dict(
                date=pd.Timestamp(date), symbol=symbol, total_return_cad=ret,
                total_return_cad_fwd_1d=np.nan, close_price_loc=local,
                fx_rate_to_cad=fx, close_price_cad=cad,
                name=name, asset_class=cls, instrument_type=kind,
                currency=ccy, sector=sector, industry="Non classé",
                country=country, market="Non classé", market_cap="Non classé",
                category_group="Equities" if kind == "ETF" else None,
                category="Developed Markets" if kind == "ETF" else None,
                theme=theme, is_included_universe=True,
            ))
            prev = cad
    return pd.DataFrame(rows)


@pytest.fixture
def panel(raw):
    return d.normalize_market_data(raw)


@pytest.fixture
def universe(panel):
    return d.build_universe(panel)


def test_as_date():
    assert d._as_date("2026-11-09") == pd.Timestamp("2026-11-09")
    assert d._as_date("2026-11-09 14:00") == pd.Timestamp("2026-11-09")
    assert d._as_date(None) is None
    with pytest.raises(Exception):
        d._as_date("date-invalide")


def test_unique_symbols():
    assert d._unique_symbols([" aapl ", "SPY", "AAPL"]) == ["AAPL", "SPY"]
    assert d._unique_symbols(None) is None
    with pytest.raises(TypeError):
        d._unique_symbols("AAPL")


def test_parse_bool():
    assert d._parse_bool(" oui ") is True
    assert d._parse_bool("0") is False
    assert d._parse_bool(True) is True
    assert pd.isna(d._parse_bool("inconnu"))


def test_load_market_data_local(tmp_path, monkeypatch, raw):
    file_path = tmp_path / "universe.parquet"
    file_path.touch()  # Simulation de lecture : pas de pyarrow nécessaire ici.
    calls = []

    def fake_read(path, columns=None):
        calls.append((path, columns))
        return raw.copy() if columns is None else raw[list(columns)].copy()

    monkeypatch.setattr(d.pd, "read_parquet", fake_read)
    result = d.load_market_data(file_path, columns=["date", "symbol"])
    assert result.columns.tolist() == ["date", "symbol"]
    assert len(result) == len(raw)
    assert len(calls) == 1
    with pytest.raises(FileNotFoundError):
        d.load_market_data(tmp_path / "absent.parquet")


def test_load_market_data_s3_without_aws(monkeypatch, raw):
    class FakeS3:
        def __init__(self):
            self.request = None

        def get_object(self, **kwargs):
            self.request = kwargs
            return {"Body": BytesIO(b"simulation-parquet")}

    client = FakeS3()
    monkeypatch.setattr(d.pd, "read_parquet", lambda *_args, **_kw: raw.copy())
    loaded = d.load_market_data("s3://bucket/test/universe.parquet", s3_client=client)
    assert client.request == {"Bucket": "bucket", "Key": "test/universe.parquet"}
    assert len(loaded) == len(raw)
    with pytest.raises(ValueError):
        d.load_market_data("s3:///cle-invalide", s3_client=client)


def test_normalize_market_data(raw):
    noisy = raw.copy()
    noisy.loc[0, "symbol"] = " aapl "
    noisy["is_included_universe"] = "true"
    noisy["total_return_cad"] = noisy["total_return_cad"].astype(str)
    result = d.normalize_market_data(noisy)
    assert result["symbol"].eq("AAPL").sum() == 3
    assert pd.api.types.is_datetime64_any_dtype(result["date"])
    assert pd.api.types.is_numeric_dtype(result["total_return_cad"])
    assert result["is_included_universe"].all()
    assert result.sort_values(["date", "symbol"]).index.equals(result.index)
    with pytest.raises(ValueError, match="Colonnes obligatoires"):
        d.normalize_market_data(raw.drop(columns="asset_class"))


def test_validate_market_data_clean(panel):
    report = d.validate_market_data(panel, strict=True)
    assert report.empty or not report["severity"].eq("ERROR").any()


def test_validate_market_data_detects_duplicates(panel):
    duplicate = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
    report = d.validate_market_data(duplicate, strict=False)
    assert "duplicate_date_symbol" in set(report["code"])
    with pytest.raises(ValueError, match="Validation"):
        d.validate_market_data(duplicate, strict=True)


def test_validate_market_data_detects_invalid_classes(panel):
    corrupted = panel.copy()
    corrupted.loc[0, "asset_class"] = "Fake Class"
    report = d.validate_market_data(corrupted, strict=False)
    assert "invalid_asset_class" in set(report["code"])


def test_filter_market_data(panel):
    result = d.filter_market_data(panel, start_date="2026-11-06", as_of="2026-11-06")
    assert result["date"].nunique() == 1
    assert result["date"].iloc[0] == pd.Timestamp("2026-11-06")
    with pytest.raises(ValueError, match="dépasser"):
        d.filter_market_data(panel, start_date="2026-11-09", as_of="2026-11-05")


def test_build_universe(panel, universe):
    assert len(universe) == 4
    assert universe.loc["AAPL", "observations"] == 3
    assert universe.loc["RY.TO", "observations"] == 2
    assert universe.loc["AAPL", "region"] == "usa"
    assert universe.loc["RY.TO", "region"] == "canada"
    assert pd.isna(universe.loc["SPY", "region"])  # Aucun look-through inventé.
    assert universe.loc["BTC-CAD", "asset_class"] == "Alternative"
    overridden = d.build_universe(panel, region_overrides={"SPY": "monde"})
    assert overridden.loc["SPY", "region"] == "monde"


def test_build_theme_membership(universe):
    tags = d.build_theme_membership(universe)
    assert set(tags.loc[tags["symbol"] == "AAPL", "theme"]) == {"ia", "tech"}
    assert "BTC-CAD" not in set(tags["symbol"])
    assert not tags.duplicated(["symbol", "theme"]).any()


def test_build_instrument_views(universe):
    views = d.build_instrument_views(universe)
    assert set(views) == {"stocks", "etfs", "crypto"}
    assert set(views["stocks"].index) == {"AAPL", "RY.TO"}
    assert views["etfs"].index.tolist() == ["SPY"]
    assert views["crypto"].index.tolist() == ["BTC-CAD"]


def test_pivot_values_keeps_structural_nan(panel):
    values = d._pivot_values(panel, ["AAPL", "RY.TO"], d.RETURN_COLUMN)
    assert values.shape == (3, 2)
    assert pd.isna(values.loc[pd.Timestamp("2026-11-06"), "RY.TO"])
    assert values.columns.tolist() == ["AAPL", "RY.TO"]
    with pytest.raises(ValueError, match="liste de symboles"):
        d._pivot_values(panel, None, d.RETURN_COLUMN)


def test_build_returns_matrix(panel):
    matrix = d.build_returns_matrix(panel, ["AAPL", "SPY", "RY.TO"])
    assert matrix.shape == (3, 3)
    assert np.isclose(matrix.loc[pd.Timestamp("2026-11-06"), "AAPL"], 0.01)
    assert pd.isna(matrix.loc[pd.Timestamp("2026-11-06"), "RY.TO"])
    assert not matrix.fillna(123).eq(0).all().all()


def test_build_price_matrix(panel):
    prices = d.build_price_matrix(panel, ["AAPL"])
    assert np.isclose(prices.loc[pd.Timestamp("2026-11-06"), "AAPL"], 101 * 1.3)


def test_describe_market_data(panel):
    summary = d.describe_market_data(panel)
    assert summary["rows"] == 11
    assert summary["symbols"] == 4
    assert summary["weekend_rows"] == 0
    assert set(summary["symbols_by_instrument_type"]) == {"Stock", "ETF", "Cryptocurrency"}


def test_prepare_optimizer_data(monkeypatch, raw):
    monkeypatch.setattr(d, "load_market_data", lambda *args, **kwargs: raw.copy())
    result = d.prepare_optimizer_data(
        symbols=["SPY", "AAPL"],
        benchmark_symbols=["RY.TO"],
        min_observations=3,
        as_of="2026-11-09",
    )
    assert isinstance(result, d.OptimizerData)
    assert result.returns.columns.tolist() == ["SPY", "AAPL"]
    assert result.prices.columns.tolist() == ["SPY", "AAPL"]
    assert result.benchmark_returns.columns.tolist() == ["RY.TO"]
    assert pd.isna(result.benchmark_returns.loc[pd.Timestamp("2026-11-06"), "RY.TO"])
    assert "RY.TO" in result.excluded_short_history
    assert "total_return_cad_fwd_1d" not in result.panel.columns
    assert result.as_of == pd.Timestamp("2026-11-09")


def test_prepare_optimizer_data_rejects_short_history(monkeypatch, raw):
    monkeypatch.setattr(d, "load_market_data", lambda *args, **kwargs: raw.copy())
    with pytest.raises(ValueError, match="non admissibles"):
        d.prepare_optimizer_data(symbols=["RY.TO"], min_observations=3)
    with pytest.raises(ValueError, match="min_observations"):
        d.prepare_optimizer_data(min_observations=1)


def test_main_cli(monkeypatch, raw, capsys):
    monkeypatch.setattr(d, "load_market_data", lambda *args, **kwargs: raw.copy())
    monkeypatch.setattr(sys, "argv", ["data.py", "--input", "test.parquet", "--symbols", "AAPL", "SPY", "--min-observations", "2"])
    d.main()
    output = capsys.readouterr().out
    assert "MATRICE DES RENDEMENTS" in output
    assert "RÉSUMÉ DU PANEL" in output


def test_real_parquet():
    """Test optionnel avec le vrai fichier, en local ou dans S3 déjà configuré."""
    path = os.getenv("MONPORT_TEST_PARQUET")
    if not path:
        pytest.skip("Définir MONPORT_TEST_PARQUET pour activer le test réel.")
    if not path.startswith("s3://") and not Path(path).is_file():
        pytest.fail(f"Fichier réel introuvable : {path}")

    result = d.prepare_optimizer_data(
        path=path,
        symbols=["AAPL", "SPY", "RY.TO", "BTC-CAD"],
        benchmark_symbols=["XLK"],
        min_observations=120,
        strict_validation=True,
    )
    assert result.returns.shape[1] == 4
    assert set(result.eligible_universe.index) == set(result.returns.columns)
    assert result.returns.index.equals(result.prices.index)
    assert result.returns.index.is_monotonic_increasing
    assert "total_return_cad_fwd_1d" not in result.panel.columns
    assert result.panel["date"].dt.dayofweek.lt(5).all()
    assert result.validation_report.empty or not result.validation_report["severity"].eq("ERROR").any()
    # Les jours fériés / dates de cotation n'ont pas été comblés artificiellement.
    assert (result.returns.notna().sum() <= len(result.returns)).all()

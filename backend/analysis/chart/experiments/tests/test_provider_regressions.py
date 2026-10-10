"""Captured provider failures, cache preservation, and incomplete flow windows."""

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from experiments.dataset.pipeline import flow_coverage, supplement_raw_ohlc, validate_prices
from experiments.features.flow import build_flow_features
from shared.data import providers as source
from shared.features.builder import normalize_trading_halts

CAPTURE = json.loads((Path(__file__).parent / "fixtures/provider_failures.json").read_text())


@pytest.mark.parametrize("case", CAPTURE["unavailable_regular_session_rows"], ids=lambda case: case["code"])
def test_actual_turnover_without_regular_session_bar_is_preserved_and_excluded(case):
    days = pd.DatetimeIndex([case["date"]])
    raw = pd.DataFrame([case["raw"]], index=days)
    adjusted = pd.DataFrame({"Close": raw["종가"] / 2, "Volume": raw["거래량"]})
    attached = source._attach_actual_vwap(adjusted, raw).rename_axis("Date").reset_index()
    verified = validate_prices(attached, days)
    assert source._has_complete_actual_vwap(verified)
    assert verified.RegularSessionUnavailable.all()
    assert not verified.Trading_Halt.any()  # No inference of an official suspension.
    assert verified.RawVolume.iloc[0] == case["raw"]["거래량"]
    assert verified.Amount.iloc[0] == case["raw"]["거래대금"]
    assert verified[["Open", "High", "Low", "RawOpen", "RawHigh", "RawLow"]].eq(0).all().all()
    expected_vwap = case["raw"]["거래대금"] / case["raw"]["거래량"] / 2
    assert verified.VWAP.iloc[0] == pytest.approx(expected_vwap)
    assert not verified.VWAPOutsideDailyRange.any()
    normalized = normalize_trading_halts(verified, days)
    assert normalized.Trading_Halt.eq(1).all()  # Downstream cannot enter/exit here.
    assert normalized.Volume.eq(0).all()
    assert normalized.RawVolume.iloc[0] == case["raw"]["거래량"]
    assert normalized.Amount.iloc[0] == case["raw"]["거래대금"]
    assert verified.VWAP.iloc[0] == pytest.approx(expected_vwap)


@pytest.mark.parametrize("bad_value", [0, -1, np.nan, np.inf])
def test_partial_missing_regular_ohlc_still_rejected(bad_value):
    _, adjusted, raw = captured_prices()
    raw.iloc[0, raw.columns.get_loc("시가")] = bad_value
    with pytest.raises(ValueError, match="OHLC relationship"):
        source._attach_actual_vwap(adjusted, raw)


def test_unavailable_bar_cannot_bypass_turnover_or_uniform_factor_validation():
    case = CAPTURE["unavailable_regular_session_rows"][0]
    days = pd.DatetimeIndex([case["date"]])
    raw = pd.DataFrame([case["raw"]], index=days)
    adjusted = pd.DataFrame({"Close": raw["종가"], "Volume": raw["거래량"]})
    frame = source._attach_actual_vwap(adjusted, raw).rename_axis("Date").reset_index()
    frame.loc[0, "Open"] = frame.Close.iloc[0]
    with pytest.raises(ValueError, match="uniform adjustment"):
        validate_prices(frame, days)
    frame.loc[0, "Open"] = 0
    frame.loc[0, "Amount"] = 0
    with pytest.raises(ValueError, match="Non-positive"):
        validate_prices(frame, days)


def captured_prices():
    days = pd.to_datetime([row["date"] for row in CAPTURE["price_rows"]])
    adjusted = pd.DataFrame([row["adjusted"] for row in CAPTURE["price_rows"]], index=days)
    raw = pd.DataFrame([row["raw"] for row in CAPTURE["price_rows"]], index=days)
    return days, adjusted, raw


def test_actual_yuhan_rounding_uses_one_factor_for_all_ohlc():
    days, adjusted, raw = captured_prices()
    assert adjusted.iloc[0].High == 41309 and adjusted.iloc[0].Close == 41310
    result = source._attach_actual_vwap(adjusted, raw)
    validated = validate_prices(result.rename_axis("Date").reset_index(), days)
    for column in ("Open", "High", "Low", "Close"):
        np.testing.assert_allclose(result[column], raw[{"Open": "시가", "High": "고가", "Low": "저가", "Close": "종가"}[column]] * result.AdjustmentFactor)
    np.testing.assert_allclose(validated.Close, adjusted.Close)
    assert validated.Volume.tolist() == raw["거래량"].tolist()


def test_vwap_range_departure_reported_but_formula_corruption_rejected():
    days, adjusted, raw = captured_prices()
    raw["거래대금"] *= 2
    result = source._attach_actual_vwap(adjusted, raw).rename_axis("Date").reset_index()
    verified = validate_prices(result, days)
    assert verified.VWAPOutsideDailyRange.all()
    assert verified.VWAPScope.eq("KRX_amount_volume_scope_unverified").all()
    result.loc[0, "VWAP"] += 100
    with pytest.raises(ValueError, match="VWAP adjustment"):
        validate_prices(result, days)
    result.loc[0, "VWAP"] -= 100
    result.loc[0, "RawHigh"] += 1
    with pytest.raises(ValueError, match="uniform adjustment"):
        validate_prices(result, days)


def test_ohlc_supplement_keeps_existing_fields_and_resumes(tmp_path):
    days, _, raw = captured_prices()
    preserved = raw.rename(columns={"종가": "RawClose", "거래량": "RawVolume", "거래대금": "Amount"})[["RawClose", "RawVolume", "Amount"]]
    before = preserved.copy()
    calls = []
    provider = SimpleNamespace(_krx_request_timeout=nullcontext,
        krx=SimpleNamespace(get_market_ohlcv_by_date=lambda *args, **kwargs: (calls.append(args) or raw)))
    result = supplement_raw_ohlc(tmp_path, "000100", days, preserved, provider)
    pd.testing.assert_frame_equal(result[before.columns], before)
    assert len(calls) == 1
    repeated = supplement_raw_ohlc(tmp_path, "000100", days, preserved, provider)
    pd.testing.assert_frame_equal(result, repeated)
    assert len(calls) == 1
    corrupted = preserved.copy()
    corrupted.iloc[0, 0] += 1
    with pytest.raises(ValueError, match="disagrees"):
        supplement_raw_ohlc(tmp_path, "000100", days, corrupted, provider)


def test_full_history_is_one_request_and_old_chunks_are_reused(tmp_path):
    from shared.io import atomic_json, atomic_parquet, sha256

    days = pd.bdate_range("2016-01-04", "2026-10-06")
    fields = ["RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount"]
    raw = pd.DataFrame([[100, 110, 90, 105, 10, 1050]] * len(days), index=days, columns=fields)
    calls = []
    provider = SimpleNamespace(_krx_request_timeout=nullcontext,
        krx=SimpleNamespace(get_market_ohlcv_by_date=lambda *args, **kwargs: (calls.append(args) or raw)))
    result = supplement_raw_ohlc(tmp_path, "000100", days, None, provider)
    pd.testing.assert_frame_equal(result, raw)
    assert calls == [("20160104", "20261006", "000100")]
    # Previously downloaded two-year windows require no new request.
    legacy = tmp_path / "legacy"
    current = days[0]
    while current <= days[-1]:
        end = min(current + pd.DateOffset(years=2) - pd.Timedelta(days=1), days[-1])
        path = legacy / "raw_ohlc_cache" / f"000100_{current:%Y%m%d}_{end:%Y%m%d}.parquet"
        atomic_parquet(path, raw.loc[current:end].rename_axis("Date").reset_index())
        atomic_json(path.with_suffix(".json"), {"sha256": sha256(path)})
        current = end + pd.Timedelta(days=1)
    pd.testing.assert_frame_equal(supplement_raw_ohlc(legacy, "000100", days, None, provider), raw)
    assert len(calls) == 1
    # A truncated provider response must not become a usable full cache.
    provider.krx.get_market_ohlcv_by_date = lambda *args, **kwargs: raw.iloc[1:]
    with pytest.raises(ValueError, match="Incomplete"):
        supplement_raw_ohlc(tmp_path / "incomplete", "000100", days, None, provider)
    assert not list((tmp_path / "incomplete").glob("raw_ohlc_cache/*.parquet"))


def test_missing_ranking_investor_is_retained_and_windows_excluded(tmp_path):
    case = CAPTURE["flow_case"]
    assert not case["present_in_ranking"] and case["detail_buy_volume"] == 0
    days = pd.bdate_range(case["date"], periods=25)
    raw = pd.DataFrame({"Date": days, "Code": case["code"], "RawVolume": 100, "Amount": 1000})
    for column in source._FLOW_COLUMNS:
        raw[column] = 0.0
    raw.loc[0, [col for col in source._FLOW_COLUMNS if col.startswith("Institution_")]] = np.nan
    (tmp_path / "raw").mkdir()
    raw.to_parquet(tmp_path / "raw/101930.parquet", index=False)
    flow = build_flow_features(raw, days)
    for window in (1, 5, 20):
        assert flow[f"flow_institution_{window}"].iloc[:window].isna().all()
        assert flow[f"flow_institution_{window}"].iloc[window] == 0
    report = flow_coverage(tmp_path, source._INVESTORS, source._FLOW_COLUMNS, days)
    institution = next(row for row in report if row["investor"] == "Institution")
    assert institution["not_returned_rows"] == institution["missing_traded_rows"] == 1
    assert institution["amount_window_coverage"]["20"]["excluded_rows"] == 20


def test_actual_ranking_omission_survives_collector_join(monkeypatch):
    case = CAPTURE["flow_case"]
    samples = case["response_samples"]
    investors = {name: prefix for prefix, name in source._INVESTORS.items()}

    def fetch(*args, investor, **kwargs):
        return pd.DataFrame(samples[investors[investor]]).set_index("Code")

    monkeypatch.setattr(source, "krx", SimpleNamespace(get_market_net_purchases_of_equities_by_ticker=fetch))
    monkeypatch.setattr(source, "_krx_request_timeout", nullcontext)
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    result = source._fetch_investor_day(pd.Timestamp(case["date"]))
    row = result.loc[result.Code.eq(case["code"])].iloc[0]
    fields = [column for column in source._FLOW_COLUMNS if column.startswith("Institution_")]
    assert row[fields].isna().all()
    assert row.Individual_BuyVolume == 9583
    assert row.Foreign_BuyVolume == 91

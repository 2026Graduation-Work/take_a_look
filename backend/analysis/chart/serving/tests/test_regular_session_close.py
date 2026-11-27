"""Since 2026-09-14 (KRX after-market) Naver's close drifts from the KRX regular-session close.

Fixtures are real KRX raw rows and Naver closes from chart_prices.
"""
import time
from contextlib import nullcontext

import pandas as pd
import pytest
from serving.internal import calendar
from serving.internal import prices as serving_prices
from serving.internal.prices import fetch_prices
from shared.data import prices as shared_prices
from shared.data import providers


def _raw(dates, ohlc, volume, amount):
    open_, high, low, close = zip(*ohlc)
    return pd.DataFrame({"RawOpen": open_, "RawHigh": high, "RawLow": low, "RawClose": close,
                         "RawVolume": volume, "Amount": amount}, index=pd.to_datetime(dates), dtype=float)


def _adapter(closes, calls, name):
    def fetch(code, start, end, *, raw_df):
        calls.append(name)
        if closes is None:
            raise ValueError("KRX unavailable")
        adjusted = pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes,
                                 "Volume": raw_df.RawVolume, "Change": 0.0}, index=raw_df.index, dtype=float)
        return providers._attach_actual_vwap(adjusted, raw_df.rename(columns={
            "RawOpen": "시가", "RawHigh": "고가", "RawLow": "저가", "RawClose": "종가",
            "RawVolume": "거래량", "Amount": "거래대금"}))
    return fetch


@pytest.fixture
def fetch(tmp_path, monkeypatch):
    monkeypatch.setenv("CHART_SERVING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(providers, "_krx_request_timeout", nullcontext)
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    def run(raw, naver, krx_adjusted):
        calls = []
        monkeypatch.setattr(calendar, "get_krx_trading_days", lambda *_: set(raw.index.date))
        monkeypatch.setattr(shared_prices, "supplement_raw_ohlc", lambda *_: raw)
        monkeypatch.setattr(serving_prices, "_fetch_krx_adjusted", _adapter(krx_adjusted, calls, "krx"))
        monkeypatch.setattr(providers, "_fetch_ohlcv_fdr", _adapter(naver, calls, "fdr"))
        monkeypatch.setattr(providers, "_fetch_ohlcv_pykrx", _adapter(krx_adjusted, calls, "pykrx"))
        result = fetch_prices("005930", str(raw.index[0].date()), str(raw.index[-1].date()))
        return result, calls
    return run


SAMSUNG_DAYS = ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20",
                "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"]
SAMSUNG = _raw(SAMSUNG_DAYS,
               [(233500, 241500, 230000, 232000), (216500, 221500, 204500, 210000), (215000, 222500, 210500, 215500),
                (207000, 219500, 206500, 218000), (219500, 219500, 208750, 211500), (217000, 228000, 217000, 223500),
                (221500, 226000, 212000, 214500), (206000, 215500, 203500, 215500), (213500, 216000, 211500, 213000),
                (222000, 225500, 220000, 222000)],
               [19009052, 34330565, 18908560, 17617415, 16561224, 17268762, 11469322, 16145972, 11376006, 14196879],
               [4471869613456, 7248593534110, 4084933131254, 3792914575250, 3515884197247, 3842731209918,
                2492992495192, 3396837242750, 2430729239364, 3162205846250])
SAMSUNG_NAVER = [234500, 207500, 217000, 223500, 209000, 223500, 214500, 213500, 213500, 225000]


def test_serving_uses_krx_regular_close(fetch):
    prices, calls = fetch(SAMSUNG, SAMSUNG_NAVER, SAMSUNG.RawClose.tolist())
    assert calls == ["krx"] and set(prices.PriceProvider) == {"pykrx"}
    close = prices.set_index("Date").Close
    # Naver showed 213,500 -> 213,500 ('전일 대비 0원'); the KRX close moved -2,500 won.
    assert close["2026-10-26"] - close["2026-10-23"] == -2500
    assert (close["2026-10-26"] / close["2026-10-23"] - 1) * 100 == pytest.approx(-1.16, abs=0.005)
    assert prices.AdjustmentFactor.eq(1).all()


@pytest.mark.parametrize("krx", [None, SAMSUNG_NAVER])
def test_drifting_close_is_never_published(fetch, krx):
    # pykrx's stock API serves adjusted=True from Naver as well, so the KRX path is checked too.
    with pytest.raises(ValueError, match="^Price providers exhausted: .*Adjustment factor moved"):
        fetch(SAMSUNG, SAMSUNG_NAVER, krx)


def test_stock_without_after_market_can_fall_back_to_fdr(fetch):
    raw = _raw(SAMSUNG_DAYS,  # 000040: Naver close equaled the KRX close every day after 9/14
               [(1000, 1000, 963, 979), (955, 975, 930, 952), (956, 990, 950, 972), (940, 997, 940, 992),
                (1100, 1289, 1025, 1289), (1402, 1485, 1192, 1248), (1283, 1350, 1141, 1172),
                (1202, 1243, 1095, 1165), (1165, 1165, 1060, 1117), (1154, 1154, 1051, 1132)],
               [25607, 12863, 15214, 45849, 995289, 1237030, 208575, 55265, 47288, 46878],
               [24932254, 12138048, 14717770, 45098401, 1248221713, 1606436032, 254490546, 64059420, 52536733, 52250002])
    prices, calls = fetch(raw, raw.RawClose.tolist(), None)
    assert calls[-1] == "fdr" and set(prices.PriceProvider) == {"fdr"}
    assert prices.Close.tolist() == raw.RawClose.tolist()


def test_real_corporate_action_step_is_kept(fetch):
    # 006490: halted 9/3~9/9, then a real adjustment (factor 1.577 -> 1) from 9/10.
    raw = _raw(["2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09",
                "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16"],
               [(0, 0, 0, 898)] * 5 + [(1416, 1840, 1416, 1840), (2390, 2390, 2250, 2390), (2715, 3025, 2250, 2590),
                                       (2400, 2745, 2250, 2250), (2270, 2440, 2030, 2030)],
               [0] * 5 + [122620, 164384, 2016401, 405646, 146025],
               [0] * 5 + [222000961, 392156975, 5499412217, 984032110, 322757366])
    adjusted = [1416] * 5 + [1840, 2390, 2590, 2250, 2030]
    for krx, naver in ((adjusted, None), (None, adjusted)):
        prices, _ = fetch(raw, naver, krx)
        factor = prices.set_index("Date").AdjustmentFactor
        assert factor[:"2026-09-09"].round(3).eq(1.577).all() and factor["2026-09-10":].eq(1).all()


def test_several_real_steps_in_a_window_are_allowed(fetch):
    steps = [0.5] * 3 + [0.8] * 3 + [1.0] * 4  # two corporate actions inside ten sessions
    prices, _ = fetch(SAMSUNG, (SAMSUNG.RawClose * steps).tolist(), None)
    assert set(prices.PriceProvider) == {"fdr"} and prices.AdjustmentFactor.round(6).tolist() == steps

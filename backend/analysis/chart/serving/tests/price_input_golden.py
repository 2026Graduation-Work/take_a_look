"""Offline check of the KRX-first path from pykrx responses to serving price inputs."""
import json
import sys
import tempfile
from contextlib import nullcontext
from itertools import zip_longest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import requests

CHART_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "fixtures/price-input-golden.json"
SAMSUNG_FIXTURE = CHART_ROOT / "shared/tests/fixtures/005930_2018.csv"
STOCK_CODE = "005930"
RAW_COLUMNS = ["시가", "고가", "저가", "종가", "거래량", "거래대금", "등락률"]
TOLERANCE = {"rtol": 1e-10, "atol": 0.0}


def _adjusted_response(raw, close):
    """Build a synthetic adjusted response with the supplied close."""
    ratio = close / raw["종가"]
    adjusted = pd.DataFrame({column: (raw[column] * ratio).round() for column in ("시가", "고가", "저가")})
    adjusted = adjusted.where(raw[["시가", "고가", "저가"]].gt(0), close, axis=0)
    adjusted["종가"] = close
    adjusted["거래량"] = raw["거래량"]
    adjusted["거래대금"] = raw["거래대금"]
    adjusted["등락률"] = (close.pct_change(fill_method=None) * 100).round(2).fillna(0.0)
    return adjusted


def split_with_halt():
    """Real KRX raw bars around Samsung's 2018-05-04 50:1 split (halted 4/30, 5/2, 5/3)."""
    frame = pd.read_csv(SAMSUNG_FIXTURE, comment="#", parse_dates=["Date"]).set_index("Date")
    frame = frame.loc["2018-04-02":"2018-05-31"]
    raw = frame.rename(columns={"RawOpen": "시가", "RawHigh": "고가", "RawLow": "저가", "RawClose": "종가",
                                "RawVolume": "거래량", "Amount": "거래대금", "RawChange": "등락률"})[RAW_COLUMNS]
    raw["등락률"] = (raw["등락률"] / (raw["종가"] - raw["등락률"]) * 100).round(2)
    # The CSV records Naver adjusted closes. The rest of the adjusted response is synthetic.
    return {"name": "split_with_halt", "kind": "factor_change", "raw": raw,
            "adjusted": _adjusted_response(raw, frame.NaverClose.astype(float))}


def regular_session_unavailable():
    """Synthetic bars: one day with turnover but no regular-session OHLC, one VWAP outside the range."""
    dates = pd.bdate_range("2024-03-04", periods=8, name="Date")
    raw = pd.DataFrame({
        "시가": [1000, 1012, 1018, 0, 1030, 1025, 1040, 1046],
        "고가": [1015, 1020, 1030, 0, 1041, 1036, 1052, 1060],
        "저가": [995, 1005, 1010, 0, 1022, 1015, 1033, 1038],
        "종가": [1010, 1016, 1025, 1025, 1035, 1028, 1048, 1050],
        "거래량": [1000, 1200, 900, 300, 1500, 1100, 1300, 1000],
        # 2024-03-06 turnover gives VWAP 1040 above the 1030 high: kept and flagged, not rejected.
        "거래대금": [1006000, 1215600, 936000, 307200, 1549500, 1129700, 1355900, 1049000],
    }, index=dates, dtype=float)
    raw["등락률"] = (raw["종가"].pct_change() * 100).round(2).fillna(0.0)
    adjusted = _adjusted_response(raw, raw["종가"])
    # Different supplier values make choosing the wrong response fail on a regular-session row.
    adjusted.loc[dates[0], ["시가", "고가", "저가", "거래량", "거래대금"]] = [1005, 1020, 1000, 1100, 1106600]
    return {"name": "regular_session_unavailable", "kind": "regular_session_unavailable", "raw": raw,
            "adjusted": adjusted}


def build_cases():
    return [split_with_halt(), regular_session_unavailable()]


def _frame(records):
    frame = pd.DataFrame(records)
    frame.index = pd.to_datetime(frame.pop("날짜")).rename("날짜")
    return frame.astype(float)


def _records(frame):
    return [{"날짜": day.date().isoformat(), **row} for day, row in zip(frame.index, frame.to_dict("records"))]


def run(case, data_dir):
    """Run the serving price fetch with the case's KRX responses at the pykrx boundary."""
    from serving.internal import calendar
    from serving.internal.prices import fetch_prices
    from shared.data import krx, prices, providers

    name, raw = case["name"], case["raw"]
    days = set(raw.index.date)
    calls = []
    candidate = None
    validate_prices = prices.validate_prices

    def response(frame, *, expect_adjusted):
        def get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
            if ticker != STOCK_CODE or adjusted is not expect_adjusted:
                raise AssertionError(
                    f"{name}: expected KRX ticker {STOCK_CODE} with adjusted={expect_adjusted}, "
                    f"got {ticker} with adjusted={adjusted}"
                )
            calls.append("adjusted" if adjusted else "raw")
            return frame.loc[pd.Timestamp(fromdate):pd.Timestamp(todate)].copy()

        return SimpleNamespace(get_market_ohlcv_by_date=get_market_ohlcv_by_date)

    def no_fallback(*args, **kwargs):
        raise AssertionError("Fixed KRX responses must not fall back to another provider")

    def no_http(*args, **kwargs):
        raise AssertionError("Price input golden cases must run without HTTP")

    def record_candidate(frame, expected_days):
        nonlocal candidate
        candidate = frame
        return validate_prices(frame, expected_days)

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CHART_SERVING_DATA_DIR", str(data_dir))
        patch.setattr(requests.Session, "request", no_http)
        patch.setattr(krx, "install_request_timeout", lambda: None)
        patch.setattr(providers, "krx", response(raw, expect_adjusted=False))
        patch.setattr(providers, "_krx_request_timeout", nullcontext)
        patch.setattr(prices, "_fetch_ohlcv_fdr", no_fallback)
        patch.setattr(prices, "_fetch_ohlcv_pykrx", no_fallback)
        patch.setattr(providers, "time", SimpleNamespace(sleep=lambda _: None))
        # Importing real pykrx can start authentication before the first price request.
        patch.setitem(sys.modules, "pykrx.website.krx.market.wrap", response(case["adjusted"], expect_adjusted=True))
        patch.setattr(calendar, "get_krx_trading_days", lambda *_: days)
        patch.setattr(prices, "validate_prices", record_candidate)
        try:
            result = fetch_prices(STOCK_CODE, str(raw.index[0].date()), str(raw.index[-1].date()))
        except ValueError as exc:
            if candidate is not None and "expected" in case:
                expected = case["expected"]
                # Validation and provider selection add these columns after the conversion.
                added = {"VWAPOutsideDailyRange", "Trading_Halt", "PriceProvider"}
                columns = [column for column in expected["columns"] if column not in added]
                try:
                    compare(name, {**expected, "columns": columns}, candidate)
                except AssertionError as mismatch:
                    raise mismatch from exc
            raise AssertionError(f"{name}: serving price conversion failed: {exc}") from exc
    if calls != ["raw", "adjusted"]:
        raise AssertionError(f"{name}: unexpected KRX calls {calls}")
    return result


def serialize(prices):
    frame = prices.copy()
    frame["Date"] = pd.to_datetime(frame.Date).map(
        lambda day: day.date().isoformat() if day.tz is None and day == day.normalize() else day.isoformat(),
        na_action="ignore",
    )
    rows = frame.astype(object).where(frame.notna(), None).to_dict("records")
    return {"columns": list(frame.columns), "rows": [{k: _plain(v) for k, v in row.items()} for row in rows]}


def _plain(value):
    if isinstance(value, np.generic):
        return value.item()
    return value


def compare(name, expected, actual):
    """Raise AssertionError naming the case, dates and columns that differ."""
    columns = list(actual.columns)
    if columns != expected["columns"]:
        raise AssertionError(f'{name}: columns differ: expected {expected["columns"]}, got {columns}')
    actual = serialize(actual)
    expected_dates = [row["Date"] for row in expected["rows"]]
    actual_dates = [row["Date"] for row in actual["rows"]]
    if actual_dates != expected_dates:
        for row, (want, got) in enumerate(zip_longest(expected_dates, actual_dates), start=1):
            if want != got:
                raise AssertionError(f"{name}: Date differs at row {row}: expected {want!r}, got {got!r}")
    differences = []
    for want, got in zip(expected["rows"], actual["rows"], strict=True):
        for column in expected["columns"]:
            if not _same(want[column], got[column]):
                differences.append(f'{want["Date"]} {column}: expected {want[column]!r}, got {got[column]!r}')
    if differences:
        shown = "; ".join(differences[:10])
        raise AssertionError(f"{name}: {len(differences)} values differ: {shown}")


def _same(expected, actual):
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, bool) or isinstance(actual, bool) or isinstance(expected, str):
        return type(expected) is type(actual) and expected == actual
    return bool(np.isclose(float(actual), float(expected), **TOLERANCE))


def load_cases():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return [{**case, "raw": _frame(case["raw"]), "adjusted": _frame(case["adjusted"])} for case in golden["cases"]]


def main():
    cases = []
    with tempfile.TemporaryDirectory() as data_dir:
        for case in build_cases():
            # Round-trip through the stored form so the test runs on exactly these inputs.
            case = {**case, "raw": _records(case["raw"]), "adjusted": _records(case["adjusted"])}
            prices = run({**case, "raw": _frame(case["raw"]), "adjusted": _frame(case["adjusted"])},
                         Path(data_dir) / case["name"])
            cases.append({**case, "expected": serialize(prices)})
    golden = {"description": "Fixed raw/adjusted responses at the pykrx boundary and the serving price inputs",
              "command": "python -m serving.tests.price_input_golden",
              "tolerance": TOLERANCE, "cases": cases}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(GOLDEN)


if __name__ == "__main__":
    main()

"""Run the learning collector on five public KRX securities and verify its saved artifacts."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from dotenv import load_dotenv
from experiments.dataset.pipeline import _require_current_training_prices, collect_dataset
from shared.data.krx import authenticated_stock
from shared.data.validation import expected_sessions
from shared.io import sha256
from shared.settings import (
    CHART_ROOT,
    PREPROCESSING,
    TRAINING_PRICE_BASIS,
    VALIDATION_VERSION,
    processing_contract,
)

CASES = {
    "005930": [("2018-05-04", 0.02, 50.0)],
    "004920": [("2020-03-20", 3.0, 1 / 3), ("2026-10-02", 10.0, 0.1)],
    "031820": [("2026-05-06", 10.0, 0.1)],
    "373220": [],
    "003410": [("2020-12-04", 1.0, 1.0)],
}
REPRICING_RETURNS = {"004920": ("2020-03-20", 623 / (295 * 3) - 1),
                     "003410": ("2020-12-04", 6700 / 5550 - 1)}


def verify(root):
    from shared.data.providers import _attach_actual_vwap

    manifest = json.loads((root / "dataset_manifest.json").read_text())
    _require_current_training_prices(manifest)
    if (manifest.get("price_basis") != TRAINING_PRICE_BASIS
            or manifest.get("processing_contract") != processing_contract(manifest["config"]["preprocessing"])):
        raise ValueError("Run collection with the current training price policy before verification")
    calendar = json.loads((root / "calendar.json").read_text())
    metadata = pd.read_csv(root / "ticker_metadata.csv", dtype={"Code": str},
                           parse_dates=["ListingDate", "DelistingDate"])
    event_path = root / manifest["price_events"]["path"]
    if sha256(event_path) != manifest["price_events"]["sha256"]:
        raise ValueError("The event table hash differs from the manifest")
    events = pd.read_parquet(event_path)
    for code, expected_events in CASES.items():
        name = f"{code}.parquet"
        raw_path = root / "krx_raw_prices" / name
        adjusted_path = root / "raw" / name
        if (sha256(raw_path) != manifest["krx_raw_files"][name]
                or sha256(adjusted_path) != manifest["raw_files"][name]):
            raise ValueError(f"{code}: stored price hash differs from the manifest")
        raw = pd.read_parquet(raw_path).set_index("Date")
        adjusted = pd.read_parquet(adjusted_path).set_index("Date")
        intervals = metadata.loc[metadata.Code.eq(code)]
        pd.testing.assert_index_equal(adjusted.index, raw.index)
        pd.testing.assert_index_equal(raw.index, expected_sessions(intervals, calendar), check_names=False)
        pd.testing.assert_frame_equal(adjusted[raw.columns], raw)
        for date, expected_factor, expected_volume in expected_events:
            event = events.loc[events.Code.eq(code) & events.ExDate.eq(pd.Timestamp(date))]
            np.testing.assert_allclose(event.PriceFactor.to_numpy(), [expected_factor])
            np.testing.assert_allclose(event.VolumeFactor.to_numpy(), [expected_volume])
        if code in REPRICING_RETURNS:
            date, expected_return = REPRICING_RETURNS[code]
            np.testing.assert_allclose(adjusted.Change.loc[date] / 100, expected_return, rtol=1e-10)
        if code == "005930" and not adjusted.loc["2018-04-30":"2018-05-03", "Trading_Halt"].eq(1).all():
            raise ValueError("Samsung trading halt was not retained")
        if code == "373220" and raw.index[0] != pd.Timestamp("2022-01-27"):
            raise ValueError("LG Energy Solution history does not begin on the IPO date")
        if code == "003410" and not intervals.DelistingDate.notna().all():
            raise ValueError("Ssangyong C&E delisting is absent from the metadata")

        checked = 0
        differences = []
        for row_index in intervals.index:
            days = expected_sessions(intervals.loc[[row_index]], calendar)
            prices, bars = adjusted.loc[days], raw.loc[days]
            exchange_changes = bars.RawChange / (bars.RawClose - bars.RawChange)
            np.testing.assert_allclose(prices.ExchangeChange / 100, exchange_changes, atol=1e-12, rtol=1e-10)
            observed_returns = prices.Close.pct_change(fill_method=None).iloc[1:]
            np.testing.assert_allclose(prices.Change.iloc[1:] / 100, observed_returns, atol=1e-12, rtol=1e-10)
            if not pd.isna(prices.Change.iloc[0]):
                raise ValueError(f"{code}: first learning return must remain unknown")
            interval_events = events.loc[events.Code.eq(code) & events.ExDate.isin(days)]
            factors = interval_events.set_index("ExDate").PriceFactor.reindex(days, fill_value=1.0)
            expected_returns = bars.RawClose / (bars.RawClose.shift() * factors) - 1
            np.testing.assert_allclose(observed_returns, expected_returns.iloc[1:], atol=1e-12, rtol=1e-10)
            expected_volume = bars.RawVolume.astype(float).copy()
            for event in interval_events.itertuples():
                expected_volume.loc[expected_volume.index < event.ExDate] *= event.VolumeFactor
            np.testing.assert_allclose(prices.Volume, expected_volume, atol=1e-12, rtol=1e-10)
            different = ~np.isclose(observed_returns, exchange_changes.iloc[1:], atol=1e-12, rtol=1e-10)
            differences.extend(days[1:][different].strftime("%Y-%m-%d").tolist())
            regular = exchange_changes.iloc[1:]
            if regular.abs().gt(0.30 + 1e-12).any():
                raise ValueError(f"{code}: KRX intraday change exceeded 30% on {list(regular.index[regular.abs().gt(0.30)])}")
            checked += len(regular)
        expected_differences = [REPRICING_RETURNS[code][0]] if code in REPRICING_RETURNS else []
        if differences != expected_differences:
            raise ValueError(f"{code}: unexplained return differences: {differences}")

        legacy_at_training_close = _attach_actual_vwap(adjusted[["Close"]], raw)
        for column in ["Open", "High", "Low", "Close", "VWAP"]:
            np.testing.assert_allclose(adjusted[column], legacy_at_training_close[column], rtol=1e-10, atol=1e-12)
        volume_changes = int(adjusted.Volume.ne(legacy_at_training_close.Volume).sum())
        if any(volume != 1 for _, _, volume in expected_events) and not volume_changes:
            raise ValueError(f"{code}: no adjusted volumes before the share-count change")
        print(f"{code} | bars={len(raw)} | KRX intraday limit checks={checked} | "
              f"volume adjustments={volume_changes} | preserved repricing={differences}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=CHART_ROOT / ".env")
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(args.env)
    authenticated_stock()
    root = args.root.resolve()
    config = root.with_suffix(".yaml")
    config.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract_version": VALIDATION_VERSION,
        "dataset_id": "training_krx_price_check",
        "root": str(root),
        "collection": {"start_date": "2018-01-02", "end_date": "2026-11-20",
                       "markets": ["KOSPI", "KOSDAQ"], "include_delisted": True,
                       "investor_flows": False, "tickers": list(CASES)},
        "preprocessing": PREPROCESSING,
    }
    if config.exists():
        if yaml.safe_load(config.read_text()) != payload:
            raise ValueError(f"Existing configuration differs: {config}")
    else:
        config.write_text(yaml.safe_dump(payload))
    collect_dataset(config)
    verify(root)


if __name__ == "__main__":
    main()

"""Run the learning collector on five public KRX securities and verify its saved artifacts."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from dotenv import load_dotenv
from experiments.dataset.pipeline import collect_dataset
from shared.data.krx import authenticated_stock
from shared.data.validation import expected_sessions
from shared.io import sha256
from shared.settings import CHART_ROOT, PREPROCESSING, VALIDATION_VERSION

CASES = {
    "005930": ("2018-05-04", 0.02),
    "004920": ("2026-10-02", 10.0),
    "031820": ("2026-05-06", 10.0),
    "373220": None,
    "003410": None,
}


def verify(root):
    from shared.data.providers import _attach_actual_vwap

    manifest = json.loads((root / "dataset_manifest.json").read_text())
    calendar = json.loads((root / "calendar.json").read_text())
    metadata = pd.read_csv(root / "ticker_metadata.csv", dtype={"Code": str},
                           parse_dates=["ListingDate", "DelistingDate"])
    event_path = root / manifest["price_events"]["path"]
    if sha256(event_path) != manifest["price_events"]["sha256"]:
        raise ValueError("The event table hash differs from the manifest")
    events = pd.read_parquet(event_path)
    for code, expected_event in CASES.items():
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
        if expected_event is not None:
            date, expected_factor = expected_event
            event = events.loc[events.Code.eq(code) & events.ExDate.eq(pd.Timestamp(date))]
            np.testing.assert_allclose(event.PriceFactor.to_numpy(), [expected_factor])
            np.testing.assert_allclose(event.VolumeFactor.to_numpy(), [1 / expected_factor])
        if code == "005930" and not adjusted.loc["2018-04-30":"2018-05-03", "Trading_Halt"].eq(1).all():
            raise ValueError("Samsung trading halt was not retained")
        if code == "373220" and raw.index[0] != pd.Timestamp("2022-01-27"):
            raise ValueError("LG Energy Solution history does not begin on the IPO date")
        if code == "003410" and not intervals.DelistingDate.notna().all():
            raise ValueError("Ssangyong C&E delisting is absent from the metadata")

        checked = 0
        for row_index in intervals.index:
            days = expected_sessions(intervals.loc[[row_index]], calendar)
            prices, bars = adjusted.loc[days], raw.loc[days]
            changes = bars.RawChange / (bars.RawClose - bars.RawChange)
            np.testing.assert_allclose(prices.Close.pct_change().iloc[1:], changes.iloc[1:], atol=1e-12, rtol=1e-10)
            regular = changes.iloc[1:]
            if regular.abs().gt(0.30 + 1e-12).any():
                raise ValueError(f"{code}: daily change exceeded 30% on {list(regular.index[regular.abs().gt(0.30)])}")
            checked += len(regular)

        legacy_at_training_close = _attach_actual_vwap(adjusted[["Close"]], raw)
        for column in ["Open", "High", "Low", "Close", "VWAP"]:
            np.testing.assert_allclose(adjusted[column], legacy_at_training_close[column], rtol=1e-10, atol=1e-12)
        volume_changes = int(adjusted.Volume.ne(legacy_at_training_close.Volume).sum())
        if expected_event is not None and not volume_changes:
            raise ValueError(f"{code}: no adjusted volumes before the share-count change")
        print(f"{code} | bars={len(raw)} | price-limit checks={checked} | "
              f"volume adjustments={volume_changes}")


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

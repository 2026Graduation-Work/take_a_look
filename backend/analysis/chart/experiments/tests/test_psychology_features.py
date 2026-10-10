# ruff: noqa: I001

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from experiments.comparison.runner import prepare_profile_data, resolve_feature_sets
from experiments.features.build_psychology_features import main as build_cli
from experiments.features.panel_builder import build_feature_store, load_feature_sources
from experiments.features.psychology.demo_panel import build_demo_price_panel
from experiments.features.psychology.market_psychology import (
    FEATURE_COLUMNS,
    OUTPUT_COLUMNS,
    RAW_FEATURES,
    SUMMARY_AXES,
    TREATMENT_FEATURES,
    PsychologyFeatureConfig,
    PsychologyInputError,
    build_psychology_features,
)


@pytest.fixture(scope="module")
def demo_prices() -> pd.DataFrame:
    return build_demo_price_panel(periods=180)


@pytest.fixture(scope="module")
def demo_features(demo_prices: pd.DataFrame) -> pd.DataFrame:
    features, _ = build_psychology_features(demo_prices)
    return features


# ── 형식 계약 ────────────────────────────────────────────────────────────────


def test_output_columns_and_no_missing_values(demo_features: pd.DataFrame) -> None:
    assert list(demo_features.columns) == list(OUTPUT_COLUMNS)
    assert not demo_features[list(FEATURE_COLUMNS)].isna().any().any()
    assert np.isfinite(demo_features[list(FEATURE_COLUMNS)].to_numpy(dtype=float)).all()
    assert demo_features["Date"].dt.normalize().equals(demo_features["Date"])
    assert demo_features["Code"].map(lambda code: isinstance(code, str)).all()
    assert demo_features["Code"].str.fullmatch(r"\d{6}").all()


def test_feature_names_pass_forbidden_column_rules() -> None:
    for column in FEATURE_COLUMNS:
        canonical = column.strip().casefold()
        assert not canonical.startswith(("target", "future_", "next_"))
        assert not canonical.endswith("_label")
        assert canonical not in {"date", "code", "availabledate"}


def test_all_features_are_bounded(demo_features: pd.DataFrame) -> None:
    values = demo_features[list(FEATURE_COLUMNS)].to_numpy(dtype=float)
    assert values.min() >= -1.0
    assert values.max() <= 1.0


def test_summary_axes_are_equal_weight_means(demo_features: pd.DataFrame) -> None:
    greed_fear = (demo_features["psych_fear_greed"] + demo_features["psych_disposition"]) / 2.0
    crowd = (demo_features["psych_herding"] + demo_features["psych_overreaction"]) / 2.0
    pd.testing.assert_series_equal(
        demo_features["psych_greed_fear_axis"], greed_fear, check_names=False
    )
    pd.testing.assert_series_equal(
        demo_features["psych_crowd_pressure_axis"], crowd, check_names=False
    )


def test_treatment_feature_count_is_within_experiment_budget() -> None:
    # baseline이 161피처이므로 추가분은 적고 개념별로 분리되어 있어야 해석할 수 있다.
    assert TREATMENT_FEATURES == RAW_FEATURES
    assert 2 <= len(TREATMENT_FEATURES) <= 6
    # 요약 축은 원지표의 선형결합이므로 기본 treatment 목록에 넣지 않는다.
    assert not set(SUMMARY_AXES) & set(TREATMENT_FEATURES)


# ── 미래 정보(lookahead) 부재 ────────────────────────────────────────────────


def test_available_date_is_strictly_after_observation_date(demo_features: pd.DataFrame) -> None:
    assert (demo_features["AvailableDate"] > demo_features["Date"]).all()


def test_future_rows_do_not_change_past_features(demo_prices: pd.DataFrame) -> None:
    """뒤쪽 날짜를 잘라내도 앞 구간 값이 그대로여야 미래 정보가 없는 것이다."""
    cutoff = pd.Timestamp("2024-06-14")
    full, _ = build_psychology_features(demo_prices)
    truncated, _ = build_psychology_features(
        demo_prices.loc[pd.to_datetime(demo_prices["Date"]) <= cutoff]
    )
    assert not truncated.empty

    # 잘린 패널의 종목별 마지막 행은 다음 거래일을 아직 모르므로 AvailableDate 비교에서 뺀다.
    last_dates = truncated.groupby("Code", observed=True)["Date"].transform("max")
    comparable = truncated.loc[truncated["Date"] < last_dates]
    merged = comparable.merge(full, on=["Date", "Code"], suffixes=("_cut", "_full"))
    assert len(merged) == len(comparable)
    for column in ("AvailableDate", *FEATURE_COLUMNS):
        pd.testing.assert_series_equal(
            merged[f"{column}_cut"], merged[f"{column}_full"], check_names=False
        )


def test_changing_a_future_price_does_not_change_earlier_features(
    demo_prices: pd.DataFrame,
) -> None:
    """특정 날짜 이후 가격·거래량을 흔들어도 그 이전 피처는 불변이어야 한다."""
    cutoff = pd.Timestamp("2024-06-14")
    baseline, _ = build_psychology_features(demo_prices)

    perturbed = demo_prices.copy()
    future = pd.to_datetime(perturbed["Date"]) > cutoff
    perturbed.loc[future, "Close"] = perturbed.loc[future, "Close"] * 1.5
    perturbed.loc[future, "Volume"] = perturbed.loc[future, "Volume"] * 3.0
    shocked, _ = build_psychology_features(perturbed)

    keys = ["Date", "Code"]
    before = baseline.loc[baseline["Date"] <= cutoff].merge(
        shocked.loc[shocked["Date"] <= cutoff], on=keys, suffixes=("_base", "_shock")
    )
    assert not before.empty
    for column in FEATURE_COLUMNS:
        pd.testing.assert_series_equal(
            before[f"{column}_base"], before[f"{column}_shock"], check_names=False
        )

    # 대조군: 변경한 구간 뒤에서는 값이 실제로 달라져야 이 테스트가 의미를 갖는다.
    after = baseline.loc[baseline["Date"] > cutoff].merge(
        shocked.loc[shocked["Date"] > cutoff], on=keys, suffixes=("_base", "_shock")
    )
    assert not after["psych_fear_greed_base"].equals(after["psych_fear_greed_shock"])


def test_warmup_rows_are_dropped(demo_prices: pd.DataFrame) -> None:
    config = PsychologyFeatureConfig()
    features, metadata = build_psychology_features(demo_prices, config)
    rows_per_code = demo_prices.groupby("Code", observed=True)["Date"].count().min()
    expected = rows_per_code - (config.warmup_trading_days - 1)
    assert set(features.groupby("Code", observed=True).size()) == {expected}
    assert metadata["warmup_trading_days"] == config.warmup_trading_days


# ── 결정론 ───────────────────────────────────────────────────────────────────


def test_repeated_runs_are_identical(demo_prices: pd.DataFrame) -> None:
    first, first_meta = build_psychology_features(demo_prices)
    second, second_meta = build_psychology_features(demo_prices)
    pd.testing.assert_frame_equal(first, second)
    assert first_meta == second_meta


def test_row_order_does_not_change_output(demo_prices: pd.DataFrame) -> None:
    shuffled = demo_prices.sample(frac=1.0, random_state=0).reset_index(drop=True)
    ordered, ordered_meta = build_psychology_features(demo_prices)
    scrambled, scrambled_meta = build_psychology_features(shuffled)
    pd.testing.assert_frame_equal(ordered, scrambled)
    assert (
        ordered_meta["input"]["fingerprint_sha256"]
        == scrambled_meta["input"]["fingerprint_sha256"]
    )


def test_demo_panel_is_seed_stable() -> None:
    pd.testing.assert_frame_equal(build_demo_price_panel(), build_demo_price_panel())


def test_metadata_records_config_and_version(demo_prices: pd.DataFrame) -> None:
    config = PsychologyFeatureConfig(fear_greed_window=15)
    _, metadata = build_psychology_features(demo_prices, config)
    assert metadata["feature_profile"] == "psychology_market_v1"
    assert metadata["generator_version"]
    assert metadata["config"]["fear_greed_window"] == 15
    assert metadata["features"]["recommended_treatment"] == list(TREATMENT_FEATURES)


# ── 입력 검증 ────────────────────────────────────────────────────────────────


def test_duplicate_keys_are_rejected(demo_prices: pd.DataFrame) -> None:
    duplicated = pd.concat([demo_prices, demo_prices.head(1)], ignore_index=True)
    with pytest.raises(PsychologyInputError, match="중복"):
        build_psychology_features(duplicated)


def test_non_positive_close_is_rejected(demo_prices: pd.DataFrame) -> None:
    broken = demo_prices.copy()
    broken.loc[0, "Close"] = 0.0
    with pytest.raises(PsychologyInputError, match="Close"):
        build_psychology_features(broken)


def test_short_history_is_rejected() -> None:
    with pytest.raises(PsychologyInputError, match="워밍업"):
        build_psychology_features(build_demo_price_panel(periods=30))


def test_invalid_config_is_rejected() -> None:
    with pytest.raises(PsychologyInputError):
        PsychologyFeatureConfig(fear_greed_window=1)
    with pytest.raises(PsychologyInputError):
        PsychologyFeatureConfig(overreaction_short_window=60, overreaction_long_window=60)


# ── 저장소의 기존 계약과의 정합성 ────────────────────────────────────────────


def test_output_passes_external_feature_source_contract(
    demo_features: pd.DataFrame, tmp_path: Path
) -> None:
    """산출물이 build_feature_panel.py의 추가 피처 계약을 그대로 통과하는지 본다."""
    path = tmp_path / "psychology_market_v1.parquet"
    demo_features.to_parquet(path, index=False)

    loaded = load_feature_sources(
        [
            {
                "name": "psychology_market",
                "path": str(path),
                "apply_period": "one_day",
                "columns": list(FEATURE_COLUMNS),
                "missing": {"policy": "drop", "add_indicator": False},
            }
        ]
    )

    assert len(loaded) == 1
    assert set(loaded[0].spec.columns) == set(FEATURE_COLUMNS)
    assert len(loaded[0].frame) == len(demo_features)


def _write_processed_store(directory: Path, panel: pd.DataFrame) -> None:
    """러너가 읽는 baseline feature store(=data/processed) 형태로 저장한다."""
    directory.mkdir(parents=True, exist_ok=True)
    for code, group in panel.groupby("Code", sort=True, observed=True):
        frame = group.sort_values("Date", kind="stable").reset_index(drop=True)
        log_return = np.log(frame["Close"] / frame["Close"].shift(1)).fillna(0.0)
        frame = frame.assign(
            Name=f"종목{code}",
            IsDelisted=0,
            Log_Ret=log_return,
            Sigma=log_return.rolling(20, min_periods=1).std(ddof=0).fillna(0.01).clip(lower=0.005),
            Trading_Halt=0,
            chart_feature_a=log_return.rolling(5, min_periods=1).mean(),
            chart_feature_b=frame["Volume"] / frame["Volume"].rolling(20, min_periods=1).mean(),
        )
        frame.to_parquet(directory / f"{code}.parquet", index=False)


def _comparison_config(
    baseline_dir: Path,
    treatment_dir: Path,
    *,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
) -> dict:
    return {
        "features": {
            "baseline": ["chart_feature_a", "chart_feature_b"],
            "treatment": list(TREATMENT_FEATURES),
        },
        "profiles": {
            "aggressive": {
                "data": {
                    "baseline_price_dir": str(baseline_dir),
                    "treatment_price_dir": str(treatment_dir),
                    "tickers": [],
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                },
                "labels": {
                    "type": "dynamic_sigma",
                    "horizon": 5,
                    "up_mult": 1.0,
                    "down_mult": 1.0,
                },
            }
        },
    }


def test_generated_store_satisfies_comparison_runner_contract(
    demo_prices: pd.DataFrame, demo_features: pd.DataFrame, tmp_path: Path
) -> None:
    """실험을 실행하지 않고, 러너의 로딩·A/B 정합성 검증만 통과하는지 확인한다.

    실제 운용 경로를 그대로 재현한다.
    ``build_psychology_features`` → ``data/external`` → ``build_feature_store`` →
    ``treatment_price_dir``.
    """
    processed_dir = tmp_path / "processed"
    _write_processed_store(processed_dir, demo_prices)

    external_path = tmp_path / "external" / "psychology_market_v1.parquet"
    external_path.parent.mkdir(parents=True, exist_ok=True)
    demo_features.to_parquet(external_path, index=False)

    store_dir = tmp_path / "feature_store" / "psychology_market_v1"
    manifest = build_feature_store(
        {
            "features": {
                "profile_name": "psychology_market_v1",
                "base_processed_dir": str(processed_dir),
                "base_columns": "*",
                "materialized_dir": str(store_dir),
                "sources": [
                    {
                        "name": "psychology_market",
                        "path": str(external_path),
                        "apply_period": "one_day",
                        "columns": list(FEATURE_COLUMNS),
                        "missing": {"policy": "drop", "add_indicator": False},
                    }
                ],
            }
        }
    )
    assert manifest["sources"][0]["columns"] == list(FEATURE_COLUMNS)
    assert sorted(path.name for path in store_dir.glob("*.parquet")) == sorted(
        path.name for path in processed_dir.glob("*.parquet")
    )

    # AvailableDate 규약 때문에 treatment store는 baseline보다 늦게 시작한다
    # (워밍업 + 하루). 실험 구간은 그 안쪽으로 잡아야 A/B 행이 같아진다.
    store_panel = pd.concat(
        [pd.read_parquet(path) for path in sorted(store_dir.glob("*.parquet"))], ignore_index=True
    )
    base_panel = pd.concat(
        [pd.read_parquet(path) for path in sorted(processed_dir.glob("*.parquet"))],
        ignore_index=True,
    )
    warmup = PsychologyFeatureConfig().warmup_trading_days
    assert store_panel["Date"].min() > base_panel["Date"].min()
    assert len(store_panel) == len(base_panel) - warmup * base_panel["Code"].nunique()

    config = _comparison_config(
        processed_dir,
        store_dir,
        train_start="2024-04-02",
        train_end="2024-06-28",
        test_start="2024-07-01",
        test_end="2024-08-15",
    )
    baseline_features, treatment_features = resolve_feature_sets(config, tmp_path)
    assert treatment_features == list(TREATMENT_FEATURES)
    assert not set(baseline_features) & set(treatment_features)

    (
        base_train,
        base_test,
        treat_train,
        treat_test,
        resolved_baseline,
        resolved_treatment,
        metadata,
    ) = prepare_profile_data(config, "aggressive", config_dir=tmp_path)

    # A/B 행·라벨 정합성은 러너가 스스로 검사한다. 여기서는 통과 사실과 형식을 본다.
    assert len(base_train) == len(treat_train) > 0
    assert len(base_test) == len(treat_test) > 0
    assert resolved_baseline == ["chart_feature_a", "chart_feature_b"]
    assert resolved_treatment == list(TREATMENT_FEATURES)
    assert metadata["train_key_label_hash"] and metadata["test_key_label_hash"]
    for column in TREATMENT_FEATURES:
        assert column in treat_train.columns
        assert column not in base_train.columns
    assert set(treat_train["Y_Label"].unique()) == {0, 1, 2}


def test_runner_rejects_treatment_store_with_missing_psychology_values(
    demo_prices: pd.DataFrame, demo_features: pd.DataFrame, tmp_path: Path
) -> None:
    """워밍업 구간을 실험 기간에 넣으면 조용히 통과하지 않고 실패해야 한다."""
    from experiments.comparison.runner import ComparisonConfigError

    processed_dir = tmp_path / "processed"
    _write_processed_store(processed_dir, demo_prices)
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    for code in sorted(demo_prices["Code"].unique()):
        base = pd.read_parquet(processed_dir / f"{code}.parquet")
        merged = base.merge(
            demo_features.loc[demo_features["Code"] == code].drop(columns=["AvailableDate"]),
            on=["Date", "Code"],
            how="left",
        )
        merged.to_parquet(store_dir / f"{code}.parquet", index=False)

    config = _comparison_config(
        processed_dir,
        store_dir,
        train_start="2024-01-02",  # 워밍업이 끝나기 전 구간을 학습에 포함시킨다.
        train_end="2024-03-15",
        test_start="2024-04-02",
        test_end="2024-08-15",
    )
    with pytest.raises(ComparisonConfigError, match="missing/non-finite"):
        prepare_profile_data(config, "aggressive", config_dir=tmp_path)


# ── 저장소에 커밋된 실제 가격 패널로 하는 생성 검증 ──────────────────────────

CHART_DIR = Path(__file__).resolve().parents[2]
SAMPLE_PROCESSED = CHART_DIR / "data" / "processed" / "005930.parquet"


@pytest.fixture(scope="module")
def real_prices() -> pd.DataFrame:
    if not SAMPLE_PROCESSED.exists():
        pytest.skip(f"샘플 processed 패널이 없습니다: {SAMPLE_PROCESSED}")
    frame = pd.read_parquet(SAMPLE_PROCESSED, columns=["Date", "Code", "Close", "Volume"])
    return frame.loc[
        pd.to_datetime(frame["Date"]).between(pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31"))
    ].reset_index(drop=True)


def test_real_ticker_generation(real_prices: pd.DataFrame) -> None:
    """커밋된 005930 Alpha158 패널로 실제 생성이 되는지 확인한다."""
    features, metadata = build_psychology_features(real_prices)

    assert metadata["input"]["codes"] == 1
    assert metadata["output"]["rows"] > 100
    assert list(features.columns) == list(OUTPUT_COLUMNS)
    assert not features.isna().any().any()
    assert features[list(FEATURE_COLUMNS)].abs().to_numpy().max() <= 1.0
    assert (features["AvailableDate"] > features["Date"]).all()
    assert features["Date"].is_monotonic_increasing
    # 워밍업 때문에 산출 시작일은 입력 시작일보다 늦다.
    assert features["Date"].min() > pd.to_datetime(real_prices["Date"]).min()


def test_real_ticker_has_no_lookahead(real_prices: pd.DataFrame) -> None:
    cutoff = pd.Timestamp("2023-09-29")
    full, _ = build_psychology_features(real_prices)
    truncated, _ = build_psychology_features(
        real_prices.loc[pd.to_datetime(real_prices["Date"]) <= cutoff]
    )
    comparable = truncated.loc[truncated["Date"] < truncated["Date"].max()]
    assert not comparable.empty
    merged = comparable.merge(full, on=["Date", "Code"], suffixes=("_cut", "_full"))
    assert len(merged) == len(comparable)
    for column in FEATURE_COLUMNS:
        pd.testing.assert_series_equal(
            merged[f"{column}_cut"], merged[f"{column}_full"], check_names=False
        )


def test_real_ticker_generation_is_deterministic(real_prices: pd.DataFrame) -> None:
    first, first_meta = build_psychology_features(real_prices)
    second, second_meta = build_psychology_features(real_prices)
    pd.testing.assert_frame_equal(first, second)
    assert first_meta["output"]["fingerprint_sha256"] == second_meta["output"]["fingerprint_sha256"]


# ── 생성 스크립트 ────────────────────────────────────────────────────────────


def test_cli_generates_parquet_metadata_and_sample(tmp_path: Path) -> None:
    output = tmp_path / "psychology_market_v1.parquet"
    sample = tmp_path / "sample.csv"
    exit_code = build_cli(
        [
            "--demo",
            "--demo-periods",
            "120",
            "--out",
            str(output),
            "--sample-csv",
            str(sample),
            "--sample-rows",
            "3",
        ]
    )

    assert exit_code == 0
    features = pd.read_parquet(output)
    assert list(features.columns) == list(OUTPUT_COLUMNS)
    assert not features.empty

    metadata = json.loads(output.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert metadata["source"]["kind"] == "synthetic_demo_panel"
    assert metadata["output"]["rows"] == len(features)
    assert metadata["environment"]["pandas"] == pd.__version__

    sample_frame = pd.read_csv(sample, dtype={"Code": str})
    assert len(sample_frame) == 3 * features["Code"].nunique()
    assert sample_frame["Code"].str.fullmatch(r"\d{6}").all()


def test_cli_refuses_to_overwrite_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "psychology_market_v1.parquet"
    assert build_cli(["--demo", "--demo-periods", "120", "--out", str(output)]) == 0
    with pytest.raises(SystemExit) as error:
        build_cli(["--demo", "--demo-periods", "120", "--out", str(output)])
    assert error.value.code == 2
    assert build_cli(["--demo", "--demo-periods", "120", "--out", str(output), "--overwrite"]) == 0


def test_cli_output_is_reproducible_across_runs(tmp_path: Path) -> None:
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    build_cli(["--demo", "--demo-periods", "120", "--out", str(first)])
    build_cli(["--demo", "--demo-periods", "120", "--out", str(second)])

    pd.testing.assert_frame_equal(pd.read_parquet(first), pd.read_parquet(second))
    first_meta = json.loads(first.with_suffix(".meta.json").read_text(encoding="utf-8"))
    second_meta = json.loads(second.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert first_meta == second_meta

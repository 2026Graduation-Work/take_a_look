# ruff: noqa: I001

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from experiments.features.panel_builder import (
    FeatureContractError,
    _select_base_columns,
    assemble_feature_panel,
    build_feature_store,
    load_feature_sources,
)


def _base_panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-02", periods=4, freq="B"),
            "Code": ["005930"] * 4,
            "Close": [70000.0, 70100.0, 70200.0, 70300.0],
            "alpha_feature": [0.1, 0.2, 0.3, 0.4],
        }
    )


def _two_code_base_panel() -> pd.DataFrame:
    dates = pd.date_range("2024-01-05", periods=4, freq="B")
    return pd.concat(
        [
            pd.DataFrame({"Date": dates, "Code": "005930", "Close": 70000.0}),
            pd.DataFrame({"Date": dates, "Code": "000660", "Close": 120000.0}),
        ],
        ignore_index=True,
    )


def _source_config(path: Path, **overrides: object) -> dict:
    config = {
        "name": "news",
        "path": str(path),
        "apply_period": "one_day",
        "columns": ["news_sentiment"],
        "missing": {"policy": "zero", "add_indicator": True},
    }
    config.update(overrides)
    return config


def test_one_day_source_applies_only_on_available_date(tmp_path: Path) -> None:
    source_path = tmp_path / "news.parquet"
    pd.DataFrame(
        {
            "Date": ["2024-01-02"],
            "Code": ["005930"],
            "AvailableDate": ["2024-01-03"],
            "news_sentiment": [0.7],
        }
    ).to_parquet(source_path, index=False)

    panel, report = assemble_feature_panel(
        _base_panel(), load_feature_sources([_source_config(source_path)])
    )

    assert panel["news_sentiment"].tolist() == [0.0, 0.7, 0.0, 0.0]
    assert panel["news__news_sentiment__missing"].tolist() == [1, 0, 1, 1]
    assert report["sources"]["news"]["apply_period"] == "one_day"


def test_until_next_update_never_uses_future_value(tmp_path: Path) -> None:
    source_path = tmp_path / "financial.parquet"
    pd.DataFrame(
        {
            "Date": ["2023-12-31", "2024-01-04"],
            "Code": ["005930", "005930"],
            "AvailableDate": ["2024-01-03", "2024-01-05"],
            "financial_health_score": [8.0, 6.5],
        }
    ).to_parquet(source_path, index=False)

    config = _source_config(
        source_path,
        name="financial",
        apply_period="until_next_update",
        columns=["financial_health_score"],
        missing={"policy": "zero", "add_indicator": True, "max_staleness_trading_days": 120},
    )
    panel, _ = assemble_feature_panel(_base_panel(), load_feature_sources([config]))

    # 1/2에는 1/3 공개값을 아직 알 수 없고, 1/5부터 새 재무점수로 바뀐다.
    assert panel["financial_health_score"].tolist() == [0.0, 8.0, 8.0, 6.5]
    assert panel["financial__financial_health_score__missing"].tolist() == [1, 0, 0, 0]


def test_one_day_weekend_available_date_maps_to_next_trading_day(tmp_path: Path) -> None:
    source_path = tmp_path / "weekend_news.parquet"
    pd.DataFrame(
        {
            "Date": ["2024-01-05"],
            "Code": ["005930"],
            "AvailableDate": ["2024-01-07"],
            "news_sentiment": [0.7],
        }
    ).to_parquet(source_path, index=False)

    base = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-05", "2024-01-08", "2024-01-09"]),
            "Code": ["005930"] * 3,
            "Close": [70000.0, 70100.0, 70200.0],
        }
    )
    panel, _ = assemble_feature_panel(base, load_feature_sources([_source_config(source_path)]))

    assert panel["news_sentiment"].tolist() == [0.0, 0.7, 0.0]


def test_until_next_update_vectorized_join_keeps_codes_separate(tmp_path: Path) -> None:
    source_path = tmp_path / "financial_multi.parquet"
    pd.DataFrame(
        {
            "Date": ["2024-01-05", "2024-01-05"],
            "Code": ["005930", "000660"],
            "AvailableDate": ["2024-01-08", "2024-01-09"],
            "financial_health_score": [8.0, 3.0],
        }
    ).to_parquet(source_path, index=False)
    config = _source_config(
        source_path,
        name="financial",
        apply_period="until_next_update",
        columns=["financial_health_score"],
        missing={"policy": "zero", "max_staleness_trading_days": 120},
    )

    panel, _ = assemble_feature_panel(_two_code_base_panel(), load_feature_sources([config]))
    values = panel.pivot(index="Date", columns="Code", values="financial_health_score")

    assert values["005930"].tolist() == [0.0, 8.0, 8.0, 8.0]
    assert values["000660"].tolist() == [0.0, 0.0, 3.0, 3.0]


def test_until_next_update_expires_stale_value(tmp_path: Path) -> None:
    source_path = tmp_path / "stale_financial.parquet"
    pd.DataFrame(
        {
            "Date": ["2024-01-02"],
            "Code": ["005930"],
            "AvailableDate": ["2024-01-02"],
            "financial_health_score": [8.0],
        }
    ).to_parquet(source_path, index=False)
    config = _source_config(
        source_path,
        name="financial",
        apply_period="until_next_update",
        columns=["financial_health_score"],
        missing={"policy": "zero", "max_staleness_trading_days": 1},
    )

    panel, _ = assemble_feature_panel(_base_panel(), load_feature_sources([config]))

    assert panel["financial_health_score"].tolist() == [8.0, 8.0, 0.0, 0.0]


def test_forward_fill_requires_and_respects_staleness_limit(tmp_path: Path) -> None:
    source_path = tmp_path / "sparse_news.parquet"
    pd.DataFrame(
        {
            "Date": ["2024-01-02"],
            "Code": ["005930"],
            "AvailableDate": ["2024-01-03"],
            "news_sentiment": [0.7],
        }
    ).to_parquet(source_path, index=False)
    config = _source_config(
        source_path,
        missing={"policy": "forward_fill", "max_staleness_trading_days": 1},
    )

    panel, _ = assemble_feature_panel(_base_panel(), load_feature_sources([config]))

    assert pd.isna(panel.loc[0, "news_sentiment"])
    assert panel.loc[1:2, "news_sentiment"].tolist() == [0.7, 0.7]
    assert pd.isna(panel.loc[3, "news_sentiment"])


def test_forward_fill_sorts_shuffled_base_before_propagating(tmp_path: Path) -> None:
    source_path = tmp_path / "shuffled_news.parquet"
    pd.DataFrame(
        {
            "Date": ["2024-01-04"],
            "Code": ["005930"],
            "AvailableDate": ["2024-01-04"],
            "news_sentiment": [0.7],
        }
    ).to_parquet(source_path, index=False)
    base = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-04", "2024-01-02", "2024-01-03"]),
            "Code": ["005930"] * 3,
            "Close": [70200.0, 70000.0, 70100.0],
        }
    )
    config = _source_config(
        source_path,
        missing={"policy": "forward_fill", "max_staleness_trading_days": 2},
    )

    panel, _ = assemble_feature_panel(base, load_feature_sources([config]))

    assert panel["Date"].tolist() == list(
        pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    )
    assert panel["news_sentiment"].isna().tolist() == [True, True, False]
    assert panel.loc[2, "news_sentiment"] == pytest.approx(0.7)


@pytest.mark.parametrize(
    "column",
    [
        "target",
        " Target_H5 ",
        "Y_LABEL",
        "future_return",
        "NEXT_DAY_RETURN",
        " date ",
        "CODE",
        "availabledate",
    ],
)
def test_rejects_target_like_and_reserved_source_columns(
    tmp_path: Path, column: str
) -> None:
    config = _source_config(tmp_path / "unused.parquet", columns=[column])

    with pytest.raises(FeatureContractError, match="키, 미래 정보 또는 target"):
        load_feature_sources([config])


@pytest.mark.parametrize("base_columns", ["*", ["alpha_feature", "TaRgEt_H5"]])
def test_rejects_target_like_columns_in_base_panel(base_columns: object) -> None:
    base = _base_panel()
    base["TaRgEt_H5"] = [1.0, 0.0, -1.0, 1.0]

    with pytest.raises(FeatureContractError, match="기본 processed 패널.*target"):
        _select_base_columns(base, {"base_columns": base_columns})


def test_allows_training_y_label_in_base_panel() -> None:
    base = _base_panel()
    base["Y_Label"] = [2, 0, 2, 1]

    selected = _select_base_columns(base, {"base_columns": "*"})

    assert selected["Y_Label"].tolist() == [2, 0, 2, 1]


def test_mixed_date_formats_follow_declared_pandas_contract(tmp_path: Path) -> None:
    source_path = tmp_path / "mixed_dates.parquet"
    pd.DataFrame(
        {
            "Date": ["2024-01-02", "2024.01.03 09:00"],
            "Code": ["005930", "005930"],
            "AvailableDate": ["2024/01/02", "2024-01-03 09:00:00"],
            "news_sentiment": [0.1, 0.2],
        }
    ).to_parquet(source_path, index=False)

    loaded = load_feature_sources([_source_config(source_path)])[0].frame

    assert loaded["Date"].tolist() == list(pd.to_datetime(["2024-01-02", "2024-01-03"]))
    assert loaded["AvailableDate"].tolist() == list(
        pd.to_datetime(["2024-01-02", "2024-01-03"])
    )


def test_rejects_duplicate_available_date_for_one_code(tmp_path: Path) -> None:
    source_path = tmp_path / "duplicate.parquet"
    pd.DataFrame(
        {
            "Date": ["2024-01-01", "2024-01-02"],
            "Code": ["005930", "005930"],
            "AvailableDate": ["2024-01-03", "2024-01-03"],
            "news_sentiment": [0.1, 0.2],
        }
    ).to_parquet(source_path, index=False)

    with pytest.raises(FeatureContractError, match="같은 Code/AvailableDate"):
        load_feature_sources([_source_config(source_path)])


def test_build_feature_store_keeps_processed_input_unchanged(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed"
    external_dir = tmp_path / "external"
    output_dir = tmp_path / "feature_store" / "text_financial"
    processed_dir.mkdir()
    external_dir.mkdir()
    base = _base_panel()
    base["unused_alpha_feature"] = [1.0, 2.0, 3.0, 4.0]
    base.to_parquet(processed_dir / "005930.parquet", index=False)
    source_path = external_dir / "news.parquet"
    pd.DataFrame(
        {
            "Date": ["2024-01-02"],
            "Code": ["005930"],
            "AvailableDate": ["2024-01-03"],
            "news_sentiment": [0.7],
        }
    ).to_parquet(source_path, index=False)

    config = {
        "data": {"price_dir": str(output_dir)},
        "features": {
            "profile_name": "text_financial",
            "base_processed_dir": str(processed_dir),
            "materialized_dir": str(output_dir),
            "base_columns": ["alpha_feature"],
            "sources": [_source_config(source_path)],
        },
    }
    manifest = build_feature_store(config)

    stored = pd.read_parquet(output_dir / "005930.parquet")
    original = pd.read_parquet(processed_dir / "005930.parquet")
    assert "news_sentiment" in stored.columns
    assert "alpha_feature" in stored.columns
    assert "unused_alpha_feature" not in stored.columns
    assert "Close" in stored.columns
    assert "news_sentiment" not in original.columns
    assert manifest["profile_name"] == "text_financial"
    assert (output_dir / "feature_manifest.json").is_file()

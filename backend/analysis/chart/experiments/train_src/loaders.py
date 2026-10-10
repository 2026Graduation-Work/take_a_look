import glob
import os

import numpy as np
import pandas as pd
from tqdm import tqdm

from .labels import apply_dynamic_sigma_barrier_labeling, apply_fixed_barrier_labeling


def load_parquet_data(
    data_dir: str,
    start_date: str = None,
    end_date: str = None,
    columns_only: list = None,
    tickers: str | list[str] | tuple[str, ...] = None,
    label_params: dict = None,
    label_observation_end: str = None,
    training: bool = False,
    keep_date: bool = False,
    universe_only: bool = False,
    strict: bool = True,
    universe_intervals: pd.DataFrame = None,
    feature_columns: list[str] = None,
    sample_only: bool = False,
) -> pd.DataFrame:
    """
    Parquet 파일들을 디스크에서 읽어오는 로더입니다.
    메모리 절약을 위해 종목별 로딩 시점에 Y 라벨 생성 및 피처 분리를 즉시 수행합니다.
    """
    files = sorted(glob.glob(os.path.join(data_dir, "*.parquet")))
    files = [path for path in files if os.path.basename(path) != "sample_keys.parquet"]

    if tickers == "KOSPI_TOP200":
        raise ValueError(
            "KOSPI_TOP200 실시간 조회는 시점에 따라 유니버스가 달라져 재현할 수 없습니다. "
            "실험 시점의 6자리 종목 코드 목록을 data.tickers에 명시하세요."
        )

    if tickers:
        requested_codes = (
            {part.strip().zfill(6) for part in tickers.split(",") if part.strip()}
            if isinstance(tickers, str)
            else {str(code).strip().zfill(6) for code in tickers}
        )
        available_codes = {os.path.basename(path).split(".")[0].zfill(6) for path in files}
        if missing_codes := requested_codes - available_codes:
            raise FileNotFoundError(f"Missing requested ticker files: {sorted(missing_codes)}")
        files = [
            path
            for path in files
            if os.path.basename(path).split(".")[0].zfill(6) in requested_codes
        ]
        if not files:
            raise ValueError(
                "data.tickers와 일치하는 parquet 파일이 없습니다: "
                f"{sorted(requested_codes)}"
            )

    print(f"총 {len(files)}개 종목 데이터 로드 중... (날짜 필터: {start_date} ~ {end_date})")

    df_list = []
    for f in tqdm(files, desc="데이터 파일 로드 중", mininterval=0.5):
        try:
            if columns_only is not None:
                import pyarrow.parquet as pq

                file_schema_names = pq.read_schema(f).names
                required_cols = [
                    "UniverseEligible",
                    "Date",
                    "Code",
                    "Close",
                    "High",
                    "Low",
                    "Open",
                    "Volume",
                    "Trading_Halt",
                    "Sigma",
                ]
                required_cols.append("SampleEligible")
                requested_features = feature_columns or []
                if missing := set(requested_features) - set(file_schema_names):
                    raise ValueError(f"Missing selected features: {sorted(missing)}")
                cols_to_load = list(dict.fromkeys(columns_only + required_cols + requested_features))
                cols_to_load = [col for col in cols_to_load if col in file_schema_names]
                temp_df = pd.read_parquet(f, columns=cols_to_load)
            else:
                temp_df = pd.read_parquet(f)

            if temp_df.empty:
                continue

            temp_df["Date"] = pd.to_datetime(temp_df["Date"])
            temp_df = temp_df.sort_values("Date").reset_index(drop=True)
            if start_date is not None:
                temp_df = temp_df[temp_df["Date"] >= pd.to_datetime(start_date)]

            # 라벨은 t 이후 horizon 거래일의 가격을 참조한다. 요청 종료일에서
            # 즉시 자르면 마지막 horizon 행의 실제 라벨이 모두 사라진다. 따라서
            # 라벨 생성시에만 종목별 우측 버퍼를 함께 읽고, 생성 뒤 요청 기간으로
            # 다시 제한한다. dynamic barrier는 거래정지일을 건너뛸 수 있어 더 넉넉한
            # 탐색 범위를 사용한다.
            requested_end = pd.to_datetime(end_date) if end_date is not None else None
            observation_end = (
                pd.to_datetime(label_observation_end)
                if label_observation_end is not None
                else None
            )
            if requested_end is not None:
                if label_params is None:
                    temp_df = temp_df[temp_df["Date"] <= requested_end]
                elif observation_end is not None:
                    temp_df = temp_df[temp_df["Date"] <= observation_end]
                else:
                    horizon = int(label_params["horizon"])
                    label_type = label_params.get("type", "fixed")
                    buffer_rows = horizon
                    if label_type == "dynamic_sigma":
                        buffer_rows = int(np.ceil(horizon * 2.5))

                    in_requested_period = temp_df[temp_df["Date"] <= requested_end]
                    right_buffer = temp_df[temp_df["Date"] > requested_end].head(buffer_rows)
                    temp_df = pd.concat([in_requested_period, right_buffer], ignore_index=True)

            if temp_df.empty:
                continue

            # [실시간 고속 Y 라벨링] 로딩 시점에 종목별로 즉시 라벨 생성 (OOM 원천 방지)
            if label_params is not None:
                label_type = label_params.get("type", "fixed")
                horizon = label_params["horizon"]

                if label_type == "dynamic_sigma":
                    up_mult = label_params.get("up_mult", 1.5)
                    down_mult = label_params.get("down_mult", 1.2)
                    y_label_series = apply_dynamic_sigma_barrier_labeling(
                        temp_df, horizon, up_mult, down_mult
                    )
                else:
                    tp = label_params.get("tp", 3.5)
                    sl = label_params.get("sl", 2.0)
                    y_label_series = apply_fixed_barrier_labeling(temp_df, horizon, tp, sl)

                temp_df["Y_Label"] = y_label_series.map({-1: 0, 0: 1, 1: 2})
                temp_df = temp_df.dropna(subset=["Y_Label"])
                temp_df["Y_Label"] = temp_df["Y_Label"].astype(int)

                if requested_end is not None:
                    temp_df = temp_df[temp_df["Date"] <= requested_end]

            if temp_df.empty:
                continue

            if universe_intervals is not None:
                code = os.path.basename(f).split(".")[0].upper().zfill(6)
                intervals = universe_intervals.loc[universe_intervals.Code.eq(code)]
                eligible = pd.Series(False, index=temp_df.index)
                for interval in intervals.itertuples():
                    active = temp_df.Date.ge(interval.ListingDate)
                    if pd.notna(interval.DelistingDate):
                        active &= temp_df.Date.lt(interval.DelistingDate)
                    eligible |= active
                temp_df["UniverseEligible"] = eligible
                if universe_only or training or label_params is not None or sample_only:
                    temp_df = temp_df.loc[eligible].copy()

            # Keep the full price path until labels have been calculated. Index
            # exits must not shorten horizons or erase subsequent exit prices.
            if universe_only:
                if "UniverseEligible" not in temp_df and universe_intervals is None:
                    raise ValueError("UniverseEligible is required for PIT filtering")
                if "UniverseEligible" in temp_df:
                    temp_df = temp_df.loc[temp_df["UniverseEligible"].eq(True)].copy()
                if "Trading_Halt" in temp_df:
                    temp_df = temp_df.loc[temp_df.Trading_Halt.eq(0)].copy()

            if feature_columns is not None:
                if missing := set(feature_columns) - set(temp_df):
                    raise ValueError(f"Missing selected features: {sorted(missing)}")
            if training or sample_only:
                if "SampleEligible" in temp_df:
                    temp_df = temp_df.loc[temp_df.SampleEligible.eq(True)].copy()
                if "Trading_Halt" in temp_df:
                    temp_df = temp_df.loc[temp_df.Trading_Halt.eq(0)].copy()
                if "roc_60" in temp_df and "SampleEligible" not in temp_df:
                    temp_df = temp_df.loc[temp_df.roc_60.notna()].copy()
                if "Sigma" in temp_df:
                    temp_df = temp_df.loc[temp_df.Sigma.notna()].copy()

            # [훈련 피처 다이어트] 훈련 데이터셋 로딩 시 즉각 피처만 남겨서 peak 메모리 최소화
            if training:
                exclude_cols = [
                    "Code",
                    "Name",
                    "Open",
                    "High",
                    "Low",
                    "Close",
                    "Volume",
                    "IsDelisted",
                    "Log_Ret",
                    "Sigma",
                    "Y_Label",
                    "Trading_Halt",
                    "UniverseEligible",
                    "VWAP", "Amount", "RawClose", "RawVolume", "AdjustmentFactor",
                ]
                if not keep_date:
                    exclude_cols.append("Date")
                exclude_cols.append("SampleEligible")
                feature_cols = feature_columns or [c for c in temp_df.columns if c not in exclude_cols]
                temp_df = temp_df[feature_cols + ["Y_Label"]]

            # [메모리 최적화] 카테고리 캐스팅
            if "Code" in temp_df.columns:
                temp_df["Code"] = temp_df["Code"].astype("category")
            if "Name" in temp_df.columns:
                temp_df["Name"] = temp_df["Name"].astype("category")

            df_list.append(temp_df)
        except Exception as e:
            if strict:
                raise ValueError(f"Failed to load {f}: {e}") from e
            print(f"Error loading {f}: {e}")

    if not df_list:
        raise ValueError(f"해당 기간({start_date} ~ {end_date})에 로드된 데이터가 없습니다.")

    full_df = pd.concat(df_list, ignore_index=True)

    del df_list
    import gc

    gc.collect()

    # 만약 training용 데이터라면 sort_values 생략하여 peak 메모리 한 번 더 절감
    if not training:
        full_df = full_df.sort_values(by=["Date", "Code"]).reset_index(drop=True)

    print(f"로드 완료: {len(full_df):,}행, 컬럼 수: {len(full_df.columns)}개")
    return full_df

import glob
import os

import numpy as np
import pandas as pd
from tqdm import tqdm

try:
    from .trading_calendar import get_krx_trading_days, reindex_to_krx_trading_days
except ImportError:  # 직접 스크립트 실행: python data_collectors/preprocess_data.py
    from trading_calendar import get_krx_trading_days, reindex_to_krx_trading_days

try:
    from point_in_time_universe import load_security_master
except ImportError:  # 직접 스크립트 실행 시 chart 루트를 import path에 추가
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from point_in_time_universe import load_security_master

# 경로 설정
RAW_DATA_DIR = "./data/raw"
PROCESSED_DATA_DIR = "./data/processed"
SECURITY_MASTER_PATH = "./data/universe/security_master.parquet"
os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)


try:
    from ..serving.internal.features import (
        generate_full_alpha158_features as generate_full_alpha158_features,
    )
    from ..serving.internal.features import normalize_trading_halts as _normalize
except ImportError:
    from serving.internal.features import (
        generate_full_alpha158_features as generate_full_alpha158_features,
    )
    from serving.internal.features import normalize_trading_halts as _normalize


def normalize_trading_halts(df, trading_days=None, *, listing_date=None, delisting_date=None):
    start = pd.Timestamp(listing_date).normalize() if listing_date is not None else None
    end = (pd.Timestamp(delisting_date).normalize() - pd.Timedelta(1, unit="D")
           if delisting_date is not None and pd.notna(delisting_date) else None)
    indexed = reindex_to_krx_trading_days(df, trading_days, start_date=start, end_date=end)
    return _normalize(indexed, indexed.index)


def calculate_dynamic_triple_barrier(df, horizon=5, up_mult=1.5, down_mult=1.2):
    """
    [금융공학 표준] K-Market형 동적 트리플 배리어 타겟팅 (Dynamic Triple Barrier Method)

    매수 진입 시점의 최근 20일 일일 변동성(Sigma)에 기반하여 상/하방 배리어를 가변적으로 설정하고,
    미래 5영업일(Horizon) 동안의 주가 경로를 추적하여 최초로 터치한 배리어에 따라 라벨을 생성합니다.

    거래정지일 처리
    ---------------
    - Trading_Halt == 1인 날은 배리어 터치 체크를 건너뜁니다.
    - 시간 배리어(horizon) 카운터는 실제 거래가 있었던 날만 셉니다.
      즉, 보유 기간 중 N일 거래정지가 있으면 horizon이 N일만큼 뒤로 연장됩니다.
    """
    df = df.copy()

    # 1. 일일 로그 수익률 계산
    df["Log_Ret"] = np.log(df["Close"] / (df["Close"].shift(1) + 1e-8))
    # 거래정지일 Log_Ret → 0 (normalize_trading_halts에서 이미 처리됐지만 안전하게 재처리)
    if "Trading_Halt" in df.columns:
        df.loc[df["Trading_Halt"] == 1, "Log_Ret"] = 0.0

    # 2. 최근 20 실거래일 변동성(Sigma): 거래정지일 제외하고 계산
    # Trading_Halt 행을 NaN으로 마스킹 후 rolling → 정지일은 카운트에서 제외
    trading_log_ret = df["Log_Ret"].where(df.get("Trading_Halt", pd.Series(0, index=df.index)) == 0)
    df["Sigma"] = trading_log_ret.rolling(20, min_periods=10).std()

    # 3. 동적 배리어 설정
    df["Barrier_Up"] = df["Close"] * (1 + up_mult * df["Sigma"])
    df["Barrier_Down"] = df["Close"] * (1 - down_mult * df["Sigma"])

    df["Y_Label"] = 0

    hit_up_day = pd.Series(999, index=df.index)
    hit_down_day = pd.Series(999, index=df.index)

    halt_flag = df.get("Trading_Halt", pd.Series(0, index=df.index))

    # 4. 미래 5 실거래일 추적 (거래정지일 스킵 및 horizon 연장)
    trading_day_cumsum = (1 - halt_flag).cumsum()
    max_search_days = int(horizon * 2.5)

    for d in range(1, max_search_days + 1):
        future_high = df["High"].shift(-d)
        future_close = df["Close"].shift(-d)
        future_halt = halt_flag.shift(-d).fillna(1)  # 범위 밖은 정지로 처리

        # 미래 d 시점까지 경과한 실제 거래일 수 (NA 방어를 위해 999로 채움)
        passed_trading_days = (trading_day_cumsum.shift(-d) - trading_day_cumsum).fillna(999)

        # 실제 거래일 기준으로 horizon 이내이고, 해당 날짜가 거래정지가 아닐 때만 유효
        active = (future_halt == 0) & (passed_trading_days <= horizon)

        is_hit_up = active & (future_high >= df["Barrier_Up"])
        is_hit_down = active & (future_close <= df["Barrier_Down"])

        hit_up_day = np.where((is_hit_up) & (hit_up_day == 999), passed_trading_days, hit_up_day)
        hit_down_day = np.where(
            (is_hit_down) & (hit_down_day == 999), passed_trading_days, hit_down_day
        )

    # 5. 채점
    success_mask = (hit_up_day != 999) & (hit_up_day < hit_down_day)
    fail_mask = (hit_down_day != 999) & (hit_down_day <= hit_up_day)

    df.loc[success_mask, "Y_Label"] = 1
    df.loc[fail_mask, "Y_Label"] = -1

    # 6. 미래 데이터 참조 누수(Data Leakage) 차단
    if len(df) > horizon:
        df.loc[df.index[-horizon:], "Y_Label"] = np.nan

    return df


# 피처 계산에 필요한 최소 롤링 윈도우 크기 (ma_60, std_60 등 60일 기반 피처)
_LOOKBACK_DAYS = 65


def _load_trading_days_for_files(raw_files: list[str], master: pd.DataFrame | None = None) -> set:
    """원본 파일 전체 기간을 덮는 KRX 캘린더를 한 번만 조회합니다."""
    min_date = None
    max_date = None
    for file_path in raw_files:
        try:
            dates = pd.to_datetime(pd.read_parquet(file_path, columns=["Date"])["Date"])
        except Exception:
            continue
        if dates.empty:
            continue
        file_min = dates.min()
        file_max = dates.max()
        min_date = file_min if min_date is None else min(min_date, file_min)
        max_date = file_max if max_date is None else max(max_date, file_max)

    if min_date is None or max_date is None:
        return set()
    if master is not None:
        file_codes = {os.path.splitext(os.path.basename(path))[0].upper() for path in raw_files}
        known_delistings = master.loc[
            master["Code"].isin(file_codes) & master["DelistingDate"].notna(),
            "DelistingDate",
        ] - pd.Timedelta(1, unit="D")
        if not known_delistings.empty:
            max_date = max(max_date, min(known_delistings.max(), pd.Timestamp.now().normalize()))
    return get_krx_trading_days(
        min_date.strftime("%Y-%m-%d"), max_date.strftime("%Y-%m-%d")
    )


def _processed_has_current_market_data(file_path: str) -> bool:
    """processed 파일에 실제 VWAP과 PIT 구간 메타데이터가 있는지 확인합니다."""
    try:
        pd.read_parquet(
            file_path,
            columns=[
                "VWAP",
                "ListingDate",
                "DelistingDate",
                "UniverseSnapshotDate",
                "InUniverse",
            ],
        )
        return True
    except Exception:
        return False


def _preprocess_raw_frame(
    df_raw: pd.DataFrame, master: pd.DataFrame, trading_days: set
) -> pd.DataFrame:
    """코드의 각 비중첩 상장 구간을 독립적으로 전처리한다."""
    if df_raw.empty or "Code" not in df_raw.columns:
        raise ValueError("raw 데이터에 Code가 없습니다.")
    codes = df_raw["Code"].astype("string").str.zfill(6).dropna().unique()
    if len(codes) != 1:
        raise ValueError(f"종목별 raw 파일에는 Code 하나만 있어야 합니다: {codes.tolist()}")
    code = codes[0]
    intervals = master.loc[master["Code"].eq(code)].sort_values("ListingDate")
    if intervals.empty:
        raise ValueError(f"security master에 없는 종목입니다: {code}")

    df_raw = df_raw.copy()
    df_raw["Date"] = pd.to_datetime(df_raw["Date"]).dt.tz_localize(None).dt.normalize()
    processed = []
    for interval in intervals.itertuples(index=False):
        in_interval = df_raw["Date"].ge(interval.ListingDate) & (
            pd.isna(interval.DelistingDate) | df_raw["Date"].lt(interval.DelistingDate)
        )
        part = df_raw.loc[in_interval].copy()
        if part.empty:
            continue
        # 확정된 상폐일이 있는 종목은 마지막 체결 뒤 상폐 전까지를 거래정지로
        # 유지한다. 활성 종목은 수집된 마지막 거래일까지로 제한한다.
        part = normalize_trading_halts(
            part,
            trading_days,
            listing_date=max(interval.ListingDate, part["Date"].min()),
            delisting_date=interval.DelistingDate,
        )
        part = generate_full_alpha158_features(part)
        part = calculate_dynamic_triple_barrier(part)
        part["ListingDate"] = interval.ListingDate
        part["DelistingDate"] = interval.DelistingDate
        part["UniverseSnapshotDate"] = interval.SnapshotDate
        part["InUniverse"] = True
        part = part.dropna(subset=["roc_60", "Sigma"])
        processed.append(part)
    if not processed:
        return pd.DataFrame()
    return pd.concat(processed, ignore_index=True).sort_values("Date").reset_index(drop=True)


def preprocess_all_data():
    """
    [full 모드] 전체 전처리.
    processed 파일이 없는 종목만 raw → 피처 계산 → 저장.
    """
    master = load_security_master(SECURITY_MASTER_PATH)
    raw_files = glob.glob(os.path.join(RAW_DATA_DIR, "*.parquet"))
    master_codes = set(master["Code"])
    excluded_files = [
        path
        for path in raw_files
        if os.path.splitext(os.path.basename(path))[0].upper() not in master_codes
    ]
    raw_files = [path for path in raw_files if path not in excluded_files]
    print(
        f"PIT 주권 raw {len(raw_files)}개 전처리 "
        f"(master 밖 파일 {len(excluded_files)}개 제외)..."
    )
    trading_days = _load_trading_days_for_files(raw_files, master)
    failed = []

    for file_path in tqdm(raw_files, desc="데이터 전처리 중"):
        file_name = os.path.basename(file_path)
        save_path = os.path.join(PROCESSED_DATA_DIR, file_name)

        if os.path.exists(save_path) and _processed_has_current_market_data(save_path):
            continue

        try:
            df = pd.read_parquet(file_path)

            if len(df) < _LOOKBACK_DAYS:
                continue

            df = _preprocess_raw_frame(df, master, trading_days)
            if df.empty:
                continue

            df.to_parquet(save_path, index=False)

        except Exception as e:
            print(f"Error processing {file_name}: {e}")
            failed.append((file_name, str(e)))

    if failed:
        raise RuntimeError(f"PIT 전체 전처리 실패 {len(failed)}개: {failed[:5]}")
    print("✅ 전체 전처리 완료. (./data/processed/)")


def update_processed_data():
    """
    [update 모드] 증분 전처리.

    동작 원리
    ---------
    1. processed 파일의 마지막 날짜(last_date)를 확인한다.
    2. raw 파일에서 (last_date - LOOKBACK_DAYS) ~ 오늘 구간만 슬라이싱해서 읽는다.
       - LOOKBACK_DAYS(65일)를 앞에 붙이는 이유:
         rolling(60) 피처 계산에 최소 60일 이전 데이터가 있어야 오늘 행의 값이 정확히 계산됨.
    3. 피처·라벨 파이프라인 전체를 적용한다.
    4. last_date 이후 신규 행만 추출해서 기존 processed 파일 끝에 append한다.
    5. processed 파일이 없는 종목은 full 전처리로 폴백한다.
    """
    master = load_security_master(SECURITY_MASTER_PATH)
    raw_files = glob.glob(os.path.join(RAW_DATA_DIR, "*.parquet"))
    master_codes = set(master["Code"])
    raw_files = [
        path
        for path in raw_files
        if os.path.splitext(os.path.basename(path))[0].upper() in master_codes
    ]
    print(f"총 {len(raw_files)}개 PIT 주권 증분 전처리 시작...")
    trading_days = _load_trading_days_for_files(raw_files, master)

    updated, skipped, created = 0, 0, 0
    failed = []

    for file_path in tqdm(raw_files, desc="증분 전처리 중"):
        file_name = os.path.basename(file_path)
        save_path = os.path.join(PROCESSED_DATA_DIR, file_name)

        try:
            # ── processed 파일이 없으면 full 전처리로 폴백 ──────────────
            if not os.path.exists(save_path):
                df_raw = pd.read_parquet(file_path)
                if len(df_raw) < _LOOKBACK_DAYS:
                    skipped += 1
                    continue
                df_raw = _preprocess_raw_frame(df_raw, master, trading_days)
                if df_raw.empty:
                    skipped += 1
                    continue
                df_raw.to_parquet(save_path, index=False)
                created += 1
                continue

            # ── 기존 processed 파일의 마지막 날짜 확인 ──────────────────
            existing = pd.read_parquet(save_path)
            existing["Date"] = pd.to_datetime(existing["Date"])
            if not {
                "VWAP",
                "ListingDate",
                "DelistingDate",
                "UniverseSnapshotDate",
                "InUniverse",
            }.issubset(existing.columns):
                df_raw = pd.read_parquet(file_path)
                if len(df_raw) < _LOOKBACK_DAYS:
                    skipped += 1
                    continue
                df_raw = _preprocess_raw_frame(df_raw, master, trading_days)
                if df_raw.empty:
                    skipped += 1
                    continue
                df_raw.to_parquet(save_path, index=False)
                updated += 1
                continue
            last_date = existing["Date"].max()

            # ── raw에서 컨텍스트 포함 슬라이싱 ─────────────────────────
            df_raw = pd.read_parquet(file_path)
            df_raw["Date"] = pd.to_datetime(df_raw["Date"])

            context_start = last_date - pd.Timedelta(int(_LOOKBACK_DAYS * 2), unit="D")
            df_ctx = df_raw[df_raw["Date"] >= context_start].copy()

            if len(df_ctx) < _LOOKBACK_DAYS:
                skipped += 1
                continue

            # ── 피처·라벨 파이프라인 ────────────────────────────────────
            df_ctx = _preprocess_raw_frame(df_ctx, master, trading_days)

            # ── last_date 이후 신규 행만 추출 ───────────────────────────
            df_ctx["Date"] = pd.to_datetime(df_ctx["Date"])
            new_rows = df_ctx[df_ctx["Date"] > last_date]

            if new_rows.empty:
                skipped += 1
                continue

            # ── 기존 파일에 append 후 저장 ──────────────────────────────
            merged = pd.concat([existing, new_rows], ignore_index=True)
            merged = (
                merged.drop_duplicates(subset=["Date"], keep="last")
                .sort_values("Date")
                .reset_index(drop=True)
            )
            merged.to_parquet(save_path, index=False)
            updated += 1

        except Exception as e:
            print(f"Error updating {file_name}: {e}")
            failed.append((file_name, str(e)))

    print(
        f"\n✅ 증분 전처리 완료: 신규={updated}개, 신규생성={created}개, 스킵={skipped}개, 실패={len(failed)}개"
    )
    if failed:
        raise RuntimeError(f"PIT 증분 전처리 실패 {len(failed)}개: {failed[:5]}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="피처/라벨 전처리기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # [최초 구축] 파일이 없는 종목 전체 전처리
  python preprocess_data.py --mode full

  # [매일 자동화] 새로 수집된 하루치 데이터만 증분 처리
  python preprocess_data.py --mode update
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["full", "update"],
        default="update",
        help="full: 신규 종목 전체 전처리 | update: 증분 처리 (기본값)",
    )
    args = parser.parse_args()

    if args.mode == "full":
        print("[모드] 전체 전처리 (Full)")
        preprocess_all_data()
    else:
        print("[모드] 증분 업데이트 (Update)")
        update_processed_data()

import argparse
import glob
import hashlib
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from multiprocessing import cpu_count

import pandas as pd
import yaml
from tqdm import tqdm

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

# 각 워커 프로세스에서 재사용될 전역 모델 객체
_model = None


def resolve_model_path(profile, model_path=None, registry_path=None):
    """명시 경로 또는 registry의 profile에 해당하는 모델을 검증해 반환합니다."""
    if model_path:
        resolved = os.path.abspath(model_path)
        if not os.path.isfile(resolved):
            raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {resolved}")
        return resolved

    registry_path = registry_path or os.path.join(
        project_root, "core", "models", "registry.yaml"
    )
    with open(registry_path, encoding="utf-8") as file:
        registry = yaml.safe_load(file)

    try:
        entry = registry["models"][profile]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"registry에 profile이 없습니다: {profile}") from exc

    resolved = os.path.join(os.path.dirname(registry_path), entry["model_file"])
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {resolved}")

    expected_sha = entry.get("sha256")
    if expected_sha:
        with open(resolved, "rb") as file:
            actual_sha = hashlib.file_digest(file, "sha256").hexdigest()
        if actual_sha != expected_sha:
            raise ValueError(
                f"모델 SHA-256 불일치: expected={expected_sha}, actual={actual_sha}"
            )
    return resolved


def init_worker(model_path):
    """
    워커 프로세스가 생성될 때 단 1회 실행되어 단일 모델을 로드합니다.
    """
    global _model
    import lightgbm as lgb

    _model = lgb.Booster(model_file=model_path)


def process_ticker(file_path, target_date, threshold):
    """
    개별 종목의 과거 입력으로 serving의 공통 피처·추론을 수행합니다.
    """
    global _model
    ticker = os.path.basename(file_path).replace(".parquet", "")
    try:
        df = pd.read_parquet(file_path)
        if df.empty:
            return None

        df["Date"] = pd.to_datetime(df["Date"])

        # 피처 생성에 필요한 최근 85 영업일 분량만 슬라이스 (성능 최적화)
        if target_date:
            target_dt = pd.to_datetime(target_date)
            df_slice = df[df["Date"] <= target_dt].tail(85).copy()
            if df_slice.empty or df_slice["Date"].max() != target_dt:
                return None
        else:
            df_slice = df.tail(85).copy()

        if len(df_slice) < 65:
            return None

        from data_collectors.trading_calendar import get_krx_trading_days
        from serving.internal.features import build_feature_frame
        from serving.internal.inference import infer_batch

        days = get_krx_trading_days(
            df_slice.Date.min().strftime("%Y-%m-%d"), df_slice.Date.max().strftime("%Y-%m-%d"))
        features = build_feature_frame(df_slice, days)
        current = features.loc[features.Date.eq(df_slice.Date.max())]
        if len(current) != 1 or pd.isna(current.iloc[0].Sigma):
            return None
        model_score = infer_batch(_model, current)[0][0]["up"]
        last_row = df_slice.iloc[-1]

        return {
            "Code": ticker,
            "Name": last_row.get("Name", ticker),
            "Date": last_row["Date"].strftime("%Y-%m-%d"),
            "Close": last_row["Close"],
            "Volume": last_row["Volume"],
            "Change": last_row.get("Change", 0.0),
            "Model_Score": model_score,
            "Review_Flag": "REVIEW" if model_score >= threshold else "NORMAL",
        }
    except Exception:
        return None


def _unit_interval(value):
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("0.0 이상 1.0 이하 숫자여야 합니다") from exc
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("0.0 이상 1.0 이하 숫자여야 합니다")
    return parsed


def _positive_int(value):
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다")
    return parsed


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="전체 종목 대상 병렬 모델 스코어 및 재점검 표시 생성"
    )
    parser.add_argument(
        "--profile",
        choices=("aggressive", "stable"),
        default="aggressive",
        help="registry의 모델 profile (aggressive=H5, stable=H20)",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        default=None,
        help="모델 직접 지정. 생략하면 --profile에 따라 registry.yaml 사용",
    )
    parser.add_argument(
        "--target-date",
        type=str,
        default=None,
        help="예측 기준 영업일 (YYYY-MM-DD). 미지정 시 각 종목의 최신 영업일 기준.",
    )
    parser.add_argument(
        "--threshold",
        type=_unit_interval,
        default=0.5,
        help="사전 합의한 재점검 스코어 임계값 (0.0 ~ 1.0)",
    )
    parser.add_argument(
        "--top-n", type=_positive_int, default=30, help="터미널에 출력할 상위 종목 수"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=os.path.join(project_root, "experiments", "results"),
        help="추론 결과 저장 디렉토리",
    )
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=None,
        help="병렬 워커 수. 미지정 시 CPU 코어 수에 맞춰 동적 결정.",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    # 1. registry 또는 명시 경로에서 모델 확인
    model_path = resolve_model_path(args.profile, args.model_path)
    print(f"📦 모델 로드: {os.path.basename(model_path)} ({args.profile})")

    # 2. 데이터 파일 목록 수집
    raw_dir = os.path.join(project_root, "data", "raw")
    data_files = glob.glob(os.path.join(raw_dir, "*.parquet"))

    if not data_files:
        print(f"❌ [Error] 추론할 데이터 파일이 없습니다: {raw_dir}")
        return

    num_workers = args.workers if args.workers else max(1, cpu_count() - 1)
    print(f"📊 총 {len(data_files)}개 종목 추론 시작 (병렬 워커 수: {num_workers})...")

    results = []

    # 3. ProcessPoolExecutor로 병렬 추론 수행
    with ProcessPoolExecutor(
        max_workers=num_workers, initializer=init_worker, initargs=(model_path,)
    ) as executor:
        futures = [
            executor.submit(process_ticker, f, args.target_date, args.threshold) for f in data_files
        ]
        for fut in tqdm(futures, desc="병렬 추론 진행 중"):
            res = fut.result()
            if res is not None:
                results.append(res)

    if not results:
        print(
            "❌ [Error] 유효한 추론 결과가 없습니다. 데이터 수집 상태나 --target-date를 확인하세요."
        )
        return

    # 4. 결과 정렬 및 저장
    result_df = pd.DataFrame(results)
    result_df = result_df.sort_values(by="Model_Score", ascending=False).reset_index(drop=True)

    unique_dates = result_df["Date"].unique()
    file_date_suffix = (
        unique_dates[0].replace("-", "")
        if len(unique_dates) == 1
        else datetime.now().strftime("%Y%m%d")
    )
    output_file = os.path.join(args.output_dir, f"inference_result_{file_date_suffix}.csv")
    result_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\n💾 추론 결과 저장 완료: {output_file}")

    # 5. 상위 종목 출력
    display_date = unique_dates[0] if len(unique_dates) == 1 else "복수"
    print("\n" + "=" * 85)
    print(f"📊 class 2 모델 스코어 상위 {args.top_n}개 종목 (기준 영업일: {display_date})")
    print("=" * 85)
    print(
        f"{'순위':<4} | {'종목코드':<8} | {'종목명':<16} | {'기준일':<10} | "
        f"{'종가':<10} | {'전일대비':<8} | {'모델스코어':<12} | {'재점검':<6}"
    )
    print("-" * 85)

    for idx, row in result_df.head(args.top_n).iterrows():
        change_pct = f"{row['Change']:+.2f}%" if "Change" in row else "N/A"
        name_trunc = row["Name"][:12] if len(row["Name"]) <= 12 else row["Name"][:10] + ".."
        print(
            f"{idx + 1:<4} | {row['Code']:<8} | {name_trunc:<16} | "
            f"{row['Date']:<10} | {int(row['Close']):,d}원 | {change_pct:<8} | "
            f"{row['Model_Score']:.4f} | {row['Review_Flag']:<6}"
        )

    print("=" * 85)
    review_rows = result_df[result_df["Review_Flag"] == "REVIEW"]
    print(
        f"💡 총 {len(result_df)}개 중 재점검 대상: {len(review_rows)}개 "
        f"(임계: {args.threshold:.2f}, 매수·매도 지시가 아님)"
    )
    print("=" * 85)


if __name__ == "__main__":
    main()

import os

import pandas as pd
from tqdm import tqdm

DATA_DIR = "./data/raw"
TICKER_METADATA_PATH = "./data/ticker_metadata.csv"


def check_integrity():
    if not os.path.exists(TICKER_METADATA_PATH):
        print("ticker_metadata.csv가 없습니다. 먼저 생성해야 합니다.")
        return

    all_stocks = pd.read_csv(TICKER_METADATA_PATH)
    all_stocks["Code"] = all_stocks["Code"].astype(str).str.zfill(6)

    print(f"총 {len(all_stocks)}개 종목 검사 시작...")

    missing_files = []
    not_uptodate = []
    has_gaps = []

    # 한국 영업일 기준일 (2026-06-12)
    target_date = pd.to_datetime("2026-06-12")

    # 영업일 캘린더 생성 (최근 1개월 기준)
    start_check_date = pd.to_datetime("2026-05-01")
    full_business_days = pd.date_range(start=start_check_date, end=target_date, freq="B")

    # 실제 개장일 필터링을 위해 삼성전자(005930)의 실제 영업일 날짜들을 기준으로 삼음
    samsung_path = os.path.join(DATA_DIR, "005930.parquet")
    if os.path.exists(samsung_path):
        samsung_df = pd.read_parquet(samsung_path)
        samsung_df["Date"] = pd.to_datetime(samsung_df["Date"])
        actual_business_days = set(
            samsung_df[
                (samsung_df["Date"] >= start_check_date) & (samsung_df["Date"] <= target_date)
            ]["Date"].dt.date
        )
    else:
        actual_business_days = set(full_business_days.date)

    print(f"검사 대상 영업일 수 (2026-05-01 ~ 2026-06-12): {len(actual_business_days)}일")

    for _, row in tqdm(all_stocks.iterrows(), total=len(all_stocks)):
        code = row["Code"]
        name = row["Name"]
        is_delisted = row["IsDelisted"]

        file_path = os.path.join(DATA_DIR, f"{code}.parquet")

        if not os.path.exists(file_path):
            if not is_delisted:
                missing_files.append((code, name))
            continue

        try:
            df = pd.read_parquet(file_path)
            if df.empty:
                if not is_delisted:
                    missing_files.append((code, name))
                continue

            df["Date"] = pd.to_datetime(df["Date"])
            last_date = df["Date"].max()

            # 활성 종목인데 최신일(2026-06-12)이 아니면 체크
            if not is_delisted and last_date < target_date:
                not_uptodate.append((code, name, last_date.strftime("%Y-%m-%d")))

            # 최근 1개월(2026-05-01 이후) 내 중간 누락 영업일이 있는지 체크 (상장폐지 종목 제외)
            if not is_delisted:
                recent_df = df[df["Date"] >= start_check_date]
                existing_dates = set(recent_df["Date"].dt.date)

                # 상장일이 2026-05-01 이후인 신규 상장 종목 고려 (최초 Date 이후만 비교)
                first_date = df["Date"].min()
                if first_date > start_check_date:
                    check_days = {d for d in actual_business_days if d >= first_date.date()}
                else:
                    check_days = actual_business_days

                missing_days = check_days - existing_dates
                if missing_days:
                    has_gaps.append((code, name, sorted(list(missing_days))))

        except Exception as e:
            print(f"에러 발생 [{code}]: {e}")

    print("\n=== 검증 결과 ===")
    print(f"1. 파일 누락 (활성 종목): {len(missing_files)}개")
    for c, n in missing_files[:10]:
        print(f"   - {c}: {n}")
    if len(missing_files) > 10:
        print(f"   ...외 {len(missing_files) - 10}개")

    print(f"\n2. 최신일(2026-06-12) 미달성 (활성 종목): {len(not_uptodate)}개")
    for c, n, ld in not_uptodate[:10]:
        print(f"   - {c}: {n} (최종일: {ld})")
    if len(not_uptodate) > 10:
        print(f"   ...외 {len(not_uptodate) - 10}개")

    print(f"\n3. 최근 1개월 내 중간 누락(Gap) 존재 (활성 종목): {len(has_gaps)}개")
    for c, n, gaps in has_gaps[:10]:
        gap_strs = [g.strftime("%Y-%m-%d") for g in gaps[:3]]
        print(f"   - {c}: {n} (누락: {gap_strs} 등 {len(gaps)}일)")
    if len(has_gaps) > 10:
        print(f"   ...외 {len(has_gaps) - 10}개")


if __name__ == "__main__":
    check_integrity()

"""화면 '예상 범위'의 기준선 적중률을 재학습 없이 계산한다(기준은 docs/research/model-improvement-plan.md 2절).

범위 = 등급(argmax) × 종목 변동성 5분위 칸마다, 그 달 1일 전에 이미 실현된 수익률의 10%, 50%, 90% 분위수.
하방 경고 = 같은 날 하방 반편차 상위 20%.

    python -m experiments.e0_range --oos-dir <dir> --prices <prices.parquet> --out <dir>
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

GRADES = np.array(["down", "neutral", "up"])
WINDOW = 60  # 거래일. 변동성과 반편차 모두
MIN_CELL = 200  # 칸의 과거 표본이 이보다 적으면 범위를 내지 않는다


def trailing_risk(prices, window=WINDOW):
    """t까지의 일간 수익률로 변동성(표준편차)과 하방 반편차 sqrt(mean(min(r, 0)²))."""
    prices = prices.sort_values(["Code", "Date"])
    r = prices.groupby("Code").Close.pct_change()
    grouped = r.groupby(prices.Code)
    vol = grouped.transform(lambda s: s.rolling(window, min_periods=window).std())
    semi = np.sqrt((r.clip(upper=0) ** 2).groupby(prices.Code).transform(
        lambda s: s.rolling(window, min_periods=window).mean()))
    return prices[["Date", "Code"]].assign(vol=vol, semi=semi)


def add_cells(frame, risk, warn_top=0.2):
    frame = frame.merge(risk, on=["Date", "Code"], how="inner").dropna(subset=["vol", "semi"])
    by_day = frame.groupby("Date")
    return frame.assign(
        grade=GRADES[frame[["prob_down", "prob_neutral", "prob_up"]].to_numpy().argmax(1)],
        vol_q=(by_day.vol.rank(pct=True, method="first") * 5).apply(np.ceil).clip(1, 5).astype(int),
        warn=by_day.semi.rank(pct=True, method="first") > 1 - warn_top)


def monthly_ranges(frame, min_cell=MIN_CELL):
    """달마다, 그 달 1일 전에 return_date가 지난 행만으로 칸별 분위수를 정해 그 달 행에 붙인다."""
    out = []
    for month, part in frame.groupby(frame.Date.dt.to_period("M")):
        past = frame.loc[frame.return_date < month.start_time].groupby(["grade", "vol_q"]).forward_return
        if not past.ngroups:
            continue
        q = past.quantile([0.1, 0.5, 0.9]).unstack().set_axis(["q10", "q50", "q90"], axis=1)
        q = q.loc[past.size() >= min_cell]
        out.append(part.merge(q, left_on=["grade", "vol_q"], right_index=True, how="inner"))
    ranged = pd.concat(out)
    return ranged.assign(inside=ranged.forward_return.between(ranged.q10, ranged.q90),
                         below=ranged.forward_return < ranged.q10)


def summarize(ranged, horizon):
    year = ranged.Date.dt.year
    yearly = ranged.groupby(year).agg(rows=("inside", "size"), coverage=("inside", "mean"),
                                      below=("below", "mean")).reset_index(names="year")
    total = {"year": "all", "rows": len(ranged), "coverage": ranged.inside.mean(), "below": ranged.below.mean()}
    yearly = pd.concat([pd.DataFrame([total]), yearly]).assign(horizon=horizon)
    up = ranged.loc[ranged.grade.eq("up")]
    warning = {"horizon": horizon, "up_rows": len(up), "warn_share": up.warn.mean(),
               "below_warn": up.loc[up.warn].below.mean(), "below_rest": up.loc[~up.warn].below.mean(),
               "warn_higher_years": int((up.groupby([up.Date.dt.year, "warn"]).below.mean().unstack()
                                         .pipe(lambda t: t[True] > t[False])).sum())}
    return yearly, warning


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--oos-dir", type=Path, required=True)
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    prices = pd.read_parquet(args.prices).assign(Date=lambda f: pd.to_datetime(f.Date), Code=lambda f: f.Code.astype(str))
    risk = trailing_risk(prices)
    tables, warnings = [], []
    for h in (5, 20):
        frame = pd.read_parquet(args.oos_dir / f"h{h}_A.parquet").assign(Code=lambda f: f.Code.astype(str))
        ranged = monthly_ranges(add_cells(frame.loc[frame.return_observed], risk))
        yearly, warning = summarize(ranged, h)
        tables.append(yearly)
        warnings.append(warning)
    pd.concat(tables).to_csv(args.out / "range_coverage.csv", index=False)
    pd.DataFrame(warnings).to_csv(args.out / "range_warning.csv", index=False)
    print(pd.concat(tables).round(4).to_string(), json.dumps(warnings, default=float, indent=1))


if __name__ == "__main__":
    main()

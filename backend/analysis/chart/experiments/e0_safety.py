"""기준선의 신뢰도(확률 보정)와 쓸모(비용 반영 상위 10% 초과수익)를 재학습 없이 계산한다.

판정 규칙은 docs/research/model-improvement-plan.md에 결과 전에 고정했다. 입력은 e0_baseline과 같은
Release OOS(h5_A, h20_A)와, 투자 가능 집단을 거를 일별 가격(Date, Code, Close, Volume)과 종목명(Code, Name)이다.

    python -m experiments.e0_safety --oos-dir <dir> --prices <prices.parquet> --names <names.parquet> --out <dir>
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from experiments.evaluation.metrics import daily_rank_ic, summarize_daily_ic
from sklearn.isotonic import IsotonicRegression

ROUND_TRIP_COST = 0.003  # 거래세 0.20% + 수수료와 슬리피지 0.10%
GRADES = ("down", "neutral", "up")  # 화면과 같은 argmax 방향


# ---- 신뢰도 ----

def calibration_curve(y, p, bins=10):
    """예측 확률 순서로 같은 행 수 bins개 구간을 나눠 평균 예측과 실제 비율을 낸다."""
    frame = pd.DataFrame({"y": np.asarray(y, float), "p": np.asarray(p, float)})
    frame["bin"] = pd.qcut(frame.p.rank(method="first"), bins, labels=False)
    return frame.groupby("bin").agg(n=("y", "size"), predicted=("p", "mean"), actual=("y", "mean"))


def expected_calibration_error(curve):
    return float((curve.n * (curve.predicted - curve.actual).abs()).sum() / curve.n.sum())


def brier(y, p):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def isotonic_from_prior_years(year, p, y):
    """각 해의 확률을 그 앞 모든 해의 OOS 예측으로 맞춘 isotonic으로 바꾼다. 첫해는 NaN(앞 해 없음)."""
    year, p, y = map(np.asarray, (year, p, y))
    out = np.full(len(p), np.nan)
    for current in np.unique(year)[1:]:
        prior = year < current
        model = IsotonicRegression(out_of_bounds="clip").fit(p[prior], y[prior])
        out[year == current] = model.predict(p[year == current])
    return out


def grade_rise_rates(frame, *, n_boot=1000, seed=0, confidence=0.95):
    """등급(argmax)별 실제로 오른(forward_return > 0) 비율과 날짜 묶음 부트스트랩 신뢰구간."""
    frame = frame.assign(rise=frame.forward_return > 0)
    per_day = frame.groupby(["grade", "Date"]).rise.agg(["sum", "size"]).unstack("grade", fill_value=0)
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(per_day), size=(n_boot, len(per_day)))
    tail = (1 - confidence) / 2
    rows = []
    for grade in GRADES:
        if ("size", grade) not in per_day or per_day["size", grade].sum() == 0:
            continue
        hits, sizes = per_day["sum", grade].to_numpy(), per_day["size", grade].to_numpy()
        with np.errstate(invalid="ignore"):
            boot = hits[picks].sum(axis=1) / sizes[picks].sum(axis=1)
        rows.append({"grade": grade, "n": int(sizes.sum()), "rise_rate": hits.sum() / sizes.sum(),
                     "ci_low": float(np.nanquantile(boot, tail)), "ci_high": float(np.nanquantile(boot, 1 - tail))})
    return pd.DataFrame(rows)


# ---- 쓸모 ----

def investable(frame, prices, names, *, liquidity_days=20, low_cut=0.2):
    """보통주만, 스팩, 리츠, ETF 제외, 날짜별 20거래일 평균 거래대금 하위 low_cut 제외. 가격이 없는 행도 뺀다."""
    name = frame.Code.map(names.drop_duplicates("Code").set_index("Code").Name).fillna("")
    common = frame.Code.str[-1].eq("0") & ~name.str.contains("스팩|리츠$|ETF|ETN")  # "리츠$": 메리츠 같은 이름은 남긴다
    amount = (prices.assign(amount=prices.Close * prices.Volume).sort_values(["Code", "Date"])
              .assign(amount=lambda f: f.groupby("Code").amount.transform(
                  lambda s: s.rolling(liquidity_days, min_periods=liquidity_days).mean())))
    kept = frame.loc[common].merge(amount[["Date", "Code", "amount"]], on=["Date", "Code"], how="left")
    kept = kept.dropna(subset=["amount"])
    pct = kept.groupby("Date").amount.rank(pct=True, method="first")
    return kept.loc[pct > low_cut].drop(columns="amount")


def top_excess(frame, score, horizon, *, quantile=0.1, cost=ROUND_TRIP_COST):
    """겹치지 않게 horizon 거래일마다 점수 상위 quantile을 동일가중으로 사고, 같은 날 집단 평균과의 차이를 잰다.

    비용 = 바뀐 종목 비율(회전율) × 왕복 비용. 첫 기간 회전율은 1이다.
    """
    frame = frame[["Date", "Code", score, "forward_return"]].dropna()
    dates = np.sort(frame.Date.unique())[::horizon]
    by_date = dict(tuple(frame.loc[frame.Date.isin(dates)].groupby("Date")))
    held, rows = set(), []
    for date in dates:
        day = by_date[date]
        top = day.loc[day[score].rank(pct=True, method="first") > 1 - quantile]
        codes = set(top.Code)
        turnover = 1 - len(codes & held) / len(codes)
        gross = top.forward_return.mean() - day.forward_return.mean()
        rows.append({"Date": date, "n": len(day), "top_n": len(top), "turnover": turnover,
                     "gross_excess": gross, "net_excess": gross - turnover * cost})
        held = codes
    return pd.DataFrame(rows)


def by_year(periods):
    periods = periods.assign(year=pd.DatetimeIndex(periods.Date).year)
    yearly = periods.groupby("year").agg(periods=("net_excess", "size"), gross_mean=("gross_excess", "mean"),
                                         net_mean=("net_excess", "mean"), turnover=("turnover", "mean"),
                                         positive_periods=("net_excess", lambda s: float((s > 0).mean())))
    return yearly.reset_index()


# ---- 실행 ----

def evaluate(frame, horizon, prices, names):
    frame = frame.assign(year=frame.Date.dt.year,
                         grade=np.array(GRADES)[frame[["prob_down", "prob_neutral", "prob_up"]].to_numpy().argmax(1)])
    labeled = frame.loc[frame.label_observed].copy()
    labeled["y_up"] = labeled.Y_Label.eq(2).astype(float)
    labeled["p_cal"] = isotonic_from_prior_years(labeled.year, labeled.prob_up, labeled.y_up)
    later = labeled.dropna(subset=["p_cal"])
    # 앞 해 실제 상승 비율 하나만 쓰는 기준(정보 없는 예측)
    base_rate = labeled.groupby("year").y_up.mean().shift(1)
    climatology = later.year.map(base_rate)
    reliability = {"horizon": horizon, "up_rate": float(labeled.y_up.mean()),
                   "brier_raw_all": brier(labeled.y_up, labeled.prob_up),
                   "ece_raw_all": expected_calibration_error(calibration_curve(labeled.y_up, labeled.prob_up)),
                   "brier_raw_2020": brier(later.y_up, later.prob_up),
                   "brier_cal_2020": brier(later.y_up, later.p_cal),
                   "brier_climatology_2020": brier(later.y_up, climatology),
                   "ece_raw_2020": expected_calibration_error(calibration_curve(later.y_up, later.prob_up)),
                   "ece_cal_2020": expected_calibration_error(calibration_curve(later.y_up, later.p_cal))}
    curves = pd.concat([calibration_curve(later.y_up, later[col]).assign(horizon=horizon, score=col)
                        for col in ("prob_up", "p_cal")]).reset_index()

    returns = frame.loc[frame.return_observed]
    grades = pd.concat([grade_rise_rates(part).assign(year=year)
                        for year, part in [("all", returns), *returns.groupby("year")]]).assign(horizon=horizon)

    universe = investable(returns, prices, names)
    periods = top_excess(universe, "prob_up", horizon)
    yearly = by_year(periods).assign(horizon=horizon)
    ic = summarize_daily_ic(daily_rank_ic(universe, "prob_up", "forward_return"))
    usefulness = {"horizon": horizon, "rows": len(returns), "investable_rows": len(universe),
                  "investable_ic": ic["ic_mean"], "investable_icir": ic["icir"],
                  "periods": len(periods), "gross_mean": float(periods.gross_excess.mean()),
                  "net_mean": float(periods.net_excess.mean()), "turnover": float(periods.turnover.mean()),
                  "positive_years": int((yearly.net_mean > 0).sum()), "years": len(yearly)}
    ordered = grades.loc[grades.year.ne("all")].pivot(index="year", columns="grade", values="rise_rate").reindex(columns=GRADES)
    usefulness["grade_order_years"] = int(((ordered.up > ordered.neutral) & (ordered.neutral > ordered.down)).sum())
    return reliability, curves, grades, yearly, usefulness


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--oos-dir", type=Path, required=True)
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--names", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    prices = pd.read_parquet(args.prices).assign(Date=lambda f: pd.to_datetime(f.Date), Code=lambda f: f.Code.astype(str))
    names = pd.read_parquet(args.names).assign(Code=lambda f: f.Code.astype(str))
    results = [evaluate(pd.read_parquet(args.oos_dir / f"h{h}_A.parquet").assign(Code=lambda f: f.Code.astype(str)),
                        h, prices, names) for h in (5, 20)]
    reliability, curves, grades, yearly, usefulness = zip(*results)
    pd.DataFrame(reliability).to_csv(args.out / "safety_reliability.csv", index=False)
    pd.concat(curves).to_csv(args.out / "safety_calibration_curve.csv", index=False)
    pd.concat(grades).to_csv(args.out / "safety_grade_rise.csv", index=False)
    pd.concat(yearly).to_csv(args.out / "safety_usefulness_by_year.csv", index=False)
    pd.DataFrame(usefulness).to_csv(args.out / "safety_usefulness.csv", index=False)
    print(json.dumps({"reliability": reliability, "usefulness": usefulness}, default=float, indent=1))


if __name__ == "__main__":
    main()

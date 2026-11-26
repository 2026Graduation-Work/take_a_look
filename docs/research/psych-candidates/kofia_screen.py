"""P1 1차 선별: 금융투자협회 신용융자, 투자자예탁금 × 종목 특성(재학습 없음, 연구용).

시장 값은 같은 날 모든 종목에 같으므로 그대로는 날짜별 순위를 바꾸지 못한다. 그래서 날짜별 "종목 특성의 IC"가
시장 심리 z에 따라 달라지는지(기울기)와, z의 부호로 특성 방향을 뒤집은 상호작용 IC를 본다(screen.py P2와 같은 방식).

입력: <kofia>/raw/*.json(공공데이터포털 GetKofiaStatisticsInfoService 원본 items), <plan> 폴더의 prices.parquet,
names.parquet, oos/h{5,20}_A.parquet, KOSPI 지수 종가 parquet(Date, Close).

    PYTHONPATH=backend/analysis/chart python docs/research/psych-candidates/kofia_screen.py <kofia> <plan> <KS11.parquet> <out>
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from experiments.e0_safety import investable
from experiments.evaluation.metrics import compare_daily_ic, daily_rank_ic
from experiments.features.psychology.market_psychology import build_psychology_features

KOFIA, PLAN, KOSPI, OUT = map(Path, sys.argv[1:5])
DISC_END = pd.Timestamp("2023-12-31")
LAG = 2  # 금투협 통계는 기준일 하루 이틀 뒤 공개된다. 2거래일 전 값만 쓴다


def kofia_signals(kospi):
    credit = pd.DataFrame(json.load(open(KOFIA / "raw/getGrantingOfCreditBalanceInfo.json")))
    capital = pd.DataFrame(json.load(open(KOFIA / "raw/getSecuritiesMarketTotalCapitalInfo.json")))
    frame = (credit[["basDt", "crdTrFingScrs"]].merge(capital[["basDt", "invrDpsgAmt"]], on="basDt", how="outer")
             .assign(Date=lambda f: pd.to_datetime(f.basDt)).set_index("Date").sort_index().drop(columns="basDt")
             .astype(float))
    index = kospi.reindex(frame.index).ffill()
    raw = pd.DataFrame({
        # shortcut: 시가총액 대신 KOSPI 지수로 나눈 근사. 상장 주식 수 변화는 반영 못 한다
        "credit_to_mcap": frame.crdTrFingScrs / index,
        "deposit_chg20": frame.invrDpsgAmt.pct_change(20, fill_method=None),
        "credit_chg20": frame.crdTrFingScrs.pct_change(20, fill_method=None),
    })
    z = (raw - raw.rolling(250, min_periods=120).mean().shift(1)) / raw.rolling(250, min_periods=120).std().shift(1)
    return z.shift(LAG)


def slope_t(ic, x, n_boot=2000, seed=0):
    """날짜별 IC를 시장 z로 회귀한 기울기와 월 블록 부트스트랩 t."""
    df = pd.DataFrame({"y": ic, "x": x}).dropna()
    arr = (df.assign(n=1.0, xy=df.x * df.y, xx=df.x ** 2)
           .groupby(pd.DatetimeIndex(df.index).to_period("M"))[["n", "x", "y", "xy", "xx"]].sum().to_numpy())

    def slope(t):
        n, sx, sy, sxy, sxx = (t[..., i] for i in range(5))
        return (sxy - sx * sy / n) / (sxx - sx ** 2 / n)

    boot = slope(arr[np.random.default_rng(seed).integers(0, len(arr), (n_boot, len(arr)))].sum(1))
    observed = float(slope(arr.sum(0)))
    return observed, observed / boot.std(ddof=1), len(df)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    kospi = pd.read_parquet(KOSPI).assign(Date=lambda f: pd.to_datetime(f.Date)).set_index("Date").Close
    signals = kofia_signals(kospi)
    prices = pd.read_parquet(PLAN / "prices.parquet").assign(Date=lambda f: pd.to_datetime(f.Date))
    names = pd.read_parquet(PLAN / "names.parquet")
    prices = prices.sort_values(["Code", "Date"])
    lr = np.log(prices.Close / prices.groupby("Code").Close.shift(1))
    prices["vol60"] = lr.groupby(prices.Code).transform(lambda s: s.rolling(60, min_periods=60).std())
    # 개인 순매수 자료가 없어, 거래량이 실린 날의 방향 쏠림(psych_herding, A/B 때 정의)을 대리 지표로 쓴다
    ids = {c: f"{i:06d}" for i, c in enumerate(sorted(prices.Code.unique()))}
    psych, _ = build_psychology_features(prices[["Date", "Code", "Close", "Volume"]].assign(Code=prices.Code.map(ids)))
    psych = (psych.assign(Code=psych.Code.map({v: k for k, v in ids.items()}))
             .drop(columns="Date").rename(columns={"AvailableDate": "Date"})[["Date", "Code", "psych_herding"]])
    traits = prices[["Date", "Code", "vol60"]].merge(psych, on=["Date", "Code"], how="left")

    rows = []
    for h in (5, 20):
        oos = pd.read_parquet(PLAN / f"oos/h{h}_A.parquet", columns=["Date", "Code", "forward_return", "return_observed"])
        oos = investable(oos.loc[oos.return_observed].assign(Code=lambda f: f.Code.astype(str)), prices, names)
        panel = oos.merge(traits, on=["Date", "Code"], how="left")
        for trait in ("vol60", "psych_herding"):
            ic = daily_rank_ic(panel.dropna(subset=[trait]), trait, "forward_return")
            for signal in signals:
                z = signals[signal].reindex(ic.index)
                for window, mask in (("disc", ic.index <= DISC_END), ("conf", ic.index > DISC_END)):
                    part, zpart = ic[mask], z[mask]
                    keep = zpart.notna()
                    slope, t, days = slope_t(part[keep], zpart[keep])
                    # 상호작용 z × 특성 순위의 날짜별 IC = sign(z) × 특성 IC
                    inter = (np.sign(zpart[keep]) * part[keep])
                    test = compare_daily_ic(pd.Series(0.0, index=inter.index), inter)
                    rows.append({"horizon": h, "trait": trait, "signal": signal, "window": window, "days": days,
                                 "first_day": part[keep].index.min().date(), "slope": slope, "slope_t": t,
                                 "inter_ic": test["diff_mean"], "inter_t": test["t_stat"]})
    result = pd.DataFrame(rows)
    wide = result.pivot_table(index=["horizon", "trait", "signal"], columns="window", values=["slope", "slope_t"])
    same = np.sign(wide["slope"]["disc"]) == np.sign(wide["slope"]["conf"])
    strong = wide["slope_t"]["disc"].abs() >= 2
    verdict = np.where(same & strong, "유망", np.where(same, "약함", "탈락")).tolist()
    result.to_csv(OUT / "kofia_screen.csv", index=False)
    summary = wide.round(4)
    summary.columns = [f"{a}_{b}" for a, b in summary.columns]
    summary.assign(verdict=verdict).reset_index().to_csv(OUT / "kofia_verdict.csv", index=False)
    print(result.round(4).to_string())
    print(summary.assign(verdict=verdict).to_string())


if __name__ == "__main__":
    main()

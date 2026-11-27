"""1차 선별: 심리지표 후보 2~5를 재학습 없이 검정한다(연구용, 레포 밖).

입력: Drive Chart/raw 가격(FDR, 2010~2026-06), Release A 표본 밖 예측(h5_A, h20_A), KOSPI 종가.
기간: 2019~2025 표본 밖 날짜. 발견 구간 2019~2023에서 고르고 확인 구간 2024~2025에서 검정한다.

    PYTHONPATH=<wt>/backend/analysis/chart python screen.py <psy 폴더> <KOSPI.parquet>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from experiments.evaluation.metrics import compare_daily_ic
from experiments.features.psychology.market_psychology import (
    RAW_FEATURES,
    build_psychology_features,
)

ROOT, KOSPI = Path(sys.argv[1]), Path(sys.argv[2])
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)
DISC_END = pd.Timestamp("2023-12-31")
HORIZONS = (1, 2, 5, 10, 20, 60)
CONTROLS = ["ret5", "ret20", "vol20", "amt20"]


def load_prices():
    frames = []
    for path in sorted((ROOT / "raw").glob("*.parquet")):
        frame = pd.read_parquet(path, columns=["Date", "Close", "Volume"])
        frame["Code"] = path.stem
        frames.append(frame)
    px = pd.concat(frames, ignore_index=True)
    px["Date"] = pd.to_datetime(px.Date).dt.normalize()
    px["Volume"] = pd.to_numeric(px.Volume, errors="coerce").fillna(0)
    px = px.loc[px.Date.ge("2015-01-01") & px.Close.gt(0)]
    return px.drop_duplicates(["Code", "Date"], keep="last").sort_values(["Code", "Date"]).reset_index(drop=True)


def add_price_columns(px):
    g = px.groupby("Code", sort=False)
    px["lr"] = np.log(px.Close / g.Close.shift(1))
    lr = px.groupby("Code", sort=False).lr
    px["ret5"] = px.Close / g.Close.shift(5) - 1
    px["ret20"] = px.Close / g.Close.shift(20) - 1
    px["vol20"] = lr.transform(lambda s: s.rolling(20, min_periods=20).std())
    px["vol60"] = lr.transform(lambda s: s.rolling(60, min_periods=60).std())
    amount = px.Close * px.Volume
    px["amt20"] = np.log1p(amount.groupby(px.Code).transform(lambda s: s.rolling(20, min_periods=20).mean()))
    for h in HORIZONS:
        px[f"fwd{h}"] = g.Close.shift(-h) / px.Close - 1
    # 다음 20거래일 실현 변동성: t+1..t+20 일간 로그수익률의 표준편차
    px["fvol20"] = lr.transform(lambda s: s.rolling(20, min_periods=20).std().shift(-20))
    px["amount"] = amount
    return px


def daily_ic(frame, x, y, min_names=20):
    d = frame[["Date", x, y]].dropna()
    rx, ry = d.groupby("Date")[x].rank(), d.groupby("Date")[y].rank()
    rx = rx - rx.groupby(d.Date).transform("mean")
    ry = ry - ry.groupby(d.Date).transform("mean")
    num = (rx * ry).groupby(d.Date).sum()
    den = np.sqrt((rx**2).groupby(d.Date).sum() * (ry**2).groupby(d.Date).sum())
    size = d.groupby("Date").size()
    ic = (num / den).where(size >= min_names)
    return ic.replace([np.inf, -np.inf], np.nan).dropna()


def stat(ic):
    """IC 평균과 월 블록 부트스트랩 t. 구간별로 따로 낸다."""
    out = {}
    for name, part in (("all", ic), ("disc", ic[ic.index <= DISC_END]), ("conf", ic[ic.index > DISC_END])):
        result = compare_daily_ic(pd.Series(0.0, index=part.index), part)
        out[f"{name}_ic"], out[f"{name}_t"] = result["diff_mean"], result["t_stat"]
    return out


def residualize(frame, column):
    """같은 날 통제 변수 순위로 회귀한 잔차(기존 가격 정보와 겹치는 부분을 뺀 값)."""
    cols = [column, *CONTROLS]
    d = frame[["Date", *cols]].dropna()
    ranks = d.groupby("Date")[cols].rank(pct=True)
    resid = pd.Series(np.nan, index=d.index)
    for _, idx in ranks.groupby(d.Date).groups.items():
        block = ranks.loc[idx]
        if len(block) < 20:
            continue
        design = np.column_stack([np.ones(len(block)), block[CONTROLS].to_numpy()])
        coef, *_ = np.linalg.lstsq(design, block[column].to_numpy(), rcond=None)
        resid.loc[idx] = block[column].to_numpy() - design @ coef
    return resid.reindex(frame.index)


def month_sums(ic, groups):
    df = pd.DataFrame({"ic": ic, "g": groups}).dropna()
    df["m"] = pd.DatetimeIndex(df.index).to_period("M")
    table = df.pivot_table(index="m", columns="g", values="ic", aggfunc=["sum", "count"]).fillna(0)
    return df, table


def regime_diff(ic, regime, n_boot=2000, seed=0):
    """시장 국면 3분위(전체 기간 분위수, 서술용)별 모델 IC와 상위-하위 차이의 월 블록 부트스트랩 t."""
    reg = regime.reindex(ic.index)
    cuts = reg.quantile([1 / 3, 2 / 3]).to_numpy()
    groups = pd.Series(np.where(reg <= cuts[0], "low", np.where(reg > cuts[1], "high", "mid")), index=ic.index)
    groups[reg.isna()] = np.nan
    df, table = month_sums(ic, groups)
    s, c = table["sum"], table["count"]
    observed = {g: df.loc[df.g == g, "ic"].mean() for g in ("low", "mid", "high")}
    picks = np.random.default_rng(seed).integers(0, len(table), size=(n_boot, len(table)))
    boot = (s["high"].to_numpy()[picks].sum(1) / c["high"].to_numpy()[picks].sum(1)
            - s["low"].to_numpy()[picks].sum(1) / c["low"].to_numpy()[picks].sum(1))
    diff = observed["high"] - observed["low"]
    return {**{f"ic_{k}": v for k, v in observed.items()}, "high_minus_low": diff, "t": diff / boot.std(ddof=1)}


def slope_test(y, x, n_boot=2000, seed=0):
    """날짜별 y(특성의 IC)를 x(시장 심리)로 회귀한 기울기와 월 블록 부트스트랩 t."""
    df = pd.DataFrame({"y": y, "x": x}).dropna()
    months = pd.DatetimeIndex(df.index).to_period("M")
    arr = df.assign(n=1.0, xy=df.x * df.y, xx=df.x**2).groupby(months)[["n", "x", "y", "xy", "xx"]].sum().to_numpy()

    def slope(t):
        n, sx, sy, sxy, sxx = (t[..., i] for i in range(5))
        return (sxy - sx * sy / n) / (sxx - sx**2 / n)

    observed = slope(arr.sum(0))
    picks = np.random.default_rng(seed).integers(0, len(arr), size=(n_boot, len(arr)))
    boot = slope(arr[picks].sum(1))
    return {"slope": float(observed), "t": float(observed / boot.std(ddof=1)), "months": len(arr)}


def causal_z(series, window=250):
    mean = series.rolling(window, min_periods=120).mean().shift(1)
    std = series.rolling(window, min_periods=120).std().shift(1)
    return (series - mean) / std


def combine_test(frame, base_ic, signal_col, target, lambdas=(0.05, 0.1, 0.2, 0.3, 0.5, 1.0)):
    """모델 점수 순위 + λ×신호 순위. 발견 구간에서 λ를 고르고 확인 구간에서 IC 차이를 검정한다."""
    d = frame[["Date", "prob_up", signal_col, target]].dropna().copy()
    d["rs"] = d.groupby("Date").prob_up.rank(pct=True)
    d["rx"] = d.groupby("Date")[signal_col].rank(pct=True) if signal_col != "bw" else d[signal_col]
    best, best_lam = -np.inf, None
    for sign in (1, -1):
        for lam in lambdas:
            d["comb"] = d.rs + sign * lam * d.rx
            ic = daily_ic(d.loc[d.Date <= DISC_END], "comb", target)
            if ic.mean() > best:
                best, best_lam = ic.mean(), sign * lam
    d["comb"] = d.rs + best_lam * d.rx
    conf = d.loc[d.Date > DISC_END]
    ic_comb = daily_ic(conf, "comb", target)
    result = compare_daily_ic(base_ic[base_ic.index > DISC_END], ic_comb)
    disc_base = base_ic[base_ic.index <= DISC_END].mean()
    return {"lambda": best_lam, "disc_gain": best - disc_base, "conf_gain": result["diff_mean"], "conf_t": result["t_stat"]}


def main():
    px = add_price_columns(load_prices())
    # 심리 함수는 숫자 6자리 코드만 받는다. 영문이 섞인 신규 코드(예: 00088K)는 임시 번호로 계산하고 되돌린다.
    ids = {code: f"{i:06d}" for i, code in enumerate(sorted(px.Code.unique()))}
    back = {v: k for k, v in ids.items()}
    psych, _ = build_psychology_features(px[["Date", "Code", "Close", "Volume"]].assign(Code=px.Code.map(ids)))
    psych["Code"] = psych.Code.map(back)
    psych = psych.drop(columns="Date").rename(columns={"AvailableDate": "Date"})[["Date", "Code", *RAW_FEATURES]]
    # 시장 단위 심리: KOSPI 공포·탐욕(같은 식), 시장 변동성, 확산(종목 공포·탐욕 평균), 거래대금 과열
    kospi = pd.read_parquet(KOSPI)
    kospi = kospi.assign(Date=pd.to_datetime(kospi.Date).dt.normalize()).set_index("Date").Close.sort_index()
    klr = np.log(kospi / kospi.shift(1))
    market = pd.DataFrame({
        "kospi_fear_greed": np.tanh(klr.rolling(20).sum() / (klr.rolling(20).std() * np.sqrt(20))),
        "kospi_vol20": klr.rolling(20).std() * np.sqrt(252),
    })
    turnover = px.groupby("Date").amount.sum()
    market["turnover_heat"] = np.log(turnover.rolling(20).mean() / turnover.rolling(250).mean()).reindex(market.index)
    breadth = psych.groupby("Date").psych_fear_greed.mean()
    market["breadth"] = breadth.reindex(market.index)

    keys = ["Date", "Code"]
    oos = {}
    for h in (5, 20):
        frame = pd.read_parquet(ROOT.parent / "e0" / "oos" / f"h{h}_A.parquet",
                                columns=["Date", "Code", "prob_up", "forward_return", "return_observed"])
        oos[h] = frame.loc[frame.return_observed].assign(Date=lambda f: pd.to_datetime(f.Date))
    panel = oos[5][keys].merge(px, on=keys, how="left").merge(psych, on=keys, how="left")

    # 점검: 원본 가격의 5일 수익률과 표본 밖 파일의 수익률이 같은 값을 보는지
    check = oos[5].merge(px[[*keys, "fwd5"]], on=keys, how="inner").dropna()
    sanity = {"rows": len(check), "corr": float(check.forward_return.corr(check.fwd5)),
              "median_abs_diff": float((check.forward_return - check.fwd5).abs().median())}

    rows = []
    # 후보 5: 기간 맞추기 + 기존 가격 정보 제거 뒤 잔차 IC
    for feature in RAW_FEATURES:
        panel[f"{feature}_res"] = residualize(panel, feature)
        for h in HORIZONS:
            for kind, col in (("raw", feature), ("resid", f"{feature}_res")):
                rows.append({"candidate": "5_horizon", "feature": feature, "kind": kind, "target": f"fwd{h}",
                             **stat(daily_ic(panel, col, f"fwd{h}"))})
    # 후보 4: 위험(다음 20일 변동성)
    rows.append({"candidate": "4_risk", "feature": "vol20(기준)", "kind": "raw", "target": "fvol20",
                 **stat(daily_ic(panel, "vol20", "fvol20"))})
    for feature in RAW_FEATURES:
        for kind, col in (("raw", feature), ("resid", f"{feature}_res")):
            rows.append({"candidate": "4_risk", "feature": feature, "kind": kind, "target": "fvol20",
                         **stat(daily_ic(panel, col, "fvol20"))})
    screen = pd.DataFrame(rows)
    screen.to_csv(OUT / "screen_features.csv", index=False)

    regimes, interactions, combos = [], [], []
    for h in (5, 20):
        model = oos[h].merge(panel[[*keys, "vol60", *RAW_FEATURES]], on=keys, how="left")
        base_ic = daily_ic(model, "prob_up", "forward_return")
        # 후보 3: 국면별 모델 IC
        for name in market:
            regimes.append({"horizon": h, "regime": name, **regime_diff(base_ic, market[name])})
        # 후보 2: 투기성 종목(변동성 상위)의 IC가 시장 심리에 따라 바뀌는가(Baker-Wurgler)
        spec_ic = daily_ic(model, "vol60", "forward_return")
        for name in market:
            z = causal_z(market[name])
            interactions.append({"horizon": h, "sentiment": name, **slope_test(spec_ic, z.reindex(spec_ic.index))})
            model["bw"] = -z.reindex(model.Date).to_numpy() * model.groupby("Date").vol60.rank(pct=True).to_numpy()
            combos.append({"horizon": h, "signal": f"bw:{name}", **combine_test(model, base_ic, "bw", "forward_return")})
        # 참고: 심리 원지표 4개를 모델 점수에 섞기(재학습 없는 근사)
        for feature in RAW_FEATURES:
            combos.append({"horizon": h, "signal": feature, **combine_test(model, base_ic, feature, "forward_return")})
    pd.DataFrame(regimes).to_csv(OUT / "regime_ic.csv", index=False)
    pd.DataFrame(interactions).to_csv(OUT / "bw_slope.csv", index=False)
    pd.DataFrame(combos).to_csv(OUT / "combine.csv", index=False)
    print("sanity", sanity)


if __name__ == "__main__":
    main()

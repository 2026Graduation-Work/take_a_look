import numpy as np
import pandas as pd


class SwingStrategy:
    def __init__(self, config: dict):
        self.config = config
        self.strat_cfg = config.get("strategy", {})
        self.prob_threshold = self.strat_cfg.get("prob_threshold", 0.75)
        self.top_n = self.strat_cfg.get("top_n", 5)

    def generate_signals(self, predictions: pd.DataFrame, price_df: pd.DataFrame) -> tuple:
        """predictions: Date, Code, Prob. price_df: Date, Code, Open, Sigma, Trading_Halt."""
        print(
            f"[Strategy] 시그널 생성 중... (Threshold: {self.prob_threshold}, Top-N: {self.top_n})"
        )

        # 전체 시장 거래일 캘린더를 유지한다. fold test 행만 이어 붙이면 shift(1)가
        # embargo를 건너 이전 fold 신호를 다음 fold 첫 거래일로 전달할 수 있다.
        # embargo 날짜는 신규 진입을 금지하지만, 기존 포지션의 청산·만기 처리는
        # 연속된 가격 캘린더 위에서 정상적으로 진행된다.
        market = price_df.copy()
        market["Date"] = pd.to_datetime(market["Date"]).dt.tz_localize(None)
        score = self.strat_cfg.get("score_column", "Prob")
        prediction_frame = (
            predictions[["Date", "Code", score]].rename(columns={score: "Prob"}).copy()
        )
        prediction_frame["Date"] = pd.to_datetime(prediction_frame["Date"]).dt.tz_localize(None)

        raw_open_price = market.pivot(index="Date", columns="Code", values="Open")
        open_price = raw_open_price.ffill()
        trading_halt = market.pivot(index="Date", columns="Code", values="Trading_Halt").fillna(0)
        eligible = (
            market.pivot(index="Date", columns="Code", values="UniverseEligible")
            .reindex(index=raw_open_price.index, columns=raw_open_price.columns)
            .fillna(False)
            .astype(bool)
            if "UniverseEligible" in market
            else pd.DataFrame(True, index=raw_open_price.index, columns=raw_open_price.columns)
        )
        prob = prediction_frame.pivot(index="Date", columns="Code", values="Prob")
        prob = prob.reindex(index=raw_open_price.index, columns=raw_open_price.columns).fillna(0.0)
        prediction_dates = prediction_frame.assign(_prediction=True).pivot(
            index="Date", columns="Code", values="_prediction"
        )
        prediction_dates = prediction_dates.reindex(
            index=raw_open_price.index, columns=raw_open_price.columns, fill_value=False
        ).fillna(False)

        valid_mask = (
            (prob >= self.prob_threshold)
            & raw_open_price.notna()
            & (open_price > 1.0)
            & (trading_halt == 0)
            & eligible
        )

        rankings = prob.where(valid_mask).rank(axis=1, method="first", ascending=False)
        raw_entries = rankings <= self.top_n

        equal_weight = 1.0 / self.top_n
        weights = pd.DataFrame(
            np.where(raw_entries, equal_weight, 0.0), index=prob.index, columns=prob.columns
        )

        # T일 예측은 T+lag일 시가에 진입시켜 미래 참조를 막는다.
        lag = self.config.get("backtest", {}).get("signal_lag_days", 1)
        entries = raw_entries.shift(lag).fillna(False)
        weights = weights.shift(lag).fillna(0.0)

        # T+1이 embargo라면 이전 fold의 신호를 실행하지 않는다. 다음 fold 첫날도
        # prediction 날짜이지만 raw signal이 없으므로, 과거 fold 신호가 건너오지 않는다.
        entries = (
            entries & prediction_dates & raw_open_price.notna() & (trading_halt == 0) & eligible
        )
        for offset in range(1, lag + 1):
            entries &= prediction_dates.shift(offset).fillna(False)

        weights = weights.where(entries, np.nan)

        signal_sigma = (
            market.pivot(index="Date", columns="Code", values="Sigma")
            .reindex(index=entries.index, columns=entries.columns)
            .shift(lag)
        )
        entries.attrs["signal_sigma"] = signal_sigma
        return entries, weights

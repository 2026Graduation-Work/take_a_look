import numpy as np
import pandas as pd


class SwingStrategy:
    """
    모델의 예측 확률(Prob)과 가격/변동성(Sigma) 데이터를 받아
    최종 트레이딩 진입(Entries) 및 비중(Weights) 시그널 매트릭스를 생성합니다.
    (기존 05_backtest.py의 시그널 생성 및 리스크 패리티 로직 통합)
    """

    def __init__(self, config: dict):
        self.config = config
        self.strat_cfg = config.get("strategy", {})
        self.prob_threshold = self.strat_cfg.get("prob_threshold", 0.75)
        self.top_n = self.strat_cfg.get("top_n", 5)

    def generate_signals(self, predictions: pd.DataFrame, price_df: pd.DataFrame) -> tuple:
        """
        predictions: ['Date', 'Code', 'Prob'] 데이터프레임
        price_df: ['Date', 'Code', 'Open', 'Sigma', 'Trading_Halt'] 데이터프레임

        Returns:
            entries: 매수 진입 시그널 (2D Matrix: Date x Code)
            weights: 진입 비중 매트릭스 (2D Matrix) - 리스크 패리티 적용
        """
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
        if (
            score == "prob_up"
            and score not in predictions
            and self.config.get("contract_version") != 3
        ):
            score = "Prob"
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

        # 3. 매수 진입 유효성 검사 (확률 컷 통과 + 거래정지 아님 + 상장됨)
        valid_mask = (
            (prob >= self.prob_threshold)
            & raw_open_price.notna()
            & (open_price > 1.0)
            & (trading_halt == 0)
            & eligible
        )

        # 4. Top N 랭킹 (행 단위로 매일 가장 유망한 종목 선별)
        rankings = prob.where(valid_mask).rank(axis=1, method="first", ascending=False)
        raw_entries = rankings <= self.top_n

        # 5. 동일 비중 (Equal Weight) 할당
        # 매일 선택된 최대 N개의 종목에 대해 각각 1/N 만큼의 동일한 비중을 할당
        equal_weight = 1.0 / self.top_n
        weights = pd.DataFrame(
            np.where(raw_entries, equal_weight, 0.0), index=prob.index, columns=prob.columns
        )

        # 6. 미래 참조(Look-ahead bias) 원천 차단
        # T일 모델 예측을 바탕으로 -> 실제 매수는 T+1일 Open 가격에 진입
        lag = self.config.get("backtest", {}).get("signal_lag_days", 1)
        entries = raw_entries.shift(lag).fillna(False)
        weights = weights.shift(lag).fillna(0.0)

        # T+1일(매수 집행일)이 거래정지일이면 진입 차단
        # T+1이 embargo라면 이전 fold의 신호를 실행하지 않는다. 다음 fold 첫날도
        # prediction 날짜이지만 raw signal이 없으므로, 과거 fold 신호가 건너오지 않는다.
        entries = (
            entries & prediction_dates & raw_open_price.notna() & (trading_halt == 0) & eligible
        )
        for offset in range(1, lag + 1):
            entries &= prediction_dates.shift(offset).fillna(False)

        # 7. 강제 리밸런싱 및 수수료 폭탄 방지
        # VectorBT는 빈칸이 아니면 매일 비중을 조절하려 하므로, 매수 진입일 외에는 NaN으로 둠
        weights = weights.where(entries, np.nan)

        signal_sigma = (
            market.pivot(index="Date", columns="Code", values="Sigma")
            .reindex(index=entries.index, columns=entries.columns)
            .shift(lag)
        )
        entries.attrs["signal_sigma"] = signal_sigma
        return entries, weights

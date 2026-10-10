# ruff: noqa: I001

import json
import os

import numpy as np
import pandas as pd

import vectorbt as vbt


BENCHMARK_WEIGHTS_VERSION = "krx_annual_market_cap_v1"


def _parse_naive_dates(values: pd.Series) -> pd.Series:
    """Parse mixed date representations without retaining timezone information."""
    try:
        parsed = pd.to_datetime(values, format="mixed")
    except (TypeError, ValueError):
        # pandas < 2.0 does not support ``format='mixed'``.
        parsed = pd.to_datetime(values)
    return parsed.dt.tz_localize(None)


def _empty_benchmark(index: pd.DatetimeIndex, source: str, reason: str) -> pd.Series:
    result = pd.Series(float("nan"), index=index, name="Benchmark_Custom_KRX")
    result.attrs["benchmark_source"] = source
    result.attrs["benchmark_reason"] = reason
    result.attrs["benchmark_valid"] = False
    return result


def _benchmark_cache_paths() -> tuple[str, str]:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    cache_dir = os.path.abspath(os.path.join(current_dir, "..", "cache", "benchmarks"))
    os.makedirs(cache_dir, exist_ok=True)
    return (
        os.path.join(cache_dir, "krx_composite_daily.parquet"),
        os.path.join(cache_dir, "krx_composite_metadata.json"),
    )


def _is_valid_benchmark(series: pd.Series) -> tuple[bool, str]:
    if series.empty:
        return False, "empty benchmark"
    if series.isna().all():
        return False, "all NaN"
    filled = series.fillna(0.0)
    if filled.abs().sum() == 0.0:
        return False, "all zero returns"
    total_return = (1.0 + filled).prod() - 1.0
    if abs(total_return) < 1e-12:
        return False, "0.00% total return"
    return True, "valid"


def _attach_benchmark_attrs(series: pd.Series, source: str, reason: str) -> pd.Series:
    valid, validity_reason = _is_valid_benchmark(series)
    result = series.rename("Benchmark_Custom_KRX")
    result.attrs["benchmark_source"] = source
    result.attrs["benchmark_reason"] = reason
    result.attrs["benchmark_valid"] = valid
    result.attrs["benchmark_validity_reason"] = validity_reason
    return result


def _load_cached_benchmark(index: pd.DatetimeIndex) -> pd.Series | None:
    daily_path, metadata_path = _benchmark_cache_paths()
    if not os.path.exists(daily_path):
        return None

    cached = pd.read_parquet(daily_path)
    if "Date" not in cached.columns or "Return" not in cached.columns:
        return None

    cached["Date"] = _parse_naive_dates(cached["Date"])
    if cached["Date"].duplicated().any():
        return None

    requested_index = pd.DatetimeIndex(index)
    if requested_index.tz is not None:
        requested_index = requested_index.tz_localize(None)
    cached_returns = cached.set_index("Date")["Return"].sort_index()
    if not requested_index.isin(cached_returns.index).all():
        return None
    series = cached_returns.reindex(requested_index)
    metadata = {}
    if os.path.exists(metadata_path):
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)
    if metadata.get("weights_version") != BENCHMARK_WEIGHTS_VERSION:
        return None
    result = _attach_benchmark_attrs(
        series,
        metadata.get("source", "cache"),
        metadata.get("reason", "loaded from benchmark cache"),
    )
    if result.attrs["benchmark_valid"]:
        return result
    return None


def _save_benchmark_cache(series: pd.Series, source: str, reason: str) -> None:
    valid, validity_reason = _is_valid_benchmark(series)
    if not valid:
        return

    daily_path, metadata_path = _benchmark_cache_paths()
    out = series.rename("Return").reset_index()
    out.columns = ["Date", "Return"]
    out.to_parquet(daily_path, index=False)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source": source,
                "reason": reason,
                "valid": valid,
                "validity_reason": validity_reason,
                "weights_version": BENCHMARK_WEIGHTS_VERSION,
                "start": str(pd.to_datetime(out["Date"]).min().date()),
                "end": str(pd.to_datetime(out["Date"]).max().date()),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def _compute_internal_equal_weight_benchmark(
    index: pd.DatetimeIndex, price_df: pd.DataFrame | None
) -> pd.Series:
    if price_df is None or price_df.empty:
        return _empty_benchmark(index, "unavailable", "price_df is empty")

    required = {"Date", "Code", "Close"}
    missing = required - set(price_df.columns)
    if missing:
        return _empty_benchmark(index, "unavailable", f"missing columns: {sorted(missing)}")

    prices = price_df.copy()
    prices["Date"] = _parse_naive_dates(prices["Date"])
    close = prices.pivot(index="Date", columns="Code", values="Close").sort_index().ffill()
    close = close.reindex(index).ffill()
    returns = close.pct_change(fill_method=None)

    if "Trading_Halt" in prices.columns:
        halt = prices.pivot(index="Date", columns="Code", values="Trading_Halt").reindex(index).fillna(0)
        returns = returns.where(halt == 0)

    ew_returns = returns.mean(axis=1, skipna=True).fillna(0.0)
    if ew_returns.abs().sum() == 0.0:
        return _empty_benchmark(index, "unavailable", "internal equal-weight returns are all zero")

    result = _attach_benchmark_attrs(
        ew_returns,
        "internal_equal_weight",
        "external KRX download failed; using universe equal-weight close returns",
    )
    return result


def configured_benchmark(config, index, price_df):
    """Use a frozen benchmark when supplied; never silently substitute another index."""
    path = config.get("evaluation", {}).get("benchmark_file")
    if not path:
        if config.get("contract_version") == 3:
            raise ValueError("evaluation.benchmark_file must identify a frozen dataset index")
        return compute_custom_krx_composite(index, price_df)
    from experiments.config import chart_path
    path = chart_path(path)
    frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, parse_dates=["Date"])
    frame["Date"] = pd.to_datetime(frame["Date"])
    frame = frame.set_index("Date")
    if frame.index.duplicated().any():
        raise ValueError("Duplicate benchmark dates")
    returns = frame["Close"].sort_index().pct_change(fill_method=None).reindex(index)
    if returns.isna().any() or not np.isfinite(returns).all():
        raise ValueError("Benchmark must cover every evaluation day and preceding close")
    return _attach_benchmark_attrs(returns, str(path), "frozen daily closes; no dividends")


def kospi_index_returns(index: pd.DatetimeIndex, csv_path: str | None = None) -> pd.Series:
    """KOSPI price-index buy-and-hold returns on the portfolio's trading dates."""
    index = pd.DatetimeIndex(index).tz_localize(None)
    if csv_path:
        closes = pd.read_csv(csv_path, parse_dates=["Date"]).set_index("Date")["Close"]
        source = csv_path
    else:
        cache_path = os.path.join(os.path.dirname(_benchmark_cache_paths()[0]), "kospi_index_close.parquet")
        if os.path.exists(cache_path):
            closes = pd.read_parquet(cache_path).set_index("Date")["Close"]
        else:
            import FinanceDataReader as fdr

            raw = fdr.DataReader(
                "KS11",
                (index.min() - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
                (index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            )
            closes = raw["Close"]
            if closes.empty:
                raise ValueError("KOSPI index download returned no closes")
            closes.index = pd.DatetimeIndex(closes.index).tz_localize(None)
            closes.rename("Close").rename_axis("Date").reset_index().to_parquet(cache_path, index=False)
        source = "FinanceDataReader KS11"

    closes.index = pd.DatetimeIndex(closes.index).tz_localize(None)
    closes = pd.to_numeric(closes, errors="coerce").sort_index()
    if closes.index.has_duplicates or closes.empty or (closes <= 0).any():
        raise ValueError("KOSPI index closes contain duplicate dates or invalid prices")
    if closes.index.min() >= index.min():
        raise ValueError("KOSPI index needs a close before the first evaluation date")
    # Portfolio dates may include KRX holidays; holding the index is flat then.
    aligned_close = closes.reindex(closes.index.union(index)).sort_index().ffill()
    returns = aligned_close.pct_change(fill_method=None).reindex(index)
    if returns.isna().any() or not np.isfinite(returns).all():
        missing = index[returns.isna()]
        raise ValueError(f"KOSPI index missing evaluation dates: {missing[:5].tolist()}")
    result = returns.rename("Benchmark_KOSPI")
    result.attrs["benchmark_source"] = source
    return result


def compute_custom_krx_composite(
    index: pd.DatetimeIndex, price_df: pd.DataFrame | None = None
) -> pd.Series:
    """
    커스텀 KRX 통합 지수 (Custom KRX Composite Index) 산출 함수

    KOSPI(^KS11)와 KOSDAQ(^KQ11)의 일별 수익률을 각 시장의
    연간 평균 유동 시가총액 비중으로 가중 평균하여 통합 지수를 구성합니다.
    """
    cached = _load_cached_benchmark(index)
    if cached is not None:
        print("[*] 커스텀 KRX 통합 지수 산출: benchmark cache 로드")
        return cached

    ANNUAL_WEIGHTS = {
        2016: (0.84, 0.16),
        2017: (0.84, 0.16),
        2018: (0.83, 0.17),
        2019: (0.83, 0.17),
        2020: (0.80, 0.20),
        2021: (0.78, 0.22),
        2022: (0.80, 0.20),
        2023: (0.82, 0.18),
        2024: (0.83, 0.17),
        2025: (0.83, 0.17),
    }
    DEFAULT_WEIGHT = (0.82, 0.18)

    try:
        import yfinance as yf

        yf_start = (index[0] - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        yf_end = (index[-1] + pd.Timedelta(days=10)).strftime("%Y-%m-%d")

        print("[*] 커스텀 KRX 통합 지수 산출: KOSPI(^KS11) + KOSDAQ(^KQ11) 다운로드 중...")
        raw = yf.download(
            ["^KS11", "^KQ11"], start=yf_start, end=yf_end, progress=False, auto_adjust=True
        )

        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"].copy()
        else:
            close = raw.copy()

        close.index = pd.to_datetime(close.index).tz_localize(None)

        ks_ret = close["^KS11"].pct_change()
        kq_ret = close["^KQ11"].pct_change()

        composite_returns = []
        for date in index:
            year = date.year
            w_ks, w_kq = ANNUAL_WEIGHTS.get(year, DEFAULT_WEIGHT)

            r_ks = ks_ret.get(date, 0.0) if date in ks_ret.index else 0.0
            r_kq = kq_ret.get(date, 0.0) if date in kq_ret.index else 0.0

            r_ks = 0.0 if pd.isna(r_ks) else float(r_ks)
            r_kq = 0.0 if pd.isna(r_kq) else float(r_kq)

            composite_returns.append(w_ks * r_ks + w_kq * r_kq)

        result = pd.Series(composite_returns, index=index, name="Benchmark_Custom_KRX")
        valid, validity_reason = _is_valid_benchmark(result)
        if not valid:
            print("⚠️ 외부 KRX 지수 수익률이 전부 0입니다. 내부 equal-weight benchmark로 대체합니다.")
            return _compute_internal_equal_weight_benchmark(index, price_df)

        result = _attach_benchmark_attrs(
            result, "external_krx", "KOSPI/KOSDAQ yfinance download succeeded"
        )
        _save_benchmark_cache(result, "external_krx", "KOSPI/KOSDAQ yfinance download succeeded")
        print(f"✅ 커스텀 KRX 통합 지수 산출 완료 (기간: {index[0].date()} ~ {index[-1].date()})")
        return result

    except Exception as e:
        print(f"⚠️ 커스텀 KRX 통합 지수 산출 실패 ({e}) - 내부 equal-weight benchmark로 대체")
        return _compute_internal_equal_weight_benchmark(index, price_df)


def calculate_rule_exits(
    entry_series,
    open_series,
    high_series,
    low_series,
    close_series,
    sigma_series,
    halt_series,
    holding_days,
    up_mult,
    down_mult,
    hard_sl_mult,
):
    """Stops and horizon exits from one synchronized position state."""
    n = len(entry_series)
    exits = pd.Series(False, index=entry_series.index)
    exit_prices = pd.Series(float("nan"), index=entry_series.index)
    if halt_series is None:
        halt_series = pd.Series(0, index=entry_series.index)

    in_position = False
    pending_next_open_exit = False
    entry_price = 0.0
    entry_sigma = 0.0
    trading_days_held = 0

    for i in range(n):
        is_halt = bool(halt_series.iloc[i])
        if in_position:
            if is_halt:
                continue

            if pending_next_open_exit:
                exits.iloc[i] = True
                exit_prices.iloc[i] = open_series.iloc[i]
                in_position = False
                pending_next_open_exit = False
                trading_days_held = 0
                continue

            trading_days_held += 1

            # D. 보유 기간 만기 청산 (Time Exit) - 만기 도래 시 당일 시가(T+Holding) 청산
            # 장중 가격 움직임보다 먼저 체크되어야 함. 당일 시가에 이미 파는 것이기 때문.
            if trading_days_held >= holding_days:
                exits.iloc[i] = True
                exit_prices.iloc[i] = open_series.iloc[i]
                in_position = False
                trading_days_held = 0
                continue

            # A. 하드 손절 (Hard Stop Loss) - 장중 저가가 손절 라인 돌파 시 당일 청산
            hard_stop_line = (
                entry_price * (1.0 - hard_sl_mult * entry_sigma)
                if hard_sl_mult is not None
                else float("-inf")
            )
            if hard_sl_mult is not None and low_series.iloc[i] <= hard_stop_line:
                exits.iloc[i] = True
                exit_prices.iloc[i] = min(open_series.iloc[i], hard_stop_line)
                in_position = False
                trading_days_held = 0
                continue

            # B. 하드 익절 (Hard Take Profit) - 장중 고가가 익절 라인 돌파 시 당일 청산
            take_profit_line = (
                entry_price * (1.0 + up_mult * entry_sigma) if up_mult is not None else float("inf")
            )
            if up_mult is not None and high_series.iloc[i] >= take_profit_line:
                exits.iloc[i] = True
                exit_prices.iloc[i] = max(open_series.iloc[i], take_profit_line)
                in_position = False
                trading_days_held = 0
                continue

            # C. 소프트 스톱 (Soft Stop) - 당일 종가가 소프트 스톱선 이탈 시 다음날 시가 청산
            soft_stop_line = entry_price * (1.0 - down_mult * entry_sigma)
            if close_series.iloc[i] < soft_stop_line:
                pending_next_open_exit = True
                continue

        if entry_series.iloc[i] and not in_position and not is_halt and not exits.iloc[i]:
            in_position = True
            entry_price = open_series.iloc[i]
            entry_sigma = sigma_series.iloc[i]
            trading_days_held = 0

    return exits, exit_prices


def calculate_soft_exits(
    entry_series, open_series, close_series, sigma_series, halt_series, holding_days, down_mult
):
    """Backward-compatible wrapper for legacy callers."""
    exits, _ = calculate_rule_exits(
        entry_series=entry_series,
        open_series=open_series,
        high_series=pd.Series(float("nan"), index=entry_series.index),
        low_series=pd.Series(float("nan"), index=entry_series.index),
        close_series=close_series,
        sigma_series=sigma_series,
        halt_series=halt_series,
        holding_days=holding_days,
        up_mult=None,
        down_mult=down_mult,
        hard_sl_mult=None,
    )
    return exits


class VectorBTEngine:
    """VectorBT 기반의 고속 포트폴리오 백테스트 엔진"""

    def __init__(self, config: dict):
        self.config = config
        self.bt_cfg = config.get("backtest", {})
        self.init_cash = self.bt_cfg.get("initial_cash", 10000000)
        self.fee = self.bt_cfg.get("fee", 0.0025)
        self.up_mult = self.bt_cfg.get("up_mult", 3.5)
        self.down_mult = self.bt_cfg.get("down_mult", 2.0)
        self.hard_sl_mult = self.bt_cfg.get("hard_sl_mult", 2.5)
        # 라벨 horizon은 학습 타깃 정의이고, 실제 보유 기간은 별도 실험 변수다.
        self.holding_days = self.bt_cfg.get(
            "max_holding_days", config.get("labels", {}).get("horizon", 5)
        )

    def run(self, entries: pd.DataFrame, weights: pd.DataFrame, price_df: pd.DataFrame, generate_report: bool = True):
        if self.config.get("contract_version") == 3:
            from .local_execution import simulate
            return simulate(self.config, entries, weights, price_df)
        print(
            f"[Backtest] 시뮬레이션 가동 (초기자금: {self.init_cash:,}원, 수수료: {self.fee * 100}%)"
        )

        price_df = price_df[
            price_df["Date"].isin(entries.index) & price_df["Code"].isin(entries.columns)
        ]

        open_price = price_df.pivot(index="Date", columns="Code", values="Open").ffill()
        high_price = price_df.pivot(index="Date", columns="Code", values="High").ffill()
        low_price = price_df.pivot(index="Date", columns="Code", values="Low").ffill()
        close_price = price_df.pivot(index="Date", columns="Code", values="Close").ffill()
        trading_halt = price_df.pivot(index="Date", columns="Code", values="Trading_Halt").fillna(0)
        sigma = price_df.pivot(index="Date", columns="Code", values="Sigma").fillna(0.01)

        aligned_frames = [open_price, high_price, low_price, close_price, trading_halt, sigma]
        for idx, frame in enumerate(aligned_frames):
            aligned = frame.reindex(index=entries.index, columns=entries.columns).ffill()
            aligned.index.name = entries.index.name
            aligned.columns.name = entries.columns.name
            aligned_frames[idx] = aligned
        open_price, high_price, low_price, close_price, trading_halt, sigma = aligned_frames

        # 상장 전·데이터 시작 전의 미래 가격을 채우지 않는다. 가격이 없는 날에는 진입을 막는다.
        price_available = open_price.notna() & high_price.notna() & low_price.notna() & close_price.notna()
        entries = entries & price_available

        print("[Backtest] Stop 및 시간 만기(Horizon) 시그널 계산 중...")
        exits_dict = {}
        exit_price_dict = {}
        for col in entries.columns:
            exits_dict[col], exit_price_dict[col] = calculate_rule_exits(
                entry_series=entries[col],
                open_series=open_price[col],
                high_series=high_price[col],
                low_series=low_price[col],
                close_series=close_price[col],
                sigma_series=sigma[col],
                halt_series=trading_halt[col],
                holding_days=self.holding_days,
                up_mult=self.up_mult,
                down_mult=self.down_mult,
                hard_sl_mult=self.hard_sl_mult,
            )
        exits = pd.DataFrame(exits_dict, index=entries.index)
        exit_prices = pd.DataFrame(exit_price_dict, index=entries.index)
        order_price = open_price.astype(float).mask(exits, exit_prices.astype(float))

        # [4] 시그널 충돌 방지 마스킹 (Signal Conflict Resolution)
        # Entry와 Exit가 같은 날 겹칠 때 vectorbt의 청산 누락 버그 방지를 위해
        # Exit가 발생하는 날에는 Entry를 강제로 차단(False)합니다.
        entries = entries & ~exits

        # [보완 패치] 비중 매트릭스 동기화 (Size Alignment)
        weights = weights.where(entries, np.nan)

        print("[Backtest] 포트폴리오 성과 집계 중...")
        pf = vbt.Portfolio.from_signals(
            close=close_price,
            price=order_price,
            open=open_price,
            high=high_price,
            low=low_price,
            entries=entries,
            exits=exits,
            size=weights,
            size_type="percent",
            fees=self.fee,
            init_cash=self.init_cash,
            freq="D",
            group_by=True,
            cash_sharing=True,
        )

        if generate_report:
            stats = pf.stats()
            print("\n" + "=" * 60)
            print("★ [VectorBT 퀀트 백테스트 결과 리포트] ★")
            print("=" * 60)
            print(stats)
            print("=" * 60)

            # 결과 저장 폴더 설정 (experiments/results 기준)
            exp_name = self.config.get("experiment_name", "default_exp")
            current_dir = os.path.dirname(os.path.abspath(__file__))
            result_dir = os.path.abspath(os.path.join(current_dir, "..", "results", exp_name))
            os.makedirs(result_dir, exist_ok=True)

            try:
                trades_df = pf.trades.records_readable
                trades_df.to_csv(os.path.join(result_dir, "trades.csv"), index=False)

                daily_returns = pf.returns()
                ew_benchmark = pf.benchmark_returns()
                custom_krx_benchmark = configured_benchmark(self.config, open_price.index, price_df)

                returns_df = pd.DataFrame(
                    {
                        "Portfolio": daily_returns,
                        "Benchmark_EW": ew_benchmark,
                        "Benchmark_CustomKRX": custom_krx_benchmark,
                    }
                )
                returns_df.attrs["benchmark_source"] = custom_krx_benchmark.attrs.get(
                    "benchmark_source", "unknown"
                )
                returns_df.to_csv(os.path.join(result_dir, "daily_returns.csv"), header=True)
                pd.DataFrame(
                    [
                        {
                            "benchmark": "Benchmark_CustomKRX",
                            "source": custom_krx_benchmark.attrs.get("benchmark_source", "unknown"),
                            "reason": custom_krx_benchmark.attrs.get("benchmark_reason", ""),
                            "valid": custom_krx_benchmark.attrs.get("benchmark_valid", False),
                            "validity_reason": custom_krx_benchmark.attrs.get(
                                "benchmark_validity_reason", ""
                            ),
                        }
                    ]
                ).to_csv(os.path.join(result_dir, "benchmark_metadata.csv"), index=False)
                print("✅ 일일 수익률 CSV 저장 완료")
            except Exception as e:
                print(f"⚠️ CSV 저장 실패: {e}")
                ew_benchmark = pd.Series(dtype=float)

            try:
                html_path = os.path.join(result_dir, "equity_curve.html")
                pf.plot().write_html(html_path)
                print(f"✅ 인터랙티브 수익률 차트 저장 완료: {html_path}")
            except Exception as e:
                print(f"⚠️ 인터랙티브 수익률 차트 저장 실패: {e}")

            try:
                import quantstats as qs

                qs_report_path = os.path.join(result_dir, "quantstats_report.html")
                qs.reports.html(
                    daily_returns,
                    ew_benchmark,
                    output=qs_report_path,
                    title=f"QuantStats Report - {exp_name} (vs Universe EW B&H)",
                )
                qs_krx_path = os.path.join(result_dir, "quantstats_report_krx.html")
                qs.reports.html(
                    daily_returns,
                    custom_krx_benchmark,
                    output=qs_krx_path,
                    title=f"QuantStats Report - {exp_name} (vs Custom KRX Composite)",
                )
                print(f"✅ QuantStats 성과 보고서 저장 완료: {qs_report_path}")
            except Exception as e:
                print(f"⚠️ QuantStats 보고서 저장 실패: {e}")

        return pf

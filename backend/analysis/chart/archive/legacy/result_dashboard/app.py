# ruff: noqa: I001

import calendar
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

EXPERIMENTS_DIR = Path(__file__).resolve().parents[1]
if str(EXPERIMENTS_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS_DIR))

from experiment_utils import generate_predictions_hash, model_cache_dir, resolve_splits  # noqa: E402

st.set_page_config(page_title="Quant Backtest Dashboard", layout="wide")


# ==========================================
# 매크로 이벤트 (하드코딩된 정성적 정보)
# ==========================================
MACRO_EVENTS = {
    "2018-01": "미·중 무역 분쟁 본격화 시작",
    "2018-10": "글로벌 증시 동반 폭락 (검은 10월)",
    "2020-03": "COVID-19 팬데믹 증시 대폭락",
    "2020-04": "동학개미운동 및 전세계적 유동성 장세 시작",
    "2021-06": "인플레이션 우려 및 금리 인상 예고",
    "2022-01": "글로벌 긴축 가속화 (베어마켓 진입)",
    "2022-09": "킹달러 및 채권 금리 폭등 쇼크",
    "2023-01": "AI 붐 (ChatGPT) 시작",
    "2023-11": "한국 주식시장 공매도 전면 금지 시행",
    "2024-02": "정부 '기업 밸류업 프로그램' 발표",
    "2024-08": "미국발 리세션 우려 블랙먼데이 쇼크",
}


def get_monthly_returns(daily_returns: pd.Series) -> pd.DataFrame:
    """일일 수익률을 월별 누적 수익률 퍼센트로 변환합니다."""
    monthly = daily_returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    df = monthly.reset_index()
    df.columns = ["Date", "Return"]
    df["Year"] = df["Date"].dt.year
    df["Month"] = df["Date"].dt.month
    pivot = df.pivot(index="Year", columns="Month", values="Return")
    return pivot


def _analysis_dir(results_dir: str) -> str:
    return os.path.join(results_dir, "horizon_final_analysis")


def _format_analysis_percent(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").map(
                lambda x: "" if pd.isna(x) else f"{x * 100:.2f}%"
            )
    return out


def render_horizon_final_analysis(results_dir: str) -> None:
    analysis_dir = _analysis_dir(results_dir)
    if not os.path.exists(analysis_dir):
        st.warning(
            "horizon_final_analysis 결과가 없습니다. "
            "`python experiments/scripts/analysis/run_horizon_final_analysis.py`를 먼저 실행하세요."
        )
        return

    st.subheader("H별 확정 Multiplier 분석")
    paths = {
        "summary": os.path.join(analysis_dir, "horizon_final_summary.csv"),
        "prob": os.path.join(analysis_dir, "probability_return_calibration.csv"),
        "ticker": os.path.join(analysis_dir, "ticker_contribution.csv"),
        "market": os.path.join(analysis_dir, "market_contribution.csv"),
        "sensitivity": os.path.join(analysis_dir, "portfolio_rule_sensitivity.csv"),
        "corr": os.path.join(analysis_dir, "horizon_signal_correlation.csv"),
        "overlap": os.path.join(analysis_dir, "horizon_signal_overlap_groups.csv"),
    }
    missing = [name for name, path in paths.items() if not os.path.exists(path)]
    if missing:
        st.error(f"분석 파일이 누락되었습니다: {missing}")
        return

    summary = pd.read_csv(paths["summary"])
    prob = pd.read_csv(paths["prob"])
    ticker = pd.read_csv(paths["ticker"])
    market = pd.read_csv(paths["market"])
    sensitivity = pd.read_csv(paths["sensitivity"])
    corr = pd.read_csv(paths["corr"])
    overlap = pd.read_csv(paths["overlap"])

    invalid_bench = summary[~summary["Benchmark Valid"]]
    if invalid_bench.empty:
        st.success("Benchmark_CustomKRX validity: all selected horizon results are valid.")
    else:
        st.warning("일부 horizon의 Benchmark_CustomKRX가 invalid입니다.")
        st.dataframe(
            invalid_bench[["Horizon", "Benchmark Validity Reason"]],
            use_container_width=True,
            hide_index=True,
        )

    tab_summary, tab_prob, tab_contrib, tab_market, tab_overlap, tab_rules = st.tabs(
        [
            "H 비교",
            "Probability Bucket",
            "종목 기여도",
            "시장별 성과",
            "신호 중복",
            "Rule 민감도",
        ]
    )

    with tab_summary:
        display = _format_analysis_percent(
            summary,
            [
                "Total Return",
                "CAGR",
                "MDD",
                "Win Rate",
                "Average Win",
                "Average Loss",
                "Expectancy",
                "Benchmark Custom KRX Return",
                "Excess Return vs Custom KRX",
            ],
        )
        st.dataframe(display, use_container_width=True, hide_index=True)
        fig = px.bar(summary, x="Horizon", y="Total Return", color="Horizon", title="H별 Total Return")
        st.plotly_chart(fig, use_container_width=True)

    with tab_prob:
        selected_h = st.selectbox("Horizon", sorted(prob["Horizon"].unique()), key="prob_horizon")
        display = prob[prob["Horizon"] == selected_h].copy()
        st.dataframe(
            _format_analysis_percent(
                display,
                [
                    "average_return",
                    "win_rate",
                    "average_win",
                    "average_loss",
                    "expectancy",
                    "Label Hit Rate",
                    "Average Forward Return",
                    "Average Realized Return",
                ],
            ),
            use_container_width=True,
            hide_index=True,
        )
        chart_df = display[display["Bucket Type"] == "probability"]
        fig = px.bar(
            chart_df,
            x="Bucket",
            y="Average Realized Return",
            color="Bucket",
            title=f"{selected_h} bucket별 realized-return proxy",
        )
        st.plotly_chart(fig, use_container_width=True)

    with tab_contrib:
        selected_h = st.selectbox("Horizon", sorted(ticker["Horizon"].unique()), key="ticker_horizon")
        contrib = ticker[ticker["Horizon"] == selected_h].sort_values("total_pnl", ascending=False)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 수익 상위")
            st.dataframe(contrib.head(20), use_container_width=True, hide_index=True)
        with col2:
            st.markdown("#### 손실 상위")
            st.dataframe(contrib.tail(20).sort_values("total_pnl"), use_container_width=True, hide_index=True)

    with tab_market:
        st.dataframe(market, use_container_width=True, hide_index=True)
        fig = px.bar(market, x="Market", y="total_pnl", color="Horizon", barmode="group")
        st.plotly_chart(fig, use_container_width=True)

    with tab_overlap:
        st.markdown("#### Prediction correlation")
        st.dataframe(corr, use_container_width=True, hide_index=True)
        st.markdown("#### Top-k overlap 및 H5/H20 group performance")
        st.dataframe(overlap, use_container_width=True, hide_index=True)

    with tab_rules:
        st.dataframe(
            _format_analysis_percent(
                sensitivity, ["proxy_total_return", "proxy_cagr", "proxy_mdd"]
            ),
            use_container_width=True,
            hide_index=True,
        )


def main():
    st.title("📈 Quant Trading Dashboard")
    st.markdown(
        "백테스트 결과를 한눈에 분석하고, 거시경제 이벤트와 결합하여 리버스 엔지니어링을 수행합니다."
    )

    # 루트 디렉토리 기준 (run_experiment와 동일한 관점)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.abspath(os.path.join(current_dir, "..", "results"))

    if not os.path.exists(results_dir):
        st.warning(f"결과 폴더가 존재하지 않습니다: {results_dir}\n먼저 백테스트를 실행해주세요.")
        return

    experiments = [
        d for d in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, d))
    ]
    experiments.sort(reverse=True)

    if not experiments:
        st.warning("저장된 실험 결과가 없습니다.")
        return

    st.sidebar.header("실험 설정")
    selected_exp = st.sidebar.selectbox("결과 분석할 실험(Experiment)을 선택하세요:", experiments)

    view_mode = st.sidebar.radio(
        "📊 대시보드 뷰 선택:",
        ["📈 기본 성과 대시보드", "🔎 H별 확정 Multiplier 분석", "📝 QuantStats 상세 분석 리포트"],
    )

    exp_path = os.path.join(results_dir, selected_exp)

    if view_mode == "🔎 H별 확정 Multiplier 분석":
        render_horizon_final_analysis(results_dir)
        return

    if view_mode == "📝 QuantStats 상세 분석 리포트":
        st.subheader("📊 QuantStats 상세 분석 보고서 (Tear Sheet)")

        qs_ew_path = os.path.join(exp_path, "quantstats_report.html")
        qs_krx_path = os.path.join(exp_path, "quantstats_report_krx.html")

        ew_exists = os.path.exists(qs_ew_path)
        krx_exists = os.path.exists(qs_krx_path)

        if not ew_exists and not krx_exists:
            st.warning(
                "⚠️ QuantStats 보고서 파일이 없습니다. 백테스트를 실행하면 자동으로 생성됩니다."
            )
            return

        # 두 벤치마크 보고서를 탭으로 나란히 표시
        tab_labels = []
        tab_paths = []
        if ew_exists:
            tab_labels.append("⚖️ vs 유니버스 EW B&H (알파 측정 기준)")
            tab_paths.append(qs_ew_path)
        if krx_exists:
            tab_labels.append("🇰🇷 vs 커스텀 KRX 통합 지수 (시장 기준)")
            tab_paths.append(qs_krx_path)

        tabs = st.tabs(tab_labels)
        for tab, path, label in zip(tabs, tab_paths, tab_labels):
            with tab:
                if "EW" in label:
                    st.info(
                        "📌 **벤치마크 해석**: 전략이 우리 유니버스 전 종목을 동일 비중으로 단순 보유했을 때 대비 **얼마나 더 나은 종목 선택 능력**을 보였는지 측정합니다. (학술적 알파 측정 기준)"
                    )
                else:
                    st.info(
                        "📌 **벤치마크 해석**: 전략이 코스피·코스닥 시장 전체 흐름(KOSPI+KOSDAQ 시가총액 가중 합산) 대비 **얼마나 더 나은 시장 초과 수익**을 냈는지 측정합니다. (직관적 시장 기준)"
                    )
                import streamlit.components.v1 as components

                with open(path, encoding="utf-8") as f:
                    html_content = f.read()
                components.html(html_content, height=1600, scrolling=True)
        return

    # ── [실험 설정 파싱 및 표기] ──
    # 실행 결과와 한 쌍인 snapshot을 최우선으로 사용한다. 없을 때만 로컬 템플릿을 탐색한다.
    config_candidates = [
        os.path.join(exp_path, "config_snapshot.yaml"),
        os.path.abspath(os.path.join(results_dir, "..", "..", "core", "config.yaml")),
        os.path.abspath(os.path.join(results_dir, "..", "..", "core", "config.example.yaml")),
        os.path.abspath(os.path.join(os.getcwd(), "config.yaml")),
        os.path.abspath(os.path.join(results_dir, "..", "configs", f"{selected_exp}.yaml")),
    ]
    config_path = None
    for p in config_candidates:
        if os.path.exists(p):
            config_path = p
            break

    config = {}
    if config_path and os.path.exists(config_path):
        try:
            import yaml

            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except Exception as e:
            st.warning(f"설정 파일을 불러오는 중 문제가 발생했습니다: {config_path} ({e})")
            config = {}

    if config:
        st.write("")  # 간격 띄우기
        with st.expander(
            "⚙️ 모델 하이퍼파라미터 & 백테스트 기준 정보 (Active Configuration)", expanded=False
        ):
            col_cfg1, col_cfg2, col_cfg3 = st.columns(3)
            with col_cfg1:
                st.markdown("#### 📊 데이터 및 분할 전략")
                st.write(f"- **데이터 시작일**: `{config.get('data', {}).get('start_date', '-')}`")
                st.write(f"- **데이터 종료일**: `{config.get('data', {}).get('end_date', '-')}`")
                st.write(f"- **분할 전략**: `{config.get('data', {}).get('split_strategy', '-')}`")
                if config.get("data", {}).get("split_strategy") == "sliding":
                    st.write(
                        f"  - `Train Window`: {config.get('data', {}).get('sliding', {}).get('train_window_years', '-')}년"
                    )
                    st.write(
                        f"  - `Test Window`: {config.get('data', {}).get('sliding', {}).get('test_window_years', '-')}년"
                    )

            with col_cfg2:
                st.markdown("#### 🤖 LightGBM 트리 모델 설정")
                model_params = config.get("model", {}).get("params", {})
                st.write(
                    f"- **트리 개수 (n_estimators)**: `{model_params.get('n_estimators', '-')}`"
                )
                st.write(
                    f"- **학습률 (learning_rate)**: `{model_params.get('learning_rate', '-')}`"
                )
                st.write(
                    f"- **최대 트리 깊이 (max_depth)**: `{model_params.get('max_depth', '-')}`"
                )
                st.write(
                    f"- **리프 노드 수 (num_leaves)**: `{model_params.get('num_leaves', '-')}`"
                )
                st.write(
                    f"- **최소 샘플 규제 (min_child_samples)**: `{model_params.get('min_child_samples', '-')}`"
                )

            with col_cfg3:
                st.markdown("#### 🛡️ 트레이딩 및 백테스트 기준")
                st.write(
                    f"- **최소 확률 컷 (prob_threshold)**: `{config.get('strategy', {}).get('prob_threshold', '-')}`"
                )
                st.write(
                    f"- **일일 선택 종목 수 (top_n)**: `{config.get('strategy', {}).get('top_n', '-')}개`"
                )
                st.write(
                    f"- **익절 배리어 승수 (up_mult)**: `{config.get('backtest', {}).get('up_mult', '-')}σ`"
                )
                st.write(
                    f"- **손절 배리어 승수 (down_mult)**: `{config.get('backtest', {}).get('down_mult', '-')}σ`"
                )
                st.write(
                    f"- **거래 비용 (수수료+세금)**: `{config.get('backtest', {}).get('fee', 0.0025) * 100:.3f}%` (편도)"
                )
    daily_returns_path = os.path.join(exp_path, "daily_returns.csv")
    trades_path = os.path.join(exp_path, "trades.csv")
    benchmark_metadata_path = os.path.join(exp_path, "benchmark_metadata.csv")

    if os.path.exists(daily_returns_path):
        ret_df = pd.read_csv(daily_returns_path)
        # 첫 번째 컬럼이 Date
        date_col = ret_df.columns[0]

        ret_df[date_col] = pd.to_datetime(ret_df[date_col], utc=True).dt.tz_localize(None)
        ret_df.set_index(date_col, inplace=True)

        # ----------------------------------------------------
        # 1. 누적 수익률 차트
        # ----------------------------------------------------
        st.subheader("1. 누적 수익률 곡선 (Cumulative Equity Curve)")

        if os.path.exists(benchmark_metadata_path):
            try:
                benchmark_meta = pd.read_csv(benchmark_metadata_path)
                if not benchmark_meta.empty:
                    meta_row = benchmark_meta.iloc[0].to_dict()
                    valid = meta_row.get("valid", True)
                    source = meta_row.get("source", "unknown")
                    reason = meta_row.get("reason", "")
                    validity_reason = meta_row.get("validity_reason", "")
                    if str(valid).lower() in {"false", "0", "nan"}:
                        st.warning(
                            f"Benchmark source: `{source}` / invalid: {validity_reason or reason}"
                        )
                    else:
                        st.info(f"Benchmark source: `{source}` / {reason}")
            except Exception as e:
                st.warning(f"benchmark_metadata.csv 로드 실패: {e}")

        portfolio_col = "Portfolio" if "Portfolio" in ret_df.columns else ret_df.columns[0]
        ret_series = ret_df[portfolio_col]
        cum_ret = (1 + ret_series).cumprod()

        plot_df = pd.DataFrame({"📈 전략 (LGBM 스윙)": cum_ret})

        # 신규 컬럼 포맷 (Benchmark_EW + Benchmark_CustomKRX)
        if "Benchmark_EW" in ret_df.columns:
            plot_df["⚖️ 유니버스 EW B&H (알파 측정 기준)"] = (1 + ret_df["Benchmark_EW"]).cumprod()
        if "Benchmark_CustomKRX" in ret_df.columns:
            plot_df["🇰🇷 커스텀 KRX 통합 지수 (시장 기준)"] = (
                1 + ret_df["Benchmark_CustomKRX"]
            ).cumprod()
        # 구버전 호환 (Benchmark 단일 컬럼)
        elif "Benchmark" in ret_df.columns and "Benchmark_EW" not in ret_df.columns:
            plot_df["📊 벤치마크"] = (1 + ret_df["Benchmark"]).cumprod()

        fig = px.line(plot_df, title=f"[{selected_exp}] 전략 vs 벤치마크 누적 수익률 비교")
        fig.update_layout(
            yaxis_title="누적 수익률 (1.0 = 0%)",
            xaxis_title="날짜",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
        )
        # 색상: 전략=에메랄드, EW=하늘색 점선, KRX=주황색 점선
        for trace in fig.data:
            if "전략" in trace.name:
                trace.line.update(color="#00b894", width=3)
            elif "EW" in trace.name:
                trace.line.update(color="#74b9ff", width=2, dash="dot")
            elif "KRX" in trace.name:
                trace.line.update(color="#fdcb6e", width=2, dash="dash")
            else:
                trace.line.update(color="#95a5a6", width=2, dash="dash")

        st.plotly_chart(fig, use_container_width=True)

        # ── 커스텀 KRX 통합 지수 방법론 설명 패널 ──
        if "Benchmark_CustomKRX" in ret_df.columns:
            with st.expander(
                "📐 커스텀 KRX 통합 지수 산출 방법론 (클릭하여 펼치기)", expanded=False
            ):
                st.markdown("""
#### 🇰🇷 커스텀 KRX 통합 지수 (Custom KRX Composite Index)란?

한국거래소(KRX)는 코스피와 코스닥을 통합한 **KRX TMI(Total Market Index)**를 2025년 1월 발표했으나,
백테스트 기간(2019~2025년) 전체를 커버하는 역사적 데이터가 아직 없습니다.
이에 아래의 논리적 절차에 따라 **직접 합성한 통합 지수**를 벤치마크로 사용합니다.

---

#### 📐 산출 공식

$$R_{composite, t} = w_{KOSPI, y} \\times R_{KOSPI, t} \\quad + \\quad w_{KOSDAQ, y} \\times R_{KOSDAQ, t}$$

- $R_{KOSPI, t}$: KOSPI 종합지수(^KS11) 일별 수익률
- $R_{KOSDAQ, t}$: KOSDAQ 종합지수(^KQ11) 일별 수익률
- $w_{KOSPI, y}$, $w_{KOSDAQ, y}$: 해당 연도($y$)의 연평균 시가총액 비중

---

#### 📊 연도별 적용 가중치 (KRX 시장 통계 연보 기준)
""")
                weight_data = {
                    "연도": [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
                    "KOSPI 비중 (%)": [84, 84, 83, 83, 80, 78, 80, 82, 83, 83],
                    "KOSDAQ 비중 (%)": [16, 16, 17, 17, 20, 22, 20, 18, 17, 17],
                    "비고": [
                        "",
                        "",
                        "",
                        "",
                        "코로나 이후 코스닥 급등",
                        "코스닥 버블 피크",
                        "고금리 충격 이후 조정",
                        "",
                        "",
                        "잠정치",
                    ],
                }
                st.dataframe(pd.DataFrame(weight_data), use_container_width=True, hide_index=True)

                st.info("""
💡 **벤치마크 선정 근거 (벤치마크 선택 기준 4원칙)**
- **투자 가능성(Investable)**: KOSPI ETF + KOSDAQ ETF를 해당 비중으로 매수하면 실제 복제 가능
- **스타일 일치성(Style Consistent)**: 우리 전략은 코스피·코스닥 전 종목 롱온리 → 두 시장 통합이 적합
- **사전 정의성(Pre-specified)**: 백테스트 실행 전 가중치 방법론을 코드에 명시하여 사후 선택(Cherry-picking) 방지
- **출처 신뢰성**: 한국거래소(KRX) 공식 시장 통계 연보 (krx.co.kr) 기반
""")

        # ----------------------------------------------------
        # 2. 월별 수익률 히트맵 & 매크로 이벤트
        # ----------------------------------------------------
        st.subheader("2. 월별 성과 히트맵 (Monthly Heatmap) & 매크로 국면")

        col1, col2 = st.columns([2, 1])

        with col1:
            monthly_pivot = get_monthly_returns(ret_series)

            for m in range(1, 13):
                if m not in monthly_pivot.columns:
                    monthly_pivot[m] = np.nan
            monthly_pivot = monthly_pivot[range(1, 13)]

            fig_hm = go.Figure(
                data=go.Heatmap(
                    z=monthly_pivot.values * 100,
                    x=[calendar.month_abbr[m] for m in range(1, 13)],
                    y=monthly_pivot.index,
                    colorscale="RdYlGn",
                    zmid=0,
                    text=np.round(monthly_pivot.values * 100, 2),
                    texttemplate="%{text}%",
                    hoverinfo="z",
                )
            )
            fig_hm.update_layout(
                yaxis_autorange="reversed", height=400, margin=dict(t=30, l=10, r=10, b=10)
            )
            st.plotly_chart(fig_hm, use_container_width=True)

        with col2:
            st.markdown("### 📰 핵심 거시경제 타임라인")
            event_df = pd.DataFrame(
                list(MACRO_EVENTS.items()), columns=["Date (YYYY-MM)", "Macro Event"]
            )
            st.dataframe(event_df, height=350, use_container_width=True)
            st.info(
                "💡 **리버스 엔지니어링 TIP**\n히트맵에서 파랗게 깨진(손실) 월을 찾고, 우측의 매크로 타임라인과 대조해 보세요. '아, 우리 모델이 금리 인상 충격(22년 9월)에는 버티지 못하는구나!' 같은 정성적 분석이 가능해집니다."
            )

    else:
        st.error(f"일일 수익률 데이터가 없습니다: {daily_returns_path}")

    if os.path.exists(trades_path):
        st.subheader("3. 돋보기: 상세 매매 일지 (Trade Logs)")
        trades_df = pd.read_csv(trades_path)

        if len(trades_df) > 0:
            # 종목 코드 메타데이터 로드하여 한글 종목명 매핑
            metadata_candidates = [
                os.path.abspath(
                    os.path.join(current_dir, "..", "..", "data", "ticker_metadata.csv")
                ),  # backend/analysis/chart/data
                os.path.abspath(
                    os.path.join(
                        current_dir, "..", "..", "..", "..", "..", "data", "ticker_metadata.csv"
                    )
                ),  # 레포 루트 data/ (result_dashboard에서 5단계 위)
                os.path.abspath(os.path.join(os.getcwd(), "data", "ticker_metadata.csv")),
                os.path.abspath(os.path.join(current_dir, "..", "data", "ticker_metadata.csv")),
            ]
            metadata_path = None
            for p in metadata_candidates:
                if os.path.exists(p):
                    metadata_path = p
                    break

            ticker_map = {}
            delisted_map = {}
            if metadata_path and os.path.exists(metadata_path):
                try:
                    meta_df = pd.read_csv(metadata_path, dtype={"Code": str})
                    ticker_map = dict(zip(meta_df["Code"], meta_df["Name"]))
                    delisted_map = dict(zip(meta_df["Code"], meta_df["IsDelisted"]))
                except Exception as e:
                    st.warning(f"종목 메타데이터 로드에 실패했습니다: {e}")

            # 1. KOSPI & KOSDAQ 시장 구분 정보 실시간 로드 및 캐싱
            @st.cache_data(ttl=3600)
            def load_market_info():
                kospi_set, kosdaq_set = set(), set()
                try:
                    import FinanceDataReader as fdr

                    kospi_df = fdr.StockListing("KOSPI")
                    kosdaq_df = fdr.StockListing("KOSDAQ")
                    kospi_set = set(kospi_df["Code"].astype(str).str.zfill(6).tolist())
                    kosdaq_set = set(kosdaq_df["Code"].astype(str).str.zfill(6).tolist())
                except Exception as e:
                    st.warning(f"시장 구분 정보 로드 실패(기본값 사용): {e}")
                return kospi_set, kosdaq_set

            kospi_set, kosdaq_set = load_market_info()

            def extract_code(col_str):
                if not isinstance(col_str, str):
                    return str(col_str)
                import ast

                try:
                    parsed = ast.literal_eval(col_str)
                    if isinstance(parsed, tuple):
                        return parsed[0]
                    else:
                        return str(parsed)
                except (ValueError, SyntaxError):
                    return (
                        col_str.replace("'", "")
                        .replace('"', "")
                        .replace("(", "")
                        .replace(")", "")
                        .split(",")[0]
                        .strip()
                    )

            def get_market_label(col_str):
                code = extract_code(col_str)
                # 오프라인 상태 (데이터를 로드하지 못한 경우)
                if not kospi_set and not kosdaq_set:
                    return "미분류 (오프라인)"

                if code in kospi_set:
                    return "코스피"
                elif code in kosdaq_set:
                    return "코스닥"
                elif delisted_map.get(code, False):
                    return "상장폐지"
                else:
                    return "기타"

            def map_code_to_name(col_str):
                code = extract_code(col_str)
                name = ticker_map.get(code, "")
                if name:
                    return f"{code} ({name})"
                return code

            # 중요 컬럼만 필터링해서 보여주기 (VectorBT 구조 반영)
            display_cols = []
            target_cols = [
                "Entry Timestamp",
                "Exit Timestamp",
                "Column",
                "Direction",
                "Size",
                "Entry Price",
                "Avg Entry Price",
                "Exit Price",
                "Avg Exit Price",
                "Return",
                "PnL",
            ]
            for c in target_cols:
                if c in trades_df.columns:
                    display_cols.append(c)

            if display_cols:
                filtered_df = trades_df[display_cols].copy()

                # 시장 구분 컬럼 생성
                if "Column" in filtered_df.columns:
                    filtered_df["시장"] = filtered_df["Column"].apply(get_market_label)

                # Column 컬럼 한글 종목명 변환 적용
                if "Column" in filtered_df.columns:
                    filtered_df["Column"] = filtered_df["Column"].apply(map_code_to_name)

                # 시계열 형식 변환
                if "Entry Timestamp" in filtered_df.columns:
                    filtered_df["Entry Timestamp"] = pd.to_datetime(filtered_df["Entry Timestamp"])
                if "Exit Timestamp" in filtered_df.columns:
                    filtered_df["Exit Timestamp"] = pd.to_datetime(filtered_df["Exit Timestamp"])

                # 1. 청산 구분 (Exit Reason) 상세 판정 로직 적용
                def deduce_exit_reason(row):
                    try:
                        entry_t = pd.to_datetime(row["Entry Timestamp"])
                        exit_t = pd.to_datetime(row["Exit Timestamp"])

                        # 실제 영업일 계산 (ret_df index 활용)
                        if "ret_df" in locals() or "ret_df" in globals():
                            days_held = len([d for d in ret_df.index if entry_t <= d <= exit_t]) - 1
                        else:
                            # fallback: 주말 감안한 영업일 추정
                            days_held = int((exit_t - entry_t).days * 5 / 7)
                    except Exception:
                        days_held = 0

                    ret_pct = row["Return"] * 100

                    # 만기 청산 우선 판정 (5영업일 이상 보유 시)
                    if days_held >= 5:
                        if ret_pct >= 0.5:
                            return "만기 청산 (익절 마감)"
                        elif ret_pct <= -0.5:
                            return "만기 청산 (손절 마감)"
                        else:
                            return "만기 청산 (횡보 마감)"

                    # 장중 터치 판정
                    if ret_pct > 0:
                        return "상방 배리어 터치 (익절)"
                    else:
                        # 손실율이 5%보다 크면 강제손절(Hard SL)로 분류
                        if ret_pct < -5.0:
                            return "하방 배리어 터치 (강제 손절)"
                        else:
                            return "하방 배리어 터치 (손절)"

                filtered_df["청산 구분"] = filtered_df.apply(deduce_exit_reason, axis=1)

                # 2. 총 투자금액(원) 계산
                entry_price_col = (
                    "Avg Entry Price"
                    if "Avg Entry Price" in filtered_df.columns
                    else ("Entry Price" if "Entry Price" in filtered_df.columns else None)
                )
                if entry_price_col and "Size" in filtered_df.columns:
                    filtered_df["총 투자금액(원)"] = (
                        (filtered_df[entry_price_col] * filtered_df["Size"]).round(0).astype(int)
                    )

                # Direction 한글 변환
                if "Direction" in filtered_df.columns:
                    filtered_df["Direction"] = (
                        filtered_df["Direction"]
                        .map({"Long": "매수 (Long)", "Short": "매도 (Short)"})
                        .fillna(filtered_df["Direction"])
                    )

                # 수익률 백분율 변환
                if "Return" in filtered_df.columns:
                    filtered_df["Return"] = (filtered_df["Return"] * 100).round(2)

                # 컬럼명 직관적인 한글로 매핑
                rename_map = {
                    "Entry Timestamp": "진입일시",
                    "Exit Timestamp": "청산일시",
                    "Column": "종목",
                    "Direction": "포지션",
                    "Size": "거래수량(주)",
                    "Entry Price": "주당 진입가격(원)",
                    "Avg Entry Price": "주당 진입가격(원)",
                    "Exit Price": "주당 청산가격(원)",
                    "Avg Exit Price": "주당 청산가격(원)",
                    "Return": "수익률(%)",
                    "PnL": "실현손익(원)",
                }
                filtered_df.rename(columns=rename_map, inplace=True)

                # 중복 컬럼 제거 (혹시 둘 다 리스트에 들어가서 이름이 겹친 경우 제거)
                filtered_df = filtered_df.loc[:, ~filtered_df.columns.duplicated()]

                # 실현손익 반올림
                if "실현손익(원)" in filtered_df.columns:
                    filtered_df["실현손익(원)"] = filtered_df["실현손익(원)"].round(0).astype(int)

                # 출력 순서 정렬 (시장 컬럼 추가)
                column_order = [
                    "진입일시",
                    "청산일시",
                    "종목",
                    "시장",
                    "포지션",
                    "거래수량(주)",
                    "주당 진입가격(원)",
                    "주당 청산가격(원)",
                    "총 투자금액(원)",
                    "수익률(%)",
                    "실현손익(원)",
                    "청산 구분",
                ]
                # 컬럼이 다 있는지 안전 검증 후 필터링
                actual_order = [col for col in column_order if col in filtered_df.columns]
                filtered_df = filtered_df[actual_order]

                # Streamlit 프리미엄 컬럼 설정 (st.column_config) 적용하여 시각화 극대화
                st.dataframe(
                    filtered_df.sort_values("진입일시", ascending=False),
                    use_container_width=True,
                    height=350,
                    column_config={
                        "진입일시": st.column_config.DatetimeColumn(
                            "진입일시", format="YYYY-MM-DD"
                        ),
                        "청산일시": st.column_config.DatetimeColumn(
                            "청산일시", format="YYYY-MM-DD"
                        ),
                        "종목": st.column_config.TextColumn("종목"),
                        "시장": st.column_config.TextColumn("시장"),
                        "포지션": st.column_config.TextColumn("포지션"),
                        "거래수량(주)": st.column_config.NumberColumn(
                            "거래수량(주)", format="%.2f"
                        ),
                        "주당 진입가격(원)": st.column_config.NumberColumn(
                            "주당 진입가격(원)", format="₩%,d"
                        ),
                        "주당 청산가격(원)": st.column_config.NumberColumn(
                            "주당 청산가격(원)", format="₩%,d"
                        ),
                        "총 투자금액(원)": st.column_config.NumberColumn(
                            "총 투자금액(원)", format="₩%,d"
                        ),
                        "수익률(%)": st.column_config.NumberColumn("수익률(%)", format="%.2f%%"),
                        "실현손익(원)": st.column_config.NumberColumn(
                            "실현손익(원)", format="₩%,d"
                        ),
                        "청산 구분": st.column_config.TextColumn("청산 구분"),
                    },
                )
            else:
                st.dataframe(trades_df, use_container_width=True)

            st.success(f"총 {len(trades_df)} 번의 단기 스윙 거래가 발생했습니다.")
        else:
            st.write("진입한 거래가 없습니다.")

    # ----------------------------------------------------
    # 4. 🤖 AI 모델 분석: 피처 중요도 (Feature Importance)
    # ----------------------------------------------------
    st.subheader("4. 🤖 AI 모델 분석: 피처 중요도 (Feature Importance)")

    # 모델 캐시 폴더 경로 지정
    models_cache_dir = model_cache_dir(__file__)

    if config:
        try:
            # 1) 폴드 목록 및 predictions_hash 계산
            resolved_splits = resolve_splits(config)
            pred_hash = generate_predictions_hash(config, resolved_splits)

            # 2) 해당 hash를 가지는 모든 fold 모델 검색
            model_files = []
            if os.path.exists(models_cache_dir):
                model_files = [
                    os.path.join(models_cache_dir, f)
                    for f in os.listdir(models_cache_dir)
                    if f.startswith(pred_hash) and f.endswith("_model.txt")
                ]

            if model_files:
                import lightgbm as lgb

                st.markdown(
                    f"현재 활성화된 실험 설정(`{pred_hash}`)에 대해 총 **{len(model_files)}개**의 교차검증(Fold) 모델을 캐시에서 로드하여 피처 기여도(Feature Importance)를 분석합니다."
                )

                # 모든 폴드 모델의 feature importance 누적
                importance_list = []
                feature_names = None

                for m_path in model_files:
                    booster = lgb.Booster(model_file=m_path)
                    # gain 방식 피처 중요도 측정
                    importances = booster.feature_importance(importance_type="gain")
                    names = booster.feature_name()

                    if feature_names is None:
                        feature_names = names

                    importance_list.append(importances)

                # 평균 피처 중요도 계산
                avg_importances = np.mean(importance_list, axis=0)

                # 데이터프레임 빌드
                fi_df = pd.DataFrame(
                    {"Feature": feature_names, "Importance (Gain)": avg_importances}
                )

                # 중요도 총합으로 정규화하여 기여도 비율(%) 계산
                total_gain = fi_df["Importance (Gain)"].sum()
                if total_gain > 0:
                    fi_df["Contribution (%)"] = (fi_df["Importance (Gain)"] / total_gain) * 100
                else:
                    fi_df["Contribution (%)"] = 0.0

                # 정렬 및 필터링
                fi_df = fi_df.sort_values("Importance (Gain)", ascending=False).reset_index(
                    drop=True
                )

                # 피처 설명 추가 (마우스 오버 툴팁 용도)
                def get_feature_desc(fname):
                    fname = str(fname).lower()
                    if "std" in fname and "vstd" not in fname:
                        return "주가 변동성 (표준편차) - 단기 상/하방 배리어 터치 확률에 핵심 영향"
                    elif "vstd" in fname:
                        return "거래량 변동성 - 시장의 거래 활성도 변화량"
                    elif "wvma" in fname:
                        return "거래량 가중 이평선 - 거래량이 동반된 추세 강도 확인"
                    elif "vma" in fname:
                        return "단순 거래량 이평선"
                    elif "rsqr" in fname:
                        return "추세 강도 (결정계수 R²) - 주가가 노이즈 없이 선형적으로 추세를 탔는지 평가"
                    elif "klen" in fname:
                        return "캔들스틱 바디 길이 - 시가와 종가의 차이 (매수/매도 압력)"
                    elif "max" in fname:
                        return "최근 N일 고점 (최고가)"
                    elif "min" in fname:
                        return "최근 N일 저점 (최저가)"
                    elif "beta" in fname:
                        return "시장 베타 - 벤치마크 지수 대비 개별 종목의 민감도"
                    elif "kmid" in fname or "kup" in fname or "klow" in fname or "ksft" in fname:
                        return "K-라인(캔들스틱) 형태적 패턴 분류 지표"
                    elif "roc" in fname:
                        return "가격 변화율 (Rate of Change)"
                    elif "macd" in fname:
                        return "MACD - 단기 및 장기 이동평균 간의 관계 (추세 전환)"
                    elif "change" in fname:
                        return "일일 주가 변동률"
                    return "알파(Alpha) 기술적 지표"

                fi_df["Description"] = fi_df["Feature"].apply(get_feature_desc)

                # 사용자 친화적인 피처 수 선택 슬라이더
                top_n_display = st.slider(
                    "표시할 상위 피처 개수를 선택하세요:",
                    min_value=5,
                    max_value=50,
                    value=20,
                    step=5,
                )

                top_fi = fi_df.head(top_n_display).copy()

                # 시각화 (수평 바차트)
                fig_fi = px.bar(
                    top_fi,
                    x="Importance (Gain)",
                    y="Feature",
                    orientation="h",
                    title=f"Top {top_n_display} Feature Importance (Average of {len(model_files)} Folds by Information Gain)",
                    labels={
                        "Importance (Gain)": "Information Gain (정밀도/손실감소 기여도)",
                        "Feature": "피처명",
                    },
                    color="Importance (Gain)",
                    color_continuous_scale=[
                        [0, "rgba(0, 184, 148, 0.3)"],
                        [1, "rgba(0, 184, 148, 1.0)"],
                    ],  # 에메랄드 톤
                    hover_data={"Description": True, "Contribution (%)": ":.2f"},
                )

                fig_fi.update_layout(
                    yaxis={"categoryorder": "total ascending"},
                    height=150 + top_n_display * 20,
                    margin=dict(l=150, r=20, t=40, b=40),
                    coloraxis_showscale=False,
                )

                st.plotly_chart(fig_fi, use_container_width=True)

                # 피처 중요도 상위 표 및 설명
                col_fi1, col_fi2 = st.columns([1, 1])
                with col_fi1:
                    st.markdown("##### 🏆 피처 중요도 순위 목록 (Top 10)")
                    st.dataframe(
                        fi_df.head(10)[
                            ["Feature", "Importance (Gain)", "Contribution (%)"]
                        ].style.format(
                            {"Importance (Gain)": "{:,.1f}", "Contribution (%)": "{:.2f}%"}
                        ),
                        use_container_width=True,
                    )
                with col_fi2:
                    st.markdown("##### 💡 퀀트 모델 관점의 피처 해석 가이드")
                    st.info(
                        "1. **`std_20`, `std_10` (변동성 지표)**\n"
                        "   - 당사의 3배리어(Triple Barrier) 라벨은 상방 터치 여부를 판별합니다.\n"
                        "   - 주가 변동성(Standard Deviation)이 높을수록, 단기 내에 상방(또는 하방) 배리어 터치 확률이 극대화되므로 모델 의사결정에 극히 핵심적인 역할을 수행합니다.\n\n"
                        "2. **`wvma_20`, `vma_20` (거래량 가중/이동평균 지표)**\n"
                        "   - 단순 주가 흐름뿐만 아니라 거래량이 수반된 돌파/변동성 증가인지 판단하는 핵심 시그널입니다.\n\n"
                        "3. **`rsqr_20` (추세의 일관성/결정계수)**\n"
                        "   - 20일간의 주가 흐름이 얼마나 노이즈 없이 선형적 추세를 보였는지를 반영하며, 가속 돌파 판별에 기여합니다."
                    )

                # ── 의사결정 규칙(Decision Rules) 및 트리 시각화 분석 섹션 신설 ──
                st.markdown("---")
                st.markdown("#### 🔍 5. 🌳 AI 모델 의사결정 규칙(Decision Rules) 돋보기")

                # 1) 폴드 선택 (여러 폴드가 있을 수 있으므로 첫번째 폴드 기본값)
                selected_fold_idx = st.selectbox(
                    "분석할 교차검증 모델(Fold)을 선택하세요:",
                    range(len(model_files)),
                    format_func=lambda idx: (
                        f"Fold {idx + 1} 모델 ({os.path.basename(model_files[idx])})"
                    ),
                )

                # 선택된 모델 로드
                selected_booster = lgb.Booster(model_file=model_files[selected_fold_idx])
                model_dict = selected_booster.dump_model()
                feature_names = selected_booster.feature_name()

                tab1, tab2 = st.tabs(
                    [
                        "📊 피처별 분기 임계점(Threshold) 분포 분석",
                        "🌳 개별 의사결정 나무(Tree) 구조 분석",
                    ]
                )

                with tab1:
                    st.markdown("##### 💡 피처별 의사결정 임계점(Threshold) 추출기")
                    st.markdown(
                        "특정 피처를 선택하면, 전체 의사결정나무 숲(Forest) 내에서 해당 피처가 **실제 어떤 수치들을 기준으로 분기되었는지** 모든 임계점을 추출하여 분포를 분석합니다."
                    )

                    # 피처 선택 (중요도 상위 피처들 중 선택)
                    top_features_list = fi_df["Feature"].head(30).tolist()
                    selected_feature = st.selectbox("분석할 피처를 선택하세요:", top_features_list)

                    # 분기 기준값(Threshold) 추출 함수
                    def extract_thresholds(node, target_feat, feat_names):
                        thrs = []
                        if not node or "leaf_value" in node:
                            return thrs
                        feat_idx = node.get("split_feature")
                        feat_name = (
                            feat_names[feat_idx]
                            if feat_idx < len(feat_names)
                            else f"Feature_{feat_idx}"
                        )
                        if feat_name == target_feat:
                            thrs.append(node.get("threshold"))
                        if "left_child" in node:
                            thrs.extend(
                                extract_thresholds(node["left_child"], target_feat, feat_names)
                            )
                        if "right_child" in node:
                            thrs.extend(
                                extract_thresholds(node["right_child"], target_feat, feat_names)
                            )
                        return thrs

                    all_thresholds = []
                    for tree in model_dict.get("tree_info", []):
                        all_thresholds.extend(
                            extract_thresholds(
                                tree.get("tree_structure", {}), selected_feature, feature_names
                            )
                        )

                    if all_thresholds:
                        st.success(
                            f"선택한 피처 `{selected_feature}`는 전체 {len(model_dict.get('tree_info', []))}개의 나무 중에서 **총 {len(all_thresholds)}번** 분기 기준으로 사용되었습니다."
                        )

                        # 통계 요약
                        th_series = pd.Series(all_thresholds)
                        col_stat1, col_stat2, col_stat3 = st.columns(3)
                        col_stat1.metric("평균 분기 임계값", f"{th_series.mean():.5f}")
                        col_stat2.metric("최솟값 (Min Threshold)", f"{th_series.min():.5f}")
                        col_stat3.metric("최댓값 (Max Threshold)", f"{th_series.max():.5f}")

                        # 히스토그램 시각화
                        fig_th = px.histogram(
                            th_series,
                            nbins=20,
                            title=f"`{selected_feature}` 피처의 의사결정 임계점(Threshold) 분포",
                            labels={"value": "분기 임계값(Threshold)", "count": "출현 빈도"},
                            color_discrete_sequence=["#00b894"],
                        )
                        fig_th.update_layout(
                            xaxis_title="분기 기준값 (Threshold)",
                            yaxis_title="출현 빈도 (번)",
                            showlegend=False,
                        )
                        st.plotly_chart(fig_th, use_container_width=True)

                        st.markdown(
                            "💡 **차트 해석 가이드**: 그래프에서 빈도가 가장 높은 구간(피크 지점)은 AI 모델이 이 종목의 상태(익절/손절)를 가르는 데 **가장 중요하게 생각하는 최적의 기준선**입니다. 이 임계값 전후로 전략의 매수 신호 강도가 어떻게 변할지 정성적으로 유추할 수 있습니다."
                        )
                    else:
                        st.warning(
                            f"선택한 피처 `{selected_feature}`는 현재 Fold 모델의 트리 분기점에서 단 한 번도 사용되지 않았습니다."
                        )

                with tab2:
                    st.markdown("##### 🌳 개별 의사결정 나무(Tree) 구조 직접 뜯어보기")
                    st.markdown(
                        "LGBM 앙상블을 구성하는 개별 나무들의 구조와 판단 규칙을 텍스트 기반 계층형 구조로 투명하게 출력합니다."
                    )

                    num_trees = len(model_dict.get("tree_info", []))
                    selected_tree_idx = st.number_input(
                        f"조회할 나무 번호를 입력하세요 (0 ~ {num_trees - 1}):",
                        min_value=0,
                        max_value=num_trees - 1,
                        value=0,
                    )

                    # 재귀적 트리 포맷터
                    def render_text_tree(node, feat_names, depth=0):
                        indent = "&nbsp;&nbsp;" * (depth * 2)
                        if not node:
                            return ""
                        if "leaf_value" in node:
                            return f"{indent}➡️ <span style='color:#0984e3; font-weight:bold;'>[Leaf] 예측 값: {node['leaf_value']:.5f}</span><br>"

                        feat_idx = node.get("split_feature")
                        feat_name = (
                            feat_names[feat_idx]
                            if feat_idx < len(feat_names)
                            else f"Feature_{feat_idx}"
                        )
                        threshold = node.get("threshold")

                        left_str = render_text_tree(node.get("left_child"), feat_names, depth + 1)
                        right_str = render_text_tree(node.get("right_child"), feat_names, depth + 1)

                        node_str = (
                            f"{indent}<span style='color:#2d3436; font-weight:bold;'>🔹 {feat_name} &le; {threshold:.5f}</span><br>"
                            f"{left_str}"
                            f"{indent}<span style='color:#2d3436; font-weight:bold;'>🔸 {feat_name} &gt; {threshold:.5f}</span><br>"
                            f"{right_str}"
                        )
                        return node_str

                    target_tree = model_dict["tree_info"][selected_tree_idx]["tree_structure"]
                    tree_html = render_text_tree(target_tree, feature_names)

                    st.markdown(
                        f"<div style='background-color:#f5f6fa; padding:15px; border-radius:8px; border:1px solid #dcdde1; max-height:400px; overflow-y:scroll; font-family:monospace; line-height:1.5;'>{tree_html}</div>",
                        unsafe_allow_html=True,
                    )

            else:
                st.warning(
                    f"⚠️ 활성화된 설정(`{pred_hash}`)에 매칭되는 학습된 모델 파일(`.txt`)을 `{models_cache_dir}`에서 찾을 수 없습니다.\n"
                    f"학습 캐시를 건너뛰지 않고 실험을 한 번도 실행하지 않았거나, 모델 파일이 손실되었을 수 있습니다."
                )
        except Exception as e:
            st.error(f"피처 중요도 분석 중 오류 발생: {str(e)}")
    else:
        st.warning("실험 설정을 읽어오지 못했습니다.")


if __name__ == "__main__":
    main()

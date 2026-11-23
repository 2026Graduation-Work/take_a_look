import os

import pandas as pd


def generate_markdown_report(
    config: dict,
    summary_metrics: dict,
    model_metrics_df: pd.DataFrame,
    calibration_df: pd.DataFrame,
    backtest_metrics_df: pd.DataFrame,
    backtest_by_year_df: pd.DataFrame,
    benchmark_comparison_df: pd.DataFrame,
    output_path: str,
) -> None:
    exp_name = config.get("experiment_name", "default_exp")
    desc = config.get("description", "설명 없음")

    md = []
    md.append(f"# 실험 결과 분석 보고서: {exp_name}")
    md.append(f"**실험 설명**: {desc}\n")
    md.append("## 1. 실험 설정 (Experiment Configuration)\n")

    data_cfg = config.get("data", {})
    labels_cfg = config.get("labels", {})
    strat_cfg = config.get("strategy", {})
    bt_cfg = config.get("backtest", {})

    md.append("| 항목 | 설정값 |")
    md.append("| :--- | :--- |")
    md.append(f"| 유니버스 (Universe) | {data_cfg.get('universe', 'N/A')} |")
    md.append(f"| 시작 및 종료일 | {data_cfg.get('start_date', 'N/A')} ~ {data_cfg.get('end_date', 'N/A')} |")
    md.append(f"| 데이터 분할 전략 | {data_cfg.get('split_strategy', 'N/A')} (Embargo: {data_cfg.get('embargo_days', 7)}일) |")
    md.append(f"| 라벨링 타겟 (Target) | {labels_cfg.get('type', 'N/A')} (Horizon: {labels_cfg.get('horizon', 5)}일) |")
    md.append(f"| 진입 기준 임계값 | {strat_cfg.get('prob_threshold', 0.5)} (Top N: {strat_cfg.get('top_n', 5)}) |")
    md.append(f"| 거래 비용 (Fee) | 편도 {bt_cfg.get('fee', 0.0025) * 100:.3f}% |")
    md.append(f"| 최대 포지션 보유일 | {bt_cfg.get('max_holding_days', 5)}일 |\n")

    md.append("## 2. 종합 성과 요약 (Overall Performance Summary)\n")
    md.append("전체 Out-of-Sample 테스트 기간 동안 집계된 핵심 ML 및 트레이딩 성과 요약입니다.\n")

    md.append("### 머신러닝 지표 (ML Evaluation)")
    md.append("| Metric | Value |")
    md.append("| :--- | :--- |")
    for k in ["accuracy", "balanced_accuracy", "macro_f1", "roc_auc", "pr_auc", "brier_score"]:
        val = summary_metrics.get(f"ml_{k}", "N/A")
        val_str = f"{val:.4f}" if isinstance(val, float) else str(val)
        md.append(f"| {k.replace('_', ' ').title()} | {val_str} |")
    md.append("")

    md.append("### 트레이딩 지표 (Trading Performance)")
    md.append("| Metric | Value |")
    md.append("| :--- | :--- |")
    for k in ["total_return", "cagr", "annualized_volatility", "sharpe_ratio", "sortino_ratio", "max_drawdown", "win_rate", "payoff_ratio", "profit_factor", "number_of_trades", "average_holding_days"]:
        val = summary_metrics.get(f"trade_{k}", "N/A")
        if isinstance(val, float):
            if k in ["total_return", "cagr", "annualized_volatility", "max_drawdown", "win_rate"]:
                val_str = f"{val * 100:.2f}%"
            else:
                val_str = f"{val:.4f}"
        else:
            val_str = str(val)
        md.append(f"| {k.replace('_', ' ').title()} | {val_str} |")
    md.append("")

    md.append("## 3. 벤치마크 대비 성능 (Benchmark Comparison)\n")
    md.append("단순 벤치마크 전략들과의 성능 비교표입니다. (부트스트랩된 Random 전략의 경우 평균값 및 신뢰구간이 표시됩니다.)\n")
    md.append(benchmark_comparison_df.to_markdown(index=False))
    md.append("")

    md.append("## 4. 연도별 성능 추이 (Yearly Performance Trend)\n")
    md.append("수익률 및 Sharpe Ratio의 연도별 안정성 분포입니다.\n")
    md.append(backtest_by_year_df.to_markdown(index=False))
    md.append("")

    md.append("## 5. 폴드별 세부 분석 (Fold-by-Fold Detailed Analysis)\n")
    md.append("### 폴드별 머신러닝 성능")
    md.append(model_metrics_df.to_markdown(index=False))
    md.append("\n### 폴드별 백테스트 성과")
    md.append(backtest_metrics_df.to_markdown(index=False))
    md.append("")

    md.append("## 6. 확률 캘리브레이션 분석 (Probability Calibration Analysis)\n")
    md.append("모델이 예측한 확률 구간에 속한 샘플들의 실제 Up Class(상승 성공) 비율 분석입니다. "
              "모델 예측의 신뢰도를 판별할 수 있습니다.\n")
    md.append(calibration_df.to_markdown(index=False))
    md.append("")

    md.append("## 7. 결론 및 향후 실험 제안 (Conclusion & Action Items)\n")

    sharpe = summary_metrics.get("trade_sharpe_ratio", 0.0)
    mdd = summary_metrics.get("trade_max_drawdown", 0.0)

    md.append("### 주요 평가 포인트")
    if sharpe > 1.0:
        md.append(f"- **성능 평가**: Sharpe Ratio가 `{sharpe:.2f}`로 우수한 수준입니다.")
    elif sharpe > 0.0:
        md.append(f"- **성능 평가**: Sharpe Ratio가 `{sharpe:.2f}`로 양수이나, 개선의 여지가 있습니다.")
    else:
        md.append(f"- **성능 평가**: Sharpe Ratio가 `{sharpe:.2f}`로 음수 성과를 보였습니다. 모델 피처 또는 라벨 변경이 필요합니다.")

    md.append(f"- **리스크**: 최대 낙폭(MDD)은 `{mdd*100:.2f}%`입니다.")

    md.append("\n### 향후 Action Items")
    md.append("1. **Barrier Parameter 조정**: Dynamic Sigma 배수를 조정하여 익절/손절 컷의 최적 지점을 재탐색합니다.")
    md.append("2. **Rank Target 도입**: 절대 확률 임계치 분류 방식에서 상대적 랭킹 스코어로 전환해 IC를 평가합니다.")
    md.append("3. **매수 필터 강화**: P(up) 단독 점수 외에 P(up) - P(down) 보수적 시그널 필터 적용을 시도합니다.")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"✅ 종합 리포트 마크다운 파일 저장 완료: {output_path}")

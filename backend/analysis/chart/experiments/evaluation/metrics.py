from math import erf, sqrt

import numpy as np
import pandas as pd


def _binary_classification_counts(y_true: pd.Series, y_pred: pd.Series) -> tuple[int, int, int, int]:
    y_true = pd.Series(y_true).astype(int)
    y_pred = pd.Series(y_pred).astype(int)
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    return tp, tn, fp, fn


def _safe_div(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def _roc_auc_score_binary(y_true: pd.Series, y_prob: pd.Series) -> float:
    y_true = pd.Series(y_true).astype(int).reset_index(drop=True)
    y_prob = pd.Series(y_prob).astype(float).reset_index(drop=True)
    n_pos = int((y_true == 1).sum())
    n_neg = int((y_true == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return np.nan

    ranks = y_prob.rank(method="average")
    pos_rank_sum = ranks[y_true == 1].sum()
    auc_value = (pos_rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(auc_value)


def _pr_auc_score_binary(y_true: pd.Series, y_prob: pd.Series) -> float:
    y_true = pd.Series(y_true).astype(int).reset_index(drop=True)
    y_prob = pd.Series(y_prob).astype(float).reset_index(drop=True)
    n_pos = int((y_true == 1).sum())
    if n_pos == 0:
        return np.nan

    # A threshold applies to every observation with the same score at once.
    # Processing tied scores row-by-row makes the curve (and its area) depend on
    # an incidental parquet/DataFrame row order.
    ranked = pd.DataFrame({"score": y_prob, "target": y_true}).groupby(
        "score", sort=False, dropna=False
    )["target"].agg(["sum", "count"])
    ranked = ranked.sort_index(ascending=False, kind="stable")
    tp_cum = ranked["sum"].cumsum().to_numpy(dtype=float)
    fp_cum = (ranked["count"] - ranked["sum"]).cumsum().to_numpy(dtype=float)
    precision = tp_cum / np.maximum(tp_cum + fp_cum, 1)
    recall = tp_cum / n_pos

    precision = np.r_[1.0, precision]
    recall = np.r_[0.0, recall]

    # NumPy 2.0에서 np.trapz가 np.trapezoid로 바뀌었다.
    if hasattr(np, "trapezoid"):
        return float(np.trapezoid(precision, recall))
    else:
        return float(np.trapz(precision, recall))


def calculate_classification_metrics(
    y_true: pd.Series, y_prob: pd.Series, threshold: float = 0.5
) -> dict:
    y_true_binary = (y_true == 2).astype(int)

    y_pred = (y_prob >= threshold).astype(int)

    tp, tn, fp, fn = _binary_classification_counts(y_true_binary, y_pred)
    pos_recall = _safe_div(tp, tp + fn)
    neg_recall = _safe_div(tn, tn + fp)
    pos_precision = _safe_div(tp, tp + fp)
    neg_precision = _safe_div(tn, tn + fn)
    pos_f1 = _safe_div(2 * pos_precision * pos_recall, pos_precision + pos_recall)
    neg_f1 = _safe_div(2 * neg_precision * neg_recall, neg_precision + neg_recall)

    metrics = {
        "sample_count": len(y_true),
        "up_class_ratio": float(y_true_binary.mean()),
        "accuracy": float((tp + tn) / len(y_true_binary)) if len(y_true_binary) else np.nan,
        "balanced_accuracy": float((pos_recall + neg_recall) / 2.0),
        "macro_f1": float((pos_f1 + neg_f1) / 2.0),
        "brier_score": float(np.mean((y_true_binary - y_prob) ** 2)),
    }

    metrics["roc_auc"] = _roc_auc_score_binary(y_true_binary, y_prob)
    metrics["pr_auc"] = _pr_auc_score_binary(y_true_binary, y_prob)

    return metrics


def calculate_calibration_table(
    y_true: pd.Series, y_prob: pd.Series, bins: list[float]
) -> pd.DataFrame:
    y_true_binary = (y_true == 2).astype(int)

    labels = [f"{bins[i]:.1f}-{bins[i+1]:.1f}" for i in range(len(bins) - 1)]
    categories = pd.cut(y_prob, bins=bins, labels=labels, include_lowest=True)

    df = pd.DataFrame(
        {
            "Prob_Bin": categories,
            "y_prob": y_prob,
            "y_true": y_true_binary,
        }
    )

    summary = df.groupby("Prob_Bin", observed=False).agg(
        sample_count=("y_true", "count"),
        predicted_mean=("y_prob", "mean"),
        actual_up_hit_rate=("y_true", "mean"),
    )

    summary = summary.fillna(0.0).reset_index()
    return summary


def calculate_rank_ic(
    eval_df: pd.DataFrame, prob_col: str = "Prob", target_col: str = "Y_Label"
) -> dict:
    """eval_df에는 'Date', prob_col, target_col 컬럼이 있어야 한다."""

    def get_spearman(group):
        if len(group) < 5:
            return np.nan
        if group[prob_col].std() == 0 or group[target_col].std() == 0:
            return np.nan
        prob_rank = group[prob_col].rank(method="average")
        target_rank = group[target_col].rank(method="average")
        return prob_rank.corr(target_rank, method="pearson")

    try:
        daily_ic = eval_df.groupby("Date", include_groups=False).apply(get_spearman).dropna()
    except TypeError:
        # include_groups는 pandas 2.2부터 지원한다.
        daily_ic = eval_df.groupby("Date").apply(get_spearman).dropna()

    n_days = len(daily_ic)
    if n_days < 2:
        return {
            "ic_mean": np.nan,
            "ic_std": np.nan,
            "ic_t_stat": np.nan,
            "ic_p_value": np.nan,
            "positive_day_ratio": np.nan,
            "n_days": n_days,
        }

    mean_ic = daily_ic.mean()
    std_ic = daily_ic.std()

    if std_ic == 0:
        t_stat = 0.0
        p_val = 1.0
    else:
        t_stat = mean_ic / (std_ic / np.sqrt(n_days))
        # n_days가 충분히 크면 t분포와 표준정규 근사가 거의 같다.
        # scipy 의존성을 피하기 위해 정규분포 양측 p-value 근사를 사용한다.
        p_val = 2.0 * (1.0 - (0.5 * (1.0 + erf(abs(t_stat) / sqrt(2.0)))))

    pos_ratio = (daily_ic > 0).mean()

    return {
        "ic_mean": float(mean_ic),
        "ic_std": float(std_ic),
        "ic_t_stat": float(t_stat),
        "ic_p_value": float(p_val),
        "positive_day_ratio": float(pos_ratio),
        "n_days": n_days,
    }

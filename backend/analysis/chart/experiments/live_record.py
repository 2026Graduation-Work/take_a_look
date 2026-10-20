"""운영 기록 지표(성적표 맨 위, #370 전 단계): 날짜별로 게시된 신호를 학습 기간 밖 실제 가격으로 채점한다.

2026년 운영 예측은 학습 기간(~2025) 밖이라 진짜 표본 밖 기록이다. 채점 규칙은 학습 라벨과 같다
(train_src.labels.barrier_labels: 종가 ± σ배 기준선 중 먼저 닿은 쪽, 동시에 닿으면 하락).

- 목록: 그날 '신호가 강한 종목' 규칙(frontend/lib/strong-signals.ts rankSignals, 회피 항목 없음)
  1위 − 2위 점수 차 순, 중립 1위 제외, 방향별 상위 5개
- 비교: 같은 날 점수가 있는 전체 종목
- 지표: 상승 목록 중 기간 안에 상승 기준선에 먼저 닿은 비율 vs 전체 종목 같은 비율. 하락도 같은 방식
- 표본 수(날짜, 종목)를 함께 남기고, 라벨이 확정된 날이 20거래일 미만이면 sufficient=false

실행: backend/analysis/chart에서 python -m experiments.live_record (SUPABASE_URL, SUPABASE_SECRET_KEY)
결과: frontend/artifacts/performance/live_record.json. 같은 DB 상태면 같은 결과(결정론).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.train_src.labels import barrier_labels  # noqa: E402
from shared.features.builder import add_sigma_barriers  # noqa: E402
from shared.settings import PREPROCESSING  # noqa: E402

SHOW = 5
MIN_DAYS = 20  # 1주 기준 라벨 확정 20거래일 이상이어야 화면에 쓴다(#370 전 단계 요청)
OUT = Path(__file__).resolve().parents[4] / "frontend" / "artifacts" / "performance" / "live_record.json"
PAGE = 1000
MIN_UNIVERSE = 100


def fetch(table: str, params: dict) -> list[dict]:
    base, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SECRET_KEY"]
    rows: list[dict] = []
    while True:
        query = urlencode({**params, "offset": len(rows), "limit": PAGE})
        request = Request(f"{base}/rest/v1/{table}?{query}", headers={"apikey": key, "Authorization": f"Bearer {key}"})
        with urlopen(request, timeout=60) as response:
            page = json.loads(response.read())
        rows += page
        if len(page) < PAGE:
            return rows


def strong_lists(day: pd.DataFrame) -> dict[str, list[str]]:
    """rankSignals와 같은 규칙. day: stock_code, prob_down, prob_neutral, prob_up."""
    scores = day[["prob_down", "prob_neutral", "prob_up"]].to_numpy()
    order = scores.argsort(axis=1)
    first, second = order[:, -1], order[:, -2]
    rows = day.assign(first=first, confidence=scores[range(len(day)), first] - scores[range(len(day)), second])
    rows = rows[rows["first"] != 1].sort_values(["confidence", "stock_code"], ascending=[False, True])
    return {"up": rows[rows["first"] == 2].stock_code.head(SHOW).tolist(),
            "down": rows[rows["first"] == 0].stock_code.head(SHOW).tolist()}


def labels_for(prices: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """종목별 가격 → (stock_code, as_of, label). 거래정지는 거래량 0으로 본다."""
    out = []
    for code, frame in prices.groupby("stock_code", sort=True):
        frame = frame.sort_values("trade_date").rename(columns={"close": "Close", "high": "High"})
        frame["Trading_Halt"] = (frame.volume <= 0).astype(int)
        frame = add_sigma_barriers(frame, PREPROCESSING)
        label = barrier_labels(frame, horizon, up_mult=PREPROCESSING["barrier_feature_up_mult"],
                               down_mult=PREPROCESSING["barrier_feature_down_mult"])
        out.append(pd.DataFrame({"stock_code": code, "as_of": frame.trade_date, "label": label.to_numpy()}))
    return pd.concat(out, ignore_index=True)


def score(log: pd.DataFrame, labels: pd.DataFrame) -> dict:
    """날짜마다 목록과 전체의 '먼저 닿은 쪽' 비율. 라벨이 확정된 날만 쓴다."""
    # 목록은 그날 게시된 전체 점수로 고르고(화면과 같게), 채점은 라벨이 확정된 종목만
    merged = log.merge(labels, on=["stock_code", "as_of"], how="left")
    days, picked = [], {"up": [], "down": []}
    for as_of, posted in merged.groupby("as_of", sort=True):
        if len(posted) < MIN_UNIVERSE:  # 9/21 화면 시험 게시(1종목)처럼 전 종목 게시가 아닌 날
            continue
        lists = strong_lists(posted)
        day = posted.dropna(subset=["label"])
        if day.empty:
            continue
        days.append(as_of)
        for direction, target in (("up", 1), ("down", -1)):
            chosen = day[day.stock_code.isin(lists[direction])]
            # 라벨이 없는 목록 종목(거래정지 등 기간 안 거래가 없어 채점 불가)은 따로 센다
            picked[direction].append({"as_of": as_of, "list_hits": int((chosen.label == target).sum()),
                                      "list_n": len(chosen), "unscored": len(lists[direction]) - len(chosen),
                                      "all_hits": int((day.label == target).sum()), "all_n": len(day)})
    result = {"days": len(days), "first_day": days[0] if days else None, "last_day": days[-1] if days else None,
              "sufficient": len(days) >= MIN_DAYS}
    for direction, rows in picked.items():
        list_n, all_n = sum(r["list_n"] for r in rows), sum(r["all_n"] for r in rows)
        result[direction] = {
            "list_rate": round(sum(r["list_hits"] for r in rows) / list_n, 4) if list_n else None,
            "list_n": list_n,
            "list_unscored": sum(r["unscored"] for r in rows),
            # 같은 날 전체 종목 평균: 날짜마다 비율을 내고 단순평균(목록과 같은 날 가중)
            "all_rate": round(sum(r["all_hits"] / r["all_n"] for r in rows) / len(rows), 4) if rows else None,
            "all_n": all_n,
        }
    return result


def main() -> None:
    log = pd.DataFrame(fetch("chart_prediction_log", {
        "select": "stock_code,as_of,horizon,prob_down,prob_neutral,prob_up", "order": "as_of,stock_code,horizon"}))
    start = (date.fromisoformat(log.as_of.min()) - timedelta(days=60)).isoformat()  # σ 20거래일 앞 여유
    prices = pd.DataFrame(fetch("chart_prices", {
        "select": "stock_code,trade_date,close,high,volume", "trade_date": f"gte.{start}",
        "order": "stock_code,trade_date"}))
    codes = set(log.stock_code)
    prices = prices[prices.stock_code.isin(codes)]
    record = {"source": "chart_prediction_log(게시 배치) + chart_prices", "rule": "strong-signals rankSignals, 방향별 상위 5",
              "label": "barrier_labels(σ 상승 1.5배, 하락 1.2배, 먼저 닿은 쪽)", "min_days": MIN_DAYS,
              "log_days": int(log.as_of.nunique()), "horizons": {}}
    for horizon in (5, 20):
        part = log[log.horizon == horizon]
        record["horizons"][str(horizon)] = score(part, labels_for(prices, horizon))
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()

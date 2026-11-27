"""게시된 신호를 학습 기간 밖 실제 가격으로 채점한다.

로그에는 과거 pack의 라벨 정의가 없어서, 지정한 평가 pack의 라벨로 다시 채점한다.
목록 규칙은 frontend/lib/strong-signals.ts의 rankSignals와 같다.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.train_src.labels import barrier_labels  # noqa: E402
from serving.internal.pack import config_path, load_pack  # noqa: E402
from shared.features.builder import add_sigma_barriers  # noqa: E402
from shared.settings import serving_root  # noqa: E402

SHOW = 5
MIN_DAYS = 20
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
    # 화면의 안정 정렬과 같이 동점은 down, neutral, up 순서로 고른다.
    order = (-scores).argsort(axis=1, kind="stable")
    first, second = order[:, 0], order[:, 1]
    rows = day.assign(first=first, confidence=scores[range(len(day)), first] - scores[range(len(day)), second])
    rows = rows[rows["first"] != 1].sort_values(["confidence", "stock_code"], ascending=[False, True])
    return {"up": rows[rows["first"] == 2].stock_code.head(SHOW).tolist(),
            "down": rows[rows["first"] == 0].stock_code.head(SHOW).tolist()}


def labels_for(prices: pd.DataFrame, horizon: int, pack: dict) -> pd.DataFrame:
    barriers = pack["horizons"][f"h{horizon}"]["label_barriers"]
    for key in ("up_mult", "down_mult"):
        value = barriers[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid H{horizon} label barrier: {key}")
    out = []
    for code, frame in prices.groupby("stock_code", sort=True):
        frame = frame.sort_values("trade_date").rename(columns={"close": "Close", "high": "High"})
        frame["Trading_Halt"] = (frame.volume <= 0).astype(int)
        frame = add_sigma_barriers(frame, pack["processing_contract"]["preprocessing"])
        label = barrier_labels(frame, horizon, **barriers)
        out.append(pd.DataFrame({"stock_code": code, "as_of": frame.trade_date, "label": label.to_numpy()}))
    return pd.concat(out, ignore_index=True)


def score(log: pd.DataFrame, labels: pd.DataFrame) -> dict:
    # 목록은 화면처럼 그날 게시된 전체 점수로 고르고, 채점은 라벨이 확정된 종목만 한다.
    merged = log.merge(labels, on=["stock_code", "as_of"], how="left")
    days, picked = [], {"up": [], "down": []}
    for as_of, posted in merged.groupby("as_of", sort=True):
        if len(posted) < MIN_UNIVERSE:  # 9/21 화면 시험 게시(1종목)처럼 전 종목 게시가 아닌 날
            continue
        # 대시보드 isTradable과 같은 정의: 그날 거래가 없는 종목은 목록 후보에서 뺀다.
        lists = strong_lists(posted[posted.volume > 0] if "volume" in posted else posted)
        day = posted.dropna(subset=["label"])
        if day.empty:
            continue
        days.append(as_of)
        for direction, target in (("up", 1), ("down", -1)):
            chosen = day[day.stock_code.isin(lists[direction])]
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
            # 목록과 같은 날 가중이 되도록 날짜별 비율을 단순평균한다.
            "all_rate": round(sum(r["all_hits"] / r["all_n"] for r in rows) / len(rows), 4) if rows else None,
            "all_n": all_n,
        }
    return result


def main() -> None:
    config = yaml.safe_load(config_path().read_text())["active_pack"]
    pack, _, _ = load_pack(serving_root() / "packs" / config["pack_id"], golden_sha256=config.get("golden_sha256"))
    log = pd.DataFrame(fetch("chart_prediction_log", {
        "select": "stock_code,as_of,horizon,prob_down,prob_neutral,prob_up", "order": "as_of,stock_code,horizon"}))
    start = (date.fromisoformat(log.as_of.min()) - timedelta(days=60)).isoformat()  # σ 20거래일 앞 여유
    prices = pd.DataFrame(fetch("chart_prices", {
        "select": "stock_code,trade_date,close,high,volume", "trade_date": f"gte.{start}",
        "order": "stock_code,trade_date"}))
    codes = set(log.stock_code)
    prices = prices[prices.stock_code.isin(codes)]
    record = {"source": "chart_prediction_log(게시 배치) + chart_prices", "rule": "strong-signals rankSignals, 방향별 상위 5",
              "evaluation_status": "computed", "evaluation_basis": "fixed_pack_labels",
              "evaluation_pack_id": pack["pack_id"],
              "label": "barrier_labels(평가 pack의 기간별 학습 라벨, 상승은 고가, 하락은 종가, 동시면 하락)", "min_days": MIN_DAYS,
              "log_days": int(log.as_of.nunique()), "horizons": {}}
    traded = prices.rename(columns={"trade_date": "as_of"})[["stock_code", "as_of", "volume"]]
    log = log.merge(traded, on=["stock_code", "as_of"], how="left").fillna({"volume": 0})
    for horizon in (5, 20):
        part = log[log.horizon == horizon]
        record["horizons"][str(horizon)] = {
            **score(part, labels_for(prices, horizon, pack)),
            "label_barriers": pack["horizons"][f"h{horizon}"]["label_barriers"],
        }
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()

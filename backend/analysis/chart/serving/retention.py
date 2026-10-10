"""무료 한도 보존 정리(docs/ops/free-tier-budget.md). 차트 서빙 게시 뒤 별도 step에서 돈다(python -m serving.retention).

1. 예측 요약 로그 적재 + 게시 배치는 최근 KEEP_BATCHES개만 남김(DB 함수 prune_chart_batches, 0009)
2. Storage 차트 입력 파일과 그 기록(chart_feature_snapshots)은 남은 게시 배치(5영업일)보다 오래된 날짜분 삭제.
   종목별 전체 가격 이력(raw-history-v3)은 남기고, 수급 원본(investor-flows-v3)은 FLOW_DAYS일(재조회 호출을 줄이려고)
3. 뉴스 원문(news_articles)·공시 목록(disclosures)은 ARTICLE_DAYS일 초과분 삭제. 일별 집계(news_sentiment_daily)는 그대로
"""

import json
from datetime import date, timedelta
from urllib.parse import quote

from serving.internal.storage import SupabaseStore

KEEP_BATCHES = 5  # 영업일 하루 1배치 → 입력 파일도 5영업일만(1GB 무료 한도, docs/ops/free-tier-budget.md)
FLOW_DAYS = 30
ARTICLE_DAYS = 90
BUCKET = "chart-features"



def prune_corrected_inputs(store, cutoff, flow_cutoff):
    """Keep the full current history; expire dated replay/flow objects only."""
    def listing(prefix):
        rows = []
        while True:
            page = store._request("POST", f"/storage/v1/object/list/{BUCKET}",
                                  {"prefix": prefix, "limit": 1000, "offset": len(rows),
                                   "sortBy": {"column": "name", "order": "asc"}})
            rows.extend(page)
            if len(page) < 1000:
                return rows
    paths = []
    for folder in listing("raw-prices-v3"):
        name = folder["name"]
        if len(name) == 10 and name < cutoff:
            prefix = f"raw-prices-v3/{name}"
            paths.extend(f"{prefix}/{item['name']}" for item in listing(prefix))
    for item in listing("investor-flows-v3"):
        if item["name"][:10] < flow_cutoff:
            paths.append(f"investor-flows-v3/{item['name']}")
    for offset in range(0, len(paths), 1000):
        store._request("DELETE", f"/storage/v1/object/{BUCKET}", {"prefixes": paths[offset:offset + 1000]})
    return len(paths)


def main(today=None):
    store = SupabaseStore()
    today = today or date.today()
    pruned = store._request("POST", "/rest/v1/rpc/prune_chart_batches", {"p_keep": KEEP_BATCHES})

    flow_cutoff = (today - timedelta(days=FLOW_DAYS)).isoformat()
    oldest = store._request("GET", "/rest/v1/chart_batches?select=as_of&order=as_of.asc&limit=1")
    cutoff = oldest[0]["as_of"] if oldest else flow_cutoff  # 남은 배치의 입력만 보존(replay 가능 범위)
    rows = []
    while True:  # PostgREST는 한 번에 최대 1000행
        page = store._request("GET", "/rest/v1/chart_feature_snapshots?select=storage_path&order=storage_path&as_of=lt."
                              + quote(cutoff) + f"&limit=1000&offset={len(rows)}")
        rows.extend(page)
        if len(page) < 1000:
            break
    paths = sorted({row["storage_path"] for row in rows})
    for offset in range(0, len(paths), 1000):
        store._request("DELETE", f"/storage/v1/object/{BUCKET}", {"prefixes": paths[offset:offset + 1000]})
    if rows:
        store._request("DELETE", "/rest/v1/chart_feature_snapshots?as_of=lt." + quote(cutoff), prefer="return=minimal")

    corrected_objects = prune_corrected_inputs(store, cutoff, flow_cutoff)

    article_cutoff = (today - timedelta(days=ARTICLE_DAYS)).isoformat()
    store._request("DELETE", "/rest/v1/news_articles?article_date=lt." + quote(article_cutoff), prefer="return=minimal")
    store._request("DELETE", "/rest/v1/disclosures?filed_on=lt." + quote(article_cutoff), prefer="return=minimal")
    print(json.dumps({"event": "retention", "pruned_batches": pruned, "feature_rows": len(rows),
                      "storage_objects": len(paths), "corrected_objects": corrected_objects, "feature_cutoff": cutoff, "article_cutoff": article_cutoff}))


if __name__ == "__main__":
    main()

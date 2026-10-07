"""무료 한도 보존 정리(docs/ops/free-tier-budget.md). 차트 서빙 게시 뒤 별도 step에서 돈다(python -m retention).

1. 예측 요약 로그 적재 + 게시 배치는 최근 KEEP_BATCHES개만 남김(DB 함수 prune_chart_batches, 0009)
2. Storage 차트 입력 파일과 그 기록(chart_feature_snapshots)은 FEATURE_DAYS일 초과분 삭제
3. 뉴스 원문(news_articles)·공시 목록(disclosures)은 ARTICLE_DAYS일 초과분 삭제. 일별 집계(news_sentiment_daily)는 그대로
"""

import json
from datetime import date, timedelta
from urllib.parse import quote

from serving.internal.storage import SupabaseStore

KEEP_BATCHES = 5
FEATURE_DAYS = 30
ARTICLE_DAYS = 90
BUCKET = "chart-features"


def main(today=None):
    store = SupabaseStore()
    today = today or date.today()
    pruned = store._request("POST", "/rest/v1/rpc/prune_chart_batches", {"p_keep": KEEP_BATCHES})

    cutoff = (today - timedelta(days=FEATURE_DAYS)).isoformat()
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

    article_cutoff = (today - timedelta(days=ARTICLE_DAYS)).isoformat()
    store._request("DELETE", "/rest/v1/news_articles?article_date=lt." + quote(article_cutoff), prefer="return=minimal")
    store._request("DELETE", "/rest/v1/disclosures?filed_on=lt." + quote(article_cutoff), prefer="return=minimal")
    print(json.dumps({"event": "retention", "pruned_batches": pruned, "feature_rows": len(rows),
                      "storage_objects": len(paths), "feature_cutoff": cutoff, "article_cutoff": article_cutoff}))


if __name__ == "__main__":
    main()

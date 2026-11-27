"""Supabase 무료 한도 안에 머물도록 오래된 배치·입력·기사를 지운다.

수급 원본(investor-flows-v3)은 재조회 호출을 줄이려고 FLOW_DAYS일 남긴다.
"""

import argparse
import json
from collections import Counter
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from serving.internal.storage import SupabaseStore

KEEP_BATCHES = 5  # 영업일 하루 1배치 → 입력 파일도 5영업일만(1GB 무료 한도)
FLOW_DAYS = 30
ARTICLE_DAYS = 90
PROPOSED_ARTICLE_DAYS = 120
KST = ZoneInfo("Asia/Seoul")
ARTICLE_SOURCES = {
    "news_articles": ("article_date", "stock_code,track,news_id"),
    "disclosures": ("filed_on", "rcept_no"),
}
BUCKET = "chart-features"



def prune_corrected_inputs(store, cutoff, flow_cutoff):
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
    for item in listing("calendars-v3"):
        name = item["name"]
        if name.endswith(".parquet"):
            try:
                day = date.fromisoformat(name.removesuffix(".parquet")).isoformat()
            except ValueError:
                continue
            if day < cutoff:
                paths.append(f"calendars-v3/{name}")
    for offset in range(0, len(paths), 1000):
        store._request("DELETE", f"/storage/v1/object/{BUCKET}", {"prefixes": paths[offset:offset + 1000]})
    return len(paths)


def article_candidates(store, cutoff):
    candidates = {}
    for table, (field, keys) in ARTICLE_SOURCES.items():
        offset = 0
        dates = Counter()
        while True:
            path = (f"/rest/v1/{table}?{field}=lt.{quote(cutoff)}&select={field}"
                    f"&order={field},{keys}&limit=1000&offset={offset}")
            rows = store._request("GET", path)
            dates.update(row[field] for row in rows)
            if len(rows) < 1000:
                break
            offset += len(rows)
        candidates[table] = {"count": dates.total(), "by_date": dict(sorted(dates.items()))}
    return candidates


def main(today=None, *, article_days=ARTICLE_DAYS, dry_run=False):
    store = SupabaseStore()
    article_today = today or datetime.now(KST).date()
    article_cutoff = (article_today - timedelta(days=article_days)).isoformat()
    if dry_run:
        print(json.dumps({"event": "retention_dry_run", "article_cutoff": article_cutoff,
                          "candidates": article_candidates(store, article_cutoff)}))
        return
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
    paths = {row["storage_path"] for row in rows}
    if paths:
        offset = 0
        while True:
            kept = store._request("GET", "/rest/v1/chart_feature_snapshots?as_of=gte." + quote(cutoff) +
                                  f"&select=storage_path&order=storage_path&limit=1000&offset={offset}")
            paths.difference_update(row["storage_path"] for row in kept)
            if len(kept) < 1000:
                break
            offset += 1000
    paths = sorted(paths)
    for offset in range(0, len(paths), 1000):
        store._request("DELETE", f"/storage/v1/object/{BUCKET}", {"prefixes": paths[offset:offset + 1000]})
    if rows:
        store._request("DELETE", "/rest/v1/chart_feature_snapshots?as_of=lt." + quote(cutoff), prefer="return=minimal")

    corrected_objects = prune_corrected_inputs(store, cutoff, flow_cutoff)
    store._request("DELETE", "/rest/v1/chart_universe?as_of=lt." + quote(cutoff), prefer="return=minimal")

    for table, (field, _) in ARTICLE_SOURCES.items():
        store._request("DELETE", f"/rest/v1/{table}?{field}=lt." + quote(article_cutoff), prefer="return=minimal")
    print(json.dumps({"event": "retention", "pruned_batches": pruned, "feature_rows": len(rows),
                      "storage_objects": len(paths), "corrected_objects": corrected_objects, "feature_cutoff": cutoff, "article_cutoff": article_cutoff}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--article-days", type=int, choices=(ARTICLE_DAYS, PROPOSED_ARTICLE_DAYS),
                        default=ARTICLE_DAYS)
    parser.add_argument("--dry-run", action="store_true", help="기사·공시 삭제 후보 날짜와 건수만 조회")
    args = parser.parse_args()
    main(article_days=args.article_days, dry_run=args.dry_run)

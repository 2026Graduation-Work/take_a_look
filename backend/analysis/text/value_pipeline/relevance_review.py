"""Offline relevance sensitivity audit; stored scores are never recomputed.

Provider bodies are read in memory only. Provisional reviewer labels are not
human ground truth; agreement with them must not be reported as accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .agents import relevant_indices
from .news_relevance import CONTEXTUAL_LIVE_COMPANIES, POLICY_VERSION, classify_live_relevance
from .newsapi_ai import _display_text

_CATEGORIES = {"direct", "indirect", "industry", "market", "irrelevant", "review"}


def _title(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _stats(scores: list[float]) -> dict:
    return {"count": len(scores), "mean": statistics.mean(scores) if scores else None,
            "std_population": statistics.pstdev(scores) if scores else None}


def build_audit(source: dict, details: dict, *, company: str, date: str,
                labels: list[dict] | None = None, details_retrieved_at: str | None = None) -> dict:
    """Compare both policies on identical title/body, retaining original scores."""
    if company not in CONTEXTUAL_LIVE_COMPANIES:
        raise ValueError("Company is not supported by the contextual live rollout")
    datetime.strptime(date, "%Y-%m-%d")
    articles = source.get("news_articles", [])
    all_ids = [str(row.get("news_id", "")) for row in articles]
    if any(not ident for ident in all_ids) or len(set(all_ids)) != len(all_ids):
        raise ValueError("Source requires unique nonempty news_id values")
    selected = [row for row in articles if row.get("article_date") == date]
    if not selected:
        raise ValueError("No source articles for requested date")
    label_map = {}
    if labels is not None:
        label_ids = [str(row.get("news_id", "")) for row in labels]
        if len(set(label_ids)) != len(label_ids) or set(label_ids) != {str(r["news_id"]) for r in selected}:
            raise ValueError("Provisional labels must cover every selected ID exactly once")
        if any(row.get("label") not in _CATEGORIES for row in labels):
            raise ValueError("Unsupported provisional label")
        label_map = dict(zip(label_ids, labels, strict=True))
    items = []
    for row in selected:
        ident = str(row["news_id"])
        info = details.get(ident, {}).get("info", {})
        body = info.get("body", "")
        if not isinstance(body, str) or not body.strip():
            raise ValueError(f"Missing provider body for {ident}")
        if _title(str(info.get("title", ""))) != _title(str(row.get("title", ""))):
            raise ValueError(f"Provider title changed for {ident}")
        score = row.get("sentiment_score")
        if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score) or not -1 <= score <= 1:
            raise ValueError(f"Invalid stored sentiment score for {ident}")
        items.append({"title": row["title"], "summary": _display_text(body)})
    legacy_indices = set(relevant_indices(items, company))
    rows = []
    for index, (article, item) in enumerate(zip(selected, items, strict=True), 1):
        decision = classify_live_relevance(item, company)
        ident = str(article["news_id"])
        label = label_map.get(ident, {})
        rows.append({"index": index, "news_id": ident, "title": article["title"],
                     "url": article.get("url", ""), "sentiment_score": article["sentiment_score"],
                     "old_included": index - 1 in legacy_indices,
                     "new_category": decision.category, "reason": decision.reason,
                     "matched_alias": decision.matched_alias, "new_included": decision.included,
                     "provider_body_sha256": hashlib.sha256(item["summary"].encode()).hexdigest(),
                     "provisional_label": label.get("label"),
                     "provisional_reason": label.get("reason"),
                     "label_evidence": label.get("evidence_level"), "human_label": ""})
    comparison = {key: _stats([r["sentiment_score"] for r in rows if r[field]])
                  for key, field in (("legacy", "old_included"), ("candidate", "new_included"))}
    comparison.update({"removed": sum(r["old_included"] and not r["new_included"] for r in rows),
                       "added": sum(not r["old_included"] and r["new_included"] for r in rows)})
    agreement = None
    if labels is not None:
        exceptions = [r["news_id"] for r in rows
                      if r["new_included"] != (r["provisional_label"] in {"direct", "indirect", "industry", "market"})]
        agreement = {"reviewer": "agent_provisional_not_human_ground_truth", "total": len(rows),
                     "matching_inclusion": len(rows) - len(exceptions), "exception_ids": exceptions}
    return {"company": company, "date": date, "policy_version": POLICY_VERSION,
            "supported_live_companies": sorted(CONTEXTUAL_LIVE_COMPANIES),
            "created_at": datetime.now(UTC).isoformat(),
            "source_as_of": source.get("as_of") or source.get("news_sentiment_tracks"),
            "details_retrieved_at": details_retrieved_at,
            "limitations": ["Provider body was re-queried and may differ from original model input.",
                            "Contextual live rollout supports the six configured companies.",
                            "Stored sentiment scores reused: sensitivity analysis, no model recomputation.",
                            "Provisional labels are agent review, not human ground truth.",
                            "Subset contains previously accepted news: excluded relevant news cannot be measured."],
            "comparison": comparison, "category_counts": dict(Counter(r["new_category"] for r in rows)),
            "agent_label_agreement": agreement, "rows": rows}


def write_audit(result: dict, out_dir: Path) -> None:
    """Persist metadata and decisions, never provider body or extracted passages."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "relevance_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    lines = [f"# {result['date']} {result['company']} 뉴스 관련성 검증", "",
             "공급자 본문 재조회 자료에 기존/신규 규칙을 동일 적용했습니다. 당시 입력과 달라졌을 수 있습니다.",
             "저장 감성점수를 재사용한 포함 여부 민감도 분석이며, 감성 모델을 재실행하지 않았습니다.",
             "임시 라벨은 에이전트 검토안입니다. 사람 정답·정확도·재현율로 해석하지 마세요.",
             "이미 통과한 기사만 있어 기존 필터가 놓친 관련 기사는 평가할 수 없습니다.", "",
             f"- 정책 버전: {result['policy_version']}",
             f"- 실제 실시간 적용 범위: {', '.join(result['supported_live_companies'])}",
             f"- 원본 기준 시각: {result['source_as_of']}",
             f"- 본문 재조회 시각: {result['details_retrieved_at'] or '별도 기록 없음'}", "",
             "| 비교 | 기사 수 | 저장 점수 평균 | 모집단 표준편차 |", "|---|---:|---:|---:|"]
    for key, name in (("legacy", "기존 규칙"), ("candidate", "신규 규칙")):
        stats = result["comparison"][key]
        values = ["—" if stats[field] is None else f"{stats[field]:.4f}" for field in ("mean", "std_population")]
        lines.append(f"| {name} | {stats['count']} | {values[0]} | {values[1]} |")
    lines += ["", f"제외 {result['comparison']['removed']}건 / 추가 {result['comparison']['added']}건",
              f"분류별 건수: {result['category_counts']}", "",
              "| 번호 | 제목·원문 | 감성점수 | 기존 포함 | 신규 분류 | 신규 포함 | 규칙 사유 | 임시 라벨 | 사람 확인 |",
              "|---:|---|---:|---|---|---|---|---|---|"]
    for row in result["rows"]:
        title = row["title"].replace("|", "／").replace("\n", " ")
        lines.append(f"| {row['index']} | [{title}]({row['url']}) | {row['sentiment_score']:+.4f} | "
                     f"{'예' if row['old_included'] else '아니오'} | {row['new_category']} | "
                     f"{'예' if row['new_included'] else '아니오'} | {row['reason']} | "
                     f"{row['provisional_label'] or '미작성'} | |")
    (out_dir / "relevance_audit.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("source", "details", "date", "company", "out-dir"):
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--labels")
    parser.add_argument("--details-retrieved-at")
    args = parser.parse_args()
    source = json.loads(Path(args.source).read_text())
    details = json.loads(Path(args.details).read_text())
    labels = json.loads(Path(args.labels).read_text()) if args.labels else None
    result = build_audit(source, details, company=args.company, date=args.date,
                         labels=labels, details_retrieved_at=args.details_retrieved_at)
    write_audit(result, Path(args.out_dir))
    print(json.dumps(result["comparison"], ensure_ascii=False))


if __name__ == "__main__":
    main()

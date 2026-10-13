"""Offline audit must distinguish provisional agent review from human truth."""
from __future__ import annotations

import json

import pytest
from analysis.text.value_pipeline.relevance_review import build_audit, write_audit


def _inputs():
    rows = [
        {"news_id": "1", "title": "현대차, 신형 투싼 출시", "article_date": "2026-10-13", "sentiment_score": 0.2, "url": "https://example.com/1"},
        {"news_id": "2", "title": "세계 1위 한국 치킨", "article_date": "2026-10-13", "sentiment_score": 0.9, "url": "https://example.com/2"},
    ]
    details = {
        "1": {"info": {"title": rows[0]["title"], "body": "현대차가 투싼을 출시했다."}},
        "2": {"info": {"title": rows[1]["title"], "body": "현대차 정의선 회장이 치맥 회동에 참석했다. RAW_BODY_MARKER"}},
    }
    labels = [{"news_id": "1", "label": "direct", "evidence_level": "provider_body"}, {"news_id": "2", "label": "irrelevant", "evidence_level": "provider_body"}]
    return {"news_articles": rows, "as_of": "2026-10-13T06:49:26Z"}, details, labels


def test_same_inputs_reuse_stored_scores_and_do_not_claim_accuracy(tmp_path):
    source, details, labels = _inputs()
    result = build_audit(source, details, company="현대차", date="2026-10-13", labels=labels)
    assert result["comparison"]["legacy"]["count"] == 2
    assert result["comparison"]["candidate"]["count"] == 1
    assert result["comparison"]["candidate"]["mean"] == pytest.approx(0.2)
    assert result["agent_label_agreement"]["matching_inclusion"] == 2
    assert result["rows"][1]["new_category"] == "irrelevant"
    assert result["rows"][1]["sentiment_score"] == 0.9
    write_audit(result, tmp_path)
    content = "".join(p.read_text() for p in tmp_path.iterdir())
    assert "RAW_BODY_MARKER" not in content
    assert "human_accuracy" not in content
    assert "summary" not in json.dumps(result)
    assert len(result["rows"][0]["provider_body_sha256"]) == 64


@pytest.mark.parametrize("damage", ["duplicate", "missing_body", "wrong_title", "wrong_date", "partial_labels", "duplicate_labels", "bad_score"])
def test_incomplete_or_changed_inputs_fail_closed(damage):
    source, details, labels = _inputs()
    if damage == "duplicate":
        source["news_articles"].append(source["news_articles"][0])
    elif damage == "missing_body":
        details["2"]["info"]["body"] = ""
    elif damage == "wrong_title":
        details["2"]["info"]["title"] = "수정된 다른 기사"
    elif damage == "wrong_date":
        for row in source["news_articles"]:
            row["article_date"] = "2026-10-12"
    elif damage == "partial_labels":
        labels.pop()
    elif damage == "duplicate_labels":
        labels[1] = labels[0]
    else:
        source["news_articles"][0]["sentiment_score"] = float("nan")
    with pytest.raises(ValueError):
        build_audit(source, details, company="현대차", date="2026-10-13", labels=labels)


def test_provider_body_uses_production_normalization_and_preserves_label_reason():
    import hashlib
    import unicodedata

    source, details, labels = _inputs()
    normal_body = "현대차가 투싼을 출시했다."
    details["1"]["info"]["body"] = " \n" + unicodedata.normalize("NFD", normal_body) + "\t"
    labels[0]["reason"] = "현대차 신차 출시가 제목에 명시됨"
    result = build_audit(source, details, company="현대차", date="2026-10-13", labels=labels)
    assert result["rows"][0]["provider_body_sha256"] == hashlib.sha256(normal_body.encode()).hexdigest()
    assert result["rows"][0]["provisional_reason"] == labels[0]["reason"]


def test_audit_refuses_company_outside_live_rollout():
    source, details, _ = _inputs()
    with pytest.raises(ValueError, match="supported"):
        build_audit(source, details, company="기아", date="2026-10-13")

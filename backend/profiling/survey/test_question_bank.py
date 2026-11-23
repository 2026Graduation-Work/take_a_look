"""채점은 TS(style-scoring.ts) 한 벌이라 Python은 문항 JSON과 스키마 계약만 검사한다."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BANK = json.loads(
    (ROOT / "frontend/lib/profiling/style-questions.json").read_text(encoding="utf-8")
)
SCHEMA = json.loads(
    (ROOT / "schema/profiling_output.schema.json").read_text(encoding="utf-8")
)


def _schema_axis_ids() -> list[str]:
    axes = SCHEMA["properties"]["style_axes"]["properties"]["axes"]
    return axes["items"]["properties"]["axis_id"]["enum"]


def test_axes_match_schema_enum_in_order() -> None:
    assert [axis["id"] for axis in BANK["axes"]] == _schema_axis_ids()


def test_every_question_targets_a_known_axis() -> None:
    axis_ids = set(_schema_axis_ids())
    for question in BANK["questions"]:
        if question["type"] == "likert":
            assert question["axis"] in axis_ids, question["id"]
            assert question["direction"] in (1, -1), question["id"]
        else:
            for option in question["options"]:
                assert set(option["scores"]) <= axis_ids, question["id"]
                assert all(-2 <= score <= 2 for score in option["scores"].values())
        assert question["weight"] > 0, question["id"]


def test_each_axis_has_reverse_keyed_question_in_every_mode() -> None:
    for mode in ("short", "quick", "detailed"):
        questions = [
            q
            for q in BANK["questions"]
            if q["type"] == "likert" and (mode == "detailed" or q[mode])
        ]
        for axis_id in _schema_axis_ids():
            directions = {q["direction"] for q in questions if q["axis"] == axis_id}
            assert directions == {1, -1}, (axis_id, mode)


def test_short_mode_is_two_per_axis_inside_quick() -> None:
    short = [q for q in BANK["questions"] if q.get("short")]
    assert len(short) == 16
    assert all(q["quick"] for q in short)
    for axis_id in _schema_axis_ids():
        assert sum(q["axis"] == axis_id for q in short) == 2, axis_id


def test_question_ids_are_unique() -> None:
    ids = [question["id"] for question in BANK["questions"]]
    assert len(ids) == len(set(ids))


def test_turnover_rules_cover_the_full_ratio_range() -> None:
    rules = BANK["turnover_day_rules"]
    bounds = [rule["max_ratio"] for rule in rules]
    assert bounds == sorted(bounds)
    assert bounds[-1] > 1.0
    days = [rule["days"] for rule in rules]
    assert days == sorted(days, reverse=True)  # 회전율이 낮을수록 기간이 길다

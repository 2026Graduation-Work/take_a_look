"""뉴스 감성 생성: BigKinds 코퍼스 실데이터 → 삼성전자 sentiment-fixture.ts / 그 외 백엔드 track JSON

backend value_pipeline news_agent와 같은 규칙으로 일별 감성을 낸다.
    관련성 필터(relevant_indices) → 하루 최대 max_daily_articles건
    → score_texts(KR-FinBERT) → aggregate 평균
기사 텍스트는 preprocess.load_daily_news와 같이 제목 + 본문 앞 1000자(summary)다.
대표 기사는 news_agent 규칙 폴백과 같이 창 마지막 날 감성 절댓값 상위 3건이다.

N07 "뉴스 감성 급변" 임계는 전체 기간 일별 감성 변화량 |Δ|의 상위 10% 분위수(p90)다.
화면에 싣는 20일 창은 |Δ| >= p90인 가장 늦은 날로 끝나게 고른다.
점수를 만들지 않고 실제 코퍼스에서 그런 날짜 구간을 찾는다.

종목(--ticker): 005930(기본)은 기존 sentiment-fixture.ts(대표 기사 제목 포함)를 만든다.
그 외 종목은 frontend/lib/providers/sentiment-<코드>.json에 news_tracks.py와 같은
historical track 계약을 쓴다. 일별 표준편차는 기사별 점수가 없는 재사용 경로에서는 null이다.
기사 제목·본문은 커밋하지 않는다(docs/decisions/bigkinds-acquisition.md). 코퍼스는 preprocess로 만든 news_corpus_<코드>.csv이고,
삼성전자와 같은 기간(2025-10-29~12-31)만 쓴다.
    cd backend && python -m analysis.text.preprocess --ticker 005380 --out news_corpus_005380.csv
    python frontend/scripts/build_sentiment_fixture.py --ticker 005380 \\
        --daily-csv backend/analysis/text/data/processed/news_sentiment_daily_005380.csv

실행
    전수(기본, torch·transformers 필요). 일별 점수를 레포 CSV로도 남긴다:
        python frontend/scripts/build_sentiment_fixture.py \\
            --daily-csv backend/analysis/text/data/processed/news_sentiment_daily.csv
    일별 점수 재사용(창 마지막 날 기사만 다시 채점). stderr 로그나 위 CSV를 받는다:
        python frontend/scripts/build_sentiment_fixture.py \\
            --daily-log backend/analysis/text/data/processed/news_sentiment_daily.csv
    빠른 플레이스홀더(사전 폴백, 몇 초):
        python frontend/scripts/build_sentiment_fixture.py --limit 300 --scorer dictionary
기본 옵션에서 KR-FinBERT를 못 불러오면 중단한다
(VALUE_PIPELINE_VALIDATION.md: 감성 백엔드 혼용 금지). 사전 결과는 PLACEHOLDER로 표시한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT_BLOCK = ROOT / "backend" / "analysis" / "text"
sys.path.insert(0, str(TEXT_BLOCK))

from value_pipeline.agents import _text_of, relevant_indices  # noqa: E402
from value_pipeline.config import SETTINGS  # noqa: E402
from value_pipeline.sentiment import _lexicon_score, aggregate, score_texts  # noqa: E402

PROCESSED = TEXT_BLOCK / "data" / "processed"
PROVIDERS = ROOT / "frontend" / "lib" / "providers"
COMPANIES = {"005930": "삼성전자", "005380": "현대차", "035720": "카카오", "068270": "셀트리온"}
PERIOD = ("2025-10-29", "2025-12-31")  # 삼성전자 코퍼스 기간. 데모 기준일(2025-12-30)을 덮는다
# parse_args()가 --ticker로 덮어쓴다
TICKER = "005930"
COMPANY = COMPANIES[TICKER]
CORPUS = PROCESSED / "news_corpus.csv"
OUT = PROVIDERS / "sentiment-fixture.ts"
BODY_CHARS = 1000  # preprocess.load_daily_news 기본값
WINDOW_DAYS = 20
HEADLINES = 3
# stderr 로그 "2025-10-29 n=55 score=+0.1234" 와 CSV "2025-10-29,55,0.1234" 둘 다 받는다.
DAILY_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?: n=|,)(\d+)(?: score=|,)([+-]?\d+\.\d+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", choices=sorted(COMPANIES), default="005930")
    parser.add_argument(
        "--scorer",
        choices=("finbert", "dictionary"),
        default="finbert",
        help="finbert = KR-FinBERT(기본), dictionary = value_pipeline 사전 폴백",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="전체 채점 기사 수 상한. 날짜마다 고르게 나눈다(날짜당 최소 1건)",
    )
    parser.add_argument(
        "--daily-log",
        type=Path,
        default=None,
        help="일별 점수 원천: 이전 전수 실행의 stderr 로그 또는 --daily-csv로 남긴 CSV",
    )
    parser.add_argument(
        "--daily-csv",
        type=Path,
        default=None,
        help="전수 KR-FinBERT 일별 점수(date,n,score)를 이 경로에 쓴다",
    )
    args = parser.parse_args()
    global TICKER, COMPANY, CORPUS, OUT
    TICKER, COMPANY = args.ticker, COMPANIES[args.ticker]
    if TICKER != "005930":
        CORPUS = PROCESSED / f"news_corpus_{TICKER}.csv"
        OUT = PROVIDERS / f"sentiment-{TICKER}.json"
    return args


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return "<저장소 밖 파일: 전수 배치 stderr 로그>"


def load_corpus() -> dict[str, list[dict]]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    with CORPUS.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            title = row["title"].strip()
            if row["ticker"] != TICKER or not title or not PERIOD[0] <= row["date"][:10] <= PERIOD[1]:
                continue
            by_day[row["date"][:10]].append(
                {
                    "news_id": row["news_id"],
                    "title": title,
                    "summary": row["body"].strip()[:BODY_CHARS],
                    "press": row["press"].strip(),
                }
            )
    # load_daily_news와 같이 하루 안에서는 news_id 순
    return {
        date: sorted(items, key=lambda item: item["news_id"])
        for date, items in sorted(by_day.items())
    }


def parse_daily_log(path: Path) -> dict[str, tuple[int, float]]:
    logged: dict[str, tuple[int, float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = DAILY_LINE.match(line.strip())
        if match:
            logged[match.group(1)] = (int(match.group(2)), float(match.group(3)))
    return logged


def write_daily_csv(path: Path, days: list[dict], daily_log: Path | None) -> None:
    lines = [
        f"# {COMPANY}({TICKER}) 일별 뉴스 감성. KR-FinBERT({SETTINGS.finbert_model}) 전수 채점",
        f"# 원천: {display_path(CORPUS)}, backend value_pipeline news_agent 규칙"
        f"(관련성 필터, 하루 최대 {SETTINGS.max_daily_articles}건, 제목 + 본문 앞 {BODY_CHARS}자)",
        f"# 생성: python frontend/scripts/build_sentiment_fixture.py --ticker {TICKER} --daily-csv {display_path(path)}",
    ]
    if daily_log is not None:
        lines.append(
            f"#       이 파일의 값은 전수 채점 실행의 일별 결과({display_path(daily_log)})를 옮겨 적었다."
        )
    lines += [
        "# n = 채점 기사 수, score = 그날 기사 감성 평균(-1 부정 ~ +1 긍정). '#' 줄은 주석이다.",
        "date,n,score",
        *[f"{day['date']},{day['articleCount']},{day['score']:.4f}" for day in days],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def score(texts: list[str], scorer: str) -> list[float]:
    if scorer == "dictionary":
        return [_lexicon_score(text) for text in texts]
    scores, backend = score_texts(texts)
    if backend != "kr-finbert":
        raise SystemExit(f"감성 백엔드가 {backend}입니다. KR-FinBERT 환경에서 실행하세요.")
    return scores


def delta(days: list[dict], index: int) -> float:
    return abs(days[index]["score"] - days[index - 1]["score"])


def build_historical_track(window: list[dict], corpus: dict[str, list[dict]], backend: str) -> dict:
    """프론트 픽스처도 백엔드 news_tracks historical 계약으로 낸다.

    재사용하는 일별 CSV에는 기사별 점수가 없으므로 sentiment_std는
    0으로 지어내지 않고 null로 남긴다.
    """
    relevant_count = sum(day["articleCount"] for day in window)
    publishers = {
        item["press"]
        for day in window
        for item in day["items"]
        if item.get("press")
    }
    weighted_mean = round(
        sum(day["score"] * day["articleCount"] for day in window) / relevant_count,
        4,
    )
    timeline = []
    for day in window:
        day_publishers = {item["press"] for item in day["items"] if item.get("press")}
        timeline.append(
            {
                "status": "ok",
                "sentiment_mean": day["score"],
                "sentiment_std": None,
                "article_count": day["articleCount"],
                "publisher_count": len(day_publishers),
                "date": day["date"],
            }
        )
    start, end = window[0]["date"], window[-1]["date"]
    return {
        "schema_version": "1.0",
        "track": "historical",
        "scope": {"ticker": TICKER, "company_name": COMPANY},
        "source": "bigkinds",
        "as_of": f"{end}T23:59:59.999999+09:00",
        "backend": backend,
        "status": "ok",
        "coverage": {
            "fetched_count": sum(len(corpus[day["date"]]) for day in window),
            "relevant_count": relevant_count,
            "publisher_count": len(publishers),
            "newest_published_at": None,
            "lag_minutes": None,
        },
        "window": {
            "start": start,
            "end": end,
            "status": "ok",
            "sentiment_mean": weighted_mean,
            "sentiment_std": None,
            "article_count": relevant_count,
            "publisher_count": len(publishers),
        },
        "timeline": timeline,
        "articles": [],
    }


def main() -> None:
    args = parse_args()
    placeholder = args.scorer != "finbert" or args.limit is not None
    if args.daily_csv is not None and placeholder:
        raise SystemExit("플레이스홀더 결과는 일별 CSV에 쓰지 않습니다. 전수 KR-FinBERT로만 씁니다.")
    corpus = load_corpus()
    per_day = SETTINGS.max_daily_articles
    if args.limit is not None:
        per_day = max(1, min(per_day, args.limit // len(corpus)))
    logged = parse_daily_log(args.daily_log) if args.daily_log else None

    days: list[dict] = []
    for date, items in corpus.items():
        relevant = [items[index] for index in relevant_indices(items, COMPANY)][:per_day]
        if not relevant:
            # 기사 0건인 날의 0.0은 관측이 아니다. 변화량 분포에서도 뺀다.
            continue
        day = {"date": date, "articleCount": len(relevant), "items": relevant}
        if logged is None:
            day["scores"] = score([_text_of(item) for item in relevant], args.scorer)
            day["score"] = aggregate(day["scores"])[0]
            print(f"{date} n={len(relevant)} score={day['score']:+.4f}", file=sys.stderr, flush=True)
        else:
            if date not in logged or logged[date][0] != len(relevant):
                raise SystemExit(f"{date}: 일별 점수의 건수가 코퍼스 관련 기사 수({len(relevant)})와 다릅니다.")
            day["score"] = logged[date][1]
        days.append(day)

    if args.daily_csv is not None:
        write_daily_csv(args.daily_csv, days, args.daily_log)

    changes = [delta(days, index) for index in range(1, len(days))]
    p90 = round(statistics.quantiles(changes, n=10, method="inclusive")[-1], 4)
    # 화면 N07 판정과 같은 비교: 마지막 두 날 |Δ| >= 반올림된 p90
    qualifying = [
        index for index in range(WINDOW_DAYS - 1, len(days)) if delta(days, index) >= p90
    ]
    if not qualifying:
        raise SystemExit("20일 창을 채울 수 있는 |Δ| >= p90 날짜가 없습니다.")
    end = qualifying[-1]
    window = days[end - WINDOW_DAYS + 1 : end + 1]
    last = window[-1]

    series = {
        "days": [
            {"date": day["date"], "score": day["score"], "articleCount": day["articleCount"]}
            for day in window
        ],
        "headlines": [],
    }
    scored = sum(day["articleCount"] for day in days)

    header: list[str] = []
    if placeholder:
        scorer_label = "사전 기반" if args.scorer == "dictionary" else "FinBERT"
        sample = f"{args.limit}건 표본" if args.limit is not None else "전수"
        header.append(f"// PLACEHOLDER — {scorer_label} {sample}. FinBERT 전수 결과로 교체 대기 중.")
    backend = (
        f"kr-finbert ({SETTINGS.finbert_model})"
        if args.scorer == "finbert"
        else "dictionary (value_pipeline.sentiment 사전 폴백 39단어)"
    )
    flags = f"--scorer {args.scorer}" + (f" --limit {args.limit}" if args.limit is not None else "")
    if args.daily_log:
        flags += f" --daily-log {display_path(args.daily_log)}"
    previous = window[-2]
    payload = build_historical_track(
        window,
        corpus,
        "kr-finbert" if args.scorer == "finbert" else "dictionary",
    )
    track_out = PROVIDERS / f"sentiment-{TICKER}.json"
    track_out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if TICKER != "005930":
        print(f"wrote {track_out} (days={len(days)}, scored={scored}, p90={p90}, window_end={last['date']})", file=sys.stderr)
        return
    last_scores = last.get("scores") or score([_text_of(item) for item in last["items"]], args.scorer)
    if "scores" not in last and abs(aggregate(last_scores)[0] - last["score"]) > 1e-4:
        raise SystemExit(f"{last['date']}: 재채점 평균이 일별 점수와 다릅니다.")
    ranked = sorted(zip(last["items"], last_scores), key=lambda pair: abs(pair[1]), reverse=True)
    series["headlines"] = [
        {"date": last["date"], "title": item["title"], "press": item["press"]}
        for item, _score in ranked[:HEADLINES]
    ]
    OUT.write_text(
        "\n".join(
            [
                *header,
                "// FIXTURE — 실데이터 아님.",
                "// 단, 삼성전자(005930) 감성 점수와 기사 제목은 실제 기사에서 집계했다. 자동 생성 파일이므로 직접 고치지 않는다.",
                f"// 생성: python frontend/scripts/build_sentiment_fixture.py {flags}",
                "//       (backend value_pipeline news_agent와 같은 규칙)",
                f"// 원천: backend/analysis/text/data/processed/news_corpus.csv, {days[0]['date']} ~ {days[-1]['date']} 중 관련 기사가 있는 {len(days)}일, 채점 {scored}건",
                f"// 감성 백엔드: {backend}, 기사 텍스트 = 제목 + 본문 앞 {BODY_CHARS}자",
                f"// N07 임계: 일별 감성 변화량 |Δ| {len(changes)}개의 상위 10% 분위수(p90, inclusive 보간) = {p90}",
                f"// 20일 창: {window[0]['date']} ~ {last['date']}. |Δ| >= p90인 가장 늦은 날로 끝나게 실제 날짜 구간을 골랐다.",
                f"//   마지막 날 |Δ| = {delta(window, len(window) - 1):.4f} ({previous['date']} {previous['score']:+.4f} → {last['date']} {last['score']:+.4f})",
                "// 데모 기준일(2025-12-30)은 코퍼스 기간 안이라 주가 기간(최근 60거래일)과 겹친다.",
                "",
                'import type { SentimentSeries } from "./index";',
                "",
                f"export const SENTIMENT_SHIFT_P90 = {p90};",
                "",
                "export const SAMSUNG_SENTIMENT: SentimentSeries = "
                + json.dumps(series, ensure_ascii=False, indent=2)
                + ";",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(
        f"wrote {OUT} and {track_out} "
        f"(days={len(days)}, scored={scored}, p90={p90}, window_end={last['date']})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

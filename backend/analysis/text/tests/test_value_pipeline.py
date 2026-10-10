"""value_pipeline 오케스트레이션 검증.

- 빅카인즈 point-in-time 뉴스 로더(preprocess.load_daily_news)
- 소셜 제거 후 News + Financial 2-에이전트 + 규칙 기반 validation LangGraph
- AGENTS.md 계약: 점수 산출 100% 결정론, LLM은 라벨·추출·설명만

검증 기준 전문: backend/analysis/text/VALUE_PIPELINE_VALIDATION.md
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path

import pandas as pd
import pytest
from analysis.text import preprocess as pp
from analysis.text.value_pipeline import agents as agents_mod
from analysis.text.value_pipeline import collectors as collectors_mod
from analysis.text.value_pipeline import graph as graph_mod
from analysis.text.value_pipeline import llm as llm_mod
from analysis.text.value_pipeline import metrics as metrics_mod
from analysis.text.value_pipeline import run as run_mod
from analysis.text.value_pipeline import schema as schema_mod
from analysis.text.value_pipeline import sentiment as sentiment_mod
from analysis.text.value_pipeline import staleness as staleness_mod


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """테스트는 .env의 실제 GEMINI_API_KEY에 영향받지 않아야 한다(헤르메틱).

    환경변수 patch로는 안 된다 — config.load_dotenv()가 import 시점에 .env를
    주입하고, SETTINGS는 frozen dataclass, get_llm()은 lru_cache라서 무력하다.
    agents가 부르는 structured 자체를 막아야 한다.
    """
    monkeypatch.setattr(agents_mod, "structured", lambda prompt, schema: None)


def _write_bigkinds(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_excel(path, index=False, engine="openpyxl")


def _fin(**over) -> dict:
    """정합적인 표준 재무 dict (항등식 자산=부채+자본 성립)."""
    base = {
        "revenue": 3.0e14, "revenue_prev": 2.7e14, "net_income": 4.0e13,
        "total_assets": 4.0e14, "total_liabilities": 1.0e14, "total_equity": 3.0e14,
        "current_assets": 2.0e14, "current_liabilities": 5.0e13,
        "shares_outstanding": 5.97e9, "price": 60000.0,
        "sector_per": 15.0, "sector_pbr": 1.5, "company_name": "삼성전자",
        "fiscal_year": 2021,
    }
    base.update(over)
    return base


def _patch_collectors(monkeypatch: pytest.MonkeyPatch, news: list, fin: dict) -> None:
    monkeypatch.setattr(
        graph_mod.collectors, "collect_news", lambda t, n, d: (news, "bigkinds")
    )
    monkeypatch.setattr(
        graph_mod.collectors, "collect_prior_news", lambda t, n, d, c: []
    )
    monkeypatch.setattr(
        graph_mod.collectors, "collect_financials", lambda t, d: (fin, "dart")
    )


def test_finbert_batch_scores_all_texts_in_one_call_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], int]] = []

    def classifier(texts: list[str], *, batch_size: int):
        calls.append((texts, batch_size))
        return [
            [{"label": "positive", "score": 0.8}, {"label": "negative", "score": 0.2}],
            [{"label": "positive", "score": 0.1}, {"label": "negative", "score": 0.7}],
        ]

    monkeypatch.setattr(sentiment_mod, "_load_finbert", lambda: classifier)

    scores, backend = sentiment_mod.score_texts(["첫 기사", "둘째 기사"])

    assert calls == [(["첫 기사", "둘째 기사"], 16)]
    assert scores == pytest.approx([0.6, -0.6])
    assert backend == "kr-finbert"


def test_require_finbert_raises_instead_of_using_lexicon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sentiment_mod, "_load_finbert", lambda: None)

    with pytest.raises(sentiment_mod.SentimentBackendError, match="KR-FinBERT"):
        sentiment_mod.score_texts(["상승 호재"], require_finbert=True)


# ── Point-in-time 뉴스 로더 ────────────────────────────────────────
def test_load_daily_news_filters_date_dedup_and_exclusion(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_bigkinds(
        data_dir / "005930_삼성전자_20220101-20221231.xlsx",
        [
            {"뉴스 식별자": "n1", "일자": 20220615, "언론사": "매일경제",
             "제목": "삼성전자 흑자 전환", "본문": "영업이익이 크게 늘었다.",
             "URL": "http://x/n1", "분석제외 여부": ""},
            {"뉴스 식별자": "n2", "일자": 20220615, "언론사": "한국경제",
             "제목": "메모리 시황 개선", "본문": "가격 반등.",
             "URL": "http://x/n2", "분석제외 여부": ""},
            # 같은 식별자 중복 → dedup
            {"뉴스 식별자": "n1", "일자": 20220615, "언론사": "매일경제",
             "제목": "삼성전자 흑자 전환", "본문": "영업이익이 크게 늘었다.",
             "URL": "http://x/n1", "분석제외 여부": ""},
            # 다른 날짜 → 필터
            {"뉴스 식별자": "n3", "일자": 20220616, "언론사": "서울경제",
             "제목": "다음날 기사", "본문": "본문", "URL": "http://x/n3",
             "분석제외 여부": ""},
            # 분석제외 → 제거
            {"뉴스 식별자": "n4", "일자": 20220615, "언론사": "이데일리",
             "제목": "제외 대상 기사", "본문": "본문", "URL": "http://x/n4",
             "분석제외 여부": "Y"},
        ],
    )

    items = pp.load_daily_news("삼성전자", "2022-06-15", data_dir=data_dir)

    assert [it["title"] for it in items] == ["삼성전자 흑자 전환", "메모리 시황 개선"]
    assert all(it["date"] == "2022-06-15" for it in items)
    assert items[0]["summary"] == "영업이익이 크게 늘었다."  # 본문이 summary로 매핑
    assert items[0]["url"] == "http://x/n1"
    assert items[0]["press"] == "매일경제"


def test_load_daily_news_emits_news_id_for_grounding(tmp_path: Path) -> None:
    """key_events 출처 인용(그라운딩)의 앵커 — 100% 채워져야 한다."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_bigkinds(
        data_dir / "005930_삼성전자_20220101-20221231.xlsx",
        [
            {"뉴스 식별자": "n1", "일자": 20220615, "언론사": "매일경제",
             "제목": "삼성전자 흑자", "본문": "본문", "URL": "", "분석제외 여부": ""},
            # 식별자 없음 → generated: 해시 폴백
            {"뉴스 식별자": "", "일자": 20220615, "언론사": "한국경제",
             "제목": "식별자 없는 기사", "본문": "본문", "URL": "", "분석제외 여부": ""},
        ],
    )
    items = pp.load_daily_news("삼성전자", "2022-06-15", data_dir=data_dir)
    assert len(items) == 2
    assert all(it["news_id"] for it in items)  # 결측 없음
    assert any(it["news_id"].startswith("generated:") for it in items)


def test_load_daily_news_limit_none_returns_all(tmp_path: Path) -> None:
    """관련성 필터가 전량을 봐야 하므로 limit=None 지원이 필요하다."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_bigkinds(
        data_dir / "005930_삼성전자_20220101-20221231.xlsx",
        [
            {"뉴스 식별자": f"n{i}", "일자": 20220615, "언론사": "매일경제",
             "제목": f"기사 {i}", "본문": "본문", "URL": "", "분석제외 여부": ""}
            for i in range(40)
        ],
    )
    assert len(pp.load_daily_news("삼성전자", "2022-06-15", data_dir=data_dir)) == 30
    assert len(
        pp.load_daily_news("삼성전자", "2022-06-15", data_dir=data_dir, limit=None)
    ) == 40


def test_load_news_range_reads_each_workbook_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """연 단위 그래프가 같은 Excel을 날짜별로 재파싱하지 않는다."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    workbook = data_dir / "005930_삼성전자_20220101-20221231.xlsx"
    _write_bigkinds(
        workbook,
        [
            {"뉴스 식별자": "n1", "일자": 20220615, "언론사": "매일경제",
             "제목": "삼성전자 흑자", "본문": "실적 개선", "URL": "", "분석제외 여부": ""},
            {"뉴스 식별자": "n2", "일자": 20220616, "언론사": "한국경제",
             "제목": "삼성전자 수요", "본문": "수요 둥화", "URL": "", "분석제외 여부": ""},
        ],
    )
    original = pp._read_workbook_uncached
    reads: list[Path] = []

    def counted(path: Path):
        reads.append(path)
        return original(path)

    pp._read_workbook_cached.cache_clear()
    monkeypatch.setattr(pp, "_read_workbook_uncached", counted)

    items = pp.load_news_range(
        "삼성전자",
        "2022-06-15",
        "2022-06-16",
        data_dir=data_dir,
        ticker="005930",
    )

    assert reads == [workbook]
    assert [item["date"] for item in items] == ["2022-06-15", "2022-06-16"]


def test_load_daily_news_nfc_company_match_and_missing_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_bigkinds(
        data_dir / "005930_삼성전자_20220101-20221231.xlsx",
        [{"뉴스 식별자": "n1", "일자": 20220301, "언론사": "매일경제",
          "제목": "기사", "본문": "본문", "URL": "", "분석제외 여부": ""}],
    )
    # 정규화 형태가 달라도(NFC) 회사명 매칭
    assert pp.find_news_workbook("삼성전자", "2022-03-01", data_dir) is not None
    # 종목코드(ticker)로도 매칭 — 회사명이 비어도 코드로 파일을 찾는다
    assert pp.find_news_workbook("", "2022-03-01", data_dir, ticker="005930") is not None
    assert pp.load_daily_news("", "2022-03-01", data_dir=data_dir, ticker="005930")
    # 기간 밖 날짜 → 파일 없음 → 빈 리스트
    assert pp.load_daily_news("삼성전자", "2019-01-01", data_dir=data_dir) == []
    # 다른 회사/코드 → 빈 리스트
    assert pp.load_daily_news("SK하이닉스", "2022-03-01", data_dir=data_dir) == []
    assert pp.find_news_workbook("", "2022-03-01", data_dir, ticker="000660") is None


def test_load_daily_news_supports_legacy_filename(tmp_path: Path) -> None:
    """구버전 파일명({회사명}_{기간}.xlsx)도 계속 인식되어야 한다."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_bigkinds(
        data_dir / "삼성전자_20220101-20221231.xlsx",
        [{"뉴스 식별자": "n1", "일자": 20220301, "언론사": "매일경제",
          "제목": "구버전 파일 기사", "본문": "본문", "URL": "", "분석제외 여부": ""}],
    )
    items = pp.load_daily_news("삼성전자", "2022-03-01", data_dir=data_dir)
    assert [it["title"] for it in items] == ["구버전 파일 기사"]


def test_load_daily_news_reads_only_ticker_directory(tmp_path: Path) -> None:
    """종목별 하위 디렉터리(data/<종목코드>/)가 있으면 그 종목만 읽어 혼입을 막는다.

    코퍼스 빌더와 동일한 <기준>/<종목코드>/ 해석을 point-in-time 로더도 공유해야
    두 소비자가 서로 다른 파일을 보고 조용히 폴백하는 사고가 없다.
    """
    data_dir = tmp_path / "data"
    (data_dir / "005930").mkdir(parents=True)
    (data_dir / "035720").mkdir()
    _write_bigkinds(
        data_dir / "005930" / "삼성전자_20220101-20221231.xlsx",
        [{"뉴스 식별자": "samsung", "일자": 20220615, "언론사": "매일경제",
          "제목": "삼성 기사", "본문": "본문", "URL": "", "분석제외 여부": ""}],
    )
    _write_bigkinds(
        data_dir / "035720" / "카카오_20220101-20221231.xlsx",
        [{"뉴스 식별자": "kakao", "일자": 20220615, "언론사": "한국경제",
          "제목": "카카오 기사", "본문": "본문", "URL": "", "분석제외 여부": ""}],
    )

    # 종목 폴더가 종목을 특정하므로 기간만 맞으면 반환한다(회사명 불일치해도 무관).
    assert pp.find_news_workbook("삼성전자", "2022-06-15", data_dir, ticker="005930") == (
        data_dir / "005930" / "삼성전자_20220101-20221231.xlsx"
    )
    samsung = pp.load_daily_news(
        "삼성전자", "2022-06-15", data_dir=data_dir, ticker="005930"
    )
    assert [it["title"] for it in samsung] == ["삼성 기사"]

    kakao = pp.load_daily_news(
        "카카오", "2022-06-15", data_dir=data_dir, ticker="035720"
    )
    assert [it["title"] for it in kakao] == ["카카오 기사"]

    # 종목 폴더가 있는데 요청 종목 폴더가 없으면 point-in-time은 예외 없이 폴백(None → []).
    assert (
        pp.load_daily_news("네이버", "2022-06-15", data_dir=data_dir, ticker="035420")
        == []
    )


def test_parse_workbook_name_new_and_legacy() -> None:
    assert pp._parse_workbook_name("005930_삼성전자_20220101-20221231.xlsx") == (
        "005930", "삼성전자", "20220101", "20221231",
    )
    assert pp._parse_workbook_name("삼성전자_20220101-20221231.xlsx") == (
        "", "삼성전자", "20220101", "20221231",
    )
    assert pp._parse_workbook_name("아무거나.xlsx") is None


# ── Point-in-time 재무 (look-ahead 방지) ──────────────────────────
def test_select_fiscal_year_is_point_in_time() -> None:
    """사업보고서는 사업연도 종료 후 90일(익년 3/31) 내 제출 → 4/1부터 공시."""
    f = collectors_mod.select_fiscal_year
    assert f("2022-06-15") == 2021
    assert f("2022-04-01") == 2021   # 경계: 제출기한 익일
    assert f("2022-03-31") == 2020   # 아직 FY2021 미공시
    assert f("2022-01-01") == 2020
    assert f("2022-12-31") == 2021


def test_select_fiscal_year_does_not_depend_on_today() -> None:
    """회귀 못박기: 과거엔 today().year-1 을 써서 4년 룩어헤드가 났다."""
    assert collectors_mod.select_fiscal_year("2022-06-15") == 2021
    assert collectors_mod.select_fiscal_year("2022-06-15") != dt.date.today().year - 1


def test_opendartreader_exposes_callable_client() -> None:
    """설치된 Python·패키지 버전에 맞는 DART 클라이언트를 사용한다."""
    assert callable(collectors_mod.OpenDartReader)


class _FakeDart:
    """OpenDartReader 대역."""

    seen: dict = {}

    def __init__(self, key):
        pass

    def finstate_all(self, corp, bsns_year, **kw):
        _FakeDart.seen["finstate_year"] = bsns_year
        return pd.DataFrame([
            {"account_nm": "매출액", "thstrm_amount": "300", "frmtrm_amount": "270"},
            {"account_nm": "자산총계", "thstrm_amount": "400", "frmtrm_amount": "380"},
        ])

    def report(self, corp, kind, year, **kw):
        _FakeDart.seen["report_year"] = year
        return pd.DataFrame([{"istc_totqy": "1000"}])


def test_fetch_dart_financials_uses_point_in_time_fiscal_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeDart.seen = {}
    monkeypatch.setattr(collectors_mod, "OpenDartReader", _FakeDart)
    monkeypatch.setattr(
        collectors_mod, "SETTINGS",
        dataclasses.replace(collectors_mod.SETTINGS, dart_api_key="x"),
    )
    out = collectors_mod._fetch_dart_financials("005930", "2022-06-15")

    assert _FakeDart.seen["finstate_year"] == 2021
    # 발행주식수는 사업연도가 아니라 스냅샷 기준연도(SHARES_ASOF_YEAR) 공시 기준 —
    # FDR 수정주가와 분할 기준을 맞추기 위해서다 (액면분할 50배 왜곡 회귀 방지).
    assert _FakeDart.seen["report_year"] == collectors_mod.SETTINGS.shares_asof_year
    assert out["fiscal_year"] == 2021
    assert out["shares_outstanding"] == 1000.0


def test_dart_falls_back_to_separate_statements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """연결(CFS)이 없는 법인은 별도(OFS)로 폴백한다.

    실측: 에코프로비엠 FY2018~19는 자회사가 없어 연결재무제표가 존재하지 않는다.
    """

    class _OfsOnlyDart:
        seen: list[str] = []

        def __init__(self, key):
            pass

        def finstate_all(self, corp, bsns_year, fs_div="CFS", **kw):
            _OfsOnlyDart.seen.append(fs_div)
            if fs_div == "CFS":
                return None  # 연결 없음
            return pd.DataFrame([
                {"account_nm": "매출액", "thstrm_amount": "300", "frmtrm_amount": "270"},
            ])

        def report(self, corp, kind, year, **kw):
            return pd.DataFrame([{"se": "보통주", "istc_totqy": "1000"}])

    _OfsOnlyDart.seen = []
    monkeypatch.setattr(collectors_mod, "OpenDartReader", _OfsOnlyDart)
    monkeypatch.setattr(
        collectors_mod, "SETTINGS",
        dataclasses.replace(collectors_mod.SETTINGS, dart_api_key="x"),
    )
    out = collectors_mod._fetch_dart_financials("247540", "2019-06-03")

    assert _OfsOnlyDart.seen[:2] == ["CFS", "OFS"]  # 연결 시도 → 별도 폴백
    assert out["revenue"] == 300.0


def test_parse_common_shares_skips_dash_rows_and_prefers_common() -> None:
    """FY2015 실응답처럼 값이 '-'뿐인 프레임은 None, 정상 프레임은 보통주 행."""
    dash_only = pd.DataFrame(
        [{"se": "합계", "istc_totqy": "-"}, {"se": "비고", "istc_totqy": "-"}]
    )
    assert collectors_mod._parse_common_shares(dash_only) is None

    normal = pd.DataFrame([
        {"se": "보통주", "istc_totqy": "140,679,337"},
        {"se": "우선주", "istc_totqy": "20,513,427"},
        {"se": "합계", "istc_totqy": "161,192,764"},
    ])
    assert collectors_mod._parse_common_shares(normal) == 140679337.0
    # 보통주 행이 없으면 합계로 폴백
    total_only = pd.DataFrame([{"se": "합계", "istc_totqy": "161,192,764"}])
    assert collectors_mod._parse_common_shares(total_only) == 161192764.0
    assert collectors_mod._parse_common_shares(None) is None


class _SharesDart:
    """주식총수 조회 대역 — 탐색 순서를 기록하고, 특정 연도만 값이 없다."""

    seen: list[int] = []
    empty_years: set[int] = set()

    def __init__(self, key):
        pass

    def report(self, corp, kind, year, **kw):
        _SharesDart.seen.append(year)
        if year in _SharesDart.empty_years:
            return pd.DataFrame([{"se": "합계", "istc_totqy": "-"}])
        return pd.DataFrame([{"se": "보통주", "istc_totqy": "5,969,782,550"}])


def test_latest_shares_searches_back_past_empty_years(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """기준연도가 '-'뿐이면(공시 전 등) 유효값이 나올 때까지 거슬러 찾는다."""
    asof = collectors_mod.SETTINGS.shares_asof_year
    _SharesDart.seen, _SharesDart.empty_years = [], {asof}
    monkeypatch.setattr(collectors_mod, "OpenDartReader", _SharesDart)
    monkeypatch.setattr(
        collectors_mod, "SETTINGS",
        dataclasses.replace(collectors_mod.SETTINGS, dart_api_key="x"),
    )
    assert collectors_mod._fetch_latest_shares("005930") == 5969782550.0
    assert _SharesDart.seen == [asof, asof - 1]  # 내림차순 탐색


def test_latest_shares_do_not_depend_on_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """회귀 못박기(PR #67 리뷰 1): 기준연도가 today()에 묶이면 실행 연도에 따라
    같은 입력의 per/pbr → signal이 달라져 재현성이 깨진다. 탐색 시작 연도는
    SHARES_ASOF_YEAR 고정값이어야 한다."""
    _SharesDart.seen, _SharesDart.empty_years = [], set()
    monkeypatch.setattr(collectors_mod, "OpenDartReader", _SharesDart)
    monkeypatch.setattr(
        collectors_mod, "SETTINGS",
        dataclasses.replace(
            collectors_mod.SETTINGS, dart_api_key="x", shares_asof_year=2023
        ),
    )
    collectors_mod._fetch_latest_shares("005930")
    assert _SharesDart.seen == [2023]  # today가 아니라 고정 스냅샷 연도에서 시작
    assert _SharesDart.seen[0] != dt.date.today().year - 1


def test_latest_shares_warns_when_snapshot_year_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """고정 연도가 낡으면(이후 분할 미반영 위험) 숫자는 유지하되 경고를 낸다."""
    _SharesDart.seen, _SharesDart.empty_years = [], set()
    monkeypatch.setattr(collectors_mod, "OpenDartReader", _SharesDart)
    monkeypatch.setattr(
        collectors_mod, "SETTINGS",
        dataclasses.replace(
            collectors_mod.SETTINGS, dart_api_key="x", shares_asof_year=2020
        ),
    )
    with pytest.warns(UserWarning, match="낡았습니다"):
        assert collectors_mod._fetch_latest_shares("005930") == 5969782550.0
    assert _SharesDart.seen == [2020]  # 경고만 — 탐색 기준은 고정값 유지(재현성)


def test_validation_catches_split_regime_mismatch() -> None:
    """수정주가(분할 반영) × 분할 전 주식수 → per/pbr이 분할 배수만큼 과소.

    실사고: 삼성 50:1 분할 소급수정 주가 37,460원 × FY2016 주식수 1.4억 주
    → per 0.28, pbr 0.03이 옛 하한(0.1/0.005)을 통과해 ok=true로 새어나갔다.
    """
    bad = _fin(shares_outstanding=1.4e8, price=37460.0)
    v = _validate(_OK_NEWS, {"metrics": metrics_mod.compute_metrics(bad),
                             "fiscal_year": 2021}, bad)
    assert not v["ok"]
    assert any("상식 범위" in e for e in v["errors"])


def test_collect_financials_raises_when_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """재무 결측 → 가짜 SELL 대신 명시적 중단."""
    monkeypatch.setattr(
        collectors_mod, "SETTINGS",
        dataclasses.replace(collectors_mod.SETTINGS, dart_api_key=None),
    )
    monkeypatch.setattr(collectors_mod, "_load_sample", lambda name: None)
    with pytest.raises(collectors_mod.FinancialsUnavailableError):
        collectors_mod.collect_financials("005930", "2022-06-15")


# ── 결정론 계약 (AGENTS.md '정량/정성 분리') ───────────────────────
def test_llm_schemas_have_no_score_or_selection_field() -> None:
    """LLM 출력 계약에 점수도 '채점 대상 선택'도 없어야 한다.

    라벨이 채점 대상을 정하면 그건 곧 점수를 정하는 것이다(PR #22 블로커).
    남은 필드는 전부 사람이 읽는 텍스트여야 한다.
    """
    assert set(agents_mod._NewsExtract.model_fields) == {"key_events"}
    assert set(agents_mod._Reason.model_fields) == {"reasoning"}
    # 관련성 판정 스키마가 되살아나면 안 된다
    assert not hasattr(agents_mod, "_NewsLabels")
    assert not hasattr(agents_mod, "_RelevanceLabel")


def test_relevance_is_deterministic_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """관련성 판정은 LLM을 아예 호출하지 않는다 — structured가 죽어도 동작해야 한다."""
    def boom(prompt, schema):
        raise AssertionError("관련성 경로에서 LLM이 호출되면 안 된다")

    news = [
        {"news_id": "n1", "title": "삼성전자 흑자 확대", "summary": "실적 개선",
         "url": "", "press": "", "date": "2022-06-15"},
        {"news_id": "n2", "title": "두산 반도체 투자", "summary": "1조원",
         "url": "", "press": "", "date": "2022-06-15"},
    ]
    monkeypatch.setattr(agents_mod, "_extract_events", lambda items, company: [])
    monkeypatch.setattr(agents_mod, "structured", boom)
    out = agents_mod.news_agent(
        {"raw_news": news, "company_name": "삼성전자", "ticker": "005930"}
    )["news_result"]
    assert out["article_count"] == 1  # 두산 기사 제외


def test_llm_text_cannot_change_any_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENTS.md 계약 테스트: LLM 텍스트가 어떤 숫자도 바꾸지 못한다."""
    news = [{"news_id": "n1", "title": "삼성전자 흑자 확대", "summary": "",
             "url": "", "press": "", "date": "2022-06-15"}]
    _patch_collectors(monkeypatch, news, _fin())

    calls = {"n": 0}

    def fake_structured(prompt, schema):
        calls["n"] += 1
        if schema is agents_mod._Reason:
            return agents_mod._Reason(reasoning=f"호출 {calls['n']}번째 근거 문장")
        return agents_mod._NewsExtract(key_events=[f"삼성전자 이벤트 {calls['n']}"])

    monkeypatch.setattr(agents_mod, "structured", fake_structured)
    a = graph_mod.run_pipeline("005930", "2022-06-15", "삼성전자")
    b = graph_mod.run_pipeline("005930", "2022-06-15", "삼성전자")

    numeric = [
        "news_sentiment", "news_impact_score", "news_sentiment_std", "news_staleness",
        "financial_health_score", "valuation_score", "composite_score",
        "value_investment_signal", "confidence", "article_count", "article_count_raw",
    ]
    for k in numeric:
        assert a[k] == b[k], f"{k}가 LLM 텍스트에 따라 달라짐 — 결정론 위반"
    assert a["reasoning"] != b["reasoning"]  # 설명 텍스트만 달라진다


def test_scores_identical_with_and_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM을 켜든 끄든 모든 숫자가 같아야 한다 — LLM이 점수 경로 밖이라는 증거."""
    news = [
        {"news_id": "n1", "title": "삼성전자 흑자 확대", "summary": "실적 개선",
         "url": "", "press": "", "date": "2022-06-15"},
        {"news_id": "n2", "title": "두산 반도체 투자", "summary": "1조원",
         "url": "", "press": "", "date": "2022-06-15"},
    ]
    _patch_collectors(monkeypatch, news, _fin())

    monkeypatch.setattr(agents_mod, "structured", lambda p, s: None)
    off = graph_mod.run_pipeline("005930", "2022-06-15", "삼성전자")

    def fake(prompt, schema):
        if schema is agents_mod._Reason:
            return agents_mod._Reason(reasoning="LLM이 쓴 근거")
        return agents_mod._NewsExtract(key_events=["삼성전자 흑자 확대 이벤트"])

    monkeypatch.setattr(agents_mod, "structured", fake)
    on = graph_mod.run_pipeline("005930", "2022-06-15", "삼성전자")

    for k in off:
        if k in ("reasoning", "key_events"):
            continue
        assert off[k] == on[k], f"{k}가 LLM 유무로 달라짐 — LLM이 점수 경로에 있음"


def _synthesis_state() -> dict:
    return {
        "ticker": "005930",
        "date": "2022-06-15",
        "company_name": "삼성전자",
        "news_result": {
            "news_sentiment": -0.1,
            "news_impact_score": 6,
            "news_sentiment_std": 0.2,
            "staleness": 0.1,
            "key_events": [],
            "article_count": 1,
            "article_count_raw": 1,
        },
        "financial_result": {
            "valuation_score": 5.0,
            "financial_health_score": 8.0,
            "metrics": {},
            "fiscal_year": 2021,
        },
        "news_source": "bigkinds",
        "financial_source": "dart",
        "validation": {"ok": True, "errors": [], "warnings": []},
    }


def test_synthesis_rejects_behavior_advice(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 설명이 사용자 행동을 제안하면 결정론적 수치 템플릿으로 대체한다."""
    seen: dict[str, str] = {}
    unsafe = "현재는 관망하며 보유 포지션 \n 을 유지하는 것이 합리적입니다."

    def fake_structured(prompt, schema):
        seen["prompt"] = prompt
        assert schema is agents_mod._Reason
        return agents_mod._Reason(reasoning=unsafe)

    monkeypatch.setattr(agents_mod, "structured", fake_structured)
    result = agents_mod.synthesis_agent(_synthesis_state())["final"]

    assert result["reasoning"] != unsafe
    assert "결정론적 구간 라벨" in result["reasoning"]
    assert "행동을 권하거나 제안하지 말고" in seen["prompt"]
    assert agents_mod._contains_behavior_advice("신규진입을 고려할 수 있습니다.")


def test_synthesis_allows_factual_action_word(monkeypatch: pytest.MonkeyPatch) -> None:
    """기사 속 매도처럼 투자자 행동 지시가 아닌 사실 서술은 보존한다."""
    factual = (
        "외국인 매도 압력은 뉴스 감성을 낮췄고 "
        "재무건전성 점수는 이를 일부 상쇄했습니다."
    )
    monkeypatch.setattr(
        agents_mod,
        "structured",
        lambda prompt, schema: agents_mod._Reason(reasoning=factual),
    )

    result = agents_mod.synthesis_agent(_synthesis_state())["final"]

    assert result["reasoning"] == factual


def test_run_pipeline_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    news = [{"news_id": "n1", "title": "삼성전자 흑자 확대", "summary": "",
             "url": "", "press": "", "date": "2022-06-15"}]
    _patch_collectors(monkeypatch, news, _fin())
    a = graph_mod.run_pipeline("005930", "2022-06-15", "삼성전자")
    b = graph_mod.run_pipeline("005930", "2022-06-15", "삼성전자")
    assert a == b  # 결정론(같은 입력 → 같은 출력)


# ── 그래프 구조 ────────────────────────────────────────────────────
def test_graph_has_news_financial_validation_agents() -> None:
    nodes = set(graph_mod.build_graph().get_graph().nodes)
    assert {"news_agent", "financial_agent", "validation_agent", "synthesis_agent"} <= nodes
    assert "social_agent" not in nodes


def test_pipeline_state_has_no_social_keys() -> None:
    keys = set(graph_mod.PipelineState.__annotations__)
    assert not any("social" in k for k in keys)


def test_schema_has_no_social_analysis_or_fields() -> None:
    assert not hasattr(schema_mod, "SocialAnalysis")
    fields = set(schema_mod.ValueSignal.model_fields)
    assert not any("social" in f for f in fields)
    assert "sentiment_divergence" not in fields


# ── 출력 계약 ──────────────────────────────────────────────────────
_EXPECTED_FIELDS = {
    "ticker", "date", "company_name",
    "news_sentiment", "news_impact_score", "news_sentiment_std", "news_staleness",
    "key_events", "article_count", "article_count_raw",
    "financial_health_score", "valuation_score", "financial_metrics",
    "financial_fiscal_year",
    "composite_score", "value_investment_signal", "confidence", "reasoning",
    "news_source", "financial_source", "validation",
}


def test_value_signal_field_contract() -> None:
    assert set(schema_mod.ValueSignal.model_fields) == _EXPECTED_FIELDS
    # 제거된 필드가 되살아나지 않도록
    for gone in ("data_quality", "sentiment_backend", "llm_used"):
        assert gone not in schema_mod.ValueSignal.model_fields


def test_row_is_self_auditing(monkeypatch: pytest.MonkeyPatch) -> None:
    """행 하나만 보고 composite·signal을 재계산할 수 있어야 한다(화이트박스)."""
    news = [{"news_id": "n1", "title": "삼성전자 흑자 확대", "summary": "",
             "url": "", "press": "", "date": "2022-06-15"}]
    _patch_collectors(monkeypatch, news, _fin())
    out = graph_mod.run_pipeline("005930", "2022-06-15", "삼성전자")

    composite = (
        out["valuation_score"] * 0.6
        + out["financial_health_score"] * 0.4
        + out["news_sentiment"] * (out["news_impact_score"] / 10.0) * 2.0
    )
    composite = max(0.0, min(10.0, composite))
    assert out["composite_score"] == pytest.approx(composite, abs=1e-3)
    assert out["value_investment_signal"] == agents_mod._to_signal(composite)


def test_run_pipeline_news_and_financial_only(monkeypatch: pytest.MonkeyPatch) -> None:
    news = [
        {"news_id": "n1", "title": "삼성전자 사상 최대 실적 흑자",
         "summary": "매출 급등, 수주 확대", "url": "", "press": "매일경제",
         "date": "2022-06-15"},
        {"news_id": "n2", "title": "삼성전자 메모리 반등 기대", "summary": "업황 개선",
         "url": "", "press": "한국경제", "date": "2022-06-15"},
    ]
    _patch_collectors(monkeypatch, news, _fin())
    out = graph_mod.run_pipeline("005930", "2022-06-15", "삼성전자")

    assert not any("social" in k for k in out)
    assert "data_quality" not in out

    assert out["ticker"] == "005930"
    assert out["company_name"] == "삼성전자"
    assert out["value_investment_signal"] in {
        "STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"
    }
    assert 0.0 <= out["confidence"] <= 1.0
    assert 0.0 <= out["composite_score"] <= 10.0
    assert out["article_count"] == 2
    assert out["news_source"] == "bigkinds"
    assert out["financial_source"] == "dart"
    assert out["financial_fiscal_year"] == 2021


# ── 관련성 필터 (결정론 규칙) ──────────────────────────────────────
def test_relevance_key_override_for_group_named_coverage() -> None:
    """접미사 규칙으로 안 잡히는 종목은 override 테이블로 명시한다.

    에코프로비엠은 언론이 그룹명 '에코프로'로 쓰는 기사가 많다
    (실측: 전량 탈락하던 1,010일 중 126일 복구).
    """
    assert agents_mod.relevance_key("에코프로비엠") == "에코프로"
    news = [{"news_id": "n1", "title": "에코프로 시가총액 11조원 돌파",
             "summary": "공매도 급등락", "url": "", "press": "", "date": "2023-03-15"}]
    assert agents_mod.relevant_indices(news, "에코프로비엠") == [0]


def test_validation_allows_retained_earnings_above_equity() -> None:
    """이익잉여금 > 자본총계는 회계 오류가 아니다 — 자기주식 차감 때문.

    실측: 네이버 FY2022 이익잉여금 23.65조 > 자본총계 23.45조인데 자산=부채+자본
    항등식은 0.0000% 오차로 성립. 옛 규칙이 멀쩡한 731행을 폐기했다.
    """
    naver = _fin(retained_earnings=3.1e14)  # 자본총계 3.0e14보다 크다
    v = _validate(_OK_NEWS, {"metrics": metrics_mod.compute_metrics(naver),
                             "fiscal_year": 2021}, naver)
    assert v["ok"], v["errors"]

    # 자산총계를 넘으면 그건 진짜 매핑 오류다
    broken = _fin(retained_earnings=5.0e14)  # 자산 4.0e14 초과
    v2 = _validate(_OK_NEWS, {"metrics": metrics_mod.compute_metrics(broken),
                              "fiscal_year": 2021}, broken)
    assert not v2["ok"]
    assert any("이익잉여금 ≤ 자산총계" in e for e in v2["errors"])


def test_relevance_key_strips_corporate_suffix() -> None:
    """'삼성전자'로 제목만 매칭하면 폭락일에 주가 기사만 남아 표본이 편향된다.

    실측(2022-06-15): 제목에 '삼성전자' → 10건, 감성 -0.80.
                      제목+본문에 '삼성' → 37건, 감성 -0.019 (LLM과 상관 0.99).
    """
    assert agents_mod.relevance_key("삼성전자") == "삼성"
    assert agents_mod.relevance_key("두산그룹") == "두산"
    assert agents_mod.relevance_key("카카오") == "카카오"   # 접미사 없음 → 그대로
    assert agents_mod.relevance_key("") == ""


def test_relevance_filter_excludes_unrelated_articles() -> None:
    news = [
        {"news_id": "n1", "title": "삼성전자 52주 신저가 5만전자 위기",
         "summary": "주가 급락 지속", "url": "", "press": "", "date": "2022-06-15"},
        {"news_id": "n2", "title": "구미대-희망디딤돌 경북센터 상호교류 업무협약 체결",
         "summary": "협약 성과 기대", "url": "", "press": "", "date": "2022-06-15"},
    ]
    assert agents_mod.relevant_indices(news, "삼성전자") == [0]


def test_relevance_filter_matches_body_not_just_title() -> None:
    """제목에 회사명이 없어도 본문에 있으면 관련 (ASML·롤러블폰 기사가 이 경우)."""
    news = [
        {"news_id": "n1", "title": "이재용, 네덜란드 총리 면담",
         "summary": "삼성 반도체 장비 수급 논의", "url": "", "press": "",
         "date": "2022-06-15"},
    ]
    assert agents_mod.relevant_indices(news, "삼성전자") == [0]


def test_relevance_filter_keeps_all_when_company_unknown() -> None:
    """회사명이 없으면 거를 근거가 없다 — 임의로 거르지 않는다."""
    news = [{"news_id": "n1", "title": "아무 기사", "summary": "", "url": "",
             "press": "", "date": "2022-06-15"}]
    assert agents_mod.relevant_indices(news, "") == [0]


def test_zero_relevant_articles_fails_validation_not_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전부 걸러지면 전량 복원하지 말 것 — 오염된 행이 정상처럼 보인다 (PR #22 블로커3)."""
    news = [{"news_id": "n1", "title": "두산 반도체 투자", "summary": "1조원",
             "url": "", "press": "", "date": "2022-06-15"}]
    _patch_collectors(monkeypatch, news, _fin())
    out = graph_mod.run_pipeline("005930", "2022-06-15", "삼성전자")

    assert out["article_count"] == 0        # 복원하지 않는다
    assert out["article_count_raw"] == 1
    assert not out["validation"]["ok"]      # 검증 실패로 드러난다
    assert any("무데이터" in e for e in out["validation"]["errors"])


def test_key_events_carry_source_news_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """HITL '근거·출처 항상 표시' + 환각 탐지."""
    news = [{"news_id": "n1", "title": "삼성전자 ASML 협력 논의", "summary": "반도체 장비",
             "url": "", "press": "", "date": "2022-06-15"}]
    monkeypatch.setattr(
        agents_mod, "_extract_events",
        lambda items, company: ["삼성전자 ASML 반도체 장비 협력", "날조 이벤트 xyzzy"],
    )
    out = agents_mod.news_agent(
        {"raw_news": news, "company_name": "삼성전자", "ticker": "005930"}
    )["news_result"]

    events = {e["event"]: e["news_ids"] for e in out["key_events"]}
    assert events["삼성전자 ASML 반도체 장비 협력"] == ["n1"]   # 출처 연결됨
    assert events["날조 이벤트 xyzzy"] == []                    # 출처 없음 → 환각 의심
    assert out["event_backend"] == "llm"


def test_grounding_requires_two_token_overlap() -> None:
    """회사명 하나만 겹쳐도 매칭되면 사실상 모든 기사가 후보가 된다 (Gemini #5).

    실측: 이벤트 1개가 73건 중 38건과 1토큰 겹침 → >=2면 13건.
    """
    items = [
        {"news_id": "n1", "title": "삼성전자 ASML 장비 협력", "summary": ""},
        {"news_id": "n2", "title": "삼성전자 배당 확대", "summary": ""},  # '삼성전자'만 겹침
    ]
    ev = agents_mod._ground_event("삼성전자 ASML 협력", items)
    assert ev.news_ids == ["n1"]  # n2는 1토큰만 겹쳐 제외


# ── validation_agent (규칙 기반) ───────────────────────────────────
def _validate(news_result: dict, fin_result: dict, raw_fin: dict, **over) -> dict:
    state = {
        "date": "2022-06-15", "ticker": "005930",
        "raw_news": [{"date": "2022-06-15"}],
        "news_result": news_result, "financial_result": fin_result,
        "raw_financials": raw_fin,
    }
    state.update(over)
    return agents_mod.validation_agent(state)["validation"]


_OK_NEWS = {"article_count": 2, "article_count_raw": 2, "key_events": []}


def test_validation_passes_on_consistent_data() -> None:
    m = metrics_mod.compute_metrics(_fin())
    v = _validate(
        _OK_NEWS,
        {"metrics": m, "fiscal_year": 2021},
        _fin(),
    )
    assert v["ok"], v["errors"]


def test_validation_catches_accounting_identity_violation() -> None:
    """자산 != 부채 + 자본 → 연결/별도 재무제표 혼입 탐지."""
    bad = _fin(total_equity=1.0e14)  # 자산 400 != 부채 100 + 자본 100
    v = _validate(_OK_NEWS, {"metrics": metrics_mod.compute_metrics(bad),
                             "fiscal_year": 2021}, bad)
    assert not v["ok"]
    assert any("회계 항등식" in e for e in v["errors"])


def test_validation_catches_lookahead_fiscal_year() -> None:
    """2022-06-15 피처에 FY2025 재무 → 룩어헤드."""
    v = _validate(_OK_NEWS,
                  {"metrics": metrics_mod.compute_metrics(_fin()), "fiscal_year": 2025},
                  _fin())
    assert not v["ok"]
    assert any("룩어헤드" in e for e in v["errors"])


def test_validation_catches_misaligned_news_date() -> None:
    v = _validate(_OK_NEWS,
                  {"metrics": metrics_mod.compute_metrics(_fin()), "fiscal_year": 2021},
                  _fin(),
                  raw_news=[{"date": "2022-06-14"}])
    assert not v["ok"]
    assert any("기준일" in e for e in v["errors"])


def test_validation_catches_zero_articles() -> None:
    """무데이터를 '중립'으로 통과시키지 않는다."""
    v = _validate({"article_count": 0, "article_count_raw": 0, "key_events": []},
                  {"metrics": metrics_mod.compute_metrics(_fin()), "fiscal_year": 2021},
                  _fin())
    assert not v["ok"]
    assert any("무데이터" in e for e in v["errors"])


def test_validation_catches_implausible_metric() -> None:
    """_band는 조용히 saturate하므로 범위 검사가 유일한 방어선."""
    bad = _fin(shares_outstanding=1.0)  # 단위 오류 → PER 폭발
    v = _validate(_OK_NEWS, {"metrics": metrics_mod.compute_metrics(bad),
                             "fiscal_year": 2021}, bad)
    assert not v["ok"]
    assert any("상식 범위" in e or "PER 불일치" in e for e in v["errors"])


def test_validation_warns_when_cap_drops_relevant_articles() -> None:
    """상한에 걸린 기사는 임의 선택으로 버려진다 → 조용히 넘어가면 안 된다."""
    v = _validate({"article_count": 30, "article_count_raw": 73,
                   "article_count_dropped": 7, "key_events": []},
                  {"metrics": metrics_mod.compute_metrics(_fin()), "fiscal_year": 2021},
                  _fin())
    assert any("상한" in w and "임의로 버려짐" in w for w in v["warnings"])


def test_relevance_cap_does_not_bind_on_real_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    """상한은 병리적인 날 방어용 — 실제 규모(최악의 날 182건)에선 걸리면 안 된다."""
    news = [
        {"news_id": f"n{i}", "title": f"삼성전자 기사 {i}", "summary": "본문",
         "url": "", "press": "", "date": "2022-06-15"}
        for i in range(182)
    ]
    monkeypatch.setattr(agents_mod, "structured", lambda p, s: None)
    out = agents_mod.news_agent(
        {"raw_news": news, "company_name": "삼성전자", "ticker": "005930"}
    )["news_result"]
    assert out["article_count"] == 182
    assert out["article_count_dropped"] == 0


def test_validation_warns_on_ungrounded_event() -> None:
    v = _validate({"article_count": 2, "article_count_raw": 2,
                   "key_events": [{"event": "출처 없는 이벤트", "news_ids": []}]},
                  {"metrics": metrics_mod.compute_metrics(_fin()), "fiscal_year": 2021},
                  _fin())
    assert any("출처 기사를 찾지 못한" in w for w in v["warnings"])


def test_validation_result_reaches_output(monkeypatch: pytest.MonkeyPatch) -> None:
    news = [{"news_id": "n1", "title": "삼성전자 흑자", "summary": "", "url": "",
             "press": "", "date": "2022-06-15"}]
    _patch_collectors(monkeypatch, news, _fin())
    out = graph_mod.run_pipeline("005930", "2022-06-15", "삼성전자")
    assert "validation" in out
    assert out["validation"]["ok"], out["validation"]["errors"]


# ── metrics: 적자 vs 결측 ──────────────────────────────────────────
def test_valuation_missing_data_is_not_treated_as_loss() -> None:
    """per 결측이 곧 적자는 아니다 — 데이터가 없을 뿐일 수 있다.

    과거엔 `elif per is None: parts.append(3.0)` 이라 주가·발행주식수 누락만으로도
    적자 페널티를 먹고 valuation 3.0 → 종합 3.8 → 가짜 SELL이 나왔다.
    """
    # 주가·발행주식수 결측 → per/pbr 모두 None, roe도 None → 판단 근거 없음
    missing = metrics_mod.compute_metrics({"revenue": 1.0e14})
    assert missing["per"] is None and missing["roe"] is None
    assert metrics_mod.valuation_score(missing) == 5.0  # 3.0(적자 취급) 아님

    # 진짜 적자(roe<=0)는 여전히 3.0 페널티를 받는다.
    # valuation_score는 가용 항목의 '평균'이라, 페널티만 확인하려면 pbr도 결측이어야 한다.
    loss = metrics_mod.compute_metrics({"net_income": -1.0e13, "total_equity": 1.0e14})
    assert loss["roe"] is not None and loss["roe"] <= 0
    assert loss["per"] is None and loss["pbr"] is None
    assert metrics_mod.valuation_score(loss) == 3.0


# ── 직전 기사 수집 (PR #22 추가 지적) ──────────────────────────────
def test_published_at_sorts_by_time_not_press_code() -> None:
    """news_id는 '{언론사코드}.{YYYYMMDDHHMMSS}{일련}'.

    그대로 정렬하면 언론사 코드가 먼저 비교되어 시간순이 아니다.
    """
    early_big_press = {"news_id": "09999999.20220614090000001", "date": "2022-06-14"}
    late_small_press = {"news_id": "02100101.20220614180000001", "date": "2022-06-14"}
    # news_id 그대로면 02...(늦은 기사)가 앞 → 시간순 아님
    assert late_small_press["news_id"] < early_big_press["news_id"]
    # _published_at 을 쓰면 시간순
    assert collectors_mod._published_at(early_big_press) < collectors_mod._published_at(
        late_small_press
    )


def test_published_at_falls_back_to_date_for_generated_id() -> None:
    assert collectors_mod._published_at(
        {"news_id": "generated:abc123", "date": "2022-06-14"}
    ) == "20220614"


def test_collect_prior_news_returns_latest_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Tetlock의 '직전 10건'은 최신 10건이어야 한다 — 언론사 코드순 10건이 아니라."""
    day = [
        {"news_id": "09999999.20220614090000001", "title": "오전 기사",
         "summary": "", "url": "", "press": "", "date": "2022-06-14"},
        {"news_id": "02100101.20220614180000001", "title": "오후 기사",
         "summary": "", "url": "", "press": "", "date": "2022-06-14"},
    ]
    monkeypatch.setattr(
        collectors_mod.preprocess, "load_daily_news",
        lambda q, d, dd, limit=None, ticker="": day if d == "2022-06-14" else [],
    )
    out = collectors_mod.collect_prior_news("005930", "삼성전자", "2022-06-15", 1)
    assert [it["title"] for it in out] == ["오후 기사"]  # 최신 1건


# ── 경로 규약 통일 (PR #22 블로커1) ────────────────────────────────
def test_corpus_and_daily_loader_share_path_contract(tmp_path: Path) -> None:
    """build_news_corpus와 load_daily_news가 같은 파일을 본다.

    규약이 갈리면 한쪽만 파일을 못 찾고 조용히 폴백해 오염된 행이 나온다.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_bigkinds(
        data_dir / "005930_삼성전자_20220101-20221231.xlsx",
        [{"뉴스 식별자": "n1", "일자": 20220615, "언론사": "매일경제",
          "제목": "삼성전자 기사", "본문": "본문", "URL": "", "분석제외 여부": ""}],
    )
    # 하루치 로더가 찾는다
    assert pp.load_daily_news("삼성전자", "2022-06-15", data_dir=data_dir)
    # 코퍼스 빌더도 같은 파일을 찾는다
    assert pp.find_corpus_workbooks(data_dir, "005930") == [
        data_dir / "005930_삼성전자_20220101-20221231.xlsx"
    ]
    report = pp.build_news_corpus("005930", tmp_path / "out.csv", raw_dir=data_dir)
    assert report.deduplicated_rows == 1


def test_corpus_workbooks_filter_by_ticker(tmp_path: Path) -> None:
    """다른 종목 워크북이 섞여 들어오면 안 된다."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in ("005930_삼성전자_20220101-20221231.xlsx",
                 "000660_SK하이닉스_20220101-20221231.xlsx"):
        _write_bigkinds(data_dir / name, [
            {"뉴스 식별자": "n1", "일자": 20220615, "언론사": "매일경제",
             "제목": "기사", "본문": "본문", "URL": "", "분석제외 여부": ""}])
    found = pp.find_corpus_workbooks(data_dir, "005930")
    assert [p.name for p in found] == ["005930_삼성전자_20220101-20221231.xlsx"]


def test_corpus_workbooks_still_accept_legacy_newsresult(tmp_path: Path) -> None:
    """레거시 NewsResult_*.xlsx 입력은 계속 동작해야 한다(하위 호환)."""
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_bigkinds(raw / "NewsResult_20220101-20221231.xlsx", [
        {"뉴스 식별자": "n1", "일자": 20220615, "언론사": "매일경제",
         "제목": "기사", "본문": "본문", "URL": "", "분석제외 여부": ""}])
    assert len(pp.find_corpus_workbooks(raw, "005930")) == 1


# ── LLM 런타임 스위치 (--no-llm) ───────────────────────────────────
@pytest.fixture()
def _llm_switch_reset():
    """스위치는 모듈 전역이라 테스트 간 누수 방지를 위해 반드시 원복한다."""
    yield
    llm_mod.set_llm_enabled(True)


def test_set_llm_enabled_blocks_api_even_with_key(
    monkeypatch: pytest.MonkeyPatch, _llm_switch_reset
) -> None:
    """--no-llm은 키가 .env에 있어도 API 경로를 차단해야 한다."""
    monkeypatch.setattr(
        llm_mod, "SETTINGS",
        dataclasses.replace(llm_mod.SETTINGS, gemini_api_key="dummy-key"),
    )
    llm_mod.set_llm_enabled(False)
    assert llm_mod.get_llm() is None  # 키가 있어도 None → structured가 폴백

    from pydantic import BaseModel

    class _Probe(BaseModel):
        text: str = ""

    # 캐시에 없는 프롬프트 → 차단 상태에선 API 대신 None(규칙 폴백 신호)
    assert llm_mod.structured("no-llm 스위치 프로브 프롬프트", _Probe) is None


def test_cli_no_llm_flag_wires_the_switch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _llm_switch_reset, capsys
) -> None:
    """run.py --no-llm 이 실행 전에 스위치를 내리는지 확인."""
    seen: dict[str, bool] = {}

    def fake_pipeline(ticker, date, name):
        seen["disabled_during_run"] = llm_mod._FORCE_DISABLED
        return {"validation": {"ok": True, "errors": [], "warnings": []}}

    monkeypatch.setattr(run_mod, "run_pipeline", fake_pipeline)
    rc = run_mod.main(
        ["--date", "2022-06-15", "--no-llm", "--out", str(tmp_path / "o.json")]
    )

    assert rc == 0
    assert seen["disabled_during_run"] is True
    capsys.readouterr()  # 결과 JSON stdout 출력 소거


# ── staleness (Tetlock 2011) ───────────────────────────────────────
def test_staleness_identical_article_is_fully_stale() -> None:
    text = ["삼성전자 반도체 실적 개선 전망 메모리 가격 반등"]
    assert staleness_mod.staleness_score(text, text) == 1.0


def test_staleness_new_article_is_fresh() -> None:
    cur = ["삼성전자 신규 파운드리 수주 계약 체결"]
    prev = ["기아 전기차 판매량 증가 유럽 시장"]
    assert staleness_mod.staleness_score(cur, prev) == 0.0


def test_staleness_no_prior_is_zero() -> None:
    assert staleness_mod.staleness_score(["삼성전자 실적"], []) == 0.0


def test_staleness_is_deterministic() -> None:
    cur = ["삼성전자 반도체 실적 개선", "메모리 가격 반등 기대"]
    prev = ["삼성전자 반도체 업황 전망", "낸드 가격 하락"]
    a = staleness_mod.staleness_score(cur, prev)
    b = staleness_mod.staleness_score(cur, prev)
    assert a == b
    assert 0.0 < a < 1.0  # 부분 중복

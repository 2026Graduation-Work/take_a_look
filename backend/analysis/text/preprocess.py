"""Merge and normalize manually downloaded BigKinds news workbooks."""

from __future__ import annotations

import argparse
import hashlib
import re
import unicodedata
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

TEXT_DIR = Path(__file__).resolve().parent
DEFAULT_PROCESSED_DIR = TEXT_DIR / "data" / "processed"
# 빅카인즈 원본 위치 — build_news_corpus(CSV 코퍼스)와 load_daily_news(하루치
# point-in-time)가 **같은 기준 디렉터리·같은 종목 분리 규약**을 본다. 규약이 갈리면
# 한쪽만 파일을 못 찾고 조용히 폴백해 오염된 행이 나온다.
#
# 종목별 분리: 원본은 기준 디렉터리 아래 <6자리 종목코드>/ 하위 폴더로 나눈다.
#   예) data/005930/삼성전자_20220101-20221231.xlsx  (삼성전자)
#       data/035720/카카오_20220101-20221231.xlsx    (카카오)
# 두 소비자 모두 <기준>/<종목코드>/ 를 먼저 해석하므로 다른 종목 뉴스가 섞이지 않는다.
# 종목 디렉터리가 하나도 없으면 기준 디렉터리 평면 구조로 폴백한다(구버전 호환).
DEFAULT_NEWS_DIR = TEXT_DIR.parents[2] / "data"
# 레거시 입력. 파일명에 회사·기간 정보가 없어 종목 필터·기간 판정이 불가능하므로
# 신규 데이터는 아래 워크북 규약을 쓸 것.
INPUT_PATTERN = "NewsResult_*.xlsx"
# 뉴스 워크북 파일명 규약 (신규 우선, 구버전 호환):
#   신규 : {종목코드}_{회사명}_{YYYYMMDD}-{YYYYMMDD}.xlsx
#          (예: 005930_삼성전자_20220101-20221231.xlsx)
#   구버전: {회사명}_{YYYYMMDD}-{YYYYMMDD}.xlsx
#          (예: 삼성전자_20220101-20221231.xlsx)
_NEWS_WORKBOOK_RE_CODE = re.compile(
    r"(?P<code>[^_]+)_(?P<company>.+)_(?P<start>\d{8})-(?P<end>\d{8})\.xlsx$"
)
_NEWS_WORKBOOK_RE_PLAIN = re.compile(
    r"(?P<company>.+)_(?P<start>\d{8})-(?P<end>\d{8})\.xlsx$"
)
OUTPUT_COLUMNS = ["news_id", "date", "title", "body", "press", "ticker"]
# point-in-time 로더가 하루치로 반환하는 기사 최대 건수(감성 안정성용).
DEFAULT_DAILY_LIMIT = 30
# "분석제외 여부" 컬럼에서 제외로 간주하는 표기(소문자 비교).
_EXCLUDE_TOKENS = {"y", "1", "true", "제외", "분석제외", "exclude", "o"}

# BigKinds export headers have changed over time. Keep every supported spelling here.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "news_id": ("뉴스 식별자", "뉴스식별자", "뉴스 ID", "뉴스ID", "기사 식별자"),
    "date": ("일자", "날짜", "작성일", "게시일", "보도일"),
    "title": ("제목", "뉴스 제목", "기사 제목"),
    "body": ("본문", "뉴스 본문", "기사 본문", "내용"),
    "keywords": ("키워드", "뉴스 키워드", "특성추출(가중치순 상위 50개)"),
    "press": ("언론사", "매체명", "신문사", "뉴스 제공처"),
    # 아래 두 개는 선택 컬럼(있으면 활용, 없으면 무시) — 필수 검증에서 제외됨.
    "url": ("URL", "url", "주소", "링크"),
    "exclude": ("분석제외 여부", "분석제외여부", "분석 제외 여부"),
}


class BigKindsSchemaError(ValueError):
    """Raised when a BigKinds workbook cannot satisfy the input contract."""


@dataclass(frozen=True)
class PreprocessReport:
    input_files: int
    raw_rows: int
    deduplicated_rows: int
    date_min: str
    date_max: str
    missing_dates: tuple[str, ...]
    output_path: Path


def _normalized_columns(columns: pd.Index) -> dict[str, object]:
    return {str(column).strip(): column for column in columns}


def _find_column(columns: dict[str, object], field: str) -> object | None:
    return next((columns[alias] for alias in COLUMN_ALIASES[field] if alias in columns), None)


def _resolve_columns(frame: pd.DataFrame, source: Path) -> dict[str, object | None]:
    columns = _normalized_columns(frame.columns)
    resolved = {field: _find_column(columns, field) for field in COLUMN_ALIASES}

    missing = [field for field in ("date", "title", "press") if resolved[field] is None]
    if resolved["body"] is None and resolved["keywords"] is None:
        missing.append("body 또는 keywords")

    if missing:
        expected = "; ".join(
            f"{field}={COLUMN_ALIASES[field]}"
            for field in ("date", "title", "body", "keywords", "press")
        )
        available = ", ".join(repr(column) for column in frame.columns)
        raise BigKindsSchemaError(
            f"{source.name}: 필수 컬럼을 찾을 수 없습니다: {', '.join(missing)}. "
            f"지원 컬럼명: {expected}. 실제 컬럼: [{available}]"
        )

    return resolved


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


@lru_cache(maxsize=4)
def _read_workbook_cached(path: Path, mtime: float, size: int) -> pd.DataFrame:
    """_read_workbook의 캐시 래퍼. mtime·size를 키에 넣어 파일이 바뀌면 무효화된다.

    빅카인즈 워크북은 20~25MB라 파싱에 4초 넘게 걸리는데, 파이프라인 1회 실행에
    collect_news + collect_prior_news가 같은 파일을 여러 번 읽는다(실측 8.4초).
    반환 프레임을 호출자가 변형하면 캐시가 오염되므로 _read_workbook이 복사본을 준다.
    """
    return _read_workbook_uncached(path)


def _read_workbook(path: Path) -> pd.DataFrame:
    try:
        stat = path.stat()
        return _read_workbook_cached(path, stat.st_mtime, stat.st_size).copy()
    except OSError:
        return _read_workbook_uncached(path)


def _read_workbook_uncached(path: Path) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        frame = pd.read_excel(path, engine="openpyxl", dtype=object)

    columns = _resolve_columns(frame, path)
    normalized = pd.DataFrame(index=frame.index)

    news_id_column = columns["news_id"]
    if news_id_column is None:
        normalized["news_id"] = ""
    else:
        normalized["news_id"] = frame[news_id_column].map(_clean_text)

    normalized["date"] = pd.to_datetime(
        frame[columns["date"]].map(_clean_text),
        errors="coerce",
        format="mixed",
        yearfirst=True,
    ).dt.normalize()
    invalid_dates = normalized["date"].isna()
    if invalid_dates.any():
        rows = [str(index + 2) for index in frame.index[invalid_dates][:5]]
        raise BigKindsSchemaError(
            f"{path.name}: 날짜로 변환할 수 없는 값이 있습니다(엑셀 행 {', '.join(rows)})."
        )

    normalized["title"] = frame[columns["title"]].map(_clean_text)
    normalized["press"] = frame[columns["press"]].map(_clean_text)

    body_column = columns["body"]
    keyword_column = columns["keywords"]
    if body_column is None:
        normalized["body"] = frame[keyword_column].map(_clean_text)
    else:
        normalized["body"] = frame[body_column].map(_clean_text)
        if keyword_column is not None:
            empty_body = normalized["body"].eq("")
            normalized.loc[empty_body, "body"] = frame.loc[empty_body, keyword_column].map(
                _clean_text
            )

    url_column = columns["url"]
    normalized["url"] = (
        frame[url_column].map(_clean_text) if url_column is not None else ""
    )
    exclude_column = columns["exclude"]
    if exclude_column is None:
        normalized["exclude"] = False
    else:
        normalized["exclude"] = (
            frame[exclude_column].map(_clean_text).str.lower().isin(_EXCLUDE_TOKENS)
        )

    return normalized


def _fallback_key(frame: pd.DataFrame) -> pd.Series:
    dates = frame["date"].dt.strftime("%Y-%m-%d")
    return dates + "\x1f" + frame["title"] + "\x1f" + frame["press"]


def _generated_news_id(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"generated:{digest}"


def _deduplicate(frame: pd.DataFrame) -> pd.DataFrame:
    working = frame.copy()
    working["_fallback_key"] = _fallback_key(working)
    has_news_id = working["news_id"].ne("")

    identified = working.loc[has_news_id].drop_duplicates(subset="news_id", keep="first")
    unidentified = working.loc[~has_news_id]

    # An unidentified copy of an article already retained by ID is still a duplicate.
    identified_fallback_keys = set(identified["_fallback_key"])
    unidentified = unidentified.loc[
        ~unidentified["_fallback_key"].isin(identified_fallback_keys)
    ].drop_duplicates(subset="_fallback_key", keep="first")
    unidentified = unidentified.copy()
    unidentified["news_id"] = unidentified["_fallback_key"].map(_generated_news_id)

    return pd.concat([identified, unidentified], ignore_index=True).drop(columns="_fallback_key")


def _resolve_output_path(out: Path) -> Path:
    return out if out.is_absolute() else DEFAULT_PROCESSED_DIR / out


def _iter_ticker_directories(base_dir: Path) -> list[Path]:
    if not base_dir.is_dir():
        return []
    return [
        path
        for path in base_dir.iterdir()
        if path.is_dir() and len(path.name) == 6 and path.name.isdigit()
    ]


def _resolve_ticker_dir(base_dir: Path, ticker: str, *, strict: bool) -> Path:
    """원본을 읽을 실제 디렉터리를 종목별로 해석한다.

    - <base>/<ticker>/ 가 있으면 그 폴더만 본다(다른 종목 혼입 방지).
    - 종목 폴더(6자리 숫자)가 하나라도 있는데 요청 종목 폴더가 없으면:
        strict=True  → FileNotFoundError (코퍼스 빌드는 잘못된 데이터로 학습 CSV를
                       만드느니 즉시 멈추는 게 낫다)
        strict=False → 기준 디렉터리 평면 구조로 폴백(point-in-time 로더는 다음
                       소스로 그레이스풀 폴백하므로 예외 대신 폴백)
    - 종목 폴더가 전혀 없으면 기준 디렉터리 평면 구조로 폴백한다(구버전 호환).
    """
    ticker = (ticker or "").strip()
    if not ticker:
        return base_dir
    ticker_dir = base_dir / ticker
    if ticker_dir.is_dir():
        return ticker_dir
    if strict:
        ticker_directories = _iter_ticker_directories(base_dir)
        if ticker_directories:
            available = ", ".join(sorted(path.name for path in ticker_directories))
            raise FileNotFoundError(
                f"{ticker} 종목 원본 디렉터리가 없습니다: {ticker_dir}. "
                f"현재 종목 디렉터리: {available}"
            )
    return base_dir


def find_corpus_workbooks(
    raw_dir: Path, ticker: str = "", company_name: str = ""
) -> list[Path]:
    """해당 종목의 빅카인즈 워크북 목록 (하위 디렉터리 포함).

    종목 분리는 load_daily_news와 동일하다 — 두 소비자가 <기준>/<종목코드>/ 를
    먼저 해석한다. 종목 폴더로 스코프되면 그 폴더의 모든 워크북을 쓴다(폴더 자체가
    종목을 특정하므로 파일명이 종목을 또 담을 필요가 없다). 종목 폴더가 없어 평면
    구조로 폴백한 경우에만 파일명 규약으로 종목을 가린다:
      정본  : {종목코드}_{회사명}_{YYYYMMDD}-{YYYYMMDD}.xlsx
      구버전: {회사명}_{YYYYMMDD}-{YYYYMMDD}.xlsx
      레거시: NewsResult_*.xlsx (파일명에 회사·기간 정보가 없어 종목 필터 불가)
    """
    input_dir = _resolve_ticker_dir(raw_dir, ticker, strict=True)
    scoped_by_dir = input_dir != raw_dir
    wanted_company = _normalize_company(company_name)
    wanted_code = (ticker or "").strip()
    found: list[Path] = []
    for path in sorted(input_dir.glob("**/*.xlsx")):
        if path.name.startswith("~$"):
            continue
        if scoped_by_dir:
            found.append(path)
            continue
        if path.name.startswith("NewsResult_"):
            found.append(path)
            continue
        parsed = _parse_workbook_name(path.name)
        if parsed is None:
            continue
        code, company, _, _ = parsed
        if (wanted_code and code == wanted_code) or (
            wanted_company and _normalize_company(company) == wanted_company
        ):
            found.append(path)
    return found


def build_news_corpus(
    ticker: str,
    out: Path,
    raw_dir: Path = DEFAULT_NEWS_DIR,
    company_name: str = "",
) -> PreprocessReport:
    """Build the deterministic FinBERT input CSV and return its coverage report."""
    ticker = ticker.strip()
    if not ticker:
        raise ValueError("ticker는 빈 문자열일 수 없습니다.")

    input_files = find_corpus_workbooks(raw_dir, ticker, company_name)
    if not input_files:
        raise FileNotFoundError(
            f"입력 파일이 없습니다: {raw_dir}/{ticker}/ (또는 평면 구조 {raw_dir}) 에서 "
            f"'{INPUT_PATTERN}' 이나 '{{회사명}}_{{YYYYMMDD}}-{{YYYYMMDD}}.xlsx' 를 "
            f"찾지 못했습니다."
        )

    frames = [_read_workbook(path) for path in input_files]
    raw_rows = sum(len(frame) for frame in frames)
    merged = pd.concat(frames, ignore_index=True)
    if merged.empty:
        raise ValueError("입력 엑셀에 뉴스 행이 없습니다.")

    deduplicated = _deduplicate(merged)
    deduplicated["ticker"] = ticker
    deduplicated["date"] = deduplicated["date"].dt.strftime("%Y-%m-%d")
    deduplicated = deduplicated[OUTPUT_COLUMNS].sort_values(
        by=["date", "news_id"], kind="stable", ignore_index=True
    )

    date_min = deduplicated["date"].min()
    date_max = deduplicated["date"].max()
    covered_dates = pd.DatetimeIndex(pd.to_datetime(deduplicated["date"].unique()))
    expected_dates = pd.date_range(date_min, date_max, freq="D")
    missing_dates = tuple(
        timestamp.strftime("%Y-%m-%d") for timestamp in expected_dates.difference(covered_dates)
    )

    output_path = _resolve_output_path(out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    deduplicated.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
        lineterminator="\n",
    )

    return PreprocessReport(
        input_files=len(input_files),
        raw_rows=raw_rows,
        deduplicated_rows=len(deduplicated),
        date_min=date_min,
        date_max=date_max,
        missing_dates=missing_dates,
        output_path=output_path,
    )


def print_report(report: PreprocessReport) -> None:
    print(f"입력 파일 수: {report.input_files}")
    print(f"원본 총 건수: {report.raw_rows}")
    print(f"dedup 후 건수: {report.deduplicated_rows}")
    print(f"실제 수록 기간: {report.date_min} ~ {report.date_max}")
    print(f"일자 구멍 개수: {len(report.missing_dates)}")
    if report.missing_dates:
        print("경고: 뉴스가 0건인 일자가 있습니다. 파이프라인은 계속 진행합니다.")
        print(f"일자 구멍: {', '.join(report.missing_dates)}")
    print(f"산출물: {report.output_path}")


def _normalize_company(name: str) -> str:
    return unicodedata.normalize("NFC", (name or "").strip())


def _parse_workbook_name(name: str) -> tuple[str, str, str, str] | None:
    """파일명 → (종목코드, 회사명, 시작일, 종료일). 코드가 없는 구버전이면 코드는 ""."""
    match = _NEWS_WORKBOOK_RE_CODE.fullmatch(name)
    if match:
        return (
            match.group("code"),
            match.group("company"),
            match.group("start"),
            match.group("end"),
        )
    match = _NEWS_WORKBOOK_RE_PLAIN.fullmatch(name)
    if match:
        return "", match.group("company"), match.group("start"), match.group("end")
    return None


def find_news_workbook(
    company_name: str,
    date: str,
    data_dir: Path = DEFAULT_NEWS_DIR,
    ticker: str = "",
) -> Path | None:
    """뉴스 워크북 중 date가 기간에 포함되는 파일 반환 (없으면 None).

    종목 분리는 코퍼스 빌더와 동일하게 <기준>/<종목코드>/ 를 먼저 해석한다.
    종목 폴더로 스코프되면 폴더 자체가 종목을 특정하므로 기간만 맞으면 반환한다.
    평면 구조로 폴백한 경우에만 파일명 규약(신규 {코드}_{명}_{기간}·구버전 {명}_{기간})의
    종목코드 또는 회사명(NFC) 일치를 추가로 요구한다.

    코퍼스 빌더와 달리 종목 폴더가 없어도 예외를 던지지 않는다(strict=False) —
    상위 호출자(collectors)가 다음 소스로 그레이스풀 폴백하기 때문이다.
    """
    base_dir = Path(data_dir)
    search_dir = _resolve_ticker_dir(base_dir, ticker, strict=False)
    scoped_by_dir = search_dir != base_dir
    # 종목 폴더 안은 재귀 탐색(분할 파일이 하위 폴더에 있을 수 있음), 평면은 최상위만
    pattern = "**/*.xlsx" if scoped_by_dir else "*.xlsx"
    target_day = date.replace("-", "")
    wanted_company = _normalize_company(company_name)
    wanted_code = (ticker or "").strip()
    for path in sorted(search_dir.glob(pattern)):
        if path.name.startswith("~$"):
            continue
        parsed = _parse_workbook_name(path.name)
        if parsed is None:
            continue
        code, company, start, end = parsed
        if not (start <= target_day <= end):
            continue
        if scoped_by_dir:
            return path
        code_match = bool(wanted_code) and code == wanted_code
        name_match = bool(wanted_company) and _normalize_company(company) == wanted_company
        if code_match or name_match:
            return path
    return None


def load_daily_news(
    company_name: str,
    date: str,
    data_dir: Path = DEFAULT_NEWS_DIR,
    limit: int | None = DEFAULT_DAILY_LIMIT,
    body_chars: int = 1000,
    ticker: str = "",
) -> list[dict]:
    """해당 회사·날짜(YYYY-MM-DD) 하루치 뉴스를 표준 dict 리스트로 반환.

    각 항목: {news_id, title, summary(=본문 일부), url, press, date}.
    - _read_workbook로 빅카인즈 컬럼을 정규화하고,
    - '분석제외 여부'가 켜진 기사를 제거한 뒤,
    - _deduplicate로 중복(식별자/폴백키)을 정리하고,
    - 해당 날짜만 남겨 news_id 순으로 상위 limit건을 돌려준다.
    파일이 없으면 빈 리스트(→ 상위 호출자가 다음 소스로 폴백).

    limit=None이면 그날 기사를 전부 돌려준다. news_id 정렬순 상위 N건은
    관련성과 무관한 사실상 임의 표본이므로, 하루치를 전부 받아 관련성으로
    거르는 호출자(news_agent)가 상한을 직접 적용한다.

    news_id는 (date, title, press) 해시 폴백까지 포함해 100% 채워지므로
    key_events의 출처 인용(그라운딩) 키로 쓸 수 있다.
    """
    path = find_news_workbook(company_name, date, data_dir, ticker)
    if path is None:
        return []

    frame = _read_workbook(path)
    if "exclude" in frame.columns:
        frame = frame.loc[~frame["exclude"].fillna(False)]
    if frame.empty:
        return []

    frame = _deduplicate(frame)
    # 전체 컬럼을 문자열로 변환(strftime)하지 않고 Timestamp로 직접 비교한다.
    # 19,549행 워크북에서 문자열 변환은 순수 낭비다.
    target = pd.Timestamp(date)
    frame = frame.loc[frame["date"].dt.normalize() == target].sort_values(
        by="news_id", kind="stable", ignore_index=True
    )

    items: list[dict] = []
    for _, row in frame.iterrows():
        title = str(row.get("title", "")).strip()
        if not title:
            continue
        body = str(row.get("body", "")).strip()
        items.append(
            {
                "news_id": str(row.get("news_id", "")).strip(),
                "title": title,
                "summary": body[:body_chars],
                "url": str(row.get("url", "")).strip(),
                "press": str(row.get("press", "")).strip(),
                "date": date,
            }
        )
        if limit is not None and len(items) >= limit:
            break
    return items


def load_news_range(
    company_name: str,
    date_start: str,
    date_end: str,
    data_dir: Path = DEFAULT_NEWS_DIR,
    body_chars: int = 1000,
    ticker: str = "",
) -> list[dict]:
    """기간 내 BigKinds 기사를 워크북별 1회만 읽어 반환한다.

    ``load_daily_news``를 날짜 수만큼 반복하면 연 단위 그래프에서 같은
    큰 Excel을 계속 복사·중복제거하게 된다. 해당 기간을 커버하는 고유
    워크북 목록을 먼저 구한 후, 각 파일을 한 번만 파싱한다.
    """
    start = pd.Timestamp(date_start).normalize()
    end = pd.Timestamp(date_end).normalize()
    if start > end:
        raise ValueError("date_start는 date_end보다 늦을 수 없습니다.")

    paths = {
        path
        for day in pd.date_range(start, end, freq="D")
        if (
            path := find_news_workbook(
                company_name, day.date().isoformat(), data_dir, ticker
            )
        )
        is not None
    }
    frames: list[pd.DataFrame] = []
    for path in sorted(paths):
        frame = _read_workbook(path)
        if "exclude" in frame.columns:
            frame = frame.loc[~frame["exclude"].fillna(False)]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return []

    frame = _deduplicate(pd.concat(frames, ignore_index=True))
    frame = frame.loc[
        (frame["date"].dt.normalize() >= start)
        & (frame["date"].dt.normalize() <= end)
    ].sort_values(by=["date", "news_id"], kind="stable", ignore_index=True)

    items: list[dict] = []
    for _, row in frame.iterrows():
        title = str(row.get("title", "")).strip()
        if not title:
            continue
        items.append(
            {
                "news_id": str(row.get("news_id", "")).strip(),
                "title": title,
                "summary": str(row.get("body", "")).strip()[:body_chars],
                "url": str(row.get("url", "")).strip(),
                "press": str(row.get("press", "")).strip(),
                "date": row["date"].date().isoformat(),
            }
        )
    return items


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="빅카인즈 엑셀을 FinBERT 입력 CSV로 변환")
    parser.add_argument("--ticker", required=True, help="모든 출력 행에 주입할 종목 코드")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("news_corpus.csv"),
        help="산출물 파일명 또는 절대 경로 (기본: data/processed/news_corpus.csv)",
    )
    parser.add_argument(
        "--name",
        default="",
        help="회사명 (구버전 파일명 {회사명}_{기간}.xlsx 매칭용)",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_NEWS_DIR,
        help=(
            "빅카인즈 원본 기준 디렉터리 (기본: 저장소 루트 data/ — value_pipeline과 동일). "
            "<종목코드>/ 하위 폴더가 있으면 --ticker 종목 폴더만 읽는다"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_news_corpus(
        ticker=args.ticker, out=args.out, raw_dir=args.raw_dir, company_name=args.name
    )
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

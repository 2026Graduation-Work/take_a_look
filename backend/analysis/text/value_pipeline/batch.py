"""일별 대량 생성 배치 러너 — LangGraph 파이프라인을 날짜 루프로 호출.

한 프로세스 안에서 도는 이유: FinBERT 로드 1회, 빅카인즈 연간 워크북(20MB) 파싱 캐시와
DART/FDR 프로세스 캐시 재사용.

LLM은 강제로 끈다 — 대량 생성 중 무료 한도를 태우지 않게. 숫자는 LLM 유무와 무관하다.

하루 실패는 기록하고 다음 날짜로 넘어가지만, FinancialsUnavailableError(키 없음 등)는
구조적 문제라 계속 돌아봤자 전부 실패하므로 즉시 중단한다.

--skip-existing 재개는 기존 산출물의 생성 조건(out_dir/_provenance.json)이 지금과 같을 때만
허용한다 — 코드·FinBERT 모델·설정이 다른 JSON이 한 데이터셋에 섞이면 안 된다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

from .collectors import FinancialsUnavailableError
from .config import SETTINGS
from .graph import run_pipeline
from .llm import set_llm_enabled


def _iter_days(start: str, end: str):
    day = dt.date.fromisoformat(start)
    stop = dt.date.fromisoformat(end)
    while day <= stop:
        yield day.isoformat()
        day += dt.timedelta(days=1)


def _write_json_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _code_version() -> str:
    pkg = Path(__file__).resolve().parent
    try:
        head = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", "."],
            cwd=pkg, capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "."],
            cwd=pkg, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    # ponytail: +dirty는 미커밋 변경끼리 구분하지 못한다 — 필요해지면 diff 해시를 붙일 것
    return (head or "unknown") + ("+dirty" if dirty else "")


def provenance() -> dict:
    """산출물의 숫자를 바꿀 수 있는 생성 조건. 하나라도 다르면 재사용 불가."""
    return {
        "code_version": _code_version(),
        "finbert_model": SETTINGS.finbert_model,
        "use_finbert": SETTINGS.use_finbert,
        "shares_asof_year": SETTINGS.shares_asof_year,
        "news_lookback_days": SETTINGS.news_lookback_days,
        "max_daily_articles": SETTINGS.max_daily_articles,
        "staleness_lookback_articles": SETTINGS.staleness_lookback_articles,
        "staleness_lookback_days": SETTINGS.staleness_lookback_days,
        "llm": "disabled",
    }


def _check_resumable(out_dir: Path, ticker: str, current: dict) -> None:
    if not any(out_dir.glob(f"{ticker}_*.json")):
        return
    path = out_dir / "_provenance.json"
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        recorded = None
    if recorded != current:
        raise ValueError(
            f"{out_dir}의 기존 산출물과 생성 조건이 다르거나 기록이 없음 → 섞지 않도록 "
            f"재개 거부. 새 디렉터리에 생성하거나 기존 파일을 지우고 다시 실행하세요.\n"
            f"  기록: {recorded}\n  현재: {current}"
        )


def _is_valid_json(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return True


def run_batch(
    ticker: str,
    name: str,
    start: str,
    end: str,
    out_dir: Path,
    skip_existing: bool = False,
) -> dict:
    set_llm_enabled(False)
    out_dir.mkdir(parents=True, exist_ok=True)
    prov = provenance()
    if skip_existing:
        _check_resumable(out_dir, ticker, prov)
    _write_json_atomic(out_dir / "_provenance.json", prov)

    ok = invalid = skipped = 0
    errors: list[dict] = []
    days = list(_iter_days(start, end))

    for i, d in enumerate(days, start=1):
        out_path = out_dir / f"{ticker}_{d}.json"
        if skip_existing and out_path.exists() and _is_valid_json(out_path):
            skipped += 1
            continue
        try:
            result = run_pipeline(ticker, d, name)
        except FinancialsUnavailableError:
            raise
        except Exception as e:
            errors.append({"date": d, "error": repr(e)})
            continue

        _write_json_atomic(out_path, result)
        if (result.get("validation") or {}).get("ok"):
            ok += 1
        else:
            invalid += 1

        if i % 50 == 0 or i == len(days):
            print(
                f"[진행] {ticker} {i}/{len(days)}일 "
                f"(성공 {ok}, 검증실패 {invalid}, 에러 {len(errors)}, 스킵 {skipped})",
                file=sys.stderr,
            )

    manifest = {
        "ticker": ticker,
        "company_name": name,
        "start": start,
        "end": end,
        "days": len(days),
        "ok": ok,
        "validation_failed": invalid,
        "errors": errors,
        "skipped_existing": skipped,
        "llm": "disabled",
        "shares_asof_year": SETTINGS.shares_asof_year,
        "provenance": prov,
    }
    _write_json_atomic(out_dir / f"_manifest_{ticker}_{start}_{end}.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="일별 가치투자 피처 대량 생성 (LLM 강제 OFF)")
    ap.add_argument("--ticker", required=True, help="종목코드 (예: 005930)")
    ap.add_argument("--name", required=True, help="회사명 (관련성 필터 키워드, 예: 삼성전자)")
    ap.add_argument("--start", required=True, help="시작일 YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="종료일 YYYY-MM-DD")
    ap.add_argument("--out-dir", default="out", help="출력 디렉터리 (기본: out/)")
    ap.add_argument(
        "--skip-existing", action="store_true",
        help="이미 생성된 날짜는 건너뛴다 (중단된 배치 재개용)",
    )
    args = ap.parse_args(argv)

    try:
        manifest = run_batch(
            args.ticker, args.name, args.start, args.end,
            Path(args.out_dir), args.skip_existing,
        )
    except (FinancialsUnavailableError, ValueError) as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 2

    print(
        f"[완료] {manifest['days']}일 중 성공 {manifest['ok']}, "
        f"검증실패 {manifest['validation_failed']}, 에러 {len(manifest['errors'])}, "
        f"스킵 {manifest['skipped_existing']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

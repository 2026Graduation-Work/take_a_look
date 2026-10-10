"""DART 재무 스냅샷을 종목별 Supabase 적재용 JSON으로 내보낸다."""
from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from . import collectors, financial_tracks, metrics
from .agents import validation_agent
from .config import SETTINGS
from .news_run import _parse_target

Collector = Callable[[str, str], tuple[dict[str, Any], str]]
FilingLoader = Callable[[str, int, str], dict[str, Any]]


def _fetch_filing_metadata(ticker: str, fiscal_year: int, as_of: str) -> dict[str, Any]:
    """사업보고서 접수번호·공시일과 연결/별도 구분을 확인한다."""
    if not SETTINGS.has_dart:
        raise RuntimeError("DART_API_KEY가 없습니다.")
    dart = collectors.OpenDartReader(SETTINGS.dart_api_key)
    statement = "CFS"
    frame = dart.finstate_all(ticker, fiscal_year)
    if frame is None or len(frame) == 0:
        statement = "OFS"
        frame = dart.finstate_all(ticker, fiscal_year, fs_div="OFS")
    if frame is None or len(frame) == 0:
        raise RuntimeError(f"{ticker} FY{fiscal_year}: DART 사업보고서가 없습니다.")

    receipt_no = str(frame["rcept_no"].iloc[0])
    filed_at = f"{receipt_no[:4]}-{receipt_no[4:6]}-{receipt_no[6:8]}"
    validation_errors: list[str] = []
    next_day = (dt.date.fromisoformat(as_of) + dt.timedelta(days=1)).isoformat()
    today = dt.date.today().isoformat()
    if next_day <= today:
        later = dart.list(ticker, start=next_day, end=today, kind="A")
        if (
            later is not None
            and len(later)
            and "report_nm" in later
            and later["report_nm"].astype(str).str.contains(f"{fiscal_year}.12").any()
        ):
            validation_errors.append(
                "기준일 이후 같은 사업연도의 정정공시가 있어 현재 DART 값과 기준일 값이 다를 수 있음"
            )
    return {
        "statement": statement,
        "receipt_no": receipt_no,
        "filed_at": filed_at,
        "validation_errors": validation_errors,
    }


def _financial_validation_errors(raw_financials: dict[str, Any], as_of: str) -> list[str]:
    calculated = metrics.compute_metrics(raw_financials)
    result = validation_agent(
        {
            "financial_result": {
                "metrics": calculated,
                "fiscal_year": raw_financials["fiscal_year"],
            },
            "raw_financials": raw_financials,
            "date": as_of,
            "raw_news": [],
            "news_result": {"article_count": 1},
        }
    )
    return list(result["validation"]["errors"])


def run_financial_cycle(
    targets: Mapping[str, str],
    *,
    as_of: str,
    collector: Collector = collectors.collect_financials,
    filing_loader: FilingLoader = _fetch_filing_metadata,
) -> dict[str, dict[str, Any]]:
    """대상 종목의 DART 스냅샷을 같은 기준일로 생성한다."""
    if not targets:
        raise ValueError("최소 하나의 대상 종목이 필요합니다.")
    dt.date.fromisoformat(as_of)
    outputs: dict[str, dict[str, Any]] = {}
    for ticker, company_name in targets.items():
        raw_financials, source = collector(ticker, as_of)
        if source != "dart":
            raise RuntimeError(f"{ticker}: DART 실데이터가 아니므로 적재 파일을 만들지 않습니다.")
        fiscal_year = int(raw_financials["fiscal_year"])
        filing = filing_loader(ticker, fiscal_year, as_of)
        errors = _financial_validation_errors(raw_financials, as_of)
        errors.extend(filing.get("validation_errors", []))
        outputs[ticker] = financial_tracks.build_financial_track(
            ticker=ticker,
            company_name=company_name,
            as_of=as_of,
            raw_financials=raw_financials,
            statement=str(filing["statement"]),
            receipt_no=str(filing["receipt_no"]),
            filed_at=str(filing["filed_at"]),
            validation_errors=errors,
        )
    return outputs


def write_financial_outputs(
    outputs: Mapping[str, dict[str, Any]], out_dir: Path
) -> None:
    for ticker, output in outputs.items():
        financial_tracks.write_financial_track(
            output, out_dir / f"{ticker}_financial.json"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=_parse_target,
        action="append",
        required=True,
        metavar="TICKER:COMPANY",
    )
    parser.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    parser.add_argument("--out-dir", type=Path, default=Path("out/financial_tracks"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    outputs = run_financial_cycle(dict(args.target), as_of=args.as_of)
    write_financial_outputs(outputs, args.out_dir)
    for ticker, output in outputs.items():
        print(
            f"{ticker}: status={output['status']} "
            f"fiscal_year={output['filing']['fiscal_year']} metrics={len(output['metrics'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import tarfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

REQUIRED_COLUMNS = {
    "Date",
    "Code",
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "Sigma",
    "Trading_Halt",
}
NON_FEATURE_COLUMNS = {
    "Date",
    "Code",
    "Name",
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "IsDelisted",
    "Log_Ret",
    "Sigma",
    "Y_Label",
    "Trading_Halt",
}


class HandoffContractError(ValueError):
    """Drive 전달 데이터가 chart processed 계약을 어길 때 발생한다."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_code(value: object) -> str:
    raw = str(value).strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{1,6}", raw):
        raise HandoffContractError(
            "종목 코드는 1~6자리 영문 대문자/숫자 KRX 단축코드여야 합니다: "
            f"{value!r}"
        )
    return raw.zfill(6)


def _read_universe(path: Path, code_column: str) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"universe 파일을 찾을 수 없습니다: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or code_column not in reader.fieldnames:
            raise HandoffContractError(
                f"universe CSV에 {code_column!r} 컬럼이 없습니다: {reader.fieldnames}"
            )
        codes = [_normalize_code(row[code_column]) for row in reader]
    if not codes:
        raise HandoffContractError("universe CSV가 비어 있습니다.")
    duplicates = sorted(code for code, count in Counter(codes).items() if count > 1)
    if duplicates:
        raise HandoffContractError(f"universe에 중복 종목 코드가 있습니다: {duplicates[:5]}")
    return sorted(codes)


def _git_commit(cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _validate_processed_file(path: Path, expected_code: str) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    columns = parquet.schema_arrow.names
    missing = sorted(REQUIRED_COLUMNS - set(columns))
    if missing:
        raise HandoffContractError(f"{path.name}: 필수 컬럼이 없습니다: {missing}")

    key_frame = pd.read_parquet(path, columns=["Date", "Code", "Sigma"])
    if key_frame.empty:
        raise HandoffContractError(f"{path.name}: 데이터가 비어 있습니다.")
    dates = pd.to_datetime(key_frame["Date"], errors="coerce")
    if dates.isna().any():
        raise HandoffContractError(f"{path.name}: 해석할 수 없는 Date가 있습니다.")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    if (dates != dates.dt.normalize()).any():
        raise HandoffContractError(f"{path.name}: Date에 시간값이 포함돼 있습니다.")

    codes = key_frame["Code"].astype("string").str.strip().str.zfill(6)
    observed_codes = sorted(codes.dropna().unique().tolist())
    if observed_codes != [expected_code]:
        raise HandoffContractError(
            f"{path.name}: 파일명 종목 {expected_code}와 Code 값이 다릅니다: {observed_codes[:5]}"
        )
    if pd.DataFrame({"Date": dates, "Code": codes}).duplicated().any():
        raise HandoffContractError(f"{path.name}: (Date, Code) 중복 행이 있습니다.")
    if key_frame["Sigma"].isna().any():
        raise HandoffContractError(f"{path.name}: Sigma 결측값이 있습니다.")

    feature_columns = [column for column in columns if column not in NON_FEATURE_COLUMNS]
    return {
        "path": f"processed/{path.name}",
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "rows": int(parquet.metadata.num_rows),
        "date_start": dates.min().date().isoformat(),
        "date_end": dates.max().date().isoformat(),
        "column_count": len(columns),
        "feature_count": len(feature_columns),
        "schema_sha256": hashlib.sha256(
            "\n".join(f"{field.name}:{field.type}" for field in parquet.schema_arrow).encode()
        ).hexdigest(),
    }


def _write_normalized_universe(path: Path, codes: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Code"])
        writer.writerows([[code] for code in codes])


def _write_checksums(path: Path, entries: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for digest, relative_path in sorted(entries, key=lambda item: item[1]):
            handle.write(f"{digest}  {relative_path}\n")


def _write_package_readme(path: Path, dataset_id: str) -> None:
    path.write_text(
        f"# {dataset_id}\n\n"
        "Chart processed 스냅샷입니다. `universe.csv`에 든 종목만 포함합니다.\n\n"
        "```bash\n"
        "sha256sum -c SHA256SUMS\n"
        "```\n\n"
        "Parquet에 저장된 `Y_Label`을 H5/H20 최종 target으로 직접 사용하지 마세요. "
        "공식 실험 config와 `experiments/train_src/loaders.py`로 3분류 라벨을 다시 "
        "계산합니다. 외부 피처는 원본을 수정하지 말고 feature-store builder로 "
        "결합합니다. 자세한 내용은 저장소의 `backend/analysis/chart/ONBOARDING.md`를 "
        "참조하세요.\n",
        encoding="utf-8",
    )


def _write_archive(
    archive_path: Path,
    processed_files: list[Path],
    package_dir: Path,
) -> None:
    if archive_path.exists():
        raise FileExistsError(f"기존 archive를 덮어쓰지 않습니다: {archive_path}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, mode="w:gz") as archive:
        for name in ("README.md", "universe.csv", "DATA_MANIFEST.json", "SHA256SUMS"):
            archive.add(package_dir / name, arcname=name, recursive=False)
        for source in processed_files:
            archive.add(source, arcname=f"processed/{source.name}", recursive=False)


def prepare_handoff_package(
    processed_dir: str | Path,
    universe_file: str | Path,
    output_dir: str | Path,
    *,
    code_column: str = "Code",
    dataset_id: str = "chart_processed_holdout2025_v1",
    archive_path: str | Path | None = None,
) -> dict[str, Any]:
    source_dir = Path(processed_dir).resolve()
    source_universe = Path(universe_file).resolve()
    destination = Path(output_dir).resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"processed 디렉터리를 찾을 수 없습니다: {source_dir}")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"기존 패키지 메타데이터를 덮어쓰지 않습니다: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    codes = _read_universe(source_universe, code_column)
    processed_files = [source_dir / f"{code}.parquet" for code in codes]
    missing_files = [path.name for path in processed_files if not path.is_file()]
    if missing_files:
        raise HandoffContractError(
            f"고정 universe에 대응하는 processed 파일이 없습니다: {missing_files[:10]}"
        )

    file_reports: list[dict[str, Any]] = []
    for index, (path, code) in enumerate(zip(processed_files, codes), start=1):
        file_reports.append(_validate_processed_file(path, code))
        if index % 100 == 0 or index == len(processed_files):
            print(f"processed 검증·해시: {index}/{len(processed_files)}")
    schema_hashes = {report["schema_sha256"] for report in file_reports}
    if len(schema_hashes) != 1:
        raise HandoffContractError("processed 파일들의 Parquet schema가 서로 다릅니다.")
    feature_counts = {report["feature_count"] for report in file_reports}
    if len(feature_counts) != 1:
        raise HandoffContractError("processed 파일들의 chart feature 수가 서로 다릅니다.")

    normalized_universe = destination / "universe.csv"
    _write_normalized_universe(normalized_universe, codes)
    common_start = max(report["date_start"] for report in file_reports)
    common_end = min(report["date_end"] for report in file_reports)
    has_common_date_range = common_start <= common_end
    manifest = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(Path(__file__).resolve().parents[5]),
        "layout": "processed/<Code>.parquet",
        "source_processed_dir_name": source_dir.name,
        "universe": {
            "file": "universe.csv",
            "sha256": _sha256(normalized_universe),
            "size": len(codes),
            "codes": codes,
        },
        "coverage": {
            "earliest_date": min(report["date_start"] for report in file_reports),
            "latest_date": max(report["date_end"] for report in file_reports),
            "common_start": common_start if has_common_date_range else None,
            "common_end": common_end if has_common_date_range else None,
            "has_common_date_range": has_common_date_range,
            "total_rows": sum(report["rows"] for report in file_reports),
        },
        "processed_contract": {
            "file_count": len(file_reports),
            "feature_count": next(iter(feature_counts)),
            "required_columns": sorted(REQUIRED_COLUMNS),
            "stored_y_label_is_not_experiment_target": True,
            "label_policy": (
                "train_src.loaders가 H5/H20 config의 dynamic-sigma 설정으로 "
                "Y_Label(0=down, 1=neutral, 2=up)을 실행 시 다시 계산한다."
            ),
            "market_volatility_policy": (
                "평가 시 고정 universe의 날짜별 Sigma 단면 평균으로 계산하며 모델 피처가 아니다."
            ),
        },
        "files": file_reports,
    }
    archive = Path(archive_path).resolve() if archive_path is not None else None
    if archive is not None:
        manifest["archive"] = {
            "file": archive.name,
            "sha256_file": f"{archive.name}.sha256",
        }
    manifest_path = destination / "DATA_MANIFEST.json"
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    readme_path = destination / "README.md"
    _write_package_readme(readme_path, dataset_id)

    checksums = [
        (report["sha256"], report["path"]) for report in file_reports
    ] + [
        (_sha256(normalized_universe), "universe.csv"),
        (_sha256(manifest_path), "DATA_MANIFEST.json"),
        (_sha256(readme_path), "README.md"),
    ]
    _write_checksums(destination / "SHA256SUMS", checksums)

    if archive is not None:
        _write_archive(archive, processed_files, destination)
        archive_checksum = archive.with_name(f"{archive.name}.sha256")
        _write_checksums(archive_checksum, [(_sha256(archive), archive.name)])
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="고정 universe의 chart processed 스냅샷을 Drive 전달용으로 검증합니다."
    )
    parser.add_argument("--processed-dir", required=True)
    parser.add_argument("--universe-file", required=True)
    parser.add_argument("--output-dir", required=True, help="manifest/checksum 출력 폴더")
    parser.add_argument("--code-column", default="Code")
    parser.add_argument("--dataset-id", default="chart_processed_holdout2025_v1")
    parser.add_argument(
        "--archive",
        help="선택적 .tar.gz 출력 경로. 지정하지 않으면 대용량 파일을 복사하지 않습니다.",
    )
    args = parser.parse_args()
    manifest = prepare_handoff_package(
        args.processed_dir,
        args.universe_file,
        args.output_dir,
        code_column=args.code_column,
        dataset_id=args.dataset_id,
        archive_path=args.archive,
    )
    print(f"검증 완료: {manifest['processed_contract']['file_count']}개 종목")
    print(f"metadata: {Path(args.output_dir).resolve()}")
    if args.archive:
        print(f"archive: {Path(args.archive).resolve()}")


if __name__ == "__main__":
    main()

"""표준 외부 피처 Parquet을 기존 processed 패널에 안전하게 결합한다.

이 모듈은 train.py를 변경하지 않는다. 결과를 ``data/feature_store/<profile>/``에
종목별 Parquet으로 저장하면 기존 실험 설정의 ``data.price_dir``만 해당 경로로
바꿔 현재 학습·검증·테스트 흐름을 그대로 재사용할 수 있다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = ("Date", "Code", "AvailableDate")
RESERVED_SOURCE_COLUMNS = frozenset({"date", "code", "availabledate"})
ALLOWED_BASE_TARGET_COLUMNS = frozenset({"y_label"})
SUPPORTED_APPLY_PERIODS = {"one_day", "until_next_update"}
SUPPORTED_MISSING_POLICIES = {"zero", "forward_fill", "drop", "error"}
FORBIDDEN_FEATURE_COLUMNS = {
    "y_label",
    "target",
    "target_h5",
    "target_h20",
    "next_day_return",
    "future_return",
}
REQUIRED_BASE_COLUMNS = {
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
    "Trading_Halt",
}


class FeatureContractError(ValueError):
    """외부 피처 파일 또는 설정이 학습 데이터 계약을 어긴 경우 발생한다."""


@dataclass(frozen=True)
class FeatureSourceSpec:
    name: str
    path: Path
    apply_period: str
    columns: tuple[str, ...]
    missing_policy: str
    add_indicator: bool
    max_staleness_trading_days: int | None


@dataclass
class LoadedFeatureSource:
    spec: FeatureSourceSpec
    frame: pd.DataFrame
    fingerprint: dict[str, Any]


def chart_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_chart_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (chart_root() / path).resolve()


def _normalize_date(series: pd.Series, column: str, source_name: str) -> pd.Series:
    # format="mixed"는 pandas 2.0부터 지원된다. 1.5는 dateutil 기반의 기존
    # 벡터화 파서를 사용해 requirements.txt의 선언된 하한에서도 같은 계약을 지킨다.
    pandas_major = int(pd.__version__.split(".", maxsplit=1)[0])
    if pandas_major >= 2:
        normalized = pd.to_datetime(series, errors="coerce", format="mixed")
    else:
        normalized = pd.to_datetime(series, errors="coerce")
    if getattr(normalized.dt, "tz", None) is not None:
        normalized = normalized.dt.tz_localize(None)
    if normalized.isna().any():
        sample = series[normalized.isna()].head(3).tolist()
        raise FeatureContractError(
            f"{source_name}: {column}에 해석할 수 없는 날짜가 있습니다: {sample}"
        )
    return normalized.dt.normalize()


def _normalize_code(series: pd.Series, source_name: str) -> pd.Series:
    raw = series.astype("string").str.strip().str.upper()
    invalid = raw.isna() | ~raw.str.fullmatch(r"(?:\d{1,6}|\d{4}[0-9A-Z]{2})")
    if invalid.any():
        sample = raw[invalid].head(3).tolist()
        raise FeatureContractError(
            f"{source_name}: Code는 앞자리 0을 보존한 1~6자리 숫자여야 합니다: {sample}"
        )
    return raw.str.zfill(6)


def _fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(path.name.encode())
    digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "manifest_sha256": digest.hexdigest(),
    }


def _canonical_column(column: object) -> str:
    return str(column).strip().casefold()


def _is_target_like_column(column: object) -> bool:
    canonical = _canonical_column(column)
    return (
        canonical in FORBIDDEN_FEATURE_COLUMNS
        or canonical.startswith(("target", "future_", "next_"))
        or canonical.endswith("_label")
    )


def _is_forbidden_source_column(column: object) -> bool:
    canonical = _canonical_column(column)
    return canonical in RESERVED_SOURCE_COLUMNS or _is_target_like_column(canonical)


def _parse_source_spec(source_config: dict[str, Any]) -> FeatureSourceSpec:
    required = ("name", "path", "apply_period", "columns")
    missing = [key for key in required if key not in source_config]
    if missing:
        raise FeatureContractError(f"외부 피처 source 설정에 필수 항목이 없습니다: {missing}")

    name = str(source_config["name"]).strip()
    if not name:
        raise FeatureContractError("외부 피처 source.name은 비어 있을 수 없습니다.")

    apply_period = str(source_config["apply_period"])
    if apply_period not in SUPPORTED_APPLY_PERIODS:
        raise FeatureContractError(
            f"{name}: apply_period는 {sorted(SUPPORTED_APPLY_PERIODS)} 중 하나여야 합니다."
        )

    columns = tuple(str(column).strip() for column in source_config["columns"])
    canonical_columns = tuple(_canonical_column(column) for column in columns)
    if (
        not columns
        or any(not column for column in columns)
        or len(columns) != len(set(canonical_columns))
    ):
        raise FeatureContractError(f"{name}: columns는 중복 없는 한 개 이상의 컬럼이어야 합니다.")
    forbidden = sorted(column for column in columns if _is_forbidden_source_column(column))
    if forbidden:
        raise FeatureContractError(
            f"{name}: 키, 미래 정보 또는 target 컬럼은 사용할 수 없습니다: {forbidden}"
        )

    missing_config = source_config.get("missing", {})
    if not isinstance(missing_config, dict):
        raise FeatureContractError(f"{name}: missing은 YAML 객체여야 합니다.")
    missing_policy = str(missing_config.get("policy", "error"))
    if missing_policy not in SUPPORTED_MISSING_POLICIES:
        raise FeatureContractError(
            f"{name}: missing.policy는 {sorted(SUPPORTED_MISSING_POLICIES)} 중 하나여야 합니다."
        )

    max_staleness = missing_config.get("max_staleness_trading_days")
    if max_staleness is not None and (
        isinstance(max_staleness, bool) or not isinstance(max_staleness, int) or max_staleness < 0
    ):
        raise FeatureContractError(
            f"{name}: missing.max_staleness_trading_days는 0 이상의 정수여야 합니다."
        )
    if apply_period == "until_next_update" and max_staleness is None:
        raise FeatureContractError(
            f"{name}: until_next_update는 오래된 값 사용을 막기 위해 "
            "missing.max_staleness_trading_days를 지정해야 합니다."
        )
    if missing_policy == "forward_fill" and max_staleness is None:
        raise FeatureContractError(
            f"{name}: forward_fill은 오래된 값 사용을 막기 위해 "
            "missing.max_staleness_trading_days를 지정해야 합니다."
        )

    return FeatureSourceSpec(
        name=name,
        path=_resolve_chart_path(source_config["path"]),
        apply_period=apply_period,
        columns=columns,
        missing_policy=missing_policy,
        add_indicator=bool(missing_config.get("add_indicator", False)),
        max_staleness_trading_days=max_staleness,
    )


def _validate_source_frame(spec: FeatureSourceSpec, frame: pd.DataFrame) -> pd.DataFrame:
    missing_columns = sorted(set(REQUIRED_COLUMNS).union(spec.columns) - set(frame.columns))
    if missing_columns:
        raise FeatureContractError(f"{spec.name}: Parquet 필수 컬럼이 없습니다: {missing_columns}")

    selected = frame[[*REQUIRED_COLUMNS, *spec.columns]].copy()
    selected["Date"] = _normalize_date(selected["Date"], "Date", spec.name)
    selected["AvailableDate"] = _normalize_date(
        selected["AvailableDate"], "AvailableDate", spec.name
    )
    selected["Code"] = _normalize_code(selected["Code"], spec.name)

    if (selected["AvailableDate"] < selected["Date"]).any():
        sample = selected.loc[
            selected["AvailableDate"] < selected["Date"], ["Code", "Date", "AvailableDate"]
        ].head(3)
        raise FeatureContractError(
            f"{spec.name}: AvailableDate는 Date보다 이를 수 없습니다: {sample.to_dict('records')}"
        )

    duplicate_keys = selected.duplicated(["Code", "Date", "AvailableDate"])
    if duplicate_keys.any():
        sample = selected.loc[duplicate_keys, ["Code", "Date", "AvailableDate"]].head(3)
        raise FeatureContractError(
            f"{spec.name}: (Code, Date, AvailableDate) 중복 행이 있습니다: {sample.to_dict('records')}"
        )

    duplicate_available = selected.duplicated(["Code", "AvailableDate"])
    if duplicate_available.any():
        sample = selected.loc[duplicate_available, ["Code", "Date", "AvailableDate"]].head(3)
        raise FeatureContractError(
            f"{spec.name}: 같은 Code/AvailableDate에 두 값이 있어 적용 시점이 모호합니다: "
            f"{sample.to_dict('records')}"
        )

    for column in spec.columns:
        numeric = pd.to_numeric(selected[column], errors="coerce")
        invalid = selected[column].notna() & numeric.isna()
        if invalid.any():
            sample = selected.loc[invalid, column].head(3).tolist()
            raise FeatureContractError(f"{spec.name}: {column}은 숫자형 피처여야 합니다: {sample}")
        selected[column] = numeric.astype(float)

    return selected.sort_values(["Code", "AvailableDate"], kind="stable").reset_index(drop=True)


def load_feature_sources(source_configs: list[dict[str, Any]]) -> list[LoadedFeatureSource]:
    """설정의 외부 source를 읽고 표준 Parquet 계약을 검증한다.

    이 단계에서 ``AvailableDate``·중복 키·숫자형 여부를 먼저 검사한다. 따라서
    이후 결합 단계에서는 외부 파일의 미래 값을 과거 행에 붙일 수 없다.
    """
    if not source_configs:
        raise FeatureContractError("features.sources에 한 개 이상의 외부 피처 source가 필요합니다.")

    loaded: list[LoadedFeatureSource] = []
    seen_names: set[str] = set()
    seen_columns: set[str] = set()
    for source_config in source_configs:
        spec = _parse_source_spec(source_config)
        if spec.name in seen_names:
            raise FeatureContractError(f"외부 피처 source.name이 중복됩니다: {spec.name}")
        if not spec.path.is_file():
            raise FileNotFoundError(f"{spec.name}: 외부 피처 Parquet을 찾을 수 없습니다: {spec.path}")
        overlap = sorted(seen_columns & set(spec.columns))
        if overlap:
            raise FeatureContractError(
                f"외부 피처 컬럼명은 source 간 중복될 수 없습니다: {overlap}"
            )

        frame = _validate_source_frame(spec, pd.read_parquet(spec.path))
        loaded.append(LoadedFeatureSource(spec=spec, frame=frame, fingerprint=_fingerprint(spec.path)))
        seen_names.add(spec.name)
        seen_columns.update(spec.columns)
    return loaded


def _panel_trading_days(base: pd.DataFrame) -> pd.DataFrame:
    """종목별 패널 행에 거래일 순번을 부여한다."""
    trading_days = base[["Code", "Date"]].drop_duplicates().sort_values(
        ["Code", "Date"], kind="stable"
    )
    trading_days["_trading_day_index"] = trading_days.groupby(
        "Code", observed=True
    ).cumcount()
    return trading_days


def _map_to_next_panel_day(
    base: pd.DataFrame, source: LoadedFeatureSource
) -> pd.DataFrame:
    """외부 AvailableDate를 해당 종목의 첫 패널 거래일에 맞춘다.

    외부 시스템이 주말·휴일을 AvailableDate로 기록해도 다음 개장일에만 사용할 수
    있게 한다. 패널 범위 뒤의 값은 아직 학습 데이터에서 사용할 수 없으므로 제외한다.
    """
    codes = base["Code"].unique()
    filtered = source.frame.loc[source.frame["Code"].isin(codes)].copy()
    if filtered.empty:
        return filtered.assign(_effective_date=pd.NaT, _effective_trading_day_index=pd.NA)

    trading_days = _panel_trading_days(base).rename(
        columns={"Date": "_effective_date", "_trading_day_index": "_effective_trading_day_index"}
    )
    left = filtered.sort_values(["AvailableDate", "Code"], kind="stable")
    right = trading_days.sort_values(["_effective_date", "Code"], kind="stable")
    mapped = pd.merge_asof(
        left,
        right,
        left_on="AvailableDate",
        right_on="_effective_date",
        by="Code",
        direction="forward",
        allow_exact_matches=True,
    )
    return mapped.loc[mapped["_effective_date"].notna()].copy()


def _join_one_day(base: pd.DataFrame, source: LoadedFeatureSource) -> pd.DataFrame:
    mapped = _map_to_next_panel_day(base, source)
    payload = mapped[["Code", "_effective_date", *source.spec.columns]].rename(
        columns={"_effective_date": "Date"}
    )
    duplicate_effective_date = payload.duplicated(["Code", "Date"])
    if duplicate_effective_date.any():
        sample = payload.loc[duplicate_effective_date, ["Code", "Date"]].head(3)
        raise FeatureContractError(
            f"{source.spec.name}: 비거래일을 다음 거래일로 매핑한 뒤 같은 Code/Date에 "
            f"여러 값이 생겼습니다. 외부 데이터를 일별로 집계하세요: {sample.to_dict('records')}"
        )
    return base.merge(payload, on=["Code", "Date"], how="left", validate="many_to_one")


def _join_until_next_update(base: pd.DataFrame, source: LoadedFeatureSource) -> pd.DataFrame:
    trading_days = _panel_trading_days(base)
    left = base[["Code", "Date"]].merge(
        trading_days, on=["Code", "Date"], how="left", validate="one_to_one"
    )
    left["_panel_row"] = base.index
    mapped = _map_to_next_panel_day(base, source)
    right = mapped[
        ["Code", "_effective_date", "_effective_trading_day_index", *source.spec.columns]
    ]

    joined = pd.merge_asof(
        left.sort_values(["Date", "Code"], kind="stable"),
        right.sort_values(["_effective_date", "Code"], kind="stable"),
        left_on="Date",
        right_on="_effective_date",
        by="Code",
        direction="backward",
        allow_exact_matches=True,
    )
    max_staleness = source.spec.max_staleness_trading_days
    if max_staleness is not None:
        age = joined["_trading_day_index"] - joined["_effective_trading_day_index"]
        joined.loc[age > max_staleness, list(source.spec.columns)] = float("nan")

    values = joined.set_index("_panel_row")
    result = base.copy()
    for column in source.spec.columns:
        result[column] = values[column].reindex(result.index)
    return result


def _apply_missing_policy(panel: pd.DataFrame, source: LoadedFeatureSource) -> pd.DataFrame:
    columns = list(source.spec.columns)
    original_missing = panel[columns].isna()

    if source.spec.add_indicator:
        for column in columns:
            indicator = f"{source.spec.name}__{column}__missing"
            if indicator in panel.columns:
                raise FeatureContractError(f"결측 표시 피처 이름이 기존 컬럼과 충돌합니다: {indicator}")
            panel[indicator] = original_missing[column].astype("int8")

    policy = source.spec.missing_policy
    if policy == "zero":
        panel[columns] = panel[columns].fillna(0.0)
    elif policy == "forward_fill":
        # until_next_update는 as-of join 자체가 직전 공개값을 전달한다. 여기서 다시
        # ffill하면 staleness 제한으로 비운 값을 되살릴 수 있으므로 one_day에만 적용한다.
        if source.spec.apply_period == "one_day":
            limit = source.spec.max_staleness_trading_days
            if limit:
                panel[columns] = panel.groupby("Code", observed=True)[columns].ffill(
                    limit=limit
                )
    elif policy == "drop":
        panel = panel.loc[~original_missing.any(axis=1)].copy()
    elif policy == "error" and original_missing.any().any():
        bad_rows = panel.loc[original_missing.any(axis=1), ["Date", "Code"]].head(5)
        raise FeatureContractError(
            f"{source.spec.name}: 외부 피처 결측 행이 있습니다. missing.policy를 변경하거나 "
            f"입력 데이터를 보완하세요: {bad_rows.to_dict('records')}"
        )
    return panel


def _select_base_columns(base: pd.DataFrame, features_config: dict[str, Any]) -> pd.DataFrame:
    """학습에 필요한 가격 메타데이터를 보존하면서 Alpha158 컬럼을 설정으로 좁힌다."""
    forbidden_base = sorted(
        str(column)
        for column in base.columns
        if _is_target_like_column(column)
        and _canonical_column(column) not in ALLOWED_BASE_TARGET_COLUMNS
    )
    if forbidden_base:
        raise FeatureContractError(
            "기본 processed 패널에 미래 정보 또는 target 컬럼이 있습니다: "
            f"{forbidden_base}"
        )

    requested = features_config.get("base_columns", "*")
    excluded = {str(column) for column in features_config.get("exclude_columns", [])}
    protected = REQUIRED_BASE_COLUMNS & set(base.columns)
    forbidden_exclusions = sorted(protected & excluded)
    if forbidden_exclusions:
        raise FeatureContractError(
            "라벨 생성과 거래 가능 여부 판단에 필요한 기본 컬럼은 제외할 수 없습니다: "
            f"{forbidden_exclusions}"
        )

    if requested == "*":
        selected = [column for column in base.columns if column not in excluded]
    elif isinstance(requested, list) and all(isinstance(column, str) for column in requested):
        missing = sorted(set(requested) - set(base.columns))
        if missing:
            raise FeatureContractError(f"base_columns에 없는 processed 컬럼이 있습니다: {missing}")
        selected_set = set(requested) | protected
        selected = [column for column in base.columns if column in selected_set and column not in excluded]
    else:
        raise FeatureContractError('features.base_columns는 "*" 또는 문자열 컬럼 목록이어야 합니다.')
    return base[selected].copy()


def assemble_feature_panel(base: pd.DataFrame, sources: list[LoadedFeatureSource]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """한 processed DataFrame에 검증된 source를 결합하고 결측 정책을 적용한다.

    ``one_day``는 AvailableDate와 같은 행에만, ``until_next_update``는 해당 날짜
    이후의 가장 최근 공개값만 붙인다. 이 함수는 메모리 안에서만 패널을 조립하고
    원본 ``data/processed`` 파일은 절대 수정하지 않는다.
    """
    missing_base_columns = {"Date", "Code"} - set(base.columns)
    if missing_base_columns:
        raise FeatureContractError(f"기본 processed 패널에 키 컬럼이 없습니다: {sorted(missing_base_columns)}")

    panel = base.copy()
    panel["Date"] = _normalize_date(panel["Date"], "Date", "기본 processed 패널")
    panel["Code"] = _normalize_code(panel["Code"], "기본 processed 패널")
    if panel.duplicated(["Date", "Code"]).any():
        raise FeatureContractError("기본 processed 패널에 (Date, Code) 중복 행이 있습니다.")
    # 결측 forward-fill은 현재 행 순서가 아니라 종목별 시간 순서에서만 안전하다.
    panel = panel.sort_values(["Code", "Date"], kind="stable").reset_index(drop=True)

    report: dict[str, Any] = {"input_rows": int(len(panel)), "sources": {}}
    for source in sources:
        collisions = sorted(set(source.spec.columns) & set(panel.columns))
        if collisions:
            raise FeatureContractError(
                f"{source.spec.name}: 외부 피처가 기존 processed 컬럼과 충돌합니다: {collisions}"
            )
        if source.spec.apply_period == "one_day":
            panel = _join_one_day(panel, source)
        else:
            panel = _join_until_next_update(panel, source)

        missing_before_policy = panel[list(source.spec.columns)].isna().mean().to_dict()
        panel = _apply_missing_policy(panel, source)
        report["sources"][source.spec.name] = {
            "apply_period": source.spec.apply_period,
            "missing_policy": source.spec.missing_policy,
            "max_staleness_trading_days": source.spec.max_staleness_trading_days,
            "feature_columns": list(source.spec.columns),
            "missing_rate_before_policy": {
                key: float(value) for key, value in missing_before_policy.items()
            },
        }

    report["output_rows"] = int(len(panel))
    report["output_columns"] = int(len(panel.columns))
    return panel.sort_values(["Date", "Code"], kind="stable").reset_index(drop=True), report


def build_feature_store(
    config: dict[str, Any],
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """processed 폴더 전체를 외부 피처가 결합된 별도 feature store로 생성한다.

    ``features.base_processed_dir``가 있으면 builder는 그 원본을 읽고, 학습 runner는
    기존 ``data.price_dir``을 계속 사용한다. 그러므로 하나의 local.yaml에서
    원본 경로와 학습용 feature store 경로를 분리할 수 있으며 train.py 변경이 없다.
    """
    features_config = config.get("features", {})
    source_configs = features_config.get("sources", [])
    sources = load_feature_sources(source_configs)

    data_config = config.get("data", {})
    source_dir = _resolve_chart_path(
        features_config.get("base_processed_dir", data_config.get("price_dir", "data/processed"))
    )
    if not source_dir.is_dir():
        raise FileNotFoundError(f"기본 processed 디렉터리를 찾을 수 없습니다: {source_dir}")
    base_files = sorted(source_dir.glob("*.parquet"))
    if not base_files:
        raise FeatureContractError(f"기본 processed 디렉터리에 Parquet 파일이 없습니다: {source_dir}")

    configured_output = output_dir or features_config.get("materialized_dir")
    if not configured_output:
        raise FeatureContractError(
            "결합 패널 저장 경로가 없습니다. features.materialized_dir 또는 --output을 지정하세요."
        )
    destination = _resolve_chart_path(configured_output)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(
            f"기존 feature store를 덮어쓰지 않습니다: {destination}. 새 profile 경로를 사용하세요."
        )
    destination.mkdir(parents=True, exist_ok=True)

    file_reports: list[dict[str, Any]] = []
    for base_file in base_files:
        base = _select_base_columns(pd.read_parquet(base_file), features_config)
        panel, report = assemble_feature_panel(base, sources)
        panel.to_parquet(destination / base_file.name, index=False)
        file_reports.append({"file": base_file.name, **report})

    manifest = {
        "profile_name": features_config.get("profile_name", destination.name),
        "input_processed_dir": str(source_dir),
        "output_feature_store_dir": str(destination),
        "base_columns": features_config.get("base_columns", "*"),
        "exclude_columns": features_config.get("exclude_columns", []),
        "source_fingerprints": {source.spec.name: source.fingerprint for source in sources},
        "sources": [
            {
                "name": source.spec.name,
                "path": str(source.spec.path),
                "apply_period": source.spec.apply_period,
                "columns": list(source.spec.columns),
                "missing_policy": source.spec.missing_policy,
                "add_indicator": source.spec.add_indicator,
                "max_staleness_trading_days": source.spec.max_staleness_trading_days,
            }
            for source in sources
        ],
        "files": file_reports,
    }
    with (destination / "feature_manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, default=str)
    return manifest

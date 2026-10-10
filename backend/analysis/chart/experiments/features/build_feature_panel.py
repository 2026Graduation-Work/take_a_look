"""외부 피처를 결합한 feature store를 생성하는 CLI."""

from __future__ import annotations

import argparse

from experiments.config import load_experiment_config

from .local_panel import prepare_local_panel


def main() -> None:
    parser = argparse.ArgumentParser(description="외부 Parquet 피처를 processed 패널에 결합합니다.")
    parser.add_argument("--config", required=True, help="실험용 local.yaml 경로")
    parser.add_argument("--output", help="feature store 출력 경로; 없으면 config 값을 사용")
    args = parser.parse_args()

    config = load_experiment_config(args.config)
    if args.output:
        raise ValueError("Configure the dataset root instead of --output")
    manifest = prepare_local_panel(config)
    print(f"feature store 생성 완료: {manifest['output_feature_store_dir']}")
    print(f"처리된 종목 파일 수: {len(manifest['files'])}")


if __name__ == "__main__":
    main()

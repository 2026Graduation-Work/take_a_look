#!/bin/bash
# 하나의 로컬 config를 학습·분석한다. Git에 없는 과거 후보 config 이름을 참조하지 않는다.
# 사용법: ./run_h10_selection.sh [configs/local.yaml]
# Run from any directory. Override PYTHON_BIN when a specific virtualenv is needed.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENTS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
cd "$EXPERIMENTS_DIR"

CONFIG_PATH="${1:-configs/local.yaml}"
if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Config not found: $CONFIG_PATH" >&2
  echo "Create one with: cp configs/base.yaml configs/local.yaml" >&2
  exit 1
fi

echo "Starting H=10 selection experiment: $CONFIG_PATH"
"$PYTHON_BIN" train.py --config "$CONFIG_PATH"
"$PYTHON_BIN" run_experiment_analysis.py --config "$CONFIG_PATH"

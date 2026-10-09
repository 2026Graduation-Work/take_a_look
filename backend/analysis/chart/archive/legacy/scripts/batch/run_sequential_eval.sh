#!/bin/bash
# 하나의 로컬 config의 학습·ML 평가·백테스트를 순차 실행한다.
# 사용법: ./run_sequential_eval.sh [configs/local.yaml]
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

echo "[1/3] train: $CONFIG_PATH"
"$PYTHON_BIN" train.py --config "$CONFIG_PATH"
echo "[2/3] ML evaluation"
"$PYTHON_BIN" run_ml_evaluation.py --config "$CONFIG_PATH"
echo "[3/3] backtest"
"$PYTHON_BIN" run_backtest.py --config "$CONFIG_PATH"

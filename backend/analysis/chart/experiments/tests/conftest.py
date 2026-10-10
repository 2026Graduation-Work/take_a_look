# ruff: noqa: I001

import sys
from pathlib import Path


CHART_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CHART_DIR))

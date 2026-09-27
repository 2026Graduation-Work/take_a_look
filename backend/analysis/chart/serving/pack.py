"""Validate the committed H5/H20 model pack."""

import argparse
import os
from pathlib import Path

import yaml

from .internal.pack import load_pack


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate"])
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.yaml"))
    parser.add_argument("--path", type=Path)
    args = parser.parse_args(argv)
    config = yaml.safe_load(args.config.read_text())["active_pack"]
    data_root = Path(os.environ.get("CHART_SERVING_DATA_DIR", Path(__file__).parent / "data"))
    path = args.path or data_root / "packs" / config["pack_id"]
    print(load_pack(path)[0]["pack_id"])

if __name__ == "__main__":
    main()

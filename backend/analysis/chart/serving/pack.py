"""Validate or download the active H5/H20 model pack."""

import argparse
from pathlib import Path

import yaml

from .internal.pack import config_path, download, load_pack


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["download", "validate"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "download":
        print(download(args.config or config_path()))
    else:
        if not args.path:
            parser.error("--path is required for validate")
        config = args.config or config_path()
        digest = None
        if args.config or config.is_file():
            active = yaml.safe_load(config.read_text())["active_pack"]
            if active["pack_id"] == args.path.name:
                digest = active.get("golden_sha256")
            elif args.config:
                parser.error("--config active pack must match --path")
        print(load_pack(args.path, golden_sha256=digest)[0]["pack_id"])


if __name__ == "__main__":
    main()

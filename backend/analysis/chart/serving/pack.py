"""Validate or download the active H5/H20 model pack."""

import argparse
from pathlib import Path

from .internal.pack import download, load_pack


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["download", "validate"])
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.yaml"))
    parser.add_argument("--path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "download":
        print(download(args.config))
    else:
        if not args.path:
            parser.error("--path is required for validate")
        print(load_pack(args.path)[0]["pack_id"])


if __name__ == "__main__":
    main()

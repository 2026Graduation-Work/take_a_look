"""Validate the committed H5/H20 model pack."""

import argparse
from pathlib import Path

from .internal.pack import load_pack
from .internal.pipeline import active_pack


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate"])
    parser.add_argument("--path", type=Path)
    args = parser.parse_args(argv)
    manifest = load_pack(args.path)[0] if args.path else active_pack()[0]
    print(manifest["pack_id"])

if __name__ == "__main__":
    main()

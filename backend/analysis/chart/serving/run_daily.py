"""Collect confirmed KRX prices, infer H5/H20, and publish one atomic batch."""

import argparse
import json

from .internal.pipeline import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", help="Confirmed KRX date YYYY-MM-DD")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.publish and args.dry_run:
        parser.error("Choose --publish or --dry-run")
    try:
        run(args)
    except Exception as exc:
        print(json.dumps({"event": "failed", "stage": "daily", "error_type": type(exc).__name__}))
        raise


if __name__ == "__main__":
    main()

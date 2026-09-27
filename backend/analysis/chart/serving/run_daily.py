"""Collect confirmed KRX prices, infer H5/H20, and publish one atomic batch."""

import argparse
import json

from .internal.pipeline import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", help="Confirmed KRX date YYYY-MM-DD")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--historical-test", action="store_true", help="Fetch past inputs again in local Supabase; dry run only")
    parser.add_argument("--code", help="Six-digit stock code for --historical-test")
    args = parser.parse_args(argv)
    if args.publish and args.dry_run:
        parser.error("Choose --publish or --dry-run")
    if args.historical_test and (not args.as_of or not args.dry_run or args.publish):
        parser.error("--historical-test requires --as-of and --dry-run")
    if args.code and not args.historical_test:
        parser.error("--code requires --historical-test")
    try:
        run(args)
    except Exception as exc:
        print(json.dumps({"event": "failed", "stage": "daily", "error_type": type(exc).__name__}))
        raise


if __name__ == "__main__":
    main()

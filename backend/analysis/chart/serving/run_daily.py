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
    parser.add_argument("--diagnose", action="store_true", help="Check KRX reads without database writes")
    parser.add_argument("--replay", action="store_true", help="Use archived inputs; requires --as-of")
    args = parser.parse_args(argv)
    if args.replay and (not args.as_of or args.historical_test or args.diagnose):
        parser.error("--replay requires --as-of and cannot combine with historical-test or diagnose")
    if args.diagnose and (args.publish or args.historical_test or args.code):
        parser.error("--diagnose cannot publish or run historical tests")
    if args.publish and args.dry_run:
        parser.error("Choose --publish or --dry-run")
    if args.historical_test and (not args.as_of or not args.dry_run or args.publish):
        parser.error("--historical-test requires --as-of and --dry-run")
    if args.code and not args.historical_test:
        parser.error("--code requires --historical-test")
    try:
        if args.diagnose:
            from .internal.krx import diagnose
            diagnose()
        else:
            run(args)
    except Exception as exc:
        print(json.dumps({"event": "failed", "stage": "daily", "error_type": type(exc).__name__}))
        raise


if __name__ == "__main__":
    main()

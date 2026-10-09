"""Compute corrected model snapshots from cached prices, optionally in local Supabase."""

import argparse

from .internal.pipeline import run_preview


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", default="005930", help="Cached six-character stock code")
    parser.add_argument("--as-of", help="Cached actual price date; defaults to latest cached date")
    parser.add_argument("--dataset-root", help="Corrected local dataset root for a new model pack")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--publish", action="store_true", help="Publish to local Supabase for the frontend")
    mode.add_argument("--compute-only", action="store_true", help="Compute snapshots without Supabase")
    run_preview(parser.parse_args(argv))


if __name__ == "__main__":
    main()

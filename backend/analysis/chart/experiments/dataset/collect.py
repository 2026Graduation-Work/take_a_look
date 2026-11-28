"""Build or resume a verified research dataset."""
import argparse
from pathlib import Path

from .pipeline import collect_dataset, verify_cached_flows
from .prepare_sources import KIND_BUDGET, SOURCE_ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--mode", choices=["full", "update"], default="full")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--action-snapshot", type=Path, help="Use an explicit verified V2 resolution snapshot")
    parser.add_argument("--source-root", type=Path, help=f"Reusable official source cache (default {SOURCE_ROOT})")
    parser.add_argument("--kind-request-budget", type=int, default=KIND_BUDGET,
                        help=f"Maximum KIND requests per run (default {KIND_BUDGET}, 0 for cached responses only)")
    parser.add_argument("--verify-flows", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_flows:
        verify_cached_flows(args.config)
    else:
        collect_dataset(args.config, mode=args.mode, rebuild=args.rebuild, action_snapshot=args.action_snapshot,
                        source_root=args.source_root, kind_request_budget=args.kind_request_budget)

if __name__ == "__main__":
    main()

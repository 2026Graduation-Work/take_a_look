"""Build or resume a verified research dataset."""
import argparse

from .pipeline import collect_dataset, verify_cached_flows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--mode", choices=["full", "update"], default="full")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--verify-flows", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_flows:
        verify_cached_flows(args.config)
    else:
        collect_dataset(args.config, mode=args.mode, rebuild=args.rebuild)

if __name__ == "__main__":
    main()

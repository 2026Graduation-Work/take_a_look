"""Build an immutable H5/H20 model and historical sample pack."""

import argparse
import json
from pathlib import Path

from shared.io import sha256_file

from .pack import build_pack


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    for horizon in (5, 20):
        parser.add_argument(f"--model-h{horizon}", type=Path, required=True)
        parser.add_argument(f"--predictions-h{horizon}", type=Path, required=True)
    parser.add_argument("--processed-dir", type=Path, required=True)
    parser.add_argument("--calendar-file", type=Path)
    parser.add_argument("--research-manifest", type=Path, help="Corrected local training provenance JSON")
    parser.add_argument("--allow-legacy-artifacts", action="store_true",
                        help="Allow model/prediction files without .manifest.json (legacy shared_v3 only)")
    args = parser.parse_args(argv)
    root, archive, reports = build_pack(
        pack_id=args.pack_id, output=args.output,
        models={5: args.model_h5, 20: args.model_h20},
        predictions={5: args.predictions_h5, 20: args.predictions_h20},
        processed_dir=args.processed_dir, calendar_file=args.calendar_file,
        research_manifest=json.loads(args.research_manifest.read_text()) if args.research_manifest else None,
        allow_legacy_artifacts=args.allow_legacy_artifacts)
    print(json.dumps({"pack": str(root), "archive": str(archive), "archive_sha256": sha256_file(archive),
                      "reports": reports}, ensure_ascii=False))


if __name__ == "__main__":
    main()

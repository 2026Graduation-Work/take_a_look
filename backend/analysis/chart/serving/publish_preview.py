"""Validate and explicitly publish the recorded display-test batch; no KRX calls."""

import argparse
import json
from pathlib import Path

from .contracts import validate_snapshot
from .internal.hashing import canonical_hash
from .internal.pipeline import active_pack
from .internal.storage import SupabaseStore

PREVIEW_DIR = Path(__file__).parent / "previews" / "2026-09-21"


def load_preview(directory=PREVIEW_DIR):
    directory = Path(directory)
    batch = json.loads((directory / "batch.json").read_text())
    snapshots = json.loads((directory / "snapshots.json").read_text())
    pack, _ = active_pack()
    if not batch["result"].get("historical_test") or batch["pack_id"] != pack["pack_id"]:
        raise ValueError("Expected a historical display-test batch for the active pack")
    expected = {(code, h) for code in batch["expected_stock_codes"] for h in (5, 20)}
    if len(snapshots) != len(expected) or {(s["stock_code"], s["horizon"]) for s in snapshots} != expected:
        raise ValueError("Preview must have exactly both horizons for each stock")
    for snapshot in snapshots:
        validate_snapshot(snapshot)
        horizon = pack["horizons"][f"h{snapshot['horizon']}"]
        if (snapshot["batch_id"] != batch["id"] or snapshot["data_asof"] != batch["as_of"]
                or snapshot["pack_id"] != batch["pack_id"]
                or snapshot["sources"]["config_sha256"] != canonical_hash(pack)
                or snapshot["sources"]["model_sha256"] != horizon["model_sha256"]
                or snapshot["sources"]["cases_sha256"] != horizon["samples_sha256"]):
            raise ValueError("Preview identity or model provenance mismatch")
    return batch, snapshots, pack


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    batch, snapshots, pack = load_preview()
    if args.publish:
        SupabaseStore().publish(batch, snapshots, pack)
    print(json.dumps({"event": "preview_published" if args.publish else "preview_validated",
                      "batch_id": batch["id"], "as_of": batch["as_of"],
                      "snapshot_count": len(snapshots), "validation_status": pack["validation_status"]}))


if __name__ == "__main__":
    main()

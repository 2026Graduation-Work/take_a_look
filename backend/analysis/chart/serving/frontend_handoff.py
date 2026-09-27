"""Export the chart-owned fields used by the existing stock detail view.

This is a handoff artifact for the frontend team. It does not invent profiling,
risk, H10, calibration, or other fields absent from the published snapshot.
"""

import argparse
import json
from pathlib import Path

from .contracts import validate_snapshot


def chart_detail_fields(snapshot):
    validate_snapshot(snapshot)
    if snapshot["contract"] != "chart_signal_detail_v2":
        raise ValueError("The frontend handoff requires chart_signal_detail_v2")
    inference = snapshot["inference"]
    distribution = snapshot["distribution"]
    history = snapshot["prices"]["history"]
    prices = [row["close"] for row in history]
    patch = {
        "code": snapshot["stock_code"],
        "name": snapshot["stock_name"],
        "asOf": snapshot["data_asof"],
        "returnHorizon": f"h{snapshot['horizon']}",
        "priceHistory": prices,
        "priceDates": [row["date"] for row in history],
        "priceProvenance": {
            "kind": "real", "source": snapshot["prices"]["source"],
            "asOf": snapshot["data_asof"],
        },
    }
    if prices:
        patch["currentPrice"] = prices[-1]
    if len(prices) >= 2:
        patch["changePercent"] = (prices[-1] / prices[-2] - 1) * 100
    if distribution["status"] == "available":
        band = distribution["histogram"]["central_68"]
        patch["returnBand"] = {"low": band["low"], "high": band["high"], "ciLevel": 0.68}
        patch["realizedReturns"] = [
            {"from": row["left"], "to": row["right"], "count": row["count"]}
            for row in distribution["histogram"]["bins"]
        ]
        patch["similarCaseCount"] = distribution["sample_count"]
    if inference["status"] == "available":
        patch["reasons"] = [
            {"title": row["label_ko"],
             "detail": f"상방 클래스 내부 원점수 기여 {row['contribution']:+.4f}",
             "source": "chart", "sourceLabel": "차트 모델 피처"}
            for row in inference["features"][:3]
        ]
    return {
        "contract": "frontend_chart_handoff_v1",
        "stockDetailPatch": patch,
        "model": {
            "status": inference["status"],
            "scores": inference["scores"],
            "sigma": inference["sigma"],
            "scoreEvent": inference["score_event"],
            "contributionSpace": inference["contribution_space"],
        },
        "historicalComparison": {
            "status": distribution["status"],
            "scoreTolerance": distribution["tolerances"]["up_absolute"],
            "sigmaRelativeTolerance": distribution["tolerances"]["sigma_relative"],
            "stockCount": distribution["stock_count"],
            "periodStart": distribution["period_start"],
            "periodEnd": distribution["period_end"],
        },
        "packId": snapshot["pack_id"],
        "batchId": snapshot["batch_id"],
        "sources": snapshot["sources"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    snapshots = json.loads(args.snapshots.read_text())
    if not isinstance(snapshots, list):
        raise ValueError("Expected a list of chart snapshots")
    result = [chart_detail_fields(snapshot) for snapshot in snapshots]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"output": str(args.output), "rows": len(result)}))


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ $# -gt 1 || ( $# -eq 1 && $1 != "--wait-for-collection" ) ]]; then
    echo "Usage: bash experiments/run_kospi_pipeline.sh [--wait-for-collection]" >&2
    exit 2
fi

# Keep the old option usable, but always process the currently available data.
if [[ ${1:-} == "--wait-for-collection" ]]; then
    echo "Collection wait disabled; using currently collected data."
fi

python -u -m experiments.dataset.preprocess --config experiments/configs/datasets/dataset_kospi.yaml --mode full --allow-partial

failed=0

for config in \
    experiments/configs/sliding_2016_2026_h5.yaml \
    experiments/configs/sliding_2016_2026_h20.yaml \
    experiments/configs/sliding_2016_2026_h5_flow.yaml \
    experiments/configs/sliding_2016_2026_h20_flow.yaml
do
    echo "Running KOSPI experiment: ${config}"
    if python -u -m experiments.features.build_feature_panel --config "${config}" &&
        python -u -m experiments.train --config "${config}" &&
        python -u -m experiments.run_experiment_analysis --config "${config}"
    then
        echo "Completed KOSPI experiment: ${config}"
    else
        echo "Failed KOSPI experiment: ${config}; continuing with the next experiment" >&2
        failed=$((failed + 1))
    fi
done

if [[ ${failed} -gt 0 ]]; then
    echo "${failed}/4 KOSPI experiments failed; inspect the output above." >&2
    exit 1
fi

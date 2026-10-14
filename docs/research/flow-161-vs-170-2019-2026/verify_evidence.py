"""Verify preserved outputs and derived summaries; does not retrain or score models."""
import csv
import hashlib
import json
import math
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_csv(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify():
    provenance = json.loads((ROOT / 'provenance.json').read_text())
    artifacts = read_csv(ROOT / 'output_artifact_hashes.csv')
    for row in artifacts:
        if row['included'] == 'True':
            path = ROOT / 'originals' / Path(row['path']).parent.name / Path(row['path']).name
            assert path.stat().st_size == int(row['bytes']), path
            assert sha256(path) == row['sha256'], path
    source = json.loads((ROOT / 'source_manifest.json').read_text())
    assert sha256(ROOT / source['archive']) == source['sha256']
    with tarfile.open(ROOT / source['archive']) as archive:
        assert {x.name for x in archive.getmembers()} == {x['path'] for x in source['files']}
        for row in source['files']:
            assert hashlib.sha256(archive.extractfile(row['path']).read()).hexdigest() == row['sha256']
    for horizon in [5, 20]:
        runs = [ROOT / 'originals' / provenance['runs'][f'h{horizon}_{variant}'] for variant in ['base', 'flow']]
        base, flow = [json.loads((run / 'run_manifest.json').read_text())['config'] for run in runs]
        assert len(base['feature_columns']) == 161 and len(flow['feature_columns']) == 170
        assert flow['feature_columns'][:161] == base['feature_columns']
        for key in ['dataset', 'model', 'labels', 'strategy', 'backtest', 'evaluation', 'training']:
            assert base[key] == flow[key], key
        data = [dict(config['data']) for config in [base, flow]]
        for item in data:
            item.pop('price_dir')
        assert data[0] == data[1]
        alignments = [read_csv(run / 'fold_alignment.csv') for run in runs]
        for left, right in zip(*alignments):
            assert left['test_start'] == right['test_start'] and left['test_end'] == right['test_end']
            assert left['is_exact_row_match'] == right['is_exact_row_match'] == 'True'
    annual = read_csv(ROOT / 'comparison_by_year.csv')
    assert len(annual) == 32
    for row in annual:
        run = ROOT / 'originals' / provenance['runs'][f"h{row['horizon']}_{row['variant']}"]
        fold = next(x for x in read_csv(run / 'model_metrics_by_fold.csv') if int(x['fold_id']) == int(row['year']) - 2019)
        backtest = next(x for x in read_csv(run / 'backtest_metrics_by_year.csv') if x['year'] == row['year'])
        for key in ['sample_count', 'roc_auc', 'pr_auc', 'accuracy', 'balanced_accuracy', 'brier_score', 'ic_mean']:
            assert float(row[key]) == float(fold[key]), (row, key)
        for key in ['total_return', 'sharpe_ratio', 'max_drawdown', 'number_of_trades', 'final_equity']:
            assert float(row[key]) == float(backtest[key]), (row, key)
        assert math.isclose(float(row['final_equity']), 1e7 * (1 + float(row['total_return'])), abs_tol=0.01)
    for mean in read_csv(ROOT / 'comparison_mean.csv'):
        rows = [x for x in annual if x['horizon'] == mean['horizon'] and x['variant'] == mean['variant'] and (mean['period'].endswith('partial') or int(x['year']) < 2026)]
        assert len(rows) == int(mean['year_count'])
        for key in ['roc_auc', 'pr_auc', 'total_return', 'sharpe_ratio', 'max_drawdown', 'ic_mean']:
            assert math.isclose(float(mean[key]), sum(float(x[key]) for x in rows) / len(rows), abs_tol=1e-12)
    for pooled in json.loads((ROOT / 'pooled_metrics.json').read_text()):
        key = f"h{pooled['horizon']}_{pooled['variant']}"
        original = json.loads((ROOT / 'originals' / provenance['runs'][key] / 'ml_metrics_summary.json').read_text())
        assert all(pooled[k] == value for k, value in original.items())
    samples = read_csv(ROOT / 'sample_eligibility_by_stock.csv')
    assert {x['file'] for x in samples if x['variant'] == 'base'} == {x['file'] for x in samples if x['variant'] == 'flow'}
    for variant in ['base', 'flow']:
        rows = [x for x in samples if x['variant'] == variant]
        assert len(rows) == provenance['stock_file_count']
        assert sum(int(x['eligible_rows']) for x in rows) == provenance[f'full_input_{variant}_eligible_rows']
    assert sum(int(x['flow_excluded_rows']) for x in samples if x['variant'] == 'flow') == provenance['full_input_flow_excluded_rows']
    print(f"Verified {len(annual)} annual rows, 8 means, 4 pooled summaries and preserved hashes")


if __name__ == '__main__':
    verify()

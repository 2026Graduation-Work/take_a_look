"""Verify the published source bytes and compact A/B evidence using the stdlib."""
import csv
import hashlib
import json
import tarfile
from pathlib import Path


def verify(root):
    manifest = json.loads((root / 'source_manifest.json').read_text())
    payload = json.loads((root / 'suite_identity.json').read_text())
    archive = root / manifest['archive']
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest['archive_sha256']:
        raise ValueError('Source archive checksum mismatch')
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if len(members) != len(manifest['files']) or {m.name for m in members} != set(manifest['files']):
            raise ValueError('Source archive file set mismatch')
        hashes = {}
        for member in members:
            if not member.isfile():
                raise ValueError('Source archive must contain only files')
            with tar.extractfile(member) as stream:
                hashes[member.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        if hashes != manifest['files']:
            raise ValueError('Source member checksum mismatch')
    historical_root = Path(manifest['historical_chart_root'])
    for name, digest in payload['files'].items():
        if hashes.get(str(Path(name).relative_to(historical_root))) != digest:
            raise ValueError(f'Suite source/input identity mismatch: {name}')
    run_id = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
    if run_id != manifest['suite_run_id']:
        raise ValueError('Suite run ID mismatch')
    with (root / 'trade_match_validation.csv').open() as stream:
        matches = list(csv.DictReader(stream))
    if len(matches) != 14 or sum(int(r['common_trades']) for r in matches) != 609:
        raise ValueError('Common trade count mismatch')
    for row in matches:
        if any(int(v) for k, v in row.items() if k.endswith('_mismatches')):
            raise ValueError('Common trade path mismatch')
        if float(row['max_path_contribution_residual_won']) >= 1:
            raise ValueError('Common trade PnL residual exceeds one won')
    with (root / 'annual_psychology_importance.csv').open() as stream:
        importance = list(csv.DictReader(stream))
    if len(importance) != 14:
        raise ValueError('Annual importance count mismatch')
    with (root / 'trade_matches.csv').open() as stream:
        trades = list(csv.DictReader(stream))
    with (root / 'feature_importance_by_model.csv').open() as stream:
        models = list(csv.DictReader(stream))
    expected = {(str(h), str(y)) for h in (5, 20) for y in range(2019, 2026)}
    for table in (matches, importance):
        if {(r['horizon'], r['year']) for r in table} != expected:
            raise ValueError('Annual horizon/year keys mismatch')
    for row in matches:
        common = [r for r in trades if r['horizon'] == row['horizon']
                  and r['year'] == row['year'] and r['group'] == 'common']
        if len(common) != int(row['common_trades']):
            raise ValueError('Per-trade count does not match summary')
        for field in ('entry_time', 'entry_price', 'exit_time', 'exit_price', 'exit_reason', 'status'):
            if any(r[field + '_A'] != r[field + '_B'] for r in common):
                raise ValueError('Per-trade path does not match summary')
    for row in importance:
        psychology = [r for r in models if r['horizon'] == row['horizon']
                      and r['year'] == row['year'] and r['psychology'] == 'True']
        actual = sum(float(r['gain_share']) for r in psychology)
        if len(psychology) != 4 or abs(actual - float(row['psychology_gain_share'])) > 1e-12:
            raise ValueError('Per-model importance does not match summary')
    print(f'Verified {len(hashes)} snapshot files, suite {run_id}, 14 annual rows, 609 common trades')


if __name__ == '__main__':
    verify(Path(__file__).resolve().parent)

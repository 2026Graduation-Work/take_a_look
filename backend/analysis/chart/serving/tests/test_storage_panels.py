import hashlib
import io

import numpy as np
import pandas as pd
import pytest
from serving.internal.storage import PRICE_COLUMNS, SupabaseStore


def source_frame():
    return pd.DataFrame({'Date': pd.to_datetime(['2026-09-30', '2026-10-01']),
                         'Open': [100., 101.], 'High': [102., 103.], 'Low': [99., 100.],
                         'Close': [101., 102.], 'Volume': [1000., 1100.], 'Change': [1., 1.],
                         'RawOpen': [100., 101.], 'RawHigh': [102., 103.], 'RawLow': [99., 100.], 'RawClose': [101., 102.], 'RawVolume': [1000., 1100.],
                         'Amount': [101000., 112200.], 'AdjustmentFactor': [1., 1.],
                         'VWAP': [101., 102.]})

def test_market_prices_and_feature_files_are_written_in_batches(monkeypatch):
    store = SupabaseStore('https://example.test', 'secret')
    calls = []
    monkeypatch.setattr(store, '_request', lambda *a, **k: calls.append((a, k)))
    frame = source_frame()
    store.upsert_price_panel({'005930': frame, '068270': frame})
    assert len(calls) == 1
    assert {row['stock_code'] for row in calls[0][0][2]} == {'005930', '068270'}
    calls.clear()
    frames = {code: (frame, {'Date': frame.Date.iloc[-1], 'Sigma': .02, 'corr_20': np.nan}) for code in ('005930', '068270')}
    store.upload_feature_panel('2026-10-01', 'builder', {code: 'a'*64 for code in frames}, frames)
    assert len(calls) == 2  # One file, one metadata write for both stocks.
    archived = pd.read_parquet(io.BytesIO(calls[0][0][2]))
    assert archived.stock_code.tolist() == ['005930', '068270']
    assert len({row['storage_path'] for row in calls[1][0][2]}) == 1

def test_bulk_archive_uses_all_pages_and_retains_alphanumeric_stock_codes(monkeypatch):
    store = SupabaseStore('https://example.test', 'secret')
    row = {target: ('2026-10-01' if source == 'Date' else 1.) for source, target in PRICE_COLUMNS.items()}
    pages = [[dict(row, stock_code=f'{i:06d}') for i in range(1000)], [dict(row, stock_code='00104K')]]
    calls = []

    def request(method, path):
        calls.append(path)
        return pages.pop(0)

    monkeypatch.setattr(store, '_request', request)
    panel = store.load_price_panel('2026-09-30', '2026-10-01')
    assert len(panel) == 1001 and '00104K' in panel
    assert 'offset=1000' in calls[1]


def test_raw_price_panel_roundtrip_legacy_and_checksum(monkeypatch):
    store = SupabaseStore('https://example.test', 'secret')
    objects = {}
    reads = []
    def request(method, path, body=None, **kwargs):
        key = path.replace('/authenticated/', '/')
        if method == 'POST':
            objects[key] = body
        else:
            reads.append(key)
            if key not in objects:
                raise FileNotFoundError(key)
            return objects[key]
    monkeypatch.setattr(store, '_request', request)
    frame = source_frame()
    frame.attrs['input_sha256'] = 'a' * 64
    second = frame.copy()
    second.attrs['input_sha256'] = 'b' * 64
    store.save_raw_price_panel('2026-10-01', {'005930': frame, '00104K': second})
    assert len(objects) == 2
    for code, source in [('005930', frame), ('00104K', second)]:
        loaded = store.load_raw_prices(code, '2026-10-01')
        pd.testing.assert_frame_equal(loaded, source)
        assert loaded.attrs == source.attrs
    assert len(reads) == 2  # The whole panel is verified and read once per daily invocation.
    assert store.load_raw_prices('missing', '2026-10-01') is None
    store.save_raw_prices('005930', '2026-09-30', frame)
    pd.testing.assert_frame_equal(store.load_raw_prices('005930', '2026-09-30'), frame)
    store.load_raw_prices('005930', '2026-09-30')
    assert sum(key.endswith('2026-09-30/batch.parquet') for key in reads) == 1
    store._raw_price_frames.clear()
    objects['/storage/v1/object/chart-features/raw-prices-v3/2026-10-01/batch.parquet'] += b'corrupt'
    with pytest.raises(ValueError, match='checksum'):
        store.load_raw_prices('005930', '2026-10-01')


def test_feature_panel_load_returns_only_requested_stock(monkeypatch):
    store = SupabaseStore('https://example.test', 'secret')
    panel = pd.DataFrame({'stock_code': ['005930', '00088K'],
                          'Date': pd.to_datetime(['2026-10-01'] * 2), 'Sigma': [.02, .03]})
    data = io.BytesIO()
    panel.to_parquet(data, index=False)
    payload = data.getvalue()
    metadata = [{'storage_path': 'builder/batch.parquet',
                 'feature_sha256': hashlib.sha256(payload).hexdigest()}]
    downloads = []
    def request(method, path):
        if path.startswith('/rest/'):
            return metadata
        downloads.append(path)
        return payload
    monkeypatch.setattr(store, '_request', request)
    result = store.load_features('00088K', '2026-10-01', 'builder', 'a' * 64)
    assert len(result) == 1 and result.iloc[0].Sigma == .03
    other = store.load_features('005930', '2026-10-01', 'builder', 'b' * 64)
    assert len(other) == 1 and other.iloc[0].Sigma == .02
    assert len(downloads) == 1
    with pytest.raises(ValueError, match='Stored feature stock/date mismatch'):
        store.load_features('123456', '2026-10-01', 'builder', 'a' * 64)
    with pytest.raises(ValueError, match='Stored feature stock/date mismatch'):
        store.load_features('00088K', '2026-10-02', 'builder', 'a' * 64)


def test_universe_load_fetches_all_pages(monkeypatch):
    store = SupabaseStore('https://example.test', 'secret')
    pages = [[{'stock_code': f'{i:06d}', 'stock_name': 'stock'} for i in range(1000)],
             [{'stock_code': '00088K', 'stock_name': 'preferred'}]]
    paths = []
    def request(method, path):
        paths.append(path)
        return pages.pop(0)
    monkeypatch.setattr(store, '_request', request)
    result = store.load_universe('2026-10-01')
    assert len(result) == 1001 and result.iloc[-1].Code == '00088K'
    assert 'offset=1000' in paths[1]

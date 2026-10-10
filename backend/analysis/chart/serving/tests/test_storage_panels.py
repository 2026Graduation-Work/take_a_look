import io

import numpy as np
import pandas as pd
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

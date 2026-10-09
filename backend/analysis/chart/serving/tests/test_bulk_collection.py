import io

import numpy as np
import pandas as pd
import pytest
from serving.internal import prices
from serving.internal.storage import PRICE_COLUMNS, SupabaseStore


def source_frame():
    return pd.DataFrame({'Date': pd.to_datetime(['2026-09-30', '2026-10-01']),
                         'Open': [100., 101.], 'High': [102., 103.], 'Low': [99., 100.],
                         'Close': [101., 102.], 'Volume': [1000., 1100.], 'Change': [1., 1.],
                         'RawOpen': [100., 101.], 'RawHigh': [102., 103.], 'RawLow': [99., 100.], 'RawClose': [101., 102.], 'RawVolume': [1000., 1100.],
                         'Amount': [101000., 112200.], 'AdjustmentFactor': [1., 1.],
                         'VWAP': [101., 102.]})


def test_incremental_prices_reuse_raw_history_and_apply_historical_adjustments(monkeypatch):
    from pykrx import stock

    stored = source_frame().iloc[:1].copy()
    adjusted = source_frame().set_index('Date').drop(columns=['RawOpen', 'RawHigh', 'RawLow', 'RawClose', 'RawVolume', 'Amount', 'AdjustmentFactor', 'VWAP'])
    adjusted.loc[adjusted.index[0], ['Open', 'High', 'Low', 'Close']] /= 2
    monkeypatch.setattr(prices, 'fetch_adjusted_prices', lambda *_: adjusted)
    monkeypatch.setattr(stock, 'get_market_ohlcv_by_date', lambda *_a, **_k: pytest.fail('raw history requested'))
    daily = {'2026-10-01': pd.DataFrame({'시가': [101], '고가': [103], '저가': [100], '종가': [102], '거래량': [1100], '거래대금': [112200]}, index=['005930'])}
    result = prices.fetch_incremental_prices('005930', '2026-09-30', '2026-10-01', stored, daily)
    assert result.VWAP.tolist() == [50.5, 102]
    assert result.RawClose.tolist() == [101, 102]
    updates = prices.changed_price_rows(result, stored)
    assert len(updates) == 2  # Corrected past row plus today's new row.
    assert prices.changed_price_rows(result, result.copy()).empty


def test_missing_archive_backfills_raw_only_once(monkeypatch):
    from pykrx import stock

    adjusted = source_frame().set_index('Date')[['Open', 'High', 'Low', 'Close', 'Volume', 'Change']]
    monkeypatch.setattr(prices, 'fetch_adjusted_prices', lambda *_: adjusted)
    calls = []

    def backfill(*args, **kwargs):
        calls.append(kwargs)
        return pd.DataFrame({'시가': [100, 101], '고가': [102, 103], '저가': [99, 100], '종가': [101, 102], '거래량': [1000, 1100], '거래대금': [101000, 112200]}, index=adjusted.index)

    monkeypatch.setattr(stock, 'get_market_ohlcv_by_date', backfill)
    result = prices.fetch_incremental_prices('005930', '2026-09-30', '2026-10-01', pd.DataFrame(), {})
    assert result.VWAP.tolist() == [101, 102]
    assert calls == [{'adjusted': False}]


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


def test_db_decimal_roundtrip_does_not_rewrite_history_but_real_changes_do():
    fresh = source_frame()
    fresh['Change'] = 1.234567890123456
    fresh['AdjustmentFactor'] = 1.0037243947858474
    fresh['VWAP'] = 271453.1620996132
    stored = fresh.copy()
    for column in ('Change', 'AdjustmentFactor', 'VWAP'):
        stored[column] = stored[column].map(lambda value: float(format(value, '.15g')))
    assert prices.changed_price_rows(fresh, stored).empty
    for column, delta in [('Close', 1), ('Volume', 1), ('Amount', 1), ('VWAP', .01)]:
        corrected = fresh.copy()
        corrected.loc[0, column] += delta
        assert len(prices.changed_price_rows(corrected, stored)) == 1

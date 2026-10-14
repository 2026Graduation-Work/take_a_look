import numpy as np
import pandas as pd
import pytest
from serving.internal import pipeline
from serving.internal.features import build_feature_frame


def price_rows(dates):
    values = np.arange(len(dates)) + 100.
    return pd.DataFrame({'Date': dates, 'Open': values, 'High': values + 1, 'Low': values - 1,
                         'Close': values, 'Volume': 10., 'VWAP': values, 'RawClose': values,
                         'RawVolume': 10., 'Amount': values * 10, 'AdjustmentFactor': 1.})


@pytest.mark.parametrize('mode', ['daily', 'volume_revision', 'amount_revision', 'split', 'gap', 'empty', 'already_current'])
def test_recent_db_cache_is_incremental_and_never_fetches_training_history(monkeypatch, mode):
    dates = pd.bdate_range('2024-01-02', periods=80)
    full = price_rows(dates)
    cached = full.iloc[:-1].copy()
    if mode == 'gap':
        cached = cached.drop(index=30)
    if mode == 'empty':
        cached = pd.DataFrame()
    if mode == 'already_current':
        cached = full.copy()
    fresh = full.copy()
    fresh['PriceProvider'] = 'test-provider'
    fresh['RawOpen'] = fresh.Open
    if mode in ('volume_revision', 'amount_revision'):
        fresh.loc[len(fresh)-2, 'RawVolume' if mode == 'volume_revision' else 'Amount'] += 1
    if mode == 'split':
        for col in ['Open', 'High', 'Low', 'Close', 'VWAP', 'AdjustmentFactor']:
            fresh.loc[fresh.index < len(fresh)-1, col] *= .5
    starts, writes = [], []
    class Store:
        def load_prices(self, code, start, end):
            assert (start, end) == (str(dates[0].date()), str(dates[-1].date()))
            return cached
        def upsert_prices(self, code, frame):
            writes.append(frame)
    def fetch(code, start, end):
        starts.append(start)
        return fresh.loc[fresh.Date.between(pd.Timestamp(start), pd.Timestamp(end))].copy()
    monkeypatch.setattr(pipeline, '_retry_fetch', fetch)
    raw = pipeline.recent_prices('005930', str(dates[0].date()), str(dates[-1].date()), set(dates.date), Store())
    expected_start = dates[0] if mode == 'empty' else dates[29] if mode == 'gap' else dates[-1] if mode == 'already_current' else dates[-2]
    assert starts == [str(expected_start.date())] + ([str(dates[0].date())] if mode == 'split' else [])
    assert len(raw) == 80 and len(writes) == 1
    assert len(writes[0]) == (80 if mode in ('empty', 'split') else 51 if mode == 'gap' else 1 if mode == 'already_current' else 2)
    assert raw.Date.min() == dates[0]
    if mode == 'split':
        assert raw.Close.iloc[0] == fresh.Close.iloc[0]
    if mode in ('daily', 'empty', 'already_current'):
        actual_features = build_feature_frame(raw, set(dates.date)).iloc[-1]
        reference_features = build_feature_frame(full, set(dates.date)).iloc[-1]
        pd.testing.assert_series_equal(actual_features[reference_features.index], reference_features)


def test_long_history_is_not_required_for_current_features():
    dates = pd.bdate_range('2023-01-02', periods=400)
    full = price_rows(dates)
    recent = full.loc[full.Date >= dates[-1] - pd.Timedelta(240, unit='D')].reset_index(drop=True)
    from shared.features.columns import BASE_FEATURES
    a = build_feature_frame(full, set(dates.date)).iloc[-1][list(BASE_FEATURES)].astype(float)
    b = build_feature_frame(recent, set(dates.date)).iloc[-1][list(BASE_FEATURES)].astype(float)
    np.testing.assert_allclose(a, b, rtol=1e-8, atol=1e-10, equal_nan=True)

from datetime import date
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest
from experiments.dataset.pipeline import build_segment_features
from experiments.export_oos import outcomes
from experiments.features.panel_builder import (
    LoadedFeatureSource,
    _parse_source_spec,
    assemble_feature_panel,
)
from experiments.features.psychology.market_psychology import (
    FEATURE_COLUMNS,
    PsychologyFeatureConfig,
    build_psychology_features,
)
from experiments.train_src.loaders import load_parquet_data
from shared.data.calendar import scheduled_sessions
from shared.data.market_notices import SecurityKey
from shared.data.market_resolutions import Resolution
from shared.data.resolution_snapshot import (
    PRICE_POLICY,
    VerifiedSourceDays,
    read_resolution_snapshot,
)
from shared.data.segmented_prices import adjust_training_window
from shared.io import atomic_json
from shared.settings import PREPROCESSING
from shared.tests.official_fixtures import fixture_snapshot


def price_rows(sessions, first=100):
    values = (first + 10 * np.sin(np.arange(len(sessions)) / 3)).astype(int)
    return pd.DataFrame({"Date": sessions, "RawClose": values, "RawOpen": values,
                         "RawHigh": values + 1, "RawLow": values - 1, "RawVolume": 100,
                         "RawChange": pd.Series(values).diff().fillna(0).astype(int),
                         "ListedShares": 10_000, "Amount": 100 * values})


@pytest.fixture
def sessions():
    return scheduled_sessions(pd.Timestamp("2024-01-02"), pd.Timestamp("2024-12-31"))[:150]


def test_pinned_price_window_keeps_adjustment_factors_inside_the_segment(tmp_path, sessions):
    def day(at):
        return sessions[at].date().isoformat()

    raw = price_rows(sessions)
    break_row = (day(75), Resolution.SEGMENT_BREAK, None, None)
    front = (day(20), Resolution.BONUS, Fraction(1, 2), Fraction(2))
    def adjusted(root, ratio):
        after = (day(100), Resolution.UNIT_CHANGE, 1 / ratio, ratio)
        path = fixture_snapshot(root, ["005930"], sessions, raw=raw, events=[front, break_row, after])
        snapshot = read_resolution_snapshot(path, verify_archive=True)
        security, = snapshot.windows
        return path, snapshot, security, adjust_training_window(security, raw, sessions, day(-1), snapshot)
    path, snapshot, key, (first, event_table) = adjusted(tmp_path / "one", Fraction(2))
    _, _, _, (second, _) = adjusted(tmp_path / "two", Fraction(3))
    pd.testing.assert_frame_equal(first.iloc[:75], second.iloc[:75])
    assert first.iloc[0].Close == raw.iloc[0].RawClose / 2
    assert first.iloc[0].VWAP == raw.iloc[0].RawClose / 2
    assert first.iloc[0].Volume == raw.iloc[0].RawVolume * 2
    assert first.iloc[75].Volume != second.iloc[75].Volume
    assert first.groupby("SegmentId", sort=False).size().tolist() == [75, 75]
    assert first.groupby("SegmentId", sort=False).head(1).Change.isna().all()
    assert event_table.PriceFactor.tolist() == [.5, .5]
    pd.testing.assert_frame_equal(first[raw.columns], raw)
    with pytest.raises(ValueError, match="partial window requires verified KRX source days"):
        adjust_training_window(key, raw.iloc[1:], sessions[1:], day(-1), snapshot)
    changed = raw.copy()
    changed.loc[0, "Amount"] += 1
    with pytest.raises(ValueError, match="prices differ"):
        adjust_training_window(key, changed, sessions, day(-1), snapshot)
    field = path.with_suffix("") / "notices.csv"
    field.write_bytes(field.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="snapshot file hash differs"):
        read_resolution_snapshot(path)


def test_subset_reuses_verified_daily_prices_and_preserves_segment(tmp_path, sessions):
    sessions = sessions[:8]
    raw = price_rows(sessions)
    source_days = tmp_path / "all"
    source_days.mkdir()
    daily = raw.assign(Code="005930", MKT_NM="KOSPI", ISU_ABBRV="Synthetic", SECT_TP_NM="")
    for row in daily.itertuples():
        daily.loc[daily.Date.eq(row.Date)].to_parquet(source_days / f"{row.Date:%Y-%m-%d}.parquet", index=False)
    events = [
        (str(sessions[1].date()), Resolution.SEGMENT_BREAK, None, None),
        (str(sessions[6].date()), Resolution.BONUS, Fraction(1, 2), Fraction(2)),
    ]
    path = fixture_snapshot(tmp_path / "wide", ["005930"], sessions, raw=raw, events=events, source_days=source_days)
    snapshot = read_resolution_snapshot(path, verify_archive=True)
    security, = snapshot.windows
    full, _ = adjust_training_window(security, raw, sessions, sessions[-1], snapshot)
    selected = sessions[2:5]
    pinned_days = tmp_path / "pinned"
    VerifiedSourceDays.read(snapshot, selected, source_days, destination=pinned_days)
    proof = VerifiedSourceDays.read(snapshot, selected, pinned_days)
    prices, applied = adjust_training_window(security, raw.iloc[2:5], selected, selected[-1], snapshot, source=proof)
    assert prices.SegmentId.tolist() == full.SegmentId.iloc[2:5].tolist()
    assert prices.AdjustmentFactor.tolist() == [1., 1., 1.]
    assert pd.isna(prices.Change.iloc[0])
    assert applied.empty
    changed = raw.iloc[2:5].assign(ListedShares=20_000)
    with pytest.raises(ValueError, match="prices differ"):
        adjust_training_window(security, changed, selected, selected[-1], snapshot, source=proof)
    file = pinned_days / f"{selected[0]:%Y-%m-%d}.parquet"
    file.write_bytes(file.read_bytes() + b"x")
    with pytest.raises(ValueError, match="source day bytes differ"):
        VerifiedSourceDays.read(snapshot, selected, pinned_days)
    with pytest.raises(ValueError, match="complete sessions"):
        snapshot.select_sessions(sessions[[2, 4]])


@pytest.mark.parametrize("kind", ["fixed", "dynamic_sigma"])
def test_projected_labels_and_oos_do_not_cross_same_code_same_isin_relisting(tmp_path, sessions, kind):
    def day(at):
        return sessions[at].date().isoformat()

    older = SecurityKey("005930", "KR7005930003", day(0), day(55), "KOSPI", "common")
    later = SecurityKey(older.code, older.isin, day(65), None, "KOSPI", "common")
    raw = pd.concat([price_rows(sessions[:55]), price_rows(sessions[65:], first=450)], ignore_index=True)
    path = fixture_snapshot(tmp_path / "source", [older.code], sessions, raw=raw, keys=[older, later])
    snapshot = read_resolution_snapshot(path)
    parts = [adjust_training_window(key, raw.loc[raw.Date.isin(snapshot.days(key))], snapshot.days(key), day(-1), snapshot)[0]
             for key in snapshot.windows]
    prices = pd.concat(parts, ignore_index=True).assign(Code=older.code, Sigma=.015, SampleEligible=True)
    assert prices.groupby("SegmentId", sort=False).size().tolist() == [55, 85]
    assert prices.iloc[0].SegmentId != prices.iloc[-1].SegmentId
    prices.loc[prices.Date.ge(later.listing) & prices.Date.lt(day(70)), "SampleEligible"] = False
    store = tmp_path / "features"
    store.mkdir()
    table = store / f"{older.code}.parquet"
    prices.to_parquet(table, index=False)
    atomic_json(store / "feature_manifest.json", {"price_policy": PRICE_POLICY, "file_hashes": {table.name: "fixture"}})
    rules = {"type": kind, "horizon": 20, "up_mult": 1.75, "down_mult": 1.5, "tp": 3.5, "sl": 2.}
    loaded = load_parquet_data(store, columns_only=["Date", "Code"], label_params=rules, sample_only=True)
    assert "SegmentId" in loaded
    assert loaded.Date.between(day(35), day(54)).sum() == 0
    assert loaded.Date.between(day(65), day(69)).sum() == 0
    if kind == "dynamic_sigma":
        result = outcomes(prices, rules)
        unsegmented = outcomes(prices.drop(columns="SegmentId"), rules)
        assert (unsegmented.Date.lt(older.delisting) & unsegmented.return_date.ge(later.listing)).sum() == 20
        assert not (result.Date.lt(older.delisting) & result.return_date.ge(later.listing)).any()
        assert set(loaded.Date) == set(result.loc[result.Y_Label.notna(), "Date"])
    prices.drop(columns="SegmentId").to_parquet(table, index=False)
    with pytest.raises(ValueError, match="SegmentId is missing"):
        load_parquet_data(store, strict=False, columns_only=["Date", "Code"], label_params=rules)


def test_pinned_spac_premerger_and_open_listing_keep_original_price_bars(tmp_path, sessions):
    raw = price_rows(sessions)
    merger = sessions[70].date().isoformat()
    for key, events in {"merged": [(merger, Resolution.SPAC_PREMERGER, None, None)], "open": []}.items():
        path = fixture_snapshot(tmp_path / key, ["005930"], sessions, raw=raw, events=events,
                                spac_codes=["005930"])
        snapshot = read_resolution_snapshot(path)
        security, = snapshot.windows
        prices, applied = adjust_training_window(security, raw, sessions, sessions[-1], snapshot)
        eligibility = ~prices.SegmentId.isin(snapshot.excluded_segment_ids(security))
        pd.testing.assert_frame_equal(prices[raw.columns], raw)
        assert applied.empty
        if events:
            assert prices.loc[eligibility, "Date"].min() == pd.Timestamp(merger)
            assert eligibility.sum() == 80
        else:
            assert not eligibility.any()
            assert len(prices) == 150
        assert list(snapshot.review_rows()) == []


def test_explicit_tickers_allow_pinned_spac_exclusions_in_a_mixed_request(tmp_path, sessions):
    file = tmp_path / "005930.parquet"
    pd.DataFrame({"Date": sessions, "Code": "005930", "SegmentId": "first", "SampleEligible": True}).to_parquet(file)
    atomic_json(tmp_path / "feature_manifest.json", {"price_policy": PRICE_POLICY,
                "file_hashes": {file.name: "fixture"}, "spac_policy_excluded_files": ["000001.parquet"]})
    loaded = load_parquet_data(tmp_path, tickers=["000001", "005930"], columns_only=["Date"])
    assert set(loaded.Code) == {"005930"}
    with pytest.raises(ValueError, match="SPAC policy exclusion"):
        load_parquet_data(tmp_path, tickers=["000001"])
    with pytest.raises(FileNotFoundError, match="999999"):
        load_parquet_data(tmp_path, tickers=["000001", "005930", "999999"])


def test_flow_psychology_windows_and_availability_restart_at_the_boundary(tmp_path, sessions):
    raw = price_rows(sessions)
    bars = raw.rename(columns={f"Raw{col}": col for col in ("Open", "High", "Low", "Close", "Volume")})
    bars = bars.assign(Code="005930", VWAP=bars.Close, RawVolume=100)
    bars["SegmentId"] = np.where(bars.Date < sessions[75], "before", "after")
    for investor in ("Individual", "Foreign", "Institution"):
        bars[f"{investor}_BuyAmount"] = np.arange(len(bars)) + 10
        bars[f"{investor}_SellAmount"] = 2
    changed = bars.copy()
    changed.loc[:74, ["Open", "High", "Low", "Close", "VWAP", "Individual_BuyAmount"]] *= 5
    one = build_segment_features(bars, sessions, PREPROCESSING)
    two = build_segment_features(changed, sessions, PREPROCESSING)
    pd.testing.assert_frame_equal(one.iloc[75:], two.iloc[75:])
    assert one.roc_60.iloc[75:135].isna().all() and pd.notna(one.roc_60.iloc[135])
    assert one.flow_individual_5.iloc[75:79].isna().all() and pd.notna(one.flow_individual_5.iloc[79])
    assert one.flow_individual_20.iloc[75:94].isna().all() and pd.notna(one.flow_individual_20.iloc[94])
    config = PsychologyFeatureConfig()
    psychology, _ = build_psychology_features(bars, config)
    altered, _ = build_psychology_features(changed, config)
    pd.testing.assert_frame_equal(psychology[psychology.SegmentId.eq("after")],
                                  altered[altered.SegmentId.eq("after")])
    assert psychology.loc[psychology.SegmentId.eq("before"), "AvailableDate"].max() == sessions[74]
    spec = _parse_source_spec({"name": "psychology", "path": str(tmp_path / "psych.parquet"),
                               "columns": list(FEATURE_COLUMNS), "apply_period": "one_day",
                               "missing": {"policy": "forward_fill", "max_staleness_trading_days": 0}})
    panel, _ = assemble_feature_panel(one, [LoadedFeatureSource(spec, psychology, {})])
    assert panel.loc[panel.Date.eq(sessions[75]), list(FEATURE_COLUMNS)].isna().all(axis=None)
    assert panel.loc[panel.SegmentId.eq("after"), list(FEATURE_COLUMNS)].notna().any(axis=None)


def test_manual_review_resolves_only_with_same_official_section_and_fraction(tmp_path):
    from experiments.dataset.census_actions import (
        _collect_notices,
        _write_csv,
        read_review_confirmations,
        verify_review_confirmations,
    )
    from shared.data.kind_market import KindBody, MarketFiling
    from shared.data.market_notices import normal_company
    from shared.data.market_resolutions import resolve_events
    from shared.data.resolution_snapshot import CONFIRMATION_COLUMNS, kind_document_url
    from shared.tests.test_market_resolutions import SAMSUNG, SOURCES, actual_notices, bars

    raw = bars(SAMSUNG, [
        ("2018-03-06", 8280, 8610, 7960, 8510, 270, 13_313_159, 111_274_387_450, 390_000_000),
        ("2018-03-07", 7750, 8180, 7500, 7620, 110, 14_231_075, 111_008_964_920, 390_000_000),
    ])
    sessions = pd.DatetimeIndex(raw.Date)
    previous = resolve_events(SAMSUNG, raw, sessions, [], coverage_complete=True)
    assert previous.resolutions[0].review
    accession = "20180306000596"
    notice, = actual_notices(SAMSUNG, accession)
    key = SAMSUNG, "2018-03-07"
    file = tmp_path / "review.csv"
    register = dict(zip(CONFIRMATION_COLUMNS, [*vars(SAMSUNG).values(), key[1], kind_document_url(accession),
                                              notice.form, notice.facts.section, "7510/8510"]))
    _write_csv(file, CONFIRMATION_COLUMNS, [register])
    confirmation = read_review_confirmations(file)

    class KnownDocument:
        def document(self, filing):
            import gzip

            from shared.tests.test_market_resolutions import FIXTURES

            info = SOURCES[filing.accession]
            body = gzip.decompress((FIXTURES / f"{filing.accession}.html.gz").read_bytes())
            source = notice.evidence[-1]
            return notice.form, KindBody(body, info["charset"], source, info["document_no"],
                                         tuple(info["family"]), info["final"]), (source,)

    info = SOURCES[accession]
    filing = MarketFiling(accession, date(2018, 3, 6), info["title"], notice.evidence[0],
                          company=info["company"], submitter="한국거래소")
    parsed, *_ = _collect_notices(KnownDocument(), [filing], {SAMSUNG: {normal_company(info["company"])}},
                                  {SAMSUNG: []}, anchors={}, spac_keys=set(), bounded=True,
                                  registered={accession})
    latest = resolve_events(SAMSUNG, raw, sessions, parsed[SAMSUNG], coverage_complete=True)
    assert latest.resolutions[0].kind == Resolution.RIGHTS
    observed = {(row.security, row.date): row for row in latest.candidates}
    assert verify_review_confirmations(confirmation, parsed, latest.resolutions, observed)
    before = fixture_snapshot(tmp_path / "before", [SAMSUNG.code], sessions, raw=raw, keys=[SAMSUNG])
    row, = latest.resolutions
    after = fixture_snapshot(tmp_path / "after", [SAMSUNG.code], sessions, raw=raw, keys=[SAMSUNG],
                             events=[(row.date, row.kind, row.price_factor, row.volume_factor)])
    assert before.stem != after.stem
    assert len(list(read_resolution_snapshot(before).review_rows())) == 1
    assert list(read_resolution_snapshot(after).review_rows()) == []
    confirmation[key][1]["Ratio"] = "2"
    with pytest.raises(ValueError, match="confirmed ratio differs"):
        verify_review_confirmations(confirmation, parsed, latest.resolutions, observed)

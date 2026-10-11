from datetime import date

import pytest
from serving import model_check
from shared.features.columns import BASE_FEATURES, FLOW_FEATURES


def setup_check(monkeypatch, *, missing_flow=False, unavailable=False):
    names = list(BASE_FEATURES) + ([] if missing_flow else list(FLOW_FEATURES))
    pack = {"pack_id": "flow", "horizons": {f"h{h}": {"feature_names": names} for h in (5, 20)}}
    monkeypatch.setattr(model_check, "active_pack", lambda: (pack, {}))
    monkeypatch.setattr(model_check, "official_day", lambda: "2026-10-11")
    monkeypatch.setattr(model_check, "refresh_krx_trading_days", lambda *_: {date(2026, 10, 8), date(2026, 10, 9)})

    def collect(as_of, store, **kwargs):
        assert as_of == "2026-10-09"
        assert kwargs == {"code": "005930", "historical_test": True}
        assert not hasattr(store, "http")
        assert not hasattr(store, "save_raw_prices")
        assert store.load_flow_day(as_of) is None
        return (), (), {}, {}, {}

    monkeypatch.setattr(model_check, "collect", collect)
    snapshots = [{"horizon": h, "inference": {"status": "unavailable" if unavailable else "available",
                                             "reason": "flow_window_incomplete" if unavailable else None}}
                 for h in (5, 20)]
    monkeypatch.setattr(model_check, "build_batch", lambda *_: ({"id": "checked"}, snapshots))
    monkeypatch.setattr(model_check, "write_batch", lambda *_: None)


def test_live_check_uses_last_confirmed_session_without_database(monkeypatch, capsys):
    setup_check(monkeypatch)
    model_check.main()
    output = capsys.readouterr().out
    assert '"features_per_model": 170' in output
    assert '"published": false' in output


def test_base_models_are_rejected(monkeypatch):
    setup_check(monkeypatch, missing_flow=True)
    with pytest.raises(ValueError, match="expected flow model"):
        model_check.main()


def test_incomplete_flow_does_not_count_as_success(monkeypatch):
    setup_check(monkeypatch, unavailable=True)
    with pytest.raises(ValueError, match="flow_window_incomplete"):
        model_check.main()

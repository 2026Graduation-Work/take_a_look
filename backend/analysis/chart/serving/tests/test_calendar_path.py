from pathlib import Path

from serving.internal import calendar


def test_calendar_uses_serving_data_without_environment_override(monkeypatch, tmp_path):
    monkeypatch.delenv("CHART_SERVING_DATA_DIR", raising=False)
    assert calendar._calendar_path() == Path(calendar.__file__).parent.parent / "data" / "krx_trading_calendar.json"

    monkeypatch.setenv("CHART_SERVING_DATA_DIR", str(tmp_path))
    assert calendar._calendar_path() == tmp_path / "krx_trading_calendar.json"

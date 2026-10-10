"""Chart tests always replace lazy providers before a library login can occur."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
collect_ignore = ["archive", "workspace"]

@pytest.fixture(autouse=True)
def offline_providers(monkeypatch):
    import requests
    from shared.data import providers
    class MockKrx:
        def __getattr__(self, name):
            def absent(*args, **kwargs):
                raise AssertionError(f"Unmocked KRX provider call: {name}")
            return absent
    monkeypatch.setattr(providers, "krx", MockKrx())
    monkeypatch.setattr(providers, "get_krx_session", lambda: SimpleNamespace(session=requests.Session()))
    def no_network(*args, **kwargs):
        raise AssertionError("Tests must mock HTTP before provider login")
    monkeypatch.setattr(requests.sessions.Session, "request", no_network)

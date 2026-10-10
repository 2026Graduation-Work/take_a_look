import io
from urllib.error import HTTPError

import pytest
import requests
from serving.internal import storage
from serving.internal.progress import stage
from shared.data import krx


@pytest.mark.parametrize('path,kwargs,retry', [
    ('/storage/v1/object/chart-features/a.parquet', {'extra_headers': {'x-upsert': 'true'}}, True),
    ('/rest/v1/chart_prices', {'prefer': 'resolution=merge-duplicates'}, True),
    ('/rest/v1/rpc/publish_chart_batch', {}, False),
])
def test_storage_520_retries_only_idempotent_writes(monkeypatch, path, kwargs, retry):
    calls = []
    response = io.BytesIO(b'[]')
    response.headers = {'Content-Type': 'application/json'}

    def request(*args, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise HTTPError('https://example.test', 520, 'error', {}, io.BytesIO())
        return response

    monkeypatch.setattr(storage, 'urlopen', request)
    monkeypatch.setattr(storage.time, 'sleep', lambda _: None)
    store = storage.SupabaseStore('https://example.test', 'secret')
    if retry:
        assert store._request('POST', path, [], **kwargs) == []
        assert len(calls) == 2
    else:
        with pytest.raises(RuntimeError, match='HTTP 520'):
            store._request('POST', path, [], **kwargs)
        assert len(calls) == 1


def test_storage_401_is_not_retried(monkeypatch):
    calls = []

    def request(*args, **kw):
        calls.append(1)
        raise HTTPError('https://example.test', 401, 'error', {}, io.BytesIO())

    monkeypatch.setattr(storage, 'urlopen', request)
    with pytest.raises(RuntimeError, match='HTTP 401'):
        storage.SupabaseStore('https://example.test', 'secret')._request('GET', '/rest/v1/chart_prices')
    assert len(calls) == 1


def test_krx_timeout_and_non_json_login_retry(monkeypatch):
    calls = []

    def request(self, method, url, **kwargs):
        calls.append(kwargs['timeout'])
        response = requests.Response()
        response.status_code = 200
        response._content = b'<html>maintenance</html>' if len(calls) == 1 else b'{}'
        response._content_consumed = True
        return response

    monkeypatch.setattr(requests.Session, 'request', request)
    monkeypatch.setattr(krx.time, 'sleep', lambda _: None)
    krx.install_request_timeout()
    wrapped = requests.Session.request
    krx.install_request_timeout()
    assert requests.Session.request is wrapped
    session = requests.Session()
    assert session.post('https://data.krx.co.kr/comm/MDCCOMS001D1.cmd').json() == {}
    session.get('https://example.test', timeout=15)
    assert calls == [(10, 30), (10, 30), 15]


def test_stage_failure_is_reported_and_preserves_exception(capsys):
    with pytest.raises(ValueError, match='bad input'):
        with stage('build_features', stock_code='005930'):
            raise ValueError('bad input')
    output = capsys.readouterr().out
    assert 'stage_failed' in output and 'ValueError' in output and '005930' in output
    assert 'bad input' not in output

"""Check KRX access without printing credentials or writing to the database."""

import contextlib
import io
import os
import time
from functools import wraps
from urllib.parse import urlparse

import requests


def install_request_timeout():
    """pykrx omits data-request timeouts; cover refreshed sessions as well."""
    original = requests.Session.request
    if getattr(original, "_chart_serving_timeout", False):
        return

    @wraps(original)
    def bounded(self, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = (10, 30)
        is_krx = urlparse(url).hostname == "data.krx.co.kr"
        for attempt in range(3):
            response = original(self, method, url, **kwargs)
            if not is_krx:
                return response
            transient = response.status_code in {408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
            # KRX sometimes returns HTML/empty maintenance responses to login.
            if urlparse(url).path.endswith("MDCCOMS001D1.cmd") and response.status_code == 200:
                try:
                    response.json()
                except requests.exceptions.JSONDecodeError:
                    transient = True
            if not transient:
                response.raise_for_status()
                return response
            status = response.status_code
            response.close()
            if attempt == 2:
                raise RuntimeError(f"KRX returned an unavailable response (HTTP {status}); retry later")
            time.sleep(2 * (attempt + 1))

    bounded._chart_serving_timeout = True
    requests.Session.request = bounded


def authenticated_stock():
    if not os.environ.get("KRX_ID") or not os.environ.get("KRX_PW"):
        raise ValueError("KRX_ID and KRX_PW are required")
    install_request_timeout()
    # pykrx prints the login ID at import time. Keep credentials out of logs.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from pykrx import stock
        from pykrx.website.comm.auth import get_auth_session

        session = get_auth_session()
    if session is None or not session.is_valid():
        raise RuntimeError("KRX authentication failed; verify the data.krx.co.kr account and KRX_ID/KRX_PW secrets")
    return stock


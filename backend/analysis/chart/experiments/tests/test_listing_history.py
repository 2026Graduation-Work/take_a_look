import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from experiments.dataset.census_actions import _security_master
from shared.data import providers
from shared.data.kind_market import KindMarket
from shared.data.listing_history import prepare_listing_masters
from shared.data.training_prices import KRX_FIELDS

ISIN = "KR7005930003"
FORMER = "KR7000660001"
ALTERNATIVE = "KR7001230002"


def _price_day(day, prices):
    return pd.DataFrame([
        {"Date": day, "Code": code, "MKT_NM": market, "ISU_ABBRV": name, "SECT_TP_NM": "",
         "RawOpen": price, "RawHigh": price + 1, "RawLow": price - 1, "RawClose": price,
         "RawChange": 0, "RawVolume": 10, "Amount": 10 * price, "ListedShares": 40}
        for code, market, name, price in prices
    ])


def _stock(source, code, *, market, name, start, end=None):
    common = {"ISU_NM": name, "LIST_DD": start, "SECUGRP_NM": "주권", "KIND_STKCERT_TP_NM": "보통주"}
    if end is None:
        return {**common, "ISU_SRT_CD": code, "ISU_CD": source, "ISU_ABBRV": name, "MKT_TP_NM": market}
    return {**common, "ISU_CD": code, "DELIST_DD": end, "MKT_NM": market}


class _Response:
    def __init__(self, content, encoding="utf-8"):
        self.content = content
        self.status_code = 200
        self.headers = {"Content-Type": "text/html; charset=" + encoding}

    def raise_for_status(self):
        pass

    def iter_content(self, _):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class _KRX:
    def __init__(self, days, *, rejected=None):
        self.days = days
        self.calls = []
        self.rejected = rejected

    def post(self, url, *, data, timeout):
        assert url == "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
        assert timeout == (10, 30)
        endpoint = data["bld"].split("/")[-1]
        self.calls.append((endpoint, data))
        if endpoint == "MDCSTAT01901":
            assert data["mktId"] == "ALL"
            value = {"OutBlock_1": [_stock(ISIN, "005930", market="KOSPI", name="새 시장", start="2024/01/04")]}
        elif endpoint == "MDCSTAT23801":
            assert data["mktId"] == "ALL"
            historical = _stock(None, "000660", market="KOSPI", name="과거 종목", start="2021/01/04", end="2024/01/04")
            value = {"output": [historical] if data["strtDd"] <= "20240104" <= data["endDd"] else []}
        elif endpoint == "finder_listdelisu":
            assert data == {"bld": "dbms/comm/finder/finder_listdelisu", "mktsel": "ALL", "searchText": "", "typeNo": "0"}
            value = {"block1": [
                {"short_code": "000660", "full_code": FORMER, "codeName": "과거 종목", "marketCode": "STK"},
                {"short_code": "000660", "full_code": ALTERNATIVE, "codeName": "같은 단축코드", "marketCode": "STK"},
            ]}
        elif endpoint == "MDCSTAT20001":
            assert data["listClssCd"] == "ALL"
            value = {"output": []}
        elif endpoint == "MDCSTAT01701":
            assert data["adjStkPrc"] == "1" and data["strtDd"] == data["endDd"]
            code = {"KR7005930003": "005930"}.get(data["isuCd"], "000660")
            day = pd.Timestamp(data["strtDd"]).strftime("%Y-%m-%d")
            bars = self.days[day]
            bar, = bars.loc[bars.Code.eq(code)].itertuples(index=False)
            wire = {column: str(getattr(bar, field)) for column, field in KRX_FIELDS.items()}
            if data["isuCd"] in {ALTERNATIVE, self.rejected}:
                wire["LIST_SHRS"] = "41"
            value = {"output": [{"TRD_DD": bar.Date.strftime("%Y/%m/%d"), **wire}]}
        else:
            raise AssertionError(f"unexpected KRX request: {data}")
        return _Response(json.dumps(value).encode())


class _KIND:
    def __init__(self):
        self.calls = []

    def request(self, method, url, *, data, **kwargs):
        assert method == "POST" and url.endswith("/listinvstg/listingcompany.do")
        assert kwargs["allow_redirects"] is False
        assert data["forward"] == "listingtype_down" and data["pageIndex"] == "1"
        market = data["marketType"]
        self.calls.append((market, data["fromDate"], data["toDate"]))
        headers = ["회사명", "종목코드", "상장일", "상장유형", "증권구분", "업종", "국적", "상장주선인",
                   "액면가 (원)", "최초상장주식수 (주)"]
        facts = {"2": ["옛 시장", "005930", "2020-01-02", "신규상장", "주권"],
                 "1": ["새 시장", "005930", "2024-01-04", "이전상장", "주권"]}
        values = [*facts[market], "제조업", "대한민국", "", "", ""]
        header = "".join(f"<th>{field}</th>" for field in headers)
        rows = ""
        if data["fromDate"] <= values[2] <= data["toDate"]:
            row = "".join(f"<td>{value}</td>" for value in values)
            rows = f"<tr>{row}</tr>"
        body = f'<table class="bbs_tb"><tr>{header}</tr>{rows}</table>'
        return _Response(body.encode("cp949"), encoding="cp949")


@pytest.fixture
def observed(tmp_path):
    days = pd.date_range("2024-01-02", "2024-01-04")
    source = tmp_path / "days"
    source.mkdir()
    captures = {}
    for day in days:
        prior = day < days[-1]
        rows = [("005930", "KOSDAQ" if prior else "KOSPI", "옛 시장" if prior else "새 시장", 100)]
        if prior:
            rows.append(("000660", "KOSPI", "과거 종목", 150))
        frame = _price_day(day, rows)
        captures[day.date().isoformat()] = frame
        frame.to_parquet(source / f"{day:%Y-%m-%d}.parquet", index=False)
    return source, days, captures


def test_official_listing_masters_recover_transfers_and_ambiguous_finder_ids(tmp_path, monkeypatch, observed):
    source, days, captures = observed
    krx = _KRX(captures)
    kind = _KIND()
    monkeypatch.setattr(providers, "get_krx_session", lambda: krx)
    monkeypatch.setattr("shared.data.kind_market.time.sleep", lambda _: None)
    root = tmp_path / "sources"
    client = KindMarket(root / "kind", budget=2, session=kind)
    paths = prepare_listing_masters(root, source, days, observed_on=date(2024, 1, 5), kind=client)
    frame = _security_master(*paths).set_index(["Code", "Market"])
    assert frame.loc[("005930", "KOSDAQ"), "ListingDate"] == pd.Timestamp("2020-01-02")
    assert frame.loc[("005930", "KOSDAQ"), "DelistingDate"] == pd.Timestamp("2024-01-04")
    assert frame.loc[("005930", "KOSPI"), "ListingDate"] == pd.Timestamp("2024-01-04")
    assert frame.loc[("000660", "KOSPI"), "ISIN"] == FORMER
    assert {form["isuCd"] for endpoint, form in krx.calls if endpoint == "MDCSTAT01701"} == {
        ISIN, FORMER, ALTERNATIVE}
    assert [market for market, _, _ in kind.calls] == ["2", "1"]
    prior = list(krx.calls)
    again = KindMarket(root / "kind", budget=0, session=kind)
    assert prepare_listing_masters(root, source, days, observed_on=date(2024, 1, 5), kind=again) == paths
    assert krx.calls == prior
    assert [market for market, _, _ in kind.calls] == ["2", "1"]

    prepare_listing_masters(root, source, days[1:], observed_on=date(2024, 1, 5), kind=again)
    assert krx.calls == prior
    assert [market for market, _, _ in kind.calls] == ["2", "1"]

    extended = KindMarket(root / "kind", budget=2, session=kind)
    prepare_listing_masters(root, source, days, observed_on=date(2024, 1, 6), kind=extended)
    assert kind.calls[-2:] == [("2", "2024-01-06", "2024-01-06"), ("1", "2024-01-06", "2024-01-06")]
    delta = krx.calls[len(prior):]
    delist_form, = [form for endpoint, form in delta if endpoint == "MDCSTAT23801"]
    assert delist_form["strtDd"] == delist_form["endDd"] == "20240106"
    assert {endpoint for endpoint, _ in delta} == {"MDCSTAT01901", "MDCSTAT23801", "finder_listdelisu"}

    active_response = next(path for path in (root / "listing_history" / "objects").iterdir()
                           if "OutBlock_1" in json.loads(path.read_bytes()))
    active_response.write_bytes(b"{}")
    with pytest.raises(ValueError, match="Changed KRX listing response"):
        prepare_listing_masters(root, source, days, observed_on=date(2024, 1, 5), kind=again)
    assert all(path.is_file() for path in paths)


def test_unverified_identity_remains_a_source_gap(tmp_path, monkeypatch, observed):
    source, days, captures = observed
    krx = _KRX(captures, rejected=ISIN)
    kind = _KIND()
    monkeypatch.setattr(providers, "get_krx_session", lambda: krx)
    monkeypatch.setattr("shared.data.kind_market.time.sleep", lambda _: None)
    root = tmp_path / "sources"
    client = KindMarket(root / "kind", budget=2, session=kind)
    with pytest.raises(ValueError, match="Incomplete official KRX listing identity"):
        prepare_listing_masters(root, source, days, observed_on=date(2024, 1, 5), kind=client)
    assert not list((root / "listing_history" / "masters").glob("*/manifest.json"))
    report = json.loads((root / "listing_history" / "latest_report.json").read_text())
    assert [(gap["code"], gap["market"]) for gap in report["unresolved"]] == [("005930", "KOSDAQ")]
    assert Path(source / "2024-01-02.parquet").is_file()

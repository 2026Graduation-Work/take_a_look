import json
from collections import Counter
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml
from experiments.dataset.collect import main as collect
from experiments.dataset.pipeline import preprocess_dataset, training_metadata
from experiments.dataset.verify_training_prices import verify
from shared.data import bulk_prices, calendar, listing_history, providers, trading_calendar
from shared.data.kind_market import DAILY_MAIN, DAILY_URL, KindMarket, KindUnavailable, daily_form
from shared.data.resolution_snapshot import read_resolution_snapshot
from shared.io import sha256


def test_cold_collection_resumes_and_reuses_only_verified_source_days(tmp_path, monkeypatch):
    calls = Counter()
    requests = []
    source_root = tmp_path / "sources"
    missing_kospi_listing = False
    corrected_prices = False
    omitted_sibling_date = None

    def source_day(day):
        calls["daily"] += 1
        requests.append(("daily", str(day.date())))
        frame = pd.DataFrame({
            "Code": ["005930", "123456"], "Date": day,
            "RawOpen": 100, "RawHigh": 102, "RawLow": 98, "RawClose": 100,
            "RawChange": 0, "RawVolume": 1000, "Amount": 100_000, "ListedShares": 100_000,
            "MKT_NM": ["KOSPI", "KOSDAQ"], "ISU_ABBRV": ["Samsung", "Unrelated identity"], "SECT_TP_NM": "",
        })
        if corrected_prices and str(day.date()) != omitted_sibling_date:
            frame = pd.concat([frame, frame.iloc[:1].assign(Code="005935")], ignore_index=True)
        return frame

    def index(start, end, ticker="1001", *, lane="pykrx"):
        calls["index"] += 1
        requests.append(("index", lane, ticker, str(start.date()), str(end.date())))
        days = calendar.scheduled_sessions(start, end)
        return pd.DataFrame({"Close": 1000.0}, index=days)

    def master(form):
        endpoint = form["bld"].split("/")[-1]
        calls[endpoint] += 1
        assert form["mktId"] == "ALL"
        if endpoint == "MDCSTAT01901":
            primary = {"ISU_SRT_CD": "005930", "ISU_CD": "KR7005930003", "ISU_NM": "Samsung",
                       "ISU_ABBRV": "Samsung", "MKT_TP_NM": "KOSPI", "SECUGRP_NM": "주권",
                       "LIST_DD": "2000/01/01", "KIND_STKCERT_TP_NM": "보통주"}
            listings = [primary, {**primary, "ISU_SRT_CD": "987654", "MKT_TP_NM": "KOSDAQ"}]
            if missing_kospi_listing:
                listings.append({**primary, "ISU_SRT_CD": "005935", "ISU_CD": "KR7005931001",
                                 "KIND_STKCERT_TP_NM": "1우선주"})
            rows = {"OutBlock_1": listings}
        else:
            assert endpoint == "MDCSTAT23801"
            rows = {"output": []}
        return SimpleNamespace(content=json.dumps(rows).encode())

    def kind_request(self, request):
        if self.remaining == 0:
            raise KindUnavailable("KIND request budget exhausted")
        assert request["url"] == DAILY_URL and request["referer"] == DAILY_MAIN
        day = pd.Timestamp(request["form"]["selDate"]).date()
        assert request["form"] == daily_form(day, 1)
        calls["publication"] += 1
        requests.append(("publication", str(day)))
        self.calls += 1
        self.remaining -= 1
        html = "조회된 결과값이 없습니다. 전체 <em>0</em>건 : <strong>1</strong>/1"
        return self._store(request, html.encode(), "utf-8", None, "fixture transport")

    def flows(day, **_):
        calls["flows"] += 1
        requests.append(("flows", str(day.date())))
        return pd.DataFrame({"Date": [day], "Code": ["005930"], **dict.fromkeys(providers._FLOW_COLUMNS, 5)})

    from contextlib import nullcontext

    monkeypatch.setattr(bulk_prices, "request_day", source_day)
    monkeypatch.setattr(bulk_prices, "time", SimpleNamespace(monotonic=lambda: 0, sleep=lambda _: None))
    monkeypatch.setattr(providers, "_krx_request_timeout", nullcontext)
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", index)
    monkeypatch.setattr(calendar, "fetch_authenticated_index", lambda lo, hi: index(lo, hi, lane="direct"))
    monkeypatch.setattr(listing_history, "krx_listing_response", master)
    monkeypatch.setattr(KindMarket, "_request", kind_request)
    monkeypatch.setattr(providers, "_fetch_investor_day", flows)

    def config(name, start, end, *, tickers=None):
        root = tmp_path / name
        path = root.with_suffix(".yaml")
        collection = {"start_date": date.fromisoformat(start), "end_date": date.fromisoformat(end), "markets": ["KOSPI"],
                      "include_delisted": True, "investor_flows": True}
        if tickers:
            collection["tickers"] = tickers
        path.write_text(yaml.safe_dump({"contract_version": 3, "dataset_id": name, "root": str(root),
                                       "collection": collection, "preprocessing": "shared_v3"}))
        return path, root

    def run(path, budget):
        collect(["--config", str(path), "--source-root", str(source_root), "--kind-request-budget", str(budget)])

    wide_config, wide = config("wide", "2024-05-07", "2024-05-09")
    with pytest.raises(ValueError, match="KIND request budget exhausted"):
        run(wide_config, 2)
    assert calls["publication"] == 2
    assert not (wide / "collection_action_pin.json").exists()
    assert not list((source_root / "official_actions" / "snapshots").glob("*.json"))
    run(wide_config, 150)
    publications = [event for event in requests if event[0] == "publication"]
    assert len(publications) == len(set(publications))
    preprocess_dataset(wide_config)
    assert calls["daily"] == 4 and calls["flows"] == 3 and calls["index"] == 3
    assert verify(wide)[0]["raw_rows"] == 3
    manifest_path = wide / "dataset_manifest.json"
    previous = sha256(manifest_path)
    pinned = json.loads(manifest_path.read_text())["official_actions"]["sha256"]
    snapshot = read_resolution_snapshot(wide / "official_actions" / "snapshots" / f"{pinned}.json")
    assert snapshot.manifest["scope"]["markets"] == ["KOSPI"]
    with pytest.raises(ValueError, match="coverage for the requested markets"):
        training_metadata(snapshot, {"markets": ["KOSPI", "KOSDAQ"]}, {"trading_days": snapshot.sessions})
    old_calls = calls.copy()
    run(wide_config, 0)
    assert sha256(manifest_path) == previous and calls == old_calls

    narrow_config, narrow = config("narrow", "2024-05-08", "2024-05-09", tickers=["005930"])
    run(narrow_config, 0)
    assert calls == old_calls
    assert json.loads((narrow / "dataset_manifest.json").read_text())["official_actions"]["sha256"] == pinned
    preprocess_dataset(narrow_config)
    assert verify(narrow)[0]["raw_rows"] == 2

    longer_config, longer = config("longer", "2024-05-07", "2024-05-10")
    requests.clear()
    run(longer_config, 150)
    assert calls - old_calls == {"daily": 1, "index": 3, "publication": 1, "flows": 1}
    assert all(event[-1] in {"2024-05-10", "2024-05-13"} for event in requests)
    assert verify(longer)[0]["raw_rows"] == 4
    assert sha256(manifest_path) == previous

    source_root = tmp_path / "missing_listing_sources"
    missing_kospi_listing = True
    invalid_config, invalid = config("missing-listing", "2024-05-07", "2024-05-09")
    requests.clear()
    with pytest.raises(ValueError, match=r"KOSPI 005935 2024-05-03\.\.2024-05-09"):
        run(invalid_config, 150)
    assert not (invalid / "collection_action_pin.json").is_file()
    assert all(event[0] != "publication" for event in requests)
    valid_config, valid = config("selected-listing", "2024-05-07", "2024-05-09", tickers=["005930"])
    run(valid_config, 150)
    assert [result["code"] for result in verify(valid)] == ["005930"]

    retained = valid / "dataset_manifest.json"
    retained_hash = sha256(retained)
    original_day = source_root / "krx_days/2024-05-07.parquet"
    old_day_hash = sha256(original_day)
    corrected_prices = True
    requests.clear()
    run(invalid_config, 0)
    retried = [(kind, day) for kind, day in requests if kind == "daily"]
    assert [day for _, day in retried] == ["2024-05-03", "2024-05-07", "2024-05-08", "2024-05-09"]
    assert {row["code"] for row in verify(invalid)} == {"005930", "005935"}
    assert old_day_hash == sha256(source_root / "krx_day_archive" / "objects" / old_day_hash)
    assert old_day_hash != sha256(original_day)
    assert sha256(retained) == retained_hash
    assert [result["code"] for result in verify(valid)] == ["005930"]

    source_root = tmp_path / "sibling_gap_sources"
    omitted_sibling_date = "2024-05-08"
    old_config, old = config("before-sibling-gap", "2024-05-07", "2024-05-07", tickers=["005930"])
    run(old_config, 150)
    old_manifest = old / "dataset_manifest.json"
    old_hash = sha256(old_manifest)

    requests.clear()
    sibling_config, sibling = config("sibling-gap", "2024-05-07", "2024-05-09", tickers=["005930"])
    with pytest.raises(ValueError, match=r"005935.*2024-05-08"):
        run(sibling_config, 150)
    assert not (sibling / "collection_action_pin.json").is_file()
    assert all(event[0] != "publication" for event in requests)
    incomplete_day = source_root / "krx_days/2024-05-08.parquet"
    incomplete_hash = sha256(incomplete_day)

    omitted_sibling_date = None
    requests.clear()
    run(sibling_config, 150)
    assert [event[-1] for event in requests if event[0] == "daily"] == ["2024-05-08"]
    assert [row["code"] for row in verify(sibling)] == ["005930"]
    assert sha256(source_root / "krx_day_archive" / "objects" / incomplete_hash) == incomplete_hash
    assert sha256(old_manifest) == old_hash
    assert [row["code"] for row in verify(old)] == ["005930"]

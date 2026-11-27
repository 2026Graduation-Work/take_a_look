import csv
import json
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest
from experiments.dataset.census_actions import main
from experiments.dataset.freeze_resolution_snapshot import freeze_resolution_snapshot
from experiments.tests.test_market_census import use_archived_kind_bodies
from shared.data.resolution_snapshot import read_resolution_snapshot
from shared.data.segmented_prices import adjust_training_window
from shared.io import sha256


@pytest.mark.parametrize("code,isin,name,term,quote,ex_day,previous,base,price,volume", [
    ("095610", "KR7095610002", "테스", "20160428000303", "20160412000324", "2016-04-14", "2016-04-12",
     12600, Fraction(2, 3), Fraction(3, 2)),
    ("126880", "KR7126880004", "제이엔케이히터", "20160722000097", "20160802000269", "2016-08-03", "2016-08-02",
     5310, Fraction(5310, 6840), Fraction(13, 10)),
])
def test_combined_offering_factors_survive_official_archive_sealing(
    tmp_path, monkeypatch, code, isin, name, term, quote, ex_day, previous, base, price, volume,
):
    fixtures = Path(__file__).parents[2] / "shared/tests/fixtures/market_actions"
    raw = pd.read_csv(fixtures / f"{code}.bonus-prices.csv.gz", dtype={"Code": str})
    raw["Date"] = pd.to_datetime(raw.Date)
    def published(accession):
        return f"{accession[:4]}-{accession[4:6]}-{accession[6:8]}"
    use_archived_kind_bodies(monkeypatch, {published(term): (term,), published(quote): (quote,)},
                            issuer=code[:5], submitter={term: name, quote: "코스닥시장본부"})
    days, output, cache = (tmp_path / part for part in ("days", "census", "kind"))
    days.mkdir()
    for day, rows in raw.groupby("Date"):
        rows.to_parquet(days / f"{day:%Y-%m-%d}.parquet", index=False)
    active, delisted = tmp_path / "active.parquet", tmp_path / "delisted.parquet"
    pd.DataFrame([(code, isin, name, name, "KOSDAQ", "주권", "2016/01/01", "보통주")],
                 columns=["ISU_SRT_CD", "ISU_CD", "ISU_NM", "ISU_ABBRV", "MKT_TP_NM", "SECUGRP_NM",
                          "LIST_DD", "KIND_STKCERT_TP_NM"]).to_parquet(active, index=False)
    pd.DataFrame(columns=["Symbol", "ISIN", "Name", "Market", "SecuGroup", "ListingDate", "DelistingDate",
                          "KIND_STKCERT_TP_NM"]).to_parquet(delisted, index=False)
    start, end = raw.Date.min().date().isoformat(), raw.Date.max().date().isoformat()
    publication_start = min((raw.Date.min() - pd.Timedelta(days=7)).date().isoformat(), published(term), published(quote))
    publication_end = (raw.Date.max() + pd.Timedelta(days=3)).date().isoformat()
    main(["--start", start, "--end", end, "--published-start", publication_start,
          "--published-end", publication_end, "--krx-days", str(days), "--active-master", str(active),
          "--delisted-master", str(delisted), "--kind-root", str(cache), "--output", str(output), "--code", code])
    def freeze(destination):
        return freeze_resolution_snapshot(output, destination, krx_days=days, active_master=active,
                                          delisted_master=delisted, evidence_archives=[cache])
    snapshot = read_resolution_snapshot(freeze(tmp_path / "official"), verify_archive=True)
    key, = snapshot.windows
    event, = (event for event in snapshot.ledgers[key].resolutions if event.date == ex_day)
    assert (event.price_factor, event.volume_factor, event.reason) == (price, volume, "combined_offering_bonus_terms")
    adjusted, _ = adjust_training_window(key, raw.drop(columns=["MKT_NM"]).assign(Market="KOSDAQ"),
                                         snapshot.days(key), end, snapshot)
    before, = adjusted.loc[adjusted.Date.eq(previous), "Close"]
    assert before == pytest.approx(base)
    with (output / "resolutions.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        columns, rows = reader.fieldnames, list(reader)
    for row in rows:
        if row["Date"] == ex_day:
            row["PriceFactor"] = "1/2"
    with (output / "resolutions.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, columns)
        writer.writeheader()
        writer.writerows(rows)
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["table_sha256"]["resolutions"] = sha256(output / "resolutions.csv")
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Combined offering bonus factors"):
        freeze(tmp_path / "tampered")

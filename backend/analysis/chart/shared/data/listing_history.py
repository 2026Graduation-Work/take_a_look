import hashlib
import html
import json
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path

import pandas as pd
import requests

from shared.io import atomic_json, atomic_parquet, canonical_hash, sha256

from .actions import official_date, valid_isin
from .bulk_prices import MissingListingPrices, prepare_source_days
from .calendar import scheduled_sessions
from .disclosures import TableRows, put_immutable, require
from .kind_market import EXCHANGE, KindMarket
from .market_notices import normal_company
from .metadata import ACTIVE_LISTING_FORM
from .providers import delisted_listing_form, krx_listing_response
from .training_prices import KRX_FIELDS, parse_krx_fields
from .validation import KRX_RAW_COLUMNS, validate_krx_raw

MARKETS = {"STK": "KOSPI", "KSQ": "KOSDAQ", "KNX": "KONEX"}
EQUITIES = {"주권", "외국주권", "주식예탁증권", "부동산투자회사"}
KIND_LISTINGS = "https://kind.krx.co.kr/listinvstg/listingcompany.do"
KIND_MARKETS = {"KOSPI": ("1", date(2000, 1, 1)), "KOSDAQ": ("2", date(1996, 7, 1)),
                "KONEX": ("6", date(2013, 7, 1))}
FINDER = {"bld": "dbms/comm/finder/finder_listdelisu", "mktsel": "ALL", "searchText": "", "typeNo": "0"}
IPO_FORM = {"bld": "dbms/MDC/STAT/issue/MDCSTAT20001", "mktId": "ALL", "isurCd": "ALL",
            "isurCd2": "ALL", "leadTpComp": "ALL", "listClssCd": "ALL", "secugrpTp": "ALL",
            "cntrIsoCd": "ALL", "share": "1", "money": "1", "locale": "ko_KR", "csvxls_isNo": "true"}
ACTIVE_FIELDS = {"ISU_SRT_CD", "ISU_CD", "ISU_NM", "ISU_ABBRV", "MKT_TP_NM", "SECUGRP_NM",
                 "KIND_STKCERT_TP_NM", "LIST_DD"}
DELIST_FIELDS = {"ISU_CD", "ISU_NM", "MKT_NM", "SECUGRP_NM", "KIND_STKCERT_TP_NM", "LIST_DD", "DELIST_DD"}
KIND_HEADERS = ["회사명", "종목코드", "상장일", "상장유형", "증권구분", "업종", "국적", "상장주선인",
                "액면가 (원)", "최초상장주식수 (주)"]
DATE_PATTERN = r"\d{4}-\d{2}-\d{2}|\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"
CACHE_VERSION = 1


def _market(value):
    return value.replace("KOSDAQ GLOBAL", "KOSDAQ")


def _date(value):
    return date.fromisoformat(value.replace("/", "-"))


@dataclass(frozen=True)
class Listing:
    code: str
    isin: str
    name: str
    short_name: str
    market: str
    group: str
    share: str
    start: date
    end: date | None
    evidence: tuple[str, ...]

    def output(self):
        return {"Symbol": self.code, "ISIN": self.isin, "Name": self.name, "ShortName": self.short_name,
                "Market": self.market, "SecuGroup": self.group, "KIND_STKCERT_TP_NM": self.share,
                "ListingDate": self.start.isoformat(), "DelistingDate": self.end.isoformat() if self.end else None,
                "HistoricalEvidence": ";".join(self.evidence)}


class ListingSources:
    def __init__(self, root):
        self.root = root

    def _request(self, form, *, generation=None):
        return {"version": CACHE_VERSION, "form": form, "observation": generation}

    def _pointer(self, request):
        return self.root / "requests" / request["form"]["bld"].rsplit("/", 1)[-1] / (canonical_hash(request) + ".json")

    def table(self, form, key, required, *, generation=None, allow_empty=True, date_field=None):
        request = self._request(form, generation=generation)
        pointer = self._pointer(request)
        if pointer.exists():
            receipt = json.loads(pointer.read_text())
            digest = receipt["sha256"]
            require(receipt["request"] == request and isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest),
                    f"Invalid KRX listing request receipt: {pointer.name}")
            body = (self.root / "objects" / digest).read_bytes()
            require(len(body) == receipt["bytes"] and hashlib.sha256(body).hexdigest() == digest,
                    f"Changed KRX listing response: {pointer.name}")
        else:
            try:
                response = krx_listing_response(form)
            except requests.RequestException as exc:
                raise ValueError(f"KRX listing request failed: {form['bld'].rsplit('/', 1)[-1]}") from exc
            body = response.content
            digest = hashlib.sha256(body).hexdigest()
        endpoint = form["bld"].rsplit("/", 1)[-1]
        try:
            result = json.loads(body)
            rows = result[key]
        except (UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"KRX {endpoint} returned no official listing table for {form}") from exc
        require(isinstance(rows, list) and (allow_empty or rows)
                and all(isinstance(row, dict) and required <= row.keys() for row in rows),
                f"Invalid KRX {endpoint} response fields for {form}")
        if date_field:
            left = datetime.strptime(form["strtDd"], "%Y%m%d").date()
            right = datetime.strptime(form["endDd"], "%Y%m%d").date()
            require(all(left <= _date(row[date_field]) <= right for row in rows),
                    f"KRX {endpoint} row date lies outside request {left}..{right}")
        if not pointer.exists():
            put_immutable(self.root / "objects" / digest, body)
            atomic_json(pointer, {"request": request, "sha256": digest, "bytes": len(body),
                                  "received_at": datetime.now(UTC).isoformat()})
        return rows, digest

    def dated(self, start, end, form_at, required, field, *, generation=None):
        example = form_at(start, end)
        folder = self._pointer(self._request(example, generation=generation)).parent
        available = []
        for path in sorted(folder.glob("*.json")):
            request = json.loads(path.read_text())["request"]
            if request["observation"] != generation:
                continue
            form = request["form"]
            lo = datetime.strptime(form["strtDd"], "%Y%m%d").date()
            hi = datetime.strptime(form["endDd"], "%Y%m%d").date()
            if form == form_at(lo, hi) and lo <= end and start <= hi:
                available.append((lo, hi))
        while start <= end:
            covering = [(left, right) for left, right in available if left <= start <= right]
            if covering:
                left, right = max(covering, key=lambda span: span[1])
            else:
                upcoming = min((left - timedelta(days=1) for left, _ in available if left > start), default=end)
                left, right = start, min(end, upcoming, start + timedelta(days=729))
            rows, digest = self.table(form_at(left, right), "output", required, generation=generation, date_field=field)
            for row in rows:
                day = _date(row[field])
                if start <= day <= end:
                    yield row, digest
            start = right + timedelta(days=1)

    def exact_raw(self, isin, observations):
        date8 = observations.Date.iloc[0].strftime("%Y%m%d")
        rows, digest = self.table(
            {"bld": "dbms/MDC/STAT/standard/MDCSTAT01701", "isuCd": isin,
             "strtDd": date8, "endDd": date8, "adjStkPrc": "1"},
            "output", {"TRD_DD", *KRX_FIELDS}, date_field="TRD_DD",
        )
        if not rows:
            return None
        checked = parse_krx_fields(pd.DataFrame(rows))
        checked["Date"] = pd.to_datetime(checked.TRD_DD, format="%Y/%m/%d")
        days = pd.DatetimeIndex(observations.Date)
        return digest if validate_krx_raw(checked, days).equals(validate_krx_raw(observations, days)) else None


def _raw_index(directory, sessions, codes):
    frames = []
    for day in sessions:
        path = directory / f"{day:%Y-%m-%d}.parquet"
        rows = pd.read_parquet(path, columns=["Code", "Date", "MKT_NM", "ISU_ABBRV"])
        require(not rows.empty and rows.Date.eq(day).all() and not rows.Code.duplicated().any(),
                f"Invalid KRX daily observations for listing identity: {path.name}")
        if codes:
            rows = rows[rows.Code.isin(codes)]
        for column in ("Code", "MKT_NM", "ISU_ABBRV"):
            rows[column] = rows[column].astype("string[pyarrow]")
        frames.append(rows)
    frame = pd.concat(frames, ignore_index=True).rename(columns={"MKT_NM": "Market"})
    frame["Market"] = frame.Market.replace({"KOSDAQ GLOBAL": "KOSDAQ"})
    require(frame.Market.isin(MARKETS.values()).all(), "KRX daily observations contain an unknown exchange")
    return frame


def _raw_probe(source_days, rows):
    # A traded row has more independent identity evidence than an unchanged halt.
    for day in reversed(rows.Date.tolist()):
        path = source_days / f"{day:%Y-%m-%d}.parquet"
        raw = pd.read_parquet(path, columns=["Code", *KRX_RAW_COLUMNS])
        observation = raw.loc[raw.Code.eq(rows.Code.iloc[0]), KRX_RAW_COLUMNS]
        require(len(observation) == 1 and observation.Date.eq(day).all(), f"Missing probe observation in {path.name}")
        if observation.RawVolume.iloc[0] > 0 or day == rows.Date.iloc[0]:
            return observation


def _active(rows, digest):
    return [Listing(row["ISU_SRT_CD"], row["ISU_CD"], row["ISU_NM"], row["ISU_ABBRV"], _market(row["MKT_TP_NM"]),
                    row["SECUGRP_NM"], row["KIND_STKCERT_TP_NM"], _date(row["LIST_DD"]), None, (digest,))
            for row in rows]


def _finder(sources, observed_on):
    rows, digest = sources.table(FINDER, "block1", {"short_code", "full_code", "codeName", "marketCode"},
                                 generation=str(observed_on), allow_empty=False)
    candidates = defaultdict(list)
    for row in rows:
        market = MARKETS.get(row["marketCode"])
        require(market is not None, "KRX delisted security finder has an unknown exchange")
        candidates[row["short_code"], market].append(row)
    return candidates, digest


def _delisted(rows, finder, sources, observations, source_days, problems):
    candidates, finder_digest = finder
    for row, digest in rows:
        code, market = row["ISU_CD"], _market(row["MKT_NM"])
        start, end = _date(row["LIST_DD"]), _date(row["DELIST_DD"])
        related = candidates[code, market]
        is_equity = row["SECUGRP_NM"] in EQUITIES
        if is_equity:
            related = [item for item in related if valid_isin(item["full_code"])]
        matches = {item["full_code"] for item in related if normal_company(item["codeName"]) == normal_company(row["ISU_NM"])}
        proof = (digest, finder_digest)
        bars = observations.get(code)
        span = bars[bars.Market.eq(market) & bars.Date.ge(pd.Timestamp(start)) & bars.Date.lt(pd.Timestamp(end))] if bars is not None else None
        has_observations = span is not None and not span.empty
        if has_observations and is_equity and (len(matches) != 1 or len({item["full_code"] for item in related}) != 1):
            probe = _raw_probe(source_days, span)
            verified = {isin: sources.exact_raw(isin, probe) for isin in sorted({item["full_code"] for item in related})}
            accepted = {isin: ref for isin, ref in verified.items() if ref}
            matches = set(accepted)
            if len(accepted) == 1:
                proof += tuple(accepted.values())
        if len(matches) != 1:
            if is_equity and has_observations:
                problems.append({"code": code, "market": market, "start": str(start), "end": str(end),
                                 "reason": "KRX delisting lacks one verified finder ISIN", "evidence": list(proof)})
            continue
        isin, = matches
        yield Listing(code, isin, row["ISU_NM"], row["ISU_NM"], market, row["SECUGRP_NM"],
                      row["KIND_STKCERT_TP_NM"], start, end, proof)


def _mask(bars, listing):
    matches = bars.Market.eq(listing.market) & bars.Date.ge(pd.Timestamp(listing.start))
    if listing.end:
        matches &= bars.Date.lt(pd.Timestamp(listing.end))
    return matches


def _missing_runs(observations, listing_by_code, sessions):
    positions = pd.Series(range(len(sessions)), index=sessions)
    for code, bars in observations.items():
        counts = pd.Series(0, index=bars.index)
        for listing in listing_by_code[code]:
            counts += _mask(bars, listing).astype("int64")
        missing = bars[counts.ne(1)].copy()
        if not missing.empty:
            breaks = missing.Date.map(positions).diff().ne(1) | missing.Market.ne(missing.Market.shift()).fillna(True)
            yield from ((code, run) for _, run in missing.groupby(breaks.astype("int64").cumsum(), sort=False))


def _complete_window(listing, rows, sessions):
    start, end = pd.Timestamp(listing.start), pd.Timestamp(listing.end)
    expected = sessions[(sessions >= start) & (sessions < end)]
    return rows.Market.eq(listing.market).all() and pd.DatetimeIndex(rows.Date).equals(expected)


def _krx_ipo(sources, start, end):
    def form_at(left, right):
        return {**IPO_FORM, "strtDd": left.strftime("%Y%m%d"), "endDd": right.strftime("%Y%m%d")}

    required = DELIST_FIELDS | {"ISU_CD_FULL", "LIST_CLSS_NM"}
    return list(sources.dated(start, end, form_at, required, "LIST_DD"))


def _kind_listing_rows(response, market, start, end, *, allow_limit=False):
    html = response.body.decode("cp949")
    table = re.search(r"<table\b[^>]*class=[\"']bbs_tb[\"'][^>]*>(.*?)</table>", html, re.S | re.I)
    require(table is not None, "KIND listing history table missing")
    parser = TableRows()
    parser.feed(table[1])
    headers = [*KIND_HEADERS]
    if market == "KONEX":
        headers[7] = "지정자문인"
    require(parser.rows and parser.rows[0] == headers, "KIND listing history columns differ")
    require(all(len(cells) == len(KIND_HEADERS) for cells in parser.rows[1:]), "Incomplete KIND listing history row")
    if len(parser.rows) > 3000 or "최대 3000건까지 다운로드 됩니다" in table[1]:
        require(allow_limit, "KIND listing history excerpt is incomplete")
        return None
    result = []
    for name, code, day, listing_type, group, *_ in parser.rows[1:]:
        require(re.fullmatch(r"[0-9A-Z]{6}", code) and start <= _date(day) <= end,
                "KIND listing history has an invalid code or date")
        result.append((code, market, _date(day), listing_type, group, name, response.evidence.receipt))
    require(len(result) == len({row[:3] for row in result}), "KIND listing history contains duplicate intervals")
    return result


def _kind_listings(kind, market, end):
    market_code, floor = KIND_MARKETS[market]
    if end < floor:
        return []

    inventory = kind.root / "listing_ranges" / market
    saved = []
    for pointer in sorted(inventory.glob("*.json")):
        left, right = map(_date, pointer.stem.split("_"))
        if left <= end and floor <= right:
            saved.append((left, right))

    def fetch(start, stop, *, cached=False):
        form = {"method": "searchListingTypeSub", "forward": "listingtype_down", "currentPageSize": "3000",
                "pageIndex": "1", "listTypeArrStr": "01|02|03|04|05|", "secuGrpArrStr": "0|ST|FS|MF|SC|RT|IF|DR|",
                "marketType": market_code, "country": "", "industry": "", "repIsuSrtCd": "", "isurCd": "",
                "searchCodeType": "", "searchCorpName": "", "searchCorpNameTmp": "", "orderMode": "", "orderStat": "",
                "choicTypeArrStr": "01|05|", "fromDate": str(start), "toDate": str(stop)}
        rows = kind._get(KIND_LISTINGS, form=form, referer=KIND_LISTINGS + "?method=searchListingTypeMain",
                         parse=lambda response: _kind_listing_rows(response, market, start, stop, allow_limit=not cached),
                         cache_only=cached)
        if rows is None:
            require(start < stop, "KIND listing results hit the export limit for one day")
            midpoint = start + (stop - start) // 2
            return fetch(start, midpoint) + fetch(midpoint + timedelta(days=1), stop)
        if not cached:
            atomic_json(inventory / f"{start}_{stop}.json", {"start": str(start), "end": str(stop)})
        return rows

    result = []
    while floor <= end:
        covering = [(left, right) for left, right in saved if left <= floor <= right]
        if covering:
            left, stop = max(covering, key=lambda span: span[1])
            rows = fetch(left, stop, cached=True)
        else:
            stop = min(end, min((left - timedelta(days=1) for left, _ in saved if left > floor), default=end))
            rows = fetch(floor, stop)
        result.extend(row for row in rows if floor <= row[2] <= end)
        floor = stop + timedelta(days=1)
    return result


def _formed_delisting(body, code, market):
    if not body.final:
        return []
    table = TableRows()
    table.feed(body.text())
    records = table.rows
    names = [cells[-1] for cells in records if re.fullmatch(r"1\.?\s*회사명", cells[0]) and len(cells) == 2]
    ends = [cells[-1] for cells in records if re.fullmatch(r"7\.?\s*상장폐지일", cells[0]) and len(cells) == 2]
    regulations = [cells[-1] for cells in records if re.fullmatch(r"8\.?\s*근거규정", cells[0]) and len(cells) == 2]
    market_korean = {"KOSPI": "유가증권시장", "KOSDAQ": "코스닥시장", "KONEX": "코넥스시장"}[market]
    if len(names) != 1 or len(ends) != 1 or len(regulations) != 1 or market_korean not in regulations[0].replace(" ", ""):
        return []
    return [(names[0], cells[0], _date(official_date(cells[-1])), _date(official_date(ends[0])))
            for cells in records if len(cells) == 4 and cells[1] == f"A{code}"
            and re.fullmatch(DATE_PATTERN, cells[-1])]


def _kind_delistings(kind, code, market, last, search_through, observed_on):
    start = last - timedelta(days=14)
    end = min(observed_on, search_through + timedelta(days=14))
    rows = []
    while start <= end:
        stop = min(end, start + timedelta(days=729))
        filings, _ = kind.market_actions(code, start, stop)
        rows.extend(filings)
        start = stop + timedelta(days=1)
    daily = {}
    for filing in rows:
        title = re.sub(r"^(?:\[[^]]+\])+|\s+", "", filing.title)
        if not re.fullmatch(r"(?:주권)?상장폐지(?:\([^)]*\))?", title) or filing.withdrawn:
            continue
        # Market search uses the requested code. The daily row also supplies the actual issuer binding.
        if filing.published not in daily:
            daily[filing.published] = {row.accession: row for row in kind.day(filing.published)[0]}
        official = daily[filing.published].get(filing.accession)
        require(official and official.submitter in EXCHANGE and official.company_id
                and code.startswith(official.company_id), f"KIND delisting issuer missing: {filing.accession}")
        if official.withdrawn:
            continue
        _, body, refs = kind.document(official)
        if not body.final:
            referral = kind.final_referral(official, body, refs)
            final_day = _date(f"{referral.route.accession[:4]}-{referral.route.accession[4:6]}-{referral.route.accession[6:8]}")
            require(final_day <= observed_on, f"KIND delisting correction not yet observable: {filing.accession}")
            _, span = kind.day(final_day)
            target = kind.dated_filing(span, referral.route.accession)
            require(target and not target.withdrawn and target.company_id == official.company_id
                    and target.submitter in EXCHANGE, f"KIND delisting correction issuer differs: {filing.accession}")
            _, body, final_refs = kind.document(target, expected=referral)
            refs = (*refs, referral.evidence, target.evidence, *final_refs)
        for name, share, listed, delisted in _formed_delisting(body, code, market):
            yield name, share, listed, delisted, (official.evidence.receipt, *(ref.receipt for ref in refs))


def _company_transfer_dates(text, market, destination):
    names = {"KOSPI": "유가증권시장", "KOSDAQ": "코스닥시장", "KONEX": "코넥스시장"}
    former = rf"{names[market]}(?:에|에서)(?:주식을)?상장(?:하였고|하였습니다|하여|되었고)"
    if market == "KOSDAQ":
        former = rf"(?:{former}|협회중개시장\(KOSDAQ\)에등록하였으며)"
    target = rf"{names[destination.market]}(?:에|으로)(?:신규|이전)상장"
    text = html.unescape(re.sub(r"<[^>]*>", " ", text))
    compact = re.sub(r"\s+", "", text)
    before_market = rf"(?:(?!(?:{DATE_PATTERN})).){{0,115}}?"
    dates = re.findall(rf"({DATE_PATTERN})(?:에|자로)?{before_market}{former}.{{0,370}}?"
                       rf"({DATE_PATTERN})(?:에|자로)?{target}", compact)
    return {listed for start, end in dates if (listed := _date(official_date(start))) < destination.start
            and _date(official_date(end)) == destination.start}


def _company_transfer(kind, destination, market, observed_on):
    end = min(observed_on, destination.start + timedelta(days=550))
    rows, _ = kind.company(destination.code, destination.start, end)
    for filing in rows:
        if (not re.search(r"(?:분기|반기|사업)보고서", filing.title) or filing.withdrawn
                or not filing.company_id or not destination.code.startswith(filing.company_id)):
            continue
        _, body, refs = kind.document(filing)
        if not body.final:
            continue
        dates = _company_transfer_dates(body.text(), market, destination)
        if dates:
            for start in dates:
                yield start, (filing.evidence.receipt, *(ref.receipt for ref in refs))
            return


def _transfer_boundary(successor, market, last, bars, sessions, source_days, record):
    destination = pd.Timestamp(successor.start)
    if destination in sessions:
        position = sessions.get_loc(destination)
        if (position and sessions[position - 1].date() == last
                and bars.Market.eq(successor.market).loc[bars.Date.eq(destination)].any()):
            return ()
        return None
    if pd.Timestamp(last) != sessions[-1] or destination <= sessions[-1]:
        return None
    boundary = scheduled_sessions(destination - pd.Timedelta(days=14), destination)
    if len(boundary) < 2 or boundary[-1] != destination:
        return None
    proof = boundary[-2:]
    prepare_source_days(source_days, proof, record)
    hashes = []
    for day, expected_market in zip(proof, (market, successor.market), strict=True):
        path = source_days / f"{day:%Y-%m-%d}.parquet"
        daily = pd.read_parquet(path, columns=["Code", "MKT_NM"])
        if len(daily.loc[daily.Code.eq(successor.code) & daily.MKT_NM.map(_market).eq(expected_market)]) != 1:
            return None
        hashes.append(sha256(path))
    return tuple(hashes)


def _recover_run(
    code, run, observations, known, sessions, *, sources, source_days, historical, finder, kind, kind_listings,
    observed_on, record,
):
    market = run.Market.iloc[0]
    first, last = run.Date.iloc[0].date(), run.Date.iloc[-1].date()
    all_bars = observations[code]
    former = [row for row in historical if row[0]["ISU_CD"] == code and _market(row[0]["MKT_NM"]) == market]
    names = set(run.ISU_ABBRV.dropna().map(normal_company))
    proposed = []
    for row, digest in former:
        if not row["DELIST_DD"]:
            continue
        listing = Listing(code, row["ISU_CD_FULL"], row["ISU_NM"], run.ISU_ABBRV.iloc[-1], market, row["SECUGRP_NM"],
                          row["KIND_STKCERT_TP_NM"], _date(row["LIST_DD"]), _date(row["DELIST_DD"]), (digest,))
        if _complete_window(listing, run, sessions):
            proposed.append(listing)

    following = [item for item in known if item.start > last]
    successor = min((item for item in following if item.market != market),
                    key=lambda item: item.start, default=None)
    if kind is not None and not proposed:
        old_listings = kind_listings(market)
        if successor:
            new_listings = [row for row in kind_listings(successor.market)
                            if row[:3] == (code, successor.market, successor.start) and row[3] == "이전상장"]
            boundary = (_transfer_boundary(successor, market, last, all_bars, sessions, source_days, record)
                        if len(new_listings) == 1 and new_listings[0][4] == successor.group else None)
            if boundary is not None:
                ending_proof = (new_listings[0][-1], *boundary)
                for row, digest in former:
                    if (not row["DELIST_DD"] and _date(row["LIST_DD"]) <= first
                            and row["SECUGRP_NM"] == successor.group and row["KIND_STKCERT_TP_NM"] == successor.share):
                        proposed.append(replace(successor, isin=row["ISU_CD_FULL"], name=row["ISU_NM"],
                                                short_name=run.ISU_ABBRV.iloc[-1], market=market,
                                                start=_date(row["LIST_DD"]), end=successor.start,
                                                evidence=(*successor.evidence, digest, *ending_proof)))
                for item in old_listings:
                    if (item[:2] == (code, market) and item[2] <= first and item[4] == successor.group
                            and successor.share == "보통주"):
                        proposed.append(replace(successor, name=item[5], short_name=run.ISU_ABBRV.iloc[-1],
                                                market=market, start=item[2], end=successor.start,
                                                evidence=(*successor.evidence, item[-1], *ending_proof)))
                if not proposed and successor.share == "보통주":
                    for start, evidence in _company_transfer(kind, successor, market, observed_on):
                        proposed.append(replace(successor, short_name=run.ISU_ABBRV.iloc[-1], market=market,
                                                start=start, end=successor.start,
                                                evidence=(*successor.evidence, *ending_proof, *evidence)))
        if not proposed:
            through = (min((item.start for item in following), default=observed_on)
                       if last == sessions[-1].date() else last)
            for name, share, start, end, evidence in _kind_delistings(kind, code, market, last, through, observed_on):
                if not start <= first <= last < end:
                    continue
                classes = {(row["ISU_CD_FULL"], row["SECUGRP_NM"], digest) for row, digest in former
                           if _date(row["LIST_DD"]) == start and row["KIND_STKCERT_TP_NM"] == share}
                official_origins = [row for row in old_listings if row[:3] == (code, market, start)]
                finder_rows, finder_digest = finder
                for item in finder_rows[code, market]:
                    if normal_company(item["codeName"]) in (names | {normal_company(name)}):
                        classes.update((item["full_code"], row[4], finder_digest) for row in official_origins)
                for isin, group, digest in sorted(classes):
                    origin = [row[-1] for row in official_origins if row[4] == group]
                    proposed.append(Listing(code, isin, name, run.ISU_ABBRV.iloc[-1], market, group, share,
                                            start, end, (*evidence, digest, *origin)))
                for item in known:
                    origins = [row[-1] for row in official_origins if row[4] == item.group]
                    if (item.share == share and item.group == "주권" and (normal_company(name) in names or origins)):
                        proposed.append(replace(item, name=name, short_name=run.ISU_ABBRV.iloc[-1], market=market,
                                                start=start, end=end, evidence=(*item.evidence, *evidence, *origins)))

    verified = {}
    probe = _raw_probe(source_days, run)
    for listing in proposed:
        if not _complete_window(listing, run, sessions) or not valid_isin(listing.isin):
            continue
        proof = sources.exact_raw(listing.isin, probe)
        if proof:
            key = listing.isin, listing.start, listing.end, listing.market, listing.group, listing.share
            previous = verified.get(key, listing)
            evidence = tuple(sorted({*previous.evidence, *listing.evidence, proof}))
            verified[key] = replace(previous, evidence=evidence)
    return list(verified.values())


def _missing_official_sessions(listings, observations, sessions, markets, codes, required_days):
    for code, market, group, start, end in listings:
        if group != "주권" or market not in markets or codes and code not in codes:
            continue
        expected = sessions[sessions >= pd.Timestamp(start)]
        if end is not None:
            expected = expected[expected < pd.Timestamp(end)]
        if not expected.isin(required_days).any():
            continue
        rows = observations.get(code)
        observed = pd.DatetimeIndex([]) if rows is None else pd.DatetimeIndex(rows.loc[rows.Market.eq(market), "Date"])
        missing = expected.difference(observed)
        if len(missing):
            yield {"code": code, "market": market, "start": missing[0].date().isoformat(),
                   "end": missing[-1].date().isoformat(),
                   "missing_sessions": [day.date().isoformat() for day in missing], "reason": "Official KRX listing interval has missing daily ALL rows"}


def prepare_listing_masters(
    source_root, source_days, sessions, *, observed_on, kind: KindMarket | None = None, codes=(),
    required_markets=(), required_codes=(), required_days=None, include_delisted=True, record=lambda _: None,
):
    """Write and return immutable active and delisted census inputs from official evidence."""
    root = Path(source_root) / "listing_history"
    source_days = Path(source_days)
    observations = {code: rows for code, rows in _raw_index(source_days, sessions, codes).groupby("Code", sort=False)}
    sources = ListingSources(root)
    active_rows, active_digest = sources.table(ACTIVE_LISTING_FORM, "OutBlock_1", ACTIVE_FIELDS, generation=str(observed_on),
                                               allow_empty=False)
    active = _active(active_rows, active_digest)
    first = sessions[0].date()
    dated = list(sources.dated(first, observed_on, delisted_listing_form, DELIST_FIELDS, "DELIST_DD"))
    report = root / "latest_report.json"

    def record_coverage(incomplete):
        atomic_json(report, {"observed_on": str(observed_on), "sessions": [str(first), str(sessions[-1].date())],
                             "codes": sorted(codes), "unresolved": incomplete})

    if required_markets:
        listings = [(item.code, item.market, item.group, item.start, item.end) for item in active]
        if include_delisted:
            listings.extend((row["ISU_CD"], _market(row["MKT_NM"]), row["SECUGRP_NM"],
                             _date(row["LIST_DD"]), _date(row["DELIST_DD"])) for row, _ in dated)
        gaps = list(_missing_official_sessions(
            listings, observations, sessions, required_markets, required_codes,
            required_days if required_days is not None else sessions,
        ))
        if gaps:
            record_coverage(gaps)
            detail = gaps[0]
            raise MissingListingPrices(
                f"Missing KRX daily ALL rows for {detail['market']} {detail['code']} "
                f"{detail['start']}..{detail['end']}; see {report}",
                {day for gap in gaps for day in gap["missing_sessions"]},
            )
    require(observations, "No requested KRX observations for listing identity")
    finder = _finder(sources, observed_on) if dated else (defaultdict(list), None)
    problems = []
    delisted = list(_delisted(dated, finder, sources, observations, source_days, problems))
    by_code = defaultdict(list)
    for listing in (*active, *delisted):
        by_code[listing.code].append(listing)

    @cache
    def kind_listings(market):
        return _kind_listings(kind, market, observed_on)

    missing = list(_missing_runs(observations, by_code, sessions))
    if missing:
        if not dated:
            finder = _finder(sources, observed_on)
        historical = _krx_ipo(sources, date(2013, 7, 1), min(observed_on, sessions[-1].date()))
        for code, run in missing:
            found = _recover_run(code, run, observations, by_code[code], sessions, sources=sources,
                                 source_days=source_days, historical=historical, finder=finder, kind=kind, kind_listings=kind_listings,
                                 observed_on=observed_on, record=record)
            if len(found) == 1:
                listing, = found
                by_code[code].append(listing)
                delisted.append(listing)
    incomplete = [{"code": code, "market": run.Market.iloc[0], "start": str(run.Date.iloc[0].date()),
                   "end": str(run.Date.iloc[-1].date()), "reason": "KRX raw rows lack one verified listing interval",
                   "candidate_evidence": [list(item.evidence) for item in by_code[code]]}
                  for code, run in _missing_runs(observations, by_code, sessions)]
    incomplete.extend(problem for problem in problems if not any(
        item.market == problem["market"] and str(item.start) == problem["start"] and str(item.end) == problem["end"]
        for item in by_code[problem["code"]]
    ))
    record_coverage(incomplete)
    require(not incomplete, f"Incomplete official KRX listing identity for {len(incomplete)} spans; see {report}")

    rows = [listing.output() for listing in delisted]
    master_id = canonical_hash({"active": active_digest, "delisted": rows})
    active_path = root / "masters" / master_id / "active.parquet"
    delisted_path = active_path.parent / "delisted.parquet"
    receipt = active_path.parent / "manifest.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        require(saved == {"active": sha256(active_path), "delisted": sha256(delisted_path)},
                "Prepared KRX listing masters changed")
    else:
        active_frame = pd.DataFrame(active_rows)
        active_frame["LIST_DD"] = [_date(value).isoformat() for value in active_frame.LIST_DD]
        atomic_parquet(active_path, active_frame)
        atomic_parquet(delisted_path, pd.DataFrame(rows, columns=list(active[0].output())))
        atomic_json(receipt, {"active": sha256(active_path), "delisted": sha256(delisted_path)})
    return active_path, delisted_path

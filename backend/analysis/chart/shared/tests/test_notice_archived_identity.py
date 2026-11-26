from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest
from shared.data.disclosures import DisclosureError
from shared.data.market_notices import match_notice, parse_notice
from shared.data.market_resolutions import Resolution
from shared.tests.test_market_resolutions import official_body, resolve
from shared.tests.test_notice_security import (
    JW_PREF,
    JW_UNIVERSE,
    SAMSUNG,
    SAMSUNG_PREF,
    SAMSUNG_UNIVERSE,
)

FIXTURES = Path(__file__).parent / "fixtures/market_actions"


@pytest.mark.parametrize("accession,security,day,price", [
    ("20160929000274", SAMSUNG, "2016-09-30", Fraction(9200, 10600)),
    ("20160929000295", SAMSUNG_PREF, "2016-09-30", Fraction(33150, 34500)),
    ("20180306000596", SAMSUNG, "2018-03-07", Fraction(7510, 8510)),
    ("20180306000610", SAMSUNG_PREF, "2018-03-07", Fraction(39150, 40150)),
])
def test_archived_samsung_rights_bind_both_real_security_classes(accession, security, day, price):
    filing, form, body = official_body(accession)
    filing = replace(filing, company_id="01014")
    facts, = parse_notice(filing, form, body)
    notice = match_notice(filing, form, facts, body, (), SAMSUNG_UNIVERSE)
    assert notice.security == security
    rows = pd.read_csv(FIXTURES / "samsung-rights-prices.csv.gz", dtype={"Code": str}, parse_dates=["Date"])
    raw = rows.loc[rows.Code.eq(security.code) & rows.Date.le(day)].tail(2).rename(columns={"MKT_NM": "Market"})
    event, = resolve(security, raw.reset_index(drop=True), [notice], coverage_complete=True).resolutions
    assert (event.kind, event.price_factor, event.volume_factor, event.review) == (Resolution.RIGHTS, price, 1, False)


def test_archived_jw_generic_class_stays_ambiguous_across_its_two_preferred_stocks():
    filing, form, body = official_body("20161216000547")
    filing = replace(filing, company_id="00106")
    facts, = (facts for facts in parse_notice(filing, form, body) if facts.share_label == "종류주식")
    assert facts.effective == "2017-01-01"
    with pytest.raises(DisclosureError, match="does not identify one KRX security"):
        match_notice(filing, form, facts, body, (), {JW_PREF: JW_UNIVERSE[JW_PREF]}, identity_universe=JW_UNIVERSE)

from collections import defaultdict
from datetime import date
from unittest.mock import Mock

import pytest
from experiments.dataset.census_actions import _collect_notices
from shared.data.kind_market import KindBody, MarketFiling
from shared.data.market_resolutions import Candidate
from shared.tests.test_notice_security import SAMSUNG, SAMSUNG_UNIVERSE, SOURCE


@pytest.mark.parametrize("rows,day,expected", [
    ([("1우선주", "A010140", "33,150")], "2016-09-30", "notice_security_unresolved"),
    ([("1우선주", "A010145", "33,150")], "2016-09-30", "outside_scope"),
    ([("1우선주", "A010145", "오류")], "2016-09-30", "preferred_only"),
    ([("보통주", "A010140", "9,200"), ("미지원종류", "A010145", "33,150")], "2016-09-30", "notice_parse_failed"),
    ([("1우선주", "A010145", "33,150")], "2016-09-31", "notice_parse_failed"),
])
def test_census_validates_all_identities_before_filtering_selected_securities(rows, day, expected):
    values = [("1. 회사명", "삼성중공업"),
              ("2. 주식의 종류와 가격", "주권종류", "단축코드", "기준가격(원)"),
              *rows, ("3. 사유", "권리락(유상증자)"), ("4. 적용일", day)]
    html = "<table>" + "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in values) + "</table>"
    filing = MarketFiling("20160929000295", date(2016, 9, 29), "권리락 기준가격 안내", SOURCE,
                          company="삼성중공업", company_id="01014", submitter="유가증권시장본부")
    body = KindBody(html.encode(), "utf-8", SOURCE, "20160929000711", ("20160929000711",), True)
    candidate = Candidate(SAMSUNG, "2016-09-30", "2016-09-29", 10600, 9200, 390000000, 390000000, False)
    client = Mock()
    client.document.return_value = "99301", body, (SOURCE, SOURCE, SOURCE)
    parsed, blocked, unparsed, _, _, failures, *_ = _collect_notices(
        client, [filing], {SAMSUNG: SAMSUNG_UNIVERSE[SAMSUNG]}, defaultdict(tuple, {SAMSUNG: (candidate,)}),
        anchors={}, spac_keys=set(), bounded=True, identity_universe=SAMSUNG_UNIVERSE,
    )
    assert not parsed and not blocked[SAMSUNG]
    if expected == "outside_scope":
        assert not failures and not unparsed[SAMSUNG]
    elif expected == "preferred_only":
        assert len(failures) == 1 and not unparsed[SAMSUNG]
    else:
        assert len(failures) == 1
        failure, = unparsed[SAMSUNG][candidate.date]
        assert failure.failed_check == expected

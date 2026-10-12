"""#292: 재무 비율은 최근 사업보고서(연간) 하나로 — 반기 연환산·일회성 이익·비지배 지분에 흔들리지 않게."""
import datetime as dt

import pandas as pd
from analysis.text.value_pipeline import financial_tracks
from analysis.text.value_pipeline.latest_financials import latest_report, parse_report

# SK하이닉스 2025 사업보고서 형태(조 단위를 1로). 반기엔 일회성 금융수익으로 순이익 > 매출이었다
ANNUAL = pd.DataFrame([
    {"sj_div": "BS", "account_id": "ifrs-full_Equity", "account_nm": "자본총계", "thstrm_amount": "121", "frmtrm_amount": "80"},
    {"sj_div": "BS", "account_id": "ifrs-full_EquityAttributableToOwnersOfParent", "account_nm": "지배기업 소유주지분",
     "thstrm_amount": "120", "frmtrm_amount": "80"},
    {"sj_div": "BS", "account_id": "ifrs-full_Liabilities", "account_nm": "부채총계", "thstrm_amount": "40", "frmtrm_amount": "35"},
    {"sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "thstrm_amount": "97", "frmtrm_amount": "66"},
    {"sj_div": "IS", "account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익", "thstrm_amount": "47", "frmtrm_amount": "23"},
    {"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익", "thstrm_amount": "42", "frmtrm_amount": "20"},
    {"sj_div": "IS", "account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent", "account_nm": "지배기업 소유주지분",
     "thstrm_amount": "40", "frmtrm_amount": "19"},
    # 자본변동표의 같은 계정 ID는 무시해야 한다
    {"sj_div": "SCE", "account_id": "ifrs-full_Equity", "account_nm": "자본총계", "thstrm_amount": "1", "frmtrm_amount": "1"},
])
HALF_WITH_ONE_OFF = pd.DataFrame([
    {"sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "thstrm_amount": "79", "thstrm_add_amount": "132"},
    {"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "account_nm": "반기순이익", "thstrm_amount": "94", "thstrm_add_amount": "134"},
])


class Dart:
    def __init__(self):
        self.calls = []

    def finstate_all(self, ticker, year, reprt_code, fs_div):
        self.calls.append((year, reprt_code, fs_div))
        if reprt_code == "11012" and year == 2026:
            return HALF_WITH_ONE_OFF
        return ANNUAL if (year, reprt_code, fs_div) == (2025, "11011", "CFS") else pd.DataFrame()


def test_uses_latest_annual_report_not_interim():
    dart = Dart()
    year, statement, frame = latest_report(dart, "000660", dt.date(2026, 10, 13))
    assert (year, statement) == (2025, "CFS") and frame is ANNUAL
    assert {code for _, code, _ in dart.calls} == {"11011"}  # 반기·분기는 묻지도 않는다


def test_roe_owners_over_average_owners_equity_and_annual_growth():
    raw = parse_report(ANNUAL)
    assert raw["roe_net_income"] == 40  # 지배주주 순이익(전체 42 아님)
    assert raw["roe_equity_avg"] == 100  # (120 + 80) / 2, 기말 120 아님
    assert raw["revenue"] == 97 and raw["revenue_prev"] == 66  # 환산 없음
    raw["fiscal_year"] = 2025
    track = financial_tracks.build_financial_track(
        ticker="000660", company_name="SK하이닉스", as_of="2026-10-13", raw_financials=raw,
        statement="CFS", receipt_no="20260310000001", filed_at="2026-03-10", validation_errors=[])
    metric = {row["metric_key"]: row for row in track["metrics"]}
    assert metric["roe"]["value"] == 40.0
    assert metric["revenue_growth"]["value"] == round((97 / 66 - 1) * 100, 4)
    assert "지배주주 순이익" in metric["roe"]["basis"] and "평균 지배주주지분" in metric["roe"]["basis"]
    assert "2025년 말" in metric["roe"]["basis"] and "2024년 말" in metric["roe"]["basis"]


def test_separate_statement_without_owner_split_uses_total_equity_average():
    frame = ANNUAL.loc[~ANNUAL.account_id.str.contains("AttributableToOwners")]
    raw = parse_report(frame)
    assert raw["roe_net_income"] == 42 and raw["roe_equity_avg"] == (121 + 80) / 2 and raw["roe_owners"] is False

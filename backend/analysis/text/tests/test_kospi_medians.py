from analysis.text.value_pipeline.kospi_medians import company_metrics, medians


def test_loss_company_has_no_per_and_medians_skip_missing():
    loss = company_metrics({"net_income": -10.0, "total_equity": 100.0, "total_equity_prev": 100.0,
                            "revenue": 200.0, "revenue_prev": 100.0, "operating_profit": 20.0,
                            "total_liabilities": 50.0}, marcap=300.0)
    assert loss["per"] is None and loss["pbr"] == 3.0
    assert (loss["roe"], loss["operating_margin"], loss["debt_ratio"], loss["revenue_growth"]) == (-10.0, 10.0, 50.0, 100.0)
    profit = company_metrics({"net_income": 30.0, "total_equity": 100.0}, marcap=300.0)
    assert profit["per"] == 10.0 and profit["roe"] is None
    out = medians([loss, profit, company_metrics({"net_income": 10.0, "total_equity": 100.0}, marcap=300.0)])
    assert out["per"] == {"median": 20.0, "count": 2}
    assert out["pbr"] == {"median": 3.0, "count": 3}

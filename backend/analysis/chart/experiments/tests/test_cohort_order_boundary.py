import pandas as pd
import pytest
from backtest_harness import bars, config, signals
from experiments.backtest.local_execution import simulate


@pytest.mark.parametrize(
    "held_prices, next_price, expected",
    [
        ([(10_000, 9659.56), (20_000, 19735.69), (30_000, 31150.32)], 11079.791869729252, 1501),
        (
            [(10000.11, 9850.10835), (20000.21, 19802.207920999997), (30000.5, 29871.49785)],
            11057.06281400478,
            1499,
        ),
    ],
    ids=["held-position-marks", "cash-after-earlier-buys"],
)
def test_opening_equity_sets_same_whole_share_quantity_in_either_ticker_order(
    held_prices, next_price, expected,
):
    prices_by_code = zip(("A", "B", "C", "D"), [*held_prices, (next_price, next_price)], strict=True)
    prices = pd.concat(
        [
            bars([(entry_price,) * 4] * 2 + [(next_open,) * 4] * 2, code)
            for code, (entry_price, next_open) in prices_by_code
        ],
        ignore_index=True,
    )
    entries = signals(prices, [(1, "A"), (1, "B"), (1, "C"), (2, "D")])
    cfg = config(top_n=3, initial_cash=100_000_000, max_holding_days=2)

    quantities = []
    for candidates in (entries, entries.iloc[:, ::-1]):
        orders = simulate(cfg, candidates, prices).events
        quantities.append(orders.loc[orders.side.eq("buy") & orders.code.eq("D"), "quantity"].item())

    assert quantities == [expected, expected]

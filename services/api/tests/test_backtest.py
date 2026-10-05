from dataclasses import replace
from decimal import Decimal as D, localcontext
from fractions import Fraction as F

import pytest
from mv_strategy import Bar, IndicatorState, confirmation_open_time
from mv_strategy.signals import Snapshot, PriceFilter, build_plan, evaluate_setup
from mv_strategy.backtest import Costs, Funding, Replay, available_open, execution_price, modeled_quote, replay_many, touch
from mv_strategy.research_metrics import aggregate, bootstrap

START = 1704067200000
FILTER = PriceFilter(D("0.1"), D(0), D(0))
ZERO = Costs(D(0), D(0), D(0), 1000)


def sources(direction="long", atr="2", hours=2):
    origin = START - 501 * 3_600_000
    snapshots = {"1h": {}, "4h": {}}
    for index in range(-2, hours):
        time = START + index * 3_600_000
        close = D(98 if direction == "long" else 102) if index == -2 else D(100)
        fast, slow, trend = map(D, ("99", "95", "90") if direction == "long" else ("101", "105", "110"))
        bar = Bar(time, time + 3_600_000 - 1, close, close + 1, close - 1, close, D(60))
        snapshots["1h"][time] = Snapshot("1h", bar, fast, slow, trend, D(atr), (time - origin) // 3_600_000 + 1, origin, str(time))
    for time in {confirmation_open_time(START + n * 3_600_000) for n in range(hours + 1)}:
        close, fast, slow, trend = map(D, ("105", "100", "95", "90") if direction == "long" else ("95", "100", "105", "110"))
        bar = Bar(time, time + 14_400_000 - 1, close, close + 1, close - 1, close, D(240))
        snapshots["4h"][time] = Snapshot("4h", bar, fast, slow, trend, D(3), 500, time - 499 * 14_400_000, str(time))
    return snapshots


def minutes(hours=1):
    return [Bar(START + n * 60_000, START + (n + 1) * 60_000 - 1, D(100), D(101), D(99), D(100), D(1)) for n in range(hours * 60)]


def replay(bars, direction="long", costs=ZERO, funding=(), atr="2", history=None):
    return replay_many("BTCUSDT", bars, history or sources(direction, atr, len(bars) // 60), list(funding), FILTER, {"baseline": costs}, START, START + len(bars) * 60_000, D(1000))["baseline"]


@pytest.mark.parametrize("direction,exit_price", [("long", "108"), ("short", "92")])
def test_shared_live_rules_and_target_accounting_independent_rational_oracle(direction, exit_price):
    bars = minutes()
    bars[2] = replace(bars[2], high=D(109) if direction == "long" else D(101), low=D(99) if direction == "long" else D(91))
    result = replay(bars, direction)
    trade = result["trades"][0]
    assert trade["exit_reason"] == "target"
    assert F(trade["net_pnl"]) == 80 and F(result["ending_equity"]) == 1080
    assert trade["entry_time"] == START + 60_000
    assert F(trade["exit_fill"]) == F(exit_price)
    history = sources(direction)
    source, previous = history["1h"][START - 3_600_000], history["1h"][START - 7_200_000]
    confirmation = history["4h"][confirmation_open_time(START)]
    quote = modeled_quote("BTCUSDT", D(100), START + 60_000, FILTER, ZERO)
    expected = build_plan("BTCUSDT", evaluate_setup(source, previous, confirmation).direction, source, quote, FILTER, START + 60_000)
    assert all(trade["plan"][key] == value for key, value in expected.items() if key != "execution")


@pytest.mark.parametrize("direction", ["long", "short"])
def test_ambiguous_intrabar_exit_is_stop_first_and_gap_is_worse(direction):
    bars = minutes()
    bars[2] = replace(bars[2], high=D(110), low=D(90))
    trade = replay(bars, direction)["trades"][0]
    assert trade["ambiguous_stop_first"] and trade["exit_reason"] == "stop"
    assert F(trade["net_pnl"]) == -40
    bars[2] = replace(bars[2], open=D(90 if direction == "long" else 110), close=D(100), high=D(110), low=D(90))
    trade = replay(bars, direction)["trades"][0]
    assert trade["exit_reason"] == "stop_gap" and F(trade["net_pnl"]) == -100
    assert trade["exit_time"] == START + 120_000


@pytest.mark.parametrize("direction,rate,expected", [("long", ".001", -2), ("short", ".001", 2), ("long", "-.001", 2), ("short", "-.001", -2)])
def test_actual_funding_sign_mark_notional_and_cash_reconciliation(direction, rate, expected):
    result = replay(minutes(), direction, funding=[Funding(START + 120_000, D(rate), D(200))])
    trade = result["trades"][0]
    assert F(trade["funding_pnl"]) == expected and trade["funding_events"] == 1
    assert F(result["ending_equity"]) == F(1000 + expected)
    assert F(result["ending_equity"]) - 1000 == sum(F(t["net_pnl"]) for t in result["trades"])


def test_funding_at_entry_timestamp_excludes_new_position_includes_existing_exit():
    bars = minutes()
    bars[2] = replace(bars[2], high=D(109))
    result = replay(bars, funding=[Funding(START + 60_000, D(".001"), D(200)), Funding(START + 120_000, D(".001"), D(200))])
    trade = result["trades"][0]
    assert trade["funding_events"] == 1 and F(trade["funding_pnl"]) == -2
    assert F(result["passive_funding_pnl"]) == -2


def test_fees_both_sides_and_fractional_sleeve_cap_independent_oracle():
    bars = minutes()
    bars[2] = replace(bars[2], high=D(109))
    costs = Costs(D(10), D(0), D(0), 1000)
    result = replay(bars, costs=costs)
    trade = result["trades"][0]
    quantity = F(1000) / (F(100) * F("1.001"))
    expected_fees = quantity * F(208) * F(".001")
    expected_net = quantity * 8 - expected_fees
    assert abs(F(trade["quantity"]) - quantity) < F("1e-30")
    assert abs(F(trade["fees"]) - expected_fees) < F("1e-28")
    assert abs(F(trade["net_pnl"]) - expected_net) < F("1e-28")
    assert F(trade["entry_notional"]) + F(trade["quantity"]) * F(100) * F(".001") <= F(1000) + F("1e-28")


def test_spread_and_slippage_round_adversely_with_nonzero_grid_origin():
    price_filter = PriceFilter(D(".5"), D(".2"), D(10000))
    costs = Costs(D(0), D(2), D(2), 1000)
    with localcontext() as ctx:
        ctx.prec = 34
        quote = modeled_quote("BTCUSDT", D(100), START, price_filter, costs)
        assert quote.bid == D("99.7") and quote.ask == D("100.2")
        assert execution_price(quote.ask, True, price_filter, costs) == D("100.7")
        assert execution_price(quote.bid, False, price_filter, costs) == D("99.2")


def test_latency_and_drift_cannot_fill_deciding_close_or_extend_expiry():
    assert available_open(START, 1000) == START + 60_000
    assert available_open(START, 120_000) == START + 120_000
    bars = minutes()
    bars[1] = replace(bars[1], open=D("101.1"), high=D(102), low=D(100), close=D(101))
    result = replay(bars)
    assert not result["trades"] and result["blocked"]["MISSED_ENTRY_PRICE_DRIFT"] == 1
    delayed = replay(minutes(), costs=Costs(D(0), D(0), D(0), 120_000))
    assert delayed["trades"][0]["entry_time"] == START + 120_000


def test_ema50_exit_is_after_closed_decision_and_stop_remains_active():
    bars, history = minutes(2), sources(atr="5")
    time = START
    source = history["1h"][time]
    history["1h"][time] = replace(source, bar=replace(source.bar, low=D(94), close=D(94)))
    bars[59] = replace(bars[59], open=D(94), high=D(94), low=D(94), close=D(94))
    bars[61] = replace(bars[61], open=D(98), high=D(100), low=D(97), close=D(99))
    trade = replay(bars, atr="5", history=history)["trades"][0]
    assert trade["exit_reason"] == "ema50_exit" and trade["exit_time"] == START + 61 * 60_000
    assert D(trade["exit_fill"]) == 98
    bars[60] = replace(bars[60], open=D(89), high=D(100), low=D(89), close=D(100))
    trade = replay(bars, atr="5", history=history)["trades"][0]
    assert trade["exit_reason"] == "stop_gap" and D(trade["exit_fill"]) == 89


def test_future_snapshots_cannot_change_prefix_and_partitions_force_flat():
    basic = replay(minutes())
    history = sources(hours=100)
    for time, snapshot in list(history["1h"].items()):
        if time >= START:
            history["1h"][time] = replace(snapshot, ema20=D(10000))
    changed = replay(minutes(), history=history)
    assert basic == changed
    assert basic["trades"][0]["exit_reason"] == "partition_end"
    assert basic["trades"][0]["exit_time"] == START + 3_600_000 - 1
    assert basic["curve"][-1]["exposure"] == "0"


def test_a_fresh_later_trigger_cannot_overlap_a_held_position():
    bars, history = minutes(3), sources(atr="5", hours=3)
    source = history["1h"][START]
    history["1h"][START] = replace(source, bar=replace(source.bar, low=D(98), close=D(98)))
    result = replay(bars, atr="5", history=history)
    assert len(result["trades"]) == 1 and result["blocked"]["ACTIVE_POSITION"] == 1


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "bad_geometry", "microseconds"])
def test_bad_execution_history_blocks_replay(mutation):
    bars = minutes()
    if mutation == "missing":
        bars.pop(12)
    elif mutation == "duplicate":
        bars[12] = bars[11]
    elif mutation == "bad_geometry":
        bars[12] = replace(bars[12], low=D(110))
    else:
        bars[12] = replace(bars[12], open_time=bars[12].open_time * 1000)
    with pytest.raises(ValueError):
        replay_many("BTCUSDT", bars, sources(), [], FILTER, {"baseline": ZERO}, START, START + 3_600_000, D(1000))


def test_wrong_or_missing_completed_confirmation_blocks_not_older_fallback():
    history = sources()
    snapshot = history["4h"].pop(confirmation_open_time(START))
    history["4h"][snapshot.bar.open_time - 14_400_000] = replace(snapshot, bar=replace(snapshot.bar, open_time=snapshot.bar.open_time - 14_400_000, close_time=snapshot.bar.close_time - 14_400_000), history_origin=snapshot.history_origin - 14_400_000)
    with pytest.raises(ValueError, match="WAITING_EXPECTED_4H"):
        replay(minutes(), history=history)


def test_portfolio_curve_sums_simultaneous_sleeves_and_net_costed_stats():
    bars = minutes()
    bars[2] = replace(bars[2], high=D(109))
    winner = replay(bars)
    bars[2] = replace(bars[2], high=D(101), low=D(95))
    loser = replay(bars)
    summary = aggregate([winner, loser], START, START + 3_600_000)
    metrics = summary["metrics"]
    assert D(metrics["net_pnl"]) == 40 and D(metrics["return"]) == D(".02")
    assert D(metrics["win_rate"]) == D(".5") and D(metrics["profit_factor"]) == 2
    assert D(metrics["expectancy_r"]) == D(".5")
    assert summary["curve"][-1]["equity"] == "2040"
    assert summary["uncertainty"]["lower"] is None


def test_bootstrap_is_reproducible_and_insufficient_samples_not_zero_uncertainty():
    assert bootstrap([D(0)] * 5)["lower"] is None
    sample = list(map(D, ("-.02", ".01", ".03", "-.01", ".02", ".04")))
    assert bootstrap(sample) == bootstrap(sample)
    assert D(bootstrap(sample)["lower"]) < D(bootstrap(sample)["upper"])


@pytest.mark.parametrize("costs", [Costs(D(-1), D(0), D(0), 1000), Costs(D(0), D("NaN"), D(0), 1000), Costs(D(0), D(0), D(0), 300_000)])
def test_invalid_policy_cannot_silently_become_zero_cost(costs):
    with pytest.raises(ValueError):
        replay(minutes(), costs=costs)

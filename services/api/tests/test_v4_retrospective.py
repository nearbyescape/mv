from types import SimpleNamespace

from mv_strategy import Bar
from app.research.v4_retrospective import (
    Candidate,
    btc_timing_reason,
    circuit_events,
    ist_session_bounds,
    portfolio_health_at,
    scaled_outcome,
    simulate,
    simulate_with_active_cap,
)


def candidate(
    signal_id,
    symbol,
    direction,
    source_open,
    published,
    *,
    recent="1.0",
    extension="0.5",
    regime="established",
    favorable=None,
    adverse=None,
    preliminary=None,
):
    from decimal import Decimal as D

    return Candidate(
        signal_id=signal_id,
        symbol=symbol,
        direction=direction,
        source_open_time=source_open,
        source_close=source_open + 3_600_000,
        published_at=published,
        setup_type="pullback_continuation",
        regime=regime,
        recent_run_atr=D(recent),
        source_extension_atr=D(extension),
        favorable_050_at=favorable,
        adverse_050_at=adverse,
        preliminary_reason=preliminary,
    )


def test_ist_session_bounds_are_exactly_09_to_23():
    start, end = ist_session_bounds("2026-10-06")
    assert end - start == 14 * 3_600_000
    from datetime import datetime
    from app.research.v4_retrospective import IST

    assert datetime.fromtimestamp(start / 1000, IST).isoformat().startswith(
        "2026-10-06T09:00:00"
    )
    assert datetime.fromtimestamp(end / 1000, IST).isoformat().startswith(
        "2026-10-06T23:00:00"
    )


def test_btc_15m_timing_guard_is_directional_and_fail_closed():
    boundary = 1_800_000
    current_open = boundary - 900_000
    previous_open = boundary - 1_800_000

    current = {
        "bar": Bar(
            current_open,
            current_open + 900_000 - 1,
            __import__("decimal").Decimal("101"),
            __import__("decimal").Decimal("104"),
            __import__("decimal").Decimal("100"),
            __import__("decimal").Decimal("103"),
            __import__("decimal").Decimal("10"),
        ),
        "count": 500,
        "ema20": __import__("decimal").Decimal("102"),
        "ema50": __import__("decimal").Decimal("101"),
    }
    previous = {
        "bar": SimpleNamespace(),
        "count": 499,
        "ema20": __import__("decimal").Decimal("101.9"),
        "ema50": __import__("decimal").Decimal("100.9"),
    }
    snapshots = {current_open: current, previous_open: previous}

    assert btc_timing_reason(snapshots, boundary, "long") is None
    assert (
        btc_timing_reason(snapshots, boundary, "short")
        == "BTC_15M_TIMING_CONFLICT"
    )
    assert (
        btc_timing_reason({current_open: current}, boundary, "long")
        == "BTC_15M_TIMING_UNAVAILABLE"
    )


def test_btc_15m_mixed_structure_does_not_veto_long():
    from decimal import Decimal as D

    boundary = 1_800_000
    current_open = boundary - 900_000
    previous_open = boundary - 1_800_000
    current = {
        "bar": Bar(
            current_open,
            current_open + 900_000 - 1,
            D("101"),
            D("103"),
            D("99"),
            D("101.5"),
            D("10"),
        ),
        "count": 500,
        "ema20": D("101"),
        "ema50": D("102"),
    }
    previous = {
        "bar": SimpleNamespace(),
        "count": 499,
        "ema20": D("101.2"),
        "ema50": D("102.1"),
    }
    # BTC is weak, but close is not below EMA20; this is not a hard opposite
    # stack and therefore cannot veto an otherwise valid V4 LONG.
    assert btc_timing_reason(
        {current_open: current, previous_open: previous}, boundary, "long"
    ) is None


def test_btc_15m_full_bearish_stack_vetoes_long():
    from decimal import Decimal as D

    boundary = 1_800_000
    current_open = boundary - 900_000
    previous_open = boundary - 1_800_000
    current = {
        "bar": Bar(
            current_open,
            current_open + 900_000 - 1,
            D("100"),
            D("101"),
            D("96"),
            D("97"),
            D("10"),
        ),
        "count": 500,
        "ema20": D("98"),
        "ema50": D("99"),
    }
    previous = {
        "bar": SimpleNamespace(),
        "count": 499,
        "ema20": D("98.5"),
        "ema50": D("99.2"),
    }
    assert (
        btc_timing_reason(
            {current_open: current, previous_open: previous}, boundary, "long"
        )
        == "BTC_15M_TIMING_CONFLICT"
    )


def test_simulation_ranks_then_caps_same_direction_cluster_at_two():
    source = 10 * 3_600_000
    published = source + 3_600_000 + 1_000
    rows = [
        candidate("a", "AUSDT", "long", source, published, recent="1.3"),
        candidate("b", "BUSDT", "long", source, published + 1, recent="0.7", extension="0.8"),
        candidate("c", "CUSDT", "long", source, published + 2, recent="0.7", extension="0.4"),
        candidate("d", "DUSDT", "short", source, published + 3, recent="0.9"),
    ]

    simulate(rows)
    by_symbol = {row.symbol: row.final_reason for row in rows}

    assert by_symbol == {
        "AUSDT": "MARKET_DIRECTION_CONCENTRATION_LIMIT",
        "BUSDT": "WOULD_PUBLISH_V4",
        "CUSDT": "WOULD_PUBLISH_V4",
        "DUSDT": "WOULD_PUBLISH_V4",
    }


def test_simulation_suppresses_same_symbol_same_direction_for_session():
    first_source = 10 * 3_600_000
    rows = [
        candidate("a", "ETHUSDT", "long", first_source, first_source + 3_600_000 + 1_000),
        candidate(
            "b",
            "ETHUSDT",
            "long",
            first_source + 3_600_000,
            first_source + 2 * 3_600_000 + 1_000,
        ),
        candidate(
            "c",
            "ETHUSDT",
            "short",
            first_source + 3_600_000,
            first_source + 2 * 3_600_000 + 2_000,
        ),
    ]

    simulate(rows)

    assert rows[0].final_reason == "WOULD_PUBLISH_V4"
    assert rows[1].final_reason == "SAME_DIRECTION_SIGNAL_THIS_SESSION"
    assert rows[2].final_reason == "WOULD_PUBLISH_V4"


def test_simulation_circuit_breaker_pauses_only_deteriorating_direction():
    base = 10 * 3_600_000
    first_publish = base + 3_600_000 + 1_000
    second_publish = base + 2 * 3_600_000 + 1_000
    trigger_one = second_publish + 5 * 60_000
    trigger_two = second_publish + 10 * 60_000
    third_publish = base + 3 * 3_600_000 + 1_000

    rows = [
        candidate(
            "a",
            "ETHUSDT",
            "long",
            base,
            first_publish,
            adverse=trigger_one,
        ),
        candidate(
            "b",
            "SOLUSDT",
            "long",
            base + 3_600_000,
            second_publish,
            adverse=trigger_two,
        ),
        candidate(
            "c",
            "XRPUSDT",
            "long",
            base + 2 * 3_600_000,
            third_publish,
        ),
        candidate(
            "d",
            "ADAUSDT",
            "short",
            base + 2 * 3_600_000,
            third_publish + 1,
        ),
    ]

    simulate(rows)

    assert rows[0].final_reason == "WOULD_PUBLISH_V4"
    assert rows[1].final_reason == "WOULD_PUBLISH_V4"
    assert rows[2].final_reason == "DIRECTIONAL_CIRCUIT_BREAKER"
    assert rows[3].final_reason == "WOULD_PUBLISH_V4"


def test_circuit_events_report_trigger_pair_even_without_later_candidate():
    base = 10 * 3_600_000
    rows = [
        candidate(
            "a",
            "ETHUSDT",
            "long",
            base,
            base + 3_600_000 + 1_000,
            adverse=base + 4_000_000,
        ),
        candidate(
            "b",
            "SOLUSDT",
            "long",
            base + 3_600_000,
            base + 2 * 3_600_000 + 1_000,
            adverse=base + 2 * 3_600_000 + 600_000,
        ),
    ]
    simulate(rows)
    events = circuit_events(rows)
    assert len(events) == 1
    assert events[0]["direction"] == "long"
    assert [item["symbol"] for item in events[0]["signals"]] == [
        "ETHUSDT",
        "SOLUSDT",
    ]
    assert events[0]["pause_until"] > events[0]["triggered_at"]


def test_active_exposure_cap_allows_six_and_blocks_seventh():
    rows = []
    base = 10 * 3_600_000
    for index, symbol in enumerate(
        ("AUSDT", "BUSDT", "CUSDT", "DUSDT", "EUSDT", "FUSDT", "GUSDT")
    ):
        source = base + index * 3_600_000
        row = candidate(
            chr(97 + index),
            symbol,
            "long",
            source,
            source + 3_600_000 + 1_000,
        )
        row.v4_scaled_outcome = {
            "status": "open",
            "terminal_at": None,
            "favorable_050_at": None,
            "adverse_050_at": None,
        }
        rows.append(row)

    simulate_with_active_cap(rows)

    assert [row.capped_reason for row in rows[:6]] == [
        "WOULD_PUBLISH_V4"
    ] * 6
    assert rows[6].capped_reason == "ACTIVE_DIRECTIONAL_EXPOSURE_LIMIT"


def test_terminal_reference_frees_directional_exposure_capacity():
    rows = []
    base = 10 * 3_600_000
    for index, symbol in enumerate(
        ("AUSDT", "BUSDT", "CUSDT", "DUSDT", "EUSDT", "FUSDT")
    ):
        source = base + index * 3_600_000
        row = candidate(
            chr(97 + index),
            symbol,
            "long",
            source,
            source + 3_600_000 + 1_000,
        )
        row.v4_scaled_outcome = {
            "status": "open",
            "terminal_at": None,
            "favorable_050_at": None,
            "adverse_050_at": None,
        }
        rows.append(row)
    rows[0].v4_scaled_outcome["status"] = "protected_be"
    rows[0].v4_scaled_outcome["terminal_at"] = base + 7 * 3_600_000

    source = base + 7 * 3_600_000
    seventh = candidate("z", "GUSDT", "long", source, source + 3_600_000 + 1_000)
    seventh.v4_scaled_outcome = {
        "status": "open",
        "terminal_at": None,
        "favorable_050_at": None,
        "adverse_050_at": None,
    }
    rows.append(seventh)

    simulate_with_active_cap(rows)

    assert rows[-1].capped_reason == "WOULD_PUBLISH_V4"


def test_preliminary_veto_never_consumes_cluster_capacity():
    source = 10 * 3_600_000
    published = source + 3_600_000 + 1_000
    rows = [
        candidate(
            "a",
            "AUSDT",
            "long",
            source,
            published,
            recent="0.1",
            preliminary="BTC_15M_TIMING_CONFLICT",
        ),
        candidate("b", "BUSDT", "long", source, published + 1, recent="0.2"),
        candidate("c", "CUSDT", "long", source, published + 2, recent="0.3"),
    ]

    simulate(rows)

    assert [row.final_reason for row in rows] == [
        "BTC_15M_TIMING_CONFLICT",
        "WOULD_PUBLISH_V4",
        "WOULD_PUBLISH_V4",
    ]


def test_scaled_retrospective_replays_v4_tp1_then_break_even_protection():
    import asyncio

    class Public:
        async def get(self, path, **params):
            assert path == "/fapi/v1/klines"
            return [
                [
                    60_000,
                    "100",
                    "102.10",
                    "99.80",
                    "101.50",
                    "10",
                    119_999,
                ],
                [
                    120_000,
                    "101.50",
                    "101.70",
                    "99.90",
                    "100.10",
                    "10",
                    179_999,
                ],
            ]

    row = candidate("x", "BTCUSDT", "long", 0, 1_000)
    row.historical_last_minute_open_time = 120_000
    row.v4_plan = {
        "entry": "100",
        "stop": "98",
        "risk_distance": "2",
        "tp1": "102",
        "tp2": "103",
        "tp3": "104",
        "tp1_r": "1",
        "tp2_r": "1.5",
        "tp3_r": "2",
    }
    result = asyncio.run(scaled_outcome(Public(), row))
    assert result["status"] == "protected_be"
    assert result["conservative_r"] == "0.30"
    assert result["tp1_reached"] is True
    assert result["tp2_reached"] is False
    assert result["observed_bars"] == 2


def test_portfolio_health_reports_only_prior_open_same_direction_signals():
    from decimal import Decimal as D
    from app.analytics.service import MinuteBar

    boundary = 300_000
    prior = candidate("p", "ETHUSDT", "long", 0, 1_000)
    prior.v4_plan = {
        "entry": "100",
        "stop": "98",
        "risk_distance": "2",
        "tp1": "102",
        "tp2": "103",
        "tp3": "104",
        "tp1_r": "1",
        "tp2_r": "1.5",
        "tp3_r": "2",
    }
    future = candidate("f", "SOLUSDT", "long", 0, boundary + 1_000)
    future.v4_plan = prior.v4_plan.copy()
    short = candidate("s", "XRPUSDT", "short", 0, 1_000)
    short.v4_plan = {
        "entry": "100",
        "stop": "102",
        "risk_distance": "2",
        "tp1": "98",
        "tp2": "97",
        "tp3": "96",
        "tp1_r": "1",
        "tp2_r": "1.5",
        "tp3_r": "2",
    }
    bars = [
        MinuteBar(60_000, 119_999, D("100"), D("100.2"), D("99.2"), D("99.4"), D("1")),
        MinuteBar(120_000, 179_999, D("99.4"), D("99.5"), D("98.9"), D("99.0"), D("1")),
        MinuteBar(180_000, 239_999, D("99.0"), D("99.1"), D("98.8"), D("99.0"), D("1")),
    ]
    health = portfolio_health_at(
        [prior, future, short],
        {"p": bars, "f": bars, "s": bars},
        boundary,
    )
    assert health["long"]["active_count"] == 1
    assert health["long"]["below_entry_count"] == 1
    assert health["long"]["at_or_below_minus_025_count"] == 1
    assert health["long"]["at_or_below_minus_050_count"] == 1
    assert health["long"]["average_mark_r"] == "-0.5"
    assert health["long"]["signals"][0]["symbol"] == "ETHUSDT"
    assert health["short"]["active_count"] == 1
    assert health["short"]["below_entry_count"] == 0

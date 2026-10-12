"""V7Sonic strict paper sizing tests, offline/no account or exchange I/O."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal as D
from unittest import TestCase
import json

from services.t7sonic.forward_risk_gate import (
    strict_execution_rules, paper_position_sizing,
)
from test_t7sonic_release_candidate import breakout, quote
from app.research.t7sonic_release_candidate import indicative_plan
from test_t7sonic_forward_live_quote import info_market, contract_data


def venue_fixture(symbol="BTCUSDT", *, min_notional="5"):
    market=info_market(symbol)
    market["filters"] += [
        {"filterType":"MARKET_LOT_SIZE","minQty":"0.001",
         "maxQty":"100000","stepSize":"0.001"},
        {"filterType":"MIN_NOTIONAL","notional":min_notional},
    ]
    return contract_data([market])


def account(**overrides):
    base={
        "equity_usdt":"1000",
        "reserved_loss_usdt":"0",
        "gross_open_notional_usdt":"0",
        "open_positions":0,
        "already_active_symbols":[],
        "fee_bps_per_side":"4",
        "slippage_bps_per_side":"4",
        "funding_buffer_bps":"2",
    }
    base.update(overrides)
    return base


def prepared():
    plan=indicative_plan(breakout(),quote())
    rule=strict_execution_rules(venue_fixture(),plan["symbol"])
    return plan,rule


class StrictSizingTests(TestCase):
    def test_nominal_plan_is_bounded_by_all_four_cap_classes(self):
        plan,rule=prepared()
        sized=paper_position_sizing(plan,rule,account())
        self.assertEqual(sized["status"],
                         "SIZED_INTERNAL_PAPER_ONLY_NEVER_EXECUTE")
        qty=D(sized["quantity"])
        self.assertEqual(qty%D(rule["lot_size_step"]),0)
        self.assertGreaterEqual(qty,D(rule["min_quantity"]))
        self.assertGreaterEqual(
            qty*D(plan["entry"]),D(rule["minimum_notional_usdt"])
        )
        self.assertLessEqual(D(sized["worst_case_stopped_loss_usdt"]),D("5"))
        self.assertLessEqual(D(sized["portfolio_risk_after_pct"]),D("0.5"))
        self.assertLessEqual(D(sized["notional_usdt"]),D("2000"))
        self.assertFalse(sized["exchange_orders_submitted"])
        self.assertFalse(sized["client_signal_publication_authorized"])
        self.assertFalse(sized["equity_or_positions_authenticated"])
        self.assertFalse(sized["futures_leverage_configured"])
        self.assertEqual(sized,paper_position_sizing(*prepared(),account()))

    def test_strict_symbol_filters_enforce_real_min_notional_field(self):
        rules=strict_execution_rules(venue_fixture(), "BTCUSDT")
        self.assertEqual(rules["minimum_notional_usdt"],"5")
        self.assertEqual(rules["market_step"],"0.001")
        self.assertTrue(rules["execution_rules_complete"])
        self.assertFalse(rules["contract_rules_independently_attested"])
        for missing in ("MARKET_LOT_SIZE","MIN_NOTIONAL"):
            d=json.loads(venue_fixture())
            d["symbols"][0]["filters"]=[
                f for f in d["symbols"][0]["filters"]
                if f["filterType"]!=missing
            ]
            with self.subTest(missing=missing),self.assertRaises(ValueError):
                strict_execution_rules(json.dumps(d).encode(),"BTCUSDT")

    def test_zero_or_unrealistically_low_account_cannot_override_minimum_notional(self):
        plan,rule=prepared()
        for equity in ("10","15","30"):
            result=paper_position_sizing(plan,rule,
                                         account(equity_usdt=equity))
            self.assertEqual(result["status"],"NO_PAPER_POSITION")
            self.assertEqual(result["reason"],
                             "QTY_OR_MIN_NOTIONAL_UNSATISFIABLE")

    def test_explicit_positions_and_aggregate_risk_limit(self):
        plan,rule=prepared()
        symbol_locked=paper_position_sizing(
            plan,rule,
            account(open_positions=1,already_active_symbols=["BTCUSDT"])
        )
        self.assertEqual(symbol_locked["reason"],"MARKET_SLOT_ALREADY_ACTIVE")
        locked=paper_position_sizing(
            plan,rule,
            account(open_positions=4,
                    already_active_symbols=[
                        "ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT"
                    ])
        )
        self.assertEqual(locked["reason"],"OPEN_POSITION_LIMIT")
        exhausted=paper_position_sizing(
            plan,rule,account(reserved_loss_usdt="20")
        )
        self.assertEqual(exhausted["reason"],"PORTFOLIO_BUDGET_EXHAUSTED")
        modified=paper_position_sizing(
            plan,rule,
            account(reserved_loss_usdt="19.4",
                    gross_open_notional_usdt="500",
                    open_positions=1,
                    already_active_symbols=["SOLUSDT"])
        )
        self.assertLessEqual(
            D(modified.get("worst_case_stopped_loss_usdt","0")),D("0.6")
        )
        self.assertNotEqual(modified["status"],
                            "SIZED_INTERNAL_PAPER_ONLY_NEVER_EXECUTE")

    def test_oversized_exposure_and_cost_unknown_cannot_pass(self):
        plan,rule=prepared()
        bad=[
            {"reserved_loss_usdt":"25"},
            {"gross_open_notional_usdt":"2500"},
            {"fee_bps_per_side":"1"},
            {"slippage_bps_per_side":"1"},
            {"funding_buffer_bps":"0.01"},
            {"funding_buffer_bps":"NaN"},
            {"already_active_symbols":["FAKE"]},
            {"open_positions":True},
            {"open_positions":2},
            {"equity_usdt":"0"},
        ]
        for overrides in bad:
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):
                paper_position_sizing(plan,rule,account(**overrides))

    def test_candidate_prices_and_digest_cannot_be_mutated(self):
        plan,rule=prepared()
        cases=[
            ("entry","103.2"),
            ("max_equity_risk_percent","5"),
            ("status","ACTIONABLE"),
            ("publishable_signal",True),
            ("funding_and_execution_impact_not_verified",False),
            ("lot_size_and_notional_verified",True),
            ("candidate_sha256","f"*64),
        ]
        for key,value in cases:
            altered=deepcopy(plan)
            altered[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                paper_position_sizing(altered,rule,account())

    def test_bad_contracts_and_unsupported_quantity_geometry_fail_closed(self):
        plan,rule=prepared()
        for key,value in (
            ("symbol","SOLUSDT"),
            ("execution_rules_complete",False),
            ("live_order_authorized",True),
            ("contract_rules_independently_attested",True),
            ("source_status","AUTHENTICATED"),
        ):
            bad=deepcopy(rule)
            bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                paper_position_sizing(plan,bad,account())
        bad=deepcopy(rule)
        bad["market_step"]="0.002"
        with self.assertRaises(ValueError):
            paper_position_sizing(plan,bad,account())
        bad=deepcopy(rule)
        bad["max_price"]="102"
        refused=paper_position_sizing(plan,bad,account())
        self.assertEqual(refused["reason"],"PRICE_FILTER_REJECTED")

    def test_sizing_proposal_remains_paper_even_with_large_equity(self):
        plan,rule=prepared()
        result=paper_position_sizing(
            plan,rule,account(equity_usdt="1000000")
        )
        self.assertEqual(result["status"],
                         "SIZED_INTERNAL_PAPER_ONLY_NEVER_EXECUTE")
        self.assertFalse(result["actual_exchange_fill_verified"])
        self.assertFalse(result["client_signal_publication_authorized"])


if __name__=="__main__":
    import unittest
    unittest.main()

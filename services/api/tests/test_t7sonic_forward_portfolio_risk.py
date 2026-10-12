"""Six-market paper portfolio sizing, with no Binance account/network."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal as D
from unittest import TestCase

from app.research.t7sonic_validation_plan import MARKETS
from app.research.t7sonic_release_preview import build_offline_preview
from services.t7sonic.forward_portfolio_risk import (
    review_six_market_paper_risk,
)
from services.t7sonic.forward_risk_gate import strict_execution_rules
from test_t7sonic_forward_risk_gate import venue_fixture, account
from test_t7sonic_release_preview import group


def full_review(**override):
    markets,quotes=group()
    preview=build_offline_preview(markets,quotes)
    venue={s:strict_execution_rules(venue_fixture(s),s) for s in MARKETS}
    a=account(**override)
    return preview,venue,a


class PortfolioRiskReviewTests(TestCase):
    def test_six_candidate_positions_rejected_after_four_slots(self):
        preview,venues,state=full_review()
        r=review_six_market_paper_risk(
            preview,rules_by_symbol=venues,paper_account=state
        )
        self.assertEqual(r["markets_evaluated"],6)
        self.assertEqual(r["candidate_count"],6)
        self.assertEqual(r["paper_sized_count"],4)
        self.assertEqual(r["paper_open_slots_after"],4)
        self.assertEqual(len(r["reviews"]),6)
        self.assertTrue(all(
            x["status"]=="NO_PAPER_POSITION" and
            x["reason"]=="OPEN_POSITION_LIMIT" for x in r["reviews"][4:]
        ))
        self.assertLessEqual(
            D(r["paper_reserved_risk_after_usdt"]),D("20")
        )
        self.assertLessEqual(
            D(r["paper_total_gross_notional_after_usdt"]),D("2000")
        )
        self.assertFalse(r["client_publication_authorized"])
        self.assertFalse(r["real_money_order_submission_authorized"])
        self.assertEqual(r["telegram_messages_sent"],0)
        self.assertEqual(
            r,review_six_market_paper_risk(
                preview,rules_by_symbol=venues,paper_account=state
            )
        )

    def test_missing_or_wrong_venue_source_aborts_everything(self):
        preview,venues,state=full_review()
        cases=[deepcopy(venues),deepcopy(venues)]
        cases[0].pop("BTCUSDT")
        cases[1]["XRPUSDT"]["symbol"]="SOLUSDT"
        for i,venue in enumerate(cases):
            with self.subTest(i=i),self.assertRaises(ValueError):
                review_six_market_paper_risk(
                    preview,rules_by_symbol=venue,paper_account=state
                )

    def test_existing_account_risk_is_respected_without_updating_user_snapshot(self):
        preview,venues,state=full_review(
            reserved_loss_usdt="19.4",
            gross_open_notional_usdt="800",
            open_positions=2,
            already_active_symbols=["SOLUSDT","ETHUSDT"],
        )
        before=deepcopy(state)
        out=review_six_market_paper_risk(
            preview,rules_by_symbol=venues,paper_account=state
        )
        self.assertEqual(state,before)
        self.assertEqual(out["markets_evaluated"],6)
        self.assertLessEqual(D(out["paper_reserved_risk_after_usdt"]),D("20"))
        self.assertLessEqual(out["paper_open_slots_after"],4)

    def test_explicit_abstain_does_not_consume_risk_slot(self):
        markets,quotes=group()
        preview=build_offline_preview(
            markets,quotes,active_symbols=("BTCUSDT",)
        )
        _,venues,state=full_review()
        state["open_positions"]=1
        state["already_active_symbols"]=["BTCUSDT"]
        out=review_six_market_paper_risk(
            preview,rules_by_symbol=venues,paper_account=state
        )
        self.assertEqual(out["reviews"][0]["status"],"NO_PAPER_POSITION")
        self.assertEqual(out["reviews"][0]["reason"],"ACTIVE_POSITION_LOCK")
        self.assertFalse(out["reviews"][0]["client_publication_authorized"])
        self.assertLessEqual(out["paper_open_slots_after"],4)

    def test_source_batch_tamper_is_rejected(self):
        preview,venues,state=full_review()
        for key, val in (
            ("batch_sha256","f"*64),
            ("client_publication_authorized",True),
            ("telegram_enqueued",True),
            ("decision_records",[]),
        ):
            amended=deepcopy(preview)
            amended[key]=val
            with self.subTest(key=key),self.assertRaises(ValueError):
                review_six_market_paper_risk(
                    amended,rules_by_symbol=venues,paper_account=state
                )


if __name__=="__main__":
    import unittest
    unittest.main()

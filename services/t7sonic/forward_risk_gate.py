"""V7Sonic EXECUTION-RULES AND PORTFOLIO PAPER RISK VETO.

This is a deterministic, zero-I/O fail-closed CHECK, not a trade order.
Entry, stop, targets and candidate digest must match frozen V7Sonic
paper plans. Uses FULL Binance USD-M exchangeInfo rules for LIMIT
LOT_SIZE and MARKET_LOT_SIZE, MIN_NOTIONAL, true price tick and
position quantity. A plan is UNSIZEABLE if any required venue field
is unknown. Never auto-adjust an exchange-order price.

Position size is capped by all of:
  * 0.5% equity at stop INCLUDING conservative roundtrip costs;
  * 2% aggregate equity stop-risk including currently reserved risk;
  * four maximum concurrent market slots;
  * 2x gross paper notional including existing exposure;
  * valid venue quantity, min-notional, and price limits.
No source actually verifies wallet equity, positions, margin, mark price,
funding, exchange order fills, or the performance of the chosen expert.
No live trade, Telegram send, DB, network, leverage command or worker.
"""
from __future__ import annotations

from decimal import Decimal as D, ROUND_FLOOR
from hashlib import sha256
import json

from app.research.t7sonic_perception import decimal_number
from app.research.t7sonic_validation_plan import MARKETS
from app.research.t7sonic_release_candidate import POLICY
from services.t7sonic.forward_live_quote import extract_contract_rule

MAX_RISK_PER_POSITION = D("0.005")
MAX_AGGREGATE_RISK = D("0.02")
MAX_GROSS_NOTIONAL_MULTIPLE = D("2")
MAX_OPEN_POSITIONS = 4
MIN_TOTAL_FEE_BPS_PER_SIDE = D("4")
MIN_SLIP_BPS_PER_SIDE = D("4")
MIN_FUNDING_BUFFER_BPS = D("2")
_EXPECTED_STATUS = "PAPER_INDICATIVE_UNVERIFIED_NOT_FOR_CLIENT_PUBLICATION"


def _pos(obj: dict, field: str, *, zero_allowed=False) -> D:
    if field not in obj or not isinstance(obj[field],str):
        raise ValueError("Explicit decimal string required for "+field)
    val=decimal_number(obj[field],field)
    if val < 0 or (val == 0 and not zero_allowed):
        raise ValueError("Negative/zero "+field)
    return val


def _fmt(value: D) -> str:
    return format(value.normalize(),"f")


def _filter(filters: list, filter_name: str) -> dict:
    matched=[x for x in filters if isinstance(x,dict)
             and x.get("filterType")==filter_name]
    if len(matched)!=1:
        raise ValueError("Exact Binance venue "+filter_name+" filter required")
    return matched[0]


def strict_execution_rules(raw: bytes, symbol: str) -> dict:
    """Extract mandatory LIMIT, MARKET, notional and tick restrictions.

    If actual exchangeInfo does not expose a mandatory filter, trading
    is NOT approved. Requirements can only be changed via reviewed code.
    """
    common=extract_contract_rule(raw,symbol)
    try:
        payload=json.loads(raw)
    except (ValueError,UnicodeDecodeError) as exc:
        raise ValueError("Invalid exchange source") from exc
    matches=[x for x in payload["symbols"]
             if isinstance(x,dict) and x.get("symbol")==symbol]
    if len(matches)!=1:
        raise ValueError("Duplicate/missing contract")
    filters=matches[0]["filters"]
    market=_filter(filters,"MARKET_LOT_SIZE")
    min_notional=_filter(filters,"MIN_NOTIONAL")
    # Binance USD-M MIN_NOTIONAL exposes 'notional'. Reject unsupported
    # metadata instead of silently inventing 5 USDT.
    market_min=_pos(market,"minQty")
    market_max=_pos(market,"maxQty")
    market_step=_pos(market,"stepSize")
    required_notional=_pos(min_notional,"notional")
    limit_min=D(common["min_quantity"])
    limit_max=D(common["max_quantity"])
    limit_step=D(common["lot_size_step"])
    if (market_min > market_max or market_step > market_max or
            market_step != limit_step or
            (market_min / market_step) % 1 or
            (limit_min / limit_step) % 1):
        raise ValueError("Unsupported/incompatible venue quantity increments")
    return {
        **common,
        "market_min_quantity":_fmt(market_min),
        "market_max_quantity":_fmt(market_max),
        "market_step":_fmt(market_step),
        "minimum_notional_usdt":_fmt(required_notional),
        "execution_rules_complete":True,
        "contract_rules_independently_attested":False,
        "live_order_authorized":False,
    }


def paper_position_sizing(plan: dict, rules: dict, account: dict) -> dict:
    """Return conditional paper *quantity* or an explicit refusal.

    IMPORTANT: All account fields are explicitly injected test claims.
    The return value is not a genuine account check, executable order,
    or operator permission. No uncertainty is hidden by defaults.
    """
    if (not isinstance(plan,dict) or not isinstance(rules,dict)
            or not isinstance(account,dict)):
        raise ValueError("Exact paper plan, venue and account fields required")
    if (plan.get("policy") != POLICY or
            plan.get("status") != _EXPECTED_STATUS or
            plan.get("publishable_signal") is not False or
            plan.get("executable_order") is not False or
            plan.get("lot_size_and_notional_verified") is not False or
            plan.get("funding_and_execution_impact_not_verified") is not True):
        raise ValueError("Not a valid unapproved paper candidate")
    if (not isinstance(plan.get("candidate_sha256"),str) or
            sha256(json.dumps(
                {k:v for k,v in plan.items() if k!="candidate_sha256"},
                sort_keys=True,separators=(",",":"),
            ).encode()).hexdigest()!=plan["candidate_sha256"]):
        raise ValueError("Candidate price/risk changed after sealed plan")
    symbol=plan.get("symbol")
    if symbol not in MARKETS or rules.get("symbol")!=symbol or (
        rules.get("execution_rules_complete") is not True or
        rules.get("live_order_authorized") is not False or
        rules.get("contract_rules_independently_attested") is not False or
        rules.get("source_status") != "UNATTESTED_EXCHANGEINFO_FORMAT_VALID"
    ):
        raise ValueError("Unverified or unapproved venue filters")
    keys={
        "equity_usdt","reserved_loss_usdt","gross_open_notional_usdt",
        "open_positions","already_active_symbols",
        "fee_bps_per_side","slippage_bps_per_side",
        "funding_buffer_bps",
    }
    if set(account)!=keys:
        raise ValueError("Full explicit paper account snapshot required")
    if (type(account["open_positions"]) is not int or
            not 0 <= account["open_positions"] <= MAX_OPEN_POSITIONS or
            not isinstance(account["already_active_symbols"],list) or
            len(set(account["already_active_symbols"])) !=
            len(account["already_active_symbols"]) or
            len(account["already_active_symbols"]) != account["open_positions"] or
            any(x not in MARKETS for x in account["already_active_symbols"])):
        raise ValueError("Malformed paper position locks")
    equity=_pos(account,"equity_usdt")
    existing_loss=_pos(account,"reserved_loss_usdt",zero_allowed=True)
    existing_notional=_pos(account,"gross_open_notional_usdt",zero_allowed=True)
    fees=_pos(account,"fee_bps_per_side")
    slip=_pos(account,"slippage_bps_per_side")
    funding=_pos(account,"funding_buffer_bps")
    if (fees < MIN_TOTAL_FEE_BPS_PER_SIDE or
            slip < MIN_SLIP_BPS_PER_SIDE or
            funding < MIN_FUNDING_BUFFER_BPS or
            existing_loss > equity*MAX_AGGREGATE_RISK or
            existing_notional > equity*MAX_GROSS_NOTIONAL_MULTIPLE):
        raise ValueError("Unrealistic cost or exceeded existing portfolio limits")

    common={
        "schema":1,
        "status":"NO_PAPER_POSITION",
        "symbol":symbol,
        "candidate_id":plan["candidate_id"],
        "plan_sha256":plan["candidate_sha256"],
        "contract_sha256":rules["contract_source_sha256"],
        "equity_or_positions_authenticated":False,
        "exchange_orders_submitted":False,
        "client_signal_publication_authorized":False,
        "futures_leverage_configured":False,
        "actual_exchange_fill_verified":False,
    }
    if symbol in account["already_active_symbols"]:
        return {**common,"reason":"MARKET_SLOT_ALREADY_ACTIVE"}
    if account["open_positions"] >= MAX_OPEN_POSITIONS:
        return {**common,"reason":"OPEN_POSITION_LIMIT"}
    entry=_pos(plan,"entry")
    stop=_pos(plan,"stop_loss")
    tp1=_pos(plan,"take_profit_1")
    tp2=_pos(plan,"take_profit_2")
    tick=_pos(rules,"tick_size")
    bottom=_pos(rules,"min_price")
    top=_pos(rules,"max_price")
    step=_pos(rules,"lot_size_step")
    minimum=_pos(rules,"min_quantity")
    maximum=_pos(rules,"max_quantity")
    market_min=_pos(rules,"market_min_quantity")
    market_max=_pos(rules,"market_max_quantity")
    market_step=_pos(rules,"market_step")
    notional_min=_pos(rules,"minimum_notional_usdt")
    if step!=market_step or bottom>=top or minimum>maximum or market_min>market_max:
        raise ValueError("Inconsistent venue quantity/price rules")
    if any(p < bottom or p > top or (p-bottom)%tick
           for p in (entry,stop,tp1,tp2)):
        return {**common,"reason":"PRICE_FILTER_REJECTED"}
    direction=plan.get("direction")
    if direction=="LONG":
        valid=stop < entry < tp1 < tp2
    elif direction=="SHORT":
        valid=tp2 < tp1 < entry < stop
    else:
        raise ValueError("Invalid plan direction")
    if not valid:
        raise ValueError("Risk/target geometry inconsistent")
    if _pos(plan,"max_equity_risk_percent") != D("0.5"):
        raise ValueError("Unreviewed plan risk ceiling")

    # Conservative worst-case entry plus stopped exit with transaction
    # fees, slippage and an explicitly supplied funding reserve.
    worst_cost=(entry+stop)*(fees+slip)/D("10000")
    worst_cost += entry*funding/D("10000")
    loss_per_unit=abs(entry-stop)+worst_cost
    budget=min(equity*MAX_RISK_PER_POSITION,
               equity*MAX_AGGREGATE_RISK-existing_loss)
    max_new_notional=(
        equity*MAX_GROSS_NOTIONAL_MULTIPLE-existing_notional
    )
    if budget <= 0 or max_new_notional <= 0:
        return {**common,"reason":"PORTFOLIO_BUDGET_EXHAUSTED"}
    raw_qty=min(
        budget/loss_per_unit,max_new_notional/entry,
        minimum*D("1000000000000"),
        maximum,market_max,
    )
    # Floor to exact exchange step, never upsize to the minimum.
    quantity=(raw_qty/step).to_integral_value(rounding=ROUND_FLOOR)*step
    if (quantity < max(minimum,market_min) or
            quantity%step or quantity%market_step or
            quantity*entry < notional_min):
        return {**common,"reason":"QTY_OR_MIN_NOTIONAL_UNSATISFIABLE"}
    risk_used=quantity*loss_per_unit
    notional=quantity*entry
    if (risk_used > budget or
            risk_used+existing_loss > equity*MAX_AGGREGATE_RISK or
            risk_used > equity*MAX_RISK_PER_POSITION or
            existing_notional+notional >
            equity*MAX_GROSS_NOTIONAL_MULTIPLE):
        raise ValueError("Internal calculated risk budget exceeded")

    return {
        **common,
        "status":"SIZED_INTERNAL_PAPER_ONLY_NEVER_EXECUTE",
        "quantity":_fmt(quantity),
        "notional_usdt":_fmt(notional),
        "worst_case_stopped_loss_usdt":_fmt(risk_used),
        "estimated_loss_per_unit_including_cost_buffer":_fmt(loss_per_unit),
        "account_risk_budget_usdt":_fmt(budget),
        "fraction_equity_at_stop_pct":_fmt(risk_used/equity*100),
        "portfolio_risk_after_pct":_fmt(
            (existing_loss+risk_used)/equity*100
        ),
        "fee_bps_per_side":_fmt(fees),
        "slippage_bps_per_side":_fmt(slip),
        "funding_buffer_bps":_fmt(funding),
        "paper_only":True,
    }

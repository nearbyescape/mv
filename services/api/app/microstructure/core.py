"""V7Sonic microstructure evidence contract and unpromoted paper classifier.

No network, DB, broker or Telegram imports. The rules are an unvalidated
hypothesis, NOT a trained probability model or evidence of profitability.
Timestamps are in milliseconds and exact Decimal quantities are kept as text.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal as D, InvalidOperation
from hashlib import sha256
import json
import re

SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","BNBUSDT")
PERIOD_MS=300_000
HORIZONS_MS=(900_000,1_800_000,3_600_000,7_200_000)
MODEL="V7S_MICROSTRUCTURE_OBSERVATION_V1"
PARAMETERS={
    "minimum_interval_ms":300_000,
    "maximum_interval_ms":1_200_000,
    "maximum_snapshot_age_ms":30_000,
    "maximum_taker_data_age_ms":900_000,
    "minimum_open_interest_increase_pct": "0.20",
    "maximum_open_interest_jump_pct": "5.00",
    "minimum_taker_buy_sell_ratio_for_long":"1.25",
    "maximum_taker_buy_sell_ratio_for_short":"0.80",
    "minimum_book_imbalance_abs":"0.10",
    "maximum_spread_bps":"5",
    "maximum_book_impact_bps":"4",
    "maximum_abs_funding_rate":"0.001",
    "minimum_cost_adjusted_target_R":"1.10",
    "gross_target_R":"1.80",
    "stop_distance_pct":"0.75",
    "per_side_fee_slippage_bps":"8",
    "reference_notional_usdt":"1000",
    "session_ist":"09:00-23:00",
    "max_active_paper_ideas":4,
    "same_symbol_cooldown_ms":10_800_000,
}
POLICY_SHA=sha256(json.dumps(PARAMETERS,sort_keys=True,separators=(",",":")).encode()).hexdigest()
IST=timezone(timedelta(hours=5,minutes=30))


def dec(value, *, positive=False, allow_zero=False):
    if not isinstance(value,str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?",value):
        raise ValueError("Expected a plain nonnegative decimal string")
    try:
        out=D(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not out.is_finite() or (positive and out <= 0) or (
        not positive and not allow_zero and out < 0
    ):
        raise ValueError("Invalid positive decimal condition")
    return out


def number(value):
    return str(value)


def canonical(payload):
    return json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=True)


def digest(payload):
    return sha256(canonical(payload).encode()).hexdigest()


def _pairs(rows, *, bid):
    if not isinstance(rows,list) or len(rows)<5 or len(rows)>100:
        raise ValueError("Depth needs 5–100 levels per side")
    result=[]
    for item in rows:
        if not isinstance(item,list) or len(item)!=2:
            raise ValueError("Malformed depth level")
        price,volume=dec(item[0],positive=True),dec(item[1],positive=True)
        result.append((price,volume))
    if len({p for p,v in result})!=len(result):
        raise ValueError("Duplicate depth level")
    result.sort(key=lambda x:x[0],reverse=bid)
    return result


def _impact(book,notional,*,side):
    """Walk immediately visible liquidity; excludes hidden orders and latency."""
    budget=notional
    filled=D(0)
    cost=D(0)
    for price,qty in book:
        take=min(qty,budget/price)
        filled+=take
        cost+=take*price
        budget-=take*price
        if budget<=D("0.000000001"):
            break
    if budget>D("0.000000001") or filled<=0:
        raise ValueError("Insufficient observed top-20 visible liquidity")
    vwap=cost/filled
    touch=book[0][0]
    return (abs(vwap-touch)/touch)*D(10000)


def normalize(symbol, raw, observed_ms, *, started_ms):
    """Normalize five fixed-origin public endpoint responses.

    REST book depth and ticker events are *not* synchronized. Reject a capture
    taking longer than 8 seconds. Depth offers local receive-time only; this
    does not claim a fully synchronized exchange book or executable fill.
    """
    if symbol not in SYMBOLS:
        raise ValueError("Unsupported research symbol")
    if type(observed_ms)!=int or type(started_ms)!=int or observed_ms<started_ms or observed_ms-started_ms>8000:
        raise ValueError("Stale/malformed public capture duration")
    if set(raw)!={"server_time","depth","open_interest","taker","premium"}:
        raise ValueError("Five exact public market inputs are required")
    server=raw["server_time"]
    if type(server.get("serverTime"))!=int or abs(server["serverTime"]-observed_ms)>5000:
        raise ValueError("Clock skew; cannot certify time")
    depth=raw["depth"]
    if type(depth.get("lastUpdateId"))!=int or depth["lastUpdateId"]<1:
        raise ValueError("Missing book snapshot update ID")
    bids=_pairs(depth.get("bids"),bid=True)
    asks=_pairs(depth.get("asks"),bid=False)
    bid,ask=bids[0][0],asks[0][0]
    if bid>=ask:
        raise ValueError("Crossed or locked book")
    mid=(bid+ask)/2
    spread_bps=(ask-bid)/mid*10000
    top=10
    b_liq=sum((p*v for p,v in bids[:top]),D(0))
    a_liq=sum((p*v for p,v in asks[:top]),D(0))
    imbalance=(b_liq-a_liq)/(b_liq+a_liq)
    notional=D(PARAMETERS["reference_notional_usdt"])
    impact_buy=_impact(asks,notional,side="buy")
    impact_sell=_impact(bids,notional,side="sell")

    oi=raw["open_interest"]
    if oi.get("symbol")!=symbol or type(oi.get("time"))!=int or not 0<=observed_ms-oi["time"]<=30_000:
        raise ValueError("Old or mismatched open interest")
    current_oi=dec(oi.get("openInterest"),positive=True)

    premium=raw["premium"]
    if premium.get("symbol")!=symbol or type(premium.get("time"))!=int or not 0<=observed_ms-premium["time"]<=30_000:
        raise ValueError("Old or mismatched premium mark")
    mark=dec(premium.get("markPrice"),positive=True)
    funding=D(premium.get("lastFundingRate")) if re.fullmatch(
        r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?",str(premium.get("lastFundingRate"))
    ) else None
    if funding is None or not funding.is_finite():
        raise ValueError("Invalid funding")
    if abs(mark-mid)/mid*10_000>D(50):
        raise ValueError("Mark and reference book diverged materially")

    taker=raw["taker"]
    if not isinstance(taker,list) or len(taker)<1:
        raise ValueError("No taker activity period")
    completed=[]
    for row in taker:
        timestamp=row.get("timestamp")
        if type(timestamp)!=int or timestamp%PERIOD_MS!=0:
            raise ValueError("Bad taker 5m period")
        if timestamp+PERIOD_MS<=server["serverTime"]:
            completed.append(row)
    if not completed:
        raise ValueError("No completed exchange taker period")
    last=max(completed,key=lambda x:x["timestamp"])
    if not 0<=observed_ms-(last["timestamp"]+PERIOD_MS)<=PARAMETERS["maximum_taker_data_age_ms"]:
        raise ValueError("Taker data are stale")
    buy_vol=dec(last.get("buyVol"),positive=True)
    sell_vol=dec(last.get("sellVol"),positive=True)
    ratio=buy_vol/sell_vol
    return {
        "version":1,"symbol":symbol,"observed_at_ms":observed_ms,
        "capture_started_ms":started_ms,"exchange_server_ms":server["serverTime"],
        "depth_last_update_id":depth["lastUpdateId"],
        "bid":number(bid),"ask":number(ask),"mid":number(mid),
        "bid_qty_top10_quote":number(b_liq),"ask_qty_top10_quote":number(a_liq),
        "spread_bps":number(spread_bps),"book_imbalance":number(imbalance),
        "buy_impact_bps":number(impact_buy),"sell_impact_bps":number(impact_sell),
        "open_interest":number(current_oi),"open_interest_exchange_ms":oi["time"],
        "taker_period_start_ms":last["timestamp"],
        "taker_buy":number(buy_vol),"taker_sell":number(sell_vol),
        "taker_ratio":number(ratio),"mark":number(mark),
        "premium_exchange_ms":premium["time"],"funding_rate":number(funding),
        "depth_consistency":"REST_POINT_SNAPSHOT_NOT_SEQUENCE_PROVED",
        "execution_price":"UNVERIFIED",
        "eligible_for_live_trades":False,
    }


def classify(previous,current):
    """Causal paper hypothesis; return a candidate or an explicit abstention.

    This does NOT estimate P(win). It is *not* a profitability certificate.
    """
    def abstain(reason):
        return {"status":"ABSTAIN","reason":reason,"paper_only":True}
    if previous["symbol"]!=current["symbol"] or current["symbol"] not in SYMBOLS:
        return abstain("SYMBOL_MISMATCH")
    duration=current["observed_at_ms"]-previous["observed_at_ms"]
    if not PARAMETERS["minimum_interval_ms"]<=duration<=PARAMETERS["maximum_interval_ms"]:
        return abstain("NONCONTIGUOUS_OBSERVATIONS")
    if current["taker_period_start_ms"]<=previous["taker_period_start_ms"]:
        return abstain("STALE_TAKER_PERIOD")
    if current["depth_last_update_id"]<=previous["depth_last_update_id"]:
        return abstain("STALE_DEPTH")
    at=current["observed_at_ms"]
    local=datetime.fromtimestamp(at/1000,IST)
    if not 9<=local.hour<23:
        return abstain("OUTSIDE_SIGNAL_SESSION")
    spread=dec(current["spread_bps"],allow_zero=True)
    if spread>D(PARAMETERS["maximum_spread_bps"]):
        return abstain("SPREAD_TOO_WIDE")
    funding=D(current["funding_rate"])
    if abs(funding)>D(PARAMETERS["maximum_abs_funding_rate"]):
        return abstain("EXTREME_FUNDING")
    old_oi=dec(previous["open_interest"],positive=True)
    new_oi=dec(current["open_interest"],positive=True)
    oi_change_pct=(new_oi-old_oi)/old_oi*100
    if not D(PARAMETERS["minimum_open_interest_increase_pct"])<=oi_change_pct<=D(PARAMETERS["maximum_open_interest_jump_pct"]):
        return abstain("OPEN_INTEREST_NOT_CONFIRMED")

    imbalance=D(current["book_imbalance"])
    taker=D(current["taker_ratio"])
    if taker>=D(PARAMETERS["minimum_taker_buy_sell_ratio_for_long"]) and imbalance>=D(PARAMETERS["minimum_book_imbalance_abs"]):
        direction=1
        side="LONG"
        entry=dec(current["ask"],positive=True)
        impact=D(current["buy_impact_bps"])
    elif taker<=D(PARAMETERS["maximum_taker_buy_sell_ratio_for_short"]) and imbalance<=-D(PARAMETERS["minimum_book_imbalance_abs"]):
        direction=-1
        side="SHORT"
        entry=dec(current["bid"],positive=True)
        impact=D(current["sell_impact_bps"])
    else:
        return abstain("TAKER_AND_BOOK_DISAGREE")
    if impact>D(PARAMETERS["maximum_book_impact_bps"]):
        return abstain("INSUFFICIENT_VISIBLE_LIQUIDITY")
    risk=entry*D(PARAMETERS["stop_distance_pct"])/100
    stop=entry-direction*risk
    target=entry+direction*risk*D(PARAMETERS["gross_target_R"])
    if stop<=0 or target<=0:
        return abstain("INVALID_PRICE_GEOMETRY")
    # Fee + slippage each side. Spread is reflected by paying the ask for
    # longs / bid for shorts and an opposite executable touch for exit.
    per_side=D(PARAMETERS["per_side_fee_slippage_bps"])/10000
    model_profit=(target-entry)*direction - (entry+target)*per_side - entry*spread/10000
    modeled_r=model_profit/(risk+entry*per_side)
    if modeled_r<D(PARAMETERS["minimum_cost_adjusted_target_R"]):
        return abstain("AFTER_COST_TARGET_TOO_WEAK")
    return {
        "status":"PAPER_CANDIDATE","policy":MODEL,"policy_sha256":POLICY_SHA,
        "symbol":current["symbol"],"direction":side,
        "decided_at_ms":at,
        "entry_reference":number(entry),"stop":number(stop),"target":number(target),
        "risk_distance":number(risk),"modeled_target_net_R":number(modeled_r),
        "oi_change_pct":number(oi_change_pct),
        "taker_ratio":current["taker_ratio"],
        "book_imbalance":current["book_imbalance"],
        "spread_bps":current["spread_bps"],"book_impact_bps":number(impact),
        "evidence_hash":digest(current),"previous_evidence_hash":digest(previous),
        "confidence_probability":None,"validated_accuracy":None,
        "reference_notional_usdt":PARAMETERS["reference_notional_usdt"],
        "no_exchange_execution":True,"no_telegram_publication":True,
        "paper_only":True,
    }


def horizon_mark(idea,observation):
    """Observed future touch, NOT an intrabar stop/target outcome."""
    direction=1 if idea["direction"]=="LONG" else -1
    entry=D(idea["entry_reference"])
    risk=D(idea["risk_distance"])
    touch=D(observation["bid"] if direction>0 else observation["ask"])
    rate=D(PARAMETERS["per_side_fee_slippage_bps"])/10000
    net=(direction*(touch-entry)-(entry+touch)*rate)/(risk+entry*rate)
    return {
        "observation_at_ms":observation["observed_at_ms"],
        "net_reference_R":number(net),
        "is_beyond_stop_at_observation":touch<=D(idea["stop"]) if direction>0 else touch>=D(idea["stop"]),
        "is_beyond_target_at_observation":touch>=D(idea["target"]) if direction>0 else touch<=D(idea["target"]),
        "not_a_verified_stop_target_fill":True,
    }

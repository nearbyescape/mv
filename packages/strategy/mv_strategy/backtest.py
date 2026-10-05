"""Offline minute replay. Shared live entry/risk rules; modeled fills are labeled separately."""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, localcontext, ROUND_HALF_EVEN

from .indicators import Bar, PRECISION
from .signals import Snapshot, Quote, PriceFilter, PlanRejected, build_plan, evaluate_setup, decision_id, canonical_hash
from .entry_filters import ENTRY_POLICIES, entry_filter

D = Decimal
MINUTE = 60_000
EXIT_POLICIES = {
    "baseline": ("EMA-PULLBACK-ATR-v1", True, True),
    "stop_target": ("EMA-PULLBACK-ATR-EXITS-ST-v1", True, False),
    "stop_ema50": ("EMA-PULLBACK-ATR-EXITS-SE-v1", False, True),
}


@dataclass(frozen=True)
class Costs:
    fee_bps: D
    spread_bps: D
    slippage_bps: D
    latency_ms: int

    def validate(self):
        if any(not isinstance(v, D) or not v.is_finite() or not 0 <= v < 1000 for v in (self.fee_bps, self.spread_bps, self.slippage_bps)) or type(self.latency_ms) is not int or not 0 < self.latency_ms < 300_000:
            raise ValueError("Invalid explicit execution-cost/latency assumptions")


@dataclass(frozen=True)
class Funding:
    time: int
    rate: D
    mark_price: D

    def validate(self):
        if type(self.time) is not int or self.time < 0 or not isinstance(self.rate, D) or not self.rate.is_finite() or not isinstance(self.mark_price, D) or not self.mark_price.is_finite() or self.mark_price <= 0:
            raise ValueError("Invalid funding event")


def validate_minute(bar):
    if type(bar.open_time) is not int or bar.open_time < 0 or bar.open_time % MINUTE or bar.close_time != bar.open_time + MINUTE - 1:
        raise ValueError("Invalid minute boundaries")
    values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
    if any(not isinstance(v, D) or not v.is_finite() for v in values) or min(values[:4]) <= 0 or bar.volume < 0 or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
        raise ValueError("Invalid minute OHLCV")


def available_open(boundary, latency):
    """A bar's open is eligible only once modeled publication is already available."""
    return ((boundary + latency + MINUTE - 1) // MINUTE) * MINUTE


def modeled_quote(symbol, opening, time, price_filter, costs):
    half = costs.spread_bps / D(20_000)
    bid = price_filter.round(opening * (1 - half), False)
    ask = price_filter.round(opening * (1 + half), True)
    return Quote(symbol, bid, ask, D(1), D(1), time, time)


def execution_price(reference, buying, price_filter, costs, include_spread=False):
    adverse = (costs.slippage_bps + (costs.spread_bps / 2 if include_spread else D(0))) / D(10_000)
    result = price_filter.round(reference * (1 + adverse if buying else 1 - adverse), buying)
    if not price_filter.allows(result):
        raise ValueError("Modeled execution price outside filter")
    return result


def touch(bar, plan, only_gap=False, target_enabled=True):
    long = plan["direction"] == "long"
    stop, target = D(plan["stop"]), D(plan["target"])
    if bar.open <= stop if long else bar.open >= stop:
        return bar.open, "stop_gap", False
    if target_enabled and (bar.open >= target if long else bar.open <= target):
        # A favorable gap earns no improvement beyond the target level.
        return target, "target_gap", False
    if only_gap:
        return None
    stop_hit = bar.low <= stop if long else bar.high >= stop
    target_hit = target_enabled and (bar.high >= target if long else bar.low <= target)
    if stop_hit:
        return stop, "stop", target_hit
    if target_hit:
        return target, "target", False
    return None


class Replay:
    def __init__(self, symbol, snapshots, funding, price_filter, costs, start, end, capital, exit_policy="baseline", entry_policy="baseline"):
        if entry_policy not in ENTRY_POLICIES or (entry_policy != "baseline" and exit_policy != "baseline"):
            raise ValueError("Unknown entry policy or unregistered combined policies")
        self.entry_policy = entry_policy
        if exit_policy not in EXIT_POLICIES:
            raise ValueError("Unknown versioned research exit policy")
        self.exit_policy = exit_policy
        self.policy_strategy, self.target_enabled, self.trend_enabled = EXIT_POLICIES[exit_policy]
        costs.validate()
        price_filter.validate()
        if not isinstance(capital, D) or not capital.is_finite() or capital <= 0 or start % 3_600_000 or end % 3_600_000 or start >= end:
            raise ValueError("Invalid replay capital or partition")
        previous_time = None
        for event in funding:
            event.validate()
            if previous_time is not None and event.time <= previous_time:
                raise ValueError("Funding events must be strictly ordered")
            previous_time = event.time
        self.symbol, self.snapshots, self.funding = symbol, snapshots, funding
        self.filter, self.costs, self.start, self.end = price_filter, costs, start, end
        self.initial, self.cash = capital, capital
        self.position = self.pending = self.pending_exit = None
        self.trades, self.decisions, self.curve = [], [], [{"time": start, "equity": str(capital), "exposure": "0"}]
        self.blocked = Counter()
        self.funding_index = self.held_minutes = 0
        self.passive = None
        self.passive_cash = capital
        self.passive_funding = self.passive_fee = D(0)

    def charge(self, event):
        for position, passive in ((self.position, False), (self.passive, True)):
            if position and position["entry_time"] < event.time:
                value = position["quantity"] * event.mark_price * event.rate
                if not passive and position["plan"]["direction"] == "short":
                    value = -value
                if passive:
                    self.passive_cash -= value
                    self.passive_funding -= value
                else:
                    self.cash -= value
                    position["funding"] -= value
                    position["funding_events"] += 1

    def consume_funding(self, through):
        while self.funding_index < len(self.funding) and self.funding[self.funding_index].time <= through:
            event = self.funding[self.funding_index]
            if event.time >= self.start:
                self.charge(event)
            self.funding_index += 1

    def close(self, reference, time, reason, ambiguous=False):
        p = self.position
        long = p["plan"]["direction"] == "long"
        fill = execution_price(reference, not long, self.filter, self.costs, True)
        gross = (fill - p["entry_fill"]) * p["quantity"] * (1 if long else -1)
        fee = fill * p["quantity"] * self.costs.fee_bps / 10_000
        net = gross - p["entry_fee"] - fee + p["funding"]
        self.cash += gross - fee
        trade = {"signal_id": p["plan"]["id"], "symbol": self.symbol, "direction": p["plan"]["direction"],
                 "source_close": p["plan"]["source_close_boundary"], "entry_time": p["entry_time"], "exit_time": time,
                 "exit_reason": reason, "ambiguous_stop_first": ambiguous, "funding_events": p["funding_events"],
                 **{key: str(value) for key, value in {"quantity": p["quantity"], "entry_fill": p["entry_fill"], "exit_fill": fill,
                     "reference_entry": D(p["plan"]["entry"]), "exit_reference": reference, "stop": D(p["plan"]["stop"]), "target": D(p["plan"]["target"]),
                     "frozen_atr": D(p["plan"]["frozen_atr"]), "initial_risk_usdt": p["risk"], "gross_pnl": gross,
                     "fees": p["entry_fee"] + fee, "funding_pnl": p["funding"], "net_pnl": net,
                     "net_r": net / p["risk"], "entry_notional": p["quantity"] * p["entry_fill"], "exit_notional": p["quantity"] * fill,
                     "mae_observed": p["mae"], "mfe_observed": p["mfe"]}.items()},
                 "evidence": p["evidence"], "plan": p["plan"]}
        self.trades.append(trade)
        self.position = self.pending_exit = None

    def enter(self, bar):
        candidate = self.pending
        self.pending = None
        if self.position or self.cash <= 0:
            self.blocked["ACTIVE_POSITION_OR_NO_CAPITAL"] += 1
            return
        source, previous, confirmation, setup = candidate["source"], candidate["previous"], candidate["confirmation"], candidate["setup"]
        quote = modeled_quote(self.symbol, bar.open, bar.open_time, self.filter, self.costs)
        try:
            plan = build_plan(self.symbol, setup.direction, source, quote, self.filter, bar.open_time)
        except PlanRejected as exc:
            self.blocked[exc.code] += 1
            return
        fill = execution_price(D(plan["entry"]), setup.direction == "long", self.filter, self.costs)
        geometry = D(plan["stop"]) < fill < D(plan["target"]) if setup.direction == "long" else D(plan["target"]) < fill < D(plan["stop"])
        if not geometry:
            self.blocked["SLIPPAGE_INVALID_GEOMETRY"] += 1
            return
        quantity = self.cash / (fill * (1 + self.costs.fee_bps / 10_000))
        fee = quantity * fill * self.costs.fee_bps / 10_000
        self.cash -= fee
        plan.update({"id": decision_id(self.symbol, source.bar.open_time), "execution": "modeled-historical-reference", "quote_assumption": "1m open plus configured spread; not historical bookTicker"})
        if self.exit_policy != "baseline":
            plan.update({"reference_strategy": plan["strategy"], "strategy": self.policy_strategy,
                         "risk_policy": self.policy_strategy, "research_exit_policy": self.exit_policy,
                         "target_active": self.target_enabled, "ema50_exit_active": self.trend_enabled,
                         "id": canonical_hash({"entry_decision": plan["id"], "exit_policy": self.policy_strategy})})
        evidence = {"source": source.evidence(), "previous": previous.evidence(), "confirmation": confirmation.evidence(), "checks": setup.checks,
                    "quote": {**quote.evidence(), "source": "modeled-from-1m-open", "quantities": "placeholders; no historical liquidity claim"}}
        evidence["hash"] = canonical_hash(evidence)
        if self.entry_policy != "baseline":
            plan.update({"reference_strategy": plan["strategy"], "strategy": ENTRY_POLICIES[self.entry_policy][0],
                         "research_entry_policy": self.entry_policy,
                         "id": canonical_hash({"entry_decision": plan["id"], "entry_policy": ENTRY_POLICIES[self.entry_policy][0]})})
            evidence["entry_filter"] = entry_filter(self.entry_policy, source, previous, setup.direction)
            evidence["hash"] = canonical_hash({k: v for k, v in evidence.items() if k != "hash"})
        self.position = {"plan": plan, "evidence": evidence, "entry_time": bar.open_time, "entry_fill": fill, "quantity": quantity,
                         "entry_fee": fee, "funding": D(0), "funding_events": 0, "risk": abs(fill - D(plan["stop"])) * quantity,
                         "mae": D(0), "mfe": D(0)}

    def decision(self, time):
        source = self.snapshots["1h"].get(time - 3_600_000)
        previous = self.snapshots["1h"].get(time - 7_200_000)
        confirmation = self.snapshots["4h"].get(time // 14_400_000 * 14_400_000 - 14_400_000)
        if source is None:
            raise ValueError("Missing completed source at replay boundary")
        setup = evaluate_setup(source, previous, confirmation)
        if self.entry_policy != "baseline" and setup.outcome in ("LONG_SETUP", "SHORT_SETUP"):
            check = entry_filter(self.entry_policy, source, previous, setup.direction)
            self.decisions.append({"time": time, "entry_filter": check, "source_hash": canonical_hash(source.evidence())})
            if not check["passed"]:
                from .signals import Setup
                self.blocked["ENTRY_FILTER_" + self.entry_policy.upper()] += 1
                setup = Setup("NO_SETUP", "ENTRY_FILTER_REJECTED", setup.direction, [*setup.checks, check])
        self.decisions.append({"time": time, "id": decision_id(self.symbol, source.bar.open_time), "outcome": setup.outcome,
                               "reason": setup.reason, "evidence_hash": canonical_hash([source.evidence(), previous.evidence() if previous else None, confirmation.evidence() if confirmation else None, setup.checks])})
        if self.position:
            if self.trend_enabled and self.pending_exit is None and (source.bar.close <= source.ema50 if self.position["plan"]["direction"] == "long" else source.bar.close >= source.ema50):
                self.pending_exit = available_open(time, self.costs.latency_ms)
            if setup.outcome in ("LONG_SETUP", "SHORT_SETUP"):
                self.blocked["ACTIVE_POSITION"] += 1
        elif setup.outcome in ("LONG_SETUP", "SHORT_SETUP"):
            self.pending = {"time": available_open(time, self.costs.latency_ms), "source": source, "previous": previous, "confirmation": confirmation, "setup": setup}
        elif setup.outcome == "BLOCKED_DATA":
            raise ValueError(f"Replay source not ready: {setup.reason}")

    def step(self, bar):
        time = bar.open_time
        self.consume_funding(time)
        if self.position:
            gap = touch(bar, self.position["plan"], True, self.target_enabled)
            if gap:
                self.close(gap[0], time, gap[1])
        if self.position and self.pending_exit is not None and time >= self.pending_exit:
            self.close(bar.open, time, "ema50_exit")
        if self.pending and time >= self.pending["time"]:
            self.enter(bar)
        if time % 3_600_000 == 0:
            self.decision(time)
        if self.passive is None and time >= available_open(self.start, self.costs.latency_ms):
            quote = modeled_quote(self.symbol, bar.open, time, self.filter, self.costs)
            fill = execution_price(quote.ask, True, self.filter, self.costs)
            quantity = self.initial / (fill * (1 + self.costs.fee_bps / 10_000))
            fee = quantity * fill * self.costs.fee_bps / 10_000
            self.passive_cash -= fee
            self.passive_fee += fee
            self.passive = {"entry_time": time, "entry_fill": fill, "quantity": quantity}
        # Funding a few milliseconds inside a minute precedes its unknown intrabar
        # stop/target order. This is explicit timing uncertainty, not tick accuracy.
        self.consume_funding(bar.close_time)
        if self.position:
            self.held_minutes += 1
            hit = touch(bar, self.position["plan"], target_enabled=self.target_enabled)
            if hit:
                self.close(hit[0], bar.close_time, hit[1], hit[2])
            else:
                p = self.position
                long = p["plan"]["direction"] == "long"
                adverse = p["entry_fill"] - bar.low if long else bar.high - p["entry_fill"]
                favorable = bar.high - p["entry_fill"] if long else p["entry_fill"] - bar.low
                p["mae"], p["mfe"] = max(p["mae"], adverse, D(0)), max(p["mfe"], favorable, D(0))
        if time + MINUTE == self.end:
            if self.position:
                self.close(bar.close, bar.close_time, "partition_end")
            if self.passive:
                fill = execution_price(bar.close, False, self.filter, self.costs, True)
                fee = fill * self.passive["quantity"] * self.costs.fee_bps / 10_000
                self.passive_cash += (fill - self.passive["entry_fill"]) * self.passive["quantity"] - fee
                self.passive_fee += fee
        if (time + MINUTE) % 3_600_000 == 0:
            equity, exposure = self.cash, D(0)
            if self.position:
                p = self.position
                equity += (bar.close - p["entry_fill"]) * p["quantity"] * (1 if p["plan"]["direction"] == "long" else -1)
                exposure = p["quantity"] * bar.close
            self.curve.append({"time": time + MINUTE, "equity": str(equity), "exposure": str(exposure)})

    def result(self):
        return {"symbol": self.symbol, "initial_capital": str(self.initial), "ending_equity": str(self.cash), "trades": self.trades,
                "curve": self.curve, "decisions": self.decisions, "blocked": dict(self.blocked), "held_minutes": self.held_minutes,
                "passive_ending_equity": str(self.passive_cash), "passive_funding_pnl": str(self.passive_funding), "passive_fees": str(self.passive_fee)}


def replay_many(symbol, bars, snapshots, funding, price_filter, scenarios, start, end, capital):
    """Stream each minute once through all preregistered execution scenarios."""
    with localcontext() as context:
        context.prec, context.rounding = PRECISION, ROUND_HALF_EVEN
        engines = {name: Replay(symbol, snapshots, funding, price_filter, costs, start, end, capital) for name, costs in scenarios.items()}
        expected = start
        for bar in bars:
            validate_minute(bar)
            if bar.open_time != expected or bar.open_time >= end:
                raise ValueError("Missing, duplicate, reordered or out-of-window minute")
            for engine in engines.values():
                engine.step(bar)
            expected += MINUTE
        if expected != end:
            raise ValueError("Incomplete execution coverage")
        return {name: engine.result() for name, engine in engines.items()}

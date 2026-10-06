"""Single local decision worker. Public quote requests happen only for qualifying setups."""
import argparse
import asyncio
import logging
from pathlib import Path
import time

from filelock import FileLock, Timeout
import httpx
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.operations.lease import worker_transaction
from app.database import Session
from app.market.binance import BinancePublic, RateLimited, now_ms
from app.market.views import collector_health
from app.models import EngineStatus, SignalDecision
from .service import PENDING, STRATEGY_ID, btc_regime_guard, check_live_contract, check_source_revisions, context_at, canonical_hash, decision_priority, discover, engine_health, evaluate_decision, expire_slots

log = logging.getLogger("mv.engine")


class SignalWorker:
    def __init__(self, public):
        self.public = public
        self.last_decision = None
        self.rate_limit_until = 0.0
        self.last_revision_scan = 0.0

    def status(self, state, error=None):
        with worker_transaction("signal-engine", Session) as session:
            row = session.get(EngineStatus, "engine") or EngineStatus(id="engine")
            row.state, row.updated_at, row.error = state, now_ms(), error
            row.last_decision_at = self.last_decision
            session.add(row)

    async def process(self, identity):
        from app.config import get_settings
        if get_settings().maintenance:
            return
        with worker_transaction("signal-engine", Session) as session:
            row = session.get(SignalDecision, identity)
            if row is None or row.strategy != STRATEGY_ID:
                return
            from app.operations.market_lock import lock_market
            lock_market(session,row.symbol)
            fingerprint = evaluate_decision(session, row, now_ms())
            symbol = row.symbol
            offset = collector_health(session)["clock_offset_ms"]
            if row.outcome != PENDING:
                self.last_decision = now_ms()
        if fingerprint is None or time.monotonic() < self.rate_limit_until:
            return
        try:
            async with asyncio.timeout(10):
                quote = await self.public.quote(symbol, offset)
        except Exception as exc:
            if isinstance(exc, RateLimited):
                self.rate_limit_until = time.monotonic() + exc.retry_after
            with worker_transaction("signal-engine", Session) as session:
                row = session.get(SignalDecision, identity)
                if row is not None and row.strategy == STRATEGY_ID and row.outcome == PENDING:
                    row.reason = "QUOTE_RATE_LIMITED" if isinstance(exc, RateLimited) else "QUOTE_UNAVAILABLE"
                    row.updated_at = now_ms()
                    row.evidence_json = {**row.evidence_json, "quote_error": str(exc)[:200]}
            return
        try:
            with worker_transaction("signal-engine", Session) as session:
                if session.get_bind().dialect.name == "sqlite":
                    session.execute(text("BEGIN IMMEDIATE"))
                row = session.get(SignalDecision, identity)
                if row is None or row.strategy != STRATEGY_ID:
                    return
                from app.operations.market_lock import lock_market
                lock_market(session,row.symbol)
                if row.outcome != PENDING:
                    return
                evidence = context_at(session, symbol, row.source_open_time)[-1]
                # Compare the exact pre-quote source, strategy checks, metadata and
                # BTC regime.  A BTC revision during an alt quote must force a
                # fresh evaluation rather than publishing against stale context.
                for key in ("checks", "setup"):
                    if key in row.evidence_json:
                        evidence[key] = row.evidence_json[key]
                if row.direction:
                    _, btc_evidence = btc_regime_guard(session, symbol, row.direction, row.source_open_time)
                    evidence["btc_regime"] = btc_evidence
                if canonical_hash(evidence) != fingerprint:
                    row.reason, row.updated_at = "SOURCE_CHANGED_DURING_QUOTE", now_ms()
                    return
                evaluate_decision(session, row, now_ms(), quote)
                self.last_decision = now_ms()
                if row.outcome == "PUBLISHED":
                    log.info("Published %s %s id=%s", row.symbol, row.direction, row.id)
        except IntegrityError:
            # Unique boundary and symbol/strategy slot protect retries and competing commits.
            log.info("Concurrent decision/slot commit rejected for %s; will reconcile", identity)

    async def tick(self):
        from app.config import get_settings
        from .session import session_view
        local_now = now_ms()
        with worker_transaction("signal-engine", Session) as session:
            health = collector_health(session)
            if not get_settings().maintenance:
                discover(session, local_now)
            expire_slots(session, local_now + health["clock_offset_ms"])
            if time.monotonic() - self.last_revision_scan >= 10:
                check_source_revisions(session, local_now + health["clock_offset_ms"])
                self.last_revision_scan = time.monotonic()
        if get_settings().maintenance:
            self.status("maintenance")
            return
        with Session() as session:
            candidates = list(session.scalars(select(SignalDecision).where(
                SignalDecision.strategy == STRATEGY_ID,
                SignalDecision.outcome == PENDING,
                SignalDecision.updated_at <= local_now - 1500,
            ).order_by(SignalDecision.source_open_time).limit(50)))
            candidates.sort(key=lambda row: decision_priority(session, row))
            identities = [row.id for row in candidates]
        for identity in identities:
            await self.process(identity)
            # A many-symbol close must not make engine health stale while quotes
            # are fetched sequentially. Publication/rounding remain unchanged.
            self.status("waiting-data" if not health["live"] else "running" if session_view(now_ms()+health["clock_offset_ms"])["open"] else "session-paused")
        self.status("waiting-data" if not health["live"] else "running" if session_view(now_ms()+health["clock_offset_ms"])["open"] else "session-paused")

    async def run(self, once=False):
        check_live_contract()
        from .session import check_policy
        check_policy()
        try:
            while True:
                try:
                    await self.tick()
                except Exception as exc:
                    self.status("error", str(exc)[:300])
                    log.exception("Engine tick failed")
                    if once:
                        raise
                    await asyncio.sleep(3)
                if once:
                    return
                await asyncio.sleep(1)
        finally:
            self.status("stopped")


async def main(once):
    from app.operations.lease import singleton
    with singleton("signal-engine"):
        await run_main(once)


async def run_main(once):
    async with httpx.AsyncClient(timeout=8) as client:
        await SignalWorker(BinancePublic(client)).run(once)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run one decision scan; do not claim a continuous worker")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    lock = FileLock(str(Path(__file__).resolve().parents[2] / ".engine.lock"), timeout=0)
    try:
        with lock:
            asyncio.run(main(args.once))
    except Timeout:
        raise SystemExit("A signal worker already runs for this local checkout")
    except KeyboardInterrupt:
        pass

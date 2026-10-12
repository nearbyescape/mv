"""V7Sonic bounded ONE-SHOT public-only paper observer (never auto-started).

This is NOT a daemon, live strategy replacement, evidence witness, API,
broker service, or Telegram publisher. No loops over future boundaries.
OFF by default. Explicit operator opt-in required to perform 31 public
GET requests (24 closed kline windows, one exchangeInfo, six top-of-book).

Inputs are limited to the frozen provisional study window. A completed
predeclared boundary must be observed within 5 seconds of its closure,
and all responses and decisions must be finished within 30 seconds.
Late/missing/invalid packets are errors, never NO-SIGNAL.

Actual HTTP responses are unsigned; local timestamps are untrusted.
This cannot produce independently certified forward-performance records.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import time

from app.research.t7sonic_forward_protocol import (
    START_MS, END_MS, STEP_MS,
)
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_acquisition import (
    ROWS_BY_FRAME, request_plan,
)
from services.t7sonic.forward_https import (
    optional_https_get, inspect_transport_response,
)
from services.t7sonic.forward_public_http import (
    optional_public_http_get, verify_http_response,
)
from services.t7sonic.forward_release_bridge import (
    preview_from_raw_candles_and_books,
)

MAX_START_LAG_MS = 5_000
MAX_DECISION_LAG_MS = 30_000
MAX_CONCURRENT_READS = 8
KLINE_TIMEOUT_SECONDS = 3.0
PUBLIC_TIMEOUT_SECONDS = 3.0


def checked_live_cycle(
    boundary_ms: int,
    source_envelopes: dict,
    book_envelopes: dict,
    exchange_info_envelope,
) -> dict:
    """Pure offline verification seam for ALL 31 public response envelopes."""
    if (type(boundary_ms) is not int or
            not START_MS <= boundary_ms < END_MS or boundary_ms % STEP_MS):
        raise ValueError("Outside frozen provisional observation window")
    expected = set(MARKETS)
    if (not isinstance(source_envelopes, dict) or
            set(source_envelopes) != expected or
            not isinstance(book_envelopes, dict) or
            set(book_envelopes) != expected):
        raise ValueError("Six complete OHLCV and quote envelope groups required")
    info_proof = verify_http_response(
        "exchangeInfo", exchange_info_envelope
    )
    if (exchange_info_envelope.received_ms_local_claim < boundary_ms or
            exchange_info_envelope.received_ms_local_claim >
            boundary_ms+MAX_DECISION_LAG_MS):
        raise ValueError("Venue metadata returned outside decision window")

    records = {}
    books = {}
    quote_receipts = {}
    evals = {}
    transport_proofs = {}
    latest_receipt = exchange_info_envelope.received_ms_local_claim
    for symbol in MARKETS:
        group = source_envelopes[symbol]
        if not isinstance(group, dict) or set(group) != set(ROWS_BY_FRAME):
            raise ValueError("Missing or extra OHLCV source frame")
        books[symbol] = book_envelopes[symbol].body
        proof = verify_http_response(
            "bookTicker", book_envelopes[symbol], symbol=symbol
        )
        received = book_envelopes[symbol].received_ms_local_claim
        if not boundary_ms <= received <= boundary_ms+MAX_DECISION_LAG_MS:
            raise ValueError("Book response outside allowed cycle")
        latest_receipt = max(latest_receipt, received)
        quote_receipts[symbol] = received
        transport_proofs[symbol] = {"quote": proof, "klines": {}}
        records[symbol] = {}
        for frame in ROWS_BY_FRAME:
            plan = request_plan(symbol, frame, boundary_ms)
            frame_bars, frame_proof = inspect_transport_response(
                plan, group[frame]
            )
            if len(frame_bars) != ROWS_BY_FRAME[frame]:
                raise ValueError("Unexpected completed-source count")
            received_frame = group[frame].received_ms
            if received_frame > boundary_ms+MAX_DECISION_LAG_MS:
                raise ValueError("Source receipt too late for indicative paper plan")
            latest_receipt = max(latest_receipt, received_frame)
            transport_proofs[symbol]["klines"][frame] = frame_proof
            records[symbol][frame] = (
                plan, group[frame].raw_body, 200, received_frame
            )
    if latest_receipt > boundary_ms+MAX_DECISION_LAG_MS:
        raise ValueError("Complete 31-source cycle exceeded deadline")
    for symbol in MARKETS:
        evals[symbol] = latest_receipt

    out = preview_from_raw_candles_and_books(
        boundary_ms, records, books, exchange_info_envelope.body,
        received_ms_by_symbol=quote_receipts,
        evaluated_ms_by_symbol=evals,
    )
    return {
        **out,
        "status": "INTERNAL_ONLY_PUBLIC_REST_CYCLE_UNATTESTED",
        "full_six_market_source_geometry_validated": True,
        "source_http_responses": 31,
        "latest_local_receipt_ms_unverified": latest_receipt,
        "public_rest_transport_proofs": transport_proofs,
        "exchange_info_transport_proof": info_proof,
        "external_independent_receipt_verified": False,
        "raw_responses_replicated_off_vps": False,
        "real_money_orders_authorized": False,
        "client_publication_authorized": False,
        "telegram_enqueued": False,
    }


def optional_public_paper_capture(
    boundary_ms: int, *, network_approved: bool = False,
) -> dict:
    """One time-bounded public HTTPS cycle, opt-in ONLY, no scheduling.

    Local time is a self-reported clock and MUST NOT be considered a
    cryptographic witness. Refuse early/missed boundaries before any I/O.
    """
    if network_approved is not True:
        raise PermissionError("One-shot public market capture is disabled")
    if (type(boundary_ms) is not int or
            not START_MS <= boundary_ms < END_MS or boundary_ms % STEP_MS):
        raise ValueError("Invalid frozen decision boundary")
    now_ms = time.time_ns()//1_000_000
    if not boundary_ms <= now_ms <= boundary_ms+MAX_START_LAG_MS:
        raise ValueError("Missed or future decision boundary; cannot backfill")
    # Phase 1: fetch all completed-candle windows plus venue metadata.
    # Quotes must be captured as close as practical to analysis, not
    # alongside slow historical klines (which can make books stale).
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_READS) as pool:
        historical = {}
        for symbol in MARKETS:
            for frame in ROWS_BY_FRAME:
                request = request_plan(symbol, frame, boundary_ms)
                future = pool.submit(
                    optional_https_get, request,
                    network_approved=True,
                    timeout_seconds=KLINE_TIMEOUT_SECONDS,
                )
                historical[future] = (symbol, frame)
        info_job = pool.submit(
            optional_public_http_get, "exchangeInfo",
            network_approved=True,
            timeout_seconds=PUBLIC_TIMEOUT_SECONDS,
        )

        sources = {symbol: {} for symbol in MARKETS}
        for future in as_completed(historical):
            symbol, frame = historical[future]
            sources[symbol][frame] = future.result()
        info = info_job.result()

        # Phase 2: collect all six live best-bid/ask quotes only after all
        # prior source downloads have completed. No signal is returned on
        # ANY missing quote or late/failed source, and there are no retries.
        quote_jobs = {}
        for symbol in MARKETS:
            future = pool.submit(
                optional_public_http_get, "bookTicker",
                symbol=symbol, network_approved=True,
                timeout_seconds=PUBLIC_TIMEOUT_SECONDS,
            )
            quote_jobs[future] = symbol
        books = {}
        for future in as_completed(quote_jobs):
            books[quote_jobs[future]] = future.result()

    if info is None:
        raise ValueError("No venue metadata received")
    if time.time_ns()//1_000_000 > boundary_ms+MAX_DECISION_LAG_MS:
        raise ValueError("Cycle completed too late; discard all data")
    report = checked_live_cycle(boundary_ms, sources, books, info)

    # A full six-market parse, reconciliation, and strategy evaluation may
    # consume significant CPU after the 31 HTTP responses arrive. The old
    # pre-parse time check was insufficient: a paper candidate could escape
    # AFTER expiry, or when the top-of-book quote was already stale.
    # Never reinterpret an expired/late observation as NO_SETUP.
    completed_ms = time.time_ns() // 1_000_000
    if completed_ms > boundary_ms + MAX_DECISION_LAG_MS:
        raise ValueError("Paper decision computation exceeded deadline")
    quote_proofs = report["quote_proofs"]
    if set(quote_proofs) != set(MARKETS):
        raise ValueError("Missing quote evidence after paper computation")
    for symbol in MARKETS:
        event_ms = quote_proofs[symbol]["exchange_event_ms_unattested"]
        if (type(event_ms) is not int or
                not 0 <= completed_ms - event_ms <= 5_000):
            raise ValueError("Quote aged beyond five seconds while computing paper plan")
    for candidate in report["indicative_candidates"]:
        expiry = candidate["expires_at_ms"]
        if type(expiry) is not int or completed_ms >= expiry:
            raise ValueError("Computed paper candidate already expired")
    return {
        **report,
        "complete_cycle_returned_before_deadline_local_clock_claim": True,
        "quotes_fresh_at_return_local_clock_claim": True,
        "paper_decision_completed_ms_local_claim": completed_ms,
        "client_publication_authorized": False,
        "telegram_enqueued": False,
        "real_money_orders_authorized": False,
    }

"""V7Sonic EARLY live engineering smoke; does NOT alter Oct-15 study.

Use manually before frozen validation start. Exactly 24 closed kline,
six bookTicker, one exchangeInfo public HTTPS GET, no credentials.
Defaults to NO NETWORK. No trades, Telegram, DB, workers or clients.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler, HTTPRedirectHandler
import argparse
import base64
import json
import os
import ssl
import stat
import tempfile
import time

from app.research.t7sonic_validation_plan import MARKETS
from app.research.t7sonic_forward_protocol import START_MS
from app.research.t7sonic_perception import Bar, INTERVAL_MS
from app.research.t7sonic_replay import _as_of
from app.research.t7sonic_release_preview import build_offline_preview
from services.t7sonic.forward_live_quote import extract_contract_rule, parse_book_ticker

FRAMES = {"1m":480,"15m":64,"1h":64,"4h":64}
STEP = 300_000
LIMIT_MS = 30_000
MAX_CAPTURE_ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 1.5
RETRY_MIN_BUDGET_MS = 4_500
RECONCILIATION_FAILURE_PREFIX = (
    "Native timeframe contradicts independently verified minute OHLCV: "
)


class _RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ValueError("Redirect rejected")


def next_boundary(now_ms):
    if type(now_ms) is not int or now_ms <= 0:
        raise ValueError("Invalid local clock")
    return (now_ms // STEP + 1) * STEP


def preflight(now_ms):
    return {
        "status":"EARLY_RESEARCH_SMOKE_NO_NETWORK",
        "next_boundary_utc":datetime.fromtimestamp(
            next_boundary(now_ms)/1000, timezone.utc).isoformat(),
        "separate_from_oct15_forward_study":True,
        "markets":list(MARKETS),"network_calls":0,
        "telegram_messages":0,"orders":0,
    }


def url_for(symbol,frame,boundary):
    if symbol not in MARKETS or frame not in FRAMES or (
        type(boundary) is not int or boundary % STEP
    ):
        raise ValueError("Bad source request")
    end=boundary // INTERVAL_MS[frame] * INTERVAL_MS[frame]
    q={"symbol":symbol,"interval":frame,
       "startTime":end-FRAMES[frame]*INTERVAL_MS[frame],
       "endTime":end-1,"limit":FRAMES[frame]}
    return "https://fapi.binance.com/fapi/v1/klines?"+urlencode(q)


def _get(url,max_bytes):
    ctx=ssl.create_default_context()
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=ctx),_RejectRedirect())
    req=Request(url,method="GET",headers={"Accept":"application/json"})
    start=time.monotonic()
    with opener.open(req,timeout=3.0) as r:
        data=r.read(max_bytes+1)
        if (r.status != 200 or r.geturl()!=url or
                r.headers.get("Content-Type","").split(";")[0].strip().lower()
                != "application/json"):
            raise ValueError("Invalid REST status, destination or content type")
    received=time.time_ns()//1_000_000
    if not 2 <= len(data) <= max_bytes:
        raise ValueError("Bad REST payload size")
    return data,received,round((time.monotonic()-start)*1000,2)


def _parse(symbol,frame,boundary,raw):
    if not isinstance(raw,bytes) or len(raw)>256_000:
        raise ValueError("Invalid native candle body")
    rows=json.loads(raw)
    if not isinstance(rows,list) or len(rows)!=FRAMES[frame]:
        raise ValueError("Incomplete native candle history")
    step=INTERVAL_MS[frame]
    last=boundary//step*step
    parsed=[]
    for i,row in enumerate(rows):
        expected=last-(len(rows)-i)*step
        if (not isinstance(row,list) or len(row)!=12 or
                type(row[0]) is not int or row[0]!=expected or
                type(row[6]) is not int or row[6]!=expected+step-1):
            raise ValueError("Gap, duplicate, future or partial kline")
        parsed.append(Bar.parse({
            "open_ms":expected,"open":row[1],"high":row[2],
            "low":row[3],"close":row[4],"volume":row[5],
        },frame))
    return parsed


def analyze(boundary,candles,books,info,book_receipts,evaluated):
    if (type(boundary) is not int or boundary%STEP or
            not boundary<=evaluated<=boundary+LIMIT_MS or
            set(candles)!=set(MARKETS) or
            set(books)!=set(MARKETS) or
            set(book_receipts)!=set(MARKETS)):
        raise ValueError("Incomplete six-market timely diagnostic")
    snapshots=[]; quotes=[]; proofs={}
    for symbol in MARKETS:
        if set(candles[symbol])!=set(FRAMES):
            raise ValueError("Missing native history")
        native={frame:_parse(symbol,frame,boundary,candles[symbol][frame])
                for frame in FRAMES}
        snapshot=_as_of(native,symbol,boundary)
        snapshots.append(snapshot["snapshot"])
        venue=extract_contract_rule(info,symbol)
        quote,proof=parse_book_ticker(
            symbol,boundary,books[symbol],venue,
            received_ms=book_receipts[symbol],evaluated_ms=evaluated)
        quotes.append(quote)
        proofs[symbol]={
            "frame_sha256":{f:sha256(candles[symbol][f]).hexdigest() for f in FRAMES},
            "book_sha256":sha256(books[symbol]).hexdigest(),
            "book_event_ms_local_unattested":quote["observed_at_ms"],
            "quote_age_ms":evaluated-quote["observed_at_ms"],
            "cross_resolution":snapshot["reconciliation"]["status"],
        }
    plans=build_offline_preview(snapshots,quotes)
    return {
        "status":"EARLY_LIVE_ENGINEERING_SMOKE_NOT_FORWARD_VALIDATION",
        "boundary_ms":boundary,"market_count":6,
        "paper_candidate_count":plans["candidate_count"],
        "decisions":[{
            "symbol":p["symbol"],"status":p["status"],
            "reason":p.get("reason"),
            "expert":p.get("expert"),"direction":p.get("direction"),
        } for p in plans["decision_records"]],
        "source_proofs":proofs,"paper_batch_sha256":plans["batch_sha256"],
        "data_source_independently_attested":False,
        "profitability_verified":False,
        "formal_forward_window_unchanged":True,
        "client_publication_authorized":False,
        "telegram_enqueued":False,"orders_submitted":False,
    }


def _save_original_responses(folder, boundary, candle_bodies,
                             book_bodies, exchange_info, book_receipts,
                             observed_ms, *, attempt=1):
    """Persist exact bytes BEFORE interpreting OHLCV or deciding a signal.

    This receipt records locally observed data, not independently verified
    exchange state or an independently witnessed capture timestamp. If later
    reconciliation fails, the raw evidence survives unchanged for forensics.
    """
    if (type(boundary) is not int or boundary % STEP or
            not isinstance(candle_bodies, dict) or
            set(candle_bodies) != set(MARKETS) or
            not isinstance(book_bodies, dict) or
            set(book_bodies) != set(MARKETS) or
            not isinstance(book_receipts, dict) or
            set(book_receipts) != set(MARKETS) or
            not isinstance(exchange_info, bytes) or
            type(observed_ms) is not int or
            type(attempt) is not int or not 1 <= attempt <= MAX_CAPTURE_ATTEMPTS):
        raise ValueError("Exact complete observation required before journal write")
    for symbol in MARKETS:
        if set(candle_bodies[symbol]) != set(FRAMES):
            raise ValueError("Incomplete candle geometry; no complete journal")
        if any(not isinstance(candle_bodies[symbol][frame], bytes)
               for frame in FRAMES) or not isinstance(book_bodies[symbol], bytes):
            raise ValueError("Original unmodified raw bytes required")
        if type(book_receipts[symbol]) is not int:
            raise ValueError("Quote receipt must be exact integer")
    def item(raw):
        return {
            "body_base64": base64.b64encode(raw).decode("ascii"),
            "original_body_sha256": sha256(raw).hexdigest(),
        }
    receipt={
        "schema":1,
        "status":"ORIGINAL_PUBLIC_REST_INPUTS_LOCAL_UNATTESTED",
        "decision_boundary_ms":boundary,
        "capture_attempt_number":attempt,
        "recorded_ms_local_clock_claim":observed_ms,
        "markets":list(MARKETS),
        "kline_bodies":{
            symbol:{frame:item(candle_bodies[symbol][frame])
                    for frame in FRAMES}
            for symbol in MARKETS
        },
        "quote_bodies":{symbol:item(book_bodies[symbol]) for symbol in MARKETS},
        "quote_received_ms_local_clock_claim":book_receipts,
        "exchange_info_body":item(exchange_info),
        "original_public_rest_responses_retained":31,
        "exchange_data_signed":False,
        "independent_timestamp_verified":False,
        "client_publication_authorized":False,
        "telegram_enqueued":False,
        "orders_submitted":False,
    }
    raw=(json.dumps(receipt,sort_keys=True,separators=(",",":"))+"\n").encode()
    if not 31 <= len(raw) <= 8_000_000:
        raise ValueError("Original-source evidence is oversized")
    attempt_suffix = "" if attempt == 1 else "-attempt-"+str(attempt)
    target=folder/("v7sonic-original-http-"+str(boundary)+attempt_suffix+".json")
    _write_immutable_file(folder,target,raw)
    return str(target),sha256(raw).hexdigest()


def _write_immutable_file(folder, destination, payload):
    """Atomic owner-private create-only file; no overwrite or silent partial."""
    if not isinstance(payload,bytes) or not payload:
        raise ValueError("No empty forensic evidence")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Evidence already exists; do not overwrite it")
    fd,tmp=tempfile.mkstemp(prefix=".v7sonic-original-",dir=folder)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp,destination,follow_symlinks=False)
        directory_fd=os.open(str(folder),os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        os.unlink(tmp)


def capture_one(directory):
    """Capture at most three complete, immutable source batches at one boundary.

    A short-lived native/1m mismatch may arise while a candle is closing.
    Only that exact reconciliation rejection permits a full fresh capture.
    Every attempt is preserved before parsing, with no blending of attempts,
    no tolerance of price/volume discrepancies and no late-paper decision.
    """
    target=Path(directory)
    if not target.is_absolute() or target.is_symlink() or not target.is_dir():
        raise PermissionError("Existing absolute private directory required")
    st=target.stat()
    if st.st_uid!=os.getuid() or st.st_mode & 0o077:
        raise PermissionError("Private directory must be owner-only")
    now=time.time_ns()//1_000_000
    boundary=next_boundary(now)
    if boundary >= START_MS:
        raise ValueError("Early engineering smoke only before October 15 UTC")
    dest=target/("v7sonic-early-smoke-"+str(boundary)+".json")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError("No duplicate observation may overwrite evidence")
    time.sleep((boundary-now)/1000)
    began=time.time_ns()//1_000_000
    if not boundary<=began<=boundary+4_000:
        raise ValueError("Missed boundary; cannot backfill")

    evidence=[]
    for attempt in range(1,MAX_CAPTURE_ATTEMPTS+1):
        # Fetch every source afresh. Do not mix completed candle responses
        # from different attempts or re-use a previous potentially stale book.
        candles={s:{} for s in MARKETS}
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs={
                pool.submit(_get,url_for(s,frame,boundary),256_000):(s,frame)
                for s in MARKETS for frame in FRAMES
            }
            exchange_url="https://fapi.binance.com/fapi/v1/exchangeInfo"
            info_job=pool.submit(_get,exchange_url,2_000_000)
            for future in as_completed(jobs):
                s,frame=jobs[future]
                candles[s][frame]=future.result()[0]
            info=info_job.result()[0]
            books={};received={}
            quote_jobs={
                pool.submit(
                    _get,"https://fapi.binance.com/fapi/v1/ticker/bookTicker?"
                    +urlencode({"symbol":s}),8192):s
                for s in MARKETS
            }
            for future in as_completed(quote_jobs):
                s=quote_jobs[future]
                raw,ts,latency=future.result()
                books[s]=raw;received[s]=ts
        completed=time.time_ns()//1_000_000

        # Immutable, original 31-body receipt per attempt, BEFORE any parse.
        raw_path,raw_sha=_save_original_responses(
            target,boundary,candles,books,info,received,completed,
            attempt=attempt
        )
        evidence.append({
            "attempt":attempt,
            "original_raw_evidence_path":raw_path,
            "original_raw_evidence_sha256":raw_sha,
        })
        try:
            outcome=analyze(boundary,candles,books,info,received,completed)
        except Exception as exc:
            retryable=(
                type(exc) is ValueError and
                str(exc).startswith(RECONCILIATION_FAILURE_PREFIX)
            )
            budget=(
                completed+int(RETRY_PAUSE_SECONDS*1000)+RETRY_MIN_BUDGET_MS
                <= boundary+LIMIT_MS
            )
            retry=retryable and attempt<MAX_CAPTURE_ATTEMPTS and budget
            failure={
                "status":"INTERNAL_LIVE_DIAGNOSTIC_REJECTED_UNPUBLISHED",
                "decision_boundary_ms":boundary,
                "capture_attempt_number":attempt,
                "raw_source_evidence_path":raw_path,
                "raw_source_evidence_sha256":raw_sha,
                "stage":"six_market_strict_analysis",
                "failure_class":type(exc).__name__,
                "failure_reason":str(exc)[:450],
                "retryable_cross_resolution_only":retryable,
                "fresh_full_batch_retry_planned":retry,
                "raw_sources_preserved":True,
                "client_publication_authorized":False,
                "telegram_enqueued":False,
                "orders_submitted":False,
            }
            try:
                _write_immutable_file(
                    target,
                    target/("v7sonic-rejected-"+str(boundary)+
                            "-attempt-"+str(attempt)+".json"),
                    (json.dumps(failure,sort_keys=True,indent=2)+"\n").encode(),
                )
            except OSError:
                # The original failure remains primary. All raw bytes were
                # persisted before analysis, whether or not summary I/O works.
                pass
            if retry:
                time.sleep(RETRY_PAUSE_SECONDS)
                continue
            raise

        finished=time.time_ns()//1_000_000
        if finished>boundary+LIMIT_MS:
            raise ValueError("Paper analysis exceeded decision deadline")
        if any(finished-p["book_event_ms_local_unattested"]>5_000
               for p in outcome["source_proofs"].values()):
            raise ValueError("Book quotes became stale while processing")
        serialized=(json.dumps(outcome,sort_keys=True,indent=2)+"\n").encode()
        fd,tmp=tempfile.mkstemp(prefix=".v7sonic-",dir=target)
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(fd,"wb") as stream:
                stream.write(serialized); stream.flush(); os.fsync(stream.fileno())
            os.link(tmp,dest,follow_symlinks=False)
        finally:
            os.unlink(tmp)
        return {
            "status":outcome["status"],"report_path":str(dest),
            "report_sha256":sha256(serialized).hexdigest(),
            "original_raw_evidence_path":raw_path,
            "original_raw_evidence_sha256":raw_sha,
            "original_raw_responses_retained":31*attempt,
            "capture_attempt_count":attempt,
            "attempt_evidence":evidence,
            "markets":6,"public_gets":31*attempt,
            "paper_candidates":outcome["paper_candidate_count"],
            "telegram_messages":0,"orders":0,
            "client_publication_authorized":False,
        }
    raise AssertionError("Unreachable finalization retry exhaustion")

def main():
    parser=argparse.ArgumentParser(description="Early real-data smoke, no network by default")
    parser.add_argument("--live-public-data",action="store_true")
    parser.add_argument("--diagnostic-only",action="store_true")
    parser.add_argument("--output-dir")
    options=parser.parse_args()
    if options.live_public_data:
        if not options.diagnostic_only or not options.output_dir:
            parser.error("Explicit --diagnostic-only and --output-dir required")
        result=capture_one(options.output_dir)
    else:
        if options.diagnostic_only or options.output_dir:
            parser.error("No diagnostics flags without --live-public-data")
        result=preflight(time.time_ns()//1_000_000)
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=="__main__":
    main()

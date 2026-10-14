"""V7Sonic forensic SOURCE CROSS-RESOLUTION ONLY, no signals or orders.

Reads already-closed Binance USD-M candles at ONE explicit past UTC
five-minute boundary. No model evaluation, Telegram, scheduled collector,
production data, trading keys, or alteration of Oct-15 forward window.

Compares exact 1m aggregates with full native 15m/1h/4h OHLCV fields,
including small volume discrepancies without treating them as acceptable.
Stores original public REST JSON source bodies and bounded diagnostic
metadata for reproducibility. No thresholds, repairs, or silent passes.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from decimal import Decimal as D
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.research.t7sonic_forward_protocol import START_MS
from app.research.t7sonic_perception import Bar, INTERVAL_MS
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.early_live_smoke import (
    FRAMES, STEP, _get, _parse, url_for
)

FIELDS = ("opening", "high", "low", "close", "volume")
MAX_PAST_AGE_MS = 48*3600*1000


def _fmt(v: D) -> str:
    return format(v, "f")


def _past_boundary(value: str, now_ms: int) -> int:
    if not isinstance(value,str) or not value.endswith("Z"):
        raise ValueError("Explicit UTC boundary format YYYY-MM-DDTHH:MM:SSZ")
    try:
        dt=datetime.strptime(value,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("Invalid UTC boundary timestamp") from exc
    boundary=int(dt.timestamp()*1000)
    if (type(now_ms) is not int or boundary % STEP or
            not 0 < boundary < START_MS or
            not 0 < now_ms-boundary <= MAX_PAST_AGE_MS):
        raise ValueError("Only previously closed 48h pre-Oct15 candle boundaries")
    return boundary


def forensic_compare(boundary: int, raw_by_symbol: dict) -> dict:
    """Pure field-by-field exact comparison; never change validation policy."""
    if (type(boundary) is not int or boundary%STEP or
            not isinstance(raw_by_symbol,dict) or
            set(raw_by_symbol)!=set(MARKETS)):
        raise ValueError("Six full markets and aligned five-minute boundary needed")
    checks={}
    any_price=0
    any_volume=0
    for symbol in MARKETS:
        raw=raw_by_symbol[symbol]
        if not isinstance(raw,dict) or set(raw)!=set(FRAMES):
            raise ValueError("All four native bar sources required")
        parsed={frame:_parse(symbol,frame,boundary,raw[frame])
                for frame in FRAMES}
        minutes=parsed["1m"]
        lookup={bar.open_ms:bar for bar in minutes}
        earliest=minutes[0].open_ms
        latest=minutes[-1].open_ms+60_000
        checks[symbol]={}
        for frame in ("15m","1h","4h"):
            count=0
            volume_disagreements=0
            price_disagreements=0
            examples=[]
            max_volume_absolute=D(0)
            max_volume_rel_pct=D(0)
            interval=INTERVAL_MS[frame]
            for native in parsed[frame]:
                first=native.open_ms
                if first < earliest or first+interval > latest:
                    continue
                sample=[lookup.get(first+k*60_000)
                        for k in range(interval//60_000)]
                if any(bar is None for bar in sample):
                    raise ValueError("1m gap in overlapping native timeframe")
                derived=Bar(
                    first,sample[0].opening,max(r.high for r in sample),
                    min(r.low for r in sample),sample[-1].close,
                    sum((r.volume for r in sample),D(0)),
                )
                changed={
                    key: {"native":_fmt(getattr(native,key)),
                          "derived_from_1m":_fmt(getattr(derived,key)),
                          "derived_minus_native":_fmt(
                              getattr(derived,key)-getattr(native,key)
                          )}
                    for key in FIELDS
                    if getattr(native,key)!=getattr(derived,key)
                }
                if changed:
                    if "volume" in changed:
                        volume_disagreements += 1
                        delta=abs(derived.volume-native.volume)
                        max_volume_absolute=max(max_volume_absolute,delta)
                        if native.volume:
                            max_volume_rel_pct=max(
                                max_volume_rel_pct,
                                delta/native.volume*D(100)
                            )
                    if any(key!="volume" for key in changed):
                        price_disagreements += 1
                    if len(examples)<3:
                        examples.append({
                            "native_open_utc":datetime.fromtimestamp(
                                first/1000,timezone.utc
                            ).isoformat(),
                            "different_fields":changed,
                        })
                count+=1
            if count==0:
                raise ValueError("No overlapping complete "+frame+" bars")
            any_price+=price_disagreements
            any_volume+=volume_disagreements
            checks[symbol][frame]={
                "native_bars_compared":count,
                "bars_with_price_disagreement":price_disagreements,
                "bars_with_volume_disagreement":volume_disagreements,
                "max_absolute_volume_difference":_fmt(max_volume_absolute),
                "max_relative_volume_difference_pct":_fmt(max_volume_rel_pct),
                "first_three_examples":examples,
                "raw_native_sha256":sha256(raw[frame]).hexdigest(),
            }
    return {
        "status":"SOURCE_OHLCV_DISAGREEMENT_FORENSIC_NO_SIGNALS",
        "boundary_ms":boundary,
        "boundary_utc":datetime.fromtimestamp(
            boundary/1000,timezone.utc
        ).isoformat(),
        "price_field_discrepancies":any_price,
        "volume_field_discrepancies":any_volume,
        "exact_reconciliation_passed":any_price==0 and any_volume==0,
        "markets":checks,
        "fresh_capture_at_original_boundary_reproduced":False,
        "historical_requery_may_reflect_later_revisions":True,
        "cross_timeframe_tolerance_applied":False,
        "forward_protocol_unchanged":True,
        "client_publication_authorized":False,
        "telegram_enqueued":False,
        "orders_authorized":False,
    }


def _owner_private_folder(value: str) -> Path:
    p=Path(value)
    if not p.is_absolute() or not p.is_dir() or p.is_symlink():
        raise PermissionError("Existing absolute private folder required")
    st=p.stat()
    if st.st_uid!=os.getuid() or st.st_mode&0o077:
        raise PermissionError("Owner-only directory permissions mandatory")
    return p


def _write_once(folder: Path, filename: str, blob: bytes):
    if not 1<=len(blob)<=5_000_000:
        raise ValueError("Bounded forensic payload required")
    path=folder/filename
    if path.exists() or path.is_symlink():
        raise FileExistsError("Forensic body already saved; no overwrite")
    handle,tmp=tempfile.mkstemp(prefix=".forensic-",dir=folder)
    try:
        os.fchmod(handle,0o600)
        with os.fdopen(handle,"wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.link(tmp,path,follow_symlinks=False)
    finally:
        os.unlink(tmp)
    return str(path)


def retrieve_and_compare(boundary: int, *, output_dir: str) -> dict:
    folder=_owner_private_folder(output_dir)
    if boundary>=START_MS:
        raise ValueError("No contamination of formal study window")
    raw={symbol:{} for symbol in MARKETS}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs={
            pool.submit(_get,url_for(symbol,frame,boundary),256_000):(symbol,frame)
            for symbol in MARKETS for frame in FRAMES
        }
        for job in as_completed(jobs):
            symbol,frame=jobs[job]
            raw[symbol][frame]=job.result()[0]
    forensic=forensic_compare(boundary,raw)
    evidence={
        "schema":2,
        "source_origin":"LATER public Binance USD-M API historical requery",
        "boundary_ms":boundary,
        "source_response_count":24,
        "collection_clock_ms_unattested":time.time_ns()//1_000_000,
        # Preserve exact bytes independently of JSON parsing/serialization.
        # A historical requery CANNOT reproduce what REST returned at close.
        "original_http_bodies": {
            symbol: {
                frame: {
                    "body_base64":base64.b64encode(raw[symbol][frame]).decode("ascii"),
                    "original_body_sha256":sha256(raw[symbol][frame]).hexdigest(),
                }
                for frame in FRAMES
            }
            for symbol in MARKETS
        },
        "all_sources_exchange_signed":False,
        "contemporaneous_exchange_quote_available":False,
        "original_close_time_source_reproduced":False,
        "research_only_not_forward_certification":True,
        "client_publication_authorized":False,
        "orders_submitted":0,
    }
    evidence_encoded=(json.dumps(evidence,sort_keys=True,separators=(",",":"))+"\n").encode()
    forensic_encoded=(json.dumps(forensic,sort_keys=True,indent=2)+"\n").encode()
    # Persistent raw evidence first; forensic summary second. Any I/O error
    # must NOT produce a false passing signal or backfill the paper journal.
    first=_write_once(folder,"v7sonic-ohlcv-raw-"+str(boundary)+".json",evidence_encoded)
    second=_write_once(folder,"v7sonic-ohlcv-diff-"+str(boundary)+".json",forensic_encoded)
    return {
        "status":forensic["status"],
        "historical_boundary_utc":forensic["boundary_utc"],
        "raw_source_file":first,
        "diff_report_file":second,
        "raw_source_sha256":sha256(evidence_encoded).hexdigest(),
        "price_field_discrepancies":forensic["price_field_discrepancies"],
        "volume_field_discrepancies":forensic["volume_field_discrepancies"],
        "max_examples":{
            s:{f:forensic["markets"][s][f]["first_three_examples"][:1]
                for f in ("15m","1h","4h")}
            for s in MARKETS
        },
        "source_requery_is_not_original_snapshot":True,
        "production_unchanged":True,
        "telegram_messages_sent":0,
        "orders_sent":0,
    }


def main():
    parser=argparse.ArgumentParser(
        description="Read-only fixed historical OHLCV forensic; offline default")
    parser.add_argument("--requery-public-klines",action="store_true")
    parser.add_argument("--boundary-utc")
    parser.add_argument("--output-dir")
    args=parser.parse_args()
    if not args.requery_public_klines:
        if args.boundary_utc or args.output_dir:
            parser.error("No network arguments permitted without opt-in")
        out={"status":"OFFLINE_CROSS_RESOLUTION_FORENSIC_PREFLIGHT",
             "market_count":6,"network_requests":0,
             "client_publication_authorized":False}
    else:
        if not args.boundary_utc or not args.output_dir:
            parser.error("UTC historical boundary and private output dir required")
        boundary=_past_boundary(
            args.boundary_utc,time.time_ns()//1_000_000)
        out=retrieve_and_compare(boundary,output_dir=args.output_dir)
    print(json.dumps(out,sort_keys=True,indent=2))


if __name__=="__main__":
    main()

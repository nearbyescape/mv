"""Oct 7–15 Binance futures public-history PROXY backtest, never original V7.

Requires recorded 5m historical OI stats, taker-volume stats, futures trade
klines and settled funding rates. Historical exact 20-level live depth,
spread, book impact, premium publication times, and actual fills are missing.
Consequently reported returns are a DIFFERENT, PARTIAL-GATE RESEARCH PROXY.

No orders, subscriptions, authentication, production DB, or secrets.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import build_opener, ProxyHandler, Request

from .core import PARAMETERS, POLICY_SHA, SYMBOLS, IST

ORIGIN="https://fapi.binance.com"
ROUTES={
    "klines":("/fapi/v1/klines","open",1500),
    "oi":("/futures/data/openInterestHist","timestamp",500),
    "taker":("/futures/data/takerlongshortRatio","timestamp",500),
    "funding":("/fapi/v1/fundingRate","fundingTime",1000),
}
PERIOD_MS=300000
START=datetime(2026,10,7,tzinfo=IST)
END=datetime(2026,10,16,tzinfo=IST)
FEE_SLIPPAGE_BPS=D(PARAMETERS["per_side_fee_slippage_bps"])
COST=FEE_SLIPPAGE_BPS/D(10000)
STOP_FRAC=D(PARAMETERS["stop_distance_pct"])/100
GROSS_TARGET=D(PARAMETERS["gross_target_R"])
HORIZON_BARS=24
COOLDOWN_MS=PARAMETERS["same_symbol_cooldown_ms"]
MAX_OPEN=PARAMETERS["max_active_paper_ideas"]
# No system proxy, alternate endpoint, order routes or credentials.
OPENER=build_opener(ProxyHandler({}))


def _utc_ms(dt):
    return int(dt.astimezone(timezone.utc).timestamp()*1000)


def _request(path, params):
    if path not in [v[0] for v in ROUTES.values()]:
        raise ValueError("Historical input path is not allowlisted")
    query=urlencode(params)
    req=Request(ORIGIN+path+"?"+query,headers={
        "Accept":"application/json",
        "User-Agent":"mv-v7-oct-history-research-proxy/1",
    },method="GET")
    try:
        with OPENER.open(req, timeout=18) as response:
            body=response.read(2_500_001)
            if len(body)>2_500_000:
                raise ValueError("Unexpected large historical API response")
            output=json.loads(body)
    except HTTPError as exc:
        if exc.code in (418,429,451):
            raise RuntimeError(
                f"STOP_NO_RETRY_BINANCE_HTTP_{exc.code} on {path}"
            ) from exc
        raise RuntimeError(f"HTTP_{exc.code} on {path}; stop, no fallback host") from exc
    except (URLError,TimeoutError) as exc:
        raise RuntimeError(f"Public history unavailable at {path}: {type(exc).__name__}") from exc
    if not isinstance(output,list):
        raise ValueError(f"Unexpected response for {path}; refusing fabricated records")
    return output


def _get_time(row, key):
    ts=int(row[0] if key=="open" else row[key])
    if not 1_000_000_000_000<=ts<=9_999_999_999_999:
        raise ValueError("Unexpected millisecond history timestamp")
    return ts


def _download(symbol, family, start_ms, end_ms):
    """Bounded, non-cursor historical requests in UTC time slices.

    Do NOT page with last_ts+1 on Binance 5m statistic endpoints:
    startTime may be bucket-rounded and repeat the previous page.
    Instead query nonoverlapping <=24h windows with response_limit >=288
    (maximum possible 5m points per UTC day). Reject a window that
    returns data exclusively from OUTSIDE the requested time span.
    Preserve any genuine sparse 5m gaps in the output and coverage.
    """
    if symbol not in SYMBOLS or family not in ROUTES:
        raise ValueError("Unsupported fixed-origin market family")
    if type(start_ms) is not int or type(end_ms) is not int or not 0<start_ms<end_ms:
        raise ValueError("Invalid historical UTC bounds")
    path,key,limit=ROUTES[family]
    chunk_ms=288*PERIOD_MS  # at most 288 five-minute samples
    records={}
    segment_count=0
    segment_start=start_ms
    while segment_start<end_ms:
        segment_end=min(segment_start+chunk_ms,end_ms)
        params={
            "symbol":symbol,
            "startTime":segment_start,
            "endTime":segment_end-1,
            "limit":limit,
        }
        if family=="klines":
            params["interval"]="5m"
        elif family in ("oi","taker"):
            params["period"]="5m"
        items=_request(path,params)
        if len(items)>limit:
            raise ValueError(
                f"HISTORY_RESPONSE_EXCEEDS_LIMIT symbol={symbol} family={family} "
                f"count={len(items)} max={limit}"
            )
        valid=0
        timestamps=[]
        for row in items:
            ts=_get_time(row,key)
            timestamps.append(ts)
            if isinstance(row,dict) and row.get("symbol",symbol)!=symbol:
                raise ValueError(
                    f"HISTORY_SYMBOL_MISMATCH symbol={symbol} family={family}"
                )
            if segment_start<=ts<segment_end:
                if ts in records and records[ts]!=row:
                    raise ValueError(
                        f"HISTORY_CONFLICTING_TIMESTAMP symbol={symbol} "
                        f"family={family} stamp={ts}"
                    )
                records[ts]=row
                valid+=1
        if items and valid==0:
            raise ValueError(
                "HISTORY_OUTSIDE_REQUESTED_SEGMENT "
                f"symbol={symbol} family={family} "
                f"window_start={segment_start} window_end_exclusive={segment_end} "
                f"returned_count={len(items)} "
                f"returned_first={min(timestamps)} returned_last={max(timestamps)}. "
                "No cursor skip, interpolation or fallback; inspect provider data."
            )
        # Sparse/empty segments are allowed but explicit missing points
        # remain missing and are reported in per-day source coverage.
        segment_start=segment_end
        segment_count+=1
        if segment_count>30:
            raise RuntimeError(f"Too many bounded segments {symbol} {family}")
        time.sleep(0.06)
    return [records[ts] for ts in sorted(records)]


def _sha_json(rows):
    return hashlib.sha256(
        json.dumps(rows,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()


def fetch_history(symbol, start_ms, end_ms, rawdir):
    if symbol not in SYMBOLS:
        raise ValueError("Symbol outside V7 frozen universe")
    out={}
    for family in ROUTES:
        # Versioned cache avoids reusing potentially incomplete snapshots
        # from the old last-timestamp pagination implementation.
        path=rawdir / f"{symbol}_{family}_{start_ms}_{end_ms}_UTC_DAY_V2.json"
        if path.exists():
            blob=json.loads(path.read_text())
            if blob.get("schema")!="UTC_DAY_SLICES_V2" or blob.get("input")!=[symbol,family,start_ms,end_ms]:
                raise ValueError("Cache is not certified for v2 UTC slices")
            rows=blob["rows"]
            if _sha_json(rows)!=blob["sha256"]:
                raise ValueError(f"Cached historical input checksum mismatch: {path}")
        else:
            rows=_download(symbol,family,start_ms,end_ms)
            if not rows:
                raise ValueError(f"NO_HISTORICAL_{family.upper()} for {symbol}: STOP")
            blob={
                "schema":"UTC_DAY_SLICES_V2",
                "input":[symbol,family,start_ms,end_ms],
                "sha256":_sha_json(rows),
                "rows":rows,
            }
            rawdir.mkdir(parents=True,exist_ok=True)
            tmp=path.with_suffix(".partial")
            if tmp.exists():
                raise ValueError(f"Unexpected incomplete cache {tmp}")
            tmp.write_text(json.dumps(blob,separators=(",",":")))
            tmp.replace(path)
        out[family]=rows
    return out


def _asof(times, rows, cutoff, max_age):
    i=bisect_right(times,cutoff)-1
    # Do not reuse the exact same 5-minute metric in the next window.
    if i<0 or cutoff-times[i]>=max_age:
        return None,i
    return rows[i],i


def _ratio(row):
    buy=D(str(row["buyVol"]))
    sell=D(str(row["sellVol"]))
    if sell<=0 or buy<0:
        return None
    return buy/sell


def _simulate(kline, idx, side, funding_events):
    """Worst-case same-bar stop-first; 8bps per side reference cost.

    Entry is *next* five-minute bar OPEN; no exact book or execution fill.
    Missing candle sequences cause a censored outcome, never a winner.
    """
    if idx+HORIZON_BARS>len(kline):
        return None
    bars=kline[idx:idx+HORIZON_BARS]
    if any(int(bars[j][0])!=int(bars[0][0])+j*PERIOD_MS
           for j in range(HORIZON_BARS)):
        return None
    direction=1 if side=="LONG" else -1
    entry=D(str(bars[0][1]))
    risk=entry*STOP_FRAC
    stop=entry-direction*risk
    target=entry+direction*risk*GROSS_TARGET
    exit_px=D(str(bars[-1][4]))
    exit_ms=int(bars[-1][6])
    reason="TIME_EXIT"
    for bar in bars:
        op,hi,lo=(D(str(bar[i])) for i in (1,2,3))
        if direction==1:
            if op<=stop:
                exit_px=op;reason="STOP_GAP"
            elif lo<=stop:
                exit_px=stop;reason="STOP_OR_BOTH"
            elif hi>=target:
                exit_px=target;reason="TARGET"
        else:
            if op>=stop:
                exit_px=op;reason="STOP_GAP"
            elif hi>=stop:
                exit_px=stop;reason="STOP_OR_BOTH"
            elif lo<=target:
                exit_px=target;reason="TARGET"
        if reason!="TIME_EXIT":
            exit_ms=int(bar[6])
            break
    funding=D(0)
    entry_ms=int(bars[0][0])
    for event in funding_events:
        when=int(event["fundingTime"])
        if entry_ms<when<=exit_ms:
            # Positive funding is paid by LONG, received by SHORT.
            funding-=direction*entry*D(str(event["fundingRate"]))
    modeled_net=direction*(exit_px-entry)-(entry+exit_px)*COST+funding
    net_r=modeled_net/(risk+entry*COST)
    return {
        "symbol":None,"side":side,
        "entry_ms":entry_ms,"exit_ms":exit_ms,
        "entry":str(entry),"exit":str(exit_px),"reason":reason,
        "net_R":float(net_r),"funding_quote_per_coin":str(funding),
        "ambiguous_intrabar_stop_first":reason=="STOP_OR_BOTH",
    }


def _signal_candidates(symbol, data, period_start, period_end):
    klines=data["klines"]
    oi=data["oi"]
    taker=data["taker"]
    if not klines or not oi or not taker:
        raise ValueError(f"Insufficient historical inputs for {symbol}")
    oi_ts=[int(r["timestamp"]) for r in oi]
    taker_end=[int(r["timestamp"])+PERIOD_MS for r in taker]
    checks=Counter()
    candidates=[]
    # Count late-day signals as censored rather than invisibly dropping them.
    for i in range(2,len(klines)-1):
        bar=klines[i]
        t=int(bar[0])
        if t<period_start or t>=period_end:
            continue
        checks["five_minute_decision_points"]+=1
        if i>=1 and int(klines[i-1][0])!=t-PERIOD_MS:
            checks["missing_prior_candle"]+=1
            continue
        hr=datetime.fromtimestamp(t/1000,IST).hour
        if hr<9 or hr>=23:
            checks["outside_IST_session"]+=1
            continue
        # Require at least one full 5m bar between data's reported
        # timestamp/period END and signal decision; publication delay
        # still unknown. Entry itself is delayed ANOTHER 5m bar.
        prior,oi_i=_asof(oi_ts,oi,t-PERIOD_MS,PERIOD_MS)
        if oi_i<1 or prior is None:
            checks["missing_or_stale_OI"]+=1
            continue
        prev=oi[oi_i-1]
        if not 240_000<=int(prior["timestamp"])-int(prev["timestamp"])<=360_000:
            checks["OI_period_not_five_minutes"]+=1
            continue
        last,taker_i=_asof(taker_end,taker,t-PERIOD_MS,PERIOD_MS)
        if last is None:
            checks["missing_or_stale_taker"]+=1
            continue
        try:
            prev_oi=D(str(prev["sumOpenInterest"]))
            oi_change=(D(str(prior["sumOpenInterest"]))-prev_oi)/prev_oi*100
            ratio=_ratio(last)
        except (KeyError,ArithmeticError):
            checks["malformed_public_metric"]+=1
            continue
        if prev_oi<=0 or ratio is None:
            checks["invalid_OI_or_volume"]+=1
            continue
        if not (D(PARAMETERS["minimum_open_interest_increase_pct"]) <=oi_change
                <=D(PARAMETERS["maximum_open_interest_jump_pct"])):
            checks["OI_not_confirmed"]+=1
            continue
        if ratio>=D(PARAMETERS["minimum_taker_buy_sell_ratio_for_long"]):
            side="LONG"
        elif ratio<=D(PARAMETERS["maximum_taker_buy_sell_ratio_for_short"]):
            side="SHORT"
        else:
            checks["taker_ratio_not_directional"]+=1
            continue
        checks["partial_rule_proxy_signals"]+=1
        candidates.append({
            "t":t,"index":i,"symbol":symbol,"side":side,
            "oi_change_pct":str(oi_change),"taker_ratio":str(ratio),
        })
    return klines,candidates,checks


def compute_backtest(history, *, start_ms, end_ms):
    checks=Counter()
    eligible=[]
    inputs={}
    for symbol in SYMBOLS:
        klines,candidates,c=_signal_candidates(
            symbol,history[symbol],start_ms,end_ms
        )
        checks.update(c)
        inputs[symbol]=klines
        eligible.extend(candidates)
    eligible.sort(key=lambda item:(item["t"],item["symbol"]))
    accepted=[]
    cooldown={}
    active=[]
    for signal in eligible:
        t=signal["t"]
        if t-cooldown.get(signal["symbol"],-10**20)<COOLDOWN_MS:
            checks["blocked_3hr_symbol_cooldown"]+=1
            continue
        active=[when for when in active if when>t-HORIZON_BARS*PERIOD_MS]
        if len(active)>=MAX_OPEN:
            checks["blocked_4slot_paper_portfolio"]+=1
            continue
        active.append(t)
        cooldown[signal["symbol"]]=t
        signal=dict(signal)
        signal["entry_index"]=signal["index"]+1
        accepted.append(signal)
    results=[]
    censored=Counter()
    for signal in accepted:
        symbol=signal["symbol"]
        trade=_simulate(
            inputs[symbol],signal["entry_index"],
            signal["side"],history[symbol]["funding"],
        )
        if trade is None:
            censored[symbol]+=1
            continue
        trade["symbol"]=symbol
        trade["signal_ms"]=signal["t"]
        trade["signal_oi_pct"]=signal["oi_change_pct"]
        trade["signal_taker_ratio"]=signal["taker_ratio"]
        results.append(trade)
    results.sort(key=lambda x:(x["exit_ms"],x["symbol"]))
    if checks["partial_rule_proxy_signals"] != (
        len(accepted)
        + checks["blocked_3hr_symbol_cooldown"]
        + checks["blocked_4slot_paper_portfolio"]
    ):
        raise ValueError("Candidate funnel count mismatch")
    if len(accepted)!=len(results)+sum(censored.values()):
        raise ValueError("Proxy trade outcome count mismatch")
    return checks,accepted,results,censored


def _stats(trades):
    vals=[float(t["net_R"]) for t in trades]
    n=len(vals)
    wins=[v for v in vals if v>0]
    losses=[v for v in vals if v<0]
    if not n:
        return {"trades":0,"positive_fraction":None,"mean_net_R":None,
                "total_net_R":None,"profit_factor":None,"max_drawdown_pct":None,
                "modeled_equity_change_pct_at_0_5pct_risk":None}
    eq=1.
    peak=1.
    dd=0.
    for x in vals:
        eq*=max(0,1+0.005*x)
        peak=max(eq,peak)
        dd=max(dd,1-eq/peak)
    return {
        "trades":n,
        "positive_fraction":len(wins)/n,
        "mean_net_R":sum(vals)/n,
        "total_net_R":sum(vals),
        "profit_factor":sum(wins)/abs(sum(losses)) if losses else None,
        "max_drawdown_pct":100*dd,
        "modeled_equity_change_pct_at_0_5pct_risk":100*(eq-1),
    }


def main():
    p=argparse.ArgumentParser(description="Binance Oct7-15 historical proxy; NOT V7Sonic")
    p.add_argument("--allow-public-history",action="store_true",required=True)
    p.add_argument("--confirm-proxy-not-v7",action="store_true",required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args()
    if not args.allow_public_history or not args.confirm_proxy_not_v7:
        raise SystemExit("Explicit proxy/network confirmations required")
    if not args.output_dir.is_absolute() or args.output_dir.is_symlink():
        raise ValueError("Require absolute real output directory")
    args.output_dir.mkdir(parents=True,exist_ok=True)
    start_ms=_utc_ms(START)
    # Oct 15 may still be in progress; never request future periods.
    end_ms=min(_utc_ms(END),int(time.time()*1000)//PERIOD_MS*PERIOD_MS)
    if end_ms<=start_ms:
        raise RuntimeError("Historic backtest date interval has not started")
    # 24hr pre-roll for OI/taker availability on the first IST day.
    raw_start=start_ms-86_400_000
    print(json.dumps({
        "kind":"PUBLIC_HISTORICAL_PROXY_ACQUISITION",
        "period_start_IST":START.isoformat(),
        "exclusive_period_end_IST":datetime.fromtimestamp(end_ms/1000,IST).isoformat(),
        "historical_funding_complete_only_to_last_record":True,
        "is_original_V7_backtest":False,
        "no_telegram_or_orders":True,
    }),flush=True)
    rawdir=args.output_dir/"raw"
    hist={}
    manifest={}
    for symbol in SYMBOLS:
        hist[symbol]=fetch_history(symbol,raw_start,end_ms,rawdir)
        manifest[symbol]={
            family:{"records":len(records),"sha256":_sha_json(records)}
            for family,records in hist[symbol].items()
        }
        print(symbol,{k:v["records"] for k,v in manifest[symbol].items()},flush=True)
    checks,eligible,trades,censored=compute_backtest(
        hist,start_ms=start_ms,end_ms=end_ms
    )
    all_days={
        datetime.fromtimestamp(t["signal_ms"]/1000,IST).date().isoformat()
        for t in trades
    }
    day_ids=[]
    cursor=START.date()
    while _utc_ms(datetime(cursor.year,cursor.month,cursor.day,tzinfo=IST))<end_ms:
        day_ids.append(cursor.isoformat())
        cursor+=timedelta(days=1)
    by_day={
        day:_stats([t for t in trades
                    if datetime.fromtimestamp(t["signal_ms"]/1000,IST).date().isoformat()==day])
        for day in day_ids
    }
    by_day_source_coverage={}
    for day in day_ids:
        day_dt=datetime.fromisoformat(day).replace(tzinfo=IST)
        dstart=max(start_ms,_utc_ms(day_dt))
        dend=min(end_ms,_utc_ms(day_dt+timedelta(days=1)))
        expected=(dend-dstart)//PERIOD_MS
        by_day_source_coverage[day]={
            "nominal_closed_5m_intervals":expected,
            "markets":{
                symbol:{
                    family:sum(
                        dstart<=_get_time(row,ROUTES[family][1])<dend
                        for row in hist[symbol][family]
                    )
                    for family in ("klines","oi","taker")
                }
                for symbol in SYMBOLS
            },
        }
    result={
        "kind":"OCT_7_TO_15_2026_PARTIAL_RULE_PROXY_NOT_V7",
        "original_V7_policy_sha256_reference_only":POLICY_SHA,
        "source":"PUBLIC_BINANCE_USDM_5M_OI_TAKER_KLINES_FUNDING",
        "includes_real_top20_orderbook":False,
        "includes_original_book_imbalance_spread_impact_gates":False,
        "includes_original_funding_horizon_exclusion":False,
        "includes_actual_premium_publication_delay":False,
        "is_complete_V7_backtest":False,
        "is_realistic_executable_fill_certificate":False,
        "start_IST":START.isoformat(),
        "end_exclusive_IST":datetime.fromtimestamp(end_ms/1000,IST).isoformat(),
        "input_manifest":manifest,
        "coverage":{
            symbol:{
                family:{
                    "in_window_records":sum(
                        start_ms<=_get_time(row,ROUTES[family][1])<end_ms
                        for row in records
                    ),
                    "first_record_ms":_get_time(records[0],ROUTES[family][1]) if records else None,
                    "last_record_ms":_get_time(records[-1],ROUTES[family][1]) if records else None,
                    "nominal_expected_5m_intervals":(
                        (end_ms-start_ms)//PERIOD_MS
                        if family!="funding" else None
                    ),
                }
                for family,records in hist[symbol].items()
            }
            for symbol in SYMBOLS
        },
        "thresholds":{
            "oi_min_pct":PARAMETERS["minimum_open_interest_increase_pct"],
            "oi_max_pct":PARAMETERS["maximum_open_interest_jump_pct"],
            "taker_long_min":PARAMETERS["minimum_taker_buy_sell_ratio_for_long"],
            "taker_short_max":PARAMETERS["maximum_taker_buy_sell_ratio_for_short"],
            "risk_stop_pct":PARAMETERS["stop_distance_pct"],
            "gross_target_R":PARAMETERS["gross_target_R"],
            "cost_per_side_bps":PARAMETERS["per_side_fee_slippage_bps"],
            "hold_max_minutes":HORIZON_BARS*5,
            "source_reporting_lag_min_assumed":5,
            "extra_entry_delay_min":5,
            "same_bar_both_hits":"STOP_FIRST_CONSERVATIVE",
        },
        "filter_counts":dict(checks),
        "preportfolio_proxy_candidates":checks["partial_rule_proxy_signals"],
        "accepted_after_original_like_cooldown_and_slots":len(eligible),
        "censored_missing_full_outcome_bars":dict(censored),
        "descriptive_proxy_results":_stats(trades),
        "by_symbol":{symbol:_stats([t for t in trades if t["symbol"]==symbol]) for symbol in SYMBOLS},
        "by_signal_day_IST":by_day,
        "by_day_source_coverage_IST":by_day_source_coverage,
        "trades":trades,
        "verdict":"PROXY_ONLY_CANNOT_APPROVE_OR_REJECT_ORIGINAL_V7",
        "warnings":[
            "Public 5m historical open-interest observations are NOT instantaneous open-interest samples",
            "Public aggregated data omit V7's original top-20 book, spread, impact and depth-consistency checks",
            "Historical OI and taker report publication timing is unknown; assumed 5m reporting lag plus 5m entry delay",
            "5m price candles cannot prove fills, intra-candle path, adverse selection, or exact funding mark",
            "Missing or late-public OI/taker records are excluded rather than interpolated",
            "A 5m bar touching both stop and target is conservatively counted as a stop",
            "The exchange reports UTC timestamps; requested days are IST (starting previous UTC evening)",
            "Funding events are retrospectively applied to positions; original 120m pre-funding exclusion cannot be reconstructed",
            "Single 8-day calendar window is descriptive, not held-out evidence for profitability",
        ],
        "exchange_orders":0,"telegram_messages":0,
    }
    out=args.output_dir/f"proxy-report-{start_ms}-{end_ms}.json"
    tmp=out.with_suffix(".partial")
    tmp.write_text(json.dumps(result,indent=2,sort_keys=True))
    tmp.replace(out)
    print(json.dumps({
        "kind":"HISTORICAL_PROXY_RESULT_NOT_V7",
        "path":str(out),
        "period":(result["start_IST"],result["end_exclusive_IST"]),
        "preportfolio_proxy_candidates":result["preportfolio_proxy_candidates"],
        "accepted_after_cooldown_and_slots":result["accepted_after_original_like_cooldown_and_slots"],
        "observed_proxy_trades":result["descriptive_proxy_results"]["trades"],
        "metrics":result["descriptive_proxy_results"],
        "filter_counts":result["filter_counts"],
        "censored":result["censored_missing_full_outcome_bars"],
        "verdict":result["verdict"],
    },indent=2),flush=True)


if __name__=="__main__":
    main()

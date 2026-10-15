"""Offline synthetic proofs for the separate Oct7-15 historical proxy.

These tests require NO Binance access and cannot submit orders/Telegram.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from app.microstructure import oct_history_proxy as proxy
from app.microstructure.core import IST


def _bar(ts, op="100", hi="101", lo="99", close="100"):
    return [
        ts,op,hi,lo,close,"500",
        ts+proxy.PERIOD_MS-1,"50000",250,"250","25000","0",
    ]


def test_stop_before_target_in_same_5m_bar():
    start=proxy._utc_ms(datetime(2026,10,7,10,0,tzinfo=IST))
    bars=[_bar(start+i*proxy.PERIOD_MS) for i in range(24)]
    # First future 5m candle touches BOTH +/-0.75% stop and +1.35% target.
    bars[0]=_bar(start,op="100",hi="103",lo="98",close="100")
    long=proxy._simulate(bars,0,"LONG",[])
    short=proxy._simulate(bars,0,"SHORT",[])
    assert long["reason"]=="STOP_OR_BOTH"
    assert short["reason"]=="STOP_OR_BOTH"
    assert long["net_R"] < -1
    assert short["net_R"] < -1


def test_funding_cost_is_applied_to_history_proxy():
    start=proxy._utc_ms(datetime(2026,10,7,10,0,tzinfo=IST))
    bars=[_bar(start+i*proxy.PERIOD_MS,op="100",hi="100.1",lo="99.9",close="100")
          for i in range(24)]
    funding=[{"fundingTime":start+20*proxy.PERIOD_MS,
              "fundingRate":"0.001"}]
    a=proxy._simulate(bars,0,"LONG",[])
    b=proxy._simulate(bars,0,"LONG",funding)
    c=proxy._simulate(bars,0,"SHORT",funding)
    assert b["net_R"] < a["net_R"]
    assert c["net_R"] > a["net_R"]


def test_missing_or_out_of_order_candles_censor_outcome():
    start=proxy._utc_ms(datetime(2026,10,7,10,0,tzinfo=IST))
    bars=[_bar(start+i*proxy.PERIOD_MS) for i in range(24)]
    assert proxy._simulate(bars[:23],0,"LONG",[]) is None
    bars[12][0]+=1
    assert proxy._simulate(bars,0,"LONG",[]) is None


def test_history_signals_cannot_use_current_unpublished_metric():
    t=proxy._utc_ms(datetime(2026,10,7,10,0,tzinfo=IST))
    candles=[_bar(t+(i-3)*proxy.PERIOD_MS,hi="100.1",lo="99.9") for i in range(35)]
    old=t-2*proxy.PERIOD_MS
    prior=t-proxy.PERIOD_MS
    data={
        "klines":candles,
        "oi":[
            {"timestamp":old,"sumOpenInterest":"10000"},
            {"timestamp":prior,"sumOpenInterest":"10040"},
            {"timestamp":t,"sumOpenInterest":"10095"},
        ],
        "taker":[
            {"timestamp":old,"buyVol":"200","sellVol":"100"},
            {"timestamp":t,"buyVol":"1000","sellVol":"50"},
        ],
        "funding":[],
    }
    bars,candidates,counts=proxy._signal_candidates(
        "BTCUSDT",data,t,t+proxy.PERIOD_MS*30
    )
    assert candidates
    assert candidates[0]["t"]==t
    assert candidates[0]["oi_change_pct"]=="0.400"
    assert candidates[0]["taker_ratio"]=="2"
    assert candidates[0]["side"]=="LONG"
    assert counts["partial_rule_proxy_signals"]>=1


def test_binance_network_is_allowlisted_and_operator_opt_in():
    from urllib.error import HTTPError
    from io import BytesIO
    with pytest.raises(ValueError,match="not allowlisted"):
        proxy._request("/fapi/v1/order",{"symbol":"BTCUSDT"})
    with pytest.raises(ValueError,match="not allowlisted"):
        proxy._request("/fapi/v1/depth",{"symbol":"BTCUSDT"})
    assert proxy.ORIGIN=="https://fapi.binance.com"
    assert proxy.PARAMETERS["minimum_open_interest_increase_pct"]=="0.20"
    assert proxy.HORIZON_BARS==24


def test_proxy_portfolio_cooldown_and_four_slot_cap_without_fake_fills():
    start=proxy._utc_ms(datetime(2026,10,7,9,0,tzinfo=IST))
    data={}
    for s in proxy.SYMBOLS:
        candles=[_bar(start+(i-3)*proxy.PERIOD_MS,hi="100.1",lo="99.9")
                 for i in range(36)]
        data[s]={
            "klines":candles,
            "oi":[
                {"timestamp":start-2*proxy.PERIOD_MS,"sumOpenInterest":"10000"},
                {"timestamp":start-proxy.PERIOD_MS,"sumOpenInterest":"10030"},
            ],
            "taker":[{
                "timestamp":start-2*proxy.PERIOD_MS,"buyVol":"200","sellVol":"100"
            }],
            "funding":[],
        }
    checks,candidates,trades,censored=proxy.compute_backtest(
        data,start_ms=start,end_ms=start+60*60_000
    )
    assert checks["partial_rule_proxy_signals"]==6
    # Candidate return value is the ACCEPTED four-slot portfolio, not
    # the pre-portfolio six eligible raw directional observations.
    assert len(candidates)==4
    assert checks["blocked_4slot_paper_portfolio"]==2
    assert len(trades)==4
    assert not censored
    assert all(t["net_R"]<0 for t in trades)



def test_history_utc_partitions_no_overlap_even_if_provider_returns_boundary():
    from unittest.mock import patch
    start=proxy._utc_ms(datetime(2026,10,7,0,0,tzinfo=IST))
    end=start+3*288*proxy.PERIOD_MS
    calls=[]
    def fake_get(path,params):
        calls.append((path,params.copy()))
        assert params["symbol"]=="BTCUSDT"
        assert params["startTime"]>=start
        assert params["endTime"]<end
        # Return aligned 5m records and one adjacent, out-of-range
        # boundary to prove it is neither used nor silently duplicated.
        first=params["startTime"]
        after=params["endTime"]+1
        assert after-first==288*proxy.PERIOD_MS
        return [
            _bar(ts)
            for ts in range(first,after+proxy.PERIOD_MS,proxy.PERIOD_MS)
        ]
    with patch.object(proxy,"_request",side_effect=fake_get):
        with patch.object(proxy.time,"sleep"):
            output=proxy._download("BTCUSDT","klines",start,end)
    assert len(calls)==3
    assert len(output)==3*288
    assert int(output[0][0])==start
    assert int(output[-1][0])==end-proxy.PERIOD_MS
    assert [c[1]["startTime"] for c in calls]==[
        start,start+288*proxy.PERIOD_MS,start+576*proxy.PERIOD_MS,
    ]


def test_out_of_range_page_produces_safe_diagnostic_not_fake_history():
    from unittest.mock import patch
    start=proxy._utc_ms(datetime(2026,10,7,0,0,tzinfo=IST))
    bad=[{"timestamp":start-proxy.PERIOD_MS,
          "sumOpenInterest":"10000"}]
    with patch.object(proxy,"_request",return_value=bad):
        with patch.object(proxy.time,"sleep"):
            with pytest.raises(ValueError,match="HISTORY_OUTSIDE_REQUESTED_SEGMENT.*BTCUSDT.*oi"):
                proxy._download("BTCUSDT","oi",start,start+288*proxy.PERIOD_MS)


def test_history_sparse_api_window_remains_missing_never_interpolated():
    from unittest.mock import patch
    start=proxy._utc_ms(datetime(2026,10,7,0,0,tzinfo=IST))
    records=[
        {"timestamp":start,"sumOpenInterest":"10000"},
        {"timestamp":start+2*proxy.PERIOD_MS,"sumOpenInterest":"10020"},
    ]
    with patch.object(proxy,"_request",return_value=records):
        with patch.object(proxy.time,"sleep"):
            result=proxy._download("BTCUSDT","oi",start,start+288*proxy.PERIOD_MS)
    assert len(result)==2
    assert [r["timestamp"] for r in result]==[
        start,start+2*proxy.PERIOD_MS
    ]

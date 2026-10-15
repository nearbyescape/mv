"""Offline synthetic acceptance for prospective order-flow paper research.

Tests never contact Binance, private endpoints, Telegram or the user's VPS.
"""
from __future__ import annotations

import asyncio
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json

import httpx
import pytest

from app.microstructure.core import (
    SYMBOLS,MODEL,HORIZONS_MS,PARAMETERS,normalize,classify,digest,
)
from app.microstructure.journal import (
    open_journal,record_snapshot,report,verify_chain,
)
from app.microstructure.public import capture_symbol,PATHS


BASE=int(datetime(2026,10,15,4,30,5,tzinfo=timezone.utc).timestamp()*1000)


def raw_for(symbol,now,*,step=0,stale_taker=False):
    # Previous COMPLETED Binance 5m activity period. Each later sample
    # moves to a new and already finished period.
    bucket=(now//300000-1)*300000
    if stale_taker:
        bucket-=300000
    depth={
        "lastUpdateId":1000+step,
        "bids":[[str(100-i*.01), "20"] for i in range(20)],
        "asks":[[str(100.02+i*.01), "10"] for i in range(20)],
    }
    return {
        "server_time":{"serverTime":now-100},
        "depth":depth,
        "open_interest":{
            "symbol":symbol,
            "time":now-200,
            "openInterest":str(10000+40*step),
        },
        "taker":[{
            "timestamp":bucket,"buyVol":"1000","sellVol":"600",
        }],
        "premium":{
            "symbol":symbol,"time":now-100,
            "markPrice":"100.01","lastFundingRate":"0.00010",
            "nextFundingTime":now+4*3_600_000,
        },
    }


def sample(step=0,symbol="BTCUSDT",stale_taker=False):
    now=BASE+step*300000
    return normalize(
        symbol,raw_for(symbol,now,step=step,stale_taker=stale_taker),
        now,started_ms=now-700
    )


def test_pure_normalization_evidence_and_paper_candidate():
    a,b=sample(0),sample(1)
    assert b["depth_consistency"]=="REST_POINT_SNAPSHOT_NOT_SEQUENCE_PROVED"
    assert b["eligible_for_live_trades"] is False
    assert b["observed_at_ms"]>a["observed_at_ms"]
    proposal=classify(a,b)
    assert proposal["status"]=="PAPER_CANDIDATE", proposal
    assert proposal["direction"]=="LONG"
    assert proposal["policy"]==MODEL
    assert proposal["confidence_probability"] is None
    assert proposal["no_telegram_publication"] is True
    assert proposal["no_exchange_execution"] is True
    assert float(proposal["modeled_target_net_R"])>1.1


def test_missing_stale_or_crossed_public_data_fail_closed():
    for kind in ("missing","stale","crossed","wrong_symbol","missing_oi"):
        r=raw_for("BTCUSDT",BASE)
        if kind=="missing":
            del r["premium"]
        elif kind=="stale":
            r["premium"]["time"]=BASE-200000
        elif kind=="crossed":
            r["depth"]["asks"][0][0]="99.00"
        elif kind=="wrong_symbol":
            r["open_interest"]["symbol"]="ETHUSDT"
        elif kind=="missing_oi":
            r["open_interest"]["openInterest"]="-1"
        with pytest.raises(ValueError):
            normalize("BTCUSDT",r,BASE,started_ms=BASE-1000)


def test_taker_period_must_be_completed():
    r=raw_for("BTCUSDT",BASE)
    r["taker"]=[{"timestamp":BASE//300000*300000,"buyVol":"100","sellVol":"100"}]
    with pytest.raises(ValueError,match="completed"):
        normalize("BTCUSDT",r,BASE,started_ms=BASE-1000)


def test_classifier_stale_or_noncontiguous_will_abstain():
    a,b=sample(0),sample(1)
    assert classify(a,{**b,"taker_period_start_ms":a["taker_period_start_ms"]})["reason"]=="STALE_TAKER_PERIOD"
    assert classify(a,{**b,"depth_last_update_id":a["depth_last_update_id"]})["reason"]=="STALE_DEPTH"
    assert classify(a,{**b,"observed_at_ms":b["observed_at_ms"]+1_800_000})["reason"]=="NONCONTIGUOUS_OBSERVATIONS"


def test_opposite_book_taker_rejected_not_force_signal():
    a,b=sample(0),sample(1)
    b["book_imbalance"]="-0.30"
    assert classify(a,b)["reason"]=="TAKER_AND_BOOK_DISAGREE"


def test_outside_ist_session_rejected():
    a,b=sample(0),sample(1)
    b["observed_at_ms"]=BASE+14*3_600_000
    a["observed_at_ms"]=b["observed_at_ms"]-300000
    assert classify(a,b)["reason"]=="OUTSIDE_SIGNAL_SESSION"


def test_immutable_paper_ledger_and_future_outcome_marks():
    with TemporaryDirectory() as dirname:
        dbpath=Path(dirname)/"prospective.db"
        with open_journal(dbpath) as journal:
            first=record_snapshot(journal,sample(0))
            assert first["decision"]["reason"]=="WAIT_FOR_PREVIOUS_REAL_SAMPLE"
            second=record_snapshot(journal,sample(1))
            assert second["decision"]["status"]=="PAPER_CANDIDATE",second
            assert record_snapshot(journal,sample(1))["stored"] is False
            for step in range(2,28):
                record_snapshot(journal,sample(step))
            overview=report(journal)
            assert overview["per_symbol_verified_samples"]["BTCUSDT"]==28
            assert overview["paper_candidate_total"]==1
            for horizon in ("15m","30m","60m","120m"):
                assert overview["marked_horizons"][horizon]["observations"]==1
                assert overview["marked_horizons"][horizon]["intrabar_stop_target_order_verified"] is False
            assert not overview["client_publication_authorized"]
            assert overview["orders_submitted"]==0
            assert overview["telegram_messages_sent"]==0
        with open_journal(dbpath,readonly=True) as reader:
            assert verify_chain(reader,"BTCUSDT")==28


def test_hash_chain_detects_modified_observation():
    with TemporaryDirectory() as dirname:
        with open_journal(Path(dirname)/"journal.db") as db:
            record_snapshot(db,sample(0))
            db.execute(
                "UPDATE observations SET payload='{}' WHERE symbol='BTCUSDT'"
            )
            db.commit()
            with pytest.raises(ValueError,match="tampering"):
                verify_chain(db,"BTCUSDT")


def test_fixed_https_get_routes_and_no_exchange_orders():
    now=BASE
    raw=raw_for("BTCUSDT",now,step=0)
    requested=[]
    def handler(request):
        requested.append((request.method,request.url.path,str(request.url.host)))
        assert request.method=="GET"
        assert request.url.host=="fapi.binance.com"
        assert not request.headers.get("X-MBX-APIKEY")
        lookup={v:k for k,v in PATHS.items()}
        return httpx.Response(200,json=raw[lookup[request.url.path]])
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.microstructure.public.wall_ms",side_effect=[BASE-700,BASE]):
                return await capture_symbol(client,"BTCUSDT")
    item=asyncio.run(scenario())
    assert item["symbol"]=="BTCUSDT"
    assert len(requested)==5
    assert all(method=="GET" for method,path,host in requested)


def test_rate_limited_no_retries_and_no_order_endpoints():
    called=[]
    def handler(request):
        called.append(request.url.path)
        return httpx.Response(429)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await capture_symbol(client,"BTCUSDT")
    with pytest.raises(RuntimeError,match="RATE_LIMIT"):
        asyncio.run(scenario())
    assert called==["/fapi/v1/time"]


def test_http_451_is_explicit_no_retry_or_fallback_host():
    paths=[]
    def handler(request):
        paths.append((request.method,str(request.url.host),request.url.path))
        return httpx.Response(451)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await capture_symbol(client,"BTCUSDT")
    with pytest.raises(RuntimeError,match="PUBLIC_BINANCE_DATA_HTTP_451"):
        asyncio.run(scenario())
    assert paths==[("GET","fapi.binance.com","/fapi/v1/time")]


def test_network_never_accessed_without_exact_cli_opt_in():
    from argparse import Namespace
    from app.microstructure.cli import _observe
    args=Namespace(
        db="/tmp/should-not-be-used.sqlite",
        allow_public_market_data=False,
        confirm_paper_only=False,
        iterations=1, interval_seconds=300,
    )
    with patch("app.microstructure.cli.capture_all") as fetch:
        with pytest.raises(ValueError,match="both explicit"):
            asyncio.run(_observe(args))
        fetch.assert_not_called()


def test_unmodeled_funding_boundary_rejects_trade():
    a,b=sample(0),sample(1)
    b["next_funding_ms"]=b["observed_at_ms"]+3_600_000
    assert classify(a,b)["reason"]=="FUNDING_WINDOW_UNMODELED"



def test_sampler_rechecks_persisted_observation_deadline():
    """Actual VPS gap: 299.904s is NOT the required >=300s."""
    from app.microstructure.cli import _seconds_until_capture
    with TemporaryDirectory() as dirname:
        path=Path(dirname)/"journal.sqlite"
        first=sample(0)
        with open_journal(path) as db:
            record_snapshot(db,first)
            last=first["observed_at_ms"]
            observed_gap_ms=299_904
            assert _seconds_until_capture(db,last+observed_gap_ms,300)>2
            assert _seconds_until_capture(db,last+300_000,300)==2
            assert _seconds_until_capture(db,last+302_000,300)==0
            assert _seconds_until_capture(db,last+302_000,315)>0
            assert _seconds_until_capture(db,last+315_000,315)==0
        # Scheduler reads the durable journal again after worker restart.
        with open_journal(path) as reopened:
            assert _seconds_until_capture(reopened,last+299_904,300)>2
            assert _seconds_until_capture(reopened,last+302_000,300)==0


def test_sampler_uses_latest_market_not_earliest_symbol_timestamp():
    """Six REST requests finish at different times; BNB can be last."""
    from app.microstructure.cli import _seconds_until_capture
    with TemporaryDirectory() as dirname:
        with open_journal(Path(dirname)/"journal.sqlite") as db:
            btc=sample(0,"BTCUSDT")
            bnb=sample(0,"BNBUSDT")
            bnb["observed_at_ms"]+=1200
            record_snapshot(db,btc)
            record_snapshot(db,bnb)
            # BTC alone would now be >=302s old. BNB still needs 1.2s.
            assert _seconds_until_capture(
                db,btc["observed_at_ms"]+302_000,300
            )>1
            assert _seconds_until_capture(
                db,bnb["observed_at_ms"]+302_000,300
            )==0



def test_offline_quality_audit_reports_overlapping_causes():
    from app.microstructure.quality import quality_report
    with TemporaryDirectory() as dirname:
        path=Path(dirname)/"quality.sqlite"
        with open_journal(path) as db:
            record_snapshot(db,sample(0))
            record_snapshot(db,sample(1))
            record_snapshot(db,sample(2))
            eth0=sample(0,"ETHUSDT")
            eth1=sample(1,"ETHUSDT")
            eth1["next_funding_ms"]=eth1["observed_at_ms"]+3_600_000
            record_snapshot(db,eth0)
            record_snapshot(db,eth1)
            result=quality_report(db,last_samples_per_symbol=3)
        assert result["total_adjacent_pairs"]==3
        assert result["first_failure_classifier_totals"]["PRE_PORTFOLIO_CANDIDATE"]==2
        assert result["first_failure_classifier_totals"]["FUNDING_WINDOW_UNMODELED"]==1
        assert result["preportfolio_candidates_not_actual_published_signals"]==2
        assert result["symbols"]["BTCUSDT"]["valid_timing_pairs"]==2
        assert result["symbols"]["BTCUSDT"]["preportfolio_candidates"]==2
        assert result["symbols"]["ETHUSDT"]["independent_blockers_overlapping"]["FUNDING_WITHIN_120M"]==1
        assert result["rules_or_thresholds_changed"] is False
        assert result["client_publication_authorized"] is False
        assert result["actual_execution_or_intrabar_fill_verified"] is False
        # No database mutation: reader can use read-only permissions.
        with open_journal(path,readonly=True) as readonly:
            assert quality_report(readonly,last_samples_per_symbol=2)["total_adjacent_pairs"]==2
            assert report(readonly)["paper_candidate_total"]==1


def test_quality_audit_detects_taker_staleness_independent_of_other_blockers():
    from app.microstructure.quality import quality_report
    with TemporaryDirectory() as dirname:
        with open_journal(Path(dirname)/"quality.sqlite") as db:
            old=sample(0)
            current=sample(1)
            current["taker_period_start_ms"]=old["taker_period_start_ms"]
            current["next_funding_ms"]=current["observed_at_ms"]+3_600_000
            record_snapshot(db,old)
            assert record_snapshot(db,current)["decision"]["reason"]=="STALE_TAKER_PERIOD"
            result=quality_report(db,last_samples_per_symbol=2)
            assert result["first_failure_classifier_totals"]["STALE_TAKER_PERIOD"]==1
            assert result["independent_blockers_overlapping_totals"]["TAKER_NOT_ADVANCED"]==1
            assert result["independent_blockers_overlapping_totals"]["FUNDING_WITHIN_120M"]==1


def test_quality_audit_rejects_corrupt_evidence_and_bad_window():
    from app.microstructure.quality import quality_report
    with TemporaryDirectory() as dirname:
        with open_journal(Path(dirname)/"quality.sqlite") as db:
            record_snapshot(db,sample(0))
            with pytest.raises(ValueError,match="last_samples_per_symbol"):
                quality_report(db,last_samples_per_symbol=1)
            db.execute("UPDATE observations SET payload='{}'")
            db.commit()
            with pytest.raises(ValueError,match="tampering"):
                quality_report(db,last_samples_per_symbol=2)



def test_transient_public_data_gaps_are_bounded_and_non_mutating(capsys):
    import httpx
    from argparse import Namespace
    from unittest.mock import AsyncMock
    from app.microstructure.cli import _observe
    with TemporaryDirectory() as dirname:
        path=Path(dirname)/"paper.sqlite"
        args=Namespace(
            db=str(path),allow_public_market_data=True,
            confirm_paper_only=True,iterations=0,interval_seconds=300,
        )
        with patch(
            "app.microstructure.cli.capture_all",
            side_effect=[
                httpx.ConnectTimeout("temporary first attempt"),
                httpx.ReadTimeout("temporary second attempt"),
                httpx.RemoteProtocolError("temporary third attempt"),
            ]
        ) as capture, patch(
            "app.microstructure.cli.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleeping:
            with pytest.raises(
                RuntimeError,
                match="PUBLIC_RESEARCH_COLLECTION_HALTED_REQUIRES_OPERATOR_REVIEW",
            ):
                asyncio.run(_observe(args))
            assert capture.call_count==3
            assert sleeping.await_count==2
            assert sleeping.await_args_list[0].args==(300,)
            assert sleeping.await_args_list[1].args==(300,)
        lines=[json.loads(s) for s in capsys.readouterr().out.splitlines()]
        assert [x["kind"] for x in lines]==[
            "PUBLIC_MARKET_PAPER_COLLECTION_GAP",
            "PUBLIC_MARKET_PAPER_COLLECTION_GAP",
            "PUBLIC_MARKET_PAPER_COLLECTION_GAP",
        ]
        assert [x["retry_after_seconds"] for x in lines]==[300,300,None]
        assert all(x["observations_committed"]==0 for x in lines)
        with open_journal(path,readonly=True) as db:
            assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]==0


def test_public_rate_limit_or_region_denial_never_auto_retries():
    from argparse import Namespace
    from unittest.mock import AsyncMock
    from app.microstructure.cli import _observe
    for reason in (
        "EXCHANGE_RATE_LIMIT_NO_AUTO_RETRY",
        "PUBLIC_BINANCE_DATA_HTTP_451_REGION_OR_LEGAL_RESTRICTION",
    ):
        with TemporaryDirectory() as dirname:
            args=Namespace(
                db=str(Path(dirname)/"paper.sqlite"),
                allow_public_market_data=True,
                confirm_paper_only=True,iterations=0,interval_seconds=300,
            )
            with patch(
                "app.microstructure.cli.capture_all",
                side_effect=RuntimeError(reason),
            ) as capture, patch(
                "app.microstructure.cli.asyncio.sleep",new_callable=AsyncMock,
            ) as sleeping:
                with pytest.raises(RuntimeError,match=reason):
                    asyncio.run(_observe(args))
                capture.assert_called_once()
                sleeping.assert_not_awaited()


def test_http_503_is_transient_but_other_http4xx_halts():
    from argparse import Namespace
    from unittest.mock import AsyncMock
    from app.microstructure.cli import _observe
    req=httpx.Request("GET","https://fapi.binance.com/fapi/v1/time")
    for status,should_retry in ((503,True),(400,False),(403,False)):
        with TemporaryDirectory() as dirname:
            path=Path(dirname)/"paper.sqlite"
            args=Namespace(
                db=str(path),allow_public_market_data=True,
                confirm_paper_only=True,iterations=0,interval_seconds=300,
            )
            err=httpx.HTTPStatusError(
                "HTTP response not OK",request=req,
                response=httpx.Response(status,request=req),
            )
            with patch("app.microstructure.cli.capture_all",side_effect=err) as capture, patch(
                "app.microstructure.cli.asyncio.sleep",new_callable=AsyncMock,
            ) as sleep:
                with pytest.raises(Exception):
                    asyncio.run(_observe(args))
                assert capture.call_count==(3 if should_retry else 1)
                assert sleep.await_count==(2 if should_retry else 0)
            with open_journal(path,readonly=True) as db:
                assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]==0


def test_one_shot_public_capture_retains_no_retry_contract():
    from argparse import Namespace
    from unittest.mock import AsyncMock
    from app.microstructure.cli import _observe
    with TemporaryDirectory() as dirname:
        args=Namespace(
            db=str(Path(dirname)/"paper.sqlite"),
            allow_public_market_data=True,
            confirm_paper_only=True,iterations=1,interval_seconds=300,
        )
        with patch(
            "app.microstructure.cli.capture_all",
            side_effect=httpx.ReadTimeout("temporary error"),
        ) as capture, patch(
            "app.microstructure.cli.asyncio.sleep",new_callable=AsyncMock,
        ) as sleep:
            with pytest.raises(httpx.ReadTimeout):
                asyncio.run(_observe(args))
            capture.assert_called_once()
            sleep.assert_not_awaited()



def test_single_transient_gap_recovers_and_commits_full_six_coin_batch(capsys):
    from argparse import Namespace
    from unittest.mock import AsyncMock
    from app.microstructure.cli import _observe
    with TemporaryDirectory() as dirname:
        path=Path(dirname)/"paper.sqlite"
        args=Namespace(
            db=str(path),allow_public_market_data=True,
            confirm_paper_only=True,iterations=0,interval_seconds=300,
        )
        full=[sample(0,symbol) for symbol in SYMBOLS]
        with patch(
            "app.microstructure.cli.capture_all",
            side_effect=[
                httpx.ReadTimeout("temporary transport interruption"),
                full,
                RuntimeError("PUBLIC_BINANCE_DATA_HTTP_451_REGION_OR_LEGAL_RESTRICTION"),
            ],
        ) as capture, patch(
            "app.microstructure.cli.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep:
            with pytest.raises(RuntimeError,match="PUBLIC_BINANCE_DATA_HTTP_451"):
                asyncio.run(_observe(args))
            assert capture.call_count==3
            assert sleep.await_count==1
            assert sleep.await_args.args==(300,)
        output=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert len(output)==2
        assert output[0]["kind"]=="PUBLIC_MARKET_PAPER_COLLECTION_GAP"
        assert output[1]["kind"]=="PUBLIC_MARKET_PAPER_CAPTURE"
        assert all(x["stored"] is True for x in output[1]["decisions"])
        with open_journal(path,readonly=True) as db:
            assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]==6
            assert report(db)["paper_candidate_total"]==0

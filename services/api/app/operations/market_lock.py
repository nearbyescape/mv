"""Serialize complete source writes with publication/hold reads on PostgreSQL."""
import hashlib
from sqlalchemy import text


def lock_market(session,symbol):
    if session.get_bind().dialect.name!="postgresql":
        return
    schema=session.scalar(text("SELECT current_schema()"))
    identity=int.from_bytes(hashlib.sha256(("mv-market:"+schema+":"+symbol).encode()).digest()[:8],"big") & ((1<<63)-1)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"),{"key":identity})

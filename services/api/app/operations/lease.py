from contextlib import contextmanager
import hashlib
from sqlalchemy import text
from uuid import uuid4
from app.database import engine, Session
from app.models import ServiceLease
from app.market.binance import now_ms

OWNERS = {}


class LeaseLost(BaseException):
    """Fatal fencing failure, intentionally outside routine reconnect exception handling."""


def assert_fence(session, name):
    if session.get_bind().dialect.name != "postgresql":
        return
    owner = OWNERS.get(name)
    row = session.get(ServiceLease, name, with_for_update=True, populate_existing=True)
    if not owner or not row or row.owner != owner:
        raise LeaseLost(f"{name} ownership lost; stop this worker")
    row.heartbeat = now_ms()


@contextmanager
def worker_transaction(name, factory=None):
    # Lock ownership in the SAME transaction as every worker mutation. A successor
    # cannot take ownership while an old transaction is still committing.
    with (factory or Session).begin() as session:
        assert_fence(session, name)
        yield session


@contextmanager
def singleton(name):
    """Advisory singleton plus a transactional ownership token fences disconnected workers."""
    if engine.dialect.name != "postgresql":
        yield
        return
    with engine.connect() as connection:
        schema=connection.scalar(text("SELECT current_schema()"))
        identity=int.from_bytes(hashlib.sha256(("mv-signal:"+schema+":"+name).encode()).digest()[:8],"big") & ((1<<63)-1)
        if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"),{"key":identity}):
            raise RuntimeError(f"A {name} worker already owns the database singleton lock")
        try:
            connection.commit()
            owner = str(uuid4())
            with Session.begin() as session:
                row=session.get(ServiceLease,name,with_for_update=True) or ServiceLease(name=name)
                row.owner,row.heartbeat=owner,now_ms()
                session.add(row)
            OWNERS[name]=owner
            yield
        finally:
            OWNERS.pop(name,None)
            try:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"),{"key":identity})
            except Exception:
                # A disconnected lock is already released; never hide a fencing failure.
                pass

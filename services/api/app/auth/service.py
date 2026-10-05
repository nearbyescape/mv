import hashlib
import re
import secrets
from contextlib import contextmanager
from threading import BoundedSemaphore
from uuid import uuid4
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from sqlalchemy import select, update
from fastapi import HTTPException, Request
from app.models import User, UserSession, Invite, AuthThrottle, AuditEvent
from app.config import get_settings
from app.market.binance import now_ms

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
HASH_BUDGET = BoundedSemaphore(2)


@contextmanager
def hashing_budget():
    if not HASH_BUDGET.acquire(timeout=1):
        raise HTTPException(status_code=429, detail="Sign-in service busy; retry shortly", headers={"Retry-After":"3"})
    try:
        yield
    finally:
        HASH_BUDGET.release()


def hash_password(password):
    with hashing_budget():
        return HASHER.hash(password)


def verify_password(encoded, password):
    with hashing_budget():
        return HASHER.verify(encoded, password)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def email(value):
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("Valid email address required")
    return value


def audit(session, actor, action, detail=None):
    session.add(AuditEvent(id=str(uuid4()), actor_id=actor, action=action, created_at=now_ms(), detail_json=detail or {}))


def principal(session, token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(status_code=401, detail="Sign in required")
    login = session.get(UserSession, digest(token))
    user = session.get(User, login.user_id) if login else None
    if not login or login.revoked_at is not None or login.expires_at <= now_ms() or not user or not user.enabled:
        raise HTTPException(status_code=401, detail="Session expired or revoked")
    return user


def user_view(user):
    return {"id":user.id,"email":user.email,"name":user.name,"role":user.role,"enabled":user.enabled,"created_at":user.created_at}


def begin_session(session, user):
    token = secrets.token_urlsafe(32)
    now = now_ms()
    expiry = now+get_settings().session_hours*3_600_000
    session.add(UserSession(token_hash=digest(token), user_id=user.id, created_at=now, expires_at=expiry, revoked_at=None))
    return {"token":token,"expires_at":expiry,"user":user_view(user)}


def throttle(session, identity, maximum, window_ms=900000):
    """Serialized durable budgets; failed logins cannot bypass limits by restarting an API."""
    key, now = digest(identity), now_ms()
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(insert(AuthThrottle).values(key=key,count=0,window_at=now).on_conflict_do_nothing(index_elements=[AuthThrottle.key]))
    row = session.get(AuthThrottle, key, with_for_update=True)
    if now-row.window_at >= window_ms:
        row.count, row.window_at = 0, now
    if row.count >= maximum:
        session.commit()
        raise HTTPException(status_code=429, detail="Too many attempts; try again later", headers={"Retry-After":"900"})
    row.count += 1
    session.commit()


def login(session, address, password, ip):
    address = email(address)
    throttle(session, "login-ip:"+ip, 60)
    throttle(session, "login-email:"+address, 10)
    user = session.scalar(select(User).where(User.email==address).with_for_update())
    try:
        verify_password(user.password_hash if user else DUMMY_HASH, password)
        valid = bool(user and user.enabled)
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid:
        audit(session,None,"login-failed",{"email_hash":digest(address)})
        session.commit()
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    if HASHER.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    result = begin_session(session,user)
    audit(session,user.id,"login")
    session.commit()
    return result


def create_invite(session, address, role, actor=None, hours=24):
    address = email(address)
    if role not in ("admin","operator","viewer") or not 1 <= hours <= 72:
        raise ValueError("Invalid invite role or expiry")
    if session.scalar(select(User.id).where(User.email==address)):
        raise ValueError("Account already exists")
    session.execute(update(Invite).where(Invite.email==address,Invite.used_at.is_(None)).values(used_at=now_ms()))
    token, now = secrets.token_urlsafe(32), now_ms()
    session.add(Invite(token_hash=digest(token),email=address,role=role,created_at=now,expires_at=now+hours*3_600_000,used_at=None,created_by=actor))
    audit(session,actor,"invite-created",{"email":address,"role":role})
    return {"token":token,"expires_at":now+hours*3_600_000,"email":address,"role":role}


def accept(session, token, address, name, password, ip):
    throttle(session,"invite-ip:"+ip,30)
    address = email(address)
    if not 15 <= len(password) <= 128 or not 1 <= len(name.strip()) <= 80:
        raise HTTPException(status_code=422,detail="Use a name and a password with 15–128 characters")
    invitation = session.get(Invite,digest(token),with_for_update=True)
    if not invitation or invitation.used_at is not None or invitation.expires_at <= now_ms() or invitation.email != address:
        raise HTTPException(status_code=400, detail="Invitation is invalid, expired or already used")
    hashed = hash_password(password)
    changed = session.execute(update(Invite).where(Invite.token_hash==invitation.token_hash,Invite.used_at.is_(None),Invite.expires_at>now_ms()).values(used_at=now_ms()))
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=409,detail="Invitation has already been used")
    user=User(id=str(uuid4()),email=address,name=name.strip(),role=invitation.role,password_hash=hashed,enabled=True,created_at=now_ms())
    session.add(user)
    from sqlalchemy.exc import IntegrityError
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409,detail="Invitation could not be accepted; contact your administrator") from exc
    result=begin_session(session,user)
    audit(session,user.id,"invite-accepted")
    session.commit()
    return result


def check_service(request: Request):
    settings = get_settings()
    if settings.environment == "production" and not secrets.compare_digest(request.headers.get("x-mv-service-key",""),settings.service_key):
        raise HTTPException(status_code=401,detail="Application gateway required")

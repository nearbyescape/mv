from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update, func, text
from sqlalchemy.orm import Session
from app.database import get_session
from app.models import User, UserSession, Invite, AuditEvent
from app.market.binance import now_ms
from . import service
from app.main import authorize

router=APIRouter()
DB=Annotated[Session,Depends(get_session)]
Actor=Annotated[User,Depends(authorize)]


class Credentials(BaseModel):
    email:str=Field(min_length=3,max_length=254)
    password:str=Field(min_length=1,max_length=128)


class Accept(Credentials):
    token:str=Field(min_length=32,max_length=128)
    name:str=Field(min_length=1,max_length=80)


def client_ip(request):
    # Only the private gateway may supply this in production (service-key checked).
    from app.config import get_settings
    if get_settings().environment=="production":
        return request.headers.get("x-mv-client-ip","unknown")[:100]
    return request.client.host if request.client else "local"


@router.post("/v1/auth/login",dependencies=[Depends(service.check_service)])
def login(payload:Credentials,request:Request,session:DB):
    try:
        return service.login(session,payload.email,payload.password,client_ip(request))
    except ValueError as exc:
        raise HTTPException(status_code=422,detail="Invalid account input") from exc


@router.post("/v1/auth/accept",dependencies=[Depends(service.check_service)])
def accept(payload:Accept,request:Request,session:DB):
    try:
        return service.accept(session,payload.token,payload.email,payload.name,payload.password,client_ip(request))
    except ValueError as exc:
        raise HTTPException(status_code=422,detail="Invalid account input") from exc


@router.get("/v1/auth/me")
def me(actor:Actor):
    from app.config import get_settings
    return {"user":service.user_view(actor),"authentication_required":get_settings().auth_required,"paper_enabled":get_settings().paper_enabled}


@router.post("/v1/auth/logout")
def logout(request:Request,actor:Actor,session:DB):
    header=request.headers.get("authorization","")
    if actor.id:
        session.execute(update(UserSession).where(UserSession.token_hash==service.digest(header.removeprefix("Bearer "))).values(revoked_at=now_ms()))
        service.audit(session,actor.id,"logout")
        session.commit()
    return {"signed_out":True}


class PasswordChange(BaseModel):
    current_password:str=Field(min_length=1,max_length=128)
    new_password:str=Field(min_length=15,max_length=128)


@router.post("/v1/auth/password")
def change_password(payload:PasswordChange,actor:Actor,session:DB):
    from argon2.exceptions import VerificationError
    if not actor.id:
        raise HTTPException(status_code=403,detail="Authenticated account required")
    service.throttle(session,"password:"+actor.id,10)
    try:
        service.verify_password(actor.password_hash,payload.current_password)
    except VerificationError as exc:
        raise HTTPException(status_code=400,detail="Current password is incorrect") from exc
    actor.password_hash=service.hash_password(payload.new_password)
    session.execute(update(UserSession).where(UserSession.user_id==actor.id,UserSession.revoked_at.is_(None)).values(revoked_at=now_ms()))
    result=service.begin_session(session,actor)
    service.audit(session,actor.id,"password-changed")
    session.commit()
    return result


@router.get("/v1/admin/users")
def users(actor:Actor,session:DB):
    return {"users":[service.user_view(u) for u in session.scalars(select(User).order_by(User.created_at))],
            "invites":[{"id":i.token_hash,"email":i.email,"role":i.role,"expires_at":i.expires_at,"used_at":i.used_at} for i in session.scalars(select(Invite).order_by(Invite.created_at.desc()).limit(100))]}


class InviteInput(BaseModel):
    email:str=Field(min_length=3,max_length=254)
    role:Literal["admin","operator","viewer"]="viewer"


@router.post("/v1/admin/invites")
def create_invite(payload:InviteInput,actor:Actor,session:DB):
    if not actor.id:
        raise HTTPException(status_code=403,detail="Bootstrap an owner account on the server first")
    try:
        result=service.create_invite(session,payload.email,payload.role,actor.id)
        session.commit()
        from app.config import get_settings
        return {**{k:v for k,v in result.items() if k!="token"},"accept_url":get_settings().public_origin+"/login#invite="+result["token"]}
    except ValueError as exc:
        raise HTTPException(status_code=409,detail=str(exc)) from exc


@router.delete("/v1/admin/invites/{identity}")
def revoke_invite(identity:str,actor:Actor,session:DB):
    invite=session.get(Invite,identity)
    if not invite:
        raise HTTPException(status_code=404,detail="Invitation not found")
    invite.used_at=now_ms()
    service.audit(session,actor.id,"invite-revoked",{"email":invite.email})
    session.commit()
    return {"revoked":True}


class UserChange(BaseModel):
    role:Literal["admin","operator","viewer"]
    enabled:bool


@router.patch("/v1/admin/users/{identity}")
def change_user(identity:str,payload:UserChange,actor:Actor,session:DB):
    if session.get_bind().dialect.name=="postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(679012347)"))
    else:
        # authorize has already opened a read transaction; lock acquisition precedes mutation.
        session.commit()
        session.execute(text("BEGIN IMMEDIATE"))
    user=session.get(User,identity,with_for_update=True,populate_existing=True)
    if not user:
        raise HTTPException(status_code=404,detail="Account not found")
    count=session.scalar(select(func.count()).select_from(User).where(User.role=="admin",User.enabled.is_(True)))
    if user.role=="admin" and user.enabled and count==1 and (payload.role!="admin" or not payload.enabled):
        raise HTTPException(status_code=409,detail="Keep at least one enabled administrator")
    user.role,user.enabled=payload.role,payload.enabled
    session.execute(update(UserSession).where(UserSession.user_id==user.id,UserSession.revoked_at.is_(None)).values(revoked_at=now_ms()))
    service.audit(session,actor.id,"account-updated",{"user_id":user.id,"role":user.role,"enabled":user.enabled})
    session.commit()
    return service.user_view(user)


@router.get("/v1/admin/audit")
def audit(actor:Actor,session:DB):
    return {"events":[{"id":e.id,"actor_id":e.actor_id,"action":e.action,"time":e.created_at,"detail":e.detail_json} for e in session.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100))]}

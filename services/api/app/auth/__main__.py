"""Owner bootstrap is a server-side CLI, never an anonymous web endpoint."""
import argparse
import json
from sqlalchemy import select, text
from app.database import Session
from app.models import User, Invite
from app.config import get_settings
from .service import create_invite
from .service import hash_password, email, audit
from app.models import UserSession
from app.market.binance import now_ms
from sqlalchemy import update
from getpass import getpass

parser=argparse.ArgumentParser(description="Create the first owner invitation on the server")
parser.add_argument("command",choices=["bootstrap","reset-password"])
parser.add_argument("--email",required=True)
args=parser.parse_args()
password=None
if args.command=="reset-password":
    password=getpass("New password (15–128 characters): ")
    if not 15 <= len(password) <= 128 or password!=getpass("Repeat new password: "):
        raise SystemExit("Password length or confirmation failed")
with Session.begin() as session:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(679012347)"))
    else:
        session.execute(text("BEGIN IMMEDIATE"))
    if args.command=="reset-password":
        user=session.scalar(select(User).where(User.email==email(args.email)).with_for_update())
        if not user:
            raise SystemExit("Account not found")
        user.password_hash=hash_password(password)
        session.execute(update(UserSession).where(UserSession.user_id==user.id).values(revoked_at=now_ms()))
        audit(session,None,"server-password-reset",{"user_id":user.id})
        print("Password changed and all account sessions revoked.")
    elif session.scalar(select(User.id).where(User.role=="admin",User.enabled.is_(True))):
        raise SystemExit("An enabled owner already exists; use authenticated administration")
    else:
        result=create_invite(session,args.email,"admin",hours=24)
        print(json.dumps({"email":result["email"],"expires_at":result["expires_at"],"accept_url":get_settings().public_origin+"/login#invite="+result["token"]},indent=2))

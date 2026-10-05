"""Explicit operator diagnostics, not an invented trading signal."""
import argparse
import asyncio
import json
import httpx
from app.config import get_settings
from .provider import verify_destination,send,DeliveryError


async def check(test_message):
    settings=get_settings()
    async with httpx.AsyncClient(follow_redirects=False) as client:
        result=await verify_destination(client,settings)
        if test_message:
            identity=await send(client,settings,{"chat_id":settings.telegram_chat_id,
                "text":"MV Signal · Connection test\nTelegram delivery is connected.\nNew signals run daily from 09:00 AM to 11:00 PM IST.\nThis is a setup message, not a trading signal."})
            result["test_message_id"]=identity
    print(json.dumps(result))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--test-message",action="store_true")
    args=parser.parse_args()
    try:
        asyncio.run(check(args.test_message))
    except DeliveryError as exc:
        raise SystemExit("Telegram setup failed: "+exc.code) from None

"""Fixed-origin Bot API requests. Provider descriptions and URLs never enter logs."""
import json
import logging
import re
import httpx

for name in ("httpx", "httpcore"):
    logging.getLogger(name).setLevel(logging.WARNING)


class DeliveryError(Exception):
    def __init__(self, code, state="failed", retry_after=0):
        super().__init__(code)
        self.code, self.state, self.retry_after = code, state, retry_after


async def call(client, token, method, payload, sending=False):
    if not re.fullmatch(r"[0-9]{5,16}:[A-Za-z0-9_-]{20,150}", token) or method not in ("sendMessage","getMe","getChat","getChatMember"):
        raise DeliveryError("INVALID_BOT_CONFIGURATION")
    try:
        async with client.stream("POST",f"https://api.telegram.org/bot{token}/{method}",json=payload,timeout=10) as response:
            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks)>65_536:
                    raise DeliveryError("INVALID_PROVIDER_RESPONSE","unknown" if sending else "failed")
            try:
                body=json.loads(chunks)
            except (ValueError,UnicodeError):
                raise DeliveryError("INVALID_PROVIDER_RESPONSE","unknown" if sending else "failed") from None
            if not isinstance(body,dict):
                raise DeliveryError("INVALID_PROVIDER_RESPONSE","unknown" if sending else "failed")
            if response.status_code==429 or body.get("error_code")==429:
                parameters=body.get("parameters")
                seconds=parameters.get("retry_after",60) if isinstance(parameters,dict) else 60
                seconds=seconds if isinstance(seconds,int) and not isinstance(seconds,bool) else 60
                raise DeliveryError("RATE_LIMITED","retry",max(4,min(seconds,3600)))
            if response.status_code>=500:
                raise DeliveryError("PROVIDER_UNAVAILABLE","unknown" if sending else "failed")
            if response.status_code!=200 or body.get("ok") is not True or not isinstance(body.get("result"),dict):
                raise DeliveryError("BOT_UNAUTHORIZED" if response.status_code==401 else "CHAT_FORBIDDEN" if response.status_code==403 else "REQUEST_REJECTED")
            return body["result"]
    except (httpx.ConnectError,httpx.ConnectTimeout,httpx.PoolTimeout):
        raise DeliveryError("CONNECTION_UNAVAILABLE","retry",15) from None
    except httpx.HTTPError:
        # A write/read failure can occur AFTER Telegram accepted the message.
        raise DeliveryError("DELIVERY_UNCERTAIN","unknown" if sending else "failed") from None


async def send(client, settings, payload):
    if str(payload.get("chat_id"))!=settings.telegram_chat_id or not isinstance(payload.get("text"),str) or not 1<=len(payload["text"])<=4096:
        raise DeliveryError("INVALID_MESSAGE_PAYLOAD")
    result=await call(client,settings.telegram_token,"sendMessage",payload,True)
    identity=result.get("message_id")
    chat=result.get("chat")
    if not isinstance(identity,int) or isinstance(identity,bool) or identity<=0 or not isinstance(chat,dict) or str(chat.get("id"))!=settings.telegram_chat_id:
        raise DeliveryError("INVALID_DELIVERY_RECEIPT","unknown")
    return identity


async def verify_destination(client, settings):
    bot=await call(client,settings.telegram_token,"getMe",{})
    chat=await call(client,settings.telegram_token,"getChat",{"chat_id":settings.telegram_chat_id})
    if str(chat.get("id"))!=settings.telegram_chat_id or not isinstance(bot.get("id"),int) or bot.get("is_bot") is not True:
        raise DeliveryError("DESTINATION_MISMATCH")
    member=await call(client,settings.telegram_token,"getChatMember",{"chat_id":settings.telegram_chat_id,"user_id":bot["id"]})
    status=member.get("status")
    restricted=status=="restricted" and (not member.get("is_member") or not member.get("can_send_messages"))
    forbidden_channel=chat.get("type")=="channel" and status!="creator" and not (status=="administrator" and member.get("can_post_messages"))
    default_restricted=status=="member" and chat.get("type") in ("group","supergroup") and chat.get("permissions",{}).get("can_send_messages") is False
    if status in (None,"left","kicked") or restricted or forbidden_channel or default_restricted:
        raise DeliveryError("BOT_CANNOT_POST")
    return {"verified":True,"chat_id":settings.telegram_chat_id,"chat_type":chat.get("type"),"bot_status":status}

"""Twilio SMS. Inert (returns not_configured) until the three Twilio secrets exist."""
import os
import re
import asyncio
import logging
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
logger = logging.getLogger(__name__)


def _creds():
    load_dotenv(ENV_PATH, override=False)
    return (os.environ.get("TWILIO_ACCOUNT_SID", "").strip(), os.environ.get("TWILIO_AUTH_TOKEN", "").strip(),
            os.environ.get("TWILIO_PHONE_NUMBER", "").strip())


def sms_configured() -> bool:
    return all(_creds())


def normalize_phone(p: str) -> str | None:
    if not p:
        return None
    digits = re.sub(r"\D", "", p)
    if p.strip().startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


async def send_sms(to: str, body: str) -> dict:
    sid, token, from_ = _creds()
    if not (sid and token and from_):
        return {"sent": False, "reason": "not_configured"}
    num = normalize_phone(to)
    if not num:
        return {"sent": False, "reason": "invalid_phone"}

    def _send():
        from twilio.rest import Client
        return Client(sid, token).messages.create(to=num, from_=normalize_phone(from_) or from_, body=body)

    try:
        msg = await asyncio.to_thread(_send)
        return {"sent": True, "sid": msg.sid, "status": msg.status, "to": num}
    except Exception as e:  # noqa
        logger.error(f"SMS failed: {e}")
        detail = getattr(e, "msg", None) or str(e)
        return {"sent": False, "reason": "twilio_error", "detail": str(detail)[:300]}

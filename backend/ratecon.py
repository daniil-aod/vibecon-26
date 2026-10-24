"""Rate confirmation reader: Gemini reads the PDF and returns structured detention terms."""
import json
import os
import re
import uuid
import logging
from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType, TextDelta, StreamDone

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
logger = logging.getLogger(__name__)

MODELS = [("gemini", "gemini-3.1-pro-preview"), ("gemini", "gemini-2.5-flash")]

SYSTEM = """You are a freight-billing analyst. You read trucking rate confirmations (rate cons) and extract
the exact detention terms a carrier needs to bill a broker. You return ONLY a JSON object, no prose, no markdown fences.
Never invent values. If a value is not stated, use null and list the field in low_confidence."""

PROMPT = """Read the attached rate confirmation and return this JSON exactly (keys in this shape):
{
  "load_number": string|null,
  "broker": {"name": string|null, "contact_name": string|null, "email": string|null, "phone": string|null},
  "carrier_name": string|null,
  "linehaul_amount": number|null,
  "stops": [
    {"type": "pickup"|"delivery", "facility_name": string|null, "address": string|null,
     "appointment": string|null  // ISO 8601 local time like 2026-03-11T08:00 if stated
    }
  ],
  "detention": {
    "free_time_hours": number|null,            // free time per stop before detention starts
    "hourly_rate": number|null,                // USD per hour
    "billing_increment_minutes": number|null,  // e.g. 15, 30, 60 if stated
    "cap_amount": number|null,                 // max detention in USD if stated
    "cap_scope": "per_stop"|"per_day"|"per_load"|null,
    "notice_after_arrival_minutes": number|null,   // e.g. 'notify within 1 hour of arrival' -> 60
    "notice_before_expiry_minutes": number|null,   // e.g. 'notify before free time expires' -> 0 ; '30 min before' -> 30
    "notice_rule_text": string|null,               // short plain-English summary of the notice requirement
    "requires_signed_bol": boolean|null,
    "clause_text": string|null                     // the detention clause copied WORD FOR WORD from the document
  },
  "low_confidence": [string]   // dotted field names you are unsure about, e.g. "detention.cap_amount"
}
Rules: copy clause_text verbatim (all sentences about detention/notification). Do not guess numbers."""


def _parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("AI did not return JSON")
    return json.loads(t[start:end + 1])


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def normalize(data: dict) -> dict:
    det = data.get("detention") or {}
    for k in ("free_time_hours", "hourly_rate", "billing_increment_minutes", "cap_amount",
              "notice_after_arrival_minutes", "notice_before_expiry_minutes"):
        det[k] = _num(det.get(k))
    data["detention"] = det
    data["linehaul_amount"] = _num(data.get("linehaul_amount"))
    data["broker"] = data.get("broker") or {}
    data["stops"] = [s for s in (data.get("stops") or []) if isinstance(s, dict)]
    lc = set(data.get("low_confidence") or [])
    for k in ("free_time_hours", "hourly_rate"):
        if det.get(k) is None:
            lc.add(f"detention.{k}")
    if not data["broker"].get("email"):
        lc.add("broker.email")
    if not det.get("clause_text"):
        lc.add("detention.clause_text")
    data["low_confidence"] = sorted(lc)
    return data


async def extract_ratecon(pdf_path: str, mime: str = "application/pdf") -> dict:
    last_err = None
    for provider, model in MODELS:
        try:
            chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"ratecon-{uuid.uuid4()}",
                           system_message=SYSTEM).with_model(provider, model)
            out = []
            async for ev in chat.stream_message(UserMessage(text=PROMPT, file_contents=[
                    FileContentWithMimeType(file_path=pdf_path, mime_type=mime)])):
                if isinstance(ev, TextDelta):
                    out.append(ev.content)
                elif isinstance(ev, StreamDone):
                    break
            data = normalize(_parse_json("".join(out)))
            data["_model"] = model
            return data
        except Exception as e:  # noqa
            logger.warning(f"ratecon extract with {model} failed: {e}")
            last_err = e
    raise RuntimeError(f"Could not read the rate confirmation: {last_err}")

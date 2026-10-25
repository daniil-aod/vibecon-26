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
  "references": {"bol_number": string|null, "pro_number": string|null, "po_number": string|null, "shipment_date": string|null},
  "billing": {
    "billing_company": string|null,          // company that must receive the invoice (payor / accounts payable)
    "billing_address": string|null,
    "ap_email": string|null,                 // accounts-payable / invoicing email, ONLY if stated for invoices
    "submission_channel": "email"|"portal"|"other"|null,
    "portal_url": string|null,
    "submission_other_text": string|null,    // e.g. 'mail originals to ...', 'upload in Navisphere'
    "requires_attachment": boolean|null,     // invoice/docs must be attached to the email
    "notice_recipient": string|null,         // who must be told about detention (email or phone or name)
    "notice_method": "email"|"phone"|"portal"|"other"|null,
    "invoice_deadline_days": number|null,    // e.g. 'invoice within 30 days of delivery' -> 30
    "invoice_deadline_trigger": "delivery"|"departure"|"pod_receipt"|"other"|null,
    "deadline_timezone": string|null,
    "required_documents": [{"doc": "signed_bol"|"pod"|"lumper_receipt"|"detention_log"|"scale_ticket"|"other", "stop": "pickup"|"delivery"|"final"|"any", "label": string}],
    "approval_required": boolean|null,      // detention/accessorial must be pre-approved
    "approval_method": "email"|"phone"|"portal"|"revised_rate_con"|"other"|null,
    "approval_rule_text": string|null,
    "payment_terms_days": number|null,       // e.g. Net 30 -> 30. null if not stated
    "payment_terms_start": "invoice_submission"|"receipt_of_complete_docs"|"delivery"|"other"|null,
    "rounding_rule": "completed_increment"|"round_up"|"nearest"|"exact"|null,
    "billing_start_rule": "arrival"|"appointment_or_arrival_later"|null,
    "late_arrival_voids": boolean|null,      // detention not paid if the truck arrives late for the appointment
    "per_day_definition": "calendar_day"|"24h_block"|null,  // only if a per-day cap is stated AND defined
    "stop_terms": [{"stop_index": number, "free_time_hours": number|null, "hourly_rate": number|null, "eligible": boolean|null}]
  },
  "source_refs": {"<dotted field>": {"page": number|null, "text": string}},  // verbatim source sentence for each billing/detention value you filled
  "document_version": string|null,         // revision / version / date printed on the document
  "low_confidence": [string]   // dotted field names you are unsure about, e.g. "detention.cap_amount"
}
Rules: copy clause_text verbatim (all sentences about detention/notification). Do not guess numbers.
Never assume defaults (no assumed Net 30, no assumed 2 free hours, no assumed rate or deadline): use null when not stated.
If this is a broker-carrier agreement or billing instructions rather than a rate con, fill only what it states."""


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
    bill = data.get("billing") if isinstance(data.get("billing"), dict) else {}
    for k in ("invoice_deadline_days", "payment_terms_days"):
        bill[k] = _num(bill.get(k))
    bill["required_documents"] = [d for d in (bill.get("required_documents") or []) if isinstance(d, dict) and d.get("doc")]
    bill["stop_terms"] = [d for d in (bill.get("stop_terms") or []) if isinstance(d, dict)]
    # detention-math terms live with the other detention terms so there is one place to read them
    for k in ("rounding_rule", "billing_start_rule", "late_arrival_voids", "per_day_definition"):
        if bill.get(k) is not None and det.get(k) is None:
            det[k] = bill[k]
        bill.pop(k, None)
    data["billing"] = bill
    data["references"] = data.get("references") if isinstance(data.get("references"), dict) else {}
    data["source_refs"] = data.get("source_refs") if isinstance(data.get("source_refs"), dict) else {}
    data["low_confidence"] = sorted(lc)
    return data


async def extract_ratecon(pdf_path: str, mime: str = "application/pdf", doc_kind: str = "rate confirmation") -> dict:
    last_err = None
    for provider, model in MODELS:
        try:
            chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"ratecon-{uuid.uuid4()}",
                           system_message=SYSTEM).with_model(provider, model)
            out = []
            async for ev in chat.stream_message(UserMessage(text=f"Document type: {doc_kind}.\n" + PROMPT, file_contents=[
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

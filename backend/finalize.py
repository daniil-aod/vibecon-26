"""Load completion + detention billing finalization.

ONE shared entry point, finalize_load(), runs after: geofence departure, manual/driver departure, document upload,
dispatcher correction, approval or billing-term changes, and the cron recovery pass. It is idempotent and
single-flight per load (DB lock + dirty flag), so repeated pings, refreshes, uploads or concurrent cron never
duplicate invoices, packets or submissions.

Separate states are kept for: transport, documents, approvals, packet, submission and payment.
"""
import asyncio
import logging
import os
import types
from datetime import timedelta

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import core
import templates
from core import now_utc, iso, parse, compute_load_billing, canonical_hash, trail_hash, fmt_min
from packetpdf import build_billing_packet

logger = logging.getLogger("dockclock.finalize")
ctx = types.SimpleNamespace()

# simulate (default): no real email leaves the system; every submission is recorded as SIMULATED.
SUBMISSION_MODE = os.environ.get("BILLING_SUBMISSION_MODE", "simulate")
# The managed email helper only sends HTML (no attachment field), so packets go out as secure download links.
EMAIL_ATTACHMENTS_SUPPORTED = False
EVIDENCE_TAIL_MIN = 45
LOCK_SECONDS = 90
SEND_CLAIM_SECONDS = 120
MAX_ATTEMPTS = 3
RETENTION_POLICY = "keep_forever"  # originals and issued versions are never auto-deleted

DOC_LABELS = {"signed_bol": "Signed BOL", "pod": "Proof of delivery (POD)", "lumper_receipt": "Lumper receipt",
              "detention_log": "Detention / in-out log", "scale_ticket": "Scale ticket", "other": "Other document",
              "bol_photo": "BOL photo"}
METHOD_LABELS = {"email": "Email", "phone": "Phone call", "portal": "Portal", "revised_rate_con": "Revised signed rate con",
                 "other": "Other method"}


def init(**deps):
    ctx.__dict__.update(deps)


def _db():
    return ctx.db


def _terms(load):
    return load.get("billing_terms") or {}


def _sorted_stops(load):
    return sorted(load.get("stops", []), key=lambda x: x.get("seq", 0))


def _stop_label(s):
    return f"{(s.get('type') or 'stop').title()} {s.get('seq', 0) + 1}"


# ---------------------------------------------------------------- transport completion

def transport_state(load) -> dict:
    stops = _sorted_stops(load)
    if not stops or not any(s.get("arrived_at") for s in stops):
        return {"state": "not_started", "review_flags": []}
    flags = []
    for s in stops:
        if s.get("departed_at") and s.get("departed_source") == "geofence":
            if (load.get("confirmed_flags") or {}).get(s["id"]):
                continue
            acc = ((s.get("departed_coords") or {}).get("accuracy")) or 0
            dwell = (parse(s["departed_at"]) - parse(s["arrived_at"])).total_seconds() / 60 if s.get("arrived_at") else 0
            if acc and acc > 100:
                flags.append({"stop_id": s["id"], "code": "low_accuracy",
                              "message": f"{_stop_label(s)}: departure detected with weak GPS (±{int(acc)} m). Confirm the truck really left."})
            elif dwell < 10:
                flags.append({"stop_id": s["id"], "code": "short_stay",
                              "message": f"{_stop_label(s)}: only {int(dwell)} min on site. Confirm it was loaded/unloaded and not a drive-by."})
    if all(s.get("arrived_at") and s.get("departed_at") for s in stops):
        last = max(stops, key=lambda s: parse(s["departed_at"]))
        mc = load.get("manual_completion") or {}
        return {"state": "completed", "completed_at": last["departed_at"],
                "source": "dispatcher_manual_completion" if mc else last.get("departed_source"),
                "manual": mc or None, "review_flags": flags}
    return {"state": "in_progress", "review_flags": flags}


# ---------------------------------------------------------------- documents, approvals, obligations

def required_documents(load) -> list:
    t = _terms(load)
    req = t.get("required_documents")
    if not req and (load.get("term_sources") or {}).get("billing.required_documents") not in ("confirmed", "extracted", "agreement") \
            and (load.get("detention") or {}).get("requires_signed_bol"):
        req = [{"doc": "signed_bol", "stop": "final", "label": "Signed BOL at delivery"}]
    return req or []


def _stop_docs(s):
    return [{**d, "doc_type": d.get("doc_type") or "bol_photo"} for d in s.get("bol", [])]


def documents_state(load) -> dict:
    stops = _sorted_stops(load)
    missing, unverified = [], []
    for r in required_documents(load):
        scope = r.get("stop") or "final"
        targets = ([stops[-1]] if scope == "final" else [s for s in stops if s.get("type") == scope] if scope in ("pickup", "delivery")
                   else stops)
        label = r.get("label") or DOC_LABELS.get(r["doc"], r["doc"])
        need_sig = r["doc"] in ("signed_bol", "pod")
        ok_types = {"signed_bol", "pod", "bol_photo"} if need_sig else {r["doc"]}
        check = [targets[0]] if scope == "any" and targets else targets
        if scope == "any":
            docs = [d for s in stops for d in _stop_docs(s) if d["doc_type"] in ok_types]
            if not docs:
                missing.append({"stop_id": None, "doc": r["doc"], "message": f"{label}: not uploaded"})
            continue
        for s in check:
            docs = [d for d in _stop_docs(s) if d["doc_type"] in ok_types]
            if not docs:
                missing.append({"stop_id": s["id"], "doc": r["doc"], "message": f"{label} for {_stop_label(s)} ({s.get('facility_name')}): not uploaded"})
            elif need_sig and not any(d.get("signature_verified") for d in docs):
                unverified.append({"stop_id": s["id"], "doc": r["doc"],
                                   "message": f"{label} for {_stop_label(s)}: photo uploaded, signature not yet confirmed by a dispatcher"})
    state = "complete" if not missing and not unverified else "missing"
    return {"state": state if required_documents(load) else "none_required", "missing": missing, "unverified": unverified,
            "requirements_known": bool(_terms(load).get("required_documents")) or (load.get("detention") or {}).get("requires_signed_bol") is not None}


def approvals_state(load, billing) -> dict:
    t = _terms(load)
    req = t.get("approval_required")
    recs = load.get("approvals") or []
    if req is None:
        return {"state": "unknown", "required": None, "records": recs}
    if not req:
        return {"state": "not_required", "required": False, "records": recs}
    detained = [s for s in _sorted_stops(load) if billing["stops"][s["id"]]["raw_amount"] > 0]
    missing = [s for s in detained if not any(a.get("stop_id") in (s["id"], None) for a in recs)]
    return {"state": "missing" if missing else "approved", "required": True, "records": recs,
            "method": t.get("approval_method"), "missing": [{"stop_id": s["id"], "message":
                f"Detention approval for {_stop_label(s)} ({s.get('facility_name')}) not recorded"} for s in missing]}


def _notice_deadline(stop, det, billing_stop):
    """Contractual notice deadline (never the free-time expiry when the contract says otherwise)."""
    a = parse(billing_stop.get("billing_start_at") or stop.get("arrived_at"))
    if not a:
        return None
    c = []
    if det.get("notice_after_arrival_minutes"):
        c.append(a + timedelta(minutes=float(det["notice_after_arrival_minutes"])))
    if det.get("notice_before_expiry_minutes") is not None and billing_stop.get("free_expires_at"):
        c.append(parse(billing_stop["free_expires_at"]) - timedelta(minutes=float(det["notice_before_expiry_minutes"] or 0)))
    if not c and billing_stop.get("free_expires_at"):
        c.append(parse(billing_stop["free_expires_at"]))
    return min(c) if c else None


def obligations(load, billing, trans, fleet) -> list:
    """Distinct obligations: arrival/detention notice, accessorial authorization, documents, invoice, payment."""
    det, t = load.get("detention") or {}, _terms(load)
    method = t.get("notice_method")
    out = []
    for s in _sorted_stops(load):
        if not s.get("arrived_at"):
            continue
        b = billing["stops"][s["id"]]
        n = s.get("notice") or {}
        dl = _notice_deadline(s, det, b)
        sent = parse(n.get("sent_at"))
        if method in (None, "email"):
            st = ("on_time" if sent and dl and sent <= dl else "late" if sent else
                  "not_needed" if n.get("status") == "not_needed" else "missed" if n.get("status") == "missed" or (dl and now_utc() > dl and s.get("departed_at")) else
                  n.get("status") or "pending")
            out.append({"kind": "arrival_notice", "stop_id": s["id"], "stop": _stop_label(s), "label": "Detention notice",
                        "method": "Email" + ("" if method else " (method not stated in contract)"), "to": n.get("to"),
                        "due_at": iso(dl), "at": n.get("sent_at"), "status": st, "ref": n.get("email_id")})
        else:
            rec = next((r for r in (s.get("notice_records") or []) if r.get("method") == method), None)
            ra = parse((rec or {}).get("at"))
            st = ("on_time" if ra and dl and ra <= dl else "late" if ra else "missed" if dl and now_utc() > dl else "pending")
            out.append({"kind": f"notice_{method}", "stop_id": s["id"], "stop": _stop_label(s), "label": "Detention notice",
                        "method": METHOD_LABELS.get(method, method), "to": (rec or {}).get("to") or t.get("notice_recipient"),
                        "due_at": iso(dl), "at": (rec or {}).get("at"), "status": st, "ref": (rec or {}).get("reference"),
                        "note": "An email does not satisfy this requirement" if n.get("sent_at") else None})
    ap = approvals_state(load, billing)
    if ap["required"]:
        for m in ap.get("missing", []):
            out.append({"kind": "approval", "stop_id": m["stop_id"], "stop": None, "label": "Accessorial authorization",
                        "method": METHOD_LABELS.get(ap.get("method"), "Not stated"), "status": "missing", "to": None})
        for r in ap["records"]:
            out.append({"kind": "approval", "stop_id": r.get("stop_id"), "label": "Accessorial authorization",
                        "method": METHOD_LABELS.get(r.get("method"), r.get("method")), "to": r.get("approver"),
                        "at": r.get("at"), "status": "recorded", "ref": r.get("reference")})
    elif ap["state"] == "unknown":
        out.append({"kind": "approval", "label": "Accessorial authorization", "status": "not_recorded",
                    "method": "Requirement not stated"})
    if trans.get("state") == "completed":
        days = t.get("invoice_deadline_days")
        trig = t.get("invoice_deadline_trigger")
        due = parse(trans["completed_at"]) + timedelta(days=float(days)) if days and trig in ("delivery", "departure") else None
        sub = (load.get("completion") or {}).get("submission") or {}
        out.append({"kind": "invoice_submission", "label": "Final invoice submission",
                    "method": METHOD_LABELS.get(t.get("submission_channel"), "Not set"), "to": destination(load)["recipient"],
                    "due_at": iso(due), "at": sub.get("accepted_at"),
                    "status": sub.get("state") or "not_started",
                    "note": (f"Within {int(days)} days of {trig.replace('_', ' ')}" if days and trig else "Deadline not stated")})
    return out


# ---------------------------------------------------------------- destination + blockers

def destination(load) -> dict:
    t = _terms(load)
    ch = t.get("submission_channel")
    to = (t.get("ap_email") or "").strip()
    basis = "accounts payable"
    if not to and t.get("use_broker_contact_for_billing"):
        to, basis = ((load.get("broker") or {}).get("email") or "").strip(), "broker contact (configured as billing recipient)"
    return {"channel": ch, "recipient": to or None, "basis": basis if to else None, "company": t.get("billing_company"),
            "portal_url": t.get("portal_url"), "other_text": t.get("submission_other_text"),
            "requires_attachment": t.get("requires_attachment")}


def blockers(load, fleet, billing, trans, docs, appr) -> list:
    out = []
    det = load.get("detention") or {}
    mt = billing["missing_terms"]
    add = lambda code, msg, action: out.append({"code": code, "message": msg, "action": action})  # noqa: E731
    if "free_time_hours" in mt or "hourly_rate" in mt:
        add("terms_missing", "Free time and/or hourly rate are unknown, so no detention amount can be billed.",
            "Enter the free time and hourly rate from the rate con (Edit terms).")
    if det.get("billing_increment_minutes") in (None, "") and det.get("rounding_rule") != "exact":
        add("increment_unknown", "Billing increment is not confirmed (draft uses exact minutes).", "Confirm the billing increment (Edit terms).")
    if "per_day_definition" in mt:
        add("per_day_unclear", "The cap is 'per day' but the agreement's meaning of a day is not confirmed.",
            "Choose calendar day or 24-hour period in Edit terms, as stated in the agreement.")
    if "appointment" in mt:
        add("appointment_missing", "Billing starts at the appointment, but an appointment time is missing.", "Add the stop appointment.")
    d = destination(load)
    setup = load.get("billing_setup") or {}
    if not setup.get("confirmed_at"):
        add("destination_unconfirmed", "Billing destination and billing mode have not been confirmed for this load.",
            "Confirm where and how to bill (Billing setup).")
    if not d["channel"]:
        add("channel_unknown", "Submission method is not set (email, portal or other).", "Set the submission method in Billing setup.")
    elif d["channel"] == "email":
        if not d["recipient"] or not ctx.email_re.match(d["recipient"]):
            add("recipient_invalid", "No valid accounts-payable email for this payor.", "Enter the AP email, or mark the broker contact as the billing recipient.")
        if d["requires_attachment"] and not EMAIL_ATTACHMENTS_SUPPORTED:
            add("attachment_unsupported", "The payor requires attachments, but this email service can only send a secure PDF link.",
                "Submit through another channel (e.g. portal) or upload the downloaded packet manually.")
    if not (fleet.get("legal_name") and fleet.get("remittance_address")):
        add("carrier_profile", "Carrier legal name or remittance address is missing.", "Add them in Settings > Billing profile.")
    for m in docs["missing"] + docs["unverified"]:
        add("document", m["message"], "Upload the document, or confirm the signature on the load page.")
    for m in appr.get("missing", []):
        add("approval", m["message"], "Request approval and record it (Record approval).")
    for c in load.get("conflicts") or []:
        if not c.get("resolved"):
            add("conflict", f"Documents disagree on {c['field']}: rate con '{c.get('ratecon')}' vs agreement '{c.get('agreement')}'.",
                "Pick the value that applies (Resolve conflict).")
    for f in trans.get("review_flags", []):
        add("review_departure", f["message"], "Confirm or correct the departure time.")
    return out


# ---------------------------------------------------------------- invoices (existing per-stop records)

async def ensure_invoices(load, fleet, billing) -> list:
    db = _db()
    for s in _sorted_stops(load):
        if not s.get("departed_at"):
            continue
        b = billing["stops"][s["id"]]
        amt = b["amount"]
        label = f"{b['billed_minutes'] / 60:.2f} h"
        ex = await db.invoices.find_one({"load_id": load["id"], "stop_id": s["id"], "adjusts_invoice_id": None}, {"_id": 0})
        if ex:
            if ex["status"] == "ready":
                if amt <= 0:
                    await db.invoices.update_one({"id": ex["id"], "status": "ready"}, {"$set": {"status": "void", "amount": 0.0},
                                                 "$push": {"history": {"at": iso(now_utc()), "action": "voided", "note": "Recalculated to $0"}}})
                elif abs(ex["amount"] - amt) > 0.001:
                    await db.invoices.update_one({"id": ex["id"], "status": "ready"}, {"$set": {"amount": amt, "billable_label": label}})
            elif ex["status"] == "void" and amt > 0:
                await db.invoices.update_one({"id": ex["id"], "status": "void"}, {"$set": {"status": "ready", "amount": amt, "billable_label": label}})
            elif ex["status"] in ("sent", "paid", "disputed", "written_off") and abs(ex["amount"] - amt) > 0.001:
                adj = ex.get("pending_adjustment") or {}
                if abs((adj.get("new_amount") or -1) - amt) > 0.001:
                    await db.invoices.update_one({"id": ex["id"]}, {"$set": {"pending_adjustment": {
                        "new_amount": amt, "delta": round(amt - ex["amount"], 2), "detected_at": iso(now_utc())}}})
            continue
        if amt <= 0:
            continue
        seq = await db.fleets.find_one_and_update({"id": fleet["id"]}, {"$inc": {"invoice_seq": 1}}, return_document=ReturnDocument.AFTER)
        inv = {"id": ctx.uid(), "fleet_id": fleet["id"], "load_id": load["id"], "stop_id": s["id"], "adjusts_invoice_id": None,
               "stop_key": f"{load['id']}:{s['id']}",
               "number": f"DC-{(seq or {}).get('invoice_seq', 1001)}", "load_number": load.get("load_number"),
               "broker_id": load.get("broker_id"), "broker_name": (load.get("broker") or {}).get("name"),
               "broker_email": None, "facility_id": s.get("facility_id"), "facility_name": s.get("facility_name"),
               "stop_type": s.get("type"), "amount": amt, "billable_label": label, "status": "ready",
               "public_token": ctx.token(), "fingerprint": None, "sealed_evidence": None, "reminders": [],
               "reminders_paused": False, "created_at": iso(now_utc()), "sent_at": None, "paid_at": None,
               "history": [{"at": iso(now_utc()), "action": "drafted", "by": "automation"}]}
        try:
            await db.invoices.insert_one(dict(inv))
        except DuplicateKeyError:
            pass  # another worker created it first
    return await db.invoices.find({"load_id": load["id"]}, {"_id": 0}).sort("created_at", 1).to_list(100)


def invoice_balance(inv) -> dict:
    st = inv["status"]
    paid = float(inv.get("paid_amount") or 0) if st == "paid" else 0.0
    credit = float(inv.get("amount") or 0) if st == "written_off" else 0.0
    collectible = st in ("ready", "sent", "disputed")
    out = round(float(inv.get("amount") or 0) - paid, 2) if collectible else 0.0
    return {"paid": paid + credit, "outstanding": max(0.0, out)}


# ---------------------------------------------------------------- snapshot

async def _stop_pings(load, s, cutoff, received_before):
    a, d = parse(s.get("arrived_at")), parse(s.get("departed_at"))
    if not a:
        return []
    lo, hi = iso(a - timedelta(minutes=EVIDENCE_TAIL_MIN)), iso(min(d + timedelta(minutes=EVIDENCE_TAIL_MIN), cutoff) if d else cutoff)
    q = {"load_id": load["id"], "ts": {"$gte": lo, "$lte": hi}}
    if received_before:
        q["$or"] = [{"received_at": {"$exists": False}}, {"received_at": {"$lte": received_before}}]
    return await _db().pings.find(q, {"_id": 0, "lat": 1, "lng": 1, "ts": 1, "accuracy": 1}).sort("ts", 1).to_list(20000)


def _status_label(inv, packet_invoice_ids_prev):
    st = inv["status"]
    return {"ready": "New - submitted with this packet", "sent": "Previously submitted", "paid": "Paid", "disputed": "Disputed",
            "written_off": "Written off", "void": "Void"}.get(st, st)


async def build_snapshot(load, fleet, billing, invoices, trans, docs, appr, packet_id, version, received_before=None,
                         status="draft", supersedes_version=None) -> dict:
    tz = ctx.tz_of(fleet)
    det, t = load.get("detention") or {}, _terms(load)
    stops = _sorted_stops(load)
    cutoff = parse(trans["completed_at"]) + timedelta(minutes=EVIDENCE_TAIL_MIN)
    snap_stops, chron, exhibits, exceptions = [], [], [], []
    n_ex = 0
    for s in stops:
        b = billing["stops"][s["id"]]
        pings = await _stop_pings(load, s, cutoff, received_before)
        accs = [p.get("accuracy") or 0 for p in pings]
        appt = core.parse_local(s.get("appointment"), tz)
        snap_stops.append({
            "id": s["id"], "seq": s.get("seq", 0), "type": s.get("type") or "stop", "facility": s.get("facility_name"),
            "address": s.get("address"), "appointment": s.get("appointment"),
            "appointment_label": f"{ctx.fmt_local(fleet, iso(appt))}" if appt else None,
            "arrived_at": s.get("arrived_at"), "departed_at": s.get("departed_at"),
            "arrived_source": s.get("arrived_source"), "departed_source": s.get("departed_source"),
            "billing": {k: b.get(k) for k in ("billing_start_at", "billing_start_rule", "rate", "increment", "rounding", "billed_minutes",
                                              "billable_minutes", "dwell_minutes", "free_minutes", "raw_amount", "amount", "capped",
                                              "cap_adjustment", "eligible", "ineligible_reason", "calc")},
            "dwell_label": fmt_min(b["dwell_minutes"]), "free_label": fmt_min(b["free_minutes"]) if b["free_minutes"] is not None else "Unknown",
            "billable_label": fmt_min(b["billable_minutes"]), "billed_label": f"{b['billed_minutes'] / 60:.2f} h",
            "gps": {"count": len(pings), "hash": trail_hash(pings), "geofence": f"{int(s.get('radius_m') or 0)} m radius",
                    "accuracy": f"median ±{int(sorted(accs)[len(accs) // 2])} m" if accs else "No GPS points"},
            "documents": [{k: d.get(k) for k in ("file_id", "sha256", "doc_type", "uploaded_at", "signature_verified", "content_type")}
                          for d in _stop_docs(s)],
        })
        for e in s.get("events", []):
            detail = {"arrival": ctx.src_label(e.get("source")), "departure": ctx.src_label(e.get("source")),
                      "free_time_expired": "Calculated from terms", "notice_sent": f"Email notice to {e['to']}" if e.get("to") else "Email notice",
                      "bol_uploaded": "Photo uploaded by driver",
                      "document_uploaded": f"{DOC_LABELS.get(e.get('note'), e.get('note'))} uploaded by dispatcher"}.get(e["type"], e.get("note") or "")
            if e.get("note") and e["type"] != "document_uploaded":
                detail += f" - reason: {e['note']}"
            if e.get("coords") and e["coords"].get("accuracy"):
                detail += f" (±{int(e['coords']['accuracy'])} m)"
            if e["type"] == "departure" and e.get("source") == "geofence":
                detail += " - left the geofence; not proof of unloading"
            chron.append({"at": e.get("at"), "stop": f"{_stop_label(s)}", "event": e["type"].replace("_", " ").title(), "detail": detail})
        for d in _stop_docs(s):
            n_ex += 1
            ok = d.get("signature_verified")
            exhibits.append({"id": f"E{n_ex}", "file_id": d["file_id"], "sha256": d["sha256"],
                             "title": f"{DOC_LABELS.get(d['doc_type'], d['doc_type'])} - {_stop_label(s)} ({s.get('facility_name')})",
                             "note": "Signature confirmed visible by dispatcher." if ok else "Photo only - signature not verified."})
    for a in load.get("approvals") or []:
        chron.append({"at": a.get("at"), "stop": "Load", "event": "Approval recorded",
                      "detail": f"{METHOD_LABELS.get(a.get('method'), a.get('method'))} - {a.get('approver') or ''} {a.get('reference') or ''}"})
    chron.sort(key=lambda e: e.get("at") or "")
    obl = obligations(load, billing, trans, fleet)
    for o in obl:
        o["status_label"] = {"on_time": "Sent on time", "late": "Sent LATE", "missed": "MISSED", "not_needed": "Not needed",
                             "pending": "Pending", "missing": "Not recorded", "not_recorded": "Not recorded",
                             "recorded": "Recorded"}.get(o["status"], str(o["status"]).replace("_", " "))
    obl_pdf = [o for o in obl if o["kind"] != "invoice_submission"]
    clauses = []
    refs = load.get("term_refs") or {}
    if det.get("clause_text"):
        clauses.append({"label": "Detention clause", "text": det["clause_text"], "source": (refs.get("detention.clause_text") or {}).get("source") or "Rate confirmation"})
    for k, lbl in (("approval_rule_text", "Approval rule"), ("submission_other_text", "Submission instructions")):
        if t.get(k):
            clauses.append({"label": lbl, "text": t[k], "source": (refs.get(f"billing.{k}") or {}).get("source") or "Billing terms"})
    if det.get("notice_rule_text"):
        clauses.append({"label": "Notice rule", "text": det["notice_rule_text"], "source": "Rate confirmation (summary)"})
    for o in obl_pdf:
        if o["status"] in ("missed", "late"):
            exceptions.append(f"{o['label']} for {o.get('stop') or 'load'}: {o['status_label']}.")
        if o.get("note"):
            exceptions.append(f"{o['label']} for {o.get('stop') or 'load'}: {o['note']}.")
    for m in docs["missing"] + docs["unverified"]:
        exceptions.append(m["message"])
    if not docs.get("requirements_known"):
        exceptions.append("Required supporting documents are not stated in the recorded terms.")
    for m in appr.get("missing", []):
        exceptions.append(m["message"])
    if appr["state"] == "unknown":
        exceptions.append("Whether detention needed prior approval is not stated; no approval is recorded.")
    for f in trans.get("review_flags", []):
        exceptions.append(f["message"])
    for c in load.get("conflicts") or []:
        exceptions.append(f"Conflict on {c['field']}: " + (f"resolved by dispatcher as '{c.get('value')}'" if c.get("resolved") else "UNRESOLVED"))
    for k in billing["missing_terms"]:
        exceptions.append(f"Unknown term: {k.replace('_', ' ')}.")
    if trans.get("manual"):
        mc = trans["manual"]
        exceptions.append(f"Completion recorded manually by {mc.get('by_name') or mc.get('by')} at {ctx.fmt_local(fleet, mc.get('at'))}: {mc.get('reason')}")
    inv_rows, tot_i, tot_p, tot_o = [], 0.0, 0.0, 0.0
    for inv in invoices:
        if inv["status"] == "void":
            continue
        s = next((x for x in stops if x["id"] == inv["stop_id"]), {})
        bal = invoice_balance(inv)
        inv_rows.append({"id": inv["id"], "number": inv["number"], "stop_id": inv["stop_id"], "stop_label": _stop_label(s) if s else "-",
                         "facility": inv.get("facility_name"), "status": inv["status"], "status_label": _status_label(inv, None),
                         "amount": inv["amount"], "paid": bal["paid"], "outstanding": bal["outstanding"],
                         "evidence_url": ctx.evidence_url(fleet, inv), "adjusts": inv.get("adjusts_invoice_id")})
        tot_i += inv["amount"]
        tot_p += bal["paid"]
        tot_o += bal["outstanding"]
    days, start = t.get("payment_terms_days"), t.get("payment_terms_start")
    terms_label = f"Net {int(days)}" if days else "Payment terms not stated in the recorded agreement"
    basis = {"invoice_submission": "from the date this packet is submitted (submission time is recorded; receipt is not confirmed)",
             "receipt_of_complete_docs": "from the payor's receipt of complete documents (receipt date not confirmed - no exact due date is stated)",
             "delivery": "from delivery"}.get(start, "basis not stated")
    car = {k: fleet.get(k) for k in ("legal_name", "address", "phone", "billing_email", "mc_number", "usdot_number", "remittance_address")}
    car["legal_name"] = car["legal_name"] or None
    d = destination(load)
    snap = {
        "packet_id": packet_id, "version": version, "status": status, "supersedes_version": supersedes_version,
        "issued_at": None, "currency": "USD", "evidence_cutoff": iso(cutoff),
        "carrier": car,
        "payor": {"company": d["company"] or (load.get("broker") or {}).get("name"), "address": t.get("billing_address"),
                  "recipient": {"email": f"Invoices to: {d['recipient']}", "portal": f"Portal: {d.get('portal_url') or 'not set'}",
                                "other": d.get("other_text") or "Other method"}.get(d["channel"] or "", "Submission method not set")},
        "load": {"number": load.get("load_number"), "refs": load.get("refs") or {}, "shipment_date": (load.get("refs") or {}).get("shipment_date"),
                 "origin": f"{stops[0].get('facility_name')}, {stops[0].get('address')}" if stops else None,
                 "destination": f"{stops[-1].get('facility_name')}, {stops[-1].get('address')}" if stops else None,
                 "completed_at": trans["completed_at"], "completion_source": trans.get("source"), "timezone": fleet.get("timezone")},
        "terms": {**{k: det.get(k) for k in core.TERM_KEYS}, "payment_terms_days": days, "payment_terms_start": start},
        "stops": snap_stops, "invoices": inv_rows,
        "totals": {"invoiced": round(tot_i, 2), "paid": round(tot_p, 2), "outstanding": round(tot_o, 2),
                   "detention_calculated": billing["total"]},
        "payment": {"terms_label": terms_label, "due_basis": basis},
        "chronology": chron, "obligations": obl_pdf, "clauses": clauses, "exhibits": exhibits, "exceptions": exceptions,
        "verification_url": ctx.evidence_url(fleet, next((i for i in invoices if i["status"] != "void"), None)) if invoices else None,
    }
    return snap


def snapshot_hash(snap) -> str:
    """Hash of the material record (excludes presentation-only fields)."""
    return canonical_hash({k: v for k, v in snap.items() if k not in ("status", "issued_at", "snapshot_hash", "verification_url")})


def material_view(snap) -> dict:
    """Money, times, documents and notices - what a revision is about (GPS-only changes are supplements)."""
    return {"stops": [{k: s.get(k) for k in ("id", "arrived_at", "departed_at", "billing", "documents")} for s in snap["stops"]],
            "invoices": [{k: i[k] for k in ("number", "amount")} for i in snap["invoices"]],  # payment/submission status is tracked separately
            "obligations": [{k: o.get(k) for k in ("kind", "stop_id", "status", "at")} for o in snap["obligations"]],
            "terms": snap["terms"], "exceptions": snap["exceptions"]}


async def render_pdf(snap, fleet) -> bytes:
    images = {}
    for x in snap["exhibits"][:12]:
        rec = await _db().files.find_one({"id": x["file_id"]}, {"_id": 0})
        if rec and (rec.get("content_type") or "").startswith("image/"):
            try:
                images[x["file_id"]], _ = await asyncio.to_thread(ctx.get_object, rec["storage_path"])
            except Exception as e:  # noqa
                logger.warning(f"exhibit fetch failed {e}")
    return await asyncio.to_thread(build_billing_packet, snap, images, lambda s: ctx.fmt_local(fleet, s) if s else "-")


async def _save_pdf(fleet, load, packet_id, version, pdf) -> dict:
    return await ctx.store_file(fleet["id"], pdf, "application/pdf", "pdf", "billing_packet",
                                {"load_id": load["id"], "packet_id": packet_id, "version": version, "retention": RETENTION_POLICY})


# ---------------------------------------------------------------- packets (draft -> issued, immutable once issued)

async def upsert_draft(load, fleet, billing, invoices, trans, docs, appr, actor):
    db = _db()
    latest = await db.packets.find_one({"load_id": load["id"]}, {"_id": 0}, sort=[("version", -1)])
    issued = await db.packets.find_one({"load_id": load["id"], "status": "issued"}, {"_id": 0}, sort=[("version", -1)])
    if latest and latest["status"] == "draft":
        pid, ver = latest["id"], latest["version"]
    else:
        pid, ver = ctx.uid(), (latest["version"] + 1 if latest else 1)
    snap = await build_snapshot(load, fleet, billing, invoices, trans, docs, appr, pid, ver,
                                supersedes_version=issued["version"] if issued else None)
    h = snapshot_hash(snap)
    if issued and canonical_hash(material_view(snap)) == canonical_hash(material_view(issued["snapshot"])):
        # Only late GPS (or presentation) differs: keep the issued packet untouched, log an auditable supplement.
        if latest and latest["status"] == "draft":
            await db.packets.delete_one({"id": latest["id"], "status": "draft"})
        late = sum(s["gps"]["count"] for s in snap["stops"]) - sum(s["gps"]["count"] for s in issued["snapshot"]["stops"])
        if late > 0 and not any(x.get("hash") == h for x in issued.get("supplements", [])):
            await db.packets.update_one({"id": issued["id"]}, {"$push": {"supplements": {
                "at": iso(now_utc()), "kind": "late_gps", "count": late, "hash": h,
                "note": f"{late} GPS point(s) arrived after issue; the issued packet is unchanged."}}})
        return issued
    if latest and latest["status"] == "draft" and latest.get("snapshot_hash") == h:
        return latest
    snap["snapshot_hash"] = h
    pdf = await render_pdf(snap, fleet)
    rec = await _save_pdf(fleet, load, pid, ver, pdf)
    doc = {"id": pid, "fleet_id": fleet["id"], "load_id": load["id"], "version": ver, "status": "draft", "snapshot": snap,
           "snapshot_hash": h, "pdf_file_id": rec["id"], "pdf_sha256": rec["sha256"], "invoice_ids": [i["id"] for i in snap["invoices"]],
           "supersedes": issued["id"] if issued else None, "created_at": iso(now_utc()), "created_by": actor or "automation",
           "retention": RETENTION_POLICY, "supplements": []}
    if latest and latest["status"] == "draft":
        await db.packets.update_one({"id": pid, "status": "draft"}, {"$set": {k: v for k, v in doc.items() if k != "id"},
                                                                    "$push": {"draft_history": {"at": iso(now_utc()), "old_hash": latest.get("snapshot_hash")}}})
    else:
        try:
            await db.packets.insert_one(dict(doc))
        except DuplicateKeyError:
            return await db.packets.find_one({"load_id": load["id"], "version": ver}, {"_id": 0})
    return doc


async def issue_packet(packet_id, fleet, actor) -> dict:
    """Freeze the current draft: re-render with the issue date, seal each new invoice from the snapshot."""
    db = _db()
    p = await db.packets.find_one({"id": packet_id}, {"_id": 0})
    if not p or p["status"] != "draft":
        return p
    snap = dict(p["snapshot"])
    now = iso(now_utc())
    snap.update({"status": "issued", "issued_at": now})
    pdf = await render_pdf(snap, fleet)
    load = await db.loads.find_one({"id": p["load_id"]}, {"_id": 0})
    rec = await _save_pdf(fleet, load, p["id"], p["version"], pdf)
    res = await db.packets.update_one({"id": packet_id, "status": "draft"}, {"$set": {
        "status": "issued", "issued_at": now, "issued_by": actor or "automation", "snapshot": snap,
        "pdf_file_id": rec["id"], "pdf_sha256": rec["sha256"], "issued_snapshot_hash": snapshot_hash(snap)}})
    if not res.modified_count:
        return await db.packets.find_one({"id": packet_id}, {"_id": 0})
    if p.get("supersedes"):
        await db.packets.update_one({"id": p["supersedes"]}, {"$set": {"status": "superseded", "superseded_by": packet_id}})
    for row in snap["invoices"]:
        st = next((s for s in snap["stops"] if s["id"] == row["stop_id"]), None)
        if not st:
            continue
        ev = {"packet_id": packet_id, "version": p["version"], "invoice_number": row["number"], "load_number": snap["load"]["number"],
              "stop": st, "obligations": [o for o in snap["obligations"] if o.get("stop_id") == row["stop_id"]],
              "terms": snap["terms"], "evidence_cutoff": snap["evidence_cutoff"]}
        await db.invoices.update_one({"id": row["id"], "status": "ready"}, {"$set": {
            "sealed_evidence": ev, "fingerprint": canonical_hash(ev), "sealed_at": now, "snapshot_packet_id": packet_id,
            "amount": row["amount"]}})
    return await db.packets.find_one({"id": packet_id}, {"_id": 0})


def verify_packet(p) -> dict:
    """Integrity of the ISSUED snapshot (independent of later source changes)."""
    if not p or p.get("status") == "draft":
        return {"state": "draft"}
    ok = snapshot_hash(p["snapshot"]) == p.get("issued_snapshot_hash")
    return {"state": "verified" if ok else "tampered", "fingerprint": p.get("issued_snapshot_hash"), "issued_at": p.get("issued_at")}


async def source_comparison(p, load, fleet) -> dict:
    """Has the live source record changed since issue? (Separate from integrity of the issued packet.)"""
    if not p or p.get("status") == "draft":
        return {"state": "n/a"}
    billing = compute_load_billing(load, tz=ctx.tz_of(fleet))
    trans = transport_state(load)
    if trans["state"] != "completed":
        return {"state": "amended", "changed": ["transport"]}
    invs = await _db().invoices.find({"load_id": load["id"]}, {"_id": 0}).to_list(100)
    cur = await build_snapshot(load, fleet, billing, invs, trans, documents_state(load), approvals_state(load, billing),
                               p["id"], p["version"], received_before=p.get("issued_at"))
    a, b = material_view(p["snapshot"]), material_view(cur)
    changed = sorted(k for k in a if canonical_hash(a[k]) != canonical_hash(b[k]))
    return {"state": "unchanged" if not changed else "amended", "changed": changed,
            "supplements": p.get("supplements", [])}


# ---------------------------------------------------------------- outbox (durable, idempotent submission)

async def enqueue(kind, load, fleet, packet=None, to=None, subject=None, html=None, extra=None) -> dict:
    key = f"{kind}:{packet['id'] if packet else load['id']}"
    job = {"id": ctx.uid(), "idempotency_key": key, "kind": kind, "fleet_id": fleet["id"], "load_id": load["id"],
           "packet_id": packet["id"] if packet else None, "to": to, "subject": subject, "html": html,
           "copy_to": fleet.get("billing_email"), "reply_to": fleet.get("billing_email") or fleet.get("reply_to_email"),
           "status": "pending", "attempts": 0, "next_attempt_at": iso(now_utc()), "created_at": iso(now_utc()),
           "simulated": SUBMISSION_MODE != "live", "history": [{"at": iso(now_utc()), "event": "queued"}], **(extra or {})}
    try:
        await _db().outbox.insert_one(dict(job))
    except DuplicateKeyError:
        job = await _db().outbox.find_one({"idempotency_key": key}, {"_id": 0})
    return job


async def _transport(job):
    """Returns provider id. Raises EmailError (definite failure) or EmailTimeout (uncertain)."""
    if job.get("simulated"):
        if ctx.fault_hook:
            await ctx.fault_hook(job)
        return f"SIMULATED-{job['id'][:8]}"
    pid = await ctx.send_email(to=job["to"], subject=job["subject"], html=job["html"], reply_to=job.get("reply_to"))
    if job.get("copy_to"):
        try:
            await ctx.send_email(to=job["copy_to"], subject=f"[Copy] {job['subject']}", html=job["html"])
        except ctx.EmailError:
            pass
    return pid


async def run_outbox(limit=50):
    db = _db()
    now = now_utc()
    # Recovery: a claim that expired mid-send may or may not have reached the provider -> never resend blindly.
    async for j in db.outbox.find({"status": "sending", "claimed_until": {"$lt": iso(now)}}, {"_id": 0}):
        await db.outbox.update_one({"id": j["id"], "status": "sending"}, {"$set": {"status": "uncertain"},
                                   "$push": {"history": {"at": iso(now), "event": "uncertain", "note": "Worker stopped mid-send; needs reconciliation"}}})
        await _sync_submission(j["load_id"])
    for _ in range(limit):
        j = await db.outbox.find_one_and_update(
            {"status": "pending", "next_attempt_at": {"$lte": iso(now_utc())}},
            {"$set": {"status": "sending", "claimed_until": iso(now_utc() + timedelta(seconds=SEND_CLAIM_SECONDS)),
                      "attempt_started_at": iso(now_utc())}, "$inc": {"attempts": 1}},
            sort=[("next_attempt_at", 1)], return_document=ReturnDocument.AFTER, projection={"_id": 0})
        if not j:
            break
        await _deliver(j)


async def _deliver(j):
    db = _db()
    try:
        ref = await _transport(j)
    except ctx.EmailTimeout as e:
        await db.outbox.update_one({"id": j["id"], "status": "sending"}, {"$set": {"status": "uncertain", "error": str(e)},
                                   "$push": {"history": {"at": iso(now_utc()), "event": "uncertain", "note": str(e)}}})
    except (ctx.EmailError, ValueError) as e:
        retry = j["attempts"] < MAX_ATTEMPTS
        await db.outbox.update_one({"id": j["id"], "status": "sending"}, {"$set": {
            "status": "pending" if retry else "failed", "error": str(e)[:300],
            "next_attempt_at": iso(now_utc() + timedelta(minutes=5 * j["attempts"]))},
            "$push": {"history": {"at": iso(now_utc()), "event": "retry_scheduled" if retry else "failed", "note": str(e)[:300]}}})
    else:
        await _accepted(j, ref, "provider" if not j.get("simulated") else "simulated")
    await _sync_submission(j["load_id"])


async def _accepted(j, ref, how, actor=None):
    db = _db()
    now = iso(now_utc())
    r = await db.outbox.update_one({"id": j["id"], "status": {"$in": ["sending", "uncertain", "pending", "failed"]}},
                                   {"$set": {"status": "accepted", "provider_ref": ref, "accepted_at": now, "accepted_how": how},
                                    "$push": {"history": {"at": now, "event": "accepted", "ref": ref, "by": actor or how}}})
    if not r.modified_count or j["kind"] != "billing_submission":
        return
    p = await db.packets.find_one({"id": j["packet_id"]}, {"_id": 0})
    for row in (p or {}).get("snapshot", {}).get("invoices", []):
        await db.invoices.update_one({"id": row["id"], "status": "ready"}, {"$set": {
            "status": "sent", "sent_at": now, "last_emailed_at": now, "broker_email": j.get("to"), "submission_ref": ref,
            "payment_terms": {k: (p.get("snapshot", {}).get("terms") or {}).get(k) for k in ("payment_terms_days", "payment_terms_start")},
            "submission_simulated": bool(j.get("simulated")), "packet_id": j["packet_id"]},
            "$push": {"history": {"at": now, "action": "submitted", "to": j.get("to"), "ref": ref,
                                  "note": "SIMULATED - no email sent" if j.get("simulated") else "Accepted by email provider (delivery not confirmed)"}}})


async def mark_portal_submitted(load, packet, reference, actor):
    """Dispatcher records the portal upload; invoices become submitted only then."""
    job = await enqueue("billing_submission", load, {"id": load["fleet_id"]}, packet, to=None, extra={"channel": "portal"})
    await _db().outbox.update_one({"id": job["id"]}, {"$set": {"status": "sending"}})
    await _accepted({**job, "status": "sending"}, reference or "portal", "dispatcher_portal", actor)
    await _sync_submission(load["id"])


async def _sync_submission(load_id):
    db = _db()
    jobs = await db.outbox.find({"load_id": load_id, "kind": "billing_submission"}, {"_id": 0}).sort("created_at", -1).to_list(10)
    if not jobs:
        return
    j = jobs[0]
    state = {"pending": "queued", "sending": "sending", "accepted": "accepted", "failed": "failed", "uncertain": "uncertain"}[j["status"]]
    sub = {"state": state, "job_id": j["id"], "to": j.get("to"), "channel": j.get("channel", "email"), "simulated": j.get("simulated"),
           "provider_ref": j.get("provider_ref"), "accepted_at": j.get("accepted_at"), "error": j.get("error"),
           "attempts": j.get("attempts"), "packet_id": j.get("packet_id")}
    await db.loads.update_one({"id": load_id}, {"$set": {"completion.submission": sub}})


# ---------------------------------------------------------------- the shared service

async def finalize_load(load_id: str, trigger: str, actor: str | None = None):
    db = _db()
    await db.loads.update_one({"id": load_id}, {"$set": {"finalize_dirty": True}})
    result = None
    for _ in range(4):
        now = now_utc()
        got = await db.loads.find_one_and_update(
            {"id": load_id, "$or": [{"finalize_lock_until": None}, {"finalize_lock_until": {"$exists": False}},
                                     {"finalize_lock_until": {"$lt": iso(now)}}]},
            {"$set": {"finalize_lock_until": iso(now + timedelta(seconds=LOCK_SECONDS)), "finalize_dirty": False}},
            return_document=ReturnDocument.AFTER, projection={"_id": 0})
        if not got:
            return None  # another worker holds it and will see the dirty flag
        try:
            result = await _finalize(got, trigger, actor)
        except Exception as e:  # noqa
            logger.exception(f"finalize {load_id} failed: {e}")
        finally:
            await db.loads.update_one({"id": load_id}, {"$set": {"finalize_lock_until": None}})
        again = await db.loads.find_one({"id": load_id}, {"_id": 0, "finalize_dirty": 1})
        if not (again or {}).get("finalize_dirty"):
            break
    return result


async def _finalize(load, trigger, actor):
    db = _db()
    fleet = await db.fleets.find_one({"id": load["fleet_id"]}, {"_id": 0})
    billing = compute_load_billing(load, tz=ctx.tz_of(fleet))
    invoices = await ensure_invoices(load, fleet, billing)
    trans = transport_state(load)
    docs, appr = documents_state(load), approvals_state(load, billing)
    blk = blockers(load, fleet, billing, trans, docs, appr)
    prev = load.get("completion") or {}
    comp = {"transport": trans, "documents": docs, "approvals": {k: v for k, v in appr.items() if k != "records"},
            "blockers": blk, "billing_total": billing["total"], "missing_terms": billing["missing_terms"],
            "submission": prev.get("submission") or {"state": "not_started"}, "packet": prev.get("packet") or {"state": "none"},
            "updated_at": iso(now_utc()), "last_trigger": trigger, "billing_mode": (load.get("billing_setup") or {}).get("mode", "review")}
    live_invoices = [i for i in invoices if i["status"] != "void"]
    bal = [invoice_balance(i) for i in live_invoices]
    paid_all = live_invoices and all(i["status"] in ("paid", "written_off") for i in live_invoices)
    comp["payment"] = {"state": "n/a" if not live_invoices else "paid" if paid_all else
                       "partial" if any(i["status"] == "paid" for i in live_invoices) else "unpaid",
                       "outstanding": round(sum(b["outstanding"] for b in bal), 2), "paid": round(sum(b["paid"] for b in bal), 2)}
    if trans["state"] == "completed":
        if not live_invoices and billing["total"] <= 0 and not billing["missing_terms"]:
            comp["packet"] = {"state": "none"}
            comp["submission"] = {"state": "not_needed"}
            comp["summary"] = {"text": f"Load {load.get('load_number')} completed {ctx.fmt_local(fleet, trans['completed_at'])}. "
                                       f"{len(load['stops'])} stops, no billable detention.", "saved_at": prev.get("summary", {}).get("saved_at") or iso(now_utc())}
            if fleet.get("completion_reports") and fleet.get("billing_email"):
                subj, html = templates.completion_report_email(fleet.get("name"), load, comp["summary"]["text"])
                job = await enqueue("completion_report", load, fleet, None, fleet["billing_email"], subj, html)
                comp["summary"]["report_job"] = job["id"]
        else:
            p = await upsert_draft(load, fleet, billing, invoices, trans, docs, appr, actor)
            comp["packet"] = {"state": p["status"], "packet_id": p["id"], "version": p["version"], "pdf_file_id": p.get("pdf_file_id")}
            sub_state = comp["submission"].get("state")
            if p["status"] == "draft":
                d = destination(load)
                if blk:
                    comp["submission"] = {**comp["submission"], "state": "blocked"} if sub_state in (None, "not_started", "blocked", "awaiting_review") else comp["submission"]
                elif p.get("supersedes"):
                    comp["submission"] = {**comp["submission"], "state": "revision_review"}
                elif comp["billing_mode"] == "auto":
                    await db.loads.update_one({"id": load["id"]}, {"$set": {"completion": comp}})
                    await submit_packet(load, fleet, p, actor or "automation", d)
                    return await db.loads.find_one({"id": load["id"]}, {"_id": 0, "completion": 1})
                elif sub_state in (None, "not_started", "blocked"):
                    comp["submission"] = {"state": "awaiting_review"}
    await db.loads.update_one({"id": load["id"]}, {"$set": {"completion": comp}})
    return comp


async def submit_packet(load, fleet, packet, actor, d=None):
    """Issue the packet and submit by the confirmed channel. Never re-submits an already accepted packet."""
    db = _db()
    d = d or destination(load)
    p = await issue_packet(packet["id"], fleet, actor) if packet["status"] == "draft" else packet
    await db.loads.update_one({"id": load["id"]}, {"$set": {"completion.packet": {
        "state": "issued", "packet_id": p["id"], "version": p["version"], "pdf_file_id": p["pdf_file_id"]}}})
    if d["channel"] == "portal":
        await db.loads.update_one({"id": load["id"]}, {"$set": {"completion.submission": {
            "state": "awaiting_portal", "packet_id": p["id"], "portal_url": d.get("portal_url"),
            "note": "Upload the downloaded packet to the payor's portal, then record the submission."}}})
        return
    if d["channel"] != "email":
        await db.loads.update_one({"id": load["id"]}, {"$set": {"completion.submission": {
            "state": "awaiting_manual", "packet_id": p["id"], "note": d.get("other_text") or "Submit by the agreed method, then record it."}}})
        return
    pdf_url = f"{fleet.get('app_url') or ''}/api/public/packets/{p['public_token']}/pdf" if p.get("public_token") else None
    if not pdf_url:
        tok = ctx.token()
        await db.packets.update_one({"id": p["id"]}, {"$set": {"public_token": tok}})
        pdf_url = f"{fleet.get('app_url') or ''}/api/public/packets/{tok}/pdf"
    snap = p["snapshot"]
    subj, html = templates.billing_submission_email(fleet, snap, pdf_url, simulated=SUBMISSION_MODE != "live")
    job = await enqueue("billing_submission", load, fleet, p, d["recipient"], subj, html, {"channel": "email", "pdf_url": pdf_url})
    await _sync_submission(load["id"])
    if job["status"] == "pending":
        await run_outbox(limit=5)

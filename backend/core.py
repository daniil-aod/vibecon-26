"""Detention math, notice timing, geofence helpers and evidence fingerprint."""
import hashlib
import json
import math
from datetime import datetime, timezone, timedelta

DEFAULT_INCREMENT = 15
DEFAULT_NOTICE_MARGIN = 30
REMINDER_DAYS = [3, 7, 14, 30]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def parse(s) -> datetime | None:
    if not s:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def free_minutes(det: dict) -> float:
    return float(det.get("free_time_hours") or 0) * 60.0


def stop_billing(stop: dict, det: dict, now: datetime | None = None, other_billed: float = 0.0) -> dict:
    """Compute dwell / billable / amount for a stop under the rate con terms."""
    now = now or now_utc()
    arrived = parse(stop.get("arrived_at"))
    departed = parse(stop.get("departed_at"))
    rate = float(det.get("hourly_rate") or 0)
    inc = float(det.get("billing_increment_minutes") or DEFAULT_INCREMENT) or DEFAULT_INCREMENT
    free = free_minutes(det)
    out = {"dwell_minutes": 0.0, "billable_minutes": 0.0, "billed_minutes": 0.0, "amount": 0.0,
           "capped": False, "free_expires_at": None, "free_left_minutes": free, "live": False}
    if not arrived:
        return out
    end = departed or now
    dwell = max(0.0, (end - arrived).total_seconds() / 60.0)
    billable = max(0.0, dwell - free)
    billed = math.floor(billable / inc) * inc if billable > 0 else 0.0
    amount = round(billed / 60.0 * rate, 2)
    cap = det.get("cap_amount")
    capped = False
    if cap:
        cap = float(cap)
        scope = det.get("cap_scope") or "per_stop"
        if scope == "per_day":
            cap = cap * max(1, math.ceil(dwell / 1440.0))
        elif scope == "per_load":
            cap = max(0.0, cap - other_billed)
        if amount > cap:
            amount, capped = round(cap, 2), True
    out.update({
        "dwell_minutes": round(dwell, 2), "billable_minutes": round(billable, 2), "billed_minutes": billed,
        "amount": amount, "capped": capped, "free_expires_at": iso(arrived + timedelta(minutes=free)),
        "free_left_minutes": round(max(0.0, free - dwell), 2), "live": departed is None,
        "rate": rate, "increment": inc, "free_minutes": free,
    })
    return out


def notice_due_at(arrived: datetime, det: dict) -> datetime:
    """When the broker notice must go out, based on the rate con rule."""
    free = free_minutes(det)
    expiry = arrived + timedelta(minutes=free)
    after = det.get("notice_after_arrival_minutes")
    before = det.get("notice_before_expiry_minutes")
    cands = []
    if after is not None and after > 0:
        cands.append(arrived + timedelta(minutes=float(after) * 0.75))
    if before is not None:
        margin = float(before) if before and before > 0 else DEFAULT_NOTICE_MARGIN
        cands.append(expiry - timedelta(minutes=margin))
    if not cands:
        cands.append(expiry - timedelta(minutes=DEFAULT_NOTICE_MARGIN))
    return max(arrived, min(cands))


def canonical_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def trail_hash(pings: list) -> str:
    return canonical_hash([[round(p["lat"], 6), round(p["lng"], 6), p["ts"]] for p in pings])


def evidence_record(invoice: dict, load: dict, stop: dict, billing: dict, notices: list, pings: list) -> dict:
    det = load.get("detention") or {}
    return {
        "invoice_number": invoice.get("number"),
        "load_number": load.get("load_number"),
        "broker": (load.get("broker") or {}).get("name"),
        "facility": stop.get("facility_name"), "address": stop.get("address"),
        "geofence": [stop.get("lat"), stop.get("lng"), stop.get("radius_m")],
        "arrived_at": stop.get("arrived_at"), "arrived_source": stop.get("arrived_source"),
        "departed_at": stop.get("departed_at"), "departed_source": stop.get("departed_source"),
        "free_time_hours": det.get("free_time_hours"), "hourly_rate": det.get("hourly_rate"),
        "cap_amount": det.get("cap_amount"), "increment": billing.get("increment"),
        "billed_minutes": billing.get("billed_minutes"), "amount": billing.get("amount"),
        "clause_text": det.get("clause_text"),
        "notices": sorted([n.get("sent_at") for n in notices if n.get("sent_at")]),
        "bol": sorted([b.get("sha256") for b in stop.get("bol", [])]),
        "trail": trail_hash(pings),
    }


def grade_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ============================================================== authoritative detention calculation
# One deterministic calculation used by the dashboard, invoices, PDFs, emails, evidence and Stripe.
# Unknown terms stay unknown (they are reported in missing_terms, never filled with guesses).

from decimal import Decimal, ROUND_HALF_UP  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

TERM_KEYS = ("free_time_hours", "hourly_rate", "billing_increment_minutes", "rounding_rule", "cap_amount",
             "cap_scope", "per_day_definition", "billing_start_rule", "late_arrival_voids", "late_grace_minutes")
ROUNDING_RULES = ("completed_increment", "round_up", "nearest", "exact")


def money(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def stop_terms(det: dict, stop: dict) -> dict:
    """Load-level terms with any stop-specific overrides (only non-null override values apply)."""
    t = {k: (det or {}).get(k) for k in TERM_KEYS}
    for k, v in ((stop or {}).get("terms_override") or {}).items():
        if v is not None and k in TERM_KEYS + ("eligible",):
            t[k] = v
    return t


def parse_local(s, tz: ZoneInfo | None) -> datetime | None:
    """Appointment strings like 2026-03-11T08:00 are local wall-clock times in the fleet timezone."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=tz or timezone.utc)
    return d.astimezone(timezone.utc)


def _round_minutes(billable: float, inc: float, rule: str) -> float:
    if billable <= 0:
        return 0.0
    if rule == "exact" or inc <= 0:
        return round(billable, 2)
    units = billable / inc
    if rule == "round_up":
        units = math.ceil(units - 1e-9)
    elif rule == "nearest":
        units = math.floor(units + 0.5)
    else:  # completed_increment (default): only completed increments count
        units = math.floor(units + 1e-9)
    return float(units * inc)


def calc_stop(stop: dict, terms: dict, now: datetime | None = None, tz: ZoneInfo | None = None) -> dict:
    """Uncapped detention for one stop. Caps are applied by compute_load_billing."""
    now = now or now_utc()
    arrived, departed = parse(stop.get("arrived_at")), parse(stop.get("departed_at"))
    missing = [k for k in ("free_time_hours", "hourly_rate") if terms.get(k) is None]
    inc = terms.get("billing_increment_minutes")
    rule = terms.get("rounding_rule") or ("completed_increment" if inc else "exact")
    rate = float(terms.get("hourly_rate") or 0)
    free = float(terms.get("free_time_hours") or 0) * 60.0 if terms.get("free_time_hours") is not None else None
    out = {"dwell_minutes": 0.0, "billable_minutes": 0.0, "billed_minutes": 0.0, "raw_amount": 0.0, "amount": 0.0,
           "capped": False, "cap_adjustment": 0.0, "free_expires_at": None, "free_left_minutes": free,
           "live": False, "rate": rate if terms.get("hourly_rate") is not None else None,
           "increment": float(inc) if inc else None, "rounding": rule,
           "free_minutes": free, "billing_start_at": None, "billing_start_rule": terms.get("billing_start_rule") or "arrival",
           "eligible": True, "ineligible_reason": None, "missing_terms": missing, "calc": []}
    if not arrived:
        return out
    end = departed or now
    start, rule_start = arrived, terms.get("billing_start_rule") or "arrival"
    appt = parse_local(stop.get("appointment"), tz)
    if rule_start == "appointment_or_arrival_later":
        if appt:
            start = max(arrived, appt)
        else:
            out["missing_terms"] = missing = missing + ["appointment"]
    if terms.get("late_arrival_voids") and appt:
        grace = float(terms.get("late_grace_minutes") or 0)
        if arrived > appt + timedelta(minutes=grace):
            out.update({"eligible": False, "ineligible_reason": "Arrived after the appointment; the contract voids detention for late arrival"})
    if terms.get("eligible") is False:
        out.update({"eligible": False, "ineligible_reason": "Marked not eligible for detention on this stop"})
    dwell = max(0.0, (end - arrived).total_seconds() / 60.0)
    counted = max(0.0, (end - start).total_seconds() / 60.0)
    out.update({"dwell_minutes": round(dwell, 2), "billing_start_at": iso(start), "live": departed is None})
    if free is not None:
        out["free_expires_at"] = iso(start + timedelta(minutes=free))
        out["free_left_minutes"] = round(max(0.0, free - counted), 2)
    if free is None or terms.get("hourly_rate") is None or not out["eligible"]:
        return out
    billable = max(0.0, counted - free)
    billed = _round_minutes(billable, float(inc or 0), rule)
    raw = money(Decimal(str(billed)) / Decimal(60) * Decimal(str(rate)))
    out.update({"billable_minutes": round(billable, 2), "billed_minutes": billed, "raw_amount": float(raw), "amount": float(raw)})
    out["calc"] = [f"Time counted {fmt_min(counted)} - free time {fmt_min(free)} = billable {fmt_min(billable)}",
                   f"Rounded ({rule.replace('_', ' ')}{', ' + str(int(inc)) + '-min increments' if inc else ''}) = {billed / 60:.2f} h",
                   f"{billed / 60:.2f} h x ${rate:,.2f}/h = ${raw:,.2f}"]
    return out


def fmt_min(m: float) -> str:
    m = int(round(m or 0))
    return f"{m // 60}h {m % 60:02d}m"


def compute_load_billing(load: dict, now: datetime | None = None, tz: ZoneInfo | None = None) -> dict:
    """THE authoritative per-stop + load total. Stops in sequence; caps per stop / per load / per day."""
    now = now or now_utc()
    det = load.get("detention") or {}
    stops = sorted(load.get("stops", []), key=lambda x: x.get("seq", 0))
    res, issues = {}, []
    load_used = Decimal(0)
    day_used: dict = {}
    for s in stops:
        t = stop_terms(det, s)
        b = calc_stop(s, t, now, tz)
        cap = t.get("cap_amount")
        amt = money(b["raw_amount"])
        if cap not in (None, "") and float(cap) > 0 and amt > 0:
            cap = money(cap)
            scope = t.get("cap_scope") or "per_stop"
            if scope == "per_load":
                allowed = max(Decimal(0), cap - load_used)
                note = f"Per-load cap ${cap:,.2f}; ${load_used:,.2f} already counted on earlier stops"
            elif scope == "per_day":
                d = t.get("per_day_definition")
                if d == "24h_block":
                    allowed = cap * max(1, math.ceil(b["dwell_minutes"] / 1440.0))
                    note = f"Cap ${cap:,.2f} per 24-hour period on site"
                elif d == "calendar_day":
                    key = (parse(b["billing_start_at"]).astimezone(tz or timezone.utc)).date().isoformat()
                    allowed = max(Decimal(0), cap - day_used.get(key, Decimal(0)))
                    note = f"Cap ${cap:,.2f} per calendar day ({key})"
                    day_used[key] = day_used.get(key, Decimal(0)) + min(amt, allowed)
                else:
                    allowed = cap
                    note = f"Cap ${cap:,.2f} 'per day' - meaning not confirmed; applied once to this stop until confirmed"
                    if "per_day_definition" not in issues:
                        issues.append("per_day_definition")
            else:
                allowed = cap
                note = f"Per-stop cap ${cap:,.2f}"
            if amt > allowed:
                b["cap_adjustment"] = float(money(allowed - amt))
                amt, b["capped"] = money(allowed), True
                b["calc"].append(f"{note}: adjusted by -${abs(b['cap_adjustment']):,.2f}")
        b["amount"] = float(amt)
        load_used += amt
        res[s["id"]] = b
    missing = sorted({m for b in res.values() for m in b["missing_terms"]} | set(issues))
    return {"stops": res, "total": float(money(load_used)),
            "raw_total": float(money(sum(Decimal(str(b["raw_amount"])) for b in res.values()))),
            "missing_terms": missing}

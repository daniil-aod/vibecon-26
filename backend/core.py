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

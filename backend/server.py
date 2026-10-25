import os
import re
import uuid
import hmac
import asyncio
import hashlib
import logging
import secrets
import mimetypes
from urllib.parse import quote
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List

import httpx
import requests
import stripe
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, UploadFile, File, BackgroundTasks
from fastapi.responses import Response, HTMLResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from clerk_auth import clerk_router, require_user  # noqa: E402
import core  # noqa: E402
from core import now_utc, iso, parse, stop_billing, notice_due_at, haversine_m, compute_load_billing  # noqa: E402
import finalize  # noqa: E402
from storage import put_object, get_object, init_storage, APP_NAME  # noqa: E402
from emailer import send_email, EmailError, EmailTimeout  # noqa: E402
from ratecon import extract_ratecon  # noqa: E402
from sms import send_sms, sms_configured  # noqa: E402
import templates  # noqa: E402
from pdfgen import build_packet  # noqa: E402
import demo  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("dockclock")

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or "sk_test_emergent"
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

app = FastAPI(title="DockClock")
api = APIRouter(prefix="/api")

DEFAULT_RADIUS = 45  # metres (15% of the old 300 m default); per-load override via geofence_radius_m
RADIUS_MIN, RADIUS_MAX = 15, 3000
# Geofence crossing rules (mirrored in the driver app, frontend/src/lib/tracking.ts):
ACC_SLACK_M = 25      # at most this much GPS error is credited toward being inside
EXIT_BUFFER_M = 10    # must be this far past the edge to count as exited (stops GPS jitter flapping)
MAX_FIX_ACC_M = 100   # fixes worse than this can't decide a crossing


def zone_state(dist_m: float, acc: float, radius: float) -> Optional[str]:
    """'inside' / 'outside' for a fix against a geofence, or None if the fix is too inaccurate to decide."""
    if acc > MAX_FIX_ACC_M:
        return None
    d = dist_m - min(acc, ACC_SLACK_M)
    if d <= radius:
        return "inside"
    if d > radius + EXIT_BUFFER_M:
        return "outside"
    return None


def uid() -> str:
    return str(uuid.uuid4())


def token() -> str:
    return secrets.token_urlsafe(24)


def clean(doc):
    if isinstance(doc, list):
        return [clean(d) for d in doc]
    if isinstance(doc, dict):
        return {k: clean(v) for k, v in doc.items() if k != "_id"}
    if isinstance(doc, datetime):
        return iso(doc)
    return doc


def tz_of(fleet) -> ZoneInfo:
    try:
        return ZoneInfo(fleet.get("timezone") or "America/Chicago")
    except Exception:  # noqa
        return ZoneInfo("America/Chicago")


def fmt_local(fleet, s) -> str:
    d = parse(s)
    if not d:
        return "-"
    return d.astimezone(tz_of(fleet)).strftime("%b %d, %Y %I:%M %p %Z")


# ---------------------------------------------------------------- auth / fleet

def _clerk_email(user_id: str) -> tuple[str, str]:
    r = requests.get(f"https://api.clerk.com/v1/users/{user_id}", timeout=10,
                     headers={"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY']}", "User-Agent": "dockclock"})
    r.raise_for_status()
    j = r.json()
    email = ""
    for e in j.get("email_addresses", []):
        if (e.get("verification") or {}).get("status") == "verified":
            email = e["email_address"].lower()
            if e.get("id") == j.get("primary_email_address_id"):
                break
    name = " ".join([x for x in [j.get("first_name"), j.get("last_name")] if x]) or email.split("@")[0]
    return email, name


async def current_member(user: dict = Depends(require_user)) -> dict:
    u = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not u:
        email, name = await asyncio.to_thread(_clerk_email, user["user_id"])
        u = {"user_id": user["user_id"], "email": email, "name": name, "fleet_id": None, "role": None,
             "created_at": iso(now_utc())}
        await db.users.update_one({"user_id": user["user_id"]}, {"$setOnInsert": u}, upsert=True)
        u = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not u.get("fleet_id") and u.get("email"):
        inv = await db.invites.find_one({"email": u["email"], "status": "pending"}, {"_id": 0})
        if inv:
            role = inv.get("role") or "dispatcher"
            await db.users.update_one({"user_id": u["user_id"]}, {"$set": {"fleet_id": inv["fleet_id"], "role": role}})
            await db.invites.update_one({"id": inv["id"]}, {"$set": {"status": "accepted", "accepted_at": iso(now_utc())}})
            # An owner invite (e.g. the demo fleet) hands over ownership so the weekly summary reaches this person.
            if role == "owner":
                await db.fleets.update_one({"id": inv["fleet_id"]}, {"$set": {"owner_user_id": u["user_id"]}})
            u["fleet_id"], u["role"] = inv["fleet_id"], role
    return u


async def fleet_member(member: dict = Depends(current_member)) -> dict:
    if not member.get("fleet_id"):
        raise HTTPException(status_code=409, detail="Create your fleet first")
    fleet = await db.fleets.find_one({"id": member["fleet_id"]}, {"_id": 0})
    if not fleet:
        raise HTTPException(status_code=409, detail="Create your fleet first")
    member["fleet"] = fleet
    return member


def require_owner(member: dict):
    if member.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only the fleet owner can do this")


class FleetIn(BaseModel):
    name: str
    timezone: str = "America/Chicago"
    reply_to_email: Optional[str] = None
    notice_mode: str = "auto"
    origin: Optional[str] = None


class FleetPatch(BaseModel):
    name: Optional[str] = None
    timezone: Optional[str] = None
    reply_to_email: Optional[str] = None
    notice_mode: Optional[str] = None


def _valid_origin(o: Optional[str]) -> Optional[str]:
    if o and re.match(r"^https://[a-z0-9.-]+(:\d+)?$", o.strip().lower()):
        return o.strip().rstrip("/")
    return None


@api.get("/me")
async def me(origin: Optional[str] = None, member: dict = Depends(current_member)):
    fleet = None
    if member.get("fleet_id"):
        fleet = await db.fleets.find_one({"id": member["fleet_id"]}, {"_id": 0})
        o = _valid_origin(origin)
        if fleet and o and fleet.get("app_url") != o:
            await db.fleets.update_one({"id": fleet["id"]}, {"$set": {"app_url": o}})
            fleet["app_url"] = o
    return {"user": member, "fleet": fleet, "sms_configured": sms_configured()}


@api.post("/fleet")
async def create_fleet(body: FleetIn, member: dict = Depends(current_member)):
    if member.get("fleet_id"):
        raise HTTPException(status_code=400, detail="You already belong to a fleet")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Fleet name is required")
    try:
        ZoneInfo(body.timezone)
    except Exception:  # noqa
        raise HTTPException(status_code=400, detail="Unknown time zone")
    fleet = {"id": uid(), "name": body.name.strip(), "timezone": body.timezone,
             "reply_to_email": (body.reply_to_email or member.get("email") or "").strip().lower(),
             "notice_mode": body.notice_mode if body.notice_mode in ("auto", "ask") else "auto",
             "owner_user_id": member["user_id"], "app_url": _valid_origin(body.origin),
             "created_at": iso(now_utc()), "invoice_seq": 1000}
    await db.fleets.insert_one(dict(fleet))
    await db.users.update_one({"user_id": member["user_id"]}, {"$set": {"fleet_id": fleet["id"], "role": "owner"}})
    return fleet


@api.patch("/fleet")
async def patch_fleet(body: FleetPatch, m: dict = Depends(fleet_member)):
    require_owner(m)
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if "timezone" in upd:
        try:
            ZoneInfo(upd["timezone"])
        except Exception:  # noqa
            raise HTTPException(status_code=400, detail="Unknown time zone")
    if "notice_mode" in upd and upd["notice_mode"] not in ("auto", "ask"):
        raise HTTPException(status_code=400, detail="notice_mode must be auto or ask")
    if upd:
        await db.fleets.update_one({"id": m["fleet_id"]}, {"$set": upd})
    return await db.fleets.find_one({"id": m["fleet_id"]}, {"_id": 0})


@api.get("/fleet/team")
async def team(m: dict = Depends(fleet_member)):
    users = await db.users.find({"fleet_id": m["fleet_id"]}, {"_id": 0}).to_list(200)
    invites = await db.invites.find({"fleet_id": m["fleet_id"], "status": "pending"}, {"_id": 0}).to_list(200)
    return {"members": users, "invites": invites}


class InviteIn(BaseModel):
    email: str


@api.post("/fleet/invites")
async def invite(body: InviteIn, m: dict = Depends(fleet_member)):
    require_owner(m)
    email = body.email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Enter a valid email")
    if await db.users.find_one({"email": email, "fleet_id": {"$ne": None}}):
        raise HTTPException(status_code=400, detail="That person already belongs to a fleet")
    inv = {"id": uid(), "fleet_id": m["fleet_id"], "email": email, "status": "pending",
           "invited_by": m["user_id"], "created_at": iso(now_utc()), "email_sent": False}
    fleet = m["fleet"]
    if fleet.get("app_url"):
        subj, html = templates.invite_email(fleet["name"], m.get("name") or "Your fleet owner", fleet["app_url"] + "/sign-up")
        try:
            await send_email(to=email, subject=subj, html=html, reply_to=fleet.get("reply_to_email"))
            inv["email_sent"] = True
        except EmailError as e:
            inv["email_error"] = str(e)
    await db.invites.insert_one(dict(inv))
    return inv


@api.delete("/fleet/invites/{invite_id}")
async def revoke_invite(invite_id: str, m: dict = Depends(fleet_member)):
    require_owner(m)
    r = await db.invites.delete_one({"id": invite_id, "fleet_id": m["fleet_id"]})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ---------------------------------------------------------------- files

async def store_file(fleet_id: str, data: bytes, content_type: str, ext: str, kind: str, extra=None) -> dict:
    path = f"{APP_NAME}/{fleet_id}/{kind}/{uid()}.{ext}"
    res = await asyncio.to_thread(put_object, path, data, content_type)
    rec = {"id": uid(), "fleet_id": fleet_id, "storage_path": res["path"], "content_type": content_type,
           "size": res.get("size", len(data)), "sha256": hashlib.sha256(data).hexdigest(), "kind": kind,
           "is_deleted": False, "created_at": iso(now_utc()), **(extra or {})}
    await db.files.insert_one(dict(rec))
    return rec


async def file_response(file_id: str, fleet_id: str):
    rec = await db.files.find_one({"id": file_id, "fleet_id": fleet_id, "is_deleted": False}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")
    data, ct = await asyncio.to_thread(get_object, rec["storage_path"])
    return Response(content=data, media_type=rec.get("content_type") or ct,
                    headers={"Cache-Control": "private, max-age=3600"})


@api.get("/files/{file_id}")
async def get_file(file_id: str, m: dict = Depends(fleet_member)):
    return await file_response(file_id, m["fleet_id"])


# ---------------------------------------------------------------- geocoding

async def geocode(address: str):
    if not address:
        return None
    try:
        async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "DockClock/1.0 (detention claims)"}) as c:
            r = await c.get("https://nominatim.openstreetmap.org/search",
                            params={"format": "json", "q": address, "limit": 1, "countrycodes": "us,ca,mx"})
            j = r.json()
            if not j:
                # retry without suite / leading facility words
                short = ", ".join(address.split(",")[-3:])
                r = await c.get("https://nominatim.openstreetmap.org/search",
                                params={"format": "json", "q": short, "limit": 1})
                j = r.json()
            if j:
                return float(j[0]["lat"]), float(j[0]["lon"])
    except Exception as e:  # noqa
        logger.warning(f"geocode failed for {address}: {e}")
    return None


@api.get("/geocode")
async def geocode_ep(q: str, m: dict = Depends(fleet_member)):
    res = await geocode(q)
    if not res:
        raise HTTPException(status_code=404, detail="Address not found")
    return {"lat": res[0], "lng": res[1]}


# ---------------------------------------------------------------- rate cons & loads

@api.post("/ratecons/extract")
async def extract(file: UploadFile = File(...), m: dict = Depends(fleet_member)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File is larger than 15 MB")
    name = (file.filename or "ratecon.pdf").lower()
    ct = file.content_type or ""
    if name.endswith(".pdf") or ct == "application/pdf":
        mime, ext = "application/pdf", "pdf"
    elif ct in ("image/png", "image/jpeg", "image/webp") or name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        mime = ct if ct.startswith("image/") else "image/jpeg"
        ext = name.rsplit(".", 1)[-1] if "." in name else "jpg"
    else:
        raise HTTPException(status_code=400, detail="Upload a PDF (or a photo) of the rate confirmation")
    rec = await store_file(m["fleet_id"], data, mime, ext, "ratecon", {"original_filename": file.filename})
    tmp = f"/tmp/{rec['id']}.{ext}"
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        extracted = await extract_ratecon(tmp, mime)
    except Exception as e:  # noqa
        raise HTTPException(status_code=502, detail=f"AI could not read this rate con. You can still enter terms by hand. ({str(e)[:120]})")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    await db.files.update_one({"id": rec["id"]}, {"$set": {"extracted": extracted}})
    return {"file_id": rec["id"], "filename": file.filename, "extracted": extracted}


class BrokerIn(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class DetentionIn(BaseModel):
    free_time_hours: Optional[float] = None
    hourly_rate: Optional[float] = None
    billing_increment_minutes: Optional[float] = 15
    cap_amount: Optional[float] = None
    cap_scope: Optional[str] = "per_stop"
    notice_after_arrival_minutes: Optional[float] = None
    notice_before_expiry_minutes: Optional[float] = None
    notice_rule_text: Optional[str] = None
    requires_signed_bol: Optional[bool] = None
    clause_text: Optional[str] = None
    rounding_rule: Optional[str] = None
    per_day_definition: Optional[str] = None
    billing_start_rule: Optional[str] = None
    late_arrival_voids: Optional[bool] = None
    late_grace_minutes: Optional[float] = None


class BillingTermsIn(BaseModel):
    billing_company: Optional[str] = None
    billing_address: Optional[str] = None
    ap_email: Optional[str] = None
    use_broker_contact_for_billing: Optional[bool] = None
    submission_channel: Optional[str] = None
    portal_url: Optional[str] = None
    submission_other_text: Optional[str] = None
    requires_attachment: Optional[bool] = None
    notice_recipient: Optional[str] = None
    notice_method: Optional[str] = None
    invoice_deadline_days: Optional[float] = None
    invoice_deadline_trigger: Optional[str] = None
    deadline_timezone: Optional[str] = None
    required_documents: Optional[List[dict]] = None
    approval_required: Optional[bool] = None
    approval_method: Optional[str] = None
    approval_rule_text: Optional[str] = None
    payment_terms_days: Optional[float] = None
    payment_terms_start: Optional[str] = None


class StopIn(BaseModel):
    id: Optional[str] = None
    type: str = "pickup"
    facility_name: Optional[str] = None
    address: Optional[str] = None
    appointment: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_m: Optional[float] = None
    terms_override: Optional[dict] = None


class DriverIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class LoadIn(BaseModel):
    file_id: Optional[str] = None
    load_number: Optional[str] = None
    carrier_name: Optional[str] = None
    linehaul_amount: Optional[float] = None
    broker: BrokerIn = BrokerIn()
    detention: DetentionIn = DetentionIn()
    stops: List[StopIn] = []
    driver: DriverIn = DriverIn()
    low_confidence: List[str] = []
    billing_terms: BillingTermsIn = BillingTermsIn()
    refs: Optional[dict] = None
    term_sources: Optional[dict] = None
    term_refs: Optional[dict] = None
    billing_mode: Optional[str] = None
    confirm_billing: Optional[bool] = None
    geofence_radius_m: Optional[float] = None


def _apply_radius(stops: list, radius: Optional[float]):
    """Load-level geofence size from the load form; stops already arrived keep the zone they were judged by."""
    if radius is None:
        return
    if not (RADIUS_MIN <= radius <= RADIUS_MAX):
        raise HTTPException(status_code=400, detail=f"Geofence radius must be {RADIUS_MIN}-{RADIUS_MAX} m")
    for s in stops:
        if not s.get("arrived_at"):
            s["radius_m"] = float(radius)


async def upsert_facility(fleet_id: str, s: dict) -> dict:
    key = re.sub(r"[^a-z0-9]", "", f"{s.get('facility_name') or ''}{s.get('address') or ''}".lower())
    fac = await db.facilities.find_one({"fleet_id": fleet_id, "key": key}, {"_id": 0})
    if fac:
        if s.get("lat") is not None and s.get("lng") is not None and (fac.get("lat") is None):
            await db.facilities.update_one({"id": fac["id"]}, {"$set": {"lat": s["lat"], "lng": s["lng"]}})
            fac.update({"lat": s["lat"], "lng": s["lng"]})
        return fac
    lat, lng = s.get("lat"), s.get("lng")
    if lat is None or lng is None:
        g = await geocode(s.get("address") or "")
        if g:
            lat, lng = g
    fac = {"id": uid(), "fleet_id": fleet_id, "key": key, "name": s.get("facility_name") or "Facility",
           "address": s.get("address") or "", "lat": lat, "lng": lng,
           "radius_m": s.get("radius_m") or DEFAULT_RADIUS, "created_at": iso(now_utc())}
    await db.facilities.insert_one(dict(fac))
    return fac


async def upsert_broker(fleet_id: str, b: dict) -> Optional[str]:
    if not b.get("name"):
        return None
    key = re.sub(r"[^a-z0-9]", "", b["name"].lower())
    br = await db.brokers.find_one({"fleet_id": fleet_id, "key": key}, {"_id": 0})
    if br:
        if b.get("email"):
            await db.brokers.update_one({"id": br["id"]}, {"$set": {"email": b["email"]}})
        return br["id"]
    bid = uid()
    await db.brokers.insert_one({"id": bid, "fleet_id": fleet_id, "key": key, "name": b["name"],
                                 "email": b.get("email"), "created_at": iso(now_utc())})
    return bid


async def build_stops(fleet_id: str, stops_in: List[StopIn], existing: Optional[list] = None) -> list:
    existing = {s["id"]: s for s in (existing or [])}
    out = []
    for i, s in enumerate(stops_in):
        sd = s.model_dump()
        prev = existing.get(sd.get("id") or "")
        if prev:
            prev["terms_override"] = sd.get("terms_override") or prev.get("terms_override")
            changed_place = (sd.get("address") != prev.get("address") or sd.get("facility_name") != prev.get("facility_name"))
            prev.update({"type": sd["type"], "facility_name": sd.get("facility_name"), "address": sd.get("address"),
                         "appointment": sd.get("appointment"), "seq": i})
            if changed_place and not prev.get("arrived_at"):
                fac = await upsert_facility(fleet_id, sd)
                prev.update({"facility_id": fac["id"], "lat": fac.get("lat"), "lng": fac.get("lng"),
                             "radius_m": fac.get("radius_m") or DEFAULT_RADIUS})
            out.append(prev)
            continue
        fac = await upsert_facility(fleet_id, sd)
        out.append({"id": uid(), "seq": i, "type": sd["type"], "facility_id": fac["id"],
                    "facility_name": sd.get("facility_name") or fac["name"], "address": sd.get("address") or fac["address"],
                    "appointment": sd.get("appointment"), "lat": fac.get("lat"), "lng": fac.get("lng"),
                    "radius_m": fac.get("radius_m") or DEFAULT_RADIUS, "arrived_at": None, "departed_at": None,
                    "arrived_source": None, "departed_source": None, "events": [], "bol": [],
                    "terms_override": sd.get("terms_override"),
                    "notice": {"status": "pending", "due_at": None, "sent_at": None}})
    return out


def _billing_fields(d: dict, m: dict, prev: dict | None = None) -> dict:
    """Billing terms + refs + provenance. Values the dispatcher saved are 'confirmed'; extracted ones keep 'extracted'."""
    bt = {k: v for k, v in (d.get("billing_terms") or {}).items()}
    if bt.get("ap_email"):
        bt["ap_email"] = bt["ap_email"].strip()
        if not EMAIL_RE.match(bt["ap_email"]):
            raise HTTPException(status_code=400, detail="Enter a valid accounts-payable email")
    if bt.get("submission_channel") not in (None, "email", "portal", "other"):
        raise HTTPException(status_code=400, detail="Submission method must be email, portal or other")
    src = dict((prev or {}).get("term_sources") or {})
    src.update(d.get("term_sources") or {})
    out = {"billing_terms": bt, "refs": d.get("refs") or (prev or {}).get("refs") or {}, "term_sources": src,
           "term_refs": d.get("term_refs") or (prev or {}).get("term_refs") or {}}
    setup = dict((prev or {}).get("billing_setup") or {"mode": "review"})
    if d.get("billing_mode") in ("auto", "review"):
        if d["billing_mode"] != setup.get("mode"):
            setup.pop("confirmed_at", None)
        setup["mode"] = d["billing_mode"]
    if d.get("confirm_billing"):
        setup.update({"confirmed_at": iso(now_utc()), "confirmed_by": m["user_id"],
                      "destination": finalize.destination({"billing_terms": bt, "broker": d.get("broker")})})
    elif prev and finalize.destination({"billing_terms": bt, "broker": d.get("broker")}) != (setup.get("destination") or {}):
        setup.pop("confirmed_at", None)  # destination changed -> must be re-confirmed
    out["billing_setup"] = setup
    return out


def _clean_driver(drv: dict) -> dict:
    """Trim the driver's email and reject typos up front, so emailing the app link never fails later."""
    email = (drv.get("email") or "").strip()
    if email and not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid driver email (like name@example.com)")
    return {**drv, "email": email}


@api.post("/loads")
async def create_load(body: LoadIn, m: dict = Depends(fleet_member)):
    if not body.stops:
        raise HTTPException(status_code=400, detail="Add at least one stop")
    _apply_radius([], body.geofence_radius_m)  # validate before anything is written
    d = body.model_dump()
    d["driver"] = _clean_driver(d["driver"])
    stops = await build_stops(m["fleet_id"], body.stops)
    _apply_radius(stops, body.geofence_radius_m)
    broker_id = await upsert_broker(m["fleet_id"], d["broker"])
    load = {"id": uid(), "fleet_id": m["fleet_id"], "load_number": d.get("load_number") or f"LOAD-{secrets.token_hex(3).upper()}",
            "geofence_radius_m": body.geofence_radius_m or DEFAULT_RADIUS,
            "carrier_name": d.get("carrier_name"), "linehaul_amount": d.get("linehaul_amount"),
            "broker": d["broker"], "broker_id": broker_id, "detention": d["detention"], "stops": stops,
            "driver": d["driver"], "driver_token": token(), "ratecon_file_id": body.file_id,
            "low_confidence": d.get("low_confidence") or [], "sms_log": [], "status": "planned",
            "created_by": m["user_id"], "created_at": iso(now_utc()), "updated_at": iso(now_utc()),
            **_billing_fields(d, m)}
    if body.file_id:
        f = await db.files.find_one({"id": body.file_id, "fleet_id": m["fleet_id"]}, {"_id": 0, "extracted": 1})
        load["source_documents"] = [{"kind": "ratecon", "file_id": body.file_id,
                                     "version": ((f or {}).get("extracted") or {}).get("document_version")}]
    await db.loads.insert_one(dict(load))
    return await load_view(load, m["fleet"])


async def get_load(load_id: str, fleet_id: str) -> dict:
    load = await db.loads.find_one({"id": load_id, "fleet_id": fleet_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Load not found")
    return load


def load_status(load: dict, invoices: list) -> str:
    stops = load.get("stops", [])
    if any(i["status"] == "paid" for i in invoices) and all(i["status"] in ("paid", "written_off") for i in invoices):
        return "paid"
    if any(i["status"] in ("sent",) for i in invoices):
        return "invoiced"
    if any(i["status"] == "disputed" for i in invoices):
        return "disputed"
    if any(i["status"] == "ready" for i in invoices):
        return "ready"
    if any(s.get("arrived_at") and not s.get("departed_at") for s in stops):
        return "on_site"
    if stops and all(s.get("departed_at") for s in stops):
        return "completed"
    if any(s.get("arrived_at") for s in stops):
        return "in_transit"
    if load.get("sms_log"):
        return "dispatched"
    return "planned"


def stops_with_billing(load: dict, fleet: dict | None = None) -> list:
    """Every screen, invoice, PDF, email and Stripe amount reads this one calculation (core.compute_load_billing)."""
    res = compute_load_billing(load, tz=tz_of(fleet) if fleet else None)
    return [{**s, "billing": res["stops"][s["id"]]} for s in sorted(load.get("stops", []), key=lambda x: x.get("seq", 0))]


async def load_view(load: dict, fleet: dict, full: bool = False) -> dict:
    invoices = await db.invoices.find({"load_id": load["id"]}, {"_id": 0}).to_list(50)
    v = {**load, "stops": stops_with_billing(load, fleet), "status": load_status(load, invoices),
         "invoices": invoices, "driver_url": f"{fleet.get('app_url') or ''}/api/open/{load['driver_token']}"}
    v["detention_total"] = round(sum(s["billing"]["amount"] for s in v["stops"]), 2)
    if full:
        v["notices"] = await db.notices.find({"load_id": load["id"]}, {"_id": 0}).sort("created_at", 1).to_list(100)
    return v


@api.get("/loads")
async def list_loads(m: dict = Depends(fleet_member)):
    loads = await db.loads.find({"fleet_id": m["fleet_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [await load_view(ld, m["fleet"]) for ld in loads]


@api.get("/loads/{load_id}")
async def load_detail(load_id: str, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    await process_load(load, m["fleet"])
    load = await get_load(load_id, m["fleet_id"])
    return await load_view(load, m["fleet"], full=True)


@api.put("/loads/{load_id}")
async def update_load(load_id: str, body: LoadIn, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    d = body.model_dump()
    d["driver"] = _clean_driver(d["driver"])
    radius_changed = body.geofence_radius_m is not None and body.geofence_radius_m != (load.get("geofence_radius_m") or DEFAULT_RADIUS)
    if radius_changed:
        _apply_radius([], body.geofence_radius_m)  # validate before anything is written
    stops = await build_stops(m["fleet_id"], body.stops, load.get("stops"))
    if radius_changed:
        _apply_radius(stops, body.geofence_radius_m)  # only when the dispatcher changed it (keeps per-facility tweaks)
    broker_id = await upsert_broker(m["fleet_id"], d["broker"])
    upd = {"load_number": d.get("load_number") or load["load_number"], "carrier_name": d.get("carrier_name"),
           "geofence_radius_m": body.geofence_radius_m or load.get("geofence_radius_m") or DEFAULT_RADIUS,
           "linehaul_amount": d.get("linehaul_amount"), "broker": d["broker"], "broker_id": broker_id,
           "detention": d["detention"], "stops": stops, "driver": d["driver"], "updated_at": iso(now_utc()),
           **_billing_fields(d, m, load)}
    # recompute notice due times for on-site stops
    for s in stops:
        if s.get("arrived_at") and s["notice"]["status"] == "pending":
            s["notice"]["due_at"] = iso(notice_due_at(parse(s["arrived_at"]), d["detention"]))
    await db.loads.update_one({"id": load_id}, {"$set": upd})
    await process_load(await get_load(load_id, m["fleet_id"]), m["fleet"], trigger="terms_change", actor=m["user_id"])
    return await load_view(await get_load(load_id, m["fleet_id"]), m["fleet"], full=True)


@api.delete("/loads/{load_id}")
async def delete_load(load_id: str, m: dict = Depends(fleet_member)):
    await get_load(load_id, m["fleet_id"])
    if await db.invoices.find_one({"load_id": load_id, "status": {"$in": ["sent", "paid"]}}):
        raise HTTPException(status_code=400, detail="This load has sent or paid invoices and cannot be deleted")
    await db.loads.delete_one({"id": load_id})
    await db.invoices.delete_many({"load_id": load_id})
    await db.pings.delete_many({"load_id": load_id})
    return {"ok": True}


@api.get("/loads/{load_id}/ratecon")
async def load_ratecon(load_id: str, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    if not load.get("ratecon_file_id"):
        raise HTTPException(status_code=404, detail="No rate con on file")
    return await file_response(load["ratecon_file_id"], m["fleet_id"])


@api.post("/loads/{load_id}/sms")
async def text_driver(load_id: str, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    fleet = m["fleet"]
    drv = load.get("driver") or {}
    if not drv.get("phone"):
        raise HTTPException(status_code=400, detail="Add the driver's phone number first")
    if not fleet.get("app_url"):
        raise HTTPException(status_code=400, detail="App address unknown yet; reload the page and try again")
    url = f"{fleet['app_url']}/api/open/{load['driver_token']}"
    first = load["stops"][0] if load.get("stops") else {}
    body = (f"{fleet['name']} via DockClock: Hi {drv.get('name') or 'driver'}, your load "
            f"{load['load_number']} ({first.get('facility_name') or ''}) is ready: {url} "
            f"Tap to open it in the DockClock Driver app, then press Start ride.")
    res = await send_sms(drv["phone"], body)
    entry = {"at": iso(now_utc()), "to": drv["phone"], "by": m["user_id"], **res}
    await db.loads.update_one({"id": load_id}, {"$push": {"sms_log": entry}})
    return {**res, "driver_url": url}


# ---------------------------------------------------------------- driver emails (link / recap, now or scheduled)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FREQS = ("once", "daily", "weekly", "monthly")
KINDS = ("link", "recap")


def _driver_link(fleet, load) -> str:
    return f"{fleet['app_url']}/api/open/{load['driver_token']}"


def _recap_window(freq: str):
    now = now_utc()
    return {"daily": now - timedelta(days=1), "weekly": now - timedelta(days=7),
            "monthly": now - timedelta(days=31)}.get(freq)


async def _recap_rows(fleet, load, freq: str):
    """Stops for this driver: this load for one-time recaps, otherwise every load of the driver in the period."""
    email = ((load.get("driver") or {}).get("email") or "").lower()
    since = _recap_window(freq)
    loads = [load]
    if since and email:
        loads = await db.loads.find({"fleet_id": fleet["id"], "driver.email": {"$regex": f"^{re.escape(email)}$", "$options": "i"},
                                     "stops": {"$elemMatch": {"arrived_at": {"$gte": iso(since)}}}}, {"_id": 0}).to_list(500)
    rows = []
    for ld in sorted(loads, key=lambda x: x.get("created_at") or ""):
        for s in sorted(ld.get("stops", []), key=lambda x: x.get("seq", 0)):
            a, d = parse(s.get("arrived_at")), parse(s.get("departed_at"))
            if not a or (since and a < since):
                continue
            wait = int(((d or now_utc()) - a).total_seconds() // 60)
            rows.append({"load": ld.get("load_number"), "facility": s.get("facility_name"), "type": s.get("type"),
                         "in": fmt_local(fleet, s.get("arrived_at")),
                         "out": fmt_local(fleet, s.get("departed_at")) if d else "On site",
                         "wait": f"{wait // 60}h {wait % 60:02d}m"})
    return rows


async def send_driver_email(fleet, load, kind: str, freq: str = "once", by: str | None = None) -> dict:
    drv = load.get("driver") or {}
    to = (drv.get("email") or "").strip()
    if not EMAIL_RE.match(to):
        return {"sent": False, "reason": "no_email",
                "detail": "The driver's email looks invalid; fix it with Edit terms" if to else "Add the driver's email first"}
    if not fleet.get("app_url"):
        return {"sent": False, "reason": "no_app_url", "detail": "App address unknown yet; reload the page and try again"}
    if kind == "link":
        first = next((s for s in sorted(load.get("stops", []), key=lambda x: x.get("seq", 0)) if not s.get("departed_at")), None) \
            or (load.get("stops") or [{}])[0]
        subj, html = templates.driver_link_email(fleet["name"], drv.get("name") or "", load["load_number"],
                                                 first.get("facility_name") or "", _driver_link(fleet, load))
    else:
        label = {"once": f"load {load['load_number']}", "daily": "the last day", "weekly": "the last 7 days",
                 "monthly": "the last month"}[freq]
        subj, html = templates.driver_recap_email(fleet["name"], drv.get("name") or "", label, await _recap_rows(fleet, load, freq))
    entry = {"at": iso(now_utc()), "to": to, "kind": kind, "by": by}
    try:
        entry["email_id"] = await send_email(to=to, subject=subj, html=html, reply_to=fleet.get("reply_to_email"))
        entry["sent"] = True
    except (EmailError, ValueError) as e:
        msg = str(e)
        if "429" in msg or "rate" in msg.lower():
            msg = "Email provider is busy (rate limited) — try again in a minute"
        entry.update({"sent": False, "reason": "email_error", "detail": msg[:300]})
    await db.loads.update_one({"id": load["id"]}, {"$push": {"email_log": entry}})
    return entry


class DriverEmailIn(BaseModel):
    kind: str = "link"


@api.post("/loads/{load_id}/email-driver")
async def email_driver(load_id: str, body: DriverEmailIn, m: dict = Depends(fleet_member)):
    if body.kind not in KINDS:
        raise HTTPException(status_code=400, detail="Unknown email type")
    load = await get_load(load_id, m["fleet_id"])
    res = await send_driver_email(m["fleet"], load, body.kind, "once", m["user_id"])
    if not res.get("sent") and res.get("reason") in ("no_email", "no_app_url"):
        raise HTTPException(status_code=400, detail=res["detail"])
    return {**res, "driver_url": _driver_link(m["fleet"], load) if m["fleet"].get("app_url") else None}


def _add_month(d: datetime) -> datetime:
    y, mo = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    import calendar
    return d.replace(year=y, month=mo, day=min(d.day, calendar.monthrange(y, mo)[1]))


def next_run(prev_utc: datetime, freq: str, fleet) -> datetime | None:
    """Next send time, keeping the same local wall-clock time in the fleet's timezone."""
    if freq == "once":
        return None
    local = prev_utc.astimezone(tz_of(fleet)).replace(tzinfo=None)
    local = local + timedelta(days=1) if freq == "daily" else local + timedelta(days=7) if freq == "weekly" else _add_month(local)
    return local.replace(tzinfo=tz_of(fleet)).astimezone(timezone.utc)


class ScheduleIn(BaseModel):
    kind: str
    frequency: str
    send_at: str  # ISO datetime (first send)


def _sched_out(s):
    return {k: s.get(k) for k in ("id", "load_id", "kind", "frequency", "send_at", "next_run_at", "active",
                                   "last_sent_at", "last_result", "created_at")}


@api.get("/loads/{load_id}/email-schedules")
async def list_schedules(load_id: str, m: dict = Depends(fleet_member)):
    await get_load(load_id, m["fleet_id"])
    rows = await db.email_schedules.find({"fleet_id": m["fleet_id"], "load_id": load_id}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return [_sched_out(s) for s in rows]


@api.post("/loads/{load_id}/email-schedules")
async def create_schedule(load_id: str, body: ScheduleIn, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    if body.kind not in KINDS or body.frequency not in FREQS:
        raise HTTPException(status_code=400, detail="Pick what to send and how often")
    if not EMAIL_RE.match(((load.get("driver") or {}).get("email") or "").strip()):
        raise HTTPException(status_code=400, detail="Add the driver's email first")
    try:
        at = parse(body.send_at)
    except ValueError:
        at = None
    if not at:
        raise HTTPException(status_code=400, detail="Pick a valid send time")
    if body.frequency == "once" and at < now_utc() - timedelta(minutes=1):
        raise HTTPException(status_code=400, detail="Pick a time in the future")
    s = {"id": uid(), "fleet_id": m["fleet_id"], "load_id": load_id, "kind": body.kind, "frequency": body.frequency,
         "send_at": iso(at), "next_run_at": iso(at), "active": True, "last_sent_at": None, "last_result": None,
         "created_by": m["user_id"], "created_at": iso(now_utc())}
    await db.email_schedules.insert_one(dict(s))
    return _sched_out(s)


@api.delete("/email-schedules/{sid}")
async def delete_schedule(sid: str, m: dict = Depends(fleet_member)):
    r = await db.email_schedules.delete_one({"id": sid, "fleet_id": m["fleet_id"]})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"ok": True}


def occurrence(base_utc: datetime, freq: str, fleet, n: int) -> datetime | None:
    """The n-th send after the first, always counted from the original send time (no drift),
    at the same local wall-clock time in the fleet's timezone."""
    if freq == "once":
        return None
    import calendar
    tz = tz_of(fleet)
    local = base_utc.astimezone(tz).replace(tzinfo=None)
    if freq == "daily":
        local = local + timedelta(days=n)
    elif freq == "weekly":
        local = local + timedelta(days=7 * n)
    else:
        mo = local.month - 1 + n
        y, mo = local.year + mo // 12, mo % 12 + 1
        local = local.replace(year=y, month=mo, day=min(local.day, calendar.monthrange(y, mo)[1]))
    return local.replace(tzinfo=tz).astimezone(timezone.utc)


TRANSIENT_RETRIES = 4


async def run_schedules(fmap: dict):
    now = now_utc()
    due = await db.email_schedules.find({"active": True, "next_run_at": {"$lte": iso(now)}}, {"_id": 0}).to_list(1000)
    for s in due:
        fleet = fmap.get(s["fleet_id"])
        load = await db.loads.find_one({"id": s["load_id"], "fleet_id": s["fleet_id"]}, {"_id": 0})
        if not fleet or not load:
            await db.email_schedules.update_one({"id": s["id"]}, {"$set": {"active": False, "last_result": "load_missing"}})
            continue
        runs = int(s.get("runs") or 0)
        n = runs + 1
        nxt = occurrence(parse(s["send_at"]), s["frequency"], fleet, n)
        while nxt and nxt <= now:  # skip missed runs (e.g. server was down)
            n += 1
            nxt = occurrence(parse(s["send_at"]), s["frequency"], fleet, n)
        # Claim this run first so overlapping ticks never double-send.
        claim = await db.email_schedules.update_one(
            {"id": s["id"], "active": True, "next_run_at": s["next_run_at"]},
            {"$set": {"next_run_at": iso(nxt) if nxt else s["next_run_at"], "active": bool(nxt), "runs": n - 1 if nxt else runs}})
        if not claim.modified_count:
            continue
        try:
            res = await send_driver_email(fleet, load, s["kind"], s["frequency"], "schedule")
        except Exception as e:  # noqa
            res = {"sent": False, "reason": "error", "detail": str(e)[:200]}
        upd = {"last_sent_at": iso(now_utc()), "last_result": "sent" if res.get("sent") else (res.get("detail") or res.get("reason"))}
        retries = int(s.get("retries") or 0)
        if res.get("sent"):
            upd["retries"] = 0
        elif res.get("reason") not in ("no_email", "no_app_url") and retries < TRANSIENT_RETRIES:
            # Temporary failure (e.g. provider rate limit): undo the claim and retry in ~15 minutes.
            upd.update({"active": True, "runs": runs, "retries": retries + 1,
                        "next_run_at": iso(now_utc() + timedelta(minutes=15)), "last_result": f"retrying: {upd['last_result']}"})
        await db.email_schedules.update_one({"id": s["id"]}, {"$set": upd})


class AdjustIn(BaseModel):
    arrived_at: Optional[str] = None
    departed_at: Optional[str] = None
    reason: str = ""


@api.post("/loads/{load_id}/stops/{stop_id}/adjust")
async def adjust_stop(load_id: str, stop_id: str, body: AdjustIn, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    if not body.reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required for manual time changes")
    stop = next((s for s in load["stops"] if s["id"] == stop_id), None)
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")
    a, dep = parse(body.arrived_at) if body.arrived_at else None, parse(body.departed_at) if body.departed_at else None
    if a and dep and dep <= a:
        raise HTTPException(status_code=400, detail="Departure must be after arrival")
    if a:
        await record_arrival(load, stop, a, "dispatcher_edit", None, m["fleet"], note=body.reason)
        load = await get_load(load_id, m["fleet_id"])
        stop = next(s for s in load["stops"] if s["id"] == stop_id)
    if dep:
        if not stop.get("arrived_at"):
            raise HTTPException(status_code=400, detail="Set an arrival time first")
        await record_departure(load, stop, dep, "dispatcher_edit", None, m["fleet"], note=body.reason)
    load = await get_load(load_id, m["fleet_id"])
    await process_load(load, m["fleet"], trigger="dispatcher_correction", actor=m["user_id"])
    return await load_view(await get_load(load_id, m["fleet_id"]), m["fleet"], full=True)


@api.post("/loads/{load_id}/stops/{stop_id}/notice")
async def send_notice_now(load_id: str, stop_id: str, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    stop = next((s for s in load["stops"] if s["id"] == stop_id), None)
    if not stop or not stop.get("arrived_at"):
        raise HTTPException(status_code=400, detail="The truck has not arrived at this stop yet")
    if stop["notice"].get("sent_at"):
        raise HTTPException(status_code=400, detail="Notice already sent")
    ok, err = await deliver_notice(load, stop, m["fleet"], manual_by=m["user_id"])
    if not ok:
        raise HTTPException(status_code=502, detail=err or "Could not send notice")
    return await load_view(await get_load(load_id, m["fleet_id"]), m["fleet"], full=True)


@api.get("/loads/{load_id}/playback")
async def playback(load_id: str, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    return await playback_data(load)


async def playback_data(load: dict, stop_id: Optional[str] = None) -> dict:
    q = {"load_id": load["id"]}
    pings = await db.pings.find(q, {"_id": 0, "lat": 1, "lng": 1, "ts": 1, "accuracy": 1, "stop_id": 1, "received_at": 1}).sort("ts", 1).to_list(20000)
    stops = stops_with_billing(load)
    if stop_id:
        stops = [s for s in stops if s["id"] == stop_id]
    events = []
    for s in stops:
        for e in s.get("events", []):
            events.append({**e, "stop_id": s["id"], "facility_name": s.get("facility_name")})
    events.sort(key=lambda e: e.get("at") or "")
    if stop_id and stops:
        s = stops[0]
        a, d = parse(s.get("arrived_at")), parse(s.get("departed_at"))
        if a:
            lo = iso(a - timedelta(minutes=45))
            hi = iso((d or now_utc()) + timedelta(minutes=45))
            pings = [p for p in pings if lo <= p["ts"] <= hi]
    return {"pings": pings, "stops": [{k: s.get(k) for k in ("id", "facility_name", "lat", "lng", "radius_m", "arrived_at",
                                                              "departed_at", "type", "billing")} for s in stops],
            "events": events}


class FacilityPatch(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_m: Optional[float] = None


@api.get("/facilities")
async def facilities(m: dict = Depends(fleet_member)):
    return await db.facilities.find({"fleet_id": m["fleet_id"]}, {"_id": 0}).to_list(1000)


@api.patch("/facilities/{fac_id}")
async def patch_facility(fac_id: str, body: FacilityPatch, m: dict = Depends(fleet_member)):
    fac = await db.facilities.find_one({"id": fac_id, "fleet_id": m["fleet_id"]}, {"_id": 0})
    if not fac:
        raise HTTPException(status_code=404, detail="Facility not found")
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if "radius_m" in upd and not (RADIUS_MIN <= upd["radius_m"] <= RADIUS_MAX):
        raise HTTPException(status_code=400, detail=f"Radius must be between {RADIUS_MIN} and {RADIUS_MAX} meters")
    await db.facilities.update_one({"id": fac_id}, {"$set": upd})
    # propagate to stops that have not been arrived at yet
    loads = await db.loads.find({"fleet_id": m["fleet_id"], "stops.facility_id": fac_id}, {"_id": 0}).to_list(500)
    for ld in loads:
        changed = False
        for s in ld["stops"]:
            if s.get("facility_id") == fac_id and not s.get("arrived_at"):
                s.update({k: v for k, v in upd.items()})
                changed = True
        if changed:
            await db.loads.update_one({"id": ld["id"]}, {"$set": {"stops": ld["stops"]}})
    return await db.facilities.find_one({"id": fac_id}, {"_id": 0})


# ---------------------------------------------------------------- stop state machine

async def save_stop(load_id: str, stop: dict):
    await db.loads.update_one({"id": load_id, "stops.id": stop["id"]},
                              {"$set": {"stops.$": stop, "updated_at": iso(now_utc())}})


async def record_arrival(load, stop, at: datetime, source: str, coords, fleet, note=None):
    det = load.get("detention") or {}
    stop["arrived_at"] = iso(at)
    stop["arrived_source"] = source
    stop["arrived_coords"] = coords
    stop["events"] = [e for e in stop.get("events", []) if e["type"] not in ("arrival", "free_time_expired")]
    stop["events"].append({"type": "arrival", "at": iso(at), "source": source, "coords": coords, "note": note})
    if stop["notice"].get("status") in ("pending", "awaiting_approval", None):
        stop["notice"]["due_at"] = iso(notice_due_at(at, det))
        stop["notice"]["status"] = "pending"
    await save_stop(load["id"], stop)


async def record_departure(load, stop, at: datetime, source: str, coords, fleet, note=None):
    stop["departed_at"] = iso(at)
    stop["departed_source"] = source
    stop["departed_coords"] = coords
    stop["events"] = [e for e in stop.get("events", []) if e["type"] != "departure"]
    stop["events"].append({"type": "departure", "at": iso(at), "source": source, "coords": coords, "note": note})
    if stop["notice"].get("status") in ("pending", "awaiting_approval") and not stop["notice"].get("sent_at"):
        b = compute_load_billing({**load, "stops": [stop]})["stops"][stop["id"]]
        stop["notice"]["status"] = "not_needed" if b["billable_minutes"] <= 0 and b["dwell_minutes"] < (b["free_minutes"] or 0) else "missed"
    await save_stop(load["id"], stop)


async def deliver_notice(load, stop, fleet, manual_by=None):
    broker = load.get("broker") or {}
    to = (broker.get("email") or "").strip()
    if not to:
        stop["notice"]["status"] = "no_email"
        await save_stop(load["id"], stop)
        return False, "No broker email on this load"
    b = compute_load_billing({**load, "stops": [stop]}, tz=tz_of(fleet))["stops"][stop["id"]]
    deadline = finalize._notice_deadline(stop, load.get("detention") or {}, b)
    was_missed = stop["notice"].get("status") == "missed"
    coords = stop.get("arrived_coords") or {}
    lat, lng = coords.get("lat") or stop.get("lat"), coords.get("lng") or stop.get("lng")
    maps_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}" if lat and lng else None
    subj, html = templates.notice_email(fleet["name"], load, stop, fmt_local(fleet, b.get("free_expires_at")),
                                        fmt_local(fleet, stop.get("arrived_at")), maps_url)
    try:
        if fleet.get("is_demo") or finalize.SUBMISSION_MODE != "live":
            email_id = f"SIMULATED-{uid()[:8]}"  # no real broker email while in simulate mode
        else:
            email_id = await send_email(to=to, subject=subj, html=html, reply_to=fleet.get("reply_to_email"))
    except EmailError as e:
        stop["notice"]["status"] = "failed"
        stop["notice"]["error"] = str(e)
        await save_stop(load["id"], stop)
        return False, str(e)
    sent = iso(now_utc())
    if fleet.get("reply_to_email") and not email_id.startswith("SIMULATED"):
        try:
            await send_email(to=fleet["reply_to_email"], subject=f"[Copy] {subj}", html=html)
        except EmailError:
            pass
    stop["notice"].update({"status": "sent", "sent_at": sent, "to": to, "email_id": email_id, "manual_by": manual_by})
    stop["events"].append({"type": "notice_sent", "at": sent, "to": to})
    await save_stop(load["id"], stop)
    await db.notices.insert_one({"id": uid(), "fleet_id": fleet["id"], "load_id": load["id"], "stop_id": stop["id"],
                                 "kind": "detention_notice", "to": to, "sent_at": sent, "email_id": email_id,
                                 "on_time": bool(not was_missed and deadline and sent <= iso(deadline)),
                                 "deadline": iso(deadline), "method": "email",
                                 "created_at": sent})
    return True, None


async def ensure_invoice(load, stop, fleet):
    b = stop_billing(stop, load.get("detention") or {})
    if b["amount"] <= 0:
        return None
    existing = await db.invoices.find_one({"load_id": load["id"], "stop_id": stop["id"]}, {"_id": 0})
    if existing:
        if existing["status"] == "ready" and abs(existing["amount"] - b["amount"]) > 0.001:
            await db.invoices.update_one({"id": existing["id"]}, {"$set": {"amount": b["amount"],
                                                                         "billable_label": f"{b['billed_minutes'] / 60:.2f} h"}})
        return existing
    seq = await db.fleets.find_one_and_update({"id": fleet["id"]}, {"$inc": {"invoice_seq": 1}}, return_document=True)
    inv = {"id": uid(), "fleet_id": fleet["id"], "load_id": load["id"], "stop_id": stop["id"],
           "number": f"DC-{(seq or {}).get('invoice_seq', 1001)}", "load_number": load.get("load_number"),
           "broker_id": load.get("broker_id"), "broker_name": (load.get("broker") or {}).get("name"),
           "broker_email": (load.get("broker") or {}).get("email"), "facility_id": stop.get("facility_id"),
           "facility_name": stop.get("facility_name"), "amount": b["amount"],
           "billable_label": f"{b['billed_minutes'] / 60:.2f} h", "status": "ready", "public_token": token(),
           "fingerprint": None, "sealed_evidence": None, "reminders": [], "reminders_paused": False,
           "created_at": iso(now_utc()), "sent_at": None, "paid_at": None}
    await db.invoices.insert_one(dict(inv))
    return inv


async def process_load(load: dict, fleet: dict, trigger: str = "tick", actor: str | None = None):
    """Idempotent: free-time events and time-sensitive notices for every stop (even while later stops are
    still active), then the shared completion/finalization service (invoices, packet, submission)."""
    now = now_utc()
    allb = compute_load_billing(load, now, tz_of(fleet))["stops"]
    for stop in load.get("stops", []):
        if not stop.get("arrived_at"):
            continue
        changed = False
        b = allb[stop["id"]]
        fe = parse(b.get("free_expires_at"))
        end = parse(stop.get("departed_at")) or now
        if fe and end >= fe and (b["free_minutes"] or 0) >= 0 and not any(e["type"] == "free_time_expired" for e in stop["events"]):
            stop["events"].append({"type": "free_time_expired", "at": iso(fe)})
            changed = True
        if not stop.get("departed_at"):
            n = stop["notice"]
            due = parse(n.get("due_at"))
            if n.get("status") == "pending" and due and now >= due:
                if fleet.get("notice_mode", "auto") == "auto":
                    await deliver_notice(load, stop, fleet)
                    continue
                n["status"] = "awaiting_approval"
                changed = True
        if changed:
            await save_stop(load["id"], stop)
    await finalize.finalize_load(load["id"], trigger, actor)


# ---------------------------------------------------------------- driver (public link)

async def load_by_driver_token(tok: str) -> dict:
    load = await db.loads.find_one({"driver_token": tok}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="This link is not valid")
    return load


def driver_payload(load, fleet):
    stops = stops_with_billing(load, fleet)
    docs = finalize.documents_state(load)
    transport = finalize.transport_state(load)["state"]
    return {"transport_completed": transport == "completed",
            "documents_needed": [x["message"] for x in docs["missing"]],
            "load_number": load.get("load_number"), "fleet_name": fleet.get("name"),
            "driver_name": (load.get("driver") or {}).get("name"),
            "free_time_hours": (load.get("detention") or {}).get("free_time_hours"),
            "requires_signed_bol": (load.get("detention") or {}).get("requires_signed_bol"),
            "test_load": bool(load.get("is_test_load")),
            "ride": load.get("ride") or None,
            "stops": [{k: s.get(k) for k in ("id", "seq", "type", "facility_name", "address", "appointment", "lat", "lng",
                                            "radius_m", "arrived_at", "departed_at", "arrived_source", "departed_source")}
                      | {"bol_count": len(s.get("bol", [])), "free_expires_at": s["billing"].get("free_expires_at"),
                         "notice_sent_at": s["notice"].get("sent_at")} for s in stops]}


@api.post("/driver/{tok}/ride/start")
async def driver_ride_start(tok: str):
    """Driver pressed Start ride: the load's main trip timer begins (shown on the web timeline too)."""
    load = await load_by_driver_token(tok)
    ride = load.get("ride") or {}
    if not ride.get("started_at") or ride.get("ended_at"):
        ride = {"started_at": iso(now_utc()), "ended_at": None}
        await db.loads.update_one({"id": load["id"]}, {"$set": {"ride": ride, "updated_at": iso(now_utc())}})
    fleet = await db.fleets.find_one({"id": load["fleet_id"]}, {"_id": 0})
    return driver_payload(await load_by_driver_token(tok), fleet)


class RideEndIn(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy: Optional[float] = None


@api.post("/driver/{tok}/ride/end")
async def driver_ride_end(tok: str, body: RideEndIn = RideEndIn()):
    """Driver pressed End ride: stops the main timer AND closes any open zone (departure stamped now)."""
    load = await load_by_driver_token(tok)
    fleet = await db.fleets.find_one({"id": load["fleet_id"]}, {"_id": 0})
    now = now_utc()
    coords = {"lat": body.lat, "lng": body.lng, "accuracy": body.accuracy} if body.lat is not None else None
    for s in load.get("stops", []):
        if s.get("arrived_at") and not s.get("departed_at"):
            await record_departure(load, s, now, "ride_end", coords, fleet, note="Driver ended the ride inside the zone")
    ride = load.get("ride") or {}
    ride = {"started_at": ride.get("started_at") or iso(now), "ended_at": iso(now)}
    await db.loads.update_one({"id": load["id"]}, {"$set": {"ride": ride, "updated_at": iso(now)}})
    load = await load_by_driver_token(tok)
    await process_load(load, fleet)
    return driver_payload(await load_by_driver_token(tok), fleet)


@api.post("/driver/{tok}/reset-test")
async def driver_reset_test(tok: str):
    """Only for the owner's test load: put it back to 'not started' so the trip can be tried again."""
    load = await load_by_driver_token(tok)
    if not load.get("is_test_load"):
        raise HTTPException(status_code=403, detail="Only test loads can be reset")
    for s in load["stops"]:
        s.update({"arrived_at": None, "departed_at": None, "arrived_source": None, "departed_source": None,
                  "arrived_coords": None, "departed_coords": None, "events": [], "bol": [],
                  "notice": {"status": "pending", "due_at": None, "sent_at": None}})
    await db.loads.update_one({"id": load["id"]}, {"$set": {"stops": load["stops"], "last_ping": None, "ride": None, "updated_at": iso(now_utc())}})
    await db.pings.delete_many({"load_id": load["id"]})
    await db.invoices.delete_many({"load_id": load["id"]})
    await db.notices.delete_many({"load_id": load["id"]})
    fleet = await db.fleets.find_one({"id": load["fleet_id"]}, {"_id": 0})
    return driver_payload(await load_by_driver_token(tok), fleet)


@api.get("/open/{tok}", response_class=HTMLResponse)
async def driver_open(tok: str, request: Request):
    """Texted link target: opens the DockClock Driver mobile app, or explains how to install it."""
    load = await db.loads.find_one({"driver_token": tok}, {"_id": 0, "load_number": 1, "driver": 1})
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    origin = f"https://{host}" if host else ""
    deep = f"dockclock://d/{tok}?api={quote(origin, safe='')}"
    page_url = f"{origin}/api/open/{tok}?noapp=1"
    # Android: if the app isn't installed, Chrome falls back to this page instead of "app can't be found".
    intent = (f"intent://d/{tok}?api={quote(origin, safe='')}#Intent;scheme=dockclock;"
              f"S.browser_fallback_url={quote(page_url, safe='')};end")
    expo_go = os.environ.get("DRIVER_APP_EXPO_GO_URL", "").rstrip("/")
    expo_go_link = f"{expo_go}/--/d/{tok}?api={quote(origin, safe='')}" if expo_go else ""
    ios_url = os.environ.get("DRIVER_APP_IOS_URL", "")
    android_url = os.environ.get("DRIVER_APP_ANDROID_URL", "")
    return HTMLResponse(templates.driver_open_page(
        expo_go_link=expo_go_link, auto_open=request.query_params.get("noapp") != "1",
        valid=bool(load), load_number=(load or {}).get("load_number") or "",
        driver_name=((load or {}).get("driver") or {}).get("name") or "",
        deep_link=deep, intent_link=intent, ios_url=ios_url, android_url=android_url),
        status_code=200 if load else 404)


@api.get("/driver/{tok}")
async def driver_get(tok: str):
    load = await load_by_driver_token(tok)
    fleet = await db.fleets.find_one({"id": load["fleet_id"]}, {"_id": 0})
    return driver_payload(load, fleet)


class PingIn(BaseModel):
    lat: float
    lng: float
    accuracy: Optional[float] = None
    ts: Optional[str] = None


def _ping_time(raw: Optional[str]) -> datetime:
    """Use the phone's GPS time for points saved offline (up to 24h old); otherwise server time."""
    now = now_utc()
    try:
        d = parse(raw) if raw else None
    except ValueError:
        d = None
    if d is None:
        return now
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    if d > now + timedelta(minutes=2) or d < now - timedelta(hours=24):
        return now
    return min(d, now)


def _current_stop(load):
    for s in sorted(load.get("stops", []), key=lambda x: x.get("seq", 0)):
        if not s.get("departed_at"):
            return s
    return None


@api.post("/driver/{tok}/ping")
async def driver_ping(tok: str, body: PingIn):
    load = await load_by_driver_token(tok)
    fleet = await db.fleets.find_one({"id": load["fleet_id"]}, {"_id": 0})
    ts = _ping_time(body.ts)
    acc = 50 if body.accuracy is None else body.accuracy
    stop = _current_stop(load)
    event = None
    if (load.get("ride") or {}).get("ended_at"):
        stop = None  # ride ended: keep the point for the trail, but no more zone events
    if stop is not None and stop.get("lat") is not None:
        dist = haversine_m(body.lat, body.lng, stop["lat"], stop["lng"])
        radius = float(stop.get("radius_m") or DEFAULT_RADIUS)
        coords = {"lat": body.lat, "lng": body.lng, "accuracy": acc}
        arrived = parse(stop.get("arrived_at")) if stop.get("arrived_at") else None
        zs = zone_state(dist, acc, radius)
        if not stop.get("arrived_at") and zs == "inside":
            await record_arrival(load, stop, ts, "geofence", coords, fleet)
            event = "arrived"
        elif arrived and ts > arrived and not stop.get("departed_at") and zs == "outside":
            await record_departure(load, stop, ts, "geofence", coords, fleet)
            event = "departed"
    await db.pings.insert_one({"load_id": load["id"], "fleet_id": load["fleet_id"], "lat": body.lat, "lng": body.lng,
                               "accuracy": acc, "ts": iso(ts), "received_at": iso(now_utc()), "stop_id": stop["id"] if stop else None})
    prev = parse((load.get("last_ping") or {}).get("ts")) if (load.get("last_ping") or {}).get("ts") else None
    if not prev or ts >= prev:
        await db.loads.update_one({"id": load["id"]}, {"$set": {"last_ping": {"lat": body.lat, "lng": body.lng, "ts": iso(ts)}}})
    load = await load_by_driver_token(tok)
    await process_load(load, fleet, trigger="geofence_departure" if event == "departed" else "ping")
    load = await load_by_driver_token(tok)
    return {"event": event, **driver_payload(load, fleet)}


@api.post("/driver/{tok}/stops/{stop_id}/tap/{action}")
async def driver_action(tok: str, stop_id: str, action: str, body: PingIn):
    if action not in ("arrive", "depart"):
        raise HTTPException(status_code=404, detail="Unknown action")
    load = await load_by_driver_token(tok)
    fleet = await db.fleets.find_one({"id": load["fleet_id"]}, {"_id": 0})
    stop = next((s for s in load["stops"] if s["id"] == stop_id), None)
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")
    coords = {"lat": body.lat, "lng": body.lng, "accuracy": body.accuracy}
    dist = haversine_m(body.lat, body.lng, stop["lat"], stop["lng"]) if stop.get("lat") is not None else None
    coords["distance_m"] = round(dist) if dist is not None else None
    ts = now_utc()
    if action == "arrive":
        if stop.get("arrived_at"):
            raise HTTPException(status_code=400, detail="Arrival already recorded")
        await record_arrival(load, stop, ts, "driver_tap", coords, fleet)
    else:
        if not stop.get("arrived_at"):
            raise HTTPException(status_code=400, detail="Tap 'I'm at the dock' first")
        if stop.get("departed_at"):
            raise HTTPException(status_code=400, detail="Departure already recorded")
        await record_departure(load, stop, ts, "driver_tap", coords, fleet)
    await db.pings.insert_one({"load_id": load["id"], "fleet_id": load["fleet_id"], "lat": body.lat, "lng": body.lng,
                               "accuracy": 50 if body.accuracy is None else body.accuracy, "ts": iso(ts), "received_at": iso(now_utc()), "stop_id": stop_id})
    load = await load_by_driver_token(tok)
    await process_load(load, fleet, trigger=f"driver_{action}")
    return driver_payload(await load_by_driver_token(tok), fleet)


@api.post("/driver/{tok}/stops/{stop_id}/bol")
async def driver_bol(tok: str, stop_id: str, file: UploadFile = File(...)):
    load = await load_by_driver_token(tok)
    fleet = await db.fleets.find_one({"id": load["fleet_id"]}, {"_id": 0})
    stop = next((s for s in load["stops"] if s["id"] == stop_id), None)
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")
    data = await file.read()
    ct = file.content_type or ""
    if not ct.startswith("image/"):
        # Native uploads may arrive as application/octet-stream; infer from the filename.
        ct = mimetypes.guess_type(file.filename or "")[0] or ct
    if not ct.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload a photo")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Photo is larger than 12 MB")
    ext = {"image/png": "png", "image/webp": "webp", "image/heic": "heic"}.get(ct, "jpg")
    rec = await store_file(load["fleet_id"], data, ct, ext, "bol", {"load_id": load["id"], "stop_id": stop_id})
    entry = {"file_id": rec["id"], "sha256": rec["sha256"], "uploaded_at": rec["created_at"], "content_type": ct}
    stop.setdefault("bol", []).append(entry)
    stop["events"].append({"type": "bol_uploaded", "at": rec["created_at"]})
    await save_stop(load["id"], stop)
    await process_load(await load_by_driver_token(tok), fleet, trigger="document_upload")
    return driver_payload(await load_by_driver_token(tok), fleet)


# ---------------------------------------------------------------- invoices

async def invoice_context(inv: dict):
    load = await db.loads.find_one({"id": inv["load_id"]}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Load missing")
    fleet = await db.fleets.find_one({"id": inv["fleet_id"]}, {"_id": 0})
    stops = stops_with_billing(load, fleet)
    stop = next((s for s in stops if s["id"] == inv["stop_id"]), None)
    notices = await db.notices.find({"load_id": load["id"], "stop_id": inv["stop_id"]}, {"_id": 0}).sort("sent_at", 1).to_list(50)
    pb = await playback_data(load, inv["stop_id"])
    return fleet, load, stop, notices, pb


def evidence_url(fleet, inv):
    return f"{fleet.get('app_url') or ''}/e/{inv['public_token']}"


async def get_invoice(inv_id: str, fleet_id: str) -> dict:
    inv = await db.invoices.find_one({"id": inv_id, "fleet_id": fleet_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


def reminder_plan(inv, terms: dict | None = None):
    """Reminders follow the confirmed payment terms. Unknown terms -> polite follow-ups, never 'overdue'."""
    sent = parse(inv.get("sent_at"))
    done = {r["day"] for r in inv.get("reminders", [])}
    t = terms if terms is not None else (inv.get("payment_terms") or {})
    days = t.get("payment_terms_days")
    if days and t.get("payment_terms_start") in ("invoice_submission", "receipt_of_complete_docs"):
        n = int(days)
        sched = [(n - 3, "due_soon", "Upcoming due date"), (n + 1, "past_due", "Past due"), (n + 7, "past_due", "Past due"),
                 (n + 21, "final", "Final notice")]
        est = t.get("payment_terms_start") == "receipt_of_complete_docs"
    elif inv.get("payment_terms") is None and terms is None:
        sched = [(3, "legacy", "Reminder"), (7, "legacy", "Reminder"), (14, "legacy", "Reminder"), (30, "legacy", "Reminder")]
        est = False
    else:
        sched = [(7, "follow_up", "Follow-up"), (14, "follow_up", "Follow-up"), (30, "follow_up", "Follow-up")]
        est = False
    return [{"day": d, "kind": k, "label": lbl + (" (estimated - receipt not confirmed)" if est and k != "due_soon" else ""),
             "due_at": iso(sent + timedelta(days=d)) if sent else None, "sent": d in done,
             "sent_at": next((r["sent_at"] for r in inv.get("reminders", []) if r["day"] == d), None)}
            for d, k, lbl in sched if d > 0]


@api.get("/invoices")
async def list_invoices(m: dict = Depends(fleet_member)):
    invs = await db.invoices.find({"fleet_id": m["fleet_id"]}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    pkt = {x["id"] for x in await db.loads.find({"fleet_id": m["fleet_id"], "billing_setup": {"$exists": True}}, {"_id": 0, "id": 1}).to_list(5000)}
    return [{**i, "packet_billed": i["load_id"] in pkt, "reminder_plan": reminder_plan(i), "evidence_url": evidence_url(m["fleet"], i)} for i in invs if i["status"] != "void"]


@api.get("/invoices/{inv_id}")
async def invoice_detail(inv_id: str, m: dict = Depends(fleet_member)):
    inv = await get_invoice(inv_id, m["fleet_id"])
    fleet, load, stop, notices, pb = await invoice_context(inv)
    return {**inv, "reminder_plan": reminder_plan(inv), "evidence_url": evidence_url(fleet, inv),
            "stop": stop, "notices": notices, "load": {k: load.get(k) for k in ("id", "load_number", "broker", "detention")},
            "verification": verify(inv, load, stop, notices, pb)}


def verify(inv, load, stop, notices, pb):
    if not inv.get("fingerprint"):
        return {"state": "unsealed"}
    if inv.get("snapshot_packet_id"):
        ok = core.canonical_hash(inv.get("sealed_evidence") or {}) == inv["fingerprint"]
        return {"state": "verified" if ok else "changed", "fingerprint": inv["fingerprint"], "sealed_at": inv.get("sealed_at"),
                "basis": "issued_snapshot", "packet_id": inv["snapshot_packet_id"]}
    if inv.get("sealed_at"):  # evidence that arrives after sealing is a supplement, not a change to the sealed record
        pb = {**pb, "pings": [p for p in pb["pings"] if not p.get("received_at") or p["received_at"] <= inv["sealed_at"]]}
    current = core.evidence_record(inv, load, stop, stop["billing"], notices, pb["pings"])
    fp = core.canonical_hash(current)
    if fp == inv["fingerprint"]:
        return {"state": "verified", "fingerprint": fp, "sealed_at": inv.get("sealed_at")}
    sealed = inv.get("sealed_evidence") or {}
    changed = sorted([k for k in set(sealed) | set(current) if sealed.get(k) != current.get(k)])
    return {"state": "changed", "fingerprint": inv["fingerprint"], "current": fp, "changed_fields": changed,
            "sealed_at": inv.get("sealed_at")}


@api.post("/invoices/{inv_id}/send")
async def send_invoice(inv_id: str, m: dict = Depends(fleet_member)):
    inv = await get_invoice(inv_id, m["fleet_id"])
    if inv["status"] not in ("ready", "sent"):
        raise HTTPException(status_code=400, detail=f"Invoice is {inv['status']}")
    fleet, load, stop, notices, pb = await invoice_context(inv)
    if load.get("billing_setup"):
        dst = finalize.destination(load)
        if inv.get("packet_id") or finalize.transport_state(load)["state"] == "completed":
            raise HTTPException(status_code=400, detail="This load is billed with a billing packet. Use 'Completion & billing' on the load page "
                                                        "so documents, approvals, the payor's AP address and review rules are applied.")
        # early (e.g. pickup) submission before the load completes: only to the confirmed AP email destination
        if not (load["billing_setup"].get("confirmed_at") and dst["channel"] == "email" and dst["recipient"]):
            raise HTTPException(status_code=400, detail="Confirm an email billing destination for this load before sending an early invoice")
    to = (finalize.destination(load).get("recipient") or (load.get("broker") or {}).get("email") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="Add the broker's email on the load first")
    if not fleet.get("app_url"):
        raise HTTPException(status_code=400, detail="App address unknown; reload and retry")
    upd = {}
    if inv["status"] == "ready":
        amount = stop["billing"]["amount"]
        inv["amount"] = amount
        inv["billable_label"] = f"{stop['billing']['billed_minutes'] / 60:.2f} h"
        ev = core.evidence_record(inv, load, stop, stop["billing"], notices, pb["pings"])
        upd = {"amount": amount, "billable_label": inv["billable_label"], "sealed_evidence": ev,
               "fingerprint": core.canonical_hash(ev), "sealed_at": iso(now_utc()), "broker_email": to}
    dest = finalize.destination(load)
    if dest.get("recipient"):
        to = dest["recipient"]
    subj, html = templates.invoice_email(fleet["name"], inv, load, stop, evidence_url(fleet, inv))
    simulated = finalize.SUBMISSION_MODE != "live" or fleet.get("is_demo")
    try:
        if not simulated:
            await send_email(to=to, subject=subj, html=html, reply_to=fleet.get("reply_to_email"))
    except EmailError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if simulated:
        upd["submission_simulated"] = True
    now = iso(now_utc())
    upd.update({"status": "sent", "last_emailed_at": now})
    if not inv.get("sent_at"):
        upd["sent_at"] = now
    await db.invoices.update_one({"id": inv_id}, {"$set": upd, "$push": {"history": {
        "at": now, "action": "emailed", "to": to, "note": "SIMULATED - no email sent" if simulated else None}}})
    await finalize.finalize_load(load["id"], "invoice_sent", m["user_id"])
    return await invoice_detail(inv_id, m)


class InvoiceAction(BaseModel):
    action: str
    method: Optional[str] = None
    note: Optional[str] = None


@api.post("/invoices/{inv_id}/status")
async def invoice_status(inv_id: str, body: InvoiceAction, m: dict = Depends(fleet_member)):
    inv = await get_invoice(inv_id, m["fleet_id"])
    now = iso(now_utc())
    a = body.action
    upd = {}
    if a == "pause":
        upd = {"reminders_paused": True}
    elif a == "resume":
        upd = {"reminders_paused": False}
    elif a == "mark_paid":
        if body.method not in ("check", "ach", "card", "factoring", "other"):
            raise HTTPException(status_code=400, detail="Pick how it was paid")
        upd = {"status": "paid", "paid_at": now, "paid_method": body.method, "paid_amount": inv["amount"]}
    elif a == "dispute":
        upd = {"status": "disputed", "reminders_paused": True}
    elif a == "write_off":
        upd = {"status": "written_off", "reminders_paused": True}
    elif a == "reopen":
        upd = {"status": "sent" if inv.get("sent_at") else "ready", "reminders_paused": False}
    else:
        raise HTTPException(status_code=400, detail="Unknown action")
    await db.invoices.update_one({"id": inv_id}, {"$set": upd, "$push": {"history": {"at": now, "action": a,
                                                                                   "note": body.note, "by": m["user_id"]}}})
    return await invoice_detail(inv_id, m)


async def packet_pdf(inv: dict) -> bytes:
    pid = inv.get("snapshot_packet_id") or inv.get("packet_id")
    p = await db.packets.find_one({"id": pid}, {"_id": 0}) if pid else None
    if p and p.get("pdf_file_id"):
        rec = await db.files.find_one({"id": p["pdf_file_id"]}, {"_id": 0})
        data, _ = await asyncio.to_thread(get_object, rec["storage_path"])
        return data
    fleet, load, stop, notices, pb = await invoice_context(inv)
    bols = []
    for b in stop.get("bol", [])[:4]:
        rec = await db.files.find_one({"id": b["file_id"]}, {"_id": 0})
        if rec:
            try:
                data, _ = await asyncio.to_thread(get_object, rec["storage_path"])
                bols.append((data, b))
            except Exception as e:  # noqa
                logger.warning(f"bol fetch failed {e}")
    return build_packet(fleet=fleet, load=load, stop=stop, invoice=inv, billing=stop["billing"], notices=notices,
                        pings=pb["pings"], bol_images=bols, evidence_url=evidence_url(fleet, inv),
                        fingerprint=inv.get("fingerprint"), fmt_time=lambda s: fmt_local(fleet, s))


@api.get("/invoices/{inv_id}/pdf")
async def invoice_pdf(inv_id: str, m: dict = Depends(fleet_member)):
    inv = await get_invoice(inv_id, m["fleet_id"])
    pdf = await packet_pdf(inv)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{inv["number"]}.pdf"'})


# ---------------------------------------------------------------- public evidence + payments

async def invoice_by_token(tok: str) -> dict:
    inv = await db.invoices.find_one({"public_token": tok}, {"_id": 0})
    if not inv or inv["status"] in ("ready", "void"):
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@api.get("/public/evidence/{tok}")
async def public_evidence(tok: str):
    inv = await invoice_by_token(tok)
    fleet, load, stop, notices, pb = await invoice_context(inv)
    if not inv.get("viewed_at"):
        await db.invoices.update_one({"id": inv["id"]}, {"$set": {"viewed_at": iso(now_utc())}})
    return {
        "invoice": {k: inv.get(k) for k in ("number", "amount", "status", "sent_at", "paid_at", "billable_label",
                                            "fingerprint", "sealed_at", "load_number", "paid_method")},
        "carrier": {"name": fleet.get("name"), "reply_to_email": fleet.get("reply_to_email"), "timezone": fleet.get("timezone")},
        "broker": load.get("broker"),
        "terms": load.get("detention"),
        "stop": {k: stop.get(k) for k in ("facility_name", "address", "lat", "lng", "radius_m", "arrived_at", "departed_at",
                                          "arrived_source", "departed_source", "arrived_coords", "departed_coords", "billing",
                                          "type", "appointment")}
                | {"bol": [{"file_id": b["file_id"], "sha256": b["sha256"], "uploaded_at": b["uploaded_at"]} for b in stop.get("bol", [])]},
        "notices": [{k: n.get(k) for k in ("sent_at", "to", "kind", "on_time")} for n in notices],
        "playback": pb,
        "verification": verify(inv, load, stop, notices, pb),
    }


@api.get("/public/evidence/{tok}/pdf")
async def public_pdf(tok: str):
    inv = await invoice_by_token(tok)
    pdf = await packet_pdf(inv)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{inv["number"]}-detention-packet.pdf"'})


@api.get("/public/evidence/{tok}/files/{file_id}")
async def public_file(tok: str, file_id: str):
    inv = await invoice_by_token(tok)
    load = await db.loads.find_one({"id": inv["load_id"]}, {"_id": 0})
    stop = next((s for s in load["stops"] if s["id"] == inv["stop_id"]), {})
    if file_id not in {b["file_id"] for b in stop.get("bol", [])}:
        raise HTTPException(status_code=404, detail="File not found")
    return await file_response(file_id, inv["fleet_id"])


class CheckoutIn(BaseModel):
    origin_url: str


def _create_session(kwargs):
    try:
        s = stripe.checkout.Session.create(**kwargs, automatic_tax={"enabled": True}, billing_address_collection="required")
        return s, "calc_only"
    except stripe.error.InvalidRequestError as e:
        logger.info(f"automatic tax unavailable, falling back: {e.user_message}")
        return stripe.checkout.Session.create(**kwargs), "none"


@api.post("/public/evidence/{tok}/checkout")
async def checkout(tok: str, body: CheckoutIn):
    inv = await invoice_by_token(tok)
    if inv["status"] == "paid":
        raise HTTPException(status_code=400, detail="This invoice is already paid")
    if inv["status"] not in ("sent", "disputed"):
        raise HTTPException(status_code=400, detail="This invoice is not payable")
    origin = _valid_origin(body.origin_url) or body.origin_url.rstrip("/")
    cents = int(round(float(inv["amount"]) * 100))
    if cents < 50:
        raise HTTPException(status_code=400, detail="Amount too small for card payment")
    fleet = await db.fleets.find_one({"id": inv["fleet_id"]}, {"_id": 0})
    kwargs = dict(
        mode="payment",
        payment_method_types=["card"],
        line_items=[{"price_data": {"currency": "usd", "unit_amount": cents,
                                    "product_data": {"name": f"Detention invoice {inv['number']} - load {inv.get('load_number')}",
                                                     "description": f"{fleet.get('name')} | {inv.get('facility_name')}"}},
                     "quantity": 1}],
        success_url=f"{origin}/payment/success?session_id={{CHECKOUT_SESSION_ID}}&t={tok}",
        cancel_url=f"{origin}/e/{tok}?payment=cancelled",
        metadata={"invoice_id": inv["id"], "invoice_number": inv["number"]},
        customer_email=inv.get("broker_email") or None,
    )
    session, tax_mode = await asyncio.to_thread(_create_session, kwargs)
    await db.payment_transactions.insert_one({
        "session_id": session.id, "invoice_id": inv["id"], "fleet_id": inv["fleet_id"], "amount": float(inv["amount"]),
        "currency": "usd", "status": "initiated", "payment_status": "pending", "tax_mode": tax_mode,
        "created_at": iso(now_utc()), "updated_at": iso(now_utc())})
    return {"checkout_url": session.url, "session_id": session.id}


async def mark_session_paid(session_id: str, payment_intent=None):
    r = await db.payment_transactions.find_one_and_update(
        {"session_id": session_id, "payment_status": {"$ne": "paid"}},
        {"$set": {"status": "completed", "payment_status": "paid", "stripe_payment_intent_id": payment_intent,
                  "updated_at": iso(now_utc())}})
    if r:
        now = iso(now_utc())
        await db.invoices.update_one({"id": r["invoice_id"], "status": {"$ne": "paid"}},
                                     {"$set": {"status": "paid", "paid_at": now, "paid_method": "card",
                                               "paid_amount": r["amount"], "reminders_paused": True},
                                      "$push": {"history": {"at": now, "action": "paid_by_card", "session_id": session_id}}})


@api.get("/payments/status/{session_id}")
async def payment_status(session_id: str):
    rec = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if rec.get("payment_status") != "paid":
        try:
            s = await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id)
            if s.payment_status == "paid":
                await mark_session_paid(session_id, s.payment_intent)
            elif s.status == "expired":
                await db.payment_transactions.update_one({"session_id": session_id},
                                                         {"$set": {"status": "expired", "payment_status": "expired"}})
            rec = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        except stripe.error.StripeError:
            pass
    return {"session_id": rec["session_id"], "status": rec["status"], "payment_status": rec["payment_status"]}


@api.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except (stripe.error.SignatureVerificationError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid signature")
    obj, t = event["data"]["object"], event["type"]
    if t in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        if obj.get("payment_status") == "paid" or t.endswith("succeeded"):
            await mark_session_paid(obj["id"], obj.get("payment_intent"))
    elif t == "checkout.session.expired":
        await db.payment_transactions.update_one({"session_id": obj["id"]}, {"$set": {"status": "expired", "payment_status": "expired"}})
    elif t == "checkout.session.async_payment_failed":
        await db.payment_transactions.update_one({"session_id": obj["id"]}, {"$set": {"status": "failed", "payment_status": "failed"}})
    return {"status": "ok"}


# ---------------------------------------------------------------- dashboard / scorecard / summary

def week_bounds(fleet, which="last"):
    tz = tz_of(fleet)
    local = now_utc().astimezone(tz)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    if which == "last":
        return (monday - timedelta(days=7)).astimezone(timezone.utc), monday.astimezone(timezone.utc)
    return monday.astimezone(timezone.utc), now_utc()


async def period_summary(fleet, start: datetime, end: datetime):
    loads = await db.loads.find({"fleet_id": fleet["id"], "stops": {"$elemMatch": {"departed_at": {"$ne": None}}}},
                                {"_id": 0}).to_list(2000)
    hours, billable, detained_loads = 0.0, 0.0, set()
    for ld in loads:
        for s in stops_with_billing(ld, fleet):
            dep = parse(s.get("departed_at"))
            if not s.get("arrived_at") or not dep or not (start <= dep < end):
                continue
            b = s["billing"]
            if b["billable_minutes"] > 0:
                hours += b["billable_minutes"] / 60
                billable += b["amount"]
                detained_loads.add(ld["id"])
    ready = await db.invoices.count_documents({"fleet_id": fleet["id"], "status": "ready"})
    return {"detained_hours": round(hours, 1), "detained_loads": len(detained_loads), "billable": round(billable, 2),
            "ready_invoices": ready}


def headline(s, label="Last week"):
    if s["detained_loads"] == 0:
        return f"{label} you had no billable detention. {s['ready_invoices']} invoice{'s' if s['ready_invoices'] != 1 else ''} ready to send."
    return (f"{label} you were detained {s['detained_hours']:g} hours across {s['detained_loads']} load"
            f"{'s' if s['detained_loads'] != 1 else ''}. ${s['billable']:,.0f} is billable under your rate cons. "
            f"{s['ready_invoices']} invoice{'s are' if s['ready_invoices'] != 1 else ' is'} ready to send.")


@api.get("/dashboard")
async def dashboard(m: dict = Depends(fleet_member)):
    fleet = m["fleet"]
    active = await db.loads.find({"fleet_id": fleet["id"], "stops": {"$elemMatch": {"arrived_at": {"$ne": None}, "departed_at": None}}},
                                 {"_id": 0}).to_list(200)
    for ld in active:
        await process_load(ld, fleet)
    ls, le = week_bounds(fleet, "last")
    ts, te = week_bounds(fleet, "this")
    last, this = await period_summary(fleet, ls, le), await period_summary(fleet, ts, te)
    loads = await db.loads.find({"fleet_id": fleet["id"]}, {"_id": 0}).sort("created_at", -1).to_list(300)
    views = [await load_view(ld, fleet) for ld in loads]
    meters, trucks, attention = [], [], []
    for v in views:
        for s in v["stops"]:
            if s.get("arrived_at") and not s.get("departed_at"):
                meters.append({"load_id": v["id"], "load_number": v["load_number"], "stop_id": s["id"],
                               "facility_name": s.get("facility_name"), "arrived_at": s["arrived_at"],
                               "billing": s["billing"], "notice": s["notice"], "detention": v["detention"],
                               "broker_name": (v.get("broker") or {}).get("name"), "driver": v.get("driver")})
            if s["notice"].get("status") == "awaiting_approval":
                attention.append({"kind": "notice_approval", "load_id": v["id"], "stop_id": s["id"],
                                  "load_number": v["load_number"], "facility_name": s.get("facility_name"),
                                  "due_at": s["notice"].get("due_at")})
            if s["notice"].get("status") in ("failed", "no_email"):
                attention.append({"kind": "notice_failed", "load_id": v["id"], "stop_id": s["id"],
                                  "load_number": v["load_number"], "facility_name": s.get("facility_name"),
                                  "detail": s["notice"].get("error") or "No broker email"})
        if v.get("last_ping") and v["status"] in ("on_site", "in_transit", "dispatched"):
            trucks.append({"load_id": v["id"], "load_number": v["load_number"], "status": v["status"], **v["last_ping"],
                           "driver": (v.get("driver") or {}).get("name")})
    invs = await db.invoices.find({"fleet_id": fleet["id"]}, {"_id": 0}).to_list(2000)
    for i in invs:
        if i["status"] == "ready":
            attention.append({"kind": "invoice_ready", "invoice_id": i["id"], "load_id": i["load_id"],
                              "load_number": i.get("load_number"), "facility_name": i.get("facility_name"), "amount": i["amount"]})
    outstanding = round(sum(i["amount"] for i in invs if i["status"] in ("sent", "issued")), 2)
    recovered = round(sum(i.get("paid_amount") or i["amount"] for i in invs if i["status"] == "paid"), 2)
    facilities = await db.facilities.find({"fleet_id": fleet["id"], "lat": {"$ne": None}}, {"_id": 0}).to_list(500)
    return {"headline": headline(last), "last_week": last, "this_week": this, "this_week_headline": headline(this, "This week"),
            "meters": meters, "trucks": trucks, "attention": attention, "facilities": facilities,
            "kpis": {"outstanding": outstanding, "recovered": recovered, "active_stops": len(meters),
                     "ready_invoices": sum(1 for i in invs if i["status"] == "ready"),
                     "loads": len(views)},
            "recent_loads": views[:8]}


@api.get("/scorecard")
async def scorecard(m: dict = Depends(fleet_member)):
    fleet = m["fleet"]
    loads = await db.loads.find({"fleet_id": fleet["id"]}, {"_id": 0}).to_list(3000)
    invs = await db.invoices.find({"fleet_id": fleet["id"]}, {"_id": 0}).to_list(5000)
    inv_by_stop = {i["stop_id"]: i for i in invs}
    fac, brk = {}, {}

    def bucket(d, key, name):
        return d.setdefault(key, {"id": key, "name": name, "stops": 0, "detained": 0, "dwell_total": 0.0,
                                  "billed": 0.0, "paid": 0.0, "invoices": 0, "paid_count": 0, "days_to_pay": [],
                                  "excess_total": 0.0, "disputed": 0})

    for ld in loads:
        bname = (ld.get("broker") or {}).get("name") or "Unknown broker"
        bkey = ld.get("broker_id") or bname
        for s in stops_with_billing(ld):
            if not (s.get("arrived_at") and s.get("departed_at")):
                continue
            b = s["billing"]
            for d, key, name in ((fac, s.get("facility_id") or s.get("facility_name"), s.get("facility_name") or "Facility"),
                                 (brk, bkey, bname)):
                x = bucket(d, key, name)
                x["stops"] += 1
                x["dwell_total"] += b["dwell_minutes"]
                if b["billable_minutes"] > 0:
                    x["detained"] += 1
                    x["excess_total"] += b["billable_minutes"]
                inv = inv_by_stop.get(s["id"])
                if inv and inv["status"] in ("sent", "paid", "disputed", "written_off"):
                    x["invoices"] += 1
                    x["billed"] += inv["amount"]
                    if inv["status"] == "paid":
                        x["paid_count"] += 1
                        x["paid"] += inv.get("paid_amount") or inv["amount"]
                        if inv.get("sent_at") and inv.get("paid_at"):
                            x["days_to_pay"].append((parse(inv["paid_at"]) - parse(inv["sent_at"])).total_seconds() / 86400)
                    if inv["status"] == "disputed":
                        x["disputed"] += 1

    def finish(x, kind):
        det_rate = x["detained"] / x["stops"] if x["stops"] else 0
        pay_rate = x["paid_count"] / x["invoices"] if x["invoices"] else None
        dtp = sum(x["days_to_pay"]) / len(x["days_to_pay"]) if x["days_to_pay"] else None
        avg_dwell = x["dwell_total"] / x["stops"] / 60 if x["stops"] else 0
        if kind == "facility":
            score = 100 - det_rate * 70 - min(30, (x["excess_total"] / max(1, x["stops"])) / 60 * 10)
        else:
            score = 100 - det_rate * 35
            if pay_rate is not None:
                score -= (1 - pay_rate) * 45
            if dtp is not None:
                score -= min(20, max(0, dtp - 7) * 1.0)
        score = max(0, min(100, score))
        return {"id": x["id"], "name": x["name"], "stops": x["stops"], "detained": x["detained"],
                "detention_rate": round(det_rate, 3), "avg_dwell_hours": round(avg_dwell, 2),
                "billed": round(x["billed"], 2), "paid": round(x["paid"], 2), "invoices": x["invoices"],
                "pay_rate": round(pay_rate, 3) if pay_rate is not None else None,
                "days_to_pay": round(dtp, 1) if dtp is not None else None, "disputed": x["disputed"],
                "score": round(score), "grade": core.grade_from_score(score),
                "advice": ("Refuse or price up" if score < 40 else "Price up" if score < 55 else "Watch" if score < 70 else "Good to book")}

    return {"facilities": sorted([finish(x, "facility") for x in fac.values()], key=lambda r: r["score"]),
            "brokers": sorted([finish(x, "broker") for x in brk.values()], key=lambda r: r["score"])}


# ---------------------------------------------------------------- reminders & weekly summary & cron

async def run_reminders(fleet):
    now = now_utc()
    invs = await db.invoices.find({"fleet_id": fleet["id"], "status": "sent", "reminders_paused": {"$ne": True}}, {"_id": 0}).to_list(2000)
    for inv in invs:
        sent = parse(inv.get("sent_at"))
        if not sent:
            continue
        plan = reminder_plan(inv)
        due = [r for r in plan if not r["sent"] and now >= sent + timedelta(days=r["day"])]
        if not due:
            continue
        r = due[-1]
        try:
            f, load, stop, notices, pb = await invoice_context(inv)
            if r["kind"] == "legacy":
                subj, html = templates.invoice_email(fleet["name"], inv, load, stop, evidence_url(fleet, inv),
                                                     tone_idx=core.REMINDER_DAYS.index(r["day"]) if r["day"] in core.REMINDER_DAYS else 0)
            else:
                subj, html = templates.payment_reminder_email(fleet["name"], inv, r["kind"], r["label"], evidence_url(fleet, inv))
            simulated = inv.get("submission_simulated") or fleet.get("is_demo") or finalize.SUBMISSION_MODE != "live"
            if not simulated:
                await send_email(to=inv["broker_email"], subject=subj, html=html, reply_to=fleet.get("reply_to_email"))
            entries = [{"day": d["day"], "sent_at": iso(now), "skipped": d["day"] != r["day"], "kind": d["kind"],
                        "simulated": bool(simulated)} for d in due]
            await db.invoices.update_one({"id": inv["id"]}, {"$push": {"reminders": {"$each": entries}}})
        except Exception as e:  # noqa
            logger.warning(f"reminder failed for {inv['id']}: {e}")


async def run_weekly(fleet, force=False):
    tz = tz_of(fleet)
    local = now_utc().astimezone(tz)
    week_key = local.strftime("%G-W%V")
    if not force and not (local.weekday() == 0 and local.hour >= 7):
        return False
    if not force and fleet.get("weekly_sent_key") == week_key:
        return False
    ls, le = week_bounds(fleet, "last")
    s = await period_summary(fleet, ls, le)
    owner = await db.users.find_one({"user_id": fleet["owner_user_id"]}, {"_id": 0})
    to = (owner or {}).get("email") or fleet.get("reply_to_email")
    if not to or not fleet.get("app_url"):
        return False
    outstanding = sum(i["amount"] for i in await db.invoices.find({"fleet_id": fleet["id"], "status": {"$in": ["sent", "issued"]}}, {"_id": 0}).to_list(2000))
    subj, html = templates.weekly_email(fleet["name"], headline(s), fleet["app_url"] + "/app", [
        ("Hours detained", f"{s['detained_hours']:g}"), ("Loads detained", s["detained_loads"]),
        ("Billable under rate cons", f"${s['billable']:,.2f}"), ("Invoices ready to send", s["ready_invoices"]),
        ("Outstanding with brokers", f"${outstanding:,.2f}")])
    try:
        await send_email(to=to, subject=subj, html=html)
    except EmailError as e:
        logger.warning(f"weekly email failed: {e}")
        return False
    await db.fleets.update_one({"id": fleet["id"]}, {"$set": {"weekly_sent_key": week_key, "weekly_sent_at": iso(now_utc())}})
    return True


async def run_tick():
    fleets = await db.fleets.find({}, {"_id": 0}).to_list(5000)
    fmap = {f["id"]: f for f in fleets}
    active = await db.loads.find({"stops": {"$elemMatch": {"arrived_at": {"$ne": None}}}}, {"_id": 0}).to_list(5000)
    for ld in active:
        f = fmap.get(ld["fleet_id"])
        if f:
            try:
                await process_load(ld, f, trigger="cron_recovery")
            except Exception as e:  # noqa
                logger.warning(f"tick load {ld['id']} failed: {e}")
    await finalize.run_outbox()
    for f in fleets:
        await run_reminders(f)
        await run_weekly(f)
    await run_schedules(fmap)


@api.post("/cron/tick")
async def cron_tick(request: Request, bg: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    secret = os.environ.get("WEBHOOK_CRON_SECRET", "")
    auth = request.headers.get("authorization", "")
    if not secret or not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
    run_id = request.headers.get("x-webhook-id")
    try:
        body = await request.json()
        run_id = run_id or (body or {}).get("run_id")
    except Exception:  # noqa
        pass
    if run_id:
        try:
            await db.cron_runs.insert_one({"_id": run_id, "at": iso(now_utc())})
        except Exception:  # noqa  duplicate delivery
            return {"status": "duplicate"}
    bg.add_task(run_tick)
    return {"status": "accepted"}


@api.post("/summary/send-now")
async def summary_now(m: dict = Depends(fleet_member)):
    require_owner(m)
    ok = await run_weekly(m["fleet"], force=True)
    if not ok:
        raise HTTPException(status_code=502, detail="Could not send the summary email")
    return {"ok": True}


@api.post("/demo/reseed")
async def demo_reseed(request: Request):
    """Rebuild the guided demo fleet on demand (same bearer secret as the cron)."""
    secret = os.environ.get("WEBHOOK_CRON_SECRET", "")
    auth = request.headers.get("authorization", "")
    if not secret or not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await demo.seed_demo(db)


# ---------------------------------------------------------------- completion, billing packet & submission

async def _member_name(m):
    return (m.get("name") or m.get("email") or m["user_id"])


async def billing_view(load: dict, fleet: dict) -> dict:
    comp = load.get("completion") or {}
    billing = compute_load_billing(load, tz=tz_of(fleet))
    trans = finalize.transport_state(load)
    packets = await db.packets.find({"load_id": load["id"]}, {"_id": 0, "snapshot": 0}).sort("version", -1).to_list(20)
    latest = await db.packets.find_one({"load_id": load["id"]}, {"_id": 0}, sort=[("version", -1)])
    issued = await db.packets.find_one({"load_id": load["id"], "status": "issued"}, {"_id": 0}, sort=[("version", -1)])
    jobs = await db.outbox.find({"load_id": load["id"]}, {"_id": 0, "html": 0}).sort("created_at", -1).to_list(20)
    invs = await db.invoices.find({"load_id": load["id"]}, {"_id": 0, "sealed_evidence": 0}).to_list(50)
    return {
        "completion": comp, "transport": trans, "billing": billing, "destination": finalize.destination(load),
        "setup": load.get("billing_setup") or {"mode": "review"}, "terms": load.get("billing_terms") or {},
        "term_sources": load.get("term_sources") or {}, "refs": load.get("refs") or {},
        "obligations": finalize.obligations(load, billing, trans, fleet),
        "documents": finalize.documents_state(load), "required_documents": finalize.required_documents(load),
        "approvals": load.get("approvals") or [], "conflicts": load.get("conflicts") or [],
        "packets": packets, "issued_verification": finalize.verify_packet(issued) if issued else {"state": "none"},
        "latest_snapshot": (latest or {}).get("snapshot"),
        "source_comparison": await finalize.source_comparison(issued, load, fleet) if issued else {"state": "n/a"},
        "outbox": jobs,
        "invoices": [{**i, **finalize.invoice_balance(i), "reminder_plan": reminder_plan(i)} for i in invs],
        "submission_mode": finalize.SUBMISSION_MODE, "attachments_supported": finalize.EMAIL_ATTACHMENTS_SUPPORTED,
        "retention": finalize.RETENTION_POLICY,
    }


@api.get("/loads/{load_id}/billing")
async def load_billing(load_id: str, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    return await billing_view(load, m["fleet"])


async def _rerun(load_id, m, trigger):
    await process_load(await get_load(load_id, m["fleet_id"]), m["fleet"], trigger=trigger, actor=m["user_id"])
    return await billing_view(await get_load(load_id, m["fleet_id"]), m["fleet"])


class SetupIn(BaseModel):
    mode: str = "review"


@api.post("/loads/{load_id}/billing/setup")
async def billing_setup(load_id: str, body: SetupIn, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    if body.mode not in ("auto", "review"):
        raise HTTPException(status_code=400, detail="Mode must be auto or review")
    dest = finalize.destination(load)
    await db.loads.update_one({"id": load_id}, {"$set": {"billing_setup": {
        "mode": body.mode, "confirmed_at": iso(now_utc()), "confirmed_by": m["user_id"], "destination": dest}}})
    return await _rerun(load_id, m, "billing_setup")


@api.post("/loads/{load_id}/billing/submit")
async def billing_submit(load_id: str, m: dict = Depends(fleet_member)):
    """Dispatcher approval (review mode) or a revision issue. Same service as automatic submission."""
    await process_load(await get_load(load_id, m["fleet_id"]), m["fleet"], trigger="dispatcher_review", actor=m["user_id"])
    load = await get_load(load_id, m["fleet_id"])
    comp = load.get("completion") or {}
    if comp.get("blockers"):
        raise HTTPException(status_code=400, detail="Resolve the listed items first: " + "; ".join(b["message"] for b in comp["blockers"][:3]))
    p = await db.packets.find_one({"load_id": load_id}, {"_id": 0}, sort=[("version", -1)])
    if not p:
        raise HTTPException(status_code=400, detail="No billing packet yet (the load is not completed or has no detention)")
    if p["status"] != "draft" and (comp.get("submission") or {}).get("state") in ("accepted", "queued", "sending", "uncertain"):
        raise HTTPException(status_code=400, detail="This packet was already submitted")
    await finalize.submit_packet(load, m["fleet"], p, m["user_id"])
    return await billing_view(await get_load(load_id, m["fleet_id"]), m["fleet"])


class RefIn(BaseModel):
    reference: str = ""
    note: str = ""


@api.post("/loads/{load_id}/billing/portal-submitted")
async def billing_portal_done(load_id: str, body: RefIn, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    sub = (load.get("completion") or {}).get("submission") or {}
    if sub.get("state") not in ("awaiting_portal", "awaiting_manual"):
        raise HTTPException(status_code=400, detail="This load is not waiting for a portal/manual submission")
    if not body.reference.strip():
        raise HTTPException(status_code=400, detail="Enter the portal confirmation or reference number")
    p = await db.packets.find_one({"id": sub["packet_id"]}, {"_id": 0})
    await finalize.mark_portal_submitted(load, p, body.reference.strip(), m["user_id"])
    return await billing_view(await get_load(load_id, m["fleet_id"]), m["fleet"])


class ResolveIn(BaseModel):
    action: str
    reference: str = ""


@api.post("/outbox/{job_id}/resolve")
async def outbox_resolve(job_id: str, body: ResolveIn, m: dict = Depends(fleet_member)):
    """Reconcile an uncertain/failed submission: confirm it arrived, retry deliberately, or cancel."""
    j = await db.outbox.find_one({"id": job_id, "fleet_id": m["fleet_id"]}, {"_id": 0})
    if not j:
        raise HTTPException(status_code=404, detail="Submission not found")
    now = iso(now_utc())
    if body.action == "mark_accepted" and j["status"] in ("uncertain", "failed"):
        if not body.reference.strip():
            raise HTTPException(status_code=400, detail="Enter how you confirmed it (e.g. the payor's reply)")
        await finalize._accepted(j, body.reference.strip(), "dispatcher_reconciled", m["user_id"])
    elif body.action == "retry" and j["status"] in ("uncertain", "failed"):
        await db.outbox.update_one({"id": job_id, "status": j["status"]}, {"$set": {"status": "pending", "next_attempt_at": now},
                                   "$push": {"history": {"at": now, "event": "manual_retry", "by": m["user_id"]}}})
        await finalize.run_outbox(limit=5)
    elif body.action == "cancel" and j["status"] in ("uncertain", "failed", "pending"):
        await db.outbox.update_one({"id": job_id}, {"$set": {"status": "failed", "error": "Cancelled by dispatcher"},
                                   "$push": {"history": {"at": now, "event": "cancelled", "by": m["user_id"]}}})
    else:
        raise HTTPException(status_code=400, detail=f"Cannot {body.action} a {j['status']} submission")
    await finalize._sync_submission(j["load_id"])
    return await billing_view(await get_load(j["load_id"], m["fleet_id"]), m["fleet"])


class CompleteIn(BaseModel):
    reason: str
    departed_at: Optional[str] = None
    arrived_at: Optional[str] = None


@api.post("/loads/{load_id}/complete")
async def manual_complete(load_id: str, body: CompleteIn, m: dict = Depends(fleet_member)):
    """GPS-failure fallback: dispatcher records the missing times; actor, time and reason are kept."""
    load = await get_load(load_id, m["fleet_id"])
    if not body.reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required to complete a load manually")
    open_stops = [s for s in sorted(load["stops"], key=lambda x: x["seq"]) if not s.get("departed_at")]
    if not open_stops:
        raise HTTPException(status_code=400, detail="Every stop already has a departure")
    if len(open_stops) > 1 and not all(s.get("arrived_at") for s in open_stops[:-1]):
        raise HTTPException(status_code=400, detail="Earlier stops have no recorded times; set them with 'Adjust times' first")
    for s in open_stops[:-1]:
        if not s.get("arrived_at"):
            raise HTTPException(status_code=400, detail=f"Set the times for {s.get('facility_name')} first")
    last = open_stops[-1]
    a = parse(body.arrived_at) if body.arrived_at else parse(last.get("arrived_at"))
    dep = parse(body.departed_at) if body.departed_at else None
    if not a or not dep:
        raise HTTPException(status_code=400, detail="Enter the arrival and departure time for the final stop")
    if dep <= a or dep > now_utc() + timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="Departure must be after arrival and not in the future")
    note = f"Manual completion: {body.reason.strip()}"
    if not last.get("arrived_at") or body.arrived_at:
        await record_arrival(load, last, a, "dispatcher_edit", None, m["fleet"], note=note)
        load = await get_load(load_id, m["fleet_id"])
        last = next(s for s in load["stops"] if s["id"] == last["id"])
    await record_departure(load, last, dep, "dispatcher_edit", None, m["fleet"], note=note)
    await db.loads.update_one({"id": load_id}, {"$set": {"manual_completion": {
        "by": m["user_id"], "by_name": await _member_name(m), "at": iso(now_utc()), "reason": body.reason.strip()}}})
    return await _rerun(load_id, m, "manual_completion")


DOC_TYPES = ("signed_bol", "pod", "lumper_receipt", "detention_log", "scale_ticket", "other", "bol_photo")


@api.post("/loads/{load_id}/stops/{stop_id}/documents")
async def upload_document(load_id: str, stop_id: str, doc_type: str = "pod", file: UploadFile = File(...),
                          m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    stop = next((s for s in load["stops"] if s["id"] == stop_id), None)
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")
    if doc_type not in DOC_TYPES:
        raise HTTPException(status_code=400, detail="Unknown document type")
    data = await file.read()
    if not data or len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File is empty or larger than 15 MB")
    ct = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    if not (ct.startswith("image/") or ct == "application/pdf"):
        raise HTTPException(status_code=400, detail="Upload a photo or PDF")
    ext = "pdf" if ct == "application/pdf" else {"image/png": "png", "image/webp": "webp"}.get(ct, "jpg")
    rec = await store_file(m["fleet_id"], data, ct, ext, "document", {"load_id": load_id, "stop_id": stop_id, "doc_type": doc_type,
                                                                      "retention": finalize.RETENTION_POLICY})
    stop.setdefault("bol", []).append({"file_id": rec["id"], "sha256": rec["sha256"], "uploaded_at": rec["created_at"],
                                       "content_type": ct, "doc_type": doc_type, "uploaded_by": m["user_id"]})
    stop["events"].append({"type": "document_uploaded", "at": rec["created_at"], "note": doc_type})
    await save_stop(load_id, stop)
    return await _rerun(load_id, m, "document_upload")


@api.post("/loads/{load_id}/stops/{stop_id}/documents/{file_id}/verify-signature")
async def verify_signature(load_id: str, stop_id: str, file_id: str, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    stop = next((s for s in load["stops"] if s["id"] == stop_id), None)
    doc = next((d for d in (stop or {}).get("bol", []) if d["file_id"] == file_id), None)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.update({"signature_verified": True, "signature_verified_by": m["user_id"], "signature_verified_at": iso(now_utc())})
    await save_stop(load_id, stop)
    return await _rerun(load_id, m, "document_review")


class NoticeRecordIn(BaseModel):
    method: str
    at: str
    to: str = ""
    reference: str = ""
    note: str = ""


@api.post("/loads/{load_id}/stops/{stop_id}/notice-record")
async def record_notice(load_id: str, stop_id: str, body: NoticeRecordIn, m: dict = Depends(fleet_member)):
    """Phone/portal notices the contract requires. The real time is recorded; it is judged against the deadline."""
    load = await get_load(load_id, m["fleet_id"])
    stop = next((s for s in load["stops"] if s["id"] == stop_id), None)
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")
    at = parse(body.at)
    if body.method not in ("phone", "portal", "other", "email") or not at or at > now_utc() + timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="Enter the method and the actual time (not in the future)")
    stop.setdefault("notice_records", []).append({"method": body.method, "at": iso(at), "to": body.to, "reference": body.reference,
                                                  "note": body.note, "by": m["user_id"], "recorded_at": iso(now_utc())})
    stop["events"].append({"type": f"notice_{body.method}_recorded", "at": iso(at), "note": f"{body.to} {body.reference}".strip()})
    await save_stop(load_id, stop)
    return await _rerun(load_id, m, "notice_record")


class ApprovalIn(BaseModel):
    stop_id: Optional[str] = None
    method: str
    approver: str
    reference: str = ""
    at: str
    note: str = ""


@api.post("/loads/{load_id}/approvals")
async def record_approval(load_id: str, body: ApprovalIn, m: dict = Depends(fleet_member)):
    await get_load(load_id, m["fleet_id"])
    at = parse(body.at)
    if not body.approver.strip() or not at:
        raise HTTPException(status_code=400, detail="Enter who approved it and when")
    rec = {"id": uid(), "stop_id": body.stop_id, "method": body.method, "approver": body.approver.strip(), "reference": body.reference,
           "at": iso(at), "note": body.note, "recorded_by": m["user_id"], "recorded_at": iso(now_utc())}
    await db.loads.update_one({"id": load_id}, {"$push": {"approvals": rec}})
    return await _rerun(load_id, m, "approval")


@api.post("/loads/{load_id}/approvals/request")
async def request_approval(load_id: str, m: dict = Depends(fleet_member)):
    """Prepare (and, by email, queue) an accessorial approval request even while final billing is blocked."""
    load = await get_load(load_id, m["fleet_id"])
    t = load.get("billing_terms") or {}
    to = (t.get("notice_recipient") or (load.get("broker") or {}).get("email") or "").strip()
    subj, html = templates.approval_request_email(m["fleet"]["name"], load, stops_with_billing(load, m["fleet"]), fmt_local, m["fleet"])
    if (t.get("approval_method") or "email") != "email" or not EMAIL_RE.match(to):
        return {"prepared": True, "sent": False, "subject": subj,
                "detail": "Approval must be requested by " + (t.get("approval_method") or "the agreed method") + "; the text is ready to use."}
    job = await finalize.enqueue("approval_request", load, m["fleet"], None, to, subj, html, {"channel": "email"})
    await finalize.run_outbox(limit=3)
    return {"prepared": True, "sent": True, "job_id": job["id"], "simulated": job.get("simulated")}


@api.post("/loads/{load_id}/flags/{stop_id}/confirm")
async def confirm_flag(load_id: str, stop_id: str, body: RefIn, m: dict = Depends(fleet_member)):
    await get_load(load_id, m["fleet_id"])
    await db.loads.update_one({"id": load_id}, {"$set": {f"confirmed_flags.{stop_id}": {
        "by": m["user_id"], "at": iso(now_utc()), "note": body.note}}})
    return await _rerun(load_id, m, "dispatcher_review")


class ConflictIn(BaseModel):
    field: str
    value: str


@api.post("/loads/{load_id}/conflicts/resolve")
async def resolve_conflict(load_id: str, body: ConflictIn, m: dict = Depends(fleet_member)):
    load = await get_load(load_id, m["fleet_id"])
    cs = load.get("conflicts") or []
    c = next((x for x in cs if x["field"] == body.field), None)
    if not c:
        raise HTTPException(status_code=404, detail="Conflict not found")
    c.update({"resolved": True, "value": body.value, "resolved_by": m["user_id"], "resolved_at": iso(now_utc())})
    sec, key = body.field.split(".", 1) if "." in body.field else ("billing", body.field)
    target = "detention" if sec == "detention" else "billing_terms"
    val = c["ratecon"] if body.value == "ratecon" else c["agreement"] if body.value == "agreement" else body.value
    await db.loads.update_one({"id": load_id}, {"$set": {"conflicts": cs, f"{target}.{key}": val, f"term_sources.{body.field}": "confirmed"}})
    return await _rerun(load_id, m, "conflict_resolved")


@api.post("/loads/{load_id}/agreement")
async def upload_agreement(load_id: str, file: UploadFile = File(...), m: dict = Depends(fleet_member)):
    """Optional broker-carrier agreement / billing instructions. Fills unknown terms; differences become conflicts."""
    load = await get_load(load_id, m["fleet_id"])
    data = await file.read()
    if not data or len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File is empty or larger than 15 MB")
    rec = await store_file(m["fleet_id"], data, "application/pdf", "pdf", "agreement", {"load_id": load_id, "retention": finalize.RETENTION_POLICY})
    tmp = f"/tmp/{rec['id']}.pdf"
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        ex = await extract_ratecon(tmp, "application/pdf", doc_kind="broker-carrier agreement or billing instructions")
    except Exception as e:  # noqa
        raise HTTPException(status_code=502, detail=f"AI could not read this document ({str(e)[:120]})")
    finally:
        os.remove(tmp)
    det, bt, src = dict(load.get("detention") or {}), dict(load.get("billing_terms") or {}), dict(load.get("term_sources") or {})
    conflicts = [c for c in (load.get("conflicts") or []) if c.get("resolved")]
    for sec, cur, new in (("detention", det, ex.get("detention") or {}), ("billing", bt, ex.get("billing") or {})):
        for k, v in new.items():
            if v in (None, "", []) or k in ("clause_text", "notice_rule_text", "stop_terms"):
                continue
            f = f"{sec}.{k}"
            if cur.get(k) in (None, "", []):
                cur[k] = v
                src[f] = "agreement"
            elif str(cur.get(k)).strip().lower() != str(v).strip().lower() and not any(c["field"] == f for c in conflicts):
                conflicts.append({"field": f, "ratecon": cur.get(k), "agreement": v, "resolved": False, "detected_at": iso(now_utc())})
    docs = (load.get("source_documents") or []) + [{"kind": "agreement", "file_id": rec["id"], "version": ex.get("document_version"),
                                                     "uploaded_at": rec["created_at"]}]
    await db.loads.update_one({"id": load_id}, {"$set": {"detention": det, "billing_terms": bt, "term_sources": src, "conflicts": conflicts,
                                                         "source_documents": docs, "agreement_extracted": ex}})
    return await _rerun(load_id, m, "agreement_upload")


@api.get("/packets/{packet_id}/pdf")
async def packet_download(packet_id: str, m: dict = Depends(fleet_member)):
    p = await db.packets.find_one({"id": packet_id, "fleet_id": m["fleet_id"]}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Packet not found")
    rec = await db.files.find_one({"id": p["pdf_file_id"]}, {"_id": 0})
    data, _ = await asyncio.to_thread(get_object, rec["storage_path"])
    name = f"Detention-Billing-Packet-{p['snapshot']['load']['number']}-v{p['version']}{'' if p['status'] == 'issued' else '-DRAFT'}.pdf"
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


@api.get("/public/packets/{tok}/pdf")
async def public_packet(tok: str):
    """Secure link sent to the payor: only issued/superseded packets, never drafts."""
    p = await db.packets.find_one({"public_token": tok, "status": {"$in": ["issued", "superseded"]}}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Packet not found")
    rec = await db.files.find_one({"id": p["pdf_file_id"]}, {"_id": 0})
    data, _ = await asyncio.to_thread(get_object, rec["storage_path"])
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Detention-Billing-Packet-{p["snapshot"]["load"]["number"]}-v{p["version"]}.pdf"'})


@api.post("/invoices/{inv_id}/adjust")
async def adjust_invoice(inv_id: str, body: RefIn, m: dict = Depends(fleet_member)):
    """Versioned correction of a sent/paid invoice: the original is untouched; only the difference is billed or credited."""
    inv = await get_invoice(inv_id, m["fleet_id"])
    adj = inv.get("pending_adjustment")
    if not adj or abs(adj.get("delta") or 0) < 0.01:
        raise HTTPException(status_code=400, detail="No pending correction for this invoice")
    if not body.note.strip():
        raise HTTPException(status_code=400, detail="A reason is required for a correction")
    n = await db.invoices.count_documents({"adjusts_invoice_id": inv_id})
    new = {**{k: inv.get(k) for k in ("fleet_id", "load_id", "stop_id", "load_number", "broker_id", "broker_name", "facility_id",
                                      "facility_name", "stop_type")},
           "id": uid(), "adjusts_invoice_id": inv_id, "number": f"{inv['number']}-A{n + 1}", "amount": round(abs(adj["delta"]), 2),
           "kind": "supplement" if adj["delta"] > 0 else "credit_note",
           "status": "ready" if adj["delta"] > 0 else "credit", "billable_label": inv.get("billable_label"),
           "public_token": token(), "reminders": [], "reminders_paused": adj["delta"] < 0, "created_at": iso(now_utc()),
           "history": [{"at": iso(now_utc()), "action": "correction", "note": body.note.strip(), "by": m["user_id"]}]}
    await db.invoices.insert_one(dict(new))
    await db.invoices.update_one({"id": inv_id}, {"$unset": {"pending_adjustment": ""}, "$push": {"history": {
        "at": iso(now_utc()), "action": "corrected_by", "note": f"{new['number']} ({new['kind']}): {body.note.strip()}", "by": m["user_id"]}}})
    await finalize.finalize_load(inv["load_id"], "invoice_correction", m["user_id"])
    return new


class FleetBillingIn(BaseModel):
    legal_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    billing_email: Optional[str] = None
    mc_number: Optional[str] = None
    usdot_number: Optional[str] = None
    remittance_address: Optional[str] = None
    completion_reports: Optional[bool] = None


@api.patch("/fleet/billing-profile")
async def fleet_billing_profile(body: FleetBillingIn, m: dict = Depends(fleet_member)):
    require_owner(m)
    upd = {k: (v.strip() if isinstance(v, str) else v) for k, v in body.model_dump().items() if v is not None}
    if upd.get("billing_email") and not EMAIL_RE.match(upd["billing_email"]):
        raise HTTPException(status_code=400, detail="Enter a valid billing contact email")
    await db.fleets.update_one({"id": m["fleet_id"]}, {"$set": upd})
    return await db.fleets.find_one({"id": m["fleet_id"]}, {"_id": 0})


@api.get("/")
async def root():
    return {"app": "DockClock", "ok": True}


app.include_router(api)
app.include_router(clerk_router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    try:
        await asyncio.to_thread(init_storage)
    except Exception as e:  # noqa
        logger.error(f"Storage init failed: {e}")
    await db.loads.create_index("id", unique=True)
    await db.loads.create_index("driver_token", unique=True)
    await db.loads.create_index("fleet_id")
    await db.email_schedules.create_index([("active", 1), ("next_run_at", 1)])
    await db.email_schedules.create_index("load_id")
    await db.invoices.create_index("public_token", unique=True)
    await db.invoices.create_index("fleet_id")
    await db.pings.create_index([("load_id", 1), ("ts", 1)])
    await db.users.create_index("user_id", unique=True)
    async for inv in db.invoices.find({"stop_key": {"$exists": False}, "adjusts_invoice_id": None}, {"_id": 0, "id": 1, "load_id": 1, "stop_id": 1}):
        await db.invoices.update_one({"id": inv["id"]}, {"$set": {"stop_key": f"{inv['load_id']}:{inv['stop_id']}"}})
    await db.invoices.create_index("stop_key", unique=True, partialFilterExpression={"stop_key": {"$exists": True}})
    await db.packets.create_index([("load_id", 1), ("version", 1)], unique=True)
    await db.packets.create_index("public_token", unique=True, partialFilterExpression={"public_token": {"$exists": True}})
    await db.outbox.create_index("idempotency_key", unique=True)
    await db.outbox.create_index([("status", 1), ("next_attempt_at", 1)])
    finalize.init(db=db, send_email=send_email, EmailError=EmailError, EmailTimeout=EmailTimeout, store_file=store_file,
                  get_object=get_object, tz_of=tz_of, fmt_local=fmt_local, uid=uid, token=token, evidence_url=evidence_url,
                  src_label=lambda x: {"geofence": "GPS geofence", "driver_tap": "Driver tap", "dispatcher_edit": "Dispatcher adjustment"}.get(x, x or "-"),
                  email_re=EMAIL_RE, fault_hook=None)
    try:
        res = await demo.ensure_demo(db)
        logger.info(f"demo fleet: {res}")
    except Exception as e:  # noqa
        logger.error(f"demo seed failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    client.close()

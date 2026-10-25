import os
import io
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
from core import now_utc, iso, parse, stop_billing, notice_due_at, haversine_m  # noqa: E402
from storage import put_object, get_object, init_storage, APP_NAME  # noqa: E402
from emailer import send_email, EmailError  # noqa: E402
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

DEFAULT_RADIUS = 300


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


class StopIn(BaseModel):
    id: Optional[str] = None
    type: str = "pickup"
    facility_name: Optional[str] = None
    address: Optional[str] = None
    appointment: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_m: Optional[float] = None


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
                    "notice": {"status": "pending", "due_at": None, "sent_at": None}})
    return out


@api.post("/loads")
async def create_load(body: LoadIn, m: dict = Depends(fleet_member)):
    if not body.stops:
        raise HTTPException(status_code=400, detail="Add at least one stop")
    d = body.model_dump()
    stops = await build_stops(m["fleet_id"], body.stops)
    broker_id = await upsert_broker(m["fleet_id"], d["broker"])
    load = {"id": uid(), "fleet_id": m["fleet_id"], "load_number": d.get("load_number") or f"LOAD-{secrets.token_hex(3).upper()}",
            "carrier_name": d.get("carrier_name"), "linehaul_amount": d.get("linehaul_amount"),
            "broker": d["broker"], "broker_id": broker_id, "detention": d["detention"], "stops": stops,
            "driver": d["driver"], "driver_token": token(), "ratecon_file_id": body.file_id,
            "low_confidence": d.get("low_confidence") or [], "sms_log": [], "status": "planned",
            "created_by": m["user_id"], "created_at": iso(now_utc()), "updated_at": iso(now_utc())}
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


def stops_with_billing(load: dict) -> list:
    det = load.get("detention") or {}
    out, billed = [], 0.0
    for s in sorted(load.get("stops", []), key=lambda x: x.get("seq", 0)):
        b = stop_billing(s, det, other_billed=billed)
        billed += b["amount"]
        out.append({**s, "billing": b})
    return out


async def load_view(load: dict, fleet: dict, full: bool = False) -> dict:
    invoices = await db.invoices.find({"load_id": load["id"]}, {"_id": 0}).to_list(50)
    v = {**load, "stops": stops_with_billing(load), "status": load_status(load, invoices),
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
    stops = await build_stops(m["fleet_id"], body.stops, load.get("stops"))
    broker_id = await upsert_broker(m["fleet_id"], d["broker"])
    upd = {"load_number": d.get("load_number") or load["load_number"], "carrier_name": d.get("carrier_name"),
           "linehaul_amount": d.get("linehaul_amount"), "broker": d["broker"], "broker_id": broker_id,
           "detention": d["detention"], "stops": stops, "driver": d["driver"], "updated_at": iso(now_utc())}
    # recompute notice due times for on-site stops
    for s in stops:
        if s.get("arrived_at") and s["notice"]["status"] == "pending":
            s["notice"]["due_at"] = iso(notice_due_at(parse(s["arrived_at"]), d["detention"]))
    await db.loads.update_one({"id": load_id}, {"$set": upd})
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
            f"Tap to open it in the DockClock Driver app, then press Start trip.")
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
        return {"sent": False, "reason": "no_email", "detail": "Add the driver's email first"}
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
    await process_load(load, m["fleet"])
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
    pings = await db.pings.find(q, {"_id": 0, "lat": 1, "lng": 1, "ts": 1, "accuracy": 1, "stop_id": 1}).sort("ts", 1).to_list(20000)
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
    if "radius_m" in upd and not (50 <= upd["radius_m"] <= 3000):
        raise HTTPException(status_code=400, detail="Radius must be between 50 and 3000 meters")
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
        b = stop_billing(stop, load.get("detention") or {})
        stop["notice"]["status"] = "not_needed" if b["billable_minutes"] <= 0 else "missed"
    await save_stop(load["id"], stop)


async def deliver_notice(load, stop, fleet, manual_by=None):
    broker = load.get("broker") or {}
    to = (broker.get("email") or "").strip()
    if not to:
        stop["notice"]["status"] = "no_email"
        await save_stop(load["id"], stop)
        return False, "No broker email on this load"
    b = stop_billing(stop, load.get("detention") or {})
    coords = stop.get("arrived_coords") or {}
    lat, lng = coords.get("lat") or stop.get("lat"), coords.get("lng") or stop.get("lng")
    maps_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}" if lat and lng else None
    subj, html = templates.notice_email(fleet["name"], load, stop, fmt_local(fleet, b.get("free_expires_at")),
                                        fmt_local(fleet, stop.get("arrived_at")), maps_url)
    try:
        email_id = await send_email(to=to, subject=subj, html=html, reply_to=fleet.get("reply_to_email"))
    except EmailError as e:
        stop["notice"]["status"] = "failed"
        stop["notice"]["error"] = str(e)
        await save_stop(load["id"], stop)
        return False, str(e)
    sent = iso(now_utc())
    if fleet.get("reply_to_email"):
        try:
            await send_email(to=fleet["reply_to_email"], subject=f"[Copy] {subj}", html=html)
        except EmailError:
            pass
    stop["notice"].update({"status": "sent", "sent_at": sent, "to": to, "email_id": email_id, "manual_by": manual_by})
    stop["events"].append({"type": "notice_sent", "at": sent, "to": to})
    await save_stop(load["id"], stop)
    await db.notices.insert_one({"id": uid(), "fleet_id": fleet["id"], "load_id": load["id"], "stop_id": stop["id"],
                                 "kind": "detention_notice", "to": to, "sent_at": sent, "email_id": email_id,
                                 "on_time": bool(stop["notice"].get("due_at") and sent <= iso(parse(b.get("free_expires_at")) or now_utc())),
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


async def process_load(load: dict, fleet: dict):
    """Idempotent tick for one load: free-time events, broker notices, invoices."""
    now = now_utc()
    det = load.get("detention") or {}
    for stop in load.get("stops", []):
        if not stop.get("arrived_at"):
            continue
        changed = False
        b = stop_billing(stop, det, now)
        fe = parse(b.get("free_expires_at"))
        end = parse(stop.get("departed_at")) or now
        if fe and end >= fe and b["free_minutes"] >= 0 and not any(e["type"] == "free_time_expired" for e in stop["events"]):
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
        if stop.get("departed_at"):
            await ensure_invoice(load, stop, fleet)


# ---------------------------------------------------------------- driver (public link)

async def load_by_driver_token(tok: str) -> dict:
    load = await db.loads.find_one({"driver_token": tok}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="This link is not valid")
    return load


def driver_payload(load, fleet):
    stops = stops_with_billing(load)
    return {"load_number": load.get("load_number"), "fleet_name": fleet.get("name"),
            "driver_name": (load.get("driver") or {}).get("name"),
            "free_time_hours": (load.get("detention") or {}).get("free_time_hours"),
            "requires_signed_bol": (load.get("detention") or {}).get("requires_signed_bol"),
            "stops": [{k: s.get(k) for k in ("id", "seq", "type", "facility_name", "address", "appointment", "lat", "lng",
                                            "radius_m", "arrived_at", "departed_at", "arrived_source", "departed_source")}
                      | {"bol_count": len(s.get("bol", [])), "free_expires_at": s["billing"].get("free_expires_at"),
                         "notice_sent_at": s["notice"].get("sent_at")} for s in stops]}


@api.get("/open/{tok}", response_class=HTMLResponse)
async def driver_open(tok: str, request: Request):
    """Texted link target: opens the DockClock Driver mobile app, or explains how to install it."""
    load = await db.loads.find_one({"driver_token": tok}, {"_id": 0, "load_number": 1, "driver": 1})
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    origin = f"https://{host}" if host else ""
    deep = f"dockclock://d/{tok}?api={quote(origin, safe='')}"
    intent = f"intent://d/{tok}?api={quote(origin, safe='')}#Intent;scheme=dockclock;end"
    ios_url = os.environ.get("DRIVER_APP_IOS_URL", "")
    android_url = os.environ.get("DRIVER_APP_ANDROID_URL", "")
    return HTMLResponse(templates.driver_open_page(
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
    acc = body.accuracy or 50
    stop = _current_stop(load)
    event = None
    if stop is not None and stop.get("lat") is not None:
        dist = haversine_m(body.lat, body.lng, stop["lat"], stop["lng"])
        radius = float(stop.get("radius_m") or DEFAULT_RADIUS)
        coords = {"lat": body.lat, "lng": body.lng, "accuracy": acc}
        arrived = parse(stop.get("arrived_at")) if stop.get("arrived_at") else None
        if not stop.get("arrived_at") and dist - min(acc, 100) <= radius and acc <= 500:
            await record_arrival(load, stop, ts, "geofence", coords, fleet)
            event = "arrived"
        elif (arrived and ts > arrived and not stop.get("departed_at")
              and dist - min(acc, 100) > radius + 150 and acc <= 300):
            await record_departure(load, stop, ts, "geofence", coords, fleet)
            event = "departed"
    await db.pings.insert_one({"load_id": load["id"], "fleet_id": load["fleet_id"], "lat": body.lat, "lng": body.lng,
                               "accuracy": acc, "ts": iso(ts), "stop_id": stop["id"] if stop else None})
    prev = parse((load.get("last_ping") or {}).get("ts")) if (load.get("last_ping") or {}).get("ts") else None
    if not prev or ts >= prev:
        await db.loads.update_one({"id": load["id"]}, {"$set": {"last_ping": {"lat": body.lat, "lng": body.lng, "ts": iso(ts)}}})
    load = await load_by_driver_token(tok)
    await process_load(load, fleet)
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
                               "accuracy": body.accuracy or 50, "ts": iso(ts), "stop_id": stop_id})
    load = await load_by_driver_token(tok)
    await process_load(load, fleet)
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
    return driver_payload(await load_by_driver_token(tok), fleet)


# ---------------------------------------------------------------- invoices

async def invoice_context(inv: dict):
    load = await db.loads.find_one({"id": inv["load_id"]}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Load missing")
    stops = stops_with_billing(load)
    stop = next((s for s in stops if s["id"] == inv["stop_id"]), None)
    fleet = await db.fleets.find_one({"id": inv["fleet_id"]}, {"_id": 0})
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


def reminder_plan(inv):
    sent = parse(inv.get("sent_at"))
    done = {r["day"] for r in inv.get("reminders", [])}
    return [{"day": d, "due_at": iso(sent + timedelta(days=d)) if sent else None, "sent": d in done,
             "sent_at": next((r["sent_at"] for r in inv.get("reminders", []) if r["day"] == d), None)}
            for d in core.REMINDER_DAYS]


@api.get("/invoices")
async def list_invoices(m: dict = Depends(fleet_member)):
    invs = await db.invoices.find({"fleet_id": m["fleet_id"]}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return [{**i, "reminder_plan": reminder_plan(i), "evidence_url": evidence_url(m["fleet"], i)} for i in invs]


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
    to = ((load.get("broker") or {}).get("email") or "").strip()
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
    subj, html = templates.invoice_email(fleet["name"], inv, load, stop, evidence_url(fleet, inv))
    try:
        await send_email(to=to, subject=subj, html=html, reply_to=fleet.get("reply_to_email"))
    except EmailError as e:
        raise HTTPException(status_code=502, detail=str(e))
    now = iso(now_utc())
    upd.update({"status": "sent", "last_emailed_at": now})
    if not inv.get("sent_at"):
        upd["sent_at"] = now
    await db.invoices.update_one({"id": inv_id}, {"$set": upd, "$push": {"history": {"at": now, "action": "emailed", "to": to}}})
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
    if not inv or inv["status"] == "ready":
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
        for s in stops_with_billing(ld):
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
    outstanding = round(sum(i["amount"] for i in invs if i["status"] == "sent"), 2)
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
        done = {r["day"] for r in inv.get("reminders", [])}
        due = [d for d in core.REMINDER_DAYS if d not in done and now >= sent + timedelta(days=d)]
        if not due:
            continue
        day = max(due)
        try:
            f, load, stop, notices, pb = await invoice_context(inv)
            subj, html = templates.invoice_email(fleet["name"], inv, load, stop, evidence_url(fleet, inv),
                                                 tone_idx=core.REMINDER_DAYS.index(day))
            await send_email(to=inv["broker_email"], subject=subj, html=html, reply_to=fleet.get("reply_to_email"))
            entries = [{"day": d, "sent_at": iso(now), "skipped": d != day} for d in due]
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
    outstanding = sum(i["amount"] for i in await db.invoices.find({"fleet_id": fleet["id"], "status": "sent"}, {"_id": 0}).to_list(2000))
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
                await process_load(ld, f)
            except Exception as e:  # noqa
                logger.warning(f"tick load {ld['id']} failed: {e}")
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
    try:
        res = await demo.ensure_demo(db)
        logger.info(f"demo fleet: {res}")
    except Exception as e:  # noqa
        logger.error(f"demo seed failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    client.close()

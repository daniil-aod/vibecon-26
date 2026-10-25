"""DockClock guided demo fleet.

Seeds one fully-worked carrier so a reviewer (abdowns4@gmail.com) can sign in and
explore every feature end to end: a rate con read by AI, a driver GPS trail, a live
detention meter, a broker notice, sealed evidence packets, a card payment, overdue
reminders, a disputed cap-hit claim, and broker/facility scorecards.

Design goals:
- Idempotent. Re-running wipes only this demo fleet's data and rebuilds it.
- Version-gated. Bump DEMO_VERSION whenever the app gains a feature that the demo
  should showcase; ensure_demo() then rebuilds automatically on the next boot.
- Self-contained sample files (rate con PDF + signed BOL photo) generated in-process.
- No real email/SMS/charges: statuses are written directly, texts are marked simulated.
"""
import asyncio
import hashlib
import io
import random
import uuid
from datetime import timedelta

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdfcanvas
from PIL import Image, ImageDraw

import core
from core import now_utc, iso
from storage import put_object, APP_NAME

DEMO_FLEET_ID = "demo-dockclock-fleet"
DEMO_OWNER_EMAIL = "abdowns4@gmail.com"
DEMO_VERSION = 2  # bump to force a rebuild on next startup when features change
PREVIEW_URL = "https://load-locator-4.preview.emergentagent.com"

# collections that hold demo-fleet-scoped data (everything keyed by fleet_id)
_SCOPED = ["loads", "invoices", "notices", "pings", "facilities", "brokers",
           "files", "payment_transactions"]


def _uid() -> str:
    return str(uuid.uuid4())


def _tok() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex[:8]


def ago(minutes=0, hours=0, days=0):
    return now_utc() - timedelta(minutes=minutes, hours=hours, days=days)


# --------------------------------------------------------------- sample files

def make_ratecon_pdf(load_number, broker, carrier, stops, det) -> bytes:
    """A realistic one-page rate confirmation the AI 'read'."""
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    w, h = letter
    y = h - 0.9 * inch
    c.setFont("Helvetica-Bold", 18)
    c.drawString(0.9 * inch, y, broker["name"])
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y - 14, "Rate Confirmation / Load Tender")
    c.drawRightString(w - 0.9 * inch, y, f"Load #: {load_number}")
    c.drawRightString(w - 0.9 * inch, y - 14, f"Broker contact: {broker.get('contact_name','Dispatch')}  {broker.get('phone','')}")
    y -= 0.5 * inch
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.line(0.9 * inch, y, w - 0.9 * inch, y)
    y -= 0.3 * inch

    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.9 * inch, y, "Carrier:")
    c.setFont("Helvetica", 10)
    c.drawString(1.7 * inch, y, carrier)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(w - 2.0 * inch, y, "Line haul:")
    c.setFont("Helvetica", 10)
    c.drawRightString(w - 0.9 * inch, y, f"${det.get('_linehaul', 1850):,.2f}")
    y -= 0.35 * inch

    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.9 * inch, y, "Stops")
    y -= 0.22 * inch
    c.setFont("Helvetica", 9)
    for i, s in enumerate(stops, 1):
        label = "PU" if s["type"] == "pickup" else "DEL"
        c.drawString(1.0 * inch, y, f"{i}. [{label}] {s['facility_name']}")
        y -= 13
        c.drawString(1.2 * inch, y, s["address"])
        if s.get("appointment"):
            c.drawString(4.9 * inch, y, f"Appt: {s['appointment'].replace('T',' ')}")
        y -= 18

    y -= 0.15 * inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.9 * inch, y, "Detention / Accessorial Terms")
    y -= 0.22 * inch
    c.setFont("Helvetica", 9)
    lines = [
        f"Free time: {det['free_time_hours']:g} hours per stop.",
        f"Detention rate: ${det['hourly_rate']:.2f} per hour, billed in {int(det['billing_increment_minutes'])}-minute increments.",
        (f"Maximum detention: ${det['cap_amount']:.2f} {det.get('cap_scope','per_stop').replace('_',' ')}."
         if det.get("cap_amount") else "Maximum detention: none stated."),
        det.get("notice_rule_text", ""),
        f"Signed bill of lading {'required' if det.get('requires_signed_bol') else 'not required'} for detention payment.",
    ]
    for ln in lines:
        if ln:
            c.drawString(1.0 * inch, y, ln)
            y -= 15

    y -= 0.1 * inch
    c.setFont("Helvetica-Oblique", 8.5)
    clause = det.get("clause_text", "")
    # wrap the verbatim clause
    words, line = clause.split(), ""
    for word in words:
        if len(line) + len(word) > 105:
            c.drawString(1.0 * inch, y, line)
            y -= 12
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        c.drawString(1.0 * inch, y, line)
    c.setFont("Helvetica", 8)
    c.drawString(0.9 * inch, 0.8 * inch, "This tender is subject to the carrier/broker agreement. Generated sample document for DockClock demo.")
    c.showPage()
    c.save()
    return buf.getvalue()


def make_bol_png(load_number, facility, driver, shipper, consignee, when=None) -> bytes:
    """A signed bill-of-lading photo (clean synthetic scan)."""
    when = when or now_utc()
    W, H = 900, 1160
    img = Image.new("RGB", (W, H), (247, 246, 242))
    d = ImageDraw.Draw(img)
    # paper
    d.rectangle([30, 30, W - 30, H - 30], fill=(255, 255, 255), outline=(210, 210, 210), width=2)

    def text(x, y, s, size=20, bold=False, fill=(30, 30, 30)):
        # PIL default bitmap font scales poorly; emulate size with repeated draw offset for bold
        d.text((x, y), s, fill=fill)
        if bold:
            d.text((x + 1, y), s, fill=fill)

    text(70, 70, "STRAIGHT BILL OF LADING - SHORT FORM", bold=True)
    text(70, 95, f"Load / Pro No.: {load_number}")
    text(600, 95, f"Date: {when.strftime('%m/%d/%Y')}")
    d.line([70, 125, W - 70, 125], fill=(200, 200, 200), width=1)

    text(70, 150, "Ship From (Shipper):", bold=True)
    text(90, 175, shipper)
    text(70, 215, "Ship To (Consignee):", bold=True)
    text(90, 240, consignee)
    text(70, 280, "Delivery Facility:", bold=True)
    text(90, 305, facility)

    d.line([70, 345, W - 70, 345], fill=(200, 200, 200), width=1)
    text(70, 365, "Qty      Description                                 Weight", bold=True)
    rows = [("24", "Palletized dry goods - GEN MERCH", "41,280 lb"),
            ("", "Seal #: 0094271   Trailer: DRY-53", "")]
    yy = 395
    for q, desc, wt in rows:
        text(80, yy, f"{q:<8} {desc:<42} {wt}")
        yy += 30

    d.rectangle([70, 470, W - 70, 470], outline=(200, 200, 200))
    text(70, 500, "Arrival stamp (guard shack):", bold=True)
    text(90, 525, f"IN: {when.strftime('%m/%d/%Y')}  recorded at dock")
    text(90, 550, "OUT: see DockClock geofence record")

    text(70, 620, "Received in good condition except as noted:", bold=True)
    text(70, 680, "Consignee signature:", bold=True)
    # handwritten-looking signature
    sig_pts = [(300, 720), (330, 695), (350, 730), (380, 700), (410, 735),
               (445, 698), (480, 728), (520, 705), (560, 730)]
    d.line(sig_pts, fill=(20, 40, 120), width=3)
    d.line([300, 745, 600, 745], fill=(120, 120, 120), width=1)
    text(70, 760, f"Printed name: {consignee.split(',')[0]} receiving dept.")

    text(70, 820, "Driver signature:", bold=True)
    d.line([(300, 850), (340, 835), (370, 858), (410, 838), (450, 856)], fill=(20, 40, 120), width=3)
    d.line([300, 868, 600, 868], fill=(120, 120, 120), width=1)
    text(70, 883, f"Driver: {driver}")

    text(70, 960, "Notes: Detention - driver held at dock beyond appointment. Times stamped by DockClock.", fill=(90, 90, 90))
    text(70, 1095, "SAMPLE DOCUMENT - DockClock demo", fill=(150, 150, 150))

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


# --------------------------------------------------------------- trail builder

def _ping(fleet_id, load_id, stop_id, lat, lng, ts, acc):
    return {"id": _uid(), "load_id": load_id, "fleet_id": fleet_id, "stop_id": stop_id,
            "lat": round(lat, 6), "lng": round(lng, 6), "accuracy": acc, "ts": iso(ts)}


def make_trail(fleet_id, load_id, stop, arrived_dt, end_dt, departing=True):
    """Approach -> dwell inside the geofence -> depart, as GPS pings."""
    lat, lng = stop["lat"], stop["lng"]
    rnd = random.Random(f"{load_id}{stop['id']}")
    pings = []
    # approach from the SW over ~24 minutes
    for i in range(4, 0, -1):
        f = i / 4.0
        pings.append(_ping(fleet_id, load_id, stop["id"],
                           lat - 0.03 * f + rnd.uniform(-0.002, 0.002),
                           lng - 0.04 * f + rnd.uniform(-0.002, 0.002),
                           arrived_dt - timedelta(minutes=6 * i), rnd.randint(18, 45)))
    # dwell: points jittered well within a 300 m geofence (~0.0009 deg ≈ 100 m)
    dwell_min = max(1.0, (end_dt - arrived_dt).total_seconds() / 60.0)
    n = max(3, int(dwell_min // 30))
    for i in range(n + 1):
        t = arrived_dt + timedelta(minutes=dwell_min * i / n)
        pings.append(_ping(fleet_id, load_id, stop["id"],
                           lat + rnd.uniform(-0.0009, 0.0009),
                           lng + rnd.uniform(-0.0009, 0.0009),
                           t, rnd.randint(10, 24)))
    # depart to the NE
    if departing:
        for i in range(1, 4):
            f = i / 3.0
            pings.append(_ping(fleet_id, load_id, stop["id"],
                               lat + 0.028 * f + rnd.uniform(-0.002, 0.002),
                               lng + 0.035 * f + rnd.uniform(-0.002, 0.002),
                               end_dt + timedelta(minutes=5 * i), rnd.randint(20, 48)))
    pings.sort(key=lambda p: p["ts"])
    return pings


def _window(all_pings, stop):
    """Mirror server.playback_data windowing so the sealed fingerprint matches on verify."""
    a = core.parse(stop.get("arrived_at"))
    d = core.parse(stop.get("departed_at"))
    if not a:
        return []
    lo = iso(a - timedelta(minutes=45))
    hi = iso((d or now_utc()) + timedelta(minutes=45))
    return sorted([p for p in all_pings if lo <= p["ts"] <= hi], key=lambda p: p["ts"])


# --------------------------------------------------------------- fixtures

FACILITIES = {
    "joliet": dict(name="Midwest Distribution Center", address="1801 Rock Creek Blvd, Joliet, IL 60431", lat=41.5250, lng=-88.0817),
    "houston": dict(name="Gulf Coast Freight Terminal", address="6400 Clinton Dr, Houston, TX 77020", lat=29.7620, lng=-95.2810),
    "fontana": dict(name="Inland Empire Cold Storage", address="15700 Slover Ave, Fontana, CA 92337", lat=34.0490, lng=-117.4350),
    "atlanta": dict(name="Northlake Grocery DC", address="2500 Northlake Pkwy, Tucker, GA 30084", lat=33.8600, lng=-84.2460),
    "columbus": dict(name="Buckeye Crossdock", address="6500 Alum Creek Dr, Columbus, OH 43217", lat=39.8640, lng=-82.9230),
}

BROKERS = {
    "evergreen": dict(name="Evergreen Logistics", contact_name="Dana Reyes", email="dispatch@evergreenlogistics-demo.com", phone="(312) 555-0142"),
    "apex": dict(name="Apex Freight Brokers", contact_name="Marcus Hill", email="ap@apexfreight-demo.com", phone="(713) 555-0198"),
    "redline": dict(name="Redline Transport Brokerage", contact_name="Priya Nair", email="billing@redline-demo.com", phone="(404) 555-0176"),
}

CLAUSE = {
    "evergreen": ("Detention will be paid at $50.00 per hour after two (2) hours of free time at each stop, billed in "
                  "fifteen (15) minute increments, not to exceed $400.00 per stop. Carrier must notify Evergreen "
                  "Logistics in writing at least thirty (30) minutes before free time expires and submit a signed "
                  "bill of lading to qualify for detention payment."),
    "apex": ("Shipper and receiver allow two (2) hours free for loading/unloading. Detention thereafter is $45.00 per "
             "hour in thirty (30) minute increments. Carrier must report detention to Apex Freight Brokers within one "
             "(1) hour of arrival. A signed, legible BOL with in and out times is required."),
    "redline": ("One (1) hour free time per stop. Detention is billed at $60.00 per hour in fifteen (15) minute "
                "increments up to a maximum of $400.00 per stop. Driver must call or text Redline before the free "
                "hour ends. No detention paid without a signed delivery receipt."),
}


def det_for(key, linehaul):
    if key == "evergreen":
        return dict(free_time_hours=2.0, hourly_rate=50.0, billing_increment_minutes=15.0, cap_amount=400.0,
                    cap_scope="per_stop", notice_after_arrival_minutes=None, notice_before_expiry_minutes=30.0,
                    notice_rule_text="Notify in writing at least 30 minutes before free time expires.",
                    requires_signed_bol=True, clause_text=CLAUSE["evergreen"], _linehaul=linehaul)
    if key == "apex":
        return dict(free_time_hours=2.0, hourly_rate=45.0, billing_increment_minutes=30.0, cap_amount=None,
                    cap_scope="per_stop", notice_after_arrival_minutes=60.0, notice_before_expiry_minutes=None,
                    notice_rule_text="Report detention within 1 hour of arrival.",
                    requires_signed_bol=True, clause_text=CLAUSE["apex"], _linehaul=linehaul)
    return dict(free_time_hours=1.0, hourly_rate=60.0, billing_increment_minutes=15.0, cap_amount=400.0,
                cap_scope="per_stop", notice_after_arrival_minutes=None, notice_before_expiry_minutes=15.0,
                notice_rule_text="Call or text Redline before the free hour ends.",
                requires_signed_bol=True, clause_text=CLAUSE["redline"], _linehaul=linehaul)


# --------------------------------------------------------------- seed

class _Seeder:
    def __init__(self, db):
        self.db = db
        self.fid = DEMO_FLEET_ID
        self.facs = {}     # key -> facility doc
        self.brokers = {}  # key -> broker id
        self.files = []
        self.loads = []
        self.invoices = []
        self.notices = []
        self.pings = []
        self.payments = []
        self.invoice_seq = 1000

    async def _store(self, data, content_type, ext, kind, extra=None, created_at=None):
        path = f"{APP_NAME}/{self.fid}/{kind}/{_uid()}.{ext}"
        res = await asyncio.to_thread(put_object, path, data, content_type)
        rec = {"id": _uid(), "fleet_id": self.fid, "storage_path": res["path"], "content_type": content_type,
               "size": res.get("size", len(data)), "sha256": hashlib.sha256(data).hexdigest(), "kind": kind,
               "is_deleted": False, "created_at": iso(created_at) if created_at else iso(now_utc()), **(extra or {})}
        self.files.append(rec)
        return rec

    def facility(self, key):
        if key not in self.facs:
            f = FACILITIES[key]
            self.facs[key] = {"id": _uid(), "fleet_id": self.fid,
                              "key": "".join(ch for ch in (f["name"] + f["address"]).lower() if ch.isalnum()),
                              "name": f["name"], "address": f["address"], "lat": f["lat"], "lng": f["lng"],
                              "radius_m": 300, "created_at": iso(now_utc())}
        return self.facs[key]

    def broker_id(self, key):
        if key not in self.brokers:
            b = BROKERS[key]
            bid = _uid()
            self.brokers[key] = bid
            self.brokers[f"_doc_{key}"] = {"id": bid, "fleet_id": self.fid,
                                           "key": "".join(ch for ch in b["name"].lower() if ch.isalnum()),
                                           "name": b["name"], "email": b["email"], "created_at": iso(now_utc())}
        return self.brokers[key]

    def _make_stop(self, seq, type_, fac_key, appt=None, arrived=None, departed=None, notice_status="pending",
                   notice_sent_at=None, geofence=True):
        fac = self.facility(fac_key)
        src = "geofence" if geofence else "driver_tap"
        coords = {"lat": fac["lat"], "lng": fac["lng"], "accuracy": 16} if geofence else None
        stop = {"id": _uid(), "seq": seq, "type": type_, "facility_id": fac["id"], "facility_name": fac["name"],
                "address": fac["address"], "appointment": appt, "lat": fac["lat"], "lng": fac["lng"], "radius_m": 300,
                "arrived_at": iso(arrived) if arrived else None, "departed_at": iso(departed) if departed else None,
                "arrived_source": src if arrived else None, "departed_source": src if departed else None,
                "arrived_coords": coords if arrived else None, "departed_coords": coords if departed else None,
                "events": [], "bol": [],
                "notice": {"status": notice_status, "due_at": iso(arrived + timedelta(minutes=90)) if arrived else None,
                           "sent_at": iso(notice_sent_at) if notice_sent_at else None}}
        if arrived:
            stop["events"].append({"type": "arrival", "at": iso(arrived), "source": src, "coords": coords})
        if notice_sent_at:
            stop["notice"].update({"to": None, "email_id": "demo", "manual_by": None})
            stop["events"].append({"type": "notice_sent", "at": iso(notice_sent_at)})
        if departed:
            stop["events"].append({"type": "departure", "at": iso(departed), "source": src, "coords": coords})
        return stop, fac

    async def _add_bol(self, stop, load_number, driver_name, shipper, consignee, uploaded_at=None):
        # A driver photographs the signed BOL at the dock on their way out, so stamp it
        # near this stop's departure — not at seed time.
        if uploaded_at is None:
            dep = core.parse(stop.get("departed_at"))
            uploaded_at = (dep + timedelta(minutes=1)) if dep else now_utc()
        png = make_bol_png(load_number, stop["facility_name"], driver_name, shipper, consignee, when=uploaded_at)
        rec = await self._store(png, "image/png", "png", "bol",
                                {"load_id": None, "stop_id": stop["id"]}, created_at=uploaded_at)
        stop["bol"].append({"file_id": rec["id"], "sha256": rec["sha256"], "uploaded_at": rec["created_at"],
                            "content_type": "image/png"})
        stop["events"].append({"type": "bol_uploaded", "at": rec["created_at"]})
        return rec

    def _notice_doc(self, load, stop, sent_at, on_time=True):
        to = (load["broker"].get("email") or "")
        doc = {"id": _uid(), "fleet_id": self.fid, "load_id": load["id"], "stop_id": stop["id"],
               "kind": "detention_notice", "to": to, "sent_at": iso(sent_at), "email_id": "demo",
               "on_time": on_time, "created_at": iso(sent_at)}
        stop["notice"]["to"] = to
        self.notices.append(doc)
        return doc

    def _invoice(self, load, stop, det, status, sent_at=None, paid_at=None, paid_method=None,
                 reminders=None, reminders_paused=False, sealed=True):
        self.invoice_seq += 1
        billing = core.stop_billing(stop, det)
        notices = [n for n in self.notices if n["stop_id"] == stop["id"]]
        inv = {"id": _uid(), "fleet_id": self.fid, "load_id": load["id"], "stop_id": stop["id"],
               "number": f"DC-{self.invoice_seq}", "load_number": load["load_number"],
               "broker_id": load.get("broker_id"), "broker_name": load["broker"].get("name"),
               "broker_email": load["broker"].get("email"), "facility_id": stop.get("facility_id"),
               "facility_name": stop.get("facility_name"), "amount": billing["amount"],
               "billable_label": f"{billing['billed_minutes'] / 60:.2f} h", "status": status,
               "public_token": _tok(), "fingerprint": None, "sealed_evidence": None,
               "reminders": reminders or [], "reminders_paused": reminders_paused,
               "created_at": iso(sent_at or paid_at or now_utc()), "sent_at": iso(sent_at) if sent_at else None,
               "paid_at": iso(paid_at) if paid_at else None, "history": []}
        if paid_method:
            inv["paid_method"] = paid_method
            inv["paid_amount"] = billing["amount"]
        if sealed and status != "ready":
            stop_b = {**stop, "billing": billing}
            pings = _window(self.pings, stop)
            ev = core.evidence_record(inv, load, stop_b, billing, notices, pings)
            inv["sealed_evidence"] = ev
            inv["fingerprint"] = core.canonical_hash(ev)
            inv["sealed_at"] = iso(sent_at or paid_at or now_utc())
        self.invoices.append(inv)
        return inv, billing

    def _load(self, load_number, broker_key, carrier, linehaul, stops, driver, status, ratecon_file_id=None,
              extracted=None, texted=True):
        det = det_for(broker_key, linehaul)
        bdoc = BROKERS[broker_key]
        load = {"id": _uid(), "fleet_id": self.fid, "load_number": load_number, "carrier_name": carrier,
                "linehaul_amount": linehaul,
                "broker": {"name": bdoc["name"], "contact_name": bdoc["contact_name"], "email": bdoc["email"], "phone": bdoc["phone"]},
                "broker_id": self.broker_id(broker_key), "detention": det, "stops": [s for s, _ in stops],
                "driver": driver, "driver_token": hashlib.sha256(f"demo-driver:{self.fid}:{load_number}".encode()).hexdigest()[:40],
                "ratecon_file_id": ratecon_file_id,
                "low_confidence": [], "sms_log": [], "status": status,
                "created_by": "demo", "created_at": iso(now_utc()),
                "updated_at": iso(now_utc())}
        if texted:
            load["sms_log"] = [{"at": iso(ago(hours=6)), "to": driver.get("phone"), "by": "demo",
                                "status": "simulated", "note": "Twilio not connected - link copied for manual send"}]
        self.loads.append(load)
        return load, det

    async def build(self):
        shipper = "Prairie Foods Co., 500 Industrial Dr, Bolingbrook, IL"

        # ---- LOAD A: completed + PAID by card (happy path, verified evidence) ----
        a_arr_pu, a_dep_pu = ago(days=9, hours=5), ago(days=9, hours=4, minutes=20)
        a_arr, a_dep = ago(days=8, hours=6), ago(days=8, hours=1, minutes=50)  # dwell 4h10 -> 2h10 billable -> 2h -> $100
        pu, _ = self._make_stop(0, "pickup", "joliet", appt=ago(days=9, hours=5).strftime("%Y-%m-%dT08:00"),
                                arrived=a_arr_pu, departed=a_dep_pu, notice_status="not_needed")
        dl, dfac = self._make_stop(1, "delivery", "houston", appt=ago(days=8, hours=6).strftime("%Y-%m-%dT09:00"),
                                   arrived=a_arr, departed=a_dep, notice_status="sent", notice_sent_at=a_arr + timedelta(minutes=90))
        detA = det_for("evergreen", 2450)
        pdf = make_ratecon_pdf("EVG-77421", BROKERS["evergreen"], "Summit Ridge Carriers LLC",
                               [{"type": "pickup", "facility_name": self.facility("joliet")["name"], "address": self.facility("joliet")["address"], "appointment": pu["appointment"]},
                                {"type": "delivery", "facility_name": dfac["name"], "address": dfac["address"], "appointment": dl["appointment"]}], detA)
        prec = await self._store(pdf, "application/pdf", "pdf", "ratecon", {"original_filename": "EVG-77421-ratecon.pdf"})
        extractedA = {"load_number": "EVG-77421", "broker": BROKERS["evergreen"], "carrier_name": "Summit Ridge Carriers LLC",
                      "linehaul_amount": 2450.0,
                      "stops": [{"type": "pickup", "facility_name": self.facility("joliet")["name"], "address": self.facility("joliet")["address"], "appointment": pu["appointment"]},
                                {"type": "delivery", "facility_name": dfac["name"], "address": dfac["address"], "appointment": dl["appointment"]}],
                      "detention": {k: v for k, v in detA.items() if not k.startswith("_")},
                      "low_confidence": [], "_model": "gemini-3.1-pro-preview"}
        prec["extracted"] = extractedA
        loadA, _ = self._load("EVG-77421", "evergreen", "Summit Ridge Carriers LLC", 2450,
                              [(pu, None), (dl, dfac)], {"name": "Luis Moreno", "phone": "+13125550111"},
                              "paid", ratecon_file_id=prec["id"])
        self.pings += make_trail(self.fid, loadA["id"], pu, a_arr_pu, a_dep_pu)
        self.pings += make_trail(self.fid, loadA["id"], dl, a_arr, a_dep)
        loadA["last_ping"] = {"lat": dl["lat"] + 0.03, "lng": dl["lng"] + 0.035, "ts": iso(a_dep + timedelta(minutes=15))}
        await self._add_bol(dl, "EVG-77421", "Luis Moreno", shipper, dfac["name"])
        self._notice_doc(loadA, dl, a_arr + timedelta(minutes=90), on_time=True)
        invA, bA = self._invoice(loadA, dl, detA, "paid", sent_at=ago(days=8), paid_at=ago(days=5),
                                 paid_method="card", reminders_paused=True)
        invA["viewed_at"] = iso(ago(days=7, hours=20))
        invA["history"] = [{"at": iso(ago(days=8)), "action": "emailed", "to": loadA["broker"]["email"]},
                           {"at": iso(ago(days=5)), "action": "paid_by_card", "session_id": "cs_demo_evg77421"}]
        self.payments.append({"session_id": "cs_demo_evg77421", "invoice_id": invA["id"], "fleet_id": self.fid,
                              "amount": invA["amount"], "currency": "usd", "status": "completed",
                              "payment_status": "paid", "tax_mode": "none", "stripe_payment_intent_id": "pi_demo_evg",
                              "created_at": iso(ago(days=5, minutes=5)), "updated_at": iso(ago(days=5))})

        # ---- LOAD B: ACTIVE on site right now (live meter + truck on the map) ----
        b_arr = ago(hours=2, minutes=35)  # dwell 2h35 -> past 2h free -> 35 min detention running
        bdl, bfac = self._make_stop(0, "delivery", "fontana", appt=now_utc().strftime("%Y-%m-%dT07:00"),
                                    arrived=b_arr, departed=None, notice_status="sent",
                                    notice_sent_at=b_arr + timedelta(minutes=90))
        detB = det_for("redline", 1950)
        pdfB = make_ratecon_pdf("RL-55018", BROKERS["redline"], "Summit Ridge Carriers LLC",
                                [{"type": "delivery", "facility_name": bfac["name"], "address": bfac["address"], "appointment": bdl["appointment"]}], detB)
        precB = await self._store(pdfB, "application/pdf", "pdf", "ratecon", {"original_filename": "RL-55018-ratecon.pdf"})
        precB["extracted"] = {"load_number": "RL-55018", "broker": BROKERS["redline"], "carrier_name": "Summit Ridge Carriers LLC",
                              "linehaul_amount": 1950.0,
                              "stops": [{"type": "delivery", "facility_name": bfac["name"], "address": bfac["address"], "appointment": bdl["appointment"]}],
                              "detention": {k: v for k, v in detB.items() if not k.startswith("_")},
                              "low_confidence": [], "_model": "gemini-3.1-pro-preview"}
        loadB, _ = self._load("RL-55018", "redline", "Summit Ridge Carriers LLC", 1950,
                              [(bdl, bfac)], {"name": "Tanya Brooks", "phone": "+19095550133"},
                              "on_site", ratecon_file_id=precB["id"])
        self.pings += make_trail(self.fid, loadB["id"], bdl, b_arr, now_utc(), departing=False)
        last = max([p for p in self.pings if p["load_id"] == loadB["id"]], key=lambda p: p["ts"])
        loadB["last_ping"] = {"lat": last["lat"], "lng": last["lng"], "ts": last["ts"]}
        self._notice_doc(loadB, bdl, b_arr + timedelta(minutes=90), on_time=True)

        # ---- LOAD C: completed, invoice READY to send (attention list) ----
        c_arr, c_dep = ago(days=2, hours=5), ago(days=2, hours=2)  # dwell 3h -> 1h billable -> $45
        cdl, cfac = self._make_stop(0, "delivery", "atlanta", appt=ago(days=2, hours=5).strftime("%Y-%m-%dT10:00"),
                                    arrived=c_arr, departed=c_dep, notice_status="sent", notice_sent_at=c_arr + timedelta(minutes=120))
        detC = det_for("apex", 2100)
        pdfC = make_ratecon_pdf("APX-30277", BROKERS["apex"], "Summit Ridge Carriers LLC",
                                [{"type": "delivery", "facility_name": cfac["name"], "address": cfac["address"], "appointment": cdl["appointment"]}], detC)
        precC = await self._store(pdfC, "application/pdf", "pdf", "ratecon", {"original_filename": "APX-30277-ratecon.pdf"})
        precC["extracted"] = {"load_number": "APX-30277", "broker": BROKERS["apex"], "carrier_name": "Summit Ridge Carriers LLC",
                              "linehaul_amount": 2100.0,
                              "stops": [{"type": "delivery", "facility_name": cfac["name"], "address": cfac["address"], "appointment": cdl["appointment"]}],
                              "detention": {k: v for k, v in detC.items() if not k.startswith("_")},
                              "low_confidence": ["detention.cap_amount"], "_model": "gemini-3.1-pro-preview"}
        loadC, _ = self._load("APX-30277", "apex", "Summit Ridge Carriers LLC", 2100,
                              [(cdl, cfac)], {"name": "Darnell Price", "phone": "+14045550155"},
                              "ready", ratecon_file_id=precC["id"])
        loadC["low_confidence"] = ["detention.cap_amount"]
        self.pings += make_trail(self.fid, loadC["id"], cdl, c_arr, c_dep)
        loadC["last_ping"] = {"lat": cdl["lat"] + 0.03, "lng": cdl["lng"] + 0.035, "ts": iso(c_dep + timedelta(minutes=15))}
        await self._add_bol(cdl, "APX-30277", "Darnell Price", shipper, cfac["name"])
        self._notice_doc(loadC, cdl, c_arr + timedelta(minutes=120), on_time=True)
        self._invoice(loadC, cdl, detC, "ready", sealed=False)

        # ---- LOAD D: invoice SENT, overdue, reminders fired (outstanding) ----
        d_arr, d_dep = ago(days=13, hours=7), ago(days=13, hours=2)  # dwell 5h -> 3h billable -> $135 (apex $45)
        ddl, dfac2 = self._make_stop(0, "delivery", "columbus", appt=ago(days=13, hours=7).strftime("%Y-%m-%dT06:00"),
                                     arrived=d_arr, departed=d_dep, notice_status="sent", notice_sent_at=d_arr + timedelta(minutes=120))
        detD = det_for("apex", 1780)
        pdfD = make_ratecon_pdf("APX-30188", BROKERS["apex"], "Summit Ridge Carriers LLC",
                                [{"type": "delivery", "facility_name": dfac2["name"], "address": dfac2["address"], "appointment": ddl["appointment"]}], detD)
        precD = await self._store(pdfD, "application/pdf", "pdf", "ratecon", {"original_filename": "APX-30188-ratecon.pdf"})
        precD["extracted"] = {"load_number": "APX-30188", "broker": BROKERS["apex"], "carrier_name": "Summit Ridge Carriers LLC",
                              "linehaul_amount": 1780.0,
                              "stops": [{"type": "delivery", "facility_name": dfac2["name"], "address": dfac2["address"], "appointment": ddl["appointment"]}],
                              "detention": {k: v for k, v in detD.items() if not k.startswith("_")},
                              "low_confidence": [], "_model": "gemini-3.1-pro-preview"}
        loadD, _ = self._load("APX-30188", "apex", "Summit Ridge Carriers LLC", 1780,
                              [(ddl, dfac2)], {"name": "Greg Olsen", "phone": "+16145550177"},
                              "invoiced", ratecon_file_id=precD["id"])
        self.pings += make_trail(self.fid, loadD["id"], ddl, d_arr, d_dep)
        loadD["last_ping"] = {"lat": ddl["lat"] + 0.03, "lng": ddl["lng"] + 0.035, "ts": iso(d_dep + timedelta(minutes=15))}
        await self._add_bol(ddl, "APX-30188", "Greg Olsen", shipper, dfac2["name"])
        self._notice_doc(loadD, ddl, d_arr + timedelta(minutes=120), on_time=True)
        sentD = ago(days=12)
        remD = [{"day": 3, "sent_at": iso(ago(days=9)), "skipped": False},
                {"day": 7, "sent_at": iso(ago(days=5)), "skipped": False}]
        invD, _ = self._invoice(loadD, ddl, detD, "sent", sent_at=sentD, reminders=remD)
        invD["last_emailed_at"] = iso(ago(days=5))
        invD["viewed_at"] = iso(ago(days=11))
        invD["history"] = [{"at": iso(sentD), "action": "emailed", "to": loadD["broker"]["email"]}]

        # ---- LOAD E: quick turn, NO detention (good facility signal) ----
        e_arr, e_dep = ago(days=4, hours=3), ago(days=4, hours=1, minutes=45)  # 1h15 dwell, under 2h free
        edl, efac = self._make_stop(0, "delivery", "joliet", appt=ago(days=4, hours=3).strftime("%Y-%m-%dT13:00"),
                                    arrived=e_arr, departed=e_dep, notice_status="not_needed")
        detE = det_for("evergreen", 1620)
        loadE, _ = self._load("EVG-77510", "evergreen", "Summit Ridge Carriers LLC", 1620,
                              [(edl, efac)], {"name": "Luis Moreno", "phone": "+13125550111"}, "completed")
        self.pings += make_trail(self.fid, loadE["id"], edl, e_arr, e_dep)
        loadE["last_ping"] = {"lat": edl["lat"] + 0.03, "lng": edl["lng"] + 0.035, "ts": iso(e_dep + timedelta(minutes=15))}

        # ---- LOAD F: CAP HIT + DISPUTED (shows cap logic + dispute handling) ----
        f_arr, f_dep = ago(days=6, hours=14), ago(days=6, hours=2)  # 12h dwell -> cap $400 (redline)
        fdl, ffac = self._make_stop(0, "delivery", "atlanta", appt=ago(days=6, hours=14).strftime("%Y-%m-%dT05:00"),
                                    arrived=f_arr, departed=f_dep, notice_status="sent", notice_sent_at=f_arr + timedelta(minutes=45))
        detF = det_for("redline", 2300)
        loadF, _ = self._load("RL-55102", "redline", "Summit Ridge Carriers LLC", 2300,
                              [(fdl, ffac)], {"name": "Tanya Brooks", "phone": "+19095550133"}, "disputed")
        self.pings += make_trail(self.fid, loadF["id"], fdl, f_arr, f_dep)
        loadF["last_ping"] = {"lat": fdl["lat"] + 0.03, "lng": fdl["lng"] + 0.035, "ts": iso(f_dep + timedelta(minutes=15))}
        await self._add_bol(fdl, "RL-55102", "Tanya Brooks", shipper, ffac["name"])
        self._notice_doc(loadF, fdl, f_arr + timedelta(minutes=45), on_time=True)
        sentF = ago(days=6)
        invF, bF = self._invoice(loadF, fdl, detF, "disputed", sent_at=sentF, reminders_paused=True)
        invF["viewed_at"] = iso(ago(days=5, hours=20))
        invF["history"] = [{"at": iso(sentF), "action": "emailed", "to": loadF["broker"]["email"]},
                           {"at": iso(ago(days=4)), "action": "dispute", "note": "Broker says appointment was missed by shipper, reviewing.", "by": "demo"}]

        # fix bol back-reference load_id now that loads exist
        for rec in self.files:
            if rec["kind"] == "bol" and rec.get("load_id") is None:
                for ld in self.loads:
                    if any(rec["id"] == b["file_id"] for s in ld["stops"] for b in s.get("bol", [])):
                        rec["load_id"] = ld["id"]
                        break

    async def commit(self):
        db = self.db
        fleet = {"id": self.fid, "name": "Summit Ridge Carriers (Demo)", "timezone": "America/Chicago",
                 "reply_to_email": DEMO_OWNER_EMAIL, "notice_mode": "auto",
                 "owner_user_id": "demo-owner-pending", "app_url": PREVIEW_URL,
                 "created_at": iso(ago(days=40)), "invoice_seq": self.invoice_seq,
                 "is_demo": True, "demo_version": DEMO_VERSION}
        # preserve an already-claimed owner so a returning reviewer keeps access
        prev = await db.fleets.find_one({"id": self.fid}, {"_id": 0})
        if prev and prev.get("owner_user_id") and prev["owner_user_id"] != "demo-owner-pending":
            fleet["owner_user_id"] = prev["owner_user_id"]
        await db.fleets.update_one({"id": self.fid}, {"$set": fleet}, upsert=True)

        if self.facs:
            await db.facilities.insert_many([dict(f) for f in self.facs.values()])
        bdocs = [v for k, v in self.brokers.items() if k.startswith("_doc_")]
        if bdocs:
            await db.brokers.insert_many([dict(b) for b in bdocs])
        if self.files:
            await db.files.insert_many([dict(f) for f in self.files])
        if self.loads:
            await db.loads.insert_many([dict(l) for l in self.loads])
        if self.invoices:
            await db.invoices.insert_many([dict(i) for i in self.invoices])
        if self.notices:
            await db.notices.insert_many([dict(n) for n in self.notices])
        if self.pings:
            await db.pings.insert_many([dict(p) for p in self.pings])
        if self.payments:
            await db.payment_transactions.insert_many([dict(p) for p in self.payments])

        # owner access: pending invite (claimed on first sign-in) + re-point an existing user
        await db.invites.update_one(
            {"fleet_id": self.fid, "email": DEMO_OWNER_EMAIL},
            {"$set": {"id": _uid(), "fleet_id": self.fid, "email": DEMO_OWNER_EMAIL, "role": "owner",
                      "status": "pending", "invited_by": "demo", "created_at": iso(now_utc()),
                      "email_sent": True, "is_demo": True}}, upsert=True)
        existing = await db.users.find_one({"email": DEMO_OWNER_EMAIL}, {"_id": 0})
        if existing:
            await db.users.update_one({"email": DEMO_OWNER_EMAIL},
                                      {"$set": {"fleet_id": self.fid, "role": "owner"}})
            await db.fleets.update_one({"id": self.fid}, {"$set": {"owner_user_id": existing["user_id"]}})
            await db.invites.update_one({"fleet_id": self.fid, "email": DEMO_OWNER_EMAIL},
                                        {"$set": {"status": "accepted", "accepted_at": iso(now_utc())}})


async def _wipe(db):
    for col in _SCOPED:
        await db[col].delete_many({"fleet_id": DEMO_FLEET_ID})


async def seed_demo(db):
    """Full idempotent rebuild of the demo fleet. Returns a short summary."""
    await _wipe(db)
    s = _Seeder(db)
    await s.build()
    await s.commit()
    return {"fleet_id": DEMO_FLEET_ID, "loads": len(s.loads), "invoices": len(s.invoices),
            "pings": len(s.pings), "files": len(s.files), "version": DEMO_VERSION}


async def ensure_demo(db):
    """Seed on first boot, or rebuild when DEMO_VERSION changes. Safe to call every startup."""
    fleet = await db.fleets.find_one({"id": DEMO_FLEET_ID}, {"_id": 0, "demo_version": 1})
    if fleet and fleet.get("demo_version") == DEMO_VERSION:
        return {"status": "current", "version": DEMO_VERSION}
    res = await seed_demo(db)
    return {"status": "seeded", **res}

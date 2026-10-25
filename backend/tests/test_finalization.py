"""End-to-end tests for load completion + detention billing finalization (in-process, isolated test fleets).

Run: cd /app/backend && python -m pytest -q tests/test_finalization.py
No real email is sent: BILLING_SUBMISSION_MODE defaults to 'simulate'.
"""
import asyncio
import io
import os
import sys
import uuid
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from starlette.datastructures import UploadFile, Headers  # noqa: E402
import server  # noqa: E402
import finalize  # noqa: E402
from core import now_utc, iso, parse  # noqa: E402

P0 = (41.5250, -88.0817)   # pickup
D0 = (34.0922, -117.4350)  # delivery
FAR = 0.05                 # ~5 km offset -> outside the geofence


def run(coro_fn):
    async def wrapper():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        server.db = db
        await asyncio.to_thread(server.init_storage)
        finalize.init(db=db, send_email=server.send_email, EmailError=server.EmailError, EmailTimeout=server.EmailTimeout,
                      store_file=server.store_file, get_object=server.get_object, tz_of=server.tz_of, fmt_local=server.fmt_local,
                      uid=server.uid, token=server.token, evidence_url=server.evidence_url, src_label=lambda x: x or "-",
                      email_re=server.EMAIL_RE, fault_hook=None)
        return await coro_fn(db)
    return asyncio.run(wrapper())


async def make_fleet(db, **extra):
    fid = f"TEST_fin_{uuid.uuid4().hex[:8]}"
    f = {"id": fid, "name": "TEST Finalize Carriers", "timezone": "America/Chicago", "owner_user_id": "test-owner",
         "app_url": "https://example.test", "invoice_seq": 5000, "notice_mode": "auto",
         "legal_name": "Test Finalize Carriers LLC", "remittance_address": "PO Box 1, Joliet, IL 60431",
         "address": "100 Test St, Joliet, IL", "billing_email": "billing@example.test", "mc_number": "MC000000", **extra}
    await db.fleets.insert_one(dict(f))
    return f, {"user_id": "test-owner", "fleet_id": fid, "fleet": f, "role": "owner", "email": "owner@example.test"}


async def make_load(db, f, det=None, terms=None, stops=None, mode="auto", confirm=True):
    lid = str(uuid.uuid4())
    stops = stops or [("pickup", P0), ("delivery", D0)]
    ss = [{"id": str(uuid.uuid4()), "seq": i, "type": t, "facility_id": None, "facility_name": f"TEST {t} {i}",
           "address": f"{i} Test Rd", "appointment": None, "lat": c[0], "lng": c[1], "radius_m": 300, "arrived_at": None,
           "departed_at": None, "arrived_source": None, "departed_source": None, "events": [], "bol": [],
           "notice": {"status": "pending", "due_at": None, "sent_at": None}} for i, (t, c) in enumerate(stops)]
    base_terms = {"billing_company": "Test Broker AP", "ap_email": "ap@example.test", "submission_channel": "email",
                  "payment_terms_days": 30, "payment_terms_start": "invoice_submission",
                  "required_documents": [{"doc": "pod", "stop": "final", "label": "Signed POD"}], "approval_required": False}
    bt = {**base_terms, **(terms or {})}
    load = {"id": lid, "fleet_id": f["id"], "load_number": f"TEST-{lid[:6]}", "broker": {"name": "Test Broker", "email": "broker@example.test"},
            "detention": det if det is not None else {"free_time_hours": 2, "hourly_rate": 75, "billing_increment_minutes": 15,
                                                      "rounding_rule": "completed_increment", "cap_scope": "per_stop",
                                                      "notice_before_expiry_minutes": 30},
            "stops": ss, "driver": {"name": "T"}, "driver_token": uuid.uuid4().hex, "billing_terms": bt,
            "billing_setup": {"mode": mode, **({"confirmed_at": iso(now_utc()), "confirmed_by": "test-owner"} if confirm else {})},
            "status": "planned", "created_at": iso(now_utc())}
    await db.loads.insert_one(dict(load))
    return load


async def ping(load, at, latlng, acc=10):
    return await server.driver_ping(load["driver_token"], server.PingIn(lat=latlng[0], lng=latlng[1], accuracy=acc, ts=iso(at)))


def away(c):
    return (c[0] + FAR, c[1] + FAR)


async def drive(load, base, pickup=(0, 190), delivery=(360, 575)):
    """Minutes after base: pickup 08:00-11:10 (190 min) and delivery 14:00-17:35 relative to an 08:00 base."""
    await ping(load, base + timedelta(minutes=pickup[0]), P0)
    await ping(load, base + timedelta(minutes=pickup[1]), away(P0))
    if delivery:
        await ping(load, base + timedelta(minutes=delivery[0]), D0)
        await ping(load, base + timedelta(minutes=delivery[1]), away(D0))


async def get(db, lid):
    return await db.loads.find_one({"id": lid}, {"_id": 0})


async def invs(db, lid):
    return await db.invoices.find({"load_id": lid, "status": {"$ne": "void"}}, {"_id": 0}).sort("created_at", 1).to_list(20)


async def upload(m, load, stop_id, doc_type="pod"):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (600, 400), (240, 240, 240)).save(b, "JPEG")
    f = UploadFile(file=io.BytesIO(b.getvalue()), filename="pod.jpg", headers=Headers({"content-type": "image/jpeg"}))
    return await server.upload_document(load["id"], stop_id, doc_type, f, m)


def BASE():
    return now_utc() - timedelta(hours=20)


# ------------------------------------------------------------------------------------------------ tests

def test_known_contract_full_flow():
    async def t(db):
        f, m = await make_fleet(db)
        load = await make_load(db, f)
        base = BASE()
        pk, dl = load["stops"][0]["id"], load["stops"][1]["id"]
        # pickup completed while delivery still active
        await ping(load, base, P0)
        await ping(load, base + timedelta(minutes=190), away(P0))
        await ping(load, base + timedelta(minutes=360), D0)
        ld = await get(db, load["id"])
        assert ld["completion"]["transport"]["state"] == "in_progress"
        iv = await invs(db, load["id"])
        assert [(i["stop_id"], i["amount"], i["status"]) for i in iv] == [(pk, 75.0, "ready")]
        assert await db.packets.count_documents({"load_id": load["id"]}) == 0
        # final departure starts finalization immediately (no dashboard, no cron, no End-trip tap)
        await ping(load, base + timedelta(minutes=575), away(D0))
        ld = await get(db, load["id"])
        c = ld["completion"]
        assert c["transport"]["state"] == "completed" and c["last_trigger"] in ("geofence_departure", "document_upload")
        assert c["billing_total"] == 187.5
        assert sorted(i["amount"] for i in await invs(db, load["id"])) == [75.0, 112.5]
        assert c["packet"]["state"] == "draft" and c["submission"]["state"] == "blocked"
        assert any(b["code"] == "document" for b in c["blockers"])
        # POD upload resumes processing without another departure; photo alone is not proof of signature
        r = await upload(m, load, dl)
        assert any("signature" in b["message"] for b in r["completion"]["blockers"])
        fid = (await get(db, load["id"]))["stops"][1]["bol"][0]["file_id"]
        r = await server.verify_signature(load["id"], dl, fid, m)
        ld = await get(db, load["id"])
        assert ld["completion"]["blockers"] == []
        assert ld["completion"]["submission"]["state"] == "accepted" and ld["completion"]["submission"]["simulated"]
        iv = await invs(db, load["id"])
        assert all(i["status"] == "sent" and i["submission_simulated"] for i in iv)
        p = await db.packets.find_one({"load_id": load["id"], "status": "issued"}, {"_id": 0})
        assert p and p["snapshot"]["totals"]["invoiced"] == 187.5 and finalize.verify_packet(p)["state"] == "verified"
        # repeated pings / concurrent cron / refreshes / repeated uploads -> no duplicates
        await asyncio.gather(*[server.process_load(await get(db, load["id"]), f, trigger="cron_recovery") for _ in range(6)],
                             *[ping(load, base + timedelta(minutes=580 + i), away(D0)) for i in range(3)])
        await upload(m, load, dl)
        assert await db.invoices.count_documents({"load_id": load["id"]}) == 2
        assert await db.outbox.count_documents({"load_id": load["id"], "kind": "billing_submission"}) == 1
        assert await db.packets.count_documents({"load_id": load["id"], "status": "issued"}) == 1
        # reminders follow Net 30: first is a due-soon courtesy at day 27, never 'overdue' on day 3
        plan = server.reminder_plan(iv[0])
        assert plan[0]["day"] == 27 and plan[0]["kind"] == "due_soon" and all(r["day"] > 3 for r in plan)
        return True
    assert run(t)


def test_per_load_cap_consistent_everywhere():
    async def t(db):
        f, m = await make_fleet(db)
        load = await make_load(db, f, det={"free_time_hours": 2, "hourly_rate": 75, "billing_increment_minutes": 15,
                                           "rounding_rule": "completed_increment", "cap_amount": 150, "cap_scope": "per_load"},
                               terms={"required_documents": []})
        await drive(load, BASE())
        ld = await get(db, load["id"])
        view = await server.load_view(ld, f)
        iv = await invs(db, load["id"])
        p = await db.packets.find_one({"load_id": load["id"], "status": "issued"}, {"_id": 0})
        assert view["detention_total"] == 150.0
        assert [s["billing"]["amount"] for s in view["stops"]] == [75.0, 75.0]
        assert sorted(i["amount"] for i in iv) == [75.0, 75.0]
        assert p["snapshot"]["totals"]["invoiced"] == 150.0 and p["snapshot"]["totals"]["outstanding"] == 150.0
        # Stripe charges exactly invoice.amount (checkout builds cents from it)
        assert sum(int(round(i["amount"] * 100)) for i in iv) == 15000
        return True
    assert run(t)


def test_previously_submitted_pickup_not_billed_twice_and_correction_versioned():
    async def t(db):
        f, m = await make_fleet(db)
        load = await make_load(db, f, terms={"required_documents": []})
        base = BASE()
        await ping(load, base, P0)
        await ping(load, base + timedelta(minutes=190), away(P0))
        pk_inv = (await invs(db, load["id"]))[0]
        await server.send_invoice(pk_inv["id"], m)  # dispatcher sent the pickup invoice early (simulated)
        sent_at = (await db.invoices.find_one({"id": pk_inv["id"]}))["sent_at"]
        await ping(load, base + timedelta(minutes=360), D0)
        await ping(load, base + timedelta(minutes=575), away(D0))
        p = await db.packets.find_one({"load_id": load["id"], "status": "issued"}, {"_id": 0})
        rows = {i["number"]: i for i in p["snapshot"]["invoices"]}
        assert rows[pk_inv["number"]]["status_label"] == "Previously submitted"
        assert (await db.invoices.find_one({"id": pk_inv["id"]}))["sent_at"] == sent_at
        assert await db.invoices.count_documents({"load_id": load["id"]}) == 2
        # post-issue correction: original PDF + amount preserved; new draft version; pending adjustment only
        pdf_before = p["pdf_sha256"]
        dl = load["stops"][1]["id"]
        await server.adjust_stop(load["id"], dl, server.AdjustIn(departed_at=iso(base + timedelta(minutes=545)),
                                                                 reason="Gate log shows earlier exit"), m)
        p1 = await db.packets.find_one({"id": p["id"]}, {"_id": 0})
        assert p1["status"] == "issued" and p1["pdf_sha256"] == pdf_before and finalize.verify_packet(p1)["state"] == "verified"
        v2 = await db.packets.find_one({"load_id": load["id"], "version": 2}, {"_id": 0})
        assert v2 and v2["status"] == "draft" and v2["supersedes"] == p["id"]
        dinv = await db.invoices.find_one({"load_id": load["id"], "stop_id": dl}, {"_id": 0})
        assert dinv["amount"] == 112.5 and dinv["pending_adjustment"]["new_amount"] == 75.0
        comp = await finalize.source_comparison(p1, await get(db, load["id"]), f)
        assert comp["state"] == "amended"
        adj = await server.adjust_invoice(dinv["id"], server.RefIn(note="Gate log correction"), m)
        assert adj["kind"] == "credit_note" and adj["amount"] == 37.5 and adj["status"] == "credit"
        return True
    assert run(t)


def test_late_offline_gps_after_issue_is_supplement():
    async def t(db):
        f, m = await make_fleet(db)
        load = await make_load(db, f, terms={"required_documents": []})
        base = BASE()
        await drive(load, base)
        p = await db.packets.find_one({"load_id": load["id"], "status": "issued"}, {"_id": 0})
        h = p["pdf_sha256"]
        # an offline point recorded inside the evidence window arrives after the packet was issued
        await ping(load, base + timedelta(minutes=580), away(D0))
        p2 = await db.packets.find_one({"id": p["id"]}, {"_id": 0})
        assert p2["pdf_sha256"] == h and finalize.verify_packet(p2)["state"] == "verified"
        assert p2.get("supplements") and p2["supplements"][0]["kind"] == "late_gps"
        assert await db.packets.count_documents({"load_id": load["id"]}) == 1
        inv = (await invs(db, load["id"]))[0]
        ctxv = await server.invoice_context(inv)
        assert server.verify(inv, ctxv[1], ctxv[2], ctxv[3], ctxv[4])["state"] == "verified"
        return True
    assert run(t)


def test_manual_and_tap_departure_share_service():
    async def t(db):
        f, m = await make_fleet(db)
        load = await make_load(db, f, terms={"required_documents": []}, mode="review")
        base = BASE()
        await ping(load, base, P0)
        s0 = load["stops"][0]["id"]
        await server.driver_action(load["driver_token"], s0, "depart", server.PingIn(lat=P0[0], lng=P0[1], accuracy=10))
        assert (await get(db, load["id"]))["completion"]["last_trigger"] == "driver_depart"
        # GPS failed at delivery: dispatcher completes manually with reason; review mode waits for approval
        r = await server.manual_complete(load["id"], server.CompleteIn(reason="Phone died at receiver",
                                                                         arrived_at=iso(now_utc() - timedelta(hours=4)),
                                                                         departed_at=iso(now_utc() - timedelta(minutes=5))), m)
        ld = await get(db, load["id"])
        assert ld["completion"]["transport"]["state"] == "completed"
        assert ld["manual_completion"]["reason"] == "Phone died at receiver"
        assert ld["completion"]["submission"]["state"] == "awaiting_review"
        r = await server.billing_submit(load["id"], m)
        assert r["completion"]["submission"]["state"] == "accepted"
        return True
    assert run(t)


def test_unknown_terms_phone_notice_portal_approval_zero_detention():
    async def t(db):
        f, m = await make_fleet(db)
        # unknown terms: completed, but no amount and a clear corrective action
        a = await make_load(db, f, det={}, terms={"required_documents": [], "payment_terms_days": None, "payment_terms_start": None})
        await drive(a, BASE())
        c = (await get(db, a["id"]))["completion"]
        assert c["transport"]["state"] == "completed" and any(b["code"] == "terms_missing" for b in c["blockers"])
        assert await db.invoices.count_documents({"load_id": a["id"]}) == 0
        # phone notice required: email notice does not satisfy it; a late call is never 'on time'
        b = await make_load(db, f, terms={"required_documents": [], "notice_method": "phone"})
        base = BASE()
        await ping(b, base, P0)
        ob = finalize.obligations(await get(db, b["id"]), server.compute_load_billing(await get(db, b["id"])),
                                  finalize.transport_state(await get(db, b["id"])), f)
        n = next(o for o in ob if o["kind"] == "notice_phone")
        assert n["status"] in ("missed", "pending")
        await server.record_notice(b["id"], b["stops"][0]["id"], server.NoticeRecordIn(
            method="phone", at=iso(base + timedelta(minutes=150)), to="Broker desk"), m)
        ob = finalize.obligations(await get(db, b["id"]), server.compute_load_billing(await get(db, b["id"])),
                                  finalize.transport_state(await get(db, b["id"])), f)
        assert next(o for o in ob if o["kind"] == "notice_phone")["status"] == "late"
        # portal-only billing: packet issued, invoices NOT marked submitted until the portal upload is recorded
        c_ = await make_load(db, f, terms={"required_documents": [], "submission_channel": "portal", "portal_url": "https://portal.example.test"})
        await drive(c_, BASE())
        ld = await get(db, c_["id"])
        assert ld["completion"]["submission"]["state"] == "awaiting_portal"
        assert all(i["status"] == "ready" for i in await invs(db, c_["id"]))
        r = await server.billing_portal_done(c_["id"], server.RefIn(reference="PORTAL-123"), m)
        assert r["completion"]["submission"]["state"] == "accepted"
        assert all(i["status"] == "sent" for i in await invs(db, c_["id"]))
        # approval required and missing -> blocked; recording it resumes
        d = await make_load(db, f, terms={"required_documents": [], "approval_required": True, "approval_method": "email"})
        await drive(d, BASE())
        assert any(x["code"] == "approval" for x in (await get(db, d["id"]))["completion"]["blockers"])
        await server.record_approval(d["id"], server.ApprovalIn(method="email", approver="J. Smith", reference="Re: detention",
                                                                 at=iso(BASE() + timedelta(hours=2))), m)
        assert (await get(db, d["id"]))["completion"]["submission"]["state"] == "accepted"
        # zero detention: completed, summary saved, no $0 invoice, nothing submitted
        e = await make_load(db, f, terms={"required_documents": []})
        await drive(e, BASE(), pickup=(0, 60), delivery=(300, 360))
        ce = (await get(db, e["id"]))["completion"]
        assert ce["transport"]["state"] == "completed" and ce["submission"]["state"] == "not_needed" and ce["summary"]["text"]
        assert await db.invoices.count_documents({"load_id": e["id"]}) == 0
        return True
    assert run(t)


def test_outbox_crash_timeout_and_failure():
    async def t(db):
        f, m = await make_fleet(db)
        load = await make_load(db, f, terms={"required_documents": []}, mode="review")
        await drive(load, BASE())

        async def timeout(job):
            raise server.EmailTimeout("provider timeout")
        finalize.ctx.fault_hook = timeout
        r = await server.billing_submit(load["id"], m)
        assert r["completion"]["submission"]["state"] == "uncertain"
        assert all(i["status"] == "ready" for i in await invs(db, load["id"]))  # not submitted before acceptance
        finalize.ctx.fault_hook = None
        await finalize.run_outbox()  # uncertain jobs are never blindly resent
        j = await db.outbox.find_one({"load_id": load["id"]}, {"_id": 0})
        assert j["status"] == "uncertain" and j["attempts"] == 1
        r = await server.outbox_resolve(j["id"], server.ResolveIn(action="mark_accepted", reference="AP confirmed by phone"), m)
        assert r["completion"]["submission"]["state"] == "accepted"
        # crash mid-send: an expired 'sending' claim becomes uncertain on recovery
        l2 = await make_load(db, f, terms={"required_documents": []}, mode="review")
        await drive(l2, BASE())
        p = await db.packets.find_one({"load_id": l2["id"]}, {"_id": 0})
        p = await finalize.issue_packet(p["id"], f, "test")
        job = await finalize.enqueue("billing_submission", await get(db, l2["id"]), f, p, "ap@example.test", "s", "<p>x</p>")
        await db.outbox.update_one({"id": job["id"]}, {"$set": {"status": "sending", "claimed_until": iso(now_utc() - timedelta(seconds=1)), "attempts": 1}})
        await finalize.run_outbox()
        assert (await db.outbox.find_one({"id": job["id"]}))["status"] == "uncertain"
        # definite provider failure -> retry scheduled, then failed after max attempts
        l3 = await make_load(db, f, terms={"required_documents": []}, mode="review")
        await drive(l3, BASE())

        async def fail(job):
            raise server.EmailError("Failed to send email")
        finalize.ctx.fault_hook = fail
        await server.billing_submit(l3["id"], m)
        j3 = await db.outbox.find_one({"load_id": l3["id"]}, {"_id": 0})
        assert j3["status"] == "pending" and j3["attempts"] == 1
        for _ in range(3):
            await db.outbox.update_one({"id": j3["id"], "status": "pending"}, {"$set": {"next_attempt_at": iso(now_utc())}})
            await finalize.run_outbox()
        assert (await db.outbox.find_one({"id": j3["id"]}))["status"] == "failed"
        finalize.ctx.fault_hook = None
        assert await db.outbox.count_documents({"load_id": l3["id"]}) == 1
        return True
    assert run(t)


def test_pdf_long_clause_multistop_exhibits(tmp_path=None):
    async def t(db):
        f, m = await make_fleet(db, address="Suite 1200, " + "Very Long Industrial Parkway Name " * 4 + ", Joliet, IL 60431")
        clause = ("Detention will be paid at the stated hourly rate after free time, billed in completed increments, provided "
                  "the carrier notifies the broker in writing before free time expires and submits signed paperwork. ") * 40
        stops = [("pickup", P0), ("pickup", (41.6, -88.1)), ("delivery", (40.0, -100.0)), ("delivery", D0)]
        load = await make_load(db, f, terms={"required_documents": [{"doc": "pod", "stop": "delivery"}]}, stops=stops, mode="review")
        await db.loads.update_one({"id": load["id"]}, {"$set": {"detention.clause_text": clause}})
        load = await get(db, load["id"])
        base = BASE()
        for i, s in enumerate(load["stops"]):
            c = (s["lat"], s["lng"])
            await ping(load, base + timedelta(minutes=i * 240), c)
            await ping(load, base + timedelta(minutes=i * 240 + 200), away(c))
        for s in load["stops"][2:]:
            await upload(m, load, s["id"])
        p = await db.packets.find_one({"load_id": load["id"]}, {"_id": 0}, sort=[("version", -1)])
        rec = await db.files.find_one({"id": p["pdf_file_id"]}, {"_id": 0})
        data, _ = await asyncio.to_thread(server.get_object, rec["storage_path"])
        assert data[:4] == b"%PDF" and data.count(b"/Type /Page") >= 6
        out = "/app/tests/artifacts"
        os.makedirs(out, exist_ok=True)
        open(f"{out}/sample_billing_packet.pdf", "wb").write(data)
        assert len(p["snapshot"]["exhibits"]) == 2 and len(p["snapshot"]["invoices"]) == 4
        return True
    assert run(t)


@pytest.fixture(scope="session", autouse=True)
def cleanup():
    yield

    async def c(db):
        ids = [f["id"] async for f in db.fleets.find({"id": {"$regex": "^TEST_fin_"}}, {"id": 1})]
        for coll in ("loads", "invoices", "packets", "outbox", "pings", "notices", "files"):
            await db[coll].delete_many({"fleet_id": {"$in": ids}})
        await db.fleets.delete_many({"id": {"$in": ids}})
    run(c)

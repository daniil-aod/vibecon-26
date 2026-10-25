# Detention billing packet / finalization via real HTTP (public URL) as Clerk QA user in fleet 'TEST_QA Haulers'.
# Covers: billing profile, geofence pings -> invoices/packet/submission, docs + signature, review submit, idempotency,
# per-load cap, portal-only, unknown terms, manual completion, packet PDF security. All submissions SIMULATED.
import os
import sys
import uuid
import pytest
import requests
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/tests")
from clerk_helper import get_or_create_user, session_jwt  # noqa: E402


def _base():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        for line in open("/app/web/.env"):
            if line.startswith("REACT_APP_BACKEND_URL="):
                url = line.split("=", 1)[1].strip()
    return url.rstrip("/")


BASE_URL = _base()
EMAIL = "dockqa+clerk_test@example.com"
SINK = "delivered@resend.dev"
P0 = (41.5250, -88.0817)
D0 = (34.0922, -117.4350)
FAR = 0.05
CREATED = []


@pytest.fixture(scope="module")
def client():
    uid = get_or_create_user(EMAIL)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {session_jwt(uid)}", "Content-Type": "application/json"})
    me = s.get(f"{BASE_URL}/api/me", params={"origin": BASE_URL}).json()
    assert me.get("fleet"), me
    yield s
    for lid in CREATED:
        s.delete(f"{BASE_URL}/api/loads/{lid}")


def make_load(client, tag, det=None, terms=None, mode="review", confirm=True):
    u = uuid.uuid4().hex[:6]
    bt = {"submission_channel": "email", "ap_email": "ap@example.test", "payment_terms_days": 30,
          "payment_terms_start": "invoice_submission", "approval_required": False,
          "required_documents": [{"doc": "pod", "stop": "final"}], **(terms or {})}
    d = {"free_time_hours": 2, "hourly_rate": 75, "billing_increment_minutes": 15, "rounding_rule": "completed_increment"}
    if det is not None:
        d = det
    body = {"load_number": f"TEST-{tag}-{u}", "broker": {"name": "TEST QA Broker", "email": SINK}, "detention": d,
            "stops": [{"type": "pickup", "facility_name": f"TEST PU {tag} {u}", "address": f"{u} Pickup Rd, Joliet, IL",
                       "lat": P0[0], "lng": P0[1]},
                      {"type": "delivery", "facility_name": f"TEST DL {tag} {u}", "address": f"{u} Delivery Rd, Fontana, CA",
                       "lat": D0[0], "lng": D0[1]}],
            "driver": {"name": "QA Driver", "phone": "3125550100", "email": ""},
            "billing_terms": bt, "billing_mode": mode, "confirm_billing": confirm}
    r = client.post(f"{BASE_URL}/api/loads", json=body)
    assert r.status_code == 200, r.text
    ld = r.json()
    CREATED.append(ld["id"])
    return ld


def ping(tok, lat, lng, ts):
    r = requests.post(f"{BASE_URL}/api/driver/{tok}/ping", json={"lat": lat, "lng": lng, "accuracy": 20, "ts": ts.isoformat()})
    assert r.status_code == 200, r.text
    return r.json()


T0 = datetime.now(timezone.utc) - timedelta(hours=20)


def drive(tok, upto=4):
    out = []
    seq = [(P0[0], P0[1], 0), (P0[0] + FAR, P0[1], 190), (D0[0], D0[1], 360), (D0[0] + FAR, D0[1], 575)]
    for lat, lng, mins in seq[:upto]:
        out.append(ping(tok, lat, lng, T0 + timedelta(minutes=mins)))
    return out


def billing(client, lid):
    r = client.get(f"{BASE_URL}/api/loads/{lid}/billing")
    assert r.status_code == 200, r.text
    return r.json()


# ---- Billing profile
def test_billing_profile(client):
    r = client.patch(f"{BASE_URL}/api/fleet/billing-profile", json={"legal_name": "TEST QA Haulers LLC",
                                                                  "remittance_address": "PO Box 77, Joliet, IL 60431"})
    assert r.status_code == 200, r.text
    assert r.json()["legal_name"] == "TEST QA Haulers LLC"


@pytest.fixture(scope="module")
def main_load(client):
    return make_load(client, "MAIN")


# ---- Main driver workflow
class TestMainFlow:
    def test_pickup_invoice_before_delivery(self, client, main_load):
        res = drive(main_load["driver_token"], upto=2)
        assert res[0]["event"] == "arrived" and res[1]["event"] == "departed"
        b = billing(client, main_load["id"])
        assert b["transport"]["state"] == "in_progress"
        invs = [i for i in b["invoices"] if i["status"] != "void"]
        assert len(invs) == 1 and invs[0]["amount"] == 75 and invs[0]["status"] == "ready"

    def test_final_departure_finalizes(self, client, main_load):
        tok = main_load["driver_token"]
        ping(tok, D0[0], D0[1], T0 + timedelta(minutes=360))
        last = ping(tok, D0[0] + FAR, D0[1], T0 + timedelta(minutes=575))
        assert last["event"] == "departed"
        assert last["transport_completed"] is True
        assert "documents_needed" in last and len(last["documents_needed"]) == 1
        b = billing(client, main_load["id"])
        c = b["completion"]
        assert b["transport"]["state"] == "completed"
        assert c["packet"]["state"] == "draft" and c["packet"]["version"] == 1
        assert c["submission"]["state"] == "blocked"
        assert b["billing"]["total"] == 187.5
        assert any(x["code"] == "document" and "not uploaded" in x["message"] for x in c["blockers"]), c["blockers"]

    def test_draft_not_public(self, client, main_load):
        b = billing(client, main_load["id"])
        pid = b["completion"]["packet"]["packet_id"]
        assert requests.get(f"{BASE_URL}/api/packets/{pid}/pdf").status_code in (401, 403)
        r = client.get(f"{BASE_URL}/api/packets/{pid}/pdf")
        assert r.status_code == 200 and r.content[:4] == b"%PDF"

    def test_upload_verify_submit(self, client, main_load):
        b = billing(client, main_load["id"])
        sid = sorted(main_load["stops"], key=lambda s: s["seq"])[-1]["id"]
        png = open("/app/tests/artifacts/pod.png", "rb").read() if os.path.exists("/app/tests/artifacts/pod.png") else None
        if png is None:
            import base64
            png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        h = {"Authorization": client.headers["Authorization"]}
        r = requests.post(f"{BASE_URL}/api/loads/{main_load['id']}/stops/{sid}/documents", params={"doc_type": "pod"},
                          files={"file": ("pod.png", png, "image/png")}, headers=h)
        assert r.status_code == 200, r.text
        b = r.json()
        msgs = [x["message"] for x in b["completion"]["blockers"]]
        assert any("signature not yet confirmed" in m for m in msgs), msgs
        st = next(s for s in client.get(f"{BASE_URL}/api/loads/{main_load['id']}").json()["stops"] if s["id"] == sid)
        fid = st["bol"][-1]["file_id"]
        r = client.post(f"{BASE_URL}/api/loads/{main_load['id']}/stops/{sid}/documents/{fid}/verify-signature")
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["completion"]["blockers"] == []
        assert b["completion"]["submission"]["state"] == "awaiting_review"
        r = client.post(f"{BASE_URL}/api/loads/{main_load['id']}/billing/submit")
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["completion"]["submission"]["state"] == "accepted"
        assert b["completion"]["submission"]["simulated"] is True
        assert b["completion"]["packet"]["state"] == "issued"
        live = [i for i in b["invoices"] if i["status"] != "void"]
        assert len(live) == 2 and all(i["status"] == "sent" for i in live)
        # issued packet public link works
        p = next(x for x in b["packets"] if x["status"] == "issued")
        assert p.get("public_token")
        r = requests.get(f"{BASE_URL}/api/public/packets/{p['public_token']}/pdf")
        assert r.status_code == 200 and r.content[:4] == b"%PDF"
        with open("/app/tests/artifacts/qa_packet_v1.pdf", "wb") as f:
            f.write(r.content)

    def test_double_submit_rejected(self, client, main_load):
        r = client.post(f"{BASE_URL}/api/loads/{main_load['id']}/billing/submit")
        assert r.status_code == 400

    def test_idempotent_reprocessing(self, client, main_load):
        tok = main_load["driver_token"]
        for _ in range(3):
            ping(tok, D0[0] + FAR, D0[1], T0 + timedelta(minutes=575))
            client.get(f"{BASE_URL}/api/loads/{main_load['id']}")
        b = billing(client, main_load["id"])
        assert len([i for i in b["invoices"] if not i.get("adjusts_invoice_id")]) == 2
        assert len([j for j in b["outbox"] if j["kind"] == "billing_submission"]) == 1
        assert len([p for p in b["packets"]]) == 1, [(p["version"], p["status"]) for p in b["packets"]]


# ---- Per-load cap
def test_per_load_cap(client):
    ld = make_load(client, "CAP", det={"free_time_hours": 2, "hourly_rate": 75, "billing_increment_minutes": 15,
                                        "rounding_rule": "completed_increment", "cap_amount": 150, "cap_scope": "per_load"})
    drive(ld["driver_token"])
    v = client.get(f"{BASE_URL}/api/loads/{ld['id']}").json()
    assert v["detention_total"] == 150, v["detention_total"]
    amts = sorted(i["amount"] for i in v["invoices"] if i["status"] != "void")
    assert amts == [75, 75], amts


# ---- Portal-only, auto mode
def test_portal_only(client):
    ld = make_load(client, "PORTAL", terms={"submission_channel": "portal", "portal_url": "https://portal.example.test",
                                             "ap_email": None, "required_documents": []}, mode="auto")
    drive(ld["driver_token"])
    b = billing(client, ld["id"])
    assert b["completion"]["submission"]["state"] == "awaiting_portal", b["completion"]
    assert all(i["status"] == "ready" for i in b["invoices"] if i["status"] != "void")
    r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/billing/portal-submitted", json={"reference": ""})
    assert r.status_code == 400
    r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/billing/portal-submitted", json={"reference": "PORTAL-123"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["completion"]["submission"]["state"] == "accepted"
    assert all(i["status"] == "sent" for i in b["invoices"] if i["status"] != "void")
    r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/billing/portal-submitted", json={"reference": "PORTAL-456"})
    assert r.status_code == 400


# ---- Unknown terms
def test_unknown_terms(client):
    ld = make_load(client, "UNK", det={"billing_increment_minutes": 15})
    drive(ld["driver_token"])
    b = billing(client, ld["id"])
    assert b["transport"]["state"] == "completed"
    tm = [x for x in b["completion"]["blockers"] if x["code"] == "terms_missing"]
    assert tm and tm[0]["action"]
    assert [i for i in b["invoices"] if i["status"] != "void"] == []


# ---- Manual completion
def test_manual_completion(client):
    ld = make_load(client, "MAN")
    drive(ld["driver_token"], upto=3)
    r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/complete", json={"reason": ""})
    assert r.status_code in (400, 422)
    dep = (T0 + timedelta(minutes=575)).isoformat()
    r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/complete", json={"reason": "TEST phone died", "departed_at": dep})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["transport"]["state"] == "completed"
    assert (b["transport"].get("manual") or {}).get("reason") == "TEST phone died"


# ---- Security
def test_public_random_404():
    assert requests.get(f"{BASE_URL}/api/public/packets/{uuid.uuid4().hex}/pdf").status_code == 404


def test_billing_no_auth():
    assert requests.get(f"{BASE_URL}/api/loads/{uuid.uuid4()}/billing").status_code in (401, 403)

# Iteration 13 retest: packet-billed invoice Send guard, early pickup send to AP, correction_pending blocker +
# supplement/credit note + revised packet v2, None->'' no-op edit keeps confirmation, reminder plan. Public URL, Clerk QA user.
import hashlib
import os
import sys
from datetime import datetime, timedelta

import pytest
import requests

sys.path.insert(0, os.path.dirname(__file__))
import test_billing_packet_http as t  # noqa: E402
from test_billing_packet_http import BASE_URL, make_load, drive, billing, ping, D0, FAR, T0  # noqa: E402,F401

client = t.client


def _png():
    p = "/app/tests/artifacts/pod.png"
    if os.path.exists(p):
        return open(p, "rb").read()
    import base64
    return base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def complete_and_submit(client, ld):
    drive(ld["driver_token"])
    sid = sorted(ld["stops"], key=lambda s: s["seq"])[-1]["id"]
    h = {"Authorization": client.headers["Authorization"]}
    r = requests.post(f"{BASE_URL}/api/loads/{ld['id']}/stops/{sid}/documents", params={"doc_type": "pod"},
                      files={"file": ("pod.png", _png(), "image/png")}, headers=h)
    assert r.status_code == 200, r.text
    st = next(s for s in client.get(f"{BASE_URL}/api/loads/{ld['id']}").json()["stops"] if s["id"] == sid)
    fid = st["bol"][-1]["file_id"]
    assert client.post(f"{BASE_URL}/api/loads/{ld['id']}/stops/{sid}/documents/{fid}/verify-signature").status_code == 200
    r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/billing/submit")
    assert r.status_code == 200, r.text
    assert r.json()["completion"]["submission"]["state"] == "accepted"
    return sid


def shift_departure(client, ld, sid, minutes):
    la = client.get(f"{BASE_URL}/api/loads/{ld['id']}").json()
    st = next(s for s in la["stops"] if s["id"] == sid)
    dep = datetime.fromisoformat(st["departed_at"].replace("Z", "+00:00")) + timedelta(minutes=minutes)
    r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/stops/{sid}/adjust", json={"departed_at": dep.isoformat(), "reason": "TEST correction"})
    assert r.status_code == 200, r.text


# ---- Bug 1: invoice send guard
class TestSendGuard:
    def test_early_pickup_send_goes_to_ap(self, client):
        ld = make_load(client, "EARLY")
        drive(ld["driver_token"], upto=2)
        inv = next(i for i in billing(client, ld["id"])["invoices"] if i["status"] == "ready")
        r = client.post(f"{BASE_URL}/api/invoices/{inv['id']}/send")
        assert r.status_code == 200, r.text
        d = r.json()
        d = d.get("invoice", d)
        assert d["status"] == "sent"
        to = [h.get("to") for h in d.get("history", []) if h.get("action") == "emailed"]
        assert to and to[-1] == "ap@example.test", to

    def test_early_send_unconfirmed_rejected(self, client):
        ld = make_load(client, "EARLYNC", confirm=False)
        drive(ld["driver_token"], upto=2)
        inv = next(i for i in billing(client, ld["id"])["invoices"] if i["status"] == "ready")
        r = client.post(f"{BASE_URL}/api/invoices/{inv['id']}/send")
        assert r.status_code == 400, r.text
        assert "Confirm" in r.json()["detail"]

    def test_completed_packet_load_send_rejected(self, client):
        ld = make_load(client, "DONE")
        drive(ld["driver_token"])
        b = billing(client, ld["id"])
        assert b["completion"]["submission"]["state"] == "blocked"
        ready = [i for i in b["invoices"] if i["status"] == "ready"]
        assert len(ready) == 2
        for i in ready:
            r = client.post(f"{BASE_URL}/api/invoices/{i['id']}/send")
            assert r.status_code == 400 and "Completion & billing" in r.json()["detail"], r.text
        lst = client.get(f"{BASE_URL}/api/invoices").json()
        mine = [i for i in lst if i["load_id"] == ld["id"]]
        assert mine and all(i["packet_billed"] is True for i in mine)
        assert all(i["status"] == "ready" for i in billing(client, ld["id"])["invoices"] if i["status"] != "void")


# ---- Bug 2: correction flow before revised packet
class TestCorrectionFlow:
    @pytest.fixture(scope="class")
    def sub_load(self, client):
        ld = make_load(client, "CORR")
        sid = complete_and_submit(client, ld)
        return ld, sid

    def test_supplement_then_revision(self, client, sub_load):
        ld, sid = sub_load
        b = billing(client, ld["id"])
        v1 = next(p for p in b["packets"] if p["version"] == 1)
        v1_pdf = client.get(f"{BASE_URL}/api/packets/{v1['id']}/pdf").content
        shift_departure(client, ld, sid, 30)
        b = billing(client, ld["id"])
        c = b["completion"]
        codes = [x["code"] for x in c["blockers"]]
        assert "correction_pending" in codes, codes
        assert c["submission"]["state"] != "revision_review", c["submission"]
        assert b["billing"]["total"] == 225
        pend = [i for i in b["invoices"] if i.get("pending_adjustment")]
        assert len(pend) == 1 and pend[0]["pending_adjustment"]["delta"] == 37.5
        r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/billing/submit")
        assert r.status_code == 400, r.text
        r = client.post(f"{BASE_URL}/api/invoices/{pend[0]['id']}/adjust", json={"note": "  "})
        assert r.status_code == 400
        r = client.post(f"{BASE_URL}/api/invoices/{pend[0]['id']}/adjust", json={"note": "TEST longer delivery wait"})
        assert r.status_code == 200, r.text
        sup = r.json()
        assert sup["number"] == pend[0]["number"] + "-A1" and sup["status"] == "ready" and sup["amount"] == 37.5
        assert sup["kind"] == "supplement"
        b = billing(client, ld["id"])
        c = b["completion"]
        assert c["blockers"] == [], c["blockers"]
        assert c["submission"]["state"] == "revision_review", c["submission"]
        assert "simulated" not in c["submission"] or not c["submission"].get("simulated")
        r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/billing/submit")
        assert r.status_code == 200, r.text
        b = r.json()
        st = {p["version"]: p["status"] for p in b["packets"]}
        assert st == {1: "superseded", 2: "issued"}, st
        assert b["completion"]["submission"]["state"] == "accepted"
        assert next(i for i in b["invoices"] if i["id"] == sup["id"])["status"] == "sent"
        assert hashlib.sha256(client.get(f"{BASE_URL}/api/packets/{v1['id']}/pdf").content).hexdigest() == hashlib.sha256(v1_pdf).hexdigest()
        TestCorrectionFlow.v2_id = next(p["id"] for p in b["packets"] if p["version"] == 2)

    def test_v2_totals_match(self, client, sub_load):
        from pymongo import MongoClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        p = db.packets.find_one({"id": TestCorrectionFlow.v2_id}, {"_id": 0, "snapshot": 1})
        tot = p["snapshot"]["totals"]
        print("v2 totals", tot, [(i["number"], i["status_label"], i["amount"]) for i in p["snapshot"]["invoices"]])
        inv_sum = round(sum(i["amount"] for i in p["snapshot"]["invoices"] if i.get("kind") != "credit_note"
                            and "Credit" not in i.get("status_label", "")), 2)
        assert inv_sum == 225, inv_sum
        vals = [v for k, v in tot.items() if isinstance(v, (int, float)) and ("invoiced" in k or "detention" in k or k == "total")]
        assert vals and all(v == 225 for v in vals), tot

    def test_credit_note_on_decrease(self, client, sub_load):
        ld, sid = sub_load
        shift_departure(client, ld, sid, -60)
        b = billing(client, ld["id"])
        assert b["billing"]["total"] == 150
        assert "correction_pending" in [x["code"] for x in b["completion"]["blockers"]]
        pend = [i for i in b["invoices"] if i.get("pending_adjustment")]
        assert len(pend) == 1 and pend[0]["pending_adjustment"]["delta"] == -75, pend
        r = client.post(f"{BASE_URL}/api/invoices/{pend[0]['id']}/adjust", json={"note": "TEST shorter"})
        assert r.status_code == 200, r.text
        cn = r.json()
        assert cn["kind"] == "credit_note" and cn["amount"] == 75 and cn["number"].endswith("-A2")
        b = billing(client, ld["id"])
        assert b["completion"]["blockers"] == [] and b["completion"]["submission"]["state"] == "revision_review"


# ---- Minor: None -> '' no-op edit keeps confirmation
def test_empty_string_put_keeps_confirmation(client):
    ld = make_load(client, "EDIT")
    g = client.get(f"{BASE_URL}/api/loads/{ld['id']}").json()
    body = {k: g.get(k) for k in ("load_number", "broker", "detention", "driver", "billing_terms", "refs", "term_sources", "term_refs")}
    body["stops"] = [{k: st.get(k) for k in ("id", "type", "facility_name", "address", "appointment", "lat", "lng", "radius_m")} for st in g["stops"]]
    body["billing_mode"] = "review"
    body["confirm_billing"] = False
    body["billing_terms"] = {**body["billing_terms"], "billing_company": "", "portal_url": "", "billing_address": "", "notice_recipient": ""}
    r = client.put(f"{BASE_URL}/api/loads/{ld['id']}", json=body)
    assert r.status_code == 200, r.text
    assert (r.json().get("billing_setup") or {}).get("confirmed_at")
    # real change still drops confirmation
    body["billing_terms"] = {**body["billing_terms"], "ap_email": "other-ap@example.test"}
    r = client.put(f"{BASE_URL}/api/loads/{ld['id']}", json=body)
    assert not (r.json().get("billing_setup") or {}).get("confirmed_at")


def test_reminder_plan_labels(client):
    lst = client.get(f"{BASE_URL}/api/invoices").json()
    plans = [p["label"] + f" day {p['day']}" for i in lst if i["status"] == "sent" for p in i["reminder_plan"]]
    assert any(x.startswith("Upcoming due date day 27") for x in plans), plans[:10]

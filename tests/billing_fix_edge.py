# Iteration 13 edge probes: v3 after credit note totals; early-sent pickup in v1 snapshot; early send without broker email.
import os
import sys
sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, "/app/tests")
import requests  # noqa: E402
from pymongo import MongoClient  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
import test_billing_packet_http as t  # noqa: E402
import test_billing_fixes_http as f  # noqa: E402
from clerk_helper import get_or_create_user, session_jwt  # noqa: E402

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
B = t.BASE_URL
s = requests.Session()
s.headers.update({"Authorization": f"Bearer {session_jwt(get_or_create_user(t.EMAIL))}", "Content-Type": "application/json"})
ids = []
try:
    # A: credit note then v3
    ld = t.make_load(s, "CN"); ids.append(ld["id"])
    sid = f.complete_and_submit(s, ld)
    f.shift_departure(s, ld, sid, -60)
    inv = next(i for i in t.billing(s, ld["id"])["invoices"] if i.get("pending_adjustment"))
    cn = s.post(f"{B}/api/invoices/{inv['id']}/adjust", json={"note": "TEST shorter"}).json()
    print("credit note", cn["number"], cn["kind"], cn["amount"], cn["status"])
    r = s.post(f"{B}/api/loads/{ld['id']}/billing/submit")
    print("v2 submit", r.status_code, r.text[:200] if r.status_code != 200 else "")
    if r.status_code == 200:
        b = r.json()
        print(" packets", [(p["version"], p["status"]) for p in b["packets"]], "sub", b["completion"]["submission"].get("state"),
              "payment", b["completion"].get("payment"))
        p = db.packets.find_one({"load_id": ld["id"], "status": "issued"}, {"_id": 0, "snapshot": 1})
        print(" totals", p["snapshot"]["totals"], [(i["number"], i["status_label"], i["amount"]) for i in p["snapshot"]["invoices"]])
        print(" invoices", [(i["number"], i["status"], i["amount"]) for i in b["invoices"]])
    # B: early pickup send then complete -> v1 snapshot
    ld = t.make_load(s, "EARLYV1"); ids.append(ld["id"])
    t.drive(ld["driver_token"], upto=2)
    pu = next(i for i in t.billing(s, ld["id"])["invoices"] if i["status"] == "ready")
    print("early send", s.post(f"{B}/api/invoices/{pu['id']}/send").status_code)
    t.drive(ld["driver_token"])
    b = t.billing(s, ld["id"])
    p = db.packets.find_one({"id": b["completion"]["packet"]["packet_id"]}, {"_id": 0, "snapshot": 1})
    print(" v1 draft invoices", [(i["number"], i["status_label"], i["amount"]) for i in p["snapshot"]["invoices"]], p["snapshot"]["totals"])
    # C: early send, AP email confirmed but broker has no email
    body_broker = {"name": "TEST NoEmail Broker", "email": ""}
    ld = t.make_load(s, "NOBRK"); ids.append(ld["id"])
    g = s.get(f"{B}/api/loads/{ld['id']}").json()
    db.loads.update_one({"id": ld["id"]}, {"$set": {"broker.email": ""}})
    t.drive(ld["driver_token"], upto=2)
    pu = next(i for i in t.billing(s, ld["id"])["invoices"] if i["status"] == "ready")
    r = s.post(f"{B}/api/invoices/{pu['id']}/send")
    print("early send no broker email (AP confirmed):", r.status_code, r.text[:150])
finally:
    for i in ids:
        s.delete(f"{B}/api/loads/{i}")

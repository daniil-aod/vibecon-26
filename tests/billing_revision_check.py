# Revision follow-up: inspect v2 snapshot, issue correction, see whether a v3 packet picks up the supplemental invoice.
import os
import sys
sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, "/app/tests")
import requests  # noqa: E402
from pymongo import MongoClient  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
import test_billing_packet_http as t  # noqa: E402
from clerk_helper import get_or_create_user, session_jwt  # noqa: E402

load_dotenv("/app/backend/.env")
B = t.BASE_URL
A = sys.argv[1]
s = requests.Session()
s.headers.update({"Authorization": f"Bearer {session_jwt(get_or_create_user(t.EMAIL))}", "Content-Type": "application/json"})
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
for p in db.packets.find({"load_id": A}).sort("version", 1):
    sn = p["snapshot"]
    print("v", p["version"], p["status"], "totals", sn["totals"], "invoices", [(i["number"], i["status_label"], i["amount"]) for i in sn["invoices"]])
inv = db.invoices.find_one({"load_id": A, "pending_adjustment": {"$exists": True}}, {"_id": 0})
r = s.post(f"{B}/api/invoices/{inv['id']}/adjust", json={"note": "TEST longer delivery wait"})
print("adjust", r.status_code, r.json().get("number"), r.json().get("amount"), r.json().get("status"))
bb = s.get(f"{B}/api/loads/{A}/billing").json()
print("before reload: sub", bb["completion"]["submission"].get("state"), "packets", [(p["version"], p["status"]) for p in bb["packets"]])
s.get(f"{B}/api/loads/{A}")
bb = s.get(f"{B}/api/loads/{A}/billing").json()
print("after reload: sub", bb["completion"]["submission"].get("state"), "packets", [(p["version"], p["status"]) for p in bb["packets"]],
      "blockers", [x["code"] for x in bb["completion"]["blockers"]])
print("invoices", [(i["number"], i["status"], i["amount"]) for i in bb["invoices"]])
lv = s.get(f"{B}/api/loads/{A}").json()
print("load detention_total", lv["detention_total"], "status", lv["status"])

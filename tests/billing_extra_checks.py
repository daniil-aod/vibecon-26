# Extra checks: edit-terms confirmation persistence, revision after submission, demo fleet states (read-only), regression pages.
import os
import sys
from datetime import timedelta
sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, "/app/tests")
import requests  # noqa: E402
from pymongo import MongoClient  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
import test_billing_packet_http as t  # noqa: E402
from clerk_helper import get_or_create_user, session_jwt  # noqa: E402

load_dotenv("/app/backend/.env")
B = t.BASE_URL
s = requests.Session()
s.headers.update({"Authorization": f"Bearer {session_jwt(get_or_create_user(t.EMAIL))}", "Content-Type": "application/json"})
M = sys.argv[1]
A = sys.argv[2]

print("== M blockers after editing billing company:", [x["code"] for x in s.get(f"{B}/api/loads/{M}/billing").json()["completion"]["blockers"]])

# no-change PUT keeps confirmation
ld = t.make_load(s, "EDIT")
g = s.get(f"{B}/api/loads/{ld['id']}").json()
body = {k: g.get(k) for k in ("load_number", "broker", "detention", "driver", "billing_terms", "refs", "term_sources", "term_refs")}
body["stops"] = [{k: st.get(k) for k in ("id", "type", "facility_name", "address", "appointment", "lat", "lng", "radius_m")} for st in g["stops"]]
body["billing_mode"] = "review"
body["confirm_billing"] = False
r = s.put(f"{B}/api/loads/{ld['id']}", json=body)
print("== no-change PUT", r.status_code, "confirmed_at kept:", bool((r.json().get("billing_setup") or {}).get("confirmed_at")))
# Same but with UI-style empty strings for billing_company/portal_url
body["billing_terms"] = {**body["billing_terms"], "billing_company": "", "portal_url": "", "billing_address": "", "notice_recipient": ""}
r = s.put(f"{B}/api/loads/{ld['id']}", json=body)
print("== empty-string PUT confirmed_at kept:", bool((r.json().get("billing_setup") or {}).get("confirmed_at")))
s.delete(f"{B}/api/loads/{ld['id']}")

# revision after submission on load A: extend delivery departure by 30 min
la = s.get(f"{B}/api/loads/{A}").json()
dl = sorted(la["stops"], key=lambda x: x["seq"])[-1]
new_dep = (t.parse(dl["departed_at"]) if hasattr(t, "parse") else None)
from datetime import datetime  # noqa: E402
dep = datetime.fromisoformat(dl["departed_at"].replace("Z", "+00:00")) + timedelta(minutes=30)
r = s.post(f"{B}/api/loads/{A}/stops/{dl['id']}/adjust", json={"departed_at": dep.isoformat(), "reason": "TEST revision"})
print("== adjust", r.status_code, r.text[:150] if r.status_code != 200 else "")
bb = s.get(f"{B}/api/loads/{A}/billing").json()
c = bb["completion"]
print("== after revision: total", bb["billing"]["total"], "packet", c["packet"], "submission", c["submission"].get("state"),
      "blockers", [x["code"] for x in c["blockers"]])
print("   invoices", [(i["number"], i["status"], i["amount"], i.get("pending_adjustment")) for i in bb["invoices"]])
print("   packets", [(p["version"], p["status"]) for p in bb["packets"]], "source_cmp", bb["source_comparison"].get("state"),
      bb["source_comparison"].get("changed"), "verify", bb["issued_verification"].get("state"))
if c["submission"].get("state") == "revision_review":
    r = s.post(f"{B}/api/loads/{A}/billing/submit")
    print("== revision submit", r.status_code, r.text[:200] if r.status_code != 200 else "")
    if r.status_code == 200:
        bb = r.json()
        print("   sub", bb["completion"]["submission"].get("state"), "packets", [(p["version"], p["status"]) for p in bb["packets"]],
              "outbox", [(j["kind"], j["status"]) for j in bb["outbox"]])

# demo fleet (read-only, DB)
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
demo = db.fleets.find_one({"is_demo": True})
print("== demo fleet", demo and demo.get("name"))
for num in ("EVG-77421", "APX-30277", "APX-30188", "RL-55102", "EVG-77510"):
    l = db.loads.find_one({"fleet_id": demo["id"], "load_number": num}, {"_id": 0, "completion": 1, "id": 1})
    if not l:
        print(num, "MISSING")
        continue
    c = l.get("completion") or {}
    invs = list(db.invoices.find({"load_id": l["id"]}, {"_id": 0, "status": 1, "amount": 1}))
    print(num, "sub:", (c.get("submission") or {}).get("state"), "sim:", (c.get("submission") or {}).get("simulated"),
          "err:", (c.get("submission") or {}).get("error"), "packet:", (c.get("packet") or {}).get("state"),
          "blockers:", [b["code"] + ":" + b["message"][:50] for b in c.get("blockers") or []], "invs:", invs)
inv = db.invoices.find_one({"fleet_id": demo["id"], "public_token": {"$ne": None}}, {"_id": 0, "public_token": 1})
r = requests.get(f"{B}/api/public/evidence/{inv['public_token']}")
print("== evidence api", r.status_code, inv["public_token"])

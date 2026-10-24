"""Extra checks: notice ask-mode, cap, evidence changed, reminders via cron, invites -> dispatcher role, isolation."""
import os, sys, time, requests
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "/app/tests")
from smoke_backend import get_user, tok, B, ORIGIN
from pymongo import MongoClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
now = datetime.now(timezone.utc)

own = {"Authorization": "Bearer " + tok(get_user("smoke+clerk_test@example.com"))}
# ask mode
print("ask", requests.patch(f"{B}/fleet", headers=own, json={"notice_mode": "ask"}).status_code)
body = {"load_number": "CAP-TEST", "broker": {"name": "Capstone Logistics", "email": "delivered@resend.dev"},
        "detention": {"free_time_hours": 2, "hourly_rate": 50, "billing_increment_minutes": 15, "cap_amount": 400, "cap_scope": "per_stop", "clause_text": "test clause"},
        "stops": [{"type": "pickup", "facility_name": "Golden Valley Foods DC", "address": "2100 S Morgan St, Chicago, IL 60608"}],
        "driver": {"name": "Ana", "phone": "3125550111"}}
ld = requests.post(f"{B}/loads", headers=own, json=body).json()
sid = ld["stops"][0]["id"]
r = requests.post(f"{B}/loads/{ld['id']}/stops/{sid}/adjust", headers=own, json={"arrived_at": (now - timedelta(hours=12)).isoformat(), "reason": "test"})
d = requests.get(f"{B}/dashboard", headers=own).json()
print("attention kinds", [a["kind"] for a in d["attention"]], "meters", [(m["load_number"], m["billing"]["amount"]) for m in d["meters"]])
print("approve", requests.post(f"{B}/loads/{ld['id']}/stops/{sid}/notice", headers=own).status_code)
requests.patch(f"{B}/fleet", headers=own, json={"notice_mode": "auto"})
r = requests.post(f"{B}/loads/{ld['id']}/stops/{sid}/adjust", headers=own, json={"departed_at": now.isoformat(), "reason": "test"})
inv = [i for i in requests.get(f"{B}/invoices", headers=own).json() if i["load_number"] == "CAP-TEST"][0]
print("cap invoice", inv["amount"], inv["status"])
print("send", requests.post(f"{B}/invoices/{inv['id']}/send", headers=own).status_code)
# tamper -> changed
requests.post(f"{B}/loads/{ld['id']}/stops/{sid}/adjust", headers=own, json={"departed_at": (now - timedelta(minutes=5)).isoformat(), "reason": "tamper test"})
ev = requests.get(f"{B}/public/evidence/{inv['public_token']}").json()
print("verification", ev["verification"]["state"], ev["verification"].get("changed_fields"))
# reminders
db.invoices.update_one({"id": inv["id"]}, {"$set": {"sent_at": (now - timedelta(days=8)).isoformat()}})
S = os.environ["WEBHOOK_CRON_SECRET"]
print("cron", requests.post(f"{B}/cron/tick", headers={"Authorization": f"Bearer {S}", "X-Webhook-Id": f"t-{time.time()}"}).status_code)
time.sleep(6)
print("reminders", db.invoices.find_one({"id": inv["id"]})["reminders"])
# pause / mark paid
print("pause", requests.post(f"{B}/invoices/{inv['id']}/status", headers=own, json={"action": "pause"}).json()["reminders_paused"])
print("paid", requests.post(f"{B}/invoices/{inv['id']}/status", headers=own, json={"action": "mark_paid", "method": "ach"}).json()["status"])
# invite -> dispatcher
em = f"disp{int(time.time())}+clerk_test@example.com"
print("invite", requests.post(f"{B}/fleet/invites", headers=own, json={"email": em}).json().get("email_sent"))
dh = {"Authorization": "Bearer " + tok(get_user(em))}
me = requests.get(f"{B}/me", headers=dh).json()
print("dispatcher", me["user"]["role"], me["fleet"]["name"] if me["fleet"] else None)
print("disp patch fleet", requests.patch(f"{B}/fleet", headers=dh, json={"name": "x"}).status_code)
print("disp sees loads", len(requests.get(f"{B}/loads", headers=dh).json()))
print("scorecard", [(f["name"], f["grade"]) for f in requests.get(f"{B}/scorecard", headers=own).json()["brokers"]])

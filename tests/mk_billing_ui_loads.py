# Creates QA loads for UI testing of the billing panel (blocked POD load, portal load, manual-complete load).
import json
import sys
sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, "/app/tests")
import requests  # noqa: E402
import test_billing_packet_http as t  # noqa: E402
from clerk_helper import get_or_create_user, session_jwt  # noqa: E402

s = requests.Session()
s.headers.update({"Authorization": f"Bearer {session_jwt(get_or_create_user(t.EMAIL))}", "Content-Type": "application/json"})
a = t.make_load(s, "UIA")
t.drive(a["driver_token"])
b = t.make_load(s, "UIP", terms={"submission_channel": "portal", "portal_url": "https://portal.example.test", "ap_email": None,
                                  "required_documents": []}, mode="auto")
t.drive(b["driver_token"])
c = t.make_load(s, "UIM")
t.drive(c["driver_token"], upto=3)
print(json.dumps({"A": a["id"], "P": b["id"], "M": c["id"]}))

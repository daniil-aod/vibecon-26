# Creates UI loads for iteration 13: CORRUI (submitted, then delivery departure +30 -> correction pending), BLKUI (completed, blocked).
import sys
sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, "/app/tests")
import requests  # noqa: E402
import test_billing_packet_http as t  # noqa: E402
import test_billing_fixes_http as f  # noqa: E402
from clerk_helper import get_or_create_user, session_jwt  # noqa: E402

s = requests.Session()
s.headers.update({"Authorization": f"Bearer {session_jwt(get_or_create_user(t.EMAIL))}", "Content-Type": "application/json"})
a = t.make_load(s, "CORRUI")
sid = f.complete_and_submit(s, a)
f.shift_departure(s, a, sid, 30)
b = t.make_load(s, "BLKUI")
t.drive(b["driver_token"])
inv = [i["id"] + ":" + i["number"] for i in t.billing(s, b["id"])["invoices"]]
print("CORR", a["id"], "BLK", b["id"], inv)

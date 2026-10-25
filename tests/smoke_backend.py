"""Backend smoke test: fleet -> extract -> load -> driver pings (arrive/depart) -> invoice -> send -> evidence -> checkout."""
import os, json, time, urllib.request, requests, sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
SK = os.environ["CLERK_SECRET_KEY"]
B = "http://localhost:8001/api"
ORIGIN = "https://naughty-hugle-13.preview.emergentagent.com"


def bapi(path, body=None, method="POST"):
    req = urllib.request.Request("https://api.clerk.com/v1" + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Authorization": "Bearer " + SK, "Content-Type": "application/json",
                                                         "User-Agent": "emergent-test"})
    return json.load(urllib.request.urlopen(req))


def get_user(email):
    import urllib.parse; users = bapi(f"/users?email_address={urllib.parse.quote(email)}", None, "GET")
    if users:
        return users[0]
    return bapi("/users", {"email_address": [email], "password": "Dock-Clock-Test-2026!", "skip_password_checks": True})


def tok(user):
    s = bapi("/sessions", {"user_id": user["id"]})
    return bapi(f"/sessions/{s['id']}/tokens", {"expires_in_seconds": 3600})["jwt"]


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "smoke+clerk_test@example.com"
    u = get_user(email)
    H = {"Authorization": "Bearer " + tok(u)}
    r = requests.get(f"{B}/me", headers=H, params={"origin": ORIGIN}); print("me", r.status_code, r.json().get("fleet"))
    if not r.json().get("fleet"):
        r = requests.post(f"{B}/fleet", headers=H, json={"name": "Smoke Haulers", "timezone": "America/Chicago",
                                                         "reply_to_email": "delivered@resend.dev", "origin": ORIGIN})
        print("fleet", r.status_code, r.text[:200])
    r = requests.post(f"{B}/ratecons/extract", headers=H, files={"file": ("rc.pdf", open("/tmp/test_ratecon.pdf", "rb"), "application/pdf")})
    print("extract", r.status_code)
    ex = r.json()["extracted"]
    ex["broker"]["email"] = "delivered@resend.dev"
    body = {"file_id": r.json()["file_id"], "load_number": ex["load_number"], "broker": ex["broker"], "detention": ex["detention"],
            "stops": ex["stops"], "driver": {"name": "Mike", "phone": "3125550100"}, "low_confidence": ex["low_confidence"]}
    r = requests.post(f"{B}/loads", headers=H, json=body); print("load", r.status_code)
    load = r.json()
    print("stops", [(s["facility_name"], s["lat"], s["lng"]) for s in load["stops"]])
    s0 = load["stops"][0]
    dt = load["driver_token"]
    r = requests.post(f"{B}/loads/{load['id']}/sms", headers=H); print("sms", r.status_code, r.text[:200])
    if s0["lat"]:
        r = requests.post(f"{B}/driver/{dt}/ping", json={"lat": s0["lat"] + 0.0005, "lng": s0["lng"], "accuracy": 15})
        print("ping arrive", r.status_code, r.json().get("event"))
    # simulate 3.5h dwell via dispatcher adjust
    now = datetime.now(timezone.utc)
    r = requests.post(f"{B}/loads/{load['id']}/stops/{s0['id']}/adjust", headers=H,
                      json={"arrived_at": (now - timedelta(hours=3, minutes=40)).isoformat(), "reason": "smoke test"})
    print("adjust arrive", r.status_code, r.text[:150] if r.status_code != 200 else "")
    r = requests.get(f"{B}/dashboard", headers=H); print("dashboard", r.status_code, r.json().get("headline"), len(r.json().get("meters", [])))
    r = requests.get(f"{B}/loads/{load['id']}", headers=H)
    print("notice", r.json()["stops"][0]["notice"])
    r = requests.post(f"{B}/driver/{dt}/stops/{s0['id']}/bol", files={"file": ("bol.png", open("/app/frontend/public/favicon.ico", "rb") if False else b"\x89PNG\r\n\x1a\n" + b"0" * 100, "image/png")})
    print("bol", r.status_code)
    r = requests.post(f"{B}/driver/{dt}/stops/{s0['id']}/tap/depart", json={"lat": s0["lat"] or 41.8, "lng": s0["lng"] or -87.6, "accuracy": 10})
    print("depart", r.status_code, r.text[:120] if r.status_code != 200 else "")
    r = requests.get(f"{B}/invoices", headers=H); invs = r.json(); print("invoices", r.status_code, [(i["number"], i["amount"], i["status"]) for i in invs])
    inv = invs[0]
    r = requests.post(f"{B}/invoices/{inv['id']}/send", headers=H); print("send", r.status_code, r.json().get("verification") if r.ok else r.text[:200])
    r = requests.get(f"{B}/public/evidence/{inv['public_token']}"); print("evidence", r.status_code, r.json().get("verification", {}).get("state") if r.ok else r.text[:200])
    r = requests.get(f"{B}/public/evidence/{inv['public_token']}/pdf"); print("pdf", r.status_code, len(r.content))
    r = requests.post(f"{B}/public/evidence/{inv['public_token']}/checkout", json={"origin_url": ORIGIN}); print("checkout", r.status_code, r.text[:120])
    if r.ok:
        r2 = requests.get(f"{B}/payments/status/{r.json()['session_id']}"); print("pstatus", r2.json())
    r = requests.get(f"{B}/scorecard", headers=H); print("scorecard", r.status_code, json.dumps(r.json())[:300])
    r = requests.get(f"{B}/loads/{load['id']}/playback", headers=H); print("playback", r.status_code, len(r.json()["pings"]), [e["type"] for e in r.json()["events"]])

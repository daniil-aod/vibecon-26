# Live mode only: real billing submission to the provider's test inbox (BILLING_SUBMISSION_MODE=live on the server).
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))
import test_billing_packet_http as t
from test_billing_packet_http import BASE_URL, billing, drive, make_load

client = t.client
INBOX = "delivered@resend.dev"


def test_live_submission_reaches_provider(client):
    ld = make_load(client, "LIVE", terms={"ap_email": INBOX})
    drive(ld["driver_token"])
    sid = max(ld["stops"], key=lambda s: s["seq"])["id"]
    h = {"Authorization": client.headers["Authorization"]}
    png = open("/app/tests/artifacts/pod.png", "rb").read()
    r = requests.post(f"{BASE_URL}/api/loads/{ld['id']}/stops/{sid}/documents", params={"doc_type": "pod"},
                      files={"file": ("pod.png", png, "image/png")}, headers=h)
    assert r.status_code == 200, r.text
    st = next(s for s in client.get(f"{BASE_URL}/api/loads/{ld['id']}").json()["stops"] if s["id"] == sid)
    r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/stops/{sid}/documents/{st['bol'][-1]['file_id']}/verify-signature")
    assert r.status_code == 200, r.text
    r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/billing/submit")
    assert r.status_code == 200, r.text
    sub = billing(client, ld["id"])["completion"]["submission"]
    assert sub["to"] == INBOX and sub["simulated"] is False, sub
    assert sub["state"] == "accepted" and not str(sub.get("provider_ref", "")).startswith("SIMULATED"), sub

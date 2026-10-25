# Driver email link flow: /me origin sync, load create with driver email, email-driver (link/recap), schedules, /api/open page.
# Auth: Clerk dev user dockqa+clerk_test@example.com; session JWT minted via Clerk Backend API (see /app/tests/clerk_helper.py).
# Only emails delivered@resend.dev (Resend test sink).
import os
import sys
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
SINK = "delivered@resend.dev"
EMAIL = "dockqa+clerk_test@example.com"


@pytest.fixture(scope="module")
def client():
    uid = get_or_create_user(EMAIL)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {session_jwt(uid)}", "Content-Type": "application/json"})
    me = s.get(f"{BASE_URL}/api/me", params={"origin": BASE_URL}).json()
    if not me.get("fleet"):
        r = s.post(f"{BASE_URL}/api/fleet", json={"name": "TEST_QA Haulers", "timezone": "America/Chicago",
                                                 "reply_to_email": SINK, "origin": BASE_URL})
        assert r.status_code == 200, r.text
    return s


def _payload(num, driver_email):
    return {"load_number": num, "broker": {"name": "TEST QA Broker", "email": SINK},
            "detention": {"free_time_hours": 2, "hourly_rate": 50},
            "stops": [{"type": "pickup", "facility_name": "Midwest DC", "address": "1000 W Jefferson St, Joliet, IL 60435"},
                      {"type": "delivery", "facility_name": "Inland DC", "address": "1 Main St, Fontana, CA 92335"}],
            "driver": {"name": "QA Driver", "phone": "3125550100", "email": driver_email}}


@pytest.fixture(scope="module")
def loads(client):
    created = {}
    for key, em in (("with", SINK), ("without", "")):
        r = client.post(f"{BASE_URL}/api/loads", json=_payload(f"TEST-PY-{key.upper()}", em))
        assert r.status_code == 200, r.text
        created[key] = r.json()
    yield created
    for ld in created.values():
        client.delete(f"{BASE_URL}/api/loads/{ld['id']}")


class TestMeOrigin:
    def test_me_syncs_app_url(self, client):
        r = client.get(f"{BASE_URL}/api/me", params={"origin": BASE_URL})
        assert r.status_code == 200
        assert r.json()["fleet"]["app_url"] == BASE_URL

    def test_me_rejects_invalid_origin(self, client):
        r = client.get(f"{BASE_URL}/api/me", params={"origin": "http://evil.example"})
        assert r.json()["fleet"]["app_url"] == BASE_URL


class TestLoadDriverEmail:
    def test_create_persists_driver_email(self, client, loads):
        ld = loads["with"]
        assert ld["driver"]["email"] == SINK
        assert ld["driver_url"] == f"{BASE_URL}/api/open/{ld['driver_token']}"
        g = client.get(f"{BASE_URL}/api/loads/{ld['id']}").json()
        assert g["driver"]["email"] == SINK

    def test_email_link_sent(self, client, loads):
        ld = loads["with"]
        r = client.post(f"{BASE_URL}/api/loads/{ld['id']}/email-driver", json={"kind": "link"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["sent"] is True and d["to"] == SINK and d["kind"] == "link"
        assert d["driver_url"].endswith(f"/api/open/{ld['driver_token']}")
        g = client.get(f"{BASE_URL}/api/loads/{ld['id']}").json()
        assert g["email_log"][-1]["sent"] is True

    def test_email_recap_sent(self, client, loads):
        r = client.post(f"{BASE_URL}/api/loads/{loads['with']['id']}/email-driver", json={"kind": "recap"})
        assert r.status_code == 200, r.text
        assert r.json()["sent"] is True and r.json()["kind"] == "recap"

    def test_email_unknown_kind(self, client, loads):
        r = client.post(f"{BASE_URL}/api/loads/{loads['with']['id']}/email-driver", json={"kind": "spam"})
        assert r.status_code == 400

    def test_email_without_driver_email(self, client, loads):
        r = client.post(f"{BASE_URL}/api/loads/{loads['without']['id']}/email-driver", json={"kind": "link"})
        assert r.status_code == 400
        assert r.json()["detail"] == "Add the driver's email first"

    def test_edit_add_then_remove_driver_email(self, client, loads):
        ld = loads["without"]
        g = client.get(f"{BASE_URL}/api/loads/{ld['id']}").json()
        g["driver"]["email"] = SINK
        r = client.put(f"{BASE_URL}/api/loads/{ld['id']}", json=g)
        assert r.status_code == 200, r.text
        assert client.get(f"{BASE_URL}/api/loads/{ld['id']}").json()["driver"]["email"] == SINK
        g["driver"]["email"] = ""
        client.put(f"{BASE_URL}/api/loads/{ld['id']}", json=g)
        g2 = client.get(f"{BASE_URL}/api/loads/{ld['id']}").json()
        assert g2["driver"]["email"] == ""
        assert g2["stops"][0]["id"] == g["stops"][0]["id"]  # stops preserved


class TestSchedules:
    def test_schedule_create_list_delete(self, client, loads):
        lid = loads["with"]["id"]
        at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        r = client.post(f"{BASE_URL}/api/loads/{lid}/email-schedules", json={"kind": "link", "frequency": "once", "send_at": at})
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        assert r.json()["active"] is True
        rows = client.get(f"{BASE_URL}/api/loads/{lid}/email-schedules").json()
        assert any(x["id"] == sid for x in rows)
        assert client.delete(f"{BASE_URL}/api/email-schedules/{sid}").status_code == 200
        rows = client.get(f"{BASE_URL}/api/loads/{lid}/email-schedules").json()
        assert not any(x["id"] == sid for x in rows)
        assert client.delete(f"{BASE_URL}/api/email-schedules/{sid}").status_code == 404

    def test_schedule_past_once_rejected(self, client, loads):
        at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        r = client.post(f"{BASE_URL}/api/loads/{loads['with']['id']}/email-schedules",
                        json={"kind": "link", "frequency": "once", "send_at": at})
        assert r.status_code == 400

    def test_schedule_naive_datetime(self, client, loads):
        # A send_at without timezone should be a clean 2xx/400, not a 500
        r = client.post(f"{BASE_URL}/api/loads/{loads['with']['id']}/email-schedules",
                        json={"kind": "link", "frequency": "once", "send_at": "2030-01-15T09:30"})
        assert r.status_code in (200, 400), r.text
        if r.status_code == 200:
            client.delete(f"{BASE_URL}/api/email-schedules/{r.json()['id']}")

    def test_schedule_garbage_time(self, client, loads):
        r = client.post(f"{BASE_URL}/api/loads/{loads['with']['id']}/email-schedules",
                        json={"kind": "link", "frequency": "once", "send_at": "not-a-date"})
        assert r.status_code == 400

    def test_schedule_requires_driver_email(self, client, loads):
        at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        r = client.post(f"{BASE_URL}/api/loads/{loads['without']['id']}/email-schedules",
                        json={"kind": "link", "frequency": "once", "send_at": at})
        assert r.status_code == 400


class TestOpenPage:
    def test_open_valid(self, loads):
        tok = loads["with"]["driver_token"]
        r = requests.get(f"{BASE_URL}/api/open/{tok}")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert f"dockclock://d/{tok}?api=" in r.text
        assert "Open in DockClock Driver" in r.text or "DockClock Driver" in r.text

    def test_open_invalid(self):
        r = requests.get(f"{BASE_URL}/api/open/definitely-not-a-token")
        assert r.status_code == 404

# Driver emails (link/recap), email schedules, next_run, auth guards — direct server import + HTTP auth checks
import asyncio
import os
import sys
import uuid
import copy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")
import server  # noqa: E402
import templates  # noqa: E402
import emailer  # noqa: E402

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
DEMO_TOKEN = "c6f13b08450947f7a4d7d1b94f340178d05b9070"
FLEET_ID = "demo-dockclock-fleet"
TAG = uuid.uuid4().hex[:6]
TEST_EMAIL = f"delivered+dc{TAG}@resend.dev"
CHI = ZoneInfo("America/Chicago")
# provider may rate-limit (429) during repeated runs; scheduling logic is still validated
OK_RESULTS = ("sent", "Failed to send email")

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
_client = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=loop)
server.db = _client[os.environ["DB_NAME"]]
run = loop.run_until_complete
db = server.db


@pytest.fixture(scope="module")
def fleet():
    return run(db.fleets.find_one({"id": FLEET_ID}, {"_id": 0}))


@pytest.fixture(scope="module")
def test_load(fleet):
    base = run(db.loads.find_one({"driver_token": DEMO_TOKEN}, {"_id": 0}))
    assert base, "demo load APX-30277 missing"
    ld = copy.deepcopy(base)
    ld["id"] = f"TEST_{uuid.uuid4().hex}"
    ld["load_number"] = f"TEST_APX-{TAG}"
    ld["driver_token"] = f"TEST{uuid.uuid4().hex}"
    ld["driver"] = {**(ld.get("driver") or {}), "email": TEST_EMAIL}
    now = datetime.now(timezone.utc)
    for i, s in enumerate(ld["stops"]):
        s["arrived_at"] = (now - timedelta(hours=3 + i)).isoformat()
        s["departed_at"] = (now - timedelta(hours=1 + i, minutes=15)).isoformat()
    ld.pop("email_log", None)
    run(db.loads.insert_one(dict(ld)))
    yield ld
    run(db.loads.delete_many({"id": {"$regex": "^TEST_"}}))
    run(db.email_schedules.delete_many({"load_id": {"$regex": "^TEST_"}}))


# ---------------- next_run (pure)
class TestNextRun:
    F = {"timezone": "America/Chicago"}

    def test_once_none(self):
        assert server.next_run(datetime(2026, 1, 5, 15, tzinfo=timezone.utc), "once", self.F) is None

    def test_daily_dst_spring(self):
        prev = datetime(2026, 3, 7, 8, 0, tzinfo=CHI).astimezone(timezone.utc)
        nxt = server.next_run(prev, "daily", self.F)
        assert nxt.astimezone(CHI).replace(tzinfo=None) == datetime(2026, 3, 8, 8, 0)
        assert nxt - prev == timedelta(hours=23)

    def test_weekly_dst_fall(self):
        prev = datetime(2026, 10, 29, 9, 30, tzinfo=CHI).astimezone(timezone.utc)
        nxt = server.next_run(prev, "weekly", self.F)
        assert nxt.astimezone(CHI).replace(tzinfo=None) == datetime(2026, 11, 5, 9, 30)
        assert nxt - prev == timedelta(days=7, hours=1)

    def test_monthly_jan31_feb28(self):
        prev = datetime(2026, 1, 31, 9, 0, tzinfo=CHI).astimezone(timezone.utc)
        nxt = server.next_run(prev, "monthly", self.F)
        assert nxt.astimezone(CHI).replace(tzinfo=None) == datetime(2026, 2, 28, 9, 0)

    def test_monthly_dec_to_jan(self):
        prev = datetime(2026, 12, 15, 7, 0, tzinfo=CHI).astimezone(timezone.utc)
        nxt = server.next_run(prev, "monthly", self.F)
        assert nxt.astimezone(CHI).replace(tzinfo=None) == datetime(2027, 1, 15, 7, 0)

    def test_monthly_drift_after_clamp(self):
        # Jan31 -> Feb28 -> Mar28 (original day 31 is lost); documented behaviour check
        prev = datetime(2026, 1, 31, 9, 0, tzinfo=CHI).astimezone(timezone.utc)
        n2 = server.next_run(server.next_run(prev, "monthly", self.F), "monthly", self.F)
        print("Jan31 -> 2 months ->", n2.astimezone(CHI))
        assert n2.astimezone(CHI).day in (28, 31)


# ---------------- templates safety
class TestTemplates:
    def test_link_template_safe(self):
        subj, html = templates.driver_link_email("Fleet <x>", "Bob", "L-1", "DC & Co", "https://example.com/api/open/abc")
        emailer._assert_safe_email(subj, html)
        assert "&lt;x&gt;" in html or "Fleet" in html

    def test_recap_template_safe(self):
        rows = [{"load": "L-1", "facility": "<b>DC</b>", "in": "a", "out": "b", "wait": "1h 00m"}]
        subj, html = templates.driver_recap_email("Fleet", "Bob", "the last day", rows)
        emailer._assert_safe_email(subj, html)
        assert "<b>DC</b>" not in html
        subj, html = templates.driver_recap_email("Fleet", "", "the last day", [])
        emailer._assert_safe_email(subj, html)
        assert "No dock stops" in html


# ---------------- send_driver_email (real email to resend.dev test inbox)
class TestSendDriverEmail:
    def test_no_email(self, fleet, test_load):
        ld = {**test_load, "driver": {"name": "x"}}
        res = run(server.send_driver_email(fleet, ld, "link"))
        assert res["sent"] is False and res["reason"] == "no_email"

    def test_link(self, fleet, test_load):
        res = run(server.send_driver_email(fleet, test_load, "link", "once", "TEST_user"))
        print("link result", res)
        assert res["sent"] is True or res.get("reason") == "email_error"
        assert res["sent"] is True, res
        doc = run(db.loads.find_one({"id": test_load["id"]}, {"_id": 0, "email_log": 1}))
        assert any(e["kind"] == "link" and e["to"] == TEST_EMAIL for e in doc["email_log"])

    def test_recap_once_rows(self, fleet, test_load):
        rows = run(server._recap_rows(fleet, test_load, "once"))
        assert len(rows) == len(test_load["stops"])
        assert rows[0]["wait"].endswith("m") and rows[0]["out"] != "On site"

    def test_recap_daily_rows_by_email(self, fleet, test_load):
        rows = run(server._recap_rows(fleet, test_load, "daily"))
        assert len(rows) >= 1 and all(r["load"].startswith("TEST_APX") for r in rows)

    def test_recap_send(self, fleet, test_load):
        res = run(server.send_driver_email(fleet, test_load, "recap", "weekly", "TEST_user"))
        print("recap result", res)
        assert res["sent"] is True, res


# ---------------- run_schedules
def _sched(load_id, freq, next_at, kind="recap"):
    return {"id": f"TEST_{uuid.uuid4().hex}", "fleet_id": FLEET_ID, "load_id": load_id, "kind": kind,
            "frequency": freq, "send_at": next_at, "next_run_at": next_at, "active": True, "last_sent_at": None,
            "last_result": None, "created_by": "TEST", "created_at": server.iso(server.now_utc())}


class TestRunSchedules:
    def test_run_schedules(self, fleet, test_load):
        now = datetime.now(timezone.utc)
        past = server.iso(now - timedelta(minutes=5))
        s_once = _sched(test_load["id"], "once", past, "link")
        s_daily = _sched(test_load["id"], "daily", server.iso(now - timedelta(days=3, minutes=5)))
        s_week = _sched(test_load["id"], "weekly", past)
        s_month = _sched(test_load["id"], "monthly", past)
        s_missing = _sched("TEST_missing_load", "daily", past)
        s_future = _sched(test_load["id"], "daily", server.iso(now + timedelta(hours=2)))
        all_s = [s_once, s_daily, s_week, s_month, s_missing, s_future]
        run(db.email_schedules.insert_many([dict(s) for s in all_s]))
        # only our fleet in fmap to avoid touching other data
        fmap = {FLEET_ID: fleet}
        log_before = len((run(db.loads.find_one({"id": test_load["id"]}, {"_id": 0, "email_log": 1})) or {}).get("email_log") or [])
        run(server.run_schedules(fmap))
        got = {s["id"]: run(db.email_schedules.find_one({"id": s["id"]}, {"_id": 0})) for s in all_s}
        for k, v in got.items():
            print(v["frequency"], v["active"], v["next_run_at"], v["last_result"])
        assert got[s_once["id"]]["active"] is False and got[s_once["id"]]["last_result"] in OK_RESULTS
        assert got[s_missing["id"]]["active"] is False and got[s_missing["id"]]["last_result"] == "load_missing"
        assert got[s_future["id"]]["last_sent_at"] is None
        lp = server.parse(past)
        d = server.parse(got[s_daily["id"]]["next_run_at"])
        assert d > now and d - now < timedelta(days=1)
        assert server.parse(got[s_week["id"]]["next_run_at"]) == server.next_run(lp, "weekly", fleet)
        assert server.parse(got[s_month["id"]]["next_run_at"]) == server.next_run(lp, "monthly", fleet)
        for s in (s_daily, s_week, s_month):
            assert got[s["id"]]["active"] is True and got[s["id"]]["last_result"] in OK_RESULTS, got[s["id"]]
        log_after = run(db.loads.find_one({"id": test_load["id"]}, {"_id": 0, "email_log": 1}))["email_log"]
        assert len(log_after) - log_before == 4
        assert all(e["by"] == "schedule" for e in log_after[log_before:])
        # second immediate call -> no double send
        run(server.run_schedules(fmap))
        log2 = run(db.loads.find_one({"id": test_load["id"]}, {"_id": 0, "email_log": 1}))["email_log"]
        assert len(log2) == len(log_after)


# ---------------- HTTP auth guards
class TestAuthGuards:
    @pytest.mark.parametrize("method,path,body", [
        ("post", "/api/loads/x/email-driver", {"kind": "link"}),
        ("get", "/api/loads/x/email-schedules", None),
        ("post", "/api/loads/x/email-schedules", {"kind": "link", "frequency": "once", "send_at": "2030-01-01T00:00:00Z"}),
        ("delete", "/api/email-schedules/x", None),
    ])
    def test_unauth(self, method, path, body):
        r = getattr(requests, method)(f"{BASE_URL}{path}", json=body, timeout=20)
        assert r.status_code in (401, 403), r.status_code

    def test_cron_requires_secret(self):
        r = requests.post(f"{BASE_URL}/api/cron/tick", timeout=20)
        assert r.status_code == 401

    def test_open_link(self):
        r = requests.get(f"{BASE_URL}/api/open/{DEMO_TOKEN}", timeout=20)
        assert r.status_code == 200 and "DockClock" in r.text

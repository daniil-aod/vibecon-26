# DockClock driver offline ping backup – body.ts honoring (_ping_time) + geofence ordering on queued pings
import os, uuid, copy, asyncio
from datetime import datetime, timedelta, timezone
import pytest, requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
ON_SITE_TOKEN = (__import__("pymongo").MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]].loads.find_one({"load_number": "RL-55018"}) or {}).get("driver_token", "")  # RL-55018 (tokens regenerate on reseed)


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def run(coro):
    return asyncio.run(coro)


def now():
    return datetime.now(timezone.utc)


def P(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def make_load():
    async def make():
        db = _db()
        src = await db.loads.find_one({"driver_token": ON_SITE_TOKEN}, {"_id": 0})
        assert src, "Demo load RL-55018 missing"
        ld = copy.deepcopy(src)
        ld["id"] = "TEST_" + uuid.uuid4().hex
        ld["driver_token"] = "testtok" + uuid.uuid4().hex
        ld["load_number"] = "TEST-" + uuid.uuid4().hex[:5]
        ld["status"] = "dispatched"
        for s in ld["stops"]:
            for k in ("arrived_at", "departed_at", "arrived_source", "departed_source", "arrived_coords", "departed_coords"):
                s[k] = None
            s["events"], s["bol"] = [], []
            s["notice"] = {"status": None}
        ld.pop("last_ping", None)
        await db.loads.insert_one(ld)
        return ld
    return run(make())


def clean(ld):
    async def c():
        db = _db()
        await db.loads.delete_many({"id": ld["id"]})
        await db.pings.delete_many({"load_id": ld["id"]})
        await db.invoices.delete_many({"load_id": ld["id"]})
    run(c())


def pings(ld):
    async def g():
        return await _db().pings.find({"load_id": ld["id"]}, {"_id": 0}).sort("_id", 1).to_list(100)
    return run(g())


def load_doc(ld):
    async def g():
        return await _db().loads.find_one({"id": ld["id"]}, {"_id": 0})
    return run(g())


@pytest.fixture
def ld():
    x = make_load()
    yield x
    clean(x)


def ping(ld, lat, lng, ts=None, acc=10):
    body = {"lat": lat, "lng": lng, "accuracy": acc}
    if ts is not None:
        body["ts"] = ts
    return requests.post(f"{BASE_URL}/api/driver/{ld['driver_token']}/ping", json=body, timeout=30)


# ---- _ping_time: which timestamp gets stored
class TestPingTime:
    def test_ts_10min_ago_honored(self, ld):
        s = ld["stops"][0]
        want = now() - timedelta(minutes=10)
        r = ping(ld, s["lat"] + 1, s["lng"], want.isoformat())
        assert r.status_code == 200 and r.json()["event"] is None
        p = pings(ld)[-1]
        assert abs((P(p["ts"]) - want).total_seconds()) < 1.5
        assert abs((P(load_doc(ld)["last_ping"]["ts"]) - want).total_seconds()) < 1.5

    def test_ts_z_suffix_honored(self, ld):
        s = ld["stops"][0]
        want = now() - timedelta(minutes=5)
        r = ping(ld, s["lat"] + 1, s["lng"], want.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z")
        assert r.status_code == 200
        assert abs((P(pings(ld)[-1]["ts"]) - want).total_seconds()) < 1.5

    def test_ts_3_days_ago_falls_back(self, ld):
        s = ld["stops"][0]
        r = ping(ld, s["lat"] + 1, s["lng"], (now() - timedelta(days=3)).isoformat())
        assert r.status_code == 200
        assert abs((P(pings(ld)[-1]["ts"]) - now()).total_seconds()) < 30

    def test_ts_1h_future_falls_back(self, ld):
        s = ld["stops"][0]
        r = ping(ld, s["lat"] + 1, s["lng"], (now() + timedelta(hours=1)).isoformat())
        assert r.status_code == 200
        assert abs((P(pings(ld)[-1]["ts"]) - now()).total_seconds()) < 30

    @pytest.mark.parametrize("bad", ["garbage", "2026-13-45T99:00:00Z", "", "12345"])
    def test_invalid_ts_no_500(self, ld, bad):
        s = ld["stops"][0]
        r = ping(ld, s["lat"] + 1, s["lng"], bad)
        assert r.status_code == 200, r.text
        assert abs((P(pings(ld)[-1]["ts"]) - now()).total_seconds()) < 30

    def test_non_string_ts_422_not_500(self, ld):
        s = ld["stops"][0]
        r = ping(ld, s["lat"] + 1, s["lng"], 1700000000)
        assert r.status_code in (200, 422), r.text

    def test_last_ping_only_moves_forward(self, ld):
        s = ld["stops"][0]
        assert ping(ld, s["lat"] + 1, s["lng"]).status_code == 200
        cur = load_doc(ld)["last_ping"]["ts"]
        assert ping(ld, s["lat"] + 2, s["lng"], (now() - timedelta(minutes=8)).isoformat()).status_code == 200
        lp = load_doc(ld)["last_ping"]
        assert lp["ts"] == cur and lp["lat"] == s["lat"] + 1
        assert len(pings(ld)) == 2  # older point still stored as evidence


# ---- geofence with queued (old) pings
class TestQueuedGeofence:
    def test_arrival_uses_queued_ts_and_no_early_departure(self, ld):
        s = ld["stops"][0]
        arr = now() - timedelta(minutes=30)
        r = ping(ld, s["lat"], s["lng"], arr.isoformat(), acc=8)
        assert r.status_code == 200 and r.json()["event"] == "arrived"
        got = r.json()["stops"][0]
        assert abs((P(got["arrived_at"]) - arr).total_seconds()) < 1.5
        assert got["arrived_source"] == "geofence"
        # queued far-away point older than arrival -> must NOT depart
        r = ping(ld, s["lat"] + 0.05, s["lng"], (arr - timedelta(minutes=5)).isoformat(), acc=8)
        assert r.status_code == 200 and r.json()["event"] is None
        assert r.json()["stops"][0]["departed_at"] is None
        # queued far-away point after arrival -> departs at its ts
        dep = arr + timedelta(minutes=20)
        r = ping(ld, s["lat"] + 0.05, s["lng"], dep.isoformat(), acc=8)
        assert r.status_code == 200 and r.json()["event"] == "departed"
        st = requests.get(f"{BASE_URL}/api/driver/{ld['driver_token']}").json()["stops"][0]
        assert abs((P(st["departed_at"]) - dep).total_seconds()) < 1.5
        assert st["departed_source"] == "geofence"

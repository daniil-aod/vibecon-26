# Iteration 13: follow-ups — radius-on-update only when changed, create_load validates first,
# accuracy 0 kept, no zone events after ride end, 45 m fallbacks, e38e91c9 host serves LOCAL backend.
import asyncio
import os
import re
import sys
import uuid

import pytest
import requests
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")
import server  # noqa: E402

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
ALT_URL = "https://e38e91c9-2f90-4132-abe8-9e55b84b1985.preview.emergentagent.com"
TOK = "15fea12acebc17d44921caaad2101f5bd5b231f6"  # local TEST-0001
PICK = (41.525, -88.0817)
FLEET_ID = "demo-dockclock-fleet"
TAG = uuid.uuid4().hex[:6]

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
_client = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=loop)
server.db = _client[os.environ["DB_NAME"]]
run = loop.run_until_complete
db = server.db


@pytest.fixture(scope="module")
def member():
    fleet = run(db.fleets.find_one({"id": FLEET_ID}, {"_id": 0}))
    assert fleet
    yield {"fleet_id": FLEET_ID, "fleet": fleet, "user_id": "TEST_user"}
    run(db.loads.delete_many({"load_number": {"$regex": f"^TEST_{TAG}"}}))
    run(db.facilities.delete_many({"name": {"$regex": f"^TEST_{TAG}"}}))


def stops_in(n=2):
    return [server.StopIn(type="pickup" if i == 0 else "delivery", facility_name=f"TEST_{TAG}_F{i}",
                          address=f"{i} Test Rd", lat=41.5 + i, lng=-88.0 - i) for i in range(n)]


# create_load: radius validated before facilities are written
class TestCreateLoad:
    def test_bad_radius_no_facility_writes(self, member):
        body = server.LoadIn(load_number=f"TEST_{TAG}_bad", stops=stops_in(), geofence_radius_m=5)
        with pytest.raises(HTTPException) as e:
            run(server.create_load(body, member))
        assert e.value.status_code == 400
        assert run(db.facilities.count_documents({"name": {"$regex": f"^TEST_{TAG}"}})) == 0

    def test_default_45(self, member):
        v = run(server.create_load(server.LoadIn(load_number=f"TEST_{TAG}_def", stops=stops_in()), member))
        ld = run(db.loads.find_one({"id": v["id"]}, {"_id": 0}))
        assert ld["geofence_radius_m"] == 45
        assert all(s["radius_m"] == 45 for s in ld["stops"])


# update_load: geofence_radius_m only re-applied when it changed
class TestUpdateLoad:
    def _mk(self, member, r=80):
        v = run(server.create_load(server.LoadIn(load_number=f"TEST_{TAG}_u{uuid.uuid4().hex[:4]}", stops=stops_in(),
                                                 geofence_radius_m=r), member))
        return run(db.loads.find_one({"id": v["id"]}, {"_id": 0}))

    def _body(self, ld, r):
        return server.LoadIn(load_number=ld["load_number"], geofence_radius_m=r,
                             stops=[server.StopIn(id=s["id"], type=s["type"], facility_name=s["facility_name"],
                                                  address=s["address"]) for s in ld["stops"]])

    def test_unchanged_keeps_per_stop_tweak(self, member):
        ld = self._mk(member, 80)
        assert all(s["radius_m"] == 80 for s in ld["stops"])
        ld["stops"][1]["radius_m"] = 200.0  # per-facility tweak
        run(db.loads.update_one({"id": ld["id"]}, {"$set": {"stops": ld["stops"]}}))
        run(server.update_load(ld["id"], self._body(ld, 80), member))
        got = run(db.loads.find_one({"id": ld["id"]}, {"_id": 0}))
        assert [s["radius_m"] for s in got["stops"]] == [80, 200.0]

    def test_changed_applies_all(self, member):
        ld = self._mk(member, 80)
        run(server.update_load(ld["id"], self._body(ld, 120), member))
        got = run(db.loads.find_one({"id": ld["id"]}, {"_id": 0}))
        assert got["geofence_radius_m"] == 120
        assert all(s["radius_m"] == 120 for s in got["stops"])

    def test_changed_invalid_400(self, member):
        ld = self._mk(member, 80)
        with pytest.raises(HTTPException) as e:
            run(server.update_load(ld["id"], self._body(ld, 9999), member))
        assert e.value.status_code == 400
        got = run(db.loads.find_one({"id": ld["id"]}, {"_id": 0}))
        assert got["geofence_radius_m"] == 80


def ping(lat, lng, acc):
    r = requests.post(f"{BASE_URL}/api/driver/{TOK}/ping", json={"lat": lat, "lng": lng, "accuracy": acc}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def s0(d):
    return sorted(d["stops"], key=lambda s: s["seq"])[0]


def last_ping():
    ld = run(db.loads.find_one({"driver_token": TOK}, {"_id": 0, "id": 1}))
    return run(db.pings.find_one({"load_id": ld["id"]}, {"_id": 0}, sort=[("ts", -1)]))


# driver_ping: accuracy 0 kept, no events after ride end (LOCAL TEST-0001; reset after)
class TestPingRules:
    @pytest.fixture(autouse=True, scope="class")
    def reset(self):
        requests.post(f"{BASE_URL}/api/driver/{TOK}/reset-test", timeout=30)
        yield
        r = requests.post(f"{BASE_URL}/api/driver/{TOK}/reset-test", timeout=30)
        assert r.status_code == 200

    def test_accuracy_zero_kept(self):
        # 50 m out: with acc 0 -> undecided (no arrival); if acc became 50 it would be 'inside'
        d = ping(PICK[0] + 0.00045, PICK[1], 0)
        assert d["event"] is None and s0(d)["arrived_at"] is None
        assert last_ping()["accuracy"] == 0

    def test_accuracy_none_defaults_50(self):
        r = requests.post(f"{BASE_URL}/api/driver/{TOK}/ping", json={"lat": 30.0, "lng": -90.0}, timeout=30)
        assert r.status_code == 200
        assert last_ping()["accuracy"] == 50

    def test_after_ride_end_no_events(self):
        assert requests.post(f"{BASE_URL}/api/driver/{TOK}/ride/start", timeout=30).status_code == 200
        r = requests.post(f"{BASE_URL}/api/driver/{TOK}/ride/end", json={}, timeout=30)
        assert r.status_code == 200 and r.json()["ride"]["ended_at"]
        d = ping(*PICK, 5)
        assert d["event"] is None and s0(d)["arrived_at"] is None
        p = last_ping()
        assert p["lat"] == PICK[0] and p["stop_id"] is None


# e38e91c9 host routes to this LOCAL backend (45 m, ride routes)
class TestAltHost:
    def test_alt_host_local(self):
        d = requests.get(f"{ALT_URL}/api/driver/{TOK}", timeout=30).json()
        assert d["load_number"] == "TEST-0001" and s0(d)["radius_m"] == 45 and "ride" in d

    def test_alt_host_in_extra_hosts(self):
        hosts = os.environ.get("EXPO_PUBLIC_EXTRA_API_HOSTS", "").lower().split(",")
        assert ALT_URL.replace("https://", "") in [h.strip() for h in hosts]


# 45 m fallbacks + slider max
class TestFallbacks:
    @pytest.mark.parametrize("path,pat", [
        ("/app/frontend/src/components/FacilityMap.tsx", r"radius_m \|\| 45"),
        ("/app/frontend/app/d/[token].tsx", r"radius_m \|\| 45"),
        ("/app/backend/pdfgen.py", r"radius_m\"\) or 45"),
        ("/app/web/src/pages/Evidence.js", r"radius_m \|\| 45"),
        ("/app/web/src/pages/LoadDetail.js", r"max=\{3000\}"),
    ])
    def test_pattern(self, path, pat):
        src = open(path).read()
        assert re.search(pat, src), path
        assert "|| 300" not in src and "or 300)" not in src

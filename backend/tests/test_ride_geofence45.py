# Iteration 12: 45 m geofence default, zone_state rules, ride start/end on LOCAL TEST-0001 load.
import os
import sys

import pytest
import requests
from fastapi import HTTPException

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
TOK = "15fea12acebc17d44921caaad2101f5bd5b231f6"
PICK = (41.525, -88.0817)
DELIV = (34.049, -117.435)

sys.path.insert(0, "/app/backend")
import server  # noqa: E402
import demo  # noqa: E402


def ping(lat, lng, acc=10):
    r = requests.post(f"{BASE_URL}/api/driver/{TOK}/ping", json={"lat": lat, "lng": lng, "accuracy": acc}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def s0(d):
    return sorted(d["stops"], key=lambda s: s["seq"])[0]


# Unit: constants + zone_state + _apply_radius
class TestUnits:
    def test_constants(self):
        assert server.DEFAULT_RADIUS == 45
        assert (server.RADIUS_MIN, server.RADIUS_MAX) == (15, 3000)
        assert demo.DEMO_VERSION == 5

    def test_zone_state(self):
        zs = server.zone_state
        assert zs(0, 10, 45) == "inside"
        assert zs(70, 25, 45) == "inside"          # 70-25 = 45 <= 45
        assert zs(70, 60, 45) == "inside"          # slack capped at 25
        assert zs(71, 25, 45) is None              # 46: buffer band
        assert zs(80, 20, 45) == "outside"         # 60 > 55
        assert zs(100, 10, 45) == "outside"
        assert zs(0, 300, 45) is None              # too inaccurate
        assert zs(0, 100, 45) == "inside"          # 100 allowed

    def test_apply_radius(self):
        stops = [{"radius_m": 300, "arrived_at": None}, {"radius_m": 300, "arrived_at": "2026-01-01T00:00:00+00:00"}]
        server._apply_radius(stops, 60)
        assert stops[0]["radius_m"] == 60.0 and stops[1]["radius_m"] == 300
        server._apply_radius(stops, None)
        assert stops[0]["radius_m"] == 60.0
        for bad in (14, 3001, 0, -5):
            with pytest.raises(HTTPException) as e:
                server._apply_radius([{"arrived_at": None}], bad)
            assert e.value.status_code == 400
        server._apply_radius([{"arrived_at": None}], 15)
        server._apply_radius([{"arrived_at": None}], 3000)


@pytest.fixture(scope="class")
def reset():
    r = requests.post(f"{BASE_URL}/api/driver/{TOK}/reset-test", timeout=30)
    assert r.status_code == 200 and r.json()["ride"] is None
    yield
    requests.post(f"{BASE_URL}/api/driver/{TOK}/reset-test", timeout=30)


@pytest.mark.usefixtures("reset")
class TestRideAndGeofence:
    def test_fresh_45m(self):
        d = requests.get(f"{BASE_URL}/api/driver/{TOK}", timeout=30).json()
        a = s0(d)
        assert (a["lat"], a["lng"], a["radius_m"]) == (PICK[0], PICK[1], 45)
        assert all(s["radius_m"] == 45 for s in d["stops"])
        assert d["ride"] is None

    def test_ride_start(self):
        r = requests.post(f"{BASE_URL}/api/driver/{TOK}/ride/start", timeout=30)
        assert r.status_code == 200
        ride = r.json()["ride"]
        assert ride["started_at"] and ride["ended_at"] is None
        # idempotent: second start keeps the same started_at
        r2 = requests.post(f"{BASE_URL}/api/driver/{TOK}/ride/start", timeout=30).json()
        assert r2["ride"]["started_at"] == ride["started_at"]

    def test_low_accuracy_no_event(self):
        d = ping(*PICK, acc=300)
        assert d["event"] is None and not s0(d)["arrived_at"]

    def test_ping_60m_outside_buffer_no_arrival(self):
        # ~150 m north: clearly outside the 45 m zone (old 300 m zone would have arrived)
        d = ping(PICK[0] + 0.00135, PICK[1], acc=10)
        assert d["event"] is None and not s0(d)["arrived_at"]

    def test_inside_arrival(self):
        d = ping(*PICK, acc=10)
        assert d["event"] == "arrived"
        a = s0(d)
        assert a["arrived_at"] and a["arrived_source"] == "geofence"

    def test_low_acc_far_no_departure(self):
        d = ping(PICK[0] + 0.0009, PICK[1], acc=300)
        assert d["event"] is None and not s0(d)["departed_at"]

    def test_100m_departure(self):
        d = ping(PICK[0] + 0.0009, PICK[1], acc=10)   # ~100 m
        assert d["event"] == "departed"
        assert s0(d)["departed_source"] == "geofence"

    def test_reenter_next_stop_none(self):
        d = ping(*PICK, acc=10)
        assert d["event"] is None


@pytest.mark.usefixtures("reset")
class TestRideEndInsideZone:
    def test_ride_end_closes_zone(self):
        requests.post(f"{BASE_URL}/api/driver/{TOK}/ride/start", timeout=30)
        d = ping(*PICK, acc=10)
        assert d["event"] == "arrived"
        r = requests.post(f"{BASE_URL}/api/driver/{TOK}/ride/end", json={"lat": PICK[0], "lng": PICK[1], "accuracy": 8}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ride"]["started_at"] and d["ride"]["ended_at"]
        a = s0(d)
        assert a["departed_at"] and a["departed_source"] == "ride_end"
        # persisted
        g = requests.get(f"{BASE_URL}/api/driver/{TOK}", timeout=30).json()
        assert g["ride"]["ended_at"] == d["ride"]["ended_at"]
        assert s0(g)["departed_source"] == "ride_end"

    def test_ride_end_no_body(self):
        r = requests.post(f"{BASE_URL}/api/driver/{TOK}/ride/end", timeout=30)
        assert r.status_code == 200, r.text

    def test_reset_clears_ride(self):
        r = requests.post(f"{BASE_URL}/api/driver/{TOK}/reset-test", timeout=30).json()
        assert r["ride"] is None and not s0(r)["arrived_at"]

    def test_bad_token(self):
        assert requests.post(f"{BASE_URL}/api/driver/nope-bad/ride/start", timeout=30).status_code == 404
        assert requests.post(f"{BASE_URL}/api/driver/nope-bad/ride/end", timeout=30).status_code == 404

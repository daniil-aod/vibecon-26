# Iteration 9: geofence-driven trip on the LOCAL TEST-0001 load (start anywhere, no anchoring), BOL completes trip.
import os
from datetime import datetime, timedelta

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
TOK = "15fea12acebc17d44921caaad2101f5bd5b231f6"
REMOTE = "https://naughty-hugle-13.preview.emergentagent.com"
REMOTE_TOK = "0968f6252c5e45f8ec02dbb9a24b1f175f3d311b"
PICK = (41.525, -88.0817)
DELIV = (34.049, -117.435)
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def ping(lat, lng, acc=10, ts=None):
    body = {"lat": lat, "lng": lng, "accuracy": acc}
    if ts:
        body["ts"] = ts
    r = requests.post(f"{BASE_URL}/api/driver/{TOK}/ping", json=body, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="class")
def reset():
    r = requests.post(f"{BASE_URL}/api/driver/{TOK}/reset-test", timeout=30)
    assert r.status_code == 200
    yield
    requests.post(f"{BASE_URL}/api/driver/{TOK}/reset-test", timeout=30)


@pytest.mark.usefixtures("reset")
class TestGeofenceTrip:
    # Fresh payload: stops have fixed coords (no anchoring), BOL required
    def test_fresh_payload(self):
        d = requests.get(f"{BASE_URL}/api/driver/{TOK}", timeout=30).json()
        assert d["test_load"] is True and d["requires_signed_bol"] is True
        s0, s1 = sorted(d["stops"], key=lambda s: s["seq"])
        assert (s0["lat"], s0["lng"], s0["radius_m"]) == (PICK[0], PICK[1], 300)
        assert (s1["lat"], s1["lng"]) == DELIV
        assert all(not s["arrived_at"] for s in d["stops"])

    # Start far away (Chicago): no arrival, coords unchanged
    def test_far_ping_no_arrival(self):
        d = ping(41.88, -87.63)
        s0 = sorted(d["stops"], key=lambda s: s["seq"])[0]
        assert d["event"] is None and not s0["arrived_at"]
        assert (s0["lat"], s0["lng"]) == PICK

    # Enter pickup zone: arrival stamped by geofence, free_expires = arrival + 2h
    def test_enter_pickup(self):
        d = ping(*PICK)
        s0 = sorted(d["stops"], key=lambda s: s["seq"])[0]
        assert d["event"] == "arrived" and s0["arrived_source"] == "geofence"
        a = datetime.fromisoformat(s0["arrived_at"].replace("Z", "+00:00"))
        f = datetime.fromisoformat(s0["free_expires_at"].replace("Z", "+00:00"))
        assert abs((f - a) - timedelta(hours=2)) < timedelta(seconds=5)

    # Coarse ping far away (acc>300) must NOT depart
    def test_coarse_no_depart(self):
        d = ping(41.535, -88.0817, acc=400)
        s0 = sorted(d["stops"], key=lambda s: s["seq"])[0]
        assert not s0["departed_at"]

    # Move ~1 km away: departure stamped, delivery is current
    def test_leave_pickup(self):
        d = ping(41.534, -88.0817)
        s0, s1 = sorted(d["stops"], key=lambda s: s["seq"])
        assert d["event"] == "departed" and s0["departed_source"] == "geofence"
        assert not s1["arrived_at"]

    # Enter delivery then leave: all departed
    def test_delivery_in_out(self):
        d = ping(*DELIV)
        assert d["event"] == "arrived"
        d = ping(DELIV[0] + 0.009, DELIV[1])
        assert d["event"] == "departed"
        assert all(s["departed_at"] for s in d["stops"])
        s1 = sorted(d["stops"], key=lambda s: s["seq"])[1]
        assert s1["bol_count"] == 0

    # Extra ping after all departed is accepted (tracking continues until BOL)
    def test_ping_after_done(self):
        d = ping(DELIV[0] + 0.02, DELIV[1])
        assert d["event"] is None

    # BOL upload on final stop -> bol_count 1
    def test_bol_upload(self):
        d = requests.get(f"{BASE_URL}/api/driver/{TOK}", timeout=30).json()
        s1 = sorted(d["stops"], key=lambda s: s["seq"])[1]
        r = requests.post(f"{BASE_URL}/api/driver/{TOK}/stops/{s1['id']}/bol",
                          files={"file": ("bol.png", PNG, "image/png")}, timeout=30)
        assert r.status_code == 200, r.text
        s1 = sorted(r.json()["stops"], key=lambda s: s["seq"])[1]
        assert s1["bol_count"] == 1

    # Reset restores fresh state
    def test_reset(self):
        d = requests.post(f"{BASE_URL}/api/driver/{TOK}/reset-test", timeout=30).json()
        assert all(not s["arrived_at"] and s["bol_count"] == 0 for s in d["stops"])
        s0 = sorted(d["stops"], key=lambda s: s["seq"])[0]
        assert (s0["lat"], s0["lng"]) == PICK


class TestRemoteReadOnly:
    # Remote web backend: GET only
    def test_remote_get(self):
        r = requests.get(f"{REMOTE}/api/driver/{REMOTE_TOK}", timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["load_number"] == "RL-55018"

    # Remote CORS allows the preview origin
    def test_remote_cors(self):
        r = requests.options(f"{REMOTE}/api/driver/{REMOTE_TOK}/ping", timeout=30, headers={
            "Origin": BASE_URL, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})
        assert r.status_code in (200, 204), r.status_code
        assert r.headers.get("access-control-allow-origin") in ("*", BASE_URL)

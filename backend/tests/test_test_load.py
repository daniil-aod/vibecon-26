# TEST-0001 real-feeling test load: anchor-on-first-fix, geofence arrive/depart, reset-test endpoint
import os
import pytest
import requests

BASE_URL = os.environ.get('EXPO_PUBLIC_BACKEND_URL').rstrip('/')
TEST_TOK = "15fea12acebc17d44921caaad2101f5bd5b231f6"
RL_TOK = "0968f6252c5e45f8ec02dbb9a24b1f175f3d311b"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    r = sess.post(f"{BASE_URL}/api/driver/{TEST_TOK}/reset-test")
    assert r.status_code == 200, r.text
    yield sess
    sess.post(f"{BASE_URL}/api/driver/{TEST_TOK}/reset-test")


def ping(s, lat, lng, acc=10):
    r = s.post(f"{BASE_URL}/api/driver/{TEST_TOK}/ping", json={"lat": lat, "lng": lng, "accuracy": acc})
    assert r.status_code == 200, r.text
    return r.json()


class TestTestLoad:
    def test_fresh_state(self, s):
        d = s.get(f"{BASE_URL}/api/driver/{TEST_TOK}").json()
        assert d["test_load"] is True
        assert d["load_number"] == "TEST-0001"
        assert d["stops"][0]["lat"] is None and d["stops"][0]["lng"] is None
        assert all(st["arrived_at"] is None and st["departed_at"] is None for st in d["stops"])
        assert d["free_time_hours"] == 2
        assert d["requires_signed_bol"] is True
        assert d["stops"][1]["type"] == "delivery"
        assert d["stops"][1]["lat"] is not None

    def test_first_ping_anchors_and_arrives(self, s):
        d = ping(s, 41.88, -87.63)
        assert d["event"] == "arrived"
        st = d["stops"][0]
        assert st["lat"] == 41.88 and st["lng"] == -87.63
        assert st["arrived_at"] is not None and st["arrived_source"] == "geofence"
        assert "41.88" in st["address"]

    def test_ping_50m_stays_on_site(self, s):
        d = ping(s, 41.88045, -87.63)  # ~50 m north
        assert d["event"] is None
        assert d["stops"][0]["departed_at"] is None
        assert d["stops"][0]["lat"] == 41.88  # anchor not moved

    def test_ping_600m_departs(self, s):
        d = ping(s, 41.8855, -87.63)  # ~610 m
        assert d["event"] == "departed"
        assert d["stops"][0]["departed_at"] is not None
        assert d["stops"][0]["departed_source"] == "geofence"
        # current stop is now delivery: not arrived, coords unchanged
        assert d["stops"][1]["arrived_at"] is None

    def test_next_ping_targets_delivery_no_reanchor(self, s):
        before = s.get(f"{BASE_URL}/api/driver/{TEST_TOK}").json()["stops"][1]
        d = ping(s, 41.8855, -87.63)
        assert d["event"] is None
        assert d["stops"][1]["lat"] == before["lat"] and d["stops"][1]["lng"] == before["lng"]

    def test_reset_restores_fresh(self, s):
        r = s.post(f"{BASE_URL}/api/driver/{TEST_TOK}/reset-test")
        assert r.status_code == 200
        d = r.json()
        assert d["test_load"] is True
        assert d["stops"][0]["lat"] is None
        assert all(st["arrived_at"] is None and st["departed_at"] is None for st in d["stops"])
        g = s.get(f"{BASE_URL}/api/driver/{TEST_TOK}").json()
        assert g["stops"][0]["lat"] is None and g["stops"][0]["arrived_at"] is None
        assert g["stops"][0]["bol_count"] == 0

    def test_reset_then_rearrive_works(self, s):
        d = ping(s, 34.05, -118.25)
        assert d["event"] == "arrived"
        assert d["stops"][0]["lat"] == 34.05
        s.post(f"{BASE_URL}/api/driver/{TEST_TOK}/reset-test")

    def test_reset_forbidden_on_real_load(self, s):
        before = s.get(f"{BASE_URL}/api/driver/{RL_TOK}").json()
        r = s.post(f"{BASE_URL}/api/driver/{RL_TOK}/reset-test")
        assert r.status_code == 403
        assert "test" in r.json()["detail"].lower()
        after = s.get(f"{BASE_URL}/api/driver/{RL_TOK}").json()
        assert after["test_load"] is False
        assert before["stops"][0]["arrived_at"] == after["stops"][0]["arrived_at"]

    def test_reset_invalid_token_404(self, s):
        r = s.post(f"{BASE_URL}/api/driver/doesnotexist123/reset-test")
        assert r.status_code == 404

    def test_rl_ping_no_anchor(self, s):
        # Real loads must never be anchored even if lat were None — just sanity GET payload
        d = s.get(f"{BASE_URL}/api/driver/{RL_TOK}").json()
        assert all(st["lat"] is not None for st in d["stops"])

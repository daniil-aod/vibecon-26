# DockClock Driver mobile app – public driver endpoints + /api/open landing page
import os, uuid, copy, asyncio
import pytest, requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
ON_SITE_TOKEN = "b8dbdcc3c583433bb0183c525f4ab4f52d74b231"  # RL-55018
COMPLETED_TOKEN = "c6f13b08450947f7a4d7d1b94f340178d05b9070"  # APX-30277
JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


@pytest.fixture(scope="module")
def pending_load():
    """Clone RL-55018 into a TEST_ load with an unarrived stop (no reseed needed)."""
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
    ld = run(make())
    yield ld

    async def clean():
        db = _db()
        await db.loads.delete_many({"id": ld["id"]})
        await db.pings.delete_many({"load_id": ld["id"]})
        await db.invoices.delete_many({"load_id": ld["id"]})
    run(clean())


# ---- /api/open landing page
class TestOpenPage:
    def test_valid_token_page(self):
        r = requests.get(f"{BASE_URL}/api/open/{ON_SITE_TOKEN}")
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
        h = r.text
        assert 'data-testid="open-app-button"' in h
        assert f"dockclock://d/{ON_SITE_TOKEN}?api=https%3A%2F%2F" in h
        assert 'data-testid="open-install-steps"' in h
        assert 'data-testid="open-install-pending"' in h
        assert "RL-55018" in h
        assert 'data-testid="open-invalid"' not in h

    def test_invalid_token_page(self):
        r = requests.get(f"{BASE_URL}/api/open/notarealtoken123456")
        assert r.status_code == 200
        assert 'data-testid="open-invalid"' in r.text


# ---- GET /api/driver/{tok}
class TestDriverGet:
    def test_on_site(self):
        r = requests.get(f"{BASE_URL}/api/driver/{ON_SITE_TOKEN}")
        assert r.status_code == 200
        d = r.json()
        assert d["load_number"] == "RL-55018"
        s = d["stops"][0]
        assert s["arrived_at"] and not s["departed_at"] and "free_expires_at" in s and "bol_count" in s
        assert "_id" not in d

    def test_invalid(self):
        r = requests.get(f"{BASE_URL}/api/driver/nope-not-valid-token")
        assert r.status_code == 404 and r.json()["detail"] == "This link is not valid"


# ---- ping / geofence / tap / bol on a cloned TEST_ load
class TestDriverFlow:
    def test_ping_far_no_event(self, pending_load):
        s = pending_load["stops"][0]
        r = requests.post(f"{BASE_URL}/api/driver/{pending_load['driver_token']}/ping",
                          json={"lat": s["lat"] + 1, "lng": s["lng"], "accuracy": 10})
        assert r.status_code == 200 and r.json()["event"] is None
        assert r.json()["stops"][0]["arrived_at"] is None

    def test_depart_before_arrive_400(self, pending_load):
        s = pending_load["stops"][0]
        r = requests.post(f"{BASE_URL}/api/driver/{pending_load['driver_token']}/stops/{s['id']}/tap/depart",
                          json={"lat": s["lat"], "lng": s["lng"], "accuracy": 10})
        assert r.status_code == 400

    def test_ping_geofence_arrival(self, pending_load):
        s = pending_load["stops"][0]
        r = requests.post(f"{BASE_URL}/api/driver/{pending_load['driver_token']}/ping",
                          json={"lat": s["lat"], "lng": s["lng"], "accuracy": 8})
        assert r.status_code == 200
        d = r.json()
        assert d["event"] == "arrived" and d["stops"][0]["arrived_at"]
        g = requests.get(f"{BASE_URL}/api/driver/{pending_load['driver_token']}").json()
        assert g["stops"][0]["arrived_at"] == d["stops"][0]["arrived_at"]

    def test_arrive_again_400(self, pending_load):
        s = pending_load["stops"][0]
        r = requests.post(f"{BASE_URL}/api/driver/{pending_load['driver_token']}/stops/{s['id']}/tap/arrive",
                          json={"lat": s["lat"], "lng": s["lng"], "accuracy": 10})
        assert r.status_code == 400

    def test_bol_octet_stream_accepted(self, pending_load):
        s = pending_load["stops"][0]
        r = requests.post(f"{BASE_URL}/api/driver/{pending_load['driver_token']}/stops/{s['id']}/bol",
                          files={"file": ("bol.jpg", JPEG, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["stops"][0]["bol_count"] == 1

    def test_bol_non_image_rejected(self, pending_load):
        s = pending_load["stops"][0]
        r = requests.post(f"{BASE_URL}/api/driver/{pending_load['driver_token']}/stops/{s['id']}/bol",
                          files={"file": ("notes.txt", b"hello", "application/octet-stream")})
        assert r.status_code == 400

    def test_tap_depart(self, pending_load):
        s = pending_load["stops"][0]
        r = requests.post(f"{BASE_URL}/api/driver/{pending_load['driver_token']}/stops/{s['id']}/tap/depart",
                          json={"lat": s["lat"], "lng": s["lng"], "accuracy": 10})
        assert r.status_code == 200
        st = r.json()["stops"][0]
        assert st["departed_at"] and st["departed_source"] == "driver_tap"

    def test_unknown_action_404(self, pending_load):
        s = pending_load["stops"][0]
        r = requests.post(f"{BASE_URL}/api/driver/{pending_load['driver_token']}/stops/{s['id']}/tap/jump",
                          json={"lat": 0, "lng": 0})
        assert r.status_code == 404

    def test_ping_bad_body_422(self, pending_load):
        r = requests.post(f"{BASE_URL}/api/driver/{pending_load['driver_token']}/ping", json={"lat": "x"})
        assert r.status_code == 422

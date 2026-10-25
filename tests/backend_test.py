"""Comprehensive backend API test for DockClock"""
import os
import sys
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Add tests directory to path for imports
sys.path.insert(0, "/app/tests")
from smoke_backend import get_user, tok

load_dotenv("/app/backend/.env")

# Configuration
BASE_URL = "https://naughty-hugle-13.preview.emergentagent.com/api"
CLERK_SECRET = os.environ["CLERK_SECRET_KEY"]
WEBHOOK_CRON_SECRET = os.environ["WEBHOOK_CRON_SECRET"]

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []
        self.token = None
        self.fleet_id = None
        self.load_id = None
        self.driver_token = None
        self.invoice_id = None
        self.public_token = None
        self.stop_id = None
        
    def log(self, msg, color=Colors.BLUE):
        print(f"{color}{msg}{Colors.END}")
        
    def test(self, name, fn):
        """Run a test and track results"""
        try:
            self.log(f"\n🔍 Testing: {name}")
            fn()
            self.passed += 1
            self.tests.append({"name": name, "status": "PASS"})
            self.log(f"✅ PASS: {name}", Colors.GREEN)
        except AssertionError as e:
            self.failed += 1
            self.tests.append({"name": name, "status": "FAIL", "error": str(e)})
            self.log(f"❌ FAIL: {name} - {str(e)}", Colors.RED)
        except Exception as e:
            self.failed += 1
            self.tests.append({"name": name, "status": "ERROR", "error": str(e)})
            self.log(f"💥 ERROR: {name} - {str(e)}", Colors.RED)
    
    def get_clerk_user(self, email):
        """Get or create Clerk user using smoke_backend helper"""
        return get_user(email)
    
    def get_token(self, user):
        """Get JWT token for user using smoke_backend helper"""
        return tok(user)
    
    def headers(self):
        """Get auth headers"""
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
    
    def summary(self):
        """Print test summary"""
        total = self.passed + self.failed
        self.log(f"\n{'='*60}")
        self.log(f"TEST SUMMARY", Colors.BLUE)
        self.log(f"{'='*60}")
        self.log(f"Total: {total} | Passed: {self.passed} | Failed: {self.failed}")
        if self.failed > 0:
            self.log(f"\nFailed tests:", Colors.RED)
            for t in self.tests:
                if t["status"] != "PASS":
                    self.log(f"  - {t['name']}: {t.get('error', 'Unknown error')}", Colors.RED)
        self.log(f"{'='*60}\n")
        return self.failed == 0

def main():
    runner = TestRunner()
    
    # Setup: Get auth token for existing user
    runner.log("🚀 Starting DockClock Backend Tests", Colors.BLUE)
    runner.log(f"Base URL: {BASE_URL}")
    
    user = runner.get_clerk_user("smoke+clerk_test@example.com")
    runner.token = runner.get_token(user)
    runner.log(f"✓ Authenticated as smoke+clerk_test@example.com")
    
    # Test 1: Protected API without token returns 401
    def test_auth_401():
        r = requests.get(f"{BASE_URL}/me")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    runner.test("AUTH: Protected API returns 401 without token", test_auth_401)
    
    # Test 2: Get user info with token
    def test_me():
        r = requests.get(f"{BASE_URL}/me", headers=runner.headers(), params={"origin": "https://naughty-hugle-13.preview.emergentagent.com"})
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "user" in data, "Missing user in response"
        assert "fleet" in data, "Missing fleet in response"
        if data["fleet"]:
            runner.fleet_id = data["fleet"]["id"]
            runner.log(f"  Fleet: {data['fleet']['name']}")
    runner.test("AUTH: GET /me with valid token", test_me)
    
    # Test 3: Rate con extraction
    def test_extract():
        with open("/tmp/test_ratecon.pdf", "rb") as f:
            r = requests.post(
                f"{BASE_URL}/ratecons/extract",
                headers={"Authorization": f"Bearer {runner.token}"},
                files={"file": ("test.pdf", f, "application/pdf")}
            )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "extracted" in data, "Missing extracted data"
        assert "file_id" in data, "Missing file_id"
        runner.log(f"  Extracted load: {data['extracted'].get('load_number')}")
        return data
    extracted = None
    runner.test("Rate con extraction", lambda: setattr(runner, 'extracted', test_extract()))
    
    # Test 4: Create load
    def test_create_load():
        ex = runner.extracted["extracted"]
        body = {
            "file_id": runner.extracted["file_id"],
            "load_number": ex["load_number"],
            "broker": {**ex["broker"], "email": "delivered@resend.dev"},
            "detention": ex["detention"],
            "stops": ex["stops"],
            "driver": {"name": "Test Driver", "phone": "3125550100"},
            "low_confidence": ex.get("low_confidence", [])
        }
        r = requests.post(f"{BASE_URL}/loads", headers=runner.headers(), json=body)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "id" in data, "Missing load id"
        runner.load_id = data["id"]
        runner.driver_token = data["driver_token"]
        if data.get("stops"):
            runner.stop_id = data["stops"][0]["id"]
        runner.log(f"  Load created: {data['load_number']}")
    runner.test("Create load from extracted data", test_create_load)
    
    # Test 5: Get load detail
    def test_get_load():
        r = requests.get(f"{BASE_URL}/loads/{runner.load_id}", headers=runner.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert data["id"] == runner.load_id, "Load ID mismatch"
        assert len(data["stops"]) > 0, "No stops in load"
    runner.test("GET load detail", test_get_load)
    
    # Test 6: Text driver (expect not configured)
    def test_sms():
        r = requests.post(f"{BASE_URL}/loads/{runner.load_id}/sms", headers=runner.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert data["sent"] == False, "SMS should not be sent (not configured)"
        assert data["reason"] == "not_configured", f"Expected 'not_configured', got {data.get('reason')}"
        assert "driver_url" in data, "Missing driver_url"
        runner.log(f"  SMS not configured (expected): {data['reason']}")
    runner.test("Text driver (expect not_configured)", test_sms)
    
    # Test 7: Driver page GET
    def test_driver_get():
        r = requests.get(f"{BASE_URL}/driver/{runner.driver_token}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "load_number" in data, "Missing load_number"
        assert "stops" in data, "Missing stops"
        runner.log(f"  Driver page loaded for {data['load_number']}")
    runner.test("Driver GET /driver/{token}", test_driver_get)
    
    # Test 8: Driver ping (arrival via geofence)
    def test_driver_ping_arrive():
        # Get stop coordinates
        r = requests.get(f"{BASE_URL}/loads/{runner.load_id}", headers=runner.headers())
        load = r.json()
        stop = load["stops"][0]
        if stop.get("lat") is None:
            runner.log(f"  Skipping: stop has no coordinates", Colors.YELLOW)
            return
        
        # Ping inside geofence
        r = requests.post(
            f"{BASE_URL}/driver/{runner.driver_token}/ping",
            json={"lat": stop["lat"] + 0.0005, "lng": stop["lng"], "accuracy": 15}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert data.get("event") == "arrived", f"Expected 'arrived' event, got {data.get('event')}"
        runner.log(f"  Arrival stamped via geofence")
    runner.test("Driver ping arrival (geofence)", test_driver_ping_arrive)
    
    # Test 9: Driver tap arrive (if not already arrived)
    def test_driver_tap_arrive():
        r = requests.get(f"{BASE_URL}/driver/{runner.driver_token}")
        data = r.json()
        stop = data["stops"][0]
        if stop.get("arrived_at"):
            runner.log(f"  Already arrived, skipping", Colors.YELLOW)
            return
        
        r = requests.post(
            f"{BASE_URL}/driver/{runner.driver_token}/stops/{runner.stop_id}/tap/arrive",
            json={"lat": 41.8, "lng": -87.6, "accuracy": 10}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        runner.log(f"  Arrival tapped")
    runner.test("Driver tap arrive", test_driver_tap_arrive)
    
    # Test 10: Adjust times (dispatcher)
    def test_adjust_times():
        now = datetime.now(timezone.utc)
        arrived = (now - timedelta(hours=3, minutes=40)).isoformat()
        r = requests.post(
            f"{BASE_URL}/loads/{runner.load_id}/stops/{runner.stop_id}/adjust",
            headers=runner.headers(),
            json={"arrived_at": arrived, "reason": "Test adjustment"}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        runner.log(f"  Times adjusted: arrival set to 3h40m ago")
    runner.test("Adjust stop times", test_adjust_times)
    
    # Test 11: Check notice auto-sent (or awaiting approval)
    def test_notice():
        r = requests.get(f"{BASE_URL}/loads/{runner.load_id}", headers=runner.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        stop = data["stops"][0]
        notice = stop.get("notice", {})
        assert notice.get("status") in ["sent", "awaiting_approval"], f"Expected notice sent or awaiting_approval, got {notice.get('status')}"
        runner.log(f"  Notice status: {notice.get('status')}")
    runner.test("Notice auto-sent or awaiting approval", test_notice)
    
    # Test 12: Upload BOL
    def test_bol_upload():
        # Create a small test image
        import io
        from PIL import Image
        img = Image.new('RGB', (100, 100), color='white')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        
        r = requests.post(
            f"{BASE_URL}/driver/{runner.driver_token}/stops/{runner.stop_id}/bol",
            files={"file": ("bol.png", buf, "image/png")}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        runner.log(f"  BOL uploaded")
    runner.test("Upload BOL photo", test_bol_upload)
    
    # Test 13: Driver tap depart
    def test_driver_tap_depart():
        r = requests.post(
            f"{BASE_URL}/driver/{runner.driver_token}/stops/{runner.stop_id}/tap/depart",
            json={"lat": 41.8, "lng": -87.6, "accuracy": 10}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        runner.log(f"  Departure tapped")
    runner.test("Driver tap depart", test_driver_tap_depart)
    
    # Test 14: Invoice created
    def test_invoice_created():
        time.sleep(1)  # Wait for invoice creation
        r = requests.get(f"{BASE_URL}/invoices", headers=runner.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert len(data) > 0, "No invoices found"
        inv = data[0]
        assert inv["status"] == "ready", f"Expected status 'ready', got {inv['status']}"
        runner.invoice_id = inv["id"]
        runner.public_token = inv["public_token"]
        runner.log(f"  Invoice created: {inv['number']} - ${inv['amount']}")
    runner.test("Invoice created after departure", test_invoice_created)
    
    # Test 15: Send invoice
    def test_send_invoice():
        r = requests.post(f"{BASE_URL}/invoices/{runner.invoice_id}/send", headers=runner.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("verification"), "Missing verification"
        runner.log(f"  Invoice sent and sealed")
    runner.test("Send invoice", test_send_invoice)
    
    # Test 16: Public evidence page
    def test_evidence():
        r = requests.get(f"{BASE_URL}/public/evidence/{runner.public_token}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "invoice" in data, "Missing invoice"
        assert "verification" in data, "Missing verification"
        assert data["verification"]["state"] == "verified", f"Expected verified, got {data['verification']['state']}"
        runner.log(f"  Evidence verified: {data['verification']['fingerprint'][:16]}...")
    runner.test("Public evidence page", test_evidence)
    
    # Test 17: Evidence PDF download
    def test_evidence_pdf():
        r = requests.get(f"{BASE_URL}/public/evidence/{runner.public_token}/pdf")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        assert r.headers.get("content-type") == "application/pdf", "Expected PDF content type"
        assert len(r.content) > 1000, "PDF too small"
        runner.log(f"  PDF downloaded: {len(r.content)} bytes")
    runner.test("Evidence PDF download", test_evidence_pdf)
    
    # Test 18: Stripe checkout
    def test_checkout():
        r = requests.post(
            f"{BASE_URL}/public/evidence/{runner.public_token}/checkout",
            json={"origin_url": "https://naughty-hugle-13.preview.emergentagent.com"}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "checkout_url" in data, "Missing checkout_url"
        assert "session_id" in data, "Missing session_id"
        runner.log(f"  Checkout session created")
    runner.test("Stripe checkout session", test_checkout)
    
    # Test 19: Dashboard
    def test_dashboard():
        r = requests.get(f"{BASE_URL}/dashboard", headers=runner.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "headline" in data, "Missing headline"
        assert "kpis" in data, "Missing kpis"
        runner.log(f"  Dashboard loaded")
    runner.test("Dashboard", test_dashboard)
    
    # Test 20: Scorecard
    def test_scorecard():
        r = requests.get(f"{BASE_URL}/scorecard", headers=runner.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "facilities" in data, "Missing facilities"
        assert "brokers" in data, "Missing brokers"
        runner.log(f"  Scorecard loaded")
    runner.test("Scorecard", test_scorecard)
    
    # Test 21: Playback
    def test_playback():
        r = requests.get(f"{BASE_URL}/loads/{runner.load_id}/playback", headers=runner.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "pings" in data, "Missing pings"
        assert "stops" in data, "Missing stops"
        assert "events" in data, "Missing events"
        runner.log(f"  Playback: {len(data['pings'])} pings, {len(data['events'])} events")
    runner.test("Playback data", test_playback)
    
    # Test 22: Cron endpoint (with auth)
    def test_cron_auth():
        r = requests.post(
            f"{BASE_URL}/cron/tick",
            headers={"Authorization": f"Bearer {WEBHOOK_CRON_SECRET}", "X-Webhook-Id": f"test-{int(time.time())}"}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        runner.log(f"  Cron tick successful")
    runner.test("Cron with auth", test_cron_auth)
    
    # Test 23: Cron without auth (should fail)
    def test_cron_no_auth():
        r = requests.post(f"{BASE_URL}/cron/tick")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    runner.test("Cron without auth returns 401", test_cron_no_auth)
    
    # Test 24: Data isolation (create second user)
    def test_data_isolation():
        # Create new user
        user2 = runner.get_clerk_user(f"test{int(time.time())}+clerk_test@example.com")
        token2 = runner.get_token(user2)
        
        # Try to access first user's load
        r = requests.get(
            f"{BASE_URL}/loads/{runner.load_id}",
            headers={"Authorization": f"Bearer {token2}", "Content-Type": "application/json"}
        )
        # Should get 409 (no fleet) or 404 (not found)
        assert r.status_code in [404, 409], f"Expected 404 or 409, got {r.status_code}"
        runner.log(f"  Data isolation verified: {r.status_code}")
    runner.test("Data isolation", test_data_isolation)
    
    # Print summary
    success = runner.summary()
    return 0 if success else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n💥 Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

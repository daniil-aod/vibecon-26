"""Test demo fleet public endpoints and data integrity"""
import sys
import requests

BASE_URL = "https://detention-pay.preview.emergentagent.com/api"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

class DemoTester:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []
        
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
    
    def summary(self):
        """Print test summary"""
        total = self.passed + self.failed
        self.log(f"\n{'='*60}")
        self.log(f"DEMO TEST SUMMARY", Colors.BLUE)
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
    runner = DemoTester()
    
    runner.log("🚀 Starting DockClock Demo Fleet Tests", Colors.BLUE)
    runner.log(f"Base URL: {BASE_URL}")
    
    # Test 1: Active demo driver load
    def test_active_driver_load():
        r = requests.get(f"{BASE_URL}/driver/cfe82998ca8c4601ac02147c806a049a8f33b4f1")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "stops" in data, "Missing stops"
        assert len(data["stops"]) > 0, "No stops in load"
        assert "facility_name" in data["stops"][0], "Missing facility_name"
        runner.log(f"  Load: {data.get('load_number')}, Facility: {data['stops'][0].get('facility_name')}")
    runner.test("Active driver load (RL-55018)", test_active_driver_load)
    
    # Test 2: Public evidence DC-1001 (paid)
    def test_evidence_dc1001():
        r = requests.get(f"{BASE_URL}/public/evidence/f2ff5eb2f3d54cf3810a8ba417ce67be6ecf9566")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "verification" in data, "Missing verification"
        assert data["verification"]["state"] == "verified", f"Expected verified, got {data['verification']['state']}"
        assert "playback" in data, "Missing playback"
        assert "pings" in data["playback"], "Missing pings"
        assert len(data["playback"]["pings"]) > 0, "Empty pings array"
        assert "notices" in data, "Missing notices"
        assert len(data["notices"]) > 0, "No notices found"
        assert "stop" in data, "Missing stop"
        assert "bol" in data["stop"], "Missing bol"
        assert len(data["stop"]["bol"]) > 0, "No BOL entries"
        runner.log(f"  DC-1001: verified, {len(data['playback']['pings'])} pings, {len(data['notices'])} notices, {len(data['stop']['bol'])} BOL")
    runner.test("Public evidence DC-1001 (paid)", test_evidence_dc1001)
    
    # Test 3: Public evidence DC-1003 (sent)
    def test_evidence_dc1003():
        r = requests.get(f"{BASE_URL}/public/evidence/c3ccf3a9b27c43cd80fd7ce9c42060bb7d641591")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert data["verification"]["state"] == "verified", f"Expected verified, got {data['verification']['state']}"
        assert len(data["playback"]["pings"]) > 0, "Empty pings array"
        assert len(data["notices"]) > 0, "No notices found"
        assert len(data["stop"]["bol"]) > 0, "No BOL entries"
        runner.log(f"  DC-1003: verified, {len(data['playback']['pings'])} pings, {len(data['notices'])} notices")
    runner.test("Public evidence DC-1003 (sent)", test_evidence_dc1003)
    
    # Test 4: Public evidence DC-1004 (disputed cap-hit)
    def test_evidence_dc1004():
        r = requests.get(f"{BASE_URL}/public/evidence/6c252d6936f04557b4b94108a15b4ecdf36c33f4")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert data["verification"]["state"] == "verified", f"Expected verified, got {data['verification']['state']}"
        assert len(data["playback"]["pings"]) > 0, "Empty pings array"
        assert len(data["notices"]) > 0, "No notices found"
        assert len(data["stop"]["bol"]) > 0, "No BOL entries"
        # Check cap hit amount
        assert "invoice" in data, "Missing invoice"
        assert data["invoice"]["amount"] == 400.0, f"Expected amount 400.0, got {data['invoice']['amount']}"
        runner.log(f"  DC-1004: verified, amount=$400 (cap hit), {len(data['playback']['pings'])} pings")
    runner.test("Public evidence DC-1004 (disputed cap-hit)", test_evidence_dc1004)
    
    # Test 5: Public evidence PDF
    def test_evidence_pdf():
        r = requests.get(f"{BASE_URL}/public/evidence/f2ff5eb2f3d54cf3810a8ba417ce67be6ecf9566/pdf")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        assert r.headers.get("content-type") == "application/pdf", f"Expected PDF, got {r.headers.get('content-type')}"
        assert len(r.content) > 1000, f"PDF too small: {len(r.content)} bytes"
        runner.log(f"  PDF downloaded: {len(r.content)} bytes")
    runner.test("Public evidence PDF", test_evidence_pdf)
    
    # Test 6: Guarded reseed endpoint (no auth)
    def test_reseed_no_auth():
        r = requests.post(f"{BASE_URL}/demo/reseed")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"
        runner.log(f"  Reseed correctly returns 401 without auth")
    runner.test("Guarded reseed endpoint (no auth)", test_reseed_no_auth)
    
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

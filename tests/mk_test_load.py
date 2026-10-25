# helper: create a TEST_ clone of RL-55018 with unarrived stops for UI tests; prints token
import sys
sys.path.insert(0, "/app/backend/tests")
from test_offline_ping import make_load
ld = make_load()
print(ld["driver_token"], ld["id"], ld["stops"][0]["lat"], ld["stops"][0]["lng"], ld["load_number"])

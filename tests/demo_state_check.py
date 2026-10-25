# Read-only demo fleet state check.
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
demo = db.fleets.find_one({"is_demo": True})
for num in ("EVG-77421", "APX-30277", "APX-30188", "RL-55102", "EVG-77510"):
    l = db.loads.find_one({"fleet_id": demo["id"], "load_number": num}, {"_id": 0, "completion": 1, "id": 1})
    c = (l or {}).get("completion") or {}
    print(num, (c.get("submission") or {}).get("state"), [b["code"] for b in c.get("blockers") or []], (c.get("packet") or {}).get("state"),
          (c.get("payment") or {}))

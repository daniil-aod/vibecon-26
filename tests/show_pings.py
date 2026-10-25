# helper: print stored pings + last_ping for a test load id
import sys, asyncio, os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
load_dotenv("/app/backend/.env")
async def m():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    async for p in db.pings.find({"load_id": sys.argv[1]}, {"_id": 0, "lat": 1, "ts": 1}).sort("_id", 1):
        print(p)
    ld = await db.loads.find_one({"id": sys.argv[1]}, {"_id": 0, "last_ping": 1})
    print("last_ping", ld.get("last_ping"))
asyncio.run(m())

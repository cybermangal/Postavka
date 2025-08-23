# db.py
import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGODB_URI = os.environ["MONGODB_URI"]
MONGO_DB = os.environ.get("MONGO_DB", "telegram_bot")

_client = AsyncIOMotorClient(MONGODB_URI, tls=True)
db = _client[MONGO_DB]

reminders = db["reminders"]
notes = db["notes"]

async def ensure_indexes():
    await reminders.create_index([("when", 1)])
    await reminders.create_index("id", unique=True, sparse=True)
    await notes.create_index([("user_id", 1), ("created_at", -1)])

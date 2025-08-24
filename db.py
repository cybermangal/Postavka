# db.py
import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGODB_URI = os.environ["MONGODB_URI"]
MONGO_DB = os.environ.get("MONGO_DB", "telegram_bot")

_client = AsyncIOMotorClient(MONGODB_URI, tls=True)
db = _client[MONGO_DB]

reminders = db["reminders"]
notes = db["notes"]
access = db["access"]  # хранит списки доступа, например {_id:"allowed", ids:[...int...]}

async def ensure_indexes():
    await reminders.create_index([("when", 1)])
    await reminders.create_index("id", unique=True, sparse=True)
    await notes.create_index([("user_id", 1), ("created_at", -1)])
    # для access достаточно _id по умолчанию

# ===== Utilities for access control =====
async def get_allowed_set() -> set[int]:
    doc = await access.find_one({"_id": "allowed"})
    if not doc:
        return set()
    return {int(x) for x in doc.get("ids", [])}

async def add_allowed(uid: int) -> None:
    await access.update_one({"_id": "allowed"}, {"$addToSet": {"ids": int(uid)}}, upsert=True)

async def remove_allowed(uid: int) -> None:
    await access.update_one({"_id": "allowed"}, {"$pull": {"ids": int(uid)}}, upsert=True)

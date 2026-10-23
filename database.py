import re
import time
from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

import config

client = AsyncIOMotorClient(config.MONGO_URI)
db = client[config.DB_NAME]
users = db.users
msgmap = db.msgmap      # relayed message -> user id
replies = db.replies    # keyword auto-replies
settings = db.settings
admins = db.admins

DEFAULTS = {
    "autoreply": True,     # keyword auto-replies on/off
    "notify": True,        # tell admins which user got an auto-reply
    "welcome": True,       # welcome message on /start
    "confirm": False,      # "message delivered" confirmation to the user
    "match": "word",       # word | contains | exact
    "flood": 10,           # max messages per 10 seconds (0 = off)
    "welcome_msg": None,
    "confirm_text": "✅ Your message has been delivered. We will reply soon.",
}

CACHE: dict = {}
ADMIN_IDS: set = {config.OWNER_ID}
BANNED: set = set()


async def init():
    await msgmap.create_index("t", expireAfterSeconds=90 * 24 * 3600)
    doc = await settings.find_one({"_id": "main"}) or {}
    CACHE.clear()
    CACHE.update(DEFAULTS)
    CACHE.update({k: v for k, v in doc.items() if k != "_id"})
    async for a in admins.find({}):
        ADMIN_IDS.add(a["_id"])
    async for u in users.find({"banned": True}, {"_id": 1}):
        BANNED.add(u["_id"])


# ---------- settings ----------
def get(key):
    return CACHE.get(key, DEFAULTS.get(key))


async def set_setting(key, value):
    CACHE[key] = value
    await settings.update_one({"_id": "main"}, {"$set": {key: value}}, upsert=True)


# ---------- users ----------
async def upsert_user(u, inc=False):
    now = int(time.time())
    update = {
        "$set": {"name": u.full_name, "username": u.username, "last": now},
        "$setOnInsert": {"joined": now},
    }
    if inc:
        update["$inc"] = {"msgs": 1}
    await users.update_one({"_id": u.id}, update, upsert=True)


async def set_ban(uid: int, flag: bool):
    await users.update_one({"_id": uid}, {"$set": {"banned": flag}}, upsert=True)
    if flag:
        BANNED.add(uid)
    else:
        BANNED.discard(uid)


# ---------- admins ----------
async def add_admin(uid: int):
    await admins.update_one({"_id": uid}, {"$set": {"t": int(time.time())}}, upsert=True)
    ADMIN_IDS.add(uid)


async def del_admin(uid: int):
    await admins.delete_one({"_id": uid})
    if uid != config.OWNER_ID:
        ADMIN_IDS.discard(uid)


# ---------- message map (admin chat message -> user) ----------
async def save_map(chat_id: int, msg_id: int, uid: int):
    await msgmap.replace_one(
        {"_id": f"{chat_id}:{msg_id}"},
        {"uid": uid, "t": datetime.now(timezone.utc)},
        upsert=True,
    )


async def get_map(chat_id: int, msg_id: int):
    d = await msgmap.find_one({"_id": f"{chat_id}:{msg_id}"})
    return d["uid"] if d else None


# ---------- keyword auto-replies ----------
async def add_reply(keys: list, content: dict):
    # a keyword can belong to only one reply: newest one wins
    await replies.update_many({}, {"$pull": {"keys": {"$in": keys}}})
    await replies.delete_many({"keys": {"$size": 0}})
    await replies.insert_one({"keys": keys, "content": content, "hits": 0})


async def all_replies():
    return [r async for r in replies.find({}).sort("_id", 1)]


async def get_reply_by_key(key: str):
    return await replies.find_one({"keys": key.lower().strip()})


async def delete_reply_key(key: str) -> int:
    res = await replies.delete_many({"keys": key.lower().strip()})
    return res.deleted_count


async def delete_reply_id(rid: str) -> int:
    res = await replies.delete_one({"_id": ObjectId(rid)})
    return res.deleted_count


async def inc_hits(rid):
    await replies.update_one({"_id": rid}, {"$inc": {"hits": 1}})


def _matches(mode: str, key: str, text: str) -> bool:
    if mode == "exact":
        return text == key
    if mode == "contains":
        return key in text
    return re.search(rf"(?<!\w){re.escape(key)}(?!\w)", text) is not None


async def find_reply(text: str):
    """Returns (reply_doc, matched_keyword) or None. Longest keyword wins."""
    t = " ".join(text.lower().split())
    mode = get("match")
    best = None
    async for r in replies.find({}):
        for k in r["keys"]:
            if _matches(mode, k, t) and (best is None or len(k) > len(best[1])):
                best = (r, k)
    return best

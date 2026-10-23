import html
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import filters

import config
import database as db


class _AdminFilter(filters.MessageFilter):
    def filter(self, message):
        return bool(message.from_user and message.from_user.id in db.ADMIN_IDS)


PRIVATE = filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE
ADMIN = PRIVATE & _AdminFilter()
NOT_ADMIN = PRIVATE & ~_AdminFilter() & ~filters.COMMAND
OWNER = PRIVATE & filters.User(user_id=config.OWNER_ID)


def esc(s) -> str:
    return html.escape(str(s or ""))


def pack(msg) -> dict:
    """Store a message so it can be sent again later (text is stored, media is copied)."""
    if msg.text:
        return {"type": "text", "html": msg.text_html}
    return {"type": "copy", "chat_id": msg.chat_id, "msg_id": msg.message_id}


async def send_packed(bot, chat_id, packed, user=None, reply_markup=None):
    if packed["type"] == "text":
        text = packed["html"]
        if user:
            text = text.replace("{name}", esc(user.first_name)).replace("{id}", str(user.id))
        return await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)
    return await bot.copy_message(
        chat_id, packed["chat_id"], packed["msg_id"], reply_markup=reply_markup
    )


def user_kb(uid: int, name: str, banned: bool = False) -> InlineKeyboardMarkup:
    ban_btn = (
        InlineKeyboardButton("✅ Unban", callback_data=f"unb:{uid}")
        if banned
        else InlineKeyboardButton("🚫 Ban", callback_data=f"ban:{uid}")
    )
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"👤 {(name or 'User')[:22]}", callback_data=f"info:{uid}"), ban_btn]]
    )


async def info_text(uid: int):
    u = await db.users.find_one({"_id": uid})
    if not u:
        return None
    joined = datetime.fromtimestamp(u.get("joined", 0), timezone.utc).strftime("%d %b %Y")
    uname = f"@{u['username']}" if u.get("username") else "-"
    return (
        f"👤 {(u.get('name') or 'User')[:40]}\n"
        f"🆔 {uid}\n"
        f"🔗 {uname}\n"
        f"📅 Joined: {joined}\n"
        f"💬 Messages: {u.get('msgs', 0)}\n"
        f"🚫 Banned: {'yes' if uid in db.BANNED else 'no'}"
    )


HELP_TEXT = """🛠 <b>Admin Panel</b>

<b>💬 Chatting</b>
Reply to any user message the bot sends you and your reply goes to that user (text, photo, video, voice, file - anything).

<b>🤖 Auto-replies (keywords)</b>
First send the content (text/link/photo...) to the bot, then reply to it with:
/addreply keyword1, keyword2
/replies - list and delete
/delreply keyword
/preview keyword

<b>👋 Welcome &amp; confirmation</b>
/setwelcome - reply to a message (text or photo+caption). Use {name} in text.
/welcome - preview | /delwelcome - back to default
/setconfirm text - "message delivered" text
/setflood N - max messages per 10 sec (0 = off)

<b>🚫 Users</b>
/ban id | /unban id | /banned
/info id (or reply to a relayed message)
/stats | /broadcast (reply to a message)

<b>⚙️ Settings</b>
/settings - toggle everything with buttons

<b>👑 Owner only</b>
/addadmin id | /deladmin id | /admins"""

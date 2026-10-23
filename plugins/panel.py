import logging

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import database as db
from utils import ADMIN, esc, info_text, user_kb

log = logging.getLogger(__name__)
MODES = ["word", "contains", "exact"]
MODE_HELP = {
    "word": "whole word (keyword 'one piece' matches 'one piece link')",
    "contains": "anywhere inside the text",
    "exact": "message must be exactly the keyword",
}


def _onoff(v) -> str:
    return "✅ ON" if v else "❌ OFF"


async def _settings_text() -> str:
    n_users = await db.users.count_documents({})
    n_rep = await db.replies.count_documents({})
    return (
        "⚙️ <b>Settings</b>\n\n"
        f"👥 Users: <b>{n_users}</b>\n"
        f"🤖 Auto-replies: <b>{n_rep}</b>\n"
        f"🔎 Match mode: <b>{db.get('match')}</b> - {MODE_HELP[db.get('match')]}\n\n"
        "Tap a button to change. /help shows all commands."
    )


def _settings_kb() -> InlineKeyboardMarkup:
    f = db.get("flood")
    return InlineKeyboardMarkup([
        [Btn(f"🤖 Auto-reply: {_onoff(db.get('autoreply'))}", callback_data="tg:autoreply")],
        [Btn(f"🔔 Notify me on auto-reply: {_onoff(db.get('notify'))}", callback_data="tg:notify")],
        [Btn(f"👋 Welcome message: {_onoff(db.get('welcome'))}", callback_data="tg:welcome")],
        [Btn(f"📨 Delivery confirmation: {_onoff(db.get('confirm'))}", callback_data="tg:confirm")],
        [Btn(f"🔎 Match mode: {db.get('match')}", callback_data="mm")],
        [
            Btn("➖", callback_data="fl:-"),
            Btn(f"🛡 Flood: {f if f else 'OFF'} msg/10s", callback_data="noop"),
            Btn("➕", callback_data="fl:+"),
        ],
    ])


async def _refresh_settings(q):
    try:
        await q.edit_message_text(
            await _settings_text(), parse_mode="HTML", reply_markup=_settings_kb()
        )
    except BadRequest:
        pass


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        await _settings_text(), parse_mode="HTML", reply_markup=_settings_kb()
    )


async def _replies_view():
    items = await db.all_replies()
    if not items:
        return "No auto-replies yet.\nUse /addreply (reply to a content message).", None
    lines, buttons = [], []
    for i, r in enumerate(items[:40], 1):
        keys = esc(", ".join(r["keys"])[:60])
        lines.append(f"{i}. <code>{keys}</code> - {r['content']['type']} - hits: {r.get('hits', 0)}")
        buttons.append(Btn(f"🗑 {i}", callback_data=f"delr:{r['_id']}"))
    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    return "📋 <b>Auto-replies</b>\n\n" + "\n".join(lines), InlineKeyboardMarkup(rows)


async def replies_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await _replies_view()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in db.ADMIN_IDS:
        await q.answer("Not allowed", show_alert=True)
        return
    data = q.data or ""

    if data == "noop":
        await q.answer()

    elif data.startswith("tg:"):
        key = data[3:]
        if key in ("autoreply", "notify", "welcome", "confirm"):
            await db.set_setting(key, not db.get(key))
        await q.answer()
        await _refresh_settings(q)

    elif data == "mm":
        nxt = MODES[(MODES.index(db.get("match")) + 1) % len(MODES)]
        await db.set_setting("match", nxt)
        await q.answer(f"Match mode: {nxt}")
        await _refresh_settings(q)

    elif data in ("fl:+", "fl:-"):
        cur = db.get("flood") or 0
        new = min(60, cur + 1) if data == "fl:+" else max(0, cur - 1)
        await db.set_setting("flood", new)
        await q.answer()
        await _refresh_settings(q)

    elif data.startswith("delr:"):
        await db.delete_reply_id(data[5:])
        await q.answer("🗑 Deleted")
        text, kb = await _replies_view()
        try:
            await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        except TelegramError:
            pass

    elif data.startswith("info:"):
        text = await info_text(int(data[5:]))
        await q.answer(text or "User not found", show_alert=True)

    elif data.startswith(("ban:", "unb:")):
        action, _, sid = data.partition(":")
        uid = int(sid)
        if uid in db.ADMIN_IDS:
            await q.answer("You cannot ban an admin", show_alert=True)
            return
        banning = action == "ban"
        await db.set_ban(uid, banning)
        u = await db.users.find_one({"_id": uid}) or {}
        await q.answer("🚫 User banned" if banning else "✅ User unbanned")
        try:
            await q.edit_message_reply_markup(user_kb(uid, u.get("name", "User"), banning))
        except TelegramError:
            pass


def register(app: Application):
    app.add_handler(CommandHandler("settings", settings_cmd, filters=ADMIN))
    app.add_handler(CommandHandler("replies", replies_cmd, filters=ADMIN))
    app.add_handler(CallbackQueryHandler(on_callback))

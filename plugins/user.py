import logging
import time
from collections import defaultdict, deque

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler

import database as db
from utils import HELP_TEXT, NOT_ADMIN, PRIVATE, esc, send_packed, user_kb

log = logging.getLogger(__name__)
_hits = defaultdict(deque)

DEFAULT_WELCOME = "👋 Hello {name}!\nSend me your message and I will reply as soon as possible."


def _flood_over(uid: int) -> int:
    """Returns how many messages over the limit (<= 0 means fine)."""
    limit = db.get("flood")
    if not limit:
        return 0
    now = time.monotonic()
    q = _hits[uid]
    while q and now - q[0] > 10:
        q.popleft()
    q.append(now)
    return len(q) - limit


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in db.ADMIN_IDS:
        await update.message.reply_text(HELP_TEXT, parse_mode="HTML")
        return
    if user.id in db.BANNED:
        return
    await db.upsert_user(user)
    if not db.get("welcome"):
        return
    w = db.get("welcome_msg")
    if w:
        try:
            await send_packed(context.bot, user.id, w, user)
            return
        except TelegramError as e:
            log.warning("welcome failed: %s", e)
    await update.message.reply_text(DEFAULT_WELCOME.replace("{name}", user.first_name or ""))


async def _relay(context, msg, user):
    """Copy (not forward) the message to every admin, so it works even if the user hides forwards."""
    for admin_id in list(db.ADMIN_IDS):
        try:
            sent = await context.bot.copy_message(
                admin_id, msg.chat_id, msg.message_id,
                reply_markup=user_kb(user.id, user.full_name),
            )
            await db.save_map(admin_id, sent.message_id, user.id)
        except TelegramError as e:
            log.warning("relay to admin %s failed: %s", admin_id, e)


async def _notify_auto(context, user, keyword, text):
    uname = f"@{user.username}" if user.username else "no username"
    body = (
        "🤖 <b>Auto-reply sent</b>\n"
        f"👤 {esc(user.full_name)} ({esc(uname)})\n"
        f"🆔 <code>{user.id}</code>\n"
        f"🔑 Keyword: <code>{esc(keyword)}</code>\n"
        f"💬 Message: {esc(text[:300])}\n\n"
        "<i>Reply to this message to continue chatting with the user.</i>"
    )
    for admin_id in list(db.ADMIN_IDS):
        try:
            sent = await context.bot.send_message(
                admin_id, body, parse_mode="HTML",
                reply_markup=user_kb(user.id, user.full_name),
            )
            await db.save_map(admin_id, sent.message_id, user.id)
        except TelegramError as e:
            log.warning("notify admin %s failed: %s", admin_id, e)


async def on_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, user = update.message, update.effective_user
    if user.id in db.BANNED:
        return

    over = _flood_over(user.id)
    if over > 0:
        if over == 1:
            await msg.reply_text("⏳ You are sending messages too fast. Please slow down.")
        return

    await db.upsert_user(user, inc=True)

    text = msg.text or msg.caption or ""
    if db.get("autoreply") and text:
        found = await db.find_reply(text)
        if found:
            reply, keyword = found
            try:
                await send_packed(context.bot, user.id, reply["content"], user)
            except TelegramError as e:
                log.warning("auto-reply failed (%s), relaying instead", e)
            else:
                await db.inc_hits(reply["_id"])
                if db.get("notify"):
                    await _notify_auto(context, user, keyword, text)
                return

    await _relay(context, msg, user)
    if db.get("confirm"):
        await msg.reply_text(db.get("confirm_text"))


def register(app: Application):
    app.add_handler(CommandHandler("start", start, filters=PRIVATE))
    app.add_handler(MessageHandler(NOT_ADMIN, on_user_message))

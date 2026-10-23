import asyncio
import logging
import time

from telegram import ReactionTypeEmoji, Update
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import config
import database as db
from utils import ADMIN, HELP_TEXT, OWNER, esc, info_text, pack, send_packed

log = logging.getLogger(__name__)


async def _target_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if context.args:
        try:
            return int(context.args[0])
        except ValueError:
            return None
    if msg.reply_to_message:
        return await db.get_map(msg.chat_id, msg.reply_to_message.message_id)
    return None


# ---------- chatting ----------
async def on_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = await db.get_map(msg.chat_id, msg.reply_to_message.message_id)
    if uid is None:
        await msg.reply_text(
            "❌ I could not find the user for this message.\n"
            "Reply to a message that the bot relayed from a user."
        )
        return
    if uid in db.BANNED:
        await msg.reply_text("🚫 This user is banned. Use /unban first.")
        return
    try:
        await context.bot.copy_message(uid, msg.chat_id, msg.message_id)
    except Forbidden:
        await msg.reply_text("⚠️ This user has blocked the bot.")
        return
    except TelegramError as e:
        await msg.reply_text(f"⚠️ Failed to send: {e}")
        return
    try:
        await msg.set_reaction(ReactionTypeEmoji("👍"))
    except TelegramError:
        await msg.reply_text("✅ Sent")


async def on_admin_plain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Reply to a user's message to answer them. Use /help to see all commands."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


# ---------- auto replies ----------
async def addreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    keys = [k.strip().lower() for k in " ".join(context.args).split(",") if k.strip()]
    if not keys or not msg.reply_to_message:
        await msg.reply_text(
            "Usage: first send the reply content (text / link / photo ...), "
            "then reply to it with:\n<code>/addreply keyword1, keyword2</code>",
            parse_mode="HTML",
        )
        return
    await db.add_reply(keys, pack(msg.reply_to_message))
    await msg.reply_text(
        f"✅ Auto-reply saved for: {', '.join(keys)}\n"
        "Note: for photos/files do not delete the content message from this chat."
    )


async def delreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = " ".join(context.args).strip()
    if not key:
        await update.message.reply_text("Usage: /delreply keyword")
        return
    n = await db.delete_reply_key(key)
    await update.message.reply_text("🗑 Deleted." if n else "❌ Keyword not found.")


async def preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = " ".join(context.args).strip()
    r = await db.get_reply_by_key(key) if key else None
    if not r:
        await update.message.reply_text("Usage: /preview keyword (keyword must exist)")
        return
    try:
        await send_packed(context.bot, update.effective_chat.id, r["content"], update.effective_user)
    except TelegramError as e:
        await update.message.reply_text(f"⚠️ Could not send preview: {e}")


# ---------- welcome / confirmation / flood ----------
async def setwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    src = update.message.reply_to_message
    if not src:
        await update.message.reply_text(
            "Reply to a message (text, or photo with caption) with /setwelcome.\n"
            "In text you can use {name}."
        )
        return
    await db.set_setting("welcome_msg", pack(src))
    await update.message.reply_text("✅ Welcome message saved. Check with /welcome")


async def welcome_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = db.get("welcome_msg")
    if not w:
        await update.message.reply_text("Default welcome message is in use.")
        return
    await send_packed(context.bot, update.effective_chat.id, w, update.effective_user)


async def delwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("welcome_msg", None)
    await update.message.reply_text("✅ Back to the default welcome message.")


async def setconfirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text("Usage: /setconfirm your text")
        return
    await db.set_setting("confirm_text", parts[1])
    await update.message.reply_text("✅ Saved. Turn it on from /settings.")


async def setflood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(context.args[0])
        assert 0 <= n <= 100
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Usage: /setflood N  (0 to 100, 0 = off)")
        return
    await db.set_setting("flood", n)
    await update.message.reply_text(f"✅ Flood limit: {n if n else 'OFF'} messages / 10 sec")


# ---------- users ----------
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = await _target_uid(update, context)
    if uid is None:
        await update.message.reply_text("Usage: /ban id  (or reply to a relayed message)")
        return
    if uid in db.ADMIN_IDS:
        await update.message.reply_text("❌ You cannot ban an admin.")
        return
    await db.set_ban(uid, True)
    await update.message.reply_text(f"🚫 Banned {uid}")


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = await _target_uid(update, context)
    if uid is None:
        await update.message.reply_text("Usage: /unban id  (or reply to a relayed message)")
        return
    await db.set_ban(uid, False)
    await update.message.reply_text(f"✅ Unbanned {uid}")


async def banned_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.BANNED:
        await update.message.reply_text("No banned users.")
        return
    lines = []
    for uid in list(db.BANNED)[:50]:
        u = await db.users.find_one({"_id": uid}) or {}
        lines.append(f"• {uid} - {(u.get('name') or 'unknown')[:30]}")
    await update.message.reply_text("🚫 Banned users:\n" + "\n".join(lines))


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = await _target_uid(update, context)
    if uid is None:
        await update.message.reply_text("Usage: /info id  (or reply to a relayed message)")
        return
    text = await info_text(uid)
    await update.message.reply_text(text or "❌ User not found.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = int(time.time())
    total = await db.users.count_documents({})
    banned = await db.users.count_documents({"banned": True})
    active = await db.users.count_documents({"last": {"$gte": now - 86400}})
    agg = await db.users.aggregate([{"$group": {"_id": None, "m": {"$sum": "$msgs"}}}]).to_list(1)
    msgs = agg[0]["m"] if agg else 0
    n_rep = await db.replies.count_documents({})
    await update.message.reply_text(
        "📊 Stats\n"
        f"👥 Users: {total}\n"
        f"🟢 Active (24h): {active}\n"
        f"🚫 Banned: {banned}\n"
        f"💬 Messages received: {msgs}\n"
        f"🤖 Auto-replies: {n_rep}\n"
        f"👮 Admins: {len(db.ADMIN_IDS)}"
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    src = update.message.reply_to_message
    if not src:
        await update.message.reply_text("Reply to the message you want to broadcast with /broadcast")
        return
    ids = [u["_id"] async for u in db.users.find({"banned": {"$ne": True}}, {"_id": 1})]
    status = await update.message.reply_text(f"📣 Broadcasting to {len(ids)} users...")
    ok = fail = 0
    for uid in ids:
        try:
            await context.bot.copy_message(uid, src.chat_id, src.message_id)
            ok += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await context.bot.copy_message(uid, src.chat_id, src.message_id)
                ok += 1
            except TelegramError:
                fail += 1
        except TelegramError:
            fail += 1
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ Broadcast finished\n• Sent: {ok}\n• Failed: {fail}")


# ---------- owner only ----------
async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /addadmin id")
        return
    await db.add_admin(uid)
    await update.message.reply_text(f"✅ {uid} is now an admin. They must press /start in the bot once.")


async def deladmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /deladmin id")
        return
    if uid == config.OWNER_ID:
        await update.message.reply_text("❌ The owner cannot be removed.")
        return
    await db.del_admin(uid)
    await update.message.reply_text(f"✅ {uid} removed from admins.")


async def admins_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [f"• {i}{' (owner)' if i == config.OWNER_ID else ''}" for i in sorted(db.ADMIN_IDS)]
    await update.message.reply_text("👮 Admins:\n" + "\n".join(lines))


def register(app: Application):
    cmds = {
        "help": help_cmd, "addreply": addreply, "delreply": delreply, "preview": preview,
        "setwelcome": setwelcome, "welcome": welcome_preview, "delwelcome": delwelcome,
        "setconfirm": setconfirm, "setflood": setflood,
        "ban": ban, "unban": unban, "banned": banned_list, "info": info,
        "stats": stats, "broadcast": broadcast, "admins": admins_list,
    }
    for name, fn in cmds.items():
        app.add_handler(CommandHandler(name, fn, filters=ADMIN))
    app.add_handler(CommandHandler("addadmin", addadmin, filters=OWNER))
    app.add_handler(CommandHandler("deladmin", deladmin, filters=OWNER))
    app.add_handler(MessageHandler(ADMIN & ~filters.COMMAND & filters.REPLY, on_admin_reply))
    app.add_handler(MessageHandler(ADMIN & ~filters.COMMAND & ~filters.REPLY, on_admin_plain))

import asyncio
import logging

from telegram import Update
from telegram.ext import ApplicationBuilder

import config
import database as db
from plugins import admin, panel, user
from webserver import self_ping, start_web

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("main")


async def on_error(update, context):
    log.error("Update caused error", exc_info=context.error)


async def main():
    await db.init()
    web_runner = await start_web(config.PORT)  # Render needs an open port

    app = ApplicationBuilder().token(config.BOT_TOKEN).concurrent_updates(True).build()
    app.add_error_handler(on_error)
    admin.register(app)
    panel.register(app)
    user.register(app)

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    ping_task = asyncio.create_task(self_ping(config.APP_URL, config.PING_INTERVAL))
    log.info("Bot started as @%s", app.bot.username)

    try:
        await asyncio.Event().wait()
    finally:
        ping_task.cancel()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await web_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

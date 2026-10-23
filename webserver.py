import asyncio
import logging

from aiohttp import ClientSession, ClientTimeout, web

log = logging.getLogger(__name__)


async def _health(request):
    return web.Response(text="Bot is alive ✅")


async def start_web(port: int) -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Web server listening on port %s", port)
    return runner


async def self_ping(url: str, interval: int):
    """Hit our own public URL so Render free tier does not put the service to sleep."""
    if not url:
        log.warning("APP_URL / RENDER_EXTERNAL_URL not set - self ping disabled")
        return
    async with ClientSession(timeout=ClientTimeout(total=20)) as session:
        while True:
            await asyncio.sleep(interval)
            try:
                async with session.get(url) as resp:
                    log.info("Self ping -> %s", resp.status)
            except Exception as e:
                log.warning("Self ping failed: %s", e)

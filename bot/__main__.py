import asyncio
import hashlib
import logging
import signal
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, ErrorEvent

from . import config, db, services
from .handlers import admin, create, mytests, solve, start
from .middlewares import SubscriptionMiddleware, UserMiddleware
from .storage import DbStorage

log = logging.getLogger("bot")


async def on_error(event: ErrorEvent) -> bool:
    log.exception("Handlerda kutilmagan xatolik", exc_info=event.exception)
    update = event.update
    try:
        if update.callback_query:
            await update.callback_query.answer("⚠️ Xatolik yuz berdi. Qaytadan urinib ko'ring.", show_alert=True)
        elif update.message:
            await update.message.answer(
                "⚠️ Kutilmagan xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.\n"
                "Muammo takrorlansa, /start ni bosing."
            )
    except Exception:
        pass
    return True


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=DbStorage())
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(UserMiddleware())
        observer.outer_middleware(SubscriptionMiddleware())
    dp.errors.register(on_error)
    # Tartib muhim: start (ro'yxatdan o'tish) birinchi, mytests (fallback) oxirgi
    dp.include_routers(start.router, admin.router, create.router, solve.router, mytests.router)
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        sys.exit("BOT_TOKEN topilmadi. .env.example faylidan nusxa olib, .env faylini to'ldiring.")
    if not config.ADMIN_IDS:
        log.warning("ADMIN_IDS bo'sh — admin paneldan hech kim foydalana olmaydi.")

    await db.init(config.DATABASE_URL or config.DB_PATH)
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()

    await bot.set_my_commands([
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="help", description="Yordam"),
        BotCommand(command="cancel", description="Amalni bekor qilish"),
    ])
    me = await bot.me()
    log.info("Bot ishga tushdi: @%s", me.username)

    watcher = asyncio.create_task(services.deadline_watcher(bot))
    try:
        if config.WEBHOOK_URL:
            await run_webhook(bot, dp)
        else:
            # Avval o'rnatilgan webhook bo'lsa, polling ishlamaydi - shuning uchun o'chiramiz
            await bot.delete_webhook()
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        watcher.cancel()
        await db.close()
        await bot.session.close()


async def health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_web_app(bot: Bot, dp: Dispatcher, secret: str) -> web.Application:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(app, path=f"/webhook/{secret}")
    return app


async def run_webhook(bot: Bot, dp: Dispatcher) -> None:
    """Server rejimi (Render): Telegram yangiliklarni HTTP orqali yuboradi, / va /health - "tirikmi" tekshiruvi."""
    secret = hashlib.sha256(config.BOT_TOKEN.encode()).hexdigest()[:40]
    runner = web.AppRunner(build_web_app(bot, dp, secret))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
    await bot.set_webhook(
        f"{config.WEBHOOK_URL}/webhook/{secret}",
        secret_token=secret,
        allowed_updates=dp.resolve_used_update_types(),
    )
    log.info("Webhook rejimi: %s, port %s", config.WEBHOOK_URL, config.PORT)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    try:
        await stop.wait()
    finally:
        # Webhook o'chirilmaydi: xizmat uxlab qolsa, Telegram so'rovi uni uyg'otadi
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code:
            print(e.code)

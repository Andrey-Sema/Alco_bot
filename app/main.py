import asyncio
import logging
import functools
import time
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from sqlalchemy import text
from aiohttp import web

from app.core.config import settings
from app.core.database import engine, async_session
from app.models.base import Base
from app.handlers.admin import admin_router
from app.handlers.client import client_router
from app.middlewares.database import DbSessionMiddleware
from app.middlewares.logging import UpdateLoggingMiddleware
from app.middlewares.throttling import ThrottlingMiddleware  # <-- ИМПОРТ ТРОТТЛИНГА

start_time = None
message_count = 0
message_count_lock = asyncio.Lock()

# Глобальные переменные для кэширования healthcheck
last_db_check = 0
db_is_healthy = False

USE_DATABASE = getattr(settings, "use_database", True)


def get_handler_name(handler) -> str:
    while isinstance(handler, functools.partial):
        handler = handler.func
    if hasattr(handler, "__name__"):
        return handler.__name__
    if hasattr(handler, "__class__"):
        return handler.__class__.__name__
    return "unknown_handler"


class DummySessionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        data["session"] = None
        try:
            return await handler(event, data)
        except AttributeError as e:
            if "NoneType" in str(e):
                h_name = get_handler_name(handler)
                logging.warning(f"⚠️ База отключена. Хендлер '{h_name}' заблокирован.")
                if hasattr(event, 'message') and event.message:
                    await event.message.answer("⚠️ База данных временно недоступна.")
                elif hasattr(event, 'answer'):
                    await event.answer("⚠️ База недоступна.")
                return
            raise


class MetricsMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        global message_count
        async with message_count_lock:
            message_count += 1
        start = datetime.now()
        result = await handler(event, data)
        elapsed = (datetime.now() - start).total_seconds()
        h_name = get_handler_name(handler)
        logging.debug(f"⏱️ {h_name} обработан за {elapsed:.3f}с")
        return result


async def healthcheck(request):
    global last_db_check, db_is_healthy
    now = time.time()
    db_status = "disabled"

    if USE_DATABASE:
        # Дергаем Supabase реально только 1 раз в 30 секунд!
        if now - last_db_check > 30:
            try:
                async with engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                db_is_healthy = True
            except Exception as e:
                logging.error(f"🚨 Healthcheck базы провален: {e}")
                db_is_healthy = False
            finally:
                last_db_check = now

        db_status = "connected" if db_is_healthy else "error"
        if not db_is_healthy:
            return web.json_response({"status": "unhealthy", "database": db_status}, status=500)

    return web.json_response({
        "status": "healthy",
        "database": db_status,
        "uptime_seconds": int((datetime.now() - start_time).total_seconds()),
        "messages_processed": message_count
    })


async def on_startup(bot: Bot):
    await bot.delete_webhook(drop_pending_updates=True)
    if USE_DATABASE:
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logging.info("✅ База данных подключена, таблицы синхронизированы.")
        except Exception as e:
            logging.critical(f"🚨 Ошибка инициализации БД: {e}")
    else:
        logging.warning("⚠️ ВНИМАНИЕ: DRY-RUN (Без базы данных).")
    logging.info("🚀 Бот инициализирован.")


async def on_shutdown(bot: Bot):
    global start_time
    uptime = datetime.now() - start_time
    logging.info(f"📊 СТАТИСТИКА: {message_count} сообщений за {uptime}")
    await asyncio.sleep(1)
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    global start_time
    start_time = datetime.now()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    app = web.Application()
    app.router.add_get("/health", healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    dp.update.outer_middleware(UpdateLoggingMiddleware())
    dp.update.middleware(MetricsMiddleware())

    # ПРАВИЛЬНАЯ ИНТЕГРАЦИЯ ТРОТТЛИНГА (Перед базой данных!)
    dp.update.middleware(ThrottlingMiddleware(default_rate=0.5, callback_rate=0.3, critical_rate=3.0))

    if USE_DATABASE:
        dp.update.middleware(DbSessionMiddleware(session_pool=async_session))
    else:
        dp.update.middleware(DummySessionMiddleware())

    dp.include_router(admin_router)
    dp.include_router(client_router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()
        if USE_DATABASE:
            await engine.dispose()
        logging.info("✨ Ресурсы освобождены.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Выход.")
    except RuntimeError as e:
        if "Event loop is closed" not in str(e):
            raise
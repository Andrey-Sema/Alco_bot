import asyncio
import logging
from aiogram import Bot, Dispatcher
from app.core.config import settings
from app.core.database import engine, async_session
from app.models.base import Base
from app.handlers.admin import admin_router
from app.handlers.client import client_router
from app.middlewares.database import DbSessionMiddleware
from app.middlewares.logging import UpdateLoggingMiddleware  # <-- ИМПОРТИРОВАЛИ


async def on_startup(bot: Bot):
    await bot.delete_webhook(drop_pending_updates=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logging.info("Бот успешно запущен и готов к работе.")


async def on_shutdown(bot: Bot):
    logging.info("Бот ложится спать. Закрываем соединения с PostgreSQL...")
    await engine.dispose()
    logging.info("Соединения закрыты. Спокойной ночи.")


async def main():
    # ПРОКАЧАЛИ ФОРМАТ ЛОГОВ ДЛЯ DEVOPS
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    bot = Bot(token=settings.bot_token, parse_mode="HTML")
    dp = Dispatcher()

    # ПОДКЛЮЧАЕМ МИДЛВАРИ
    # Update middleware ловит ВООБЩЕ ВСЁ на самом входе
    dp.update.outer_middleware(UpdateLoggingMiddleware())

    # Message/Callback middleware прокидывает сессию только туда, где она реально нужна
    dp.update.middleware(DbSessionMiddleware(session_pool=async_session))

    # ПОДКЛЮЧАЕМ РОУТЕРЫ
    dp.include_router(admin_router)
    dp.include_router(client_router)

    # ХУКИ
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Процесс принудительно остановлен юзером (Ctrl+C).")
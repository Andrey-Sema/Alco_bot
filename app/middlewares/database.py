# app/middlewares/database.py

from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

class DbSessionMiddleware(BaseMiddleware):
    """
    Мидлварь для автоматического открытия и закрытия сессий SQLAlchemy.
    Она перехватывает апдейт, берет коннект из пула, прокидывает его в хендлер,
    а после завершения хендлера — автоматически закрывает сессию.
    """
    def __init__(self, session_pool: async_sessionmaker):
        super().__init__()
        self.session_pool = session_pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Открываем асинхронную сессию с базой данных
        async with self.session_pool() as session:
            # Прокидываем её в словарь данных, чтобы хендлеры её увидели
            data["session"] = session
            # Передаем управление дальше по цепочке
            return await handler(event, data)
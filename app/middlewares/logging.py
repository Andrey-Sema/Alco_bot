import logging
import time
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update


class UpdateLoggingMiddleware(BaseMiddleware):
    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: Update,
            data: Dict[str, Any],
    ) -> Any:
        # Засекаем время старта
        start_time = time.time()

        # Вытаскиваем юзера и его действие (текст или нажатие кнопки)
        user = None
        action = "Unknown Action"

        if event.message:
            user = event.message.from_user
            action = f"MSG: {event.message.text}"
        elif event.callback_query:
            user = event.callback_query.from_user
            action = f"BTN: {event.callback_query.data}"

        user_info = f"[ID:{user.id} | @{user.username or 'hidden'}]" if user else "[System/Unknown]"

        # Логируем ВХОД
        logging.info(f"📥 ИНПУТ  | {user_info} | Действие: {action}")

        try:
            # Передаем управление дальше (в другие мидлвари и хендлеры)
            result = await handler(event, data)

            # Считаем время выполнения
            execution_time = (time.time() - start_time) * 1000

            # Логируем УСПЕШНЫЙ ВЫХОД
            logging.info(f"✅ АУТПУТ | {user_info} | Время: {execution_time:.2f} мс")

            return result
        except Exception as e:
            # Если где-то внутри всё пошло по пизде и не было поймано
            execution_time = (time.time() - start_time) * 1000
            logging.error(f"❌ КРАШ   | {user_info} | Время: {execution_time:.2f} мс | Ошибка: {e}")
            raise  # Прокидываем ошибку дальше, чтобы aiogram её тоже увидел
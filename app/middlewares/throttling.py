import time
import logging
from typing import Any, Awaitable, Callable, Dict
from collections import defaultdict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery


class ThrottlingMiddleware(BaseMiddleware):
    """
    Умная защита от спама и DDoS.
    - Быстрые клики: гасим часики.
    - Чекаут: жесткий лимит 3 сек (защита от двойного списания).
    """

    def __init__(
            self,
            default_rate: float = 0.5,
            callback_rate: float = 0.3,
            critical_rate: float = 3.0,
            cleanup_after: int = 3600
    ):
        super().__init__()
        self.default_rate = default_rate
        self.callback_rate = callback_rate
        self.critical_rate = critical_rate
        self.cleanup_after = cleanup_after

        self.cache: Dict[int, Dict[str, float]] = defaultdict(dict)
        self.last_cleanup = time.time()

        # Точные совпадения с префиксами из твоего cb_factory.py
        self.critical_actions = {"cart:checkout"}

    def _get_action_type(self, event: TelegramObject) -> str:
        if isinstance(event, CallbackQuery):
            data = event.data or ""
            if any(action in data for action in self.critical_actions):
                return "critical"
            return "callback"
        elif isinstance(event, Message):
            if event.text and event.text.startswith("/"):
                return "command"
            return "message"
        return "other"

    def _get_rate_limit(self, action_type: str) -> float:
        if action_type == "critical":
            return self.critical_rate
        elif action_type == "callback":
            return self.callback_rate
        return self.default_rate

    async def _cleanup_cache(self):
        now = time.time()
        if now - self.last_cleanup < self.cleanup_after:
            return

        max_age = max(self.default_rate, self.callback_rate, self.critical_rate) * 2
        expired_users = []
        for user_id, actions in self.cache.items():
            if all(now - last_time > max_age for last_time in actions.values()):
                expired_users.append(user_id)

        for user_id in expired_users:
            del self.cache[user_id]

        self.last_cleanup = now
        if expired_users:
            logging.debug(f"🧹 Throttling: Очищено {len(expired_users)} устаревших записей")

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if not user:
            return await handler(event, data)

        await self._cleanup_cache()

        action_type = self._get_action_type(event)
        rate_limit = self._get_rate_limit(action_type)
        now = time.time()
        last_time = self.cache[user.id].get(action_type, 0)

        if now - last_time < rate_limit:
            wait_time = rate_limit - (now - last_time)
            if isinstance(event, CallbackQuery):
                if action_type == "critical":
                    await event.answer(f"⏳ Подожди {wait_time:.1f} сек. перед повтором", show_alert=True)
                else:
                    await event.answer()  # Тихо гасим "часики"
                logging.warning(f"🛑 Троттлинг: user={user.id}, type={action_type}, wait={wait_time:.2f}s")
            elif isinstance(event, Message):
                logging.warning(f"🛑 Спам-фильтр: user={user.id}, type={action_type}")
            return  # Блокируем дальнейшее выполнение

        self.cache[user.id][action_type] = now
        return await handler(event, data)
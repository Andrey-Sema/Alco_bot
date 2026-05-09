from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# echo=False в проде, чтобы не засирать логи SQL-запросами
engine = create_async_engine(settings.db_url, echo=False)

# Фабрика сессий для работы с БД в хендлерах
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
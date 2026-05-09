from datetime import datetime
from enum import Enum as PyEnum
from typing import List, Optional

from sqlalchemy import BigInteger, Integer, String, ForeignKey, Enum, CheckConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


# Статусы заказа. Enum гарантирует, что в БД не запишут левый статус типа "xz_kakoy_status"
class OrderStatus(str, PyEnum):
    PENDING = "pending"  # В корзине, оформляется
    PROCESSING = "processing"  # Отправлен менеджеру
    COMPLETED = "completed"  # Выполнен
    CANCELLED = "cancelled"  # Отменен


class User(Base):
    __tablename__ = "users"

    # Telegram ID - идеальный primary key для юзера
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Связи (когда удаляем юзера, удаляется его корзина и история)
    orders: Mapped[List["Order"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    cart_items: Mapped[List["CartItem"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(50), index=True)  # index=True ускоряет поиск по витрине
    name: Mapped[str] = mapped_column(String(100))
    # Защита от дебилов: цена не может быть отрицательной
    price: Mapped[int] = mapped_column(Integer, CheckConstraint('price >= 0'))
    photo_id: Mapped[str] = mapped_column(String(255))
    # Soft delete: менеджер "удаляет" товар, но мы просто скрываем его из витрины
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CartItem(Base):
    __tablename__ = "cart_items"

    # Это временная таблица. Лежит тут, пока юзер не нажмет "Сделать заказ"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    quantity: Mapped[int] = mapped_column(Integer, CheckConstraint('quantity > 0'), default=1)

    user: Mapped["User"] = relationship(back_populates="cart_items")
    product: Mapped["Product"] = relationship()


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="RESTRICT"))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING)
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    # Индекс для быстрой выборки "последние 15 заказов" (ORDER BY created_at DESC LIMIT 15)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)

    user: Mapped["User"] = relationship(back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    # Товар нельзя физически удалить из БД, если он есть в истории заказов (RESTRICT)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(Integer, CheckConstraint('quantity > 0'))

    # КРИТИЧНО ВАЖНО: Фиксируем цену за 1 литр на момент покупки!
    price_per_item: Mapped[int] = mapped_column(Integer, CheckConstraint('price_per_item >= 0'))

    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()
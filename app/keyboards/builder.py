from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.handlers.cb_factory import CategoryClick, ProductClick, CartAction


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Витрина 🍸", callback_data="catalog"))
    builder.row(InlineKeyboardButton(text="Мои заказы 📜", callback_data="history"))
    builder.row(InlineKeyboardButton(text="Инфо о мастере 👤", callback_data="info"))
    builder.row(InlineKeyboardButton(text="Инструкция 📖", callback_data="help"))
    builder.row(InlineKeyboardButton(text="Корзина 🛒", callback_data=CartAction(action="view").pack()))
    builder.adjust(1) # Делаем кнопки в столбик
    return builder.as_markup()


def catalog_kb(categories: list[str]) -> InlineKeyboardMarkup:
    """Список категорий (Водка, Джин и т.д.)"""
    builder = InlineKeyboardBuilder()

    # Динамически создаем кнопки под каждую категорию из БД
    for category in categories:
        builder.button(
            text=category,
            callback_data=CategoryClick(category_name=category).pack()
        )

    builder.adjust(2)  # Автоматически раскидает кнопки по 2 в ряд
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))

    return builder.as_markup()


def products_kb(products, category_name: str) -> InlineKeyboardMarkup:
    """Список товаров в конкретной категории"""
    builder = InlineKeyboardBuilder()

    for product in products:
        # В названии кнопки сразу пишем цену
        builder.row(InlineKeyboardButton(
            text=f"{product.name} — {product.price}грн/л",
            callback_data=ProductClick(product_id=product.id).pack()
        ))

    builder.row(InlineKeyboardButton(text="⬅️ К категориям", callback_data="catalog"))

    return builder.as_markup()


def item_card_kb(product_id: int) -> InlineKeyboardMarkup:
    """Кнопки под фото конкретного товара"""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить в корзину",
            callback_data=CartAction(action="add", product_id=product_id).pack()
        )
    )
    builder.row(InlineKeyboardButton(text="🛒 Перейди в корзину", callback_data=CartAction(action="view").pack()))
    builder.row(InlineKeyboardButton(text="⬅️ К категориям", callback_data="catalog"))

    return builder.as_markup()


def cart_kb(cart_items) -> InlineKeyboardMarkup:
    """Клавиатура внутри корзины для регулировки количества"""
    builder = InlineKeyboardBuilder()

    for item in cart_items:
        # Для каждой позиции создаем ряд с кнопками: [-] Название (Кол-во) [+]
        builder.row(
            InlineKeyboardButton(
                text="➖",
                callback_data=CartAction(action="dec", product_id=item.product_id).pack()
            ),
            InlineKeyboardButton(
                text=f"{item.product.name} ({item.quantity}л)",
                callback_data="ignore"  # Кнопка-пустышка, просто показывает инфу
            ),
            InlineKeyboardButton(
                text="➕",
                callback_data=CartAction(action="inc", product_id=item.product_id).pack()
            )
        )

    # Кнопки действий под списком товаров
    builder.row(InlineKeyboardButton(text="✅ Сделать заказ", callback_data=CartAction(action="checkout").pack()))
    builder.row(InlineKeyboardButton(text="➕ Добавить товары", callback_data="catalog"))

    return builder.as_markup()
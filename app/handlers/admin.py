import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.models.shop import Product

admin_router = Router()

# Фильтр: только для админов из списка в .env
admin_router.message.filter(F.from_user.id.in_(settings.admin_ids))


class AdminStates(StatesGroup):
    add_category = State()
    add_name = State()
    add_price = State()
    add_photo = State()
    edit_price = State()


# --- ПАНЕЛЬ УПРАВЛЕНИЯ ---
@admin_router.message(F.text == "/admin")
async def admin_panel(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_add")],
        [InlineKeyboardButton(text="⚙️ Управление товарами", callback_data="admin_manage")]
    ])
    await message.answer("🛠 <b>Панель администратора</b>", reply_markup=kb)
    return


# --- ДОБАВЛЕНИЕ ТОВАРА ---
@admin_router.callback_query(F.data == "admin_add")
async def start_add(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите категорию (например, Водка):")
    await state.set_state(AdminStates.add_category)
    await callback.answer()
    return


@admin_router.message(AdminStates.add_category)
async def add_cat(message: Message, state: FSMContext):
    await state.update_data(category=message.text.strip())
    await message.answer("Введите название товара:")
    await state.set_state(AdminStates.add_name)
    return


@admin_router.message(AdminStates.add_name)
async def add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Введите цену за литр:")
    await state.set_state(AdminStates.add_price)
    return


@admin_router.message(AdminStates.add_price)
async def add_price(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Нужны только цифры! Попробуй ещё раз:")
        return
    await state.update_data(price=int(message.text))
    await message.answer("Отправьте фото товара:")
    await state.set_state(AdminStates.add_photo)
    return


@admin_router.message(AdminStates.add_photo, F.photo)
async def add_photo(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    try:
        new_prod = Product(
            category=data['category'],
            name=data['name'],
            price=data['price'],
            photo_id=message.photo[-1].file_id
        )
        session.add(new_prod)
        await session.commit()
        await message.answer(f"✅ Товар '{data['name']}' добавлен!")
    except SQLAlchemyError as e:
        await session.rollback()
        logging.error(f"Ошибка при добавлении товара: {e}")
        await message.answer("❌ Ошибка базы данных при сохранении.")
    finally:
        await state.clear()
    return


# --- УПРАВЛЕНИЕ СПИСКОМ ---
@admin_router.callback_query(F.data == "admin_manage")
async def manage_products(callback: CallbackQuery, session: AsyncSession):
    try:
        stmt = select(Product).where(Product.is_active == True)
        products = (await session.execute(stmt)).scalars().all()

        if not products:
            await callback.answer("Витрина пуста!", show_alert=True)
            return

        kb_list = []
        for p in products:
            kb_list.append([InlineKeyboardButton(text=f"{p.name} ({p.price}грн)", callback_data=f"edit_{p.id}")])

        kb = InlineKeyboardMarkup(inline_keyboard=kb_list)
        await callback.message.edit_text("Выберите товар для редактирования:", reply_markup=kb)
    except SQLAlchemyError as e:
        logging.error(f"Ошибка при получении списка товаров: {e}")
        await callback.answer("Ошибка БД", show_alert=True)
    await callback.answer()
    return


@admin_router.callback_query(F.data.startswith("edit_"))
async def edit_product_options(callback: CallbackQuery, session: AsyncSession):
    p_id = int(callback.data.split("_")[1])
    product = await session.get(Product, p_id)

    if not product:
        await callback.answer("Товар не найден")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data=f"price_{p_id}")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data=f"del_{p_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_manage")]
    ])

    await callback.message.edit_text(
        f"Товар: <b>{product.name}</b>\nТекущая цена: {product.price} грн",
        reply_markup=kb
    )
    await callback.answer()
    return


# --- ИЗМЕНЕНИЕ ЦЕНЫ ---
@admin_router.callback_query(F.data.startswith("price_"))
async def change_price_start(callback: CallbackQuery, state: FSMContext):
    p_id = int(callback.data.split("_")[1])
    await state.update_data(edit_id=p_id)
    await callback.message.answer("Введите новую цену за литр:")
    await state.set_state(AdminStates.edit_price)
    await callback.answer()
    return


@admin_router.message(AdminStates.edit_price)
async def change_price_finish(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text.isdigit():
        await message.answer("Введите число!")
        return

    data = await state.get_data()
    p_id = data['edit_id']

    try:
        await session.execute(update(Product).where(Product.id == p_id).values(price=int(message.text)))
        await session.commit()
        await message.answer("✅ Цена успешно обновлена!")
    except SQLAlchemyError as e:
        await session.rollback()
        logging.error(f"Ошибка при обновлении цены (ID {p_id}): {e}")
        await message.answer("❌ Не удалось обновить цену.")
    finally:
        await state.clear()
    return


# --- МЯГКОЕ УДАЛЕНИЕ ---
@admin_router.callback_query(F.data.startswith("del_"))
async def delete_product(callback: CallbackQuery, session: AsyncSession):
    p_id = int(callback.data.split("_")[1])
    try:
        await session.execute(update(Product).where(Product.id == p_id).values(is_active=False))
        await session.commit()
        await callback.answer("🗑 Товар убран с витрины")
        # Возвращаемся к списку товаров
        await manage_products(callback, session)
    except SQLAlchemyError as e:
        await session.rollback()
        logging.error(f"Ошибка при удалении товара (ID {p_id}): {e}")
        await callback.answer("Ошибка удаления", show_alert=True)
    return
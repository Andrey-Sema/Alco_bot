import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.models.shop import Product, User, CartItem, Order, OrderItem, OrderStatus
from app.keyboards.builder import main_menu_kb, catalog_kb, products_kb, item_card_kb, cart_kb
from app.handlers.cb_factory import CategoryClick, ProductClick, CartAction

client_router = Router()


# --- DRY: Вспомогательная функция безопасного редактирования ---
async def safe_edit_or_resend(message: Message, text: str, reply_markup):
    """Меняет сообщение с фото на текст без крашей API Телеграма"""
    if message.photo:
        await message.delete()
        await message.answer(text=text, reply_markup=reply_markup)
    else:
        await message.edit_text(text=text, reply_markup=reply_markup)


@client_router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()
    return


@client_router.message(CommandStart())
async def cmd_start(message: Message, session):
    user_id = message.from_user.id
    username = message.from_user.username
    try:
        await session.merge(User(telegram_id=user_id, username=username))
        await session.commit()
    except SQLAlchemyError as e:
        await session.rollback()
        logging.error(f"Ошибка регистрации юзера {user_id}: {e}")

    await message.answer(
        f"Здарова, {message.from_user.first_name}! 🥂\nВыбирай, что по душе в нашей витрине.",
        reply_markup=main_menu_kb()
    )


@client_router.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery):
    await safe_edit_or_resend(callback.message, "Главное меню. Выбирай, что интересует:", main_menu_kb())
    await callback.answer()


@client_router.callback_query(F.data == "info")
async def show_info(callback: CallbackQuery):
    text = (
        "👤 <b>О мастере:</b>\nЛучший крафтовый алкоголь в Одессе.\n\n"
        "📞 <b>Контакты:</b> @master_alko_odessa\n📍 Самовывоз или доставка."
    )
    await safe_edit_or_resend(callback.message, text, main_menu_kb())
    await callback.answer()


@client_router.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    text = "📖 <b>Инструкция:</b>\n1. Выберите товар в витрине.\n2. Добавьте в корзину.\n3. Сделайте заказ."
    await safe_edit_or_resend(callback.message, text, main_menu_kb())
    await callback.answer()


@client_router.callback_query(F.data == "catalog")
async def show_categories(callback: CallbackQuery, session):
    try:
        stmt = select(Product.category).where(Product.is_active == True).distinct()
        categories = (await session.execute(stmt)).scalars().all()
        if not categories:
            await callback.answer("Витрина пока пуста!", show_alert=True)
            return
        await safe_edit_or_resend(callback.message, "Выберите интересующую группу напитков:", catalog_kb(categories))
    except SQLAlchemyError as e:
        logging.error(f"Ошибка категорий: {e}")
        await callback.answer("Ошибка сервера.", show_alert=True)
    finally:
        await callback.answer()


@client_router.callback_query(CategoryClick.filter())
async def show_products_by_category(callback: CallbackQuery, callback_data: CategoryClick, session):
    try:
        stmt = select(Product).where(Product.category == callback_data.category_name, Product.is_active == True)
        products = (await session.execute(stmt)).scalars().all()
        await safe_edit_or_resend(
            callback.message,
            f"Группа: <b>{callback_data.category_name}</b>\nВыберите напиток:",
            products_kb(products, callback_data.category_name)
        )
    except SQLAlchemyError as e:
        logging.error(f"Ошибка товаров: {e}")
        await callback.answer("Ошибка сервера.", show_alert=True)
    finally:
        await callback.answer()


@client_router.callback_query(ProductClick.filter())
async def show_product_card(callback: CallbackQuery, callback_data: ProductClick, session):
    try:
        product = await session.get(Product, callback_data.product_id)
        if not product:
            await callback.answer("Товар не найден", show_alert=True)
            return

        stmt = select(CartItem.quantity).where(
            CartItem.user_id == callback.from_user.id,
            CartItem.product_id == product.id
        )
        qty_in_cart = (await session.execute(stmt)).scalar_one_or_none() or 0

        await callback.message.delete()
        caption = (
            f"🍷 <b>{product.name}</b>\n\n💰 Цена: {product.price} грн/л\n"
            f"🧪 Категория: {product.category}\n\n<i>{product.description or 'Отличный выбор!'}</i>"
        )
        kb = item_card_kb(product_id=product.id, current_qty=qty_in_cart, category_name=product.category)

        if product.photo_id and len(product.photo_id.strip()) > 5:
            await callback.message.answer_photo(photo=product.photo_id, caption=caption, reply_markup=kb)
        else:
            await callback.message.answer(text=caption, reply_markup=kb)

    except SQLAlchemyError as e:
        logging.error(f"Ошибка карточки: {e}")
        await callback.answer("Ошибка при загрузке товара.", show_alert=True)
    finally:
        await callback.answer()


# ЗАЩИТА ОТ ГОНКИ: with_for_update() блокирует строку от параллельных быстрых кликов
@client_router.callback_query(CartAction.filter(F.action.in_(["card_inc", "card_dec"])))
async def update_cart_from_card(callback: CallbackQuery, callback_data: CartAction, session):
    try:
        stmt = select(CartItem).where(
            CartItem.user_id == callback.from_user.id,
            CartItem.product_id == callback_data.product_id
        ).with_for_update()
        item = (await session.execute(stmt)).scalar_one_or_none()

        if callback_data.action == "card_inc":
            if item:
                item.quantity += 1
            else:
                session.add(CartItem(user_id=callback.from_user.id, product_id=callback_data.product_id, quantity=1))
        elif callback_data.action == "card_dec" and item:
            if item.quantity > 1:
                item.quantity -= 1
            else:
                await session.delete(item)

        await session.commit()

        qty_stmt = select(CartItem.quantity).where(
            CartItem.user_id == callback.from_user.id,
            CartItem.product_id == callback_data.product_id
        )
        new_qty = (await session.execute(qty_stmt)).scalar_one_or_none() or 0
        product = await session.get(Product, callback_data.product_id)

        new_kb = item_card_kb(product_id=product.id, current_qty=new_qty, category_name=product.category)
        await callback.message.edit_reply_markup(reply_markup=new_kb)

    except SQLAlchemyError as e:
        await session.rollback()
        logging.error(f"Ошибка корзины (карточка): {e}")
        await callback.answer("Ошибка БД.", show_alert=True)
    finally:
        await callback.answer()


@client_router.callback_query(CartAction.filter(F.action == "view"))
async def view_cart(callback: CallbackQuery, session):
    try:
        stmt = select(CartItem).options(joinedload(CartItem.product)).where(CartItem.user_id == callback.from_user.id)
        cart_items = (await session.execute(stmt)).scalars().all()

        if not cart_items:
            await safe_edit_or_resend(callback.message, "🛒 Твоя корзина пуста.", main_menu_kb())
            await callback.answer()
            return

        total_amount = sum(item.quantity * item.product.price for item in cart_items)
        text = "🛒 <b>Твоя корзина:</b>\n\n"
        for i, item in enumerate(cart_items, 1):
            text += f"{i}. {item.product.name} — {item.quantity}л x {item.product.price} грн\n"
        text += f"\n💰 <b>Итого: {total_amount} грн</b>"

        await safe_edit_or_resend(callback.message, text, cart_kb(cart_items))
    except SQLAlchemyError as e:
        logging.error(f"Ошибка просмотра корзины: {e}")
        await callback.answer("Ошибка сервера.", show_alert=True)
    finally:
        await callback.answer()


# ЗАЩИТА ОТ ГОНКИ ВНУТРИ КОРЗИНЫ
@client_router.callback_query(CartAction.filter(F.action.in_(["inc", "dec"])))
async def update_cart_item(callback: CallbackQuery, callback_data: CartAction, session):
    try:
        stmt = select(CartItem).where(
            CartItem.user_id == callback.from_user.id,
            CartItem.product_id == callback_data.product_id
        ).with_for_update()
        item = (await session.execute(stmt)).scalar_one_or_none()

        if not item:
            await callback.answer("Товар не найден", show_alert=True)
            return

        if callback_data.action == "inc":
            item.quantity += 1
        elif callback_data.action == "dec":
            if item.quantity > 1:
                item.quantity -= 1
            else:
                await session.delete(item)

        await session.commit()
        await view_cart(callback, session)
    except SQLAlchemyError as e:
        await session.rollback()
        logging.error(f"Ошибка изменения количества в корзине: {e}")
        await callback.answer("Ошибка.", show_alert=True)


@client_router.callback_query(CartAction.filter(F.action == "checkout"))
async def process_checkout(callback: CallbackQuery, session, bot: Bot):
    try:
        stmt = select(CartItem).options(joinedload(CartItem.product)).where(CartItem.user_id == callback.from_user.id)
        cart_items = (await session.execute(stmt)).scalars().all()

        if not cart_items:
            await callback.answer("Корзина пуста!", show_alert=True)
            return

        total_amount = sum(item.quantity * item.product.price for item in cart_items)
        new_order = Order(user_id=callback.from_user.id, status=OrderStatus.PROCESSING, total_amount=total_amount)
        session.add(new_order)
        await session.flush()

        order_text = f"🚨 <b>НОВЫЙ ЗАКАЗ #{new_order.id}</b> 🚨\n👤 Клиент: @{callback.from_user.username or 'скрыт'}\n\n"
        for item in cart_items:
            session.add(OrderItem(order_id=new_order.id, product_id=item.product_id, quantity=item.quantity,
                                  price_per_item=item.product.price))
            order_text += f"▪️ {item.product.name} — {item.quantity}л\n"
            await session.delete(item)

        order_text += f"\n💰 <b>Сумма: {total_amount} грн</b>"
        await session.commit()
        logging.info(f"Чекаут! Заказ #{new_order.id} на {total_amount}грн от {callback.from_user.id}")

        await safe_edit_or_resend(callback.message, f"✅ <b>Заказ #{new_order.id} оформлен!</b>", main_menu_kb())

        try:
            await bot.send_message(chat_id=settings.manager_group_id, text=order_text)
        except Exception as e:
            logging.error(f"Ошибка отправки менеджерам: {e}")

    except SQLAlchemyError as e:
        await session.rollback()
        logging.critical(f"КРИТИЧЕСКАЯ ОШИБКА ЧЕКАУТА {callback.from_user.id}: {e}")
        await callback.answer("❌ Произошла ошибка. Обратитесь в поддержку.", show_alert=True)
    finally:
        await callback.answer()


@client_router.callback_query(F.data == "history")
async def show_order_history(callback: CallbackQuery, session):
    try:
        stmt = (select(Order).options(joinedload(Order.items).joinedload(OrderItem.product))
                .where(Order.user_id == callback.from_user.id).order_by(Order.created_at.desc()).limit(15))
        orders = (await session.execute(stmt)).unique().scalars().all()

        if not orders:
            await safe_edit_or_resend(callback.message, "История пуста!", main_menu_kb())
            await callback.answer()
            return

        text = "📜 <b>Твои последние заказы:</b>\n\n"
        for order in orders:
            text += f"📦 <b>Заказ #{order.id}</b> ({order.created_at.strftime('%d.%m')})\n"
            for item in order.items:
                text += f" ▫️ {item.product.name} ({item.quantity}л)\n"
            text += f"Итого: {order.total_amount} грн\n---\n"

        await safe_edit_or_resend(callback.message, text, main_menu_kb())
    except SQLAlchemyError as e:
        logging.error(f"Ошибка истории: {e}")
        await callback.answer("Ошибка загрузки истории.", show_alert=True)
    finally:
        await callback.answer()
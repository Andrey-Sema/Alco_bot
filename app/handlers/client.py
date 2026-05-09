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


# --- ЗАГЛУШКА ДЛЯ ПУСТЫХ КНОПОК ---
@client_router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    """Гасит часики Телеграма на информационных кнопках"""
    await callback.answer()
    return


# --- СТАРТ И МЕНЮ ---
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
        # Не блокируем юзера, пускаем дальше, но лог записали

    await message.answer(
        f"Здарова, {message.from_user.first_name}! 🥂\n"
        "Выбирай, что по душе в нашей витрине.",
        reply_markup=main_menu_kb()
    )
    return


@client_router.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "Главное меню. Выбирай, что интересует:",
        reply_markup=main_menu_kb()
    )
    await callback.answer()
    return


# --- ИНФО И ПОМОЩЬ ---
@client_router.callback_query(F.data == "info")
async def show_info(callback: CallbackQuery):
    text = (
        "👤 <b>О мастере:</b>\n"
        "Лучший крафтовый алкоголь в Одессе. Только натуральное сырье и проверенные рецепты.\n\n"
        "📞 <b>Контакты:</b> @master_alko_odessa\n"
        "📍 Самовывоз или доставка по городу."
    )
    await callback.message.edit_text(text, reply_markup=main_menu_kb())
    await callback.answer()
    return


@client_router.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    text = (
        "📖 <b>Инструкция к боту:</b>\n\n"
        "1. Перейдите в <b>Витрину</b> и выберите категорию.\n"
        "2. Нажмите на понравившийся напиток для просмотра карточки.\n"
        "3. Добавьте товар в <b>Корзину</b>.\n"
        "4. В корзине можно изменить количество кнопками [+] и [-].\n"
        "5. Нажмите <b>Сделать заказ</b>, и менеджер получит уведомление."
    )
    await callback.message.edit_text(text, reply_markup=main_menu_kb())
    await callback.answer()
    return


# --- ВИТРИНА ---
@client_router.callback_query(F.data == "catalog")
async def show_categories(callback: CallbackQuery, session):
    try:
        stmt = select(Product.category).where(Product.is_active == True).distinct()
        result = await session.execute(stmt)
        categories = [row[0] for row in result.all()]

        if not categories:
            await callback.answer("Витрина пока пуста, заходи позже!", show_alert=True)
            return

        await callback.message.edit_text(
            "Выберите интересующую группу напитков:",
            reply_markup=catalog_kb(categories)
        )
    except SQLAlchemyError as e:
        logging.error(f"Ошибка загрузки категорий: {e}")
        await callback.answer("Ошибка сервера. Попробуй позже.", show_alert=True)
    finally:
        await callback.answer()
    return


@client_router.callback_query(CategoryClick.filter())
async def show_products_by_category(callback: CallbackQuery, callback_data: CategoryClick, session):
    try:
        stmt = select(Product).where(
            Product.category == callback_data.category_name,
            Product.is_active == True
        )
        result = await session.execute(stmt)
        products = result.scalars().all()

        await callback.message.edit_text(
            f"Группа: <b>{callback_data.category_name}</b>\nВыберите напиток:",
            reply_markup=products_kb(products, callback_data.category_name)
        )
    except SQLAlchemyError as e:
        logging.error(f"Ошибка загрузки товаров категории {callback_data.category_name}: {e}")
        await callback.answer("Ошибка сервера.", show_alert=True)
    finally:
        await callback.answer()
    return


@client_router.callback_query(ProductClick.filter())
async def show_product_card(callback: CallbackQuery, callback_data: ProductClick, session):
    try:
        product = await session.get(Product, callback_data.product_id)

        if not product:
            await callback.answer("Товар не найден", show_alert=True)
            return

        await callback.message.delete()

        caption = (
            f"<b>{product.name}</b>\n\n"
            f"💰 Цена: {product.price} грн/л\n"
            f"🧪 Группа: {product.category}\n\n"
            f"<i>Нажми кнопку ниже, чтобы добавить в корзину.</i>"
        )

        await callback.message.answer_photo(
            photo=product.photo_id,
            caption=caption,
            reply_markup=item_card_kb(product.id)
        )
    except SQLAlchemyError as e:
        logging.error(f"Ошибка загрузки карточки товара {callback_data.product_id}: {e}")
        await callback.answer("Ошибка при загрузке товара.", show_alert=True)
    finally:
        await callback.answer()
    return


@client_router.callback_query(CartAction.filter(F.action == "add"))
async def add_to_cart(callback: CallbackQuery, callback_data: CartAction, session):
    try:
        stmt = select(CartItem).where(
            CartItem.user_id == callback.from_user.id,
            CartItem.product_id == callback_data.product_id
        )
        result = await session.execute(stmt)
        cart_item = result.scalar_one_or_none()

        if cart_item:
            cart_item.quantity += 1
        else:
            new_item = CartItem(user_id=callback.from_user.id, product_id=callback_data.product_id)
            session.add(new_item)

        await session.commit()
        await callback.answer("✅ Успешно добавлено!", show_alert=False)
    except SQLAlchemyError as e:
        await session.rollback()
        logging.error(f"Ошибка добавления в корзину юзера {callback.from_user.id}: {e}")
        await callback.answer("❌ Ошибка при добавлении. Попробуй еще раз.", show_alert=True)
    return


# --- КОРЗИНА ---
@client_router.callback_query(CartAction.filter(F.action == "view"))
async def view_cart(callback: CallbackQuery, session):
    try:
        stmt = select(CartItem).options(joinedload(CartItem.product)).where(CartItem.user_id == callback.from_user.id)
        cart_items = (await session.execute(stmt)).scalars().all()

        if not cart_items:
            text = "🛒 Твоя корзина пуста."
            if callback.message.photo:
                await callback.message.delete()
                await callback.message.answer(text, reply_markup=main_menu_kb())
            else:
                await callback.message.edit_text(text, reply_markup=main_menu_kb())
            await callback.answer()
            return

        total_amount = sum(item.quantity * item.product.price for item in cart_items)
        text = "🛒 <b>Твоя корзина:</b>\n\n"
        for i, item in enumerate(cart_items, 1):
            text += f"{i}. {item.product.name} — {item.quantity}л x {item.product.price} грн\n"
        text += f"\n💰 <b>Итого: {total_amount} грн</b>"

        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=cart_kb(cart_items))
        else:
            await callback.message.edit_text(text, reply_markup=cart_kb(cart_items))
    except SQLAlchemyError as e:
        logging.error(f"Ошибка просмотра корзины {callback.from_user.id}: {e}")
        await callback.answer("Ошибка сервера.", show_alert=True)
    finally:
        await callback.answer()
    return


@client_router.callback_query(CartAction.filter(F.action.in_(["inc", "dec"])))
async def update_cart_item(callback: CallbackQuery, callback_data: CartAction, session):
    try:
        stmt = select(CartItem).where(
            CartItem.user_id == callback.from_user.id,
            CartItem.product_id == callback_data.product_id
        )
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
        await view_cart(callback, session)  # Перерисовываем корзину
    except SQLAlchemyError as e:
        await session.rollback()
        logging.error(f"Ошибка изменения количества в корзине: {e}")
        await callback.answer("Ошибка. Попробуй еще раз.", show_alert=True)
    return


# --- ЧЕКАУТ (КРИТИЧЕСКИЙ УЗЕЛ) ---
@client_router.callback_query(CartAction.filter(F.action == "checkout"))
async def process_checkout(callback: CallbackQuery, session, bot: Bot):
    try:
        stmt = select(CartItem).options(joinedload(CartItem.product)).where(CartItem.user_id == callback.from_user.id)
        cart_items = (await session.execute(stmt)).scalars().all()

        if not cart_items:
            await callback.answer("Корзина пуста!", show_alert=True)
            return

        total_amount = sum(item.quantity * item.product.price for item in cart_items)

        # 1. Создаем заказ
        new_order = Order(user_id=callback.from_user.id, status=OrderStatus.PROCESSING, total_amount=total_amount)
        session.add(new_order)
        await session.flush()  # Получаем ID заказа

        order_text = f"🚨 <b>НОВЫЙ ЗАКАЗ #{new_order.id}</b> 🚨\n👤 Клиент: @{callback.from_user.username or 'скрыт'}\n\n"

        # 2. Переносим позиции и удаляем из корзины
        for item in cart_items:
            order_item = OrderItem(order_id=new_order.id, product_id=item.product_id, quantity=item.quantity,
                                   price_per_item=item.product.price)
            session.add(order_item)
            order_text += f"▪️ {item.product.name} — {item.quantity}л\n"
            await session.delete(item)

        order_text += f"\n💰 <b>Сумма: {total_amount} грн</b>"

        # 3. Коммитим транзакцию
        await session.commit()

        # Логируем успешную продажу для бизнес-аналитики
        logging.info(
            f"Успешный чекаут! Заказ #{new_order.id} на сумму {total_amount} грн от юзера {callback.from_user.id}")

        await callback.message.edit_text(f"✅ <b>Заказ #{new_order.id} оформлен!</b>", reply_markup=main_menu_kb())

        # 4. Отправляем в группу менеджеров
        try:
            await bot.send_message(chat_id=settings.manager_group_id, text=order_text)
        except Exception as e:
            logging.error(f"Ошибка отправки в группу менеджеров: {e}")

    except SQLAlchemyError as e:
        await session.rollback()  # Откатываем ВСЁ, если где-то ебнулось
        logging.critical(f"КРИТИЧЕСКАЯ ОШИБКА ЧЕКАУТА у юзера {callback.from_user.id}: {e}")
        await callback.answer("❌ Произошла ошибка при оформлении заказа. Пожалуйста, обратитесь в поддержку.",
                              show_alert=True)
    finally:
        await callback.answer()
    return


# --- ИСТОРИЯ ---
@client_router.callback_query(F.data == "history")
async def show_order_history(callback: CallbackQuery, session):
    try:
        stmt = (
            select(Order)
            .options(joinedload(Order.items).joinedload(OrderItem.product))
            .where(Order.user_id == callback.from_user.id)
            .order_by(Order.created_at.desc())
            .limit(15)
        )
        orders = (await session.execute(stmt)).unique().scalars().all()

        if not orders:
            await callback.answer("История пуста!", show_alert=True)
            return

        text = "📜 <b>Твои последние заказы:</b>\n\n"
        for order in orders:
            text += f"📦 <b>Заказ #{order.id}</b> ({order.created_at.strftime('%d.%m')})\n"
            for item in order.items:
                text += f" ▫️ {item.product.name} ({item.quantity}л)\n"
            text += f"Итого: {order.total_amount} грн\n---\n"

        await callback.message.edit_text(text, reply_markup=main_menu_kb())
    except SQLAlchemyError as e:
        logging.error(f"Ошибка загрузки истории заказов: {e}")
        await callback.answer("Ошибка загрузки истории.", show_alert=True)
    finally:
        await callback.answer()
    return
from aiogram.filters.callback_data import CallbackData

class CategoryClick(CallbackData, prefix="cat"):
    category_name: str

class ProductClick(CallbackData, prefix="prod"):
    product_id: int

class CartAction(CallbackData, prefix="cart"):
    action: str  # add, remove, view, checkout
    product_id: int | None = None
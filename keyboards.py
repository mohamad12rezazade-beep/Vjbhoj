from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎁 ساخت قرعه‌کشی", callback_data="create_lottery"))
    builder.row(InlineKeyboardButton(text="📋 قرعه‌کشی‌های فعال", callback_data="active_lotteries"))
    builder.row(InlineKeyboardButton(text="👤 قرعه‌کشی‌های من", callback_data="my_lotteries"))
    builder.row(InlineKeyboardButton(text="📊 آمار ربات", callback_data="stats"))
    builder.row(InlineKeyboardButton(text="📖 راهنما", callback_data="help"))
    return builder.as_markup()

def back_to_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به منو", callback_data="main_menu"))
    return builder.as_markup()

def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ لغو", callback_data="main_menu"))
    return builder.as_markup()

def confirm_lottery_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ ساخت قرعه‌کشی", callback_data="confirm_create"))
    builder.row(InlineKeyboardButton(text="❌ لغو", callback_data="main_menu"))
    return builder.as_markup()

def lottery_join_kb(lottery_id: int, bot_username: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎉 شرکت در قرعه‌کشی", url=f"https://t.me/{bot_username}?start=join_{lottery_id}"))
    return builder.as_markup()

def join_lottery_inline_kb(lottery_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎉 شرکت در قرعه‌کشی", callback_data=f"join_{lottery_id}"))
    return builder.as_markup()

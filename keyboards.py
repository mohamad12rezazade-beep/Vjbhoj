from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
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

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_USERNAME = "BOT_TEKvcxBOT"

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

def lottery_join_kb(lottery_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎉 شرکت در قرعه‌کشی", url=f"https://t.me/{BOT_USERNAME}?start=join_{lottery_id}"))
    return builder.as_markup()

def join_confirm_kb(lottery_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ بله، شرکت می‌کنم", callback_data=f"do_join_{lottery_id}"),
        InlineKeyboardButton(text="❌ خیر", callback_data="main_menu")
    )
    return builder.as_markup()

def must_join_channels_kb(channels: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ch in channels:
        builder.row(InlineKeyboardButton(text=f"📢 عضویت در {ch}", url=f"https://t.me/{ch.replace('@', '')}"))
    builder.row(InlineKeyboardButton(text="✅ عضو شدم", callback_data="check_join_membership"))
    return builder.as_markup()

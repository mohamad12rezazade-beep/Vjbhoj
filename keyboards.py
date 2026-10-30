from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# منوی اصلی
def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 ساخت قرعه‌کشی",
                    callback_data="create_giveaway"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌐 قرعه‌کشی‌های فعال ربات",
                    callback_data="active_giveaways"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 قرعه‌کشی‌های من",
                    callback_data="my_giveaways"
                )
            ]
        ]
    )


# دکمه شرکت در قرعه‌کشی
def giveaway_keyboard(giveaway_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎉 شرکت در قرعه‌کشی",
                    callback_data=f"join_{giveaway_id}"
                )
            ]
        ]
    )


# دکمه‌های مدیریت قرعه‌کشی
def manage_giveaway_keyboard(giveaway_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 آمار شرکت‌کنندگان",
                    callback_data=f"stats_{giveaway_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏸ توقف قرعه‌کشی",
                    callback_data=f"stop_{giveaway_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ لغو قرعه‌کشی",
                    callback_data=f"cancel_{giveaway_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 مشاهده برندگان",
                    callback_data=f"winners_{giveaway_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data="back_home"
                )
            ]
        ]
    )


# دکمه تأیید و انصراف
def confirm_keyboard(yes_callback, no_callback):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید",
                    callback_data=yes_callback
                ),
                InlineKeyboardButton(
                    text="❌ انصراف",
                    callback_data=no_callback
                )
            ]
        ]
    )


# دکمه بازگشت
def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت به منوی اصلی",
                    callback_data="back_home"
                )
            ]
        ]
    )


# دکمه بررسی عضویت
def verify_keyboard(giveaway_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بررسی عضویت",
                    callback_data=f"verify_{giveaway_id}"
                )
            ]
        ]
)

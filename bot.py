import asyncio
import logging
import random
import json
import re

from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS

from database import (
    connect_db,
    close_db,
    save_user,
    create_giveaway,
    get_giveaway,
    get_active_giveaways,
    get_user_giveaways,
    get_required_channels,
    add_participant,
    get_participants,
    save_winners,
    get_winners,
    finish_giveaway,
    cancel_giveaway
)

from states import CreateGiveaway


# =====================================
# LOGGING
# =====================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# =====================================
# MAIN MENU
# =====================================

def main_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 ساخت قرعه‌کشی",
                    callback_data="create"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 قرعه‌کشی‌های فعال ربات",
                    callback_data="active"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 قرعه‌کشی‌های من",
                    callback_data="mine"
                )
            ]
        ]
    )


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


def channel_keyboard(channels, giveaway_id):

    buttons = []

    for channel in channels:

        if channel["invite_link"]:

            buttons.append([
                InlineKeyboardButton(
                    text=f"عضویت در {channel['title'] or 'کانال'}",
                    url=channel["invite_link"]
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            text="✅ بررسی عضویت",
            callback_data=f"verify_{giveaway_id}"
        )
    ])

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


def management_keyboard(giveaway_id):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 آمار",
                    callback_data=f"stats_{giveaway_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 برندگان",
                    callback_data=f"winners_{giveaway_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ لغو قرعه‌کشی",
                    callback_data=f"cancel_gw_{giveaway_id}"
                )
            ]
        ]
    )


# =====================================
# HELPERS
# =====================================

def is_admin(user_id):

    return user_id in ADMIN_IDS


def parse_integer(text):

    try:
        return int(text.strip())

    except (ValueError, AttributeError):
        return None


async def check_bot_admin(chat_id):

    try:

        member = await bot.get_chat_member(
            chat_id,
            bot.id
        )

        return member.status in (
            "administrator",
            "creator"
        )

    except Exception:

        logging.exception("Bot admin check failed")

        return False


async def get_channel_information(channel):

    chat = await bot.get_chat(channel)

    if chat.username:

        invite_link = f"https://t.me/{chat.username}"

    else:

        invite = await bot.create_chat_invite_link(
            chat.id
        )

        invite_link = invite.invite_link

    return {
        "chat_id": str(chat.id),
        "title": chat.title or str(chat.id),
        "invite_link": invite_link
    }


async def is_user_member(user_id, chat_id):

    try:

        member = await bot.get_chat_member(
            chat_id,
            user_id
        )

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except Exception:

        logging.exception("Membership check failed")

        return False


# =====================================
# START
# =====================================

@dp.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext
):

    await state.clear()

    user = message.from_user

    await save_user(
        user.id,
        user.username,
        user.first_name
    )

    parts = message.text.split(maxsplit=1)

    if len(parts) > 1:

        match = re.fullmatch(
            r"gw_(\d+)_ref_(\d+)",
            parts[1].strip()
        )

        if match:

            giveaway_id = int(match.group(1))
            referrer_id = int(match.group(2))

            if referrer_id != user.id:

                await state.update_data(
                    pending_giveaway_id=giveaway_id,
                    pending_referrer_id=referrer_id
                )

    await message.answer(
        "سلام! به ربات قرعه‌کشی خوش اومدی 🎉\n\n"
        "از منوی زیر استفاده کن:",
        reply_markup=main_menu()
    )


# =====================================
# CREATE GIVEAWAY
# =====================================

@dp.callback_query(F.data == "create")
async def create_start(
    callback: CallbackQuery,
    state: FSMContext
):

    if not is_admin(callback.from_user.id):

        await callback.answer(
            "اجازه ساخت قرعه‌کشی نداری.",
            show_alert=True
        )

        return

    await state.clear()

    await state.set_state(
        CreateGiveaway.winner_count
    )

    await callback.message.answer(
        "🏆 تعداد برنده‌ها رو وارد کن:"
    )

    await callback.answer()


@dp.message(CreateGiveaway.winner_count)
async def winner_count_handler(
    message: Message,
    state: FSMContext
):

    value = parse_integer(message.text)

    if value is None or value < 1 or value > 100:

        await message.answer(
            "تعداد برنده‌ها باید بین ۱ تا ۱۰۰ باشه."
        )

        return

    await state.update_data(
        winner_count=value
    )

    await state.set_state(
        CreateGiveaway.prizes
    )

    await message.answer(
        "🎁 جایزه هر رتبه رو در یک خط وارد کن.\n\n"
        "مثال:\n"
        "جایزه رتبه اول\n"
        "جایزه رتبه دوم"
    )


@dp.message(CreateGiveaway.prizes)
async def prizes_handler(
    message: Message,
    state: FSMContext
):

    if not message.text:

        await message.answer("لطفاً متن ارسال کن.")

        return

    prizes = [
        line.strip()
        for line in message.text.splitlines()
        if line.strip()
    ]

    data = await state.get_data()

    if len(prizes) != data["winner_count"]:

        await message.answer(
            f"باید دقیقاً {data['winner_count']} جایزه وارد کنی."
        )

        return

    await state.update_data(
        prizes=prizes
    )

    await state.set_state(
        CreateGiveaway.min_users
    )

    await message.answer(
        "👥 حداقل تعداد شرکت‌کننده‌ها چقدر باشه؟"
    )


@dp.message(CreateGiveaway.min_users)
async def min_users_handler(
    message: Message,
    state: FSMContext
):

    value = parse_integer(message.text)

    if value is None or value < 1:

        await message.answer("یک عدد معتبر وارد کن.")

        return

    await state.update_data(
        min_users=value
    )

    await state.set_state(
        CreateGiveaway.max_users
    )

    await message.answer(
        "👥 حداکثر تعداد شرکت‌کننده‌ها چقدر باشه؟"
    )


@dp.message(CreateGiveaway.max_users)
async def max_users_handler(
    message: Message,
    state: FSMContext
):

    value = parse_integer(message.text)

    data = await state.get_data()

    if value is None or value < data["min_users"]:

        await message.answer(
            "حداکثر باید بزرگ‌تر یا مساوی حداقل باشه."
        )

        return

    await state.update_data(
        max_users=value
    )

    await state.set_state(
        CreateGiveaway.duration
    )

    await message.answer(
        "⏰ مدت قرعه‌کشی رو به ساعت وارد کن:"
    )


@dp.message(CreateGiveaway.duration)
async def duration_handler(
    message: Message,
    state: FSMContext
):

    value = parse_integer(message.text)

    if value is None or value < 1:

        await message.answer(
            "مدت باید حداقل یک ساعت باشه."
        )

        return

    await state.update_data(
        duration=value
    )

    await state.set_state(
        CreateGiveaway.mode
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 انتخاب تصادفی",
                    callback_data="mode_random"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 بیشترین دعوت",
                    callback_data="mode_referral"
                )
            ]
        ]
    )

    await message.answer(
        "روش انتخاب برنده رو انتخاب کن:",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("mode_"))
async def mode_handler(
    callback: CallbackQuery,
    state: FSMContext
):

    mode = callback.data.replace("mode_", "")

    if mode not in ("random", "referral"):

        await callback.answer(
            "روش نامعتبره.",
            show_alert=True
        )

        return

    await state.update_data(
        mode=mode,
        required_channels=[]
    )

    await state.set_state(
        CreateGiveaway.required_channels
    )

    await callback.message.answer(
        "📢 آیدی یا لینک کانال‌های عضویت اجباری رو بفرست.\n\n"
        "هر کانال در یک خط.\n"
        "اگر کانالی نداری بنویس: ندارد"
    )

    await callback.answer()


@dp.message(CreateGiveaway.required_channels)
async def required_channels_handler(
    message: Message,
    state: FSMContext
):

    text = message.text.strip()

    channels = []

    if text.lower() not in (
        "ندارد",
        "ندارم",
        "none",
        "no"
    ):

        items = [
            item.strip()
            for item in text.splitlines()
            if item.strip()
        ]

        if len(items) > 20:

            await message.answer(
                "حداکثر ۲۰ کانال می‌تونی وارد کنی."
            )

            return

        for item in items:

            try:

                info = await get_channel_information(item)

                if not await check_bot_admin(info["chat_id"]):

                    await message.answer(
                        f"ربات در کانال {info['title']} ادمین نیست."
                    )

                    return

                channels.append(info)

            except Exception:

                logging.exception(
                    "Required channel information error"
                )

                await message.answer(
                    f"کانال {item} پیدا نشد یا ربات بهش دسترسی نداره."
                )

                return

    await state.update_data(
        required_channels=channels
    )

    await state.set_state(
        CreateGiveaway.target_channel
    )

    await message.answer(
        "📣 آیدی یا لینک کانال انتشار قرعه‌کشی رو بفرست:"
    )


@dp.message(CreateGiveaway.target_channel)
async def target_channel_handler(
    message: Message,
    state: FSMContext
):

    try:

        chat = await bot.get_chat(
            message.text.strip()
        )

        if not await check_bot_admin(chat.id):

            await message.answer(
                "ربات باید در کانال مقصد ادمین باشه."
            )

            return

        await state.update_data(
            target_channel=str(chat.id),
            target_title=chat.title
        )

        await state.set_state(
            CreateGiveaway.post_text
        )

        await message.answer(
            "✍️ متن پست قرعه‌کشی رو ارسال کن:"
        )

    except Exception:

        logging.exception("Target channel error")

        await message.answer(
            "کانال پیدا نشد. آیدی یا لینک رو بررسی کن."
        )


@dp.message(CreateGiveaway.post_text)
async def post_text_handler(
    message: Message,
    state: FSMContext
):

    if not message.text:

        await message.answer(
            "لطفاً متن ساده ارسال کن."
        )

        return

    await state.update_data(
        post_text=message.text
    )

    data = await state.get_data()

    preview = (
        "📋 پیش‌نمایش قرعه‌کشی:\n\n"
        f"🏆 برندگان: {data['winner_count']}\n"
        f"🎁 جوایز:\n"
        + "\n".join(data["prizes"])
        + f"\n\n👥 حداقل: {data['min_users']}"
        + f"\n👥 حداکثر: {data['max_users']}"
        + f"\n⏰ مدت: {data['duration']} ساعت"
        + f"\n🎯 روش: {data['mode']}"
        + f"\n📢 کانال: {data['target_title']}"
        + f"\n\n📝 متن پست:\n{data['post_text']}"
        + "\n\nبرای انتشار تأیید کن:"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ ساخت قرعه‌کشی",
                    callback_data="confirm_create"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ لغو",
                    callback_data="abort_creation"
                )
            ]
        ]
    )

    await message.answer(
        preview,
        reply_markup=keyboard
    )


# =====================================
# CONFIRM CREATION
# =====================================

@dp.callback_query(F.data == "confirm_create")
async def confirm_giveaway(
    callback: CallbackQuery,
    state: FSMContext
):

    if not is_admin(callback.from_user.id):

        await callback.answer(
            "اجازه نداری.",
            show_alert=True
        )

        return

    data = await state.get_data()

    required = [
        "winner_count",
        "prizes",
        "min_users",
        "max_users",
        "duration",
        "mode",
        "target_channel",
        "post_text",
        "required_channels"
    ]

    if any(key not in data for key in required):

        await callback.answer(
            "اطلاعات قرعه‌کشی ناقصه. دوباره بساز.",
            show_alert=True
        )

        await state.clear()

        return

    giveaway_id = None

    try:

        await save_user(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name
        )

        giveaway_id = await create_giveaway(
            creator_id=callback.from_user.id,
            winner_count=data["winner_count"],
            prizes=data["prizes"],
            min_users=data["min_users"],
            max_users=data["max_users"],
            duration=data["duration"],
            mode=data["mode"],
            target_channel=data["target_channel"],
            post_text=data["post_text"],
            required_channels=data["required_channels"]
        )

        post = (
            f"{data['post_text']}\n\n"
            f"🏆 تعداد برنده‌ها: {data['winner_count']}\n"
            f"👥 حداقل شرکت‌کننده: {data['min_users']}\n"
            f"👥 حداکثر شرکت‌کننده: {data['max_users']}\n"
            f"⏰ مدت: {data['duration']} ساعت"
        )

        await bot.send_message(
            int(data["target_channel"]),
            post,
            reply_markup=giveaway_keyboard(giveaway_id)
        )

        await callback.message.answer(
            f"✅ قرعه‌کشی شماره {giveaway_id} منتشر شد.",
            reply_markup=main_menu()
        )

        await state.clear()

    except Exception:

        logging.exception(
            "Giveaway creation or publication failed"
        )

        if giveaway_id is not None:

            try:
                await cancel_giveaway(giveaway_id)

            except Exception:
                logging.exception("Could not cancel giveaway")

        await callback.message.answer(
            "❌ خطا در ساخت یا انتشار قرعه‌کشی.\n"
            "گزارش کامل خطا در لاگ اجرا ثبت شده."
        )

    await callback.answer()


# =====================================
# CANCEL CREATION
# =====================================

@dp.callback_query(F.data == "abort_creation")
async def abort_creation_handler(
    callback: CallbackQuery,
    state: FSMContext
):

    await state.clear()

    await callback.answer(
        "ساخت قرعه‌کشی لغو شد."
    )

    try:

        await callback.message.edit_text(
            "❌ ساخت قرعه‌کشی لغو شد."
        )

    except Exception:

        await callback.message.answer(
            "❌ ساخت قرعه‌کشی لغو شد."
        )

    await callback.message.answer(
        "منوی اصلی:",
        reply_markup=main_menu()
    )


# =====================================
# JOIN
# =====================================

async def register_participant(
    giveaway_id,
    user_id,
    username,
    first_name,
    referrer_id=None
):

    await save_user(
        user_id,
        username,
        first_name
    )

    return await add_participant(
        giveaway_id,
        user_id,
        referrer_id
    )


@dp.callback_query(F.data.startswith("join_"))
async def join_giveaway(
    callback: CallbackQuery,
    state: FSMContext
):

    giveaway_id = parse_integer(
        callback.data.replace("join_", "")
    )

    if giveaway_id is None:

        await callback.answer(
            "شناسه نامعتبره.",
            show_alert=True
        )

        return

    giveaway = await get_giveaway(giveaway_id)

    if not giveaway or giveaway["status"] != "active":

        await callback.answer(
            "این قرعه‌کشی فعال نیست.",
            show_alert=True
        )

        return

    channels = await get_required_channels(
        giveaway_id
    )

    not_joined = []

    for channel in channels:

        if not await is_user_member(
            callback.from_user.id,
            channel["chat_id"]
        ):

            not_joined.append(channel)

    if not_joined:

        await callback.message.answer(
            "برای شرکت، ابتدا در کانال‌های زیر عضو شو:",
            reply_markup=channel_keyboard(
                not_joined,
                giveaway_id
            )
        )

        await callback.answer()

        return

    await verify_and_register(
        callback,
        giveaway_id,
        state
    )


@dp.callback_query(F.data.startswith("verify_"))
async def verify_handler(
    callback: CallbackQuery,
    state: FSMContext
):

    giveaway_id = parse_integer(
        callback.data.replace("verify_", "")
    )

    if giveaway_id is None:

        await callback.answer(
            "شناسه نامعتبره.",
            show_alert=True
        )

        return

    giveaway = await get_giveaway(giveaway_id)

    if not giveaway or giveaway["status"] != "active":

        await callback.answer(
            "قرعه‌کشی پایان یافته.",
            show_alert=True
        )

        return

    channels = await get_required_channels(
        giveaway_id
    )

    for channel in channels:

        if not await is_user_member(
            callback.from_user.id,
            channel["chat_id"]
        ):

            await callback.answer(
                "هنوز در همه کانال‌ها عضو نشدی.",
                show_alert=True
            )

            return

    await verify_and_register(
        callback,
        giveaway_id,
        state
    )


async def verify_and_register(
    callback,
    giveaway_id,
    state
):

    data = await state.get_data()

    referrer_id = None

    if data.get("pending_giveaway_id") == giveaway_id:

        referrer_id = data.get(
            "pending_referrer_id"
        )

    success, result = await register_participant(
        giveaway_id,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.first_name,
        referrer_id
    )

    if success:

        await state.clear()

        await callback.message.answer(
            "🎉 با موفقیت در قرعه‌کشی شرکت کردی!"
        )

        try:

            me = await bot.get_me()

            link = (
                f"https://t.me/{me.username}"
                f"?start=gw_{giveaway_id}_ref_{callback.from_user.id}"
            )

            await callback.message.answer(
                "🔗 لینک دعوت اختصاصی تو:\n"
                f"{link}"
            )

        except Exception:

            logging.exception(
                "Referral link creation failed"
            )

    else:

        errors = {
            "ended": "این قرعه‌کشی پایان یافته.",
            "already_joined": "قبلاً شرکت کردی.",
            "full": "ظرفیت قرعه‌کشی تکمیل شده."
        }

        await callback.answer(
            errors.get(result, "ثبت‌نام انجام نشد."),
            show_alert=True
        )

        return

    await callback.answer()


# =====================================
# ACTIVE GIVEAWAYS
# =====================================

@dp.callback_query(F.data == "active")
async def active_handler(
    callback: CallbackQuery
):

    try:

        giveaways = await get_active_giveaways()

        if not giveaways:

            await callback.message.answer(
                "📭 در حال حاضر قرعه‌کشی فعالی وجود نداره.",
                reply_markup=main_menu()
            )

            await callback.answer()

            return

        await callback.message.answer(
            f"📋 تعداد قرعه‌کشی‌های فعال: {len(giveaways)}"
        )

        for giveaway in giveaways:

            text = (
                f"🎁 قرعه‌کشی شماره {giveaway['id']}\n\n"
                f"🏆 تعداد برنده‌ها: {giveaway['winner_count']}\n"
                f"👥 ظرفیت: {giveaway['max_users']}\n"
                f"🎯 روش: {giveaway['mode']}\n"
                f"⏰ زمان پایان: {giveaway['ends_at']}"
            )

            await callback.message.answer(
                text,
                reply_markup=giveaway_keyboard(
                    giveaway["id"]
                )
            )

    except Exception:

        logging.exception(
            "Active giveaways handler failed"
        )

        await callback.message.answer(
            "❌ دریافت قرعه‌کشی‌ها با خطا مواجه شد."
        )

    await callback.answer()


# =====================================
# MY GIVEAWAYS
# =====================================

@dp.callback_query(F.data == "mine")
async def mine_handler(
    callback: CallbackQuery
):

    try:

        giveaways = await get_user_giveaways(
            callback.from_user.id
        )

        if not giveaways:

            await callback.message.answer(
                "📭 هنوز هیچ قرعه‌کشی‌ای نساختی.",
                reply_markup=main_menu()
            )

            await callback.answer()

            return

        await callback.message.answer(
            f"👤 تعداد قرعه‌کشی‌های ساخته‌شده توسط تو: {len(giveaways)}"
        )

        for giveaway in giveaways:

            text = (
                f"🎁 قرعه‌کشی شماره {giveaway['id']}\n\n"
                f"🏆 تعداد برنده‌ها: {giveaway['winner_count']}\n"
                f"👥 حداکثر شرکت‌کننده: {giveaway['max_users']}\n"
                f"📌 وضعیت: {giveaway['status']}\n"
                f"⏰ پایان: {giveaway['ends_at']}"
            )

            await callback.message.answer(
                text,
                reply_markup=management_keyboard(
                    giveaway["id"]
                )
            )

    except Exception:

        logging.exception(
            "My giveaways handler failed"
        )

        await callback.message.answer(
            "❌ دریافت قرعه‌کشی‌های تو با خطا مواجه شد."
        )

    await callback.answer()


# =====================================
# STATISTICS
# =====================================

@dp.callback_query(F.data.startswith("stats_"))
async def stats_handler(
    callback: CallbackQuery
):

    giveaway_id = parse_integer(
        callback.data.replace("stats_", "")
    )

    if giveaway_id is None:

        await callback.answer(
            "شناسه نامعتبره.",
            show_alert=True
        )

        return

    giveaway = await get_giveaway(
        giveaway_id
    )

    if (
        not giveaway
        or giveaway["creator_id"] != callback.from_user.id
    ):

        await callback.answer(
            "اجازه دسترسی نداری.",
            show_alert=True
        )

        return

    participants = await get_participants(
        giveaway_id
    )

    referral_total = sum(
        p["referral_count"]
        for p in participants
    )

    await callback.message.answer(
        f"📊 آمار قرعه‌کشی {giveaway_id}\n\n"
        f"👥 شرکت‌کننده‌ها: {len(participants)}\n"
        f"🔗 دعوت‌های معتبر: {referral_total}\n"
        f"🏆 تعداد برنده‌ها: {giveaway['winner_count']}\n"
        f"📌 وضعیت: {giveaway['status']}"
    )

    await callback.answer()


# =====================================
# WINNERS
# =====================================

@dp.callback_query(F.data.startswith("winners_"))
async def winners_handler(
    callback: CallbackQuery
):

    giveaway_id = parse_integer(
        callback.data.replace("winners_", "")
    )

    if giveaway_id is None:

        await callback.answer(
            "شناسه نامعتبره.",
            show_alert=True
        )

        return

    giveaway = await get_giveaway(
        giveaway_id
    )

    if (
        not giveaway
        or giveaway["creator_id"] != callback.from_user.id
    ):

        await callback.answer(
            "اجازه دسترسی نداری.",
            show_alert=True
        )

        return

    winners = await get_winners(
        giveaway_id
    )

    if not winners:

        await callback.message.answer(
            "هنوز برنده‌ای ثبت نشده."
        )

    else:

        text = "🏆 برندگان قرعه‌کشی:\n\n"

        for winner in winners:

            text += (
                f"رتبه {winner['position']}: "
                f"{winner['user_id']}\n"
            )

        await callback.message.answer(text)

    await callback.answer()


# =====================================
# CANCEL GIVEAWAY
# =====================================

@dp.callback_query(F.data.startswith("cancel_gw_"))
async def cancel_handler(
    callback: CallbackQuery
):

    giveaway_id = parse_integer(
        callback.data.replace("cancel_gw_", "")
    )

    if giveaway_id is None:

        await callback.answer(
            "شناسه نامعتبره.",
            show_alert=True
        )

        return

    giveaway = await get_giveaway(
        giveaway_id
    )

    if (
        not giveaway
        or giveaway["creator_id"] != callback.from_user.id
    ):

        await callback.answer(
            "اجازه لغو این قرعه‌کشی رو نداری.",
            show_alert=True
        )

        return

    result = await cancel_giveaway(
        giveaway_id
    )

    if result:

        await callback.message.edit_reply_markup(
            reply_markup=None
        )

        await callback.message.answer(
            f"❌ قرعه‌کشی شماره {giveaway_id} لغو شد."
        )

    else:

        await callback.answer(
            "این قرعه‌کشی فعال نیست.",
            show_alert=True
        )

        return

    await callback.answer()


# =====================================
# FINISH GIVEAWAY
# =====================================

async def finish_giveaway_process(giveaway):

    giveaway_id = giveaway["id"]

    participants = await get_participants(
        giveaway_id
    )

    if len(participants) < giveaway["min_users"]:

        result = await finish_giveaway(
            giveaway_id
        )

        if result:

            await bot.send_message(
                int(giveaway["target_channel"]),
                f"قرعه‌کشی {giveaway_id} به حداقل تعداد شرکت‌کننده نرسید."
            )

        return

    if giveaway["mode"] == "referral":

        ordered = sorted(
            participants,
            key=lambda p: p["referral_count"],
            reverse=True
        )

        winners = ordered[:giveaway["winner_count"]]

    else:

        winners = random.sample(
            participants,
            min(
                len(participants),
                giveaway["winner_count"]
            )
        )

    winner_data = [
        {"user_id": winner["user_id"]}
        for winner in winners
    ]

    await save_winners(
        giveaway_id,
        winner_data
    )

    result = await finish_giveaway(
        giveaway_id
    )

    if not result:
        return

    winners = await get_winners(
        giveaway_id
    )

    text = (
        f"🏆 نتایج قرعه‌کشی شماره {giveaway_id}\n\n"
    )

    for winner in winners:

        text += (
            f"رتبه {winner['position']}: "
            f"{winner['user_id']}\n"
        )

    prizes = giveaway["prizes"]

    if isinstance(prizes, str):
        prizes = json.loads(prizes)

    text += "\n🎁 جوایز:\n"

    for prize in prizes:
        text += f"• {prize}\n"

    await bot.send_message(
        int(giveaway["target_channel"]),
        text
    )


# =====================================
# AUTOMATIC WORKER
# =====================================

async def giveaway_worker():

    while True:

        try:

            giveaways = await get_active_giveaways()

            now = datetime.now(timezone.utc)

            for giveaway in giveaways:

                if giveaway["ends_at"] <= now:

                    try:

                        await finish_giveaway_process(
                            giveaway
                        )

                    except Exception:

                        logging.exception(
                            "Finishing giveaway %s failed",
                            giveaway["id"]
                        )

        except Exception:

            logging.exception(
                "Giveaway worker failed"
            )

        await asyncio.sleep(30)


# =====================================
# MAIN
# =====================================

async def main():

    await connect_db()

    worker = asyncio.create_task(
        giveaway_worker()
    )

    try:

        await dp.start_polling(bot)

    finally:

        worker.cancel()

        try:
            await worker

        except asyncio.CancelledError:
            pass

        await close_db()

        await bot.session.close()


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print("Bot stopped")

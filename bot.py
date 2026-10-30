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


logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# =====================================
# KEYBOARDS
# =====================================

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎁 ساخت قرعه‌کشی",
                callback_data="create"
            )
        ],
        [
            InlineKeyboardButton(
                text="📋 قرعه‌کشی‌های فعال",
                callback_data="active"
            )
        ],
        [
            InlineKeyboardButton(
                text="👤 قرعه‌کشی‌های من",
                callback_data="mine"
            )
        ]
    ])


def giveaway_keyboard(giveaway_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎉 شرکت در قرعه‌کشی",
                callback_data=f"join_{giveaway_id}"
            )
        ]
    ])


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

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =====================================
# HELPERS
# =====================================

def is_admin(user_id):
    return user_id in ADMIN_IDS


async def check_bot_admin(chat_id):
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        return member.status in ("administrator", "creator")
    except Exception:
        logging.exception("Could not check bot admin status")
        return False


async def get_channel_information(channel):
    chat = await bot.get_chat(channel)

    if chat.username:
        invite_link = f"https://t.me/{chat.username}"
    else:
        invite = await bot.create_chat_invite_link(chat.id)
        invite_link = invite.invite_link

    return {
        "chat_id": str(chat.id),
        "title": chat.title or str(chat.id),
        "invite_link": invite_link
    }


async def is_user_member(user_id, chat_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except Exception:
        logging.exception("Membership check failed")
        return False


def parse_integer(text):
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None


# =====================================
# START
# =====================================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):

    await state.clear()

    user = message.from_user

    await save_user(
        user.id,
        user.username,
        user.first_name
    )

    referrer_id = None

    parts = message.text.split(maxsplit=1)

    if len(parts) > 1:
        match = re.fullmatch(
            r"gw_(\d+)_ref_(\d+)",
            parts[1].strip()
        )

        if match:
            giveaway_id = int(match.group(1))
            referrer_id = int(match.group(2))

            await state.update_data(
                pending_giveaway_id=giveaway_id,
                pending_referrer_id=referrer_id
            )

    await message.answer(
        "سلام! به ربات قرعه‌کشی خوش اومدی 🎉",
        reply_markup=main_menu()
    )


# =====================================
# CREATE GIVEAWAY
# =====================================

@dp.callback_query(F.data == "create")
async def create_start(callback: CallbackQuery, state: FSMContext):

    if not is_admin(callback.from_user.id):
        await callback.answer("اجازه ساخت قرعه‌کشی نداری.", show_alert=True)
        return

    await state.clear()
    await state.set_state(CreateGiveaway.winner_count)

    await callback.message.answer(
        "تعداد برنده‌ها رو وارد کن:"
    )

    await callback.answer()


@dp.message(CreateGiveaway.winner_count)
async def winner_count_handler(message: Message, state: FSMContext):

    value = parse_integer(message.text)

    if value is None or value < 1 or value > 100:
        await message.answer("یک عدد بین ۱ تا ۱۰۰ وارد کن.")
        return

    await state.update_data(winner_count=value)
    await state.set_state(CreateGiveaway.prizes)

    await message.answer(
        "جایزه هر رتبه رو وارد کن.\n"
        "مثال:\n"
        "رتبه اول: ۱۰۰ هزار تومان\n"
        "رتبه دوم: ۵۰ هزار تومان"
    )


@dp.message(CreateGiveaway.prizes)
async def prizes_handler(message: Message, state: FSMContext):

    text = message.text.strip()

    prizes = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    data = await state.get_data()

    if len(prizes) != data["winner_count"]:
        await message.answer(
            f"باید دقیقاً {data['winner_count']} جایزه وارد کنی."
        )
        return

    await state.update_data(prizes=prizes)
    await state.set_state(CreateGiveaway.min_users)

    await message.answer("حداقل تعداد شرکت‌کننده‌ها چقدر باشه؟")


@dp.message(CreateGiveaway.min_users)
async def min_users_handler(message: Message, state: FSMContext):

    value = parse_integer(message.text)

    if value is None or value < 1:
        await message.answer("یک عدد معتبر وارد کن.")
        return

    await state.update_data(min_users=value)
    await state.set_state(CreateGiveaway.max_users)

    await message.answer("حداکثر تعداد شرکت‌کننده‌ها چقدر باشه؟")


@dp.message(CreateGiveaway.max_users)
async def max_users_handler(message: Message, state: FSMContext):

    value = parse_integer(message.text)
    data = await state.get_data()

    if value is None or value < data["min_users"]:
        await message.answer(
            "حداکثر باید بزرگ‌تر یا مساوی حداقل باشه."
        )
        return

    await state.update_data(max_users=value)
    await state.set_state(CreateGiveaway.duration)

    await message.answer("مدت قرعه‌کشی به ساعت چقدر باشه؟")


@dp.message(CreateGiveaway.duration)
async def duration_handler(message: Message, state: FSMContext):

    value = parse_integer(message.text)

    if value is None or value < 1:
        await message.answer("مدت باید حداقل یک ساعت باشه.")
        return

    await state.update_data(duration=value)
    await state.set_state(CreateGiveaway.mode)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎲 تصادفی",
                callback_data="mode_random"
            )
        ],
        [
            InlineKeyboardButton(
                text="👥 بیشترین دعوت",
                callback_data="mode_referral"
            )
        ]
    ])

    await message.answer(
        "روش انتخاب برنده رو مشخص کن:",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("mode_"))
async def mode_handler(callback: CallbackQuery, state: FSMContext):

    mode = callback.data.replace("mode_", "")

    if mode not in ("random", "referral"):
        await callback.answer("روش نامعتبر است.", show_alert=True)
        return

    await state.update_data(
        mode=mode,
        required_channels=[]
    )

    await state.set_state(CreateGiveaway.required_channels)

    await callback.message.answer(
        "آیدی یا لینک کانال‌های عضویت اجباری رو بفرست.\n"
        "هر کانال در یک خط.\n"
        "اگر کانال اجباری نداری، بنویس: ندارد"
    )

    await callback.answer()


@dp.message(CreateGiveaway.required_channels)
async def required_channels_handler(message: Message, state: FSMContext):

    text = message.text.strip()

    channels = []

    if text.lower() not in ("ندارد", "ندارم", "none", "no"):

        items = [
            item.strip()
            for item in text.splitlines()
            if item.strip()
        ]

        if len(items) > 20:
            await message.answer("حداکثر ۲۰ کانال می‌تونی وارد کنی.")
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
                logging.exception("Required channel error")
                await message.answer(
                    f"اطلاعات کانال {item} دریافت نشد. "
                    "آیدی یا لینک را بررسی کن."
                )
                return

    await state.update_data(required_channels=channels)
    await state.set_state(CreateGiveaway.target_channel)

    await message.answer(
        "آیدی یا لینک کانالی که قرعه‌کشی باید در آن منتشر بشه رو بفرست."
    )


@dp.message(CreateGiveaway.target_channel)
async def target_channel_handler(message: Message, state: FSMContext):

    try:
        chat = await bot.get_chat(message.text.strip())

        if not await check_bot_admin(chat.id):
            await message.answer("ربات باید در کانال مقصد ادمین باشه.")
            return

        await state.update_data(
            target_channel=str(chat.id),
            target_title=chat.title
        )

        await state.set_state(CreateGiveaway.post_text)

        await message.answer(
            "متن پست قرعه‌کشی رو بفرست."
        )

    except Exception:
        logging.exception("Target channel error")
        await message.answer(
            "کانال پیدا نشد. آیدی یا لینک کانال رو بررسی کن."
        )


@dp.message(CreateGiveaway.post_text)
async def post_text_handler(message: Message, state: FSMContext):

    if not message.text:
        await message.answer("لطفاً متن ساده ارسال کن.")
        return

    await state.update_data(post_text=message.text)

    data = await state.get_data()

    preview = (
        "🎁 پیش‌نمایش قرعه‌کشی\n\n"
        f"🏆 تعداد برنده‌ها: {data['winner_count']}\n"
        f"🎁 جوایز:\n" +
        "\n".join(data["prizes"]) +
        f"\n\n👥 حداقل شرکت‌کننده: {data['min_users']}"
        f"\n👥 حداکثر شرکت‌کننده: {data['max_users']}"
        f"\n⏰ مدت: {data['duration']} ساعت"
        f"\n🎯 روش: {data['mode']}"
        f"\n📢 کانال مقصد: {data['target_title']}"
        f"\n\n📝 متن پست:\n{data['post_text']}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ تأیید و انتشار",
                callback_data="confirm_create"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ لغو",
                callback_data="cancel_create"
            )
        ]
    ])

    await state.set_state(CreateGiveaway.post_text)

    await message.answer(
        preview,
        reply_markup=keyboard
    )


@dp.callback_query(F.data == "confirm_create")
async def confirm_giveaway(callback: CallbackQuery, state: FSMContext):

    if not is_admin(callback.from_user.id):
        await callback.answer("اجازه نداری.", show_alert=True)
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
        await callback.answer("اطلاعات ناقص است.", show_alert=True)
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

        text = (
            f"{data['post_text']}\n\n"
            f"🏆 تعداد برنده‌ها: {data['winner_count']}\n"
            f"👥 حداقل شرکت‌کننده: {data['min_users']}\n"
            f"👥 حداکثر شرکت‌کننده: {data['max_users']}\n"
            f"⏰ مدت: {data['duration']} ساعت"
        )

        await bot.send_message(
            int(data["target_channel"]),
            text,
            reply_markup=giveaway_keyboard(giveaway_id)
        )

        await callback.message.answer(
            f"قرعه‌کشی شماره {giveaway_id} با موفقیت منتشر شد. 🎉",
            reply_markup=main_menu()
        )

        await state.clear()

    except Exception as error:

        logging.exception("Giveaway creation/publication failed")

        if giveaway_id is not None:
            try:
                await cancel_giveaway(giveaway_id)
            except Exception:
                logging.exception("Could not cancel failed giveaway")

        await callback.message.answer(
            f"خطا در ساخت یا انتشار قرعه‌کشی:\n{error}"
        )

    await callback.answer()


@dp.callback_query(F.data == "cancel_create")
async def cancel_create(callback: CallbackQuery, state: FSMContext):

    await state.clear()

    await callback.message.answer(
        "ساخت قرعه‌کشی لغو شد.",
        reply_markup=main_menu()
    )

    await callback.answer()


# =====================================
# JOIN GIVEAWAY
# =====================================

async def register_participant(
    giveaway_id,
    user_id,
    username,
    first_name,
    referrer_id=None
):
    await save_user(user_id, username, first_name)

    return await add_participant(
        giveaway_id,
        user_id,
        referrer_id
    )


@dp.callback_query(F.data.startswith("join_"))
async def join_giveaway(callback: CallbackQuery, state: FSMContext):

    giveaway_id = parse_integer(
        callback.data.replace("join_", "")
    )

    if giveaway_id is None:
        await callback.answer("شناسه نامعتبر است.", show_alert=True)
        return

    giveaway = await get_giveaway(giveaway_id)

    if not giveaway or giveaway["status"] != "active":
        await callback.answer("این قرعه‌کشی فعال نیست.", show_alert=True)
        return

    channels = await get_required_channels(giveaway_id)

    not_joined = []

    for channel in channels:
        if not await is_user_member(
            callback.from_user.id,
            channel["chat_id"]
        ):
            not_joined.append(channel)

    if not_joined:
        await callback.message.answer(
            "برای شرکت ابتدا در کانال‌های زیر عضو شو:",
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
async def verify_handler(callback: CallbackQuery, state: FSMContext):

    giveaway_id = parse_integer(
        callback.data.replace("verify_", "")
    )

    if giveaway_id is None:
        await callback.answer("شناسه نامعتبر است.", show_alert=True)
        return

    giveaway = await get_giveaway(giveaway_id)

    if not giveaway or giveaway["status"] != "active":
        await callback.answer("قرعه‌کشی پایان یافته.", show_alert=True)
        return

    channels = await get_required_channels(giveaway_id)

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
    callback: CallbackQuery,
    giveaway_id,
    state: FSMContext
):

    data = await state.get_data()

    referrer_id = None

    if data.get("pending_giveaway_id") == giveaway_id:
        referrer_id = data.get("pending_referrer_id")

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
            "تبریک! با موفقیت در قرعه‌کشی شرکت کردی. 🎉"
        )

        try:
            me = await bot.get_me()

            link = (
                f"https://t.me/{me.username}"
                f"?start=gw_{giveaway_id}_ref_{callback.from_user.id}"
            )

            await callback.message.answer(
                "لینک اختصاصی دعوت دوستانت:\n"
                f"{link}"
            )

        except Exception:
            logging.exception("Could not create referral link")

    else:

        messages = {
            "ended": "این قرعه‌کشی پایان یافته.",
            "already_joined": "قبلاً در این قرعه‌کشی شرکت کردی.",
            "full": "ظرفیت قرعه‌کشی تکمیل شده است."
        }

        await callback.answer(
            messages.get(result, "ثبت‌نام انجام نشد."),
            show_alert=True
        )

    await callback.answer()


# =====================================
# ACTIVE GIVEAWAYS
# =====================================

@dp.callback_query(F.data == "active")
async def active_handler(callback: CallbackQuery):

    giveaways = await get_active_giveaways()

    if not giveaways:
        await callback.message.answer("قرعه‌کشی فعالی وجود نداره.")
        await callback.answer()
        return

    for giveaway in giveaways:

        text = (
            f"🎁 قرعه‌کشی شماره {giveaway['id']}\n"
            f"🏆 تعداد برنده‌ها: {giveaway['winner_count']}\n"
            f"👥 ظرفیت: {giveaway['max_users']}\n"
            f"⏰ پایان: {giveaway['ends_at']}"
        )

        await callback.message.answer(
            text,
            reply_markup=giveaway_keyboard(giveaway["id"])
        )

    await callback.answer()


# =====================================
# MY GIVEAWAYS
# =====================================

@dp.callback_query(F.data == "mine")
async def mine_handler(callback: CallbackQuery):

    giveaways = await get_user_giveaways(
        callback.from_user.id
    )

    if not giveaways:
        await callback.message.answer(
            "هنوز قرعه‌کشی‌ای نساختی."
        )
        await callback.answer()
        return

    for giveaway in giveaways:

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 آمار",
                    callback_data=f"stats_{giveaway['id']}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 برندگان",
                    callback_data=f"winners_{giveaway['id']}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ لغو قرعه‌کشی",
                    callback_data=f"cancel_{giveaway['id']}"
                )
            ]
        ])

        await callback.message.answer(
            f"قرعه‌کشی شماره {giveaway['id']}\n"
            f"وضعیت: {giveaway['status']}\n"
            f"پایان: {giveaway['ends_at']}",
            reply_markup=keyboard
        )

    await callback.answer()


# =====================================
# STATISTICS
# =====================================

@dp.callback_query(F.data.startswith("stats_"))
async def stats_handler(callback: CallbackQuery):

    giveaway_id = parse_integer(
        callback.data.replace("stats_", "")
    )

    giveaway = await get_giveaway(giveaway_id)

    if not giveaway or giveaway["creator_id"] != callback.from_user.id:
        await callback.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    participants = await get_participants(giveaway_id)

    await callback.message.answer(
        f"📊 آمار قرعه‌کشی {giveaway_id}\n\n"
        f"👥 تعداد شرکت‌کننده‌ها: {len(participants)}\n"
        f"🏆 تعداد برنده‌ها: {giveaway['winner_count']}\n"
        f"وضعیت: {giveaway['status']}"
    )

    await callback.answer()


# =====================================
# WINNERS
# =====================================

@dp.callback_query(F.data.startswith("winners_"))
async def winners_handler(callback: CallbackQuery):

    giveaway_id = parse_integer(
        callback.data.replace("winners_", "")
    )

    giveaway = await get_giveaway(giveaway_id)

    if not giveaway or giveaway["creator_id"] != callback.from_user.id:
        await callback.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    winners = await get_winners(giveaway_id)

    if not winners:
        await callback.message.answer(
            "هنوز برنده‌ای ثبت نشده."
        )
    else:
        text = "🏆 برندگان:\n\n"

        for winner in winners:
            text += (
                f"رتبه {winner['position']}: "
                f"`{winner['user_id']}`\n"
            )

        await callback.message.answer(
            text,
            parse_mode="Markdown"
        )

    await callback.answer()


# =====================================
# CANCEL GIVEAWAY
# =====================================

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_handler(callback: CallbackQuery):

    giveaway_id = parse_integer(
        callback.data.replace("cancel_", "")
    )

    giveaway = await get_giveaway(giveaway_id)

    if not giveaway or giveaway["creator_id"] != callback.from_user.id:
        await callback.answer("اجازه لغو نداری.", show_alert=True)
        return

    result = await cancel_giveaway(giveaway_id)

    if result:
        await callback.message.answer(
            f"قرعه‌کشی {giveaway_id} لغو شد."
        )
    else:
        await callback.message.answer(
            "این قرعه‌کشی فعال نیست."
        )

    await callback.answer()


# =====================================
# FINISH GIVEAWAY
# =====================================

async def finish_giveaway_process(giveaway):

    giveaway_id = giveaway["id"]

    participants = await get_participants(giveaway_id)

    if len(participants) < giveaway["min_users"]:
        await finish_giveaway(giveaway_id)

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

    # ابتدا برنده‌ها ذخیره می‌شوند تا در صورت خطا از بین نروند.
    await save_winners(giveaway_id, winner_data)

    finished = await finish_giveaway(giveaway_id)

    if not finished:
        return

    winners = await get_winners(giveaway_id)

    text = f"🏆 نتایج قرعه‌کشی {giveaway_id}\n\n"

    for winner in winners:
        text += (
            f"رتبه {winner['position']}: "
            f"`{winner['user_id']}`\n"
        )

    prizes = giveaway["prizes"]

    if isinstance(prizes, str):
        prizes = json.loads(prizes)

    text += "\n🎁 جوایز:\n"

    for prize in prizes:
        text += f"• {prize}\n"

    await bot.send_message(
        int(giveaway["target_channel"]),
        text,
        parse_mode="Markdown"
    )


# =====================================
# WORKER
# =====================================

async def giveaway_worker():

    while True:

        try:
            giveaways = await get_active_giveaways()

            now = datetime.now(timezone.utc)

            for giveaway in giveaways:

                if giveaway["ends_at"] <= now:
                    try:
                        await finish_giveaway_process(giveaway)

                    except Exception:
                        logging.exception(
                            "Could not finish giveaway %s",
                            giveaway["id"]
                        )

        except Exception:
            logging.exception("Giveaway worker error")

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

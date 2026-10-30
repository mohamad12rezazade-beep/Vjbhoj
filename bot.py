import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from supabase import create_client

import os


# =========================
# CONFIGURATION
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip()
]

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN تنظیم نشده است")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("اطلاعات Supabase تنظیم نشده است")


# =========================
# INITIALIZATION
# =========================

logging.basicConfig(level=logging.INFO)

db = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(
    storage=MemoryStorage()
)


# =========================
# STATES
# =========================

class GiveawayStates(StatesGroup):

    winner_count = State()

    prizes = State()

    minimum = State()

    maximum = State()

    duration = State()

    mode = State()

    required_channels = State()

    target_channel = State()

    post_text = State()

    confirmation = State()


# =========================
# KEYBOARDS
# =========================

def main_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🎉 ساخت قرعه‌کشی",
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
                    text="🎯 قرعه‌کشی‌هایی که خودم ساختم",
                    callback_data="mine"
                )
            ]

        ]
    )


def mode_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🔥 بیشترین رفرال",
                    callback_data="referral"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🎲 انتخاب خودکار",
                    callback_data="random"
                )
            ]

        ]
    )


def participation_menu(giveaway_id):

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="✅ شرکت کردن",
                    callback_data=f"join:{giveaway_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    text="❌ لغو شرکت",
                    callback_data=f"leave:{giveaway_id}"
                )
            ]

        ]
    )


# =========================
# DATABASE FUNCTIONS
# =========================

def get_giveaway(giveaway_id):

    result = db.table(
        "giveaways"
    ).select("*").eq(
        "id",
        giveaway_id
    ).maybe_single().execute()

    return result.data


def get_required_channels(giveaway_id):

    result = db.table(
        "required_channels"
    ).select("*").eq(
        "giveaway_id",
        giveaway_id
    ).execute()

    return result.data or []


def get_participant(giveaway_id, user_id):

    result = db.table(
        "participants"
    ).select("*").eq(
        "giveaway_id",
        giveaway_id
    ).eq(
        "user_id",
        user_id
    ).maybe_single().execute()

    return result.data


# =========================
# ADMIN CHECK
# =========================

async def check_bot_admin(channel):

    me = await bot.get_me()

    member = await bot.get_chat_member(
        channel,
        me.id
    )

    return member.status in [
        "administrator",
        "creator"
    ]


# =========================
# MEMBERSHIP CHECK
# =========================

async def check_membership(user_id, channels):

    missing = []

    for channel in channels:

        try:

            member = await bot.get_chat_member(
                channel["chat_id"],
                user_id
            )

            if member.status not in [
                "member",
                "administrator",
                "creator"
            ]:

                missing.append(channel)

        except Exception:

            missing.append(channel)

    return missing


# =========================
# START COMMAND
# =========================

@dp.message(CommandStart())
async def start(message: Message):

    user = message.from_user

    db.table("users").upsert({

        "user_id": user.id,

        "username": user.username,

        "first_name": user.first_name or ""

    }).execute()

    await message.answer(
        "سلام ❤️\n\n"
        "به ربات حرفه‌ای قرعه‌کشی خوش آمدید.",
        reply_markup=main_menu()
    )


# =========================
# CREATE GIVEAWAY
# =========================

@dp.callback_query(F.data == "create")
async def create_giveaway(
    call: CallbackQuery,
    state: FSMContext
):

    if call.from_user.id not in ADMIN_IDS:

        await call.answer(
            "شما اجازه ساخت قرعه‌کشی ندارید.",
            show_alert=True
        )

        return

    await state.set_state(
        GiveawayStates.winner_count
    )

    await call.message.answer(
        "🎁 جایزه به چند نفر تعلق می‌گیرد؟"
    )

    await call.answer()


# =========================
# WINNER COUNT
# =========================

@dp.message(GiveawayStates.winner_count)
async def winner_count(
    message: Message,
    state: FSMContext
):

    try:

        count = int(message.text)

        if count < 1 or count > 50:
            raise ValueError

    except ValueError:

        await message.answer(
            "لطفاً عددی بین ۱ تا ۵۰ وارد کن."
        )

        return

    await state.update_data(
        winner_count=count,
        prizes=[]
    )

    await state.set_state(
        GiveawayStates.prizes
    )

    await message.answer(
        "🏆 جایزه نفر اول را ارسال کن."
    )


# =========================
# PRIZES
# =========================

@dp.message(GiveawayStates.prizes)
async def prizes(
    message: Message,
    state: FSMContext
):

    data = await state.get_data()

    prize_list = data.get("prizes", [])

    prize_list.append(message.text)

    await state.update_data(
        prizes=prize_list
    )

    if len(prize_list) < data["winner_count"]:

        await message.answer(
            f"جایزه نفر {len(prize_list) + 1} را ارسال کن."
        )

        return

    await state.set_state(
        GiveawayStates.minimum
    )

    await message.answer(
        "👥 حداقل تعداد شرکت‌کنندگان چقدر باشد؟"
    )


# =========================
# MINIMUM
# =========================

@dp.message(GiveawayStates.minimum)
async def minimum(
    message: Message,
    state: FSMContext
):

    try:

        number = int(message.text)

        if number < 1:
            raise ValueError

    except ValueError:

        await message.answer(
            "عدد معتبر وارد کن."
        )

        return

    await state.update_data(
        minimum=number
    )

    await state.set_state(
        GiveawayStates.maximum
    )

    await message.answer(
        "👥 حداکثر تعداد شرکت‌کنندگان چقدر باشد؟"
    )


# =========================
# MAXIMUM
# =========================

@dp.message(GiveawayStates.maximum)
async def maximum(
    message: Message,
    state: FSMContext
):

    try:

        number = int(message.text)

        data = await state.get_data()

        if number < data["minimum"]:
            raise ValueError

    except ValueError:

        await message.answer(
            "حداکثر باید بزرگ‌تر یا مساوی حداقل باشد."
        )

        return

    await state.update_data(
        maximum=number
    )

    await state.set_state(
        GiveawayStates.duration
    )

    await message.answer(
        "⏰ قرعه‌کشی چند ساعت فعال باشد؟"
    )


# =========================
# DURATION
# =========================

@dp.message(GiveawayStates.duration)
async def duration(
    message: Message,
    state: FSMContext
):

    try:

        hours = int(message.text)

        if hours < 1 or hours > 720:
            raise ValueError

    except ValueError:

        await message.answer(
            "تعداد ساعت باید بین ۱ تا ۷۲۰ باشد."
        )

        return

    await state.update_data(
        duration=hours
    )

    await state.set_state(
        GiveawayStates.mode
    )

    await message.answer(
        "🎯 روش انتخاب برنده را انتخاب کن:",
        reply_markup=mode_menu()
    )


# =========================
# MODE
# =========================

@dp.callback_query(
    GiveawayStates.mode,
    F.data.in_(["referral", "random"])
)
async def mode(
    call: CallbackQuery,
    state: FSMContext
):

    await state.update_data(
        mode=call.data
    )

    await state.set_state(
        GiveawayStates.required_channels
    )

    await call.message.answer(
        "📢 کانال‌های جوین اجباری را ارسال کن.\n\n"
        "هر کانال در یک خط.\n"
        "مثال:\n"
        "@channel1\n"
        "@channel2\n\n"
        "اگر جوین اجباری نمی‌خواهی بنویس: ندارد"
    )

    await call.answer()


# =========================
# REQUIRED CHANNELS
# =========================

@dp.message(GiveawayStates.required_channels)
async def required_channels(
    message: Message,
    state: FSMContext
):

    channels = []

    if message.text.strip() != "ندارد":

        for line in message.text.splitlines():

            channel = line.strip()

            if not channel:
                continue

            try:

                if not await check_bot_admin(channel):

                    await message.answer(
                        f"❌ ربات در {channel} ادمین نیست."
                    )

                    return

                chat = await bot.get_chat(channel)

                invite = chat.invite_link

                if not invite:

                    invite = f"https://t.me/{channel.lstrip('@')}"

                channels.append({

                    "chat_id": str(chat.id),

                    "title": chat.title or channel,

                    "invite_link": invite

                })

            except Exception:

                await message.answer(
                    f"❌ امکان بررسی {channel} وجود ندارد."
                )

                return

    await state.update_data(
        required_channels=channels
    )

    await state.set_state(
        GiveawayStates.target_channel
    )

    await message.answer(
        "📢 آیدی کانال انتشار قرعه‌کشی را ارسال کن."
    )


# =========================
# TARGET CHANNEL
# =========================

@dp.message(GiveawayStates.target_channel)
async def target_channel(
    message: Message,
    state: FSMContext
):

    channel = message.text.strip()

    try:

        if not await check_bot_admin(channel):

            await message.answer(
                "❌ ربات باید در کانال انتشار ادمین باشد."
            )

            return

        chat = await bot.get_chat(channel)

    except Exception:

        await message.answer(
            "کانال معتبر نیست یا ربات دسترسی ندارد."
        )

        return

    await state.update_data(
        target_channel=str(chat.id),
        target_username=channel
    )

    await state.set_state(
        GiveawayStates.post_text
    )

    await message.answer(
        "📝 متن معرفی قرعه‌کشی در کانال را ارسال کن."
    )


# =========================
# POST TEXT
# =========================

@dp.message(GiveawayStates.post_text)
async def post_text(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        post_text=message.text
    )

    data = await state.get_data()

    preview = (
        "🎁 پیش‌نمایش قرعه‌کشی\n\n"
        f"تعداد برندگان: {data['winner_count']}\n"
        f"جوایز: {' | '.join(data['prizes'])}\n"
        f"حداقل: {data['minimum']}\n"
        f"حداکثر: {data['maximum']}\n"
        f"مدت: {data['duration']} ساعت\n"
        f"روش: {data['mode']}\n"
        f"کانال: {data['target_username']}\n\n"
        "برای ساخت /confirm\n"
        "برای لغو /cancel"
    )

    await state.set_state(
        GiveawayStates.confirmation
    )

    await message.answer(preview)


# =========================
# CONFIRM GIVEAWAY
# =========================

@dp.message(
    GiveawayStates.confirmation,
    F.text == "/confirm"
)
async def confirm(
    message: Message,
    state: FSMContext
):

    data = await state.get_data()

    now = datetime.now(timezone.utc)

    end_time = now + timedelta(
        hours=data["duration"]
    )

    result = db.table("giveaways").insert({

        "creator_id": message.from_user.id,

        "winner_count": data["winner_count"],

        "prizes": data["prizes"],

        "min_users": data["minimum"],

        "max_users": data["maximum"],

        "mode": data["mode"],

        "target_channel": data["target_channel"],

        "post_text": data["post_text"],

        "status": "active",

        "ends_at": end_time.isoformat()

    }).execute()

    giveaway_id = result.data[0]["id"]

    for channel in data["required_channels"]:

        db.table("required_channels").insert({

            "giveaway_id": giveaway_id,

            **channel

        }).execute()

    me = await bot.get_me()

    join_link = (
        f"https://t.me/{me.username}"
        f"?start=gw_{giveaway_id}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🎁 شرکت در قرعه‌کشی",
                    url=join_link
                )
            ]

        ]
    )

    await bot.send_message(
        data["target_channel"],
        data["post_text"],
        reply_markup=keyboard
    )

    await message.answer(
        f"✅ قرعه‌کشی با موفقیت ساخته شد.\n"
        f"شناسه: {giveaway_id}"
    )

    await state.clear()


# =========================
# CANCEL CREATION
# =========================

@dp.message(F.text == "/cancel")
async def cancel(
    message: Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "عملیات لغو شد.",
        reply_markup=main_menu()
    )


# =========================
# ACTIVE GIVEAWAYS
# =========================

@dp.callback_query(F.data == "active")
async def active(call: CallbackQuery):

    rows = db.table(
        "giveaways"
    ).select("*").eq(
        "status",
        "active"
    ).execute().data or []

    if not rows:

        await call.message.answer(
            "قرعه‌کشی فعالی وجود ندارد."
        )

    else:

        for giveaway in rows:

            await call.message.answer(
                f"🎁 قرعه‌کشی شماره {giveaway['id']}",
                reply_markup=participation_menu(
                    giveaway["id"]
                )
            )

    await call.answer()


# =========================
# MY GIVEAWAYS
# =========================

@dp.callback_query(F.data == "mine")
async def mine(call: CallbackQuery):

    rows = db.table(
        "giveaways"
    ).select("*").eq(
        "creator_id",
        call.from_user.id
    ).execute().data or []

    if not rows:

        await call.message.answer(
            "هنوز قرعه‌کشی نساخته‌اید."
        )

    else:

        for giveaway in rows:

            await call.message.answer(
                f"🎁 قرعه‌کشی #{giveaway['id']}\n"
                f"وضعیت: {giveaway['status']}"
            )

    await call.answer()


# =========================
# PARTICIPATION
# =========================

@dp.callback_query(F.data.startswith("join:"))
async def join(call: CallbackQuery):

    giveaway_id = int(
        call.data.split(":")[1]
    )

    giveaway = get_giveaway(giveaway_id)

    if not giveaway or giveaway["status"] != "active":

        await call.answer(
            "قرعه‌کشی فعال نیست.",
            show_alert=True
        )

        return

    channels = get_required_channels(
        giveaway_id
    )

    missing = []

    for channel in channels:

        try:

            member = await bot.get_chat_member(
                channel["chat_id"],
                call.from_user.id
            )

            if member.status not in [
                "member",
                "administrator",
                "creator"
            ]:

                missing.append(channel)

        except Exception:

            missing.append(channel)

    if missing:

        rows = []

        for channel in missing:

            rows.append([

                InlineKeyboardButton(
                    text=f"عضویت در {channel['title']}",
                    url=channel["invite_link"]
                )

            ])

        rows.append([

            InlineKeyboardButton(
                text="🔄 تأیید عضویت",
                callback_data=f"verify:{giveaway_id}"
            )

        ])

        await call.message.answer(
            "ابتدا عضو کانال‌های زیر شو:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=rows
            )
        )

        await call.answer()

        return

    await register_user(
        call,
        giveaway_id
    )


async def register_user(call, giveaway_id):

    user_id = call.from_user.id

    old = get_participant(
        giveaway_id,
        user_id
    )

    if old and old["active"]:

        await call.answer(
            "قبلاً شرکت کرده‌ای.",
            show_alert=True
        )

        return

    count = db.table(
        "participants"
    ).select(
        "user_id",
        count="exact"
    ).eq(
        "giveaway_id",
        giveaway_id
    ).eq(
        "active",
        True
    ).execute().count or 0

    giveaway = get_giveaway(giveaway_id)

    if count >= giveaway["max_users"]:

        await call.answer(
            "ظرفیت تکمیل شده است.",
            show_alert=True
        )

        return

    db.table("participants").upsert({

        "giveaway_id": giveaway_id,

        "user_id": user_id,

        "active": True,

        "referral_count": 0

    }).execute()

    me = await bot.get_me()

    referral_link = (
        f"https://t.me/{me.username}"
        f"?start=gw_{giveaway_id}_ref_{user_id}"
    )

    await call.message.answer(
        "✅ با موفقیت شرکت کردی!\n\n"
        "🔗 لینک اختصاصی رفرال:\n"
        f"{referral_link}"
    )

    await call.answer(
        "ثبت‌نام انجام شد."
    )


# =========================
# VERIFY MEMBERSHIP
# =========================

@dp.callback_query(F.data.startswith("verify:"))
async def verify(call: CallbackQuery):

    giveaway_id = int(
        call.data.split(":")[1]
    )

    channels = get_required_channels(
        giveaway_id
    )

    for channel in channels:

        try:

            member = await bot.get_chat_member(
                channel["chat_id"],
                call.from_user.id
            )

            if member.status not in [
                "member",
                "administrator",
                "creator"
            ]:

                await call.answer(
                    "هنوز عضو همه کانال‌ها نشده‌ای.",
                    show_alert=True
                )

                return

        except Exception:

            await call.answer(
                "عضویت قابل بررسی نیست.",
                show_alert=True
            )

            return

    await call.answer(
        "عضویت تأیید شد.",
        show_alert=True
    )


# =========================
# MAIN
# =========================

async def main():

    logging.info("Bot started")

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())

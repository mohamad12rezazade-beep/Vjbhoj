import asyncio
import logging
import random
import json

from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
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
    get_winners,
    save_winners,
    finish_giveaway,
    cancel_giveaway,
)

from keyboards import main_menu, giveaway_keyboard
from states import CreateGiveaway


# =========================
# تنظیمات
# =========================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# =========================
# کیبوردها
# =========================

def cancel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ لغو ساخت",
                    callback_data="cancel_creation"
                )
            ]
        ]
    )


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


def management_keyboard(giveaway_id):
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
                    text="🏆 مشاهده برندگان",
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


# =========================
# ابزار کانال
# =========================

async def check_bot_admin(chat_id):
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)

        return member.status in (
            "administrator",
            "creator"
        )

    except Exception:
        return False


async def get_channel_information(chat_id):
    chat = await bot.get_chat(chat_id)

    if chat.username:
        invite_link = f"https://t.me/{chat.username}"

    else:
        invite = await bot.create_chat_invite_link(
            chat_id=chat.id
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
        return False


# =========================
# شروع ربات
# =========================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):

    await state.clear()

    user = message.from_user

    await save_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name
    )

    args = message.text.split(maxsplit=1)

    if len(args) > 1:

        payload = args[1]

        if payload.startswith("gw_"):

            try:
                parts = payload.split("_")

                giveaway_id = int(parts[1])
                referrer_id = None

                if len(parts) == 4 and parts[2] == "ref":
                    referrer_id = int(parts[3])

                giveaway = await get_giveaway(giveaway_id)

                if giveaway and giveaway["status"] == "active":

                    await state.update_data(
                        pending_giveaway_id=giveaway_id,
                        pending_referrer_id=referrer_id
                    )

                    await message.answer(
                        "🎁 برای شرکت در این قرعه‌کشی "
                        "روی دکمه زیر بزن.",
                        reply_markup=giveaway_keyboard(
                            giveaway_id
                        )
                    )

                    return

            except Exception:
                logging.exception("Deep link error")

    await message.answer(
        "سلام 👋\n\n"
        "به ربات مدیریت قرعه‌کشی خوش اومدی.\n"
        "از منوی زیر استفاده کن:",
        reply_markup=main_menu()
    )


# =========================
# بازگشت به منو
# =========================

@dp.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery, state: FSMContext):

    await state.clear()

    await callback.message.answer(
        "منوی اصلی:",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================
# ساخت قرعه‌کشی
# =========================

@dp.callback_query(F.data == "create_giveaway")
async def create_start(callback: CallbackQuery, state: FSMContext):

    await state.clear()

    await state.set_state(
        CreateGiveaway.winner_count
    )

    await callback.message.answer(
        "🏆 چند نفر برنده داشته باشیم؟"
    )

    await callback.answer()


@dp.message(CreateGiveaway.winner_count)
async def get_winner_count(message: Message, state: FSMContext):

    try:
        count = int(message.text)

        if count < 1 or count > 100:
            raise ValueError

    except Exception:
        await message.answer(
            "❌ یک عدد بین 1 تا 100 وارد کن."
        )
        return

    await state.update_data(
        winner_count=count,
        prizes=[]
    )

    await state.set_state(
        CreateGiveaway.prizes
    )

    await message.answer(
        "🎁 جایزه نفر اول رو وارد کن."
    )


@dp.message(CreateGiveaway.prizes)
async def get_prizes(message: Message, state: FSMContext):

    data = await state.get_data()

    prizes = data.get("prizes", [])

    prizes.append(message.text.strip())

    if len(prizes) < data["winner_count"]:

        await state.update_data(prizes=prizes)

        await message.answer(
            f"🎁 جایزه نفر {len(prizes) + 1} رو وارد کن."
        )

        return

    await state.update_data(prizes=prizes)

    await state.set_state(
        CreateGiveaway.min_users
    )

    await message.answer(
        "👥 حداقل تعداد شرکت‌کننده‌ها چند نفر باشه؟"
    )


@dp.message(CreateGiveaway.min_users)
async def get_min_users(message: Message, state: FSMContext):

    try:
        value = int(message.text)

        if value < 1:
            raise ValueError

    except Exception:
        await message.answer("❌ عدد معتبر وارد کن.")
        return

    await state.update_data(min_users=value)

    await state.set_state(
        CreateGiveaway.max_users
    )

    await message.answer(
        "👥 حداکثر تعداد شرکت‌کننده‌ها چند نفر باشه؟"
    )


@dp.message(CreateGiveaway.max_users)
async def get_max_users(message: Message, state: FSMContext):

    data = await state.get_data()

    try:
        value = int(message.text)

        if value < data["min_users"]:
            raise ValueError

    except Exception:
        await message.answer(
            "❌ حداکثر باید برابر یا بیشتر از حداقل باشه."
        )
        return

    await state.update_data(max_users=value)

    await state.set_state(
        CreateGiveaway.duration
    )

    await message.answer(
        "⏰ قرعه‌کشی چند ساعت فعال باشه؟"
    )


@dp.message(CreateGiveaway.duration)
async def get_duration(message: Message, state: FSMContext):

    try:
        hours = int(message.text)

        if hours < 1 or hours > 8760:
            raise ValueError

    except Exception:
        await message.answer(
            "❌ تعداد ساعت باید بین 1 تا 8760 باشه."
        )
        return

    await state.update_data(duration=hours)

    await state.set_state(
        CreateGiveaway.mode
    )

    await message.answer(
        "🎯 روش انتخاب برنده رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎲 انتخاب تصادفی",
                        callback_data="mode_random"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔥 بیشترین رفرال",
                        callback_data="mode_referral"
                    )
                ]
            ]
        )
    )


# =========================
# انتخاب روش
# =========================

@dp.callback_query(F.data.startswith("mode_"))
async def select_mode(callback: CallbackQuery, state: FSMContext):

    mode = callback.data.replace("mode_", "")

    await state.update_data(
        mode=mode,
        required_channels=[]
    )

    await state.set_state(
        CreateGiveaway.required_channels
    )

    await callback.message.answer(
        "📢 آیدی کانال جوین اجباری رو بفرست.\n\n"
        "مثال:\n"
        "@mychannel\n\n"
        "برای پایان، کلمه «تمام» رو بفرست.\n"
        "اگر کانال اجباری نداری، «ندارد» رو بفرست."
    )

    await callback.answer()


# =========================
# کانال‌های اجباری
# =========================

@dp.message(CreateGiveaway.required_channels)
async def get_required_channels(message: Message, state: FSMContext):

    channel = message.text.strip()

    if channel == "ندارد" or channel == "تمام":

        await state.set_state(
            CreateGiveaway.target_channel
        )

        await message.answer(
            "📣 آیدی کانال انتشار قرعه‌کشی رو بفرست."
        )

        return

    if not channel.startswith("@") and not channel.startswith("-100"):

        await message.answer(
            "❌ آیدی کانال معتبر نیست."
        )

        return

    if not await check_bot_admin(channel):

        await message.answer(
            "❌ ربات در این کانال ادمین نیست!\n\n"
            "ربات رو ادمین کن و دوباره آدرس کانال رو بفرست."
        )

        return

    try:

        channel_info = await get_channel_information(channel)

        data = await state.get_data()

        channels = data.get("required_channels", [])

        if any(
            item["chat_id"] == channel_info["chat_id"]
            for item in channels
        ):

            await message.answer(
                "این کانال قبلاً ثبت شده."
            )

            return

        channels.append(channel_info)

        await state.update_data(
            required_channels=channels
        )

        await message.answer(
            f"✅ کانال {channel_info['title']} ثبت شد.\n"
            f"تعداد کانال‌ها: {len(channels)}\n\n"
            "کانال بعدی رو بفرست یا «تمام» رو ارسال کن."
        )

    except Exception:

        await message.answer(
            "❌ دریافت اطلاعات کانال ناموفق بود.\n"
            "آیدی کانال و دسترسی ادمین ربات رو بررسی کن."
        )


# =========================
# کانال انتشار
# =========================

@dp.message(CreateGiveaway.target_channel)
async def get_target_channel(message: Message, state: FSMContext):

    channel = message.text.strip()

    if not await check_bot_admin(channel):

        await message.answer(
            "❌ ربات باید در کانال انتشار ادمین باشه."
        )

        return

    await state.update_data(
        target_channel=channel
    )

    await state.set_state(
        CreateGiveaway.post_text
    )

    await message.answer(
        "✍️ متن پست قرعه‌کشی رو ارسال کن."
    )


# =========================
# متن پست
# =========================

@dp.message(CreateGiveaway.post_text)
async def get_post_text(message: Message, state: FSMContext):

    await state.update_data(
        post_text=message.text
    )

    data = await state.get_data()

    await message.answer(
        "📋 پیش‌نمایش قرعه‌کشی:\n\n"
        f"🏆 برندگان: {data['winner_count']}\n"
        f"🎁 جایزه‌ها: {', '.join(data['prizes'])}\n"
        f"👥 حداقل: {data['min_users']}\n"
        f"👥 حداکثر: {data['max_users']}\n"
        f"⏰ مدت: {data['duration']} ساعت\n"
        f"🎯 روش: {data['mode']}\n"
        f"📣 کانال: {data['target_channel']}\n\n"
        "برای انتشار تأیید کن:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ ساخت قرعه‌کشی",
                        callback_data="confirm_giveaway"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ لغو",
                        callback_data="cancel_creation"
                    )
                ]
            ]
        )
    )


# =========================
# تأیید ساخت
# =========================

@dp.callback_query(F.data == "confirm_giveaway")
async def confirm_giveaway(callback: CallbackQuery, state: FSMContext):

    data = await state.get_data()

    try:

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
            f"🏆 تعداد برندگان: {data['winner_count']}\n"
            f"👥 حداقل شرکت‌کننده: {data['min_users']}\n"
            f"⏰ مدت: {data['duration']} ساعت"
        )

        await bot.send_message(
            data["target_channel"],
            text,
            reply_markup=giveaway_keyboard(giveaway_id)
        )

        await callback.message.answer(
            f"✅ قرعه‌کشی ساخته شد!\n"
            f"شناسه: {giveaway_id}"
        )

        await state.clear()

    except Exception:

        logging.exception("Giveaway creation error")

        await callback.message.answer(
            "❌ خطا در ساخت یا انتشار قرعه‌کشی.\n"
            "اطلاعات کانال و دیتابیس رو بررسی کن."
        )

    await callback.answer()


@dp.callback_query(F.data == "cancel_creation")
async def cancel_creation(callback: CallbackQuery, state: FSMContext):

    await state.clear()

    await callback.message.answer(
        "❌ ساخت قرعه‌کشی لغو شد.",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================
# شرکت در قرعه‌کشی
# =========================

@dp.callback_query(F.data.startswith("join_"))
async def join_giveaway(callback: CallbackQuery, state: FSMContext):

    giveaway_id = int(callback.data.split("_")[1])

    giveaway = await get_giveaway(giveaway_id)

    if not giveaway or giveaway["status"] != "active":

        await callback.answer(
            "این قرعه‌کشی فعال نیست.",
            show_alert=True
        )

        return

    channels = await get_required_channels(giveaway_id)

    buttons = []

    not_joined = []

    for channel in channels:

        joined = await is_user_member(
            callback.from_user.id,
            channel["chat_id"]
        )

        if not joined:

            not_joined.append(channel)

            buttons.append([
                InlineKeyboardButton(
                    text=f"عضویت در {channel['title']}",
                    url=channel["invite_link"]
                )
            ])

    if not_joined:

        buttons.append([
            InlineKeyboardButton(
                text="✅ بررسی عضویت",
                callback_data=f"verify_{giveaway_id}"
            )
        ])

        await callback.message.answer(
            "برای شرکت باید عضو همه کانال‌های زیر بشی:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=buttons
            )
        )

        await callback.answer()

        return

    await register_participant(
        callback,
        giveaway_id,
        state
    )


@dp.callback_query(F.data.startswith("verify_"))
async def verify_membership(callback: CallbackQuery, state: FSMContext):

    giveaway_id = int(callback.data.split("_")[1])

    channels = await get_required_channels(giveaway_id)

    for channel in channels:

        joined = await is_user_member(
            callback.from_user.id,
            channel["chat_id"]
        )

        if not joined:

            await callback.answer(
                "❌ هنوز عضو همه کانال‌ها نشدی.",
                show_alert=True
            )

            return

    await register_participant(
        callback,
        giveaway_id,
        state
    )


# =========================
# ثبت شرکت‌کننده
# =========================

async def register_participant(callback, giveaway_id, state):

    data = await state.get_data()

    referrer_id = data.get("pending_referrer_id")

    if referrer_id == callback.from_user.id:
        referrer_id = None

    success = await add_participant(
        giveaway_id=giveaway_id,
        user_id=callback.from_user.id,
        referrer_id=referrer_id
    )

    if not success:

        await callback.answer(
            "قبلاً ثبت‌نام کردی یا ظرفیت قرعه‌کشی تکمیل شده.",
            show_alert=True
        )

        return

    me = await bot.get_me()

    referral_link = (
        f"https://t.me/{me.username}"
        f"?start=gw_{giveaway_id}_ref_{callback.from_user.id}"
    )

    await callback.message.answer(
        "🎉 با موفقیت در قرعه‌کشی ثبت‌نام شدی!\n\n"
        "🔗 لینک اختصاصی دعوت دوستانت:\n"
        f"{referral_link}\n\n"
        "هر دعوت معتبر یک امتیاز رفرال برات ثبت می‌کنه."
    )

    await callback.answer("ثبت‌نام موفق بود!")


# =========================
# قرعه‌کشی‌های فعال
# =========================

@dp.callback_query(F.data == "active_giveaways")
async def active_giveaways(callback: CallbackQuery):

    giveaways = await get_active_giveaways()

    if not giveaways:

        await callback.message.answer(
            "فعلاً قرعه‌کشی فعالی وجود نداره."
        )

        await callback.answer()

        return

    for giveaway in giveaways:

        await callback.message.answer(
            f"🎁 قرعه‌کشی شماره {giveaway['id']}\n"
            f"🏆 تعداد برندگان: {giveaway['winner_count']}\n"
            f"⏰ پایان: {giveaway['ends_at']}",
            reply_markup=giveaway_keyboard(
                giveaway["id"]
            )
        )

    await callback.answer()


# =========================
# قرعه‌کشی‌های من
# =========================

@dp.callback_query(F.data == "my_giveaways")
async def my_giveaways(callback: CallbackQuery):

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

        await callback.message.answer(
            f"🎁 قرعه‌کشی شماره {giveaway['id']}\n"
            f"📌 وضعیت: {giveaway['status']}\n"
            f"⏰ پایان: {giveaway['ends_at']}",
            reply_markup=management_keyboard(
                giveaway["id"]
            )
        )

    await callback.answer()


# =========================
# آمار شرکت‌کنندگان
# =========================

@dp.callback_query(F.data.startswith("stats_"))
async def giveaway_stats(callback: CallbackQuery):

    giveaway_id = int(callback.data.split("_")[1])

    giveaway = await get_giveaway(giveaway_id)

    if not giveaway or giveaway["creator_id"] != callback.from_user.id:

        await callback.answer(
            "اجازه دسترسی نداری.",
            show_alert=True
        )

        return

    participants = await get_participants(giveaway_id)

    await callback.message.answer(
        f"📊 آمار قرعه‌کشی {giveaway_id}\n\n"
        f"👥 تعداد شرکت‌کنندگان: {len(participants)}"
    )

    await callback.answer()


# =========================
# مشاهده برندگان
# =========================

@dp.callback_query(F.data.startswith("winners_"))
async def show_winners(callback: CallbackQuery):

    giveaway_id = int(callback.data.split("_")[1])

    giveaway = await get_giveaway(giveaway_id)

    if not giveaway or giveaway["creator_id"] != callback.from_user.id:

        await callback.answer(
            "اجازه دسترسی نداری.",
            show_alert=True
        )

        return

    winners = await get_winners(giveaway_id)

    if not winners:

        await callback.message.answer(
            "هنوز برنده‌ای ثبت نشده."
        )

        await callback.answer()

        return

    text = "🏆 برندگان قرعه‌کشی:\n\n"

    for winner in winners:

        text += (
            f"رتبه {winner['position']}: "
            f"{winner['user_id']}\n"
            f"🎁 جایزه: {winner['prize']}\n\n"
        )

    await callback.message.answer(text)

    await callback.answer()


# =========================
# لغو قرعه‌کشی
# =========================

@dp.callback_query(F.data.startswith("cancel_gw_"))
async def cancel_giveaway_handler(callback: CallbackQuery):

    giveaway_id = int(callback.data.split("_")[-1])

    giveaway = await get_giveaway(giveaway_id)

    if not giveaway or giveaway["creator_id"] != callback.from_user.id:

        await callback.answer(
            "اجازه لغو این قرعه‌کشی رو نداری.",
            show_alert=True
        )

        return

    await cancel_giveaway(giveaway_id)

    await callback.message.answer(
        "❌ قرعه‌کشی لغو شد."
    )

    await callback.answer()


# =========================
# پایان خودکار قرعه‌کشی
# =========================

async def giveaway_worker():

    while True:

        try:

            giveaways = await get_active_giveaways()

            now = datetime.now(timezone.utc)

            for giveaway in giveaways:

                ends_at = giveaway["ends_at"]

                if ends_at.tzinfo is None:
                    ends_at = ends_at.replace(
                        tzinfo=timezone.utc
                    )

                if ends_at <= now:

                    await finish_giveaway_process(
                        giveaway
                    )

        except Exception:

            logging.exception(
                "Giveaway worker error"
            )

        await asyncio.sleep(30)


# =========================
# انتخاب برندگان
# =========================

async def finish_giveaway_process(giveaway):

    giveaway_id = giveaway["id"]

    participants = await get_participants(
        giveaway_id
    )

    if len(participants) < giveaway["min_users"]:

        await finish_giveaway(giveaway_id)

        await bot.send_message(
            giveaway["target_channel"],
            "⚠️ قرعه‌کشی به حداقل تعداد شرکت‌کننده نرسید "
            "و برنده‌ای انتخاب نشد."
        )

        return

    if not await finish_giveaway(giveaway_id):
        return

    if giveaway["mode"] == "referral":

        participants.sort(
            key=lambda x: x["referral_count"],
            reverse=True
        )

        winners = participants[
            :giveaway["winner_count"]
        ]

    else:

        winners = random.sample(
            participants,
            min(
                len(participants),
                giveaway["winner_count"]
            )
        )

    prizes = giveaway["prizes"]

    if isinstance(prizes, str):
        prizes = json.loads(prizes)

    winner_rows = []

    for index, winner in enumerate(winners):

        winner_rows.append({
            "user_id": winner["user_id"],
            "position": index + 1,
            "prize": prizes[index]
        })

    await save_winners(
        giveaway_id,
        winner_rows
    )

    text = "🏆 قرعه‌کشی به پایان رسید!\n\n"

    for winner in winner_rows:

        text += (
            f"🥇 رتبه {winner['position']}\n"
            f"👤 شناسه کاربر: {winner['user_id']}\n"
            f"🎁 جایزه: {winner['prize']}\n\n"
        )

    await bot.send_message(
        giveaway["target_channel"],
        text
    )


# =========================
# اجرای ربات
# =========================

async def main():

    await connect_db()

    logging.info("Database connected")

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

    asyncio.run(main())

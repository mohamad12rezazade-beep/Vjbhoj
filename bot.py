import asyncio
import logging
import sys
import random
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from config import BOT_TOKEN, DATABASE_URL, ADMIN_IDS
from database import Database, PostgresStorage
from keyboards import (
    main_menu_kb, back_to_menu_kb, cancel_kb, confirm_lottery_kb,
    join_lottery_inline_kb, lottery_join_kb
)
from states import CreateLottery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("lottery-bot")

db = Database(DATABASE_URL)
router = Router()

REQUIRED_CHANNEL = "@BET_1XZX"

async def init_db() -> None:
    async with db.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                points INTEGER NOT NULL DEFAULT 0,
                referred_by BIGINT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS lotteries (
                id BIGSERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                winners_count INTEGER NOT NULL CHECK (winners_count > 0),
                prizes TEXT NOT NULL,
                min_participants INTEGER NOT NULL DEFAULT 1,
                max_participants INTEGER NOT NULL,
                mode TEXT NOT NULL,
                required_channels TEXT NOT NULL DEFAULT '',
                publish_channel TEXT NOT NULL,
                post_text TEXT NOT NULL,
                post_message_id BIGINT,
                status TEXT NOT NULL DEFAULT 'active',
                ends_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ
            );

            CREATE TABLE IF NOT EXISTS participants (
                id BIGSERIAL PRIMARY KEY,
                lottery_id BIGINT NOT NULL REFERENCES lotteries(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(lottery_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS winners (
                id BIGSERIAL PRIMARY KEY,
                lottery_id BIGINT NOT NULL REFERENCES lotteries(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                prize TEXT,
                position INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(lottery_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS fsm_states (
                user_id BIGINT PRIMARY KEY,
                state TEXT,
                data JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                temp_flag TEXT
            );
        """)
        # این خط خودش ستون رو به جدول اضافه میکنه اگه نبود
        await conn.execute("ALTER TABLE fsm_states ADD COLUMN IF NOT EXISTS temp_flag TEXT;")
        logger.info("✅ جدول‌ها آماده هستند.")

async def is_member(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status not in ("left", "kicked")
    except Exception as e:
        logger.warning(f"خطا در بررسی عضویت {REQUIRED_CHANNEL}: {e}")
        return False

def join_channel_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📢 عضویت در کانال", url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}"))
    builder.row(InlineKeyboardButton(text="✅ عضو شدم", callback_data="check_member"))
    return builder.as_markup()

async def finish_lottery(bot: Bot, lottery_id: int) -> None:
    lot = await db.get_lottery(lottery_id)
    if not lot or lot["status"] != "active":
        return

    participants = await db.get_participants(lottery_id)
    if len(participants) < lot["min_participants"]:
        await db.cancel_lottery(lottery_id)
        try:
            await bot.send_message(
                chat_id=lot["publish_channel"],
                text=f"⚠️ قرعه‌کشی #{lottery_id} به دلیل عدم رسیدن به حداقل شرکت‌کننده لغو شد."
            )
        except Exception:
            pass
        return

    if lot["mode"] == "points":
        participants.sort(key=lambda p: p["points"], reverse=True)
        selected = participants[:lot["winners_count"]]
    else:
        selected = random.sample(participants, min(lot["winners_count"], len(participants)))

    prizes = [p.strip() for p in lot["prizes"].split("\n") if p.strip()]
    winners_data = []
    for i, p in enumerate(selected):
        prize = prizes[i] if i < len(prizes) else f"جایزه {i+1}"
        winners_data.append((p["user_id"], prize))

    await db.save_winners(lottery_id, winners_data)

    result_text = f"🏆 <b>نتیجه قرعه‌کشی #{lottery_id}</b>\n\n"
    for i, (uid, prize) in enumerate(winners_data):
        result_text += f"{i+1}. <a href='tg://user?id={uid}'>کاربر {uid}</a> — {prize}\n"

    try:
        await bot.send_message(chat_id=lot["publish_channel"], text=result_text, parse_mode="HTML")
    except Exception as e:
        logger.exception(f"خطا در ارسال نتیجه: {e}")

async def lottery_checker(bot: Bot) -> None:
    while True:
        try:
            expired = await db.get_expired_active_lotteries()
            for lot in expired:
                await finish_lottery(bot, lot["id"])
        except Exception as e:
            logger.exception(f"خطا در اسکنر: {e}")
        await asyncio.sleep(60)


# 🟢 ---- دستور استارت ----
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user = message.from_user
    if user is None:
        return

    if not await is_member(bot, user.id):
        await message.answer(
            f"⚠️ برای استفاده از ربات، ابتدا باید در کانال زیر عضو بشی:\n\n"
            f"➡️ {REQUIRED_CHANNEL}\n\n"
            "بعد از عضویت، روی دکمه «✅ عضو شدم» بزن.",
            reply_markup=join_channel_kb()
        )
        return

    try:
        await db.upsert_user(user.id, user.username, user.first_name, user.last_name)
        if user.id in ADMIN_IDS:
            await db.set_admin(user.id, True)
    except Exception as e:
        logger.exception("خطا در ثبت کاربر: %s", e)
        await message.answer(f"❌ خطای دیتابیس:\n\n<code>{type(e).__name__}: {e}</code>")
        return

    await message.answer(
        f"👋 سلام <b>{user.first_name}</b>!\n\n"
        "به ربات <b>قرعه‌کشی</b> خوش آمدی.\n"
        "از منوی زیر یک گزینه را انتخاب کن:",
        reply_markup=main_menu_kb(),
    )

@router.callback_query(F.data == "check_member")
async def cb_check_member(callback: CallbackQuery, bot: Bot) -> None:
    if await is_member(bot, callback.from_user.id):
        user = callback.from_user
        try:
            await db.upsert_user(user.id, user.username, user.first_name, user.last_name)
            if user.id in ADMIN_IDS:
                await db.set_admin(user.id, True)
        except Exception:
            pass
        await callback.message.edit_text(
            f"✅ عضویتت تأیید شد، خوش اومدی <b>{user.first_name}</b>!\n\n"
            "از منوی زیر انتخاب کن:",
            reply_markup=main_menu_kb()
        )
    else:
        await callback.answer("❌ هنوز عضو نشدی! اول عضو شو.", show_alert=True)

@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    if not await is_member(bot, message.from_user.id):
        await message.answer("⚠️ اول در کانال عضو شو.", reply_markup=join_channel_kb())
        return
    await message.answer("📋 منوی اصلی:", reply_markup=main_menu_kb())

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    if not await is_member(bot, callback.from_user.id):
        await callback.message.edit_text("⚠️ اول در کانال عضو شو.", reply_markup=join_channel_kb())
        await callback.answer()
        return
    await callback.message.edit_text("📋 منوی اصلی:", reply_markup=main_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery) -> None:
    try:
        s = await db.stats()
    except Exception as e:
        await callback.answer(f"❌ {type(e).__name__}: {e}", show_alert=True)
        return

    text = (
        "📊 <b>آمار ربات</b>\n\n"
        f"👥 کاربران: <b>{s['users']}</b>\n"
        f"🎁 کل قرعه‌کشی‌ها: <b>{s['lotteries']}</b>\n"
        f"✅ فعال: <b>{s['active']}</b>\n"
        f"🙋 شرکت‌کنندگان: <b>{s['participants']}</b>"
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery) -> None:
    text = (
        "📖 <b>راهنمای استفاده</b>\n\n"
        "🎁 <b>ساخت قرعه‌کشی:</b> یک قرعه‌کشی جدید بساز\n"
        "📋 <b>قرعه‌کشی‌های فعال:</b> همه قرعه‌کشی‌های در جریان\n"
        "👤 <b>قرعه‌کشی‌های من:</b> قرعه‌کشی‌هایی که خودت ساختی\n"
        "📊 <b>آمار:</b> آمار کلی ربات\n\n"
        "🔗 <b>دعوت دوستان:</b> با لینک اختصاصی، امتیاز بگیر."
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "create_lottery")
async def cb_create_lottery(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not await is_member(bot, callback.from_user.id):
        await callback.answer("اول عضو کانال شو!", show_alert=True)
        return
    await state.clear()
    await state.set_state(CreateLottery.winners_count)
    await callback.message.edit_text(
        "🎁 <b>مرحله ۱ از ۱۰</b>\n\nچند برنده می‌خوای؟ (یک عدد بفرست)",
        reply_markup=cancel_kb()
    )
    await callback.answer()

# 🟢 ---- هندلرهای FSM ----
@router.message(CreateLottery.winners_count)
async def step_winners(message: Message, state: FSMContext) -> None:
    try:
        n = int(message.text.strip())
        if n <= 0: raise ValueError
    except:
        await message.answer("❌ یک عدد مثبت بفرست.")
        return
    await state.update_data(winners_count=n)
    await state.set_state(CreateLottery.prizes)
    await message.answer(
        f"✅ تعداد برندگان: <b>{n}</b>\n\n"
        "🎁 <b>مرحله ۲ از ۱۰</b>\n\n"
        "جوایز رو بنویس (هر جایزه در یک خط):",
        reply_markup=cancel_kb()
    )

# 🟢 ---- هندلر نجات‌دهنده (Fallback for numbers) ----
@router.message(F.text.regexp(r"^\d+$"))
async def fallback_number_handler(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is not None:
        return 
    
    try:
        n = int(message.text.strip())
        if n <= 0: raise ValueError
    except:
        await message.answer("❌ یک عدد مثبت بفرست.")
        return
        
    await state.update_data(winners_count=n)
    await state.set_state(CreateLottery.prizes)
    await message.answer(
        f"✅ تعداد برندگان: <b>{n}</b>\n\n"
        "🎁 <b>مرحله ۲ از ۱۰</b>\n\n"
        "جوایز رو بنویس (هر جایزه در یک خط):",
        reply_markup=cancel_kb()
    )

@router.message(CreateLottery.prizes)
async def step_prizes(message: Message, state: FSMContext) -> None:
    await state.update_data(prizes=message.text.strip())
    await state.set_state(CreateLottery.min_participants)
    await message.answer(
        "👥 <b>مرحله ۳ از ۱۰</b>\n\nحداقل تعداد شرکت‌کننده چند نفر باشه؟",
        reply_markup=cancel_kb()
    )

@router.message(CreateLottery.min_participants)
async def step_min(message: Message, state: FSMContext) -> None:
    try:
        n = int(message.text.strip())
        if n <= 0: raise ValueError
    except:
        await message.answer("❌ یک عدد مثبت بفرست.")
        return
    await state.update_data(min_participants=n)
    await state.set_state(CreateLottery.max_participants)
    await message.answer(
        f"✅ حداقل: <b>{n}</b>\n\n"
        "👥 <b>مرحله ۴ از ۱۰</b>\n\nحداکثر تعداد شرکت‌کننده چند نفر باشه؟",
        reply_markup=cancel_kb()
    )

@router.message(CreateLottery.max_participants)
async def step_max(message: Message, state: FSMContext) -> None:
    try:
        n = int(message.text.strip())
    except:
        await message.answer("❌ یک عدد بفرست.")
        return
    data = await state.get_data()
    if n < data.get("min_participants", 1):
        await message.answer("❌ حداکثر باید بیشتر یا مساوی حداقل باشه.")
        return
    await state.update_data(max_participants=n)
    await state.set_state(CreateLottery.duration)
    await message.answer(
        f"✅ حداکثر: <b>{n}</b>\n\n"
        "⏱ <b>مرحله ۵ از ۱۰</b>\n\nمدت قرعه‌کشی چند ساعت باشه؟",
        reply_markup=cancel_kb()
    )

@router.message(CreateLottery.duration)
async def step_duration(message: Message, state: FSMContext) -> None:
    try:
        h = float(message.text.strip())
        if h <= 0: raise ValueError
    except:
        await message.answer("❌ یک عدد مثبت (ساعت) بفرست.")
        return
    await state.update_data(duration_hours=h)
    await state.set_state(CreateLottery.mode)
    await message.answer(
        f"✅ مدت: <b>{h} ساعت</b>\n\n"
        "🎲 <b>مرحله ۶ از ۱۰</b>\n\nروش قرعه‌کشی:\n"
        "<b>random</b> = تصادفی\n<b>points</b> = بر اساس امتیاز",
        reply_markup=cancel_kb()
    )

@router.message(CreateLottery.mode)
async def step_mode(message: Message, state: FSMContext) -> None:
    mode = message.text.strip().lower()
    if mode not in ("random", "points"):
        await message.answer("❌ فقط بنویس random یا points")
        return
    await state.update_data(mode=mode)
    await state.set_state(CreateLottery.required_channels)
    await message.answer(
        f"✅ روش: <b>{mode}</b>\n\n"
        "📢 <b>مرحله ۷ از ۱۰</b>\n\nکانال‌های عضویت اجباری رو با کاما جدا کن:",
        reply_markup=cancel_kb()
    )

@router.message(CreateLottery.required_channels)
async def step_channels(message: Message, state: FSMContext) -> None:
    await state.update_data(required_channels=message.text.strip())
    await state.set_state(CreateLottery.publish_channel)
    await message.answer(
        "📢 <b>مرحله ۸ از ۱۰</b>\n\nکانال انتشار پست رو بفرست (مثلاً @mychannel):",
        reply_markup=cancel_kb()
    )

@router.message(CreateLottery.publish_channel)
async def step_publish(message: Message, state: FSMContext, bot: Bot) -> None:
    ch = message.text.strip()
    if not ch.startswith("@"):
        await message.answer("❌ با @ شروع کن (مثلاً @mychannel)")
        return
    try:
        await bot.get_chat(ch)
    except Exception:
        await message.answer("❌ ربات به این کانال دسترسی نداره. ادمینش کن.")
        return
    await state.update_data(publish_channel=ch)
    await state.set_state(CreateLottery.post_text)
    await message.answer(
        f"✅ کانال: <b>{ch}</b>\n\n"
        "📝 <b>مرحله ۹ از ۱۰</b>\n\nمتن پست قرعه‌کشی رو بفرست:",
        reply_markup=cancel_kb()
    )

@router.message(CreateLottery.post_text)
async def step_post(message: Message, state: FSMContext) -> None:
    await state.update_data(post_text=message.text)
    await state.set_state(CreateLottery.preview)
    data = await state.get_data()

    text = (
        f"📋 <b>پیش‌نمایش قرعه‌کشی:</b>\n\n"
        f"🏆 برندگان: <b>{data['winners_count']}</b>\n"
        f"🎁 جوایز:\n<code>{data['prizes']}</code>\n\n"
        f"👥 حداقل: {data['min_participants']}\n"
        f"👥 حداکثر: {data['max_participants']}\n"
        f"⏱ مدت: {data['duration_hours']} ساعت\n"
        f"🎲 روش: {data['mode']}\n"
        f"📢 کانال‌ها: {data['required_channels']}\n"
        f"📢 انتشار: {data['publish_channel']}\n\n"
        f"📝 متن پست:\n<code>{data['post_text']}</code>\n\n"
        "برای انتشار تأیید کن:"
    )
    await message.answer(text, reply_markup=confirm_lottery_kb())

@router.callback_query(F.data == "confirm_create")
async def cb_confirm_create(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    if not data:
        await callback.answer("اطلاعات ناقصه.", show_alert=True)
        return

    ends_at = datetime.now(timezone.utc) + timedelta(hours=float(data["duration_hours"]))

    try:
        lot_id = await db.create_lottery({
            "owner_id": callback.from_user.id,
            "winners_count": int(data["winners_count"]),
            "prizes": data["prizes"],
            "min_participants": int(data["min_participants"]),
            "max_participants": int(data["max_participants"]),
            "mode": data["mode"],
            "required_channels": data["required_channels"],
            "publish_channel": data["publish_channel"],
            "post_text": data["post_text"],
            "ends_at": ends_at,
        })
    except Exception as e:
        logger.exception(f"خطا در ساخت: {e}")
        await callback.message.edit_text(f"❌ خطا:\n<code>{type(e).__name__}: {e}</code>")
        return

    bot_info = await bot.get_me()
    channel_post = (
        f"{data['post_text']}\n\n"
        f"🏆 تعداد برندگان: {data['winners_count']}\n"
        f"🎁 جوایز:\n{data['prizes']}\n\n"
        f"⏱ پایان: {ends_at.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"برای شرکت روی دکمه زیر بزن 👇"
    )

    try:
        sent = await bot.send_message(
            chat_id=data["publish_channel"],
            text=channel_post,
            reply_markup=lottery_join_kb(lot_id, bot_info.username),
        )
        await db.set_post_message(lot_id, sent.message_id)
    except Exception as e:
        logger.exception(f"خطا در ارسال به کانال: {e}")
        await callback.message.edit_text(
            f"⚠️ قرعه‌کشی ساخته شد (#{lot_id}) ولی ارسال به کانال خطا داد:\n<code>{e}</code>"
        )
        return

    await callback.message.edit_text(
        f"✅ قرعه‌کشی #{lot_id} ساخته و در کانال منتشر شد!",
        reply_markup=back_to_menu_kb()
    )
    await callback.answer("ساخته شد!")

async def process_join(message: Message, lottery_id: int, bot: Bot, user_id: int, username) -> None:
    lot = await db.get_lottery(lottery_id)
    if not lot or lot["status"] != "active":
        await message.answer("❌ این قرعه‌کشی فعال نیست.")
        return

    channels = [c.strip() for c in lot["required_channels"].split(",") if c.strip()]
    not_joined = []
    for ch in channels:
        if not await is_member(bot, user_id):
            not_joined.append(ch)

    if not_joined:
        text = "⚠️ برای شرکت در این قرعه‌کشی اول باید در کانال عضو بشی:\n\n"
        for ch in not_joined:
            text += f"➡️ {ch}\n"
        await message.answer(text, reply_markup=join_channel_kb())
        return

    result = await db.join_lottery(lottery_id, user_id)
    if result == "ok":
        cnt = await db.count_participants(lottery_id)
        bot_info = await bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        await message.answer(
            f"🎉 با موفقیت در قرعه‌کشی #{lottery_id} ثبت‌نام شدی!\n\n"
            f"👥 تعداد شرکت‌کنندگان: {cnt}\n\n"
            f"🔗 لینک دعوت اختصاصی تو:\n{ref_link}\n\n"
            "با هر دعوت، یک امتیاز می‌گیری!"
        )
    elif result == "already":
        await message.answer("⚠️ قبلاً ثبت‌نام کردی.")
    elif result == "full":
        await message.answer("❌ ظرفیت پر شده.")

@router.callback_query(F.data == "active_lotteries")
async def cb_active_lotteries(callback: CallbackQuery, bot: Bot) -> None:
    try:
        rows = await db.get_active_lotteries(limit=10)
    except Exception as e:
        await callback.answer(f"❌ {type(e).__name__}: {e}", show_alert=True)
        return

    if not rows:
        text = "📋 هیچ قرعه‌کشی فعالی وجود ندارد."
    else:
        lines = ["📋 <b>قرعه‌کشی‌های فعال:</b>\n"]
        for r in rows:
            lines.append(f"🎁 #{r['id']} — {r['winners_count']} برنده")
        text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "my_lotteries")
async def cb_my_lotteries(callback: CallbackQuery) -> None:
    try:
        rows = await db.get_user_lotteries(callback.from_user.id, limit=10)
    except Exception as e:
        await callback.answer(f"❌ {type(e).__name__}: {e}", show_alert=True)
        return

    if not rows:
        text = "👤 هنوز قرعه‌کشی نساخته‌ای."
    else:
        lines = ["👤 <b>قرعه‌کشی‌های من:</b>\n"]
        for r in rows:
            status = {"active": "🟢 فعال", "finished": "🔴 پایان‌یافته", "cancelled": "⚫ لغو"}[r["status"]]
            lines.append(f"#{r['id']} — {status} — {r['winners_count']} برنده")
        text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
    await callback.answer()

@router.callback_query()
async def cb_fallback(callback: CallbackQuery) -> None:
    await callback.answer("این دکمه هنوز فعال نشده.", show_alert=True)

@router.message()
async def msg_fallback(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is not None:
        return 
    await message.answer("متوجه نشدم. از /menu استفاده کن.")

async def main() -> None:
    logger.info("در حال اتصال به دیتابیس...")
    await db.connect()
    
    logger.info("در حال بررسی جدول‌ها...")
    await init_db()

    logger.info("✅ همه چیز آماده است. شروع پولینگ...")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=PostgresStorage(db))
    dp.include_router(router)

    asyncio.create_task(lottery_checker(bot))

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()
        logger.info("ربات متوقف شد.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("خروج.")

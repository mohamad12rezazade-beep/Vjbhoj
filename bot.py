import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import BOT_TOKEN, DATABASE_URL, ADMIN_IDS
from database import Database, PostgresStorage
from keyboards import main_menu_kb, back_to_menu_kb

# ------------------- لاگ -------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("lottery-bot")

# ------------------- آبجکت‌های سراسری -------------------
db = Database(DATABASE_URL)
router = Router()


# ------------------- هندلرها -------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if user is None:
        return
    try:
        await db.upsert_user(user.id, user.username, user.first_name, user.last_name)
        if user.id in ADMIN_IDS:
            await db.set_admin(user.id, True)
    except Exception as e:
        logger.exception("خطا در ثبت کاربر: %s", e)
        await message.answer("❌ خطای داخلی. لطفاً بعداً امتحان کن.")
        return

    await message.answer(
        f"👋 سلام <b>{user.first_name}</b>!\n\n"
        "به ربات <b>قرعه‌کشی</b> خوش آمدی.\n"
        "از منوی زیر یک گزینه را انتخاب کن:",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("📋 منوی اصلی:", reply_markup=main_menu_kb())


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "📋 منوی اصلی:", reply_markup=main_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery) -> None:
    try:
        s = await db.stats()
    except Exception as e:
        logger.exception("خطا در آمار: %s", e)
        await callback.answer("❌ خطا در دریافت آمار", show_alert=True)
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
        "🔗 <b>دعوت دوستان:</b> با لینک اختصاصی، امتیاز بگیر و شانس برنده شدنت را بالا ببر."
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "create_lottery")
async def cb_create_lottery(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🎁 ساخت قرعه‌کشی\n\n"
        "⚠️ این بخش در مرحله بعدی اضافه می‌شود.\n"
        "فعلاً فقط زیرساخت تست می‌شود.",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "active_lotteries")
async def cb_active_lotteries(callback: CallbackQuery) -> None:
    try:
        rows = await db.get_active_lotteries(limit=10)
    except Exception as e:
        logger.exception("خطا در لیست فعال: %s", e)
        await callback.answer("❌ خطا", show_alert=True)
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
        logger.exception("خطا در قرعه‌کشی‌های من: %s", e)
        await callback.answer("❌ خطا", show_alert=True)
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
async def msg_fallback(message: Message) -> None:
    await message.answer(
        "متوجه نشدم. از /menu استفاده کن.",
    )


# ------------------- راه‌اندازی -------------------
async def main() -> None:
    logger.info("در حال اتصال به دیتابیس...")
    await db.connect()
    logger.info("اتصال برقرار شد. شروع پولینگ...")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=PostgresStorage(db))
    dp.include_router(router)

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

import logging
from datetime import datetime, timezone, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from config import ADMIN_IDS
from database import Database
from keyboards import (
    main_menu_kb, back_to_menu_kb, cancel_kb, confirm_lottery_kb,
    lottery_join_kb, join_confirm_kb, must_join_channels_kb, create_ref_link
)
from states import CreateLottery

logger = logging.getLogger("lottery-bot")
REQUIRED_CHANNEL = "@BET_1XZX"

def join_channel_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📢 عضویت در کانال", url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}"))
    builder.row(InlineKeyboardButton(text="✅ عضو شدم", callback_data="check_member"))
    return builder.as_markup()

async def is_member(bot: Bot, user_id: int, channel: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False

def setup_handlers(db: Database) -> Router:
    router = Router()

    async def show_lottery_preview(message: Message, lottery_id: int):
        lot = await db.get_lottery(lottery_id)
        if not lot or lot["status"] != "active":
            await message.answer("❌ این قرعه‌کشی فعال نیست یا به پایان رسیده.")
            return
        text = (
            f"🎁 <b>اطلاعات قرعه‌کشی #{lot['id']}</b>\n\n"
            f"📝 <b>توضیحات:</b>\n{lot['post_text']}\n\n"
            f"🏆 <b>تعداد برندگان:</b> {lot['winners_count']} نفر\n"
            f"🎁 <b>جوایز:</b>\n{lot['prizes']}\n\n"
            f"📢 <b>کانال‌های اجباری:</b>\n{lot['required_channels']}\n\n"
            f"👥 <b>حداقل شرکت‌کننده:</b> {lot['min_participants']}\n"
            f"⏱ <b>مدت باقی‌مانده:</b> تا {lot['ends_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
            f"آیا می‌خواهی در این قرعه‌کشی شرکت کنی؟"
        )
        await message.answer(text, reply_markup=join_confirm_kb(lottery_id))

    @router.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext, bot: Bot):
        await state.clear()
        user = message.from_user
        if user is None: return

        args = message.text.split()
        payload = args[1] if len(args) > 1 else None

        # ۱. اول چک عضویت کانال اجباری اصلی
        if not await is_member(bot, user.id, REQUIRED_CHANNEL):
            await message.answer(
                f"⚠️ برای استفاده از ربات، ابتدا باید در کانال زیر عضو بشی:\n\n➡️ {REQUIRED_CHANNEL}\n\nبعد از عضویت، روی دکمه «✅ عضو شدم» بزن.",
                reply_markup=join_channel_kb()
            )
            return

        # ۲. ثبت کاربر در دیتابیس
        try:
            await db.upsert_user(user.id, user.username, user.first_name, user.last_name)
            if user.id in ADMIN_IDS: await db.set_admin(user.id, True)
        except Exception as e:
            logger.exception(f"خطا در ثبت کاربر: {e}")
            return

        # ۳. بررسی لینک رفرال
        ref_lottery_id = None
        if payload and payload.startswith("ref_"):
            parts = payload.replace("ref_", "").split("_")
            if len(parts) >= 1:
                try:
                    referrer_id = int(parts[0])
                    success = await db.set_referrer_if_empty(user.id, referrer_id)
                    if success:
                        try: await bot.send_message(referrer_id, "🎉 یکی از دوستانت با لینک تو وارد ربات شد و <b>۱ امتیاز</b> گرفتی!")
                        except Exception: pass
                except Exception as e:
                    logger.exception(f"خطا در ثبت رفرال: {e}")
            if len(parts) >= 2:
                try: ref_lottery_id = int(parts[1])
                except Exception: pass

        # ۴. اگر با لینک قرعه‌کشی اومده بود (یا با لینک رفرال حاوی آیدی قرعه‌کشی)
        target_lottery_id = None
        if payload and payload.startswith("join_"):
            try: target_lottery_id = int(payload.replace("join_", ""))
            except Exception: pass
        elif ref_lottery_id is not None:
            target_lottery_id = ref_lottery_id

        if target_lottery_id is not None:
            await show_lottery_preview(message, target_lottery_id)
            return

        # ۵. منوی اصلی
        await message.answer(
            f"👋 سلام <b>{user.first_name}</b>!\n\nبه ربات <b>قرعه‌کشی</b> خوش آمدی.\nاز منوی زیر یک گزینه را انتخاب کن:",
            reply_markup=main_menu_kb(),
        )

    @router.callback_query(F.data == "check_member")
    async def cb_check_member(callback: CallbackQuery, bot: Bot):
        if await is_member(bot, callback.from_user.id, REQUIRED_CHANNEL):
            user = callback.from_user
            try:
                await db.upsert_user(user.id, user.username, user.first_name, user.last_name)
                if user.id in ADMIN_IDS: await db.set_admin(user.id, True)
            except Exception: pass
            await callback.message.edit_text(
                f"✅ عضویتت تأیید شد، خوش اومدی <b>{user.first_name}</b>!\n\nحالا می‌تونی از منوی زیر استفاده کنی یا دوباره روی لینک قرعه‌کشی کلیک کنی.",
                reply_markup=main_menu_kb()
            )
        else:
            await callback.answer("❌ هنوز عضو نشدی! اول عضو شو.", show_alert=True)

    @router.callback_query(F.data.startswith("do_join_"))
    async def cb_do_join(callback: CallbackQuery, bot: Bot):
        lottery_id = int(callback.data.replace("do_join_", ""))
        lot = await db.get_lottery(lottery_id)
        if not lot or lot["status"] != "active":
            await callback.answer("❌ این قرعه‌کشی فعال نیست.", show_alert=True)
            return
        channels = [c.strip() for c in lot["required_channels"].split(",") if c.strip()]
        not_joined = [ch for ch in channels if not await is_member(bot, callback.from_user.id, ch)]
        if not_joined:
            text = "⚠️ برای شرکت در این قرعه‌کشی، ابتدا باید در کانال‌های زیر عضو بشی:\n\n"
            for ch in not_joined: text += f"➡️ {ch}\n"
            await callback.message.edit_text(text, reply_markup=must_join_channels_kb(not_joined, lottery_id))
            await callback.answer()
            return
        await process_join(callback, lottery_id, bot, callback.from_user.id, db)

    @router.callback_query(F.data.startswith("check_lottery_member_"))
    async def cb_check_lottery_member(callback: CallbackQuery, bot: Bot):
        lottery_id = int(callback.data.replace("check_lottery_member_", ""))
        lot = await db.get_lottery(lottery_id)
        if not lot or lot["status"] != "active":
            await callback.answer("❌ این قرعه‌کشی فعال نیست.", show_alert=True)
            return
        channels = [c.strip() for c in lot["required_channels"].split(",") if c.strip()]
        still_not_joined = [ch for ch in channels if not await is_member(bot, callback.from_user.id, ch)]
        if still_not_joined:
            await callback.answer("❌ هنوز عضو همه کانال‌ها نشدی!", show_alert=True)
            return
        await process_join(callback, lottery_id, bot, callback.from_user.id, db)

    async def process_join(callback: CallbackQuery, lottery_id: int, bot: Bot, user_id: int, db_ref: Database):
        lot = await db_ref.get_lottery(lottery_id)
        result = await db_ref.join_lottery(lottery_id, user_id)
        
        if result == "ok":
            cnt = await db_ref.count_participants(lottery_id)
            ref_link = create_ref_link(user_id, lottery_id)
            text = (
                f"🎉 با موفقیت در قرعه‌کشی #{lottery_id} ثبت‌نام شدی!\n\n"
                f"👥 تعداد شرکت‌کنندگان: {cnt}\n\n"
                f"🌟 <b>+۱ امتیاز</b> بابت شرکت در قرعه‌کشی گرفتی!\n\n"
                f"🔗 <b>لینک دعوت اختصاصی تو:</b>\n{ref_link}\n\n"
                f"🎯 با هر بار دعوت از دوستانت، <b>۱ امتیاز</b> دیگه هم می‌گیری."
            )
            await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
            await callback.answer("ثبت‌نام شدی و ۱ امتیاز گرفتی! 🎉")
        elif result == "already":
            await callback.answer("⚠️ قبلاً در این قرعه‌کشی ثبت‌نام کرده‌ای!", show_alert=True)
            await callback.message.edit_text("شما قبلاً ثبت‌نام کرده بودید.", reply_markup=back_to_menu_kb())
        elif result == "full":
            await callback.answer("❌ ظرفیت پر شده.", show_alert=True)
            await callback.message.edit_text("ظرفیت پر شده.", reply_markup=back_to_menu_kb())
        elif result == "not_active":
            await callback.answer("❌ قرعه‌کشی فعال نیست.", show_alert=True)
            await callback.message.edit_text("قرعه‌کشی تمام شده.", reply_markup=back_to_menu_kb())

    @router.message(Command("menu"))
    async def cmd_menu(message: Message, state: FSMContext, bot: Bot):
        await state.clear()
        if not await is_member(bot, message.from_user.id, REQUIRED_CHANNEL):
            await message.answer("⚠️ اول در کانال عضو شو.", reply_markup=join_channel_kb())
            return
        await message.answer("📋 منوی اصلی:", reply_markup=main_menu_kb())

    @router.callback_query(F.data == "main_menu")
    async def cb_main_menu(callback: CallbackQuery, state: FSMContext, bot: Bot):
        await state.clear()
        if not await is_member(bot, callback.from_user.id, REQUIRED_CHANNEL):
            await callback.message.edit_text("⚠️ اول در کانال عضو شو.", reply_markup=join_channel_kb())
            await callback.answer()
            return
        await callback.message.edit_text("📋 منوی اصلی:", reply_markup=main_menu_kb())
        await callback.answer()

    @router.callback_query(F.data == "stats")
    async def cb_stats(callback: CallbackQuery):
        s = await db.stats()
        text = f"📊 <b>آمار ربات</b>\n\n👥 کاربران: <b>{s['users']}</b>\n🎁 قرعه‌کشی‌ها: <b>{s['lotteries']}</b>\n✅ فعال: <b>{s['active']}</b>\n🙋 شرکت‌کنندگان: <b>{s['participants']}</b>"
        await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
        await callback.answer()

    @router.callback_query(F.data == "help")
    async def cb_help(callback: CallbackQuery):
        text = "📖 <b>راهنمای استفاده</b>\n\n🎁 <b>ساخت قرعه‌کشی:</b> یک قرعه‌کشی جدید بساز\n📋 <b>قرعه‌کشی‌های فعال:</b> همه قرعه‌کشی‌های در جریان\n👤 <b>قرعه‌کشی‌های من:</b> قرعه‌کشی‌هایی که خودت ساختی\n📊 <b>آمار:</b> آمار کلی ربات\n\n🔗 <b>دعوت دوستان:</b> با لینک اختصاصی، امتیاز بگیر."
        await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
        await callback.answer()

    @router.callback_query(F.data == "create_lottery")
    async def cb_create_lottery(callback: CallbackQuery, state: FSMContext, bot: Bot):
        if not await is_member(bot, callback.from_user.id, REQUIRED_CHANNEL):
            await callback.answer("اول عضو کانال شو!", show_alert=True)
            return
        await state.clear()
        await state.set_state(CreateLottery.winners_count)
        await callback.message.edit_text("🎁 <b>مرحله ۱ از ۱۰</b>\n\nچند برنده می‌خوای؟ (یک عدد بفرست)", reply_markup=cancel_kb())
        await callback.answer()

    @router.message(CreateLottery.winners_count)
    async def step_winners(message: Message, state: FSMContext):
        try:
            text = message.text.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            n = int(text)
            if n <= 0: raise ValueError
        except:
            await message.answer("❌ یک عدد مثبت بفرست.")
            return
        await state.update_data(winners_count=n)
        await state.set_state(CreateLottery.prizes)
        await message.answer(f"✅ تعداد برندگان: <b>{n}</b>\n\n🎁 <b>مرحله ۲ از ۱۰</b>\n\nجوایز رو بنویس (هر جایزه در یک خط):", reply_markup=cancel_kb())

    @router.message(CreateLottery.prizes)
    async def step_prizes(message: Message, state: FSMContext):
        await state.update_data(prizes=message.text.strip())
        await state.set_state(CreateLottery.min_participants)
        await message.answer("👥 <b>مرحله ۳ از ۱۰</b>\n\nحداقل تعداد شرکت‌کننده چند نفر باشه؟", reply_markup=cancel_kb())

    @router.message(CreateLottery.min_participants)
    async def step_min(message: Message, state: FSMContext):
        try:
            text = message.text.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            n = int(text)
            if n <= 0: raise ValueError
        except:
            await message.answer("❌ یک عدد مثبت بفرست.")
            return
        await state.update_data(min_participants=n)
        await state.set_state(CreateLottery.max_participants)
        await message.answer(f"✅ حداقل: <b>{n}</b>\n\n👥 <b>مرحله ۴ از ۱۰</b>\n\nحداکثر تعداد شرکت‌کننده چند نفر باشه؟", reply_markup=cancel_kb())

    @router.message(CreateLottery.max_participants)
    async def step_max(message: Message, state: FSMContext):
        try:
            text = message.text.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            n = int(text)
        except:
            await message.answer("❌ یک عدد بفرست.")
            return
        data = await state.get_data()
        if n < data.get("min_participants", 1):
            await message.answer("❌ حداکثر باید بیشتر یا مساوی حداقل باشه.")
            return
        await state.update_data(max_participants=n)
        await state.set_state(CreateLottery.duration)
        await message.answer(f"✅ حداکثر: <b>{n}</b>\n\n⏱ <b>مرحله ۵ از ۱۰</b>\n\nمدت قرعه‌کشی چند ساعت باشه؟", reply_markup=cancel_kb())

    @router.message(CreateLottery.duration)
    async def step_duration(message: Message, state: FSMContext):
        try:
            text = message.text.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            h = float(text)
            if h <= 0: raise ValueError
        except:
            await message.answer("❌ یک عدد مثبت (ساعت) بفرست.")
            return
        await state.update_data(duration_hours=h)
        await state.set_state(CreateLottery.mode)
        await message.answer(f"✅ مدت: <b>{h} ساعت</b>\n\n🎲 <b>مرحله ۶ از ۱۰</b>\n\nروش قرعه‌کشی:\n<b>random</b> = تصادفی\n<b>points</b> = بر اساس امتیاز", reply_markup=cancel_kb())

    @router.message(CreateLottery.mode)
    async def step_mode(message: Message, state: FSMContext):
        mode = message.text.strip().lower()
        if mode not in ("random", "points"):
            await message.answer("❌ فقط بنویس random یا points")
            return
        await state.update_data(mode=mode)
        await state.set_state(CreateLottery.required_channels)
        await message.answer(f"✅ روش: <b>{mode}</b>\n\n📢 <b>مرحله ۷ از ۱۰</b>\n\nکانال‌های عضویت اجباری رو با کاما جدا کن (مثلاً @ch1,@ch2):", reply_markup=cancel_kb())

    @router.message(CreateLottery.required_channels)
    async def step_channels(message: Message, state: FSMContext):
        await state.update_data(required_channels=message.text.strip())
        await state.set_state(CreateLottery.publish_channel)
        await message.answer("📢 <b>مرحله ۸ از ۱۰</b>\n\nکانال انتشار پست رو بفرست (مثلاً @mychannel):", reply_markup=cancel_kb())

    @router.message(CreateLottery.publish_channel)
    async def step_publish(message: Message, state: FSMContext, bot: Bot):
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
        await message.answer(f"✅ کانال: <b>{ch}</b>\n\n📝 <b>مرحله ۹ از ۱۰</b>\n\nمتن پست قرعه‌کشی رو بفرست:", reply_markup=cancel_kb())

    @router.message(CreateLottery.post_text)
    async def step_post(message: Message, state: FSMContext):
        await state.update_data(post_text=message.text)
        await state.set_state(CreateLottery.preview)
        data = await state.get_data()
        text = (
            f"📋 <b>پیش‌نمایش قرعه‌کشی:</b>\n\n🏆 برندگان: <b>{data['winners_count']}</b>\n🎁 جوایز:\n<code>{data['prizes']}</code>\n\n👥 حداقل: {data['min_participants']}\n👥 حداکثر: {data['max_participants']}\n⏱ مدت: {data['duration_hours']} ساعت\n🎲 روش: {data['mode']}\n📢 کانال‌ها: {data['required_channels']}\n📢 انتشار: {data['publish_channel']}\n\n📝 متن پست:\n<code>{data['post_text']}</code>\n\nبرای انتشار تأیید کن:"
        )
        await message.answer(text, reply_markup=confirm_lottery_kb())

    @router.callback_query(F.data == "confirm_create")
    async def cb_confirm_create(callback: CallbackQuery, state: FSMContext, bot: Bot):
        data = await state.get_data()
        await state.clear()
        if not data:
            await callback.answer("اطلاعات ناقصه.", show_alert=True)
            return
        ends_at = datetime.now(timezone.utc) + timedelta(hours=float(data["duration_hours"]))
        try:
            lot_id = await db.create_lottery({
                "owner_id": callback.from_user.id, "winners_count": int(data["winners_count"]),
                "prizes": data["prizes"], "min_participants": int(data["min_participants"]),
                "max_participants": int(data["max_participants"]), "mode": data["mode"],
                "required_channels": data["required_channels"], "publish_channel": data["publish_channel"],
                "post_text": data["post_text"], "ends_at": ends_at,
            })
        except Exception as e:
            await callback.message.edit_text(f"❌ خطا:\n<code>{type(e).__name__}: {e}</code>")
            return
        channel_post = f"{data['post_text']}\n\n🏆 تعداد برندگان: {data['winners_count']}\n🎁 جوایز:\n{data['prizes']}\n\n⏱ پایان: {ends_at.strftime('%Y-%m-%d %H:%M UTC')}\n\nبرای شرکت روی دکمه زیر بزن 👇"
        try:
            sent = await bot.send_message(chat_id=data["publish_channel"], text=channel_post, reply_markup=lottery_join_kb(lot_id))
            await db.set_post_message(lot_id, sent.message_id)
        except Exception as e:
            await callback.message.edit_text(f"⚠️ قرعه‌کشی ساخته شد (#{lot_id}) ولی ارسال به کانال خطا داد:\n<code>{e}</code>")
            return
        await callback.message.edit_text(f"✅ قرعه‌کشی #{lot_id} ساخته و در کانال منتشر شد!", reply_markup=back_to_menu_kb())
        await callback.answer("ساخته شد!")

    @router.callback_query(F.data == "active_lotteries")
    async def cb_active_lotteries(callback: CallbackQuery):
        rows = await db.get_active_lotteries(limit=10)
        if not rows: text = "📋 هیچ قرعه‌کشی فعالی وجود ندارد."
        else:
            lines = ["📋 <b>قرعه‌کشی‌های فعال:</b>\n"]
            for r in rows: lines.append(f"🎁 #{r['id']} — {r['winners_count']} برنده")
            text = "\n".join(lines)
        await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
        await callback.answer()

    @router.callback_query(F.data == "my_lotteries")
    async def cb_my_lotteries(callback: CallbackQuery):
        rows = await db.get_user_lotteries(callback.from_user.id, limit=10)
        if not rows: text = "👤 هنوز قرعه‌کشی نساخته‌ای."
        else:
            lines = ["👤 <b>قرعه‌کشی‌های من:</b>\n"]
            for r in rows:
                status = {"active": "🟢 فعال", "finished": "🔴 پایان‌یافته", "cancelled": "⚫ لغو"}[r["status"]]
                lines.append(f"#{r['id']} — {status} — {r['winners_count']} برنده")
            text = "\n".join(lines)
        await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
        await callback.answer()

    @router.callback_query()
    async def cb_fallback(callback: CallbackQuery):
        await callback.answer("این دکمه هنوز فعال نشده.", show_alert=True)

    @router.message()
    async def msg_fallback(message: Message, state: FSMContext):
        current_state = await state.get_state()
        if current_state is not None: return
        await message.answer("متوجه نشدم. از /menu استفاده کن.")

    return router

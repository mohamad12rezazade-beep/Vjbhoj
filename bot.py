import asyncio
import logging
import sys
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, DATABASE_URL
from database import Database
from handlers import setup_handlers
import random

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("lottery-bot")

db = Database(DATABASE_URL)

async def init_db() -> None:
    async with db.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, is_admin BOOLEAN NOT NULL DEFAULT FALSE, points INTEGER NOT NULL DEFAULT 0, referred_by BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
            CREATE TABLE IF NOT EXISTS lotteries (id BIGSERIAL PRIMARY KEY, owner_id BIGINT NOT NULL, winners_count INTEGER NOT NULL, prizes TEXT NOT NULL, min_participants INTEGER NOT NULL DEFAULT 1, max_participants INTEGER NOT NULL, mode TEXT NOT NULL, required_channels TEXT NOT NULL DEFAULT '', publish_channel TEXT NOT NULL, post_text TEXT NOT NULL, post_message_id BIGINT, status TEXT NOT NULL DEFAULT 'active', ends_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), finished_at TIMESTAMPTZ);
            CREATE TABLE IF NOT EXISTS participants (id BIGSERIAL PRIMARY KEY, lottery_id BIGINT NOT NULL REFERENCES lotteries(id) ON DELETE CASCADE, user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(lottery_id, user_id));
            CREATE TABLE IF NOT EXISTS winners (id BIGSERIAL PRIMARY KEY, lottery_id BIGINT NOT NULL REFERENCES lotteries(id) ON DELETE CASCADE, user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, prize TEXT, position INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(lottery_id, user_id));
        """)
        logger.info("✅ جدول‌ها آماده هستند.")

async def finish_lottery(bot: Bot, lottery_id: int) -> None:
    lot = await db.get_lottery(lottery_id)
    if not lot or lot["status"] != "active": return
    participants = await db.get_participants(lottery_id)
    if len(participants) < lot["min_participants"]:
        await db.cancel_lottery(lottery_id)
        try: await bot.send_message(chat_id=lot["publish_channel"], text=f"⚠️ قرعه‌کشی #{lottery_id} لغو شد.")
        except: pass
        return
    if lot["mode"] == "points":
        participants.sort(key=lambda p: p["points"], reverse=True)
        selected = participants[:lot["winners_count"]]
    else:
        selected = random.sample(participants, min(lot["winners_count"], len(participants)))
    prizes = [p.strip() for p in lot["prizes"].split("\n") if p.strip()]
    winners_data = [(p["user_id"], prizes[i] if i < len(prizes) else f"جایزه {i+1}") for i, p in enumerate(selected)]
    await db.save_winners(lottery_id, winners_data)
    result_text = f"🏆 <b>نتیجه قرعه‌کشی #{lottery_id}</b>\n\n"
    for i, (uid, prize) in enumerate(winners_data):
        result_text += f"{i+1}. <a href='tg://user?id={uid}'>کاربر {uid}</a> — {prize}\n"
    try: await bot.send_message(chat_id=lot["publish_channel"], text=result_text, parse_mode="HTML")
    except: pass

async def lottery_checker(bot: Bot) -> None:
    while True:
        try:
            expired = await db.get_expired_active_lotteries()
            for lot in expired: await finish_lottery(bot, lot["id"])
        except: pass
        await asyncio.sleep(60)

async def main() -> None:
    await db.connect()
    await init_db()
    
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    
    # اینجا از فایل handlers.py استفاده میکنیم
    dp.include_router(setup_handlers(db))
    
    asyncio.create_task(lottery_checker(bot))

    logger.info("✅ ربات شروع به کار کرد...")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): pass

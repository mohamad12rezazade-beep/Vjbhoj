import os
from dotenv import load_dotenv

load_dotenv()

# توکن ربات تلگرام
BOT_TOKEN = os.getenv("BOT_TOKEN")

# آدرس اتصال PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")

# شناسه ادمین‌های ربات
ADMIN_IDS = [
    int(user_id)
    for user_id in os.getenv("ADMIN_IDS", "").split(",")
    if user_id.strip()
]

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN تنظیم نشده است!")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL تنظیم نشده است!")

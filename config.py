import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"متغیر محیطی {name} تنظیم نشده است.")
    return value


BOT_TOKEN: str = _require("BOT_TOKEN")
DATABASE_URL: str = _require("DATABASE_URL")

_admin_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = [int(x.strip()) for x in _admin_raw.split(",") if x.strip().isdigit()]

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"متغیر محیطی {name} تنظیم نشده است.")
    return value


@dataclass(frozen=True)
class Config:
    bot_token: str
    database_url: str
    # آیدی عددی ادمین اصلی (اولین ادمین)
    super_admin_id: int


def load_config() -> Config:
    return Config(
        bot_token=_require("BOT_TOKEN"),
        database_url=_require("DATABASE_URL"),
        super_admin_id=int(os.getenv("SUPER_ADMIN_ID", "0")),
    )


config = load_config()

import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
import asyncpg
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=5, command_timeout=60, statement_cache_size=0)
        logger.info("اتصال به دیتابیس برقرار شد.")

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def upsert_user(self, user_id: int, username: Optional[str], first_name: Optional[str], last_name: Optional[str]) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name, last_name = EXCLUDED.last_name
            """, user_id, username, first_name, last_name)

    async def get_user(self, user_id: int) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

    async def set_admin(self, user_id: int, is_admin: bool) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_admin = $1 WHERE user_id = $2", is_admin, user_id)

    async def set_referrer_if_empty(self, user_id: int, referrer_id: int) -> bool:
        if user_id == referrer_id: return False
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT referred_by FROM users WHERE user_id = $1 FOR UPDATE", user_id)
                if row is None or row["referred_by"] is not None: return False
                await conn.execute("UPDATE users SET referred_by = $1 WHERE user_id = $2", referrer_id, user_id)
                await conn.execute("UPDATE users SET points = points + 1 WHERE user_id = $1", referrer_id)
                return True

    async def create_lottery(self, data: dict[str, Any]) -> int:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("""
                    INSERT INTO lotteries (owner_id, winners_count, prizes, min_participants, max_participants, mode, required_channels, publish_channel, post_text, ends_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id
                """, data["owner_id"], data["winners_count"], data["prizes"], data["min_participants"], data["max_participants"], data["mode"], data["required_channels"], data["publish_channel"], data["post_text"], data["ends_at"])
                return row["id"]

    async def set_post_message(self, lottery_id: int, message_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE lotteries SET post_message_id = $1 WHERE id = $2", message_id, lottery_id)

    async def get_lottery(self, lottery_id: int) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM lotteries WHERE id = $1", lottery_id)

    async def get_active_lotteries(self, limit: int = 20) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM lotteries WHERE status='active' ORDER BY ends_at ASC LIMIT $1", limit)

    async def get_user_lotteries(self, owner_id: int, limit: int = 20) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM lotteries WHERE owner_id=$1 ORDER BY created_at DESC LIMIT $2", owner_id, limit)

    async def cancel_lottery(self, lottery_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE lotteries SET status='cancelled', finished_at=NOW() WHERE id=$1 AND status='active'", lottery_id)

    async def get_expired_active_lotteries(self) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM lotteries WHERE status='active' AND ends_at <= NOW()")

    async def is_participant(self, lottery_id: int, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT 1 FROM participants WHERE lottery_id=$1 AND user_id=$2", lottery_id, user_id)
        return row is not None

    async def count_participants(self, lottery_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM participants WHERE lottery_id=$1", lottery_id)

    async def join_lottery(self, lottery_id: int, user_id: int) -> Optional[str]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                lot = await conn.fetchrow("SELECT * FROM lotteries WHERE id=$1 FOR UPDATE", lottery_id)
                if lot is None or lot["status"] != "active": return "not_active"
                if lot["ends_at"] <= datetime.now(timezone.utc): return "not_active"
                if await conn.fetchrow("SELECT 1 FROM participants WHERE lottery_id=$1 AND user_id=$2", lottery_id, user_id): return "already"
                cnt = await conn.fetchval("SELECT COUNT(*) FROM participants WHERE lottery_id=$1", lottery_id)
                if cnt >= lot["max_participants"]: return "full"
                await conn.execute("INSERT INTO participants (lottery_id, user_id) VALUES ($1,$2)", lottery_id, user_id)
                return "ok"

    async def get_participants(self, lottery_id: int) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT p.user_id, u.points FROM participants p JOIN users u ON u.user_id=p.user_id WHERE p.lottery_id=$1", lottery_id)

    async def get_winner_ids(self, lottery_id: int) -> set[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM winners WHERE lottery_id=$1", lottery_id)
        return {r["user_id"] for r in rows}

    async def save_winners(self, lottery_id: int, winners: Iterable[tuple[int, str]]) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                pos = 0
                for user_id, prize in winners:
                    pos += 1
                    await conn.execute("INSERT INTO winners (lottery_id, user_id, prize, position) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", lottery_id, user_id, prize, pos)
                await conn.execute("UPDATE lotteries SET status='finished', finished_at=NOW() WHERE id=$1 AND status='active'", lottery_id)

    async def stats(self) -> dict[str, int]:
        async with self.pool.acquire() as conn:
            users = await conn.fetchval("SELECT COUNT(*) FROM users")
            lotteries = await conn.fetchval("SELECT COUNT(*) FROM lotteries")
            participants = await conn.fetchval("SELECT COUNT(*) FROM participants")
            active = await conn.fetchval("SELECT COUNT(*) FROM lotteries WHERE status='active'")
        return {"users": users, "lotteries": lotteries, "participants": participants, "active": active}

class PostgresStorage(BaseStorage):
    def __init__(self, db: Database) -> None:
        self.db = db
    async def set_state(self, key: StorageKey, state) -> None:
        state_value = state.state if isinstance(state, State) else state
        async with self.db.pool.acquire() as conn:
            await conn.execute("INSERT INTO fsm_states (user_id, state, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (user_id) DO UPDATE SET state = EXCLUDED.state, updated_at = NOW()", key.user_id, state_value)
    async def get_state(self, key: StorageKey):
        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT state FROM fsm_states WHERE user_id=$1", key.user_id)
        return row["state"] if row else None
    async def set_data(self, key: StorageKey, data: dict) -> None:
        async with self.db.pool.acquire() as conn:
            await conn.execute("INSERT INTO fsm_states (user_id, data, updated_at) VALUES ($1, $2::jsonb, NOW()) ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()", key.user_id, json.dumps(data, ensure_ascii=False))
    async def get_data(self, key: StorageKey) -> dict:
        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM fsm_states WHERE user_id=$1", key.user_id)
        return dict(row["data"]) if row and row["data"] else {}
    async def close(self) -> None:
        return None

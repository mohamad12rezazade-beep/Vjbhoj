import json
import asyncpg
from config import DATABASE_URL

_pool = None


async def connect_db():
    global _pool

    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            ssl="require",
            command_timeout=30
        )

    return _pool


async def close_db():
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool():
    if _pool is None:
        raise RuntimeError("Database is not connected")

    return _pool


async def save_user(user_id, username=None, first_name=None):
    await get_pool().execute("""
        INSERT INTO users (user_id, username, first_name)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name
    """, user_id, username, first_name)


async def create_giveaway(
    creator_id,
    winner_count,
    prizes,
    min_users,
    max_users,
    duration,
    mode,
    target_channel,
    post_text,
    required_channels
):
    async with get_pool().acquire() as conn:
        async with conn.transaction():

            await conn.execute("""
                INSERT INTO users (user_id)
                VALUES ($1)
                ON CONFLICT (user_id) DO NOTHING
            """, creator_id)

            giveaway_id = await conn.fetchval("""
                INSERT INTO giveaways (
                    creator_id,
                    winner_count,
                    prizes,
                    min_users,
                    max_users,
                    duration,
                    mode,
                    target_channel,
                    post_text,
                    status,
                    ends_at
                )
                VALUES (
                    $1, $2, $3::jsonb, $4, $5, $6, $7, $8, $9,
                    'active',
                    NOW() + ($6 * INTERVAL '1 hour')
                )
                RETURNING id
            """,
                creator_id,
                winner_count,
                json.dumps(prizes, ensure_ascii=False),
                min_users,
                max_users,
                duration,
                mode,
                str(target_channel),
                post_text
            )

            for channel in required_channels:
                await conn.execute("""
                    INSERT INTO required_channels (
                        giveaway_id,
                        chat_id,
                        title,
                        invite_link
                    )
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (giveaway_id, chat_id)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        invite_link = EXCLUDED.invite_link
                """,
                    giveaway_id,
                    str(channel["chat_id"]),
                    channel.get("title"),
                    channel.get("invite_link")
                )

            return giveaway_id


async def get_giveaway(giveaway_id):
    return await get_pool().fetchrow("""
        SELECT * FROM giveaways WHERE id = $1
    """, giveaway_id)


async def get_active_giveaways():
    return await get_pool().fetch("""
        SELECT * FROM giveaways
        WHERE status = 'active'
        ORDER BY ends_at ASC
    """)


async def get_user_giveaways(user_id):
    return await get_pool().fetch("""
        SELECT * FROM giveaways
        WHERE creator_id = $1
        ORDER BY created_at DESC
    """, user_id)


async def get_required_channels(giveaway_id):
    return await get_pool().fetch("""
        SELECT * FROM required_channels
        WHERE giveaway_id = $1
    """, giveaway_id)


async def add_participant(giveaway_id, user_id, referrer_id=None):
    async with get_pool().acquire() as conn:
        async with conn.transaction():

            giveaway = await conn.fetchrow("""
                SELECT * FROM giveaways
                WHERE id = $1
                FOR UPDATE
            """, giveaway_id)

            if not giveaway or giveaway["status"] != "active":
                return False, "ended"

            if giveaway["ends_at"] <= await conn.fetchval("SELECT NOW()"):
                return False, "ended"

            existing = await conn.fetchval("""
                SELECT 1 FROM participants
                WHERE giveaway_id = $1 AND user_id = $2
            """, giveaway_id, user_id)

            if existing:
                return False, "already_joined"

            count = await conn.fetchval("""
                SELECT COUNT(*) FROM participants
                WHERE giveaway_id = $1 AND active = TRUE
            """, giveaway_id)

            if count >= giveaway["max_users"]:
                return False, "full"

            await conn.execute("""
                INSERT INTO users (user_id)
                VALUES ($1)
                ON CONFLICT (user_id) DO NOTHING
            """, user_id)

            valid_referrer = None

            if referrer_id and referrer_id != user_id:
                is_valid = await conn.fetchval("""
                    SELECT 1 FROM participants
                    WHERE giveaway_id = $1
                      AND user_id = $2
                      AND active = TRUE
                """, giveaway_id, referrer_id)

                if is_valid:
                    valid_referrer = referrer_id

            await conn.execute("""
                INSERT INTO participants (
                    giveaway_id,
                    user_id,
                    active,
                    referral_count,
                    referred_by
                )
                VALUES ($1, $2, TRUE, 0, $3)
            """, giveaway_id, user_id, valid_referrer)

            if valid_referrer:
                inserted = await conn.fetchval("""
                    INSERT INTO referrals (
                        giveaway_id,
                        referrer_id,
                        referred_user_id
                    )
                    VALUES ($1, $2, $3)
                    ON CONFLICT DO NOTHING
                    RETURNING referred_user_id
                """, giveaway_id, valid_referrer, user_id)

                if inserted:
                    await conn.execute("""
                        UPDATE participants
                        SET referral_count = referral_count + 1
                        WHERE giveaway_id = $1 AND user_id = $2
                    """, giveaway_id, valid_referrer)

            return True, "joined"


async def get_participants(giveaway_id):
    return await get_pool().fetch("""
        SELECT * FROM participants
        WHERE giveaway_id = $1 AND active = TRUE
    """, giveaway_id)


async def save_winners(giveaway_id, winners):
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                DELETE FROM winners WHERE giveaway_id = $1
            """, giveaway_id)

            for position, winner in enumerate(winners, start=1):
                await conn.execute("""
                    INSERT INTO winners (
                        giveaway_id,
                        user_id,
                        position
                    )
                    VALUES ($1, $2, $3)
                    ON CONFLICT DO NOTHING
                """, giveaway_id, winner["user_id"], position)


async def get_winners(giveaway_id):
    return await get_pool().fetch("""
        SELECT w.*, p.referral_count
        FROM winners w
        LEFT JOIN participants p
          ON p.giveaway_id = w.giveaway_id
         AND p.user_id = w.user_id
        WHERE w.giveaway_id = $1
        ORDER BY w.position
    """, giveaway_id)


async def finish_giveaway(giveaway_id):
    return await get_pool().fetchrow("""
        UPDATE giveaways
        SET status = 'ended'
        WHERE id = $1 AND status = 'active'
        RETURNING *
    """, giveaway_id)


async def cancel_giveaway(giveaway_id):
    return await get_pool().fetchrow("""
        UPDATE giveaways
        SET status = 'cancelled'
        WHERE id = $1 AND status = 'active'
        RETURNING *
    """, giveaway_id)

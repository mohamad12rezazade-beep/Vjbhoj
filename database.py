import asyncpg
from config import DATABASE_URL

pool = None


async def connect_db():
    global pool

    if pool is None:
        pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            ssl="require"
        )


async def close_db():
    global pool

    if pool:
        await pool.close()
        pool = None


# -------------------------
# USERS
# -------------------------

async def save_user(user_id, username=None, first_name=None):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id)
            DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name
        """, user_id, username, first_name)


# -------------------------
# GIVEAWAYS
# -------------------------

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
    async with pool.acquire() as conn:
        async with conn.transaction():
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
                    $1, $2, $3::jsonb, $4, $5, $6,
                    $7, $8, $9, 'active',
                    NOW() + ($6 * INTERVAL '1 hour')
                )
                RETURNING id
            """,
                creator_id,
                winner_count,
                __import__("json").dumps(prizes),
                min_users,
                max_users,
                duration,
                mode,
                target_channel,
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
                """,
                    giveaway_id,
                    channel["chat_id"],
                    channel["title"],
                    channel["invite_link"]
                )

            return giveaway_id


async def get_giveaway(giveaway_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT *
            FROM giveaways
            WHERE id = $1
        """, giveaway_id)

        return dict(row) if row else None


async def get_active_giveaways():
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT *
            FROM giveaways
            WHERE status = 'active'
            ORDER BY created_at DESC
        """)

        return [dict(row) for row in rows]


async def get_user_giveaways(user_id):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT *
            FROM giveaways
            WHERE creator_id = $1
            ORDER BY created_at DESC
        """, user_id)

        return [dict(row) for row in rows]


async def cancel_giveaway(giveaway_id):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE giveaways
            SET status = 'cancelled'
            WHERE id = $1
        """, giveaway_id)


# -------------------------
# REQUIRED CHANNELS
# -------------------------

async def add_required_channel(
    giveaway_id,
    chat_id,
    title,
    invite_link
):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO required_channels (
                giveaway_id,
                chat_id,
                title,
                invite_link
            )
            VALUES ($1, $2, $3, $4)
        """, giveaway_id, str(chat_id), title, invite_link)


async def get_required_channels(giveaway_id):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT *
            FROM required_channels
            WHERE giveaway_id = $1
        """, giveaway_id)

        return [dict(row) for row in rows]


# -------------------------
# PARTICIPANTS
# -------------------------

async def add_participant(
    giveaway_id,
    user_id,
    referrer_id=None
):
    async with pool.acquire() as conn:
        async with conn.transaction():
            giveaway = await conn.fetchrow("""
                SELECT *
                FROM giveaways
                WHERE id = $1 AND status = 'active'
                FOR UPDATE
            """, giveaway_id)

            if not giveaway:
                return False

            existing = await conn.fetchval("""
                SELECT active
                FROM participants
                WHERE giveaway_id = $1 AND user_id = $2
            """, giveaway_id, user_id)

            if existing:
                return False

            count = await conn.fetchval("""
                SELECT COUNT(*)
                FROM participants
                WHERE giveaway_id = $1 AND active = TRUE
            """, giveaway_id)

            if count >= giveaway["max_users"]:
                return False

            await conn.execute("""
                INSERT INTO participants (
                    giveaway_id,
                    user_id,
                    active,
                    referral_count,
                    referred_by
                )
                VALUES ($1, $2, TRUE, 0, $3)
            """, giveaway_id, user_id, referrer_id)

            if referrer_id and referrer_id != user_id:
                await conn.execute("""
                    INSERT INTO referrals (
                        giveaway_id,
                        referrer_id,
                        referred_user_id
                    )
                    SELECT $1, $2, $3
                    WHERE EXISTS (
                        SELECT 1 FROM participants
                        WHERE giveaway_id = $1
                        AND user_id = $2
                        AND active = TRUE
                    )
                    ON CONFLICT (giveaway_id, referred_user_id)
                    DO NOTHING
                """, giveaway_id, referrer_id, user_id)

                await conn.execute("""
                    UPDATE participants
                    SET referral_count = (
                        SELECT COUNT(*)
                        FROM referrals
                        WHERE giveaway_id = $1
                        AND referrer_id = $2
                    )
                    WHERE giveaway_id = $1
                    AND user_id = $2
                    AND EXISTS (
                        SELECT 1 FROM referrals
                        WHERE giveaway_id = $1
                        AND referrer_id = $2
                        AND referred_user_id = $3
                    )
                """, giveaway_id, referrer_id, user_id)

            return True


async def get_participants(giveaway_id):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT *
            FROM participants
            WHERE giveaway_id = $1
            AND active = TRUE
        """, giveaway_id)

        return [dict(row) for row in rows]


# -------------------------
# REFERRALS
# -------------------------

async def add_referral(
    giveaway_id,
    referrer_id,
    referred_user_id
):
    if referrer_id == referred_user_id:
        return False

    async with pool.acquire() as conn:
        async with conn.transaction():
            referrer = await conn.fetchval("""
                SELECT active
                FROM participants
                WHERE giveaway_id = $1 AND user_id = $2
            """, giveaway_id, referrer_id)

            referred = await conn.fetchval("""
                SELECT active
                FROM participants
                WHERE giveaway_id = $1 AND user_id = $2
            """, giveaway_id, referred_user_id)

            if not referrer or not referred:
                return False

            result = await conn.execute("""
                INSERT INTO referrals (
                    giveaway_id,
                    referrer_id,
                    referred_user_id
                )
                VALUES ($1, $2, $3)
                ON CONFLICT (giveaway_id, referred_user_id)
                DO NOTHING
            """, giveaway_id, referrer_id, referred_user_id)

            if result.endswith("1"):
                await conn.execute("""
                    UPDATE participants
                    SET referral_count = referral_count + 1
                    WHERE giveaway_id = $1
                    AND user_id = $2
                """, giveaway_id, referrer_id)

                return True

            return False


# -------------------------
# WINNERS
# -------------------------

async def save_winners(giveaway_id, winners):
    async with pool.acquire() as conn:
        async with conn.transaction():
            for winner in winners:
                await conn.execute("""
                    INSERT INTO winners (
                        giveaway_id,
                        user_id,
                        position,
                        prize
                    )
                    VALUES ($1, $2, $3, $4)
                """,
                    giveaway_id,
                    winner["user_id"],
                    winner["position"],
                    winner["prize"]
                )


async def get_winners(giveaway_id):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT *
            FROM winners
            WHERE giveaway_id = $1
            ORDER BY position
        """, giveaway_id)

        return [dict(row) for row in rows]

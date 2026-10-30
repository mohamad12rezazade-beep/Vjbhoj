-- ============================================
-- Lottery Telegram Bot - Database Schema
-- ============================================

-- جدول کاربران
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    points INTEGER NOT NULL DEFAULT 0,
    referred_by BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by);
CREATE INDEX IF NOT EXISTS idx_users_is_admin ON users(is_admin);

-- جدول قرعه‌کشی‌ها
CREATE TABLE IF NOT EXISTS lotteries (
    id BIGSERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    winners_count INTEGER NOT NULL CHECK (winners_count > 0),
    prizes TEXT NOT NULL,                          -- جوایز به صورت متن (هر خط یک جایزه)
    min_participants INTEGER NOT NULL DEFAULT 1 CHECK (min_participants >= 1),
    max_participants INTEGER NOT NULL CHECK (max_participants >= min_participants),
    mode TEXT NOT NULL CHECK (mode IN ('random', 'points')),
    required_channels TEXT NOT NULL DEFAULT '',    -- با کاما جدا شده: @ch1,@ch2
    publish_channel TEXT NOT NULL,                 -- کانال انتشار پست و نتیجه
    post_text TEXT NOT NULL,
    post_message_id BIGINT,                        -- آیدی پیام پست در کانال انتشار
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'finished', 'cancelled')),
    ends_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_lotteries_status ON lotteries(status);
CREATE INDEX IF NOT EXISTS idx_lotteries_ends_at ON lotteries(ends_at);
CREATE INDEX IF NOT EXISTS idx_lotteries_owner ON lotteries(owner_id);

-- جدول شرکت‌کنندگان
CREATE TABLE IF NOT EXISTS participants (
    id BIGSERIAL PRIMARY KEY,
    lottery_id BIGINT NOT NULL REFERENCES lotteries(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(lottery_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_participants_lottery ON participants(lottery_id);
CREATE INDEX IF NOT EXISTS idx_participants_user ON participants(user_id);

-- جدول برندگان
CREATE TABLE IF NOT EXISTS winners (
    id BIGSERIAL PRIMARY KEY,
    lottery_id BIGINT NOT NULL REFERENCES lotteries(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    prize TEXT,
    position INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(lottery_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_winners_lottery ON winners(lottery_id);

-- جدول State های FSM (برای پایداری در GitHub Actions)
CREATE TABLE IF NOT EXISTS fsm_states (
    user_id BIGINT PRIMARY KEY,
    state TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fsm_updated ON fsm_states(updated_at);

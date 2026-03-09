-- ============================================
-- ZIK BOT SYSTEM (PostgreSQL)
-- ============================================

-- This schema is intentionally "simple + restart-safe":
-- all timers are derived from DB timestamps.

-- USERS
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    display_name TEXT,
    language VARCHAR(2) DEFAULT 'az',

    subscription_enabled BOOLEAN DEFAULT FALSE,
    subscription_end_at TIMESTAMPTZ,
    subscription_activated_at TIMESTAMPTZ,

    violations_count INTEGER DEFAULT 0,
    last_ban_days INTEGER DEFAULT 0,
    banned_until TIMESTAMPTZ,

    is_suspicious BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ZIK ACCOUNTS
CREATE TABLE IF NOT EXISTS zik_accounts (
    account_id SERIAL PRIMARY KEY,
    account_name TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    password TEXT NOT NULL,

    custom_url TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,

    is_active BOOLEAN DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'free', -- free | reserved | occupied
    current_user_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    reservation_until TIMESTAMPTZ,
    session_start TIMESTAMPTZ,
    session_end TIMESTAMPTZ,

    stop_requested BOOLEAN DEFAULT FALSE,
    delete_requested BOOLEAN DEFAULT FALSE,

    last_released_by BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    last_released_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- QUEUE
CREATE TABLE IF NOT EXISTS queue (
    queue_id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- One active queue row per user
CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_unique_active_user
ON queue(user_id)
WHERE is_active=TRUE;

CREATE INDEX IF NOT EXISTS idx_queue_active_position
ON queue(position)
WHERE is_active=TRUE;

-- SESSIONS
CREATE TABLE IF NOT EXISTS sessions (
    session_id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    account_id INTEGER REFERENCES zik_accounts(account_id) ON DELETE SET NULL,

    state TEXT NOT NULL, -- reserved | active | ended
    from_queue BOOLEAN DEFAULT FALSE,

    reserved_at TIMESTAMPTZ DEFAULT NOW(),
    confirm_deadline_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,

    session_start_at TIMESTAMPTZ,
    session_end_at TIMESTAMPTZ,

    ended_at TIMESTAMPTZ,
    ended_reason TEXT,

    extended_seconds INTEGER DEFAULT 0,

    token UUID UNIQUE NOT NULL,
    last_heartbeat_at TIMESTAMPTZ,

    extend_prompt_sent BOOLEAN DEFAULT FALSE,
    warn15_sent BOOLEAN DEFAULT FALSE,
    copy_sent BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_active
ON sessions(user_id, state)
WHERE state IN ('reserved','active');

CREATE INDEX IF NOT EXISTS idx_sessions_token
ON sessions(token);

-- RULES
CREATE TABLE IF NOT EXISTS rules (
    rules_id SERIAL PRIMARY KEY,
    rules_text_az TEXT,
    rules_text_ru TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    updated_by BIGINT REFERENCES users(user_id) ON DELETE SET NULL
);

-- SYSTEM STATE
CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- INIT
INSERT INTO rules (rules_text_az, rules_text_ru)
SELECT '-', '-'
WHERE NOT EXISTS (SELECT 1 FROM rules);

-- Complaints / Feedback
CREATE TABLE IF NOT EXISTS complaints (
  complaint_id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  username TEXT,
  display_name TEXT,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',   -- open | closed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  replied_at TIMESTAMPTZ,
  replied_by BIGINT,
  admin_reply TEXT,
  closed_at TIMESTAMPTZ,
  closed_by BIGINT
);

CREATE INDEX IF NOT EXISTS idx_complaints_status_created
  ON complaints(status, created_at DESC);

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

import asyncpg
import pytz

from config import Config


_SLUG_RE = re.compile(r"/zik/([^/?#]+)")


def now_baku() -> datetime:
    tz = pytz.timezone(Config.TIMEZONE)
    return datetime.now(tz)


def parse_slug(custom_url: str) -> str:
    """Extract slug from a full custom URL like https://.../zik/<slug>."""
    m = _SLUG_RE.search(custom_url)
    if not m:
        parts = [p for p in custom_url.split("/") if p]
        return parts[-1]
    return m.group(1)


def make_auto_slug(account_name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "-", (account_name or "").strip().lower()).strip("-")
    if not base:
        base = "account"
    return f"{base}-{uuid.uuid4().hex[:6]}"


def clean_pasted_value(value: str | None) -> str:
    if value is None:
        return ""

    s = str(value).replace("\ufeff", "").replace("\u200b", "").strip()
    quote_chars = "\"'“”‘’"

    while s and s[0] in quote_chars:
        s = s[1:].lstrip()

    while s and s[-1] in quote_chars:
        s = s[:-1].rstrip()

    return s


@dataclass
class Account:
    account_id: int
    account_name: str
    email: str
    password: str
    custom_url: str
    slug: str
    is_active: bool
    status: str
    current_user_id: Optional[int]
    reservation_until: Optional[datetime]
    session_end: Optional[datetime]


@dataclass
class Session:
    session_id: int
    user_id: int
    account_id: int
    state: str
    from_queue: bool
    confirm_deadline_at: Optional[datetime]
    session_end_at: Optional[datetime]
    token: str


class Database:
    """Asyncpg wrapper.

    This project is designed to be restart-safe: any timers are derived from DB timestamps.
    """

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def init(self) -> None:
        if self._pool is None:
            if not Config.DATABASE_URL:
                raise RuntimeError("DATABASE_URL is not set")
            self._pool = await asyncpg.create_pool(dsn=Config.DATABASE_URL, min_size=1, max_size=10)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    # -------------------- Users --------------------
    async def upsert_user(self, user_id: int, username: str | None) -> None:
        username = (username or "").lstrip("@").strip()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, username)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE
                SET username = EXCLUDED.username,
                    updated_at = NOW();
                """,
                user_id,
                username,
            )

    async def get_user(self, user_id: int) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
            return dict(row) if row else None

    async def set_language(self, user_id: int, lang: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE users SET language=$1, updated_at=NOW() WHERE user_id=$2", lang, user_id)

    async def get_language(self, user_id: int) -> str:
        user = await self.get_user(user_id)
        return (user or {}).get("language") or "az"

    async def set_display_name(self, user_id: int, display_name: str) -> None:
        display_name = display_name.strip()
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE users SET display_name=$1, updated_at=NOW() WHERE user_id=$2", display_name, user_id)

    async def set_subscription(self, user_id: int, end_at: datetime) -> bool:
        """Enable subscription until end_at. Returns True if it was an activation (not just extension)."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT subscription_enabled, subscription_end_at FROM users WHERE user_id=$1 FOR UPDATE",
                    user_id,
                )
                if not row:
                    return False
                was_enabled = bool(row["subscription_enabled"])
                prev_end = row["subscription_end_at"]
                activation = (not was_enabled) or (prev_end is None) or (prev_end < now_baku())
                await conn.execute(
                    """
                    UPDATE users
                    SET subscription_enabled=TRUE,
                        subscription_end_at=$2,
                        subscription_activated_at = CASE
                            WHEN subscription_activated_at IS NULL THEN NOW() ELSE subscription_activated_at
                        END,
                        updated_at=NOW()
                    WHERE user_id=$1
                    """,
                    user_id,
                    end_at,
                )
                return activation

    async def deactivate_subscription(self, user_id: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE users SET subscription_enabled=FALSE, updated_at=NOW() WHERE user_id=$1", user_id)

    async def is_user_allowed(self, user_id: int) -> tuple[bool, str | None]:
        """Return (allowed, reason_key).

        reason_key is one of: 'subscription_inactive', 'banned'
        """
        user = await self.get_user(user_id)
        if not user:
            return False, "subscription_inactive"

        if not user.get("subscription_enabled"):
            return False, "subscription_inactive"

        end_at = user.get("subscription_end_at")
        if end_at is None or end_at < now_baku():
            return False, "subscription_inactive"

        banned_until = user.get("banned_until")
        if banned_until is not None and banned_until > now_baku():
            return False, "banned"

        return True, None

    # -------------------- Rules --------------------
    async def get_rules(self) -> dict[str, str]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT rules_text_az, rules_text_ru FROM rules ORDER BY rules_id DESC LIMIT 1")
            if not row:
                return {"az": "-", "ru": "-"}
            return {"az": row["rules_text_az"] or "-", "ru": row["rules_text_ru"] or "-"}

    async def set_rules(self, *, az_text: str | None = None, ru_text: str | None = None, updated_by: int | None = None) -> None:
        current = await self.get_rules()
        az = az_text if az_text is not None else current["az"]
        ru = ru_text if ru_text is not None else current["ru"]
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO rules (rules_text_az, rules_text_ru, updated_by) VALUES ($1,$2,$3)",
                az,
                ru,
                updated_by,
            )

    async def save_creds_msg_ids(self, session_id: int, msg_ids: list[int]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE sessions SET creds_msg_ids=$2 WHERE session_id=$1",
                session_id,
                msg_ids,
            )

    async def pop_creds_msg_ids(self, session_id: int) -> list[int]:
        """Mesaj id-lərini qaytarır və DB-də dərhal NULL edir (təkrar silməsin)."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT creds_msg_ids FROM sessions WHERE session_id=$1 FOR UPDATE",
                    session_id,
                )
                ids = list(row["creds_msg_ids"] or []) if row else []
                await conn.execute("UPDATE sessions SET creds_msg_ids=NULL WHERE session_id=$1", session_id)
                return [int(x) for x in ids]

    async def save_timer_msg_ids(self, session_id: int, msg_ids: list[int]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE sessions SET timer_msg_ids=$2 WHERE session_id=$1",
                session_id,
                msg_ids,
            )

    async def pop_timer_msg_ids(self, session_id: int) -> list[int]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT timer_msg_ids FROM sessions WHERE session_id=$1 FOR UPDATE",
                    session_id,
                )
                ids = list(row["timer_msg_ids"] or []) if row else []
                await conn.execute("UPDATE sessions SET timer_msg_ids=NULL WHERE session_id=$1", session_id)
                return [int(x) for x in ids]

    # -------------------- Complaints / Feedback --------------------
    async def add_complaint(self, user_id: int, text: str) -> int:
        user = await self.get_user(user_id)
        username = user.get("username") if user else None
        display_name = user.get("display_name") if user else None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO complaints (user_id, username, display_name, text)
                VALUES ($1, $2, $3, $4)
                RETURNING complaint_id
                """,
                user_id,
                username,
                display_name,
                text,
            )
            return int(row["complaint_id"])

    async def list_complaints(self, status: str = "open", limit: int = 30):
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT complaint_id, user_id, username, display_name, text, status, created_at
                FROM complaints
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                status,
                limit,
            )
            return [dict(r) for r in rows]

    async def get_complaint(self, complaint_id: int):
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT complaint_id,
                       user_id,
                       username,
                       display_name,
                       text,
                       status,
                       created_at,
                       replied_at,
                       replied_by,
                       admin_reply,
                       closed_at,
                       closed_by
                FROM complaints
                WHERE complaint_id = $1
                """,
                complaint_id,
            )
            return dict(row) if row else None

    async def reply_complaint(self, complaint_id: int, admin_id: int, reply_text: str) -> bool:
        async with self._pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE complaints
                SET replied_at=NOW(),
                    replied_by=$2,
                    admin_reply=$3
                WHERE complaint_id = $1
                """,
                complaint_id,
                admin_id,
                reply_text,
            )
            return res.startswith("UPDATE 1")

    async def close_complaint(self, complaint_id: int, closed_by: int) -> bool:
        async with self._pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE complaints
                SET status='closed',
                    closed_at=NOW(),
                    closed_by=$2
                WHERE complaint_id = $1
                  AND status = 'open'
                """,
                complaint_id,
                closed_by,
            )
            return res.startswith("UPDATE 1")

    async def delete_complaint(self, complaint_id: int) -> bool:
        async with self._pool.acquire() as conn:
            res = await conn.execute("DELETE FROM complaints WHERE complaint_id=$1", complaint_id)
            return res.startswith("DELETE 1")

    # -------------------- Accounts --------------------
    async def list_accounts(self):
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    a.account_id,
                    a.account_name,
                    a.is_active,
                    a.status,

                    -- account table-də saxlanan fallback
                    a.current_user_id AS account_current_user_id,
                    a.session_start   AS account_session_start,
                    a.session_end     AS account_session_end,

                    -- current_user_id üçün user məlumatı (fallback)
                    u0.username       AS account_current_username,
                    u0.display_name   AS account_current_display_name,

                    -- ACTIVE session (latest)
                    act.user_id            AS active_user_id,
                    u1.username            AS active_username,
                    u1.display_name        AS active_display_name,
                    act.session_start_at   AS active_session_start_at,
                    act.session_end_at     AS active_session_end_at,

                    -- RESERVED session (latest)
                    res.user_id             AS reserved_user_id,
                    u2.username             AS reserved_username,
                    u2.display_name         AS reserved_display_name,
                    res.confirm_deadline_at AS reserved_deadline

                FROM zik_accounts a

                LEFT JOIN users u0 ON u0.user_id = a.current_user_id

                LEFT JOIN LATERAL (
                    SELECT s.user_id, s.confirm_deadline_at, s.session_start_at, s.session_end_at
                    FROM sessions s
                    WHERE s.account_id = a.account_id AND s.state = 'active'
                    ORDER BY s.session_start_at DESC NULLS LAST, s.session_id DESC
                    LIMIT 1
                ) act ON TRUE
                LEFT JOIN users u1 ON u1.user_id = act.user_id

                LEFT JOIN LATERAL (
                    SELECT s.user_id, s.confirm_deadline_at
                    FROM sessions s
                    WHERE s.account_id = a.account_id AND s.state = 'reserved'
                    ORDER BY s.created_at DESC NULLS LAST, s.session_id DESC
                    LIMIT 1
                ) res ON TRUE
                LEFT JOIN users u2 ON u2.user_id = res.user_id

                ORDER BY a.account_id ASC
                """
            )
            return [dict(r) for r in rows]

    async def get_account(self, account_id: int) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM zik_accounts WHERE account_id=$1", account_id)
            return dict(row) if row else None

    async def add_account(self, account_name: str, email: str, password: str, custom_url: str | None = None) -> None:
        account_name = clean_pasted_value(account_name)
        email = clean_pasted_value(email)
        password = clean_pasted_value(password)

        custom_url = clean_pasted_value(custom_url or Config.DEFAULT_ZIK_LOGIN_URL)
        if not custom_url:
            custom_url = Config.DEFAULT_ZIK_LOGIN_URL

        slug = make_auto_slug(account_name)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO zik_accounts (account_name, email, password, custom_url, slug)
                VALUES ($1,$2,$3,$4,$5)
                """,
                account_name,
                email,
                password,
                custom_url,
                slug,
            )

    async def update_account_credentials(
        self,
        account_id: int,
        email: str,
        password: str,
        custom_url: str | None = None,
    ) -> None:
        email = clean_pasted_value(email)
        password = clean_pasted_value(password)

        custom_url = clean_pasted_value(custom_url or Config.DEFAULT_ZIK_LOGIN_URL)
        if not custom_url:
            custom_url = Config.DEFAULT_ZIK_LOGIN_URL

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE zik_accounts
                SET email=$2,
                    password=$3,
                    custom_url=$4,
                    updated_at=NOW()
                WHERE account_id=$1
                """,
                account_id,
                email,
                password,
                custom_url,
            )

    async def request_stop_account(self, account_id: int) -> dict[str, Any]:
        """Mark stop_requested.

        If account is free, stop immediately (is_active=false).
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT status, is_active FROM zik_accounts WHERE account_id=$1 FOR UPDATE", account_id)
                if not row:
                    return {"ok": False, "reason": "not_found"}
                status = row["status"]
                is_active = row["is_active"]
                if not is_active:
                    return {"ok": False, "reason": "already_inactive"}
                if status == "free":
                    await conn.execute("UPDATE zik_accounts SET is_active=FALSE, stop_requested=FALSE, updated_at=NOW() WHERE account_id=$1", account_id)
                    return {"ok": True, "stopped_now": True}
                await conn.execute("UPDATE zik_accounts SET stop_requested=TRUE, updated_at=NOW() WHERE account_id=$1", account_id)
                return {"ok": True, "stopped_now": False}

    async def start_account(self, account_id: int) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT is_active FROM zik_accounts WHERE account_id=$1 FOR UPDATE", account_id)
                if not row:
                    return {"ok": False, "reason": "not_found"}
                if row["is_active"]:
                    return {"ok": False, "reason": "already_active"}
                await conn.execute("UPDATE zik_accounts SET is_active=TRUE, stop_requested=FALSE, updated_at=NOW() WHERE account_id=$1", account_id)
                return {"ok": True}

    async def request_delete_account(self, account_id: int) -> dict[str, Any]:
        """Delete immediately if free, otherwise mark delete_requested."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT status FROM zik_accounts WHERE account_id=$1 FOR UPDATE", account_id)
                if not row:
                    return {"ok": False, "reason": "not_found"}
                if row["status"] == "free":
                    await conn.execute("DELETE FROM zik_accounts WHERE account_id=$1", account_id)
                    return {"ok": True, "deleted_now": True}
                await conn.execute("UPDATE zik_accounts SET delete_requested=TRUE, updated_at=NOW() WHERE account_id=$1", account_id)
                return {"ok": True, "deleted_now": False}

    # -------------------- Queue --------------------
    async def queue_count(self) -> int:
        async with self._pool.acquire() as conn:
            return int(await conn.fetchval("SELECT COUNT(*) FROM queue WHERE is_active=TRUE"))

    async def is_in_queue(self, user_id: int) -> bool:
        async with self._pool.acquire() as conn:
            v = await conn.fetchval("SELECT 1 FROM queue WHERE user_id=$1 AND is_active=TRUE", user_id)
            return v is not None

    async def add_to_queue(self, user_id: int) -> int:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval("SELECT 1 FROM queue WHERE user_id=$1 AND is_active=TRUE", user_id)
                if exists:
                    pos = await conn.fetchval("SELECT position FROM queue WHERE user_id=$1 AND is_active=TRUE", user_id)
                    return int(pos)
                max_pos = await conn.fetchval("SELECT COALESCE(MAX(position),0) FROM queue WHERE is_active=TRUE")
                new_pos = int(max_pos) + 1
                await conn.execute("INSERT INTO queue (user_id, position, is_active) VALUES ($1,$2,TRUE)", user_id, new_pos)
                return new_pos

    async def pop_next_queue_user(self, conn: asyncpg.Connection) -> Optional[int]:
        """Pop next active queue user (within a transaction). Returns user_id or None."""
        row = await conn.fetchrow(
            """
            SELECT q.queue_id, q.user_id, q.position
            FROM queue q
            JOIN users u ON u.user_id = q.user_id
            WHERE q.is_active=TRUE
              AND u.subscription_enabled=TRUE
              AND u.subscription_end_at IS NOT NULL AND u.subscription_end_at > NOW()
              AND (u.banned_until IS NULL OR u.banned_until <= NOW())
            ORDER BY q.position ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
        if not row:
            return None
        queue_id = row["queue_id"]
        user_id = int(row["user_id"])
        position = int(row["position"])
        await conn.execute("UPDATE queue SET is_active=FALSE WHERE queue_id=$1", queue_id)
        await conn.execute("UPDATE queue SET position=position-1 WHERE is_active=TRUE AND position>$1", position)
        return user_id

    async def remove_from_queue(self, user_id: int) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT queue_id, position FROM queue WHERE user_id=$1 AND is_active=TRUE FOR UPDATE",
                    user_id,
                )
                if not row:
                    return
                position = int(row["position"])
                await conn.execute("UPDATE queue SET is_active=FALSE WHERE queue_id=$1", row["queue_id"])
                await conn.execute("UPDATE queue SET position=position-1 WHERE is_active=TRUE AND position>$1", position)

    # -------------------- Sessions / Reservations --------------------
    async def get_user_active_session(self, user_id: int) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.*, a.account_name, a.custom_url
                FROM sessions s
                JOIN zik_accounts a ON a.account_id = s.account_id
                WHERE s.user_id=$1 AND s.state IN ('reserved','active')
                ORDER BY s.session_id DESC
                LIMIT 1
                """,
                user_id,
            )
            return dict(row) if row else None

    async def reserve_free_account(self, user_id: int, *, from_queue: bool, confirm_minutes: int) -> Optional[dict[str, Any]]:
        """Reserve a free account for a user.

        Returns a dict with session + account fields, or None if no free accounts.
        """
        deadline = now_baku() + timedelta(minutes=confirm_minutes)
        token = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchval("SELECT 1 FROM sessions WHERE user_id=$1 AND state IN ('reserved','active')", user_id)
                if existing:
                    row = await conn.fetchrow(
                        """
                        SELECT s.*, a.account_name, a.custom_url
                        FROM sessions s
                        JOIN zik_accounts a ON a.account_id=s.account_id
                        WHERE s.user_id=$1 AND s.state IN ('reserved','active')
                        ORDER BY s.session_id DESC
                        LIMIT 1
                        """,
                        user_id,
                    )
                    return dict(row) if row else None

                acc = await conn.fetchrow(
                    """
                    SELECT *
                    FROM zik_accounts
                    WHERE is_active=TRUE AND status='free'
                    ORDER BY account_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
                if not acc:
                    return None
                account_id = int(acc["account_id"])
                await conn.execute(
                    """
                    UPDATE zik_accounts
                    SET status='reserved',
                        current_user_id=$2,
                        reservation_until=$3,
                        updated_at=NOW()
                    WHERE account_id=$1
                    """,
                    account_id,
                    user_id,
                    deadline,
                )
                row = await conn.fetchrow(
                    """
                    INSERT INTO sessions (user_id, account_id, state, from_queue, reserved_at, confirm_deadline_at, token)
                    VALUES ($1,$2,'reserved',$3,NOW(),$4,$5)
                    RETURNING *
                    """,
                    user_id,
                    account_id,
                    from_queue,
                    deadline,
                    token,
                )
                result = dict(row)
                result["account_name"] = acc["account_name"]
                result["custom_url"] = acc["custom_url"]
                return result

    async def cancel_offer(self, user_id: int, session_id: int) -> bool:
        """Cancel a reservation (reserved state)."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                s = await conn.fetchrow("SELECT * FROM sessions WHERE session_id=$1 FOR UPDATE", session_id)
                if not s:
                    return False
                if int(s["user_id"]) != user_id or s["state"] != "reserved":
                    return False
                account_id = int(s["account_id"])
                await conn.execute("UPDATE sessions SET state='ended', ended_at=NOW(), ended_reason='cancelled' WHERE session_id=$1", session_id)
                await conn.execute(
                    """
                    UPDATE zik_accounts
                    SET status='free', current_user_id=NULL, reservation_until=NULL, updated_at=NOW()
                    WHERE account_id=$1
                    """,
                    account_id,
                )

                a2 = await conn.fetchrow("SELECT stop_requested, delete_requested FROM zik_accounts WHERE account_id=$1 FOR UPDATE", account_id)
                if a2 and a2["delete_requested"]:
                    await conn.execute("DELETE FROM zik_accounts WHERE account_id=$1", account_id)
                elif a2 and a2["stop_requested"]:
                    await conn.execute("UPDATE zik_accounts SET is_active=FALSE, stop_requested=FALSE, updated_at=NOW() WHERE account_id=$1", account_id)
                return True

    async def confirm_session(self, user_id: int, session_id: int) -> Optional[dict[str, Any]]:
        """Confirm a reserved session and start the 60-min usage."""
        start = now_baku()
        end = start + timedelta(minutes=Config.DEFAULT_SESSION_MINUTES)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                s = await conn.fetchrow("SELECT * FROM sessions WHERE session_id=$1 FOR UPDATE", session_id)
                if not s:
                    return None
                if int(s["user_id"]) != user_id:
                    return None
                if s["state"] != "reserved":
                    return None
                if s["confirm_deadline_at"] is not None and s["confirm_deadline_at"] < start:
                    return None
                account_id = int(s["account_id"])
                a = await conn.fetchrow(
                    "SELECT status, current_user_id, custom_url, account_name FROM zik_accounts WHERE account_id=$1 FOR UPDATE",
                    account_id,
                )
                if not a or a["status"] != "reserved" or (a["current_user_id"] and int(a["current_user_id"]) != user_id):
                    return None
                await conn.execute(
                    """
                    UPDATE sessions
                    SET state='active',
                        confirmed_at=NOW(),
                        session_start_at=$2,
                        session_end_at=$3
                    WHERE session_id=$1
                    """,
                    session_id,
                    start,
                    end,
                )
                await conn.execute(
                    """
                    UPDATE zik_accounts
                    SET status='occupied',
                        reservation_until=NULL,
                        session_end=$2,
                        session_start=$3,
                        updated_at=NOW()
                    WHERE account_id=$1
                    """,
                    account_id,
                    end,
                    start,
                )
                out = dict(s)
                out["session_end_at"] = end
                out["token"] = s["token"]
                out["custom_url"] = a["custom_url"]
                out["account_name"] = a["account_name"]
                return out

    async def extend_session(self, user_id: int, session_id: int, minutes: int) -> Optional[dict[str, Any]]:
        if minutes not in Config.EXTEND_OPTIONS_MINUTES:
            return None
        add = timedelta(minutes=minutes)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                s = await conn.fetchrow("SELECT * FROM sessions WHERE session_id=$1 FOR UPDATE", session_id)
                if not s or s["state"] != "active" or int(s["user_id"]) != user_id:
                    return None
                end_at = s["session_end_at"]
                if end_at is None:
                    return None
                new_end = end_at + add
                new_ext = int(s["extended_seconds"] or 0) + int(add.total_seconds())
                await conn.execute(
                    """
                    UPDATE sessions
                    SET session_end_at=$2,
                        extended_seconds=$3,
                        extend_prompt_sent=FALSE,
                        warn15_sent=FALSE
                    WHERE session_id=$1
                    """,
                    session_id,
                    new_end,
                    new_ext,
                )
                await conn.execute("UPDATE zik_accounts SET session_end=$2, updated_at=NOW() WHERE account_id=$1", int(s["account_id"]), new_end)
                return {"new_end": new_end, "extended_minutes": minutes}

    async def update_heartbeat(self, token: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE sessions SET last_heartbeat_at=NOW() WHERE token=$1 AND state='active'", token)

    async def get_session_by_token(self, token: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.session_id, s.user_id, s.account_id, s.state, s.session_end_at, s.last_heartbeat_at,
                       a.email, a.password, a.account_name
                FROM sessions s
                JOIN zik_accounts a ON a.account_id=s.account_id
                WHERE s.token=$1
                LIMIT 1
                """,
                token,
            )
            return dict(row) if row else None

    async def mark_copy_sent(self, user_id: int, session_id: int) -> bool:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT copy_sent, user_id FROM sessions WHERE session_id=$1 FOR UPDATE", session_id)
                if not row or int(row["user_id"]) != user_id:
                    return False
                if row["copy_sent"]:
                    return False
                await conn.execute("UPDATE sessions SET copy_sent=TRUE WHERE session_id=$1", session_id)
                return True

    async def release_session(self, user_id: int, session_id: int, *, require_tab_closed: bool = True) -> dict[str, Any]:
        now = now_baku()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                s = await conn.fetchrow("SELECT * FROM sessions WHERE session_id=$1 FOR UPDATE", session_id)
                if not s or s["state"] != "active" or int(s["user_id"]) != user_id:
                    return {"ok": False, "reason": "not_found"}

                if require_tab_closed:
                    hb = s["last_heartbeat_at"]
                    if hb is not None:
                        age = (now - hb).total_seconds()
                        if age <= Config.HEARTBEAT_FRESH_SECONDS:
                            return {"ok": False, "reason": "tab_open"}

                account_id = int(s["account_id"])
                await conn.execute("UPDATE sessions SET state='ended', ended_at=NOW(), ended_reason='released' WHERE session_id=$1", session_id)
                await conn.execute(
                    """
                    UPDATE zik_accounts
                    SET status='free',
                        current_user_id=NULL,
                        reservation_until=NULL,
                        session_start=NULL,
                        session_end=NULL,
                        updated_at=NOW(),
                        last_released_by=$2,
                        last_released_at=NOW()
                    WHERE account_id=$1
                    """,
                    account_id,
                    user_id,
                )

                a = await conn.fetchrow("SELECT stop_requested, delete_requested FROM zik_accounts WHERE account_id=$1 FOR UPDATE", account_id)
                if a and a["delete_requested"]:
                    await conn.execute("DELETE FROM zik_accounts WHERE account_id=$1", account_id)
                elif a and a["stop_requested"]:
                    await conn.execute("UPDATE zik_accounts SET is_active=FALSE, stop_requested=FALSE, updated_at=NOW() WHERE account_id=$1", account_id)

                return {"ok": True, "account_id": account_id}

    async def expire_overdue(self) -> list[dict[str, Any]]:
        now = now_baku()
        events: list[dict[str, Any]] = []
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT s.session_id, s.user_id, s.account_id, s.from_queue, s.confirm_deadline_at, a.account_name
                    FROM sessions s
                    JOIN zik_accounts a ON a.account_id=s.account_id
                    WHERE s.state='reserved' AND s.confirm_deadline_at IS NOT NULL AND s.confirm_deadline_at < $1
                    FOR UPDATE SKIP LOCKED
                    """,
                    now,
                )
                for r in rows:
                    await conn.execute("UPDATE sessions SET state='ended', ended_at=NOW(), ended_reason='not_confirmed' WHERE session_id=$1", int(r["session_id"]))
                    await conn.execute("UPDATE zik_accounts SET status='free', current_user_id=NULL, reservation_until=NULL, updated_at=NOW() WHERE account_id=$1", int(r["account_id"]))

                    a = await conn.fetchrow("SELECT stop_requested, delete_requested FROM zik_accounts WHERE account_id=$1 FOR UPDATE", int(r["account_id"]))
                    if a and a["delete_requested"]:
                        await conn.execute("DELETE FROM zik_accounts WHERE account_id=$1", int(r["account_id"]))
                    elif a and a["stop_requested"]:
                        await conn.execute("UPDATE zik_accounts SET is_active=FALSE, stop_requested=FALSE, updated_at=NOW() WHERE account_id=$1", int(r["account_id"]))

                    events.append(
                        {
                            "type": "reservation_expired",
                            "user_id": int(r["user_id"]),
                            "from_queue": bool(r["from_queue"]),
                            "account_name": r["account_name"],
                            "session_id": int(r["session_id"]),
                        }
                    )

                rows2 = await conn.fetch(
                    """
                    SELECT s.session_id, s.user_id, s.account_id, s.session_end_at, a.account_name
                    FROM sessions s
                    JOIN zik_accounts a ON a.account_id=s.account_id
                    WHERE s.state='active' AND s.session_end_at IS NOT NULL AND s.session_end_at < $1
                    FOR UPDATE SKIP LOCKED
                    """,
                    now,
                )
                for r in rows2:
                    session_id = int(r["session_id"])
                    user_id = int(r["user_id"])
                    account_id = int(r["account_id"])

                    await conn.execute("UPDATE sessions SET state='ended', ended_at=NOW(), ended_reason='expired' WHERE session_id=$1", session_id)
                    await conn.execute(
                        """
                        UPDATE zik_accounts
                        SET status='free', current_user_id=NULL, reservation_until=NULL, session_start=NULL, session_end=NULL,
                            updated_at=NOW(), last_released_by=$2, last_released_at=NOW()
                        WHERE account_id=$1
                        """,
                        account_id,
                        user_id,
                    )

                    events.append({"type": "session_expired", "user_id": user_id, "account_name": r["account_name"], "session_id": session_id})

                    a = await conn.fetchrow("SELECT stop_requested, delete_requested FROM zik_accounts WHERE account_id=$1 FOR UPDATE", account_id)
                    if a and a["delete_requested"]:
                        await conn.execute("DELETE FROM zik_accounts WHERE account_id=$1", account_id)
                    elif a and a["stop_requested"]:
                        await conn.execute("UPDATE zik_accounts SET is_active=FALSE, stop_requested=FALSE, updated_at=NOW() WHERE account_id=$1", account_id)

        return events

    async def get_sessions_needing_prompts(self) -> list[dict[str, Any]]:
        now = now_baku()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.session_id, s.user_id, s.session_end_at, s.extend_prompt_sent, s.warn15_sent,
                       a.account_name, a.custom_url
                FROM sessions s
                JOIN zik_accounts a ON a.account_id=s.account_id
                WHERE s.state='active' AND s.session_end_at IS NOT NULL
                """
            )
            out: list[dict[str, Any]] = []
            for r in rows:
                end_at = r["session_end_at"]
                if end_at is None:
                    continue
                remaining = (end_at - now).total_seconds()
                if remaining <= 0:
                    continue
                needs_extend = remaining <= 30 * 60 and not r["extend_prompt_sent"]
                needs_warn15 = remaining <= 15 * 60 and not r["warn15_sent"]
                if needs_extend or needs_warn15:
                    out.append(
                        {
                            "session_id": int(r["session_id"]),
                            "user_id": int(r["user_id"]),
                            "remaining_seconds": int(remaining),
                            "needs_extend": needs_extend,
                            "needs_warn15": needs_warn15,
                            "account_name": r["account_name"],
                            "custom_url": r["custom_url"],
                        }
                    )
            return out

    async def mark_extend_prompt_sent(self, session_id: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE sessions SET extend_prompt_sent=TRUE WHERE session_id=$1", session_id)

    async def mark_warn15_sent(self, session_id: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE sessions SET warn15_sent=TRUE WHERE session_id=$1", session_id)

    # -------------------- Violations / Monthly reset --------------------
    async def add_violation_and_maybe_ban(self, user_id: int) -> dict[str, Any]:
        now = now_baku()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                u = await conn.fetchrow("SELECT violations_count, last_ban_days FROM users WHERE user_id=$1 FOR UPDATE", user_id)
                if not u:
                    return {"warn": 0, "banned": False}
                warnings = int(u["violations_count"] or 0) + 1
                last_ban_days = int(u["last_ban_days"] or 0)

                if warnings < Config.WARNINGS_BEFORE_BAN:
                    await conn.execute("UPDATE users SET violations_count=$2, updated_at=NOW() WHERE user_id=$1", user_id, warnings)
                    return {"warn": warnings, "banned": False}

                ban_days = last_ban_days + 1 if last_ban_days >= 1 else 1
                banned_until = now + timedelta(days=ban_days)
                await conn.execute(
                    """
                    UPDATE users
                    SET violations_count=0,
                        last_ban_days=$2,
                        banned_until=$3,
                        updated_at=NOW()
                    WHERE user_id=$1
                    """,
                    user_id,
                    ban_days,
                    banned_until,
                )
                return {"warn": Config.WARNINGS_BEFORE_BAN, "banned": True, "ban_days": ban_days, "banned_until": banned_until}

    async def restore_expired_bans(self) -> list[int]:
        now = now_baku()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM users WHERE banned_until IS NOT NULL AND banned_until <= $1", now)
            if not rows:
                return []
            ids = [int(r["user_id"]) for r in rows]
            await conn.execute("UPDATE users SET banned_until=NULL, updated_at=NOW() WHERE banned_until IS NOT NULL AND banned_until <= $1", now)
            return ids

    async def monthly_reset_if_needed(self) -> list[int]:
        now = now_baku()
        if now.day != 1:
            return []
        month_key = now.strftime("%Y-%m")

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                st = await conn.fetchrow("SELECT value FROM system_state WHERE key='last_monthly_reset' FOR UPDATE")
                if st and st["value"] == month_key:
                    return []

                banned_users = await conn.fetch("SELECT user_id FROM users WHERE banned_until IS NOT NULL")
                cleared_ids = [int(r["user_id"]) for r in banned_users]

                await conn.execute(
                    """
                    UPDATE users
                    SET violations_count=0,
                        last_ban_days=0,
                        banned_until=NULL,
                        updated_at=NOW();
                    """
                )

                await conn.execute(
                    """
                    INSERT INTO system_state (key, value)
                    VALUES ('last_monthly_reset', $1)
                    ON CONFLICT (key) DO UPDATE
                    SET value=EXCLUDED.value,
                        updated_at=NOW()
                    """,
                    month_key,
                )

                return cleared_ids

    # -------------------- Queue assignment helper --------------------
    async def assign_free_accounts_to_queue(self) -> list[dict[str, Any]]:
        assignments: list[dict[str, Any]] = []
        confirm_minutes = Config.CONFIRM_MINUTES_QUEUE
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                while True:
                    acc = await conn.fetchrow(
                        """
                        SELECT *
                        FROM zik_accounts
                        WHERE is_active=TRUE AND status='free'
                        ORDER BY account_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                        """
                    )
                    if not acc:
                        break
                    user_id = await self.pop_next_queue_user(conn)
                    if user_id is None:
                        break

                    deadline = now_baku() + timedelta(minutes=confirm_minutes)
                    token = str(uuid.uuid4())
                    account_id = int(acc["account_id"])

                    await conn.execute(
                        """
                        UPDATE zik_accounts
                        SET status='reserved', current_user_id=$2, reservation_until=$3, updated_at=NOW()
                        WHERE account_id=$1
                        """,
                        account_id,
                        user_id,
                        deadline,
                    )
                    s = await conn.fetchrow(
                        """
                        INSERT INTO sessions (user_id, account_id, state, from_queue, reserved_at, confirm_deadline_at, token)
                        VALUES ($1,$2,'reserved',TRUE,NOW(),$3,$4)
                        RETURNING session_id
                        """,
                        user_id,
                        account_id,
                        deadline,
                        token,
                    )
                    assignments.append(
                        {"user_id": user_id, "session_id": int(s["session_id"]), "account_name": acc["account_name"], "confirm_minutes": confirm_minutes}
                    )

        return assignments

    # -------------------- Admin users list --------------------
    async def list_users_for_admin(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, username, display_name, violations_count, last_ban_days, banned_until, is_suspicious,
                       subscription_enabled, subscription_end_at
                FROM users
                ORDER BY user_id
                """
            )
            return [dict(r) for r in rows]

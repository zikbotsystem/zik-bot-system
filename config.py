"""Project configuration.

⚠️ Secrets must be provided via environment variables.

Timezone: Asia/Baku
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


@dataclass(frozen=True)
class Config:
    # --- Telegram ---
    BOT_TOKEN: str = _env("BOT_TOKEN", "") or ""

    # Admin Telegram IDs (given in the technical assignment)
    ADMIN_IDS: tuple[int, ...] = (7665317457, 2091774116)

    # --- Database ---
    DATABASE_URL: str = _env("DATABASE_URL", "") or ""

    # --- App URLs ---
    # Base public URL of your web service (Render).
    # Used to build account links if you store only slugs.
    PUBLIC_BASE_URL: str = _env("PUBLIC_BASE_URL", "https://zikloginbot.onrender.com") or "https://zikloginbot.onrender.com"
    
    DEFAULT_ZIK_LOGIN_URL = "https://app.zikanalytics.com/login"

    # ZIK-in login səhifəsi (hamıda eyni olmalıdır)
    ZIK_LOGIN_URL = "https://app.zikanalytics.com/login"

    # ZIK Analytics login page (default is the current official app login)
    # If ZIK changes this, just update env var.
    ZIK_LOGIN_URL: str = _env("ZIK_LOGIN_URL", "https://app.zikanalytics.com/login") or "https://app.zikanalytics.com/login"

    # --- Timezone ---
    TIMEZONE: str = _env("TIMEZONE", "Asia/Baku") or "Asia/Baku"

    # --- Session/Queue timing (minutes) ---
    DEFAULT_SESSION_MINUTES: int = int(_env("DEFAULT_SESSION_MINUTES", "60") or "60")
    CONFIRM_MINUTES_DIRECT: int = int(_env("CONFIRM_MINUTES_DIRECT", "5") or "5")
    CONFIRM_MINUTES_QUEUE: int = int(_env("CONFIRM_MINUTES_QUEUE", "10") or "10")

    EXTEND_OPTIONS_MINUTES: tuple[int, ...] = (30, 60)

    # Extension heartbeat: if last heartbeat is newer than this, we assume the tab is still open.
    HEARTBEAT_FRESH_SECONDS: int = int(_env("HEARTBEAT_FRESH_SECONDS", "90") or "90")

    # Scheduler loop interval
    SCHEDULER_TICK_SECONDS: int = int(_env("SCHEDULER_TICK_SECONDS", "20") or "20")

    # --- Violations/Bans ---
    WARNINGS_BEFORE_BAN: int = int(_env("WARNINGS_BEFORE_BAN", "3") or "3")

    # --- Links / Content ---
    VIDEO_TUTORIAL_URL: str = _env("VIDEO_TUTORIAL_URL", "https://youtu.be/qDL4L3FSotc") or "https://youtu.be/qDL4L3FSotc" 

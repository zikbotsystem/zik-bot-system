from __future__ import annotations

from datetime import datetime

import pytz

from config import Config


_RU_MONTHS = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]

_AZ_MONTHS = [
    "yanvar",
    "fevral",
    "mart",
    "aprel",
    "may",
    "iyun",
    "iyul",
    "avqust",
    "sentyabr",
    "oktyabr",
    "noyabr",
    "dekabr",
]


def tz_now() -> datetime:
    return datetime.now(pytz.timezone(Config.TIMEZONE))


def format_dt(dt: datetime, lang: str) -> str:
    """Format: HH:MM, DD Month"""
    if dt.tzinfo is None:
        dt = pytz.timezone(Config.TIMEZONE).localize(dt)
    hhmm = dt.strftime("%H:%M")
    day = dt.day
    month_idx = dt.month - 1
    if lang == "ru":
        month = _RU_MONTHS[month_idx]
    else:
        month = _AZ_MONTHS[month_idx]
    return f"{hhmm}, {day:02d} {month}"


def add_months(dt: datetime, months: int) -> datetime:
    """Add months keeping day if possible, otherwise clamp to last day."""
    year = dt.year
    month = dt.month + months
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1

    # clamp day
    from calendar import monthrange

    last_day = monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def next_month_day_15(dt: datetime) -> datetime:
    """Return datetime set to the 15th of the next month at 23:59:59."""
    nxt = add_months(dt, 1)
    return nxt.replace(day=15, hour=23, minute=59, second=59, microsecond=0)


def parse_date(text: str, tz: str = Config.TIMEZONE) -> datetime | None:
    """Parse YYYY-MM-DD or DD.MM.YYYY into a timezone-aware datetime at 23:59:59."""
    text = text.strip()
    fmts = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"]
    for f in fmts:
        try:
            d = datetime.strptime(text, f)
            d = d.replace(hour=23, minute=59, second=59, microsecond=0)
            return pytz.timezone(tz).localize(d)
        except ValueError:
            continue
    return None

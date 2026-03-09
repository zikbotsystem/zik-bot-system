from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from config import Config
from database import Database
from utils import format_dt
from keyboards import kb_account_offer, kb_account_active, kb_extend_options


logger = logging.getLogger(__name__)


def _tr(lang: str, az: str, ru: str) -> str:
    return az if lang == "az" else ru


def _append_token(url: str, token: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}t={token}"


async def run_scheduler(bot: Bot, db: Database):
    """Background loop.

    Important: we do NOT rely on in-memory timers — everything is derived from timestamps in DB.
    """

    while True:
        try:
            # 1) Monthly reset (only on day 1)
            cleared = await db.monthly_reset_if_needed()
            for uid in cleared:
                lang = await db.get_language(uid)
                await bot.send_message(
                    uid,
                    _tr(lang, "✅ Yeni ay başladı. Qaydalar sıfırlandı və giriş bərpa olundu.", "✅ Наступил новый месяц. Нарушения сброшены и доступ восстановлен."),
                )

            # 2) Expired bans
            restored = await db.restore_expired_bans()
            for uid in restored:
                lang = await db.get_language(uid)
                await bot.send_message(
                    uid,
                    _tr(lang, "✅ ZIK Analytics-ə giriş bərpa olundu.", "✅ Доступ к ZIK Analytics восстановлен."),
                )

            # 3) Expire overdue reservations + sessions
            events = await db.expire_overdue()
            for ev in events:
                uid = ev["user_id"]
                lang = await db.get_language(uid)
                if ev["type"] == "reservation_expired":
                    minutes = Config.CONFIRM_MINUTES_QUEUE if ev.get("from_queue") else Config.CONFIRM_MINUTES_DIRECT
                    msg = _tr(
                        lang,
                        f"❗ Siz hesabı təyin edilmiş {minutes} dəqiqə ərzində götürmədiniz, ona görə də o sərbəst buraxıldı.",
                        f"❗ Так как вы не взяли аккаунт в течении выделенных {minutes} минут после его получения, он был освобожден.",
                    )
                    await bot.send_message(uid, msg)

                if ev["type"] == "session_expired":
                    # violation + possible ban
                    result = await db.add_violation_and_maybe_ban(uid)
                    if not result.get("banned"):
                        warn_no = int(result.get("warn") or 0)
                        msg = _tr(
                            lang,
                            f"❗ Siz botdan istifadə qaydalarını pozmusunuz (ZIK hesabını sərbəst buraxmamaq). Bu {warn_no}-ci xəbərdarlıqdır. 3 xəbərdarlıqdan sonra giriş 1 gün bağlanacaq.",
                            f"❗ Вы нарушили правила использования бота (не освободили аккаунт). Это {warn_no}-ое предупреждение. После 3-го предупреждения доступ будет закрыт на 1 день.",
                        )
                        await bot.send_message(uid, msg)
                    else:
                        ban_days = int(result.get("ban_days") or 1)
                        until = result.get("banned_until")
                        until_s = format_dt(until, lang) if until else "-"
                        msg = _tr(
                            lang,
                            f"‼️ 3 təkrar pozuntuya görə giriş {ban_days} gün bağlandı. Giriş {until_s} tarixində bərpa olunacaq.",
                            f"‼️ По причине трёх повторных нарушений доступ закрыт на {ban_days} день. Доступ восстановится в {until_s}.",
                        )
                        await bot.send_message(uid, msg)

            # 4) Assign free accounts to queue users
            assignments = await db.assign_free_accounts_to_queue()
            for a in assignments:
                uid = a["user_id"]
                lang = await db.get_language(uid)
                name = a["account_name"]
                session_id = int(a["session_id"])
                timeout = a["confirm_minutes"]
                text1 = _tr(lang, f"✅ Sərbəst ZIK hesabı tapıldı ({name})", f"✅ Найден свободный ZIK аккаунт ({name})")
                text2 = _tr(
                    lang,
                    f"❗ Əgər ZIK-ə daxil olmaq istəyirsinizsə, mütləq 'ZIK-ə daxil ol' düyməsini {timeout} dəqiqə ərzində basın. Əks halda hesab sərbəst buraxılacaq.",
                    f"❗ Если хотите войти в ZIK, обязательно нажмите кнопку 'Войти в ZIK' в течении {timeout} минут. Иначе аккаунт освободится.",
                )
                await bot.send_message(uid, text1)
                await bot.send_message(uid, text2, reply_markup=kb_account_offer(session_id, lang))

            # 5) 30min extend prompt + 15min warning
            prompts = await db.get_sessions_needing_prompts()
            for p in prompts:
                uid = p["user_id"]
                lang = await db.get_language(uid)
                session_id = int(p["session_id"])
                if p.get("needs_warn15"):
                    await db.mark_warn15_sent(session_id)
                    msg = _tr(
                        lang,
                        "❗ Sizə hesabdan istifadə etmək üçün 15 dəqiqə qalıb. Davam etmək istəyirsinizsə, botda 'Müddəti uzat' düyməsini basın.",
                        "❗ У вас осталось 15 минут. Если хотите продолжить, перейдите в бота и нажмите 'Продлить время'.",
                    )
                    await bot.send_message(uid, msg)
                if p.get("needs_extend"):
                    await db.mark_extend_prompt_sent(session_id)
                    msg = _tr(lang, "⏰ Müddəti uzat", "⏰ Продлить время")
                    await bot.send_message(uid, msg, reply_markup=kb_extend_options(session_id, lang))

        except Exception:
            logger.exception("Scheduler tick failed")

        await asyncio.sleep(Config.SCHEDULER_TICK_SECONDS)

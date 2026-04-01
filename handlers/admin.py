from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple
import re

import pytz
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config
from database import Database, now_baku
from keyboards import kb_admin_main, kb_back, kb_cancel
from locales import get_text
from utils import add_months, next_month_day_15, parse_date, tz_now

router = Router(name="admin")


def _get_admin_ids() -> list[int]:
    ids = getattr(Config, "ADMIN_IDS", []) or []
    return [int(x) for x in ids]


def _is_admin(user_id: int) -> bool:
    return int(user_id) in set(_get_admin_ids())


_BAKU_TZ = pytz.timezone(getattr(Config, "TIMEZONE", "Asia/Baku"))


def _to_baku(dt: Optional[datetime]) -> Optional[datetime]:
    if not dt:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        try:
            return dt.astimezone(_BAKU_TZ)
        except Exception:
            return dt
    try:
        return _BAKU_TZ.localize(dt)
    except Exception:
        return dt


def _tr(lang: str, az: str, ru: str) -> str:
    return az if lang == "az" else ru


def _format_who(display_name: str | None, username: str | None, user_id: int | None) -> str:
    parts: list[str] = []
    if display_name:
        parts.append(display_name)
    if username:
        parts.append(f"@{username}")
    base = " ".join(parts).strip()
    if base:
        return f"{base} ({user_id})" if user_id else base
    return str(user_id) if user_id else "-"


def _user_display_name(u: dict) -> str:
    display_name = (u.get("display_name") or "").strip()
    username = (u.get("username") or "").strip()

    if display_name:
        return display_name
    if username:
        return f"@{username}"
    return f"User {u['user_id']}"


def _user_sort_key(u: dict):
    created_at = _to_baku(u.get("created_at"))
    if created_at is None:
        return (1, int(u["user_id"]))
    return (0, created_at, int(u["user_id"]))


def _split_and_sort_users(users: list[dict]) -> tuple[list[dict], list[dict]]:
    admin_ids = _get_admin_ids()
    admin_set = set(admin_ids)

    admins = [u for u in users if int(u["user_id"]) in admin_set]
    regulars = [u for u in users if int(u["user_id"]) not in admin_set]

    admin_order = {uid: i for i, uid in enumerate(admin_ids)}
    admins.sort(key=lambda u: (admin_order.get(int(u["user_id"]), 999999),) + _user_sort_key(u))
    regulars.sort(key=_user_sort_key)

    return admins, regulars


def _format_mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    m = seconds // 60
    s = seconds % 60
    return f"{m}:{s:02d}"


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _extract_email_password(raw: str) -> Tuple[Optional[str], Optional[str]]:
    lines = [l.strip() for l in (raw or "").splitlines() if l.strip()]
    if not lines:
        return None, None

    email_idx = None
    for i, line in enumerate(lines):
        if _EMAIL_RE.match(line):
            email_idx = i
            break

    if email_idx is None:
        return None, None

    email = lines[email_idx]
    password = None

    if email_idx + 1 < len(lines):
        password = lines[email_idx + 1]

    if not password:
        for i, line in enumerate(lines):
            if i != email_idx:
                password = line
                break

    return email, password


def _zik_login_url() -> str:
    url = getattr(Config, "ZIK_LOGIN_URL", None) or "https://app.zikanalytics.com/login"
    return url.strip()


async def _show_user_details(
    target_user_id: int,
    event_message,
    db: Database,
    state: FSMContext,
    actor_user_id: int,
):
    lang = await db.get_language(actor_user_id)
    user = await db.get_user(target_user_id)

    if not user:
        await event_message.edit_text(
            _tr(lang, "❌ İstifadəçi tapılmadı", "❌ Пользователь не найден"),
            reply_markup=kb_back("admin:users", lang),
        )
        return

    await state.update_data(target_user_id=target_user_id)
    await state.set_state(UserSelect.user_id)

    sub_end = user.get("subscription_end_at")
    sub_end_s = sub_end.strftime("%Y-%m-%d") if sub_end else "-"
    sub_enabled = bool(user.get("subscription_enabled"))
    username = user.get("username")
    username_text = f"@{username}" if username else "-"

    text = _tr(
        lang,
        (
            f"İstifadəçi ID: {target_user_id}\n"
            f"Ad: {user.get('display_name') or '-'}\n"
            f"Username: {username_text}\n"
            f"Abunəlik: {'Aktiv' if sub_enabled else 'Deaktiv'}\n"
            f"Bitmə tarixi: {sub_end_s}"
        ),
        (
            f"Пользователь ID: {target_user_id}\n"
            f"Имя: {user.get('display_name') or '-'}\n"
            f"Username: {username_text}\n"
            f"Подписка: {'Активна' if sub_enabled else 'Деактивирована'}\n"
            f"Окончание: {sub_end_s}"
        ),
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=_tr(lang, "Ad təyin et", "Задать имя"), callback_data="admin:user:set_name")
    kb.button(text=_tr(lang, "1 ay aktiv et", "Активировать 1 месяц"), callback_data="admin:user:sub:1m")
    kb.button(text=_tr(lang, "Ayın 15-ə kimi", "До 15-го след. месяца"), callback_data="admin:user:sub:15")
    kb.button(text=_tr(lang, "Tarix seç", "Выбрать дату"), callback_data="admin:user:sub:custom")
    kb.button(text=_tr(lang, "Deaktiv et", "Деактивировать"), callback_data="admin:user:sub:off")
    kb.button(text=_tr(lang, "Sil", "Удалить"), callback_data="admin:user:delete")
    kb.button(text=get_text("back", lang), callback_data="admin:users")
    kb.adjust(2, 2, 2, 1)

    await event_message.edit_text(text, reply_markup=kb.as_markup())


class AddAccount(StatesGroup):
    name = State()
    creds = State()


class EditAccount(StatesGroup):
    acc_id = State()
    creds = State()


class SimpleAskId(StatesGroup):
    value = State()


class Announcement(StatesGroup):
    text = State()


class RulesEdit(StatesGroup):
    text = State()


class UserSelect(StatesGroup):
    user_id = State()


class UserSetName(StatesGroup):
    name = State()


class UserSubCustom(StatesGroup):
    date = State()


class ComplaintReply(StatesGroup):
    text = State()


@router.callback_query(F.data == "admin:main")
async def admin_main(callback: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Not allowed", show_alert=True)
        return

    await state.clear()
    lang = await db.get_language(callback.from_user.id)
    await callback.message.edit_text(get_text("admin_menu", lang), reply_markup=kb_admin_main(lang))
    await callback.answer()


@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Not allowed", show_alert=True)
        return

    await state.set_state(UserSelect.user_id)
    lang = await db.get_language(callback.from_user.id)
    users = await db.list_users_for_admin()

    if not users:
        await callback.message.edit_text(
            _tr(lang, "İstifadəçi yoxdur", "Пользователей нет"),
            reply_markup=kb_back("admin:main", lang),
        )
        await callback.answer()
        return

    admins, regulars = _split_and_sort_users(users)

    # əvvəlki siyahı mesajını dəyiş
    await callback.message.edit_text(
        _tr(
            lang,
            "İstifadəçilər siyahısı aşağıdadır:",
            "Список пользователей ниже:",
        ),
        reply_markup=kb_back("admin:main", lang),
    )

    async def send_user_block(u: dict):
        user_id = int(u["user_id"])
        name_part = _user_display_name(u)

        if user_id in set(_get_admin_ids()):
            name_part += " (Admin)"

        viol = int(u.get("violations_count") or 0)
        days = int(u.get("last_ban_days") or 0)
        sus = "⚠️ " if u.get("is_suspicious") else ""

        text = (
            f"{sus}{name_part}\n"
            f"{_tr(lang, f'Poz. - {viol} / Gün - {days}', f'Наруш. - {viol} / Дни - {days}')}\n"
            f"ID: {user_id}"
        )

        kb = InlineKeyboardBuilder()
        kb.button(text=str(user_id), callback_data=f"admin:user_open:{user_id}")
        kb.adjust(1)

        await callback.message.answer(text, reply_markup=kb.as_markup())

    # adminlər yuxarıda
    for u in admins:
        await send_user_block(u)

    # admin və user arası boş ayırıcı
    if admins and regulars:
        await callback.message.answer(" ")

    # adi userlər aşağıda
    for u in regulars:
        await send_user_block(u)

    # sonda izah mesajı
    await callback.message.answer(
        _tr(
            lang,
            "İstifadəçini açmaq üçün altındakı ID düyməsini basın.",
            "Чтобы открыть пользователя, нажмите кнопку ID под ним.",
        ),
        reply_markup=kb_back("admin:main", lang),
    )

    await callback.answer()


@router.callback_query(F.data.startswith("admin:user_open:"))
async def admin_user_open_from_button(cb: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)

    try:
        user_id = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer(_tr(lang, "ID yanlışdır", "Неверный ID"), show_alert=True)
        return

    user = await db.get_user(user_id)
    if not user:
        await cb.answer(_tr(lang, "İstifadəçi tapılmadı", "Пользователь не найден"), show_alert=True)
        return

    await _show_user_details(user_id, cb.message, db, state, cb.from_user.id)
    await cb.answer()


@router.message(UserSelect.user_id)
async def admin_user_selected(message: Message, db: Database, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    lang = await db.get_language(message.from_user.id)

    try:
        user_id = int((message.text or "").strip())
    except ValueError:
        await message.answer(_tr(lang, "❌ ID yanlışdır", "❌ Неверный ID"), reply_markup=kb_back("admin:main", lang))
        return

    user = await db.get_user(user_id)
    if not user:
        await message.answer(_tr(lang, "❌ İstifadəçi tapılmadı", "❌ Пользователь не найден"), reply_markup=kb_back("admin:users", lang))
        return

    await state.update_data(target_user_id=user_id)

    sub_end = user.get("subscription_end_at")
    sub_end_s = sub_end.strftime("%Y-%m-%d") if sub_end else "-"
    sub_enabled = bool(user.get("subscription_enabled"))
    username = user.get("username")
    username_text = f"@{username}" if username else "-"

    text = _tr(
        lang,
        (
            f"İstifadəçi ID: {user_id}\n"
            f"Ad: {user.get('display_name') or '-'}\n"
            f"Username: {username_text}\n"
            f"Abunəlik: {'Aktiv' if sub_enabled else 'Deaktiv'}\n"
            f"Bitmə tarixi: {sub_end_s}"
        ),
        (
            f"Пользователь ID: {user_id}\n"
            f"Имя: {user.get('display_name') or '-'}\n"
            f"Username: {username_text}\n"
            f"Подписка: {'Активна' if sub_enabled else 'Деактивирована'}\n"
            f"Окончание: {sub_end_s}"
        ),
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=_tr(lang, "Ad təyin et", "Задать имя"), callback_data="admin:user:set_name")
    kb.button(text=_tr(lang, "1 ay aktiv et", "Активировать 1 месяц"), callback_data="admin:user:sub:1m")
    kb.button(text=_tr(lang, "Ayın 15-ə kimi", "До 15-го след. месяца"), callback_data="admin:user:sub:15")
    kb.button(text=_tr(lang, "Tarix seç", "Выбрать дату"), callback_data="admin:user:sub:custom")
    kb.button(text=_tr(lang, "Deaktiv et", "Деактивировать"), callback_data="admin:user:sub:off")
    kb.button(text=_tr(lang, "Sil", "Удалить"), callback_data="admin:user:delete")
    kb.button(text=get_text("back", lang), callback_data="admin:users")
    kb.adjust(2, 2, 2, 1)

    await message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "admin:user:set_name")
async def admin_user_set_name(cb: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    await state.set_state(UserSetName.name)
    await cb.message.edit_text(
        _tr(lang, "İstifadəçinin adını yazın:", "Введите имя пользователя:"),
        reply_markup=kb_cancel("admin:users", lang),
    )
    await cb.answer()


@router.message(UserSetName.name)
async def admin_user_set_name_msg(message: Message, db: Database, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    lang = await db.get_language(message.from_user.id)
    data = await state.get_data()
    target = int(data.get("target_user_id")) if data.get("target_user_id") else None

    if not target:
        await state.clear()
        await message.answer(
            _tr(lang, "❌ Hədəf istifadəçi seçilməyib", "❌ Пользователь не выбран"),
            reply_markup=kb_back("admin:users", lang),
        )
        return

    await db.set_display_name(target, (message.text or "").strip())
    await state.set_state(UserSelect.user_id)
    await message.answer(_tr(lang, "✅ Ad yeniləndi", "✅ Имя обновлено"), reply_markup=kb_back("admin:users", lang))


@router.callback_query(F.data.startswith("admin:user:sub:"))
async def admin_user_sub(cb: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    data = await state.get_data()
    target = int(data.get("target_user_id")) if data.get("target_user_id") else None

    if not target:
        await cb.answer(_tr(lang, "İstifadəçi seçilməyib", "Пользователь не выбран"), show_alert=True)
        return

    action = cb.data.split(":")[-1]

    if action == "off":
        await db.deactivate_subscription(target)
        await cb.message.answer(_tr(lang, "✅ Abunəlik deaktiv edildi", "✅ Подписка деактивирована"))
        await cb.answer()
        return

    if action == "custom":
        await state.set_state(UserSubCustom.date)
        await cb.message.answer(_tr(lang, "Tarixi yazın (YYYY-MM-DD):", "Введите дату (YYYY-MM-DD):"))
        await cb.answer()
        return

    now = tz_now()
    if action == "1m":
        end_at = add_months(now, 1).replace(hour=23, minute=59, second=59, microsecond=0)
    elif action == "15":
        end_at = next_month_day_15(now)
    else:
        await cb.answer(_tr(lang, "❌ Seçim yanlışdır", "❌ Неверный выбор"), show_alert=True)
        return

    activated = await db.set_subscription(target, end_at)
    await cb.message.answer(
        _tr(
            lang,
            "✅ Abunəlik aktiv edildi" if activated else "✅ Abunəlik uzadıldı",
            "✅ Подписка активирована" if activated else "✅ Подписка продлена",
        )
    )
    await cb.answer()


@router.message(UserSubCustom.date)
async def admin_user_sub_custom(message: Message, db: Database, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    lang = await db.get_language(message.from_user.id)
    data = await state.get_data()
    target = int(data.get("target_user_id")) if data.get("target_user_id") else None

    dt = parse_date(message.text)
    if not dt:
        await message.answer(_tr(lang, "❌ Tarix formatı yanlışdır", "❌ Неверный формат даты"))
        return

    if not target:
        await message.answer(_tr(lang, "❌ İstifadəçi seçilməyib", "❌ Пользователь не выбран"))
        return

    activated = await db.set_subscription(target, dt)
    await state.set_state(UserSelect.user_id)
    await message.answer(
        _tr(
            lang,
            "✅ Abunəlik aktiv edildi" if activated else "✅ Abunəlik uzadıldı",
            "✅ Подписка активирована" if activated else "✅ Подписка продлена",
        ),
        reply_markup=kb_back("admin:users", lang),
    )


@router.callback_query(F.data == "admin:user:delete")
async def admin_user_delete(cb: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    data = await state.get_data()
    target = int(data.get("target_user_id")) if data.get("target_user_id") else None

    if not target:
        await cb.answer(_tr(lang, "İstifadəçi seçilməyib", "Пользователь не выбран"), show_alert=True)
        return

    async with db._pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE user_id=$1", target)

    await cb.message.answer(_tr(lang, "✅ İstifadəçi silindi", "✅ Пользователь удалён"), reply_markup=kb_back("admin:users", lang))
    await cb.answer()


@router.callback_query(F.data == "admin:accounts")
async def admin_accounts(callback: CallbackQuery, db: Database):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(callback.from_user.id)
    qcount = await db.queue_count()
    accounts = await db.list_accounts()

    header = _tr(
        lang,
        f"📊 Növbədə olan istifadəçilərin ümumi sayı - {qcount}\n\n",
        f"📊 Общее кол-во пользователей в очереди - {qcount}\n\n",
    )

    if not accounts:
        await callback.message.edit_text(header + _tr(lang, "Hesab yoxdur", "Аккаунтов нет"), reply_markup=kb_back("admin:main", lang))
        await callback.answer()
        return

    lines: list[str] = []

    for i, a in enumerate(accounts, start=1):
        left = _tr(lang, "Aktiv" if a.get("is_active") else "Deaktiv", "Активен" if a.get("is_active") else "Неактивен")
        status = a.get("status")

        auid = a.get("active_user_id")
        aun = a.get("active_username")
        adn = a.get("active_display_name")

        ruid = a.get("reserved_user_id")
        run = a.get("reserved_username")
        rdn = a.get("reserved_display_name")
        rdead = a.get("reserved_deadline")

        end_at = (
            a.get("active_session_end_at")
            or a.get("session_end_at")
            or a.get("active_end_at")
            or a.get("session_end")
            or a.get("account_session_end")
        )
        end_local = _to_baku(end_at)

        if status == "occupied" and auid:
            who = _format_who(adn, aun, int(auid))
            remain_mmss = "0:00"
            end_s = "-"
            if end_local:
                try:
                    remain_sec = int((end_local - now_baku()).total_seconds())
                    remain_mmss = _format_mmss(remain_sec)
                    end_s = end_local.strftime("%H:%M")
                except Exception:
                    pass

            right = _tr(
                lang,
                f"Məşğul: {who} | Qalan: {remain_mmss} | Bitir: {end_s}",
                f"Занят: {who} | Осталось: {remain_mmss} | Конец: {end_s}",
            )

        elif status == "reserved" and ruid:
            who = _format_who(rdn, run, int(ruid))
            remain_mmss = "0:00"
            if rdead:
                rdead_local = _to_baku(rdead)
                if rdead_local:
                    remain_sec = int((rdead_local - now_baku()).total_seconds())
                    remain_mmss = _format_mmss(remain_sec)

            right = _tr(
                lang,
                f"Rezervdə: {who} — {remain_mmss}",
                f"Резерв: {who} — {remain_mmss}",
            )
        else:
            right = _tr(lang, "Sərbəst", "Свободен")

        lines.append(f"{i}. {left} | {a['account_name']} | {right} (ID:{a['account_id']})")

    await callback.message.edit_text(header + "\n".join(lines), reply_markup=kb_back("admin:main", lang))
    await callback.answer()


@router.callback_query(F.data == "admin:manage_accounts")
async def admin_manage_accounts(callback: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Not allowed", show_alert=True)
        return

    await state.clear()
    lang = await db.get_language(callback.from_user.id)

    kb = InlineKeyboardBuilder()
    kb.button(text=_tr(lang, "Hesab əlavə et", "Добавить аккаунт"), callback_data="admin:acc:add")
    kb.button(text=_tr(lang, "Hesabı redaktə et", "Редактировать"), callback_data="admin:acc:edit")
    kb.button(text=_tr(lang, "Dayandır", "Остановить"), callback_data="admin:acc:stop")
    kb.button(text=_tr(lang, "Başlat", "Запустить"), callback_data="admin:acc:start")
    kb.button(text=_tr(lang, "Sil", "Удалить"), callback_data="admin:acc:delete")
    kb.button(text=get_text("back", lang), callback_data="admin:main")
    kb.adjust(2, 2, 1, 1)

    await callback.message.edit_text(get_text("manage_accounts", lang), reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data == "admin:acc:add")
async def admin_acc_add(cb: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    await state.set_state(AddAccount.name)
    await cb.message.edit_text(get_text("enter_account_name", lang), reply_markup=kb_cancel("admin:manage_accounts", lang))
    await cb.answer()


@router.message(AddAccount.name)
async def admin_acc_add_name(message: Message, db: Database, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    lang = await db.get_language(message.from_user.id)
    await state.update_data(account_name=(message.text or "").strip())
    await state.set_state(AddAccount.creds)

    await message.answer(
        _tr(lang, "Gmail və Parolu göndərin (başlıq yazsanız da olar):", "Отправьте Gmail и пароль (можно с заголовком):"),
        reply_markup=kb_cancel("admin:manage_accounts", lang),
    )


@router.message(AddAccount.creds)
async def admin_acc_add_creds(message: Message, db: Database, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    lang = await db.get_language(message.from_user.id)
    data = await state.get_data()
    account_name = (data.get("account_name") or "").strip()

    email, password = _extract_email_password(message.text or "")
    if not email or not password:
        await message.answer(_tr(lang, "❌ Format yanlışdır. Email və parolu göndərin.", "❌ Неверный формат. Отправьте email и пароль."))
        return

    try:
        await db.add_account(account_name, email, password, _zik_login_url())
    except Exception as e:
        await message.answer(_tr(lang, f"❌ Xəta: {e}", f"❌ Ошибка: {e}"))
        return

    await state.clear()
    await message.answer(get_text("account_added", lang), reply_markup=kb_back("admin:manage_accounts", lang))


@router.callback_query(F.data == "admin:acc:edit")
async def admin_acc_edit(cb: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    await state.set_state(EditAccount.acc_id)
    await cb.message.answer(
        _tr(lang, "Redaktə üçün hesab ID göndərin:", "Отправьте ID аккаунта для редактирования:"),
        reply_markup=kb_cancel("admin:manage_accounts", lang),
    )
    await cb.answer()


@router.message(EditAccount.acc_id)
async def admin_acc_edit_id(message: Message, db: Database, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    lang = await db.get_language(message.from_user.id)
    try:
        acc_id = int((message.text or "").strip())
    except ValueError:
        await message.answer(_tr(lang, "❌ ID yanlışdır", "❌ Неверный ID"))
        return

    acc = await db.get_account(acc_id)
    if not acc:
        await message.answer(_tr(lang, "❌ Hesab tapılmadı", "❌ Аккаунт не найден"))
        return

    await state.update_data(acc_id=acc_id)
    await state.set_state(EditAccount.creds)
    await message.answer(_tr(lang, "Yeni Gmail və Parolu göndərin (başlıq yazsanız da olar):", "Отправьте новый Gmail и пароль (можно с заголовком):"))


@router.message(EditAccount.creds)
async def admin_acc_edit_creds(message: Message, db: Database, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    lang = await db.get_language(message.from_user.id)
    data = await state.get_data()
    acc_id = int(data.get("acc_id") or 0)

    if not acc_id:
        await state.clear()
        await message.answer(_tr(lang, "❌ Hesab seçilməyib", "❌ Аккаунт не выбран"))
        return

    email, password = _extract_email_password(message.text or "")
    if not email or not password:
        await message.answer(_tr(lang, "❌ Format yanlışdır. Email və parolu göndərin.", "❌ Неверный формат. Отправьте email и пароль."))
        return

    try:
        await db.update_account_credentials(acc_id, email, password, _zik_login_url())
    except Exception as e:
        await message.answer(_tr(lang, f"❌ Xəta: {e}", f"❌ Ошибка: {e}"))
        return

    await state.clear()
    await message.answer(get_text("account_updated", lang), reply_markup=kb_back("admin:manage_accounts", lang))


@router.callback_query(F.data.in_({"admin:acc:stop", "admin:acc:start", "admin:acc:delete"}))
async def admin_acc_action(cb: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    action = cb.data.split(":")[-1]
    await state.set_state(SimpleAskId.value)
    await state.update_data(acc_action=action)

    await cb.message.answer(
        _tr(
            lang,
            "Hesab ID göndərin:\n(Məs: siyahıda ID:5 yazılıbsa 5 göndərin)",
            "Отправьте ID аккаунта:\n(Напр: если в списке ID:5 — отправьте 5)",
        ),
        reply_markup=kb_cancel("admin:manage_accounts", lang),
    )
    await cb.answer()


@router.message(SimpleAskId.value)
async def admin_acc_action_id(message: Message, db: Database, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    lang = await db.get_language(message.from_user.id)
    data = await state.get_data()
    action = data.get("acc_action")

    try:
        acc_id = int((message.text or "").strip())
    except ValueError:
        await message.answer(_tr(lang, "❌ ID yanlışdır", "❌ Неверный ID"))
        return

    if action == "stop":
        res = await db.request_stop_account(acc_id)
        if res.get("ok"):
            text = _tr(
                lang,
                "✅ Dayandırıldı" if res.get("stopped_now") else "✅ Dayandırılma sorğusu qəbul edildi",
                "✅ Остановлен" if res.get("stopped_now") else "✅ Запрос на остановку принят",
            )
        else:
            text = _tr(lang, "❌ Dayandırmaq olmadı", "❌ Не удалось остановить")
    elif action == "start":
        res = await db.start_account(acc_id)
        text = _tr(lang, "✅ Başladı" if res.get("ok") else "❌ Başlatmaq olmadı", "✅ Запущен" if res.get("ok") else "❌ Не удалось запустить")
    elif action == "delete":
        res = await db.request_delete_account(acc_id)
        if res.get("ok"):
            text = _tr(
                lang,
                "✅ Silindi" if res.get("deleted_now") else "✅ Silinmə sorğusu qəbul edildi",
                "✅ Удалён" if res.get("deleted_now") else "✅ Запрос на удаление принят",
            )
        else:
            text = _tr(lang, "❌ Silmək olmadı", "❌ Не удалось удалить")
    else:
        text = _tr(lang, "❌ Əməliyyat tapılmadı", "❌ Неизвестное действие")

    await state.clear()
    await message.answer(text, reply_markup=kb_back("admin:manage_accounts", lang))


@router.callback_query(F.data == "admin:announcement")
async def admin_announcement(cb: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    await state.set_state(Announcement.text)
    await cb.message.edit_text(get_text("enter_message", lang), reply_markup=kb_cancel("admin:main", lang))
    await cb.answer()


@router.message(Announcement.text)
async def admin_announcement_send(message: Message, db: Database, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    lang = await db.get_language(message.from_user.id)
    text = (message.text or "").strip()

    async with db._pool.acquire() as conn:
        ids = await conn.fetch("SELECT user_id FROM users")

    ok = 0
    for r in ids:
        uid = int(r["user_id"])
        if uid == message.from_user.id:
            continue
        try:
            await message.bot.send_message(uid, text)
            ok += 1
        except Exception:
            pass

    await state.clear()
    await message.answer(
        _tr(lang, f"✅ Mesaj {ok} istifadəçiyə göndərildi", f"✅ Сообщение отправлено {ok} пользователям"),
        reply_markup=kb_back("admin:main", lang),
    )


@router.callback_query(F.data == "admin:rules")
async def admin_rules(cb: CallbackQuery, db: Database):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    rules = await db.get_rules()
    text = rules.get(lang, "-")

    kb = InlineKeyboardBuilder()
    kb.button(text=_tr(lang, "AZ dəyiş", "Изменить AZ"), callback_data="admin:rules:edit:az")
    kb.button(text=_tr(lang, "RU dəyiş", "Изменить RU"), callback_data="admin:rules:edit:ru")
    kb.button(text=get_text("back", lang), callback_data="admin:main")
    kb.adjust(2, 1)

    await cb.message.edit_text(text, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("admin:rules:edit:"))
async def admin_rules_edit(cb: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    target_lang = cb.data.split(":")[-1]
    await state.set_state(RulesEdit.text)
    await state.update_data(rules_lang=target_lang)
    await cb.message.edit_text(_tr(lang, "Yeni qaydaları göndərin:", "Отправьте новые правила:"), reply_markup=kb_cancel("admin:rules", lang))
    await cb.answer()


@router.message(RulesEdit.text)
async def admin_rules_edit_save(message: Message, db: Database, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    lang = await db.get_language(message.from_user.id)
    data = await state.get_data()
    rules_lang = data.get("rules_lang")
    txt = (message.text or "").strip()

    if rules_lang == "az":
        await db.set_rules(az_text=txt, updated_by=message.from_user.id)
    else:
        await db.set_rules(ru_text=txt, updated_by=message.from_user.id)

    await state.clear()
    await message.answer(get_text("rules_updated", lang), reply_markup=kb_back("admin:rules", lang))


@router.callback_query(F.data == "admin:complaints")
async def admin_complaints(cb: CallbackQuery, db: Database):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    items = await db.list_complaints(status="open", limit=30)

    if not items:
        await cb.message.edit_text(
            _tr(lang, "📨 Açıq şikayət yoxdur.", "📨 Открытых жалоб нет."),
            reply_markup=kb_back("admin:main", lang),
        )
        await cb.answer()
        return

    lines = []
    kb = InlineKeyboardBuilder()

    for i, c in enumerate(items, start=1):
        cid = int(c["complaint_id"])
        uid = int(c["user_id"])
        who = _format_who(c.get("display_name"), c.get("username"), uid)

        preview = (c.get("text") or "").replace("\n", " ").strip()
        if len(preview) > 40:
            preview = preview[:40] + "…"

        lines.append(f"{i}) #{cid} | {who} | {preview}")
        kb.button(text=f"#{cid}", callback_data=f"admin:complaint:view:{cid}")

    kb.button(text=get_text("back", lang), callback_data="admin:main")
    kb.adjust(5, 5, 5, 5, 1)

    text = _tr(lang, "📨 Açıq şikayətlər:\n\n", "📨 Открытые жалобы:\n\n") + "\n".join(lines)
    await cb.message.edit_text(text, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("admin:complaint:view:"))
async def admin_complaint_view(cb: CallbackQuery, db: Database):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    cid = int(cb.data.split(":")[-1])

    c = await db.get_complaint(cid)
    if not c:
        await cb.answer(_tr(lang, "Tapılmadı", "Не найдено"), show_alert=True)
        return

    uid = int(c["user_id"])
    who = _format_who(c.get("display_name"), c.get("username"), uid)

    admin_reply = c.get("admin_reply")
    reply_block = ""
    if admin_reply:
        reply_block = _tr(
            lang,
            f"\n\n💬 <b>Admin cavabı:</b>\n{admin_reply}",
            f"\n\n💬 <b>Ответ админа:</b>\n{admin_reply}",
        )

    text = _tr(
        lang,
        f"📨 <b>Şikayət</b> #{cid}\n👤 {who}\n📌 Status: <b>{c['status']}</b>\n\n{c['text']}{reply_block}",
        f"📨 <b>Жалоба</b> #{cid}\n👤 {who}\n📌 Статус: <b>{c['status']}</b>\n\n{c['text']}{reply_block}",
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=_tr(lang, "✉️ Cavab yaz", "✉️ Ответить"), callback_data=f"admin:complaint:reply:{cid}")
    kb.button(text=_tr(lang, "✅ Bağla", "✅ Закрыть"), callback_data=f"admin:complaint:close:{cid}")
    kb.button(text=_tr(lang, "🗑 Sil", "🗑 Удалить"), callback_data=f"admin:complaint:delete:{cid}")
    kb.button(text=get_text("back", lang), callback_data="admin:complaints")
    kb.adjust(2, 2)

    await cb.message.edit_text(text, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("admin:complaint:reply:"))
async def admin_complaint_reply_start(cb: CallbackQuery, db: Database, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    cid = int(cb.data.split(":")[-1])

    c = await db.get_complaint(cid)
    if not c:
        await cb.answer(_tr(lang, "Tapılmadı", "Не найдено"), show_alert=True)
        return

    await state.set_state(ComplaintReply.text)
    await state.update_data(reply_cid=cid)

    await cb.message.answer(_tr(lang, f"✍️ Şikayət #{cid} üçün cavabı yazın:", f"✍️ Напишите ответ для жалобы #{cid}:"))
    await cb.answer()


@router.message(ComplaintReply.text)
async def admin_complaint_reply_send(message: Message, db: Database, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    lang = await db.get_language(message.from_user.id)
    data = await state.get_data()
    cid = data.get("reply_cid")

    if not cid:
        await state.clear()
        await message.answer(_tr(lang, "❌ Şikayət seçilməyib", "❌ Жалоба не выбрана"), reply_markup=kb_back("admin:complaints", lang))
        return

    c = await db.get_complaint(int(cid))
    if not c:
        await state.clear()
        await message.answer(_tr(lang, "❌ Şikayət tapılmadı", "❌ Жалоба не найдена"), reply_markup=kb_back("admin:complaints", lang))
        return

    reply_text = (message.text or "").strip()
    if len(reply_text) < 2:
        await message.answer(_tr(lang, "❌ Cavab çox qısadır", "❌ Слишком коротко"))
        return

    user_id = int(c["user_id"])

    try:
        await message.bot.send_message(
            user_id,
            _tr(
                lang,
                f"📩 <b>Admin cavabı</b> (Şikayət #{cid}):\n\n{reply_text}",
                f"📩 <b>Ответ администратора</b> (Жалоба #{cid}):\n\n{reply_text}",
            ),
        )
    except Exception as e:
        await message.answer(_tr(lang, f"❌ Göndərilmədi: {e}", f"❌ Не отправлено: {e}"))
        return

    await db.reply_complaint(int(cid), message.from_user.id, reply_text)

    await state.clear()
    await message.answer(_tr(lang, "✅ Cavab göndərildi", "✅ Ответ отправлен"), reply_markup=kb_back("admin:complaints", lang))


@router.callback_query(F.data.startswith("admin:complaint:close:"))
async def admin_complaint_close(cb: CallbackQuery, db: Database):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    cid = int(cb.data.split(":")[-1])

    ok = await db.close_complaint(cid, cb.from_user.id)
    await cb.answer(_tr(lang, "Bağlandı" if ok else "Bağlanmadı", "Закрыто" if ok else "Не закрыто"), show_alert=True)
    await admin_complaints(cb, db)


@router.callback_query(F.data.startswith("admin:complaint:delete:"))
async def admin_complaint_delete(cb: CallbackQuery, db: Database):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not allowed", show_alert=True)
        return

    lang = await db.get_language(cb.from_user.id)
    cid = int(cb.data.split(":")[-1])

    ok = await db.delete_complaint(cid)
    await cb.answer(_tr(lang, "Silindi" if ok else "Silinmədi", "Удалено" if ok else "Не удалено"), show_alert=True)
    await admin_complaints(cb, db)

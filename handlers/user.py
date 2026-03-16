from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config
from database import Database, now_baku
from keyboards import (
    kb_account_active,
    kb_account_offer,
    kb_back,
    kb_extend_options,
    kb_queue_offer,
    kb_user_main,
)

router = Router(name="user")


# ---------- Complaint/Feedback FSM ----------
class ComplaintState(StatesGroup):
    text = State()


def _tr(lang: str, az: str, ru: str) -> str:
    return az if lang == "az" else ru


def _append_token(url: str | None, token: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}t={token}"


def _get_admin_ids() -> list[int]:
    ids = getattr(Config, "ADMIN_IDS", None)
    if isinstance(ids, (list, tuple)) and ids:
        return [int(x) for x in ids]
    single = getattr(Config, "ADMIN_ID", None)
    if single:
        return [int(single)]
    return []


def _is_admin(user_id: int) -> bool:
    return user_id in set(_get_admin_ids())


async def _safe_delete_messages(bot, chat_id: int, message_ids: list[int]) -> None:
    for mid in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=int(mid))
        except Exception:
            pass


def kb_home_menu(lang: str, user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text=_tr(lang, "👤 İstifadəçi menyusu", "👤 Меню пользователя"), callback_data="user:main")
    if _is_admin(user_id):
        kb.button(text=_tr(lang, "👑 Admin menyusu", "👑 Админ меню"), callback_data="admin:main")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "user:main")
async def user_main(callback: CallbackQuery, db: Database):
    lang = await db.get_language(callback.from_user.id)
    await callback.message.edit_text(
        "👤 Menyu" if lang == "az" else "👤 Меню",
        reply_markup=kb_user_main(lang),
    )
    await callback.answer()


@router.callback_query(F.data == "user:back")
async def user_back(callback: CallbackQuery, db: Database, state: FSMContext):
    await state.clear()
    lang = await db.get_language(callback.from_user.id)
    await callback.message.edit_text(
        _tr(lang, "🏠 Əsas menyu", "🏠 Главное меню"),
        reply_markup=kb_home_menu(lang, callback.from_user.id),
    )
    await callback.answer()


@router.callback_query(F.data == "user:fines")
async def user_fines(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    lang = await db.get_language(user_id)
    user = await db.get_user(user_id) or {}

    violations = int(user.get("violations_count") or 0)
    last_ban_days = int(user.get("last_ban_days") or 0)
    banned_until = user.get("banned_until")
    banned_str = banned_until.strftime("%H:%M, %d.%m.%Y") if banned_until else _tr(lang, "Yoxdur", "Нет")

    text = _tr(
        lang,
        (
            "🧾 <b>Mənim cərimələrim</b>\n\n"
            f"• Pozuntu sayı: <b>{violations}</b>\n"
            f"• Son ban müddəti: <b>{last_ban_days} gün</b>\n"
            f"• Ban bitmə tarixi: <b>{banned_str}</b>\n"
        ),
        (
            "🧾 <b>Мои штрафы</b>\n\n"
            f"• Кол-во нарушений: <b>{violations}</b>\n"
            f"• Последний бан: <b>{last_ban_days} дней</b>\n"
            f"• Бан до: <b>{banned_str}</b>\n"
        ),
    )

    await callback.message.edit_text(text, reply_markup=kb_back("user:main", lang))
    await callback.answer()


@router.callback_query(F.data == "user:feedback")
async def user_feedback_start(callback: CallbackQuery, db: Database, state: FSMContext):
    lang = await db.get_language(callback.from_user.id)
    await state.set_state(ComplaintState.text)

    text = _tr(
        lang,
        "✍️ Rəy/şikayətinizi yazın və göndərin (1 mesaj).\n\nLəğv etmək üçün <b>Geri</b> düyməsini basın.",
        "✍️ Напишите ваш отзыв/жалобу (1 сообщение).\n\nЧтобы отменить — нажмите <b>Назад</b>.",
    )
    await callback.message.edit_text(text, reply_markup=kb_back("user:main", lang))
    await callback.answer()


@router.message(ComplaintState.text)
async def user_feedback_receive(message: Message, db: Database, state: FSMContext):
    user_id = message.from_user.id
    lang = await db.get_language(user_id)
    text_in = (message.text or "").strip()

    if len(text_in) < 5:
        await message.answer(_tr(lang, "❗ Çox qısadır. Bir az detallı yazın.", "❗ Слишком коротко. Напишите подробнее."))
        return

    cid = await db.add_complaint(user_id, text_in)

    admins = _get_admin_ids()
    uname = f"@{message.from_user.username}" if message.from_user.username else "-"
    disp = message.from_user.full_name or "-"

    notify = _tr(
        lang,
        (
            f"📨 <b>Yeni şikayət</b> #{cid}\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"👤 Username: {uname}\n"
            f"👤 Ad: {disp}\n\n"
            f"💬 Mətn:\n{text_in}"
        ),
        (
            f"📨 <b>Новая жалоба</b> #{cid}\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"👤 Username: {uname}\n"
            f"👤 Имя: {disp}\n\n"
            f"💬 Текст:\n{text_in}"
        ),
    )

    for admin_id in admins:
        try:
            await message.bot.send_message(admin_id, notify)
        except Exception:
            pass

    await state.clear()
    await message.answer(
        _tr(lang, f"✅ Göndərildi. Şikayət ID: {cid}.", f"✅ Отправлено. ID жалобы: {cid}."),
        reply_markup=kb_user_main(lang),
    )


@router.callback_query(F.data == "user:rules")
async def user_rules(callback: CallbackQuery, db: Database):
    lang = await db.get_language(callback.from_user.id)
    rules = await db.get_rules()
    await callback.message.edit_text(rules.get(lang, "-"), reply_markup=kb_back("user:main", lang))
    await callback.answer()


@router.callback_query(F.data == "user:video")
async def user_video(callback: CallbackQuery, db: Database):
    lang = await db.get_language(callback.from_user.id)

    kb = InlineKeyboardBuilder()
    kb.button(text=_tr(lang, "🎬 Video dərs", "🎬 Видео урок"), url=Config.VIDEO_TUTORIAL_URL)
    kb.button(text=_tr(lang, "Geri", "Назад"), callback_data="user:main")
    kb.adjust(1)

    await callback.message.edit_text("🎬", reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data == "user:get_account")
async def user_get_account(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    lang = await db.get_language(user_id)

    allowed, reason = await db.is_user_allowed(user_id)
    if not allowed:
        if reason == "banned":
            user = await db.get_user(user_id)
            end = user.get("banned_until") if user else None
            end_str = end.strftime("%H:%M, %d %B") if end else "-"
            text = _tr(
                lang,
                f"‼️ Siz ZIK Analytics-ə giriş hüququndan məhrumsunuz. Giriş {end_str} tarixində bərpa olunacaq.",
                f"‼️ Вы лишены доступа к ZIK Analytics. Доступ восстановится в {end_str}.",
            )
        else:
            text = _tr(
                lang,
                "⚠️ Abunəliyiniz deaktivdir. Zəhmət olmasa adminlə əlaqə saxlayın.",
                "⚠️ Ваша подписка деактивирована. Пожалуйста, свяжитесь с Админом.",
            )
        await callback.message.edit_text(text, reply_markup=kb_back("user:main", lang))
        await callback.answer()
        return

    existing = await db.get_user_active_session(user_id)
    if existing:
        st = existing.get("state")
        account_name = existing.get("account_name")
        token = str(existing.get("token"))
        session_id = int(existing.get("session_id"))

        if st == "reserved":
            deadline = existing.get("confirm_deadline_at")
            minutes_left = 0
            if deadline:
                minutes_left = max(0, int((deadline - now_baku()).total_seconds() // 60))
            text = _tr(
                lang,
                f"❗ Siz artıq bir hesab rezerv etmisiniz ({account_name}). Qalan vaxt: {minutes_left} dəq.",
                f"❗ Вы уже получили аккаунт ({account_name}) и он ожидает подтверждения. Осталось: {minutes_left} мин.",
            )
            await callback.message.edit_text(text, reply_markup=kb_account_offer(session_id, lang))
            await callback.answer()
            return

        if st == "active":
            end_at = existing.get("session_end_at")
            remaining = int((end_at - now_baku()).total_seconds()) if end_at else 0
            show_extend = remaining <= 30 * 60

            login_url = _append_token(Config.ZIK_LOGIN_URL, token)
            text = _tr(
                lang,
                f"✅ Aktiv hesab: {account_name}\nQalan vaxt: {max(0, remaining // 60)} dəq.",
                f"✅ Активный аккаунт: {account_name}\nОсталось: {max(0, remaining // 60)} мин.",
            )
            await callback.message.edit_text(
                text,
                reply_markup=kb_account_active(login_url, session_id, lang, show_extend=show_extend),
            )
            await callback.answer()
            return

    s = await db.reserve_free_account(user_id, from_queue=False, confirm_minutes=Config.CONFIRM_MINUTES_DIRECT)
    if not s:
        text1 = _tr(lang, "⚠️ Hazırda bütün ZIK hesabları məşğuldur", "⚠️ На данный момент все ZIK аккаунты заняты")
        text2 = _tr(
            lang,
            "❗ Növbəyə qoşula bilərsiniz və hesab sərbəst olan kimi bot sizə yazacaq.",
            "❗ Вы можете занять очередь и бот напишет, как только появится свободный аккаунт.",
        )
        await callback.message.edit_text(text1, reply_markup=None)
        await callback.message.answer(text2, reply_markup=kb_queue_offer(lang))
        await callback.answer()
        return

    account_name = s["account_name"]
    session_id = int(s["session_id"])
    timeout = Config.CONFIRM_MINUTES_DIRECT

    await db.remove_from_queue(user_id)

    text1 = _tr(lang, f"✅ Sərbəst ZIK hesabı tapıldı ({account_name})", f"✅ Найден свободный ZIK аккаунт ({account_name})")
    text2 = _tr(
        lang,
        f"❗ ZIK-ə daxil olmaq üçün mütləq 'ZIK-ə daxil ol' düyməsini {timeout} dəqiqə ərzində basın. Əks halda hesab sərbəst buraxılacaq.",
        f"❗ Для входа обязательно нажмите 'Войти в ZIK' в течении {timeout} минут. Иначе аккаунт освободится.",
    )

    await callback.message.edit_text(text1, reply_markup=None)
    await callback.message.answer(text2, reply_markup=kb_account_offer(session_id, lang))
    await callback.answer()


@router.callback_query(F.data == "user:queue:join")
async def user_join_queue(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    lang = await db.get_language(user_id)

    allowed, _ = await db.is_user_allowed(user_id)
    if not allowed:
        await callback.answer(_tr(lang, "Abunəlik aktiv deyil", "Подписка не активна"), show_alert=True)
        return

    existing = await db.get_user_active_session(user_id)
    if existing:
        await callback.answer(_tr(lang, "Siz artıq hesab almısınız.", "У вас уже есть аккаунт."), show_alert=True)
        return

    pos = await db.add_to_queue(user_id)
    text = _tr(
        lang,
        f"✅ Siz növbəyə qoşuldunuz. Sıra: {pos}. Hesab sərbəst olan kimi bot yazacaq (10 dəqiqə təsdiq vaxtı).",
        f"✅ Вы заняли место в очереди. Ваш номер: {pos}. Как появится аккаунт, бот напишет (10 минут на подтверждение).",
    )
    await callback.message.edit_text(text, reply_markup=kb_back("user:main", lang))
    await callback.answer()


@router.callback_query(F.data.startswith("user:cancel_offer:"))
async def user_cancel_offer(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    lang = await db.get_language(user_id)
    session_id = int(callback.data.split(":")[-1])

    ok = await db.cancel_offer(user_id, session_id)
    await db.remove_from_queue(user_id)

    if ok:
        text1 = _tr(
            lang,
            "❗ Siz ZIK hesabından imtina etdiniz, ona görə də hesab sərbəst buraxıldı.",
            "❗ Так как вы отказались от ZIK аккаунта, он был освобожден.",
        )
        text2 = _tr(
            lang,
            "❗ Yenidən daxil olmaq üçün 'ZIK hesabı al' düyməsini basın.",
            "❗ Если хотите войти в ZIK, нажмите снова 'Взять ZIK аккаунт'.",
        )
        await callback.message.edit_text(text1, reply_markup=None)
        await callback.message.answer(text2, reply_markup=kb_user_main(lang))
    else:
        await callback.message.edit_text(_tr(lang, "❌ Ləğv edilə bilmədi", "❌ Не удалось отменить"), reply_markup=kb_user_main(lang))
    await callback.answer()


@router.callback_query(F.data.startswith("user:enter:"))
async def user_enter(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    lang = await db.get_language(user_id)
    session_id = int(callback.data.split(":")[-1])

    s = await db.confirm_session(user_id, session_id)
    if not s:
        await callback.message.edit_text(_tr(lang, "❌ Bu hesab artıq əlçatan deyil", "❌ Этот аккаунт больше не доступен"), reply_markup=kb_user_main(lang))
        await callback.answer()
        return

    account_name = s.get("account_name")
    token = str(s.get("token"))
    login_url = _append_token(Config.ZIK_LOGIN_URL, token)

    text1 = _tr(lang, f"✅ Siz '{account_name}' hesabını aldınız", f"✅ Вы успешно взяли аккаунт '{account_name}'")
    text2 = _tr(
        lang,
        "❗ ZIK-ə daxil olmaq üçün düyməni basın. Avtomatik doldurma işləməsə, 'Gmail və Parolu kopyalayın' düyməsini basın.",
        "❗ Для входа нажмите кнопку. Если автозаполнение не работает, нажмите 'Скопировать Gmail и Пароль'.",
    )

    await callback.message.edit_text(text1, reply_markup=None)
    await callback.message.answer(text2, reply_markup=kb_account_active(login_url, session_id, lang, show_extend=False))
    await callback.answer()


@router.callback_query(F.data.startswith("user:copy:"))
async def user_copy(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    lang = await db.get_language(user_id)
    session_id = int(callback.data.split(":")[-1])

    s = await db.get_user_active_session(user_id)
    if not s or int(s.get("session_id")) != session_id:
        await callback.answer(_tr(lang, "Sessiya tapılmadı", "Сессия не найдена"), show_alert=True)
        return
    if s.get("state") != "active":
        await callback.answer(_tr(lang, "Əvvəlcə 'ZIK-ə daxil ol' basın", "Сначала нажмите 'Войти в ZIK'"), show_alert=True)
        return

    first_time = await db.mark_copy_sent(user_id, session_id)
    if not first_time:
        await callback.answer()
        return

    acc = await db.get_account(int(s["account_id"]))
    if not acc:
        await callback.answer(_tr(lang, "Hesab tapılmadı", "Аккаунт не найден"), show_alert=True)
        return

    email = acc["email"]
    password = acc["password"]

    header = _tr(lang, "❗ ZIK hesabının Gmail və Parolu:", "❗ Gmail и Пароль от ZIK аккаунта:")

    m0 = await callback.message.answer(header)
    m1 = await callback.message.answer(f"Gmail: <code>{email}</code>")
    m2 = await callback.message.answer(f"Пароль: <code>{password}</code>" if lang == "ru" else f"Parol: <code>{password}</code>")

    await db.save_creds_msg_ids(session_id, [m0.message_id, m1.message_id, m2.message_id])
    await callback.answer()


@router.callback_query(F.data.startswith("user:release:"))
async def user_release(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    lang = await db.get_language(user_id)
    session_id = int(callback.data.split(":")[-1])

    res = await db.release_session(user_id, session_id, require_tab_closed=True)
    if not res.get("ok") and res.get("reason") == "tab_open":
        await callback.answer(
            _tr(
                lang,
                "❗ Hesabı sərbəst buraxmaq üçün əvvəlcə ZIK Analytics tabını bağlayın, sonra yenidən cəhd edin.",
                "❗ Чтобы освободить аккаунт, сначала закройте вкладку ZIK Analytics и попробуйте ещё раз.",
            ),
            show_alert=True,
        )
        return

    if not res.get("ok"):
        await callback.answer(_tr(lang, "❌ Alınmadı", "❌ Не удалось"), show_alert=True)
        return

    creds_msg_ids = await db.pop_creds_msg_ids(session_id)
    await _safe_delete_messages(callback.bot, user_id, creds_msg_ids)

    timer_msg_ids = await db.pop_timer_msg_ids(session_id)
    await _safe_delete_messages(callback.bot, user_id, timer_msg_ids)

    await callback.message.edit_text(
        _tr(lang, "✅ Hesab sərbəst buraxıldı.", "✅ Аккаунт был освобожден."),
        reply_markup=kb_user_main(lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("user:extend:"))
async def user_extend(callback: CallbackQuery, db: Database):
    lang = await db.get_language(callback.from_user.id)
    session_id = int(callback.data.split(":")[-1])
    await callback.message.answer(_tr(lang, "Uzatma seçimləri:", "Варианты продления:"), reply_markup=kb_extend_options(session_id, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("user:extend_apply:"))
async def user_extend_apply(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    lang = await db.get_language(user_id)
    parts = callback.data.split(":")
    session_id = int(parts[2])
    minutes = int(parts[3])

    r = await db.extend_session(user_id, session_id, minutes)
    if not r:
        await callback.answer(_tr(lang, "❌ Uzatma mümkün deyil", "❌ Продление недоступно"), show_alert=True)
        return

    timer_msg_ids = await db.pop_timer_msg_ids(session_id)
    await _safe_delete_messages(callback.bot, user_id, timer_msg_ids)

    new_end = r["new_end"]
    remaining_min = max(0, int((new_end - now_baku()).total_seconds() // 60))

    await callback.message.answer(
        _tr(lang, f"✅ Müddət {minutes} dəqiqə uzadıldı.", f"✅ Время использования продлено на {minutes} мин.")
    )
    await callback.message.answer(
        _tr(lang, f"✅ Ümumi qalan vaxt: {remaining_min} dəq.", f"✅ Общее оставшееся время: {remaining_min} мин.")
    )
    await callback.answer()

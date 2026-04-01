from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder

from locales import get_text


def kb_language():
    kb = InlineKeyboardBuilder()
    kb.button(text="Azərbaycan dili 🇦🇿", callback_data="lang:az")
    kb.button(text="Русский язык 🇷🇺", callback_data="lang:ru")
    kb.adjust(1)
    return kb.as_markup()


def kb_choose_role(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(
        text="Админ как войти" if lang == "ru" else "Admin kimi daxil ol",
        callback_data="role:admin",
    )
    kb.button(
        text="Пользователь как войти" if lang == "ru" else "İstifadəçi kimi daxil ol",
        callback_data="role:user",
    )
    kb.adjust(2)
    return kb.as_markup()


def kb_back(callback_data: str, lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=get_text("back", lang), callback_data=callback_data)
    kb.adjust(1)
    return kb.as_markup()


def kb_cancel(back_cb: str, lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=get_text("cancel", lang), callback_data=back_cb)
    kb.adjust(1)
    return kb.as_markup()


def kb_admin_main(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=get_text("users", lang), callback_data="admin:users")
    kb.button(text=get_text("zik_accounts", lang), callback_data="admin:accounts")
    kb.button(text=get_text("manage_accounts", lang), callback_data="admin:manage_accounts")
    kb.button(text=get_text("announcement", lang), callback_data="admin:announcement")
    kb.button(text=get_text("complaints", lang), callback_data="admin:complaints")
    kb.button(text=get_text("rules", lang), callback_data="admin:rules")
    kb.button(text=get_text("exit_to_main", lang), callback_data="admin:exit")
    kb.adjust(2, 1, 2, 1, 1)
    return kb.as_markup()


def kb_user_main(lang: str):
    kb = InlineKeyboardBuilder()

    kb.button(text=get_text("rules", lang), callback_data="user:rules")
    kb.button(text=get_text("video_tutorial", lang), callback_data="user:video")
    kb.button(text=get_text("get_zik_account", lang), callback_data="user:get_account")
    kb.button(text=get_text("my_fines", lang), callback_data="user:fines")
    kb.button(text=get_text("feedback", lang), callback_data="user:feedback")
    kb.button(text=get_text("back", lang), callback_data="user:back")

    kb.adjust(1, 1, 1, 1, 1, 1)
    return kb.as_markup()


def kb_account_offer(session_id: int, lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=get_text("enter_zik", lang), callback_data=f"user:enter:{session_id}")
    kb.button(text=get_text("cancel", lang), callback_data=f"user:cancel_offer:{session_id}")
    kb.button(text=get_text("copy_credentials", lang), callback_data=f"user:copy:{session_id}")
    kb.adjust(2, 1)
    return kb.as_markup()


def kb_account_active(login_url: str, session_id: int, lang: str, show_extend: bool = False):
    kb = InlineKeyboardBuilder()
    kb.button(text=get_text("enter_zik", lang), url=login_url)
    kb.button(text=get_text("release_account", lang), callback_data=f"user:release:{session_id}")
    kb.button(text=get_text("copy_credentials", lang), callback_data=f"user:copy:{session_id}")

    if show_extend:
        kb.button(text=get_text("extend_time", lang), callback_data=f"user:extend:{session_id}")
        kb.adjust(2, 1, 1)
    else:
        kb.adjust(2, 1)

    return kb.as_markup()


def kb_queue_offer(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=get_text("join_queue", lang), callback_data="user:queue:join")
    kb.button(text=get_text("cancel", lang), callback_data="user:main")
    kb.adjust(2)
    return kb.as_markup()


def kb_extend_options(session_id: int, lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=get_text("extend_30min", lang), callback_data=f"user:extend_apply:{session_id}:30")
    kb.button(text=get_text("extend_1hour", lang), callback_data=f"user:extend_apply:{session_id}:60")
    kb.adjust(2)
    return kb.as_markup()

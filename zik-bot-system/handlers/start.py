from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from config import Config
from database import Database
from keyboards import kb_choose_role, kb_language, kb_user_main, kb_admin_main
from locales import get_text


router = Router(name="start")


def _is_admin(user_id: int) -> bool:
    return user_id in Config.ADMIN_IDS


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, db: Database):
    user_id = message.from_user.id
    await db.upsert_user(user_id, message.from_user.username)

    # Default language when user didn't choose yet: AZ
    lang = await db.get_language(user_id)
    if lang not in ("az", "ru"):
        lang = "az"

    text = get_text("welcome_admin", lang) if _is_admin(user_id) else get_text("welcome_user", lang)
    await message.answer(text, reply_markup=kb_language())


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    lang = callback.data.split(":", 1)[1]
    if lang not in ("az", "ru"):
        lang = "az"
    await db.set_language(user_id, lang)

    if _is_admin(user_id):
        await callback.message.edit_text(get_text("select_language", lang), reply_markup=kb_choose_role(lang))
    else:
        await callback.message.edit_text(get_text("user_menu", lang), reply_markup=kb_user_main(lang))

    await callback.answer()


@router.callback_query(F.data == "role:admin")
async def cb_role_admin(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    lang = await db.get_language(user_id)
    if not _is_admin(user_id):
        await callback.answer("Not allowed", show_alert=True)
        return
    await callback.message.edit_text(get_text("admin_menu", lang), reply_markup=kb_admin_main(lang))
    await callback.answer()


@router.callback_query(F.data == "role:user")
async def cb_role_user(callback: CallbackQuery, db: Database):
    lang = await db.get_language(callback.from_user.id)
    await callback.message.edit_text(get_text("user_menu", lang), reply_markup=kb_user_main(lang))
    await callback.answer()


@router.callback_query(F.data == "admin:exit")
async def cb_admin_exit(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    lang = await db.get_language(user_id)
    if _is_admin(user_id):
        await callback.message.edit_text(get_text("select_language", lang), reply_markup=kb_choose_role(lang))
    else:
        await callback.message.edit_text(get_text("user_menu", lang), reply_markup=kb_user_main(lang))
    await callback.answer()
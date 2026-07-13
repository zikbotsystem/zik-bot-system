import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramServerError
from aiogram.fsm.storage.memory import MemoryStorage

from config import Config
from database import Database
from handlers.start import router as start_router
from handlers.admin import router as admin_router
from handlers.user import router as user_router
from middlewares import DbMiddleware
from scheduler import run_scheduler


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    if not Config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")

    db = Database()
    await db.init()

    bot = Bot(
        token=Config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(DbMiddleware(db))
    dp.callback_query.middleware(DbMiddleware(db))

    dp.include_router(start_router)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    scheduler_task = None

    try:
        # Telegram müvəqqəti timeout/502 verərsə burada ilişib qalmasın
        try:
            await bot.delete_webhook(
                drop_pending_updates=False,
                request_timeout=20,
            )
            logger.info("Webhook silindi və ya artıq mövcud deyildi")

        except (TelegramServerError, TelegramNetworkError) as error:
            logger.warning(
                "Webhook yoxlanılması alınmadı, polling başladılır: %s",
                error,
            )

        scheduler_task = asyncio.create_task(run_scheduler(bot, db))

        logger.info("Bot started")

        while True:
            try:
                await dp.start_polling(
                    bot,
                    close_bot_session=False,
                )
                break

            except (TelegramServerError, TelegramNetworkError) as error:
                logger.warning(
                    "Telegram bağlantı xətası: %s. "
                    "10 saniyə sonra yenidən qoşulur...",
                    error,
                )
                await asyncio.sleep(10)

    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()

            with suppress(asyncio.CancelledError):
                await scheduler_task

        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

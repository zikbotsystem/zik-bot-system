import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

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

    # Inject DB into handlers
    dp.message.middleware(DbMiddleware(db))
    dp.callback_query.middleware(DbMiddleware(db))

    dp.include_router(start_router)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # Start scheduler background task
    asyncio.create_task(run_scheduler(bot, db))

    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

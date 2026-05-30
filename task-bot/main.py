import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

import database
from bot import setup_bot
from scheduler import setup_scheduler

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    database.init_db()
    logger.info("Base de datos inicializada.")

    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN no está definido en .env")

    application = setup_bot(token)
    scheduler = setup_scheduler(application)

    async with application:
        scheduler.start()
        logger.info("Scheduler activo.")

        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot iniciado. Esperando mensajes...")

        try:
            await asyncio.Event().wait()
        finally:
            scheduler.shutdown(wait=False)
            await application.updater.stop()
            await application.stop()
            logger.info("Bot detenido.")


if __name__ == "__main__":
    asyncio.run(main())

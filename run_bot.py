"""Entry point — starts the Telegram bot."""

import logging

from src.core.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    from src.bot.telegram_bot import TelegramBot

    logger.info("Starting AIManager Telegram bot")
    bot = TelegramBot()
    bot.run()

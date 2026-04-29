"""Entry point — starts the Telegram bot."""

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-30s  %(levelname)-8s  %(message)s",
)

if __name__ == "__main__":
    from src.bot.telegram_bot import TelegramBot

    bot = TelegramBot()
    bot.run()

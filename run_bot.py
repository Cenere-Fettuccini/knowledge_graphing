"""Entry point — run this file to start the Telegram bot.

Usage:
    python run_bot.py
"""

import logging
import sys

# Configure root logger before any module-level loggers fire.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
from src.bot.telegram_bot import TelegramBot  # noqa: E402 — import after logging setup


def main() -> None:
    bot = TelegramBot()
    bot.run()


if __name__ == "__main__":
    main()
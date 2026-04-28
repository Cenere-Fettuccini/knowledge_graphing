import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from src.core.agent import Agent
from src.core.config import settings

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self):
        self._agent = Agent()
        self._app = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .build()
        )
        self._register_handlers()

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("help", self._handle_help))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

    # ------------------------------------------------------------------
    # Auth helper
    # ------------------------------------------------------------------

    def _is_authorized(self, update: Update) -> bool:
        user_id = str(update.effective_user.id)
        return user_id in settings.allowed_user_ids

    async def _deny(self, update: Update) -> None:
        logger.warning(
            "Unauthorised access attempt from user_id=%s", update.effective_user.id
        )
        await update.message.reply_text("⛔ You are not authorised to use this bot.")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_authorized(update):
            await self._deny(update)
            return
        await update.message.reply_text(
            "👋 Hi! I'm AIManager — your personal AI with long-term memory.\n\n"
            "Just talk to me normally. I'll remember everything."
        )

    async def _handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_authorized(update):
            await self._deny(update)
            return
        await update.message.reply_text(
            "ℹ️ *AIManager*\n\n"
            "I'm a personal AI assistant that remembers your conversations and "
            "builds a knowledge graph of your world.\n\n"
            "Just send me a message — no special commands needed.",
            parse_mode="Markdown",
        )

    async def _handle_message(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_authorized(update):
            await self._deny(update)
            return

        user_id = str(update.effective_user.id)
        text = update.message.text

        # Show "typing…" indicator while we wait for the LLM
        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            tokens: list[str] = []
            async for token in self._agent.process_message_stream(user_id, text):
                tokens.append(token)
            await update.message.reply_text("".join(tokens))
        except Exception:
            logger.exception("Agent stream failed for user_id=%s", user_id)
            await update.message.reply_text(
                "⚠️ I'm having trouble thinking right now. Please try again in a moment."
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the bot using long-polling (blocks until interrupted)."""
        logger.info("Starting AIManager Telegram bot (polling)…")
        self._app.run_polling(drop_pending_updates=True)
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
        self._app.add_handler(CommandHandler("new", self._handle_new))
        self._app.add_handler(CommandHandler("history", self._handle_history))
        self._app.add_handler(CommandHandler("pin", self._handle_pin))
        self._app.add_handler(CommandHandler("sessions", self._handle_sessions))
        self._app.add_handler(CommandHandler("swap", self._handle_swap))
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
            "Just send me a message — no special commands needed.\n\n"
            "*Commands:*\n"
            "/new - Start a new conversation session\n"
            "/history - View recent conversation history\n"
            "/pin <name> - Pin the current active session\n"
            "/sessions - List your pinned sessions\n"
            "/swap <id> - Swap to a pinned session",
            parse_mode="Markdown",
        )

    async def _handle_new(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_authorized(update):
            await self._deny(update)
            return
        user_id = str(update.effective_user.id)
        self._agent.reset_session(user_id)
        await update.message.reply_text("🔄 Started a new conversation. Short-term context cleared.")

    async def _handle_history(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_authorized(update):
            await self._deny(update)
            return
        user_id = str(update.effective_user.id)
        history_str = await self._agent.get_history(user_id, n=15)
        
        if not history_str:
            await update.message.reply_text("📭 No recent history found.")
            return

        if len(history_str) > 4000:
            history_str = "... " + history_str[-3995:]
            
        await update.message.reply_text(
            f"📜 *Recent History:*\n\n{history_str}", 
            parse_mode="Markdown"
        )

    async def _handle_pin(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._deny(update)
            return
        if not context.args:
            await update.message.reply_text("❌ Please provide a name. Usage: `/pin <name>`", parse_mode="Markdown")
            return
        name = " ".join(context.args)
        user_id = str(update.effective_user.id)
        self._agent.pin_session(user_id, name)
        await update.message.reply_text(f"📌 Pinned current session as: *{name}*", parse_mode="Markdown")

    async def _handle_sessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._deny(update)
            return
        user_id = str(update.effective_user.id)
        pinned = self._agent.get_pinned_sessions(user_id)
        if not pinned:
            await update.message.reply_text("📭 You have no pinned sessions yet. Use `/pin <name>` to save the current one.")
            return
        
        lines = ["📌 *Your Pinned Sessions:*"]
        for p in pinned:
            lines.append(f"- `{p['session_id'][:8]}` : {p['name']}")
        lines.append("\nUse `/swap <id>` to switch to one.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _handle_swap(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._deny(update)
            return
        if not context.args:
            await update.message.reply_text("❌ Please provide a session ID. Usage: `/swap <id>`", parse_mode="Markdown")
            return
        session_id_prefix = context.args[0]
        user_id = str(update.effective_user.id)
        pinned = self._agent.get_pinned_sessions(user_id)
        
        target_session = None
        for p in pinned:
            if p["session_id"].startswith(session_id_prefix):
                target_session = p["session_id"]
                break
                
        if not target_session:
            await update.message.reply_text(f"❌ Could not find a pinned session matching `{session_id_prefix}`.", parse_mode="Markdown")
            return
            
        self._agent.swap_session(user_id, target_session)
        await update.message.reply_text(f"🔄 Swapped to session: `{target_session[:8]}`", parse_mode="Markdown")

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
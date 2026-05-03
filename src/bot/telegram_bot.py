"""src/bot/telegram_bot.py

Telegram interface for AIManager.

This module is the *only* thing that talks to Telegram. It handles:
  - Authentication (user whitelist)
  - All slash-command handlers
  - Plain-text message dispatch
  - Session management (in-memory for now, JSON file persistence)
  - Typing indicators and error recovery

The bot does NOT contain any AI logic. It delegates message processing
to an agent interface (currently a placeholder echo). When the Agent Core
is implemented in Step 4, only the `_process_message` method needs to change.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.core.config import settings
from src.core.agent import Agent
from src.memory.manager import MemoryManager
from src.bot.messages import (
    AGENT_ERROR_TEXT,
    HELP_TEXT,
    HISTORY_HEADER,
    NEW_SESSION_TEXT,
    NO_HISTORY_TEXT,
    NO_SESSIONS_TEXT,
    PIN_SUCCESS_TEXT,
    PIN_USAGE_TEXT,
    SESSIONS_FOOTER,
    SESSIONS_HEADER,
    STATUS_TEXT,
    SWAP_NOT_FOUND_TEXT,
    SWAP_SUCCESS_TEXT,
    SWAP_USAGE_TEXT,
    UNAUTHORIZED_TEXT,
    WELCOME_TEXT,
)

logger = logging.getLogger(__name__)


# ── Session Store ─────────────────────────────────────────────────────────────

class SessionStore:
    """
    Lightweight per-user session tracker with JSON file persistence.

    Each user has:
      - An active session_id (UUID4 string)
      - A turn counter for the current session
      - A list of named "pinned" sessions
      - An in-memory conversation history buffer

    This is intentionally simple — it will be replaced by the MemoryManager
    facade once ChromaDB and Neo4j are wired in.
    """

    def __init__(self, persist_path: str | None = None) -> None:
        self._persist_path = Path(persist_path) if persist_path else None
        self._users: dict[str, dict[str, Any]] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load session data from disk if the file exists."""
        if self._persist_path and self._persist_path.exists():
            try:
                raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
                self._users = raw
                logger.info("Loaded sessions for %d user(s) from %s", len(raw), self._persist_path)
            except Exception:
                logger.exception("Failed to load session file — starting fresh")

    def _save(self) -> None:
        """Persist session data to disk."""
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(
                json.dumps(self._users, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to save session file")

    # ── User bootstrap ────────────────────────────────────────────────────

    def _ensure_user(self, user_id: str) -> dict[str, Any]:
        """Return the user record, creating one with a fresh session if needed."""
        if user_id not in self._users:
            self._users[user_id] = {
                "active_session": str(uuid.uuid4()),
                "turn_index": 0,
                "pinned": [],
                "history": [],  # list of {role, text, timestamp, session_id}
            }
            self._save()
        return self._users[user_id]

    # ── Active session ────────────────────────────────────────────────────

    def get_session(self, user_id: str) -> tuple[str, int]:
        """Return (session_id, turn_index) for the user."""
        u = self._ensure_user(user_id)
        return u["active_session"], u["turn_index"]

    def advance_turn(self, user_id: str, by: int = 2) -> None:
        """Advance the turn counter (user msg + assistant reply = 2)."""
        self._ensure_user(user_id)["turn_index"] += by
        self._save()

    def reset_session(self, user_id: str) -> str:
        """Start a brand-new session. Returns the new session_id."""
        u = self._ensure_user(user_id)
        new_id = str(uuid.uuid4())
        u["active_session"] = new_id
        u["turn_index"] = 0
        self._save()
        return new_id

    # ── Pinning ───────────────────────────────────────────────────────────

    def pin_session(self, user_id: str, name: str) -> None:
        """Pin the current active session with a human-readable name."""
        u = self._ensure_user(user_id)
        # Avoid duplicate pins for the same session
        for p in u["pinned"]:
            if p["session_id"] == u["active_session"]:
                p["name"] = name  # just rename it
                self._save()
                return
        u["pinned"].append({
            "session_id": u["active_session"],
            "name": name,
            "pinned_at": datetime.now(timezone.utc).isoformat(),
        })
        self._save()

    def get_pinned(self, user_id: str) -> list[dict[str, str]]:
        """Return the list of pinned sessions."""
        return self._ensure_user(user_id)["pinned"]

    def find_pinned_by_prefix(self, user_id: str, prefix: str) -> str | None:
        """Find a pinned session_id that starts with the given prefix."""
        for p in self.get_pinned(user_id):
            if p["session_id"].startswith(prefix):
                return p["session_id"]
        return None

    def swap_session(self, user_id: str, session_id: str) -> None:
        """Switch the active session to a different session_id."""
        u = self._ensure_user(user_id)
        u["active_session"] = session_id
        u["turn_index"] = 0
        self._save()

    # ── History buffer ────────────────────────────────────────────────────

    def add_to_history(
        self,
        user_id: str,
        role: str,
        text: str,
        session_id: str,
    ) -> None:
        """Append a turn to the in-memory history buffer."""
        u = self._ensure_user(user_id)
        u["history"].append({
            "role": role,
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
        })
        # Cap at 200 entries to prevent unbounded growth
        if len(u["history"]) > 200:
            u["history"] = u["history"][-200:]
        self._save()

    def get_history(self, user_id: str, n: int = 15) -> list[dict[str, str]]:
        """Return the last *n* history entries for the current session."""
        u = self._ensure_user(user_id)
        active = u["active_session"]
        session_turns = [h for h in u["history"] if h["session_id"] == active]
        return session_turns[-n:]


# ── Telegram Bot ──────────────────────────────────────────────────────────────

class TelegramBot:
    """
    Telegram bot interface for AIManager.

    Handles all user interaction — commands, text messages, auth.
    Delegates AI processing to an agent (currently placeholder echo).
    """

    def __init__(self) -> None:
        self._sessions = SessionStore(persist_path=settings.session_store_path)
        self._memory = MemoryManager()
        self._agent = Agent(memory=self._memory)
        self._app = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .build()
        )
        self._register_handlers()
        logger.info("TelegramBot initialised (auth whitelist: %s)", settings.allowed_user_ids)

    # ── Handler Registration ──────────────────────────────────────────────

    def _register_handlers(self) -> None:
        """Register all command and message handlers."""
        commands = [
            ("start",    self._handle_start),
            ("help",     self._handle_help),
            ("new",      self._handle_new),
            ("history",  self._handle_history),
            ("pin",      self._handle_pin),
            ("sessions", self._handle_sessions),
            ("swap",     self._handle_swap),
            ("status",   self._handle_status),
        ]
        for name, callback in commands:
            self._app.add_handler(CommandHandler(name, callback))

        # Plain text messages — catch-all (must be registered last)
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

    # ── Auth ──────────────────────────────────────────────────────────────

    def _is_authorized(self, update: Update) -> bool:
        """Check if the sender is in the allowed user ID whitelist."""
        user_id = str(update.effective_user.id)
        return user_id in settings.allowed_user_ids

    async def _deny(self, update: Update) -> None:
        """Send an unauthorized message and log the attempt."""
        logger.warning(
            "Unauthorized access attempt — user_id=%s, username=%s",
            update.effective_user.id,
            update.effective_user.username,
        )
        await update.message.reply_text(UNAUTHORIZED_TEXT)

    # ── Command Handlers ──────────────────────────────────────────────────

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Send the welcome message."""
        if not self._is_authorized(update):
            return await self._deny(update)
        await update.message.reply_text(WELCOME_TEXT, parse_mode=ParseMode.MARKDOWN)

    async def _handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Send the command reference."""
        if not self._is_authorized(update):
            return await self._deny(update)
        await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)

    async def _handle_new(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Start a fresh conversation session."""
        if not self._is_authorized(update):
            return await self._deny(update)
        user_id = str(update.effective_user.id)
        new_id = self._sessions.reset_session(user_id)
        logger.info("New session for user_id=%s → %s", user_id, new_id[:8])
        await update.message.reply_text(NEW_SESSION_TEXT)

    async def _handle_history(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Display recent conversation history for the active session."""
        if not self._is_authorized(update):
            return await self._deny(update)

        user_id = str(update.effective_user.id)
        turns = self._sessions.get_history(user_id, n=15)

        if not turns:
            await update.message.reply_text(NO_HISTORY_TEXT)
            return

        lines = []
        for t in turns:
            prefix = "You" if t["role"] == "user" else "🤖"
            lines.append(f"{prefix}: {t['text']}")
        history_str = "\n".join(lines)

        # Telegram has a 4096-char limit per message
        if len(history_str) > 3900:
            history_str = "…" + history_str[-3895:]

        await update.message.reply_text(
            HISTORY_HEADER + history_str, parse_mode=ParseMode.MARKDOWN
        )

    async def _handle_pin(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Pin the current active session with a user-provided name."""
        if not self._is_authorized(update):
            return await self._deny(update)
        if not context.args:
            await update.message.reply_text(PIN_USAGE_TEXT, parse_mode=ParseMode.MARKDOWN)
            return

        name = " ".join(context.args)
        user_id = str(update.effective_user.id)
        self._sessions.pin_session(user_id, name)
        logger.info("Pinned session for user_id=%s as '%s'", user_id, name)
        await update.message.reply_text(
            PIN_SUCCESS_TEXT.format(name=name), parse_mode=ParseMode.MARKDOWN
        )

    async def _handle_sessions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """List all pinned sessions for the user."""
        if not self._is_authorized(update):
            return await self._deny(update)

        user_id = str(update.effective_user.id)
        pinned = self._sessions.get_pinned(user_id)

        if not pinned:
            await update.message.reply_text(NO_SESSIONS_TEXT, parse_mode=ParseMode.MARKDOWN)
            return

        lines = [SESSIONS_HEADER]
        for p in pinned:
            short_id = p["session_id"][:8]
            lines.append(f"  `{short_id}` — {p['name']}")
        lines.append(SESSIONS_FOOTER)
        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN
        )

    async def _handle_swap(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Swap the active session to a previously pinned one."""
        if not self._is_authorized(update):
            return await self._deny(update)
        if not context.args:
            await update.message.reply_text(SWAP_USAGE_TEXT, parse_mode=ParseMode.MARKDOWN)
            return

        prefix = context.args[0]
        user_id = str(update.effective_user.id)
        target = self._sessions.find_pinned_by_prefix(user_id, prefix)

        if not target:
            await update.message.reply_text(
                SWAP_NOT_FOUND_TEXT.format(prefix=prefix),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        self._sessions.swap_session(user_id, target)
        logger.info("Swapped user_id=%s to session %s", user_id, target[:8])
        await update.message.reply_text(
            SWAP_SUCCESS_TEXT.format(session_id=target[:8]),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _handle_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Show current system status."""
        if not self._is_authorized(update):
            return await self._deny(update)

        user_id = str(update.effective_user.id)
        session_id, turn_count = self._sessions.get_session(user_id)

        health = self._agent.status()
        await update.message.reply_text(
            STATUS_TEXT.format(
                agent_status=health["llm"],
                memory_status=health["memory"]["chroma"],
                graph_status=health["memory"]["neo4j"],
                session_id=session_id[:8],
                turn_count=turn_count,
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Message Handler ───────────────────────────────────────────────────

    async def _handle_message(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle a plain-text message from the user.

        Currently echoes back with a placeholder response.
        When the Agent Core is implemented (Step 4), this method will
        delegate to agent.process_message_stream() instead.
        """
        if not self._is_authorized(update):
            return await self._deny(update)

        user_id = str(update.effective_user.id)
        text = update.message.text
        session_id, _ = self._sessions.get_session(user_id)

        # Show "typing…" indicator while processing
        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            # Agent handles: retrieve context → generate → store to ChromaDB
            reply = self._agent.process_message(user_id, text, session_id)

            # Also keep the lightweight session history buffer in sync
            self._sessions.add_to_history(user_id, "user", text, session_id)
            self._sessions.add_to_history(user_id, "assistant", reply, session_id)
            self._sessions.advance_turn(user_id)

            await update.message.reply_text(reply)

        except Exception:
            logger.exception("Message handling failed for user_id=%s", user_id)
            await update.message.reply_text(AGENT_ERROR_TEXT)


    # ── Lifecycle ─────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the bot using long-polling. Blocks until interrupted."""
        logger.info("Starting AIManager Telegram bot (polling)…")
        self._app.run_polling(drop_pending_updates=True)

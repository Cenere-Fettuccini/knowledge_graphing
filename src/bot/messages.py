"""Bot-facing text constants — every string the user sees lives here.

Centralising these makes it easy to update copy, add i18n later, or
generate help text dynamically from the command registry.
"""

# ── /start ────────────────────────────────────────────────────────────────────

WELCOME_TEXT = (
    "👋 *Hey! I'm AIManager* — your personal AI with long-term memory.\n\n"
    "Just talk to me normally. I'll remember everything.\n\n"
    "Type /help to see what I can do."
)

# ── /help ─────────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "ℹ️ *AIManager — Command Reference*\n\n"
    "🗣️ *Conversation*\n"
    "Just send a message — no special syntax needed.\n\n"
    "📋 *Commands*\n"
    "/start  — Show welcome message\n"
    "/help   — This reference\n"
    "/new    — Start a fresh conversation session\n"
    "/history — View recent conversation history\n"
    "/pin `<name>` — Pin the current session with a label\n"
    "/sessions — List your pinned sessions\n"
    "/swap `<id>` — Switch to a pinned session\n"
    "/status — Show system status\n\n"
    "🧠 *How I work*\n"
    "Everything you tell me is stored in episodic memory. "
    "Over time I'll organise it into a knowledge graph, "
    "track your tasks, and surface insights you might have missed."
)

# ── /new ──────────────────────────────────────────────────────────────────────

NEW_SESSION_TEXT = "🔄 Started a new conversation session. Short-term context cleared."

# ── /history ──────────────────────────────────────────────────────────────────

NO_HISTORY_TEXT = "📭 No conversation history yet. Start chatting!"
HISTORY_HEADER = "📜 *Recent History*\n\n"

# ── /pin ──────────────────────────────────────────────────────────────────────

PIN_USAGE_TEXT = "❌ Please provide a name.\nUsage: `/pin <name>`"
PIN_SUCCESS_TEXT = "📌 Pinned current session as: *{name}*"

# ── /sessions ─────────────────────────────────────────────────────────────────

NO_SESSIONS_TEXT = (
    "📭 No pinned sessions yet.\n"
    "Use `/pin <name>` to save the current conversation."
)
SESSIONS_HEADER = "📌 *Your Pinned Sessions:*\n"
SESSIONS_FOOTER = "\nUse `/swap <id>` to switch to one."

# ── /swap ─────────────────────────────────────────────────────────────────────

SWAP_USAGE_TEXT = "❌ Please provide a session ID.\nUsage: `/swap <id>`"
SWAP_NOT_FOUND_TEXT = "❌ No pinned session matches `{prefix}`."
SWAP_SUCCESS_TEXT = "🔄 Swapped to session `{session_id}`."

# ── /status ───────────────────────────────────────────────────────────────────

STATUS_TEXT = (
    "⚙️ *System Status*\n\n"
    "🤖 Bot: online\n"
    "🧠 Agent: `{agent_status}`\n"
    "💾 Memory: `{memory_status}`\n"
    "📊 Graph: `{graph_status}`\n"
    "🔄 Session: `{session_id}`\n"
    "📝 Turns: `{turn_count}`"
)

# ── Auth ──────────────────────────────────────────────────────────────────────

UNAUTHORIZED_TEXT = "⛔ You are not authorised to use this bot."

# ── Errors ────────────────────────────────────────────────────────────────────

AGENT_ERROR_TEXT = (
    "⚠️ I'm having trouble thinking right now. Please try again in a moment."
)

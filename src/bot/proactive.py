"""Proactive bot jobs: daily digest, soft-archive prompts, refinement (S3.3 / S4.2 / S4.4).

Runs inside the Telegram bot process (``run_bot.py``) because that's where
the Application + chat_id live. APScheduler drives the cron; each job
assembles content from the MemoryManager, sends it via the bot's
``send_message`` API, and registers callbacks for inline-button replies.

Action mapping for inline buttons (S4.2):
  approve:<pending_belief_id>   -> memory.approve_pending_belief
  reject:<pending_belief_id>    -> memory.reject_pending_belief
  edit:<pending_belief_id>      -> opens edit conversation (S4.4)
  archive:<entity_id>:<era_id?> -> bind to closing era (S3.3)
  keep:<entity_id>              -> dismiss soft-archive prompt
  reconcile:<a_id>:<b_id>       -> opens refinement conversation (S4.4)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.config import settings
from src.memory.manager import MemoryManager, get_memory_manager

logger = logging.getLogger(__name__)


def _owner_chat_id() -> int | None:
    """Single-user app: the first allowed user is also the proactive target."""
    ids = settings.allowed_user_ids
    if not ids:
        return None
    try:
        return int(next(iter(ids)))
    except (ValueError, StopIteration):
        return None


class ProactiveBot:
    """Schedules and dispatches outbound bot messages."""

    def __init__(self, application: Application, memory: MemoryManager | None = None) -> None:
        self._app = application
        self._memory = memory or get_memory_manager()
        self._scheduler = AsyncIOScheduler()
        # Active multi-turn refinement conversations, keyed by chat_id.
        self._refinements: dict[int, dict[str, Any]] = {}

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if not settings.proactive_bot_enabled:
            logger.info("ProactiveBot disabled via settings.proactive_bot_enabled")
            return
        if _owner_chat_id() is None:
            logger.warning("ProactiveBot: no allowed_user_ids configured; skipping")
            return

        # Daily digest — weekdays at the configured local time.
        self._scheduler.add_job(
            self._run_daily_digest,
            CronTrigger(
                day_of_week="mon-fri",
                hour=settings.digest_hour_local,
                minute=settings.digest_minute_local,
            ),
            id="daily_digest",
            replace_existing=True,
        )

        # Soft-archive sweep — once a week.
        self._scheduler.add_job(
            self._run_soft_archive_sweep,
            CronTrigger(
                day_of_week=settings.soft_archive_check_weekday,
                hour=10, minute=0,
            ),
            id="soft_archive",
            replace_existing=True,
        )

        # Nightly cleanup at 23:00 — expired rejections, quarantine purge candidates.
        self._scheduler.add_job(
            self._run_nightly_cleanup,
            CronTrigger(hour=23, minute=0),
            id="nightly_cleanup",
            replace_existing=True,
        )

        # Callback router for all inline-button presses.
        self._app.add_handler(CallbackQueryHandler(self._on_callback))
        self._scheduler.start()
        logger.info("ProactiveBot started: digest %02d:%02d weekdays, soft-archive %s 10:00",
                    settings.digest_hour_local, settings.digest_minute_local,
                    settings.soft_archive_check_weekday)

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    # ── S4.2 — Daily digest ────────────────────────────────────────────────

    async def _run_daily_digest(self) -> None:
        chat_id = _owner_chat_id()
        if chat_id is None:
            return
        items = self._collect_digest_items(limit=settings.digest_max_items)
        if not items:
            logger.info("daily_digest: no items today; skipping send (per spec)")
            return
        await self._send_digest(chat_id, items)

    def _collect_digest_items(self, *, limit: int) -> list[dict]:
        """Pending beliefs first (most actionable), then contradictions."""
        out: list[dict] = []
        try:
            for b in self._memory.list_pending_beliefs(limit=limit):
                out.append({"kind": "pending_belief", "data": b})
                if len(out) >= limit:
                    return out
        except Exception:
            logger.exception("digest: list_pending_beliefs failed")
        try:
            for c in self._memory.list_contradictions(limit=limit - len(out)):
                out.append({"kind": "contradiction", "data": c})
                if len(out) >= limit:
                    break
        except Exception:
            logger.exception("digest: list_contradictions failed")
        return out

    async def _send_digest(self, chat_id: int, items: list[dict]) -> None:
        lines: list[str] = [f"*Daily digest* ({len(items)} item{'s' if len(items) != 1 else ''})\n"]
        keyboard: list[list[InlineKeyboardButton]] = []

        for idx, item in enumerate(items, start=1):
            if item["kind"] == "pending_belief":
                data = item["data"]
                bid = data.get("id", "")
                content = (data.get("content") or "")[:140]
                lines.append(f"{idx}. _Pending belief_: {content}")
                keyboard.append([
                    InlineKeyboardButton("✓ Approve", callback_data=f"approve:{bid}"),
                    InlineKeyboardButton("✗ Reject", callback_data=f"reject:{bid}"),
                    InlineKeyboardButton("✎ Edit", callback_data=f"edit:{bid}"),
                ])
            elif item["kind"] == "contradiction":
                d = item["data"]
                a_id = d.get("a_id", "")
                b_id = d.get("b_id", "")
                a_content = (d.get("a_content") or "")[:80]
                b_content = (d.get("b_content") or "")[:80]
                lines.append(f"{idx}. _Contradiction_:\n   • {a_content}\n   • {b_content}")
                keyboard.append([
                    InlineKeyboardButton("⚖ Reconcile", callback_data=f"reconcile:{a_id}:{b_id}"),
                ])

        text = "\n".join(lines)
        try:
            await self._app.bot.send_message(
                chat_id=chat_id, text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            )
        except Exception:
            logger.exception("digest: failed to send")

    # ── S3.3 — Soft-archive prompts ────────────────────────────────────────

    async def _run_soft_archive_sweep(self) -> None:
        chat_id = _owner_chat_id()
        if chat_id is None:
            return
        candidate = self._find_dormant_entity()
        if not candidate:
            logger.info("soft_archive: no dormant entities")
            return
        await self._send_soft_archive_prompt(chat_id, candidate)

    def _find_dormant_entity(self) -> dict | None:
        """Return one entity not touched in N days. Cheap query — pick one
        per week, leave the rest for next week's sweep."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.soft_archive_dormant_days)).isoformat()
        # Reuse the neo4j driver directly — single ad-hoc query, no facade method warranted yet.
        if not self._memory.neo4j.driver:
            return None
        cypher = """
        MATCH (n:Person)
        WHERE NOT n:Quarantine AND NOT n.is_root = true
          AND coalesce(n.updated_at, n.created_at) < $cutoff
          AND NOT EXISTS { MATCH (n)-[:OCCURRED_IN]->(:Era) }
        RETURN n.id AS id, n.name AS name, n.updated_at AS updated_at
        ORDER BY coalesce(n.updated_at, n.created_at) ASC LIMIT 1
        """
        try:
            with self._memory.neo4j.driver.session() as session:
                rec = session.run(cypher, cutoff=cutoff).single()
                return dict(rec) if rec else None
        except Exception:
            logger.exception("soft_archive: dormant query failed")
            return None

    async def _send_soft_archive_prompt(self, chat_id: int, entity: dict) -> None:
        name = entity.get("name", "Unknown")
        eid = entity.get("id", "")
        text = (
            f"I haven't heard about *{name}* in a while.\n\n"
            f"Should I archive this to a past era, keep it active, or ignore?"
        )
        keyboard = [[
            InlineKeyboardButton("📦 Archive", callback_data=f"archive:{eid}"),
            InlineKeyboardButton("🟢 Keep active", callback_data=f"keep:{eid}"),
        ]]
        try:
            await self._app.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception:
            logger.exception("soft_archive: send failed")

    # ── Nightly cleanup (existing scheduler hook) ──────────────────────────

    async def _run_nightly_cleanup(self) -> None:
        try:
            purged = self._memory.purge_expired_rejections()
            if purged:
                logger.info("nightly_cleanup: purged %d expired rejections", purged)
        except Exception:
            logger.exception("nightly_cleanup failed")

    # ── Callback router ────────────────────────────────────────────────────

    async def _on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        data = query.data or ""
        try:
            action, _, rest = data.partition(":")
            if action == "approve":
                self._memory.approve_pending_belief(rest)
                await query.edit_message_text(f"{query.message.text}\n\n✓ Approved.")
            elif action == "reject":
                self._memory.reject_pending_belief(rest, reason="rejected via digest")
                await query.edit_message_text(f"{query.message.text}\n\n✗ Rejected (30-day TTL).")
            elif action == "edit":
                # S4.4: open a refinement conversation. Track state so the
                # next plain-text message from this chat is treated as the edit.
                self._refinements[query.message.chat_id] = {
                    "kind": "edit_belief", "belief_id": rest,
                }
                await query.edit_message_text(
                    f"{query.message.text}\n\n✎ Send me the new wording in your next message."
                )
            elif action == "keep":
                await query.edit_message_text(f"{query.message.text}\n\n🟢 Keeping active.")
            elif action == "archive":
                # Without an explicit era we just stamp "archived" on the node
                # via a synthetic "Archived" era — quick path; better UX in
                # S4.6 will let you pick an existing era.
                era = self._memory.upsert_era(name="Archived", description="Soft-archived items")
                self._memory.bind_node_to_era(rest, era["id"])
                await query.edit_message_text(f"{query.message.text}\n\n📦 Archived.")
            elif action == "reconcile":
                a_id, _, b_id = rest.partition(":")
                self._refinements[query.message.chat_id] = {
                    "kind": "reconcile", "a_id": a_id, "b_id": b_id,
                }
                await query.edit_message_text(
                    f"{query.message.text}\n\n⚖ Tell me which one still holds, or how to merge them."
                )
            else:
                logger.warning("unknown callback action: %s", action)
        except Exception:
            logger.exception("callback handler failed for data=%s", data)

    # ── S4.4 — Refinement conversation hook ────────────────────────────────

    def pop_refinement(self, chat_id: int) -> dict | None:
        """Called by the bot's text handler: if a refinement is active in this
        chat, pop and return it so the message can be routed to the matching
        action instead of the agent."""
        return self._refinements.pop(chat_id, None)

    async def handle_refinement_reply(
        self, chat_id: int, refinement: dict, user_text: str
    ) -> str:
        kind = refinement.get("kind")
        if kind == "edit_belief":
            belief_id = refinement.get("belief_id", "")
            result = self._memory.edit_pending_belief(belief_id, new_content=user_text)
            if result:
                return f"✓ Edited and approved: \"{user_text[:80]}\""
            return "Couldn't find that pending belief — it may have been actioned already."
        if kind == "reconcile":
            # CT8 (quick mode): single-shot reconciliation, but the reply
            # is parsed into a structured resolution by a Gemini Flash
            # call. The extractor produces a summary + per-belief evidence
            # items, which are landed as SUPPORTED_BY / WEAKENED_BY edges
            # from a fresh :RefinementSession node. The CONTRADICTS edge
            # is stamped resolved so the digest stops surfacing it.
            from src.agent_platform.analyzers import refinement_extraction

            a_id = refinement.get("a_id", "")
            b_id = refinement.get("b_id", "")
            belief_a = self._memory.get_belief(a_id) or {}
            belief_b = self._memory.get_belief(b_id) or {}
            a_text = belief_a.get("content") or belief_a.get("name") or ""
            b_text = belief_b.get("content") or belief_b.get("name") or ""

            parsed = await refinement_extraction.parse_reconciliation_reply(
                belief_a_text=a_text, belief_b_text=b_text, user_reply=user_text,
            )
            summary = parsed.get("summary") or user_text[:200]
            evidence = parsed.get("evidence") or []
            resolved = bool(parsed.get("resolved"))

            stats = self._memory.resolve_contradiction(
                a_id, b_id,
                summary=summary, user_reply=user_text,
                evidence=evidence, resolved=resolved,
            )
            edges = stats.get("edges_written", 0)
            marker = "✓ Reconciled" if resolved else "⚖ Noted"
            evidence_note = (
                f" ({edges} evidence edge{'s' if edges != 1 else ''})"
                if edges else ""
            )
            return f"{marker}: {summary[:160]}{evidence_note}"
        return "Unknown refinement state — ignored."

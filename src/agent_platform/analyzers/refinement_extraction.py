"""LLM-driven structural extraction for reconciliation replies (CT8).

When the operator hits "⚖ Reconcile" on a contradiction in the daily
digest and types a reply, the bot used to store the entire reply as a
free-text ``user_note`` property on the CONTRADICTS edge. That note was
unreadable to anything downstream.

This module turns that reply into structured output:

  {
    "summary": "<one-sentence resolution>",
    "evidence": [
      {"belief": "a"|"b", "kind": "supports"|"weakens", "text": "<excerpt>"},
      ...
    ],
    "resolved": <bool>,
  }

The caller writes ``SUPPORTED_BY`` / ``WEAKENED_BY`` edges from each
belief to a ``:RefinementSession`` node, then stamps the CONTRADICTS
edge with the summary and ``resolved`` flag. The conversation stays
single-shot — the full multi-turn Socratic flow is a future enhancement
(CT8 phase 2). What we get here is structure without state.
"""

from __future__ import annotations

import asyncio
import json
import logging

from src.core.config import settings

logger = logging.getLogger(__name__)

_CLOUD_MODEL = "gemini-2.5-flash"

_SYSTEM_PROMPT = """\
You interpret a user's single-shot reconciliation of two beliefs they hold that the system flagged as contradictory.

Return EXACTLY this JSON shape (no prose, no fences):
{
  "summary": "<one short sentence — how does the user reconcile A and B?>",
  "evidence": [
    {"belief": "a" | "b", "kind": "supports" | "weakens", "text": "<short excerpt from user's reply>"},
    ...
  ],
  "resolved": <true if the user clearly chose one or merged the two, false if they're still ambivalent>
}

Rules:
- ``evidence`` items break the user's reasoning into the specific claims that bolster ("supports") or undermine ("weakens") each belief.
- Empty ``evidence`` is fine if the user only gave a meta-comment ("they're not actually related").
- Always produce a ``summary`` even when no evidence is extractable.
"""


def _build_user_prompt(
    belief_a_text: str, belief_b_text: str, user_reply: str
) -> str:
    return (
        f"Belief A: {belief_a_text}\n"
        f"Belief B: {belief_b_text}\n"
        f"User's reconciliation reply:\n{user_reply}\n"
    )


def _parse_response(raw: str, fallback_text: str) -> dict:
    """Parse a Gemini JSON reply. Fallback shape if the model misbehaves."""
    default = {"summary": fallback_text[:200], "evidence": [], "resolved": False}
    if not raw or not raw.strip():
        return default
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("refinement_extraction: non-JSON response (%s): %r", e, raw[:200])
        return default
    if not isinstance(parsed, dict):
        return default

    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = fallback_text[:200]

    raw_evidence = parsed.get("evidence") or []
    evidence: list[dict] = []
    if isinstance(raw_evidence, list):
        for item in raw_evidence:
            if not isinstance(item, dict):
                continue
            belief = item.get("belief")
            kind = item.get("kind")
            text = item.get("text")
            if belief not in ("a", "b"):
                continue
            if kind not in ("supports", "weakens"):
                continue
            if not isinstance(text, str) or not text.strip():
                continue
            evidence.append({"belief": belief, "kind": kind, "text": text.strip()})

    resolved = bool(parsed.get("resolved"))
    return {"summary": summary.strip(), "evidence": evidence, "resolved": resolved}


def _call_gemini_sync(system_prompt: str, user_prompt: str) -> str:
    try:
        from google import genai
    except ImportError as e:
        logger.error("google.genai not installed; can't run refinement extraction: %s", e)
        return ""

    api_key = (settings.google_api_keys or "").split(",")[0].strip()
    if not api_key:
        logger.error("refinement_extraction: no GOOGLE_API_KEY configured")
        return ""

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=_CLOUD_MODEL,
            contents=user_prompt,
            config={
                "system_instruction": system_prompt,
                "response_mime_type": "application/json",
                "temperature": 0.1,
            },
        )
        return getattr(response, "text", "") or ""
    except Exception as e:
        logger.warning("refinement_extraction: Gemini call failed: %s", e)
        return ""


async def parse_reconciliation_reply(
    *, belief_a_text: str, belief_b_text: str, user_reply: str
) -> dict:
    """Run the extractor off the event loop.

    Always returns a usable shape. On any failure (LLM down, malformed
    output, parse error) the result is ``{summary: <truncated reply>,
    evidence: [], resolved: False}`` so the reconcile still records
    something meaningful on the CONTRADICTS edge.
    """
    if not user_reply.strip():
        return {"summary": "", "evidence": [], "resolved": False}
    user_prompt = _build_user_prompt(belief_a_text, belief_b_text, user_reply)
    raw = await asyncio.to_thread(_call_gemini_sync, _SYSTEM_PROMPT, user_prompt)
    return _parse_response(raw, fallback_text=user_reply)

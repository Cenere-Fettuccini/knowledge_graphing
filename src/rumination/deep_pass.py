"""The Night Shift / Deep Synthesis Engine."""

import asyncio
import json
import logging
import random

from google import genai
from google.genai.types import GenerateContentConfig

from src.core.config import settings
from src.memory.manager import MemoryManager, get_memory_manager

logger = logging.getLogger(__name__)

DEEP_PASS_SYSTEM_PROMPT = """You are the AIManager Deep Synthesis Engine.
Your job is to perform heavy, retroactive analysis on the user's past thoughts and beliefs.
You will be given a specific Belief the user holds, along with a batch of historical conversations related to the topic of that belief.

Your goal:
1. Identify if this belief has EVOLVED from an older, implicit belief found in the conversations.
2. Identify if this belief CONTRADICTS any past statements, revealing a cognitive shift.
3. Extract any NEW structured facts, tasks, or deeper psychological drivers that haven't been captured yet.
4. Output your analysis as a structured JSON object.

Output JSON format:
{
    "new_beliefs": [
        {"content": "...", "confidence": 0.0_to_1.0, "reason": "Why this belief was extracted"}
    ],
    "evolutions": [
        {"from_belief": "The old statement or belief", "to_current_belief": "The new belief", "reason": "Why the shift happened"}
    ],
    "reframings": [
        {"insight": "A profound insight about how the user's thinking has changed on this topic"}
    ]
}

Return ONLY the raw JSON object. Do not use markdown code blocks.
"""

RABBIT_HOLE_SYSTEM_PROMPT = """You are the AIManager Subconscious Rumination Engine.
You are having 'late night thoughts'. You are wandering through the user's memories, making bizarre, creative, or profound connections between seemingly unrelated things they have said or believed.
You will be given a 'Seed Memory' (a random thought from today or recently), and a set of 'Tangent Memories' (memories that vaguely relate to a tangent concept).

Your goal:
1. Connect these disparate thoughts. Find the hidden through-line or subconscious pattern.
2. Formulate a profound 'late night thought' or epiphany.
3. Output a structured JSON object.

Output JSON format:
{
    "epiphany": "A creative, deep, or philosophical realization connecting these memories.",
    "new_beliefs": [
        {"content": "...", "confidence": 0.8, "reason": "Why this belief emerged from the tangent"}
    ]
}

Return ONLY the raw JSON object. Do not use markdown code blocks.
"""


class DeepSynthesisEngine:
    def __init__(self, memory: MemoryManager = None):
        self.memory = memory or get_memory_manager()
        api_key = settings.api_keys[0] if settings.api_keys else ""
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-2.5-flash"

    async def _generate_json(self, system_prompt: str, user_prompt: str, *, temperature: float) -> dict:
        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=user_prompt,
            config=GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )
        raw_json = (response.text or "").strip()
        return json.loads(raw_json)

    async def run_batch(self):
        """Run a single batch of deep synthesis over un-analyzed beliefs."""
        logger.info("Starting Deep Synthesis batch...")

        beliefs = self.memory.get_unanalyzed_beliefs(limit=10)
        if not beliefs:
            logger.info("No un-analyzed beliefs found. Night Shift resting.")
            return 0

        insights_generated = 0

        for belief in beliefs:
            logger.info("Deep analyzing belief: %s...", belief["content"][:50])

            memories = self.memory.search(belief["content"], k=30)
            if not memories:
                self.memory.mark_belief_deep_analyzed(belief["id"])
                continue

            context = f"CURRENT BELIEF TO ANALYZE:\n{belief['content']} (Confidence: {belief['confidence']})\n\n"
            context += "HISTORICAL CONVERSATIONS (EVIDENCE):\n"
            for i, mem in enumerate(memories):
                date = mem["metadata"].get("timestamp", "Unknown Date")
                context += f"--- Entry {i + 1} ({date}) ---\n{mem['text']}\n\n"

            try:
                analysis = await self._generate_json(
                    DEEP_PASS_SYSTEM_PROMPT,
                    context,
                    temperature=0.2,
                )
                new_beliefs = analysis.get("new_beliefs", [])
                evolutions = analysis.get("evolutions", [])
                reframings = analysis.get("reframings", [])

                if new_beliefs or evolutions or reframings:
                    logger.info(
                        "Found %d new beliefs, %d evolutions, %d reframings.",
                        len(new_beliefs),
                        len(evolutions),
                        len(reframings),
                    )
                    insights_generated += 1

                    for nb in new_beliefs:
                        # CT2: stamp provenance so this synthesis traces
                        # back to the belief that seeded the deep pass.
                        self.memory.upsert_belief(
                            nb["content"],
                            nb.get("confidence", 0.5),
                            extraction_method="deep_pass",
                            derived_from_belief_id=belief["id"],
                        )

                    for reframing in reframings:
                        logger.info("INSIGHT: %s", reframing["insight"])

            except Exception as e:
                logger.error("Error during LLM synthesis for belief %s: %s", belief["id"], e)
            finally:
                self.memory.mark_belief_deep_analyzed(belief["id"])

            await asyncio.sleep(2)

        return insights_generated

    async def run_rabbit_hole(self):
        """Pick a random recent memory, find a tangent, and ruminate on it."""
        logger.info("Entering the Rabbit Hole (Late Night Thoughts)...")

        recent = self.memory.get_recent_memories(n=100)
        if not recent:
            logger.info("No recent memories to ruminate on.")
            return 0

        seed_memory = random.choice(recent)
        logger.info("Seed memory selected: %s...", seed_memory["text"][:80])

        tangent_prompt = (
            f"Given this memory: '{seed_memory['text']}', extract one single, abstract, tangent concept "
            "1-3 words long that this vaguely relates to psychologically or philosophically. "
            "Return only the concept."
        )
        try:
            tangent_response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=tangent_prompt,
                config=GenerateContentConfig(temperature=0.8, max_output_tokens=64),
            )
            tangent = (tangent_response.text or "").strip()
            logger.info("Tangent concept generated: %s", tangent)
        except Exception as e:
            logger.error("Failed to generate tangent: %s", e)
            return 0

        tangent_memories = self.memory.search(tangent, k=15)
        context = f"SEED MEMORY:\n{seed_memory['text']}\n\nTANGENT CONCEPT: {tangent}\n\nTANGENT MEMORIES:\n"
        for i, mem in enumerate(tangent_memories):
            context += f"--- {i + 1} ---\n{mem['text']}\n\n"

        try:
            analysis = await self._generate_json(
                RABBIT_HOLE_SYSTEM_PROMPT,
                context,
                temperature=0.8,
            )

            epiphany = analysis.get("epiphany")
            if epiphany:
                logger.info("\n%s\nEPIPHANY:\n%s\n%s\n", "=" * 50, epiphany, "=" * 50)

            for nb in analysis.get("new_beliefs", []):
                # CT2: anchor the rabbit-hole insight to the seed
                # conversation so the provenance chain ends at a real turn.
                self.memory.upsert_belief(
                    nb["content"],
                    nb.get("confidence", 0.7),
                    extraction_method="rabbit_hole",
                    source_session_id=(seed_memory.get("metadata") or {}).get("session_id"),
                    source_text=seed_memory.get("text"),
                )
                logger.info("Graph Updated with Insight: %s", nb["content"])

            return 1
        except Exception as e:
            logger.error("Error during Rabbit Hole synthesis: %s", e)
            return 0

"""The Night Shift / Deep Synthesis Engine.

Iterates over un-analyzed beliefs and conversations, feeding them to the LLM
to extract deep structural connections, evolutions in thought, and psychological patterns.
"""

import logging
import asyncio
from datetime import datetime, timezone
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage

from src.core.config import settings
from src.memory.manager import MemoryManager

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
        self.memory = memory or MemoryManager()
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.2,
            max_output_tokens=2048,
        )

    def _get_unanalyzed_beliefs(self):
        """Fetch Beliefs from Neo4j that haven't been deeply analyzed yet."""
        query = """
        MATCH (b:Belief)
        WHERE b.deep_analyzed IS NULL OR b.deep_analyzed = false
        RETURN b.id AS id, b.content AS content, b.confidence AS conf
        LIMIT 10
        """
        try:
            records, _, _ = self.memory.neo4j.driver.execute_query(query)
            return [{"id": r["id"], "content": r["content"], "confidence": r["conf"]} for r in records]
        except Exception as e:
            logger.error(f"Failed to fetch beliefs for deep pass: {e}")
            return []

    def _mark_belief_analyzed(self, belief_id: str):
        """Mark a belief as analyzed so we don't process it again."""
        query = """
        MATCH (b:Belief {id: $id})
        SET b.deep_analyzed = true, b.last_analyzed = $now
        """
        try:
            self.memory.neo4j.driver.execute_query(query, id=belief_id, now=datetime.now(timezone.utc).isoformat())
        except Exception as e:
            logger.error(f"Failed to mark belief analyzed: {e}")

    async def run_batch(self):
        """Run a single batch of deep synthesis."""
        logger.info("Starting Deep Synthesis batch...")
        
        beliefs = self._get_unanalyzed_beliefs()
        if not beliefs:
            logger.info("No un-analyzed beliefs found. Night Shift resting.")
            return 0
            
        insights_generated = 0

        for belief in beliefs:
            logger.info(f"Deep analyzing belief: {belief['content'][:50]}...")
            
            # 1. Fetch related conversations from ChromaDB using the belief content
            # We fetch a large chunk of episodic memory to find contradictions/support
            memories = self.memory.chroma.query_memory(belief["content"], k=30)
            if not memories:
                self._mark_belief_analyzed(belief["id"])
                continue

            # 2. Build the prompt
            context = f"CURRENT BELIEF TO ANALYZE:\n{belief['content']} (Confidence: {belief['confidence']})\n\n"
            context += "HISTORICAL CONVERSATIONS (EVIDENCE):\n"
            for i, mem in enumerate(memories):
                date = mem["metadata"].get("timestamp", "Unknown Date")
                context += f"--- Entry {i+1} ({date}) ---\n{mem['text']}\n\n"

            messages = [
                SystemMessage(content=DEEP_PASS_SYSTEM_PROMPT),
                HumanMessage(content=context)
            ]

            # 3. Call LLM
            try:
                # We use a synchronous call in an executor, or just ainvoke if available
                response = await self.llm.ainvoke(messages)
                
                # Parse JSON (naive parsing for now)
                raw_json = response.content.strip()
                if raw_json.startswith("```json"):
                    raw_json = raw_json[7:-3]
                elif raw_json.startswith("```"):
                    raw_json = raw_json[3:-3]
                
                import json
                analysis = json.loads(raw_json)
                
                # 4. Process insights
                new_beliefs = analysis.get("new_beliefs", [])
                evolutions = analysis.get("evolutions", [])
                reframings = analysis.get("reframings", [])
                
                if new_beliefs or evolutions or reframings:
                    logger.info(f"Found {len(new_beliefs)} new beliefs, {len(evolutions)} evolutions, {len(reframings)} reframings.")
                    insights_generated += 1
                    
                    # Store new beliefs directly in Neo4j
                    for nb in new_beliefs:
                        self.memory.neo4j.upsert_belief(nb["content"], nb.get("confidence", 0.5))
                        
                    # Here we would normally store the reframings as explicit REFRAMED_BY edges in Neo4j
                    # For now, we log them as proof of concept
                    for r in reframings:
                        logger.info(f"INSIGHT: {r['insight']}")

            except Exception as e:
                logger.error(f"Error during LLM synthesis for belief {belief['id']}: {e}")
            finally:
                # Always mark analyzed to prevent infinite loops on failing beliefs
                self._mark_belief_analyzed(belief["id"])
                
            # Sleep briefly to respect rate limits
            await asyncio.sleep(2)

        return insights_generated

    async def run_rabbit_hole(self):
        """Pick a random recent memory, find a tangent, and ruminate on it."""
        logger.info("Entering the Rabbit Hole (Late Night Thoughts)...")
        
        # 1. Get a random recent memory from Chroma
        recent = self.memory.chroma.get_recent(n=100)
        if not recent:
            logger.info("No recent memories to ruminate on.")
            return 0
            
        import random
        seed_memory = random.choice(recent)
        logger.info(f"Seed memory selected: {seed_memory['text'][:80]}...")
        
        creative_llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.8, # Higher temp for creative tangents
            max_output_tokens=2048,
        )
        
        # 2. Ask LLM for a tangent concept
        tangent_prompt = f"Given this memory: '{seed_memory['text']}', extract one single, abstract, tangent concept (1-3 words) that this vaguely relates to psychologically or philosophically. Return ONLY the concept."
        try:
            tangent_res = await creative_llm.ainvoke([HumanMessage(content=tangent_prompt)])
            tangent = tangent_res.content.strip()
            logger.info(f"Tangent concept generated: {tangent}")
        except Exception as e:
            logger.error(f"Failed to generate tangent: {e}")
            return 0
            
        # 3. Vector search for the tangent concept
        tangent_memories = self.memory.chroma.query_memory(tangent, k=15)
        
        # 4. Build prompt
        context = f"SEED MEMORY:\n{seed_memory['text']}\n\nTANGENT CONCEPT: {tangent}\n\nTANGENT MEMORIES:\n"
        for i, mem in enumerate(tangent_memories):
            context += f"--- {i+1} ---\n{mem['text']}\n\n"
            
        messages = [
            SystemMessage(content=RABBIT_HOLE_SYSTEM_PROMPT),
            HumanMessage(content=context)
        ]
        
        # 5. Synthesize the epiphany
        try:
            response = await creative_llm.ainvoke(messages)
            raw_json = response.content.strip()
            if raw_json.startswith("```json"):
                raw_json = raw_json[7:-3]
            elif raw_json.startswith("```"):
                raw_json = raw_json[3:-3]
            
            import json
            analysis = json.loads(raw_json)
            
            epiphany = analysis.get("epiphany")
            if epiphany:
                logger.info(f"\n{'='*50}\n🌟 EPIPHANY:\n{epiphany}\n{'='*50}\n")
                
            new_beliefs = analysis.get("new_beliefs", [])
            for nb in new_beliefs:
                # Merge the epiphany as a core structural belief in Neo4j
                self.memory.neo4j.upsert_belief(nb["content"], nb.get("confidence", 0.7))
                logger.info(f"Graph Updated w/ Insight: {nb['content']}")
                
            return 1
        except Exception as e:
            logger.error(f"Error during Rabbit Hole synthesis: {e}")
            return 0

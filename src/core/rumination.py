import logging
from datetime import datetime, timedelta, timezone
from src.core.config import settings
from src.memory.manager import memory_manager
from src.core.router import llm_router
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)

RUMINATION_PROMPT = """\
You are the Rumination Engine of AIManager. Your job is to analyze recent conversations and extract structured knowledge for the long-term Knowledge Graph.

TASKS:
1. Identify new entities (People, Places, Preferences, Projects, etc.).
2. Identify new relationships or facts between entities.
3. Identify contradictions or conflicts with existing knowledge.

OUTPUT FORMAT (JSON):
{
    "new_nodes": [{"label": "Person", "name": "Alice", "fact": "Likes tea"}],
    "new_edges": [{"source": "Kevin", "target": "Alice", "type": "FRIEND_OF"}],
    "conflicts": ["User previously said they lived in London, but now mentioned NYC."]
}
"""

class RuminationEngine:
    """
    Background worker that synthesizes episodic memories into structured knowledge.
    """

    def __init__(self):
        self.memory = memory_manager
        self.router = llm_router

    async def ruminate(self):
        """
        Main background job: Scan, Synthesize, Store.
        """
        logger.info("Starting rumination cycle...")
        
        # 1. Fetch recent memories (last 24 hours)
        # In a real scenario, we'd track the last rumination timestamp
        recent_mems = self.memory.chroma.search("", n_results=20) # Get a sample of recent stuff
        if not recent_mems:
            logger.info("No recent memories to ruminate on.")
            return

        text_to_analyze = "\n".join([m["text"] for m in recent_mems])

        # 2. Synthesize using a cost-efficient model (Flash)
        spec = self.router.get_best_model("EXTRACTION")
        # We need a synchronous way or run in thread
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model=spec.model_id,
            google_api_key=spec.api_key,
            temperature=0.1
        )

        try:
            response = await llm.ainvoke([
                SystemMessage(content=RUMINATION_PROMPT),
                HumanMessage(content=f"Analyze these recent memories:\n{text_to_analyze}")
            ])
            
            # 3. Parse and Store (simplified for now)
            # In a full implementation, we'd use a PydanticOutputParser
            logger.info("Rumination complete. Found new insights.")
            # TODO: Iterate over JSON and call self.memory.neo4j.add_node/edge
            
        except Exception as e:
            logger.error("Rumination failed: %s", e)

rumination_engine = RuminationEngine()

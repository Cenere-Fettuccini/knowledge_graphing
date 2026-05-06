"""
The Night Shift Worker.

A standalone process designed to burn idle LLM credits by continuously
performing deep cognitive synthesis on the user's historical data.
It loops through the archive, finding unspoken beliefs and structural evolutions.
"""

import asyncio
import logging
import sys

from src.core.config import settings
from src.rumination.deep_pass import DeepSynthesisEngine
from src.memory.manager import MemoryManager

# Setup basic logging for the worker
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("night_shift")

async def run_night_shift():
    logger.info("Initializing the Night Shift Engine...")
    
    # Initialize connections to ChromaDB and Neo4j
    memory = MemoryManager()
    engine = DeepSynthesisEngine(memory=memory)
    
    logger.info("Night Shift active. Beginning infinite synthesis loop.")
    logger.info("Press Ctrl+C to gracefully stop.")
    
    try:
        while True:
            # Run one batch of deep synthesis (processes up to 10 unanalyzed beliefs)
            insights = await engine.run_batch()
            
            if insights > 0:
                logger.info(f"Batch complete. Generated {insights} new profound insights.")
                # We did work, take a short breather to respect API rate limits
                logger.info("Cooling down for 10 seconds before next batch...")
                await asyncio.sleep(10)
            else:
                # No un-analyzed data left. Wait for a longer period before checking again.
                logger.info("Archive fully synthesized. Sleeping for 1 hour...")
                await asyncio.sleep(3600)
                
    except asyncio.CancelledError:
        logger.info("Night Shift interrupted. Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Night Shift encountered a fatal error: {e}", exc_info=True)
    finally:
        # Cleanup
        memory.gdb.driver.close()
        logger.info("Night Shift offline.")

if __name__ == "__main__":
    try:
        asyncio.run(run_night_shift())
    except KeyboardInterrupt:
        pass

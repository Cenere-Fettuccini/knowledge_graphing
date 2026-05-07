"""
The Late Night Thoughts Worker.

A standalone process designed to ruminate creatively over the user's memories.
It picks random thoughts, extracts bizarre or profound tangents, searches the 
archive for those tangents, and synthesizes "late night epiphanies" that are 
written back into the knowledge graph as new core beliefs.
"""

import asyncio
import logging

from src.core.logging_config import setup_logging
from src.rumination.deep_pass import DeepSynthesisEngine
from src.memory.manager import MemoryManager

setup_logging()
logger = logging.getLogger("late_night_thoughts")

async def run_late_night_thoughts():
    logger.info("Initializing the Subconscious Rumination Engine...")
    
    # Initialize connections to ChromaDB and Neo4j
    memory = MemoryManager()
    engine = DeepSynthesisEngine(memory=memory)
    
    logger.info("Rabbit Hole sequence active. Synthesizing random tangent thoughts.")
    logger.info("Press Ctrl+C to gracefully stop.")
    
    try:
        while True:
            # Wander down one rabbit hole
            insights = await engine.run_rabbit_hole()
            
            # Wait a bit before diving into the next one
            logger.info("Taking a breath before the next tangent... (sleeping 15s)")
            await asyncio.sleep(15)
                
    except asyncio.CancelledError:
        logger.info("Rumination interrupted. Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Engine encountered a fatal error: {e}", exc_info=True)
    finally:
        # Cleanup
        memory.neo4j.driver.close()
        logger.info("Subconscious offline.")

if __name__ == "__main__":
    try:
        asyncio.run(run_late_night_thoughts())
    except KeyboardInterrupt:
        pass

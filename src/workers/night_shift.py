"""
The Late Night Thoughts Worker.

A standalone process that runs the Rumination Engine continuously — picks
random memories, extracts tangents, and synthesises "late night epiphanies"
written back into the knowledge graph as new Belief nodes.

Run directly for manual / one-off use:
    python -m src.workers.night_shift

In production, prefer enabling the RuminationScheduler via RUMINATION_ENABLED=true
so the FastAPI lifespan manages the lifecycle automatically.
"""

import asyncio
import logging

from src.core.logging_config import setup_logging
from src.memory.manager import get_memory_manager
from src.rumination.deep_pass import DeepSynthesisEngine

setup_logging()
logger = logging.getLogger("late_night_thoughts")


async def run_late_night_thoughts():
    logger.info("Initializing the Subconscious Rumination Engine...")

    memory = get_memory_manager()
    engine = DeepSynthesisEngine(memory=memory)

    logger.info("Rabbit Hole sequence active. Synthesizing random tangent thoughts.")
    logger.info("Press Ctrl+C to gracefully stop.")

    try:
        while True:
            await engine.run_rabbit_hole()
            logger.info("Taking a breath before the next tangent... (sleeping 15s)")
            await asyncio.sleep(15)

    except asyncio.CancelledError:
        logger.info("Rumination interrupted. Shutting down gracefully...")
    except Exception as e:
        logger.error("Engine encountered a fatal error: %s", e, exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(run_late_night_thoughts())
    except KeyboardInterrupt:
        pass

import logging
from datetime import datetime
from src.core.config import settings
from src.memory.manager import memory_manager
from telegram import Bot
import asyncio

logger = logging.getLogger(__name__)

class ProactiveManager:
    """
    Handles proactive notifications and task reminders.
    """

    def __init__(self):
        self.bot = Bot(token=settings.telegram_bot_token)
        self.memory = memory_manager

    async def check_and_notify(self):
        """
        Scan Neo4j for due tasks and notify the user.
        """
        logger.info("Checking for proactive reminders...")
        
        try:
            # Query Neo4j for TODO tasks
            # This is a bit simplified, ideally we'd filter by due_date in Cypher
            overview = self.memory.neo4j.get_graph_overview(limit=100)
            tasks = [n for n in overview["nodes"] if n["label"] == "Task" and n.get("status") == "TODO"]
            
            if not tasks:
                return

            # For now, we just notify about the first TODO task as a POC
            task = tasks[0]
            message = f"🔔 Reminder: You have an active task: '{task['name']}'."
            
            # We need a chat_id. In a multi-user system, we'd store this in the graph.
            # For this MVP, we'll try to find the most recent session chat_id.
            # Assuming there's a 'last_chat_id' in settings or similar.
            # For now, we just log it unless we have a reliable target.
            logger.info(f"Proactive Notification: {message}")
            
        except Exception as e:
            logger.error(f"Proactive check failed: {e}")

proactive_manager = ProactiveManager()

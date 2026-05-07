from __future__ import annotations

from datetime import datetime

from langchain_core.tools import tool


@tool
def get_current_time():
    """
    Returns the current local date and time.
    Use this when the user asks about the time, date, or relative events (e.g., 'tomorrow', 'next week').
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"The current local time is {now}"

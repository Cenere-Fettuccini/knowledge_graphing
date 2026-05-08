from __future__ import annotations

from pathlib import Path

from src.platform.registry import AppDefinition


def get_routine_scheduler_app() -> AppDefinition:
    return AppDefinition(
        id="routine_scheduler",
        name="Routine Scheduler",
        description="A separate scheduling app for routines, recurring structure, and calendar-driven automation.",
        route_prefix="/apps/routine-scheduler",
        section_role="domain",
        static_dir=Path(__file__).resolve().parents[2] / "frontend" / "shell",
        icon="Routine",
        status="active",
    )

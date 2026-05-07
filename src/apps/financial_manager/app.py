from __future__ import annotations

from pathlib import Path

from src.platform.registry import AppDefinition


def get_financial_manager_app() -> AppDefinition:
    return AppDefinition(
        id="financial_manager",
        name="Financial Manager",
        description="A separate app surface for money workflows, analysis, and future finance-safe tools.",
        route_prefix="/apps/financial-manager",
        static_dir=Path(__file__).resolve().parent / "static",
        icon="Finance",
        status="active",
    )

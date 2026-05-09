from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AppDefinition:
    """Metadata and mount details for a platform app."""

    id: str
    name: str
    description: str
    route_prefix: str
    section_role: str
    static_dir: Path | None = None
    api_prefix: str | None = None
    api_router: object | None = None
    icon: str = "App"
    status: str = "active"
    legacy_api_prefixes: tuple[str, ...] = ()
    legacy_route_prefixes: tuple[str, ...] = ()


@dataclass
class AppRegistry:
    """In-memory catalog of registered apps."""

    _apps: list[AppDefinition] = field(default_factory=list)

    def register(self, app_def: AppDefinition) -> None:
        if any(existing.id == app_def.id for existing in self._apps):
            raise ValueError(f"App '{app_def.id}' is already registered")
        self._apps.append(app_def)

    def list_apps(self) -> list[AppDefinition]:
        return list(self._apps)

    def iter_active_apps(self) -> Iterable[AppDefinition]:
        return (app_def for app_def in self._apps if app_def.status == "active")

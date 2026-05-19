"""Model registry.

Importing this package imports every concrete adapter module, which
fires ``__init_subclass__`` and populates ``BaseModel._registry``.
External callers use ``get_model(name)`` / ``all_models()``.
"""

from __future__ import annotations

from src.agent._models import lmstudio as _lmstudio  # noqa: F401 — side-effect: registers
from src.agent._models._base import BaseModel


def get_model(name: str) -> BaseModel:
    """Return the registered model adapter, or raise ``UnknownModelError``."""
    return BaseModel.get(name)


def all_models() -> list[BaseModel]:
    """Return every registered model adapter, sorted by name."""
    return [BaseModel.get(n) for n in BaseModel.all_names()]


__all__ = ["BaseModel", "all_models", "get_model"]

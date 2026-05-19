"""Turn id generation.

A turn id is a short UUID4 hex with a configurable prefix. Ids are
opaque outside the memory module; collisions are astronomically
unlikely with 12 hex chars (~48 bits of entropy).
"""

from __future__ import annotations

import os
import uuid


def new_turn_id() -> str:
    """Return a fresh turn id, e.g. ``t-9f1c2a8b04de``.

    The prefix is read from ``TURN_ID_PREFIX`` (default ``t-``) on every
    call so tests can monkeypatch it.
    """
    prefix = os.environ.get("TURN_ID_PREFIX", "t-")
    return f"{prefix}{uuid.uuid4().hex[:12]}"

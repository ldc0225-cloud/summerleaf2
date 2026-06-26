"""activities._registry — 활동 id → 클래스 (순환 import 방지)."""

from __future__ import annotations

from typing import Dict, Optional

_REGISTRY: Dict[str, type] = {}


def register_activity(activity_id: str, cls: type) -> None:
    _REGISTRY[(activity_id or "").strip()] = cls


def create_activity(activity_id: str):
    cls = _REGISTRY.get((activity_id or "").strip())
    if cls is None:
        return None
    return cls()


def list_registered() -> list:
    return sorted(_REGISTRY.keys())

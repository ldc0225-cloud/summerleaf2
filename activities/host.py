"""
activities.host — 필드 활동 호스트 (main.py 브릿지 대상).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._registry import create_activity
from .base import BaseFieldActivity, FieldDrawContext


class FieldActivityHost:
    """main.py 가 소유하는 단일 활동 세션 관리자."""

    def __init__(self):
        self._session: Optional[BaseFieldActivity] = None
        self._finished: Optional[Dict[str, Any]] = None

    @property
    def is_active(self) -> bool:
        return self._session is not None and bool(self._session.is_active)

    @property
    def active_id(self) -> Optional[str]:
        if self._session is None:
            return None
        return getattr(self._session, "activity_id", None)

    def blocks_field_move(self) -> bool:
        if not self.is_active:
            return False
        try:
            return bool(self._session.blocks_field_move())
        except Exception:
            return True

    def blocks_zone_confirm(self) -> bool:
        if not self.is_active:
            return False
        try:
            return bool(self._session.blocks_zone_confirm())
        except Exception:
            return True

    def consume_request(self, request: dict, *, player) -> bool:
        """ev_mgr.field_activity_request 소비."""
        if not isinstance(request, dict):
            return False
        if str(request.get("action") or "").strip().lower() != "start":
            return False
        if self.is_active:
            print("[activity] already active — ignore start")
            return False
        aid = str(request.get("id") or "").strip()
        session = create_activity(aid)
        if session is None:
            print(f"[activity] unknown id: {aid}")
            return False
        params = {k: v for k, v in request.items() if k not in ("id", "action")}
        try:
            ok = bool(session.begin(player, **params))
        except Exception as e:
            print(f"[activity] begin failed ({aid}): {e}")
            ok = False
        if ok:
            self._session = session
            self._finished = None
            print(f"[activity] started: {aid}")
        return ok

    def cancel(self) -> None:
        if self._session is None:
            return
        try:
            cancel_fn = getattr(self._session, "cancel", None)
            if callable(cancel_fn):
                cancel_fn()
        except Exception:
            self._session = None

    def tick(self, dt_sec: float, player, now_ms: int) -> None:
        if self._session is None:
            return
        try:
            self._session.tick(dt_sec, player, now_ms)
        except Exception as e:
            print(f"[activity] tick error: {e}")
            self._session = None
            return
        if self._session.is_finished:
            try:
                self._finished = dict(self._session.result())
            except Exception:
                self._finished = {"activity": self.active_id, "won": False}
            print(f"[activity] finished: {self._finished}")
            self._session = None

    def on_pointer_down(self, screen_xy, world_xy, now_ms: int) -> bool:
        if self._session is None:
            return False
        try:
            return bool(self._session.on_pointer_down(screen_xy, world_xy, now_ms))
        except Exception:
            return True

    def on_pointer_up(self, now_ms: int) -> bool:
        if self._session is None:
            return False
        try:
            return bool(self._session.on_pointer_up(now_ms))
        except Exception:
            return True

    def draw(self, ctx: FieldDrawContext) -> None:
        if self._session is None:
            return
        try:
            self._session.draw(ctx)
        except Exception as e:
            print(f"[activity] draw error: {e}")

    def pop_finished_result(self) -> Optional[Dict[str, Any]]:
        """종료 직후 1회만 반환."""
        r = self._finished
        self._finished = None
        return r

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

    def freeze_field(self) -> bool:
        """활성 세션이 월드 시뮬(이동·애니)까지 멈추길 원할 때 True."""
        if not self.is_active:
            return False
        try:
            fn = getattr(self._session, "freeze_field", None)
            return bool(fn()) if callable(fn) else False
        except Exception:
            return False

    def blocks_zone_confirm(self) -> bool:
        if not self.is_active:
            return False
        try:
            return bool(self._session.blocks_zone_confirm())
        except Exception:
            return True

    def consume_request(
        self, request: dict, *, player, objs=None, npcs=None, mask=None, world_data=None, ev_mgr=None, bg=None
    ) -> bool:
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
        if objs is not None:
            params["objs"] = objs
        if npcs is not None:
            params["npcs"] = npcs
        if mask is not None:
            params["mask"] = mask
        if bg is not None:
            params["bg"] = bg
        if world_data is not None:
            params["world_data"] = world_data
        if ev_mgr is not None:
            params["ev_mgr"] = ev_mgr
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
            return
        if self._session.is_finished:
            try:
                self._finished = dict(self._session.result())
            except Exception:
                self._finished = {"activity": self.active_id, "won": False, "quit": True}
            print(f"[activity] cancelled/finished: {self._finished}")
            self._session = None

    def get_save_location_override(self):
        if self._session is None:
            return None
        try:
            fn = getattr(self._session, "save_location_override", None)
            if callable(fn):
                return fn()
        except Exception:
            pass
        return None

    def tick(self, dt_sec: float, player, now_ms: int, *, npcs=None, objs=None) -> None:
        if self._session is None:
            return
        # 맵 전환·progress 적용 후 main 의 npcs 리스트가 바뀌어도 세션이 최신 참조를 쓰게 함
        try:
            bind = getattr(self._session, "bind_field_lists", None)
            if callable(bind):
                bind(npcs=npcs, objs=objs)
        except Exception:
            pass
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
            handled = bool(self._session.on_pointer_down(screen_xy, world_xy, now_ms))
        except Exception:
            handled = True
        if self._session is not None and self._session.is_finished:
            try:
                self._finished = dict(self._session.result())
            except Exception:
                self._finished = {"activity": self.active_id, "won": False, "quit": True}
            print(f"[activity] finished (input): {self._finished}")
            self._session = None
        return handled

    def on_primary_key(self, key: int) -> bool:
        if self._session is None:
            return False
        try:
            fn = getattr(self._session, "on_primary_key", None)
            if callable(fn):
                return bool(fn(key))
        except Exception:
            pass
        return False

    def on_pointer_up(self, now_ms: int) -> bool:
        if self._session is None:
            return False
        try:
            return bool(self._session.on_pointer_up(now_ms))
        except Exception:
            return True

    def draw_world_under(self, ctx: FieldDrawContext) -> None:
        """배경 직후·캐릭터 ysort 직전 (연꽃잎·wave 등)."""
        if self._session is None:
            return
        try:
            fn = getattr(self._session, "draw_world_under", None)
            if callable(fn):
                fn(ctx)
        except Exception as e:
            print(f"[activity] draw_world_under error: {e}")

    def collect_ysort_sprites(self):
        """활동이 제공하는 ysort 스프라이트 (황소개구리·물방울 등)."""
        if self._session is None:
            return []
        try:
            fn = getattr(self._session, "collect_ysort_sprites", None)
            if callable(fn):
                out = fn()
                return list(out) if out else []
        except Exception as e:
            print(f"[activity] collect_ysort_sprites error: {e}")
        return []

    def draw_world(self, ctx: FieldDrawContext) -> None:
        if self._session is None:
            return
        try:
            draw_world = getattr(self._session, "draw_world", None)
            if callable(draw_world):
                draw_world(ctx)
            else:
                # fishing 등: 월드 오버레이는 draw() 한 경로만
                self._session.draw(ctx)
        except Exception as e:
            print(f"[activity] draw_world error: {e}")

    def draw(self, ctx: FieldDrawContext) -> None:
        if self._session is None:
            return
        try:
            draw_world = getattr(self._session, "draw_world", None)
            if callable(draw_world):
                draw_world(ctx)
            else:
                self._session.draw(ctx)
        except Exception as e:
            print(f"[activity] draw error: {e}")

    def draw_screen(self, ctx: FieldDrawContext) -> None:
        """월드 줌 이후 논리 화면에 그릴 UI (야구 메뉴·레이스 HUD 등). draw()로 폴백하지 않음."""
        if self._session is None:
            return
        try:
            draw_screen = getattr(self._session, "draw_screen", None)
            if callable(draw_screen):
                draw_screen(ctx)
        except Exception as e:
            print(f"[activity] draw_screen error: {e}")

    def pop_finished_result(self) -> Optional[Dict[str, Any]]:
        """종료 직후 1회만 반환."""
        r = self._finished
        self._finished = None
        return r

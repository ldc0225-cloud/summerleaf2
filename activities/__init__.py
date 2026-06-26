"""
activities — 필드 위 미니게임(그네·낚시 등) 통합 패키지.

[개념]
  - minigames/ : 전체 화면 전환 (raindodge, antarctic_run …)
  - activities/: 맵·캐릭터를 유지한 채 필드에서 플레이 (swing_ride, fishing …)

[호출 — 이벤트에서 직관적으로]
  { "type": "DEV_CMD", "cmd": "start_fishing" }
  { "type": "DEV_CMD", "cmd": "start_fishing", "pond": "jjangpu_pond" }

  범용 형태 (추가 활동용):
  { "type": "DEV_CMD", "cmd": "start_activity_swing" }   ← 추후 그네 통합 시

[main.py 역할]
  - FieldActivityHost 인스턴스 1개
  - tick / 입력 / draw 브릿지만 (로직은 이 패키지)

[새 활동 추가]
  1. activities/<id>.py 에 BaseFieldActivity 서브클래스
  2. __init__ 에 register_activity("<id>", Class)
  3. field_runtime.apply_dev_runtime_command 에 start_<id> / stop_<id>
"""

from __future__ import annotations

from .base import BaseFieldActivity, FieldDrawContext
from .fishing import FishingActivity
from .host import FieldActivityHost
from ._registry import create_activity, list_registered, register_activity

register_activity("fishing", FishingActivity)


def list_activities():
    return list_registered()


def request_field_activity(ev_mgr, activity_id: str, **params) -> None:
    """
    필드 활동 시작 요청. main 루프가 다음 틱에 소비한다.
    (그네 start_swing_ride 와 동일한 request 패턴)
    """
    aid = (activity_id or "").strip()
    if not aid:
        return
    payload = {"id": aid, "action": "start"}
    payload.update(params or {})
    try:
        ev_mgr.field_activity_request = payload
    except Exception:
        pass


__all__ = [
    "BaseFieldActivity",
    "FieldActivityHost",
    "FieldDrawContext",
    "FishingActivity",
    "create_activity",
    "list_activities",
    "request_field_activity",
]

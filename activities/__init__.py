"""
activities — 필드 위 미니게임(그네·낚시·야구·레이스·황소개구리·징검다리 등) 통합 패키지.

[개념]
  - activities/: 맵·캐릭터를 유지한 채 필드에서 플레이 (본체 미니게임은 여기만)

[호출 — 이벤트에서 직관적으로]
  { "type": "DEV_CMD", "cmd": "start_fishing" }
  { "type": "DEV_CMD", "cmd": "start_fishing", "pond": "jjangpu_pond" }

  범용 형태 (추가 활동용):
  { "type": "DEV_CMD", "cmd": "start_activity_baseball" }

[야구]
  { "type": "DEV_CMD", "cmd": "start_baseball" }
  { "type": "DEV_CMD", "cmd": "start_baseball", "mode": "story" }
  OVERLAY_UI click_action: stop_baseball

[레이스]
  { "type": "DEV_CMD", "cmd": "start_racing", "map": "bg_town" }
  OVERLAY_UI click_action: stop_racing

[황소개구리]
  { "type": "DEV_CMD", "cmd": "start_bullfrog", "map": "bg_pond01",
    "return_map": "bg_jjangpu", "return_pos": [816, 2304] }
  OVERLAY_UI click_action: stop_bullfrog

[징검다리 — 황소개구리 축약, 맵 전환 없음]
  { "type": "DEV_CMD", "cmd": "start_lotus_cross", "from_side": "a" }
  { "type": "DEV_CMD", "cmd": "start_lotus_cross", "from_side": "b" }
  OVERLAY_UI click_action: stop_lotus_cross

[캐릭터 선택 — 세이브 없이 첫 시작, 보통은 데모 종료 후 main 이 자동 시작]
  { "type": "DEV_CMD", "cmd": "start_activity_char_select" }

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
from .baseball import BaseballActivity
from .bullfrog import BullfrogActivity
from .char_select import CharSelectActivity
from .fishing import FishingActivity
from .lotus_cross import LotusCrossActivity, draw_lotus_cross_idle
from .racing import RacingActivity
from .host import FieldActivityHost
from ._registry import create_activity, list_registered, register_activity

register_activity("fishing", FishingActivity)
register_activity("baseball", BaseballActivity)
register_activity("racing", RacingActivity)
register_activity("bullfrog", BullfrogActivity)
register_activity("lotus_cross", LotusCrossActivity)
register_activity("char_select", CharSelectActivity)


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
    "BaseballActivity",
    "RacingActivity",
    "BullfrogActivity",
    "LotusCrossActivity",
    "draw_lotus_cross_idle",
    "CharSelectActivity",
    "create_activity",
    "list_activities",
    "request_field_activity",
]

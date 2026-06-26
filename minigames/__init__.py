"""
minigames — 미니게임 패키지 (코드·에셋 배치 규칙)

[디렉터리 구조]
  minigames/
    __init__.py       ← 레지스트리, create_session(), 공통 파싱
    _paths.py         ← PROJECT_ROOT, minigame_asset() 경로 헬퍼
    raindodge.py      ← 게임 1개 = py 파일 1개 (세션 클래스)
    kart_circuit.py   ← 카트 프로토타입 (단독 데모, 연동 예정)
    antarctic_run.py  ← 남극탐험 스타일 전진 원근 러너 (뒤→앞 시점)

  activities/         ← 필드 위 미니게임 (낚시·그네 등) — main 브릿지

  assets/minigames/
    raindodge/
    kart/
    antarctic_run/
    _shared/          ← HUD·폰트 등 여러 게임 공용

  (루트)
    kart_circuit_demo.py    ← kart 단독 테스트 런처
    antarctic_run_demo.py   ← antarctic_run 단독 테스트 런처

[본편 연동]
  - main.py / engine.py 는 게임 로직을 갖지 않음.
  - events.json MINIGAME_PLAY → create_session(game_id) → tick/draw/result
  - 세션 인터페이스: handle_event, tick, draw, done, result

[새 게임 추가 체크리스트]
  1. minigames/<game_id>.py 에 세션 클래스 작성
  2. __init__._REGISTRY 에 game_id 등록
  3. assets/minigames/<game_id>/ 에 에셋 배치
  4. events.json 에 MINIGAME_PLAY 스텝 연결
"""

from __future__ import annotations

from typing import Dict, Optional, Type

from ._paths import PROJECT_ROOT, minigame_asset, minigame_shared_asset
from .antarctic_run import AntarcticRunSession
from .raindodge import RainDodgeSession

# game_id → 세션 클래스 (MINIGAME_PLAY 의 "game" 값과 일치)
_REGISTRY: Dict[str, Type] = {
    "raindodge": RainDodgeSession,
    "frog_catch_trial": RainDodgeSession,  # 구 id 호환
    "antarctic_run": AntarcticRunSession,
    # "kart_circuit": KartCircuitSession,  # 연동 시 등록
}


def parse_goal_and_time(step: dict) -> tuple[int, float]:
    """MINIGAME_PLAY 스텝에서 goal·time_limit 공통 파싱."""
    try:
        goal = int(step.get("goal", 5) or 5)
    except (TypeError, ValueError):
        goal = 5
    try:
        time_limit = float(step.get("time_limit", 45) or 45)
    except (TypeError, ValueError):
        time_limit = 45.0
    goal = max(1, min(99, goal))
    time_limit = max(5.0, min(600.0, time_limit))
    return goal, time_limit


def create_session(
    game_id: str,
    width: int,
    height: int,
    step: dict,
    save_data: Optional[dict] = None,
):
    """
    이벤트 MINIGAME_PLAY 스텝으로 미니게임 세션 생성.
    알 수 없는 game_id 이면 None (engine 이 스텝을 건너뜀).
    """
    gid = (game_id or "").strip()
    cls = _REGISTRY.get(gid)
    if cls is None:
        return None
    goal, time_limit = parse_goal_and_time(step)
    return cls(
        int(width),
        int(height),
        goal=goal,
        time_limit=time_limit,
        save_data=dict(save_data or {}),
    )


def list_registered_games():
    """에디터·디버그용 등록 목록."""
    return sorted(_REGISTRY.keys())

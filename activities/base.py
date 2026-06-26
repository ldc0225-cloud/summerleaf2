"""activities.base — 필드 활동 공통 타입 (순환 import 없음)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import pygame


@dataclass
class FieldDrawContext:
    """월드 좌표 → 화면(논리 px) 변환에 필요한 렌더 파라미터."""

    surf: pygame.Surface
    cam_draw_x: float
    cam_draw_y: float
    z: float
    y_transform: Optional[Callable[[float], float]]
    x_offset_fn: Optional[Callable[[float], float]]
    font_fn: Callable[[int], pygame.font.Font]


class BaseFieldActivity:
    """필드 활동 공통 인터페이스."""

    activity_id: str = "base"

    def begin(self, player, **params) -> bool:
        raise NotImplementedError

    def tick(self, dt_sec: float, player, now_ms: int) -> None:
        pass

    def on_pointer_down(self, screen_xy, world_xy, now_ms: int) -> bool:
        """처리했으면 True (필드 이동 클릭 등 상위 입력 차단)."""
        return False

    def on_pointer_up(self, now_ms: int) -> bool:
        return False

    def draw(self, ctx: FieldDrawContext) -> None:
        pass

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_finished(self) -> bool:
        return False

    def blocks_field_move(self) -> bool:
        return True

    def blocks_zone_confirm(self) -> bool:
        return True

    def result(self) -> Dict[str, Any]:
        return {"activity": self.activity_id, "won": False}

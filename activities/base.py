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
    mode7_ctx: Any = None  # rotate3d Mode7 ctx (레이스 아이템 등)
    # draw_screen: world_surf → 후처리 줌 합성 뒤 최종 논리 좌표 (월드 UI 앵커용)
    world_zoom_draw: float = 1.0
    world_zoom_off_x: float = 0.0
    world_zoom_off_y: float = 0.0
    # 필드 원근 세로압축 계수 — sprite_tilt=0 누운 스프라이트용 (없으면 무시)
    sprite_perspective_q: Optional[float] = None


# 캐릭터 선택 그리드에서 고를 수 없는 칸(이미 고른 플레이어 등)을 덮는 알파
CHAR_PICK_TAKEN_DIM_ALPHA = 130


def blit_ui_dim(surf: pygame.Surface, rect: pygame.Rect, alpha: int = CHAR_PICK_TAKEN_DIM_ALPHA) -> None:
    """UI 칸을 어둡게 덮는다. 야구·레이스 NPC 선택에서 이미 고른 캐릭터 표시에 사용."""
    if surf is None or rect is None:
        return
    try:
        w, h = int(rect.width), int(rect.height)
    except Exception:
        return
    if w <= 0 or h <= 0:
        return
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, max(0, min(255, int(alpha)))))
    surf.blit(overlay, (rect.left, rect.top))


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

    def draw_world_under(self, ctx: FieldDrawContext) -> None:
        """배경 직후·캐릭터 ysort 직전 (연꽃잎·바닥 FX 등)."""
        pass

    def collect_ysort_sprites(self):
        """캐릭터와 함께 ysort 할 임시 스프라이트 목록 (pos/layer/draw 필요)."""
        return []

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_finished(self) -> bool:
        return False

    def blocks_field_move(self) -> bool:
        return True

    def freeze_field(self) -> bool:
        """True면 뒤 월드(이동·애니·오토스크롤)를 정지. 기본은 활동만 입력 차단."""
        return False

    def blocks_zone_confirm(self) -> bool:
        return True

    def result(self) -> Dict[str, Any]:
        return {"activity": self.activity_id, "won": False}

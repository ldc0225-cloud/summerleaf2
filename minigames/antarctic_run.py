"""
antarctic_run — 남극탐험(펭귄 어드벤처) 스타일 전진 러너 뼈대.

[시점] 횡스크롤이 아님 — 캐릭터 뒤에서 앞으로 달려가는 원근(얼음 길이 멀어짐).
  고전 「남극탐험」/ Konami Penguin Adventure 와 같은 계열.

[메카닉 뼈대]
  - 자동 전진 + 좌우(얼음 위 위치) + 점프(갈라진 얼음 구간)
  - 멀리서 다가오는 구간에 갭(바다) / 물고기(점프해서 먹기)
  - goal(m) 도달 승리 / 생명 소진·시간 초과 실패

[입력]
  - 좌우: ←→ / A D / 화면 하단 좌·우 터치
  - 점프: Space / W / ↑ / 화면 상단 터치

[에셋] (추후) assets/minigames/antarctic_run/
"""

from __future__ import annotations

import math
import random
import time
from typing import Callable, Optional

import pygame

# --- 화면 연출 상수 (원근 얼음길) ---
SKY_COLOR = (148, 198, 235)
ICE_COLOR = (218, 236, 248)
ICE_EDGE = (170, 200, 220)
GAP_COLOR = (32, 58, 98)
HORIZON_FRAC = 0.28  # 화면 위쪽 비율 = 하늘
JUMP_CLEAR = 0.38  # 이 높이 이상이면 갭 통과


class AntarcticRunSession:
    """전진 원근 러너 — handle_event / tick / draw / done / result."""

    def __init__(
        self,
        width: int,
        height: int,
        *,
        goal: int = 80,
        time_limit: float = 60.0,
        save_data: Optional[dict] = None,
    ):
        self.w = max(160, int(width))
        self.h = max(120, int(height))
        self.goal = max(10, int(goal))
        self.time_limit = max(5.0, float(time_limit))
        self.save_data = dict(save_data or {})

        self.horizon_y = int(self.h * HORIZON_FRAC)

        # 전진 거리(z 월드 좌표, m로 표시)
        self.forward_z = 0.0
        self.run_speed = max(55.0, self.w * 0.22)
        self.distance_m = 0.0

        # 좌우 위치: -1(왼쪽) ~ +1(오른쪽), 0=중앙
        self.player_lat = 0.0
        self.lat_speed = 1.35

        # 점프(0=바닥, 1=최고점 근처)
        self.jump_h = 0.0
        self.jump_v = 0.0
        self.gravity = 5.2
        self.jump_impulse = 2.35

        self.score = 0
        self.lives = 3
        self.elapsed = 0.0

        # z 구간 스트립: {"z0","z1","kind":"ice"|"gap", "fish": None|{lat, phase}}
        self._strips: list[dict] = []
        self._strip_end = 0.0
        self._rng = random.Random()

        self._move_left = False
        self._move_right = False
        self._jump_pressed = False

        self.game_over = False
        self.won = False
        self._game_over_at = 0.0
        self.result_hold_sec = 1.35

        self._gen_initial_strips()

    @property
    def done(self) -> bool:
        if not self.game_over:
            return False
        return (time.monotonic() - self._game_over_at) >= float(self.result_hold_sec)

    # --- 입력 ---

    def handle_event(self, event) -> None:
        if self.game_over:
            return
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_LEFT, pygame.K_a):
                self._move_left = True
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                self._move_right = True
            elif event.key in (pygame.K_SPACE, pygame.K_UP, pygame.K_w):
                self._jump_pressed = True
        elif event.type == pygame.KEYUP:
            if event.key in (pygame.K_LEFT, pygame.K_a):
                self._move_left = False
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                self._move_right = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            try:
                mx = float(event.pos[0])
                my = float(event.pos[1])
            except (TypeError, ValueError, AttributeError):
                return
            if my < self.h * 0.42:
                self._jump_pressed = True
            elif mx < self.w * 0.5:
                self._move_left = True
                self._move_right = False
            else:
                self._move_right = True
                self._move_left = False
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._move_left = False
            self._move_right = False

    # --- 시뮬레이션 ---

    def tick(self, dt_sec: float) -> None:
        if self.game_over:
            return
        dt = max(0.0, min(0.1, float(dt_sec)))
        self.elapsed += dt

        if self._move_left:
            self.player_lat -= self.lat_speed * dt
        if self._move_right:
            self.player_lat += self.lat_speed * dt
        self.player_lat = max(-1.0, min(1.0, self.player_lat))

        if self._jump_pressed and self.jump_h <= 0.02:
            self.jump_v = self.jump_impulse
        self._jump_pressed = False

        self.jump_v -= self.gravity * dt
        self.jump_h += self.jump_v * dt
        if self.jump_h <= 0.0:
            self.jump_h = 0.0
            self.jump_v = 0.0

        self.forward_z += self.run_speed * dt
        self.distance_m = self.forward_z / 10.0
        self._ensure_strips(self.forward_z + 280.0)

        self._check_gap_collision()
        self._collect_fish()

        if self.distance_m >= float(self.goal):
            self._set_game_over(True)
            self.score += max(0, int((self.time_limit - self.elapsed) * 2))
        elif self.elapsed >= self.time_limit:
            self._set_game_over(False)

    def _check_gap_collision(self) -> None:
        if self.jump_h >= JUMP_CLEAR:
            return
        feet_z = self.forward_z + 4.0
        for st in self._strips:
            if st["kind"] != "gap":
                continue
            if st["z0"] <= feet_z <= st["z1"]:
                self._fall_in_gap()
                return

    def _fall_in_gap(self) -> None:
        self.lives -= 1
        if self.lives <= 0:
            self._set_game_over(False)
            return
        self.forward_z += 25.0
        self.jump_h = 0.0
        self.jump_v = 0.0

    def _collect_fish(self) -> None:
        bite_z = self.forward_z + 8.0
        for st in self._strips:
            fish = st.get("fish")
            if not fish or fish.get("got"):
                continue
            if not (st["z0"] <= bite_z <= st["z1"]):
                continue
            lat_ok = abs(float(fish["lat"]) - self.player_lat) < 0.42
            jump_ok = self.jump_h > 0.12
            if lat_ok and jump_ok:
                fish["got"] = True
                self.score += 10

    def _set_game_over(self, won: bool) -> None:
        self.game_over = True
        self.won = bool(won)
        self._game_over_at = time.monotonic()

    # --- 지형(전진 z 스트립) ---

    def _gen_initial_strips(self) -> None:
        self._strips.clear()
        self._strip_end = 0.0
        self._ensure_strips(320.0)

    def _ensure_strips(self, need_z: float) -> None:
        while self._strip_end < need_z:
            z0 = self._strip_end
            length = self._rng.uniform(18.0, 42.0)
            z1 = z0 + length
            if self._rng.random() < 0.2 and z0 > 40.0:
                kind = "gap"
                fish = None
            else:
                kind = "ice"
                fish = None
                if self._rng.random() < 0.32:
                    fish = {
                        "lat": self._rng.uniform(-0.75, 0.75),
                        "phase": self._rng.uniform(0.0, math.pi * 2.0),
                        "got": False,
                    }
            self._strips.append({"z0": z0, "z1": z1, "kind": kind, "fish": fish})
            self._strip_end = z1

    def _strip_at_z(self, world_z: float) -> Optional[dict]:
        for st in self._strips:
            if st["z0"] <= world_z < st["z1"]:
                return st
        return None

    def result(self) -> dict:
        return {
            "won": bool(self.won),
            "score": int(self.score),
            "distance_m": int(self.distance_m),
            "lives": int(self.lives),
            "elapsed": float(self.elapsed),
        }

    # --- 원근 투영 헬퍼 ---

    def _row_depth(self, sy: int) -> tuple[float, float]:
        """스캔라인 sy → (z_ahead, road_half_width). z_ahead=발밑 기준 앞쪽 거리."""
        h = self.h
        hy = self.horizon_y
        if sy <= hy:
            return 9999.0, 0.0
        t = (sy - hy) / float(max(1, h - hy - 1))
        t = max(0.0, min(1.0, t))
        z_ahead = 220.0 * (1.0 - t) ** 1.65
        half_w = (self.w * 0.42) * (0.08 + t * 0.92)
        return z_ahead, half_w

    def _project(self, z_world: float, lat: float) -> Optional[tuple[int, int, float]]:
        """월드 (z, lat) → 화면 (sx, sy, scale). 발밑 z=forward_z 근처가 화면 하단."""
        z_ahead = z_world - self.forward_z
        if z_ahead < -5.0 or z_ahead > 260.0:
            return None
        hy = self.horizon_y
        h = self.h
        z_pos = max(0.0, float(z_ahead))
        t = 1.0 - (z_pos / 220.0) ** 0.6
        t = max(0.0, min(1.0, t))
        sy = int(hy + t * (h - hy - 1))
        half_w = (self.w * 0.42) * (0.08 + t * 0.92)
        sx = int(self.w * 0.5 + lat * half_w)
        scale = 0.15 + t * 0.85
        return sx, sy, scale

    # --- 렌더 (원근 얼음길 + 플레이스홀더 펭귄) ---

    def draw(self, surf: pygame.Surface, font_fn: Callable[[int], pygame.font.Font]) -> None:
        w, h = self.w, self.h
        hy = self.horizon_y
        surf.fill(SKY_COLOR, (0, 0, w, hy))

        # 원근 얼음 / 갭 스트립 (멀리→가까이)
        for sy in range(hy, h):
            z_ahead, half_w = self._row_depth(sy)
            world_z = self.forward_z + z_ahead
            st = self._strip_at_z(world_z)
            cx = w // 2
            left = int(cx - half_w)
            right = int(cx + half_w)
            if st and st["kind"] == "gap":
                pygame.draw.rect(surf, GAP_COLOR, (left, sy, right - left, 1))
            else:
                col = ICE_COLOR if (sy % 4) else (205, 228, 242)
                pygame.draw.rect(surf, col, (left, sy, right - left, 1))
            if sy == h - 1:
                pygame.draw.line(surf, ICE_EDGE, (left, sy), (right, sy), 1)

        # 물고기 (멀리서 점프하며 다가옴)
        t_anim = self.elapsed
        for st in self._strips:
            fish = st.get("fish")
            if not fish or fish.get("got"):
                continue
            z_mid = (st["z0"] + st["z1"]) * 0.5
            pr = self._project(z_mid, float(fish["lat"]))
            if pr is None:
                continue
            sx, sy, sc = pr
            hop = abs(math.sin(t_anim * 4.5 + float(fish["phase"]))) * (12.0 * sc)
            fy = int(sy - hop - 6 * sc)
            fw = max(4, int(10 * sc))
            fh = max(3, int(6 * sc))
            pygame.draw.ellipse(surf, (255, 150, 50), (sx - fw // 2, fy - fh // 2, fw, fh))
            pygame.draw.ellipse(surf, (255, 210, 80), (sx - fw // 4, fy - fh // 4, fw // 2, fh // 2))

        # 펭귄(플레이스홀더) — 화면 하단, 좌우 위치 + 점프 높이
        _, half_bot = self._row_depth(h - 2)
        sc_bot = max(0.2, half_bot / max(1.0, self.w * 0.42))
        base_y = h - max(18, int(h * 0.12))
        jump_px = int(self.jump_h * 38.0 * sc_bot)
        px = int(w * 0.5 + self.player_lat * (w * 0.38))
        pw = max(12, int(18 * sc_bot))
        ph = max(16, int(22 * sc_bot))
        py = base_y - ph - jump_px
        pygame.draw.ellipse(surf, (25, 28, 38), (px - pw // 2, py + 4, pw, ph - 4))
        pygame.draw.ellipse(surf, (245, 248, 252), (px - pw // 2 + 2, py + 6, pw - 4, ph - 8))
        pygame.draw.circle(surf, (20, 22, 30), (px + pw // 4, py + 7), max(2, pw // 7))

        # HUD
        hud = font_fn(max(9, min(16, w // 28)))
        title = font_fn(max(10, min(18, w // 24)))
        surf.blit(title.render("antarctic_run", True, (35, 55, 80)), (8, 6))
        remain = max(0.0, self.time_limit - self.elapsed)
        surf.blit(hud.render(f"{int(self.distance_m)}/{self.goal}m", True, (30, 50, 70)), (w - 72, 8))
        surf.blit(hud.render(f"{remain:0.0f}s", True, (50, 70, 90)), (w // 2 - 16, 8))
        surf.blit(hud.render(f"♥{self.lives}  {self.score}pt", True, (40, 55, 75)), (8, h - 18))
        surf.blit(
            hud.render("←→ 이동  Space 점프(물고기)", True, (70, 90, 110)),
            (8, h - 34),
        )

        if self.game_over:
            overlay = pygame.Surface((w, h), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 130))
            surf.blit(overlay, (0, 0))
            msg = "도착!" if self.won else "실패…"
            col = (140, 220, 255) if self.won else (255, 190, 150)
            tf = font_fn(max(14, min(26, w // 16)))
            img = tf.render(msg, True, col)
            surf.blit(img, (w // 2 - img.get_width() // 2, h // 2 - 16))


def run_demo():
    """단독 실행. python antarctic_run_demo.py"""
    pygame.init()
    w, h = 320, 240
    screen = pygame.display.set_mode((w, h))
    pygame.display.set_caption("antarctic_run demo (forward view)")
    clock = pygame.time.Clock()
    font_fn = lambda s: pygame.font.SysFont("malgungothic", s) or pygame.font.SysFont("arial", s)

    session = AntarcticRunSession(w, h, goal=80, time_limit=90.0)
    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            else:
                session.handle_event(event)
        session.tick(dt)
        session.draw(screen, font_fn)
        pygame.display.flip()
        if session.done:
            pygame.time.wait(800)
            running = False
    pygame.quit()


if __name__ == "__main__":
    run_demo()

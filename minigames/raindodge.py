"""
raindodge — 비 피하고 음식 받기 미니게임.

[게임 규칙]
  - 화면 위에서 음식(좋음)과 빗방울(나쁨)이 떨어진다.
  - 플레이어는 하단에서 좌우 이동하며 음식을 받고 빗방울은 피한다.
  - goal개 음식을 모으면 승리, time_limit 초과 시 실패.

[입력] (EventManager.minigame_push_event → handle_event)
  - 키보드: ←→ / A D
  - 원터치: 화면 좌·우 반쪽 (MOUSEBUTTONDOWN/UP)

[엔진 연동] engine.EventManager + main.py 루프
  - MINIGAME_PLAY 스텝 → minigames.create_session("raindodge", …)
  - 매 프레임: tick_minigame(dt) / draw_minigame(surf, get_ui_font)
  - 종료: session.done == True → _finish_minigame → save 플래그 반영

[에셋] (추후)
  assets/minigames/raindodge/ — PNG 없으면 도형으로 그린다.
  경로 헬퍼: minigames.minigame_asset("raindodge", "images", …)
"""

from __future__ import annotations

import random
import time
from typing import Callable, Optional

import pygame


class RainDodgeSession:
    """
    미니게임 세션 — engine.EventManager가 기대하는 공통 인터페이스.

    필수 멤버/메서드:
      handle_event, tick, draw, done(property), result
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        goal: int = 5,
        time_limit: float = 45.0,
        save_data: Optional[dict] = None,
    ):
        self.w = max(160, int(width))
        self.h = max(120, int(height))
        self.goal = max(1, int(goal))
        self.time_limit = max(5.0, float(time_limit))
        self.save_data = dict(save_data or {})

        # 플레이어(받기 상자) — 좌우 이동
        self.player_w = max(28, self.w // 9)
        self.player_h = max(14, self.h // 18)
        self.player_x = float(self.w * 0.5)
        self.move_speed = max(120.0, self.w * 0.55)

        self.caught = 0
        self.score = 0
        self.misses = 0
        self.elapsed = 0.0
        self.spawn_cd = 0.35
        self.falling: list[dict] = []

        self.game_over = False
        self.won = False
        self._game_over_at = 0.0
        self.result_hold_sec = 1.35

        self._move_left = False
        self._move_right = False
        self._rng = random.Random()

    # --- engine: 종료 판정 (승패 화면 잠시 유지 후 done=True) ---

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
        elif event.type == pygame.KEYUP:
            if event.key in (pygame.K_LEFT, pygame.K_a):
                self._move_left = False
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                self._move_right = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            try:
                mx = float(event.pos[0])
            except (TypeError, ValueError, AttributeError):
                return
            if mx < self.w * 0.5:
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

        dx = 0.0
        if self._move_left:
            dx -= self.move_speed * dt
        if self._move_right:
            dx += self.move_speed * dt
        half = self.player_w * 0.5 + 4.0
        self.player_x = max(half, min(self.w - half, self.player_x + dx))

        self.spawn_cd -= dt
        if self.spawn_cd <= 0.0:
            self._spawn_drop()
            base = 0.55 - min(0.25, self.elapsed * 0.004)
            self.spawn_cd = max(0.22, base + self._rng.uniform(-0.08, 0.12))

        floor_y = float(self.h - self.player_h - 8)
        catch_top = floor_y - 6.0
        catch_l = self.player_x - self.player_w * 0.42
        catch_r = self.player_x + self.player_w * 0.42

        alive = []
        for it in self.falling:
            it["y"] += it["vy"] * dt
            r = it["r"]
            if it["y"] - r > self.h + 8:
                if it["is_food"]:
                    self.misses += 1
                continue
            if it["y"] + r >= catch_top and catch_l <= it["x"] <= catch_r:
                if it["is_food"]:
                    self.caught += 1
                    self.score += 10
                else:
                    self.score = max(0, self.score - 5)
                    self.misses += 1
                continue
            alive.append(it)
        self.falling = alive

        if self.caught >= self.goal:
            self._set_game_over(True)
            self.score += max(0, int((self.time_limit - self.elapsed) * 2))
        elif self.elapsed >= self.time_limit:
            self._set_game_over(False)

    def _set_game_over(self, won: bool) -> None:
        self.game_over = True
        self.won = bool(won)
        self._game_over_at = time.monotonic()

    def _spawn_drop(self) -> None:
        margin = 16.0
        x = self._rng.uniform(margin, max(margin + 1, self.w - margin))
        is_food = self._rng.random() > 0.22
        r = max(5.0, min(11.0, self.w / 48.0 + self._rng.uniform(-1.5, 2.0)))
        vy = self._rng.uniform(self.h * 0.38, self.h * 0.62)
        self.falling.append({"x": x, "y": -r, "vy": vy, "r": r, "is_food": is_food})

    def result(self) -> dict:
        """engine._finish_minigame 이 읽는 결과 dict."""
        return {
            "won": bool(self.won),
            "score": int(self.score),
            "caught": int(self.caught),
            "misses": int(self.misses),
            "elapsed": float(self.elapsed),
        }

    # --- 렌더 (전체 화면 덮개 — main draw_minigame 경로) ---

    def draw(self, surf: pygame.Surface, font_fn: Callable[[int], pygame.font.Font]) -> None:
        w, h = self.w, self.h
        surf.fill((32, 52, 72))

        # 하늘 → 땅 그라데이션 느낌
        for i in range(0, h, max(8, h // 20)):
            shade = 40 + (i % 20)
            surf.fill((shade, shade + 28, shade + 48), (0, i, w, max(4, h // 24)))

        title_font = font_fn(max(10, min(22, w // 22)))
        hud_font = font_fn(max(9, min(18, w // 28)))
        small_font = font_fn(max(8, min(14, w // 32)))

        remain = max(0.0, self.time_limit - self.elapsed)
        surf.blit(title_font.render("비 피하고 음식 받기", True, (210, 235, 255)), (8, 6))
        surf.blit(hud_font.render(f"{self.caught}/{self.goal}", True, (255, 255, 180)), (w - 56, 8))
        surf.blit(hud_font.render(f"{remain:0.1f}s", True, (180, 220, 255)), (w // 2 - 24, 8))
        surf.blit(small_font.render(f"점수 {self.score}", True, (200, 200, 200)), (8, h - 18))

        for it in self.falling:
            if it["is_food"]:
                col = (100, 210, 90)
                inner = (50, 140, 45)
            else:
                col = (100, 160, 230)
                inner = (60, 110, 200)
            ix, iy, ir = int(it["x"]), int(it["y"]), int(it["r"])
            pygame.draw.circle(surf, col, (ix, iy), ir)
            pygame.draw.circle(surf, inner, (ix, iy), max(1, int(ir * 0.55)))

        floor_y = h - self.player_h - 8
        bx = int(self.player_x)
        pw, ph = int(self.player_w), int(self.player_h)
        pygame.draw.rect(surf, (120, 78, 42), (bx - pw // 2, floor_y, pw, ph), border_radius=3)
        pygame.draw.rect(surf, (160, 110, 58), (bx - pw // 2 + 2, floor_y + 2, pw - 4, ph - 5), border_radius=2)

        hint = "← →  또는  A D  /  화면 좌우 터치"
        surf.blit(small_font.render(hint, True, (170, 190, 210)), (8, h - 34))

        if self.game_over:
            overlay = pygame.Surface((w, h), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 140))
            surf.blit(overlay, (0, 0))
            msg = "성공!" if self.won else "시간 초과…"
            col = (140, 255, 160) if self.won else (255, 180, 140)
            tf = font_fn(max(14, min(28, w // 16)))
            img = tf.render(msg, True, col)
            surf.blit(img, (w // 2 - img.get_width() // 2, h // 2 - 20))

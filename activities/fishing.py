"""
activities.fishing — 호숫가 필드 낚시.

[물고기 그림자]
  - 수면 위로 랜덤 등장 → 제자리에서 방향 2~3회 변경하며 이동 → 5~15초 후 퇴장
  - 희귀할수록 수면 체류 시간 짧음 (data.py fish_types)

[찌]
  - 짧게/길게 던지기 (cast_near/far, 기본 2배 거리)
  - 입질 전 탭 → 줄·찌 회수
  - 그림자가 찌 근처 → 랜덤 입질 → 찌 좌우 흔들림 → 빠른 탭으로 걸기
  - 놓치면 물고기가 찌를 떼고 유유히 사라짐
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Tuple

import pygame

from data import FISHING_PONDS
from .base import BaseFieldActivity, FieldDrawContext

ST_ARMED = "armed"
ST_CHARGING = "charging"
ST_CASTING = "casting"
ST_FLOAT = "float"
ST_BITE_SHAKE = "bite_shake"
ST_RETRIEVE = "retrieve"
ST_REELING = "reeling"
ST_STRUGGLE = "struggle"
ST_SUCCESS = "success"
ST_FAIL = "fail"
ST_QUIT = "quit"

# 그림자 생애 주기
SH_HIDDEN = "hidden"
SH_ACTIVE = "active"
SH_LEAVING = "leaving"


def _lerp(a: float, b: float, t: float) -> float:
    return float(a) + (float(b) - float(a)) * float(t)


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(float(bx) - float(ax), float(by) - float(ay))


def _random_in_rect(rng: random.Random, rect: list) -> Tuple[float, float]:
    x, y, w, h = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
    return x + rng.uniform(0.1, 0.9) * w, y + rng.uniform(0.2, 0.85) * h


def _clamp_in_rect(x: float, y: float, rect: list, margin: float = 6.0) -> Tuple[float, float]:
    wx, wy, ww, wh = [float(v) for v in rect]
    m = float(margin)
    return (
        max(wx + m, min(wx + ww - m, float(x))),
        max(wy + m, min(wy + wh - m, float(y))),
    )


def _world_to_screen(ctx: FieldDrawContext, wx: float, wy: float) -> Tuple[int, int]:
    dx = (float(wx) - float(ctx.cam_draw_x)) * float(ctx.z)
    dy = (float(wy) - float(ctx.cam_draw_y)) * float(ctx.z)
    if callable(ctx.y_transform):
        try:
            dy = float(ctx.y_transform(dy))
        except Exception:
            pass
    if callable(ctx.x_offset_fn):
        try:
            dx = float(dx) + float(ctx.x_offset_fn(float(dy)))
        except Exception:
            pass
    return int(round(dx)), int(round(dy))


class _FishShadow:
    """수면 그림자 — 등장·방향 전환·퇴장 AI."""

    __slots__ = (
        "x",
        "y",
        "heading",
        "speed",
        "size",
        "phase",
        "life",
        "lifecycle",
        "age",
        "lifetime",
        "turns_left",
        "turn_timer",
        "respawn_timer",
        "fish_id",
        "rarity",
        "bite_chance",
        "leave_speed",
        "alpha",
    )

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0
        self.speed = 12.0
        self.size = 1.0
        self.phase = 0.0
        self.life = SH_HIDDEN
        self.age = 0.0
        self.lifetime = 10.0
        self.turns_left = 0
        self.turn_timer = 0.0
        self.respawn_timer = 0.0
        self.fish_id = "?"
        self.rarity = "common"
        self.bite_chance = 0.5
        self.leave_speed = 8.0
        self.alpha = 0.0

    @property
    def visible(self) -> bool:
        return self.life in (SH_ACTIVE, SH_LEAVING) and self.alpha > 0.02

    def reset_hidden(self, rng: random.Random, delay: float) -> None:
        self.life = SH_HIDDEN
        self.age = 0.0
        self.alpha = 0.0
        self.respawn_timer = max(0.5, float(delay))
        self.turns_left = 0

    def surface_at(self, x: float, y: float, fish: dict, rng: random.Random) -> None:
        self.x, self.y = float(x), float(y)
        self.fish_id = str(fish.get("id") or "?")
        self.rarity = str(fish.get("rarity") or "common")
        self.bite_chance = float(fish.get("bite_chance", 0.5))
        tmin = float(fish.get("surface_min", 8.0))
        tmax = float(fish.get("surface_max", 14.0))
        self.lifetime = rng.uniform(tmin, tmax)
        self.age = 0.0
        self.life = SH_ACTIVE
        self.alpha = 0.0
        self.heading = rng.uniform(0.0, math.pi * 2.0)
        self.speed = rng.uniform(10.0, 22.0)
        self.size = rng.uniform(0.8, 1.3)
        if self.rarity == "rare":
            self.size *= 1.15
        elif self.rarity == "uncommon":
            self.size *= 1.05
        self.turns_left = rng.randint(2, 3)
        self.turn_timer = rng.uniform(0.6, 1.4)
        self.phase = rng.uniform(0.0, math.pi * 2.0)

    def begin_leave(self, rng: random.Random) -> None:
        self.life = SH_LEAVING
        self.leave_speed = rng.uniform(6.0, 14.0)
        # 아래(깊이)로 천천히 사라지는 느낌
        self.heading = rng.uniform(math.pi * 0.35, math.pi * 0.65)

    def tick(self, dt: float, water_rect: list, rng: random.Random) -> None:
        if self.life == SH_HIDDEN:
            self.respawn_timer -= dt
            return

        self.phase += dt * 2.5

        if self.life == SH_ACTIVE:
            self.age += dt
            # 페이드 인
            self.alpha = min(1.0, self.alpha + dt * 2.2)
            self.turn_timer -= dt
            if self.turn_timer <= 0.0 and self.turns_left > 0:
                self.turns_left -= 1
                self.heading = rng.uniform(0.0, math.pi * 2.0)
                self.speed = rng.uniform(8.0, 24.0)
                self.turn_timer = rng.uniform(0.7, 1.8)

            self.x += math.cos(self.heading) * self.speed * dt
            self.y += math.sin(self.heading) * self.speed * dt
            self.x, self.y = _clamp_in_rect(self.x, self.y, water_rect)

            if self.age >= self.lifetime:
                self.begin_leave(rng)

        elif self.life == SH_LEAVING:
            self.age += dt
            self.alpha = max(0.0, self.alpha - dt * 0.55)
            self.x += math.cos(self.heading) * self.leave_speed * dt
            self.y += math.sin(self.heading) * self.leave_speed * dt * 0.35
            if self.alpha <= 0.02:
                self.reset_hidden(rng, rng.uniform(2.0, 6.0))


class FishingActivity(BaseFieldActivity):
    activity_id = "fishing"

    def __init__(self):
        self.state = ST_ARMED
        self.pond_id = ""
        self.pond: dict = {}
        self._rng = random.Random()
        self.water_rect = [0.0, 0.0, 1.0, 1.0]
        self._fish_table: List[dict] = []

        self.stand_xy = (0.0, 0.0)
        self.rod_tip = (0.0, 0.0)
        self.bobber_xy = (0.0, 0.0)
        self.fish_xy = (0.0, 0.0)
        self._shadows: List[_FishShadow] = []
        self._biting_shadow: Optional[_FishShadow] = None

        self._cast_from = (0.0, 0.0)
        self._cast_to = (0.0, 0.0)
        self._cast_t = 0.0
        self._cast_dur = 0.42
        self._retrieve_t = 0.0
        self._retrieve_dur = 0.32
        self._retrieve_from = (0.0, 0.0)
        self._retrieve_to = (0.0, 0.0)

        self._charge_start_ms = 0
        self._charge_power = 0.0
        self._bite_shake_left = 0.0
        self._bite_shake_phase = 0.0
        self._bobber_shake_x = 0.0
        self._shake_off_x = 0.0
        self._shake_off_y = 0.0
        self._struggle_shake_t = 0.0
        self._hook_start_dist = 80.0
        self._bite_near_shore = 0.0

        self._pull = 0.0
        self._tension = 0.0
        self._struggle_left = 0.0
        self._struggle_cooldown = 0.0
        self._last_tap_ms = 0
        self._msg = ""
        self._win_flag = "progress_fishing_win"
        self._won = False
        self._fail_reason = ""
        self._finish_hold = 0.0
        self._elapsed = 0.0

    def _pond_cfg(self, pond_id: str) -> Optional[dict]:
        return FISHING_PONDS.get((pond_id or "").strip())

    def _pond_f(self, key: str, default):
        try:
            v = self.pond.get(key)
            return default if v is None else v
        except Exception:
            return default

    def _near_shore_factor(self, wx: float, wy: float) -> float:
        """0=먼 물, 1=물가 가까이(짧은 캐스트·캐릭터 쪽). 입질 난이도(반항 빈도)에 사용."""
        sx, sy = self.stand_xy
        cast_far = max(1.0, float(self._pond_f("cast_far", 116.0)))
        depth = max(0.0, float(wy) - float(sy))
        ratio = depth / cast_far
        shore_cut = float(self._pond_f("near_shore_cast_ratio", 0.45))
        if ratio >= shore_cut:
            return 0.0
        return max(0.0, min(1.0, 1.0 - ratio / max(1e-6, shore_cut)))

    def _unit_away_from_stand(self, wx: float, wy: float) -> Tuple[float, float]:
        """캐릭터(stand)에서 멀어지는 단위 방향."""
        sx, sy = self.stand_xy
        dx, dy = float(wx) - float(sx), float(wy) - float(sy)
        d = math.hypot(dx, dy)
        if d < 1e-3:
            return 0.0, 1.0
        return dx / d, dy / d

    def _next_struggle_cooldown(self) -> float:
        lo = float(self._pond_f("struggle_cooldown_min", 0.8))
        hi = float(self._pond_f("struggle_cooldown_max", 1.4))
        cd = self._rng.uniform(lo, hi)
        bonus = float(self._pond_f("struggle_near_shore_freq", 0.55)) * float(
            self._bite_near_shore
        )
        return cd * max(0.22, 1.0 - bonus)

    def _struggle_duration(self) -> float:
        lo = float(self._pond_f("struggle_duration_min", 0.9))
        hi = float(self._pond_f("struggle_duration_max", 1.6))
        return self._rng.uniform(lo, hi)

    def _sync_hooked_positions(self, *, bobber_follow: float = 0.45) -> None:
        if self._biting_shadow:
            self._biting_shadow.x = self.fish_xy[0]
            self._biting_shadow.y = self.fish_xy[1]
        t = max(0.0, min(1.0, float(bobber_follow)))
        bx, by = self.bobber_xy
        self.bobber_xy = (
            _lerp(bx, self.fish_xy[0], t),
            _lerp(by, self.fish_xy[1], t),
        )

    def _pick_fish_type(self) -> dict:
        table = self._fish_table or [{"id": "물고기", "rarity": "common", "weight": 1,
                                       "surface_min": 8.0, "surface_max": 14.0, "bite_chance": 0.5}]
        weights = [max(0.1, float(f.get("weight", 1))) for f in table]
        return self._rng.choices(table, weights=weights, k=1)[0]

    def _init_shadow_pool(self) -> None:
        n = int(self.pond.get("max_shadows", 4) or 4)
        n = max(2, min(8, n))
        self._shadows = []
        for i in range(n):
            sh = _FishShadow()
            sh.reset_hidden(self._rng, self._rng.uniform(0.3, 2.5) + i * 0.8)
            self._shadows.append(sh)

    def _tick_shadow_spawner(self, dt: float) -> None:
        active_n = sum(1 for s in self._shadows if s.life == SH_ACTIVE)
        max_active = max(2, int(self.pond.get("max_shadows", 4)) - 1)
        for sh in self._shadows:
            sh.tick(dt, self.water_rect, self._rng)
            if sh.life == SH_HIDDEN and sh.respawn_timer <= 0.0 and active_n < max_active:
                fx, fy = _random_in_rect(self._rng, self.water_rect)
                sh.surface_at(fx, fy, self._pick_fish_type(), self._rng)
                active_n += 1

    def begin(self, player, **params) -> bool:
        pid = str(params.get("pond") or params.get("pond_id") or "jjangpu_water1").strip()
        spot = self._pond_cfg(pid)
        if spot is None:
            print(f"[fishing] unknown pond: {pid}")
            return False
        self.pond_id = pid
        self.pond = dict(spot)
        self._rng = random.Random()
        self._fish_table = list(spot.get("fish_types") or [])
        self._win_flag = str(params.get("win_flag") or "progress_fishing_win").strip()
        self.water_rect = list(spot.get("water_rect") or [0, 0, 100, 50])

        sx, sy = float(spot["stand"][0]), float(spot["stand"][1])
        self.stand_xy = (sx, sy)
        self.rod_tip = (sx + 6.0, sy - 16.0)
        self.bobber_xy = (sx, sy)
        self._init_shadow_pool()
        self._biting_shadow = None

        face = str(spot.get("face") or "down")
        try:
            player.stop_moving()
            player.pos[0], player.pos[1] = sx, sy
            player.target = [sx, sy]
            player.path = []
            player.direction = face
        except Exception:
            pass
        try:
            player.play_anim("idle", duration_ms=None, loop=True, release="stop")
        except Exception:
            pass

        await_tap = params.get("await_tap", True)
        if isinstance(await_tap, str):
            await_tap = await_tap.strip().lower() not in ("0", "false", "no", "off")
        else:
            await_tap = bool(await_tap)

        self.state = ST_ARMED if await_tap else ST_CHARGING
        self._pull = 0.0
        self._tension = 0.0
        self._won = False
        self._fail_reason = ""
        self._finish_hold = 0.0
        self._elapsed = 0.0
        self._msg = "화면을 눌러 낚시를 시작" if await_tap else "짧게: 가까이 · 길게: 멀리"
        return True

    def cancel(self) -> None:
        if self.state in (ST_SUCCESS, ST_FAIL, ST_QUIT):
            return
        self.state = ST_QUIT
        self._won = False
        self._finish_hold = 0.05
        self._msg = ""

    @property
    def is_active(self) -> bool:
        return self.state not in (ST_SUCCESS, ST_FAIL, ST_QUIT)

    @property
    def is_finished(self) -> bool:
        return self.state in (ST_SUCCESS, ST_FAIL, ST_QUIT) and self._finish_hold <= 0.0

    def blocks_field_move(self) -> bool:
        return self.is_active

    def blocks_zone_confirm(self) -> bool:
        return self.is_active

    def _charge_power_from_ms(self, held_ms: int) -> float:
        return max(0.0, min(1.0, (float(held_ms) - 70.0) / 780.0))

    def _engage_fishing(self) -> None:
        self.state = ST_CHARGING
        self._msg = "짧게: 가까이 · 길게: 멀리"

    def on_pointer_down(self, screen_xy, world_xy, now_ms: int) -> bool:
        if self.state == ST_ARMED:
            self._engage_fishing()
            self._charge_start_ms = int(now_ms)
            self._msg = "던질 힘…"
            return True
        if self.state == ST_CHARGING:
            if self._charge_start_ms <= 0:
                self._charge_start_ms = int(now_ms)
            return True
        if self.state == ST_FLOAT:
            self._start_retrieve()
            return True
        if self.state == ST_BITE_SHAKE:
            self._on_hook_set()
            return True
        if self.state == ST_REELING:
            if int(now_ms) - int(self._last_tap_ms) >= 42:
                self._last_tap_ms = int(now_ms)
                self._on_reel_tap()
            return True
        if self.state == ST_STRUGGLE:
            pen = float(self._pond_f("tension_tap_penalty_struggle", 0.2))
            self._tension = min(float(self._pond_f("tension_fail", 1.0)), float(self._tension) + pen)
            self._msg = "몸부림! 멈춰!"
            if float(self._tension) >= float(self._pond_f("tension_fail", 1.0)):
                self._set_fail("물고기가 도망갔다…")
            return True
        return True

    def on_pointer_up(self, now_ms: int) -> bool:
        if self.state == ST_CHARGING:
            held = max(0, int(now_ms) - int(self._charge_start_ms))
            self._charge_power = self._charge_power_from_ms(held)
            self._start_cast()
            return True
        return self.is_active

    def _cast_point(self, power: float) -> Tuple[float, float]:
        wx, wy, ww, wh = [float(v) for v in self.water_rect]
        near = float(self.pond.get("cast_near", 36))
        far = float(self.pond.get("cast_far", 116))
        sx, sy = self.stand_xy
        ty = sy + _lerp(near, far, power)
        ty = max(wy + 6.0, min(wy + wh - 6.0, ty))
        tx = sx + self._rng.uniform(-ww * 0.32, ww * 0.32)
        tx = max(wx + 8.0, min(wx + ww - 8.0, tx))
        return tx, ty

    def _start_cast(self) -> None:
        tx, ty = self._cast_point(self._charge_power)
        self._cast_from = self.rod_tip
        self._cast_to = (tx, ty)
        self.bobber_xy = self._cast_from
        self._cast_t = 0.0
        self._biting_shadow = None
        self.state = ST_CASTING
        self._msg = "찌를 던지는 중…"

    def _start_retrieve(self) -> None:
        self._retrieve_from = (float(self.bobber_xy[0]), float(self.bobber_xy[1]))
        self._retrieve_to = self.rod_tip
        self._retrieve_t = 0.0
        self._biting_shadow = None
        self.state = ST_RETRIEVE
        self._msg = "찌를 걷는 중…"

    def _on_hook_set(self) -> None:
        self.state = ST_REELING
        self._pull = 0.12
        self._tension = 0.1
        self._struggle_cooldown = self._next_struggle_cooldown()
        self._bobber_shake_x = 0.0
        self._shake_off_x = 0.0
        self._shake_off_y = 0.0
        if self._biting_shadow:
            self.fish_xy = (self._biting_shadow.x, self._biting_shadow.y)
        sx, sy = self.stand_xy
        self._hook_start_dist = max(
            24.0, _dist(self.fish_xy[0], self.fish_xy[1], sx, sy)
        )
        self._msg = "걸었다! 빠르게 연타!"

    def _fish_release_and_leave(self) -> None:
        sh = self._biting_shadow
        if sh is not None:
            sh.begin_leave(self._rng)
        self._biting_shadow = None
        self._bobber_shake_x = 0.0
        self.state = ST_FLOAT
        self._msg = "놓쳤다… 다시 기다려"

    def _on_reel_tap(self) -> None:
        pull_gain = float(self._pond_f("reel_tap_pull_gain", 0.058))
        self._pull = min(1.0, float(self._pull) + pull_gain)
        relief = float(self._pond_f("tension_tap_relief", 0.035))
        self._tension = max(0.0, float(self._tension) - relief)
        sx, sy = self.stand_xy
        dx, dy = sx - self.fish_xy[0], sy - self.fish_xy[1]
        d = math.hypot(dx, dy)
        if d > 1e-3:
            step_base = float(self._pond_f("reel_tap_step_base", 5.5))
            step_pull = float(self._pond_f("reel_tap_step_pull", 11.0))
            step = step_base + step_pull * float(self._pull)
            self.fish_xy = (self.fish_xy[0] + dx / d * step, self.fish_xy[1] + dy / d * step)
        self._sync_hooked_positions(bobber_follow=0.4)
        self._msg = "당겨!"
        if _dist(self.fish_xy[0], self.fish_xy[1], sx, sy) <= float(
            self._pond_f("success_dist", 24)
        ):
            self._set_success()

    def _set_success(self) -> None:
        self.state = ST_SUCCESS
        self._won = True
        self._finish_hold = 1.4
        self._msg = "잡았다!"

    def _set_fail(self, reason: str) -> None:
        self.state = ST_FAIL
        self._won = False
        self._fail_reason = reason
        self._finish_hold = 1.1
        self._msg = reason

    def _try_bite_at_bobber(self) -> None:
        bx, by = self.bobber_xy
        hook_r = float(self.pond.get("hook_radius", 20))
        candidates = [
            sh for sh in self._shadows
            if sh.life == SH_ACTIVE and sh.visible and _dist(sh.x, sh.y, bx, by) <= hook_r
        ]
        if not candidates:
            return
        sh = min(candidates, key=lambda s: _dist(s.x, s.y, bx, by))
        if self._rng.random() > float(sh.bite_chance):
            return
        self._biting_shadow = sh
        self.fish_xy = (sh.x, sh.y)
        bx, by = self.bobber_xy
        self._bite_near_shore = self._near_shore_factor(bx, by)
        self.state = ST_BITE_SHAKE
        self._bite_shake_left = float(self.pond.get("bite_shake_sec", 0.95))
        self._bite_shake_phase = 0.0
        self._msg = "입질! 빠르게 탭!"

    def tick(self, dt_sec: float, player, now_ms: int) -> None:
        dt = max(0.0, min(0.1, float(dt_sec)))
        self._elapsed += dt

        if self._finish_hold > 0.0:
            self._finish_hold -= dt
            if self.state not in (ST_CASTING, ST_RETRIEVE):
                self._tick_shadow_spawner(dt)
            return

        # 그림자 AI는 낚시 중 항상 동작 (armed 포함)
        if self.state != ST_CASTING:
            self._tick_shadow_spawner(dt)

        if self.state == ST_ARMED:
            return

        if self.state == ST_CASTING:
            self._cast_t += dt
            t = min(1.0, self._cast_t / float(self._cast_dur))
            t = t * t * (3.0 - 2.0 * t)
            self.bobber_xy = (
                _lerp(self._cast_from[0], self._cast_to[0], t),
                _lerp(self._cast_from[1], self._cast_to[1], t),
            )
            if t >= 1.0:
                self.state = ST_FLOAT
                self._msg = "물고기를 기다려… (탭: 찌 회수)"

        elif self.state == ST_RETRIEVE:
            self._retrieve_t += dt
            t = min(1.0, self._retrieve_t / float(self._retrieve_dur))
            t = t * t * (3.0 - 2.0 * t)
            fx, fy = self._retrieve_from
            tx, ty = self._retrieve_to
            self.bobber_xy = (_lerp(fx, tx, t), _lerp(fy, ty, t))
            if t >= 1.0:
                self.bobber_xy = self._retrieve_to
                self.state = ST_CHARGING
                self._charge_start_ms = 0
                self._msg = "짧게: 가까이 · 길게: 멀리"

        elif self.state == ST_FLOAT:
            self._try_bite_at_bobber()

        elif self.state == ST_BITE_SHAKE:
            self._bite_shake_left -= dt
            self._bite_shake_phase += dt * 22.0
            self._bobber_shake_x = math.sin(self._bite_shake_phase) * 7.0
            if self._biting_shadow:
                self._biting_shadow.x = self.bobber_xy[0]
                self._biting_shadow.y = self.bobber_xy[1] + 4.0
                self.fish_xy = (self._biting_shadow.x, self._biting_shadow.y)
            if self._bite_shake_left <= 0.0:
                self._fish_release_and_leave()

        elif self.state == ST_REELING:
            self._shake_off_x = 0.0
            self._shake_off_y = 0.0
            t_decay = float(self._pond_f("tension_decay_reel", 0.07))
            self._tension = max(0.0, float(self._tension) - dt * t_decay)
            self._struggle_cooldown -= dt
            pull_decay = float(self._pond_f("reel_pull_decay", 0.028))
            self._pull = max(0.0, float(self._pull) - dt * pull_decay)
            sx, sy = self.stand_xy
            drift_back = float(self._pond_f("reel_fish_drift_back", 0.012))
            self.fish_xy = (
                _lerp(self.fish_xy[0], sx, dt * drift_back),
                _lerp(self.fish_xy[1], sy, dt * drift_back * 0.85),
            )
            self._sync_hooked_positions(bobber_follow=0.35)
            if self._struggle_cooldown <= 0.0:
                self.state = ST_STRUGGLE
                self._struggle_left = self._struggle_duration()
                self._struggle_shake_t = 0.0
                self._msg = "몸부림! 멈춰!"
            t_fail = float(self._pond_f("tension_fail", 1.0))
            if float(self._tension) >= t_fail:
                self._set_fail("줄이 끊겼다…")

        elif self.state == ST_STRUGGLE:
            self._struggle_left -= dt
            self._struggle_shake_t += dt
            tsh = self._struggle_shake_t
            self._shake_off_x = (
                math.sin(tsh * 41.0) * 4.5 + math.cos(tsh * 53.0) * 2.5
            )
            self._shake_off_y = (
                math.sin(tsh * 37.0) * 4.0 + math.cos(tsh * 49.0) * 2.0
            )
            drift = float(self._pond_f("struggle_drift_speed", 14.0)) * dt
            ax, ay = self._unit_away_from_stand(self.fish_xy[0], self.fish_xy[1])
            nx = self.fish_xy[0] + ax * drift
            ny = self.fish_xy[1] + ay * drift
            nx, ny = _clamp_in_rect(nx, ny, self.water_rect, margin=4.0)
            self.fish_xy = (nx, ny)
            self._sync_hooked_positions(bobber_follow=0.58)
            t_build = float(self._pond_f("tension_build_struggle", 0.1))
            t_fail = float(self._pond_f("tension_fail", 1.0))
            self._tension = min(t_fail, float(self._tension) + dt * t_build)
            if self._struggle_left <= 0.0:
                self.state = ST_REELING
                self._struggle_cooldown = self._next_struggle_cooldown()
                self._tension = max(0.0, float(self._tension) - 0.22)
                self._shake_off_x = 0.0
                self._shake_off_y = 0.0
                self._msg = "다시 연타!"
            if float(self._tension) >= t_fail:
                self._set_fail("물고기가 도망갔다…")

    def result(self) -> Dict[str, Any]:
        return {
            "activity": self.activity_id,
            "won": bool(self._won),
            "quit": self.state == ST_QUIT,
            "pond": self.pond_id,
            "win_flag": self._win_flag,
            "win_value": 1,
            "reason": self._fail_reason,
            "elapsed": float(self._elapsed),
        }

    def _cast_charge_power_now(self) -> float:
        if self.state != ST_CHARGING or self._charge_start_ms <= 0:
            return 0.0
        held = max(0, pygame.time.get_ticks() - int(self._charge_start_ms))
        return self._charge_power_from_ms(held)

    def _reel_line_color(self) -> Tuple[int, int, int]:
        """당길수록 파랑 → 빨강 (게이지 대신 줄 색으로 표현)."""
        sx, sy = self.stand_xy
        d = _dist(self.fish_xy[0], self.fish_xy[1], sx, sy)
        ref = max(24.0, float(self._hook_start_dist))
        t = max(0.0, min(1.0, 1.0 - float(d) / ref))
        if self.state == ST_STRUGGLE:
            t = max(t, 0.55 + 0.35 * abs(math.sin(self._struggle_shake_t * 12.0)))
        return (
            int(_lerp(88, 218, t)),
            int(_lerp(158, 58, t)),
            int(_lerp(228, 52, t)),
        )

    def _bobber_draw_offset(self) -> Tuple[float, float]:
        ox, oy = 0.0, 0.0
        if self.state == ST_BITE_SHAKE:
            ox += float(self._bobber_shake_x)
        if self.state == ST_STRUGGLE:
            ox += float(self._shake_off_x)
            oy += float(self._shake_off_y)
        return ox, oy

    def _shadow_draw_offset(self, sh: _FishShadow) -> Tuple[float, float]:
        if sh is not self._biting_shadow:
            return 0.0, 0.0
        if self.state == ST_STRUGGLE:
            return float(self._shake_off_x), float(self._shake_off_y)
        if self.state == ST_BITE_SHAKE:
            return float(self._bobber_shake_x), 0.0
        return 0.0, 0.0

    def _draw_cast_gauge(self, ctx: FieldDrawContext, power: float) -> None:
        """던지기 충전 — 화면 오른쪽 세로 게이지 (아래→위)."""
        surf = ctx.surf
        sw, sh = surf.get_width(), surf.get_height()
        bar_w = max(8, min(14, sw // 28))
        bar_h = max(48, min(88, sh - 56))
        x = sw - bar_w - 14
        y = (sh - bar_h) // 2
        pygame.draw.rect(surf, (38, 48, 62), (x, y, bar_w, bar_h), border_radius=3)
        pygame.draw.rect(surf, (70, 88, 108), (x, y, bar_w, bar_h), 1, border_radius=3)
        p = max(0.0, min(1.0, float(power)))
        fill_h = max(0, int(round(bar_h * p)))
        if fill_h > 0:
            fy = y + bar_h - fill_h
            pygame.draw.rect(
                surf, (118, 188, 238), (x + 2, fy, bar_w - 4, fill_h), border_radius=2
            )

    def _draw_shadow(
        self,
        ctx: FieldDrawContext,
        sh: _FishShadow,
        *,
        highlight: bool = False,
        off_x: float = 0.0,
        off_y: float = 0.0,
    ) -> None:
        if not sh.visible:
            return
        sx, sy = _world_to_screen(ctx, sh.x + off_x, sh.y + off_y)
        wob = int(math.sin(sh.phase * 2.2) * 2.0)
        rw = int(14 * sh.size)
        rh = max(4, int(5 * sh.size))
        if sh.rarity == "rare":
            base = (70, 95, 130)
        elif sh.rarity == "uncommon":
            base = (60, 85, 110)
        else:
            base = (50, 72, 92)
        if highlight:
            base = (min(255, base[0] + 25), min(255, base[1] + 25), min(255, base[2] + 25))
        al = int(max(0, min(255, sh.alpha * 255)))
        if al <= 0:
            return
        col = (*base, al)
        tmp = pygame.Surface((rw + 2, rh + 2), pygame.SRCALPHA)
        pygame.draw.ellipse(tmp, col, (1, 1 + wob, rw, rh))
        ctx.surf.blit(tmp, (sx - rw // 2, sy - rh // 2))

    def draw(self, ctx: FieldDrawContext) -> None:
        surf = ctx.surf
        rsx, rsy = _world_to_screen(ctx, *self.rod_tip)

        for sh in self._shadows:
            hl = sh is self._biting_shadow and self.state in (
                ST_BITE_SHAKE, ST_REELING, ST_STRUGGLE,
            )
            sox, soy = self._shadow_draw_offset(sh)
            self._draw_shadow(ctx, sh, highlight=hl, off_x=sox, off_y=soy)

        show_line = self.state not in (ST_ARMED, ST_CHARGING)
        if show_line:
            bx_w, by_w = self.bobber_xy
            bdx, bdy = self._bobber_draw_offset()
            bx_w += bdx
            by_w += bdy
            bx, by = _world_to_screen(ctx, bx_w, by_w)
            if self.state in (ST_REELING, ST_STRUGGLE):
                line_col = self._reel_line_color()
                line_w = 2
            elif self.state == ST_BITE_SHAKE:
                line_col = (200, 120, 100)
                line_w = 1
            else:
                line_col = (200, 205, 215)
                line_w = 1
            pygame.draw.line(surf, line_col, (rsx, rsy), (bx, by), line_w)
            bob_r = 4
            if self.state == ST_BITE_SHAKE:
                bob_r = 5 + int(abs(math.sin(self._bite_shake_phase)) * 2)
            elif self.state == ST_STRUGGLE:
                bob_r = 5
            bob_col = (240, 80, 70) if self.state in (ST_BITE_SHAKE, ST_REELING, ST_STRUGGLE) else (248, 248, 248)
            pygame.draw.circle(surf, bob_col, (bx, by), bob_r)

        if self.state in (ST_REELING, ST_STRUGGLE, ST_SUCCESS):
            fx, fy = self.fish_xy
            if self.state == ST_STRUGGLE:
                fx += self._shake_off_x
                fy += self._shake_off_y
            fx, fy = _world_to_screen(ctx, fx, fy)
            wob = int(math.sin(self._elapsed * 8.0) * 2.0)
            fcol = (255, 130, 90) if self.state == ST_STRUGGLE else (100, 170, 230)
            pygame.draw.ellipse(surf, fcol, (fx - 11, fy - 5 + wob, 22, 10))

        hud = ctx.font_fn(max(9, min(14, surf.get_width() // 28)))
        if self.state == ST_CHARGING:
            self._draw_cast_gauge(ctx, self._cast_charge_power_now())

        tip = hud.render(self._msg, True, (248, 252, 255))
        surf.blit(tip, (8, surf.get_height() - 15))

        if self.state == ST_SUCCESS:
            big = ctx.font_fn(max(12, min(18, surf.get_width() // 20)))
            t = big.render("낚시 성공!", True, (140, 255, 170))
            surf.blit(t, (surf.get_width() // 2 - t.get_width() // 2, 10))

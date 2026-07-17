"""
activities.racing — 옆시야(좌→우) 레이스 필드 미니게임 (SNES 마리오카트식 Mode7).

[시야]
  - 카메라는 플레이어 실제 진행(heading)의 오른쪽에서 비춘다 (경로 접선 스냅 금지).
  - 코너에서도 heading/카메라가 서서히 돌며, 화면상 대체로 좌→우로 달린다.
  - 트랙 차선 A(상)/B(중)/C(하). 화면 왼쪽 ▲▼ 버튼으로 한 칸씩 이동
    (에셋 없으면 자동 생성, 있으면 assets/images/ui/racing/<anim>/ 애니 세트).

[아이템·날씨·슬립스트림]
  - 경로 배치: normal / secret(??? 룰렛) / roulette(레인 순환) / summon(원거리 소환)
  - 날씨(맵별): 비=감속, 번개=잠깐 정지. clean_zones 구간은 랜덤 무효.
  - 슬립스트림: 최고속 90%↑ 앞차 뒤에 들어가면 가속. 추돌 시 앞 전진·뒤 감속.

[경로]
  - 월드 좌표 폴리라인(닫힌 루프 가능). 마스크 샘플 안 함.
  - 자동 주행: heading 방향으로 관성 이동 + 앞 경로점을 chase 하며 선회.
  - 경로에는 약한 인력만 (코너에서 밖으로 살짝 나가는 느낌).

[연동]
  DEV_CMD: start_racing / stop_racing / return_from_racing
  OVERLAY / 화면 UI: 경기 중지 → stop_racing
  data.py RACING_DEFAULTS + world_data[map].racing
"""

from __future__ import annotations

import math
import os
import random
from typing import Any, Dict, List, Optional, Tuple

import pygame

from data import (
    CHAR_ASSETS,
    CONFIG,
    RACING_DEFAULTS,
    RACING_ITEM_TYPES,
    RACING_LANE_LETTERS,
    RACING_MYSTERY_EFFECT_POOL,
    get_activity_ui,
)
from field_runtime import scale_ui_text_px
from render_align import blit_topleft_bottom_center
from char_behavior import get_char_ui_name

from .base import BaseFieldActivity, FieldDrawContext

ST_MENU = "menu"
ST_PICK_CHAR = "pick_char"
ST_COUNTDOWN = "countdown"
ST_RACE = "race"
ST_FINISH = "finish"
ST_QUIT = "quit"

LANE_UPPER = -1.0
LANE_LOWER = 1.0
LANE_CENTER = 0.0
# A(상) → B(중) → C(하) 한 칸씩 이동용
_LANE_STEP_ORDER = (LANE_UPPER, LANE_CENTER, LANE_LOWER)


def _lane_letter_to_offset(letter) -> float:
    key = str(letter or "B").strip().upper()
    if key in RACING_LANE_LETTERS:
        return float(RACING_LANE_LETTERS[key])
    try:
        v = float(letter)
        return max(-1.0, min(1.0, v))
    except (TypeError, ValueError):
        return 0.0


def _lane_offset_to_letter(offset: float) -> str:
    o = float(offset)
    if o < -0.33:
        return "A"
    if o > 0.33:
        return "C"
    return "B"


def _lane_offset_to_step_index(offset: float) -> int:
    """레인 오프셋 → 0=A, 1=B, 2=C."""
    letter = _lane_offset_to_letter(offset)
    if letter == "A":
        return 0
    if letter == "C":
        return 2
    return 1


def _make_arrow_button_surf(size: int, *, pointing_up: bool) -> pygame.Surface:
    """에셋 없을 때 쓰는 기본 화살표 버튼 (둥근 칩 + 삼각형)."""
    s = max(24, int(size))
    surf = pygame.Surface((s, s), pygame.SRCALPHA)
    pad = max(2, s // 12)
    body = pygame.Rect(pad, pad, s - pad * 2, s - pad * 2)
    try:
        pygame.draw.rect(surf, (48, 62, 92, 220), body, border_radius=max(4, s // 6))
        pygame.draw.rect(surf, (160, 200, 255, 255), body, max(1, s // 20), border_radius=max(4, s // 6))
    except TypeError:
        pygame.draw.rect(surf, (48, 62, 92, 220), body)
        pygame.draw.rect(surf, (160, 200, 255, 255), body, max(1, s // 20))
    cx, cy = s // 2, s // 2
    arm = max(6, s // 3)
    if pointing_up:
        pts = [(cx, cy - arm), (cx - arm, cy + arm // 2), (cx + arm, cy + arm // 2)]
    else:
        pts = [(cx, cy + arm), (cx - arm, cy - arm // 2), (cx + arm, cy - arm // 2)]
    pygame.draw.polygon(surf, (240, 248, 255, 255), pts)
    return surf


def _load_racing_hud_anim_frames(anim_name: str) -> List[pygame.Surface]:
    """
    레인 HUD 버튼 애니 세트 로드.
    우선순위:
      1) assets/images/ui/racing/<anim_name>/  (폴더 PNG 시퀀스)
      2) assets/images/ui/racing/<anim_name>_0.png … (번호 시퀀스)
    없으면 [] → 호출측에서 자동 생성 화살표 사용.
    """
    name = str(anim_name or "").strip().replace("\\", "/").strip("/")
    if not name or ".." in name:
        return []
    base_dir = os.path.join("assets", "images", "ui", "racing")
    folder = os.path.normpath(os.path.join(base_dir, name.replace("/", os.sep)))
    try:
        from engine import _load_anim_dir_cached, _load_numbered_ui_sequence

        frames = _load_anim_dir_cached(folder)
        if frames:
            return list(frames)
        seq = _load_numbered_ui_sequence(
            f"images/ui/racing/{name}", max_frames=32
        )
        if seq:
            return list(seq)
    except Exception:
        pass
    return []


class RaceLaneHudButton:
    """
    레이스 레인 이동 HUD 버튼.
    - frames 가 비면 자동 생성 화살표 1장.
    - 나중에 assets/images/ui/racing/<anim>/ 에 PNG 넣으면 그 세트로 교체.
    - press_t > 0 이면 눌림 피드백(약간 어둡게).
    """

    __slots__ = (
        "action",
        "pointing_up",
        "rect",
        "frames",
        "frame_i",
        "anim_t",
        "press_t",
        "anim_name",
    )

    def __init__(self, action: str, *, pointing_up: bool, anim_name: str = ""):
        self.action = str(action)
        self.pointing_up = bool(pointing_up)
        self.rect = pygame.Rect(0, 0, 32, 32)
        self.anim_name = str(anim_name or "")
        self.frames: List[pygame.Surface] = []
        self.frame_i = 0
        self.anim_t = 0.0
        self.press_t = 0.0
        self.reload_frames()

    def reload_frames(self) -> None:
        loaded = _load_racing_hud_anim_frames(self.anim_name)
        self.frames = list(loaded) if loaded else []
        self.frame_i = 0
        self.anim_t = 0.0

    def ensure_fallback(self, size: int) -> None:
        if self.frames:
            return
        self.frames = [_make_arrow_button_surf(size, pointing_up=self.pointing_up)]

    def layout(self, rect: pygame.Rect) -> None:
        self.rect = pygame.Rect(rect)

    def hit(self, screen_xy) -> bool:
        if not screen_xy:
            return False
        try:
            return bool(self.rect.collidepoint(int(screen_xy[0]), int(screen_xy[1])))
        except Exception:
            return False

    def press(self) -> None:
        self.press_t = 0.18

    def tick(self, dt: float, fps: float) -> None:
        dt = max(0.0, float(dt))
        if self.press_t > 0.0:
            self.press_t = max(0.0, self.press_t - dt)
        if len(self.frames) <= 1:
            return
        rate = max(1.0, float(fps) or 8.0)
        self.anim_t += dt
        step = 1.0 / rate
        while self.anim_t >= step:
            self.anim_t -= step
            self.frame_i = (self.frame_i + 1) % len(self.frames)

    def current_surf(self, draw_size: int) -> pygame.Surface:
        self.ensure_fallback(draw_size)
        img = self.frames[int(self.frame_i) % len(self.frames)]
        try:
            iw, ih = img.get_width(), img.get_height()
        except Exception:
            return img
        if iw == draw_size and ih == draw_size:
            out = img
        else:
            try:
                out = pygame.transform.smoothscale(img, (draw_size, draw_size))
            except Exception:
                out = pygame.transform.scale(img, (draw_size, draw_size))
        if self.press_t > 0.0:
            try:
                dim = out.copy()
                dim.fill((0, 0, 0, 90), special_flags=pygame.BLEND_RGBA_SUB)
                return dim
            except Exception:
                pass
        return out

    def draw(self, surf: pygame.Surface, draw_size: int) -> None:
        if surf is None:
            return
        img = self.current_surf(draw_size)
        try:
            dx = self.rect.centerx - img.get_width() // 2
            dy = self.rect.centery - img.get_height() // 2
            surf.blit(img, (dx, dy))
        except Exception:
            pass


_CHAR_PICK_COLS = 4
_CHAR_PICK_ROWS = 2

_ITEM_SURF_CACHE: Dict[str, pygame.Surface] = {}
_ITEM_SYMBOL_SURF_CACHE: Dict[Tuple[str, int], pygame.Surface] = {}

_ITEM_SYMBOLS = {
    "speed": "△",
    "slow": "▽",
    "secret": "?",
    "summon_pad": "☆",
    "swap": "↕",
    "roulette_pad": "↔",
}


def _placeholder_item_surf(color, size=24) -> pygame.Surface:
    """에셋 없을 때 쓰는 단색 네모(+테두리)."""
    sz = max(8, int(size))
    s = pygame.Surface((sz, sz), pygame.SRCALPHA)
    try:
        c = (int(color[0]), int(color[1]), int(color[2]))
    except Exception:
        c = (180, 180, 200)
    pygame.draw.rect(s, (*c, 230), (0, 0, sz, sz), border_radius=4)
    pygame.draw.rect(s, (255, 255, 255, 220), (0, 0, sz, sz), 2, border_radius=4)
    return s


def _load_racing_item_surface(asset_key: str, *, placeholder_color=(120, 200, 120)) -> pygame.Surface:
    """
    assets/images/object/<asset>.png 또는 동명 폴더 / OBJ_ASSETS path.
    없으면 단색 네모 (기존 오브젝트 폴백 패턴과 동일 계열).
    """
    key = str(asset_key or "").strip() or "_default"
    hit = _ITEM_SURF_CACHE.get(key)
    if hit is not None:
        return hit
    frames = None
    try:
        from data import OBJ_ASSETS
        from engine import _load_obj_asset_frames

        info = OBJ_ASSETS.get(key) or {}
        rel = str(info.get("path") or "").strip()
        if not rel:
            rel = f"images/object/{key}.png"
        frames = _load_obj_asset_frames(rel)
        if not frames:
            # 폴더만 있는 경우
            frames = _load_obj_asset_frames(f"images/object/{key}")
    except Exception:
        frames = None
    if frames:
        surf = frames[0]
        _ITEM_SURF_CACHE[key] = surf
        return surf
    surf = _placeholder_item_surf(placeholder_color)
    _ITEM_SURF_CACHE[key] = surf
    return surf


def _item_type_info(type_id: str) -> dict:
    tid = str(type_id or "speed").strip().lower() or "speed"
    base = dict(RACING_ITEM_TYPES.get(tid) or RACING_ITEM_TYPES.get("speed") or {})
    base["id"] = tid if tid in RACING_ITEM_TYPES else "speed"
    return base


class RaceItemPoint:
    """경로 위 아이템/발판 1개 (s+lane). kind 에 따라 동작이 다름."""

    __slots__ = (
        "s",
        "lane",
        "lane_letter",
        "type_id",
        "kind",
        "strength",
        "duration_sec",
        "asset",
        "taken",
        "wx",
        "wy",
        "surf",
        "roulette_t",
        "roulette_lane_i",
        "roulette_period",
        "inner_type_id",
    )

    def __init__(self, raw: dict, path: "RacePath", lane_w: float):
        kind = str(raw.get("kind") or "normal").strip().lower() or "normal"
        type_raw = raw.get("type") or raw.get("item") or "speed"
        if kind == "secret":
            type_raw = "secret"
        elif kind == "roulette":
            type_raw = raw.get("type") or "speed"
        elif kind == "summon":
            type_raw = "summon_pad"
        info = _item_type_info(type_raw)
        try:
            self.s = float(raw.get("s", 0.0) or 0.0)
        except (TypeError, ValueError):
            self.s = 0.0
        self.kind = kind
        self.lane_letter = str(raw.get("lane") or "B").strip().upper() or "B"
        if self.lane_letter not in ("A", "B", "C"):
            self.lane_letter = "B"
        self.lane = _lane_letter_to_offset(self.lane_letter)
        self.type_id = str(info.get("id") or "speed")
        self.inner_type_id = str(raw.get("inner_type") or self.type_id)
        try:
            self.strength = float(raw.get("strength", info.get("strength", 1.0)) or 1.0)
        except (TypeError, ValueError):
            self.strength = float(info.get("strength", 1.0) or 1.0)
        try:
            self.duration_sec = float(
                raw.get("duration_sec", info.get("duration_sec", 2.0)) or 2.0
            )
        except (TypeError, ValueError):
            self.duration_sec = 2.0
        self.asset = str(raw.get("asset") or info.get("asset") or "item_racing001").strip()
        self.taken = False
        self.wx = 0.0
        self.wy = 0.0
        try:
            self.roulette_period = float(
                raw.get("roulette_period_sec")
                or raw.get("roulette_period")
                or _cfg("roulette_lane_period_sec", 0.55)
                or 0.55
            )
        except (TypeError, ValueError):
            self.roulette_period = 0.55
        self.roulette_period = max(0.2, min(3.0, self.roulette_period))
        self.roulette_t = 0.0
        self.roulette_lane_i = _lane_offset_to_step_index(self.lane)
        col = info.get("placeholder_color") or (160, 160, 180)
        if kind == "secret":
            pad = _item_type_info("secret")
            self.surf = _load_racing_item_surface(
                str(raw.get("asset") or pad.get("asset") or "item_racing_secret"),
                placeholder_color=pad.get("placeholder_color") or col,
            )
        elif kind == "roulette":
            pad = _item_type_info("roulette_pad")
            self.surf = _load_racing_item_surface(
                str(raw.get("asset") or pad.get("asset") or "item_racing_roulette"),
                placeholder_color=pad.get("placeholder_color") or col,
            )
        elif kind == "summon":
            pad = _item_type_info("summon_pad")
            self.surf = _load_racing_item_surface(
                str(raw.get("asset") or pad.get("asset") or "item_racing_summon"),
                placeholder_color=pad.get("placeholder_color") or col,
            )
        else:
            self.surf = _load_racing_item_surface(self.asset, placeholder_color=col)
        self.recompute_world(path, lane_w)

    def tick_roulette(self, dt: float) -> None:
        """룰렛 발판: 레인 A→B→C→A 순환."""
        if self.taken or self.kind != "roulette":
            return
        self.roulette_t += max(0.0, float(dt))
        step = self.roulette_period / 3.0
        if step <= 1e-6:
            return
        while self.roulette_t >= step:
            self.roulette_t -= step
            self.roulette_lane_i = (self.roulette_lane_i + 1) % 3
            self.lane = float(_LANE_STEP_ORDER[self.roulette_lane_i])
            self.lane_letter = _lane_offset_to_letter(self.lane)

    def recompute_world(self, path: "RacePath", lane_w: float) -> None:
        if path is None:
            return
        x, y, tang, _ = path.sample(self.s)
        nx = -math.sin(tang)
        ny = math.cos(tang)
        lw = float(lane_w)
        self.wx = float(x) + nx * self.lane * lw
        self.wy = float(y) + ny * self.lane * lw

    def to_dict(self) -> dict:
        return {
            "s": round(float(self.s), 2),
            "lane": self.lane_letter,
            "type": self.type_id,
            "strength": float(self.strength),
            "duration_sec": float(self.duration_sec),
            "asset": self.asset,
        }


def _cfg(key: str, default=None):
    """전역 RACING_DEFAULTS 전용. 맵별 수치는 RacingActivity._p 사용."""
    if key in RACING_DEFAULTS:
        return RACING_DEFAULTS[key]
    try:
        return CONFIG.get(key, default)
    except Exception:
        return default


def _field_cfg(map_id: str, world_data=None) -> dict:
    """RACING_DEFAULTS ⊕ world_data[map].racing 병합."""
    wd = world_data if isinstance(world_data, dict) else {}
    block = {}
    try:
        block = dict((wd.get(map_id) or {}).get("racing") or {})
    except Exception:
        block = {}
    out = dict(RACING_DEFAULTS)
    out.update(block)
    return out


def _angle_wrap(a: float) -> float:
    while a > math.pi:
        a -= math.pi * 2.0
    while a < -math.pi:
        a += math.pi * 2.0
    return a


def _angle_approach(cur: float, target: float, max_delta: float) -> float:
    d = _angle_wrap(float(target) - float(cur))
    if abs(d) <= max_delta:
        return float(target)
    return float(cur) + math.copysign(max_delta, d)


def _lerp(a: float, b: float, t: float) -> float:
    return float(a) + (float(b) - float(a)) * max(0.0, min(1.0, float(t)))


class RacePath:
    """월드 좌표 폴리라인. closed면 루프. s(거리) ↔ 위치/접선/꺾임."""

    def __init__(self, points: List[Tuple[float, float]], *, closed: bool = True):
        pts = [(float(p[0]), float(p[1])) for p in points if len(p) >= 2]
        if len(pts) < 2:
            pts = [(160.0, 240.0), (480.0, 240.0)]
        self.closed = bool(closed)
        if self.closed and pts[0] != pts[-1]:
            pts = list(pts) + [pts[0]]
        self.points = pts
        self.seg_lens: List[float] = []
        self.cum: List[float] = [0.0]
        for i in range(len(pts) - 1):
            dx = pts[i + 1][0] - pts[i][0]
            dy = pts[i + 1][1] - pts[i][1]
            L = math.hypot(dx, dy)
            self.seg_lens.append(max(1e-6, L))
            self.cum.append(self.cum[-1] + self.seg_lens[-1])
        self.length = float(self.cum[-1]) if self.cum else 1.0

    def wrap_s(self, s: float) -> float:
        if self.closed and self.length > 1e-6:
            return float(s) % self.length
        return max(0.0, min(self.length, float(s)))

    def sample(self, s: float) -> Tuple[float, float, float, float]:
        """
        return: x, y, tangent_rad, turn_rad (다음 구간과의 heading 차 · 코너 강도)
        """
        s = self.wrap_s(s)
        if self.length <= 1e-6 or len(self.points) < 2:
            p0 = self.points[0]
            return p0[0], p0[1], 0.0, 0.0
        # 구간 찾기
        i = 0
        for j in range(len(self.seg_lens)):
            if s <= self.cum[j + 1]:
                i = j
                break
            i = j
        seg0 = self.cum[i]
        seg_L = self.seg_lens[i]
        t = 0.0 if seg_L <= 1e-9 else (s - seg0) / seg_L
        t = max(0.0, min(1.0, t))
        x0, y0 = self.points[i]
        x1, y1 = self.points[i + 1]
        x = _lerp(x0, x1, t)
        y = _lerp(y0, y1, t)
        tang = math.atan2(y1 - y0, x1 - x0)
        # 다음 세그먼트 꺾임
        ni = (i + 1) % max(1, len(self.seg_lens)) if self.closed else min(i + 1, len(self.seg_lens) - 1)
        if ni == i and not self.closed:
            turn = 0.0
        else:
            n0 = self.points[ni]
            n1 = self.points[min(ni + 1, len(self.points) - 1)]
            tang2 = math.atan2(n1[1] - n0[1], n1[0] - n0[0])
            turn = abs(_angle_wrap(tang2 - tang))
        return x, y, tang, turn

    def lookahead_turn(self, s: float, dist: float) -> float:
        """앞에 dist 만큼의 최대 꺾임(rad)."""
        steps = 6
        best = 0.0
        for k in range(1, steps + 1):
            _, _, _, turn = self.sample(s + dist * (k / float(steps)))
            if turn > best:
                best = turn
        return float(best)

    def nearest_s(self, wx: float, wy: float) -> float:
        """월드 점에 가장 가까운 경로 거리 s (세그먼트 투영)."""
        wx = float(wx)
        wy = float(wy)
        best_s = 0.0
        best_d2 = 1e30
        if len(self.points) < 2:
            return 0.0
        for i, seg_L in enumerate(self.seg_lens):
            x0, y0 = self.points[i]
            x1, y1 = self.points[i + 1]
            dx = x1 - x0
            dy = y1 - y0
            if seg_L <= 1e-9:
                continue
            t = ((wx - x0) * dx + (wy - y0) * dy) / (seg_L * seg_L)
            t = max(0.0, min(1.0, t))
            px = x0 + dx * t
            py = y0 + dy * t
            d2 = (wx - px) * (wx - px) + (wy - py) * (wy - py)
            if d2 < best_d2:
                best_d2 = d2
                best_s = self.cum[i] + seg_L * t
        return float(best_s)


class RacerState:
    __slots__ = (
        "char_id",
        "is_player",
        "s",
        "lane",
        "lane_target",
        "speed",
        "heading",
        "pos",
        "lap",
        "finished",
        "entity",
        "ai_timer",
        "prev_s",
        "speed_mul",
        "buff_t",
        "buff_label",
        "hud_role",
        "freeze_t",
        "slipstream_mul",
        "bump_slow_t",
        "weather_slow_mul",
    )

    def __init__(self, char_id: str, *, is_player: bool, s0: float, lane0: float, hud_role: str = ""):
        self.char_id = str(char_id)
        self.is_player = bool(is_player)
        self.s = float(s0)
        self.prev_s = float(s0)
        self.lane = float(lane0)
        self.lane_target = float(lane0)
        self.speed = 0.0
        self.heading = 0.0
        self.pos = [0.0, 0.0]
        self.lap = 0
        self.finished = False
        self.entity = None
        self.ai_timer = random.uniform(0.8, 2.2)
        self.speed_mul = 1.0
        self.buff_t = 0.0
        self.buff_label = ""
        role = str(hud_role or "").strip().lower()
        if role not in ("npc1", "player", "npc2"):
            role = "player" if is_player else "npc1"
        self.hud_role = role
        self.buff_label = ""
        self.freeze_t = 0.0
        self.slipstream_mul = 1.0
        self.bump_slow_t = 0.0
        self.weather_slow_mul = 1.0


class RacingActivity(BaseFieldActivity):
    activity_id = "racing"

    def __init__(self):
        self.state = ST_MENU
        self.map_id = ""
        self.field: dict = {}
        self._player_ref = None
        self._ev_mgr = None
        self._npcs_list = None
        self._save_data: dict = {}
        self._orig_char_name = ""
        self._player_char = "summer_k"
        self._char_opts: List[str] = []
        self._char_pick_ix = 0
        self._char_pending_ix: Optional[int] = None
        self._menu_rects: List[Tuple[pygame.Rect, str]] = []
        self._char_pick_rects: List[Tuple[pygame.Rect, int]] = []
        self._ui_screen_wh: Optional[Tuple[int, int]] = None
        self._idle_cache: Dict[Tuple[str, str], List] = {}
        self._return_map = ""
        self._return_pos: Optional[List[float]] = None
        self._should_return = False
        self._msg = ""
        self._path: Optional[RacePath] = None
        self._racers: List[RacerState] = []
        self._temp_npcs: List[Any] = []
        self._countdown_t = 0.0
        self._finish_t = 0.0
        self._lap_goal = 3
        self._race_time = 0.0
        self._won = False
        self._stop_btn_rect: Optional[pygame.Rect] = None
        self._option_btn_rect: Optional[pygame.Rect] = None
        # 레이스 중 왼쪽 위 옵션 버튼 팝업 (카메라·미니맵·게임 중지)
        self._race_options_open = False
        self._race_opt_rects: List[Tuple[pygame.Rect, str]] = []
        # 게임 중지 확인창 (예/아니오)
        self._race_quit_confirm = False
        self._race_confirm_rects: List[Tuple[pygame.Rect, str]] = []
        self._camera_popup_rect: Optional[pygame.Rect] = None
        self._camera_side_rect: Optional[pygame.Rect] = None
        self._camera_back_rect: Optional[pygame.Rect] = None
        self._minimap_toggle_rect: Optional[pygame.Rect] = None
        self._options_open = False
        self._camera_mode = "side"  # side | back
        self._minimap_user_enabled = True  # 옵션 팝업 토글 (세션 단위)
        self.mode7_player_x_frac: Optional[float] = None
        # main.py 가 읽는 Mode7 / 틸트 오버라이드
        self.field_rotate3d_target: Optional[float] = None
        self.mode7_cam_heading: Optional[float] = None
        self._cam_heading: Optional[float] = None  # 스무스 카메라 (경로 접선 스냅 금지)
        self.field_tilt_target: Optional[float] = None
        self._items: List[RaceItemPoint] = []
        self._item_msg = ""
        self._item_msg_t = 0.0
        # "record" = 기록용(기존), "versus" = 경쟁(A/B/C 나란히·선착승)
        self._race_mode = "record"
        self._winner: Optional[RacerState] = None
        self._objs_list = None
        # 레인 화살표 HUD (왼쪽 · 자동생성 또는 애니 세트)
        self._lane_btn_up = RaceLaneHudButton(
            "lane_up", pointing_up=True, anim_name=str(_cfg("lane_btn_up_anim", "lane_up") or "lane_up")
        )
        self._lane_btn_down = RaceLaneHudButton(
            "lane_down",
            pointing_up=False,
            anim_name=str(_cfg("lane_btn_down_anim", "lane_down") or "lane_down"),
        )
        self._lane_btns: List[RaceLaneHudButton] = [self._lane_btn_up, self._lane_btn_down]
        # 경로 기반 도로 자동 그리기 (bg에 직접 덧그림 → Mode7·미니맵에 그대로 반영)
        self._bg_ref: Optional[pygame.Surface] = None
        self._road_painted = False
        # 미니맵 오버레이 (전체 맵 1/8 축소 + 레이서 위치 + 경과 시간)
        self._world_data: dict = {}
        self._minimap_bg: Optional[pygame.Surface] = None
        self._minimap_map_wh: Tuple[float, float] = (1.0, 1.0)
        # 날씨·청정·시크릿 룰렛·소환 번쩍
        self._clean_zones: List[Tuple[float, float]] = []
        self._weather_zones: List[dict] = []
        self._spawn_flashes: List[dict] = []
        self._secret_spin: Optional[dict] = None
        self._weather_msg = ""
        self._weather_msg_t = 0.0

    def _p(self, key: str, default=None):
        """맵별 world_data.racing ⊕ RACING_DEFAULTS 값."""
        try:
            if key in self.field:
                return self.field[key]
        except Exception:
            pass
        return _cfg(key, default)

    # --- lifecycle ---------------------------------------------------------

    def begin(self, player, **params) -> bool:
        self._player_ref = player
        self._ev_mgr = params.get("ev_mgr")
        self._npcs_list = params.get("npcs")
        self.map_id = str(
            params.get("map") or params.get("map_id") or _cfg("default_map_id", "bg_town")
        ).strip()
        self.field = _field_cfg(self.map_id, params.get("world_data"))
        wd = params.get("world_data")
        self._world_data = wd if isinstance(wd, dict) else {}
        self._minimap_bg = None  # 맵이 바뀌었을 수 있으니 미니맵 캐시 초기화
        save = params.get("save_data") or {}
        self._save_data = dict(save) if isinstance(save, dict) else {}

        pts_raw = self.field.get("path") or _cfg("path") or []
        pts: List[Tuple[float, float]] = []
        for p in pts_raw:
            try:
                pts.append((float(p[0]), float(p[1])))
            except (TypeError, ValueError, IndexError):
                continue
        if len(pts) < 2:
            pts = list(_cfg("path") or [(120.0, 240.0), (520.0, 240.0)])
        self._path = RacePath(pts, closed=bool(self.field.get("closed", _cfg("closed", True))))
        self._lap_goal = int(self.field.get("laps", _cfg("laps", 3)))
        self._lap_goal = max(1, min(99, self._lap_goal))

        self._player_char = str(getattr(player, "name", "") or _cfg("default_player_char", "summer_k"))
        self._orig_char_name = str(self._player_char)
        fixed = self.field.get("char_pick") or _cfg("char_pick") or []
        opts = [str(x).strip() for x in fixed if str(x).strip() and str(x).strip() in CHAR_ASSETS]
        if not opts:
            opts = [c for c in (_cfg("char_pick") or []) if c in CHAR_ASSETS]
        if not opts:
            opts = [k for k in sorted(CHAR_ASSETS.keys()) if k.endswith("_k")][:8]
        self._char_opts = opts[:8]
        self._char_pick_ix = 0
        for i, cid in enumerate(self._char_opts):
            if cid == self._player_char:
                self._char_pick_ix = i
                break

        self._return_map = str(params.get("return_map") or "").strip()
        rp = params.get("return_pos")
        if isinstance(rp, (list, tuple)) and len(rp) >= 2:
            self._return_pos = [float(rp[0]), float(rp[1])]
        else:
            self._return_pos = None
        self._resolve_return_anchor()

        self.state = ST_MENU
        self._msg = "메뉴"
        self.field_rotate3d_target = 0.0
        self.mode7_cam_heading = None
        self.mode7_player_x_frac = None
        self._cam_heading = None
        self._options_open = False
        self._race_options_open = False
        self._race_opt_rects = []
        self._option_btn_rect = None
        self._race_quit_confirm = False
        self._race_confirm_rects = []
        self._camera_mode = "side"
        self._minimap_user_enabled = bool(self._p("minimap_enabled", True))
        self.field_tilt_target = 1.0
        try:
            player.stop_moving()
            player.path = []
            player.target = list(player.pos)
        except Exception:
            pass
        lw, lh = self._logical_screen_size()
        self._layout_menu_rects(lw, lh)
        # 경로 기반 3레인 도로를 bg에 덧그림 (맵에 레인을 직접 그릴 필요 없음)
        bg = params.get("bg")
        self._bg_ref = bg if isinstance(bg, pygame.Surface) else None
        self._road_painted = False
        self._paint_road_on_bg()
        print(f"[racing] begin map={self.map_id} path_len={self._path.length:.0f}")
        return True

    def cancel(self) -> None:
        self._quit_session()

    @property
    def is_active(self) -> bool:
        return self.state != ST_QUIT

    @property
    def is_finished(self) -> bool:
        return self.state == ST_QUIT

    def blocks_field_move(self) -> bool:
        return True

    def blocks_zone_confirm(self) -> bool:
        return True

    def save_location_override(self):
        # 레이스 중 강제 종료해도 서킷 맵이 세이브되지 않도록 항상 exit/return 좌표 제공.
        em, pos = self._configured_exit()
        if self._return_map:
            em = self._return_map
            if self._return_pos is not None:
                pos = self._return_pos
        return (str(em), [float(pos[0]), float(pos[1])])

    def result(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "activity": self.activity_id,
            "won": bool(self._won),
            "quit": self.state == ST_QUIT,
            "exit_event_id": "ev_racing_exit",
        }
        if self._return_map and (self._should_return or self.state == ST_QUIT):
            out["return_map"] = self._return_map
            pos = self._return_pos
            if not (isinstance(pos, (list, tuple)) and len(pos) >= 2):
                _, pos = self._configured_exit()
            out["return_pos"] = [float(pos[0]), float(pos[1])]
            out["quit"] = True
        return out

    def poll_camera_command(self) -> Optional[Dict[str, Any]]:
        # 레이스 중엔 follow(플레이어=메인 레이서). 메뉴는 고정 가능.
        if self.state in (ST_RACE, ST_COUNTDOWN, ST_FINISH):
            return {"mode": "follow_player", "smooth": True, "duration_sec": 0.15}
        return None

    # --- exit / return -----------------------------------------------------

    def _configured_exit(self) -> Tuple[str, List[float]]:
        em = str(self.field.get("exit_map") or _cfg("exit_map", "bg_jjangpu")).strip()
        ep = self.field.get("exit_pos") or _cfg("exit_pos", [850.0, 2310.0])
        try:
            pos = [float(ep[0]), float(ep[1])]
        except (TypeError, ValueError, IndexError):
            pos = [850.0, 2310.0]
        return em or "bg_jjangpu", pos

    def _resolve_return_anchor(self) -> None:
        if self._return_map:
            if self._return_pos is None:
                _, self._return_pos = self._configured_exit()
            return
        self._return_map, self._return_pos = self._configured_exit()

    def _quit_session(self) -> None:
        self._cleanup_temp_npcs()
        self._restore_player_char()
        self._should_return = True
        self.state = ST_QUIT
        self._options_open = False
        self._race_options_open = False
        self._option_btn_rect = None
        self._race_opt_rects = []
        self._race_quit_confirm = False
        self._race_confirm_rects = []
        self.field_rotate3d_target = 0.0
        self.mode7_cam_heading = None
        self.mode7_player_x_frac = None
        self._cam_heading = None
        self.field_tilt_target = None
        try:
            if self._ev_mgr is not None:
                self._ev_mgr.remove_ui_overlay("racing_exit")
        except Exception:
            pass
        try:
            from engine import clear_ui_font_cache

            clear_ui_font_cache()
        except Exception:
            pass

    def _restore_player_char(self) -> None:
        pl = self._player_ref
        if pl is None or not self._orig_char_name:
            return
        if str(getattr(pl, "name", "") or "") == self._orig_char_name:
            return
        rt = getattr(pl, "retarget_char_def", None)
        if callable(rt):
            try:
                rt(self._orig_char_name)
            except Exception:
                pass

    def _apply_player_char(self, char_id: str) -> None:
        self._player_char = str(char_id)
        pl = self._player_ref
        if pl is None:
            return
        if str(getattr(pl, "name", "") or "") == self._player_char:
            return
        rt = getattr(pl, "retarget_char_def", None)
        if callable(rt):
            try:
                rt(self._player_char)
            except Exception:
                pass

    # --- race setup --------------------------------------------------------

    def _path_s_dist(self, a: float, b: float) -> float:
        """닫힌 경로에서 두 s 사이 최단 거리(px)."""
        path = self._path
        if path is None:
            return abs(float(a) - float(b))
        L = max(1e-6, float(path.length))
        d = abs(float(a) - float(b)) % L
        return float(min(d, L - d))

    def _lane_occupied(
        self,
        lane_off: float,
        except_r: Optional[RacerState] = None,
        *,
        near_s: Optional[float] = None,
    ) -> bool:
        """
        같은 레인에 다른 레이서가 가까이 있으면 True.
        near_s 기준(없으면 except_r.s). 한 레인에 겹쳐 달릴 수 없게 함.
        """
        path = self._path
        if path is None:
            return False
        try:
            sep = float(self._p("lane_occupy_s", 40.0) or 40.0)
        except (TypeError, ValueError):
            sep = 40.0
        sep = max(8.0, sep)
        ref_s = float(near_s) if near_s is not None else (
            float(except_r.s) if except_r is not None else 0.0
        )
        lo = float(lane_off)
        for o in self._racers:
            if o is except_r or o.finished:
                continue
            # 현재 레인 또는 목표 레인이 같으면 점유로 봄
            if abs(float(o.lane) - lo) > 0.45 and abs(float(o.lane_target) - lo) > 0.45:
                continue
            if self._path_s_dist(ref_s, float(o.s)) < sep:
                return True
        return False

    def _try_set_lane(self, r: RacerState, lane_off: float) -> bool:
        """레인 변경 시도. 근처 같은 레인이 있으면 실패(목표 유지)."""
        if r is None or r.finished:
            return False
        lo = float(lane_off)
        if abs(float(r.lane_target) - lo) < 0.05:
            return True
        if self._lane_occupied(lo, except_r=r, near_s=float(r.s)):
            return False
        r.lane_target = lo
        return True

    def _pick_npc_pair(self) -> Tuple[str, str]:
        """
        선택 가능 캐릭터(_char_opts)에서 플레이어를 제외한 뒤 랜덤 2명.
        부족하면 char_pick 기본·CHAR_ASSETS 로 채움.
        """
        player_cid = str(self._player_char or "").strip()
        pool = [str(c).strip() for c in (self._char_opts or []) if str(c).strip() and str(c).strip() != player_cid]
        if len(pool) < 2:
            extra = [
                str(c).strip()
                for c in (_cfg("char_pick") or [])
                if str(c).strip() and str(c).strip() != player_cid and str(c).strip() not in pool
            ]
            pool.extend(extra)
        if len(pool) < 2:
            for c in CHAR_ASSETS.keys():
                cs = str(c).strip()
                if not cs or cs == player_cid or cs in pool:
                    continue
                if cs.endswith("_k"):
                    pool.append(cs)
                if len(pool) >= 8:
                    break
        if not pool:
            pool = [player_cid or "summer_k"]
        random.shuffle(pool)
        a = str(pool[0])
        b = str(pool[1]) if len(pool) > 1 else str(pool[0])
        # 가능하면 서로 다른 캐릭터
        if b == a and len(pool) > 1:
            for c in pool[1:]:
                if str(c) != a:
                    b = str(c)
                    break
        return a, b

    def bind_field_lists(self, *, npcs=None, objs=None) -> None:
        """main 루프의 최신 npcs/objs 참조를 붙인다 (progress 적용 후 리스트 교체 대응)."""
        if isinstance(npcs, list):
            self._npcs_list = npcs
        if objs is not None:
            self._objs_list = objs

    def _start_countdown(self) -> None:
        self._cleanup_temp_npcs()
        self._racers = []
        path = self._path
        assert path is not None
        start_s = float(self._p("start_s", 0.0))
        spacing = float(self._p("start_spacing", 18.0))
        self._winner = None

        versus = str(self._race_mode or "record").strip().lower() == "versus"
        npc1, npc2 = self._pick_npc_pair()

        if versus:
            # 경쟁: A=NPC1, B=플레이어, C=NPC2 — 같은 s 에 나란히
            slots = [
                (npc1, False, LANE_UPPER, "npc1"),      # A
                (self._player_char, True, LANE_CENTER, "player"),  # B
                (npc2, False, LANE_LOWER, "npc2"),      # C
            ]
            s_list = [start_s, start_s, start_s]
        else:
            # 기록용: 플레이어 앞·NPC 뒤 간격 + 레인 섞기
            slots = [
                (self._player_char, True, LANE_UPPER, "player"),
                (npc1, False, LANE_LOWER, "npc1"),
                (npc2, False, LANE_CENTER, "npc2"),
            ]
            s_list = [start_s - i * spacing for i in range(3)]

        lane_w = float(self._p("lane_width", 26.0))
        for i, (cid, is_pl, lane0, role) in enumerate(slots):
            r = RacerState(
                cid, is_player=is_pl, s0=float(s_list[i]), lane0=lane0, hud_role=role
            )
            r.lane_target = lane0
            x, y, tang, _ = path.sample(r.s)
            nx = -math.sin(tang)
            ny = math.cos(tang)
            r.heading = tang
            r.pos = [x + nx * lane0 * lane_w, y + ny * lane0 * lane_w]
            r.prev_s = r.s
            self._racers.append(r)

        self._apply_player_char(self._player_char)
        self._spawn_temp_npcs()
        self._sync_entities_to_racers()
        print(
            f"[racing] grid player={self._player_char} npc1={npc1} npc2={npc2} "
            f"spawned={sum(1 for r in self._racers if (not r.is_player) and r.entity is not None)}"
        )
        self._countdown_t = float(self._p("countdown_sec", 3.0))
        self._race_time = 0.0
        self._won = False
        self.state = ST_COUNTDOWN
        self._msg = "경쟁 출발!" if versus else "출발 준비"
        self.field_rotate3d_target = float(self._p("rotate3d_strength", 1.0))
        # 카메라: 진행 방향의 오른쪽 — 초기값만 맞추고 이후는 heading 을 스무스 추종
        pr0 = next((x for x in self._racers if x.is_player), None)
        side = float(self._p("cam_side_sign", -1.0))
        if pr0 is not None:
            self._cam_heading = float(pr0.heading) + side * (math.pi * 0.5)
            self.mode7_cam_heading = self._cam_heading
        else:
            self._cam_heading = None
        self._rebuild_items()
        self._init_race_environment()
        self._item_msg = ""
        self._item_msg_t = 0.0

    def _init_race_environment(self) -> None:
        """청정 구간·날씨 존 생성 (레이스 시작 시)."""
        self._clean_zones = []
        raw_cz = self.field.get("clean_zones")
        if raw_cz is None:
            raw_cz = _cfg("clean_zones") or []
        if isinstance(raw_cz, list):
            for row in raw_cz:
                try:
                    if isinstance(row, (list, tuple)) and len(row) >= 2:
                        a, b = float(row[0]), float(row[1])
                        if b < a:
                            a, b = b, a
                        self._clean_zones.append((a, b))
                except (TypeError, ValueError):
                    pass
        self._weather_zones = []
        self._spawn_flashes = []
        self._secret_spin = None
        self._weather_msg = ""
        self._weather_msg_t = 0.0
        path = self._path
        if path is None:
            return
        wcfg = self.field.get("weather")
        if wcfg is None:
            wcfg = _cfg("weather") or {}
        if not isinstance(wcfg, dict) or not bool(wcfg.get("enabled", True)):
            return
        L = float(path.length)
        laps = max(1, int(self._lap_goal))
        for lap_i in range(laps):
            base = lap_i * L
            for kind, key in (("rain", "rain"), ("lightning", "lightning")):
                block = wcfg.get(key) if isinstance(wcfg.get(key), dict) else {}
                try:
                    chance = float(block.get("chance_per_lap", 0.0) or 0.0)
                except (TypeError, ValueError):
                    chance = 0.0
                if chance <= 0.0 or random.random() > chance:
                    continue
                zlen = block.get("zone_len_s") or [80.0, 140.0]
                try:
                    zmin = float(zlen[0]) if isinstance(zlen, (list, tuple)) else 80.0
                    zmax = float(zlen[1]) if isinstance(zlen, (list, tuple)) and len(zlen) > 1 else zmin
                except (TypeError, ValueError, IndexError):
                    zmin, zmax = 80.0, 140.0
                zlen_f = random.uniform(max(20.0, zmin), max(zmin, zmax))
                s0 = random.uniform(60.0, max(61.0, L - zlen_f - 40.0))
                s0 = base + s0
                s1 = s0 + zlen_f
                if self._zone_overlaps_clean(s0, s1):
                    continue
                self._weather_zones.append(
                    {
                        "kind": kind,
                        "s0": float(s0),
                        "s1": float(s1),
                        "slow_mul": float(block.get("slow_mul", 0.72) or 0.72),
                        "strike_chance": float(block.get("strike_chance", 0.35) or 0.35),
                        "freeze_sec": float(block.get("freeze_sec", 1.15) or 1.15),
                    }
                )

    def _zone_overlaps_clean(self, s0: float, s1: float) -> bool:
        for a, b in self._clean_zones:
            if s1 >= a and s0 <= b:
                return True
        return False

    def _s_in_clean_zone(self, s: float) -> bool:
        path = self._path
        if path is None:
            return False
        ss = float(path.wrap_s(s))
        for a, b in self._clean_zones:
            if a <= ss <= b:
                return True
        return False

    def _racer_in_weather(self, r: RacerState, kind: str) -> Optional[dict]:
        if r is None or self._s_in_clean_zone(r.s):
            return None
        for z in self._weather_zones:
            if str(z.get("kind") or "") != kind:
                continue
            s0, s1 = float(z.get("s0", 0)), float(z.get("s1", 0))
            if s0 <= float(r.s) <= s1:
                return z
        return None

    def _rebuild_items(self) -> None:
        """world_data.racing.items (+ 랜덤 옵션) → 런타임 아이템."""
        path = self._path
        self._items = []
        if path is None:
            return
        lane_w = float(self._p("lane_width", 26.0))
        raw_list = self.field.get("items")
        if not isinstance(raw_list, list):
            raw_list = _cfg("items") or []
        rows = [dict(x) for x in raw_list if isinstance(x, dict)]
        if (not rows) and bool(self._p("item_random_enabled", False)):
            rows = self._generate_random_item_rows(path)
        for row in rows:
            try:
                it = RaceItemPoint(row, path, lane_w)
                self._items.append(it)
            except Exception as e:
                print(f"[racing] item skip: {e}")

    def _generate_random_item_rows(self, path: RacePath) -> List[dict]:
        try:
            n = int(self._p("item_random_count", 6) or 6)
        except (TypeError, ValueError):
            n = 6
        n = max(0, min(40, n))
        types = list(RACING_MYSTERY_EFFECT_POOL) or ["speed", "slow", "swap"]
        lanes = ["A", "B", "C"]
        out = []
        L = max(1.0, float(path.length))
        for i in range(n):
            # 스타트 직후는 피하고 균등+지터
            frac = (i + 0.5) / max(1, n)
            s = (frac * L + random.uniform(-L * 0.03, L * 0.03)) % L
            if s < 40.0:
                s = 40.0 + random.uniform(0, 30)
            out.append(
                {
                    "s": float(s),
                    "lane": random.choice(lanes),
                    "type": random.choice(types),
                    "kind": random.choices(
                        ["normal", "secret", "roulette", "summon"],
                        weights=[55, 15, 18, 12],
                        k=1,
                    )[0],
                }
            )
        return out

    def _pick_mystery_effect(self) -> str:
        pool = [str(x) for x in (RACING_MYSTERY_EFFECT_POOL or ("speed", "slow", "swap"))]
        return random.choice(pool) if pool else "speed"

    def _apply_effect_to_racer(self, r: RacerState, type_id: str, *, strength=None, duration=None) -> None:
        """type_id 기준 효과 적용 (speed/slow/swap/freeze)."""
        if r is None or r.finished:
            return
        tid = str(type_id or "speed").strip().lower()
        info = _item_type_info(tid)
        effect = str(info.get("effect") or "speed_mul")
        if effect == "swap":
            self._effect_swap(r)
            if r.is_player:
                self._item_msg = str(info.get("label") or "위치 교환!")
                self._item_msg_t = 1.8
            return
        if effect == "freeze" or tid == "freeze":
            try:
                r.freeze_t = max(r.freeze_t, float(duration or info.get("duration_sec", 1.0) or 1.0))
            except (TypeError, ValueError):
                r.freeze_t = max(r.freeze_t, 1.0)
            r.speed = 0.0
            if r.is_player:
                self._item_msg = "번개!!"
                self._item_msg_t = 1.5
            return
        try:
            st = float(strength if strength is not None else info.get("strength", 1.0) or 1.0)
        except (TypeError, ValueError):
            st = 1.0
        try:
            dur = float(duration if duration is not None else info.get("duration_sec", 2.0) or 2.0)
        except (TypeError, ValueError):
            dur = 2.0
        r.speed_mul = st
        r.buff_t = max(0.05, dur)
        r.buff_label = str(info.get("label") or tid)
        if abs(st - 1.0) > 1e-6:
            r.speed = max(0.0, float(r.speed) * st)
        if r.is_player:
            self._item_msg = r.buff_label
            self._item_msg_t = 1.6

    def _effect_swap(self, r: RacerState) -> None:
        """다른 레이서와 경로 위치·레인 교환."""
        others = [x for x in self._racers if x is not r and not x.finished]
        if not others:
            return
        other = min(others, key=lambda o: self._path_s_dist(float(r.s), float(o.s)))
        path = self._path
        if path is None:
            return
        lane_w = float(self._p("lane_width", 26.0))
        rs, rl, rt = float(r.s), float(r.lane), float(r.lane_target)
        r.s = float(other.s)
        r.lane = float(other.lane)
        r.lane_target = float(other.lane_target)
        other.s = rs
        other.lane = rl
        other.lane_target = rt
        for who in (r, other):
            x, y, tang, _ = path.sample(who.s)
            nx = -math.sin(tang)
            ny = math.cos(tang)
            who.pos[0] = x + nx * who.lane * lane_w
            who.pos[1] = y + ny * who.lane * lane_w
            who.heading = tang
            # 아이템 소환과 같은 링 효과를 두 레이서의 교환 도착점에 표시.
            self._add_spawn_flash(who.pos[0], who.pos[1])

    def _start_secret_spin(self, r: RacerState) -> None:
        """시크릿 상자 — 마리오카트식 아이콘 룰렛 후 효과 적용."""
        if r is None:
            return
        final = self._pick_mystery_effect()
        pool = list(RACING_MYSTERY_EFFECT_POOL) or ["speed", "slow", "swap"]
        try:
            dur = float(self._p("secret_spin_sec", 1.35) or 1.35)
        except (TypeError, ValueError):
            dur = 1.35
        self._secret_spin = {
            "racer": r,
            "pool": pool,
            "t": 0.0,
            "dur": max(0.6, dur),
            "final": final,
            "applied": False,
        }
        if r.is_player:
            self._item_msg = "??? 상자!"
            self._item_msg_t = dur + 0.3

    def _tick_secret_spin(self, dt: float) -> None:
        sp = self._secret_spin
        if not sp or sp.get("applied"):
            return
        sp["t"] = float(sp.get("t", 0.0)) + max(0.0, float(dt))
        if float(sp["t"]) >= float(sp.get("dur", 1.0)):
            r = sp.get("racer")
            if r is not None and not sp.get("applied"):
                self._apply_effect_to_racer(r, str(sp.get("final") or "speed"))
            sp["applied"] = True
            self._secret_spin = None

    def _summon_random_item(self, *, avoid_s: Optional[float] = None) -> None:
        """청정 구간 피해 경로에 일반 아이템 소환."""
        path = self._path
        if path is None:
            return
        L = float(path.length)
        for _ in range(24):
            s = random.uniform(50.0, max(51.0, L - 50.0))
            if avoid_s is not None and abs(self._path_s_dist(s, float(avoid_s))) < 45.0:
                continue
            if self._s_in_clean_zone(s):
                continue
            lane = random.choice(["A", "B", "C"])
            tid = self._pick_mystery_effect()
            row = {"s": float(s), "lane": lane, "type": tid, "kind": "normal"}
            try:
                it = RaceItemPoint(row, path, float(self._p("lane_width", 26.0)))
                self._items.append(it)
                self._add_spawn_flash(it.wx, it.wy)
                if self._player_ref:
                    pr = next((x for x in self._racers if x.is_player), None)
                    if pr is not None:
                        self._item_msg = "아이템 소환!"
                        self._item_msg_t = 1.2
                return
            except Exception:
                continue

    def _add_spawn_flash(self, wx: float, wy: float) -> None:
        try:
            sec = float(self._p("summon_flash_sec", 1.6) or 1.6)
        except (TypeError, ValueError):
            sec = 1.6
        self._spawn_flashes.append({"wx": float(wx), "wy": float(wy), "t": max(0.4, sec)})

    def _tick_spawn_flashes(self, dt: float) -> None:
        if not self._spawn_flashes:
            return
        out = []
        for f in self._spawn_flashes:
            t = float(f.get("t", 0.0)) - max(0.0, float(dt))
            if t > 0.0:
                f["t"] = t
                out.append(f)
        self._spawn_flashes = out

    def _on_item_pickup(self, r: RacerState, it: RaceItemPoint) -> None:
        """아이템/발판 종류별 처리."""
        kind = str(getattr(it, "kind", "normal") or "normal")
        if kind == "secret":
            it.taken = True
            self._start_secret_spin(r)
            return
        if kind == "summon":
            it.taken = True
            self._summon_random_item(avoid_s=float(it.s))
            return
        if kind == "roulette":
            it.taken = True
            self._apply_effect_to_racer(r, str(getattr(it, "inner_type_id", "speed") or "speed"))
            return
        it.taken = True
        self._apply_effect_to_racer(
            r,
            str(it.type_id),
            strength=float(it.strength),
            duration=float(it.duration_sec),
        )

    def _tick_item_platforms(self, dt: float) -> None:
        path = self._path
        if path is None:
            return
        lane_w = float(self._p("lane_width", 26.0))
        for it in self._items:
            if it.taken:
                continue
            if str(getattr(it, "kind", "")) == "roulette":
                it.tick_roulette(dt)
                it.recompute_world(path, lane_w)

    def _tick_weather(self, dt: float) -> None:
        if self.state != ST_RACE:
            return
        for r in self._racers:
            if r.finished:
                r.weather_slow_mul = 1.0
                continue
            rz = self._racer_in_weather(r, "rain")
            if rz:
                try:
                    r.weather_slow_mul = float(rz.get("slow_mul", 0.72) or 0.72)
                except (TypeError, ValueError):
                    r.weather_slow_mul = 0.72
            else:
                r.weather_slow_mul = 1.0
            lz = self._racer_in_weather(r, "lightning")
            if lz and float(r.freeze_t or 0.0) <= 0.0:
                try:
                    ch = float(lz.get("strike_chance", 0.35) or 0.35)
                except (TypeError, ValueError):
                    ch = 0.35
                if random.random() < ch * max(0.0, float(dt)) * 2.5:
                    try:
                        fs = float(lz.get("freeze_sec", 1.15) or 1.15)
                    except (TypeError, ValueError):
                        fs = 1.15
                    r.freeze_t = max(float(r.freeze_t or 0.0), fs)
                    r.speed = 0.0
                    if r.is_player:
                        self._weather_msg = "번개!"
                        self._weather_msg_t = 1.2

    def _tick_slipstream_and_bumps(self, dt: float) -> None:
        if self.state != ST_RACE:
            return
        path = self._path
        if path is None:
            return
        try:
            min_frac = float(self._p("slipstream_min_speed_frac", 0.90) or 0.90)
            follow_s = float(self._p("slipstream_follow_s", 38.0) or 38.0)
            lane_tol = float(self._p("slipstream_lane_tol", 0.42) or 0.42)
            bump_s = float(self._p("slipstream_bump_s", 22.0) or 22.0)
        except (TypeError, ValueError):
            min_frac, follow_s, lane_tol, bump_s = 0.9, 38.0, 0.42, 22.0
        max_spd_base = float(self._p("max_speed", 140.0))
        for r in self._racers:
            r.slipstream_mul = 1.0
        # 슬립스트림: 앞차 90%+ 속도일 때 뒤차 가속
        for lead in self._racers:
            if lead.finished:
                continue
            cap = max_spd_base * max(0.15, float(lead.speed_mul)) * max(0.15, float(lead.weather_slow_mul or 1.0))
            if cap < 1e-3 or float(lead.speed) < cap * min_frac:
                continue
            for follow in self._racers:
                if follow is lead or follow.finished:
                    continue
                if abs(float(follow.lane) - float(lead.lane)) > lane_tol:
                    continue
                ds = self._path_s_dist(float(follow.s), float(lead.s))
                if ds <= 1.0 or ds > follow_s:
                    continue
                # follow 가 뒤에 있어야 함 (경로 진행 방향 근사)
                if not self._racer_is_behind(follow, lead):
                    continue
                follow.slipstream_mul = 1.0 + 0.35
        # 추돌: 같은 레인·가까우면 앞은 전진·뒤는 감속
        for i, a in enumerate(self._racers):
            if a.finished:
                continue
            for b in self._racers[i + 1 :]:
                if b.finished:
                    continue
                if abs(float(a.lane) - float(b.lane)) > lane_tol * 0.85:
                    continue
                ds = self._path_s_dist(float(a.s), float(b.s))
                if ds > bump_s:
                    continue
                rear, front = (a, b) if self._racer_is_behind(a, b) else (b, a)
                if rear is front:
                    continue
                if float(rear.bump_slow_t or 0.0) > 0.05:
                    continue
                try:
                    boost = float(self._p("slipstream_bump_front_boost", 1.35) or 1.35)
                    slow = float(self._p("slipstream_bump_rear_slow", 0.45) or 0.45)
                    slow_t = float(self._p("slipstream_bump_slow_sec", 1.4) or 1.4)
                except (TypeError, ValueError):
                    boost, slow, slow_t = 1.35, 0.45, 1.4
                front.speed = min(max_spd_base * 1.5, float(front.speed) * boost + 12.0)
                rear.speed *= slow
                rear.bump_slow_t = max(float(rear.bump_slow_t or 0.0), slow_t)
                rear.speed_mul = min(float(rear.speed_mul), slow)
                if rear.is_player:
                    self._item_msg = "추돌!"
                    self._item_msg_t = 0.9

    def _racer_is_behind(self, rear: RacerState, front: RacerState) -> bool:
        """경로 s 기준 rear 가 front 뒤인지 (랩 래핑 고려)."""
        path = self._path
        if path is None:
            return float(rear.s) < float(front.s)
        L = float(path.length)
        if L < 1e-3:
            return True
        d = (float(front.s) - float(rear.s)) % L
        return 0.0 < d < L * 0.5

    def _tick_race_extras(self, dt: float) -> None:
        if self._weather_msg_t > 0.0:
            self._weather_msg_t = max(0.0, self._weather_msg_t - max(0.0, float(dt)))
        self._tick_item_platforms(dt)
        self._tick_weather(dt)
        self._tick_slipstream_and_bumps(dt)
        self._tick_secret_spin(dt)
        self._tick_spawn_flashes(dt)

    def _apply_item_to_racer(self, r: RacerState, it: RaceItemPoint) -> None:
        self._on_item_pickup(r, it)

    def _tick_item_pickups(self) -> None:
        path = self._path
        if path is None or self.state != ST_RACE:
            return
        try:
            rad = float(self._p("item_pick_radius", 18.0) or 18.0)
        except (TypeError, ValueError):
            rad = 18.0
        rad2 = max(4.0, rad) ** 2
        for it in self._items:
            if it.taken:
                continue
            for r in self._racers:
                if r.finished:
                    continue
                # 같은 차선 근처 + 근접
                if abs(float(r.lane) - float(it.lane)) > 0.55:
                    continue
                dx = float(r.pos[0]) - float(it.wx)
                dy = float(r.pos[1]) - float(it.wy)
                if dx * dx + dy * dy <= rad2:
                    it.taken = True
                    self._apply_item_to_racer(r, it)
                    break

    def _spawn_temp_npcs(self) -> None:
        """레이스 NPC 엔티티를 필드 npcs 리스트에 붙인다 (메인 렌더 + 위치 동기화)."""
        from engine import MaskWalkingCharacter

        self._cleanup_temp_npcs()
        if not isinstance(self._npcs_list, list):
            # begin 시점 참조 유실 대비 — 임시 리스트라도 만들어 두고 bind 때 합류
            self._npcs_list = []
            print("[racing] warn: npcs list missing — using temp list (bind_field_lists 필요)")
        for r in self._racers:
            if r.is_player:
                r.entity = self._player_ref
                continue
            try:
                ent = MaskWalkingCharacter(
                    r.char_id, [float(r.pos[0]), float(r.pos[1])], {"ysort": "ground"}
                )
                ent._racing_temp = True
                # 메인 Character.draw 는 끄고 racing.draw_world 에서 그림 (리스트 유실 대비)
                ent.is_visible = False
                ent.path = []
                ent.target = list(ent.pos)
                ent.direction = "right"
                ent.state = "idle"
                # 메인 렌더 풀에 반드시 들어가게
                if ent not in self._npcs_list:
                    self._npcs_list.append(ent)
                self._temp_npcs.append(ent)
                r.entity = ent
            except Exception as e:
                print(f"[racing] npc spawn fail ({r.char_id}): {e}")
                r.entity = None

    def _cleanup_temp_npcs(self) -> None:
        if isinstance(self._npcs_list, list) and self._temp_npcs:
            for ent in list(self._temp_npcs):
                try:
                    if ent in self._npcs_list:
                        self._npcs_list.remove(ent)
                except Exception:
                    pass
        self._temp_npcs = []
        for r in self._racers:
            if not r.is_player:
                r.entity = None

    def _sync_entities_to_racers(self) -> None:
        """물리 pos 를 엔티티에만 반영 (경로에 위치를 덮어쓰지 않음)."""
        # 리스트 교체 후에도 임시 NPC 가 메인 npcs 에 있도록 재부착
        if isinstance(self._npcs_list, list):
            for ent in self._temp_npcs:
                if ent is not None and ent not in self._npcs_list:
                    self._npcs_list.append(ent)
        for r in self._racers:
            if (not r.is_player) and r.entity is None and self.state in (
                ST_COUNTDOWN,
                ST_RACE,
                ST_FINISH,
            ):
                # 스폰 실패·정리 누락 시 재시도
                try:
                    from engine import MaskWalkingCharacter

                    ent = MaskWalkingCharacter(
                        r.char_id, [float(r.pos[0]), float(r.pos[1])], {"ysort": "ground"}
                    )
                    ent._racing_temp = True
                    ent.is_visible = False
                    if isinstance(self._npcs_list, list) and ent not in self._npcs_list:
                        self._npcs_list.append(ent)
                    self._temp_npcs.append(ent)
                    r.entity = ent
                except Exception as e:
                    print(f"[racing] npc respawn fail ({r.char_id}): {e}")
            ent = r.entity
            if ent is None:
                continue
            try:
                ent.pos[0] = float(r.pos[0])
                ent.pos[1] = float(r.pos[1])
                ent.target = list(ent.pos)
                ent.path = []
                # 옆시야 빌보드: 화면에서 대체로 좌→우로 달리므로 right
                ent.direction = "right"
                if self.state in (ST_RACE, ST_COUNTDOWN) and r.speed > 8.0:
                    ent.state = "run"
                elif self.state == ST_RACE:
                    ent.state = "walk"
                else:
                    ent.state = "idle"
                # 메인 update_anim 이 스킵되어도 이미지가 비지 않게
                if getattr(ent, "image", None) is None:
                    frames = self._idle_frames(r.char_id, "right")
                    if frames:
                        ent.image = frames[0]
            except Exception:
                pass

    # --- physics -----------------------------------------------------------

    def _update_racer(self, r: RacerState, dt: float, *, racing: bool) -> None:
        """
        직선은 heading 으로 달리고, 코너에서는 관성으로 앞으로 나가며
        앞쪽 경로점(룩어헤드)을 향해 heading 을 서서히 튼다.
        위치는 경로에 강제 스냅하지 않음 — 약한 인력만.
        """
        path = self._path
        if path is None or r.finished:
            return
        lane_spd = float(self._p("lane_lerp", 4.5))
        r.lane = _lerp(r.lane, r.lane_target, 1.0 - math.exp(-lane_spd * dt))

        look = float(self._p("corner_lookahead_px", 90.0))
        turn_ahead = path.lookahead_turn(r.s, look)
        lane_w = float(self._p("lane_width", 30.0))
        lane_off = float(r.lane) * lane_w
        # 목표: 앞 경로점 chase (세그먼트 접선 스냅 대신 → 관성 코너)
        # ★ 자기 레인 중심선을 chase — 중심선을 chase 하면 1·3레인 발 위치가
        #   레인 중앙보다 안쪽으로 치우친다 (pull과의 평형점이 어긋남)
        lx, ly, look_tang, _ = path.sample(r.s + look)
        lx += -math.sin(look_tang) * lane_off
        ly += math.cos(look_tang) * lane_off
        desired = math.atan2(ly - r.pos[1], lx - r.pos[0])
        # 자기 레인 중심선에서 많이 벗어나면 룩어헤드 접선 비중↑ (트랙 복귀)
        cx, cy, tang0, _ = path.sample(r.s)
        cx += -math.sin(tang0) * lane_off
        cy += math.cos(tang0) * lane_off
        off = math.hypot(r.pos[0] - cx, r.pos[1] - cy)
        blend = max(0.0, min(0.55, off / 70.0))
        err_to_pt = _angle_wrap(desired - r.heading)
        err_to_tang = _angle_wrap(look_tang - r.heading)
        desired = _angle_wrap(r.heading + err_to_pt * (1.0 - blend) + err_to_tang * blend)

        turn_rate = float(self._p("turn_rate_rad", 2.2))
        if float(r.freeze_t or 0.0) > 0.0:
            r.freeze_t = max(0.0, float(r.freeze_t) - dt)
            r.speed = 0.0
            return
        sp = self._secret_spin
        if sp and not sp.get("applied") and sp.get("racer") is r:
            r.speed = max(0.0, float(r.speed) * 0.25)
        if float(r.bump_slow_t or 0.0) > 0.0:
            r.bump_slow_t = max(0.0, float(r.bump_slow_t) - dt)
        # 버프 틱
        if r.buff_t > 0.0:
            r.buff_t = max(0.0, float(r.buff_t) - dt)
            if r.buff_t <= 0.0:
                r.speed_mul = 1.0
                r.buff_label = ""
        else:
            r.speed_mul = 1.0

        turn_rate *= max(0.30, 1.0 - 0.40 * (r.speed / max(1.0, float(self._p("max_speed", 140.0)))))
        r.heading = _angle_approach(r.heading, desired, turn_rate * dt)

        max_spd = float(self._p("max_speed", 140.0)) * max(0.15, float(r.speed_mul))
        max_spd *= max(0.2, float(getattr(r, "weather_slow_mul", 1.0) or 1.0))
        min_spd = float(self._p("min_corner_speed", 45.0)) * max(0.15, min(1.0, float(r.speed_mul)))
        corner_k = float(self._p("corner_brake", 1.35))
        # 헤딩이 목표와 어긋난 정도도 감속에 반영 (관성으로 미끄러질 때)
        steer_err = abs(_angle_wrap(desired - r.heading))
        target_spd = max_spd / (1.0 + turn_ahead * corner_k + steer_err * 0.85)
        target_spd = max(min_spd, min(max_spd, target_spd))
        if not racing:
            target_spd = 0.0

        accel = float(self._p("accel", 55.0))
        brake = float(self._p("brake", 90.0))
        if float(getattr(r, "slipstream_mul", 1.0) or 1.0) > 1.01:
            accel += float(self._p("slipstream_accel_bonus", 28.0) or 28.0)
        if r.speed < target_spd:
            r.speed = min(target_spd, r.speed + accel * dt)
        else:
            r.speed = max(target_spd, r.speed - brake * dt)

        # ★ 관성 이동: heading 방향으로 적분 (경로 세그먼트에 붙지 않음)
        r.pos[0] += math.cos(r.heading) * r.speed * dt
        r.pos[1] += math.sin(r.heading) * r.speed * dt

        # 경로+차선으로 약한 인력 (코너에서 밖으로 살짝 나가게)
        lane_w = float(self._p("lane_width", 26.0))
        new_s = path.nearest_s(r.pos[0], r.pos[1])
        px, py, tang, _ = path.sample(new_s)
        nx = -math.sin(tang)
        ny = math.cos(tang)
        tx = px + nx * r.lane * lane_w
        ty = py + ny * r.lane * lane_w
        pull = float(self._p("path_pull", 2.2))
        k = 1.0 - math.exp(-pull * dt)
        r.pos[0] = _lerp(r.pos[0], tx, k)
        r.pos[1] = _lerp(r.pos[1], ty, k)

        # 랩: nearest_s 랩어라운드
        r.prev_s = r.s
        r.s = path.wrap_s(new_s)
        if path.closed and racing and path.length > 1.0:
            # 큰 역행이 아닌 전진 랩 크로스
            if r.prev_s > path.length * 0.75 and r.s < path.length * 0.25:
                r.lap += 1
                if r.lap >= self._lap_goal:
                    r.finished = True
                    r.speed = 0.0

        if (not r.is_player) and racing and not r.finished:
            r.ai_timer -= dt
            if r.ai_timer <= 0.0:
                r.ai_timer = random.uniform(1.2, 3.0)
                # 비어 있는 레인만 (가까우면 같은 레인 금지)
                candidates = [LANE_UPPER, LANE_CENTER, LANE_LOWER]
                random.shuffle(candidates)
                for cand in candidates:
                    if self._try_set_lane(r, cand):
                        break

    def _update_camera_heading(self, dt: float = 0.016) -> None:
        """
        카메라 모드:
        - side: 플레이어 실제 진행의 옆(기존 SNES풍)
        - back: 플레이어 뒤(일반 레이싱 추적 시점)
        경로 접선을 쓰면 코너에서 카메라가 재설정(스냅)되므로 금지.
        """
        player_r = next((x for x in self._racers if x.is_player), None)
        if player_r is None:
            self.mode7_cam_heading = None
            self.mode7_player_x_frac = None
            return
        mode = str(getattr(self, "_camera_mode", "side") or "side").strip().lower()
        if mode == "back":
            # Mode7 카메라 heading 은 "어느 방향을 보느냐"라서
            # 뒤쫓는 카메라는 플레이어 진행 방향을 그대로 바라봐야 한다.
            desired = float(player_r.heading)
            self.mode7_player_x_frac = 0.5
        else:
            side = float(self._p("cam_side_sign", -1.0))
            desired = float(player_r.heading) + side * (math.pi * 0.5)
            self.mode7_player_x_frac = None
        if self._cam_heading is None:
            self._cam_heading = desired
        else:
            cam_rate = float(self._p("cam_turn_rate_rad", 3.4))
            self._cam_heading = _angle_approach(self._cam_heading, desired, cam_rate * max(0.0, float(dt)))
        self.mode7_cam_heading = float(self._cam_heading)

    # --- tick / input ------------------------------------------------------

    def tick(self, dt_sec: float, player, now_ms: int) -> None:
        dt = max(0.0, min(0.1, float(dt_sec)))
        if self.state == ST_COUNTDOWN:
            self._countdown_t -= dt
            self._sync_entities_to_racers()
            self._update_camera_heading(dt)
            self._tick_lane_buttons(dt)
            if self._countdown_t <= 0.0:
                self.state = ST_RACE
                self._msg = "레이스!"
            return
        if self.state == ST_RACE:
            self._race_time += dt
            self._tick_race_extras(dt)
            for r in self._racers:
                self._update_racer(r, dt, racing=True)
            self._tick_item_pickups()
            if self._item_msg_t > 0.0:
                self._item_msg_t = max(0.0, self._item_msg_t - dt)
            self._sync_entities_to_racers()
            self._update_camera_heading(dt)
            self._tick_lane_buttons(dt)
            # 선착승: 누구든 먼저 랩 달성하면 종료 (경쟁). 기록용은 플레이어 골만.
            versus = str(self._race_mode or "record").strip().lower() == "versus"
            if versus:
                finisher = next((x for x in self._racers if x.finished), None)
                if finisher is not None:
                    self._winner = finisher
                    self._won = bool(finisher.is_player)
                    self.state = ST_FINISH
                    self._finish_t = float(self._p("finish_hold_sec", 2.5))
                    if finisher.is_player:
                        self._msg = "1등!"
                    else:
                        self._msg = f"{self._char_label(finisher.char_id)} 우승"
            else:
                pr = next((x for x in self._racers if x.is_player), None)
                if pr is not None and pr.finished:
                    self._winner = pr
                    self._won = True
                    self.state = ST_FINISH
                    self._finish_t = float(self._p("finish_hold_sec", 2.5))
                    self._msg = "골인!"
            return
        if self.state == ST_FINISH:
            self._finish_t -= dt
            self._sync_entities_to_racers()
            self._update_camera_heading(dt)
            if self._finish_t <= 0.0:
                self._cleanup_temp_npcs()
                self._restore_player_char()
                self._racers = []
                self.field_rotate3d_target = 0.0
                self.mode7_cam_heading = None
                self._cam_heading = None
                self.state = ST_MENU
                self._msg = "메뉴"
                try:
                    lw, lh = self._logical_screen_size()
                    self._layout_menu_rects(lw, lh)
                except Exception:
                    pass
            return

    def on_pointer_down(self, screen_xy, world_xy, now_ms: int) -> bool:
        if self.state in (ST_MENU, ST_PICK_CHAR):
            act = self._menu_hit(screen_xy)
            return self._apply_menu_action(act)
        if self.state in (ST_RACE, ST_COUNTDOWN, ST_FINISH):
            px_py = None
            if screen_xy:
                try:
                    px_py = (int(screen_xy[0]), int(screen_xy[1]))
                except (TypeError, ValueError, IndexError):
                    px_py = None
            # 게임 중지 확인창이 떠 있으면 예/아니오만 받는다
            if self._race_quit_confirm:
                if px_py:
                    for rrect, act in self._race_confirm_rects:
                        if not rrect.collidepoint(px_py):
                            continue
                        self._race_quit_confirm = False
                        if act == "yes":
                            self._quit_session()
                        return True
                return True
            # 왼쪽 위 옵션 버튼 (기존 '경기 중지' 오버레이 대체)
            if px_py and self._option_btn_rect and self._option_btn_rect.collidepoint(px_py):
                self._race_options_open = not bool(self._race_options_open)
                return True
            if self._race_options_open:
                if px_py:
                    for rrect, act in self._race_opt_rects:
                        if not rrect.collidepoint(px_py):
                            continue
                        if act == "camera":
                            self._camera_mode = "back" if str(self._camera_mode or "side") == "side" else "side"
                            self._cam_heading = None
                        elif act == "minimap":
                            self._minimap_user_enabled = not bool(self._minimap_user_enabled)
                        elif act == "stop":
                            self._race_options_open = False
                            self._race_quit_confirm = True
                        return True
                # 팝업 밖 클릭 → 닫기
                self._race_options_open = False
                return True
            # 레인 화살표 (카운트다운·레이스 중 한 칸씩)
            if self.state in (ST_RACE, ST_COUNTDOWN):
                if self._handle_lane_button(screen_xy):
                    return True
            return True
        return True

    def on_primary_key(self, key: int) -> bool:
        if key == pygame.K_ESCAPE:
            if self.state in (ST_RACE, ST_COUNTDOWN):
                if self._race_quit_confirm:
                    self._race_quit_confirm = False
                else:
                    self._race_options_open = False
                    self._race_quit_confirm = True
                return True
            if self.state == ST_PICK_CHAR:
                if self._char_pending_ix is not None:
                    # 확인창(서브메뉴)이 떠 있으면 ESC = 확인 취소
                    self._char_pending_ix = None
                    return True
                self.state = ST_MENU
                return True
            if self.state == ST_MENU:
                if self._options_open:
                    # 옵션 서브메뉴가 열려 있으면 ESC = 팝업 닫기
                    self._options_open = False
                    return True
                self._quit_session()
                return True
        # 데스크톱: 위/아래 키로도 한 칸 이동
        if self.state in (ST_RACE, ST_COUNTDOWN):
            if key in (pygame.K_UP, pygame.K_w):
                self._nudge_player_lane(-1)
                return True
            if key in (pygame.K_DOWN, pygame.K_s):
                self._nudge_player_lane(1)
                return True
        return False

    def _lane_btn_draw_size(self, screen_w: int) -> int:
        try:
            sz320 = float(self._p("lane_btn_size_px_320", 40.0) or 40.0)
        except (TypeError, ValueError):
            sz320 = 40.0
        return max(28, int(round(scale_ui_text_px(sz320, screen_w=screen_w))))

    def _layout_lane_buttons(self, w: int, h: int) -> None:
        """화면 왼쪽: 위 화살표, 그 아래 아래 화살표."""
        size = self._lane_btn_draw_size(w)
        try:
            gap320 = float(self._p("lane_btn_gap_px_320", 10.0) or 10.0)
        except (TypeError, ValueError):
            gap320 = 10.0
        gap = max(4, int(round(scale_ui_text_px(gap320, screen_w=w))))
        try:
            mx = float(self._p("lane_btn_margin_x_frac", 0.03) or 0.03)
        except (TypeError, ValueError):
            mx = 0.03
        try:
            cy_frac = float(self._p("lane_btn_center_y_frac", 0.55) or 0.55)
        except (TypeError, ValueError):
            cy_frac = 0.55
        mx = max(0.0, min(0.2, mx))
        cy_frac = max(0.25, min(0.85, cy_frac))
        x = int(w * mx)
        total_h = size * 2 + gap
        y0 = int(h * cy_frac) - total_h // 2
        y0 = max(8, min(h - total_h - 8, y0))
        # 맵 설정이 바뀌었을 수 있어 애니 이름 동기화
        up_name = str(self._p("lane_btn_up_anim", "lane_up") or "lane_up")
        down_name = str(self._p("lane_btn_down_anim", "lane_down") or "lane_down")
        if up_name != self._lane_btn_up.anim_name:
            self._lane_btn_up.anim_name = up_name
            self._lane_btn_up.reload_frames()
        if down_name != self._lane_btn_down.anim_name:
            self._lane_btn_down.anim_name = down_name
            self._lane_btn_down.reload_frames()
        self._lane_btn_up.ensure_fallback(size)
        self._lane_btn_down.ensure_fallback(size)
        self._lane_btn_up.layout(pygame.Rect(x, y0, size, size))
        self._lane_btn_down.layout(pygame.Rect(x, y0 + size + gap, size, size))

    def _tick_lane_buttons(self, dt: float) -> None:
        try:
            fps = float(self._p("lane_btn_anim_fps", 8.0) or 8.0)
        except (TypeError, ValueError):
            fps = 8.0
        for btn in self._lane_btns:
            btn.tick(dt, fps)

    def _draw_lane_buttons(self, surf: pygame.Surface, w: int, h: int) -> None:
        if surf is None:
            return
        if self.state not in (ST_COUNTDOWN, ST_RACE):
            return
        self._layout_lane_buttons(w, h)
        size = self._lane_btn_draw_size(w)
        for btn in self._lane_btns:
            btn.draw(surf, size)

    def _nudge_player_lane(self, direction: int) -> None:
        """
        direction -1 = 위(A 쪽), +1 = 아래(C 쪽). 한 레인씩.
        가까이에 다른 레이서가 같은 레인이면 거부.
        """
        pr = next((x for x in self._racers if x.is_player), None)
        if pr is None or pr.finished:
            return
        ix = _lane_offset_to_step_index(float(pr.lane_target))
        nix = max(0, min(len(_LANE_STEP_ORDER) - 1, ix + int(direction)))
        if nix == ix:
            return
        want = float(_LANE_STEP_ORDER[nix])
        if not self._try_set_lane(pr, want):
            self._item_msg = "차선 사용 중"
            self._item_msg_t = 0.7

    def _handle_lane_button(self, screen_xy) -> bool:
        """왼쪽 화살표 히트 시 한 칸 이동. 처리했으면 True."""
        if not screen_xy:
            return False
        w, h = self._ui_screen_wh or self._logical_screen_size()
        self._layout_lane_buttons(int(w), int(h))
        if self._lane_btn_up.hit(screen_xy):
            self._lane_btn_up.press()
            self._nudge_player_lane(-1)
            return True
        if self._lane_btn_down.hit(screen_xy):
            self._lane_btn_down.press()
            self._nudge_player_lane(1)
            return True
        return False

    def _draw_race_options(self, surf: pygame.Surface, w: int, h: int, small) -> None:
        """레이스 중 왼쪽 위 '옵션' 버튼 + 팝업 (카메라 옆/뒤 · 미니맵 켬/끔 · 게임 중지)."""
        label = small.render("옵션", True, (240, 248, 255))
        pad_x, pad_y = 8, 4
        rect = pygame.Rect(8, 8, label.get_width() + pad_x * 2, label.get_height() + pad_y * 2)
        self._option_btn_rect = rect
        pygame.draw.rect(surf, (40, 58, 88), rect, border_radius=6)
        pygame.draw.rect(surf, (120, 160, 220), rect, 1, border_radius=6)
        surf.blit(label, (rect.x + pad_x, rect.y + pad_y))

        self._race_opt_rects = []
        if not self._race_options_open:
            return
        cam_back = str(self._camera_mode or "side") == "back"
        rows = [
            ("camera", f"카메라 : {'뒤' if cam_back else '옆'}", (46, 52, 70)),
            ("minimap", f"미니맵 : {'켬' if self._minimap_user_enabled else '끔'}", (46, 52, 70)),
            ("stop", "게임 중지", (70, 40, 40)),
        ]
        pw = max(140, int(round(w * 0.22)))
        row_h = max(24, int(round(h * 0.05)))
        gap = 6
        ph = len(rows) * row_h + (len(rows) - 1) * gap + 16
        px, py = rect.x, rect.bottom + 6
        popup_rect = pygame.Rect(px, py, pw, ph)
        popup = pygame.Surface((pw, ph), pygame.SRCALPHA)
        popup.fill((24, 28, 40, 230))
        surf.blit(popup, popup_rect.topleft)
        pygame.draw.rect(surf, (180, 200, 235), popup_rect, 2, border_radius=8)
        ry = py + 8
        for act, text, bg in rows:
            rrect = pygame.Rect(px + 8, ry, pw - 16, row_h)
            pygame.draw.rect(surf, bg, rrect, border_radius=6)
            pygame.draw.rect(surf, (120, 140, 170), rrect, 1, border_radius=6)
            t = small.render(text, True, (240, 248, 255))
            surf.blit(t, (rrect.x + 8, rrect.centery - t.get_height() // 2))
            self._race_opt_rects.append((rrect, act))
            ry += row_h + gap
        # 팝업 밖 클릭 판정용으로 팝업 영역도 저장
        self._race_opt_rects.append((popup_rect, "popup"))

    def _draw_race_quit_confirm(self, surf: pygame.Surface, w: int, h: int, small) -> None:
        """'게임 중지' 확인창 — 화면 중앙 딤 + 예/아니오."""
        self._race_confirm_rects = []
        if not self._race_quit_confirm:
            return
        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 130))
        surf.blit(dim, (0, 0))
        msg = small.render("정말 게임을 중지할까요?", True, (245, 245, 250))
        bw = max(60, int(round(w * 0.14)))
        bh = max(26, int(round(h * 0.06)))
        gap = max(10, int(round(w * 0.03)))
        pw = max(msg.get_width() + 32, bw * 2 + gap + 32)
        ph = msg.get_height() + bh + 16 * 2 + 10
        px = w // 2 - pw // 2
        py = h // 2 - ph // 2
        box_rect = pygame.Rect(px, py, pw, ph)
        box = pygame.Surface((pw, ph), pygame.SRCALPHA)
        box.fill((24, 28, 40, 235))
        surf.blit(box, box_rect.topleft)
        pygame.draw.rect(surf, (180, 200, 235), box_rect, 2, border_radius=8)
        surf.blit(msg, (px + pw // 2 - msg.get_width() // 2, py + 16))
        by = py + 16 + msg.get_height() + 10
        for i, (act, text, bg) in enumerate((
            ("yes", "예", (70, 40, 40)),
            ("no", "아니오", (40, 58, 88)),
        )):
            bx = px + pw // 2 - (bw * 2 + gap) // 2 + i * (bw + gap)
            rrect = pygame.Rect(bx, by, bw, bh)
            pygame.draw.rect(surf, bg, rrect, border_radius=6)
            pygame.draw.rect(surf, (120, 140, 170), rrect, 1, border_radius=6)
            t = small.render(text, True, (240, 248, 255))
            surf.blit(t, (rrect.centerx - t.get_width() // 2, rrect.centery - t.get_height() // 2))
            self._race_confirm_rects.append((rrect, act))

    def _layout_camera_popup(self, w: int, h: int) -> None:
        """옵션 서브메뉴 팝업 — 열리는 동안 상위 메뉴는 숨기므로 화면 중앙에 배치."""
        pw = max(160, int(round(w * 0.34)))
        row_h = max(24, int(round(h * 0.16 * 0.28)))
        ph = 28 + row_h * 3 + 8 * 2 + 10  # 제목 + 3행(카메라 옆/뒤 + 미니맵) + 간격
        px = w // 2 - pw // 2
        py = max(8, int(round(h * 0.32)))
        self._camera_popup_rect = pygame.Rect(px, py, pw, ph)
        inner_x = px + 10
        inner_w = pw - 20
        self._camera_side_rect = pygame.Rect(inner_x, py + 28, inner_w, row_h)
        self._camera_back_rect = pygame.Rect(inner_x, py + 28 + row_h + 8, inner_w, row_h)
        self._minimap_toggle_rect = pygame.Rect(inner_x, py + 28 + (row_h + 8) * 2, inner_w, row_h)

    # --- menu UI -----------------------------------------------------------

    def _logical_screen_size(self) -> Tuple[int, int]:
        try:
            return int(CONFIG.get("WIDTH", 640) or 640), int(CONFIG.get("HEIGHT", 480) or 480)
        except Exception:
            return 640, 480

    def _layout_menu_rects(self, w: int, h: int) -> None:
        self._menu_rects = []
        bw_frac = float(get_activity_ui("racing", "menu_button_width_frac", 0.72) or 0.72)
        bh_frac = float(get_activity_ui("racing", "menu_button_height_frac", 0.10) or 0.10)
        if self.state == ST_MENU:
            bw, bh = int(w * bw_frac), int(h * bh_frac)
            bx = w // 2 - bw // 2
            y0 = int(h * 0.28)
            for i, act in enumerate(("1p", "1p_vs", "options", "exit")):
                self._menu_rects.append((pygame.Rect(bx, y0 + i * (bh + 10), bw, bh), act))
            return
        if self.state == ST_PICK_CHAR:
            if self._char_pending_ix is not None:
                bw, bh = int(w * 0.34), int(h * 0.09)
                gap = int(w * 0.04)
                cy = int(h * 0.72)
                total = bw * 2 + gap
                bx = w // 2 - total // 2
                self._menu_rects.append((pygame.Rect(bx, cy, bw, bh), "char_yes"))
                self._menu_rects.append((pygame.Rect(bx + bw + gap, cy, bw, bh), "char_no"))
            else:
                self._layout_char_pick_rects(w, h)
                for rect, ix in self._char_pick_rects:
                    self._menu_rects.append((rect, f"char_pick:{ix}"))
            bw, bh = max(52, int(w * 0.16)), max(24, int(h * 0.07))
            self._menu_rects.append(
                (pygame.Rect(int(w * 0.04), h - bh - int(h * 0.04), bw, bh), "menu_back")
            )

    def _layout_char_pick_rects(self, w: int, h: int) -> None:
        self._char_pick_rects = []
        opts = list(self._char_opts or [])
        if not opts:
            return
        n = min(8, len(opts))
        cols, rows = _CHAR_PICK_COLS, _CHAR_PICK_ROWS
        pad_x = int(w * 0.03)
        pad_top = int(h * 0.22)
        pad_bot = int(h * 0.13)
        gap_x = max(2, int(w * 0.006))
        gap_y = max(2, int(h * 0.010))
        avail_w = w - pad_x * 2
        avail_h = h - pad_top - pad_bot
        cell_w = max(28, (avail_w - gap_x * max(0, cols - 1)) // cols)
        cell_h = max(36, (avail_h - gap_y * max(0, rows - 1)) // rows)
        total_w = cols * cell_w + max(0, cols - 1) * gap_x
        x0 = w // 2 - total_w // 2
        y0 = pad_top
        for i in range(n):
            col = i % cols
            row = i // cols
            rx = x0 + col * (cell_w + gap_x)
            ry = y0 + row * (cell_h + gap_y)
            self._char_pick_rects.append((pygame.Rect(rx, ry, cell_w, cell_h), i))

    def _menu_hit(self, screen_xy) -> Optional[str]:
        if not screen_xy:
            return None
        try:
            px, py = int(screen_xy[0]), int(screen_xy[1])
        except (TypeError, ValueError, IndexError):
            return None
        wh = self._ui_screen_wh
        if isinstance(wh, (tuple, list)) and len(wh) >= 2:
            lw, lh = int(wh[0]), int(wh[1])
        else:
            lw, lh = self._logical_screen_size()
        self._layout_menu_rects(lw, lh)
        if self.state == ST_MENU and self._options_open:
            self._layout_camera_popup(lw, lh)
            try:
                if self._camera_side_rect and self._camera_side_rect.collidepoint(px, py):
                    return "camera_side"
                if self._camera_back_rect and self._camera_back_rect.collidepoint(px, py):
                    return "camera_back"
                if self._minimap_toggle_rect and self._minimap_toggle_rect.collidepoint(px, py):
                    return "minimap_toggle"
                if self._camera_popup_rect and self._camera_popup_rect.collidepoint(px, py):
                    return "popup"
            except Exception:
                pass
            # 팝업이 열려 있는 동안엔 뒤의 상위 메뉴 버튼으로 클릭이 통과하지 않게
            # 팝업 밖 클릭 = 팝업 닫기만 수행
            return "popup_close"
        for rect, action in self._menu_rects:
            if rect.collidepoint(px, py):
                return action
        return None

    def _apply_menu_action(self, act: Optional[str]) -> bool:
        if not act:
            return False
        if self.state == ST_MENU:
            if act == "1p":
                self._race_mode = "record"
                self._options_open = False
                self.state = ST_PICK_CHAR
                self._char_pending_ix = None
                self._msg = "캐릭터 선택 (기록)"
                return True
            if act == "1p_vs":
                self._race_mode = "versus"
                self._options_open = False
                self.state = ST_PICK_CHAR
                self._char_pending_ix = None
                self._msg = "캐릭터 선택 (경쟁)"
                return True
            if act == "options":
                self._options_open = not bool(self._options_open)
                return True
            if act == "camera_side":
                self._camera_mode = "side"
                self._cam_heading = None
                self._options_open = False
                return True
            if act == "camera_back":
                self._camera_mode = "back"
                self._cam_heading = None
                self._options_open = False
                return True
            if act == "minimap_toggle":
                self._minimap_user_enabled = not bool(self._minimap_user_enabled)
                return True
            if act == "popup":
                return True
            if act == "popup_close":
                self._options_open = False
                return True
            if act == "exit":
                self._quit_session()
                return True
        if self.state == ST_PICK_CHAR:
            if act == "menu_back":
                if self._char_pending_ix is not None:
                    self._char_pending_ix = None
                else:
                    self.state = ST_MENU
                return True
            if act.startswith("char_pick:"):
                try:
                    ix = int(act.split(":", 1)[1])
                except Exception:
                    return True
                if 0 <= ix < len(self._char_opts):
                    self._char_pending_ix = ix
                return True
            if act == "char_yes" and self._char_pending_ix is not None:
                ix = int(self._char_pending_ix)
                self._char_pending_ix = None
                self._apply_player_char(self._char_opts[ix])
                self._start_countdown()
                return True
            if act == "char_no":
                self._char_pending_ix = None
                return True
        return False

    def _idle_frames(self, char_id: str, direction: str = "right") -> List:
        key = (str(char_id), str(direction))
        if key in self._idle_cache:
            return self._idle_cache[key]
        from engine import load_anim_auto

        frames = load_anim_auto(char_id, "idle", "left") or []
        if direction == "right" and frames:
            frames = [pygame.transform.flip(img, True, False) for img in frames]
        self._idle_cache[key] = frames
        return frames

    def _blit_idle(self, surf, frames, center_xy, max_h: int) -> None:
        if not frames:
            return
        img = frames[0]
        try:
            iw, ih = img.get_width(), img.get_height()
        except Exception:
            return
        if ih <= 0:
            return
        sc = min(1.0, float(max_h) / float(ih))
        if sc < 0.99:
            img = pygame.transform.smoothscale(img, (max(1, int(iw * sc)), max(1, int(ih * sc))))
        dx, dy = blit_topleft_bottom_center(
            int(center_xy[0]), int(center_xy[1]), img.get_width(), img.get_height()
        )
        surf.blit(img, (dx, dy))

    def _char_label(self, cid: str) -> str:
        """캐릭터 표시 이름 (char_defs name — 예: 여름이)."""
        try:
            nm = str(get_char_ui_name(cid) or "").strip()
            if nm:
                return nm
        except Exception:
            pass
        try:
            info = CHAR_ASSETS.get(cid) or {}
            return str(info.get("label") or info.get("name") or cid)
        except Exception:
            return str(cid or "?")

    def _racer_hud_label(self, r: RacerState) -> str:
        """네임박스 이름 — 역할색과 별도로 캐릭터 이름 표시."""
        if r is None:
            return "?"
        return self._char_label(getattr(r, "char_id", "") or "")

    def _racer_hud_pastel(self, r: RacerState) -> Tuple[int, int, int]:
        """NPC1=파란 / 플레이어=녹색 / NPC2=빨간 파스텔."""
        role = str(getattr(r, "hud_role", "") or "")
        if role == "player":
            return (168, 218, 178)
        if role == "npc2":
            return (236, 170, 170)
        return (168, 198, 232)  # npc1 기본

    def _plain_hud_font(self, size_px: int):
        """
        네임박스·메뉴용 — outline/force_color 없이 호출색 그대로.
        (hud_racing force_color=True 면 버튼 글자가 검정이 되어 안 보임)
        엔진 _resolve_ui_font 캐시를 쓴다 (TTF 반복 로드·캐시 전체 삭제 방지).
        """
        sz = max(8, min(96, int(size_px)))
        try:
            from engine import get_font_profile, _resolve_ui_font

            st = dict(get_font_profile("hud_racing") or {})
            st["outline_enabled"] = False
            st["force_color"] = False
            st["soft_px_320"] = 0
            fk = str(st.get("font_key") or "default").strip() or "default"
            return _resolve_ui_font(fk, sz, outlined=True, style=st)
        except Exception:
            try:
                return pygame.font.SysFont("malgungothic", sz)
            except Exception:
                return pygame.font.Font(None, sz)

    def _racer_feet_screen_xy(
        self, ctx: FieldDrawContext, r: RacerState
    ) -> Tuple[Optional[float], Optional[float]]:
        """발 화면 좌표. Mode7 플레이어는 하단 빌보드 고정점."""
        if r is None or ctx is None:
            return None, None
        m7 = getattr(ctx, "mode7_ctx", None)
        if m7 and r.is_player:
            try:
                from engine import rotate3d_mode7_player_screen

                return rotate3d_mode7_player_screen(
                    m7, height_off=0.0, zoom=float(ctx.z)
                )
            except Exception:
                pass
        return self._world_to_draw_xy(
            ctx, float(r.pos[0]), float(r.pos[1]), 0.0
        )

    def _draw_racer_lane_nameboxes(self, ctx: FieldDrawContext) -> None:
        """
        레이서 머리 위 네임박스 (오버레이급 · 원근 스케일 없음).
        월드 오브젝트에 가려져도 보이도록 draw_screen 최상단에서 그림.
        폰트 ~11(320기준), 오른쪽에 현재 레인 A/B/C.
        """
        if ctx is None or ctx.surf is None:
            return
        if self.state not in (ST_COUNTDOWN, ST_RACE, ST_FINISH):
            return
        surf = ctx.surf
        try:
            sw = int(surf.get_width())
            sh = int(surf.get_height())
        except Exception:
            return
        # 원근과 무관 — UI 텍스트 스케일만 (크기 일정). outline 없는 plain 폰트.
        name_px = max(10, int(round(scale_ui_text_px(11))))
        lane_px = max(9, int(round(scale_ui_text_px(10))))
        try:
            name_font = self._plain_hud_font(name_px)
            lane_font = self._plain_hud_font(lane_px)
        except Exception:
            return
        try:
            head_off = float(self._p("namebox_head_off_px", 42.0) or 42.0)
        except (TypeError, ValueError):
            head_off = 42.0
        head_off = max(24.0, min(80.0, head_off))
        pad_x, pad_y = 5, 2
        gap = 4

        # 플레이어를 마지막에 그려 겹칠 때 이름이 가려지지 않게
        ordered = sorted(
            (r for r in self._racers if r is not None),
            key=lambda x: (1 if x.is_player else 0),
        )
        for r in ordered:
            if r.finished and self.state != ST_FINISH:
                continue
            fx, fy = self._racer_feet_screen_xy(ctx, r)
            if fx is None or fy is None:
                continue
            try:
                cx = int(round(float(fx)))
                cy = int(round(float(fy) - head_off))
            except (TypeError, ValueError):
                continue

            name = self._racer_hud_label(r) or "?"
            lane_ch = _lane_offset_to_letter(float(r.lane))
            fill = self._racer_hud_pastel(r)
            try:
                name_s = name_font.render(str(name), True, (32, 36, 42))
                lane_s = lane_font.render(str(lane_ch), True, (32, 36, 42))
            except Exception:
                continue
            nw, nh = int(name_s.get_width()), int(name_s.get_height())
            lw, lh = int(lane_s.get_width()), int(lane_s.get_height())
            if nw < 1 and lw < 1:
                continue
            box_h = max(nh, lh) + pad_y * 2
            box_w = max(1, nw + gap + lw + pad_x * 2)
            # 박스 전체가 화면 안에 들어오게 — 중심만 클램프하면 왼쪽(이름)이 잘림
            rx = int(cx - box_w // 2)
            ry = int(cy - box_h)
            rx = max(2, min(sw - box_w - 2, rx))
            ry = max(2, min(sh - box_h - 2, ry))
            rect = pygame.Rect(rx, ry, box_w, box_h)
            try:
                chip = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
                chip.fill((*fill, 235))
                surf.blit(chip, rect.topleft)
            except Exception:
                pygame.draw.rect(surf, fill, rect)
            border = tuple(max(0, min(255, c - 40)) for c in fill)
            try:
                pygame.draw.rect(surf, border, rect, 1, border_radius=3)
            except TypeError:
                pygame.draw.rect(surf, border, rect, 1)
            if nw > 0:
                surf.blit(name_s, (rect.x + pad_x, rect.y + (box_h - nh) // 2))
            if lw > 0:
                surf.blit(
                    lane_s,
                    (rect.right - pad_x - lw, rect.y + (box_h - lh) // 2),
                )

    # --- draw --------------------------------------------------------------

    def draw_world(self, ctx: FieldDrawContext) -> None:
        """경로 위 아이템 표시 (+ 디버그 경로). Mode7 ctx가 있으면 Mode7 투영."""
        if ctx is None or ctx.surf is None:
            return
        path = self._path
        if path is not None and bool(self._p("debug_draw_path", False)):
            pts = []
            steps = 64
            for i in range(steps):
                s = path.length * (i / float(steps))
                x, y, _, _ = path.sample(s)
                sx, sy = self._world_to_draw_xy(ctx, x, y, 0.0)
                if sx is not None:
                    pts.append((int(sx), int(sy)))
            if len(pts) >= 2:
                try:
                    pygame.draw.lines(ctx.surf, (255, 220, 80), True, pts, 2)
                except Exception:
                    pass

        if self.state not in (ST_COUNTDOWN, ST_RACE, ST_FINISH):
            return
        try:
            h_off = float(self._p("item_draw_height", 10.0) or 10.0)
        except (TypeError, ValueError):
            h_off = 10.0
        for it in self._items:
            if it.taken:
                continue
            sx, sy = self._world_to_draw_xy(ctx, it.wx, it.wy, h_off)
            if sx is None:
                continue
            img = it.surf
            if img is None:
                continue
            # Mode7 깊이 스케일 (project zoom 포함 → 추가 z 곱하지 않음)
            sc = float(ctx.z)
            m7 = getattr(ctx, "mode7_ctx", None)
            if m7:
                try:
                    from engine import rotate3d_mode7_project

                    pr = rotate3d_mode7_project(it.wx, it.wy, m7, height_off=h_off, zoom=float(ctx.z))
                    if pr and pr.get("valid", pr.get("visible")):
                        sc = float(pr.get("scale", 1.0) or 1.0)
                except Exception:
                    sc = 1.0
            try:
                iw, ih = img.get_width(), img.get_height()
                tw = max(6, int(round(iw * sc)))
                th = max(6, int(round(ih * sc)))
                if (tw, th) != (iw, ih):
                    img2 = pygame.transform.smoothscale(img, (tw, th))
                else:
                    img2 = img
            except Exception:
                img2 = img
            # Mode7: 발점이 아니라 스케일된 아이템 사각형으로 컬링
            if m7:
                try:
                    from engine import rotate3d_mode7_bounds_visible

                    if not rotate3d_mode7_bounds_visible(
                        float(sx),
                        float(sy),
                        img2.get_width(),
                        img2.get_height(),
                        m7,
                        anchor="feet",
                    ):
                        continue
                except Exception:
                    pass
            dx, dy = blit_topleft_bottom_center(int(sx), int(sy), img2.get_width(), img2.get_height())
            try:
                # 바닥 그림자: 아이템 높이와 분리된 월드 발점에 그려 입체감을 준다.
                ground_x, ground_y = self._world_to_draw_xy(ctx, it.wx, it.wy, 0.0)
                if ground_x is not None and ground_y is not None:
                    shadow_w = max(6, int(round(img2.get_width() * 0.72)))
                    shadow_h = max(2, int(round(img2.get_height() * 0.20)))
                    shadow = pygame.Surface((shadow_w, shadow_h), pygame.SRCALPHA)
                    pygame.draw.ellipse(
                        shadow,
                        (0, 0, 0, 105),
                        shadow.get_rect(),
                    )
                    ctx.surf.blit(
                        shadow,
                        (
                            int(round(ground_x - shadow_w * 0.5)),
                            int(round(ground_y - shadow_h * 0.5)),
                        ),
                    )
                ctx.surf.blit(img2, (dx, dy))
                self._draw_item_symbol(ctx.surf, it, dx, dy, img2.get_width(), img2.get_height())
            except Exception:
                pass

        # NPC 레이서 스프라이트 (필드 렌더와 별도로 그려 누락 방지)
        self._draw_npc_racer_sprites(ctx)
        self._draw_slipstream_afterburners(ctx)
        self._draw_spawn_flashes_world(ctx)

    def _draw_slipstream_afterburners(self, ctx: FieldDrawContext) -> None:
        """최고속 90%↑ 일 때 뒤쪽 반투명 에프터버너."""
        if ctx is None or ctx.surf is None or self.state not in (ST_COUNTDOWN, ST_RACE, ST_FINISH):
            return
        try:
            min_frac = float(self._p("slipstream_min_speed_frac", 0.90) or 0.90)
            max_spd = float(self._p("max_speed", 140.0))
        except (TypeError, ValueError):
            min_frac, max_spd = 0.9, 140.0
        for r in self._racers:
            if r is None or r.finished:
                continue
            cap = max_spd * max(0.15, float(r.speed_mul))
            if float(r.speed) < cap * min_frac:
                continue
            fx, fy = self._racer_feet_screen_xy(ctx, r)
            if fx is None or fy is None:
                continue
            tang = float(r.heading)
            length = int(round(scale_ui_text_px(36)))
            thick = max(4, int(round(scale_ui_text_px(6))))
            ex = float(fx) - math.cos(tang) * length
            ey = float(fy) - math.sin(tang) * length
            col = (120, 200, 255) if r.is_player else (180, 210, 255)
            try:
                pygame.draw.line(
                    ctx.surf,
                    (*col, 90),
                    (int(fx), int(fy)),
                    (int(ex), int(ey)),
                    thick,
                )
            except TypeError:
                pygame.draw.line(ctx.surf, col, (int(fx), int(fy)), (int(ex), int(ey)), thick)

    def _draw_spawn_flashes_world(self, ctx: FieldDrawContext) -> None:
        if not self._spawn_flashes or ctx is None or ctx.surf is None:
            return
        for f in self._spawn_flashes:
            sx, sy = self._world_to_draw_xy(ctx, float(f["wx"]), float(f["wy"]), 12.0)
            if sx is None:
                continue
            t = float(f.get("t", 0.0))
            pulse = 0.5 + 0.5 * math.sin(t * 14.0)
            rad = int(12 + pulse * 18)
            try:
                ring = pygame.Surface((rad * 2, rad * 2), pygame.SRCALPHA)
                pygame.draw.circle(ring, (255, 255, 160, int(120 + 80 * pulse)), (rad, rad), rad, 3)
                ctx.surf.blit(ring, (int(sx) - rad, int(sy) - rad - 8))
            except Exception:
                pass

    def _item_symbol_for(self, item_or_type) -> str:
        if isinstance(item_or_type, RaceItemPoint):
            if item_or_type.kind == "secret":
                tid = "secret"
            elif item_or_type.kind == "summon":
                tid = "summon_pad"
            elif item_or_type.kind == "roulette":
                tid = "roulette_pad"
            else:
                tid = item_or_type.type_id
        else:
            tid = str(item_or_type or "").strip().lower()
        return _ITEM_SYMBOLS.get(tid, "?")

    def _item_symbol_surface(self, symbol: str, size_px: int) -> pygame.Surface:
        size = max(8, min(72, int(size_px)))
        key = (str(symbol), size)
        hit = _ITEM_SYMBOL_SURF_CACHE.get(key)
        if hit is not None:
            return hit
        font = self._plain_hud_font(size)
        # 검은 외곽 8방향 + 밝은 본문. 어떤 에셋 색에서도 읽히게 한다.
        core = font.render(symbol, True, (255, 255, 245))
        outline = font.render(symbol, True, (18, 20, 28))
        surf = pygame.Surface((core.get_width() + 4, core.get_height() + 4), pygame.SRCALPHA)
        for ox, oy in ((0, 1), (2, 1), (1, 0), (1, 2), (0, 0), (2, 0), (0, 2), (2, 2)):
            surf.blit(outline, (ox, oy))
        surf.blit(core, (1, 1))
        _ITEM_SYMBOL_SURF_CACHE[key] = surf
        return surf

    def _draw_item_symbol(
        self, surf: pygame.Surface, item_or_type, x: int, y: int, width: int, height: int
    ) -> None:
        symbol = self._item_symbol_for(item_or_type)
        sym = self._item_symbol_surface(symbol, max(8, int(round(height * 0.48))))
        surf.blit(
            sym,
            (
                int(x + width * 0.5 - sym.get_width() * 0.5),
                int(y + height * 0.5 - sym.get_height() * 0.5),
            ),
        )

    def _draw_secret_roulette_ui(self, surf: pygame.Surface, w: int, h: int) -> None:
        sp = self._secret_spin
        if not sp or sp.get("applied") or surf is None:
            return
        pool = list(sp.get("pool") or [])
        if not pool:
            return
        cx, cy = w // 2, int(h * 0.36)
        slot = max(40, int(scale_ui_text_px(52)))
        rect = pygame.Rect(cx - slot // 2 - 6, cy - slot // 2 - 6, slot + 12, slot + 12)
        pygame.draw.rect(surf, (40, 48, 70, 220), rect, border_radius=10)
        pygame.draw.rect(surf, (200, 220, 255), rect, 2, border_radius=10)
        t = float(sp.get("t", 0.0))
        dur = max(0.1, float(sp.get("dur", 1.0)))
        hold = min(0.45, dur * 0.30)
        spin_end = max(0.1, dur - hold)
        final = str(sp.get("final") or pool[0])
        # 화면 중앙 아이템 하나만 빠르게 바뀌고, 마지막 hold 동안 최종 아이템에 멈춘다.
        if t >= spin_end:
            tid = final
        else:
            interval = 0.075 + 0.14 * max(0.0, min(1.0, t / spin_end)) ** 2
            tid = pool[int(t / interval) % len(pool)]
        info = _item_type_info(tid)
        col = info.get("roulette_color") or info.get("placeholder_color") or (200, 200, 200)
        chip = _load_racing_item_surface(
            str(info.get("asset") or ""),
            placeholder_color=col,
        )
        chip = pygame.transform.smoothscale(chip, (slot, slot))
        chip_x, chip_y = cx - slot // 2, cy - slot // 2
        surf.blit(chip, (chip_x, chip_y))
        self._draw_item_symbol(surf, tid, chip_x, chip_y, slot, slot)
        if t >= spin_end:
            finfo = _item_type_info(final)
            lbl = self._plain_hud_font(int(round(scale_ui_text_px(14)))).render(
                str(finfo.get("label") or final), True, (255, 248, 200)
            )
            surf.blit(lbl, (cx - lbl.get_width() // 2, rect.bottom + 8))

    def _draw_weather_hud(self, surf: pygame.Surface, w: int, h: int) -> None:
        pr = next((x for x in self._racers if x.is_player), None)
        if pr is None:
            return
        in_rain = self._racer_in_weather(pr, "rain") is not None
        in_storm = self._racer_in_weather(pr, "lightning") is not None
        if not in_rain and not in_storm:
            return
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        if in_rain:
            overlay.fill((80, 120, 200, 35))
        if in_storm:
            overlay.fill((60, 60, 90, 25))
        surf.blit(overlay, (0, 0))
        if self._weather_msg_t > 0.0 and self._weather_msg:
            f = self._plain_hud_font(int(round(scale_ui_text_px(13))))
            t = f.render(str(self._weather_msg), True, (255, 240, 120))
            surf.blit(t, (w // 2 - t.get_width() // 2, int(h * 0.12)))

    def _racer_sprite_image(self, r: RacerState):
        """엔티티 현재 프레임, 없으면 idle 폴백."""
        ent = getattr(r, "entity", None)
        img = getattr(ent, "image", None) if ent is not None else None
        if img is not None:
            return img
        frames = self._idle_frames(str(getattr(r, "char_id", "") or ""), "right")
        if frames:
            return frames[0]
        return None

    def _draw_npc_racer_sprites(self, ctx: FieldDrawContext) -> None:
        """
        NPC 레이서를 Mode7/월드 좌표로 직접 그림.
        메인 npcs 리스트에서 빠졌거나 Character.draw 가 스킵돼도 보이게 함.
        (엔티티 is_visible=False 로 메인 중복 그리기 방지)
        """
        if ctx is None or ctx.surf is None:
            return
        m7 = getattr(ctx, "mode7_ctx", None)
        rows = []
        for r in self._racers:
            if r is None or r.is_player:
                continue
            if r.finished and self.state != ST_FINISH:
                continue
            sx, sy = self._world_to_draw_xy(ctx, float(r.pos[0]), float(r.pos[1]), 0.0)
            if sx is None or sy is None:
                continue
            img = self._racer_sprite_image(r)
            if img is None:
                continue
            sc = float(ctx.z)
            if m7:
                try:
                    from engine import rotate3d_mode7_project

                    pr = rotate3d_mode7_project(
                        float(r.pos[0]),
                        float(r.pos[1]),
                        m7,
                        height_off=0.0,
                        zoom=float(ctx.z),
                    )
                    if pr and pr.get("valid", pr.get("visible")):
                        sc = float(pr.get("scale", 1.0) or 1.0)
                except Exception:
                    sc = 1.0
            try:
                iw, ih = img.get_width(), img.get_height()
                tw = max(4, int(round(iw * sc)))
                th = max(4, int(round(ih * sc)))
                if (tw, th) != (iw, ih):
                    img2 = pygame.transform.scale(img, (tw, th))
                else:
                    img2 = img
            except Exception:
                img2 = img
            if m7:
                try:
                    from engine import rotate3d_mode7_bounds_visible

                    if not rotate3d_mode7_bounds_visible(
                        float(sx),
                        float(sy),
                        img2.get_width(),
                        img2.get_height(),
                        m7,
                        anchor="feet",
                    ):
                        continue
                except Exception:
                    pass
            rows.append((float(sy), img2, float(sx), float(sy)))
        rows.sort(key=lambda t: t[0])
        for _, img2, sx, sy in rows:
            dx, dy = blit_topleft_bottom_center(
                int(sx), int(sy), img2.get_width(), img2.get_height()
            )
            try:
                ctx.surf.blit(img2, (dx, dy))
            except Exception:
                pass

    def _world_to_draw_xy(
        self, ctx: FieldDrawContext, wx: float, wy: float, height_off: float
    ) -> Tuple[Optional[float], Optional[float]]:
        m7 = getattr(ctx, "mode7_ctx", None)
        if m7:
            try:
                from engine import rotate3d_mode7_project

                pr = rotate3d_mode7_project(
                    float(wx), float(wy), m7, height_off=float(height_off), zoom=float(ctx.z)
                )
                # 투영만 되면 좌표 반환. 화면 밖 여부는 draw 쪽에서 bounds로 판정.
                if not pr or not pr.get("valid", pr.get("visible")):
                    return None, None
                return float(pr["sx"]), float(pr["sy"])
            except Exception:
                return None, None
        sx = (float(wx) - float(ctx.cam_draw_x)) * float(ctx.z)
        sy = (float(wy) - float(ctx.cam_draw_y)) * float(ctx.z)
        if callable(ctx.y_transform):
            try:
                sy = float(ctx.y_transform(float(sy)))
            except Exception:
                pass
        if callable(ctx.x_offset_fn):
            try:
                sx = float(sx) + float(ctx.x_offset_fn(float(sy)))
            except Exception:
                pass
        sy -= float(height_off) * float(ctx.z)
        return sx, sy

    # --- 경로 기반 도로 자동 그리기 ----------------------------------------

    def _road_lane_colors(self) -> List[Tuple[int, int, int]]:
        """1=A(상) 빨강 / 2=B(중) 노랑 / 3=C(하) 파랑 기본. racing.road_lane_colors 로 덮어씀."""
        defaults = [(210, 60, 60), (235, 205, 70), (70, 115, 230)]
        raw = self._p("road_lane_colors") or []
        out: List[Tuple[int, int, int]] = []
        for i in range(3):
            try:
                c = raw[i]
                out.append((int(c[0]), int(c[1]), int(c[2])))
            except (TypeError, ValueError, IndexError):
                out.append(defaults[i])
        return out

    def _paint_road_on_bg(self) -> None:
        """
        레이서 배치와 같은 식(경로점 + 법선*lane*lane_width)으로 bg에 3레인 도로를 굽는다.
        bg 자체를 수정하므로 Mode7 배경·미니맵에 자동으로 반영된다 (맵 파일은 그대로).
        """
        bg = self._bg_ref
        path = self._path
        if bg is None or path is None or self._road_painted:
            return
        if not bool(self._p("road_draw_enabled", True)):
            return
        try:
            lane_w = float(self._p("lane_width", 30.0) or 30.0)
        except (TypeError, ValueError):
            lane_w = 30.0
        lane_w = max(6.0, lane_w)
        colors = self._road_lane_colors()
        try:
            bc = self._p("road_border_color") or [40, 40, 46]
            border_color = (int(bc[0]), int(bc[1]), int(bc[2]))
        except (TypeError, ValueError, IndexError):
            border_color = (40, 40, 46)
        try:
            border_px = max(0.0, float(self._p("road_border_px", 3.0) or 3.0))
        except (TypeError, ValueError):
            border_px = 3.0

        # 경로를 촘촘히 샘플해 원을 이어 굵은 줄무늬를 만든다 (두꺼운 lines의 꺾임 아티팩트 방지)
        step = max(2.0, lane_w * 0.25)
        n = max(2, int(math.ceil(path.length / step)))
        samples: List[Tuple[float, float, float, float]] = []
        for i in range(n + 1):
            x, y, tang, _ = path.sample(path.length * (i / float(n)))
            samples.append((x, y, -math.sin(tang), math.cos(tang)))

        lane_r = int(math.ceil(lane_w * 0.5))
        # 1) 도로 전체 테두리 (반폭 1.5레인 + 테두리)
        if border_px > 0.0:
            br = int(math.ceil(lane_w * 1.5 + border_px))
            for x, y, nx, ny in samples:
                pygame.draw.circle(bg, border_color, (int(round(x)), int(round(y))), br)
        # 2) 레인 줄무늬: A(-1) → B(0) → C(+1)
        for lane_i, off in enumerate((LANE_UPPER, LANE_CENTER, LANE_LOWER)):
            col = colors[lane_i]
            d = off * lane_w
            for x, y, nx, ny in samples:
                pygame.draw.circle(bg, col, (int(round(x + nx * d)), int(round(y + ny * d))), lane_r)
        self._road_painted = True
        print(f"[racing] road painted: lane_w={lane_w:.0f} samples={len(samples)}")

    # --- 미니맵 오버레이 (마리오카트식) ------------------------------------

    _MINIMAP_DOT_COLORS = {
        "player": (255, 70, 70),
        "npc1": (90, 160, 255),
        "npc2": (255, 215, 80),
    }

    def _ensure_minimap(self) -> Optional[pygame.Surface]:
        """전체 맵 bg를 minimap_scale(기본 1/16)로 축소한 캐시 서피스 (+트랙 경로선)."""
        if not bool(self._p("minimap_enabled", True)) or not bool(self._minimap_user_enabled):
            return None
        if self._minimap_bg is not None:
            return self._minimap_bg
        img = self._bg_ref  # 도로가 덧그려진 실제 bg 우선 (미니맵에도 도로 반영)
        if img is None:
            try:
                m = (self._world_data or {}).get(self.map_id) or {}
                bg_name = str(m.get("bg_img") or "").strip()
                if not bg_name:
                    return None
                img = pygame.image.load(os.path.join("assets", "images", "bg", bg_name)).convert()
            except Exception:
                return None
        try:
            scale = float(self._p("minimap_scale", 0.0625) or 0.0625)
        except (TypeError, ValueError):
            scale = 0.0625
        scale = max(0.02, min(0.5, scale))
        mw = max(16, int(round(img.get_width() * scale)))
        mh = max(16, int(round(img.get_height() * scale)))
        try:
            mini = pygame.transform.smoothscale(img, (mw, mh)).convert_alpha()
        except Exception:
            mini = pygame.transform.scale(img, (mw, mh)).convert_alpha()
        self._minimap_map_wh = (float(max(1, img.get_width())), float(max(1, img.get_height())))
        # 트랙 경로선을 살짝 얹어 코스 파악을 돕는다
        path = self._path
        if path is not None and len(path.points) >= 2:
            fx = mw / self._minimap_map_wh[0]
            fy = mh / self._minimap_map_wh[1]
            pts = [(int(round(x * fx)), int(round(y * fy))) for x, y in path.points]
            try:
                pygame.draw.lines(mini, (255, 255, 255), path.closed, pts, 1)
            except Exception:
                pass
        pygame.draw.rect(mini, (24, 28, 40), mini.get_rect(), 1)
        try:
            mini.set_alpha(max(0, min(255, int(self._p("minimap_alpha", 215)))))
        except (TypeError, ValueError):
            mini.set_alpha(215)
        self._minimap_bg = mini
        return mini

    def _format_race_time(self) -> str:
        t = max(0.0, float(self._race_time))
        m, s = divmod(t, 60.0)
        return f"{int(m)}:{s:05.2f}"

    def _draw_minimap(self, surf: pygame.Surface, w: int, h: int, small) -> Optional[int]:
        """오른쪽 위 exit 버튼 밑 미니맵 + 레이서 점 + 경과 시간. 반환: 시간 텍스트 하단 y."""
        mini = self._ensure_minimap()
        if mini is None:
            return None
        mw, mh = mini.get_width(), mini.get_height()
        margin = int(round(w * float(self._p("minimap_margin_x_frac", 0.015) or 0.015)))
        mx = w - mw - max(2, margin)
        my = int(round(h * float(self._p("minimap_top_frac", 0.075) or 0.075)))
        surf.blit(mini, (mx, my))
        # 레이서 위치 점 (플레이어 빨강 / NPC 파랑·노랑)
        fx = mw / self._minimap_map_wh[0]
        fy = mh / self._minimap_map_wh[1]
        rdot = max(2, int(round(mw * 0.022)))
        for r in self._racers:
            try:
                px = mx + int(round(float(r.pos[0]) * fx))
                py = my + int(round(float(r.pos[1]) * fy))
            except (TypeError, ValueError, IndexError):
                continue
            px = max(mx, min(mx + mw - 1, px))
            py = max(my, min(my + mh - 1, py))
            col = self._MINIMAP_DOT_COLORS.get(r.hud_role, (200, 200, 200))
            pygame.draw.circle(surf, (10, 10, 16), (px, py), rdot + 1)
            pygame.draw.circle(surf, col, (px, py), rdot)
        # 경과 시간 (미니맵 바로 밑, 오른쪽 정렬)
        tt = small.render(self._format_race_time(), True, (255, 248, 220))
        pad = 3
        box = pygame.Surface((tt.get_width() + pad * 2, tt.get_height() + pad * 2), pygame.SRCALPHA)
        box.fill((16, 20, 30, 170))
        bx = mx + mw - box.get_width()
        by = my + mh + 2
        surf.blit(box, (bx, by))
        surf.blit(tt, (bx + pad, by + pad))
        return by + box.get_height()

    def draw_screen(self, ctx: FieldDrawContext) -> None:
        if ctx is None or ctx.surf is None:
            return
        surf = ctx.surf
        w, h = surf.get_width(), surf.get_height()
        self._ui_screen_wh = (w, h)
        # 글자 크기: ui.state.json activities.racing.*_px_320
        # plain 폰트: hud_racing force_color 가 검정 고정이라 메뉴 버튼 글자가 안 보이던 문제 방지
        title_px = float(get_activity_ui("racing", "menu_title_px_320", 14) or 14)
        body_px = float(get_activity_ui("racing", "menu_body_px_320", 11) or 11)
        font = self._plain_hud_font(int(round(scale_ui_text_px(title_px))))
        small = self._plain_hud_font(int(round(scale_ui_text_px(body_px))))

        if self.state in (ST_MENU, ST_PICK_CHAR):
            dim = pygame.Surface((w, h), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 150))
            surf.blit(dim, (0, 0))
            # 상위 메뉴 제목은 메인 메뉴에서만 — 캐릭터 선택(서브메뉴)은 자기 제목을
            # 그리므로 여기서 같이 그리면 글자가 겹친다
            if self.state == ST_MENU:
                title = font.render("레이스", True, (255, 248, 220))
                surf.blit(title, (w // 2 - title.get_width() // 2, int(h * 0.08)))
            self._layout_menu_rects(w, h)
            if self.state == ST_MENU:
                # 옵션 서브메뉴가 열려 있으면 상위 메뉴 버튼은 그리지 않는다 (겹침 방지)
                if not self._options_open:
                    labels = [
                        ("1인 플레이 (기록 갱신용)", "1p"),
                        ("1인 플레이 (경쟁)", "1p_vs"),
                        ("옵션", "options"),
                        ("나가기", "exit"),
                    ]
                    for rect, act in self._menu_rects:
                        label = next((lb for lb, a in labels if a == act), act)
                        col = (70, 50, 50) if act == "exit" else (40, 58, 88)
                        if act == "1p_vs":
                            col = (40, 70, 55)
                        elif act == "options":
                            col = (60, 64, 96)
                        pygame.draw.rect(surf, col, rect, border_radius=6)
                        pygame.draw.rect(surf, (120, 160, 220), rect, 2, border_radius=6)
                        t = small.render(label, True, (240, 248, 255))
                        surf.blit(
                            t,
                            (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2),
                        )
                if self._options_open:
                    self._layout_camera_popup(w, h)
                    if self._camera_popup_rect:
                        popup = pygame.Surface(
                            (self._camera_popup_rect.width, self._camera_popup_rect.height),
                            pygame.SRCALPHA,
                        )
                        popup.fill((24, 28, 40, 230))
                        surf.blit(popup, self._camera_popup_rect.topleft)
                        pygame.draw.rect(surf, (180, 200, 235), self._camera_popup_rect, 2, border_radius=8)
                        ttl = small.render("옵션", True, (255, 248, 220))
                        surf.blit(ttl, (self._camera_popup_rect.x + 10, self._camera_popup_rect.y + 8))
                        mm_on = bool(self._minimap_user_enabled)
                        for rect, active, label in (
                            (self._camera_side_rect, str(self._camera_mode or "side") == "side", "카메라 모드 : 옆"),
                            (self._camera_back_rect, str(self._camera_mode or "side") == "back", "카메라 모드 : 뒤"),
                            (self._minimap_toggle_rect, mm_on, f"미니맵 : {'켬' if mm_on else '끔'}"),
                        ):
                            if rect is None:
                                continue
                            pygame.draw.rect(
                                surf,
                                (64, 92, 122) if active else (46, 52, 70),
                                rect,
                                border_radius=6,
                            )
                            pygame.draw.rect(
                                surf,
                                (255, 230, 120) if active else (120, 140, 170),
                                rect,
                                2,
                                border_radius=6,
                            )
                            txt = small.render(label, True, (240, 248, 255))
                            surf.blit(txt, (rect.x + 10, rect.centery - txt.get_height() // 2))
                return
            # pick char
            versus = str(self._race_mode or "record").strip().lower() == "versus"
            pt = font.render("캐릭터 선택", True, (255, 248, 220))
            surf.blit(pt, (w // 2 - pt.get_width() // 2, int(h * 0.06)))
            if self._char_pending_ix is None:
                # 선택 그리드 — 확인창(서브메뉴)이 떠 있으면 그리지 않는다 (겹침 방지)
                if versus:
                    hint = small.render("경쟁: A레인 NPC · B레인 나 · C레인 NPC (나란히)", True, (180, 200, 220))
                else:
                    hint = small.render("고르면 나머지 2명은 랜덤 NPC", True, (180, 200, 220))
                surf.blit(hint, (w // 2 - hint.get_width() // 2, int(h * 0.13)))
                self._layout_char_pick_rects(w, h)
                for rect, ix in self._char_pick_rects:
                    cid = self._char_opts[ix]
                    frames = self._idle_frames(cid, "right")
                    self._blit_idle(surf, frames, (rect.centerx, rect.centery), max(16, int(rect.height * 0.55)))
                    lbl = small.render(self._char_label(cid), True, (210, 225, 245))
                    surf.blit(lbl, (rect.centerx - lbl.get_width() // 2, rect.bottom - lbl.get_height() - 2))
                    pygame.draw.rect(surf, (100, 140, 200), rect, 1, border_radius=4)
            else:
                # 선택 확인창 — 상위(그리드)는 숨긴 상태로 확인 UI만 표시
                cid = self._char_opts[int(self._char_pending_ix)]
                frames = self._idle_frames(cid, "right")
                self._blit_idle(surf, frames, (w // 2, int(h * 0.40)), int(h * 0.28))
                ask = font.render("선택 하시겠습니까?", True, (230, 240, 255))
                surf.blit(ask, (w // 2 - ask.get_width() // 2, int(h * 0.58)))
                for rect, act in self._menu_rects:
                    if act in ("char_yes", "char_no"):
                        pygame.draw.rect(surf, (40, 70, 50) if act == "char_yes" else (70, 40, 40), rect, border_radius=6)
                        lab = "예" if act == "char_yes" else "아니오"
                        t = small.render(lab, True, (240, 248, 255))
                        surf.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))
            # back (그리드/확인창 공통 — 확인창에서는 '뒤로'가 확인 취소)
            for rect, act in self._menu_rects:
                if act == "menu_back":
                    pygame.draw.rect(surf, (50, 50, 70), rect, border_radius=6)
                    t = small.render("뒤로", True, (220, 220, 240))
                    surf.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))
            return

        # HUD (게임 중지는 왼쪽 위 옵션 버튼 팝업에서 — _draw_race_options)
        self._stop_btn_rect = None
        # 미니맵 오버레이 (exit 버튼 밑) — 표시 시 랩·버프 텍스트는 그 아래로 내림
        mm_bottom = None
        if self.state in (ST_COUNTDOWN, ST_RACE, ST_FINISH):
            mm_bottom = self._draw_minimap(surf, w, h, small)
        pr = next((x for x in self._racers if x.is_player), None)
        lap_i = int(pr.lap) + 1 if pr else 1
        lap_txt = small.render(f"랩 {min(lap_i, self._lap_goal)}/{self._lap_goal}", True, (240, 248, 255))
        lap_y = (mm_bottom + 4) if mm_bottom is not None else int(h * 0.04)
        surf.blit(lap_txt, (w - lap_txt.get_width() - int(w * 0.04), lap_y))
        if pr is not None and pr.buff_t > 0.0 and pr.buff_label:
            bt = small.render(f"{pr.buff_label} {pr.buff_t:.1f}s", True, (255, 240, 160))
            surf.blit(bt, (w - bt.get_width() - int(w * 0.04), lap_y + lap_txt.get_height() + 4))
        if self._item_msg_t > 0.0 and self._item_msg:
            msg_px = float(get_activity_ui("racing", "item_msg_px_320", title_px) or title_px)
            msg_font = self._plain_hud_font(int(round(scale_ui_text_px(msg_px))))
            mt = msg_font.render(str(self._item_msg), True, (255, 250, 180))
            surf.blit(mt, (w // 2 - mt.get_width() // 2, int(h * 0.18)))

        if self.state in (ST_COUNTDOWN, ST_RACE, ST_FINISH):
            self._draw_weather_hud(surf, w, h)
            self._draw_secret_roulette_ui(surf, w, h)

        if self.state == ST_COUNTDOWN:
            n = max(1, int(math.ceil(self._countdown_t)))
            cd_px = float(get_activity_ui("racing", "countdown_px_320", 32) or 32)
            big = self._plain_hud_font(int(round(scale_ui_text_px(cd_px))))
            label = "GO!" if self._countdown_t <= 0.35 else str(n)
            ct = big.render(label, True, (255, 240, 120))
            surf.blit(ct, (w // 2 - ct.get_width() // 2, int(h * 0.38)))
            tip = small.render("왼쪽 ▲▼ 로 차선 이동 (한 칸씩)", True, (200, 220, 240))
            surf.blit(tip, (w // 2 - tip.get_width() // 2, int(h * 0.72)))
        elif self.state == ST_FINISH:
            fin_px = float(get_activity_ui("racing", "finish_px_320", 24) or 24)
            big = self._plain_hud_font(int(round(scale_ui_text_px(fin_px))))
            finish_label = str(self._msg or "골인!")
            ct = big.render(finish_label, True, (255, 230, 120))
            surf.blit(ct, (w // 2 - ct.get_width() // 2, int(h * 0.40)))
        elif self.state == ST_RACE:
            tip = small.render("왼쪽 ▲▼ = 차선 A↔B↔C", True, (180, 200, 220))
            surf.blit(tip, (w // 2 - tip.get_width() // 2, h - tip.get_height() - 8))

        # 레인 화살표 HUD (오버레이급)
        self._draw_lane_buttons(surf, w, h)
        # 레인 네임박스: 월드/오브젝트 위 · 오버레이급(원근 크기 고정)
        self._draw_racer_lane_nameboxes(ctx)
        # 왼쪽 위 옵션 버튼 + 팝업 (맨 위에 그려 다른 HUD에 가리지 않게)
        self._draw_race_options(surf, w, h, small)
        # 게임 중지 확인창 (최상단)
        self._draw_race_quit_confirm(surf, w, h, small)

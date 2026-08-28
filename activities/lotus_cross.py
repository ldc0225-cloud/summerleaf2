"""
activities.lotus_cross — 징검다리(연꽃잎) 타일 횡단.

[무엇인가]
  황소개구리(bullfrog)의 축약판. 보스·물방울·반격·아레나 전환 없이
  「그리드 타일 + 타일 간 점프 + lotusleaf 세트」만 남긴다.
  필드 점프(JUMP_ALLOW_WALL_GAP)로 끊긴 길을 넘는 방식은 쓰지 않는다.

[타일 배치] 황소개구리와 같은 설정
  tile_size / grid_origin_x,y / grid_cols / grid_rows
  좌상단 origin 부터 균일 그리드. 칸마다 lotusleaf1~3 고정 순환.
  활동 시작 전에도 같은 그리드로 연꽃잎을 그린다 (world_data 오브젝트 중복 배치 없음).

[점프 규칙] 황소개구리와 동일
  - 4방향 인접 타일만 (col±1 / row±1, 대각 불가)
  - 한 번에 1칸
  - 점프·착지 쿨 중에는 입력 무시
  - 키(←→↑↓ / WASD) 또는 타일 클릭
  - 점프 중 무적 없음. 착지 전까지 출발 칸 물방울에 맞음 (jump_hit_origin_frac)

[진입·퇴장]
  이벤트박스 → 시작 타일: 점프 착지 (순간이동 없음).
  타일 위에 올라간 뒤 A·B 양쪽 모두 나갈 수 있다.
  왼쪽 끝 열에서 더 왼쪽(터치/←) → exit_pos_a 로 점프 착지 후 필드 복귀.
  오른쪽 끝 열에서 더 오른쪽(터치/→) → exit_pos_b 로 점프 착지 후 필드 복귀.

[동행 NPC]
  이벤트박스 진입 시 follow NPC 는 fadeout 후 숨김 (물 마스크를 따라 건너지 않음).
  behavior_spec follow + FOLLOW_START(ev_mgr._followers) 모두 대상.
  exit_pos 착지 후 플레이어 근처에 PLACE appear 처럼 fadein.
  persist/travel 동행은 flow.prepare_traveling_placed 로 세이브 좌표도 강가에 맞춤.

[튜토리얼 물방울] (drops_enabled)
  황소개구리 보스전 축약 — 그림자 예고 → 랜덤 칸 낙하 → 맞으면 falldown (목숨·점수 없음).
  drop_interval_sec 간격으로 반복. 진입/퇴장 점프·넘어짐 중에는 이동만 막고 낙하는 계속될 수 있음.

[연동]
  DEV_CMD: start_lotus_cross / stop_lotus_cross  (from_side=a|b)
  이벤트: ev_pond02_lotus_cross_a / ev_pond02_lotus_cross_b
  data.py LOTUS_CROSS_DEFAULTS + world_data[map].lotus_cross

[에셋]
  character/ 또는 object/ lotusleaf1~3/{land,hit}_left/  (bullfrog _load_lotus_frames)
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Tuple

import pygame

from char_behavior import normalize_behavior_mode, set_npc_behavior
from data import BULLFROG_DEFAULTS, CONFIG, LOTUS_CROSS_DEFAULTS
from engine import get_cached_scaled_sprite
from field_runtime import fade_alpha_delta
from .base import BaseFieldActivity, FieldDrawContext
from .bullfrog import _BullfrogYSortSprite, _load_char_frames, _load_lotus_frames, _placeholder_surf

TileXY = Tuple[int, int]  # (col, row)

ST_PLAY = "play"
ST_ENTER_JUMP = "enter_jump"  # 이벤트박스 → 시작 타일 점프 중
ST_EXIT_JUMP = "exit_jump"  # 끝 타일 → exit_pos 점프 중
ST_QUIT = "quit"


def _cfg(key: str, default=None):
    if key in LOTUS_CROSS_DEFAULTS:
        return LOTUS_CROSS_DEFAULTS.get(key, default)
    return BULLFROG_DEFAULTS.get(key, default)


def _field_cfg(map_id: str, world_data) -> dict:
    """world_data[map].lotus_cross ⊕ LOTUS_CROSS_DEFAULTS."""
    out = dict(LOTUS_CROSS_DEFAULTS)
    mid = str(map_id or "").strip()
    if isinstance(world_data, dict) and mid:
        block = (world_data.get(mid) or {}).get("lotus_cross")
        if isinstance(block, dict):
            out.update(block)
    return out


def _as_tile(val, fallback: TileXY = (0, 0)) -> TileXY:
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            return (int(val[0]), int(val[1]))
        except (TypeError, ValueError):
            pass
    return fallback


def _as_xy(val, fallback=None):
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            return (float(val[0]), float(val[1]))
        except (TypeError, ValueError):
            pass
    return fallback


def map_has_lotus_cross(map_id, world_data) -> bool:
    """world_data[map].lotus_cross 가 있을 때만 장식·활동을 쓴다 (기본값만으로 전 맵에 안 그림)."""
    mid = str(map_id or "").strip()
    if not isinstance(world_data, dict) or not mid:
        return False
    return isinstance((world_data.get(mid) or {}).get("lotus_cross"), dict)


def lotus_cross_variant_ix(col: int, row: int, cols: int, nsets: int) -> int:
    """칸마다 고정 세트 인덱스. 필드 장식과 활동 중 잎이 같게."""
    n = max(1, int(nsets) or 1)
    return (int(col) + int(row) * max(1, int(cols))) % n


_IDLE_LAND_CACHE: Dict[tuple, List[List[pygame.Surface]]] = {}


def _idle_land_frames(sets: List[str], tile: int) -> List[List[pygame.Surface]]:
    key = (tuple(str(s) for s in sets), int(tile))
    cached = _IDLE_LAND_CACHE.get(key)
    if cached is not None:
        return cached
    loaded = [_load_lotus_frames(name, "land", tile) for name in sets]
    _IDLE_LAND_CACHE[key] = loaded
    return loaded


def _blit_lotus_world(
    surf,
    img,
    wx,
    wy,
    cam_x,
    cam_y,
    z,
    *,
    sprite_tilt: float = 1.0,
    sprite_perspective_q=None,
    y_transform=None,
    x_offset_fn=None,
):
    if img is None or surf is None:
        return
    sx = (float(wx) - float(cam_x)) * z
    sy = (float(wy) - float(cam_y)) * z
    if callable(y_transform):
        try:
            sy = float(y_transform(sy))
        except Exception:
            pass
    if callable(x_offset_fn):
        try:
            sx = float(sx) + float(x_offset_fn(sy))
        except Exception:
            pass
    try:
        scaled = get_cached_scaled_sprite(
            img,
            float(z),
            sprite_perspective_q=sprite_perspective_q,
            sprite_tilt=float(sprite_tilt),
        )
    except Exception:
        scaled = None
    if scaled is None:
        iw, ih = img.get_width(), img.get_height()
        sw = max(1, int(round(iw * z)))
        sh = max(1, int(round(ih * z)))
        try:
            scaled = pygame.transform.scale(img, (sw, sh)) if (sw, sh) != (iw, ih) else img
        except Exception:
            scaled = img
            sw, sh = iw, ih
    else:
        sw, sh = scaled.get_width(), scaled.get_height()
    ox = int(sx - sw * 0.5)
    oy = int(sy - sh * 0.5)
    surf.blit(scaled, (ox, oy))


def draw_lotus_cross_idle(ctx: FieldDrawContext, map_id: str, world_data) -> None:
    """
    활동 시작 전에도 징검다리 연꽃잎을 같은 그리드에 표시.
    world_data 에 오브젝트를 따로 깔지 않는다 (위치 이중 관리 방지).
    lotus_cross 활동 중에는 활동 draw_world_under 가 대신 그린다.
    """
    if ctx is None or ctx.surf is None:
        return
    if not map_has_lotus_cross(map_id, world_data):
        return
    field = _field_cfg(map_id, world_data)
    tile = max(8, int(field.get("tile_size", 32) or 32))
    cols = max(1, int(field.get("grid_cols", 5) or 5))
    rows = max(1, int(field.get("grid_rows", 1) or 1))
    ox = float(field.get("grid_origin_x", 0.0) or 0.0)
    oy = float(field.get("grid_origin_y", 0.0) or 0.0)
    sets = list(
        field.get("lotus_leaf_sets")
        or _cfg("lotus_leaf_sets")
        or ["lotusleaf1", "lotusleaf2", "lotusleaf3"]
    )
    nsets = max(1, len(sets))
    land = _idle_land_frames(sets, tile)
    if not land:
        return
    tilt = float(field.get("lotus_sprite_tilt", 1.0))
    fps = max(1.0, float(field.get("anim_fps", 10.0)))
    try:
        t = pygame.time.get_ticks() / 1000.0
    except Exception:
        t = 0.0
    surf = ctx.surf
    z = float(ctx.z or 1.0)
    cam_x = float(ctx.cam_draw_x)
    cam_y = float(ctx.cam_draw_y)
    spq = getattr(ctx, "sprite_perspective_q", None)
    y_tr = getattr(ctx, "y_transform", None)
    x_off = getattr(ctx, "x_offset_fn", None)
    for r in range(rows):
        for c in range(cols):
            vi = lotus_cross_variant_ix(c, r, cols, nsets)
            frames = land[vi % len(land)] if land else []
            if not frames:
                continue
            ix = int(t * fps) % len(frames)
            cx = ox + (c + 0.5) * tile
            cy = oy + (r + 0.5) * tile
            _blit_lotus_world(
                surf,
                frames[ix],
                cx,
                cy,
                cam_x,
                cam_y,
                z,
                sprite_tilt=tilt,
                sprite_perspective_q=spq,
                y_transform=y_tr,
                x_offset_fn=x_off,
            )


class LotusCrossActivity(BaseFieldActivity):
    """강 횡단 징검다리 — 그리드 타일 점프만."""

    activity_id = "lotus_cross"

    def __init__(self):
        self.state = ST_QUIT
        self.map_id = ""
        self.field: dict = {}
        self._ev_mgr = None
        self._player_ref = None

        self._tile = 32
        self._cols = 5
        self._rows = 1
        self._ox = 0.0
        self._oy = 0.0
        self._leaf_tiles: List[TileXY] = []
        self._leaf_set = set()
        self._leaf_variant: Dict[TileXY, int] = {}
        self._leaf_anim: Dict[TileXY, Dict[str, Any]] = {}

        self._from_side = "a"
        self._start_a: TileXY = (0, 0)
        self._start_b: TileXY = (0, 0)
        self._exit_a = (0.0, 0.0)
        self._exit_b = (0.0, 0.0)
        self._exit_a_col = 0
        self._exit_b_col = 0
        self._exit_jump_side = ""
        self._exit_from_xy = (0.0, 0.0)
        self._exit_to_xy = (0.0, 0.0)

        self._player_tile: TileXY = (0, 0)
        self._player_from: TileXY = (0, 0)
        self._player_jump_t = 0.0
        self._player_jumping = False
        self._player_land_cd = 0.0
        self._player_bob_ix = -1
        self._player_bob_t = 0.0
        self._player_base_height = 0.0
        self._player_hide_shadow_saved = False
        self._key_held = False

        self._won = False
        self._finish_side = ""
        self._finish_hold = 0.0
        self._field_camera_command: Optional[Dict[str, Any]] = None

        self._lotus_land: List[List[pygame.Surface]] = []
        self._lotus_hit: List[List[pygame.Surface]] = []

        self._npcs: list = []
        self._mask = None
        self._follow_npcs: List[Any] = []
        self._follow_saved_specs: Dict[int, dict] = {}
        self._follow_ev_entries: List[dict] = []  # FOLLOW_START(ev_mgr._followers) 일시 해제용
        self._follow_fade = ""  # "" | "out" | "in"
        self._follow_fade_sec = 0.5

        # 튜토리얼 물방울 (drops_enabled)
        self._drop_fall: List[pygame.Surface] = []
        self._drop_impact: List[pygame.Surface] = []
        self._drop_wave: Optional[Dict[str, Any]] = None  # phase shadow|drop, tiles, t, land_done
        self._drop_wait = 0.0
        self._drop_pulse_t = 0.0
        self._drop_hit_this_wave = False
        self._falldown_active = False
        self._falldown_t = 0.0
        self._falldown_dur = 0.0
        self._falldown_frame_ends: List[float] = []

        self.field_tilt_enabled: Optional[bool] = None
        self.field_tilt_target: Optional[float] = None

    # ------------------------------------------------------------------ begin / end

    def begin(self, player, **params) -> bool:
        self._player_ref = player
        self._ev_mgr = params.get("ev_mgr")
        self.map_id = str(
            params.get("map")
            or params.get("map_id")
            or _cfg("default_map_id", "bg_pond02")
        ).strip()
        self.field = _field_cfg(self.map_id, params.get("world_data"))
        self._tile = max(8, int(self.field.get("tile_size", 32) or 32))

        if not self._build_tiles():
            print("[lotus_cross] no tiles configured")
            return False

        side = str(params.get("from_side") or self.field.get("from_side") or "").strip().lower()
        if side not in ("a", "b"):
            side = self._infer_side_from_player(player)
        self._from_side = side

        self._start_a = _as_tile(self.field.get("start_a"), (0, 0))
        self._start_b = _as_tile(self.field.get("start_b"), (self._cols - 1, 0))
        if self._start_a not in self._leaf_set:
            self._start_a = (0, 0)
        if self._start_b not in self._leaf_set:
            self._start_b = (self._cols - 1, 0)

        self._exit_a_col = int(self.field.get("exit_a_col", 0) or 0)
        self._exit_b_col = int(self.field.get("exit_b_col", self._cols - 1) or (self._cols - 1))
        self._exit_a = _as_xy(self.field.get("exit_pos_a"), self._tile_center(self._start_a))
        self._exit_b = _as_xy(self.field.get("exit_pos_b"), self._tile_center(self._start_b))
        if self._exit_a is None:
            self._exit_a = self._tile_center(self._start_a)
        if self._exit_b is None:
            self._exit_b = self._tile_center(self._start_b)

        start = self._start_a if side == "a" else self._start_b
        self._player_tile = start
        self._player_from = start
        self._exit_jump_side = ""
        self._won = False
        self._finish_side = ""
        self._finish_hold = 0.0
        self._player_jumping = False
        self._player_jump_t = 0.0
        self._player_land_cd = 0.0
        self._player_bob_ix = -1
        self._player_bob_t = 0.0
        self._key_held = False

        self._load_assets()
        self._init_leaf_anims_land()
        self._reset_drop_state(first=True)

        self._mask = params.get("mask")
        npcs = params.get("npcs")
        self._npcs = npcs if isinstance(npcs, list) else []
        try:
            self._follow_fade_sec = max(0.0, float(self.field.get("follow_fade_sec", 0.5) or 0.0))
        except (TypeError, ValueError):
            self._follow_fade_sec = 0.5

        try:
            self._player_base_height = float(getattr(player, "height", 0.0) or 0.0)
            self._player_hide_shadow_saved = bool(getattr(player, "_hide_feet_shadow", False))
            player.stop_moving()
            player.path = []
            player.height = self._player_base_height
            player._hide_feet_shadow = False
            try:
                player.is_visible = True
            except Exception:
                pass
        except Exception:
            pass

        self._field_camera_command = {
            "mode": "follow_player",
            "smooth": True,
            "duration_sec": 0.2,
        }
        self._begin_follow_fadeout()
        self._begin_enter_jump(start)
        print(
            f"[lotus_cross] begin map={self.map_id} side={self._from_side} "
            f"grid={self._cols}x{self._rows} start={start}"
        )
        return True

    def _begin_enter_jump(self, start: TileXY) -> None:
        """이벤트박스(현재 발 위치) → 시작 타일 점프. 거의 붙어 있으면 스냅만."""
        p = self._player_ref
        foot = self._tile_center(start)
        try:
            fx = float(p.pos[0]) if p is not None else foot[0]
            fy = float(p.pos[1]) if p is not None else foot[1]
        except Exception:
            fx, fy = foot[0], foot[1]
        dist = math.hypot(foot[0] - fx, foot[1] - fy)
        snap_px = max(4.0, float(self.field.get("enter_snap_px", 6.0) or 6.0))
        if dist <= snap_px:
            if p is not None:
                try:
                    p.pos[0], p.pos[1] = foot[0], foot[1]
                    p.target = list(p.pos)
                    p.path = []
                    p.height = self._player_base_height
                    p.state = "idle"
                    p.play_anim("idle", duration_ms=None, loop=True, release="stop")
                except Exception:
                    pass
            self._play_leaf_hit(start)
            self.state = ST_PLAY
            return
        self._exit_from_xy = (fx, fy)
        self._exit_to_xy = (float(foot[0]), float(foot[1]))
        self._player_jumping = True
        self._player_jump_t = 0.0
        self._player_bob_ix = -1
        self._player_bob_t = 0.0
        self._face_toward_xy(fx, fy, foot[0], foot[1])
        self._start_player_jump_anim(duration_sec=self._free_jump_sec(self._exit_from_xy, self._exit_to_xy))
        self.state = ST_ENTER_JUMP

    def cancel(self) -> None:
        if self.state == ST_QUIT:
            return
        self._reset_drop_state()
        self._finish_to_side(self._from_side, won=False, instant=True)

    @property
    def is_active(self) -> bool:
        # fadein 동안에도 세션 유지 (존 재진입·다른 활동 시작 방지)
        return self.state != ST_QUIT or self._finish_hold > 0.0

    @property
    def is_finished(self) -> bool:
        return self.state == ST_QUIT and self._finish_hold <= 0.0

    def blocks_field_move(self) -> bool:
        return self.state != ST_QUIT

    def blocks_zone_confirm(self) -> bool:
        return self.state != ST_QUIT or self._finish_hold > 0.0

    def bind_field_lists(self, *, npcs=None, objs=None) -> None:
        if isinstance(npcs, list):
            self._npcs = npcs

    def result(self) -> Dict[str, Any]:
        return {
            "activity": self.activity_id,
            "won": bool(self._won),
            "quit": not bool(self._won),
            "from_side": self._from_side,
            "finish_side": self._finish_side,
        }

    def poll_camera_command(self) -> Optional[Dict[str, Any]]:
        cmd = self._field_camera_command
        self._field_camera_command = None
        return cmd

    # ------------------------------------------------------------------ tiles (bullfrog 그리드)

    def _build_tiles(self) -> bool:
        """origin + cols×rows 균일 그리드. 보스 구멍 없음."""
        self._cols = max(1, int(self.field.get("grid_cols", 5) or 5))
        self._rows = max(1, int(self.field.get("grid_rows", 1) or 1))
        self._ox = float(self.field.get("grid_origin_x", 0.0) or 0.0)
        self._oy = float(self.field.get("grid_origin_y", 0.0) or 0.0)
        leaves = [(c, r) for r in range(self._rows) for c in range(self._cols)]
        self._leaf_tiles = leaves
        self._leaf_set = set(leaves)
        sets = list(self.field.get("lotus_leaf_sets") or _cfg("lotus_leaf_sets") or [])
        nsets = max(1, len(sets))
        self._leaf_variant = {
            t: lotus_cross_variant_ix(t[0], t[1], self._cols, nsets) for t in leaves
        }
        return True

    def _infer_side_from_player(self, player) -> str:
        try:
            px = float(player.pos[0])
            py = float(player.pos[1])
        except Exception:
            return "a"
        a = self._tile_center((0, 0))
        b = self._tile_center((self._cols - 1, 0))
        da = (px - a[0]) ** 2 + (py - a[1]) ** 2
        db = (px - b[0]) ** 2 + (py - b[1]) ** 2
        return "a" if da <= db else "b"

    def _tile_center(self, tile: TileXY) -> Tuple[float, float]:
        c, r = tile
        return (
            self._ox + (c + 0.5) * self._tile,
            self._oy + (r + 0.5) * self._tile,
        )

    def _tile_at_world(self, wx: float, wy: float) -> Optional[TileXY]:
        c = int((wx - self._ox) // self._tile)
        r = int((wy - self._oy) // self._tile)
        t = (c, r)
        if t in self._leaf_set:
            return t
        return None

    def _neighbors4(self, tile: TileXY) -> List[TileXY]:
        c, r = tile
        out = []
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c + dc, r + dr)
            if n in self._leaf_set:
                out.append(n)
        return out

    def _can_exit_side(self, side: str) -> bool:
        """끝 열에 있을 때만 해당 강가로 점프 퇴장."""
        c, _r = self._player_tile
        if str(side).lower() == "a":
            return c == int(self._exit_a_col)
        return c == int(self._exit_b_col)

    # ------------------------------------------------------------------ assets / leaf anim

    def _load_assets(self) -> None:
        tile = self._tile
        sets = list(
            self.field.get("lotus_leaf_sets")
            or _cfg("lotus_leaf_sets")
            or ["lotusleaf1", "lotusleaf2", "lotusleaf3"]
        )
        self._lotus_land = []
        self._lotus_hit = []
        for name in sets:
            self._lotus_land.append(_load_lotus_frames(name, "land", tile))
            self._lotus_hit.append(_load_lotus_frames(name, "hit", tile))
        self._drop_fall = []
        self._drop_impact = []
        if self._drops_enabled():
            self._load_waterdrop_assets()

    def _load_waterdrop_assets(self) -> None:
        """물방울 fall/impact — bullfrog 와 동일 경로(BULLFROG_DEFAULTS / field)."""
        tile = self._tile
        drop_fx_dir = str(
            self.field.get("waterdrop_fx_dir") or _cfg("waterdrop_fx_dir") or ""
        ).strip()
        drop_fx_name = str(self.field.get("waterdrop_fx") or _cfg("waterdrop_fx") or "").strip()
        if not drop_fx_dir and drop_fx_name:
            drop_fx_dir = f"assets/images/fx/{drop_fx_name}"
        impact_fx_dir = str(
            self.field.get("waterdrop_impact_fx_dir") or _cfg("waterdrop_impact_fx_dir") or ""
        ).strip()
        impact_fx_name = str(
            self.field.get("waterdrop_impact_fx") or _cfg("waterdrop_impact_fx") or ""
        ).strip()
        if not impact_fx_dir and impact_fx_name:
            impact_fx_dir = f"assets/images/fx/{impact_fx_name}"
        if drop_fx_dir:
            try:
                from engine import _load_anim_dir_cached

                loaded = _load_anim_dir_cached(drop_fx_dir)
                if loaded:
                    self._drop_fall = list(loaded)
            except Exception as e:
                print(f"[lotus_cross] waterdrop fall fx load fail {drop_fx_dir}: {e}")
        if impact_fx_dir:
            try:
                from engine import _load_anim_dir_cached

                loaded = _load_anim_dir_cached(impact_fx_dir)
                if loaded:
                    self._drop_impact = list(loaded)
            except Exception as e:
                print(f"[lotus_cross] waterdrop impact fx load fail {impact_fx_dir}: {e}")
        drop_char = str(self.field.get("waterdrop_char") or _cfg("waterdrop_char") or "waterdrop")
        if not self._drop_fall:
            self._drop_fall = _load_char_frames(drop_char, "fall")
        if not self._drop_impact:
            self._drop_impact = _load_char_frames(drop_char, "impact")
        if not self._drop_fall:
            self._drop_fall = [_placeholder_surf(16, 22, (120, 180, 255), "drop")]
        if not self._drop_impact:
            self._drop_impact = [_placeholder_surf(tile - 4, 14, (180, 210, 255), "splash")]

    def _init_leaf_anims_land(self) -> None:
        self._leaf_anim = {t: {"state": "land", "t": 0.0} for t in self._leaf_tiles}

    def _leaf_hit_duration(self, variant_ix: int) -> float:
        cfg = float(self.field.get("leaf_hit_sec", 0.0) or 0.0)
        if cfg > 0.0:
            return cfg
        frames = []
        if self._lotus_hit:
            frames = self._lotus_hit[int(variant_ix) % len(self._lotus_hit)]
        fps = max(1.0, float(self.field.get("anim_fps", 10.0)))
        n = max(1, len(frames) if frames else 4)
        return float(n) / fps

    def _tick_leaf_anims(self, dt: float) -> None:
        for tile in self._leaf_tiles:
            info = self._leaf_anim.get(tile)
            if not info:
                self._leaf_anim[tile] = {"state": "land", "t": 0.0}
                continue
            info["t"] = float(info.get("t") or 0.0) + dt
            if str(info.get("state") or "land") == "hit":
                vi = int(self._leaf_variant.get(tile, 0))
                if float(info["t"]) >= self._leaf_hit_duration(vi):
                    info["state"] = "land"
                    info["t"] = 0.0

    def _play_leaf_hit(self, tile: TileXY) -> None:
        if tile not in self._leaf_set:
            return
        self._leaf_anim[tile] = {"state": "hit", "t": 0.0}

    def _leaf_draw_frame(self, tile: TileXY) -> Optional[pygame.Surface]:
        vi = int(self._leaf_variant.get(tile, 0))
        info = self._leaf_anim.get(tile) or {"state": "land", "t": 0.0}
        st = str(info.get("state") or "land")
        t = float(info.get("t") or 0.0)
        if st == "hit" and self._lotus_hit:
            frames = self._lotus_hit[vi % len(self._lotus_hit)]
        else:
            frames = self._lotus_land[vi % len(self._lotus_land)] if self._lotus_land else []
        if not frames:
            return None
        return self._anim_frame(frames, t)

    def _anim_frame(self, frames: List[pygame.Surface], t: float) -> pygame.Surface:
        if not frames:
            return _placeholder_surf(16, 16, (255, 0, 255))
        fps = float(self.field.get("anim_fps", 10.0))
        ix = int(t * fps) % len(frames)
        return frames[ix]

    # ------------------------------------------------------------------ jump (bullfrog 와 동일 규칙)

    def _drops_enabled(self) -> bool:
        v = self.field.get("drops_enabled", _cfg("drops_enabled", False))
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "t", "yes", "y", "on")
        return bool(v)

    def _reset_drop_state(self, *, first: bool = False) -> None:
        self._drop_wave = None
        self._drop_pulse_t = 0.0
        self._drop_hit_this_wave = False
        self._falldown_active = False
        self._falldown_t = 0.0
        self._falldown_dur = 0.0
        self._falldown_frame_ends = []
        try:
            delay = float(
                self.field.get("drop_first_delay_sec", _cfg("drop_first_delay_sec", 2.0)) or 2.0
            )
        except (TypeError, ValueError):
            delay = 2.0
        self._drop_wait = max(0.0, delay) if first else 0.0
        self._sync_drop_player_shadow()

    def _drop_shadow_sec(self) -> float:
        try:
            return max(0.25, float(self.field.get("drop_shadow_sec", _cfg("drop_shadow_sec", 1.0)) or 1.0))
        except (TypeError, ValueError):
            return 1.0

    def _drop_interval_sec(self) -> float:
        try:
            return max(0.5, float(self.field.get("drop_interval_sec", _cfg("drop_interval_sec", 4.0)) or 4.0))
        except (TypeError, ValueError):
            return 4.0

    def _drop_shadow_fade_sec(self) -> float:
        fade = max(0.0, float(self.field.get("shadow_fade_sec", _cfg("shadow_fade_sec", 0.3)) or 0.3))
        shadow_sec = self._drop_shadow_sec()
        if shadow_sec <= 0.0:
            return 0.0
        return min(fade, shadow_sec * 0.45)

    def _drop_phase_dur(self) -> float:
        return float(self.field.get("drop_fall_sec", _cfg("drop_fall_sec", 0.5))) + float(
            self.field.get("drop_impact_sec", _cfg("drop_impact_sec", 1.0))
        )

    def _pick_drop_tiles(self) -> set:
        pool = list(self._leaf_tiles)
        ex = self.field.get("drop_exclude_player_tile", _cfg("drop_exclude_player_tile", True))
        if ex is True or (isinstance(ex, str) and ex.strip().lower() in ("1", "true", "t", "yes", "y", "on")):
            occ = self._player_occupancy_tile()
            pool = [t for t in pool if t != occ]
        if not pool:
            pool = list(self._leaf_tiles)
        try:
            count = max(1, int(self.field.get("drops_per_wave", _cfg("drops_per_wave", 1)) or 1))
        except (TypeError, ValueError):
            count = 1
        count = min(count, len(pool))
        random.shuffle(pool)
        return set(pool[:count])

    def _spawn_drop_wave(self) -> None:
        tiles = self._pick_drop_tiles()
        if not tiles:
            return
        self._drop_wave = {
            "phase": "shadow",
            "tiles": set(tiles),
            "t": 0.0,
            "land_done": False,
        }
        self._drop_hit_this_wave = False
        self._sync_drop_player_shadow()

    def _drop_shadow_fade_mul(self, t: float) -> float:
        fade = self._drop_shadow_fade_sec()
        shadow_sec = self._drop_shadow_sec()
        if fade <= 0.0:
            return 1.0 if 0.0 <= t < shadow_sec else 0.0
        if t < fade:
            return max(0.0, min(1.0, t / fade))
        remain = shadow_sec - t
        if remain < fade:
            return max(0.0, min(1.0, remain / fade))
        return 1.0

    def _drop_shadow_alpha_by_tile(self) -> Dict[TileXY, int]:
        w = self._drop_wave
        if not w or str(w.get("phase") or "") != "shadow":
            return {}
        t = float(w.get("t") or 0.0)
        mul = self._drop_shadow_fade_mul(t)
        if mul <= 0.001:
            return {}
        pulse = 80 + int(40 * abs(math.sin(self._drop_pulse_t * 8.0)))
        alpha = int(round(pulse * mul))
        if alpha <= 0:
            return {}
        return {tile: alpha for tile in set(w.get("tiles") or ())}

    def _sync_drop_player_shadow(self) -> None:
        """물방울 그림자 예고 중에는 발그림자 숨김 (bullfrog 와 동일 구분)."""
        if not self._drops_enabled():
            return
        p = self._player_ref
        if p is None:
            return
        active = False
        w = self._drop_wave
        if w is not None and str(w.get("phase") or "") in ("shadow", "drop"):
            active = True
        try:
            p._hide_feet_shadow = active or bool(self._player_hide_shadow_saved)
        except Exception:
            pass

    def _play_player_falldown(self) -> None:
        p = self._player_ref
        if p is None:
            return
        fall_dur = float(self.field.get("falldown_sec", _cfg("falldown_sec", 2.0)))
        self._falldown_active = True
        self._falldown_t = 0.0
        self._falldown_dur = fall_dur
        raw = list(self.field.get("falldown_frame_sec") or _cfg("falldown_frame_sec") or [])
        self._falldown_frame_ends = []
        if raw:
            t = 0.0
            for s in raw:
                t += float(s)
                self._falldown_frame_ends.append(t)
        try:
            dur_ms = max(80, int(round(fall_dur * 1000.0)))
            p.play_anim("falldown", duration_ms=dur_ms, loop=False, release="idle")
            p.state = "falldown"
        except Exception:
            pass

    def _apply_falldown_frame(self, t: float) -> None:
        ends = self._falldown_frame_ends
        if not ends:
            return
        p = self._player_ref
        if p is None:
            return
        idx = len(ends) - 1
        for i, t_end in enumerate(ends):
            if t < t_end:
                idx = i
                break
        try:
            if getattr(p, "_anim_override", None) is not None:
                p.frame_idx = idx
                anims = p.anims_l if p.direction == "left" else p.anims_r
                frames = anims.get("falldown") or anims.get("idle")
                if frames and idx < len(frames):
                    p.image = frames[idx]
        except Exception:
            pass

    def _tick_falldown(self, dt: float) -> None:
        if not self._falldown_active:
            return
        self._falldown_t += dt
        if self._falldown_t >= self._falldown_dur:
            self._falldown_active = False
            self._end_player_jump_anim()
            return
        self._apply_falldown_frame(self._falldown_t)

    def _apply_drop_hit(self) -> None:
        if self._drop_hit_this_wave or self._falldown_active:
            return
        self._drop_hit_this_wave = True
        occ = self._snap_player_to_occupancy_for_hit()
        self._play_leaf_hit(occ)
        self._play_player_falldown()

    def _tick_drop_wave(self, dt: float) -> None:
        w = self._drop_wave
        if not w:
            return
        self._drop_pulse_t += dt
        w["t"] = float(w.get("t") or 0.0) + dt
        phase = str(w.get("phase") or "shadow")
        shadow_sec = self._drop_shadow_sec()
        fall = float(self.field.get("drop_fall_sec", _cfg("drop_fall_sec", 0.5)))
        drop_dur = self._drop_phase_dur()

        if phase == "shadow":
            if w["t"] >= shadow_sec:
                w["phase"] = "drop"
                w["t"] = 0.0
                w["land_done"] = False
                phase = "drop"
            self._sync_drop_player_shadow()
            return

        if phase == "drop":
            tiles = set(w.get("tiles") or ())
            if not w.get("land_done") and w["t"] >= fall:
                w["land_done"] = True
                for t in tiles:
                    self._play_leaf_hit(t)
                if (
                    not self._drop_hit_this_wave
                    and self._player_occupancy_tile() in tiles
                ):
                    self._apply_drop_hit()
            if w["t"] >= drop_dur:
                self._drop_wave = None
                self._drop_wait = self._drop_interval_sec()
                self._sync_drop_player_shadow()
            return

    def _tick_drops(self, dt: float) -> None:
        if not self._drops_enabled() or self.state != ST_PLAY:
            return
        self._tick_falldown(dt)
        if self._drop_wave is not None:
            self._tick_drop_wave(dt)
            return
        if self._falldown_active:
            return
        self._drop_wait = max(0.0, float(self._drop_wait) - dt)
        if self._drop_wait <= 0.0:
            self._spawn_drop_wave()

    def _can_player_move(self) -> bool:
        return (
            self.state == ST_PLAY
            and not self._player_jumping
            and self._player_land_cd <= 0.0
            and not self._falldown_active
        )

    def _jump_hit_origin_frac(self) -> float:
        """점프 중 출발 칸 피격 유지 비율. 1.0=착지 전까지, 0.5=전반부만."""
        try:
            v = float(self.field.get("jump_hit_origin_frac", _cfg("jump_hit_origin_frac", 1.0)))
        except (TypeError, ValueError):
            v = 1.0
        return max(0.0, min(1.0, v))

    def _player_occupancy_tile(self) -> TileXY:
        """물방울 피격 칸. 점프 중에는 출발 칸을 jump_hit_origin_frac 동안 유지 (무적 없음)."""
        if not self._player_jumping:
            return self._player_tile
        frac = self._jump_hit_origin_frac()
        if frac <= 0.0:
            return self._player_tile
        try:
            jump_sec = float(self.field.get("player_jump_sec", _cfg("player_jump_sec", 0.4)) or 0.4)
        except (TypeError, ValueError):
            jump_sec = 0.4
        if jump_sec <= 0.0:
            return self._player_from
        t = min(1.0, float(self._player_jump_t or 0.0) / jump_sec)
        if t < frac:
            return self._player_from
        return self._player_tile

    def _snap_player_to_occupancy_for_hit(self) -> TileXY:
        """피격 시 점프를 끊고 판정 칸으로 스냅 (출발 칸에 맞으면 그 칸으로 되돌림)."""
        occ = self._player_occupancy_tile()
        if self._player_jumping:
            self._player_tile = occ
            self._player_jumping = False
            self._end_player_jump_anim()
            p = self._player_ref
            if p is not None:
                foot = self._tile_center(occ)
                try:
                    p.pos[0], p.pos[1] = float(foot[0]), float(foot[1])
                    p.target = [float(foot[0]), float(foot[1])]
                    p.height = self._player_base_height
                    p.path = []
                except Exception:
                    pass
        return occ

    def _player_jump_duration_ms(self, sec: float | None = None) -> int:
        if sec is None:
            sec = float(self.field.get("player_jump_sec", _cfg("player_jump_sec", 0.4)))
        return max(80, int(round(float(sec) * 1000.0)))

    def _free_jump_sec(self, from_xy, to_xy) -> float:
        """이벤트박스↔타일·타일↔exit_pos 처럼 칸 간격이 아닐 때 점프 시간."""
        base = float(self.field.get("player_jump_sec", _cfg("player_jump_sec", 0.4)))
        tile = max(1.0, float(self._tile))
        try:
            dist = math.hypot(float(to_xy[0]) - float(from_xy[0]), float(to_xy[1]) - float(from_xy[1]))
        except (TypeError, ValueError, IndexError):
            return base
        return base * max(1.0, min(2.5, dist / tile))

    def _land_bob_offsets(self) -> List[int]:
        raw = self.field.get("player_land_bob_y", _cfg("player_land_bob_y"))
        if isinstance(raw, (list, tuple)) and raw:
            out: List[int] = []
            for v in raw:
                try:
                    out.append(int(v))
                except (TypeError, ValueError):
                    out.append(0)
            return out
        return [3, 1, 0, 0, -3, -1]

    def _land_bob_frame_sec(self) -> float:
        fps = max(1.0, float(self.field.get("anim_fps", 10.0)))
        return 1.0 / fps

    def _start_land_bob(self) -> None:
        if not self._land_bob_offsets():
            self._player_bob_ix = -1
            self._player_bob_t = 0.0
            return
        self._player_bob_ix = 0
        self._player_bob_t = 0.0

    def _current_land_bob_y(self) -> float:
        if self._player_bob_ix < 0:
            return 0.0
        offs = self._land_bob_offsets()
        if not offs or self._player_bob_ix >= len(offs):
            return 0.0
        return float(offs[self._player_bob_ix])

    def _face_toward_xy(self, fx: float, fy: float, tx: float, ty: float) -> None:
        p = self._player_ref
        if p is None:
            return
        dx, dy = tx - fx, ty - fy
        try:
            if abs(dx) >= abs(dy):
                p.direction = "right" if dx > 0 else "left"
            else:
                p.direction = "left"
        except Exception:
            pass

    def _face_toward(self, from_tile: TileXY, to_tile: TileXY) -> None:
        fc = self._tile_center(from_tile)
        tc = self._tile_center(to_tile)
        self._face_toward_xy(fc[0], fc[1], tc[0], tc[1])

    def _start_player_jump_anim(self, *, duration_sec: float | None = None) -> None:
        p = self._player_ref
        if p is None:
            return
        dur = self._player_jump_duration_ms(duration_sec)
        try:
            p.play_anim("jump", duration_ms=dur, loop=True, release="idle")
            try:
                p.state = "jump"
            except Exception:
                pass
        except Exception:
            try:
                p.play_anim("walk", duration_ms=dur, loop=True, release="idle")
            except Exception:
                pass

    def _end_player_jump_anim(self) -> None:
        p = self._player_ref
        if p is None:
            return
        try:
            p.clear_anim_override()
        except Exception:
            pass
        try:
            p.state = "idle"
            p.play_anim("idle", duration_ms=None, loop=True, release="stop")
        except Exception:
            pass

    def _try_step(self, dest: TileXY) -> bool:
        """인접 타일 점프. 그리드 밖이면 끝 열에서 exit_pos 점프."""
        if dest in self._leaf_set:
            return self._try_jump_to(dest)
        c, r = self._player_tile
        dc, dr = dest[0] - c, dest[1] - r
        if abs(dc) + abs(dr) != 1:
            return False
        if dc < 0:
            return self._try_exit_to("a")
        if dc > 0:
            return self._try_exit_to("b")
        return False

    def _try_jump_to(self, dest: TileXY) -> bool:
        if dest not in self._leaf_set:
            return False
        if dest == self._player_tile:
            return False
        if dest not in self._neighbors4(self._player_tile):
            return False
        if self._player_jumping or self._player_land_cd > 0.0:
            return False
        self._player_bob_ix = -1
        self._player_bob_t = 0.0
        self._player_from = self._player_tile
        self._player_tile = dest
        self._player_jumping = True
        self._player_jump_t = 0.0
        self._face_toward(self._player_from, dest)
        self._start_player_jump_anim()
        return True

    def _try_exit_to(self, side: str) -> bool:
        """끝 타일에서 강가 exit_pos 로 점프 퇴장 (양쪽 모두 가능)."""
        if not self._can_player_move():
            return False
        side = "b" if str(side).strip().lower() == "b" else "a"
        if not self._can_exit_side(side):
            return False
        dest = self._exit_b if side == "b" else self._exit_a
        foot = self._tile_center(self._player_tile)
        self._player_bob_ix = -1
        self._player_bob_t = 0.0
        self._exit_jump_side = side
        self._exit_from_xy = (float(foot[0]), float(foot[1]))
        self._exit_to_xy = (float(dest[0]), float(dest[1]))
        self._player_jumping = True
        self._player_jump_t = 0.0
        self._face_toward_xy(
            self._exit_from_xy[0], self._exit_from_xy[1],
            self._exit_to_xy[0], self._exit_to_xy[1],
        )
        self._start_player_jump_anim(
            duration_sec=self._free_jump_sec(self._exit_from_xy, self._exit_to_xy)
        )
        self.state = ST_EXIT_JUMP
        return True

    def _try_exit_from_click(self, wx: float, wy: float) -> bool:
        """끝 열에서 그리드 밖·exit_pos 쪽을 터치하면 그쪽으로 점프."""
        rad = self._tile * float(self.field.get("exit_click_radius_ratio", 1.25) or 1.25)
        rad2 = rad * rad
        for side, pos in (("a", self._exit_a), ("b", self._exit_b)):
            if pos is None:
                continue
            if (wx - pos[0]) ** 2 + (wy - pos[1]) ** 2 <= rad2:
                if self._try_exit_to(side):
                    return True
        c, _r = self._player_tile
        if c == self._exit_a_col and wx < self._ox:
            return self._try_exit_to("a")
        if c == self._exit_b_col and wx >= self._ox + self._cols * self._tile:
            return self._try_exit_to("b")
        return False

    def _on_player_landed(self) -> None:
        self._player_jumping = False
        self._play_leaf_hit(self._player_tile)
        self._end_player_jump_anim()
        self._start_land_bob()
        self._player_land_cd = float(
            self.field.get("player_land_cooldown_sec", _cfg("player_land_cooldown_sec", 0.05))
        )
        p = self._player_ref
        if p is not None:
            try:
                p.height = self._player_base_height
            except Exception:
                pass

    def _on_enter_landed(self) -> None:
        self._player_jumping = False
        self._play_leaf_hit(self._player_tile)
        self._end_player_jump_anim()
        self._start_land_bob()
        self._player_land_cd = float(
            self.field.get("player_land_cooldown_sec", _cfg("player_land_cooldown_sec", 0.05))
        )
        p = self._player_ref
        if p is not None:
            try:
                p.height = self._player_base_height
            except Exception:
                pass
        self.state = ST_PLAY

    def _on_exit_landed(self) -> None:
        side = self._exit_jump_side or "a"
        self._player_jumping = False
        self._end_player_jump_anim()
        self._finish_to_side(side, won=True, instant=False)

    def _sync_player_pos(self, dt: float) -> None:
        p = self._player_ref
        if p is None:
            return
        if self._player_land_cd > 0.0:
            self._player_land_cd = max(0.0, self._player_land_cd - dt)

        if self._player_bob_ix >= 0:
            offs = self._land_bob_offsets()
            self._player_bob_t += dt
            step = self._land_bob_frame_sec()
            while self._player_bob_ix >= 0 and self._player_bob_t >= step:
                self._player_bob_t -= step
                self._player_bob_ix += 1
                if self._player_bob_ix >= len(offs):
                    self._player_bob_ix = -1
                    self._player_bob_t = 0.0
                    break

        jump_sec = float(self.field.get("player_jump_sec", _cfg("player_jump_sec", 0.4)))
        jump_h = float(self.field.get("player_jump_height", _cfg("player_jump_height", 25.0)))

        if self.state in (ST_ENTER_JUMP, ST_EXIT_JUMP) and self._player_jumping:
            free_sec = self._free_jump_sec(self._exit_from_xy, self._exit_to_xy)
            self._player_jump_t += dt
            t = 0.0 if free_sec <= 0 else min(1.0, self._player_jump_t / free_sec)
            ax, ay = self._exit_from_xy
            bx, by = self._exit_to_xy
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            h = jump_h * math.sin(math.pi * t)
            try:
                p.pos[0], p.pos[1] = x, y
                p.target = [x, y]
                p.height = self._player_base_height + h
                p.path = []
            except Exception:
                pass
            if t >= 1.0:
                if self.state == ST_ENTER_JUMP:
                    self._on_enter_landed()
                else:
                    self._on_exit_landed()
            return

        if self._player_jumping:
            self._player_jump_t += dt
            t = 0.0 if jump_sec <= 0 else min(1.0, self._player_jump_t / jump_sec)
            a = self._tile_center(self._player_from)
            b = self._tile_center(self._player_tile)
            x = a[0] + (b[0] - a[0]) * t
            y = a[1] + (b[1] - a[1]) * t
            h = jump_h * math.sin(math.pi * t)
            try:
                p.pos[0], p.pos[1] = x, y
                p.target = [x, y]
                p.height = self._player_base_height + h
                p.path = []
            except Exception:
                pass
            if t >= 1.0:
                self._on_player_landed()
            return

        if self.state != ST_PLAY:
            return

        foot = self._tile_center(self._player_tile)
        bob_y = self._current_land_bob_y()
        x, y = foot[0], foot[1] + bob_y
        try:
            p.pos[0], p.pos[1] = x, y
            p.target = [x, y]
            p.height = self._player_base_height
            p.path = []
        except Exception:
            pass

    # ------------------------------------------------------------------ follow NPC fade (옵션 1)

    def _npc_matches_follower_token(self, npc, token: str) -> bool:
        tok = str(token or "").strip()
        if not tok or npc is None:
            return False
        try:
            if str(getattr(npc, "name", "") or "").strip() == tok:
                return True
            iid = str(getattr(npc, "instance_id", "") or "").strip()
            if iid and iid == tok:
                return True
        except Exception:
            pass
        try:
            from engine import _entity_matches_event_target

            return bool(_entity_matches_event_target(npc, tok))
        except Exception:
            return False

    def _collect_follow_npcs(self) -> List[Any]:
        """behavior_spec follow + FOLLOW_START(ev_mgr._followers) 동행 NPC."""
        out: List[Any] = []
        seen: set = set()

        def _add(npc) -> None:
            if npc is None or npc is self._player_ref:
                return
            eid = id(npc)
            if eid in seen:
                return
            seen.add(eid)
            out.append(npc)

        for npc in list(self._npcs or []):
            spec = getattr(npc, "behavior_spec", None) or {}
            if normalize_behavior_mode(spec.get("mode") or "") == "follow":
                _add(npc)

        ev = self._ev_mgr
        if ev is not None:
            for f in list(getattr(ev, "_followers", None) or []):
                fol_name = str(f.get("follower") or "").strip()
                if not fol_name:
                    continue
                for npc in self._npcs or []:
                    if self._npc_matches_follower_token(npc, fol_name):
                        _add(npc)
                        break
        return out

    def _pause_ev_mgr_followers(self, npcs: List[Any]) -> None:
        """징검다리 중 ev_mgr FOLLOW_START 추종 일시 중단(연못 따라옴 방지)."""
        self._follow_ev_entries = []
        ev = self._ev_mgr
        if ev is None or not npcs:
            return
        kept: List[dict] = []
        for f in list(getattr(ev, "_followers", None) or []):
            fol_name = str(f.get("follower") or "").strip()
            matched = any(self._npc_matches_follower_token(n, fol_name) for n in npcs)
            if matched:
                self._follow_ev_entries.append(dict(f))
            else:
                kept.append(f)
        try:
            ev._followers = kept
        except Exception:
            pass

    def _resume_ev_mgr_followers(self) -> None:
        ev = self._ev_mgr
        entries = list(self._follow_ev_entries or [])
        self._follow_ev_entries = []
        if ev is None or not entries:
            return
        cur = list(getattr(ev, "_followers", None) or [])
        existing = {str(x.get("follower") or "").strip() for x in cur}
        for entry in entries:
            fol = str(entry.get("follower") or "").strip()
            if fol and fol not in existing:
                cur.append(dict(entry))
                existing.add(fol)
        try:
            ev._followers = cur
        except Exception:
            pass

    def _prepare_follow_npc_for_fade(self, npc) -> None:
        spec = getattr(npc, "behavior_spec", None) or {}
        self._follow_saved_specs[id(npc)] = dict(spec) if isinstance(spec, dict) else {}
        try:
            set_npc_behavior(npc, "idle")
        except Exception:
            pass
        sm = getattr(npc, "stop_moving", None)
        if callable(sm):
            try:
                sm()
            except Exception:
                pass
        try:
            npc.path = []
        except Exception:
            pass
        try:
            npc.alpha = 255
            npc.is_visible = True
        except Exception:
            pass

    def _begin_follow_fadeout(self) -> None:
        """이벤트박스 진입 — follow NPC 를 idle 로 고정한 뒤 fadeout."""
        self._follow_npcs = []
        self._follow_saved_specs = {}
        self._follow_ev_entries = []
        self._follow_fade = ""
        self._follow_npcs = self._collect_follow_npcs()
        for npc in self._follow_npcs:
            self._prepare_follow_npc_for_fade(npc)
        if not self._follow_npcs:
            return
        self._pause_ev_mgr_followers(self._follow_npcs)
        self._follow_fade = "out"
        print(f"[lotus_cross] follow fadeout n={len(self._follow_npcs)}")

    def _begin_follow_fadein(self) -> None:
        """exit_pos 착지 — 플레이어 근처로 옮긴 뒤 fadein (PLACE appear 와 같은 alpha)."""
        if not self._follow_npcs:
            return
        if self._follow_fade == "out":
            self._apply_follow_hidden()
            self._follow_fade = ""
        self._place_follow_near_player()
        for npc in self._follow_npcs:
            try:
                npc.is_visible = True
                npc.alpha = 0
            except Exception:
                pass
            sm = getattr(npc, "stop_moving", None)
            if callable(sm):
                try:
                    sm()
                except Exception:
                    pass
        if self._follow_fade_sec <= 1e-6:
            self._apply_follow_visible_full()
            self._restore_follow_behavior()
            self._follow_fade = ""
            self._finish_hold = 0.0
            return
        self._follow_fade = "in"
        self._finish_hold = max(self._finish_hold, float(self._follow_fade_sec))
        print(f"[lotus_cross] follow fadein n={len(self._follow_npcs)}")

    def _apply_follow_hidden(self) -> None:
        for npc in self._follow_npcs:
            try:
                npc.alpha = 0
                npc.is_visible = False
            except Exception:
                pass
            sm = getattr(npc, "stop_moving", None)
            if callable(sm):
                try:
                    sm()
                except Exception:
                    pass

    def _apply_follow_visible_full(self) -> None:
        for npc in self._follow_npcs:
            try:
                npc.alpha = 255
                npc.is_visible = True
            except Exception:
                pass

    def _restore_follow_behavior(self) -> None:
        for npc in self._follow_npcs:
            saved = self._follow_saved_specs.get(id(npc))
            if isinstance(saved, dict) and saved:
                try:
                    npc.behavior_spec = dict(saved)
                    continue
                except Exception:
                    pass
            try:
                set_npc_behavior(npc, "follow")
            except Exception:
                pass
        self._resume_ev_mgr_followers()

    def _follow_save_data(self):
        try:
            flow = getattr(self._ev_mgr, "flow", None) if self._ev_mgr is not None else None
            sd = getattr(flow, "save_data", None) if flow is not None else None
        except Exception:
            return None
        return sd if isinstance(sd, dict) else None

    def _follow_fallback_pos(self, index: int, px: float, py: float, used) -> List[float]:
        """placed 에 없는 follow NPC — PLACED_FOLLOW_SPAWN_* 오프셋 + walk 스냅."""
        try:
            base_off = float(CONFIG.get("PLACED_FOLLOW_SPAWN_OFFSET_PX", 28) or 28)
        except (TypeError, ValueError):
            base_off = 28.0
        try:
            spacing = float(CONFIG.get("PLACED_FOLLOW_SPAWN_SPACING_PX", 20) or 20)
        except (TypeError, ValueError):
            spacing = 20.0
        try:
            min_sep = float(CONFIG.get("PLACED_FOLLOW_SPAWN_MIN_SEP_PX", 14) or 14)
        except (TypeError, ValueError):
            min_sep = 14.0
        try:
            snap_r = int(CONFIG.get("PLACED_FOLLOW_SPAWN_SNAP_R_PX", 72) or 72)
        except (TypeError, ValueError):
            snap_r = 72
        ox = base_off + index * spacing
        cands = [
            (px - ox, py),
            (px + ox, py),
            (px, py + ox),
            (px, py - ox),
            (px - ox * 0.7, py + ox * 0.7),
            (px + ox * 0.7, py + ox * 0.7),
        ]
        snap_fn = None
        if self._mask is not None:
            try:
                from engine import _snap_to_nearest_walk

                snap_fn = _snap_to_nearest_walk
            except Exception:
                snap_fn = None

        def _ok(x, y) -> bool:
            for ux, uy in used:
                if math.hypot(x - ux, y - uy) < min_sep:
                    return False
            return True

        for cx, cy in cands:
            x, y = float(cx), float(cy)
            if snap_fn is not None:
                sn = snap_fn(self._mask, x, y, max_r=snap_r, step=2)
                if sn is not None:
                    x, y = float(sn[0]), float(sn[1])
            if _ok(x, y):
                return [x, y]
        return [px, py]

    def _place_follow_near_player(self) -> None:
        """prepare_traveling_placed 로 persist 동행 좌표를 강가에 맞추고 라이브 NPC 에 적용."""
        p = self._player_ref
        if p is None:
            return
        try:
            px, py = float(p.pos[0]), float(p.pos[1])
        except Exception:
            return
        sd = self._follow_save_data()
        if sd is not None:
            try:
                from flow import prepare_traveling_placed

                prepare_traveling_placed(sd, self.map_id, (px, py), config=CONFIG, mask=self._mask)
            except Exception:
                pass
        used: List[Tuple[float, float]] = []
        for i, npc in enumerate(self._follow_npcs):
            pos = None
            if sd is not None:
                try:
                    from flow import find_placed_entry, placed_entry_travels

                    entry = find_placed_entry(sd, str(getattr(npc, "name", "") or ""))
                    if entry and placed_entry_travels(entry):
                        raw = entry.get("pos")
                        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                            pos = [float(raw[0]), float(raw[1])]
                except Exception:
                    pos = None
            if pos is None:
                pos = self._follow_fallback_pos(i, px, py, used)
            try:
                npc.pos = [float(pos[0]), float(pos[1])]
                npc.target = list(npc.pos)
                npc.path = []
                if hasattr(npc, "origin_pos"):
                    npc.origin_pos = list(npc.pos)
            except Exception:
                pass
            used.append((float(pos[0]), float(pos[1])))

    def _tick_follow_fade(self, dt_sec: float) -> None:
        phase = self._follow_fade
        if phase not in ("out", "in"):
            return
        npcs = [n for n in self._follow_npcs if n is not None]
        if not npcs:
            self._follow_fade = ""
            return
        sec = max(0.0, float(self._follow_fade_sec))
        if sec <= 1e-6:
            if phase == "out":
                self._apply_follow_hidden()
            else:
                self._apply_follow_visible_full()
                self._restore_follow_behavior()
                self._finish_hold = 0.0
            self._follow_fade = ""
            return
        delta = fade_alpha_delta(255.0, sec, max(0.0, float(dt_sec)))
        all_done = True
        for npc in npcs:
            try:
                a = int(getattr(npc, "alpha", 255) or 0)
            except Exception:
                a = 255
            if phase == "out":
                a = max(0, a - int(round(delta)))
            else:
                a = min(255, a + int(round(delta)))
            try:
                npc.alpha = a
            except Exception:
                pass
            if phase == "out" and a > 0:
                all_done = False
            if phase == "in" and a < 255:
                all_done = False
        if not all_done:
            return
        if phase == "out":
            self._apply_follow_hidden()
        else:
            self._apply_follow_visible_full()
            self._restore_follow_behavior()
            self._finish_hold = 0.0
        self._follow_fade = ""

    def _finish_to_side(self, side: str, *, won: bool, instant: bool) -> None:
        side = "b" if str(side).strip().lower() == "b" else "a"
        self._won = bool(won)
        self._finish_side = side
        dest = self._exit_b if side == "b" else self._exit_a
        p = self._player_ref
        if p is not None:
            try:
                p.height = self._player_base_height
                p._hide_feet_shadow = bool(self._player_hide_shadow_saved)
                p.stop_moving()
                if instant:
                    p.pos[0] = float(dest[0])
                    p.pos[1] = float(dest[1])
                else:
                    p.pos[0] = float(self._exit_to_xy[0] if self._exit_to_xy else dest[0])
                    p.pos[1] = float(self._exit_to_xy[1] if self._exit_to_xy else dest[1])
                p.target = list(p.pos)
                p.path = []
                try:
                    p.clear_anim_override()
                except Exception:
                    pass
                p.state = "idle"
                p.play_anim("idle", duration_ms=None, loop=True, release="stop")
            except Exception:
                pass
        self._field_camera_command = {
            "mode": "follow_player",
            "smooth": True,
            "duration_sec": 0.25,
        }
        self.state = ST_QUIT
        self._finish_hold = 0.0
        self._reset_drop_state()
        self._begin_follow_fadein()
        print(f"[lotus_cross] finish side={side} won={won} pos={tuple(p.pos) if p else dest}")

    # ------------------------------------------------------------------ tick / input

    def tick(self, dt_sec: float, player, now_ms: int) -> None:
        if self.state == ST_QUIT:
            self._tick_follow_fade(dt_sec)
            # fadein 중에는 _tick_follow_fade 가 끝날 때까지 hold 유지
            if self._follow_fade != "in":
                self._finish_hold = max(0.0, self._finish_hold - dt_sec)
            return
        dt = max(0.0, float(dt_sec))
        self._tick_follow_fade(dt)
        self._tick_leaf_anims(dt)
        self._sync_player_pos(dt)
        if self.state == ST_QUIT:
            return
        self._tick_drops(dt)

        if self._can_player_move():
            try:
                keys = pygame.key.get_pressed()
                dest = None
                c, r = self._player_tile
                if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                    dest = (c - 1, r)
                elif keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                    dest = (c + 1, r)
                elif keys[pygame.K_UP] or keys[pygame.K_w]:
                    dest = (c, r - 1)
                elif keys[pygame.K_DOWN] or keys[pygame.K_s]:
                    dest = (c, r + 1)
                if dest is not None:
                    if not self._key_held:
                        self._try_step(dest)
                        self._key_held = True
                else:
                    self._key_held = False
            except Exception:
                pass

    def on_pointer_down(self, screen_xy, world_xy, now_ms: int) -> bool:
        if self.state == ST_QUIT:
            return True
        if not self._can_player_move():
            return True
        wx = wy = None
        if isinstance(world_xy, (list, tuple)) and len(world_xy) >= 2:
            wx, wy = float(world_xy[0]), float(world_xy[1])
        if wx is None:
            return True
        dest = self._tile_at_world(wx, wy)
        if dest is not None:
            self._try_jump_to(dest)
            return True
        self._try_exit_from_click(wx, wy)
        return True

    def on_pointer_up(self, now_ms: int) -> bool:
        return self.state != ST_QUIT

    def on_primary_key(self, key) -> bool:
        if not self._can_player_move():
            return True
        c, r = self._player_tile
        try:
            k = int(key)
        except Exception:
            return True
        dest = None
        if k in (pygame.K_LEFT, pygame.K_a):
            dest = (c - 1, r)
        elif k in (pygame.K_RIGHT, pygame.K_d):
            dest = (c + 1, r)
        elif k in (pygame.K_UP, pygame.K_w):
            dest = (c, r - 1)
        elif k in (pygame.K_DOWN, pygame.K_s):
            dest = (c, r + 1)
        if dest is not None:
            self._try_step(dest)
        return True

    # ------------------------------------------------------------------ draw

    def _blit_world_centered(
        self,
        surf,
        img,
        wx,
        wy,
        cam_x,
        cam_y,
        z,
        *,
        sprite_tilt: float = 1.0,
        sprite_perspective_q=None,
        y_transform=None,
        x_offset_fn=None,
    ):
        _blit_lotus_world(
            surf,
            img,
            wx,
            wy,
            cam_x,
            cam_y,
            z,
            sprite_tilt=sprite_tilt,
            sprite_perspective_q=sprite_perspective_q,
            y_transform=y_transform,
            x_offset_fn=x_offset_fn,
        )

    def draw_world_under(self, ctx: FieldDrawContext) -> None:
        """배경 위 · 캐릭터 아래 — 연꽃잎만."""
        if ctx is None or ctx.surf is None or self.state == ST_QUIT:
            return
        surf = ctx.surf
        z = float(ctx.z or 1.0)
        cam_x = float(ctx.cam_draw_x)
        cam_y = float(ctx.cam_draw_y)
        spq = getattr(ctx, "sprite_perspective_q", None)
        y_tr = getattr(ctx, "y_transform", None)
        x_off = getattr(ctx, "x_offset_fn", None)
        leaf_tilt = float(self.field.get("lotus_sprite_tilt", 1.0))
        shadow_alphas = self._drop_shadow_alpha_by_tile()
        for tile in self._leaf_tiles:
            cx, cy = self._tile_center(tile)
            img = self._leaf_draw_frame(tile)
            self._blit_world_centered(
                surf,
                img,
                cx,
                cy,
                cam_x,
                cam_y,
                z,
                sprite_tilt=leaf_tilt,
                sprite_perspective_q=spq,
                y_transform=y_tr,
                x_offset_fn=x_off,
            )
            if tile in shadow_alphas:
                sx = (cx - cam_x) * z
                sy = (cy - cam_y) * z
                if callable(y_tr):
                    try:
                        sy = float(y_tr(sy))
                    except Exception:
                        pass
                if callable(x_off):
                    try:
                        sx = float(sx) + float(x_off(sy))
                    except Exception:
                        pass
                alpha = int(shadow_alphas[tile])
                if alpha <= 0:
                    continue
                shad = pygame.Surface(
                    (max(4, int(self._tile * z * 0.7)), max(3, int(self._tile * z * 0.35))),
                    pygame.SRCALPHA,
                )
                pygame.draw.ellipse(shad, (20, 30, 60, alpha), shad.get_rect())
                surf.blit(
                    shad,
                    (int(sx - shad.get_width() * 0.5), int(sy - shad.get_height() * 0.2)),
                )

    def collect_ysort_sprites(self):
        """떨어지는 물방울 — bullfrog collect_ysort 와 동일 ysort."""
        if self.state == ST_QUIT or not self._drops_enabled():
            return []
        w = self._drop_wave
        if not w or str(w.get("phase") or "") != "drop":
            return []
        out: List[_BullfrogYSortSprite] = []
        fall = float(self.field.get("drop_fall_sec", _cfg("drop_fall_sec", 0.5)))
        drop_start_h = float(self.field.get("drop_start_height", _cfg("drop_start_height", 200.0)))
        drop_fps = float(self.field.get("drop_anim_fps", _cfg("drop_anim_fps", 0.0)))
        if drop_fps <= 0:
            drop_fps = float(self.field.get("anim_fps", 10.0))
        impact_sec = float(self.field.get("drop_impact_sec", _cfg("drop_impact_sec", 1.0)))
        drop_t = float(w.get("t") or 0.0)
        for tile_xy in set(w.get("tiles") or ()):
            cx, cy = self._tile_center(tile_xy)
            if drop_t < fall:
                u = 0.0 if fall <= 0 else min(1.0, drop_t / fall)
                h = drop_start_h * (1.0 - u)
                n = len(self._drop_fall) or 1
                ix = min(n - 1, int(drop_t * drop_fps))
                fr = self._drop_fall[ix]
                out.append(_BullfrogYSortSprite(cx, cy, fr, height=h, anchor="feet"))
            else:
                impact_t = drop_t - fall
                n = len(self._drop_impact) or 1
                if impact_sec <= 0 or n <= 1:
                    fr = self._drop_impact[n - 1]
                else:
                    u = min(1.0, max(0.0, impact_t / impact_sec))
                    ix = min(n - 1, int(u * n) if u < 1.0 else n - 1)
                    fr = self._drop_impact[ix]
                out.append(_BullfrogYSortSprite(cx, cy, fr, height=0.0, anchor="center"))
        return out

    def draw(self, ctx: FieldDrawContext) -> None:
        return

    def draw_world(self, ctx: FieldDrawContext) -> None:
        return

"""
activities.bullfrog — 황소개구리 보스전 (연못 타일 아레나).

[화면·타일]
  논리 320×240 고정. 타일 32×32.
  여백: 좌 32 / 우 32 / 위 16 → 플레이 그리드 8×7=56칸.
  중앙 4×3=12칸은 황소개구리 자리(연꽃잎 없음) → 연꽃잎 44칸.

[연꽃잎 — 1단계]
  character/lotusleaf1~3 (32×32). 타일마다 랜덤 1종.
  기본 표시: land 루프. 캐릭터가 점프해 착지하면 hit 1회 → land 복귀.

[일반 공격 물방울]
  1차·2차·3차 병렬 웨이브 = 1턴. 턴×3(회피 성공) = 1세트 → 반격. 세트×3 = 클리어.
  n차 시작 = (n-1)*drop_wave_gap_sec, 그림자 유지 = shadow_sec_by_set.
  설정에 따라 2차 그림자와 1차 낙하가 겹칠 수 있음. 한 턴 피해는 최대 1회.
  보스전 중 플레이어 발그림자는 _hide_feet_shadow 로 숨김(물방울 그림자와 구분).

[그리기 순서]
  맵 → wave01 → splash → 연꽃잎 → (ysort) 플레이어·개구리·황소개구리·물방울 → HUD/페이드

[연동]
  DEV_CMD: start_bullfrog / stop_bullfrog / return_from_bullfrog
  이벤트: ev_bullfrog_enter / ev_bullfrog_exit
  data.py BULLFROG_DEFAULTS + world_data[map].bullfrog

[에셋] (없어도 프로시저럴 플레이스홀더)
  character/lotusleaf1~3/{land,hit}_left/
  character/bullfrog/{idle,jump,splash,beattacked,loss}_left/
  character/frog01/{idle,jump}_left/
  character/waterdrop/{fall,impact}_left/
  assets/images/fx/waterdrop01/ … (낙하) / waterdrop02/ … (착지 퍼짐)
  assets/images/fx/wave01/wave01_0.png … (물결 FX)
  assets/images/fx/splash01/ … (착수 물튀김 — 공격·반격 공통; splash02는 추후 교체)
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Tuple

import pygame

from data import BULLFROG_DEFAULTS, CONFIG, get_activity_ui
from engine import get_cached_scaled_sprite
from .base import BaseFieldActivity, FieldDrawContext

# ---------------------------------------------------------------------------
# 상태
# ---------------------------------------------------------------------------
ST_CAM_HOLD = "cam_hold"        # 인트로: 맵 상단 풍경 잠시 보여줌
ST_CAM_PAN = "cam_pan"          # 인트로: 상단 → 아레나로 카메라 이동
ST_INTRO = "intro"              # 화면 밖에서 시작 타일로 진입
ST_TITLE = "title"              # 시작 타이틀(게임 시작!) 표시
ST_WAIT = "wait"                # 다음 공격 대기
ST_BOSS_JUMP = "boss_jump"      # 황소개구리 점프
ST_SPLASH = "splash"            # 착수·물 튀김
ST_SHADOW = "shadow"            # 물방울 공격 중(병렬 웨이브: 그림자·낙하 혼재)
ST_DROP = "drop"                # (호환) 낙하 연출 — 병렬 모드에서는 ST_SHADOW에 통합
ST_HIT = "hit"                  # 플레이어 피격 스턴(턴 종료 후 falldown 잔여)
ST_COUNTER_SPAWN = "counter_spawn"  # 아군 개구리 등장
ST_COUNTER_WAIT = "counter_wait"    # 보스 점프 대기(반격창 전)
ST_COUNTER_WINDOW = "counter_window"  # frog01 타일로 이동할 창
ST_COUNTER_MISS_DESCEND = "counter_miss_descend"  # 반격 실패: jumpfly→jump3 하강 후 착수
ST_COUNTER_PREP = "counter_prep"      # frog01 위 idle 첫프레임 고정 0.5초
ST_COUNTER_ASCENT = "counter_ascent"  # 보스 배 위치로 jump
ST_TICKLE = "tickle"                  # 플레이어 tickle + 보스 down (공중)
ST_COUNTER_RETURN = "counter_return"  # 원래 타일 복귀 · frog01 퇴장 · 보스 하강
ST_SINK = "sink"                # 보스 sink
ST_SUBMERGED = "submerged"      # 물속에 숨음(표시 안 함)
ST_RISE = "rise"                # 보스 재등장(난이도↑)
ST_WIN = "win"
ST_LOSE = "lose"
ST_QUIT = "quit"

TileXY = Tuple[int, int]  # (col, row)


class _BullfrogYSortSprite:
    """플레이어와 함께 ysort 되는 임시 스프라이트 (황소개구리·아군·물방울)."""

    __slots__ = ("pos", "layer", "ysort_mode", "height", "_img", "_anchor")

    def __init__(
        self,
        wx: float,
        wy: float,
        img: pygame.Surface,
        *,
        height: float = 0.0,
        layer: int = 0,
        anchor: str = "feet",
    ):
        self.pos = [float(wx), float(wy)]
        self.layer = int(layer)
        self.ysort_mode = "ground"
        self.height = float(height)
        self._img = img
        self._anchor = str(anchor or "feet")

    def draw(
        self,
        screen,
        cam_x,
        cam_y,
        zoom=1.0,
        jump_shadow_mode=None,
        y_transform=None,
        x_offset_fn=None,
        sprite_perspective_q=None,
        shear_lod=False,
        x_scale_fn=None,
        x_shift_fn=None,
        pivot_xy=None,
        cam_angle_rad=0.0,
        mode7_ctx=None,
        view_w=None,
    ):
        img = self._img
        if img is None or screen is None:
            return
        z = float(zoom or 1.0)
        sx = (float(self.pos[0]) - float(cam_x)) * z
        sy = (float(self.pos[1]) - float(cam_y)) * z
        # 연꽃잎(_blit_world_centered)·플레이어(map_feet_screen_xy)와 동일:
        # flat → y_transform(틸트) → x_offset(쉬어) → height
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
        h = float(self.height or 0.0)
        sy = sy - h * z
        try:
            scaled = get_cached_scaled_sprite(
                img,
                z,
                sprite_perspective_q=sprite_perspective_q,
                sprite_tilt=1.0,
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
        if self._anchor == "center":
            ox = int(sx - sw * 0.5)
            oy = int(sy - sh * 0.5)
        else:
            # feet: 발=pos
            ox = int(sx - sw * 0.5)
            oy = int(sy - sh)
        screen.blit(scaled, (ox, oy))


def _cfg(key: str, default=None):
    return BULLFROG_DEFAULTS.get(key, default)


def _field_cfg(map_id: str, world_data) -> dict:
    """world_data[map].bullfrog ⊕ BULLFROG_DEFAULTS."""
    out = dict(BULLFROG_DEFAULTS)
    mid = str(map_id or "").strip()
    if isinstance(world_data, dict) and mid:
        block = (world_data.get(mid) or {}).get("bullfrog")
        if isinstance(block, dict):
            out.update(block)
    return out


def _scale_from_320(px320: float) -> int:
    sw = float(CONFIG.get("WIDTH", 320) or 320)
    return max(1, int(round(float(px320) * sw / 320.0)))


# ---------------------------------------------------------------------------
# 에셋 로드 (누락 시 플레이스홀더)
# ---------------------------------------------------------------------------
def _placeholder_surf(w: int, h: int, color, label: str = "") -> pygame.Surface:
    s = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
    s.fill((*color[:3], 210 if len(color) < 4 else color[3]))
    if label:
        try:
            font = pygame.font.Font(None, max(10, min(w, h) // 3))
            t = font.render(label[:6], True, (20, 20, 20))
            s.blit(t, t.get_rect(center=(w // 2, h // 2)))
        except Exception:
            pass
    return s


def _load_char_frames(char_name: str, state: str) -> List[pygame.Surface]:
    """engine.load_anim_auto 우선. 분홍 플레이스홀더만 있으면 빈 목록."""
    name = str(char_name or "").strip()
    st = str(state or "idle").strip()
    if not name:
        return []
    try:
        from engine import load_anim_auto

        frames = load_anim_auto(name, st, "left")
        if frames:
            # 분홍 플레이스홀더만 있으면 "없음"으로 취급
            if len(frames) == 1:
                px = frames[0]
                if px.get_width() <= 24 and px.get_height() <= 32:
                    c = px.get_at((px.get_width() // 2, px.get_height() // 2))
                    if c[0] > 200 and c[1] < 40 and c[2] > 200:
                        return []
            return list(frames)
    except Exception:
        pass
    return []


def _is_magenta_placeholder(surf: pygame.Surface) -> bool:
    try:
        if surf.get_width() > 24 or surf.get_height() > 32:
            return False
        c = surf.get_at((surf.get_width() // 2, surf.get_height() // 2))
        return c[0] > 200 and c[1] < 40 and c[2] > 200
    except Exception:
        return False


def _load_lotus_frames(set_name: str, state: str, tile: int) -> List[pygame.Surface]:
    """
    연꽃잎 land/hit 프레임.
    폴더: character/<set>/<state>_left/*.png
    파일명 규칙이 lotusleaf01_* 처럼 폴더명(lotusleaf1)과 달라도
    디렉터리 PNG 전부 로드 (에셋 export 이름 호환).
    """
    name = str(set_name or "").strip()
    st = str(state or "land").strip().lower()
    frames = _load_char_frames(name, st)
    if frames and not (len(frames) == 1 and _is_magenta_placeholder(frames[0])):
        return frames
    # stem 불일치 폴백 — 폴더 안 PNG 전부
    try:
        import os
        from engine import _load_anim_dir_cached

        path = os.path.join("assets", "images", "character", name, f"{st}_left")
        loaded = _load_anim_dir_cached(path)
        if loaded:
            print(f"[bullfrog] lotus frames via dir: {name}/{st}_left ({len(loaded)})")
            return list(loaded)
    except Exception as e:
        print(f"[bullfrog] lotus dir load fail {name}/{st}: {e}")
    # 프로시저럴 플레이스홀더
    colors = {
        "land": (70, 160, 70),
        "hit": (110, 200, 90),
    }
    s = _placeholder_surf(tile, tile, colors.get(st, (70, 160, 70)), f"{st[:4]}")
    pygame.draw.ellipse(s, (50, 130, 55), s.get_rect().inflate(-4, -10), 1)
    return [s]


class BullfrogActivity(BaseFieldActivity):
    """황소개구리 보스 — 연꽃잎 타일 위에서 물방울 회피 + 간질 반격."""

    activity_id = "bullfrog"

    def __init__(self):
        self.state = ST_QUIT
        self.map_id = ""
        self.field: dict = {}
        self._rng = random.Random()
        self._ev_mgr = None
        self._player_ref = None
        self._bg_surf = None

        self._return_map = ""
        self._return_pos: Optional[List[float]] = None
        self._should_return = False
        self._won = False
        self._save_patch: Dict[str, Any] = {}
        self._win_flag = "progress_bullfrog_win"

        self._tile = 32
        self._cols = 8
        self._rows = 7
        self._ox = 32.0
        self._oy = 16.0
        self._boss_col = 2
        self._boss_row = 2
        self._boss_w = 4
        self._boss_h = 3
        self._combat_enabled = False

        self._leaf_tiles: List[TileXY] = []
        self._leaf_variant: Dict[TileXY, int] = {}
        # 타일별 애니: state=land|hit, t=경과초. 기본은 land 루프
        self._leaf_anim: Dict[TileXY, Dict[str, Any]] = {}
        self._player_tile: TileXY = (0, 6)
        self._player_from: TileXY = (0, 6)
        self._player_jump_t = 0.0
        self._player_jumping = False
        self._player_land_cd = 0.0
        # 착지 바운스: frame ix / 경과초. y오프셋은 field.player_land_bob_y
        self._player_bob_ix = -1
        self._player_bob_t = 0.0
        self._player_base_height = 0.0
        self._player_visible_saved = True
        self._player_hide_shadow_saved = False

        self._lives = 3
        self._set_ix = 0  # 0-based, 클리어한 세트 수
        self._attacks_in_set = 0  # 현재 세트에서 턴(회피 성공) 수
        self._counter_fail_all_drop = False  # 반격 실패 후 전타일 패널티 낙하 중
        self._phase_t = 0.0
        self._phase_dur = 0.0
        self._finish_hold = 0.0

        self._shadow_tiles: set = set()
        self._safe_tiles: set = set()
        # 병렬 웨이브: [{tiles, phase, t, start_at, land_done}, ...]
        # phase: waiting | shadow | drop | done
        self._wave_actors: List[Dict[str, Any]] = []
        self._wave_attack_t = 0.0  # 이번 공격 턴 경과(초)
        self._turn_hit = False  # 이번 splash 턴에서 이미 1회 피격했는지
        self._falldown_active = False
        self._falldown_t = 0.0
        self._falldown_dur = 0.0
        self._drop_t = 0.0  # ST_HIT 잔여 impact용(레거시)
        self._drop_was_hit = False
        self._pending_next_drop = False
        self._falldown_frame_ends: List[float] = []
        self._ally_tile: Optional[TileXY] = None
        self._ally_visible = False
        # 반격 연출용 아군 위치/높이 오버라이드
        self._ally_draw_xy: Optional[Tuple[float, float]] = None
        self._ally_draw_h = 0.0
        self._ally_anim = "idle"
        self._ally_anim_t = 0.0

        self._boss_anim = "idle"
        self._boss_anim_t = 0.0
        self._boss_offset_y = 0.0  # 점프 높이(월드)
        self._boss_air_lock = False
        self._boss_air_h = 0.0
        self._counter_fail_all_drop = False
        # 자유 점프(보스 배↔타일): {ax,ay,bx,by,ha,hb,peak,t,dur,land_tile,leaf_hit,done}
        self._player_arc: Optional[Dict[str, Any]] = None
        self._ally_arc: Optional[Dict[str, Any]] = None
        self._msg = ""
        self._announce = ""

        self._cam_fixed = (160.0, 120.0)
        self._cam_pan_from = (160.0, 60.0)
        self._cam_pan_to = (160.0, 120.0)
        self._field_camera_command: Optional[Dict[str, Any]] = None
        self._pending_world_zoom: Optional[Dict[str, Any]] = None
        self._counter_zoom_active = False
        self._field_tilt_target: Optional[float] = 0.0

        # 에셋 캐시 — lotus_land/hit[variant_ix]
        self._lotus_land: List[List[pygame.Surface]] = []
        self._lotus_hit: List[List[pygame.Surface]] = []
        self._boss_frames: Dict[str, List[pygame.Surface]] = {}
        self._ally_frames: Dict[str, List[pygame.Surface]] = {}
        self._drop_fall: List[pygame.Surface] = []
        self._drop_impact: List[pygame.Surface] = []
        self._wave_frames: List[pygame.Surface] = []
        # wave 인스턴스: {wx, wy, t, dur}
        self._waves: List[Dict[str, Any]] = []
        # splash01/02 FX
        self._splash_attack_frames: List[pygame.Surface] = []
        self._splash_counter_frames: List[pygame.Surface] = []
        # splash 인스턴스: {wx, wy, t, dur, frames}
        self._splashes: List[Dict[str, Any]] = []
        self._splash_kind = "attack"  # "attack" | "counter"
        self._splash_fade_active = False
        self._splash_shadows_ready = False
        self._submerged_mode = "resume_attack"  # "resume_attack" | "next_set"
        self._key_held = False

        self.field_tilt_enabled: Optional[bool] = False
        self.field_tilt_target: Optional[float] = 1.0

    # ------------------------------------------------------------------ begin

    def begin(self, player, **params) -> bool:
        self._player_ref = player
        self._ev_mgr = params.get("ev_mgr")
        self._bg_surf = params.get("bg")
        self.map_id = str(
            params.get("map") or params.get("map_id") or _cfg("default_map_id", "bg_pond01")
        ).strip()
        self.field = _field_cfg(self.map_id, params.get("world_data"))

        self._win_flag = str(self.field.get("story_win_flag") or _cfg("story_win_flag"))
        self._return_map = str(params.get("return_map") or "").strip()
        rp = params.get("return_pos")
        if isinstance(rp, (list, tuple)) and len(rp) >= 2:
            self._return_pos = [float(rp[0]), float(rp[1])]
        else:
            self._return_pos = None
        self._resolve_return_anchor()

        self._tile = int(self.field.get("tile_size", 32))
        self._cols = int(self.field.get("grid_cols", 8))
        self._rows = int(self.field.get("grid_rows", 7))
        self._ox = float(self.field.get("grid_origin_x", 32.0))
        self._oy = float(self.field.get("grid_origin_y", 16.0))
        self._boss_col = int(self.field.get("boss_col", 2))
        self._boss_row = int(self.field.get("boss_row", 2))
        self._boss_w = int(self.field.get("boss_w", 4))
        self._boss_h = int(self.field.get("boss_h", 3))
        self._combat_enabled = bool(self.field.get("combat_enabled", False))

        cf = self.field.get("cam_fixed") or [160.0, 120.0]
        try:
            self._cam_fixed = (float(cf[0]), float(cf[1]))
        except (TypeError, ValueError, IndexError):
            self._cam_fixed = (160.0, 120.0)

        self._rng = random.Random()
        self._build_leaf_tiles()
        self._load_assets()

        sc = int(self.field.get("start_col", 0))
        sr = int(self.field.get("start_row", self._rows - 1))
        start = (sc, sr)
        if start not in self._leaf_tiles and self._leaf_tiles:
            start = self._leaf_tiles[0]
        self._player_tile = start
        self._player_from = start

        self._lives = max(1, int(self.field.get("player_lives", 3)))
        self._set_ix = 0
        self._attacks_in_set = 0
        self._won = False
        self._should_return = False
        self._save_patch = {}
        self._shadow_tiles = set()
        self._safe_tiles = set()
        self._wave_actors = []
        self._wave_attack_t = 0.0
        self._turn_hit = False
        self._falldown_active = False
        self._falldown_t = 0.0
        self._falldown_dur = 0.0
        self._pending_next_drop = False
        self._ally_tile = None
        self._ally_visible = False
        self._ally_draw_xy = None
        self._ally_draw_h = 0.0
        self._ally_anim = "idle"
        self._leaf_anim = {}
        self._init_leaf_anims_land()
        self._waves = []
        self._splashes = []
        self._splash_kind = "attack"
        self._splash_fade_active = False
        self._splash_shadows_ready = False
        self._submerged_mode = "resume_attack"
        self._boss_anim = "idle"
        self._boss_anim_t = 0.0
        self._boss_offset_y = 0.0
        self._boss_air_lock = False
        self._boss_air_h = 0.0
        self._player_arc = None
        self._ally_arc = None
        self._msg = "연꽃잎을 눌러 점프" if not self._combat_enabled else ""
        self._announce = ""
        self._finish_hold = 0.0
        self._counter_zoom_active = False
        self._cam_pan_from = self._resolve_intro_cam_from()
        self._cam_pan_to = self._cam_fixed

        # 틸트/쉬어 끄고 — 인트로는 맵 상단에서 시작
        self._apply_tilt(False)
        self._field_camera_command = {
            "mode": "fixed",
            "x": self._cam_pan_from[0],
            "y": self._cam_pan_from[1],
            "smooth": False,
        }
        self._request_arena_zoom()

        # 플레이어를 화면 밖(시작 타일 아래)에 두고 카메라 연출 동안 숨김
        try:
            self._player_base_height = float(getattr(player, "height", 0.0) or 0.0)
            self._player_visible_saved = bool(getattr(player, "visible", True))
            player.stop_moving()
            player.path = []
            foot = self._tile_center(start)
            player.pos[0] = foot[0]
            player.pos[1] = foot[1] + float(self._tile) * 1.5
            player.target = list(player.pos)
            player.direction = "left"
            player.height = self._player_base_height
            self._player_hide_shadow_saved = bool(getattr(player, "_hide_feet_shadow", False))
            player._hide_feet_shadow = True
            try:
                player.is_visible = False
            except Exception:
                pass
        except Exception:
            pass

        self._player_land_cd = 0.0
        self._player_bob_ix = -1
        self._player_bob_t = 0.0
        self._player_jumping = False
        self._player_from = start
        # 카메라 홀드 → 팬 → 캐릭터 등장 → 타이틀 → 게임
        hold = max(0.0, float(self.field.get("intro_cam_hold_sec", 0.8)))
        if hold > 0.01:
            self.state = ST_CAM_HOLD
            self._phase_t = 0.0
            self._phase_dur = hold
        else:
            self._begin_cam_pan()
        print(f"[bullfrog] begin map={self.map_id} leaves={len(self._leaf_tiles)}")
        return True

    def cancel(self) -> None:
        if self.state == ST_QUIT:
            return
        self._restore_counter_zoom_fx()
        self._cleanup_player()
        self._should_return = True
        self.state = ST_QUIT
        self._finish_hold = 0.05
        self._announce = ""

    @property
    def is_active(self) -> bool:
        return self.state != ST_QUIT

    @property
    def is_finished(self) -> bool:
        return self.state == ST_QUIT and self._finish_hold <= 0.0

    def blocks_field_move(self) -> bool:
        return self.state != ST_QUIT

    def blocks_zone_confirm(self) -> bool:
        return self.state != ST_QUIT

    def save_location_override(self):
        if self._return_map:
            pos = self._return_pos
            if not (isinstance(pos, (list, tuple)) and len(pos) >= 2):
                _, pos = self._configured_exit()
            return self._return_map, [float(pos[0]), float(pos[1])]
        return None

    def result(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "activity": self.activity_id,
            "won": bool(self._won),
            "quit": True,
            "exit_event_id": "ev_bullfrog_exit",
            "save_patch": dict(self._save_patch),
            "sets_cleared": int(self._set_ix),
        }
        if self._return_map:
            out["return_map"] = self._return_map
            pos = self._return_pos
            if not (isinstance(pos, (list, tuple)) and len(pos) >= 2):
                _, pos = self._configured_exit()
            out["return_pos"] = [float(pos[0]), float(pos[1])]
        return out

    def poll_camera_command(self) -> Optional[Dict[str, Any]]:
        cmd = self._field_camera_command
        self._field_camera_command = None
        if cmd is not None:
            return cmd
        if self.state in (ST_QUIT,):
            return None
        # 인트로 카메라: 상단 홀드 / 아레나로 팬
        if self.state == ST_CAM_HOLD:
            return {
                "mode": "fixed",
                "x": float(self._cam_pan_from[0]),
                "y": float(self._cam_pan_from[1]),
                "smooth": False,
            }
        if self.state == ST_CAM_PAN:
            x, y = self._cam_pan_xy()
            return {
                "mode": "fixed",
                "x": x,
                "y": y,
                "smooth": False,
            }
        # 반격 확대 연출 중: 플레이어 중심 고정 (매 틱 cam_fixed로 덮지 않음)
        if self._counter_zoom_active:
            px, py = self._player_focus_xy()
            return {
                "mode": "fixed",
                "x": px,
                "y": py,
                "smooth": False,
            }
        return {
            "mode": "fixed",
            "x": self._cam_fixed[0],
            "y": self._cam_fixed[1],
            "smooth": False,
        }

    def poll_world_zoom_command(self) -> Optional[Dict[str, Any]]:
        cmd = self._pending_world_zoom
        self._pending_world_zoom = None
        return cmd

    def _player_focus_xy(self) -> Tuple[float, float]:
        p = self._player_ref
        if p is not None:
            try:
                return float(p.pos[0]), float(p.pos[1])
            except Exception:
                pass
        return self._tile_center(self._player_tile)

    def _arena_world_zoom_value(self) -> float:
        return float(self.field.get("arena_world_zoom", 2.0) or 2.0)

    def _resolve_intro_cam_from(self) -> Tuple[float, float]:
        """맵 상단 풍경용 카메라 시작점."""
        raw = self.field.get("intro_cam_from")
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            try:
                return float(raw[0]), float(raw[1])
            except (TypeError, ValueError):
                pass
        y = float(self.field.get("intro_cam_from_y", 60.0) or 60.0)
        return float(self._cam_fixed[0]), y

    def _cam_pan_xy(self) -> Tuple[float, float]:
        """상단 → 아레나 smoothstep 보간."""
        fx, fy = float(self._cam_pan_from[0]), float(self._cam_pan_from[1])
        tx, ty = float(self._cam_pan_to[0]), float(self._cam_pan_to[1])
        dur = max(0.01, float(self._phase_dur) or 0.01)
        u = max(0.0, min(1.0, float(self._phase_t) / dur))
        s = u * u * (3.0 - 2.0 * u)
        return fx + (tx - fx) * s, fy + (ty - fy) * s

    def _begin_cam_pan(self) -> None:
        self.state = ST_CAM_PAN
        self._phase_t = 0.0
        self._phase_dur = max(0.05, float(self.field.get("intro_cam_pan_sec", 3.5)))
        self._cam_pan_to = self._cam_fixed
        self._announce = ""
        self._msg = ""

    def _begin_player_enter(self) -> None:
        """카메라 도착 후 플레이어 등장(점프 인) → 타이틀로 이어짐."""
        p = self._player_ref
        if p is not None:
            try:
                p.is_visible = True
            except Exception:
                pass
        self.state = ST_INTRO
        self._phase_t = 0.0
        self._phase_dur = float(self.field.get("intro_enter_sec", 0.55))
        self._player_jumping = True
        self._player_from = self._player_tile
        self._start_player_jump_anim(duration_sec=self._phase_dur)
        # 아레나 카메라 확정
        self._field_camera_command = {
            "mode": "fixed",
            "x": self._cam_fixed[0],
            "y": self._cam_fixed[1],
            "smooth": False,
        }

    def _start_counter_zoom_fx(self) -> None:
        """반격 prep: 플레이어 중심 zoom-in (야구 초강력타격과 동일 계열)."""
        self._counter_zoom_active = True
        px, py = self._player_focus_xy()
        cam_dur = float(self.field.get("counter_zoom_cam_dur_sec", 0.12))
        self._field_camera_command = {
            "mode": "fixed",
            "x": px,
            "y": py,
            "smooth": True,
            "duration_sec": max(0.0, cam_dur),
        }
        if not bool(self.field.get("world_zoom_auto", True)):
            return
        self._pending_world_zoom = {
            "val": float(self.field.get("counter_zoom_value", 4.0)),
            "duration_sec": float(self.field.get("counter_zoom_in_sec", 0.12)),
        }

    def _restore_counter_zoom_fx(self) -> None:
        """점프 시작/종료: 아레나 zoom·고정 카메라로 복귀."""
        was = bool(self._counter_zoom_active)
        self._counter_zoom_active = False
        cam_dur = float(self.field.get("counter_zoom_cam_dur_sec", 0.12))
        self._field_camera_command = {
            "mode": "fixed",
            "x": self._cam_fixed[0],
            "y": self._cam_fixed[1],
            "smooth": True,
            "duration_sec": max(0.0, cam_dur),
        }
        if not was:
            return
        if not bool(self.field.get("world_zoom_auto", True)):
            return
        self._pending_world_zoom = {
            "val": self._arena_world_zoom_value(),
            "duration_sec": float(self.field.get("counter_zoom_restore_sec", 0.12)),
        }

    # ------------------------------------------------------------------ grid

    def _is_boss_tile(self, col: int, row: int) -> bool:
        return (
            self._boss_col <= col < self._boss_col + self._boss_w
            and self._boss_row <= row < self._boss_row + self._boss_h
        )

    def _build_leaf_tiles(self) -> None:
        leaves: List[TileXY] = []
        for r in range(self._rows):
            for c in range(self._cols):
                if self._is_boss_tile(c, r):
                    continue
                leaves.append((c, r))
        self._leaf_tiles = leaves
        sets = list(self.field.get("lotus_leaf_sets") or _cfg("lotus_leaf_sets") or [])
        nsets = max(1, len(sets))
        # 타일마다 lotusleaf1~3 중 랜덤
        self._leaf_variant = {t: self._rng.randrange(nsets) for t in leaves}

    def _init_leaf_anims_land(self) -> None:
        """모든 연꽃잎을 land 루프 상태로."""
        self._leaf_anim = {t: {"state": "land", "t": 0.0} for t in self._leaf_tiles}

    def _play_leaf_hit(self, tile: TileXY) -> None:
        """캐릭터(또는 물방울) 착지 — hit 1회 재생 후 land 복귀 + wave 스폰."""
        if tile not in self._leaf_tiles:
            return
        self._leaf_anim[tile] = {"state": "hit", "t": 0.0}
        self._spawn_wave_at_tile(tile)

    def _spawn_wave_at_tile(self, tile: TileXY) -> None:
        if not self._wave_frames:
            return
        cx, cy = self._tile_center(tile)
        fps = max(1.0, float(self.field.get("anim_fps", 10.0)))
        dur = float(len(self._wave_frames)) / fps
        self._waves.append({"wx": cx, "wy": cy, "t": 0.0, "dur": dur})

    def _tick_waves(self, dt: float) -> None:
        if not self._waves:
            return
        alive = []
        for w in self._waves:
            w["t"] = float(w.get("t") or 0.0) + dt
            if float(w["t"]) < float(w.get("dur") or 0.4):
                alive.append(w)
        self._waves = alive

    def _boss_foot_xy(self) -> Tuple[float, float]:
        tile = self._tile
        bx = self._ox + (self._boss_col + self._boss_w * 0.5) * tile
        by = self._oy + (self._boss_row + self._boss_h) * tile
        return float(bx), float(by)

    def _spawn_splash_fx(self, kind: str = "attack") -> None:
        """착수 물튀김. attack/counter 모두 splash 프레임 사용(현재 둘 다 splash01)."""
        frames = (
            self._splash_attack_frames
            if kind == "attack"
            else (self._splash_counter_frames or self._splash_attack_frames)
        )
        if not frames:
            # 에셋 없으면 wave로 약한 대체
            if self._wave_frames:
                frames = self._wave_frames
            else:
                return
        fps = float(self.field.get("splash_fx_fps", self.field.get("anim_fps", 10.0)))
        dur = max(0.15, float(len(frames)) / max(1.0, fps))
        wx, wy = self._boss_foot_xy()
        off_y = float(
            self.field.get(
                "splash_attack_offset_y" if kind == "attack" else "splash_counter_offset_y",
                0.0,
            )
            or 0.0
        )
        self._splashes.append({
            "wx": wx,
            "wy": wy + off_y,
            "t": 0.0,
            "dur": dur,
            "frames": frames,
            "fps": fps,
        })

    def _tick_splashes(self, dt: float) -> None:
        if not self._splashes:
            return
        alive = []
        for s in self._splashes:
            s["t"] = float(s.get("t") or 0.0) + dt
            if float(s["t"]) < float(s.get("dur") or 0.01):
                alive.append(s)
        self._splashes = alive

    def _splash_fade_timings(self) -> Tuple[float, float, float]:
        fade_in = max(0.05, float(self.field.get("splash_fade_in_sec", 1.0)))
        fade_hold = max(0.0, float(self.field.get("splash_fade_hold_sec", 0.6)))
        fade_out = max(0.05, float(self.field.get("splash_fade_out_sec", 0.8)))
        return fade_in, fade_hold, fade_out

    def _splash_fade_alpha(self) -> int:
        """공격 착수 라이트블루 페이드 알파(0~255). in → hold(최대) → out."""
        if not self._splash_fade_active:
            return 0
        if self.state != ST_SPLASH:
            return 0
        fade_in, fade_hold, fade_out = self._splash_fade_timings()
        amax = int(self.field.get("splash_fade_alpha_max", 230) or 230)
        amax = max(0, min(255, amax))
        t = float(self._phase_t)
        if t <= fade_in:
            u = t / fade_in
            return int(round(amax * max(0.0, min(1.0, u))))
        if t <= fade_in + fade_hold:
            return amax
        u = (t - fade_in - fade_hold) / fade_out
        return int(round(amax * max(0.0, min(1.0, 1.0 - u))))

    def _begin_landing_splash(self, *, all_tiles: bool = False) -> None:
        """착수 공통: 보스 숨김 + splash/페이드 → emerge → 다단 그림자 → 다단 물방울.

        all_tiles=True 이면 전타일 단파 낙하(반격 실패). False면 일반 다단 웨이브.
        """
        self._splash_kind = "attack"  # 페이드·숨김 연출은 공격과 동일
        self._splash_fade_active = True
        self._splash_shadows_ready = False
        self._submerged_mode = "resume_attack"
        self._counter_fail_all_drop = bool(all_tiles)
        self.state = ST_SPLASH
        self._phase_t = 0.0
        fade_in, fade_hold, fade_out = self._splash_fade_timings()
        self._phase_dur = fade_in + fade_hold + fade_out
        self._boss_anim = "idle"
        self._boss_anim_t = 0.0
        self._boss_offset_y = 0.0
        self._apply_tilt(False)
        self._shadow_tiles = set()
        self._safe_tiles = set()
        self._wave_actors = []
        self._wave_attack_t = 0.0
        self._turn_hit = False
        self._pending_next_drop = False
        self._spawn_splash_fx("attack")
        self._announce = "풍덩!"
        self._msg = "피할 수 없다!" if all_tiles else ""

    def _begin_attack_splash(self) -> None:
        """일반 공격 착수."""
        self._begin_landing_splash(all_tiles=False)

    def _begin_counter_miss_descend(self) -> None:
        """반격 실패: jumpfly 체공에서 jump3로 수면 하강 → 착수 공통 연출."""
        self._ally_visible = False
        self._ally_tile = None
        self._ally_draw_xy = None
        self._boss_air_lock = False
        self._counter_fail_all_drop = True
        self._attacks_in_set = 0
        # 하강 시작 높이 보존 (창 중 peak)
        peak = float(self.field.get("boss_jumpfly_height", 40.0))
        if float(self._boss_offset_y or 0.0) > 1.0:
            peak = float(self._boss_offset_y)
        self._boss_air_h = peak
        self.state = ST_COUNTER_MISS_DESCEND
        self._phase_t = 0.0
        self._phase_dur = max(0.05, float(self.field.get("boss_jump3_sec", 0.5)))
        self._boss_anim = "jump3"
        self._boss_anim_t = 0.0
        self._apply_tilt(True)
        self._announce = "놓쳤다!"
        self._msg = "세트 처음부터…"

    def _dodges_needed_for_counter(self) -> int:
        """반격 기회까지 필요한 회피 성공 수."""
        v = self.field.get("dodges_before_counter")
        if v is None:
            v = self.field.get("attacks_before_counter", _cfg("dodges_before_counter", 3))
        return max(1, int(v or 3))

    def _reset_set_progress(self, *, announce: str = "") -> None:
        """현재 세트 회피 카운트 초기화 (반격 실패 시)."""
        self._attacks_in_set = 0
        self._counter_fail_all_drop = False
        if announce:
            self._announce = announce

    def _on_dodge_success(self) -> None:
        """물방울 회피 성공(전 웨이브 무피격) → 카운트 증가 후 WAIT. 패널티 낙하면 세트 재시작만."""
        self._shadow_tiles = set()
        self._wave_actors = []
        self._wave_attack_t = 0.0
        if self._counter_fail_all_drop:
            # 반격 실패 패널티 낙하를 버팀 → 세트 처음부터
            self._reset_set_progress(announce="")
            self._msg = "세트 다시! 턴부터"
            self._announce = ""
        else:
            self._attacks_in_set += 1
            need = self._dodges_needed_for_counter()
            self._msg = f"턴 {self._attacks_in_set}/{need}"
            self._announce = ""
        self.state = ST_WAIT
        self._phase_t = 0.0
        self._phase_dur = float(self.field.get("attack_interval_sec", 10.0))

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
            st = str(info.get("state") or "land")
            if st == "hit":
                vi = int(self._leaf_variant.get(tile, 0))
                if float(info["t"]) >= self._leaf_hit_duration(vi):
                    info["state"] = "land"
                    info["t"] = 0.0

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

    def _tile_center(self, tile: TileXY) -> Tuple[float, float]:
        c, r = tile
        return (
            self._ox + (c + 0.5) * self._tile,
            self._oy + (r + 0.5) * self._tile,
        )

    def _tile_at_world(self, wx: float, wy: float) -> Optional[TileXY]:
        c = int((wx - self._ox) // self._tile)
        r = int((wy - self._oy) // self._tile)
        if 0 <= c < self._cols and 0 <= r < self._rows:
            t = (c, r)
            if t in self._leaf_tiles:
                return t
        return None

    def _neighbors4(self, tile: TileXY) -> List[TileXY]:
        c, r = tile
        out = []
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c + dc, r + dr)
            if n in self._leaf_tiles:
                out.append(n)
        return out

    def _configured_exit(self) -> Tuple[str, List[float]]:
        em = str(self.field.get("exit_map") or _cfg("exit_map", "bg_jjangpu")).strip()
        ep = self.field.get("exit_pos") or _cfg("exit_pos", [816.0, 2304.0])
        try:
            pos = [float(ep[0]), float(ep[1])]
        except (TypeError, ValueError, IndexError):
            pos = [816.0, 2304.0]
        return em or "bg_jjangpu", pos

    def _resolve_return_anchor(self) -> None:
        if self._return_map:
            if self._return_pos is None:
                _, self._return_pos = self._configured_exit()
            return
        self._return_map, self._return_pos = self._configured_exit()

    def _request_arena_zoom(self) -> None:
        """
        320×240 아레나를 화면에 맞춤.
        전역 기본은 NATIVE_640(640×480)이라, world_zoom val=2.0 을 요청하면
        AUTO_OUTPUT_MODE 가 UPSCALED 320 으로 전환되며 타일 1칸=32px 로 보인다.
        (잘못된 키 on/strength 를 쓰면 val 기본 1.0 → 640 화면에 맵만 작게 보임)
        """
        if not bool(self.field.get("world_zoom_auto", True)):
            return
        try:
            # baseball 과 동일: pending_world_zoom 은 val / duration_sec / instant
            play_zoom = self._arena_world_zoom_value()
            self._pending_world_zoom = {
                "val": play_zoom,
                "duration_sec": 0.0,
                "instant": True,
            }
        except Exception:
            pass

    # ------------------------------------------------------------------ assets

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

        boss = str(self.field.get("bullfrog_char") or "bullfrog")
        self._boss_frames = {}
        for st in ("idle", "jump1", "jump2", "jump3", "jumpfly", "down", "sink", "emerge"):
            fr = _load_char_frames(boss, st)
            if not fr:
                # 보스 영역 ≈ 4×3 타일
                bw = self._boss_w * tile
                bh = self._boss_h * tile
                colors = {
                    "idle": (60, 120, 50),
                    "jump1": (80, 150, 60),
                    "jump2": (90, 160, 70),
                    "jump3": (70, 140, 55),
                    "jumpfly": (110, 170, 90),
                    "down": (200, 180, 60),
                    "sink": (50, 95, 130),
                    "emerge": (85, 125, 160),
                }
                fr = [_placeholder_surf(bw, bh, colors.get(st, (60, 120, 50)), st)]
            self._boss_frames[st] = fr

        ally = str(self.field.get("ally_frog_char") or "frog01")
        self._ally_frames = {}
        for st in ("idle", "jump"):
            fr = _load_char_frames(ally, st)
            if not fr:
                fr = [_placeholder_surf(tile - 4, tile - 4, (40, 160, 70), "frog")]
            self._ally_frames[st] = fr

        # waterdrop_fx_dir → fall, waterdrop_impact_fx_dir → impact (없으면 character/ 폴백)
        drop_fx_dir = str(
            self.field.get("waterdrop_fx_dir")
            or _cfg("waterdrop_fx_dir")
            or ""
        ).strip()
        drop_fx_name = str(
            self.field.get("waterdrop_fx") or _cfg("waterdrop_fx") or ""
        ).strip()
        if not drop_fx_dir and drop_fx_name:
            drop_fx_dir = f"assets/images/fx/{drop_fx_name}"
        impact_fx_dir = str(
            self.field.get("waterdrop_impact_fx_dir")
            or _cfg("waterdrop_impact_fx_dir")
            or ""
        ).strip()
        impact_fx_name = str(
            self.field.get("waterdrop_impact_fx") or _cfg("waterdrop_impact_fx") or ""
        ).strip()
        if not impact_fx_dir and impact_fx_name:
            impact_fx_dir = f"assets/images/fx/{impact_fx_name}"

        self._drop_fall = []
        self._drop_impact = []
        if drop_fx_dir:
            try:
                from engine import _load_anim_dir_cached

                loaded = _load_anim_dir_cached(drop_fx_dir)
                if loaded:
                    self._drop_fall = list(loaded)
                    print(f"[bullfrog] waterdrop fall fx: {drop_fx_dir} ({len(self._drop_fall)} frames)")
            except Exception as e:
                print(f"[bullfrog] waterdrop fall fx load fail {drop_fx_dir}: {e}")
        if impact_fx_dir:
            try:
                from engine import _load_anim_dir_cached

                loaded = _load_anim_dir_cached(impact_fx_dir)
                if loaded:
                    self._drop_impact = list(loaded)
                    print(f"[bullfrog] waterdrop impact fx: {impact_fx_dir} ({len(self._drop_impact)} frames)")
            except Exception as e:
                print(f"[bullfrog] waterdrop impact fx load fail {impact_fx_dir}: {e}")
        drop_char = str(self.field.get("waterdrop_char") or _cfg("waterdrop_char") or "waterdrop")
        if not self._drop_fall:
            self._drop_fall = _load_char_frames(drop_char, "fall")
        if not self._drop_impact:
            self._drop_impact = _load_char_frames(drop_char, "impact")
        if not self._drop_fall:
            self._drop_fall = [_placeholder_surf(16, 22, (120, 180, 255), "drop")]
        if not self._drop_impact:
            self._drop_impact = [_placeholder_surf(tile - 4, 14, (180, 210, 255), "splash")]

        # wave01 — assets/images/fx/wave01/wave01_0.png … (캐릭터 폴더 아님)
        self._wave_frames = []
        wave_dir = str(
            self.field.get("wave_fx_dir")
            or _cfg("wave_fx_dir")
            or "assets/images/fx/wave01"
        ).strip()
        wave_name = str(self.field.get("wave_fx") or _cfg("wave_fx") or "wave01").strip()
        if not wave_dir and wave_name:
            wave_dir = f"assets/images/fx/{wave_name}"
        if wave_dir:
            try:
                from engine import _load_anim_dir_cached

                loaded = _load_anim_dir_cached(wave_dir)
                if loaded:
                    self._wave_frames = list(loaded)
                    print(f"[bullfrog] wave fx: {wave_dir} ({len(self._wave_frames)} frames)")
            except Exception as e:
                print(f"[bullfrog] wave fx load fail {wave_dir}: {e}")
                self._wave_frames = []

        # splash01 — 착수 물튀김 (공격/반격 공통; counter 키는 splash02 교체용)
        self._splash_attack_frames = self._load_fx_dir(
            "splash_attack_fx_dir",
            "splash_attack_fx",
            "assets/images/fx/splash01",
            "splash01",
        )
        self._splash_counter_frames = self._load_fx_dir(
            "splash_counter_fx_dir",
            "splash_counter_fx",
            "assets/images/fx/splash01",
            "splash_counter",
        )
        # counter 에셋 없으면 attack(splash01)과 공유
        if not self._splash_counter_frames and self._splash_attack_frames:
            self._splash_counter_frames = list(self._splash_attack_frames)

    def _load_fx_dir(
        self,
        dir_key: str,
        name_key: str,
        default_dir: str,
        label: str,
    ) -> List[pygame.Surface]:
        fx_dir = str(self.field.get(dir_key) or _cfg(dir_key) or default_dir).strip()
        fx_name = str(self.field.get(name_key) or _cfg(name_key) or "").strip()
        if not fx_dir and fx_name:
            fx_dir = f"assets/images/fx/{fx_name}"
        if not fx_dir:
            return []
        try:
            from engine import _load_anim_dir_cached

            loaded = _load_anim_dir_cached(fx_dir)
            if loaded:
                print(f"[bullfrog] {label} fx: {fx_dir} ({len(loaded)} frames)")
                return list(loaded)
        except Exception as e:
            print(f"[bullfrog] {label} fx load fail {fx_dir}: {e}")
        return []

    def _anim_frame(self, frames: List[pygame.Surface], t: float) -> pygame.Surface:
        if not frames:
            return _placeholder_surf(16, 16, (255, 0, 255))
        fps = float(self.field.get("anim_fps", 10.0))
        ix = int(t * fps) % len(frames)
        return frames[ix]

    # ------------------------------------------------------------------ combat helpers

    def _safe_count_for_set(self) -> int:
        arr = list(self.field.get("safe_tiles_by_set") or _cfg("safe_tiles_by_set") or [4])
        ix = min(self._set_ix, max(0, len(arr) - 1))
        return max(1, int(arr[ix]))

    def _shadow_sec_for_set(self) -> float:
        arr = list(self.field.get("shadow_sec_by_set") or _cfg("shadow_sec_by_set") or [1.0])
        ix = min(self._set_ix, max(0, len(arr) - 1))
        return max(0.25, float(arr[ix]))

    def _drop_wave_count(self) -> int:
        """일반 공격 병렬 웨이브 수. 반격 실패 패널티는 1파 고정."""
        if self._counter_fail_all_drop:
            return 1
        return max(1, int(self.field.get("drop_wave_count", _cfg("drop_wave_count", 3)) or 3))

    def _drop_wave_gap_sec(self) -> float:
        """다음 차 그림자 시작까지의 간격(초)."""
        return max(
            0.05,
            float(self.field.get("drop_wave_gap_sec", _cfg("drop_wave_gap_sec", 2.0)) or 2.0),
        )

    def _shadow_sec_now(self) -> float:
        """각 차 그림자 예고 시간. 반격실패=counter_miss, 일반=세트별 shadow_sec."""
        if self._counter_fail_all_drop:
            return max(
                0.05,
                float(self.field.get("counter_miss_shadow_sec", _cfg("counter_miss_shadow_sec", 0.5))),
            )
        return self._shadow_sec_for_set()

    def _drop_phase_dur(self) -> float:
        return float(self.field.get("drop_fall_sec", 0.28)) + float(
            self.field.get("drop_impact_sec", 0.35)
        )

    def _boss_profile(self, *, counter: bool) -> List[Tuple[str, float]]:
        # 반격 창은 tick에서 jump1→jumpfly 홀드로 별도 처리 (창 중 jump3/하강 금지)
        if counter:
            return [
                ("jump1", float(self.field.get("boss_jump1_sec", 1.0))),
                ("jumpfly", float(self.field.get("boss_jumpfly_sec", 4.0))),
            ]
        return [
            ("jump1", float(self.field.get("boss_jump1_sec", 1.0))),
            ("jump2", float(self.field.get("boss_jump2_sec", 2.0))),
            ("jump3", float(self.field.get("boss_jump3_sec", 1.0))),
        ]

    def _pick_counter_ally_tile(self) -> TileXY:
        """플레이어와 충분히 먼(맨해튼 8칸 이상 우선) 연꽃잎을 고른다."""
        leaves = [t for t in self._leaf_tiles if t != self._player_tile]
        if not leaves:
            return self._player_tile
        px, py = self._player_tile
        far = [t for t in leaves if abs(t[0] - px) + abs(t[1] - py) >= 8]
        pool = far or leaves
        self._rng.shuffle(pool)
        return pool[0]

    def _pick_spread_tiles(self, pool: List[TileXY], count: int) -> set:
        """맨해튼 거리 최대화로 타일을 화면 전체에 골고루 고른다."""
        if count <= 0 or not pool:
            return set()
        leaves = list(pool)
        if count >= len(leaves):
            return set(leaves)
        self._rng.shuffle(leaves)
        picked: List[TileXY] = [leaves.pop(0)]
        while len(picked) < count and leaves:
            best_i = 0
            best_d = -1
            for i, t in enumerate(leaves):
                d = min(abs(t[0] - p[0]) + abs(t[1] - p[1]) for p in picked)
                if d > best_d or (d == best_d and self._rng.random() < 0.5):
                    best_d = d
                    best_i = i
            picked.append(leaves.pop(best_i))
        return set(picked)

    def _make_wave_actor(self, tiles: set, start_at: float) -> Dict[str, Any]:
        return {
            "tiles": set(tiles),
            "start_at": float(start_at),
            "phase": "waiting",  # waiting | shadow | drop | done
            "t": 0.0,
            "land_done": False,
        }

    def _set_all_shadow_tiles(self) -> None:
        """반격 실패: 전타일 단파 액터 1개."""
        self._safe_tiles = set()
        self._shadow_tiles = set()
        self._wave_actors = [self._make_wave_actor(set(self._leaf_tiles), 0.0)]
        self._wave_attack_t = 0.0

    def _plan_attack_waves(self) -> None:
        """일반 공격: 웨이브마다 안전칸 분산 배치 → 병렬 액터 생성.

        n차 그림자 시작 = (n-1)*gap. 각 차는 shadow_sec 후 자체 낙하.
        """
        leaves = list(self._leaf_tiles)
        self._wave_actors = []
        self._wave_attack_t = 0.0
        self._shadow_tiles = set()
        if not leaves:
            self._safe_tiles = set()
            return
        n_waves = self._drop_wave_count()
        gap = self._drop_wave_gap_sec()
        safe_n = min(self._safe_count_for_set(), max(1, len(leaves) - 1))
        first_safe: set = set()
        for wi in range(n_waves):
            safe = self._pick_spread_tiles(leaves, safe_n)
            if wi == 0:
                first_safe = set(safe)
            danger = set(leaves) - safe
            if not danger and leaves:
                danger = {leaves[self._rng.randrange(len(leaves))]}
            self._wave_actors.append(self._make_wave_actor(danger, wi * gap))
        self._safe_tiles = first_safe

    def _shadow_fade_sec(self) -> float:
        """그림자 힌트 페이드인/아웃 각각 시간. shadow_sec의 절반을 넘지 않게 클램프."""
        fade = max(
            0.0,
            float(self.field.get("shadow_fade_sec", _cfg("shadow_fade_sec", 0.1)) or 0.1),
        )
        shadow_sec = self._shadow_sec_now()
        if shadow_sec <= 0.0:
            return 0.0
        return min(fade, shadow_sec * 0.45)

    def _wave_shadow_fade_mul(self, w: Dict[str, Any]) -> float:
        """그림자 단계 가시성 0~1. 등장·퇴장 시 페이드."""
        if str(w.get("phase") or "") != "shadow":
            return 0.0
        fade = self._shadow_fade_sec()
        shadow_sec = self._shadow_sec_now()
        t = float(w.get("t") or 0.0)
        if fade <= 0.0:
            return 1.0 if 0.0 <= t < shadow_sec else 0.0
        if t < fade:
            return max(0.0, min(1.0, t / fade))
        remain = shadow_sec - t
        if remain < fade:
            return max(0.0, min(1.0, remain / fade))
        return 1.0

    def _shadow_alpha_by_tile(self) -> Dict[TileXY, int]:
        """타일별 그림자 알파(0~255). 여러 웨이브가 겹치면 더 진한 쪽."""
        out: Dict[TileXY, int] = {}
        if self.state not in (ST_SHADOW, ST_DROP, ST_BOSS_JUMP):
            return out
        # 펄스 베이스(80~120) × 웨이브 페이드
        pulse = 80 + int(40 * abs(math.sin(self._wave_attack_t * 8.0)))
        for w in self._wave_actors:
            if str(w.get("phase") or "") != "shadow":
                continue
            mul = self._wave_shadow_fade_mul(w)
            if mul <= 0.001:
                continue
            alpha = int(round(pulse * mul))
            if alpha <= 0:
                continue
            for tile in set(w.get("tiles") or ()):
                prev = out.get(tile, 0)
                if alpha > prev:
                    out[tile] = alpha
        return out

    def _sync_shadow_tiles_from_actors(self) -> None:
        """표시용: 그림자 단계 타일 합집합 (낙하 중은 물방울이 보이므로 제외)."""
        shown: set = set()
        for w in self._wave_actors:
            if w.get("phase") == "shadow":
                # 페이드아웃 중(거의 0)이어도 타일은 유지해 그리기 쪽에서 알파 처리
                shown |= set(w.get("tiles") or ())
        self._shadow_tiles = shown
        if shown:
            self._safe_tiles = set(self._leaf_tiles) - shown

    def _begin_shadow_phase(self) -> None:
        """emerge 후 병렬 웨이브 공격 시작."""
        self._turn_hit = False
        self._drop_was_hit = False
        self._wave_attack_t = 0.0
        if not self._wave_actors:
            if self._counter_fail_all_drop:
                self._set_all_shadow_tiles()
            else:
                self._plan_attack_waves()
        # waiting 상태로 리셋 (splash에서 플랜만 짜 둔 경우)
        for w in self._wave_actors:
            w["phase"] = "waiting"
            w["t"] = 0.0
            w["land_done"] = False
        self._shadow_tiles = set()
        self.state = ST_SHADOW
        self._phase_t = 0.0
        self._phase_dur = 9999.0  # 종료는 액터 all-done으로 판정
        if self._counter_fail_all_drop:
            self._msg = "피할 수 없다!"
        else:
            self._msg = "그림자 없는 잎으로!"
        # t=0 웨이브 즉시 개시
        self._tick_parallel_waves(0.0)

    def _tick_parallel_waves(self, dt: float) -> None:
        """병렬 웨이브 진행. 각 액터: waiting→shadow→drop→done."""
        if not self._wave_actors:
            return
        self._wave_attack_t += dt
        shadow_sec = self._shadow_sec_now()
        fall = float(self.field.get("drop_fall_sec", 0.28))
        drop_dur = self._drop_phase_dur()
        any_drop = False
        active_n = 0
        done_n = 0

        for wi, w in enumerate(self._wave_actors):
            phase = str(w.get("phase") or "waiting")
            if phase == "done":
                done_n += 1
                continue
            active_n += 1
            if phase == "waiting":
                if self._wave_attack_t >= float(w.get("start_at") or 0.0):
                    w["phase"] = "shadow"
                    w["t"] = 0.0
                    phase = "shadow"
                    n = len(self._wave_actors)
                    self._msg = f"그림자 {wi + 1}/{n}"
                else:
                    continue

            w["t"] = float(w.get("t") or 0.0) + dt

            if phase == "shadow":
                if w["t"] >= shadow_sec:
                    w["phase"] = "drop"
                    w["t"] = 0.0
                    w["land_done"] = False
                    phase = "drop"
                    n = len(self._wave_actors)
                    self._msg = f"낙하 {wi + 1}/{n}"

            if phase == "drop":
                any_drop = True
                tiles = set(w.get("tiles") or ())
                # 착지 순간 1회
                if not w.get("land_done") and w["t"] >= fall:
                    w["land_done"] = True
                    for t in tiles:
                        self._play_leaf_hit(t)
                    if (
                        not self._turn_hit
                        and self._player_tile in tiles
                        and not self._player_jumping
                    ):
                        self._apply_player_hit(keep_attack_state=True)
                if w["t"] >= drop_dur:
                    w["phase"] = "done"
                    done_n += 1
                    active_n -= 1

        self._sync_shadow_tiles_from_actors()
        # 낙하가 하나라도 있으면 ST_DROP으로 표시(물방울 draw 경로)
        if any_drop and self.state == ST_SHADOW:
            self.state = ST_DROP
        elif not any_drop and self.state == ST_DROP and active_n > 0:
            # 잠시 그림자만 남은 구간 — ST_SHADOW로 복귀해도 draw는 shadow_tiles 사용
            self.state = ST_SHADOW

        if done_n >= len(self._wave_actors):
            self._finish_attack_turn()

    def _finish_attack_turn(self) -> None:
        """병렬 낙하 종료 — 회피 성공 / 피격 후 대기 / 패배."""
        self._shadow_tiles = set()
        self._wave_actors = []
        self._wave_attack_t = 0.0
        if self._turn_hit or self._drop_was_hit:
            if self._lives <= 0:
                if self._falldown_active:
                    remain = max(0.05, self._falldown_dur - self._falldown_t)
                    self.state = ST_HIT
                    self._phase_t = self._falldown_t
                    self._phase_dur = max(self._phase_t + 0.05, self._falldown_t + min(remain, 0.35))
                else:
                    self._finish_lose()
                return
            if self._counter_fail_all_drop:
                self._reset_set_progress()
                self._msg = "세트 다시! 턴부터"
            else:
                need = self._dodges_needed_for_counter()
                self._msg = f"턴 {self._attacks_in_set}/{need}"
            self._announce = ""
            if self._falldown_active:
                self.state = ST_HIT
                self._phase_t = self._falldown_t
                self._phase_dur = max(self._phase_t + 0.05, self._falldown_dur)
            else:
                self._end_player_jump_anim()
                self.state = ST_WAIT
                self._phase_t = 0.0
                self._phase_dur = float(self.field.get("attack_interval_sec", 10.0))
            return
        self._on_dodge_success()

    def _apply_tilt(self, on: bool) -> None:
        """메인 루프가 이미 쓰는 tilt_control 경로로 bullfrog 틸트를 직접 건다."""
        target = float(self.field.get("boss_jump_tilt_factor", 0.55)) if on else 1.0
        dur = float(self.field.get("boss_tilt_in_sec", 0.25)) if on else float(
            self.field.get("boss_tilt_out_sec", 0.25)
        )
        self.field_tilt_enabled = bool(on)
        self.field_tilt_target = float(target)
        try:
            if self._ev_mgr is not None:
                self._ev_mgr.tilt_control = {
                    "target": float(target),
                    "duration_sec": max(0.0, float(dur)),
                }
        except Exception:
            pass

    def _boss_anim_frame(self) -> pygame.Surface:
        st = self._boss_anim if self._boss_anim in self._boss_frames else "idle"
        frames = self._boss_frames.get(st) or []
        if not frames:
            return _placeholder_surf(self._boss_w * self._tile, self._boss_h * self._tile, (255, 0, 255))
        if st == "idle":
            return self._anim_frame(frames, self._boss_anim_t)
        dur_map = {
            "jump1": float(self.field.get("boss_jump1_sec", 1.0)),
            "jump2": float(self.field.get("boss_jump2_sec", 2.0)),
            "jump3": float(self.field.get("boss_jump3_sec", 1.0)),
            "jumpfly": float(self.field.get("boss_jumpfly_sec", 4.0)),
            "down": float(self.field.get("boss_down_sec", 1.0)),
            "sink": float(self.field.get("sink_sec", 1.5)),
            "emerge": float(self.field.get("rise_sec", 2.0)),
        }
        dur = max(0.01, float(dur_map.get(st, 1.0)))
        ix = min(len(frames) - 1, int((self._boss_anim_t / dur) * len(frames)))
        return frames[ix]

    def _plan_or_set_attack_tiles(self) -> None:
        """splash 페이드 중 미리 웨이브/전타일 플랜."""
        if self._counter_fail_all_drop:
            self._set_all_shadow_tiles()
        else:
            self._plan_attack_waves()

    def _start_boss_attack(self) -> None:
        self.state = ST_BOSS_JUMP
        self._phase_t = 0.0
        self._phase_dur = sum(d for _, d in self._boss_profile(counter=False))
        self._boss_anim = "jump1"
        self._boss_anim_t = 0.0
        self._boss_offset_y = 0.0
        self._counter_fail_all_drop = False
        self._apply_tilt(True)
        self._announce = ""
        self._msg = "풍덩…!"

    def _start_counter_phase(self) -> None:
        self.state = ST_COUNTER_SPAWN
        self._phase_t = 0.0
        self._phase_dur = float(self.field.get("counter_spawn_delay_sec", 5.0))
        self._ally_visible = False
        self._ally_tile = None
        self._announce = ""
        self._msg = "어딘가에서 도와줄 개구리가 나타날 것 같다…"

    def _boss_center_xy(self) -> Tuple[float, float]:
        tile = float(self._tile)
        bx = self._ox + (self._boss_col + self._boss_w * 0.5) * tile
        by = self._oy + (self._boss_row + self._boss_h * 0.5) * tile
        return bx, by

    def _boss_feet_xy(self) -> Tuple[float, float]:
        tile = float(self._tile)
        bx = self._ox + (self._boss_col + self._boss_w * 0.5) * tile
        by = self._oy + (self._boss_row + self._boss_h) * tile
        return bx, by

    def _ensure_player_anim(self, state_name: str) -> str:
        """캐릭터에 세트 주입. 없으면 idle로 폴백한 상태명 반환."""
        st = str(state_name or "idle").strip().lower() or "idle"
        p = self._player_ref
        if p is None:
            return "idle"
        anims_l = getattr(p, "anims_l", None)
        if not isinstance(anims_l, dict):
            return "idle"
        existing = anims_l.get(st)
        if isinstance(existing, list) and existing and not (
            len(existing) == 1 and _is_magenta_placeholder(existing[0])
        ):
            return st
        name = str(getattr(p, "name", "") or "").strip()
        frames = _load_char_frames(name, st) if name else []
        if not frames:
            idle = anims_l.get("idle") or []
            frames = list(idle) if idle else []
            st = "idle"
        if frames:
            anims_l[st] = list(frames)
            anims_r = getattr(p, "anims_r", None)
            if isinstance(anims_r, dict):
                try:
                    anims_r[st] = [pygame.transform.flip(img, True, False) for img in frames]
                except Exception:
                    anims_r[st] = list(frames)
        return st

    def _play_player_state(self, state_name: str, *, duration_sec: float | None = None, loop: bool = True) -> None:
        p = self._player_ref
        if p is None:
            return
        st = self._ensure_player_anim(state_name)
        dur_ms = None if duration_sec is None else max(80, int(round(float(duration_sec) * 1000.0)))
        try:
            p.play_anim(st, duration_ms=dur_ms, loop=bool(loop), release="idle")
            p.state = st
            if st == "idle" and not loop:
                p.frame_idx = 0
                p.last_anim_time = pygame.time.get_ticks() + 10**9
        except Exception:
            pass

    def _freeze_player_idle_frame0(self) -> None:
        """숙이기: idle 첫 프레임 고정."""
        p = self._player_ref
        if p is None:
            return
        try:
            p.clear_anim_override()
        except Exception:
            pass
        try:
            p.state = "idle"
            p.frame_idx = 0
            p.last_anim_time = pygame.time.get_ticks() + 10**9
            anims = p.anims_r if getattr(p, "direction", "left") == "right" else p.anims_l
            frames = (anims or {}).get("idle") or []
            if frames:
                p.image = frames[0]
        except Exception:
            pass

    def _start_player_arc(
        self,
        ax: float,
        ay: float,
        bx: float,
        by: float,
        *,
        ha: float,
        hb: float,
        dur: float,
        peak: float,
        land_tile: Optional[TileXY] = None,
        leaf_hit: bool = False,
        anim: str = "jump",
    ) -> None:
        self._player_jumping = True
        self._player_jump_t = 0.0
        self._player_bob_ix = -1
        self._player_arc = {
            "ax": float(ax),
            "ay": float(ay),
            "bx": float(bx),
            "by": float(by),
            "ha": float(ha),
            "hb": float(hb),
            "peak": float(peak),
            "t": 0.0,
            "dur": max(0.05, float(dur)),
            "land_tile": land_tile,
            "leaf_hit": bool(leaf_hit),
        }
        self._play_player_state(anim, duration_sec=dur, loop=True)

    def _start_ally_arc(
        self,
        ax: float,
        ay: float,
        bx: float,
        by: float,
        *,
        ha: float,
        hb: float,
        dur: float,
        peak: float,
        hide_at_end: bool = False,
    ) -> None:
        self._ally_anim = "jump"
        self._ally_arc = {
            "ax": float(ax),
            "ay": float(ay),
            "bx": float(bx),
            "by": float(by),
            "ha": float(ha),
            "hb": float(hb),
            "peak": float(peak),
            "t": 0.0,
            "dur": max(0.05, float(dur)),
            "hide_at_end": bool(hide_at_end),
        }

    def _tick_arc(self, arc: Optional[Dict[str, Any]], dt: float) -> Tuple[Optional[Dict[str, Any]], bool]:
        """한 프레임 진행. (갱신된 arc 또는 None, 완료 여부)."""
        if not isinstance(arc, dict):
            return None, False
        arc["t"] = float(arc.get("t") or 0.0) + dt
        dur = max(0.05, float(arc.get("dur") or 0.05))
        done = float(arc["t"]) >= dur
        return arc, done

    def _arc_sample(self, arc: Dict[str, Any]) -> Tuple[float, float, float]:
        dur = max(0.05, float(arc.get("dur") or 0.05))
        u = min(1.0, float(arc.get("t") or 0.0) / dur)
        ax, ay = float(arc["ax"]), float(arc["ay"])
        bx, by = float(arc["bx"]), float(arc["by"])
        ha, hb = float(arc["ha"]), float(arc["hb"])
        peak = float(arc.get("peak") or 0.0)
        x = ax + (bx - ax) * u
        y = ay + (by - ay) * u
        h = ha + (hb - ha) * u + peak * math.sin(math.pi * u)
        return x, y, h

    def _lock_boss_airborne(self) -> None:
        peak = float(self.field.get("boss_jumpfly_height", 40.0))
        self._boss_air_lock = True
        self._boss_air_h = max(peak, float(self._boss_offset_y or 0.0))
        self._boss_offset_y = self._boss_air_h
        self._boss_anim = "jumpfly"
        self._apply_tilt(True)

    def _begin_counter_prep(self) -> None:
        """frog01 착지 → 반격 확정. 보스는 공중 고정."""
        self._lock_boss_airborne()
        self.state = ST_COUNTER_PREP
        self._phase_t = 0.0
        self._phase_dur = float(self.field.get("counter_prep_sec", 0.5))
        self._announce = "간질간질!"
        self._msg = ""
        self._freeze_player_idle_frame0()
        if self._ally_tile is not None:
            cx, cy = self._tile_center(self._ally_tile)
            self._ally_draw_xy = (cx, cy + self._tile * 0.35)
            self._ally_draw_h = 2.0
            self._ally_anim = "idle"
        self._start_counter_zoom_fx()

    def _set_player_draw_above_boss(self, on: bool) -> None:
        """반격 공중 연출 중 플레이어를 황소개구리보다 위에 그린다."""
        p = self._player_ref
        if p is None:
            return
        try:
            if on:
                if not hasattr(self, "_player_layer_saved"):
                    self._player_layer_saved = int(getattr(p, "layer", 0) or 0)
                p.layer = max(int(self._player_layer_saved), 0) + 10
            else:
                if hasattr(self, "_player_layer_saved"):
                    p.layer = int(self._player_layer_saved)
                    delattr(self, "_player_layer_saved")
        except Exception:
            pass

    def _begin_counter_ascent(self) -> None:
        ally = self._ally_tile or self._player_tile
        ax, ay = self._tile_center(ally)
        bx, by = self._boss_center_xy()
        peak_boss = float(self._boss_air_h or self.field.get("boss_jumpfly_height", 40.0))
        below = float(self.field.get("tickle_belly_height_below", 10.0))
        belly_h = max(0.0, peak_boss - below)
        dur = float(self.field.get("counter_ascent_sec", 0.45))
        jump_h = float(self.field.get("player_jump_height", 21.0))
        self.state = ST_COUNTER_ASCENT
        self._phase_t = 0.0
        self._phase_dur = dur
        self._boss_anim = "jumpfly"
        self._boss_anim_t = 0.0
        self._announce = "간질간질!"
        self._restore_counter_zoom_fx()
        self._set_player_draw_above_boss(True)
        self._start_player_arc(
            ax, ay, bx, by,
            ha=self._player_base_height,
            hb=self._player_base_height + belly_h,
            dur=dur,
            peak=jump_h,
            anim="jump",
        )
        # frog01: 플레이어 중앙 점프와 동시에 제자리 점프(밀어주는 연출)
        foot_y = ay + self._tile * 0.35
        ally_peak = float(self.field.get("ally_boost_jump_height", jump_h))
        self._ally_anim = "jump"
        self._ally_anim_t = 0.0
        self._start_ally_arc(
            ax, foot_y, ax, foot_y,
            ha=2.0,
            hb=2.0,
            dur=dur,
            peak=ally_peak,
        )

    def _begin_tickle(self) -> None:
        self.state = ST_TICKLE
        self._phase_t = 0.0
        self._phase_dur = float(self.field.get("tickle_sec", 1.0))
        self._player_jumping = False
        self._player_arc = None
        self._boss_anim = "down"
        self._boss_anim_t = 0.0
        self._boss_offset_y = float(self._boss_air_h)
        self._announce = "간질간질!"
        peak_boss = float(self._boss_air_h or self.field.get("boss_jumpfly_height", 40.0))
        below = float(self.field.get("tickle_belly_height_below", 10.0))
        belly_h = max(0.0, peak_boss - below)
        bx, by = self._boss_center_xy()
        p = self._player_ref
        if p is not None:
            try:
                p.pos[0], p.pos[1] = bx, by
                p.target = [bx, by]
                p.height = self._player_base_height + belly_h
            except Exception:
                pass
        self._set_player_draw_above_boss(True)
        self._play_player_state("tickle", duration_sec=self._phase_dur, loop=True)
        # frog01은 원래 타일에서 jump 유지
        if self._ally_tile is not None:
            cx, cy = self._tile_center(self._ally_tile)
            self._ally_draw_xy = (cx, cy + self._tile * 0.35)
            self._ally_draw_h = 2.0
        self._ally_anim = "jump"
        self._ally_arc = None

    def _begin_counter_return(self) -> None:
        ally = self._ally_tile or self._player_tile
        bx, by = self._boss_center_xy()
        tx, ty = self._tile_center(ally)
        peak_boss = float(self._boss_air_h or self.field.get("boss_jumpfly_height", 40.0))
        below = float(self.field.get("tickle_belly_height_below", 10.0))
        belly_h = max(0.0, peak_boss - below)
        dur = float(self.field.get("counter_return_sec", 0.45))
        jump_h = float(self.field.get("player_jump_height", 21.0))
        descend = float(self.field.get("boss_counter_descend_sec", 0.55))
        self.state = ST_COUNTER_RETURN
        self._phase_t = 0.0
        self._phase_dur = max(dur, descend)
        self._boss_anim = "down"
        self._boss_anim_t = 0.0
        self._set_player_draw_above_boss(True)
        self._start_player_arc(
            bx, by, tx, ty,
            ha=self._player_base_height + belly_h,
            hb=self._player_base_height,
            dur=dur,
            peak=jump_h,
            land_tile=ally,
            leaf_hit=True,
            anim="jump",
        )
        # frog01: 제자리에서 화면 밖으로 jump 퇴장
        foot_x, foot_y = self._tile_center(ally)
        foot_y = foot_y + self._tile * 0.35
        if self._ally_draw_xy is not None:
            foot_x = float(self._ally_draw_xy[0])
            foot_y = float(self._ally_draw_xy[1])
        off_y = float(self._cam_fixed[1]) + 160.0
        self._ally_anim_t = 0.0
        self._start_ally_arc(
            foot_x, foot_y, foot_x, off_y,
            ha=float(self._ally_draw_h or 2.0),
            hb=0.0,
            dur=dur,
            peak=jump_h * 0.4,
            hide_at_end=True,
        )

    def _apply_player_hit(self, *, keep_attack_state: bool = False) -> None:
        """물방울 피격. keep_attack_state=True 이면 다단 낙하를 계속하고 falldown만 재생."""
        if self._turn_hit:
            return  # 한 턴 피해 1회
        self._lives -= 1
        self._turn_hit = True
        self._drop_was_hit = True
        self._announce = "맞았다!"
        self._msg = f"목숨 {self._lives}"
        self._play_leaf_hit(self._player_tile)
        fall_dur = float(
            self.field.get("falldown_sec", self.field.get("hit_stun_sec", 2.0))
        )
        self._falldown_active = True
        self._falldown_t = 0.0
        self._falldown_dur = fall_dur
        self._play_player_state("falldown", duration_sec=fall_dur, loop=False)
        raw = list(self.field.get("falldown_frame_sec") or _cfg("falldown_frame_sec") or [])
        self._falldown_frame_ends: List[float] = []
        if raw:
            t = 0.0
            for s in raw:
                t += float(s)
                self._falldown_frame_ends.append(t)
        if keep_attack_state:
            # 다단 웨이브 계속 — 상태 유지, 후속 낙하 무적
            if self._lives <= 0:
                self._falldown_dur = min(self._falldown_dur, 0.35)
            return
        self.state = ST_HIT
        self._phase_t = 0.0
        self._phase_dur = fall_dur
        if self._lives <= 0:
            self._phase_dur = min(self._phase_dur, 0.35)

    def _on_tickle_success(self) -> None:
        # 하위 호환 — 창에서 바로 들어오면 prep부터
        self._begin_counter_prep()

    def _finish_win(self) -> None:
        self._won = True
        self._save_patch[self._win_flag] = 1
        self._save_patch["progress_frog_minigame_win"] = 1
        self.state = ST_WIN
        self._phase_t = 0.0
        self._phase_dur = float(self.field.get("result_hold_sec", 2.2))
        self._finish_hold = self._phase_dur
        self._boss_anim = "down"
        self._announce = "승리!"
        self._msg = "황소개구리를 굴복시켰다"

    def _finish_lose(self) -> None:
        self._won = False
        self.state = ST_LOSE
        self._phase_t = 0.0
        self._phase_dur = float(self.field.get("result_hold_sec", 2.2))
        self._finish_hold = self._phase_dur
        self._announce = "패배…"
        self._msg = "다시 도전해 보자"

    def _quit_to_exit(self) -> None:
        self._counter_zoom_active = False
        self._cleanup_player()
        self._should_return = True
        self.state = ST_QUIT
        self._finish_hold = 0.05
        # 종료 직전에 zoom 1.0을 먼저 쏘면 pond 화면이 잠깐 640으로 튄다.
        # 줌/출력모드 복귀는 map change 이후 해당 맵 기본값에 맡긴다.

    def _cleanup_player(self) -> None:
        p = self._player_ref
        if p is None:
            return
        self._set_player_draw_above_boss(False)
        try:
            p.height = self._player_base_height
            p.visible = self._player_visible_saved
            try:
                p.is_visible = True
            except Exception:
                pass
            p.stop_moving()
            p._hide_feet_shadow = bool(self._player_hide_shadow_saved)
        except Exception:
            pass
        try:
            if self._ev_mgr is not None:
                self._ev_mgr.remove_ui_overlay("bullfrog_exit")
        except Exception:
            pass
        # 줌 복구는 exit 이벤트/맵 전환에 맡김

    # ------------------------------------------------------------------ player move

    def _can_player_move(self) -> bool:
        # falldown 중에는 이동 불가. ST_DROP 중에는 다음 웨이브 회피를 위해 이동 허용.
        if self._falldown_active:
            return False
        return self.state in (
            ST_TITLE,
            ST_WAIT,
            ST_SHADOW,
            ST_DROP,
            ST_COUNTER_SPAWN,
            ST_COUNTER_WAIT,
            ST_COUNTER_WINDOW,
            ST_COUNTER_MISS_DESCEND,
            ST_BOSS_JUMP,  # 반격 창과 겹칠 수 있음 — 일반 공격 점프 중엔 이동 허용(회피)
            ST_SPLASH,
        ) and not self._player_jumping and self._player_land_cd <= 0.0

    def _player_jump_duration_ms(self, sec: float | None = None) -> int:
        if sec is None:
            sec = float(self.field.get("player_jump_sec", 0.33))
        return max(80, int(round(float(sec) * 1000.0)))

    def _land_bob_offsets(self) -> List[int]:
        raw = self.field.get("player_land_bob_y")
        if isinstance(raw, (list, tuple)) and raw:
            out: List[int] = []
            for v in raw:
                try:
                    out.append(int(v))
                except (TypeError, ValueError):
                    out.append(0)
            return out
        return [2, 1, -2, -1]

    def _land_bob_frame_sec(self) -> float:
        fps = max(1.0, float(self.field.get("anim_fps", 10.0)))
        return 1.0 / fps

    def _start_land_bob(self) -> None:
        """착지 직후 잎이 가라앉았다가 올라가는 Y 오프셋 시퀀스 시작."""
        if not self._land_bob_offsets():
            self._player_bob_ix = -1
            self._player_bob_t = 0.0
            return
        self._player_bob_ix = 0
        self._player_bob_t = 0.0

    def _on_player_landed(self) -> None:
        """착지 공통: 잎 hit · jump→idle · 바운스 · 쿨타임."""
        self._player_jumping = False
        self._play_leaf_hit(self._player_tile)
        self._end_player_jump_anim()
        self._start_land_bob()
        self._player_land_cd = float(self.field.get("player_land_cooldown_sec", 0.2))
        p = self._player_ref
        if p is not None:
            try:
                p.height = self._player_base_height
            except Exception:
                pass

    def _current_land_bob_y(self) -> float:
        if self._player_bob_ix < 0:
            return 0.0
        offs = self._land_bob_offsets()
        if not offs or self._player_bob_ix >= len(offs):
            return 0.0
        return float(offs[self._player_bob_ix])

    def _face_toward(self, from_tile: TileXY, to_tile: TileXY) -> None:
        """점프 방향에 맞춰 좌/우 스프라이트 선택 (엔진은 jump를 left 기준+플립)."""
        p = self._player_ref
        if p is None:
            return
        fc = self._tile_center(from_tile)
        tc = self._tile_center(to_tile)
        dx, dy = tc[0] - fc[0], tc[1] - fc[1]
        try:
            if abs(dx) >= abs(dy):
                p.direction = "right" if dx > 0 else "left"
            else:
                # 상하는 left 세트 사용 (up/down 키면 anims_r로 잘못 감)
                p.direction = "left"
        except Exception:
            pass

    def _start_player_jump_anim(self, *, duration_sec: float | None = None) -> None:
        """캐릭터 jump 애니 세트 재생 (character/<name>/jump_left/)."""
        p = self._player_ref
        if p is None:
            return
        dur = self._player_jump_duration_ms(duration_sec)
        try:
            # duration 동안 jump 유지. loop=True 로 짧은 점프에서도 프레임이 돈다.
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

    def _try_jump_to(self, dest: TileXY) -> bool:
        if dest not in self._leaf_tiles:
            return False
        if dest == self._player_tile:
            return False
        if dest not in self._neighbors4(self._player_tile):
            return False
        if self._player_jumping or self._player_land_cd > 0.0:
            return False
        # 새 점프 시 착지 바운스 중단
        self._player_bob_ix = -1
        self._player_bob_t = 0.0
        self._player_from = self._player_tile
        self._player_tile = dest
        self._player_jumping = True
        self._player_jump_t = 0.0
        self._face_toward(self._player_from, dest)
        self._start_player_jump_anim()
        return True

    def _sync_player_pos(self, dt: float) -> None:
        p = self._player_ref
        if p is None:
            return
        if self._player_land_cd > 0.0:
            self._player_land_cd = max(0.0, self._player_land_cd - dt)

        # 착지 바운스 프레임 진행 (anim_fps 간격)
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

        # 반격용 자유 포물선 점프
        if isinstance(self._player_arc, dict):
            arc, done = self._tick_arc(self._player_arc, dt)
            self._player_arc = arc
            if arc is not None:
                x, y, h = self._arc_sample(arc)
                try:
                    p.pos[0], p.pos[1] = x, y
                    p.target = [x, y]
                    p.height = h
                    p.path = []
                except Exception:
                    pass
            if done and isinstance(self._player_arc, dict):
                land = self._player_arc.get("land_tile")
                leaf_hit = bool(self._player_arc.get("leaf_hit"))
                hb = float(self._player_arc.get("hb") or self._player_base_height)
                self._player_arc = None
                self._player_jumping = False
                if isinstance(land, tuple) and len(land) == 2:
                    self._player_tile = (int(land[0]), int(land[1]))
                try:
                    p.height = hb
                except Exception:
                    pass
                if leaf_hit:
                    self._play_leaf_hit(self._player_tile)
                    self._end_player_jump_anim()
                    self._start_land_bob()
                    self._player_land_cd = float(
                        self.field.get("player_land_cooldown_sec", 0.2)
                    )
            # ally arc도 같이
            self._sync_ally_arc(dt)
            return

        self._sync_ally_arc(dt)

        jump_sec = float(self.field.get("player_jump_sec", 0.33))
        jump_h = float(self.field.get("player_jump_height", 21.0))
        if self.state in (ST_CAM_HOLD, ST_CAM_PAN):
            # 카메라 연출 중: 시작 타일 아래 대기(비가시)
            dest = self._tile_center(self._player_tile)
            x = dest[0]
            y = dest[1] + float(self._tile) * 1.5
            try:
                p.pos[0], p.pos[1] = x, y
                p.target = [x, y]
                p.height = self._player_base_height
            except Exception:
                pass
            return

        if self.state == ST_INTRO:
            # 화면 아래 → 시작 타일
            t = 0.0 if self._phase_dur <= 0 else min(1.0, self._phase_t / self._phase_dur)
            dest = self._tile_center(self._player_tile)
            start_y = dest[1] + float(self._tile) * 1.5
            x = dest[0]
            y = start_y + (dest[1] - start_y) * t
            h = jump_h * math.sin(math.pi * t)
            try:
                p.pos[0], p.pos[1] = x, y
                p.target = [x, y]
                p.height = self._player_base_height + h
            except Exception:
                pass
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
            except Exception:
                pass
            if t >= 1.0:
                self._on_player_landed()
            return

        # prep: idle 첫 프레임 유지
        if self.state == ST_COUNTER_PREP:
            self._freeze_player_idle_frame0()

        # 반격 공중 연출 중에는 타일 스냅하지 않음
        if self.state in (ST_COUNTER_ASCENT, ST_TICKLE, ST_COUNTER_RETURN):
            return

        # 정지(+ 착지 바운스 Y)
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

    def _sync_ally_arc(self, dt: float) -> None:
        if not isinstance(self._ally_arc, dict):
            return
        arc, done = self._tick_arc(self._ally_arc, dt)
        self._ally_arc = arc
        if arc is not None:
            x, y, h = self._arc_sample(arc)
            self._ally_draw_xy = (x, y)
            self._ally_draw_h = h
            self._ally_anim = "jump"
        if done:
            hide = bool((arc or {}).get("hide_at_end")) if arc else False
            self._ally_arc = None
            if hide:
                self._ally_visible = False
                self._ally_draw_xy = None
                self._ally_draw_h = 0.0
                self._ally_anim = "idle"

    def _tick_falldown(self, dt: float) -> None:
        """다단 낙하 중 falldown 애니·프레임 진행. ST_HIT는 기존 phase 경로도 사용."""
        if not self._falldown_active:
            return
        if self.state == ST_HIT:
            # ST_HIT는 phase_t 기준 — falldown_t 동기화만
            self._falldown_t = float(self._phase_t)
            if self._falldown_t >= self._falldown_dur:
                self._falldown_active = False
            else:
                self._apply_falldown_frame(self._falldown_t)
            return
        self._falldown_t += dt
        if self._falldown_t >= self._falldown_dur:
            self._falldown_active = False
            self._end_player_jump_anim()
            return
        self._apply_falldown_frame(self._falldown_t)

    def _apply_falldown_frame(self, t: float) -> None:
        ends = getattr(self, "_falldown_frame_ends", [])
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
            ao = getattr(p, "_anim_override", None)
            if ao is not None:
                p.frame_idx = idx
                anims = p.anims_l if p.direction == "left" else p.anims_r
                frames = anims.get("falldown") or anims.get("idle")
                if frames and idx < len(frames):
                    p.image = frames[idx]
        except Exception:
            pass

    # ------------------------------------------------------------------ tick

    def tick(self, dt_sec: float, player, now_ms: int) -> None:
        if self.state == ST_QUIT:
            self._finish_hold = max(0.0, self._finish_hold - dt_sec)
            return

        dt = max(0.0, float(dt_sec))
        self._phase_t += dt
        self._boss_anim_t += dt
        self._ally_anim_t += dt
        self._tick_leaf_anims(dt)
        self._tick_waves(dt)
        self._tick_splashes(dt)
        self._tick_falldown(dt)

        self._sync_player_pos(dt)

        # 방향키 폴링 (host.on_primary_key 가 main에서 안 불릴 수 있어 자체 처리)
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
                    # 키 반복 방지: 점프 중이 아닐 때만 1회
                    if not getattr(self, "_key_held", False):
                        self._try_jump_to(dest)
                        self._key_held = True
                else:
                    self._key_held = False
            except Exception:
                pass

        # 보스 점프 높이 / 반격 공중 고정
        if self._boss_air_lock or self.state in (
            ST_COUNTER_PREP,
            ST_COUNTER_ASCENT,
            ST_TICKLE,
        ):
            self._boss_offset_y = float(self._boss_air_h)
            if self.state == ST_TICKLE:
                self._boss_anim = "down"
            elif self.state in (ST_COUNTER_PREP, ST_COUNTER_ASCENT):
                # 반격 확정~상승: jumpfly 유지 (down은 tickle부터)
                self._boss_anim = "jumpfly"
            self.field_tilt_enabled = True
            self.field_tilt_target = float(self.field.get("boss_jump_tilt_factor", 0.55))
        elif self.state == ST_COUNTER_RETURN:
            # down 세트로 지면까지 하강
            descend = max(0.05, float(self.field.get("boss_counter_descend_sec", 0.55)))
            u = min(1.0, self._phase_t / descend)
            peak = float(self._boss_air_h or self.field.get("boss_jumpfly_height", 40.0))
            self._boss_offset_y = peak * (1.0 - u)
            self._boss_anim = "down"
            if u >= 1.0:
                self._boss_air_lock = False
                self._boss_air_h = 0.0
            self.field_tilt_enabled = True
            self.field_tilt_target = float(self.field.get("boss_jump_tilt_factor", 0.55))
        elif self.state == ST_COUNTER_WINDOW:
            # 반격 가능 시간 전체: jump1 도약 후 jumpfly 체공 유지 (창 중 하강/down 금지)
            peak = float(self.field.get("boss_jumpfly_height", 40.0))
            j1 = max(0.001, float(self.field.get("boss_jump1_sec", 0.5)))
            self.field_tilt_enabled = True
            self.field_tilt_target = float(self.field.get("boss_jump_tilt_factor", 0.55))
            if self._phase_t < j1:
                u = max(0.0, min(1.0, self._phase_t / j1))
                self._boss_anim = "jump1"
                self._boss_offset_y = peak * math.sin(u * math.pi * 0.5)
            else:
                self._boss_anim = "jumpfly"
                self._boss_offset_y = peak
        elif self.state == ST_COUNTER_MISS_DESCEND:
            # 반격 실패: jumpfly 체공 → jump3로 수면까지 (일반 공격 jump3와 동일 곡선)
            peak = float(self._boss_air_h or self.field.get("boss_jumpfly_height", 40.0))
            dur = max(0.05, float(self._phase_dur or self.field.get("boss_jump3_sec", 0.5)))
            u = max(0.0, min(1.0, self._phase_t / dur))
            self._boss_anim = "jump3"
            self._boss_offset_y = peak * math.cos(u * math.pi * 0.5)
            self.field_tilt_enabled = True
            self.field_tilt_target = float(self.field.get("boss_jump_tilt_factor", 0.55))
        elif self.state == ST_BOSS_JUMP:
            profile = self._boss_profile(counter=False)
            peak = float(self.field.get("boss_jump_height", 28.0))
            tleft = self._phase_t
            self._boss_offset_y = 0.0
            self._boss_anim = profile[-1][0]
            self.field_tilt_enabled = True
            for anim_name, seg_dur in profile:
                seg_dur = max(0.001, float(seg_dur))
                if tleft <= seg_dur:
                    u = max(0.0, min(1.0, tleft / seg_dur))
                    self._boss_anim = anim_name
                    if anim_name in ("jump1", "jump2", "jumpfly"):
                        self._boss_offset_y = peak * math.sin(u * math.pi * 0.5)
                        if anim_name in ("jump2", "jumpfly"):
                            self._boss_offset_y = peak
                        self.field_tilt_target = float(self.field.get("boss_jump_tilt_factor", 0.55))
                    else:  # jump3
                        self._boss_offset_y = peak * math.cos(u * math.pi * 0.5)
                        self.field_tilt_target = float(self.field.get("boss_jump_tilt_factor", 0.55))
                    break
                tleft -= seg_dur
        elif self.state == ST_SINK:
            self._boss_offset_y = 0.0
            self._boss_anim = "sink"
            self.field_tilt_enabled = False
            self.field_tilt_target = 1.0
        elif self.state == ST_SUBMERGED:
            self._boss_offset_y = 0.0
            self.field_tilt_enabled = False
            self.field_tilt_target = 1.0
        elif self.state == ST_RISE:
            self._boss_offset_y = 0.0
            self._boss_anim = "emerge"
            self.field_tilt_enabled = False
            self.field_tilt_target = 1.0
        else:
            self._boss_offset_y = 0.0
            self.field_tilt_enabled = False
            self.field_tilt_target = 1.0

        if self.state == ST_CAM_HOLD:
            if self._phase_t >= self._phase_dur:
                self._begin_cam_pan()
            return

        if self.state == ST_CAM_PAN:
            if self._phase_t >= self._phase_dur:
                self._begin_player_enter()
            return

        if self.state == ST_INTRO:
            if self._phase_t >= self._phase_dur:
                self._on_player_landed()
                self.state = ST_TITLE
                self._phase_t = 0.0
                self._phase_dur = float(self.field.get("intro_title_sec", 1.5))
                self._announce = str(
                    self.field.get("intro_title_text") or "게임 시작!"
                )
                self._msg = ""
            return

        if self.state == ST_TITLE:
            if self._phase_t >= self._phase_dur:
                self.state = ST_WAIT
                self._phase_t = 0.0
                self._phase_dur = float(self.field.get("intro_cooldown_sec", 2.0))
                self._announce = ""
                if self._combat_enabled:
                    self._msg = "황소개구리를 조심해!"
                else:
                    self._msg = "연꽃잎을 눌러 점프 (←→↑↓)"
            return

        if self.state == ST_WAIT:
            # 1단계(잎만): 전투 OFF — 점프 연습만
            if not self._combat_enabled:
                return
            if self._phase_t >= self._phase_dur:
                need = self._dodges_needed_for_counter()
                if self._attacks_in_set >= need:
                    self._start_counter_phase()
                else:
                    self._start_boss_attack()
            return

        if self.state == ST_BOSS_JUMP:
            if self._phase_t >= self._phase_dur:
                self._begin_attack_splash()
            return

        if self.state == ST_COUNTER_MISS_DESCEND:
            if self._phase_t >= self._phase_dur:
                self._boss_air_h = 0.0
                self._begin_landing_splash(all_tiles=True)
            return

        if self.state == ST_SPLASH:
            fade_in, fade_hold, _fade_out = self._splash_fade_timings()
            # 페이드인 끝난 뒤(홀드 시작) 웨이브 플랜을 미리 짠다.
            # 실제 그림자 표시는 emerge 뒤 ST_SHADOW에서 1차부터.
            if (
                self._splash_fade_active
                and not self._splash_shadows_ready
                and self._phase_t >= fade_in
            ):
                self._plan_or_set_attack_tiles()
                self._splash_shadows_ready = True
                self._msg = ""
            if self._phase_t >= self._phase_dur:
                self._splash_fade_active = False
                if not self._splash_shadows_ready:
                    self._plan_or_set_attack_tiles()
                    self._splash_shadows_ready = True
                # 일반 공격·반격 실패 모두: emerge → 다단 그림자 → 다단 물방울
                self.state = ST_RISE
                self._phase_t = 0.0
                self._phase_dur = float(self.field.get("rise_sec", 2.0))
                self._boss_anim = "emerge"
                self._boss_anim_t = 0.0
                self._announce = ""
                self._msg = ""
            return

        if self.state == ST_SHADOW or self.state == ST_DROP:
            # 병렬 웨이브: 그림자·낙하가 설정에 따라 겹침
            if self._wave_actors:
                self._tick_parallel_waves(dt)
            return

        if self.state == ST_HIT:
            # 프레임별 타이밍으로 falldown frame_idx 직접 제어
            self._apply_falldown_frame(self._phase_t)
            if self._phase_t >= self._phase_dur:
                self._falldown_active = False
                if self._lives <= 0:
                    self._finish_lose()
                else:
                    # 피격은 회피 카운트에 포함하지 않음. 반격실패 패널티면 세트 리셋 유지.
                    self._shadow_tiles = set()
                    self._wave_actors = []
                    if self._counter_fail_all_drop:
                        self._reset_set_progress()
                        self._msg = "세트 다시! 턴부터"
                    else:
                        need = self._dodges_needed_for_counter()
                        self._msg = f"턴 {self._attacks_in_set}/{need}"
                    self._end_player_jump_anim()
                    self.state = ST_WAIT
                    self._phase_t = 0.0
                    self._phase_dur = float(self.field.get("attack_interval_sec", 10.0))
                    self._announce = ""
            return

        if self.state == ST_COUNTER_SPAWN:
            if self._phase_t >= self._phase_dur:
                self._ally_tile = self._pick_counter_ally_tile()
                self._ally_visible = True
                self._ally_anim = "idle"
                self._ally_draw_xy = None
                self._ally_draw_h = 2.0
                self.state = ST_COUNTER_WAIT
                self._phase_t = 0.0
                self._phase_dur = float(self.field.get("counter_ready_delay_sec", 5.0))
                self._announce = "개구리가 도와줘!"
                self._msg = "5초 뒤 높이 떴을 때 개구리를 밟아!"
            return

        if self.state == ST_COUNTER_WAIT:
            if self._phase_t >= self._phase_dur:
                # 보스 특수 점프 + 반격 창
                self.state = ST_COUNTER_WINDOW
                self._phase_t = 0.0
                self._phase_dur = float(self.field.get("counter_window_sec", 6.0))
                self._boss_anim = "jump1"
                self._boss_anim_t = 0.0
                self._boss_air_lock = False
                self._apply_tilt(True)
                self._announce = "지금!"
            return

        if self.state == ST_COUNTER_WINDOW:
            # 창 동안 아군 타일 착지 → 반격 확정(prep). 보스는 공중 고정.
            if (
                self._ally_tile is not None
                and self._player_tile == self._ally_tile
                and not self._player_jumping
            ):
                self._begin_counter_prep()
                return
            if self._phase_t >= self._phase_dur:
                # 실패 — jump3 하강 → 착수(페이드) → emerge → 전타일 짧은 그림자 → 물방울
                self._begin_counter_miss_descend()
            return

        if self.state == ST_COUNTER_PREP:
            if self._phase_t >= self._phase_dur:
                self._begin_counter_ascent()
            return

        if self.state == ST_COUNTER_ASCENT:
            if self._phase_t >= self._phase_dur and not self._player_jumping:
                self._begin_tickle()
            return

        if self.state == ST_TICKLE:
            if self._phase_t >= self._phase_dur:
                self._begin_counter_return()
            return

        if self.state == ST_COUNTER_RETURN:
            if self._phase_t >= self._phase_dur and not self._player_jumping:
                self._set_player_draw_above_boss(False)
                self._boss_air_lock = False
                self._boss_air_h = 0.0
                self._boss_offset_y = 0.0
                self._ally_visible = False
                self._ally_tile = None
                self._spawn_splash_fx("counter")  # 반격 후 착수 (현재 splash01)
                self._submerged_mode = "next_set"
                self.state = ST_SINK
                self._phase_t = 0.0
                self._phase_dur = float(self.field.get("sink_sec", 1.5))
                self._boss_anim = "sink"
                self._boss_anim_t = 0.0
                self._apply_tilt(False)
                self._announce = ""
                self._msg = "풍덩…"
            return

        if self.state == ST_SINK:
            if self._phase_t >= self._phase_dur:
                self.state = ST_SUBMERGED
                self._phase_t = 0.0
                self._phase_dur = float(self.field.get("submerged_sec", 2.0))
                self._boss_anim = "sink"
                self._boss_anim_t = 0.0
            return

        if self.state == ST_SUBMERGED:
            if self._phase_t >= self._phase_dur:
                if self._submerged_mode == "next_set":
                    self._set_ix += 1
                    need = int(self.field.get("sets_to_win", 3))
                    if self._set_ix >= need:
                        self._finish_win()
                    else:
                        self.state = ST_RISE
                        self._phase_t = 0.0
                        self._phase_dur = float(self.field.get("rise_sec", 2.0))
                        self._boss_anim = "emerge"
                        self._boss_anim_t = 0.0
                        self._attacks_in_set = 0
                        self._announce = f"세트 {self._set_ix + 1}!"
                        self._msg = "더 빨라진다!"
                else:
                    self.state = ST_RISE
                    self._phase_t = 0.0
                    self._phase_dur = float(self.field.get("rise_sec", 2.0))
                    self._boss_anim = "emerge"
                    self._boss_anim_t = 0.0
                    self._announce = ""
                    self._msg = ""
            return

        if self.state == ST_RISE:
            if self._phase_t >= self._phase_dur:
                self._boss_anim = "idle"
                self._boss_anim_t = 0.0
                self._announce = ""
                if self._submerged_mode == "resume_attack":
                    self._begin_shadow_phase()
                else:
                    self.state = ST_WAIT
                    self._phase_t = 0.0
                    self._phase_dur = float(self.field.get("attack_interval_sec", 10.0))
            return

        if self.state in (ST_WIN, ST_LOSE):
            self._finish_hold = max(0.0, self._finish_hold - dt)
            if self._finish_hold <= 0.0:
                self._quit_to_exit()
            return

    # ------------------------------------------------------------------ input

    def on_pointer_down(self, screen_xy, world_xy, now_ms: int) -> bool:
        if self.state in (ST_WIN, ST_LOSE):
            self._finish_hold = 0.0
            self._quit_to_exit()
            return True
        if self.state == ST_QUIT or self.state in (ST_CAM_HOLD, ST_CAM_PAN, ST_INTRO):
            return True
        if not self._can_player_move():
            return True

        wx = wy = None
        if isinstance(world_xy, (list, tuple)) and len(world_xy) >= 2:
            wx, wy = float(world_xy[0]), float(world_xy[1])
        elif isinstance(screen_xy, (list, tuple)) and len(screen_xy) >= 2:
            # 월드 변환 실패 시 화면→타일 근사 (캠 고정·줌 가정)
            sx, sy = float(screen_xy[0]), float(screen_xy[1])
            sw = float(CONFIG.get("WIDTH", 320) or 320)
            sh = float(CONFIG.get("HEIGHT", 240) or 240)
            z = sw / 320.0
            wx = self._cam_fixed[0] + (sx - sw * 0.5) / z
            wy = self._cam_fixed[1] + (sy - sh * 0.5) / z

        if wx is None:
            return True
        dest = self._tile_at_world(wx, wy)
        if dest is None:
            return True
        self._try_jump_to(dest)
        return True

    def on_pointer_up(self, now_ms: int) -> bool:
        return self.state != ST_QUIT

    def on_primary_key(self, key) -> bool:
        """방향키로도 한 칸 이동 (데모 편의)."""
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
            self._try_jump_to(dest)
        return True

    # ------------------------------------------------------------------ draw
    # 레이어: 맵 → draw_world_under(wave → 연꽃잎) → ysort(플레이어·개구리·황소·물방울)
    #        → draw_world(거의 비움) → draw_screen(HUD)

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
        h=0.0,
        anchor="center",
        sprite_tilt: float = 1.0,
        sprite_perspective_q=None,
        y_transform=None,
        x_offset_fn=None,
    ):
        if img is None:
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
        sy = sy - float(h) * z
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
        if anchor == "feet":
            ox = int(sx - sw * 0.5)
            oy = int(sy - sh)
        else:
            ox = int(sx - sw * 0.5)
            oy = int(sy - sh * 0.5)
        surf.blit(scaled, (ox, oy))

    def draw_world_under(self, ctx: FieldDrawContext) -> None:
        """배경 위 · 캐릭터 아래 — wave01 → 연꽃잎(+그림자 예고)."""
        if ctx is None or ctx.surf is None or self.state == ST_QUIT:
            return
        surf = ctx.surf
        z = float(ctx.z or 1.0)
        cam_x = float(ctx.cam_draw_x)
        cam_y = float(ctx.cam_draw_y)
        spq = getattr(ctx, "sprite_perspective_q", None)
        y_tr = getattr(ctx, "y_transform", None)
        x_off = getattr(ctx, "x_offset_fn", None)
        # 연꽃잎 = 바닥에 누운 타일 (sprite_tilt 0)
        leaf_tilt = float(self.field.get("lotus_sprite_tilt", 0.0))

        # 1) wave FX (잎보다 아래)
        if self._wave_frames and self._waves:
            for w in self._waves:
                fr = self._anim_frame(self._wave_frames, float(w.get("t") or 0.0))
                self._blit_world_centered(
                    surf,
                    fr,
                    float(w["wx"]),
                    float(w["wy"]),
                    cam_x,
                    cam_y,
                    z,
                    anchor="center",
                    sprite_tilt=leaf_tilt,
                    sprite_perspective_q=spq,
                    y_transform=y_tr,
                    x_offset_fn=x_off,
                )

        # 1b) splash FX (착수 물튀김 — 잎 아래·위 모두 보이게 잎 전에)
        if self._splashes:
            for s in self._splashes:
                frames = s.get("frames") or []
                if not frames:
                    continue
                t = float(s.get("t") or 0.0)
                fps = max(1.0, float(s.get("fps") or self.field.get("splash_fx_fps", 4.0)))
                ix = min(len(frames) - 1, int(t * fps))
                fr = list(frames)[ix]
                self._blit_world_centered(
                    surf,
                    fr,
                    float(s["wx"]),
                    float(s["wy"]),
                    cam_x,
                    cam_y,
                    z,
                    anchor="center",
                    sprite_tilt=leaf_tilt,
                    sprite_perspective_q=spq,
                    y_transform=y_tr,
                    x_offset_fn=x_off,
                )

        # 2) 연꽃잎 (누운 타일) + 물방울 그림자 힌트(페이드)
        shadow_alphas = self._shadow_alpha_by_tile()
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
                anchor="center",
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

        # 반격 타일 강조 링 (잎 위·캐릭터 아래)
        if (
            self._ally_visible
            and self._ally_tile is not None
            and self.state in (ST_COUNTER_SPAWN, ST_COUNTER_WAIT, ST_COUNTER_WINDOW)
        ):
            cx, cy = self._tile_center(self._ally_tile)
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
            ring = pygame.Surface(
                (int(self._tile * z), int(self._tile * z * 0.5)), pygame.SRCALPHA
            )
            pygame.draw.ellipse(ring, (255, 230, 80, 140), ring.get_rect(), 2)
            surf.blit(
                ring,
                (int(sx - ring.get_width() * 0.5), int(sy - ring.get_height() * 0.2)),
            )

    def collect_ysort_sprites(self):
        """플레이어와 ysort — 황소개구리 / 아군 개구리 / 떨어지는 물방울."""
        if self.state == ST_QUIT:
            return []
        out: List[_BullfrogYSortSprite] = []
        tile = self._tile

        # 황소개구리 — 발 Y = 보스 영역 하단
        # 착수 splash 중에는 보스 숨김 (일반 공격·반격 실패 공통)
        hide_boss = self.state == ST_SUBMERGED or self.state == ST_SPLASH
        if not hide_boss:
            bfr = self._boss_anim_frame()
            target_w = max(1, self._boss_w * tile)
            target_h = max(1, int(self._boss_h * tile * 1))
            try:
                boss_img = pygame.transform.scale(bfr, (target_w, target_h))
            except Exception:
                boss_img = bfr
            bx = self._ox + (self._boss_col + self._boss_w * 0.5) * tile
            by = self._oy + (self._boss_row + self._boss_h) * tile  # 발 = 영역 하단
            out.append(
                _BullfrogYSortSprite(
                    bx, by, boss_img, height=float(self._boss_offset_y), anchor="feet"
                )
            )

        # 아군 개구리
        if self._ally_visible and self._ally_tile is not None:
            st = self._ally_anim if self._ally_anim in self._ally_frames else "idle"
            if self.state in (ST_COUNTER_ASCENT, ST_COUNTER_RETURN, ST_TICKLE):
                st = "jump" if "jump" in self._ally_frames else st
            fr = self._anim_frame(
                self._ally_frames.get(st) or self._ally_frames.get("idle") or [],
                self._ally_anim_t,
            )
            if self._ally_draw_xy is not None:
                cx, cy = float(self._ally_draw_xy[0]), float(self._ally_draw_xy[1])
                ah = float(self._ally_draw_h)
            else:
                cx, cy = self._tile_center(self._ally_tile)
                cy = cy + tile * 0.35
                ah = 2.0
            out.append(_BullfrogYSortSprite(cx, cy, fr, height=ah, anchor="feet"))

        # 물방울 — 병렬 웨이브마다 독립 drop_t 로 낙하/착지 연출
        fall = float(self.field.get("drop_fall_sec", 0.42))
        drop_start_h = float(self.field.get("drop_start_height", 200.0))
        drop_fps = float(self.field.get("drop_anim_fps", 0.0))
        if drop_fps <= 0:
            drop_fps = float(self.field.get("anim_fps", 10.0))
        impact_sec = float(self.field.get("drop_impact_sec", 0.5))
        if self.state in (ST_SHADOW, ST_DROP) and self._wave_actors:
            for w in self._wave_actors:
                if str(w.get("phase") or "") != "drop":
                    continue
                drop_t = float(w.get("t") or 0.0)
                for tile_xy in set(w.get("tiles") or ()):
                    cx, cy = self._tile_center(tile_xy)
                    if drop_t < fall:
                        u = 0.0 if fall <= 0 else min(1.0, drop_t / fall)
                        h = drop_start_h * (1.0 - u)
                        n = len(self._drop_fall) or 1
                        ix = min(n - 1, int(drop_t * drop_fps))
                        fr = self._drop_fall[ix]
                        out.append(
                            _BullfrogYSortSprite(cx, cy, fr, height=h, anchor="feet")
                        )
                    else:
                        impact_t = drop_t - fall
                        n = len(self._drop_impact) or 1
                        if impact_sec <= 0 or n <= 1:
                            fr = self._drop_impact[n - 1]
                        else:
                            u = min(1.0, max(0.0, impact_t / impact_sec))
                            ix = min(n - 1, int(u * n) if u < 1.0 else n - 1)
                            fr = self._drop_impact[ix]
                        out.append(
                            _BullfrogYSortSprite(cx, cy, fr, height=0.0, anchor="center")
                        )
        return out

    def draw_world(self, ctx: FieldDrawContext) -> None:
        """ysort 이후 월드 오버레이 — 현재는 비움 (잎/보스/물방울은 under·ysort)."""
        return

    def draw_screen(self, ctx: FieldDrawContext) -> None:
        if ctx is None or ctx.surf is None or self.state == ST_QUIT:
            return
        surf = ctx.surf
        font_fn = ctx.font_fn
        hud_px = int(get_activity_ui("bullfrog", "hud_px_320", 11) or 11)
        ann_px = int(get_activity_ui("bullfrog", "announce_px_320", 16) or 16)
        res_px = int(get_activity_ui("bullfrog", "result_px_320", 22) or 22)
        title_px = int(get_activity_ui("bullfrog", "title_px_320", 32) or 32)

        try:
            font = font_fn(_scale_from_320(hud_px))
            font_a = font_fn(_scale_from_320(ann_px))
            font_r = font_fn(_scale_from_320(res_px))
            font_t = font_fn(_scale_from_320(title_px))
        except Exception:
            font = pygame.font.Font(None, 16)
            font_a = pygame.font.Font(None, 22)
            font_r = pygame.font.Font(None, 28)
            font_t = pygame.font.Font(None, 40)

        # HUD: 세트 / 턴 / 목숨 (카메라 인트로·타이틀 중에는 숨김)
        if self.state not in (ST_TITLE, ST_CAM_HOLD, ST_CAM_PAN):
            need = int(self.field.get("sets_to_win", 3))
            dodge_need = self._dodges_needed_for_counter()
            hud = (
                f"세트 {self._set_ix}/{need}   "
                f"턴 {self._attacks_in_set}/{dodge_need}   "
                f"목숨 {'♥' * max(0, self._lives)}"
            )
            try:
                t = font.render(hud, True, (255, 255, 240))
                surf.blit(t, (8, 6))
            except Exception:
                pass

            if self._msg:
                try:
                    t = font.render(str(self._msg), True, (220, 240, 255))
                    surf.blit(t, (8, 6 + t.get_height() + 2))
                except Exception:
                    pass

        if self.state == ST_TITLE and self._announce:
            # 로고 타이틀: 반투명 띠 + 큰 글자
            try:
                band_h = max(48, surf.get_height() // 4)
                band = pygame.Surface((surf.get_width(), band_h), pygame.SRCALPHA)
                band.fill((0, 20, 10, 160))
                by = (surf.get_height() - band_h) // 2
                surf.blit(band, (0, by))
                col = (255, 255, 140)
                t = font_t.render(str(self._announce), True, col)
                surf.blit(t, t.get_rect(center=(surf.get_width() // 2, surf.get_height() // 2)))
            except Exception:
                pass
        elif self._announce:
            try:
                col = (255, 255, 120) if self.state != ST_LOSE else (255, 160, 160)
                if self.state == ST_WIN:
                    col = (120, 255, 160)
                    t = font_r.render(str(self._announce), True, col)
                else:
                    t = font_a.render(str(self._announce), True, col)
                surf.blit(t, t.get_rect(center=(surf.get_width() // 2, surf.get_height() // 5)))
            except Exception:
                pass

        # 조작 힌트
        if self.state in (ST_TITLE, ST_WAIT, ST_SHADOW, ST_COUNTER_WAIT, ST_COUNTER_WINDOW):
            try:
                tip = font.render("연꽃잎을 눌러 점프 (←→↑↓)", True, (200, 220, 200))
                surf.blit(tip, tip.get_rect(midbottom=(surf.get_width() // 2, surf.get_height() - 6)))
            except Exception:
                pass

        # 공격 착수 라이트블루 페이드 (물방울에 가려지는 연출)
        fade_a = self._splash_fade_alpha()
        if fade_a > 0:
            try:
                col = self.field.get("splash_fade_color") or _cfg("splash_fade_color") or [160, 210, 255]
                r, g, b = int(col[0]), int(col[1]), int(col[2])
                overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
                overlay.fill((r, g, b, fade_a))
                surf.blit(overlay, (0, 0))
            except Exception:
                pass





















"""
activities.baseball — 야구장 맵 필드 타격 미니게임 (어린이 홈런 대결).

[규칙]
  - 기본 타석 수(swings, 보통 5). 플레이 스타일에 따라 승부 방식이 갈림.
  - 1단계: 부채꼴 방향 게이지 — 화살표=타구 방향(±소폭 변동). fan_half_deg_auto 시 마스크 파울라인에 맞춤.
  - 2단계: 가로 파워 게이지 — 가운데=강타. 1/3·2/3 함정=빗맞음(머리 뒤). 파울=착지 마스크만.
  - 타구 후: 공은 포물선(높이), 그림자는 지면 직선 → 입체감.
  - 타격 전 field tilt 압축 → 타격 순간 해제 (main.py 가 field_tilt_target 읽음).

[연동]
  events.json DEV_CMD: start_baseball / stop_baseball
  data.py BASEBALL_DEFAULTS + world_data baseball
  에셋: assets/minigames/baseball/ (없으면 도형 폴백)

[모드 — 메뉴]
  혼자서 하기
    · NPC와 하기(npc_vs / npc_alt) — 플레이어↔NPC 번갈아 타격, 비거리 승점 + 합계비거리 보너스
    · 기록 갱신하기(record_1p / solo_record) — 5타 합산 → HIGH SCORE
  둘이서 하기
    · 번갈아 하기(record_2p / duo_alt) — 1P↔2P 한 타씩 번갈아, 승점 대결
    · 모아서 하기(record_2p / duo_batch) — 각자 횟수만큼 전부 친 뒤 HR+합계비거리 승부
  story/demo — 이벤트·데모용 (events.json mode 파라미터)
"""

from __future__ import annotations

import math
import os
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

import pygame

# Logo 폰트 캐시
_LOGO_FONT_CACHE: Dict[int, pygame.font.Font] = {}

def _get_logo_font(size: int) -> pygame.font.Font:
    """로고 슬롯(UI_FONT_PROFILES.logo) 폰트 — 에디터 FONT 설정 반영."""
    try:
        size_i = int(size)
    except Exception:
        size_i = 32
    size_i = max(16, min(128, size_i))
    key = size_i
    if key in _LOGO_FONT_CACHE:
        return _LOGO_FONT_CACHE[key]
    try:
        from engine import resolve_font_profile

        f = resolve_font_profile("logo", size_px=size_i)
        _LOGO_FONT_CACHE[key] = f
        return f
    except Exception:
        pass
    try:
        f = pygame.font.SysFont("malgungothic", size_i)
    except Exception:
        f = pygame.font.SysFont("arial", size_i)
    _LOGO_FONT_CACHE[key] = f
    return f

from activities.baseball_zones import (
    classify_mask_landing,
    clamp_to_fielder_reachable,
    collect_scoreboard_objects,
    collect_zone_objects,
    draw_zone_ellipse_on_surface,
    estimate_fan_half_deg_from_mask,
    is_scoreboard_object,
    merge_field_config,
    resolve_flight_landing,
    resolve_landing_zone,
    scale_mask_to_background,
    scoreboard_screen_size,
    scoreboard_style_from_object,
    zone_footprint_rect,
    zone_uses_ellipse_fallback,
    _last_infield_before_fence,
)
from render_align import blit_topleft_bottom_center
from data import BASEBALL_DEFAULTS, CONFIG
from field_runtime import scale_ui_text_px

from .base import BaseFieldActivity, FieldDrawContext
from .fishing import _world_to_screen

# --- 상태 ---
ST_MENU = "menu"
ST_MENU_SOLO = "menu_solo"  # 혼자서 하기 — NPC / 기록 갱신
ST_MENU_DUO = "menu_duo"  # 둘이서 하기 — 번갈아 / 모아서
ST_RECORDS = "records"
ST_DIFFICULTY = "difficulty"
ST_PICK_P2 = "pick_p2"
ST_PICK_CHAR = "pick_char"
ST_BAT_DIR = "bat_dir"
ST_BAT_PWR = "bat_pwr"
ST_PWR_CONFIRM = "pwr_confirm"
ST_SWING_PAUSE = "swing_pause"
ST_POWER_SWING_PAUSE = "power_swing_pause"
ST_SWING = "swing"
ST_FLIGHT = "flight"
ST_TURN_WAIT = "turn_wait"
ST_ANNOUNCE = "announce"
ST_FIELD_INTRO = "field_intro"
ST_NPC_SHOW = "npc_show"
ST_MATCH_END = "match_end"
ST_DEMO_RESULT = "demo_result"
ST_REPLAY_ASK = "replay_ask"
ST_LEADERBOARD = "leaderboard"
ST_QUIT = "quit"

# 메뉴·캐릭터 선택 등 UI 오버레이 상태 (필드 플레이 아님)
_MENU_OVERLAY_STATES = (
    ST_MENU,
    ST_MENU_SOLO,
    ST_MENU_DUO,
    ST_DIFFICULTY,
    ST_PICK_CHAR,
    ST_PICK_P2,
    ST_RECORDS,
    ST_LEADERBOARD,
    ST_QUIT,
)

MODE_STORY = "story"
MODE_RECORD_1P = "record_1p"
MODE_RECORD_2P = "record_2p"
MODE_NPC_VS = "npc_vs"  # 1P vs NPC (번갈아 승점)
MODE_DEMO = "demo"

# 플레이 스타일 — 같은 mode 안에서도 승부 규칙을 나눔
PLAY_SOLO_RECORD = "solo_record"  # 기록 갱신 (기존 1P)
PLAY_NPC_ALT = "npc_alt"  # NPC와 번갈아
PLAY_DUO_ALT = "duo_alt"  # 2P 번갈아 타격·승점
PLAY_DUO_BATCH = "duo_batch"  # 2P 모아서 (기존 각자 전부 친 뒤 비교)

# 캐릭터 선택 그리드 — NPC 랜덤 슬롯
CHAR_PICK_RANDOM = "?"

# NPC AI 비거리 밴드 (0~100 스케일 → max_carry 비율)
# a:0~20  b:21~40  c:41~60  d:61~80  e:81~100
_NPC_BAND_KEYS = ("foul", "a", "b", "c", "d", "e")
_NPC_BAND_FRAC = {
    "a": (0.00, 0.20),
    "b": (0.21, 0.40),
    "c": (0.41, 0.60),
    "d": (0.61, 0.80),
    "e": (0.81, 1.00),
}

BASEBALL_DIFFICULTY_OPTIONS = [
    ("easy", "짱짱(초급)"),
    ("normal", "푸들(중급)"),
    ("hard", "아마(고급)"),
]
BASEBALL_DIFFICULTY_DEFAULT = "easy"


def _cfg(key: str, default=None):
    if key in BASEBALL_DEFAULTS:
        return BASEBALL_DEFAULTS[key]
    try:
        return CONFIG.get(key, default)
    except Exception:
        return default


def _field_val(field: dict, key: str, default=None):
    if isinstance(field, dict):
        v = field.get(key)
        if v is not None:
            return v
    if default is not None:
        return default
    return _cfg(key)


def _field_num(field: dict, key: str, default=None) -> float:
    try:
        return float(_field_val(field, key, default))
    except (TypeError, ValueError):
        return float(default if default is not None else _cfg(key))


def _field_cfg(map_id: str, world_data=None) -> dict:
    return merge_field_config(map_id, world_data)


def _mask_path_for_field(map_id: str, field: dict) -> str:
    mask_name = str(field.get("mask_img") or f"{(map_id or '').strip()}_mask.png").strip()
    return os.path.join("assets", "images", "bg", mask_name)


def _total_distance_meters(distances: List[float], px_per_meter: float) -> float:
    """유효 타구(px) 중 상위 3개를 미터로 환산해 합산."""
    ppm = max(0.1, float(px_per_meter))
    valid_dists = [float(d) for d in distances if float(d) > 0.0]
    # 내림차순으로 정렬한 뒤 상위 3개만 사용
    valid_dists.sort(reverse=True)
    top3_dists = valid_dists[:3]
    return float(sum(d / ppm for d in top3_dists))


_SWING_ORDINAL_KO = ("첫", "두", "세", "네", "다섯")

# (문구, 자동 표시 초, 탭으로 넘김 여부)
AnnounceStep = Tuple[str, float, bool]


def _ann_step(text: str, dur: float = 1.0, *, tap: bool = False) -> AnnounceStep:
    return (str(text), float(dur), bool(tap))

_BB_OVERLAY_IDLE_FPS = 6.0
_BB_OVERLAY_SWING_FPS = 12.0  # 기본 8fps 대비 1.5배
_BB_OVERLAY_SWING_HOLD_SEC = 2.0
_CHAR_PICK_IDLE_FULL_H = 64
# 선택 그리드는 예전(1/2)보다 1.5배 크게: 64 * 0.75 = 48
_CHAR_PICK_IDLE_GRID_H = int(round(_CHAR_PICK_IDLE_FULL_H * 0.75))
# "선택 하시겠습니까?" 팝업은 2배
_CHAR_PICK_IDLE_CONFIRM_H = _CHAR_PICK_IDLE_FULL_H * 2
# 경기 결과 화면 캐릭터 — 원본 스프라이트 대비 정배수 줌 (idle 48px → 192px)
_MATCH_RESULT_CHAR_ZOOM = 4
_MATCH_RESULT_CHAR_FPS = 6.0
_CHAR_PICK_GRID_COLS = 4
_CHAR_PICK_GRID_ROWS = 2


def _play_bat_swing(player) -> None:
    """레거시 per-char swing — 공용 오버레이가 있으면 baseball 쪽에서 처리."""
    del player


def _body_type_for_char(char_id: str) -> str:
    from char_behavior import char_body_type, get_char_type_def

    return char_body_type(get_char_type_def(char_id))


def _load_bb_overlay_frames(body_type: str, anim_set: str) -> List:
    from engine import load_baseball_overlay_frames

    return list(load_baseball_overlay_frames(body_type, anim_set) or [])


def _sync_baseball_overlay_idle(player, char_id: str = "") -> None:
    if player is None or not bool(getattr(player, "playing_baseball", False)):
        return
    cid = str(char_id or getattr(player, "name", "") or "").strip()
    bt = _body_type_for_char(cid)
    if bt == "animal":
        clr = getattr(player, "clear_sprite_overlay", None)
        if callable(clr):
            clr()
        return
    frames = _load_bb_overlay_frames(bt, "idle_baseball")
    setter = getattr(player, "set_sprite_overlay", None)
    if frames and callable(setter):
        setter(frames, loop=True, fps=_BB_OVERLAY_IDLE_FPS)
    else:
        clr = getattr(player, "clear_sprite_overlay", None)
        if callable(clr):
            clr()


def _sync_baseball_overlay_idle_frozen(player, char_id: str = "") -> None:
    if player is None or not bool(getattr(player, "playing_baseball", False)):
        return
    cid = str(char_id or getattr(player, "name", "") or "").strip()
    bt = _body_type_for_char(cid)
    if bt == "animal":
        return
    idle = _load_bb_overlay_frames(bt, "idle_baseball")
    setter = getattr(player, "set_sprite_overlay", None)
    if idle and callable(setter):
        setter(idle[:1], loop=True, fps=1.0)
    else:
        _sync_baseball_overlay_idle(player, cid)


def _freeze_baseball_batter_pose(player, char_id: str = "") -> None:
    _sync_baseball_overlay_idle_frozen(player, char_id)
    if player is None:
        return
    try:
        player.clear_anim_override()
    except Exception:
        pass
    try:
        player.stop_moving()
    except Exception:
        pass
    try:
        player.state = "idle"
        player.frame_idx = 0
        player.last_anim_time = pygame.time.get_ticks()
        dr = "right" if str(getattr(player, "direction", "right")) == "right" else "left"
        anims = getattr(player, "anims_r", None) if dr == "right" else getattr(player, "anims_l", None)
        frames = (anims or {}).get("idle") or []
        if frames:
            player.image = frames[0]
    except Exception:
        pass


def _sync_baseball_overlay_swing(player, char_id: str = "") -> None:
    if player is None or not bool(getattr(player, "playing_baseball", False)):
        return
    cid = str(char_id or getattr(player, "name", "") or "").strip()
    bt = _body_type_for_char(cid)
    if bt == "animal":
        return
    idle = _load_bb_overlay_frames(bt, "idle_baseball")
    swing = _load_bb_overlay_frames(bt, "swing_baseball")
    play = getattr(player, "play_sprite_overlay_once", None)
    if swing and callable(play):
        play(
            swing,
            fps=_BB_OVERLAY_SWING_FPS,
            hold_sec=_BB_OVERLAY_SWING_HOLD_SEC,
            release_frames=idle or None,
        )
    elif idle:
        _sync_baseball_overlay_idle(player, cid)


def _set_player_playing_baseball(
    player, on: bool, *, char_id: str = "", apply_overlay: bool = False
) -> None:
    if player is None:
        return
    player.playing_baseball = bool(on)
    if on:
        if apply_overlay:
            _sync_baseball_overlay_idle(player, char_id)
    else:
        clr = getattr(player, "clear_sprite_overlay", None)
        if callable(clr):
            clr()


class BaseballActivity(BaseFieldActivity):
    activity_id = "baseball"

    def __init__(self):
        self.state = ST_MENU
        self.map_id = ""
        self.field: dict = {}
        self._rng = random.Random()

        self.mode = MODE_RECORD_1P
        # 메뉴에서 고른 플레이 규칙 (solo_record / npc_alt / duo_alt / duo_batch)
        self._play_style = PLAY_SOLO_RECORD
        self._story_cleared = False
        self._win_flag = str(_cfg("story_win_flag", "progress_baseball_story"))
        self._seed_flag = str(_cfg("story_seed_flag", "progress_baseball_seed"))

        self.plate_xy = (0.0, 0.0)
        self.tee_xy = (0.0, 0.0)
        self.ball_rest_xy = (0.0, 0.0)
        self._ball_rest_h = float(_cfg("tee_height", 16.0))
        self._ball_item = None
        self._bat_item = None
        self._zone_objs: List = []
        self._scoreboard_objs: List = []
        self._last_zone_label = ""
        self._wait_opponent_offset = (-30.0, 22.0)
        self._p1_wait_pos: Optional[Tuple[float, float]] = None
        self._p2_wait_pos: Optional[Tuple[float, float]] = None
        self._swings_per_side = int(_cfg("swings", 5))
        self._fan_half_deg = float(_cfg("fan_half_deg", 32.0))
        self._max_carry = float(_cfg("max_carry_px", 720.0))
        self._pwr_power_sweet_spot_bonus_mul = float(_cfg("pwr_power_sweet_spot_bonus_mul", 1.2))
        self._pwr_confirm_hold_sec = float(_cfg("pwr_confirm_hold_sec", 0.5))
        self._swing_speed_mul = float(_cfg("swing_speed_mul", 1.3))
        self._pwr_confirm_hold_t = 0.0
        self._power_swing_pause_t = 0.0
        self._is_power_swing = False
        self._power_swing_fx_left = 0.0
        self._power_swing_zoom_active = False

        self._menu_rects: List[Tuple[pygame.Rect, str]] = []
        self._p2_char_opts: List[str] = []
        self._p2_pick_ix = 0
        self._char_pick_ix = 0
        self._char_opts: List[str] = []
        self._char_pick_rects: List[Tuple[pygame.Rect, int]] = []
        self._char_idle_cache: Dict[str, Dict[str, List]] = {}
        self._char_anim_cache: Dict[str, List] = {}
        self._char_pending_ix: Optional[int] = None
        self._char_pick_phase = "solo"  # solo | 1p | 2p | npc
        self._char_opts_base: List[str] = []  # "?" 제외한 선택 풀
        self._p1_char = ""
        self._p2_char = ""
        self._char_locked: set[str] = set()
        self._npc_random_pick = False  # "?" 로 뽑았는지 (표시용)
        self._records_view = False
        self._orig_char_name = ""
        self._return_map = ""
        self._return_pos: Optional[List[float]] = None
        self._should_return = False

        self._player_char = ""
        self._npc_name = ""
        self._turn_is_player = True
        self._swing_ix = 0
        self._p1_dists: List[float] = []
        self._p2_dists: List[float] = []
        self._p1_hr = 0
        self._p2_hr = 0
        self._npc_dists: List[float] = []
        self._batting_as_p2 = False
        # 번갈아 모드 승점 (라운드 비거리 비교 + 합계비거리 보너스)
        self._p1_pts = 0
        self._p2_pts = 0
        # 2P/번갈아 페이드 전환 시 목표 타자 (True=2P, False=1P)
        self._switch_batter_to_p2 = True
        self._save_data: Dict[str, Any] = {}
        self._difficulty_id = BASEBALL_DIFFICULTY_DEFAULT

        self._dir_phase = 0.0
        self._dir_speed = float(_cfg("dir_sweep_hz", 1.35))
        self._locked_dir_deg = 0.0
        self._pwr_phase = 0.0
        self._pwr_speed = float(_cfg("pwr_sweep_hz", 0.95))
        self._locked_pwr = 0.0
        self._locked_pwr_marker_t = 0.5
        self._ball_touch_r = float(_cfg("ball_touch_radius_px", 36.0))
        self._batter_face_default = "right"

        self._swing_t = 0.0
        self._flight_t = 0.0
        self._flight_dur = 1.8
        self._flight_sub = "arc"
        self._flight_angle_deg = 0.0
        self._ground_roll_angle_deg = 0.0
        self._land_xy = (0.0, 0.0)
        self._roll_xy = [0.0, 0.0]
        self._roll_left = 0.0
        self._roll_travel_total = 0.0
        self._bounce_travel_total = 0.0
        self._bounce_ix = 0
        self._bounce_t = 0.0
        self._bounce_dur = 0.4
        self._bounce_count = 3
        self._bounce_h0 = 12.0
        self._carry_px = 0.0
        self._ball_h_max = 48.0
        self._is_foul = False
        self._is_pop_foul = False
        self._fence_hit = False
        self._ground_fence_bounced = False
        self._planned_home_run = False
        self._turn_wait = 0.0
        self._npc_flash_t = 0.0
        self._npc_flash_dist = 0.0

        self._msg = ""
        self._hud_lines: List[str] = []
        self._announce_text = ""
        self._announce_is_home_run = False
        self._announce_left = 0.0
        self._announce_tap_wait = False
        self._announce_steps: List[AnnounceStep] = []
        self._announce_on_done: Optional[Callable[[], None]] = None
        self._gauge_time_left = 0.0
        self._gauge_time_limit = float(_cfg("gauge_time_limit_sec", 5.0))
        self._scene_frozen = False
        self._scene_ball_xy = (0.0, 0.0)
        self._scene_cam_xy = (0.0, 0.0)
        self._won = False
        self._match_win_side = 0  # 1=P1, -1=P2, 0=무승부 (2P 결과 화면)
        self._finish_hold = 0.0
        self._elapsed = 0.0
        self._save_patch: Dict[str, Any] = {}

        self.field_tilt_target: Optional[float] = None
        self._player_ref = None
        self._ball_screen_rect = None
        self._batter_face_default = "right"
        self._cam_fixed = (220.0, 500.0)
        self._field_camera_command: Optional[Dict[str, Any]] = None
        self._cam_cmd_key: Optional[Tuple] = None
        self._pending_world_zoom: Optional[Dict[str, Any]] = None
        self._intro_phase = ""
        self._intro_t = 0.0
        self._p2_switch_fade_phase = ""
        self._p2_switch_fade_t = 0.0
        self._p2_switch_fade_dur = 0.0
        self._p2_switch_fade_alpha = 0
        self._intro_elapsed = 0.0
        self._intro_on_done: Optional[Callable[[], None]] = None
        self._intro_pan_points: List[Tuple[float, float]] = []
        self._intro_pan_ix = 0
        self._leaderboard_highlight = -1
        self._fielders: List = []
        self._fielder_home: Dict[int, Tuple[float, float]] = {}
        self._fielder_chase_t = 0.0
        self._active_chasers: set = set()
        self._ball_caught = False
        self._ball_catcher = None
        self._catch_ball_xy = (0.0, 0.0)
        self._catch_hold_t = 0.0
        self._catch_release_targets: Dict[int, Tuple[float, float]] = {}
        self._nav_mask = None
        self._nav_objs: List = []
        self._nav_npcs: List = []
        self._mask_surf = None

    # ------------------------------------------------------------------ begin

    def begin(self, player, **params) -> bool:
        self._player_ref = player
        self._ev_mgr = params.get("ev_mgr")
        self.map_id = str(
            params.get("map")
            or params.get("map_id")
            or _cfg("default_map_id", "bg_baseball1")
        ).strip()
        self.field = _field_cfg(self.map_id, params.get("world_data"))
        if not self.field:
            print(f"[baseball] unknown map config: {self.map_id}")
            return False

        save = params.get("save_data") or {}
        if isinstance(save, dict):
            self._save_data = dict(save)
            self._story_cleared = bool(int(save.get(self._win_flag, 0) or 0))
            self._difficulty_id = self._normalize_difficulty_id(
                save.get("baseball_difficulty")
            )
        else:
            self._save_data = {}
            self._story_cleared = False
            self._difficulty_id = BASEBALL_DIFFICULTY_DEFAULT

        plate = self.field.get("plate") or [float(player.pos[0]), float(player.pos[1])]
        self.plate_xy = (float(plate[0]), float(plate[1]))
        tee = self.field.get("tee") or [self.plate_xy[0] + 18.0, self.plate_xy[1] - 8.0]
        self.tee_xy = (float(tee[0]), float(tee[1]))
        self.ball_rest_xy = (float(self.tee_xy[0]), float(self.tee_xy[1]))
        try:
            self._ball_rest_h = float(
                self.field.get("tee_height", _cfg("tee_height", 16.0))
            )
        except (TypeError, ValueError):
            self._ball_rest_h = float(_cfg("tee_height", 16.0))
        self._ball_rest_h = max(0.0, float(self._ball_rest_h))
        self._load_landing_mask()
        self._bind_field_objects(params.get("objs"))
        self._bind_field_npcs(params.get("npcs"), params.get("mask"), params.get("objs"))
        self._npc_name = str(self.field.get("npc_name") or "야구친구")
        self._swings_per_side = int(self.field.get("swings", _cfg("swings", 5)))
        self._pwr_power_sweet_spot_bonus_mul = float(self.field.get("pwr_power_sweet_spot_bonus_mul", _cfg("pwr_power_sweet_spot_bonus_mul", 1.2)))
        self._pwr_confirm_hold_sec = float(self.field.get("pwr_confirm_hold_sec", _cfg("pwr_confirm_hold_sec", 0.5)))
        self._swing_speed_mul = max(0.01, float(self.field.get("swing_speed_mul", _cfg("swing_speed_mul", 1.3))))
        self._apply_fan_half_deg()
        self._max_carry = float(self.field.get("max_carry_px", _cfg("max_carry_px", 720.0)))
        self._px_per_meter = float(
            self.field.get("px_per_meter", _cfg("px_per_meter", 7.2))
        )
        self._apply_difficulty_balance()
        self._carry_mul = float(
            self.field.get("carry_distance_mul", _cfg("carry_distance_mul", 1.3))
        )
        self._height_mul = float(
            self.field.get("flight_height_mul", _cfg("flight_height_mul", 1.5))
        )
        wo = self.field.get("wait_opponent_offset") or [-30.0, 22.0]
        try:
            self._wait_opponent_offset = (float(wo[0]), float(wo[1]))
        except (TypeError, ValueError, IndexError):
            self._wait_opponent_offset = (-30.0, 22.0)
        self._p1_wait_pos = self._parse_optional_xy(self.field.get("p1_wait_pos"))
        self._p2_wait_pos = self._parse_optional_xy(self.field.get("p2_wait_pos"))
        cf = self.field.get("cam_fixed") or [220.0, 500.0]
        try:
            self._cam_fixed = (float(cf[0]), float(cf[1]))
        except (TypeError, ValueError, IndexError):
            self._cam_fixed = (220.0, 500.0)
        self._intro_pan_points = self._parse_intro_pan_points(self.field)
        self._field_camera_command = {
            "mode": "fixed",
            "x": self._cam_fixed[0],
            "y": self._cam_fixed[1],
            "smooth": True,
            "duration_sec": 0.35,
        }

        self._player_char = str(getattr(player, "name", "") or _cfg("default_player_char", "c10"))

        from data import CHAR_ASSETS

        self._p2_char_opts = list(
            self.field.get("p2_chars")
            or _cfg("p2_chars")
            or sorted(CHAR_ASSETS.keys())[:6]
        )
        self._p2_char = str(self._p2_char_opts[0] if self._p2_char_opts else self._player_char)

        # 캐릭터 선택: 고정 6 + 히든 2 (총 8칸, 4x2)
        fixed = self.field.get("char_pick_fixed")
        hidden = self.field.get("char_pick_hidden")
        if not isinstance(fixed, (list, tuple)) or not fixed:
            fixed = self.field.get("demo_chars") or _cfg("p2_chars")
        if not isinstance(fixed, (list, tuple)) or not fixed:
            fixed = sorted(CHAR_ASSETS.keys())[:6]
        if not isinstance(hidden, (list, tuple)):
            hidden = []

        fixed6 = [str(x).strip() for x in list(fixed) if str(x).strip()][:6]
        hidden2 = [str(x).strip() for x in list(hidden) if str(x).strip()][:2]

        opts8: List[str] = []
        for cid in fixed6 + hidden2:
            if cid and cid in CHAR_ASSETS and cid not in opts8:
                opts8.append(cid)
        for cid in fixed6:
            if len(opts8) >= 8:
                break
            if cid and cid in CHAR_ASSETS and cid not in opts8:
                opts8.append(cid)
        self._char_opts = opts8[:8]
        self._char_opts_base = list(self._char_opts)

        # 히든 잠금: save_data.flags.unlock_<cid> 가 없으면 선택 불가(표시는 함)
        self._char_locked = set()
        try:
            flags = (self._save_data or {}).get("flags") or {}
        except Exception:
            flags = {}
        for cid in hidden2:
            if cid not in self._char_opts:
                continue
            key = f"unlock_{cid}"
            unlocked = False
            try:
                unlocked = bool(flags.get(key))
            except Exception:
                unlocked = False
            if not unlocked:
                self._char_locked.add(cid)
        self._char_pick_ix = 0
        for i, cn in enumerate(self._char_opts):
            if cn == self._player_char:
                self._char_pick_ix = i
                break

        self._orig_char_name = str(getattr(player, "name", "") or self._player_char)
        self._return_map = str(params.get("return_map") or "").strip()
        rp = params.get("return_pos")
        if isinstance(rp, (list, tuple)) and len(rp) >= 2:
            self._return_pos = [float(rp[0]), float(rp[1])]
        else:
            self._return_pos = None
        self._should_return = False
        self._resolve_return_anchor(save)

        req_mode = str(params.get("mode") or "").strip().lower()
        if req_mode == MODE_DEMO:
            self.mode = MODE_DEMO
            self.state = ST_PICK_CHAR
            self._msg = "캐릭터를 고르고 게임을 시작하세요"
            lw, lh = self._logical_screen_size()
            self._layout_menu_rects(lw, lh)
        elif req_mode == MODE_STORY:
            self.mode = MODE_STORY
            self._start_story_match()
        elif req_mode == MODE_RECORD_1P:
            self.mode = MODE_RECORD_1P
            self._play_style = PLAY_SOLO_RECORD
            self.state = ST_PICK_CHAR
            self._char_pick_phase = "solo"
            self._msg = "1P 캐릭터 선택"
            lw, lh = self._logical_screen_size()
            self._layout_menu_rects(lw, lh)
        elif req_mode == MODE_RECORD_2P:
            self.mode = MODE_RECORD_2P
            self._play_style = PLAY_DUO_BATCH
            self.state = ST_PICK_CHAR
            self._char_pick_phase = "1p"
            self._msg = "1P 캐릭터 선택"
            lw, lh = self._logical_screen_size()
            self._layout_menu_rects(lw, lh)
        elif req_mode == MODE_NPC_VS:
            self.mode = MODE_NPC_VS
            self._play_style = PLAY_NPC_ALT
            self.state = ST_PICK_CHAR
            self._char_pick_phase = "solo"
            self._msg = "캐릭터 선택"
            lw, lh = self._logical_screen_size()
            self._layout_menu_rects(lw, lh)
        else:
            self.mode = MODE_RECORD_1P
            self._play_style = PLAY_SOLO_RECORD
            self.state = ST_MENU
            self._msg = "메뉴 — 항목을 누르세요"
            lw, lh = self._logical_screen_size()
            self._layout_menu_rects(lw, lh)

        try:
            player.stop_moving()
            player.pos[0], player.pos[1] = float(self.plate_xy[0]), float(self.plate_xy[1])
            player.target = list(player.pos)
            player.path = []
            self._batter_face_default = str(self.field.get("batter_face") or "right").lower()
            if self._batter_face_default not in ("left", "right"):
                self._batter_face_default = "right"
            player.direction = self._batter_face_default
        except Exception:
            pass

        self.field_tilt_target = float(_cfg("tilt_compressed", 0.68))
        _set_player_playing_baseball(player, True, char_id=self._player_char)
        print(f"[baseball] begin map={self.map_id} state={self.state}")
        return True

    def cancel(self) -> None:
        if self.mode == MODE_DEMO and self._return_map:
            self._quit_demo_return()
            return
        self._quit_via_menu()

    def _configured_exit(self) -> Tuple[str, List[float]]:
        em = str(self.field.get("exit_map") or _cfg("exit_map", "bg_jjangpu")).strip()
        ep_raw = self.field.get("exit_pos")
        if not (isinstance(ep_raw, (list, tuple)) and len(ep_raw) >= 2):
            ep_raw = _cfg("exit_pos", [780.0, 2200.0])
        try:
            pos = [float(ep_raw[0]), float(ep_raw[1])]
        except (TypeError, ValueError, IndexError):
            pos = [780.0, 2200.0]
        if not em:
            em = "bg_jjangpu"
        return em, pos

    def _resolve_return_anchor(self, save: Optional[dict] = None) -> None:
        if self._return_map:
            if self._return_pos is None:
                _, pos = self._configured_exit()
                self._return_pos = pos
            return
        sd = save if isinstance(save, dict) else self._save_data
        em = str((sd or {}).get("baseball_entry_map") or "").strip()
        ep = (sd or {}).get("baseball_entry_pos")
        if em and em != "bg_baseball1" and isinstance(ep, (list, tuple)) and len(ep) >= 2:
            self._return_map = em
            try:
                self._return_pos = [float(ep[0]), float(ep[1])]
            except (TypeError, ValueError, IndexError):
                self._return_map, self._return_pos = self._configured_exit()
            return
        self._return_map, self._return_pos = self._configured_exit()

    def _quit_via_menu(self) -> None:
        """나가기 — world_data exit_map/exit_pos (또는 data.py 기본값) 로 복귀."""
        self._finish_quit_session()

    def _finish_quit_session(self) -> None:
        self._return_map, self._return_pos = self._configured_exit()
        self._reset_fielders()
        self._clear_power_swing_fx()
        self._restore_player_char()
        self._show_rest_ball()
        self._should_return = True
        self.state = ST_QUIT
        self._finish_hold = 0.0
        self.field_tilt_target = None

    def save_location_override(self) -> Optional[Tuple[str, List[float]]]:
        """세이브/종료 시 야구장 좌표 대신 복귀·exit 맵·좌표 사용 (강제 종료 포함)."""
        if self._return_map:
            pos = self._return_pos
            if pos is not None and len(pos) >= 2:
                return (str(self._return_map), [float(pos[0]), float(pos[1])])
            em, pos = self._configured_exit()
            return (str(self._return_map), [float(pos[0]), float(pos[1])])
        em, pos = self._configured_exit()
        return (str(em), [float(pos[0]), float(pos[1])])

    @property
    def is_active(self) -> bool:
        return self.state != ST_QUIT

    @property
    def is_finished(self) -> bool:
        return self.state == ST_QUIT

    def blocks_field_move(self) -> bool:
        return self.state != ST_QUIT

    def blocks_zone_confirm(self) -> bool:
        return self.state not in (ST_QUIT,)

    def _carry_px_to_meters(self, carry_px: float) -> float:
        ppm = max(0.1, float(getattr(self, "_px_per_meter", _cfg("px_per_meter", 12.39))))
        return max(0.0, float(carry_px)) / ppm

    def _total_score_m(self, distances: List[float]) -> float:
        return _total_distance_meters(distances, getattr(self, "_px_per_meter", _cfg("px_per_meter", 12.39)))

    def poll_camera_command(self) -> Optional[Dict[str, Any]]:
        cmd = self._field_camera_command
        self._field_camera_command = None
        return cmd

    def poll_world_zoom_command(self) -> Optional[Dict[str, Any]]:
        cmd = self._pending_world_zoom
        self._pending_world_zoom = None
        return cmd

    def result(self) -> Dict[str, Any]:
        save_patch = dict(self._save_patch)
        save_patch["baseball_difficulty"] = self._difficulty_id
        out: Dict[str, Any] = {
            "activity": self.activity_id,
            "won": bool(self._won),
            "quit": self.state == ST_QUIT,
            "mode": self.mode,
            "play_style": self._play_style,
            "win_flag": self._win_flag if self._won and self.mode == MODE_STORY else None,
            "win_value": 1,
            "save_patch": save_patch,
            "player_total": self._total_score_m(self._p1_dists),
            "opponent_total": self._total_score_m(
                self._p2_dists
                if self.mode in (MODE_RECORD_2P, MODE_NPC_VS)
                else self._npc_dists
            ),
            "p1_pts": int(self._p1_pts),
            "p2_pts": int(self._p2_pts),
        }
        if self._return_map and (self._should_return or self.state == ST_QUIT):
            out["return_map"] = self._return_map
            pos = self._return_pos
            if not (isinstance(pos, (list, tuple)) and len(pos) >= 2):
                _, pos = self._configured_exit()
            out["return_pos"] = [float(pos[0]), float(pos[1])]
        return out

    def _apply_fan_half_deg(self) -> None:
        """fan_half_deg_auto: 마스크 파울라인에 맞춰 화살표 범위=실제 조준 각도."""
        auto = bool(self.field.get("fan_half_deg_auto", _cfg("fan_half_deg_auto", False)))
        if auto and self._mask_surf is not None:
            margin = float(
                self.field.get("fan_half_margin_deg", _cfg("fan_half_margin_deg", 1.5))
            )
            est = estimate_fan_half_deg_from_mask(
                self.plate_xy,
                self._mask_surf,
                cfg=self.field,
                margin_deg=margin,
            )
            if est is not None:
                self._fan_half_deg = float(est)
                print(
                    f"[baseball] fan_half_deg={est:.1f}° (auto from mask, margin={margin:.1f}°)"
                )
                return
        self._fan_half_deg = float(
            self.field.get("fan_half_deg", _cfg("fan_half_deg", 32.0))
        )

    def _angle_spread_deg(self, locked_dir: float, locked_pwr: float) -> float:
        """화살표 방향 기준 ±(부채꼴 반각×비율) 균일 변동 — 가장자리 추가 분산 없음."""
        half = max(1.0, float(self._fan_half_deg))
        ratio = float(
            _field_num(self.field, "swing_dir_spread_ratio", 0.10,
            )
        )
        ratio = max(0.0, min(0.5, ratio))
        spread = half * ratio
        pwr_ratio = float(
            _field_num(self.field, "swing_dir_spread_pwr_ratio", 0.02,
            )
        )
        pwr_off = min(1.0, abs(float(locked_pwr) - 0.5) * 2.0)
        spread += half * max(0.0, min(0.25, pwr_ratio)) * pwr_off
        return spread

    def _resolve_swing_angle(self, locked_dir: float, locked_pwr: float) -> float:
        spread = self._angle_spread_deg(locked_dir, locked_pwr)
        if spread <= 1e-6:
            return float(locked_dir)
        return float(locked_dir) + self._rng.uniform(-spread, spread)

    def _carry_from_locked_swing(self, locked_dir: float, locked_pwr: float) -> float:
        del locked_dir
        base_carry = (
            float(self._max_carry)
            * max(0.0, min(1.0, float(locked_pwr)))
            * float(self._carry_mul)
        )
        
        # 파워장타 구간에 있을 경우
        if self._is_power_swing:
            power_sweet_spot_bonus_mul = self._pwr_power_sweet_spot_bonus_mul
            base_carry *= power_sweet_spot_bonus_mul
        # 장타 구간에 있을 경우 비거리 보너스
        elif self._pwr_in_sweet_spot(locked_pwr):
            sweet_spot_bonus_mul = float(
                _field_num(self.field, "pwr_sweet_spot_bonus_mul", 1.1) # 기본 10% 보너스
            )
            base_carry *= sweet_spot_bonus_mul

        return base_carry

    def _land_xy_from_angle_carry(
        self, angle_deg: float, carry_px: float
    ) -> Tuple[float, float]:
        ox, oy = float(self.ball_rest_xy[0]), float(self.ball_rest_xy[1])
        rad = math.radians(float(angle_deg))
        return (
            ox + math.cos(rad) * float(carry_px),
            oy + math.sin(rad) * float(carry_px),
        )

    def _landing_mask_class(self, wx: float, wy: float) -> str:
        return classify_mask_landing(
            float(wx), float(wy), self._mask_surf, cfg=self.field
        )

    # ------------------------------------------------------------------ field objects / demo helpers

    def _load_landing_mask(self) -> None:
        self._mask_surf = None
        mp = _mask_path_for_field(self.map_id, self.field)
        if not os.path.isfile(mp):
            return
        try:
            surf = pygame.image.load(mp)
            bg_name = str(self.field.get("bg_img") or f"{self.map_id}.png").strip()
            bp = os.path.join("assets", "images", "bg", bg_name)
            if os.path.isfile(bp):
                try:
                    bg = pygame.image.load(bp)
                    bw, bh = bg.get_size()
                    surf = scale_mask_to_background(surf, bw, bh)
                except Exception:
                    pass
            self._mask_surf = surf
        except Exception:
            self._mask_surf = None

    def _bind_field_npcs(self, npcs, mask, objs) -> None:
        """야구장 맵에 배치된 NPC 전원 — 타구 추격용."""
        self._fielders = list(npcs or [])
        self._fielder_home = {}
        self._nav_mask = mask
        self._nav_objs = list(objs or [])
        self._nav_npcs = list(npcs or [])
        for n in self._fielders:
            try:
                self._fielder_home[id(n)] = (float(n.pos[0]), float(n.pos[1]))
            except Exception:
                pass

    def _reset_fielder_chase_state(self) -> None:
        self._release_caught_ball()
        self._active_chasers = set()
        self._ball_caught = False
        self._ball_catcher = None
        self._catch_ball_xy = (0.0, 0.0)
        self._catch_hold_t = 0.0
        self._fielder_chase_t = 0.0
        self._catch_release_targets = {}

    def _attach_ball_to_catcher(self, catcher) -> None:
        """잡은 NPC 가 공을 들게 — 엔진 held_item(들기) 기능 재사용."""
        ball = self._ball_item
        if ball is None or catcher is None:
            return
        if getattr(catcher, "held_item", None) is not None:
            return
        try:
            ball.is_flying = False
            ball.is_held = True
            ball.target_slot = None
            ball.height = 0.0
            ball.is_visible = True
            catcher.held_item = ball
        except Exception:
            pass

    def _release_caught_ball(self) -> None:
        """다음 타격 전 — 잡은 NPC 손에서 공 회수."""
        ball = self._ball_item
        catcher = self._ball_catcher
        if catcher is not None and getattr(catcher, "held_item", None) is ball:
            try:
                catcher.held_item = None
            except Exception:
                pass
        if ball is not None and bool(getattr(ball, "is_held", False)):
            try:
                ball.is_held = False
            except Exception:
                pass

    def _ball_held_by_catcher(self) -> bool:
        ball = self._ball_item
        return (
            ball is not None
            and bool(getattr(ball, "is_held", False))
            and getattr(self._ball_catcher, "held_item", None) is ball
        )

    def _fielder_chase_radius(self) -> float:
        return max(40.0, float(_cfg("fielder_chase_radius_px", 220.0)))

    def _ball_catch_radius(self) -> float:
        return max(8.0, float(_cfg("fielder_catch_radius_px", 28.0)))

    def _ball_catch_max_height(self) -> float:
        return max(0.0, float(_cfg("fielder_catch_max_height_px", 6.0)))

    def _ball_is_catchable(self, h: float) -> bool:
        """포물선 비행(arc) 중에는 잡을 수 없고, 착지 후 높이가 낮을 때만."""
        if self.state != ST_FLIGHT or self._ball_caught:
            return False
        if str(getattr(self, "_flight_sub", "") or "") == "arc":
            return False
        return float(h) <= self._ball_catch_max_height()

    def _reset_fielders(self) -> None:
        self._reset_fielder_chase_state()
        for n in self._fielders:
            home = self._fielder_home.get(id(n))
            if home is None:
                continue
            try:
                n.stop_moving()
                n.pos[0], n.pos[1] = float(home[0]), float(home[1])
                n.target = list(n.pos)
                n.path = []
                n.event_speed_mul = 1.0
            except Exception:
                pass

    def _chase_fielders(self, gx: float, gy: float) -> None:
        if self._ball_caught or not self._fielders or self._nav_mask is None:
            return
        radius = self._fielder_chase_radius()
        spd = float(_cfg("fielder_chase_speed_mul", 1.35))
        next_chasers = set()
        for n in self._fielders:
            try:
                nid = id(n)
                px, py = float(n.pos[0]), float(n.pos[1])
                dist = math.hypot(px - float(gx), py - float(gy))
                already = nid in self._active_chasers
                if not already and dist > radius:
                    continue
                tx, ty = clamp_to_fielder_reachable(
                    float(gx),
                    float(gy),
                    px,
                    py,
                    self._mask_surf,
                    cfg=self.field,
                )
                next_chasers.add(nid)
                n.event_speed_mul = spd
                n.set_new_target(
                    float(tx),
                    float(ty),
                    self._nav_mask,
                    self._nav_objs,
                    self._nav_npcs,
                )
            except Exception:
                pass
        self._active_chasers = next_chasers

    def _tick_fielder_catch(self) -> bool:
        if self._ball_caught:
            return True
        gx, gy, h = self._ball_flight_state()
        if not self._ball_is_catchable(h):
            return False
        bx, by = float(gx), float(gy) - float(h)
        catch_r = self._ball_catch_radius()
        catcher = None
        best_d = catch_r + 1.0
        for n in self._fielders:
            if id(n) not in self._active_chasers:
                continue
            try:
                d = math.hypot(float(n.pos[0]) - bx, float(n.pos[1]) - by)
                if d <= catch_r and d < best_d:
                    best_d = d
                    catcher = n
            except Exception:
                pass
        if catcher is None:
            return False
        self._ball_caught = True
        self._ball_catcher = catcher
        self._catch_ball_xy = (bx, by)
        self._catch_hold_t = max(0.05, float(_cfg("fielder_catch_hold_sec", 0.4)))
        # 캐치 확정: 공 추격은 즉시 종료. 대신 다른 수비수는 "짧게 감속하며 제자리로 복귀"시키기.
        # - 딱 멈추는 느낌을 피한다.
        # - _chase_fielders는 _ball_caught 때문에 더 이상 갱신되지 않는다.
        try:
            spd = float(_cfg("fielder_chase_speed_mul", 1.35))
        except Exception:
            spd = 1.35
        try:
            for n in self._fielders:
                if n is catcher:
                    continue
                nid = id(n)
                if nid not in self._active_chasers:
                    continue
                home = self._fielder_home.get(nid)
                if home is None:
                    continue
                self._catch_release_targets[nid] = (float(home[0]), float(home[1]))
                try:
                    n.event_speed_mul = max(0.35, float(spd) * 0.65)
                except Exception:
                    pass
                try:
                    # 공 쪽으로 달려가던 경로를 "복귀 경로"로 교체
                    n.set_new_target(
                        float(home[0]),
                        float(home[1]),
                        self._nav_mask,
                        self._nav_objs,
                        self._nav_npcs,
                    )
                except Exception:
                    pass
            self._active_chasers = {id(catcher)}
        except Exception:
            self._catch_release_targets = {}
        try:
            catcher.stop_moving()
        except Exception:
            pass
        self._attach_ball_to_catcher(catcher)
        return True

    def _ease_non_catcher_fielders(self, dt_sec: float) -> None:
        if not self._ball_caught:
            return
        decay = max(0.05, float(_cfg("fielder_stop_decay_sec", 0.2)))
        # 캐치 직후에는 빠르게 풀리도록 기본보다 더 강하게 감속
        step = max(0.0, float(dt_sec)) / decay
        for n in self._fielders:
            if n is self._ball_catcher:
                continue
            nid = id(n)
            if nid not in self._active_chasers and nid not in (self._catch_release_targets or {}):
                continue
            try:
                mul = float(getattr(n, "event_speed_mul", 1.0) or 1.0)
                mul = max(0.0, mul - step)
                n.event_speed_mul = mul
                home = (self._catch_release_targets or {}).get(nid)
                if home is not None:
                    try:
                        if math.hypot(float(n.pos[0]) - float(home[0]), float(n.pos[1]) - float(home[1])) <= 6.0:
                            mul = 0.0
                            n.event_speed_mul = 0.0
                    except Exception:
                        pass
                if mul <= 0.02:
                    n.stop_moving()
                    self._active_chasers.discard(nid)
                    try:
                        self._catch_release_targets.pop(nid, None)
                    except Exception:
                        pass
            except Exception:
                pass

    @staticmethod
    def _match_winner_side(p1_hr: int, p1_tot: float, p2_hr: int, p2_tot: float) -> int:
        """1=P1 승, -1=P2 승, 0=무승부. (모아서 하기: 홈런 우선, 동점이면 합계비거리)."""
        if int(p1_hr) != int(p2_hr):
            return 1 if int(p1_hr) > int(p2_hr) else -1
        if float(p1_tot) != float(p2_tot):
            return 1 if float(p1_tot) > float(p2_tot) else -1
        return 0

    def _is_alternate_play(self) -> bool:
        """번갈아 타격·승점 규칙 (2P 번갈아 / NPC와 하기)."""
        return self._play_style in (PLAY_DUO_ALT, PLAY_NPC_ALT)

    def _is_duo_batch(self) -> bool:
        """둘이서 모아서 하기 — 각자 횟수만큼 전부 친 뒤 HR+합계 비교."""
        return self._play_style == PLAY_DUO_BATCH

    def _is_versus_match(self) -> bool:
        """전광판·대기 상대 등 대결 UI가 필요한 모드."""
        return self.mode in (MODE_RECORD_2P, MODE_NPC_VS)

    def _opponent_display_name(self) -> str:
        """대결 상대 표시명 (2P/NPC 캐릭터 UI명)."""
        if self.mode == MODE_NPC_VS:
            if self._p2_char and self._p2_char != CHAR_PICK_RANDOM:
                return self._char_label(self._p2_char)
            return str(self._npc_name or "NPC").strip() or "NPC"
        return self._char_label(self._p2_char)

    def _batter_overlay_char(self) -> str:
        """타격 오버레이에 쓸 현재 타자 캐릭터 ID."""
        return str(self._current_batter_char() or self._player_char or "")

    def _difficulty_npc_skill(self) -> float:
        """난이도별 NPC 레거시 스킬 (스토리 일괄 시뮬 폴백)."""
        did = self._normalize_difficulty_id(self._difficulty_id)
        fallback = {
            "easy": float(_cfg("difficulty_easy_npc_skill", 0.45)),
            "normal": float(_cfg("difficulty_normal_npc_skill", 0.62)),
            "hard": float(_cfg("difficulty_hard_npc_skill", 0.80)),
        }.get(did, float(_cfg("npc_skill", 0.62)))
        try:
            return max(0.05, min(0.98, float(_cfg(f"difficulty_{did}_npc_skill", fallback))))
        except (TypeError, ValueError):
            return max(0.05, min(0.98, float(fallback)))

    def _npc_band_weights(self) -> List[float]:
        """난이도별 [foul,a,b,c,d,e] 가중치. d 최고·c/e 다음이 기본."""
        did = self._normalize_difficulty_id(self._difficulty_id)
        defaults = {
            "easy": [0.14, 0.20, 0.24, 0.18, 0.14, 0.10],
            "normal": [0.08, 0.10, 0.12, 0.22, 0.30, 0.18],
            "hard": [0.04, 0.06, 0.08, 0.20, 0.36, 0.26],
        }
        raw = _cfg(f"difficulty_{did}_npc_band_weights", defaults.get(did))
        out: List[float] = []
        if isinstance(raw, (list, tuple)) and len(raw) >= 6:
            for i in range(6):
                try:
                    out.append(max(0.0, float(raw[i])))
                except (TypeError, ValueError):
                    out.append(0.0)
        else:
            out = list(defaults.get(did, defaults["normal"]))
        s = sum(out)
        if s <= 1e-9:
            return list(defaults["normal"])
        return [x / s for x in out]

    def _npc_ai_roll_band(self) -> str:
        """가중 랜덤으로 foul/a/b/c/d/e 중 하나."""
        weights = self._npc_band_weights()
        r = self._rng.random()
        acc = 0.0
        for key, w in zip(_NPC_BAND_KEYS, weights):
            acc += float(w)
            if r <= acc:
                return str(key)
        return "d"

    def _npc_ai_plan_swing(self) -> Dict[str, Any]:
        """
        NPC 한 타 계획.
        반환: {foul:bool, pop_foul:bool, dir_deg, pwr, carry_px, power_swing:bool, band:str}
        비거리 0~100 스케일 → max_carry 비율로 환산해 실제 비행에 사용.
        """
        band = self._npc_ai_roll_band()
        fan = max(8.0, float(self._fan_half_deg))
        if band == "foul":
            # 파울: 빗맞음(머리 뒤) 또는 방향 파울
            if self._rng.random() < 0.55:
                return {
                    "foul": True,
                    "pop_foul": True,
                    "band": band,
                    "dir_deg": 0.0,
                    "pwr": 0.2,
                    "carry_px": 0.0,
                    "power_swing": False,
                }
            # 페어라인 밖 방향
            side = 1.0 if self._rng.random() < 0.5 else -1.0
            dir_deg = side * self._rng.uniform(fan * 0.92, fan * 1.15)
            pwr = self._rng.uniform(0.25, 0.55)
            return {
                "foul": True,
                "pop_foul": False,
                "band": band,
                "dir_deg": dir_deg,
                "pwr": pwr,
                "carry_px": float(_cfg("foul_carry_px", 20.0)),
                "power_swing": False,
            }
        lo, hi = _NPC_BAND_FRAC.get(band, (0.61, 0.80))
        # 밴드 안 균등 + 살짝 가우스로 중앙 쪽 편향
        mid = (lo + hi) * 0.5
        frac = max(lo, min(hi, self._rng.gauss(mid, (hi - lo) * 0.22)))
        max_c = max(80.0, float(self._max_carry))
        carry_px = max_c * float(frac)
        # 페어 지역 방향 — 장타일수록 가운데로
        center_bias = 0.35 + 0.45 * float(frac)
        dir_deg = self._rng.gauss(0.0, fan * (1.0 - center_bias) * 0.55)
        dir_deg = max(-fan * 0.95, min(fan * 0.95, dir_deg))
        pwr = max(0.15, min(1.0, float(frac)))
        power_swing = bool(band == "e" and frac >= 0.88)
        return {
            "foul": False,
            "pop_foul": False,
            "band": band,
            "dir_deg": float(dir_deg),
            "pwr": float(pwr),
            "carry_px": float(carry_px),
            "power_swing": power_swing,
        }

    def _bind_field_objects(self, objs) -> None:
        self._ball_item = None
        self._bat_item = None
        self._zone_objs = collect_zone_objects(objs)
        self._scoreboard_objs = collect_scoreboard_objects(objs)
        if not objs:
            return
        for o in objs:
            n = str(getattr(o, "name", "") or "")
            if n == "ball1" and self._ball_item is None:
                self._ball_item = o
            elif n == "baseballbat1" and self._bat_item is None:
                self._bat_item = o
        if self._ball_item is not None:
            bx = float(self._ball_item.pos[0])
            by = float(self._ball_item.pos[1])
            self.ball_rest_xy = (bx, by)
            try:
                ih = float(getattr(self._ball_item, "height", 0) or 0)
            except (TypeError, ValueError):
                ih = 0.0
            if ih > 0.0:
                self._ball_rest_h = ih
        self._sync_rest_ball_object()

    def _sync_rest_ball_object(self) -> None:
        """맵 ball1 — pos=바닥, height=티 높이(방망이 위). 틸트 시 엔진 ysort 와 동일."""
        ball = self._ball_item
        if ball is None:
            return
        try:
            ball.pos[0] = float(self.ball_rest_xy[0])
            ball.pos[1] = float(self.ball_rest_xy[1])
            ball.height = float(self._ball_rest_h)
        except Exception:
            pass

    def _show_rest_ball(self) -> None:
        self._release_caught_ball()
        if self._ball_item is not None:
            self._sync_rest_ball_object()
            self._ball_item.is_visible = True

    def _hide_rest_ball(self) -> None:
        if self._ball_item is not None:
            self._ball_item.is_visible = False

    def _apply_batter_char(self, char_name: str) -> None:
        self._player_char = str(char_name or self._player_char)
        pl = self._player_ref
        if pl is None:
            return
        cur = str(getattr(pl, "name", "") or "")
        if self._player_char == cur:
            pl.direction = "right"
            return
        rt = getattr(pl, "retarget_char_def", None)
        if callable(rt):
            try:
                rt(self._player_char)
            except Exception:
                pass
        try:
            pl.direction = "right"
        except Exception:
            pass
        if bool(getattr(pl, "playing_baseball", False)) and self.state in (
            ST_BAT_DIR,
            ST_BAT_PWR,
            ST_SWING_PAUSE,
            ST_POWER_SWING_PAUSE,
            ST_TURN_WAIT,
            ST_SWING,
        ):
            _sync_baseball_overlay_idle(pl, self._player_char)

    def _apply_demo_char(self, char_name: str) -> None:
        self._apply_batter_char(char_name)

    def _restore_player_char(self) -> None:
        pl = self._player_ref
        if pl is not None:
            _set_player_playing_baseball(pl, False)
        if pl is None or not self._orig_char_name:
            return
        cur = str(getattr(pl, "name", "") or "")
        if cur == self._orig_char_name:
            return
        rt = getattr(pl, "retarget_char_def", None)
        if callable(rt):
            try:
                rt(self._orig_char_name)
            except Exception:
                pass

    def _start_demo_match(self) -> None:
        self._p1_dists = []
        self._swing_ix = 0
        self._won = False
        self._save_patch = {}
        self._show_rest_ball()
        self._begin_match_intro(show_turn=False)

    def _finish_demo(self) -> None:
        self._clear_scene_freeze()
        self._show_rest_ball()
        p_tot = self._total_score_m(self._p1_dists)
        tags = []
        for i, d in enumerate(self._p1_dists, start=1):
            tags.append("파울" if float(d) <= 0.0 else f"{self._format_meters(d)}m")
        self._hud_lines = [
            f"타격 기록: {', '.join(tags) if tags else '-'}",
            f"거리 합: {int(round(p_tot))}m",
        ]
        self.state = ST_DEMO_RESULT
        self.field_tilt_target = 1.0
        self._msg = "결과"

    def _quit_demo_return(self) -> None:
        if not str(self._return_map or "").strip():
            self._return_map, self._return_pos = self._configured_exit()
        elif self._return_pos is None:
            _, pos = self._configured_exit()
            self._return_pos = pos
        self._restore_player_char()
        self._show_rest_ball()
        self._should_return = True
        self.state = ST_QUIT
        self._finish_hold = 0.0
        self.field_tilt_target = None

    def _pin_batter(self) -> None:
        pl = self._player_ref
        if pl is None:
            return
        try:
            pl.stop_moving()
            pl.pos[0], pl.pos[1] = float(self.plate_xy[0]), float(self.plate_xy[1])
            pl.target = list(pl.pos)
            pl.path = []
            pl.direction = "right"
        except Exception:
            pass
        if self.state in (ST_PWR_CONFIRM, ST_SWING_PAUSE, ST_POWER_SWING_PAUSE):
            _freeze_baseball_batter_pose(pl, self._batter_overlay_char())

    @staticmethod
    def _parse_optional_xy(v) -> Optional[Tuple[float, float]]:
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            try:
                return float(v[0]), float(v[1])
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _parse_intro_pan_points(field) -> List[Tuple[float, float]]:
        """필드 투어 패닝 지점 — intro_pan_points(최대 4) 또는 레거시 intro_pan_right."""
        pts: List[Tuple[float, float]] = []
        raw = field.get("intro_pan_points") if isinstance(field, dict) else None
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    try:
                        pts.append((float(item[0]), float(item[1])))
                    except (TypeError, ValueError):
                        pass
        if not pts and isinstance(field, dict):
            for i in range(1, 5):
                v = field.get(f"intro_pan_{i}")
                if isinstance(v, (list, tuple)) and len(v) >= 2:
                    try:
                        pts.append((float(v[0]), float(v[1])))
                    except (TypeError, ValueError):
                        pass
        if pts:
            return pts[:4]
        pr = field.get("intro_pan_right") if isinstance(field, dict) else None
        if isinstance(pr, (list, tuple)) and len(pr) >= 2:
            try:
                return [(float(pr[0]), float(pr[1]))]
            except (TypeError, ValueError):
                pass
        off = (field.get("intro_pan_right_offset") if isinstance(field, dict) else None) or [
            280.0,
            -30.0,
        ]
        try:
            ox, oy = float(off[0]), float(off[1])
        except (TypeError, ValueError, IndexError):
            ox, oy = 280.0, -30.0
        cf = field.get("cam_fixed") if isinstance(field, dict) else None
        if isinstance(cf, (list, tuple)) and len(cf) >= 2:
            try:
                return [(float(cf[0]) + ox, float(cf[1]) + oy)]
            except (TypeError, ValueError):
                pass
        return [(220.0 + ox, 500.0 + oy)]

    def _waiting_opponent_char(self) -> str:
        if self.mode not in (MODE_RECORD_2P, MODE_NPC_VS):
            return ""
        if self._batting_as_p2:
            return str(self._p1_char or self._player_char)
        return str(self._p2_char or "")

    def _waiting_opponent_xy(self) -> Optional[Tuple[float, float]]:
        if self.mode not in (MODE_RECORD_2P, MODE_NPC_VS):
            return None
        px, py = float(self.plate_xy[0]), float(self.plate_xy[1])
        if self._batting_as_p2 and self._p1_wait_pos is not None:
            return self._p1_wait_pos
        if not self._batting_as_p2 and self._p2_wait_pos is not None:
            return self._p2_wait_pos
        ox, oy = self._wait_opponent_offset
        return px + float(ox), py + float(oy)

    def _draw_char_idle_world(
        self,
        ctx: FieldDrawContext,
        char_id: str,
        wx: float,
        wy: float,
        *,
        face: str = "left",
    ) -> None:
        cid = str(char_id or "").strip()
        if not cid:
            return
        direction = "right" if str(face) == "right" else "left"
        frames = self._idle_frames_for_direction(cid, direction)
        if not frames:
            return
        img = frames[int(self._elapsed * 6.0) % len(frames)]
        z = max(0.5, float(ctx.z))
        try:
            iw, ih = img.get_size()
            dw = max(1, int(round(iw * z)))
            dh = max(1, int(round(ih * z)))
            if dw != iw or dh != ih:
                img = pygame.transform.scale(img, (dw, dh))
        except Exception:
            return
        sx, sy = _world_to_screen(ctx, float(wx), float(wy))
        dx, dy = blit_topleft_bottom_center(int(sx), int(sy), img.get_width(), img.get_height())
        try:
            ctx.surf.blit(img, (int(dx), int(dy)))
        except Exception:
            pass

    def _draw_waiting_opponent(self, ctx: FieldDrawContext) -> None:
        if self.mode not in (MODE_RECORD_2P, MODE_NPC_VS):
            return
        if self.state in _MENU_OVERLAY_STATES:
            return
        cid = self._waiting_opponent_char()
        pos = self._waiting_opponent_xy()
        if not cid or pos is None:
            return
        self._draw_char_idle_world(ctx, cid, pos[0], pos[1], face="right")

    def _scoreboard_text_lines(self) -> List[str]:
        p1 = int(round(self._total_score_m(self._p1_dists)))
        versus = self._is_versus_match()
        p2 = int(round(self._total_score_m(self._p2_dists))) if versus else 0
        active = self.state not in (
            ST_MENU,
            ST_MENU_SOLO,
            ST_MENU_DUO,
            ST_DIFFICULTY,
            ST_PICK_CHAR,
            ST_PICK_P2,
            ST_RECORDS,
            ST_LEADERBOARD,
            ST_MATCH_END,
            ST_DEMO_RESULT,
            ST_QUIT,
        )
        live1 = active and (not versus or not self._batting_as_p2)
        live2 = active and versus and self._batting_as_p2
        # 번갈아: 현재 라운드(1-based). 모아서/기록: 이번 타석 쪽 진행 수
        if self._is_alternate_play():
            set_n = min(self._swings_per_side, int(self._swing_ix) + 1)
            set_line = f"라운드 {set_n}/{self._swings_per_side}"
            opp = "NPC" if self.mode == MODE_NPC_VS else "2P"
            return [
                set_line,
                f"1P {int(self._p1_pts)}점 합계{p1}m" + (" 경기중" if live1 else ""),
                f"{opp} {int(self._p2_pts)}점 합계{p2}m" + (" 경기중" if live2 else ""),
            ]
        return [
            f"세트 {self._swing_ix}/{self._swings_per_side}",
            f"1P 홈런 {int(self._p1_hr)} 합계{p1}m" + (" 경기중" if live1 else ""),
            f"2P 홈런 {int(self._p2_hr)} 합계{p2}m" + (" 경기중" if live2 else ""),
        ]

    def _world_to_composited_screen(self, ctx: FieldDrawContext, wx: float, wy: float) -> Tuple[int, int]:
        """world_surf 좌표 → 후처리 월드 줌 합성 뒤 render_surf 좌표."""
        sx, sy = _world_to_screen(ctx, wx, wy)
        try:
            wz = float(getattr(ctx, "world_zoom_draw", 1.0) or 1.0)
        except Exception:
            wz = 1.0
        try:
            ox = float(getattr(ctx, "world_zoom_off_x", 0.0) or 0.0)
            oy = float(getattr(ctx, "world_zoom_off_y", 0.0) or 0.0)
        except Exception:
            ox, oy = 0.0, 0.0
        return int(round(sx * wz + ox)), int(round(sy * wz + oy))

    def _scoreboard_screen_rect(self, ctx: FieldDrawContext, o) -> Optional[pygame.Rect]:
        if not is_scoreboard_object(o):
            return None
        sw = max(1, int(ctx.surf.get_width()))
        dw, dh = scoreboard_screen_size(o, screen_w=sw)
        cx, cy = self._world_to_composited_screen(ctx, float(o.pos[0]), float(o.pos[1]))
        return pygame.Rect(int(cx - dw // 2), int(cy - dh), dw, dh)

    def _field_item_screen_rect(self, ctx: FieldDrawContext, o) -> Optional[pygame.Rect]:
        z = max(0.5, float(ctx.z))
        rect = zone_footprint_rect(o)
        if rect is None:
            return None
        z = max(0.5, float(ctx.z))
        sx1, sy1 = _world_to_screen(ctx, float(rect.left), float(rect.top))
        sx2, sy2 = _world_to_screen(ctx, float(rect.right), float(rect.bottom))
        left = min(sx1, sx2)
        top = min(sy1, sy2)
        w = max(1, abs(sx2 - sx1))
        h = max(1, abs(sy2 - sy1))
        if w < 8 or h < 8:
            iw, ih = o.image.get_size()
            dw = max(8, int(round(iw * z)))
            dh = max(8, int(round(ih * z)))
            cx, cy = _world_to_screen(ctx, float(o.pos[0]), float(o.pos[1]))
            return pygame.Rect(int(cx - dw // 2), int(cy - dh), dw, dh)
        return pygame.Rect(int(left), int(top), int(w), int(h))

    def _draw_scoreboards(self, ctx: FieldDrawContext) -> None:
        if self.state in (
            ST_MENU,
            ST_MENU_SOLO,
            ST_MENU_DUO,
            ST_DIFFICULTY,
            ST_PICK_CHAR,
            ST_PICK_P2,
            ST_RECORDS,
            ST_QUIT,
        ):
            return
        if not self._scoreboard_objs:
            return
        lines = self._scoreboard_text_lines()
        if not lines:
            return
        font = self._ui_font(ctx, 9)
        corner_font = self._ui_font(ctx, 7)
        for board in self._scoreboard_objs:
            rect = self._scoreboard_screen_rect(ctx, board)
            if rect is None or rect.w < 4 or rect.h < 4:
                continue
            style = scoreboard_style_from_object(board)
            alpha = int(style.get("alpha", 200) or 200)
            if style.get("use_image", True):
                try:
                    board.alpha = alpha
                except Exception:
                    pass
            else:
                fill = tuple((style.get("fill_color") or [24, 48, 40])[:3])
                border = tuple((style.get("border_color") or [210, 255, 220])[:3])
                box = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
                box.fill((*fill, alpha))
                pygame.draw.rect(box, (*border, alpha), box.get_rect(), max(1, rect.w // 24))
                ctx.surf.blit(box, rect.topleft)
                if style.get("show_corner_label", True):
                    tag_text = str(style.get("corner_label") or "").strip()
                    if tag_text:
                        tag = corner_font.render(tag_text, True, border)
                        ctx.surf.blit(tag, (rect.x + 4, rect.y + 2))
            pad = max(2, rect.w // 16)
            y = rect.y + pad
            line_h = max(10, (rect.h - pad * 2) // max(1, len(lines)))
            for ln in lines:
                try:
                    t = font.render(str(ln), True, (210, 255, 220))
                    scale = min(1.0, (rect.w - pad * 2) / max(1, t.get_width()))
                    if scale < 0.85:
                        nw = max(1, int(t.get_width() * scale))
                        nh = max(1, int(t.get_height() * scale))
                        t = pygame.transform.smoothscale(t, (nw, nh))
                    tx = rect.x + (rect.w - t.get_width()) // 2
                    ctx.surf.blit(t, (int(tx), int(y)))
                except Exception:
                    pass
                y += line_h

    def _update_batter_facing_from_gauge(self, deg: Optional[float] = None) -> None:
        """타자는 항상 오른쪽(공이 날아가는 방향)을 본다."""
        del deg
        pl = self._player_ref
        if pl is not None:
            try:
                pl.direction = "right"
            except Exception:
                pass

    def _ball_flight_state(self) -> Tuple[float, float, float]:
        """비행 중 공 월드 (gx, gy=바닥 격자, h=바닥에서 띄운 높이)."""
        if self._ball_caught:
            gx, gy = self._catch_ball_xy
            return float(gx), float(gy), 0.0
        ox, oy = float(self.ball_rest_xy[0]), float(self.ball_rest_xy[1])
        rest_h = float(self._ball_rest_h)
        if self.state != ST_FLIGHT or float(self._carry_px) <= 0.0:
            if self.state in (ST_BAT_DIR, ST_BAT_PWR, ST_SWING_PAUSE, ST_POWER_SWING_PAUSE, ST_SWING, ST_TURN_WAIT, ST_ANNOUNCE):
                return ox, oy, rest_h
            return ox, oy, 0.0
        rad = math.radians(float(self._flight_angle_deg))
        if self._flight_sub == "arc":
            u = max(0.0, min(1.0, self._flight_t / max(0.01, self._flight_dur)))
            dist = float(self._carry_px) * u
            gx = ox + math.cos(rad) * dist
            gy = oy + math.sin(rad) * dist
            flight_h = 4.0 * float(self._ball_h_max) * u * (1.0 - u)
            h = rest_h * (1.0 - u) + flight_h
            return gx, gy, h
        if self._flight_sub == "bounce":
            rad = math.radians(float(self._ground_roll_angle_deg))
            bt = max(0.0, min(1.0, self._bounce_t / max(0.01, self._bounce_dur)))
            phase = min(1.0, (float(self._bounce_ix) + bt) / max(1.0, float(self._bounce_count)))
            dist_along = float(self._bounce_travel_total) * phase
            gx = float(self._land_xy[0]) + math.cos(rad) * dist_along
            gy = float(self._land_xy[1]) + math.sin(rad) * dist_along
            scale = max(0.1, 1.0 - phase * 0.88)
            h = float(self._bounce_h0) * scale * math.sin(math.pi * bt)
            return gx, gy, h
        rad = math.radians(float(self._ground_roll_angle_deg))
        roll_tot = max(1.0, float(self._roll_travel_total))
        roll_prog = 1.0 - max(0.0, float(self._roll_left)) / roll_tot
        dist_along = float(self._bounce_travel_total) + float(self._roll_travel_total) * roll_prog
        gx = float(self._land_xy[0]) + math.cos(rad) * dist_along
        gy = float(self._land_xy[1]) + math.sin(rad) * dist_along
        wob = 1.2 + 0.8 * abs(math.sin(self._elapsed * 12.0)) * max(0.0, float(self._roll_left) / roll_tot)
        return gx, gy, wob

    def _ball_world_pos(self) -> Tuple[float, float]:
        gx, gy, h = self._ball_flight_state()
        return gx, gy - h

    def _ball_ground_pos(self) -> Tuple[float, float]:
        gx, gy, _h = self._ball_flight_state()
        return float(gx), float(gy)

    def _ball_visual_at_rest(self) -> Tuple[float, float]:
        bx, by = float(self.ball_rest_xy[0]), float(self.ball_rest_xy[1])
        return bx, by - float(self._ball_rest_h)

    def _push_camera_command(self, key: Tuple, cmd: Dict[str, Any]) -> None:
        if self._cam_cmd_key == key:
            return
        self._cam_cmd_key = key
        self._field_camera_command = dict(cmd)

    def _finish_field_intro_camera(self) -> None:
        """투어 종료 — 빠르게 320 줌 + 타석 카메라 스냅, 이후 안내."""
        play_zoom = float(self.field.get("intro_zoom_play", _cfg("intro_zoom_play", 2.0)))
        zoom_dur = float(_cfg("intro_zoom_end_dur_sec", 0.12))
        self._pending_world_zoom = {
            "val": play_zoom,
            "duration_sec": zoom_dur,
        }
        self._cam_cmd_key = ("bat",)
        x, y = float(self._cam_fixed[0]), float(self._cam_fixed[1])
        self._field_camera_command = {
            "mode": "fixed",
            "x": x,
            "y": y,
            "smooth": False,
            "duration_sec": 0.0,
        }
        self.field_tilt_target = float(_cfg("tilt_compressed", 0.68))

    def _bat_cam_return_sec(self) -> float:
        return max(0.05, float(_cfg("bat_cam_return_sec", 0.3)))

    def _return_to_plate_camera(self, *, smooth: bool = True) -> None:
        dur = self._bat_cam_return_sec() if smooth else 0.0
        self._push_camera_command(
            ("bat",),
            {
                "mode": "fixed",
                "x": float(self._cam_fixed[0]),
                "y": float(self._cam_fixed[1]),
                "smooth": bool(smooth),
                "duration_sec": dur,
            },
        )

    def _sync_camera(self) -> None:
        if self.state == ST_FIELD_INTRO:
            return
        if self.state == ST_FLIGHT:
            gx, gy = self._ball_ground_pos()
            self._push_camera_command(
                ("flight", round(float(gx), 1), round(float(gy), 1)),
                {
                    "mode": "fixed",
                    "x": float(gx),
                    "y": float(gy),
                    "smooth": True,
                    "duration_sec": 0.07,
                },
            )
            return
        if self.state == ST_ANNOUNCE and self._scene_frozen:
            cx, cy = self._scene_cam_xy
            self._push_camera_command(
                ("frozen", round(float(cx), 1), round(float(cy), 1)),
                {
                    "mode": "fixed",
                    "x": float(cx),
                    "y": float(cy),
                    "smooth": False,
                    "duration_sec": 0.0,
                },
            )
            return
        if self.state == ST_ANNOUNCE:
            bat_dur = float(_cfg("bat_cam_return_sec", 0.12))
            self._push_camera_command(
                ("bat",),
                {
                    "mode": "fixed",
                    "x": float(self._cam_fixed[0]),
                    "y": float(self._cam_fixed[1]),
                    "smooth": True,
                    "duration_sec": bat_dur,
                },
            )
            return
        if self.state in (ST_BAT_DIR, ST_BAT_PWR, ST_SWING_PAUSE, ST_POWER_SWING_PAUSE, ST_SWING, ST_TURN_WAIT):
            bat_dur = float(_cfg("bat_cam_return_sec", 0.12))
            self._push_camera_command(
                ("bat",),
                {
                    "mode": "fixed",
                    "x": float(self._cam_fixed[0]),
                    "y": float(self._cam_fixed[1]),
                    "smooth": True,
                    "duration_sec": bat_dur,
                },
            )

    def _is_ball_touch(self, world_xy, screen_xy=None) -> bool:
        if world_xy is not None:
            try:
                bx, by = self._ball_visual_at_rest()
                wx = float(world_xy[0])
                wy = float(world_xy[1])
                r = max(12.0, float(self._ball_touch_r))
                if math.hypot(wx - bx, wy - by) <= r:
                    return True
            except (TypeError, ValueError, IndexError):
                pass
        if screen_xy and getattr(self, "_ball_screen_rect", None) is not None:
            try:
                px, py = int(screen_xy[0]), int(screen_xy[1])
                if self._ball_screen_rect.collidepoint(px, py):
                    return True
            except Exception:
                pass
        return False

    def _note_ball_screen_rect(self, ctx: FieldDrawContext) -> None:
        """타격 대기 중 공 스프라이트 화면 영역 (터치 판정용)."""
        self._ball_screen_rect = None
        if self.state not in (ST_BAT_DIR, ST_BAT_PWR, ST_TURN_WAIT):
            return
        bx, by = self._ball_visual_at_rest()
        sx, sy = _world_to_screen(ctx, bx, by)
        ball = self._ball_item
        frames = getattr(ball, "frames", None) or []
        img = None
        if frames:
            img = frames[int(getattr(ball, "frame_idx", 0) or 0) % len(frames)]
        elif getattr(ball, "image", None) is not None:
            img = ball.image
        z = max(0.5, float(ctx.z))
        if img is not None:
            iw, ih = img.get_size()
            pad = max(10, int(round(max(iw, ih) * z * 0.65)))
        else:
            pad = max(14, int(round(12 * z)))
        self._ball_screen_rect = pygame.Rect(
            int(sx - pad), int(sy - pad), int(pad * 2), int(pad * 2)
        )

    def _draw_ball_at_rest(self, ctx: FieldDrawContext) -> None:
        if self._ball_item is not None and bool(getattr(self._ball_item, "is_visible", True)):
            self._sync_rest_ball_object()
            self._note_ball_screen_rect(ctx)
            return
        bx, by = self._ball_visual_at_rest()
        sx, sy = _world_to_screen(ctx, bx, by)
        ball = self._ball_item
        frames = getattr(ball, "frames", None) or []
        img = None
        if frames:
            img = frames[int(getattr(ball, "frame_idx", 0) or 0) % len(frames)]
        elif getattr(ball, "image", None) is not None:
            img = ball.image
        z = max(0.5, float(ctx.z))
        if img is not None:
            iw, ih = img.get_size()
            dw = max(1, int(round(iw * z)))
            dh = max(1, int(round(ih * z)))
            if dw != iw or dh != ih:
                img = pygame.transform.scale(img, (dw, dh))
            ctx.surf.blit(img, (int(sx - dw // 2), int(sy - dh // 2)))
        else:
            pygame.draw.circle(ctx.surf, (255, 248, 240), (int(sx), int(sy)), max(4, int(6 * z)))
        if self.state in (ST_BAT_DIR, ST_BAT_PWR):
            pulse = int(3 + abs(math.sin(self._elapsed * 6.0)) * 3)
            pygame.draw.circle(
                ctx.surf, (255, 230, 90), (int(sx), int(sy)), max(8, int(10 * z + pulse)), 2
            )
        self._note_ball_screen_rect(ctx)

    # ------------------------------------------------------------------ announce overlays

    def _char_label(self, char_id: str) -> str:
        from char_behavior import get_char_ui_name

        cid = str(char_id or "").strip()
        if not cid:
            return "플레이어"
        return get_char_ui_name(cid)

    def _swing_announce_text(self, swing_ix: int) -> str:
        ix = max(0, min(int(swing_ix), len(_SWING_ORDINAL_KO) - 1))
        return f"{_SWING_ORDINAL_KO[ix]}번째 타격!"

    def _plate_return_swing_steps(self, swing_ix: int) -> List[AnnounceStep]:
        """타석 카메라 복귀 대기 후 N번째 타격 안내."""
        swing_sec = float(_cfg("announce_swing_sec", 1.0))
        return [
            _ann_step("", self._bat_cam_return_sec()),
            _ann_step(self._swing_announce_text(swing_ix), swing_sec),
        ]

    def _current_batter_char(self) -> str:
        if self._is_versus_match():
            if self._batting_as_p2:
                return str(self._p2_char or "")
            return str(self._p1_char or self._player_char or "")
        return str(self._p1_char or self._player_char or "")

    def _turn_announce_text(
        self, char_id: Optional[str] = None, *, as_p2: Optional[bool] = None
    ) -> str:
        cid = str(char_id or self._current_batter_char() or "").strip()
        if self.mode == MODE_NPC_VS and (as_p2 is True or (as_p2 is None and self._batting_as_p2)):
            return f"{self._opponent_display_name()} 차례!"
        label = self._char_label(cid)
        if self.mode == MODE_RECORD_2P:
            p2 = self._batting_as_p2 if as_p2 is None else bool(as_p2)
            who = "2P" if p2 else "1P"
            return f"{who} {label} 차례!"
        return f"{label} 차례!"

    def _turn_announce_step(
        self, char_id: Optional[str] = None, *, as_p2: Optional[bool] = None
    ) -> AnnounceStep:
        return _ann_step(self._turn_announce_text(char_id, as_p2=as_p2), tap=True)

    def _format_meters(self, carry_px: float) -> str:
        ppm = float(getattr(self, "_px_per_meter", _cfg("px_per_meter", 12.39)))
        meters = max(0.0, float(carry_px)) / max(0.1, ppm)
        if meters >= 100.0:
            return str(int(round(meters)))
        rounded = round(meters, 1)
        if abs(rounded - round(rounded)) < 0.05:
            return str(int(round(rounded)))
        return f"{rounded:.1f}"

    def _result_announce_text(
        self,
        carry_px: float,
        is_foul: bool,
        zone_label: str = "",
        *,
        is_home_run: bool = False,
        is_pop_foul: bool = False,
    ) -> str:
        if is_pop_foul:
            return "빗맞음!!"
        if is_home_run:
            base = "홈런!!"
            if zone_label:
                return f"{base} ({zone_label})"
            return base
        if is_foul:
            return "파울!!" if not zone_label else f"파울!! ({zone_label})"
        base = f"{self._format_meters(carry_px)} 미터!!"
        if zone_label:
            return f"{base} ({zone_label})"
        return base

    def _capture_scene_freeze(self) -> None:
        gx, gy, h = self._ball_flight_state()
        self._scene_ball_xy = (float(gx), float(gy))
        self._scene_cam_xy = (float(gx), float(gy) - float(h))
        self._scene_frozen = True
        self._cam_cmd_key = None

    def _scored_carry_px(self) -> float:
        """홈플레이트 → 첫 착지(포물선 끝) 직선 거리(px). 굴러간 뒤가 아님."""
        px, py = float(self.plate_xy[0]), float(self.plate_xy[1])
        lx, ly = float(self._land_xy[0]), float(self._land_xy[1])
        return max(0.0, math.hypot(lx - px, ly - py))

    def _clear_scene_freeze(self, *, reset_camera: bool = True) -> None:
        self._scene_frozen = False
        if reset_camera:
            self._cam_cmd_key = None

    def _play_world_zoom_value(self) -> float:
        return float(self.field.get("intro_zoom_play", _cfg("intro_zoom_play", 2.0)))

    def _clear_power_swing_fx(self, *, restore_zoom: bool = False) -> None:
        self._power_swing_fx_left = 0.0
        self._power_swing_pause_t = 0.0
        self._power_swing_zoom_active = False
        ev_mgr = getattr(self, "_ev_mgr", None)
        if ev_mgr is not None and hasattr(ev_mgr, "screen_fx_shake"):
            ev_mgr.screen_fx_shake = {"enabled": False}
        if restore_zoom:
            self._pending_world_zoom = {
                "val": self._play_world_zoom_value(),
                "duration_sec": _field_num(self.field, "power_swing_zoom_restore_sec", 0.12),
            }

    def _start_power_swing_fx(self) -> None:
        self._power_swing_zoom_active = True
        self._pending_world_zoom = {
            "val": _field_num(self.field, "power_swing_zoom_value", 4.0),
            "duration_sec": _field_num(self.field, "power_swing_zoom_in_sec", 0.12),
        }

    def _start_power_swing_release_fx(self) -> None:
        from engine import build_screen_shake_from_step

        self._power_swing_zoom_active = False
        self._power_swing_fx_left = max(0.0, _field_num(self.field, "power_swing_shake_sec", 1.0))
        ev_mgr = getattr(self, "_ev_mgr", None)
        if ev_mgr is not None and hasattr(ev_mgr, "screen_fx_shake"):
            ev_mgr.screen_fx_shake = build_screen_shake_from_step({
                "amp_px": _field_num(self.field, "power_swing_shake_amp_px", 50.0),
                "freq_hz": _field_num(self.field, "power_swing_shake_freq_hz", 16.0),
            })
        self._pending_world_zoom = {
            "val": self._play_world_zoom_value(),
            "duration_sec": _field_num(self.field, "power_swing_zoom_restore_sec", 0.12),
        }

    def _ball_motion_speed_mul(self) -> float:
        """타구 비행·튕김·굴러감 체감 속도 (1.0=기본, 0.9=10% 느림)."""
        try:
            v = float(
                _field_num(
                    self.field,
                    "ball_motion_speed_mul",
                    _cfg("ball_motion_speed_mul", 0.9),
                )
            )
        except (TypeError, ValueError):
            v = 0.9
        return max(0.05, min(4.0, v))

    def _setup_ground_motion(self, carry: float, *, fence_hit: bool) -> None:
        """착지 후 튕김·굴러감 거리·속도 — field/world_data 또는 data.py 기본값."""
        field = self.field
        carry = max(0.0, float(carry))
        max_c = max(80.0, float(self._max_carry))
        bounce_ratio = _field_num(field, "bounce_travel_carry_ratio", 0.38
        )
        roll_ratio = _field_num(field, "roll_travel_carry_ratio", 0.062
        )
        bounce_h_ratio = _field_num(field, "bounce_height_carry_ratio", 0.028
        )
        bounce_mul = _field_num(field, "bounce_duration_mul", 1.3)
        try:
            bounce_count = int(
                field.get("bounce_count", _cfg("bounce_count", 3)) or 3
            )
        except (TypeError, ValueError):
            bounce_count = 3
        self._bounce_travel_total = max(44.0, carry * bounce_ratio)
        self._roll_travel_total = max(14.0, carry * roll_ratio)
        if fence_hit:
            fence_bounce_ratio = _field_num(field, "fence_bounce_carry_ratio", 0.14
            )
            fence_h_mul = _field_num(field, "fence_bounce_height_mul", 0.55
            )
            try:
                fence_bounce_max = int(
                    field.get("fence_bounce_count_max", _cfg("fence_bounce_count_max", 2)) or 2
                )
            except (TypeError, ValueError):
                fence_bounce_max = 2
            self._bounce_travel_total = max(20.0, carry * fence_bounce_ratio)
            self._roll_travel_total = max(8.0, carry * roll_ratio * 0.22)
            self._bounce_count = max(1, min(fence_bounce_max, bounce_count))
            self._bounce_h0 = max(
                5.0,
                min(22.0, (6.0 + carry * bounce_h_ratio * fence_h_mul)),
            )
        else:
            self._bounce_count = max(1, min(5, bounce_count))
            self._bounce_h0 = max(7.0, min(36.0, 9.0 + carry * bounce_h_ratio))
        self._bounce_ix = 0
        self._bounce_t = 0.0
        base_dur = max(0.30, min(0.46, 0.26 + carry / max_c * 0.11))
        speed_mul = self._ball_motion_speed_mul()
        self._bounce_dur = max(0.24, min(0.72, base_dur * bounce_mul)) / max(
            0.05, speed_mul
        )
        self._roll_speed_max = max(
            20.0,
            _field_num(field, "roll_speed_max", 108.0),
        ) * speed_mul
        self._roll_speed_min = max(
            8.0,
            _field_num(field, "roll_speed_min", 52.0),
        ) * speed_mul
        if self._roll_speed_min > self._roll_speed_max:
            self._roll_speed_min = self._roll_speed_max * 0.45
        self._roll_speed_exp = max(
            0.15,
            min(1.2, _field_num(field, "roll_speed_exp", 0.55)),
        )

    def _roll_speed_px_s(self) -> float:
        roll_tot = max(1.0, float(self._roll_travel_total))
        roll_frac = max(0.0, min(1.0, float(self._roll_left) / roll_tot))
        exp = float(getattr(self, "_roll_speed_exp", 0.55))
        v_max = float(getattr(self, "_roll_speed_max", 108.0))
        v_min = float(getattr(self, "_roll_speed_min", 52.0))
        return v_min + (v_max - v_min) * (roll_frac ** exp)

    def _start_announce(
        self,
        steps: List[AnnounceStep],
        on_done: Optional[Callable[[], None]] = None,
        *,
        freeze_scene: bool = False,
        keep_camera: bool = False,
    ) -> None:
        self._announce_steps = list(steps)
        self._announce_on_done = on_done
        if freeze_scene:
            pass
        else:
            self._clear_scene_freeze(reset_camera=not keep_camera)
            self.field_tilt_target = float(_cfg("tilt_compressed", 0.68))
        self._announce_advance()

    def _announce_advance(self) -> None:
        if not self._announce_steps:
            self._announce_text = ""
            self._announce_is_home_run = False
            self._announce_left = 0.0
            self._announce_tap_wait = False
            cb = self._announce_on_done
            self._announce_on_done = None
            if cb is not None:
                cb()
            return
        text, dur, tap = self._announce_steps.pop(0)
        self._announce_text = str(text or "")
        self._announce_tap_wait = bool(tap and str(text or "").strip())
        # announce_is_home_run은 _schedule_after_swing에서만 설정되므로, 여기선 초기화하지 않음
        self._announce_left = 0.0 if self._announce_tap_wait else max(0.01, float(dur))
        self.state = ST_ANNOUNCE

    def _begin_match_intro(self, *, show_turn: bool = False, turn_char: str = "") -> None:
        self._start_field_intro(
            lambda: self._run_match_intro_announce(show_turn=show_turn, turn_char=turn_char)
        )

    def _run_match_intro_announce(self, *, show_turn: bool = False, turn_char: str = "") -> None:
        title_sec = float(_cfg("announce_title_sec", 2.0))
        swing_sec = float(_cfg("announce_swing_sec", 1.0))
        steps: List[AnnounceStep] = [
            _ann_step("게임 시작!!", title_sec),
        ]
        if show_turn and str(turn_char or "").strip():
            steps.append(self._turn_announce_step(turn_char, as_p2=False))
        steps.append(_ann_step(self._swing_announce_text(0), swing_sec))
        self._start_announce(steps, self._begin_player_swing)

    def _start_field_intro(self, on_done: Callable[[], None]) -> None:
        if not bool(_cfg("intro_field_tour_enabled", True)):
            on_done()
            return
        if not self._intro_pan_points:
            on_done()
            return
        self.state = ST_FIELD_INTRO
        self._intro_on_done = on_done
        self._cam_cmd_key = None
        self._intro_pan_ix = 0
        zoom_dur = float(_cfg("intro_zoom_dur_sec", _cfg("intro_zoom_dur_sec", 0.55)))
        hold = float(_cfg("intro_hold_sec", 0.65))
        wide = float(self.field.get("intro_zoom_wide", _cfg("intro_zoom_wide", 0.5)))
        try:
            flat_tilt = float(_cfg("intro_tilt_flat", 1.0))
        except (TypeError, ValueError):
            flat_tilt = 1.0
        self.field_tilt_target = max(0.0, min(1.0, flat_tilt))
        self._intro_phase = "wide_hold"
        self._intro_t = zoom_dur + hold
        self._intro_elapsed = 0.0
        self._pending_world_zoom = {
            "val": wide,
            "duration_sec": zoom_dur,
        }
        self._set_intro_camera_point(0, smooth=False)

    def _set_intro_camera_point(self, index: int, *, smooth: bool = True) -> None:
        pts = self._intro_pan_points
        if not pts:
            return
        ix = max(0, min(len(pts) - 1, int(index)))
        x, y = pts[ix]
        dur = float(_cfg("intro_pan_dur_sec", 0.9)) if smooth else 0.0
        self._push_camera_command(
            ("intro", "pt", ix, bool(smooth)),
            {
                "mode": "fixed",
                "x": float(x),
                "y": float(y),
                "smooth": bool(smooth),
                "duration_sec": dur,
            },
        )

    def _tick_field_intro(self, dt_sec: float) -> None:
        self._intro_t -= max(0.0, float(dt_sec))
        self._intro_elapsed += max(0.0, float(dt_sec))
        if self._intro_t > 0.0:
            return
        pan_dur = float(_cfg("intro_pan_dur_sec", 0.9))
        hold = float(_cfg("intro_hold_sec", 0.65))
        last_ix = max(0, len(self._intro_pan_points) - 1)

        if self._intro_phase == "wide_hold":
            self._intro_phase = "hold"
            self._intro_t = hold
        elif self._intro_phase == "hold":
            if self._intro_pan_ix < last_ix:
                self._intro_pan_ix += 1
                self._set_intro_camera_point(self._intro_pan_ix, smooth=True)
                self._intro_phase = "pan"
                self._intro_t = pan_dur
            else:
                self._intro_phase = ""
                cb = self._intro_on_done
                self._intro_on_done = None
                self._finish_field_intro_camera()
                if cb is not None:
                    cb()
        elif self._intro_phase == "pan":
            self._intro_phase = "hold"
            self._intro_t = hold

    def _start_2p_switch_fade(self) -> None:
        """타자 교체 페이드 — `_switch_batter_to_p2` 로 1P↔2P 방향 지정."""
        self._clear_scene_freeze(reset_camera=True)
        self._clear_power_swing_fx()
        self._show_rest_ball()
        self._reset_fielders()
        self._return_to_plate_camera(smooth=False)
        self.field_tilt_target = float(_cfg("tilt_compressed", 0.68))
        self.state = ST_TURN_WAIT
        self._msg = ""
        self._p2_switch_fade_phase = "out"
        self._p2_switch_fade_dur = max(0.01, _field_num(self.field, "p2_switch_fade_out_sec", 0.25))
        self._p2_switch_fade_t = self._p2_switch_fade_dur
        self._p2_switch_fade_alpha = 0

    def _tick_2p_switch_fade(self, dt_sec: float) -> None:
        if not self._p2_switch_fade_phase:
            return
        self._p2_switch_fade_t = max(0.0, self._p2_switch_fade_t - float(dt_sec))
        dur = max(0.01, float(self._p2_switch_fade_dur))
        left = float(self._p2_switch_fade_t)
        if self._p2_switch_fade_phase == "out":
            self._p2_switch_fade_alpha = int(round(255.0 * (1.0 - left / dur)))
            if left <= 0.0:
                self._batting_as_p2 = bool(getattr(self, "_switch_batter_to_p2", True))
                # 모아서 하기: 1P 전부 끝난 뒤 2P 이닝 시작 시에만 타석 카운터 리셋
                if self._is_duo_batch() and self._batting_as_p2:
                    self._swing_ix = 0
                char = (
                    self._p2_char
                    if self._batting_as_p2
                    else (self._p1_char or self._player_char)
                )
                self._apply_batter_char(char)
                hold = max(0.0, _field_num(self.field, "p2_switch_fade_hold_sec", 0.08))
                if hold > 0.0:
                    self._p2_switch_fade_phase = "hold"
                    self._p2_switch_fade_dur = hold
                    self._p2_switch_fade_t = hold
                    self._p2_switch_fade_alpha = 255
                else:
                    self._p2_switch_fade_phase = "in"
                    self._p2_switch_fade_dur = max(0.01, _field_num(self.field, "p2_switch_fade_in_sec", 0.25))
                    self._p2_switch_fade_t = self._p2_switch_fade_dur
        elif self._p2_switch_fade_phase == "hold":
            self._p2_switch_fade_alpha = 255
            if left <= 0.0:
                self._p2_switch_fade_phase = "in"
                self._p2_switch_fade_dur = max(0.01, _field_num(self.field, "p2_switch_fade_in_sec", 0.25))
                self._p2_switch_fade_t = self._p2_switch_fade_dur
        else:
            self._p2_switch_fade_alpha = int(round(255.0 * (left / dur)))
            if left <= 0.0:
                self._p2_switch_fade_phase = ""
                self._p2_switch_fade_alpha = 0
                self._run_2p_turn_announce_after_switch()

    def _run_2p_turn_announce_after_switch(self) -> None:
        swing_sec = float(_cfg("announce_swing_sec", 1.0))
        char = (
            self._p2_char
            if self._batting_as_p2
            else (self._p1_char or self._player_char)
        )
        self._start_announce(
            [
                self._turn_announce_step(char, as_p2=self._batting_as_p2),
                _ann_step(self._swing_announce_text(self._swing_ix), swing_sec),
            ],
            self._begin_player_swing,
        )

    def _switch_to_2p_batting(self) -> None:
        """모아서 하기 — 1P 이닝 종료 후 2P 이닝으로."""
        self._switch_batter_to_p2 = True
        self._start_2p_switch_fade()

    def _switch_alt_to_p2(self) -> None:
        """번갈아 하기 — 이번 라운드 2P 타석."""
        self._switch_batter_to_p2 = True
        self._start_2p_switch_fade()

    def _switch_alt_to_p1(self) -> None:
        """번갈아 하기 — 다음 라운드 1P 타석."""
        self._switch_batter_to_p2 = False
        self._start_2p_switch_fade()

    def _award_alt_round_point(self) -> str:
        """방금 끝난 라운드 비거리 비교 → 승점 1. 동점이면 점수 없음."""
        ix = min(len(self._p1_dists), len(self._p2_dists)) - 1
        if ix < 0:
            return ""
        d1 = float(self._p1_dists[ix])
        d2 = float(self._p2_dists[ix])
        p1_name = self._char_label(self._p1_char or self._player_char)
        p2_name = self._opponent_display_name()
        if d1 > d2:
            self._p1_pts += 1
            return f"{p1_name} 1점!"
        if d2 > d1:
            self._p2_pts += 1
            return f"{p2_name} 1점!"
        return "동점!"

    def _schedule_after_swing(
        self,
        was_foul: bool,
        carry_px: float,
        *,
        zone_label: str = "",
        is_home_run: bool = False,
        is_pop_foul: bool = False,
    ) -> None:
        result_sec = float(_cfg("announce_result_sec", 2.0))
        pause_sec = float(_cfg("announce_pause_sec", 1.0))
        swing_sec = float(_cfg("announce_swing_sec", 1.0))
        turn_sec = float(_cfg("announce_turn_sec", 2.0))
        end_sec = float(_cfg("announce_match_end_sec", 2.0))
        self._announce_is_home_run = is_home_run
        result_step = _ann_step(
            self._result_announce_text(
                carry_px,
                was_foul,
                zone_label,
                is_home_run=is_home_run,
                is_pop_foul=is_pop_foul,
            ),
            result_sec,
        )

        def _start_next_at_plate(
            next_steps: List[AnnounceStep],
            on_done: Optional[Callable[[], None]],
        ) -> None:
            """결과는 타구 위치에서 보여주고, 빈 대기 동안 타격 장소로 복귀한 뒤 다음 안내."""
            def _return_then_announce() -> None:
                self._clear_scene_freeze(reset_camera=True)
                self._show_rest_ball()
                self.field_tilt_target = float(_cfg("tilt_compressed", 0.68))
                self._return_to_plate_camera(smooth=True)
                self._start_announce(next_steps, on_done, keep_camera=True)

            self._start_announce([result_step], _return_then_announce, freeze_scene=True)

        def _start_match_result_at_plate(on_done: Optional[Callable[[], None]]) -> None:
            cam_sec = self._bat_cam_return_sec()
            _start_next_at_plate(
                [
                    _ann_step("", cam_sec),
                    _ann_step("", pause_sec),
                    _ann_step("경기 결과!!", end_sec),
                ],
                on_done,
            )

        def _next_swing_steps(swing_ix: int) -> List[AnnounceStep]:
            return self._plate_return_swing_steps(swing_ix)

        if self.mode == MODE_DEMO:
            if self._swing_ix >= self._swings_per_side:
                _start_match_result_at_plate(self._finish_demo)
            else:
                _start_next_at_plate(
                    self._plate_return_swing_steps(self._swing_ix),
                    self._begin_player_swing,
                )
            return

        if self.mode == MODE_RECORD_1P:
            if self._swing_ix >= self._swings_per_side:
                _start_match_result_at_plate(self._finish_1p_solo)
            else:
                _start_next_at_plate(
                    _next_swing_steps(self._swing_ix),
                    self._begin_player_swing,
                )
            return

        # --- 번갈아 (2P / NPC): 한 타씩 주고받기 → 비거리 승점 ---
        if self._is_alternate_play():
            if not self._batting_as_p2:
                # 1P 타석 종료 → 상대(2P 또는 NPC) 타석 — 페이드 후 타격 연출
                _start_next_at_plate(
                    [
                        _ann_step("", self._bat_cam_return_sec()),
                        _ann_step("", pause_sec),
                    ],
                    self._switch_alt_to_p2,
                )
            else:
                # 상대 타석 종료 → 승점 안내 후 다음 라운드 또는 결과
                point_txt = self._award_alt_round_point()
                self._swing_ix += 1
                point_step = _ann_step(point_txt or "동점!", turn_sec)
                if self._swing_ix >= self._swings_per_side:
                    _start_next_at_plate(
                        [
                            point_step,
                            _ann_step("", self._bat_cam_return_sec()),
                            _ann_step("", pause_sec),
                            _ann_step("경기 결과!!", end_sec),
                        ],
                        self._finish_alt_match,
                    )
                else:
                    _start_next_at_plate(
                        [
                            point_step,
                            _ann_step("", self._bat_cam_return_sec()),
                            _ann_step("", pause_sec),
                        ],
                        self._switch_alt_to_p1,
                    )
            return

        if self.mode == MODE_RECORD_2P:
            # 모아서 하기 — 각자 횟수만큼 전부
            if self._swing_ix >= self._swings_per_side:
                if not self._batting_as_p2:
                    _start_next_at_plate(
                        [
                            _ann_step("", self._bat_cam_return_sec()),
                            _ann_step("", pause_sec),
                        ],
                        self._switch_to_2p_batting,
                    )
                else:
                    _start_match_result_at_plate(self._finish_match)
            else:
                _start_next_at_plate(
                    _next_swing_steps(self._swing_ix),
                    self._begin_player_swing,
                )
            return

        if self.mode == MODE_STORY:
            if self._swing_ix >= self._swings_per_side:
                npc = str(self._npc_name or "NPC").strip()
                _start_next_at_plate(
                    [
                        _ann_step("", self._bat_cam_return_sec()),
                        _ann_step("", pause_sec),
                        _ann_step(f"{npc} 순서", turn_sec),
                    ],
                    self._run_npc_swings,
                )
            else:
                _start_next_at_plate(
                    self._plate_return_swing_steps(self._swing_ix),
                    self._begin_player_swing,
                )
            return

        _start_next_at_plate(
            self._plate_return_swing_steps(self._swing_ix),
            self._begin_player_swing,
        )

    # ------------------------------------------------------------------ match flow

    def _start_solo_match(self) -> None:
        """기록 갱신 — 캐릭터 선택 후 N타 (NPC 없음)."""
        self.mode = MODE_RECORD_1P
        self._play_style = PLAY_SOLO_RECORD
        self._p1_dists = []
        self._p1_hr = 0
        self._p1_pts = 0
        self._p2_pts = 0
        self._swing_ix = 0
        self._batting_as_p2 = False
        self._won = False
        self._save_patch = {}
        self._apply_batter_char(self._p1_char or self._player_char)
        self._show_rest_ball()
        self._begin_match_intro(
            show_turn=True, turn_char=self._p1_char or self._player_char
        )

    def _start_npc_alt_match(self) -> None:
        """NPC와 하기 — 플레이어↔NPC 번갈아 타격·승점 (NPC도 스윙·비행 연출)."""
        self.mode = MODE_NPC_VS
        self._play_style = PLAY_NPC_ALT
        self._p1_dists = []
        self._p2_dists = []
        self._npc_dists = []
        self._p1_hr = 0
        self._p2_hr = 0
        self._p1_pts = 0
        self._p2_pts = 0
        self._swing_ix = 0
        self._batting_as_p2 = False
        self._won = False
        self._save_patch = {}
        if self._p2_char:
            self._npc_name = self._char_label(self._p2_char)
        self._apply_batter_char(self._p1_char or self._player_char)
        self._show_rest_ball()
        self._begin_match_intro(
            show_turn=True, turn_char=self._p1_char or self._player_char
        )

    def _start_story_match(self) -> None:
        self._p1_dists = []
        self._npc_dists = []
        self._swing_ix = 0
        self._batting_as_p2 = False
        self._won = False
        self._save_patch = {}
        self._show_rest_ball()
        self._begin_match_intro(show_turn=False)

    def _start_match_2p(self) -> None:
        """2인 — 1P·2P 캐릭터 확정 후 시작. `_play_style` 이 alt/batch 를 가름."""
        self.mode = MODE_RECORD_2P
        if self._play_style not in (PLAY_DUO_ALT, PLAY_DUO_BATCH):
            self._play_style = PLAY_DUO_BATCH
        self._p1_dists = []
        self._p2_dists = []
        self._p1_hr = 0
        self._p2_hr = 0
        self._p1_pts = 0
        self._p2_pts = 0
        self._swing_ix = 0
        self._batting_as_p2 = False
        self._won = False
        self._save_patch = {}
        self._apply_batter_char(self._p1_char)
        self._show_rest_ball()
        self._begin_match_intro(show_turn=True, turn_char=self._p1_char)

    def _start_match(self) -> None:
        self._start_match_2p()

    def _gauge_time_limit_sec(self) -> float:
        return max(
            0.1,
            float(
                _field_num(
                    self.field,
                    "gauge_time_limit_sec",
                    _cfg("gauge_time_limit_sec", 5.0),
                )
            ),
        )

    def _gauge_sweep_speed_mul(self) -> float:
        """제한시간 경과에 따라 게이지 스윕 속도 선형 가속 (시작 1.0 → 종료 end_mul)."""
        lim = max(0.1, float(getattr(self, "_gauge_time_limit", 0.0) or 0.0))
        if lim <= 0.0:
            lim = self._gauge_time_limit_sec()
        left = max(0.0, float(self._gauge_time_left))
        progress = max(0.0, min(1.0, 1.0 - left / lim))
        try:
            end_mul = float(
                _field_num(
                    self.field,
                    "gauge_sweep_end_speed_mul",
                    _cfg("gauge_sweep_end_speed_mul", 1.5),
                )
            )
        except (TypeError, ValueError):
            end_mul = 1.5
        end_mul = max(1.0, min(3.0, end_mul))
        return 1.0 + (end_mul - 1.0) * progress

    def _reset_gauge_timer(self) -> None:
        lim = self._gauge_time_limit_sec()
        self._gauge_time_limit = lim
        self._gauge_time_left = lim

    def _begin_player_swing(self, *, reset_camera: bool = False) -> None:
        # NPC 타석이면 자동 타격 연출로
        if self.mode == MODE_NPC_VS and self._batting_as_p2:
            self._begin_npc_auto_swing(reset_camera=reset_camera)
            return
        self._clear_scene_freeze(reset_camera=reset_camera)
        self._clear_power_swing_fx()
        self._show_rest_ball()
        self._reset_fielders()
        self._is_pop_foul = False
        self._turn_is_player = True
        self.state = ST_BAT_DIR
        self._dir_phase = self._rng.uniform(0.0, math.pi * 2.0)
        self._reset_gauge_timer()
        if self.mode == MODE_DEMO:
            self._msg = f"타격 {self._swing_ix + 1}/{self._swings_per_side} — 공을 터치!"
        else:
            who = "2P" if self._batting_as_p2 else "1P"
            self._msg = f"{who} 타격 {self._swing_ix + 1}/{self._swings_per_side} — 화면 터치!"
        self._update_batter_facing_from_gauge()
        self.field_tilt_target = float(_cfg("tilt_compressed", 0.68))
        pl = self._player_ref
        if pl is not None:
            _sync_baseball_overlay_idle(pl, self._batter_overlay_char())

    def _begin_npc_auto_swing(self, *, reset_camera: bool = False) -> None:
        """NPC 타석 — AI가 비거리 밴드를 고르고 스윙·비행 연출까지 진행."""
        self._clear_scene_freeze(reset_camera=reset_camera)
        self._clear_power_swing_fx()
        self._show_rest_ball()
        self._reset_fielders()
        self._is_pop_foul = False
        self._turn_is_player = False
        self._batting_as_p2 = True
        self._apply_batter_char(self._p2_char)
        self.field_tilt_target = float(_cfg("tilt_compressed", 0.68))
        npc = self._opponent_display_name()
        self._msg = f"{npc} 타격 {self._swing_ix + 1}/{self._swings_per_side}"
        pl = self._player_ref
        if pl is not None:
            _sync_baseball_overlay_idle(pl, self._batter_overlay_char())
        plan = self._npc_ai_plan_swing()
        self._locked_dir_deg = float(plan.get("dir_deg", 0.0))
        self._locked_pwr = float(plan.get("pwr", 0.5))
        self._locked_pwr_marker_t = 0.5
        self._is_power_swing = bool(plan.get("power_swing"))
        self._update_batter_facing_from_gauge(self._locked_dir_deg)
        if bool(plan.get("pop_foul")):
            self._resolve_pop_foul_swing()
            return
        if bool(plan.get("foul")) and not bool(plan.get("pop_foul")):
            # 방향 파울 — 짧은 비행 후 파울 판정
            self._flight_angle_deg = float(self._locked_dir_deg)
            self._carry_px = float(plan.get("carry_px") or _cfg("foul_carry_px", 20.0))
            self._is_foul = True
            self._is_pop_foul = False
            self._fence_hit = False
            self._ground_fence_bounced = False
            self._planned_home_run = False
            self._power_swing_pause_t = max(
                0.25, float(_field_num(self.field, "normal_swing_pause_sec", 0.5))
            )
            self.state = ST_SWING_PAUSE
            return
        # 페어 타구 — AI 목표 비거리로 비행
        self._flight_angle_deg = self._resolve_swing_angle(
            float(self._locked_dir_deg), float(self._locked_pwr)
        )
        self._carry_px = float(plan.get("carry_px") or 0.0)
        self._is_foul = False
        self._is_pop_foul = False
        self._fence_hit = False
        self._ground_fence_bounced = False
        self._planned_home_run = False
        if pl is not None:
            _freeze_baseball_batter_pose(pl, self._batter_overlay_char())
        if self._is_power_swing:
            self._start_power_swing_fx()
            self._power_swing_pause_t = max(
                0.0, _field_num(self.field, "power_swing_pause_sec", 1.5)
            )
            self.state = ST_POWER_SWING_PAUSE
            return
        self._power_swing_pause_t = max(
            0.25, _field_num(self.field, "normal_swing_pause_sec", 0.5)
        )
        self.state = ST_SWING_PAUSE

    def _begin_pwr_phase(self) -> None:
        self.state = ST_BAT_PWR
        self._pwr_phase = self._rng.uniform(0.0, math.pi * 2.0)
        self._reset_gauge_timer()
        self._msg = "파워 — 공을 터치!"
        self._update_batter_facing_from_gauge(self._locked_dir_deg)

    def _resolve_player_swing(self) -> None:
        # 파워 확인 상태로 넘어가기
        self._locked_pwr_marker_t = self._pwr_marker_t()
        self._pwr_confirm_hold_t = self._pwr_confirm_hold_sec
        self._is_power_swing = self._pwr_in_power_sweet_spot(self._locked_pwr_marker_t)
        self.state = ST_PWR_CONFIRM
        
    def _start_locked_swing_animation(self) -> None:
        pl = self._player_ref
        if pl is not None:
            _sync_baseball_overlay_swing(pl, self._batter_overlay_char())
        self.state = ST_SWING
        self._swing_t = max(0.05, _field_num(self.field, "swing_anim_base_sec", 0.45)) / max(0.01, float(self._swing_speed_mul))
        self.field_tilt_target = 1.0

    def _actual_swing_after_confirm(self) -> None:
        if self._pwr_in_trap_zone(self._locked_pwr_marker_t):
            self._resolve_pop_foul_swing()
            return
        locked_dir = float(self._locked_dir_deg)
        locked_pwr = max(0.0, min(1.0, float(self._locked_pwr)))
        self._flight_angle_deg = self._resolve_swing_angle(locked_dir, locked_pwr)
        self._carry_px = self._carry_from_locked_swing(locked_dir, locked_pwr)
        self._is_foul = False
        self._is_pop_foul = False
        self._fence_hit = False
        self._ground_fence_bounced = False
        self._planned_home_run = False
        pl = self._player_ref
        if pl is not None:
            _freeze_baseball_batter_pose(pl, self._batter_overlay_char())
        if self._is_power_swing:
            self._start_power_swing_fx()
            self._power_swing_pause_t = max(0.0, _field_num(self.field, "power_swing_pause_sec", 1.5))
            self.state = ST_POWER_SWING_PAUSE
            return
        self._power_swing_pause_t = max(0.0, _field_num(self.field, "normal_swing_pause_sec", 0.5))
        self.state = ST_SWING_PAUSE

    def _resolve_pop_foul_swing(self) -> None:
        """파워 게이지 1/3·2/3 함정 — 빗맞아 머리 뒤로 짧게 뜨는 파울."""
        pl = self._player_ref
        if pl is not None:
            _sync_baseball_overlay_swing(pl, self._batter_overlay_char())
        base_ang = float(
            _field_num(self.field, "pop_foul_angle_deg", 180.0)
        )
        spread = float(
            _field_num(self.field, "pop_foul_angle_spread_deg", 12.0,
            )
        )
        self._flight_angle_deg = base_ang + self._rng.uniform(-spread, spread)
        self._carry_px = float(
            _field_num(self.field, "pop_foul_carry_px", 58.0)
        )
        self._is_foul = True
        self._is_pop_foul = True
        self._fence_hit = False
        self._ground_fence_bounced = False
        self._planned_home_run = False
        self.state = ST_SWING
        self._swing_t = 0.38
        self.field_tilt_target = 1.0

    def _start_pop_foul_flight(self) -> None:
        carry = max(8.0, float(self._carry_px))
        self._carry_px = carry
        self._land_xy = self._land_xy_from_angle_carry(
            float(self._flight_angle_deg), carry
        )
        self._is_foul = True
        self._fence_hit = False
        self._planned_home_run = False
        self._ground_roll_angle_deg = float(self._flight_angle_deg)
        pop_h = float(
            _field_num(self.field, "pop_foul_height_px", 36.0)
        )
        self._ball_h_max = max(14.0, min(48.0, pop_h))
        dur_override = float(
            _field_num(self.field, "pop_foul_flight_dur_sec", 0.0,
            )
        )
        if dur_override > 0.0:
            self._flight_dur = max(0.45, dur_override)
        else:
            # 일반 파울과 비슷한 체감 — 짧은 거리라도 너무 빠르지 않게
            self._flight_dur = max(
                0.78,
                min(1.18, 0.56 + carry / 125.0 + math.sqrt(self._ball_h_max) / 28.0),
            )
        self._flight_dur /= max(0.05, self._ball_motion_speed_mul())
        self._roll_xy = [float(self._land_xy[0]), float(self._land_xy[1])]
        self._roll_left = 0.0
        self._bounce_travel_total = 0.0
        self._roll_travel_total = 0.0
        self._bounce_ix = 0
        self._bounce_t = 0.0
        self._flight_sub = "arc"

    def _start_flight(self) -> None:
        self.state = ST_FLIGHT
        self._cam_cmd_key = None
        self._reset_fielder_chase_state()
        self._ground_fence_bounced = False
        self._flight_t = 0.0
        self._flight_sub = "arc"
        self._hide_rest_ball()

        if self._power_swing_zoom_active:
            self._start_power_swing_release_fx()

        if self._is_pop_foul:
            self._start_pop_foul_flight()
            return
        carry = float(self._carry_px)
        fair_h = max(
            24.0,
            min(270.0, (36.0 + carry * 0.18) * float(self._height_mul)),
        )
        ox, oy = float(self.ball_rest_xy[0]), float(self.ball_rest_xy[1])
        plan = resolve_flight_landing(
            ox,
            oy,
            float(self._flight_angle_deg),
            carry,
            fair_h,
            self._mask_surf,
            cfg=self.field,
            fence_clear_height_px=float(_cfg("fence_clear_height_px", 18.0)),
            trace_step_px=float(_cfg("fence_trace_step_px", 4.0)),
        )
        self._carry_px = float(plan["carry_px"])
        self._land_xy = (float(plan["land_xy"][0]), float(plan["land_xy"][1]))
        self._is_foul = bool(plan["is_foul"])
        self._fence_hit = bool(plan["fence_hit"])
        self._planned_home_run = bool(plan["is_home_run"])
        self._ground_roll_angle_deg = float(plan["ground_angle_deg"])
        # 파울도 착지 마스크 판정만 다르고, 비행 높이·시간·비거리는 일반 타구와 동일
        self._flight_dur = max(
            0.9,
            min(2.8, 0.7 + float(self._carry_px) / max(80.0, self._max_carry) * 1.6),
        )
        self._flight_dur /= max(0.05, self._ball_motion_speed_mul())
        self._ball_h_max = fair_h
        self._roll_xy = [float(self._land_xy[0]), float(self._land_xy[1])]
        self._roll_left = 0.0
        self._setup_ground_motion(float(self._carry_px), fence_hit=bool(self._fence_hit))
        gx, gy, _h = self._ball_flight_state()
        self._chase_fielders(gx, gy)
        self._fielder_chase_t = float(_cfg("fielder_chase_repath_sec", 0.12))

    def _end_player_swing(self) -> None:
        was_foul = bool(self._is_foul)
        was_pop = bool(self._is_pop_foul)
        if self._ball_item is not None and not self._ball_held_by_catcher():
            self._ball_item.is_visible = False
        if self._ball_caught:
            # 안내 연출 중에도 남은 추격 NPC 가 계속 모여들지 않게 즉시 정지
            for n in self._fielders:
                if n is self._ball_catcher:
                    continue
                if id(n) not in self._active_chasers:
                    continue
                try:
                    n.stop_moving()
                    n.event_speed_mul = 1.0
                except Exception:
                    pass
            self._active_chasers = set()
        # 비거리는 첫 착지(_land_xy) 직선거리 — 굴러간 뒤가 아님
        land_x, land_y = float(self._land_xy[0]), float(self._land_xy[1])
        carry_px = 0.0 if was_foul else self._scored_carry_px()
        self._capture_scene_freeze()
        zone_label = ""
        if self._zone_objs and carry_px > 0.0:
            zone_x, zone_y = self._ball_ground_pos()
            carry_px, was_foul, zone_label = resolve_landing_zone(
                zone_x,
                zone_y,
                self._zone_objs,
                carry_px,
                was_foul,
                px_per_meter=float(getattr(self, "_px_per_meter", _cfg("px_per_meter", 7.2))),
            )
        is_home_run = False
        if not was_foul and (
            bool(getattr(self, "_planned_home_run", False))
            or self._landing_mask_class(land_x, land_y) == "home_run"
        ):
            is_home_run = True
            if self._batting_as_p2:
                self._p2_hr += 1
            else:
                self._p1_hr += 1
        self._last_zone_label = zone_label
        if was_foul:
            carry_px = 0.0
        if self._batting_as_p2:
            self._p2_dists.append(carry_px)
        else:
            self._p1_dists.append(carry_px)
        # 번갈아 모드는 양쪽 타석이 끝난 뒤 `_schedule_after_swing` 에서 라운드 카운트
        if not self._is_alternate_play():
            self._swing_ix += 1
        disp_ix = int(self._swing_ix) + (1 if self._is_alternate_play() else 0)
        who = "2P" if self._batting_as_p2 else "1P"
        if self.mode == MODE_NPC_VS and self._batting_as_p2:
            who = self._opponent_display_name()
        if was_pop:
            self._msg = f"{who} — 빗맞음 ({disp_ix}/{self._swings_per_side})"
        elif was_foul:
            self._msg = f"{who} — 파울 ({disp_ix}/{self._swings_per_side})"
        elif is_home_run:
            zm = f" [{zone_label}]" if zone_label else ""
            self._msg = (
                f"{who} — 홈런!!{zm} ({disp_ix}/{self._swings_per_side})"
            )
        else:
            zm = f" [{zone_label}]" if zone_label else ""
            self._msg = (
                f"{who} — {self._format_meters(carry_px)}m{zm} "
                f"({disp_ix}/{self._swings_per_side})"
            )
        self._schedule_after_swing(
            was_foul,
            carry_px,
            zone_label=zone_label,
            is_home_run=is_home_run,
            is_pop_foul=was_pop,
        )
        self._is_pop_foul = False

    def _arcade_records(self) -> List[Dict[str, Any]]:
        try:
            from flow import append_baseball_record, baseball_record_history

            hist = baseball_record_history()
        except Exception:
            hist = []
        rows = [r for r in hist if isinstance(r, dict)]
        rows.sort(key=lambda r: int(r.get("score", r.get("player", 0)) or 0), reverse=True)
        return rows[:10]

    def _finish_1p_solo(self) -> None:
        self._clear_scene_freeze()
        self._show_rest_ball()
        p_tot = self._total_score_m(self._p1_dists)
        tags = []
        for d in self._p1_dists:
            tags.append("파울" if float(d) <= 0.0 else f"{self._format_meters(d)}m")
        self._hud_lines = [
            f"캐릭터: {self._p1_char or self._player_char}",
            f"홈런: {int(self._p1_hr)}",
            f"타격: {', '.join(tags) if tags else '-'}",
            f"거리 합: {int(round(p_tot))}m",
        ]
        entry = {
            "mode": MODE_RECORD_1P,
            "char": str(self._p1_char or self._player_char),
            "score": int(round(p_tot)),
            "player": int(round(p_tot)),
            "distances": [
                int(round(self._carry_px_to_meters(d)))
                for d in self._p1_dists
                if float(d) > 0.0
            ],
        }
        try:
            from flow import append_baseball_record

            ranked = append_baseball_record(entry)
        except Exception:
            ranked = sorted([entry], key=lambda r: int(r.get("score", 0) or 0), reverse=True)
        self._leaderboard_highlight = -1
        for i, row in enumerate(ranked[:10]):
            if row is entry or (
                int(row.get("score", 0) or 0) == int(entry["score"])
                and str(row.get("char", "")) == str(entry["char"])
                and row.get("distances") == entry.get("distances")
            ):
                self._leaderboard_highlight = i
                break
        self.state = ST_LEADERBOARD
        self.field_tilt_target = 1.0
        self._msg = "기록 갱신!"
        self._sync_camera()

    def _return_to_main_menu(self) -> None:
        self.state = ST_MENU
        self._msg = "메뉴 — 항목을 누르세요"
        self._finish_hold = 0.0
        lw, lh = self._logical_screen_size()
        self._layout_menu_rects(lw, lh)
        self._show_rest_ball()
        self._sync_camera()

    def _normalize_difficulty_id(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        valid = {key for key, _label in BASEBALL_DIFFICULTY_OPTIONS}
        return raw if raw in valid else BASEBALL_DIFFICULTY_DEFAULT

    def _difficulty_label(self, difficulty_id: Optional[str] = None) -> str:
        did = self._normalize_difficulty_id(
            self._difficulty_id if difficulty_id is None else difficulty_id
        )
        for key, label in BASEBALL_DIFFICULTY_OPTIONS:
            if key == did:
                return label
        return BASEBALL_DIFFICULTY_OPTIONS[0][1]

    def _difficulty_balance_value(
        self,
        suffix: str,
        *,
        easy: float,
        normal: float,
        hard: float,
    ) -> float:
        did = self._normalize_difficulty_id(self._difficulty_id)
        fallback = {
            "easy": float(easy),
            "normal": float(normal),
            "hard": float(hard),
        }.get(did, float(normal))
        try:
            return float(_cfg(f"difficulty_{did}_{suffix}", fallback))
        except (TypeError, ValueError):
            return float(fallback)

    def _difficulty_dir_speed_mul(self) -> float:
        return self._difficulty_balance_value(
            "dir_speed_mul", easy=0.9, normal=1.0, hard=1.1
        )

    def _difficulty_pwr_speed_mul(self) -> float:
        return self._difficulty_balance_value(
            "pwr_speed_mul", easy=0.85, normal=1.0, hard=1.15
        )

    def _difficulty_sweet_width_mul(self) -> float:
        return self._difficulty_balance_value(
            "sweet_width_mul", easy=1.2, normal=1.0, hard=0.85
        )

    def _difficulty_power_sweet_width_mul(self) -> float:
        return self._difficulty_balance_value(
            "power_sweet_width_mul", easy=1.15, normal=1.0, hard=0.8
        )

    def _difficulty_trap_width_mul(self) -> float:
        return self._difficulty_balance_value(
            "trap_width_mul", easy=0.8, normal=1.0, hard=1.2
        )

    def _apply_difficulty_balance(self) -> None:
        base_dir_speed = float(
            self.field.get("dir_sweep_hz", _cfg("dir_sweep_hz", 1.35))
        )
        base_pwr_speed = float(
            self.field.get("pwr_sweep_hz", _cfg("pwr_sweep_hz", 0.95))
        )
        self._dir_speed = base_dir_speed * self._difficulty_dir_speed_mul()
        self._pwr_speed = base_pwr_speed * self._difficulty_pwr_speed_mul()

    def _run_npc_swings(self) -> None:
        """스토리 모드 — NPC N타석 일괄 시뮬 (짧은 연출 후 결과)."""
        self._clear_scene_freeze()
        self._show_rest_ball()
        self._npc_dists = []
        for _ in range(self._swings_per_side):
            self._npc_dists.append(self._simulate_npc_distance())
        self.state = ST_NPC_SHOW
        self._npc_flash_ix = 0
        self._npc_flash_t = float(_cfg("npc_flash_sec", 0.55))
        self._npc_flash_dist = float(self._npc_dists[0] if self._npc_dists else 0.0)

    def _simulate_npc_distance(self, skill: float = -1.0) -> float:
        """스토리/폴백용 — 밴드 AI로 비거리(px)만 산출 (연출 없음)."""
        del skill  # 밴드 가중치가 난이도를 반영
        plan = self._npc_ai_plan_swing()
        if bool(plan.get("foul")) or bool(plan.get("pop_foul")):
            return 0.0
        dir_deg = float(plan.get("dir_deg", 0.0))
        carry = float(plan.get("carry_px", 0.0))
        actual = self._resolve_swing_angle(dir_deg, float(plan.get("pwr", 0.5)))
        ox, oy = float(self.ball_rest_xy[0]), float(self.ball_rest_xy[1])
        ball_h = max(
            24.0,
            min(270.0, (36.0 + float(carry) * 0.18) * float(self._height_mul)),
        )
        land_plan = resolve_flight_landing(
            ox,
            oy,
            float(actual),
            float(carry),
            ball_h,
            self._mask_surf,
            cfg=self.field,
            fence_clear_height_px=float(_cfg("fence_clear_height_px", 18.0)),
            trace_step_px=float(_cfg("fence_trace_step_px", 4.0)),
        )
        if bool(land_plan.get("is_foul")):
            return 0.0
        lx, ly = land_plan["land_xy"]
        px, py = float(self.plate_xy[0]), float(self.plate_xy[1])
        return max(0.0, math.hypot(float(lx) - px, float(ly) - py))

    def _ground_dist_blocked_by_fence(self, dist_along: float) -> bool:
        if self._mask_surf is None or float(dist_along) <= 1e-3:
            return False
        rad = math.radians(float(self._ground_roll_angle_deg))
        gx = float(self._land_xy[0]) + math.cos(rad) * float(dist_along)
        gy = float(self._land_xy[1]) + math.sin(rad) * float(dist_along)
        cls = classify_mask_landing(gx, gy, self._mask_surf, cfg=self.field)
        if cls == "foul":
            return True
        if cls == "fence":
            if bool(getattr(self, "_fence_hit", False)):
                bounce_cap = max(20.0, float(self._bounce_travel_total) * 0.95)
                return float(dist_along) > bounce_cap
            return True
        return False

    def _handle_ground_fence_hit(self, dist_along: float) -> bool:
        """굴러가다 펜스에 닿으면 짧게 튕겨 되돌아옴 (직격 펜스 타구와 유사)."""
        if bool(getattr(self, "_ground_fence_bounced", False)):
            return False
        rad = math.radians(float(self._ground_roll_angle_deg))
        contact_x = float(self._land_xy[0]) + math.cos(rad) * float(dist_along)
        contact_y = float(self._land_xy[1]) + math.sin(rad) * float(dist_along)
        step = max(2.0, float(_cfg("fence_trace_step_px", 4.0)))
        if self._mask_surf is not None:
            pt, land_dist = _last_infield_before_fence(
                float(self._land_xy[0]),
                float(self._land_xy[1]),
                float(self._ground_roll_angle_deg),
                float(dist_along),
                self._mask_surf,
                cfg=self.field,
                step_px=step,
            )
            if land_dist > 1e-3:
                contact_x, contact_y = float(pt[0]), float(pt[1])
        self._land_xy = (float(contact_x), float(contact_y))
        self._ground_fence_bounced = True
        self._fence_hit = True
        self._ground_roll_angle_deg = float(self._ground_roll_angle_deg) + 180.0
        carry_to_fence = max(8.0, float(dist_along))
        self._setup_ground_motion(carry_to_fence, fence_hit=True)
        self._flight_sub = "bounce"
        self._bounce_ix = 0
        self._bounce_t = 0.0
        self._roll_left = float(self._roll_travel_total)
        return True

    def _finish_match(self) -> None:
        self._clear_scene_freeze()
        self._show_rest_ball()
        p_tot = self._total_score_m(self._p1_dists)
        if self.mode == MODE_STORY:
            o_tot = self._total_score_m(self._npc_dists)
            self._won = p_tot > o_tot or (p_tot == o_tot and p_tot > 0)
            self._hud_lines = [
                f"플레이어 HR {int(self._p1_hr)} / 합 {int(round(p_tot))}m",
                f"{self._npc_name} 합 {int(round(o_tot))}m",
                "승리!" if self._won else "패배…",
            ]
            if self._won and not bool(int(self._save_data.get(self._win_flag, 0) or 0)):
                self._save_patch[self._win_flag] = 1
                self._save_patch[self._seed_flag] = 1
                self._story_cleared = True
            self.state = ST_MATCH_END
            self.field_tilt_target = 1.0
            self._msg = "경기 종료"
            self._sync_camera()
            return
        o_tot = self._total_score_m(self._p2_dists)
        win_side = self._match_winner_side(
            int(self._p1_hr), float(p_tot), int(self._p2_hr), float(o_tot)
        )
        self._won = win_side >= 0
        self._match_win_side = int(win_side)
        if win_side > 0:
            win_line = f"1P({self._p1_char}) 승리!"
        elif win_side < 0:
            win_line = f"2P({self._p2_char}) 승리!"
        else:
            win_line = "무승부"
        self._hud_lines = [
            f"1P {self._p1_char}: HR {int(self._p1_hr)} / 합 {int(round(p_tot))}m",
            f"2P {self._p2_char}: HR {int(self._p2_hr)} / 합 {int(round(o_tot))}m",
            win_line,
        ]
        self.state = ST_MATCH_END
        self.field_tilt_target = 1.0
        self._msg = "경기 종료"
        self._sync_camera()

    def _finish_alt_match(self) -> None:
        """번갈아 모드 종료 — 합계비거리 보너스 1점 후 N 대 M 승자 안내."""
        self._clear_scene_freeze()
        self._show_rest_ball()
        p_tot = self._total_score_m(self._p1_dists)
        o_tot = self._total_score_m(self._p2_dists)
        p1_name = self._char_label(self._p1_char or self._player_char)
        p2_name = self._opponent_display_name()
        bonus_line = ""
        if float(p_tot) > float(o_tot):
            self._p1_pts += 1
            bonus_line = f"{p1_name} 합계비거리 보너스 1점!"
        elif float(o_tot) > float(p_tot):
            self._p2_pts += 1
            bonus_line = f"{p2_name} 합계비거리 보너스 1점!"
        else:
            bonus_line = "합계비거리 동점!"
        p1_pts = int(self._p1_pts)
        p2_pts = int(self._p2_pts)
        if p1_pts > p2_pts:
            self._match_win_side = 1
            self._won = True
            win_line = f"{p1_pts} 대 {p2_pts} {p1_name} 승리!!"
        elif p2_pts > p1_pts:
            self._match_win_side = -1
            self._won = False
            win_line = f"{p1_pts} 대 {p2_pts} {p2_name} 승리!!"
        else:
            self._match_win_side = 0
            self._won = False
            win_line = f"{p1_pts} 대 {p2_pts} 무승부!!"
        opp_tag = "NPC" if self.mode == MODE_NPC_VS else "2P"
        self._hud_lines = [
            f"1P {p1_name}: {p1_pts}점 / 합 {int(round(p_tot))}m",
            f"{opp_tag} {p2_name}: {p2_pts}점 / 합 {int(round(o_tot))}m",
            bonus_line,
            win_line,
        ]
        self.state = ST_MATCH_END
        self.field_tilt_target = 1.0
        self._msg = "경기 종료"
        self._sync_camera()

    # ------------------------------------------------------------------ tick

    def tick(self, dt_sec: float, player, now_ms: int) -> None:
        del now_ms
        self._elapsed += max(0.0, float(dt_sec))
        self._pin_batter()
        if self.state in (ST_BAT_DIR, ST_BAT_PWR, ST_SWING_PAUSE, ST_POWER_SWING_PAUSE, ST_TURN_WAIT):
            self._sync_rest_ball_object()
        elif self.state == ST_ANNOUNCE and not self._scene_frozen:
            self._sync_rest_ball_object()
        self._sync_camera()
        if self._p2_switch_fade_phase:
            self._tick_2p_switch_fade(float(dt_sec))
            return
        if self.state == ST_FIELD_INTRO:
            self._tick_field_intro(float(dt_sec))
            return
        if self.state == ST_ANNOUNCE:
            if not self._announce_tap_wait:
                self._announce_left -= float(dt_sec)
                if self._announce_left <= 0.0:
                    self._announce_advance()
            return
        if self.state in (ST_MATCH_END, ST_LEADERBOARD, ST_DEMO_RESULT):
            return
        if self.state == ST_QUIT:
            return

        if self._power_swing_fx_left > 0.0:
            self._power_swing_fx_left = max(
                0.0,
                float(self._power_swing_fx_left) - float(dt_sec),
            )
            if self._power_swing_fx_left <= 0.0:
                self._clear_power_swing_fx()

        if self.state == ST_BAT_DIR:
            sweep_mul = self._gauge_sweep_speed_mul()
            self._dir_phase += (
                float(dt_sec) * float(self._dir_speed) * sweep_mul * math.pi * 2.0
            )
            self._update_batter_facing_from_gauge()
            self._gauge_time_left -= float(dt_sec)
            if self._gauge_time_left <= 0.0:
                # 방향 시간 제한: 랜덤 방향
                self._locked_dir_deg = self._rng.uniform(-self._fan_half_deg, self._fan_half_deg)
                self._update_batter_facing_from_gauge(self._locked_dir_deg)
                self._begin_pwr_phase()
        elif self.state == ST_BAT_PWR:
            sweep_mul = self._gauge_sweep_speed_mul()
            self._pwr_phase += (
                float(dt_sec) * float(self._pwr_speed) * sweep_mul * math.pi * 2.0
            )
            self._gauge_time_left -= float(dt_sec)
            if self._gauge_time_left <= 0.0:
                # 파워 시간 제한: 빗맞춤 효과
                self._resolve_pop_foul_swing()
        elif self.state == ST_PWR_CONFIRM:
            pl = self._player_ref
            if pl is not None:
                _freeze_baseball_batter_pose(pl, self._batter_overlay_char())
            self._pwr_confirm_hold_t -= float(dt_sec)
            if self._pwr_confirm_hold_t <= 0.0:
                self._actual_swing_after_confirm()
        elif self.state in (ST_SWING_PAUSE, ST_POWER_SWING_PAUSE):
            pl = self._player_ref
            if pl is not None:
                _freeze_baseball_batter_pose(pl, self._batter_overlay_char())
            self._power_swing_pause_t -= float(dt_sec)
            if self._power_swing_pause_t <= 0.0:
                self._start_locked_swing_animation()
        elif self.state == ST_SWING:
            self._swing_t -= float(dt_sec)
            if self._swing_t <= 0.0:
                self._start_flight()
        elif self.state == ST_FLIGHT:
            gx, gy, _h = self._ball_flight_state()
            if self._ball_caught:
                self._ease_non_catcher_fielders(float(dt_sec))
                self._catch_hold_t -= float(dt_sec)
                if self._catch_hold_t <= 0.0:
                    self._end_player_swing()
                return
            self._fielder_chase_t -= float(dt_sec)
            if self._fielder_chase_t <= 0.0:
                if not bool(getattr(self, "_is_pop_foul", False)):
                    self._chase_fielders(gx, gy)
                self._fielder_chase_t = float(_cfg("fielder_chase_repath_sec", 0.12))
            if not bool(getattr(self, "_is_pop_foul", False)) and self._tick_fielder_catch():
                return
            if self._flight_sub == "arc":
                self._flight_t += float(dt_sec)
                if self._flight_t >= self._flight_dur:
                    if bool(getattr(self, "_is_pop_foul", False)):
                        self._end_player_swing()
                    elif float(self._carry_px) <= 8.0 and not bool(
                        getattr(self, "_fence_hit", False)
                    ):
                        self._end_player_swing()
                    else:
                        self._flight_sub = "bounce"
                        self._bounce_ix = 0
                        self._bounce_t = 0.0
            elif self._flight_sub == "bounce":
                self._bounce_t += float(dt_sec)
                if self._bounce_t >= float(self._bounce_dur):
                    self._bounce_ix += 1
                    self._bounce_t = 0.0
                    if self._bounce_ix >= int(self._bounce_count):
                        self._flight_sub = "roll"
                        self._roll_left = float(self._roll_travel_total)
                else:
                    bt = max(0.0, min(1.0, self._bounce_t / max(0.01, self._bounce_dur)))
                    phase = min(
                        1.0,
                        (float(self._bounce_ix) + bt) / max(1.0, float(self._bounce_count)),
                    )
                    phase_dist = float(self._bounce_travel_total) * phase
                    if self._ground_dist_blocked_by_fence(phase_dist):
                        if not self._handle_ground_fence_hit(phase_dist):
                            self._roll_left = 0.0
                            self._end_player_swing()
            elif self._flight_sub == "roll":
                roll_tot = max(1.0, float(self._roll_travel_total))
                spd = self._roll_speed_px_s()
                step = spd * float(dt_sec)
                next_left = max(0.0, float(self._roll_left) - step)
                roll_prog_next = 1.0 - next_left / roll_tot
                dist_next = float(self._bounce_travel_total) + roll_tot * roll_prog_next
                if self._ground_dist_blocked_by_fence(dist_next):
                    if not self._handle_ground_fence_hit(dist_next):
                        self._roll_left = 0.0
                else:
                    self._roll_left = next_left
                if self._roll_left <= 0.0:
                    self._end_player_swing()
        elif self.state == ST_TURN_WAIT:
            self._turn_wait -= float(dt_sec)
            if self._turn_wait <= 0.0:
                self._begin_player_swing()
        elif self.state == ST_NPC_SHOW:
            self._npc_flash_t -= float(dt_sec)
            if self._npc_flash_t <= 0.0:
                self._npc_flash_ix = int(getattr(self, "_npc_flash_ix", 0)) + 1
                if self._npc_flash_ix >= self._swings_per_side:
                    end_sec = float(_cfg("announce_match_end_sec", 2.0))
                    self._start_announce([_ann_step("경기 결과!!", end_sec)], self._finish_match)
                else:
                    self._npc_flash_t = float(_cfg("npc_flash_sec", 0.55))
                    self._npc_flash_dist = float(self._npc_dists[self._npc_flash_ix])

    # ------------------------------------------------------------------ input

    def _dir_now_deg(self) -> float:
        return math.sin(self._dir_phase) * float(self._fan_half_deg)

    def _pwr_now(self) -> float:
        x = (math.sin(self._pwr_phase) + 1.0) * 0.5
        return max(0.0, min(1.0, 1.0 - abs(x - 0.5) * 2.0))

    def _pwr_marker_t(self) -> float:
        """파워 게이지 바 위 커서 위치 (0=왼쪽, 1=오른쪽)."""
        return (math.sin(self._pwr_phase) + 1.0) * 0.5

    def _pwr_trap_centers(self) -> Tuple[float, float]:
        return (1.0 / 3.0, 2.0 / 3.0)

    def _pwr_trap_half_width(self) -> float:
        half_w = float(
            _field_num(self.field, "pwr_trap_half_width", 0.01,)
        )
        half_w *= self._difficulty_trap_width_mul()
        return max(0.0, min(0.25, half_w))

    def _pwr_sweet_spot_half_width(self) -> float:
        half_w = float(
            _field_num(self.field, "pwr_sweet_spot_half_width", 0.05)
        )
        half_w *= self._difficulty_sweet_width_mul()
        return max(0.0, min(0.25, half_w))

    def _pwr_sweet_spot_center(self) -> float:
        return 0.5

    def _pwr_trap_half_width_new(self) -> float:
        half_w = float(
            _field_num(self.field, "pwr_trap_half_width_new", 0.02)
        )
        half_w *= self._difficulty_trap_width_mul()
        return max(0.005, min(0.2, half_w))

    def _pwr_power_sweet_spot_half_width_value(self) -> float:
        half_w = float(
            _field_num(self.field, "pwr_power_sweet_spot_half_width", 0.025)
        )
        half_w *= self._difficulty_power_sweet_width_mul()
        return max(0.0, min(self._pwr_sweet_spot_half_width(), half_w))

    def _pwr_in_sweet_spot(self, marker_t: float) -> bool:
        half_w = self._pwr_sweet_spot_half_width()
        center = self._pwr_sweet_spot_center()
        t = max(0.0, min(1.0, float(marker_t)))
        return abs(t - center) <= half_w

    def _pwr_in_power_sweet_spot(self, marker_t: float) -> bool:
        half_w = self._pwr_power_sweet_spot_half_width_value()
        center = self._pwr_sweet_spot_center()
        t = max(0.0, min(1.0, float(marker_t)))
        return abs(t - center) <= half_w

    def _pwr_in_trap_zone(self, marker_t: float) -> bool:
        t = max(0.0, min(1.0, float(marker_t)))

        # 장타 구간이면 함정 아님
        if self._pwr_in_sweet_spot(marker_t):
            return False

        sweet_spot_center = self._pwr_sweet_spot_center()
        sweet_spot_half_w = self._pwr_sweet_spot_half_width()
        trap_half_w_new = self._pwr_trap_half_width_new()

        # 장타 구간 왼쪽 함정
        left_trap_start = sweet_spot_center - sweet_spot_half_w - trap_half_w_new
        left_trap_end = sweet_spot_center - sweet_spot_half_w
        if left_trap_start <= t < left_trap_end:
            return True

        # 장타 구간 오른쪽 함정
        right_trap_start = sweet_spot_center + sweet_spot_half_w
        right_trap_end = sweet_spot_center + sweet_spot_half_w + trap_half_w_new
        if right_trap_start < t <= right_trap_end:
            return True

        return False

    def _logical_screen_size(self) -> Tuple[int, int]:
        try:
            w = int(CONFIG.get("WIDTH", 320) or 320)
            h = int(CONFIG.get("HEIGHT", 240) or 240)
        except Exception:
            w, h = 320, 240
        return max(64, w), max(48, h)

    def _idle_frames_for_direction(self, char_id: str, direction: str = "right") -> List:
        cid = str(char_id or "").strip()
        if not cid:
            return []
        face = "right" if str(direction) == "right" else "left"
        bucket = self._char_idle_cache.get(cid)
        if not isinstance(bucket, dict):
            bucket = {}
            self._char_idle_cache[cid] = bucket
        if face in bucket:
            return bucket[face]
        from engine import load_anim_auto

        frames = load_anim_auto(cid, "idle", face) or []
        if not frames or self._idle_frames_are_placeholder(frames):
            alt = "left" if face == "right" else "right"
            alt_frames = load_anim_auto(cid, "idle", alt) or []
            if alt_frames and not self._idle_frames_are_placeholder(alt_frames):
                frames = [pygame.transform.flip(f, True, False) for f in alt_frames]
            else:
                frames = []
        bucket[face] = frames
        return frames

    def _load_char_anim_frames(self, char_id: str, anim_name: str, direction: str) -> List:
        cid = str(char_id or "").strip()
        an = str(anim_name or "").strip().lower()
        if not cid or not an:
            return []
        face = "right" if str(direction) == "right" else "left"
        cache_key = f"{cid}:{an}:{face}"
        if cache_key in self._char_anim_cache:
            return self._char_anim_cache[cache_key]
        frames: List = []
        overlay_map = {
            "idle": "idle_baseball",
            "cheer": "cheer_baseball",
            "swing": "swing_baseball",
        }
        overlay_name = overlay_map.get(an)
        if overlay_name:
            bt = _body_type_for_char(cid)
            if bt not in ("animal", "pet"):
                raw = _load_bb_overlay_frames(bt, overlay_name)
                if raw:
                    if face == "right":
                        frames = [pygame.transform.flip(f, True, False) for f in raw]
                    else:
                        frames = list(raw)
        if not frames or self._idle_frames_are_placeholder(frames):
            from engine import load_anim_auto

            frames = load_anim_auto(cid, an, face) or []
            if not frames or self._idle_frames_are_placeholder(frames):
                alt = "left" if face == "right" else "right"
                alt_frames = load_anim_auto(cid, an, alt) or []
                if alt_frames and not self._idle_frames_are_placeholder(alt_frames):
                    frames = [pygame.transform.flip(f, True, False) for f in alt_frames]
                else:
                    frames = []
        self._char_anim_cache[cache_key] = frames
        return frames

    def _result_char_frames(self, char_id: str, *, face: str, cheer: bool) -> List:
        direction = "right" if str(face) == "right" else "left"
        if cheer:
            frames = self._load_char_anim_frames(char_id, "cheer", direction)
            if frames and not self._idle_frames_are_placeholder(frames):
                return frames
        return self._idle_frames_for_direction(char_id, direction)

    def _ensure_char_idle(self, char_id: str, direction: str = "right") -> None:
        self._idle_frames_for_direction(char_id, direction)

    @staticmethod
    def _idle_frames_are_placeholder(frames: List) -> bool:
        """engine.load_anim_auto 누락 표시(마젠타 24×32) 여부."""
        if len(frames) != 1:
            return False
        s = frames[0]
        try:
            if s.get_size() != (24, 32):
                return False
            r, g, b, *rest = s.get_at((0, 0))
            return r > 250 and g < 10 and b > 250
        except Exception:
            return False

    def _set_char_opts_for_phase(self, phase: str) -> None:
        """플레이어/NPC 선택 단계에 맞게 그리드 옵션 구성. NPC 단계는 '?' 랜덤 슬롯 추가."""
        base = [c for c in (self._char_opts_base or self._char_opts or []) if c and c != CHAR_PICK_RANDOM]
        if phase == "npc":
            self._char_opts = list(base[:8]) + [CHAR_PICK_RANDOM]
        else:
            self._char_opts = list(base[:8])

    def _resolve_random_npc_char(self) -> str:
        """'?' 선택 시 — 잠금·1P 제외 풀에서 랜덤."""
        pool = []
        for cid in (self._char_opts_base or []):
            c = str(cid or "").strip()
            if not c or c == CHAR_PICK_RANDOM:
                continue
            if c in (self._char_locked or set()):
                continue
            if c == str(self._p1_char or ""):
                continue
            pool.append(c)
        if not pool:
            pool = [
                str(c)
                for c in (self._char_opts_base or [])
                if c and c != CHAR_PICK_RANDOM and c not in (self._char_locked or set())
            ]
        if not pool:
            return str(self._p2_char_opts[0] if self._p2_char_opts else self._player_char)
        return str(self._rng.choice(pool))

    def _layout_char_pick_rects(self, w: int, h: int) -> None:
        self._char_pick_rects = []
        opts = list(self._char_opts or [])
        if not opts:
            return
        n = len(opts)
        cols = _CHAR_PICK_GRID_COLS
        rows = max(_CHAR_PICK_GRID_ROWS, (n + cols - 1) // cols)
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
        for i, _cid in enumerate(opts[:n]):
            col = i % cols
            row = i // cols
            rx = x0 + col * (cell_w + gap_x)
            ry = y0 + row * (cell_h + gap_y)
            self._char_pick_rects.append((pygame.Rect(rx, ry, cell_w, cell_h), i))

    def _menu_back_button_rect(self, w: int, h: int) -> pygame.Rect:
        bw, bh = max(52, int(w * 0.16)), max(24, int(h * 0.07))
        return pygame.Rect(int(w * 0.04), h - bh - int(h * 0.04), bw, bh)

    def _char_pick_phase_title(self) -> str:
        if self.mode == MODE_RECORD_2P and self._char_pick_phase == "2p":
            return "2P 캐릭터 선택"
        if self.mode == MODE_RECORD_2P:
            style = "번갈아" if self._play_style == PLAY_DUO_ALT else "모아서"
            return f"1P 캐릭터 선택 ({style})"
        if self.mode == MODE_NPC_VS and self._char_pick_phase == "npc":
            return "NPC 캐릭터 선택"
        if self.mode == MODE_NPC_VS:
            return "플레이어 캐릭터 선택"
        if self.mode == MODE_DEMO:
            return "캐릭터 선택"
        if self._play_style == PLAY_SOLO_RECORD:
            return "캐릭터 선택 (기록 갱신)"
        return "1P 캐릭터 선택"

    def _char_pick_go_back(self) -> bool:
        if self._char_pending_ix is not None:
            self._char_pending_ix = None
            return True
        if self.state == ST_REPLAY_ASK:
            if self._return_map:
                self._quit_demo_return()
            else:
                self._return_to_main_menu()
            return True
        if self.state != ST_PICK_CHAR:
            return False
        if self.mode == MODE_NPC_VS and self._char_pick_phase == "npc":
            self._char_pick_phase = "solo"
            self._set_char_opts_for_phase("solo")
            self._char_pick_ix = 0
            self._char_pending_ix = None
            self._msg = "플레이어 캐릭터 선택"
            return True
        if self.mode == MODE_RECORD_2P and self._char_pick_phase == "2p":
            self._char_pick_phase = "1p"
            self._char_pick_ix = 0
            self._msg = "1P 캐릭터 선택"
            return True
        if self.mode == MODE_DEMO and self._return_map:
            self._quit_demo_return()
            return True
        # 서브메뉴로 복귀
        if self.mode == MODE_RECORD_2P:
            self.state = ST_MENU_DUO
            self._msg = "둘이서 하기"
            return True
        if self.mode in (MODE_RECORD_1P, MODE_NPC_VS):
            self.state = ST_MENU_SOLO
            self._msg = "혼자서 하기"
            return True
        self._return_to_main_menu()
        return True

    def _draw_menu_back_button(
        self, surf: pygame.Surface, rect: pygame.Rect, font: pygame.font.Font
    ) -> None:
        pygame.draw.rect(surf, (50, 50, 70), rect, border_radius=6)
        pygame.draw.rect(surf, (110, 110, 150), rect, 2, border_radius=6)
        t = font.render("뒤로", True, (220, 220, 240))
        surf.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))

    def _blit_idle_frame(
        self, surf: pygame.Surface, frames: List, center_xy: Tuple[int, int], max_h: int
    ) -> None:
        if not frames:
            return
        fi = int(self._elapsed * 6.0) % len(frames)
        img = frames[fi]
        iw, ih = img.get_size()
        if ih <= 0:
            return
        sc = max_h / ih
        dw, dh = max(1, int(iw * sc)), max(1, int(ih * sc))
        if (dw, dh) != (iw, ih):
            img = pygame.transform.scale(img, (dw, dh))
        cx, cy = center_xy
        surf.blit(img, (cx - dw // 2, cy - dh // 2))

    def _blit_char_anim_frame(
        self,
        surf: pygame.Surface,
        frames: List,
        foot_xy: Tuple[int, int],
        *,
        zoom_mul: int = _MATCH_RESULT_CHAR_ZOOM,
        fps: float = _MATCH_RESULT_CHAR_FPS,
    ) -> None:
        if not frames:
            return
        fi = int(self._elapsed * float(fps)) % len(frames)
        img = frames[fi]
        iw, ih = img.get_size()
        if ih <= 0 or iw <= 0:
            return
        zm = max(1, int(zoom_mul))
        dw, dh = iw * zm, ih * zm
        if (dw, dh) != (iw, ih):
            img = pygame.transform.scale(img, (dw, dh))
        fx, fy = foot_xy
        dx, dy = blit_topleft_bottom_center(int(fx), int(fy), dw, dh)
        surf.blit(img, (int(dx), int(dy)))

    def _draw_match_result(self, ctx: FieldDrawContext) -> None:
        surf = ctx.surf
        w, h = surf.get_width(), surf.get_height()
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        surf.blit(overlay, (0, 0))
        if self.mode in (MODE_RECORD_2P, MODE_NPC_VS):
            self._draw_match_result_2p(ctx)
            return
        big = self._ui_font(ctx, 20)
        head = big.render("경기 결과!!", True, (255, 248, 210))
        surf.blit(head, (w // 2 - head.get_width() // 2, int(h * 0.18)))
        detail = self._ui_font(ctx, 13)
        y = int(h * 0.30)
        for ln in self._hud_lines:
            t = detail.render(ln, True, (240, 248, 255))
            surf.blit(t, (w // 2 - t.get_width() // 2, y))
            y += 22
        hint = self._ui_font(ctx, 11).render("화면을 탭하세요", True, (200, 210, 230))
        surf.blit(hint, (w // 2 - hint.get_width() // 2, y + 12))

    def _draw_match_result_2p(self, ctx: FieldDrawContext) -> None:
        surf = ctx.surf
        w, h = surf.get_width(), surf.get_height()
        foot_y = int(h * 0.86)
        win_side = int(getattr(self, "_match_win_side", 0) or 0)
        p1_cheer = win_side > 0
        p2_cheer = win_side < 0
        p1_frames = self._result_char_frames(self._p1_char, face="right", cheer=p1_cheer)
        self._blit_char_anim_frame(
            surf, p1_frames, (int(w * 0.20), foot_y)
        )
        if self.mode == MODE_RECORD_2P and self._p2_char:
            p2_frames = self._result_char_frames(self._p2_char, face="left", cheer=p2_cheer)
            self._blit_char_anim_frame(
                surf, p2_frames, (int(w * 0.80), foot_y)
            )
        elif self.mode == MODE_NPC_VS and self._p2_char:
            p2_frames = self._result_char_frames(self._p2_char, face="left", cheer=p2_cheer)
            self._blit_char_anim_frame(
                surf, p2_frames, (int(w * 0.80), foot_y)
            )
        title_font = self._ui_font(ctx, 20)
        head = title_font.render("경기 결과!!", True, (255, 248, 210))
        surf.blit(head, (w // 2 - head.get_width() // 2, int(h * 0.08)))
        score_font = self._ui_font(ctx, 13)
        small = self._ui_font(ctx, 11)
        p_tot = int(round(self._total_score_m(self._p1_dists)))
        o_tot = int(round(self._total_score_m(self._p2_dists)))
        p1_nm = self._char_label(self._p1_char)
        p2_nm = self._opponent_display_name()
        p1_hr = int(self._p1_hr)
        p2_hr = int(self._p2_hr)
        win_col = (255, 230, 120)
        lose_col = (200, 215, 235)
        p1_col = win_col if win_side > 0 else lose_col
        p2_col = win_col if win_side < 0 else lose_col
        tie_col = (220, 235, 255)
        if win_side == 0:
            p1_col = p2_col = tie_col
        cy = int(h * 0.30)
        p1_line1 = score_font.render(f"1P {p1_nm}", True, p1_col)
        opp_tag = "NPC" if self.mode == MODE_NPC_VS else "2P"
        p2_line1 = score_font.render(f"{opp_tag} {p2_nm}", True, p2_col)
        gap = max(12, int(w * 0.06))
        mid = w // 2
        surf.blit(p1_line1, (mid - gap - p1_line1.get_width(), cy))
        surf.blit(p2_line1, (mid + gap, cy))
        cy += 20
        if self._is_alternate_play():
            p1_line2 = small.render(
                f"{int(self._p1_pts)}점  /  {p_tot}m", True, p1_col
            )
            p2_line2 = small.render(
                f"{int(self._p2_pts)}점  /  {o_tot}m", True, p2_col
            )
        else:
            p1_line2 = small.render(f"HR {p1_hr}  /  {p_tot}m", True, p1_col)
            p2_line2 = small.render(f"HR {p2_hr}  /  {o_tot}m", True, p2_col)
        surf.blit(p1_line2, (mid - gap - p1_line2.get_width(), cy))
        surf.blit(p2_line2, (mid + gap, cy))
        cy += 24
        for ln in self._hud_lines:
            if not ln:
                continue
            # 상세 줄은 위에 이미 점수 표시 — 보너스·승패 문구만
            if ln.startswith("1P ") or ln.startswith("2P ") or ln.startswith("NPC "):
                continue
            col = (255, 248, 180) if ("승리" in ln or "무승부" in ln or "보너스" in ln or "동점" in ln) else (230, 240, 255)
            wt = score_font.render(str(ln), True, col)
            surf.blit(wt, (w // 2 - wt.get_width() // 2, cy))
            cy += 22
        hint = small.render("화면을 탭하세요", True, (200, 210, 230))
        surf.blit(hint, (w // 2 - hint.get_width() // 2, int(h * 0.92)))

    def _confirm_char_pick(self, ix: int) -> bool:
        opts = list(self._char_opts or [])
        if not opts:
            return False
        ix = int(ix) % len(opts)
        self._char_pick_ix = ix
        pick = str(opts[ix])
        is_random = pick == CHAR_PICK_RANDOM
        if (not is_random) and pick in (self._char_locked or set()):
            self._msg = "잠긴 캐릭터입니다"
            return False
        if self.mode == MODE_DEMO:
            self._apply_batter_char(pick)
            self._start_demo_match()
            return True
        # NPC와 하기 — 플레이어 고른 뒤 NPC 선택(?=랜덤)
        if self.mode == MODE_NPC_VS:
            if self._char_pick_phase == "npc":
                self._npc_random_pick = bool(is_random)
                if is_random:
                    pick = self._resolve_random_npc_char()
                self._p2_char = pick
                self._npc_name = self._char_label(pick)
                self._start_npc_alt_match()
                return True
            # 플레이어 선택 → NPC 선택 단계
            if is_random:
                self._msg = "플레이어는 캐릭터를 골라 주세요"
                return False
            self._p1_char = pick
            self._apply_batter_char(pick)
            self._char_pick_phase = "npc"
            self._set_char_opts_for_phase("npc")
            self._char_pick_ix = 0
            self._char_pending_ix = None
            self._msg = "NPC 캐릭터 선택"
            return True
        if self.mode == MODE_RECORD_1P:
            self._p1_char = pick
            self._apply_batter_char(pick)
            self._start_solo_match()
            return True
        if self._char_pick_phase == "1p":
            self._p1_char = pick
            self._char_pick_phase = "2p"
            self._char_pick_ix = 0
            self._char_pending_ix = None
            self._msg = "2P 캐릭터 선택"
            return True
        if self._char_pick_phase == "2p":
            self._p2_char = pick
            self._start_match_2p()
            return True
        return False

    def _layout_menu_rects(self, w: int, h: int) -> None:
        """그리기 전에도 클릭 판정이 되도록 버튼 영역만 갱신."""
        self._menu_rects = []
        if self.state == ST_REPLAY_ASK:
            bw, bh = int(w * 0.62), int(h * 0.09)
            bx = w // 2 - bw // 2
            self._menu_rects.append((pygame.Rect(bx, int(h * 0.44), bw, bh), "replay_yes"))
            self._menu_rects.append((pygame.Rect(bx, int(h * 0.58), bw, bh), "replay_no"))
            self._menu_rects.append((self._menu_back_button_rect(w, h), "menu_back"))
            return
        if self.state == ST_MENU:
            items = ["solo", "duo", "records", "difficulty", "exit"]
            bw, bh = int(w * 0.72), int(h * 0.09)
            bx = w // 2 - bw // 2
            y0 = int(h * 0.20)
            for i, act in enumerate(items):
                self._menu_rects.append(
                    (pygame.Rect(bx, y0 + i * (bh + 8), bw, bh), act)
                )
            return
        if self.state in (ST_MENU_SOLO, ST_MENU_DUO):
            bw, bh = int(w * 0.72), int(h * 0.09)
            bx = w // 2 - bw // 2
            y0 = int(h * 0.32)
            if self.state == ST_MENU_SOLO:
                acts = ["solo_npc", "solo_record"]
            else:
                acts = ["duo_alt", "duo_batch"]
            for i, act in enumerate(acts):
                self._menu_rects.append(
                    (pygame.Rect(bx, y0 + i * (bh + 10), bw, bh), act)
                )
            self._menu_rects.append((self._menu_back_button_rect(w, h), "menu_back"))
            return
        if self.state == ST_DIFFICULTY:
            bw, bh = int(w * 0.72), int(h * 0.09)
            bx = w // 2 - bw // 2
            y0 = int(h * 0.28)
            for i, (difficulty_id, _label) in enumerate(BASEBALL_DIFFICULTY_OPTIONS):
                self._menu_rects.append(
                    (
                        pygame.Rect(bx, y0 + i * (bh + 10), bw, bh),
                        f"difficulty:{difficulty_id}",
                    )
                )
            self._menu_rects.append((self._menu_back_button_rect(w, h), "menu_back"))
            return
        if self.state == ST_PICK_CHAR:
            if self._char_pending_ix is not None:
                bw, bh = int(w * 0.34), int(h * 0.09)
                gap = int(w * 0.04)
                cy = int(h * 0.72)
                total = bw * 2 + gap
                bx = w // 2 - total // 2
                self._menu_rects.append((pygame.Rect(bx, cy, bw, bh), "char_confirm_yes"))
                self._menu_rects.append(
                    (pygame.Rect(bx + bw + gap, cy, bw, bh), "char_confirm_no")
                )
            else:
                self._layout_char_pick_rects(w, h)
                for rect, ix in self._char_pick_rects:
                    self._menu_rects.append((rect, f"char_pick:{ix}"))
            self._menu_rects.append((self._menu_back_button_rect(w, h), "menu_back"))
            return
        if self.state == ST_PICK_P2:
            bw, bh = int(w * 0.72), int(h * 0.09)
            bx = w // 2 - bw // 2
            self._menu_rects.append((pygame.Rect(bx, int(h * 0.48), bw, bh), "2p_start"))
            self._menu_rects.append((pygame.Rect(bx, int(h * 0.62), bw, bh), "menu_back"))

    def _menu_hit(self, screen_xy) -> Optional[str]:
        if not screen_xy:
            return None
        try:
            px, py = int(screen_xy[0]), int(screen_xy[1])
        except (TypeError, ValueError, IndexError):
            return None
        wh = getattr(self, "_ui_screen_wh", None)
        if isinstance(wh, (tuple, list)) and len(wh) >= 2:
            lw, lh = int(wh[0]), int(wh[1])
        else:
            lw, lh = self._logical_screen_size()
        self._layout_menu_rects(lw, lh)
        if not self._menu_rects:
            return None
        for rect, action in self._menu_rects:
            if rect.collidepoint(px, py):
                return action
        return None

    def _begin_char_pick(self, *, mode: str, play_style: str, phase: str, msg: str) -> None:
        """서브메뉴에서 캐릭터 선택으로 진입."""
        self.mode = mode
        self._play_style = play_style
        self._char_pick_phase = phase
        self._char_pick_ix = 0
        self._char_pending_ix = None
        self.state = ST_PICK_CHAR
        self._msg = msg

    def _apply_menu_action(self, act: Optional[str]) -> bool:
        if not act:
            return False
        if self.state == ST_MENU:
            if act == "solo":
                self.state = ST_MENU_SOLO
                self._msg = "혼자서 하기"
                return True
            if act == "duo":
                self.state = ST_MENU_DUO
                self._msg = "둘이서 하기"
                return True
            if act == "records":
                self.state = ST_RECORDS
                return True
            if act == "difficulty":
                self.state = ST_DIFFICULTY
                self._msg = "난이도를 선택하세요"
                return True
            if act == "exit":
                self._quit_via_menu()
                return True
        if self.state == ST_MENU_SOLO:
            if act == "menu_back":
                self._return_to_main_menu()
                return True
            if act == "solo_npc":
                self._begin_char_pick(
                    mode=MODE_NPC_VS,
                    play_style=PLAY_NPC_ALT,
                    phase="solo",
                    msg="캐릭터 선택",
                )
                return True
            if act == "solo_record":
                self._begin_char_pick(
                    mode=MODE_RECORD_1P,
                    play_style=PLAY_SOLO_RECORD,
                    phase="solo",
                    msg="1P 캐릭터 선택",
                )
                return True
        if self.state == ST_MENU_DUO:
            if act == "menu_back":
                self._return_to_main_menu()
                return True
            if act == "duo_alt":
                self._begin_char_pick(
                    mode=MODE_RECORD_2P,
                    play_style=PLAY_DUO_ALT,
                    phase="1p",
                    msg="1P 캐릭터 선택",
                )
                return True
            if act == "duo_batch":
                self._begin_char_pick(
                    mode=MODE_RECORD_2P,
                    play_style=PLAY_DUO_BATCH,
                    phase="1p",
                    msg="1P 캐릭터 선택",
                )
                return True
        if self.state == ST_DIFFICULTY:
            if act == "menu_back":
                self._return_to_main_menu()
                return True
            if act.startswith("difficulty:"):
                try:
                    difficulty_id = act.split(":", 1)[1]
                except (ValueError, IndexError):
                    return False
                self._difficulty_id = self._normalize_difficulty_id(difficulty_id)
                self._apply_difficulty_balance()
                self._save_data["baseball_difficulty"] = self._difficulty_id
                self._save_patch["baseball_difficulty"] = self._difficulty_id
                self._return_to_main_menu()
                self._msg = f"난이도 설정: {self._difficulty_label()}"
                return True
        if self.state == ST_PICK_CHAR:
            if act == "menu_back":
                return self._char_pick_go_back()
            if act == "char_confirm_yes":
                ix = self._char_pending_ix
                self._char_pending_ix = None
                if ix is not None:
                    return self._confirm_char_pick(int(ix))
                return False
            if act == "char_confirm_no":
                self._char_pending_ix = None
                return True
            if act.startswith("char_pick:"):
                try:
                    ix = int(act.split(":", 1)[1])
                except (ValueError, IndexError):
                    return False
                opts = list(self._char_opts or [])
                if not opts:
                    return False
                ix = int(ix) % len(opts)
                self._char_pick_ix = ix
                self._char_pending_ix = ix
                return True
        if self.state == ST_PICK_P2:
            if act == "2p_start":
                self._start_match_2p()
                return True
            if act == "menu_back":
                self.state = ST_MENU
                return True
        if self.state == ST_REPLAY_ASK:
            if act == "menu_back":
                return self._char_pick_go_back()
            if act == "replay_yes":
                self._char_pending_ix = None
                self.state = ST_PICK_CHAR
                self._msg = "캐릭터를 고르고 게임을 시작하세요"
                return True
            if act == "replay_no":
                self._quit_demo_return()
                return True
        return False

    def _advance_result_screen(self) -> None:
        """경기 결과·리더보드·데모 결과 — 탭 시 다음 단계."""
        if self.state == ST_DEMO_RESULT:
            self.state = ST_REPLAY_ASK
            self._msg = "다시 할래요?"
            return
        if self.state in (ST_MATCH_END, ST_LEADERBOARD):
            self._return_to_main_menu()

    def on_primary_key(self, key: int) -> bool:
        """게임플레이 상태 표시(실제 입력은 main ui_cursor + on_pointer_down)."""
        del key
        return self.state in (
            ST_ANNOUNCE,
            ST_BAT_DIR,
            ST_BAT_PWR,
            ST_MENU,
            ST_MENU_SOLO,
            ST_MENU_DUO,
            ST_PICK_CHAR,
            ST_REPLAY_ASK,
            ST_LEADERBOARD,
            ST_MATCH_END,
            ST_DEMO_RESULT,
        )

    def on_pointer_down(self, screen_xy, world_xy, now_ms: int) -> bool:
        del now_ms
        if self.state == ST_FIELD_INTRO:
            if self._intro_elapsed >= 1.0:
                # 투어 시작 1초 후 클릭하면 투어 종료
                self._intro_phase = ""
                cb = self._intro_on_done
                self._intro_on_done = None
                self._finish_field_intro_camera()
                if cb is not None:
                    cb()
            return True
        if self.state in (
            ST_MENU,
            ST_MENU_SOLO,
            ST_MENU_DUO,
            ST_DIFFICULTY,
            ST_PICK_CHAR,
            ST_PICK_P2,
            ST_REPLAY_ASK,
        ):
            act = self._menu_hit(screen_xy)
            if act and self._apply_menu_action(act):
                return True
            return True
        if self.state in (ST_RECORDS, ST_LEADERBOARD, ST_MATCH_END, ST_DEMO_RESULT):
            if self.state == ST_RECORDS:
                self._return_to_main_menu()
            else:
                self._advance_result_screen()
            return True
        if self.state == ST_ANNOUNCE:
            if self._announce_tap_wait:
                self._announce_advance()
            return True
        # NPC 자동 타격 중에는 플레이어 입력 무시
        if self.mode == MODE_NPC_VS and self._batting_as_p2:
            return True
        if self.state == ST_BAT_DIR:
            self._locked_dir_deg = self._dir_now_deg()
            self._update_batter_facing_from_gauge(self._locked_dir_deg)
            self._begin_pwr_phase()
            return True
        if self.state == ST_BAT_PWR:
            self._locked_pwr = self._pwr_now()
            self._resolve_player_swing()
            return True
        if self.state == ST_PWR_CONFIRM:
            return True
        return self.state in (
            ST_ANNOUNCE,
            ST_BAT_DIR,
            ST_BAT_PWR,
            ST_PWR_CONFIRM,
            ST_MENU,
            ST_MENU_SOLO,
            ST_MENU_DUO,
            ST_DIFFICULTY,
            ST_RECORDS,
            ST_MATCH_END,
            ST_LEADERBOARD,
            ST_PICK_P2,
            ST_PICK_CHAR,
            ST_DEMO_RESULT,
            ST_REPLAY_ASK,
        )

    def on_pointer_up(self, now_ms: int) -> bool:
        del now_ms
        if self.state == ST_PICK_P2:
            # 짧은 탭=다음 캐릭터, 길게는 미구현 — 더블탭 대신 메뉴 시작 버튼 영역
            return True
        return False

    # ------------------------------------------------------------------ draw

    def _ui_font(self, ctx: FieldDrawContext, px: int) -> pygame.font.Font:
        try:
            sc = float(scale_ui_text_px(px, screen_w=ctx.surf.get_width()))
        except Exception:
            sc = float(px)
        return ctx.font_fn(max(8, int(round(sc))))

    def _draw_announce_overlay(self, ctx: FieldDrawContext) -> None:
        text = str(self._announce_text or "").strip()
        if not text:
            return
        surf = ctx.surf
        w, h = surf.get_width(), surf.get_height()
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((4, 8, 18, 175))
        surf.blit(overlay, (0, 0))
        
        if self._announce_is_home_run:
            # 홈런일 때 logo 폰트로 크게 표시
            logo_font = _get_logo_font(72)
            title = logo_font.render(text, True, (255, 210, 0))
            shadow = logo_font.render(text, True, (80, 40, 0))
        else:
            # 일반 텍스트
            big = self._ui_font(ctx, 24)
            title = big.render(text, True, (255, 248, 210))
            shadow = big.render(text, True, (20, 24, 40))

        vis = title.get_bounding_rect()
        if vis.width > 0 and vis.height > 0:
            tx = w // 2 - (vis.x + vis.width // 2)
            ty = h // 2 - (vis.y + vis.height // 2)
        else:
            tx = w // 2 - title.get_width() // 2
            ty = h // 2 - title.get_height() // 2
        surf.blit(shadow, (tx + 2, ty + 2))
        surf.blit(title, (tx, ty))
        if self._announce_tap_wait:
            small = self._ui_font(ctx, 11)
            hint = small.render("화면을 터치하세요", True, (200, 220, 245))
            surf.blit(hint, (w // 2 - hint.get_width() // 2, ty + title.get_height() + 14))

    def _draw_gauge_timer(self, ctx: FieldDrawContext, y: int) -> None:
        left = max(0.0, float(self._gauge_time_left))
        font = self._ui_font(ctx, 11)
        t = font.render(f"{left:.1f}s", True, (255, 210, 120) if left <= 1.5 else (220, 235, 255))
        surf = ctx.surf
        surf.blit(t, (surf.get_width() // 2 - t.get_width() // 2, int(y)))

    def _draw_menu(self, ctx: FieldDrawContext) -> None:
        surf = ctx.surf
        w, h = surf.get_width(), surf.get_height()
        font = self._ui_font(ctx, 14)
        small = self._ui_font(ctx, 11)
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((8, 12, 24, 190))
        surf.blit(overlay, (0, 0))

        if self.state == ST_REPLAY_ASK:
            title = font.render("다시 할래요?", True, (255, 248, 220))
            surf.blit(title, (w // 2 - title.get_width() // 2, int(h * 0.28)))
            self._layout_menu_rects(w, h)
            bw, bh = int(w * 0.62), int(h * 0.09)
            bx = w // 2 - bw // 2
            yes_r = pygame.Rect(bx, int(h * 0.44), bw, bh)
            pygame.draw.rect(surf, (50, 90, 60), yes_r, border_radius=6)
            ts = small.render("예", True, (230, 255, 230))
            surf.blit(ts, (yes_r.centerx - ts.get_width() // 2, yes_r.centery - ts.get_height() // 2))
            no_r = pygame.Rect(bx, int(h * 0.58), bw, bh)
            pygame.draw.rect(surf, (70, 50, 50), no_r, border_radius=6)
            tn = small.render("아니오", True, (255, 230, 230))
            surf.blit(tn, (no_r.centerx - tn.get_width() // 2, no_r.centery - tn.get_height() // 2))
            back_r = self._menu_back_button_rect(w, h)
            self._draw_menu_back_button(surf, back_r, small)
            return

        # 상위 메뉴 제목은 메인·서브·2P 시작에서만 — 난이도·캐릭터는 자기 제목 사용
        if self.state in (ST_MENU, ST_MENU_SOLO, ST_MENU_DUO, ST_PICK_P2):
            title = font.render("어린이 야구 — 홈런 대결", True, (255, 248, 220))
            surf.blit(title, (w // 2 - title.get_width() // 2, int(h * 0.08)))

        self._layout_menu_rects(w, h)
        if self.state == ST_MENU:
            items = [
                ("혼자서 하기", "solo"),
                ("둘이서 하기", "duo"),
                ("기록 보기", "records"),
                (f"난이도 설정  [{self._difficulty_label()}]", "difficulty"),
                ("나가기", "exit"),
            ]
            bw, bh = int(w * 0.72), int(h * 0.09)
            bx = w // 2 - bw // 2
            y0 = int(h * 0.20)
            for i, (label, act) in enumerate(items):
                rect = pygame.Rect(bx, y0 + i * (bh + 8), bw, bh)
                if act == "exit":
                    col = (70, 50, 50)
                elif act == "difficulty":
                    col = (52, 70, 110)
                else:
                    col = (40, 58, 88)
                pygame.draw.rect(surf, col, rect, border_radius=6)
                pygame.draw.rect(surf, (120, 160, 220), rect, 2, border_radius=6)
                t = small.render(label, True, (240, 248, 255))
                surf.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))
            return

        if self.state in (ST_MENU_SOLO, ST_MENU_DUO):
            sub_title = "혼자서 하기" if self.state == ST_MENU_SOLO else "둘이서 하기"
            st = font.render(sub_title, True, (255, 248, 220))
            surf.blit(st, (w // 2 - st.get_width() // 2, int(h * 0.18)))
            if self.state == ST_MENU_SOLO:
                items = [
                    ("NPC와 하기", "solo_npc"),
                    ("기록 갱신하기", "solo_record"),
                ]
            else:
                items = [
                    ("번갈아 하기", "duo_alt"),
                    ("모아서 하기", "duo_batch"),
                ]
            bw, bh = int(w * 0.72), int(h * 0.09)
            bx = w // 2 - bw // 2
            y0 = int(h * 0.32)
            for i, (label, _act) in enumerate(items):
                rect = pygame.Rect(bx, y0 + i * (bh + 10), bw, bh)
                pygame.draw.rect(surf, (40, 58, 88), rect, border_radius=6)
                pygame.draw.rect(surf, (120, 160, 220), rect, 2, border_radius=6)
                t = small.render(label, True, (240, 248, 255))
                surf.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))
            back_r = self._menu_back_button_rect(w, h)
            self._draw_menu_back_button(surf, back_r, small)
            return

        if self.state == ST_DIFFICULTY:
            title2 = font.render("난이도 설정", True, (255, 248, 220))
            surf.blit(title2, (w // 2 - title2.get_width() // 2, int(h * 0.14)))
            hint = small.render(
                f"현재 선택: {self._difficulty_label()}",
                True,
                (190, 215, 255),
            )
            surf.blit(hint, (w // 2 - hint.get_width() // 2, int(h * 0.20)))
            bw, bh = int(w * 0.72), int(h * 0.09)
            bx = w // 2 - bw // 2
            y0 = int(h * 0.28)
            for i, (difficulty_id, label) in enumerate(BASEBALL_DIFFICULTY_OPTIONS):
                rect = pygame.Rect(bx, y0 + i * (bh + 10), bw, bh)
                selected = difficulty_id == self._difficulty_id
                fill = (58, 90, 74) if selected else (40, 58, 88)
                border = (255, 220, 120) if selected else (120, 160, 220)
                pygame.draw.rect(surf, fill, rect, border_radius=6)
                pygame.draw.rect(surf, border, rect, 2, border_radius=6)
                text = label + ("  [선택됨]" if selected else "")
                t = small.render(text, True, (240, 248, 255))
                surf.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))
            back_r = self._menu_back_button_rect(w, h)
            self._draw_menu_back_button(surf, back_r, small)
            return

        if self.state == ST_PICK_CHAR:
            phase_title = self._char_pick_phase_title()
            pt = font.render(phase_title, True, (255, 248, 220))
            surf.blit(pt, (w // 2 - pt.get_width() // 2, int(h * 0.06)))
            if self._char_pending_ix is None:
                # 선택 그리드 — 확인창(서브메뉴)이 떠 있으면 그리지 않는다 (겹침 방지)
                hint_txt = (
                    "NPC를 고르거나 ? 로 랜덤"
                    if self._char_pick_phase == "npc"
                    else "캐릭터를 탭하세요"
                )
                hint = small.render(hint_txt, True, (180, 200, 220))
                surf.blit(hint, (w // 2 - hint.get_width() // 2, int(h * 0.13)))
                self._layout_char_pick_rects(w, h)
                grid_sprite_h = _CHAR_PICK_IDLE_GRID_H
                for rect, ix in self._char_pick_rects:
                    cid = str(self._char_opts[ix])
                    if cid == CHAR_PICK_RANDOM:
                        pygame.draw.rect(surf, (48, 58, 90), rect, border_radius=8)
                        pygame.draw.rect(surf, (180, 200, 255), rect, 2, border_radius=8)
                        qf = font.render("?", True, (255, 248, 210))
                        surf.blit(
                            qf,
                            (
                                rect.centerx - qf.get_width() // 2,
                                rect.centery - qf.get_height() // 2 - 6,
                            ),
                        )
                        lbl = small.render("랜덤", True, (210, 225, 245))
                        ly = rect.bottom - lbl.get_height() - 2
                        if ly >= rect.top:
                            surf.blit(lbl, (rect.centerx - lbl.get_width() // 2, ly))
                        continue
                    frames = self._idle_frames_for_direction(cid, "right")
                    sprite_h = min(grid_sprite_h, max(16, int(rect.height * 0.55)))
                    sy = rect.centery - int(sprite_h * 0.15)
                    self._blit_idle_frame(surf, frames, (rect.centerx, sy), sprite_h)
                    locked = cid in (self._char_locked or set())
                    if locked:
                        dim2 = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                        dim2.fill((0, 0, 0, 130))
                        surf.blit(dim2, (rect.left, rect.top))
                    lbl_txt = "???" if locked else self._char_label(cid)
                    lbl = small.render(lbl_txt, True, (210, 225, 245))
                    ly = rect.bottom - lbl.get_height() - 2
                    if ly >= rect.top:
                        surf.blit(lbl, (rect.centerx - lbl.get_width() // 2, ly))
            back_r = self._menu_back_button_rect(w, h)
            self._draw_menu_back_button(surf, back_r, small)
            if self._char_pending_ix is not None:
                # 선택 확인창 — 상위(그리드)는 숨긴 상태로 확인 UI만 표시
                ix = int(self._char_pending_ix)
                cid = str(self._char_opts[ix]) if self._char_opts else ""
                full_h = min(int(h * 0.30), _CHAR_PICK_IDLE_CONFIRM_H)
                cy = int(h * 0.40)
                if cid == CHAR_PICK_RANDOM:
                    qf = font.render("?", True, (255, 248, 210))
                    big_q = _get_logo_font(72)
                    qbig = big_q.render("?", True, (255, 248, 210))
                    surf.blit(qbig, (w // 2 - qbig.get_width() // 2, cy - qbig.get_height() // 2))
                    nm = font.render("랜덤 NPC", True, (255, 248, 220))
                else:
                    frames = self._idle_frames_for_direction(cid, "right")
                    self._blit_idle_frame(surf, frames, (w // 2, cy), full_h)
                    nm = font.render(self._char_label(cid), True, (255, 248, 220))
                surf.blit(nm, (w // 2 - nm.get_width() // 2, int(h * 0.54)))
                ask = font.render("선택 하시겠습니까?", True, (230, 240, 255))
                surf.blit(ask, (w // 2 - ask.get_width() // 2, int(h * 0.62)))
                bw, bh = int(w * 0.34), int(h * 0.09)
                gap = int(w * 0.04)
                cy_btn = int(h * 0.72)
                total = bw * 2 + gap
                bx = w // 2 - total // 2
                yes_r = pygame.Rect(bx, cy_btn, bw, bh)
                pygame.draw.rect(surf, (50, 90, 60), yes_r, border_radius=6)
                ty = small.render("응", True, (230, 255, 230))
                surf.blit(ty, (yes_r.centerx - ty.get_width() // 2, yes_r.centery - ty.get_height() // 2))
                no_r = pygame.Rect(bx + bw + gap, cy_btn, bw, bh)
                pygame.draw.rect(surf, (70, 50, 50), no_r, border_radius=6)
                tn = small.render("아니", True, (255, 230, 230))
                surf.blit(tn, (no_r.centerx - tn.get_width() // 2, no_r.centery - tn.get_height() // 2))
                self._draw_menu_back_button(surf, back_r, small)
            return

        # ST_PICK_P2
        bw, bh = int(w * 0.72), int(h * 0.09)
        bx = w // 2 - bw // 2
        hint = small.render(
            f"2P 캐릭터: {self._p2_char}  (탭=다음)", True, (200, 230, 255)
        )
        surf.blit(hint, (w // 2 - hint.get_width() // 2, int(h * 0.35)))
        start_r = pygame.Rect(bx, int(h * 0.48), bw, bh)
        pygame.draw.rect(surf, (50, 90, 60), start_r, border_radius=6)
        ts = small.render("게임 시작", True, (230, 255, 230))
        surf.blit(ts, (start_r.centerx - ts.get_width() // 2, start_r.centery - ts.get_height() // 2))
        back_r = pygame.Rect(bx, int(h * 0.62), bw, bh)
        pygame.draw.rect(surf, (50, 50, 70), back_r, border_radius=6)
        tb = small.render("메뉴로", True, (220, 220, 240))
        surf.blit(tb, (back_r.centerx - tb.get_width() // 2, back_r.centery - tb.get_height() // 2))

    def _draw_records(self, ctx: FieldDrawContext) -> None:
        surf = ctx.surf
        w, h = surf.get_width(), surf.get_height()
        font = self._ui_font(ctx, 12)
        small = self._ui_font(ctx, 10)
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((8, 12, 24, 200))
        surf.blit(overlay, (0, 0))
        title = font.render("HIGH SCORE", True, (255, 220, 120))
        surf.blit(title, (w // 2 - title.get_width() // 2, int(h * 0.08)))
        rows = self._arcade_records()
        y = int(h * 0.18)
        if not rows:
            t = small.render("(기록 없음)", True, (180, 190, 210))
            surf.blit(t, (w // 2 - t.get_width() // 2, y))
        else:
            hdr = small.render("RANK   SCORE   NAME", True, (160, 180, 220))
            surf.blit(hdr, (w // 2 - hdr.get_width() // 2, y))
            y += 18
            for i, row in enumerate(rows[:8], start=1):
                sc = int(row.get("score", row.get("player", 0)) or 0)
                cid = str(row.get("char", "") or "").strip()
                nm = (self._char_label(cid) if cid else str(row.get("mode", "?")))[:10]
                line = f"{i:2d}     {sc:5d}   {nm}"
                t = small.render(line, True, (230, 240, 255))
                surf.blit(t, (w // 2 - t.get_width() // 2, y))
                y += 16
        hint = small.render("탭 — 메뉴로", True, (180, 190, 210))
        surf.blit(hint, (w // 2 - hint.get_width() // 2, int(h * 0.88)))

    def _draw_leaderboard(self, ctx: FieldDrawContext) -> None:
        surf = ctx.surf
        w, h = surf.get_width(), surf.get_height()
        font = self._ui_font(ctx, 13)
        small = self._ui_font(ctx, 10)
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((8, 12, 24, 210))
        surf.blit(overlay, (0, 0))
        title = font.render("경기 결과!!", True, (255, 248, 220))
        surf.blit(title, (w // 2 - title.get_width() // 2, int(h * 0.06)))
        y = int(h * 0.14)
        for ln in self._hud_lines:
            t = small.render(ln, True, (230, 240, 255))
            surf.blit(t, (w // 2 - t.get_width() // 2, y))
            y += 18
        y += 8
        hs = font.render("— HIGH SCORE —", True, (255, 210, 90))
        surf.blit(hs, (w // 2 - hs.get_width() // 2, y))
        y += 22
        rows = self._arcade_records()
        for i, row in enumerate(rows[:8], start=1):
            sc = int(row.get("score", row.get("player", 0)) or 0)
            cid = str(row.get("char", "") or "").strip()
            nm = (self._char_label(cid) if cid else "?")[:10]
            hi = (i - 1) == int(self._leaderboard_highlight)
            col = (255, 255, 160) if hi else (220, 230, 250)
            mark = " ◀ NEW" if hi else ""
            line = f"{i:2d}  {sc:5d}  {nm}{mark}"
            t = small.render(line, True, col)
            surf.blit(t, (w // 2 - t.get_width() // 2, y))
            y += 16
        hint = small.render("화면을 탭하세요", True, (180, 190, 210))
        surf.blit(hint, (w // 2 - hint.get_width() // 2, int(h * 0.90)))

    def _draw_fan_gauge(self, ctx: FieldDrawContext) -> None:
        surf = ctx.surf
        w, h = surf.get_width(), surf.get_height()
        cx, cy = int(w * 0.20), int(h * 0.72)
        r = int(min(w, h) * 0.2)
        fan = math.radians(float(self._fan_half_deg))
        # 부채꼴·화살표 = 타구 방향(+X 기준, 화면 오른쪽)과 동일 (cos/sin)
        rect = (cx - r, cy - r, r * 2, r * 2)
        pygame.draw.arc(surf, (80, 100, 130), rect, -fan, fan, 3)
        ang = math.radians(self._dir_now_deg())
        ex = cx + int(math.cos(ang) * r * 0.78)
        ey = cy + int(math.sin(ang) * r * 0.78)
        pygame.draw.line(surf, (255, 220, 80), (cx, cy), (ex, ey), 3)
        pygame.draw.circle(surf, (255, 240, 120), (ex, ey), 5)
        font = self._ui_font(ctx, 11)
        tip = font.render("방향 — 화면 터치!", True, (240, 248, 255))
        surf.blit(tip, (cx - tip.get_width() // 2, cy + r // 2))
        self._draw_gauge_timer(ctx, cy + r // 2 + 18)

    def _draw_pwr_gauge(self, ctx: FieldDrawContext) -> None:
        surf = ctx.surf
        w, h = surf.get_width(), surf.get_height()
        gw = int(w * 0.78)
        gh = 14
        gx = w // 2 - gw // 2
        gy = int(h * 0.82)
        pygame.draw.rect(surf, (40, 48, 60), (gx, gy, gw, gh), border_radius=4)

        # 장타 구간 그리기 (초록색)
        sweet_spot_center = self._pwr_sweet_spot_center()
        sweet_spot_half_w = self._pwr_sweet_spot_half_width()
        sweet_spot_col = (60, 200, 60) # 초록색

        ss_x0 = gx + (sweet_spot_center - sweet_spot_half_w) * gw
        ss_x1 = gx + (sweet_spot_center + sweet_spot_half_w) * gw
        pygame.draw.rect(surf, sweet_spot_col, (ss_x0, gy, ss_x1 - ss_x0, gh), border_radius=4)

        # 파워장타 구간 그리기 (파란색, 장타 구간 안쪽)
        power_sweet_spot_half_w = self._pwr_power_sweet_spot_half_width_value()
        power_sweet_spot_col = (60, 120, 200) # 파란색

        pss_x0 = gx + (sweet_spot_center - power_sweet_spot_half_w) * gw
        pss_x1 = gx + (sweet_spot_center + power_sweet_spot_half_w) * gw
        pygame.draw.rect(surf, power_sweet_spot_col, (pss_x0, gy, pss_x1 - pss_x0, gh), border_radius=4)

        # 새로운 함정 구간 그리기 (장타 구간 바로 옆, 빨간색)
        trap_half_w_new = self._pwr_trap_half_width_new()
        trap_col_new = (200, 58, 58) # 빨간색

        # 왼쪽 함정
        left_trap_x0 = gx + (sweet_spot_center - sweet_spot_half_w - trap_half_w_new) * gw
        left_trap_x1 = gx + (sweet_spot_center - sweet_spot_half_w) * gw
        pygame.draw.rect(surf, trap_col_new, (left_trap_x0, gy, left_trap_x1 - left_trap_x0, gh), border_radius=4)

        # 오른쪽 함정
        right_trap_x0 = gx + (sweet_spot_center + sweet_spot_half_w) * gw
        right_trap_x1 = gx + (sweet_spot_center + sweet_spot_half_w + trap_half_w_new) * gw
        pygame.draw.rect(surf, trap_col_new, (right_trap_x0, gy, right_trap_x1 - right_trap_x0, gh), border_radius=4)

        # 마커 그리기
        t = self._locked_pwr_marker_t if self.state == ST_PWR_CONFIRM else self._pwr_marker_t()
        lx = gx + int(t * gw)
        pygame.draw.line(surf, (255, 200, 90), (lx, gy - 4), (lx, gy + gh + 4), 3)
        font = self._ui_font(ctx, 11)
        if self.state == ST_PWR_CONFIRM:
            tip = font.render("파워 확정!", True, (255, 235, 140))
        else:
            tip = font.render("파워 — 화면 터치! (빨강=빗맞음)", True, (240, 248, 255))
        surf.blit(tip, (w // 2 - tip.get_width() // 2, gy - 22))
        if self.state != ST_PWR_CONFIRM:
            self._draw_gauge_timer(ctx, gy - 38)

    def _draw_ball_world(
        self, ctx: FieldDrawContext, gx: float, gy: float, h: float
    ) -> None:
        sx, sy = _world_to_screen(ctx, gx, gy - h)
        shx, shy = _world_to_screen(ctx, gx, gy)
        sh_col = (120, 40, 40, 90) if self._is_foul else (20, 20, 30, 90)
        pygame.draw.ellipse(ctx.surf, sh_col, (shx - 6, shy - 2, 12, 5))
        ball = self._ball_item
        img = None
        if ball is not None:
            frames = getattr(ball, "frames", None) or []
            if frames:
                img = frames[int(getattr(ball, "frame_idx", 0) or 0) % len(frames)]
            elif getattr(ball, "image", None) is not None:
                img = ball.image
        if img is not None:
            try:
                z = max(0.5, float(ctx.z))
                iw, ih = img.get_size()
                dw = max(1, int(round(iw * z)))
                dh = max(1, int(round(ih * z)))
                if dw != iw or dh != ih:
                    img = pygame.transform.scale(img, (dw, dh))
                ctx.surf.blit(img, (int(sx - dw // 2), int(sy - dh // 2)))
                return
            except Exception:
                pass
        pygame.draw.circle(ctx.surf, (255, 248, 240), (sx, sy), max(3, int(5 * ctx.z)))

    def _draw_ball_flight(self, ctx: FieldDrawContext) -> None:
        if self._ball_held_by_catcher():
            return
        gx, gy, h = self._ball_flight_state()
        self._draw_ball_world(ctx, gx, gy, h)

    def _draw_ball_frozen(self, ctx: FieldDrawContext) -> None:
        if self._ball_held_by_catcher():
            return
        gx, gy = self._scene_ball_xy
        self._draw_ball_world(ctx, float(gx), float(gy), 0.0)

    def _draw_zone_ground_markers(self, ctx: FieldDrawContext) -> None:
        for o in self._zone_objs or []:
            if not zone_uses_ellipse_fallback(o):
                continue
            draw_zone_ellipse_on_surface(
                ctx.surf,
                o,
                world_to_xy=lambda wx, wy, _c=ctx: _world_to_screen(_c, float(wx), float(wy)),
            )

    def draw_world(self, ctx: FieldDrawContext) -> None:
        """월드 줌 전 — 공(대기·비행)·대기 상대·전광판 스코어."""
        self._draw_zone_ground_markers(ctx)
        self._draw_waiting_opponent(ctx)
        if self.state == ST_ANNOUNCE and self._scene_frozen:
            self._draw_ball_frozen(ctx)
        elif self.state in (ST_BAT_DIR, ST_BAT_PWR, ST_SWING_PAUSE, ST_POWER_SWING_PAUSE, ST_TURN_WAIT, ST_ANNOUNCE, ST_FIELD_INTRO):
            self._draw_ball_at_rest(ctx)
        show_fan_guide = bool(self.field.get("fan_half_guide_visible", _cfg("fan_half_guide_visible", True)))
        if show_fan_guide and self.state in (ST_BAT_DIR, ST_BAT_PWR):
            self._draw_fan_half_debug_world(ctx)
        if self.state == ST_FLIGHT:
            self._draw_ball_flight(ctx)

    def _draw_fan_half_debug_world(self, ctx: FieldDrawContext) -> None:
        """fan_half_deg를 맵 위에서 눈으로 맞추기 위한 파울라인(부채꼴) 표시."""
        surf = ctx.surf
        try:
            ox, oy = float(self.ball_rest_xy[0]), float(self.ball_rest_xy[1])
        except Exception:
            return
        half = max(1.0, float(self._fan_half_deg))
        # +X(오른쪽) 기준 ±half_deg (gauge와 동일)
        a0 = math.radians(-half)
        a1 = math.radians(+half)
        length = max(120.0, min(1800.0, float(self._max_carry)))
        p0 = (ox + math.cos(a0) * length, oy + math.sin(a0) * length)
        p1 = (ox + math.cos(a1) * length, oy + math.sin(a1) * length)
        sx0, sy0 = _world_to_screen(ctx, ox, oy)
        sx1, sy1 = _world_to_screen(ctx, float(p0[0]), float(p0[1]))
        sx2, sy2 = _world_to_screen(ctx, float(p1[0]), float(p1[1]))
        col = (255, 220, 80)
        try:
            pygame.draw.line(surf, col, (int(sx0), int(sy0)), (int(sx1), int(sy1)), 2)
            pygame.draw.line(surf, col, (int(sx0), int(sy0)), (int(sx2), int(sy2)), 2)
        except Exception:
            pass

    def draw_screen(self, ctx: FieldDrawContext) -> None:
        """월드 줌 후 논리 화면 — 메뉴·게이지·결과."""
        surf = ctx.surf
        self._ui_screen_wh = (max(1, int(surf.get_width())), max(1, int(surf.get_height())))
        if self.state in (
            ST_MENU,
            ST_MENU_SOLO,
            ST_MENU_DUO,
            ST_DIFFICULTY,
            ST_PICK_P2,
            ST_PICK_CHAR,
            ST_REPLAY_ASK,
        ):
            self._draw_menu(ctx)
            return
        if self.state == ST_RECORDS:
            self._draw_records(ctx)
            return
        if self.state == ST_LEADERBOARD:
            self._draw_leaderboard(ctx)
            return
        if self.state == ST_ANNOUNCE:
            self._draw_announce_overlay(ctx)
            return

        font = self._ui_font(ctx, 11)
        if self._msg:
            tip = font.render(self._msg, True, (248, 252, 255))
            surf.blit(tip, (8, surf.get_height() - 16))

        if self.state == ST_BAT_DIR:
            self._draw_fan_gauge(ctx)
        elif self.state in (ST_BAT_PWR, ST_PWR_CONFIRM):
            self._draw_pwr_gauge(ctx)
        elif self.state == ST_NPC_SHOW:
            t = font.render(
                f"{self._npc_name} 타격… {self._format_meters(self._npc_flash_dist)}m",
                True,
                (255, 220, 160),
            )
            surf.blit(t, (surf.get_width() // 2 - t.get_width() // 2, 24))
        elif self.state in (ST_MATCH_END, ST_DEMO_RESULT):
            self._draw_match_result(ctx)

        self._draw_scoreboards(ctx)
        self._draw_2p_switch_fade(ctx)

    def _draw_2p_switch_fade(self, ctx: FieldDrawContext) -> None:
        a = max(0, min(255, int(self._p2_switch_fade_alpha or 0)))
        if a <= 0:
            return
        overlay = pygame.Surface(ctx.surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, a))
        ctx.surf.blit(overlay, (0, 0))

    def draw(self, ctx: FieldDrawContext) -> None:
        self.draw_world(ctx)
        self.draw_screen(ctx)

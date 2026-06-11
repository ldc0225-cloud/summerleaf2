import pygame, os, math, uuid
import heapq
from collections import deque

from data import CONFIG, OBJ_ASSETS, CHAR_ASSETS, UI_FONT_FILES
try:
    from android_fix import resolve_asset_dir, resolve_asset_path
except Exception:
    def resolve_asset_path(path):
        return path

    def resolve_asset_dir(rel_dir):
        try:
            if os.path.isdir(rel_dir):
                return rel_dir
        except Exception:
            pass
        return None
from flow import evaluate_event_step_condition, evaluate_global_condition
from render_align import (
    blit_topleft_bottom_center,
    blit_topleft_center_on_pixel,
    left_edge_bottom_center_x,
    snap_render_zoom,
)
from field_runtime import (
    PARALLEL_EFFECT_STEP_TYPES,
    effect_now_ms,
    parse_camera_step,
    parse_shear_step,
    parse_tilt_step,
    parse_zoom_step,
    timed_effect_finished,
    timed_effect_init,
    timed_effect_value,
)

# --- global image caches (reduce duplicate loads, critical for 1GB devices) ---
_IMG_CACHE = {}   # abs_path -> pygame.Surface
_ANIM_CACHE = {}  # norm_dir_path -> [pygame.Surface, ...]  (오브젝트 등)
_CHAR_ANIM_CACHE = {}  # (norm_dir, state, direction) -> [pygame.Surface, ...]

# --- swing prototype caches (kept here to slim main.py) ---
_SWING_IMG_IDLE = None
_SWING_IMG_FORWARD = None
_SWING_IMG_BACK = None


def _swing_world_state(swing_t0_ms: int = 0, *, theta_amp_override=None):
    """
    그네 프로토타입의 현재 상태를 월드 좌표로 계산한다.
    A: 중심/상단 앵커(ax_w, ay_w) 높이 a_h
    B: 그네 좌석 중심(bx_w, by_w) 높이 b_h
    """
    p = CONFIG.get("SWING_BASE_XY", [810, 1900]) or [810, 1900]
    base_x, base_y = float(p[0]), float(p[1])
    a_h = float(CONFIG.get("SWING_A_HEIGHT", 50.0))
    b_rest_h = float(CONFIG.get("SWING_B_REST_HEIGHT", 10.0))
    L = max(1.0, float(a_h) - float(b_rest_h))

    now_ms = pygame.time.get_ticks()
    tsec = max(0.0, float(now_ms - int(swing_t0_ms)) / 1000.0)
    try:
        hz = float(CONFIG.get("SWING_HZ", 0.75))
    except Exception:
        hz = 0.75
    hz = max(0.05, min(3.0, hz))
    omega = 2.0 * math.pi * float(hz)
    try:
        tau = float(CONFIG.get("SWING_DAMP_TAU_SEC", 10.0))
    except Exception:
        tau = 10.0
    tau = max(0.2, min(120.0, tau))
    # amplitude: default is damped theta0, but can be overridden externally (ride/pump demo)
    if theta_amp_override is not None:
        try:
            theta_amp = float(theta_amp_override)
        except Exception:
            theta_amp = None
        if theta_amp is None:
            theta_amp_override = None
        else:
            theta_amp = max(0.0, min(1.35, theta_amp))
    if theta_amp_override is None:
        try:
            theta0 = float(CONFIG.get("SWING_THETA0_RAD", 0.85))
        except Exception:
            theta0 = 0.85
        theta0 = max(0.0, min(1.35, theta0))
        theta_amp = float(theta0) * math.exp(-tsec / float(tau))
    if theta_amp < 1e-3:
        theta = 0.0
    else:
        theta = theta_amp * math.cos(omega * tsec)

    depth = float(L) * math.sin(theta)
    vdrop = float(L) * max(0.0, math.cos(theta))
    b_h = float(a_h) - float(vdrop)

    try:
        fmul = float(CONFIG.get("SWING_DEPTH_TO_Y_FORWARD", 1.0))
    except Exception:
        fmul = 1.0
    try:
        bmul = float(CONFIG.get("SWING_DEPTH_TO_Y_BACK", 1.0))
    except Exception:
        bmul = 1.0
    fmul = max(0.0, min(3.0, fmul))
    bmul = max(0.0, min(3.0, bmul))
    depth_to_y = fmul if depth >= 0.0 else bmul

    ax_w, ay_w = float(base_x), float(base_y)
    bx_w, by_w = float(base_x), float(base_y) + float(depth) * float(depth_to_y)
    # derived helpers (for jump window / UI):
    try:
        depth_n = float(depth) / float(L)
    except Exception:
        depth_n = 0.0
    try:
        depth_peak_n = abs(math.sin(float(theta_amp)))
    except Exception:
        depth_peak_n = 0.0
    depth_peak_n = max(0.0, min(1.0, float(depth_peak_n)))
    return {
        "ax_w": ax_w,
        "ay_w": ay_w,
        "a_h": a_h,
        "bx_w": bx_w,
        "by_w": by_w,
        "b_h": b_h,
        "L": L,
        "depth": depth,
        "depth_n": float(depth_n),
        "depth_peak_n": float(depth_peak_n),
        "theta": float(theta),
        "theta_amp": float(theta_amp),
        "tsec": float(tsec),
        "omega": float(omega),
    }


def swing_world_state(swing_t0_ms: int = 0, *, theta_amp_override=None):
    """Public wrapper for swing prototype world state (for main loop interactions)."""
    return _swing_world_state(int(swing_t0_ms or 0), theta_amp_override=theta_amp_override)


class SwingPrototypeEntity:
    """그네(좌석+끈)를 하나의 엔티티로 만들어 ysort에 포함."""

    __slots__ = ("pos", "layer", "ysort_mode", "is_held", "visible", "swing_t0_ms", "theta_amp_override")

    def __init__(self, swing_t0_ms: int = 0):
        self.pos = [0.0, 0.0]
        self.layer = 0
        self.ysort_mode = "ground"
        self.is_held = False
        self.visible = True
        self.swing_t0_ms = int(swing_t0_ms or 0)
        self.theta_amp_override = None

    def update_sort_pos(self):
        try:
            st = _swing_world_state(int(self.swing_t0_ms), theta_amp_override=getattr(self, "theta_amp_override", None))
            self.pos[0] = float(st["bx_w"])
            self.pos[1] = float(st["by_w"])
        except Exception:
            pass

    def draw(self, screen, cam_x, cam_y, zoom=1.0, jump_shadow_mode=None, y_transform=None, x_offset_fn=None, sprite_perspective_q=None, shear_lod=False):
        # cam_x/cam_y는 main에서 넘기는 cam_draw_x/cam_draw_y
        global _SWING_IMG_IDLE, _SWING_IMG_FORWARD, _SWING_IMG_BACK
        if not self.visible:
            return False

        try:
            st = _swing_world_state(int(self.swing_t0_ms), theta_amp_override=getattr(self, "theta_amp_override", None))
            ax_w, ay_w, a_h = float(st["ax_w"]), float(st["ay_w"]), float(st["a_h"])
            bx_w, by_w, b_h = float(st["bx_w"]), float(st["by_w"]), float(st["b_h"])
            L = float(st["L"])
            depth = float(st["depth"])
        except Exception:
            return False

        def _world_to_screen(wx, wy, h_world):
            sx = (float(wx) - float(cam_x)) * float(zoom)
            sy = (float(wy) - float(cam_y)) * float(zoom)
            if callable(y_transform):
                try:
                    sy = float(y_transform(sy))
                except Exception:
                    pass
            if callable(x_offset_fn):
                try:
                    sy_q = float(int(round(float(sy))))
                    sx = float(sx) + float(x_offset_fn(float(sy_q)))
                except Exception:
                    pass
            sy = float(sy) - float(h_world) * float(zoom)
            return sx, sy

        ax_s, ay_s = _world_to_screen(ax_w, ay_w, a_h)
        bx_s, by_s = _world_to_screen(bx_w, by_w, b_h)
        ax_i, ay_i = int(round(ax_s)), int(round(ay_s))
        bx_i, by_i = int(round(bx_s)), int(round(by_s))

        # shadow on ground (reuse feet shadow if enabled)
        try:
            if bool(CONFIG.get("CHARACTER_SHADOW_ENABLED", True)):
                try:
                    s_mul = float(CONFIG.get("SWING_SHADOW_SIZE_MUL", 1.0))
                except Exception:
                    s_mul = 1.0
                try:
                    a_mul = float(CONFIG.get("SWING_SHADOW_ALPHA_MUL", 1.0))
                except Exception:
                    a_mul = 1.0
                s_mul = max(0.15, min(3.0, s_mul))
                a_mul = max(0.0, min(2.0, a_mul))
                _blit_feet_shadow(
                    screen,
                    float(bx_w),
                    float(by_w),
                    float(cam_x),
                    float(cam_y),
                    float(zoom),
                    size_scale=float(s_mul),
                    alpha_scale=float(a_mul),
                    y_transform=y_transform,
                    x_offset_fn=x_offset_fn,
                    entity_scale_mul=1.0,
                )
        except Exception:
            pass

        # ropes: 2 lines, 좌우 약 10px 간격
        try:
            rope_gap = float(CONFIG.get("SWING_ROPE_HALF_GAP_PX", 10.0))
        except Exception:
            rope_gap = 10.0
        rope_gap = max(2.0, min(40.0, rope_gap))
        dx = int(round(rope_gap))
        col = (255, 0, 0)
        pygame.draw.line(screen, col, (ax_i - dx, ay_i), (bx_i - dx, by_i), 2)
        pygame.draw.line(screen, col, (ax_i + dx, ay_i), (bx_i + dx, by_i), 2)

        # load images once
        if _SWING_IMG_IDLE is None:
            _SWING_IMG_IDLE = _load_image_cached(str(CONFIG.get("SWING_IMG_IDLE", "assets/images/swing1.png"))) or False
        if _SWING_IMG_FORWARD is None:
            _SWING_IMG_FORWARD = _load_image_cached(str(CONFIG.get("SWING_IMG_FORWARD", "assets/images/swing2.png"))) or False
        if _SWING_IMG_BACK is None:
            _SWING_IMG_BACK = _load_image_cached(str(CONFIG.get("SWING_IMG_BACK", "assets/images/swing3.png"))) or False

        try:
            depth_n = float(depth) / float(L)
        except Exception:
            depth_n = 0.0
        try:
            th_f = float(CONFIG.get("SWING_POSE_THRESH_FORWARD", 0.45))
        except Exception:
            th_f = 0.45
        try:
            th_b = float(CONFIG.get("SWING_POSE_THRESH_BACK", 0.45))
        except Exception:
            th_b = 0.45
        th_f = max(0.05, min(0.95, th_f))
        th_b = max(0.05, min(0.95, th_b))

        if depth_n >= th_f and _SWING_IMG_FORWARD:
            src_img = _SWING_IMG_FORWARD
        elif depth_n <= -th_b and _SWING_IMG_BACK:
            src_img = _SWING_IMG_BACK
        else:
            src_img = _SWING_IMG_IDLE if _SWING_IMG_IDLE else False

        sz = CONFIG.get("SWING_SPRITE_SIZE", [36, 10]) or [36, 10]
        try:
            sw0 = int(sz[0])
            sh0 = int(sz[1])
        except Exception:
            sw0, sh0 = 36, 10
        sw = max(1, int(round(float(sw0) * float(zoom))))
        sh = max(1, int(round(float(sh0) * float(zoom))))
        left = int(round(float(bx_i) - sw / 2.0))
        top = int(round(float(by_i) - sh / 2.0))
        if src_img:
            img = src_img
            if img.get_width() != sw or img.get_height() != sh:
                img = pygame.transform.scale(src_img, (sw, sh))
            screen.blit(img, (left, top))
        else:
            pygame.draw.rect(screen, (200, 200, 255), pygame.Rect(left, top, sw, sh), 1)
        return True


def _load_image_cached(path: str):
    """Load PNG once per path; returns shared Surface."""
    p = os.path.normpath(path)
    img = _IMG_CACHE.get(p)
    if img is not None:
        return img
    try:
        img = pygame.image.load(p).convert_alpha()
    except Exception:
        return None
    _IMG_CACHE[p] = img
    # defensive cap: avoid unbounded growth on dev machines
    if len(_IMG_CACHE) > 2048:
        _IMG_CACHE.clear()
        _IMG_CACHE[p] = img
    return img


def draw_swing_prototype(
    screen,
    *,
    cam,
    cam_draw_x: float,
    cam_draw_y: float,
    y_transform=None,
    x_offset_fn=None,
    swing_t0_ms: int = 0,
):
    """
    Prototype: height-based 3D pendulum swing drawing.
    - Moved out of main.py to keep main loop small.
    - Uses CONFIG for params/resources.
    """
    global _SWING_IMG_IDLE, _SWING_IMG_FORWARD, _SWING_IMG_BACK
    try:
        p = CONFIG.get("SWING_BASE_XY", [810, 1900]) or [810, 1900]
        base_x, base_y = float(p[0]), float(p[1])
        a_h = float(CONFIG.get("SWING_A_HEIGHT", 50.0))
        b_rest_h = float(CONFIG.get("SWING_B_REST_HEIGHT", 10.0))
        L = max(1.0, float(a_h) - float(b_rest_h))

        now_ms = pygame.time.get_ticks()
        tsec = max(0.0, float(now_ms - int(swing_t0_ms)) / 1000.0)
        try:
            hz = float(CONFIG.get("SWING_HZ", 0.75))
        except Exception:
            hz = 0.75
        hz = max(0.05, min(3.0, hz))
        omega = 2.0 * math.pi * float(hz)
        try:
            tau = float(CONFIG.get("SWING_DAMP_TAU_SEC", 10.0))
        except Exception:
            tau = 10.0
        tau = max(0.2, min(120.0, tau))
        try:
            theta0 = float(CONFIG.get("SWING_THETA0_RAD", 0.85))
        except Exception:
            theta0 = 0.85
        theta0 = max(0.0, min(1.35, theta0))

        theta_amp = float(theta0) * math.exp(-tsec / float(tau))
        if theta_amp < 1e-3:
            theta = 0.0
        else:
            theta = theta_amp * math.cos(omega * tsec)

        depth = float(L) * math.sin(theta)
        vdrop = float(L) * max(0.0, math.cos(theta))
        b_h = float(a_h) - float(vdrop)

        try:
            fmul = float(CONFIG.get("SWING_DEPTH_TO_Y_FORWARD", 1.0))
        except Exception:
            fmul = 1.0
        try:
            bmul = float(CONFIG.get("SWING_DEPTH_TO_Y_BACK", 1.0))
        except Exception:
            bmul = 1.0
        fmul = max(0.0, min(3.0, fmul))
        bmul = max(0.0, min(3.0, bmul))
        depth_to_y = fmul if depth >= 0.0 else bmul
        ax_w, ay_w = float(base_x), float(base_y)
        bx_w, by_w = float(base_x), float(base_y) + float(depth) * float(depth_to_y)

        def _world_to_screen(wx, wy, h_world):
            sx = (float(wx) - float(cam_draw_x)) * float(cam.current_zoom)
            sy = (float(wy) - float(cam_draw_y)) * float(cam.current_zoom)
            if callable(y_transform):
                sy = float(y_transform(sy))
            if callable(x_offset_fn):
                sx = float(sx) + float(x_offset_fn(sy))
            sy = float(sy) - float(h_world) * float(cam.current_zoom)
            return sx, sy

        ax_s, ay_s = _world_to_screen(ax_w, ay_w, a_h)
        bx_s, by_s = _world_to_screen(bx_w, by_w, b_h)

        # shadow on ground (reuse feet shadow if enabled)
        try:
            if bool(CONFIG.get("CHARACTER_SHADOW_ENABLED", True)):
                try:
                    s_mul = float(CONFIG.get("SWING_SHADOW_SIZE_MUL", 1.0))
                except Exception:
                    s_mul = 1.0
                try:
                    a_mul = float(CONFIG.get("SWING_SHADOW_ALPHA_MUL", 1.0))
                except Exception:
                    a_mul = 1.0
                s_mul = max(0.15, min(3.0, s_mul))
                a_mul = max(0.0, min(2.0, a_mul))
                _blit_feet_shadow(
                    screen,
                    float(bx_w),
                    float(by_w),
                    float(cam_draw_x),
                    float(cam_draw_y),
                    float(cam.current_zoom),
                    size_scale=float(s_mul),
                    alpha_scale=float(a_mul),
                    y_transform=y_transform,
                    x_offset_fn=x_offset_fn,
                    entity_scale_mul=1.0,
                )
        except Exception:
            pass

        ax_i, ay_i = int(round(ax_s)), int(round(ay_s))
        bx_i, by_i = int(round(bx_s)), int(round(by_s))

        # ropes: 2 lines, 좌우 약 10px 간격
        try:
            rope_gap = float(CONFIG.get("SWING_ROPE_HALF_GAP_PX", 10.0))
        except Exception:
            rope_gap = 10.0
        rope_gap = max(2.0, min(40.0, rope_gap))
        dx = int(round(rope_gap))
        col = (255, 0, 0)
        pygame.draw.line(screen, col, (ax_i - dx, ay_i), (bx_i - dx, by_i), 2)
        pygame.draw.line(screen, col, (ax_i + dx, ay_i), (bx_i + dx, by_i), 2)

        # load images once
        if _SWING_IMG_IDLE is None:
            _SWING_IMG_IDLE = _load_image_cached(str(CONFIG.get("SWING_IMG_IDLE", "assets/images/swing1.png"))) or False
        if _SWING_IMG_FORWARD is None:
            _SWING_IMG_FORWARD = _load_image_cached(str(CONFIG.get("SWING_IMG_FORWARD", "assets/images/swing2.png"))) or False
        if _SWING_IMG_BACK is None:
            _SWING_IMG_BACK = _load_image_cached(str(CONFIG.get("SWING_IMG_BACK", "assets/images/swing3.png"))) or False

        try:
            depth_n = float(depth) / float(L)
        except Exception:
            depth_n = 0.0
        try:
            th_f = float(CONFIG.get("SWING_POSE_THRESH_FORWARD", 0.45))
        except Exception:
            th_f = 0.45
        try:
            th_b = float(CONFIG.get("SWING_POSE_THRESH_BACK", 0.45))
        except Exception:
            th_b = 0.45
        th_f = max(0.05, min(0.95, th_f))
        th_b = max(0.05, min(0.95, th_b))

        if depth_n >= th_f and _SWING_IMG_FORWARD:
            src_img = _SWING_IMG_FORWARD
        elif depth_n <= -th_b and _SWING_IMG_BACK:
            src_img = _SWING_IMG_BACK
        else:
            src_img = _SWING_IMG_IDLE if _SWING_IMG_IDLE else False

        sz = CONFIG.get("SWING_SPRITE_SIZE", [36, 10]) or [36, 10]
        try:
            sw0 = int(sz[0])
            sh0 = int(sz[1])
        except Exception:
            sw0, sh0 = 36, 10
        sw = max(1, int(round(float(sw0) * float(cam.current_zoom))))
        sh = max(1, int(round(float(sh0) * float(cam.current_zoom))))
        left = int(round(float(bx_i) - sw / 2.0))
        top = int(round(float(by_i) - sh / 2.0))
        if src_img:
            img = src_img
            if img.get_width() != sw or img.get_height() != sh:
                img = pygame.transform.scale(src_img, (sw, sh))
            screen.blit(img, (left, top))
        else:
            pygame.draw.rect(screen, (200, 200, 255), pygame.Rect(left, top, sw, sh), 1)
    except Exception:
        return False
    return True


def _load_anim_dir_cached(dir_path: str):
    """Load frame directory once; returns shared list of Surfaces."""
    d = os.path.normpath(dir_path)
    cached = _ANIM_CACHE.get(d)
    if cached is not None:
        return cached
    if not (os.path.exists(d) and os.path.isdir(d)):
        return None
    try:
        files = sorted(
            [f for f in os.listdir(d) if f.endswith(".png")],
            key=lambda x: int("".join(filter(str.isdigit, x)) or "0"),
        )
    except Exception:
        files = []
    frames = []
    for f in files:
        img = _load_image_cached(os.path.join(d, f))
        if img is not None:
            frames.append(img)
    if not frames:
        return None
    _ANIM_CACHE[d] = frames
    if len(_ANIM_CACHE) > 512:
        _ANIM_CACHE.clear()
        _ANIM_CACHE[d] = frames
    return frames


def _numbered_stem_from_obj_path(rel_path: str):
    """
  OBJ path → numbered sequence stem (assets 기준 상대 경로, _0 생략).
  - images/object/flower1_0.png → images/object/flower1
  - images/object/flower1 (확장자 없음) → images/object/flower1
  - images/object/flower1.png → None (단일 PNG)
    """
    p = str(rel_path or "").strip().replace("\\", "/")
    if not p:
        return None
    base, ext = os.path.splitext(p)
    if ext.lower() != ".png":
        return p
    stem_name = os.path.basename(base)
    if "_" in stem_name:
        prefix, suffix = stem_name.rsplit("_", 1)
        if suffix.isdigit():
            parent = os.path.dirname(base).replace("\\", "/")
            return f"{parent}/{prefix}" if parent else prefix
    return None


def _assets_path_from_rel(rel_path: str) -> str:
    p = str(rel_path or "").strip().replace("\\", "/")
    if p.startswith("assets/"):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join("assets", p.replace("/", os.sep)))


def _load_obj_asset_frames(rel_path: str, *, max_frames: int = 64):
    """
  OBJ_ASSETS path 로드: 폴더 / name_0.png 연속 / 단일 PNG.
  _0만 있으면 1프레임(정지), _1… 이 있으면 애니메이션.
    """
    if not rel_path:
        return None
    mf = max(1, min(128, int(max_frames or 64)))
    full = _assets_path_from_rel(rel_path)
    if os.path.isdir(full):
        return _load_anim_dir_cached(full)
    stem = _numbered_stem_from_obj_path(rel_path)
    if stem is not None:
        frames = _load_numbered_ui_sequence(stem, max_frames=mf)
        if frames:
            return frames
    surf = _load_image_cached(full)
    if surf is not None:
        return [surf]
    return None


def _obj_anim_delay_ms(info: dict) -> int:
    """OBJ_ASSETS anim_delay_ms(또는 anim_delay). 없으면 CONFIG['ANIM_DELAY']."""
    if not info:
        info = {}
    raw = info.get("anim_delay_ms", info.get("anim_delay"))
    if raw is not None and str(raw).strip() != "":
        try:
            return max(16, int(float(raw)))
        except Exception:
            pass
    try:
        return max(16, int(float(CONFIG.get("ANIM_DELAY", 150) or 150)))
    except Exception:
        return 150


def _char_anim_stem_matches(stem: str, prefix: str) -> bool:
    """프레임 stem이 동작 접두사와 일치: idle_left / idle_left_0 …"""
    return stem == prefix or stem.startswith(prefix + "_")


def _char_anim_sort_key(filename: str):
    stem, _ext = os.path.splitext(filename)
    return int("".join(filter(str.isdigit, stem)) or "0")


def _load_char_anim_dir_cached(dir_path: str, state: str, direction: str, char_name: str):
    """
    character/<이름>/<동작>_<방향>/ 안의 PNG만 로드.
    우선: walk_left.png, walk_left_0.png … (캐릭터 이름 없음)
    없으면: summer_walk_left_0.png … (구 자산 호환)
    """
    d = os.path.normpath(dir_path)
    cache_key = (d, str(state), str(direction))
    cached = _CHAR_ANIM_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if not (os.path.exists(d) and os.path.isdir(d)):
        return None
    action_prefix = f"{state}_{direction}"
    try:
        pngs = [f for f in os.listdir(d) if f.lower().endswith(".png")]
    except Exception:
        pngs = []
    stems = [(f, os.path.splitext(f)[0]) for f in pngs]
    new_files = [f for f, stem in stems if _char_anim_stem_matches(stem, action_prefix)]
    if new_files:
        files = sorted(new_files, key=_char_anim_sort_key)
    else:
        legacy_prefix = f"{char_name}_{action_prefix}" if char_name else ""
        legacy_files = [f for f, stem in stems if legacy_prefix and _char_anim_stem_matches(stem, legacy_prefix)]
        files = sorted(legacy_files, key=_char_anim_sort_key)
    frames = []
    for f in files:
        img = _load_image_cached(os.path.join(d, f))
        if img is not None:
            frames.append(img)
    if not frames:
        return None
    _CHAR_ANIM_CACHE[cache_key] = frames
    if len(_CHAR_ANIM_CACHE) > 512:
        _CHAR_ANIM_CACHE.clear()
        _CHAR_ANIM_CACHE[cache_key] = frames
    return frames


def cache_estimated_mb():
    """
    Rough memory estimate of cached Surfaces (RGBA assumed ~4 bytes/pixel).
    Returns dict with counts + MB.
    """
    img_px = 0
    img_cnt = 0
    for _p, surf in list(_IMG_CACHE.items()):
        try:
            w, h = surf.get_size()
            img_px += int(w) * int(h)
            img_cnt += 1
        except Exception:
            pass
    anim_frames = 0
    anim_dirs = 0
    for _d, frames in list(_ANIM_CACHE.items()):
        anim_dirs += 1
        try:
            anim_frames += len(frames or [])
        except Exception:
            pass
    for _k, frames in list(_CHAR_ANIM_CACHE.items()):
        anim_dirs += 1
        try:
            anim_frames += len(frames or [])
        except Exception:
            pass
    # 4 bytes per pixel (very rough)
    img_mb = (float(img_px) * 4.0) / (1024.0 * 1024.0)
    return {
        "img_count": img_cnt,
        "anim_dirs": anim_dirs,
        "anim_frames": anim_frames,
        "img_est_mb": img_mb,
    }


def _clamp_draw_height(v):
    """스프라이트를 발 기준 위로 올리는 높이(월드 픽셀). 화면에서는 zoom 후 틸트와 별도로 적용."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(4000.0, x))


def _clamp_sprite_tilt(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, x))


def _apply_sprite_perspective_squash(render_img, sprite_perspective_q, sprite_tilt):
    """
    배경 원근(세로 압축 계수 f_q)에 맞춰 스프라이트 높이를 섞는다.
    sprite_tilt==1 → 비트맵 높이 유지(지금과 같이 '꼿꼿이').
    sprite_tilt==0 → 높이 비율이 배경과 동일(바닥에 붙은 느낌).
    """
    if render_img is None or sprite_perspective_q is None:
        return render_img
    try:
        fq = float(sprite_perspective_q)
    except (TypeError, ValueError):
        return render_img
    if fq >= 1.0 - 1e-5:
        return render_img
    t = _clamp_sprite_tilt(sprite_tilt)
    sprite_fq = fq + (1.0 - fq) * t
    if sprite_fq >= 1.0 - 1e-5:
        return render_img
    try:
        rw, rh = render_img.get_size()
    except Exception:
        return render_img
    nh = max(1, int(round(rh * sprite_fq)))
    if nh == rh:
        return render_img
    return pygame.transform.scale(render_img, (rw, nh))


# --- sprite scaling cache (reduce per-frame transform.scale cost) ---
try:
    from collections import OrderedDict
except Exception:
    OrderedDict = dict  # type: ignore

_SPRITE_SCALE_CACHE = OrderedDict()  # key -> (Surface, est_mb)
_SPRITE_SCALE_CACHE_MB = 0.0


def _est_rgba_mb(w: int, h: int) -> float:
    try:
        return (float(int(w)) * float(int(h)) * 4.0) / (1024.0 * 1024.0)
    except Exception:
        return 0.0


def _sprite_cache_get(key):
    v = _SPRITE_SCALE_CACHE.get(key)
    if v is None:
        return None
    try:
        _SPRITE_SCALE_CACHE.move_to_end(key)
    except Exception:
        pass
    return v[0]


def _sprite_cache_put(key, surf):
    global _SPRITE_SCALE_CACHE_MB
    if surf is None:
        return
    try:
        w, h = surf.get_size()
    except Exception:
        return
    est = _est_rgba_mb(w, h)
    try:
        mb_limit = float(CONFIG.get("SPRITE_SCALE_CACHE_MB_LIMIT", 96.0))
    except Exception:
        mb_limit = 96.0
    mb_limit = max(8.0, min(512.0, mb_limit))
    try:
        max_items = int(CONFIG.get("SPRITE_SCALE_CACHE_MAX_ITEMS", 512) or 512)
    except Exception:
        max_items = 512
    max_items = max(32, min(4096, max_items))
    if est <= 0.0 or est > mb_limit * 0.5:
        return
    old = _SPRITE_SCALE_CACHE.get(key)
    if old is not None:
        try:
            _SPRITE_SCALE_CACHE_MB -= float(old[1])
        except Exception:
            pass
        try:
            del _SPRITE_SCALE_CACHE[key]
        except Exception:
            pass
    try:
        while (_SPRITE_SCALE_CACHE_MB + est) > mb_limit and _SPRITE_SCALE_CACHE:
            _k, (_s, mb) = _SPRITE_SCALE_CACHE.popitem(last=False)
            try:
                _SPRITE_SCALE_CACHE_MB -= float(mb)
            except Exception:
                pass
        while len(_SPRITE_SCALE_CACHE) >= max_items and _SPRITE_SCALE_CACHE:
            _k, (_s, mb) = _SPRITE_SCALE_CACHE.popitem(last=False)
            try:
                _SPRITE_SCALE_CACHE_MB -= float(mb)
            except Exception:
                pass
    except Exception:
        _SPRITE_SCALE_CACHE.clear()
        _SPRITE_SCALE_CACHE_MB = 0.0
    _SPRITE_SCALE_CACHE[key] = (surf, float(est))
    _SPRITE_SCALE_CACHE_MB += float(est)


def get_cached_scaled_sprite(image, eff_zoom: float, sprite_perspective_q=None, sprite_tilt: float = 1.0):
    """Scale + perspective-squash with caching (best-effort)."""
    if image is None:
        return None
    try:
        step = float(CONFIG.get("SPRITE_SCALE_STEP", 0.1))
    except Exception:
        step = 0.1
    step = max(0.01, min(0.5, step))
    try:
        zq = round(round(float(eff_zoom) / step) * step, 4)
    except Exception:
        zq = float(eff_zoom)
    try:
        iw, ih = image.get_size()
    except Exception:
        return image
    sw = max(1, int(round(float(iw) * float(zq))))
    sh = max(1, int(round(float(ih) * float(zq))))
    try:
        pq = 0.0 if sprite_perspective_q is None else round(float(sprite_perspective_q), 4)
    except Exception:
        pq = 0.0
    try:
        st = round(float(sprite_tilt), 4)
    except Exception:
        st = 1.0
    key = ("spr", id(image), sw, sh, pq, st)
    got = _sprite_cache_get(key)
    if got is not None:
        return got
    if (sw, sh) != (iw, ih):
        try:
            scaled = pygame.transform.scale(image, (sw, sh))
        except Exception:
            scaled = image
    else:
        scaled = image
    out = _apply_sprite_perspective_squash(scaled, pq if pq > 0 else None, st)
    try:
        _sprite_cache_put(key, out)
    except Exception:
        pass
    return out


def _normalize_ysort_mode(v):
    """
    y-sorting 기준:
    - "ground": 기존과 동일하게 pos[1] (땅/앵커)
    - "visual": height를 뺀 pos[1]-height (올라간 이미지의 발 위치)
    """
    try:
        s = str(v).strip().lower()
    except Exception:
        return "ground"
    if s in ("visual", "image", "img", "height", "height_bottom"):
        return "visual"
    return "ground"


def _scan_music_library():
    """
    assets/musics 폴더를 스캔해서 {display_name: abs_path} 형태로 반환.
    - display_name: 확장자 제거 파일명
    """
    out = {}
    for rel in (os.path.join("assets", "musics"), os.path.join("assets", "music")):
        base_dir = resolve_asset_dir(rel)
        if not base_dir:
            continue
        try:
            for fn in sorted(os.listdir(base_dir)):
                if not fn:
                    continue
                low = fn.lower()
                if not (low.endswith(".mp3") or low.endswith(".ogg") or low.endswith(".wav")):
                    continue
                name = os.path.splitext(fn)[0]
                out[name] = os.path.join(base_dir, fn)
        except Exception:
            continue
    return out


def _shear_surface_by_field_xoffset(
    render_img: pygame.Surface,
    top_y_screen: float,
    bottom_y_screen: float,
    x_offset_fn,
    slice_h: int = 8,
):
    """
    배경 쉬어(x_offset_fn)를 스프라이트 자체에도 적용해 '사다리꼴/쉬어진' 느낌을 만든다.
    - bottom_y_screen에서의 x_offset을 기준(0)으로 삼고, 각 행의 (x_offset(y)-x_offset(bottom))만큼 shift.
    반환: (sheared_surface, dx_adjust)  dx_adjust를 blit x에 더하면 bottom 행 정렬이 유지됨.
    """
    if not callable(x_offset_fn):
        return render_img, 0
    try:
        w, h = render_img.get_size()
    except Exception:
        return render_img, 0
    if w <= 1 or h <= 1:
        return render_img, 0
    try:
        slice_h = int(slice_h)
    except Exception:
        slice_h = 8
    slice_h = max(1, min(64, slice_h))

    # 화면 Y가 1픽셀 미만으로 흔들릴 때 slice별 int(round) 오프셋이 ±1로 튀며 떨림이 난다.
    # 샘플 Y는 픽셀 그리드에 스냅해 쉬어 샘플링을 안정화한다.
    try:
        top_snap = float(round(float(top_y_screen)))
        bot_snap = float(round(float(bottom_y_screen)))
    except Exception:
        top_snap, bot_snap = float(top_y_screen), float(bottom_y_screen)
    try:
        base_off = float(x_offset_fn(bot_snap))
    except Exception:
        base_off = 0.0

    shifts = []
    for yy in range(0, h, slice_h):
        hh = min(slice_h, h - yy)
        try:
            mid = float(round(top_snap + float(yy) + 0.5 * float(hh)))
        except Exception:
            mid = top_snap + float(yy) + 0.5 * float(hh)
        try:
            off = float(x_offset_fn(mid))
        except Exception:
            off = base_off
        shifts.append(int(round(off - base_off)))

    if not shifts:
        return render_img, 0
    mn = min(shifts)
    mx = max(shifts)
    if mx - mn == 0:
        return render_img, 0

    out_w = w + (mx - mn)
    out = pygame.Surface((out_w, h), pygame.SRCALPHA)
    i = 0
    for yy in range(0, h, slice_h):
        hh = min(slice_h, h - yy)
        dx = (shifts[i] - mn)
        i += 1
        try:
            out.blit(render_img, (dx, yy), area=pygame.Rect(0, yy, w, hh))
        except Exception:
            pass
    # bottom 행은 shift=0 → 원래 x에 오도록 dx_adjust=mn 반환
    return out, int(mn)


class MusicManager:
    """
    pygame.mixer.music 기반의 간단 BGM 관리자.
    요구 기능:
    - 곡 시작 페이드인
    - 곡 종료/전환 페이드아웃(명령 기반)
    - 일시정지/재개
    - 다른 곡 실행 시: 기존 곡이 끝난 뒤 자동 재생(큐)
    - 재생 중인 곡 끝내기(즉시 stop)
    """

    def __init__(self):
        self.library = _scan_music_library()
        self.current_name = None
        self.current_path = None
        self._queued = None  # dict or None: {"name":..., "fade_in_ms":..., "loop":..., "volume":...}
        self._paused = False
        try:
            n = len(self.library)
            if n <= 0:
                print("[MUSIC] library empty (check assets/musics in APK)")
            else:
                print(f"[MUSIC] library: {n} track(s)")
        except Exception:
            pass

    def refresh_library(self):
        self.library = _scan_music_library()
        return list(self.library.keys())

    def list_tracks(self):
        return list(self.library.keys())

    def is_playing(self):
        try:
            return bool(pygame.mixer.music.get_busy()) and not self._paused
        except Exception:
            return False

    def is_paused(self):
        return bool(self._paused)

    def get_title(self):
        return self.current_name

    def _load_and_play(self, name, fade_in_ms=0, loop=False, volume=None):
        path = self.library.get(name)
        if not path:
            return False
        path = resolve_asset_path(path)
        try:
            if not os.path.isfile(path):
                print(f"[MUSIC] file missing: {path}")
                return False
            pygame.mixer.music.load(path)
            if volume is not None and volume != "":
                pygame.mixer.music.set_volume(max(0.0, min(1.0, float(volume))))
            pygame.mixer.music.play(-1 if loop else 0, fade_ms=max(0, int(fade_in_ms or 0)))
            self.current_name = name
            self.current_path = path
            self._paused = False
            return True
        except Exception as e:
            print(f"[MUSIC] load/play failed: {name} ({e})")
            return False

    def play(self, name, fade_in_ms=0, loop=False, volume=None, queue_after_current=True):
        """
        - queue_after_current=True: 지금 곡이 재생 중이면 끝난 뒤 재생(요구사항)
        - queue_after_current=False: 즉시 교체(기존 곡은 stop 후 새 곡 시작)
        """
        if not name:
            return False
        if name not in self.library:
            # 라이브러리 갱신 후 재시도
            self.refresh_library()
        if name not in self.library:
            print(f"[MUSIC] unknown track: {name}")
            return False
        try:
            busy = bool(pygame.mixer.music.get_busy())
        except Exception:
            busy = False
        if busy and queue_after_current:
            self._queued = {
                "name": name,
                "fade_in_ms": int(max(0, fade_in_ms or 0)),
                "loop": bool(loop),
                "volume": volume,
            }
            return True
        if busy and not queue_after_current:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        return self._load_and_play(name, fade_in_ms=fade_in_ms, loop=loop, volume=volume)

    def stop(self, fade_out_ms=200):
        """페이드아웃 후 정지."""
        self._queued = None
        self._paused = False
        try:
            pygame.mixer.music.fadeout(max(0, int(fade_out_ms or 0)))
        except Exception:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self.current_name = None
        self.current_path = None

    def end_now(self):
        """즉시 정지."""
        self._queued = None
        self._paused = False
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        self.current_name = None
        self.current_path = None

    def pause(self):
        try:
            pygame.mixer.music.pause()
            self._paused = True
        except Exception:
            pass

    def resume(self):
        try:
            pygame.mixer.music.unpause()
            self._paused = False
        except Exception:
            pass

    def update(self):
        """매 프레임 호출: 곡이 끝났으면 큐된 곡을 시작."""
        if not self._queued:
            return
        try:
            busy = bool(pygame.mixer.music.get_busy())
        except Exception:
            busy = False
        if busy:
            return
        q = self._queued
        self._queued = None
        self._load_and_play(q["name"], fade_in_ms=q.get("fade_in_ms", 0), loop=q.get("loop", False), volume=q.get("volume"))


def _smoothstep_unit(u):
    u = max(0.0, min(1.0, float(u)))
    return u * u * (3.0 - 2.0 * u)


def _lerp(a, b, t):
    return float(a) + (float(b) - float(a)) * float(t)


def _compute_jump_params(span_px, jump_max_gap_px, dist_px, jump_height_px=None):
    """
    도랑 폭(span)에 따라 점프 높이/시간을 자동 조절합니다.
    span_px는 _analyze_ditch_jump_land_only 반환값(도랑 구간 길이) 기준.
    jump_height_px(캐릭터 height)가 양수면 arc_h로 그대로 사용해 점프와 그리기 높이를 통일합니다.
    """
    try:
        jm = max(1e-6, float(jump_max_gap_px))
        s = max(0.0, float(span_px))
        u = max(0.0, min(1.0, s / jm))
    except Exception:
        u = 0.5

    h_min = float(CONFIG.get("JUMP_ARC_HEIGHT_MIN", 10))
    h_max = float(CONFIG.get("JUMP_ARC_HEIGHT_MAX", CONFIG.get("JUMP_ARC_HEIGHT", 22)))
    jh = _clamp_draw_height(jump_height_px) if jump_height_px is not None else 0.0
    if jh > 0.5:
        arc_h = jh
    else:
        arc_h = _lerp(h_min, h_max, u)

    dmin = int(CONFIG.get("JUMP_MIN_DURATION_MS", 220))
    dmax = int(CONFIG.get("JUMP_MAX_DURATION_MS", 520))
    dur_per_px = float(CONFIG.get("JUMP_DUR_PER_PX", 12.0))
    mul_min = float(CONFIG.get("JUMP_DUR_SPAN_MUL_MIN", 0.85))
    mul_max = float(CONFIG.get("JUMP_DUR_SPAN_MUL_MAX", 1.15))
    dur_mul = _lerp(mul_min, mul_max, u)
    dur = int(min(dmax, max(dmin, float(dist_px) * dur_per_px * dur_mul)))

    return arc_h, dur


def _blit_feet_shadow(
    screen,
    gx,
    gy,
    cam_x,
    cam_y,
    zoom,
    size_scale=1.0,
    alpha_scale=1.0,
    y_transform=None,
    x_offset_fn=None,
    entity_scale_mul=1.0,
):
    if not CONFIG.get("CHARACTER_SHADOW_ENABLED", True):
        return
    try:
        size_scale = max(0.15, float(size_scale))
        alpha_scale = max(0.0, float(alpha_scale))
    except (TypeError, ValueError):
        size_scale, alpha_scale = 1.0, 1.0
    if alpha_scale < 0.02:
        return
    try:
        entity_scale_mul = max(0.05, min(8.0, float(entity_scale_mul)))
    except (TypeError, ValueError):
        entity_scale_mul = 1.0
    offx = float(CONFIG.get("SHADOW_OFFSET_X", 5))
    offy = float(CONFIG.get("SHADOW_OFFSET_Y", 6))
    cx = (gx + offx - cam_x) * zoom
    cy = (gy + offy - cam_y) * zoom
    if callable(y_transform):
        try:
            cy = float(y_transform(float(cy)))
        except Exception:
            pass
    # tilt/shear에서 subpixel y 흔들림이 x_offset_fn 입력을 흔들어 떨림이 생길 수 있어,
    # x_offset_fn에는 정수 픽셀 y를 넣는다(가벼운 안정화).
    cy_q = float(int(round(float(cy))))
    if callable(x_offset_fn):
        try:
            cx = float(cx) + float(x_offset_fn(float(cy_q)))
        except Exception:
            pass
    base_rx = float(CONFIG.get("SHADOW_ELLIPSE_RX", 15))
    base_ry = float(CONFIG.get("SHADOW_ELLIPSE_RY", 7))
    rx = max(2, int(base_rx * zoom * size_scale * entity_scale_mul))
    ry = max(1, int(base_ry * zoom * size_scale * entity_scale_mul))
    col = CONFIG.get("SHADOW_COLOR", (18, 18, 38))
    r, g, b = int(col[0]), int(col[1]), int(col[2])
    base_alpha = float(CONFIG.get("SHADOW_BASE_ALPHA", 92))
    a = int(max(0, min(255, base_alpha * alpha_scale)))
    if a < 6:
        return
    # 성능: 발그림자는 엔티티 수만큼 호출되므로 매 프레임 Surface 생성/ellipse draw를 피한다.
    # (rx,ry,color,alpha)별로 작게 캐시.
    global _FEET_SHADOW_CACHE
    try:
        _FEET_SHADOW_CACHE
    except NameError:
        _FEET_SHADOW_CACHE = {}
    k = (int(rx), int(ry), int(r), int(g), int(b), int(a))
    surf = _FEET_SHADOW_CACHE.get(k)
    if surf is None:
        w, h = rx * 2 + 4, ry * 2 + 4
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        rect = pygame.Rect(2, 2, rx * 2, ry * 2)
        pygame.draw.ellipse(surf, (r, g, b, a), rect)
        _FEET_SHADOW_CACHE[k] = surf
        # 상한 초과 시 전체 비우기(간단/안전)
        if len(_FEET_SHADOW_CACHE) > 256:
            _FEET_SHADOW_CACHE.clear()
            _FEET_SHADOW_CACHE[k] = surf
    try:
        w, h = surf.get_size()
    except Exception:
        w, h = rx * 2 + 4, ry * 2 + 4
    cpx, cpy = int(round(cx)), int(round(cy))
    sx, sy = blit_topleft_center_on_pixel(cpx, cpy, w, h)
    screen.blit(surf, (sx, sy))


def _parse_loop_jump_table(steps):
    """LOOP_START / LOOP_END 짝을 맞춰 루프 끝 인덱스 → 루프 본문 시작 인덱스 테이블을 만듭니다."""
    stack = []
    end_to_head = {}
    pairs = []
    for i, st in enumerate(steps or []):
        t = (st.get("type") or "").upper()
        if t == "LOOP_START":
            stack.append(i)
        elif t == "LOOP_END":
            if stack:
                si = stack.pop()
                head = si + 1
                end_to_head[i] = head
                pairs.append((head, i))
    return end_to_head, pairs


def _resolve_escape_pygame_key(name):
    if not name:
        return None
    n = str(name).strip().upper()
    if n.startswith("K_"):
        n = n[2:]
    return getattr(pygame, "K_" + n, None)

def load_anim_auto(char_name, state, direction):
    def _root_fallback_image():
        """애니 폴더(idle 포함)까지 없을 때: character/<name>/<name>.png 로 폴백."""
        try:
            p = os.path.join("assets", "images", "character", char_name, f"{char_name}.png")
            if os.path.exists(p):
                return _load_image_cached(p)
        except Exception:
            return None
        return None

    path = os.path.join("assets", "images", "character", char_name, f"{state}_{direction}")
    frames = _load_char_anim_dir_cached(path, state, direction, char_name)
    if not frames:
        img = _root_fallback_image()
        return [img] if img is not None else [pygame.Surface((24, 32))]
    return frames


def _load_char_state_or_fallback(char_name, state, fallback="walk"):
    path_l = os.path.join("assets", "images", "character", char_name, f"{state}_left")
    if os.path.isdir(path_l):
        return load_anim_auto(char_name, state, "left")
    return load_anim_auto(char_name, fallback, "left")


def mask_terrain_class(mask_img, x, y):
    """walk / ditch / wall / oob — 플레이어 발 위치 기준."""
    cx, cy = int(x), int(y)
    if not mask_img or not (0 <= cx < mask_img.get_width() and 0 <= cy < mask_img.get_height()):
        return "oob"
    col = mask_img.get_at((cx, cy))
    r, g, b = col[0], col[1], col[2]
    rm = int(CONFIG.get("DITCH_COLOR_R_MAX", 90))
    gm = int(CONFIG.get("DITCH_COLOR_G_MAX", 90))
    bm = int(CONFIG.get("DITCH_COLOR_B_MIN", 200))
    if r <= rm and g <= gm and b >= bm:
        return "ditch"
    if r > 180 and g > 180 and b > 180:
        return "walk"
    if r > g and r > b:
        return "walk"
    if g > r and g > b:
        return "walk"
    if b > r and b > g:
        return "walk"
    return "wall"


def _analyze_ditch_jump_on_segment(mask_img, ax, ay, bx, by, jump_max_px):
    """
    A→B 직선에서 도랑만 건너는 경우, (이륙점, 착지점)과 도랑 구간 길이(px)를 반환.
    이륙점 = 직선상 마지막 walk 샘플(도랑 직전), 착지점 = 도랑 이후 첫 walk.
    벽이 끼이거나 도랑이 jump_max 초과면 (None, span).
    """
    dist = math.hypot(bx - ax, by - ay)
    if dist < 1e-3:
        return None, 0.0
    steps = max(2, int(math.ceil(dist / 2.0)))
    ditch_run = 0.0
    max_ditch = 0.0
    in_ditch = False
    saw_ditch = False
    land_x, land_y = bx, by
    takeoff_x, takeoff_y = None, None
    first_ditch_t = None  # 직선 파라미터 t (0~1)에서 첫 도랑 샘플
    prev_tx, prev_ty = ax, ay
    step_len = dist / steps
    hit_wall_in_gap = False
    for i in range(1, steps + 1):
        t = i / steps
        tx = ax + (bx - ax) * t
        ty = ay + (by - ay) * t
        cls = mask_terrain_class(mask_img, tx, ty)
        if cls == "oob":
            hit_wall_in_gap = True
            break
        if cls == "ditch":
            saw_ditch = True
            if not in_ditch:
                in_ditch = True
                ditch_run = step_len
                if first_ditch_t is None:
                    first_ditch_t = t
                if mask_terrain_class(mask_img, prev_tx, prev_ty) == "walk":
                    takeoff_x, takeoff_y = prev_tx, prev_ty
            else:
                ditch_run += step_len
            max_ditch = max(max_ditch, ditch_run)
        elif cls == "walk":
            if in_ditch:
                in_ditch = False
                land_x, land_y = tx, ty
            ditch_run = 0.0
        else:
            if in_ditch or saw_ditch:
                hit_wall_in_gap = True
                break
        prev_tx, prev_ty = tx, ty
    if not saw_ditch:
        return None, 0.0
    if hit_wall_in_gap or max_ditch > float(jump_max_px) + 0.01:
        return None, max_ditch
    # 시작점이 도랑 안이면 prev가 walk가 아니어 이륙이 비는 경우가 있음 → 첫 도랑 이전으로 t를 줄여 walk 경계 탐색
    if takeoff_x is None and saw_ditch and first_ditch_t is not None and first_ditch_t > 1e-6:
        lo, hi = 0.0, first_ditch_t
        for _ in range(18):
            mid = (lo + hi) * 0.5
            qx = ax + (bx - ax) * mid
            qy = ay + (by - ay) * mid
            if mask_terrain_class(mask_img, qx, qy) == "walk":
                lo = mid
            else:
                hi = mid
        qx = ax + (bx - ax) * lo
        qy = ay + (by - ay) * lo
        if mask_terrain_class(mask_img, qx, qy) == "walk":
            takeoff_x, takeoff_y = qx, qy
    if takeoff_x is None:
        return None, max_ditch
    return ((takeoff_x, takeoff_y), (land_x, land_y)), max_ditch


def _analyze_ditch_jump_land_only(mask_img, ax, ay, bx, by, jump_max_px):
    """
    (호환/폴백) A→B 직선에서 도랑만 건너는 경우, 착지 좌표와 도랑 폭(px)을 반환.
    예전 FOLLOW 구현처럼 이륙점이 애매한 케이스에서도 "일단 착지점으로 점프"가 가능하도록 유지합니다.
    """
    dist = math.hypot(bx - ax, by - ay)
    if dist < 1e-3:
        return None, 0.0
    steps = max(2, int(math.ceil(dist / 2.0)))
    ditch_run = 0.0
    max_ditch = 0.0
    in_ditch = False
    saw_ditch = False
    land_x, land_y = bx, by
    step_len = dist / steps
    hit_wall_in_gap = False
    for i in range(1, steps + 1):
        t = i / steps
        tx = ax + (bx - ax) * t
        ty = ay + (by - ay) * t
        cls = mask_terrain_class(mask_img, tx, ty)
        if cls == "oob":
            hit_wall_in_gap = True
            break
        if cls == "ditch":
            saw_ditch = True
            if not in_ditch:
                in_ditch = True
                ditch_run = step_len
            else:
                ditch_run += step_len
            max_ditch = max(max_ditch, ditch_run)
        elif cls == "walk":
            if in_ditch:
                in_ditch = False
                land_x, land_y = tx, ty
            ditch_run = 0.0
        else:
            if in_ditch or saw_ditch:
                hit_wall_in_gap = True
                break
    if not saw_ditch:
        return None, 0.0
    if hit_wall_in_gap or max_ditch > float(jump_max_px) + 0.01:
        return None, max_ditch
    return (land_x, land_y), max_ditch


def _push_land_forward_on_walk(mask_img, lx, ly, toward_x, toward_y):
    """
    착지점을 진행 방향으로 조금 더 전진시켜, 도랑 가장자리에서 바로 멈추는 느낌을 줄입니다.
    - walk 픽셀 위에서만 전진
    - 설정은 data.CONFIG의 JUMP_LAND_FORWARD_* 로 조절
    """
    if mask_img is None:
        return float(lx), float(ly)
    try:
        base = float(CONFIG.get("JUMP_LAND_FORWARD_PX", 8.0))
        max_px = float(CONFIG.get("JUMP_LAND_FORWARD_MAX_PX", 18.0))
        step = float(CONFIG.get("JUMP_LAND_FORWARD_STEP_PX", 2.0))
    except Exception:
        return float(lx), float(ly)
    if max_px <= 0.01 or step <= 0.01:
        return float(lx), float(ly)
    dx = float(toward_x) - float(lx)
    dy = float(toward_y) - float(ly)
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return float(lx), float(ly)
    ux, uy = dx / d, dy / d

    best_x, best_y = float(lx), float(ly)
    dist = 0.0
    # base까지는 최소 전진을 시도하고, 이후 max_px까지는 가능한 만큼 전진
    target = max(0.0, min(max_px, base))
    while dist + step <= max_px + 1e-6:
        dist += step
        if dist < target - 1e-6:
            pass
        qx = float(lx) + ux * dist
        qy = float(ly) + uy * dist
        if mask_terrain_class(mask_img, qx, qy) == "walk":
            best_x, best_y = qx, qy
        else:
            break
    return best_x, best_y


def _snap_to_nearest_walk(mask_img, x, y, max_r=40, step=2):
    """
    목표점이 도랑/벽/oob인 경우, 주변의 가장 가까운 walk 픽셀로 스냅합니다.
    없으면 None.
    """
    if mask_img is None:
        return None
    try:
        max_r = int(max(0, max_r))
        step = int(max(1, step))
    except Exception:
        return None
    cx, cy = float(x), float(y)
    if mask_terrain_class(mask_img, cx, cy) == "walk":
        return (cx, cy)
    for r in range(step, max_r + 1, step):
        # 사각 링 검사
        for ox in range(-r, r + 1, step):
            for oy in (-r, r):
                qx, qy = cx + ox, cy + oy
                if mask_terrain_class(mask_img, qx, qy) == "walk":
                    return (qx, qy)
        for oy in range(-r + step, r - step + 1, step):
            for ox in (-r, r):
                qx, qy = cx + ox, cy + oy
                if mask_terrain_class(mask_img, qx, qy) == "walk":
                    return (qx, qy)
    return None


def _build_full_waypoints_for_augment(sx, sy, raw_points):
    """점프 구간 검사에 현재 위치→첫 A* 노드 사이 도랑이 빠지지 않도록 시작점을 포함한 (x,y) 리스트."""
    full = [(float(sx), float(sy))]
    for p in raw_points:
        fx, fy = float(p[0]), float(p[1])
        if math.hypot(fx - full[-1][0], fy - full[-1][1]) > 0.5:
            full.append((fx, fy))
    return full


def _event_target_mid_scripted_move(target):
    """이벤트 MOVE로 잡힌 경로를 아직 수행 중이면 True (같은 대상에 연속 MOVE를 큐로 이어 붙일 때)."""
    ew = getattr(target, "event_waypoints", None)
    if isinstance(ew, list) and len(ew) > 0:
        return True
    path = getattr(target, "path", None)
    if path:
        return True
    if getattr(target, "_path_plan_job", None) is not None:
        return True
    return False


def _event_move_force_from_step(fragment) -> bool:
    """이벤트 MOVE force. 생략 시 EVENT_MOVE_FORCE_DEFAULT(기본 True=연출용 직선·마스크 무시)."""
    fr = fragment.get("force", fragment.get("ignore_mask", fragment.get("noclip")))
    if fr is None or (isinstance(fr, str) and str(fr).strip() == ""):
        try:
            return bool(CONFIG.get("EVENT_MOVE_FORCE_DEFAULT", True))
        except Exception:
            return True
    if isinstance(fr, str):
        return fr.strip().lower() in ("1", "true", "t", "yes", "y", "on")
    return bool(fr)


def _event_finish_move_target(target):
    """이벤트 MOVE 종료: move_anim 유지 시 anim override는 보존."""
    preserve = bool(getattr(target, "_event_wp_preserve_path_anim", False))
    sm = getattr(target, "stop_moving", None)
    if callable(sm):
        sm(preserve_anim_override=preserve)
    if preserve:
        try:
            target._event_wp_preserve_path_anim = False
        except Exception:
            pass


def augment_player_path_with_jumps(mask_img, path_2d, jump_max_px):
    """
    (단순화) 경로에 점프 웨이포인트를 끼워 넣지 않습니다.
    도랑 점프는 move()에서 '도랑을 밟으려는 순간' 트리거로 처리합니다.
    """
    if not path_2d:
        return []
    return [(float(p[0]), float(p[1]), 0) for p in path_2d]


def tick_straight_line_path(entity):
    """Maskless straight-line motion for event MOVE on NPCs/objects."""
    spd = CONFIG.get("CHAR_SPEED", 1.6)
    try:
        spd = float(spd) * float(getattr(entity, "event_speed_mul", 1.0) or 1.0)
    except Exception:
        pass
    if not getattr(entity, "path", None):
        return
    next_pt = entity.path[0]
    dx, dy = next_pt[0] - entity.pos[0], next_pt[1] - entity.pos[1]
    dist = math.hypot(dx, dy)
    if hasattr(entity, "direction") and abs(dx) > 0.1:
        entity.direction = "left" if dx < 0 else "right"
    if dist < spd:
        entity.pos = list(entity.path.pop(0))
        op = getattr(entity, "origin_pos", None)
        if op is not None:
            op[0], op[1] = entity.pos[0], entity.pos[1]
        if not entity.path:
            if hasattr(entity, "_arrival_finish_segment"):
                entity._arrival_finish_segment(None, None, None, getattr(entity, "_event_wp_preserve_path_anim", False))
            else:
                entity.stop_moving()
    else:
        ang = math.atan2(dy, dx)
        entity.pos[0] += math.cos(ang) * spd
        entity.pos[1] += math.sin(ang) * spd
        op = getattr(entity, "origin_pos", None)
        if op is not None:
            op[0], op[1] = entity.pos[0], entity.pos[1]
        if hasattr(entity, "state"):
            entity.state = "walk"


class BaseCharacter:
    def __init__(self, name, pos, info):
        self.name=name
        self.alpha = 255
        self.is_visible = True # 가시성 속성 추가 (모든 캐릭터 공통)
        if isinstance(pos, (list, tuple)):
            # 좌표가 꾸러미 (x, y)로 들어온 경우
            self.pos = [float(pos[0]), float(pos[1])]
        elif info is not None and isinstance(info, (int, float)):
            # 에디터에서 x, y를 각각 보낸 경우 (pos=x, info=y 가 됨)
            self.pos = [float(pos), float(info)]
            info = {} # y값으로 쓰인 info는 비워줌
        else:
            # 그 외 예외 상황
            self.pos = [0.0, 0.0]
        
        self.info = info if info else {}
        self.sprite_tilt = _clamp_sprite_tilt(self.info.get("sprite_tilt", 1.0))
        _ch = CHAR_ASSETS.get(self.name, {}) if self.name else {}
        # layer: 렌더 정렬에 사용 (낮을수록 먼저/뒤)
        if "layer" in self.info:
            try:
                self.layer = int(float(self.info.get("layer")))
            except Exception:
                self.layer = int(_ch.get("layer", 0) or 0)
        else:
            self.layer = int(_ch.get("layer", 0) or 0)
        if "ysort" in self.info:
            self.ysort_mode = _normalize_ysort_mode(self.info.get("ysort"))
        else:
            self.ysort_mode = _normalize_ysort_mode(_ch.get("ysort", "ground"))
        if "height" in self.info:
            self.height = _clamp_draw_height(self.info.get("height"))
        else:
            self.height = _clamp_draw_height(_ch.get("height", 0))
        
        # [수정] 이동의 기준이 되는 target 변수를 현재 위치(pos)와 동일하게 초기화합니다.
        self.target = list(self.pos) 
        
        self.anims_l = {
            "idle": load_anim_auto(name, "idle", "left"),
            "walk": load_anim_auto(name, "walk", "left"),
            "jump": _load_char_state_or_fallback(name, "jump", "walk"),
            # 더블클릭 달리기용 (없으면 walk로 폴백)
            "run": _load_char_state_or_fallback(name, "run", "walk"),
        }
        # 추가 애니메이션 세트 (없으면 idle로 안전하게 폴백)
        # - seat: 앉기(기본)
        # - seating: 탑승/앉기 전 이동(그네 등 데모)
        # - seat_idle: 앉은 상태 유지(그네 등 데모)
        # 상태별 폴백 규칙:
        # - seating / seat_idle 자산이 없으면 idle로 돌아가 버려 "그네 위에서 다시 서는" 문제가 생김
        #   → 최소한 seat로 폴백해서 앉은 자세를 유지한다.
        _fallback_by_state = {
            "seating": "seat",
            "seat_idle": "seat",
        }
        for st in ("hurt", "laugh", "attack", "lie", "seat", "seating", "seat_idle", "question", "surprise", "say", "sleep", "sad"):
            fb = _fallback_by_state.get(st, "idle")
            self.anims_l[st] = _load_char_state_or_fallback(name, st, fb)
        self.anims_r = {k: [pygame.transform.flip(img, True, False) for img in v] for k, v in self.anims_l.items()}
        self.state, self.direction, self.frame_idx, self.last_anim_time = "idle", "left", 0, 0
        self.image = self.anims_l["idle"][0]
        self.held_item = None
        self.path = []
        # 이벤트/연출용: 상태 머신과 무관하게 특정 애니메이션을 강제 재생
        # - duration_ms > 0: 해당 시간동안 반복 후 종료(원래 상태로 복귀)
        # - duration_ms <= 0 or None: 다음 명령이 오기 전까지 지속
        self._anim_override = None  # {"state":str,"t_end":int|None,"prev":str,"loop":bool}
        # 이벤트 ZOOM: 카메라 줌과 별도로 스프라이트만 추가 배율 (1.0=기본)
        self.event_entity_zoom = 1.0
        self.event_entity_zoom_target = 1.0
        try:
            self.event_entity_zoom_speed = float(CONFIG.get("ENTITY_ZOOM_LERP", 0.12))
        except Exception:
            self.event_entity_zoom_speed = 0.12

    def stop_moving(self, preserve_anim_override=False):
        if not preserve_anim_override:
            self.clear_anim_override()
        self.path = []
        self.target = list(self.pos)
        if not preserve_anim_override:
            self.state = "idle"
        self.event_waypoints = None
        # 이벤트 MOVE speed(wait:false) 같은 임시 속도 복구
        try:
            if getattr(self, "_event_speed_restore", False):
                self.event_speed_mul = getattr(self, "_event_speed_old_mul", 1.0)
                self._event_speed_restore = False
        except Exception:
            pass

    def _arrival_finish_segment(self, mask_img=None, objects=None, npcs=None, preserve_path_anim=False):
        """경로 한 구간이 끝났을 때: 이벤트 웨이포인트가 있으면 다음 목표로, 없으면 정지."""
        wps = getattr(self, "event_waypoints", None)
        if isinstance(wps, list) and len(wps) > 0:
            p0 = wps[0]
            rest = list(wps[1:]) if len(wps) > 1 else []
            try:
                nx, ny = float(p0[0]), float(p0[1])
            except (TypeError, ValueError, IndexError):
                self.event_waypoints = None
                self.stop_moving()
                return
            self.event_waypoints = rest if rest else None
            self.set_new_target(
                nx,
                ny,
                mask_img,
                objects,
                npcs,
                preserve_path_anim=preserve_path_anim,
                clear_event_waypoints=False,
            )
            return
        self.event_waypoints = None
        preserve = bool(preserve_path_anim) or bool(
            getattr(self, "_event_wp_preserve_path_anim", False)
        )
        self.stop_moving(preserve_anim_override=preserve)
        if preserve:
            try:
                self._event_wp_preserve_path_anim = False
            except Exception:
                pass

    def set_new_target(self, tx, ty, mask_img=None, objects=None, npcs=None, preserve_path_anim=False, clear_event_waypoints=True):
        if clear_event_waypoints:
            self.event_waypoints = None
        if not preserve_path_anim:
            self.clear_anim_override()
        self.target = [float(tx), float(ty)]
        self.direction = "left" if tx < self.pos[0] else "right"
        self.path = [(float(tx), float(ty))]

    def move(self, mask, objs, npcs=None):
        if not self.path:
            self.state = "idle"
            return
        tick_straight_line_path(self)

    def _apply_anim_override_teardown(self, ao):
        """이벤트용 애니 오버라이드 해제: 높이 복구, release(stop 시 경로 정리)."""
        if not ao:
            return
        rel = (ao.get("release") or "idle").strip().lower()
        if rel not in ("idle", "stop"):
            rel = "idle"
        ph = ao.get("prev_height")
        self._anim_override = None
        if ph is not None and hasattr(self, "height"):
            try:
                self.height = float(ph)
            except (TypeError, ValueError):
                pass
        if rel == "stop":
            self.path = []
            self.target = list(self.pos)
            if hasattr(self, "_jump_arc"):
                self._jump_arc = None

    def play_anim(self, state_name, duration_ms=None, loop=True, release="idle", temp_height=None):
        st = (state_name or "").strip().lower()
        if not st:
            return
        old = getattr(self, "_anim_override", None)
        if old is not None:
            self._apply_anim_override_teardown(old)
        now = pygame.time.get_ticks()
        t_end = None
        if duration_ms is not None:
            try:
                duration_ms = int(float(duration_ms))
            except Exception:
                duration_ms = 0
            if duration_ms > 0:
                t_end = int(now + duration_ms)
        prev = str(getattr(self, "state", "idle") or "idle")
        rel = (release or "idle").strip().lower()
        if rel not in ("idle", "stop"):
            rel = "idle"
        override = {"state": st, "t_end": t_end, "prev": prev, "loop": bool(loop), "release": rel}
        if temp_height is not None and hasattr(self, "height"):
            try:
                th = _clamp_draw_height(temp_height)
            except Exception:
                th = None
            if th is not None:
                try:
                    override["prev_height"] = float(getattr(self, "height", 0) or 0)
                except (TypeError, ValueError):
                    override["prev_height"] = 0.0
                self.height = th
        self._anim_override = override
        self.frame_idx = 0
        self.last_anim_time = 0

    def clear_anim_override(self):
        ao = getattr(self, "_anim_override", None)
        if ao is None:
            return
        self._apply_anim_override_teardown(ao)
        if getattr(self, "state", None) not in (None, ""):
            return
        self.state = "idle"

    def update_anim(self):
        now = pygame.time.get_ticks()
        ao = getattr(self, "_anim_override", None)
        if ao is not None:
            t_end = ao.get("t_end")
            if t_end is not None and now >= int(t_end):
                self._apply_anim_override_teardown(ao)
                if self.state == "jump":
                    pass
                else:
                    self.state = "idle"
                ao = None

        if now - self.last_anim_time > CONFIG["ANIM_DELAY"]:
            self.last_anim_time = now
            active_state = self.state
            if ao is not None:
                active_state = ao.get("state") or self.state
            anims = (self.anims_l if self.direction == "left" else self.anims_r)
            frames = anims.get(active_state) or anims.get("idle")
            if frames:
                if ao is not None and not bool(ao.get("loop", True)):
                    self.frame_idx = min(self.frame_idx + 1, len(frames) - 1)
                else:
                    self.frame_idx = (self.frame_idx + 1) % len(frames)
                self.image = frames[self.frame_idx]

    def ground_feet_position(self):
        return float(self.pos[0]), float(self.pos[1])

    def jump_air_fraction(self):
        return None

    def _draw_feet_shadow(
        self,
        screen,
        cam_x,
        cam_y,
        zoom,
        jump_shadow_mode,
        y_transform=None,
        x_offset_fn=None,
        entity_scale_mul=1.0,
    ):
        if not CONFIG.get("CHARACTER_SHADOW_ENABLED", True):
            return
        override = getattr(self, "_jump_shadow_override", None)
        if override is not None:
            mode = str(override).strip().lower() or "ground"
        else:
            mode = (jump_shadow_mode or "").strip().lower() or "ground"
        if mode not in ("hide", "ground"):
            mode = "ground"
        in_arc = getattr(self, "_jump_arc", None) is not None
        if in_arc and mode == "hide":
            return
        gx, gy = self.ground_feet_position()
        size_scale, alpha_scale = 1.0, 1.0
        if in_arc and mode == "ground":
            af = self.jump_air_fraction()
            if af is None:
                af = 0.0
            smin = float(CONFIG.get("SHADOW_JUMP_SIZE_MUL_MIN", 0.4))
            amin = float(CONFIG.get("SHADOW_JUMP_ALPHA_MUL_MIN", 0.22))
            size_scale = 1.0 + (smin - 1.0) * af
            alpha_scale = 1.0 + (amin - 1.0) * af
        _blit_feet_shadow(
            screen,
            gx,
            gy,
            cam_x,
            cam_y,
            zoom,
            size_scale=size_scale,
            alpha_scale=alpha_scale,
            y_transform=y_transform,
            x_offset_fn=x_offset_fn,
            entity_scale_mul=entity_scale_mul,
        )

    def draw(self, screen, cam_x, cam_y, zoom=1.0, jump_shadow_mode=None, y_transform=None, x_offset_fn=None, sprite_perspective_q=None, shear_lod=False):
        if not self.is_visible: return # 플레이어가 숨김 상태면 그리지 않음

        try:
            ez = float(getattr(self, "event_entity_zoom", 1.0) or 1.0)
        except Exception:
            ez = 1.0
        ez = max(0.05, min(8.0, ez))
        eff = float(zoom) * ez

        self._draw_feet_shadow(
            screen,
            cam_x,
            cam_y,
            zoom,
            jump_shadow_mode,
            y_transform=y_transform,
            x_offset_fn=x_offset_fn,
            entity_scale_mul=ez,
        )

        # 1. 캐릭터 이미지 줌 처리 (카메라 줌 × 이벤트 엔티티 배율)
        render_img = self.image
        # shared Surface를 직접 set_alpha 하면 다른 엔티티에도 영향을 줌 → 필요할 때만 copy
        try:
            a = int(getattr(self, "alpha", 255))
        except Exception:
            a = 255
        if a != 255:
            try:
                render_img = render_img.copy()
                render_img.set_alpha(a)
            except Exception:
                pass
        render_img = get_cached_scaled_sprite(
            render_img,
            eff,
            sprite_perspective_q=sprite_perspective_q,
            sprite_tilt=getattr(self, "sprite_tilt", 1.0),
        )

        # 2. 줌이 적용된 화면 좌표 계산
        feet_y = float((self.pos[1] - cam_y) * zoom)
        if callable(y_transform):
            try:
                feet_y = float(y_transform(feet_y))
            except Exception:
                pass
        # 쉬어(x_offset_fn)의 입력 y를 정수 픽셀로 스냅(홀수 좌표 배치 + 카메라 이동 시 떨림 완화)
        feet_y_q = float(int(round(float(feet_y))))
        feet_x = float((self.pos[0] - cam_x) * zoom)
        if callable(x_offset_fn):
            try:
                feet_x = float(feet_x) + float(x_offset_fn(float(feet_y_q)))
            except Exception:
                pass
        h_off = float(getattr(self, "height", 0) or 0)
        if h_off > 0.0:
            feet_y = float(feet_y_q) - h_off * float(zoom)
        else:
            feet_y = float(feet_y_q)
        # 발 픽셀 고정 후 정수 절반폭 (에디터·FieldItem·render_align 규칙과 동일)
        fpx, fpy = int(round(float(feet_x))), int(round(float(feet_y)))
        dx, dy = blit_topleft_bottom_center(fpx, fpy, render_img.get_width(), render_img.get_height())

        screen.blit(render_img, (dx, dy))

        # 3. 손에 든 물건 — is_held 일 때만 (발 중앙 앵커 = FieldItem·ANIM_ONCE 와 동일 규칙)
        if self.held_item and bool(getattr(self.held_item, "is_held", False)):
            hi = self.held_item
            if len(getattr(hi, "frames", []) or []) > 1:
                hi.update_anim()
            h_img = hi.image
            if self.direction == "right":
                try:
                    fc = getattr(self, "_held_flip_cache", None)
                    if fc is None:
                        fc = {}
                        self._held_flip_cache = fc
                    fk = (id(h_img), "R")
                    h2 = fc.get(fk)
                    if h2 is None:
                        h2 = pygame.transform.flip(h_img, True, False)
                        fc[fk] = h2
                    h_img = h2
                except Exception:
                    h_img = pygame.transform.flip(h_img, True, False)

            foot_wx, foot_wy = _held_item_foot_world_pos(
                self.pos[0], self.pos[1], self.direction
            )
            hi.pos[0] = foot_wx
            hi.pos[1] = foot_wy
            hi.origin_pos[0] = foot_wx
            hi.origin_pos[1] = foot_wy

            try:
                hez = float(getattr(hi, "event_entity_zoom", 1.0) or 1.0)
            except Exception:
                hez = 1.0
            hez = max(0.05, min(8.0, hez))
            h_eff = float(zoom) * hez

            dx_base, dy_base = _field_world_to_screen_anchor(
                foot_wx,
                foot_wy,
                cam_x,
                cam_y,
                zoom,
                height=float(getattr(hi, "height", 0) or 0),
                y_transform=y_transform,
                x_offset_fn=x_offset_fn,
                anchor="feet",
            )
            prepared = _prepare_field_sprite_blit(
                h_img,
                dx_base,
                dy_base,
                eff_z=h_eff,
                sprite_tilt=getattr(hi, "sprite_tilt", 1.0),
                sprite_perspective_q=sprite_perspective_q,
                x_offset_fn=x_offset_fn,
                shear_lod=shear_lod,
                shear_cache_holder=hi,
                anchor="feet",
                alpha=255,
            )
            if prepared is not None:
                render_h, fx, fy = prepared
                screen.blit(render_h, (fx, fy))

class MaskWalkingCharacter(BaseCharacter):
    """마스크 A* + 도랑 점프 (플레이어·FOLLOW용 NPC 등)."""

    def __init__(self, name, pos, info):
        super().__init__(name, pos, info)
        self.layer = 0
        self._move_mode = "walk"  # "walk" | "run"
        self._click_run_restore = False
        self.jump_max_gap = float(CHAR_ASSETS.get(name, {}).get("jump_max_gap", CONFIG.get("JUMP_MAX_GAP_PX", 30)))
        self.jump_pad_zones = []
        self._jump_arc = None
        # A*는 비용이 커서 클릭/이벤트 순간 멈칫이 생길 수 있다.
        # 경로 계산을 프레임에 분할(타임슬라이스)하기 위한 비동기 플래너 상태.
        self._path_plan_job = None  # dict or None
        self._path_plan_seq = 0
        self._path_plan_last_tick_ms = 0
        # FOLLOW용: 매 프레임 A*를 돌리지 않기 위한 간단 추종 타겟
        self._follow_target = None  # (x,y) or None
        self._follow_slot_goal = None  # 리더 뒤 목표 슬롯; 도랑 점프 경로 덮어쓰기 방지용
        self._follow_last_plan_ms = 0

    def ground_feet_position(self):
        ja = self._jump_arc
        if ja is None:
            return float(self.pos[0]), float(self.pos[1])
        now = pygame.time.get_ticks()
        u = (now - ja["t0"]) / float(ja["dur"])
        if u >= 1.0:
            return float(self.pos[0]), float(self.pos[1])
        sm = _smoothstep_unit(u)
        gx = ja["sx"] + (ja["ex"] - ja["sx"]) * sm
        gy = ja["sy"] + (ja["ey"] - ja["sy"]) * sm
        return gx, gy

    def jump_air_fraction(self):
        ja = self._jump_arc
        if ja is None:
            return None
        now = pygame.time.get_ticks()
        u = (now - ja["t0"]) / float(ja["dur"])
        if u >= 1.0:
            return None
        sm = _smoothstep_unit(u)
        arc_h = float(ja.get("arc_h", CONFIG.get("JUMP_ARC_HEIGHT", 22)))
        if arc_h < 1e-6:
            return 0.0
        lift = math.sin(math.pi * sm) * arc_h
        return max(0.0, min(1.0, lift / arc_h))

    def _astar_walk_path(self, target_x, target_y, mask_img, objects, npcs, start_xy, grid, max_visited):
        """A* (격자 grid px). start_xy는 플레이어 위치와 달리도 호출 가능(코너 탈출 앵커용)."""
        start = (int(start_xy[0]), int(start_xy[1]))
        goal = (int(target_x), int(target_y))
        grid = max(1, int(grid))
        max_visited = int(max(120, max_visited))

        queue = []
        tie = 0
        heapq.heappush(queue, (0.0, tie, start, []))
        tie += 1
        visited = set()

        while queue:
            _, _, current, path = heapq.heappop(queue)

            grid_pos = (current[0] // grid, current[1] // grid)
            if grid_pos in visited:
                continue
            visited.add(grid_pos)

            if math.hypot(current[0] - goal[0], current[1] - goal[1]) < grid * 2:
                return path + [goal]

            for dx, dy in [
                (0, -grid),
                (0, grid),
                (-grid, 0),
                (grid, 0),
                (-grid, -grid),
                (-grid, grid),
                (grid, -grid),
                (grid, grid),
            ]:
                nx, ny = current[0] + dx, current[1] + dy
                walkable, _ = self.check_walkable(nx, ny, mask_img, objects, npcs)
                if walkable:
                    new_path = path + [(nx, ny)]
                    priority = len(new_path) + math.hypot(nx - goal[0], ny - goal[1])
                    heapq.heappush(queue, (priority, tie, (nx, ny), new_path))
                    tie += 1

            if len(visited) > max_visited:
                break
        return []

    def _astar_begin(self, target_x, target_y, start_xy, grid, max_visited):
        start = (int(start_xy[0]), int(start_xy[1]))
        goal = (int(target_x), int(target_y))
        grid = max(1, int(grid))
        max_visited = int(max(120, max_visited))
        queue = []
        tie = 0
        heapq.heappush(queue, (0.0, tie, start, []))
        tie += 1
        visited = set()
        return {
            "start": start,
            "goal": goal,
            "grid": grid,
            "max_visited": max_visited,
            "queue": queue,
            "tie": tie,
            "visited": visited,
            "result": None,
            "done": False,
        }

    def _astar_step(self, st, mask_img, objects, npcs, *, budget_ms):
        """A*를 budget_ms만큼만 진행. 완료 시 st['result']에 raw path(list[(x,y)]) 저장."""
        if not st or st.get("done"):
            return st
        try:
            budget_ms = float(budget_ms)
        except Exception:
            budget_ms = 1.5
        budget_ms = max(0.2, min(12.0, budget_ms))

        t0 = pygame.time.get_ticks()
        goal = st["goal"]
        grid = st["grid"]
        max_visited = st["max_visited"]
        queue = st["queue"]
        visited = st["visited"]

        while queue:
            if (pygame.time.get_ticks() - t0) >= budget_ms:
                break
            _prio, _tie, current, path = heapq.heappop(queue)

            grid_pos = (current[0] // grid, current[1] // grid)
            if grid_pos in visited:
                continue
            visited.add(grid_pos)

            if math.hypot(current[0] - goal[0], current[1] - goal[1]) < grid * 2:
                st["result"] = path + [goal]
                st["done"] = True
                return st

            for dx, dy in [
                (0, -grid),
                (0, grid),
                (-grid, 0),
                (grid, 0),
                (-grid, -grid),
                (-grid, grid),
                (grid, -grid),
                (grid, grid),
            ]:
                nx, ny = current[0] + dx, current[1] + dy
                walkable, _ = self.check_walkable(nx, ny, mask_img, objects, npcs)
                if walkable:
                    new_path = path + [(nx, ny)]
                    priority = len(new_path) + math.hypot(nx - goal[0], ny - goal[1])
                    heapq.heappush(queue, (priority, st["tie"], (nx, ny), new_path))
                    st["tie"] += 1

            if len(visited) > max_visited:
                st["done"] = True
                st["result"] = []
                return st

        if not queue:
            st["done"] = True
            st["result"] = []
        return st

    def _begin_path_plan_job(self, tx, ty, mask_img, objects, npcs):
        """경로 계획을 프레임 분할로 시작. 호출 즉시에는 최소 반응(직선 목표)만 세팅."""
        self._path_plan_seq = int(getattr(self, "_path_plan_seq", 0) or 0) + 1
        pid = int(self._path_plan_seq)

        # 우선은 바로 출발(직선 목표). 실제 A* 경로는 이후에 덮어쓴다.
        self.path = [(float(tx), float(ty), 0)]

        g0 = int(CONFIG.get("PATHFIND_GRID_PX", 5))
        grids = [max(1, g0)]
        g1 = int(CONFIG.get("PATHFIND_GRID_FINE_PX", 3))
        if g1 > 0:
            g1 = max(1, g1)
            if g1 not in grids:
                grids.append(g1)
        gu = int(CONFIG.get("PATHFIND_GRID_ULTRA_PX", 0))
        if gu > 0:
            gu = max(1, gu)
            if gu not in grids:
                grids.append(gu)

        base_vis = int(CONFIG.get("PATHFIND_MAX_VISITED", 3800))
        base_vis = max(200, base_vis)

        self._path_plan_job = {
            "id": pid,
            "tx": float(tx),
            "ty": float(ty),
            "sx": float(self.pos[0]),
            "sy": float(self.pos[1]),
            "objects": objects or [],
            "npcs": npcs or [],
            "grids": grids,
            "grid_idx": 0,
            "base_vis": base_vis,
            "astar": None,
            "result": None,
        }

    def _tick_path_plan_job(self, mask_img, objects, npcs):
        job = getattr(self, "_path_plan_job", None)
        if not isinstance(job, dict):
            return
        # 동일 프레임(sim_steps>1)에서 과도하게 돌지 않도록 억제
        now = pygame.time.get_ticks()
        if int(getattr(self, "_path_plan_last_tick_ms", 0) or 0) == int(now):
            return
        self._path_plan_last_tick_ms = int(now)

        try:
            budget_ms = float(CONFIG.get("PATHFIND_BUDGET_MS_PER_FRAME", 1.8))
        except Exception:
            budget_ms = 1.8

        # 목표가 바뀌었거나 job이 stale이면 취소
        if getattr(self, "target", None) and (
            abs(float(self.target[0]) - float(job.get("tx", 0.0))) > 0.5
            or abs(float(self.target[1]) - float(job.get("ty", 0.0))) > 0.5
        ):
            self._path_plan_job = None
            return

        grids = job.get("grids") or []
        gi = int(job.get("grid_idx") or 0)
        if gi >= len(grids):
            self._path_plan_job = None
            return

        g = int(grids[gi])
        base_vis = int(job.get("base_vis") or 200)
        mv = int(base_vis * (1.85 if g <= 3 else 1.0))

        # 경로 계산이 끝나기 전에 캐릭터가 이미 앞으로 움직이면,
        # 완료된 경로의 첫 점이 "현재 위치 기준 뒤쪽"이 되어 잠깐 되돌아가는 현상이 생길 수 있다.
        # 일정 거리 이상 이동했으면 시작점을 현재로 리베이스해서 A*를 다시 시작한다.
        try:
            rebase_dist = float(CONFIG.get("PATHFIND_REBASE_START_DIST_PX", 18.0))
        except Exception:
            rebase_dist = 18.0
        if rebase_dist > 0:
            try:
                moved = math.hypot(float(self.pos[0]) - float(job.get("sx", self.pos[0])), float(self.pos[1]) - float(job.get("sy", self.pos[1])))
            except Exception:
                moved = 0.0
            if moved >= rebase_dist:
                job["sx"], job["sy"] = float(self.pos[0]), float(self.pos[1])
                job["grid_idx"] = 0
                job["astar"] = None
                return

        ast = job.get("astar")
        if not isinstance(ast, dict):
            ast = self._astar_begin(job["tx"], job["ty"], (job["sx"], job["sy"]), g, mv)
            job["astar"] = ast

        self._astar_step(ast, mask_img, objects or [], npcs or [], budget_ms=budget_ms)
        if not ast.get("done"):
            return

        raw = ast.get("result") or []
        if raw:
            job["result"] = raw
            # 완료: 현재 위치에 가장 가까운 지점부터 경로를 적용(뒤로 돌아가는 현상 방지)
            cx, cy = float(self.pos[0]), float(self.pos[1])
            best_i = 0
            best_d = None
            for i, p in enumerate(raw):
                try:
                    d = math.hypot(float(p[0]) - cx, float(p[1]) - cy)
                except Exception:
                    continue
                if best_d is None or d < best_d:
                    best_d = d
                    best_i = i
            try:
                near_cut = float(CONFIG.get("PATHFIND_ATTACH_NEAR_CUT_PX", max(6.0, float(g) * 2.0)))
            except Exception:
                near_cut = max(6.0, float(g) * 2.0)
            if best_d is not None and best_d <= near_cut:
                raw2 = raw[int(best_i):]
            else:
                raw2 = raw
            # 현재 경로를 A* 결과로 자연스럽게 덮어쓰기
            self.path = [(float(p[0]), float(p[1]), 0) for p in (raw2 or raw)]
            self._strip_redundant_path_head()
            self._path_plan_job = None
            return

        # 다음 격자로 재시도
        job["grid_idx"] = gi + 1
        job["astar"] = None

    def _local_open_neighbors(self, x, y, mask_img, objects, npcs, grid_g):
        """grid_g 간격 8방 이웃 중 walk 가능한 개수(코너·틈에서 탈출 여부 힌트)."""
        n = 0
        gg = max(1, int(grid_g))
        for dx, dy in [
            (0, -gg),
            (0, gg),
            (-gg, 0),
            (gg, 0),
            (-gg, -gg),
            (-gg, gg),
            (gg, -gg),
            (gg, gg),
        ]:
            if self.check_walkable(x + dx, y + dy, mask_img, objects, npcs)[0]:
                n += 1
        return n

    @staticmethod
    def _merge_trail_and_path(trail, raw):
        if not trail:
            return raw
        if not raw:
            return trail
        lx, ly = trail[-1]
        fx, fy = float(raw[0][0]), float(raw[0][1])
        if math.hypot(lx - fx, ly - fy) < 1.5:
            return trail[:-1] + raw
        return trail + raw

    def _plan_path_corner_escape(self, target_x, target_y, mask_img, objects, npcs, start_xy, grid_for_astar, max_vis):
        """시작점이 좁은 모서리일 때: 짧은 BFS로 안쪽으로 빠져 나간 뒤 A* 재시도."""
        sx, sy = int(start_xy[0]), int(start_xy[1])
        step = max(1, int(CONFIG.get("PATHFIND_ESCAPE_STEP_PX", 2)))
        max_nodes = int(CONFIG.get("PATHFIND_ESCAPE_MAX_NODES", 3200))
        max_dist = float(CONFIG.get("PATHFIND_ESCAPE_MAX_DIST_PX", 96.0))
        min_dist_try = float(CONFIG.get("PATHFIND_ESCAPE_MIN_BEFORE_REPLAN_PX", 4.0))
        try:
            min_open = int(CONFIG.get("PATHFIND_ESCAPE_MIN_OPEN_NEIGHBORS", 1))
        except Exception:
            min_open = 1
        min_open = max(0, min(8, min_open))

        neigh = [
            (0, -step),
            (0, step),
            (-step, 0),
            (step, 0),
            (-step, -step),
            (-step, step),
            (step, -step),
            (step, step),
        ]
        q = deque()
        q.append((sx, sy, []))
        vis = set()
        vis.add((sx // step, sy // step))
        nodes = 0

        while q and nodes < max_nodes:
            cx, cy, trail = q.popleft()
            nodes += 1

            moved = bool(trail)
            dist_home = math.hypot(cx - sx, cy - sy)
            if moved and dist_home >= min_dist_try:
                open_ok = min_open <= 0 or (
                    self._local_open_neighbors(cx, cy, mask_img, objects, npcs, grid_for_astar) >= min_open
                )
                if open_ok:
                    raw = self._astar_walk_path(
                        target_x, target_y, mask_img, objects, npcs, (cx, cy), grid_for_astar, max_vis
                    )
                    if raw:
                        return self._merge_trail_and_path(trail, raw)

            if dist_home > max_dist:
                continue

            for dx, dy in neigh:
                nx, ny = cx + dx, cy + dy
                gk = (nx // step, ny // step)
                if gk in vis:
                    continue
                if not self.check_walkable(nx, ny, mask_img, objects, npcs)[0]:
                    continue
                vis.add(gk)
                q.append((nx, ny, trail + [(nx, ny)]))

        return []

    def _plan_path_resilient(self, target_x, target_y, mask_img, objects, npcs):
        """격자 단계(굵음→세밀) + 코너 BFS 탈출. 좁은 모서리에서 길이 끊기지 않게 함."""
        sx, sy = int(self.pos[0]), int(self.pos[1])
        grids = []
        g0 = int(CONFIG.get("PATHFIND_GRID_PX", 5))
        grids.append(max(1, g0))
        g1 = int(CONFIG.get("PATHFIND_GRID_FINE_PX", 3))
        if g1 > 0:
            g1 = max(1, g1)
            if g1 not in grids:
                grids.append(g1)
        gu = int(CONFIG.get("PATHFIND_GRID_ULTRA_PX", 0))
        if gu > 0:
            gu = max(1, gu)
            if gu not in grids:
                grids.append(gu)

        base_vis = int(CONFIG.get("PATHFIND_MAX_VISITED", 3800))
        base_vis = max(200, base_vis)

        for g in grids:
            mv = int(base_vis * (1.85 if g <= 3 else 1.0))
            raw = self._astar_walk_path(target_x, target_y, mask_img, objects, npcs, (sx, sy), g, mv)
            if raw:
                return raw

        if not bool(CONFIG.get("PATHFIND_CORNER_ESCAPE_ENABLED", True)):
            return []

        grid_anchor = min(grids)
        mv_esc = max(base_vis * 2, 5200)
        return self._plan_path_corner_escape(
            target_x, target_y, mask_img, objects, npcs, (sx, sy), grid_anchor, mv_esc
        )

    def plan_path(self, target_x, target_y, mask_img, objects, npcs):
        """호환용: 기본 격자 한 번만 시도. 새 경로는 _plan_path_resilient 사용."""
        g = max(1, int(CONFIG.get("PATHFIND_GRID_PX", 5)))
        mv = int(CONFIG.get("PATHFIND_MAX_VISITED", 3800))
        return self._astar_walk_path(
            target_x, target_y, mask_img, objects, npcs, (int(self.pos[0]), int(self.pos[1])), g, mv
        )

    def check_walkable(self, x, y, mask_img, objects, npcs):
        """기존의 복잡한 레이어 및 충돌 판정을 독립적으로 수행합니다."""
        cx, cy = int(x), int(y)
        if not (0 <= cx < mask_img.get_width() and 0 <= cy < mask_img.get_height()):
            return False, self.layer

        if mask_terrain_class(mask_img, x, y) != "walk":
            return False, self.layer

        col = mask_img.get_at((cx, cy))
        r, g, b = col[0], col[1], col[2]
        new_layer = self.layer
        can_pass = False

        # 층수 판정 (도랑 색은 mask_terrain_class에서 이미 제외됨)
        if r > 180 and g > 180 and b > 180: new_layer = 0; can_pass = True
        elif r > g and r > b: new_layer = 1; can_pass = True
        elif g > r and g > b: new_layer = 2; can_pass = True
        elif b > r and b > g: new_layer = 3; can_pass = True

        if not can_pass: return False, self.layer

        # 오브젝트 충돌 (살짝 넉넉하게 판정하여 끼임 방지)
        for o in objects:
            if o.collision and not getattr(o, 'is_held', False) and getattr(o, 'layer', 0) == new_layer:
                rw = o.rect_for_logic.width // 2 - 2 # 2픽셀 여유
                if abs(o.pos[0] - x) < rw and -8 < y - o.pos[1] < 1:
                    return False, new_layer
        
        if npcs:
            for n in npcs:
                if n != self and getattr(n, 'layer', 0) == new_layer:
                    if abs(n.pos[0] - x) < 10 and -8 < y - n.pos[1] < 1:
                        return False, new_layer
                        
        return True, new_layer

    def move(self, mask_img, objects, npcs=None):
        """계산된 경로(Path)를 따라 한 스텝씩 이동합니다."""
        if mask_img is not None and getattr(self, "_path_plan_job", None):
            try:
                self._tick_path_plan_job(mask_img, objects or [], npcs or [])
            except Exception:
                # 플래너 오류가 이동을 막지 않도록 안전하게 중단
                self._path_plan_job = None
        if not self.path:
            self.state = "idle"
            self._jump_arc = None
            return

        now = pygame.time.get_ticks()

        next_pt = self.path[0]
        tx, ty = float(next_pt[0]), float(next_pt[1])
        jump_wp = len(next_pt) >= 3 and int(next_pt[2]) == 1

        if jump_wp:
            ex, ey = tx, ty
            if self._jump_arc is None:
                self.direction = "left" if ex < self.pos[0] else "right"
                dist = math.hypot(ex - self.pos[0], ey - self.pos[1])
                arc_h, dur = _compute_jump_params(
                    0.0, self.jump_max_gap, dist, jump_height_px=getattr(self, "height", 0)
                )
                self._jump_arc = {
                    "t0": now,
                    "dur": dur,
                    "sx": float(self.pos[0]),
                    "sy": float(self.pos[1]),
                    "ex": ex,
                    "ey": ey,
                    "arc_h": float(arc_h),
                }
                self.state = "jump"
                self.frame_idx = 0

            ja = self._jump_arc
            u = (now - ja["t0"]) / float(ja["dur"])
            if u >= 1.0:
                self.pos = [ja["ex"], ja["ey"]]
                self.path.pop(0)
                self._jump_arc = None
                # 점프 종료 시: 도랑 점프로 숨겼던 그림자 모드 복구
                if getattr(self, "_jump_shadow_override", None) == "hide":
                    self._jump_shadow_override = None
                walkable, nl = self.check_walkable(self.pos[0], self.pos[1], mask_img, objects, npcs)
                if walkable:
                    self.layer = nl
                self.state = "walk" if self.path else "idle"
                if not self.path:
                    self._arrival_finish_segment(
                        mask_img,
                        objects,
                        npcs,
                        getattr(self, "_event_wp_preserve_path_anim", False),
                    )
            else:
                sm = _smoothstep_unit(u)
                self.pos[0] = ja["sx"] + (ja["ex"] - ja["sx"]) * sm
                self.pos[1] = ja["sy"] + (ja["ey"] - ja["sy"]) * sm
                arc_h = float(ja.get("arc_h", CONFIG.get("JUMP_ARC_HEIGHT", 22)))
                self.pos[1] -= math.sin(math.pi * sm) * arc_h
                self.state = "jump"
            return

        dx, dy = tx - self.pos[0], ty - self.pos[1]
        dist = math.hypot(dx, dy)
        # 방향 전환(좌/우)은 "다음 웨이포인트의 dx 부호"만 보면
        # A* 격자/대각선 노드에서 x가 미세하게 흔들릴 때 1프레임씩 뒤돌아보는 현상이 생길 수 있다.
        # 그래서 실제로 이동하는 스텝의 x 변화(velocity) 기준으로, 작은 변화는 무시한다.
        try:
            dir_eps = float(CONFIG.get("DIR_CHANGE_EPS_X", 0.28))
        except Exception:
            dir_eps = 0.28
        dir_eps = max(0.02, min(3.0, dir_eps))

        try:
            spd = float(CONFIG["CHAR_SPEED"]) * float(getattr(self, "event_speed_mul", 1.0) or 1.0)
        except Exception:
            spd = CONFIG["CHAR_SPEED"]

        if dist < spd:
            self.pos = [tx, ty]
            self.path.pop(0)
            if not self.path:
                self._arrival_finish_segment(
                    mask_img,
                    objects,
                    npcs,
                    getattr(self, "_event_wp_preserve_path_anim", False),
                )
            else:
                self.state = "run" if str(getattr(self, "_move_mode", "walk")) == "run" else "walk"
        else:
            angle = math.atan2(dy, dx)
            nx = self.pos[0] + math.cos(angle) * spd
            ny = self.pos[1] + math.sin(angle) * spd
            stepx = nx - self.pos[0]
            if abs(stepx) >= dir_eps:
                self.direction = "left" if stepx < 0 else "right"

            if getattr(self, "_event_force_move", False):
                # force 모드: 마스크/충돌/도랑 규칙을 모두 무시하고 직선으로 이동
                self.pos = [nx, ny]
                self.state = "run" if str(getattr(self, "_move_mode", "walk")) == "run" else "walk"
                return

            # --- 도랑 점프 트리거: 다음 스텝이 도랑이면 즉시 점프 시작 ---
            if mask_img is not None and mask_terrain_class(mask_img, nx, ny) == "ditch":
                land, span = _analyze_ditch_jump_land_only(
                    mask_img, float(self.pos[0]), float(self.pos[1]), float(tx), float(ty), self.jump_max_gap
                )
                if land is not None and span > 0.01:
                    ex, ey = _push_land_forward_on_walk(mask_img, float(land[0]), float(land[1]), float(tx), float(ty))
                    self.direction = "left" if ex < self.pos[0] else "right"
                    dist2 = math.hypot(ex - self.pos[0], ey - self.pos[1])
                    arc_h, dur = _compute_jump_params(
                        span, self.jump_max_gap, dist2, jump_height_px=getattr(self, "height", 0)
                    )
                    now = pygame.time.get_ticks()
                    self._jump_arc = {
                        "t0": now,
                        "dur": dur,
                        "sx": float(self.pos[0]),
                        "sy": float(self.pos[1]),
                        "ex": ex,
                        "ey": ey,
                        "arc_h": float(arc_h),
                    }
                    # 도랑 점프(트리거) 중에는 그림자 숨김
                    self._jump_shadow_override = "hide"
                    self.state = "jump"
                    self.frame_idx = 0
                    # 점프 착지 후 원래 웨이포인트로 계속 이동
                    self.path = [(ex, ey, 1)] + [(tx, ty, 0)] + list(self.path[1:])
                    return
                # 점프할 수 없는 도랑이면 정지(기존 동작)
                self.path = []
                self.state = "idle"
                self.event_waypoints = None
                return

            walkable, nl = self.check_walkable(nx, ny, mask_img, objects, npcs)
            if walkable:
                self.pos = [nx, ny]
                self.layer = nl
                self.state = "run" if str(getattr(self, "_move_mode", "walk")) == "run" else "walk"
                self._fire_jump_pad_hooks(mask_img, objects, npcs)
            else:
                self.path = []
                self.state = "idle"
                self.event_waypoints = None

    def follow_step(self, leader_pos, desired_dist, mask_img, objects, npcs, speed_mul=1.0, leader=None):
        """
        FOLLOW: 리더 뒤 슬롯 (tx, ty)만 목표로 잡고, 이동·도랑 점프는 MOVE와 동일하게
        set_new_target(A*) + move() 규칙을 사용한다.
        A*는 FOLLOW_REPLAN_MS / FOLLOW_REPLAN_DIST_PX / 슬롯 양자화로 스로틀한다.
        자기 점프·점프 태그 경로 중에는 재계획하지 않는다. 리더가 공중(_jump_arc)일 때는
        슬롯이 프레임마다 크게 튀어 재계획이 폭주하지 않도록 거리 트리거만 끈다(시간만).
        """
        try:
            self.event_speed_mul = float(speed_mul)
        except Exception:
            pass
        if not leader_pos:
            return
        lx, ly = float(leader_pos[0]), float(leader_pos[1])
        sx, sy = float(self.pos[0]), float(self.pos[1])
        dx, dy = lx - sx, ly - sy
        dnow = math.hypot(dx, dy)
        if dnow <= float(desired_dist or 0):
            sm = getattr(self, "stop_moving", None)
            if callable(sm):
                sm()
            return

        # 리더 방향으로 desired_dist 만큼 뒤에 위치한 점을 목표로
        if dnow < 1e-6:
            return
        ux, uy = dx / dnow, dy / dnow
        tx = lx - ux * float(desired_dist)
        ty = ly - uy * float(desired_dist)
        try:
            q = float(CONFIG.get("FOLLOW_SLOT_QUANTIZE_PX", 0) or 0)
        except Exception:
            q = 0.0
        if q > 0:
            tx = round(tx / q) * q
            ty = round(ty / q) * q
        self._follow_target = (tx, ty)
        if abs(tx - sx) > 0.1:
            self.direction = "left" if tx < sx else "right"

        if self._jump_arc is not None:
            return
        path = getattr(self, "path", None) or []
        if path and any(len(p) >= 3 and int(p[2]) == 1 for p in path):
            return

        # FOLLOW도 일반 이동 규칙(A* + 동일 move/점프)을 그대로 사용.
        now_ms = pygame.time.get_ticks()
        replan_ms = int(CONFIG.get("FOLLOW_REPLAN_MS", 180))
        try:
            replan_dist = float(CONFIG.get("FOLLOW_REPLAN_DIST_PX", 18.0))
        except Exception:
            replan_dist = 18.0

        leader_jumping = leader is not None and getattr(leader, "_jump_arc", None) is not None

        need_plan = False
        if not path:
            need_plan = True
        if (now_ms - int(getattr(self, "_follow_last_plan_ms", 0) or 0)) >= replan_ms:
            need_plan = True
        elif self._follow_slot_goal is None:
            need_plan = True
        elif not leader_jumping:
            if math.hypot(
                float(tx) - float(self._follow_slot_goal[0]), float(ty) - float(self._follow_slot_goal[1])
            ) >= replan_dist:
                need_plan = True

        if not need_plan:
            return

        self._follow_slot_goal = (float(tx), float(ty))
        self._follow_last_plan_ms = int(now_ms)
        if mask_img:
            # 목표만 리더 기반으로 잡고, 이동/점프 법칙은 set_new_target와 동일하게
            self.set_new_target(tx, ty, mask_img, objects or [], npcs or [])
        else:
            self.path = [(float(tx), float(ty), 0)]

    def _fire_jump_pad_hooks(self, mask_img, objects, npcs):
        """건반 오브젝트 / 맵 jump_pads 존(미니게임·리듬 확장용)."""
        px, py = self.pos[0], self.pos[1]
        for o in objects or []:
            if not getattr(o, "jump_pad", False):
                continue
            half_w = max(8, o.rect_for_logic.width // 2)
            half_h = max(6, o.rect_for_logic.height // 2)
            if abs(px - o.origin_pos[0]) < half_w and abs(py - o.origin_pos[1]) < half_h:
                cb = getattr(self, "on_jump_pad", None)
                if callable(cb):
                    cb(o)
                break
        for zp in getattr(self, "jump_pad_zones", None) or []:
            rect = zp.get("rect")
            if not rect or len(rect) < 4:
                continue
            r = pygame.Rect(int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
            if r.collidepoint(int(px), int(py)):
                cb = getattr(self, "on_jump_pad_zone", None)
                if callable(cb):
                    cb(zp)
                break

    def _strip_redundant_path_head(self):
        """시작점과 겹치는 일반 웨이포인트만 제거 (점프 웨이포인트는 유지)."""
        while self.path:
            pr = self.path[0]
            px, py = float(pr[0]), float(pr[1])
            tag = int(pr[2]) if len(pr) >= 3 else 0
            if tag == 1:
                break
            if math.hypot(px - self.pos[0], py - self.pos[1]) > 1.5:
                break
            self.path.pop(0)

    def set_new_target(self, tx, ty, mask_img=None, objects=None, npcs=None, preserve_path_anim=False, clear_event_waypoints=True):
        """목표가 생기면 경로를 미리 짜둡니다."""
        if clear_event_waypoints:
            self.event_waypoints = None
        if not preserve_path_anim:
            self.clear_anim_override()
        self._jump_arc = None
        # 새 목표면 기존 계획 취소
        self._path_plan_job = None
        tx, ty = float(tx), float(ty)
        self.target = [tx, ty]
        self.direction = "left" if tx < self.pos[0] else "right"
        sx, sy = float(self.pos[0]), float(self.pos[1])
        objects = objects or []
        npcs = npcs or []

        if mask_img:
            # 목표점이 도랑/벽이면 서 있을 수 없음 → 주변 walk로 스냅(선택)
            if CONFIG.get("TARGET_SNAP_TO_WALK", True) and mask_terrain_class(mask_img, tx, ty) != "walk":
                sn = _snap_to_nearest_walk(
                    mask_img,
                    tx,
                    ty,
                    max_r=CONFIG.get("TARGET_SNAP_MAX_R_PX", 48),
                    step=CONFIG.get("TARGET_SNAP_STEP_PX", 2),
                )
                if sn is None:
                    self.path = []
                    self.state = "idle"
                    self.event_waypoints = None
                    return
                tx, ty = float(sn[0]), float(sn[1])
                self.target = [tx, ty]
                self.direction = "left" if tx < self.pos[0] else "right"
            # 이동 모드: 기본은 걷기(A* 분할), 더블클릭은 직선 달리기(길찾기 없이)
            move_mode = str(getattr(self, "_move_mode", "walk") or "walk")
            if move_mode == "run":
                self.path = [(float(tx), float(ty), 0)]
                try:
                    self.event_speed_mul = float(CONFIG.get("RUN_SPEED_MUL", 1.8))
                except Exception:
                    self.event_speed_mul = 1.8
                self._click_run_restore = True
            else:
                # 핵심: A*는 프레임 분할로 돌려 클릭/이벤트 순간 멈칫을 제거한다.
                self._begin_path_plan_job(tx, ty, mask_img, objects, npcs)
        else:
            self.path = [(tx, ty, 0)]

    def stop_moving(self, preserve_anim_override=False):
        if not preserve_anim_override:
            self.clear_anim_override()
        self.path = []
        self.target = list(self.pos)
        if not preserve_anim_override:
            self.state = "idle"
        self._jump_arc = None
        self.event_waypoints = None
        self._move_mode = "walk"
        self._follow_slot_goal = None
        # 이벤트 MOVE force(true): 마스크/충돌 무시 플래그 해제
        try:
            self._event_force_move = False
        except Exception:
            pass
        if getattr(self, "_jump_shadow_override", None) == "hide":
            self._jump_shadow_override = None
        # 이벤트 MOVE speed(wait:false) 같은 임시 속도 복구
        try:
            if getattr(self, "_event_speed_restore", False):
                self.event_speed_mul = getattr(self, "_event_speed_old_mul", 1.0)
                self._event_speed_restore = False
        except Exception:
            pass
        # 더블클릭 달리기 속도 복구
        try:
            if getattr(self, "_click_run_restore", False):
                self.event_speed_mul = 1.0
                self._click_run_restore = False
        except Exception:
            pass


class Player(MaskWalkingCharacter):
    def __init__(self, name, pos, info):
        super().__init__(name, pos, info)
        self.stuck_time = 0

    def _clear_item_fly_flags(self, item):
        """CARRY fly 연출용 임시 플래그 초기화 (FieldItem.update 와 공유)."""
        try:
            item._event_fly_dest = None
            item._event_fly_drop_world = False
        except Exception:
            pass

    def begin_carry_pickup(self, item):
        """
        [CARRY / 상호작용] 들기 시작 — FieldItem 이 손 쪽으로 fly, 도착 후 is_held=True.
        Player.draw / render_pool 규칙은 기존 interact_with 와 동일.
        """
        from data import OBJ_ASSETS

        info = OBJ_ASSETS.get(getattr(item, "name", ""), {})
        if not info.get("is_holdable"):
            return False
        if getattr(item, "is_held", False) or getattr(item, "is_flying", False):
            return False
        if self.held_item:
            return False
        if getattr(item, "parent_slot", None):
            item.parent_slot.is_occupied = False
            item.parent_slot = None
        self._clear_item_fly_flags(item)
        self.held_item = item
        item.is_flying = True
        item.is_held = False
        item.target_slot = None
        try:
            item._carry_fly_dir = str(getattr(self, "direction", "left") or "left")
        except Exception:
            item._carry_fly_dir = "left"
        return True

    def begin_carry_put_slot(self, slot, *, flow=None, objs=None, npcs=None, map_id=""):
        """
        [CARRY / 상호작용] 슬롯(type=slot)에 내려놓기 — match_id·slot_kind 검사 후 fly.
        """
        from data import CONFIG, OBJ_ASSETS

        item = self.held_item
        if not item:
            return False
        info = OBJ_ASSETS.get(getattr(slot, "name", ""), {})
        item_info = OBJ_ASSETS.get(item.name, {})
        if info.get("type") != "slot":
            return False
        if item_info.get("match_id") != info.get("match_id"):
            return False
        slot_kind = str(info.get("slot_kind") or getattr(slot, "slot_kind", "") or "item").lower()
        if slot_kind == "crop" and getattr(slot, "is_occupied", False):
            return False
        item.pos = [float(item.pos[0]), float(item.pos[1])]
        item.origin_pos = list(item.pos)
        self._clear_item_fly_flags(item)
        item.is_flying = True
        item.is_held = False
        item.target_slot = slot
        self.held_item = None
        if slot_kind == "crop":
            plot_id = (
                getattr(slot, "plot_id", None)
                or info.get("plot_id")
                or CONFIG.get("GARDEN_DEFAULT_PLOT", "garden_01")
            )
            crop = str(item_info.get("crop_id") or "flower_1")
            try:
                stage = int(item_info.get("plant_stage", CONFIG.get("GARDEN_STAGE_PLANTED_WILT", 3)))
            except (TypeError, ValueError):
                stage = int(CONFIG.get("GARDEN_STAGE_PLANTED_WILT", 3))
            item._garden_plant_pending = {
                "plot_id": str(plot_id),
                "crop": crop,
                "stage": stage,
                "flow": flow,
                "map_id": str(map_id or ""),
                "objs": objs,
                "npcs": npcs,
            }
        return True

    def begin_carry_put_world(self, pos):
        """
        [CARRY] 월드 좌표에 내려놓기 — 슬롯 없이 바닥에 두는 연출 (이벤트 CARRY pos 용).
        fly 종료 후 is_held=False, 맵 오브젝트로 남음.
        """
        item = self.held_item
        if not item:
            return False
        try:
            tx, ty = float(pos[0]), float(pos[1])
        except (TypeError, ValueError, IndexError):
            return False
        item.pos = [float(item.pos[0]), float(item.pos[1])]
        item.origin_pos = list(item.pos)
        self._clear_item_fly_flags(item)
        item._event_fly_dest = [tx, ty]
        item._event_fly_drop_world = True
        item.is_flying = True
        item.is_held = False
        item.target_slot = None
        self.held_item = None
        return True

    def interact_with(self, target, *, flow=None, objs=None, npcs=None, map_id=""):
        """플레이어 클릭 상호작용 — CARRY 핵심 로직(begin_carry_*) 재사용."""
        from flow import entity_carry_click_allowed

        if not self.held_item:
            if entity_carry_click_allowed(target):
                return self.begin_carry_pickup(target)
            return False
        return self.begin_carry_put_slot(
            target,
            flow=flow,
            objs=objs,
            npcs=npcs,
            map_id=map_id,
        )

    def handle_input(self, m_pos, mask_img, objects, npcs=None, move_mode="walk"):
        """마우스/키보드 입력을 받아 이동 경로를 계산하고 상호작용 대상이 있는지 확인합니다."""
        from data import OBJ_ASSETS

        wx, wy = m_pos[0], m_pos[1]
        
        # 1. 이동 경로 계산 (이전에 수정한 똑똑한 길찾기 호출)
        # main.py에서 보내주는 mask, objects, npcs를 그대로 사용합니다.
        self._move_mode = (str(move_mode or "walk").strip().lower() or "walk")
        self.set_new_target(wx, wy, mask_img, objects, npcs)
        
        # 2. NPC 상호작용 — 클릭은 스프라이트 히트만(접근 거리 range 와 분리)
        pool = npcs or []
        best_npc, best_d = None, 1e9
        try:
            from char_behavior import npc_interact_enabled
            from flow import click_hits_entity_sprite, entity_interact_enabled

            for n in pool:
                if not (npc_interact_enabled(n) or entity_interact_enabled(n)):
                    continue
                if not click_hits_entity_sprite(n, wx, wy):
                    continue
                op = getattr(n, "origin_pos", None) or getattr(n, "pos", None)
                if not op:
                    continue
                d = math.dist([wx, wy], op)
                if d < best_d:
                    best_d, best_npc = d, n
        except Exception:
            best_npc = None
        if best_npc is not None:
            return "interact_npc", best_npc

        # 3. 손에 든 채 슬롯에 놓기
        if self.held_item:
            for o in objects:
                oinfo = OBJ_ASSETS.get(getattr(o, "name", ""), {})
                if oinfo.get("type") == "slot" and math.dist([wx, wy], o.origin_pos) < 34:
                    return "interact", o

        # 4. progress 조건 이벤트 상호작용 — 클릭은 스프라이트 히트, 실행 거리는 main 의 range
        try:
            from flow import click_hits_entity_sprite, entity_interact_enabled

            best_io, best_id = None, 1e9
            for o in objects:
                if not entity_interact_enabled(o):
                    continue
                if not click_hits_entity_sprite(o, wx, wy):
                    continue
                op = getattr(o, "origin_pos", None) or getattr(o, "pos", None)
                if not op:
                    continue
                d = math.dist([wx, wy], op)
                if d < best_id:
                    best_id, best_io = d, o
            if best_io is not None:
                return "interact", best_io
        except Exception:
            pass

        # 5. 클릭 줍기 — interact.enabled true 이고 bindings 없을 때만 (이벤트 전용은 CARRY)
        try:
            from flow import click_hits_entity_sprite, entity_carry_click_allowed

            for o in objects:
                if not entity_carry_click_allowed(o):
                    continue
                if click_hits_entity_sprite(o, wx, wy):
                    return "interact", o
        except Exception:
            pass

        return "move", None


def _field_world_to_screen_anchor(
    world_x,
    world_y,
    cam_x,
    cam_y,
    zoom,
    *,
    height=0.0,
    y_transform=None,
    x_offset_fn=None,
    anchor="feet",
):
    """
    월드 앵커 좌표 → 화면 앵커 (float, blit 직전).
    FieldItem · Effect(ANIM_ONCE/EFFECT) · 월드 클릭 마커 등 필드 스프라이트 공통.
    UI(논리 해상도 고정 오버레이)는 이 함수를 쓰지 않는다.

    anchor:
      feet/foot/ground/bottom — pos 는 발(바닥) 격자. height>0 이면 Y에서 height*zoom 만큼 위로.
      center/head/… — pos 가 앵커 그대로 (height 보정 없음).
    """
    z = float(zoom)
    dx_base = float((float(world_x) - float(cam_x)) * z)
    dy_base = float((float(world_y) - float(cam_y)) * z)
    if callable(y_transform):
        try:
            dy_base = float(y_transform(dy_base))
        except Exception:
            pass
    dy_q = float(int(round(float(dy_base))))
    if callable(x_offset_fn):
        try:
            dx_base = float(dx_base) + float(x_offset_fn(float(dy_q)))
        except Exception:
            pass
    anc = (anchor or "feet").strip().lower()
    if anc in ("feet", "foot", "ground", "bottom"):
        h_off = float(height or 0.0)
        if h_off > 0.0:
            dy_base = float(dy_q) - h_off * z
        else:
            dy_base = float(dy_q)
    else:
        dy_base = float(dy_q)
    return dx_base, dy_base


def _prepare_field_sprite_blit(
    current_img,
    dx_base,
    dy_base,
    *,
    eff_z,
    sprite_tilt=1.0,
    sprite_perspective_q=None,
    x_offset_fn=None,
    shear_lod=False,
    shear_cache_holder=None,
    anchor="feet",
    alpha=255,
):
    """
    줌·원근·쉬어·발/중심 앵커까지 적용한 (render_img, blit_x, blit_y).
    FieldItem.draw 와 Effect.draw 가 동일 규칙으로 월드에 붙는다.
    """
    if current_img is None:
        return None

    render_img = get_cached_scaled_sprite(
        current_img,
        float(eff_z),
        sprite_perspective_q=sprite_perspective_q,
        sprite_tilt=float(sprite_tilt),
    )

    try:
        a = int(alpha)
    except (TypeError, ValueError):
        a = 255
    if a < 255:
        try:
            render_img = render_img.copy()
            render_img.set_alpha(a)
        except Exception:
            pass

    anc = (anchor or "feet").strip().lower()
    if anc in ("center", "c", "middle", "head", "top"):
        cpx = int(round(float(dx_base)))
        cpy = int(round(float(dy_base)))
        left, top = blit_topleft_center_on_pixel(
            cpx, cpy, render_img.get_width(), render_img.get_height()
        )
        return render_img, int(left), int(top)

    pre_w = int(render_img.get_width())
    dx_adj = 0
    shear_applied = False
    try:
        st = float(sprite_tilt)
    except Exception:
        st = 1.0
    if st < 0.999 and callable(x_offset_fn) and render_img.get_height() > 1:
        try:
            slice_h = int(CONFIG.get("SPRITE_SHEAR_SLICE_H_PX", CONFIG.get("TILT_SHEAR_SLICE_H_PX", 8)) or 8)
        except Exception:
            slice_h = 8
        if bool(shear_lod) and not bool(CONFIG.get("SPRITE_SHEAR_DURING_ANIM", False)):
            slice_h = 999999
        elif bool(shear_lod):
            try:
                slice_h = max(int(slice_h), int(CONFIG.get("SPRITE_SHEAR_SLICE_H_PX_LOD", 14) or 14))
            except Exception:
                slice_h = max(int(slice_h), 14)
        top_y = float(dy_base) - float(render_img.get_height())
        bot_y = float(dy_base)
        try:
            q = int(CONFIG.get("SPRITE_SHEAR_Y_QUANT_PX", 2) or 2)
        except Exception:
            q = 2
        if bool(shear_lod):
            try:
                q = int(CONFIG.get("SPRITE_SHEAR_Y_QUANT_PX_LOD", 8) or 8)
            except Exception:
                q = max(4, q)
        q = max(1, min(32, int(q)))
        try:
            qtop = int(round(float(top_y) / float(q))) * q
            qbot = int(round(float(bot_y) / float(q))) * q
            base_off_i = int(round(float(x_offset_fn(float(qbot)))))
        except Exception:
            qtop, qbot, base_off_i = int(round(top_y)), int(round(bot_y)), 0
        skey = (id(render_img), int(slice_h), int(qtop), int(qbot), int(base_off_i))
        cached = getattr(shear_cache_holder, "_sprite_shear_cache", None) if shear_cache_holder else None
        if cached is not None and cached.get("key") == skey:
            render_img = cached.get("surf", render_img)
            dx_adj = int(cached.get("dx", 0) or 0)
        else:
            if int(slice_h) >= 999999:
                dx_adj = 0
            else:
                render_img, dx_adj = _shear_surface_by_field_xoffset(
                    render_img,
                    top_y_screen=float(qtop),
                    bottom_y_screen=float(qbot),
                    x_offset_fn=x_offset_fn,
                    slice_h=slice_h,
                )
            if shear_cache_holder is not None:
                try:
                    shear_cache_holder._sprite_shear_cache = {
                        "key": skey,
                        "surf": render_img,
                        "dx": int(dx_adj),
                    }
                except Exception:
                    pass
        shear_applied = int(render_img.get_width()) != int(pre_w)

    feet_sx = int(round(float(dx_base)))
    feet_sy = int(round(float(dy_base)))
    if shear_applied:
        final_dx = float(left_edge_bottom_center_x(feet_sx, pre_w)) + float(dx_adj)
    else:
        final_dx = float(left_edge_bottom_center_x(feet_sx, render_img.get_width()))
    final_dy = float(feet_sy - render_img.get_height())
    return render_img, int(round(final_dx)), int(round(final_dy))


def _held_item_foot_world_pos(player_x, player_y, direction):
    """
    손에 든 FieldItem 의 월드 발 격자 — 바닥에 놓을 때·FieldItem.draw 와 동일 의미.
    CONFIG: HELD_ITEM_FOOT_OFFSET_X(기본 12), HELD_ITEM_FOOT_OFFSET_Y(기본 15, fly 목표와 동일).
    """
    try:
        ox = float(CONFIG.get("HELD_ITEM_FOOT_OFFSET_X", 12))
    except (TypeError, ValueError):
        ox = 12.0
    try:
        oy = float(CONFIG.get("HELD_ITEM_FOOT_OFFSET_Y", 15))
    except (TypeError, ValueError):
        oy = 15.0
    ox = max(0.0, min(200.0, ox))
    oy = max(0.0, min(200.0, oy))
    d = str(direction or "left").strip().lower()
    wx = float(player_x) + (ox if d == "right" else -ox)
    wy = float(player_y) - oy
    return wx, wy


class FieldItem:
    def __init__(self, name, x, y, sprite_tilt=None, height=None, ysort_mode=None, layer=None):
        from data import OBJ_ASSETS, CONFIG # CONFIG 추가
        self.name, self.pos, self.origin_pos = name, [float(x), float(y)], [float(x), float(y)]
        self.sprite_tilt = _clamp_sprite_tilt(sprite_tilt if sprite_tilt is not None else 1.0)
        info = OBJ_ASSETS.get(name, {})
        if ysort_mode is not None:
            self.ysort_mode = _normalize_ysort_mode(ysort_mode)
        else:
            self.ysort_mode = _normalize_ysort_mode(info.get("ysort", "ground"))
        if height is not None:
            self.height = _clamp_draw_height(height)
        else:
            self.height = _clamp_draw_height(info.get("height", 0))
        
        # layer 기능 도입 (기본값 0)
        # 이제 except_ysorting 대신 self.layer 값을 사용합니다.
        if layer is not None:
            try:
                self.layer = int(float(layer))
            except Exception:
                self.layer = int(info.get("layer", 0) or 0)
        else:
            self.layer = int(info.get("layer", 0) or 0)

        self.event_entity_zoom = 1.0
        self.event_entity_zoom_target = 1.0
        try:
            self.event_entity_zoom_speed = float(CONFIG.get("ENTITY_ZOOM_LERP", 0.12))
        except Exception:
            self.event_entity_zoom_speed = 0.12

        self.is_slot = (info.get("type") == "slot")
        self.blink_timer = 0 # 깜빡임용
        
        self.is_holdable = info.get("is_holdable", False)
        # progress→events.json 상호작용 (flow.merge_interact_spec, 맵 인스턴스는 load_map 에서 덮어씀)
        self.interact_instance = {}
        try:
            from flow import merge_interact_spec

            self.interact_spec = merge_interact_spec(info, {})
        except Exception:
            self.interact_spec = dict(info.get("interact") or {})
        self.collision = info.get("collision", False)
        self.can_hide_player = info.get("can_hide_player", False)
        self.type = info.get("type", "item")
        self.jump_pad = bool(info.get("jump_pad", False))
        
        # 이미지 로드 로직
        self.frames = self.load_obj_anim(name)
        self.image = self.frames[0]
        
        # [수정] 이미지가 분홍색 사각형(기본값)이고 슬롯 타입이면, 
        # 나중에 draw에서 깜빡이로 대체하기 위해 체크용 변수 설정
        self.has_real_image = True
        if info.get("path") is None and not os.path.isdir(os.path.join("assets", "images", "object", name)):
            self.has_real_image = False

        self.rect_for_logic = self.image.get_rect()
        self.frame_idx = 0
        self.last_anim_time = 0
        self.anim_delay = _obj_anim_delay_ms(info)
        self.is_held = False
        self.is_flying = False
        self.fly_speed = 0.2
        self.is_occupied = False
        self.parent_slot = None
        self.target_slot = None
        # 이벤트 MOVE(직선 이동·웨이포인트) — BaseCharacter와 동일 API
        self.direction = "left"
        self.target = list(self.pos)
        self.path = []
        self.event_waypoints = None
        self.event_speed_mul = 1.0
        self._event_speed_restore = False
        self._event_speed_old_mul = 1.0
        self._event_wp_preserve_path_anim = False

    def stop_moving(self, preserve_anim_override=False):
        self.path = []
        self.target = list(self.pos)
        self.event_waypoints = None
        try:
            if getattr(self, "_event_speed_restore", False):
                self.event_speed_mul = getattr(self, "_event_speed_old_mul", 1.0)
                self._event_speed_restore = False
        except Exception:
            pass

    def _arrival_finish_segment(self, mask_img=None, objects=None, npcs=None, preserve_path_anim=False):
        wps = getattr(self, "event_waypoints", None)
        if isinstance(wps, list) and len(wps) > 0:
            p0 = wps[0]
            rest = list(wps[1:]) if len(wps) > 1 else []
            try:
                nx, ny = float(p0[0]), float(p0[1])
            except (TypeError, ValueError, IndexError):
                self.event_waypoints = None
                self.stop_moving()
                return
            self.event_waypoints = rest if rest else None
            self.set_new_target(
                nx,
                ny,
                mask_img,
                objects,
                npcs,
                preserve_path_anim=preserve_path_anim,
                clear_event_waypoints=False,
            )
            return
        self.event_waypoints = None
        preserve = bool(preserve_path_anim) or bool(
            getattr(self, "_event_wp_preserve_path_anim", False)
        )
        self.stop_moving()
        if preserve:
            try:
                self._event_wp_preserve_path_anim = False
            except Exception:
                pass

    def set_new_target(
        self,
        tx,
        ty,
        mask_img=None,
        objects=None,
        npcs=None,
        preserve_path_anim=False,
        clear_event_waypoints=True,
    ):
        if clear_event_waypoints:
            self.event_waypoints = None
        self.target = [float(tx), float(ty)]
        if abs(float(tx) - float(self.pos[0])) > 0.1:
            self.direction = "left" if float(tx) < float(self.pos[0]) else "right"
        self.path = [(float(tx), float(ty))]

    def move(self, mask=None, objs=None, npcs=None):
        if not self.path:
            return
        tick_straight_line_path(self)

    def load_obj_anim(self, name):
        path = os.path.join("assets", "images", "object", name)
        frames = _load_anim_dir_cached(path)
        if frames:
            return frames
        try:
            info = OBJ_ASSETS.get(name, {})
            rel = info.get("path")
            if rel:
                mx = int(CONFIG.get("OBJ_ANIM_MAX_FRAMES", 64) or 64)
                frames = _load_obj_asset_frames(rel, max_frames=mx)
                if frames:
                    return frames
        except Exception:
            pass
        surf = pygame.Surface((16, 16))
        surf.fill((255, 0, 255))
        return [surf]

    def retarget_object_def(self, new_name: str) -> bool:
        """
        object_defs 키만 바꿔 스프라이트·들기 속성 갱신 (이벤트 CHANGE, 들고 있는 중 포함).
        맵 인스턴스·player.held_item 참조는 그대로.
        """
        from data import OBJ_ASSETS

        key = str(new_name or "").strip()
        if not key or key not in OBJ_ASSETS:
            return False
        info = OBJ_ASSETS.get(key, {}) or {}
        self.name = key
        self.is_holdable = bool(info.get("is_holdable", False))
        self.collision = bool(info.get("collision", False))
        self.can_hide_player = bool(info.get("can_hide_player", False))
        self.type = info.get("type", "item")
        self.match_id = info.get("match_id")
        self.frames = self.load_obj_anim(key)
        self.frame_idx = 0
        self.image = self.frames[0] if self.frames else self.image
        try:
            from flow import merge_interact_spec

            inst = getattr(self, "interact_instance", None) or {}
            self.interact_spec = merge_interact_spec(info, {"interact": inst} if inst else {})
        except Exception:
            self.interact_spec = dict(info.get("interact") or {})
        return True

    def _anim_frame_idx(self):
        n = len(self.frames)
        if n <= 1:
            return 0
        delay = max(16, int(getattr(self, "anim_delay", 150) or 150))
        return (pygame.time.get_ticks() // delay) % n

    def update_anim(self):
        if len(self.frames) > 1:
            idx = self._anim_frame_idx()
            if idx != self.frame_idx:
                self.frame_idx = idx
                self.image = self.frames[idx]

    def draw(self, screen, cam_x, cam_y, player=None, global_frame=0, zoom=1.0, y_transform=None, x_offset_fn=None, sprite_perspective_q=None, shear_lod=False):
        if self.is_held: return

        try:
            ez = float(getattr(self, "event_entity_zoom", 1.0) or 1.0)
        except Exception:
            ez = 1.0
        ez = max(0.05, min(8.0, ez))
        eff_z = float(zoom) * ez

        # --- [1. 기본 좌표 계산] — FieldItem·Effect(ANIM_ONCE) 공통 규칙 ---
        dx_base, dy_base = _field_world_to_screen_anchor(
            self.pos[0],
            self.pos[1],
            cam_x,
            cam_y,
            zoom,
            height=float(getattr(self, "height", 0) or 0),
            y_transform=y_transform,
            x_offset_fn=x_offset_fn,
            anchor="feet",
        )

        # --- [2. 이미지 준비 & 크기 파악] ---
        # 최적화 검사 전에 이미지 크기를 알아야 정확한 마진을 잡을 수 있습니다.
        # anim_delay_ms 기준(전역 global_frame은 사용하지 않음 — 예전 100ms 고정 타이머)
        current_img = self.image
        if len(self.frames) > 1:
            idx = self._anim_frame_idx()
            current_img = self.frames[idx]
            self.frame_idx = idx
            self.image = current_img

        # 실제 그려질 이미지의 너비와 높이 (카메라 줌 × 이벤트 엔티티 배율)
        img_w = int(current_img.get_width() * eff_z)
        img_h = int(current_img.get_height() * eff_z)

        asc_pre = getattr(self, "auto_scroll", None)
        tile_hscroll = False
        if isinstance(asc_pre, dict):
            try:
                vx_pre = float(asc_pre.get("vx", 0.0) or 0.0)
            except Exception:
                vx_pre = 0.0
            wm_pre = str(asc_pre.get("wrap", "camera_view") or "camera_view").strip().lower()
            tile_hscroll = abs(vx_pre) > 1e-9 and wm_pre not in ("legacy_wrap", "teleport")
        
        # 슬롯처럼 이미지가 작아도 최소 50픽셀의 여유는 줍니다.
        # 가로 타일 스크롤: 발(앵커)만으로 컬링하면 넓은 레이어가 화면 밖으로 잘못 걸러질 수 있음
        if tile_hscroll:
            margin_w = max(50, img_w * 2 + 120)
        else:
            margin_w = max(50, img_w // 2 + 10)
        margin_h = max(50, img_h + 10)

        from data import CONFIG
        screen_w = CONFIG["WIDTH"]
        screen_h = CONFIG["HEIGHT"]

        # --- [3. 최적화 조건문 (이미지 크기 반영)] ---
        # 이미지 전체가 화면 밖으로 완전히 나갔을 때만 return 합니다.
        if dx_base < -margin_w or dx_base > screen_w + margin_w or \
           dy_base < -10 or dy_base > screen_h + margin_h: # dy_base는 발 밑 기준이므로 상단 여유는 넉넉히
            return 
        
        # --- [4. 나머지 로직 (슬롯, 스케일링, 투명도 등 동일)] ---
        if self.is_slot and not self.has_real_image:
            import math
            self.blink_timer += 0.05
            alpha = int((math.sin(self.blink_timer * 5) + 1) * 127.5)
            
            base_size = int(20 * eff_z)
            # 성능: 매 프레임 Surface 생성하지 말고 재사용
            try:
                if getattr(self, "_slot_blink_surf", None) is None or int(getattr(self, "_slot_blink_size", 0) or 0) != int(base_size):
                    self._slot_blink_surf = pygame.Surface((base_size, base_size), pygame.SRCALPHA)
                    self._slot_blink_size = int(base_size)
                s = self._slot_blink_surf
            except Exception:
                s = pygame.Surface((base_size, base_size), pygame.SRCALPHA)
            try:
                s.fill((0, 0, 0, 0))
            except Exception:
                pass
            pygame.draw.circle(s, (0, 255, 0, alpha), (base_size//2, base_size//2), int(6 * eff_z))
            pygame.draw.circle(s, (255, 255, 255, alpha), (base_size//2, base_size//2), int(2 * eff_z))
            fpx, fpy = int(round(float(dx_base))), int(round(float(dy_base)))
            sx, sy = blit_topleft_center_on_pixel(fpx, fpy, base_size, base_size)
            screen.blit(s, (sx, sy))
            return


        if self.can_hide_player and player:
            # 1. 기본적인 층수 및 앞뒤 관계 확인
            is_lower = player.layer < self.layer
            is_same_layer_behind = (player.layer == self.layer and player.pos[1] < self.pos[1])
            
            # 2. [핵심 수정] 가로(X) 범위 판정
            half_w = current_img.get_width() // 2
            is_inside_x = abs(self.pos[0] - player.pos[0]) < (half_w * 0.8) # 좌우 80% 영역만 감지

            # 3. [핵심 수정] 세로(Y) 범위 판정 (건물 바닥에서 위로만 감지)
            # 플레이어가 건물 바닥선(self.pos[1])보다 위에 있고, 
            # 건물의 전체 높이(img_h) 이내에 있을 때만 "가려진 것"으로 간주
            # (player.pos[1] - 20)은 플레이어의 허리 높이 기준입니다.
            foot_y = float(self.pos[1]) - float(getattr(self, "height", 0) or 0)
            is_inside_y = (foot_y - img_h) < (player.pos[1] - 20) < foot_y

            # 최종 판정: 뒤에 있거나 아래층에 있으면서, '실제 이미지 영역(X, Y)' 안에 들어왔을 때만!
            if (is_lower or is_same_layer_behind) and is_inside_x and is_inside_y:
                # shared frame surface를 직접 set_alpha 하지 않도록 copy
                try:
                    ci = current_img.copy()
                    ci.set_alpha(150)
                    current_img = ci
                except Exception:
                    pass
            else:
                pass

        # 줌·쉬어·발 앵커 (Effect/ANIM_ONCE 와 동일 — _prepare_field_sprite_blit)
        prepared = _prepare_field_sprite_blit(
            current_img,
            dx_base,
            dy_base,
            eff_z=eff_z,
            sprite_tilt=getattr(self, "sprite_tilt", 1.0),
            sprite_perspective_q=sprite_perspective_q,
            x_offset_fn=x_offset_fn,
            shear_lod=shear_lod,
            shear_cache_holder=self,
            anchor="feet",
        )
        if prepared is None:
            return
        render_img, fx, fy = prepared
        asc = getattr(self, "auto_scroll", None)
        do_h_tile = False
        if isinstance(asc, dict) and not self.is_slot:
            try:
                vx_a = float(asc.get("vx", 0.0) or 0.0)
            except Exception:
                vx_a = 0.0
            wm_a = str(asc.get("wrap", "camera_view") or "camera_view").strip().lower()
            do_h_tile = abs(vx_a) > 1e-9 and wm_a not in ("legacy_wrap", "teleport")
        if do_h_tile:
            try:
                iw_nat = max(1.0, float(current_img.get_width()))
            except Exception:
                iw_nat = 1.0
            try:
                acc = float(getattr(self, "_auto_scroll_accum", 0.0))
            except Exception:
                acc = 0.0
            acc = acc % iw_nat
            rw = max(1, int(render_img.get_width()))
            try:
                off = int(round((acc / iw_nat) * float(rw))) % rw
            except Exception:
                off = 0
            x0 = fx - off
            screen.blit(render_img, (x0, fy))
            screen.blit(render_img, (x0 + rw, fy))
        else:
            screen.blit(render_img, (fx, fy))

    def update(self, player_pos):
        if self.is_flying:
            # fly 목표: 이벤트 CARRY pos > 슬롯 > 손(들기)
            fly_dest = getattr(self, "_event_fly_dest", None)
            if fly_dest is not None:
                try:
                    tx, ty = float(fly_dest[0]), float(fly_dest[1])
                except (TypeError, ValueError, IndexError):
                    tx, ty = float(player_pos[0]), float(player_pos[1]) - 15.0
            elif self.target_slot:
                tx, ty = self.target_slot.origin_pos
            else:
                fly_dir = getattr(self, "_carry_fly_dir", "left")
                tx, ty = _held_item_foot_world_pos(
                    player_pos[0], player_pos[1], fly_dir
                )
            self.pos[0] += (tx - self.pos[0]) * self.fly_speed
            self.pos[1] += (ty - self.pos[1]) * self.fly_speed
            # 실시간 클릭 좌표 동기화
            self.origin_pos = [self.pos[0], self.pos[1]]
            if math.dist(self.pos, (tx, ty)) < 2:
                # [강제 고정] 소수점 오차 제거
                self.pos = [float(tx), float(ty)]
                self.origin_pos = [float(tx), float(ty)]
                self.is_flying = False
                drop_world = bool(getattr(self, "_event_fly_drop_world", False))
                try:
                    self._event_fly_dest = None
                    self._event_fly_drop_world = False
                except Exception:
                    pass
                if self.target_slot:
                    self.target_slot.is_occupied = True
                    self.parent_slot = self.target_slot
                    self.target_slot = None
                    self.is_held = False
                elif drop_world:
                    self.is_held = False
                else:
                    self.is_held = True


def _load_effect_frames(effect_name: str):
    """
    EFFECT 스텝 / Effect 클래스용 프레임 로드.
    - object_defs 키(name)의 path → FieldItem과 동일(_load_obj_asset_frames)
    - 레거시: OBJ_ASSETS[name].imgs 에 Surface 리스트가 있으면 그대로 사용
    """
    info = OBJ_ASSETS.get(str(effect_name or "").strip(), {}) or {}
    rel = info.get("path")
    if rel:
        try:
            mx = int(CONFIG.get("OBJ_ANIM_MAX_FRAMES", 64) or 64)
        except Exception:
            mx = 64
        frames = _load_obj_asset_frames(str(rel), max_frames=mx)
        if frames:
            return frames
    imgs = info.get("imgs")
    if isinstance(imgs, (list, tuple)) and imgs:
        out = []
        for im in imgs:
            if im is not None:
                try:
                    out.append(im)
                except Exception:
                    pass
        if out:
            return out
    return []


def _effect_anchor_from_step(step) -> str:
    a = (step.get("anchor") or "feet").strip().lower()
    if a in ("feet", "foot", "ground", "bottom"):
        return "feet"
    if a in ("center", "c", "middle"):
        return "center"
    if a in ("head", "top"):
        return "head"
    return "feet"


def _effect_pos_from_step(step, *, player, npcs, objs):
    """EFFECT 스텝 → 월드 [x,y]. target 있으면 anchor 기준, 없으면 pos."""
    if "target" in step:
        target_name = step.get("target")
        target = (
            player
            if target_name == "player"
            else next((x for x in (npcs + objs) if getattr(x, "name", "") == target_name), None)
        )
        if target:
            try:
                px = float(target.pos[0])
                py = float(target.pos[1])
            except (TypeError, ValueError):
                px, py = 0.0, 0.0
            try:
                h_off = float(getattr(target, "height", 0) or 0)
            except (TypeError, ValueError):
                h_off = 0.0
            anchor = _effect_anchor_from_step(step)
            if anchor == "head":
                py = py - 50.0 - h_off
            elif anchor == "center":
                py = py - h_off * 0.5
            return [px, py]
    raw = step.get("pos", [0, 0])
    try:
        return [float(raw[0]), float(raw[1])]
    except (TypeError, ValueError, IndexError):
        return [0.0, 0.0]


def _anim_once_pos_from_step(step):
    """ANIM_ONCE: pos [x,y] 만 사용 (target/anchor 없음)."""
    raw = step.get("pos", [0, 0])
    try:
        return float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError):
        return 0.0, 0.0


def _parse_carry_step_action(step) -> str:
    """
    CARRY 스텝 action → 'pick' | 'put' | ''.
    pick: pick/take/grab/hold …  put: put/drop/place/release …
    """
    raw = (step.get("action") or step.get("mode") or "").strip().lower()
    if raw in ("pick", "take", "grab", "hold", "get", "pickup", "pick_up", "들기"):
        return "pick"
    if raw in ("put", "drop", "place", "release", "putdown", "put_down", "drop_down", "놓기", "내려놓기"):
        return "put"
    if raw in ("pick", "put"):
        return raw
    return ""


def _parse_carry_step_wait(step) -> bool:
    """CARRY wait — fly 연출 끝날 때까지 다음 스텝 보류 (기본 true)."""
    w = step.get("wait")
    if w is None:
        return True
    if isinstance(w, str):
        return w.strip().lower() not in ("0", "false", "f", "no", "n", "off")
    return bool(w)


def _event_resolve_entity(name, player, npcs, objs):
    """이벤트 스텝 target/holder → player | FieldItem | BaseCharacter | None."""
    tn = (name or "").strip()
    if not tn:
        return None
    if tn == "player":
        return player
    for pool in (objs or [], npcs or []):
        for ent in pool:
            if getattr(ent, "name", "") == tn:
                return ent
    return None


def _event_find_holdable_obj(name, objs):
    """맵 위 들 수 있는 오브젝트 1개 (이름 일치, 아직 안 들림)."""
    tn = (name or "").strip()
    if not tn:
        return None
    for o in objs or []:
        if getattr(o, "name", "") != tn:
            continue
        if getattr(o, "is_held", False) or getattr(o, "is_flying", False):
            continue
        if getattr(o, "is_holdable", False):
            return o
        try:
            from data import OBJ_ASSETS
            if OBJ_ASSETS.get(tn, {}).get("is_holdable"):
                return o
        except Exception:
            pass
    return None


def _parse_effect_step_wait(step) -> bool:
    w = step.get("wait")
    if w is None:
        return False
    if isinstance(w, str):
        return w.strip().lower() not in ("0", "false", "f", "no", "n", "off")
    return bool(w)


class Effect:
    """
    이벤트 EFFECT 스텝: 월드 좌표에 스프라이트 애니 1회(또는 loop) 재생.
    object_defs 의 path / name_0.png … 시퀀스를 FieldItem 과 같은 방식으로 로드한다.
    """

    def __init__(self, name, x, y, loop=False, *, anim_delay_ms=None, anchor="feet"):
        self.name = name
        self.pos = [float(x), float(y)]
        self.loop = bool(loop)
        self.anchor = (anchor or "feet").strip().lower()
        self.images = _load_effect_frames(name)
        self.alpha = 255
        self.frame_idx = 0
        self.is_done = False
        info = OBJ_ASSETS.get(str(name or "").strip(), {}) or {}
        self.height = _clamp_draw_height(info.get("height", 0))
        self.sprite_tilt = _clamp_sprite_tilt(
            info.get("sprite_tilt") if info.get("sprite_tilt") is not None else 1.0
        )
        self._sprite_shear_cache = None
        if anim_delay_ms is not None and str(anim_delay_ms).strip() != "":
            try:
                self.anim_delay_ms = max(16, int(float(anim_delay_ms)))
            except (TypeError, ValueError):
                self.anim_delay_ms = _obj_anim_delay_ms(info)
        else:
            self.anim_delay_ms = _obj_anim_delay_ms(info)
        try:
            self._t0_ms = int(pygame.time.get_ticks())
        except Exception:
            self._t0_ms = 0
        if not self.images:
            self.is_done = True
            try:
                rel = (OBJ_ASSETS.get(str(name or "").strip(), {}) or {}).get("path", "")
            except Exception:
                rel = ""
            print(
                f"[EFFECT/ANIM_ONCE] '{name}' 프레임 없음 — "
                f"assets/{rel}_0.png … 또는 assets/{rel}/ 폴더 확인"
            )

    def _frame_index(self):
        n = len(self.images)
        if n <= 0:
            return 0
        if n <= 1:
            return 0
        delay = max(16, int(getattr(self, "anim_delay_ms", 150) or 150))
        elapsed = max(0, int(pygame.time.get_ticks()) - int(getattr(self, "_t0_ms", 0) or 0))
        return min(n - 1, elapsed // delay) if not self.loop else (elapsed // delay) % n

    def update(self):
        if self.is_done or not self.images:
            return
        n = len(self.images)
        delay = max(16, int(getattr(self, "anim_delay_ms", 150) or 150))
        elapsed = max(0, int(pygame.time.get_ticks()) - int(getattr(self, "_t0_ms", 0) or 0))
        if self.loop:
            self.frame_idx = (elapsed // delay) % n if n > 1 else 0
            return
        if n <= 1:
            self.frame_idx = 0
            self.is_done = True
            return
        played = elapsed // delay
        self.frame_idx = min(n - 1, played)
        if played >= n:
            self.frame_idx = n - 1
            self.is_done = True

    def draw(
        self,
        screen,
        cam_x,
        cam_y,
        zoom=1.0,
        y_transform=None,
        x_offset_fn=None,
        sprite_perspective_q=None,
        shear_lod=False,
    ):
        """
        월드 이펙트(ANIM_ONCE/EFFECT) — FieldItem 과 동일한 틸트/쉬어/발·중심 앵커 규칙.
        main.py 가 y_transform·x_offset_fn·sprite_perspective_q 를 넘겨야 PLACE 오브젝트와 좌표가 일치한다.
        """
        if self.is_done or not self.images:
            return
        idx = max(0, min(len(self.images) - 1, int(self.frame_idx)))
        img = self.images[idx]
        anc = (self.anchor or "feet").strip().lower()
        dx_base, dy_base = _field_world_to_screen_anchor(
            self.pos[0],
            self.pos[1],
            cam_x,
            cam_y,
            zoom,
            height=float(getattr(self, "height", 0) or 0),
            y_transform=y_transform,
            x_offset_fn=x_offset_fn,
            anchor=anc,
        )
        prepared = _prepare_field_sprite_blit(
            img,
            dx_base,
            dy_base,
            eff_z=float(zoom),
            sprite_tilt=getattr(self, "sprite_tilt", 1.0),
            sprite_perspective_q=sprite_perspective_q,
            x_offset_fn=x_offset_fn,
            shear_lod=shear_lod,
            shear_cache_holder=self,
            anchor=anc,
            alpha=self.alpha,
        )
        if prepared is None:
            return
        render_img, fx, fy = prepared
        screen.blit(render_img, (fx, fy))


class Camera:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.target_zoom = 1.0
        self.current_zoom = 1.0
        self.zoom_step = 0.1  # 아버님이 설정하신 0.1!
        self.pos = [0, 0]
        self.image_cache = {}
        # follow_player | follow_entity | fixed_world
        self._cam_mode = "follow_player"
        self._follow_entity_name = ""
        self._fixed_world = [0.0, 0.0]
        self._cam_smooth = True
        try:
            self._cam_lerp = float(CONFIG.get("CAMERA_FOLLOW_LERP", 0.1) or 0.1)
        except Exception:
            self._cam_lerp = 0.1
        self._cam_lerp = max(0.02, min(1.0, self._cam_lerp))
        self._cam_blend_duration_sec = None
        self._cam_blend_t0_ms = None
        self._cam_blend_start = None
        self._view_lock_blend_from = None
        self._view_lock_blend_to = None
        self._zoom_frame_i = 0

    def _cam_blend_u(self):
        if (
            self._cam_blend_duration_sec is not None
            and float(self._cam_blend_duration_sec) > 0.0
            and self._cam_blend_t0_ms is not None
            and self._cam_blend_start is not None
        ):
            elapsed = max(0.0, (int(pygame.time.get_ticks()) - int(self._cam_blend_t0_ms)) / 1000.0)
            return min(1.0, elapsed / float(self._cam_blend_duration_sec))
        return None

    def _cam_blend_active(self):
        u = self._cam_blend_u()
        return u is not None and u < 1.0

    def _begin_cam_timed_blend(self, duration_sec):
        d = self._norm_cam_duration(duration_sec)
        self._cam_blend_duration_sec = d
        if d is not None:
            self._cam_blend_t0_ms = int(pygame.time.get_ticks())
            self._cam_blend_start = [float(self.pos[0]), float(self.pos[1])]
        else:
            self._cam_blend_t0_ms = None
            self._cam_blend_start = None

    def set_follow_player(self, smooth=True, lerp=None, duration_sec=None):
        self._cam_mode = "follow_player"
        self._follow_entity_name = ""
        if lerp is not None:
            try:
                self._cam_lerp = max(0.02, min(1.0, float(lerp)))
            except (TypeError, ValueError):
                pass
        self._cam_smooth = bool(smooth)
        self._begin_cam_timed_blend(duration_sec)

    def set_follow_entity(self, name, smooth=True, lerp=None, duration_sec=None):
        self._cam_mode = "follow_entity"
        self._follow_entity_name = str(name or "").strip()
        if lerp is not None:
            try:
                self._cam_lerp = max(0.02, min(1.0, float(lerp)))
            except (TypeError, ValueError):
                pass
        self._cam_smooth = bool(smooth)
        self._begin_cam_timed_blend(duration_sec)

    def set_fixed_world(self, wx, wy, smooth=False, lerp=None, duration_sec=None):
        self._cam_mode = "fixed_world"
        try:
            self._fixed_world = [float(wx), float(wy)]
        except (TypeError, ValueError):
            self._fixed_world = [0.0, 0.0]
        if lerp is not None:
            try:
                self._cam_lerp = max(0.02, min(1.0, float(lerp)))
            except (TypeError, ValueError):
                pass
        self._cam_smooth = bool(smooth)
        self._begin_cam_timed_blend(duration_sec)

    @staticmethod
    def _norm_cam_duration(duration_sec):
        if duration_sec is None or str(duration_sec).strip() == "":
            return None
        try:
            d = float(duration_sec)
        except (TypeError, ValueError):
            return None
        return None if d <= 0.0 else max(0.01, min(30.0, d))

    def _resolve_follow_center(self, player, npcs, objs):
        if self._cam_mode == "fixed_world":
            return float(self._fixed_world[0]), float(self._fixed_world[1])
        if self._cam_mode == "follow_entity":
            nm = (self._follow_entity_name or "").strip()
            if nm:
                try:
                    from field_runtime import find_entity_by_name

                    ent = find_entity_by_name(nm, player, npcs, objs)
                    if ent is not None:
                        return float(ent.pos[0]), float(ent.pos[1])
                except Exception:
                    pass
                if nm.lower() != "player":
                    try:
                        print(f"[CAMERA] follow_entity: '{nm}' not found, fallback to player")
                    except Exception:
                        pass
        return float(player.pos[0]), float(player.pos[1])

    def get_focus_world_point(self, player, npcs=None, objs=None):
        """카메라가 맞추는 월드 앵커(추적 대상 / lock_here 고정점)."""
        if self._cam_mode == "fixed_world":
            try:
                wx = float(getattr(self, "_view_lock_world_x", self._fixed_world[0]))
                wy = float(getattr(self, "_view_lock_world_y", self._fixed_world[1]))
            except Exception:
                wx, wy = float(self._fixed_world[0]), float(self._fixed_world[1])
            return wx, wy
        return self._resolve_follow_center(player, npcs, objs)

    def update(self, player, npcs, objs, map_w, map_h, shear_screen_px=0.0, dt_sec=1.0 / 60.0):
        # 새 월드 줌 시스템(main.py)로 전환:
        # - 카메라 줌/양자화/스냅은 사용하지 않는다.
        # - 카메라는 "월드 좌표계에서 무엇을 볼지"만 담당하고, 화면 확대/축소는 후처리로 한 장을 스케일한다.
        self.current_zoom = 1.0
        self.target_zoom = 1.0

        view_w = float(self.width) / float(self.current_zoom)
        view_h = float(self.height) / float(self.current_zoom)

        # 쉬어(스케일 맵 좌측 빈 띠)가 보이지 않게: 카메라 중심 X 허용 구간만 살짝 줄임. 플레이어 추적·중앙은 그대로.
        shear_px = max(0.0, float(shear_screen_px))
        try:
            shear_clamp_on = bool(CONFIG.get("SHEAR_CAMERA_CLAMP_ENABLED", True))
        except Exception:
            shear_clamp_on = True
        try:
            shear_clamp_eps = float(CONFIG.get("SHEAR_CAMERA_CLAMP_EPS", 0.25))
        except Exception:
            shear_clamp_eps = 0.25
        margin_x_world = 0.0
        if shear_clamp_on and shear_px > float(shear_clamp_eps):
            try:
                mf = float(CONFIG.get("SHEAR_CAMERA_MARGIN_FRAC", 1.0))
            except Exception:
                mf = 1.0
            mf = max(0.0, min(2.0, mf))
            zx = max(1e-6, float(self.current_zoom))
            margin_x_world = mf * shear_px / zx

        # 2. 추적 목표 (플레이어 / NPC·오브젝트 이름 / 고정 월드 좌표)
        tx, ty = self._resolve_follow_center(player, npcs, objs)
        if self._cam_mode != "fixed_world":
            # 해상도(논리)/업스케일 전환 시에도 "물리 화면에서 플레이어 위치 느낌"을 유지하려면
            # main.py가 설정하는 EFFECTIVE 값을 우선 사용한다.
            eff = CONFIG.get("CAMERA_FOLLOW_OFFSET_Y_PX_EFFECTIVE", None)
            if eff is not None:
                try:
                    off_y_px = float(eff)
                except Exception:
                    off_y_px = float(CONFIG.get("CAMERA_FOLLOW_OFFSET_Y_PX", 0) or 0)
            else:
                off_y_px = float(CONFIG.get("CAMERA_FOLLOW_OFFSET_Y_PX", 0) or 0)
            off_y_world = off_y_px / max(1e-6, float(self.current_zoom))
            ty = float(ty) - off_y_world

        # 3. 맵 안으로 목표 중심을 먼저 가두고 lerp (lerp 후 클램프는 위로 스크롤 시 미세 끊김 유발 가능)
        mw, mh = float(map_w), float(map_h)
        if mw > view_w:
            min_cx0 = view_w / 2.0
            max_cx0 = mw - view_w / 2.0
            min_cx = min(min_cx0 + margin_x_world, max_cx0)
            tx = max(min_cx, min(max_cx0, float(tx)))
        else:
            tx = mw / 2.0

        if mh > view_h:
            min_cy = view_h / 2.0
            max_cy = mh - view_h / 2.0
            ty = max(min_cy, min(max_cy, float(ty)))
        else:
            # 줌 아웃 등으로 화면이 맵보다 커져 검은 여백이 생길 때,
            # 하단 여백이 생기지 않도록 '맵 바닥이 화면 바닥에 붙게' 중심을 맞춘다.
            # (top 쪽 여백은 허용)
            ty = mh - view_h / 2.0

        u = self._cam_blend_u()
        if u is not None:
            sx, sy = float(self._cam_blend_start[0]), float(self._cam_blend_start[1])
            self.pos[0] = sx + (float(tx) - sx) * u
            self.pos[1] = sy + (float(ty) - sy) * u
            vf = getattr(self, "_view_lock_blend_from", None)
            vt = getattr(self, "_view_lock_blend_to", None)
            if self._cam_mode == "fixed_world" and vf is not None and vt is not None:
                fx, fy = float(vf[0]), float(vf[1])
                tx_lock, ty_lock = float(vt[0]), float(vt[1])
                try:
                    self._view_lock_world_x = fx + (tx_lock - fx) * u
                    self._view_lock_world_y = fy + (ty_lock - fy) * u
                except Exception:
                    pass
            if u >= 1.0:
                self._cam_blend_t0_ms = None
                self._cam_blend_start = None
                self._cam_blend_duration_sec = None
                if self._cam_mode == "fixed_world":
                    try:
                        self._view_lock_world_x = float(self._fixed_world[0])
                        self._view_lock_world_y = float(self._fixed_world[1])
                    except Exception:
                        pass
                    self._view_lock_blend_from = None
                    self._view_lock_blend_to = None
        else:
            ler = float(self._cam_lerp)
            if not self._cam_smooth:
                ler = 1.0
            self.pos[0] += (float(tx) - float(self.pos[0])) * ler
            self.pos[1] += (float(ty) - float(self.pos[1])) * ler

        # 수치 드리프트·초기 스냅 오차 방지
        if mw > view_w:
            min_cx0 = view_w / 2.0
            max_cx0 = mw - view_w / 2.0
            min_cx = min(min_cx0 + margin_x_world, max_cx0)
            self.pos[0] = max(min_cx, min(max_cx0, float(self.pos[0])))
        else:
            self.pos[0] = mw / 2.0

        if mh > view_h:
            self.pos[1] = max(view_h / 2.0, min(mh - view_h / 2.0, float(self.pos[1])))
        else:
            self.pos[1] = mh - view_h / 2.0

    def get_fast_image(self, original_img, zoom_level):
        """줌이 움직일 때 사용하는 초고속 스케일링 (캐싱 안 함)"""
        w, h = original_img.get_size()
        new_w, new_h = int(w * zoom_level), int(h * zoom_level)
        # transform.scale은 빠르고, smoothscale은 느립니다. 줌 도중엔 빠른 걸 씁니다.
        return pygame.transform.scale(original_img, (max(1, new_w), max(1, new_h)))

    def get_scaled_image(self, name, original_img):
        """전체 맵 스케일(배경/마스크). 캐시는 main.py 통합 _render_cache에서만 관리(B안)."""
        return self.get_fast_image(original_img, self.current_zoom)

    def to_screen(self, world_x, world_y):
        """월드 좌표를 화면 줌 좌표로 변환 (소수점 유지)"""
        zx = (world_x - self.pos[0]) * self.current_zoom + self.width / 2
        zy = (world_y - self.pos[1]) * self.current_zoom + self.height / 2
        # 여기서 int()를 씌우지 않고 그대로 반환합니다.
        return zx, zy

    def to_world(self, screen_x, screen_y):
        """화면 클릭 좌표를 실제 월드 좌표로 역산"""
        wx = (screen_x - self.width / 2) / self.current_zoom + self.pos[0]
        wy = (screen_y - self.height / 2) / self.current_zoom + self.pos[1]
        return wx, wy
    
    # [추가] 카메라를 즉시 특정 위치로 보냅니다.
    def snap_to(self, target_pos):
        self.pos[0] = target_pos[0]
        self.pos[1] = target_pos[1]


import pygame
import math

# --- 화면 고정 UI 오버레이 (OVERLAY_UI 스텝): 논리 해상도 기준 ---
_UI_FONT_CACHE = {}  # (font_key, size) -> pygame.font.Font


def _resolve_ui_font(font_key, size_px: int):
    try:
        sz = max(6, min(256, int(size_px)))
    except Exception:
        sz = 16
    fk = (font_key or "default") or "default"
    k = (fk, sz)
    hit = _UI_FONT_CACHE.get(k)
    if hit is not None:
        return hit
    path = None
    try:
        reg = UI_FONT_FILES or {}
        path = reg.get(fk)
        if path is None or str(path).strip() == "":
            path = reg.get("default")
    except Exception:
        path = None
    font = None
    if path and isinstance(path, str) and path.strip():
        full = path.strip()
        if not os.path.isabs(full) and not full.replace("\\", "/").startswith("assets/"):
            full = os.path.join("assets", full.replace("\\", "/"))
        if os.path.isfile(full):
            try:
                font = pygame.font.Font(full, sz)
            except Exception:
                font = None
    if font is None:
        try:
            font = pygame.font.Font(None, sz)
        except Exception:
            font = pygame.font.SysFont("arial", sz)
    _UI_FONT_CACHE[k] = font
    if len(_UI_FONT_CACHE) > 128:
        _UI_FONT_CACHE.clear()
        _UI_FONT_CACHE[k] = font
    return font


def _parse_overlay_rgb(step):
    c = step.get("color")
    if isinstance(c, (list, tuple)) and len(c) >= 3:
        try:
            return (int(c[0]), int(c[1]), int(c[2]))
        except Exception:
            pass
    s = step.get("color")
    if isinstance(s, str) and "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) >= 3:
            try:
                return (int(parts[0]), int(parts[1]), int(parts[2]))
            except Exception:
                pass
    return (255, 255, 255)


def _overlay_anchor_xy(anchor: str, w: int, h: int, mx: int, my: int, sw: int, sh: int):
    a = (anchor or "center").strip().lower()
    if a in ("tl", "top_left", "left_top"):
        return (mx, my)
    if a in ("tr", "top_right", "right_top"):
        return (sw - w - mx, my)
    if a in ("bl", "bottom_left", "left_bottom"):
        return (mx, sh - h - my)
    if a in ("br", "bottom_right", "right_bottom"):
        return (sw - w - mx, sh - h - my)
    # center
    return ((sw - w) // 2 + mx, (sh - h) // 2 + my)


def _scroll_enter_delta(enter: str, w: int, h: int, sw: int, sh: int):
    e = (enter or "left").strip().lower()
    bx = max(sw + w + 8, sw)
    by = max(sh + h + 8, sh)
    if e in ("left", "l", "west"):
        return (-bx, 0)
    if e in ("right", "r", "east"):
        return (bx, 0)
    if e in ("up", "top", "north"):
        return (0, -by)
    if e in ("down", "bottom", "south"):
        return (0, by)
    return (-bx, 0)


def _scroll_exit_delta(enter: str, w: int, h: int, sw: int, sh: int):
    sx, sy = _scroll_enter_delta(enter, w, h, sw, sh)
    return (-sx, -sy)


def _load_obj_surface_ui(obj_name: str):
    info = OBJ_ASSETS.get(obj_name) or {}
    p = info.get("path")
    if not p:
        return None
    mx = int(CONFIG.get("OBJ_ANIM_MAX_FRAMES", 64) or 64)
    frames = _load_obj_asset_frames(p, max_frames=mx)
    if frames:
        return frames[0].copy()
    return None


def _build_overlay_surface_from_step(step: dict):
    ct = (step.get("content") or step.get("content_type") or "text").strip().lower()
    if ct == "image":
        name = (step.get("object") or step.get("obj") or "").strip()
        if not name:
            return None
        return _load_obj_surface_ui(name)
    font_key = (step.get("font") or "default").strip() or "default"
    try:
        fs = int(float(step.get("size") or step.get("font_size") or 16))
    except Exception:
        fs = 16
    col = _parse_overlay_rgb(step)
    font = _resolve_ui_font(font_key, fs)
    raw = step.get("text") or ""
    lines = str(raw).replace("\r\n", "\n").split("\n") if raw else [""]
    surfaces = []
    max_w = 4
    total_h = 0
    line_gap = 2
    for ln in lines:
        try:
            surf = font.render(ln, True, col)
        except Exception:
            surf = font.render("", True, col)
        surfaces.append(surf)
        max_w = max(max_w, surf.get_width())
        total_h += surf.get_height() + line_gap
    total_h -= line_gap
    if total_h < 1:
        total_h = 1
    out = pygame.Surface((max_w, total_h), pygame.SRCALPHA)
    y = 0
    for i, surf in enumerate(surfaces):
        out.blit(surf, (0, y))
        y += surf.get_height()
        if i + 1 < len(surfaces):
            y += line_gap
    return out


def _wrap_text_by_pixels(text: str, font: pygame.font.Font, max_w: int):
    """CJK 포함: 문자 단위 줄바꿈(예측 가능 우선)."""
    if text is None:
        text = ""
    s = str(text).replace("\r\n", "\n")
    chunks = s.split("\n")
    lines = []
    for chunk in chunks:
        cur = ""
        for ch in chunk:
            nxt = cur + ch
            try:
                w, _h = font.size(nxt)
            except Exception:
                w = 10**9
            if cur and w > int(max_w):
                lines.append(cur)
                cur = ch
            else:
                cur = nxt
        lines.append(cur)
    return lines or [""]


def _scale_px_from_320(px_320: float, *, screen_w: int):
    """텍스트박스·폰트 등 320 설계 UI 좌표 → 현재 논리 해상도."""
    try:
        from field_runtime import scale_ui_text_px

        return scale_ui_text_px(px_320, screen_w=screen_w)
    except Exception:
        try:
            sc = float(screen_w) / 320.0
        except Exception:
            sc = 1.0
        return float(px_320) * sc


def _blit_text_with_outline(
    dst: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    x: int,
    y: int,
    *,
    color,
    outline_color,
    outline_px: int,
    alpha: int = 255,
):
    """텍스트 테두리(스트로크) 렌더: outline_color로 주변을 찍고 color를 마지막에 찍는다."""
    try:
        outline_px = int(outline_px)
    except Exception:
        outline_px = 0
    outline_px = max(0, min(6, outline_px))
    try:
        s_main = font.render(str(text or ""), True, color)
    except Exception:
        s_main = None
    if s_main is None:
        return 0, 0
    try:
        a = int(alpha)
    except Exception:
        a = 255
    a = max(0, min(255, a))

    if outline_px <= 0:
        if a < 255:
            sm = s_main.copy()
            sm.set_alpha(a)
            dst.blit(sm, (int(x), int(y)))
        else:
            dst.blit(s_main, (int(x), int(y)))
        return int(s_main.get_width()), int(s_main.get_height())

    try:
        s_ol = font.render(str(text or ""), True, outline_color)
    except Exception:
        s_ol = None
    if s_ol is not None:
        pad = int(outline_px) + 3
        sw = int(s_main.get_width()) + 2 * pad
        sh = int(s_main.get_height()) + 2 * pad
        tmp = pygame.Surface((max(1, sw), max(1, sh)), pygame.SRCALPHA)
        cx, cy = int(pad), int(pad)
        offs = [(-outline_px, 0), (outline_px, 0), (0, -outline_px), (0, outline_px),
                (-outline_px, -outline_px), (-outline_px, outline_px), (outline_px, -outline_px), (outline_px, outline_px)]
        for dx, dy in offs:
            tmp.blit(s_ol, (cx + dx, cy + dy))
        if outline_px >= 2:
            d2 = int(outline_px)
            offs2 = [(-d2, 0), (d2, 0), (0, -d2), (0, d2)]
            for dx, dy in offs2:
                tmp.blit(s_ol, (cx + dx, cy + dy))
        tmp.blit(s_main, (cx, cy))
        if a < 255:
            tmp.set_alpha(a)
        dst.blit(tmp, (int(x) - pad, int(y) - pad))
        return int(s_main.get_width()), int(s_main.get_height())

    if a < 255:
        sm = s_main.copy()
        sm.set_alpha(a)
        dst.blit(sm, (int(x), int(y)))
    else:
        dst.blit(s_main, (int(x), int(y)))
    return int(s_main.get_width()), int(s_main.get_height())


def _sanitize_ui_emotion_token(s) -> str:
    x = str(s or "").strip()
    return "".join(c for c in x if c.isalnum() or c == "_")[:64]


def _load_numbered_ui_sequence(rel_stem: str, *, max_frames: int = 64):
    """rel_stem 예: 'images/ui/speechbubble' → assets/.../speechbubble_0.png …"""
    mf = max(1, min(128, int(max_frames or 64)))
    stem = str(rel_stem or "").strip().replace("\\", "/")
    if stem.startswith("assets/"):
        base = os.path.normpath(stem)
    else:
        base = os.path.normpath(os.path.join("assets", stem.replace("/", os.sep)))
    frames = []
    for i in range(mf):
        p = os.path.normpath(f"{base}_{i}.png")
        surf = _load_image_cached(p)
        if surf is None:
            break
        frames.append(surf)
    return frames


def _head_top_center_screen(ent, head_ctx):
    """캐릭터 draw와 동일한 발→화면 변환 후 스프라이트 상단 중앙 (cx, top_y) 논리 좌표."""
    if ent is None or not head_ctx:
        return None
    try:
        cam_x = float(head_ctx["cam_draw_x"])
        cam_y = float(head_ctx["cam_draw_y"])
        z = float(head_ctx["z"])
    except Exception:
        return None
    y_transform = head_ctx.get("y_transform")
    x_offset_fn = head_ctx.get("x_offset_fn")
    try:
        fq = float(head_ctx.get("f_q") or 1.0)
    except Exception:
        fq = 1.0
    try:
        wx, wy = float(ent.pos[0]), float(ent.pos[1])
    except Exception:
        return None
    feet_y = float((wy - cam_y) * z)
    if callable(y_transform):
        try:
            feet_y = float(y_transform(feet_y))
        except Exception:
            pass
    feet_y_q = float(int(round(float(feet_y))))
    feet_x = float((wx - cam_x) * z)
    if callable(x_offset_fn):
        try:
            feet_x = float(feet_x) + float(x_offset_fn(float(feet_y_q)))
        except Exception:
            pass
    h_off = float(getattr(ent, "height", 0) or 0)
    if h_off > 0.0:
        feet_y = float(feet_y_q) - h_off * z
    else:
        feet_y = float(feet_y_q)
    fpx, fpy = int(round(float(feet_x))), int(round(float(feet_y)))
    try:
        ez = float(getattr(ent, "event_entity_zoom", 1.0) or 1.0)
    except Exception:
        ez = 1.0
    eff = float(z) * max(0.05, min(8.0, ez))
    img = getattr(ent, "image", None)
    if img is None:
        return None
    try:
        st = float(getattr(ent, "sprite_tilt", 1.0) or 1.0)
    except Exception:
        st = 1.0
    render_img = get_cached_scaled_sprite(img, eff, sprite_perspective_q=fq, sprite_tilt=st)
    iw, ih = render_img.get_width(), render_img.get_height()
    dx, dy = blit_topleft_bottom_center(fpx, fpy, iw, ih)
    return float(dx + iw * 0.5), float(dy)


def _normalize_move_step_waypoints(step):
    """
    MOVE step의 pos를 [[x,y], ...]로 통일.
    - [x, y] : 한 점
    - [[x1,y1],[x2,y2], ...] : 웨이포인트(순서대로 방문)
    - pos 생략 + dir(left/right): 이동 없이 방향만 (_event_move_start_on_target)

    다점(웨이포인트) MOVE에서 wait:false 이면 스크립트는 다음 스텝으로 진행되며,
    다른 대상의 MOVE와 병렬로 움직일 수 있다. 같은 대상에 연속 MOVE가 오면
    웨이포인트는 event_waypoints 끝에 이어 붙여 덮어쓰지 않는다.
    연속된 MOVE에 같은 문자열 move_sync(또는 sync)가 있으면 parallel 배열 없이
    전원이 목표에 도착할 때까지 묶어서 진행한다(에디터에서 move_sync 필드로 지정).

    병렬 이동(선택): "parallel": [ { "target", "pos", ... }, ... ] — 한 스텝에
    여러 대상; wait 는 그룹 전체 완료 기준.
    """
    pos = step.get("pos")
    if pos is None:
        return []
    if isinstance(pos, (list, tuple)) and len(pos) == 2:
        if not isinstance(pos[0], (list, tuple)):
            try:
                return [[float(pos[0]), float(pos[1])]]
            except (TypeError, ValueError):
                return []
    out = []
    if isinstance(pos, (list, tuple)):
        for p in pos:
            if isinstance(p, (list, tuple)) and len(p) >= 2 and not isinstance(p[0], (list, tuple)):
                try:
                    out.append([float(p[0]), float(p[1])])
                except (TypeError, ValueError):
                    continue
    return out


def _event_apply_step_dir(target, step) -> bool:
    """MOVE/PLACE 등: dir(face)만 지정 시 좌표 없이 방향만 바꿀 때 True."""
    d = (step.get("dir") or step.get("face") or "").strip().lower()
    if d in ("left", "l"):
        target.direction = "left"
        return True
    if d in ("right", "r"):
        target.direction = "right"
        return True
    return False


def _step_bool_true(val):
    if val is True:
        return True
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "t", "yes", "y", "on")
    return False


def _step_transition_instant(step):
    return _step_bool_true(step.get("instant"))


def _step_lerp_speed_optional(step):
    """이벤트 스텝 speed (0~1). 없으면 None → CONFIG 기본값 사용."""
    raw = step.get("speed")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return None


def _step_world_zoom_speed_optional(step):
    """카메라(월드) ZOOM speed (zoom/sec). 없으면 None."""
    raw = step.get("speed")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return max(0.05, min(20.0, float(raw)))
    except (TypeError, ValueError):
        return None


class EventManager:
    def __init__(self, flow_ref, music_mgr=None):
        self.flow = flow_ref
        self.music = music_mgr  # MusicManager or None
        self.active_event = None
        self.step_idx = 0
        self.is_talking = False
        self.is_busy = False    
        self.wait_timer = 0
        self.current_who = ""
        self.current_text = ""        
        # SAY(typewriter) runtime
        self._say_full_text = ""
        self._say_visible_n = 0
        self._say_last_char_ms = 0
        self._say_done = True
        self._say_can_close_at_ms = 0
        self._say_show_name = None
        self._say_ignore_input_until_ms = 0
        # SAY 텍스트박스 UI 페이드 (in → visible → out)
        self._say_ui_fade_phase = None  # None | "in" | "visible" | "out"
        self._say_ui_fade_t0_ms = 0
        self._say_bubble = None  # dict: target_name, frames, frame_idx, acc_ms, frame_ms
        self._emote_overlay = None  # dict: see _execute_step EMOTE
        self.fade_alpha = 0      # 현재 검은 투명도
        self.fade_target = 0     # 목표 투명도 (0 or 255)
        self.fade_t0_ms = 0      # 페이드 시작 시각(레거시)
        self.fade_duration_ms = 0  # 0이면 시간 기반 페이드 비활성
        self.fade_duration_sec = 0.0
        self.fade_elapsed_sec = 0.0
        self.fade_start_alpha = 0.0  # fade_t0_ms 시점의 알파
        self.is_fading = False   # 현재 페이드 연출 중인가?
        self._say_ui_fade_elapsed = 0.0
        self._pending_fade_in_after_fadeout_sec = None  # 페이드아웃 완료 직후 페이드인(초)
        self.active_effects = [] # 현재 화면에 떠 있는 이펙트들
        self._effect_wait_ref = None  # EFFECT wait:true — 재생 끝날 때까지 next_step 보류
        self._carry_wait_item = None  # CARRY wait — fly 중인 FieldItem (완료 시 next_step)
        self.active_event_result = None  # events.json의 result (종료 시 적용)
        # SCREEN overlay (인트로/슬라이드 같은 화면 덮개)
        self.active_screen = None  # dict or None
        # UI 오버레이 (로고/텍스트, 논리 해상도 좌표)
        self._ui_overlays = []  # list of dict, see _apply_overlay_ui_step
        self.pending_map_change = None # {"map_id": ..., "pos": ...}
        self.cursor_visible = True # 커서 가시성 제어 추가
        self._cursor_visible_persist = False  # True면 이벤트 종료 후에도 cursor_visible 유지
        self.last_ended_event_id = None  # 직전에 끝난 이벤트 ID (온보딩 후 스폰 등)
        self._loop_end_to_head = {}
        self._loop_pairs = []
        self._escape_mode = "none"
        self._escape_action = "end"  # end | break_loop | lock
        self._escape_key_pygame = None
        self._escape_condition = ""
        self._restore_speed_after_move = {}  # (id(target), step_idx) -> old_mul
        self._end_zoom = None
        self._last_camera = None
        self._followers = []  # [{"follower":"c1","leader":"player","dist":40,"speed":0.8}]
        # 연속 MOVE + 같은 move_sync 문자열: parallel JSON 없이 전원 도착까지 한 번에 진행
        self._move_sync_group = None  # {"base_idx", "count", "sync", "entries": [{step_i, target_name, wps}, ...]}
        self._event_mask_img = None  # 마지막으로 받은 맵 마스크 (FOLLOW 도랑 점프용, None으로 덮어쓰지 않음)
        self._anim_wait_end_ms = 0
        # 필드 연출: 이벤트 스텝 TILT/SHEAR가 main의 tilt/shear를 덮어쓸 때 사용
        self.tilt_control = None  # dict: target, instant_once?, speed?(0~1)
        self.shear_control = None  # dict: enabled, max_px?, strength_mul, bypass_strength, instant_once?, speed?
        self.world_zoom_step_speed = None  # 디버그 핫키 등 구형 zoom/sec
        self.world_zoom_timed = None  # 시계 기반 월드 줌 보간 {start,target,t0_ms,duration_sec}
        self.field_tilt_snapshot = None  # (tilt_bg_demo, tilt_target, tilt_current, shear_debug) 이벤트 시작 시점
        self.pending_field_tilt_restore = None  # end_event 후 main이 한 번 소비
        # FX: 구름 그림자 오버레이 (main.py에서 실제 렌더)
        self.cloud_shadow_control = None  # dict: enabled, dir, speed, freq
        self.pending_camera_command = None  # dict → main이 cam에 적용 후 소비
        # 이벤트 중 CAMERA 스텝(save_camera)으로 저장한 월드 중심 좌표 (슬롯명 → [x,y])
        self._camera_saved_slots = {}
        self._free_say_on_finish = None
        # FRAGMENTS / CALL_EVENT: 부모 이벤트 복귀 스택
        self._fragment_catalog = {}
        self._event_call_stack = []
        self._fragment_call_depth = 0
        self._fragment_call_set = set()
        self.MAX_FRAGMENT_DEPTH = 8
        # SYNC: 맵 로드 후 순차 실행 대기열 (main.py가 채움)
        self.pending_sync_queue = []
        self._is_sync_event = False

    def set_fragment_catalog(self, catalog: dict):
        """CALL_EVENT target 카탈로그 (LOCAL/GLOBAL/SYNC/FRAGMENTS)."""
        self._fragment_catalog = dict(catalog or {})

    def emote_needs_advance_input(self) -> bool:
        em = getattr(self, "_emote_overlay", None)
        return bool(em and em.get("awaiting_click"))

    def start_event(self, event_list, event_id=None, result=None, event_entry=None, is_sync=False):
        self.last_ended_event_id = None
        self._is_sync_event = bool(is_sync)
        self._event_call_stack = []
        self._fragment_call_depth = 0
        self._fragment_call_set = set()
        self.active_event = event_list
        self.active_event_id = event_id  # 이벤트 ID 저장 (예: 'EV001')
        self.active_event_result = result
        self.step_idx = 0
        self.is_busy = False
        self.is_talking = False
        self._say_ui_fade_phase = None
        self._followers = []
        self._move_sync_group = None
        self._cursor_visible_persist = False
        self._loop_end_to_head, self._loop_pairs = _parse_loop_jump_table(event_list)
        self._event_skip_depth = 0
        # (정책 변경) 이벤트 옵션(escape)로 중도 스탑/탈출을 설정하지 않는다.
        # 대신 스텝(EVT_STOP_BEGIN/EVT_STOP_END)으로 "언제부터/언제까지" 스탑 입력을 받을지 제어한다.
        self._escape_mode = "none"
        self._escape_action = "end"
        self._escape_key_pygame = None
        self._escape_condition = ""
        ez = (event_entry or {}).get("end_zoom") if event_entry else None
        if ez is None or ez == "":
            self._end_zoom = None
        else:
            try:
                self._end_zoom = float(ez)
            except Exception:
                self._end_zoom = None
        # 이벤트 시작 시 screen은 유지할 수도 있지만, 기본은 유지(스크립트로 remove 가능)
        print(f"[이벤트 시작] ID: {event_id}")
        self.tilt_control = None
        self.shear_control = None
        self.world_zoom_step_speed = None
        self.world_zoom_timed = None
        # FX는 이벤트 밖에서도 유지될 수 있으니 기본은 유지. (OFF는 FX 스텝에서 명시)
        self.field_tilt_snapshot = None
        self.pending_field_tilt_restore = None
        self._camera_saved_slots = {}
        self._say_bubble = None
        self._emote_overlay = None

    def _restore_all_move_speed_overrides(self):
        if not self._restore_speed_after_move:
            return
        # id(entity) -> old_mul (마지막 기록 우선)
        restore_map = {}
        for (ent_id, _st), old_mul in list(self._restore_speed_after_move.items()):
            restore_map[ent_id] = old_mul
        self._restore_speed_after_move.clear()

        # 현재 맵에 있는 엔티티들만 복구 (존재하지 않으면 무시)
        if not getattr(self, "_active_entities", None):
            return
        for ent in self._active_entities:
            try:
                if id(ent) in restore_map:
                    ent.event_speed_mul = restore_map[id(ent)]
            except Exception:
                pass

    def _escape_jump_index(self):
        """break_loop 점프 대상(step_idx).
        - 현재 step_idx가 루프 안이면: 가장 안쪽(짧은 span) 루프의 (end+1)
        - 루프 밖(루프 전 포함)이면: 첫 번째 LOOP_END의 (end+1)
        """
        cur = int(self.step_idx or 0)
        best = None  # (span, end)
        for head, end in self._loop_pairs or []:
            if head <= cur <= end:
                span = end - head
                if best is None or span < best[0]:
                    best = (span, end)
        if best is not None:
            return int(best[1]) + 1
        # 루프 밖이면: 첫 루프의 end+1로 점프 (루프 전 클릭도 동일 동작)
        if self._loop_pairs:
            try:
                return int(self._loop_pairs[0][1]) + 1
            except Exception:
                return None
        return None

    def _fade_duration_sec_from_step(self, step, default_sec=1.0):
        """FADEIN/FADEOUT step['val'] → 초. 비어 있거나 잘못된 값이면 default_sec."""
        raw = step.get("val", default_sec)
        if raw is None or (isinstance(raw, str) and not str(raw).strip()):
            raw = default_sec
        try:
            v = float(raw)
        except (TypeError, ValueError):
            v = float(default_sec)
        return max(0.0, v)

    def _begin_global_fade(self, target_alpha: int, duration_sec: float):
        try:
            tgt = int(max(0, min(255, int(target_alpha))))
        except (TypeError, ValueError):
            tgt = 0
        if tgt != 255:
            self._pending_fade_in_after_fadeout_sec = None
        try:
            ds = float(duration_sec)
        except (TypeError, ValueError):
            ds = 1.0
        ds = max(0.0, ds)
        self.fade_target = tgt
        if ds <= 0.0:
            self.fade_alpha = tgt
            self.fade_duration_ms = 0
            self.fade_duration_sec = 0.0
            self.fade_elapsed_sec = 0.0
            self.is_fading = False
            return
        self.fade_start_alpha = float(self.fade_alpha)
        self.fade_t0_ms = pygame.time.get_ticks()
        self.fade_duration_sec = float(ds)
        self.fade_elapsed_sec = 0.0
        self.fade_duration_ms = max(1, int(round(ds * 1000.0)))
        self.is_fading = True

    def start_global_fade_to(self, target_alpha: int, duration_sec: float):
        """전역 검은 오버레이를 duration_sec(초)에 맞춰 현재 fade_alpha에서 target까지 선형 페이드."""
        self._begin_global_fade(target_alpha, duration_sec)

    def schedule_fade_in_after_current_fadeout(self, duration_sec=0.5):
        """이벤트 페이드아웃(목표 255)이 진행 중일 때 끊지 않고, 완료 후 검→밝음 페이드만 예약."""
        try:
            self._pending_fade_in_after_fadeout_sec = max(0.05, float(duration_sec))
        except Exception:
            self._pending_fade_in_after_fadeout_sec = 0.5

    def _apply_overlay_ui_step(self, step):
        """OVERLAY_UI: 화면 고정 로고/텍스트 (논리 해상도).
        action remove: overlay_id로 제거. disappear(초)>0 이면 즉시 삭제 대신
        기존 show의 mode(fade/scroll)로 퇴장 연출 후 목록에서 빠짐."""
        act = (step.get("action") or "show").strip().lower()
        if act == "remove":
            rid = (step.get("overlay_id") or step.get("id") or "").strip()
            try:
                diss_raw = step.get("disappear")
                if diss_raw is None:
                    diss_raw = step.get("disappear_sec")
                if diss_raw is None or diss_raw == "":
                    diss = 0.0
                else:
                    diss = float(diss_raw)
            except Exception:
                diss = 0.0
            t_out_rem = max(0, int(diss * 1000))

            if not rid:
                self._ui_overlays = []
                return

            if t_out_rem <= 0:
                self._ui_overlays = [o for o in (self._ui_overlays or []) if o.get("id") != rid]
                return

            now_ms = pygame.time.get_ticks()
            matched = False
            for ov in list(self._ui_overlays or []):
                if ov.get("id") != rid:
                    continue
                matched = True
                ph_was = ov.get("phase")
                if ph_was == "in":
                    om = (ov.get("mode") or "fade").strip().lower()
                    if om == "scroll":
                        ov["draw_dx"] = 0.0
                        ov["draw_dy"] = 0.0
                        ov["draw_alpha"] = 255
                    else:
                        ov["draw_dx"] = 0.0
                        ov["draw_dy"] = 0.0
                        ov["draw_alpha"] = 255
                else:
                    om = (ov.get("mode") or "fade").strip().lower()
                    if om == "scroll":
                        ov["draw_dx"] = 0.0
                        ov["draw_dy"] = 0.0
                    try:
                        ov["draw_alpha"] = int(max(0, min(255, int(ov.get("draw_alpha", 255)))))
                    except Exception:
                        ov["draw_alpha"] = 255
                ov["phase"] = "out"
                ov["t_phase0_ms"] = now_ms
                ov["t_out_ms"] = t_out_rem
                ov["hold_forever"] = False
                break

            if not matched:
                self._ui_overlays = [o for o in (self._ui_overlays or []) if o.get("id") != rid]
            return
        surf = _build_overlay_surface_from_step(step)
        if surf is None:
            return
        sw = int(CONFIG.get("WIDTH", 320))
        sh = int(CONFIG.get("HEIGHT", 240))
        w, h = surf.get_size()
        anchor = step.get("anchor") or "center"
        try:
            mx = int(float(step.get("margin_x") or 0))
        except Exception:
            mx = 0
        try:
            my = int(float(step.get("margin_y") or 0))
        except Exception:
            my = 0
        rx, ry = _overlay_anchor_xy(anchor, w, h, mx, my, sw, sh)
        mode = (step.get("mode") or "fade").strip().lower()
        if mode not in ("fade", "scroll"):
            mode = "fade"
        scroll_enter = (step.get("scroll_enter") or step.get("from") or "left").strip().lower()
        try:
            appear = float(step.get("appear") if step.get("appear") is not None else step.get("appear_sec", 0.5))
        except Exception:
            appear = 0.5
        try:
            disappear = float(step.get("disappear") if step.get("disappear") is not None else step.get("disappear_sec", 0.5))
        except Exception:
            disappear = 0.5
        hold_forever = bool(step.get("hold_forever") or step.get("infinite_hold"))
        hold_raw = step.get("hold") if "hold" in step else step.get("hold_sec")
        if hold_forever:
            t_hold_ms = None
        else:
            try:
                hs = float(hold_raw if hold_raw is not None and hold_raw != "" else 2.0)
            except Exception:
                hs = 2.0
            t_hold_ms = max(0, int(hs * 1000))
        t_in_ms = max(0, int(appear * 1000))
        t_out_ms = max(0, int(disappear * 1000))

        oid = (step.get("overlay_id") or step.get("id") or "").strip()
        if not oid:
            oid = "ov_" + uuid.uuid4().hex[:10]
        persist = bool(step.get("persist", False))

        sx, sy = _scroll_enter_delta(scroll_enter, w, h, sw, sh)
        ex, ey = _scroll_exit_delta(scroll_enter, w, h, sw, sh)

        now = pygame.time.get_ticks()
        ov = {
            "id": oid,
            "surf": surf,
            "mode": mode,
            "rest_x": rx,
            "rest_y": ry,
            "w": w,
            "h": h,
            "sw": sw,
            "sh": sh,
            "scroll_enter": scroll_enter,
            "sx": sx,
            "sy": sy,
            "ex": ex,
            "ey": ey,
            "phase": "in",
            "t_phase0_ms": now,
            "t_in_ms": t_in_ms,
            "t_hold_ms": t_hold_ms,
            "t_out_ms": t_out_ms,
            "hold_forever": hold_forever,
            "persist": persist,
            "draw_alpha": 0,
            "draw_dx": 0.0,
            "draw_dy": 0.0,
        }
        if mode == "scroll":
            ov["draw_dx"] = float(sx)
            ov["draw_dy"] = float(sy)
            ov["draw_alpha"] = 255
        self._ui_overlays = [o for o in (self._ui_overlays or []) if o.get("id") != oid]
        self._ui_overlays.append(ov)

    def _tick_ui_overlays(self):
        now = pygame.time.get_ticks()
        alive = []
        for ov in list(self._ui_overlays or []):
            ph = ov.get("phase")
            if ph == "done":
                continue
            mode = (ov.get("mode") or "fade").strip().lower()
            t0 = int(ov.get("t_phase0_ms") or now)

            if ph == "in":
                dur = max(0, int(ov.get("t_in_ms") or 0))
                if dur <= 0:
                    p = 1.0
                else:
                    p = min(1.0, max(0.0, (now - t0) / float(dur)))
                if mode == "fade":
                    ov["draw_alpha"] = int(round(255 * p))
                    ov["draw_dx"] = 0.0
                    ov["draw_dy"] = 0.0
                else:
                    sx, sy = float(ov["sx"]), float(ov["sy"])
                    ov["draw_dx"] = sx * (1.0 - p)
                    ov["draw_dy"] = sy * (1.0 - p)
                    ov["draw_alpha"] = 255
                if p >= 1.0:
                    ov["phase"] = "hold"
                    ov["t_phase0_ms"] = now
                alive.append(ov)
                continue

            if ph == "hold":
                ov["draw_dx"] = 0.0
                ov["draw_dy"] = 0.0
                ov["draw_alpha"] = 255
                if ov.get("hold_forever"):
                    alive.append(ov)
                    continue
                hm = int(ov.get("t_hold_ms") or 0)
                if now - t0 >= hm:
                    ov["phase"] = "out"
                    ov["t_phase0_ms"] = now
                alive.append(ov)
                continue

            if ph == "out":
                dur = max(0, int(ov.get("t_out_ms") or 0))
                if dur <= 0:
                    continue
                p = min(1.0, max(0.0, (now - t0) / float(max(1, dur))))
                if mode == "fade":
                    ov["draw_alpha"] = int(round(255 * (1.0 - p)))
                    ov["draw_dx"] = 0.0
                    ov["draw_dy"] = 0.0
                else:
                    ex, ey = float(ov["ex"]), float(ov["ey"])
                    ov["draw_dx"] = ex * p
                    ov["draw_dy"] = ey * p
                    ov["draw_alpha"] = 255
                if p >= 1.0:
                    continue
                alive.append(ov)
                continue

        self._ui_overlays = alive

    def _resolve_head_entity(self, name, head_ctx):
        if not head_ctx:
            return None
        n = str(name or "").strip()
        if not n or n.lower() == "player":
            return head_ctx.get("player")
        for pool in (head_ctx.get("npcs") or [], head_ctx.get("objs") or []):
            for x in pool:
                try:
                    if getattr(x, "name", "") == n:
                        return x
                except Exception:
                    continue
        return None

    def _say_ui_fade_alpha_for_overlays(self):
        """SAY 텍스트박스와 동일 페이드 알파(대화 중이 아니면 255)."""
        if not bool(getattr(self, "is_talking", False)):
            return 255
        try:
            fade_en = bool(CONFIG.get("SAY_UI_FADE_ENABLED", True))
        except Exception:
            fade_en = True
        if not fade_en:
            return 255
        try:
            fin_sec = float(CONFIG.get("SAY_UI_FADE_IN_SEC", 0.5) or 0.5)
        except Exception:
            fin_sec = 0.5
        try:
            fout_sec = float(CONFIG.get("SAY_UI_FADE_OUT_SEC", 0.5) or 0.5)
        except Exception:
            fout_sec = 0.5
        ph = getattr(self, "_say_ui_fade_phase", None) or "visible"
        el = float(getattr(self, "_say_ui_fade_elapsed", 0.0) or 0.0)
        if ph == "in" and fin_sec > 0:
            u = el / float(fin_sec)
            return int(round(255 * max(0.0, min(1.0, u))))
        if ph == "out" and fout_sec > 0:
            u = el / float(fout_sec)
            return int(round(255 * max(0.0, min(1.0, 1.0 - u))))
        if ph == "out":
            return 0
        return 255

    def _configure_say_bubble_from_step(self, step):
        self._say_bubble = None
        b_raw = step.get("bubble", None)
        if b_raw is None:
            try:
                show_b = bool(CONFIG.get("SAY_BUBBLE_DEFAULT", False))
            except Exception:
                show_b = False
        else:
            if isinstance(b_raw, str):
                s = b_raw.strip().lower()
                if s in ("0", "false", "f", "no", "n", "off", "clear", ""):
                    show_b = False
                elif s in ("1", "true", "t", "yes", "y", "on"):
                    show_b = True
                else:
                    show_b = bool(s)
            else:
                show_b = bool(b_raw)
        if not show_b:
            return
        tgt = (step.get("bubble_target") or step.get("who") or "").strip()
        if not tgt:
            return
        try:
            prefix = str(CONFIG.get("SAY_BUBBLE_UI_PREFIX", "images/ui/speechbubble") or "images/ui/speechbubble").strip()
        except Exception:
            prefix = "images/ui/speechbubble"
        try:
            mx = int(CONFIG.get("SAY_BUBBLE_MAX_FRAMES", 32) or 32)
        except Exception:
            mx = 32
        frames = _load_numbered_ui_sequence(prefix, max_frames=mx)
        if not frames:
            return
        try:
            fm = int(CONFIG.get("SAY_BUBBLE_FRAME_MS", 140) or 140)
        except Exception:
            fm = 140
        fm = max(16, min(2000, fm))
        self._say_bubble = {
            "target_name": tgt,
            "frames": frames,
            "frame_idx": 0,
            "acc_ms": 0,
            "frame_ms": fm,
        }

    def _tick_say_bubble_frame(self):
        bb = getattr(self, "_say_bubble", None)
        if not bb or not bool(getattr(self, "is_talking", False)) or not bb.get("frames"):
            return
        try:
            now = int(pygame.time.get_ticks())
        except Exception:
            return
        last = int(bb.get("_last_ms", now) or now)
        bb["_last_ms"] = now
        dt = max(0, now - last)
        bb["acc_ms"] = int(bb.get("acc_ms", 0) or 0) + dt
        fm = max(16, int(bb.get("frame_ms", 140) or 140))
        n = len(bb["frames"])
        fi = int(bb.get("frame_idx", 0) or 0)
        while int(bb["acc_ms"]) >= fm and fi < n - 1:
            bb["acc_ms"] = int(bb["acc_ms"]) - fm
            fi += 1
        bb["frame_idx"] = max(0, min(n - 1, fi))

    def _tick_emote_overlay(self):
        em = getattr(self, "_emote_overlay", None)
        if not em or not em.get("frames") or em.get("_advanced_step"):
            return
        if (em.get("phase") or "play") == "static":
            return
        try:
            now = int(pygame.time.get_ticks())
        except Exception:
            return
        last = int(em.get("_last_ms", now) or now)
        em["_last_ms"] = now
        dt = max(0, now - last)
        frames = em["frames"]
        n = len(frames)
        if n <= 0:
            return
        fm = max(16, int(em.get("frame_ms", 120) or 120))
        phase = em.get("phase") or "play"
        if phase == "play":
            acc = int(em.get("acc_ms", 0) or 0) + dt
            fi = int(em.get("frame_idx", 0) or 0)
            while acc >= fm:
                if fi < n - 1:
                    fi += 1
                    acc -= fm
                else:
                    em["frame_idx"] = n - 1
                    em["acc_ms"] = 0
                    em["phase"] = "post"
                    em["post_acc"] = 0
                    return
            em["frame_idx"] = fi
            em["acc_ms"] = acc
            return
        if phase == "post":
            hr = max(0, int(em.get("hold_remaining_ms", 0) or 0))
            pa = int(em.get("post_acc", 0) or 0) + dt
            if pa < hr:
                em["post_acc"] = pa
                return
            em["post_acc"] = pa
            em["phase"] = "static"
            if (em.get("advance_mode") or "continue") == "continue":
                em["_advanced_step"] = True
                self.next_step()
            else:
                em["awaiting_click"] = True
            return

    def _draw_head_attached_ui(self, screen: pygame.Surface, head_ctx):
        if not head_ctx:
            return
        try:
            w = int(CONFIG.get("WIDTH", 320) or 320)
        except Exception:
            w = 320
        try:
            from field_runtime import scale_ui_px, ui_layout_scale

            layout_sc = float(ui_layout_scale(screen_w=w))
        except Exception:
            scale_ui_px = None
            layout_sc = 1.0
        try:
            wz = float(head_ctx.get("world_zoom_draw", 1.0) or 1.0)
        except Exception:
            wz = 1.0
        wz = max(0.1, min(8.0, float(wz)))
        try:
            wz_ox = float(head_ctx.get("world_zoom_off_x", 0.0) or 0.0)
            wz_oy = float(head_ctx.get("world_zoom_off_y", 0.0) or 0.0)
        except Exception:
            wz_ox, wz_oy = 0.0, 0.0
        # 말풍선·이모트: 논리 해상도 1:1 × 월드 줌(2배 줌이면 아이콘도 2배)
        sc = max(0.1, min(8.0, float(layout_sc) * float(wz)))
        # 틸트(f_q<1)는 y 간격이 압축된다. UI 오버레이 오프셋도 동일하게 압축해 "머리 위" 느낌을 유지.
        try:
            fq = float(head_ctx.get("f_q", 1.0) or 1.0)
        except Exception:
            fq = 1.0
        fq = max(0.05, min(1.0, float(fq)))

        def map_head_screen(sx, sy):
            return float(sx) * wz + wz_ox, float(sy) * wz + wz_oy

        def scaled_surf(surf):
            if surf is None:
                return None
            try:
                iw, ih = surf.get_size()
            except Exception:
                return None
            tw, th = int(max(1, round(iw * sc))), int(max(1, round(ih * sc)))
            if tw == iw and th == ih:
                return surf
            try:
                return pygame.transform.scale(surf, (tw, th))
            except Exception:
                return surf

        def blit_icon(surf, cx, top_y, ox_px, oy_px, alpha):
            img = scaled_surf(surf)
            if img is None:
                return
            rect = img.get_rect(midbottom=(int(round(cx)) + ox_px, int(round(top_y)) + oy_px))
            if alpha < 255:
                tmp = img.copy()
                tmp.set_alpha(max(0, min(255, int(alpha))))
                screen.blit(tmp, rect)
            else:
                screen.blit(img, rect)

        em = getattr(self, "_emote_overlay", None)
        if em and em.get("frames"):
            ent = self._resolve_head_entity(em.get("target"), head_ctx)
            anc = _head_top_center_screen(ent, head_ctx)
            if anc:
                cx, top_y = map_head_screen(*anc)
                try:
                    ox0 = float(CONFIG.get("EMOTE_OFFSET_X_PX_320", 0) or 0)
                    oy0 = float(CONFIG.get("EMOTE_OFFSET_Y_PX_320", -4) or -4)
                except Exception:
                    ox0, oy0 = 0.0, -4.0
                if scale_ui_px is not None:
                    ox = int(round(scale_ui_px(ox0, screen_w=w) * wz))
                    oy = int(round(scale_ui_px(oy0, screen_w=w) * fq * wz))
                else:
                    ox = int(round(ox0 * wz))
                    oy = int(round(oy0 * fq * wz))
                fi = int(em.get("frame_idx", 0) or 0)
                fi = max(0, min(len(em["frames"]) - 1, fi))
                blit_icon(em["frames"][fi], cx, top_y, ox, oy, 255)

        bb = getattr(self, "_say_bubble", None)
        if bb and bool(getattr(self, "is_talking", False)) and bb.get("frames"):
            ent = self._resolve_head_entity(bb.get("target_name"), head_ctx)
            anc = _head_top_center_screen(ent, head_ctx)
            if anc:
                cx, top_y = map_head_screen(*anc)
                try:
                    ox0 = float(CONFIG.get("SAY_BUBBLE_OFFSET_X_PX_320", 0) or 0)
                    oy0 = float(CONFIG.get("SAY_BUBBLE_OFFSET_Y_PX_320", -10) or -10)
                except Exception:
                    ox0, oy0 = 0.0, -10.0
                if scale_ui_px is not None:
                    ox = int(round(scale_ui_px(ox0, screen_w=w) * wz))
                    oy = int(round(scale_ui_px(oy0, screen_w=w) * fq * wz))
                else:
                    ox = int(round(ox0 * wz))
                    oy = int(round(oy0 * fq * wz))
                fi = int(bb.get("frame_idx", 0) or 0)
                fi = max(0, min(len(bb["frames"]) - 1, fi))
                al = self._say_ui_fade_alpha_for_overlays()
                blit_icon(bb["frames"][fi], cx, top_y, ox, oy, al)

    def draw_ui_overlays(self, screen: pygame.Surface, head_ctx=None):
        """논리 해상도 서피스(CONFIG WIDTH×HEIGHT) 좌표로 블릿."""
        try:
            self._draw_head_attached_ui(screen, head_ctx)
        except Exception:
            pass
        # SAY 텍스트박스 (events.json SAY)
        if bool(getattr(self, "is_talking", False)) and bool(CONFIG.get("SAY_USE_TEXTBOX_UI", True)):
            try:
                w = int(CONFIG.get("WIDTH", 320) or 320)
                h = int(CONFIG.get("HEIGHT", 240) or 240)
            except Exception:
                w, h = 320, 240

            say_alpha = 255
            try:
                fade_en = bool(CONFIG.get("SAY_UI_FADE_ENABLED", True))
            except Exception:
                fade_en = True
            if fade_en:
                try:
                    fin_sec = float(CONFIG.get("SAY_UI_FADE_IN_SEC", 0.5) or 0.5)
                except Exception:
                    fin_sec = 0.5
                try:
                    fout_sec = float(CONFIG.get("SAY_UI_FADE_OUT_SEC", 0.5) or 0.5)
                except Exception:
                    fout_sec = 0.5
                ph = getattr(self, "_say_ui_fade_phase", None) or "visible"
                el = float(getattr(self, "_say_ui_fade_elapsed", 0.0) or 0.0)
                if ph == "in" and fin_sec > 0:
                    u = el / float(fin_sec)
                    say_alpha = int(round(255 * max(0.0, min(1.0, u))))
                elif ph == "out" and fout_sec > 0:
                    u = el / float(fout_sec)
                    say_alpha = int(round(255 * max(0.0, min(1.0, 1.0 - u))))
                elif ph == "out":
                    say_alpha = 0

            # 1) textbox image (320x240 asset) → logical resolution
            try:
                key = str(CONFIG.get("SAY_TEXTBOX_ASSET", "textbox01") or "textbox01").strip()
            except Exception:
                key = "textbox01"
            try:
                tb = _load_obj_surface_ui(key) if key else None
                if tb is not None:
                    if tb.get_width() != w or tb.get_height() != h:
                        tb2 = pygame.transform.scale(tb, (w, h))
                    else:
                        tb2 = tb
                    if say_alpha < 255:
                        tb_draw = tb2.copy()
                        tb_draw.set_alpha(max(0, min(255, int(say_alpha))))
                        screen.blit(tb_draw, (0, 0))
                    else:
                        screen.blit(tb2, (0, 0))
            except Exception:
                # 로드 실패는 게임을 깨지 않게 무시
                pass

            # 2) text rect + fonts
            try:
                r0 = CONFIG.get("SAY_TEXTBOX_RECT_320", [18, 182, 284, 52]) or [18, 182, 284, 52]
                x0, y0, rw0, rh0 = float(r0[0]), float(r0[1]), float(r0[2]), float(r0[3])
            except Exception:
                x0, y0, rw0, rh0 = 18.0, 182.0, 284.0, 52.0
            x = int(round(_scale_px_from_320(x0, screen_w=w)))
            y = int(round(_scale_px_from_320(y0, screen_w=w)))
            rw = int(round(_scale_px_from_320(rw0, screen_w=w)))
            rh = int(round(_scale_px_from_320(rh0, screen_w=w)))

            try:
                fkey = str(CONFIG.get("SAY_FONT_KEY", "dialog") or "dialog").strip() or "dialog"
            except Exception:
                fkey = "dialog"
            try:
                fs0 = float(CONFIG.get("SAY_FONT_SIZE_320", 12) or 12)
            except Exception:
                fs0 = 12.0
            try:
                nfs0 = float(CONFIG.get("SAY_NAME_FONT_SIZE_320", fs0) or fs0)
            except Exception:
                nfs0 = fs0
            fs = max(6, int(round(_scale_px_from_320(fs0, screen_w=w))))
            nfs = max(6, int(round(_scale_px_from_320(nfs0, screen_w=w))))
            font = _resolve_ui_font(fkey, fs)
            name_font = _resolve_ui_font(fkey, nfs)

            try:
                line_gap0 = float(CONFIG.get("SAY_LINE_GAP_PX_320", 2) or 2)
            except Exception:
                line_gap0 = 2.0
            try:
                name_gap0 = float(CONFIG.get("SAY_NAME_GAP_PX_320", 2) or 2)
            except Exception:
                name_gap0 = 2.0
            line_gap = int(round(_scale_px_from_320(line_gap0, screen_w=w)))
            name_gap = int(round(_scale_px_from_320(name_gap0, screen_w=w)))

            try:
                name_col = tuple(CONFIG.get("SAY_NAME_COLOR", (255, 235, 120)) or (255, 235, 120))
            except Exception:
                name_col = (255, 235, 120)
            try:
                text_col = tuple(CONFIG.get("SAY_TEXT_COLOR", (255, 255, 255)) or (255, 255, 255))
            except Exception:
                text_col = (255, 255, 255)
            try:
                ol_on = bool(CONFIG.get("SAY_FONT_OUTLINE_ENABLED", False))
            except Exception:
                ol_on = False
            try:
                ol_px0 = float(CONFIG.get("SAY_FONT_OUTLINE_PX_320", 1) or 1)
            except Exception:
                ol_px0 = 1.0
            ol_px = int(round(_scale_px_from_320(ol_px0, screen_w=w))) if ol_on else 0
            try:
                ol_col = tuple(CONFIG.get("SAY_FONT_OUTLINE_COLOR", (0, 0, 0)) or (0, 0, 0))
            except Exception:
                ol_col = (0, 0, 0)

            cur_y = y
            try:
                who = str(getattr(self, "current_who", "") or "")
            except Exception:
                who = ""
            try:
                show_name = getattr(self, "_say_show_name", None)
            except Exception:
                show_name = None
            if show_name is None:
                try:
                    show_name = bool(CONFIG.get("SAY_SHOW_NAME_DEFAULT", True))
                except Exception:
                    show_name = True
            if bool(show_name) and who.strip():
                try:
                    if ol_px > 0:
                        _tw, _th = _blit_text_with_outline(
                            screen,
                            name_font,
                            who,
                            x,
                            cur_y,
                            color=name_col,
                            outline_color=ol_col,
                            outline_px=ol_px,
                            alpha=say_alpha,
                        )
                        cur_y += int(_th) + name_gap
                    else:
                        s_who = name_font.render(who, True, name_col)
                        if say_alpha < 255:
                            s_who = s_who.copy()
                            s_who.set_alpha(max(0, min(255, int(say_alpha))))
                        screen.blit(s_who, (x, cur_y))
                        cur_y += s_who.get_height() + name_gap
                except Exception:
                    pass

            try:
                full = str(getattr(self, "_say_full_text", getattr(self, "current_text", "")) or "")
            except Exception:
                full = ""
            try:
                nvis = int(getattr(self, "_say_visible_n", len(full)))
            except Exception:
                nvis = len(full)
            vis = full[: max(0, min(len(full), nvis))]
            lines = _wrap_text_by_pixels(vis, font, max(1, rw))
            for ln in lines:
                if cur_y >= y + rh:
                    break
                try:
                    if ol_px > 0:
                        _tw, _th = _blit_text_with_outline(
                            screen,
                            font,
                            ln,
                            x,
                            cur_y,
                            color=text_col,
                            outline_color=ol_col,
                            outline_px=ol_px,
                            alpha=say_alpha,
                        )
                        cur_y += int(_th) + line_gap
                    else:
                        s_ln = font.render(ln, True, text_col)
                        if say_alpha < 255:
                            s_ln = s_ln.copy()
                            s_ln.set_alpha(max(0, min(255, int(say_alpha))))
                        screen.blit(s_ln, (x, cur_y))
                        cur_y += s_ln.get_height() + line_gap
                except Exception:
                    break

        for ov in list(self._ui_overlays or []):
            if ov.get("phase") == "done":
                continue
            surf = ov.get("surf")
            if not surf:
                continue
            try:
                alpha = int(ov.get("draw_alpha", 255))
            except Exception:
                alpha = 255
            alpha = max(0, min(255, alpha))
            if alpha <= 0:
                continue
            x = int(float(ov.get("rest_x", 0)) + float(ov.get("draw_dx", 0)))
            y = int(float(ov.get("rest_y", 0)) + float(ov.get("draw_dy", 0)))
            if alpha >= 255:
                screen.blit(surf, (x, y))
            else:
                tmp = surf.copy()
                tmp.set_alpha(alpha)
                screen.blit(tmp, (x, y))

    def _tick_say_typewriter(self):
        if not bool(getattr(self, "is_talking", False)):
            return
        ph_tw = getattr(self, "_say_ui_fade_phase", None)
        if ph_tw in ("in", "out"):
            return
        try:
            full = str(self._say_full_text or self.current_text or "")
        except Exception:
            full = ""
        if not full:
            self._say_full_text = ""
            self._say_visible_n = 0
            self._say_done = True
            self._say_can_close_at_ms = 0
            return
        try:
            if bool(self._say_done):
                return
        except Exception:
            pass
        try:
            now = int(pygame.time.get_ticks())
        except Exception:
            return
        try:
            ms_per = int(CONFIG.get("SAY_TYPE_MS_PER_CHAR", 28) or 28)
        except Exception:
            ms_per = 28
        ms_per = max(1, min(500, ms_per))
        try:
            last = int(self._say_last_char_ms or 0)
        except Exception:
            last = 0
        if last <= 0:
            # 첫 프레임: 기준 시각을 저장해 다음 프레임부터 진행되게 한다.
            self._say_last_char_ms = now
            last = now
        dt = max(0, now - last)
        add = int(dt // ms_per)
        if add <= 0:
            return
        try:
            cur = int(self._say_visible_n or 0)
        except Exception:
            cur = 0
        nxt = min(len(full), cur + add)
        self._say_visible_n = nxt
        self._say_last_char_ms = last + add * ms_per
        if nxt >= len(full):
            self._say_done = True
            try:
                hold = float(CONFIG.get("SAY_MIN_CLOSE_DELAY_SEC", 0.7) or 0.7)
            except Exception:
                hold = 0.7
            hold_ms = int(max(0.0, min(3.0, hold)) * 1000.0)
            self._say_can_close_at_ms = now + hold_ms

    def _say_peek_next_is_say(self):
        """현재 스텝 직후가 SAY이면 True (연속 대사 체인용)."""
        try:
            if not bool(CONFIG.get("SAY_CHAIN_WITHIN_EVENT", True)):
                return False
        except Exception:
            pass
        ev = getattr(self, "active_event", None)
        if not ev or not isinstance(ev, (list, tuple)):
            return False
        j = int(getattr(self, "step_idx", 0) or 0) + 1
        if j < 0 or j >= len(ev):
            return False
        try:
            t = (ev[j].get("type") or "").strip().upper()
        except Exception:
            return False
        return t == "SAY"

    def _apply_say_step(self, step, *, chain=False):
        """SAY 스텝 내용 적용. chain=True면 UI 페이드 인 생략(박스 유지)."""
        self.is_talking = True
        self.current_who = step.get("who", "")
        self.current_text = step.get("text", "")
        try:
            self._say_full_text = str(step.get("text") or "")
        except Exception:
            self._say_full_text = ""
        sn = step.get("show_name", None)
        if isinstance(sn, str):
            s2 = sn.strip().lower()
            if s2 in ("1", "true", "t", "yes", "y", "on"):
                self._say_show_name = True
            elif s2 in ("0", "false", "f", "no", "n", "off"):
                self._say_show_name = False
            else:
                self._say_show_name = None
        elif sn is None:
            self._say_show_name = None
        else:
            self._say_show_name = bool(sn)
        self._say_visible_n = 0
        self._say_last_char_ms = 0
        self._say_done = False
        self._say_can_close_at_ms = 0
        try:
            hold_open = float(CONFIG.get("SAY_MIN_OPEN_DELAY_SEC", 1.0) or 1.0)
        except Exception:
            hold_open = 1.0
        hold_open_ms = int(max(0.0, min(5.0, hold_open)) * 1000.0)
        try:
            now = int(pygame.time.get_ticks())
        except Exception:
            now = 0
        self._say_ignore_input_until_ms = (int(now) + hold_open_ms) if now else 0
        if chain:
            self._say_ui_fade_phase = "visible"
            self._say_ui_fade_t0_ms = int(now) if now else 0
        else:
            try:
                fade_en = bool(CONFIG.get("SAY_UI_FADE_ENABLED", True))
            except Exception:
                fade_en = True
            try:
                fin_sec = float(CONFIG.get("SAY_UI_FADE_IN_SEC", 0.5) or 0.5)
            except Exception:
                fin_sec = 0.5
            fin_ms = max(0, min(5000, int(fin_sec * 1000)))
            if fade_en and fin_ms > 0:
                self._say_ui_fade_phase = "in"
                self._say_ui_fade_t0_ms = int(now) if now else 0
                self._say_ui_fade_elapsed = 0.0
                ig2 = int(now) + fin_ms if now else 0
                self._say_ignore_input_until_ms = max(int(self._say_ignore_input_until_ms or 0), ig2)
            else:
                self._say_ui_fade_phase = "visible"
                self._say_ui_fade_t0_ms = int(now) if now else 0
        self._configure_say_bubble_from_step(step)

    def _try_advance_say_chain(self):
        """다음 스텝이 SAY면 step만 진행하고 대사만 갱신. 성공 시 True."""
        if not self._say_peek_next_is_say():
            return False
        nxt = int(self.step_idx) + 1
        try:
            st = self.active_event[nxt]
        except Exception:
            return False
        self.step_idx = nxt
        self.is_busy = True
        self._apply_say_step(st, chain=True)
        return True

    def start_free_say(self, say_step: dict, on_finish=None):
        """이벤트 SAY 스텝·기타 경로용 자유 대사 표시."""
        self._free_say_on_finish = on_finish
        self._apply_say_step(dict(say_step or {}), chain=False)

    def _say_finish_after_fade_out(self):
        """SAY 페이드아웃 완료 후 정리하고 다음 스텝으로."""
        self._say_ui_fade_phase = None
        if self._try_advance_say_chain():
            return
        cb = getattr(self, "_free_say_on_finish", None)
        if cb is not None and not self.active_event:
            self._free_say_on_finish = None
            self.current_who = ""
            self.current_text = ""
            self._say_full_text = ""
            self._say_visible_n = 0
            self._say_last_char_ms = 0
            self._say_done = True
            self._say_can_close_at_ms = 0
            self._say_bubble = None
            self.is_talking = False
            try:
                cb()
            except Exception:
                pass
            return
        self.current_who = ""
        self.current_text = ""
        self._say_full_text = ""
        self._say_visible_n = 0
        self._say_last_char_ms = 0
        self._say_done = True
        self._say_can_close_at_ms = 0
        self._say_bubble = None
        self.next_step()

    def _tick_say_ui_fade(self, dt_sec=1.0 / 60.0):
        if not bool(getattr(self, "is_talking", False)):
            return
        ph = getattr(self, "_say_ui_fade_phase", None)
        if ph not in ("in", "out"):
            return
        try:
            fade_en = bool(CONFIG.get("SAY_UI_FADE_ENABLED", True))
        except Exception:
            fade_en = True
        if not fade_en:
            if ph == "in":
                self._say_ui_fade_phase = "visible"
            elif ph == "out":
                self._say_finish_after_fade_out()
            return
        try:
            fin_sec = float(CONFIG.get("SAY_UI_FADE_IN_SEC", 0.5) or 0.5)
        except Exception:
            fin_sec = 0.5
        try:
            fout_sec = float(CONFIG.get("SAY_UI_FADE_OUT_SEC", 0.5) or 0.5)
        except Exception:
            fout_sec = 0.5
        fin_sec = max(0.0, min(5.0, float(fin_sec)))
        fout_sec = max(0.0, min(5.0, float(fout_sec)))
        self._say_ui_fade_elapsed = float(getattr(self, "_say_ui_fade_elapsed", 0.0) or 0.0)
        self._say_ui_fade_elapsed += max(0.0, float(dt_sec))
        el = float(self._say_ui_fade_elapsed)
        if ph == "in":
            if fin_sec <= 0.0 or el >= fin_sec:
                self._say_ui_fade_phase = "visible"
            return
        if ph == "out":
            if fout_sec <= 0.0 or el >= fout_sec:
                self._say_finish_after_fade_out()
            return

    def advance_dialog(self):
        """대사 입력 처리: 1번=전체 표시, 2번=닫고 다음(단, 최소 대기시간 이후)."""
        em = getattr(self, "_emote_overlay", None)
        if em and em.get("awaiting_click"):
            em["awaiting_click"] = False
            self.next_step()
            return
        if bool(getattr(self, "is_talking", False)):
            try:
                full = str(self._say_full_text or self.current_text or "")
            except Exception:
                full = ""
            try:
                now = int(pygame.time.get_ticks())
            except Exception:
                now = 0
            if getattr(self, "_say_ui_fade_phase", None) == "out":
                return
            # 시작 직후엔 입력을 무시(스킵/닫기 모두)
            try:
                ig = int(self._say_ignore_input_until_ms or 0)
            except Exception:
                ig = 0
            if ig and now and int(now) < int(ig):
                return
            # 1) 아직 타자 중이면 즉시 전체 표시 + 닫힘 딜레이 설정
            try:
                cur = int(self._say_visible_n or 0)
            except Exception:
                cur = 0
            if full and cur < len(full):
                self._say_visible_n = len(full)
                self._say_done = True
                try:
                    hold = float(CONFIG.get("SAY_MIN_CLOSE_DELAY_SEC", 0.7) or 0.7)
                except Exception:
                    hold = 0.7
                hold_ms = int(max(0.0, min(3.0, hold)) * 1000.0)
                self._say_can_close_at_ms = int(now) + hold_ms
                return

            # 2) 전체 표시 상태면: 딜레이가 지나야 닫기
            try:
                can_ms = int(self._say_can_close_at_ms or 0)
            except Exception:
                can_ms = 0
            if can_ms and now and int(now) < int(can_ms):
                return

            # 연속 SAY: 박스 닫지 않고 다음 대사만 적용
            if self._say_peek_next_is_say() and self._try_advance_say_chain():
                return

            # close (페이드아웃 후 next_step)
            try:
                fade_en = bool(CONFIG.get("SAY_UI_FADE_ENABLED", True))
            except Exception:
                fade_en = True
            try:
                fout_sec = float(CONFIG.get("SAY_UI_FADE_OUT_SEC", 0.5) or 0.5)
            except Exception:
                fout_sec = 0.5
            fout_ms = max(0, min(5000, int(fout_sec * 1000)))
            if fade_en and fout_ms > 0:
                self._say_ui_fade_phase = "out"
                self._say_ui_fade_t0_ms = int(now) if now else 0
                self._say_ui_fade_elapsed = 0.0
            else:
                self._say_finish_after_fade_out()
            return

        if bool(getattr(self, "active_screen", None)):
            self.next_step()

    def update(self, player, camera, objs, npcs, mask_img=None, dt_sec=1.0 / 60.0):
        if mask_img is not None:
            self._event_mask_img = mask_img
        # escape에서 속도 복구용 (가장 최근 프레임 엔티티 풀)
        self._active_entities = [player] + list(npcs) + list(objs)
        self._last_camera = camera
        # 0. 화면 전체 페이드 (검은 화면) — FADEIN/FADEOUT의 val은 초(duration), dt_sec 기준
        if self.is_fading and float(getattr(self, "fade_duration_sec", 0.0) or 0.0) > 0.0:
            self.fade_elapsed_sec = float(getattr(self, "fade_elapsed_sec", 0.0) or 0.0)
            self.fade_elapsed_sec += max(0.0, float(dt_sec))
            dur = max(1e-6, float(self.fade_duration_sec))
            u = self.fade_elapsed_sec / dur
            if u >= 1.0:
                completed_tgt = int(max(0, min(255, int(self.fade_target))))
                self.fade_alpha = completed_tgt
                self.is_fading = False
                self.fade_duration_ms = 0
                self.fade_duration_sec = 0.0
                self.fade_elapsed_sec = 0.0
                pend = getattr(self, "_pending_fade_in_after_fadeout_sec", None)
                if pend is not None and completed_tgt >= 250:
                    self._pending_fade_in_after_fadeout_sec = None
                    try:
                        sec = max(0.05, float(pend))
                    except Exception:
                        sec = 0.5
                    self.start_global_fade_to(0, sec)
            else:
                u = max(0.0, min(1.0, u))
                fs = float(self.fade_start_alpha)
                ft = float(self.fade_target)
                self.fade_alpha = int(round(fs + (ft - fs) * u))

        self._tick_ui_overlays()
        # SAY typewriter는 busy 중에도 진행돼야 함
        try:
            self._tick_say_typewriter()
        except Exception:
            pass
        try:
            self._tick_say_ui_fade(dt_sec)
        except Exception:
            pass
        try:
            self._tick_say_bubble_frame()
        except Exception:
            pass
        try:
            self._tick_emote_overlay()
        except Exception:
            pass

        if not self.active_event:
            return

        # 이벤트 개체 줌 보간 (카메라 줌과 별도; busy 여부와 무관하게 매 프레임)
        self._tick_entity_event_zoom(player, npcs, objs, dt_sec)

        # FOLLOW 처리 (루프/스텝 진행과 무관하게 매 프레임 추종 갱신)
        if self._followers:
            ent = {"player": player}
            for x in (npcs or []):
                ent[getattr(x, "name", "")] = x
            for x in (objs or []):
                ent[getattr(x, "name", "")] = x
            for f in list(self._followers):
                fol = ent.get(f.get("follower"))
                lead = ent.get(f.get("leader"))
                if not fol or not lead:
                    continue
                try:
                    dist = float(f.get("dist", 40))
                except Exception:
                    dist = 40.0
                try:
                    spm = float(f.get("speed", 1.0))
                except Exception:
                    spm = 1.0
                # leader와 가까우면 정지, 멀면 leader쪽으로 계속 갱신
                try:
                    dnow = math.dist(fol.pos, lead.pos)
                except Exception:
                    dnow = 9999
                if dnow <= dist:
                    sm = getattr(fol, "stop_moving", None)
                    if callable(sm):
                        sm()
                    continue
                try:
                    fol.event_speed_mul = spm
                except Exception:
                    pass
                m = self._event_mask_img
                if isinstance(fol, MaskWalkingCharacter):
                    try:
                        fol.follow_step(lead.pos, dist, m, objs, npcs, speed_mul=spm, leader=lead)
                    except Exception:
                        pass
                else:
                    try:
                        fol.set_new_target(lead.pos[0], lead.pos[1])
                    except Exception:
                        pass

        if self._escape_mode == "condition" and self._escape_condition:
            ctx = dict(self.flow.save_data)
            ctx["gamestart"] = self.flow.boot_phase
            if evaluate_global_condition(self._escape_condition, ctx):
                self._trigger_event_escape()

        if not self.active_event:
            return

        # [이펙트] ANIM_ONCE/EFFECT wait(is_busy) 중에도 매 프레임 갱신 (아니면 영원히 is_done=False)
        for e in self.active_effects[:]:
            e.update()
            if e.is_done:
                self.active_effects.remove(e)

        # 그 다음 체크 로직으로 넘어감
        if self.is_busy:
            self._check_completion(player, camera, npcs, objs, dt_sec=dt_sec)
            return

        # 2. 다음 단계 실행 (ZOOM/TILT/SHEAR/CAMERA·CONDITION은 연속 burst 가능)
        if self.step_idx < len(self.active_event):
            burst = 0
            skip_depth = int(getattr(self, "_event_skip_depth", 0) or 0)
            while self.step_idx < len(self.active_event) and burst < 24:
                step = self.active_event[self.step_idx]
                st = (step.get("type") or "").upper()

                if st == "CONDITION_SKIP":
                    if skip_depth > 0:
                        skip_depth -= 1
                    self._event_skip_depth = skip_depth
                    self.next_step()
                    burst += 1
                    continue

                if skip_depth > 0:
                    self.next_step()
                    burst += 1
                    continue

                if st == "CONDITION":
                    ctx = dict(self.flow.save_data) if self.flow else {}
                    try:
                        ctx["gamestart"] = self.flow.boot_phase
                    except Exception:
                        pass
                    if not evaluate_event_step_condition(step, ctx):
                        skip_depth += 1
                    self._event_skip_depth = skip_depth
                    self.next_step()
                    burst += 1
                    continue

                self._execute_step(step, player, camera, npcs, objs)
                burst += 1
                if self.is_busy:
                    break
                if st not in PARALLEL_EFFECT_STEP_TYPES:
                    break
            self._event_skip_depth = skip_depth
        else:
            self.end_event()

    def _tick_entity_event_zoom(self, player, npcs, objs, dt_sec=1.0 / 60.0):
        del dt_sec  # 시계 기반 보간
        for ent in [player] + list(npcs or []) + list(objs or []):
            try:
                zt = float(getattr(ent, "event_entity_zoom_target", 1.0))
                zc = float(getattr(ent, "event_entity_zoom", 1.0))
            except Exception:
                continue
            zt = max(0.05, min(8.0, zt))
            zc = max(0.05, min(8.0, zc))
            eps = max(0.008, abs(zt) * 0.02)
            ztimed = getattr(ent, "event_entity_zoom_timed", None)
            if isinstance(ztimed, dict):
                ent.event_entity_zoom = timed_effect_value(ztimed, zc)
                if timed_effect_finished(ztimed):
                    ent.event_entity_zoom = zt
                    ent.event_entity_zoom_timed = None
                continue
            if abs(zc - zt) <= eps:
                ent.event_entity_zoom = zt

    def reset_entity_event_zooms(self, player, npcs, objs):
        """새 이벤트 시작 전 등: 모든 엔티티의 이벤트 줌 배율을 1로 초기화."""
        for ent in [player] + list(npcs or []) + list(objs or []):
            try:
                ent.event_entity_zoom = 1.0
                ent.event_entity_zoom_target = 1.0
                ent.event_entity_zoom_timed = None
            except Exception:
                pass

    def _run_char_anim_step(self, step, player, npcs, objs):
        """ANIM(레거시) + ACTION_ANIM(모드·방향·점프 높이·release)."""
        s_type = (step.get("type") or "ANIM").upper()
        target_name = (step.get("target") or "player").strip()
        anim_name = (step.get("name") or step.get("anim") or step.get("state") or "").strip()
        if not anim_name:
            self.next_step()
            return
        target = (
            player
            if target_name == "player"
            else next((x for x in (npcs + objs) if getattr(x, "name", "") == target_name), None)
        )
        if not target:
            self.next_step()
            return

        def _parse_wait(w):
            if isinstance(w, str):
                return w.strip().lower() not in ("0", "false", "f", "no", "n", "off")
            return bool(w)

        def _parse_loop(loop):
            if isinstance(loop, str):
                return loop.strip().lower() not in ("0", "false", "f", "no", "n", "off")
            return bool(loop)

        mode = (step.get("mode") or "").strip().lower()
        use_extended = s_type == "ACTION_ANIM" or (s_type == "ANIM" and bool(mode))

        if not use_extended:
            dur_raw = step.get("val", step.get("duration", 0))
            try:
                dur_s = float(dur_raw) if dur_raw is not None else 0.0
            except Exception:
                dur_s = 0.0
            duration_ms = int(max(0.0, dur_s) * 1000.0)
            loop = _parse_loop(step.get("loop", True))
            wait_for_finish = _parse_wait(step.get("wait", True))
            pa = getattr(target, "play_anim", None)
            if callable(pa):
                pa(anim_name, duration_ms=duration_ms if duration_ms > 0 else 0, loop=loop)
            if duration_ms > 0 and wait_for_finish:
                self._anim_wait_end_ms = pygame.time.get_ticks() + duration_ms
            else:
                self._anim_wait_end_ms = 0
                self.next_step()
            return

        if mode not in ("once", "hold"):
            mode = "once"
        if mode == "once":
            dur_raw = step.get("val", step.get("duration", 1.0))
            try:
                dur_s = float(dur_raw) if dur_raw is not None else 1.0
            except Exception:
                dur_s = 1.0
            duration_ms = int(max(0.05, dur_s) * 1000.0)
            loop = _parse_loop(step.get("loop", False))
            wait_for_finish = _parse_wait(step.get("wait", True))
        else:
            duration_ms = 0
            loop = _parse_loop(step.get("loop", True))
            wait_for_finish = _parse_wait(step.get("wait", False))

        release = (step.get("release") or "idle").strip().lower()
        if release not in ("idle", "stop"):
            release = "idle"

        d = (step.get("dir") or step.get("face") or "").strip().lower()
        if d in ("left", "l"):
            target.direction = "left"
        elif d in ("right", "r"):
            target.direction = "right"

        temp_height = None
        if anim_name == "jump" and ("height" in step or str(step.get("height", "")).strip() != ""):
            try:
                temp_height = float(step.get("height"))
            except (TypeError, ValueError):
                temp_height = None

        pa = getattr(target, "play_anim", None)
        if callable(pa):
            pa(
                anim_name,
                duration_ms=duration_ms if duration_ms > 0 else 0,
                loop=loop,
                release=release,
                temp_height=temp_height,
            )
        if duration_ms > 0 and wait_for_finish:
            self._anim_wait_end_ms = pygame.time.get_ticks() + duration_ms
        else:
            self._anim_wait_end_ms = 0
            self.next_step()

    def _event_move_start_on_target(self, fragment, target, player, npcs, objs, wait_for_finish):
        """
        단일 대상에 MOVE 적용. 반환: "skip" | "instant" | "moving"
        (instant 시 next_step 은 호출자가 처리)
        """
        wps = _normalize_move_step_waypoints(fragment)
        if not wps:
            # pos 없이 dir 만: 제자리 방향 전환 (예: { "type":"MOVE", "target":"player", "dir":"right" })
            if _event_apply_step_dir(target, fragment):
                stop = getattr(target, "stop_moving", None)
                if callable(stop):
                    stop()
                target.event_waypoints = None
                return "instant"
            return "skip"
        ins = fragment.get("instant")
        instant = ins is True or (isinstance(ins, str) and ins.strip().lower() in ("1", "true", "yes", "on"))
        force = _event_move_force_from_step(fragment)
        move_anim = (fragment.get("move_anim") or fragment.get("path_anim") or "").strip()
        preserve_pa = bool(move_anim)
        fx0, fy0 = float(wps[0][0]), float(wps[0][1])
        rest_wp = [[float(p[0]), float(p[1])] for p in wps[1:]]
        if instant:
            lx, ly = float(wps[-1][0]), float(wps[-1][1])
            target.pos = [lx, ly]
            if hasattr(target, "origin_pos"):
                target.origin_pos = [lx, ly]
            target.event_waypoints = None
            stop = getattr(target, "stop_moving", None)
            if callable(stop):
                stop()
            if move_anim:
                pa = getattr(target, "play_anim", None)
                if callable(pa):
                    pa(move_anim, duration_ms=0, loop=True, release="idle", temp_height=None)
            return "instant"
        # 같은 대상에 wait:false로 MOVE가 연달아 있을 때: 웨이포인트를 덮어쓰지 않고 끝에 이어 붙인다.
        if _event_target_mid_scripted_move(target):
            extras = [[float(p[0]), float(p[1])] for p in wps]
            ew = list(getattr(target, "event_waypoints", None) or [])
            last = None
            if ew:
                try:
                    last = (float(ew[-1][0]), float(ew[-1][1]))
                except (TypeError, ValueError, IndexError):
                    last = None
            if last is None:
                t = getattr(target, "target", None)
                if t is not None and len(t) >= 2:
                    try:
                        last = (float(t[0]), float(t[1]))
                    except (TypeError, ValueError):
                        last = None
            if last is not None and extras:
                lx, ly = last[0], last[1]
                try:
                    fx, fy = float(extras[0][0]), float(extras[0][1])
                except (TypeError, ValueError):
                    fx, fy = lx, ly
                if math.hypot(fx - lx, fy - ly) < 8.0:
                    extras = extras[1:]
            if not extras:
                return "skip"
            target.event_waypoints = ew + extras
            return "moving"
        sp = fragment.get("speed", None)
        if sp is not None and sp != "":
            try:
                mul = float(sp)
                old_mul = getattr(target, "event_speed_mul", 1.0)
                target.event_speed_mul = mul
                if wait_for_finish:
                    self._restore_speed_after_move[(id(target), self.step_idx)] = old_mul
                else:
                    target._event_speed_old_mul = old_mul
                    target._event_speed_restore = True
            except Exception:
                pass
        m = getattr(self, "_event_mask_img", None)
        try:
            if isinstance(target, MaskWalkingCharacter):
                target._event_force_move = bool(force)
        except Exception:
            pass
        target._event_wp_preserve_path_anim = preserve_pa
        target.event_waypoints = rest_wp if rest_wp else None
        if isinstance(target, MaskWalkingCharacter) and m is not None and (not force):
            target.set_new_target(
                fx0, fy0, m, objs, npcs,
                preserve_path_anim=preserve_pa,
                clear_event_waypoints=False,
            )
        else:
            target.set_new_target(
                fx0, fy0,
                preserve_path_anim=preserve_pa,
                clear_event_waypoints=False,
            )
        if move_anim:
            pa = getattr(target, "play_anim", None)
            if callable(pa):
                pa(move_anim, duration_ms=0, loop=True, release="idle", temp_height=None)
        if "dir" in fragment:
            _event_apply_step_dir(target, fragment)
        return "moving"

    def _spawn_anim_once(self, step):
        """
        ANIM_ONCE: object_defs 키(name) + 월드 pos — 애니 1회 재생, 끝날 때까지 다음 스텝 대기.
        (내부적으로 Effect + _effect_wait_ref, EFFECT wait:true 와 동일한 완료 처리)
        """
        e_name = (step.get("name") or "").strip()
        if not e_name:
            return False
        px, py = _anim_once_pos_from_step(step)
        new_effect = Effect(e_name, px, py, loop=False, anchor="feet")
        self.active_effects.append(new_effect)
        self._effect_wait_ref = new_effect
        return True

    def _execute_carry_step(self, step, player, npcs, objs):
        """
        [CARRY] 이벤트 — 오브젝트 들기/내려놓기.
        Player.begin_carry_* + FieldItem fly 연출 재사용 (클릭 interact_with 와 동일).

        JSON 필드:
          action  : pick | put  (take/grab/drop 등 별칭 가능, _parse_carry_step_action)
          holder  : 누가 드는지 (기본 player — 현재 Player 만 지원)
          target  : pick → 맵 위 오브젝트 이름(object_defs 키)
                     put  → 슬롯 이름(type=slot). pos 가 있으면 target 슬롯은 무시
          pos     : put 시 월드 [x,y] — 바닥에 내려놓기 (슬롯 없이)
          wait    : fly 연출 끝까지 대기 (기본 true)
        """
        from data import OBJ_ASSETS

        action = _parse_carry_step_action(step)
        if action not in ("pick", "put"):
            print(f"[CARRY] action 없음/알 수 없음 — 건너뜀")
            self.next_step()
            return

        holder_name = (step.get("holder") or step.get("who") or "player").strip()
        holder = _event_resolve_entity(holder_name, player, npcs, objs)
        if holder is None or not isinstance(holder, Player):
            print(f"[CARRY] holder '{holder_name}' 없음 또는 Player 아님 — 건너뜀")
            self.next_step()
            return

        wait_fly = _parse_carry_step_wait(step)
        target_name = (step.get("target") or step.get("name") or step.get("item") or "").strip()
        map_id = str(getattr(self.flow, "save_data", {}).get("current_map") or "")

        started = False
        fly_item = None

        if action == "pick":
            if not target_name:
                print("[CARRY] pick: target(오브젝트 이름) 필요")
                self.next_step()
                return
            item = _event_find_holdable_obj(target_name, objs)
            if not item:
                print(f"[CARRY] pick: '{target_name}' 없음 또는 이미 들림")
                self.next_step()
                return
            started = holder.begin_carry_pickup(item)
            fly_item = item if started else None
            if not started:
                print(f"[CARRY] pick: '{target_name}' begin_carry_pickup 실패")
                self.next_step()
                return
        else:
            item = holder.held_item
            if not item:
                print("[CARRY] put: holder 손이 비어 있음")
                self.next_step()
                return
            raw_pos = step.get("pos")
            if raw_pos is not None:
                try:
                    drop_pos = [float(raw_pos[0]), float(raw_pos[1])]
                except (TypeError, ValueError, IndexError):
                    print("[CARRY] put: pos 좌표 오류")
                    self.next_step()
                    return
                started = holder.begin_carry_put_world(drop_pos)
            elif target_name:
                slot_ent = _event_resolve_entity(target_name, player, npcs, objs)
                slot_info = OBJ_ASSETS.get(target_name, {}) or {}
                if slot_ent is None or slot_info.get("type") != "slot":
                    print(f"[CARRY] put: '{target_name}' 슬롯 아님 — pos 없으면 실패")
                    self.next_step()
                    return
                started = holder.begin_carry_put_slot(
                    slot_ent,
                    flow=self.flow,
                    objs=objs,
                    npcs=npcs,
                    map_id=map_id,
                )
            else:
                try:
                    hx, hy = float(holder.pos[0]), float(holder.pos[1])
                except (TypeError, ValueError):
                    hx, hy = 0.0, 0.0
                started = holder.begin_carry_put_world([hx, hy])
            fly_item = item if started else None
            if not started:
                print("[CARRY] put: begin_carry_put 실패")
                self.next_step()
                return

        if wait_fly and fly_item is not None and getattr(fly_item, "is_flying", False):
            self._carry_wait_item = fly_item
            self.is_busy = True
        else:
            self.next_step()

    def _execute_change_step(self, step, player, npcs, objs):
        """
        [CHANGE] FieldItem 외형을 다른 object_defs 키로 교체 (들고 있는 중 OK).

        target: 맵 오브젝트 이름 | held | @held (player.held_item)
        to: 새 object_defs 키 (wateringcan3 등)
        """
        tgt_raw = (step.get("target") or step.get("from") or "").strip()
        new_name = (step.get("to") or step.get("new_name") or step.get("name") or "").strip()
        if not new_name:
            print("[CHANGE] to(새 object_defs 키) 필요")
            self.next_step()
            return

        item = None
        tl = tgt_raw.lower()
        if tl in ("held", "@held", "player.held", "hand"):
            item = getattr(player, "held_item", None)
            if item is None:
                print("[CHANGE] 손에 든 물건 없음")
                self.next_step()
                return
        elif tgt_raw:
            ent = _event_resolve_entity(tgt_raw, player, npcs, objs)
            if ent is getattr(player, "held_item", None):
                item = ent
            elif isinstance(ent, FieldItem):
                item = ent
            else:
                print(f"[CHANGE] '{tgt_raw}' 는 FieldItem 이 아님")
                self.next_step()
                return
        else:
            item = getattr(player, "held_item", None)
            if item is None:
                print("[CHANGE] target 비었고 손도 비어 있음")
                self.next_step()
                return

        if not isinstance(item, FieldItem):
            print("[CHANGE] 대상이 FieldItem 이 아님")
            self.next_step()
            return
        old = getattr(item, "name", "?")
        if item.retarget_object_def(new_name):
            print(f"[CHANGE] {old} -> {new_name}")
        else:
            print(f"[CHANGE] 실패: to='{new_name}' 없음(object_defs)")
        self.next_step()

    def _execute_step(self, step, player, camera, npcs, objs):
        s_type = step["type"]
        self.is_busy = True # 일단 바쁘다고 설정
        
        if s_type == "SAY":
            # 대화는 클릭할 때까지 busy 유지 (main에서 처리)
            self._apply_say_step(step, chain=False)
        elif s_type == "EMOTE":
            act = (step.get("action") or "show").strip().lower()
            if act == "clear":
                self._emote_overlay = None
                self.next_step()
                return
            emo = _sanitize_ui_emotion_token(step.get("emotion") or step.get("name") or "")
            if not emo:
                self.next_step()
                return
            rel = f"images/ui/{emo}"
            try:
                mx = int(CONFIG.get("EMOTE_MAX_FRAMES", 48) or 48)
            except Exception:
                mx = 48
            frames = _load_numbered_ui_sequence(rel, max_frames=mx)
            if not frames:
                self.next_step()
                return
            tgt = (step.get("target") or "player").strip() or "player"
            adv_raw = (step.get("advance") or "continue").strip().lower()
            advance_mode = "stop" if adv_raw in ("stop", "wait", "click", "block") else "continue"
            try:
                frame_ms = int(step.get("frame_ms", CONFIG.get("EMOTE_DEFAULT_FRAME_MS", 120)) or 120)
            except Exception:
                frame_ms = 120
            frame_ms = max(16, min(2000, frame_ms))
            try:
                hold_last_sec = float(step.get("hold_last_sec", step.get("hold_sec", 0)) or 0)
            except Exception:
                hold_last_sec = 0.0
            hold_last_sec = max(0.0, min(120.0, hold_last_sec))
            hold_ms = int(round(hold_last_sec * 1000.0))
            try:
                now0 = int(pygame.time.get_ticks())
            except Exception:
                now0 = 0
            self._emote_overlay = {
                "target": tgt,
                "frames": frames,
                "frame_idx": 0,
                "frame_ms": frame_ms,
                "acc_ms": 0,
                "phase": "play",
                "hold_remaining_ms": max(0, min(1200000, hold_ms)),
                "advance_mode": advance_mode,
                "awaiting_click": False,
                "_advanced_step": False,
                "_last_ms": now0,
                "post_acc": 0,
            }
            # busy 유지: continue는 애니+유지시간 후 자동 next, stop은 클릭까지
        elif s_type in ("EVT_STOP_BEGIN", "EVENT_STOP_BEGIN", "STOP_BEGIN"):
            # 원터치 입력 게임 정책:
            # - 이벤트 스탑 입력은 "클릭(=A/Enter/Space도 클릭으로 취급)"만 허용한다.
            # - 디버그용 키 입력은 main.py에서 별도로 처리.
            act = (step.get("action") or "end").strip().lower()
            if act in ("end_event", "endgame", "end_event_now"):
                act = "end"
            if act not in ("end", "break_loop", "lock"):
                act = "end"
            self._escape_action = act
            self._escape_mode = "click"
            self._escape_key_pygame = None
            self._escape_condition = ""
            self.next_step()

        elif s_type in ("EVT_STOP_END", "EVENT_STOP_END", "STOP_END"):
            # 이벤트 중도 스탑(탈출) 입력 비활성화.
            self._escape_mode = "none"
            self._escape_action = "end"
            self._escape_key_pygame = None
            self._escape_condition = ""
            self.next_step()

        elif s_type == "MOVE":
            par = step.get("parallel")
            if isinstance(par, (list, tuple)) and len(par) > 0:
                w = step.get("wait", False)
                if isinstance(w, str):
                    wait_for_finish = w.strip().lower() not in ("0", "false", "f", "no", "n", "off")
                else:
                    wait_for_finish = bool(w)
                started = False
                for frag in par:
                    if not isinstance(frag, dict):
                        continue
                    tn = frag.get("target")
                    target = player if tn == "player" else next((x for x in (npcs + objs) if x.name == tn), None)
                    if not target:
                        continue
                    res = self._event_move_start_on_target(frag, target, player, npcs, objs, wait_for_finish)
                    if res != "skip":
                        started = True
                if not started:
                    self.next_step()
                elif not wait_for_finish:
                    self.next_step()
                return

            move_sync = (step.get("move_sync") or step.get("sync") or "").strip()
            if move_sync:
                ev = self.active_event
                i0 = self.step_idx
                bundle_idx = [i0]
                j = i0 + 1
                while j < len(ev):
                    sj = ev[j]
                    if sj.get("type") != "MOVE" or sj.get("parallel"):
                        break
                    sj_sync = (sj.get("move_sync") or sj.get("sync") or "").strip()
                    if sj_sync != move_sync:
                        break
                    bundle_idx.append(j)
                    j += 1
                if len(bundle_idx) >= 2:
                    entries = []
                    started = False
                    for bi in bundle_idx:
                        st = ev[bi]
                        tn = st.get("target")
                        tgt = player if tn == "player" else next((x for x in (npcs + objs) if getattr(x, "name", "") == tn), None)
                        wpsi = _normalize_move_step_waypoints(st)
                        if not tgt or not wpsi:
                            continue
                        ins = st.get("instant")
                        inst = ins is True or (
                            isinstance(ins, str) and ins.strip().lower() in ("1", "true", "yes", "on")
                        )
                        if inst:
                            res = self._event_move_start_on_target(st, tgt, player, npcs, objs, True)
                            if res != "skip":
                                started = True
                                entries.append({"step_i": bi, "target_name": tn, "wps": wpsi})
                            continue
                        res = self._event_move_start_on_target(st, tgt, player, npcs, objs, True)
                        if res == "skip":
                            continue
                        if res == "instant":
                            started = True
                            entries.append({"step_i": bi, "target_name": tn, "wps": wpsi})
                            continue
                        started = True
                        entries.append({"step_i": bi, "target_name": tn, "wps": wpsi})
                    if not started:
                        self.step_idx += len(bundle_idx)
                        self.is_busy = False
                        self.is_talking = False
                        self._say_ui_fade_phase = None
                    else:
                        self._move_sync_group = {
                            "base_idx": i0,
                            "count": len(bundle_idx),
                            "sync": move_sync,
                            "entries": entries,
                        }
                    return

            target = player if step.get("target") == "player" else \
                     next((x for x in (npcs + objs) if x.name == step["target"]), None)
            if not target:
                self.next_step()
            else:
                wps = _normalize_move_step_waypoints(step)
                ins = step.get("instant")
                instant = ins is True or (
                    isinstance(ins, str) and ins.strip().lower() in ("1", "true", "yes", "on")
                )
                w = step.get("wait", False)
                if isinstance(w, str):
                    wait_for_finish = w.strip().lower() not in ("0", "false", "f", "no", "n", "off")
                else:
                    wait_for_finish = bool(w)
                res = self._event_move_start_on_target(step, target, player, npcs, objs, wait_for_finish)
                if res == "skip":
                    self.next_step()
                elif res == "instant":
                    self.next_step()
                elif not wait_for_finish:
                    self.next_step()

        elif s_type in ("WAIT", "INTERVAL"):
            try:
                sec = float(step.get("val", 0) or 0)
            except (TypeError, ValueError):
                sec = 0.0
            self.wait_timer = pygame.time.get_ticks() + int(max(0.0, sec) * 1000)

        elif s_type in ("ANIM", "ACTION_ANIM"):
            self._run_char_anim_step(step, player, npcs, objs)

        elif s_type == "ZOOM":
            pz = parse_zoom_step(step)
            raw_tgt = (pz.get("target") or "").strip()
            lt = raw_tgt.lower()
            val = float(pz["val"])
            is_cam = bool(pz["is_camera"])
            instant = bool(pz["instant"])
            dur = float(pz["duration_sec"])
            t0 = effect_now_ms()

            if is_cam:
                wz_cmd = {"val": val, "duration_sec": dur, "t0_ms": t0}
                if instant:
                    wz_cmd["instant"] = True
                self.world_zoom_step_speed = None
                self.world_zoom_timed = None
                self.pending_world_zoom = wz_cmd
                self.next_step()
            else:
                ent = (
                    player
                    if lt == "player"
                    else next(
                        (x for x in (npcs + objs) if getattr(x, "name", "") == raw_tgt),
                        None,
                    )
                )
                if not ent:
                    self.next_step()
                else:
                    ent.event_entity_zoom_target = val
                    ent.event_entity_zoom_duration_sec = dur
                    ent.event_entity_zoom_timed = None
                    if instant:
                        ent.event_entity_zoom = val
                        self.next_step()
                    else:
                        zc = float(getattr(ent, "event_entity_zoom", 1.0))
                        ent.event_entity_zoom_timed = {}
                        timed_effect_init(
                            ent.event_entity_zoom_timed, zc, val, dur, now_ms=t0
                        )
                        self.next_step()

        elif s_type == "TILT":
            pt = parse_tilt_step(step)
            tc = {
                "target": float(pt["target"]),
                "duration_sec": float(pt["duration_sec"]),
                "t0_ms": effect_now_ms(),
            }
            if pt["instant"]:
                tc["instant_once"] = True
            self.tilt_control = tc
            self.next_step()

        elif s_type == "SHEAR":
            ps = parse_shear_step(step)
            instant_once = bool(ps["instant"])
            dur = float(ps["duration_sec"])
            t0 = effect_now_ms()
            if not ps["on"]:
                off = {"enabled": False, "duration_sec": dur, "t0_ms": t0}
                if instant_once:
                    off["instant_once"] = True
                self.shear_control = off
                self.next_step()
                return
            d = {
                "enabled": True,
                "strength_mul": float(ps["strength"]),
                "bypass_strength": bool(ps["bypass_strength"]),
                "duration_sec": dur,
                "t0_ms": t0,
            }
            if instant_once:
                d["instant_once"] = True
            if ps.get("max_px") is not None:
                d["max_px"] = int(ps["max_px"])
            self.shear_control = d
            self.next_step()

        elif s_type == "FX":
            # FX: 비주얼 효과 제어 (현재: cloud_shadow)
            kind = (step.get("kind") or step.get("name") or "").strip().lower()
            if kind in ("cloud", "cloudshadow", "cloud_shadow", "cloud-shadow"):
                on_raw = step.get("on", True)
                if isinstance(on_raw, str):
                    on_b = on_raw.strip().lower() in ("1", "true", "t", "yes", "y", "on")
                else:
                    on_b = bool(on_raw)
                if not on_b:
                    self.cloud_shadow_control = {"enabled": False}
                    self.next_step()
                    return
                d = {"enabled": True}
                d["dir"] = (step.get("dir") or step.get("direction") or "RANDOM")
                sp = step.get("speed", None)
                if sp is not None and sp != "":
                    try:
                        d["speed"] = float(sp)
                    except (TypeError, ValueError):
                        pass
                fr = step.get("freq", step.get("frequency", None))
                if fr is not None and fr != "":
                    try:
                        d["freq"] = float(fr)
                    except (TypeError, ValueError):
                        pass
                for gk, sk in (
                    ("grid_cell", "grid_cell"),
                    ("grid_jitter", "grid_jitter"),
                    ("grid_max", "grid_max"),
                ):
                    gv = step.get(sk)
                    if gv is not None and str(gv).strip() != "":
                        try:
                            d[gk] = float(gv) if gk != "grid_max" else int(float(gv))
                        except (TypeError, ValueError):
                            pass
                self.cloud_shadow_control = d
                self.next_step()
            else:
                # 알 수 없는 FX는 무시
                self.next_step()

        elif s_type == "CAMERA":
            pcam = parse_camera_step(step)
            mode = pcam["mode"]
            smooth_b = pcam["smooth"]
            ler = pcam.get("lerp")
            slot = pcam["slot"]
            cam_dur = float(pcam["duration_sec"])

            # --- 현재 위치 고정 / 저장 / 불러오기 (한글·영문 별칭) ---
            if mode in ("save_camera", "camera_save", "save", "카메라_저장", "위치_저장"):
                if camera is not None:
                    try:
                        cx, cy = float(camera.pos[0]), float(camera.pos[1])
                    except Exception:
                        cx, cy = 0.0, 0.0
                    self._camera_saved_slots[slot] = [cx, cy]
                self.next_step()
                return
            if mode in ("load_camera", "camera_load", "load", "카메라_불러오기", "위치_불러오기"):
                data = self._camera_saved_slots.get(slot)
                if data and len(data) >= 2:
                    try:
                        fx, fy = float(data[0]), float(data[1])
                    except Exception:
                        fx, fy = 0.0, 0.0
                    self.pending_camera_command = {
                        "mode": "fixed",
                        "x": fx,
                        "y": fy,
                        "smooth": smooth_b,
                        "lerp": ler,
                        "duration_sec": cam_dur,
                    }
                self.next_step()
                return
            if mode in (
                "lock_here",
                "lock_current",
                "camera_lock_here",
                "lock",
                "고정",
                "현재_고정",
                "현재카메라위치고정",
            ):
                self.pending_camera_command = {
                    "mode": "lock_here",
                    "smooth": smooth_b,
                    "lerp": ler,
                    "duration_sec": cam_dur,
                }
                self.next_step()
                return

            cmd = {"mode": mode, "smooth": smooth_b, "lerp": ler, "duration_sec": cam_dur}
            if mode in ("follow_entity", "follow", "entity"):
                cmd["target"] = (pcam.get("target") or "").strip()
            if mode in ("fixed", "fixed_world", "world", "point"):
                cmd["x"] = pcam.get("x")
                cmd["y"] = pcam.get("y")
            self.pending_camera_command = cmd
            self.next_step()

        elif s_type in ("DEV_CMD", "GLOBAL"):
            from field_runtime import apply_dev_runtime_command

            cmd = (
                step.get("cmd")
                or step.get("command")
                or (step.get("action") if s_type == "GLOBAL" else None)
                or ""
            )
            cmd = str(cmd).strip()
            if cmd:
                try:
                    mid = (self.flow.save_data or {}).get("current_map")
                except Exception:
                    mid = None
                apply_dev_runtime_command(
                    cmd,
                    ev_mgr=self,
                    cam=camera,
                    flow=self.flow,
                    map_id=mid,
                    player=player,
                )
            self.next_step()

        elif s_type == "CALL_EVENT":
            # 다른 이벤트(LOCAL/GLOBAL/SYNC/FRAGMENTS) steps·result 를 여기서 실행 후 복귀
            call_id = (step.get("target") or step.get("fragment") or "").strip()
            if not call_id:
                self.next_step()
                return
            callee = (self._fragment_catalog or {}).get(call_id)
            if not callee:
                print(f"[CALL_EVENT] unknown event id: {call_id}")
                self.next_step()
                return
            if call_id in self._fragment_call_set:
                print(f"[CALL_EVENT] cycle detected: {call_id}")
                self.next_step()
                return
            callee_steps = list(callee.get("steps") or [])
            if not callee_steps:
                print(f"[CALL_EVENT] no steps: {call_id}")
                self.next_step()
                return
            if self._fragment_call_depth >= self.MAX_FRAGMENT_DEPTH:
                print("[CALL_EVENT] max call depth exceeded")
                self.next_step()
                return
            self._event_call_stack.append(
                {
                    "event_list": self.active_event,
                    "event_id": self.active_event_id,
                    "result": self.active_event_result,
                    "return_idx": int(self.step_idx) + 1,
                }
            )
            self._fragment_call_depth += 1
            self._fragment_call_set.add(call_id)
            self.active_event = callee_steps
            parent_id = self.active_event_id or "?"
            self.active_event_id = f"{parent_id}::{call_id}"
            callee_result = callee.get("result")
            self.active_event_result = (
                dict(callee_result) if isinstance(callee_result, dict) else None
            )
            self.step_idx = 0
            self.is_busy = False
            self.is_talking = False
            self._say_ui_fade_phase = None
            self._loop_end_to_head, self._loop_pairs = _parse_loop_jump_table(self.active_event)
            sec = callee.get("_call_event_section", "?")
            print(f"[CALL_EVENT] -> {call_id} [{sec}]")
            return

        elif s_type == "FOLLOW_START":
            follower = (step.get("follower") or step.get("target") or "").strip()
            leader = (step.get("leader") or step.get("follow") or "").strip()
            if follower and leader:
                self._followers = [x for x in self._followers if not (x.get("follower") == follower)]
                self._followers.append(
                    {
                        "follower": follower,
                        "leader": leader,
                        "dist": step.get("dist", 40),
                        "speed": step.get("speed", 1.0),
                    }
                )
                fol_ent = next(
                    (x for x in (npcs + objs) if getattr(x, "name", "") == follower),
                    None,
                )
                if fol_ent is not None:
                    sm = getattr(fol_ent, "stop_moving", None)
                    if callable(sm):
                        sm()
            self.next_step()

        elif s_type == "FOLLOW_STOP":
            follower = (step.get("follower") or step.get("target") or "").strip()
            if follower:
                self._followers = [x for x in self._followers if x.get("follower") != follower]
            else:
                self._followers = []
            self.next_step()

        elif s_type == "MAP":
            map_id = step.get("target")
            # [수정] pos_x, pos_y가 비어있거나 0인 경우 None으로 취급
            pos_x = step.get("pos_x")
            pos_y = step.get("pos_y")
            
            # 구형(pos 필드) 및 신형(pos_x, pos_y) 대응
            if not pos_x and not pos_y:
                p = step.get("pos")
                if p and (p[0] != 0 or p[1] != 0):
                    pos = p
                else:
                    pos = None # 좌표 비어있음
            else:
                try:
                    pos = [float(pos_x), float(pos_y)]
                except:
                    pos = None

            if map_id:
                # 맵 이동 정보를 담아둠 (main.py에서 처리)
                self.pending_map_change = {"map_id": map_id, "pos": pos}
            self.next_step()

        elif s_type == "FADEOUT":
            dur = self._fade_duration_sec_from_step(step, 1.0)
            self._begin_global_fade(255, dur)
            self.next_step()

        elif s_type == "FADEIN":
            dur = self._fade_duration_sec_from_step(step, 1.0)
            self._begin_global_fade(0, dur)
            self.next_step()
        
        elif s_type == "PLAYER_VISIBLE":
            # val: True/False 또는 0/1, "0"/"1" 등도 허용
            v = step.get("val", True)
            if isinstance(v, str):
                is_visible = v.strip().lower() not in ("0", "false", "f", "no", "n", "off", "")
            else:
                is_visible = bool(v)
            player.is_visible = is_visible
            self.next_step()

        elif s_type == "CURSOR_VISIBLE":
            # val: True/False 또는 0/1, "0"/"1" 등도 허용
            v = step.get("val", True)
            if isinstance(v, str):
                is_visible = v.strip().lower() not in ("0", "false", "f", "no", "n", "off", "")
            else:
                is_visible = bool(v)
            self.cursor_visible = is_visible
            # persist:true면 이 이벤트가 끝나도 상태를 유지한다.
            p = step.get("persist", False)
            if isinstance(p, str):
                self._cursor_visible_persist = p.strip().lower() not in ("0", "false", "f", "no", "n", "off", "")
            else:
                self._cursor_visible_persist = bool(p)
            self.next_step()

        elif s_type == "PLACE":
            target_name = step.get("target")
            st_raw = step.get("sprite_tilt", None)
            st_place = None
            if st_raw is not None:
                try:
                    st_place = _clamp_sprite_tilt(st_raw)
                except Exception:
                    st_place = None
            has_place_height = "height" in step
            h_place = _clamp_draw_height(step.get("height")) if has_place_height else None
            has_place_ysort = "ysort" in step
            ysort_place = _normalize_ysort_mode(step.get("ysort")) if has_place_ysort else None
            has_place_layer = "layer" in step
            layer_place = None
            if has_place_layer:
                try:
                    layer_place = int(float(step.get("layer")))
                except Exception:
                    layer_place = 0
            # 1. 대상 찾기
            target = player if target_name == "player" else \
                     next((x for x in (npcs + objs) if getattr(x, 'name', '') == target_name), None)
            
            # 2. 신규 생성 로직 (대상을 못 찾았을 때)
            if not target and target_name != "player":
                pos = step.get("pos", [0, 0])
                if target_name in OBJ_ASSETS:
                    target = FieldItem(
                        target_name,
                        pos[0],
                        pos[1],
                        sprite_tilt=st_place if st_place is not None else 1.0,
                        height=h_place,
                        ysort_mode=ysort_place,
                        layer=layer_place,
                    )
                    objs.append(target)
                else:
                    ch_info = {}
                    if st_place is not None:
                        ch_info["sprite_tilt"] = st_place
                    if has_place_height:
                        ch_info["height"] = h_place
                    if has_place_ysort:
                        ch_info["ysort"] = ysort_place
                    if has_place_layer:
                        ch_info["layer"] = layer_place
                    if CHAR_ASSETS.get(target_name, {}).get("mask_nav"):
                        target = MaskWalkingCharacter(target_name, pos, ch_info)
                    else:
                        target = BaseCharacter(target_name, pos, ch_info)
                    try:
                        from char_behavior import attach_npc_from_entry
                        attach_npc_from_entry(
                            target,
                            {"name": target_name, "pos": list(pos)[:2]},
                        )
                    except Exception:
                        pass
                    npcs.append(target)
                print(f"[PLACE] {target_name} 생성됨")

            # 3. 실제 동작 (이동, 삭제, 페이드)
            if target:
                if st_place is not None and hasattr(target, "sprite_tilt"):
                    target.sprite_tilt = st_place
                if has_place_height and hasattr(target, "height"):
                    target.height = h_place
                if has_place_ysort and hasattr(target, "ysort_mode"):
                    target.ysort_mode = ysort_place
                if has_place_layer and hasattr(target, "layer"):
                    target.layer = layer_place
                if "dir" in step: target.direction = step["dir"]

                # [삭제 연출]
                if step.get("action") == "remove":
                    if step.get("appear") == "fade":
                        self.is_waiting_for_appear = True
                        self.is_busy = True 
                    else:
                        if target in objs: objs.remove(target)
                        elif target in npcs: npcs.remove(target)
                        self.next_step()
                
                # [등장 및 이동 연출]
                else:
                    new_pos = step.get("pos")
                    if new_pos:
                        target.pos = [float(new_pos[0]), float(new_pos[1])]
                        if hasattr(target, 'origin_pos'):
                            target.origin_pos = [float(new_pos[0]), float(new_pos[1])]
                        sm = getattr(target, "stop_moving", None)
                        if callable(sm):
                            sm()
                    
                    if step.get("appear") == "fade":
                        target.alpha = 0 
                        self.is_waiting_for_appear = True
                        self.is_busy = True
                    else:
                        target.alpha = 255
                        self.next_step()
            else:
                # 타겟도 없고 생성도 실패했다면 그냥 넘김
                self.next_step()

        elif s_type == "TUNE":
            # 이미 배치된 대상의 설정만 변경 (생성/이동 없음)
            target_name = step.get("target")
            target = player if target_name == "player" else \
                     next((x for x in (npcs + objs) if getattr(x, 'name', '') == target_name), None)
            if target:
                if "sprite_tilt" in step and hasattr(target, "sprite_tilt"):
                    try:
                        target.sprite_tilt = _clamp_sprite_tilt(step.get("sprite_tilt"))
                    except Exception:
                        pass
                if "height" in step and hasattr(target, "height"):
                    target.height = _clamp_draw_height(step.get("height"))
                if "ysort" in step and hasattr(target, "ysort_mode"):
                    target.ysort_mode = _normalize_ysort_mode(step.get("ysort"))
                if "layer" in step and hasattr(target, "layer"):
                    try:
                        target.layer = int(float(step.get("layer")))
                    except Exception:
                        pass
                if "visible" in step and hasattr(target, "is_visible"):
                    try:
                        target.is_visible = bool(step.get("visible"))
                    except Exception:
                        pass
                if "alpha" in step and hasattr(target, "alpha"):
                    try:
                        a = int(float(step.get("alpha")))
                        target.alpha = max(0, min(255, a))
                    except Exception:
                        pass
            self.next_step()

        elif s_type == "EFFECT":
            # 월드 이펙트: object_defs 키(name)의 path 애니. loop:false(기본)=1회 재생 후 제거.
            e_name = (step.get("name") or "").strip()
            if not e_name:
                self.next_step()
                return
            is_loop = step.get("loop", False)
            if isinstance(is_loop, str):
                is_loop = is_loop.strip().lower() not in ("0", "false", "f", "no", "n", "off")
            if step.get("action") == "remove":
                self.active_effects = [e for e in self.active_effects if e.name != e_name]
                self.next_step()
                return
            pos = _effect_pos_from_step(step, player=player, npcs=npcs, objs=objs)
            anchor = _effect_anchor_from_step(step)
            delay_raw = step.get("anim_delay_ms", step.get("frame_ms"))
            new_effect = Effect(
                e_name,
                pos[0],
                pos[1],
                loop=bool(is_loop),
                anim_delay_ms=delay_raw,
                anchor=anchor,
            )
            self.active_effects.append(new_effect)
            if _parse_effect_step_wait(step) and (not is_loop):
                self._effect_wait_ref = new_effect
            else:
                self.next_step()

        elif s_type == "ANIM_ONCE":
            # 지정 좌표 + object_defs 애니 1회 (옵션 없음). 재생 끝까지 wait.
            if not self._spawn_anim_once(step):
                self.next_step()

        elif s_type == "CARRY":
            # 들기/내려놓기 — Player.begin_carry_* (상호작용과 동일 fly 연출)
            self._execute_carry_step(step, player, npcs, objs)

        elif s_type == "CHANGE":
            self._execute_change_step(step, player, npcs, objs)

        elif s_type == "LOOP_START":
            self.next_step()

        elif s_type == "LOOP_END":
            head = self._loop_end_to_head.get(self.step_idx)
            if head is not None:
                self.step_idx = head
                self.is_busy = False
                self.is_talking = False
                self._say_ui_fade_phase = None
            else:
                self.next_step()

        elif s_type == "SCREEN":
            # 화면을 덮는 이미지/음악/전환 오버레이
            action = (step.get("action") or "").strip().lower()
            transition = (step.get("transition") or "fade").strip().lower()
            bg = (step.get("bg") or "black").strip().lower()

            # remove: 현재 screen을 전환하면서 걷어냄
            if action == "remove":
                if self.active_screen:
                    self.active_screen["mode"] = "removing"
                    self.active_screen["transition"] = transition or self.active_screen.get("transition", "fade")
                    self.active_screen["t0"] = pygame.time.get_ticks()
                    self.active_screen["duration_ms"] = int(float(step.get("val", 0) or 0) * 1000) if step.get("val") else self.active_screen.get("duration_ms", 400)
                    self.active_screen["duration_ms"] = max(120, int(self.active_screen["duration_ms"] or 400))
                else:
                    self.next_step()
                return

            # show/update: 오버레이 생성/갱신
            pic = (step.get("picture") or "").strip()
            music = (step.get("music") or "").strip()
            text = step.get("text")

            # picture는 상대경로면 assets/images/screen 기준으로 보정
            if pic and not os.path.isabs(pic):
                # 이미 assets/... 로 시작하면 그대로, 아니면 screen 폴더로
                if not pic.replace("\\", "/").startswith("assets/"):
                    pic = os.path.join("assets", "images", "screen", pic)

            # 기본 duration (전환 시간). val이 있으면 전환+자동넘김에 같이 사용
            trans_ms = 400
            if step.get("val") is not None:
                try:
                    trans_ms = max(120, int(float(step.get("val")) * 1000))
                except:
                    trans_ms = 400

            # 이미지 로드
            img = None
            if pic:
                try:
                    img = pygame.image.load(pic).convert_alpha()
                except Exception as e:
                    print(f"[SCREEN] picture load failed: {pic} ({e})")

            now_t = pygame.time.get_ticks()
            # 이미 스크린이 떠 있는 상황에서 새로운 스크린이 오면, 스크린끼리 전환 상태(crossing)로 진입
            if self.active_screen and self.active_screen.get("mode") in ("showing", "holding"):
                prev_img = self.active_screen.get("img")
                self.active_screen = {
                    "img": img,  # 다음 스크린의 최종 이미지
                    "prev_img": prev_img,
                    "next_img": img,
                    "picture": pic,
                    "music": music,
                    "transition": transition or "fade",
                    "bg": bg,
                    "mode": "crossing",
                    "t0": now_t,
                    "duration_ms": trans_ms,
                    "text": text if text is not None else "",
                    "auto": bool(step.get("auto", False)),
                    "auto_ms": int(float(step.get("val", 0) or 0) * 1000) if step.get("auto") and step.get("val") is not None else None,
                }
            else:
                # 처음 켜질 때는 검은 바탕 위로 페이드 인
                self.active_screen = {
                    "img": img,
                    "picture": pic,
                    "music": music,
                    "transition": transition or "fade",
                    "bg": bg,
                    "mode": "showing",
                    "t0": now_t,
                    "duration_ms": trans_ms,
                    "text": text if text is not None else "",
                    "auto": bool(step.get("auto", False)),
                    "auto_ms": int(float(step.get("val", 0) or 0) * 1000) if step.get("auto") and step.get("val") is not None else None,
                }

            # 음악 재생(지정된 경우)
            if music:
                try:
                    if not os.path.isabs(music) and not music.replace("\\", "/").startswith("assets/"):
                        # 기본: assets/musics (프로젝트 표준)
                        cand = os.path.join("assets", "musics", music)
                        # 구형 호환: assets/music
                        if not os.path.isfile(resolve_asset_path(cand)):
                            cand = os.path.join("assets", "music", music)
                        music = resolve_asset_path(cand)
                    else:
                        music = resolve_asset_path(music)
                    if not os.path.isfile(music):
                        raise FileNotFoundError(music)
                    pygame.mixer.music.load(music)
                    pygame.mixer.music.play(-1)
                    self.active_screen["music"] = music
                except Exception as e:
                    print(f"[SCREEN] music load/play failed: {music} ({e})")

            # SCREEN 자체는 즉시 다음 스텝으로 넘어가도 오버레이는 유지됨
            self.next_step()

        elif s_type == "OVERLAY_UI":
            self._apply_overlay_ui_step(step)
            self.next_step()

        elif s_type == "MUSIC_PLAY":
            if not self.music:
                self.next_step()
                return
            name = (step.get("music") or step.get("name") or "").strip()
            if not name:
                self.next_step()
                return
            try:
                fin = float(step.get("fade_in", step.get("fadein", 0)) or 0.0)
            except Exception:
                fin = 0.0
            try:
                vol = step.get("volume", None)
                if vol is not None and vol != "":
                    vol = float(vol)
            except Exception:
                vol = None
            loop = step.get("loop", False)
            q = step.get("queue", True)
            if isinstance(q, str):
                q = q.strip().lower() not in ("0", "false", "f", "no", "n", "off")
            self.music.play(
                name,
                fade_in_ms=int(max(0.0, fin) * 1000.0),
                loop=bool(loop),
                volume=vol,
                queue_after_current=bool(q),
            )
            self.next_step()

        elif s_type == "MUSIC_STOP":
            if self.music:
                try:
                    fout = float(step.get("fade_out", step.get("fadeout", 0.2)) or 0.2)
                except Exception:
                    fout = 0.2
                self.music.stop(fade_out_ms=int(max(0.0, fout) * 1000.0))
            self.next_step()

        elif s_type == "MUSIC_END":
            if self.music:
                self.music.end_now()
            self.next_step()

        elif s_type == "MUSIC_PAUSE":
            if self.music:
                self.music.pause()
            self.next_step()

        elif s_type == "MUSIC_RESUME":
            if self.music:
                self.music.resume()
            self.next_step()


    def _check_completion(self, player, camera, npcs, objs, dt_sec=1.0 / 60.0):
        """현재 진행 중인 타입에 따라 완료되었는지 확인"""
        step = self.active_event[self.step_idx]
        s_type = step["type"]

        # [통합] 등장/퇴장(Fade) 연출 대기 처리
        if getattr(self, 'is_waiting_for_appear', False):
            target_name = step.get("target")
            target = player if target_name == "player" else \
                     next((x for x in (npcs + objs) if getattr(x, 'name', '') == target_name), None)
            
            if target:
                is_remove = (step.get("action") == "remove")
                try:
                    appear_sec = float(
                        step.get("appear_sec")
                        if step.get("appear_sec") is not None
                        else CONFIG.get("APPEAR_FADE_SEC", 0.85)
                    )
                except Exception:
                    appear_sec = 0.85
                appear_sec = max(0.05, float(appear_sec))
                delta = (255.0 / appear_sec) * max(0.0, float(dt_sec))
                # 1. 알파값 업데이트 (실시간 기준)
                if is_remove:
                    target.alpha = max(0, int(target.alpha) - int(round(delta)))
                else:
                    target.alpha = min(255, int(target.alpha) + int(round(delta)))
                
                # 2. 완료 체크
                if (not is_remove and target.alpha >= 255) or (is_remove and target.alpha <= 0):
                    if is_remove:
                        if target in objs: objs.remove(target)
                        elif target in npcs: npcs.remove(target)
                    self.is_waiting_for_appear = False
                    self.next_step()
            else:
                self.is_waiting_for_appear = False
                self.next_step()
            return

        if s_type in ("EFFECT", "ANIM_ONCE"):
            ref = getattr(self, "_effect_wait_ref", None)
            if ref is not None:
                if bool(getattr(ref, "is_done", False)) or ref not in self.active_effects:
                    self._effect_wait_ref = None
                    self.next_step()
            elif not self.active_effects:
                # wait 대상이 없으면(0프레임 등) 바로 진행
                self.next_step()
            return

        if s_type == "CARRY":
            item = getattr(self, "_carry_wait_item", None)
            if item is None:
                self.next_step()
                return
            if not getattr(item, "is_flying", False):
                self._carry_wait_item = None
                self.next_step()
            return

        if s_type == "MOVE":
            msg = getattr(self, "_move_sync_group", None)
            if msg:
                if int(self.step_idx or 0) != int(msg.get("base_idx", -1)):
                    self._move_sync_group = None
                else:
                    any_need = False
                    all_done = True
                    for ent in msg.get("entries") or []:
                        tn = ent.get("target_name")
                        target = player if tn == "player" else next(
                            (x for x in (npcs + objs) if getattr(x, "name", "") == tn), None
                        )
                        wpsi = ent.get("wps") or []
                        if not target or not wpsi:
                            continue
                        any_need = True
                        try:
                            final = wpsi[-1]
                            fx, fy = float(final[0]), float(final[1])
                        except (TypeError, ValueError, IndexError):
                            all_done = False
                            continue
                        pending = getattr(target, "event_waypoints", None)
                        if isinstance(pending, list) and len(pending) > 0:
                            all_done = False
                            continue
                        path = getattr(target, "path", None)
                        if path:
                            all_done = False
                            continue
                        try:
                            if math.hypot(float(target.pos[0]) - fx, float(target.pos[1]) - fy) >= 10:
                                all_done = False
                        except (TypeError, ValueError):
                            all_done = False
                    if any_need and all_done:
                        for ent in msg.get("entries") or []:
                            tn = ent.get("target_name")
                            target = player if tn == "player" else next(
                                (x for x in (npcs + objs) if getattr(x, "name", "") == tn), None
                            )
                            if not target:
                                continue
                            bi = ent.get("step_i")
                            try:
                                bi = int(bi)
                            except (TypeError, ValueError):
                                bi = int(self.step_idx or 0)
                            k = (id(target), bi)
                            if k in self._restore_speed_after_move:
                                try:
                                    target.event_speed_mul = self._restore_speed_after_move.pop(k)
                                except Exception:
                                    self._restore_speed_after_move.pop(k, None)
                            _event_finish_move_target(target)
                        cnt = int(msg.get("count") or 0)
                        self.step_idx += max(1, cnt)
                        self.is_busy = False
                        self.is_talking = False
                        self._say_ui_fade_phase = None
                        self._move_sync_group = None
                    return

            par = step.get("parallel")
            if isinstance(par, (list, tuple)) and len(par) > 0:
                any_need = False
                all_done = True
                for frag in par:
                    if not isinstance(frag, dict):
                        continue
                    wps = _normalize_move_step_waypoints(frag)
                    if not wps:
                        continue
                    tn = frag.get("target")
                    target = player if tn == "player" else next((x for x in (npcs + objs) if x.name == tn), None)
                    if not target:
                        continue
                    any_need = True
                    final = wps[-1]
                    pending = getattr(target, "event_waypoints", None)
                    if isinstance(pending, list) and len(pending) > 0:
                        all_done = False
                        continue
                    path = getattr(target, "path", None)
                    if path:
                        all_done = False
                        continue
                    if math.dist(target.pos, final) >= 10:
                        all_done = False
                if any_need and all_done:
                    for frag in par:
                        if not isinstance(frag, dict):
                            continue
                        wps = _normalize_move_step_waypoints(frag)
                        if not wps:
                            continue
                        tn = frag.get("target")
                        target = player if tn == "player" else next((x for x in (npcs + objs) if x.name == tn), None)
                        if not target:
                            continue
                        k = (id(target), self.step_idx)
                        if k in self._restore_speed_after_move:
                            try:
                                target.event_speed_mul = self._restore_speed_after_move.pop(k)
                            except Exception:
                                self._restore_speed_after_move.pop(k, None)
                        _event_finish_move_target(target)
                    self.next_step()
                return

            target = player if step.get("target") == "player" else \
                     next((x for x in (npcs + objs) if x.name == step["target"]), None)
            wps = _normalize_move_step_waypoints(step)
            if not wps or not target:
                return
            final = wps[-1]
            pending = getattr(target, "event_waypoints", None)
            if isinstance(pending, list) and len(pending) > 0:
                return
            path = getattr(target, "path", None)
            if path:
                return
            if math.dist(target.pos, final) < 10:
                _event_finish_move_target(target)
                # MOVE 속도 배수 복구
                k = (id(target), self.step_idx)
                if k in self._restore_speed_after_move:
                    try:
                        target.event_speed_mul = self._restore_speed_after_move.pop(k)
                    except Exception:
                        self._restore_speed_after_move.pop(k, None)
                self.next_step()

        elif s_type in ("WAIT", "INTERVAL"):
            if pygame.time.get_ticks() >= self.wait_timer:
                self.next_step()

        elif s_type in ("ANIM", "ACTION_ANIM"):
            if self._anim_wait_end_ms and pygame.time.get_ticks() >= int(self._anim_wait_end_ms):
                self._anim_wait_end_ms = 0
                self.next_step()

        elif s_type == "ZOOM":
            raw_tgt = (step.get("target") or "").strip()
            lt = raw_tgt.lower()
            cam_aliases = ("", "camera", "cam", "screen", "global", "__global__")
            if lt in cam_aliases:
                return
            ins = step.get("instant")
            instant = ins is True or (
                isinstance(ins, str) and ins.strip().lower() in ("1", "true", "yes", "on")
            )
            if instant:
                return
            ent = (
                player
                if lt == "player"
                else next(
                    (x for x in (npcs + objs) if getattr(x, "name", "") == raw_tgt),
                    None,
                )
            )
            if not ent:
                self.next_step()
                return
            try:
                zc = float(getattr(ent, "event_entity_zoom", 1.0))
                zt = float(getattr(ent, "event_entity_zoom_target", 1.0))
            except Exception:
                self.next_step()
                return
            eps = max(0.008, abs(zt) * 0.02)
            if abs(zc - zt) <= eps:
                ent.event_entity_zoom = zt
                self.next_step()

        # SAY는 main.py에서 클릭 시 next_step()을 직접 호출해줌
        # FADEOUT/FADEIN은 논블로킹(즉시 next_step) — val은 초(duration), 보간은 update() 상단

        # SCREEN remove가 진행 중이면 여기서 완료 처리(오버레이 제거)
        if self.active_screen and self.active_screen.get("mode") == "removing":
            now = pygame.time.get_ticks()
            dur = max(120, int(self.active_screen.get("duration_ms") or 400))
            if now - int(self.active_screen.get("t0") or now) >= dur:
                # SCREEN 스텝이 자체 음악을 재생한 경우에만 정리.
                # (이벤트의 MUSIC_PLAY로 재생 중인 BGM까지 꺼지지 않도록)
                if self.active_screen.get("music"):
                    try:
                        pygame.mixer.music.fadeout(200)
                    except Exception:
                        pass
                self.active_screen = None
                self.next_step()

    def next_step(self):
        self.step_idx += 1
        self.is_busy = False
        self.is_talking = False
        self._say_ui_fade_phase = None

    def _trigger_event_escape(self):
        """탈출: end(즉시 종료) 또는 break_loop(루프 뒤 연출로 점프)."""
        if not self.active_event:
            return
        if self._escape_action == "lock":
            return
        # 진행 중인 MOVE 속도 배수는 어떤 방식으로든 빠져나갈 때 복구
        self._restore_all_move_speed_overrides()
        self._move_sync_group = None

        if getattr(self, "is_waiting_for_appear", False):
            self.is_waiting_for_appear = False
        self.is_busy = False
        self.is_talking = False
        self._say_ui_fade_phase = None
        self._followers = []
        # 탈출 시에는 이벤트 연출을 전부 끄고 스냅샷 복구(end_event)가 되도록 틸트/쉬어 명령 제거
        self.tilt_control = None
        self.shear_control = None
        self.world_zoom_step_speed = None
        self.world_zoom_timed = None
        if self._escape_action == "break_loop":
            j = self._escape_jump_index()
            if j is not None:
                self.step_idx = max(0, min(len(self.active_event), j))
                return

        # 기본: 즉시 종료(end)
        if self._end_zoom is not None and self._last_camera:
            self._last_camera.target_zoom = float(self._end_zoom)
        self.active_screen = None
        # 이벤트 강제 종료 시에도 BGM은 유지 (MUSIC_STOP/END가 있을 때만 끈다)
        self.step_idx = len(self.active_event)
        self.end_event()

    def try_escape_click(self, button):
        if not self.active_event or self._escape_mode != "click":
            return False
        if self._escape_action == "lock":
            return False
        if button != 1:
            return False
        self._trigger_event_escape()
        return True

    def try_escape_key(self, key):
        if not self.active_event or self._escape_mode != "key":
            return False
        if self._escape_action == "lock":
            return False
        if self._escape_key_pygame is None or key != self._escape_key_pygame:
            return False
        self._trigger_event_escape()
        return True

    def _apply_event_result_to_save(self, results, event_id=None):
        """이벤트 result dict → flow.save_data (end_event·CALL_EVENT 복귀 공통)."""
        if not results or not getattr(self, "flow", None):
            return
        eid = event_id or self.active_event_id
        new_prog = results.get("mainprogress", None)
        if new_prog is not None and str(new_prog) != "":
            self.flow.save_data["mainprogress"] = new_prog
            print(f"[진행도 변경] -> {new_prog}")
        if "add_laugh_point" in results:
            points_to_add = results["add_laugh_point"]
            current_points = self.flow.save_data.get("laugh_point", 0)
            self.flow.save_data["laugh_point"] = current_points + points_to_add
            print(f"[포인트 획득] +{points_to_add} (총: {self.flow.save_data['laugh_point']})")
        for rk, rv in results.items():
            if rk in ("mainprogress", "add_laugh_point", "gamestart"):
                continue
            if rv is None or (isinstance(rv, str) and str(rv).strip() == ""):
                continue
            self.flow.save_data[rk] = rv
            print(f"[세이브 갱신] {rk} = {rv}")
        if eid:
            print(f"[이벤트 종료] ID: {eid}")

    def end_event(self):
        # CALL_EVENT 로 호출한 하위 이벤트 종료 → result 반영 후 부모로 복귀
        if self._event_call_stack:
            if self.active_event_result:
                self._apply_event_result_to_save(
                    self.active_event_result, self.active_event_id
                )
            frame = self._event_call_stack.pop()
            self._fragment_call_depth = max(0, self._fragment_call_depth - 1)
            if self._fragment_call_depth <= 0:
                self._fragment_call_set = set()
            self.active_event = frame["event_list"]
            self.active_event_id = frame["event_id"]
            self.active_event_result = frame["result"]
            self.step_idx = int(frame["return_idx"])
            self.is_busy = False
            self.is_talking = False
            self._say_ui_fade_phase = None
            self._loop_end_to_head, self._loop_pairs = _parse_loop_jump_table(self.active_event)
            self._event_skip_depth = 0
            print(f"[CALL_EVENT] return -> {self.active_event_id}")
            return

        ended_id = self.active_event_id
        for ent in getattr(self, "_active_entities", []) or []:
            try:
                ent.event_entity_zoom = 1.0
                ent.event_entity_zoom_target = 1.0
                ent.event_entity_zoom_timed = None
            except Exception:
                pass
            try:
                ent.event_waypoints = None
            except Exception:
                pass
        if self._end_zoom is not None and self._last_camera:
            self._last_camera.target_zoom = float(self._end_zoom)
        self._restore_all_move_speed_overrides()
        self._followers = []
        self._move_sync_group = None
        if ended_id and self.active_event_result:
            self._apply_event_result_to_save(self.active_event_result, ended_id)

        self.last_ended_event_id = ended_id
        try:
            self._ui_overlays = [o for o in (self._ui_overlays or []) if o.get("persist")]
        except Exception:
            self._ui_overlays = []
        # 2. 상태 초기화
        self.active_event = None
        self.active_event_id = None
        self.active_event_result = None
        self._is_sync_event = False
        self.is_busy = False
        self.is_talking = False
        self._say_ui_fade_phase = None
        self._say_bubble = None
        self._emote_overlay = None
        self._effect_wait_ref = None
        self.active_effects = []
        self._carry_wait_item = None
        snap = getattr(self, "field_tilt_snapshot", None)
        tc_end = getattr(self, "tilt_control", None)
        sc_end = getattr(self, "shear_control", None)
        # 마지막 스텝이 TILT면 tilt_control이 잡힌 채로 종료되므로, 스냅샷 복구는 틸트 명령이 없을 때만.
        if snap is not None and not isinstance(tc_end, dict):
            self.pending_field_tilt_restore = snap
        self.field_tilt_snapshot = None
        if not isinstance(tc_end, dict):
            self.tilt_control = None
        if not isinstance(sc_end, dict):
            self.shear_control = None
        self.world_zoom_step_speed = None
        self.world_zoom_timed = None
        # 기본 동작: 이벤트가 끝나면 커서는 다시 보이게 복구.
        # 단, CURSOR_VISIBLE에 persist:true가 지정되면 상태를 유지한다.
        if not bool(getattr(self, "_cursor_visible_persist", False)):
            self.cursor_visible = True

    def draw_screen_overlay(self, screen: pygame.Surface):
        """SCREEN 스텝 오버레이를 게임 화면 위에 렌더링."""
        if not self.active_screen:
            return
        info = self.active_screen
        img = info.get("img")
        transition = (info.get("transition") or "fade").strip().lower()
        bg = (info.get("bg") or "black").strip().lower()
        mode = info.get("mode") or "showing"
        t0 = int(info.get("t0") or pygame.time.get_ticks())
        dur = max(120, int(info.get("duration_ms") or 400))
        now = pygame.time.get_ticks()
        p = min(1.0, max(0.0, (now - t0) / dur))
        if mode == "removing":
            p = 1.0 - p

        # 배경 처리
        # - bg="black"(기본): 기존처럼 검은 배경으로 화면을 덮은 뒤 이미지를 표시
        # - bg="keep": 게임 화면을 유지한 채 이미지만 얹기(투명 PNG 로고용)
        w, h = screen.get_size()
        if bg != "keep":
            back = pygame.Surface((w, h), pygame.SRCALPHA)
            back.fill((0, 0, 0, 255))

            # 스크린 사이 전환(crossing) 또는 보여주기(showing)일 때는 검은 바탕을 항상 완전 불투명으로 유지
            # 제거(removing)일 때만 검은 바탕의 알파를 낮춰가며 게임 화면을 드러낸다.
            if mode in ("showing", "crossing", "holding"):
                screen.blit(back, (0, 0))
            else:  # removing
                back.set_alpha(int(255 * p))
                screen.blit(back, (0, 0))

        # 이미지가 있으면 화면에 맞춰 비율 유지 스케일
        def blit_scaled_center(image, alpha=255, clip_p=None):
            if not image:
                return
            iw, ih = image.get_size()
            if iw <= 0 or ih <= 0:
                return
            scale = min(w / iw, h / ih)
            nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
            s_img = pygame.transform.scale(image, (nw, nh)) if (nw, nh) != (iw, ih) else image
            rect = s_img.get_rect(center=(w // 2, h // 2))
            try:
                s_img = s_img.copy()
                s_img.set_alpha(int(alpha))
            except:
                pass
            if clip_p is not None:
                ww = int(rect.width * max(0.0, min(1.0, clip_p)))
                if ww > 0:
                    screen.blit(s_img, rect, area=pygame.Rect(0, 0, ww, rect.height))
            else:
                screen.blit(s_img, rect)

        if mode == "crossing":
            prev_img = info.get("prev_img")
            next_img = info.get("next_img") or img
            if transition in ("fade", "dissolve"):
                # 이전 스크린 -> 다음 스크린 크로스페이드 (검은 바탕은 항상 유지)
                blit_scaled_center(prev_img, alpha=255 * (1.0 - p))
                blit_scaled_center(next_img, alpha=255 * p)
            elif transition == "wipe":
                # 이전 스크린 전체 위에 다음 스크린을 좌->우로 와이프
                blit_scaled_center(prev_img, alpha=255)
                blit_scaled_center(next_img, alpha=255, clip_p=p)
            else:
                blit_scaled_center(prev_img, alpha=255 * (1.0 - p))
                blit_scaled_center(next_img, alpha=255 * p)

            # 전환 완료 시 다음 스크린으로 확정
            if (now - t0) >= dur:
                self.active_screen = {
                    "img": next_img,
                    "picture": info.get("picture"),
                    "music": info.get("music"),
                    "transition": transition,
                    "bg": bg,
                    "mode": "holding",  # 완전히 켜진 상태
                    "t0": now,
                    "duration_ms": dur,
                    "text": info.get("text") or "",
                    "auto": info.get("auto", False),
                    "auto_ms": info.get("auto_ms"),
                }
                info = self.active_screen
                img = info.get("img")

        elif mode in ("showing", "holding"):
            # 켜질 때는 이미지가 검은 바탕 위에서 서서히 나타남(showing), holding은 완전히 표시된 상태
            if mode == "showing":
                alpha = 255 * p
            else:
                alpha = 255
            if transition == "wipe":
                blit_scaled_center(img, alpha=255, clip_p=p if mode == "showing" else 1.0)
            else:
                blit_scaled_center(img, alpha=alpha)

        else:  # removing
            # 제거 시에는 검은 바탕과 이미지 모두 알파 p로 줄이며 게임 화면을 드러냄
            if transition == "wipe":
                blit_scaled_center(img, alpha=255, clip_p=p)
            else:
                blit_scaled_center(img, alpha=255 * p)

        # 텍스트(옵션): 간단히 하단 중앙
        txt = info.get("text") or ""
        if txt:
            try:
                font = pygame.font.SysFont("malgungothic", 22)
            except:
                font = pygame.font.SysFont("arial", 22)
            pad = 16
            box = pygame.Surface((w, 80), pygame.SRCALPHA)
            box.fill((0, 0, 0, int(160 * p)))
            screen.blit(box, (0, h - 80))
            t_surf = font.render(str(txt), True, (255, 255, 255))
            screen.blit(t_surf, (pad, h - 60))

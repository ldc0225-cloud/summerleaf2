import pygame, os, math, uuid
import heapq
from collections import deque, OrderedDict

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
    fade_alpha_delta,
    parse_camera_step,
    parse_rotate3d_step,
    parse_shear_step,
    parse_tilt_step,
    parse_zoom_step,
    timed_effect_finished,
    timed_effect_init,
    timed_effect_value,
    visual_smooth_step,
)

# --- global image caches (reduce duplicate loads, critical for 1GB devices) ---
_IMG_CACHE = OrderedDict()   # abs_path -> pygame.Surface (LRU)
_ANIM_CACHE = OrderedDict()  # norm_dir_path -> [pygame.Surface, ...]
_CHAR_ANIM_CACHE = OrderedDict()  # (norm_dir, state, direction) -> [pygame.Surface, ...]
_IMG_CACHE_MAX = 2048
_ANIM_CACHE_MAX = 512

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

    def draw(self, screen, cam_x, cam_y, zoom=1.0, jump_shadow_mode=None, y_transform=None, x_offset_fn=None, sprite_perspective_q=None, shear_lod=False, x_scale_fn=None, x_shift_fn=None, pivot_xy=None, cam_angle_rad=0.0, mode7_ctx=None, view_w=None):
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
                    mode7_ctx=mode7_ctx,
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
        try:
            _IMG_CACHE.move_to_end(p)
        except Exception:
            pass
        return img
    try:
        raw = pygame.image.load(p)
        try:
            img = raw.convert_alpha()
        except Exception:
            img = raw.convert()
    except Exception:
        return None
    _IMG_CACHE[p] = img
    try:
        _IMG_CACHE.move_to_end(p)
    except Exception:
        pass
    while len(_IMG_CACHE) > _IMG_CACHE_MAX:
        try:
            _IMG_CACHE.popitem(last=False)
        except Exception:
            break
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
                    mode7_ctx=None,
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
        try:
            _ANIM_CACHE.move_to_end(d)
        except Exception:
            pass
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
    try:
        _ANIM_CACHE.move_to_end(d)
    except Exception:
        pass
    while len(_ANIM_CACHE) > _ANIM_CACHE_MAX:
        try:
            _ANIM_CACHE.popitem(last=False)
        except Exception:
            break
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
        try:
            _CHAR_ANIM_CACHE.move_to_end(cache_key)
        except Exception:
            pass
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
    try:
        _CHAR_ANIM_CACHE.move_to_end(cache_key)
    except Exception:
        pass
    while len(_CHAR_ANIM_CACHE) > _ANIM_CACHE_MAX:
        try:
            _CHAR_ANIM_CACHE.popitem(last=False)
        except Exception:
            break
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
    """
    Scale + perspective-squash with caching (best-effort).

    SPRITE_SCALE_STEP (원근 크기 점프 관련):
      >0 이면 zoom 을 그 간격으로 양자화 → 예: 0.1 이면 배율이 10% 단위로만 바뀌어
      가까이 올수록 탁탁 커지는 느낌이 남. 0 이면 픽셀 크기만 반올림(가장 연속적).
    SPRITE_SCALE_SMOOTH: 외곽 보간(smoothscale). 크기 점프와 무관. 기본 False(nearest).
    """
    if image is None:
        return None
    try:
        step = float(CONFIG.get("SPRITE_SCALE_STEP", 0.0) or 0.0)
    except Exception:
        step = 0.0
    step = max(0.0, min(0.5, step))
    try:
        z_raw = float(eff_zoom)
    except Exception:
        z_raw = 1.0
    if step > 1e-9:
        try:
            zq = round(round(z_raw / step) * step, 4)
        except Exception:
            zq = z_raw
    else:
        zq = z_raw
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
    try:
        use_smooth = bool(CONFIG.get("SPRITE_SCALE_SMOOTH", False))
    except Exception:
        use_smooth = False
    key = ("spr", id(image), sw, sh, pq, st, 1 if use_smooth else 0)
    got = _sprite_cache_get(key)
    if got is not None:
        return got
    if (sw, sh) != (iw, ih):
        try:
            if use_smooth:
                scaled = pygame.transform.smoothscale(image, (sw, sh))
            else:
                scaled = pygame.transform.scale(image, (sw, sh))
        except Exception:
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


# --- vertical top-anchored shear (bg/mask) — main.py 와 동일 공식, dx 병합으로 blit 횟수 축소 ---
_VERTICAL_TOP_SHEAR_PLAN_CACHE = OrderedDict()
_VERTICAL_TOP_SHEAR_PLAN_MAX = 64


def vertical_top_shear_merged_plan(surface_h: int, shear_px: int, slice_h: int):
    """round((1 - yy/h) * shear) 슬라이스 계획. 연속 동일 dx 행은 blit 1회로 병합."""
    try:
        sh = int(surface_h)
        spx = int(shear_px)
        sh_slice = int(slice_h)
    except Exception:
        return ()
    sh = max(0, sh)
    spx = max(0, spx)
    sh_slice = max(1, min(64, sh_slice))
    key = (sh, spx, sh_slice)
    cached = _VERTICAL_TOP_SHEAR_PLAN_CACHE.get(key)
    if cached is not None:
        try:
            _VERTICAL_TOP_SHEAR_PLAN_CACHE.move_to_end(key)
        except Exception:
            pass
        return cached
    raw = []
    for yy in range(0, sh, sh_slice):
        hh = min(sh_slice, sh - yy)
        rel = 0.0 if sh <= 1 else (yy / float(sh))
        dxs = int(round((1.0 - rel) * float(spx)))
        raw.append((yy, hh, dxs))
    if not raw:
        plan = ()
    else:
        merged = []
        i = 0
        n = len(raw)
        while i < n:
            yy0, hh0, dx0 = raw[i]
            total_h = hh0
            j = i + 1
            while j < n and raw[j][2] == dx0:
                total_h += raw[j][1]
                j += 1
            merged.append((yy0, total_h, dx0))
            i = j
        plan = tuple(merged)
    try:
        _VERTICAL_TOP_SHEAR_PLAN_CACHE[key] = plan
        _VERTICAL_TOP_SHEAR_PLAN_CACHE.move_to_end(key)
        while len(_VERTICAL_TOP_SHEAR_PLAN_CACHE) > _VERTICAL_TOP_SHEAR_PLAN_MAX:
            _VERTICAL_TOP_SHEAR_PLAN_CACHE.popitem(last=False)
    except Exception:
        pass
    return plan


def apply_vertical_top_shear(dst, src, shear_px, slice_h, *, plan=None, clear_dst=True):
    """배경/마스크용 상단 고정 선형 쉬어 — 시각 결과는 main 슬라이스 루프와 동일."""
    if dst is None or src is None:
        return dst
    try:
        sw = int(src.get_width())
        sh = int(src.get_height())
    except Exception:
        return dst
    if sw <= 0 or sh <= 0:
        return dst
    try:
        spx = int(shear_px)
    except Exception:
        spx = 0
    if spx <= 0:
        if clear_dst:
            try:
                dst.fill((0, 0, 0, 0))
            except Exception:
                pass
        try:
            dst.blit(src, (0, 0))
        except Exception:
            pass
        return dst
    try:
        sh_slice = int(slice_h)
    except Exception:
        sh_slice = 8
    sh_slice = max(1, min(64, sh_slice))
    if plan is None:
        plan = vertical_top_shear_merged_plan(sh, spx, sh_slice)
    if clear_dst:
        try:
            dst.fill((0, 0, 0, 0))
        except Exception:
            pass
    blit = dst.blit
    Rect = pygame.Rect
    for yy, hh, dxs in plan:
        try:
            blit(src, (dxs, yy), area=Rect(0, yy, sw, hh))
        except Exception:
            pass
    return dst


def vertical_top_shear_merged_plan_region(
    surface_h_full: int,
    shear_px: int,
    slice_h: int,
    row_start: int,
    row_end: int,
):
    """전체 높이 sh_full 기준 rel 공식으로 [row_start, row_end) 구간만 슬라이스·병합."""
    try:
        shf = int(surface_h_full)
        spx = int(shear_px)
        sh_slice = int(slice_h)
        r0 = int(row_start)
        r1 = int(row_end)
    except Exception:
        return ()
    shf = max(1, shf)
    spx = max(0, spx)
    sh_slice = max(1, min(64, sh_slice))
    r0 = max(0, min(shf, r0))
    r1 = max(r0, min(shf, r1))
    if r1 <= r0 or spx <= 0:
        return ()
    key = (shf, spx, sh_slice, r0, r1)
    cached = _VERTICAL_TOP_SHEAR_PLAN_CACHE.get(key)
    if cached is not None:
        try:
            _VERTICAL_TOP_SHEAR_PLAN_CACHE.move_to_end(key)
        except Exception:
            pass
        return cached
    raw = []
    for yy in range(r0, r1, sh_slice):
        hh = min(sh_slice, r1 - yy, shf - yy)
        if hh <= 0:
            break
        rel = 0.0 if shf <= 1 else (yy / float(shf))
        dxs = int(round((1.0 - rel) * float(spx)))
        raw.append((yy, hh, dxs))
    if not raw:
        plan = ()
    else:
        merged = []
        i = 0
        n = len(raw)
        while i < n:
            yy0, hh0, dx0 = raw[i]
            total_h = hh0
            j = i + 1
            while j < n and raw[j][2] == dx0:
                total_h += raw[j][1]
                j += 1
            merged.append((yy0, total_h, dx0))
            i = j
        plan = tuple(merged)
    try:
        _VERTICAL_TOP_SHEAR_PLAN_CACHE[key] = plan
        _VERTICAL_TOP_SHEAR_PLAN_CACHE.move_to_end(key)
        while len(_VERTICAL_TOP_SHEAR_PLAN_CACHE) > _VERTICAL_TOP_SHEAR_PLAN_MAX:
            _VERTICAL_TOP_SHEAR_PLAN_CACHE.popitem(last=False)
    except Exception:
        pass
    return plan


def apply_vertical_top_shear_region(
    dst,
    src,
    shear_px,
    slice_h,
    row_start,
    row_end,
    surface_h_full,
    *,
    plan=None,
    clear_dst=True,
):
    """전체 맵 쉬어의 [row_start,row_end) 부분만 dst(높이=row_end-row_start)에 기록."""
    if dst is None or src is None:
        return dst
    try:
        sw = int(src.get_width())
        shf = int(surface_h_full)
        r0 = int(row_start)
        r1 = int(row_end)
        spx = int(shear_px)
    except Exception:
        return dst
    if sw <= 0 or shf <= 0 or spx <= 0 or r1 <= r0:
        return dst
    r0 = max(0, min(shf, r0))
    r1 = max(r0, min(shf, r1))
    strip_h = r1 - r0
    try:
        sh_slice = int(slice_h)
    except Exception:
        sh_slice = 8
    sh_slice = max(1, min(64, sh_slice))
    if plan is None:
        plan = vertical_top_shear_merged_plan_region(shf, spx, sh_slice, r0, r1)
    if clear_dst:
        try:
            dst.fill((0, 0, 0, 0))
        except Exception:
            pass
    blit = dst.blit
    Rect = pygame.Rect
    for yy, hh, dxs in plan:
        try:
            blit(src, (dxs, yy - r0), area=Rect(0, yy, sw, hh))
        except Exception:
            pass
    return dst


# --- 3D_ROTATE / Mode7 (레이싱·원근 필드 전용) ---
# 사다리꼴(apply_rotate3d) 경로는 폐기. 배경·엔티티·클릭은 모두 Mode7 ctx 를 공유한다.


def rotate3d_config_from_data():
    """3D_ROTATE CONFIG — Mode7 파라미터만 (data.py ROTATE3D_*)."""
    try:
        horizon_frac = float(CONFIG.get("ROTATE3D_HORIZON_FRAC", 0.30) or 0.30)
    except (TypeError, ValueError):
        horizon_frac = 0.30
    try:
        cam_h = float(CONFIG.get("ROTATE3D_CAM_H", 60.0) or 60.0)
    except (TypeError, ValueError):
        cam_h = 60.0
    try:
        near = float(CONFIG.get("ROTATE3D_NEAR", 8.0) or 8.0)
    except (TypeError, ValueError):
        near = 8.0
    try:
        depth_mul = float(CONFIG.get("ROTATE3D_DEPTH_MUL", 165.0) or 165.0)
    except (TypeError, ValueError):
        depth_mul = 165.0
    try:
        lateral_mul = float(CONFIG.get("ROTATE3D_LATERAL_MUL", 1.05) or 1.05)
    except (TypeError, ValueError):
        lateral_mul = 1.05
    try:
        camera_back = float(CONFIG.get("ROTATE3D_CAMERA_BACK", 26.0) or 26.0)
    except (TypeError, ValueError):
        camera_back = 26.0
    try:
        base_heading = float(CONFIG.get("ROTATE3D_BASE_HEADING", math.pi * 0.5) or (math.pi * 0.5))
    except (TypeError, ValueError):
        base_heading = math.pi * 0.5
    try:
        scale_min = float(CONFIG.get("ROTATE3D_SPRITE_SCALE_MIN", 0.05) or 0.05)
    except (TypeError, ValueError):
        scale_min = 0.05
    try:
        scale_max = float(CONFIG.get("ROTATE3D_SPRITE_SCALE_MAX", 8.0) or 8.0)
    except (TypeError, ValueError):
        scale_max = 8.0
    try:
        scale_on = bool(CONFIG.get("ROTATE3D_SPRITE_SCALE_ENABLED", True))
    except Exception:
        scale_on = True

    def _rgb3(key, default):
        raw = CONFIG.get(key, default)
        try:
            if isinstance(raw, (list, tuple)) and len(raw) >= 3:
                return (
                    max(0, min(255, int(raw[0]))),
                    max(0, min(255, int(raw[1]))),
                    max(0, min(255, int(raw[2]))),
                )
        except (TypeError, ValueError):
            pass
        return default

    try:
        sky_path = str(CONFIG.get("ROTATE3D_SKY_PANORAMA", "") or "").strip()
    except Exception:
        sky_path = ""
    try:
        sky_yaw = float(CONFIG.get("ROTATE3D_SKY_PANORAMA_YAW_OFFSET", 0.0) or 0.0)
    except (TypeError, ValueError):
        sky_yaw = 0.0
    try:
        sky_fov = float(CONFIG.get("ROTATE3D_SKY_FOV_RAD", 1.2) or 1.2)
    except (TypeError, ValueError):
        sky_fov = 1.2
    try:
        player_x_frac = float(CONFIG.get("ROTATE3D_PLAYER_SCREEN_X_FRAC", 0.5) or 0.5)
    except (TypeError, ValueError):
        player_x_frac = 0.5
    return {
        "horizon_frac": max(0.0, min(0.50, float(horizon_frac))),
        "cam_h": max(1.0, float(cam_h)),
        "near": max(0.5, float(near)),
        "depth_mul": max(1.0, float(depth_mul)),
        "lateral_mul": max(0.05, float(lateral_mul)),
        "camera_back": max(0.0, float(camera_back)),
        "base_heading": float(base_heading),
        "sprite_scale_enabled": bool(scale_on),
        "sprite_scale_min": max(0.05, min(8.0, float(scale_min))),
        "sprite_scale_max": max(0.05, min(8.0, float(scale_max))),
        # 지평선 위/아래 빈 공간 + 360 하늘
        "sky_color": _rgb3("ROTATE3D_SKY_COLOR", (135, 206, 235)),
        "ground_fill_color": _rgb3("ROTATE3D_GROUND_FILL_COLOR", (0, 0, 0)),
        "sky_panorama": sky_path,
        "sky_panorama_yaw_offset": float(sky_yaw),
        "sky_fov_rad": max(0.2, min(math.pi * 1.5, float(sky_fov))),
        "player_screen_x_frac": max(0.05, min(0.95, float(player_x_frac))),
    }


def rotate3d_mode7_build_ctx(
    cfg,
    strength_01,
    view_w,
    view_h,
    cam_x,
    cam_y,
    cam_angle_rad,
    *,
    ref_forward=None,
    player_wx=None,
    player_wy=None,
):
    """
    Mode7 공통 파라미터. 배경·엔티티·클릭이 같은 식만 쓴다.

      row = sy - horizon
      p   = CAM_H / (row + NEAR)
      depth = p * DEPTH_MUL
      lat_scale = p * LATERAL_MUL

    위쪽일수록 p↓ → 맵이 멀고 작게. sy_shift / 가로 고정 같은 후처리 없음.
    PIVOT_FIT 은 DEPTH_MUL 만 조정해 발이 화면 하단 빌보드에 맞게 함.
    """
    try:
        w = max(1, int(view_w))
        h = max(1, int(view_h))
        s = max(0.0, min(1.0, float(strength_01)))
        cx = float(cam_x)
        cy = float(cam_y)
        ang = float(cam_angle_rad)
    except (TypeError, ValueError):
        return None
    hf = float(cfg.get("horizon_frac", 0.30))
    horizon = int(round(float(h) * hf * s))
    horizon = max(0, min(h - 2, horizon))
    cam_h = float(cfg.get("cam_h", 60.0))
    near = float(cfg.get("near", 8.0))
    depth_mul = float(cfg.get("depth_mul", 165.0)) * max(s, 1e-6)
    lateral_mul = float(cfg.get("lateral_mul", 1.05))
    fwd_x = math.cos(ang)
    fwd_y = math.sin(ang)
    lat_x = -fwd_y
    lat_y = fwd_x
    if ref_forward is None:
        try:
            ref_forward = float(cfg.get("camera_back", 26.0)) * s
        except (TypeError, ValueError):
            ref_forward = 26.0 * s
    ref_forward = max(float(near), float(ref_forward))

    try:
        pad = float(CONFIG.get("ROTATE3D_PLAYER_BOTTOM_PAD", 18) or 18)
    except (TypeError, ValueError):
        pad = 18.0
    pad = max(0.0, pad)
    # 플레이어 발·Mode7 가로 원점(view_cx). 0.5=중앙, ~0.33=좌측 1/3 → 전방 트랙이 오른쪽에 넓게.
    try:
        if isinstance(cfg, dict) and cfg.get("player_screen_x_frac") is not None:
            x_frac = float(cfg.get("player_screen_x_frac"))
        else:
            x_frac = float(CONFIG.get("ROTATE3D_PLAYER_SCREEN_X_FRAC", 0.5) or 0.5)
    except (TypeError, ValueError):
        x_frac = 0.5
    x_frac = max(0.05, min(0.95, float(x_frac)))
    player_sx = float(w) * x_frac
    player_sy = float(h) - pad
    view_cx = float(player_sx)  # 배경·스프라이트 lateral 원점 = 플레이어 화면 X

    try:
        pivot_fit = bool(CONFIG.get("ROTATE3D_PIVOT_FIT_PLAYER", True))
    except Exception:
        pivot_fit = True
    if pivot_fit and cam_h > 1e-6 and ref_forward > 1e-6:
        denom = float(player_sy) - float(horizon) + float(near)
        if denom > 1.0:
            depth_mul = float(denom) * float(ref_forward) / float(cam_h)
            depth_mul = max(1.0, min(2000.0, depth_mul))

    return {
        "mode7": True,
        "w": w,
        "h": h,
        "strength": s,
        "horizon": horizon,
        "cam_h": cam_h,
        "near": near,
        "depth_mul": depth_mul,
        "lateral_mul": lateral_mul,
        "cam_x": cx,
        "cam_y": cy,
        "cam_angle": ang,
        "fwd_x": fwd_x,
        "fwd_y": fwd_y,
        "lat_x": lat_x,
        "lat_y": lat_y,
        "ref_forward": float(ref_forward),
        "player_sx": float(player_sx),
        "player_sy": float(player_sy),
        "view_cx": float(view_cx),  # Mode7 가로 투영 중심(=player_sx)
        "player_screen_x_frac": float(x_frac),
        "sprite_scale_enabled": bool(cfg.get("sprite_scale_enabled", True)),
        "sprite_scale_min": float(cfg.get("sprite_scale_min", 0.05)),
        "sprite_scale_max": float(cfg.get("sprite_scale_max", 8.0)),
    }


def rotate3d_mode7_forward(wx, wy, ctx):
    """카메라→월드점 forward 깊이(월드 단위)."""
    if not ctx:
        return 0.0
    try:
        dx = float(wx) - float(ctx.get("cam_x", 0.0))
        dy = float(wy) - float(ctx.get("cam_y", 0.0))
        return dx * float(ctx.get("fwd_x", 1.0)) + dy * float(ctx.get("fwd_y", 0.0))
    except (TypeError, ValueError):
        return 0.0


def rotate3d_mode7_cull_pads():
    """
    Mode7 스프라이트 컬링 패딩 (data.ROTATE3D_CULL_*).
    bounds-aware cull 이 화면 가장자리·하단 여유에 사용한다.
    """
    try:
        pad = float(CONFIG.get("ROTATE3D_CULL_PAD_PX", 64) or 64)
    except (TypeError, ValueError):
        pad = 64.0
    pad = max(0.0, min(256.0, pad))
    try:
        below_pad = float(CONFIG.get("ROTATE3D_CULL_BELOW_PAD_PX", 220) or 220)
    except (TypeError, ValueError):
        below_pad = 220.0
    below_pad = max(pad, min(480.0, below_pad))
    return pad, below_pad


def rotate3d_mode7_billboard_bounds(sx, sy, img_w, img_h, *, anchor="feet"):
    """
    Mode7 빌보드 화면 사각형 (left, top, right, bottom).
    feet: 하단 중앙 앵커(위쪽으로 그림). center: 중심 앵커.
    """
    iw = max(0.0, float(img_w))
    ih = max(0.0, float(img_h))
    sx = float(sx)
    sy = float(sy)
    a = (anchor or "feet").strip().lower()
    if a in ("center", "centre", "mid", "middle", "head"):
        left = sx - iw * 0.5
        top = sy - ih * 0.5
    else:
        # feet / foot / ground / bottom
        left = sx - iw * 0.5
        top = sy - ih
    return left, top, left + iw, top + ih


def rotate3d_mode7_bounds_visible(sx, sy, img_w, img_h, ctx, *, anchor="feet"):
    """
    스프라이트 화면 사각형이 (패딩된) 뷰와 겹치면 True.

    발점이 지평선·화면 밖이어도 몸통이 남아 있으면 그린다.
    → 큰 mountain/tree 가 거리·각도에 따라 통째로 팝인/아웃 하던 문제 완화.
    지평선(horizon)으로 발을 자르지 않는다(빌보드는 하늘 띠로 올라가는 게 정상).
    """
    if not ctx:
        return True
    pad, below_pad = rotate3d_mode7_cull_pads()
    try:
        w = float(ctx.get("w", CONFIG.get("WIDTH", 640)) or 640)
        h = float(ctx.get("h", CONFIG.get("HEIGHT", 480)) or 480)
    except (TypeError, ValueError):
        w = float(CONFIG.get("WIDTH", 640) or 640)
        h = float(CONFIG.get("HEIGHT", 480) or 480)
    left, top, right, bottom = rotate3d_mode7_billboard_bounds(
        sx, sy, img_w, img_h, anchor=anchor
    )
    if right < -pad or left > w + pad:
        return False
    # 전체가 화면 위로 완전히 나간 경우만 제외 (상단 패딩 = pad)
    if bottom < -pad:
        return False
    if top > h + below_pad:
        return False
    return True


def rotate3d_mode7_project(wx, wy, ctx, *, height_off=0.0, zoom=1.0, screen_w=0.0, screen_h=0.0, anchor="feet"):
    """
    월드 점 → Mode7 화면 feet + 스프라이트 깊이 스케일 (SNES Mode7 / 마리오카트식).

    위치(sx,sy): 배경과 같은 Mode7 식 (도로 좌우 수렴 유지).
    스프라이트 크기: 앞뒤(forward)만. 좌우(lateral)는 크기에 안 씀.
      scale = ref_forward / forward
    → 플레이어와 같은 깊이(카메라 앞쪽 거리)면 scale≈1 (플레이어 빌보드와 동일).
      더 앞(카메라에 가까움)이면 커지고, 더 뒤(지평선)면 작아짐.

    반환:
      valid — 투영 수학 가능(카메라 앞 near 이상). False면 그리지 말 것.
      visible — 컬링 힌트.
        screen_w/h > 0 이면 스프라이트 사각형(bounds-aware).
        없으면 발점+패딩 폴백(지평선 컷 없음). 실제 draw는 크기 확정 후 bounds 재판정 권장.
    """
    if not ctx:
        return None
    try:
        w = float(ctx.get("w", 1))
        h = float(ctx.get("h", 1))
        horizon = float(ctx.get("horizon", 0))
        cam_x = float(ctx.get("cam_x", 0.0))
        cam_y = float(ctx.get("cam_y", 0.0))
        fwd_x = float(ctx.get("fwd_x", 1.0))
        fwd_y = float(ctx.get("fwd_y", 0.0))
        lat_x = float(ctx.get("lat_x", 0.0))
        lat_y = float(ctx.get("lat_y", 1.0))
        cam_h = float(ctx.get("cam_h", 60.0))
        near = float(ctx.get("near", 8.0))
        depth_mul = max(1e-6, float(ctx.get("depth_mul", 165.0)))
        lateral_mul = float(ctx.get("lateral_mul", 1.05))
        try:
            ref_forward = float(ctx.get("ref_forward", 26.0))
        except (TypeError, ValueError):
            ref_forward = 26.0
        ref_forward = max(1e-6, ref_forward)
        z = max(1e-6, float(zoom))
        wx = float(wx)
        wy = float(wy)
    except (TypeError, ValueError):
        return None

    dx = wx - cam_x
    dy = wy - cam_y
    forward = dx * fwd_x + dy * fwd_y
    lateral = dx * lat_x + dy * lat_y

    min_fwd = max(near * 0.25, 1.0)
    if forward < min_fwd:
        return {
            "sx": 0.0,
            "sy": 0.0,
            "scale": 0.0,
            "forward": float(forward),
            "lat_scale": 0.0,
            "visible": False,
            "valid": False,
        }

    p = forward / depth_mul
    sy = horizon + cam_h / max(p, 1e-9) - near
    # 위치용 가로 샘플(도로 Mode7). 스프라이트 크기에는 쓰지 않음.
    # 가로 원점은 view_cx(=player_sx). 중앙(0.5w)이 아니면 전방 시야가 한쪽으로 넓어짐.
    lat_scale = max(p * lateral_mul, 1e-6)
    try:
        view_cx = float(ctx.get("view_cx", ctx.get("player_sx", w * 0.5)))
    except (TypeError, ValueError):
        view_cx = w * 0.5
    sx = view_cx + lateral / lat_scale

    try:
        if not bool(ctx.get("sprite_scale_enabled", True)):
            sc = 1.0
        else:
            # 깊이만: 플레이어 발(depth=ref_forward)에서 1.0
            sc = float(ref_forward) / max(float(forward), 1e-6)
            lo = float(ctx.get("sprite_scale_min", 0.05))
            hi = float(ctx.get("sprite_scale_max", 8.0))
            if lo > hi:
                lo, hi = hi, lo
            sc = max(lo, min(hi, float(sc)))
    except (TypeError, ValueError):
        sc = float(ref_forward) / max(float(forward), 1e-6)

    if float(height_off or 0.0) > 0.0:
        # 플레이어 점프와 동일 계열: 같은 깊이에서 height_off*zoom
        sy -= float(height_off) * z * float(sc)

    try:
        sw = float(screen_w or 0.0)
        sh = float(screen_h or 0.0)
    except (TypeError, ValueError):
        sw, sh = 0.0, 0.0
    if sw > 0.0 or sh > 0.0:
        # 호출측이 스케일된 스프라이트 크기를 넘긴 경우: 사각형 기준
        visible = rotate3d_mode7_bounds_visible(
            sx, sy, sw, sh, ctx, anchor=anchor
        )
    else:
        # 크기 모름(sort/헬퍼): 발점+패딩만. 지평선으로 자르지 않음.
        pad, below_pad = rotate3d_mode7_cull_pads()
        visible = (sy <= h + below_pad) and (sy >= -pad) and (-pad <= sx <= w + pad)

    return {
        "sx": float(sx),
        "sy": float(sy),
        "scale": float(sc),
        "forward": float(forward),
        "lat_scale": float(lat_scale),
        "visible": bool(visible),
        "valid": True,
    }


def rotate3d_mode7_sprite_scale(wx, wy, ctx):
    """월드 오브젝트 빌보드 깊이 스케일. 투영 불가면 0."""
    pr = rotate3d_mode7_project(wx, wy, ctx)
    if not pr or not pr.get("valid", pr.get("visible")):
        return 0.0
    return float(pr.get("scale", 1.0))


def rotate3d_mode7_sort_key(wx, wy, ctx):
    """
    y-sort 키: 작을수록 먼저(뒤) 그린다.
    Mode7에서는 화면 feet Y — 멀리(지평선 쪽)가 더 작음.
    투영 불가(카메라 뒤)만 아주 작게(맨 뒤) 두어 정렬 안정화.
    """
    if not ctx:
        try:
            return float(wy)
        except (TypeError, ValueError):
            return 0.0
    pr = rotate3d_mode7_project(wx, wy, ctx)
    if not pr or not pr.get("valid", pr.get("visible")):
        return -1e9
    return float(pr["sy"])


def rotate3d_mode7_world_to_screen(wx, wy, ctx, *, height_off=0.0, zoom=1.0):
    """맵 월드 좌표 → Mode7 화면 좌표. 투영 불가면 (매우 밖) 좌표."""
    pr = rotate3d_mode7_project(wx, wy, ctx, height_off=height_off, zoom=zoom)
    if not pr:
        return float(wx), float(wy)
    if not pr.get("valid", pr.get("visible")):
        return -1e6, -1e6
    return float(pr["sx"]), float(pr["sy"])


def rotate3d_mode7_screen_to_world(sx, sy, ctx):
    """Mode7 화면(world_surf) 좌표 → 맵 월드 좌표 (배경 샘플 역변환과 동일)."""
    if not ctx:
        return float(sx), float(sy)
    try:
        w = float(ctx.get("w", 1))
        horizon = float(ctx.get("horizon", 0))
        cam_x = float(ctx.get("cam_x", 0.0))
        cam_y = float(ctx.get("cam_y", 0.0))
        fwd_x = float(ctx.get("fwd_x", 1.0))
        fwd_y = float(ctx.get("fwd_y", 0.0))
        lat_x = float(ctx.get("lat_x", 0.0))
        lat_y = float(ctx.get("lat_y", 1.0))
        cam_h = float(ctx.get("cam_h", 60.0))
        near = float(ctx.get("near", 6.0))
        depth_mul = max(1e-6, float(ctx.get("depth_mul", 165.0)))
        lateral_mul = float(ctx.get("lateral_mul", 1.05))
        sx = float(sx)
        sy = float(sy)
    except (TypeError, ValueError):
        return float(sx), float(sy)
    row = max(near * 0.05, sy - horizon + near)
    p_row = cam_h / row
    forward = p_row * depth_mul
    lat_scale = max(p_row * lateral_mul, 1e-6)
    try:
        view_cx = float(ctx.get("view_cx", ctx.get("player_sx", w * 0.5)))
    except (TypeError, ValueError):
        view_cx = w * 0.5
    lateral = (sx - view_cx) * lat_scale
    wx = cam_x + forward * fwd_x + lateral * lat_x
    wy = cam_y + forward * fwd_y + lateral * lat_y
    return float(wx), float(wy)


def rotate3d_mode7_player_screen(ctx, *, height_off=0.0, zoom=1.0):
    """플레이어 스프라이트는 화면 하단·player_sx 고정 (회전 피벗 = 이 발 좌표)."""
    if not ctx:
        return 320.0, 400.0
    try:
        sx = float(ctx.get("player_sx", float(ctx.get("w", 640)) * 0.5))
        sy = float(ctx.get("player_sy", float(ctx.get("h", 480)) - 18.0))
    except (TypeError, ValueError):
        return 320.0, 400.0
    if float(height_off or 0.0) > 0.0:
        # 점프 높이: 플레이어는 빌보드라 월드 압축비 대신 zoom만 (손아이템과 동일 계열)
        sy -= float(height_off) * float(zoom)
    return float(sx), float(sy)


def rotate3d_mode7_entity_screen(wx, wy, ctx, *, height_off=0.0, zoom=1.0, player_billboard=False):
    """
    Mode7 엔티티 feet 화면좌표.
    player_billboard=True → 하단·player_sx 고정(플레이어·손에 든 아이템만).
    그 외는 월드 투영. 비가시이면 (-1e6,-1e6).
    """
    if player_billboard:
        return rotate3d_mode7_player_screen(ctx, height_off=height_off, zoom=zoom)
    return rotate3d_mode7_world_to_screen(wx, wy, ctx, height_off=height_off, zoom=zoom)


def _rotate3d_mode7_parse_rgb(raw, default=(0, 0, 0)):
    """CONFIG/cfg RGB 튜플 파싱."""
    try:
        if isinstance(raw, (list, tuple)) and len(raw) >= 3:
            return (
                max(0, min(255, int(raw[0]))),
                max(0, min(255, int(raw[1]))),
                max(0, min(255, int(raw[2]))),
            )
    except (TypeError, ValueError):
        pass
    return default


def rotate3d_mode7_fill_sky_and_ground(dst, ctx, cfg=None, *, fill_sky=True):
    """
    Mode7 빈 공간 채움.
      - 지평선 아래: ground_fill_color (기본 검정) — 맵 밖 픽셀이 여기에 남음
      - 지평선 위: sky_color 단색, 또는 ROTATE3D_SKY_PANORAMA 360 원통 샘플
        · 가로: cam_angle + 화면X FOV → 이미지 U wrap (좌우 회전 시 하늘이 같이 돎)
        · 세로: 화면 0..horizon → 이미지 V (상단=하늘 위, 지평선=이미지 하단)
    fill_sky=False 이면 전체 clear만 (마스크 Mode7용).
    """
    if dst is None or not ctx:
        return
    try:
        w = int(dst.get_width())
        h = int(dst.get_height())
        horizon = int(ctx.get("horizon", 0) or 0)
    except Exception:
        return
    if w <= 0 or h <= 0:
        return
    horizon = max(0, min(h, horizon))
    cfg = cfg if isinstance(cfg, dict) else {}

    ground = _rotate3d_mode7_parse_rgb(
        cfg.get("ground_fill_color", CONFIG.get("ROTATE3D_GROUND_FILL_COLOR", (0, 0, 0))),
        (0, 0, 0),
    )
    sky = _rotate3d_mode7_parse_rgb(
        cfg.get("sky_color", CONFIG.get("ROTATE3D_SKY_COLOR", (135, 206, 235))),
        (135, 206, 235),
    )

    # 1) 전체(또는 하단)를 바닥색으로 — Mode7 맵 샘플이 덮지 못한 곳은 검정으로 남음
    try:
        dst.fill(ground)
    except Exception:
        return

    if not fill_sky or horizon <= 0:
        return

    # 2) 지평선 위 하늘
    sky_path = ""
    try:
        sky_path = str(cfg.get("sky_panorama", CONFIG.get("ROTATE3D_SKY_PANORAMA", "")) or "").strip()
    except Exception:
        sky_path = ""
    pan = _load_image_cached(sky_path) if sky_path else None

    if pan is None:
        try:
            dst.fill(sky, pygame.Rect(0, 0, w, horizon))
        except Exception:
            pass
        return

    try:
        cam_ang = float(ctx.get("cam_angle", 0.0) or 0.0)
    except (TypeError, ValueError):
        cam_ang = 0.0
    try:
        yaw_off = float(
            cfg.get(
                "sky_panorama_yaw_offset",
                CONFIG.get("ROTATE3D_SKY_PANORAMA_YAW_OFFSET", 0.0),
            )
            or 0.0
        )
    except (TypeError, ValueError):
        yaw_off = 0.0
    try:
        fov = float(
            cfg.get("sky_fov_rad", CONFIG.get("ROTATE3D_SKY_FOV_RAD", 1.2)) or 1.2
        )
    except (TypeError, ValueError):
        fov = 1.2
    fov = max(0.2, min(math.pi * 1.5, fov))

    try:
        sw = int(pan.get_width())
        sh = int(pan.get_height())
    except Exception:
        sw, sh = 0, 0
    if sw <= 0 or sh <= 0:
        try:
            dst.fill(sky, pygame.Rect(0, 0, w, horizon))
        except Exception:
            pass
        return

    two_pi = math.pi * 2.0
    base_yaw = cam_ang + yaw_off

    try:
        import numpy as np

        sky_arr = pygame.surfarray.array3d(pan)
        out = pygame.surfarray.pixels3d(dst)
        try:
            sx_arr = np.arange(w, dtype=np.float64)
            # 화면 가로 → yaw 슬라이스 (원통 360). 원점은 view_cx(플레이어 X).
            try:
                vcx = float(ctx.get("view_cx", ctx.get("player_sx", w * 0.5)))
            except (TypeError, ValueError):
                vcx = float(w) * 0.5
            ang = base_yaw + ((sx_arr - vcx) / max(1.0, float(w))) * fov
            ux = np.floor(np.mod(ang / two_pi, 1.0) * float(sw)).astype(np.int32)
            np.clip(ux, 0, sw - 1, out=ux)
            # 세로: sy=0 → 이미지 상단, sy=horizon-1 → 이미지 하단
            den = max(1, horizon - 1)
            for sy in range(horizon):
                vy = int(round(float(sy) / float(den) * float(sh - 1)))
                vy = max(0, min(sh - 1, vy))
                out[:, sy] = sky_arr[ux, vy]
        finally:
            del out
    except Exception:
        # numpy 실패 시 픽셀 루프
        try:
            try:
                vcx = float(ctx.get("view_cx", ctx.get("player_sx", w * 0.5)))
            except (TypeError, ValueError):
                vcx = float(w) * 0.5
            for sx in range(w):
                ang = base_yaw + ((float(sx) - vcx) / max(1.0, float(w))) * fov
                u = int(math.floor((ang / two_pi) % 1.0 * float(sw)))
                u = max(0, min(sw - 1, u))
                den = max(1, horizon - 1)
                for sy in range(horizon):
                    v = int(round(float(sy) / float(den) * float(sh - 1)))
                    v = max(0, min(sh - 1, v))
                    dst.set_at((sx, sy), pan.get_at((u, v)))
        except Exception:
            try:
                dst.fill(sky, pygame.Rect(0, 0, w, horizon))
            except Exception:
                pass


def apply_rotate3d_mode7(
    dst,
    map_surf,
    cam_x,
    cam_y,
    cam_angle_rad,
    strength_01,
    cfg,
    *,
    ctx=None,
    clear_color=(0, 0, 0),
    ref_forward=None,
    player_wx=None,
    player_wy=None,
    fill_sky=True,
):
    """
    Mode7 배경: 지평선~하단 각 행
      p = CAM_H/(row+NEAR); depth = p*DEPTH_MUL; lat_scale = p*LATERAL_MUL
    → 윗줄일수록 맵이 멀고 작게 (상하·좌우 같은 비율).

    빈 공간:
      fill_sky=True  → 지평선 위 하늘색/360파노라마, 아래(맵 밖) 검정(ground_fill)
      fill_sky=False → clear_color 단색만 (마스크 Mode7 등)
    """
    if dst is None or map_surf is None:
        return None
    try:
        w = int(dst.get_width())
        h = int(dst.get_height())
        mw = int(map_surf.get_width())
        mh = int(map_surf.get_height())
    except Exception:
        return None
    if w <= 0 or h <= 0 or mw <= 0 or mh <= 0:
        return None
    if ctx is None:
        ctx = rotate3d_mode7_build_ctx(
            cfg,
            strength_01,
            w,
            h,
            cam_x,
            cam_y,
            cam_angle_rad,
            ref_forward=ref_forward,
            player_wx=player_wx,
            player_wy=player_wy,
        )
    if ctx is None or float(ctx.get("strength", 0.0)) <= 1e-6:
        return None
    horizon = int(ctx["horizon"])
    fwd_x = float(ctx["fwd_x"])
    fwd_y = float(ctx["fwd_y"])
    lat_x = float(ctx["lat_x"])
    lat_y = float(ctx["lat_y"])
    cam_h = float(ctx["cam_h"])
    near = float(ctx["near"])
    depth_mul = float(ctx["depth_mul"])
    lateral_mul = float(ctx["lateral_mul"])
    cx = float(ctx["cam_x"])
    cy = float(ctx["cam_y"])
    try:
        view_cx = float(ctx.get("view_cx", ctx.get("player_sx", w * 0.5)))
    except (TypeError, ValueError):
        view_cx = float(w) * 0.5

    # 지평선 위/아래 빈 공간 선채움 (맵 샘플이 덮는 부분만 이후 덮어씀)
    if fill_sky:
        rotate3d_mode7_fill_sky_and_ground(dst, ctx, cfg, fill_sky=True)
    else:
        try:
            dst.fill(clear_color)
        except Exception:
            pass

    # PC: numpy+surfarray 고속 경로. Android APK 는 numpy 미포함(p4a/py3.10 충돌) → get_at 폴백.
    try:
        import numpy as np

        map_arr = pygame.surfarray.array3d(map_surf)
        out = pygame.surfarray.pixels3d(dst)
        sx_arr = np.arange(w, dtype=np.float32)
        try:
            for sy in range(horizon, h):
                row = float(sy - horizon)
                p_row = cam_h / (row + near)
                depth = p_row * depth_mul
                lat_scale = p_row * lateral_mul
                row_cx = cx + fwd_x * depth
                row_cy = cy + fwd_y * depth
                lat = (sx_arr - view_cx) * lat_scale
                mx = (row_cx + lat * lat_x).astype(np.int32)
                my = (row_cy + lat * lat_y).astype(np.int32)
                m = (mx >= 0) & (mx < mw) & (my >= 0) & (my < mh)
                if np.any(m):
                    out[sx_arr[m].astype(np.int32), sy] = map_arr[mx[m], my[m]]
        finally:
            del out
        return ctx
    except Exception:
        pass

    # numpy/surfarray 없음: Surface 픽셀 폴백 (가로 2px 스텝으로 모바일 부하↓)
    try:
        x_step = 2
        for sy in range(horizon, h):
            row = float(sy - horizon)
            p_row = cam_h / (row + near)
            depth = p_row * depth_mul
            lat_scale = p_row * lateral_mul
            row_cx = cx + fwd_x * depth
            row_cy = cy + fwd_y * depth
            sx = 0
            while sx < w:
                lat = (float(sx) - view_cx) * lat_scale
                mx = int(row_cx + lat * lat_x)
                my = int(row_cy + lat * lat_y)
                if 0 <= mx < mw and 0 <= my < mh:
                    c = map_surf.get_at((mx, my))
                    dst.set_at((sx, sy), c)
                    if x_step > 1 and sx + 1 < w:
                        dst.set_at((sx + 1, sy), c)
                sx += x_step
    except Exception:
        return None
    return ctx


def rotate3d_flat_rotate(fx, fy, px, py, angle_rad):
    """평면 cam-screen 좌표를 pivot 기준 angle_rad 만큼 회전 (틸트 보조·하위호환)."""
    try:
        a = float(angle_rad)
        fx, fy, px, py = float(fx), float(fy), float(px), float(py)
    except (TypeError, ValueError):
        return fx, fy
    if abs(a) <= 1e-9:
        return fx, fy
    c = math.cos(a)
    s = math.sin(a)
    rdx = fx - px
    rdy = fy - py
    return px + rdx * c - rdy * s, py + rdx * s + rdy * c


def rotate3d_flat_unrotate(fx, fy, px, py, angle_rad):
    """rotate3d_flat_rotate 의 역."""
    return rotate3d_flat_rotate(fx, fy, px, py, -float(angle_rad))


def map_feet_screen_xy(
    flat_x,
    flat_y,
    *,
    y_transform=None,
    x_scale_fn=None,
    x_shift_fn=None,
    x_offset_fn=None,
    pivot_xy=None,
    cam_angle_rad=0.0,
    anchor_x=0.5,
    view_w=640,
    height_off=0.0,
    zoom=1.0,
):
    """평면 cam-screen 좌표 → 틸트/쉬어 반영 발 위치(스프라이트 크기는 그대로)."""
    fx = float(flat_x)
    fy_flat = float(flat_y)
    if pivot_xy is not None:
        try:
            px, py = float(pivot_xy[0]), float(pivot_xy[1])
            fx, fy_flat = rotate3d_flat_rotate(fx, fy_flat, px, py, float(cam_angle_rad))
        except (TypeError, ValueError, IndexError):
            pass
    vw = max(1.0, float(view_w))
    ax = float(anchor_x) * vw
    if callable(x_scale_fn):
        try:
            sc = float(x_scale_fn(fy_flat))
            fx = ax + (fx - ax) * sc
        except Exception:
            pass
    if callable(x_shift_fn):
        try:
            fx += float(x_shift_fn(fy_flat))
        except Exception:
            pass
    if callable(y_transform):
        try:
            fy = float(y_transform(fy_flat))
        except Exception:
            fy = fy_flat
    else:
        fy = fy_flat
    fy_q = float(int(round(float(fy))))
    if callable(x_offset_fn):
        try:
            fx += float(shear_base_offset_px(fy_q, x_offset_fn))
        except Exception:
            pass
    h_off = float(height_off or 0.0)
    if h_off > 0.0:
        fy = fy_q - h_off * float(zoom)
    else:
        fy = fy_q
    return float(fx), float(fy)


def shear_strip_row_span(surface_h, blit_y, view_h, *, pad_px=64, bucket_px=128):
    """화면에 보이는 tilt 행 구간 [r0,r1). bucket 으로 수직 팬 시 캐시 재사용."""
    try:
        sh = int(surface_h)
        by = float(blit_y)
        vh = int(view_h)
        pad = max(0, int(pad_px))
        bucket = max(16, int(bucket_px))
    except Exception:
        return 0, max(1, int(surface_h or 1))
    sh = max(1, sh)
    vh = max(1, vh)
    r0 = max(0, int(math.floor(-by)) - pad)
    r1 = min(sh, int(math.ceil(float(vh) - by)) + pad)
    if r1 <= r0:
        r0, r1 = 0, sh
    r0b = (r0 // bucket) * bucket
    r1b = min(sh, ((r1 + bucket - 1) // bucket) * bucket)
    if r1b <= r0b:
        r0b, r1b = 0, sh
    return int(r0b), int(r1b)


# --- sprite field shear cache (동일 qtop/qbot 밴드 오브젝트 간 공유) ---
_SPRITE_FIELD_SHEAR_CACHE = OrderedDict()  # key -> (Surface, dx_adj, est_mb)
_SPRITE_FIELD_SHEAR_CACHE_MB = 0.0


def _sprite_field_shear_cache_get(key):
    v = _SPRITE_FIELD_SHEAR_CACHE.get(key)
    if v is None:
        return None
    try:
        _SPRITE_FIELD_SHEAR_CACHE.move_to_end(key)
    except Exception:
        pass
    return v[0], int(v[1])


def _sprite_field_shear_cache_put(key, surf, dx_adj):
    global _SPRITE_FIELD_SHEAR_CACHE_MB
    if surf is None:
        return
    try:
        w, h = surf.get_size()
    except Exception:
        return
    est = _est_rgba_mb(w, h)
    try:
        mb_limit = float(CONFIG.get("SPRITE_FIELD_SHEAR_CACHE_MB_LIMIT", 48.0))
    except Exception:
        mb_limit = 48.0
    mb_limit = max(8.0, min(256.0, mb_limit))
    try:
        max_items = int(CONFIG.get("SPRITE_FIELD_SHEAR_CACHE_MAX_ITEMS", 128) or 128)
    except Exception:
        max_items = 128
    max_items = max(16, min(1024, max_items))
    if est <= 0.0 or est > mb_limit * 0.5:
        return
    old = _SPRITE_FIELD_SHEAR_CACHE.get(key)
    if old is not None:
        try:
            _SPRITE_FIELD_SHEAR_CACHE_MB -= float(old[2])
        except Exception:
            pass
        try:
            del _SPRITE_FIELD_SHEAR_CACHE[key]
        except Exception:
            pass
    try:
        while (_SPRITE_FIELD_SHEAR_CACHE_MB + est) > mb_limit and _SPRITE_FIELD_SHEAR_CACHE:
            _k, (_s, _dx, mb) = _SPRITE_FIELD_SHEAR_CACHE.popitem(last=False)
            try:
                _SPRITE_FIELD_SHEAR_CACHE_MB -= float(mb)
            except Exception:
                pass
        while len(_SPRITE_FIELD_SHEAR_CACHE) >= max_items and _SPRITE_FIELD_SHEAR_CACHE:
            _k, (_s, _dx, mb) = _SPRITE_FIELD_SHEAR_CACHE.popitem(last=False)
            try:
                _SPRITE_FIELD_SHEAR_CACHE_MB -= float(mb)
            except Exception:
                pass
    except Exception:
        _SPRITE_FIELD_SHEAR_CACHE.clear()
        _SPRITE_FIELD_SHEAR_CACHE_MB = 0.0
    _SPRITE_FIELD_SHEAR_CACHE[key] = (surf, int(dx_adj), float(est))
    _SPRITE_FIELD_SHEAR_CACHE_MB += float(est)


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
    bands = []
    i = 0
    for yy in range(0, h, slice_h):
        hh = min(slice_h, h - yy)
        dx = int(shifts[i] - mn)
        i += 1
        if bands and bands[-1][2] == dx and bands[-1][0] + bands[-1][1] == yy:
            bands[-1] = (bands[-1][0], bands[-1][1] + hh, dx)
        else:
            bands.append((yy, hh, dx))
    blit = out.blit
    Rect = pygame.Rect
    for yy, hh, dx in bands:
        try:
            blit(render_img, (dx, yy), area=Rect(0, yy, w, hh))
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
            # Android/Windows 빌드에서 한글 파일명이 깨지면 events.json 이름과 library 키가 어긋난다.
            # 트랙이 1곡뿐이면 그 곡으로 폴백(실기기 logcat에서 확인된 케이스).
            if len(self.library) == 1:
                fallback = next(iter(self.library))
                print(f"[MUSIC] name miss ({name!r}) -> sole track {fallback!r}")
                name = fallback
            else:
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
    mode7_ctx=None,
    player_billboard=False,
):
    """발 그림자. Mode7 중에는 지면 좌표를 rotate3d_mode7_project 로 투영 (height=0 지면)."""
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
    depth_scale = 1.0
    if mode7_ctx:
        # 지면 그림자: height_off=0. 월드 오프셋 후 Mode7 투영.
        if player_billboard:
            cx, cy = rotate3d_mode7_player_screen(mode7_ctx, height_off=0.0, zoom=float(zoom))
            # 플레이어 빌보드: 화면 오프셋을 살짝만 (월드 단위 off 는 깊이마다 달라서 사용 안 함)
            try:
                cx = float(cx) + float(offx) * 0.35 * float(zoom)
                cy = float(cy) + float(offy) * 0.35 * float(zoom)
            except Exception:
                pass
            depth_scale = 1.0
        else:
            pr = rotate3d_mode7_project(
                float(gx) + float(offx),
                float(gy) + float(offy),
                mode7_ctx,
                height_off=0.0,
                zoom=float(zoom),
            )
            # 그림자: 투영만 되면 그림(작은 타원이라 발점 지평선 컷 불필요)
            if not pr or not pr.get("valid", pr.get("visible")):
                return
            cx = float(pr["sx"])
            cy = float(pr["sy"])
            try:
                depth_scale = max(0.08, min(4.0, float(pr.get("scale", 1.0) or 1.0)))
            except (TypeError, ValueError):
                depth_scale = 1.0
    else:
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
            cx = float(cx) + float(shear_base_offset_px(cy_q, x_offset_fn))
    base_rx = float(CONFIG.get("SHADOW_ELLIPSE_RX", 15))
    base_ry = float(CONFIG.get("SHADOW_ELLIPSE_RY", 7))
    rx = max(2, int(base_rx * zoom * size_scale * entity_scale_mul * depth_scale))
    ry = max(1, int(base_ry * zoom * size_scale * entity_scale_mul * depth_scale))
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

    def _missing_anim_placeholder():
        """에셋 누락 표시 — 검은 상자 대신 분홍(누락) 타일."""
        s = pygame.Surface((24, 32), pygame.SRCALPHA)
        s.fill((255, 0, 255, 200))
        return s

    path = os.path.join("assets", "images", "character", char_name, f"{state}_{direction}")
    frames = _load_char_anim_dir_cached(path, state, direction, char_name)
    if not frames:
        st = (state or "").strip().lower()
        if st not in ("idle", ""):
            idle_path = os.path.join(
                "assets", "images", "character", char_name, f"idle_{direction}"
            )
            frames = _load_char_anim_dir_cached(idle_path, "idle", direction, char_name)
        if not frames:
            img = _root_fallback_image()
            if img is not None:
                return [img]
            return [_missing_anim_placeholder()]
    return frames


def load_baseball_overlay_frames(body_type: str, anim_set: str):
    """
    공용 야구 오버레이 — assets/images/character/baseball_a|k/<anim_set>_left/
    body_type: adult | kid | animal (animal → 빈 목록)
    anim_set: idle_baseball | swing_baseball
    """
    bt = str(body_type or "adult").strip().lower()
    if bt in ("animal", "pet"):
        return []
    folder = "baseball_k" if bt in ("kid", "child") else "baseball_a"
    st = str(anim_set or "idle_baseball").strip().lower()
    path = os.path.join("assets", "images", "character", folder, f"{st}_left")
    frames = _load_anim_dir_cached(path)
    return list(frames) if frames else []


def load_fishing_overlay_frames(body_type: str, anim_set: str):
    """
    공용 낚시 오버레이 — assets/images/character/fishing_a|k/<anim_set>_left/
    body_type: adult | kid | animal (animal → 빈 목록)
    anim_set: idle_fishing | draw_fishing | pull_fishing | tension_fishing
    """
    bt = str(body_type or "adult").strip().lower()
    if bt in ("animal", "pet"):
        return []
    folder = "fishing_k" if bt in ("kid", "child") else "fishing_a"
    st = str(anim_set or "idle_fishing").strip().lower()
    path = os.path.join("assets", "images", "character", folder, f"{st}_left")
    frames = _load_anim_dir_cached(path)
    return list(frames) if frames else []


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
        self.playing_baseball = False
        self.playing_fishing = False
        self._sprite_overlay = None
        self._fishing_overlay_tag = ""
        # 이벤트 ZOOM: 카메라 줌과 별도로 스프라이트만 추가 배율 (1.0=기본)
        self.event_entity_zoom = 1.0
        self.event_entity_zoom_target = 1.0
        self.entity_def_zoom = 1.0
        try:
            self.event_entity_zoom_speed = float(CONFIG.get("ENTITY_ZOOM_LERP", 0.12))
        except Exception:
            self.event_entity_zoom_speed = 0.12

    def retarget_char_def(self, new_name: str) -> bool:
        """
        char_defs 키만 바꿔 외형(애니메이션 세트)·표시 속성을 갱신 (이벤트 CHANGE).
        위치/방향/이동 경로/들고 있는 물건 등 인스턴스 상태는 그대로 둔다.
        ACTION_ANIM hold 등 남아 있던 애니 오버라이드는 해제하고 idle 로 맞춘다.
        """
        key = str(new_name or "").strip()
        if not key or key not in CHAR_ASSETS:
            return False
        self.clear_anim_override()
        self.state = "idle"
        self.name = key
        _ch = CHAR_ASSETS.get(key, {}) or {}
        # 표시 속성: __init__과 동일 규칙(인스턴스 info 우선, 없으면 char_def).
        if "layer" not in self.info:
            self.layer = int(_ch.get("layer", 0) or 0)
        if "ysort" not in self.info:
            self.ysort_mode = _normalize_ysort_mode(_ch.get("ysort", "ground"))
        if "height" not in self.info:
            self.height = _clamp_draw_height(_ch.get("height", 0))
        # 애니메이션 세트 재로딩 (__init__과 동일한 상태·폴백 규칙).
        self.anims_l = {
            "idle": load_anim_auto(key, "idle", "left"),
            "walk": load_anim_auto(key, "walk", "left"),
            "jump": _load_char_state_or_fallback(key, "jump", "walk"),
            "run": _load_char_state_or_fallback(key, "run", "walk"),
        }
        _fallback_by_state = {"seating": "seat", "seat_idle": "seat"}
        for st in ("hurt", "laugh", "attack", "lie", "seat", "seating", "seat_idle", "question", "surprise", "say", "sleep", "sad"):
            fb = _fallback_by_state.get(st, "idle")
            self.anims_l[st] = _load_char_state_or_fallback(key, st, fb)
        self.anims_r = {
            k: [pygame.transform.flip(img, True, False) for img in v]
            for k, v in self.anims_l.items()
        }
        # 방향은 유지, 표시는 idle 기준으로 초기화.
        self.frame_idx = 0
        self.last_anim_time = 0
        try:
            anims = self.anims_r if getattr(self, "direction", "left") == "right" else self.anims_l
            cur = anims.get("idle") or self.anims_l.get("idle")
            if cur:
                self.image = cur[0]
        except Exception:
            pass
        try:
            from char_behavior import apply_char_type_retarget

            apply_char_type_retarget(self, key)
        except Exception:
            pass
        return True

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

    def clear_sprite_overlay(self):
        self._sprite_overlay = None

    def set_sprite_overlay(self, frames, *, loop=True, fps=6.0):
        if not frames:
            self._sprite_overlay = None
            return
        self._sprite_overlay = {
            "frames": list(frames),
            "idx": 0,
            "last_ms": pygame.time.get_ticks(),
            "fps": max(1.0, float(fps)),
            "loop": bool(loop),
            "phase": "play",
            "hold_until_ms": 0,
            "release_frames": None,
            "hold_sec": 0.0,
        }

    def play_sprite_overlay_once(
        self, frames, *, fps=8.0, hold_sec=2.0, release_frames=None
    ):
        if not frames:
            return
        self._sprite_overlay = {
            "frames": list(frames),
            "idx": 0,
            "last_ms": pygame.time.get_ticks(),
            "fps": max(1.0, float(fps)),
            "loop": False,
            "phase": "play",
            "hold_until_ms": 0,
            "release_frames": list(release_frames) if release_frames else None,
            "hold_sec": max(0.0, float(hold_sec)),
        }

    def _tick_sprite_overlay(self, now_ms):
        ov = getattr(self, "_sprite_overlay", None)
        if not isinstance(ov, dict):
            return
        frames = ov.get("frames") or []
        if not frames:
            self._sprite_overlay = None
            return
        if ov.get("phase") == "hold":
            if now_ms >= int(ov.get("hold_until_ms") or 0):
                rel = ov.get("release_frames")
                if rel:
                    self.set_sprite_overlay(rel, loop=True, fps=float(ov.get("fps") or 6.0))
                else:
                    self.clear_sprite_overlay()
            return
        fps = float(ov.get("fps") or 6.0)
        delay_ms = max(1, int(round(1000.0 / fps)))
        last = int(ov.get("last_ms") or 0)
        if now_ms - last < delay_ms:
            return
        ov["last_ms"] = now_ms
        n = len(frames)
        if ov.get("loop"):
            ov["idx"] = (int(ov.get("idx") or 0) + 1) % n
            return
        idx = int(ov.get("idx") or 0)
        if idx < n - 1:
            ov["idx"] = idx + 1
            return
        hold_sec = float(ov.get("hold_sec") or 0.0)
        rel = ov.get("release_frames")
        if hold_sec > 0.0 and rel:
            ov["phase"] = "hold"
            ov["hold_until_ms"] = int(now_ms + hold_sec * 1000.0)
        elif rel:
            self.set_sprite_overlay(rel, loop=True, fps=fps)
        else:
            self.clear_sprite_overlay()

    def _draw_sprite_overlay(self, screen, feet_x_px, feet_y_px, zoom_mul, sprite_perspective_q=None):
        ov = getattr(self, "_sprite_overlay", None)
        if not isinstance(ov, dict):
            return
        frames = ov.get("frames") or []
        if not frames:
            return
        idx = int(ov.get("idx") or 0) % len(frames)
        img = frames[idx]
        if str(getattr(self, "direction", "left") or "left") == "right":
            try:
                img = pygame.transform.flip(img, True, False)
            except Exception:
                pass
        render_img = get_cached_scaled_sprite(
            img,
            float(zoom_mul),
            sprite_perspective_q=sprite_perspective_q,
            sprite_tilt=getattr(self, "sprite_tilt", 1.0),
        )
        dx, dy = blit_topleft_bottom_center(
            int(feet_x_px),
            int(feet_y_px),
            render_img.get_width(),
            render_img.get_height(),
        )
        screen.blit(render_img, (dx, dy))

    def update_anim(self):
        now = pygame.time.get_ticks()
        self._tick_sprite_overlay(now)
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
        mode7_ctx=None,
        player_billboard=False,
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
            mode7_ctx=mode7_ctx,
            player_billboard=player_billboard,
        )

    def draw(self, screen, cam_x, cam_y, zoom=1.0, jump_shadow_mode=None, y_transform=None, x_offset_fn=None, sprite_perspective_q=None, shear_lod=False, x_scale_fn=None, x_shift_fn=None, pivot_xy=None, cam_angle_rad=0.0, mode7_ctx=None, view_w=None):
        if not self.is_visible: return # 플레이어가 숨김 상태면 그리지 않음

        try:
            ez = entity_combined_zoom_mul(self)
        except Exception:
            ez = 1.0
        # Mode7: Player만 하단 고정·스케일1. NPC/기타는 월드 투영 + 깊이 스케일
        eff = float(zoom) * ez
        mode7_player_bb = bool(mode7_ctx) and isinstance(self, Player)

        h_off = float(getattr(self, "height", 0) or 0)
        mode7_pr = None
        if mode7_ctx and (not mode7_player_bb):
            mode7_pr = rotate3d_mode7_project(
                float(self.pos[0]),
                float(self.pos[1]),
                mode7_ctx,
                height_off=h_off,
                zoom=float(zoom),
            )
            # 카메라 뒤 등 투영 불가일 때만 즉시 스킵. 화면 컬링은 스케일 후 bounds.
            if not mode7_pr or not mode7_pr.get("valid", mode7_pr.get("visible")):
                return
            eff *= float(mode7_pr.get("scale", 1.0) or 1.0)

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
        render_img = apply_entity_fx_to_image(render_img, getattr(self, "entity_fx", None))
        render_img = get_cached_scaled_sprite(
            render_img,
            eff,
            sprite_perspective_q=sprite_perspective_q,
            sprite_tilt=getattr(self, "sprite_tilt", 1.0),
        )

        # 2. 줌이 적용된 화면 좌표 계산
        try:
            vw = float(view_w if view_w is not None else CONFIG.get("WIDTH", 640))
        except Exception:
            vw = 640.0
        if mode7_player_bb:
            feet_x, feet_y = rotate3d_mode7_player_screen(
                mode7_ctx,
                height_off=h_off,
                zoom=float(zoom),
            )
        elif mode7_pr is not None:
            feet_x, feet_y = float(mode7_pr["sx"]), float(mode7_pr["sy"])
        else:
            feet_x, feet_y = map_feet_screen_xy(
                float((self.pos[0] - cam_x) * zoom),
                float((self.pos[1] - cam_y) * zoom),
                y_transform=y_transform,
                x_scale_fn=x_scale_fn,
                x_shift_fn=x_shift_fn,
                x_offset_fn=x_offset_fn,
                pivot_xy=pivot_xy,
                cam_angle_rad=float(cam_angle_rad),
                anchor_x=0.5,
                view_w=vw,
                height_off=h_off,
                zoom=float(zoom),
            )

        # Mode7 NPC 등: 발점이 지평선 밖이어도 몸통이 남으면 그림
        if mode7_ctx and (not mode7_player_bb):
            if not rotate3d_mode7_bounds_visible(
                feet_x,
                feet_y,
                render_img.get_width(),
                render_img.get_height(),
                mode7_ctx,
                anchor="feet",
            ):
                return

        # 발 그림자: Mode7이면 지면 투영 (높이 반영 X — 점프해도 그림자만 작아짐)
        self._draw_feet_shadow(
            screen,
            cam_x,
            cam_y,
            zoom,
            jump_shadow_mode,
            y_transform=y_transform,
            x_offset_fn=x_offset_fn,
            entity_scale_mul=ez * (float(mode7_pr.get("scale", 1.0)) if mode7_pr else 1.0),
            mode7_ctx=mode7_ctx,
            player_billboard=mode7_player_bb,
        )

        fpx, fpy = int(round(float(feet_x))), int(round(float(feet_y)))
        dx, dy = blit_topleft_bottom_center(fpx, fpy, render_img.get_width(), render_img.get_height())

        screen.blit(render_img, (dx, dy))
        if getattr(self, "_sprite_overlay", None) is not None:
            self._draw_sprite_overlay(
                screen,
                fpx,
                fpy,
                eff,
                sprite_perspective_q=sprite_perspective_q,
            )

        # 3. 손에 든 물건 — is_held 일 때만 (발 중앙 앵커 = FieldItem·ANIM_ONCE 와 동일 규칙)
        if self.held_item and bool(getattr(self.held_item, "is_held", False)):
            hi = self.held_item
            if len(getattr(hi, "frames", []) or []) > 1:
                hi.update_anim()
            h_img = hi.image
            h_img = apply_entity_fx_to_image(h_img, getattr(hi, "entity_fx", None))
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
                try:
                    hez = entity_combined_zoom_mul(hi)
                except Exception:
                    hez = 1.0
            except Exception:
                hez = 1.0
            hez = max(0.05, min(8.0, hez))
            h_eff = float(zoom) * hez
            # 손에 든 아이템: 플레이어와 같이 하단 고정·스케일 1
            if mode7_ctx:
                dx_base, dy_base = rotate3d_mode7_player_screen(
                    mode7_ctx,
                    height_off=float(getattr(hi, "height", 0) or 0),
                    zoom=float(zoom),
                )
            else:
                dx_base, dy_base = _field_world_to_screen_anchor(
                    foot_wx,
                    foot_wy,
                    cam_x,
                    cam_y,
                    zoom,
                    height=float(getattr(hi, "height", 0) or 0),
                    y_transform=y_transform,
                    x_offset_fn=x_offset_fn,
                    x_scale_fn=x_scale_fn,
                    x_shift_fn=x_shift_fn,
                    pivot_xy=pivot_xy,
                    cam_angle_rad=float(cam_angle_rad),
                    mode7_ctx=None,
                    view_w=view_w,
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
        # 캐릭터/오브젝트 자연 회피(동적 A* 재계획) 상태 — 효율 위해 쿨다운/횟수 제한
        self._avoid_block_since_ms = 0   # 현재 막힘이 시작된 시각(0=안 막힘)
        self._avoid_replans = 0          # 연속 막힘 동안 누적 재계획 횟수
        self._avoid_next_replan_ms = 0   # 다음 재계획 허용 시각(쿨다운)
        self._steer_side = 0             # 장애물 비껴가기 선호 방향(+1/-1, 0=없음) — 좌우 떨림 방지

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
            # 모든 격자 실패 → 마지막으로 코너 탈출(BFS로 빠져나간 뒤 A*) 1회 시도.
            # 좁은 모서리/장애물 옆에 끼어 A* 시작점이 막힌 경우를 구제한다.
            if (not job.get("escape_tried")) and bool(CONFIG.get("PATHFIND_CORNER_ESCAPE_ENABLED", True)):
                job["escape_tried"] = True
                base_vis = int(job.get("base_vis") or 200)
                grid_anchor = min(grids) if grids else max(1, int(CONFIG.get("PATHFIND_GRID_PX", 5)))
                mv_esc = max(base_vis * 2, 5200)
                try:
                    raw = self._plan_path_corner_escape(
                        job["tx"], job["ty"], mask_img, objects or [], npcs or [],
                        (job["sx"], job["sy"]), grid_anchor, mv_esc,
                    )
                except Exception:
                    raw = []
                if self._apply_raw_path(raw, grid_anchor):
                    self._path_plan_job = None
                    return
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
            self._apply_raw_path(raw, g)
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

    def _walk_probe(self, x, y, mask_img, objects, npcs):
        """check_walkable 와 동일 판정 + 막힌 사유를 함께 반환.

        반환: (walkable, layer, reason)
          reason in (None, "bounds", "terrain", "layer", "object", "npc")
        """
        cx, cy = int(x), int(y)
        if not (0 <= cx < mask_img.get_width() and 0 <= cy < mask_img.get_height()):
            return False, self.layer, "bounds"

        if mask_terrain_class(mask_img, x, y) != "walk":
            return False, self.layer, "terrain"

        col = mask_img.get_at((cx, cy))
        r, g, b = col[0], col[1], col[2]
        new_layer = self.layer
        can_pass = False

        # 층수 판정 (도랑 색은 mask_terrain_class에서 이미 제외됨)
        if r > 180 and g > 180 and b > 180: new_layer = 0; can_pass = True
        elif r > g and r > b: new_layer = 1; can_pass = True
        elif g > r and g > b: new_layer = 2; can_pass = True
        elif b > r and b > g: new_layer = 3; can_pass = True

        if not can_pass: return False, self.layer, "layer"

        # 오브젝트 충돌 (살짝 넉넉하게 판정하여 끼임 방지)
        for o in objects:
            if o.collision and not getattr(o, 'is_held', False) and getattr(o, 'layer', 0) == new_layer:
                rw = o.rect_for_logic.width // 2 - 2 # 2픽셀 여유
                if abs(o.pos[0] - x) < rw and -8 < y - o.pos[1] < 1:
                    return False, new_layer, "object"

        if npcs:
            for n in npcs:
                if n != self and getattr(n, 'layer', 0) == new_layer:
                    if abs(n.pos[0] - x) < 10 and -8 < y - n.pos[1] < 1:
                        return False, new_layer, "npc"

        return True, new_layer, None

    def check_walkable(self, x, y, mask_img, objects, npcs):
        """기존의 복잡한 레이어 및 충돌 판정을 독립적으로 수행합니다."""
        walkable, layer, _ = self._walk_probe(x, y, mask_img, objects, npcs)
        return walkable, layer

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

            walkable, nl, block_reason = self._walk_probe(nx, ny, mask_img, objects, npcs)
            if walkable:
                self.pos = [nx, ny]
                self.layer = nl
                self.state = "run" if str(getattr(self, "_move_mode", "walk")) == "run" else "walk"
                self._fire_jump_pad_hooks(mask_img, objects, npcs)
                # 직진 성공 → 회피/스티어 상태 초기화(다시 막히면 새로 판단)
                self._avoid_block_since_ms = 0
                self._avoid_replans = 0
                self._steer_side = 0
            else:
                # 캐릭터/오브젝트에 막힌 경우: 멈추지 말고 목표 방향으로 비껴 가며 우회 시도
                if self._try_avoid(block_reason, mask_img, objects, npcs, desired_dx=dx, desired_dy=dy):
                    return
                self.path = []
                self.state = "idle"
                self.event_waypoints = None
                self._avoid_reset()

    def _avoid_reset(self):
        self._avoid_block_since_ms = 0
        self._avoid_replans = 0
        self._avoid_next_replan_ms = 0
        self._steer_side = 0

    def _steer_around_step(self, desired_dx, desired_dy, mask_img, objects, npcs):
        """막힌 목표 방향 기준으로 좌우로 각도를 틀어, 갈 수 있는 가장 가까운 방향으로 한 칸 전진.

        명령 즉시 그 방향으로 움직이며 장애물을 따라 비껴 가도록 한다(벽 슬라이드/스티어링).
        좌우 떨림 방지를 위해 직전에 택한 방향(_steer_side)을 우선 시도한다.
        실제로 한 칸 전진했으면 True.
        """
        if mask_img is None:
            return False
        if abs(float(desired_dx)) < 1e-9 and abs(float(desired_dy)) < 1e-9:
            return False
        try:
            spd = float(CONFIG["CHAR_SPEED"]) * float(getattr(self, "event_speed_mul", 1.0) or 1.0)
        except Exception:
            spd = float(CONFIG.get("CHAR_SPEED", 1.6))
        base = math.atan2(float(desired_dy), float(desired_dx))
        try:
            max_deg = float(CONFIG.get("AVOID_STEER_MAX_DEG", 105))
        except Exception:
            max_deg = 105.0
        try:
            step_deg = float(CONFIG.get("AVOID_STEER_STEP_DEG", 18))
        except Exception:
            step_deg = 18.0
        step_deg = max(5.0, min(45.0, step_deg))
        max_deg = max(step_deg, min(150.0, max_deg))

        pref = int(getattr(self, "_steer_side", 0) or 0)
        # 시도 각도(라디안) 목록: 크기를 키워 가며, 같은 크기에서는 선호 방향 먼저.
        offsets = []
        d = step_deg
        while d <= max_deg + 1e-6:
            if pref >= 0:
                offsets.append(+d)
                offsets.append(-d)
            else:
                offsets.append(-d)
                offsets.append(+d)
            d += step_deg

        for off_deg in offsets:
            a = base + math.radians(off_deg)
            nx = self.pos[0] + math.cos(a) * spd
            ny = self.pos[1] + math.sin(a) * spd
            walkable, nl, _ = self._walk_probe(nx, ny, mask_img, objects, npcs)
            if walkable:
                self.pos = [nx, ny]
                self.layer = nl
                stepx = math.cos(a) * spd
                try:
                    dir_eps = float(CONFIG.get("DIR_CHANGE_EPS_X", 0.28))
                except Exception:
                    dir_eps = 0.28
                if abs(stepx) >= dir_eps:
                    self.direction = "left" if stepx < 0 else "right"
                self.state = "run" if str(getattr(self, "_move_mode", "walk")) == "run" else "walk"
                self._steer_side = 1 if off_deg > 0 else -1
                self._fire_jump_pad_hooks(mask_img, objects, npcs)
                return True
        return False

    def _terrain_walk_ok(self, x, y, mask_img):
        """엔티티는 무시하고 지형만 walk 인지(끼임 탈출용)."""
        cx, cy = int(x), int(y)
        if not (0 <= cx < mask_img.get_width() and 0 <= cy < mask_img.get_height()):
            return False
        return mask_terrain_class(mask_img, x, y) == "walk"

    def _nearest_blocker_pos(self, objects, npcs):
        """현재 위치와 겹쳐 있는 가장 가까운 오브젝트/NPC 의 중심 좌표(없으면 None)."""
        px, py = float(self.pos[0]), float(self.pos[1])
        best = None
        best_d = None
        for o in objects or []:
            if getattr(o, "collision", False) and not getattr(o, "is_held", False) and getattr(o, "layer", 0) == self.layer:
                try:
                    rw = o.rect_for_logic.width // 2 - 2
                except Exception:
                    rw = 8
                if abs(o.pos[0] - px) < rw and -8 < py - o.pos[1] < 1:
                    d = math.hypot(px - o.pos[0], py - o.pos[1])
                    if best_d is None or d < best_d:
                        best_d = d
                        best = (float(o.pos[0]), float(o.pos[1]))
        for n in npcs or []:
            if n is not self and getattr(n, "layer", 0) == self.layer:
                if abs(n.pos[0] - px) < 10 and -8 < py - n.pos[1] < 1:
                    d = math.hypot(px - n.pos[0], py - n.pos[1])
                    if best_d is None or d < best_d:
                        best_d = d
                        best = (float(n.pos[0]), float(n.pos[1]))
        return best

    def _unstick_step(self, mask_img, objects, npcs):
        """현재 위치가 엔티티와 겹쳐 끼었으면 장애물 반대 방향으로 한 칸 빠져나온다.

        처리(이동)했으면 True. 겹침이 아니거나 빠져나갈 지형이 없으면 False.
        지형(벽/도랑)만 검사하고 엔티티는 무시한다 — 겹친 상태에서 빠져나오는 동작이므로.
        """
        if mask_img is None:
            return False
        walkable, _, reason = self._walk_probe(self.pos[0], self.pos[1], mask_img, objects, npcs)
        if walkable or reason not in ("object", "npc"):
            return False
        blocker = self._nearest_blocker_pos(objects, npcs)
        if blocker is None:
            return False
        dx = float(self.pos[0]) - blocker[0]
        dy = float(self.pos[1]) - blocker[1]
        ln = math.hypot(dx, dy)
        base = math.atan2(dy, dx) if ln > 1e-6 else math.pi  # 겹침 중심이면 좌측으로
        try:
            spd = float(CONFIG["CHAR_SPEED"]) * float(getattr(self, "event_speed_mul", 1.0) or 1.0)
        except Exception:
            spd = float(CONFIG.get("CHAR_SPEED", 1.6))
        # 반대방향을 중심으로 약간씩 각도를 틀어 지형이 허용하는 첫 후보로 빠져나온다.
        for off in (0.0, 0.6, -0.6, 1.2, -1.2, math.pi):
            a = base + off
            nx = self.pos[0] + math.cos(a) * spd
            ny = self.pos[1] + math.sin(a) * spd
            if not self._terrain_walk_ok(nx, ny, mask_img):
                continue
            self.pos = [nx, ny]
            if abs(math.cos(a)) > 0.05:
                self.direction = "left" if math.cos(a) < 0 else "right"
            self.state = "walk"
            return True
        return False

    def _apply_raw_path(self, raw, grid_for_cut):
        """A* raw 결과를 현재 위치 기준으로 잘라 self.path 에 적용. 적용하면 True."""
        if not raw:
            return False
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
            near_cut = float(CONFIG.get("PATHFIND_ATTACH_NEAR_CUT_PX", max(6.0, float(grid_for_cut) * 2.0)))
        except Exception:
            near_cut = max(6.0, float(grid_for_cut) * 2.0)
        if best_d is not None and best_d <= near_cut:
            raw2 = raw[int(best_i):]
        else:
            raw2 = raw
        self.path = [(float(p[0]), float(p[1]), 0) for p in (raw2 or raw)]
        self._strip_redundant_path_head()
        return True

    def _try_avoid(self, reason, mask_img, objects, npcs, desired_dx=0.0, desired_dy=0.0):
        """이동 중 엔티티에 막혔을 때: 멈추지 말고 즉시 목표 방향으로 비껴 가며 우회. 처리했으면 True.

        우선순위:
          1) 끼임(겹침) → 장애물 반대로 빠져나옴
          2) 스티어링(벽 슬라이드) → 목표 방향 기준 좌우로 틀어 한 칸 전진(즉각 반응)
          3) 스티어 불가(거의 갇힘)일 때만 A* 재계획/양보로 폴백
        지형(벽/도랑/경계)·층 변화·강제이동·달리기에는 관여하지 않는다(기존처럼 정지).
        백그라운드 A* 경로가 완성되면 자연스럽게 그 경로로 전환된다.
        """
        # 엔티티(object/npc)뿐 아니라 맵 마스크 벽/모서리/경계(terrain/bounds/layer)도
        # 멈추지 말고 벽을 따라 미끄러지며 목표 방향으로 가도록 처리한다.
        if reason not in ("object", "npc", "terrain", "bounds", "layer"):
            return False
        if not bool(CONFIG.get("AVOID_ENABLED", True)):
            return False
        if getattr(self, "_event_force_move", False):
            return False
        if str(getattr(self, "_move_mode", "walk")) == "run":
            return False

        now = pygame.time.get_ticks()
        if int(getattr(self, "_avoid_block_since_ms", 0) or 0) == 0:
            self._avoid_block_since_ms = now
        blocked_ms = now - int(self._avoid_block_since_ms)

        # 1) 끼임 해소 최우선(엔티티와 겹친 경우만): 겹친 상태에선 경로를 못 따라가므로 반대로 빠져나온다.
        if reason in ("object", "npc") and self._unstick_step(mask_img, objects, npcs):
            return True

        # 2) 스티어링: 목표 방향으로 즉시 비껴 가며 전진(명령 즉시 반응 + 장애물 따라 돌기).
        #    움직이는 NPC가 막은 경우엔 잠깐(AVOID_NPC_WAIT_MS) 양보 후 비껴 간다.
        npc_wait = reason == "npc" and blocked_ms < int(CONFIG.get("AVOID_NPC_WAIT_MS", 250))
        if not npc_wait:
            if self._steer_around_step(desired_dx, desired_dy, mask_img, objects, npcs):
                return True

        # 3) 스티어 실패(거의 갇힘) → A* 재계획으로 우회로 확보(백그라운드 진행 중이면 대기).
        if getattr(self, "_path_plan_job", None):
            self.state = "idle"
            return True
        if blocked_ms > int(CONFIG.get("AVOID_GIVEUP_MS", 1500)):
            return False  # 너무 오래 못 뚫으면 정지
        if npc_wait:
            self.state = "idle"
            return True
        if now >= int(getattr(self, "_avoid_next_replan_ms", 0) or 0) and \
           int(getattr(self, "_avoid_replans", 0) or 0) < int(CONFIG.get("AVOID_MAX_REPLANS", 4)):
            self._avoid_next_replan_ms = now + int(CONFIG.get("AVOID_REPLAN_COOLDOWN_MS", 350))
            self._avoid_replans = int(getattr(self, "_avoid_replans", 0) or 0) + 1
            tgt = list(getattr(self, "target", None) or self.pos)
            self.set_new_target(
                tgt[0], tgt[1], mask_img, objects, npcs,
                preserve_path_anim=True, clear_event_waypoints=False,
                avoid_replan=True,
            )
            self.path = []
            self.state = "idle"
            return True

        self.state = "idle"
        return True

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

    def set_new_target(self, tx, ty, mask_img=None, objects=None, npcs=None, preserve_path_anim=False, clear_event_waypoints=True, avoid_replan=False):
        """목표가 생기면 경로를 미리 짜둡니다."""
        # 외부에서 새 목표를 줄 때만 회피 누적 상태 초기화(회피 재계획은 누적 유지).
        if not avoid_replan:
            self._avoid_reset()
        if clear_event_waypoints:
            self.event_waypoints = None
        if not preserve_path_anim:
            self.clear_anim_override()
        self._jump_arc = None
        # 새 목표면 기존 계획 취소
        self._path_plan_job = None
        tx, ty = float(tx), float(ty)
        self.target = [tx, ty]
        # 회피 재계획 중에는 방향을 목표 쪽으로 강제로 돌리지 않는다(좌우 흔들림 방지).
        if not avoid_replan:
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
                if not avoid_replan:
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
        self._avoid_reset()
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


def shear_base_offset_px(y_screen, x_offset_fn):
    """쉬어(기울기) 가로 오프셋을 '정수 + y 격자 양자화'로 계산한다.

    연속 실수 오프셋을 매 프레임 final round 직전에 더하면, 카메라가 미세하게 흔들릴 때
    입력 y(→오프셋)가 흔들리고 그것이 스프라이트 월드좌표 소수부(짝/홀)와 맞물려 ±1px로 떨린다.
    입력 y를 슬라이스 양자화(SPRITE_SHEAR_Y_QUANT_PX, 배경/필드 슬라이스 쉬어와 동일)에 맞추고
    결과를 정수로 만들어, 본체·그림자·필드 오브젝트가 모두 같은 정수 오프셋으로 lockstep 이동하게 한다.
    """
    if not callable(x_offset_fn):
        return 0
    if not bool(CONFIG.get("SHEAR_SPRITE_STABILIZE", True)):
        try:
            return int(round(float(x_offset_fn(float(y_screen)))))
        except Exception:
            return 0
    try:
        q = int(CONFIG.get("SPRITE_SHEAR_Y_QUANT_PX", 2) or 2)
    except Exception:
        q = 2
    q = max(1, min(32, q))
    try:
        yq = round(float(y_screen) / q) * q
        return int(round(float(x_offset_fn(float(yq)))))
    except Exception:
        try:
            return int(round(float(x_offset_fn(float(y_screen)))))
        except Exception:
            return 0


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
    x_scale_fn=None,
    x_shift_fn=None,
    pivot_xy=None,
    cam_angle_rad=0.0,
    mode7_ctx=None,
    anchor_x=0.5,
    view_w=None,
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
    flat_x = float((float(world_x) - float(cam_x)) * z)
    flat_y = float((float(world_y) - float(cam_y)) * z)
    anc = (anchor or "feet").strip().lower()
    h_off = float(height or 0.0) if anc in ("feet", "foot", "ground", "bottom") else 0.0
    if mode7_ctx:
        pr = rotate3d_mode7_project(
            float(world_x),
            float(world_y),
            mode7_ctx,
            height_off=h_off,
            zoom=z,
        )
        if not pr or not pr.get("valid", pr.get("visible")):
            return -1e6, -1e6
        return float(pr["sx"]), float(pr["sy"])
    if callable(x_scale_fn) or callable(x_shift_fn) or pivot_xy is not None:
        try:
            vw = float(view_w if view_w is not None else CONFIG.get("WIDTH", 640))
        except Exception:
            vw = 640.0
        return map_feet_screen_xy(
            flat_x,
            flat_y,
            y_transform=y_transform,
            x_scale_fn=x_scale_fn,
            x_shift_fn=x_shift_fn,
            x_offset_fn=x_offset_fn,
            pivot_xy=pivot_xy,
            cam_angle_rad=float(cam_angle_rad),
            anchor_x=float(anchor_x),
            view_w=vw,
            height_off=h_off,
            zoom=z,
        )
    dx_base = flat_x
    dy_base = flat_y
    if callable(y_transform):
        try:
            dy_base = float(y_transform(dy_base))
        except Exception:
            pass
    dy_q = float(int(round(float(dy_base))))
    if callable(x_offset_fn):
        dx_base = float(dx_base) + float(shear_base_offset_px(dy_base, x_offset_fn))
    if h_off > 0.0:
        dy_base = float(dy_q) - h_off * z
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
    anchor_y_from_top = int(render_img.get_height())

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
        top_y = float(dy_base) - float(anchor_y_from_top)
        bot_y = float(dy_base) + float(render_img.get_height() - int(anchor_y_from_top))
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
        g_cached = _sprite_field_shear_cache_get(skey)
        if g_cached is not None:
            render_img, dx_adj = g_cached[0], int(g_cached[1])
        else:
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
                _sprite_field_shear_cache_put(skey, render_img, dx_adj)
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
    final_dy = float(feet_sy - float(anchor_y_from_top))
    return render_img, int(round(final_dx)), int(round(final_dy))


# =============================================================================
# 엔티티 FX (이벤트 FX 스텝 kind=entity_fx)
# 캐릭터·오브젝트 스프라이트 불투명 픽셀에 단색을 섞어 반짝임(pulse) 또는 고정 틴트(tint).
# FieldItem.draw · BaseCharacter.draw 에서 _apply_entity_fx_to_image() 호출.
# =============================================================================

_ENTITY_FX_TINT_CACHE = OrderedDict()


def _entity_fx_cache_max_items():
    try:
        return max(16, min(512, int(CONFIG.get("ENTITY_FX_TINT_CACHE_MAX", 96) or 96)))
    except Exception:
        return 96


def _entity_fx_parse_rgb(step_or_val, default=(255, 240, 160)):
    raw = step_or_val
    if isinstance(step_or_val, dict):
        raw = step_or_val.get("color") or step_or_val.get("rgb") or step_or_val.get("tint")
    if raw is None:
        return tuple(int(default[i]) for i in range(3))
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            return (
                int(max(0, min(255, float(raw[0])))),
                int(max(0, min(255, float(raw[1])))),
                int(max(0, min(255, float(raw[2])))),
            )
        except (TypeError, ValueError):
            pass
    s = str(raw or "").strip()
    if not s:
        return tuple(int(default[i]) for i in range(3))
    try:
        parts = [int(float(x.strip())) for x in s.replace(";", ",").split(",") if x.strip() != ""]
        if len(parts) >= 3:
            return (
                max(0, min(255, parts[0])),
                max(0, min(255, parts[1])),
                max(0, min(255, parts[2])),
            )
    except (TypeError, ValueError):
        pass
    return tuple(int(default[i]) for i in range(3))


def entity_fx_strength(fx) -> float:
    """FX 상태 → 0~1 (불투명 픽셀에 섞을 단색 비율)."""
    if not fx:
        return 0.0
    mode = (fx.get("mode") or "pulse").strip().lower()
    try:
        peak = int(fx.get("alpha", fx.get("alpha_max", 160) or 160))
    except (TypeError, ValueError):
        peak = 160
    peak = max(0, min(255, peak))
    if mode in ("tint", "cover", "solid", "overlay"):
        return peak / 255.0
    try:
        cycle = float(fx.get("cycle_sec", fx.get("speed", 1.0) or 1.0))
    except (TypeError, ValueError):
        cycle = 1.0
    cycle = max(0.15, min(30.0, cycle))
    phase = float(fx.get("phase_sec", 0.0) or 0.0)
    u = (math.sin(2.0 * math.pi * phase / cycle) + 1.0) * 0.5
    return max(0.0, min(1.0, u * (peak / 255.0)))


def tick_entity_fx_state(fx, dt_sec: float) -> None:
    """pulse 모드 phase 진행 (실제 경과 초)."""
    if not fx:
        return
    mode = (fx.get("mode") or "pulse").strip().lower()
    if mode in ("tint", "cover", "solid", "overlay"):
        return
    fx["phase_sec"] = float(fx.get("phase_sec", 0.0) or 0.0) + max(0.0, float(dt_sec))


def _tint_sprite_lerp_opaque(src, rgb, strength: float):
    """불투명 픽셀만 원본↔단색 선형 보간. strength 0=원본."""
    strength = max(0.0, min(1.0, float(strength)))
    if strength <= 1e-6:
        return src
    sq = int(round(strength * 64.0))
    tr, tg, tb = [int(max(0, min(255, int(rgb[i])))) for i in range(3)]
    key = (id(src), sq, tr, tg, tb)
    hit = _ENTITY_FX_TINT_CACHE.get(key)
    if hit is not None:
        return hit
    out = src.copy()
    inv = 1.0 - strength
    w, h = out.get_size()
    for y in range(h):
        for x in range(w):
            c = out.get_at((x, y))
            a = c[3]
            if a <= 8:
                continue
            out.set_at(
                (x, y),
                (
                    int(c[0] * inv + tr * strength),
                    int(c[1] * inv + tg * strength),
                    int(c[2] * inv + tb * strength),
                    a,
                ),
            )
    try:
        _ENTITY_FX_TINT_CACHE[key] = out
        while len(_ENTITY_FX_TINT_CACHE) > _entity_fx_cache_max_items():
            _ENTITY_FX_TINT_CACHE.popitem(last=False)
    except Exception:
        pass
    return out


def apply_entity_fx_to_image(img, fx):
    if img is None or not fx:
        return img
    try:
        strength = entity_fx_strength(fx)
        if strength <= 1e-6:
            return img
        rgb = fx.get("color")
        if not rgb:
            return img
        return _tint_sprite_lerp_opaque(img, rgb, strength)
    except Exception:
        return img


def clear_entity_fx(entity) -> None:
    try:
        entity.entity_fx = None
    except Exception:
        pass


def clamp_entity_def_zoom(val) -> float:
    try:
        zmin = float(CONFIG.get("ENTITY_ZOOM_MIN", 0.5))
        zmax = float(CONFIG.get("ENTITY_ZOOM_MAX", 2.0))
    except Exception:
        zmin, zmax = 0.5, 2.0
    try:
        z = float(val)
    except (TypeError, ValueError):
        z = 1.0
    return max(zmin, min(zmax, z))


def entity_combined_zoom_mul(entity) -> float:
    """def·progress·binding 줌 × 이벤트 ZOOM 스텝 줌."""
    try:
        dz = float(getattr(entity, "entity_def_zoom", 1.0) or 1.0)
    except Exception:
        dz = 1.0
    try:
        ez = float(getattr(entity, "event_entity_zoom", 1.0) or 1.0)
    except Exception:
        ez = 1.0
    return max(0.05, min(8.0, dz)) * max(0.05, min(8.0, ez))


def clear_entity_visual(entity) -> None:
    clear_entity_fx(entity)
    try:
        entity.entity_def_zoom = 1.0
    except Exception:
        pass


def apply_entity_visual_patch(entity, patch) -> None:
    """def·binding·progress 의 entity_fx + zoom (False/ stop = 시각효과 전부 끔)."""
    if entity is None:
        return
    if patch is None:
        return
    if patch is False:
        clear_entity_visual(entity)
        return
    if isinstance(patch, str):
        if patch.strip().lower() in ("false", "off", "stop", "clear", "none", "0"):
            clear_entity_visual(entity)
        return
    if not isinstance(patch, dict):
        return
    action = (patch.get("action") or patch.get("cmd") or "start").strip().lower()
    if action in ("stop", "clear", "off", "remove", "end"):
        clear_entity_visual(entity)
        return
    if patch.get("enabled") is False:
        clear_entity_visual(entity)
        return

    mode = (patch.get("mode") or patch.get("efx_mode") or patch.get("fx_mode") or "").strip().lower()
    has_tint = bool(mode and mode not in ("off", "none", "clear", "stop"))
    has_tint = has_tint or any(
        patch.get(k) is not None and str(patch.get(k)).strip() != ""
        for k in ("color", "efx_color", "rgb", "alpha", "efx_alpha", "cycle_sec", "efx_cycle_sec", "speed")
    )
    if mode in ("off", "none", "clear", "stop"):
        clear_entity_fx(entity)
    elif has_tint:
        step = {
            "mode": mode or "pulse",
            "color": patch.get("color") or patch.get("efx_color") or patch.get("rgb"),
            "alpha": patch.get("alpha", patch.get("efx_alpha")),
            "cycle_sec": patch.get("cycle_sec", patch.get("efx_cycle_sec", patch.get("speed"))),
        }
        entity.entity_fx = build_entity_fx_from_step(step)

    if "zoom" in patch:
        try:
            entity.entity_def_zoom = clamp_entity_def_zoom(patch.get("zoom"))
        except Exception:
            pass
    elif mode in ("off", "none", "clear", "stop") and not has_tint:
        try:
            entity.entity_def_zoom = 1.0
        except Exception:
            pass


def apply_entity_fx_patch(entity, patch) -> None:
    """하위 호환 별칭 — tint·zoom 통합 패치."""
    apply_entity_visual_patch(entity, patch)


def _entity_visual_snapshot(ent) -> dict:
    fx = getattr(ent, "entity_fx", None)
    if isinstance(fx, dict):
        fx = dict(fx)
    try:
        dz = float(getattr(ent, "entity_def_zoom", 1.0) or 1.0)
    except Exception:
        dz = 1.0
    try:
        ez = float(getattr(ent, "event_entity_zoom", 1.0) or 1.0)
    except Exception:
        ez = 1.0
    try:
        ezt = float(getattr(ent, "event_entity_zoom_target", 1.0) or 1.0)
    except Exception:
        ezt = 1.0
    return {
        "entity_fx": fx,
        "entity_def_zoom": dz,
        "event_entity_zoom": ez,
        "event_entity_zoom_target": ezt,
        "event_entity_zoom_timed": getattr(ent, "event_entity_zoom_timed", None),
    }


def _entity_visual_restore(ent, snap: dict) -> None:
    if not snap:
        return
    try:
        ent.entity_fx = snap.get("entity_fx")
        ent.entity_def_zoom = float(snap.get("entity_def_zoom", 1.0) or 1.0)
        ent.event_entity_zoom = float(snap.get("event_entity_zoom", 1.0) or 1.0)
        ent.event_entity_zoom_target = float(snap.get("event_entity_zoom_target", 1.0) or 1.0)
        ent.event_entity_zoom_timed = snap.get("event_entity_zoom_timed")
    except Exception:
        pass


def build_entity_fx_from_step(step: dict) -> dict:
    """FX entity_fx 스텝 → entity.entity_fx dict."""
    mode = (step.get("mode") or step.get("fx_mode") or "pulse").strip().lower()
    if mode in ("shimmer", "glow", "blink", "sparkle"):
        mode = "pulse"
    try:
        alpha = int(float(step.get("alpha", step.get("alpha_max", 160) or 160)))
    except (TypeError, ValueError):
        alpha = 160
    alpha = max(0, min(255, alpha))
    try:
        cycle = float(
            step.get("cycle_sec")
            if step.get("cycle_sec") is not None
            else step.get("speed", CONFIG.get("ENTITY_FX_DEFAULT_CYCLE_SEC", 1.0))
        )
    except (TypeError, ValueError):
        cycle = 1.0
    cycle = max(0.15, min(30.0, cycle))
    return {
        "mode": mode,
        "color": _entity_fx_parse_rgb(step),
        "alpha": alpha,
        "cycle_sec": cycle,
        "phase_sec": 0.0,
    }


# 화면 전체 FX (이벤트 SCREEN_FX — kind: cloud | flash | shake | rain | vignette | tone)
# cloud: 구름 그림자 (field_runtime)
# flash: 논리 해상도 전체 색 오버레이 pulse/tint
# shake: 합성 프레임 오프셋 (main.py 렌더 말미)
# rain: 전경 비 라인 파티클 (SRCALPHA 오버레이)
# vignette: 가장자리 어둡게 (SRCALPHA radial)
# tone: 화이트밸런스/색온도 틴트 (warm/cool/custom)
# =============================================================================

_vignette_surf_cache = {}


def resolve_screen_fx_kind(step) -> str:
    """SCREEN_FX 스텝 → cloud | flash | shake | rain | vignette | tone."""
    if not isinstance(step, dict):
        return "cloud"
    k = str(step.get("kind") or step.get("sfx_kind") or step.get("name") or "").strip().lower()
    if k in ("cloud", "cloudshadow", "cloud_shadow", "cloud-shadow"):
        return "cloud"
    if k in ("screen_flash", "flash", "fullscreen_flash", "screen_glow"):
        return "flash"
    if k in ("screen_shake", "shake", "screen_quake", "quake"):
        return "shake"
    if k in ("rain", "screen_rain", "비"):
        return "rain"
    if k in ("vignette", "screen_vignette", "비네팅"):
        return "vignette"
    if k in ("tone", "screen_tone", "white_balance", "whitebalance", "wb", "색온도", "톤"):
        return "tone"
    if k in ("all", "clear", "none", "reset", "off"):
        return "all"
    if k in ("cloud", "flash", "shake", "rain", "vignette", "tone"):
        return k
    return "cloud"


def build_cloud_shadow_control_from_step(step: dict) -> dict:
    """SCREEN_FX kind=cloud → cloud_shadow_control dict."""
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
    return d


def build_screen_flash_from_step(step: dict) -> dict:
    """SCREEN_FX kind=flash → screen_fx_flash dict."""
    mode = (step.get("flash_mode") or step.get("mode") or "pulse").strip().lower()
    if mode in ("shimmer", "glow", "blink", "sparkle", "flash"):
        mode = "pulse"
    try:
        alpha = int(float(step.get("alpha", step.get("alpha_max", CONFIG.get("SCREEN_FX_FLASH_DEFAULT_ALPHA", 140)) or 140)))
    except (TypeError, ValueError):
        alpha = int(CONFIG.get("SCREEN_FX_FLASH_DEFAULT_ALPHA", 140) or 140)
    alpha = max(0, min(255, alpha))
    try:
        cycle = float(
            step.get("cycle_sec")
            if step.get("cycle_sec") is not None
            else step.get("speed", CONFIG.get("SCREEN_FX_FLASH_DEFAULT_CYCLE_SEC", 0.7))
        )
    except (TypeError, ValueError):
        cycle = float(CONFIG.get("SCREEN_FX_FLASH_DEFAULT_CYCLE_SEC", 0.7) or 0.7)
    cycle = max(0.15, min(30.0, cycle))
    return {
        "enabled": True,
        "mode": mode,
        "color": _entity_fx_parse_rgb(step, (255, 255, 255)),
        "alpha": alpha,
        "cycle_sec": cycle,
        "phase_sec": 0.0,
    }


def build_screen_shake_from_step(step: dict) -> dict:
    """SCREEN_FX kind=shake → screen_fx_shake dict."""
    try:
        amp = float(step.get("amp_px", step.get("amp", CONFIG.get("SCREEN_FX_SHAKE_DEFAULT_AMP_PX", 7)) or 7))
    except (TypeError, ValueError):
        amp = float(CONFIG.get("SCREEN_FX_SHAKE_DEFAULT_AMP_PX", 7) or 7)
    amp = max(0.0, min(48.0, amp))
    try:
        freq = float(step.get("freq_hz", step.get("freq", CONFIG.get("SCREEN_FX_SHAKE_DEFAULT_FREQ_HZ", 14)) or 14))
    except (TypeError, ValueError):
        freq = float(CONFIG.get("SCREEN_FX_SHAKE_DEFAULT_FREQ_HZ", 14) or 14)
    freq = max(0.5, min(60.0, freq))
    return {
        "enabled": True,
        "amp_px": amp,
        "freq_hz": freq,
        "phase_sec": 0.0,
    }


def build_screen_vignette_from_step(step: dict) -> dict:
    """SCREEN_FX kind=vignette → screen_fx_vignette dict."""
    try:
        strength = float(step.get("strength", CONFIG.get("SCREEN_FX_VIGNETTE_DEFAULT_STRENGTH", 0.55) or 0.55))
    except (TypeError, ValueError):
        strength = float(CONFIG.get("SCREEN_FX_VIGNETTE_DEFAULT_STRENGTH", 0.55) or 0.55)
    strength = max(0.0, min(1.0, strength))
    try:
        size = float(step.get("size", step.get("inner", CONFIG.get("SCREEN_FX_VIGNETTE_DEFAULT_SIZE", 0.42) or 0.42)))
    except (TypeError, ValueError):
        size = float(CONFIG.get("SCREEN_FX_VIGNETTE_DEFAULT_SIZE", 0.42) or 0.42)
    size = max(0.0, min(0.95, size))
    try:
        softness = float(step.get("softness", CONFIG.get("SCREEN_FX_VIGNETTE_DEFAULT_SOFTNESS", 0.65) or 0.65))
    except (TypeError, ValueError):
        softness = float(CONFIG.get("SCREEN_FX_VIGNETTE_DEFAULT_SOFTNESS", 0.65) or 0.65)
    softness = max(0.05, min(1.0, softness))
    return {
        "enabled": True,
        "strength": strength,
        "size": size,
        "softness": softness,
        "color": _entity_fx_parse_rgb(step, (0, 0, 0)),
    }


def _screen_fx_tone_preset_rgb(preset: str):
    """톤 preset → RGB (오버레이 틴트 색)."""
    p = str(preset or "warm").strip().lower()
    if p in ("cool", "cold", "차가", "차가운", "blue"):
        raw = CONFIG.get("SCREEN_FX_TONE_COOL_RGB", (170, 205, 255))
    elif p in ("neutral", "none", "off", "중립"):
        raw = CONFIG.get("SCREEN_FX_TONE_NEUTRAL_RGB", (255, 255, 255))
    elif p in ("warm", "따뜻", "따뜻한", "orange"):
        raw = CONFIG.get("SCREEN_FX_TONE_WARM_RGB", (255, 210, 170))
    else:
        raw = CONFIG.get("SCREEN_FX_TONE_WARM_RGB", (255, 210, 170))
    try:
        return int(raw[0]), int(raw[1]), int(raw[2])
    except Exception:
        return 255, 210, 170


def build_screen_tone_from_step(step: dict) -> dict:
    """SCREEN_FX kind=tone → screen_fx_tone dict (warm/cool/neutral/custom)."""
    preset = str(
        step.get("preset") or step.get("tone") or step.get("white_balance") or step.get("mode") or "warm"
    ).strip().lower()
    if preset in ("따뜻", "따뜻한"):
        preset = "warm"
    elif preset in ("차가", "차가운"):
        preset = "cool"
    elif preset in ("중립",):
        preset = "neutral"
    if preset not in ("warm", "cool", "neutral", "custom"):
        preset = "warm"
    try:
        strength = float(step.get("strength", CONFIG.get("SCREEN_FX_TONE_DEFAULT_STRENGTH", 0.32) or 0.32))
    except (TypeError, ValueError):
        strength = float(CONFIG.get("SCREEN_FX_TONE_DEFAULT_STRENGTH", 0.32) or 0.32)
    strength = max(0.0, min(1.0, strength))
    if preset == "custom":
        color = _entity_fx_parse_rgb(step, _screen_fx_tone_preset_rgb("warm"))
    else:
        color = _screen_fx_tone_preset_rgb(preset)
    return {
        "enabled": True,
        "preset": preset,
        "strength": strength,
        "color": color,
    }


def _get_vignette_overlay_surf(w, h, strength, size, softness, color):
    """비네팅 SRCALPHA 서피스 — 파라미터별 캐시."""
    try:
        r, g, b = int(color[0]), int(color[1]), int(color[2])
    except Exception:
        r, g, b = 0, 0, 0
    key = (
        int(w),
        int(h),
        round(float(strength), 3),
        round(float(size), 3),
        round(float(softness), 3),
        r,
        g,
        b,
    )
    cached = _vignette_surf_cache.get(key)
    if cached is not None:
        return cached
    tex_n = 128
    tmp = pygame.Surface((tex_n, tex_n), pygame.SRCALPHA)
    cx = cy = (tex_n - 1) * 0.5
    max_r = math.hypot(cx, cy) or 1.0
    inner_r = max_r * float(size)
    span = max(1e-3, max_r * float(softness))
    smax = max(0.0, min(1.0, float(strength)))
    for y in range(tex_n):
        for x in range(tex_n):
            d = math.hypot(x - cx, y - cy)
            if d <= inner_r:
                a = 0
            else:
                t = min(1.0, (d - inner_r) / span)
                a = int(round(t * smax * 255.0))
            tmp.set_at((x, y), (r, g, b, a))
    try:
        surf = pygame.transform.smoothscale(tmp, (int(w), int(h)))
    except Exception:
        surf = pygame.transform.scale(tmp, (int(w), int(h)))
    if len(_vignette_surf_cache) > 24:
        _vignette_surf_cache.clear()
    _vignette_surf_cache[key] = surf
    return surf


def draw_screen_fx_vignette(target_surf, overlay_surf, fx) -> None:
    """비네팅 — 화면 가장자리 어둡게. tilt/shear/카메라 무관."""
    if target_surf is None or overlay_surf is None or not isinstance(fx, dict) or not fx.get("enabled"):
        return
    try:
        strength = float(fx.get("strength", 0.0) or 0.0)
    except Exception:
        strength = 0.0
    if strength <= 1e-6:
        return
    try:
        tw, th = target_surf.get_size()
    except Exception:
        return
    if overlay_surf.get_size() != (tw, th):
        return
    vignette = _get_vignette_overlay_surf(
        tw,
        th,
        strength,
        float(fx.get("size", 0.42) or 0.42),
        float(fx.get("softness", 0.65) or 0.65),
        fx.get("color") or (0, 0, 0),
    )
    target_surf.blit(vignette, (0, 0))


def draw_screen_fx_tone(target_surf, overlay_surf, fx) -> None:
    """색온도/톤 틴트 — warm/cool/custom. tilt/shear/카메라 무관."""
    if target_surf is None or overlay_surf is None or not isinstance(fx, dict) or not fx.get("enabled"):
        return
    preset = str(fx.get("preset") or "warm").strip().lower()
    if preset == "neutral":
        return
    try:
        strength = float(fx.get("strength", 0.0) or 0.0)
    except Exception:
        strength = 0.0
    if strength <= 1e-6:
        return
    try:
        tw, th = target_surf.get_size()
    except Exception:
        return
    if overlay_surf.get_size() != (tw, th):
        return
    rgb = fx.get("color") or (255, 210, 170)
    try:
        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    except Exception:
        r, g, b = 255, 210, 170
    alpha = int(round(max(0.0, min(1.0, strength)) * 255.0))
    if alpha <= 0:
        return
    overlay_surf.fill((r, g, b))
    overlay_surf.set_alpha(alpha)
    target_surf.blit(overlay_surf, (0, 0))
    overlay_surf.set_alpha(255)


def _screen_fx_rain_parse_angle(step: dict) -> float:
    """SCREEN_FX rain 각도(도) — 수직(↓) 기준. 0=수직, 45=대각, 클수록 바람 성분↑."""
    raw = step.get("angle", step.get("rain_angle", None))
    if raw is None or raw == "":
        try:
            return float(CONFIG.get("SCREEN_FX_RAIN_DEFAULT_ANGLE", 82) or 82)
        except Exception:
            return 82.0
    try:
        angle_deg = float(raw)
    except (TypeError, ValueError):
        try:
            return float(CONFIG.get("SCREEN_FX_RAIN_DEFAULT_ANGLE", 82) or 82)
        except Exception:
            return 82.0
    try:
        lo = float(CONFIG.get("SCREEN_FX_RAIN_ANGLE_MIN", 0) or 0)
        hi = float(CONFIG.get("SCREEN_FX_RAIN_ANGLE_MAX", 88) or 88)
    except Exception:
        lo, hi = 0.0, 88.0
    lo = max(0.0, min(89.0, lo))
    hi = max(lo, min(89.0, hi))
    return max(lo, min(hi, angle_deg))


def _screen_fx_rain_velocity(speed, angle_deg):
    """낙하 속도·각도 → 월드 vx, vy (vy>0 유지 — 재유입·낙하용)."""
    try:
        spd = float(speed)
    except (TypeError, ValueError):
        spd = float(CONFIG.get("SCREEN_FX_RAIN_DEFAULT_SPEED", 280) or 280)
    spd = max(20.0, min(900.0, spd))
    ang = _screen_fx_rain_parse_angle({"angle": angle_deg})
    rad = math.radians(ang)
    vx = math.sin(rad) * spd
    vy = math.cos(rad) * spd
    if vy < 1e-3:
        vy = 1e-3
    return float(vx), float(vy), float(ang)


def _screen_fx_rain_drop_count(density: float, view_w: float, view_h: float) -> int:
    """현재 뷰포트 면적 기준 드롭 수."""
    try:
        div = float(CONFIG.get("SCREEN_FX_RAIN_DENSITY_AREA_DIV", 280.0) or 280.0)
    except Exception:
        div = 280.0
    div = max(80.0, min(3000.0, div))
    try:
        max_drops = int(CONFIG.get("SCREEN_FX_RAIN_MAX_DROPS", 320) or 320)
    except Exception:
        max_drops = 320
    max_drops = max(8, min(600, max_drops))
    d = max(0.0, min(1.0, float(density)))
    return max(0, min(max_drops, int(d * view_w * view_h / div)))


def _screen_fx_rain_jitter(i: int, salt: int = 0) -> tuple:
    """인덱스별 0~1 의사난수 두 개.

    [중요] 예전 LCG(선형) 방식은 i·salt에 대해 결과가 선형이라, 재생성 salt가 (상수+k*i)
    꼴이면 연속 인덱스 드롭이 거의 같은 x에 몰려 '국지적으로 겹쳐 내리는' 뭉침이 생겼다.
    그래서 비트 혼합(xorshift/finalizer)로 바꿔 인접 인덱스도 무상관하게 흩어지도록 한다.
    """
    h = (int(i) * 0x9E3779B1 + int(salt) * 0x85EBCA77 + 0x165667B1) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 0x2C1B3C6D) & 0xFFFFFFFF
    h ^= h >> 12
    h = (h * 0x297A2D39) & 0xFFFFFFFF
    h ^= h >> 15
    a = (h & 0xFFFFFFFF) / 4294967295.0
    h2 = (h ^ 0x68E31DA4) & 0xFFFFFFFF
    h2 = (h2 * 0x2545F491) & 0xFFFFFFFF
    h2 ^= h2 >> 13
    h2 = (h2 * 0x9E3779B1) & 0xFFFFFFFF
    h2 ^= h2 >> 16
    b = (h2 & 0xFFFFFFFF) / 4294967295.0
    return a, b


def _screen_fx_rain_stratified_xy(i, n, left, top, width, height, salt=0):
    """격자+지터 — 영역 전체에 고르게 분포."""
    if n <= 0 or width <= 1e-6 or height <= 1e-6:
        return float(left), float(top)
    aspect = width / max(height, 1.0)
    cols = max(1, int(math.ceil(math.sqrt(n * aspect))))
    rows = max(1, (n + cols - 1) // cols)
    row = i // cols
    col = i % cols
    jx, jy = _screen_fx_rain_jitter(i, salt)
    cell_w = width / cols
    cell_h = height / rows
    x = left + (col + jx) * cell_w
    y = top + (row + jy) * cell_h
    return float(x), float(y)


def _screen_fx_rain_viewport_band(cam_x, cam_y, view_w, view_h):
    """카메라를 따라가는 월드 사각형(화면 + 사방 여백).

    드롭은 월드 좌표에 두고 카메라 스크롤·줌으로 화면에 투영한다.
    tilt/shear 는 draw 단계에서 적용하지 않는다(비는 수직/설정각 유지).
    """
    try:
        mx = float(CONFIG.get("SCREEN_FX_RAIN_MARGIN_X", 64) or 64)
    except Exception:
        mx = 64.0
    mt = mx
    below = 32.0
    left = float(cam_x) - mx
    top = float(cam_y) - mt
    width = float(view_w) + mx * 2.0
    height = mt + float(view_h) + below
    ground = float(cam_y) + float(view_h)
    return left, top, width, height, ground


def _screen_fx_rain_assign_profile(d, i, drop_len):
    """드롭에 '깊이 레이어' 프로파일을 부여(지속 필드).

    실제 게임 비처럼 원경/근경 2겹으로 나눠 깊이감을 준다. 인덱스 해시로 결정하므로
    매 프레임 재계산 없이 값이 고정되고(뭉침·깜빡임 없음), 레이어별로 속도·길이·밝기·
    굵기를 다르게 해 '일제히 떨어지는 장막' 현상을 없앤다.
      - lay=1 근경: 길고·진하고·빠르게 (필요시 굵게)
      - lay=0 원경: 짧고·흐리고·느리게 (가늘게)
    저장 필드: sp(속도배율) am(밝기배율) w(선 굵기) len(길이) lay(레이어)
    """
    try:
        near_ratio = float(CONFIG.get("SCREEN_FX_RAIN_NEAR_RATIO", 0.45) or 0.45)
    except Exception:
        near_ratio = 0.45
    near_ratio = max(0.0, min(1.0, near_ratio))
    a, b = _screen_fx_rain_jitter(i, 7)   # a: 레이어 선택, b: 속도 편차
    c, e = _screen_fx_rain_jitter(i, 23)  # c: 밝기 편차, e: 길이 편차
    base = max(2, int(drop_len))
    if a < near_ratio:
        d["lay"] = 1
        d["sp"] = 1.0 + 0.28 * b            # 1.00 ~ 1.28 (빠름)
        d["am"] = 0.82 + 0.18 * c           # 0.82 ~ 1.00 (진함)
        d["w"] = 1
        d["len"] = max(3, int(round(base * (1.0 + 0.35 * e))))  # 김
    else:
        d["lay"] = 0
        d["sp"] = 0.60 + 0.28 * b           # 0.60 ~ 0.88 (느림)
        d["am"] = 0.38 + 0.22 * c           # 0.38 ~ 0.60 (흐림)
        d["w"] = 1
        d["len"] = max(2, int(round(base * (0.45 + 0.30 * e))))  # 짧음


def _screen_fx_rain_assign_land_y(d, i, band_top, band_h, salt=0):
    """탑다운: 드롭마다 화면 밴드 안 랜덤 착지 y (여기 닿으면 스플래시 후 재유입)."""
    _f, g = _screen_fx_rain_jitter(int(i), 101 + int(salt))
    # 밴드 상단 여백 아래 ~ 하단 직전 사이. 화면 어디서든 착지하도록 전 구간 분포.
    d["land_y"] = float(band_top) + (0.12 + 0.86 * g) * float(band_h)


def _screen_fx_rain_ensure_drops(fx, view_w, view_h):
    density = float(fx.get("density", CONFIG.get("SCREEN_FX_RAIN_DEFAULT_DENSITY", 0.35)) or 0.35)
    n = _screen_fx_rain_drop_count(density, view_w, view_h)
    drop_len = int(fx.get("drop_len", CONFIG.get("SCREEN_FX_RAIN_DEFAULT_DROP_LEN", 7)) or 7)
    drops = fx.get("drops")
    if not isinstance(drops, list):
        drops = []
    while len(drops) < n:
        i = len(drops)
        nd = {}
        _screen_fx_rain_assign_profile(nd, i, drop_len)
        drops.append(nd)
    if len(drops) > n:
        del drops[n:]
    for i, d in enumerate(drops):
        if not isinstance(d, dict):
            d = {}
            drops[i] = d
        if "sp" not in d or "lay" not in d or "am" not in d:
            _screen_fx_rain_assign_profile(d, i, drop_len)
    fx["drops"] = drops
    return drops, n


def _screen_fx_rain_sync_viewport(fx, cam_x, cam_y, view_w, view_h) -> float:
    """드롭 개수 보장 + 최초/카메라 점프 시 월드 밴드에 균일 재분포. ground_y 반환.

    정상 스크롤 중에는 드롭을 건드리지 않는다(카메라 변환으로 자연스럽게 따라감).
    화면 밖 유출 재유입은 draw 루프의 _screen_fx_rain_respawn_drop 이 담당한다.
    """
    drops, n = _screen_fx_rain_ensure_drops(fx, view_w, view_h)
    band_left, band_top, band_w, band_h, ground_y = _screen_fx_rain_viewport_band(
        cam_x, cam_y, view_w, view_h
    )
    last = fx.get("_rain_cam")
    cam_jump = not bool(fx.get("world_coords")) or bool(fx.get("screen_coords"))
    if isinstance(last, (list, tuple)) and len(last) >= 4:
        lx, ly, lw, lh = float(last[0]), float(last[1]), float(last[2]), float(last[3])
        if abs(float(cam_x) - lx) > lw * 0.35 or abs(float(cam_y) - ly) > lh * 0.35:
            cam_jump = True
    salt = int((float(cam_x) + float(cam_y)) * 0.17) & 0xFFFF
    for i, d in enumerate(drops):
        if cam_jump or ("x" not in d) or ("y" not in d):
            wx, wy = _screen_fx_rain_stratified_xy(
                i, n, band_left, band_top, band_w, band_h, salt=salt
            )
            d["x"], d["y"] = wx, wy
        if "land_y" not in d:
            _screen_fx_rain_assign_land_y(d, i, band_top, band_h, salt=salt)
    fx["world_coords"] = True
    fx.pop("screen_coords", None)
    fx["_rain_cam"] = (float(cam_x), float(cam_y), float(view_w), float(view_h))
    return ground_y


def _screen_fx_rain_respawn_drop(i, d, cam_x, cam_y, view_w, view_h, vx, vy):
    """화면 밖으로 나간 드롭을 월드 유입 경계(위·바람 불어오는 옆)에서 재생성."""
    band_left, band_top, band_w, band_h, _ground = _screen_fx_rain_viewport_band(
        cam_x, cam_y, view_w, view_h
    )
    band_right = band_left + band_w
    avx = abs(float(vx))
    avy = abs(float(vy)) or 1.0
    top_flux = avy * band_w        # 위 경계 유입량 (가로 전체)
    side_flux = avx * band_h       # 옆 경계 유입량 (세로 전체)
    total = top_flux + side_flux or 1.0
    rc = int(d.get("rc", 0)) + 1
    d["rc"] = rc
    a, b = _screen_fx_rain_jitter(int(i) + rc * 7919, rc * 40503 + int(i) * 97)
    if side_flux <= 1e-6 or a * total <= top_flux:
        # 위 경계에서 유입 — x 는 가로 전체 균일, y 는 화면 위(약간 바깥)
        d["x"] = band_left + b * band_w
        d["y"] = band_top - 2.0
    else:
        # 바람 불어오는 옆 경계에서 유입 — y 는 세로 전체 균일
        d["x"] = (band_left - 2.0) if float(vx) >= 0.0 else (band_right + 2.0)
        d["y"] = band_top + b * band_h
    # 탑다운: 다음 착지 지점(화면 어디든)도 새로 뽑는다.
    _screen_fx_rain_assign_land_y(d, int(i) + rc * 131, band_top, band_h, salt=rc * 733)


def build_screen_rain_from_step(step: dict) -> dict:
    """SCREEN_FX kind=rain → screen_fx_rain dict (drops 초기화)."""
    try:
        w = int(CONFIG.get("WIDTH", 640) or 640)
        h = int(CONFIG.get("HEIGHT", 480) or 480)
    except Exception:
        w, h = 640, 480
    try:
        density = float(step.get("density", CONFIG.get("SCREEN_FX_RAIN_DEFAULT_DENSITY", 0.35) or 0.35))
    except (TypeError, ValueError):
        density = float(CONFIG.get("SCREEN_FX_RAIN_DEFAULT_DENSITY", 0.35) or 0.35)
    density = max(0.0, min(1.0, density))
    try:
        speed = float(step.get("speed", CONFIG.get("SCREEN_FX_RAIN_DEFAULT_SPEED", 280) or 280))
    except (TypeError, ValueError):
        speed = float(CONFIG.get("SCREEN_FX_RAIN_DEFAULT_SPEED", 280) or 280)
    speed = max(20.0, min(900.0, speed))
    angle_deg = _screen_fx_rain_parse_angle(step)
    try:
        drop_len = int(float(step.get("drop_len", CONFIG.get("SCREEN_FX_RAIN_DEFAULT_DROP_LEN", 7) or 7)))
    except (TypeError, ValueError):
        drop_len = int(CONFIG.get("SCREEN_FX_RAIN_DEFAULT_DROP_LEN", 7) or 7)
    drop_len = max(2, min(24, drop_len))
    try:
        alpha = int(float(step.get("alpha", step.get("rain_alpha", CONFIG.get("SCREEN_FX_RAIN_DEFAULT_ALPHA", 170)) or 170)))
    except (TypeError, ValueError):
        alpha = int(CONFIG.get("SCREEN_FX_RAIN_DEFAULT_ALPHA", 170) or 170)
    alpha = max(0, min(255, alpha))
    count = _screen_fx_rain_drop_count(density, float(w), float(h))
    vx, vy, angle_deg = _screen_fx_rain_velocity(speed, angle_deg)
    drops = [{"len": drop_len + (i % 3) - 1} for i in range(count)]
    return {
        "enabled": True,
        "drops": drops,
        "splashes": [],
        "density": density,
        "drop_len": drop_len,
        "angle": angle_deg,
        "vx": vx,
        "vy": vy,
        "alpha": alpha,
        "color": _entity_fx_parse_rgb(step, (180, 200, 255)),
        "width": w,
        "height": h,
    }


def screen_fx_flash_alpha(fx) -> int:
    """screen_flash 상태 → 0~255 오버레이 알파."""
    if not isinstance(fx, dict) or not fx.get("enabled"):
        return 0
    return int(round(max(0.0, min(1.0, entity_fx_strength(fx))) * 255.0))


def screen_fx_shake_offset(fx):
    """screen_shake 상태 → (dx, dy) 픽셀 오프셋."""
    if not isinstance(fx, dict) or not fx.get("enabled"):
        return 0, 0
    try:
        amp = float(fx.get("amp_px", fx.get("amp", 0.0)) or 0.0)
    except (TypeError, ValueError):
        amp = 0.0
    if amp <= 1e-6:
        return 0, 0
    try:
        freq = float(fx.get("freq_hz", fx.get("freq", 12.0)) or 12.0)
    except (TypeError, ValueError):
        freq = 12.0
    t = float(fx.get("phase_sec", 0.0) or 0.0)
    w = 2.0 * math.pi * max(0.5, freq)
    dx = math.sin(t * w) * amp
    dy = math.sin(t * w * 1.37 + 0.65) * amp * 0.55
    return int(round(dx)), int(round(dy))


def tick_screen_fx_flash(fx, dt_sec: float) -> None:
    tick_entity_fx_state(fx, dt_sec)


def tick_screen_fx_shake(fx, dt_sec: float) -> None:
    if not isinstance(fx, dict) or not fx.get("enabled"):
        return
    fx["phase_sec"] = float(fx.get("phase_sec", 0.0) or 0.0) + max(0.0, float(dt_sec))


def tick_screen_fx_rain(fx, dt_sec: float) -> None:
    if not isinstance(fx, dict) or not fx.get("enabled"):
        return
    vx = float(fx.get("vx", 0.0) or 0.0)
    vy = float(fx.get("vy", 280.0) or 280.0)
    dt = max(0.0, float(dt_sec))
    drops = fx.get("drops") or []
    for i, d in enumerate(drops):
        sp = float(d.get("sp", 1.0) or 1.0)  # 드롭별 속도 편차(깊이감·장막 방지)
        d["x"] = float(d.get("x", 0.0)) + vx * sp * dt
        d["y"] = float(d.get("y", 0.0)) + vy * sp * dt
    # splashes: draw 에서 생성, 여기서는 수명만 줄임
    spl = fx.get("splashes")
    if isinstance(spl, list) and spl:
        keep = []
        for s in spl:
            if not isinstance(s, dict):
                continue
            try:
                t = float(s.get("t", 0.0) or 0.0) - dt
            except Exception:
                t = -1.0
            if t > 0.0:
                s["t"] = t
                keep.append(s)
        fx["splashes"] = keep


def draw_screen_fx_rain(
    target_surf,
    overlay_surf,
    fx,
    *,
    cam_draw_x: float = 0.0,
    cam_draw_y: float = 0.0,
    zoom: float = 1.0,
) -> None:
    """비 FX — 월드 좌표, 카메라 스크롤·줌 추종. tilt/shear 미적용."""
    if target_surf is None or overlay_surf is None or not isinstance(fx, dict) or not fx.get("enabled"):
        return
    try:
        tw, th = target_surf.get_size()
    except Exception:
        return
    if overlay_surf.get_size() != (tw, th):
        return
    overlay_surf.fill((0, 0, 0, 0))
    try:
        alpha = int(fx.get("alpha", 170) or 170)
    except Exception:
        alpha = 170
    alpha = max(0, min(255, alpha))
    rgb = fx.get("color") or (180, 200, 255)
    try:
        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    except Exception:
        r, g, b = 180, 200, 255
    vx = float(fx.get("vx", 0.0) or 0.0)
    vy = float(fx.get("vy", 280.0) or 280.0)
    mag = math.hypot(vx, vy) or 1.0
    ux, uy = vx / mag, vy / mag
    try:
        z = max(1e-6, float(zoom))
    except Exception:
        z = 1.0
    view_w = float(tw) / z
    view_h = float(th) / z
    _ground_y = _screen_fx_rain_sync_viewport(fx, cam_draw_x, cam_draw_y, view_w, view_h)
    drops = fx.get("drops") or []
    if not drops:
        return

    # 탑다운: 각 드롭은 자기 land_y(화면 아무 곳)에 닿으면 스플래시 후 재유입.
    band_left, band_top, band_w, band_h, _bg = _screen_fx_rain_viewport_band(
        cam_draw_x, cam_draw_y, view_w, view_h
    )
    band_right = band_left + band_w
    out_m = 16.0
    try:
        splash_max = int(CONFIG.get("SCREEN_FX_RAIN_SPLASH_MAX", 120) or 120)
    except Exception:
        splash_max = 120
    splash_max = max(0, min(400, splash_max))
    try:
        splash_life = float(CONFIG.get("SCREEN_FX_RAIN_SPLASH_LIFE_SEC", 0.28) or 0.28)
    except Exception:
        splash_life = 0.28
    splash_life = max(0.05, min(2.0, splash_life))
    try:
        splash_r0 = float(CONFIG.get("SCREEN_FX_RAIN_SPLASH_R0", 1.0) or 1.0)
        splash_r_max = float(CONFIG.get("SCREEN_FX_RAIN_SPLASH_R_MAX", 5.0) or 5.0)
    except Exception:
        splash_r0, splash_r_max = 1.0, 5.0
    splash_enabled = bool(CONFIG.get("SCREEN_FX_RAIN_SPLASH_ENABLED", True))
    splashes = fx.get("splashes")
    if not isinstance(splashes, list):
        splashes = []
        fx["splashes"] = splashes
    for i, d in enumerate(drops):
        if not isinstance(d, dict):
            continue
        try:
            wy = float(d.get("y", 0.0))
            wx = float(d.get("x", 0.0))
            land_y = float(d.get("land_y", band_top + band_h))
        except (TypeError, ValueError):
            continue
        landed = wy >= land_y
        outside = (
            landed
            or wx < band_left - out_m
            or wx > band_right + out_m
            or wy < band_top - out_m
        )
        if outside:
            # 근경(lay=1)만 스플래시 — 원경까지 튀기면 과함/과부하.
            if (
                landed
                and splash_enabled
                and int(d.get("lay", 0)) == 1
                and len(splashes) < splash_max
            ):
                splashes.append(
                    {"x": wx, "y": land_y, "t": splash_life, "life": splash_life}
                )
            _screen_fx_rain_respawn_drop(i, d, cam_draw_x, cam_draw_y, view_w, view_h, vx, vy)

    scr_margin = 32.0
    for d in drops:
        try:
            wx = float(d.get("x", 0.0))
            wy = float(d.get("y", 0.0))
            ln = max(2, int(d.get("len", 6) or 6))
        except Exception:
            continue
        d_am = float(d.get("am", 1.0) or 1.0)
        d_w = max(1, int(d.get("w", 1) or 1))
        d_alpha = max(0, min(255, int(alpha * d_am)))
        d_line_c = (r, g, b, d_alpha)
        # 카메라·줌만 적용 — tilt/shear 없음
        sx0 = (wx - float(cam_draw_x)) * z
        sy0 = (wy - float(cam_draw_y)) * z
        sx1 = (wx - ux * (float(ln) / z) - float(cam_draw_x)) * z
        sy1 = (wy - uy * (float(ln) / z) - float(cam_draw_y)) * z
        if (
            sx0 < -scr_margin
            or sx0 > float(tw) + scr_margin
            or sy0 < -scr_margin
            or sy0 > float(th) + scr_margin
        ):
            continue
        pygame.draw.line(
            overlay_surf,
            d_line_c,
            (int(round(sx0)), int(round(sy0))),
            (int(round(sx1)), int(round(sy1))),
            d_w,
        )

    # 스플래시: 속 빈 하얀 테두리 원이 커지다 사라짐 (알파 페이드 없음).
    ring_col = (r, g, b, alpha)
    for s in fx.get("splashes") or []:
        if not isinstance(s, dict):
            continue
        try:
            wx = float(s.get("x", 0.0))
            wy = float(s.get("y", 0.0))
            t = float(s.get("t", 0.0) or 0.0)
            life = float(s.get("life", splash_life) or splash_life)
        except Exception:
            continue
        if t <= 0.0:
            continue
        prog = 1.0 - max(0.0, min(1.0, t / max(1e-3, life)))  # 0→1 로 커짐
        rr = splash_r0 + (splash_r_max - splash_r0) * prog
        rr_px = max(1, int(round(rr * z)))
        sx0 = (wx - float(cam_draw_x)) * z
        sy0 = (wy - float(cam_draw_y)) * z
        if (
            sx0 < -scr_margin
            or sx0 > float(tw) + scr_margin
            or sy0 < -scr_margin
            or sy0 > float(th) + scr_margin
        ):
            continue
        pygame.draw.circle(
            overlay_surf, ring_col, (int(round(sx0)), int(round(sy0))), rr_px, 1
        )
    target_surf.blit(overlay_surf, (0, 0))


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
    def __init__(
        self,
        name,
        x,
        y,
        sprite_tilt=None,
        height=None,
        ysort_mode=None,
        layer=None,
    ):
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
        self.entity_def_zoom = 1.0
        try:
            self.event_entity_zoom_speed = float(CONFIG.get("ENTITY_ZOOM_LERP", 0.12))
        except Exception:
            self.event_entity_zoom_speed = 0.12

        self.is_slot = (info.get("type") == "slot")
        self.blink_timer = 0 # 깜빡임용
        
        self.is_holdable = info.get("is_holdable", False)
        self.is_visible = True
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
        try:
            from char_behavior import apply_object_type_retarget

            apply_object_type_retarget(self, key)
        except Exception:
            pass
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

    def draw(self, screen, cam_x, cam_y, player=None, global_frame=0, zoom=1.0, y_transform=None, x_offset_fn=None, sprite_perspective_q=None, shear_lod=False, x_scale_fn=None, x_shift_fn=None, pivot_xy=None, cam_angle_rad=0.0, mode7_ctx=None, view_w=None):
        if self.is_held:
            return
        if not bool(getattr(self, "is_visible", True)):
            return

        try:
            ez = entity_combined_zoom_mul(self)
        except Exception:
            ez = 1.0
        eff_z = float(zoom) * ez
        h_world = float(getattr(self, "height", 0) or 0)
        if mode7_ctx:
            # Mode7: 카메라 앞이면 투영. 가시성은 스케일 확정 후 스프라이트 사각형으로 재판정.
            m7 = rotate3d_mode7_project(
                float(self.pos[0]),
                float(self.pos[1]),
                mode7_ctx,
                height_off=h_world,
                zoom=float(zoom),
            )
            if not m7 or not m7.get("valid", m7.get("visible")):
                return
            eff_z *= float(m7.get("scale", 1.0) or 1.0)
            dx_base, dy_base = float(m7["sx"]), float(m7["sy"])
        else:
            # --- [1. 기본 좌표 계산] — FieldItem·Effect(ANIM_ONCE) 공통 규칙 ---
            dx_base, dy_base = _field_world_to_screen_anchor(
                self.pos[0],
                self.pos[1],
                cam_x,
                cam_y,
                zoom,
                height=h_world,
                y_transform=y_transform,
                x_offset_fn=x_offset_fn,
                x_scale_fn=x_scale_fn,
                x_shift_fn=x_shift_fn,
                pivot_xy=pivot_xy,
                cam_angle_rad=float(cam_angle_rad),
                mode7_ctx=None,
                view_w=view_w,
                anchor="feet",
            )

        # --- [2. 이미지 준비 & 크기 파악] ---
        current_img = self.image
        if len(self.frames) > 1:
            idx = self._anim_frame_idx()
            if idx != self.frame_idx:
                self.frame_idx = idx
                self.image = self.frames[idx]
            current_img = self.image
        current_img = apply_entity_fx_to_image(current_img, getattr(self, "entity_fx", None))

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

        screen_w = CONFIG["WIDTH"]
        screen_h = CONFIG["HEIGHT"]

        # --- [3. 최적화 조건문 (이미지 크기 반영)] ---
        # Mode7: 발점이 아니라 스케일된 스프라이트 사각형이 뷰와 겹칠 때만 유지.
        if mode7_ctx:
            if not rotate3d_mode7_bounds_visible(
                dx_base, dy_base, img_w, img_h, mode7_ctx, anchor="feet"
            ):
                return
        else:
            # 슬롯처럼 이미지가 작아도 최소 50픽셀의 여유는 줍니다.
            # 가로 타일 스크롤: 발(앵커)만으로 컬링하면 넓은 레이어가 화면 밖으로 잘못 걸러질 수 있음
            if tile_hscroll:
                margin_w = max(50, img_w * 2 + 120)
            else:
                margin_w = max(50, img_w // 2 + 10)
            margin_h = max(50, img_h + 10)
            # 이미지 전체가 화면 밖으로 완전히 나갔을 때만 return 합니다.
            # dy_base는 발 밑 기준 → 상단은 img_h로 margin_h에 이미 반영.
            if dx_base < -margin_w or dx_base > screen_w + margin_w or \
               dy_base < -10 or dy_base > screen_h + margin_h:
                return 
        
        # --- [4. 나머지 로직 (슬롯, 스케일링, 투명도 등 동일)] ---
        if self.is_slot and not self.has_real_image:
            import math
            try:
                _now_b = int(pygame.time.get_ticks())
            except Exception:
                _now_b = 0
            _last_b = int(getattr(self, "_slot_blink_last_ms", _now_b) or _now_b)
            if _last_b <= 0:
                _last_b = _now_b
            _dt_b = max(0.0, (_now_b - _last_b) / 1000.0)
            self._slot_blink_last_ms = _now_b
            self.blink_timer += _dt_b * 3.0
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
                try:
                    cid = id(current_img)
                    cached_dim = getattr(self, "_hide_dim_surf", None)
                    cached_key = getattr(self, "_hide_dim_key", None)
                    if cached_dim is not None and cached_key == cid:
                        current_img = cached_dim
                    else:
                        ci = current_img.copy()
                        ci.set_alpha(150)
                        self._hide_dim_surf = ci
                        self._hide_dim_key = cid
                        current_img = ci
                except Exception:
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
        draw_object_text_label(screen, self, dx_base, dy_base, eff_z)

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
        x_scale_fn=None,
        x_shift_fn=None,
        pivot_xy=None,
        cam_angle_rad=0.0,
        mode7_ctx=None,
        view_w=None,
        **_unused,
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
        eff_z = float(zoom)
        h_world = float(getattr(self, "height", 0) or 0)
        if mode7_ctx:
            m7 = rotate3d_mode7_project(
                float(self.pos[0]),
                float(self.pos[1]),
                mode7_ctx,
                height_off=h_world if anc in ("feet", "foot", "ground", "bottom") else 0.0,
                zoom=float(zoom),
            )
            if not m7 or not m7.get("valid", m7.get("visible")):
                return
            eff_z *= float(m7.get("scale", 1.0) or 1.0)
            dx_base, dy_base = float(m7["sx"]), float(m7["sy"])
        else:
            dx_base, dy_base = _field_world_to_screen_anchor(
                self.pos[0],
                self.pos[1],
                cam_x,
                cam_y,
                zoom,
                height=h_world,
                y_transform=y_transform,
                x_offset_fn=x_offset_fn,
                x_scale_fn=x_scale_fn,
                x_shift_fn=x_shift_fn,
                pivot_xy=pivot_xy,
                cam_angle_rad=float(cam_angle_rad),
                mode7_ctx=None,
                view_w=view_w,
                anchor=anc,
            )
        prepared = _prepare_field_sprite_blit(
            img,
            dx_base,
            dy_base,
            eff_z=eff_z,
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
        # Mode7: 준비된 실제 blit 크기로 bounds-aware cull
        if mode7_ctx:
            anc_b = "center" if anc in ("center", "centre", "mid", "middle", "head") else "feet"
            # prepared 의 (fx,fy)는 topleft. 앵커 점으로 되돌리지 않고 사각형 교차로 판정.
            rw = float(render_img.get_width())
            rh = float(render_img.get_height())
            if anc_b == "center":
                ax = float(fx) + rw * 0.5
                ay = float(fy) + rh * 0.5
            else:
                ax = float(dx_base)
                ay = float(dy_base)
            if not rotate3d_mode7_bounds_visible(ax, ay, rw, rh, mode7_ctx, anchor=anc_b):
                return
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
            and self._cam_blend_start is not None
        ):
            elapsed = float(getattr(self, "_cam_blend_elapsed_sec", 0.0) or 0.0)
            u = min(1.0, elapsed / float(self._cam_blend_duration_sec))
            # 긴 패닝만 ease-in-out, 짧은 추적/복귀는 선형
            if float(self._cam_blend_duration_sec) >= 0.35:
                return u * u * (3.0 - 2.0 * u)
            return u
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
            self._cam_blend_elapsed_sec = 0.0
        else:
            self._cam_blend_t0_ms = None
            self._cam_blend_start = None
            self._cam_blend_elapsed_sec = 0.0

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
        dt_vis = max(0.0, float(dt_sec))
        if (
            self._cam_blend_duration_sec is not None
            and float(self._cam_blend_duration_sec) > 0.0
            and self._cam_blend_start is not None
        ):
            self._cam_blend_elapsed_sec = float(getattr(self, "_cam_blend_elapsed_sec", 0.0) or 0.0) + dt_vis
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
            if self._cam_smooth:
                ler_eff = visual_smooth_step(float(self._cam_lerp), dt_vis)
            else:
                ler_eff = 1.0
            self.pos[0] += (float(tx) - float(self.pos[0])) * ler_eff
            self.pos[1] += (float(ty) - float(self.pos[1])) * ler_eff

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
_UI_FONT_CACHE = {}  # (font_key, size, outlined) -> pygame.font.Font | OutlinedUIFont
_BASE_UI_FONT_CACHE = {}  # (font_key, size) -> pygame.font.Font (TTF 본체)
_UI_FONT_CACHE_MAX = 256
_UI_TITLE_FONT_KEYS = frozenset({"logo", "title"})


def _ui_font_outline_px() -> int:
    try:
        on = bool(CONFIG.get("UI_FONT_OUTLINE_ENABLED", CONFIG.get("SAY_FONT_OUTLINE_ENABLED", True)))
    except Exception:
        on = True
    if not on:
        return 0
    try:
        px320 = float(
            CONFIG.get("UI_FONT_OUTLINE_PX_320", CONFIG.get("SAY_FONT_OUTLINE_PX_320", 1)) or 1
        )
    except (TypeError, ValueError):
        px320 = 1.0
    try:
        return max(1, int(round(_scale_px_from_320(px320, screen_w=int(CONFIG.get("WIDTH", 320) or 320)))))
    except Exception:
        try:
            return max(1, int(round(float(px320))))
        except Exception:
            return 1


def _ui_font_outline_color():
    try:
        col = CONFIG.get("UI_FONT_OUTLINE_COLOR", CONFIG.get("SAY_FONT_OUTLINE_COLOR", (255, 255, 255)))
        if isinstance(col, (list, tuple)) and len(col) >= 3:
            return (int(col[0]), int(col[1]), int(col[2]))
    except Exception:
        pass
    return (255, 255, 255)


def _normalize_rgb_color(color):
    try:
        if isinstance(color, (list, tuple)) and len(color) >= 3:
            return (int(color[0]), int(color[1]), int(color[2]))
    except Exception:
        pass
    return (255, 255, 255)


def _is_light_outline_color(color) -> bool:
    r, g, b = _normalize_rgb_color(color)
    return min(r, g, b) >= 200


def _is_white_fill_color(color) -> bool:
    r, g, b = _normalize_rgb_color(color)
    return min(r, g, b) >= 230


def _ui_font_fill_color_default():
    """게임 통일 채움색(검정). CONFIG UI_FONT_FILL_COLOR."""
    try:
        col = CONFIG.get("UI_FONT_FILL_COLOR", (0, 0, 0))
        if isinstance(col, (list, tuple)) and len(col) >= 3:
            return (int(col[0]), int(col[1]), int(col[2]))
    except Exception:
        pass
    return (0, 0, 0)


def _ui_font_force_fill_enabled() -> bool:
    try:
        return bool(CONFIG.get("UI_FONT_FORCE_FILL_COLOR", True))
    except Exception:
        return True


def _ui_font_resolve_fill_color(color, outline_color):
    """
    채움색 결정.
    - UI_FONT_FORCE_FILL_COLOR: 항상 UI_FONT_FILL_COLOR (검정+흰테두리 통일)
    - 아니면 밝은 테두리+흰 채움일 때만 UI_FONT_LIGHT_FILL_COLOR 로 대체
    """
    if _ui_font_force_fill_enabled():
        return _ui_font_fill_color_default()
    if not _is_light_outline_color(outline_color):
        return color
    if not _is_white_fill_color(color):
        return color
    try:
        rep = CONFIG.get("UI_FONT_LIGHT_FILL_COLOR", CONFIG.get("UI_FONT_FILL_COLOR", (0, 0, 0)))
        if isinstance(rep, (list, tuple)) and len(rep) >= 3:
            return (int(rep[0]), int(rep[1]), int(rep[2]))
    except Exception:
        pass
    return _ui_font_fill_color_default()


def _ui_font_fill_on_light_outline(color, outline_color):
    """호환용 별칭 — _ui_font_resolve_fill_color."""
    return _ui_font_resolve_fill_color(color, outline_color)


def clear_ui_font_cache() -> None:
    """CONFIG 폰트 설정 변경 후 캐시 무효화 (에디터 FONT 저장·미니게임 종료 시)."""
    try:
        _UI_FONT_CACHE.clear()
    except Exception:
        pass
    try:
        _BASE_UI_FONT_CACHE.clear()
    except Exception:
        pass


def _trim_ui_font_cache() -> None:
    """캐시 상한 초과 시 전체 삭제 대신 오래된 항목만 제거."""
    try:
        n = len(_UI_FONT_CACHE)
    except Exception:
        return
    if n <= _UI_FONT_CACHE_MAX:
        return
    try:
        drop = max(1, n - _UI_FONT_CACHE_MAX // 2)
        for k in list(_UI_FONT_CACHE.keys())[:drop]:
            _UI_FONT_CACHE.pop(k, None)
    except Exception:
        try:
            _UI_FONT_CACHE.clear()
        except Exception:
            pass


def _effective_outline_px(font: pygame.font.Font, outline_px: int) -> int:
    try:
        px = int(outline_px)
    except Exception:
        px = 0
    px = max(0, min(6, px))
    if px <= 0:
        return 0
    try:
        h = int(font.get_height())
    except Exception:
        return px
    if h <= 12:
        return 0
    if h <= 18:
        return min(px, 1)
    if h <= 26:
        return min(px, 1)
    return px


def _outline_ring_offsets(radius: int):
    """반지름 r 인근 8방향(+축) 오프셋."""
    r = max(1, int(radius))
    return (
        (-r, 0),
        (r, 0),
        (0, -r),
        (0, r),
        (-r, -r),
        (-r, r),
        (r, -r),
        (r, r),
    )


def _render_surface_with_outline(
    font: pygame.font.Font,
    text,
    antialias,
    color,
    *,
    outline_px: int,
    outline_color,
    resolve_fill: bool = True,
    soft_px: int = 0,
) -> pygame.Surface:
    """font.render + 테두리(+옵션 soft 글로우)를 합친 Surface 반환."""
    outline_px = _effective_outline_px(font, outline_px)
    try:
        soft_i = max(0, min(8, int(soft_px)))
    except Exception:
        soft_i = 0
    if resolve_fill:
        color = _ui_font_resolve_fill_color(color, outline_color)
    try:
        s_main = font.render(str(text or ""), bool(antialias), color)
    except Exception:
        s_main = None
    if s_main is None:
        return pygame.Surface((1, 1), pygame.SRCALPHA)
    if outline_px <= 0 and soft_i <= 0:
        return s_main
    try:
        s_ol = font.render(str(text or ""), bool(antialias), outline_color)
    except Exception:
        return s_main
    pad = int(outline_px) + int(soft_i) + 3
    sw = int(s_main.get_width()) + 2 * pad
    sh = int(s_main.get_height()) + 2 * pad
    tmp = pygame.Surface((max(1, sw), max(1, sh)), pygame.SRCALPHA)
    cx, cy = int(pad), int(pad)

    # soft 글로우: 하드 테두리 바깥에 알파가 줄어드는 링
    if soft_i > 0:
        hard = max(1, int(outline_px)) if outline_px > 0 else 0
        for r in range(hard + soft_i, hard, -1):
            # 바깥일수록 옅게
            dist = r - hard
            frac = 1.0 - (float(dist) / float(soft_i + 1))
            a = max(16, min(160, int(150.0 * frac)))
            try:
                layer = s_ol.copy()
                layer.set_alpha(a)
            except Exception:
                layer = s_ol
            for dx, dy in _outline_ring_offsets(r):
                tmp.blit(layer, (cx + dx, cy + dy))

    if outline_px > 0:
        offs = list(_outline_ring_offsets(outline_px))
        for dx, dy in offs:
            tmp.blit(s_ol, (cx + dx, cy + dy))
        if outline_px >= 2:
            d2 = int(outline_px)
            for dx, dy in ((-d2, 0), (d2, 0), (0, -d2), (0, d2)):
                tmp.blit(s_ol, (cx + dx, cy + dy))
    tmp.blit(s_main, (cx, cy))
    return tmp


class OutlinedUIFont:
    """UI 폰트 — render() 시 테두리 포함 Surface.
    style(dict)이 있으면 용도별 프로필 색·두께·AA·soft 를 쓰고, 없으면 CONFIG UI_FONT_* 전역값.
    """

    def __init__(self, base_font: pygame.font.Font, *, font_key: str = "default", style=None):
        self._base = base_font
        self._font_key = str(font_key or "default").strip().lower()
        self._style = dict(style) if isinstance(style, dict) else None

    def render(self, text, antialias, color):
        st = self._style
        if st is not None:
            try:
                ol_on = bool(st.get("outline_enabled", True))
            except Exception:
                ol_on = True
            try:
                ol_px0 = float(st.get("outline_px_320", 1) or 1)
            except (TypeError, ValueError):
                ol_px0 = 1.0
            if ol_on:
                try:
                    ol_px = max(
                        0,
                        int(
                            round(
                                _scale_px_from_320(
                                    ol_px0, screen_w=int(CONFIG.get("WIDTH", 320) or 320)
                                )
                            )
                        ),
                    )
                except Exception:
                    ol_px = max(1, int(round(ol_px0)))
            else:
                ol_px = 0
            # soft_px_320 → 논리 px (테두리 외곽 번짐)
            try:
                soft0 = float(st.get("soft_px_320", 0) or 0)
            except (TypeError, ValueError):
                soft0 = 0.0
            soft0 = max(0.0, min(8.0, soft0))
            if soft0 > 0.0:
                try:
                    soft_px = max(
                        0,
                        int(
                            round(
                                _scale_px_from_320(
                                    soft0, screen_w=int(CONFIG.get("WIDTH", 320) or 320)
                                )
                            )
                        ),
                    )
                except Exception:
                    soft_px = max(0, int(round(soft0)))
            else:
                soft_px = 0
            # 프로필 antialias 가 있으면 호출부의 True/False 보다 우선
            if "antialias" in st:
                try:
                    aa = bool(st.get("antialias", True))
                except Exception:
                    aa = bool(antialias)
            else:
                aa = bool(antialias)
            ol_col = _normalize_rgb_color(st.get("outline_color", (255, 255, 255)))
            if bool(st.get("force_color", True)):
                fill = _normalize_rgb_color(st.get("color", (0, 0, 0)))
            else:
                fill = color
            return _render_surface_with_outline(
                self._base,
                text,
                aa,
                fill,
                outline_px=ol_px,
                outline_color=ol_col,
                resolve_fill=False,
                soft_px=soft_px,
            )
        return _render_surface_with_outline(
            self._base,
            text,
            antialias,
            color,
            outline_px=_ui_font_outline_px(),
            outline_color=_ui_font_outline_color(),
        )


    def size(self, text):
        return self._base.size(text)

    def get_height(self):
        return self._base.get_height()

    def get_linesize(self):
        return self._base.get_linesize()

    def metrics(self, *args, **kwargs):
        return self._base.metrics(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._base, name)


def get_font_profile(slot: str) -> dict:
    """용도 슬롯 프로필 (data.UI_FONT_PROFILES)."""
    try:
        from data import ensure_ui_font_profiles

        profiles = ensure_ui_font_profiles()
    except Exception:
        profiles = CONFIG.get("UI_FONT_PROFILES") or {}
    sid = str(slot or "ui").strip() or "ui"
    try:
        p = profiles.get(sid) or profiles.get("ui") or {}
        return dict(p) if isinstance(p, dict) else {}
    except Exception:
        return {}


def font_profile_size_px(slot: str, *, screen_w: int | None = None, size_320=None) -> int:
    """프로필 size_320 → 현재 논리 해상도 px."""
    p = get_font_profile(slot)
    try:
        s320 = float(size_320 if size_320 is not None else p.get("size_320", 14) or 14)
    except (TypeError, ValueError):
        s320 = 14.0
    try:
        sw = int(screen_w if screen_w is not None else CONFIG.get("WIDTH", 320) or 320)
    except Exception:
        sw = 320
    try:
        return max(6, int(round(_scale_px_from_320(s320, screen_w=sw))))
    except Exception:
        return max(6, int(round(s320)))


def _load_base_ui_font(font_key: str, size_px: int) -> pygame.font.Font:
    """TTF만 로드 (테두리 래퍼 없음). 동일 (font_key, size) 는 재사용."""
    try:
        sz = max(6, min(256, int(size_px)))
    except Exception:
        sz = 16
    fk = (font_key or "default") or "default"
    fk_l = str(fk).strip().lower()
    bk = (fk_l, sz)
    hit = _BASE_UI_FONT_CACHE.get(bk)
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
    _BASE_UI_FONT_CACHE[bk] = font
    return font


def _style_cache_key(style) -> tuple:
    if not isinstance(style, dict):
        return ("nostyle",)
    c = _normalize_rgb_color(style.get("color", (0, 0, 0)))
    oc = _normalize_rgb_color(style.get("outline_color", (255, 255, 255)))
    try:
        opx = round(float(style.get("outline_px_320", 1) or 1), 3)
    except (TypeError, ValueError):
        opx = 1.0
    try:
        soft = round(float(style.get("soft_px_320", 0) or 0), 3)
    except (TypeError, ValueError):
        soft = 0.0
    return (
        str(style.get("font_key") or ""),
        bool(style.get("outline_enabled", True)),
        opx,
        soft,
        bool(style.get("antialias", True)),
        c,
        oc,
        bool(style.get("force_color", True)),
    )


def resolve_font_profile(slot: str, size_px: int | None = None, *, screen_w: int | None = None):
    """용도 슬롯 프로필로 OutlinedUIFont(또는 동일 인터페이스) 반환."""
    style = get_font_profile(slot)
    fk = str(style.get("font_key") or "default").strip() or "default"
    if size_px is None:
        sz = font_profile_size_px(slot, screen_w=screen_w)
    else:
        try:
            sz = max(6, min(256, int(size_px)))
        except Exception:
            sz = 16
    return _resolve_ui_font(fk, sz, outlined=True, style=style)


def _resolve_ui_font(font_key, size_px: int, *, outlined: bool = True, style=None):
    try:
        sz = max(6, min(256, int(size_px)))
    except Exception:
        sz = 16
    fk = (font_key or "default") or "default"
    fk_l = str(fk).strip().lower()
    if isinstance(style, dict):
        use_outline = True  # OutlinedUIFont 가 style.outline_enabled 로 두께 0 가능
        k = ("styled", fk_l, sz, _style_cache_key(style))
    else:
        use_outline = bool(outlined) and fk_l not in _UI_TITLE_FONT_KEYS
        k = (fk_l, sz, use_outline)
    hit = _UI_FONT_CACHE.get(k)
    if hit is not None:
        return hit
    font = _load_base_ui_font(fk, sz)
    if use_outline:
        font = OutlinedUIFont(font, font_key=fk_l, style=style)
    _UI_FONT_CACHE[k] = font
    _trim_ui_font_cache()
    return font


def _normalize_object_text_label(spec):
    if not isinstance(spec, dict):
        return None
    text = str(spec.get("text") or "").strip()
    if not text:
        return None
    try:
        size = max(6, min(96, int(float(spec.get("size", 16) or 16))))
    except Exception:
        size = 16
    try:
        ox = float(spec.get("offset_x", 0) or 0)
    except Exception:
        ox = 0.0
    try:
        oy = float(spec.get("offset_y", -24) or -24)
    except Exception:
        oy = -24.0
    font_key = str(spec.get("font") or "default").strip() or "default"
    return {"text": text, "font": font_key, "size": size, "offset_x": ox, "offset_y": oy}


def _get_object_text_label(item):
    base = dict((OBJ_ASSETS.get(str(getattr(item, "name", "") or ""), {}) or {}).get("text_label") or {})
    we = getattr(item, "_world_entry", None) or {}
    inst = we.get("text_label") if isinstance(we, dict) else None
    if isinstance(inst, dict) and inst:
        base.update(inst)
    return _normalize_object_text_label(base)


def draw_object_text_label(surface, item, anchor_x, anchor_y, zoom=1.0):
    spec = _get_object_text_label(item)
    if not spec:
        return
    try:
        scale = max(0.25, float(zoom))
    except Exception:
        scale = 1.0
    # 오브젝트 size 가 있으면 사용, 없으면 프로필 size_320
    try:
        base_sz = float(spec["size"])
    except Exception:
        base_sz = float(get_font_profile("object_label").get("size_320", 16) or 16)
    size_px = max(6, int(round(base_sz * scale)))
    style = get_font_profile("object_label")
    fk = str(spec.get("font") or style.get("font_key") or "default").strip() or "default"
    style = dict(style)
    style["font_key"] = fk
    font = _resolve_ui_font(fk, size_px, outlined=True, style=style)
    fg = font.render(spec["text"], True, style.get("color", (0, 0, 0)))
    px = float(anchor_x) + float(spec["offset_x"]) * scale
    py = float(anchor_y) + float(spec["offset_y"]) * scale
    sx = int(round(px - fg.get_width() * 0.5))
    sy = int(round(py - fg.get_height()))
    surface.blit(fg, (sx, sy))


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
    # 기본 오버레이 글자색 — 검정(흰 테두리는 OutlinedUIFont)
    return (0, 0, 0)


def _overlay_anchor_xy(anchor: str, w: int, h: int, mx: int, my: int, sw: int, sh: int):
    a = (anchor or "center").strip().lower()
    if a in ("tl", "top_left", "left_top"):
        return (mx, my)
    if a in ("tr", "top_right", "right_top", "right"):
        return (sw - w - mx, my)
    if a in ("bl", "bottom_left", "left_bottom"):
        return (mx, sh - h - my)
    if a in ("br", "bottom_right", "right_bottom"):
        return (sw - w - mx, sh - h - my)
    if a in ("left", "l", "west"):
        return (mx, (sh - h) // 2 + my)
    if a in ("top", "upper", "north"):
        return ((sw - w) // 2 + mx, my)
    if a in ("bottom", "lower", "south"):
        return ((sw - w) // 2 + mx, sh - h - my)
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


def _overlay_ui_should_scale(step: dict | None) -> bool:
    if step and step.get("ui_scale") is False:
        return False
    return True


def _overlay_ui_px(px_320: float, *, screen_w: int, step: dict | None = None) -> int:
    """OVERLAY_UI 스텝 수치는 320 설계 기준 — 논리 해상도에 맞게 스케일."""
    if not _overlay_ui_should_scale(step):
        try:
            return int(round(float(px_320)))
        except Exception:
            return 0
    try:
        from field_runtime import scale_ui_text_px

        return int(round(scale_ui_text_px(px_320, screen_w=screen_w)))
    except Exception:
        try:
            return int(round(float(px_320) * float(screen_w) / 320.0))
        except Exception:
            return int(round(float(px_320)))


def _overlay_styled_font(step: dict, *, screen_w: int, default_size_320=14):
    """OVERLAY_UI: logo 키면 logo 프로필, 아니면 ui 프로필 + 스텝 font/size."""
    font_key = str(step.get("font") or "").strip() or None
    slot = "logo" if (font_key or "").lower() in ("logo", "title") else "ui"
    style = dict(get_font_profile(slot))
    if font_key:
        style["font_key"] = font_key
    else:
        font_key = str(style.get("font_key") or "default")
    size_src = step.get("size")
    if size_src is None:
        size_src = step.get("font_size")
    if size_src is None:
        size_src = style.get("size_320", default_size_320)
    fs = max(1, _overlay_ui_px(size_src, screen_w=screen_w, step=step))
    font = _resolve_ui_font(font_key, fs, outlined=True, style=style)
    col = _parse_overlay_rgb(step)
    if bool(style.get("force_color", True)):
        col = _normalize_rgb_color(style.get("color", col))
    return font, col


def _build_overlay_surface_from_step(step: dict):
    try:
        screen_w = int(CONFIG.get("WIDTH", 320) or 320)
    except Exception:
        screen_w = 320
    ct = (step.get("content") or step.get("content_type") or "text").strip().lower()
    if ct == "button":
        font, col = _overlay_styled_font(step, screen_w=screen_w, default_size_320=14)
        label = str(step.get("text") or step.get("label") or "OK")
        try:
            ts = font.render(label, True, col)
        except Exception:
            ts = font.render("OK", True, col)
        pad_x = _overlay_ui_px(step.get("pad_x") if step.get("pad_x") is not None else 10, screen_w=screen_w, step=step)
        pad_y = _overlay_ui_px(step.get("pad_y") if step.get("pad_y") is not None else 6, screen_w=screen_w, step=step)
        w = ts.get_width() + pad_x * 2
        h = ts.get_height() + pad_y * 2
        out = pygame.Surface((max(4, w), max(4, h)), pygame.SRCALPHA)
        try:
            bg = step.get("bg_color") or step.get("button_bg") or "40,60,80"
            if isinstance(bg, str):
                parts = [int(x.strip()) for x in bg.split(",") if x.strip() != ""]
                if len(parts) >= 3:
                    bgc = tuple(parts[:3])
                else:
                    bgc = (40, 60, 80)
            else:
                bgc = (40, 60, 80)
        except Exception:
            bgc = (40, 60, 80)
        br = max(1, _overlay_ui_px(step.get("border_radius") if step.get("border_radius") is not None else 4, screen_w=screen_w, step=step))
        bw = max(1, _overlay_ui_px(1, screen_w=screen_w, step=step))
        pygame.draw.rect(out, bgc, (0, 0, out.get_width(), out.get_height()), border_radius=br)
        pygame.draw.rect(out, (180, 200, 220), (0, 0, out.get_width(), out.get_height()), bw, border_radius=br)
        out.blit(ts, (pad_x, pad_y))
        return out
    if ct == "image":
        name = (step.get("object") or step.get("obj") or "").strip()
        if not name:
            return None
        return _load_obj_surface_ui(name)
    font, col = _overlay_styled_font(step, screen_w=screen_w, default_size_320=16)
    raw = step.get("text") or ""
    lines = str(raw).replace("\r\n", "\n").split("\n") if raw else [""]
    surfaces = []
    max_w = 4
    total_h = 0
    line_gap = _overlay_ui_px(step.get("line_gap") if step.get("line_gap") is not None else 2, screen_w=screen_w, step=step)
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
    resolve_fill: bool = True,
):
    """텍스트 테두리(스트로크) 렌더: outline_color로 주변을 찍고 color를 마지막에 찍는다."""
    outline_px = _effective_outline_px(font, outline_px)
    if resolve_fill:
        if _ui_font_force_fill_enabled():
            color = _ui_font_fill_color_default()
        else:
            color = _ui_font_resolve_fill_color(color, outline_color)
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


def load_interact_prompt_frames(entity_key: str, prompt_set: str = None, *, max_frames: int = None):
    """
    상호작용 안내 아이콘 프레임 로드.
    1) assets/images/ui/{entity_key}/{set}0.png …
    2) assets/images/ui/pushbutton/{set}0.png …
    3) 구형 존 프롬프트: assets/images/ui/pushbutton0.png …
    각 경로에서 {set}{i}.png 와 {set}_{i}.png 를 순서대로 시도.
    """
    try:
        ps = str(
            prompt_set or CONFIG.get("INTERACT_PROMPT_DEFAULT_SET", "pushbutton") or "pushbutton"
        ).strip()
    except Exception:
        ps = "pushbutton"
    if not ps:
        ps = "pushbutton"
    try:
        nfr = int(
            max_frames
            if max_frames is not None
            else CONFIG.get("INTERACT_PROMPT_FRAMES", CONFIG.get("ZONE_CONFIRM_PROMPT_FRAMES", 4))
            or 4
        )
    except Exception:
        nfr = 4
    nfr = max(1, min(32, nfr))
    ek = str(entity_key or "").strip().replace("\\", "/").strip("/")
    prefixes = []
    if ek:
        prefixes.append(os.path.join("assets", "images", "ui", ek.replace("/", os.sep), ps))
    prefixes.append(os.path.join("assets", "images", "ui", "pushbutton", ps))
    if ps == "pushbutton":
        prefixes.append(os.path.join("assets", "images", "ui", "pushbutton"))
    seen = set()
    for pre in prefixes:
        pre_n = os.path.normpath(pre)
        if pre_n in seen:
            continue
        seen.add(pre_n)
        frames = []
        for i in range(nfr):
            found = None
            for suffix in (f"{i}.png", f"_{i}.png"):
                p = os.path.normpath(pre_n + suffix)
                surf = _load_image_cached(p)
                if surf is not None:
                    found = surf
                    break
            if found is None:
                break
            frames.append(found)
        if frames:
            return frames
    return []


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
        feet_x = float(feet_x) + float(shear_base_offset_px(feet_y_q, x_offset_fn))
    h_off = float(getattr(ent, "height", 0) or 0)
    if h_off > 0.0:
        feet_y = float(feet_y_q) - h_off * z
    else:
        feet_y = float(feet_y_q)
    fpx, fpy = int(round(float(feet_x))), int(round(float(feet_y)))
    try:
        ez = entity_combined_zoom_mul(ent)
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
        self._change_fade = None  # CHANGE fade — 디졸브 진행 상태 dict (완료 시 next_step)
        self._carry_wait_item = None  # CARRY wait — fly 중인 FieldItem (완료 시 next_step)
        self.active_event_result = None  # events.json의 result (종료 시 적용)
        self._progress_refresh_pending = False
        # SCREEN overlay (인트로/슬라이드 같은 화면 덮개)
        self.active_screen = None  # dict or None
        # SCREEN hi_res: main.py가 640x480 전환 전 출력 상태를 보관·복구
        self.screen_hi_res_snapshot = None
        # UI 오버레이 (로고/텍스트, 논리 해상도 좌표)
        self._ui_overlays = []  # list of dict, see _apply_overlay_ui_step
        self._ui_overlay_pending = []  # [{execute_at_ms, step}] — 트랙별 예약
        self._overlay_track_free_at = {}  # overlay_id → ms (해당 트랙 다음 스텝 가능 시각)
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
        self.rotate3d_control = None  # dict: target(strength 0~1), instant_once?, duration_sec?, t0_ms
        self.world_zoom_step_speed = None  # 디버그 핫키 등 구형 zoom/sec
        self.world_zoom_timed = None  # 시계 기반 월드 줌 보간 {start,target,t0_ms,duration_sec}
        self.field_tilt_snapshot = None  # (tilt_bg_demo, tilt_target, tilt_current, shear_debug) 이벤트 시작 시점
        self.pending_field_tilt_restore = None  # end_event 후 main이 한 번 소비
        # FX: 구름 그림자 오버레이 (main.py에서 실제 렌더)
        self.cloud_shadow_control = None  # dict: enabled, dir, speed, freq
        # FX: 화면 전체 번쩍·흔들림 (main.py 렌더 말미)
        self.screen_fx_flash = None
        self.screen_fx_shake = None
        self.screen_fx_rain = None
        self.screen_fx_vignette = None
        self.screen_fx_tone = None
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
        # 외부 minigames/ 패키지 연동은 폐기. 훅은 하위 호환용 no-op 만 남긴다.
        self._active_minigame = None
        self._entity_visual_event_snaps = {}  # id(ent) -> 이벤트 시작 전(첫 변경 시) 스냅샷
        self._entity_visual_event_persist = set()  # id(ent) — 종료 후에도 유지

    def is_minigame_active(self) -> bool:
        """외부 minigames/ 비사용 — 항상 False."""
        return False

    def _clear_minigame(self):
        self._active_minigame = None

    def minigame_push_event(self, event) -> None:
        return

    def tick_minigame(self, dt_sec: float) -> None:
        return

    def draw_minigame(self, surf, font_fn) -> None:
        return

    def _finish_minigame(self, session, step) -> None:
        self._clear_minigame()

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
        self._clear_minigame()
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
        self.rotate3d_control = None
        self.world_zoom_step_speed = None
        self.world_zoom_timed = None
        # FX는 이벤트 밖에서도 유지될 수 있으니 기본은 유지. (OFF는 FX 스텝에서 명시)
        self.field_tilt_snapshot = None
        self.pending_field_tilt_restore = None
        self._camera_saved_slots = {}
        self._say_bubble = None
        self._emote_overlay = None
        self._ui_overlay_pending = []
        self._overlay_track_free_at = {}
        self._entity_visual_event_snaps = {}
        self._entity_visual_event_persist = set()

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

    @staticmethod
    def _parse_overlay_delay_sec(step) -> float:
        raw = step.get("delay")
        if raw is None:
            raw = step.get("delay_sec")
        if raw is None or raw == "":
            return 0.0
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return 0.0

    def _clear_overlay_pending(self, *, keep_persist_scheduled=False):
        if not keep_persist_scheduled:
            self._ui_overlay_pending = []
            self._overlay_track_free_at = {}
            return
        kept = []
        for item in list(self._ui_overlay_pending or []):
            st = item.get("step") if isinstance(item, dict) else None
            if not isinstance(st, dict):
                continue
            act = (st.get("action") or "show").strip().lower()
            if act != "remove" and bool(st.get("persist")):
                kept.append(item)
        self._ui_overlay_pending = kept
        if kept:
            free = {}
            now = pygame.time.get_ticks()
            for item in kept:
                st = item.get("step") or {}
                oid = self._overlay_step_track_id(st)
                if not oid:
                    continue
                try:
                    end = int(item.get("execute_at_ms") or now)
                except (TypeError, ValueError):
                    end = now
                end = self._overlay_step_track_end_ms(st, end)
                free[oid] = max(int(free.get(oid, 0)), int(end))
            self._overlay_track_free_at = free
        else:
            self._overlay_track_free_at = {}

    @staticmethod
    def _overlay_step_track_id(step) -> str:
        if not isinstance(step, dict):
            return ""
        return str(step.get("overlay_id") or step.get("id") or "").strip()

    def _overlay_step_timing_ms(self, step):
        """show/remove 스텝의 appear·hold·disappear 길이(ms). hold=표시 유지 시간."""
        act = (step.get("action") or "show").strip().lower()
        if act == "remove":
            try:
                diss_raw = step.get("disappear")
                if diss_raw is None:
                    diss_raw = step.get("disappear_sec")
                if diss_raw is None or diss_raw == "":
                    diss = 0.0
                else:
                    diss = float(diss_raw)
            except (TypeError, ValueError):
                diss = 0.0
            out_ms = max(0, int(diss * 1000))
            return 0, 0, out_ms

        try:
            appear = float(
                step.get("appear")
                if step.get("appear") is not None
                else step.get("appear_sec", 0.5)
            )
        except (TypeError, ValueError):
            appear = 0.5
        try:
            disappear = float(
                step.get("disappear")
                if step.get("disappear") is not None
                else step.get("disappear_sec", 0.5)
            )
        except (TypeError, ValueError):
            disappear = 0.5
        hold_forever = bool(step.get("hold_forever") or step.get("infinite_hold"))
        hold_ms = 0
        if not hold_forever:
            hold_raw = step.get("hold") if "hold" in step else step.get("hold_sec")
            try:
                hs = float(hold_raw if hold_raw is not None and hold_raw != "" else 2.0)
            except (TypeError, ValueError):
                hs = 2.0
            hold_ms = max(0, int(hs * 1000))
        in_ms = max(0, int(appear * 1000))
        out_ms = 0 if hold_forever else max(0, int(disappear * 1000))
        return in_ms, hold_ms, out_ms

    def _overlay_step_track_end_ms(self, step, execute_at_ms: int) -> int:
        """이 스텝이 끝난 뒤 같은 overlay_id 트랙이 비는 시각."""
        act = (step.get("action") or "show").strip().lower()
        in_ms, hold_ms, out_ms = self._overlay_step_timing_ms(step)
        if act == "remove":
            return int(execute_at_ms) + int(out_ms)
        hold_forever = bool(step.get("hold_forever") or step.get("infinite_hold"))
        if hold_forever:
            return int(execute_at_ms) + int(in_ms)
        return int(execute_at_ms) + int(in_ms) + int(hold_ms) + int(out_ms)

    def _dispatch_overlay_ui_step(self, step):
        """overlay_id 트랙: 이전 연출 종료 + delay 후 실행. 다른 id는 병렬."""
        if not isinstance(step, dict):
            return
        step = dict(step)
        act = (step.get("action") or "show").strip().lower()
        oid = self._overlay_step_track_id(step)
        if not oid:
            if act == "remove":
                self._apply_overlay_ui_step(step)
                return
            oid = "ov_" + uuid.uuid4().hex[:10]
            step["overlay_id"] = oid

        delay_sec = self._parse_overlay_delay_sec(step)
        now = pygame.time.get_ticks()
        if oid in self._overlay_track_free_at:
            base_ms = int(self._overlay_track_free_at[oid])
        else:
            base_ms = int(now)

        execute_at = int(base_ms + delay_sec * 1000.0)
        if execute_at < now:
            execute_at = int(now)

        end_at = self._overlay_step_track_end_ms(step, execute_at)
        self._overlay_track_free_at[oid] = int(end_at)

        if execute_at <= now:
            self._apply_overlay_ui_step(step)
        else:
            self._ui_overlay_pending.append(
                {
                    "execute_at_ms": int(execute_at),
                    "step": step,
                }
            )

    def _tick_pending_overlay_ui_steps(self):
        if not self._ui_overlay_pending:
            return
        now = pygame.time.get_ticks()
        ready = []
        remain = []
        for item in list(self._ui_overlay_pending):
            try:
                at = int(item.get("execute_at_ms") or 0)
            except (TypeError, ValueError):
                at = 0
            if now >= at:
                ready.append(item)
            else:
                remain.append(item)
        self._ui_overlay_pending = remain
        for item in ready:
            st = item.get("step")
            if isinstance(st, dict):
                self._apply_overlay_ui_step(st)

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
                ov["phase_elapsed_sec"] = 0.0
                ov["t_out_sec"] = max(0.0, float(diss))
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
        mx = _overlay_ui_px(float(step.get("margin_x") or 0), screen_w=sw, step=step)
        my = _overlay_ui_px(float(step.get("margin_y") or 0), screen_w=sw, step=step)
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
        t_in_sec = max(0.0, float(appear))
        t_out_sec = max(0.0, float(disappear))
        if hold_forever:
            t_hold_sec = None
        else:
            try:
                hs = float(hold_raw if hold_raw is not None and hold_raw != "" else 2.0)
            except Exception:
                hs = 2.0
            t_hold_sec = max(0.0, float(hs))

        oid = (step.get("overlay_id") or step.get("id") or "").strip()
        if not oid:
            oid = "ov_" + uuid.uuid4().hex[:10]
        persist = bool(step.get("persist", False))

        sx, sy = _scroll_enter_delta(scroll_enter, w, h, sw, sh)
        ex, ey = _scroll_exit_delta(scroll_enter, w, h, sw, sh)

        ct = (step.get("content") or step.get("content_type") or "text").strip().lower()
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
            "t_in_sec": t_in_sec,
            "t_hold_sec": t_hold_sec,
            "t_out_sec": t_out_sec,
            "phase_elapsed_sec": 0.0,
            "hold_forever": hold_forever,
            "persist": persist,
            "draw_alpha": 0,
            "draw_dx": 0.0,
            "draw_dy": 0.0,
            "clickable": bool(
                step.get("clickable") or step.get("button") or ct == "button"
            ),
            "click_action": (step.get("click_action") or step.get("on_click") or "").strip(),
        }
        if mode == "scroll":
            ov["draw_dx"] = float(sx)
            ov["draw_dy"] = float(sy)
            ov["draw_alpha"] = 255
        self._ui_overlays = [o for o in (self._ui_overlays or []) if o.get("id") != oid]
        self._ui_overlays.append(ov)

    def _tick_ui_overlays(self, dt_sec=1.0 / 60.0):
        """OVERLAY_UI 페이드/스크롤 — 실제 경과 초(dt_sec) 기준."""
        self._tick_pending_overlay_ui_steps()
        dt = max(0.0, float(dt_sec))
        alive = []
        for ov in list(self._ui_overlays or []):
            ph = ov.get("phase")
            if ph == "done":
                continue
            mode = (ov.get("mode") or "fade").strip().lower()

            if ph == "in":
                try:
                    dur_sec = float(ov.get("t_in_sec", 0) or 0)
                except Exception:
                    dur_sec = 0.0
                if dur_sec <= 0:
                    try:
                        dur_sec = max(0.0, float(int(ov.get("t_in_ms") or 0)) / 1000.0)
                    except Exception:
                        dur_sec = 0.0
                el = float(ov.get("phase_elapsed_sec", 0.0) or 0.0) + dt
                ov["phase_elapsed_sec"] = el
                if dur_sec <= 0:
                    p = 1.0
                else:
                    p = min(1.0, max(0.0, el / dur_sec))
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
                    ov["phase_elapsed_sec"] = 0.0
                alive.append(ov)
                continue

            if ph == "hold":
                ov["draw_dx"] = 0.0
                ov["draw_dy"] = 0.0
                ov["draw_alpha"] = 255
                if ov.get("hold_forever"):
                    alive.append(ov)
                    continue
                try:
                    hm_sec = float(ov.get("t_hold_sec", 0) or 0)
                except Exception:
                    hm_sec = 0.0
                if hm_sec <= 0:
                    try:
                        hm_sec = max(0.0, float(int(ov.get("t_hold_ms") or 0)) / 1000.0)
                    except Exception:
                        hm_sec = 0.0
                el = float(ov.get("phase_elapsed_sec", 0.0) or 0.0) + dt
                ov["phase_elapsed_sec"] = el
                if el >= hm_sec:
                    ov["phase"] = "out"
                    ov["phase_elapsed_sec"] = 0.0
                alive.append(ov)
                continue

            if ph == "out":
                try:
                    dur_sec = float(ov.get("t_out_sec", 0) or 0)
                except Exception:
                    dur_sec = 0.0
                if dur_sec <= 0:
                    try:
                        dur_sec = max(0.0, float(int(ov.get("t_out_ms") or 0)) / 1000.0)
                    except Exception:
                        dur_sec = 0.0
                if dur_sec <= 0:
                    continue
                el = float(ov.get("phase_elapsed_sec", 0.0) or 0.0) + dt
                ov["phase_elapsed_sec"] = el
                p = min(1.0, max(0.0, el / dur_sec))
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

    def _tick_say_bubble_frame(self, dt_sec=1.0 / 60.0):
        bb = getattr(self, "_say_bubble", None)
        if not bb or not bool(getattr(self, "is_talking", False)) or not bb.get("frames"):
            return
        dt_ms = int(max(0.0, float(dt_sec)) * 1000.0)
        if dt_ms <= 0:
            return
        bb["acc_ms"] = int(bb.get("acc_ms", 0) or 0) + dt_ms
        fm = max(16, int(bb.get("frame_ms", 140) or 140))
        n = len(bb["frames"])
        fi = int(bb.get("frame_idx", 0) or 0)
        while int(bb["acc_ms"]) >= fm and fi < n - 1:
            bb["acc_ms"] = int(bb["acc_ms"]) - fm
            fi += 1
        bb["frame_idx"] = max(0, min(n - 1, fi))

    def _tick_emote_overlay(self, dt_sec=1.0 / 60.0):
        em = getattr(self, "_emote_overlay", None)
        if not em or not em.get("frames") or em.get("_advanced_step"):
            return
        if (em.get("phase") or "play") == "static":
            return
        dt_ms = int(max(0.0, float(dt_sec)) * 1000.0)
        if dt_ms <= 0:
            return
        frames = em["frames"]
        n = len(frames)
        if n <= 0:
            return
        fm = max(16, int(em.get("frame_ms", 120) or 120))
        phase = em.get("phase") or "play"
        if phase == "play":
            acc = int(em.get("acc_ms", 0) or 0) + dt_ms
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
            pa = int(em.get("post_acc", 0) or 0) + dt_ms
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

    def draw_ui_overlays(self, screen: pygame.Surface, head_ctx=None, *, layer="all"):
        """논리 해상도 서피스(CONFIG WIDTH×HEIGHT) 좌표로 블릿.

        layer:
          all — chrome + dialog (기본)
          chrome — OVERLAY_UI(exit 버튼 등), SCREEN 아래
          dialog — 말풍선·SAY 텍스트박스, SCREEN 위
        """
        draw_chrome = layer in ("all", "chrome")
        draw_dialog = layer in ("all", "dialog")

        if draw_dialog:
            try:
                self._draw_head_attached_ui(screen, head_ctx)
            except Exception:
                pass
        # SAY 텍스트박스 (events.json SAY)
        if draw_dialog and bool(getattr(self, "is_talking", False)) and bool(CONFIG.get("SAY_USE_TEXTBOX_UI", True)):
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

            # 대화/이름: UI_FONT_PROFILES dialog / dialog_name
            body_p = get_font_profile("dialog")
            name_p = get_font_profile("dialog_name")
            fkey = str(body_p.get("font_key") or CONFIG.get("SAY_FONT_KEY", "dialog") or "dialog").strip() or "dialog"
            nfkey = str(name_p.get("font_key") or fkey).strip() or fkey
            try:
                fs0 = float(body_p.get("size_320", CONFIG.get("SAY_FONT_SIZE_320", 12)) or 12)
            except Exception:
                fs0 = 12.0
            try:
                nfs0 = float(name_p.get("size_320", CONFIG.get("SAY_NAME_FONT_SIZE_320", fs0)) or fs0)
            except Exception:
                nfs0 = fs0
            fs = max(6, int(round(_scale_px_from_320(fs0, screen_w=w))))
            nfs = max(6, int(round(_scale_px_from_320(nfs0, screen_w=w))))
            font = _resolve_ui_font(fkey, fs, outlined=False)
            name_font = _resolve_ui_font(nfkey, nfs, outlined=False)

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

            name_col = _normalize_rgb_color(name_p.get("color", CONFIG.get("SAY_NAME_COLOR", (0, 0, 0))))
            text_col = _normalize_rgb_color(body_p.get("color", CONFIG.get("SAY_TEXT_COLOR", (0, 0, 0))))
            try:
                ol_on = bool(body_p.get("outline_enabled", CONFIG.get("SAY_FONT_OUTLINE_ENABLED", True)))
            except Exception:
                ol_on = True
            try:
                ol_px0 = float(body_p.get("outline_px_320", CONFIG.get("SAY_FONT_OUTLINE_PX_320", 1)) or 1)
            except Exception:
                ol_px0 = 1.0
            ol_px = int(round(_scale_px_from_320(ol_px0, screen_w=w))) if ol_on else 0
            ol_col = _normalize_rgb_color(
                body_p.get("outline_color", CONFIG.get("SAY_FONT_OUTLINE_COLOR", (255, 255, 255)))
            )
            # 이름 전용 테두리(프로필이 다르면 이름 쪽 우선)
            try:
                name_ol_on = bool(name_p.get("outline_enabled", ol_on))
            except Exception:
                name_ol_on = ol_on
            try:
                name_ol_px0 = float(name_p.get("outline_px_320", ol_px0) or ol_px0)
            except Exception:
                name_ol_px0 = ol_px0
            name_ol_px = int(round(_scale_px_from_320(name_ol_px0, screen_w=w))) if name_ol_on else 0
            name_ol_col = _normalize_rgb_color(name_p.get("outline_color", ol_col))

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
                    if name_ol_px > 0:
                        _tw, _th = _blit_text_with_outline(
                            screen,
                            name_font,
                            who,
                            x,
                            cur_y,
                            color=name_col,
                            outline_color=name_ol_col,
                            outline_px=name_ol_px,
                            alpha=say_alpha,
                            resolve_fill=False,
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
                            resolve_fill=False,
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

        if not draw_chrome:
            return
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

        if self.try_advance_screen():
            return

    def update(self, player, camera, objs, npcs, mask_img=None, dt_sec=1.0 / 60.0):
        if mask_img is not None:
            self._event_mask_img = mask_img
        # escape에서 속도 복구용 (가장 최근 프레임 엔티티 풀) — 리스트 재사용
        ents = getattr(self, "_active_entities", None)
        if ents is None:
            ents = []
            self._active_entities = ents
        ents.clear()
        ents.append(player)
        try:
            ents.extend(npcs)
        except Exception:
            pass
        try:
            ents.extend(objs)
        except Exception:
            pass
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

        self._tick_ui_overlays(dt_sec)
        try:
            self._tick_entity_fx_on_entities(player, npcs, objs, dt_sec)
        except Exception:
            pass
        # 이벤트 개체 줌 보간 — 이벤트 종료 후에도 진행 중인 배율 연출 유지
        try:
            self._tick_entity_event_zoom(player, npcs, objs, dt_sec)
        except Exception:
            pass
        try:
            self._tick_screen_fx(dt_sec)
        except Exception:
            pass
        try:
            self._tick_active_screen(dt_sec)
        except Exception:
            pass
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
            self._tick_say_bubble_frame(dt_sec)
        except Exception:
            pass
        try:
            self._tick_emote_overlay(dt_sec)
        except Exception:
            pass

        if not self.active_event:
            return

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

    def _track_event_entity_visual(self, ent, step) -> None:
        """이벤트 중 시각효과 변경 — persist 옵션·종료 시 복구용 스냅샷."""
        if ent is None:
            return
        from field_runtime import parse_step_persist

        eid = id(ent)
        if eid not in self._entity_visual_event_snaps:
            self._entity_visual_event_snaps[eid] = _entity_visual_snapshot(ent)
        if parse_step_persist(step):
            self._entity_visual_event_persist.add(eid)
        else:
            self._entity_visual_event_persist.discard(eid)

    def _commit_persisted_entity_event_zooms(self) -> None:
        """persist ZOOM — event_entity_zoom을 entity_def_zoom에 합쳐 이벤트 종료 후에도 유지."""
        persist = getattr(self, "_entity_visual_event_persist", None) or set()
        for ent in getattr(self, "_active_entities", []) or []:
            try:
                eid = id(ent)
            except Exception:
                continue
            if eid not in persist:
                continue
            try:
                ez = float(getattr(ent, "event_entity_zoom", 1.0) or 1.0)
            except Exception:
                ez = 1.0
            if abs(ez - 1.0) <= 1e-6:
                continue
            try:
                dz = float(getattr(ent, "entity_def_zoom", 1.0) or 1.0)
            except Exception:
                dz = 1.0
            try:
                ent.entity_def_zoom = clamp_entity_def_zoom(dz * ez)
                ent.event_entity_zoom = 1.0
                ent.event_entity_zoom_target = 1.0
                ent.event_entity_zoom_timed = None
            except Exception:
                pass

    def _restore_entity_event_visuals(self) -> None:
        """이벤트 종료 — persist 가 아닌 엔티티 시각효과를 이벤트 전 상태로 복구."""
        for ent in getattr(self, "_active_entities", []) or []:
            try:
                eid = id(ent)
            except Exception:
                continue
            if eid in self._entity_visual_event_persist:
                continue
            snap = self._entity_visual_event_snaps.get(eid)
            if snap is not None:
                _entity_visual_restore(ent, snap)
        self._entity_visual_event_snaps.clear()
        self._entity_visual_event_persist.clear()

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
            elif isinstance(ent, (FieldItem, BaseCharacter)):
                item = ent
            else:
                print(f"[CHANGE] '{tgt_raw}' 는 FieldItem/캐릭터 가 아님")
                self.next_step()
                return
        else:
            item = getattr(player, "held_item", None)
            if item is None:
                print("[CHANGE] target 비었고 손도 비어 있음")
                self.next_step()
                return

        # fade(초)가 주어지면 즉시 교체 대신 디졸브: 현재 외형이 사라진 뒤(alpha→0)
        # 새 외형으로 교체하고 다시 나타난다(alpha→255). 한 인스턴스라 위치/정렬은 유지됨.
        try:
            fade_sec = float(step.get("fade", step.get("fade_sec", 0)) or 0)
        except (TypeError, ValueError):
            fade_sec = 0.0

        if fade_sec > 0.0 and isinstance(item, (BaseCharacter, FieldItem)):
            self._change_fade = {
                "item": item,
                "new_name": new_name,
                "phase": "out",          # out(사라짐) -> in(나타남)
                "half_sec": max(0.05, fade_sec / 2.0),
                "start_alpha": int(getattr(item, "alpha", 255)),
                "applied": False,        # 교체 적용 여부
            }
            self.is_busy = True
            return

        self._apply_change_retarget(item, new_name)
        self.next_step()

    def _apply_change_retarget(self, item, new_name):
        """CHANGE 외형 교체 실제 적용 (즉시/디졸브 공통)."""
        old = getattr(item, "name", "?")
        if isinstance(item, BaseCharacter):
            if item.retarget_char_def(new_name):
                print(f"[CHANGE] {old} -> {new_name} (char)")
            else:
                print(f"[CHANGE] 실패: to='{new_name}' 없음(char_defs)")
        elif isinstance(item, FieldItem):
            if item.retarget_object_def(new_name):
                print(f"[CHANGE] {old} -> {new_name}")
            else:
                print(f"[CHANGE] 실패: to='{new_name}' 없음(object_defs)")
        else:
            print("[CHANGE] 대상이 FieldItem/캐릭터 가 아님")

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

        elif s_type == "MINIGAME_PLAY":
            # 외부 패키지 minigames/ 는 본체에 포함·import 하지 않는다.
            # 필드 미니게임은 activities/ 만 사용. 잔존 이벤트 스텝은 스킵.
            game_id = (step.get("game") or step.get("val") or step.get("name") or "").strip()
            print(f"[MINIGAME] skipped (external minigames disabled): {game_id!r}")
            self.next_step()

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
                from field_runtime import find_entity_by_name, parse_step_persist

                ent = (
                    player
                    if lt == "player"
                    else _event_resolve_entity(raw_tgt, player, npcs, objs)
                    or find_entity_by_name(raw_tgt, player, npcs=npcs, objs=objs)
                )
                if not ent:
                    print(f"[ZOOM] target not found: {raw_tgt!r}")
                    self.next_step()
                else:
                    persist_zoom = parse_step_persist(step)
                    self._track_event_entity_visual(ent, step)
                    ent.event_entity_zoom_target = val
                    ent.event_entity_zoom_duration_sec = dur
                    ent.event_entity_zoom_timed = None
                    if instant:
                        if persist_zoom:
                            try:
                                dz = float(getattr(ent, "entity_def_zoom", 1.0) or 1.0)
                            except Exception:
                                dz = 1.0
                            ent.entity_def_zoom = clamp_entity_def_zoom(dz * val)
                            ent.event_entity_zoom = 1.0
                            ent.event_entity_zoom_target = 1.0
                        else:
                            ent.event_entity_zoom = val
                        self.next_step()
                    else:
                        zc = float(getattr(ent, "event_entity_zoom", 1.0))
                        ent.event_entity_zoom_timed = {}
                        timed_effect_init(
                            ent.event_entity_zoom_timed, zc, val, dur, now_ms=t0
                        )
                        # duration_sec 동안 busy 유지 → _check_completion에서 완료 후 next_step

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

        elif s_type == "3D_ROTATE":
            pr = parse_rotate3d_step(step)
            rc = {
                "target": float(pr["target"]),
                "duration_sec": float(pr["duration_sec"]),
                "t0_ms": effect_now_ms(),
            }
            if pr["instant"]:
                rc["instant_once"] = True
            self.rotate3d_control = rc
            self.next_step()

        elif s_type == "ENTITY_FX":
            self._execute_entity_fx_step(step, player, npcs, objs)
            return

        elif s_type == "SCREEN_FX":
            self._execute_screen_fx_step(step)
            return

        elif s_type == "SCREEN_FLASH":
            self._execute_screen_fx_step({**step, "kind": "flash"})
            return

        elif s_type == "SCREEN_SHAKE":
            self._execute_screen_fx_step({**step, "kind": "shake"})
            return

        elif s_type == "FX":
            # FX: 구름 그림자(cloud_shadow). 구형 kind=entity_fx/screen_* 도 하위 호환.
            kind = (step.get("kind") or step.get("name") or "").strip().lower()
            if kind in (
                "entity_fx",
                "entity_glow",
                "entity_tint",
                "entity_pulse",
                "entity_shimmer",
                "entity",
            ):
                self._execute_entity_fx_step(step, player, npcs, objs)
                return
            if kind in ("screen_flash", "flash", "fullscreen_flash", "screen_glow"):
                self._execute_screen_fx_step({**step, "kind": "flash"})
                return
            if kind in ("screen_shake", "shake", "screen_quake", "quake"):
                self._execute_screen_fx_step({**step, "kind": "shake"})
                return
            if kind in ("rain", "screen_rain"):
                self._execute_screen_fx_step({**step, "kind": "rain"})
                return
            if kind in ("vignette", "screen_vignette"):
                self._execute_screen_fx_step({**step, "kind": "vignette"})
                return
            if kind in ("tone", "screen_tone", "white_balance", "whitebalance", "wb"):
                self._execute_screen_fx_step({**step, "kind": "tone"})
                return
            if kind in ("cloud", "cloudshadow", "cloud_shadow", "cloud-shadow", ""):
                self._execute_screen_fx_step({**step, "kind": "cloud"})
                return
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
                    step=step if isinstance(step, dict) else None,
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
                    self.active_screen["phase_elapsed_sec"] = 0.0
                    self.active_screen["skip_pending"] = False
                    self.active_screen["advance_done"] = True
                    try:
                        if step.get("val") is not None:
                            diss = float(step.get("val") or 0)
                        else:
                            diss = float(
                                self.active_screen.get(
                                    "transition_sec",
                                    self.active_screen.get("duration_sec", 0.4),
                                )
                                or 0.4
                            )
                    except Exception:
                        diss = 0.4
                    diss = max(0.12, float(diss)) * 2.0
                    self.active_screen["transition_sec"] = diss
                    self.active_screen["duration_sec"] = diss
                    self.active_screen["duration_ms"] = int(diss * 1000.0)
                    self.is_busy = True
                else:
                    self.next_step()
                return

            # show/update: 오버레이 생성/갱신
            pic = (step.get("picture") or "").strip()
            music = (step.get("music") or "").strip()

            # picture는 상대경로면 assets/images/screen 기준으로 보정
            if pic and not os.path.isabs(pic):
                # 이미 assets/... 로 시작하면 그대로, 아니면 screen 폴더로
                if not pic.replace("\\", "/").startswith("assets/"):
                    pic = os.path.join("assets", "images", "screen", pic)

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
                self.active_screen = self._screen_overlay_from_step(
                    step,
                    img=img,
                    pic=pic,
                    music=music,
                    transition=transition or "fade",
                    bg=bg,
                    mode="crossing",
                    now_t=now_t,
                    prev_img=prev_img,
                )
            else:
                # 처음 켜질 때는 검은 바탕 위로 페이드 인
                self.active_screen = self._screen_overlay_from_step(
                    step,
                    img=img,
                    pic=pic,
                    music=music,
                    transition=transition or "fade",
                    bg=bg,
                    mode="showing",
                    now_t=now_t,
                )

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

            # 유지 시간·클릭 대기 — 완료 시 _complete_screen_slide()가 next_step 1회
            self.is_busy = True

        elif s_type == "OVERLAY_UI":
            self._dispatch_overlay_ui_step(step)
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
                delta = fade_alpha_delta(255.0, appear_sec, dt_sec)
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

        if s_type == "CHANGE":
            cf = getattr(self, "_change_fade", None)
            if not cf:
                self.next_step()
                return
            item = cf["item"]
            delta = fade_alpha_delta(255.0, float(cf["half_sec"]), dt_sec)
            if cf["phase"] == "out":
                item.alpha = max(0, int(getattr(item, "alpha", 255)) - int(round(delta)))
                if item.alpha <= 0:
                    item.alpha = 0
                    if not cf["applied"]:
                        self._apply_change_retarget(item, cf["new_name"])
                        cf["applied"] = True
                    cf["phase"] = "in"
            else:  # in
                item.alpha = min(255, int(getattr(item, "alpha", 0)) + int(round(delta)))
                if item.alpha >= 255:
                    item.alpha = 255
                    self._change_fade = None
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

        elif s_type == "MINIGAME_PLAY":
            # 본체는 minigames/ 를 쓰지 않음. busy 잔존 시에도 즉시 통과.
            self._clear_minigame()
            self.is_busy = False
            self.next_step()

        elif s_type in ("ANIM", "ACTION_ANIM"):
            if self._anim_wait_end_ms and pygame.time.get_ticks() >= int(self._anim_wait_end_ms):
                self._anim_wait_end_ms = 0
                self.next_step()

        elif s_type == "ZOOM":
            pz = parse_zoom_step(step)
            if bool(pz.get("is_camera")):
                return
            if bool(pz.get("instant")):
                return
            raw_tgt = (pz.get("target") or "").strip()
            lt = raw_tgt.lower()
            ent = (
                player
                if lt == "player"
                else _event_resolve_entity(raw_tgt, player, npcs, objs)
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
            ztimed = getattr(ent, "event_entity_zoom_timed", None)
            if isinstance(ztimed, dict) and not timed_effect_finished(ztimed):
                return
            eps = max(0.008, abs(zt) * 0.02)
            if abs(zc - zt) <= eps:
                ent.event_entity_zoom = zt
                ent.event_entity_zoom_timed = None
                self.next_step()

        # SAY는 main.py에서 클릭 시 next_step()을 직접 호출해줌
        # FADEOUT/FADEIN은 논블로킹(즉시 next_step) — val은 초(duration), 보간은 update() 상단

        # SCREEN remove가 진행 중이면 여기서 완료 처리(오버레이 제거)
        if self.active_screen and self.active_screen.get("mode") == "removing":
            try:
                dur = float(self.active_screen.get("duration_sec", 0.4) or 0.4)
            except Exception:
                dur = 0.4
            dur = max(0.12, dur)
            el = float(self.active_screen.get("phase_elapsed_sec", 0.0) or 0.0)
            if el >= dur:
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
        self.rotate3d_control = None
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
        self._clear_minigame()
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

    def try_overlay_ui_click(self, mx: int, my: int):
        """OVERLAY_UI clickable 영역 클릭. click_action 문자열 또는 None."""
        try:
            ix, iy = int(mx), int(my)
        except Exception:
            return None
        for ov in reversed(list(self._ui_overlays or [])):
            if not ov.get("clickable"):
                continue
            if ov.get("phase") == "done":
                continue
            try:
                alpha = int(ov.get("draw_alpha", 255))
            except Exception:
                alpha = 255
            if alpha <= 0:
                continue
            x = int(float(ov.get("rest_x", 0)) + float(ov.get("draw_dx", 0)))
            y = int(float(ov.get("rest_y", 0)) + float(ov.get("draw_dy", 0)))
            w = int(ov.get("w", 0) or 0)
            h = int(ov.get("h", 0) or 0)
            if w <= 0 or h <= 0:
                continue
            if x <= ix < x + w and y <= iy < y + h:
                act = (ov.get("click_action") or "").strip()
                return act or "click"
        return None

    def remove_ui_overlay(self, overlay_id: str) -> None:
        rid = (overlay_id or "").strip()
        if not rid:
            return
        self._ui_overlays = [o for o in (self._ui_overlays or []) if o.get("id") != rid]

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
                self._progress_refresh_pending = True
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
        if ended_id:
            self._progress_refresh_pending = True

        self.last_ended_event_id = ended_id
        self._clear_minigame()
        try:
            self._ui_overlays = [o for o in (self._ui_overlays or []) if o.get("persist")]
        except Exception:
            self._ui_overlays = []
        self._clear_overlay_pending(keep_persist_scheduled=True)
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
        # CHANGE 디졸브가 끝나기 전에 이벤트가 종료되면 외형 교체를 마저 적용하고 alpha 복구
        cf_end = getattr(self, "_change_fade", None)
        if cf_end:
            try:
                if not cf_end.get("applied"):
                    self._apply_change_retarget(cf_end["item"], cf_end["new_name"])
                cf_end["item"].alpha = 255
            except Exception:
                pass
            self._change_fade = None
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
        self._commit_persisted_entity_event_zooms()
        self._restore_entity_event_visuals()

    def _tick_entity_fx_on_entities(self, player, npcs, objs, dt_sec):
        """entity_fx pulse phase 갱신 (필드·이벤트 공통)."""
        pools = []
        if player is not None:
            pools.append(player)
        pools.extend(list(npcs or []))
        pools.extend(list(objs or []))
        for ent in pools:
            fx = getattr(ent, "entity_fx", None)
            if fx:
                tick_entity_fx_state(fx, dt_sec)

    def _execute_entity_fx_step(self, step, player, npcs, objs):
        """ENTITY_FX — 대상 캐릭터/오브젝트 반짝임·틴트·zoom."""
        from field_runtime import find_entity_by_name

        action = (step.get("action") or step.get("cmd") or "start").strip().lower()
        if action in ("stop", "clear", "off", "remove", "end"):
            tgt_name = (step.get("target") or step.get("who") or "").strip()
            if tgt_name:
                ent = find_entity_by_name(tgt_name, player, npcs=npcs, objs=objs)
                if ent is not None:
                    clear_entity_visual(ent)
            else:
                for pool in (npcs or []), (objs or []):
                    for ent in pool:
                        clear_entity_visual(ent)
                if player is not None:
                    clear_entity_visual(player)
            self.next_step()
            return
        on_raw = step.get("on", True)
        if isinstance(on_raw, str) and on_raw.strip().lower() in ("0", "false", "f", "no", "n", "off"):
            self._execute_entity_fx_step({**step, "action": "stop"}, player, npcs, objs)
            return
        tgt = (step.get("target") or step.get("who") or "player").strip()
        ent = find_entity_by_name(tgt, player, npcs=npcs, objs=objs)
        if ent is None:
            print(f"[FX entity_fx] 대상 없음: {tgt}")
            self.next_step()
            return
        self._track_event_entity_visual(ent, step)
        apply_entity_visual_patch(ent, step)
        self.next_step()

    def _parse_step_bool(self, raw, *, default=False) -> bool:
        if raw is None:
            return bool(default)
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "t", "yes", "y", "on")
        return bool(raw)

    def _parse_fx_on_flag(self, step) -> bool:
        """SCREEN_FX 등 스텝 dict의 on 필드."""
        if not isinstance(step, dict):
            return self._parse_step_bool(step, default=True)
        return self._parse_step_bool(step.get("on", True), default=True)

    def _screen_timing_from_step(self, step) -> dict:
        """SCREEN show 스텝 → 전환·유지·텍스트 지연·입력 정책."""
        hold_sec = 3.0
        if step.get("val") is not None:
            try:
                hold_sec = max(0.0, float(step.get("val")))
            except (TypeError, ValueError):
                hold_sec = 3.0
        transition_sec = 0.5
        if step.get("transition_sec") is not None:
            try:
                transition_sec = max(0.12, float(step.get("transition_sec")))
            except (TypeError, ValueError):
                transition_sec = 0.5
        transition_sec = max(0.12, float(transition_sec)) * 2.0
        try:
            min_hold_sec = max(0.0, float(CONFIG.get("SCREEN_MIN_HOLD_SEC", 1.0) or 1.0))
        except (TypeError, ValueError, NameError):
            min_hold_sec = 1.0
        text_raw = step.get("text")
        text_str = "" if text_raw is None else str(text_raw)
        text_delay = 1.0
        if text_str.strip():
            if step.get("text_delay_sec") is not None:
                try:
                    text_delay = max(0.0, float(step.get("text_delay_sec")))
                except (TypeError, ValueError):
                    text_delay = 1.0
        force = self._parse_step_bool(
            step.get("force", step.get("locked", False)), default=False
        )
        auto = self._parse_step_bool(step.get("auto", True), default=True)
        return {
            "hold_sec": float(hold_sec),
            "transition_sec": float(transition_sec),
            "min_hold_sec": float(min_hold_sec),
            "text": text_str,
            "text_show_delay_sec": float(text_delay),
            "force": bool(force),
            "auto": bool(auto),
            "hi_res": self._parse_step_bool(step.get("hi_res", False), default=False),
        }

    def try_advance_screen(self) -> bool:
        """SCREEN holding 중 클릭 스킵(강제 모드·중복 클릭 무시)."""
        info = getattr(self, "active_screen", None)
        if not info:
            return False
        if info.get("advance_done") or info.get("skip_pending"):
            return False
        if bool(info.get("force")):
            return False
        if str(info.get("mode") or "").strip().lower() != "holding":
            return False
        info["skip_pending"] = True
        return True

    def _complete_screen_slide(self) -> None:
        """현재 SCREEN 슬라이드 종료 → 이벤트 다음 스텝 1회만."""
        info = getattr(self, "active_screen", None)
        if not info or info.get("advance_done"):
            return
        info["advance_done"] = True
        self.is_busy = False
        self.next_step()

    def _screen_overlay_from_step(
        self,
        step,
        *,
        img,
        pic: str,
        music: str,
        transition: str,
        bg: str,
        mode: str,
        now_t: int,
        prev_img=None,
    ) -> dict:
        timing = self._screen_timing_from_step(step)
        trans_sec = float(timing["transition_sec"])
        trans_ms = max(120, int(trans_sec * 1000.0))
        overlay = {
            "img": img,
            "picture": pic,
            "music": music,
            "transition": transition or "fade",
            "bg": bg,
            "hi_res": bool(timing["hi_res"]),
            "mode": mode,
            "t0": now_t,
            "transition_sec": trans_sec,
            "duration_ms": trans_ms,
            "duration_sec": trans_sec,
            "phase_elapsed_sec": 0.0,
            "hold_sec": float(timing["hold_sec"]),
            "hold_elapsed_sec": 0.0,
            "min_hold_sec": float(timing.get("min_hold_sec", 1.0) or 1.0),
            "text": timing["text"],
            "text_show_delay_sec": float(timing["text_show_delay_sec"]),
            "force": bool(timing["force"]),
            "auto": bool(timing["auto"]),
            "skip_pending": False,
            "advance_done": False,
        }
        if prev_img is not None:
            overlay["prev_img"] = prev_img
            overlay["next_img"] = img
        return overlay

    def _screen_holding_state_from(self, info: dict) -> dict:
        trans_sec = max(
            0.12,
            float(info.get("transition_sec", info.get("duration_sec", 0.5)) or 0.5),
        )
        return {
            "img": info.get("next_img") or info.get("img"),
            "picture": info.get("picture"),
            "music": info.get("music"),
            "transition": info.get("transition", "fade"),
            "bg": info.get("bg", "black"),
            "hi_res": bool(info.get("hi_res", False)),
            "mode": "holding",
            "transition_sec": trans_sec,
            "duration_sec": trans_sec,
            "duration_ms": int(trans_sec * 1000.0),
            "phase_elapsed_sec": 0.0,
            "hold_sec": float(info.get("hold_sec", 3.0) or 3.0),
            "hold_elapsed_sec": 0.0,
            "min_hold_sec": float(info.get("min_hold_sec", 1.0) or 1.0),
            "text": info.get("text") or "",
            "text_show_delay_sec": float(info.get("text_show_delay_sec", 1.0) or 1.0),
            "force": bool(info.get("force", False)),
            "auto": bool(info.get("auto", True)),
            "skip_pending": False,
            "advance_done": False,
        }

    def clear_all_screen_fx(self) -> None:
        """SCREEN_FX kind=all on:false — 구름·비·톤 등 화면 FX 전부 끔."""
        self.cloud_shadow_control = {"enabled": False}
        self.screen_fx_flash = {"enabled": False}
        self.screen_fx_shake = {"enabled": False}
        self.screen_fx_rain = {"enabled": False}
        self.screen_fx_vignette = {"enabled": False}
        self.screen_fx_tone = {"enabled": False}

    def _execute_screen_fx_step(self, step):
        """SCREEN_FX — kind 별 cloud / flash / shake / rain / vignette / tone / all (on:false 로 해당 효과만 끔)."""
        kind = resolve_screen_fx_kind(step)
        if kind == "all":
            if not self._parse_fx_on_flag(step):
                self.clear_all_screen_fx()
            self.next_step()
            return
        if not self._parse_fx_on_flag(step):
            if kind == "flash":
                self.screen_fx_flash = {"enabled": False}
            elif kind == "shake":
                self.screen_fx_shake = {"enabled": False}
            elif kind == "rain":
                self.screen_fx_rain = {"enabled": False}
            elif kind == "vignette":
                self.screen_fx_vignette = {"enabled": False}
            elif kind == "tone":
                self.screen_fx_tone = {"enabled": False}
            elif kind == "cloud":
                self.cloud_shadow_control = {"enabled": False}
            self.next_step()
            return
        if kind == "cloud":
            self.cloud_shadow_control = build_cloud_shadow_control_from_step(step)
        elif kind == "shake":
            self.screen_fx_shake = build_screen_shake_from_step(step)
        elif kind == "rain":
            self.screen_fx_rain = build_screen_rain_from_step(step)
        elif kind == "vignette":
            self.screen_fx_vignette = build_screen_vignette_from_step(step)
        elif kind == "tone":
            self.screen_fx_tone = build_screen_tone_from_step(step)
        else:
            self.screen_fx_flash = build_screen_flash_from_step(step)
        self.next_step()

    def _tick_screen_fx(self, dt_sec):
        flash = self.screen_fx_flash
        if isinstance(flash, dict) and flash.get("enabled"):
            tick_screen_fx_flash(flash, dt_sec)
        shake = self.screen_fx_shake
        if isinstance(shake, dict) and shake.get("enabled"):
            tick_screen_fx_shake(shake, dt_sec)
        rain = self.screen_fx_rain
        if isinstance(rain, dict) and rain.get("enabled"):
            tick_screen_fx_rain(rain, dt_sec)

    def _tick_active_screen(self, dt_sec=1.0 / 60.0):
        """SCREEN 오버레이 전환·유지·자동/클릭 넘김."""
        info = self.active_screen
        if not info:
            return
        mode = (info.get("mode") or "showing").strip().lower()
        dt = max(0.0, float(dt_sec))

        if mode == "holding":
            info["hold_elapsed_sec"] = float(info.get("hold_elapsed_sec", 0.0) or 0.0) + dt
            hold_el = float(info.get("hold_elapsed_sec", 0.0) or 0.0)
            try:
                min_hold = max(0.0, float(info.get("min_hold_sec", 1.0) or 1.0))
            except (TypeError, ValueError):
                min_hold = 1.0
            if hold_el < min_hold:
                return
            if info.get("skip_pending") and not bool(info.get("force")):
                self._complete_screen_slide()
                return
            hold_sec = float(info.get("hold_sec", 3.0) or 3.0)
            if bool(info.get("auto", True)) and hold_el >= hold_sec:
                self._complete_screen_slide()
            return

        if mode not in ("showing", "crossing", "removing"):
            return

        el = float(info.get("phase_elapsed_sec", 0.0) or 0.0) + dt
        info["phase_elapsed_sec"] = el
        try:
            dur = float(info.get("transition_sec", info.get("duration_sec", 0.4)) or 0.4)
        except Exception:
            dur = 0.4
        dur = max(0.12, dur)
        if el < dur:
            return
        if mode == "crossing":
            self.active_screen = self._screen_holding_state_from(info)
        elif mode == "showing":
            info["mode"] = "holding"
            info["phase_elapsed_sec"] = 0.0
            info["hold_elapsed_sec"] = 0.0
            info["skip_pending"] = False
            info["advance_done"] = False

    def draw_screen_overlay(self, screen: pygame.Surface):
        """SCREEN 스텝 오버레이를 게임 화면 위에 렌더링."""
        if not self.active_screen:
            return
        info = self.active_screen
        img = info.get("img")
        transition = (info.get("transition") or "fade").strip().lower()
        bg = (info.get("bg") or "black").strip().lower()
        mode = info.get("mode") or "showing"
        try:
            dur = float(info.get("transition_sec", info.get("duration_sec", 0.4)) or 0.4)
        except Exception:
            dur = 0.4
        if dur <= 0 and info.get("duration_ms"):
            try:
                dur = max(0.12, float(int(info.get("duration_ms") or 400)) / 1000.0)
            except Exception:
                dur = 0.4
        dur = max(0.12, float(dur))
        el = float(info.get("phase_elapsed_sec", 0.0) or 0.0)
        p = min(1.0, max(0.0, el / dur))
        if mode == "removing":
            p = 1.0 - p
        if mode == "holding":
            p = 1.0
            el = float(info.get("hold_elapsed_sec", 0.0) or 0.0)

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

        # 텍스트(옵션): 이미지 표시(holding) 후 text_show_delay_sec 뒤 페이드 인
        txt = info.get("text") or ""
        if txt and mode == "holding":
            delay = float(info.get("text_show_delay_sec", 1.0) or 1.0)
            hold_el = float(info.get("hold_elapsed_sec", 0.0) or 0.0)
            if hold_el >= delay:
                fade_dur = 0.35
                text_u = min(1.0, max(0.0, (hold_el - delay) / fade_dur))
                try:
                    font = resolve_font_profile("screen_caption", screen_w=w)
                except Exception:
                    font = resolve_font_profile("ui", size_px=22, screen_w=w)
                pad = 16
                box = pygame.Surface((w, 80), pygame.SRCALPHA)
                box.fill((0, 0, 0, int(160 * text_u)))
                screen.blit(box, (0, h - 80))
                cap_col = _normalize_rgb_color(get_font_profile("screen_caption").get("color", (0, 0, 0)))
                t_surf = font.render(str(txt), True, cap_col)
                if text_u < 1.0:
                    t_surf = t_surf.copy()
                    t_surf.set_alpha(int(255 * text_u))
                screen.blit(t_surf, (pad, h - 60))

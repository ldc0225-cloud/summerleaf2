import os
import sys
import traceback
import time
import gc
import statistics
import pygame, math
from collections import deque
from data import CONFIG, OBJ_ASSETS, CHAR_ASSETS
from flow import (
    GameFlow,
    merge_event_catalog,
    merge_call_event_catalog,
    merge_fragment_catalog,
    pick_global_auto_event,
    pick_sync_events,
    try_start_interact_event,
)
from engine import Player, FieldItem, BaseCharacter, Camera, EventManager, MusicManager, mask_terrain_class
import engine as engine_mod
from field_runtime import (
    CloudShadowSystem,
    FIELD_RUNTIME_UI,
    auto_res_zoom_in_trigger,
    auto_res_zoom_out_trigger,
    native_world_zoom_draw,
    tilt_shear_effective,
    apply_pending_camera_command,
    ui_layout_scale,
    scale_ui_text_px,
    try_start_hotkey_global_event,
    apply_dev_runtime_command,
    timed_effect_finished,
    timed_effect_init,
    timed_effect_value,
    _pygame_key_from_spec,
)
from render_align import snap_render_zoom


_SWING_RESTART_KEY = _pygame_key_from_spec(CONFIG.get("SWING_RESTART_HOTKEY", "g"))
if _SWING_RESTART_KEY is None:
    _SWING_RESTART_KEY = pygame.K_g

_UI_FONT_CACHE = {}


def _find_ui_font_file():
    # 설정으로 지정 가능
    p = str(CONFIG.get("UI_FONT_PATH", "") or "").strip()
    if p and os.path.isfile(p):
        return p

    # 프로젝트에 포함된 폰트(기기에서도 동일 경로로 배포되는 전제)
    dirs = [
        os.path.join("assets", "fonts"),
        os.path.join("assets", "font"),
        os.path.join("fonts"),
    ]
    preferred = [
        "NanumGothic.ttf",
        "NanumGothic.otf",
        "NotoSansCJKkr-Regular.otf",
        "NotoSansKR-Regular.otf",
        "NotoSansKR.ttf",
        "MalgunGothic.ttf",
        "malgun.ttf",
        "D2Coding.ttf",
    ]
    for d in dirs:
        try:
            if not os.path.isdir(d):
                continue
            for fn in preferred:
                fp = os.path.join(d, fn)
                if os.path.isfile(fp):
                    return fp
            for fn in os.listdir(d):
                low = (fn or "").lower()
                if low.endswith((".ttf", ".otf", ".ttc")):
                    fp = os.path.join(d, fn)
                    if os.path.isfile(fp):
                        return fp
        except Exception:
            continue
    return None


def get_ui_font(size: int):
    """한글 포함 UI용 폰트(파일 우선) — 없으면 SysFont로 안전 폴백."""
    try:
        size_i = int(size)
    except Exception:
        size_i = 14
    size_i = max(8, min(64, size_i))

    key = int(size_i)
    if key in _UI_FONT_CACHE:
        return _UI_FONT_CACHE[key]

    fp = _find_ui_font_file()
    if fp:
        try:
            f = pygame.font.Font(fp, size_i)
            _UI_FONT_CACHE[key] = f
            return f
        except Exception:
            pass
    try:
        f = pygame.font.SysFont("malgungothic", size_i)
    except Exception:
        f = pygame.font.SysFont("arial", size_i)
    _UI_FONT_CACHE[key] = f
    return f


def _log_path():
    try:
        os.makedirs("logs", exist_ok=True)
    except Exception:
        pass
    return os.path.join("logs", "runtime.log")


def log_line(msg: str):
    """Append a line to logs/runtime.log (best-effort)."""
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        ts = "time"
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def perf_profile_log(msg: str):
    """PERF 덤프 전용 로그(기본: logs/perf_profile.log). RG35XX 등에서 병목 수치만 따로 모을 때 사용."""
    try:
        if not bool(CONFIG.get("PERF_PROFILE_LOG_ENABLED", True)):
            return
        p = str(CONFIG.get("PERF_PROFILE_LOG_PATH", "logs/perf_profile.log") or "logs/perf_profile.log").strip()
        if not p:
            return
        dn = os.path.dirname(p)
        if dn:
            os.makedirs(dn, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        ts = "time"
        p = "logs/perf_profile.log"
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
            f.flush()
    except Exception:
        pass


def _is_android_runtime():
    try:
        if "android" in sys.platform:
            return True
    except Exception:
        pass
    return bool(os.environ.get("ANDROID_ARGUMENT") or os.environ.get("ANDROID_PRIVATE"))


def _sync_display_fit_config(lw, lh, pw, ph):
    """Android 등: 논리 해상도를 물리 화면에 비율 유지로 맞춘 present/입력 파라미터."""
    try:
        lw_i, lh_i = int(lw), int(lh)
        pw_i, ph_i = int(pw), int(ph)
    except Exception:
        lw_i, lh_i, pw_i, ph_i = 0, 0, 0, 0
    CONFIG["_PHYSICAL_WIDTH"] = pw_i
    CONFIG["_PHYSICAL_HEIGHT"] = ph_i
    use_fit = (
        _is_android_runtime()
        and bool(CONFIG.get("ANDROID_DISPLAY_FIT", True))
        and lw_i > 0
        and lh_i > 0
        and pw_i > 0
        and ph_i > 0
        and (pw_i != lw_i or ph_i != lh_i)
    )
    if not use_fit:
        CONFIG["_DISPLAY_FIT_ENABLED"] = False
        return
    scale = min(pw_i / float(lw_i), ph_i / float(lh_i))
    sw = max(1, int(round(lw_i * scale)))
    sh = max(1, int(round(lh_i * scale)))
    CONFIG["_DISPLAY_FIT_ENABLED"] = True
    CONFIG["_DISPLAY_FIT_SCALE"] = float(scale)
    CONFIG["_DISPLAY_OFFSET_X"] = int((pw_i - sw) // 2)
    CONFIG["_DISPLAY_OFFSET_Y"] = int((ph_i - sh) // 2)
    CONFIG["_DISPLAY_SCALED_W"] = sw
    CONFIG["_DISPLAY_SCALED_H"] = sh


def _embed_phys_to_logical_xy(px, py, *, scale_factor=1):
    """
    물리 화면 좌표 → 논리 렌더 좌표.
    Android display-fit(레터박스) 또는 UPSCALE 정수배 출력을 역변환한다.
    """
    try:
        lw = int(CONFIG.get("WIDTH", 0) or 0)
        lh = int(CONFIG.get("HEIGHT", 0) or 0)
    except Exception:
        return int(px), int(py)
    try:
        ix = int(px)
        iy = int(py)
    except Exception:
        ix, iy = 0, 0
    if lw <= 0 or lh <= 0:
        return ix, iy

    if bool(CONFIG.get("_DISPLAY_FIT_ENABLED", False)):
        try:
            ox = int(CONFIG.get("_DISPLAY_OFFSET_X", 0) or 0)
            oy = int(CONFIG.get("_DISPLAY_OFFSET_Y", 0) or 0)
            sw = int(CONFIG.get("_DISPLAY_SCALED_W", lw) or lw)
            sh = int(CONFIG.get("_DISPLAY_SCALED_H", lh) or lh)
        except Exception:
            ox, oy, sw, sh = 0, 0, lw, lh
        sw = max(1, sw)
        sh = max(1, sh)
        rx = ix - ox
        ry = iy - oy
        rx = max(0, min(sw - 1, rx))
        ry = max(0, min(sh - 1, ry))
        lx = rx * lw // sw
        ly = ry * lh // sh
        return max(0, min(lw - 1, lx)), max(0, min(lh - 1, ly))

    try:
        sf = int(scale_factor)
    except Exception:
        sf = 1
    if sf > 1:
        return max(0, min(lw - 1, ix // sf)), max(0, min(lh - 1, iy // sf))

    try:
        pw = int(CONFIG.get("_PHYSICAL_WIDTH", 0) or 0)
        ph = int(CONFIG.get("_PHYSICAL_HEIGHT", 0) or 0)
    except Exception:
        pw, ph = 0, 0
    if pw <= 0 or ph <= 0 or (pw == lw and ph == lh):
        return ix, iy
    lx = ix * lw // pw
    ly = iy * lh // ph
    return max(0, min(lw - 1, lx)), max(0, min(lh - 1, ly))


def _present_draw_surf_to_screen(screen, draw_surf, *, scale_factor, present_tmp):
    """논리 프레임(draw_surf)을 물리 screen에 출력."""
    if bool(CONFIG.get("_DISPLAY_FIT_ENABLED", False)):
        try:
            sw = int(CONFIG.get("_DISPLAY_SCALED_W", draw_surf.get_width()))
            sh = int(CONFIG.get("_DISPLAY_SCALED_H", draw_surf.get_height()))
            ox = int(CONFIG.get("_DISPLAY_OFFSET_X", 0) or 0)
            oy = int(CONFIG.get("_DISPLAY_OFFSET_Y", 0) or 0)
        except Exception:
            screen.blit(draw_surf, (0, 0))
            return
        screen.fill((0, 0, 0))
        tmp = present_tmp[0]
        if tmp is None or tmp.get_width() != sw or tmp.get_height() != sh:
            tmp = pygame.Surface((sw, sh))
            present_tmp[0] = tmp
        try:
            pygame.transform.scale(draw_surf, (sw, sh), tmp)
        except Exception:
            tmp = pygame.transform.scale(draw_surf, (sw, sh))
            present_tmp[0] = tmp
        screen.blit(tmp, (ox, oy))
        return
    if scale_factor != 1:
        try:
            pw = int(screen.get_width())
            ph = int(screen.get_height())
            pygame.transform.scale(draw_surf, (pw, ph), screen)
        except Exception:
            screen.blit(
                pygame.transform.scale(draw_surf, (screen.get_width(), screen.get_height())),
                (0, 0),
            )
    else:
        screen.blit(draw_surf, (0, 0))


def _blit_bg_view_scaled(dst, bg, cam_origin_x, cam_origin_y, zoom):
    """
    Memory-safe background render:
    Crop only the camera view from the big map surface, then scale that crop.
    This avoids scaling/caching the entire huge map surface (which can make RSS climb).
    """
    try:
        z = float(zoom)
    except Exception:
        z = 1.0
    z = max(1e-6, z)
    try:
        view_w = int(dst.get_width())
        view_h = int(dst.get_height())
    except Exception:
        return False
    try:
        src_w = int(math.ceil(view_w / z)) + 2
        src_h = int(math.ceil(view_h / z)) + 2
    except Exception:
        return False
    sx = int(math.floor(float(cam_origin_x)))
    sy = int(math.floor(float(cam_origin_y)))
    rect = pygame.Rect(sx, sy, src_w, src_h)
    try:
        bw, bh = bg.get_size()
    except Exception:
        return False
    rect = rect.clip(pygame.Rect(0, 0, bw, bh))
    if rect.width <= 1 or rect.height <= 1:
        return False
    try:
        sub = bg.subsurface(rect)
    except Exception:
        return False
    # Avoid per-frame Surface allocation: scale directly into dst when possible.
    try:
        pygame.transform.scale(sub, (view_w, view_h), dst)
    except Exception:
        try:
            scaled = pygame.transform.scale(sub, (view_w, view_h))
            dst.blit(scaled, (0, 0))
        except Exception:
            try:
                scaled = pygame.transform.scale(sub.copy(), (view_w, view_h))
                dst.blit(scaled, (0, 0))
            except Exception:
                return False
    return True


def _bg_view_world_rect(cam_origin_x, cam_origin_y, zoom, view_w, view_h, bw, bh):
    """카메라가 보는 맵 월드 픽셀 직사각형(_blit_bg_view_scaled와 동일한 크기 기준)."""
    z = max(1e-6, float(zoom))
    try:
        vw = int(view_w)
        vh = int(view_h)
        bw_i = int(bw)
        bh_i = int(bh)
    except Exception:
        return None
    src_w = int(math.ceil(vw / z)) + 2
    src_h = int(math.ceil(vh / z)) + 2
    sx = int(math.floor(float(cam_origin_x)))
    sy = int(math.floor(float(cam_origin_y)))
    r = pygame.Rect(sx, sy, src_w, src_h)
    r = r.clip(pygame.Rect(0, 0, bw_i, bh_i))
    if r.width <= 1 or r.height <= 1:
        return None
    return r


def _bg_expand_world_rect_perspective(base_r, bw, bh, zoom, view_w, view_h, f_q, shear_eff_px, pad_px):
    """
    틸트(f_q<1 시 세로로 더 필요) + 쉬어(가로 여유)를 위해 월드 크롭을 넉넉히 확장.
    """
    if base_r is None:
        return None
    z = max(1e-6, float(zoom))
    try:
        fq = max(0.05, min(1.0, float(f_q)))
    except Exception:
        fq = 1.0
    try:
        vw = int(view_w)
        vh = int(view_h)
    except Exception:
        vw, vh = 640, 480
    try:
        sh_eff = max(0, int(shear_eff_px))
    except Exception:
        sh_eff = 0
    try:
        pad = max(0, int(pad_px))
    except Exception:
        pad = 0
    min_w = int(math.ceil(float(vw) / z)) + 6 + int(math.ceil((float(sh_eff) + float(pad) * 2.0) / z))
    min_h = int(math.ceil(float(vh) / (fq * z))) + 8 + pad
    min_w = max(min_w, base_r.w + 2)
    min_h = max(min_h, base_r.h + 2)
    min_w = min(min_w, int(bw))
    min_h = min(min_h, int(bh))
    cx = base_r.centerx
    cy = base_r.centery
    nx = int(cx - min_w // 2)
    ny = int(cy - min_h // 2)
    nx = max(0, min(nx, int(bw) - min_w))
    ny = max(0, min(ny, int(bh) - min_h))
    r = pygame.Rect(nx, ny, min_w, min_h)
    return r.clip(pygame.Rect(0, 0, int(bw), int(bh)))


def rss_mb():
    """Best-effort process RSS (MB). Linux: /proc, Windows: ctypes fallback. Returns float or None."""
    # Linux /proc
    try:
        p = "/proc/self/status"
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            kb = float(parts[1])
                            return kb / 1024.0
    except Exception:
        pass
    # Windows ctypes
    try:
        import ctypes
        import ctypes.wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        GetCurrentProcess = ctypes.windll.kernel32.GetCurrentProcess
        GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi.dll")
        GetProcessMemoryInfo = psapi.GetProcessMemoryInfo
        GetProcessMemoryInfo.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            ctypes.wintypes.DWORD,
        ]
        GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if GetProcessMemoryInfo(GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return float(counters.WorkingSetSize) / (1024.0 * 1024.0)
    except Exception:
        pass
    return None


def _screen_to_world_field(mx, my, *, cam, cam_x_start, cam_y_start, player, bg_h, tilt_current, tilt_eps, shear_smoothed):
    """
    쉬어/틸트가 켜져도 '클릭한 곳'이 맞도록 screen(px) → world(px) 역변환.
    렌더링에서 오브젝트가 쓰는 변환을 역으로 적용한다.
    """
    try:
        zoom = snap_render_zoom(float(cam.current_zoom))
    except Exception:
        zoom = 1.0
    zoom = max(1e-6, zoom)
    mx = float(mx)
    my = float(my)

    tilt_active = abs(float(tilt_current) - 1.0) > float(tilt_eps)
    try:
        sh_br = float(CONFIG.get("SHEAR_BRANCH_OFF_EPS", 0.02))
    except Exception:
        sh_br = 0.02
    use_branch = tilt_active or float(shear_smoothed) > float(sh_br)
    if not use_branch:
        wx = float(cam.pos[0]) + (mx - float(CONFIG["WIDTH"]) / 2.0) / zoom
        wy = float(cam.pos[1]) + (my - float(CONFIG["HEIGHT"]) / 2.0) / zoom
        return wx, wy

    # 렌더와 동일: 배경 blit 원점은 int(round((0-cam)*zoom))
    bg_dx_i = int(round((0.0 - float(cam_x_start)) * zoom))
    bg_dy_i = int(round((0.0 - float(cam_y_start)) * zoom))
    try:
        tq = float(CONFIG.get("RENDER_TILT_STEP", 0.01))
    except Exception:
        tq = 0.01
    tq = max(0.001, min(0.1, tq))
    if tilt_active:
        f = max(0.2, min(1.0, float(tilt_current)))
        f_q = max(0.2, min(1.0, round(round(f / tq) * tq, 4)))
    else:
        f_q = 1.0

    try:
        player_sy = float((float(player.pos[1]) - float(cam_y_start)) * zoom)
    except Exception:
        player_sy = float((0.0 - float(cam_y_start)) * zoom)
    shift_y = float((player_sy - float(bg_dy_i)) * (1.0 - float(f_q)))
    # 렌더와 동일한 "하단 여백 방지" 보정까지 포함해야 틸트 상태 클릭이 정확해진다.
    # (배경이 세로 압축되면 아래쪽에 빈 공간이 생길 수 있어 shift_y를 추가로 늘림)
    try:
        scr_h = int(CONFIG.get("HEIGHT", 480) or 480)
    except Exception:
        scr_h = 480
    try:
        comp_h = float(bg_h) * float(zoom) * float(f_q)
    except Exception:
        comp_h = float(scr_h)
    bottom = float(bg_dy_i) + float(shift_y) + float(comp_h)
    if comp_h > 0.0 and bottom < float(scr_h):
        shift_y += float(scr_h) - float(bottom)

    # 렌더의 y_transform(실제 코드):
    #   y1 = bg_dy + shift_y + (y0 - bg_dy) * f_q
    # 역변환:
    #   y0 = bg_dy + (y1 - bg_dy - shift_y) / f_q
    top = float(bg_dy_i + shift_y)
    dy_raw = float(bg_dy_i) + (float(my) - float(top)) / max(1e-6, float(f_q))

    shear_eff = max(0.0, float(shear_smoothed))
    try:
        h = float(bg_h) * zoom * float(f_q)
    except Exception:
        h = zoom * float(f_q) * float(CONFIG["HEIGHT"])
    h = max(1.0, h)
    rel = (float(my) - top) / h
    rel = 0.0 if rel < 0.0 else (1.0 if rel > 1.0 else rel)
    xoff = (1.0 - rel) * float(shear_eff)

    dx_raw = float(mx) - xoff
    wx = float(cam_x_start) + float(dx_raw) / zoom
    wy = float(cam_y_start) + float(dy_raw) / zoom
    return wx, wy


def _screen_to_world_from_render_xform(mx, my, *, xf):
    """
    렌더 루프에서 '실제로 사용한' 변환 파라미터(xf)를 이용해 screen(px) → world(px) 역변환.
    - 월드 후처리 줌(world_zoom_off/draw)
    - 틸트 y_transform(하단 보정 포함)
    - 쉬어 x_offset_fn
    를 렌더와 동일한 기준으로 되돌린다.
    """
    if not xf:
        return None
    try:
        mx = float(mx)
        my = float(my)
    except Exception:
        return None

    # 1) 월드 후처리 줌 역변환 (UI 좌표 -> world_surf 좌표)
    try:
        zf = float(xf.get("world_zoom_draw", 1.0))
    except Exception:
        zf = 1.0
    zf = max(1e-6, float(zf))
    try:
        off_x = float(xf.get("world_zoom_off_x", 0.0))
        off_y = float(xf.get("world_zoom_off_y", 0.0))
    except Exception:
        off_x, off_y = 0.0, 0.0
    mx = (mx - off_x) / zf
    my = (my - off_y) / zf

    # 2) 틸트 y 역변환 (렌더 y_transform의 역)
    try:
        bg_dy = float(xf.get("bg_blit_dy", 0.0))
        shift_y = float(xf.get("shift_y", 0.0))
        f_q = float(xf.get("f_q", 1.0))
    except Exception:
        bg_dy, shift_y, f_q = 0.0, 0.0, 1.0
    f_q = max(1e-6, float(f_q))
    y0 = bg_dy + (my - bg_dy - shift_y) / f_q

    # 3) 쉬어 x 역변환 (x_offset_fn의 역)
    try:
        shear_eff = float(xf.get("shear_eff", 0.0))
    except Exception:
        shear_eff = 0.0
    if shear_eff > 0.0:
        try:
            h = float(xf.get("shear_h", 1.0))
        except Exception:
            h = 1.0
        h = max(1.0, float(h))
        top = float(bg_dy) + float(shift_y)
        rel = (float(my) - top) / h
        rel = 0.0 if rel < 0.0 else (1.0 if rel > 1.0 else rel)
        xoff = (1.0 - rel) * float(shear_eff)
        x0 = float(mx) - xoff
    else:
        x0 = float(mx)

    # 4) world 복원
    try:
        z = float(xf.get("z", 1.0))
    except Exception:
        z = 1.0
    z = max(1e-6, float(z))
    try:
        cam_draw_x = float(xf.get("cam_draw_x", 0.0))
        cam_draw_y = float(xf.get("cam_draw_y", 0.0))
    except Exception:
        cam_draw_x, cam_draw_y = 0.0, 0.0
    wx = cam_draw_x + x0 / z
    wy = cam_draw_y + y0 / z
    return wx, wy


def _preserve_cam_world_center(cam, map_w, map_h):
    """해상도/뷰포트 변경 후에도 cam.pos가 가리키던 월드 점이 화면 중앙에 오도록 클램프."""
    try:
        wx, wy = float(cam.pos[0]), float(cam.pos[1])
    except Exception:
        return
    z = max(1e-6, float(getattr(cam, "current_zoom", 1.0) or 1.0))
    try:
        vw = float(cam.width) / z
        vh = float(cam.height) / z
    except Exception:
        return
    mw, mh = float(map_w), float(map_h)
    tx, ty = wx, wy
    if mw > vw:
        min_cx = vw / 2.0
        max_cx = mw - vw / 2.0
        tx = max(min_cx, min(max_cx, tx))
    else:
        tx = mw / 2.0
    if mh > vh:
        min_cy = vh / 2.0
        max_cy = mh - vh / 2.0
        ty = max(min_cy, min(max_cy, ty))
    else:
        ty = mh - vh / 2.0
    try:
        cam.pos[0] = float(tx)
        cam.pos[1] = float(ty)
    except Exception:
        pass


def _auto_res_follow_offset_world(scale_factor, cam_zoom=1.0):
    """논리 해상도(scale_factor) 기준 follow Y 오프셋(월드 단위)."""
    try:
        base = float(CONFIG.get("CAMERA_FOLLOW_OFFSET_Y_PX", 0) or 0)
    except Exception:
        base = 0.0
    sf = max(1e-6, float(scale_factor))
    z = max(1e-6, float(cam_zoom))
    return (base / sf) / z


def _auto_res_compensate_follow_offset(cam, prev_scale_factor, new_scale_factor):
    """640↔320 전환 시 follow 오프셋(월드) 변화만큼 cam.pos.y를 보정 — cam.update 1프레임 튐 방지."""
    if getattr(cam, "_cam_mode", "") == "fixed_world":
        return
    try:
        z = max(1e-6, float(getattr(cam, "current_zoom", 1.0) or 1.0))
        old_w = _auto_res_follow_offset_world(prev_scale_factor, z)
        new_w = _auto_res_follow_offset_world(new_scale_factor, z)
        cam.pos[1] = float(cam.pos[1]) + (old_w - new_w)
    except Exception:
        pass


def _player_feet_screen_xy_like_draw(px, py, cam_draw_x, cam_draw_y, z, y_transform, x_offset_fn):
    """
    FieldItem.draw와 동일: cam_draw(렌더 스냅·쉬어 중앙 보정 반영) + 틸트 y_transform + 쉬어 x_offset_fn.
    cam.to_screen(cam.pos 기준)과 달라서, 월드 후처리 줌 앵커는 반드시 이 경로를 써야 쉬어 시 튐이 없다.
    """
    dx_base = (float(px) - float(cam_draw_x)) * float(z)
    dy_base = (float(py) - float(cam_draw_y)) * float(z)
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
    return float(dx_base), float(dy_base)


def main():
    log_line("=== launch ===")
    # Android/SDL: init 전 pre_init이 없으면 mixer가 무음이거나 play()가 실패하는 경우가 있다.
    try:
        if not pygame.get_init():
            pygame.mixer.pre_init(44100, -16, 2, 2048)
    except Exception:
        pass
    pygame.init()
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
    except Exception as e:
        print(f"[MUSIC] mixer init failed: {e}")
        log_line(f"[MUSIC] mixer init failed: {e}")

    # Output mode: UPSCALE_320 (320->640) or NATIVE_640 (640 direct), optional fullscreen
    # (define bindings before using nonlocal)
    screen = None
    draw_surf = None   # UI 포함 최종(논리 해상도)
    render_surf = None # draw_surf alias (기존 코드 호환)
    world_surf = None  # 월드 전용(오버레이 제외)
    physical_w = 0
    physical_h = 0
    output_mode = str(CONFIG.get("OUTPUT_MODE", "UPSCALE_320") or "UPSCALE_320").strip().upper()
    try:
        upscale_factor = int(CONFIG.get("UPSCALE_FACTOR", 2) or 2)
    except Exception:
        upscale_factor = 2
    upscale_factor = max(1, min(6, upscale_factor))
    fullscreen_on = bool(CONFIG.get("FULLSCREEN", False))
    if _is_android_runtime():
        fullscreen_on = True
    scale_factor = 1
    last_frame_logical = None  # 해상도 전환 시 1프레임 블랙 방지용
    present_scale_tmp = [None]  # Android display-fit present 버퍼

    # 자동 가변 해상도 전환(옵션): 월드 줌 2x "완료" 시 320x240 업스케일로 전환 + 줌 1x로 리맵
    auto_res_enabled = bool(CONFIG.get("AUTO_OUTPUT_MODE_ENABLED", False))
    auto_zoom_in_trigger = auto_res_zoom_in_trigger()
    auto_zoom_out_trigger = auto_res_zoom_out_trigger()
    try:
        auto_switch_cooldown_ms = int(CONFIG.get("AUTO_OUTPUT_MODE_COOLDOWN_MS", 900))
    except Exception:
        auto_switch_cooldown_ms = 900
    last_auto_switch_ms = -999999
    # 현재 출력모드가 "줌을 해상도로 치환"한 정도(기본 1.0, UPSCALE_320로 내려가면 2.0)
    auto_res_zoom_mul = 1.0
    auto_res_hold_cam_pos = None  # 해상도 전환 프레임: cam.update()가 pos를 덮어쓰지 않도록

    def _apply_output_mode(*, mode, fullscreen):
        nonlocal screen, draw_surf, render_surf, world_surf, physical_w, physical_h, scale_factor, output_mode, fullscreen_on, last_frame_logical
        m = str(mode or "").strip().upper()
        if m not in ("UPSCALE_320", "NATIVE_640"):
            m = "UPSCALE_320"
        output_mode = m
        fullscreen_on = bool(fullscreen)

        if output_mode == "NATIVE_640":
            CONFIG["WIDTH"], CONFIG["HEIGHT"] = 640, 480
            scale_factor = 1
        else:
            CONFIG["WIDTH"], CONFIG["HEIGHT"] = 320, 240
            scale_factor = int(upscale_factor)

        lw, lh = int(CONFIG["WIDTH"]), int(CONFIG["HEIGHT"])
        # UI_LAYOUT_WIDTH는 NATIVE_640 기준 고정(320 모드에서 pushbutton·말풍선 0.5× 스케일).
        try:
            CONFIG["UI_LAYOUT_WIDTH"] = int(
                CONFIG.get("UI_LAYOUT_BASE_WIDTH", CONFIG.get("UI_LAYOUT_WIDTH", 640)) or 640
            )
        except Exception:
            CONFIG["UI_LAYOUT_WIDTH"] = 640
        try:
            base_off = float(CONFIG.get("CAMERA_FOLLOW_OFFSET_Y_PX", 0) or 0)
            CONFIG["CAMERA_FOLLOW_OFFSET_Y_PX_EFFECTIVE"] = float(base_off) / max(
                1e-6, float(scale_factor)
            )
        except Exception:
            pass
        flags = pygame.FULLSCREEN if fullscreen_on else 0
        if _is_android_runtime() and bool(CONFIG.get("ANDROID_DISPLAY_FIT", True)):
            screen = pygame.display.set_mode((0, 0), flags)
            physical_w, physical_h = screen.get_size()
            _sync_display_fit_config(lw, lh, physical_w, physical_h)
        else:
            physical_w, physical_h = int(lw * scale_factor), int(lh * scale_factor)
            screen = pygame.display.set_mode((physical_w, physical_h), flags)
            _sync_display_fit_config(lw, lh, physical_w, physical_h)
        # 새 줌 시스템: "오버레이 제외 최종 출력물"을 통째로 scale 하므로,
        # 출력 모드와 무관하게 항상 논리 해상도 Surface에 렌더링하고 마지막에만 screen으로 blit한다.
        draw_surf = pygame.Surface((lw, lh))
        render_surf = draw_surf
        world_surf = pygame.Surface((lw, lh))
        # 전환 직후 1프레임 검은 화면을 피하기 위해 직전 프레임을 즉시 한 번 present
        try:
            if last_frame_logical is not None:
                lf = last_frame_logical
                try:
                    pygame.transform.scale(lf, (lw, lh), draw_surf)
                except Exception:
                    draw_surf.blit(pygame.transform.scale(lf, (lw, lh)), (0, 0))
                _present_draw_surf_to_screen(
                    screen, draw_surf, scale_factor=scale_factor, present_tmp=present_scale_tmp
                )
                pygame.display.flip()
        except Exception:
            pass

    # init output mode
    _apply_output_mode(mode=output_mode, fullscreen=fullscreen_on)
    # viewport-temporary surfaces (avoid scaling whole map surfaces)
    view_bg_tmp = None
    view_mask_tmp = None
    tilt_bg_tmp = None
    shear_bg_tmp = None
    tilt_mask_tmp = None
    shear_mask_tmp = None
    vp_bg_scale_tmp = None  # BG_VIEWPORT: 맵 크롭→스케일 재사용 버퍼

    font = get_ui_font(10)

    # 하드웨어 마우스 커서:
    # - PC에선 커서가 보이는 게 디버그/조작에 유리
    # - rg35xx 같은 마우스 없는 기기(EMBEDDED_LIGHTWEIGHT)는 소프트웨어 커서(ui_cursor) 사용
    try:
        hide_mouse = bool(CONFIG.get("EMBEDDED_LIGHTWEIGHT", False)) or _is_android_runtime()
        pygame.mouse.set_visible(not hide_mouse)
    except Exception:
        pass
    clock = pygame.time.Clock()
    cloud_fx = CloudShadowSystem()
    flow = GameFlow(CONFIG)
    raw_events = flow.load_events()
    events_catalog = merge_event_catalog(raw_events)
    fragment_catalog = merge_call_event_catalog(raw_events)
    # 시스템 이벤트: from flow import start_system_event → start_system_event(ev_mgr, events_catalog, "event_id")
    is_fullscreen = False

    # --- 온보딩 / 스폰 분기용: 실행 시점에 디스크에 세이브 파일이 있었는지 ---
    had_save_at_launch = os.path.isfile(flow.save_path)
    save_file = flow.load_save_data()
    save_spawn_snapshot = None
    if had_save_at_launch and isinstance(save_file, dict):
        save_spawn_snapshot = {
            "current_map": save_file.get("current_map"),
            "player_pos": save_file.get("player_pos"),
        }

    # 매 실행 인트로→데모까지는 START_MAP만; 본편 맵/좌표는 데모 종료 후 스폰 블록에서 적용
    initial_map_data = {"current_map": CONFIG["START_MAP"]}
    map_id, bg, mask, player, objs, npcs = flow.load_map(save_data=initial_map_data)

    # 2. 카메라 및 매니저 설정
    cam = Camera(CONFIG["WIDTH"], CONFIG["HEIGHT"])
    cam.snap_to(player.pos)
    cam.set_follow_player(smooth=False)
    music_mgr = MusicManager()
    ev_mgr = EventManager(flow, music_mgr=music_mgr)
    ev_mgr.set_fragment_catalog(fragment_catalog)

    def _reload_event_bundles():
        nonlocal raw_events, events_catalog, fragment_catalog
        raw_events = flow.load_events()
        events_catalog = merge_event_catalog(raw_events)
        fragment_catalog = merge_call_event_catalog(raw_events)
        ev_mgr.set_fragment_catalog(fragment_catalog)

    def _queue_sync_for_map(target_map_id):
        """본편(boot_phase>=2) 맵 로드/변경 직후: progress 조건 맞는 SYNC 이벤트 대기열."""
        if flow.boot_phase < 2:
            ev_mgr.pending_sync_queue = []
            return
        ev_mgr.pending_sync_queue = pick_sync_events(
            raw_events,
            flow.save_data,
            target_map_id,
            events_catalog,
            session_vars={"gamestart": flow.boot_phase},
        )

    def _try_start_pending_sync_event():
        """대기 중인 SYNC 이벤트를 하나 시작 (활성 이벤트 없을 때만)."""
        if ev_mgr.active_event or flow.boot_phase < 2:
            return False
        pq = getattr(ev_mgr, "pending_sync_queue", None) or []
        while pq:
            sid = pq.pop(0)
            ev = events_catalog.get(sid)
            if not ev:
                continue
            ev_mgr.reset_entity_event_zooms(player, npcs, objs)
            ev_mgr.start_event(
                ev.get("steps") or [],
                sid,
                ev.get("result"),
                ev,
                is_sync=True,
            )
            ev_mgr.field_tilt_snapshot = (
                ui.tilt_bg_demo,
                float(ui.tilt_target),
                float(tilt_current),
                bool(ui.shear_debug_on),
            )
            player.stop_moving()
            return True
        ev_mgr.pending_sync_queue = []
        return False

    # --- BG ZONES (원경/배경 범위 지정) ---
    # world_data.json: bg_zones = [{rect:[x,y,w,h], layer:int, draw_only_when_tilt:bool, update_policy:str, sort_policy:str, cull_margin_px:int}, ...]
    bg_zones_norm = []
    ent_bg_zone_idx = {}  # id(ent) -> zone_idx (None이면 근경)
    bg_zone_cached_order = {}  # zone_idx -> [ents...] (sort_policy == "cached")

    def _norm_bg_zones(_map_id: str):
        m = flow.world_data.get(_map_id, {}) if _map_id else {}
        raw = m.get("bg_zones", []) or []
        out = []
        for z in raw:
            try:
                r = z.get("rect", None)
            except Exception:
                r = None
            if not (isinstance(r, (list, tuple)) and len(r) == 4):
                continue
            try:
                zx, zy, zw, zh = int(r[0]), int(r[1]), int(r[2]), int(r[3])
            except Exception:
                continue
            if zw <= 0 or zh <= 0:
                continue
            try:
                layer = int(z.get("layer", -50))
            except Exception:
                layer = -50
            dot = bool(z.get("draw_only_when_tilt", True))
            up = str(z.get("update_policy", "none") or "none").strip().lower()
            if up not in ("none", "lowrate", "normal"):
                up = "none"
            sp = str(z.get("sort_policy", "none") or "none").strip().lower()
            if sp not in ("none", "cached"):
                sp = "none"
            try:
                cm = int(z.get("cull_margin_px", 160) or 160)
            except Exception:
                cm = 160
            cm = max(0, min(2000, cm))
            out.append(
                {
                    "name": str(z.get("name", "") or ""),
                    "rect": [zx, zy, zw, zh],
                    "layer": layer,
                    "draw_only_when_tilt": dot,
                    "update_policy": up,
                    "sort_policy": sp,
                    "cull_margin_px": cm,
                }
            )
        return out

    def _bg_zone_pick(ent, zones):
        try:
            x, y = float(ent.pos[0]), float(ent.pos[1])
        except Exception:
            return None
        # 리스트 순서가 우선순위(겹치면 먼저 나온 존이 이김)
        for i, z in enumerate(zones):
            zx, zy, zw, zh = z["rect"]
            if zx <= x <= zx + zw and zy <= y <= zy + zh:
                return i
        return None

    def _rebuild_bg_zone_cache():
        nonlocal bg_zones_norm, ent_bg_zone_idx, bg_zone_cached_order
        bg_zones_norm = _norm_bg_zones(map_id)
        ent_bg_zone_idx = {}
        bg_zone_cached_order = {}
        if not bg_zones_norm:
            return
        # assign once at map load (원경은 대부분 고정 오브젝트)
        for ent in list(objs) + list(npcs):
            zi = _bg_zone_pick(ent, bg_zones_norm)
            if zi is not None:
                ent_bg_zone_idx[id(ent)] = zi
        # cached ordering per zone (sort once)
        for zi, z in enumerate(bg_zones_norm):
            if z.get("sort_policy") != "cached":
                continue
            pool = []
            for ent in list(objs) + list(npcs):
                if ent_bg_zone_idx.get(id(ent)) != zi:
                    continue
                # 손에 들린 오브젝트는 근경 취급(런타임에서 분리)
                if bool(getattr(ent, "is_held", False)):
                    continue
                pool.append(ent)
            pool.sort(key=lambda e: (getattr(e, "layer", 0) or 0, float(getattr(e, "pos", [0, 0])[1] or 0)))
            bg_zone_cached_order[zi] = pool

    _rebuild_bg_zone_cache()

    # 3. 상호작용 관련 변수 (아버님 과거 코드 방식 복구)
    ui = FIELD_RUNTIME_UI
    zoom_steps = list(CONFIG.get("DEBUG_ZOOM_STEPS", [2.0, 0.5, 1.0]))
    if len(zoom_steps) < 1:
        zoom_steps = [1.0]
    try:
        best_i, best_d = 0, 1e9
        for i, z in enumerate(zoom_steps):
            try:
                d = abs(float(z) - float(cam.target_zoom))
            except (TypeError, ValueError):
                d = 1e9
            if d < best_d:
                best_d, best_i = d, i
        ui.zoom_idx = best_i
    except Exception:
        ui.zoom_idx = 0
    try:
        cam.target_zoom = float(zoom_steps[int(ui.zoom_idx)])
    except (TypeError, ValueError, IndexError):
        pass

    tilt_current = 1.0
    shear_smoothed = 0.0  # 쉬어 픽셀 목표에 서서히 수렴
    if bool(CONFIG.get("FIELD_PERSPECTIVE_DEFAULT_ON", False)):
        try:
            _field_tilt_f = float(CONFIG.get("TILT_BG_ON_FACTOR", 0.72))
        except (TypeError, ValueError):
            _field_tilt_f = 0.72
        try:
            _tfm0 = float(CONFIG.get("TILT_FACTOR_MIN", 0.2))
        except (TypeError, ValueError):
            _tfm0 = 0.2
        _tfm0 = max(0.02, min(0.99, _tfm0))
        _field_tilt_f = max(_tfm0, min(1.0, _field_tilt_f))
        ui.tilt_target = float(_field_tilt_f)
        tilt_current = float(_field_tilt_f)

    if bool(CONFIG.get("TILT_SHEAR_ENABLED", False)):
        try:
            shear_smoothed = float(
                tilt_shear_effective(None, tilt_current, False)
            )
        except Exception:
            pass

    # --- 새 월드 줌(후처리) 컨트롤러 ---
    # 원칙:
    # - 월드(배경/오브젝트/마스크/월드FX)를 world_surf에 렌더
    # - 그 결과물만 통째로 스케일해서 draw_surf에 합성
    # - UI/오버레이는 draw_surf에 따로 그려서 줌 영향을 받지 않음
    try:
        world_zoom_enabled = bool(CONFIG.get("WORLD_ZOOM_ENABLED", True))
    except Exception:
        world_zoom_enabled = True
    try:
        world_zoom_min = float(CONFIG.get("WORLD_ZOOM_MIN", 0.5))
    except Exception:
        world_zoom_min = 0.5
    try:
        world_zoom_max = float(CONFIG.get("WORLD_ZOOM_MAX", 2.0))
    except Exception:
        world_zoom_max = 2.0
    world_zoom_min = max(0.1, min(8.0, world_zoom_min))
    world_zoom_max = max(world_zoom_min, min(8.0, world_zoom_max))
    try:
        world_zoom_speed = float(CONFIG.get("WORLD_ZOOM_SPEED", 2.0))
    except Exception:
        world_zoom_speed = 2.0
    world_zoom_speed = max(0.05, min(20.0, world_zoom_speed))
    try:
        world_zoom_target = float(CONFIG.get("WORLD_ZOOM_DEFAULT", 1.0))
    except Exception:
        world_zoom_target = 1.0
    world_zoom_target = max(world_zoom_min, min(world_zoom_max, world_zoom_target))
    world_zoom_current = float(world_zoom_target)
    # 줌 합성 정보(입력 역변환에 사용): draw_surf 기준 좌표계
    world_zoom_off_x = 0.0
    world_zoom_off_y = 0.0
    world_zoom_draw = 1.0
    world_zoom_tmp = None  # 스케일 결과 재사용 버퍼
    # 입력 역변환을 위한 "렌더 변환 캐시"(전 프레임)
    render_xform_for_input = None
    # 통합 변환 캐시(LRU + MB 상한): tilt/shear 결과(및 일부 스케일 결과)를 한 곳에서 관리
    # - 기존 bg_scale_cache/mask_scale_cache/shear_cache는 중복이 많고 clear로 스파이크가 나기 쉬움
    # - 여기서는 "총 MB"를 제한해 피크 RSS를 강제로 낮춘다.
    from collections import OrderedDict

    _render_cache = OrderedDict()  # key -> (Surface, est_mb)
    _render_cache_mb = 0.0
    try:
        _render_cache_mb_limit = float(CONFIG.get("RENDER_CACHE_MB_LIMIT", 220.0))
    except Exception:
        _render_cache_mb_limit = 220.0
    _render_cache_mb_limit = max(32.0, min(1024.0, _render_cache_mb_limit))
    try:
        _render_cache_max_items = int(CONFIG.get("RENDER_CACHE_MAX_ITEMS", 96) or 96)
    except Exception:
        _render_cache_max_items = 96
    _render_cache_max_items = max(16, min(512, _render_cache_max_items))

    def _rc_get(key):
        nonlocal _render_cache_mb
        v = _render_cache.get(key)
        if v is None:
            return None
        try:
            _render_cache.move_to_end(key)
        except Exception:
            pass
        return v[0]

    def _rc_put(key, surf):
        nonlocal _render_cache_mb
        if surf is None:
            return
        try:
            w, h = surf.get_width(), surf.get_height()
        except Exception:
            return
        est = _est_rgba_mb(w, h)
        # 너무 큰 1개는 캐시하지 않음(피크 방지)
        if est <= 0.0 or est > max(8.0, _render_cache_mb_limit * 0.6):
            return

        # 기존 값 있으면 교체(용량 갱신)
        old = _render_cache.get(key)
        if old is not None:
            try:
                _render_cache_mb -= float(old[1])
            except Exception:
                pass
            try:
                del _render_cache[key]
            except Exception:
                pass

        # LRU 퇴출: MB 상한 + item 상한
        try:
            while (_render_cache_mb + est) > _render_cache_mb_limit and _render_cache:
                _k, (_s, mb) = _render_cache.popitem(last=False)
                try:
                    _render_cache_mb -= float(mb)
                except Exception:
                    pass
            while len(_render_cache) >= _render_cache_max_items and _render_cache:
                _k, (_s, mb) = _render_cache.popitem(last=False)
                try:
                    _render_cache_mb -= float(mb)
                except Exception:
                    pass
        except Exception:
            _render_cache.clear()
            _render_cache_mb = 0.0

        _render_cache[key] = (surf, float(est))
        _render_cache_mb += float(est)

    def _render_cache_lru_free_target_mb(free_mb: float) -> None:
        """LRU에서 약 free_mb(추정 MB)만큼 퇴출. 전량 clear 대신 점진적 정리에 사용."""
        nonlocal _render_cache_mb
        try:
            need = float(free_mb)
        except Exception:
            return
        if need <= 0.0 or not _render_cache:
            return
        freed = 0.0
        while freed + 1e-6 < need and _render_cache:
            try:
                _k, (_s, mb) = _render_cache.popitem(last=False)
            except Exception:
                break
            try:
                m = float(mb)
            except Exception:
                m = 0.0
            try:
                _render_cache_mb -= m
            except Exception:
                pass
            freed += m
        if _render_cache_mb < 0.0:
            _render_cache_mb = 0.0

    def _est_rgba_mb(w: int, h: int) -> float:
        try:
            return (float(int(w)) * float(int(h)) * 4.0) / (1024.0 * 1024.0)
        except Exception:
            return 0.0

    # 대형 Surface 생성 스파이크 방지 (특히 틸트/쉬어 중). 초과 시 해당 프레임은 안전 폴백.
    try:
        _tmp_surf_mb_limit = float(CONFIG.get("TEMP_SURF_MB_LIMIT", 96.0))
    except Exception:
        _tmp_surf_mb_limit = 96.0
    _tmp_surf_mb_limit = max(24.0, min(512.0, _tmp_surf_mb_limit))

    _full_scale_tmp = {}  # cname -> reusable Surface

    def _new_scale_tmp_like(src_surf, w, h):
        """Create a destination Surface compatible with src_surf for transform.scale(dst=...)."""
        try:
            has_alpha = bool(src_surf.get_flags() & pygame.SRCALPHA)
        except Exception:
            has_alpha = False
        try:
            if has_alpha:
                return pygame.Surface((int(w), int(h)), pygame.SRCALPHA).convert_alpha()
            return pygame.Surface((int(w), int(h))).convert()
        except Exception:
            # last resort (no convert available yet)
            return pygame.Surface((int(w), int(h)), pygame.SRCALPHA if has_alpha else 0)

    def _rc_get_full_scale(cname, surf, zq, *, is_zooming=False):
        """
        배경/마스크 전체 스케일.
        - B안: '장기 보관'은 통합 _render_cache(LRU/MB)만 사용
        - 단, 캐시에 못 넣는 큰 서피스라도 매 프레임 새로 할당하지 않도록 목적지 Surface를 재사용한다.
        """
        try:
            zk = float(zq)
        except Exception:
            zk = 1.0
        if zk <= 0:
            zk = 1.0
        k = ("full_scale", str(cname), id(surf), round(zk, 6))
        got = _rc_get(k)
        if got is not None:
            return got
        try:
            bw0, bh0 = surf.get_size()
        except Exception:
            return cam.get_fast_image(surf, zk)
        nw = max(1, int(round(float(bw0) * zk)))
        nh = max(1, int(round(float(bh0) * zk)))
        # scale into reusable destination to avoid allocations
        tmp = _full_scale_tmp.get(str(cname))
        if tmp is None or tmp.get_width() != nw or tmp.get_height() != nh:
            tmp = _new_scale_tmp_like(surf, nw, nh)
            _full_scale_tmp[str(cname)] = tmp
        try:
            pygame.transform.scale(surf, (nw, nh), tmp)
        except TypeError:
            # 일부 pygame 빌드에서 dest 인자를 지원 안 할 수 있음 → 폴백
            tmp = pygame.transform.scale(surf, (nw, nh))
            _full_scale_tmp[str(cname)] = tmp

        # 줌이 멈췄을 때만(=키가 안정적일 때만) 캐시에 넣어 장기 재사용
        try:
            should_cache = (not bool(is_zooming))
        except Exception:
            should_cache = False
        if should_cache:
            est_mb = _est_rgba_mb(nw, nh)
            # 너무 큰 1장은 render cache 상한 거의 전체를 차지할 수 있으므로, 상한의 95% 이내만 허용
            if est_mb > 0.0 and est_mb <= float(_render_cache_mb_limit) * 0.95:
                _rc_put(k, tmp.copy())
                got2 = _rc_get(k)
                if got2 is not None:
                    return got2
        return tmp

    ui_cursor = [CONFIG["WIDTH"]//2, CONFIG["HEIGHT"]//2] 
    cursor_speed = float(CONFIG.get("CURSOR_SPEED", 3.5))
    
    pending_action = None  # "interact" | "interact_npc"
    target_obj = None
    target_npc = None

    # [추가] 클릭 피드백 시스템
    click_feedback = None  # {"pos": (x, y), "color": (r, g, b), "start_time": t}
    # 더블클릭(달리기) 판정용
    last_click_ms = -999999
    last_click_world = None  # (x,y)
    # 키 더블탭(달리기) 판정용 (대표: a/space/enter)
    last_move_key_ms = -999999
    last_move_key = None

    def _auto_res_to_native640():
        """320(UPSCALE) + 줌2x 치환 상태 → 640(NATIVE)으로 복귀. world_zoom은 640 기준(1.0~2.0) 유지."""
        nonlocal output_mode, auto_res_zoom_mul, last_auto_switch_ms
        if not auto_res_enabled:
            return
        if output_mode == "NATIVE_640" and float(auto_res_zoom_mul) <= 1.0:
            return
        now_ms = pygame.time.get_ticks()
        if (now_ms - int(last_auto_switch_ms)) < int(auto_switch_cooldown_ms):
            return
        prev_sf = float(scale_factor)
        _apply_output_mode(mode="NATIVE_640", fullscreen=fullscreen_on)
        _after_resolution_change(prev_scale_factor=prev_sf)
        auto_res_zoom_mul = 1.0
        try:
            _preserve_cam_world_center(cam, bg_w, bg_h)
        except Exception:
            pass
        last_auto_switch_ms = int(now_ms)

    def _after_resolution_change(*, prev_scale_factor=1):
        """해상도 전환 후: 카메라/커서/캐시·서피스 정리 + 커서/카메라 오프셋 스케일 보정."""
        nonlocal fade_overlay_surf, world_zoom_tmp, font
        try:
            cam.width, cam.height = int(CONFIG["WIDTH"]), int(CONFIG["HEIGHT"])
        except Exception:
            pass
        try:
            CONFIG["UI_LAYOUT_WIDTH"] = int(
                CONFIG.get("UI_LAYOUT_BASE_WIDTH", CONFIG.get("UI_LAYOUT_WIDTH", 640)) or 640
            )
        except Exception:
            CONFIG["UI_LAYOUT_WIDTH"] = 640
        # 카메라 follow 오프셋을 물리 기준으로 유지(UPSCALE_320면 논리 px이 절반 효과)
        try:
            base_off = float(CONFIG.get("CAMERA_FOLLOW_OFFSET_Y_PX", 0) or 0)
        except Exception:
            base_off = 0.0
        try:
            CONFIG["CAMERA_FOLLOW_OFFSET_Y_PX_EFFECTIVE"] = float(base_off) / max(1e-6, float(scale_factor))
        except Exception:
            pass

        # 커서(UI 좌표)는 논리 px이므로, 전환 후에도 "물리 화면에서 같은 위치"로 보이게 리스케일
        try:
            ps = max(1e-6, float(prev_scale_factor))
            ns = max(1e-6, float(scale_factor))
            k = ps / ns
            ui_cursor[0] = float(ui_cursor[0]) * k
            ui_cursor[1] = float(ui_cursor[1]) * k
        except Exception:
            pass
        try:
            ui_cursor[0] = max(0, min(int(CONFIG["WIDTH"]) - 1, int(ui_cursor[0])))
            ui_cursor[1] = max(0, min(int(CONFIG["HEIGHT"]) - 1, int(ui_cursor[1])))
        except Exception:
            pass
        try:
            _clear_transform_caches()
        except Exception:
            pass
        try:
            if hasattr(cam, "image_cache") and isinstance(cam.image_cache, dict):
                cam.image_cache.clear()
        except Exception:
            pass
        try:
            lw_r = int(CONFIG["WIDTH"])
            lh_r = int(CONFIG["HEIGHT"])
            fade_overlay_surf = pygame.Surface((lw_r, lh_r))
        except Exception:
            pass
        world_zoom_tmp = None
        try:
            for _ok, _ov in list(overlay_cache.items()):
                if str(_ok).endswith("_surf"):
                    overlay_cache[_ok] = None
                elif _ok in ("debug_text", "perf_text", "bgm_text", "rss_text", "cache_text"):
                    overlay_cache[_ok] = ""
            overlay_cache["zone_labels"] = {}
        except Exception:
            pass
        try:
            font = get_ui_font(max(6, int(round(10.0 * float(CONFIG["WIDTH"]) / 640.0))))
        except Exception:
            pass

    # 페이드 오버레이: 매 프레임 Surface 새로 만들지 않음 (저사양/핸드헬드용)
    fade_overlay_surf = pygame.Surface((CONFIG["WIDTH"], CONFIG["HEIGHT"]))

    # 애니메이션 중 캐시 churn(쌓고 비우기)을 막기 위한 상태 추적
    last_tilt_draw = float(tilt_current)
    last_shear_draw = float(shear_smoothed)

    # 시작 시 그네가 자동으로 흔들리지 않게: 충분히 감쇠된 "정지 상태"로 시작
    # (b키 SWING_RESTART_HOTKEY로만 최대 진폭에서 재시작)
    try:
        _tau0 = float(CONFIG.get("SWING_DAMP_TAU_SEC", 10.0) or 10.0)
    except Exception:
        _tau0 = 10.0
    _tau0 = max(0.2, min(120.0, _tau0))
    try:
        swing_t0_ms = int(pygame.time.get_ticks()) - int(_tau0 * 1000.0 * 20.0)
    except Exception:
        swing_t0_ms = pygame.time.get_ticks()
    swing_ent = None

    # --- 그네 타기(데모) ---
    # 상태: None(미사용) | "approach" | "mount" | "ride"
    swing_ride_mode = None
    swing_ride_power = 0.0  # 0~1
    swing_ride_theta_amp = None
    swing_ride_pump_times = deque()
    swing_ride_prev_height = None
    swing_ride_stop_hold = 0.0
    swing_ride_mount_end_ms = None
    swing_ride_no_dismount_until_s = 0.0
    swing_ride_mount_frames_total = 4
    swing_ride_mount_frames_left = 0
    swing_ride_mount_start_xy = None
    swing_ride_mount_start_h = 0.0
    # 정렬은 layer 변경 대신 ysort bias로 처리

    # --- 그네 점프(간소화: 뒤 정점 누름 시작 -> 앞 정점 떼면 점프) ---
    swing_jump_ready = False
    swing_jump_hold_active = False
    swing_jump_hold_started_ms = 0
    swing_jump_hold_press_ratio = 0.0   # depth_n/depth_peak_n (≈ -1 at back peak)

    def _swing_seat_state():
        try:
            st = engine_mod.swing_world_state(
                int(swing_t0_ms),
                theta_amp_override=swing_ride_theta_amp,
            )
            return st
        except Exception:
            return None

    def _swing_seat_xy():
        st = _swing_seat_state()
        if not st:
            return None
        try:
            return float(st["bx_w"]), float(st["by_w"])
        except Exception:
            return None

    def _swing_seat_height():
        st = _swing_seat_state()
        if not st:
            return 0.0
        try:
            return float(st.get("b_h", 0.0) or 0.0)
        except Exception:
            return 0.0

    def _is_primary_action_key(key):
        return key in (pygame.K_a, pygame.K_SPACE, pygame.K_RETURN)

    def _swing_ride_on_primary_press():
        """ride 중 A/Space/Enter/좌클릭 동일: 점프 홀드 시작 또는 펌프."""
        nonlocal swing_jump_hold_active, swing_jump_hold_started_ms, swing_jump_hold_press_ratio
        if swing_ride_mode != "ride":
            return False
        if bool(swing_jump_ready) and (not swing_jump_hold_active):
            stx = _swing_seat_state()
            if stx is not None:
                try:
                    dn = float(stx.get("depth_n", 0.0) or 0.0)
                    dpk = float(stx.get("depth_peak_n", 0.0) or 0.0)
                except Exception:
                    dn, dpk = 0.0, 0.0
                if float(dpk) > 1e-6:
                    swing_jump_hold_active = True
                    swing_jump_hold_started_ms = int(pygame.time.get_ticks())
                    swing_jump_hold_press_ratio = float(dn) / float(dpk)
                    return True
        try:
            swing_ride_pump_times.append(float(pygame.time.get_ticks()) / 1000.0)
        except Exception:
            pass
        return True

    # 디버그: 0 키로 플레이어 캐릭터 순환 (CHAR_ASSETS 등록 순서)
    player_cycle_names = [k for k in (CHAR_ASSETS or {}).keys()]
    try:
        player_cycle_names.sort()
    except Exception:
        pass

    def cycle_player_character():
        nonlocal player
        if not player_cycle_names:
            return
        cur = str(getattr(player, "name", "") or "")
        try:
            idx = player_cycle_names.index(cur)
        except Exception:
            idx = -1
        nxt = player_cycle_names[(idx + 1) % len(player_cycle_names)]
        old = player
        try:
            new_player = Player(nxt, [float(old.pos[0]), float(old.pos[1])], {})
        except Exception:
            return
        try:
            new_player.jump_pad_zones = getattr(old, "jump_pad_zones", []) or []
        except Exception:
            pass
        try:
            new_player.is_visible = getattr(old, "is_visible", True)
        except Exception:
            pass
        try:
            new_player.alpha = getattr(old, "alpha", 255)
        except Exception:
            pass
        try:
            new_player.held_item = getattr(old, "held_item", None)
        except Exception:
            pass
        player = new_player
        print(f"[DEBUG] player cycled: {cur or '?'} -> {nxt}")
        try:
            cam.snap_to(player.pos)
        except Exception:
            pass

    running = True
    # 메모리 워치독: 변환 캐시(스케일/틸트/쉬어) 주기 정리로 RSS 누적 완화
    mem_watch_enabled = bool(CONFIG.get("MEM_WATCHDOG_ENABLED", True))
    try:
        mem_watch_interval = float(CONFIG.get("MEM_WATCHDOG_INTERVAL_SEC", 2.0))
    except Exception:
        mem_watch_interval = 2.0
    mem_watch_interval = max(0.25, min(30.0, mem_watch_interval))
    try:
        mem_watch_high_mb = float(CONFIG.get("MEM_WATCHDOG_HIGH_MB", 220.0))
    except Exception:
        mem_watch_high_mb = 220.0
    mem_watch_high_mb = max(80.0, mem_watch_high_mb)
    try:
        mem_watch_growth_mb = float(CONFIG.get("MEM_WATCHDOG_GROWTH_MB", 40.0))
    except Exception:
        mem_watch_growth_mb = 40.0
    mem_watch_growth_mb = max(5.0, mem_watch_growth_mb)
    try:
        mem_watch_growth_trigger = bool(CONFIG.get("MEM_WATCHDOG_GROWTH_TRIGGER_ENABLED", True))
    except Exception:
        mem_watch_growth_trigger = True
    try:
        mem_watch_soft_growth = bool(CONFIG.get("MEM_WATCHDOG_SOFT_GROWTH_TRIM", True))
    except Exception:
        mem_watch_soft_growth = True
    try:
        mem_watch_growth_trim_frac = float(CONFIG.get("MEM_WATCHDOG_GROWTH_TRIM_FRACTION", 0.35))
    except Exception:
        mem_watch_growth_trim_frac = 0.35
    mem_watch_growth_trim_frac = max(0.05, min(0.95, mem_watch_growth_trim_frac))
    try:
        mem_watch_gc_full = bool(CONFIG.get("MEM_WATCHDOG_GC_AFTER_FULL_CLEAR", True))
    except Exception:
        mem_watch_gc_full = True
    mem_watch_last_t = time.time()
    mem_watch_base_rss = None

    # PERF profiler: rg35xxsp에서 병목 구간 확인용(기본 off)
    perf_enabled = bool(CONFIG.get("PERF_PROFILER_ENABLED", False))
    try:
        perf_print_every = int(CONFIG.get("PERF_PROFILER_PRINT_EVERY", 120) or 120)
    except Exception:
        perf_print_every = 120
    perf_print_every = max(30, min(600, perf_print_every))
    try:
        perf_detail = bool(CONFIG.get("PERF_PROFILER_DETAIL", True))
    except Exception:
        perf_detail = True
    perf_detail = bool(perf_detail and perf_enabled)
    perf_buf = {
        "frame": [],
        "dt_real_ms": [],
        "fps_pace_ms": [],
        "event": [],
        "shear_smooth": [],
        "obj_update": [],
        "cam_update": [],
        "render_cpu": [],
        "bg": [],
        "obj_draw": [],
        "mask": [],
        "cloud": [],
        "effects": [],
        "overlay": [],
        "ui": [],
        "flip": [],
        "world_zoom": [],
        "present": [],
        # --- PERF_PROFILER_DETAIL: render_cpu 내부 세분화 ---
        "bg_zones": [],
        "obj_pool_sort": [],
        "wz_scale": [],
        "wz_blit": [],
        "world_tail": [],
        "overlay_build": [],
    }
    perf_frame_i = 0
    perf_last_dump = 0
    if perf_enabled and bool(CONFIG.get("PERF_PROFILE_LOG_ENABLED", True)):
        perf_profile_log("=== perf session start (PERF_PROFILER_ENABLED) ===")
        try:
            perf_profile_log(
                "boot_ctx "
                f"W={CONFIG.get('WIDTH')} H={CONFIG.get('HEIGHT')} "
                f"OUTPUT_MODE={CONFIG.get('OUTPUT_MODE')} UPSCALE_FACTOR={CONFIG.get('UPSCALE_FACTOR')} "
                f"WORLD_ZOOM_ENABLED={CONFIG.get('WORLD_ZOOM_ENABLED')} "
                f"WORLD_ZOOM_DRAW≈{CONFIG.get('WORLD_ZOOM_DEFAULT')} "
                f"BG_VIEWPORT_BLIT_ENABLED={CONFIG.get('BG_VIEWPORT_BLIT_ENABLED')}"
            )
        except Exception:
            perf_profile_log("boot_ctx (failed to stringify CONFIG)")

    # 오버레이(텍스트) 업데이트 주기(초): 1초에 1번만 문자열/폰트 렌더/RSS 조회
    try:
        overlay_update_interval = float(CONFIG.get("OVERLAY_UPDATE_INTERVAL_SEC", 1.0))
    except Exception:
        overlay_update_interval = 1.0
    overlay_update_interval = max(0.2, min(5.0, overlay_update_interval))
    overlay_last_update_t = 0.0
    overlay_cache = {
        "debug_text": "",
        "debug_surf": None,
        "perf_text": "",
        "perf_surf": None,
        "bgm_text": "",
        "bgm_surf": None,
        "rss_mb": None,
        "rss_text": "",
        "rss_surf": None,
        "zone_labels": {},  # event_id -> Surface (rarely changes)
        "cache_text": "",
        "cache_surf": None,
    }

    def _pnow():
        return time.perf_counter()

    def _padd(name, dt_s):
        try:
            perf_buf[name].append(float(dt_s) * 1000.0)
        except Exception:
            pass

    def _pdump():
        keys = (
            "frame",
            "dt_real_ms",
            "fps_pace_ms",
            "event",
            "shear_smooth",
            "obj_update",
            "cam_update",
            "render_cpu",
            "bg",
            "bg_zones",
            "obj_pool_sort",
            "obj_draw",
            "mask",
            "cloud",
            "effects",
            "overlay",
            "overlay_build",
            "world_zoom",
            "wz_scale",
            "wz_blit",
            "world_tail",
            "ui",
            "flip",
            "present",
        )
        parts = []
        for k in keys:
            arr = perf_buf.get(k) or []
            if not arr:
                continue
            try:
                ms = statistics.median(arr)
            except Exception:
                ms = arr[-1]
            parts.append(f"{k}:{ms:.2f}ms")
            arr.clear()
        msg = " | ".join(parts)
        if msg:
            print("[PERF] " + msg)
            log_line("[PERF] " + msg)
            perf_profile_log("[PERF] " + msg)

    # Cache stats (Surface caches that can drive RSS)
    cache_stats_enabled = bool(CONFIG.get("CACHE_STATS_ENABLED", False))
    cache_stats_log = bool(CONFIG.get("CACHE_STATS_LOG", False))

    def _surf_est_mb(surf):
        try:
            w, h = surf.get_size()
        except Exception:
            return 0.0
        # assume 32bpp worst case (safe upper bound)
        return (float(w) * float(h) * 4.0) / (1024.0 * 1024.0)

    def _cache_est_mb(d):
        try:
            it = list(d.values())
        except Exception:
            return 0.0
        total = 0.0
        for v in it:
            try:
                total += _surf_est_mb(v)
            except Exception:
                pass
        return total

    # Draw TopN profiler (sampled): find expensive object draw types
    draw_topn_enabled = bool(CONFIG.get("DRAW_TOPN_ENABLED", False))
    try:
        draw_topn_sample_every = int(CONFIG.get("DRAW_TOPN_SAMPLE_EVERY", 20) or 20)
    except Exception:
        draw_topn_sample_every = 20
    draw_topn_sample_every = max(1, min(120, draw_topn_sample_every))
    try:
        draw_topn_max_items = int(CONFIG.get("DRAW_TOPN_MAX_ITEMS", 80) or 80)
    except Exception:
        draw_topn_max_items = 80
    draw_topn_max_items = max(10, min(500, draw_topn_max_items))
    draw_topn_acc = {}  # key -> [ms_total, count]
    draw_topn_last_dump_t = 0.0
    try:
        draw_topn_dump_every = float(CONFIG.get("DRAW_TOPN_DUMP_EVERY_SEC", 2.0))
    except Exception:
        draw_topn_dump_every = 2.0
    draw_topn_dump_every = max(0.5, min(10.0, draw_topn_dump_every))

    def _draw_key(ent):
        cls = ent.__class__.__name__
        if isinstance(ent, FieldItem):
            try:
                nm = str(getattr(ent, "name", "") or "")
            except Exception:
                nm = ""
            try:
                oid = str(getattr(ent, "obj_id", "") or "")
            except Exception:
                oid = ""
            tag = nm or oid
            return f"{cls}:{tag}" if tag else cls
        return cls

    def _clear_transform_caches(*, run_gc: bool = True):
        nonlocal tilt_bg_tmp, shear_bg_tmp, tilt_mask_tmp, shear_mask_tmp, vp_bg_scale_tmp
        try:
            _render_cache.clear()
        except Exception:
            pass
        try:
            # mb counter reset
            nonlocal _render_cache_mb
            _render_cache_mb = 0.0
        except Exception:
            pass
        try:
            if hasattr(cam, "image_cache") and isinstance(cam.image_cache, dict):
                cam.image_cache.clear()
        except Exception:
            pass
        try:
            if hasattr(cloud_fx, "_render_cache") and isinstance(cloud_fx._render_cache, dict):
                cloud_fx._render_cache.clear()
        except Exception:
            pass
        # 큰 임시 surface들도 한번씩 내려놓기(다음 프레임에 필요 시 재생성)
        tilt_bg_tmp = None
        shear_bg_tmp = None
        tilt_mask_tmp = None
        shear_mask_tmp = None
        vp_bg_scale_tmp = None
        if run_gc:
            try:
                gc.collect()
            except Exception:
                pass

    _fixed_ts_enabled = bool(CONFIG.get("FIXED_TIMESTEP_ENABLED", True))
    try:
        _hz_cfg = CONFIG.get("FIXED_TIMESTEP_HZ", None)
        _fixed_ts_hz = float(CONFIG["FPS"] if _hz_cfg is None else _hz_cfg)
    except Exception:
        _fixed_ts_hz = 60.0
    _fixed_ts_hz = max(10.0, min(240.0, _fixed_ts_hz))
    fixed_step_ms = 1000.0 / _fixed_ts_hz
    try:
        fixed_ts_max_steps = int(CONFIG.get("FIXED_TIMESTEP_MAX_STEPS", 12))
    except Exception:
        fixed_ts_max_steps = 12
    fixed_ts_max_steps = max(1, min(64, fixed_ts_max_steps))
    try:
        fixed_max_frame_ms = float(CONFIG.get("FIXED_TIMESTEP_MAX_FRAME_MS", 250.0))
    except Exception:
        fixed_max_frame_ms = 250.0
    fixed_max_frame_ms = max(fixed_step_ms, min(500.0, fixed_max_frame_ms))
    fixed_ts_acc = 0.0
    if _fixed_ts_enabled:
        try:
            clock.tick(0)
        except Exception:
            pass

    # dynamic FPS cap (render only)
    dyn_fps_on = bool(CONFIG.get("DYNAMIC_FPS_ENABLED", False))
    try:
        fps_idle = int(CONFIG.get("FPS_IDLE", CONFIG.get("FPS", 30)) or 30)
    except Exception:
        fps_idle = int(CONFIG.get("FPS", 30) or 30)
    try:
        fps_fx = int(CONFIG.get("FPS_EFFECTS", max(10, fps_idle - 6)) or max(10, fps_idle - 6))
    except Exception:
        fps_fx = max(10, fps_idle - 6)
    fps_idle = max(10, min(120, fps_idle))
    fps_fx = max(10, min(120, fps_fx))
    fps_cap = int(fps_idle)

    while running:
        # frame counter for sampling (works even if perf profiler is off)
        try:
            loop_i += 1
        except NameError:
            loop_i = 1
        t_frame0 = _pnow() if perf_enabled else None
        t0 = _pnow() if perf_enabled else None
        if _fixed_ts_enabled:
            # fixed timestep에서는 tick()을 딱 1번만 호출해야 누적(acc)과 sim_steps가 안정적이다.
            # 여기서 FPS 캡(예: 30)까지 같이 걸어 렌더 프레임을 제한한다.
            dt_real_ms = float(clock.tick(int(fps_cap)))
            if dt_real_ms <= 0.0:
                dt_real_ms = fixed_step_ms
            dt_real_ms = min(dt_real_ms, fixed_max_frame_ms)
            fixed_ts_acc += dt_real_ms
            sim_steps = 0
            while fixed_ts_acc >= fixed_step_ms - 1e-9 and sim_steps < fixed_ts_max_steps:
                fixed_ts_acc -= fixed_step_ms
                sim_steps += 1
            dt = int(round(dt_real_ms))
            dt_sim_ms = fixed_step_ms
            dt_sec = (float(sim_steps) * float(dt_sim_ms)) / 1000.0
            if dt_sec <= 0.0:
                dt_sec = dt_real_ms / 1000.0
        else:
            dt = clock.tick(int(fps_cap))
            dt_real_ms = float(dt)
            sim_steps = 1
            dt_sim_ms = dt_real_ms
            dt_sec = float(dt) / 1000.0
        if perf_enabled and t0 is not None:
            # pygame.time.Clock.tick: FPS 캡까지 대기 + "지난 프레임 실제 경과(ms)" 반환. 대기 시간이 크게 잡힐 수 있음.
            _padd("fps_pace_ms", _pnow() - t0)
        if perf_enabled:
            # clock.tick() 반환값(밀리초)을 그대로 기록(프레임이 느려졌는지 판단용)
            try:
                _padd("dt_real_ms", float(dt_real_ms) / 1000.0)
            except Exception:
                pass
        global_anim_timer = pygame.time.get_ticks() // 100
        music_mgr.update()

        if mem_watch_enabled:
            now = time.time()
            if now - mem_watch_last_t >= mem_watch_interval:
                mem_watch_last_t = now
                cur = rss_mb()
                if cur is not None:
                    if mem_watch_base_rss is None:
                        mem_watch_base_rss = float(cur)
                    grow = float(cur) - float(mem_watch_base_rss)
                    skip_growth_clear = False
                    try:
                        if bool(CONFIG.get("MEM_WATCHDOG_SKIP_GROWTH_WHEN_FX_FPS", False)):
                            try:
                                eff_fx = int(CONFIG.get("FPS_EFFECTS", 15) or 15)
                            except Exception:
                                eff_fx = 15
                            eff_fx = max(1, min(120, eff_fx))
                            try:
                                skip_growth_clear = int(fps_cap) <= eff_fx
                            except Exception:
                                skip_growth_clear = False
                    except Exception:
                        skip_growth_clear = False
                    abs_high = float(cur) >= mem_watch_high_mb
                    growth_hit = (
                        mem_watch_growth_trigger
                        and grow >= mem_watch_growth_mb
                        and (not skip_growth_clear)
                    )
                    if abs_high:
                        _clear_transform_caches(run_gc=mem_watch_gc_full)
                        cur2 = rss_mb()
                        mem_watch_base_rss = float(cur2) if cur2 is not None else None
                    elif growth_hit:
                        if mem_watch_soft_growth and _render_cache_mb > 1e-6:
                            _render_cache_lru_free_target_mb(
                                float(_render_cache_mb) * float(mem_watch_growth_trim_frac)
                            )
                        else:
                            _clear_transform_caches(run_gc=mem_watch_gc_full)
                        cur2 = rss_mb()
                        mem_watch_base_rss = float(cur2) if cur2 is not None else None

        # Fixed timestep: render FPS can be low, but simulation runs in stable steps.
        # We update dt_sec per sim step so movement/animation stays consistent at 30fps render.
        step_ms = float(dt_sim_ms)
        step_sec = step_ms / 1000.0
        if sim_steps < 1:
            sim_steps = 1

        for _si in range(int(sim_steps)):
            dt_sec = step_sec

        # --- 틸트/쉬어 보간(부드럽게 수렴) ---
        # 정책: 감속(ease-out) 없음.
        # 예전에는 목표 근처에서 END_SPEED로 속도를 낮춰 "마무리만 천천히" 했는데,
        # 화면상 거의 끝난 상태가 오래 지속되며(특히 저사양에서) 성능/체감 복귀가 늦어져 제거했다.
        # 이제 SPEED 하나로 끝까지 일정한 속도로 수렴한다. (스냅 임계값은 *_EPS)

        # 배경 압축(틸트) 값도 zoom처럼 부드럽게 수렴 (게임 진행은 계속)
        try:
            tilt_speed = float(CONFIG.get("TILT_BG_SPEED", 0.12))
        except Exception:
            tilt_speed = 0.12
        tilt_speed = max(0.0, min(1.0, tilt_speed))
        _tilt_ctrl = getattr(ev_mgr, "tilt_control", None)
        if isinstance(_tilt_ctrl, dict) and _tilt_ctrl.get("speed") is not None:
            try:
                tilt_speed = float(_tilt_ctrl.get("speed"))
            except (TypeError, ValueError):
                pass
            tilt_speed = max(0.0, min(1.0, tilt_speed))
        try:
            tilt_eps = float(CONFIG.get("TILT_BG_EPS", 0.002))
        except Exception:
            tilt_eps = 0.002
        try:
            tilt_factor_min = float(CONFIG.get("TILT_FACTOR_MIN", 0.2))
        except Exception:
            tilt_factor_min = 0.2
        tilt_factor_min = max(0.02, min(0.99, tilt_factor_min))

        pr = getattr(ev_mgr, "pending_field_tilt_restore", None)
        if pr is not None:
            try:
                if len(pr) >= 4:
                    td, tt, tc, sd = pr[0], pr[1], pr[2], pr[3]
                    ui.shear_debug_on = bool(sd)
                else:
                    td, tt, tc = pr[0], pr[1], pr[2]
                ui.tilt_bg_demo = bool(td)
                ui.tilt_target = float(tt)
                tilt_current = float(tc)
            except Exception:
                pass
            ev_mgr.pending_field_tilt_restore = None

        if isinstance(getattr(ev_mgr, "tilt_control", None), dict):
            tc = ev_mgr.tilt_control
            try:
                ui.tilt_target = float(tc.get("target", 1.0))
            except (TypeError, ValueError):
                ui.tilt_target = 1.0
            ui.tilt_target = max(tilt_factor_min, min(1.0, ui.tilt_target))
            if tc.get("instant_once"):
                tilt_current = ui.tilt_target
                tc["instant_once"] = False

        _tilt_tc = getattr(ev_mgr, "tilt_control", None)
        if isinstance(_tilt_tc, dict) and _tilt_tc.get("duration_sec") is not None:
            try:
                _tilt_dur = float(_tilt_tc.get("duration_sec"))
            except (TypeError, ValueError):
                _tilt_dur = None
            if _tilt_dur is not None and _tilt_dur > 0.0 and "start" not in _tilt_tc:
                timed_effect_init(
                    _tilt_tc,
                    float(tilt_current),
                    float(ui.tilt_target),
                    _tilt_dur,
                    now_ms=_tilt_tc.get("t0_ms"),
                )
            if _tilt_dur is not None and _tilt_dur > 0.0:
                tilt_current = timed_effect_value(_tilt_tc, float(tilt_current))
            elif abs(ui.tilt_target - tilt_current) <= tilt_eps:
                tilt_current = ui.tilt_target
            else:
                tilt_current = float(ui.tilt_target)
        elif abs(ui.tilt_target - tilt_current) <= tilt_eps:
            tilt_current = ui.tilt_target
        else:
            k = max(1e-6, float(step_ms) / 16.666)
            alpha = 1.0 - pow(max(0.0, 1.0 - float(tilt_speed)), k)
            tilt_current = float(tilt_current) + (float(ui.tilt_target) - float(tilt_current)) * alpha
        
        # --- 1. 카메라 및 매니저 업데이트 ---
        bg_w, bg_h = bg.get_size()
        t0 = _pnow() if perf_enabled else None
        ev_mgr.update(player, cam, objs, npcs, mask_img=mask, dt_sec=dt_sec)
        if perf_enabled and t0 is not None:
            _padd("event", _pnow() - t0)
        pc = getattr(ev_mgr, "pending_camera_command", None)
        if pc:
            ev_mgr.pending_camera_command = None
            apply_pending_camera_command(cam, pc, player=player, npcs=npcs, objs=objs)

        # --- 새 월드 줌(후처리) 업데이트 ---
        # 이벤트 ZOOM(camera) / 디버그 핫키가 ev_mgr.pending_world_zoom으로 목표를 요청한다.
        pz = getattr(ev_mgr, "pending_world_zoom", None)
        if pz is not None:
            if isinstance(pz, dict):
                try:
                    world_zoom_target = float(pz.get("val", pz.get("target", 1.0)))
                except (TypeError, ValueError):
                    pass
            else:
                try:
                    world_zoom_target = float(pz)
                except Exception:
                    pass
            world_zoom_target = max(
                world_zoom_min, min(world_zoom_max, float(world_zoom_target))
            )
            # AUTO_OUTPUT_MODE: world_zoom은 항상 640 기준(1.0=기본, 2.0=2배).
            # 2.0 미만으로 가려면 320(UPSCALE) 상태에서 먼저 640으로 올린 뒤 보간한다.
            if (
                auto_res_enabled
                and output_mode == "UPSCALE_320"
                and float(auto_res_zoom_mul) > 1.0
                and float(world_zoom_target) < float(auto_zoom_in_trigger) - 1e-6
            ):
                _auto_res_to_native640()
            if isinstance(pz, dict):
                if pz.get("instant"):
                    world_zoom_current = float(world_zoom_target)
                    ev_mgr.world_zoom_timed = None
                    if (
                        auto_res_enabled
                        and float(world_zoom_target) < float(auto_zoom_in_trigger) - 1e-6
                    ):
                        _auto_res_to_native640()
                else:
                    try:
                        wz_d = float(pz.get("duration_sec", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        wz_d = 0.0
                    if wz_d > 0.0:
                        wzt = {}
                        timed_effect_init(
                            wzt,
                            float(world_zoom_current),
                            float(world_zoom_target),
                            wz_d,
                            now_ms=pz.get("t0_ms"),
                        )
                        ev_mgr.world_zoom_timed = wzt
                    else:
                        world_zoom_current = float(world_zoom_target)
                        ev_mgr.world_zoom_timed = None
                wz_sp = pz.get("speed")
                if wz_sp is not None:
                    try:
                        ev_mgr.world_zoom_step_speed = float(wz_sp)
                        ev_mgr.world_zoom_timed = None
                    except (TypeError, ValueError):
                        pass
            try:
                ev_mgr.pending_world_zoom = None
            except Exception:
                pass
        world_zoom_target = max(world_zoom_min, min(world_zoom_max, float(world_zoom_target)))

        # 보간 중에도 2.0 미만 목표면 640 선전환 (320+줌치환 상태에서 draw만 줄이면 깨짐)
        if (
            auto_res_enabled
            and output_mode == "UPSCALE_320"
            and float(auto_res_zoom_mul) > 1.0
            and float(world_zoom_target) < float(auto_zoom_in_trigger) - 1e-6
        ):
            _auto_res_to_native640()

        if not world_zoom_enabled:
            world_zoom_current = 1.0
            world_zoom_target = 1.0
        else:
            _wz_timed = getattr(ev_mgr, "world_zoom_timed", None)
            if isinstance(_wz_timed, dict) and getattr(ev_mgr, "world_zoom_step_speed", None) is None:
                world_zoom_current = timed_effect_value(_wz_timed, float(world_zoom_current))
                if timed_effect_finished(_wz_timed):
                    world_zoom_current = float(_wz_timed.get("target", world_zoom_target))
                    ev_mgr.world_zoom_timed = None
            else:
                dz = float(world_zoom_target) - float(world_zoom_current)
                if abs(dz) <= 1e-6:
                    world_zoom_current = float(world_zoom_target)
                else:
                    try:
                        _wz_step_spd = getattr(ev_mgr, "world_zoom_step_speed", None)
                        _wz_spd_use = (
                            float(_wz_step_spd)
                            if _wz_step_spd is not None
                            else float(world_zoom_speed)
                        )
                    except (TypeError, ValueError):
                        _wz_spd_use = float(world_zoom_speed)
                    _wz_spd_use = max(0.05, min(20.0, _wz_spd_use))
                    step = _wz_spd_use * max(0.0, float(dt_sec))
                    if abs(dz) <= step:
                        world_zoom_current = float(world_zoom_target)
                    else:
                        world_zoom_current = float(world_zoom_current) + (
                            step if dz > 0 else -step
                        )

        # 입력 역변환/합성: 640 기준 world_zoom → 실제 draw 배율
        world_zoom_draw = (
            native_world_zoom_draw(
                float(world_zoom_current) if world_zoom_enabled else 1.0,
                output_mode,
                auto_res_zoom_mul,
            )
            if world_zoom_enabled
            else 1.0
        )
        try:
            lw_i = int(CONFIG["WIDTH"])
            lh_i = int(CONFIG["HEIGHT"])
        except Exception:
            lw_i, lh_i = 320, 240
        # 후처리 줌 앵커: draw 단계에서 cam_draw+쉬어 기준으로 다시 잡는다(아래는 초기 추정).
        try:
            fwx, fwy = cam.get_focus_world_point(player, npcs, objs)
            ax, ay = cam.to_screen(float(fwx), float(fwy))
        except Exception:
            ax, ay = float(lw_i) * 0.5, float(lh_i) * 0.5
        try:
            ax = float(ax)
            ay = float(ay)
        except Exception:
            ax, ay = float(lw_i) * 0.5, float(lh_i) * 0.5
        world_zoom_off_x = ax * (1.0 - float(world_zoom_draw))
        world_zoom_off_y = ay * (1.0 - float(world_zoom_draw))
        # --- 자동 가변 해상도 전환 (640 기준 world_zoom) ---
        # zoom=2.0 완료 → 320 출력(UPSCALE_320, mul=2, draw=1.0)
        # zoom=1.0 완료 → 640 출력(NATIVE_640)
        if auto_res_enabled:
            now_ms = pygame.time.get_ticks()
            can_switch = (now_ms - int(last_auto_switch_ms)) >= int(auto_switch_cooldown_ms)
            zoom_done = abs(float(world_zoom_current) - float(world_zoom_target)) <= 1e-6
            if can_switch and zoom_done:
                zc = float(world_zoom_current)
                if output_mode == "NATIVE_640" and abs(zc - float(auto_zoom_in_trigger)) <= 1e-6:
                    prev_sf = float(scale_factor)
                    _apply_output_mode(mode="UPSCALE_320", fullscreen=fullscreen_on)
                    _after_resolution_change(prev_scale_factor=prev_sf)
                    try:
                        _auto_res_compensate_follow_offset(cam, prev_sf, float(scale_factor))
                        _preserve_cam_world_center(cam, bg_w, bg_h)
                        auto_res_hold_cam_pos = (float(cam.pos[0]), float(cam.pos[1]))
                    except Exception:
                        pass
                    auto_res_zoom_mul = 2.0
                    world_zoom_current = float(auto_zoom_in_trigger)
                    world_zoom_target = float(auto_zoom_in_trigger)
                    ev_mgr.world_zoom_timed = None
                    world_zoom_draw = native_world_zoom_draw(
                        world_zoom_current, output_mode, auto_res_zoom_mul
                    )
                    last_auto_switch_ms = int(now_ms)
                elif (
                    output_mode == "UPSCALE_320"
                    and float(auto_res_zoom_mul) > 1.0
                    and abs(zc - float(auto_zoom_out_trigger)) <= 1e-6
                ):
                    _auto_res_to_native640()
                    world_zoom_current = float(auto_zoom_out_trigger)
                    world_zoom_target = float(auto_zoom_out_trigger)
                    ev_mgr.world_zoom_timed = None
                    world_zoom_draw = 1.0
                    world_zoom_off_x = 0.0
                    world_zoom_off_y = 0.0
        # 쉬어 "줌에 맞춤" 보정:
        # - 카메라 줌(cam.current_zoom)은 여기선 보통 1로 고정
        # - AUTO_OUTPUT_MODE(640->320 업스케일)에서는 "줌 2x"를 해상도 치환(auto_res_zoom_mul)로 표현하므로
        #   쉬어(각도/보정)도 체감 줌 기준으로 동작해야 전환 순간에 플레이어 중앙 보정이 튀지 않는다.
        try:
            world_z_for_shear = float(world_zoom_draw) if world_zoom_enabled else float(cam.current_zoom)
        except Exception:
            world_z_for_shear = 1.0
        try:
            if auto_res_enabled and output_mode == "UPSCALE_320" and float(auto_res_zoom_mul) > 1.0:
                world_z_for_shear = float(world_z_for_shear) * float(auto_res_zoom_mul)
        except Exception:
            pass
        world_z_for_shear = max(1e-6, float(world_z_for_shear))

        # 쉬어: 목표 픽셀(tilt_shear_effective)에 틸트·줌처럼 dt 보정 보간
        t0 = _pnow() if perf_enabled else None
        try:
            shear_speed = float(
                CONFIG.get("SHEAR_SMOOTH_SPEED", CONFIG.get("TILT_BG_SPEED", 0.12))
            )
        except Exception:
            shear_speed = 0.12
        shear_speed = max(0.0, min(1.0, shear_speed))
        _shear_ctrl = getattr(ev_mgr, "shear_control", None)
        if isinstance(_shear_ctrl, dict) and _shear_ctrl.get("speed") is not None:
            try:
                shear_speed = float(_shear_ctrl.get("speed"))
            except (TypeError, ValueError):
                pass
            shear_speed = max(0.0, min(1.0, shear_speed))
        try:
            shear_eps = float(CONFIG.get("SHEAR_SMOOTH_EPS", 0.06))
        except Exception:
            shear_eps = 0.06
        shear_goal = float(tilt_shear_effective(ev_mgr, tilt_current, ui.shear_debug_on))
        if isinstance(_shear_ctrl, dict) and _shear_ctrl.get("instant_once"):
            shear_smoothed = shear_goal
            _shear_ctrl["instant_once"] = False
        if isinstance(_shear_ctrl, dict) and _shear_ctrl.get("duration_sec") is not None:
            try:
                _shear_dur = float(_shear_ctrl.get("duration_sec"))
            except (TypeError, ValueError):
                _shear_dur = None
            if _shear_dur is not None and _shear_dur > 0.0:
                if "start" not in _shear_ctrl:
                    if "_goal_at_start" not in _shear_ctrl:
                        _shear_ctrl["_goal_at_start"] = float(shear_goal)
                    timed_effect_init(
                        _shear_ctrl,
                        float(shear_smoothed),
                        float(_shear_ctrl["_goal_at_start"]),
                        _shear_dur,
                        now_ms=_shear_ctrl.get("t0_ms"),
                    )
                shear_smoothed = timed_effect_value(_shear_ctrl, float(shear_smoothed))
            elif abs(shear_goal - shear_smoothed) <= shear_eps:
                shear_smoothed = shear_goal
            else:
                shear_smoothed = shear_goal
        elif abs(shear_goal - shear_smoothed) <= shear_eps:
            shear_smoothed = shear_goal
        else:
            k_sh = max(1e-6, float(step_ms) / 16.666)
            alpha_sh = 1.0 - pow(max(0.0, 1.0 - float(shear_speed)), k_sh)
            shear_smoothed = float(shear_smoothed) + (shear_goal - float(shear_smoothed)) * alpha_sh
        if perf_enabled and t0 is not None:
            _padd("shear_smooth", _pnow() - t0)

        if sim_steps > 1 and _si < int(sim_steps) - 1:
            # 다음 시뮬 스텝 전에 입력/렌더 관련 코드로 넘어가지 않도록(렌더는 루프 밖에서 1번)
            continue

        # [추가] 맵 이동 요청 처리 (이벤트 도중 MAP 스텝 발생 시)
        if ev_mgr.pending_map_change:
            target_map = ev_mgr.pending_map_change["map_id"]
            target_pos = ev_mgr.pending_map_change["pos"]
            ev_mgr.pending_map_change = None
            
            # 실제 맵 전환 처리
            # target_pos가 None이면 flow.load_map 내부에서 세이브 파일 정보를 활용함
            map_id, bg, mask, player, objs, npcs = flow.load_map(save_data={"current_map": target_map, "player_pos": target_pos})
            cam.snap_to(player.pos)
            cam.set_follow_player(smooth=False)
            print(f"[Map Transition] Moved to {target_map} at {player.pos}")
            # bg_zones 캐시도 맵 단위로 재빌드
            try:
                _rebuild_bg_zone_cache()
            except Exception:
                pass
            # 이벤트 도중 맵이 바뀌면, catalog도 새로 갱신해주는 게 안전
            _reload_event_bundles()
            _queue_sync_for_map(map_id)

        # --- 2. 입력 처리 ---
        # 렌더링과 동일한 "픽셀 그리드 정렬" 카메라 원점을 써야 클릭/블릿이 1px 어긋나지 않음.
        # cam.update 전이라도 정수 줌 스냅은 동일 규칙 적용(RENDER_INTEGER_ZOOM_EPS).
        z_in = snap_render_zoom(float(cam.current_zoom))
        z_in = max(1e-6, z_in)
        cam_origin_x_in = float(cam.pos[0]) - float(cam.width) / z_in / 2.0
        cam_origin_y_in = float(cam.pos[1]) - float(cam.height) / z_in / 2.0
        cam_origin_x_in = round(cam_origin_x_in * z_in) / z_in
        cam_origin_y_in = round(cam_origin_y_in * z_in) / z_in
        bg_dx_in = int(round((0.0 - float(cam_origin_x_in)) * z_in))
        bg_dy_in = int(round((0.0 - float(cam_origin_y_in)) * z_in))
        cam_draw_x_in = -float(bg_dx_in) / z_in
        cam_draw_y_in = -float(bg_dy_in) / z_in
        # 렌더링과 동일하게: 줌이 커지면 쉬어(px)도 같이 커져야 각도가 유지됨
        shear_render_in = float(shear_smoothed)
        try:
            if bool(CONFIG.get("SHEAR_SCALE_WITH_ZOOM", False)):
                zref = float(CONFIG.get("SHEAR_ZOOM_REF", 1.0) or 1.0)
                zp = float(CONFIG.get("SHEAR_ZOOM_POWER", 1.0) or 1.0)
                zref = max(1e-6, zref)
                scale = pow(float(world_z_for_shear) / zref, zp)
                shear_render_in *= float(scale)
                smax = float(CONFIG.get("SHEAR_RENDER_PX_MAX", 512) or 512)
                shear_render_in = max(0.0, min(float(smax), float(shear_render_in)))
        except Exception:
            pass
        # contact_confirm: 이번 프레임 맵 상호작용 점 1개 (좌클릭 월드좌표 또는 A/Space/Enter→커서 월드좌표)
        zone_confirm_click_world = None
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if not ev_mgr.active_event and bool(getattr(ev_mgr, "is_talking", False)):
                if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                    try:
                        ev_mgr.advance_dialog()
                    except Exception:
                        pass
                if event.type != pygame.QUIT:
                    continue

            if ev_mgr.active_event:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if ev_mgr.try_escape_click(event.button):
                        player.stop_moving()
                        for n in npcs:
                            sm = getattr(n, "stop_moving", None)
                            if callable(sm):
                                sm()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_d:
                        apply_dev_runtime_command(
                            "restart_delete_save",
                            ev_mgr=ev_mgr,
                            cam=cam,
                            flow=flow,
                            map_id=map_id,
                            player=player,
                        )

                    # --- Request 3: A button == left click (also for event escape click-mode) ---
                    if event.key in (pygame.K_a, pygame.K_SPACE, pygame.K_RETURN):
                        if ev_mgr.try_escape_click(1):
                            player.stop_moving()
                            for n in npcs:
                                sm = getattr(n, "stop_moving", None)
                                if callable(sm):
                                    sm()
                    # 원터치 입력 정책: 이벤트 스탑/탈출은 클릭(및 A/Space/Enter를 클릭 취급)만 사용.
                    # (try_escape_key는 디버그 외 입력을 늘려버리므로 사용하지 않음)
                if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                    # 대사/스크린은 클릭(또는 키)로 넘길 수 있게 (탈출이 먼저 처리됨)
                    if ev_mgr.active_event and (
                        ev_mgr.is_talking
                        or ev_mgr.active_screen
                        or getattr(ev_mgr, "emote_needs_advance_input", lambda: False)()
                    ):
                        try:
                            adv = getattr(ev_mgr, "advance_dialog", None)
                            if callable(adv):
                                adv()
                            else:
                                ev_mgr.next_step()
                        except Exception:
                            ev_mgr.next_step()
                continue

            # [평상시 마우스 클릭 이동]
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # 그네 타기 중: approach/mount는 클릭 이동 막기. ride는 점프 드래그를 위해 클릭을 받는다.
                if swing_ride_mode in ("approach", "mount"):
                    continue
                mx, my = _embed_phys_to_logical_xy(event.pos[0], event.pos[1], scale_factor=scale_factor)

                # 렌더 변환 캐시 기반 역변환(틸트+줌+쉬어를 항상 렌더와 동일하게 복원)
                if render_xform_for_input:
                    ww = _screen_to_world_from_render_xform(mx, my, xf=render_xform_for_input)
                else:
                    ww = None
                if ww is not None:
                    world_x, world_y = ww
                else:
                    # 폴백: 기존 수식 기반(캐시가 아직 없는 첫 프레임 등)
                    if world_zoom_enabled:
                        try:
                            zf = float(world_zoom_draw)
                        except Exception:
                            zf = 1.0
                        zf = max(1e-6, zf)
                        try:
                            mx = (float(mx) - float(world_zoom_off_x)) / zf
                            my = (float(my) - float(world_zoom_off_y)) / zf
                        except Exception:
                            pass
                    world_x, world_y = _screen_to_world_field(
                        mx,
                        my,
                        cam=cam,
                        cam_x_start=cam_draw_x_in,
                        cam_y_start=cam_draw_y_in,
                        player=player,
                        bg_h=bg.get_height(),
                        tilt_current=tilt_current,
                        tilt_eps=tilt_eps,
                        shear_smoothed=shear_render_in,
                    )
                
                # (world_x, world_y) 확보 완료
                zone_confirm_click_world = (float(world_x), float(world_y))

                # --- 그네 타기: (옵션) 그네 클릭으로 자동 접근 + 탑승 / (ride 중) 점프 홀드/펌프 ---
                try:
                    swing_click_r = float(CONFIG.get("SWING_RIDE_INTERACT_DIST", 55.0) or 55.0)
                except Exception:
                    swing_click_r = 55.0
                swing_click_r = max(8.0, min(200.0, swing_click_r))
                seat_xy = _swing_seat_xy()
                if seat_xy is not None:
                    sx0, sy0 = float(seat_xy[0]), float(seat_xy[1])
                    try:
                        if math.hypot(float(world_x) - sx0, float(world_y) - sy0) <= float(swing_click_r):
                            # (구 방식) 클릭으로 탑승 시작은 옵션으로만 유지 (ride 중은 아래 공통 처리)
                            if swing_ride_mode != "ride" and bool(CONFIG.get("SWING_CLICK_TO_RIDE_ENABLED", False)):
                                swing_ride_mode = "approach"
                                swing_ride_power = 0.0
                                swing_ride_theta_amp = 0.0
                                swing_ride_stop_hold = 0.0
                                swing_ride_mount_end_ms = None
                                swing_ride_no_dismount_until_s = 0.0
                                swing_ride_mount_frames_left = 0
                                swing_ride_mount_start_xy = None
                                try:
                                    swing_ride_pump_times.clear()
                                except Exception:
                                    swing_ride_pump_times = deque()
                                pending_action, target_obj = None, None
                                # 자동 이동
                                try:
                                    player.set_new_target(float(sx0), float(sy0), mask, objs, npcs)
                                except Exception:
                                    try:
                                        player.handle_input([float(sx0), float(sy0)], mask, objs, npcs)
                                    except Exception:
                                        pass
                                continue
                    except Exception:
                        pass
                # ride 중 좌클릭 = A/Space/Enter (점프 홀드 또는 펌프, 좌석 근접 불필요)
                if _swing_ride_on_primary_press():
                    continue
                
                # ui_cursor는 "UI 좌표"(논리 px)를 기억한다. (UI는 월드 줌 영향을 받지 않음)
                ui_cursor[0], ui_cursor[1] = int(mx), int(my)
                
                # 보정된 world_x, world_y를 player에게 전달합니다.
                # (기본 handle_input 구조에 맞춰 target_pos로 쓰이게 수정)
                now_ms = pygame.time.get_ticks()
                try:
                    dbl_ms = int(CONFIG.get("DOUBLE_CLICK_MS", 280))
                except Exception:
                    dbl_ms = 280
                try:
                    dbl_dist = float(CONFIG.get("DOUBLE_CLICK_DIST_PX", 18.0))
                except Exception:
                    dbl_dist = 18.0
                is_double = False
                if hasattr(event, "clicks"):
                    try:
                        is_double = int(getattr(event, "clicks", 0) or 0) >= 2
                    except Exception:
                        is_double = False
                if not is_double and (now_ms - int(last_click_ms)) <= dbl_ms and last_click_world is not None:
                    try:
                        if math.hypot(float(world_x) - float(last_click_world[0]), float(world_y) - float(last_click_world[1])) <= dbl_dist:
                            is_double = True
                    except Exception:
                        pass
                last_click_ms = int(now_ms)
                last_click_world = (float(world_x), float(world_y))

                action, target = player.handle_input(
                    [world_x, world_y],
                    mask,
                    objs,
                    npcs,
                    move_mode=("run" if is_double else "walk"),
                )
                
                # [추가] 클릭 피드백 (이동 가능한 곳인지 체크)
                # 마스크 상의 색상을 확인하여 갈 수 있는 곳인지 판단
                is_walkable = False
                cx, cy = int(world_x), int(world_y)
                if 0 <= cx < mask.get_width() and 0 <= cy < mask.get_height():
                    is_walkable = mask_terrain_class(mask, world_x, world_y) == "walk"
                
                color = (0, 255, 0) if is_walkable else (255, 0, 0)
                click_feedback = {"pos": (world_x, world_y), "color": color, "start_time": pygame.time.get_ticks()}

                if action == "interact":
                    pending_action, target_obj, target_npc = "interact", target, None
                elif action == "interact_npc":
                    pending_action, target_obj, target_npc = "interact_npc", None, target
                else:
                    pending_action, target_obj, target_npc = None, None, None

            if event.type == pygame.KEYDOWN:
                # 출력 모드 토글: F5 (UPSCALE_320 ↔ NATIVE_640), 풀스크린 토글: F6
                if event.key == pygame.K_F5:
                    prev_sf = float(scale_factor)
                    new_mode = "NATIVE_640" if output_mode == "UPSCALE_320" else "UPSCALE_320"
                    _apply_output_mode(mode=new_mode, fullscreen=fullscreen_on)
                    _after_resolution_change(prev_scale_factor=prev_sf)
                if event.key == pygame.K_F6:
                    _apply_output_mode(mode=output_mode, fullscreen=(not fullscreen_on))
                    try:
                        cam.width, cam.height = int(CONFIG["WIDTH"]), int(CONFIG["HEIGHT"])
                    except Exception:
                        pass
                # 카메라 포커스(월드 중심) 디버그 점 — F 토글
                if event.key == pygame.K_f:
                    ui.show_camera_focus = not bool(getattr(ui, "show_camera_focus", False))

                if event.key in (pygame.K_0, pygame.K_KP0):
                    cycle_player_character()
                try_start_hotkey_global_event(
                    event.key,
                    ev_mgr=ev_mgr,
                    events_catalog=events_catalog,
                )

                # 그네 재시작: data.py SWING_RESTART_HOTKEY
                if event.key == _SWING_RESTART_KEY:
                    try:
                        swing_t0_ms = pygame.time.get_ticks()
                    except Exception:
                        pass

                if _is_primary_action_key(event.key):
                    if swing_ride_mode in ("approach", "mount"):
                        continue
                    if _swing_ride_on_primary_press():
                        continue

                    # --- Request 3 확장: 키 입력도 클릭과 동일하게(그네 탑승 포함) ---
                    # [추가] 키보드 입력 시에도 클릭 피드백 표시
                    mx0, my0 = float(ui_cursor[0]), float(ui_cursor[1])
                    if render_xform_for_input:
                        ww = _screen_to_world_from_render_xform(mx0, my0, xf=render_xform_for_input)
                    else:
                        ww = None
                    if ww is not None:
                        wx, wy = ww
                    else:
                        if world_zoom_enabled:
                            try:
                                zf = float(world_zoom_draw)
                            except Exception:
                                zf = 1.0
                            zf = max(1e-6, zf)
                            try:
                                mx0 = (float(mx0) - float(world_zoom_off_x)) / zf
                                my0 = (float(my0) - float(world_zoom_off_y)) / zf
                            except Exception:
                                pass
                        wx, wy = _screen_to_world_field(
                            mx0,
                            my0,
                            cam=cam,
                            cam_x_start=cam_draw_x_in,
                            cam_y_start=cam_draw_y_in,
                            player=player,
                            bg_h=bg.get_height(),
                            tilt_current=tilt_current,
                            tilt_eps=tilt_eps,
                            shear_smoothed=shear_render_in,
                        )

                    # 터치/키 동일: contact_confirm 판정용 상호작용 점(커서=포인터 위치)
                    zone_confirm_click_world = (float(wx), float(wy))

                    # 그네 타기: (구 방식) 키 입력으로 탑승 시도는 옵션으로만 유지
                    if bool(CONFIG.get("SWING_CLICK_TO_RIDE_ENABLED", False)) and swing_ride_mode not in ("approach", "mount", "ride"):
                        try:
                            swing_click_r = float(CONFIG.get("SWING_RIDE_INTERACT_DIST", 55.0) or 55.0)
                        except Exception:
                            swing_click_r = 55.0
                        swing_click_r = max(8.0, min(200.0, swing_click_r))
                        seat_xy = _swing_seat_xy()
                        if seat_xy is not None:
                            sx0, sy0 = float(seat_xy[0]), float(seat_xy[1])
                            try:
                                if math.hypot(float(wx) - sx0, float(wy) - sy0) <= float(swing_click_r):
                                    swing_ride_mode = "approach"
                                    swing_ride_power = 0.0
                                    swing_ride_theta_amp = 0.0
                                    swing_ride_stop_hold = 0.0
                                    swing_ride_mount_end_ms = None
                                    swing_ride_no_dismount_until_s = 0.0
                                    swing_ride_mount_frames_left = 0
                                    swing_ride_mount_start_xy = None
                                    try:
                                        swing_ride_pump_times.clear()
                                    except Exception:
                                        swing_ride_pump_times = deque()
                                    pending_action, target_obj = None, None
                                    # 자동 이동
                                    try:
                                        player.set_new_target(float(sx0), float(sy0), mask, objs, npcs)
                                    except Exception:
                                        try:
                                            player.handle_input([float(sx0), float(sy0)], mask, objs, npcs)
                                        except Exception:
                                            pass
                                    continue
                            except Exception:
                                pass

                    # --- 키 입력 = 클릭: 일반 이동/상호작용 처리 ---
                    is_walkable = False
                    try:
                        cx, cy = int(wx), int(wy)
                        if 0 <= cx < mask.get_width() and 0 <= cy < mask.get_height():
                            is_walkable = mask_terrain_class(mask, wx, wy) == "walk"
                    except Exception:
                        is_walkable = False
                    try:
                        color = (0, 255, 0) if is_walkable else (255, 0, 0)
                        click_feedback = {"pos": (wx, wy), "color": color, "start_time": pygame.time.get_ticks()}
                    except Exception:
                        pass

                    # 더블탭(달리기) 판정: 같은 키를 일정 시간 내 반복
                    now_ms = pygame.time.get_ticks()
                    try:
                        dbl_ms = int(CONFIG.get("DOUBLE_CLICK_MS", 280))
                    except Exception:
                        dbl_ms = 280
                    is_double = False
                    try:
                        if (now_ms - int(last_move_key_ms)) <= dbl_ms and int(event.key) == int(last_move_key):
                            is_double = True
                    except Exception:
                        is_double = False
                    last_move_key_ms = int(now_ms)
                    last_move_key = int(event.key)

                    action, target = player.handle_input(
                        [wx, wy],
                        mask,
                        objs,
                        npcs,
                        move_mode=("run" if is_double else "walk"),
                    )
                    if action == "interact":
                        pending_action, target_obj, target_npc = "interact", target, None
                    elif action == "interact_npc":
                        pending_action, target_obj, target_npc = "interact_npc", None, target
                    else:
                        pending_action, target_obj, target_npc = None, None, None

            # 그네 점프 릴리즈(키/마우스): 앞 정점에서 떼면 점프
            if swing_ride_mode == "ride" and swing_jump_hold_active:
                release = False
                if event.type == pygame.KEYUP and _is_primary_action_key(event.key):
                    release = True
                if event.type == pygame.MOUSEBUTTONUP and getattr(event, "button", None) == 1:
                    release = True
                if release:
                    now_ms = int(pygame.time.get_ticks())
                    try:
                        min_hold = int(CONFIG.get("SWING_JUMP_MIN_HOLD_MS", 220) or 220)
                    except Exception:
                        min_hold = 220
                    min_hold = max(0, min(2000, int(min_hold)))
                    held_ms = int(now_ms - int(swing_jump_hold_started_ms or 0))
                    # 너무 짧게 누른 건 펌프와 구분이 어려우므로 점프 실패(=그냥 펌프로 취급)
                    if held_ms < min_hold:
                        try:
                            swing_ride_pump_times.append(float(now_ms) / 1000.0)
                        except Exception:
                            pass
                        swing_jump_hold_active = False
                    else:
                        stx = _swing_seat_state()
                        ok_front = False
                        rel_ratio = 0.0
                        if stx is not None:
                            try:
                                dn = float(stx.get("depth_n", 0.0) or 0.0)
                                dpk = float(stx.get("depth_peak_n", 0.0) or 0.0)
                            except Exception:
                                dn, dpk = 0.0, 0.0
                            try:
                                rfrac = float(CONFIG.get("SWING_JUMP_RELEASE_FRAC", 0.82) or 0.82)
                            except Exception:
                                rfrac = 0.82
                            rfrac = max(0.1, min(0.999, rfrac))
                            if float(dpk) > 1e-6:
                                rel_ratio = float(dn) / float(dpk)
                                ok_front = bool(float(dn) >= float(dpk) * float(rfrac))
                        if not ok_front:
                            # 앞 정점이 아니면 점프 취소(다시 시도)
                            swing_jump_hold_active = False
                        else:
                            # 정확도 -> 10단계 거리(12~120)
                            try:
                                levels = int(CONFIG.get("SWING_JUMP_LEVELS", 10) or 10)
                            except Exception:
                                levels = 10
                            levels = max(2, min(20, int(levels)))
                            try:
                                press_frac = float(CONFIG.get("SWING_JUMP_PRESS_FRAC", 0.82) or 0.82)
                            except Exception:
                                press_frac = 0.82
                            press_frac = max(0.1, min(0.999, press_frac))
                            # press_ratio는 -1에 가까울수록 좋음, rel_ratio는 +1에 가까울수록 좋음
                            pr = float(swing_jump_hold_press_ratio)
                            press_acc = max(0.0, min(1.0, (-float(pr) - float(press_frac)) / max(1e-6, (1.0 - float(press_frac)))))
                            rel_acc = max(0.0, min(1.0, (float(rel_ratio) - float(press_frac)) / max(1e-6, (1.0 - float(press_frac)))))
                            acc = max(0.0, min(1.0, min(float(press_acc), float(rel_acc))))
                            lvl = 1 + int(round(float(acc) * float(levels - 1)))
                            try:
                                dmin = float(CONFIG.get("SWING_JUMP_DIST_MIN_STEP_PX", 12.0) or 12.0)
                            except Exception:
                                dmin = 12.0
                            try:
                                dmax = float(CONFIG.get("SWING_JUMP_DIST_MAX_STEP_PX", 120.0) or 120.0)
                            except Exception:
                                dmax = 120.0
                            dmin = max(0.0, dmin)
                            dmax = max(dmin, dmax)
                            step = (float(dmax) - float(dmin)) / float(levels - 1)
                            jump_dist = float(dmin) + float(step) * float(lvl - 1)

                            # 그네에서 내려 점프 웨이포인트 실행
                            swing_ride_mode = None
                            swing_ride_theta_amp = None
                            swing_jump_hold_active = False
                            try:
                                player.clear_anim_override()
                            except Exception:
                                pass
                            if swing_ride_prev_height is not None:
                                try:
                                    player.height = float(swing_ride_prev_height)
                                except Exception:
                                    pass
                            swing_ride_prev_height = None

                            land = None
                            for k in (1.0, 0.8, 0.6, 0.45, 0.3):
                                lx = float(player.pos[0])
                                ly = float(player.pos[1]) + float(jump_dist) * float(k)
                                try:
                                    ok, _nl = player.check_walkable(lx, ly, mask, objs, npcs)
                                except Exception:
                                    ok = True
                                if ok:
                                    land = (lx, ly)
                                    break
                            if land is None:
                                land = (float(player.pos[0]), float(player.pos[1]) + float(jump_dist))
                            try:
                                player.path = [(float(land[0]), float(land[1]), 1)]
                                player.target = [float(land[0]), float(land[1])]
                            except Exception:
                                pass

        
            can_move = False

        # 인트로/데모 종료 처리: update()로 끝난 경우와, 입력(탈출 클릭 등)으로 end_event()된 경우 모두
        # 이 블록은 pick_global_auto_event보다 먼저 실행되어야 데모가 같은 프레임에 재시작되지 않음.
        intro_id = CONFIG.get("INTRO_EVENT_ID", "ev_intro_scene")
        if ev_mgr.last_ended_event_id == intro_id:
            ev_mgr.last_ended_event_id = None
            flow.boot_phase = 1

        demo_id = CONFIG.get("DEMO_EVENT_ID")
        if ev_mgr.last_ended_event_id == demo_id:
            ev_mgr.last_ended_event_id = None
            if had_save_at_launch and save_spawn_snapshot and save_spawn_snapshot.get("current_map"):
                flow.save_data["current_map"] = save_spawn_snapshot["current_map"]
                pp = save_spawn_snapshot.get("player_pos")
                spawn_sd = {"current_map": flow.save_data["current_map"]}
                if pp is not None:
                    spawn_sd["player_pos"] = list(pp)
                else:
                    mid = flow.save_data["current_map"]
                    sp = flow.world_data.get(mid, {}).get("start_pos", [100, 100])
                    spawn_sd["player_pos"] = list(sp)
                map_id, bg, mask, player, objs, npcs = flow.load_map(save_data=spawn_sd)
            else:
                flow.save_data["current_map"] = CONFIG["NEW_GAME_SPAWN_MAP"]
                flow.save_data["player_pos"] = list(CONFIG["NEW_GAME_SPAWN_POS"])
                map_id, bg, mask, player, objs, npcs = flow.load_map(
                    save_data={
                        "current_map": flow.save_data["current_map"],
                        "player_pos": flow.save_data["player_pos"],
                    }
                )
            # bg_zones 캐시도 맵 단위로 재빌드
            try:
                _rebuild_bg_zone_cache()
            except Exception:
                pass
            flow.save_data["player_pos"] = [int(player.pos[0]), int(player.pos[1])]
            cam.snap_to(player.pos)
            cam.set_follow_player(smooth=False)
            _reload_event_bundles()
            flow.save_game(map_id, player.pos)
            flow.boot_phase = 2
            _queue_sync_for_map(map_id)
            # 데모 이벤트의 FADEOUT(검게)이 진행 중이면 타이머를 덮어쓰지 않고, 끝난 뒤에만 페이드인
            if getattr(ev_mgr, "is_fading", False) and int(getattr(ev_mgr, "fade_target", 0) or 0) == 255:
                ev_mgr.schedule_fade_in_after_current_fadeout(0.5)
            else:
                fa = int(getattr(ev_mgr, "fade_alpha", 0) or 0)
                if fa < 16:
                    ev_mgr.fade_alpha = 255
                ev_mgr.start_global_fade_to(0, 0.5)
            print(f"[온보딩 완료] 스폰 맵={map_id}, pos={flow.save_data['player_pos']}")

        # --- 3. 상호작용 및 물리 로직 ---
        for _sim_i in range(max(0, int(sim_steps))):
            # 그네 타기(탑승 이후): 이동 로직 대신 좌석에 고정
            if swing_ride_mode in ("mount", "ride"):
                # stop_moving()은 anim_override까지 지워버려(seat_idle/seating이 풀림) 여기서는 쓰지 않는다.
                # 대신 경로만 제거해서 이동만 막는다.
                try:
                    player.path = []
                    player.target = list(player.pos)
                except Exception:
                    pass
            elif not bool(getattr(ev_mgr, "is_talking", False)):
                player.move(mask, objs, npcs)
                # 이벤트 MOVE 중에도 NPC는 path/event_waypoints를 따라가야 함 (carrot 등 BaseCharacter)
                for n in npcs:
                    n.move(mask, objs, npcs)
                # 이벤트 MOVE: PLACE 된 오브젝트(FieldItem) 직선 이동
                for o in objs:
                    if getattr(o, "path", None):
                        om = getattr(o, "move", None)
                        if callable(om):
                            om(mask, objs, npcs)
            if not ev_mgr.active_event and not bool(getattr(ev_mgr, "is_talking", False)):
                try:
                    from char_behavior import tick_npc_behaviors
                    tick_npc_behaviors(npcs, player, mask, objs, ev_mgr, map_id)
                except Exception:
                    pass
        
        # --- 그네 타기 상태 업데이트(데모) ---
        if not ev_mgr.active_event and swing_ride_mode in ("approach", "mount", "ride"):
            seat_xy = _swing_seat_xy()
            if seat_xy is not None:
                sx, sy = float(seat_xy[0]), float(seat_xy[1])
                st0 = _swing_seat_state()
                # 점프 준비 구간 판정(ride 상태에서만)
                swing_jump_ready = False
                if swing_ride_mode == "ride" and st0:
                    try:
                        pth = float(CONFIG.get("SWING_JUMP_POWER_THRESH", 0.75) or 0.75)
                    except Exception:
                        pth = 0.75
                    try:
                        back_frac = float(CONFIG.get("SWING_JUMP_BACK_PEAK_FRAC", 0.88) or 0.88)
                    except Exception:
                        back_frac = 0.88
                    back_frac = max(0.1, min(0.999, back_frac))
                    try:
                        dn = float(st0.get("depth_n", 0.0) or 0.0)
                        dpk = float(st0.get("depth_peak_n", 0.0) or 0.0)
                    except Exception:
                        dn, dpk = 0.0, 0.0
                    if float(swing_ride_power) >= float(pth) and float(dpk) > 1e-6:
                        swing_jump_ready = bool(float(dn) <= -float(dpk) * float(back_frac))
                # 접근 → 탑승 트리거
                if swing_ride_mode == "approach":
                    try:
                        mount_r = float(CONFIG.get("SWING_RIDE_MOUNT_DIST", 26.0) or 26.0)
                    except Exception:
                        mount_r = 26.0
                    mount_r = max(6.0, min(120.0, mount_r))
                    try:
                        if math.hypot(float(player.pos[0]) - sx, float(player.pos[1]) - sy) <= mount_r:
                            swing_ride_mode = "mount"
                            try:
                                swing_ride_prev_height = float(getattr(player, "height", 0) or 0)
                            except Exception:
                                swing_ride_prev_height = 0.0
                            # 탑승 중 정렬: 그네 엔티티 layer를 -1로 내려 플레이어를 덮지 않게 한다.
                            # 4프레임 동안 탑승 전 위치 → 그네 좌석으로 이동(점프처럼)
                            try:
                                swing_ride_mount_frames_total = int(CONFIG.get("SWING_RIDE_MOUNT_FRAMES", swing_ride_mount_frames_total) or swing_ride_mount_frames_total)
                            except Exception:
                                pass
                            swing_ride_mount_frames_total = max(1, min(20, int(swing_ride_mount_frames_total)))
                            swing_ride_mount_frames_left = int(swing_ride_mount_frames_total)
                            try:
                                swing_ride_mount_start_xy = (float(player.pos[0]), float(player.pos[1]))
                            except Exception:
                                swing_ride_mount_start_xy = (float(sx), float(sy))
                            try:
                                swing_ride_mount_start_h = float(getattr(player, "height", 0) or 0)
                            except Exception:
                                swing_ride_mount_start_h = 0.0
                            pending_action, target_obj = None, None
                            try:
                                player.stop_moving()
                            except Exception:
                                pass
                            try:
                                player.direction = "left"
                            except Exception:
                                pass
                            try:
                                # seating_left 세트 사용: state=seating + direction=left
                                player.play_anim("seating", duration_ms=None, loop=True, release="stop")
                            except Exception:
                                pass
                    except Exception:
                        pass

                # 탑승/주행: 좌석에 붙이고 높이를 동기화
                if swing_ride_mode in ("mount", "ride"):
                    seat_h = float(_swing_seat_height())
                    try:
                        h_off = float(CONFIG.get("SWING_RIDE_SEAT_HEIGHT_OFFSET_PX", -5.0) or -5.0)
                    except Exception:
                        h_off = -5.0
                    seat_h = max(0.0, float(seat_h) + float(h_off))
                    if swing_ride_mode == "mount" and int(swing_ride_mount_frames_left) > 0 and swing_ride_mount_start_xy is not None:
                        # 4프레임 이동
                        total = max(1, int(swing_ride_mount_frames_total))
                        left = max(1, int(swing_ride_mount_frames_left))
                        done = total - left + 1
                        t = float(done) / float(total)
                        t = max(0.0, min(1.0, t))
                        sx0, sy0 = float(swing_ride_mount_start_xy[0]), float(swing_ride_mount_start_xy[1])
                        px = sx0 + (float(sx) - sx0) * t
                        py = sy0 + (float(sy) - sy0) * t
                        try:
                            player.pos[0], player.pos[1] = float(px), float(py)
                            player.target = [float(px), float(py)]
                            player.path = []
                        except Exception:
                            pass
                        # seating 동안 높이도 부드럽게 좌석 높이로
                        try:
                            ph0 = float(swing_ride_mount_start_h)
                            player.height = float(ph0 + (seat_h - ph0) * t)
                        except Exception:
                            pass
                        swing_ride_mount_frames_left = int(swing_ride_mount_frames_left) - 1
                    else:
                        # 좌석 고정
                        try:
                            player.pos[0], player.pos[1] = float(sx), float(sy)
                            player.target = [float(sx), float(sy)]
                            player.path = []
                        except Exception:
                            pass
                        try:
                            player.height = float(seat_h)
                        except Exception:
                            pass

                # mount 끝나면 ride로 전환(앉은 자세 지속)
                if swing_ride_mode == "mount":
                    try:
                        if int(swing_ride_mount_frames_left) <= 0:
                            swing_ride_mode = "ride"
                            swing_ride_mount_end_ms = None
                            swing_ride_mount_start_xy = None
                            try:
                                min_ride = float(CONFIG.get("SWING_RIDE_MIN_RIDE_SEC", 3.0) or 3.0)
                            except Exception:
                                min_ride = 3.0
                            min_ride = max(0.0, min(30.0, min_ride))
                            try:
                                swing_ride_no_dismount_until_s = float(pygame.time.get_ticks()) / 1000.0 + float(min_ride)
                            except Exception:
                                swing_ride_no_dismount_until_s = 0.0
                            try:
                                # seat_idle_left 세트 사용: state=seat_idle + direction=left
                                player.play_anim("seat_idle", duration_ms=None, loop=True, release="stop")
                            except Exception:
                                pass
                    except Exception:
                        pass

                # ride: 연타로 파워 상승, 아니면 감쇠
                if swing_ride_mode == "ride":
                    now_s = float(pygame.time.get_ticks()) / 1000.0
                    try:
                        wsec = float(CONFIG.get("SWING_RIDE_PUMP_WINDOW_SEC", 0.8) or 0.8)
                    except Exception:
                        wsec = 0.8
                    wsec = max(0.2, min(2.0, wsec))
                    # 윈도우 밖 입력 제거
                    try:
                        while swing_ride_pump_times and (now_s - float(swing_ride_pump_times[0])) > wsec:
                            swing_ride_pump_times.popleft()
                    except Exception:
                        pass
                    try:
                        cps = float(len(swing_ride_pump_times)) / max(1e-6, float(wsec))
                    except Exception:
                        cps = 0.0
                    try:
                        cps_th = float(CONFIG.get("SWING_RIDE_PUMP_CPS", 4.5) or 4.5)
                    except Exception:
                        cps_th = 4.5
                    try:
                        acc = float(CONFIG.get("SWING_RIDE_ACCEL_PER_SEC", 0.55) or 0.55)
                    except Exception:
                        acc = 0.55
                    try:
                        dec = float(CONFIG.get("SWING_RIDE_DECAY_PER_SEC", 0.18) or 0.18)
                    except Exception:
                        dec = 0.18
                    try:
                        pmax = float(CONFIG.get("SWING_RIDE_POWER_MAX", 1.0) or 1.0)
                    except Exception:
                        pmax = 1.0
                    pmax = max(0.1, min(1.0, pmax))

                    pumping = bool(cps >= float(cps_th))
                    if pumping:
                        swing_ride_power = min(float(pmax), float(swing_ride_power) + float(acc) * max(0.0, float(dt_sec)))
                    else:
                        swing_ride_power = max(0.0, float(swing_ride_power) - float(dec) * max(0.0, float(dt_sec)))

                    # 파워 -> 진폭(라디안)
                    try:
                        th0 = float(CONFIG.get("SWING_THETA0_RAD", 0.85) or 0.85)
                    except Exception:
                        th0 = 0.85
                    th0 = max(0.0, min(1.35, th0))
                    swing_ride_theta_amp = float(th0) * max(0.0, min(1.0, float(swing_ride_power)))

                    # 정지 판정 → 자동 하차
                    try:
                        eps = float(CONFIG.get("SWING_RIDE_STOP_POWER_EPS", 0.03) or 0.03)
                    except Exception:
                        eps = 0.03
                    eps = max(0.0, min(0.2, eps))
                    try:
                        hold = float(CONFIG.get("SWING_RIDE_STOP_HOLD_SEC", 0.35) or 0.35)
                    except Exception:
                        hold = 0.35
                    hold = max(0.05, min(2.0, hold))

                    if float(swing_ride_power) <= eps and (not pumping):
                        swing_ride_stop_hold += max(0.0, float(dt_sec))
                    else:
                        swing_ride_stop_hold = 0.0

                    if swing_ride_stop_hold >= hold:
                        # 최소 유지 시간(탑승 직후 바로 하차 방지)
                        try:
                            if float(now_s) < float(swing_ride_no_dismount_until_s):
                                swing_ride_stop_hold = 0.0
                                # 이 프레임은 하차하지 않음
                                continue
                        except Exception:
                            pass
                        # 하차: 높이/애니 복구
                        swing_ride_mode = None
                        swing_ride_power = 0.0
                        swing_ride_theta_amp = None
                        swing_ride_stop_hold = 0.0
                        swing_ride_mount_end_ms = None
                        swing_ride_no_dismount_until_s = 0.0
                        try:
                            swing_ride_pump_times.clear()
                        except Exception:
                            pass
                        try:
                            player.clear_anim_override()
                        except Exception:
                            pass
                        if swing_ride_prev_height is not None:
                            try:
                                player.height = float(swing_ride_prev_height)
                            except Exception:
                                pass
                        swing_ride_prev_height = None

                    # (점프 로직 변경) 드래그 기반 점프는 제거됨.

        # 상호작용: progress→이벤트 / NPC 대화 / 물건 집기
        if not ev_mgr.active_event and not bool(getattr(ev_mgr, "is_talking", False)):
            _interact_snap = (
                ui.tilt_bg_demo,
                float(ui.tilt_target),
                float(tilt_current),
                bool(ui.shear_debug_on),
            )
            _sess = {"gamestart": flow.boot_phase}
            if pending_action == "interact_npc" and target_npc:
                from char_behavior import get_interact_range, start_npc_talk

                from flow import entity_interact_anchor_xy

                npos = entity_interact_anchor_xy(target_npc)
                if npos and math.dist(player.pos, npos) < get_interact_range(target_npc):
                    started_evt = try_start_interact_event(
                        target_npc,
                        flow,
                        ev_mgr,
                        events_catalog,
                        map_id,
                        session_vars=_sess,
                        field_tilt_snapshot=_interact_snap,
                        player=player,
                        npcs=npcs,
                        objs=objs,
                    )
                    if not started_evt:
                        start_npc_talk(
                            target_npc,
                            player,
                            flow,
                            ev_mgr,
                            map_id,
                            session_vars=_sess,
                        )
                pending_action, target_obj, target_npc = None, None, None
            elif pending_action == "interact" and target_obj:
                from flow import entity_interact_anchor_xy, entity_interact_range

                op = entity_interact_anchor_xy(target_obj)
                rng = max(
                    40.0,
                    entity_interact_range(
                        target_obj, default=float(CONFIG.get("OBJECT_INTERACT_RANGE", 40))
                    ),
                )
                if op and math.dist(player.pos, op) < rng:
                    if not try_start_interact_event(
                        target_obj,
                        flow,
                        ev_mgr,
                        events_catalog,
                        map_id,
                        session_vars=_sess,
                        field_tilt_snapshot=_interact_snap,
                        player=player,
                        npcs=npcs,
                        objs=objs,
                    ):
                        iw = getattr(player, "interact_with", None)
                        if callable(iw):
                            iw(
                                target_obj,
                                flow=flow,
                                objs=objs,
                                npcs=npcs,
                                map_id=map_id,
                            )
                pending_action, target_obj, target_npc = None, None, None

        # 글로벌 조건 트리거(인트로 등) → 존(맵 박스) 트리거보다 먼저
        if not ev_mgr.active_event:
            # 이벤트(DEV_CMD)로 요청된 그네 탑승 시작 처리
            req = getattr(ev_mgr, "swing_ride_request", None)
            if isinstance(req, dict) and req.get("action") == "start":
                try:
                    ev_mgr.swing_ride_request = None
                except Exception:
                    pass
                seat_xy = _swing_seat_xy()
                if seat_xy is not None:
                    sx0, sy0 = float(seat_xy[0]), float(seat_xy[1])
                    swing_ride_mode = "approach"
                    swing_ride_power = 0.0
                    swing_ride_theta_amp = 0.0
                    swing_ride_stop_hold = 0.0
                    swing_ride_mount_end_ms = None
                    swing_ride_no_dismount_until_s = 0.0
                    swing_ride_mount_frames_left = 0
                    swing_ride_mount_start_xy = None
                    try:
                        swing_ride_pump_times.clear()
                    except Exception:
                        swing_ride_pump_times = deque()
                    pending_action, target_obj = None, None
                    try:
                        player.set_new_target(float(sx0), float(sy0), mask, objs, npcs)
                    except Exception:
                        pass

            if _try_start_pending_sync_event():
                pending_action = None
            else:
                gid, _gent = pick_global_auto_event(
                    raw_events,
                    flow.save_data,
                    events_catalog,
                    session_vars={"gamestart": flow.boot_phase},
                )
                if gid:
                    ev = events_catalog[gid]
                    ev_mgr.reset_entity_event_zooms(player, npcs, objs)
                    ev_mgr.start_event(ev.get("steps") or [], gid, ev.get("result"), ev)
                    ev_mgr.field_tilt_snapshot = (
                        ui.tilt_bg_demo,
                        float(ui.tilt_target),
                        float(tilt_current),
                        bool(ui.shear_debug_on),
                    )
                    player.stop_moving()
                    pending_action = None
                else:
                    tid = flow.check_zone_trigger(
                        map_id,
                        player.pos,
                        False,
                        dt_sec,
                        objs=objs,
                        npcs=npcs,
                        # 그네 탑승/접근 중에는 이벤트존 confirm을 잠시 무시:
                        # swing zone(그네타기 박스) 안에서 펌프/점프 입력이 매번 이벤트를 재시작하지 않게 한다.
                        zone_click_world=(None if swing_ride_mode in ("approach", "mount", "ride") else zone_confirm_click_world),
                    )
                    if tid and tid in events_catalog:
                        ev = events_catalog[tid]
                        ev_mgr.reset_entity_event_zooms(player, npcs, objs)
                        ev_mgr.start_event(ev.get("steps") or [], tid, ev.get("result"), ev)
                        ev_mgr.field_tilt_snapshot = (
                            ui.tilt_bg_demo,
                            float(ui.tilt_target),
                            float(tilt_current),
                            bool(ui.shear_debug_on),
                        )
                        player.stop_moving()
                        pending_action = None

            pass

        # 커서 이동 (rg35xxsp: 마우스 없이 D-pad로 이동)
        keys = pygame.key.get_pressed()
        _cursor_k = max(1e-6, float(dt_real_ms) / 16.666)
        if keys[pygame.K_LEFT]: ui_cursor[0] -= cursor_speed * _cursor_k
        if keys[pygame.K_RIGHT]: ui_cursor[0] += cursor_speed * _cursor_k
        if keys[pygame.K_UP]: ui_cursor[1] -= cursor_speed * _cursor_k
        if keys[pygame.K_DOWN]: ui_cursor[1] += cursor_speed * _cursor_k
        # 화면 밖으로 나가면 조작이 불편하므로 항상 클램프
        try:
            ui_cursor[0] = max(0, min(int(CONFIG["WIDTH"]) - 1, int(ui_cursor[0])))
            ui_cursor[1] = max(0, min(int(CONFIG["HEIGHT"]) - 1, int(ui_cursor[1])))
        except Exception:
            pass

        # (점프 로직 변경) 드래그 기반 점프 제거됨.

        # --- 4. 업데이트 및 애니메이션 ---
        t0 = _pnow() if perf_enabled else None
        for o in objs:
            # --- optional auto scroll (background fog etc.) ---
            # Apply even if BGZONES update_policy == "none".
            try:
                asc = getattr(o, "auto_scroll", None)
            except Exception:
                asc = None
            if isinstance(asc, dict) and not bool(getattr(o, "is_held", False)) and not bool(getattr(o, "is_flying", False)):
                try:
                    vx = float(asc.get("vx", 0.0) or 0.0)  # px/sec (world)
                except Exception:
                    vx = 0.0
                if abs(vx) > 1e-9:
                    wrap = str(asc.get("wrap", "camera_view") or "camera_view").strip().lower()
                    # --- 기본: seamless 가로 타일(텍스처 위상만 이동, FieldItem.draw에서 2장 이어붙임)
                    # --- wrap: legacy_wrap | teleport 만 예전 방식(월드 이동+뷰 밖 텔레포트)
                    if wrap in ("legacy_wrap", "teleport"):
                        try:
                            o.pos[0] = float(o.pos[0]) + float(vx) * float(dt_sec)
                            o.origin_pos = [float(o.pos[0]), float(o.pos[1])]
                        except Exception:
                            pass
                        try:
                            z_wrap = snap_render_zoom(float(cam.current_zoom))
                            z_wrap = max(1e-6, float(z_wrap))
                            view_left = float(cam.pos[0]) - float(cam.width) / z_wrap / 2.0
                            view_right = view_left + float(cam.width) / z_wrap
                            try:
                                half_w = float(o.image.get_width()) * 0.5
                            except Exception:
                                half_w = 0.0
                            if float(vx) > 0.0 and (float(o.pos[0]) - half_w) > view_right:
                                o.pos[0] = float(view_left) - float(half_w)
                                o.origin_pos = [float(o.pos[0]), float(o.pos[1])]
                            elif float(vx) < 0.0 and (float(o.pos[0]) + half_w) < view_left:
                                o.pos[0] = float(view_right) + float(half_w)
                                o.origin_pos = [float(o.pos[0]), float(o.pos[1])]
                        except Exception:
                            pass
                    else:
                        try:
                            iw = float(o.image.get_width())
                            iw = max(1.0, iw)
                        except Exception:
                            iw = 1.0
                        if not hasattr(o, "_auto_scroll_accum"):
                            try:
                                o._auto_scroll_accum = float(o.pos[0]) % iw
                            except Exception:
                                o._auto_scroll_accum = 0.0
                        try:
                            o._auto_scroll_accum = float(o._auto_scroll_accum) + float(vx) * float(dt_sec)
                            o._auto_scroll_accum = o._auto_scroll_accum % iw
                        except Exception:
                            pass

            # BGZONES: 원경 오브젝트는 update를 줄이거나 아예 끈다(정렬/업데이트 부하 절감)
            if bool(getattr(o, "is_held", False)):
                o.update_anim()
                wx, wy = engine_mod._held_item_foot_world_pos(
                    player.pos[0], player.pos[1], player.direction
                )
                o.pos[0] = wx
                o.pos[1] = wy
                o.origin_pos[0] = wx
                o.origin_pos[1] = wy
                o.update(player.pos)
                continue
            zi = ent_bg_zone_idx.get(id(o)) if bg_zones_norm else None
            if zi is not None and 0 <= int(zi) < len(bg_zones_norm):
                pol = bg_zones_norm[int(zi)].get("update_policy", "none")
                if pol == "none":
                    continue
                if pol == "lowrate":
                    # 저주기 업데이트(기본 4프레임당 1번)
                    if (loop_i % 4) != 0:
                        continue
            o.update_anim()
            o.update(player.pos)
        for c in [player] + npcs:
            if c is player:
                c.update_anim()
                continue
            zi = ent_bg_zone_idx.get(id(c)) if bg_zones_norm else None
            if zi is not None and 0 <= int(zi) < len(bg_zones_norm):
                pol = bg_zones_norm[int(zi)].get("update_policy", "none")
                if pol == "none":
                    continue
                if pol == "lowrate" and (loop_i % 4) != 0:
                    continue
            c.update_anim()
        if perf_enabled and t0 is not None:
            _padd("obj_update", _pnow() - t0)

        # 이동·애니 이후에 카메라를 맞춤(이전: move 전에 update 해서 위쪽 스크롤이 한 박자 어긋져 끊겨 보일 수 있음)
        t0 = _pnow() if perf_enabled else None
        # 렌더링에 쓰는 쉬어(px)를 줌에 맞게 보정해서 카메라 클램프도 동일 기준으로 동작하게 한다.
        shear_render = float(shear_smoothed)
        try:
            if bool(CONFIG.get("SHEAR_SCALE_WITH_ZOOM", False)):
                zref = float(CONFIG.get("SHEAR_ZOOM_REF", 1.0) or 1.0)
                zp = float(CONFIG.get("SHEAR_ZOOM_POWER", 1.0) or 1.0)
                zref = max(1e-6, zref)
                scale = pow(float(world_z_for_shear) / zref, zp)
                shear_render *= float(scale)
                smax = float(CONFIG.get("SHEAR_RENDER_PX_MAX", 512) or 512)
                shear_render = max(0.0, min(float(smax), float(shear_render)))
        except Exception:
            pass
        # OUTPUT_MODE 전환(640<->320 업스케일)에서도 "물리 화면에서 같은 쉬어/보정 느낌"을 유지:
        # shear_render는 '스크린 픽셀 단위'이므로 논리 해상도(320)에서는 scale_factor만큼 줄여야 한다.
        # (마지막에 screen으로 업스케일되면서 물리 픽셀 크기는 다시 동일해짐)
        try:
            sf = max(1e-6, float(scale_factor))
            shear_render = float(shear_render) / sf
        except Exception:
            pass
        cam.update(
            player, npcs, objs, bg_w, bg_h, shear_screen_px=float(shear_render), dt_sec=dt_sec
        )
        if auto_res_hold_cam_pos is not None:
            try:
                cam.pos[0] = float(auto_res_hold_cam_pos[0])
                cam.pos[1] = float(auto_res_hold_cam_pos[1])
            except Exception:
                pass
            auto_res_hold_cam_pos = None
        if perf_enabled and t0 is not None:
            _padd("cam_update", _pnow() - t0)

        # --- 5. 그리기 ---
        # 새 줌 시스템: 월드(오버레이 제외)를 world_surf에 렌더한 뒤, 그 결과물만 통째로 스케일해 draw_surf에 합성한다.
        t_render0 = _pnow() if perf_enabled else None
        now_s = time.time()
        world_surf.fill((30, 30, 30))
        render_surf = world_surf
        # [1. 공통 카메라 시작점] — 부동소수 원점으로 틸트 앵커를 계산하고, 타일 정렬만 int로 맞춤
        z = snap_render_zoom(float(cam.current_zoom))
        z = max(1e-6, float(z))
        cam_origin_x = float(cam.pos[0]) - float(cam.width) / z / 2.0
        cam_origin_y = float(cam.pos[1]) - float(cam.height) / z / 2.0
        # 렌더링용 원점은 zoom 픽셀 그리드에 스냅(떨림/1px 차이 완화)
        cam_origin_x = round(cam_origin_x * z) / z
        cam_origin_y = round(cam_origin_y * z) / z

        # [2. 배경 그리기] - cam.to_screen을 쓰지 않고 직접 계산합니다.
        y_transform = None
        x_offset_fn = None
        # 입력 역변환용 파라미터는 매 프레임 확정값으로 초기화해야 한다.
        # (파이썬 함수 프레임에서는 루프가 돌아도 지역변수가 남아, locals() 기반 체크로는
        #  이전 프레임 tilt 값(shift_y/f_q)이 남아 클릭 좌표가 틀어질 수 있다.)
        shift_y = 0.0
        f_q = 1.0
        tilt_active = abs(float(tilt_current) - 1.0) > tilt_eps
        try:
            sh_br = float(CONFIG.get("SHEAR_BRANCH_OFF_EPS", 0.02))
        except Exception:
            sh_br = 0.02
        shear_eff = max(0, int(round(float(shear_render))))
        use_perspective_branch = tilt_active or float(shear_render) > sh_br

        # 배경: 기본은 뷰포트(맵 일부 크롭→스케일). 틸트/쉬어 시엔 월드 크롭을 넉넉히 확장한 뒤 동일 파이프라인.
        bg_no_cache = False

        # 안전장치(메모리 스파이크): "전체 배경 스케일 Surface"가 너무 크면 생성 자체를 피한다.
        # zoom+tilt+shear가 겹치면 큰 Surface가 한 프레임에 여러 장 생겨 RSS가 순간적으로 치솟을 수 있다.
        bg_direct_fallback = False
        try:
            bw0, bh0 = bg.get_size()
            est_full_mb = _est_rgba_mb(int(round(float(bw0) * float(z))), int(round(float(bh0) * float(z))))
            if est_full_mb > _tmp_surf_mb_limit:
                bg_direct_fallback = True
        except Exception:
            bg_direct_fallback = False

        t0 = _pnow() if perf_enabled else None
        flat_vp_ok = False
        vp_exp_r = None
        s_bg = None
        bg_blit_dx = 0
        bg_blit_dy = 0

        if bg_direct_fallback:
            # emergency: 화면(view)만 잘라 스케일해 그린다(대형 Surface 생성 회피).
            # 이 프레임은 tilt/shear를 생략(메모리 안정 우선).
            _blit_bg_view_scaled(render_surf, bg, cam_origin_x, cam_origin_y, z)
            bg_dx = 0
            bg_dy = 0
            cam_draw_x = float(cam_origin_x)
            cam_draw_y = float(cam_origin_y)
            y_transform = None
            x_offset_fn = None
            use_perspective_branch = False
            f_q = 1.0
            bg_blit_dx, bg_blit_dy = 0, 0
        else:
            is_zooming = False
            try:
                is_zooming = abs(float(cam.current_zoom) - float(cam.target_zoom)) > 1e-9
            except Exception:
                is_zooming = False
            bg_dx = int(round((0.0 - cam_origin_x) * z))
            bg_dy = int(round((0.0 - cam_origin_y) * z))
            cam_draw_x = -float(bg_dx) / z
            cam_draw_y = -float(bg_dy) / z
            bg_blit_dx, bg_blit_dy = bg_dx, bg_dy

            use_vp_bg = bool(CONFIG.get("BG_VIEWPORT_BLIT_ENABLED", True))
            view_w_i = int(CONFIG["WIDTH"])
            view_h_i = int(CONFIG["HEIGHT"])

            # 줌 중에는(틸트/쉬어 없는 경우) viewport crop→scale을 강제로 사용해 부하를 줄인다.
            # BG_VIEWPORT_BLIT_ENABLED 기본값이 꺼져 있어도, 줌 중에만 켠다.
            try:
                zoom_lod_on = bool(CONFIG.get("ZOOM_LOD_BG_VIEWPORT_ENABLED", True))
            except Exception:
                zoom_lod_on = True
            if zoom_lod_on and is_zooming and (not use_perspective_branch):
                use_vp_bg = True

            if use_vp_bg and (not use_perspective_branch):
                if _blit_bg_view_scaled(render_surf, bg, cam_origin_x, cam_origin_y, z):
                    flat_vp_ok = True

            if (not flat_vp_ok) and use_vp_bg and use_perspective_branch:
                try:
                    try:
                        vp_pad = int(CONFIG.get("BG_VIEWPORT_TILT_PAD_PX", 8) or 8)
                    except Exception:
                        vp_pad = 8
                    vp_pad = max(0, min(64, vp_pad))
                    try:
                        tq_pre = float(CONFIG.get("RENDER_TILT_STEP", 0.01))
                    except Exception:
                        tq_pre = 0.01
                    tq_pre = max(0.001, min(0.1, tq_pre))
                    try:
                        anim_t_pre = bool(tilt_active) and abs(float(ui.tilt_target) - float(tilt_current)) > float(
                            tilt_eps
                        )
                    except Exception:
                        anim_t_pre = False
                    if anim_t_pre:
                        tq_pre = max(tq_pre, 0.02)
                    if tilt_active:
                        f_pre = max(tilt_factor_min, min(1.0, float(tilt_current)))
                        f_q_pre = max(tilt_factor_min, min(1.0, round(round(f_pre / tq_pre) * tq_pre, 4)))
                    else:
                        f_q_pre = 1.0
                    base_wr = _bg_view_world_rect(cam_origin_x, cam_origin_y, z, view_w_i, view_h_i, bw0, bh0)
                    if base_wr is not None:
                        try:
                            cur_h_vp = float(CONFIG["HEIGHT"])
                        except Exception:
                            cur_h_vp = 480.0
                        cur_h_vp = max(1e-6, cur_h_vp)
                        try:
                            fq_vp = max(0.12, float(f_q_pre))
                        except Exception:
                            fq_vp = 1.0
                        shear_eff_vp = max(
                            int(shear_eff),
                            int(
                                math.ceil(
                                    float(shear_render) * float(view_h_i) / cur_h_vp / fq_vp
                                )
                            ),
                        )
                        vp_exp_r = _bg_expand_world_rect_perspective(
                            base_wr, bw0, bh0, z, view_w_i, view_h_i, f_q_pre, shear_eff_vp, vp_pad
                        )
                    if vp_exp_r is not None and vp_exp_r.width > 1 and vp_exp_r.height > 1:
                        sub_vp = bg.subsurface(vp_exp_r)
                        sw_sc = max(1, int(round(float(vp_exp_r.width) * z)))
                        sh_sc = max(1, int(round(float(vp_exp_r.height) * z)))
                        if vp_bg_scale_tmp is None or vp_bg_scale_tmp.get_width() != sw_sc or vp_bg_scale_tmp.get_height() != sh_sc:
                            vp_bg_scale_tmp = pygame.Surface((sw_sc, sh_sc))
                        try:
                            pygame.transform.scale(sub_vp, (sw_sc, sh_sc), vp_bg_scale_tmp)
                        except TypeError:
                            vp_bg_scale_tmp = pygame.transform.scale(sub_vp, (sw_sc, sh_sc))
                        s_bg = vp_bg_scale_tmp
                        bg_blit_dx = int(round(float(vp_exp_r.x - cam_origin_x) * z))
                        bg_blit_dy = int(round(float(vp_exp_r.y - cam_origin_y) * z))
                except Exception:
                    s_bg = None
                    vp_exp_r = None
                    bg_blit_dx, bg_blit_dy = bg_dx, bg_dy

            if (not flat_vp_ok) and s_bg is None:
                s_bg = _rc_get_full_scale("bg", bg, z, is_zooming=is_zooming)

        # 애니메이션 중에는 캐시 저장을 하지 않고(읽기만), 임시 Surface 재사용으로 처리해 churn을 줄인다.
        try:
            is_zooming = abs(float(cam.current_zoom) - float(cam.target_zoom)) > 1e-9
        except Exception:
            is_zooming = False
        try:
            anim_tilt_draw = abs(float(tilt_current) - float(last_tilt_draw)) > float(tilt_eps) * 0.5
        except Exception:
            anim_tilt_draw = False
        try:
            anim_shear_draw = abs(float(shear_smoothed) - float(last_shear_draw)) > max(
                0.02, float(CONFIG.get("SHEAR_SMOOTH_EPS", 0.06)) * 0.5
            )
        except Exception:
            anim_shear_draw = False
        cache_write_ok = not (is_zooming or anim_tilt_draw or anim_shear_draw)

        # 틸트 계수(양자화)
        f_q = 1.0
        if use_perspective_branch and (not bg_direct_fallback) and s_bg is not None:
            # 데모: 배경 세로 압축(L) + 쉬어(K 디버그 또는 틸트에 연동된 쉬어)
            try:
                try:
                    tq = float(CONFIG.get("RENDER_TILT_STEP", 0.01))
                except Exception:
                    tq = 0.01
                tq = max(0.001, min(0.1, tq))
                # 틸트가 "움직이는 중"엔 f_q가 계속 바뀌어 캐시 키가 폭발할 수 있으니,
                # 이때만 양자화 단위를 굵게 해서(=키 개수 줄이기) 순간 RSS 스파이크를 줄인다.
                try:
                    anim_tilt = bool(tilt_active) and abs(float(ui.tilt_target) - float(tilt_current)) > float(tilt_eps)
                except Exception:
                    anim_tilt = False
                if anim_tilt:
                    tq = max(tq, 0.02)
                if tilt_active:
                    f = max(tilt_factor_min, min(1.0, float(tilt_current)))
                    f_q = max(tilt_factor_min, min(1.0, round(round(f / tq) * tq, 4)))
                else:
                    f_q = 1.0

                if vp_exp_r is not None:
                    key = (
                        "bg_tilt_vp",
                        id(bg),
                        int(vp_exp_r.x),
                        int(vp_exp_r.y),
                        int(vp_exp_r.w),
                        int(vp_exp_r.h),
                        float(cam.current_zoom),
                        float(f_q),
                    )
                else:
                    key = ("bg_tilt", id(bg), float(cam.current_zoom), float(f_q))
                s_bg2 = _rc_get(key)
                if s_bg2 is None:
                    sw, sh = s_bg.get_width(), s_bg.get_height()
                    nh = max(1, int(sh * f_q))
                    # 임시 대형 Surface 생성 방지: 너무 크면 틸트를 그 프레임만 생략(안정 우선)
                    if _est_rgba_mb(sw, nh) > _tmp_surf_mb_limit:
                        # 안전 폴백: 틸트/쉬어 없이 스케일된 배경만 그림
                        render_surf.blit(s_bg, (bg_blit_dx, bg_blit_dy))
                        if perf_enabled and t0 is not None:
                            _padd("bg", _pnow() - t0)
                        # 배경 분기 끝. 이후 오브젝트는 tilt/shear 없는 좌표계로 그려진다.
                        y_transform = None
                        x_offset_fn = None
                        use_perspective_branch = False
                        raise RuntimeError("skip_tilt_bg_large_surface")
                    s_bg2 = pygame.transform.scale(s_bg, (sw, nh))
                    if cache_write_ok:
                        _rc_put(key, s_bg2)

                # s_bg2 자체가 이미 (sw, sh*f_q)로 만들어진 압축 결과다.
                # tilt_bg_tmp를 같은 크기로 재사용해서, 이후 쉬어 처리가 항상 기대 크기를 보도록 한다.
                sw2, sh2 = s_bg2.get_width(), s_bg2.get_height()
                if tilt_bg_tmp is None or tilt_bg_tmp.get_width() != sw2 or tilt_bg_tmp.get_height() != sh2:
                    tilt_bg_tmp = pygame.Surface((sw2, sh2))
                tilt_bg_tmp.blit(s_bg2, (0, 0))

                # 틸트 후 실제 높이(sh2)에 맞춰 쉬어 픽셀 재계산: 보이는 기울기 ≈ atan2(shear_eff, sh2).
                # 예전엔 shear_eff≈round(shear_render)만 써서, 뷰포트 확장으로 sh2≠논리 HEIGHT일 때 640/320 간 각도가 어긋날 수 있었음.
                try:
                    cur_h_f = float(CONFIG["HEIGHT"])
                except Exception:
                    cur_h_f = 480.0
                cur_h_f = max(1e-6, cur_h_f)
                try:
                    sh2f = float(s_bg2.get_height())
                except Exception:
                    sh2f = cur_h_f
                shear_eff = max(0, int(round(float(shear_render) * (float(sh2f) / cur_h_f))))

                # "플레이어의 화면 위치는 고정"되도록, 압축 변환을 플레이어 발 위치(screen y)에 앵커링
                # 앵커는 렌더에 쓰는 스냅 줌(z)과 동일해야 1~몇 px 드리프트가 줄어든다.
                player_sy = float((player.pos[1] - cam_draw_y) * float(z))
                # shift_y를 int로 먼저 고정하면 틸트 상태에서 스프라이트가 몇 px씩 더 내려가는 오차가 누적되기 쉽다.
                # float로 유지하고, 최종 blit에서만 라운딩한다.
                shift_y = float((player_sy - float(bg_blit_dy)) * (1.0 - float(f_q)))
                # 틸트(세로 압축)로 배경 높이가 줄어들면, 아래쪽에 검은 여백이 생길 수 있음.
                # 이 경우 배경의 바닥이 화면 바닥에 '딱 붙도록' 아래로 추가 이동한다(위쪽 여백은 허용).
                # 논리 뷰포트 높이(내부 렌더 해상도). 물리 screen 높이를 쓰면 EMBEDDED_LIGHTWEIGHT에서
                # 틸트 하단 보정이 2배 크게 잡혀 배경이 과도하게 밀린다.
                try:
                    scr_h = int(CONFIG.get("HEIGHT", 480) or 480)
                except Exception:
                    scr_h = 480
                try:
                    comp_h = int(tilt_bg_tmp.get_height())
                except Exception:
                    comp_h = 0
                bottom = float(bg_blit_dy) + float(shift_y) + float(comp_h)
                if comp_h > 0 and bottom < scr_h:
                    shift_y += float(scr_h) - float(bottom)

                def y_transform(y_screen):
                    try:
                        return float(bg_blit_dy) + float(shift_y) + (float(y_screen) - float(bg_blit_dy)) * float(f_q)
                    except Exception:
                        return y_screen

                try:
                    slice_h = int(CONFIG.get("TILT_SHEAR_SLICE_H_PX", 8) or 8)
                except Exception:
                    slice_h = 8
                slice_h = max(1, min(64, slice_h))

                # 쉬어 결과는 왼쪽에 shear_eff 만큼 투명 열이 있다. 전체 맵(bg_dx 큰 음수)에선 화면 밖으로 잘리지만
                # 뷰포트(bg_blit_dx≈0)에선 그 열이 화면 왼쪽에 그대로 보이므로 그때만 blit X를 당긴다.
                try:
                    sh_i = int(shear_eff)
                except Exception:
                    sh_i = 0
                if vp_exp_r is not None and sh_i > 0:
                    blit_x_shear = int(bg_blit_dx) - sh_i
                else:
                    blit_x_shear = int(bg_blit_dx)

                if shear_eff > 0:
                    if vp_exp_r is not None:
                        skey = (
                            "bg_shear_vp",
                            id(bg),
                            int(vp_exp_r.x),
                            int(vp_exp_r.y),
                            int(vp_exp_r.w),
                            int(vp_exp_r.h),
                            float(cam.current_zoom),
                            float(f_q),
                            int(shear_eff),
                            int(slice_h),
                        )
                    else:
                        skey = ("bg_shear", id(bg), float(cam.current_zoom), float(f_q), int(shear_eff), int(slice_h))
                    s_bg3 = _rc_get(skey)
                    if s_bg3 is None:
                        sw, sh2 = tilt_bg_tmp.get_width(), tilt_bg_tmp.get_height()
                        out_w = sw + shear_eff
                        # 쉬어 결과는 폭이 더 커져 메모리 스파이크가 심함 → 너무 크면 쉬어만 생략(틸트는 유지)
                        if _est_rgba_mb(out_w, sh2) > _tmp_surf_mb_limit:
                            render_surf.blit(tilt_bg_tmp, (int(bg_blit_dx), int(round(float(bg_blit_dy) + float(shift_y)))))

                            # 쉬어는 생략
                            x_offset_fn = None
                            raise RuntimeError("skip_shear_bg_large_surface")
                        if shear_bg_tmp is None or shear_bg_tmp.get_width() != out_w or shear_bg_tmp.get_height() != sh2:
                            shear_bg_tmp = pygame.Surface((out_w, sh2), pygame.SRCALPHA)
                        shear_bg_tmp.fill((0, 0, 0, 0))
                        for yy in range(0, sh2, slice_h):
                            hh = min(slice_h, sh2 - yy)
                            rel = 0.0 if sh2 <= 1 else (yy / float(sh2))
                            dxs = int(round((1.0 - rel) * shear_eff))
                            src = pygame.Rect(0, yy, sw, hh)
                            shear_bg_tmp.blit(tilt_bg_tmp, (dxs, yy), area=src)
                        s_bg3 = shear_bg_tmp.copy()
                        if cache_write_ok:
                            _rc_put(skey, s_bg3)

                    def x_offset_fn(y_screen):
                        try:
                            top = float(bg_blit_dy) + float(shift_y)
                            h = float(tilt_bg_tmp.get_height())
                            if h <= 1.0:
                                return float(shear_eff)
                            rel = (float(y_screen) - top) / h
                            rel = 0.0 if rel < 0.0 else (1.0 if rel > 1.0 else rel)
                            return (1.0 - rel) * float(shear_eff)
                        except Exception:
                            return 0.0

                    # 쉬어로 스프라이트가 화면에서 오른쪽으로 밀리므로, draw()와 동일한 feet_y로 x_offset을 구해 카메라 X를 보정한다.
                    try:
                        recen = bool(CONFIG.get("SHEAR_PLAYER_CENTER_CAM_ENABLED", True))
                    except Exception:
                        recen = True
                    try:
                        anchor_wx, anchor_wy = cam.get_focus_world_point(player, npcs, objs)
                    except Exception:
                        anchor_wx = float(player.pos[0])
                        anchor_wy = float(player.pos[1])
                    if recen and callable(x_offset_fn):
                        # 중요: 렌더용 "중앙 보정"은 cam.pos(시뮬레이션 상태)를 변경하면 누적 오프셋이 생길 수 있다.
                        # 그래서 이 블록에서는 cam.pos를 절대 수정하지 않고, 이번 프레임 렌더에만 cam_origin/cam_draw를 보정한다.
                        try:
                            feet_y_pre = float((float(anchor_wy) - float(cam_draw_y)) * float(z))
                            feet_y2 = float(y_transform(feet_y_pre))
                            dx_off = float(x_offset_fn(float(feet_y2)))
                            if abs(dx_off) > 1e-6:
                                dwc = float(dx_off) / max(1e-6, float(z))
                                cam_center_x = float(cam.pos[0]) + float(dwc)
                                cam_center_y = float(cam.pos[1])
                                cam_origin_x = float(cam_center_x) - float(cam.width) / z / 2.0
                                cam_origin_y = float(cam_center_y) - float(cam.height) / z / 2.0
                                cam_origin_x = round(cam_origin_x * z) / z
                                cam_origin_y = round(cam_origin_y * z) / z
                                bg_dx = int(round((0.0 - cam_origin_x) * z))
                                bg_dy = int(round((0.0 - cam_origin_y) * z))
                                cam_draw_x = -float(bg_dx) / z
                                cam_draw_y = -float(bg_dy) / z
                                if vp_exp_r is not None:
                                    bg_blit_dx = int(round(float(vp_exp_r.x - cam_origin_x) * z))
                                    bg_blit_dy = int(round(float(vp_exp_r.y - cam_origin_y) * z))
                                else:
                                    bg_blit_dx, bg_blit_dy = bg_dx, bg_dy
                                try:
                                    sh_ii = int(shear_eff)
                                except Exception:
                                    sh_ii = 0
                                if vp_exp_r is not None and sh_ii > 0:
                                    blit_x_shear = int(bg_blit_dx) - sh_ii
                                else:
                                    blit_x_shear = int(bg_blit_dx)
                        except Exception:
                            pass

                    render_surf.blit(s_bg3, (int(blit_x_shear), int(round(float(bg_blit_dy) + float(shift_y)))))
                else:
                    render_surf.blit(tilt_bg_tmp, (int(bg_blit_dx), int(round(float(bg_blit_dy) + float(shift_y)))))

            except Exception:
                # (안전) 틸트/쉬어 과정에서 대형 Surface를 의도적으로 생략한 경우도 여기로 들어온다.
                if s_bg is not None:
                    render_surf.blit(s_bg, (bg_blit_dx, bg_blit_dy))
        elif (not bg_direct_fallback) and (not flat_vp_ok) and s_bg is not None:
            render_surf.blit(s_bg, (bg_blit_dx, bg_blit_dy))
        if perf_enabled and t0 is not None:
            _padd("bg", _pnow() - t0)

        # --- 입력 역변환용: "렌더에서 실제로 사용한" 변환 파라미터 캐시 ---
        # 다음 프레임 입력에서 사용(줌+틸트에서도 클릭 좌표가 흔들리지 않게)
        # 입력 역변환에서 shear의 rel(y) 계산에 쓰는 높이.
        # 주의: tilt_bg_tmp는 이전 프레임 잔상이 남을 수 있어(현재 프레임에 틸트를 안 그렸는데도)
        # 그대로 쓰면 클릭 좌표가 틀어질 수 있다. "이번 프레임 렌더에서 실제로 적용된" 변환 기준으로만 선택한다.
        try:
            if callable(y_transform) and (tilt_bg_tmp is not None):
                _shear_h = float(tilt_bg_tmp.get_height())
            else:
                _shear_h = float(bg.get_height()) * float(z)
        except Exception:
            _shear_h = float(CONFIG.get("HEIGHT", 480) or 480)
        try:
            render_xform_for_input = {
                "cam_draw_x": float(cam_draw_x),
                "cam_draw_y": float(cam_draw_y),
                "z": float(z),
                "bg_blit_dy": float(bg_blit_dy),
                "shift_y": float(shift_y),
                "f_q": float(f_q),
                "shear_eff": float(shear_eff),
                "shear_h": float(_shear_h),
                "world_zoom_draw": float(world_zoom_draw) if world_zoom_enabled else 1.0,
                "world_zoom_off_x": float(world_zoom_off_x),
                "world_zoom_off_y": float(world_zoom_off_y),
            }
        except Exception:
            pass

        # --- [2.5] 그네(프로토타입) ---
        # ysort에 포함시키기 위해 "엔티티"로 렌더 풀에 넣는다.
        try:
            if swing_ent is None:
                swing_ent = engine_mod.SwingPrototypeEntity(int(swing_t0_ms))
            swing_ent.swing_t0_ms = int(swing_t0_ms)
            # 그네 타기(데모): 외부에서 진폭을 제어(연타/감쇠)
            if swing_ride_mode in ("approach", "mount", "ride") and swing_ride_theta_amp is not None:
                swing_ent.theta_amp_override = float(swing_ride_theta_amp)
            else:
                swing_ent.theta_amp_override = None
            # 탑승 중엔 그네가 플레이어를 덮지 않게: 그네 레이어를 -1로 내려 항상 뒤에 그린다.
            try:
                swing_ent.layer = (-1 if swing_ride_mode in ("mount", "ride") else 0)
            except Exception:
                pass
            swing_ent.update_sort_pos()
        except Exception:
            swing_ent = None

        # draw 구간 기준 애니 상태 갱신(다음 프레임 churn 판단용)
        last_tilt_draw = float(tilt_current)
        last_shear_draw = float(shear_smoothed)

        # dynamic FPS decision for next frame
        if dyn_fps_on:
            try:
                # 변화 중이거나(zoom/tilt/shear 보간 중), 기능 토글이 켜져 있으면(FX 활성) 낮은 FPS 캡을 사용
                fx_enabled = bool(
                    bool(use_perspective_branch)
                    or bool(getattr(ui, "tilt_bg_demo", False))
                    or bool(getattr(ui, "shear_debug_on", False))
                    or (
                        bool(CONFIG.get("TILT_SHEAR_ENABLED", False))
                        and not bool(getattr(ui, "shear_suppressed", False))
                    )
                )
                fx_active = bool(is_zooming or anim_tilt_draw or anim_shear_draw or fx_enabled)
            except Exception:
                fx_active = False
            fps_cap = int(fps_fx if fx_active else fps_idle)

        # --- [3 & 4. 통합 레이어 시스템 그리기] ---
        # 1. 화면에 그릴 모든 대상을 하나의 리스트로 모읍니다.
        # (손에 들고 있는 아이템은 제외)
        # 성능(핸드헬드): 화면 밖 오브젝트는 draw/정렬에서 제외(컬링)
        # 기본은 OFF (판정 실수로 오브젝트가 사라지는 문제 방지)
        cull_enabled = bool(CONFIG.get("DRAW_CULL_ENABLED", False))
        try:
            cull_pad = int(CONFIG.get("DRAW_CULL_PAD_PX", 96) or 96)
        except Exception:
            cull_pad = 96
        cull_pad = max(0, min(600, cull_pad))
        scr_w = int(CONFIG.get("WIDTH", 640) or 640)
        scr_h = int(CONFIG.get("HEIGHT", 480) or 480)

        def _rough_screen_xy(ent):
            try:
                wx = float(ent.pos[0])
                wy = float(ent.pos[1])
            except Exception:
                return None
            try:
                return _player_feet_screen_xy_like_draw(wx, wy, cam_draw_x, cam_draw_y, z, y_transform, x_offset_fn)
            except Exception:
                try:
                    sx, sy = cam.to_screen(wx, wy)
                except Exception:
                    sx = (wx - float(cam.pos[0])) * float(cam.current_zoom) + float(cam.width) / 2.0
                    sy = (wy - float(cam.pos[1])) * float(cam.current_zoom) + float(cam.height) / 2.0
                return sx, sy

        def _is_visible(ent, extra_pad=0):
            p = _rough_screen_xy(ent)
            if p is None:
                return True
            sx, sy = p
            pad = float(cull_pad) + float(extra_pad or 0)
            return (-pad <= sx <= float(scr_w) + pad) and (-pad <= sy <= float(scr_h) + pad)

        def _is_bg_far(ent):
            if not (bg_zones_norm and ent_bg_zone_idx):
                return False
            if bool(getattr(ent, "is_held", False)):
                return False
            return ent_bg_zone_idx.get(id(ent)) is not None

        # BGZONES: 원경은 y-sort 풀에 넣지 않고, 존 정책대로 별도로 draw
        t_bg_z = _pnow() if perf_detail else None
        if bg_zones_norm and ent_bg_zone_idx:
            try:
                tilt_on_now = bool(tilt_active)
            except Exception:
                tilt_on_now = False
            try:
                from engine import FieldItem as _FieldItemClass
            except Exception:
                _FieldItemClass = FieldItem

            z_order = list(range(len(bg_zones_norm)))
            try:
                z_order.sort(key=lambda zi: int(bg_zones_norm[zi].get("layer", -50)))
            except Exception:
                pass
            for zi in z_order:
                bgz = bg_zones_norm[zi]
                if bgz.get("draw_only_when_tilt", True) and (not tilt_on_now):
                    continue
                extra_pad = int(bgz.get("cull_margin_px", 0) or 0)
                if bgz.get("sort_policy") == "cached" and zi in bg_zone_cached_order:
                    pool = bg_zone_cached_order[zi]
                else:
                    pool = []
                    for ent in list(objs) + list(npcs):
                        if ent_bg_zone_idx.get(id(ent)) != zi:
                            continue
                        if bool(getattr(ent, "is_held", False)):
                            continue
                        pool.append(ent)
                for item in pool:
                    if cull_enabled and (not _is_visible(item, extra_pad=extra_pad)):
                        continue
                    if isinstance(item, _FieldItemClass):
                        item.draw(
                            render_surf,
                            cam_draw_x,
                            cam_draw_y,
                            global_frame=global_anim_timer,
                            zoom=cam.current_zoom,
                            player=player,
                            y_transform=y_transform,
                            x_offset_fn=x_offset_fn,
                            sprite_perspective_q=float(f_q) if callable(y_transform) else None,
                            shear_lod=True,  # 원경은 저비용 우선
                        )
                    else:
                        item.draw(
                            render_surf,
                            cam_draw_x,
                            cam_draw_y,
                            zoom=cam.current_zoom,
                            jump_shadow_mode=flow.save_data.get("jump_shadow_mode", "ground"),
                            y_transform=y_transform,
                            x_offset_fn=x_offset_fn,
                            sprite_perspective_q=float(f_q) if callable(y_transform) else None,
                        )

        if perf_detail and t_bg_z is not None:
            _padd("bg_zones", _pnow() - t_bg_z)

        t_ps = _pnow() if perf_detail else None
        _hi = getattr(player, "held_item", None)

        def _skip_world_obj_draw(o):
            # is_held: Player.draw 손 표시 / is_flying+held_item: fly 중 월드만
            if bool(getattr(o, "is_held", False)):
                return True
            if _hi is o and not bool(getattr(o, "is_flying", False)):
                return True
            return False

        if cull_enabled:
            render_pool = [
                o
                for o in objs
                if (not _skip_world_obj_draw(o)) and (not _is_bg_far(o)) and _is_visible(o)
            ]
            render_pool.extend([c for c in npcs if (not _is_bg_far(c)) and _is_visible(c)])
        else:
            render_pool = [o for o in objs if (not _skip_world_obj_draw(o)) and (not _is_bg_far(o))]
            render_pool.extend([c for c in npcs if not _is_bg_far(c)])
        # 플레이어는 항상 draw
        render_pool.append(player)
        # 그네(좌석+끈)도 하나의 오브젝트처럼 ysort
        if swing_ent is not None:
            render_pool.append(swing_ent)

        def _ysort_y(ent):
            try:
                y = float(ent.pos[1])
            except Exception:
                return 0.0
            mode = str(getattr(ent, "ysort_mode", "ground") or "ground").strip().lower()
            if mode == "visual":
                try:
                    h = float(getattr(ent, "height", 0) or 0)
                except Exception:
                    h = 0.0
                y = y - h
            return y

        # 2. 통합 정렬 (핵심!)
        # - 1순위: layer 숫자 (낮은 게 먼저/아래에 그려짐)
        # - 2순위: pos[1] (Y좌표가 작은 게 먼저/뒤에 그려짐)
        render_list = sorted(render_pool, key=lambda x: (getattr(x, 'layer', 0), _ysort_y(x)))

        if perf_detail and t_ps is not None:
            _padd("obj_pool_sort", _pnow() - t_ps)

        jshadow = flow.save_data.get("jump_shadow_mode", "ground")
        sprite_perspective_q = float(f_q) if callable(y_transform) else None
        # 스프라이트 쉬어 LOD: 원근(줌/틸트/쉬어)이 변하는 동안엔 비용을 크게 줄인다.
        sprite_shear_lod = bool(is_zooming or anim_tilt_draw or anim_shear_draw)
        # 3. 순서대로 그리기
        t0 = _pnow() if perf_enabled else None
        do_topn = draw_topn_enabled and (loop_i % draw_topn_sample_every == 0)
        topn_left = draw_topn_max_items if do_topn else 0
        for item in render_list:
            if do_topn and topn_left > 0:
                t_item0 = _pnow()
            if isinstance(item, FieldItem):
                # player 객체를 인자로 넘겨서 내부에서 layer를 비교하게 합니다.
                item.draw(
                    render_surf,
                    cam_draw_x,
                    cam_draw_y,
                    global_frame=global_anim_timer,
                    zoom=cam.current_zoom,
                    player=player,
                    y_transform=y_transform,
                    x_offset_fn=x_offset_fn,
                    sprite_perspective_q=sprite_perspective_q,
                    shear_lod=sprite_shear_lod,
                )
            else:
                item.draw(
                    render_surf,
                    cam_draw_x,
                    cam_draw_y,
                    zoom=cam.current_zoom,
                    jump_shadow_mode=jshadow,
                    y_transform=y_transform,
                    x_offset_fn=x_offset_fn,
                    sprite_perspective_q=sprite_perspective_q,
                    shear_lod=sprite_shear_lod,
                )
            if do_topn and topn_left > 0:
                dt_ms = (_pnow() - t_item0) * 1000.0
                k = _draw_key(item)
                prev = draw_topn_acc.get(k)
                if prev is None:
                    draw_topn_acc[k] = [dt_ms, 1]
                else:
                    prev[0] += dt_ms
                    prev[1] += 1
                topn_left -= 1

        if perf_enabled and t0 is not None:
            _padd("obj_draw", _pnow() - t0)

        if draw_topn_enabled:
            if now_s - draw_topn_last_dump_t >= draw_topn_dump_every:
                draw_topn_last_dump_t = now_s
                try:
                    items = [(k, v[0], v[1]) for k, v in draw_topn_acc.items() if v and v[1] > 0]
                    items.sort(key=lambda x: x[1], reverse=True)
                    top = items[:8]
                    if top:
                        line = " | ".join([f"{k}:{(ms/max(1,c)):.2f}ms x{c}" for (k, ms, c) in top])
                        print("[DRAW_TOP] " + line)
                        log_line("[DRAW_TOP] " + line)
                except Exception:
                    pass


        # --- [위치 변경] 마스크를 모든 오브젝트보다 위에 그리기 ---
        if ui.show_mask:
            t0 = _pnow() if perf_enabled else None
            # 원래 방식: 전체 마스크를 스케일하여 항상 전부 그린다(캐시 사용)
            mask_direct_fallback = False
            try:
                mw0, mh0 = mask.get_size()
                est_full_mb = _est_rgba_mb(int(round(float(mw0) * float(z))), int(round(float(mh0) * float(z))))
                if est_full_mb > _tmp_surf_mb_limit:
                    mask_direct_fallback = True
            except Exception:
                mask_direct_fallback = False

            mask_no_cache = False

            if mask_direct_fallback:
                # emergency: mask는 생략(보기용 디버그이므로 안전 우선)
                s_mask = None
            else:
                is_zooming = False
                try:
                    is_zooming = abs(float(cam.current_zoom) - float(cam.target_zoom)) > 1e-9
                except Exception:
                    is_zooming = False
                # 주의: _rc_get_full_scale는 공유 캐시 Surface를 돌려줄 수 있으므로 set_alpha로 직접 변형하면 안 된다.
                s_mask0 = _rc_get_full_scale("mask", mask, z, is_zooming=is_zooming)
                akey = ("mask_alpha", id(mask), float(z), 120)
                s_mask = _rc_get(akey)
                if s_mask is None:
                    try:
                        s_mask = s_mask0.copy()
                        s_mask.set_alpha(120)
                    except Exception:
                        s_mask = s_mask0
                    if cache_write_ok and s_mask is not None:
                        _rc_put(akey, s_mask)

            if (s_mask is not None) and (not mask_direct_fallback) and use_perspective_branch and callable(y_transform):
                try:
                    try:
                        tq = float(CONFIG.get("RENDER_TILT_STEP", 0.01))
                    except Exception:
                        tq = 0.01
                    tq = max(0.001, min(0.1, tq))
                    if tilt_active:
                        f = max(tilt_factor_min, min(1.0, float(tilt_current)))
                        f_q = max(tilt_factor_min, min(1.0, round(round(f / tq) * tq, 4)))
                    else:
                        f_q = 1.0

                    key = ("mask_tilt", id(mask), float(cam.current_zoom), float(f_q))
                    s_mask2 = _rc_get(key)
                    if s_mask2 is None:
                        sw, sh = s_mask.get_width(), s_mask.get_height()
                        nh = max(1, int(sh * f_q))
                        # 임시 대형 Surface 생성 방지: 너무 크면 마스크 틸트/쉬어는 그 프레임만 생략(안정 우선)
                        if _est_rgba_mb(sw, nh) > _tmp_surf_mb_limit:
                            render_surf.blit(s_mask, (bg_dx, bg_dy))
                            raise RuntimeError("skip_tilt_mask_large_surface")
                        s_mask2 = pygame.transform.scale(s_mask, (sw, nh))
                        s_mask2.set_alpha(120)
                        if cache_write_ok:
                            _rc_put(key, s_mask2)

                    if tilt_mask_tmp is None or tilt_mask_tmp.get_width() != s_mask2.get_width() or tilt_mask_tmp.get_height() != s_mask2.get_height():
                        tilt_mask_tmp = pygame.Surface((s_mask2.get_width(), s_mask2.get_height()), pygame.SRCALPHA)
                    tilt_mask_tmp.fill((0, 0, 0, 0))
                    tilt_mask_tmp.blit(s_mask2, (0, 0))

                    # 앵커는 렌더 스냅 줌(z) 기준
                    player_sy = float((player.pos[1] - cam_draw_y) * float(z))
                    shift_y = float((player_sy - float(bg_dy)) * (1.0 - float(f_q)))
                    try:
                        slice_h = int(CONFIG.get("TILT_SHEAR_SLICE_H_PX", 8) or 8)
                    except Exception:
                        slice_h = 8
                    slice_h = max(1, min(64, slice_h))

                    sw = int(tilt_mask_tmp.get_width())
                    sh2 = int(tilt_mask_tmp.get_height())
                    if shear_eff > 0:
                        skey = ("mask_shear", id(mask), float(cam.current_zoom), float(f_q), int(shear_eff), int(slice_h))
                        s_mask3 = _rc_get(skey)
                        if s_mask3 is None:
                            out_w = sw + shear_eff
                            if _est_rgba_mb(out_w, sh2) > _tmp_surf_mb_limit:
                                # 쉬어는 생략하고 틸트 마스크만 사용
                                render_surf.blit(tilt_mask_tmp, (int(bg_dx), int(round(float(bg_dy) + float(shift_y)))))
                                raise RuntimeError("skip_shear_mask_large_surface")
                            s_mask3 = pygame.Surface((out_w, sh2), pygame.SRCALPHA)
                            for yy in range(0, sh2, slice_h):
                                hh = min(slice_h, sh2 - yy)
                                rel = 0.0 if sh2 <= 1 else (yy / float(sh2))
                                dxs = int(round((1.0 - rel) * shear_eff))
                                src = pygame.Rect(0, yy, sw, hh)
                                s_mask3.blit(tilt_mask_tmp, (dxs, yy), area=src)
                            s_mask3.set_alpha(120)
                        if cache_write_ok:
                            _rc_put(skey, s_mask3)
                        render_surf.blit(s_mask3, (int(bg_dx), int(round(float(bg_dy) + float(shift_y)))))
                    else:
                        render_surf.blit(tilt_mask_tmp, (int(bg_dx), int(round(float(bg_dy) + float(shift_y)))))
                except Exception:
                    if s_mask is not None:
                        render_surf.blit(s_mask, (bg_dx, bg_dy))
            else:
                if s_mask is not None:
                    render_surf.blit(s_mask, (bg_dx, bg_dy))
            if perf_enabled and t0 is not None:
                _padd("mask", _pnow() - t0)
        # --------------------------------------------------

        # --- 구름 그림자 FX (맵/캐릭터/오브젝트 위에 덮음: 월드에 붙이고 틸트/줌/쉬어와 함께 변형) ---
        fx = getattr(ev_mgr, "cloud_shadow_control", None)
        enabled = bool(CONFIG.get("CLOUD_SHADOW_ENABLED", False))
        dirv = CONFIG.get("CLOUD_SHADOW_DIR", "RANDOM")
        spd = CONFIG.get("CLOUD_SHADOW_SPEED", 22.0)
        frq = CONFIG.get("CLOUD_SHADOW_FREQ", 0.06)
        alp = CONFIG.get("CLOUD_SHADOW_ALPHA", 70)
        sc_min = CONFIG.get("CLOUD_SHADOW_SCALE_MIN", 0.8)
        sc_max = CONFIG.get("CLOUD_SHADOW_SCALE_MAX", 1.4)
        soft = CONFIG.get("CLOUD_SHADOW_SOFTEN", 0.0)
        grid_cell = CONFIG.get("CLOUD_SHADOW_GRID_CELL_PX", 160)
        grid_jitter = CONFIG.get("CLOUD_SHADOW_GRID_JITTER_RATIO", 0.42)
        grid_max = CONFIG.get("CLOUD_SHADOW_GRID_MAX_CLOUDS", 200)
        if isinstance(fx, dict):
            if fx.get("enabled") is False:
                enabled = False
            elif fx.get("enabled") is True:
                enabled = True
            if fx.get("dir") is not None and str(fx.get("dir")).strip() != "":
                dirv = fx.get("dir")
            if fx.get("speed") is not None and fx.get("speed") != "":
                spd = fx.get("speed")
            if fx.get("freq") is not None and fx.get("freq") != "":
                frq = fx.get("freq")
            if fx.get("grid_cell") is not None and str(fx.get("grid_cell")).strip() != "":
                grid_cell = fx.get("grid_cell")
            if fx.get("grid_jitter") is not None and str(fx.get("grid_jitter")).strip() != "":
                grid_jitter = fx.get("grid_jitter")
            if fx.get("grid_max") is not None and str(fx.get("grid_max")).strip() != "":
                grid_max = fx.get("grid_max")
        try:
            bg_w, bg_h = bg.get_size()
        except Exception:
            bg_w, bg_h = CONFIG["WIDTH"], CONFIG["HEIGHT"]
        t0 = _pnow() if perf_enabled else None
        cloud_fx.update_and_draw_world(
            render_surf,
            dt_sec,
            {
                "enabled": enabled,
                "dir": dirv,
                "speed": spd,
                "freq": frq,
                "alpha": alp,
                "scale_min": sc_min,
                "scale_max": sc_max,
                "soften": soft,
                "grid_cell": grid_cell,
                "grid_jitter": grid_jitter,
                "grid_max": grid_max,
            },
            cam_origin_x,
            cam_origin_y,
            cam.current_zoom,
            y_transform=y_transform,
            x_offset_fn=x_offset_fn,
            f_q=f_q if "f_q" in locals() else 1.0,
            map_size=(bg_w, bg_h),
        )
        if perf_enabled and t0 is not None:
            _padd("cloud", _pnow() - t0)

        # [추가] 이펙트 그리기 — FieldItem 과 동일 틸트/쉬어/원근 (ANIM_ONCE 좌표 일치)
        t0 = _pnow() if perf_enabled else None
        for e in ev_mgr.active_effects:
            e.draw(
                render_surf,
                cam_draw_x,
                cam_draw_y,
                zoom=cam.current_zoom,
                y_transform=y_transform,
                x_offset_fn=x_offset_fn,
                sprite_perspective_q=sprite_perspective_q,
                shear_lod=sprite_shear_lod,
            )
        if perf_enabled and t0 is not None:
            _padd("effects", _pnow() - t0)

        # [추가] 클릭 피드백 그리기 (월드에 붙는 표시이므로 월드 렌더에 포함)
        if click_feedback:
            now = pygame.time.get_ticks()
            elapsed = now - click_feedback["start_time"]
            if elapsed < 1000: # 1초 동안 표시
                # 깜빡임 효과 (0.2초 간격)
                if (elapsed // 200) % 2 == 0:
                    # (중요) 마커는 카메라/배경과 같은 좌표계로 계산해야 틸트에서도 "클릭한 자리"에 고정된다.
                    # cam.to_screen은 내부 rounding/중심 기준이 달라 1~수 px 어긋날 수 있어,
                    # 여기서는 draw 루프의 cam_draw_x/y + z 기반으로 직접 계산한다.
                    try:
                        zmk = snap_render_zoom(float(cam.current_zoom))
                    except Exception:
                        zmk = 1.0
                    zmk = max(1e-6, float(zmk))
                    try:
                        wx0, wy0 = float(click_feedback["pos"][0]), float(click_feedback["pos"][1])
                    except Exception:
                        wx0, wy0 = click_feedback["pos"][0], click_feedback["pos"][1]
                    fx = (float(wx0) - float(cam_draw_x)) * zmk
                    fy = (float(wy0) - float(cam_draw_y)) * zmk
                    try:
                        if callable(y_transform):
                            fy = float(y_transform(float(fy)))
                        if callable(x_offset_fn):
                            fx = float(fx) + float(x_offset_fn(float(fy)))
                    except Exception:
                        pass
                    # 줌 배율에 맞춰 크기 조절
                    radius = int(6 * cam.current_zoom)
                    pygame.draw.circle(render_surf, click_feedback["color"], (int(fx), int(fy)), radius, 2)
            else:
                click_feedback = None

        # --- 그네 점프 화살표 FX (월드에 붙는 표시) ---
        # 조건이 발동(파워+최대진폭 근처)이면 그네 오른쪽에 "긴 양방향 화살표"를 계속 표시.
        # 자산: assets/images/fx/swingjumparrow/ (프레임 PNG들)
        if (not ev_mgr.active_event) and swing_ride_mode == "ride":
            st0 = _swing_seat_state()
            show_arrow = False
            if st0 is not None:
                try:
                    dn = float(st0.get("depth_n", 0.0) or 0.0)
                    dpk = float(st0.get("depth_peak_n", 0.0) or 0.0)
                except Exception:
                    dn, dpk = 0.0, 0.0
                try:
                    pth = float(CONFIG.get("SWING_JUMP_POWER_THRESH", 0.75) or 0.75)
                except Exception:
                    pth = 0.75
                try:
                    pkf = float(CONFIG.get("SWING_JUMP_ARROW_SHOW_PEAK_FRAC", 0.82) or 0.82)
                except Exception:
                    pkf = 0.82
                pkf = max(0.1, min(0.999, pkf))
                if float(swing_ride_power) >= float(pth) and float(dpk) > 1e-6:
                    show_arrow = bool(abs(float(dn)) >= float(dpk) * float(pkf))

            if show_arrow and st0 is not None:
                try:
                    wx0, wy0 = float(st0.get("bx_w", 0.0) or 0.0), float(st0.get("by_w", 0.0) or 0.0)
                except Exception:
                    wx0, wy0 = 0.0, 0.0
                try:
                    offx_w = float(CONFIG.get("SWING_JUMP_ARROW_OFFSET_X_PX", 30.0) or 30.0)
                except Exception:
                    offx_w = 30.0
                wx0 = float(wx0) + float(offx_w)
                # screen pos (same math as click marker)
                try:
                    zmk = snap_render_zoom(float(cam.current_zoom))
                except Exception:
                    zmk = 1.0
                zmk = max(1e-6, float(zmk))
                fx = (float(wx0) - float(cam_draw_x)) * zmk
                fy = (float(wy0) - float(cam_draw_y)) * zmk
                try:
                    if callable(y_transform):
                        fy = float(y_transform(float(fy)))
                    if callable(x_offset_fn):
                        fx = float(fx) + float(x_offset_fn(float(fy)))
                except Exception:
                    pass

                # lazy load frames
                if "_swing_jump_arrow_frames" not in locals():
                    _swing_jump_arrow_frames = None
                    _swing_jump_arrow_dir = None
                if _swing_jump_arrow_frames is None:
                    try:
                        pdir = str(CONFIG.get("SWING_JUMP_ARROW_FX_DIR", "assets/images/fx/swingjumparrow") or "").strip()
                    except Exception:
                        pdir = "assets/images/fx/swingjumparrow"
                    _swing_jump_arrow_dir = pdir
                    try:
                        _swing_jump_arrow_frames = engine_mod._load_anim_dir_cached(pdir)
                    except Exception:
                        _swing_jump_arrow_frames = None

                img = None
                if _swing_jump_arrow_frames:
                    try:
                        idx = int(pygame.time.get_ticks() // 90) % len(_swing_jump_arrow_frames)
                        img = _swing_jump_arrow_frames[idx]
                    except Exception:
                        img = _swing_jump_arrow_frames[0]

                if img is not None:
                    # asset이 있으면 그대로(간단하게) 표시하되, 위치는 우측 고정
                    try:
                        sc = max(0.5, min(3.0, float(cam.current_zoom)))
                    except Exception:
                        sc = 1.0
                    try:
                        iw, ih = img.get_width(), img.get_height()
                        tw, th = int(round(iw * sc)), int(round(ih * sc))
                        if tw != iw or th != ih:
                            img2 = pygame.transform.scale(img, (max(1, tw), max(1, th)))
                        else:
                            img2 = img
                    except Exception:
                        img2 = img
                    try:
                        ox = int(round(float(fx) - float(img2.get_width()) / 2.0))
                        oy = int(round(float(fy) - float(img2.get_height()) / 2.0))
                    except Exception:
                        ox, oy = int(fx), int(fy)
                    render_surf.blit(img2, (ox, oy))
                else:
                    # fallback: draw a long double-headed vertical arrow
                    try:
                        col = (255, 255, 0)
                        x = int(round(float(fx)))
                        y = int(round(float(fy)))
                        try:
                            ah = float(CONFIG.get("SWING_JUMP_ARROW_HEIGHT_PX", 80.0) or 80.0)
                        except Exception:
                            ah = 80.0
                        ah = max(24.0, min(240.0, ah))
                        h2 = int(round(ah / 2.0))
                        y0 = int(y - h2)
                        y1 = int(y + h2)
                        pygame.draw.line(render_surf, col, (x, y0), (x, y1), 3)
                        # up head
                        pygame.draw.polygon(render_surf, col, [(x - 8, y0 + 10), (x + 8, y0 + 10), (x, y0 - 2)])
                        # down head
                        pygame.draw.polygon(render_surf, col, [(x - 8, y1 - 10), (x + 8, y1 - 10), (x, y1 + 2)])
                    except Exception:
                        pass

        # --- 이벤트 존(contact_confirm) "클릭 가능" 프롬프트 (pushbutton 애니) ---
        # 조건: 플레이어가 존 안에 있고(위치+조건), trigger가 contact_confirm인 박스.
        # 클릭을 기다리는 박스들(1번 더 눌러야 발동)임을 UX로 알려준다.
        try:
            zprompt_on = bool(CONFIG.get("ZONE_CONFIRM_PROMPT_ENABLED", True))
        except Exception:
            zprompt_on = True
        # 이벤트가 발동되어 진행 중일 땐(대사/스크린 포함) 프롬프트를 숨긴다.
        if (
            zprompt_on
            and (not ev_mgr.active_event)
            and (not bool(getattr(ev_mgr, "is_busy", False)))
            and (not bool(getattr(ev_mgr, "is_talking", False)))
            and (not bool(getattr(ev_mgr, "active_screen", None)))
            # 그네 타기(approach/mount/ride)는 이벤트처럼 동작하므로 프롬프트를 숨긴다.
            and (swing_ride_mode not in ("approach", "mount", "ride"))
        ):
            m_data = flow.world_data.get(map_id, {}) if flow is not None else {}
            zones = m_data.get("event_zones", []) if isinstance(m_data, dict) else []
            if zones:
                # lazy load frames
                if "_zone_prompt_frames" not in locals():
                    _zone_prompt_frames = None
                    _zone_prompt_paths = None
                if _zone_prompt_frames is None:
                    try:
                        pre = str(CONFIG.get("ZONE_CONFIRM_PROMPT_PREFIX", "assets/images/ui/pushbutton") or "").strip()
                    except Exception:
                        pre = "assets/images/ui/pushbutton"
                    try:
                        nfr = int(CONFIG.get("ZONE_CONFIRM_PROMPT_FRAMES", 4) or 4)
                    except Exception:
                        nfr = 4
                    nfr = max(1, min(32, nfr))
                    _zone_prompt_paths = [f"{pre}{i}.png" for i in range(int(nfr))]
                    frs = []
                    for p in _zone_prompt_paths:
                        try:
                            img = engine_mod._load_image_cached(p)
                            if img is not None:
                                frs.append(img)
                        except Exception:
                            pass
                    _zone_prompt_frames = frs if frs else None

                img = None
                if _zone_prompt_frames:
                    try:
                        fms = int(CONFIG.get("ZONE_CONFIRM_PROMPT_FRAME_MS", 110) or 110)
                    except Exception:
                        fms = 110
                    fms = max(40, min(600, fms))
                    try:
                        idx = int(pygame.time.get_ticks() // int(fms)) % len(_zone_prompt_frames)
                        img = _zone_prompt_frames[idx]
                    except Exception:
                        img = _zone_prompt_frames[0]

                if img is not None:
                    # 현재 프레임에서 조건이 만족하는 존들(너무 많으면 상한)
                    try:
                        offy = float(CONFIG.get("ZONE_CONFIRM_PROMPT_OFFSET_Y_PX", -6) or -6)
                    except Exception:
                        offy = -6.0
                    try:
                        mp = str(flow.save_data.get("mainprogress", "") or "")
                    except Exception:
                        mp = ""
                    try:
                        lp = int(flow.save_data.get("laugh_point", 0) or 0)
                    except Exception:
                        lp = 0

                    shown = 0
                    for z0 in zones:
                        if shown >= 6:
                            break
                        try:
                            if str(z0.get("trigger", "contact")).strip() != "contact_confirm":
                                continue
                            zx, zy, zw, zh = z0.get("rect") or (0, 0, 0, 0)
                            zx, zy, zw, zh = float(zx), float(zy), float(zw), float(zh)
                        except Exception:
                            continue
                        # inside zone?
                        try:
                            if not (zx <= float(player.pos[0]) <= zx + zw and zy <= float(player.pos[1]) <= zy + zh):
                                continue
                        except Exception:
                            continue
                        # conditions (match flow.check_zone_trigger)
                        cond = z0.get("conditions", {}) if isinstance(z0.get("conditions", {}), dict) else {}
                        try:
                            if cond.get("mainprogress") and str(cond.get("mainprogress")) != str(mp):
                                continue
                        except Exception:
                            pass
                        try:
                            if "min_laugh_point" in cond and int(lp) < int(cond.get("min_laugh_point") or 0):
                                continue
                        except Exception:
                            pass

                        cxw = zx + zw * 0.5
                        cyw = zy + zh * 0.5 + float(offy)
                        # screen pos (same math as click marker)
                        try:
                            zmk = snap_render_zoom(float(cam.current_zoom))
                        except Exception:
                            zmk = 1.0
                        zmk = max(1e-6, float(zmk))
                        fx = (float(cxw) - float(cam_draw_x)) * zmk
                        fy = (float(cyw) - float(cam_draw_y)) * zmk
                        try:
                            if callable(y_transform):
                                fy = float(y_transform(float(fy)))
                            if callable(x_offset_fn):
                                fx = float(fx) + float(x_offset_fn(float(fy)))
                        except Exception:
                            pass
                        # 존 클릭 FX: 말풍선과 동일하게 논리 px = 에셋 px (이중 스케일 없음)
                        try:
                            sc = float(ui_layout_scale())
                        except Exception:
                            sc = 1.0
                        try:
                            iw, ih = img.get_width(), img.get_height()
                            if abs(sc - 1.0) > 1e-6:
                                tw, th = int(round(iw * sc)), int(round(ih * sc))
                                img2 = pygame.transform.scale(img, (max(1, tw), max(1, th)))
                            else:
                                img2 = img
                        except Exception:
                            img2 = img
                        try:
                            ox = int(round(float(fx) - float(img2.get_width()) / 2.0))
                            oy = int(round(float(fy) - float(img2.get_height()) / 2.0))
                        except Exception:
                            ox, oy = int(fx), int(fy)
                        render_surf.blit(img2, (ox, oy))
                        shown += 1

        # --- 월드 줌(후처리) 합성: world_surf -> draw_surf ---
        # 오버레이(UI)는 줌 영향을 받지 않으므로, 여기서만 스케일한다.
        t_wz0 = _pnow() if perf_enabled else None
        render_surf = draw_surf
        try:
            lw_i = int(CONFIG["WIDTH"])
            lh_i = int(CONFIG["HEIGHT"])
        except Exception:
            lw_i, lh_i = 320, 240
        render_surf.fill((30, 30, 30))
        if (not world_zoom_enabled) or abs(float(world_zoom_draw) - 1.0) <= 1e-6:
            t_wz_bl0 = _pnow() if perf_detail else None
            render_surf.blit(world_surf, (0, 0))
            if perf_detail and t_wz_bl0 is not None:
                _padd("wz_blit", _pnow() - t_wz_bl0)
            # 입력 역변환 캐시도 "실제 합성 결과" 기준으로 확정
            try:
                if render_xform_for_input is not None:
                    render_xform_for_input["world_zoom_draw"] = 1.0
                    render_xform_for_input["world_zoom_off_x"] = 0.0
                    render_xform_for_input["world_zoom_off_y"] = 0.0
            except Exception:
                pass
        else:
            zf = max(1e-6, float(world_zoom_draw))
            sw_i = max(1, int(round(float(lw_i) * zf)))
            sh_i = max(1, int(round(float(lh_i) * zf)))
            if world_zoom_tmp is None or world_zoom_tmp.get_width() != sw_i or world_zoom_tmp.get_height() != sh_i:
                world_zoom_tmp = pygame.Surface((sw_i, sh_i))
            t_wz_sc0 = _pnow() if perf_detail else None
            try:
                pygame.transform.scale(world_surf, (sw_i, sh_i), world_zoom_tmp)
            except Exception:
                world_zoom_tmp = pygame.transform.scale(world_surf, (sw_i, sh_i))
            if perf_detail and t_wz_sc0 is not None:
                _padd("wz_scale", _pnow() - t_wz_sc0)
            # 렌더링 시점: cam.to_screen(cam.pos)은 쉬어 "렌더 전용" cam_draw 보정을 모름 → 앵커가 어긋난다.
            try:
                z_anchor_x, z_anchor_y = cam.get_focus_world_point(player, npcs, objs)
                ax, ay = _player_feet_screen_xy_like_draw(
                    float(z_anchor_x),
                    float(z_anchor_y),
                    float(cam_draw_x),
                    float(cam_draw_y),
                    float(z),
                    y_transform,
                    x_offset_fn,
                )
            except Exception:
                ax, ay = float(lw_i) * 0.5, float(lh_i) * 0.5
            world_zoom_off_x = ax * (1.0 - zf)
            world_zoom_off_y = ay * (1.0 - zf)
            # 입력 역변환 캐시도 "실제 합성 결과" 기준으로 확정
            try:
                if render_xform_for_input is not None:
                    render_xform_for_input["world_zoom_draw"] = float(zf)
                    render_xform_for_input["world_zoom_off_x"] = float(world_zoom_off_x)
                    render_xform_for_input["world_zoom_off_y"] = float(world_zoom_off_y)
            except Exception:
                pass
            bx = int(round(float(world_zoom_off_x)))
            by = int(round(float(world_zoom_off_y)))
            t_wz_bl0 = _pnow() if perf_detail else None
            render_surf.blit(world_zoom_tmp, (bx, by))
            if perf_detail and t_wz_bl0 is not None:
                _padd("wz_blit", _pnow() - t_wz_bl0)
        if perf_enabled and t_wz0 is not None:
            _padd("world_zoom", _pnow() - t_wz0)

        # [추가] SCREEN 오버레이 (인트로/슬라이드)
        t0 = _pnow() if perf_enabled else None
        ev_mgr.draw_screen_overlay(render_surf)
        if perf_enabled and t0 is not None:
            _padd("overlay", _pnow() - t0)

        t_ui = _pnow() if perf_enabled else None
        try:
            head_ctx = {
                "cam_draw_x": float(cam_draw_x),
                "cam_draw_y": float(cam_draw_y),
                "z": float(z),
                "y_transform": y_transform,
                "x_offset_fn": x_offset_fn,
                "f_q": float(f_q),
                "world_zoom_draw": float(world_zoom_draw) if world_zoom_enabled else 1.0,
                "world_zoom_off_x": float(world_zoom_off_x),
                "world_zoom_off_y": float(world_zoom_off_y),
                "player": player,
                "npcs": npcs,
                "objs": objs,
            }
        except Exception:
            head_ctx = None
        ev_mgr.draw_ui_overlays(render_surf, head_ctx)
        if perf_enabled and t_ui is not None:
            _padd("ui_overlay", _pnow() - t_ui)

        # 월드 후단: 페이드·대화·디버그 블릿·존 박스·커서 등(overlay 화면연출과 구분)
        t_wtail0 = _pnow() if perf_detail else None

        # [추가] 4.5 페이드 효과 (모든 물체 위에, UI 아래에 덮음)
        if ev_mgr.fade_alpha > 0:
            fade_overlay_surf.fill((0, 0, 0))
            fade_overlay_surf.set_alpha(ev_mgr.fade_alpha)
            render_surf.blit(fade_overlay_surf, (0, 0))
            
        

        # (레거시) 대화창 UI
        if bool(CONFIG.get("SAY_DEBUG_LEGACY_BOX", False)) and ui.show_overlay_text and ev_mgr.is_talking:
            try:
                _dlg_sw = int(CONFIG["WIDTH"])
                _dlg_sh = int(CONFIG["HEIGHT"])
            except Exception:
                _dlg_sw, _dlg_sh = 640, 480
            _dlg_m = int(round(scale_ui_text_px(50, screen_w=_dlg_sw)))
            _dlg_h = int(round(scale_ui_text_px(100, screen_w=_dlg_sw)))
            _dlg_top = int(round(scale_ui_text_px(130, screen_w=_dlg_sw)))
            _dlg_tx = int(round(scale_ui_text_px(70, screen_w=_dlg_sw)))
            _dlg_ty1 = _dlg_sh - int(round(scale_ui_text_px(120, screen_w=_dlg_sw)))
            _dlg_ty2 = _dlg_sh - int(round(scale_ui_text_px(95, screen_w=_dlg_sw)))
            dialog_rect = pygame.Rect(
                _dlg_m, _dlg_sh - _dlg_top, max(1, _dlg_sw - _dlg_m * 2), _dlg_h
            )
            pygame.draw.rect(render_surf, (0, 0, 0, 200), dialog_rect)
            pygame.draw.rect(render_surf, (255, 255, 255), dialog_rect, 2)
            render_surf.blit(font.render(ev_mgr.current_who, True, (255, 255, 0)), (_dlg_tx, _dlg_ty1))
            render_surf.blit(font.render(ev_mgr.current_text, True, (255, 255, 255)), (_dlg_tx, _dlg_ty2))

        # 디버그/오버레이 텍스트는 1초에 1번만 갱신해서 비용을 줄인다.
        now_ov = time.time()
        if now_ov - overlay_last_update_t >= overlay_update_interval:
            t_ob0 = _pnow() if perf_detail else None
            overlay_last_update_t = now_ov
            overlay_cache["rss_mb"] = rss_mb()
            try:
                cs = engine_mod.cache_estimated_mb()
            except Exception:
                cs = None

            if cache_stats_enabled:
                try:
                    cam_cache = getattr(cam, "image_cache", {}) if cam is not None else {}
                except Exception:
                    cam_cache = {}
                try:
                    cloud_cache = getattr(cloud_fx, "_render_cache", {}) if cloud_fx is not None else {}
                except Exception:
                    cloud_cache = {}
                try:
                    cam_n = len(cam_cache) if isinstance(cam_cache, dict) else 0
                except Exception:
                    cam_n = 0
                try:
                    bg_n = len(bg_scale_cache)
                except Exception:
                    bg_n = 0
                try:
                    mask_n = len(mask_scale_cache)
                except Exception:
                    mask_n = 0
                try:
                    sh_n = len(shear_cache)
                except Exception:
                    sh_n = 0
                try:
                    cl_n = len(cloud_cache) if isinstance(cloud_cache, dict) else 0
                except Exception:
                    cl_n = 0

                cam_mb = _cache_est_mb(cam_cache) if isinstance(cam_cache, dict) else 0.0
                bg_mb = _cache_est_mb(bg_scale_cache)
                mask_mb = _cache_est_mb(mask_scale_cache)
                sh_mb = _cache_est_mb(shear_cache)
                cl_mb = _cache_est_mb(cloud_cache) if isinstance(cloud_cache, dict) else 0.0
                total_mb = cam_mb + bg_mb + mask_mb + sh_mb + cl_mb

                cache_text = f"CACHE cam:{cam_n} bgT:{bg_n} maskT:{mask_n} sh:{sh_n} cl:{cl_n} (~{total_mb:.0f}MB)"
                if cache_text != overlay_cache.get("cache_text", ""):
                    overlay_cache["cache_text"] = cache_text
                    try:
                        overlay_cache["cache_surf"] = font.render(cache_text, True, (240, 240, 210))
                    except Exception:
                        overlay_cache["cache_surf"] = None
                if cache_stats_log:
                    log_line(cache_text)

            # 성능(두번째 줄): frame(전체) - fps_pace_ms(루프 맨 위 clock.tick 구간, FPS 캡 대기 포함) ≈ 나머지 작업(ms)
            # - fps_pace_ms는 대기 시간이 크게 잡힐 수 있음(30fps면 ~33ms 근처가 정상일 수 있음)
            # - frame은 루프 전체(대기 포함). 둘을 분리해 "이 장면에서 가능한 처리량"을 추정한다.
            perf_line = ""
            try:
                f_arr = perf_buf.get("frame") or []
                t_arr = perf_buf.get("fps_pace_ms") or []
                if f_arr and t_arr:
                    f_ms = float(statistics.median(f_arr))
                    t_ms = float(statistics.median(t_arr))
                    cpu_ms = max(0.0, f_ms - t_ms)
                    fps_cap = 1000.0 / max(1e-3, cpu_ms) if cpu_ms > 0.05 else 999.0
                    use = cpu_ms / 16.666 if cpu_ms > 0 else 0.0
                    # 짧게: CPUms / approxFPS / 60fps 대비 배수
                    perf_line = f"PERF CPU:{cpu_ms:.1f}ms ~{fps_cap:.0f}fps ({use:.2f}x)"
            except Exception:
                perf_line = ""
            if perf_line != overlay_cache.get("perf_text", ""):
                overlay_cache["perf_text"] = perf_line
                if perf_line:
                    try:
                        overlay_cache["perf_surf"] = font.render(perf_line, True, (210, 235, 255))
                    except Exception:
                        overlay_cache["perf_surf"] = None
                else:
                    overlay_cache["perf_surf"] = None

            if ui.show_overlay_text:
                try:
                    fps_show = int(round(float(clock.get_fps())))
                except Exception:
                    fps_show = 0
                debug_text = (
                    f"FPS: {fps_show} | Pos: ({int(player.pos[0])}, {int(player.pos[1])})"
                )
                if overlay_cache["rss_mb"] is not None:
                    debug_text += f" | RSS:{float(overlay_cache['rss_mb']):.0f}MB"
                if isinstance(cs, dict):
                    try:
                        debug_text += f" | IMG:{int(cs.get('img_count',0))} (~{float(cs.get('img_est_mb',0.0)):.0f}MB)"
                    except Exception:
                        pass
                if debug_text != overlay_cache.get("debug_text", ""):
                    overlay_cache["debug_text"] = debug_text
                    try:
                        overlay_cache["debug_surf"] = font.render(debug_text, True, (255, 255, 255))
                    except Exception:
                        overlay_cache["debug_surf"] = None

                bgm = music_mgr.get_title()
                bgm_text = f"BGM: {bgm}" if bgm else ""
                if bgm_text != overlay_cache.get("bgm_text", ""):
                    overlay_cache["bgm_text"] = bgm_text
                    if bgm_text:
                        try:
                            overlay_cache["bgm_surf"] = font.render(bgm_text, True, (220, 220, 235))
                        except Exception:
                            overlay_cache["bgm_surf"] = None
                    else:
                        overlay_cache["bgm_surf"] = None
            else:
                # overlay_text가 꺼져 있어도 RSS는 간단히 표시(갱신은 동일하게 1초 간격)
                if overlay_cache["rss_mb"] is not None:
                    rss_text = f"RSS {float(overlay_cache['rss_mb']):.0f}MB"
                else:
                    rss_text = ""
                if rss_text != overlay_cache.get("rss_text", ""):
                    overlay_cache["rss_text"] = rss_text
                    if rss_text:
                        try:
                            overlay_cache["rss_surf"] = font.render(rss_text, True, (255, 255, 255))
                        except Exception:
                            overlay_cache["rss_surf"] = None
                    else:
                        overlay_cache["rss_surf"] = None

            if perf_detail and t_ob0 is not None:
                _padd("overlay_build", _pnow() - t_ob0)

        # 디버그 정보 표시(렌더는 매 프레임, 텍스트 생성/렌더만 1초에 1번)
        if ui.show_overlay_text:
            try:
                _ov_x = max(4, int(CONFIG["WIDTH"]) - int(round(300.0 * float(CONFIG["WIDTH"]) / 640.0)))
            except Exception:
                _ov_x = 20
            try:
                _ov_bgm_y = int(CONFIG["HEIGHT"]) - int(round(scale_ui_text_px(28, screen_w=int(CONFIG["WIDTH"]))))
            except Exception:
                _ov_bgm_y = int(CONFIG["HEIGHT"]) - 28
            if overlay_cache.get("debug_surf") is not None:
                render_surf.blit(overlay_cache["debug_surf"], (_ov_x, 20))
            if overlay_cache.get("perf_surf") is not None:
                render_surf.blit(overlay_cache["perf_surf"], (_ov_x, 34))
            if overlay_cache.get("cache_surf") is not None:
                render_surf.blit(overlay_cache["cache_surf"], (_ov_x, 48))
            if overlay_cache.get("bgm_surf") is not None:
                render_surf.blit(overlay_cache["bgm_surf"], (int(round(scale_ui_text_px(70, screen_w=int(CONFIG["WIDTH"])))), _ov_bgm_y))
        else:
            if bool(CONFIG.get("SHOW_RSS_OVERLAY_WHEN_OFF", False)):
                if overlay_cache.get("rss_surf") is not None:
                    render_surf.blit(overlay_cache["rss_surf"], (6, 6))
        
        if ui.show_camera_focus:
            try:
                fwx, fwy = cam.get_focus_world_point(player, npcs, objs)
            except Exception:
                try:
                    fwx, fwy = float(cam.pos[0]), float(cam.pos[1])
                except Exception:
                    fwx, fwy = 0.0, 0.0
            try:
                _fsx, _fsy = _player_feet_screen_xy_like_draw(
                    float(fwx),
                    float(fwy),
                    float(cam_draw_x),
                    float(cam_draw_y),
                    float(z),
                    y_transform,
                    x_offset_fn,
                )
                _zf = float(world_zoom_draw) if world_zoom_enabled else 1.0
                _zf = max(1e-6, float(_zf))
                _fsx = float(_fsx) * _zf + float(world_zoom_off_x)
                _fsy = float(_fsy) * _zf + float(world_zoom_off_y)
                _fpx, _fpy = int(round(_fsx)), int(round(_fsy))
                _fr = max(3, int(round(4.0 * _zf)))
                pygame.draw.circle(render_surf, (0, 220, 0), (_fpx, _fpy), _fr)
                pygame.draw.circle(render_surf, (255, 255, 255), (_fpx, _fpy), _fr, 1)
            except Exception:
                pass

        if ui.show_mask:  # 변수명 z는 위쪽 렌더 줌과 충돌하므로 zone 사용
            m_data = flow.world_data.get(map_id, {})
            for zone in m_data.get("event_zones", []):
                zx, zy, zw, zh = zone["rect"]
                # 월드 좌표를 카메라 화면 좌표로 변환
                screen_pos = cam.to_screen(zx, zy)
                # 새 월드 줌(후처리)까지 반영: 이 디버그 박스는 월드에 붙어 있어야 한다.
                try:
                    zf = float(world_zoom_draw) if world_zoom_enabled else 1.0
                except Exception:
                    zf = 1.0
                zf = max(1e-6, zf)
                sx = float(screen_pos[0]) * zf + float(world_zoom_off_x)
                sy = float(screen_pos[1]) * zf + float(world_zoom_off_y)
                rect_w = float(zw) * zf
                rect_h = float(zh) * zf

                # 투명한 보라색 사각형 그리기 (Rect는 정수여야 함)
                debug_rect = pygame.Rect(int(sx), int(sy), int(rect_w), int(rect_h))
                pygame.draw.rect(render_surf, (255, 0, 255), debug_rect, 2)  # 보라색 테두리

                # 이벤트 ID 이름도 표시
                zid = str(zone.get("event_id", "EV") or "EV")
                label = overlay_cache["zone_labels"].get(zid)
                if label is None:
                    try:
                        label = font.render(zid, True, (255, 0, 255))
                    except Exception:
                        label = None
                    overlay_cache["zone_labels"][zid] = label
                render_surf.blit(label, (sx, sy - 20))
        
        # 커서(포인트): 이벤트 스텝의 cursor_visible 토글을 존중한다.
        # rg35xxsp용 표시: 빨간색 2x2 픽셀 사각형.
        try:
            cx, cy = int(ui_cursor[0]), int(ui_cursor[1])
        except Exception:
            cx, cy = ui_cursor[0], ui_cursor[1]
        if bool(getattr(ev_mgr, "cursor_visible", True)):
            try:
                cur_sz = int(CONFIG.get("UI_CURSOR_SIZE", 6) or 6)
            except Exception:
                cur_sz = 6
            cur_sz = max(2, min(32, cur_sz))
            half = cur_sz // 2
            # 가운데 정렬(커서 좌표를 중심으로)
            rx = int(cx) - half
            ry = int(cy) - half
            pygame.draw.rect(render_surf, (255, 0, 0), pygame.Rect(rx, ry, cur_sz, cur_sz))
            # 외곽선으로 가시성 강화
            pygame.draw.rect(render_surf, (0, 0, 0), pygame.Rect(rx - 1, ry - 1, cur_sz + 2, cur_sz + 2), 1)

        if perf_detail and t_wtail0 is not None:
            _padd("world_tail", _pnow() - t_wtail0)

        # 최종 프레임: 논리 해상도(draw_surf) → 물리 화면(screen)
        # NATIVE_640(scale_factor==1)에서도 draw_surf는 별도 Surface이므로 반드시 blit해야 한다.
        t_pr0 = _pnow() if perf_enabled else None
        _present_draw_surf_to_screen(
            screen, draw_surf, scale_factor=scale_factor, present_tmp=present_scale_tmp
        )
        if perf_enabled and t_pr0 is not None:
            _padd("present", _pnow() - t_pr0)

        if perf_enabled and t_render0 is not None:
            _padd("render_cpu", _pnow() - t_render0)

        t0 = _pnow() if perf_enabled else None
        pygame.display.flip()
        # 다음 해상도 전환 시 바로 보여줄 수 있도록 마지막 논리 프레임 저장
        try:
            last_frame_logical = draw_surf.copy()
        except Exception:
            last_frame_logical = None
        if perf_enabled and t0 is not None:
            _padd("flip", _pnow() - t0)

        # fixed timestep에서는 이미 루프 시작에서 FPS 캡을 걸었으므로 여기서 tick()을 또 호출하면
        # 다음 프레임의 dt_real_ms가 0에 가까워져 sim_steps가 망가지고(=게임 속도가 느려짐) stutter가 생긴다.

        if perf_enabled and t_frame0 is not None:
            _padd("frame", _pnow() - t_frame0)
            perf_frame_i += 1
            if (perf_frame_i - perf_last_dump) >= perf_print_every:
                perf_last_dump = perf_frame_i
                _pdump()

    flow.save_game(map_id, player.pos)
    pygame.quit()

if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        log_line("=== crash ===")
        for ln in tb.splitlines():
            log_line(ln)
        raise
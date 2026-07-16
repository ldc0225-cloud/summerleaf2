"""야구 점수 구역 — 맵에 누운 오브젝트(sprite_tilt≈0)로 배치, 공 착지 위치에 규칙 적용.

에디터(BASEBALL 모드)와 activities/baseball.py 가 공유.
world_data objects 항목 예:
  {"name":"bbzone_x2","pos":[x,y],"sprite_tilt":0,"baseball_zone":{"mode":"mul","value":2.0,"label":"×2"}}
object_defs.json 타입 기본값과 인스턴스 baseball_zone 을 병합.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

ZoneHit = Tuple[float, bool, str]  # (carry_px, is_foul, label)


def _safe_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def zone_spec_from_parts(
    obj_name: str,
    obj_def: Optional[dict],
    world_row: Optional[dict],
) -> Optional[dict]:
    """타입 기본 + 맵 인스턴스 baseball_zone 병합."""
    base: Dict[str, Any] = {}
    if isinstance(obj_def, dict):
        bz = obj_def.get("baseball_zone")
        if isinstance(bz, dict):
            base.update(dict(bz))
    if isinstance(world_row, dict):
        bz = world_row.get("baseball_zone")
        if isinstance(bz, dict):
            base.update(dict(bz))
    if not base and not str(obj_name or "").startswith("bbzone_"):
        return None
    mode = str(base.get("mode") or "mul").strip().lower()
    name = str(obj_name or "")
    def_rx, def_ry, _def_col = zone_type_defaults(name, obj_def)
    spec = {
        "mode": mode,
        "value": _safe_float(base.get("value"), 1.0),
        "label": str(base.get("label") or "").strip(),
        "name": name,
        "radius_x": _safe_float(base.get("radius_x"), def_rx),
        "radius_y": _safe_float(base.get("radius_y"), def_ry),
    }
    col = base.get("color")
    if isinstance(col, (list, tuple)) and len(col) >= 3:
        spec["color"] = [int(col[0]), int(col[1]), int(col[2]), int(col[3]) if len(col) > 3 else 100]
    if mode in ("mul", "add_px", "add_m", "set_foul", "foul"):
        render = str(base.get("render") or "ellipse").strip().lower()
        spec["render"] = render
        return spec
    return None


def zone_render_mode(o) -> str:
    spec = zone_spec_from_object(o) or {}
    return str(spec.get("render") or "ellipse").strip().lower()


def zone_uses_ellipse_fallback(o) -> bool:
    if not is_baseball_zone_object(o):
        return False
    mode = zone_render_mode(o)
    if mode in ("sprite", "image", "png"):
        od = getattr(o, "obj_def", None) or {}
        return not zone_asset_image_exists(getattr(o, "name", ""), od)
    return True


def zone_spec_from_object(o) -> Optional[dict]:
    obj_def = getattr(o, "obj_def", None) or {}
    we = getattr(o, "_world_entry", None) or {}
    return zone_spec_from_parts(getattr(o, "name", ""), obj_def, we)


def is_baseball_zone_object(o) -> bool:
    return zone_spec_from_object(o) is not None


def is_scoreboard_object(o) -> bool:
    nm = str(getattr(o, "name", "") or "")
    if nm.startswith("bbscoreboard"):
        return True
    od = getattr(o, "obj_def", None) or {}
    return bool(od.get("baseball_scoreboard"))


def scoreboard_default_zoom(obj_def: Optional[dict] = None) -> float:
    if isinstance(obj_def, dict):
        style = obj_def.get("scoreboard_style") or {}
        z = obj_def.get("scoreboard_zoom", style.get("zoom", obj_def.get("zoom")))
        if z is not None:
            return max(0.25, _safe_float(z, 1.75))
    return 1.75


def scoreboard_style_from_object(o) -> Dict[str, Any]:
    od = getattr(o, "obj_def", None) or {}
    we = getattr(o, "_world_entry", None) or {}
    style = {
        "use_image": True,
        "alpha": 200,
        "show_corner_label": True,
        "corner_label": "",
        "border_color": [210, 255, 220],
        "fill_color": [24, 48, 40],
    }
    if isinstance(od.get("scoreboard_style"), dict):
        style.update(dict(od.get("scoreboard_style") or {}))
    if isinstance(we.get("scoreboard_style"), dict):
        style.update(dict(we.get("scoreboard_style") or {}))
    style["use_image"] = bool(style.get("use_image", True))
    style["show_corner_label"] = bool(style.get("show_corner_label", True))
    style["corner_label"] = str(style.get("corner_label") or "").strip()
    style["alpha"] = max(0, min(255, int(_safe_float(style.get("alpha"), 200))))
    return style


def scoreboard_zoom_from_object(o) -> float:
    we = getattr(o, "_world_entry", None) or {}
    if isinstance(we, dict) and we.get("scoreboard_zoom") is not None:
        return max(0.25, _safe_float(we.get("scoreboard_zoom"), 1.75))
    od = getattr(o, "obj_def", None) or {}
    return scoreboard_default_zoom(od if isinstance(od, dict) else None)


def apply_scoreboard_defaults(o) -> None:
    """전광판은 bbzone과 달리 서 있는 일반 오브젝트."""
    from data import OBJ_ASSETS

    od = getattr(o, "obj_def", None) or OBJ_ASSETS.get(getattr(o, "name", ""), {}) or {}
    if not isinstance(getattr(o, "obj_def", None), dict) or not o.obj_def:
        o.obj_def = dict(od)
    o.sprite_tilt = 1.0
    o.ysort_mode = str(od.get("ysort", "ground") or "ground")
    o.is_visible = bool(scoreboard_style_from_object(o).get("use_image", True))
    o.entity_def_zoom = scoreboard_zoom_from_object(o)
    if getattr(o, "layer", None) is None:
        o.layer = 1
    we = getattr(o, "_world_entry", None)
    if not isinstance(we, dict):
        we = {}
        o._world_entry = we
    we["sprite_tilt"] = 1.0
    we["ysort"] = o.ysort_mode


ZONE_TYPE_STYLE = {
    "bbzone_x2": (80.0, 48.0, (255, 220, 60, 100)),
    "bbzone_half": (72.0, 44.0, (120, 200, 255, 95)),
    "bbzone_bonus": (88.0, 52.0, (100, 255, 140, 100)),
    "bbzone_penalty": (88.0, 52.0, (255, 110, 110, 100)),
    "bbzone_safe": (76.0, 46.0, (200, 200, 200, 85)),
}


def zone_type_defaults(obj_name: str, obj_def: Optional[dict] = None):
    nm = str(obj_name or "")
    if nm in ZONE_TYPE_STYLE:
        rx, ry, col = ZONE_TYPE_STYLE[nm]
        return float(rx), float(ry), col
    if isinstance(obj_def, dict):
        bz = obj_def.get("baseball_zone")
        if isinstance(bz, dict):
            rx = _safe_float(bz.get("radius_x"), 72.0)
            ry = _safe_float(bz.get("radius_y"), 44.0)
            col = bz.get("color")
            if isinstance(col, (list, tuple)) and len(col) >= 3:
                return rx, ry, tuple(col)
    return 72.0, 44.0, (255, 230, 80, 95)


def zone_asset_image_exists(obj_name: str, obj_def: Optional[dict] = None) -> bool:
    import os

    from engine import _assets_path_from_rel

    nm = str(obj_name or "")
    info = obj_def if isinstance(obj_def, dict) else {}
    if not info:
        try:
            from data import OBJ_ASSETS

            info = OBJ_ASSETS.get(nm, {}) or {}
        except Exception:
            info = {}
    rel = info.get("path")
    if rel:
        try:
            return os.path.isfile(_assets_path_from_rel(str(rel)))
        except Exception:
            return False
    return os.path.isdir(os.path.join("assets", "images", "object", nm))


def zone_ellipse_geom(o):
    """발 위치 pos = 타원 bbox 하단 중앙. 반환 (cx, foot_y, rx, ry)."""
    spec = zone_spec_from_object(o) or {}
    nm = str(getattr(o, "name", "") or "")
    od = getattr(o, "obj_def", None) or {}
    def_rx, def_ry, _ = zone_type_defaults(nm, od)
    rx = max(4.0, _safe_float(spec.get("radius_x"), def_rx))
    ry = max(3.0, _safe_float(spec.get("radius_y"), def_ry))
    cx = _safe_float(getattr(o, "pos", [0, 0])[0])
    foot_y = _safe_float(getattr(o, "pos", [0, 0])[1])
    return cx, foot_y, rx, ry


def zone_ellipse_center(o):
    cx, foot_y, rx, ry = zone_ellipse_geom(o)
    return cx, foot_y - ry, rx, ry


def zone_color_rgba(o) -> Tuple[int, int, int, int]:
    spec = zone_spec_from_object(o) or {}
    col = spec.get("color")
    if isinstance(col, (list, tuple)) and len(col) >= 3:
        return (
            int(col[0]),
            int(col[1]),
            int(col[2]),
            int(col[3]) if len(col) > 3 else 95,
        )
    _nm = str(getattr(o, "name", "") or "")
    _od = getattr(o, "obj_def", None) or {}
    _rx, _ry, def_col = zone_type_defaults(_nm, _od)
    del _rx, _ry
    if isinstance(def_col, (list, tuple)) and len(def_col) >= 3:
        return (
            int(def_col[0]),
            int(def_col[1]),
            int(def_col[2]),
            int(def_col[3]) if len(def_col) > 3 else 95,
        )
    return (255, 230, 80, 95)


def zone_point_hit(wx: float, wy: float, o) -> bool:
    ecx, ecy, rx, ry = zone_ellipse_center(o)
    if rx <= 0.0 or ry <= 0.0:
        return False
    dx = (float(wx) - ecx) / rx
    dy = (float(wy) - ecy) / ry
    return (dx * dx + dy * dy) <= 1.0


def set_zone_radii(o, radius_x: float, radius_y: float) -> None:
    we = getattr(o, "_world_entry", None)
    if not isinstance(we, dict):
        we = {}
        o._world_entry = we
    bz = dict(we.get("baseball_zone") or {})
    od = getattr(o, "obj_def", None) or {}
    spec = zone_spec_from_object(o) or {}
    bz.setdefault("mode", spec.get("mode") or "mul")
    bz.setdefault("value", spec.get("value", 1.0))
    bz.setdefault("label", spec.get("label") or "")
    bz["radius_x"] = max(8.0, float(radius_x))
    bz["radius_y"] = max(6.0, float(radius_y))
    we["baseball_zone"] = bz


def draw_zone_ellipse_on_surface(
    surf,
    o,
    *,
    world_to_xy,
    selected: bool = False,
) -> Optional[pygame.Rect]:
    """월드→서피스 좌표 변환 콜백으로 타원 그리기."""
    import pygame

    if not zone_uses_ellipse_fallback(o):
        return None
    cx, foot_y, rx, ry = zone_ellipse_geom(o)
    left_w, top_w = world_to_xy(cx - rx, foot_y - ry)
    right_w, bot_w = world_to_xy(cx + rx, foot_y)
    left = int(min(left_w, right_w))
    top = int(min(top_w, bot_w))
    w = max(2, int(abs(right_w - left_w)))
    h = max(2, int(abs(bot_w - top_w)))
    rect = pygame.Rect(left, top, w, h)
    r, g, b, a = zone_color_rgba(o)
    fill = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.ellipse(fill, (r, g, b, a), fill.get_rect())
    surf.blit(fill, (left, top))
    border = (255, 255, 80) if selected else (max(0, r - 30), max(0, g - 30), max(0, b - 30))
    pygame.draw.ellipse(surf, border, rect, 2 if selected else 1)
    return rect


def collect_scoreboard_objects(objs) -> List:
    return [o for o in (objs or []) if is_scoreboard_object(o)]


def zone_footprint_rect(o):
    """바닥 타원 bbox (월드 px). 이미지 있으면 스프라이트 AABB."""
    import pygame
    from render_align import left_edge_bottom_center_x

    if zone_uses_ellipse_fallback(o):
        cx, foot_y, rx, ry = zone_ellipse_geom(o)
        return pygame.Rect(int(cx - rx), int(foot_y - ry), int(2.0 * rx), int(ry))

    surf = getattr(o, "image", None)
    if surf is None:
        return None
    try:
        iw, ih = surf.get_size()
    except Exception:
        return None
    frx = int(round(_safe_float(getattr(o, "pos", [0, 0])[0])))
    fry = int(round(_safe_float(getattr(o, "pos", [0, 0])[1])))
    left = float(left_edge_bottom_center_x(frx, iw))
    top = float(fry) - float(ih)
    return pygame.Rect(int(left), int(top), int(iw), int(ih))


def collect_zone_objects(objs) -> List:
    out = []
    for o in objs or []:
        if is_baseball_zone_object(o):
            out.append(o)
    return out


def hit_zone_at(wx: float, wy: float, zone_objs: List) -> Optional[Tuple[Any, dict]]:
    """(gx, gy)를 덮는 구역 1개 — layer 높은 쪽, 같으면 면적 작은 쪽."""
    hits = []
    for o in zone_objs or []:
        spec = zone_spec_from_object(o)
        if not spec:
            continue
        rect = zone_footprint_rect(o)
        if rect is None:
            continue
        if zone_uses_ellipse_fallback(o):
            if not zone_point_hit(float(wx), float(wy), o):
                continue
        else:
            try:
                if not rect.collidepoint(float(wx), float(wy)):
                    continue
            except Exception:
                continue
        layer = int(getattr(o, "layer", 0) or 0)
        area = max(1, int(rect.w) * int(rect.h))
        hits.append((layer, area, o, spec))
    if not hits:
        return None
    hits.sort(key=lambda t: (-t[0], t[1]))
    _, _, obj, spec = hits[0]
    return obj, spec


def apply_zone_mod(
    carry_px: float,
    is_foul: bool,
    spec: dict,
    *,
    px_per_meter: float = 7.2,
) -> ZoneHit:
    """착지 구역 규칙 → (수정 carry, foul 여부, UI 라벨)."""
    mode = str(spec.get("mode") or "mul").strip().lower()
    val = _safe_float(spec.get("value"), 1.0)
    label = str(spec.get("label") or "").strip()

    if is_foul:
        return float(carry_px), True, label

    if mode in ("set_foul", "foul"):
        return 0.0, True, label or "파울 구역"

    base = max(0.0, float(carry_px))
    if mode == "mul":
        out = base * val
    elif mode == "add_px":
        out = base + val
    elif mode == "add_m":
        out = base + val * max(0.1, float(px_per_meter))
    else:
        out = base

    out = max(0.0, float(out))
    if not label:
        if mode == "mul" and val != 1.0:
            label = f"×{val:g}"
        elif mode == "add_m":
            label = f"{val:+.0f}m"
        elif mode == "add_px":
            label = f"{val:+.0f}px"
    return out, False, label


def _mask_landing_sample_radius(cfg=None) -> int:
    """착지점 단일 픽셀 보정 — 인필드 경계·안티앨리어싱용 이웃 반경(px)."""
    try:
        src = cfg if isinstance(cfg, dict) else None
        if src is None:
            from data import BASEBALL_DEFAULTS

            src = BASEBALL_DEFAULTS
        return max(0, int(src.get("mask_landing_sample_radius_px", 6)))
    except (TypeError, ValueError):
        return 6


def scale_mask_to_background(mask_surf, bg_w: int, bg_h: int):
    """배경과 마스크 크기가 다르면 배경 해상도에 맞춰 스케일(구버전 1024 마스크 등)."""
    import pygame

    if mask_surf is None:
        return None
    try:
        mw, mh = mask_surf.get_size()
        bw, bh = int(bg_w), int(bg_h)
    except Exception:
        return mask_surf
    if mw == bw and mh == bh:
        return mask_surf
    if bw < 1 or bh < 1:
        return mask_surf
    try:
        return pygame.transform.smoothscale(mask_surf, (bw, bh))
    except Exception:
        return mask_surf


def _mask_landing_thresholds(cfg=None) -> Tuple[int, int, int, int]:
    """white_min, blue_min, chroma_max, foul_alpha_max."""
    white_min = 200
    blue_min = 170
    chroma_max = 130
    foul_alpha_max = 128
    src = cfg if isinstance(cfg, dict) else None
    if src is None:
        try:
            from data import BASEBALL_DEFAULTS

            src = BASEBALL_DEFAULTS
        except Exception:
            src = {}
    try:
        white_min = int(src.get("mask_infield_white_min", white_min))
    except (TypeError, ValueError):
        pass
    try:
        blue_min = int(src.get("home_run_mask_blue_min", blue_min))
    except (TypeError, ValueError):
        pass
    try:
        chroma_max = int(src.get("home_run_mask_chroma_max", chroma_max))
    except (TypeError, ValueError):
        pass
    try:
        foul_alpha_max = int(src.get("mask_foul_alpha_max", foul_alpha_max))
    except (TypeError, ValueError):
        pass
    return white_min, blue_min, chroma_max, foul_alpha_max


def _mask_fence_paint_rgb(cfg=None) -> Optional[Tuple[int, int, int]]:
    """마스크 펜스 칠 색 RGB (기본: 노랑 [255, 255, 0])."""
    src = cfg if isinstance(cfg, dict) else {}
    raw = src.get("mask_fence_color")
    if raw is None:
        try:
            from data import BASEBALL_DEFAULTS

            raw = BASEBALL_DEFAULTS.get("mask_fence_color")
        except Exception:
            raw = None
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    try:
        return int(raw[0]), int(raw[1]), int(raw[2])
    except (TypeError, ValueError):
        return None


def _mask_fence_paint_tol(cfg=None) -> int:
    try:
        src = cfg if isinstance(cfg, dict) else {}
        v = src.get("mask_fence_color_tol")
        if v is None:
            from data import BASEBALL_DEFAULTS

            v = BASEBALL_DEFAULTS.get("mask_fence_color_tol", 48)
        return max(8, int(v))
    except (TypeError, ValueError):
        return 48


def pixel_is_fence_paint(r: int, g: int, b: int, *, cfg=None, tol: Optional[int] = None) -> bool:
    rgb = _mask_fence_paint_rgb(cfg)
    if rgb is None:
        return False
    if tol is None:
        tol = _mask_fence_paint_tol(cfg)
    tr, tg, tb = rgb
    return (
        abs(int(r) - tr) <= int(tol)
        and abs(int(g) - tg) <= int(tol)
        and abs(int(b) - tb) <= int(tol)
    )


def _classify_mask_pixel(
    r: int,
    g: int,
    b: int,
    alpha: int,
    *,
    cfg=None,
    white_min: int,
    blue_min: int,
    chroma_max: int,
    foul_alpha_max: int,
) -> str:
    if pixel_is_fence_paint(r, g, b, cfg=cfg):
        return "fence"
    if pixel_is_home_run_zone(r, g, b, blue_min=blue_min, chroma_max=chroma_max):
        return "home_run"
    if r >= white_min and g >= white_min and b >= white_min:
        return "infield"
    if alpha < int(foul_alpha_max):
        return "foul"
    return "foul"


def _ray_reaches_fair_territory(
    ox: float,
    oy: float,
    angle_deg: float,
    mask_surf,
    *,
    cfg=None,
    max_dist: float = 1400.0,
    step_px: float = 6.0,
    start_px: float = 28.0,
) -> bool:
    """홈에서 angle_deg 방향으로 레이를 쏴 인필드·펜스·홈런 구역에 닿는지."""
    if mask_surf is None:
        return True
    rad = math.radians(float(angle_deg))
    dx, dy = math.cos(rad), math.sin(rad)
    d = max(4.0, float(start_px))
    while d <= float(max_dist):
        cls = classify_mask_landing(ox + dx * d, oy + dy * d, mask_surf, cfg=cfg)
        if cls in ("infield", "fence", "home_run"):
            return True
        d += max(2.0, float(step_px))
    return False


def _foul_line_half_deg(
    ox: float,
    oy: float,
    sign: float,
    mask_surf,
    *,
    cfg=None,
    max_dist: float = 1400.0,
) -> float:
    """sign=-1 왼쪽, +1 오른쪽 파울라인 각도(°) — 이 각도까지 조준 가능."""
    if mask_surf is None:
        return 0.0
    sign = -1.0 if float(sign) < 0.0 else 1.0
    hi = 89.0
    if not _ray_reaches_fair_territory(
        ox, oy, sign * hi, mask_surf, cfg=cfg, max_dist=max_dist
    ):
        for trial in (60.0, 45.0, 30.0, 20.0, 12.0):
            if _ray_reaches_fair_territory(
                ox, oy, sign * trial, mask_surf, cfg=cfg, max_dist=max_dist
            ):
                hi = trial
                break
        else:
            return 0.0
    lo = 0.5
    for _ in range(18):
        mid = (lo + hi) * 0.5
        if _ray_reaches_fair_territory(
            ox, oy, sign * mid, mask_surf, cfg=cfg, max_dist=max_dist
        ):
            lo = mid
        else:
            hi = mid
    return max(0.5, lo)


def estimate_fan_half_deg_from_mask(
    origin_xy: Tuple[float, float],
    mask_surf,
    *,
    cfg=None,
    margin_deg: float = 1.5,
    max_dist: float = 1400.0,
) -> Optional[float]:
    """
    마스크 파울라인에 맞춘 방향 게이지 반각(°).
    화살표 0°=오른쪽(+X), ±반각=양쪽 파울라인 — 파울은 착지 마스크로만 판정.
    """
    if mask_surf is None:
        return None
    try:
        ox, oy = float(origin_xy[0]), float(origin_xy[1])
    except (TypeError, ValueError, IndexError):
        return None
    left = _foul_line_half_deg(ox, oy, -1.0, mask_surf, cfg=cfg, max_dist=max_dist)
    right = _foul_line_half_deg(ox, oy, 1.0, mask_surf, cfg=cfg, max_dist=max_dist)
    half = max(left, right) - max(0.0, float(margin_deg))
    if half < 2.0:
        return None
    return min(89.0, half)


def classify_mask_landing(wx: float, wy: float, mask_surf, *, cfg=None) -> str:
    """
    마스크 착지 분류.
    흰=인필드, 파랑=홈런, 노랑(MASK_FENCE_COLOR)=펜스, 그 외 투명·검정·맵 밖=파울.
    Returns: "infield" | "home_run" | "fence" | "foul"
    """
    if mask_surf is None:
        return "infield"
    try:
        w, h = mask_surf.get_size()
    except Exception:
        return "foul"
    x = int(round(float(wx)))
    y = int(round(float(wy)))
    if not (0 <= x < w and 0 <= y < h):
        return "foul"
    white_min, blue_min, chroma_max, foul_alpha_max = _mask_landing_thresholds(cfg)
    try:
        px = mask_surf.get_at((x, y))
        r, g, b = int(px[0]), int(px[1]), int(px[2])
        alpha = int(px[3]) if len(px) >= 4 else 255
    except Exception:
        return "foul"
    primary = _classify_mask_pixel(
        r,
        g,
        b,
        alpha,
        cfg=cfg,
        white_min=white_min,
        blue_min=blue_min,
        chroma_max=chroma_max,
        foul_alpha_max=foul_alpha_max,
    )
    if primary != "foul":
        return primary
    sample_r = _mask_landing_sample_radius(cfg)
    if sample_r <= 0:
        return "foul"
    r2 = int(sample_r) * int(sample_r)
    infield_n = 0
    hr_n = 0
    fence_n = 0
    for dy in range(-sample_r, sample_r + 1):
        yy = y + dy
        if yy < 0 or yy >= h:
            continue
        for dx in range(-sample_r, sample_r + 1):
            if dx * dx + dy * dy > r2:
                continue
            xx = x + dx
            if xx < 0 or xx >= w:
                continue
            try:
                sp = mask_surf.get_at((xx, yy))
                sr, sg, sb = int(sp[0]), int(sp[1]), int(sp[2])
                sa = int(sp[3]) if len(sp) >= 4 else 255
            except Exception:
                continue
            cls = _classify_mask_pixel(
                sr,
                sg,
                sb,
                sa,
                cfg=cfg,
                white_min=white_min,
                blue_min=blue_min,
                chroma_max=chroma_max,
                foul_alpha_max=foul_alpha_max,
            )
            if cls == "infield":
                infield_n += 1
            elif cls == "home_run":
                hr_n += 1
            elif cls == "fence":
                fence_n += 1
    snap_min = max(4, int((sample_r * sample_r) * 0.28))
    if infield_n >= snap_min:
        return "infield"
    if fence_n >= snap_min:
        return "fence"
    if hr_n >= snap_min and infield_n == 0:
        return "home_run"
    return "foul"


def is_ball_blocked_by_fence(wx: float, wy: float, mask_surf, *, cfg=None) -> bool:
    """펜스·파울(맵 밖) — 공이 굴러/튀어 들어갈 수 없는 구역."""
    return classify_mask_landing(wx, wy, mask_surf, cfg=cfg) in ("fence", "foul")


def clamp_to_fielder_reachable(
    wx: float,
    wy: float,
    from_wx: float,
    from_wy: float,
    mask_surf,
    *,
    cfg=None,
) -> Tuple[float, float]:
    """펜스/파울/홈런존 목표 → NPC 쪽으로 되돌려 인필드 위치로."""
    cls = classify_mask_landing(wx, wy, mask_surf, cfg=cfg)
    if cls == "infield":
        return float(wx), float(wy)
    fx, fy = float(from_wx), float(from_wy)
    tx, ty = float(wx), float(wy)
    dist = math.hypot(tx - fx, ty - fy)
    if dist < 1e-3:
        return fx, fy
    steps = max(2, int(dist / 3.0))
    for i in range(steps - 1, 0, -1):
        t = float(i) / float(steps)
        px = fx + (tx - fx) * t
        py = fy + (ty - fy) * t
        if classify_mask_landing(px, py, mask_surf, cfg=cfg) == "infield":
            return px, py
    return fx, fy


def _arc_height_at(dist_along: float, carry_px: float, ball_h_max: float) -> float:
    if carry_px <= 1e-3:
        return 0.0
    u = max(0.0, min(1.0, float(dist_along) / float(carry_px)))
    return 4.0 * float(ball_h_max) * u * (1.0 - u)


def _last_infield_before_fence(
    ox: float,
    oy: float,
    angle_deg: float,
    fence_dist: float,
    mask_surf,
    *,
    cfg=None,
    step_px: float = 4.0,
) -> Tuple[Tuple[float, float], float]:
    rad = math.radians(float(angle_deg))
    dx, dy = math.cos(rad), math.sin(rad)
    step = max(2.0, float(step_px))
    d = max(0.0, float(fence_dist) - step)
    while d >= 0.0:
        x = ox + dx * d
        y = oy + dy * d
        if classify_mask_landing(x, y, mask_surf, cfg=cfg) == "infield":
            return (x, y), d
        d -= step
    return (float(ox), float(oy)), 0.0


def resolve_flight_landing(
    ox: float,
    oy: float,
    angle_deg: float,
    carry_px: float,
    ball_h_max: float,
    mask_surf,
    *,
    cfg=None,
    fence_clear_height_px: float = 18.0,
    trace_step_px: float = 4.0,
) -> Dict[str, Any]:
    """
    타구 궤적 — 펜스 충돌·홈런(펜스 넘김) 판정.
    Returns carry_px, land_xy, is_foul, fence_hit, is_home_run, ground_angle_deg.
    """
    carry = max(0.0, float(carry_px))
    rad = math.radians(float(angle_deg))
    dx, dy = math.cos(rad), math.sin(rad)
    ox, oy = float(ox), float(oy)
    end_x = ox + dx * carry
    end_y = oy + dy * carry
    end_cls = classify_mask_landing(end_x, end_y, mask_surf, cfg=cfg)

    if mask_surf is None or carry <= 1e-3:
        return {
            "carry_px": carry,
            "land_xy": (end_x, end_y),
            "is_foul": end_cls == "foul",
            "fence_hit": end_cls == "fence",
            "is_home_run": end_cls == "home_run",
            "ground_angle_deg": float(angle_deg),
        }

    step = max(2.0, float(trace_step_px))
    fence_dist: Optional[float] = None
    seen_infield = classify_mask_landing(ox, oy, mask_surf, cfg=cfg) == "infield"
    last_infield = (ox, oy)
    last_infield_dist = 0.0
    d = step
    while d <= carry + 1e-3:
        x = ox + dx * d
        y = oy + dy * d
        cls = classify_mask_landing(x, y, mask_surf, cfg=cfg)
        if cls == "infield":
            seen_infield = True
            last_infield = (x, y)
            last_infield_dist = d
        elif cls in ("fence", "home_run") and seen_infield and fence_dist is None:
            fence_dist = d
        d += step

    def _fence_bounce() -> Dict[str, Any]:
        contact_dist = float(fence_dist) if fence_dist is not None else float(last_infield_dist)
        if contact_dist <= 1e-3:
            contact_dist = max(8.0, float(carry))
        contact_dist = max(8.0, contact_dist)
        pt, land_dist = _last_infield_before_fence(
            ox, oy, angle_deg, contact_dist, mask_surf, cfg=cfg, step_px=step
        )
        if land_dist <= 1e-3:
            land_dist = max(8.0, contact_dist - step * 2.0)
            pt = (ox + dx * land_dist, oy + dy * land_dist)
        return {
            "carry_px": contact_dist,
            "land_xy": (float(pt[0]), float(pt[1])),
            "is_foul": False,
            "fence_hit": True,
            "is_home_run": False,
            "ground_angle_deg": float(angle_deg) + 180.0,
        }

    if end_cls == "home_run":
        if fence_dist is not None and seen_infield:
            h_fence = _arc_height_at(fence_dist, carry, ball_h_max)
            if h_fence < float(fence_clear_height_px):
                return _fence_bounce()
        return {
            "carry_px": carry,
            "land_xy": (end_x, end_y),
            "is_foul": False,
            "fence_hit": False,
            "is_home_run": True,
            "ground_angle_deg": float(angle_deg),
        }

    if end_cls == "fence" and (seen_infield or fence_dist is not None):
        return _fence_bounce()

    if end_cls == "foul":
        if fence_dist is not None and seen_infield:
            return _fence_bounce()
        return {
            "carry_px": carry,
            "land_xy": (end_x, end_y),
            "is_foul": True,
            "fence_hit": False,
            "is_home_run": False,
            "ground_angle_deg": float(angle_deg),
        }

    if fence_dist is not None and seen_infield and fence_dist < carry - 1e-3:
        h_fence = _arc_height_at(fence_dist, carry, ball_h_max)
        if h_fence < float(fence_clear_height_px):
            return _fence_bounce()

    return {
        "carry_px": carry,
        "land_xy": (end_x, end_y),
        "is_foul": False,
        "fence_hit": False,
        "is_home_run": False,
        "ground_angle_deg": float(angle_deg),
    }


def pixel_is_home_run_zone(r: int, g: int, b: int, *, blue_min: int = 170, chroma_max: int = 130) -> bool:
    """마스크 파란색 = 홈런 펜스 너머 (흰색 인플레이와 구분)."""
    ri, gi, bi = int(r), int(g), int(b)
    if bi < int(blue_min):
        return False
    if ri > int(chroma_max) or gi > int(chroma_max):
        return False
    return bi > ri + 30 and bi > gi + 30


def is_home_run_landing(wx: float, wy: float, mask_surf, *, cfg=None) -> bool:
    return classify_mask_landing(wx, wy, mask_surf, cfg=cfg) == "home_run"


def resolve_landing_zone(
    wx: float,
    wy: float,
    zone_objs: List,
    carry_px: float,
    is_foul: bool,
    *,
    px_per_meter: float = 7.2,
) -> Tuple[float, bool, str]:
    hit = hit_zone_at(wx, wy, zone_objs)
    if not hit:
        return float(carry_px), bool(is_foul), ""
    _, spec = hit
    new_carry, new_foul, label = apply_zone_mod(
        carry_px, is_foul, spec, px_per_meter=px_per_meter
    )
    return new_carry, new_foul, label


# --- 에디터: 야구장 설정 키 (world_data[map]["baseball"] 에 저장) ---

def _bbd(key: str, fallback):
    try:
        from data import BASEBALL_DEFAULTS

        v = BASEBALL_DEFAULTS.get(key)
        return fallback if v is None else v
    except Exception:
        return fallback


BASEBALL_EDITOR_SCALAR_KEYS = [
    ("swings", "타석 수", "int", _bbd("swings", 5)),
    ("fan_half_deg", "방향 게이지 반각(°)", "float", _bbd("fan_half_deg", 37.0)),
    ("fan_half_deg_auto", "반각 마스크 자동", "bool", _bbd("fan_half_deg_auto", False)),
    ("fan_half_margin_deg", "자동 반각 여유(°)", "float", _bbd("fan_half_margin_deg", 1.5)),
    ("fan_half_guide_visible", "맵 가이드라인 표시", "bool", _bbd("fan_half_guide_visible", True)),
    ("pwr_sweet_spot_half_width", "장타 구간 반폭(0~1)", "float", _bbd("pwr_sweet_spot_half_width", 0.05)),
    ("pwr_power_sweet_spot_half_width", "파워장타 구간 반폭(0~1)", "float", _bbd("pwr_power_sweet_spot_half_width", 0.025)),
    ("pwr_trap_half_width_new", "새 함정 구간 반폭(0~1)", "float", _bbd("pwr_trap_half_width_new", 0.02)),
    ("pwr_sweet_spot_bonus_mul", "장타 보너스 배율", "float", _bbd("pwr_sweet_spot_bonus_mul", 1.1)),
    ("pwr_power_sweet_spot_bonus_mul", "파워 게이지 선택 표시 유지(초)", "float", _bbd("pwr_confirm_hold_sec", 1.0)),
    ("normal_swing_pause_sec", "일반 타구 포즈 대기(초)", "float", _bbd("normal_swing_pause_sec", 0.5)),
    ("power_swing_pause_sec", "파워장타 포즈 대기(초)", "float", _bbd("power_swing_pause_sec", 1.5)),
    ("power_swing_zoom_value", "파워장타 줌 값", "float", _bbd("power_swing_zoom_value", 4.0)),
    ("power_swing_zoom_in_sec", "파워장타 줌인 시간(초)", "float", _bbd("power_swing_zoom_in_sec", 0.12)),
    ("power_swing_zoom_restore_sec", "파워장타 줌복귀 시간(초)", "float", _bbd("power_swing_zoom_restore_sec", 0.12)),
    ("power_swing_shake_sec", "파워장타 흔들림 시간(초)", "float", _bbd("power_swing_shake_sec", 1.0)),
    ("power_swing_shake_amp_px", "파워장타 흔들림 세기(px)", "float", _bbd("power_swing_shake_amp_px", 50.0)),
    ("power_swing_shake_freq_hz", "파워장타 흔들림 Hz", "float", _bbd("power_swing_shake_freq_hz", 16.0)),
    ("p2_switch_fade_out_sec", "1P→2P 페이드아웃(초)", "float", _bbd("p2_switch_fade_out_sec", 0.25)),
    ("p2_switch_fade_hold_sec", "1P→2P 검정화면 유지(초)", "float", _bbd("p2_switch_fade_hold_sec", 0.08)),
    ("p2_switch_fade_in_sec", "1P→2P 페이드인(초)", "float", _bbd("p2_switch_fade_in_sec", 0.25)),
    ("swing_anim_base_sec", "타격 애니메이션 기본시간(초)", "float", _bbd("swing_anim_base_sec", 0.45)),
    ("swing_speed_mul", "타격 애니메이션 속도 배율", "float", _bbd("swing_speed_mul", 1.3)),
    ("max_carry_px", "최대 비거리(px)", "float", _bbd("max_carry_px", 960.0)),
    ("tee_height", "티 높이", "float", _bbd("tee_height", 16.0)),
    ("npc_skill", "NPC 실력(0~1)", "float", _bbd("npc_skill", 0.62)),
    ("px_per_meter", "px/미터(표시)", "float", _bbd("px_per_meter", 12.39)),
    ("dir_sweep_hz", "방향 게이지 Hz", "float", _bbd("dir_sweep_hz", 2.0)),
    ("pwr_sweep_hz", "파워 게이지 Hz", "float", _bbd("pwr_sweep_hz", 2.0)),
    ("swing_dir_spread_ratio", "방향 변동(반각×비율)", "float", _bbd("swing_dir_spread_ratio", 0.10)),
    ("swing_dir_spread_pwr_ratio", "방향 변동(파워)", "float", _bbd("swing_dir_spread_pwr_ratio", 0.02)),
    ("foul_carry_px", "파울 비거리(px)", "float", _bbd("foul_carry_px", 20.0)),
    ("carry_distance_mul", "비거리 배율", "float", _bbd("carry_distance_mul", 1.3)),
    ("flight_height_mul", "타구 높이 배율", "float", _bbd("flight_height_mul", 1.5)),
    ("bounce_duration_mul", "튕김 시간 배율", "float", _bbd("bounce_duration_mul", 1.3)),
    ("bounce_travel_carry_ratio", "튕김 거리 비율", "float", _bbd("bounce_travel_carry_ratio", 0.38)),
    ("bounce_count", "튕김 횟수", "int", _bbd("bounce_count", 3)),
    ("bounce_height_carry_ratio", "튕김 높이 비율", "float", _bbd("bounce_height_carry_ratio", 0.028)),
    ("roll_travel_carry_ratio", "굴러감 거리 비율", "float", _bbd("roll_travel_carry_ratio", 0.062)),
    ("roll_speed_max", "굴러감 최대속도", "float", _bbd("roll_speed_max", 108.0)),
    ("roll_speed_min", "굴러감 최저속도", "float", _bbd("roll_speed_min", 52.0)),
    ("roll_speed_exp", "굴러감 감속 곡선", "float", _bbd("roll_speed_exp", 0.55)),
]

BASEBALL_EDITOR_XY_KEYS = [
    ("plate", "홈(plate) [x,y]"),
    ("tee", "티(공) [x,y]"),
    ("cam_fixed", "고정 카메라 [x,y]"),
    ("exit_pos", "나가기 좌표 [x,y]"),
    ("wait_opponent_offset", "대기 상대 오프셋 [dx,dy]"),
    ("p1_wait_pos", "1P 대기 위치 [x,y] (비우면 오프셋)"),
    ("p2_wait_pos", "2P 대기 위치 [x,y] (비우면 오프셋)"),
    ("intro_pan_1", "투어 지점 1 [x,y]"),
    ("intro_pan_2", "투어 지점 2 [x,y]"),
    ("intro_pan_3", "투어 지점 3 [x,y]"),
    ("intro_pan_4", "투어 지점 4 [x,y]"),
]

BASEBALL_SCOREBOARD_PRESETS = [
    ("bbscoreboard1", "전광판"),
]

BASEBALL_EDITOR_TEXT_KEYS = [
    ("npc_name", "NPC 이름", "야구친구"),
    ("batter_face", "타자 방향", "right"),
    ("exit_map", "나가기 맵", "bg_jjangpu"),
    ("mask_img", "마스크 파일", "bg_baseball1_mask.png"),
]

BASEBALL_ZONE_PRESETS = [
    ("bbzone_x2", "×2"),
    ("bbzone_half", "×0.5"),
    ("bbzone_bonus", "+보너스"),
    ("bbzone_penalty", "−페널티"),
    ("bbzone_safe", "안전"),
]

ZONE_MODES = [
    ("mul", "곱하기 (×)"),
    ("add_px", "더하기 (px)"),
    ("add_m", "더하기 (m)"),
    ("set_foul", "강제 파울"),
]


def merge_field_config(map_id: str, world_data: Optional[dict] = None) -> dict:
    """BASEBALL_DEFAULTS + world_data[map].baseball (+ 맵 루트 mask_img)."""
    from data import BASEBALL_DEFAULTS

    mid = str(map_id or "").strip()
    out = dict(BASEBALL_DEFAULTS)
    if isinstance(world_data, dict):
        map_row = world_data.get(mid)
        if isinstance(map_row, dict):
            for mk in ("bg_img", "mask_img"):
                if mk in map_row:
                    out[mk] = map_row[mk]
            overlay = map_row.get("baseball")
            if isinstance(overlay, dict):
                for k, v in overlay.items():
                    if not str(k).startswith("_"):
                        out[k] = v
    return out


def baseball_config_to_world_row(cfg: dict) -> dict:
    """에디터 저장용 — world_data baseball 블록."""
    if not isinstance(cfg, dict):
        return {}
    row = {}
    for key, _, _, _ in BASEBALL_EDITOR_SCALAR_KEYS:
        if key in cfg:
            row[key] = cfg[key]
    for key, _ in BASEBALL_EDITOR_XY_KEYS:
        v = cfg.get(key)
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            row[key] = [float(v[0]), float(v[1])]
    pan_pts = []
    for i in range(1, 5):
        v = cfg.get(f"intro_pan_{i}")
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            pan_pts.append([float(v[0]), float(v[1])])
    if pan_pts:
        row["intro_pan_points"] = pan_pts
    elif isinstance(cfg.get("intro_pan_points"), list):
        pts = []
        for item in cfg.get("intro_pan_points") or []:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pts.append([float(item[0]), float(item[1])])
        if pts:
            row["intro_pan_points"] = pts
    for key, _, default in BASEBALL_EDITOR_TEXT_KEYS:
        if key in cfg:
            row[key] = cfg[key]
        elif default:
            row[key] = default
    return row


def load_editor_config(flow, map_id: str) -> dict:
    cfg = merge_field_config(map_id, getattr(flow, "world_data", None))
    pts = cfg.get("intro_pan_points")
    if isinstance(pts, list):
        for i, item in enumerate(pts[:4], 1):
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                try:
                    cfg[f"intro_pan_{i}"] = [float(item[0]), float(item[1])]
                except (TypeError, ValueError):
                    pass
    return cfg

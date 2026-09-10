"""에디터 BASEBALL 모드 — 점수 구역 배치 + 야구장 설정(world_data.baseball).

editor.py 가 이벤트/그리기 훅으로 호출.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import pygame

import editor_text as ed_txt

from activities.baseball_zones import (
    BASEBALL_EDITOR_SCALAR_KEYS,
    BASEBALL_EDITOR_TEXT_KEYS,
    BASEBALL_EDITOR_XY_KEYS,
    BASEBALL_SCOREBOARD_PRESETS,
    BASEBALL_ZONE_PRESETS,
    ZONE_MODES,
    apply_scoreboard_defaults,
    baseball_config_to_world_row,
    is_baseball_zone_object,
    is_scoreboard_object,
    load_editor_config,
    set_zone_radii,
    zone_asset_image_exists,
    zone_ellipse_geom,
    zone_point_hit,
    zone_spec_from_object,
    zone_uses_ellipse_fallback,
)
from data import OBJ_ASSETS

EDITOR_BB_LINE_H = 22
EDITOR_BB_MODAL_ROW_H = 28
BB_MODAL_HEADER_H = 36
BB_MODAL_FOOTER_H = 54
BB_MODAL_SB_W = 12
BB_MODAL_PAD_X = 12
BB_MODAL_WHEEL_STEP = 30


def new_state() -> dict:
    return {
        "tool": "ZONES",  # ZONES | MARKERS | SETTINGS
        "show_settings": False,
        "show_zone_modal": False,
        "settings_fields": {},
        "zone_fields": {"mode": "mul", "value": "2.0", "label": "×2"},
        "zone_edit_node": None,
        "pick_xy_key": None,  # plate | tee | cam_fixed | exit_pos
        "scroll_left": 0,
        "settings_scroll": 0,
        "settings_sb_drag": False,
        "zone_modal_scroll": 0,
        "text_edit": ed_txt.EditSession(),
    }


def _te(state) -> ed_txt.EditSession:
    te = state.get("text_edit")
    if not isinstance(te, ed_txt.EditSession):
        te = ed_txt.EditSession()
        state["text_edit"] = te
    return te


def is_baseball_map(map_id: str) -> bool:
    mid = str(map_id or "").strip()
    return mid.startswith("bg_baseball") or mid == "bg_baseball1"


def reload_object_assets():
    """object_defs.json 갱신 후 에디터 OBJ 목록 반영."""
    try:
        from entity_defs import reload_entity_defs

        reload_entity_defs()
        from data import OBJ_ASSETS as fresh

        return fresh
    except Exception:
        return OBJ_ASSETS


def _parse_float(s, default=0.0) -> float:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return float(default)


def _parse_int(s, default=0) -> int:
    try:
        return int(float(str(s).strip()))
    except (TypeError, ValueError):
        return int(default)


def _parse_xy(text: str, default=(0.0, 0.0)) -> Tuple[float, float]:
    t = str(text or "").strip()
    if not t:
        return default
    t = t.replace("[", "").replace("]", "")
    parts = [p.strip() for p in t.split(",") if p.strip()]
    if len(parts) >= 2:
        return _parse_float(parts[0], default[0]), _parse_float(parts[1], default[1])
    return default


def _xy_to_text(v) -> str:
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return f"{float(v[0]):g}, {float(v[1]):g}"
    return "0, 0"


def load_settings_fields(flow, map_id: str) -> dict:
    cfg = load_editor_config(flow, map_id)
    fields: Dict[str, str] = {}
    for key, _label, _typ, default in BASEBALL_EDITOR_SCALAR_KEYS:
        v = cfg.get(key, default)
        fields[key] = str(v)
    for key, _label in BASEBALL_EDITOR_XY_KEYS:
        if key in ("p1_wait_pos", "p2_wait_pos") and key not in cfg:
            fields[key] = ""
        else:
            fields[key] = _xy_to_text(cfg.get(key))
    for key, _label, default in BASEBALL_EDITOR_TEXT_KEYS:
        fields[key] = str(cfg.get(key, default) or default)
    return fields


def apply_settings_fields(flow, map_id: str, fields: dict) -> None:
    cfg = load_editor_config(flow, map_id)
    for key, _label, typ, default in BASEBALL_EDITOR_SCALAR_KEYS:
        raw = fields.get(key, str(default))
        if typ == "int":
            cfg[key] = _parse_int(raw, default)
        else:
            cfg[key] = _parse_float(raw, default)
    optional_xy = {"p1_wait_pos", "p2_wait_pos"}
    for key, _label in BASEBALL_EDITOR_XY_KEYS:
        raw = str(fields.get(key, "") or "").strip()
        if key in optional_xy and not raw:
            cfg.pop(key, None)
            continue
        cfg[key] = list(_parse_xy(raw if raw else "0, 0"))
    for key, _label, default in BASEBALL_EDITOR_TEXT_KEYS:
        cfg[key] = str(fields.get(key, default) or default).strip()
    row = baseball_config_to_world_row(cfg)
    flow.world_data.setdefault(map_id, {})["baseball"] = row


def sync_zone_fields_from_node(node, fields: dict) -> None:
    spec = zone_spec_from_object(node) or {}
    fields["mode"] = str(spec.get("mode") or "mul")
    fields["value"] = str(spec.get("value", 1.0))
    fields["label"] = str(spec.get("label") or "")
    fields["radius_x"] = str(spec.get("radius_x", 72.0))
    fields["radius_y"] = str(spec.get("radius_y", 44.0))


def apply_zone_fields_to_node(node, fields: dict) -> None:
    we = getattr(node, "_world_entry", None)
    if not isinstance(we, dict):
        we = {}
        node._world_entry = we
    we["baseball_zone"] = {
        "mode": str(fields.get("mode") or "mul").strip(),
        "value": _parse_float(fields.get("value"), 1.0),
        "label": str(fields.get("label") or "").strip(),
        "radius_x": max(8.0, _parse_float(fields.get("radius_x"), 72.0)),
        "radius_y": max(6.0, _parse_float(fields.get("radius_y"), 44.0)),
    }


def place_scoreboard_object(asset_name: str, wx: float, wy: float, objs: list):
    from engine import FieldItem

    od = OBJ_ASSETS.get(asset_name, {}) or {}
    o = FieldItem(
        str(asset_name),
        float(wx),
        float(wy),
        sprite_tilt=1.0,
        height=0,
        ysort_mode=str(od.get("ysort", "ground") or "ground"),
        layer=1,
    )
    o.obj_def = dict(od)
    o._world_entry = {
        "name": asset_name,
        "pos": [int(wx), int(wy)],
        "sprite_tilt": 1.0,
        "ysort": o.ysort_mode,
        "layer": 1,
    }
    apply_scoreboard_defaults(o)
    objs.append(o)
    return o


def place_zone_object(asset_name: str, wx: float, wy: float, objs: list):
    from engine import FieldItem

    o = FieldItem(str(asset_name), float(wx), float(wy), sprite_tilt=0.0, height=0)
    o.ysort_mode = "ground"
    o.layer = 0
    od = OBJ_ASSETS.get(asset_name, {}) or {}
    o.obj_def = dict(od)
    bz = od.get("baseball_zone")
    we = {"name": asset_name, "pos": [int(wx), int(wy)], "sprite_tilt": 0.0}
    if isinstance(bz, dict):
        we["baseball_zone"] = dict(bz)
    o._world_entry = we
    if zone_uses_ellipse_fallback(o):
        o.is_visible = False
    objs.append(o)
    return o


def left_list_tops(top_bar_h: int, tool: str = "ZONES") -> dict:
    tb = int(top_bar_h)
    tools = tb + 38
    y = tools + 30
    presets = y
    if str(tool or "ZONES").upper() == "ZONES":
        preset_count = len(BASEBALL_ZONE_PRESETS) + len(BASEBALL_SCOREBOARD_PRESETS)
        grid_rows = (preset_count + 1) // 2
        y = presets + grid_rows * 30 + 8
    settings_btn = y
    list_header = settings_btn + 36
    list_top = list_header + 18
    return {
        "tools": tools,
        "presets": presets,
        "settings_btn": settings_btn,
        "list_header": list_header,
        "list": list_top,
    }


def sidebar_list_metrics(top_bar_h: int, tool: str, objs) -> Tuple[int, int]:
    """좌측 PLACED 리스트 스크롤 — (list_top, content_height)."""
    tops = left_list_tops(top_bar_h, tool)
    rows = placed_object_rows(objs)
    return tops["list"], len(rows) * EDITOR_BB_LINE_H


def is_placed_object(o) -> bool:
    return is_baseball_zone_object(o) or is_scoreboard_object(o)


def pick_placed_object_at(objs, npcs, wx, wy, alpha_hit_fn):
    """야구 배치 오브젝트 — 타원 구역은 내부 클릭, 전광판은 스프라이트 히트."""
    hits = []
    for o in objs or []:
        if not is_placed_object(o):
            continue
        if is_baseball_zone_object(o) and zone_uses_ellipse_fallback(o):
            if not zone_point_hit(float(wx), float(wy), o):
                continue
            _cx, _fy, rx, ry = zone_ellipse_geom(o)
            area = float(rx) * float(ry)
        elif not alpha_hit_fn(o, wx, wy):
            continue
        else:
            try:
                iw, ih = o.image.get_size()
                area = float(iw) * float(ih)
            except Exception:
                area = 9999.0
        layer = int(getattr(o, "layer", 0) or 0)
        hits.append((layer, area, o))
    if not hits:
        return None
    hits.sort(key=lambda t: (-t[0], t[1]))
    return hits[0][2]


def adjust_zone_radii(o, drx: float = 0.0, dry: float = 0.0) -> None:
    spec = zone_spec_from_object(o) or {}
    rx = max(8.0, _parse_float(spec.get("radius_x"), 72.0) + float(drx))
    ry = max(6.0, _parse_float(spec.get("radius_y"), 44.0) + float(dry))
    set_zone_radii(o, rx, ry)


def zone_object_rows(objs) -> List[dict]:
    return placed_object_rows(objs)


def placed_object_rows(objs) -> List[dict]:
    rows = []
    for o in objs or []:
        if is_baseball_zone_object(o):
            spec = zone_spec_from_object(o) or {}
            rows.append(
                {
                    "node": o,
                    "name": str(getattr(o, "name", "")),
                    "label": str(spec.get("label") or spec.get("mode") or ""),
                }
            )
        elif is_scoreboard_object(o):
            rows.append(
                {
                    "node": o,
                    "name": str(getattr(o, "name", "")),
                    "label": "전광판",
                }
            )
    return rows


def filter_right_categories(categories: dict) -> dict:
    """BASEBALL ZONES 툴 — 점수 구역 카테고리만."""
    out = {}
    for cat, items in (categories or {}).items():
        if "야구장" in str(cat) or cat == "야구장(점수구역)":
            out[cat] = list(items)
    if not out:
        for cat, items in (categories or {}).items():
            if any(str(n).startswith("bbzone_") for n in items):
                out[cat] = [n for n in items if str(n).startswith("bbzone_")]
    if not out:
        for cat, items in (categories or {}).items():
            if "전광판" in str(cat) or any(str(n).startswith("bbscoreboard") for n in items):
                out[cat] = [
                    n for n in items
                    if str(n).startswith("bbscoreboard") or "전광판" in str(cat)
                ]
    return out


def draw_mode_tabs(screen, font, sidebar_w, top_bar_h, edit_mode):
    """5분할 MAP / EVENT / FLOW / BASEBALL / RACING 탭."""
    modes = ("MAP", "EVENT", "FLOW", "BASEBALL", "RACING")
    band = max(1, top_bar_h // len(modes))
    colors = ((60, 60, 60), (70, 70, 70), (55, 52, 48), (52, 58, 72), (48, 62, 58))
    for i, col in enumerate(colors):
        pygame.draw.rect(screen, col, (0, i * band, sidebar_w, band))
    ix = modes.index(edit_mode) if edit_mode in modes else 0
    pygame.draw.rect(screen, (255, 215, 0), (0, ix * band, sidebar_w, band), 2)
    labels = ("MAP", "EVENT", "FLOW", "BB", "RACE")
    for i, lab in enumerate(labels):
        c = (255, 255, 255) if edit_mode == modes[i] else (100, 100, 100)
        screen.blit(font.render(lab, True, c), (10, i * band + max(0, (band - 14) // 2)))


def mode_from_click(my: int, top_bar_h: int) -> Optional[str]:
    if my <= 0 or my >= top_bar_h:
        return None
    modes = ("MAP", "EVENT", "FLOW", "BASEBALL", "RACING")
    band = max(1, top_bar_h // len(modes))
    idx = min(len(modes) - 1, int(my // band))
    return modes[idx]


def draw_left_panel(
    screen,
    font,
    title_font,
    state,
    map_id,
    objs,
    top_bar_h,
    sidebar_w,
    map_view_h,
    *,
    selected_nodes=None,
    list_scroll=0,
):
    tool = str(state.get("tool") or "ZONES")
    tops = left_list_tops(top_bar_h, tool)
    if not is_baseball_map(map_id):
        screen.blit(
            font.render("야구 맵(bg_baseball*)만", True, (255, 180, 120)),
            (8, tops["tools"]),
        )
        return tops

    tool = str(state.get("tool") or "ZONES")
    tw = max(36, (sidebar_w - 32) // 3)
    btn_z = pygame.Rect(8, tops["tools"], tw, 26)
    btn_m = pygame.Rect(btn_z.right + 4, tops["tools"], tw, 26)
    btn_s = pygame.Rect(btn_m.right + 4, tops["tools"], tw, 26)
    for b, lab, key in (
        (btn_z, "구역", "ZONES"),
        (btn_m, "핀", "MARKERS"),
        (btn_s, "설정", "SETTINGS"),
    ):
        pygame.draw.rect(screen, (70, 70, 70), b)
        if tool == key:
            pygame.draw.rect(screen, (255, 215, 0), b, 2)
        screen.blit(font.render(lab, True, (255, 255, 255)), (b.x + 6, b.y + 4))

    if tool == "ZONES":
        pw = max(48, (sidebar_w - 24) // 2)
        y = tops["presets"]
        preset_rows = list(BASEBALL_ZONE_PRESETS) + list(BASEBALL_SCOREBOARD_PRESETS)
        for i, (asset, label) in enumerate(preset_rows):
            col = i % 2
            row = i // 2
            r = pygame.Rect(8 + col * (pw + 4), y + row * 30, pw, 26)
            col_bg = (55, 75, 55) if str(asset).startswith("bbzone_") else (45, 55, 85)
            pygame.draw.rect(screen, col_bg, r)
            screen.blit(font.render(label, True, (220, 255, 220)), (r.x + 4, r.y + 4))

    settings_btn = pygame.Rect(8, tops["settings_btn"], sidebar_w - 16, 28)
    pygame.draw.rect(screen, (50, 60, 90), settings_btn)
    screen.blit(font.render("야구 설정 편집…", True, (230, 240, 255)), (settings_btn.x + 8, settings_btn.y + 6))

    pygame.draw.line(
        screen,
        (70, 80, 70),
        (8, tops["list_header"]),
        (sidebar_w - 8, tops["list_header"]),
        1,
    )
    screen.blit(title_font.render("PLACED", True, (200, 255, 200)), (10, tops["list_header"] + 4))
    rows = placed_object_rows(objs)
    y0 = tops["list"] - int(list_scroll or 0)
    sel_set = set(selected_nodes or [])
    for row in rows:
        r = pygame.Rect(8, y0, sidebar_w - 16, EDITOR_BB_LINE_H)
        if r.bottom > top_bar_h and r.top < top_bar_h + map_view_h:
            sel = state.get("zone_edit_node") is row["node"] or row["node"] in sel_set
            if sel:
                pygame.draw.rect(screen, (80, 80, 40), r)
            screen.blit(
                font.render(f"{row['name']} {row['label']}", True, (220, 220, 220)),
                (r.x + 4, r.y + 2),
            )
        y0 += EDITOR_BB_LINE_H
    return tops


def draw_map_overlay(screen, state, cfg: dict, cam_x, cam_y, zoom_level, get_screen_pos):
    """홈·티·카메라 핀 + 구역 하이라이트."""
    pins = [
        ("plate", (255, 80, 80), "P"),
        ("tee", (255, 220, 80), "T"),
        ("cam_fixed", (120, 200, 255), "C"),
        ("wait_opponent_offset", (255, 160, 220), "W"),
    ]
    for key, color, ch in pins:
        v = cfg.get(key)
        if key == "wait_opponent_offset":
            plate = cfg.get("plate")
            if isinstance(plate, (list, tuple)) and len(plate) >= 2 and isinstance(v, (list, tuple)) and len(v) >= 2:
                v = [float(plate[0]) + float(v[0]), float(plate[1]) + float(v[1])]
            else:
                continue
        if not isinstance(v, (list, tuple)) or len(v) < 2:
            continue
        sx, sy = get_screen_pos(float(v[0]), float(v[1]))
        pygame.draw.circle(screen, color, (int(sx), int(sy)), 6)
        pygame.draw.circle(screen, (255, 255, 255), (int(sx), int(sy)), 6, 1)
        try:
            fnt = pygame.font.Font(None, 18)
            screen.blit(fnt.render(ch, True, color), (int(sx) + 8, int(sy) - 8))
        except Exception:
            pass

    for key, color, ch in (
        ("p1_wait_pos", (180, 220, 255), "1"),
        ("p2_wait_pos", (220, 180, 255), "2"),
    ):
        v = cfg.get(key)
        if not isinstance(v, (list, tuple)) or len(v) < 2:
            continue
        sx, sy = get_screen_pos(float(v[0]), float(v[1]))
        pygame.draw.circle(screen, color, (int(sx), int(sy)), 5)
        pygame.draw.circle(screen, (255, 255, 255), (int(sx), int(sy)), 5, 1)
        try:
            fnt = pygame.font.Font(None, 18)
            screen.blit(fnt.render(ch, True, color), (int(sx) + 8, int(sy) - 8))
        except Exception:
            pass

    pick = state.get("pick_xy_key")
    if pick:
        try:
            fnt = pygame.font.Font(None, 20)
            screen.blit(
                fnt.render(f"클릭: {pick} 좌표", True, (255, 255, 120)),
                (12, 12),
            )
        except Exception:
            pass

    tour_colors = (
        (255, 200, 80),
        (255, 170, 60),
        (255, 140, 50),
        (255, 110, 40),
    )
    cfg_pts = cfg.get("intro_pan_points")
    tour_pts = []
    if isinstance(cfg_pts, list):
        for item in cfg_pts:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                tour_pts.append(item)
    if not tour_pts:
        for i in range(1, 5):
            v = cfg.get(f"intro_pan_{i}")
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                tour_pts.append(v)
    for i, v in enumerate(tour_pts[:4]):
        sx, sy = get_screen_pos(float(v[0]), float(v[1]))
        color = tour_colors[i % len(tour_colors)]
        pygame.draw.circle(screen, color, (int(sx), int(sy)), 5)
        pygame.draw.circle(screen, (255, 255, 255), (int(sx), int(sy)), 5, 1)
        try:
            fnt = pygame.font.Font(None, 18)
            screen.blit(fnt.render(str(i + 1), True, color), (int(sx) + 8, int(sy) - 8))
        except Exception:
            pass


def _modal_rect(sw, sh, rows: int):
    h = min(sh - 40, 80 + rows * EDITOR_BB_MODAL_ROW_H)
    return pygame.Rect(sw // 2 - 210, sh // 2 - h // 2, 420, h)


def _settings_modal_metrics(sw, sh):
    rows = _settings_modal_rows()
    content_h = max(1, len(rows) * EDITOR_BB_MODAL_ROW_H)
    max_body = max(100, int(sh * 0.66))
    body_vp = min(content_h, max_body)
    ph = BB_MODAL_HEADER_H + body_vp + BB_MODAL_FOOTER_H
    margin = 40
    ph = min(ph, max(BB_MODAL_HEADER_H + BB_MODAL_FOOTER_H + 80, sh - margin))
    y0 = max(margin // 2, (sh - ph) // 2)
    panel = pygame.Rect(sw // 2 - 210, y0, 420, ph)
    return panel, content_h, body_vp


def _settings_modal_body_layout(panel, scroll_px, content_h):
    pad = BB_MODAL_PAD_X
    sb_w = BB_MODAL_SB_W
    gap = 4
    body_top = panel.y + BB_MODAL_HEADER_H
    body_bottom = panel.bottom - BB_MODAL_FOOTER_H
    body_h = max(1, int(body_bottom - body_top))
    inner_w = panel.width - 2 * pad
    body_w = max(40, int(inner_w - sb_w - gap))
    body_rect = pygame.Rect(int(panel.x + pad), int(body_top), body_w, body_h)
    sb_rect = pygame.Rect(int(panel.right - pad - sb_w), int(body_top), int(sb_w), body_h)
    max_scroll = max(0, int(content_h) - body_h)
    sp = int(max(0, min(max_scroll, int(scroll_px or 0))))
    return body_rect, sb_rect, max_scroll, sp


def _bb_scrollbar_layout(sb_rect, viewport_h, content_h, scroll_px):
    vh = max(1, int(viewport_h))
    ch = max(int(content_h), 1)
    max_scroll = max(0, ch - vh)
    sp = int(max(0, min(max_scroll, int(scroll_px or 0))))
    track = thumb = None
    thumb_h = None
    if max_scroll > 0 and sb_rect.height > 2:
        track = pygame.Rect(sb_rect.x + 1, sb_rect.y + 1, sb_rect.width - 2, sb_rect.height - 2)
        thumb_h = max(18, int(track.height * (vh / float(ch))))
        span = max(0, track.height - thumb_h)
        thumb_y = track.y + int(round(span * (sp / float(max_scroll))))
        thumb = pygame.Rect(track.x + 1, thumb_y, track.width - 2, thumb_h)
    return {
        "max_scroll": max_scroll,
        "scroll_px": sp,
        "track": track,
        "thumb": thumb,
        "thumb_h": thumb_h,
    }


def _bb_scroll_px_from_sb_my(my, sb_ui):
    tr = sb_ui.get("track")
    th = int(sb_ui.get("thumb_h") or 18)
    max_sc = int(sb_ui.get("max_scroll") or 0)
    if tr is None or max_sc <= 0:
        return None
    y = int(my) - (th // 2)
    y = max(tr.y, min(tr.bottom - th, y))
    span = max(0, tr.height - th)
    p = 0.0 if span <= 0 else (y - tr.y) / float(span)
    return int(round(p * max_sc))


def _bb_modal_sb_hit(pos, sb_ui):
    max_sc = int(sb_ui.get("max_scroll") or 0)
    if max_sc <= 0:
        return None
    th = sb_ui.get("thumb")
    tr = sb_ui.get("track")
    if th is not None and th.collidepoint(pos):
        return "thumb"
    if tr is not None and tr.collidepoint(pos):
        return "track"
    return None


def _bb_wheel_delta(event, *, step=None):
    st = BB_MODAL_WHEEL_STEP if step is None else int(step)
    dy = getattr(event, "precise_y", None)
    if dy is not None:
        delta = int(round(-float(dy) * st))
    else:
        delta = -int(getattr(event, "y", 0) or 0) * st
    if delta == 0 and getattr(event, "y", 0):
        delta = -int(event.y) * st
    return delta


def _bb_pointer_xy(event, mx, my):
    pos = getattr(event, "pos", None)
    if pos is not None:
        return int(pos[0]), int(pos[1])
    return int(mx), int(my)


def _bb_rects_contain_point(px, py, *rects):
    for r in rects:
        if r is not None and r.collidepoint(px, py):
            return True
    return False


def _draw_bb_scrollbar(screen, sb_rect, body_h, content_h, scroll_px):
    sb_ui = _bb_scrollbar_layout(sb_rect, body_h, content_h, scroll_px)
    pygame.draw.rect(screen, (42, 42, 52), sb_rect)
    tr = sb_ui.get("track")
    th = sb_ui.get("thumb")
    if tr is not None:
        pygame.draw.rect(screen, (58, 58, 72), tr, border_radius=3)
    if th is not None:
        pygame.draw.rect(screen, (130, 140, 165), th, border_radius=3)
    return sb_ui


def _settings_modal_layout(state, sw, sh):
    """draw/layout 공통 — panel, body, scroll, field/pick rects."""
    if not state.get("show_settings"):
        return None
    panel, content_h, _body_vp = _settings_modal_metrics(sw, sh)
    body_rect, sb_rect, max_scroll, scroll = _settings_modal_body_layout(
        panel, state.get("settings_scroll"), content_h
    )
    state["settings_scroll"] = scroll
    field_rects = {}
    pick_rects = {}
    y = body_rect.y - scroll
    for item in _settings_modal_rows():
        if len(item) == 4:
            key, _label, _typ, _default = item
            kind = _typ
        else:
            key, _label, kind = item
        row_rect = pygame.Rect(body_rect.x, y, body_rect.width, EDITOR_BB_MODAL_ROW_H)
        if row_rect.bottom > body_rect.top and row_rect.top < body_rect.bottom:
            # XY 필드는 오른쪽 "픽" 버튼 공간을 남겨 둔다.
            pick_w = 36 if kind == "xy" else 0
            gap_w = 4 if kind == "xy" else 0
            fr_w = body_rect.width - 148 - (pick_w + gap_w)
            fr = pygame.Rect(panel.x + 160, y, max(40, fr_w), EDITOR_BB_MODAL_ROW_H - 2)
            field_rects[key] = fr
            if kind == "xy":
                pick_rects[key] = pygame.Rect(fr.right + 4, y, 36, EDITOR_BB_MODAL_ROW_H - 2)
        y += EDITOR_BB_MODAL_ROW_H
    save_b = pygame.Rect(panel.centerx - 105, panel.bottom - 40, 95, 32)
    canc_b = pygame.Rect(panel.centerx + 10, panel.bottom - 40, 95, 32)
    sb_ui = _bb_scrollbar_layout(sb_rect, body_rect.height, content_h, scroll)
    return {
        "panel": panel,
        "body": body_rect,
        "sb": sb_rect,
        "content_h": content_h,
        "max_scroll": max_scroll,
        "scroll": scroll,
        "sb_ui": sb_ui,
        "fields": field_rects,
        "picks": pick_rects,
        "save": save_b,
        "cancel": canc_b,
    }


def _settings_modal_rows():
    return (
        list(BASEBALL_EDITOR_SCALAR_KEYS)
        + [(k, lb, "xy") for k, lb in BASEBALL_EDITOR_XY_KEYS]
        + [(k, lb, "text") for k, lb, _ in BASEBALL_EDITOR_TEXT_KEYS]
    )


def layout_settings_modal_ui(state, sw, sh):
    """클릭 판정용 — draw_settings_modal 과 동일 좌표."""
    ui = _settings_modal_layout(state, sw, sh)
    if ui is None:
        return None
    return {
        "panel": ui["panel"],
        "fields": ui["fields"],
        "picks": ui["picks"],
        "save": ui["save"],
        "cancel": ui["cancel"],
        "body": ui["body"],
        "sb": ui["sb"],
        "sb_ui": ui["sb_ui"],
    }


def layout_zone_modal_ui(state, sw, sh):
    if not state.get("show_zone_modal"):
        return None
    panel = _modal_rect(sw, sh, 7)
    y = panel.y + 40
    rects = {}
    for key, _label in (
        ("mode", "규칙"),
        ("value", "값"),
        ("label", "표시"),
        ("radius_x", "가로 반경"),
        ("radius_y", "세로 반경"),
    ):
        fr = pygame.Rect(panel.x + 120, y, 260, EDITOR_BB_MODAL_ROW_H - 2)
        rects[key] = fr
        y += EDITOR_BB_MODAL_ROW_H + 4
    save_b = pygame.Rect(panel.centerx - 105, panel.bottom - 40, 95, 32)
    canc_b = pygame.Rect(panel.centerx + 10, panel.bottom - 40, 95, 32)
    del_b = pygame.Rect(panel.x + 12, panel.bottom - 40, 80, 32)
    return {"panel": panel, "fields": rects, "save": save_b, "cancel": canc_b, "delete": del_b}


def draw_settings_modal(screen, font, state, sw, sh):
    if not state.get("show_settings"):
        return None
    fields = state.get("settings_fields") or {}
    ui = _settings_modal_layout(state, sw, sh)
    if ui is None:
        return None
    panel = ui["panel"]
    body_rect = ui["body"]
    scroll = ui["scroll"]
    pygame.draw.rect(screen, (35, 35, 45), panel)
    pygame.draw.rect(screen, (180, 180, 200), panel, 2)
    screen.blit(
        font.render("야구장 설정 (world_data.baseball)", True, (255, 255, 200)),
        (panel.x + 12, panel.y + 8),
    )
    hint = "마우스 휠=스크롤 · 오른쪽 막대=드래그"
    screen.blit(font.render(hint, True, (110, 125, 145)), (panel.x + 12, panel.bottom - 72))
    prev_clip = screen.get_clip()
    screen.set_clip(body_rect)
    y = body_rect.y - scroll
    for item in _settings_modal_rows():
        if len(item) == 4:
            key, label, typ, _default = item
            kind = typ
        else:
            key, label, kind = item
        row_rect = pygame.Rect(body_rect.x, y, body_rect.width, EDITOR_BB_MODAL_ROW_H)
        if row_rect.bottom > body_rect.top and row_rect.top < body_rect.bottom:
            screen.blit(font.render(label, True, (200, 200, 200)), (panel.x + 12, y + 4))
            fr = ui["fields"].get(key)
            if fr is not None:
                pygame.draw.rect(screen, (50, 50, 60), fr)
                val = str(fields.get(key, ""))
                active = state.get("_edit_field") == key
                if active:
                    pygame.draw.rect(screen, (255, 215, 0), fr, 2)
                ed_txt.blit_field_value(
                    screen, font, val, fr, active=active, session=_te(state), trunc_limit=28
                )
            if kind == "xy":
                pr = ui["picks"].get(key)
                if pr is not None:
                    pygame.draw.rect(screen, (70, 90, 70), pr)
                    screen.blit(font.render("픽", True, (220, 255, 220)), (pr.x + 8, pr.y + 4))
        y += EDITOR_BB_MODAL_ROW_H
    screen.set_clip(prev_clip)
    _draw_bb_scrollbar(screen, ui["sb"], body_rect.height, ui["content_h"], scroll)
    save_b = ui["save"]
    canc_b = ui["cancel"]
    pygame.draw.rect(screen, (60, 100, 60), save_b, border_radius=4)
    pygame.draw.rect(screen, (100, 60, 60), canc_b, border_radius=4)
    screen.blit(font.render("저장", True, (255, 255, 255)), (save_b.x + 28, save_b.y + 6))
    screen.blit(font.render("닫기", True, (255, 255, 255)), (canc_b.x + 28, canc_b.y + 6))
    return layout_settings_modal_ui(state, sw, sh)


def draw_zone_modal(screen, font, state, sw, sh):
    if not state.get("show_zone_modal"):
        return None
    node = state.get("zone_edit_node")
    nm = str(getattr(node, "name", "") if node else "")
    panel = _modal_rect(sw, sh, 7)
    pygame.draw.rect(screen, (35, 45, 35), panel)
    pygame.draw.rect(screen, (140, 200, 140), panel, 2)
    screen.blit(font.render(f"점수 구역 — {nm}", True, (220, 255, 220)), (panel.x + 12, panel.y + 8))
    zf = state.get("zone_fields") or {}
    y = panel.y + 40
    rects = {}
    edit_key = state.get("_edit_zone_field")
    for key, label in (
        ("mode", "규칙"),
        ("value", "값"),
        ("label", "표시"),
        ("radius_x", "가로 반경(px)"),
        ("radius_y", "세로 반경(px)"),
    ):
        screen.blit(font.render(label, True, (200, 220, 200)), (panel.x + 12, y + 4))
        fr = pygame.Rect(panel.x + 120, y, 260, EDITOR_BB_MODAL_ROW_H - 2)
        pygame.draw.rect(screen, (50, 60, 50), fr)
        if edit_key == key:
            pygame.draw.rect(screen, (255, 215, 0), fr, 2)
        ed_txt.blit_field_value(
            screen,
            font,
            zf.get(key, ""),
            fr,
            active=(edit_key == key),
            session=_te(state),
        )
        rects[key] = fr
        y += EDITOR_BB_MODAL_ROW_H + 4
    if zf.get("mode") == "mode":
        pass
    hint_y = y + 4
    modes_txt = " / ".join(f"{a}:{b}" for a, b in ZONE_MODES)
    screen.blit(font.render(modes_txt[:52], True, (150, 170, 150)), (panel.x + 12, hint_y))
    screen.blit(
        font.render("Alt+휠: 크기 조절", True, (140, 160, 140)),
        (panel.x + 12, hint_y + 18),
    )
    save_b = pygame.Rect(panel.centerx - 105, panel.bottom - 40, 95, 32)
    canc_b = pygame.Rect(panel.centerx + 10, panel.bottom - 40, 95, 32)
    del_b = pygame.Rect(panel.x + 12, panel.bottom - 40, 80, 32)
    pygame.draw.rect(screen, (60, 100, 60), save_b, border_radius=4)
    pygame.draw.rect(screen, (100, 60, 60), canc_b, border_radius=4)
    pygame.draw.rect(screen, (120, 50, 50), del_b, border_radius=4)
    screen.blit(font.render("적용", True, (255, 255, 255)), (save_b.x + 28, save_b.y + 6))
    screen.blit(font.render("닫기", True, (255, 255, 255)), (canc_b.x + 28, canc_b.y + 6))
    screen.blit(font.render("삭제", True, (255, 220, 220)), (del_b.x + 18, del_b.y + 6))
    return {"panel": panel, "fields": rects, "save": save_b, "cancel": canc_b, "delete": del_b}


def handle_settings_modal_event(state, event, sw, sh, mx, my) -> bool:
    """휠·스크롤바 드래그. True면 이벤트 소비."""
    if not state.get("show_settings"):
        return False
    ui = _settings_modal_layout(state, sw, sh)
    if ui is None:
        return False
    body_rect = ui["body"]
    sb_rect = ui["sb"]
    panel = ui["panel"]
    sb_ui = ui["sb_ui"]
    if event.type == pygame.MOUSEWHEEL:
        px, py = _bb_pointer_xy(event, mx, my)
        delta = _bb_wheel_delta(event)
        if _bb_rects_contain_point(px, py, body_rect, sb_rect, panel):
            state["settings_scroll"] = max(
                0, min(ui["max_scroll"], int(state.get("settings_scroll") or 0) + delta)
            )
            return True
        return False
    if event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
        delta = BB_MODAL_WHEEL_STEP if event.button == 4 else -BB_MODAL_WHEEL_STEP
        state["settings_scroll"] = max(
            0, min(ui["max_scroll"], int(state.get("settings_scroll") or 0) + delta)
        )
        return True
    if event.type == pygame.MOUSEMOTION and state.get("settings_sb_drag"):
        sp = _bb_scroll_px_from_sb_my(event.pos[1], sb_ui)
        if sp is not None:
            state["settings_scroll"] = sp
        return True
    if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
        if state.get("settings_sb_drag"):
            state["settings_sb_drag"] = False
            return True
        return False
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        hit = _bb_modal_sb_hit(event.pos, sb_ui)
        if hit == "thumb":
            state["settings_sb_drag"] = True
            return True
        if hit == "track":
            sp = _bb_scroll_px_from_sb_my(event.pos[1], sb_ui)
            if sp is not None:
                state["settings_scroll"] = sp
            return True
    return False


def handle_settings_modal_click(state, mx, my, ui, flow, map_id) -> bool:
    if not ui:
        return False
    if ui["save"].collidepoint(mx, my):
        apply_settings_fields(flow, map_id, state.get("settings_fields") or {})
        state["show_settings"] = False
        state["pick_xy_key"] = None
        return True
    if ui["cancel"].collidepoint(mx, my):
        state["show_settings"] = False
        state["pick_xy_key"] = None
        return True
    for key, pr in (ui.get("picks") or {}).items():
        if pr.collidepoint(mx, my):
            state["pick_xy_key"] = key
            state["show_settings"] = False
            return True
    for key, fr in (ui.get("fields") or {}).items():
        if fr.collidepoint(mx, my):
            state["_edit_field"] = key
            _te(state).focus(str((state.get("settings_fields") or {}).get(key, "")))
            return True
    return ui["panel"].collidepoint(mx, my)


def handle_zone_modal_click(state, mx, my, ui, objs) -> Optional[str]:
    """반환: 'deleted' | 'saved' | 'closed' | None"""
    if not ui:
        return None
    node = state.get("zone_edit_node")
    if ui["save"].collidepoint(mx, my) and node is not None:
        apply_zone_fields_to_node(node, state.get("zone_fields") or {})
        state["show_zone_modal"] = False
        return "saved"
    if ui["cancel"].collidepoint(mx, my):
        state["show_zone_modal"] = False
        return "closed"
    if ui["delete"].collidepoint(mx, my) and node is not None:
        if node in objs:
            objs.remove(node)
        state["show_zone_modal"] = False
        state["zone_edit_node"] = None
        return "deleted"
    for key, fr in (ui.get("fields") or {}).items():
        if fr.collidepoint(mx, my):
            state["_edit_zone_field"] = key
            _te(state).focus(str((state.get("zone_fields") or {}).get(key, "")))
            return None
    return None


def handle_left_click(
    state, mx, my, tops, sidebar_w, objs, flow, map_id, *, list_scroll=0
) -> Optional[str]:
    """반환: preset asset name | 'settings' | None"""
    if not is_baseball_map(map_id):
        return None
    tool = str(state.get("tool") or "ZONES")
    tw = max(36, (sidebar_w - 32) // 3)
    btn_z = pygame.Rect(8, tops["tools"], tw, 26)
    btn_m = pygame.Rect(btn_z.right + 4, tops["tools"], tw, 26)
    btn_s = pygame.Rect(btn_m.right + 4, tops["tools"], tw, 26)
    if btn_z.collidepoint(mx, my):
        state["tool"] = "ZONES"
        return None
    if btn_m.collidepoint(mx, my):
        state["tool"] = "MARKERS"
        return None
    if btn_s.collidepoint(mx, my):
        state["tool"] = "SETTINGS"
        state["settings_fields"] = load_settings_fields(flow, map_id)
        state["settings_scroll"] = 0
        state["show_settings"] = True
        return None
    settings_btn = pygame.Rect(8, tops["settings_btn"], sidebar_w - 16, 28)
    if settings_btn.collidepoint(mx, my):
        state["settings_fields"] = load_settings_fields(flow, map_id)
        state["settings_scroll"] = 0
        state["show_settings"] = True
        return "settings"
    tool = str(state.get("tool") or "ZONES")
    if tool == "ZONES":
        pw = max(48, (sidebar_w - 24) // 2)
        y = tops["presets"]
        preset_rows = list(BASEBALL_ZONE_PRESETS) + list(BASEBALL_SCOREBOARD_PRESETS)
        for i, (asset, _label) in enumerate(preset_rows):
            col = i % 2
            row = i // 2
            r = pygame.Rect(8 + col * (pw + 4), y + row * 30, pw, 26)
            if r.collidepoint(mx, my):
                return asset
    y0 = tops["list"] - int(list_scroll or 0)
    for row in placed_object_rows(objs):
        r = pygame.Rect(8, y0, sidebar_w - 16, EDITOR_BB_LINE_H)
        if r.collidepoint(mx, my):
            node = row["node"]
            state["zone_edit_node"] = node
            state["list_select_node"] = node
            if is_baseball_zone_object(node):
                sync_zone_fields_from_node(node, state.setdefault("zone_fields", {}))
                state["show_zone_modal"] = True
            return None
        y0 += EDITOR_BB_LINE_H
    return None


def apply_xy_pick(state, wx: float, wy: float, flow, map_id: str) -> bool:
    key = state.get("pick_xy_key")
    if not key:
        return False
    fields = state.setdefault("settings_fields", load_settings_fields(flow, map_id))
    fields[key] = f"{float(wx):g}, {float(wy):g}"
    state["pick_xy_key"] = None
    state["show_settings"] = True
    return True


def handle_textinput(state, text: str, flow, map_id) -> bool:
    t = str(text or "")
    if not t:
        return False
    te = _te(state)
    ef = state.get("_edit_field")
    if ef and state.get("show_settings"):
        fields = state.setdefault("settings_fields", {})
        fields[ef] = te.insert(str(fields.get(ef, "")), t)
        return True
    zef = state.get("_edit_zone_field")
    if zef and state.get("show_zone_modal"):
        zf = state.setdefault("zone_fields", {})
        zf[zef] = te.insert(str(zf.get(zef, "")), t)
        return True
    return False


def handle_keydown(state, event, flow, map_id) -> bool:
    """설정/구역 모달 텍스트 입력."""
    if event.type != pygame.KEYDOWN:
        return False
    key = event.key
    if key == pygame.K_ESCAPE:
        state.pop("_edit_field", None)
        state.pop("_edit_zone_field", None)
        if state.get("show_settings"):
            state["show_settings"] = False
            state["settings_sb_drag"] = False
            return True
        if state.get("show_zone_modal"):
            state["show_zone_modal"] = False
            return True
        return False
    te = _te(state)
    for slot, store_key in (("_edit_field", "settings_fields"), ("_edit_zone_field", "zone_fields")):
        ef = state.get(slot)
        if not ef:
            continue
        fields = state.setdefault(store_key, {})
        if key == pygame.K_RETURN:
            state.pop("_edit_field", None)
            state.pop("_edit_zone_field", None)
            return True
        nt, handled = te.keydown(str(fields.get(ef, "")), event)
        if handled:
            fields[ef] = nt
            return True
        return True
    return False


def handle_map_click(
    state,
    wx,
    wy,
    swx,
    swy,
    objs,
    npcs,
    flow,
    map_id,
    *,
    pick_top_node,
    selected_asset,
):
    """맵 클릭 — 구역 배치·핀 픽·구역 선택. 반환: (new_selected_asset, consumed)."""
    if state.get("pick_xy_key"):
        if apply_xy_pick(state, swx, swy, flow, map_id):
            return None, True
    asset = selected_asset
    if asset and str(asset).startswith("bbzone_"):
        place_zone_object(str(asset), swx, swy, objs)
        return None, True
    if asset and str(asset).startswith("bbscoreboard"):
        place_scoreboard_object(str(asset), swx, swy, objs)
        return None, True
    tool = str(state.get("tool") or "ZONES")
    if tool == "ZONES":
        hit = pick_top_node(objs, npcs, wx, wy)
        if hit is not None and is_placed_object(hit):
            return None, False
    elif tool == "MARKERS":
        fields = state.setdefault("settings_fields", load_settings_fields(flow, map_id))
        for key in ("plate", "tee", "cam_fixed"):
            if str(state.get("_marker_pick") or "") == key:
                fields[key] = f"{float(swx):g}, {float(wy):g}"
                apply_settings_fields(flow, map_id, fields)
                state["_marker_pick"] = None
                return None, True
    return asset, False


def on_map_switch(state, flow, map_id: str, objs=None) -> None:
    state["settings_fields"] = load_settings_fields(flow, map_id)
    state["zone_edit_node"] = None
    state["show_zone_modal"] = False
    state["pick_xy_key"] = None
    state.pop("_edit_field", None)
    state.pop("_edit_zone_field", None)
    state.pop("_marker_pick", None)
    if objs and is_baseball_map(map_id):
        for o in objs:
            if is_scoreboard_object(o):
                apply_scoreboard_defaults(o)
                continue
            if not is_baseball_zone_object(o):
                continue
            if zone_uses_ellipse_fallback(o):
                o.is_visible = False
                we = getattr(o, "_world_entry", None)
                if not isinstance(we, dict):
                    we = {}
                    o._world_entry = we
                bz = we.get("baseball_zone")
                if not isinstance(bz, dict):
                    od = OBJ_ASSETS.get(getattr(o, "name", ""), {}) or {}
                    bz = dict(od.get("baseball_zone") or {})
                    we["baseball_zone"] = bz
                bz.setdefault("render", "ellipse")
                if not getattr(o, "obj_def", None):
                    o.obj_def = dict(OBJ_ASSETS.get(getattr(o, "name", ""), {}) or {})

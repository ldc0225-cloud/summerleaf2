import os

# 한글·중일 등 IME 후보 창(SDL). pygame/SDL 로드 전에 설정하는 것이 안전합니다.
os.environ.setdefault("SDL_IME_SHOW_UI", "1")

import pygame, math, json
from data import CONFIG, OBJ_ASSETS, CHAR_ASSETS, UI_FONT_FILES
from entity_defs import (
    FLOW_EVENT_LINKED_HEADER,
    build_editor_flow_catalog_rows,
    build_editor_placed_list_rows,
)
from char_editor_ui import (
    any_char_modal_open,
    char_def_modal,
    char_inst_modal,
    close_all_char_modals,
    obj_def_modal,
    obj_inst_modal,
    presence_zone_modal,
)
from flow import (
    GameFlow,
    _flow_entity_catalog_entry,
    _flow_zone_entry,
    build_entity_flow_diagram,
    build_zone_flow_diagram,
    merge_event_catalog,
    progress_value_key,
)
from field_runtime import build_step_from_editor_fields, fill_editor_fields_from_step
from engine import FieldItem, BaseCharacter, MaskWalkingCharacter
from render_align import (
    bg_anchor,
    blit_topleft_bottom_center,
    left_edge_bottom_center_x,
    map_surface_to_world_xy,
    snap_render_zoom,
    world_to_map_surface_xy,
)

# events.json 섹션 (에디터 목록·저장 공통)
EDITOR_EVENT_SECTIONS = ("LOCAL", "GLOBAL", "SYNC", "FRAGMENTS")

# 에디터 레이아웃 — 좌·우 목록과 하단 설정을 넓히고 중앙 작업창은 그만큼 줄임
EDITOR_SIDEBAR_W = 292
EDITOR_TOP_BAR_H = 76
EDITOR_STATUS_BAR_H = 34
EDITOR_INSPECTOR_H = 86
EDITOR_LINE_H = 28
EDITOR_MAP_BOTTOM_H = EDITOR_STATUS_BAR_H + EDITOR_INSPECTOR_H
EDITOR_RIGHT_STEPS_TOP = EDITOR_TOP_BAR_H + 42


def _editor_map_view_h(screen_h, top_bar_h=EDITOR_TOP_BAR_H):
    """중앙 맵 작업면 높이(하단 설정·상태줄 제외)."""
    return max(120, int(screen_h) - int(top_bar_h) - EDITOR_MAP_BOTTOM_H)


def _editor_sidebar_list_bottom(screen_h):
    """좌·우 리스트 스크롤/클립 하단(인스펙터 위)."""
    return int(screen_h) - EDITOR_MAP_BOTTOM_H


def _editor_left_list_tops(top_bar_h):
    """좌측 리스트 시작 Y — metrics / 그리기 / 클릭 공통."""
    tb = int(top_bar_h)
    return {
        "flow": tb + 40,
        "map_tools": tb + 38,
        "map_zone_btn": tb + 74,
        "map_bgzone_btn": tb + 108,
        "map_presence_btn": tb + 142,
        "map_objects": tb + 110,
        "map_zones": tb + 110,
        "map_bgzones": tb + 142,
        "map_presences": tb + 176,
    }


def _editor_entity_world_rect(o):
    """월드 픽셀 격자에 맞춘 AABB. 가로는 런타임과 동일하게 left_edge(발 정수 열, 홀수 폭 floor)."""
    iw, ih = o.image.get_size()
    frx = int(round(float(o.pos[0])))
    fry = int(round(float(o.pos[1])))
    left = float(left_edge_bottom_center_x(frx, iw))
    top = float(fry) - float(ih)
    return pygame.Rect(int(left), int(top), iw, ih)


def _editor_pick_alpha_min():
    try:
        return max(1, min(255, int(CONFIG.get("EDITOR_PICK_ALPHA_MIN", 16) or 16)))
    except Exception:
        return 16


def _editor_surface_pick_mask(surf, *, alpha_min=None):
    """스프라이트 투명 영역 제외 픽용 bitmask (surf id 기준 캐시)."""
    if surf is None:
        return None
    if alpha_min is None:
        alpha_min = _editor_pick_alpha_min()
    cache = getattr(surf, "_editor_pick_mask_cache", None)
    if isinstance(cache, dict) and cache.get("alpha_min") == alpha_min and cache.get("surf_id") == id(surf):
        return cache.get("mask")
    try:
        mask = pygame.mask.from_surface(surf, alpha_min)
    except Exception:
        mask = None
    try:
        surf._editor_pick_mask_cache = {"surf_id": id(surf), "alpha_min": alpha_min, "mask": mask}
    except Exception:
        pass
    return mask


def _editor_surface_alpha_hit(surf, rect, px, py, *, alpha_min=None):
    """rect(스프라이트 배치) 안 (px,py)가 불투명 픽셀인지."""
    if surf is None or rect is None:
        return False
    try:
        if not rect.collidepoint(float(px), float(py)):
            return False
    except Exception:
        return False
    lx = int(px) - int(rect.x)
    ly = int(py) - int(rect.y)
    try:
        iw, ih = surf.get_size()
    except Exception:
        return False
    if lx < 0 or ly < 0 or lx >= iw or ly >= ih:
        return False
    if alpha_min is None:
        alpha_min = _editor_pick_alpha_min()
    mask = _editor_surface_pick_mask(surf, alpha_min=alpha_min)
    if mask is not None:
        try:
            return bool(mask.get_at((lx, ly)))
        except Exception:
            pass
    try:
        c = surf.get_at((lx, ly))
        if len(c) >= 4:
            return int(c[3]) >= int(alpha_min)
        return True
    except Exception:
        return False


def _editor_entity_alpha_hit(o, wx, wy, *, alpha_min=None):
    """월드 좌표가 스프라이트의 보이는(불투명) 픽셀 위인지."""
    img = getattr(o, "image", None)
    if img is None:
        return False
    return _editor_surface_alpha_hit(img, _editor_entity_world_rect(o), wx, wy, alpha_min=alpha_min)


def _editor_entity_alpha_hit_rect(o, sel_rect, *, alpha_min=None):
    """선택 사각형과 스프라이트 불투명 영역이 겹치는지."""
    img = getattr(o, "image", None)
    if img is None:
        return False
    r = _editor_entity_world_rect(o)
    try:
        inter = r.clip(sel_rect)
    except Exception:
        return False
    if inter.width <= 0 or inter.height <= 0:
        return False
    if alpha_min is None:
        alpha_min = _editor_pick_alpha_min()
    mask = _editor_surface_pick_mask(img, alpha_min=alpha_min)
    if mask is None:
        return True
    try:
        chunk = pygame.mask.Mask((int(inter.width), int(inter.height)), fill=True)
        if mask.overlap(chunk, (int(inter.x - r.x), int(inter.y - r.y))) is not None:
            return True
    except Exception:
        pass
    return False


def _editor_pick_top_node(objs, npcs, wx, wy):
    """화면상 위에 가까운 것 우선(레이어·y 정렬)으로 한 개만."""
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
            return y - h
        return y

    objs_to_check = sorted(objs + npcs, key=lambda x: (getattr(x, "layer", 0), _ysort_y(x)), reverse=True)
    for o in objs_to_check:
        if _editor_entity_alpha_hit(o, wx, wy):
            return o
    return None


def editor_snap_pick_world_xy(wx, wy, grid_px, fine_shift_held):
    """
    스텝 좌표 픽 / 존 사각형 지정 등: 기본은 월드 격자(바닥)에 스냅.
    Shift 누르면 1픽셀 단위(반올림) 미세 — 오브젝트 배치(swx)와 동일 정책.
    """
    if fine_shift_held:
        return int(round(float(wx))), int(round(float(wy)))
    g = max(1, int(grid_px))
    return (int(float(wx)) // g) * g, (int(float(wy)) // g) * g


def _editor_draw_height_span_on_map(
    surf,
    start_x,
    start_y,
    world_x,
    world_y,
    height_px,
    bg_orig_w,
    bg_orig_h,
    scaled_w,
    scaled_h,
    selected=False,
):
    """
    맵 편집용: 배경과 동일 scale 비율로 월드→맵 픽셀 변환 후 세로선(스프라이트 발 열과 동일).
    """
    try:
        h = float(height_px)
    except (TypeError, ValueError):
        return
    if h <= 0.0:
        return
    bg_ix = int(round(float(start_x)))
    bg_iy = int(round(float(start_y)))
    fpx, anchor_y_scr = world_to_map_surface_xy(
        bg_ix, bg_iy, float(world_x), float(world_y), bg_orig_w, bg_orig_h, scaled_w, scaled_h, 0.0
    )
    _, feet_y_scr = world_to_map_surface_xy(
        bg_ix, bg_iy, float(world_x), float(world_y), bg_orig_w, bg_orig_h, scaled_w, scaled_h, h
    )
    x = int(fpx)
    y0, y1 = (int(feet_y_scr), int(anchor_y_scr)) if feet_y_scr <= anchor_y_scr else (int(anchor_y_scr), int(feet_y_scr))
    if abs(y1 - y0) < 1:
        return
    z_vis = float(scaled_w) / float(max(1, int(bg_orig_w)))
    lw = max(1, min(4, int(round(z_vis * 1.2))))
    if selected:
        line_c, ac, fc = (68, 138, 255), (110, 190, 255), (150, 215, 255)
    else:
        line_c, ac, fc = (52, 108, 188), (85, 145, 200), (115, 175, 215)
    pygame.draw.line(surf, line_c, (x, y0), (x, y1), lw)
    r = max(2, int(round(2.5 * z_vis)))
    pygame.draw.circle(surf, ac, (x, int(anchor_y_scr)), r, 1)
    pygame.draw.circle(surf, fc, (x, int(feet_y_scr)), r, 1)


def _editor_entity_play_hidden(ent) -> bool:
    """플레이 중 숨김(is_visible=false) — 에디터에서는 윤곽 고스트로 표시."""
    return not bool(getattr(ent, "is_visible", True))


def _editor_draw_hidden_entity_ghost(surf, s_img, x, y, *, selected=False):
    """
    is_visible=false 엔티티: 반투명 실루엣 + 윤곽선 (맵 편집·배치용).
    플레이어 화면과 달리 에디터에서는 위치 확인·선택이 가능해야 함.
    """
    try:
        w, h = s_img.get_width(), s_img.get_height()
    except Exception:
        return
    if w < 1 or h < 1:
        return
    ghost = s_img.copy()
    ghost.set_alpha(72 if selected else 48)
    surf.blit(ghost, (int(x), int(y)))
    outline = (255, 210, 90) if selected else (110, 210, 255)
    pygame.draw.rect(surf, outline, (int(x), int(y), w, h), 3 if selected else 2)
    # 모서리 꺾쇠 — 숨김 상태임을 한눈에 구분
    corner = max(4, min(14, w // 5, h // 5))
    cx, cy = int(x), int(y)
    for ox, oy, dx, dy in (
        (0, 0, 1, 1),
        (w, 0, -1, 1),
        (0, h, 1, -1),
        (w, h, -1, -1),
    ):
        px, py = cx + ox, cy + oy
        pygame.draw.line(surf, outline, (px, py), (px + dx * corner, py), 2)
        pygame.draw.line(surf, outline, (px, py), (px, py + dy * corner), 2)


def _editor_nodes_in_world_rect(objs, npcs, x1, y1, x2, y2):
    """월드 좌표 사각형과 스프라이트 AABB가 겹치는 오브젝트·NPC 전부."""
    ax, bx = min(float(x1), float(x2)), max(float(x1), float(x2))
    ay, by = min(float(y1), float(y2)), max(float(y1), float(y2))
    rw, rh = max(1, int(math.ceil(bx - ax))), max(1, int(math.ceil(by - ay)))
    r = pygame.Rect(int(ax), int(ay), rw, rh)
    out = []
    for o in sorted(objs + npcs, key=lambda x: (getattr(x, "layer", 0), x.pos[1])):
        if _editor_entity_alpha_hit_rect(o, r):
            out.append(o)
    return out


def _editor_event_preview_map(edata, map_list):
    """에디터에서 스텝 미리보기용 맵: work_map 우선, 그다음 일반 map_id."""
    wm = str(edata.get("work_map") or "").strip()
    if wm and wm in map_list:
        return wm
    mid = edata.get("map_id")
    if mid in ("ALL", "__GLOBAL__", "", None):
        return None
    mid = str(mid).strip() if mid is not None else ""
    if mid in map_list:
        return mid
    return None


def _parse_editor_json_kv_blob(text: str):
    """
    에디터 Result Opt / Zone cond_opt 등: 객체 1개를 dict 로 파싱.
    - 권장: "progress_x": 1001  (중괄호 없이, 쌍따옴표)
    - 허용: { "progress_x": 1001 }  전체 JSON
    실패 시 None.
    """
    s = (text or "").strip()
    if not s:
        return {}
    try:
        if s.startswith("{"):
            obj = json.loads(s)
        else:
            obj = json.loads("{" + s + "}")
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _result_to_res_fields(edata):
    res = edata.get("result") or {}
    prog = res.get("mainprogress", "")
    opt = {k: v for k, v in res.items() if k != "mainprogress"}
    if not opt:
        return ("" if prog is None else str(prog)), ""
    body = json.dumps(opt, ensure_ascii=False)
    if body.startswith("{") and body.endswith("}"):
        body = body[1:-1].strip()
    return ("" if prog is None else str(prog)), body


def _escape_fields_from_edata(edata):
    ex = edata.get("escape") if isinstance(edata.get("escape"), dict) else {}
    em = (ex.get("mode") or "none").strip().lower()
    if em not in ("none", "click", "key", "condition"):
        em = "none"
    ea = (ex.get("action") or "end").strip().lower()
    if ea not in ("end", "break_loop"):
        ea = "end"
    return em, ea, str(ex.get("key") or ""), str(ex.get("condition") or "")


def _editor_fill_event_settings_from_edata(cat, eid, edata):
    """이벤트 설정 모달 필드 채우기 (EVENT 목록·FLOW 차트 공통)."""
    rp, ro = _result_to_res_fields(edata)
    pr = edata.get("priority", 100)
    try:
        pr = int(pr)
    except (TypeError, ValueError):
        pr = 100
    em, ea, ek, ec = _escape_fields_from_edata(edata)
    return {
        "cat": cat,
        "eid": eid,
        "title": edata.get("title", eid),
        "res_prog": rp,
        "res_opt": ro,
        "trigger": str(edata.get("trigger") or "auto"),
        "condition": str(edata.get("condition") or ""),
        "priority": str(pr),
        "work_map": str(edata.get("work_map") or ""),
        "escape_mode": em,
        "escape_action": ea,
        "escape_key": ek,
        "escape_condition": ec,
    }


# FLOW 네트워크 다이어그램 — 엔티티 → binding → 이벤트 → progress
_FLOW_ROW_Y_VAR = {"var": 44, "state": 128, "entity": 268, "zone": 268, "event": 408}
_FLOW_ROW_Y_ENTITY = {"entity": 56, "bind": 168, "event": 308, "state": 448}
_FLOW_ROW_Y_ZONE = {"zone": 56, "bind": 168, "event": 308, "state": 448}
_FLOW_NODE_W = 152
_FLOW_NODE_H = 52
_FLOW_NODE_GAP = 18


def _editor_flow_diagram_layout(diagram):
    mode = (diagram or {}).get("mode")
    if mode == "entity":
        return ("entity", "bind", "event", "state"), dict(_FLOW_ROW_Y_ENTITY)
    if mode == "zone":
        return ("zone", "bind", "event", "state"), dict(_FLOW_ROW_Y_ZONE)
    return ("var", "state", "entity", "zone", "event"), dict(_FLOW_ROW_Y_VAR)


def _editor_flow_node_sort_key(node):
    sk = node.get("sort_key", node.get("label", ""))
    if node.get("kind") == "state":
        try:
            return (1, int(str(sk)))
        except (TypeError, ValueError):
            return (2, str(sk))
    return (0, str(sk))


def _editor_flow_draw_arrow(surface, color, p0, p1, width=2, head=8):
    """p0 → p1 방향 화살표."""
    pygame.draw.line(surface, color, p0, p1, width)
    dx = float(p1[0] - p0[0])
    dy = float(p1[1] - p0[1])
    ln = math.hypot(dx, dy)
    if ln < 1.0:
        return
    ux, uy = dx / ln, dy / ln
    px, py = -uy, ux
    tip = (int(p1[0]), int(p1[1]))
    back = (int(p1[0] - ux * head), int(p1[1] - uy * head))
    p2 = (int(back[0] + px * head * 0.45), int(back[1] + py * head * 0.45))
    p3 = (int(back[0] - px * head * 0.45), int(back[1] - py * head * 0.45))
    pygame.draw.polygon(surface, color, [tip, p2, p3])


def _editor_flow_open_entity_modal(name, entity_kind, *, on_map=False, objs=None, npcs=None):
    """FLOW 차트·사이드바 — 타입/맵 인스턴스 상호작용 모달."""
    nm = str(name or "").strip()
    if not nm:
        return
    ek = str(entity_kind or "").lower()
    if on_map:
        if ek in ("char", "npc"):
            for n in npcs or []:
                if getattr(n, "name", None) == nm:
                    char_inst_modal.open(n)
                    return
        else:
            for o in objs or []:
                if getattr(o, "name", None) == nm:
                    obj_inst_modal.open(o)
                    return
    _editor_open_interact_type_modal(nm)


def _editor_flow_paint_diagram(surface, area, diagram, scroll_x, scroll_y, font, title_font):
    """
    FLOW 작업화면 — 캐릭터/오브젝트·binding·이벤트·progress 상자와 화살표.
    """
    hits = []
    surface.fill((22, 24, 30))
    if not diagram or (not diagram.get("var") and not diagram.get("entity_name")):
        surface.blit(font.render("왼쪽에서 항목 선택", True, (160, 170, 190)), (24, 40))
        return hits

    nodes = diagram.get("nodes") or []
    edges = diagram.get("edges") or []
    scroll = max(0, int(scroll_y or 0))
    scroll_h = max(0, int(scroll_x or 0))
    ox = int(area.x) - scroll_h
    oy = int(area.y) - scroll
    aw = max(320, int(area.width))

    is_entity = diagram.get("mode") == "entity"
    is_zone = diagram.get("mode") == "zone"
    if is_zone:
        title = f"FLOW · BOX {diagram.get('zone_name', '')}"
        legend = "이벤트 박스 → 트리거/조건 → 이벤트 → progress"
    elif is_entity:
        ek = diagram.get("entity_kind", "obj")
        tag = "NPC" if ek == "npc" else "OBJ"
        title = f"FLOW · {tag} {diagram.get('entity_name', '')}"
        legend = "캐릭터/오브젝트 → 조건(binding) → 이벤트 → progress"
    else:
        title = f"FLOW · {diagram.get('var')}"
        legend = "변수 → 상태 → 오브젝트/NPC → 이벤트 → result(상태)"

    surface.blit(title_font.render(title, True, (255, 230, 160)), (ox + 12, oy + 8))
    leg_y = oy + 28
    surface.blit(font.render(legend, True, (130, 145, 165)), (ox + 12, leg_y))
    note = str(diagram.get("note") or "")
    if note:
        surface.blit(font.render(note, True, (200, 140, 140)), (ox + 12, leg_y + 18))

    if not nodes:
        surface.blit(
            font.render("연결된 binding·이벤트가 없습니다.", True, (200, 160, 160)),
            (ox + 24, oy + 100),
        )
        return hits

    kind_styles = {
        "var": ((42, 38, 62), (180, 160, 255)),
        "state": ((55, 48, 28), (220, 190, 90)),
        "entity": ((48, 42, 30), (180, 150, 90)),
        "bind": ((38, 48, 58), (100, 180, 220)),
        "zone": ((40, 52, 40), (130, 200, 130)),
        "event": ((32, 42, 58), (120, 160, 220)),
    }
    row_kinds, row_y_map = _editor_flow_diagram_layout(diagram)
    by_kind = {k: [] for k in row_kinds}
    for n in nodes:
        k = n.get("kind") or "event"
        if k in by_kind:
            by_kind[k].append(n)

    node_rect = {}
    for kind in row_kinds:
        row = sorted(by_kind[kind], key=_editor_flow_node_sort_key)
        if not row:
            continue
        ncol = len(row)
        span = ncol * (_FLOW_NODE_W + _FLOW_NODE_GAP) - _FLOW_NODE_GAP
        x0 = ox + max(20, (aw - span) // 2)
        ry = oy + row_y_map.get(kind, 200)
        for i, n in enumerate(row):
            r = pygame.Rect(
                x0 + i * (_FLOW_NODE_W + _FLOW_NODE_GAP),
                ry,
                _FLOW_NODE_W,
                _FLOW_NODE_H,
            )
            node_rect[n["id"]] = r

    def _anchor_bottom_mid(rect):
        return (rect.centerx, rect.bottom)

    def _anchor_top_mid(rect):
        return (rect.centerx, rect.top)

    def _anchor_side_toward(rect, target_x):
        if target_x < rect.centerx:
            return (rect.left, rect.centery)
        return (rect.right, rect.centery)

    for e in edges:
        r0 = node_rect.get(e.get("from"))
        r1 = node_rect.get(e.get("to"))
        if not r0 or not r1:
            continue
        col = (255, 170, 70) if e.get("cycle") else (100, 175, 230)
        k0 = (e.get("from") or "").split(":", 1)[0]
        k1 = (e.get("to") or "").split(":", 1)[0]
        if k0 == "evt" and k1 == "state" and r1.centery < r0.centery:
            p0 = _anchor_side_toward(r0, r1.centerx)
            p1 = _anchor_side_toward(r1, r0.centerx)
            mid_x = max(r0.right, r1.right) + 36
            pts = [p0, (mid_x, p0[1]), (mid_x, p1[1]), p1]
            for i in range(len(pts) - 1):
                _editor_flow_draw_arrow(surface, col, pts[i], pts[i + 1], width=2)
        elif r1.centery > r0.centery:
            _editor_flow_draw_arrow(
                surface, col, _anchor_bottom_mid(r0), _anchor_top_mid(r1), width=2
            )
        else:
            _editor_flow_draw_arrow(
                surface, col, r0.center, r1.center, width=2
            )
        lbl = str(e.get("label") or "")
        if lbl:
            mx = (r0.centerx + r1.centerx) // 2
            my = (r0.centery + r1.centery) // 2
            surface.blit(font.render(lbl[:22], True, col), (mx - 20, my - 8))

    default_val = str(diagram.get("default") or "")
    for n in nodes:
        r = node_rect.get(n["id"])
        if not r:
            continue
        kind = n.get("kind") or "event"
        fill, border = kind_styles.get(kind, ((40, 40, 50), (140, 140, 160)))
        if kind == "state" and default_val and n.get("label") == f"= {default_val}":
            fill = (68, 58, 32)
            border = (255, 200, 90)
        pygame.draw.rect(surface, fill, r, border_radius=6)
        pygame.draw.rect(surface, border, r, 2, border_radius=6)
        surface.blit(font.render(n.get("label", ""), True, (245, 245, 250)), (r.x + 8, r.y + 10))
        sub = str(n.get("sublabel") or "")
        if sub:
            surface.blit(font.render(sub[:22], True, (160, 170, 185)), (r.x + 8, r.y + 28))
        hit = dict(n.get("hit") or {})
        if hit.get("action"):
            row = dict(hit)
            row["rect"] = r.copy()
            hits.append(row)

    return hits


def _editor_flow_diagram_content_size(diagram, view_w):
    """FLOW 다이어그램 콘텐츠 가로·세로 범위 (스크롤/패닝 상한)."""
    if not diagram:
        return 800, 480
    nodes = diagram.get("nodes") or []
    _, row_y_map = _editor_flow_diagram_layout(diagram)
    kinds = {n.get("kind") for n in nodes}
    max_y = 0
    for k in kinds:
        max_y = max(max_y, row_y_map.get(k, 0))
    content_h = max(520, max_y + _FLOW_NODE_H + 100)
    by_kind = {}
    for n in nodes:
        by_kind.setdefault(n.get("kind") or "event", []).append(n)
    max_cols = max((len(v) for v in by_kind.values()), default=1)
    content_w = max(
        int(view_w),
        40 + max_cols * (_FLOW_NODE_W + _FLOW_NODE_GAP),
    )
    return content_w, content_h


def _editor_flow_diagram_content_height(diagram, view_w=800):
    return _editor_flow_diagram_content_size(diagram, view_w)[1]


def _draw_dropdown_with_scrollbar(screen, font, rect, options, selected_index, scroll_px, item_h, colors):
    """
    드롭다운 리스트 + 스크롤바 (윈도우 스타일 느낌의 최소 구현).
    - rect: 리스트 영역
    - scroll_px: 픽셀 스크롤 (0..max)
    """
    bg = colors.get("bg", (28, 28, 36))
    border = colors.get("border", (150, 155, 175))
    hover = colors.get("hover", (52, 56, 70))
    cur_bg = colors.get("cur_bg", (60, 60, 90))
    text = colors.get("text", (235, 235, 240))
    text_dim = colors.get("text_dim", (200, 200, 200))
    sb_track = colors.get("sb_track", (18, 18, 24))
    sb_thumb = colors.get("sb_thumb", (110, 120, 150))
    sb_thumb2 = colors.get("sb_thumb2", (140, 150, 180))

    pygame.draw.rect(screen, bg, rect)
    pygame.draw.rect(screen, border, rect, 1)

    n_opt = len(options or [])
    total_h = n_opt * item_h
    vis_h = max(1, rect.height)
    max_scroll = max(0, total_h - vis_h)
    sp = int(max(0, min(max_scroll, scroll_px or 0)))

    # rows
    prev_clip = screen.get_clip()
    screen.set_clip(rect)
    mx, my = pygame.mouse.get_pos()
    for i, opt in enumerate(options or []):
        iy = rect.y + i * item_h - sp
        if iy + item_h <= rect.y or iy >= rect.bottom:
            continue
        row = pygame.Rect(rect.x, iy, rect.width, item_h)
        is_cur = (i == selected_index)
        is_hover = row.collidepoint(mx, my)
        if is_cur:
            pygame.draw.rect(screen, cur_bg, row)
        elif is_hover:
            pygame.draw.rect(screen, hover, row)
        txt = str(opt)
        if len(txt) > 36:
            txt = txt[:33] + "..."
        screen.blit(font.render(txt, True, text if (is_cur or is_hover) else text_dim), (row.x + 6, row.y + 4))
    screen.set_clip(prev_clip)

    track = None
    thumb = None
    thumb_h = None

    # scrollbar
    if max_scroll > 0:
        sb_w = 10
        track = pygame.Rect(rect.right - sb_w, rect.y + 1, sb_w - 1, rect.height - 2)
        pygame.draw.rect(screen, sb_track, track)
        thumb_h = max(18, int(track.height * (vis_h / total_h)))
        thumb_y = track.y + int((track.height - thumb_h) * (sp / max_scroll))
        thumb = pygame.Rect(track.x + 1, thumb_y, track.width - 2, thumb_h)
        pygame.draw.rect(screen, sb_thumb, thumb, border_radius=3)
        pygame.draw.rect(screen, sb_thumb2, thumb, 1, border_radius=3)
    return {
        "max_scroll": max_scroll,
        "scroll_px": sp,
        "track": track,
        "thumb": thumb,
        "thumb_h": thumb_h,
    }


def _ui_font_options():
    try:
        return sorted((UI_FONT_FILES or {}).keys())
    except Exception:
        return ["default"]


def _obj_asset_name_options():
    try:
        return sorted(OBJ_ASSETS.keys())
    except Exception:
        return []


OVERLAY_UI_ANCHORS = ["center", "top_left", "top_right", "bottom_left", "bottom_right"]
OVERLAY_UI_MODES = ["fade", "scroll"]
OVERLAY_UI_SCROLL = ["left", "right", "up", "down"]
OVERLAY_UI_CONTENT = ["text", "image"]
OVERLAY_UI_ACTION = ["show", "remove"]


def _overlay_ui_dropdown_options(field_key):
    fk = (field_key or "").strip()
    if fk == "font":
        return _ui_font_options()
    if fk == "object":
        return _obj_asset_name_options()
    if fk == "anchor":
        return list(OVERLAY_UI_ANCHORS)
    if fk == "mode":
        return list(OVERLAY_UI_MODES)
    if fk == "scroll_enter":
        return list(OVERLAY_UI_SCROLL)
    if fk == "content":
        return list(OVERLAY_UI_CONTENT)
    if fk == "action":
        return list(OVERLAY_UI_ACTION)
    return []


# 스텝 설정 모달 본문 한 줄 높이 (왼쪽 옵션 제목 2줄 + 입력칸)
STEP_BODY_ROW_H = 50
STEP_MODAL_LABEL_W = 158
STEP_OVERLAY_SB_W = 12


def _step_settings_panel_rect(sw, sh, step_fields):
    ft = (step_fields.get("type") or "MOVE").upper()
    rows = _step_field_rows(ft)
    body_rows = max(1, len(rows))
    ph = min(max(420, 120 + body_rows * STEP_BODY_ROW_H + 80), int(sh * 0.92))
    if ft == "OVERLAY_UI":
        ph = max(ph, 620)
    elif ft == "ACTION_ANIM":
        ph = max(ph, 540)
    elif ft == "CAMERA":
        ph = max(ph, 540)
    y0 = max(40, sh // 2 - ph // 2)
    return pygame.Rect(sw // 2 - 280, y0, 560, ph)


def _step_overlay_body_geometry(panel_rect, rows_layout):
    """OVERLAY_UI 필드 목록: 클립 영역 + 패널 오른쪽 스크롤바 영역."""
    body_top = panel_rect.y + 120
    body_bottom = panel_rect.bottom - 55
    body_h = max(1, int(body_bottom - body_top))
    pad = 4
    sb_w = STEP_OVERLAY_SB_W
    gap = 4
    inner_w = panel_rect.width - 2 * pad
    body_w = max(40, int(inner_w - sb_w - gap))
    body_rect = pygame.Rect(int(panel_rect.x + pad), int(body_top), body_w, body_h)
    sb_rect = pygame.Rect(int(panel_rect.right - pad - sb_w), int(body_top), int(sb_w), body_h)
    content_h = len(rows_layout) * STEP_BODY_ROW_H
    max_scroll = max(0, content_h - body_h)
    return body_rect, sb_rect, max_scroll, content_h


def _step_overlay_scrollbar_layout(sb_rect, viewport_h, content_h, scroll_px):
    """세로 스크롤바 트랙/썸 (_draw_dropdown_with_scrollbar와 유사)."""
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


# --- 통합 설정 모달 (이벤트 / 이벤트 박스 / BG 박스): 스크롤 본문 + 우측 스크롤바 + List 드롭다운 ---
# ROW_H: 왼쪽 옵션 제목(라벨) 최대 2줄 + 입력칸 세로 여유
EDITOR_MODAL_ROW_H = 50
EDITOR_MODAL_SB_W = 12
EDITOR_MODAL_PAD_X = 12
EDITOR_MODAL_HEADER_H = 48
EDITOR_MODAL_SECTION_BAR_H = 38
EDITOR_MODAL_FOOTER_H = 54
EDITOR_MODAL_LABEL_W = 148
EDITOR_MODAL_LABEL_LINES = 2
GLOBAL_EDITOR_TRIGGER_OPTS = ["auto", "global", "intercept"]
ZONE_TRIGGER_OPTS = [
    "contact_player",
    "contact_confirm",
    "contact_object",
    "press_z",
    "time",
]
BGZONE_BOOL_OPTS = ["true", "false"]
BGZONE_UPDATE_OPTS = ["none", "lowrate", "normal"]
BGZONE_SORT_OPTS = ["none", "cached"]


def _editor_std_modal_rect(sw, sh, n_rows, row_h=EDITOR_MODAL_ROW_H):
    header = EDITOR_MODAL_HEADER_H
    footer = EDITOR_MODAL_FOOTER_H
    content_h = max(1, int(n_rows * row_h))
    max_body = max(100, int(sh * 0.66))
    body_vp = min(content_h, max_body)
    ph = header + body_vp + footer
    margin = 40
    ph = min(ph, max(header + footer + 80, sh - margin))
    y0 = max(margin // 2, (sh - ph) // 2)
    return pygame.Rect(sw // 2 - 280, y0, 560, ph), content_h, body_vp


def _editor_modal_body_scroll_layout(panel_rect, scroll_px, content_h, section_bar_h=0):
    pad = EDITOR_MODAL_PAD_X
    sb_w = EDITOR_MODAL_SB_W
    gap = 4
    sbh = int(section_bar_h or 0)
    body_top = panel_rect.y + EDITOR_MODAL_HEADER_H + sbh
    body_bottom = panel_rect.bottom - EDITOR_MODAL_FOOTER_H
    body_h = max(1, int(body_bottom - body_top))
    inner_w = panel_rect.width - 2 * pad
    body_w = max(40, int(inner_w - sb_w - gap))
    body_rect = pygame.Rect(int(panel_rect.x + pad), int(body_top), body_w, body_h)
    sb_rect = pygame.Rect(int(panel_rect.right - pad - sb_w), int(body_top), int(sb_w), body_h)
    max_scroll = max(0, content_h - body_h)
    sp = int(max(0, min(max_scroll, int(scroll_px or 0))))
    return body_rect, sb_rect, max_scroll, sp


def _editor_call_event_id_options(all_events):
    """CALL_EVENT target — events.json 전 섹션 ID (LOCAL·GLOBAL·SYNC·FRAGMENTS)."""
    try:
        from flow import merge_call_event_catalog

        return sorted(merge_call_event_catalog(all_events or {}).keys())
    except Exception:
        ids = []
        for sec in ("LOCAL", "GLOBAL", "SYNC", "FRAGMENTS"):
            ids.extend((all_events or {}).get(sec) or {})
        return sorted(set(str(x) for x in ids))


def _editor_event_display_name(eid, edata):
    """이벤트 리스트·정렬용 표시 이름 (title 없으면 event id)."""
    return (str((edata or {}).get("title") or "").strip() or str(eid))


def _editor_event_passes_map_filter(cat, edata, map_id):
    if cat == "LOCAL" and (edata or {}).get("map_id") != map_id:
        return False
    if cat == "SYNC":
        wm = str((edata or {}).get("work_map") or "").strip()
        if wm and wm != map_id:
            return False
    return True


def _editor_sorted_events_in_section(all_events, map_id, cat):
    """한 섹션(LOCAL/GLOBAL/…) 이벤트 — 맵 필터 후 이름(title→id) 순."""
    items = []
    for eid, edata in (all_events.get(cat) or {}).items():
        if not _editor_event_passes_map_filter(cat, edata, map_id):
            continue
        items.append((str(eid), edata or {}))
    items.sort(
        key=lambda pair: (
            _editor_event_display_name(pair[0], pair[1]).casefold(),
            pair[0].casefold(),
        )
    )
    return items


def _editor_collect_event_id_options(all_events, map_id):
    ids = []
    for eid, ed in (all_events.get("LOCAL") or {}).items():
        if str((ed or {}).get("map_id") or "") == str(map_id):
            ids.append(eid)
    for eid in (all_events.get("GLOBAL") or {}).keys():
        ids.append(eid)
    return sorted(set(ids))


def _editor_collect_entity_name_options(objs, npcs):
    names = []
    seen = set()
    for o in objs + npcs:
        n = getattr(o, "name", None)
        if n and n not in seen:
            seen.add(n)
            names.append(str(n))
    return sorted(names)


def _event_modal_rows(cat):
    cu = str(cat).upper()
    rows = [
        (
            "※ 이벤트 = 연출 스텝 묶음. 저장 시 events.json 에 기록됩니다.",
            "_hint_evt_intro",
            "hint",
        ),
        ("Category", "cat", "dropdown", list(EDITOR_EVENT_SECTIONS)),
        ("Event ID", "eid", "text"),
        ("Title", "title", "text"),
        ("Result Prog (mainprogress)", "res_prog", "text"),
        (
            'Result Opt — 추가 progress 예: "progress_flower1_1": 1003  (따옴표만, 중괄호 없이)',
            "res_opt",
            "text",
        ),
        (
            "※ Condition = 조건식 문자열. 예: progress_flower1_1 == 1003  (JSON 아님)",
            "_hint_evt_cond",
            "hint",
        ),
    ]
    if cu == "GLOBAL":
        rows += [
            ("Trigger", "trigger", "dropdown", GLOBAL_EDITOR_TRIGGER_OPTS),
            ("Condition (progress 식)", "condition", "text"),
            ("Priority", "priority", "text"),
            ("Work map (editor)", "work_map", "maps"),
        ]
    elif cu == "SYNC":
        rows += [
            ("Work map", "work_map", "maps"),
            ("Condition (progress 식)", "condition", "text"),
            ("Priority", "priority", "text"),
        ]
    # FRAGMENTS: result·condition 없이 steps만 (CALL_EVENT 전용)
    # (정책 변경) 이벤트 옵션의 escape는 제거. 스텝(EVT_STOP_BEGIN/END)에서 제어.
    return rows


def _editor_zone_fields_from_zone_dict(z):
    """event_zones 항목 → 이벤트 박스 모달 필드."""
    z = z if isinstance(z, dict) else {}
    fields = {
        "name": str(z.get("name", "") or ""),
        "event_id": str(z.get("event_id", "") or ""),
        "target": str(z.get("target", "") or ""),
        "trigger": str(z.get("trigger", "contact_player") or "contact_player"),
        "cond_mainprogress": str((z.get("conditions", {}) or {}).get("mainprogress", "") or ""),
        "cond_min_laugh_point": str((z.get("conditions", {}) or {}).get("min_laugh_point", "") or ""),
        "cond_opt": "",
        "rect": list(z.get("rect")) if isinstance(z.get("rect"), (list, tuple)) else None,
    }
    try:
        cond = dict(z.get("conditions", {}) or {})
        cond.pop("mainprogress", None)
        cond.pop("min_laugh_point", None)
        if cond:
            fields["cond_opt"] = ", ".join(
                [
                    json.dumps(k, ensure_ascii=False) + ": " + json.dumps(v, ensure_ascii=False)
                    for k, v in cond.items()
                ]
            )
    except Exception:
        pass
    return fields


def _editor_flow_catalog_rows(world_data, map_id):
    zones = (world_data or {}).get(map_id, {}).get("event_zones", [])
    return build_editor_flow_catalog_rows(
        CHAR_ASSETS, OBJ_ASSETS, map_id=map_id, event_zones=zones
    )


def _editor_flow_row_matches_entry(row, ent):
    if not row or not ent:
        return False
    rk = row.get("kind")
    if rk == "zone":
        return ent.get("kind") == "zone" and ent.get("zone_index") == row.get("zone_index")
    return ent.get("name") == row.get("name") and ent.get("kind") == rk


def _zone_modal_rows():
    return [
        (
            "※ 이벤트 박스 = 플레이어가 영역에 들어오거나 Z키를 누르면 이벤트가 시작됩니다.",
            "_hint_zone_intro",
            "hint",
        ),
        ("Box Name", "name", "text"),
        ("Event ID", "event_id", "events"),
        ("Target (contact_object)", "target", "text_pick"),
        ("Trigger", "trigger", "dropdown", ZONE_TRIGGER_OPTS),
        ("Cond mainprogress", "cond_mainprogress", "text"),
        ("Cond min_laugh_point", "cond_min_laugh_point", "text"),
        ('Cond opt — 추가 조건 JSON 예: "progress_x": 1001', "cond_opt", "text"),
        ("Area — Set Area 버튼으로 맵에 사각형 지정", "_area", "area"),
    ]


def _bgzone_modal_rows():
    return [
        (
            "※ 원경(배경) 묶음 — 카메라 틸트 시에만 그릴지, 레이어·정렬 방식 지정",
            "_hint_bgzone_intro",
            "hint",
        ),
        ("Box Name", "name", "text"),
        ("Layer", "layer", "text"),
        ("Draw only when tilt", "draw_only_when_tilt", "dropdown", BGZONE_BOOL_OPTS),
        ("Update policy", "update_policy", "dropdown", BGZONE_UPDATE_OPTS),
        ("Sort policy", "sort_policy", "dropdown", BGZONE_SORT_OPTS),
        ("Cull margin px", "cull_margin_px", "text"),
        ("Area", "_area", "area"),
    ]


def _editor_draw_modal_scrollbar(screen, sb_ui):
    tr = sb_ui.get("track")
    thm = sb_ui.get("thumb")
    if tr is not None:
        pygame.draw.rect(screen, (18, 18, 24), tr)
    if thm is not None:
        pygame.draw.rect(screen, (110, 120, 150), thm, border_radius=3)
        pygame.draw.rect(screen, (140, 150, 180), thm, 1, border_radius=3)


SIDEBAR_SB_W = 10
EDITOR_SCROLL_WHEEL_STEP = 28
EDITOR_SIDEBAR_WHEEL_STEP = 30


def _editor_wheel_delta(event, *, step=None):
    """마우스 휠 한 칸 → 스크롤 픽셀 (모든 모달·사이드바 공통)."""
    st = EDITOR_SCROLL_WHEEL_STEP if step is None else int(step)
    dy = getattr(event, "precise_y", None)
    if dy is not None:
        delta = int(round(-float(dy) * st))
    else:
        delta = -int(getattr(event, "y", 0) or 0) * st
    if delta == 0 and getattr(event, "y", 0):
        delta = -int(event.y) * st
    return delta


def _editor_pointer_xy(event, mx, my):
    pos = getattr(event, "pos", None)
    if pos is not None:
        return int(pos[0]), int(pos[1])
    return int(mx), int(my)


def _editor_rects_contain_point(px, py, *rects):
    for r in rects:
        if r is not None and r.collidepoint(px, py):
            return True
    return False


def _editor_scroll_px_from_sb_my(my, sb_ui):
    """스크롤바 트랙/썸 — 마우스 Y를 scroll 픽셀(0..max)로 변환."""
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


def _editor_modal_sb_hit(pos, sb_ui):
    """스크롤바 클릭 위치 — 'thumb' | 'track' | None."""
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


def _editor_paint_modal_scroll_hint(screen, font, panel_rect):
    """모달 하단 — 스크롤 조작 안내 (모든 설정 창 공통)."""
    hint = "마우스 휠=위아래 스크롤 · 오른쪽 막대=클릭(이동) 또는 드래그"
    screen.blit(
        font.render(hint, True, (110, 125, 145)),
        (panel_rect.x + 14, panel_rect.bottom - 72),
    )


def _sidebar_scroll_clamp(scroll_y, content_h, view_top, view_bottom):
    """사이드바 scroll_y: 0=맨 위, 음수=아래로 스크롤."""
    view_h = max(1, int(view_bottom) - int(view_top))
    max_scroll = max(0, int(content_h) - view_h)
    sp = max(0, min(max_scroll, -int(scroll_y or 0)))
    return -sp


def _sidebar_sb_rect(panel_x, panel_w, view_top, view_bottom):
    return pygame.Rect(
        int(panel_x) + int(panel_w) - SIDEBAR_SB_W - 2,
        int(view_top),
        SIDEBAR_SB_W,
        max(1, int(view_bottom) - int(view_top)),
    )


def _sidebar_sb_scroll_from_my(my, sb_ui):
    tr = sb_ui.get("track")
    th = int(sb_ui.get("thumb_h") or 18)
    max_sc = int(sb_ui.get("max_scroll") or 0)
    if tr is None or max_sc <= 0:
        return None
    y = int(my) - (th // 2)
    y = max(tr.y, min(tr.bottom - th, y))
    span = max(0, tr.height - th)
    p = 0.0 if span <= 0 else (y - tr.y) / float(span)
    return -int(round(p * max_sc))


def _editor_filter_collapsed_rows(rows, collapsed_keys):
    visible = []
    section = None
    for row in rows:
        if row["kind"] == "header":
            section = row["label"]
            visible.append(row)
        elif section in collapsed_keys:
            continue
        else:
            visible.append(row)
    return visible


def _editor_collapse_mark(collapsed_keys, key):
    return "▶" if key in collapsed_keys else "▼"


EDITOR_UI_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "editor_ui_state.json")
EDITOR_UI_COLLAPSE_MAP_LEFT = "map_left_collapsed"
EDITOR_UI_COLLAPSE_FLOW_LEFT = "flow_left_collapsed"
EDITOR_UI_COLLAPSE_MAP_RIGHT = "map_right_collapsed"


def _load_editor_ui_state() -> dict:
    try:
        with open(EDITOR_UI_STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _save_editor_ui_state(data: dict) -> None:
    try:
        with open(EDITOR_UI_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _editor_collapsed_set_from_state(data: dict, storage_key: str) -> set:
    raw = (data or {}).get(storage_key)
    if isinstance(raw, list):
        return {str(x) for x in raw if str(x).strip()}
    return set()


def _editor_toggle_collapsed(ui_state: dict, storage_key: str, collapsed_set: set, section_key: str) -> None:
    key = str(section_key or "")
    if not key:
        return
    if key in collapsed_set:
        collapsed_set.discard(key)
    else:
        collapsed_set.add(key)
    ui_state[storage_key] = sorted(collapsed_set)
    _save_editor_ui_state(ui_state)


def _editor_right_map_lines(categories, collapsed_keys):
    lines = []
    for cat, items in categories.items():
        lines.append({"kind": "header", "cat": cat, "count": len(items)})
        if cat not in collapsed_keys:
            for name in items:
                lines.append({"kind": "item", "cat": cat, "name": name})
    return lines


def _editor_right_map_list_top():
    """우측 MAP 에셋 리스트 — 썸네일 토글(34px) 아래부터."""
    return 45


def _editor_right_map_side_btn_rect(panel_x, panel_w, row_y, line_h):
    """NPC/Evt 타입·interact 버튼 — 그리기·클릭 좌표 공통."""
    return pygame.Rect(int(panel_x) + int(panel_w) - 58, int(row_y) + 2, 48, int(line_h) - 6)


def _editor_modal_label_wrap_width():
    """통합 모달 왼쪽 옵션 제목 최대 픽셀 폭."""
    return max(72, EDITOR_MODAL_LABEL_W - 10)


def _editor_paint_wrapped_label(
    screen, font, text, x, y, max_w, color, *, max_lines=2, line_gap=2
):
    """
    설정 모달·스텝 모달의 '옵션 제목'(입력칸 왼쪽 안내).
    한 줄로 잘리지 않게 픽셀 폭 기준 줄바꿈(최대 max_lines).
    """
    raw = str(text or "").strip()
    if not raw:
        return 0
    lines = _editor_wrap_lines_to_pixel_width(font, [raw], max_w)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            ell = "…"
            last = lines[-1]
            while last and _editor_font_line_width(font, last + ell) > max_w:
                last = last[:-1]
            lines[-1] = (last + ell) if last else ell
    lh = font.get_height()
    yy = int(y)
    for ln in lines:
        screen.blit(font.render(ln, True, color), (int(x), yy))
        yy += lh + line_gap
    return max(lh, yy - int(y) - line_gap)


def _editor_left_list_metrics(
    edit_mode,
    map_tool,
    map_id,
    objs,
    npcs,
    flow,
    all_events,
    line_h,
    top_bar_h,
    event_list_start_y,
    placed_collapsed=None,
    flow_entity_entries=None,
    flow_placed_collapsed=None,
):
    tops = _editor_left_list_tops(top_bar_h)
    if edit_mode == "FLOW":
        list_top = tops["flow"]
        rows = _editor_filter_collapsed_rows(
            _editor_flow_catalog_rows(flow.world_data, map_id),
            flow_placed_collapsed or set(),
        )
        content_h = len(rows) * line_h
    elif edit_mode == "MAP":
        if map_tool == "OBJECTS":
            list_top = tops["map_objects"]
            rows = _editor_filter_collapsed_rows(
                build_editor_placed_list_rows(objs, npcs),
                placed_collapsed or set(),
            )
            content_h = len(rows) * line_h
        elif map_tool == "ZONES":
            list_top = tops["map_zones"]
            zones = flow.world_data.get(map_id, {}).get("event_zones", [])
            content_h = len(zones) * line_h
        elif map_tool == "BGZONES":
            list_top = tops["map_bgzones"]
            zones = flow.world_data.get(map_id, {}).get("bg_zones", [])
            content_h = len(zones) * line_h
        else:
            list_top = tops["map_presences"]
            zones = flow.world_data.get(map_id, {}).get("presence_zones", [])
            content_h = len(zones) * line_h
    else:
        list_top = event_list_start_y
        content_h = 0
        for cat in EDITOR_EVENT_SECTIONS:
            content_h += line_h
            content_h += line_h * len(
                _editor_sorted_events_in_section(all_events, map_id, cat)
            )
    return list_top, content_h


def _editor_list_row_at(rows, idx):
    if 0 <= idx < len(rows):
        return rows[idx]
    return None


def _editor_right_map_content_height(categories, line_h, collapsed_keys=None):
    n = len(_editor_right_map_lines(categories, collapsed_keys or set()))
    return n * line_h


def _editor_paint_sidebar_scrollbar(screen, panel_x, panel_w, view_top, view_bottom, content_h, scroll_y):
    scroll_y = _sidebar_scroll_clamp(scroll_y, content_h, view_top, view_bottom)
    vh = max(1, int(view_bottom) - int(view_top))
    if max(0, int(content_h) - vh) <= 0:
        return scroll_y, None
    sb_rect = _sidebar_sb_rect(panel_x, panel_w, view_top, view_bottom)
    sp = -int(scroll_y or 0)
    sb_ui = _step_overlay_scrollbar_layout(sb_rect, vh, content_h, sp)
    _editor_draw_modal_scrollbar(screen, sb_ui)
    return scroll_y, sb_ui


def _editor_paint_modal_overlay(
    screen, title_font, font, title, panel_rect, rows, scroll_px, store, active_key, *, area_theme="zone", section_bar_h=0
):
    """통합 설정 모달 본문 + 우측 스크롤바. 드롭다운은 호출측에서 별도로 그림."""
    pygame.draw.rect(screen, (40, 40, 40), panel_rect)
    pygame.draw.rect(screen, (200, 200, 200), panel_rect, 2)
    screen.blit(title_font.render(title, True, (255, 255, 255)), (panel_rect.x + 16, panel_rect.y + 12))

    content_h = len(rows) * EDITOR_MODAL_ROW_H
    body_rect, sb_rect, _ms, sp = _editor_modal_body_scroll_layout(
        panel_rect, scroll_px, content_h, section_bar_h
    )
    prev = screen.get_clip()
    screen.set_clip(body_rect)

    row_h = EDITOR_MODAL_ROW_H
    fx0 = body_rect.x + EDITOR_MODAL_LABEL_W
    fw, lw = 220, 52
    tw = 168

    for i, row in enumerate(rows):
        rk = row[1]
        kind = row[2]
        ry = body_rect.y + i * row_h - sp
        if ry + row_h < body_rect.top or ry > body_rect.bottom:
            continue
        lab = row[0]
        lw = _editor_modal_label_wrap_width()
        if kind == "hint":
            _editor_paint_wrapped_label(
                screen,
                font,
                lab,
                body_rect.x + 8,
                ry + 6,
                body_rect.width - 16,
                (120, 160, 130),
                max_lines=3,
            )
            continue
        if kind == "add_btn":
            btn_w = min(200, body_rect.width - 24)
            btn_rect = pygame.Rect(body_rect.centerx - btn_w // 2, ry + 4, btn_w, row_h - 8)
            pygame.draw.rect(screen, (35, 85, 45), btn_rect)
            pygame.draw.rect(screen, (100, 200, 120), btn_rect, 1)
            ts = font.render(lab, True, (230, 255, 235))
            screen.blit(ts, (btn_rect.centerx - ts.get_width() // 2, btn_rect.centery - ts.get_height() // 2))
            continue
        _editor_paint_wrapped_label(
            screen,
            font,
            lab,
            body_rect.x + 4,
            ry + 6,
            lw,
            (170, 175, 190),
            max_lines=EDITOR_MODAL_LABEL_LINES,
        )

        def _col():
            return (255, 255, 0) if active_key == rk else (200, 200, 200)

        if kind == "dropdown":
            val = str(store.get(rk, "") or "")
            c = _col()
            val_rect = pygame.Rect(fx0, ry + 4, fw, row_h - 8)
            pygame.draw.rect(screen, (20, 20, 20), val_rect)
            pygame.draw.rect(screen, c, val_rect, 1)
            dv = val if len(val) <= 28 else val[:25] + "..."
            screen.blit(font.render(dv, True, (250, 250, 252)), (val_rect.x + 5, val_rect.y + 5))
            lb = pygame.Rect(fx0 + fw + 4, ry + 4, lw, row_h - 8)
            pygame.draw.rect(screen, (50, 70, 90), lb)
            pygame.draw.rect(screen, (120, 160, 200), lb, 1)
            screen.blit(font.render("List", True, (230, 240, 255)), (lb.x + 9, lb.y + 6))
        elif kind == "maps":
            val = str(store.get(rk, "") or "")
            c = _col()
            val_rect = pygame.Rect(fx0, ry + 4, fw, row_h - 8)
            pygame.draw.rect(screen, (20, 20, 20), val_rect)
            pygame.draw.rect(screen, c, val_rect, 1)
            dv = val if len(val) <= 28 else val[:25] + "..."
            screen.blit(font.render(dv, True, (250, 250, 252)), (val_rect.x + 5, val_rect.y + 5))
            lb = pygame.Rect(fx0 + fw + 4, ry + 4, lw, row_h - 8)
            pygame.draw.rect(screen, (50, 70, 90), lb)
            pygame.draw.rect(screen, (120, 160, 200), lb, 1)
            screen.blit(font.render("List", True, (230, 240, 255)), (lb.x + 9, lb.y + 6))
        elif kind == "text":
            c = _col()
            val_rect = pygame.Rect(fx0, ry + 4, body_rect.right - fx0 - 8, row_h - 8)
            pygame.draw.rect(screen, (20, 20, 20), val_rect)
            pygame.draw.rect(screen, c, val_rect, 1)
            val = str(store.get(rk, "") or "")
            dv = val if len(val) <= 36 else val[:33] + "..."
            screen.blit(font.render(dv, True, (250, 250, 252)), (val_rect.x + 5, val_rect.y + 5))
        elif kind == "events":
            c = _col()
            val_rect = pygame.Rect(fx0, ry + 4, fw, row_h - 8)
            pygame.draw.rect(screen, (20, 20, 20), val_rect)
            pygame.draw.rect(screen, c, val_rect, 1)
            val = str(store.get(rk, "") or "")
            dv = val if len(val) <= 28 else val[:25] + "..."
            screen.blit(font.render(dv, True, (250, 250, 252)), (val_rect.x + 5, val_rect.y + 5))
            lb = pygame.Rect(fx0 + fw + 4, ry + 4, lw, row_h - 8)
            pygame.draw.rect(screen, (50, 70, 90), lb)
            pygame.draw.rect(screen, (120, 160, 200), lb, 1)
            screen.blit(font.render("List", True, (230, 240, 255)), (lb.x + 9, lb.y + 6))
        elif kind == "text_pick":
            c = _col()
            val_rect = pygame.Rect(fx0, ry + 4, tw, row_h - 8)
            pygame.draw.rect(screen, (20, 20, 20), val_rect)
            pygame.draw.rect(screen, c, val_rect, 1)
            val = str(store.get(rk, "") or "")
            dv = val if len(val) <= 22 else val[:19] + "..."
            screen.blit(font.render(dv, True, (250, 250, 252)), (val_rect.x + 5, val_rect.y + 5))
            lb = pygame.Rect(val_rect.right + 4, ry + 4, lw, row_h - 8)
            pygame.draw.rect(screen, (50, 70, 90), lb)
            pygame.draw.rect(screen, (120, 160, 200), lb, 1)
            screen.blit(font.render("List", True, (230, 240, 255)), (lb.x + 9, lb.y + 6))
            pb = pygame.Rect(lb.right + 4, ry + 4, lw, row_h - 8)
            pygame.draw.rect(screen, (70, 70, 55), pb)
            pygame.draw.rect(screen, (200, 200, 140), pb, 1)
            screen.blit(font.render("Pick", True, (250, 250, 230)), (pb.x + 9, pb.y + 6))
        elif kind == "area":
            ab = pygame.Rect(fx0, ry + 4, 140, row_h - 8)
            if area_theme == "bgzone":
                pygame.draw.rect(screen, (55, 60, 90), ab)
                pygame.draw.rect(screen, (130, 160, 200), ab, 1)
            else:
                pygame.draw.rect(screen, (60, 80, 60), ab)
                pygame.draw.rect(screen, (140, 170, 140), ab, 1)
            screen.blit(font.render("Set Area", True, (255, 255, 255)), (ab.x + 14, ab.y + 6))
            rect_txt = store.get("rect")
            rect_label = "None" if not rect_txt else str(rect_txt)
            screen.blit(font.render(rect_label, True, (150, 155, 170)), (ab.right + 12, ry + 10))

    screen.set_clip(prev)
    sb_ui = _step_overlay_scrollbar_layout(sb_rect, body_rect.height, content_h, sp)
    _editor_draw_modal_scrollbar(screen, sb_ui)
    _editor_paint_modal_scroll_hint(screen, font, panel_rect)
    return sb_ui


def _char_anim_dropdown_options():
    return [
        "idle",
        "walk",
        "jump",
        "hurt",
        "laugh",
        "attack",
        "lie",
        "seat_idle",
        "question",
        "surprise",
        "say",
        "sleep",
        "sad",
        "seating",
    ]


def _parse_waypoints_semicolon(text):
    """MOVE 추가 좌표: 'x,y; x2,y2' 또는 'x y; x2 y2'."""
    out = []
    for seg in (text or "").split(";"):
        seg = seg.strip()
        if not seg or seg.startswith("#"):
            continue
        a, b = None, None
        if "," in seg:
            parts = [p.strip() for p in seg.split(",", 1)]
            if len(parts) >= 2:
                a, b = parts[0], parts[1]
        else:
            parts = seg.split()
            if len(parts) >= 2:
                a, b = parts[0], parts[1]
        if a is not None:
            try:
                out.append((float(a), float(b)))
            except (TypeError, ValueError):
                pass
    return out


def _step_field_rows(step_type):
    """스텝 타입별 (라벨, 필드키) — 입력/그리기/히트테스트 공통."""
    t = (step_type or "MOVE").upper()
    if t == "MOVE":
        return [
            ("MOVE: pos [x,y] 또는 [[x,y],…] 웨이포인트; 에디터는 Pos+추가(;)", "_hint_move"),
            ("Target (목록/직접입력)", "target"),
            ("Pos X", "pos_x"),
            ("Pos Y", "pos_y"),
            ("웨이포인트(;구분) · WP+로 맵에서 연속 추가", "waypoints"),
            ("Dir", "dir"),
            ("instant (true=순간)", "instant"),
            ("force (true=마스크/이동가능 무시)", "force"),
            ("Speed mul (1.0=기본, 0.5=느림, 2.0=빠름)", "speed"),
            ("wait (단일 목적지만 즉시 다음; 웨이포인트 경로는 엔진이 끝까지 대기)", "wait"),
            ("move_sync (같은 문자열의 연속 MOVE 전원 도착까지 묶음; 비우면 개별)", "move_sync"),
            ("이동 중 애니 (비우면 기본·idle 등)", "move_anim"),
        ]
    if t == "PLACE":
        return [
            ("PLACE: 새 오브젝트/NPC 등장 (기존 위치 바꿀 땐 MOVE+instant)", "_hint_place"),
            ("Target (자산 이름)", "target"),
            ("Pos X", "pos_x"),
            ("Pos Y", "pos_y"),
            ("Appear", "appear"),
            ("Dir", "dir"),
            ("Action", "action"),
            ("sprite_tilt (0~1, 비우면 유지/기본)", "sprite_tilt"),
            ("height (px, 그리기+점프 arc, 비우면 유지/기본)", "height"),
            ("ysort (ground/visual, 비우면 유지/기본)", "ysort"),
            ("layer (int, 비우면 유지/기본)", "layer"),
        ]
    if t == "TUNE":
        return [
            ("TUNE: 이미 배치된 대상의 설정값 변경(생성/이동 없음)", "_hint_tune"),
            ("Target (목록/직접입력)", "target"),
            ("sprite_tilt (0~1, 비우면 유지)", "sprite_tilt"),
            ("height (px, 비우면 유지)", "height"),
            ("ysort (ground/visual, 비우면 유지)", "ysort"),
            ("layer (int, 비우면 유지)", "layer"),
            ("visible (true/false, 비우면 유지)", "visible"),
            ("alpha (0~255, 비우면 유지)", "alpha"),
        ]
    if t == "MAP":
        return [
            ("Map ID", "target"),
            ("Pos X", "pos_x"),
            ("Pos Y", "pos_y"),
            ("Appear", "appear"),
            ("Dir", "dir"),
        ]
    if t == "ACTION_ANIM":
        return [
            ("ACTION_ANIM: 캐릭터 동작(애니 세트)", "_hint_action_anim"),
            ("Target (목록/픽)", "target"),
            ("Anim (목록 또는 직접 입력)", "anim"),
            ("mode: once | hold", "mode"),
            ("val (초, once일 때)", "val"),
            ("loop (true/false)", "loop"),
            ("wait (once+시간 있을 때)", "wait"),
            ("dir: left | right | 비우면 유지", "dir"),
            ("height (jump일 때 점프 arc px)", "height"),
            ("release: idle | stop (해제 시)", "release"),
        ]
    if t == "SAY":
        return [
            ("Who", "who"),
            ("Show name(true/false, 비우면 기본값)", "show_name"),
            ("Text", "text"),
            ("Voice", "voice"),
            ("Auto(true/false)", "auto"),
            ("Val(sec)", "val"),
            ("말풍선(bubble, true/false 비우면 data 기본)", "bubble"),
            ("말풍선 대상(bubble_target, 비우면 who)", "bubble_target"),
        ]
    if t == "EMOTE":
        return [
            ("EMOTE: 머리 위 감정 PNG 연속 (images/ui/{emotion}_0.png)", "_hint_emote"),
            ("action: show | clear", "action"),
            ("Target (player 또는 이름)", "target"),
            ("emotion (파일 접두어, 예: surprise)", "emotion"),
            ("frame_ms", "frame_ms"),
            ("hold_last_sec (마지막 프레임 유지 후 진행/대기)", "hold_last_sec"),
            ("advance: continue | stop", "advance"),
        ]
    if t == "EVT_STOP_BEGIN":
        return [
            ("EVT_STOP_BEGIN: 이벤트 중도 스탑 입력 허용 시작", "_hint_evt_stop_begin"),
            ("action: end | break_loop | lock", "action"),
            ("(원터치 정책) 입력은 클릭/A/Enter/Space만 사용", "_hint_evt_stop_one_touch"),
        ]
    if t == "EVT_STOP_END":
        return [
            ("EVT_STOP_END: 이벤트 중도 스탑 입력 비활성화", "_hint_evt_stop_end"),
        ]
    if t == "WAIT":
        return [("Val(sec)", "val")]
    if t == "INTERVAL":
        return [("INTERVAL: 다음 스텝 전까지 대기(초, WAIT과 동일)", "_hint_interval"), ("Val(sec)", "val")]
    if t == "ZOOM":
        return [
            ("ZOOM: target 비우면 카메라(월드), 이름이면 스프라이트", "_hint_zoom"),
            ("on (true/false)", "zoom_on"),
            ("strength (0~1, 0=1x 1=최대줌)", "zoom_strength"),
            ("duration_sec (0=즉시)", "zoom_duration_sec"),
            ("val (배율 직접지정, 비우면 strength 사용)", "val"),
            ("Target (비우면 카메라)", "target"),
        ]
    if t == "FOLLOW_START":
        return [
            ("Follower(name)", "follower"),
            ("Leader(name)", "leader"),
            ("Dist(px)", "dist"),
            ("Speed mul", "speed"),
        ]
    if t == "FOLLOW_STOP":
        return [
            ("Follower(name, empty=all)", "follower"),
        ]
    if t in ("FADEIN", "FADEOUT"):
        return [
            ("논블로킹: 페이드 중에도 다음 스텝(MOVE 등) 진행", "_hint_fade"),
            ("Val(sec)", "val"),
        ]
    if t == "EFFECT":
        return [
            ("Name", "name"),
            ("Target", "target"),
            ("Anchor", "anchor"),
            ("Pos X", "pos_x"),
            ("Pos Y", "pos_y"),
            ("Loop(true/false)", "loop"),
            ("Action(remove)", "action"),
        ]
    if t == "ANIM_ONCE":
        return [
            ("ANIM_ONCE: object_defs name + 좌표, 1회 재생(끝날 때까지 대기)", "_hint_anim_once"),
            ("Name (object_defs 키)", "name"),
            ("Pos X", "pos_x"),
            ("Pos Y", "pos_y"),
        ]
    if t == "CARRY":
        return [
            ("CARRY: 들기/내려놓기 (Player 상호작용 fly 연출 재사용)", "_hint_carry"),
            ("Holder (기본 player)", "holder"),
            ("Action: pick | put", "action"),
            ("Target (pick=물건, put+slot=슬롯 이름)", "target"),
            ("Pos X (put 바닥 위치, 있으면 슬롯 무시)", "pos_x"),
            ("Pos Y", "pos_y"),
            ("wait (fly 끝까지 대기, 기본 true)", "wait"),
        ]
    if t == "CHANGE":
        return [
            ("CHANGE: FieldItem/캐릭터 외형 교체 (들고 있는 중 OK)", "_hint_change"),
            ("Target (held=손, 맵 오브젝트/캐릭터 이름)", "target"),
            ("To (FieldItem=object_defs / 캐릭터=char_defs 키)", "to"),
            ("Fade (초, 디졸브 — 사라졌다 나타남. 0/빈칸=즉시)", "fade"),
        ]
    if t == "SCREEN":
        return [
            ("Picture", "picture"),
            ("Music", "music"),
            ("Transition", "transition"),
            ("Text", "text"),
            ("Auto(true/false)", "auto"),
            ("Val(sec)", "val"),
            ("Action(remove)", "action"),
        ]
    if t == "OVERLAY_UI":
        return [
            ("OVERLAY_UI: 화면 고정 텍스트/오브젝트 이미지 (논리 해상도)", "_hint_overlay_ui"),
            ("action (show/remove)", "action"),
            ("overlay_id (트랙 — 같은 id는 순서대로, 다른 id는 병렬)", "overlay_id"),
            ("delay (초, 같은 id 이전 연출 끝난 뒤 대기)", "delay"),
            ("content (text/image)", "content"),
            ("text (줄바꿈 \\n)", "text"),
            ("font (레지스트리 키)", "font"),
            ("size (px)", "size"),
            ("color R,G,B", "color"),
            ("object (OBJ_ASSETS 이름)", "object"),
            ("anchor", "anchor"),
            ("margin_x", "margin_x"),
            ("margin_y", "margin_y"),
            ("mode (fade/scroll)", "mode"),
            ("scroll_enter (left/right/up/down)", "scroll_enter"),
            ("appear (sec)", "appear"),
            ("hold (sec, hold_forever면 무시)", "hold"),
            ("disappear (sec)", "disappear"),
            ("hold_forever (true=무한 유지)", "hold_forever"),
            ("persist (true=이벤트 종료 후 유지)", "persist"),
        ]
    if t == "MUSIC_PLAY":
        return [
            ("MUSIC_PLAY: BGM 재생(기본은 현재 곡 끝나고 큐)", "_hint_music_play"),
            ("Track (드롭다운/직접입력)", "music"),
            ("fade_in(sec)", "fade_in"),
            ("loop(true/false)", "loop"),
            ("queue(true/false)", "queue"),
            ("volume(0~1)", "volume"),
        ]
    if t == "MUSIC_STOP":
        return [
            ("MUSIC_STOP: 페이드아웃 후 정지", "_hint_music_stop"),
            ("fade_out(sec)", "fade_out"),
        ]
    if t == "MUSIC_END":
        return [("MUSIC_END: 즉시 정지", "_hint_music_end")]
    if t == "MUSIC_PAUSE":
        return [("MUSIC_PAUSE: 일시정지", "_hint_music_pause")]
    if t == "MUSIC_RESUME":
        return [("MUSIC_RESUME: 재개", "_hint_music_resume")]
    if t == "PLAYER_VISIBLE":
        return [("Val(true/false)", "val")]
    if t == "CURSOR_VISIBLE":
        return [("Val(true/false)", "val")]
    if t == "CONDITION":
        return [
            (
                "CONDITION: false면 다음 CONDITION_SKIP 직전까지 스텝 건너뜀",
                "_hint_condition",
            ),
            ("조건식(전체)  progress_x == 1002", "condition"),
            ("또는 변수 var", "var"),
            ("연산·값 op  >=100, ==1002", "op"),
        ]
    if t == "CONDITION_SKIP":
        return [
            (
                "CONDITION_SKIP: 블록 끝 (false면 여기로 점프, 맨 끝이면 이벤트 종료)",
                "_hint_condition_skip",
            ),
        ]
    if t == "LOOP_START":
        return [("LOOP_START: 본문 첫 스텝으로 되돌아가는 루프 시작", "_hint_loop")]
    if t == "LOOP_END":
        return [("LOOP_END: 짝 맞는 LOOP_START 다음 스텝으로 점프", "_hint_loop")]
    if t == "TILT":
        return [
            ("TILT: 세로 압축(0=평면, 1=최대 기울임)", "_hint_tilt"),
            ("on (true/false)", "tilt_on"),
            ("strength (0~1)", "tilt_strength"),
            ("duration_sec (0=즉시)", "tilt_duration_sec"),
        ]
    if t == "SHEAR":
        return [
            ("SHEAR: 위쪽이 오른쪽으로 밀림", "_hint_shear"),
            ("on (true/false)", "shear_on"),
            ("strength (0~1)", "shear_strength"),
            ("duration_sec (0=즉시)", "shear_duration_sec"),
            ("px (선택, data 기본 대신)", "shear_px"),
        ]
    if t == "FX":
        return [
            ("FX: 화면 효과(현재 cloud_shadow)", "_hint_fx"),
            ("kind (cloud_shadow)", "fx_kind"),
            ("on (true/false)", "fx_on"),
            ("dir (SE/SW/NE/NW/RANDOM)", "fx_dir"),
            ("speed (px/sec)", "fx_speed"),
            ("freq (spawns/sec)", "fx_freq"),
            ("grid_cell (비우면 data)", "fx_grid_cell"),
            ("grid_jitter (0~0.49, 비우면 data)", "fx_grid_jitter"),
            ("grid_max (비우면 data)", "fx_grid_max"),
        ]
    if t == "CALL_EVENT":
        return [
            ("CALL_EVENT: 다른 이벤트 steps 삽입 (순환 주의)", "_hint_call_event"),
            ("Event ID (LOCAL/GLOBAL/SYNC/FRAGMENTS)", "target"),
        ]
    if t == "DEV_CMD":
        return [
            ("DEV_CMD: 필드 즉시 동작 (field_runtime.apply_dev_runtime_command)", "_hint_dev_cmd"),
            ("cmd (예: toggle_show_mask, cycle_zoom_debug)", "dev_cmd"),
        ]
    if t == "CAMERA":
        return [
            ("CAMERA: follow / fixed / 현재고정 / 저장·불러오기(slot)", "_hint_cam"),
            ("mode", "cam_mode"),
            ("slot (save_camera·load_camera)", "cam_slot"),
            ("target (follow_entity)", "cam_target"),
            ("x (fixed)", "cam_x"),
            ("y (fixed)", "cam_y"),
            ("smooth (true/false)", "cam_smooth"),
            ("duration_sec (이동·전환 시간)", "cam_duration_sec"),
            ("lerp (구형, 비우면 duration 사용)", "cam_lerp"),
        ]
    return []


def _entity_names_on_map(player, objs, npcs):
    names = {"player"}
    for n in npcs:
        names.add(n.name)
    for o in objs:
        names.add(o.name)
    return names


def _names_after_steps(steps, before_index, player, objs, npcs):
    """before_index 직전까지 적용한 뒤 존재하는 target 이름 (MOVE 목록용)."""
    names = _entity_names_on_map(player, objs, npcs)
    end = max(0, min(before_index, len(steps)))
    for i in range(end):
        st = steps[i]
        typ = (st.get("type") or "").upper()
        tgt = (st.get("target") or "").strip()
        if not tgt:
            continue
        if typ == "PLACE":
            if st.get("action") == "remove":
                names.discard(tgt)
            else:
                names.add(tgt)
        elif typ == "MOVE":
            names.add(tgt)
    return sorted(names)


def _place_target_options():
    return sorted(set(CHAR_ASSETS.keys()) | set(OBJ_ASSETS.keys()))


def _move_target_options(steps, before_index, player, objs, npcs):
    return _names_after_steps(steps, before_index, player, objs, npcs)


def _dev_cmd_dropdown_options():
    return [
        "toggle_show_mask",
        "toggle_show_overlay",
        "toggle_tilt_demo",
        "toggle_shear_debug",
        "cycle_zoom_debug",
        "toggle_jump_shadow",
        "toggle_fullscreen",
        "camera_follow_player",
        "start_swing_ride",
        "stop_fishing",
        "start_fishing",
        "start_activity_fishing",
        "restart_delete_save",
    ]


def _step_coord_xy_pairs(step_type):
    """맵 클릭으로 채울 (x필드, y필드) 쌍."""
    t = (step_type or "").upper()
    pairs = []
    if t in ("MOVE", "PLACE", "MAP", "EFFECT", "ANIM_ONCE", "CARRY"):
        pairs.append(("pos_x", "pos_y"))
    if t == "CAMERA":
        pairs.append(("cam_x", "cam_y"))
    return pairs


def _step_row_entity_pick(step_type, field_key):
    """이름 목록 + 맵 픽이 붙는 필드."""
    t = (step_type or "").upper()
    fk = (field_key or "").strip()
    if fk == "target":
        return t in ("MOVE", "PLACE", "TUNE", "ZOOM", "ACTION_ANIM", "EFFECT", "EMOTE", "CARRY", "CHANGE")
    if fk == "holder" and t == "CARRY":
        return True
    if fk == "cam_target" and t == "CAMERA":
        return True
    if fk == "follower" and t in ("FOLLOW_START", "FOLLOW_STOP"):
        return True
    if fk == "leader" and t == "FOLLOW_START":
        return True
    if t == "SAY" and fk in ("who", "bubble_target"):
        return True
    return False


def _step_entity_options_for_pick(step_type, field_key, steps_ref, before_ix, player, objs, npcs):
    t = (step_type or "").upper()
    fk = (field_key or "").strip()
    if fk == "target" and t in ("MOVE", "ACTION_ANIM"):
        return _move_target_options(steps_ref, before_ix, player, objs, npcs)
    if fk == "target" and t == "PLACE":
        return _place_target_options()
    if fk == "target" and t == "ZOOM":
        return _zoom_target_options(steps_ref, before_ix, player, objs, npcs)
    if fk == "target" and t in ("TUNE", "EFFECT", "EMOTE"):
        return _move_target_options(steps_ref, before_ix, player, objs, npcs)
    if fk == "target" and t == "CHANGE":
        opts = ["held", "@held"]
        opts.extend(_move_target_options(steps_ref, before_ix, player, objs, npcs))
        return opts
    if fk == "to" and t == "CHANGE":
        # FieldItem 대상은 object_defs, 캐릭터 대상은 char_defs 키로 교체된다. 둘 다 제공.
        return sorted(set(OBJ_ASSETS.keys()) | set(CHAR_ASSETS.keys()))
    if fk == "cam_target" and t == "CAMERA":
        return sorted(_entity_names_on_map(player, objs, npcs))
    if fk in ("follower", "leader") and t == "FOLLOW_START":
        return sorted(_entity_names_on_map(player, objs, npcs))
    if fk == "follower" and t == "FOLLOW_STOP":
        return sorted(_entity_names_on_map(player, objs, npcs))
    if fk in ("who", "bubble_target") and t == "SAY":
        return _move_target_options(steps_ref, before_ix, player, objs, npcs)
    return []


def _step_dropdown_field_options(step_type, field_key, *, map_list, steps_ref, before_ix, player, objs, npcs, all_events=None):
    """고정 후보가 있으면 문자열 리스트, 없으면 None(자유 텍스트)."""
    t = (step_type or "").upper()
    fk = (field_key or "").strip()
    if t == "CALL_EVENT" and fk == "target":
        return [""] + _editor_call_event_id_options(all_events or {})
    if t == "OVERLAY_UI" and fk in ("font", "object", "anchor", "mode", "scroll_enter", "content", "action"):
        out = _overlay_ui_dropdown_options(fk)
        return out if out else None
    if t == "MAP" and fk == "target":
        return [""] + sorted(str(m) for m in (map_list or []) if str(m).strip())
    if t == "CAMERA":
        if fk == "cam_mode":
            return [
                "follow_player",
                "follow_entity",
                "fixed",
                "lock_here",
                "save_camera",
                "load_camera",
            ]
        if fk == "cam_smooth":
            return ["true", "false"]
    if fk == "dir" and t in ("MOVE", "PLACE", "MAP", "ACTION_ANIM"):
        return ["", "left", "right"]
    if fk == "appear" and t in ("MOVE", "PLACE", "MAP"):
        return ["", "fade"]
    if fk in ("instant", "force") and t == "MOVE":
        return ["", "true", "false"]
    if fk == "wait" and t == "MOVE":
        return ["", "true", "false"]
    if fk == "show_name" and t == "SAY":
        return ["", "true", "false"]
    if fk in ("auto",) and t == "SAY":
        return ["", "true", "false"]
    if fk == "bubble" and t == "SAY":
        return ["", "true", "false"]
    if fk == "action" and t == "EMOTE":
        return ["show", "clear"]
    if fk == "advance" and t == "EMOTE":
        return ["continue", "stop"]
    if fk == "action" and t == "EVT_STOP_BEGIN":
        return ["end", "break_loop", "lock"]
    if fk == "instant" and t == "ZOOM":
        return ["", "true", "false"]
    if fk == "loop" and t in ("EFFECT", "ACTION_ANIM"):
        return ["", "true", "false"]
    if fk == "wait" and t == "ACTION_ANIM":
        return ["", "true", "false"]
    if fk == "loop" and t == "MUSIC_PLAY":
        return ["true", "false"]
    if fk == "queue" and t == "MUSIC_PLAY":
        return ["true", "false"]
    if fk == "mode" and t == "ACTION_ANIM":
        return ["once", "hold"]
    if fk == "release" and t == "ACTION_ANIM":
        return ["idle", "stop"]
    if fk == "transition" and t == "SCREEN":
        return ["fade", "dissolve", "wipe"]
    if fk == "action" and t == "SCREEN":
        return ["", "remove"]
    if fk in ("tilt_on", "zoom_on") and t in ("TILT", "ZOOM"):
        return ["true", "false"]
    if fk in ("shear_on",) and t == "SHEAR":
        return ["true", "false"]
    if fk == "fx_on" and t == "FX":
        return ["true", "false"]
    if fk == "fx_kind" and t == "FX":
        return ["cloud_shadow"]
    if fk == "fx_dir" and t == "FX":
        return ["SE", "SW", "NE", "NW", "RANDOM"]
    if fk == "val" and t in ("PLAYER_VISIBLE", "CURSOR_VISIBLE"):
        return ["true", "false"]
    if fk == "ysort" and t in ("PLACE", "TUNE"):
        return ["", "ground", "visual"]
    if fk == "visible" and t == "TUNE":
        return ["", "true", "false"]
    if fk == "action" and t == "PLACE":
        return ["", "remove"]
    if fk == "action" and t == "CARRY":
        return ["pick", "put"]
    if fk == "wait" and t == "CARRY":
        return ["true", "false"]
    if fk == "dev_cmd" and t == "DEV_CMD":
        return _dev_cmd_dropdown_options()
    return None


def _zoom_target_options(steps, before_index, player, objs, npcs):
    """빈 문자열 = 카메라(전체) 줌. 이후 플레이어·맵상 NPC/오브젝트 이름."""
    base = _names_after_steps(steps, before_index, player, objs, npcs)
    return [""] + sorted(base)


def _apply_default_step_fields_on_type_change(step_fields, new_type):
    """이벤트 스텝 타입을 바꿀 때, 비어 있는 필드에 data.CONFIG 기반 기본값을 넣습니다."""
    from data import CONFIG

    t = (new_type or "MOVE").upper()

    def empt(k):
        return str(step_fields.get(k) or "").strip() == ""

    if t == "WAIT" and empt("val"):
        step_fields["val"] = "1.0"
    elif t == "ZOOM":
        if empt("zoom_on"):
            step_fields["zoom_on"] = "true"
        if empt("zoom_strength"):
            step_fields["zoom_strength"] = "0"
        if empt("zoom_duration_sec"):
            step_fields["zoom_duration_sec"] = "1.0"
    elif t == "TILT":
        if empt("tilt_on"):
            step_fields["tilt_on"] = "true"
        if empt("tilt_strength"):
            step_fields["tilt_strength"] = "1.0"
        if empt("tilt_duration_sec"):
            step_fields["tilt_duration_sec"] = "1.0"
    elif t == "SHEAR":
        if empt("shear_on"):
            step_fields["shear_on"] = "true"
        if empt("shear_strength"):
            step_fields["shear_strength"] = "1.0"
        if empt("shear_duration_sec"):
            step_fields["shear_duration_sec"] = "1.0"
    elif t in ("FADEIN", "FADEOUT") and empt("val"):
        step_fields["val"] = "1.0"
    elif t == "FOLLOW_START":
        if empt("dist"):
            step_fields["dist"] = "40"
        if empt("speed"):
            step_fields["speed"] = "1.0"
    elif t == "ANIM" and empt("val"):
        step_fields["val"] = "0"
    elif t == "ACTION_ANIM":
        if empt("mode"):
            step_fields["mode"] = "once"
        if empt("release"):
            step_fields["release"] = "idle"
        if empt("val"):
            step_fields["val"] = "1.0"
        if empt("anim"):
            step_fields["anim"] = "idle"
    elif t == "CARRY":
        if empt("action"):
            step_fields["action"] = "pick"
        if empt("holder"):
            step_fields["holder"] = "player"
        if empt("wait"):
            step_fields["wait"] = "true"
    elif t == "CHANGE":
        if empt("target"):
            step_fields["target"] = "held"
    elif t == "MUSIC_PLAY":
        if empt("fade_in"):
            step_fields["fade_in"] = "0.5"
        if empt("loop"):
            step_fields["loop"] = "true"
        if empt("queue"):
            step_fields["queue"] = "true"
        if empt("volume"):
            step_fields["volume"] = "1.0"
    elif t == "MUSIC_STOP" and empt("fade_out"):
        step_fields["fade_out"] = "0.5"
    elif t == "SCREEN" and empt("val"):
        step_fields["val"] = "3.0"
    elif t == "OVERLAY_UI":
        if empt("action"):
            step_fields["action"] = "show"
        if empt("content"):
            step_fields["content"] = "text"
        if empt("text"):
            step_fields["text"] = ""
        if empt("font"):
            step_fields["font"] = "default"
        if empt("size"):
            step_fields["size"] = "16"
        if empt("color"):
            step_fields["color"] = "255,255,255"
        if empt("object"):
            step_fields["object"] = ""
        if empt("anchor"):
            step_fields["anchor"] = "center"
        if empt("margin_x"):
            step_fields["margin_x"] = "0"
        if empt("margin_y"):
            step_fields["margin_y"] = "0"
        if empt("mode"):
            step_fields["mode"] = "fade"
        if empt("scroll_enter"):
            step_fields["scroll_enter"] = "left"
        if empt("appear"):
            step_fields["appear"] = "0.5"
        if empt("hold"):
            step_fields["hold"] = "2.0"
        if empt("disappear"):
            step_fields["disappear"] = "0.5"
        if empt("overlay_id"):
            step_fields["overlay_id"] = ""
        if empt("delay"):
            step_fields["delay"] = ""
    elif t == "SAY" and empt("val"):
        step_fields["val"] = "0"
    elif t == "EMOTE":
        if empt("action"):
            step_fields["action"] = "show"
        if empt("target"):
            step_fields["target"] = "player"
        if empt("frame_ms"):
            try:
                step_fields["frame_ms"] = str(int(CONFIG.get("EMOTE_DEFAULT_FRAME_MS", 120) or 120))
            except Exception:
                step_fields["frame_ms"] = "120"
        if empt("hold_last_sec"):
            step_fields["hold_last_sec"] = "0"
        if empt("advance"):
            step_fields["advance"] = "continue"
    elif t == "CAMERA":
        if empt("cam_mode"):
            step_fields["cam_mode"] = "follow_player"
        if empt("cam_smooth"):
            step_fields["cam_smooth"] = "true"
        if empt("cam_slot"):
            step_fields["cam_slot"] = "default"
        if empt("cam_duration_sec"):
            step_fields["cam_duration_sec"] = "0.5"


def _music_track_options():
    """assets/musics 폴더의 음악 파일명을 드롭다운 옵션으로 제공(확장자 제거)."""
    base_dir = os.path.join("assets", "musics")
    out = []
    try:
        if not os.path.isdir(base_dir):
            return out
        for fn in sorted(os.listdir(base_dir)):
            low = (fn or "").lower()
            if low.endswith(".mp3") or low.endswith(".ogg") or low.endswith(".wav"):
                out.append(os.path.splitext(fn)[0])
    except Exception:
        return out
    return out


def _export_map_png(map_id: str, bg, objs, npcs, export_dir: str = "exports"):
    """
    에디터용: UI/격자 없이 "맵 배경 + 오브젝트/NPC"를 맵 원본 해상도로 PNG 저장.
    - player는 제외
    """
    mid = str(map_id or "map").strip() or "map"
    # 실행 cwd가 달라져도 항상 프로젝트(현재 파일) 기준으로 저장되게 고정
    base_dir = os.path.dirname(os.path.abspath(__file__))
    export_dir_abs = os.path.join(base_dir, str(export_dir or "exports"))
    try:
        os.makedirs(export_dir_abs, exist_ok=True)
    except Exception:
        export_dir_abs = base_dir

    # bg는 Surface가 원칙이지만, 혹시 경로/문자열이 들어오면 로드해서 처리
    if isinstance(bg, (str, bytes, os.PathLike)):
        try:
            bg = pygame.image.load(os.fspath(bg)).convert()
        except Exception:
            return None
    try:
        bw, bh = bg.get_size()
    except Exception:
        return None

    try:
        if not (bg.get_flags() & pygame.SRCALPHA):
            bg_draw = bg.convert_alpha()
        else:
            bg_draw = bg
    except Exception:
        try:
            bg_draw = bg.convert()
        except Exception:
            bg_draw = bg

    surf = pygame.Surface((int(bw), int(bh)), pygame.SRCALPHA)
    try:
        surf.blit(bg_draw, (0, 0))
    except Exception:
        try:
            surf.blit(bg_draw.convert(), (0, 0))
        except Exception:
            pass

    pool = list(objs or []) + list(npcs or [])
    pool.sort(key=lambda x: (getattr(x, "layer", 0), x.pos[1]))
    for o in pool:
        img = getattr(o, "image", None)
        frames = getattr(o, "frames", None)
        if frames and len(frames) > 1:
            try:
                afi = getattr(o, "_anim_frame_idx", None)
                if callable(afi):
                    img = frames[int(afi()) % len(frames)]
                else:
                    fi = int(getattr(o, "frame_idx", 0) or 0) % len(frames)
                    img = frames[fi]
            except Exception:
                img = frames[0]
        if not img:
            continue
        try:
            iw, ih = img.get_size()
            x = int(round(float(o.pos[0]) - iw / 2))
            y = int(round(float(o.pos[1]) - ih))
            surf.blit(img, (x, y))
        except Exception:
            continue

    ts = int(pygame.time.get_ticks())
    out_path = os.path.join(export_dir_abs, f"{mid}_{ts}.png")
    try:
        pygame.image.save(surf, out_path)
    except Exception:
        return None
    return out_path


def _append_export_log(line: str, export_dir: str = "exports"):
    """터미널 출력이 안 보이는 환경에서도 원인 추적용 로그 파일."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        export_dir_abs = os.path.join(base_dir, str(export_dir or "exports"))
        os.makedirs(export_dir_abs, exist_ok=True)
        p = os.path.join(export_dir_abs, "export_log.txt")
        with open(p, "a", encoding="utf-8") as f:
            f.write(str(line).rstrip() + "\n")
    except Exception:
        pass


def _editor_event_is_f7(event) -> bool:
    """KEYDOWN에서 F7 판별. SDL2에서는 scancode가 물리 키에 더 안정적인 경우가 있다."""
    if event.type != pygame.KEYDOWN:
        return False
    if event.key == pygame.K_F7:
        return True
    try:
        if int(event.key) == int(pygame.K_F7):
            return True
    except Exception:
        pass
    try:
        if getattr(event, "scancode", None) == pygame.KSCAN_F7:
            return True
    except Exception:
        pass
    try:
        kn = pygame.key.name(event.key) if event.key is not None else ""
        if str(kn).upper() == "F7":
            return True
    except Exception:
        pass
    return False


def _editor_export_hotkey_down(keys) -> bool:
    """F7 또는 Ctrl+Shift+E (폴링용)."""
    try:
        if keys[pygame.K_F7]:
            return True
    except Exception:
        pass
    try:
        if keys[pygame.KSCAN_F7]:
            return True
    except Exception:
        pass
    try:
        ctrl = bool(keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL])
        shift = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT])
        if ctrl and shift and (keys[pygame.K_e] or keys[pygame.K_E]):
            return True
    except Exception:
        pass
    return False


def _editor_event_triggers_map_export(event) -> bool:
    """KEYDOWN: F7 / Ctrl+Shift+E."""
    if event.type != pygame.KEYDOWN:
        return False
    if _editor_event_is_f7(event):
        return True
    try:
        k = event.key
        if k in (ord("e"), ord("E"), pygame.K_e, pygame.K_E):
            mods = pygame.key.get_mods()
            if (mods & pygame.KMOD_CTRL) and (mods & pygame.KMOD_SHIFT):
                return True
    except Exception:
        pass
    return False


def _editor_wants_text_input(
    *,
    show_event_config,
    active_field,
    show_zone_config,
    active_zone_field,
    show_bgzone_config,
    active_bgzone_field,
    show_step_config,
    active_step_field,
    obj_height_active,
    obj_sprite_tilt_active,
    obj_layer_active,
):
    return bool(
        (show_event_config and active_field)
        or (show_zone_config and active_zone_field)
        or (show_bgzone_config and active_bgzone_field)
        or (show_step_config and active_step_field)
        or (char_def_modal.show and char_def_modal.active_field)
        or (char_inst_modal.show and char_inst_modal.active_field)
        or (obj_def_modal.show and obj_def_modal.active_field)
        or (obj_inst_modal.show and obj_inst_modal.active_field)
        or (presence_zone_modal.show and presence_zone_modal.active_field)
        or obj_height_active
        or obj_sprite_tilt_active
        or obj_layer_active
    )


def _editor_sync_text_input(wants: bool):
    """IME/텍스트 입력은 필드 편집 중에만 — 항상 켜두면 F7 등 단축키가 안 들어오는 환경이 있다."""
    try:
        if wants:
            pygame.key.start_text_input()
        else:
            pygame.key.stop_text_input()
    except Exception:
        pass


def _editor_map_obj_inspector_layout(screen_w, screen_h, sidebar_w):
    """
    맵 편집: 단일 선택 시 높이·틸트 입력 (왼쪽 정렬, 두 줄로 겹침 방지).
    반환: bar, height_rect, tilt_rect, ysort_rect 등.
    """
    bar_h = EDITOR_INSPECTOR_H
    bar_top = int(screen_h) - EDITOR_STATUS_BAR_H - bar_h
    bar = pygame.Rect(0, bar_top, screen_w, bar_h)
    ix = int(sidebar_w) + 10
    row_h = bar_top + 10
    row_t = bar_top + 38
    field_w = 88
    # 라벨 뒤 입력칸
    h_field_x = ix + 118
    t_field_x = ix + 118
    hr = pygame.Rect(h_field_x, row_h, field_w, 22)
    tr = pygame.Rect(t_field_x, row_t, field_w, 22)
    yr = pygame.Rect(bar.right - 200, row_h, 188, 22)
    lr = pygame.Rect(bar.right - 200, row_t, 188, 22)
    return {
        "bar": bar,
        "height_rect": hr,
        "tilt_rect": tr,
        "ysort_rect": yr,
        "layer_rect": lr,
        "ix": ix,
        "row_h": row_h,
        "row_t": row_t,
    }


def _editor_right_sidebar_view_bottom(
    *,
    screen_h: int,
    edit_mode: str,
    map_tool: str,
    selected_nodes,
    sidebar_w: int,
    event_preview_sel=None,
):
    """
    우측 사이드바 리스트가 실제로 '보이는' 하단 경계.

    - 항상 하단 상태바(30px)를 피한다.
    - MAP/OBJECTS에서 단일 선택이면 하단 인스펙터(설정상자)가 올라오므로 그 top까지로 제한한다.

    이 값이 작아야 스크롤/클리핑/툴팁 판정이 '가려진 영역'을 포함하지 않는다.
    """
    vb = _editor_sidebar_list_bottom(screen_h)
    try:
        if (edit_mode or "").upper() == "MAP" and (map_tool or "").upper() == "OBJECTS":
            if selected_nodes and len(selected_nodes) == 1:
                L = _editor_map_obj_inspector_layout(0, int(screen_h), int(sidebar_w))
                vb = min(vb, int(L["bar"].top))
        elif (edit_mode or "").upper() == "EVENT" and event_preview_sel:
            L = _editor_map_obj_inspector_layout(0, int(screen_h), int(sidebar_w))
            vb = min(vb, int(L["bar"].top))
    except Exception:
        pass
    return max(1, vb)


def _preview_upto_index(show_step_config, step_edit_index, step_insert_index, steps, selected_step_idx):
    if show_step_config:
        if step_edit_index is not None:
            return step_edit_index
        if step_insert_index is not None:
            return max(-1, step_insert_index - 1)
        return max(-1, len(steps) - 1)
    if selected_step_idx >= 0:
        return selected_step_idx
    if steps:
        return len(steps) - 1
    return -1


def _simulate_event_preview(steps, upto_inclusive, player, objs, npcs):
    """누적 위치와 MOVE 화살표(에디터 표시용)."""
    pos = {}
    pos["player"] = [float(player.pos[0]), float(player.pos[1])]
    for n in npcs:
        pos[n.name] = [float(n.pos[0]), float(n.pos[1])]
    for o in objs:
        pos[o.name] = [float(o.pos[0]), float(o.pos[1])]
    arrows = []
    last_step_for = {}

    n_steps = len(steps)
    last_i = min(upto_inclusive, n_steps - 1)
    if last_i < 0:
        return pos, arrows, last_step_for

    for si in range(last_i + 1):
        st = steps[si]
        typ = (st.get("type") or "").upper()
        if typ == "PLACE":
            tgt = (st.get("target") or "").strip()
            if not tgt:
                continue
            if st.get("action") == "remove":
                pos.pop(tgt, None)
            else:
                p = st.get("pos")
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    pos[tgt] = [float(p[0]), float(p[1])]
                    last_step_for[tgt] = si
        elif typ == "MOVE":
            tgt = (st.get("target") or "").strip()
            p = st.get("pos")
            wpl = []
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                if not isinstance(p[0], (list, tuple)):
                    wpl = [[float(p[0]), float(p[1])]]
                else:
                    for sub in p:
                        if isinstance(sub, (list, tuple)) and len(sub) >= 2:
                            wpl.append([float(sub[0]), float(sub[1])])
            if not tgt or not wpl:
                continue
            ins = st.get("instant")
            if isinstance(ins, str):
                instant = ins.strip().lower() in ("1", "true", "yes", "on")
            else:
                instant = bool(ins)
            for wi in range(len(wpl)):
                tx, ty = wpl[wi][0], wpl[wi][1]
                fx = fy = None
                if tgt in pos:
                    fx, fy = pos[tgt][0], pos[tgt][1]
                if fx is not None:
                    arrows.append(
                        {
                            "x1": fx,
                            "y1": fy,
                            "x2": tx,
                            "y2": ty,
                            "step": si,
                            "tgt": tgt,
                            "instant": instant,
                        }
                    )
                pos[tgt] = [tx, ty]
            last_step_for[tgt] = si

    return pos, arrows, last_step_for


def _resolve_preview_base_image(name, player, objs, npcs, cache):
    """이벤트 시뮬 전용: 맵에 없는 PLACE 대상도 OBJ/CHAR 에셋으로 스프라이트 확보."""
    if name == "player":
        return player.image
    for pool in (objs, npcs):
        for ent in pool:
            if getattr(ent, "name", None) == name:
                return ent.image
    if name in cache:
        return cache[name]
    if name in OBJ_ASSETS:
        try:
            o = FieldItem(name, 0, 0)
            cache[name] = o.image
            return o.image
        except Exception:
            return None
    if name in CHAR_ASSETS:
        try:
            c = BaseCharacter(name, [0, 0], {})
            cache[name] = c.image
            return c.image
        except Exception:
            return None
    return None


def _editor_world_map_row_by_name(world_data, map_id, name, *, kind="obj"):
    """맵 인스턴스 1개 — 동일 name 이 여러 개면 첫 항목."""
    m = (world_data or {}).get(map_id, {}) if map_id else {}
    key = "objects" if kind == "obj" else "npcs"
    for row in m.get(key, []) or []:
        if isinstance(row, dict) and str(row.get("name") or "").strip() == str(name or "").strip():
            return row
    return None


def _editor_preview_interact_spec_for_name(name, objs, npcs, world_data, map_id):
    """EVENT 미리보기용 병합 interact spec (없으면 None)."""
    from flow import entity_interact_spec, interact_spec_enabled, merge_interact_spec

    nm = str(name or "").strip()
    if not nm or nm == "player":
        return None

    for o in objs:
        if getattr(o, "name", None) == nm:
            spec = entity_interact_spec(o)
            return spec if interact_spec_enabled(spec) else None

    for n in npcs:
        if getattr(n, "name", None) != nm:
            continue
        try:
            from char_behavior import npc_interact_enabled

            if npc_interact_enabled(n):
                return entity_interact_spec(n) or {}
            spec = entity_interact_spec(n)
            return spec if interact_spec_enabled(spec) else None
        except Exception:
            spec = entity_interact_spec(n)
            return spec if interact_spec_enabled(spec) else None

    if nm in OBJ_ASSETS:
        row = _editor_world_map_row_by_name(world_data, map_id, nm, kind="obj")
        inst = (row or {}).get("interact") if isinstance(row, dict) else None
        spec = merge_interact_spec(
            OBJ_ASSETS.get(nm, {}),
            {"interact": inst} if isinstance(inst, dict) else {},
        )
        return spec if interact_spec_enabled(spec) else None

    if nm in CHAR_ASSETS:
        row = _editor_world_map_row_by_name(world_data, map_id, nm, kind="npc")
        merged = dict(CHAR_ASSETS.get(nm, {}) or {})
        if isinstance(row, dict):
            if row.get("interact"):
                merged["interact"] = dict(merged.get("interact") or {})
                merged["interact"].update(row.get("interact") or {})
            if row.get("talk"):
                merged["talk"] = dict(merged.get("talk") or {})
                merged["talk"].update(row.get("talk") or {})
        talk = merged.get("talk") or {}
        inter = merged.get("interact") or {}
        if talk.get("lines") or talk.get("fallback"):
            return inter if isinstance(inter, dict) else {}
        return inter if interact_spec_enabled(inter) else None

    return None


def _editor_preview_interact_anchor_range(name, foot_xy, objs, npcs, world_data, map_id):
    """
    EVENT 스텝 미리보기 — (중심 x, y, range) 월드 px.
    중심 = 미리보기 발 위치 + interact.offset.
    """
    from flow import interact_spec_offset, interact_spec_enabled

    spec = _editor_preview_interact_spec_for_name(name, objs, npcs, world_data, map_id)
    if not isinstance(spec, dict):
        return None
    nm = str(name or "").strip()
    try:
        fx, fy = float(foot_xy[0]), float(foot_xy[1])
    except (TypeError, ValueError, IndexError):
        return None
    dx, dy = interact_spec_offset(spec)
    if nm in CHAR_ASSETS and not interact_spec_enabled(spec):
        try:
            rng = float(CONFIG.get("NPC_INTERACT_RANGE", 48))
        except (TypeError, ValueError):
            rng = 48.0
    else:
        try:
            default = (
                float(CONFIG.get("NPC_INTERACT_RANGE", 48))
                if nm in CHAR_ASSETS
                else float(CONFIG.get("OBJECT_INTERACT_RANGE", 40))
            )
        except (TypeError, ValueError):
            default = 48.0 if nm in CHAR_ASSETS else 40.0
        try:
            rng = float(spec.get("range", default))
        except (TypeError, ValueError):
            rng = default
    return fx + dx, fy + dy, rng


def _editor_find_map_entity_by_name(name, objs, npcs):
    nm = str(name or "").strip()
    for o in objs:
        if getattr(o, "name", None) == nm:
            return o, "obj"
    for n in npcs:
        if getattr(n, "name", None) == nm:
            return n, "npc"
    return None, None


def _editor_open_interact_type_modal(name):
    """이벤트 미리보기·FLOW 등 — 타입 상호작용 설정(object_defs / char_defs)."""
    nm = str(name or "").strip()
    if not nm or nm == "player":
        return
    if nm in CHAR_ASSETS:
        char_def_modal.open(nm)
    elif nm in OBJ_ASSETS:
        obj_def_modal.open(nm)


def _editor_event_preview_pick_at_screen(
    mx,
    my,
    *,
    sidebar_w,
    top_bar_h,
    steps,
    upto_inclusive,
    player,
    objs,
    npcs,
    cam_x,
    cam_y,
    zoom_level,
    bg_w,
    bg_h,
    map_area_w,
    view_h,
    preview_sprite_cache,
    scaled_cache,
):
    """EVENT 작업창 — 미리보기 스프라이트 위 클릭 시 이름(맨 앞에 그려진 것 우선)."""
    if upto_inclusive < 0 or not steps:
        return None
    lx = float(mx) - float(sidebar_w)
    ly = float(my) - float(top_bar_h)
    if lx < 0 or ly < 0 or lx >= map_area_w or ly >= view_h:
        return None
    _ox = float(map_area_w) / 2.0
    _oy = float(view_h) / 2.0
    bg_blit_x, bg_blit_y = bg_anchor(float(cam_x), float(cam_y), float(zoom_level), _ox, _oy)
    zl = max(0.25, float(zoom_level))
    sw_bg = max(1, int(bg_w * zl))
    sh_bg = max(1, int(bg_h * zl))
    pos_sim, _, _ = _simulate_event_preview(steps, upto_inclusive, player, objs, npcs)
    picked = None
    for name, p in sorted(pos_sim.items(), key=lambda kv: kv[1][1], reverse=True):
        base_img = _resolve_preview_base_image(name, player, objs, npcs, preview_sprite_cache)
        hit = False
        if base_img:
            orig_w, orig_h = base_img.get_size()
            sk = ("_evpv", name, round(zl * 1000))
            if sk not in scaled_cache:
                scaled_cache[sk] = pygame.transform.scale(
                    base_img, (int(orig_w * zl), int(orig_h * zl))
                )
            s_img = scaled_cache[sk]
            fpx, fpy = world_to_map_surface_xy(
                bg_blit_x, bg_blit_y, float(p[0]), float(p[1]), bg_w, bg_h, sw_bg, sh_bg, 0.0
            )
            final_x, final_y = blit_topleft_bottom_center(
                fpx, fpy, s_img.get_width(), s_img.get_height()
            )
            pr = pygame.Rect(final_x, final_y, s_img.get_width(), s_img.get_height())
            hit = _editor_surface_alpha_hit(s_img, pr, lx, ly)
        else:
            sx, sy = world_to_map_surface_xy(
                bg_blit_x, bg_blit_y, float(p[0]), float(p[1]), bg_w, bg_h, sw_bg, sh_bg, 0.0
            )
            rad = max(6, int(8 * min(zl, 2)))
            hit = math.hypot(lx - float(sx), ly - float(sy)) <= float(rad)
        if hit:
            picked = name
            break
    return picked


def _editor_draw_interact_range_on_map(
    map_surf,
    bg_blit_x,
    bg_blit_y,
    wx,
    wy,
    radius_world,
    bg_w,
    bg_h,
    sw_bg,
    sh_bg,
    viewport_rect,
    *,
    color=(255, 90, 200),
):
    """월드 interact.range 를 맵 작업면에 원(접근 거리)으로 표시."""
    try:
        rw = float(radius_world)
    except (TypeError, ValueError):
        return
    if rw <= 0:
        return
    cx, cy = world_to_map_surface_xy(
        bg_blit_x, bg_blit_y, float(wx), float(wy), bg_w, bg_h, sw_bg, sh_bg, 0.0
    )
    r_px = max(2, int(round(rw * float(sw_bg) / max(1.0, float(bg_w)))))
    if not viewport_rect.inflate(r_px * 2 + 8, r_px * 2 + 8).collidepoint(int(cx), int(cy)):
        return
    dia = r_px * 2 + 6
    try:
        ov = pygame.Surface((dia, dia), pygame.SRCALPHA)
        pygame.draw.circle(ov, (*color[:3], 42), (dia // 2, dia // 2), r_px, 0)
        pygame.draw.circle(ov, (*color[:3], 110), (dia // 2, dia // 2), r_px, 2)
        map_surf.blit(ov, (int(cx) - dia // 2, int(cy) - dia // 2))
    except Exception:
        pygame.draw.circle(map_surf, color, (int(cx), int(cy)), r_px, 2)


def _draw_arrow_on_map(surf, x1, y1, x2, y2, color, zoom):
    pygame.draw.line(surf, color, (int(x1), int(y1)), (int(x2), int(y2)), max(1, int(2 * min(zoom, 2))))
    ang = math.atan2(y2 - y1, x2 - x1)
    ah = 10 * min(zoom, 1.5)
    for a in (0.45, -0.45):
        ax = x2 - ah * math.cos(ang + a)
        ay = y2 - ah * math.sin(ang + a)
        pygame.draw.line(surf, color, (int(x2), int(y2)), (int(ax), int(ay)), max(1, int(2 * min(zoom, 2))))


def _editor_font_line_width(font, text):
    try:
        return int(font.size(str(text))[0])
    except Exception:
        return max(1, len(str(text)) * 7)


def _editor_truncate_text_to_width(font, text, max_w, *, min_chars=6):
    """말줄임(…): max_w 픽셀 안에 들어가게 자름. 앞부분은 최소 min_chars 글자 우선."""
    s = str(text)
    if not s:
        return "", False
    if max_w <= 8:
        n = min(len(s), max(1, min_chars))
        return s[:n], len(s) > n
    if _editor_font_line_width(font, s) <= max_w:
        return s, False
    ell = "…"
    w_ell = _editor_font_line_width(font, ell)
    lo, hi = 0, len(s)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = (s[:mid] + ell) if mid < len(s) else s
        if _editor_font_line_width(font, cand) <= max_w:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    # 폭이 너무 좁아 '…'만 남는 경우 → 앞글자부터 최대한 표시
    only_ell = best in ("", ell) or (len(best) <= len(ell) and ell in best)
    if only_ell:
        cap = min(len(s), max(min_chars, 48))
        for k in range(1, cap + 1):
            cand = s[:k] + (ell if k < len(s) else "")
            if _editor_font_line_width(font, cand) <= max_w:
                best = cand
            else:
                if k > 1:
                    prev = s[: k - 1] + ell
                    if _editor_font_line_width(font, prev) <= max_w:
                        best = prev
                elif k == 1:
                    best = s[:1]
                break
    return best, best != s


def _editor_step_list_visible_line(font, head, detail, max_w, *, min_detail_chars=10):
    """스텝 리스트 한 줄: '3. say' + '(대사 앞부분…)' — 타입은 잘리지 않음."""
    head = str(head)
    detail = str(detail).strip()
    if not detail:
        return _editor_truncate_text_to_width(font, head, max_w, min_chars=4)
    open_s = head + "("
    close_s = ")"
    avail = max(
        32,
        int(max_w)
        - _editor_font_line_width(font, open_s)
        - _editor_font_line_width(font, close_s),
    )
    det_vis, clipped = _editor_truncate_text_to_width(
        font, detail, avail, min_chars=min_detail_chars
    )
    return open_s + det_vis + close_s, clipped


def _editor_fmt_step_pos(pos):
    """MOVE/PLACE/MAP pos → 'x,y' 또는 'Npts'."""
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        return ""
    try:
        if isinstance(pos[0], (list, tuple)):
            p = pos[-1]
            return f"{int(float(p[0]))},{int(float(p[1]))} ({len(pos)}pts)"
        return f"{int(float(pos[0]))},{int(float(pos[1]))}"
    except (TypeError, ValueError, IndexError):
        return ""


def _editor_step_preview_text(step, *, max_chars=80):
    """SAY 등 대사 미리보기 (첫 줄). 리스트 폭 자르기는 렌더 시 처리."""
    raw = str(step.get("text") or step.get("message") or "").replace("\r", "")
    if not raw.strip():
        return ""
    line = raw.split("\n", 1)[0].strip()
    if len(line) > max_chars:
        return line[:max_chars]
    return line


def _editor_tooltip_wrap_lines(text, max_chars=None):
    """툴팁용: 긴 한 줄을 여러 줄로 (앞부분부터). 픽셀 재줄바꿈은 draw 시 처리."""
    if max_chars is None:
        try:
            side = int(CONFIG.get("EDITOR_SIDEBAR_WIDTH_PX", 220) or 220)
            mul = float(CONFIG.get("EDITOR_TOOLTIP_WIDTH_SIDEBAR_MUL", 1.5) or 1.5)
            max_chars = max(40, int(side * mul / 6))
        except (TypeError, ValueError):
            max_chars = 78
    out = []
    for raw in str(text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            out.append("")
            continue
        while len(line) > max_chars:
            out.append(line[:max_chars])
            line = line[max_chars:]
        out.append(line)
    return out


def _editor_step_list_summary(index, step):
    """
    이벤트 스텝 사이드바용 (짧은 라벨, 호버 툴팁 본문).
    툴팁 인프라는 기존 sidebar_list_tooltip 을 그대로 씀.
    """
    st = (step.get("type") or "MOVE").upper()
    tip = [f"{index}. [{st}]"]
    parts = []

    def _tip(key, val):
        if val is None:
            return
        s = str(val).strip()
        if s != "":
            tip.append(f"{key}: {s}")

    tg = (step.get("target") or step.get("who") or step.get("bubble_target") or "").strip()

    if st == "MOVE":
        t = tg or "player"
        parts.append(t)
        pos_s = _editor_fmt_step_pos(step.get("pos"))
        if pos_s:
            parts.append(pos_s)
        _tip("target", t)
        _tip("pos", pos_s or step.get("pos"))
        for k in ("dir", "wait", "force", "instant", "speed", "move_sync"):
            _tip(k, step.get(k))
        ma = (step.get("move_anim") or step.get("path_anim") or "").strip()
        if ma:
            parts.append(f"+{ma}")
            _tip("move_anim", ma)
    elif st == "PLACE":
        t = tg or "?"
        parts.append(t)
        act = (step.get("action") or "").strip()
        if act:
            parts.append(act)
        pos_s = _editor_fmt_step_pos(step.get("pos"))
        if pos_s:
            parts.append(pos_s)
        _tip("target", t)
        _tip("action", act)
        _tip("pos", pos_s or step.get("pos"))
        for k in ("dir", "appear", "layer", "visible"):
            _tip(k, step.get(k))
    elif st == "SAY":
        who = tg or "player"
        preview = _editor_step_preview_text(step)
        if preview:
            parts.append(preview)
        else:
            parts.append(who)
        _tip("who", who)
        _tip("bubble_target", step.get("bubble_target"))
        full = str(step.get("text") or "").replace("\r", "").strip()
        if full:
            tip.append("text:")
            wrapped = _editor_tooltip_wrap_lines(full, max_chars=52)
            tip.extend(wrapped[:12])
            if len(wrapped) > 12:
                tip.append("…")
    elif st == "CARRY":
        act = (step.get("action") or "pick").strip()
        parts.append(act)
        t = tg or "?"
        if t:
            parts.append(t)
        pos_s = _editor_fmt_step_pos(step.get("pos"))
        if pos_s:
            parts.append(pos_s)
        _tip("action", act)
        _tip("holder", step.get("holder") or "player")
        _tip("target", t)
        _tip("pos", pos_s or step.get("pos"))
        _tip("wait", step.get("wait", True))
    elif st == "CHANGE":
        to_k = (step.get("to") or step.get("new_name") or "").strip()
        parts.append(tg or "held")
        if to_k:
            parts.append(f"→{to_k}")
        _tip("target", tg or "held")
        _tip("to", to_k)
    elif st == "ACTION_ANIM":
        t = tg or "player"
        an = (step.get("anim") or step.get("name") or step.get("state") or "").strip()
        parts.append(t)
        if an:
            parts.append(an)
        _tip("target", t)
        _tip("anim", an)
        for k in ("mode", "dir", "loop", "release", "val", "duration"):
            _tip(k, step.get(k))
    elif st == "EMOTE":
        if (step.get("action") or "").strip().lower() == "clear":
            parts.append("clear")
            _tip("action", "clear")
        else:
            em = (step.get("emotion") or step.get("name") or "").strip()
            if em:
                parts.append(em)
            if tg:
                parts.append(f"@{tg}")
            _tip("emotion", em)
            _tip("target", tg)
    elif st in ("WAIT", "INTERVAL"):
        v = step.get("val")
        if v is not None and str(v).strip() != "":
            parts.append(f"{v}s")
            _tip("val", f"{v}s")
    elif st == "OVERLAY_UI":
        act = (step.get("action") or "show").strip().lower()
        parts.append(act)
        oid = (step.get("overlay_id") or "").strip()
        if oid:
            parts.append(f"#{oid}")
        dl = step.get("delay", step.get("delay_sec"))
        if dl is not None and str(dl).strip() != "":
            try:
                if float(dl) > 0.0:
                    parts.append(f"after {dl}s")
            except (TypeError, ValueError):
                pass
        if act == "show":
            ho = step.get("hold", step.get("hold_sec"))
            if ho is not None and str(ho).strip() != "" and not step.get("hold_forever"):
                parts.append(f"hold {ho}s")
            tx = (step.get("text") or "").strip()
            if tx:
                parts.append(tx[:12] + ("…" if len(tx) > 12 else ""))
        _tip("action", act)
        _tip("overlay_id", oid)
        _tip("delay", dl)
        _tip("hold", step.get("hold"))
    elif st == "CAMERA":
        mode = (step.get("mode") or "follow_player").strip()
        parts.append(mode)
        _tip("mode", mode)
        if mode in ("fixed", "fixed_world", "world", "point"):
            try:
                xy = f"{int(float(step.get('x', 0)))},{int(float(step.get('y', 0)))}"
                parts.append(xy)
                _tip("xy", xy)
            except (TypeError, ValueError):
                pass
        elif (step.get("target") or step.get("name") or "").strip():
            _tip("target", step.get("target") or step.get("name"))
        for k in ("smooth", "duration_sec", "lerp"):
            _tip(k, step.get(k))
    elif st == "MAP":
        mid = (step.get("target") or step.get("map") or step.get("map_id") or "").strip()
        if mid:
            parts.append(mid)
        pos_s = _editor_fmt_step_pos(step.get("pos"))
        if pos_s:
            parts.append(pos_s)
        _tip("map", mid)
        _tip("pos", pos_s or step.get("pos"))
        _tip("dir", step.get("dir"))
    elif st in ("ZOOM", "TILT", "SHEAR"):
        on = step.get("on")
        parts.append("on" if on in (True, "true", "1", 1, "on") else "off")
        _tip("on", on)
        for k in ("strength", "duration_sec", "target", "val"):
            _tip(k, step.get(k))
    elif st in ("FADEIN", "FADEOUT"):
        v = step.get("val")
        if v is not None and str(v).strip() != "":
            parts.append(f"{v}s")
        _tip("val", v)
    elif st == "FX":
        parts.append((step.get("kind") or step.get("name") or "fx").strip())
        _tip("on", step.get("on"))
    elif st == "CONDITION":
        c = (step.get("condition") or step.get("expr") or "").strip()
        if not c and step.get("var"):
            c = f"{step.get('var')} {step.get('op', '')}".strip()
        if c:
            parts.append(c[:28] + ("…" if len(c) > 28 else ""))
        _tip("condition", c)
    elif st == "CONDITION_SKIP":
        parts.append("skip-end")
    elif st in ("LOOP_START", "LOOP_END"):
        pass
    elif st in ("EVT_STOP_BEGIN", "EVT_STOP_END"):
        act = (step.get("action") or "").strip()
        if act:
            parts.append(act)
        _tip("action", act)
    elif st == "CALL_EVENT":
        fid = (step.get("target") or step.get("fragment") or "").strip()
        parts.append(f"@{fid}" if fid else "CALL")
        _tip("target", fid)
    elif st == "DEV_CMD":
        cmd = (step.get("cmd") or step.get("command") or "").strip()
        if cmd:
            parts.append(cmd)
        _tip("cmd", cmd)
    elif st.startswith("MUSIC"):
        parts.append((step.get("music") or step.get("name") or "").strip() or st.lower())
        for k in ("music", "name", "volume", "fade_in", "fade_out", "queue"):
            _tip(k, step.get(k))
    elif st in ("FOLLOW_START", "FOLLOW_STOP"):
        parts.append(tg or "player")
        _tip("target", tg)
    else:
        if tg:
            parts.append(tg)
            _tip("target", tg)
        for k in ("name", "action", "text", "val", "anim"):
            if step.get(k) not in (None, ""):
                _tip(k, step.get(k))

    head = f"{index}. {st.lower()}"
    detail = ", ".join(parts) if parts else ""
    tooltip = "\n".join(tip)
    return head, detail, tooltip


def _editor_step_list_tooltip_enabled():
    try:
        return bool(CONFIG.get("EDITOR_STEP_LIST_TOOLTIP_ENABLED", True))
    except Exception:
        return True


def _editor_step_list_tooltip_ok(
    show_event_config,
    show_zone_config,
    show_bgzone_config,
    show_multi_delete_confirm=False,
):
    """스텝 리스트 전용: STEP 설정 모달이 열려 있어도 우측 리스트 호버 툴팁 허용."""
    if not _editor_step_list_tooltip_enabled():
        return False
    return not (
        show_event_config
        or show_zone_config
        or show_bgzone_config
        or show_multi_delete_confirm
        or any_char_modal_open()
    )


def _editor_sidebar_list_tooltip_ok(
    show_event_config,
    show_zone_config,
    show_bgzone_config,
    show_step_config,
    show_multi_delete_confirm=False,
):
    return not (
        show_event_config
        or show_zone_config
        or show_bgzone_config
        or show_step_config
        or show_multi_delete_confirm
        or any_char_modal_open()
    )


def _editor_wrap_lines_to_pixel_width(font, lines, max_body_w):
    """긴 줄을 픽셀 폭 기준으로 잘라 여러 줄로 (앞부분부터)."""
    out = []
    max_body_w = max(80, int(max_body_w))
    for ln in lines:
        s = str(ln).replace("\r", "")
        if not s:
            out.append("")
            continue
        if _editor_font_line_width(font, s) <= max_body_w:
            out.append(s)
            continue
        buf = ""
        for ch in s:
            trial = buf + ch
            if _editor_font_line_width(font, trial) <= max_body_w:
                buf = trial
            else:
                if buf:
                    out.append(buf)
                buf = ch
        if buf:
            out.append(buf)
    return out


def _editor_draw_hover_tooltip(screen, font, screen_w, screen_h, mx, my, text):
    """마우스 근처에 여러 줄 툴팁 (반투명, 리스트보다 ~50% 넓게)."""
    if not str(text or "").strip():
        return
    try:
        side_px = int(CONFIG.get("EDITOR_SIDEBAR_WIDTH_PX", 220) or 220)
    except (TypeError, ValueError):
        side_px = 220
    try:
        mul = float(CONFIG.get("EDITOR_TOOLTIP_WIDTH_SIDEBAR_MUL", 1.5) or 1.5)
    except (TypeError, ValueError):
        mul = 1.5
    mul = max(1.0, min(2.5, mul))
    try:
        max_body_w = int(CONFIG.get("EDITOR_TOOLTIP_MAX_BODY_WIDTH_PX", 0) or 0)
    except (TypeError, ValueError):
        max_body_w = 0
    if max_body_w <= 0:
        max_body_w = int(side_px * mul)
    try:
        bg_alpha = int(CONFIG.get("EDITOR_TOOLTIP_BG_ALPHA", 185) or 185)
    except (TypeError, ValueError):
        bg_alpha = 185
    bg_alpha = max(72, min(245, bg_alpha))

    raw_lines = [ln.replace("\r", "") for ln in str(text).split("\n")]
    lines = _editor_wrap_lines_to_pixel_width(font, raw_lines, max_body_w)
    surfs = []
    for ln in lines:
        if ln == "":
            continue
        surfs.append(font.render(ln, True, (235, 240, 250)))
    if not surfs:
        return
    pad = 8
    gap = 2
    w = max(max_body_w, max(s.get_width() for s in surfs)) + pad * 2
    h = sum(s.get_height() for s in surfs) + gap * (len(surfs) - 1) + pad * 2
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    surf.fill((22, 26, 34, bg_alpha))
    y = pad
    for s in surfs:
        surf.blit(s, (pad, y))
        y += s.get_height() + gap
    pygame.draw.rect(surf, (150, 170, 210, bg_alpha), surf.get_rect(), 1)
    # 우측 스텝 리스트: 맵 쪽(왼쪽)으로 넓게 펼쳐 리스트 가리지 않게
    if mx > screen_w - side_px - 80:
        bx = mx - w - 12
    else:
        bx = mx + 14
    by = my - h - 10
    if by < 4:
        by = min(screen_h - h - 4, my + 18)
    if bx + w > screen_w - 4:
        bx = screen_w - w - 4
    if bx < 4:
        bx = 4
    if by + h > screen_h - 4:
        by = screen_h - h - 4
    screen.blit(surf, (bx, by))


# 맵 모드 우측 오브젝트/NPC 목록용 미리보기 (픽셀)
_SIDEBAR_THUMB_PX = 22


def _sidebar_asset_thumbnail(kind, name, cache: dict, use_smooth_scale: bool = False):
    """kind: 'obj' | 'char'. 정사각형 안에 비율 유지로 축소한 Surface (캐시).

    use_smooth_scale: True면 smoothscale(느림·부드러움), False면 scale(픽셀·가벼움).
    """
    key = (kind, name, bool(use_smooth_scale))
    if key in cache:
        return cache[key]
    src = None
    try:
        if kind == "obj" and name in OBJ_ASSETS:
            o = FieldItem(name, 0.0, 0.0)
            src = o.frames[0] if getattr(o, "frames", None) else o.image
        elif kind == "char" and name in CHAR_ASSETS:
            c = BaseCharacter(name, [0.0, 0.0], {})
            src = c.image
    except Exception:
        src = None
    tw = th = _SIDEBAR_THUMB_PX
    if src is None:
        s = pygame.Surface((tw, th))
        s.fill((52, 52, 68))
        pygame.draw.rect(s, (95, 95, 115), s.get_rect(), 1)
        cache[key] = s
        return s
    w, h = src.get_size()
    scale = min(tw / max(w, 1), th / max(h, 1))
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    try:
        if use_smooth_scale:
            scaled = pygame.transform.smoothscale(src, (nw, nh))
        else:
            scaled = pygame.transform.scale(src, (nw, nh))
    except Exception:
        scaled = pygame.transform.scale(src, (nw, nh))
    out = pygame.Surface((tw, th), pygame.SRCALPHA)
    out.fill((0, 0, 0, 0))
    out.blit(scaled, ((tw - nw) // 2, (th - nh) // 2))
    pygame.draw.rect(out, (100, 110, 130), out.get_rect(), 1)
    cache[key] = out
    return out


def editor_main():
    pygame.init()
    # 에디터 전체 창 크기
    SCREEN_W, SCREEN_H = 1500, 900
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)
    pygame.display.set_caption("여름이 엔진 에디터 - 이벤트 기능 확장 버전")
    _editor_sync_text_input(False)

    scaled_cache = {}
    preview_sprite_cache = {}
    sidebar_thumb_cache = {}
    # 우측 에셋 썸네일: 기본은 거친 픽셀(scale). 다수 선택·대량 에셋 시 PC 부하 완화. F8 또는 우측 상단 버튼으로 부드러운 스케일 토글.
    editor_smooth_sidebar_thumbs = False

    editor_ui_state = _load_editor_ui_state()
       
    scroll_y_left = 0
    scroll_y_right = 0
    scroll_y_steps = 0
    sidebar_left_sb_drag = False
    sidebar_right_sb_drag = False
    LINE_H = EDITOR_LINE_H
    
    edit_mode = "MAP"  # "MAP" | "EVENT" | "FLOW"

    # --- FLOW 모드 (맵 캐릭터/오브젝트 ↔ 이벤트 연결) ---
    flow_entity_entries = []
    flow_selected_entity_idx = -1
    flow_graph = None
    flow_scroll_x = 0
    flow_scroll_y = 0
    flow_panning = False
    flow_pan_last = (0, 0)
    flow_entity_node_counts = {}
    flow_hit_boxes = []
    flow_opened_settings = False
    flow_placed_collapsed = _editor_collapsed_set_from_state(
        editor_ui_state, EDITOR_UI_COLLAPSE_FLOW_LEFT
    )

    def _flow_node_count():
        if not flow_graph:
            return 0
        return len(flow_graph.get("nodes") or [])

    def _flow_entity_key(entry):
        if entry.get("kind") == "zone":
            return ("zone", entry.get("name"), int(entry.get("zone_index", -1)))
        n = entry.get("node")
        return (entry.get("kind"), entry.get("name"), id(n) if n is not None else 0)

    def _flow_diagram_for_entry(ent):
        if ent.get("kind") == "zone":
            return build_zone_flow_diagram(
                ent.get("zone_data") or {},
                ent.get("map_id") or map_id,
                ent.get("zone_index", 0),
                all_events,
                events_catalog,
            )
        return build_entity_flow_diagram(
            ent["name"],
            ent["kind"],
            all_events,
            events_catalog,
            entity_node=ent.get("node"),
            char_assets=CHAR_ASSETS,
            obj_assets=OBJ_ASSETS,
        )

    def _flow_recount_all_entity_nodes():
        nonlocal flow_entity_node_counts
        counts = {}
        for ent in flow_entity_entries:
            try:
                dg = _flow_diagram_for_entry(ent)
                counts[_flow_entity_key(ent)] = len(dg.get("nodes") or [])
            except Exception:
                counts[_flow_entity_key(ent)] = 0
        flow_entity_node_counts = counts

    current_event_id = None     # 예: 'talk_npc_1'
    current_event_type = None   # 'LOCAL' 또는 'GLOBAL'
    selected_step_idx = -1      # 스텝 리스트 중 선택된 번호
    event_preview_sel = None    # EVENT 미리보기 스프라이트 클릭 선택 (이름)
    event_preview_pick_ms = 0
    event_preview_pick_name = None

    is_dragging = False
    show_mask = False 
    mask_surf_alpha = None # 투명도가 적용된 마스크 서피스 저장용

    show_event_config = False      # 설정창 표시 여부
    config_target_id = None        # 수정 중인 경우 해당 ID (생성이면 None)
    input_fields = {               # 입력 데이터 저장소
        "cat": "LOCAL",            # 로컬/글로벌
        "eid": "",                 # ev_map_name_...
        "title": "",               # 이벤트 이름
        "res_prog": "",            # 결과 progress
        "res_opt": "",             # 추가 옵션 (JSON 문자열 형태, mainprogress 제외)
        "trigger": "auto",        # GLOBAL: auto / global / intercept (코드 전용은 미포함)
        "condition": "",          # GLOBAL: save 조건식
        "priority": "100",         # GLOBAL: 낮을수록 먼저
        "work_map": "",           # GLOBAL: 에디터 미리보기용 맵 ID
        "escape_mode": "none",
        "escape_action": "end",
        "escape_key": "",
        "escape_condition": "",
    }
    active_field = None            # 현재 타이핑 중인 칸 (eid, title 등)

    # --- MAP: 이벤트 박스(event_zones) 추가 모달 ---
    show_zone_config = False
    zone_edit_idx = None  # 현재는 추가 위주(추후 수정 확장용)
    zone_fields = {
        "name": "",
        "event_id": "",
        "target": "",  # contact_object일 때 접촉 대상(오브젝트/NPC name)
        "trigger": "contact_player",
        "cond_mainprogress": "",
        "cond_min_laugh_point": "",
        "cond_opt": "",
        "rect": None,  # [x,y,w,h]
    }
    active_zone_field = None
    is_selecting_zone_rect = False
    zone_drag_start = None
    zone_drag_end = None
    reopen_zone_config_after_area = False

    # --- MAP: 배경 박스(bg_zones) 추가 모달 ---
    # 목적: "원경/배경" 오브젝트를 범위로 묶어 draw/update/sort 정책을 단순하게 지정
    show_bgzone_config = False
    bgzone_edit_idx = None
    bgzone_fields = {
        "name": "",
        "rect": None,  # [x,y,w,h]
        "layer": "-50",  # 기본은 항상 뒤(배경)로 깔리게
        "draw_only_when_tilt": "true",  # 틸트 ON일 때만 그리기(기본)
        "update_policy": "none",  # none | lowrate | normal
        "sort_policy": "none",    # none | cached
        "cull_margin_px": "160",  # 화면 밖 컬링 여유(대충 원경은 넉넉히)
    }
    active_bgzone_field = None
    is_selecting_bgzone_rect = False
    bgzone_drag_start = None
    bgzone_drag_end = None
    reopen_bgzone_config_after_area = False

    # --- MAP: 체류 박스(presence_zones) — 플레이어 체류 시 상태 오버레이 ---
    is_selecting_presence_rect = False
    presence_drag_start = None
    presence_drag_end = None
    reopen_presence_config_after_area = False

    def _on_char_def_saved(char_name):
        nonlocal categories, cat_list
        _flow_refresh_entity_list()
        categories = {}
        for name, info in OBJ_ASSETS.items():
            cat_name = info.get("category", "ETC (기타)")
            if cat_name not in categories:
                categories[cat_name] = []
            categories[cat_name].append(name)
        categories["CHAR (NPC)"] = list(CHAR_ASSETS.keys())
        cat_list = sorted(list(categories.keys()))
        for n in npcs:
            if getattr(n, "name", None) == char_name:
                from char_behavior import attach_npc_from_entry, npc_entry_from_instance
                attach_npc_from_entry(n, npc_entry_from_instance(n))

    def _on_obj_def_saved(obj_name):
        from data import OBJ_ASSETS
        from flow import merge_interact_spec

        for o in objs:
            if getattr(o, "name", None) == obj_name:
                inst = getattr(o, "interact_instance", None) or {}
                o.interact_spec = merge_interact_spec(
                    OBJ_ASSETS.get(obj_name, {}),
                    {"interact": inst} if inst else {},
                )
        _flow_refresh_entity_list()

    def _on_inst_saved_flow():
        flow.save_editor_data(map_id, objs, npcs)
        _flow_refresh_entity_list()

    def _editor_char_modal_ctx():
        ent_names = set()
        for n in npcs:
            ent_names.add(n.name)
        for o in objs:
            ent_names.add(o.name)
        return {
            "screen_w": SCREEN_W,
            "screen_h": SCREEN_H,
            "mouse": (mx, my),
            "modal_body_drag": modal_body_drag,
            "modal_dropdown_drag": modal_dropdown_drag,
            "on_char_def_saved": _on_char_def_saved,
            "on_obj_def_saved": _on_obj_def_saved,
            "on_inst_saved": _on_inst_saved_flow,
            "event_ids": _editor_collect_event_id_options(all_events, map_id),
            "map_id": map_id,
            "map_entity_names": sorted(ent_names),
            "on_presence_area_pick": _on_presence_area_pick,
            "on_presence_zone_saved": _on_presence_zone_saved,
        }

    def _on_presence_area_pick():
        nonlocal is_selecting_presence_rect, presence_drag_start, presence_drag_end, reopen_presence_config_after_area
        is_selecting_presence_rect = True
        presence_drag_start = None
        presence_drag_end = None
        reopen_presence_config_after_area = True
        presence_zone_modal.show = False

    def _on_presence_zone_saved(zone_dict, edit_idx):
        zones = flow.world_data.setdefault(map_id, {}).setdefault("presence_zones", [])
        if edit_idx is not None and 0 <= int(edit_idx) < len(zones):
            zones[int(edit_idx)] = zone_dict
        else:
            zones.append(zone_dict)
        flow.save_editor_data(map_id, objs, npcs)
        _flow_refresh_entity_list()

    # --- STEP 설정(추가/삽입/수정) 모달 ---
    show_step_config = False
    step_edit_index = None         # 수정이면 int, 추가/삽입이면 None
    step_insert_index = None       # 삽입 위치 (None이면 append)
    step_fields = {}
    active_step_field = None
    step_type_cycle = [
        "MOVE",
        "PLACE",
        "TUNE",
        "MAP",
        "SAY",
        "EMOTE",
        "ACTION_ANIM",
        "WAIT",
        "INTERVAL",
        "ZOOM",
        "FADEIN",
        "FADEOUT",
        "EFFECT",
        "ANIM_ONCE",
        "CARRY",
        "CHANGE",
        "SCREEN",
        "MUSIC_PLAY",
        "MUSIC_STOP",
        "MUSIC_END",
        "MUSIC_PAUSE",
        "MUSIC_RESUME",
        "PLAYER_VISIBLE",
        "CURSOR_VISIBLE",
        "FOLLOW_START",
        "FOLLOW_STOP",
        "CONDITION",
        "CONDITION_SKIP",
        "LOOP_START",
        "LOOP_END",
        "TILT",
        "SHEAR",
        "FX",
        "OVERLAY_UI",
        # 이벤트 중도 스탑 입력(탈출) 구간 제어
        "EVT_STOP_BEGIN",
        "EVT_STOP_END",
        "CALL_EVENT",
        "DEV_CMD",
        "CAMERA",
    ]
    escape_mode_cycle = ["none", "click", "key", "condition"]
    escape_action_cycle = ["end", "break_loop"]
    step_type_dropdown_open = False
    step_target_dropdown_open = False
    step_target_scroll = 0
    step_type_scroll = 0
    step_target_field_key = "target"  # 드롭다운 선택이 반영될 step_fields 키
    dd_drag_kind = None  # "type" | "target" | "step_body" | None
    dd_drag_start_y = 0
    dd_drag_start_scroll = 0
    step_type_dd_ui = None
    step_target_dd_ui = None
    step_body_scroll = 0
    step_body_sb_ui = None
    step_target_options = []
    step_target_dropdown_rect = None
    show_step_delete_confirm = False
    is_picking_step_pos = False
    picking_step_xy_keys = ("pos_x", "pos_y")
    is_picking_step_waypoints = False
    reopen_step_config_after_pick = False
    is_picking_step_target = False
    picking_step_target_field_key = "target"
    reopen_step_config_after_target_pick = False

    event_modal_scroll = 0
    event_modal_dd_open = False
    event_modal_dd_key = None
    event_modal_dd_scroll = 0
    event_modal_dd_rect = None
    event_modal_dd_options = []
    event_modal_dd_ui = None
    modal_body_drag = None  # "event" | "zone" | "bgzone"
    modal_dropdown_drag = None  # "event_dd" | "zone_dd" | "bgzone_dd"

    zone_modal_scroll = 0
    zone_modal_dd_open = False
    zone_modal_dd_key = None
    zone_modal_dd_scroll = 0
    zone_modal_dd_rect = None
    zone_modal_dd_options = []
    zone_modal_dd_ui = None
    is_picking_zone_target = False
    reopen_zone_config_after_target_pick = False

    bgzone_modal_scroll = 0
    bgzone_modal_dd_open = False
    bgzone_modal_dd_key = None
    bgzone_modal_dd_scroll = 0
    bgzone_modal_dd_rect = None
    bgzone_modal_dd_options = []
    bgzone_modal_dd_ui = None

    is_editing_event = False 
    event_input_text = ""

    # [EVENT_DATA_TEMP] 나중에 events.json으로 분리될 임시 데이터 구조
    # 맵 귀속 이벤트(Local)와 글로벌 이벤트를 나눌 준비
    event_list = {
        "LOCAL": ["talk_npc_1", "touch_sign"],
        "GLOBAL": ["prologue", "dream_scene_1"]
    }
    
    try:
        font = pygame.font.SysFont("malgungothic", 14)
        title_font = pygame.font.SysFont("malgungothic", 16, bold=True)
    except:
        font = pygame.font.SysFont("arial", 14)
        title_font = pygame.font.SysFont("arial", 16, bold=True)

    flow = GameFlow()
    all_events = flow.load_events()
    events_catalog = merge_event_catalog(all_events)

    def _flow_rebuild_graph():
        nonlocal flow_graph
        if flow_selected_entity_idx < 0 or not flow_entity_entries:
            flow_graph = None
            return
        ent = flow_entity_entries[flow_selected_entity_idx]
        try:
            flow_graph = _flow_diagram_for_entry(ent)
        except Exception as ex:
            print(f"[FLOW] graph build failed for {ent.get('name')}: {ex}")
            flow_graph = {
                "mode": ent.get("kind", "entity"),
                "entity_name": ent.get("name", ""),
                "entity_kind": ent.get("kind", "obj"),
                "zone_name": ent.get("name", ""),
                "var": ent.get("name", ""),
                "note": str(ex),
                "nodes": [],
                "edges": [],
            }

    def _open_zone_config_at(zone_index):
        nonlocal zone_edit_idx, show_zone_config, zone_modal_scroll, zone_modal_dd_open
        nonlocal active_zone_field, zone_fields, selected_zone_idx, is_zone_dragging
        nonlocal flow_opened_settings
        zones = flow.world_data.get(map_id, {}).get("event_zones", [])
        zi = int(zone_index)
        if 0 <= zi < len(zones):
            zone_edit_idx = zi
            zone_fields = _editor_zone_fields_from_zone_dict(zones[zi])
            show_zone_config = True
            zone_modal_scroll = 0
            zone_modal_dd_open = False
            active_zone_field = None
            selected_zone_idx = zi
            is_zone_dragging = False
            flow_opened_settings = True

    def _flow_refresh_entity_list():
        nonlocal flow_entity_entries, flow_selected_entity_idx
        prev_name = prev_kind = None
        prev_zone_index = None
        if 0 <= flow_selected_entity_idx < len(flow_entity_entries):
            prev = flow_entity_entries[flow_selected_entity_idx]
            prev_name = prev.get("name")
            prev_kind = prev.get("kind")
            if prev_kind == "zone":
                prev_zone_index = prev.get("zone_index")
        flow_entity_entries = []
        for row in _editor_flow_catalog_rows(flow.world_data, map_id):
            rk = row.get("kind")
            if rk == "zone":
                ent = _flow_zone_entry(row["zone_data"], row["zone_index"], map_id)
            elif rk in ("npc", "obj"):
                ent = _flow_entity_catalog_entry(
                    row["name"],
                    rk,
                    char_assets=CHAR_ASSETS,
                    obj_assets=OBJ_ASSETS,
                )
            else:
                continue
            ent["list_label"] = row.get("label") or ent.get("label")
            flow_entity_entries.append(ent)
        flow_selected_entity_idx = -1
        if prev_kind:
            for i, ent in enumerate(flow_entity_entries):
                if prev_kind == "zone":
                    if (
                        ent.get("kind") == "zone"
                        and ent.get("zone_index") == prev_zone_index
                        and ent.get("name") == prev_name
                    ):
                        flow_selected_entity_idx = i
                        break
                elif ent.get("name") == prev_name and ent.get("kind") == prev_kind:
                    flow_selected_entity_idx = i
                    break
        if flow_selected_entity_idx < 0 and flow_entity_entries:
            flow_selected_entity_idx = 0
        _flow_recount_all_entity_nodes()
        _flow_rebuild_graph()

    map_list = list(flow.world_data.keys())
    cur_idx = 0
    # 초기 맵 로드
    map_id, bg, mask, player, objs, npcs = flow.load_map(save_data={"current_map": map_list[cur_idx]})
    _flow_refresh_entity_list()

    sidebar_w = EDITOR_SIDEBAR_W
    right_sidebar_w = EDITOR_SIDEBAR_W
    left_placed_collapsed = _editor_collapsed_set_from_state(
        editor_ui_state, EDITOR_UI_COLLAPSE_MAP_LEFT
    )
    right_asset_collapsed = _editor_collapsed_set_from_state(
        editor_ui_state, EDITOR_UI_COLLAPSE_MAP_RIGHT
    )
    map_area_w = SCREEN_W - sidebar_w - right_sidebar_w
    TOP_BAR_H = EDITOR_TOP_BAR_H
    map_view_h = _editor_map_view_h(SCREEN_H, TOP_BAR_H)

    zoom_steps = [0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
    # 에디터 시작 시: 맵이 작업창에 "가득" 차도록 자동 줌(가로/세로 중 더 작은 비율)
    bg_w, bg_h = bg.get_width(), bg.get_height()
    view_h = max(1, map_view_h)
    fit_zoom = min(map_area_w / max(1, bg_w), view_h / max(1, bg_h))
    fit_zoom = max(min(fit_zoom, max(zoom_steps)), min(zoom_steps))
    zoom_idx = min(range(len(zoom_steps)), key=lambda i: abs(zoom_steps[i] - fit_zoom))
    zoom_level = zoom_steps[zoom_idx]

    cam_x = bg_w / 2
    cam_y = bg_h / 2

    # 키 입력 디버그: 터미널 대신 화면/파일 로그로 확인
    debug_last_key = ""
    debug_last_key_t = 0
    prev_export_hotkey_down = False
    last_export_msg = ""
    last_export_msg_t = 0

    # 카테고리 분류
    categories = {}

    # 1. OBJ_ASSETS를 돌며 category 값에 따라 그룹 묶기
    for name, info in OBJ_ASSETS.items():
        # category가 없으면 "ETC (기타)"로 분류
        cat_name = info.get("category", "ETC (기타)")
        
        if cat_name not in categories:
            categories[cat_name] = []
        categories[cat_name].append(name)

    # 2. NPC는 따로 "CHAR (NPC)" 카테고리에 추가
    categories["CHAR (NPC)"] = list(CHAR_ASSETS.keys())

    # 3. 화면 표시를 위해 카테고리 이름 목록(리스트) 만들기
    cat_list = sorted(list(categories.keys()))
    cat_idx = 0  # 현재 선택된 카테고리 번호

    
    selected_asset, selected_node, is_panning = None, None, False
    selected_nodes = []  # 다중 선택(동일 인스턴스는 objs/npcs 안에서만)
    show_multi_delete_confirm = False
    box_select_start = None  # (wx, wy) 월드
    box_select_current = None
    multi_drag_leader = None
    multi_drag_anchor = None
    multi_drag_origins = None  # id(o) -> [x, y] 드래그 시작 시점
    obj_sprite_tilt_active = False
    obj_sprite_tilt_buf = ""
    obj_height_active = False
    obj_height_buf = ""
    obj_layer_active = False
    obj_layer_buf = ""
    last_m = (0,0)
    GRID_SIZE = 16
    EVENT_ADD_Y = TOP_BAR_H + 34
    EVENT_ADD_H = 30
    # ADD 버튼 아래 여백 후 LOCAL / GLOBAL 스크롤 목록 시작 (버튼과 겹치지 않음)
    EVENT_LIST_START_Y = EVENT_ADD_Y + EVENT_ADD_H + 12
    # zoom_level = 1.0
    # 좌·우 사이드바 리스트: 마우스 오버 시 전체 문자열 툴팁 (모달 열리면 비활성)
    sidebar_list_tooltip = None

    # --- MAP 서브툴: OBJECTS / ZONES ---
    map_tool = "OBJECTS"  # "OBJECTS" | "ZONES" | "BGZONES" | "PRESENCE"
    selected_zone_idx = None
    is_zone_dragging = False
    zone_drag_offset = (0, 0)  # (mouse_x - rect_x, mouse_y - rect_y) in world coords

    selected_bgzone_idx = None
    is_bgzone_dragging = False
    bgzone_drag_offset = (0, 0)

    selected_presence_idx = None
    is_presence_dragging = False
    presence_drag_offset = (0, 0)


















    last_map_export_ts = 0

    def trigger_map_png_export():
        """F7 / Ctrl+Shift+E / 상단 PNG 버튼 — 현재 로드 맵을 exports/ 에 저장."""
        nonlocal last_map_export_ts, last_export_msg, last_export_msg_t
        now = pygame.time.get_ticks()
        if now - last_map_export_ts < 220:
            return
        last_map_export_ts = now
        ts0 = now
        bg_export = bg
        try:
            m = flow.world_data.get(map_id, {}) or {}
            img_name = m.get("bg_img")
            if img_name:
                bp = os.path.join("assets", "images", "bg", str(img_name))
                if os.path.isfile(bp):
                    bg_export = pygame.image.load(bp).convert()
        except Exception as ex:
            print(f">>> [EXPORT] bg reload warn: {ex}")
        out = _export_map_png(map_id, bg_export, objs, npcs, export_dir="exports")
        if out:
            print(f">>> [EXPORT] map png saved: {out}")
            _append_export_log(f"[{ts0}] EXPORT OK: {out}")
            last_export_msg = f"EXPORT OK: {out}"
        else:
            print(">>> [EXPORT] failed — exports/export_log.txt 확인")
            _append_export_log(f"[{ts0}] EXPORT FAIL map={map_id}")
            last_export_msg = "EXPORT FAIL (콘솔·export_log 확인)"
        last_export_msg_t = ts0

    running = True
    while running:
        mx, my = pygame.mouse.get_pos()
        right_panel_w = 0 if edit_mode == "FLOW" else right_sidebar_w
        map_area_w = SCREEN_W - sidebar_w - right_panel_w
        sidebar_list_tooltip = None
        export_map_btn = pygame.Rect(int(sidebar_w + map_area_w - 80), 10, 72, 38)
        pygame.event.pump()
        _editor_sync_text_input(
            _editor_wants_text_input(
                show_event_config=show_event_config,
                active_field=active_field,
                show_zone_config=show_zone_config,
                active_zone_field=active_zone_field,
                show_bgzone_config=show_bgzone_config,
                active_bgzone_field=active_bgzone_field,
                show_step_config=show_step_config,
                active_step_field=active_step_field,
                obj_height_active=obj_height_active,
                obj_sprite_tilt_active=obj_sprite_tilt_active,
                obj_layer_active=obj_layer_active,
            )
        )
        # 정수 배율(2x 등)에 가까우면 스냅: 배경·오브젝트 int(w*z)가 동일 배율이 되도록 (런타임 Camera와 동일)
        zoom_level = snap_render_zoom(float(zoom_level))
        map_view_h = _editor_map_view_h(SCREEN_H, TOP_BAR_H)
        sidebar_list_bottom = _editor_sidebar_list_bottom(SCREEN_H)
        left_list_tops = _editor_left_list_tops(TOP_BAR_H)

        # [수정] 버튼 좌표를 루프 상단에서 미리 정의 (판정과 그리기 모두 사용)
        panel_rect = pygame.Rect(SCREEN_W//2 - 280, SCREEN_H//2 - 300, 560, 600)
        save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
        canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)











        # --- 헬퍼 함수: 실제 맵 좌표를 화면상의 줌 좌표로 변환 ---
        def get_zoomed_pos(rx, ry):
            # cam_x, cam_y가 화면의 '작업 영역' 정중앙에 오도록 계산
            zx = (rx - cam_x) * zoom_level + (map_area_w / 2)
            zy = (ry - cam_y) * zoom_level + (map_view_h / 2)
            return zx, zy

        # 맵 서피스 중심 오프셋(배경 정수 원점 계산에 사용). get_real_pos는 매 호출 시 현재 zoom_level로 bg를 다시 구함(휠 줌 동일 프레임 안전).
        _map_ox = float(map_area_w) / 2.0
        _map_oy = float(map_view_h) / 2.0

        # --- 헬퍼 함수: 화면 좌표(마우스) → 월드 (배경 scaled_w/h 와 동일 비율 역변환, 픽셀 일치) ---
        def get_real_pos(mx, my):
            bx, by = bg_anchor(float(cam_x), float(cam_y), float(zoom_level), _map_ox, _map_oy)
            mx_local = float(mx - sidebar_w)
            my_local = float(my - TOP_BAR_H)
            zl = float(zoom_level)
            sw = max(1, int(bg_w * zl))
            sh = max(1, int(bg_h * zl))
            return map_surface_to_world_xy(mx_local, my_local, bx, by, bg_w, bg_h, sw, sh)
        

        # 실제 맵 좌표 계산 (줌 반영)
        wx, wy = get_real_pos(mx, my)        











        # [수정] 쉬프트 키를 누르고 있으면 자석(Grid Snap) 해제
        keys = pygame.key.get_pressed()
        is_shift_pressed = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]

        # [F7] 맵 PNG 내보내기(복원): KEYDOWN이 안 들어오는 환경 대비 폴링(에지 감지). SDL2는 KSCAN_F7 권장.
        export_hot_down = _editor_export_hotkey_down(keys)
        if export_hot_down and not prev_export_hotkey_down:
            trigger_map_png_export()
        prev_export_hotkey_down = export_hot_down

        if is_shift_pressed:
            swx, swy = wx, wy
        else:
            # 격자 선은 월드 0, GRID_SIZE, 2*GRID_SIZE... 에 그려짐. 스냅도 같은 격점에 맞춤
            # (이전: X는 셀 중앙 +8, Y는 +16 등으로 선과 어긋나 0.5px처럼 보이는 불일치 발생)
            swx = float((int(wx) // GRID_SIZE) * GRID_SIZE)
            swy = float((int(wy) // GRID_SIZE) * GRID_SIZE)














        for event in pygame.event.get():

            if event.type == pygame.QUIT:
                editor_ui_state[EDITOR_UI_COLLAPSE_MAP_LEFT] = sorted(left_placed_collapsed)
                editor_ui_state[EDITOR_UI_COLLAPSE_FLOW_LEFT] = sorted(flow_placed_collapsed)
                editor_ui_state[EDITOR_UI_COLLAPSE_MAP_RIGHT] = sorted(right_asset_collapsed)
                _save_editor_ui_state(editor_ui_state)
                running = False

            # [F7] 맵 PNG 내보내기: KEYDOWN 경로(폴링이 안 되는 환경 대비)
            if _editor_event_triggers_map_export(event):
                debug_last_key = "EXPORT"
                debug_last_key_t = pygame.time.get_ticks()
                trigger_map_png_export()
                continue
            elif event.type == pygame.KEYDOWN:
                # 다른 키도 들어오는지 화면에서 확인
                try:
                    debug_last_key = pygame.key.name(event.key)
                except Exception:
                    debug_last_key = str(getattr(event, "key", ""))
                debug_last_key_t = pygame.time.get_ticks()

            # --- MAP: event zone 영역 드래그 지정 ---
            if is_selecting_zone_rect:
                # 맵 작업 영역에서만 드래그 받음
                in_map_area = (sidebar_w < mx < SCREEN_W - right_panel_w) and (my > TOP_BAR_H)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and in_map_area:
                    _zwx, _zwy = get_real_pos(mx, my)
                    _zsx, _zsy = editor_snap_pick_world_xy(_zwx, _zwy, GRID_SIZE, is_shift_pressed)
                    zone_drag_start = (_zsx, _zsy)
                    zone_drag_end = zone_drag_start
                elif event.type == pygame.MOUSEMOTION and zone_drag_start:
                    _zwx, _zwy = get_real_pos(mx, my)
                    _zsx, _zsy = editor_snap_pick_world_xy(_zwx, _zwy, GRID_SIZE, is_shift_pressed)
                    zone_drag_end = (_zsx, _zsy)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and zone_drag_start and zone_drag_end:
                    x1, y1 = zone_drag_start
                    x2, y2 = zone_drag_end
                    zx = int(min(x1, x2))
                    zy = int(min(y1, y2))
                    zw = int(abs(x2 - x1))
                    zh = int(abs(y2 - y1))
                    zone_fields["rect"] = [zx, zy, zw, zh]
                    is_selecting_zone_rect = False
                    zone_drag_start = None
                    zone_drag_end = None
                    if reopen_zone_config_after_area:
                        show_zone_config = True
                        reopen_zone_config_after_area = False
                # 영역 지정 모드에서는 다른 입력 처리 방지
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                    continue

            # --- MAP: bg zone 영역 드래그 지정 ---
            if is_selecting_bgzone_rect:
                in_map_area = (sidebar_w < mx < SCREEN_W - right_panel_w) and (my > TOP_BAR_H)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and in_map_area:
                    _bwx, _bwy = get_real_pos(mx, my)
                    _bsx, _bsy = editor_snap_pick_world_xy(_bwx, _bwy, GRID_SIZE, is_shift_pressed)
                    bgzone_drag_start = (_bsx, _bsy)
                    bgzone_drag_end = bgzone_drag_start
                elif event.type == pygame.MOUSEMOTION and bgzone_drag_start:
                    _bwx, _bwy = get_real_pos(mx, my)
                    _bsx, _bsy = editor_snap_pick_world_xy(_bwx, _bwy, GRID_SIZE, is_shift_pressed)
                    bgzone_drag_end = (_bsx, _bsy)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and bgzone_drag_start and bgzone_drag_end:
                    x1, y1 = bgzone_drag_start
                    x2, y2 = bgzone_drag_end
                    zx = int(min(x1, x2))
                    zy = int(min(y1, y2))
                    zw = int(abs(x2 - x1))
                    zh = int(abs(y2 - y1))
                    bgzone_fields["rect"] = [zx, zy, zw, zh]
                    is_selecting_bgzone_rect = False
                    bgzone_drag_start = None
                    bgzone_drag_end = None
                    if reopen_bgzone_config_after_area:
                        show_bgzone_config = True
                        reopen_bgzone_config_after_area = False
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                    continue

            # --- MAP: presence zone 영역 드래그 지정 ---
            if is_selecting_presence_rect:
                in_map_area = (sidebar_w < mx < SCREEN_W - right_panel_w) and (my > TOP_BAR_H)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and in_map_area:
                    _pwx, _pwy = get_real_pos(mx, my)
                    _psx, _psy = editor_snap_pick_world_xy(_pwx, _pwy, GRID_SIZE, is_shift_pressed)
                    presence_drag_start = (_psx, _psy)
                    presence_drag_end = presence_drag_start
                elif event.type == pygame.MOUSEMOTION and presence_drag_start:
                    _pwx, _pwy = get_real_pos(mx, my)
                    _psx, _psy = editor_snap_pick_world_xy(_pwx, _pwy, GRID_SIZE, is_shift_pressed)
                    presence_drag_end = (_psx, _psy)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and presence_drag_start and presence_drag_end:
                    x1, y1 = presence_drag_start
                    x2, y2 = presence_drag_end
                    zx = int(min(x1, x2))
                    zy = int(min(y1, y2))
                    zw = int(abs(x2 - x1))
                    zh = int(abs(y2 - y1))
                    presence_zone_modal.set_rect([zx, zy, zw, zh])
                    is_selecting_presence_rect = False
                    presence_drag_start = None
                    presence_drag_end = None
                    if reopen_presence_config_after_area:
                        presence_zone_modal.show = True
                        reopen_presence_config_after_area = False
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                    continue

            # --- EVENT: step pos 찍기 모드 (작업창 클릭으로 좌표 설정) ---
            if is_picking_step_target:
                # ESC로 픽 모드 취소하고 편집창 복귀
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    is_picking_step_target = False
                    if reopen_step_config_after_target_pick:
                        show_step_config = True
                        step_body_scroll = 0
                        reopen_step_config_after_target_pick = False
                    continue

                in_map_area = (sidebar_w < mx < SCREEN_W - right_panel_w) and (my > TOP_BAR_H)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and in_map_area:
                    hit = _editor_pick_top_node(objs, npcs, wx, wy)
                    if hit is not None:
                        fk_tp = str(picking_step_target_field_key or "target")
                        step_fields[fk_tp] = str(getattr(hit, "name", "") or "")
                    is_picking_step_target = False
                    if reopen_step_config_after_target_pick:
                        show_step_config = True
                        step_body_scroll = 0
                        reopen_step_config_after_target_pick = False
                    continue
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION) and in_map_area:
                    continue

            if is_picking_zone_target:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    is_picking_zone_target = False
                    if reopen_zone_config_after_target_pick:
                        show_zone_config = True
                        zone_modal_scroll = 0
                        reopen_zone_config_after_target_pick = False
                    continue

                in_map_area = (sidebar_w < mx < SCREEN_W - right_panel_w) and (my > TOP_BAR_H)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and in_map_area:
                    hit = _editor_pick_top_node(objs, npcs, wx, wy)
                    if hit is not None:
                        zone_fields["target"] = str(getattr(hit, "name", "") or "")
                    is_picking_zone_target = False
                    if reopen_zone_config_after_target_pick:
                        show_zone_config = True
                        zone_modal_scroll = 0
                        reopen_zone_config_after_target_pick = False
                    continue
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION) and in_map_area:
                    continue

            if is_picking_step_waypoints:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    is_picking_step_waypoints = False
                    if reopen_step_config_after_pick:
                        show_step_config = True
                        step_body_scroll = 0
                        reopen_step_config_after_pick = False
                    continue

                in_map_area = (sidebar_w < mx < SCREEN_W - right_panel_w) and (my > TOP_BAR_H)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and in_map_area:
                    _apx, _apy = editor_snap_pick_world_xy(wx, wy, GRID_SIZE, is_shift_pressed)
                    seg = f"{_apx},{_apy}"
                    cur = (step_fields.get("waypoints") or "").strip()
                    step_fields["waypoints"] = (cur + ";" + seg) if cur else seg
                    continue
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION) and in_map_area:
                    continue

            if is_picking_step_pos:
                # ESC로 픽 모드 취소하고 편집창 복귀
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    is_picking_step_pos = False
                    if reopen_step_config_after_pick:
                        show_step_config = True
                        step_body_scroll = 0
                        reopen_step_config_after_pick = False
                    continue

                in_map_area = (sidebar_w < mx < SCREEN_W - right_panel_w) and (my > TOP_BAR_H)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and in_map_area:
                    # 현재 마우스가 가리키는 월드 좌표를 step_fields에 반영 (격자 스냅, Shift=미세)
                    kx, ky = picking_step_xy_keys if picking_step_xy_keys else ("pos_x", "pos_y")
                    _px, _py = editor_snap_pick_world_xy(wx, wy, GRID_SIZE, is_shift_pressed)
                    step_fields[str(kx)] = str(_px)
                    step_fields[str(ky)] = str(_py)
                    is_picking_step_pos = False
                    if reopen_step_config_after_pick:
                        show_step_config = True
                        step_body_scroll = 0
                        reopen_step_config_after_pick = False
                    continue
                # 픽 모드에서는 '작업창 영역' 안의 마우스 입력만 막고,
                # 상단 맵 바/좌우 사이드바 클릭(맵 전환 등)은 허용
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION) and in_map_area:
                    continue

            if show_multi_delete_confirm:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    show_multi_delete_confirm = False
                    continue
                if event.type == pygame.MOUSEBUTTONDOWN:
                    ex, ey = event.pos
                    cw, ch = 440, 168
                    confirm_rect = pygame.Rect(SCREEN_W // 2 - cw // 2, SCREEN_H // 2 - ch // 2, cw, ch)
                    yes_btn = pygame.Rect(confirm_rect.x + 28, confirm_rect.bottom - 48, 160, 36)
                    no_btn = pygame.Rect(confirm_rect.right - 188, confirm_rect.bottom - 48, 160, 36)
                    if yes_btn.collidepoint(ex, ey):
                        for n in list(selected_nodes):
                            if n in objs:
                                objs.remove(n)
                            elif n in npcs:
                                npcs.remove(n)
                        obj_sprite_tilt_active = False
                        obj_height_active = False
                        obj_layer_active = False
                        selected_nodes.clear()
                        selected_node = None
                        show_multi_delete_confirm = False
                    elif no_btn.collidepoint(ex, ey) or not confirm_rect.collidepoint(ex, ey):
                        show_multi_delete_confirm = False
                    continue
                continue

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                _tilt_r = None
                _height_r = None
                _ysort_r = None
                _layer_r = None
                if edit_mode == "MAP" and map_tool == "OBJECTS" and len(selected_nodes) == 1:
                    _ins = _editor_map_obj_inspector_layout(SCREEN_W, SCREEN_H, sidebar_w)
                    _height_r = _ins["height_rect"]
                    _tilt_r = _ins["tilt_rect"]
                    _ysort_r = _ins.get("ysort_rect")
                    _layer_r = _ins.get("layer_rect")
                if _height_r and _height_r.collidepoint(event.pos):
                    obj_height_active = True
                    obj_sprite_tilt_active = False
                    obj_layer_active = False
                    obj_height_buf = str(int(round(float(getattr(selected_nodes[0], "height", 0) or 0))))
                    continue
                if _tilt_r and _tilt_r.collidepoint(event.pos):
                    obj_sprite_tilt_active = True
                    obj_height_active = False
                    obj_layer_active = False
                    obj_sprite_tilt_buf = str(getattr(selected_nodes[0], "sprite_tilt", 1.0))
                    continue
                if _ysort_r and _ysort_r.collidepoint(event.pos):
                    # y-sorting 기준 토글: ground <-> visual
                    if selected_nodes:
                        o = selected_nodes[0]
                        cur = str(getattr(o, "ysort_mode", "ground") or "ground").strip().lower()
                        nxt = "visual" if cur != "visual" else "ground"
                        setattr(o, "ysort_mode", nxt)
                    obj_sprite_tilt_active = False
                    obj_height_active = False
                    obj_layer_active = False
                    continue
                if _layer_r and _layer_r.collidepoint(event.pos):
                    obj_layer_active = True
                    obj_sprite_tilt_active = False
                    obj_height_active = False
                    obj_layer_buf = str(int(getattr(selected_nodes[0], "layer", 0) or 0))
                    continue
                if edit_mode == "MAP" and map_tool == "OBJECTS" and len(selected_nodes) == 1:
                    _ins_npc = _editor_map_obj_inspector_layout(SCREEN_W, SCREEN_H, sidebar_w)
                    n0sel = selected_nodes[0]
                    if n0sel in npcs:
                        btn_type = pygame.Rect(_ins_npc["bar"].right - 210, _ins_npc["bar"].y + 6, 96, 22)
                        btn_inst = pygame.Rect(_ins_npc["bar"].right - 108, _ins_npc["bar"].y + 6, 96, 22)
                        if btn_type.collidepoint(event.pos):
                            char_def_modal.open(n0sel.name)
                            continue
                        if btn_inst.collidepoint(event.pos):
                            char_inst_modal.open(n0sel)
                            continue
                    elif n0sel in objs:
                        btn_ot = pygame.Rect(_ins_npc["bar"].right - 210, _ins_npc["bar"].y + 6, 96, 22)
                        btn_oi = pygame.Rect(_ins_npc["bar"].right - 108, _ins_npc["bar"].y + 6, 96, 22)
                        if btn_ot.collidepoint(event.pos):
                            obj_def_modal.open(n0sel.name)
                            continue
                        if btn_oi.collidepoint(event.pos):
                            obj_inst_modal.open(n0sel)
                            continue
                if edit_mode == "EVENT" and event_preview_sel:
                    _ins_ev = _editor_map_obj_inspector_layout(SCREEN_W, SCREEN_H, sidebar_w)
                    btn_type = pygame.Rect(_ins_ev["bar"].right - 210, _ins_ev["bar"].y + 6, 96, 22)
                    btn_inst = pygame.Rect(_ins_ev["bar"].right - 108, _ins_ev["bar"].y + 6, 96, 22)
                    if btn_type.collidepoint(event.pos):
                        _editor_open_interact_type_modal(event_preview_sel)
                        continue
                    ent_on_map, ent_kind = _editor_find_map_entity_by_name(
                        event_preview_sel, objs, npcs
                    )
                    if ent_on_map and btn_inst.collidepoint(event.pos):
                        if ent_kind == "npc":
                            char_inst_modal.open(ent_on_map)
                        else:
                            obj_inst_modal.open(ent_on_map)
                        continue
                if obj_sprite_tilt_active or obj_height_active or obj_layer_active:
                    obj_sprite_tilt_active = False
                    obj_height_active = False
                    obj_layer_active = False

            if event.type == pygame.TEXTINPUT:
                if obj_height_active:
                    obj_height_buf = (obj_height_buf or "") + (event.text or "")
                    continue
                if obj_sprite_tilt_active:
                    obj_sprite_tilt_buf = (obj_sprite_tilt_buf or "") + (event.text or "")
                    continue
                if obj_layer_active:
                    obj_layer_buf = (obj_layer_buf or "") + (event.text or "")
                    continue
                if show_step_config and active_step_field:
                    step_fields[active_step_field] = (step_fields.get(active_step_field, "") or "") + (
                        event.text or ""
                    )
                    continue
                if show_zone_config and active_zone_field:
                    zone_fields[active_zone_field] = (zone_fields.get(active_zone_field, "") or "") + (
                        event.text or ""
                    )
                    continue
                if show_bgzone_config and active_bgzone_field:
                    bgzone_fields[active_bgzone_field] = (bgzone_fields.get(active_bgzone_field, "") or "") + (
                        event.text or ""
                    )
                    continue
                if presence_zone_modal.show and presence_zone_modal.active_field:
                    presence_zone_modal.fields[presence_zone_modal.active_field] = (
                        presence_zone_modal.fields.get(presence_zone_modal.active_field, "") or ""
                    ) + (event.text or "")
                    continue
                if show_event_config and active_field:
                    input_fields[active_field] = (input_fields.get(active_field, "") or "") + (
                        event.text or ""
                    )
                    continue

            if event.type == pygame.KEYDOWN and (obj_sprite_tilt_active or obj_height_active or obj_layer_active):
                if event.key == pygame.K_BACKSPACE:
                    if obj_height_active:
                        obj_height_buf = (obj_height_buf or "")[:-1]
                    elif obj_sprite_tilt_active:
                        obj_sprite_tilt_buf = (obj_sprite_tilt_buf or "")[:-1]
                    else:
                        obj_layer_buf = (obj_layer_buf or "")[:-1]
                    continue
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if obj_height_active:
                        try:
                            hv = float((obj_height_buf or "").strip() or "0")
                        except ValueError:
                            hv = 0.0
                        hv = max(0.0, min(4000.0, hv))
                        if selected_nodes:
                            selected_nodes[0].height = hv
                        obj_height_active = False
                    elif obj_sprite_tilt_active:
                        try:
                            v = float((obj_sprite_tilt_buf or "").strip() or "1")
                        except ValueError:
                            v = 1.0
                        v = max(0.0, min(1.0, v))
                        if selected_nodes:
                            selected_nodes[0].sprite_tilt = v
                        obj_sprite_tilt_active = False
                    else:
                        try:
                            lv = int(float((obj_layer_buf or "").strip() or "0"))
                        except ValueError:
                            lv = 0
                        lv = max(-999, min(999, lv))
                        if selected_nodes:
                            selected_nodes[0].layer = lv
                        obj_layer_active = False
                    continue

            if show_event_config:
                rows_ev = _event_modal_rows(input_fields.get("cat", "LOCAL"))
                panel_rect, content_h_ev, _bv_ev = _editor_std_modal_rect(SCREEN_W, SCREEN_H, len(rows_ev))
                body_rect_ev, sb_rect_ev, max_ev_scroll, event_modal_scroll = _editor_modal_body_scroll_layout(
                    panel_rect, event_modal_scroll, content_h_ev
                )
                save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
                canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)
                row_h_ev = EDITOR_MODAL_ROW_H
                dd_item_h_ev = 22
                label_x_ev = body_rect_ev.x + 4
                field_x_ev = body_rect_ev.x + EDITOR_MODAL_LABEL_W
                field_w_ev = 220
                list_w_ev = 52

                if event.type == pygame.MOUSEWHEEL:
                    px, py = _editor_pointer_xy(event, mx, my)
                    delta = _editor_wheel_delta(event)
                    if event_modal_dd_open and event_modal_dd_rect:
                        total_h = len(event_modal_dd_options) * dd_item_h_ev
                        vis = max(1, event_modal_dd_rect.height)
                        max_dd = max(0, total_h - vis)
                        if max_dd > 0 and _editor_rects_contain_point(
                            px, py, event_modal_dd_rect, body_rect_ev, panel_rect
                        ):
                            event_modal_dd_scroll = max(0, min(max_dd, event_modal_dd_scroll + delta))
                    elif _editor_rects_contain_point(px, py, body_rect_ev, sb_rect_ev, panel_rect):
                        event_modal_scroll = max(0, min(max_ev_scroll, event_modal_scroll + delta))
                    continue

                if event.type == pygame.MOUSEMOTION and modal_body_drag == "event":
                    ui_sb = _step_overlay_scrollbar_layout(
                        sb_rect_ev, body_rect_ev.height, content_h_ev, event_modal_scroll
                    )
                    sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_sb)
                    if sp is not None:
                        event_modal_scroll = sp
                    continue

                if event.type == pygame.MOUSEMOTION and modal_dropdown_drag == "event_dd":
                    if event_modal_dd_ui:
                        sp = _editor_scroll_px_from_sb_my(event.pos[1], event_modal_dd_ui)
                        if sp is not None:
                            event_modal_dd_scroll = sp
                    continue

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if modal_body_drag == "event":
                        modal_body_drag = None
                    if modal_dropdown_drag == "event_dd":
                        modal_dropdown_drag = None
                    continue

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if event_modal_dd_open and event_modal_dd_rect:
                        dr = event_modal_dd_rect
                        ui_prev = event_modal_dd_ui
                        if dr.collidepoint(event.pos):
                            if ui_prev:
                                dd_hit = _editor_modal_sb_hit(event.pos, ui_prev)
                                if dd_hit == "thumb":
                                    modal_dropdown_drag = "event_dd"
                                    continue
                                if dd_hit == "track":
                                    sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_prev)
                                    if sp is not None:
                                        event_modal_dd_scroll = sp
                                    continue
                            sb_ex = 11 if int((ui_prev or {}).get("max_scroll") or 0) > 0 else 0
                            pick_w = max(1, dr.width - sb_ex)
                            if event.pos[0] < dr.x + pick_w:
                                rel_y = event.pos[1] - dr.y + event_modal_dd_scroll
                                ix = rel_y // dd_item_h_ev
                                if 0 <= ix < len(event_modal_dd_options):
                                    k = event_modal_dd_key
                                    if k:
                                        input_fields[k] = str(event_modal_dd_options[ix])
                                    event_modal_dd_open = False
                                    continue
                            continue
                        event_modal_dd_open = False

                    ui_sb_ev = _step_overlay_scrollbar_layout(
                        sb_rect_ev, body_rect_ev.height, content_h_ev, event_modal_scroll
                    )
                    sb_hit = _editor_modal_sb_hit(event.pos, ui_sb_ev)
                    if sb_hit == "thumb":
                        modal_body_drag = "event"
                        continue
                    if sb_hit == "track":
                        sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_sb_ev)
                        if sp is not None:
                            event_modal_scroll = sp
                        continue

                    active_field = None

                    for i, row in enumerate(rows_ev):
                        rk = row[1]
                        kind = row[2]
                        if kind == "hint":
                            continue
                        ry = body_rect_ev.y + i * row_h_ev - event_modal_scroll
                        if ry + row_h_ev < body_rect_ev.top or ry > body_rect_ev.bottom:
                            continue
                        if kind in ("dropdown", "maps"):
                            opts = row[3] if kind == "dropdown" else ([""] + list(map_list))
                            list_btn = pygame.Rect(field_x_ev + field_w_ev + 4, ry + 3, list_w_ev, row_h_ev - 6)
                            val_rect = pygame.Rect(field_x_ev, ry + 3, field_w_ev, row_h_ev - 6)
                            if list_btn.collidepoint(event.pos):
                                event_modal_dd_key = rk
                                event_modal_dd_options = list(opts)
                                event_modal_dd_scroll = 0
                                n_opt = len(event_modal_dd_options)
                                dd_h = min(220, max(dd_item_h_ev, n_opt * dd_item_h_ev))
                                event_modal_dd_rect = pygame.Rect(field_x_ev, ry + row_h_ev + 2, field_w_ev + list_w_ev + 4, dd_h)
                                event_modal_dd_open = True
                                continue
                            if val_rect.collidepoint(event.pos):
                                active_field = rk
                                continue
                        elif kind == "text":
                            val_rect = pygame.Rect(
                                field_x_ev, ry + 3, body_rect_ev.right - field_x_ev - 8, row_h_ev - 6
                            )
                            if val_rect.collidepoint(event.pos):
                                active_field = rk
                                continue

                    # 하단 버튼
                    if save_btn.collidepoint(event.pos):
                        # --- 데이터 저장 로직 ---
                        cat = input_fields["cat"].upper()
                        if cat not in EDITOR_EVENT_SECTIONS:
                            cat = "LOCAL"
                        eid = input_fields["eid"] or f"ev_new_{pygame.time.get_ticks()}"

                        res_data = {}
                        rp = (input_fields.get("res_prog") or "").strip()
                        if rp:
                            res_data["mainprogress"] = rp
                        if input_fields["res_opt"].strip():
                            opt_json = _parse_editor_json_kv_blob(input_fields["res_opt"])
                            if opt_json is None:
                                print(
                                    "Result Opt JSON 오류 — 예: \"progress_wateringcan\": 1001 "
                                    "(쌍따옴표, 중괄호는 있어도 없어도 됨)"
                                )
                            else:
                                res_data.update(opt_json)

                        old_steps = []
                        if config_target_id:
                            for c in EDITOR_EVENT_SECTIONS:
                                if config_target_id in all_events.get(c, {}):
                                    old_steps = all_events[c][config_target_id].get("steps", [])
                                    del all_events[c][config_target_id]
                                    break

                        entry = {
                            "title": input_fields["title"] or eid,
                            "steps": old_steps,
                        }
                        if cat != "FRAGMENTS":
                            entry["result"] = res_data
                        if cat == "LOCAL":
                            entry["map_id"] = map_id
                        elif cat == "GLOBAL":
                            entry["map_id"] = "__GLOBAL__"
                            wm = (input_fields.get("work_map") or "").strip()
                            if wm and wm in map_list:
                                entry["work_map"] = wm
                            trig = (input_fields.get("trigger") or "auto").strip()
                            if trig:
                                entry["trigger"] = trig
                            cond = (input_fields.get("condition") or "").strip()
                            if cond:
                                entry["condition"] = cond
                            pr = (input_fields.get("priority") or "").strip()
                            if pr:
                                try:
                                    entry["priority"] = int(pr)
                                except ValueError:
                                    pass
                        elif cat == "SYNC":
                            wm = (input_fields.get("work_map") or "").strip()
                            if wm and wm in map_list:
                                entry["work_map"] = wm
                            cond = (input_fields.get("condition") or "").strip()
                            if cond:
                                entry["condition"] = cond
                            pr = (input_fields.get("priority") or "").strip()
                            if pr:
                                try:
                                    entry["priority"] = int(pr)
                                except ValueError:
                                    pass

                        # (정책 변경) entry["escape"]는 더 이상 저장하지 않는다. (스텝에서 제어)
                        entry.pop("escape", None)

                        all_events[cat][eid] = entry
                        show_event_config = False
                        flow.save_events(all_events) # 즉시 파일 저장
                        _flow_refresh_entity_list()

                    elif canc_btn.collidepoint(event.pos):
                        show_event_config = False
                
                # 키보드 입력 로직 (동일)
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if event_modal_dd_open:
                            event_modal_dd_open = False
                        else:
                            show_event_config = False
                    elif active_field:
                        if event.key == pygame.K_BACKSPACE:
                            input_fields[active_field] = input_fields[active_field][:-1]
                        elif event.key == pygame.K_RETURN:
                            active_field = None
                continue # 설정창 열려있으면 맵 클릭 방지

            if char_def_modal.show:
                if char_def_modal.handle_event(event, _editor_char_modal_ctx()):
                    continue
            if char_inst_modal.show:
                if char_inst_modal.handle_event(event, _editor_char_modal_ctx()):
                    continue
            if obj_def_modal.show:
                if obj_def_modal.handle_event(event, _editor_char_modal_ctx()):
                    continue
            if obj_inst_modal.show:
                if obj_inst_modal.handle_event(event, _editor_char_modal_ctx()):
                    continue
            if presence_zone_modal.show:
                if presence_zone_modal.handle_event(event, _editor_char_modal_ctx()):
                    continue

            if show_zone_config:
                rows_zn = _zone_modal_rows()
                panel_rect, content_h_zn, _ = _editor_std_modal_rect(SCREEN_W, SCREEN_H, len(rows_zn))
                body_rect_zn, sb_rect_zn, max_zn_scroll, zone_modal_scroll = _editor_modal_body_scroll_layout(
                    panel_rect, zone_modal_scroll, content_h_zn
                )
                save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
                canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)
                row_h_zn = EDITOR_MODAL_ROW_H
                dd_item_h_zn = 22
                field_x_zn = body_rect_zn.x + EDITOR_MODAL_LABEL_W
                field_w_zn = 220
                list_w_zn = 52
                pick_w_zn = 52
                fld_txt_w_zn = 168
                ev_ids_zn = _editor_collect_event_id_options(all_events, map_id)
                ent_opts_zn = _editor_collect_entity_name_options(objs, npcs)

                if event.type == pygame.MOUSEWHEEL:
                    px, py = _editor_pointer_xy(event, mx, my)
                    delta = _editor_wheel_delta(event)
                    if zone_modal_dd_open and zone_modal_dd_rect:
                        total_h = len(zone_modal_dd_options) * dd_item_h_zn
                        vis = max(1, zone_modal_dd_rect.height)
                        max_dd = max(0, total_h - vis)
                        if max_dd > 0 and _editor_rects_contain_point(
                            px, py, zone_modal_dd_rect, body_rect_zn, panel_rect
                        ):
                            zone_modal_dd_scroll = max(0, min(max_dd, zone_modal_dd_scroll + delta))
                    elif _editor_rects_contain_point(px, py, body_rect_zn, sb_rect_zn, panel_rect):
                        zone_modal_scroll = max(0, min(max_zn_scroll, zone_modal_scroll + delta))
                    continue

                if event.type == pygame.MOUSEMOTION and modal_body_drag == "zone":
                    ui_sb = _step_overlay_scrollbar_layout(
                        sb_rect_zn, body_rect_zn.height, content_h_zn, zone_modal_scroll
                    )
                    sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_sb)
                    if sp is not None:
                        zone_modal_scroll = sp
                    continue

                if event.type == pygame.MOUSEMOTION and modal_dropdown_drag == "zone_dd":
                    if zone_modal_dd_ui:
                        sp = _editor_scroll_px_from_sb_my(event.pos[1], zone_modal_dd_ui)
                        if sp is not None:
                            zone_modal_dd_scroll = sp
                    continue

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if modal_body_drag == "zone":
                        modal_body_drag = None
                    if modal_dropdown_drag == "zone_dd":
                        modal_dropdown_drag = None
                    continue

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if zone_modal_dd_open and zone_modal_dd_rect:
                        dr = zone_modal_dd_rect
                        ui_prev = zone_modal_dd_ui
                        if dr.collidepoint(event.pos):
                            if ui_prev:
                                dd_hit = _editor_modal_sb_hit(event.pos, ui_prev)
                                if dd_hit == "thumb":
                                    modal_dropdown_drag = "zone_dd"
                                    continue
                                if dd_hit == "track":
                                    sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_prev)
                                    if sp is not None:
                                        zone_modal_dd_scroll = sp
                                    continue
                            sb_ex = 11 if int((ui_prev or {}).get("max_scroll") or 0) > 0 else 0
                            pick_w = max(1, dr.width - sb_ex)
                            if event.pos[0] < dr.x + pick_w:
                                rel_y = event.pos[1] - dr.y + zone_modal_dd_scroll
                                ix = rel_y // dd_item_h_zn
                                if 0 <= ix < len(zone_modal_dd_options):
                                    k = zone_modal_dd_key
                                    if k:
                                        zone_fields[k] = str(zone_modal_dd_options[ix])
                                    zone_modal_dd_open = False
                                    continue
                            continue
                        zone_modal_dd_open = False

                    ui_sb_zn = _step_overlay_scrollbar_layout(
                        sb_rect_zn, body_rect_zn.height, content_h_zn, zone_modal_scroll
                    )
                    sb_hit = _editor_modal_sb_hit(event.pos, ui_sb_zn)
                    if sb_hit == "thumb":
                        modal_body_drag = "zone"
                        continue
                    if sb_hit == "track":
                        sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_sb_zn)
                        if sp is not None:
                            zone_modal_scroll = sp
                        continue

                    active_zone_field = None

                    for i, row in enumerate(rows_zn):
                        rk = row[1]
                        kind = row[2]
                        ry = body_rect_zn.y + i * row_h_zn - zone_modal_scroll
                        if ry + row_h_zn < body_rect_zn.top or ry > body_rect_zn.bottom:
                            continue
                        if kind == "text":
                            val_rect = pygame.Rect(
                                field_x_zn, ry + 3, body_rect_zn.right - field_x_zn - 8, row_h_zn - 6
                            )
                            if val_rect.collidepoint(event.pos):
                                active_zone_field = rk
                                continue
                        elif kind == "events":
                            list_btn = pygame.Rect(field_x_zn + field_w_zn + 4, ry + 3, list_w_zn, row_h_zn - 6)
                            val_rect = pygame.Rect(field_x_zn, ry + 3, field_w_zn, row_h_zn - 6)
                            if list_btn.collidepoint(event.pos):
                                zone_modal_dd_key = rk
                                zone_modal_dd_options = list(ev_ids_zn)
                                zone_modal_dd_scroll = 0
                                n_opt = len(zone_modal_dd_options)
                                dd_h = min(220, max(dd_item_h_zn, n_opt * dd_item_h_zn))
                                zone_modal_dd_rect = pygame.Rect(
                                    field_x_zn, ry + row_h_zn + 2, field_w_zn + list_w_zn + 4, dd_h
                                )
                                zone_modal_dd_open = True
                                continue
                            if val_rect.collidepoint(event.pos):
                                active_zone_field = rk
                                continue
                        elif kind == "text_pick":
                            val_rect = pygame.Rect(field_x_zn, ry + 3, fld_txt_w_zn, row_h_zn - 6)
                            list_btn = pygame.Rect(val_rect.right + 4, ry + 3, list_w_zn, row_h_zn - 6)
                            pick_btn = pygame.Rect(list_btn.right + 4, ry + 3, pick_w_zn, row_h_zn - 6)
                            if list_btn.collidepoint(event.pos):
                                zone_modal_dd_key = rk
                                zone_modal_dd_options = list(ent_opts_zn)
                                zone_modal_dd_scroll = 0
                                n_opt = len(zone_modal_dd_options)
                                dd_h = min(220, max(dd_item_h_zn, n_opt * dd_item_h_zn))
                                zone_modal_dd_rect = pygame.Rect(
                                    field_x_zn, ry + row_h_zn + 2, fld_txt_w_zn + list_w_zn + pick_w_zn + 12, dd_h
                                )
                                zone_modal_dd_open = True
                                continue
                            if pick_btn.collidepoint(event.pos):
                                is_picking_zone_target = True
                                reopen_zone_config_after_target_pick = True
                                show_zone_config = False
                                zone_modal_dd_open = False
                                continue
                            if val_rect.collidepoint(event.pos):
                                active_zone_field = rk
                                continue
                        elif kind == "dropdown":
                            opts = row[3]
                            list_btn = pygame.Rect(field_x_zn + field_w_zn + 4, ry + 3, list_w_zn, row_h_zn - 6)
                            val_rect = pygame.Rect(field_x_zn, ry + 3, field_w_zn, row_h_zn - 6)
                            if list_btn.collidepoint(event.pos):
                                zone_modal_dd_key = rk
                                zone_modal_dd_options = list(opts)
                                zone_modal_dd_scroll = 0
                                n_opt = len(zone_modal_dd_options)
                                dd_h = min(220, max(dd_item_h_zn, n_opt * dd_item_h_zn))
                                zone_modal_dd_rect = pygame.Rect(
                                    field_x_zn, ry + row_h_zn + 2, field_w_zn + list_w_zn + 4, dd_h
                                )
                                zone_modal_dd_open = True
                                continue
                            if val_rect.collidepoint(event.pos):
                                active_zone_field = rk
                                continue
                        elif kind == "area":
                            area_btn_r = pygame.Rect(field_x_zn, ry + 3, 140, row_h_zn - 6)
                            if area_btn_r.collidepoint(event.pos):
                                is_selecting_zone_rect = True
                                zone_drag_start = None
                                zone_drag_end = None
                                show_zone_config = False
                                reopen_zone_config_after_area = True
                                zone_modal_dd_open = False
                                continue

                    if save_btn.collidepoint(event.pos):
                        # zone 저장
                        name = (zone_fields.get("name") or "").strip()
                        eid = (zone_fields.get("event_id") or "").strip()
                        rect = zone_fields.get("rect")

                        if name and eid and rect and rect[2] > 0 and rect[3] > 0:
                            z = {
                                "name": name,
                                "rect": [int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])],
                                "trigger": zone_fields.get("trigger") or "contact_player",
                                "conditions": {},
                                "event_id": eid,
                            }

                            # contact_object: 어떤 대상과 접촉해야 하는지 저장
                            if (z["trigger"] == "contact_object"):
                                tgt = (zone_fields.get("target") or "").strip()
                                if tgt:
                                    z["target"] = tgt

                            mp = (zone_fields.get("cond_mainprogress") or "").strip()
                            if mp:
                                z["conditions"]["mainprogress"] = mp
                            mlp = (zone_fields.get("cond_min_laugh_point") or "").strip()
                            if mlp:
                                try:
                                    z["conditions"]["min_laugh_point"] = int(float(mlp))
                                except:
                                    pass
                            opt = (zone_fields.get("cond_opt") or "").strip()
                            if opt:
                                extra = _parse_editor_json_kv_blob(opt)
                                if extra is None:
                                    print(
                                        "Zone cond_opt JSON 오류 — 예: \"progress_x\": 1001"
                                    )
                                else:
                                    z["conditions"].update(extra)

                            zones = flow.world_data.setdefault(map_id, {}).setdefault("event_zones", [])
                            if zone_edit_idx is not None and 0 <= zone_edit_idx < len(zones):
                                zones[zone_edit_idx] = z
                            else:
                                zones.append(z)

                            # 파일 즉시 저장 (objects/npcs도 함께 최신화)
                            flow.save_editor_data(map_id, objs, npcs)
                            _flow_refresh_entity_list()

                        show_zone_config = False
                        zone_edit_idx = None
                        active_zone_field = None
                        is_selecting_zone_rect = False

                    elif canc_btn.collidepoint(event.pos):
                        show_zone_config = False
                        zone_edit_idx = None
                        active_zone_field = None
                        is_selecting_zone_rect = False

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if zone_modal_dd_open:
                            zone_modal_dd_open = False
                        else:
                            show_zone_config = False
                    elif active_zone_field:
                        if event.key == pygame.K_BACKSPACE:
                            zone_fields[active_zone_field] = (zone_fields.get(active_zone_field, "")[:-1])
                        elif event.key == pygame.K_RETURN:
                            active_zone_field = None
                continue

            if show_bgzone_config:
                rows_bg = _bgzone_modal_rows()
                panel_rect, content_h_bg, _ = _editor_std_modal_rect(SCREEN_W, SCREEN_H, len(rows_bg))
                body_rect_bg, sb_rect_bg, max_bg_scroll, bgzone_modal_scroll = _editor_modal_body_scroll_layout(
                    panel_rect, bgzone_modal_scroll, content_h_bg
                )
                save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
                canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)
                row_h_bg = EDITOR_MODAL_ROW_H
                dd_item_h_bg = 22
                field_x_bg = body_rect_bg.x + EDITOR_MODAL_LABEL_W
                field_w_bg = 220
                list_w_bg = 52

                if event.type == pygame.MOUSEWHEEL:
                    px, py = _editor_pointer_xy(event, mx, my)
                    delta = _editor_wheel_delta(event)
                    if bgzone_modal_dd_open and bgzone_modal_dd_rect:
                        total_h = len(bgzone_modal_dd_options) * dd_item_h_bg
                        vis = max(1, bgzone_modal_dd_rect.height)
                        max_dd = max(0, total_h - vis)
                        if max_dd > 0 and _editor_rects_contain_point(
                            px, py, bgzone_modal_dd_rect, body_rect_bg, panel_rect
                        ):
                            bgzone_modal_dd_scroll = max(0, min(max_dd, bgzone_modal_dd_scroll + delta))
                    elif _editor_rects_contain_point(px, py, body_rect_bg, sb_rect_bg, panel_rect):
                        bgzone_modal_scroll = max(0, min(max_bg_scroll, bgzone_modal_scroll + delta))
                    continue

                if event.type == pygame.MOUSEMOTION and modal_body_drag == "bgzone":
                    ui_sb = _step_overlay_scrollbar_layout(
                        sb_rect_bg, body_rect_bg.height, content_h_bg, bgzone_modal_scroll
                    )
                    sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_sb)
                    if sp is not None:
                        bgzone_modal_scroll = sp
                    continue

                if event.type == pygame.MOUSEMOTION and modal_dropdown_drag == "bgzone_dd":
                    if bgzone_modal_dd_ui:
                        sp = _editor_scroll_px_from_sb_my(event.pos[1], bgzone_modal_dd_ui)
                        if sp is not None:
                            bgzone_modal_dd_scroll = sp
                    continue

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if modal_body_drag == "bgzone":
                        modal_body_drag = None
                    if modal_dropdown_drag == "bgzone_dd":
                        modal_dropdown_drag = None
                    continue

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if bgzone_modal_dd_open and bgzone_modal_dd_rect:
                        dr = bgzone_modal_dd_rect
                        ui_prev = bgzone_modal_dd_ui
                        if dr.collidepoint(event.pos):
                            if ui_prev:
                                dd_hit = _editor_modal_sb_hit(event.pos, ui_prev)
                                if dd_hit == "thumb":
                                    modal_dropdown_drag = "bgzone_dd"
                                    continue
                                if dd_hit == "track":
                                    sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_prev)
                                    if sp is not None:
                                        bgzone_modal_dd_scroll = sp
                                    continue
                            sb_ex = 11 if int((ui_prev or {}).get("max_scroll") or 0) > 0 else 0
                            pick_w = max(1, dr.width - sb_ex)
                            if event.pos[0] < dr.x + pick_w:
                                rel_y = event.pos[1] - dr.y + bgzone_modal_dd_scroll
                                ix = rel_y // dd_item_h_bg
                                if 0 <= ix < len(bgzone_modal_dd_options):
                                    k = bgzone_modal_dd_key
                                    if k:
                                        bgzone_fields[k] = str(bgzone_modal_dd_options[ix])
                                    bgzone_modal_dd_open = False
                                    continue
                            continue
                        bgzone_modal_dd_open = False

                    ui_sb_bg = _step_overlay_scrollbar_layout(
                        sb_rect_bg, body_rect_bg.height, content_h_bg, bgzone_modal_scroll
                    )
                    sb_hit = _editor_modal_sb_hit(event.pos, ui_sb_bg)
                    if sb_hit == "thumb":
                        modal_body_drag = "bgzone"
                        continue
                    if sb_hit == "track":
                        sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_sb_bg)
                        if sp is not None:
                            bgzone_modal_scroll = sp
                        continue

                    active_bgzone_field = None

                    for i, row in enumerate(rows_bg):
                        rk = row[1]
                        kind = row[2]
                        ry = body_rect_bg.y + i * row_h_bg - bgzone_modal_scroll
                        if ry + row_h_bg < body_rect_bg.top or ry > body_rect_bg.bottom:
                            continue
                        if kind == "text":
                            val_rect = pygame.Rect(
                                field_x_bg, ry + 3, body_rect_bg.right - field_x_bg - 8, row_h_bg - 6
                            )
                            if val_rect.collidepoint(event.pos):
                                active_bgzone_field = rk
                                continue
                        elif kind == "dropdown":
                            opts = row[3]
                            list_btn = pygame.Rect(field_x_bg + field_w_bg + 4, ry + 3, list_w_bg, row_h_bg - 6)
                            val_rect = pygame.Rect(field_x_bg, ry + 3, field_w_bg, row_h_bg - 6)
                            if list_btn.collidepoint(event.pos):
                                bgzone_modal_dd_key = rk
                                bgzone_modal_dd_options = list(opts)
                                bgzone_modal_dd_scroll = 0
                                n_opt = len(bgzone_modal_dd_options)
                                dd_h = min(220, max(dd_item_h_bg, n_opt * dd_item_h_bg))
                                bgzone_modal_dd_rect = pygame.Rect(
                                    field_x_bg, ry + row_h_bg + 2, field_w_bg + list_w_bg + 4, dd_h
                                )
                                bgzone_modal_dd_open = True
                                continue
                            if val_rect.collidepoint(event.pos):
                                active_bgzone_field = rk
                                continue
                        elif kind == "area":
                            area_btn_r = pygame.Rect(field_x_bg, ry + 3, 140, row_h_bg - 6)
                            if area_btn_r.collidepoint(event.pos):
                                is_selecting_bgzone_rect = True
                                bgzone_drag_start = None
                                bgzone_drag_end = None
                                show_bgzone_config = False
                                reopen_bgzone_config_after_area = True
                                bgzone_modal_dd_open = False
                                continue

                    if save_btn.collidepoint(event.pos):
                        name = (bgzone_fields.get("name") or "").strip()
                        rect = bgzone_fields.get("rect")
                        try:
                            layer = int(float((bgzone_fields.get("layer") or "-50").strip()))
                        except Exception:
                            layer = -50
                        draw_only_when_tilt = str(bgzone_fields.get("draw_only_when_tilt", "true") or "true").strip().lower() == "true"
                        update_policy = str(bgzone_fields.get("update_policy", "none") or "none").strip().lower()
                        if update_policy not in ("none", "lowrate", "normal"):
                            update_policy = "none"
                        sort_policy = str(bgzone_fields.get("sort_policy", "none") or "none").strip().lower()
                        if sort_policy not in ("none", "cached"):
                            sort_policy = "none"
                        try:
                            cull_margin_px = int(float((bgzone_fields.get("cull_margin_px") or "160").strip()))
                        except Exception:
                            cull_margin_px = 160
                        cull_margin_px = max(0, min(2000, cull_margin_px))

                        if rect and rect[2] > 0 and rect[3] > 0:
                            z = {
                                "name": name or f"bg_{pygame.time.get_ticks()}",
                                "rect": [int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])],
                                "layer": int(layer),
                                "draw_only_when_tilt": bool(draw_only_when_tilt),
                                "update_policy": update_policy,
                                "sort_policy": sort_policy,
                                "cull_margin_px": int(cull_margin_px),
                            }
                            zones = flow.world_data.setdefault(map_id, {}).setdefault("bg_zones", [])
                            if bgzone_edit_idx is not None and 0 <= bgzone_edit_idx < len(zones):
                                zones[bgzone_edit_idx] = z
                            else:
                                zones.append(z)
                            flow.save_editor_data(map_id, objs, npcs)

                        show_bgzone_config = False
                        bgzone_edit_idx = None
                        active_bgzone_field = None
                        is_selecting_bgzone_rect = False

                    elif canc_btn.collidepoint(event.pos):
                        show_bgzone_config = False
                        bgzone_edit_idx = None
                        active_bgzone_field = None
                        is_selecting_bgzone_rect = False

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if bgzone_modal_dd_open:
                            bgzone_modal_dd_open = False
                        else:
                            show_bgzone_config = False
                    elif active_bgzone_field:
                        if event.key == pygame.K_BACKSPACE:
                            bgzone_fields[active_bgzone_field] = (bgzone_fields.get(active_bgzone_field, "")[:-1])
                        elif event.key == pygame.K_RETURN:
                            active_bgzone_field = None
                continue

            if show_step_config:
                panel_rect = _step_settings_panel_rect(SCREEN_W, SCREEN_H, step_fields)
                save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
                canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)
                delete_btn = pygame.Rect(panel_rect.x + 20, panel_rect.bottom - 50, 100, 35)
                t_cur = (step_fields.get("type") or "MOVE").upper()
                rows_layout = _step_field_rows(step_fields.get("type", "MOVE"))
                tgt_item_h = 22

                if event.type == pygame.MOUSEWHEEL:
                    px, py = _editor_pointer_xy(event, mx, my)
                    delta = _editor_wheel_delta(event)
                    if (
                        step_target_dropdown_open
                        and step_target_dropdown_rect
                        and step_target_options
                    ):
                        total_h = len(step_target_options) * tgt_item_h
                        vis = max(1, step_target_dropdown_rect.height)
                        max_sc = max(0, total_h - vis)
                        if max_sc > 0 and _editor_rects_contain_point(
                            px, py, step_target_dropdown_rect, panel_rect
                        ):
                            step_target_scroll = max(0, min(max_sc, step_target_scroll + delta))

                    if step_type_dropdown_open:
                        dropdown_item_h = 22
                        type_rect = pygame.Rect(panel_rect.x + 180, panel_rect.y + 70, 280, 30)
                        max_h = 260
                        vis_h = min(max_h, dropdown_item_h * len(step_type_cycle))
                        dropdown_rect = pygame.Rect(type_rect.x, type_rect.bottom, type_rect.width, vis_h)
                        total_h = len(step_type_cycle) * dropdown_item_h
                        max_sc = max(0, total_h - vis_h)
                        if max_sc > 0 and _editor_rects_contain_point(px, py, dropdown_rect, panel_rect):
                            step_type_scroll = max(0, min(max_sc, step_type_scroll + delta))

                    if (not step_target_dropdown_open) and (not step_type_dropdown_open):
                        body_r, sb_r, max_bsc, ch_ov = _step_overlay_body_geometry(panel_rect, rows_layout)
                        if max_bsc > 0 and _editor_rects_contain_point(px, py, body_r, sb_r, panel_rect):
                            step_body_scroll = max(0, min(max_bsc, step_body_scroll + delta))

                if event.type == pygame.MOUSEBUTTONDOWN:
                    # 삭제 확인창이 열려 있으면, 그 입력만 처리
                    if show_step_delete_confirm:
                        confirm_rect = pygame.Rect(panel_rect.centerx - 160, panel_rect.centery - 70, 320, 140)
                        yes_btn = pygame.Rect(confirm_rect.x + 30, confirm_rect.bottom - 45, 110, 32)
                        no_btn = pygame.Rect(confirm_rect.right - 140, confirm_rect.bottom - 45, 110, 32)
                        if yes_btn.collidepoint(event.pos):
                            if current_event_id and current_event_type and step_edit_index is not None:
                                steps = all_events[current_event_type][current_event_id].setdefault("steps", [])
                                if 0 <= step_edit_index < len(steps):
                                    steps.pop(step_edit_index)
                                    flow.save_events(all_events)
                            # 닫기/리셋
                            show_step_delete_confirm = False
                            show_step_config = False
                            step_edit_index = None
                            step_insert_index = None
                            active_step_field = None
                            step_type_dropdown_open = False
                            step_target_dropdown_open = False
                        elif no_btn.collidepoint(event.pos) or not confirm_rect.collidepoint(event.pos):
                            show_step_delete_confirm = False
                        continue

                    if step_target_dropdown_open and step_target_dropdown_rect:
                        if step_target_dropdown_rect.collidepoint(event.pos):
                            if step_target_dd_ui:
                                sb_hit = _editor_modal_sb_hit(event.pos, step_target_dd_ui)
                                if sb_hit == "thumb":
                                    dd_drag_kind = "target"
                                    continue
                                if sb_hit == "track":
                                    sp = _editor_scroll_px_from_sb_my(event.pos[1], step_target_dd_ui)
                                    if sp is not None:
                                        step_target_scroll = sp
                                    continue
                            rel = event.pos[1] - step_target_dropdown_rect.y + step_target_scroll
                            pick_i = int(rel // tgt_item_h)
                            if 0 <= pick_i < len(step_target_options):
                                ky = step_target_field_key or "target"
                                step_fields[ky] = step_target_options[pick_i]
                            step_target_dropdown_open = False
                            continue
                        step_target_dropdown_open = False

                    # 필드 클릭 판정
                    active_step_field = None

                    type_rect = pygame.Rect(panel_rect.x + 180, panel_rect.y + 70, 280, 30)
                    # 드롭다운: 타입 클릭 → 열기/닫기, 옵션 클릭 → 선택
                    dropdown_item_h = 22
                    max_h = 260
                    vis_h = min(max_h, dropdown_item_h * len(step_type_cycle))
                    dropdown_rect = pygame.Rect(type_rect.x, type_rect.bottom, type_rect.width, vis_h)

                    if step_type_dropdown_open:
                        # 바깥 클릭하면 닫기 (옵션 클릭 포함 처리)
                        if dropdown_rect.collidepoint(event.pos):
                            if step_type_dd_ui:
                                sb_hit = _editor_modal_sb_hit(event.pos, step_type_dd_ui)
                                if sb_hit == "thumb":
                                    dd_drag_kind = "type"
                                    continue
                                if sb_hit == "track":
                                    sp = _editor_scroll_px_from_sb_my(event.pos[1], step_type_dd_ui)
                                    if sp is not None:
                                        step_type_scroll = sp
                                    continue
                            rel_y = event.pos[1] - dropdown_rect.y + step_type_scroll
                            pick = int(rel_y // dropdown_item_h)
                            if 0 <= pick < len(step_type_cycle):
                                step_fields["type"] = step_type_cycle[pick]
                                _apply_default_step_fields_on_type_change(step_fields, step_fields["type"])
                                step_body_scroll = 0
                            step_type_dropdown_open = False
                            step_target_dropdown_open = False
                            continue
                        elif type_rect.collidepoint(event.pos):
                            step_type_dropdown_open = False
                            continue
                        else:
                            step_type_dropdown_open = False
                            # 닫고 나머지 클릭 처리 계속

                    if type_rect.collidepoint(event.pos):
                        step_type_dropdown_open = True
                        step_type_scroll = 0
                        step_target_dropdown_open = False
                        continue

                    # Delete 버튼 (수정 모드에서만)
                    if step_edit_index is not None and delete_btn.collidepoint(event.pos):
                        show_step_delete_confirm = True
                        step_type_dropdown_open = False
                        step_target_dropdown_open = False
                        continue

                    scroll_off = step_body_scroll
                    body_r, sb_r, max_bsc, ch_ov = _step_overlay_body_geometry(panel_rect, rows_layout)
                    step_body_scroll = min(step_body_scroll, max_bsc)
                    if max_bsc > 0:
                        ui_sb = _step_overlay_scrollbar_layout(sb_r, body_r.height, ch_ov, step_body_scroll)
                        sb_hit = _editor_modal_sb_hit(event.pos, ui_sb)
                        if sb_hit == "thumb":
                            dd_drag_kind = "step_body"
                            continue
                        if sb_hit == "track":
                            sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_sb)
                            if sp is not None:
                                step_body_scroll = sp
                            continue

                    cy = 0
                    coord_pair_rows = {}
                    waypoint_pick_row_top = None
                    step_field_click_done = False
                    steps_ref = []
                    before_ix = 0
                    if current_event_id and current_event_type:
                        steps_ref = all_events[current_event_type][current_event_id].get("steps", [])
                        if step_edit_index is not None:
                            before_ix = int(step_edit_index)
                        elif step_insert_index is not None:
                            before_ix = int(step_insert_index)
                        else:
                            before_ix = len(steps_ref)
                    for _label, key in rows_layout:
                        row_top = panel_rect.y + 120 + cy - scroll_off
                        if key.startswith("_hint"):
                            cy += STEP_BODY_ROW_H
                            continue
                        row_interactive = body_r.collidepoint(event.pos) and (
                            row_top + STEP_BODY_ROW_H > body_r.top and row_top - 5 < body_r.bottom
                        )
                        if not row_interactive:
                            cy += STEP_BODY_ROW_H
                            continue
                        for pair in _step_coord_xy_pairs(t_cur):
                            if key == pair[0]:
                                coord_pair_rows[pair] = row_top
                                break
                        if t_cur == "MOVE" and key == "waypoints":
                            waypoint_pick_row_top = row_top
                        dd_opts = _step_dropdown_field_options(
                            t_cur,
                            key,
                            map_list=map_list,
                            steps_ref=steps_ref,
                            before_ix=before_ix,
                            player=player,
                            objs=objs,
                            npcs=npcs,
                            all_events=all_events,
                        )
                        if dd_opts is not None:
                            r = pygame.Rect(panel_rect.x + 180, row_top - 5, 220, 30)
                            list_btn = pygame.Rect(panel_rect.x + 180 + 225, row_top - 5, 52, 30)
                            if list_btn.collidepoint(event.pos):
                                step_target_options = list(dd_opts)
                                step_target_scroll = 0
                                step_target_dropdown_open = True
                                step_target_field_key = key
                                n_opt = len(step_target_options)
                                dd_h = min(220, max(tgt_item_h, n_opt * tgt_item_h))
                                step_target_dropdown_rect = pygame.Rect(
                                    panel_rect.x + 180,
                                    row_top + 28,
                                    280,
                                    dd_h,
                                )
                                step_field_click_done = True
                                break
                            if r.collidepoint(event.pos):
                                active_step_field = key
                        elif key == "music" and t_cur in ("SCREEN", "MUSIC_PLAY"):
                            r = pygame.Rect(panel_rect.x + 180, row_top - 5, 220, 30)
                            list_btn = pygame.Rect(panel_rect.x + 180 + 225, row_top - 5, 52, 30)
                            if list_btn.collidepoint(event.pos):
                                step_target_options = _music_track_options()
                                step_target_scroll = 0
                                step_target_dropdown_open = True
                                step_target_field_key = "music"
                                n_opt = len(step_target_options)
                                dd_h = min(220, max(tgt_item_h, n_opt * tgt_item_h))
                                step_target_dropdown_rect = pygame.Rect(
                                    panel_rect.x + 180,
                                    row_top + 28,
                                    280,
                                    dd_h,
                                )
                                step_field_click_done = True
                                break
                            if r.collidepoint(event.pos):
                                active_step_field = "music"
                        elif key == "anim" and t_cur == "ACTION_ANIM":
                            r = pygame.Rect(panel_rect.x + 180, row_top - 5, 220, 30)
                            list_btn = pygame.Rect(panel_rect.x + 180 + 225, row_top - 5, 52, 30)
                            if list_btn.collidepoint(event.pos):
                                step_target_options = _char_anim_dropdown_options()
                                step_target_scroll = 0
                                step_target_dropdown_open = True
                                step_target_field_key = "anim"
                                n_opt = len(step_target_options)
                                dd_h = min(220, max(tgt_item_h, n_opt * tgt_item_h))
                                step_target_dropdown_rect = pygame.Rect(
                                    panel_rect.x + 180,
                                    row_top + 28,
                                    280,
                                    dd_h,
                                )
                                step_field_click_done = True
                                break
                            if r.collidepoint(event.pos):
                                active_step_field = "anim"
                        elif _step_row_entity_pick(t_cur, key) and current_event_id and current_event_type:
                            r = pygame.Rect(panel_rect.x + 180, row_top - 5, 220, 30)
                            list_btn = pygame.Rect(panel_rect.x + 180 + 225, row_top - 5, 52, 30)
                            pick_btn = pygame.Rect(panel_rect.x + 180 + 225 + 56, row_top - 5, 52, 30)
                            if list_btn.collidepoint(event.pos):
                                step_target_options = _step_entity_options_for_pick(
                                    t_cur, key, steps_ref, before_ix, player, objs, npcs
                                )
                                step_target_scroll = 0
                                step_target_dropdown_open = True
                                step_target_field_key = key
                                n_opt = len(step_target_options)
                                dd_h = min(220, max(tgt_item_h, n_opt * tgt_item_h))
                                step_target_dropdown_rect = pygame.Rect(
                                    panel_rect.x + 180,
                                    row_top + 28,
                                    280,
                                    dd_h,
                                )
                                step_field_click_done = True
                                break
                            if pick_btn.collidepoint(event.pos):
                                picking_step_target_field_key = key
                                is_picking_step_target = True
                                reopen_step_config_after_target_pick = True
                                show_step_config = False
                                active_step_field = None
                                step_type_dropdown_open = False
                                step_target_dropdown_open = False
                                step_field_click_done = True
                                break
                            if r.collidepoint(event.pos):
                                active_step_field = key
                        else:
                            r = pygame.Rect(panel_rect.x + 180, row_top - 5, 280, 30)
                            if r.collidepoint(event.pos):
                                active_step_field = key
                        cy += STEP_BODY_ROW_H
                    if step_field_click_done:
                        continue

                    # 좌표 찍기 (모든 월드 좌표 쌍)
                    t_now = (step_fields.get("type") or "MOVE").upper()
                    _picked_coord = False
                    for pair, row_y in coord_pair_rows.items():
                        pick_btn = pygame.Rect(panel_rect.x + 180 + 192, row_y - 1, 86, 22)
                        if pick_btn.collidepoint(event.pos):
                            is_picking_step_pos = True
                            picking_step_xy_keys = pair
                            reopen_step_config_after_pick = True
                            show_step_config = False
                            active_step_field = None
                            step_type_dropdown_open = False
                            step_target_dropdown_open = False
                            _picked_coord = True
                            break
                    if _picked_coord:
                        continue

                    if t_now == "MOVE" and waypoint_pick_row_top is not None:
                        pick_wp_btn = pygame.Rect(panel_rect.x + 180 + 192, waypoint_pick_row_top - 1, 86, 22)
                        if pick_wp_btn.collidepoint(event.pos):
                            is_picking_step_waypoints = True
                            reopen_step_config_after_pick = True
                            show_step_config = False
                            active_step_field = None
                            step_type_dropdown_open = False
                            step_target_dropdown_open = False
                            continue

                    if save_btn.collidepoint(event.pos):
                        # 저장(삽입/수정/추가)
                        if current_event_id and current_event_type:
                            t = (step_fields.get("type") or "MOVE").upper()
                            if t == "GLOBAL":
                                t = "DEV_CMD"

                            def parse_float(s, default=None):
                                try:
                                    return float(s)
                                except:
                                    return default

                            def parse_bool(s):
                                s = (s or "").strip().lower()
                                if s in ("1", "true", "t", "yes", "y", "on"):
                                    return True
                                if s in ("0", "false", "f", "no", "n", "off"):
                                    return False
                                return None

                            def pos_pair():
                                x = parse_float(step_fields.get("pos_x"), None)
                                y = parse_float(step_fields.get("pos_y"), None)
                                if x is None or y is None:
                                    return None
                                return [int(x), int(y)]

                            new_step = {"type": t}
                            if t in ("MOVE", "PLACE", "MAP"):
                                if step_fields.get("target"):
                                    new_step["target"] = step_fields.get("target")
                                if t == "MOVE":
                                    extras = _parse_waypoints_semicolon(step_fields.get("waypoints"))
                                    p = pos_pair()
                                    if p is not None:
                                        pts = [[int(p[0]), int(p[1])]] + [
                                            [int(round(ax)), int(round(ay))] for ax, ay in extras
                                        ]
                                    elif extras:
                                        pts = [[int(round(ax)), int(round(ay))] for ax, ay in extras]
                                    else:
                                        pts = []
                                    if len(pts) == 1:
                                        new_step["pos"] = pts[0]
                                    elif len(pts) > 1:
                                        new_step["pos"] = pts
                                else:
                                    p = pos_pair()
                                    if p is not None:
                                        new_step["pos"] = p
                                if step_fields.get("dir"):
                                    new_step["dir"] = step_fields.get("dir")
                                if step_fields.get("appear"):
                                    new_step["appear"] = step_fields.get("appear")
                                if t == "PLACE" and step_fields.get("action"):
                                    new_step["action"] = step_fields.get("action")
                                if t == "PLACE":
                                    stv = parse_float(step_fields.get("sprite_tilt"), None)
                                    if stv is not None:
                                        new_step["sprite_tilt"] = max(0.0, min(1.0, stv))
                                    h_pl = parse_float(step_fields.get("height"), None)
                                    if h_pl is not None:
                                        new_step["height"] = max(0.0, min(4000.0, h_pl))
                                    ys = (step_fields.get("ysort") or "").strip()
                                    if ys:
                                        new_step["ysort"] = ys
                                    ly = parse_float(step_fields.get("layer"), None)
                                    if ly is not None:
                                        new_step["layer"] = int(round(ly))
                                if t == "MOVE":
                                    binst = parse_bool(step_fields.get("instant"))
                                    if binst is True:
                                        new_step["instant"] = True
                                    bf = parse_bool(step_fields.get("force"))
                                    if bf is True:
                                        new_step["force"] = True
                                    sp = parse_float(step_fields.get("speed"), None)
                                    if sp is not None:
                                        new_step["speed"] = sp
                                    bw = parse_bool(step_fields.get("wait"))
                                    if bw is True:
                                        new_step["wait"] = True
                                    elif bw is False:
                                        new_step["wait"] = False
                                    ma = (step_fields.get("move_anim") or "").strip()
                                    if ma:
                                        new_step["move_anim"] = ma
                                    ms = (step_fields.get("move_sync") or "").strip()
                                    if ms:
                                        new_step["move_sync"] = ms
                            elif t == "ACTION_ANIM":
                                tg = (step_fields.get("target") or "").strip()
                                if tg:
                                    new_step["target"] = tg
                                an = (step_fields.get("anim") or "").strip()
                                if an:
                                    new_step["anim"] = an
                                md = (step_fields.get("mode") or "once").strip().lower()
                                if md in ("once", "hold"):
                                    new_step["mode"] = md
                                rel = (step_fields.get("release") or "idle").strip().lower()
                                if rel in ("idle", "stop"):
                                    new_step["release"] = rel
                                v = parse_float(step_fields.get("val"), None)
                                if v is not None:
                                    new_step["val"] = float(v)
                                bl = parse_bool(step_fields.get("loop"))
                                if bl is not None:
                                    new_step["loop"] = bl
                                bw = parse_bool(step_fields.get("wait"))
                                if bw is not None:
                                    new_step["wait"] = bw
                                dr = (step_fields.get("dir") or "").strip()
                                if dr:
                                    new_step["dir"] = dr
                                hj = parse_float(step_fields.get("height"), None)
                                if hj is not None:
                                    new_step["height"] = max(0.0, min(4000.0, float(hj)))
                            elif t == "TUNE":
                                if step_fields.get("target"):
                                    new_step["target"] = step_fields.get("target")
                                stv = parse_float(step_fields.get("sprite_tilt"), None)
                                if stv is not None:
                                    new_step["sprite_tilt"] = max(0.0, min(1.0, stv))
                                h_pl = parse_float(step_fields.get("height"), None)
                                if h_pl is not None:
                                    new_step["height"] = max(0.0, min(4000.0, h_pl))
                                ys = (step_fields.get("ysort") or "").strip()
                                if ys:
                                    new_step["ysort"] = ys
                                ly = parse_float(step_fields.get("layer"), None)
                                if ly is not None:
                                    new_step["layer"] = int(round(ly))
                                bv = parse_bool(step_fields.get("visible"))
                                if bv is not None:
                                    new_step["visible"] = bv
                                av = parse_float(step_fields.get("alpha"), None)
                                if av is not None:
                                    new_step["alpha"] = int(max(0, min(255, int(round(av)))))
                            elif t == "SAY":
                                if step_fields.get("who"):
                                    new_step["who"] = step_fields.get("who")
                                sn = parse_bool(step_fields.get("show_name"))
                                if sn is not None:
                                    new_step["show_name"] = sn
                                new_step["text"] = step_fields.get("text", "")
                                if step_fields.get("voice"):
                                    new_step["voice"] = step_fields.get("voice")
                                b = parse_bool(step_fields.get("auto"))
                                if b is not None:
                                    new_step["auto"] = b
                                v = parse_float(step_fields.get("val"), None)
                                if v is not None:
                                    new_step["val"] = v
                                bb = parse_bool(step_fields.get("bubble"))
                                if bb is not None:
                                    new_step["bubble"] = bb
                                bbt = (step_fields.get("bubble_target") or "").strip()
                                if bbt:
                                    new_step["bubble_target"] = bbt
                            elif t == "EMOTE":
                                act = (step_fields.get("action") or "show").strip().lower()
                                new_step["action"] = act if act in ("show", "clear") else "show"
                                if new_step["action"] != "clear":
                                    emo = (step_fields.get("emotion") or "").strip()
                                    emo = "".join(ch for ch in emo if ch.isalnum() or ch == "_")[:64]
                                    if emo:
                                        new_step["emotion"] = emo
                                    tg = (step_fields.get("target") or "").strip()
                                    if tg:
                                        new_step["target"] = tg
                                    fm = parse_float(step_fields.get("frame_ms"), None)
                                    if fm is not None:
                                        new_step["frame_ms"] = max(16, min(2000, int(round(fm))))
                                    hs = parse_float(step_fields.get("hold_last_sec"), None)
                                    if hs is not None:
                                        new_step["hold_last_sec"] = max(0.0, min(120.0, float(hs)))
                                    adv = (step_fields.get("advance") or "continue").strip().lower()
                                    if adv in ("continue", "stop"):
                                        new_step["advance"] = adv
                            elif t == "EVT_STOP_BEGIN":
                                act = (step_fields.get("action") or "end").strip().lower()
                                if act in ("end", "break_loop", "lock"):
                                    new_step["action"] = act
                            elif t == "EVT_STOP_END":
                                pass
                            elif t in ("WAIT", "INTERVAL"):
                                v = parse_float(step_fields.get("val"), 0)
                                new_step["val"] = v
                            elif t == "ZOOM":
                                built = build_step_from_editor_fields(step_fields, t)
                                if built:
                                    new_step = built
                            elif t in ("FADEIN", "FADEOUT", "PLAYER_VISIBLE", "CURSOR_VISIBLE"):
                                v = parse_float(step_fields.get("val"), 0)
                                new_step["val"] = v
                            elif t == "FOLLOW_START":
                                fol = (step_fields.get("follower") or "").strip()
                                lea = (step_fields.get("leader") or "").strip()
                                if fol:
                                    new_step["follower"] = fol
                                if lea:
                                    new_step["leader"] = lea
                                d = parse_float(step_fields.get("dist"), None)
                                if d is not None:
                                    new_step["dist"] = d
                                sp = parse_float(step_fields.get("speed"), None)
                                if sp is not None:
                                    new_step["speed"] = sp
                            elif t == "FOLLOW_STOP":
                                fol = (step_fields.get("follower") or "").strip()
                                if fol:
                                    new_step["follower"] = fol
                            elif t == "EFFECT":
                                if step_fields.get("name"):
                                    new_step["name"] = step_fields.get("name")
                                if step_fields.get("target"):
                                    new_step["target"] = step_fields.get("target")
                                if step_fields.get("anchor"):
                                    new_step["anchor"] = step_fields.get("anchor")
                                p = pos_pair()
                                if p is not None:
                                    new_step["pos"] = p
                                b = parse_bool(step_fields.get("loop"))
                                if b is not None:
                                    new_step["loop"] = b
                                if step_fields.get("action"):
                                    new_step["action"] = step_fields.get("action")
                            elif t == "ANIM_ONCE":
                                if step_fields.get("name"):
                                    new_step["name"] = step_fields.get("name")
                                p = pos_pair()
                                if p is not None:
                                    new_step["pos"] = p
                            elif t == "CARRY":
                                act = (step_fields.get("action") or "pick").strip().lower()
                                if act:
                                    new_step["action"] = act
                                h = (step_fields.get("holder") or "").strip()
                                if h:
                                    new_step["holder"] = h
                                tg = (step_fields.get("target") or "").strip()
                                if tg:
                                    new_step["target"] = tg
                                p = pos_pair()
                                if p is not None:
                                    new_step["pos"] = p
                                bw = parse_bool(step_fields.get("wait"))
                                if bw is not None:
                                    new_step["wait"] = bw
                            elif t == "CHANGE":
                                tg = (step_fields.get("target") or "").strip()
                                if tg:
                                    new_step["target"] = tg
                                to_k = (step_fields.get("to") or "").strip()
                                if to_k:
                                    new_step["to"] = to_k
                                fd = (step_fields.get("fade") or "").strip()
                                if fd:
                                    try:
                                        fv = float(fd)
                                        if fv > 0:
                                            new_step["fade"] = fv
                                    except ValueError:
                                        pass
                            elif t == "CONDITION":
                                cond = (step_fields.get("condition") or "").strip()
                                var = (step_fields.get("var") or "").strip()
                                op = (step_fields.get("op") or "").strip()
                                if cond:
                                    new_step["condition"] = cond
                                elif var and op:
                                    new_step["var"] = var
                                    new_step["op"] = op
                            elif t == "CONDITION_SKIP":
                                pass
                            elif t == "SCREEN":
                                if step_fields.get("picture"):
                                    new_step["picture"] = step_fields.get("picture")
                                if step_fields.get("music"):
                                    new_step["music"] = step_fields.get("music")
                                if step_fields.get("transition"):
                                    new_step["transition"] = step_fields.get("transition")
                                if step_fields.get("text"):
                                    new_step["text"] = step_fields.get("text")
                                b = parse_bool(step_fields.get("auto"))
                                if b is not None:
                                    new_step["auto"] = b
                                v = parse_float(step_fields.get("val"), None)
                                if v is not None:
                                    new_step["val"] = v
                                if step_fields.get("action"):
                                    new_step["action"] = step_fields.get("action")
                            elif t == "MUSIC_PLAY":
                                if step_fields.get("music"):
                                    new_step["music"] = step_fields.get("music")
                                fi = parse_float(step_fields.get("fade_in"), None)
                                if fi is not None:
                                    new_step["fade_in"] = fi
                                b = parse_bool(step_fields.get("loop"))
                                if b is not None:
                                    new_step["loop"] = b
                                bq = parse_bool(step_fields.get("queue"))
                                if bq is not None:
                                    new_step["queue"] = bq
                                vol = parse_float(step_fields.get("volume"), None)
                                if vol is not None:
                                    new_step["volume"] = vol
                            elif t == "MUSIC_STOP":
                                fo = parse_float(step_fields.get("fade_out"), None)
                                if fo is not None:
                                    new_step["fade_out"] = fo
                            elif t in ("MUSIC_END", "MUSIC_PAUSE", "MUSIC_RESUME"):
                                pass
                            elif t == "TILT":
                                built = build_step_from_editor_fields(step_fields, t)
                                if built:
                                    new_step = built
                            elif t == "SHEAR":
                                built = build_step_from_editor_fields(step_fields, t)
                                if built:
                                    new_step = built
                            elif t == "FX":
                                if step_fields.get("fx_kind"):
                                    new_step["kind"] = str(step_fields.get("fx_kind"))
                                bo = parse_bool(step_fields.get("fx_on"))
                                new_step["on"] = True if bo is None else bo
                                if step_fields.get("fx_dir"):
                                    new_step["dir"] = str(step_fields.get("fx_dir"))
                                sp = parse_float(step_fields.get("fx_speed"), None)
                                if sp is not None:
                                    new_step["speed"] = float(sp)
                                fr = parse_float(step_fields.get("fx_freq"), None)
                                if fr is not None:
                                    new_step["freq"] = float(fr)
                                gc = parse_float(step_fields.get("fx_grid_cell"), None)
                                if gc is not None:
                                    new_step["grid_cell"] = float(gc)
                                gj = parse_float(step_fields.get("fx_grid_jitter"), None)
                                if gj is not None:
                                    new_step["grid_jitter"] = float(gj)
                                gm = parse_float(step_fields.get("fx_grid_max"), None)
                                if gm is not None:
                                    new_step["grid_max"] = int(gm)
                            elif t == "OVERLAY_UI":
                                act = (step_fields.get("action") or "show").strip().lower()
                                new_step["action"] = act
                                dl = parse_float(step_fields.get("delay"), None)
                                if dl is not None and float(dl) > 0.0:
                                    new_step["delay"] = float(dl)
                                if act == "remove":
                                    oid = (step_fields.get("overlay_id") or "").strip()
                                    if oid:
                                        new_step["overlay_id"] = oid
                                    di = parse_float(step_fields.get("disappear"), None)
                                    if di is not None:
                                        new_step["disappear"] = float(di)
                                else:
                                    new_step["content"] = (step_fields.get("content") or "text").strip().lower()
                                    if new_step["content"] == "image":
                                        ob = (step_fields.get("object") or "").strip()
                                        if ob:
                                            new_step["object"] = ob
                                    else:
                                        new_step["text"] = step_fields.get("text") or ""
                                        fk = (step_fields.get("font") or "default").strip()
                                        if fk:
                                            new_step["font"] = fk
                                        sz = parse_float(step_fields.get("size"), None)
                                        if sz is not None:
                                            new_step["size"] = int(sz)
                                        col = (step_fields.get("color") or "").strip()
                                        if col:
                                            new_step["color"] = col
                                    oid = (step_fields.get("overlay_id") or "").strip()
                                    if oid:
                                        new_step["overlay_id"] = oid
                                    new_step["anchor"] = (step_fields.get("anchor") or "center").strip()
                                    mxx = parse_float(step_fields.get("margin_x"), None)
                                    myy = parse_float(step_fields.get("margin_y"), None)
                                    if mxx is not None:
                                        new_step["margin_x"] = int(mxx)
                                    if myy is not None:
                                        new_step["margin_y"] = int(myy)
                                    new_step["mode"] = (step_fields.get("mode") or "fade").strip().lower()
                                    new_step["scroll_enter"] = (step_fields.get("scroll_enter") or "left").strip().lower()
                                    ap = parse_float(step_fields.get("appear"), None)
                                    if ap is not None:
                                        new_step["appear"] = float(ap)
                                    ho = parse_float(step_fields.get("hold"), None)
                                    if ho is not None:
                                        new_step["hold"] = float(ho)
                                    di = parse_float(step_fields.get("disappear"), None)
                                    if di is not None:
                                        new_step["disappear"] = float(di)
                                    if parse_bool(step_fields.get("hold_forever")) is True:
                                        new_step["hold_forever"] = True
                                    if parse_bool(step_fields.get("persist")) is True:
                                        new_step["persist"] = True
                            elif t == "CALL_EVENT":
                                tg = (step_fields.get("target") or "").strip()
                                if tg:
                                    new_step["target"] = tg
                            elif t == "DEV_CMD":
                                dc = (step_fields.get("dev_cmd") or "").strip()
                                if dc:
                                    new_step["cmd"] = dc
                            elif t == "CAMERA":
                                if step_fields.get("cam_mode"):
                                    new_step["mode"] = str(step_fields.get("cam_mode")).strip()
                                cs = (step_fields.get("cam_slot") or "").strip()
                                if cs:
                                    new_step["slot"] = cs
                                if step_fields.get("cam_target"):
                                    new_step["target"] = str(step_fields.get("cam_target")).strip()
                                cx = parse_float(step_fields.get("cam_x"), None)
                                cy = parse_float(step_fields.get("cam_y"), None)
                                if cx is not None:
                                    new_step["x"] = float(cx)
                                if cy is not None:
                                    new_step["y"] = float(cy)
                                bs = parse_bool(step_fields.get("cam_smooth"))
                                if bs is not None:
                                    new_step["smooth"] = bs
                                cd = parse_float(step_fields.get("cam_duration_sec"), None)
                                if cd is not None:
                                    new_step["duration_sec"] = max(0.0, float(cd))
                                cl = parse_float(step_fields.get("cam_lerp"), None)
                                if cl is not None:
                                    new_step["lerp"] = float(cl)

                            steps = all_events[current_event_type][current_event_id].setdefault("steps", [])
                            if step_edit_index is not None and 0 <= step_edit_index < len(steps):
                                steps[step_edit_index] = new_step
                            else:
                                if step_insert_index is None:
                                    steps.append(new_step)
                                else:
                                    steps.insert(max(0, min(len(steps), step_insert_index)), new_step)

                            flow.save_events(all_events)

                        show_step_config = False
                        step_edit_index = None
                        step_insert_index = None
                        active_step_field = None
                        step_type_dropdown_open = False
                        step_target_dropdown_open = False
                        show_step_delete_confirm = False
                        continue

                    if canc_btn.collidepoint(event.pos):
                        show_step_config = False
                        step_edit_index = None
                        step_insert_index = None
                        active_step_field = None
                        step_type_dropdown_open = False
                        step_target_dropdown_open = False
                        show_step_delete_confirm = False
                        continue

                if event.type == pygame.MOUSEMOTION and dd_drag_kind and show_step_config:
                    if dd_drag_kind == "type" and step_type_dd_ui:
                        sp = _editor_scroll_px_from_sb_my(event.pos[1], step_type_dd_ui)
                        if sp is not None:
                            step_type_scroll = sp
                    elif dd_drag_kind == "target" and step_target_dd_ui:
                        sp = _editor_scroll_px_from_sb_my(event.pos[1], step_target_dd_ui)
                        if sp is not None:
                            step_target_scroll = sp
                    elif dd_drag_kind == "step_body":
                        panel_r = _step_settings_panel_rect(SCREEN_W, SCREEN_H, step_fields)
                        rows_ov = _step_field_rows(step_fields.get("type", "MOVE"))
                        b_r, s_r, _mx, ch0 = _step_overlay_body_geometry(panel_r, rows_ov)
                        ui_b = _step_overlay_scrollbar_layout(s_r, b_r.height, ch0, step_body_scroll)
                        sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_b)
                        if sp is not None:
                            step_body_scroll = sp

                if event.type == pygame.MOUSEBUTTONUP and dd_drag_kind:
                    dd_drag_kind = None
                    continue

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if show_step_delete_confirm:
                            show_step_delete_confirm = False
                        elif step_target_dropdown_open:
                            step_target_dropdown_open = False
                        else:
                            show_step_config = False
                            step_edit_index = None
                            step_insert_index = None
                            active_step_field = None
                            step_type_dropdown_open = False
                            step_target_dropdown_open = False
                    elif active_step_field:
                        if event.key == pygame.K_BACKSPACE:
                            step_fields[active_step_field] = (step_fields.get(active_step_field, "")[:-1])
                        elif event.key == pygame.K_RETURN:
                            active_step_field = None
                continue














            if event.type == pygame.VIDEORESIZE:
                # 창의 너비와 높이 업데이트
                SCREEN_W, SCREEN_H = event.w, event.h
                screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)

                # 핵심: 중앙 작업창 너비·높이 재계산 (양쪽 사이드바 너비는 고정)
                map_area_w = SCREEN_W - sidebar_w - right_sidebar_w
                map_view_h = _editor_map_view_h(SCREEN_H, TOP_BAR_H)
            

















            if event.type == pygame.MOUSEBUTTONDOWN:
                # 휠(버튼 4/5): 일부 환경에서 MOUSEWHEEL 대신 들어옴 → 스크롤만, 선택 없음
                if event.button in (4, 5) and my > TOP_BAR_H:
                    _wheel_dy = EDITOR_SIDEBAR_WHEEL_STEP if event.button == 4 else -EDITOR_SIDEBAR_WHEEL_STEP
                    if mx < sidebar_w:
                        _lt, _lch = _editor_left_list_metrics(
                            edit_mode,
                            map_tool,
                            map_id,
                            objs,
                            npcs,
                            flow,
                            all_events,
                            LINE_H,
                            TOP_BAR_H,
                            EVENT_LIST_START_Y,
                            left_placed_collapsed,
                            flow_entity_entries=flow_entity_entries,
                            flow_placed_collapsed=flow_placed_collapsed,
                        )
                        scroll_y_left = _sidebar_scroll_clamp(
                            scroll_y_left + _wheel_dy, _lch, _lt, sidebar_list_bottom
                        )
                        continue
                    if mx > SCREEN_W - right_panel_w:
                        if edit_mode == "MAP":
                            _rt = _editor_right_map_list_top()
                            _rch = _editor_right_map_content_height(
                                categories, LINE_H, right_asset_collapsed
                            )
                            _vb_wheel = _editor_right_sidebar_view_bottom(
                                screen_h=SCREEN_H,
                                edit_mode=edit_mode,
                                map_tool=map_tool,
                                selected_nodes=selected_nodes,
                                sidebar_w=sidebar_w,
                                event_preview_sel=event_preview_sel,
                            )
                            scroll_y_right = _sidebar_scroll_clamp(
                                scroll_y_right + _wheel_dy, _rch, _rt, _vb_wheel
                            )
                        elif current_event_id and current_event_type:
                            _steps = all_events[current_event_type][current_event_id].get(
                                "steps", []
                            )
                            scroll_y_steps = _sidebar_scroll_clamp(
                                scroll_y_steps + _wheel_dy,
                                len(_steps) * LINE_H + 40,
                                EDITOR_RIGHT_STEPS_TOP,
                                sidebar_list_bottom,
                            )
                        continue

                # 좌·우 사이드바 스크롤바 (리스트 클릭보다 먼저)
                if (
                    event.button == 1
                    and _editor_sidebar_list_tooltip_ok(
                        show_event_config,
                        show_zone_config,
                        show_bgzone_config,
                        show_step_config,
                        show_multi_delete_confirm,
                    )
                    and my > TOP_BAR_H
                ):
                    if mx < sidebar_w:
                        _lt, _lch = _editor_left_list_metrics(
                            edit_mode,
                            map_tool,
                            map_id,
                            objs,
                            npcs,
                            flow,
                            all_events,
                            LINE_H,
                            TOP_BAR_H,
                            EVENT_LIST_START_Y,
                            left_placed_collapsed,
                            flow_entity_entries=flow_entity_entries,
                            flow_placed_collapsed=flow_placed_collapsed,
                        )
                        scroll_y_left = _sidebar_scroll_clamp(scroll_y_left, _lch, _lt, sidebar_list_bottom)
                        _sb = _sidebar_sb_rect(0, sidebar_w, _lt, sidebar_list_bottom)
                        _ui = _step_overlay_scrollbar_layout(
                            _sb, SCREEN_H - _lt, _lch, -scroll_y_left
                        )
                        if int(_ui.get("max_scroll") or 0) > 0:
                            _th, _tr = _ui.get("thumb"), _ui.get("track")
                            if (_th and _th.collidepoint(mx, my)) or (_tr and _tr.collidepoint(mx, my)):
                                sidebar_left_sb_drag = True
                                _ns = _sidebar_sb_scroll_from_my(my, _ui)
                                if _ns is not None:
                                    scroll_y_left = _ns
                                continue
                    elif mx > SCREEN_W - right_panel_w:
                        if edit_mode == "MAP":
                            _rt = _editor_right_map_list_top()
                            _rch = _editor_right_map_content_height(
                                categories, LINE_H, right_asset_collapsed
                            )
                            _vb_sb = _editor_right_sidebar_view_bottom(
                                screen_h=SCREEN_H,
                                edit_mode=edit_mode,
                                map_tool=map_tool,
                                selected_nodes=selected_nodes,
                                sidebar_w=sidebar_w,
                                event_preview_sel=event_preview_sel,
                            )
                            scroll_y_right = _sidebar_scroll_clamp(
                                scroll_y_right, _rch, _rt, _vb_sb
                            )
                            _sb = _sidebar_sb_rect(
                                SCREEN_W - right_panel_w, right_sidebar_w, _rt, _vb_sb
                            )
                            _ui = _step_overlay_scrollbar_layout(
                                _sb, _vb_sb - _rt, _rch, -scroll_y_right
                            )
                        elif current_event_id and current_event_type:
                            _steps = all_events[current_event_type][current_event_id].get("steps", [])
                            _rt, _rch = EDITOR_RIGHT_STEPS_TOP, len(_steps) * LINE_H + 40
                            scroll_y_steps = _sidebar_scroll_clamp(
                                scroll_y_steps, _rch, _rt, sidebar_list_bottom
                            )
                            _sb = _sidebar_sb_rect(
                                SCREEN_W - right_panel_w, right_sidebar_w, _rt, sidebar_list_bottom
                            )
                            _ui = _step_overlay_scrollbar_layout(
                                _sb, sidebar_list_bottom - _rt, _rch, -scroll_y_steps
                            )
                        else:
                            _ui = None
                        if _ui and int(_ui.get("max_scroll") or 0) > 0:
                            _th, _tr = _ui.get("thumb"), _ui.get("track")
                            if (_th and _th.collidepoint(mx, my)) or (_tr and _tr.collidepoint(mx, my)):
                                sidebar_right_sb_drag = True
                                _ns = _sidebar_sb_scroll_from_my(my, _ui)
                                if _ns is not None:
                                    if edit_mode == "MAP":
                                        scroll_y_right = _ns
                                    else:
                                        scroll_y_steps = _ns
                                continue

                # [1-1. 상단 모드 전환 바 클릭 — MAP / EVENT / FLOW]
                if event.button == 1 and 0 < my < TOP_BAR_H and 0 < mx < sidebar_w:
                    band = max(1, TOP_BAR_H // 3)
                    if my < band:
                        edit_mode = "MAP"
                    elif my < band * 2:
                        edit_mode = "EVENT"
                    else:
                        edit_mode = "FLOW"
                        flow_scroll_x = 0
                        flow_scroll_y = 0
                        scroll_y_left = 0
                        _flow_refresh_entity_list()

                # [FLOW] 뒤로 가기·차트 노드 클릭 (좌측 변수 리스트는 아래 [2]에서 처리)
                elif (
                    event.button == 1
                    and edit_mode == "FLOW"
                    and (
                        (flow_back_btn is not None and flow_back_btn.collidepoint(mx, my))
                        or (
                            sidebar_w < mx < SCREEN_W - right_panel_w
                            and my > TOP_BAR_H
                        )
                    )
                ):
                    if (
                        flow_back_btn is not None
                        and flow_back_btn.collidepoint(mx, my)
                    ):
                        show_event_config = False
                        show_zone_config = False
                        show_bgzone_config = False
                        show_step_config = False
                        close_all_char_modals()
                        flow_opened_settings = False
                        continue
                    if sidebar_w < mx < SCREEN_W - right_panel_w and my > TOP_BAR_H:
                        flow_lx = mx - sidebar_w + flow_scroll_x
                        flow_ly = my - TOP_BAR_H + flow_scroll_y
                        for hb in flow_hit_boxes:
                            if not hb.get("rect") or not hb["rect"].collidepoint(flow_lx, flow_ly):
                                continue
                            flow_opened_settings = True
                            act = hb.get("action")
                            if act == "event":
                                eid = str(hb.get("event_id") or "")
                                sec = str(hb.get("section") or "")
                                if not sec:
                                    for cat in EDITOR_EVENT_SECTIONS:
                                        if eid in all_events.get(cat, {}):
                                            sec = cat
                                            break
                                if sec and eid in all_events.get(sec, {}):
                                    edata = all_events[sec][eid]
                                    show_event_config = True
                                    event_modal_scroll = 0
                                    event_modal_dd_open = False
                                    config_target_id = eid
                                    input_fields = _editor_fill_event_settings_from_edata(
                                        sec, eid, edata
                                    )
                                    current_event_id = eid
                                    current_event_type = sec
                            elif act == "entity":
                                ent = str(hb.get("entity") or "")
                                _editor_flow_open_entity_modal(
                                    ent,
                                    hb.get("entity_kind"),
                                    on_map=bool(hb.get("on_map")),
                                    objs=objs,
                                    npcs=npcs,
                                )
                            elif act == "binding":
                                ent = str(hb.get("entity") or "")
                                _editor_flow_open_entity_modal(
                                    ent,
                                    hb.get("entity_kind"),
                                    on_map=bool(hb.get("on_map")),
                                    objs=objs,
                                    npcs=npcs,
                                )
                            elif act == "zone":
                                zi = hb.get("zone_index")
                                if zi is not None:
                                    _open_zone_config_at(zi)
                            break
                        continue

                # [1. 상단 맵 바 클릭]
                elif event.button == 1 and 0 < my < TOP_BAR_H and sidebar_w < mx < SCREEN_W - right_panel_w:
                    if export_map_btn.collidepoint(mx, my):
                        trigger_map_png_export()
                        continue
                    map_idx = (mx - sidebar_w - 10) // 112
                    if 0 <= map_idx < len(map_list):
                        cur_idx = map_idx
                        map_id, bg, mask, player, objs, npcs = flow.load_map(save_data={"current_map": map_list[cur_idx]})
                        scaled_cache.clear()
                        # 맵 변경 시에도 작업창에 꽉 차도록 줌 재계산 + 카메라 중앙
                        bg_w, bg_h = bg.get_width(), bg.get_height()
                        map_area_w = SCREEN_W - sidebar_w - right_sidebar_w
                        view_h = max(1, map_view_h)
                        fit_zoom = min(map_area_w / max(1, bg_w), view_h / max(1, bg_h))
                        fit_zoom = max(min(fit_zoom, max(zoom_steps)), min(zoom_steps))
                        zoom_idx = min(range(len(zoom_steps)), key=lambda i: abs(zoom_steps[i] - fit_zoom))
                        zoom_level = zoom_steps[zoom_idx]
                        cam_x = bg_w / 2
                        cam_y = bg_h / 2
                        _flow_refresh_entity_list()
                # [2. 좌측 리스트 클릭] (왼쪽 버튼만 — 휠은 위에서 스크롤 전용 처리)
                elif event.button == 1 and mx < sidebar_w:
                    if edit_mode == "MAP":
                        # MAP 모드: OBJECTS / ZONES / BGZONES / PRESENCE 토글
                        tool_w = max(40, (sidebar_w - 40) // 4)
                        tool_btn_obj = pygame.Rect(8, left_list_tops["map_tools"], tool_w, 28)
                        tool_btn_zone = pygame.Rect(tool_btn_obj.right + 4, left_list_tops["map_tools"], tool_w, 28)
                        tool_btn_bgz = pygame.Rect(tool_btn_zone.right + 4, left_list_tops["map_tools"], tool_w, 28)
                        tool_btn_pres = pygame.Rect(tool_btn_bgz.right + 4, left_list_tops["map_tools"], tool_w, 28)
                        if tool_btn_obj.collidepoint(mx, my):
                            map_tool = "OBJECTS"
                            selected_zone_idx = None
                            is_zone_dragging = False
                            selected_bgzone_idx = None
                            is_bgzone_dragging = False
                            selected_presence_idx = None
                            is_presence_dragging = False
                            box_select_start = None
                            box_select_current = None
                            continue
                        if tool_btn_zone.collidepoint(mx, my):
                            map_tool = "ZONES"
                            selected_node = None
                            selected_asset = None
                            selected_nodes.clear()
                            selected_presence_idx = None
                            is_presence_dragging = False
                            box_select_start = None
                            box_select_current = None
                            continue
                        if tool_btn_bgz.collidepoint(mx, my):
                            map_tool = "BGZONES"
                            selected_node = None
                            selected_asset = None
                            selected_nodes.clear()
                            selected_zone_idx = None
                            is_zone_dragging = False
                            selected_presence_idx = None
                            is_presence_dragging = False
                            box_select_start = None
                            box_select_current = None
                            continue
                        if tool_btn_pres.collidepoint(mx, my):
                            map_tool = "PRESENCE"
                            selected_node = None
                            selected_asset = None
                            selected_nodes.clear()
                            selected_zone_idx = None
                            is_zone_dragging = False
                            selected_bgzone_idx = None
                            is_bgzone_dragging = False
                            box_select_start = None
                            box_select_current = None
                            continue

                        # MAP 모드: Add Event Box 버튼 클릭
                        add_zone_btn = pygame.Rect(8, left_list_tops["map_zone_btn"], sidebar_w - 16, 28)
                        if map_tool == "ZONES" and add_zone_btn.collidepoint(mx, my):
                            show_zone_config = True
                            zone_modal_scroll = 0
                            zone_modal_dd_open = False
                            zone_edit_idx = None
                            active_zone_field = None
                            zone_fields = {
                                "name": "",
                                "event_id": "",
                                "target": "",
                                "trigger": "contact_player",
                                "cond_mainprogress": "",
                                "cond_min_laugh_point": "",
                                "cond_opt": "",
                                "rect": None,
                            }
                            continue

                        # MAP 모드: Add BG Box 버튼 클릭
                        add_bgzone_btn = pygame.Rect(8, left_list_tops["map_bgzone_btn"], sidebar_w - 16, 28)
                        if map_tool == "BGZONES" and add_bgzone_btn.collidepoint(mx, my):
                            show_bgzone_config = True
                            bgzone_modal_scroll = 0
                            bgzone_modal_dd_open = False
                            bgzone_edit_idx = None
                            active_bgzone_field = None
                            bgzone_fields = {
                                "name": "",
                                "rect": None,
                                "layer": "-50",
                                "draw_only_when_tilt": "true",
                                "update_policy": "none",
                                "sort_policy": "none",
                                "cull_margin_px": "160",
                            }
                            continue

                        # MAP 모드: Add Presence Box 버튼 클릭
                        add_presence_btn = pygame.Rect(8, left_list_tops["map_presence_btn"], sidebar_w - 16, 28)
                        if map_tool == "PRESENCE" and add_presence_btn.collidepoint(mx, my):
                            presence_zone_modal.open_new()
                            continue

                        # MAP / ZONES: 현재 맵의 이벤트 박스 목록 클릭/뷰
                        if map_tool == "ZONES":
                            zones = flow.world_data.get(map_id, {}).get("event_zones", [])
                            list_start_y = left_list_tops["map_zones"]
                            idx = (my - list_start_y - scroll_y_left) // LINE_H
                            if 0 <= idx < len(zones):
                                row_y = list_start_y + (idx * LINE_H) + scroll_y_left
                                view_btn_rect = pygame.Rect(sidebar_w - 50, row_y + 2, 44, LINE_H - 6)
                                row_rect = pygame.Rect(8, row_y, sidebar_w - 58, LINE_H)

                                if view_btn_rect.collidepoint(mx, my):
                                    # 설정창 열기 (현재 zone → fields로 풀기)
                                    z = zones[idx]
                                    zone_edit_idx = idx
                                    show_zone_config = True
                                    zone_modal_scroll = 0
                                    zone_modal_dd_open = False
                                    active_zone_field = None
                                    zone_fields = _editor_zone_fields_from_zone_dict(z)
                                    selected_zone_idx = idx
                                    is_zone_dragging = False
                                elif row_rect.collidepoint(mx, my):
                                    selected_zone_idx = idx
                                    is_zone_dragging = False
                                continue

                        # MAP / BGZONES: 현재 맵의 배경 박스 목록 클릭/뷰
                        if map_tool == "BGZONES":
                            zones = flow.world_data.get(map_id, {}).get("bg_zones", [])
                            list_start_y = left_list_tops["map_bgzones"]
                            idx = (my - list_start_y - scroll_y_left) // LINE_H
                            if 0 <= idx < len(zones):
                                row_y = list_start_y + (idx * LINE_H) + scroll_y_left
                                view_btn_rect = pygame.Rect(sidebar_w - 50, row_y + 2, 44, LINE_H - 6)
                                row_rect = pygame.Rect(8, row_y, sidebar_w - 58, LINE_H)
                                if view_btn_rect.collidepoint(mx, my):
                                    z = zones[idx]
                                    bgzone_edit_idx = idx
                                    show_bgzone_config = True
                                    bgzone_modal_scroll = 0
                                    bgzone_modal_dd_open = False
                                    active_bgzone_field = None
                                    bgzone_fields = {
                                        "name": str(z.get("name", "") or ""),
                                        "rect": list(z.get("rect")) if isinstance(z.get("rect"), (list, tuple)) else None,
                                        "layer": str(z.get("layer", -50)),
                                        "draw_only_when_tilt": str(z.get("draw_only_when_tilt", True)).lower(),
                                        "update_policy": str(z.get("update_policy", "none") or "none"),
                                        "sort_policy": str(z.get("sort_policy", "none") or "none"),
                                        "cull_margin_px": str(z.get("cull_margin_px", 160)),
                                    }
                                    selected_bgzone_idx = idx
                                    is_bgzone_dragging = False
                                elif row_rect.collidepoint(mx, my):
                                    selected_bgzone_idx = idx
                                    is_bgzone_dragging = False
                                continue

                        # MAP / PRESENCE: 체류 박스 목록 클릭/뷰
                        if map_tool == "PRESENCE":
                            zones = flow.world_data.get(map_id, {}).get("presence_zones", [])
                            list_start_y = left_list_tops["map_presences"]
                            idx = (my - list_start_y - scroll_y_left) // LINE_H
                            if 0 <= idx < len(zones):
                                row_y = list_start_y + (idx * LINE_H) + scroll_y_left
                                view_btn_rect = pygame.Rect(sidebar_w - 50, row_y + 2, 44, LINE_H - 6)
                                row_rect = pygame.Rect(8, row_y, sidebar_w - 58, LINE_H)
                                if view_btn_rect.collidepoint(mx, my):
                                    z = zones[idx]
                                    presence_zone_modal.open_edit(z, idx)
                                    selected_presence_idx = idx
                                    is_presence_dragging = False
                                elif row_rect.collidepoint(mx, my):
                                    selected_presence_idx = idx
                                    is_presence_dragging = False
                                continue

                        # --- 맵 배치 오브젝트/캐릭터 리스트 선택 ---
                        if map_tool != "OBJECTS":
                            continue
                        list_start_y = left_list_tops["map_objects"]
                        idx = (my - list_start_y - scroll_y_left) // LINE_H
                        placed_rows = _editor_filter_collapsed_rows(
                            build_editor_placed_list_rows(objs, npcs),
                            left_placed_collapsed,
                        )
                        if 0 <= idx < len(placed_rows):
                            row_y = list_start_y + (idx * LINE_H) + scroll_y_left
                            row0 = placed_rows[idx]
                            if row0.get("kind") == "npc":
                                vb = pygame.Rect(sidebar_w - 50, row_y + 2, 44, LINE_H - 6)
                                if vb.collidepoint(mx, my):
                                    char_inst_modal.open(row0["node"])
                                    continue
                        row = _editor_list_row_at(placed_rows, idx)
                        if row:
                            if row["kind"] == "header":
                                key = row["label"]
                                _editor_toggle_collapsed(
                                    editor_ui_state,
                                    EDITOR_UI_COLLAPSE_MAP_LEFT,
                                    left_placed_collapsed,
                                    key,
                                )
                            else:
                                target = row["node"]
                                selected_node = target
                                selected_nodes = [target]
                                cam_x, cam_y = target.pos[0], target.pos[1]

                    elif edit_mode == "FLOW":
                        list_start_y = left_list_tops["flow"]
                        idx = (my - list_start_y - scroll_y_left) // LINE_H
                        placed_rows = _editor_filter_collapsed_rows(
                            _editor_flow_catalog_rows(flow.world_data, map_id),
                            flow_placed_collapsed,
                        )
                        row = _editor_list_row_at(placed_rows, idx)
                        if row:
                            if row["kind"] == "header":
                                key = row["label"]
                                _editor_toggle_collapsed(
                                    editor_ui_state,
                                    EDITOR_UI_COLLAPSE_FLOW_LEFT,
                                    flow_placed_collapsed,
                                    key,
                                )
                            elif row["kind"] in ("npc", "obj", "zone"):
                                for i, ent in enumerate(flow_entity_entries):
                                    if _editor_flow_row_matches_entry(row, ent):
                                        flow_selected_entity_idx = i
                                        break
                                flow_scroll_x = 0
                                flow_scroll_y = 0
                                _flow_rebuild_graph()

                    elif edit_mode == "EVENT":
                        add_rect_click = pygame.Rect(8, EVENT_ADD_Y, sidebar_w - 16, EVENT_ADD_H)
                        if add_rect_click.collidepoint(mx, my):
                            show_event_config = True
                            event_modal_scroll = 0
                            event_modal_dd_open = False
                            config_target_id = None
                            input_fields = {
                                "cat": "LOCAL",
                                "eid": "ev_",
                                "title": "",
                                "res_prog": "",
                                "res_opt": "",
                                "trigger": "auto",
                                "condition": "",
                                "priority": "100",
                                "work_map": "",
                                "escape_mode": "none",
                                "escape_action": "end",
                                "escape_key": "",
                                "escape_condition": "",
                            }
                        else:
                            y_ptr = EVENT_LIST_START_Y + scroll_y_left
                            for cat in EDITOR_EVENT_SECTIONS:
                                y_ptr += LINE_H
                                for eid, edata in _editor_sorted_events_in_section(
                                    all_events, map_id, cat
                                ):
                                    view_btn_rect = pygame.Rect(
                                        sidebar_w - 50, y_ptr + 2, 44, LINE_H - 6
                                    )
                                    row_rect = pygame.Rect(8, y_ptr, sidebar_w - 58, LINE_H)
                                    if view_btn_rect.collidepoint(mx, my):
                                        show_event_config = True
                                        event_modal_scroll = 0
                                        event_modal_dd_open = False
                                        config_target_id = eid
                                        rp, ro = _result_to_res_fields(edata)
                                        pr = edata.get("priority", 100)
                                        try:
                                            pr = int(pr)
                                        except (TypeError, ValueError):
                                            pr = 100
                                        em, ea, ek, ec = _escape_fields_from_edata(edata)
                                        input_fields = {
                                            "cat": cat,
                                            "eid": eid,
                                            "title": edata.get("title", eid),
                                            "res_prog": rp,
                                            "res_opt": ro,
                                            "trigger": str(edata.get("trigger") or "auto"),
                                            "condition": str(edata.get("condition") or ""),
                                            "priority": str(pr),
                                            "work_map": str(edata.get("work_map") or ""),
                                            "escape_mode": em,
                                            "escape_action": ea,
                                            "escape_key": ek,
                                            "escape_condition": ec,
                                        }
                                    elif row_rect.collidepoint(mx, my):
                                        current_event_id = eid
                                        current_event_type = cat
                                        selected_step_idx = -1
                                        event_preview_sel = None
                                        preview_map = _editor_event_preview_map(edata, map_list)
                                        if preview_map and map_id != preview_map:
                                            cur_idx = map_list.index(preview_map)
                                            map_id, bg, mask, player, objs, npcs = flow.load_map(
                                                save_data={"current_map": preview_map}
                                            )
                                            scaled_cache.clear()
                                            _flow_refresh_entity_list()
                                            print(f"Map Switched to: {preview_map} for Event: {eid}")
                                        print(f"Event Selected: {eid}")
                                    y_ptr += LINE_H

                # [3. 우측 사이드바 클릭]
                elif event.button == 1 and mx > SCREEN_W - right_panel_w:
                    if edit_mode == "MAP":
                        _tx = SCREEN_W - right_panel_w
                        _thumb_toggle_rect = pygame.Rect(_tx + 4, 6, right_sidebar_w - 8, 34)
                        if _thumb_toggle_rect.collidepoint(mx, my):
                            editor_smooth_sidebar_thumbs = not editor_smooth_sidebar_thumbs
                            sidebar_thumb_cache.clear()
                        else:
                            _rt_clk = _editor_right_map_list_top()
                            _vb_clk = _editor_right_sidebar_view_bottom(
                                screen_h=SCREEN_H,
                                edit_mode=edit_mode,
                                map_tool=map_tool,
                                selected_nodes=selected_nodes,
                                sidebar_w=sidebar_w,
                                event_preview_sel=event_preview_sel,
                            )
                            _panel_x = SCREEN_W - right_panel_w
                            found_asset = None
                            curr_y = 0
                            for line in _editor_right_map_lines(
                                categories, right_asset_collapsed
                            ):
                                row_y_abs = _rt_clk + scroll_y_right + curr_y
                                row_rect = pygame.Rect(
                                    _panel_x, row_y_abs, right_sidebar_w, LINE_H
                                )
                                if line["kind"] == "item":
                                    side_btn = _editor_right_map_side_btn_rect(
                                        _panel_x, right_sidebar_w, row_y_abs, LINE_H
                                    )
                                    if side_btn.collidepoint(mx, my):
                                        if line.get("cat") == "CHAR (NPC)":
                                            char_def_modal.open(line["name"])
                                        else:
                                            obj_def_modal.open(line["name"])
                                        found_asset = None
                                        break
                                if row_rect.collidepoint(mx, my) and row_y_abs < _vb_clk:
                                    if line["kind"] == "header":
                                        cat = line["cat"]
                                        _editor_toggle_collapsed(
                                            editor_ui_state,
                                            EDITOR_UI_COLLAPSE_MAP_RIGHT,
                                            right_asset_collapsed,
                                            cat,
                                        )
                                        break
                                    found_asset = line["name"]
                                    break
                                curr_y += LINE_H

                            if found_asset:
                                selected_asset = found_asset
                                selected_node = None
                                selected_nodes.clear()

                    elif edit_mode == "EVENT":
                        # --- 이벤트 모드: 스텝 선택 / View / Insert(+) / Add Step ---
                        if current_event_id and current_event_type:
                            base_x = SCREEN_W - right_panel_w
                            steps = all_events[current_event_type][current_event_id].get('steps', [])

                            # [+ ADD STEP] 버튼 클릭 (맨 아래)
                            add_step_rect = pygame.Rect(
                                base_x + 10,
                                EDITOR_RIGHT_STEPS_TOP + scroll_y_steps + (len(steps) * LINE_H) + 12,
                                120,
                                28,
                            )
                            if add_step_rect.collidepoint(mx, my):
                                show_step_config = True
                                step_body_scroll = 0
                                step_edit_index = None
                                step_insert_index = None
                                active_step_field = None
                                step_fields = {"type": "MOVE", "target": "", "pos_x": "", "pos_y": "", "waypoints": "", "dir": "left", "instant": "", "force": "", "speed": "", "wait": "", "move_sync": "", "appear": "", "who": "", "text": "", "voice": "", "auto": "", "val": "", "name": "", "anchor": "", "loop": "", "action": "", "picture": "", "music": "", "transition": "", "fade_in": "", "fade_out": "", "queue": "", "volume": "", "tilt_on": "", "tilt_strength": "", "tilt_duration_sec": "", "shear_on": "", "shear_strength": "", "shear_duration_sec": "", "shear_px": "", "zoom_on": "", "zoom_strength": "", "zoom_duration_sec": "", "fx_kind": "", "fx_on": "", "fx_dir": "", "fx_speed": "", "fx_freq": "", "fx_grid_cell": "", "fx_grid_jitter": "", "fx_grid_max": "", "dev_cmd": "", "cam_mode": "", "cam_slot": "", "cam_target": "", "cam_x": "", "cam_y": "", "cam_smooth": "", "cam_lerp": "", "sprite_tilt": "", "height": "", "ysort": "", "layer": "", "visible": "", "alpha": "", "move_anim": "", "anim": "", "mode": "once", "release": "idle", "bubble": "", "bubble_target": "", "emotion": "", "frame_ms": "", "hold_last_sec": "", "advance": "continue"}
                            else:
                                head_ins_rect = pygame.Rect(
                                    base_x + 10,
                                    EDITOR_RIGHT_STEPS_TOP + scroll_y_steps,
                                    18,
                                    18,
                                )
                                if not steps and head_ins_rect.collidepoint(mx, my):
                                    show_step_config = True
                                    step_body_scroll = 0
                                    step_edit_index = None
                                    step_insert_index = 0
                                    active_step_field = None
                                    step_fields = {"type": "MOVE", "target": "", "pos_x": "", "pos_y": "", "waypoints": "", "dir": "left", "instant": "", "force": "", "speed": "", "wait": "", "move_sync": "", "appear": "", "who": "", "text": "", "voice": "", "auto": "", "val": "", "name": "", "anchor": "", "loop": "", "action": "", "picture": "", "music": "", "transition": "", "fade_in": "", "fade_out": "", "queue": "", "volume": "", "tilt_on": "", "tilt_strength": "", "tilt_duration_sec": "", "shear_on": "", "shear_strength": "", "shear_duration_sec": "", "shear_px": "", "zoom_on": "", "zoom_strength": "", "zoom_duration_sec": "", "fx_kind": "", "fx_on": "", "fx_dir": "", "fx_speed": "", "fx_freq": "", "fx_grid_cell": "", "fx_grid_jitter": "", "fx_grid_max": "", "dev_cmd": "", "cam_mode": "", "cam_slot": "", "cam_target": "", "cam_x": "", "cam_y": "", "cam_smooth": "", "cam_lerp": "", "sprite_tilt": "", "height": "", "ysort": "", "layer": "", "visible": "", "alpha": "", "move_anim": "", "anim": "", "mode": "once", "release": "idle", "bubble": "", "bubble_target": "", "emotion": "", "frame_ms": "", "hold_last_sec": "", "advance": "continue"}
                                else:
                                    # 각 스텝 행 + View 버튼 + 삽입(+) 버튼
                                    for i, step in enumerate(steps):
                                        row_y = EDITOR_RIGHT_STEPS_TOP + scroll_y_steps + i * LINE_H
                                        view_rect = pygame.Rect(base_x + right_sidebar_w - 60, row_y + 2, 50, LINE_H - 6)
                                        row_rect = pygame.Rect(base_x + 10, row_y, right_sidebar_w - 72, LINE_H)
                                        insert_rect = pygame.Rect(base_x + 10, row_y - 12, 18, 18)

                                        if insert_rect.collidepoint(mx, my):
                                            show_step_config = True
                                            step_body_scroll = 0
                                            step_edit_index = None
                                            step_insert_index = i
                                            active_step_field = None
                                            step_fields = {"type": "MOVE", "target": "", "pos_x": "", "pos_y": "", "waypoints": "", "dir": "left", "instant": "", "force": "", "speed": "", "wait": "", "move_sync": "", "appear": "", "who": "", "text": "", "voice": "", "auto": "", "val": "", "name": "", "anchor": "", "loop": "", "action": "", "picture": "", "music": "", "transition": "", "fade_in": "", "fade_out": "", "queue": "", "volume": "", "tilt_on": "", "tilt_strength": "", "tilt_duration_sec": "", "shear_on": "", "shear_strength": "", "shear_duration_sec": "", "shear_px": "", "zoom_on": "", "zoom_strength": "", "zoom_duration_sec": "", "fx_kind": "", "fx_on": "", "fx_dir": "", "fx_speed": "", "fx_freq": "", "fx_grid_cell": "", "fx_grid_jitter": "", "fx_grid_max": "", "dev_cmd": "", "cam_mode": "", "cam_slot": "", "cam_target": "", "cam_x": "", "cam_y": "", "cam_smooth": "", "cam_lerp": "", "sprite_tilt": "", "height": "", "ysort": "", "layer": "", "visible": "", "alpha": "", "move_anim": "", "anim": "", "mode": "once", "release": "idle", "bubble": "", "bubble_target": "", "emotion": "", "frame_ms": "", "hold_last_sec": "", "advance": "continue"}
                                            break

                                        if view_rect.collidepoint(mx, my):
                                            # 수정 모달 열기 (현재 step → fields로 풀기)
                                            show_step_config = True
                                            step_body_scroll = 0
                                            step_edit_index = i
                                            step_insert_index = None
                                            active_step_field = None

                                            t_raw = (step.get("type") or "MOVE").upper()
                                            t = "DEV_CMD" if t_raw == "GLOBAL" else t_raw
                                            step_fields = {"type": t}
                                            step_fields["target"] = str(step.get("target", "") or "")
                                            step_fields["dir"] = str(step.get("dir", "") or "")
                                            step_fields["appear"] = str(step.get("appear", "") or "")
                                            step_fields["action"] = str(step.get("action", "") or "")
                                            step_fields["ysort"] = str(step.get("ysort", "") or "")
                                            step_fields["layer"] = str(step.get("layer", "") or "")
                                            step_fields["sprite_tilt"] = str(step.get("sprite_tilt", "") or "")
                                            step_fields["height"] = str(step.get("height", "") or "")
                                            step_fields["visible"] = str(step.get("visible", "") or "")
                                            step_fields["alpha"] = str(step.get("alpha", "") or "")
                                            p = step.get("pos")
                                            step_fields["waypoints"] = ""
                                            if isinstance(p, (list, tuple)) and len(p) >= 2:
                                                p0 = p[0]
                                                if isinstance(p0, (list, tuple)) and len(p0) >= 2:
                                                    step_fields["pos_x"] = str(p0[0])
                                                    step_fields["pos_y"] = str(p0[1])
                                                    extra = []
                                                    for sub in p[1:]:
                                                        if isinstance(sub, (list, tuple)) and len(sub) >= 2:
                                                            extra.append(f"{sub[0]},{sub[1]}")
                                                    step_fields["waypoints"] = ";".join(extra)
                                                else:
                                                    step_fields["pos_x"] = str(p[0])
                                                    step_fields["pos_y"] = str(p[1])
                                            else:
                                                step_fields["pos_x"] = ""
                                                step_fields["pos_y"] = ""
                                            step_fields["who"] = str(step.get("who", "") or "")
                                            step_fields["text"] = str(step.get("text", "") or "")
                                            step_fields["voice"] = str(step.get("voice", "") or "")
                                            step_fields["auto"] = str(step.get("auto", "") or "")
                                            step_fields["bubble"] = str(step.get("bubble", "") or "")
                                            step_fields["bubble_target"] = str(step.get("bubble_target", "") or "")
                                            step_fields["emotion"] = str(step.get("emotion", "") or "")
                                            step_fields["frame_ms"] = str(step.get("frame_ms", "") or "")
                                            step_fields["hold_last_sec"] = str(step.get("hold_last_sec", "") or "")
                                            step_fields["advance"] = str(step.get("advance", "") or "")
                                            step_fields["val"] = str(step.get("val", "") or "")
                                            step_fields["name"] = str(step.get("name", "") or "")
                                            step_fields["anchor"] = str(step.get("anchor", "") or "")
                                            step_fields["loop"] = str(step.get("loop", "") or "")
                                            step_fields["picture"] = str(step.get("picture", "") or "")
                                            step_fields["music"] = str(step.get("music", "") or "")
                                            step_fields["transition"] = str(step.get("transition", "") or "")
                                            step_fields["fade_in"] = str(step.get("fade_in", "") or "")
                                            step_fields["fade_out"] = str(step.get("fade_out", "") or "")
                                            step_fields["queue"] = str(step.get("queue", "") or "")
                                            step_fields["volume"] = str(step.get("volume", "") or "")
                                            step_fields["speed"] = str(step.get("speed", "") or "")
                                            step_fields["wait"] = str(step.get("wait", "") or "")
                                            step_fields["move_sync"] = str(step.get("move_sync") or step.get("sync") or "")
                                            ins = step.get("instant")
                                            if isinstance(ins, bool):
                                                step_fields["instant"] = "true" if ins else ""
                                            else:
                                                step_fields["instant"] = str(ins or "")
                                            if t in ("TILT", "SHEAR", "ZOOM"):
                                                fill_editor_fields_from_step(step_fields, step, t)
                                            elif t == "FX":
                                                step_fields["fx_kind"] = str(step.get("kind", "") or "")
                                                step_fields["fx_on"] = str(step.get("on", True))
                                                step_fields["fx_dir"] = str(step.get("dir", "") or "")
                                                sp = step.get("speed")
                                                step_fields["fx_speed"] = "" if sp is None else str(sp)
                                                fr = step.get("freq", step.get("frequency"))
                                                step_fields["fx_freq"] = "" if fr is None else str(fr)
                                                gc = step.get("grid_cell")
                                                step_fields["fx_grid_cell"] = "" if gc is None else str(gc)
                                                gj = step.get("grid_jitter")
                                                step_fields["fx_grid_jitter"] = "" if gj is None else str(gj)
                                                gm = step.get("grid_max")
                                                step_fields["fx_grid_max"] = "" if gm is None else str(gm)
                                            elif t == "OVERLAY_UI":
                                                step_fields["action"] = str(step.get("action") or "show")
                                                step_fields["delay"] = (
                                                    "" if step.get("delay") is None else str(step.get("delay"))
                                                )
                                                step_fields["overlay_id"] = str(step.get("overlay_id") or "")
                                                step_fields["content"] = str(step.get("content") or "text")
                                                step_fields["text"] = str(step.get("text") or "")
                                                step_fields["font"] = str(step.get("font") or "default")
                                                step_fields["size"] = "" if step.get("size") is None else str(step.get("size"))
                                                c = step.get("color")
                                                if isinstance(c, (list, tuple)) and len(c) >= 3:
                                                    step_fields["color"] = f"{c[0]},{c[1]},{c[2]}"
                                                else:
                                                    step_fields["color"] = str(step.get("color") or "255,255,255")
                                                step_fields["object"] = str(step.get("object") or "")
                                                step_fields["anchor"] = str(step.get("anchor") or "center")
                                                step_fields["margin_x"] = (
                                                    "" if step.get("margin_x") is None else str(step.get("margin_x"))
                                                )
                                                step_fields["margin_y"] = (
                                                    "" if step.get("margin_y") is None else str(step.get("margin_y"))
                                                )
                                                step_fields["mode"] = str(step.get("mode") or "fade")
                                                step_fields["scroll_enter"] = str(step.get("scroll_enter") or "left")
                                                step_fields["appear"] = (
                                                    "" if step.get("appear") is None else str(step.get("appear"))
                                                )
                                                step_fields["hold"] = "" if step.get("hold") is None else str(step.get("hold"))
                                                step_fields["disappear"] = (
                                                    "" if step.get("disappear") is None else str(step.get("disappear"))
                                                )
                                                step_fields["hold_forever"] = (
                                                    "true" if step.get("hold_forever") else ""
                                                )
                                                step_fields["persist"] = "true" if step.get("persist") else ""
                                            elif t == "DEV_CMD":
                                                step_fields["dev_cmd"] = str(
                                                    step.get("cmd") or step.get("command") or step.get("action", "") or ""
                                                )
                                            elif t == "CAMERA":
                                                fill_editor_fields_from_step(step_fields, step, t)
                                            elif t == "ACTION_ANIM":
                                                step_fields["anim"] = str(
                                                    step.get("anim") or step.get("name") or step.get("state") or ""
                                                )
                                                step_fields["mode"] = str(step.get("mode") or "once")
                                                step_fields["release"] = str(step.get("release") or "idle")
                                            elif t == "CARRY":
                                                step_fields["action"] = str(step.get("action") or "pick")
                                                step_fields["holder"] = str(step.get("holder") or "player")
                                                step_fields["target"] = str(step.get("target") or "")
                                                pos = step.get("pos")
                                                if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                                                    step_fields["pos_x"] = str(pos[0])
                                                    step_fields["pos_y"] = str(pos[1])
                                                else:
                                                    step_fields["pos_x"] = ""
                                                    step_fields["pos_y"] = ""
                                                w = step.get("wait")
                                                step_fields["wait"] = (
                                                    "false"
                                                    if w is False
                                                    or (
                                                        isinstance(w, str)
                                                        and w.strip().lower() in ("0", "false", "f", "no", "n", "off")
                                                    )
                                                    else "true"
                                                )
                                            elif t == "CHANGE":
                                                step_fields["target"] = str(step.get("target") or "held")
                                                step_fields["to"] = str(
                                                    step.get("to") or step.get("new_name") or ""
                                                )
                                                _fd = step.get("fade", step.get("fade_sec"))
                                                step_fields["fade"] = "" if _fd in (None, "") else str(_fd)
                                            elif t == "CONDITION":
                                                step_fields["condition"] = str(
                                                    step.get("condition") or step.get("expr") or ""
                                                )
                                                step_fields["var"] = str(step.get("var") or "")
                                                step_fields["op"] = str(step.get("op") or "")
                                            elif t == "CONDITION_SKIP":
                                                pass
                                            step_fields["move_anim"] = str(
                                                step.get("move_anim") or step.get("path_anim") or ""
                                            )
                                            break

                                        if row_rect.collidepoint(mx, my):
                                            selected_step_idx = i
                                            print(f"Selected Step: {i}")
                                            break

                # [4. 중앙 작업창 클릭]
                else:
                    in_map_area = (sidebar_w < mx < SCREEN_W - right_panel_w) and (my > TOP_BAR_H)
                    if event.type == pygame.MOUSEBUTTONDOWN and in_map_area and event.button == 3:
                        if edit_mode == "FLOW":
                            flow_panning = True
                            flow_pan_last = (mx, my)
                        else:
                            is_panning = True
                            last_m = (mx, my)
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:  # 왼쪽 클릭
                        if edit_mode == "EVENT" and in_map_area:
                            if current_event_id and current_event_type:
                                steps_pv = all_events[current_event_type][current_event_id].get(
                                    "steps", []
                                )
                                upto_pv = _preview_upto_index(
                                    show_step_config,
                                    step_edit_index,
                                    step_insert_index,
                                    steps_pv,
                                    selected_step_idx,
                                )
                                pick = _editor_event_preview_pick_at_screen(
                                    mx,
                                    my,
                                    sidebar_w=sidebar_w,
                                    top_bar_h=TOP_BAR_H,
                                    steps=steps_pv,
                                    upto_inclusive=upto_pv,
                                    player=player,
                                    objs=objs,
                                    npcs=npcs,
                                    cam_x=cam_x,
                                    cam_y=cam_y,
                                    zoom_level=zoom_level,
                                    bg_w=bg.get_width(),
                                    bg_h=bg.get_height(),
                                    map_area_w=map_area_w,
                                    view_h=map_view_h,
                                    preview_sprite_cache=preview_sprite_cache,
                                    scaled_cache=scaled_cache,
                                )
                                if pick:
                                    now_pick = int(pygame.time.get_ticks())
                                    if (
                                        pick == event_preview_pick_name
                                        and (now_pick - int(event_preview_pick_ms)) <= 380
                                    ):
                                        _editor_open_interact_type_modal(pick)
                                    event_preview_sel = pick
                                    event_preview_pick_name = pick
                                    event_preview_pick_ms = now_pick
                                else:
                                    event_preview_sel = None
                                    event_preview_pick_name = None

                        elif edit_mode == "FLOW":
                            pass

                        elif edit_mode == "MAP" and in_map_area:
                            # MAP / ZONES: 이벤트 박스 선택/드래그
                            if map_tool == "ZONES":
                                zones = flow.world_data.get(map_id, {}).get("event_zones", [])

                                # 1) 이미 선택된 zone이 있고, 그 위를 다시 눌렀으면 드래그 시작
                                if selected_zone_idx is not None and 0 <= selected_zone_idx < len(zones):
                                    zx, zy, zw, zh = zones[selected_zone_idx].get("rect", [0, 0, 0, 0])
                                    if zx <= wx <= zx + zw and zy <= wy <= zy + zh:
                                        is_zone_dragging = True
                                        zone_drag_offset = (wx - zx, wy - zy)
                                        continue

                                # 2) 새로 선택 (위에 있는 박스 우선: 뒤에서부터)
                                found_idx = None
                                for i in range(len(zones) - 1, -1, -1):
                                    zx, zy, zw, zh = zones[i].get("rect", [0, 0, 0, 0])
                                    if zw <= 0 or zh <= 0:
                                        continue
                                    if zx <= wx <= zx + zw and zy <= wy <= zy + zh:
                                        found_idx = i
                                        break
                                selected_zone_idx = found_idx
                                is_zone_dragging = False
                                continue

                            # MAP / BGZONES: 배경 박스 선택/드래그
                            if map_tool == "BGZONES":
                                zones = flow.world_data.get(map_id, {}).get("bg_zones", [])
                                if selected_bgzone_idx is not None and 0 <= selected_bgzone_idx < len(zones):
                                    zx, zy, zw, zh = zones[selected_bgzone_idx].get("rect", [0, 0, 0, 0])
                                    if zx <= wx <= zx + zw and zy <= wy <= zy + zh:
                                        is_bgzone_dragging = True
                                        bgzone_drag_offset = (wx - zx, wy - zy)
                                        continue
                                found_idx = None
                                for i in range(len(zones) - 1, -1, -1):
                                    zx, zy, zw, zh = zones[i].get("rect", [0, 0, 0, 0])
                                    if zw <= 0 or zh <= 0:
                                        continue
                                    if zx <= wx <= zx + zw and zy <= wy <= zy + zh:
                                        found_idx = i
                                        break
                                selected_bgzone_idx = found_idx
                                is_bgzone_dragging = False
                                continue

                            # MAP / PRESENCE: 체류 박스 선택/드래그
                            if map_tool == "PRESENCE":
                                zones = flow.world_data.get(map_id, {}).get("presence_zones", [])
                                if selected_presence_idx is not None and 0 <= selected_presence_idx < len(zones):
                                    zx, zy, zw, zh = zones[selected_presence_idx].get("rect", [0, 0, 0, 0])
                                    if zx <= wx <= zx + zw and zy <= wy <= zy + zh:
                                        is_presence_dragging = True
                                        presence_drag_offset = (wx - zx, wy - zy)
                                        continue
                                found_idx = None
                                for i in range(len(zones) - 1, -1, -1):
                                    zx, zy, zw, zh = zones[i].get("rect", [0, 0, 0, 0])
                                    if zw <= 0 or zh <= 0:
                                        continue
                                    if zx <= wx <= zx + zw and zy <= wy <= zy + zh:
                                        found_idx = i
                                        break
                                selected_presence_idx = found_idx
                                is_presence_dragging = False
                                continue

                            if selected_asset:  # 배치하기 모드 (에셋 선택 중일 때)
                                if selected_asset in OBJ_ASSETS:
                                    objs.append(FieldItem(selected_asset, swx, swy))
                                else:
                                    from char_behavior import attach_npc_from_entry
                                    ch_info = {}
                                    if CHAR_ASSETS.get(selected_asset, {}).get("mask_nav"):
                                        ch = MaskWalkingCharacter(selected_asset, [swx, swy], ch_info)
                                    else:
                                        ch = BaseCharacter(selected_asset, [swx, swy], ch_info)
                                    attach_npc_from_entry(
                                        ch,
                                        {"name": selected_asset, "pos": [int(swx), int(swy)]},
                                    )
                                    npcs.append(ch)

                            elif map_tool == "OBJECTS":
                                hit = _editor_pick_top_node(objs, npcs, wx, wy)
                                if selected_nodes:
                                    if hit and hit in selected_nodes:
                                        is_dragging = True
                                        multi_drag_leader = hit
                                        multi_drag_anchor = (float(wx), float(wy))
                                        multi_drag_origins = {
                                            id(o): [float(o.pos[0]), float(o.pos[1])] for o in selected_nodes
                                        }
                                    elif hit and hit not in selected_nodes:
                                        selected_nodes = [hit]
                                        selected_node = hit
                                        selected_asset = None
                                        box_select_start = None
                                        box_select_current = None
                                    else:
                                        box_select_start = (wx, wy)
                                        box_select_current = (wx, wy)
                                else:
                                    if hit:
                                        selected_nodes = [hit]
                                        selected_node = hit
                                        selected_asset = None
                                    else:
                                        box_select_start = (wx, wy)
                                        box_select_current = (wx, wy)









            if event.type == pygame.MOUSEBUTTONUP:
                # [수정] 마우스를 떼도 selected_node는 유지 (ESC로 지우기 위해)
                # 드래그/팬 상태만 해제 (우클릭 팬은 3번 버튼 기준)
                if event.button == 1:
                    if box_select_start is not None:
                        if edit_mode == "MAP" and map_tool == "OBJECTS":
                            x1, y1 = box_select_start
                            x2, y2 = (
                                box_select_current
                                if box_select_current is not None
                                else box_select_start
                            )
                            picked = _editor_nodes_in_world_rect(objs, npcs, x1, y1, x2, y2)
                            if abs(x2 - x1) < 4 and abs(y2 - y1) < 4 and not picked:
                                obj_sprite_tilt_active = False
                                obj_height_active = False
                                obj_layer_active = False
                                selected_nodes.clear()
                                selected_node = None
                            elif picked:
                                selected_nodes = picked
                                selected_node = (
                                    selected_nodes[0] if len(selected_nodes) == 1 else None
                                )
                                selected_asset = None
                                if len(selected_nodes) != 1:
                                    obj_sprite_tilt_active = False
                                    obj_height_active = False
                                    obj_layer_active = False
                        box_select_start = None
                        box_select_current = None
                    is_dragging = False
                    is_zone_dragging = False
                    is_bgzone_dragging = False
                    multi_drag_leader = None
                    multi_drag_origins = None
                    multi_drag_anchor = None
                if event.button == 3:
                    is_panning = False
                    flow_panning = False

















            if event.type == pygame.MOUSEMOTION:
                if flow_panning and edit_mode == "FLOW":
                    flow_scroll_x -= mx - flow_pan_last[0]
                    flow_scroll_y -= my - flow_pan_last[1]
                    flow_pan_last = (mx, my)
                    _fcw, _fch = _editor_flow_diagram_content_size(
                        flow_graph, map_area_w
                    )
                    _fvh = max(1, map_view_h - 20)
                    flow_scroll_x = max(
                        0, min(max(0, _fcw - map_area_w), int(flow_scroll_x))
                    )
                    flow_scroll_y = max(
                        0, min(max(0, _fch - _fvh), int(flow_scroll_y))
                    )
                elif is_panning:
                    cam_x -= (mx - last_m[0]) / zoom_level
                    cam_y -= (my - last_m[1]) / zoom_level
                    last_m = (mx, my)
                
                # MAP / ZONES: 드래그 이동
                if edit_mode == "MAP" and map_tool == "ZONES" and is_zone_dragging and selected_zone_idx is not None:
                    zones = flow.world_data.get(map_id, {}).get("event_zones", [])
                    if 0 <= selected_zone_idx < len(zones):
                        r = zones[selected_zone_idx].get("rect", [0, 0, 0, 0])
                        if len(r) == 4:
                            nx = wx - zone_drag_offset[0]
                            ny = wy - zone_drag_offset[1]
                            if is_shift_pressed:
                                zx, zy = int(nx), int(ny)
                            else:
                                zx = (int(nx) // GRID_SIZE) * GRID_SIZE
                                zy = (int(ny) // GRID_SIZE) * GRID_SIZE
                            zones[selected_zone_idx]["rect"][0] = zx
                            zones[selected_zone_idx]["rect"][1] = zy
                    continue

                # MAP / BGZONES: 드래그 이동
                if edit_mode == "MAP" and map_tool == "BGZONES" and is_bgzone_dragging and selected_bgzone_idx is not None:
                    zones = flow.world_data.get(map_id, {}).get("bg_zones", [])
                    if 0 <= selected_bgzone_idx < len(zones):
                        r = zones[selected_bgzone_idx].get("rect", [0, 0, 0, 0])
                        if len(r) == 4:
                            nx = wx - bgzone_drag_offset[0]
                            ny = wy - bgzone_drag_offset[1]
                            if is_shift_pressed:
                                zx, zy = int(nx), int(ny)
                            else:
                                zx = (int(nx) // GRID_SIZE) * GRID_SIZE
                                zy = (int(ny) // GRID_SIZE) * GRID_SIZE
                            zones[selected_bgzone_idx]["rect"][0] = zx
                            zones[selected_bgzone_idx]["rect"][1] = zy
                    continue

                # MAP / PRESENCE: 드래그 이동
                if edit_mode == "MAP" and map_tool == "PRESENCE" and is_presence_dragging and selected_presence_idx is not None:
                    zones = flow.world_data.get(map_id, {}).get("presence_zones", [])
                    if 0 <= selected_presence_idx < len(zones):
                        r = zones[selected_presence_idx].get("rect", [0, 0, 0, 0])
                        if len(r) == 4:
                            nx = wx - presence_drag_offset[0]
                            ny = wy - presence_drag_offset[1]
                            if is_shift_pressed:
                                zx, zy = int(nx), int(ny)
                            else:
                                zx = (int(nx) // GRID_SIZE) * GRID_SIZE
                                zy = (int(ny) // GRID_SIZE) * GRID_SIZE
                            zones[selected_presence_idx]["rect"][0] = zx
                            zones[selected_presence_idx]["rect"][1] = zy
                    continue

                if (
                    selected_nodes
                    and is_dragging
                    and multi_drag_origins is not None
                    and multi_drag_leader is not None
                ):
                    lox, loy = multi_drag_origins[id(multi_drag_leader)]
                    if is_shift_pressed:
                        ltx, lty = float(wx), float(wy)
                    else:
                        ltx = float((int(wx) // GRID_SIZE) * GRID_SIZE)
                        lty = float((int(wy) // GRID_SIZE) * GRID_SIZE)
                    dx = ltx - lox
                    dy = lty - loy
                    for o in selected_nodes:
                        ox, oy = multi_drag_origins[id(o)]
                        nx, ny = int(round(ox + dx)), int(round(oy + dy))
                        o.pos = [nx, ny]
                        if hasattr(o, "origin_pos"):
                            o.origin_pos = [nx, ny]

                if (
                    box_select_start is not None
                    and pygame.mouse.get_pressed()[0]
                    and not is_dragging
                    and edit_mode == "MAP"
                    and map_tool == "OBJECTS"
                ):
                    box_select_current = (wx, wy)
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            if event.type == pygame.MOUSEMOTION and sidebar_left_sb_drag:
                _lt, _lch = _editor_left_list_metrics(
                    edit_mode,
                    map_tool,
                    map_id,
                    objs,
                    npcs,
                    flow,
                    all_events,
                    LINE_H,
                    TOP_BAR_H,
                    EVENT_LIST_START_Y,
                    left_placed_collapsed,
                    flow_entity_entries=flow_entity_entries,
                    flow_placed_collapsed=flow_placed_collapsed,
                )
                _sb = _sidebar_sb_rect(0, sidebar_w, _lt, sidebar_list_bottom)
                _ui = _step_overlay_scrollbar_layout(_sb, SCREEN_H - _lt, _lch, -scroll_y_left)
                _ns = _sidebar_sb_scroll_from_my(event.pos[1], _ui)
                if _ns is not None:
                    scroll_y_left = _ns
                continue

            if event.type == pygame.MOUSEMOTION and sidebar_right_sb_drag:
                if edit_mode == "MAP":
                    _rt, _rch = 45, _editor_right_map_content_height(
                        categories, LINE_H, right_asset_collapsed
                    )
                    _vb = _editor_right_sidebar_view_bottom(
                        screen_h=SCREEN_H,
                        edit_mode=edit_mode,
                        map_tool=map_tool,
                        selected_nodes=selected_nodes,
                        sidebar_w=sidebar_w,
                        event_preview_sel=event_preview_sel,
                    )
                    scroll_y_right = _sidebar_scroll_clamp(scroll_y_right, _rch, _rt, _vb)
                    _sb = _sidebar_sb_rect(SCREEN_W - right_panel_w, right_sidebar_w, _rt, _vb)
                    _ui = _step_overlay_scrollbar_layout(_sb, _vb - _rt, _rch, -scroll_y_right)
                    _ns = _sidebar_sb_scroll_from_my(event.pos[1], _ui)
                    if _ns is not None:
                        scroll_y_right = _ns
                elif current_event_id and current_event_type:
                    _steps = all_events[current_event_type][current_event_id].get("steps", [])
                    _rt, _rch, _vb = EDITOR_RIGHT_STEPS_TOP, len(_steps) * LINE_H + 40, sidebar_list_bottom
                    scroll_y_steps = _sidebar_scroll_clamp(scroll_y_steps, _rch, _rt, _vb)
                    _sb = _sidebar_sb_rect(SCREEN_W - right_panel_w, right_sidebar_w, _rt, _vb)
                    _ui = _step_overlay_scrollbar_layout(_sb, _vb - _rt, _rch, -scroll_y_steps)
                    _ns = _sidebar_sb_scroll_from_my(event.pos[1], _ui)
                    if _ns is not None:
                        scroll_y_steps = _ns
                continue

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if sidebar_left_sb_drag:
                    sidebar_left_sb_drag = False
                if sidebar_right_sb_drag:
                    sidebar_right_sb_drag = False

            if event.type == pygame.MOUSEWHEEL:
                if mx < sidebar_w: # 좌측 리스트 휠 (스크롤만)
                    scroll_y_left += event.y * EDITOR_SIDEBAR_WHEEL_STEP
                    _lt, _lch = _editor_left_list_metrics(
                        edit_mode,
                        map_tool,
                        map_id,
                        objs,
                        npcs,
                        flow,
                        all_events,
                        LINE_H,
                        TOP_BAR_H,
                        EVENT_LIST_START_Y,
                        left_placed_collapsed,
                        flow_entity_entries=flow_entity_entries,
                        flow_placed_collapsed=flow_placed_collapsed,
                    )
                    scroll_y_left = _sidebar_scroll_clamp(scroll_y_left, _lch, _lt, sidebar_list_bottom)
                    continue
                elif (
                    edit_mode == "FLOW"
                    and sidebar_w < mx < SCREEN_W - right_panel_w
                    and my > TOP_BAR_H
                ):
                    delta = _editor_wheel_delta(event, step=EDITOR_SIDEBAR_WHEEL_STEP)
                    cw, ch = _editor_flow_diagram_content_size(flow_graph, map_area_w)
                    vh = max(1, map_view_h - 20)
                    if is_shift_pressed:
                        flow_scroll_x = max(
                            0, min(max(0, cw - map_area_w), flow_scroll_x + delta)
                        )
                    else:
                        flow_scroll_y = max(
                            0, min(max(0, ch - vh), flow_scroll_y + delta)
                        )
                    continue
                elif mx > SCREEN_W - right_panel_w: # 우측 리스트 휠
                    if edit_mode == "MAP":
                        scroll_y_right += event.y * EDITOR_SIDEBAR_WHEEL_STEP
                        _rt, _rch = 45, _editor_right_map_content_height(
                            categories, LINE_H, right_asset_collapsed
                        )
                        _vb = _editor_right_sidebar_view_bottom(
                            screen_h=SCREEN_H,
                            edit_mode=edit_mode,
                            map_tool=map_tool,
                            selected_nodes=selected_nodes,
                            sidebar_w=sidebar_w,
                            event_preview_sel=event_preview_sel,
                        )
                        scroll_y_right = _sidebar_scroll_clamp(scroll_y_right, _rch, _rt, _vb)
                    else:
                        scroll_y_steps += event.y * EDITOR_SIDEBAR_WHEEL_STEP
                        if current_event_id and current_event_type:
                            _steps = all_events[current_event_type][current_event_id].get("steps", [])
                            scroll_y_steps = _sidebar_scroll_clamp(
                                scroll_y_steps,
                                len(_steps) * LINE_H + 40,
                                EDITOR_RIGHT_STEPS_TOP,
                                sidebar_list_bottom,
                            )
                        elif scroll_y_steps > 0:
                            scroll_y_steps = 0
                    continue
                else: # 중앙 화면은 기존 줌 기능
                    scaled_cache.clear()
                    old_wx, old_wy = get_real_pos(mx, my)
                    if event.y > 0: zoom_idx = min(len(zoom_steps) - 1, zoom_idx + 1)
                    else: zoom_idx = max(0, zoom_idx - 1)
                    zoom_level = zoom_steps[zoom_idx]
                    new_mx_real, new_my_real = get_real_pos(mx, my)
                    cam_x -= (new_mx_real - old_wx)
                    cam_y -= (new_my_real - old_wy)
                
















            if event.type == pygame.KEYDOWN:
                if _editor_event_triggers_map_export(event):
                    debug_last_key = "EXPORT"
                    debug_last_key_t = pygame.time.get_ticks()
                    trigger_map_png_export()
                    continue

                if event.key == pygame.K_m:
                    show_mask = not show_mask # m 누를 때마다 켜고 끄기
                    if show_mask:
                        # 마스크 이미지를 가져와서 투명도를 줄 수 있는 형태로 변환
                        mask_surf_alpha = mask.convert_alpha()
                        # 전체 픽셀에 128(약 50%) 투명도 적용
                        mask_surf_alpha.set_alpha(128)

                if event.key == pygame.K_F8:
                    editor_smooth_sidebar_thumbs = not editor_smooth_sidebar_thumbs
                    sidebar_thumb_cache.clear()

                # [S] 키로 통합 저장
                if event.key == pygame.K_s:
                    # 1. 맵 데이터 저장 (world_data.json)
                    flow.save_editor_data(map_id, objs, npcs)
                    
                    # 2. 이벤트 데이터 저장 (events.json)
                    # 현재 에디터 메모리에 로드된 all_events 객체를 그대로 저장합니다.
                    try:
                        flow.save_events(all_events)
                        print(">>> [SUCCESS] 모든 데이터(맵+이벤트) 저장 완료!")
                    except Exception as e:
                        print(f">>> [ERROR] 이벤트 저장 중 오류 발생: {e}")
                
                if event.key == pygame.K_ESCAPE:
                    if show_multi_delete_confirm:
                        show_multi_delete_confirm = False
                    elif any_char_modal_open():
                        close_all_char_modals()
                    elif edit_mode == "MAP" and map_tool == "ZONES" and selected_zone_idx is not None:
                        selected_zone_idx = None
                        is_zone_dragging = False
                    elif edit_mode == "MAP" and map_tool == "BGZONES" and selected_bgzone_idx is not None:
                        selected_bgzone_idx = None
                        is_bgzone_dragging = False
                    else:
                        obj_sprite_tilt_active = False
                        obj_height_active = False
                        obj_layer_active = False
                        selected_node = None
                        selected_asset = None
                        selected_nodes.clear()

                if (
                    event.key == pygame.K_DELETE
                    and edit_mode == "MAP"
                    and map_tool == "OBJECTS"
                ):
                    if show_multi_delete_confirm:
                        pass
                    elif len(selected_nodes) > 1:
                        show_multi_delete_confirm = True
                    elif len(selected_nodes) == 1:
                        n = selected_nodes[0]
                        if n in objs:
                            objs.remove(n)
                        elif n in npcs:
                            npcs.remove(n)
                        obj_sprite_tilt_active = False
                        obj_height_active = False
                        obj_layer_active = False
                        selected_nodes.clear()
                        selected_node = None

                if event.key == pygame.K_DELETE and edit_mode == "MAP" and map_tool == "ZONES" and selected_zone_idx is not None:
                    zones = flow.world_data.get(map_id, {}).get("event_zones", [])
                    if 0 <= selected_zone_idx < len(zones):
                        zones.pop(selected_zone_idx)
                        selected_zone_idx = None
                        is_zone_dragging = False
                        flow.save_editor_data(map_id, objs, npcs)

                if event.key == pygame.K_DELETE and edit_mode == "MAP" and map_tool == "BGZONES" and selected_bgzone_idx is not None:
                    zones = flow.world_data.get(map_id, {}).get("bg_zones", [])
                    if 0 <= selected_bgzone_idx < len(zones):
                        zones.pop(selected_bgzone_idx)
                        selected_bgzone_idx = None
                        is_bgzone_dragging = False
                        flow.save_editor_data(map_id, objs, npcs)

                # --- [신규] 화살표 키 미세 조정 (1픽셀씩 이동, 다중 선택 시 전부) ---
                if selected_nodes:
                    dx = dy = 0
                    if event.key == pygame.K_LEFT:
                        dx = -1
                    elif event.key == pygame.K_RIGHT:
                        dx = 1
                    elif event.key == pygame.K_UP:
                        dy = -1
                    elif event.key == pygame.K_DOWN:
                        dy = 1
                    if dx or dy:
                        for o in selected_nodes:
                            o.pos[0] += dx
                            o.pos[1] += dy
                            if hasattr(o, "origin_pos"):
                                o.origin_pos = [o.pos[0], o.pos[1]]

















        # --- [1] 그리기 준비 (상단 바 영역 확보) ---       
        screen.fill((30, 30, 30))
        
        # 가변적인 map_area_w를 사용하여 서피스 생성
        map_surf = pygame.Surface((map_area_w, map_view_h))
        map_surf.fill((20, 20, 20))

        bg_blit_x, bg_blit_y = bg_anchor(float(cam_x), float(cam_y), float(zoom_level), _map_ox, _map_oy)















        # --- [2] 맵 배경 및 격자 그리기 (최적화 버전) ---
        bg_w, bg_h = bg.get_size()
        bg_key = (id(bg), zoom_level)
        if bg_key not in scaled_cache:
                scaled_cache[bg_key] = pygame.transform.scale(bg, (int(bg_w * zoom_level), int(bg_h * zoom_level)))
        s_bg_map = scaled_cache[bg_key]
        sw_bg, sh_bg = s_bg_map.get_size()
        map_surf.blit(s_bg_map, (bg_blit_x, bg_blit_y))

















        # --- [3] 오브젝트/NPC 그리기 ---
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
                    return y - h
                return y

        render_pool = sorted(objs + npcs + [player], key=lambda x: (getattr(x, 'layer', 0), _ysort_y(x)))
        viewport_rect = pygame.Rect(0, 0, map_area_w, map_view_h)

        for o in render_pool:
                orig_w, orig_h = o.image.get_size()
                cache_key = (id(o.image), zoom_level)
                if cache_key not in scaled_cache:
                    scaled_cache[cache_key] = pygame.transform.scale(o.image, (int(orig_w * zoom_level), int(orig_h * zoom_level)))
        
                s_img = scaled_cache[cache_key]
                h_draw = float(getattr(o, "height", 0) or 0)
                # 월드→맵: 배경과 동일 (ow,oh)→(sw_bg,sh_bg) 비율. wx*줌 반올림과 달리 배경 텍스처 열과 일치
                foot_px_x, foot_px_y = world_to_map_surface_xy(
                    bg_blit_x,
                    bg_blit_y,
                    float(o.pos[0]),
                    float(o.pos[1]),
                    bg_w,
                    bg_h,
                    sw_bg,
                    sh_bg,
                    h_draw,
                )
                final_x, final_y = blit_topleft_bottom_center(
                    foot_px_x, foot_px_y, s_img.get_width(), s_img.get_height()
                )

                spr_rect = pygame.Rect(final_x, final_y, s_img.get_width(), s_img.get_height())
                _, anchor_y_scr = world_to_map_surface_xy(
                    bg_blit_x, bg_blit_y, float(o.pos[0]), float(o.pos[1]), bg_w, bg_h, sw_bg, sh_bg, 0.0
                )
                on_map = spr_rect.colliderect(viewport_rect)
                # 높이 막대: 선택과 무관. 앵커(바닥)가 뷰 근처이거나 스프라이트가 보이면 표시
                if edit_mode == "MAP" and map_tool == "OBJECTS" and h_draw > 0:
                    pad_y = min(640, int(h_draw * float(zoom_level)) + 160)
                    near_anchor = viewport_rect.inflate(64, pad_y).collidepoint(float(foot_px_x), float(anchor_y_scr))
                    if near_anchor or on_map:
                        _editor_draw_height_span_on_map(
                            map_surf,
                            float(bg_blit_x),
                            float(bg_blit_y),
                            float(o.pos[0]),
                            float(o.pos[1]),
                            h_draw,
                            bg_w,
                            bg_h,
                            sw_bg,
                            sh_bg,
                            selected=(o in selected_nodes),
                        )

                if on_map:
                    hidden = _editor_entity_play_hidden(o)
                    if hidden:
                        _editor_draw_hidden_entity_ghost(
                            map_surf,
                            s_img,
                            final_x,
                            final_y,
                            selected=(o in selected_nodes),
                        )
                    else:
                        map_surf.blit(s_img, (final_x, final_y))
                    if o in selected_nodes:
                        if not hidden:
                            pygame.draw.rect(
                                map_surf,
                                (255, 255, 0),
                                (final_x, final_y, s_img.get_width(), s_img.get_height()),
                                2,
                            )
                        if edit_mode == "MAP" and o is not player:
                            try:
                                from char_behavior import npc_interact_enabled
                                from flow import (
                                    entity_interact_anchor_xy,
                                    entity_interact_range,
                                    entity_interact_spec,
                                    interact_spec_enabled,
                                )

                                spec = entity_interact_spec(o)
                                show_rng = interact_spec_enabled(spec) or (
                                    getattr(o, "char_def", None) and npc_interact_enabled(o)
                                )
                                if show_rng:
                                    anch = entity_interact_anchor_xy(o)
                                    if anch:
                                        def_rng = (
                                            float(CONFIG.get("NPC_INTERACT_RANGE", 48))
                                            if getattr(o, "char_def", None)
                                            else float(CONFIG.get("OBJECT_INTERACT_RANGE", 40))
                                        )
                                        _editor_draw_interact_range_on_map(
                                            map_surf,
                                            bg_blit_x,
                                            bg_blit_y,
                                            float(anch[0]),
                                            float(anch[1]),
                                            float(entity_interact_range(o, default=def_rng)),
                                            bg_w,
                                            bg_h,
                                            sw_bg,
                                            sh_bg,
                                            viewport_rect,
                                        )
                            except Exception:
                                pass

        # EVENT: 선택/편집 스텝까지 누적된 MOVE·PLACE 미리보기
        if edit_mode == "EVENT" and current_event_id and current_event_type:
                steps_pv = all_events[current_event_type][current_event_id].get("steps", [])
                upto_pv = _preview_upto_index(
                    show_step_config, step_edit_index, step_insert_index, steps_pv, selected_step_idx
                )
                if upto_pv >= 0:
                    pos_sim, arrows_sim, last_st = _simulate_event_preview(
                        steps_pv, upto_pv, player, objs, npcs
                    )
                    zl = max(0.25, zoom_level)
                    # 상호작용 접근 거리(interact.range) — 스프라이트 아래에 원으로 표시
                    for name, p in pos_sim.items():
                        ar = _editor_preview_interact_anchor_range(
                            name, p, objs, npcs, flow.world_data, map_id
                        )
                        if ar is not None:
                            _editor_draw_interact_range_on_map(
                                map_surf,
                                bg_blit_x,
                                bg_blit_y,
                                float(ar[0]),
                                float(ar[1]),
                                float(ar[2]),
                                bg_w,
                                bg_h,
                                sw_bg,
                                sh_bg,
                                viewport_rect,
                                color=(
                                    (255, 60, 220)
                                    if name == event_preview_sel
                                    else (255, 90, 200)
                                ),
                            )
                    for name, p in sorted(pos_sim.items(), key=lambda kv: kv[1][1]):
                        base_img = _resolve_preview_base_image(
                            name, player, objs, npcs, preview_sprite_cache
                        )
                        if base_img:
                            orig_w, orig_h = base_img.get_size()
                            sk = ("_evpv", name, round(zoom_level * 1000))
                            if sk not in scaled_cache:
                                scaled_cache[sk] = pygame.transform.scale(
                                    base_img,
                                    (int(orig_w * zoom_level), int(orig_h * zoom_level)),
                                )
                            s_img = scaled_cache[sk]
                            zf = float(zoom_level)
                            fpx, fpy = world_to_map_surface_xy(
                                bg_blit_x, bg_blit_y, float(p[0]), float(p[1]), bg_w, bg_h, sw_bg, sh_bg, 0.0
                            )
                            final_x, final_y = blit_topleft_bottom_center(
                                fpx, fpy, s_img.get_width(), s_img.get_height()
                            )
                            pr = pygame.Rect(final_x, final_y, s_img.get_width(), s_img.get_height())
                            if viewport_rect.colliderect(pr):
                                map_surf.blit(s_img, (final_x, final_y))
                                sel_pv = name == event_preview_sel
                                pygame.draw.rect(
                                    map_surf,
                                    (255, 220, 60) if sel_pv else (60, 200, 255),
                                    pr,
                                    3 if sel_pv else 2,
                                )
                                tag = name if name != "player" else "player"
                                if name in last_st:
                                    tag = f"{tag} s{last_st[name]}"
                                map_surf.blit(
                                    font.render(tag, True, (200, 240, 255)),
                                    (final_x, min(map_surf.get_height() - 14, final_y + s_img.get_height())),
                                )
                        else:
                            sx, sy = world_to_map_surface_xy(
                                bg_blit_x, bg_blit_y, float(p[0]), float(p[1]), bg_w, bg_h, sw_bg, sh_bg, 0.0
                            )
                            rad = max(3, int(5 * min(zl, 2)))
                            pygame.draw.circle(map_surf, (70, 190, 255), (sx, sy), rad, 2)
                            tag = name if name != "player" else "player"
                            if name in last_st:
                                tag = f"{tag} s{last_st[name]}"
                            map_surf.blit(font.render(tag, True, (180, 230, 255)), (sx + rad, sy - rad))
                    for ar in arrows_sim:
                        sxa, sya = world_to_map_surface_xy(
                            bg_blit_x, bg_blit_y, float(ar["x1"]), float(ar["y1"]), bg_w, bg_h, sw_bg, sh_bg, 0.0
                        )
                        sxb, syb = world_to_map_surface_xy(
                            bg_blit_x, bg_blit_y, float(ar["x2"]), float(ar["y2"]), bg_w, bg_h, sw_bg, sh_bg, 0.0
                        )
                        col = (255, 170, 70) if ar["instant"] else (100, 255, 140)
                        _draw_arrow_on_map(map_surf, sxa, sya, sxb, syb, col, zoom_level)
                        midx, midy = (sxa + sxb) // 2, (sya + syb) // 2
                        map_surf.blit(font.render(f"{ar['step']}", True, col), (midx - 4, midy - 14))

        # --- [추가] 이벤트 박스(event_zones) 표시 ---
        if edit_mode == "MAP":
                zones = flow.world_data.get(map_id, {}).get("event_zones", [])
                for i, z in enumerate(zones):
                    zx, zy, zw, zh = z.get("rect", [0, 0, 0, 0])
                    if zw <= 0 or zh <= 0:
                        continue
                    left, top = world_to_map_surface_xy(
                        bg_blit_x, bg_blit_y, float(zx), float(zy), bg_w, bg_h, sw_bg, sh_bg, 0.0
                    )
                    w = max(1, int(round(float(zw) * float(sw_bg) / float(bg_w))))
                    h = max(1, int(round(float(zh) * float(sh_bg) / float(bg_h))))
                    r = pygame.Rect(left, top, w, h)
                    # 반투명 채움 + 테두리
                    fill = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
                    sel = (map_tool == "ZONES" and selected_zone_idx == i)
                    fill.fill((255, 255, 0, 50) if sel else (0, 255, 0, 40))
                    map_surf.blit(fill, (left, top))
                    pygame.draw.rect(map_surf, (255, 255, 0) if sel else (0, 255, 0), r, 2)
                    label = z.get("name") or z.get("event_id", "EV")
                    map_surf.blit(font.render(str(label), True, (255, 255, 0) if sel else (0, 255, 0)), (left + 3, top - 16))

                # --- [추가] 배경 박스(bg_zones) 표시 ---
                bgzones = flow.world_data.get(map_id, {}).get("bg_zones", [])
                for i, z in enumerate(bgzones):
                    zx, zy, zw, zh = z.get("rect", [0, 0, 0, 0])
                    if zw <= 0 or zh <= 0:
                        continue
                    left, top = world_to_map_surface_xy(
                        bg_blit_x, bg_blit_y, float(zx), float(zy), bg_w, bg_h, sw_bg, sh_bg, 0.0
                    )
                    w = max(1, int(round(float(zw) * float(sw_bg) / float(bg_w))))
                    h = max(1, int(round(float(zh) * float(sh_bg) / float(bg_h))))
                    r = pygame.Rect(left, top, w, h)
                    fill = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
                    sel = (map_tool == "BGZONES" and selected_bgzone_idx == i)
                    fill.fill((80, 160, 255, 40) if not sel else (255, 120, 255, 60))
                    map_surf.blit(fill, (left, top))
                    pygame.draw.rect(map_surf, (80, 160, 255) if not sel else (255, 120, 255), r, 2)
                    label = z.get("name") or f"bg_{i}"
                    map_surf.blit(
                        font.render(str(label), True, (80, 160, 255) if not sel else (255, 120, 255)),
                        (left + 3, top - 16),
                    )

                # --- [추가] 체류 박스(presence_zones) 표시 ---
                pzones = flow.world_data.get(map_id, {}).get("presence_zones", [])
                for i, z in enumerate(pzones):
                    zx, zy, zw, zh = z.get("rect", [0, 0, 0, 0])
                    if zw <= 0 or zh <= 0:
                        continue
                    left, top = world_to_map_surface_xy(
                        bg_blit_x, bg_blit_y, float(zx), float(zy), bg_w, bg_h, sw_bg, sh_bg, 0.0
                    )
                    w = max(1, int(round(float(zw) * float(sw_bg) / float(bg_w))))
                    h = max(1, int(round(float(zh) * float(sh_bg) / float(bg_h))))
                    r = pygame.Rect(left, top, w, h)
                    fill = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
                    sel = (map_tool == "PRESENCE" and selected_presence_idx == i)
                    fill.fill((255, 120, 180, 45) if not sel else (255, 200, 120, 65))
                    map_surf.blit(fill, (left, top))
                    pygame.draw.rect(map_surf, (255, 120, 180) if not sel else (255, 200, 120), r, 2)
                    label = z.get("name") or f"pre_{i}"
                    map_surf.blit(
                        font.render(str(label), True, (255, 120, 180) if not sel else (255, 200, 120)),
                        (left + 3, top - 16),
                    )

        # 드래그 중인 이벤트 박스 프리뷰
        if is_selecting_zone_rect and zone_drag_start and zone_drag_end:
                x1, y1 = zone_drag_start
                x2, y2 = zone_drag_end
                zx = min(x1, x2)
                zy = min(y1, y2)
                zw = abs(x2 - x1)
                zh = abs(y2 - y1)
                left, top = world_to_map_surface_xy(
                    bg_blit_x, bg_blit_y, float(zx), float(zy), bg_w, bg_h, sw_bg, sh_bg, 0.0
                )
                w = max(1, int(round(float(zw) * float(sw_bg) / float(bg_w))))
                h = max(1, int(round(float(zh) * float(sh_bg) / float(bg_h))))
                pygame.draw.rect(map_surf, (0, 255, 0), pygame.Rect(left, top, w, h), 2)

        # 드래그 중인 배경 박스 프리뷰
        if is_selecting_bgzone_rect and bgzone_drag_start and bgzone_drag_end:
                x1, y1 = bgzone_drag_start
                x2, y2 = bgzone_drag_end
                zx = min(x1, x2)
                zy = min(y1, y2)
                zw = abs(x2 - x1)
                zh = abs(y2 - y1)
                left, top = world_to_map_surface_xy(
                    bg_blit_x, bg_blit_y, float(zx), float(zy), bg_w, bg_h, sw_bg, sh_bg, 0.0
                )
                w = max(1, int(round(float(zw) * float(sw_bg) / float(bg_w))))
                h = max(1, int(round(float(zh) * float(sh_bg) / float(bg_h))))
                pygame.draw.rect(map_surf, (80, 160, 255), pygame.Rect(left, top, w, h), 2)

        # 드래그 중인 presence 박스 프리뷰
        if is_selecting_presence_rect and presence_drag_start and presence_drag_end:
                x1, y1 = presence_drag_start
                x2, y2 = presence_drag_end
                zx = min(x1, x2)
                zy = min(y1, y2)
                zw = abs(x2 - x1)
                zh = abs(y2 - y1)
                left, top = world_to_map_surface_xy(
                    bg_blit_x, bg_blit_y, float(zx), float(zy), bg_w, bg_h, sw_bg, sh_bg, 0.0
                )
                w = max(1, int(round(float(zw) * float(sw_bg) / float(bg_w))))
                h = max(1, int(round(float(zh) * float(sh_bg) / float(bg_h))))
                pygame.draw.rect(map_surf, (255, 120, 180), pygame.Rect(left, top, w, h), 2)

        # 오브젝트 다중선택 드래그 박스(월드 → 맵 서피스)
        if (
                box_select_start is not None
                and edit_mode == "MAP"
                and map_tool == "OBJECTS"
        ):
                bx1, by1 = box_select_start
                bx2, by2 = (
                    box_select_current if box_select_current is not None else box_select_start
                )
                zx = min(bx1, bx2)
                zy = min(by1, by2)
                zw = abs(bx2 - bx1)
                zh = abs(by2 - by1)
                left, top = world_to_map_surface_xy(
                    bg_blit_x, bg_blit_y, float(zx), float(zy), bg_w, bg_h, sw_bg, sh_bg, 0.0
                )
                w = max(1, int(round(float(zw) * float(sw_bg) / float(bg_w))))
                h = max(1, int(round(float(zh) * float(sh_bg) / float(bg_h))))
                pygame.draw.rect(map_surf, (120, 200, 255), pygame.Rect(left, top, w, h), 2)














        # --- [추가] 마스크(이동 구역) 표시 ---
        if show_mask and mask_surf_alpha:
                mask_key = (id(mask_surf_alpha), zoom_level)
                if mask_key not in scaled_cache:
                    mw, mh = mask_surf_alpha.get_size()
                    scaled_cache[mask_key] = pygame.transform.scale(mask_surf_alpha, (int(mw * zoom_level), int(mh * zoom_level)))
        
                # 모든 오브젝트 위에 50% 투명도로 덮기
                map_surf.blit(scaled_cache[mask_key], (bg_blit_x, bg_blit_y))

















        # 격자: 배경 scaled 비율과 동일 변환(월드 격자선 = 배경 픽셀 열)
        _mh = map_surf.get_height()
        for gx in range(0, bg_w + 1, GRID_SIZE):
                lx, _ = world_to_map_surface_xy(
                    bg_blit_x, bg_blit_y, float(gx), 0.0, bg_w, bg_h, sw_bg, sh_bg, 0.0
                )
                if 0 <= lx <= map_area_w:
                    pygame.draw.line(map_surf, (50, 50, 50), (lx, 0), (lx, _mh))
        for gy in range(0, bg_h + 1, GRID_SIZE):
                _, ly = world_to_map_surface_xy(
                    bg_blit_x, bg_blit_y, 0.0, float(gy), bg_w, bg_h, sw_bg, sh_bg, 0.0
                )
                if 0 <= ly <= _mh:
                    pygame.draw.line(map_surf, (50, 50, 50), (0, ly), (map_area_w, ly))


















        # 고스트(미리보기)
        if selected_asset and sidebar_w < mx < SCREEN_W - right_panel_w and my > TOP_BAR_H:
                gzx, gzy = world_to_map_surface_xy(
                    bg_blit_x, bg_blit_y, float(swx), float(swy), bg_w, bg_h, sw_bg, sh_bg, 0.0
                )
                pygame.draw.circle(
                    map_surf, (255, 255, 0), (gzx, gzy), int(5 * zoom_level), 2
                )
                try:
                    if selected_asset in OBJ_ASSETS:
                        gh = float(OBJ_ASSETS.get(selected_asset, {}).get("height", 0) or 0)
                    elif selected_asset in CHAR_ASSETS:
                        gh = float(CHAR_ASSETS.get(selected_asset, {}).get("height", 0) or 0)
                    else:
                        gh = 0.0
                except Exception:
                    gh = 0.0
                if gh > 0.0:
                    _editor_draw_height_span_on_map(
                        map_surf,
                        float(bg_blit_x),
                        float(bg_blit_y),
                        float(swx),
                        float(swy),
                        gh,
                        bg_w,
                        bg_h,
                        sw_bg,
                        sh_bg,
                        selected=True,
                    )















        # 스텝 좌표 픽(Pos / WP+): 격자 스냅 위치 미리보기 (Shift=미세)
        if (is_picking_step_pos or is_picking_step_waypoints) and sidebar_w < mx < SCREEN_W - right_panel_w and my > TOP_BAR_H:
                prx, pry = editor_snap_pick_world_xy(wx, wy, GRID_SIZE, is_shift_pressed)
                gzx, gzy = world_to_map_surface_xy(
                    bg_blit_x, bg_blit_y, float(prx), float(pry), bg_w, bg_h, sw_bg, sh_bg, 0.0
                )
                cr = max(3, int(round(5 * float(zoom_level))))
                if not is_shift_pressed:
                    g = GRID_SIZE
                    x0w, y0w = float(prx), float(pry)
                    x1w, y1w = float(prx + g), float(pry + g)
                    c00 = world_to_map_surface_xy(bg_blit_x, bg_blit_y, x0w, y0w, bg_w, bg_h, sw_bg, sh_bg, 0.0)
                    c10 = world_to_map_surface_xy(bg_blit_x, bg_blit_y, x1w, y0w, bg_w, bg_h, sw_bg, sh_bg, 0.0)
                    c11 = world_to_map_surface_xy(bg_blit_x, bg_blit_y, x1w, y1w, bg_w, bg_h, sw_bg, sh_bg, 0.0)
                    c01 = world_to_map_surface_xy(bg_blit_x, bg_blit_y, x0w, y1w, bg_w, bg_h, sw_bg, sh_bg, 0.0)
                    poly = [
                        (int(round(float(c00[0]))), int(round(float(c00[1])))),
                        (int(round(float(c10[0]))), int(round(float(c10[1])))),
                        (int(round(float(c11[0]))), int(round(float(c11[1])))),
                        (int(round(float(c01[0]))), int(round(float(c01[1])))),
                    ]
                    try:
                        pygame.draw.lines(map_surf, (150, 255, 210), True, poly, 2)
                    except Exception:
                        pass
                pygame.draw.line(
                    map_surf,
                    (255, 255, 255),
                    (float(gzx) - cr, float(gzy)),
                    (float(gzx) + cr, float(gzy)),
                    2,
                )
                pygame.draw.line(
                    map_surf,
                    (255, 255, 255),
                    (float(gzx), float(gzy) - cr),
                    (float(gzx), float(gzy) + cr),
                    2,
                )
                pygame.draw.circle(
                    map_surf, (255, 230, 80), (int(round(float(gzx))), int(round(float(gzy)))), max(2, cr // 3), 1
                )

        # FLOW 모드: 맵 위에 그려진 내용을 지우고 네트워크 다이어그램만 표시
        if edit_mode == "FLOW":
            map_surf.fill((22, 24, 30))
            flow_hit_boxes = _editor_flow_paint_diagram(
                map_surf,
                pygame.Rect(0, 0, map_area_w, map_view_h),
                flow_graph,
                flow_scroll_x,
                flow_scroll_y,
                font,
                title_font,
            )

        # 메인 화면에 맵 붙이기
        screen.blit(map_surf, (sidebar_w, TOP_BAR_H))
        if edit_mode == "FLOW":
            screen.blit(
                font.render(
                    "우클릭 드래그: 이동 · 휠: 세로 · Shift+휠: 가로",
                    True,
                    (120, 130, 150),
                ),
                (sidebar_w + 12, TOP_BAR_H + 6),
            )

        flow_back_btn = None
        if edit_mode == "FLOW" and flow_opened_settings and (
            show_event_config
            or show_zone_config
            or show_bgzone_config
            or show_step_config
            or any_char_modal_open()
        ):
            flow_back_btn = pygame.Rect(sidebar_w + 12, TOP_BAR_H + 8, 168, 30)
            pygame.draw.rect(screen, (48, 52, 72), flow_back_btn, border_radius=4)
            pygame.draw.rect(screen, (160, 180, 220), flow_back_btn, 1, border_radius=4)
            screen.blit(font.render("← FLOW 로 돌아가기", True, (230, 240, 255)), (flow_back_btn.x + 10, flow_back_btn.y + 7))



















        # [NEW_UI_ADD] 1. 좌측 상단 모드 전환 — MAP / EVENT / FLOW
        mode_band = max(1, TOP_BAR_H // 3)
        mode_color_map = (255, 255, 255) if edit_mode == "MAP" else (100, 100, 100)
        mode_color_evt = (255, 255, 255) if edit_mode == "EVENT" else (100, 100, 100)
        mode_color_flow = (255, 255, 255) if edit_mode == "FLOW" else (100, 100, 100)
        for i, col in enumerate(((60, 60, 60), (70, 70, 70), (55, 52, 48))):
            pygame.draw.rect(screen, col, (0, i * mode_band, sidebar_w, mode_band))
        if edit_mode == "MAP":
            pygame.draw.rect(screen, (255, 215, 0), (0, 0, sidebar_w, mode_band), 2)
        elif edit_mode == "EVENT":
            pygame.draw.rect(screen, (255, 215, 0), (0, mode_band, sidebar_w, mode_band), 2)
        else:
            pygame.draw.rect(screen, (255, 215, 0), (0, mode_band * 2, sidebar_w, TOP_BAR_H - mode_band * 2), 2)
        screen.blit(font.render("MAP", True, mode_color_map), (12, 2))
        screen.blit(font.render("EVENT", True, mode_color_evt), (12, mode_band + 2))
        screen.blit(font.render("FLOW", True, mode_color_flow), (12, mode_band * 2 + 2))

        # (키 디버그 표시는 하단 상태바 위에서 처리)













        # --- [4] UI: 상단 맵 목록 바 ---
        pygame.draw.rect(screen, (45, 45, 45), (sidebar_w, 0, map_area_w, TOP_BAR_H))
        pygame.draw.line(screen, (100, 100, 100), (sidebar_w, TOP_BAR_H-1), (sidebar_w + map_area_w, TOP_BAR_H-1))
        pygame.draw.rect(screen, (55, 75, 95), export_map_btn, border_radius=5)
        pygame.draw.rect(screen, (140, 170, 210), export_map_btn, 2, border_radius=5)
        screen.blit(font.render("PNG", True, (240, 248, 255)), (export_map_btn.x + 18, export_map_btn.y + 10))
        for i, m_name in enumerate(map_list):
            m_color = (255, 215, 0) if i == cur_idx else (180, 180, 180)
            m_rect = pygame.Rect(sidebar_w + 10 + (i * 112), 12, 104, 34)
            pygame.draw.rect(screen, (60, 60, 60), m_rect, border_radius=5)
            if i == cur_idx: pygame.draw.rect(screen, (255, 215, 0), m_rect, 2, border_radius=5)
            screen.blit(font.render(m_name, True, m_color), (m_rect.x + 10, m_rect.y + 7))















        # --- [5] UI: 좌측 오브젝트 목록 (이중 구조) ---
        pygame.draw.rect(screen, (40, 40, 40), (0, TOP_BAR_H, sidebar_w, map_view_h))

        if edit_mode == "MAP":
            # 1. 제목 위치: TOP_BAR_H에서 10픽셀만 더 내림
            list_title_y = TOP_BAR_H + 10
            screen.blit(title_font.render("PLACED (category)", True, (200, 255, 200)), (10, list_title_y))

            # MAP 모드: OBJECTS / ZONES / BGZONES / PRESENCE 토글 버튼
            tool_w = max(40, (sidebar_w - 40) // 4)
            tool_btn_obj = pygame.Rect(8, left_list_tops["map_tools"], tool_w, 28)
            tool_btn_zone = pygame.Rect(tool_btn_obj.right + 4, left_list_tops["map_tools"], tool_w, 28)
            tool_btn_bgz = pygame.Rect(tool_btn_zone.right + 4, left_list_tops["map_tools"], tool_w, 28)
            tool_btn_pres = pygame.Rect(tool_btn_bgz.right + 4, left_list_tops["map_tools"], tool_w, 28)
            for tb in (tool_btn_obj, tool_btn_zone, tool_btn_bgz, tool_btn_pres):
                pygame.draw.rect(screen, (70, 70, 70), tb)
            if map_tool == "OBJECTS":
                pygame.draw.rect(screen, (255, 215, 0), tool_btn_obj, 2)
            elif map_tool == "ZONES":
                pygame.draw.rect(screen, (255, 215, 0), tool_btn_zone, 2)
            elif map_tool == "BGZONES":
                pygame.draw.rect(screen, (255, 215, 0), tool_btn_bgz, 2)
            else:
                pygame.draw.rect(screen, (255, 215, 0), tool_btn_pres, 2)
            screen.blit(font.render("OBJ", True, (255, 255, 255)), (tool_btn_obj.x + 10, tool_btn_obj.y + 4))
            screen.blit(font.render("EVT", True, (255, 255, 255)), (tool_btn_zone.x + 10, tool_btn_zone.y + 4))
            screen.blit(font.render("BG", True, (255, 255, 255)), (tool_btn_bgz.x + 12, tool_btn_bgz.y + 4))
            screen.blit(font.render("PRE", True, (255, 255, 255)), (tool_btn_pres.x + 8, tool_btn_pres.y + 4))

            # MAP / ZONES: Add Event Box 버튼
            add_zone_btn = pygame.Rect(8, left_list_tops["map_zone_btn"], sidebar_w - 16, 28)
            if map_tool == "ZONES":
                pygame.draw.rect(screen, (50, 80, 50), add_zone_btn)
                pygame.draw.rect(screen, (110, 160, 110), add_zone_btn, 1)
                screen.blit(font.render("+ ADD EVENT BOX", True, (255, 255, 255)), (add_zone_btn.x + 10, add_zone_btn.y + 6))

            # MAP / BGZONES: Add BG Box 버튼
            add_bgzone_btn = pygame.Rect(8, left_list_tops["map_bgzone_btn"], sidebar_w - 16, 28)
            if map_tool == "BGZONES":
                pygame.draw.rect(screen, (55, 60, 90), add_bgzone_btn)
                pygame.draw.rect(screen, (130, 160, 200), add_bgzone_btn, 1)
                screen.blit(font.render("+ ADD BG BOX", True, (255, 255, 255)), (add_bgzone_btn.x + 18, add_bgzone_btn.y + 6))

            # MAP / PRESENCE: Add Presence Box 버튼
            add_presence_btn = pygame.Rect(8, left_list_tops["map_presence_btn"], sidebar_w - 16, 28)
            if map_tool == "PRESENCE":
                pygame.draw.rect(screen, (90, 55, 70), add_presence_btn)
                pygame.draw.rect(screen, (200, 130, 160), add_presence_btn, 1)
                screen.blit(font.render("+ ADD PRESENCE", True, (255, 255, 255)), (add_presence_btn.x + 8, add_presence_btn.y + 6))
            if map_tool == "OBJECTS":
                list_start_y = left_list_tops["map_objects"]
                placed_rows = _editor_filter_collapsed_rows(
                    build_editor_placed_list_rows(objs, npcs),
                    left_placed_collapsed,
                )
                for i, row in enumerate(placed_rows):
                    item_y = list_start_y + (i * LINE_H) + scroll_y_left
                    if not (TOP_BAR_H + 30 < item_y < sidebar_list_bottom):
                        continue
                    label_x = 8
                    if row["kind"] == "header":
                        key = row["label"]
                        mark = _editor_collapse_mark(left_placed_collapsed, key)
                        hdr = f"{mark} {key}"
                        hdr_rect = pygame.Rect(label_x, item_y, sidebar_w - label_x - 6, LINE_H)
                        screen.blit(
                            title_font.render(hdr, True, (100, 170, 120)),
                            (label_x, item_y),
                        )
                        if _editor_sidebar_list_tooltip_ok(
                            show_event_config, show_zone_config, show_bgzone_config, show_step_config, show_multi_delete_confirm
                        ) and hdr_rect.collidepoint(mx, my):
                            sidebar_list_tooltip = (mx, my, "클릭: 접기/펼치기")
                        continue
                    node = row["node"]
                    is_sel = node in selected_nodes or selected_node is node
                    txt_color = (255, 255, 0) if is_sel else (180, 180, 180)
                    prefix = "◎ " if row["kind"] == "npc" else "· "
                    body = row["label"]
                    max_body_w = max(
                        24,
                        sidebar_w - label_x - 8 - _editor_font_line_width(font, prefix),
                    )
                    vb_left = sidebar_w - 50
                    max_body_w = max(
                        24,
                        vb_left - label_x - 6 - _editor_font_line_width(font, prefix),
                    )
                    body_vis, _cut = _editor_truncate_text_to_width(font, body, max_body_w)
                    label = f"{prefix}{body_vis}"
                    row_rect = pygame.Rect(label_x, item_y, vb_left - label_x - 4, LINE_H)
                    screen.blit(font.render(label, True, txt_color), (label_x, item_y))
                    if row["kind"] == "npc":
                        vb = pygame.Rect(sidebar_w - 50, item_y + 2, 44, LINE_H - 6)
                        pygame.draw.rect(screen, (55, 75, 100), vb)
                        pygame.draw.rect(screen, (130, 160, 200), vb, 1)
                        screen.blit(font.render("Inst", True, (220, 230, 255)), (vb.x + 4, vb.y + 2))
                    if _editor_sidebar_list_tooltip_ok(
                        show_event_config, show_zone_config, show_bgzone_config, show_step_config, show_multi_delete_confirm
                    ) and row_rect.collidepoint(mx, my):
                        tip = f"{body}\n({int(node.pos[0])}, {int(node.pos[1])})"
                        sidebar_list_tooltip = (mx, my, tip)

            elif map_tool == "ZONES":
                # ZONES 목록 (현재 맵에 깔린 이벤트 박스들)
                zones = flow.world_data.get(map_id, {}).get("event_zones", [])
                list_start_y = left_list_tops["map_objects"]
                for i, z in enumerate(zones):
                    item_y = list_start_y + (i * LINE_H) + scroll_y_left
                    if not (TOP_BAR_H + 30 < item_y < sidebar_list_bottom):
                        continue
                    is_sel = (selected_zone_idx == i)
                    txt_color = (255, 255, 0) if is_sel else (180, 180, 180)
                    name = z.get("name") or f"zone_{i}"
                    eid = z.get("event_id") or ""
                    prefix = " > " if is_sel else "   "
                    label_x = 8
                    vb_left = sidebar_w - 50
                    max_name_w = max(20, vb_left - label_x - 6 - _editor_font_line_width(font, prefix))
                    name_vis, _nc = _editor_truncate_text_to_width(font, name, max_name_w)
                    label = f"{prefix}{name_vis}"
                    row_rect = pygame.Rect(label_x, item_y, vb_left - label_x - 4, LINE_H)
                    screen.blit(font.render(label, True, txt_color), (label_x, item_y))
                    if _editor_sidebar_list_tooltip_ok(
                        show_event_config, show_zone_config, show_bgzone_config, show_step_config, show_multi_delete_confirm
                    ) and row_rect.collidepoint(mx, my):
                        sidebar_list_tooltip = (
                            mx,
                            my,
                            name if not eid else f"{name}\nevent_id: {eid}",
                        )

                    # View 버튼
                    vb = pygame.Rect(sidebar_w - 50, item_y + 2, 44, LINE_H - 6)
                    pygame.draw.rect(screen, (55, 75, 100), vb)
                    pygame.draw.rect(screen, (130, 160, 200), vb, 1)
                    screen.blit(font.render("View", True, (220, 230, 255)), (vb.x + 4, vb.y + 2))

            elif map_tool == "BGZONES":
                zones = flow.world_data.get(map_id, {}).get("bg_zones", [])
                list_start_y = left_list_tops["map_bgzones"]
                for i, z in enumerate(zones):
                    item_y = list_start_y + (i * LINE_H) + scroll_y_left
                    if not (TOP_BAR_H + 30 < item_y < sidebar_list_bottom):
                        continue
                    is_sel = (selected_bgzone_idx == i)
                    txt_color = (255, 255, 0) if is_sel else (180, 180, 180)
                    name = z.get("name") or f"bg_{i}"
                    prefix = " > " if is_sel else "   "
                    label_x = 8
                    vb_left = sidebar_w - 50
                    max_name_w = max(20, vb_left - label_x - 6 - _editor_font_line_width(font, prefix))
                    name_vis, _bc = _editor_truncate_text_to_width(font, name, max_name_w)
                    label = f"{prefix}{name_vis}"
                    row_rect = pygame.Rect(label_x, item_y, vb_left - label_x - 4, LINE_H)
                    screen.blit(font.render(label, True, txt_color), (label_x, item_y))
                    if _editor_sidebar_list_tooltip_ok(
                        show_event_config, show_zone_config, show_bgzone_config, show_step_config, show_multi_delete_confirm
                    ) and row_rect.collidepoint(mx, my):
                        sidebar_list_tooltip = (mx, my, name)

                    vb = pygame.Rect(sidebar_w - 50, item_y + 2, 44, LINE_H - 6)
                    pygame.draw.rect(screen, (55, 75, 100), vb)
                    pygame.draw.rect(screen, (130, 160, 200), vb, 1)
                    screen.blit(font.render("View", True, (220, 230, 255)), (vb.x + 4, vb.y + 2))

            elif map_tool == "PRESENCE":
                zones = flow.world_data.get(map_id, {}).get("presence_zones", [])
                list_start_y = left_list_tops["map_presences"]
                for i, z in enumerate(zones):
                    item_y = list_start_y + (i * LINE_H) + scroll_y_left
                    if not (TOP_BAR_H + 30 < item_y < sidebar_list_bottom):
                        continue
                    is_sel = (selected_presence_idx == i)
                    txt_color = (255, 255, 0) if is_sel else (180, 180, 180)
                    name = z.get("name") or f"presence_{i}"
                    prefix = " > " if is_sel else "   "
                    label_x = 8
                    vb_left = sidebar_w - 50
                    max_name_w = max(20, vb_left - label_x - 6 - _editor_font_line_width(font, prefix))
                    name_vis, _pc = _editor_truncate_text_to_width(font, name, max_name_w)
                    label = f"{prefix}{name_vis}"
                    row_rect = pygame.Rect(label_x, item_y, vb_left - label_x - 4, LINE_H)
                    screen.blit(font.render(label, True, txt_color), (label_x, item_y))
                    if _editor_sidebar_list_tooltip_ok(
                        show_event_config, show_zone_config, show_bgzone_config, show_step_config, show_multi_delete_confirm
                    ) and row_rect.collidepoint(mx, my):
                        sidebar_list_tooltip = (mx, my, name)
                    vb = pygame.Rect(sidebar_w - 50, item_y + 2, 44, LINE_H - 6)
                    pygame.draw.rect(screen, (55, 75, 100), vb)
                    pygame.draw.rect(screen, (130, 160, 200), vb, 1)
                    screen.blit(font.render("View", True, (220, 230, 255)), (vb.x + 4, vb.y + 2))

        elif edit_mode == "FLOW":
            screen.blit(
                title_font.render("캐릭터 / 오브젝트 / 이벤트박스", True, (255, 230, 180)),
                (10, TOP_BAR_H + 6),
            )
            screen.blit(
                font.render("타입 전체 + 현재 맵 이벤트박스 · 클릭 → 차트", True, (130, 145, 165)),
                (10, TOP_BAR_H + 26),
            )
            screen.blit(
                font.render("휠=차트 스크롤 · Shift+휠=가로 · 드래그=이동", True, (110, 125, 145)),
                (10, TOP_BAR_H + 44),
            )
            list_start_y = left_list_tops["flow"]
            placed_rows = _editor_filter_collapsed_rows(
                _editor_flow_catalog_rows(flow.world_data, map_id),
                flow_placed_collapsed,
            )
            for i, row in enumerate(placed_rows):
                item_y = list_start_y + (i * LINE_H) + scroll_y_left
                if not (TOP_BAR_H + 28 < item_y < sidebar_list_bottom):
                    continue
                label_x = 8
                if row["kind"] == "header":
                    key = row["label"]
                    mark = _editor_collapse_mark(flow_placed_collapsed, key)
                    hdr = f"{mark} {key}"
                    hdr_rect = pygame.Rect(label_x, item_y, sidebar_w - 16, LINE_H)
                    hdr_color = (255, 215, 120) if key == FLOW_EVENT_LINKED_HEADER else (180, 220, 255)
                    screen.blit(title_font.render(hdr, True, hdr_color), (label_x + 4, item_y + 2))
                    if _editor_sidebar_list_tooltip_ok(
                        show_event_config, show_zone_config, show_bgzone_config, show_step_config, show_multi_delete_confirm
                    ) and hdr_rect.collidepoint(mx, my):
                        sidebar_list_tooltip = (mx, my, "클릭: 접기/펼치기")
                    continue
                sel = False
                rname = row.get("name")
                rkind = row.get("kind")
                if 0 <= flow_selected_entity_idx < len(flow_entity_entries):
                    se = flow_entity_entries[flow_selected_entity_idx]
                    sel = _editor_flow_row_matches_entry(row, se)
                ent_meta = None
                for ent in flow_entity_entries:
                    if _editor_flow_row_matches_entry(row, ent):
                        ent_meta = ent
                        break
                if rkind == "zone":
                    col = (255, 255, 0) if sel else (150, 210, 150)
                elif (ent_meta or {}).get("event_ids"):
                    col = (255, 255, 0) if sel else (220, 200, 140)
                else:
                    col = (255, 255, 0) if sel else (190, 195, 210)
                prefix = ">" if sel else ("▣ " if rkind == "zone" else " ")
                name = row.get("label") or rname or ""
                n_ev = len((ent_meta or {}).get("event_ids") or [])
                suffix = f"  ev×{n_ev}" if n_ev else ""
                row_rect = pygame.Rect(label_x, item_y, sidebar_w - 16, LINE_H)
                screen.blit(
                    font.render(f"{prefix} {name}{suffix}", True, col),
                    (label_x + 4, item_y + 4),
                )
                if _editor_sidebar_list_tooltip_ok(
                    show_event_config, show_zone_config, show_bgzone_config, show_step_config, show_multi_delete_confirm
                ) and row_rect.collidepoint(mx, my):
                    evs = ", ".join(sorted((ent_meta or {}).get("event_ids") or []))
                    tip = f"{name}\n이벤트: {evs or '(없음)'}"
                    sidebar_list_tooltip = (mx, my, tip)

        elif edit_mode == "EVENT":
            screen.blit(title_font.render("EVENT LIST", True, (200, 255, 200)), (10, TOP_BAR_H + 6))
            add_rect = pygame.Rect(8, EVENT_ADD_Y, sidebar_w - 16, EVENT_ADD_H)
            pygame.draw.rect(screen, (50, 100, 50), add_rect)
            pygame.draw.rect(screen, (100, 180, 100), add_rect, 1)
            screen.blit(font.render("+ ADD EVENT", True, (255, 255, 255)), (add_rect.x + 10, add_rect.y + 6))

            y_ptr = EVENT_LIST_START_Y + scroll_y_left
            for cat in EDITOR_EVENT_SECTIONS:
                if TOP_BAR_H < y_ptr < sidebar_list_bottom:
                    screen.blit(title_font.render(f"[{cat}]", True, (100, 200, 100)), (10, y_ptr))
                y_ptr += LINE_H

                for eid, edata in _editor_sorted_events_in_section(
                    all_events, map_id, cat
                ):
                    is_sel = eid == current_event_id
                    txt_color = (255, 255, 0) if is_sel else (180, 180, 180)
                    prefix = " > " if is_sel else "    "
                    disp = _editor_event_display_name(eid, edata)
                    label_x = 14
                    vb_left = sidebar_w - 50
                    max_disp_w = max(24, vb_left - label_x - 6 - _editor_font_line_width(font, prefix))
                    disp_vis, _dc = _editor_truncate_text_to_width(font, disp, max_disp_w)
                    if TOP_BAR_H < y_ptr < sidebar_list_bottom:
                        screen.blit(font.render(f"{prefix}{disp_vis}", True, txt_color), (label_x, y_ptr))
                        vb = pygame.Rect(sidebar_w - 50, y_ptr + 2, 44, LINE_H - 6)
                        pygame.draw.rect(screen, (55, 75, 100), vb)
                        pygame.draw.rect(screen, (130, 160, 200), vb, 1)
                        screen.blit(font.render("View", True, (220, 230, 255)), (vb.x + 4, vb.y + 2))
                        row_rect = pygame.Rect(label_x, y_ptr, vb_left - label_x - 4, LINE_H)
                        if _editor_sidebar_list_tooltip_ok(
                            show_event_config, show_zone_config, show_bgzone_config, show_step_config, show_multi_delete_confirm
                        ) and row_rect.collidepoint(mx, my):
                            tip = disp if disp == eid else f"{disp}\nid: {eid}"
                            sidebar_list_tooltip = (mx, my, tip)
                    y_ptr += LINE_H

        _lt_sb, _lch_sb = _editor_left_list_metrics(
            edit_mode,
            map_tool,
            map_id,
            objs,
            npcs,
            flow,
            all_events,
            LINE_H,
            TOP_BAR_H,
            EVENT_LIST_START_Y,
            left_placed_collapsed,
            flow_entity_entries=flow_entity_entries,
            flow_placed_collapsed=flow_placed_collapsed,
        )
        scroll_y_left, _ = _editor_paint_sidebar_scrollbar(
            screen, 0, sidebar_w, _lt_sb, sidebar_list_bottom, _lch_sb, scroll_y_left
        )















        # --- [6] UI: 우측 에셋 바 & 하단 상태 바 (FLOW는 좌측 목록+차트만) ---
        if right_panel_w > 0:
            pygame.draw.rect(
                screen, (45, 45, 45), (SCREEN_W - right_panel_w, TOP_BAR_H, right_panel_w, map_view_h)
            )
        if edit_mode == "MAP" and right_panel_w > 0:
            _rbx = SCREEN_W - right_panel_w
            thumb_toggle_draw = pygame.Rect(_rbx + 4, 6, right_sidebar_w - 8, 34)
            pygame.draw.rect(screen, (52, 56, 72), thumb_toggle_draw)
            pygame.draw.rect(
                screen,
                (130, 140, 180) if editor_smooth_sidebar_thumbs else (90, 100, 120),
                thumb_toggle_draw,
                2,
            )
            _tl = "썸네일: 부드럽게 (F8)" if editor_smooth_sidebar_thumbs else "썸네일: 픽셀 (F8)"
            screen.blit(font.render(_tl, True, (230, 230, 235)), (_rbx + 8, 14))

            _vb = _editor_right_sidebar_view_bottom(
                screen_h=SCREEN_H,
                edit_mode=edit_mode,
                map_tool=map_tool,
                selected_nodes=selected_nodes,
                sidebar_w=sidebar_w,
                event_preview_sel=event_preview_sel,
            )
            _rt_draw = _editor_right_map_list_top()
            y_ptr = _rt_draw + scroll_y_right
            _rbx_list = SCREEN_W - right_panel_w

            for line in _editor_right_map_lines(categories, right_asset_collapsed):
                if line["kind"] == "header":
                    cat = line["cat"]
                    mark = _editor_collapse_mark(right_asset_collapsed, cat)
                    hdr = f"{mark} [{cat}] ({line['count']})"
                    if 0 < y_ptr < _vb:
                        hdr_rect = pygame.Rect(_rbx_list + 6, y_ptr, right_sidebar_w - 12, LINE_H)
                        screen.blit(title_font.render(hdr, True, (100, 200, 255)), (_rbx_list + 10, y_ptr))
                        if _editor_sidebar_list_tooltip_ok(
                            show_event_config, show_zone_config, show_bgzone_config, show_step_config, show_multi_delete_confirm
                        ) and hdr_rect.collidepoint(mx, my):
                            sidebar_list_tooltip = (mx, my, "클릭: 접기/펼치기")
                    y_ptr += LINE_H
                    continue

                cat = line["cat"]
                item = line["name"]
                kind = "char" if cat == "CHAR (NPC)" else "obj"
                thumb = _sidebar_asset_thumbnail(
                    kind, item, sidebar_thumb_cache, editor_smooth_sidebar_thumbs
                )
                tx = _rbx_list + 6
                if 0 < y_ptr < _vb:
                    screen.blit(thumb, (tx, y_ptr + max(0, (LINE_H - _SIDEBAR_THUMB_PX) // 2)))
                    color = (0, 255, 0) if selected_asset == item else (200, 200, 200)
                    label_x = tx + _SIDEBAR_THUMB_PX + 5
                    def_w = 48
                    max_item_w = max(24, SCREEN_W - 8 - label_x - def_w)
                    item_vis, _ic = _editor_truncate_text_to_width(font, item, max_item_w)
                    screen.blit(font.render(item_vis, True, color), (label_x, y_ptr + 4))
                    db = _editor_right_map_side_btn_rect(
                        _rbx_list, right_sidebar_w, y_ptr, LINE_H
                    )
                    if cat == "CHAR (NPC)":
                        pygame.draw.rect(screen, (55, 90, 70), db)
                        pygame.draw.rect(screen, (130, 200, 140), db, 1)
                        screen.blit(font.render("NPC", True, (220, 255, 230)), (db.x + 8, db.y + 2))
                    else:
                        pygame.draw.rect(screen, (55, 48, 30), db)
                        pygame.draw.rect(screen, (180, 150, 90), db, 1)
                        screen.blit(font.render("Evt", True, (255, 240, 210)), (db.x + 10, db.y + 2))
                    row_h = max(LINE_H, _SIDEBAR_THUMB_PX)
                    row_rect = pygame.Rect(tx, y_ptr, right_sidebar_w - 10 - def_w, row_h)
                    if _editor_sidebar_list_tooltip_ok(
                        show_event_config, show_zone_config, show_bgzone_config, show_step_config, show_multi_delete_confirm
                    ) and row_rect.collidepoint(mx, my):
                        sidebar_list_tooltip = (mx, my, item)
                y_ptr += LINE_H

            _rt_sb = _editor_right_map_list_top()
            _rch_sb = _editor_right_map_content_height(
                categories, LINE_H, right_asset_collapsed
            )
            scroll_y_right, _ = _editor_paint_sidebar_scrollbar(
                screen, SCREEN_W - right_panel_w, right_sidebar_w, _rt_sb, _vb, _rch_sb, scroll_y_right
            )

        elif edit_mode == "EVENT" and right_panel_w > 0:
            if current_event_id:
                # 선택된 이벤트 정보 표시
                evt_title = all_events[current_event_type][current_event_id].get('title', 'No Title')
                _hdr_x = SCREEN_W - right_panel_w + 10
                _hdr_w = max(40, right_sidebar_w - 20)
                ev_line = f"EVENT: {current_event_id}"
                ev_vis, _he = _editor_truncate_text_to_width(title_font, ev_line, _hdr_w)
                screen.blit(title_font.render(ev_vis, True, (255, 255, 100)), (_hdr_x, 45))
                title_line = f"Title: {evt_title}"
                tl_vis, _te = _editor_truncate_text_to_width(font, title_line, _hdr_w)
                screen.blit(font.render(tl_vis, True, (200, 200, 200)), (_hdr_x, 70))
                
                pygame.draw.line(screen, (100, 100, 100), (SCREEN_W - right_panel_w + 5, 95), (SCREEN_W - 5, 95))
                
                # [스텝 리스트 출력 시작]
                steps = all_events[current_event_type][current_event_id].get('steps', [])
                s_y = EDITOR_RIGHT_STEPS_TOP + scroll_y_steps
                if not steps:
                    ins0 = pygame.Rect(SCREEN_W - right_panel_w + 10, s_y, 18, 18)
                    if 90 < s_y < sidebar_list_bottom:
                        pygame.draw.rect(screen, (60, 60, 60), ins0)
                        pygame.draw.rect(screen, (120, 120, 120), ins0, 1)
                        screen.blit(font.render("+", True, (220, 220, 220)), (ins0.x + 5, ins0.y + 1))
                        if _editor_step_list_tooltip_ok(
                            show_event_config, show_zone_config, show_bgzone_config, show_multi_delete_confirm
                        ) and ins0.collidepoint(mx, my):
                            sidebar_list_tooltip = (mx, my, ["맨 앞에 스텝 삽입"])
                for i, step in enumerate(steps):
                    step_head, step_detail, step_tooltip = _editor_step_list_summary(i, step)
                    color = (255, 255, 0) if i == selected_step_idx else (180, 180, 180)
                    vb = pygame.Rect(SCREEN_W - 60, s_y + 2, 50, LINE_H - 6)
                    if 90 < s_y < sidebar_list_bottom:
                        _rbx_step = SCREEN_W - right_panel_w
                        _tx_step = _rbx_step + 15
                        _vb_x = SCREEN_W - 60
                        max_sw = max(24, _vb_x - 6 - _tx_step)
                        step_vis, _st = _editor_step_list_visible_line(
                            font, step_head, step_detail, max_sw, min_detail_chars=10
                        )
                        screen.blit(font.render(step_vis, True, color), (_tx_step, s_y))
                        row_rect = pygame.Rect(_rbx_step + 8, s_y - 1, right_sidebar_w - 16, LINE_H + 2)
                        if _editor_step_list_tooltip_ok(
                            show_event_config, show_zone_config, show_bgzone_config, show_multi_delete_confirm
                        ) and (row_rect.collidepoint(mx, my) or vb.collidepoint(mx, my)):
                            sidebar_list_tooltip = (mx, my, step_tooltip)
                    # 삽입(+) 버튼 (스텝 앞 — i==0 이면 맨 앞 삽입)
                    ins = pygame.Rect(SCREEN_W - right_panel_w + 10, s_y - 12, 18, 18)
                    if 90 < s_y < sidebar_list_bottom:
                        pygame.draw.rect(screen, (60, 60, 60), ins)
                        pygame.draw.rect(screen, (120, 120, 120), ins, 1)
                        screen.blit(font.render("+", True, (220, 220, 220)), (ins.x + 5, ins.y + 1))
                        if _editor_step_list_tooltip_ok(
                            show_event_config, show_zone_config, show_bgzone_config, show_multi_delete_confirm
                        ) and ins.collidepoint(mx, my):
                            tip = "맨 앞에 스텝 삽입" if i == 0 else f"스텝 {i} 앞에 삽입"
                            sidebar_list_tooltip = (mx, my, [tip])

                    # View 버튼
                    if 90 < s_y < sidebar_list_bottom:
                        pygame.draw.rect(screen, (55, 75, 100), vb)
                        pygame.draw.rect(screen, (130, 160, 200), vb, 1)
                        screen.blit(font.render("View", True, (220, 230, 255)), (vb.x + 6, vb.y + 2))

                    s_y += LINE_H
                
                # [+] 스텝 추가 버튼 (임시 시각화)
                add_step_rect = pygame.Rect(SCREEN_W - right_panel_w + 10, s_y + 12, 120, 26)
                if add_step_rect.y < SCREEN_H - 10:
                    pygame.draw.rect(screen, (60, 80, 60), add_step_rect)
                    pygame.draw.rect(screen, (120, 160, 120), add_step_rect, 1)
                    screen.blit(font.render("+ ADD STEP", True, (255, 255, 255)), (add_step_rect.x + 10, add_step_rect.y + 5))
            else:
                screen.blit(font.render("Select an event from left", True, (120, 120, 120)), (SCREEN_W - right_panel_w + 10, 100))

            if current_event_id and current_event_type:
                _steps_sb = all_events[current_event_type][current_event_id].get("steps", [])
                scroll_y_steps, _ = _editor_paint_sidebar_scrollbar(
                    screen,
                    SCREEN_W - right_panel_w,
                    right_sidebar_w,
                    EDITOR_RIGHT_STEPS_TOP,
                    sidebar_list_bottom,
                    len(_steps_sb) * LINE_H + 40,
                    scroll_y_steps,
                )












        # 하단 고정 영역(인스펙터 + 상태줄) 배경
        _chrome_y = SCREEN_H - EDITOR_MAP_BOTTOM_H
        pygame.draw.rect(screen, (18, 20, 24), (0, _chrome_y, SCREEN_W, EDITOR_MAP_BOTTOM_H))
        pygame.draw.line(screen, (58, 62, 72), (0, _chrome_y), (SCREEN_W, _chrome_y), 1)

        # [하단] EVENT 미리보기 엔티티 — 상호작용 설정 (MAP 인스펙터와 동일 버튼 배치)
        if edit_mode == "EVENT" and event_preview_sel and current_event_id:
            L = _editor_map_obj_inspector_layout(SCREEN_W, SCREEN_H, sidebar_w)
            pygame.draw.rect(screen, (24, 22, 32), L["bar"])
            ix = L["ix"]
            nm = str(event_preview_sel)
            kind = "NPC" if nm in CHAR_ASSETS else ("OBJ" if nm in OBJ_ASSETS else "?")
            screen.blit(
                font.render(f"미리보기: {nm} ({kind})", True, (220, 210, 255)),
                (ix, L["bar"].y + 8),
            )
            screen.blit(
                font.render("클릭=선택 · 더블클릭=타입 설정", True, (130, 140, 170)),
                (ix, L["bar"].y + 28),
            )
            btn_type = pygame.Rect(L["bar"].right - 210, L["bar"].y + 6, 96, 22)
            btn_inst = pygame.Rect(L["bar"].right - 108, L["bar"].y + 6, 96, 22)
            pygame.draw.rect(screen, (48, 42, 70), btn_type)
            pygame.draw.rect(screen, (170, 140, 220), btn_type, 1)
            screen.blit(font.render("타입 설정", True, (240, 230, 255)), (btn_type.x + 10, btn_type.y + 4))
            ent_on_map, ent_kind = _editor_find_map_entity_by_name(event_preview_sel, objs, npcs)
            if ent_on_map:
                pygame.draw.rect(screen, (42, 48, 62), btn_inst)
                pygame.draw.rect(screen, (140, 170, 210), btn_inst, 1)
                screen.blit(
                    font.render("맵 인스턴스", True, (220, 235, 255)),
                    (btn_inst.x + 6, btn_inst.y + 4),
                )
            else:
                screen.blit(
                    font.render("(맵에 없음 → 타입만)", True, (110, 115, 135)),
                    (btn_inst.x - 148, btn_inst.y + 4),
                )

        # [하단] 단일 오브젝트/NPC 선택 시 height / sprite_tilt (두 줄·좌측 정렬)
        if edit_mode == "MAP" and map_tool == "OBJECTS" and len(selected_nodes) == 1:
            L = _editor_map_obj_inspector_layout(SCREEN_W, SCREEN_H, sidebar_w)
            pygame.draw.rect(screen, (22, 24, 28), L["bar"])
            hr = L["height_rect"]
            tr = L["tilt_rect"]
            yr = L.get("ysort_rect")
            lr = L.get("layer_rect")
            ix, row_h, row_t = L["ix"], L["row_h"], L["row_t"]
            n0 = selected_nodes[0]
            screen.blit(font.render("높이(px)", True, (195, 205, 225)), (ix, row_h + 3))
            pygame.draw.rect(screen, (14, 14, 18), hr)
            hc = (220, 235, 255) if obj_height_active else (110, 120, 140)
            pygame.draw.rect(screen, hc, hr, 1)
            hdisp = obj_height_buf if obj_height_active else str(
                int(round(float(getattr(n0, "height", 0) or 0)))
            )
            screen.blit(font.render(hdisp, True, (235, 240, 250)), (hr.x + 4, hr.y + 3))
            screen.blit(font.render("틸트(0=flat ~ 1=upright)", True, (195, 205, 225)), (ix, row_t + 3))
            pygame.draw.rect(screen, (14, 14, 18), tr)
            c = (220, 235, 255) if obj_sprite_tilt_active else (110, 120, 140)
            pygame.draw.rect(screen, c, tr, 1)
            disp = obj_sprite_tilt_buf if obj_sprite_tilt_active else str(
                round(float(getattr(n0, "sprite_tilt", 1.0)), 4)
            )
            screen.blit(font.render(disp, True, (235, 240, 250)), (tr.x + 4, tr.y + 3))
            if yr:
                cur_m = str(getattr(n0, "ysort_mode", "ground") or "ground").strip().lower()
                label = "정렬: 땅" if cur_m != "visual" else "정렬: 이미지"
                pygame.draw.rect(screen, (14, 14, 18), yr)
                pygame.draw.rect(screen, (110, 120, 140), yr, 1)
                screen.blit(font.render(label, True, (235, 240, 250)), (yr.x + 8, yr.y + 3))
            if lr:
                pygame.draw.rect(screen, (14, 14, 18), lr)
                lc = (220, 235, 255) if obj_layer_active else (110, 120, 140)
                pygame.draw.rect(screen, lc, lr, 1)
                ldisp = obj_layer_buf if obj_layer_active else str(int(getattr(n0, "layer", 0) or 0))
                screen.blit(font.render(f"layer: {ldisp}", True, (235, 240, 250)), (lr.x + 8, lr.y + 3))
            if n0 in npcs:
                btn_type = pygame.Rect(L["bar"].right - 210, L["bar"].y + 6, 96, 22)
                btn_inst = pygame.Rect(L["bar"].right - 108, L["bar"].y + 6, 96, 22)
                pygame.draw.rect(screen, (45, 70, 55), btn_type)
                pygame.draw.rect(screen, (120, 180, 130), btn_type, 1)
                screen.blit(font.render("타입 설정", True, (220, 255, 230)), (btn_type.x + 6, btn_type.y + 4))
                pygame.draw.rect(screen, (45, 55, 80), btn_inst)
                pygame.draw.rect(screen, (130, 160, 200), btn_inst, 1)
                screen.blit(font.render("맵 인스턴스", True, (220, 230, 255)), (btn_inst.x + 6, btn_inst.y + 4))
            elif n0 in objs:
                btn_ot = pygame.Rect(L["bar"].right - 210, L["bar"].y + 6, 96, 22)
                btn_oi = pygame.Rect(L["bar"].right - 108, L["bar"].y + 6, 96, 22)
                pygame.draw.rect(screen, (55, 48, 30), btn_ot)
                pygame.draw.rect(screen, (180, 150, 90), btn_ot, 1)
                screen.blit(font.render("타입 이벤트", True, (255, 240, 210)), (btn_ot.x + 4, btn_ot.y + 4))
                pygame.draw.rect(screen, (48, 42, 70), btn_oi)
                pygame.draw.rect(screen, (150, 140, 200), btn_oi, 1)
                screen.blit(font.render("맵 이벤트", True, (230, 225, 255)), (btn_oi.x + 10, btn_oi.y + 4))
            hint = "NPC/OBJ: [C]spawn [D]progress [A]bindings · 숨김=청색 윤곽 고스트"
            screen.blit(font.render(hint, True, (120, 135, 160)), (ix, L["bar"].bottom - 16))

        # [하단 상태바] - 레이어 최상단에 배치하여 가림 방지
        pygame.draw.rect(
            screen, (15, 15, 15), (0, SCREEN_H - EDITOR_STATUS_BAR_H, SCREEN_W, EDITOR_STATUS_BAR_H)
        )
        _thumb_st = "smooth" if editor_smooth_sidebar_thumbs else "pixel"
        status_txt = (
            f"[{edit_mode}] MAP: {map_id} | ZOOM: {zoom_level:.1f}x | POS: {int(wx)},{int(wy)}"
            f" | THUMB:{_thumb_st} (F8)"
        )
        if selected_nodes:
            if len(selected_nodes) == 1:
                status_txt += f" | SELECTED: {selected_nodes[0].name}"
                if edit_mode == "MAP" and map_tool == "OBJECTS":
                    status_txt += " | 높이·틸트: 바로 위 회색 줄"
            else:
                status_txt += f" | SELECTED x{len(selected_nodes)}"
        if edit_mode == "FLOW" and 0 <= flow_selected_entity_idx < len(flow_entity_entries):
            se = flow_entity_entries[flow_selected_entity_idx]
            status_txt += f" | FLOW: {se.get('label', se.get('name', ''))}"
        if edit_mode == "EVENT" and current_event_id and current_event_type:
            stp = all_events[current_event_type][current_event_id].get("steps", [])
            upi = _preview_upto_index(
                show_step_config, step_edit_index, step_insert_index, stp, selected_step_idx
            )
            if upi >= 0:
                status_txt += f" | EV preview thru step {upi}"
            if event_preview_sel:
                status_txt += f" | preview: {event_preview_sel}"
        
        screen.blit(
            font.render(status_txt, True, (0, 255, 0)),
            (15, SCREEN_H - EDITOR_STATUS_BAR_H + 8),
        )

        # KEYDOWN이 들어오는지 확실히 보이게 하단에 표시(최근 2초)
        if debug_last_key:
            try:
                now_t = pygame.time.get_ticks()
                if now_t - int(debug_last_key_t or 0) <= 2000:
                    screen.blit(
                        font.render(f"[KEY] {debug_last_key}", True, (255, 200, 120)),
                        (SCREEN_W - 200, SCREEN_H - EDITOR_STATUS_BAR_H + 8),
                    )
            except Exception:
                pass

        # 내보내기 결과를 하단 상태바에 잠깐 표시
        if last_export_msg:
            try:
                now_t = pygame.time.get_ticks()
                if now_t - int(last_export_msg_t or 0) <= 2500:
                    screen.blit(
                        font.render(last_export_msg, True, (255, 220, 80)),
                        (15, SCREEN_H - 45),
                    )
            except Exception:
                pass


















        # --- [UI] 이벤트 설정 팝업창 ---
        if show_event_config:
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            screen.blit(overlay, (0, 0))

            rows_ev_d = _event_modal_rows(input_fields.get("cat", "LOCAL"))
            panel_rect, content_h_ev_d, _ = _editor_std_modal_rect(SCREEN_W, SCREEN_H, len(rows_ev_d))
            _editor_paint_modal_overlay(
                screen,
                title_font,
                font,
                "EVENT SETTINGS",
                panel_rect,
                rows_ev_d,
                event_modal_scroll,
                input_fields,
                active_field,
            )
            save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
            canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)
            pygame.draw.rect(screen, (0, 100, 0), save_btn)
            pygame.draw.rect(screen, (100, 0, 0), canc_btn)
            screen.blit(font.render("SAVE", True, (255, 255, 255)), (save_btn.x + 25, save_btn.y + 7))
            screen.blit(font.render("CANCEL", True, (255, 255, 255)), (canc_btn.x + 15, canc_btn.y + 7))

            dd_item_ev = 22
            event_modal_dd_ui = None
            if event_modal_dd_open and event_modal_dd_rect and event_modal_dd_options:
                cv = str(input_fields.get(event_modal_dd_key or "", "") or "")
                try:
                    ci = event_modal_dd_options.index(cv)
                except ValueError:
                    ci = -1
                event_modal_dd_ui = _draw_dropdown_with_scrollbar(
                    screen,
                    font,
                    event_modal_dd_rect,
                    event_modal_dd_options,
                    ci,
                    event_modal_dd_scroll,
                    dd_item_ev,
                    colors={},
                )

        if char_def_modal.show:
            char_def_modal.draw(screen, title_font, font, _editor_char_modal_ctx())
        if char_inst_modal.show:
            char_inst_modal.draw(screen, title_font, font, _editor_char_modal_ctx())
        if obj_def_modal.show:
            obj_def_modal.draw(screen, title_font, font, _editor_char_modal_ctx())
        if obj_inst_modal.show:
            obj_inst_modal.draw(screen, title_font, font, _editor_char_modal_ctx())
        if presence_zone_modal.show:
            presence_zone_modal.draw(screen, title_font, font, _editor_char_modal_ctx())

        # --- [UI] 이벤트 박스(event_zones) 설정 팝업창 ---
        if show_zone_config:
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            screen.blit(overlay, (0, 0))

            rows_zn_d = _zone_modal_rows()
            panel_rect, content_h_zn_d, _ = _editor_std_modal_rect(SCREEN_W, SCREEN_H, len(rows_zn_d))
            _editor_paint_modal_overlay(
                screen,
                title_font,
                font,
                "EVENT BOX SETTINGS",
                panel_rect,
                rows_zn_d,
                zone_modal_scroll,
                zone_fields,
                active_zone_field,
            )
            save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
            canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)
            pygame.draw.rect(screen, (0, 100, 0), save_btn)
            pygame.draw.rect(screen, (100, 0, 0), canc_btn)
            screen.blit(font.render("SAVE", True, (255, 255, 255)), (save_btn.x + 25, save_btn.y + 7))
            screen.blit(font.render("CANCEL", True, (255, 255, 255)), (canc_btn.x + 15, canc_btn.y + 7))

            dd_item_zn = 22
            zone_modal_dd_ui = None
            if zone_modal_dd_open and zone_modal_dd_rect and zone_modal_dd_options:
                cv = str(zone_fields.get(zone_modal_dd_key or "", "") or "")
                try:
                    ci = zone_modal_dd_options.index(cv)
                except ValueError:
                    ci = -1
                zone_modal_dd_ui = _draw_dropdown_with_scrollbar(
                    screen,
                    font,
                    zone_modal_dd_rect,
                    zone_modal_dd_options,
                    ci,
                    zone_modal_dd_scroll,
                    dd_item_zn,
                    colors={},
                )

        # --- [UI] 배경 박스(bg_zones) 설정 팝업창 ---
        if show_bgzone_config:
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            screen.blit(overlay, (0, 0))

            rows_bg_d = _bgzone_modal_rows()
            panel_rect, content_h_bg_d, _ = _editor_std_modal_rect(SCREEN_W, SCREEN_H, len(rows_bg_d))
            _editor_paint_modal_overlay(
                screen,
                title_font,
                font,
                "BG BOX SETTINGS",
                panel_rect,
                rows_bg_d,
                bgzone_modal_scroll,
                bgzone_fields,
                active_bgzone_field,
                area_theme="bgzone",
            )
            save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
            canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)
            pygame.draw.rect(screen, (0, 100, 0), save_btn)
            pygame.draw.rect(screen, (100, 0, 0), canc_btn)
            screen.blit(font.render("SAVE", True, (255, 255, 255)), (save_btn.x + 25, save_btn.y + 7))
            screen.blit(font.render("CANCEL", True, (255, 255, 255)), (canc_btn.x + 15, canc_btn.y + 7))

            dd_item_bg = 22
            bgzone_modal_dd_ui = None
            if bgzone_modal_dd_open and bgzone_modal_dd_rect and bgzone_modal_dd_options:
                cv = str(bgzone_fields.get(bgzone_modal_dd_key or "", "") or "")
                try:
                    ci = bgzone_modal_dd_options.index(cv)
                except ValueError:
                    ci = -1
                bgzone_modal_dd_ui = _draw_dropdown_with_scrollbar(
                    screen,
                    font,
                    bgzone_modal_dd_rect,
                    bgzone_modal_dd_options,
                    ci,
                    bgzone_modal_dd_scroll,
                    dd_item_bg,
                    colors={},
                )

        # 영역 지정 안내 텍스트(마우스 따라다님)
        if is_selecting_zone_rect:
            msg = f"영역 지정 (드래그) · {GRID_SIZE}px 격자 스냅 · Shift=미세"
            screen.blit(font.render(msg, True, (0, 255, 0)), (mx + 15, my + 15))
        if is_selecting_bgzone_rect:
            msg = f"BG 영역 지정 (드래그) · {GRID_SIZE}px 격자 스냅 · Shift=미세"
            screen.blit(font.render(msg, True, (80, 160, 255)), (mx + 15, my + 15))
        if is_selecting_presence_rect:
            msg = f"PRESENCE 영역 지정 (드래그) · {GRID_SIZE}px 격자 스냅 · Shift=미세"
            screen.blit(font.render(msg, True, (255, 120, 180)), (mx + 15, my + 15))
        if is_picking_zone_target:
            screen.blit(
                font.render("맵에서 Target 픽 (오브젝트/NPC 클릭) · ESC 취소", True, (255, 220, 160)),
                (mx + 15, my + 18),
            )
        if is_picking_step_waypoints:
            _prx, _pry = editor_snap_pick_world_xy(wx, wy, GRID_SIZE, is_shift_pressed)
            _mode = "Shift 미세" if is_shift_pressed else f"{GRID_SIZE}px 격자"
            screen.blit(
                font.render(f"웨이포인트 추가 → ({_prx},{_pry})  [{_mode}] · ESC 복귀", True, (180, 210, 255)),
                (mx + 15, my + 18),
            )
        elif is_picking_step_pos:
            _prx, _pry = editor_snap_pick_world_xy(wx, wy, GRID_SIZE, is_shift_pressed)
            _mode = "Shift 미세" if is_shift_pressed else f"{GRID_SIZE}px 격자"
            screen.blit(
                font.render(f"좌표 픽 → ({_prx},{_pry})  [{_mode}] · ESC 취소", True, (200, 255, 200)),
                (mx + 15, my + 18),
            )

        # --- [UI] 스텝 설정 팝업창 ---
        if show_step_config:
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            screen.blit(overlay, (0, 0))

            panel_rect = _step_settings_panel_rect(SCREEN_W, SCREEN_H, step_fields)
            pygame.draw.rect(screen, (40, 40, 40), panel_rect)
            pygame.draw.rect(screen, (200, 200, 200), panel_rect, 2)

            y_off = panel_rect.y + 20
            screen.blit(title_font.render("STEP SETTINGS", True, (255, 255, 255)), (panel_rect.x + 20, y_off))
            screen.blit(
                font.render(
                    "※ 이벤트 한 단계 = 스텝. 위 Type 변경 후 아래 필드 입력 → SAVE",
                    True,
                    (120, 155, 130),
                ),
                (panel_rect.x + 20, y_off + 28),
            )

            # Type
            y_off += 50
            t_color = (255, 255, 0) if active_step_field == "type" else (200, 200, 200)
            screen.blit(font.render("Type", True, t_color), (panel_rect.x + 20, y_off))
            type_rect = pygame.Rect(panel_rect.x + 180, y_off - 5, 280, 30)
            pygame.draw.rect(screen, (20, 20, 20), type_rect)
            pygame.draw.rect(screen, t_color, type_rect, 1)
            screen.blit(font.render(step_fields.get("type", "MOVE"), True, (255, 255, 255)), (type_rect.x + 5, type_rect.y + 5))

            draw_t_cur = (step_fields.get("type") or "MOVE").upper()
            step_body_sb_ui = None
            rows_draw = _step_field_rows(step_fields.get("type", "MOVE"))
            scroll_draw = step_body_scroll
            body_clip_rect, sb_draw_rect, max_body_scroll, ch_draw = _step_overlay_body_geometry(panel_rect, rows_draw)
            step_body_scroll = min(step_body_scroll, max_body_scroll)
            prev_clip_fields = screen.get_clip()
            screen.set_clip(body_clip_rect)

            cy = 0
            d_titem_h = 22
            steps_draw_ref = []
            before_ix_draw = 0
            if current_event_id and current_event_type:
                steps_draw_ref = all_events[current_event_type][current_event_id].get("steps", [])
                if step_edit_index is not None:
                    before_ix_draw = int(step_edit_index)
                elif step_insert_index is not None:
                    before_ix_draw = int(step_insert_index)
                else:
                    before_ix_draw = len(steps_draw_ref)
            for label, key in rows_draw:
                y_ptr = panel_rect.y + 120 + cy - scroll_draw
                if key.startswith("_hint"):
                    show_hint = (
                        body_clip_rect is not None
                        and y_ptr + STEP_BODY_ROW_H > body_clip_rect.top
                        and y_ptr < body_clip_rect.bottom
                    )
                    if show_hint:
                        _editor_paint_wrapped_label(
                            screen,
                            font,
                            label,
                            panel_rect.x + 20,
                            y_ptr + 6,
                            panel_rect.width - 40,
                            (130, 180, 130),
                            max_lines=3,
                        )
                    cy += STEP_BODY_ROW_H
                    continue
                if body_clip_rect is not None:
                    if y_ptr + STEP_BODY_ROW_H <= body_clip_rect.top or y_ptr >= body_clip_rect.bottom:
                        cy += STEP_BODY_ROW_H
                        continue
                color = (255, 255, 0) if active_step_field == key else (200, 200, 200)
                _editor_paint_wrapped_label(
                    screen,
                    font,
                    label,
                    panel_rect.x + 20,
                    y_ptr + 4,
                    STEP_MODAL_LABEL_W,
                    color,
                    max_lines=2,
                )
                dd_opts_d = _step_dropdown_field_options(
                    draw_t_cur,
                    key,
                    map_list=map_list,
                    steps_ref=steps_draw_ref,
                    before_ix=before_ix_draw,
                    player=player,
                    objs=objs,
                    npcs=npcs,
                    all_events=all_events,
                )
                if dd_opts_d is not None:
                    r = pygame.Rect(panel_rect.x + 180, y_ptr - 5, 220, 30)
                    list_btn = pygame.Rect(panel_rect.x + 180 + 225, y_ptr - 5, 52, 30)
                    pygame.draw.rect(screen, (20, 20, 20), r)
                    pygame.draw.rect(screen, color, r, 1)
                    screen.blit(font.render(str(step_fields.get(key, "")), True, (255, 255, 255)), (r.x + 5, r.y + 5))
                    pygame.draw.rect(screen, (50, 70, 90), list_btn)
                    pygame.draw.rect(screen, (120, 160, 200), list_btn, 1)
                    screen.blit(font.render("List", True, (230, 240, 255)), (list_btn.x + 8, list_btn.y + 7))
                elif key == "music" and draw_t_cur in ("SCREEN", "MUSIC_PLAY"):
                    r = pygame.Rect(panel_rect.x + 180, y_ptr - 5, 220, 30)
                    list_btn = pygame.Rect(panel_rect.x + 180 + 225, y_ptr - 5, 52, 30)
                    pygame.draw.rect(screen, (20, 20, 20), r)
                    pygame.draw.rect(screen, color, r, 1)
                    screen.blit(font.render(str(step_fields.get(key, "")), True, (255, 255, 255)), (r.x + 5, r.y + 5))
                    pygame.draw.rect(screen, (50, 70, 90), list_btn)
                    pygame.draw.rect(screen, (120, 160, 200), list_btn, 1)
                    screen.blit(font.render("List", True, (230, 240, 255)), (list_btn.x + 8, list_btn.y + 7))
                elif key == "anim" and draw_t_cur == "ACTION_ANIM":
                    r = pygame.Rect(panel_rect.x + 180, y_ptr - 5, 220, 30)
                    list_btn = pygame.Rect(panel_rect.x + 180 + 225, y_ptr - 5, 52, 30)
                    pygame.draw.rect(screen, (20, 20, 20), r)
                    pygame.draw.rect(screen, color, r, 1)
                    screen.blit(font.render(str(step_fields.get(key, "")), True, (255, 255, 255)), (r.x + 5, r.y + 5))
                    pygame.draw.rect(screen, (50, 70, 90), list_btn)
                    pygame.draw.rect(screen, (120, 160, 200), list_btn, 1)
                    screen.blit(font.render("List", True, (230, 240, 255)), (list_btn.x + 8, list_btn.y + 7))
                elif _step_row_entity_pick(draw_t_cur, key):
                    r = pygame.Rect(panel_rect.x + 180, y_ptr - 5, 220, 30)
                    list_btn = pygame.Rect(panel_rect.x + 180 + 225, y_ptr - 5, 52, 30)
                    pick_btn = pygame.Rect(panel_rect.x + 180 + 225 + 56, y_ptr - 5, 52, 30)
                    pygame.draw.rect(screen, (20, 20, 20), r)
                    pygame.draw.rect(screen, color, r, 1)
                    screen.blit(font.render(str(step_fields.get(key, "")), True, (255, 255, 255)), (r.x + 5, r.y + 5))
                    pygame.draw.rect(screen, (50, 70, 90), list_btn)
                    pygame.draw.rect(screen, (120, 160, 200), list_btn, 1)
                    screen.blit(font.render("List", True, (230, 240, 255)), (list_btn.x + 8, list_btn.y + 7))
                    pygame.draw.rect(screen, (70, 70, 55), pick_btn)
                    pygame.draw.rect(screen, (200, 200, 140), pick_btn, 1)
                    screen.blit(font.render("Pick", True, (250, 250, 230)), (pick_btn.x + 8, pick_btn.y + 7))
                else:
                    r = pygame.Rect(panel_rect.x + 180, y_ptr - 5, 280, 30)
                    pygame.draw.rect(screen, (20, 20, 20), r)
                    pygame.draw.rect(screen, color, r, 1)
                    screen.blit(font.render(str(step_fields.get(key, "")), True, (255, 255, 255)), (r.x + 5, r.y + 5))
                for px_key, _py_key in _step_coord_xy_pairs(draw_t_cur):
                    if key == px_key:
                        pick_btn = pygame.Rect(r.right - 86, r.y + 4, 78, 22)
                        pygame.draw.rect(screen, (60, 80, 60), pick_btn)
                        pygame.draw.rect(screen, (140, 170, 140), pick_btn, 1)
                        screen.blit(font.render("Pick", True, (255, 255, 255)), (pick_btn.x + 18, pick_btn.y + 3))
                        break
                if draw_t_cur == "MOVE" and key == "waypoints":
                    pick_wp = pygame.Rect(r.right - 86, r.y + 4, 78, 22)
                    pygame.draw.rect(screen, (55, 65, 95), pick_wp)
                    pygame.draw.rect(screen, (150, 170, 220), pick_wp, 1)
                    screen.blit(font.render("WP+", True, (235, 240, 255)), (pick_wp.x + 12, pick_wp.y + 3))
                cy += STEP_BODY_ROW_H

            if body_clip_rect is not None and prev_clip_fields is not None:
                screen.set_clip(prev_clip_fields)
                uix = _step_overlay_scrollbar_layout(sb_draw_rect, body_clip_rect.height, ch_draw, step_body_scroll)
                step_body_sb_ui = uix
                tr = uix.get("track")
                thm = uix.get("thumb")
                if tr is not None:
                    pygame.draw.rect(screen, (18, 18, 24), tr)
                if thm is not None:
                    pygame.draw.rect(screen, (110, 120, 150), thm, border_radius=3)
                    pygame.draw.rect(screen, (140, 150, 180), thm, 1, border_radius=3)

            if step_target_dropdown_open and step_target_options:
                yy_sync = panel_rect.y + 120
                fk = step_target_field_key or "target"
                sy = 0
                for _lb, ky in rows_draw:
                    yy_sync = panel_rect.y + 120 + sy - scroll_draw
                    if ky.startswith("_hint"):
                        sy += STEP_BODY_ROW_H
                        continue
                    if ky == fk:
                        n_opt = len(step_target_options)
                        dd_h = min(220, max(d_titem_h, n_opt * d_titem_h))
                        step_target_dropdown_rect = pygame.Rect(
                            panel_rect.x + 180,
                            yy_sync + 28,
                            280,
                            dd_h,
                        )
                        break
                    sy += STEP_BODY_ROW_H

            # Type 드롭다운 표시 (다른 입력란들 위에 덮이도록 맨 마지막에 그림)
            if step_type_dropdown_open:
                dropdown_item_h = 22
                max_h = 260
                dd_h = min(max_h, dropdown_item_h * len(step_type_cycle))
                dropdown_rect = pygame.Rect(type_rect.x, type_rect.bottom, type_rect.width, dd_h)
                cur_t = step_fields.get("type", "MOVE")
                try:
                    cur_i = step_type_cycle.index(cur_t)
                except ValueError:
                    cur_i = -1
                step_type_dd_ui = _draw_dropdown_with_scrollbar(
                    screen,
                    font,
                    dropdown_rect,
                    step_type_cycle,
                    cur_i,
                    step_type_scroll,
                    dropdown_item_h,
                    colors={},
                )

            if step_target_dropdown_open and step_target_dropdown_rect and step_target_options:
                dr = step_target_dropdown_rect
                step_target_dd_ui = _draw_dropdown_with_scrollbar(
                    screen,
                    font,
                    dr,
                    step_target_options,
                    -1,
                    step_target_scroll,
                    d_titem_h,
                    colors={},
                )

            save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
            canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)
            delete_btn = pygame.Rect(panel_rect.x + 20, panel_rect.bottom - 50, 100, 35)
            pygame.draw.rect(screen, (0, 100, 0), save_btn)
            pygame.draw.rect(screen, (100, 0, 0), canc_btn)
            if step_edit_index is not None:
                pygame.draw.rect(screen, (120, 60, 60), delete_btn)
                pygame.draw.rect(screen, (200, 140, 140), delete_btn, 1)
                screen.blit(font.render("DELETE", True, (255, 255, 255)), (delete_btn.x + 18, delete_btn.y + 7))
            screen.blit(font.render("SAVE", True, (255, 255, 255)), (save_btn.x + 25, save_btn.y + 7))
            screen.blit(font.render("CANCEL", True, (255, 255, 255)), (canc_btn.x + 15, canc_btn.y + 7))
            _editor_paint_modal_scroll_hint(screen, font, panel_rect)

            # 삭제 확인 모달
            if show_step_delete_confirm:
                confirm_rect = pygame.Rect(panel_rect.centerx - 160, panel_rect.centery - 70, 320, 140)
                pygame.draw.rect(screen, (30, 30, 30), confirm_rect)
                pygame.draw.rect(screen, (220, 220, 220), confirm_rect, 2)
                screen.blit(title_font.render("DELETE STEP?", True, (255, 255, 255)), (confirm_rect.x + 20, confirm_rect.y + 18))
                screen.blit(font.render("정말 삭제할까요? (되돌릴 수 없음)", True, (200, 200, 200)), (confirm_rect.x + 20, confirm_rect.y + 55))
                yes_btn = pygame.Rect(confirm_rect.x + 30, confirm_rect.bottom - 45, 110, 32)
                no_btn = pygame.Rect(confirm_rect.right - 140, confirm_rect.bottom - 45, 110, 32)
                pygame.draw.rect(screen, (100, 0, 0), yes_btn)
                pygame.draw.rect(screen, (60, 60, 60), no_btn)
                pygame.draw.rect(screen, (200, 200, 200), no_btn, 1)
                screen.blit(font.render("DELETE", True, (255, 255, 255)), (yes_btn.x + 24, yes_btn.y + 6))
                screen.blit(font.render("CANCEL", True, (255, 255, 255)), (no_btn.x + 22, no_btn.y + 6))












        if show_multi_delete_confirm:
            ov = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 185))
            screen.blit(ov, (0, 0))
            cw, ch = 440, 168
            confirm_rect = pygame.Rect(SCREEN_W // 2 - cw // 2, SCREEN_H // 2 - ch // 2, cw, ch)
            pygame.draw.rect(screen, (42, 42, 52), confirm_rect)
            pygame.draw.rect(screen, (230, 200, 120), confirm_rect, 2)
            screen.blit(
                title_font.render("선택 오브젝트 삭제?", True, (255, 255, 240)),
                (confirm_rect.x + 22, confirm_rect.y + 18),
            )
            screen.blit(
                font.render(
                    f"{len(selected_nodes)}개를 삭제합니다. 되돌릴 수 없습니다.",
                    True,
                    (210, 210, 215),
                ),
                (confirm_rect.x + 22, confirm_rect.y + 52),
            )
            yes_btn = pygame.Rect(confirm_rect.x + 28, confirm_rect.bottom - 48, 160, 36)
            no_btn = pygame.Rect(confirm_rect.right - 188, confirm_rect.bottom - 48, 160, 36)
            pygame.draw.rect(screen, (120, 40, 40), yes_btn)
            pygame.draw.rect(screen, (55, 55, 65), no_btn)
            pygame.draw.rect(screen, (200, 200, 210), no_btn, 1)
            screen.blit(font.render("삭제", True, (255, 255, 255)), (yes_btn.x + 58, yes_btn.y + 10))
            screen.blit(font.render("취소", True, (255, 255, 255)), (no_btn.x + 58, no_btn.y + 10))

        if sidebar_list_tooltip:
            _tmx, _tmy, _ttxt = sidebar_list_tooltip
            _editor_draw_hover_tooltip(screen, font, SCREEN_W, SCREEN_H, _tmx, _tmy, _ttxt)

        pygame.display.flip()
        pygame.time.Clock().tick(60)

    pygame.quit()

if __name__ == "__main__":
    editor_main()

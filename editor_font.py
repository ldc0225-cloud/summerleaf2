"""에디터 FONT 설정 — 용도별(슬롯) 폰트 프로필 편집.

상단바 FONT → 왼쪽 용도 목록 / 오른쪽 종류·크기·색·테두리.
저장: ui.state.json (profiles + layout) + CONFIG.UI_FONT_PROFILES
(구 ui_font_settings.json 은 로드 폴백만; 에디터 UI 상태 editor_ui_state.json 은 별도)
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pygame

import editor_text as ed_txt

from data import (
    CONFIG,
    UI_FONT_FILES,
    UI_FONT_PROFILE_ORDER,
    UI_STATE_PATH,
    ensure_ui_font_profiles,
    save_ui_font_settings,
    sync_legacy_font_keys_from_profiles,
)

# 슬롯별 편집 필드 (key, 화면라벨, kind)
SLOT_FIELDS: List[Tuple[str, str, str]] = [
    ("font_key", "폰트 종류 (레지스트리 키)", "font_key"),
    ("size_320", "크기 (320 기준)", "float"),
    ("color", "글자 색 RGB", "rgb"),
    ("outline_enabled", "테두리 on (1/0)", "bool"),
    ("outline_px_320", "테두리 두께 (320)", "float"),
    ("outline_color", "테두리 색 RGB", "rgb"),
    ("antialias", "부드러운 AA (1/0)", "bool"),
    ("soft_px_320", "테두리 소프트(0=선명)", "float"),
    ("force_color", "글자색 강제 (1/0)", "bool"),
]

GLOBAL_FIELDS: List[Tuple[str, str, str]] = [
    ("UI_TEXT_REFERENCE_WIDTH", "전체 텍스트 기준폭", "float"),
]


def new_state() -> dict:
    return {
        "show": False,
        "slot": "dialog",
        "settings_fields": {},
        "global_fields": {},
        "settings_scroll": 0,
        "_edit_field": None,
        "msg": "",
        "text_edit": ed_txt.EditSession(),
    }


def _te(state) -> ed_txt.EditSession:
    te = state.get("text_edit")
    if not isinstance(te, ed_txt.EditSession):
        te = ed_txt.EditSession()
        state["text_edit"] = te
    return te


def _rgb_to_text(v) -> str:
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return f"{int(v[0])}, {int(v[1])}, {int(v[2])}"
    return "0, 0, 0"


def _parse_rgb(text: str, default=(0, 0, 0)) -> Tuple[int, int, int]:
    t = str(text or "").strip().replace("(", "").replace(")", "").replace("[", "").replace("]", "")
    parts = [p.strip() for p in t.split(",") if p.strip()]
    if len(parts) >= 3:
        try:
            return (int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
        except (TypeError, ValueError):
            pass
    return (int(default[0]), int(default[1]), int(default[2]))


def _parse_bool(s, default=True) -> bool:
    t = str(s if s is not None else default).strip().lower()
    if t in ("1", "true", "yes", "on"):
        return True
    if t in ("0", "false", "no", "off"):
        return False
    return bool(default)


def _parse_float(s, default=0.0) -> float:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return float(default)


def _slot_ids() -> List[str]:
    profiles = ensure_ui_font_profiles()
    ordered = [s for s in UI_FONT_PROFILE_ORDER if s in profiles]
    for s in profiles:
        if s not in ordered:
            ordered.append(s)
    return ordered or ["ui"]


def load_slot_fields(slot: str) -> Dict[str, str]:
    profiles = ensure_ui_font_profiles()
    p = profiles.get(slot) or profiles.get("ui") or {}
    fields: Dict[str, str] = {}
    for key, _lab, kind in SLOT_FIELDS:
        v = p.get(key)
        if kind == "rgb":
            fields[key] = _rgb_to_text(v if v is not None else (0, 0, 0))
        elif kind == "bool":
            # antialias 기본 True, force/outline도 True 쪽 — 키가 없으면 기본 반영
            if v is None:
                if key == "antialias":
                    v = True
                elif key in ("outline_enabled", "force_color"):
                    v = True
                else:
                    v = False
            fields[key] = "1" if bool(v) else "0"
        elif kind == "font_key":
            fields[key] = str(v or "default")
        else:
            if key == "soft_px_320" and (v is None or str(v).strip() == ""):
                fields[key] = "0"
            else:
                fields[key] = str(v if v is not None else "")
    return fields


def load_global_fields() -> Dict[str, str]:
    return {
        "UI_TEXT_REFERENCE_WIDTH": str(CONFIG.get("UI_TEXT_REFERENCE_WIDTH", 320) or 320),
    }


def open_modal(state: dict) -> None:
    state["show"] = True
    ids = _slot_ids()
    if state.get("slot") not in ids:
        state["slot"] = ids[0]
    state["settings_fields"] = load_slot_fields(state["slot"])
    state["global_fields"] = load_global_fields()
    state["settings_scroll"] = 0
    state["_edit_field"] = None
    state["msg"] = "용도별 폰트 — 저장 시 게임에 즉시 반영"


def _apply_slot_fields_to_profile(slot: str, fields: dict) -> None:
    profiles = ensure_ui_font_profiles()
    p = dict(profiles.get(slot) or {})
    for key, _lab, kind in SLOT_FIELDS:
        raw = fields.get(key, "")
        if kind == "rgb":
            p[key] = _parse_rgb(str(raw), (0, 0, 0))
        elif kind == "bool":
            p[key] = _parse_bool(raw, True)
        elif kind == "float":
            p[key] = _parse_float(raw, float(p.get(key, 1) or 1))
        elif kind == "font_key":
            p[key] = str(raw or "default").strip() or "default"
    # 메타(label/desc)는 기본값 유지
    from data import UI_FONT_PROFILE_DEFAULTS

    base = UI_FONT_PROFILE_DEFAULTS.get(slot) or {}
    p.setdefault("label", base.get("label", slot))
    p.setdefault("desc", base.get("desc", ""))
    profiles[slot] = p
    CONFIG["UI_FONT_PROFILES"] = profiles


def apply_settings_fields(state: dict) -> bool:
    """현재 슬롯 + 전역값 → CONFIG / JSON / 캐시 클리어."""
    slot = str(state.get("slot") or "ui")
    fields = state.get("settings_fields") or load_slot_fields(slot)
    _apply_slot_fields_to_profile(slot, fields)
    g = state.get("global_fields") or load_global_fields()
    try:
        CONFIG["UI_TEXT_REFERENCE_WIDTH"] = _parse_float(
            g.get("UI_TEXT_REFERENCE_WIDTH", "320"), 320.0
        )
    except Exception:
        pass
    sync_legacy_font_keys_from_profiles()
    ok = bool(save_ui_font_settings())
    try:
        from engine import clear_ui_font_cache

        clear_ui_font_cache()
    except Exception:
        pass
    try:
        import main as main_mod

        if hasattr(main_mod, "_UI_FONT_CACHE"):
            main_mod._UI_FONT_CACHE.clear()
    except Exception:
        pass
    # 야구 로고 캐시
    try:
        import activities.baseball as bb

        if hasattr(bb, "_LOGO_FONT_CACHE"):
            bb._LOGO_FONT_CACHE.clear()
    except Exception:
        pass
    state["msg"] = f"저장됨 · [{slot}] → {UI_STATE_PATH}" if ok else "저장 실패"
    state["settings_fields"] = load_slot_fields(slot)
    return ok


def select_slot(state: dict, slot: str) -> None:
    """슬롯 전환 전 현재 편집값을 메모리 프로필에 반영(저장 전 미리보기용)."""
    cur = str(state.get("slot") or "ui")
    if cur:
        _apply_slot_fields_to_profile(cur, state.get("settings_fields") or {})
    state["slot"] = slot
    state["settings_fields"] = load_slot_fields(slot)
    state["_edit_field"] = None
    state["settings_scroll"] = 0


def cycle_font_key(state: dict) -> None:
    keys = list((UI_FONT_FILES or {}).keys()) or ["default", "dialog", "logo"]
    fields = state.setdefault("settings_fields", {})
    cur = str(fields.get("font_key", "default") or "default")
    try:
        ix = keys.index(cur)
    except ValueError:
        ix = -1
    fields["font_key"] = keys[(ix + 1) % len(keys)]


def apply_all_slots_like_current(state: dict) -> None:
    """현재 슬롯의 색/테두리/강제색을 모든 슬롯에 복사 (폰트키·크기는 유지)."""
    cur = str(state.get("slot") or "ui")
    fields = state.get("settings_fields") or load_slot_fields(cur)
    _apply_slot_fields_to_profile(cur, fields)
    profiles = ensure_ui_font_profiles()
    src = profiles.get(cur) or {}
    for sid in profiles:
        if sid == cur:
            continue
        p = dict(profiles[sid])
        for k in (
            "color",
            "outline_enabled",
            "outline_px_320",
            "outline_color",
            "force_color",
            "antialias",
            "soft_px_320",
        ):
            if k in src:
                p[k] = src[k]
        profiles[sid] = p
    CONFIG["UI_FONT_PROFILES"] = profiles
    state["msg"] = "현재 슬롯 색·테두리·AA를 전체 슬롯에 복사 (저장 버튼을 눌러 확정)"


def layout_settings_modal_ui(state, sw, sh) -> dict:
    w, h = min(720, max(560, sw - 40)), min(580, max(400, sh - 40))
    rect = pygame.Rect(sw // 2 - w // 2, sh // 2 - h // 2, w, h)
    list_w = 200
    list_rect = pygame.Rect(rect.x + 10, rect.y + 44, list_w, rect.height - 140)
    slot_rects = {}
    y = list_rect.y + 4
    for sid in _slot_ids():
        slot_rects[sid] = pygame.Rect(list_rect.x + 4, y, list_w - 8, 28)
        y += 30
    fields = {}
    fx = list_rect.right + 12
    fy = rect.y + 70 - int(state.get("settings_scroll") or 0)
    field_w = rect.right - fx - 16
    for key, _lab, _kind in SLOT_FIELDS:
        fields[key] = pygame.Rect(fx + 150, fy, max(80, field_w - 150), 24)
        fy += 28
    for key, _lab, _kind in GLOBAL_FIELDS:
        fields[f"g:{key}"] = pygame.Rect(fx + 150, fy + 8, max(80, field_w - 150), 24)
        fy += 28
    by = rect.bottom - 44
    save = pygame.Rect(rect.x + 14, by, 88, 30)
    cancel = pygame.Rect(save.right + 8, by, 88, 30)
    cycle = pygame.Rect(cancel.right + 8, by, 100, 30)
    copy_all = pygame.Rect(cycle.right + 8, by, 130, 30)
    preview = pygame.Rect(list_rect.right + 12, rect.bottom - 100, rect.right - list_rect.right - 28, 44)
    return {
        "rect": rect,
        "list_rect": list_rect,
        "slot_rects": slot_rects,
        "fields": fields,
        "save": save,
        "cancel": cancel,
        "cycle": cycle,
        "copy_all": copy_all,
        "preview": preview,
        "slot_field_keys": [k for k, _, _ in SLOT_FIELDS],
        "global_field_keys": [f"g:{k}" for k, _, _ in GLOBAL_FIELDS],
    }


def draw_settings_modal(screen, font, state, sw, sh) -> dict:
    ui = layout_settings_modal_ui(state, sw, sh)
    rect = ui["rect"]
    dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 150))
    screen.blit(dim, (0, 0))
    pygame.draw.rect(screen, (36, 40, 50), rect, border_radius=8)
    pygame.draw.rect(screen, (200, 210, 230), rect, 2, border_radius=8)
    screen.blit(
        font.render("FONT 설정 — 용도별 게임 폰트", True, (255, 255, 200)),
        (rect.x + 14, rect.y + 10),
    )
    msg = str(state.get("msg") or "")
    if msg:
        screen.blit(font.render(msg[:64], True, (160, 210, 160)), (rect.x + 14, rect.y + 28))

    # 왼쪽 슬롯 목록
    pygame.draw.rect(screen, (28, 32, 40), ui["list_rect"], border_radius=4)
    profiles = ensure_ui_font_profiles()
    cur = str(state.get("slot") or "ui")
    for sid, sr in ui["slot_rects"].items():
        active = sid == cur
        pygame.draw.rect(screen, (70, 85, 60) if active else (45, 50, 60), sr, border_radius=3)
        if active:
            pygame.draw.rect(screen, (255, 215, 0), sr, 1, border_radius=3)
        lab = str((profiles.get(sid) or {}).get("label") or sid)
        screen.blit(font.render(lab[:16], True, (245, 248, 255)), (sr.x + 6, sr.y + 6))

    # 설명
    desc = str((profiles.get(cur) or {}).get("desc") or "")
    screen.blit(
        font.render(f"[{cur}] {desc}"[:56], True, (180, 195, 215)),
        (ui["list_rect"].right + 12, rect.y + 46),
    )

    fields_data = state.get("settings_fields") or {}
    global_data = state.get("global_fields") or {}
    clip = screen.get_clip()
    edit_area = pygame.Rect(
        ui["list_rect"].right + 8,
        rect.y + 66,
        rect.right - ui["list_rect"].right - 20,
        rect.height - 180,
    )
    screen.set_clip(edit_area)
    for key, lab, _kind in SLOT_FIELDS:
        fr = ui["fields"][key]
        if fr.bottom < edit_area.top or fr.top > edit_area.bottom:
            continue
        screen.blit(font.render(lab, True, (210, 220, 235)), (edit_area.x + 4, fr.y + 4))
        pygame.draw.rect(screen, (28, 32, 40), fr)
        active = state.get("_edit_field") == key
        pygame.draw.rect(screen, (255, 215, 0) if active else (110, 130, 160), fr, 1)
        val = str(fields_data.get(key, ""))
        ed_txt.blit_field_value(
            screen, font, val, fr, active=active, session=_te(state), color=(245, 248, 255), trunc_limit=36
        )
    for key, lab, _kind in GLOBAL_FIELDS:
        fk = f"g:{key}"
        fr = ui["fields"][fk]
        if fr.bottom < edit_area.top or fr.top > edit_area.bottom:
            continue
        screen.blit(font.render(lab, True, (180, 200, 160)), (edit_area.x + 4, fr.y + 4))
        pygame.draw.rect(screen, (28, 32, 40), fr)
        active = state.get("_edit_field") == fk
        pygame.draw.rect(screen, (255, 215, 0) if active else (110, 130, 160), fr, 1)
        val = str(global_data.get(key, ""))
        ed_txt.blit_field_value(
            screen, font, val, fr, active=active, session=_te(state), color=(245, 248, 255), trunc_limit=36
        )
    screen.set_clip(clip)

    # 미리보기 — 현재 편집값을 임시 적용 후 렌더
    prev = ui["preview"]
    pygame.draw.rect(screen, (90, 130, 95), prev, border_radius=4)
    sample = "Aa가나다 123 — 미리보기"
    try:
        from engine import clear_ui_font_cache, resolve_font_profile

        _apply_slot_fields_to_profile(cur, fields_data)
        clear_ui_font_cache()
        pf = resolve_font_profile(cur)
        col = _parse_rgb(fields_data.get("color", "0,0,0"), (0, 0, 0))
        surf = pf.render(sample, True, col)
        screen.blit(surf, (prev.x + 8, prev.y + max(2, (prev.height - surf.get_height()) // 2)))
    except Exception:
        screen.blit(font.render(sample, True, (0, 0, 0)), (prev.x + 8, prev.y + 10))

    for b, lab, col in (
        (ui["save"], "저장", (50, 90, 60)),
        (ui["cancel"], "닫기", (70, 50, 50)),
        (ui["cycle"], "폰트 순환", (50, 70, 100)),
        (ui["copy_all"], "색·테두리 전체복사", (70, 60, 40)),
    ):
        pygame.draw.rect(screen, col, b, border_radius=4)
        screen.blit(font.render(lab, True, (240, 248, 255)), (b.x + 6, b.y + 6))
    return ui


def handle_settings_modal_click(state, mx, my, ui) -> Optional[str]:
    if not ui:
        return None
    for sid, sr in (ui.get("slot_rects") or {}).items():
        if sr.collidepoint(mx, my):
            select_slot(state, sid)
            return None
    if ui["save"].collidepoint(mx, my):
        apply_settings_fields(state)
        state["show"] = False
        return "saved"
    if ui["cancel"].collidepoint(mx, my):
        state["show"] = False
        state.pop("_edit_field", None)
        return "closed"
    if ui["cycle"].collidepoint(mx, my):
        cycle_font_key(state)
        return None
    if ui["copy_all"].collidepoint(mx, my):
        apply_all_slots_like_current(state)
        return None
    for key, fr in (ui.get("fields") or {}).items():
        if fr.collidepoint(mx, my):
            state["_edit_field"] = key
            if str(key).startswith("g:"):
                gkey = str(key)[2:]
                cur = str((state.get("global_fields") or {}).get(gkey, ""))
            else:
                cur = str((state.get("settings_fields") or {}).get(key, ""))
            _te(state).focus(cur)
            return None
    return None


def handle_settings_modal_event(state, event, sw, sh, mx, my) -> bool:
    if not state.get("show"):
        return False
    if event.type == pygame.MOUSEWHEEL:
        state["settings_scroll"] = max(
            0, int(state.get("settings_scroll") or 0) - int(event.y) * 24
        )
        return True
    return False


def handle_textinput(state, text: str) -> bool:
    t = str(text or "")
    if not t:
        return False
    ef = state.get("_edit_field")
    if not (ef and state.get("show")):
        return False
    te = _te(state)
    if str(ef).startswith("g:"):
        gkey = str(ef)[2:]
        gfields = state.setdefault("global_fields", {})
        gfields[gkey] = te.insert(str(gfields.get(gkey, "")), t)
    else:
        fields = state.setdefault("settings_fields", {})
        fields[ef] = te.insert(str(fields.get(ef, "")), t)
    return True


def handle_keydown(state, event) -> bool:
    if event.type != pygame.KEYDOWN:
        return False
    if not state.get("show"):
        return False
    key = event.key
    if key == pygame.K_ESCAPE:
        state["show"] = False
        state.pop("_edit_field", None)
        return True
    ef = state.get("_edit_field")
    if ef:
        te = _te(state)
        if str(ef).startswith("g:"):
            gkey = str(ef)[2:]
            gfields = state.setdefault("global_fields", {})
            if key == pygame.K_RETURN:
                state.pop("_edit_field", None)
                return True
            nt, handled = te.keydown(str(gfields.get(gkey, "")), event)
            if handled:
                gfields[gkey] = nt
                return True
            return True
        else:
            fields = state.setdefault("settings_fields", {})
            if key == pygame.K_RETURN:
                state.pop("_edit_field", None)
                return True
            nt, handled = te.keydown(str(fields.get(ef, "")), event)
            if handled:
                fields[ef] = nt
                return True
            return True
    return False

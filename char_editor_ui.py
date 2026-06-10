"""에디터: char_defs 타입 기본값 / 맵 NPC 인스턴스 설정 모달."""
from __future__ import annotations

import json
import re

import pygame

from typing import Any, Callable, Dict, List, Optional, Tuple


ROW_H = 38
BOOL_OPTS = [("Yes", "true"), ("No", "false")]
BEHAVIOR_OPTS = [
    ("idle", "idle"),
    ("patrol", "patrol"),
    ("wander", "wander"),
    ("follow", "follow"),
    ("flee", "flee"),
    ("frozen", "frozen"),
]
BIND_SLOT_COUNT = 3
TALK_LINE_COUNT = 4


def _format_talk_when(when: Any) -> str:
    if when is None:
        return ""
    if isinstance(when, str):
        return when.strip()
    if isinstance(when, dict):
        if "expr" in when:
            return str(when.get("expr") or "").strip()
        parts = []
        if "not_flag" in when:
            parts.append(f"not_flag:{when['not_flag']}")
        if "flag" in when:
            parts.append(f"flag:{when['flag']}")
        if "mainprogress" in when:
            parts.append(f"mainprogress:{when['mainprogress']}")
        if "affinity_gte" in when:
            parts.append(f"affinity_gte:{when['affinity_gte']}")
        return ";".join(parts)
    return ""


def _parse_talk_when(s: str) -> Any:
    s = str(s or "").strip()
    if not s:
        return None
    if "==" in s or ">=" in s or "<=" in s or "!=" in s or (">" in s) or ("<" in s):
        return s
    return s


def _format_talk_after(after: Any) -> str:
    from char_behavior import format_talk_after_text

    return format_talk_after_text(after)


def _parse_talk_after(s: str) -> Any:
    from char_behavior import parse_talk_after_text

    t = str(s or "").strip()
    if not t:
        return None
    return parse_talk_after_text(t)


def _bindings_to_slot_fields(bindings, fields: dict) -> None:
    for i in range(1, BIND_SLOT_COUNT + 1):
        fields[f"bind{i}_cond"] = ""
        fields[f"bind{i}_event"] = ""
        fields[f"bind{i}_pri"] = "100"
    for i, b in enumerate(bindings or []):
        if i >= BIND_SLOT_COUNT or not isinstance(b, dict):
            break
        n = i + 1
        fields[f"bind{n}_cond"] = str(b.get("condition") or "")
        fields[f"bind{n}_event"] = str(b.get("event_id") or "")
        try:
            fields[f"bind{n}_pri"] = str(int(b.get("priority", 100)))
        except (TypeError, ValueError):
            fields[f"bind{n}_pri"] = "100"


def _interact_enabled_field(inter: dict) -> str:
    from flow import interact_spec_enabled

    return "true" if interact_spec_enabled(inter or {}) else "false"


def _bindings_from_slot_fields(fields: dict) -> list:
    out = []
    for i in range(1, BIND_SLOT_COUNT + 1):
        eid = str(fields.get(f"bind{i}_event") or "").strip()
        if not eid:
            continue
        row = {
            "condition": str(fields.get(f"bind{i}_cond") or "").strip(),
            "event_id": eid,
        }
        pr_s = str(fields.get(f"bind{i}_pri") or "").strip()
        if pr_s:
            try:
                row["priority"] = int(float(pr_s))
            except (TypeError, ValueError):
                row["priority"] = 100
        out.append(row)
    return out


def _interact_offset_to_fields(inter: dict) -> tuple:
    """interact.offset → 에디터 필드 문자열 (0,0 이면 공란)."""
    off = (inter or {}).get("offset")
    if isinstance(off, (list, tuple)) and len(off) >= 2:
        try:
            x, y = float(off[0]), float(off[1])
            if abs(x) < 1e-9 and abs(y) < 1e-9:
                return "", ""
            return str(x), str(y)
        except (TypeError, ValueError):
            pass
    return "", ""


def _interact_offset_into_dict(fields: dict, out: dict) -> None:
    """에디터 offset 필드 → interact.offset (비우면 키 생략)."""
    xs = str(fields.get("interact_offset_x") or "").strip()
    ys = str(fields.get("interact_offset_y") or "").strip()
    if not xs and not ys:
        return
    try:
        x = float(xs) if xs else 0.0
        y = float(ys) if ys else 0.0
    except ValueError:
        return
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return
    out["offset"] = [x, y]


def _interact_range_offset_rows() -> list:
    return [
        ("상호작용 거리", "interact_range", "text"),
        ("중심 X (발 기준 px)", "interact_offset_x", "text"),
        ("중심 Y (발 기준 px)", "interact_offset_y", "text"),
        ("※ 거리·offset 비우면 타입/전역 기본값", "_hint_interact_anchor", "hint"),
    ]


def _interact_dict_from_fields(fields: dict) -> dict:
    out = {
        "enabled": str(fields.get("interact_enabled", "false")).lower() in ("true", "1", "yes"),
        "range": float(fields.get("interact_range") or 48),
    }
    _interact_offset_into_dict(fields, out)
    binds = _bindings_from_slot_fields(fields)
    if binds:
        out["bindings"] = binds
    return out


def char_def_modal_rows() -> list:
    rows = [
        ("표시 이름", "display_name", "text"),
        ("── [A] 연출 이벤트 (bindings → events.json) ──", "_hint_evt", "hint"),
        ("상호작용 활성", "interact_enabled", "dropdown", BOOL_OPTS),
    ]
    rows.extend(_interact_range_offset_rows())
    rows.extend(
        [
        ("조건=progress 식 · List=이벤트 ID · 우선순위↑먼저", "_hint_bind", "hint"),
        ]
    )
    for i in range(1, BIND_SLOT_COUNT + 1):
        rows.append((f"  #{i} 조건", f"bind{i}_cond", "text"))
        rows.append((f"  #{i} 이벤트 ID", f"bind{i}_event", "events"))
        rows.append((f"  #{i} 우선순위", f"bind{i}_pri", "text"))
    rows.extend(
        [
            ("── [B] 일상 대사 (char_defs · SAY만) ──", "_hint_talk", "hint"),
            ("대화 시 바라보기", "face_player", "dropdown", BOOL_OPTS),
            ("when=progress 식(이벤트와 동일) · 위→아래 첫 매칭", "_hint_talk_when", "hint"),
        ]
    )
    for i in range(1, TALK_LINE_COUNT + 1):
        rows.append((f"  대사{i} when", f"line{i}_when", "text"))
        rows.append((f"  대사{i} text", f"line{i}_text", "text"))
        rows.append((f"  대사{i} after", f"line{i}_after", "text"))
    rows.extend(
        [
            ("  기본 대사 (fallback)", "fallback_text", "text"),
            ("after 예: progress_c10_talk:1", "_hint_talk_after", "hint"),
            ("── 이동 AI (behavior) ──", "_hint_beh", "hint"),
            ("behavior mode", "behavior_mode", "dropdown", BEHAVIOR_OPTS),
            ("jump_max_gap", "jump_max_gap", "text"),
            ("mask_nav", "mask_nav", "dropdown", BOOL_OPTS),
        ]
    )
    return rows


def char_inst_modal_rows() -> list:
    rows = [
        ("Instance ID", "instance_id", "text"),
        ("── 맵만: 이벤트 bindings 덮어쓰기 ──", "_hint_inst_evt", "hint"),
        ("상호작용 활성", "interact_enabled", "dropdown", BOOL_OPTS),
    ]
    rows.extend(_interact_range_offset_rows())
    rows.extend(
        [
        ("※ bindings 는 타입 설정을 맵에서 덮어씀", "_hint_inst_talk", "hint"),
        ]
    )
    for i in range(1, BIND_SLOT_COUNT + 1):
        rows.append((f"  #{i} 조건", f"bind{i}_cond", "text"))
        rows.append((f"  #{i} 이벤트 ID", f"bind{i}_event", "events"))
        rows.append((f"  #{i} 우선순위", f"bind{i}_pri", "text"))
    rows.extend(
        [
            ("── behavior (맵) ──", "_hint_inst_beh", "hint"),
            ("Behavior mode", "behavior_mode", "dropdown", BEHAVIOR_OPTS),
            ("Waypoints (x,y;…)", "waypoints", "text"),
            ("Patrol wait ms", "wait_ms", "text"),
            ("Wander radius", "wander_radius", "text"),
            ("Wander interval ms", "wander_interval_ms", "text"),
            ("Follow trigger px", "follow_trigger", "text"),
            ("Follow stop px", "follow_stop", "text"),
            ("Flee trigger px", "flee_trigger", "text"),
            ("Flee safe px", "flee_safe", "text"),
        ]
    )
    return rows


def char_def_to_fields(cdef: dict, char_name: str) -> dict:
    inter = cdef.get("interact") or {}
    beh = cdef.get("behavior") or {}
    talk = cdef.get("talk") or {}
    lines = list(talk.get("lines") or [])
    fb = talk.get("fallback") or {}
    fb_say = fb.get("say") if isinstance(fb, dict) else {}
    iox, ioy = _interact_offset_to_fields(inter)
    fields = {
        "display_name": str(cdef.get("display_name") or ""),
        "interact_range": str(inter.get("range", 48)),
        "interact_offset_x": iox,
        "interact_offset_y": ioy,
        "interact_enabled": _interact_enabled_field(inter),
        "face_player": "true" if inter.get("face_player_on_talk", True) else "false",
        "behavior_mode": str(beh.get("mode") or "idle"),
        "jump_max_gap": str(cdef.get("jump_max_gap", 30)),
        "mask_nav": "true" if cdef.get("mask_nav") else "false",
        "fallback_text": str((fb_say or {}).get("text") or ""),
    }
    _bindings_to_slot_fields(inter.get("bindings"), fields)
    for i in range(1, TALK_LINE_COUNT + 1):
        if i - 1 < len(lines):
            ln = lines[i - 1]
            say = ln.get("say") or {}
            fields[f"line{i}_when"] = _format_talk_when(ln.get("when"))
            fields[f"line{i}_text"] = str(say.get("text") or "")
            fields[f"line{i}_after"] = _format_talk_after(ln.get("after"))
        else:
            fields[f"line{i}_when"] = ""
            fields[f"line{i}_text"] = ""
            fields[f"line{i}_after"] = ""
    if not fields["display_name"]:
        fields["display_name"] = char_name
    return fields


def fields_to_char_def(fields: dict, char_name: str) -> dict:
    from char_behavior import get_char_type_def

    base = dict(get_char_type_def(char_name))
    out: dict = {
        "jump_max_gap": int(float(fields.get("jump_max_gap") or base.get("jump_max_gap", 30))),
    }
    if str(fields.get("mask_nav", "false")).lower() in ("true", "1", "yes"):
        out["mask_nav"] = True
    dn = str(fields.get("display_name") or "").strip()
    if dn:
        out["display_name"] = dn
    out["interact"] = _interact_dict_from_fields(fields)
    out["interact"]["face_player_on_talk"] = str(fields.get("face_player", "true")).lower() in (
        "true",
        "1",
        "yes",
    )
    mode = str(fields.get("behavior_mode") or "idle").strip() or "idle"
    out["behavior"] = {"mode": mode}
    lines = []
    for i in range(1, TALK_LINE_COUNT + 1):
        txt = str(fields.get(f"line{i}_text") or "").strip()
        if not txt:
            continue
        wh = _parse_talk_when(fields.get(f"line{i}_when"))
        af = _parse_talk_after(fields.get(f"line{i}_after"))
        say = {"who": char_name, "text": txt, "show_name": True}
        entry = {"id": f"line{i}", "say": say}
        if wh is not None:
            entry["when"] = wh
        if af:
            entry["after"] = af
        lines.append(entry)
    talk: dict = {}
    if lines:
        talk["lines"] = lines
    fb_txt = str(fields.get("fallback_text") or "").strip()
    if fb_txt:
        talk["fallback"] = {"say": {"text": fb_txt, "show_name": False}}
    if talk:
        out["talk"] = talk
    return out


def save_char_def_to_json(char_name: str, fields: dict) -> None:
    from entity_defs import load_char_defs, reload_entity_defs, save_char_defs

    all_defs = load_char_defs()
    all_defs[char_name] = fields_to_char_def(fields, char_name)
    save_char_defs(all_defs)
    reload_entity_defs()


def parse_waypoints(s: str) -> list:
    out = []
    for part in re.split(r"[;\n]+", str(s or "")):
        part = part.strip()
        if not part:
            continue
        xy = re.split(r"[, \t]+", part)
        if len(xy) >= 2:
            try:
                out.append([int(float(xy[0])), int(float(xy[1]))])
            except ValueError:
                pass
    return out


def format_waypoints(wps: list) -> str:
    return "; ".join(f"{int(p[0])},{int(p[1])}" for p in (wps or []) if len(p) >= 2)


def char_inst_fields_from_npc(npc) -> dict:
    spec = getattr(npc, "behavior_spec", None) or {}
    raw = getattr(npc, "interact_instance", None) or {}
    inter = raw if isinstance(raw, dict) else {}
    iox, ioy = _interact_offset_to_fields(inter)
    fields = {
        "instance_id": str(getattr(npc, "instance_id", "") or ""),
        "interact_enabled": (
            _interact_enabled_field(inter) if "enabled" in inter else ""
        ),
        "interact_range": str(inter.get("range", "")),
        "interact_offset_x": iox,
        "interact_offset_y": ioy,
        "behavior_mode": str(spec.get("mode") or "idle"),
        "waypoints": format_waypoints(spec.get("waypoints") or []),
        "wait_ms": str(spec.get("wait_ms", 800)),
        "wander_radius": str(spec.get("radius", 64)),
        "wander_interval_ms": str(spec.get("interval_ms", 3000)),
        "follow_trigger": str(spec.get("trigger_range", 120)),
        "follow_stop": str(spec.get("stop_dist", 36)),
        "flee_trigger": str(spec.get("trigger_range", 80)),
        "flee_safe": str(spec.get("safe_range", 140)),
    }
    _bindings_to_slot_fields(inter.get("bindings"), fields)
    return fields


def apply_char_inst_fields(npc, fields: dict) -> None:
    from char_behavior import attach_npc_from_entry, npc_entry_from_instance

    inst_inter: dict = {}
    if str(fields.get("interact_enabled", "")).strip():
        inst_inter["enabled"] = str(fields.get("interact_enabled", "false")).lower() in (
            "true",
            "1",
            "yes",
        )
    rng_s = str(fields.get("interact_range") or "").strip()
    if rng_s:
        try:
            inst_inter["range"] = float(rng_s)
        except ValueError:
            pass
    _interact_offset_into_dict(fields, inst_inter)
    binds = _bindings_from_slot_fields(fields)
    if binds:
        inst_inter["bindings"] = binds
    npc.interact_instance = inst_inter

    spec: dict = {"mode": str(fields.get("behavior_mode") or "idle").strip() or "idle"}
    wps = parse_waypoints(fields.get("waypoints"))
    if wps:
        spec["waypoints"] = wps
    try:
        spec["wait_ms"] = int(float(fields.get("wait_ms") or 800))
    except ValueError:
        pass
    try:
        spec["radius"] = float(fields.get("wander_radius") or 64)
    except ValueError:
        pass
    try:
        spec["interval_ms"] = int(float(fields.get("wander_interval_ms") or 3000))
    except ValueError:
        pass
    try:
        spec["trigger_range"] = float(fields.get("follow_trigger") or fields.get("flee_trigger") or 100)
    except ValueError:
        pass
    if spec["mode"] == "follow":
        try:
            spec["stop_dist"] = float(fields.get("follow_stop") or 36)
            spec["trigger_range"] = float(fields.get("follow_trigger") or 120)
        except ValueError:
            pass
    if spec["mode"] == "flee":
        try:
            spec["safe_range"] = float(fields.get("flee_safe") or 140)
            spec["trigger_range"] = float(fields.get("flee_trigger") or 80)
        except ValueError:
            pass

    npc.instance_id = str(fields.get("instance_id") or getattr(npc, "instance_id", ""))
    entry = npc_entry_from_instance(npc)
    entry["instance_id"] = npc.instance_id
    entry["behavior"] = spec
    if inst_inter:
        entry["interact"] = inst_inter
    attach_npc_from_entry(npc, entry)


class _ConfigModal:
    """zone 모달과 동일 패턴의 단순 설정창."""

    tag: str = "cfg"
    title: str = "CONFIG"

    def get_rows(self) -> list:
        return []

    def __init__(self):
        self.show = False
        self.fields: Dict[str, str] = {}
        self.scroll = 0
        self.active_field: Optional[str] = None
        self.dd_open = False
        self.dd_key: Optional[str] = None
        self.dd_scroll = 0
        self.dd_rect = None
        self.dd_options: list = []
        self.dd_ui = None
        self._body_drag = False
        self._dd_drag = False

    def close(self):
        self.show = False
        self.dd_open = False
        self.active_field = None

    def _row_opts(self, row) -> list:
        if len(row) >= 4 and row[2] == "dropdown":
            return [o[1] if isinstance(o, (list, tuple)) else o for o in row[3]]
        return []

    def _event_id_options(self, ctx) -> list:
        return list(ctx.get("event_ids") or [])

    def handle_event(self, event, ctx) -> bool:
        if not self.show:
            return False
        from editor import (
            EDITOR_MODAL_ROW_H,
            _editor_modal_body_scroll_layout,
            _editor_std_modal_rect,
            _step_overlay_scrollbar_layout,
        )

        rows = self.get_rows()
        sw, sh = ctx["screen_w"], ctx["screen_h"]
        mx, my = ctx["mouse"]
        panel_rect, content_h, _ = _editor_std_modal_rect(sw, sh, len(rows))
        body_rect, sb_rect, max_scroll, _ = _editor_modal_body_scroll_layout(
            panel_rect, self.scroll, content_h
        )
        save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
        canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)
        field_x = body_rect.x + 148
        field_w, list_w = 220, 52
        dd_item_h = 22
        modal_body_drag = ctx.get("modal_body_drag")
        modal_dd_drag = ctx.get("modal_dropdown_drag")

        if event.type == pygame.MOUSEWHEEL:
            wxw, wyw = getattr(event, "pos", (mx, my))
            dy = getattr(event, "precise_y", None)
            if dy is not None:
                delta = int(round(-dy * 40))
            else:
                delta = -int(event.y) * 24
            if delta == 0 and event.y:
                delta = -int(event.y) * 24
            if self.dd_open and self.dd_rect:
                total_h = len(self.dd_options) * dd_item_h
                vis = max(1, self.dd_rect.height)
                max_dd = max(0, total_h - vis)
                if max_dd > 0 and (
                    self.dd_rect.collidepoint(wxw, wyw) or panel_rect.collidepoint(wxw, wyw)
                ):
                    self.dd_scroll = max(0, min(max_dd, self.dd_scroll + delta))
            elif panel_rect.collidepoint(wxw, wyw):
                self.scroll = max(0, min(max_scroll, self.scroll + delta))
            return True

        if event.type == pygame.MOUSEMOTION and modal_body_drag == self.tag:
            ui_sb = _step_overlay_scrollbar_layout(
                sb_rect, body_rect.height, content_h, self.scroll
            )
            tr, th = ui_sb.get("track"), int(ui_sb.get("thumb_h") or 18)
            max_sc = int(ui_sb.get("max_scroll") or 0)
            if tr is not None and max_sc > 0:
                y = event.pos[1] - (th // 2)
                y = max(tr.y, min(tr.bottom - th, y))
                span = max(0, tr.height - th)
                p = 0.0 if span <= 0 else (y - tr.y) / span
                self.scroll = int(p * max_sc)
            return True

        if event.type == pygame.MOUSEMOTION and modal_dd_drag == f"{self.tag}_dd":
            if self.dd_ui and self.dd_ui.get("track"):
                tr = self.dd_ui["track"]
                th = int(self.dd_ui.get("thumb_h") or 18)
                max_sc = int(self.dd_ui.get("max_scroll") or 0)
                if max_sc > 0:
                    y = event.pos[1] - (th // 2)
                    y = max(tr.y, min(tr.bottom - th, y))
                    span = max(0, tr.height - th)
                    p = 0.0 if span <= 0 else (y - tr.y) / span
                    self.dd_scroll = int(p * max_sc)
            return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if modal_body_drag == self.tag:
                ctx["modal_body_drag"] = None
            if modal_dd_drag == f"{self.tag}_dd":
                ctx["modal_dropdown_drag"] = None
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.dd_open and self.dd_rect:
                dr = self.dd_rect
                ui_prev = self.dd_ui
                if dr.collidepoint(event.pos):
                    if ui_prev and ui_prev.get("thumb") and ui_prev["thumb"].collidepoint(event.pos):
                        ctx["modal_dropdown_drag"] = f"{self.tag}_dd"
                        return True
                    sb_ex = 11 if int((ui_prev or {}).get("max_scroll") or 0) > 0 else 0
                    pick_w = max(1, dr.width - sb_ex)
                    if event.pos[0] < dr.x + pick_w:
                        rel_y = event.pos[1] - dr.y + self.dd_scroll
                        ix = rel_y // dd_item_h
                        if 0 <= ix < len(self.dd_options):
                            if self.dd_key:
                                self.fields[self.dd_key] = str(self.dd_options[ix])
                            self.dd_open = False
                        return True
                self.dd_open = False

            if save_btn.collidepoint(event.pos):
                self.on_save(ctx)
                self.close()
                return True
            if canc_btn.collidepoint(event.pos):
                self.close()
                return True

            ui_sb = _step_overlay_scrollbar_layout(
                sb_rect, body_rect.height, content_h, self.scroll
            )
            if ui_sb.get("thumb") and ui_sb["thumb"].collidepoint(event.pos):
                ctx["modal_body_drag"] = self.tag
                return True

            self.active_field = None
            for i, row in enumerate(rows):
                rk = row[1]
                kind = row[2]
                ry = body_rect.y + i * EDITOR_MODAL_ROW_H - self.scroll
                if ry + EDITOR_MODAL_ROW_H < body_rect.top or ry > body_rect.bottom:
                    continue
                if kind == "hint":
                    continue
                if kind == "text":
                    val_rect = pygame.Rect(
                        field_x, ry + 3, body_rect.right - field_x - 8, EDITOR_MODAL_ROW_H - 6
                    )
                    if val_rect.collidepoint(event.pos):
                        self.active_field = rk
                        return True
                elif kind == "events":
                    lb = pygame.Rect(field_x + field_w + 4, ry + 3, list_w, EDITOR_MODAL_ROW_H - 6)
                    val_rect = pygame.Rect(field_x, ry + 3, field_w, EDITOR_MODAL_ROW_H - 6)
                    if lb.collidepoint(event.pos):
                        self.dd_key = rk
                        self.dd_options = self._event_id_options(ctx)
                        self.dd_scroll = 0
                        self.dd_open = True
                        n_opt = max(1, len(self.dd_options))
                        self.dd_rect = pygame.Rect(
                            field_x,
                            ry + EDITOR_MODAL_ROW_H + 2,
                            field_w + list_w + 4,
                            min(220, n_opt * dd_item_h + 4),
                        )
                        return True
                    if val_rect.collidepoint(event.pos):
                        self.active_field = rk
                        return True
                elif kind == "dropdown":
                    lb = pygame.Rect(field_x + field_w + 4, ry + 3, list_w, EDITOR_MODAL_ROW_H - 6)
                    val_rect = pygame.Rect(field_x, ry + 3, field_w, EDITOR_MODAL_ROW_H - 6)
                    if lb.collidepoint(event.pos):
                        self.dd_key = rk
                        self.dd_options = self._row_opts(row)
                        self.dd_scroll = 0
                        self.dd_open = True
                        n_opt = max(1, len(self.dd_options))
                        self.dd_rect = pygame.Rect(
                            field_x,
                            ry + EDITOR_MODAL_ROW_H + 2,
                            field_w + list_w + 4,
                            min(220, n_opt * dd_item_h + 4),
                        )
                        return True
                    if val_rect.collidepoint(event.pos):
                        self.active_field = rk
                        return True
            return True

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self.dd_open:
                    self.dd_open = False
                else:
                    self.close()
                return True
            if self.active_field:
                if event.key == pygame.K_BACKSPACE:
                    self.fields[self.active_field] = self.fields.get(self.active_field, "")[:-1]
                elif event.key == pygame.K_RETURN:
                    self.active_field = None
                return True
        if event.type == pygame.TEXTINPUT and self.active_field:
            self.fields[self.active_field] = self.fields.get(self.active_field, "") + event.text
            return True
        return True

    def on_save(self, ctx):
        pass

    def draw(self, screen, title_font, font, ctx):
        if not self.show:
            return
        from editor import (
            _draw_dropdown_with_scrollbar,
            _editor_paint_modal_overlay,
            _editor_std_modal_rect,
        )

        overlay = pygame.Surface((ctx["screen_w"], ctx["screen_h"]), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))
        rows = self.get_rows()
        panel_rect, content_h, _ = _editor_std_modal_rect(ctx["screen_w"], ctx["screen_h"], len(rows))
        _editor_paint_modal_overlay(
            screen,
            title_font,
            font,
            self.title,
            panel_rect,
            rows,
            self.scroll,
            self.fields,
            self.active_field,
        )
        save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
        canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)
        pygame.draw.rect(screen, (0, 100, 0), save_btn)
        pygame.draw.rect(screen, (100, 0, 0), canc_btn)
        screen.blit(font.render("SAVE", True, (255, 255, 255)), (save_btn.x + 25, save_btn.y + 7))
        screen.blit(font.render("CANCEL", True, (255, 255, 255)), (canc_btn.x + 15, canc_btn.y + 7))
        self.dd_ui = None
        if self.dd_open and self.dd_rect and self.dd_options:
            cv = str(self.fields.get(self.dd_key or "", "") or "")
            try:
                ci = self.dd_options.index(cv)
            except ValueError:
                ci = -1
            self.dd_ui = _draw_dropdown_with_scrollbar(
                screen,
                font,
                self.dd_rect,
                self.dd_options,
                ci,
                self.dd_scroll,
                22,
                colors={},
            )


class CharDefModal(_ConfigModal):
    tag = "char_def"
    title = "NPC 타입 — [A]연출 / [B]대사 (char_defs)"

    def get_rows(self):
        return char_def_modal_rows()

    def __init__(self):
        super().__init__()
        self.target_name: str = ""

    def open(self, char_name: str):
        from char_behavior import get_char_type_def

        self.target_name = char_name
        self.fields = char_def_to_fields(get_char_type_def(char_name), char_name)
        self.show = True
        self.scroll = 0
        self.active_field = None
        self.dd_open = False

    def on_save(self, ctx):
        save_char_def_to_json(self.target_name, self.fields)
        ctx.get("on_char_def_saved", lambda _n: None)(self.target_name)


class CharInstModal(_ConfigModal):
    tag = "char_inst"
    title = "NPC 맵 인스턴스 — 이벤트 bindings만"

    def get_rows(self):
        return char_inst_modal_rows()

    def __init__(self):
        super().__init__()
        self.target_npc = None

    def open(self, npc):
        self.target_npc = npc
        self.fields = char_inst_fields_from_npc(npc)
        self.show = True
        self.scroll = 0
        self.active_field = None
        self.dd_open = False

    def on_save(self, ctx):
        if self.target_npc:
            apply_char_inst_fields(self.target_npc, self.fields)
        cb = ctx.get("on_inst_saved")
        if callable(cb):
            cb()


def obj_interact_modal_rows() -> list:
    rows = [
        ("── 오브젝트 상호작용 (progress → events) ──", "_hint_obj_evt", "hint"),
        ("상호작용 활성", "interact_enabled", "dropdown", BOOL_OPTS),
    ]
    rows.extend(_interact_range_offset_rows())
    rows.append(("조건=progress · List=이벤트 ID", "_hint_obj_bind", "hint"))
    for i in range(1, BIND_SLOT_COUNT + 1):
        rows.append((f"  #{i} 조건", f"bind{i}_cond", "text"))
        rows.append((f"  #{i} 이벤트 ID", f"bind{i}_event", "events"))
        rows.append((f"  #{i} 우선순위", f"bind{i}_pri", "text"))
    return rows


def _fields_from_interact_dict(inter: dict) -> dict:
    inter = inter or {}
    iox, ioy = _interact_offset_to_fields(inter)
    fields = {
        "interact_enabled": _interact_enabled_field(inter),
        "interact_range": str(inter.get("range", CONFIG.get("OBJECT_INTERACT_RANGE", 16))),
        "interact_offset_x": iox,
        "interact_offset_y": ioy,
    }
    _bindings_to_slot_fields(inter.get("bindings"), fields)
    return fields


class ObjDefModal(_ConfigModal):
    """object_defs.json 타입별 interact (progress→events.json)."""

    tag = "obj_def"
    title = "오브젝트 타입 — 이벤트 bindings (object_defs)"

    def get_rows(self):
        return obj_interact_modal_rows()

    def __init__(self):
        super().__init__()
        self.target_name = ""

    def open(self, obj_name: str):
        from data import OBJ_ASSETS

        self.target_name = str(obj_name or "")
        info = OBJ_ASSETS.get(self.target_name, {})
        self.fields = _fields_from_interact_dict(info.get("interact"))
        self.show = True
        self.scroll = 0
        self.active_field = None
        self.dd_open = False

    def on_save(self, ctx):
        from entity_defs import load_object_defs, reload_entity_defs, save_object_defs

        all_defs = load_object_defs()
        row = dict(all_defs.get(self.target_name, {}) or {})
        row["interact"] = _interact_dict_from_fields(self.fields)
        all_defs[self.target_name] = row
        save_object_defs(all_defs)
        reload_entity_defs()
        cb = ctx.get("on_obj_def_saved")
        if callable(cb):
            cb(self.target_name)


class ObjInstModal(_ConfigModal):
    """맵에 배치된 FieldItem 인스턴스 interact (world_data.objects[].interact)."""

    tag = "obj_inst"
    title = "오브젝트 맵 — 이벤트 bindings 덮어쓰기"

    def get_rows(self):
        return obj_interact_modal_rows()

    def __init__(self):
        super().__init__()
        self.target_item = None

    def open(self, item):
        from data import OBJ_ASSETS
        from flow import merge_interact_spec

        self.target_item = item
        spec = getattr(item, "interact_spec", None)
        if not isinstance(spec, dict):
            inst = getattr(item, "interact_instance", None) or {}
            spec = merge_interact_spec(
                OBJ_ASSETS.get(item.name, {}),
                {"interact": inst} if isinstance(inst, dict) else {},
            )
        self.fields = _fields_from_interact_dict(spec)
        self.show = True
        self.scroll = 0
        self.active_field = None
        self.dd_open = False

    def on_save(self, ctx):
        if not self.target_item:
            return
        from data import OBJ_ASSETS
        from flow import merge_interact_spec

        inst = _interact_dict_from_fields(self.fields)
        self.target_item.interact_instance = inst
        self.target_item.interact_spec = merge_interact_spec(
            OBJ_ASSETS.get(self.target_item.name, {}),
            {"interact": inst},
        )
        cb = ctx.get("on_inst_saved")
        if callable(cb):
            cb()


char_def_modal = CharDefModal()
char_inst_modal = CharInstModal()
obj_def_modal = ObjDefModal()
obj_inst_modal = ObjInstModal()


def any_char_modal_open() -> bool:
    return (
        char_def_modal.show
        or char_inst_modal.show
        or obj_def_modal.show
        or obj_inst_modal.show
    )


def close_all_char_modals():
    char_def_modal.close()
    char_inst_modal.close()
    obj_def_modal.close()
    obj_inst_modal.close()

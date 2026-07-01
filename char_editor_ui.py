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
DEFAULT_BIND_SLOTS = 3
DEFAULT_TALK_LINES = 4
DEFAULT_PROGRESS_RULES = 4
MAX_EXPAND_SLOTS = 32
# 하위 호환 별칭
BIND_SLOT_COUNT = DEFAULT_BIND_SLOTS
TALK_LINE_COUNT = DEFAULT_TALK_LINES
PROGRESS_RULE_COUNT = DEFAULT_PROGRESS_RULES
VISIBLE_OPTS = [("—", ""), ("Yes", "true"), ("No", "false")]
ANIM_MODE_OPTS = [("—", ""), ("hold", "hold"), ("once", "once")]
DIR_OPTS = [("—", ""), ("left", "left"), ("right", "right")]
YSORT_OPTS = [("—", ""), ("ground", "ground"), ("visual", "visual")]
SHEAR_ON_OPTS = [("—", ""), ("On", "true"), ("Off", "false")]
DEFAULT_PRESENCE_TARGETS = 3


def _tune_value_modal_rows(prefix: str) -> list:
    """TUNE 스텝과 동일 필드 — prefix 예: player_, tgt1_."""
    p = str(prefix or "")
    return [
        (f"sprite_tilt (0~1, 비우면 유지)", f"{p}sprite_tilt", "text"),
        (f"height (px, 비우면 유지)", f"{p}height", "text"),
        (f"ysort (비우면 유지)", f"{p}ysort", "dropdown", YSORT_OPTS),
        (f"layer (비우면 유지)", f"{p}layer", "text"),
        (f"visible (비우면 유지)", f"{p}visible", "dropdown", VISIBLE_OPTS),
        (f"alpha (0~255, 비우면 유지)", f"{p}alpha", "text"),
        (f"anim (비우면 유지)", f"{p}anim", "text"),
        (f"dir (비우면 유지)", f"{p}dir", "dropdown", DIR_OPTS),
    ]


def _tune_fields_from_patch(patch: dict, fields: dict, prefix: str) -> None:
    p = dict(patch or {})
    fields[f"{prefix}sprite_tilt"] = "" if p.get("sprite_tilt") is None else str(p.get("sprite_tilt"))
    fields[f"{prefix}height"] = "" if p.get("height") is None else str(p.get("height"))
    fields[f"{prefix}ysort"] = str(p.get("ysort") or "")
    fields[f"{prefix}layer"] = "" if p.get("layer") is None else str(p.get("layer"))
    fields[f"{prefix}visible"] = _opt_bool_field(p.get("visible"), "")
    fields[f"{prefix}alpha"] = "" if p.get("alpha") is None else str(p.get("alpha"))
    fields[f"{prefix}anim"] = str(p.get("anim") or p.get("state") or "")
    d = str(p.get("dir") or p.get("face") or "").strip().lower()
    fields[f"{prefix}dir"] = d if d in ("left", "right") else ""


def _tune_patch_from_fields(fields: dict, prefix: str) -> dict:
    from flow import build_tune_patch_from_dict

    raw = {
        "sprite_tilt": fields.get(f"{prefix}sprite_tilt"),
        "height": fields.get(f"{prefix}height"),
        "ysort": fields.get(f"{prefix}ysort"),
        "layer": fields.get(f"{prefix}layer"),
        "visible": fields.get(f"{prefix}visible"),
        "alpha": fields.get(f"{prefix}alpha"),
        "anim": fields.get(f"{prefix}anim"),
        "dir": fields.get(f"{prefix}dir"),
    }
    return build_tune_patch_from_dict(raw)


def _field_screen_from_patch(patch: dict, fields: dict) -> None:
    p = dict(patch or {})
    fields["field_tilt_target"] = "" if p.get("tilt_target") is None else str(p.get("tilt_target"))
    fields["field_shear_on"] = _opt_bool_field(p.get("shear_on"), "")
    fields["field_shear_strength"] = "" if p.get("shear_strength") is None else str(p.get("shear_strength"))
    fields["field_shear_max_px"] = "" if p.get("shear_max_px") is None else str(p.get("shear_max_px"))


def _field_screen_to_patch(fields: dict) -> dict:
    from flow import build_field_patch_from_dict

    return build_field_patch_from_dict(
        {
            "tilt_target": fields.get("field_tilt_target"),
            "shear_on": fields.get("field_shear_on"),
            "shear_strength": fields.get("field_shear_strength"),
            "shear_max_px": fields.get("field_shear_max_px"),
        }
    )


def presence_zone_to_fields(zone: dict, *, target_count: int = DEFAULT_PRESENCE_TARGETS) -> dict:
    z = dict(zone or {})
    fields = {
        "name": str(z.get("name") or ""),
        "cond_mainprogress": str((z.get("conditions") or {}).get("mainprogress") or ""),
        "cond_min_laugh_point": str((z.get("conditions") or {}).get("min_laugh_point") or ""),
    }
    _field_screen_from_patch(z.get("field") or {}, fields)
    _tune_fields_from_patch(z.get("player") or {}, fields, "player_")
    targets = z.get("targets") or []
    if not isinstance(targets, list):
        targets = []
    n = max(target_count, len(targets), DEFAULT_PRESENCE_TARGETS)
    for i in range(1, n + 1):
        row = targets[i - 1] if i - 1 < len(targets) else {}
        fields[f"tgt{i}_name"] = str((row or {}).get("name") or "")
        _tune_fields_from_patch(row or {}, fields, f"tgt{i}_")
    return fields, n


def presence_zone_from_fields(fields: dict, rect, *, target_count: int) -> dict:
    z = {
        "name": str(fields.get("name") or "").strip() or "presence_zone",
        "rect": [int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])],
        "conditions": {},
    }
    mp = str(fields.get("cond_mainprogress") or "").strip()
    if mp:
        z["conditions"]["mainprogress"] = mp
    mlp = str(fields.get("cond_min_laugh_point") or "").strip()
    if mlp:
        try:
            z["conditions"]["min_laugh_point"] = int(float(mlp))
        except (TypeError, ValueError):
            pass
    fp = _field_screen_to_patch(fields)
    if fp:
        z["field"] = fp
    pp = _tune_patch_from_fields(fields, "player_")
    if pp:
        z["player"] = pp
    targets = []
    for i in range(1, int(target_count) + 1):
        name = str(fields.get(f"tgt{i}_name") or "").strip()
        tp = _tune_patch_from_fields(fields, f"tgt{i}_")
        if not name and not tp:
            continue
        row = dict(tp)
        if name:
            row["name"] = name
        targets.append(row)
    if targets:
        z["targets"] = targets
    return z


def presence_zone_modal_section_rows(*, target_count: int = DEFAULT_PRESENCE_TARGETS) -> dict:
    basic = [
        (
            "※ 체류 존 — 플레이어가 영역 안에 있을 때만 상태 적용, 나가면 복구",
            "_hint_presence_intro",
            "hint",
        ),
        ("Box Name", "name", "text"),
        ("Cond mainprogress", "cond_mainprogress", "text"),
        ("Cond min_laugh_point", "cond_min_laugh_point", "text"),
        ("Area — Set Area 버튼으로 맵에 사각형 지정", "_hint_presence_area", "hint"),
        ("맵에서 영역 지정", "_area:pick", "add_btn"),
    ]
    field_rows = [
        ("── 화면(틸트/쉬어) — 비운 칸은 변경 없음 ──", "_hint_field", "hint"),
        ("tilt_target (0~1, 비우면 유지)", "field_tilt_target", "text"),
        ("shear on (비우면 유지)", "field_shear_on", "dropdown", SHEAR_ON_OPTS),
        ("shear strength (0~1)", "field_shear_strength", "text"),
        ("shear max_px", "field_shear_max_px", "text"),
    ]
    player_rows = [
        ("── 플레이어 — TUNE 과 동일 필드 ──", "_hint_player", "hint"),
    ]
    player_rows.extend(_tune_value_modal_rows("player_"))
    target_rows = [
        (
            "── 지정 오브젝트/NPC — 이름 + TUNE 필드 (플레이어 제외) ──",
            "_hint_targets",
            "hint",
        ),
    ]
    for i in range(1, target_count + 1):
        target_rows.append((f"#{i} 이름 (입력 또는 List)", f"tgt{i}_name", "events"))
        target_rows.extend(_tune_value_modal_rows(f"tgt{i}_"))
    target_rows.append(("+ 대상 추가", "_add:tgt", "add_btn"))
    return {
        "basic": basic,
        "field": field_rows,
        "player": player_rows,
        "targets": target_rows,
    }


def _max_numbered_slot(fields: dict, prefix: str) -> int:
    """fields 키에서 prefix{N}_ 패턴의 최대 N."""
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)_")
    max_n = 0
    for k in fields:
        m = pat.match(k)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n


def _add_btn_row(label: str, add_id: str) -> tuple:
    return (label, add_id, "add_btn")


def _init_bind_slot_fields(fields: dict, n: int) -> None:
    fields[f"bind{n}_cond"] = ""
    fields[f"bind{n}_event"] = ""
    fields[f"bind{n}_pri"] = "100"
    fields[f"bind{n}_after"] = ""
    fields[f"bind{n}_st_visible"] = ""
    fields[f"bind{n}_st_anim"] = ""
    fields[f"bind{n}_st_anim_mode"] = ""


def _init_talk_line_fields(fields: dict, n: int) -> None:
    fields[f"line{n}_when"] = ""
    fields[f"line{n}_text"] = ""
    fields[f"line{n}_after"] = ""


def _init_prog_rule_fields(fields: dict, slot_prefix: str, n: int) -> None:
    p = f"{slot_prefix}{n}_"
    fields[f"{p}when"] = ""
    _state_patch_to_fields({}, fields, p)


def _default_slot_counts() -> Dict[str, int]:
    return {
        "bind": DEFAULT_BIND_SLOTS,
        "talk": DEFAULT_TALK_LINES,
        "prog": DEFAULT_PROGRESS_RULES,
        "inst_prog": DEFAULT_PROGRESS_RULES,
    }


def _opt_bool_field(val, default_empty="") -> str:
    if val is None:
        return default_empty
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val).strip().lower() if str(val).strip() else default_empty


def _parse_opt_bool(s) -> Optional[bool]:
    t = str(s or "").strip().lower()
    if not t or t == "—":
        return None
    return t in ("true", "1", "yes")


def _state_patch_to_fields(patch: dict, fields: dict, prefix: str) -> None:
    """spawn_state / binding.state / progress 규칙 → 에디터 필드."""
    p = patch or {}
    fields[f"{prefix}visible"] = _opt_bool_field(p.get("visible"), "")
    fields[f"{prefix}spawn"] = _opt_bool_field(p.get("spawn"), "")
    fields[f"{prefix}anim"] = str(p.get("anim") or p.get("state") or "")
    fields[f"{prefix}anim_mode"] = str(p.get("anim_mode") or p.get("mode") or "")
    fields[f"{prefix}change_to"] = str(p.get("change_to") or p.get("to") or "")
    fields[f"{prefix}dir"] = str(p.get("dir") or p.get("face") or "")


def _state_patch_from_fields(fields: dict, prefix: str) -> Optional[dict]:
    """에디터 필드 → 상태 패치 dict (비어 있으면 None)."""
    out: dict = {}
    vis = _parse_opt_bool(fields.get(f"{prefix}visible"))
    if vis is not None:
        out["visible"] = vis
    sp = _parse_opt_bool(fields.get(f"{prefix}spawn"))
    if sp is not None:
        out["spawn"] = sp
    anim = str(fields.get(f"{prefix}anim") or "").strip()
    if anim:
        out["anim"] = anim
    mode = str(fields.get(f"{prefix}anim_mode") or "").strip()
    if mode:
        out["anim_mode"] = mode
    ct = str(fields.get(f"{prefix}change_to") or "").strip()
    if ct:
        out["change_to"] = ct
    d = str(fields.get(f"{prefix}dir") or "").strip().lower()
    if d in ("left", "right"):
        out["dir"] = d
    return out if out else None


def _progress_apply_to_fields(rules: list, fields: dict, *, slot_prefix: str = "prog") -> None:
    rule_count = max(
        DEFAULT_PROGRESS_RULES,
        len(rules or []),
        _max_numbered_slot(fields, slot_prefix),
    )
    for i in range(1, rule_count + 1):
        fields[f"{slot_prefix}{i}_when"] = ""
        _state_patch_to_fields({}, fields, f"{slot_prefix}{i}_")
    for i, row in enumerate(rules or []):
        if not isinstance(row, dict):
            continue
        n = i + 1
        p = f"{slot_prefix}{n}_"
        cond = row.get("when")
        if cond is None:
            cond = row.get("condition")
        fields[f"{p}when"] = str(cond or "").strip()
        st = row.get("state") if isinstance(row.get("state"), dict) else row
        if isinstance(st, dict):
            _state_patch_to_fields(st, fields, p)
        else:
            _state_patch_to_fields({}, fields, p)


def _progress_apply_from_fields(fields: dict, *, slot_prefix: str = "prog") -> Optional[list]:
    rules = []
    rule_count = max(DEFAULT_PROGRESS_RULES, _max_numbered_slot(fields, slot_prefix))
    for i in range(1, rule_count + 1):
        p = f"{slot_prefix}{i}_"
        when = str(fields.get(f"{p}when") or "").strip()
        if not when:
            continue
        row: dict = {"when": when}
        patch = _state_patch_from_fields(fields, p)
        if patch:
            row.update(patch)
        rules.append(row)
    return rules if rules else None


def _spawn_editor_rows(*, spawn_prefix: str = "spawn_") -> list:
    return [
        (
            "── [C] spawn_state — 맵에 처음 나타날 때의 모습 (저장 후 맵 다시 열면 적용) ──",
            "_hint_spawn",
            "hint",
        ),
        ("  visible — false면 플레이 중 안 보임 (에디터는 윤곽으로 표시)", f"{spawn_prefix}visible", "dropdown", VISIBLE_OPTS),
        ("  dir — 바라보는 방향 left / right", f"{spawn_prefix}dir", "dropdown", DIR_OPTS),
        ("  anim — idle, walk 등 애니 이름", f"{spawn_prefix}anim", "text"),
        ("  anim_mode — hold=계속, once=한 번 재생", f"{spawn_prefix}anim_mode", "dropdown", ANIM_MODE_OPTS),
    ]


def _progress_editor_rows(
    *,
    prog_prefix: str = "prog",
    rule_count: int = DEFAULT_PROGRESS_RULES,
    with_add: bool = True,
) -> list:
    rows = [
        (
            "── [D] progress_apply — 세이브의 progress 숫자에 따라 자동으로 모습 변경 ──",
            "_hint_prog",
            "hint",
        ),
        (
            "  when 예: progress_flower1_1 == 1003 · 위에서 아래로 첫 번째 맞는 규칙만 적용",
            "_hint_prog2",
            "hint",
        ),
    ]
    for i in range(1, rule_count + 1):
        p = f"{prog_prefix}{i}_"
        rows.append((f"  규칙{i} when", f"{p}when", "text"))
        rows.append((f"  규칙{i} visible", f"{p}visible", "dropdown", VISIBLE_OPTS))
        rows.append((f"  규칙{i} anim", f"{p}anim", "text"))
        rows.append((f"  규칙{i} anim_mode", f"{p}anim_mode", "dropdown", ANIM_MODE_OPTS))
        rows.append((f"  규칙{i} change_to", f"{p}change_to", "text"))
        rows.append((f"  규칙{i} dir", f"{p}dir", "dropdown", DIR_OPTS))
    if with_add:
        rows.append(_add_btn_row("+ 단계 추가", f"_add:prog:{prog_prefix}"))
    return rows


def _spawn_progress_editor_rows(*, spawn_prefix: str = "spawn_", prog_prefix: str = "prog") -> list:
    """char_defs / object_defs 공통 — [C] 초기값 · [D] progress_apply."""
    rows = _spawn_editor_rows(spawn_prefix=spawn_prefix)
    rows.extend(_progress_editor_rows(prog_prefix=prog_prefix))
    return rows


def _binding_inline_rows(*, bind_count: int = DEFAULT_BIND_SLOTS) -> list:
    """bindings 슬롯 — 이벤트 ID 또는 인라인 state/after."""
    rows = [
        (
            "  ※ 이벤트 ID를 비우면 아래 state/after 만 즉시 적용 (events.json 없이)",
            "_hint_bind_inline",
            "hint",
        ),
    ]
    for i in range(1, bind_count + 1):
        rows.append((f"  #{i} after (progress)", f"bind{i}_after", "text"))
        rows.append((f"  #{i} state visible", f"bind{i}_st_visible", "dropdown", VISIBLE_OPTS))
        rows.append((f"  #{i} state anim", f"bind{i}_st_anim", "text"))
        rows.append((f"  #{i} state anim_mode", f"bind{i}_st_anim_mode", "dropdown", ANIM_MODE_OPTS))
    return rows

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
    bind_count = max(
        DEFAULT_BIND_SLOTS,
        len(bindings or []),
        _max_numbered_slot(fields, "bind"),
    )
    for i in range(1, bind_count + 1):
        _init_bind_slot_fields(fields, i)
    for i, b in enumerate(bindings or []):
        if not isinstance(b, dict):
            continue
        n = i + 1
        fields[f"bind{n}_cond"] = str(b.get("condition") or "")
        fields[f"bind{n}_event"] = str(b.get("event_id") or "")
        fields[f"bind{n}_after"] = _format_talk_after(b.get("after"))
        try:
            fields[f"bind{n}_pri"] = str(int(b.get("priority", 100)))
        except (TypeError, ValueError):
            fields[f"bind{n}_pri"] = "100"
        st = b.get("state") if isinstance(b.get("state"), dict) else None
        if not st:
            st = {
                k: b.get(k)
                for k in ("visible", "anim", "anim_mode", "change_to", "dir", "spawn")
                if k in b
            }
            st = st or None
        if isinstance(st, dict):
            fields[f"bind{n}_st_visible"] = _opt_bool_field(st.get("visible"), "")
            fields[f"bind{n}_st_anim"] = str(st.get("anim") or st.get("state") or "")
            fields[f"bind{n}_st_anim_mode"] = str(st.get("anim_mode") or st.get("mode") or "")


def _binding_inline_state_from_fields(fields: dict, slot: int) -> Optional[dict]:
    return _state_patch_from_fields(fields, f"bind{slot}_st_")


def _interact_enabled_field(inter: dict) -> str:
    from flow import interact_spec_enabled

    return "true" if interact_spec_enabled(inter or {}) else "false"


def _bindings_from_slot_fields(fields: dict) -> list:
    out = []
    bind_count = max(DEFAULT_BIND_SLOTS, _max_numbered_slot(fields, "bind"))
    for i in range(1, bind_count + 1):
        cond = str(fields.get(f"bind{i}_cond") or "").strip()
        eid = str(fields.get(f"bind{i}_event") or "").strip()
        after = _parse_talk_after(fields.get(f"bind{i}_after"))
        st = _binding_inline_state_from_fields(fields, i)
        if not cond and not eid and not after and not st:
            continue
        if not cond:
            continue
        row: dict = {"condition": cond}
        if eid:
            row["event_id"] = eid
        if st:
            row["state"] = st
        if after:
            row["after"] = after
        if not eid and not st and not after:
            continue
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
        ("상호작용 거리 (픽셀)", "interact_range", "text"),
        ("중심 X (발 위치 기준)", "interact_offset_x", "text"),
        ("중심 Y (발 위치 기준, +는 아래)", "interact_offset_y", "text"),
        (
            "※ 거리·offset 을 비우면 char_defs / object_defs 기본값 사용",
            "_hint_interact_anchor",
            "hint",
        ),
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


def _bindings_slot_rows(*, bind_count: int = DEFAULT_BIND_SLOTS, with_add: bool = True) -> list:
    """bindings 본문 (섹션 헤더 없음)."""
    rows = [
        ("상호작용 사용", "interact_enabled", "dropdown", BOOL_OPTS),
    ]
    rows.extend(_interact_range_offset_rows())
    rows.append(
        (
            "  조건=progress 식 · 이벤트 ID=events.json · 우선순위 숫자 클수록 먼저 검사",
            "_hint_bind",
            "hint",
        )
    )
    for i in range(1, bind_count + 1):
        rows.append((f"  #{i} 조건", f"bind{i}_cond", "text"))
        rows.append((f"  #{i} 이벤트 ID", f"bind{i}_event", "events"))
        rows.append((f"  #{i} 우선순위", f"bind{i}_pri", "text"))
    rows.extend(_binding_inline_rows(bind_count=bind_count))
    if with_add:
        rows.append(_add_btn_row("+ 단계 추가", "_add:bind"))
    return rows


def _bindings_core_rows(
    *,
    intro_hint: str = "_hint_evt",
    bind_count: int = DEFAULT_BIND_SLOTS,
    with_add: bool = True,
) -> list:
    rows = [
        ("── [A] 클릭 상호작용 (bindings) ──", intro_hint, "hint"),
        (
            "  플레이어가 클릭했을 때 — 조건 맞으면 이벤트 실행 또는 즉시 상태 변경",
            "_hint_evt2",
            "hint",
        ),
    ]
    rows.extend(_bindings_slot_rows(bind_count=bind_count, with_add=with_add))
    return rows


def _talk_line_rows(*, talk_count: int = DEFAULT_TALK_LINES, with_add: bool = True) -> list:
    rows = []
    for i in range(1, talk_count + 1):
        rows.append((f"  대사{i} when", f"line{i}_when", "text"))
        rows.append((f"  대사{i} text", f"line{i}_text", "text"))
        rows.append((f"  대사{i} after", f"line{i}_after", "text"))
    if with_add:
        rows.append(_add_btn_row("+ 단계 추가", "_add:talk"))
    return rows


def char_def_modal_section_rows(
    *,
    bind_count: int = DEFAULT_BIND_SLOTS,
    talk_count: int = DEFAULT_TALK_LINES,
    prog_count: int = DEFAULT_PROGRESS_RULES,
) -> dict:
    basic_setup = [
        (
            "※ NPC 타입 기본값 — char_defs.json 에 저장 · 맵마다 덮어쓰려면 맵 인스턴스 모달 사용",
            "_hint_char_def_intro",
            "hint",
        ),
        ("표시 이름 (대화창에 나오는 이름)", "display_name", "text"),
    ]
    basic_setup.extend(_spawn_editor_rows(spawn_prefix="spawn_"))
    basic_setup.extend(
        [
            ("── 이동 AI (behavior) ──", "_hint_beh", "hint"),
            ("behavior mode — idle=가만히, patrol=왕복 등", "behavior_mode", "dropdown", BEHAVIOR_OPTS),
            ("jump_max_gap — 점프로 넘을 수 있는 틈(픽셀)", "jump_max_gap", "text"),
            ("mask_nav — true면 마스크 위를 걸어다님", "mask_nav", "dropdown", BOOL_OPTS),
        ]
    )
    return {
        "basic_setup": basic_setup,
        "progress": _progress_editor_rows(prog_prefix="prog", rule_count=prog_count),
        "interact": _bindings_core_rows(bind_count=bind_count),
        "talk": [
            ("── [B] 일상 대사 (게임 중 말 걸기) ──", "_hint_talk", "hint"),
            ("대화 시 플레이어 쪽 바라보기", "face_player", "dropdown", BOOL_OPTS),
            (
                "  when=progress 조건 · 위에서 아래 첫 번째 맞는 대사만 표시",
                "_hint_talk_when",
                "hint",
            ),
        ]
        + _talk_line_rows(talk_count=talk_count)
        + [
            ("  기본 대사 (위 조건 모두 안 맞을 때)", "fallback_text", "text"),
            ("  after 예: progress_c10_talk:1 — 대사 후 progress 변경", "_hint_talk_after", "hint"),
        ],
    }


def char_def_modal_rows() -> list:
    rows = []
    for _sid, sec_rows in char_def_modal_section_rows().items():
        rows.extend(sec_rows)
    return rows


def char_inst_modal_section_rows(
    *,
    bind_count: int = DEFAULT_BIND_SLOTS,
    inst_prog_count: int = DEFAULT_PROGRESS_RULES,
) -> dict:
    basic_setup = [
        (
            "※ 이 맵에만 적용 — 비우면 char_defs 타입 기본값 사용 (world_data.json 저장)",
            "_hint_inst_intro",
            "hint",
        ),
        ("Instance ID (구분용, 비워도 됨)", "instance_id", "text"),
        ("── 맵 전용: spawn (타입 [C] 덮어쓰기) ──", "_hint_inst_spawn", "hint"),
    ]
    basic_setup.extend(_spawn_editor_rows(spawn_prefix="inst_spawn_"))
    basic_setup.extend(
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
    return {
        "basic_setup": basic_setup,
        "progress": [
            ("── 맵 전용: progress (타입 [D] 덮어쓰기) ──", "_hint_inst_prog", "hint"),
        ]
        + _progress_editor_rows(prog_prefix="inst_prog", rule_count=inst_prog_count),
        "interact": [
            ("── 맵 전용: 클릭 상호작용 bindings ──", "_hint_inst_evt", "hint"),
            (
                "※ 여기 입력한 bindings 가 타입(char_defs) 설정보다 우선합니다",
                "_hint_inst_talk",
                "hint",
            ),
        ]
        + _bindings_slot_rows(bind_count=bind_count),
    }


def char_inst_modal_rows() -> list:
    rows = []
    for sec_rows in char_inst_modal_section_rows().values():
        rows.extend(sec_rows)
    return rows


def obj_def_modal_section_rows(
    *,
    bind_count: int = DEFAULT_BIND_SLOTS,
    prog_count: int = DEFAULT_PROGRESS_RULES,
) -> dict:
    return {
        "basic_setup": _spawn_editor_rows(spawn_prefix="spawn_"),
        "progress": _progress_editor_rows(prog_prefix="prog", rule_count=prog_count),
        "interact": _interact_binding_modal_rows(bind_count=bind_count),
    }


def obj_inst_modal_section_rows(
    *,
    bind_count: int = DEFAULT_BIND_SLOTS,
    inst_prog_count: int = DEFAULT_PROGRESS_RULES,
) -> dict:
    basic_setup = [
        (
            "※ 이 맵에만 적용 — 비우면 object_defs 타입 기본값 사용",
            "_hint_obj_inst_intro",
            "hint",
        ),
    ]
    basic_setup.extend(_spawn_editor_rows(spawn_prefix="inst_spawn_"))
    return {
        "basic_setup": basic_setup,
        "progress": _progress_editor_rows(prog_prefix="inst_prog", rule_count=inst_prog_count),
        "interact": _interact_binding_modal_rows(bind_count=bind_count),
    }


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
    talk_count = max(DEFAULT_TALK_LINES, len(lines))
    for i in range(1, talk_count + 1):
        if i - 1 < len(lines):
            ln = lines[i - 1]
            say = ln.get("say") or {}
            fields[f"line{i}_when"] = _format_talk_when(ln.get("when"))
            fields[f"line{i}_text"] = str(say.get("text") or "")
            fields[f"line{i}_after"] = _format_talk_after(ln.get("after"))
        else:
            _init_talk_line_fields(fields, i)
    if not fields["display_name"]:
        fields["display_name"] = char_name
    _state_patch_to_fields(cdef.get("spawn_state") or {}, fields, "spawn_")
    _progress_apply_to_fields(cdef.get("progress_apply"), fields, slot_prefix="prog")
    return fields


def fields_to_char_def(fields: dict, char_name: str) -> dict:
    from char_behavior import get_char_type_def, _deep_merge

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
    ss = _state_patch_from_fields(fields, "spawn_")
    if ss:
        out["spawn_state"] = ss
    pa = _progress_apply_from_fields(fields, slot_prefix="prog")
    if pa:
        out["progress_apply"] = pa
    lines = []
    talk_count = max(DEFAULT_TALK_LINES, _max_numbered_slot(fields, "line"))
    for i in range(1, talk_count + 1):
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
    merged = _deep_merge(base, out)
    if str(fields.get("mask_nav", "false")).lower() not in ("true", "1", "yes"):
        merged.pop("mask_nav", None)
    if not ss and "spawn_state" in merged:
        merged.pop("spawn_state", None)
    if not pa and "progress_apply" in merged:
        merged.pop("progress_apply", None)
    if ss:
        merged["spawn_state"] = ss
    if pa:
        merged["progress_apply"] = pa
    return merged


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
    we = getattr(npc, "_world_entry", None) or {}
    _state_patch_to_fields(we.get("spawn_state") or {}, fields, "inst_spawn_")
    _progress_apply_to_fields(we.get("progress_apply"), fields, slot_prefix="inst_prog")
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
    ss = _state_patch_from_fields(fields, "inst_spawn_")
    if ss:
        entry["spawn_state"] = ss
    else:
        entry.pop("spawn_state", None)
    pa = _progress_apply_from_fields(fields, slot_prefix="inst_prog")
    if pa:
        entry["progress_apply"] = pa
    else:
        entry.pop("progress_apply", None)
    npc._world_entry = dict(entry)
    attach_npc_from_entry(npc, entry)
    from char_behavior import apply_entity_progress_state
    from flow import GameFlow

    try:
        gf = GameFlow()
        apply_entity_progress_state(npc, gf.save_data)
    except Exception:
        pass


class _ConfigModal:
    """zone 모달과 동일 패턴의 단순 설정창."""

    tag: str = "cfg"
    title: str = "CONFIG"

    def get_sections(self) -> List[Tuple[str, str]]:
        return []

    def get_section_rows(self) -> Dict[str, list]:
        return {}

    def get_rows(self) -> list:
        sections = self.get_sections()
        if not sections:
            return []
        sec_map = self.get_section_rows()
        sid = self.section_id or sections[0][0]
        return list(sec_map.get(sid, []))

    def __init__(self):
        self.show = False
        self.fields: Dict[str, str] = {}
        self.scroll = 0
        self.section_id = ""
        self.slot_counts: Dict[str, int] = _default_slot_counts()
        self.active_field: Optional[str] = None
        self.dd_open = False
        self.dd_key: Optional[str] = None
        self.dd_scroll = 0
        self.dd_rect = None
        self.dd_options: list = []
        self.dd_ui = None
        self._body_drag = False
        self._dd_drag = False

    def _reset_section(self):
        sections = self.get_sections()
        self.section_id = sections[0][0] if sections else ""

    def _sync_slot_counts_from_fields(self):
        base = _default_slot_counts()
        base["bind"] = max(base["bind"], _max_numbered_slot(self.fields, "bind"))
        base["talk"] = max(base["talk"], _max_numbered_slot(self.fields, "line"))
        base["prog"] = max(base["prog"], _max_numbered_slot(self.fields, "prog"))
        base["inst_prog"] = max(base["inst_prog"], _max_numbered_slot(self.fields, "inst_prog"))
        self.slot_counts = base

    def _scroll_to_bottom(self, ctx) -> None:
        from editor import _editor_modal_body_scroll_layout, _editor_std_modal_rect

        rows = self.get_rows()
        sw, sh = ctx["screen_w"], ctx["screen_h"]
        panel_rect, content_h, _ = _editor_std_modal_rect(sw, sh, len(rows))
        sbh = self._section_bar_h()
        _, _, max_scroll, _ = _editor_modal_body_scroll_layout(panel_rect, 0, content_h, sbh)
        self.scroll = max_scroll

    def _on_add_slot_click(self, add_id: str, ctx) -> None:
        if add_id == "_add:bind":
            if self.slot_counts["bind"] >= MAX_EXPAND_SLOTS:
                return
            self.slot_counts["bind"] += 1
            _init_bind_slot_fields(self.fields, self.slot_counts["bind"])
        elif add_id == "_add:talk":
            if self.slot_counts["talk"] >= MAX_EXPAND_SLOTS:
                return
            self.slot_counts["talk"] += 1
            _init_talk_line_fields(self.fields, self.slot_counts["talk"])
        elif add_id.startswith("_add:prog:"):
            prefix = add_id[len("_add:prog:") :]
            cur = self.slot_counts.get(prefix, DEFAULT_PROGRESS_RULES)
            if cur >= MAX_EXPAND_SLOTS:
                return
            self.slot_counts[prefix] = cur + 1
            _init_prog_rule_fields(self.fields, prefix, self.slot_counts[prefix])
        else:
            return
        self.dd_open = False
        self.active_field = None
        self._scroll_to_bottom(ctx)

    def _section_bar_h(self) -> int:
        from editor import EDITOR_MODAL_SECTION_BAR_H

        return EDITOR_MODAL_SECTION_BAR_H if self.get_sections() else 0

    def _section_tab_layout(self, panel_rect) -> List[Tuple[str, str, pygame.Rect]]:
        sections = self.get_sections()
        if not sections:
            return []
        from editor import EDITOR_MODAL_HEADER_H

        pad_x = 8
        y = panel_rect.y + EDITOR_MODAL_HEADER_H + 4
        h = 30
        gap = 4
        n = len(sections)
        avail = panel_rect.width - 2 * pad_x
        tw = max(48, int((avail - gap * (n - 1)) / n))
        out: List[Tuple[str, str, pygame.Rect]] = []
        x = panel_rect.x + pad_x
        for sid, label in sections:
            w = min(tw, panel_rect.right - pad_x - x)
            if w < 40:
                break
            out.append((sid, label, pygame.Rect(x, y, w, h)))
            x += w + gap
        return out

    def _paint_section_tabs(self, screen, font, panel_rect):
        tabs = self._section_tab_layout(panel_rect)
        if not tabs:
            return
        from editor import EDITOR_MODAL_HEADER_H

        line_y = panel_rect.y + EDITOR_MODAL_HEADER_H + 34
        pygame.draw.line(
            screen, (90, 90, 90), (panel_rect.x + 8, line_y), (panel_rect.right - 8, line_y)
        )
        active_sid = self.section_id or tabs[0][0]
        for sid, label, rect in tabs:
            active = sid == active_sid
            bg = (70, 90, 130) if active else (48, 48, 48)
            pygame.draw.rect(screen, bg, rect)
            pygame.draw.rect(screen, (160, 160, 160), rect, 1)
            ts = font.render(label, True, (255, 255, 255) if active else (190, 190, 190))
            tx = rect.x + max(4, (rect.width - ts.get_width()) // 2)
            screen.blit(ts, (tx, rect.y + 7))

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
            _editor_modal_sb_hit,
            _editor_pointer_xy,
            _editor_rects_contain_point,
            _editor_scroll_px_from_sb_my,
            _editor_std_modal_rect,
            _editor_wheel_delta,
            _step_overlay_scrollbar_layout,
        )

        rows = self.get_rows()
        sw, sh = ctx["screen_w"], ctx["screen_h"]
        mx, my = ctx["mouse"]
        panel_rect, content_h, _ = _editor_std_modal_rect(sw, sh, len(rows))
        sbh = self._section_bar_h()
        body_rect, sb_rect, max_scroll, _ = _editor_modal_body_scroll_layout(
            panel_rect, self.scroll, content_h, sbh
        )
        save_btn = pygame.Rect(panel_rect.centerx - 110, panel_rect.bottom - 50, 100, 35)
        canc_btn = pygame.Rect(panel_rect.centerx + 10, panel_rect.bottom - 50, 100, 35)
        field_x = body_rect.x + 148
        field_w, list_w = 220, 52
        dd_item_h = 22
        modal_body_drag = ctx.get("modal_body_drag")
        modal_dd_drag = ctx.get("modal_dropdown_drag")

        if event.type == pygame.MOUSEWHEEL:
            px, py = _editor_pointer_xy(event, mx, my)
            delta = _editor_wheel_delta(event)
            if self.dd_open and self.dd_rect:
                total_h = len(self.dd_options) * dd_item_h
                vis = max(1, self.dd_rect.height)
                max_dd = max(0, total_h - vis)
                if max_dd > 0 and _editor_rects_contain_point(px, py, self.dd_rect, body_rect, panel_rect):
                    self.dd_scroll = max(0, min(max_dd, self.dd_scroll + delta))
            elif _editor_rects_contain_point(px, py, body_rect, sb_rect, panel_rect) and max_scroll > 0:
                self.scroll = max(0, min(max_scroll, self.scroll + delta))
            return True

        if event.type == pygame.MOUSEMOTION and modal_body_drag == self.tag:
            ui_sb = _step_overlay_scrollbar_layout(
                sb_rect, body_rect.height, content_h, self.scroll
            )
            sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_sb)
            if sp is not None:
                self.scroll = sp
            return True

        if event.type == pygame.MOUSEMOTION and modal_dd_drag == f"{self.tag}_dd":
            if self.dd_ui and self.dd_ui.get("track"):
                sp = _editor_scroll_px_from_sb_my(event.pos[1], self.dd_ui)
                if sp is not None:
                    self.dd_scroll = sp
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
                    if ui_prev:
                        dd_hit = _editor_modal_sb_hit(event.pos, ui_prev)
                        if dd_hit == "thumb":
                            ctx["modal_dropdown_drag"] = f"{self.tag}_dd"
                            return True
                        if dd_hit == "track":
                            sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_prev)
                            if sp is not None:
                                self.dd_scroll = sp
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

            for sid, _label, tab_rect in self._section_tab_layout(panel_rect):
                if tab_rect.collidepoint(event.pos):
                    if sid != self.section_id:
                        self.section_id = sid
                        self.scroll = 0
                        self.dd_open = False
                        self.active_field = None
                    return True

            ui_sb = _step_overlay_scrollbar_layout(
                sb_rect, body_rect.height, content_h, self.scroll
            )
            sb_hit = _editor_modal_sb_hit(event.pos, ui_sb)
            if sb_hit == "thumb":
                ctx["modal_body_drag"] = self.tag
                return True
            if sb_hit == "track":
                sp = _editor_scroll_px_from_sb_my(event.pos[1], ui_sb)
                if sp is not None:
                    self.scroll = sp
                return True

            self.active_field = None
            for i, row in enumerate(rows):
                rk = row[1]
                kind = row[2]
                ry = body_rect.y + i * EDITOR_MODAL_ROW_H - self.scroll
                if ry + EDITOR_MODAL_ROW_H < body_rect.top or ry > body_rect.bottom:
                    continue
                if kind == "add_btn":
                    btn_w = min(200, body_rect.width - 24)
                    btn_rect = pygame.Rect(
                        body_rect.centerx - btn_w // 2, ry + 3, btn_w, EDITOR_MODAL_ROW_H - 6
                    )
                    if btn_rect.collidepoint(event.pos):
                        self._on_add_slot_click(rk, ctx)
                        return True
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
        sbh = self._section_bar_h()
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
            section_bar_h=sbh,
        )
        self._paint_section_tabs(screen, font, panel_rect)
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
    title = "NPC 타입 (char_defs)"

    def get_sections(self):
        return [
            ("basic_setup", "기본설정"),
            ("progress", "자동 실행"),
            ("interact", "상호작용(이벤트)"),
            ("talk", "상호작용(대화)"),
        ]

    def get_section_rows(self):
        return char_def_modal_section_rows(
            bind_count=self.slot_counts["bind"],
            talk_count=self.slot_counts["talk"],
            prog_count=self.slot_counts["prog"],
        )

    def get_rows(self):
        return super().get_rows()

    def __init__(self):
        super().__init__()
        self.target_name: str = ""

    def open(self, char_name: str):
        from char_behavior import get_char_type_def

        self.target_name = char_name
        self.fields = char_def_to_fields(get_char_type_def(char_name), char_name)
        self._sync_slot_counts_from_fields()
        self.show = True
        self.scroll = 0
        self._reset_section()
        self.active_field = None
        self.dd_open = False

    def on_save(self, ctx):
        save_char_def_to_json(self.target_name, self.fields)
        ctx.get("on_char_def_saved", lambda _n: None)(self.target_name)


class CharInstModal(_ConfigModal):
    tag = "char_inst"
    title = "NPC 맵 인스턴스"

    def get_sections(self):
        return [
            ("basic_setup", "기본설정"),
            ("progress", "자동 실행"),
            ("interact", "상호작용(이벤트)"),
        ]

    def get_section_rows(self):
        return char_inst_modal_section_rows(
            bind_count=self.slot_counts["bind"],
            inst_prog_count=self.slot_counts["inst_prog"],
        )

    def get_rows(self):
        return super().get_rows()

    def __init__(self):
        super().__init__()
        self.target_npc = None

    def open(self, npc):
        self.target_npc = npc
        self.fields = char_inst_fields_from_npc(npc)
        self._sync_slot_counts_from_fields()
        self.show = True
        self.scroll = 0
        self._reset_section()
        self.active_field = None
        self.dd_open = False

    def on_save(self, ctx):
        if self.target_npc:
            apply_char_inst_fields(self.target_npc, self.fields)
        cb = ctx.get("on_inst_saved")
        if callable(cb):
            cb()


def _interact_binding_modal_rows(
    *, bind_count: int = DEFAULT_BIND_SLOTS, with_add: bool = True
) -> list:
    rows = [
        (
            "── [A] 클릭 상호작용 (bindings) — 오브젝트를 클릭했을 때 ──",
            "_hint_obj_evt",
            "hint",
        ),
        (
            "  조건이 맞으면 events.json 이벤트 실행 · 비우면 들기(CARRY) 등 기본 동작",
            "_hint_obj_evt2",
            "hint",
        ),
        ("상호작용 사용", "interact_enabled", "dropdown", BOOL_OPTS),
    ]
    rows.extend(_interact_range_offset_rows())
    rows.append(
        (
            "  조건=progress 식 · 이벤트 ID · 우선순위(숫자 클수록 먼저 검사)",
            "_hint_obj_bind",
            "hint",
        )
    )
    for i in range(1, bind_count + 1):
        rows.append((f"  #{i} 조건", f"bind{i}_cond", "text"))
        rows.append((f"  #{i} 이벤트 ID", f"bind{i}_event", "events"))
        rows.append((f"  #{i} 우선순위", f"bind{i}_pri", "text"))
    rows.extend(_binding_inline_rows(bind_count=bind_count))
    if with_add:
        rows.append(_add_btn_row("+ 단계 추가", "_add:bind"))
    return rows


def obj_interact_modal_rows() -> list:
    rows = []
    for sec_rows in obj_def_modal_section_rows().values():
        rows.extend(sec_rows)
    return rows


def _obj_def_to_fields(odef: dict) -> dict:
    fields = _fields_from_interact_dict((odef or {}).get("interact"))
    _state_patch_to_fields((odef or {}).get("spawn_state") or {}, fields, "spawn_")
    _progress_apply_to_fields((odef or {}).get("progress_apply"), fields, slot_prefix="prog")
    return fields


def _obj_def_from_fields(fields: dict, base: dict) -> dict:
    from char_behavior import _deep_merge

    row = _deep_merge(dict(base or {}), {})
    row["interact"] = _interact_dict_from_fields(fields)
    ss = _state_patch_from_fields(fields, "spawn_")
    if ss:
        row["spawn_state"] = ss
    else:
        row.pop("spawn_state", None)
    pa = _progress_apply_from_fields(fields, slot_prefix="prog")
    if pa:
        row["progress_apply"] = pa
    else:
        row.pop("progress_apply", None)
    return row


def _fields_from_interact_dict(inter: dict) -> dict:
    from data import CONFIG

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
    title = "오브젝트 타입 (object_defs)"

    def get_sections(self):
        return [
            ("basic_setup", "기본설정"),
            ("progress", "자동 실행"),
            ("interact", "상호작용(이벤트)"),
        ]

    def get_section_rows(self):
        return obj_def_modal_section_rows(
            bind_count=self.slot_counts["bind"],
            prog_count=self.slot_counts["prog"],
        )

    def get_rows(self):
        return super().get_rows()

    def __init__(self):
        super().__init__()
        self.target_name = ""

    def open(self, obj_name: str):
        from data import OBJ_ASSETS

        self.target_name = str(obj_name or "")
        info = OBJ_ASSETS.get(self.target_name, {})
        self.fields = _obj_def_to_fields(info)
        self._sync_slot_counts_from_fields()
        self.show = True
        self.scroll = 0
        self._reset_section()
        self.active_field = None
        self.dd_open = False

    def on_save(self, ctx):
        from entity_defs import load_object_defs, reload_entity_defs, save_object_defs

        all_defs = load_object_defs()
        base = dict(all_defs.get(self.target_name, {}) or {})
        all_defs[self.target_name] = _obj_def_from_fields(self.fields, base)
        save_object_defs(all_defs)
        reload_entity_defs()
        cb = ctx.get("on_obj_def_saved")
        if callable(cb):
            cb(self.target_name)


class ObjInstModal(_ConfigModal):
    """맵에 배치된 FieldItem 인스턴스 interact (world_data.objects[].interact)."""

    tag = "obj_inst"
    title = "오브젝트 맵 인스턴스"

    def get_sections(self):
        return [
            ("basic_setup", "기본설정"),
            ("progress", "자동 실행"),
            ("interact", "상호작용(이벤트)"),
        ]

    def get_section_rows(self):
        return obj_inst_modal_section_rows(
            bind_count=self.slot_counts["bind"],
            inst_prog_count=self.slot_counts["inst_prog"],
        )

    def get_rows(self):
        return super().get_rows()

    def __init__(self):
        super().__init__()
        self.target_item = None

    def open(self, item):
        from data import OBJ_ASSETS

        self.target_item = item
        inst = getattr(item, "interact_instance", None) or {}
        self.fields = _fields_from_interact_dict(inst if isinstance(inst, dict) else {})
        we = getattr(item, "_world_entry", None) or {}
        _state_patch_to_fields(we.get("spawn_state") or {}, self.fields, "inst_spawn_")
        _progress_apply_to_fields(we.get("progress_apply"), self.fields, slot_prefix="inst_prog")
        self._sync_slot_counts_from_fields()
        self.show = True
        self.scroll = 0
        self._reset_section()
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
        we = dict(getattr(self.target_item, "_world_entry", None) or {})
        we["name"] = self.target_item.name
        we["pos"] = [int(self.target_item.pos[0]), int(self.target_item.pos[1])]
        ss = _state_patch_from_fields(self.fields, "inst_spawn_")
        if ss:
            we["spawn_state"] = ss
        else:
            we.pop("spawn_state", None)
        pa = _progress_apply_from_fields(self.fields, slot_prefix="inst_prog")
        if pa:
            we["progress_apply"] = pa
        else:
            we.pop("progress_apply", None)
        self.target_item._world_entry = we
        from char_behavior import apply_entity_progress_state
        from flow import GameFlow

        try:
            apply_entity_progress_state(self.target_item, GameFlow().save_data)
        except Exception:
            pass
        cb = ctx.get("on_inst_saved")
        if callable(cb):
            cb()


class PresenceZoneModal(_ConfigModal):
    """MAP presence_zones — 화면/플레이어/지정 오브젝트 상태 오버레이."""

    tag = "presence_zone"
    title = "PRESENCE BOX"

    def __init__(self):
        super().__init__()
        self.edit_idx: Optional[int] = None
        self.rect: Optional[list] = None
        self.target_count: int = DEFAULT_PRESENCE_TARGETS

    def get_sections(self):
        return [
            ("basic", "기본"),
            ("field", "화면(틸트/쉬어)"),
            ("player", "플레이어"),
            ("targets", "지정 오브젝트"),
        ]

    def get_section_rows(self):
        return presence_zone_modal_section_rows(target_count=self.target_count)

    def _event_id_options(self, ctx) -> list:
        if (self.dd_key or "").startswith("tgt") and (self.dd_key or "").endswith("_name"):
            names = list(ctx.get("map_entity_names") or [])
            return [""] + sorted({str(n) for n in names if str(n).strip() and str(n).lower() != "player"})
        return super()._event_id_options(ctx)

    def _on_add_slot_click(self, add_id: str, ctx) -> None:
        if add_id == "_area:pick":
            cb = ctx.get("on_presence_area_pick")
            if callable(cb):
                cb()
            return
        if add_id == "_add:tgt":
            if self.target_count >= MAX_EXPAND_SLOTS:
                return
            self.target_count += 1
            p = f"tgt{self.target_count}_"
            self.fields[f"{p}name"] = ""
            _tune_fields_from_patch({}, self.fields, p)
            self.dd_open = False
            self.active_field = None
            self._scroll_to_bottom(ctx)
            return
        super()._on_add_slot_click(add_id, ctx)

    def open_new(self):
        self.edit_idx = None
        self.rect = None
        self.target_count = DEFAULT_PRESENCE_TARGETS
        self.fields = presence_zone_to_fields({}, target_count=self.target_count)[0]
        self.show = True
        self.scroll = 0
        self._reset_section()
        self.active_field = None
        self.dd_open = False

    def open_edit(self, zone: dict, edit_idx: int):
        self.edit_idx = int(edit_idx)
        rect = zone.get("rect")
        self.rect = list(rect) if isinstance(rect, (list, tuple)) and len(rect) >= 4 else None
        self.fields, self.target_count = presence_zone_to_fields(zone, target_count=DEFAULT_PRESENCE_TARGETS)
        self.show = True
        self.scroll = 0
        self._reset_section()
        self.active_field = None
        self.dd_open = False

    def set_rect(self, rect):
        if isinstance(rect, (list, tuple)) and len(rect) >= 4:
            self.rect = [int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])]

    def on_save(self, ctx):
        rect = self.rect
        if not rect or rect[2] <= 0 or rect[3] <= 0:
            print("[PresenceZone] rect 미지정 — 저장 취소")
            return
        z = presence_zone_from_fields(self.fields, rect, target_count=self.target_count)
        cb = ctx.get("on_presence_zone_saved")
        if callable(cb):
            cb(z, self.edit_idx)


char_def_modal = CharDefModal()
char_inst_modal = CharInstModal()
obj_def_modal = ObjDefModal()
obj_inst_modal = ObjInstModal()
presence_zone_modal = PresenceZoneModal()


def any_char_modal_open() -> bool:
    return (
        char_def_modal.show
        or char_inst_modal.show
        or obj_def_modal.show
        or obj_inst_modal.show
        or presence_zone_modal.show
    )


def close_all_char_modals():
    char_def_modal.close()
    char_inst_modal.close()
    obj_def_modal.close()
    obj_inst_modal.close()
    presence_zone_modal.close()

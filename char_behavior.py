"""
NPC·엔티티 정의(char_defs / object_defs via flow.build_obj_def)와 런타임 행동.

- build_npc_def / attach_npc_from_entry — 타입+맵 인스턴스 병합
- talk (when/after) · interact bindings — progress 조건 (flow.py 와 공유)
- spawn_state / progress_apply — apply_map_progress_states (load_map·이벤트 종료 후)
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any, Optional

from data import CHAR_ASSETS, CONFIG
from flow import build_eval_ctx, evaluate_global_condition


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base) if base else {}
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def get_char_type_def(name: str) -> dict:
    return dict(CHAR_ASSETS.get(name, {}) or {})


def get_char_ui_name(char_id: str) -> str:
    """UI·야구 등에 쓸 짧은 이름 (char_defs name → id)."""
    cid = str(char_id or "").strip()
    if not cid:
        return ""
    info = get_char_type_def(cid)
    nm = str(info.get("name") or "").strip()
    return nm or cid


def get_char_call_name(char_id: str) -> str:
    """
    호칭(대화용). 여름이→여름아, 이경이→이경아, 유하→유하야.
    char_defs.call_name 이 있으면 우선, 없으면 name 규칙으로 유도.
    """
    cid = str(char_id or "").strip()
    if not cid:
        return ""
    info = get_char_type_def(cid)
    explicit = str(info.get("call_name") or "").strip()
    if explicit:
        return explicit
    nm = str(info.get("name") or "").strip() or cid
    if nm.endswith("이"):
        return nm[:-1] + "아"
    return nm + "야"


def char_body_type(cdef: dict | None) -> str:
    """캐릭터 체형 — adult | kid | animal (야구 오버레이 세트 선택)."""
    t = str((cdef or {}).get("type") or "adult").strip().lower()
    if t in ("kid", "child"):
        return "kid"
    if t in ("animal", "pet"):
        return "animal"
    return "adult"


def build_npc_def(name: str, world_entry: Optional[dict] = None) -> dict:
    """타입(char_defs) + world_data 인스턴스(overrides/behavior/interact) 병합."""
    base = get_char_type_def(name)
    entry = world_entry or {}
    merged = _deep_merge(base, entry.get("overrides") or {})
    if entry.get("talk"):
        merged["talk"] = _deep_merge(merged.get("talk") or {}, entry["talk"])
    if entry.get("behavior"):
        merged["behavior"] = _deep_merge(merged.get("behavior") or {}, entry["behavior"])
    if entry.get("interact"):
        merged["interact"] = _deep_merge(merged.get("interact") or {}, entry["interact"])
    if base.get("spawn_state") or entry.get("spawn_state"):
        merged["spawn_state"] = _deep_merge(
            base.get("spawn_state") or {}, entry.get("spawn_state") or {}
        )
    if entry.get("progress_apply"):
        merged["progress_apply"] = list(entry["progress_apply"])
    elif base.get("progress_apply"):
        merged["progress_apply"] = list(base["progress_apply"])
    return merged


def attach_interact_spec(entity, type_asset: dict, world_entry: dict = None):
    """NPC/오브젝트에 병합 interact + 맵 전용 interact_instance 부착."""
    from flow import merge_interact_spec

    entry = world_entry if isinstance(world_entry, dict) else {}
    entity.interact_instance = (
        dict(entry.get("interact") or {}) if isinstance(entry.get("interact"), dict) else {}
    )
    entity.interact_spec = merge_interact_spec(type_asset, entry)


def normalize_behavior_mode(mode: str) -> str:
    """UI/JSON 별칭 → 내부 모드. randomwalk=wander, play=randomplay."""
    m = str(mode or "idle").strip().lower()
    if m in ("randomwalk", "random_walk"):
        return "wander"
    if m in ("play",):
        return "randomplay"
    return m or "idle"


def display_behavior_mode(mode: str) -> str:
    """에디터 표시용 — wander → randomwalk."""
    m = normalize_behavior_mode(mode)
    if m == "wander":
        return "randomwalk"
    return m


def _behavior_mode_wants_mask_nav(mode) -> bool:
    """ambient 이동 AI — 마스크 위를 걸어야 하는 모드."""
    return normalize_behavior_mode(mode) in (
        "wander",
        "randomplay",
        "patrol",
        "follow",
        "flee",
    )


def spawn_as_mask_walker(name: str, world_entry: Optional[dict] = None) -> bool:
    """
    MaskWalkingCharacter 로 스폰할지.
    char_defs.mask_nav 또는 roam/play 계열 behavior 이면 True.
    """
    asset = CHAR_ASSETS.get(str(name or ""), {}) or {}
    if asset.get("mask_nav"):
        return True
    entry = world_entry if isinstance(world_entry, dict) else {}
    mode = None
    if entry.get("mode"):
        mode = entry.get("mode")
    beh = entry.get("behavior")
    if mode is None and isinstance(beh, dict):
        mode = beh.get("mode")
    elif mode is None and isinstance(beh, str):
        mode = beh
    if mode is None:
        mode = (asset.get("behavior") or {}).get("mode")
    return _behavior_mode_wants_mask_nav(mode)


def _roam_home(npc) -> tuple[float, float]:
    home = getattr(npc, "_bh_home", None)
    if isinstance(home, (list, tuple)) and len(home) >= 2:
        try:
            return float(home[0]), float(home[1])
        except (TypeError, ValueError):
            pass
    op = getattr(npc, "origin_pos", None)
    if isinstance(op, (list, tuple)) and len(op) >= 2:
        try:
            return float(op[0]), float(op[1])
        except (TypeError, ValueError):
            pass
    try:
        return float(npc.pos[0]), float(npc.pos[1])
    except (TypeError, ValueError):
        return 0.0, 0.0


def set_roam_home(npc, x=None, y=None) -> None:
    if x is None or y is None:
        try:
            x, y = float(npc.pos[0]), float(npc.pos[1])
        except (TypeError, ValueError):
            return
    npc._bh_home = [float(x), float(y)]


def set_npc_behavior(npc, mode, *, radius=None, interval_ms=None, clear_event_hold=True) -> None:
    """런타임 behavior.mode 설정 (캐릭터 기본·이벤트 BEHAVIOR/PLACE 공통)."""
    if npc is None:
        return
    m = normalize_behavior_mode(mode)
    spec = dict(getattr(npc, "behavior_spec", None) or {})
    # 저장/표시는 사용자 친화 이름 유지 (wander → randomwalk)
    spec["mode"] = display_behavior_mode(m)
    if radius is not None:
        try:
            spec["radius"] = float(radius)
        except (TypeError, ValueError):
            pass
    if interval_ms is not None:
        try:
            spec["interval_ms"] = int(interval_ms)
        except (TypeError, ValueError):
            pass
    npc.behavior_spec = spec
    if clear_event_hold:
        npc._bh_event_hold = False
    st = getattr(npc, "_bh_state", None)
    if not isinstance(st, dict):
        st = {}
        npc._bh_state = st
    st["wander_next_ms"] = 0
    st["play_next_ms"] = 0
    st["wander_target"] = None
    if m in ("idle", "frozen"):
        sm = getattr(npc, "stop_moving", None)
        if callable(sm):
            try:
                sm()
            except Exception:
                pass


def hold_npc_ai_for_event(npc) -> None:
    """MOVE/ACTION_ANIM 등 이벤트 직접 제어 시 ambient AI 일시 정지."""
    if npc is None:
        return
    npc._bh_event_hold = True


def attach_npc_from_entry(npc, world_entry: dict):
    """BaseCharacter / MaskWalkingCharacter 인스턴스에 정의·행동 상태 부착."""
    name = getattr(npc, "name", "") or ""
    entry = world_entry or {}
    npc.instance_id = str(entry.get("instance_id") or f"{name}@{int(npc.pos[0])}_{int(npc.pos[1])}")
    npc.char_def = build_npc_def(name, entry)
    npc._world_entry = dict(entry)
    from data import CHAR_ASSETS

    attach_interact_spec(npc, CHAR_ASSETS.get(name, {}), entry)
    npc.behavior_spec = dict((npc.char_def.get("behavior") or {}))
    raw_mode = npc.behavior_spec.get("mode")
    if raw_mode:
        npc.behavior_spec["mode"] = display_behavior_mode(raw_mode)
    npc._bh_state = {
        "patrol_idx": 0,
        "wait_until_ms": 0,
        "wander_next_ms": 0,
        "wander_target": None,
        "play_next_ms": 0,
    }
    npc._bh_event_hold = False
    wps = entry.get("waypoints")
    if wps:
        npc.behavior_spec.setdefault("waypoints", list(wps))
    if entry.get("mode"):
        npc.behavior_spec["mode"] = display_behavior_mode(entry["mode"])
    set_roam_home(npc)
    npc._in_npc_talk = False


def npc_interact_enabled(npc) -> bool:
    from flow import entity_interact_enabled

    cdef = getattr(npc, "char_def", None) or {}
    talk = cdef.get("talk") or {}
    if talk.get("lines") or talk.get("fallback"):
        return True
    return entity_interact_enabled(npc)


def get_interact_range(npc) -> float:
    from flow import entity_interact_range

    try:
        return float(
            entity_interact_range(
                npc, default=float(CONFIG.get("NPC_INTERACT_RANGE", 48))
            )
        )
    except (TypeError, ValueError):
        return 48.0


def face_toward_player(npc, player):
    if not getattr(npc, "char_def", {}).get("interact", {}).get("face_player_on_talk", True):
        return
    try:
        npc.direction = "left" if float(player.pos[0]) < float(npc.pos[0]) else "right"
    except Exception:
        pass


def eval_talk_when(when: Any, ctx: dict, npc_name: str = "") -> bool:
    """대사 줄 선택 조건 — 이벤트 bindings 와 동일한 progress 식(문자열) 우선."""
    if when is None:
        return True
    if isinstance(when, str):
        s = when.strip()
        return evaluate_global_condition(s, ctx) if s else True
    if not isinstance(when, dict):
        return True
    if "expr" in when:
        return evaluate_global_condition(when.get("expr"), ctx)
    flags = ctx.get("flags") or {}
    aff_all = ctx.get("affinity") or {}
    nf = when.get("not_flag")
    if nf is not None and flags.get(str(nf)):
        return False
    fk = when.get("flag")
    if fk is not None:
        cur = flags.get(str(fk))
        if "eq" in when:
            return cur == when.get("eq")
        if "neq" in when:
            return cur != when.get("neq")
        return bool(cur)
    mp = when.get("mainprogress")
    if mp is not None and str(ctx.get("mainprogress", "")) != str(mp):
        return False
    ag = when.get("affinity_gte")
    if ag is not None:
        who = str(when.get("who") or npc_name or "")
        try:
            if float(aff_all.get(who, 0)) < float(ag):
                return False
        except (TypeError, ValueError):
            return False
    return True


def pick_talk_line(npc, flow, map_id: str, player_pos=None, session_vars=None) -> Optional[dict]:
    cdef = getattr(npc, "char_def", None) or {}
    talk = cdef.get("talk") or {}
    ctx = build_eval_ctx(flow.save_data if flow else {}, session_vars)
    ctx["flags"] = (flow.save_data.get("flags") if flow else {}) or {}
    if not isinstance(ctx["flags"], dict):
        ctx["flags"] = {}
    aff = (flow.save_data.get("affinity") if flow else {}) or {}
    if not isinstance(aff, dict):
        aff = {}
    ctx["affinity"] = aff
    ctx["npc_name"] = str(getattr(npc, "name", "") or "")
    ctx["npc_affinity"] = aff.get(ctx["npc_name"], 0)
    ctx["map_id"] = str(map_id or "")
    if player_pos is not None:
        ctx["player_pos"] = list(player_pos)
    ctx["npc_pos"] = list(getattr(npc, "pos", [0, 0]))

    for line in talk.get("lines") or []:
        if not isinstance(line, dict):
            continue
        if eval_talk_when(line.get("when"), ctx, getattr(npc, "name", "")):
            return line
    fb = talk.get("fallback")
    return fb if isinstance(fb, dict) else None


def parse_talk_after_text(s: str) -> dict:
    """에디터 after 칸: progress_key:값; mainprogress:010100"""
    out: dict = {}
    for part in re.split(r"[;\n]+", str(s or "")):
        part = part.strip()
        if not part or part.startswith("#"):
            continue
        if ":" in part:
            k, v = part.split(":", 1)
            k, v = k.strip(), v.strip()
            if not k:
                continue
            if v.isdigit() and len(v) > 1 and v.startswith("0"):
                out[k] = v
            else:
                try:
                    out[k] = int(v) if "." not in v else float(v)
                except ValueError:
                    out[k] = v
        elif "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip()
            if k:
                try:
                    out[k] = int(v) if "." not in v else float(v)
                except ValueError:
                    out[k] = v
    return out


def format_talk_after_text(after: Any) -> str:
    if not after or not isinstance(after, dict):
        return ""
    parts = []
    for k, v in after.items():
        if k in ("set_flag", "clear_flag", "affinity_add", "add_mainprogress", "set_behavior"):
            continue
        if v is None:
            continue
        parts.append(f"{k}:{v}")
    return ";".join(parts)


def apply_talk_after(after: Any, flow, npc) -> None:
    if not after or not flow:
        return
    if isinstance(after, str):
        after = parse_talk_after_text(after)
    if not isinstance(after, dict):
        return
    save = flow.save_data
    flags = save.get("flags")
    if not isinstance(flags, dict):
        flags = {}
        save["flags"] = flags
    aff = save.get("affinity")
    if not isinstance(aff, dict):
        aff = {}
        save["affinity"] = aff
    name = getattr(npc, "name", "") or ""

    sf = after.get("set_flag")
    if isinstance(sf, str):
        flags[sf] = True
    elif isinstance(sf, dict):
        for fk, val in sf.items():
            flags[str(fk)] = val
    cf = after.get("clear_flag")
    if isinstance(cf, str):
        flags.pop(cf, None)
    elif isinstance(cf, (list, tuple)):
        for fk in cf:
            flags.pop(str(fk), None)

    if "add_mainprogress" in after:
        try:
            cur = int(str(save.get("mainprogress", "0") or "0"))
            save["mainprogress"] = str(cur + int(after["add_mainprogress"])).zfill(6)
        except (TypeError, ValueError):
            pass
    if "mainprogress" in after:
        save["mainprogress"] = str(after["mainprogress"])

    if "affinity_add" in after:
        try:
            aff[name] = int(aff.get(name, 0)) + int(after["affinity_add"])
        except (TypeError, ValueError):
            pass

    for rk, rv in after.items():
        if rk in (
            "set_flag",
            "clear_flag",
            "add_mainprogress",
            "mainprogress",
            "affinity_add",
            "set_behavior",
        ):
            continue
        if rv is None or (isinstance(rv, str) and not str(rv).strip()):
            continue
        save[str(rk)] = rv

    mode = after.get("set_behavior")
    if isinstance(mode, str) and mode:
        set_npc_behavior(npc, mode)

    flow.save_game(save.get("current_map", ""), save.get("player_pos", [0, 0]))


# ---------------------------------------------------------------------------
# [Progress 상태] spawn_state / progress_apply — char_defs·object_defs·world_data
#
# 세이브의 progress_* 를 기준으로 NPC·오브젝트의 보이기/애니/외형을 맞춥니다.
# talk.lines(when) · interact.bindings(condition) 와 같은 조건식·우선순위 규칙을 재사용합니다.
#
# 적용 시점 (호출부):
#   - flow.load_map 직후
#   - main: 이벤트 종료 후 ev_mgr._progress_refresh_pending
#   - flow.try_start_interact_event: binding 인라인(state/after, event_id 없음)
#
# JSON 필드:
#   spawn_state   — 맵 스폰 직후 초기값 (progress_apply 보다 먼저)
#   progress_apply — [{ "when": "progress_x == 1", "visible": true, ... }] 첫 매칭 규칙
#   bindings[].state / bindings[].after — 클릭 시 즉시 상태·progress (apply_talk_after 재사용)
# ---------------------------------------------------------------------------


def entity_progress_def(entity) -> dict:
    """런타임 NPC(char_def) 또는 오브젝트(obj_def) 병합 정의."""
    cdef = getattr(entity, "char_def", None)
    if isinstance(cdef, dict):
        return cdef
    odef = getattr(entity, "obj_def", None)
    if isinstance(odef, dict):
        return odef
    return {}


def pick_progress_rule(rules: list, ctx: dict) -> Optional[dict]:
    """progress_apply 에서 when/condition 첫 매칭 — pick_talk_line 과 동일 순회."""
    for row in rules or []:
        if not isinstance(row, dict):
            continue
        cond = row.get("when")
        if cond is None:
            cond = row.get("condition")
        if eval_talk_when(cond, ctx):
            return row
    return None


def _coerce_visible(val) -> bool:
    if isinstance(val, str):
        return val.strip().lower() not in ("0", "false", "f", "no", "n", "off", "")
    return bool(val)


def _entity_set_visible(entity, visible: bool) -> None:
    if hasattr(entity, "is_visible"):
        entity.is_visible = bool(visible)
    elif hasattr(entity, "visible"):
        entity.visible = bool(visible)


def _apply_char_anim(entity, patch: dict) -> None:
    """ACTION_ANIM hold/once 와 동일 규칙으로 play_anim 호출."""
    anim = (patch.get("anim") or patch.get("state") or "").strip()
    if not anim:
        return
    pa = getattr(entity, "play_anim", None)
    if not callable(pa):
        if hasattr(entity, "state"):
            entity.state = anim.lower()
        return
    mode = str(patch.get("anim_mode") or patch.get("mode") or "hold").strip().lower()
    release = str(patch.get("anim_release") or patch.get("release") or "idle").strip().lower()
    if mode == "once":
        try:
            dur_s = float(patch.get("anim_duration") or patch.get("duration") or 1.0)
        except (TypeError, ValueError):
            dur_s = 1.0
        duration_ms = int(max(0.05, dur_s) * 1000.0)
        loop = bool(patch.get("anim_loop", False))
        pa(anim, duration_ms=duration_ms, loop=loop, release=release)
    else:
        pa(anim, duration_ms=0, loop=True, release=release)
    ua = getattr(entity, "update_anim", None)
    if callable(ua):
        ua()


def apply_char_type_retarget(entity, new_key: str) -> bool:
    """CHANGE / change_to 후 char_defs·interact·가시성 동기화."""
    key = str(new_key or "").strip()
    if not key or key not in CHAR_ASSETS:
        return False
    entry = getattr(entity, "_world_entry", None) or {}
    was_visible = bool(getattr(entity, "is_visible", True))
    entity.char_def = build_npc_def(key, entry)
    attach_interact_spec(entity, CHAR_ASSETS.get(key, {}), entry)
    if was_visible:
        entity.is_visible = True
    reset_entity_motion_on_change(entity)
    return True


def apply_object_type_retarget(entity, new_key: str) -> bool:
    """CHANGE / change_to 후 object_defs 동기화."""
    from data import OBJ_ASSETS
    from flow import build_obj_def

    key = str(new_key or "").strip()
    if not key or key not in OBJ_ASSETS:
        return False
    info = OBJ_ASSETS.get(key, {}) or {}
    entry = getattr(entity, "_world_entry", None) or {}
    was_visible = bool(getattr(entity, "is_visible", True))
    entity.obj_def = build_obj_def(key, entry)
    attach_interact_spec(entity, info, entry)
    if was_visible:
        entity.is_visible = True
    reset_entity_motion_on_change(entity)
    return True


def reset_entity_motion_on_change(entity) -> None:
    """change_to / CHANGE 직후 이동 경로·AI·표시 상태를 idle 로 정리."""
    sm = getattr(entity, "stop_moving", None)
    if callable(sm):
        try:
            sm(preserve_anim_override=True)
        except TypeError:
            try:
                sm()
            except Exception:
                pass
        except Exception:
            pass
    else:
        if hasattr(entity, "path"):
            entity.path = []
        if hasattr(entity, "pos") and hasattr(entity, "target"):
            try:
                entity.target = list(entity.pos)
            except Exception:
                pass

    if hasattr(entity, "event_waypoints"):
        entity.event_waypoints = None

    if hasattr(entity, "state"):
        entity.state = "idle"

    if hasattr(entity, "behavior_spec"):
        ndef = entity_progress_def(entity)
        spec = dict(ndef.get("behavior") or getattr(entity, "behavior_spec", None) or {})
        spec["mode"] = "idle"
        entity.behavior_spec = spec

    if hasattr(entity, "_bh_state"):
        entity._bh_state = {
            "patrol_idx": 0,
            "wait_until_ms": 0,
            "wander_next_ms": 0,
            "wander_target": None,
        }

    frames = getattr(entity, "frames", None)
    if frames:
        entity.frame_idx = 0
        try:
            entity.image = frames[0]
        except Exception:
            pass


def apply_state_patch(entity, patch: dict) -> bool:
    """
    단일 상태 패치 — TUNE/ACTION_ANIM/CHANGE 스텝과 같은 의미의 필드.
    visible, spawn, dir, anim, change_to, behavior_mode 지원.
    반환 True: spawn:false 로 맵 목록에서 제거해야 함.
    """
    if not patch or not isinstance(patch, dict):
        return False

    remove = False
    if "spawn" in patch and not _coerce_visible(patch.get("spawn")):
        remove = True
        setattr(entity, "_progress_spawn_removed", True)

    if "visible" in patch:
        _entity_set_visible(entity, _coerce_visible(patch.get("visible")))

    change_to = patch.get("change_to") or patch.get("to")
    if change_to:
        key = str(change_to).strip()
        rt_char = getattr(entity, "retarget_char_def", None)
        rt_obj = getattr(entity, "retarget_object_def", None)
        changed = False
        if callable(rt_char) and rt_char(key):
            changed = True
        elif callable(rt_obj) and rt_obj(key):
            changed = True

    d = (patch.get("dir") or patch.get("face") or "").strip().lower()
    if d in ("left", "l"):
        entity.direction = "left"
    elif d in ("right", "r"):
        entity.direction = "right"

    bm = patch.get("behavior_mode") or patch.get("behavior")
    if isinstance(bm, str) and bm.strip():
        set_npc_behavior(entity, bm.strip())

    if patch.get("anim") or patch.get("state"):
        _apply_char_anim(entity, patch)

    if "playing_baseball" in patch:
        entity.playing_baseball = _coerce_visible(patch.get("playing_baseball"))
        if not entity.playing_baseball:
            clr = getattr(entity, "clear_sprite_overlay", None)
            if callable(clr):
                try:
                    clr()
                except Exception:
                    pass

    return remove


def _resolve_entity_fx_patch(ndef: dict, spawn: dict | None, rule: dict | None):
    """progress 규칙 entity_fx > (규칙 있으면) 타입 기본 > spawn_state > 타입 기본."""
    if isinstance(rule, dict):
        if "entity_fx" in rule:
            return rule.get("entity_fx"), True
        st = rule.get("state")
        if isinstance(st, dict) and "entity_fx" in st:
            return st.get("entity_fx"), True
        if isinstance(ndef, dict) and "entity_fx" in ndef:
            return ndef.get("entity_fx"), True
        return None, True
    if isinstance(spawn, dict) and "entity_fx" in spawn:
        return spawn.get("entity_fx"), True
    if isinstance(ndef, dict) and "entity_fx" in ndef:
        return ndef.get("entity_fx"), True
    return None, False


def apply_entity_fx_from_def(entity, ndef: dict, *, spawn=None, rule=None) -> None:
    from engine import apply_entity_visual_patch, clear_entity_fx

    fx, explicit = _resolve_entity_fx_patch(ndef or {}, spawn, rule)
    if not explicit:
        # progress 규칙에 FX가 없을 때 tint만 끔 — 이벤트 ZOOM persist 등 entity_def_zoom 은 유지
        clear_entity_fx(entity)
        return
    if fx is None:
        clear_entity_fx(entity)
    else:
        apply_entity_visual_patch(entity, fx)


def apply_entity_progress_state(entity, save_data: dict, *, session_vars=None) -> bool:
    """spawn_state → progress_apply 순 적용. spawn:false 면 True."""
    ndef = entity_progress_def(entity)
    ctx = build_eval_ctx(save_data or {}, session_vars)

    spawn = ndef.get("spawn_state")
    if isinstance(spawn, dict) and spawn:
        if apply_state_patch(entity, spawn):
            return True

    rule = pick_progress_rule(ndef.get("progress_apply") or [], ctx)
    if isinstance(rule, dict):
        state = rule.get("state")
        if isinstance(state, dict):
            if apply_state_patch(entity, state):
                return True
        else:
            row = {
                k: v
                for k, v in rule.items()
                if k not in ("when", "condition", "after", "entity_fx")
            }
            if apply_state_patch(entity, row):
                return True
    apply_entity_fx_from_def(entity, ndef, spawn=spawn if isinstance(spawn, dict) else None, rule=rule)
    return bool(getattr(entity, "_progress_spawn_removed", False))


def apply_map_progress_states(objs, npcs, save_data: dict, *, session_vars=None):
    """맵 전체 NPC·오브젝트 progress 상태 일괄 적용 (load_map·이벤트 종료 후)."""
    kept_objs = []
    for o in objs or []:
        if apply_entity_progress_state(o, save_data, session_vars=session_vars):
            continue
        if getattr(o, "_progress_spawn_removed", False):
            continue
        kept_objs.append(o)

    kept_npcs = []
    for n in npcs or []:
        if apply_entity_progress_state(n, save_data, session_vars=session_vars):
            continue
        if getattr(n, "_progress_spawn_removed", False):
            continue
        kept_npcs.append(n)

    return kept_objs, kept_npcs


def _say_step_from_line(line: dict, npc) -> dict:
    say = dict(line.get("say") or {})
    if not say.get("who"):
        say["who"] = getattr(npc, "name", "") or ""
    if say.get("show_name") is None:
        say["show_name"] = True
    return say


def start_npc_talk(npc, player, flow, ev_mgr, map_id: str, *, session_vars=None) -> bool:
    if ev_mgr and (ev_mgr.active_event or ev_mgr.is_talking):
        return False
    line = pick_talk_line(npc, flow, map_id, player.pos, session_vars=session_vars)
    if not line:
        return False
    say = _say_step_from_line(line, npc)
    after = line.get("after")
    face_toward_player(npc, player)
    npc._in_npc_talk = True
    try:
        player.stop_moving()
    except Exception:
        pass
    try:
        npc.stop_moving()
    except Exception:
        pass

    def _on_done():
        npc._in_npc_talk = False
        apply_talk_after(after, flow, npc)

    ev_mgr.start_free_say(say, on_finish=_on_done)
    return True


def _behavior_mode(npc) -> str:
    if getattr(npc, "_in_npc_talk", False):
        return "frozen"
    spec = getattr(npc, "behavior_spec", None) or {}
    return normalize_behavior_mode(spec.get("mode") or "idle")


def _tick_patrol(npc, mask, objs, npcs, now_ms: int):
    spec = npc.behavior_spec or {}
    wps = spec.get("waypoints") or []
    if not wps:
        return
    st = npc._bh_state
    if now_ms < int(st.get("wait_until_ms") or 0):
        return
    if getattr(npc, "path", None):
        return
    try:
        if math.hypot(float(npc.target[0]) - float(npc.pos[0]), float(npc.target[1]) - float(npc.pos[1])) > 6:
            return
    except Exception:
        pass

    idx = int(st.get("patrol_idx") or 0) % len(wps)
    wp = wps[idx]
    try:
        tx, ty = float(wp[0]), float(wp[1])
    except (TypeError, ValueError, IndexError):
        return
    setter = getattr(npc, "set_new_target", None)
    if callable(setter) and mask is not None:
        setter(tx, ty, mask, objs, npcs)
    else:
        npc.target = [tx, ty]
        npc.path = [(tx, ty)]
        npc.state = "walk"
    wait_ms = int(spec.get("wait_ms", 800) or 800)
    st["wait_until_ms"] = now_ms + wait_ms
    st["patrol_idx"] = (idx + 1) % len(wps)


def _is_mask_walk(mask, x, y) -> bool:
    if mask is None:
        return True
    try:
        from engine import mask_terrain_class

        return mask_terrain_class(mask, float(x), float(y)) == "walk"
    except Exception:
        return True


def _point_walkable(npc, mask, objs, npcs, x, y) -> bool:
    """마스크(+가능하면 충돌 probe) 기준 서 있을 수 있는 점."""
    if mask is None:
        return True
    if not _is_mask_walk(mask, x, y):
        return False
    probe = getattr(npc, "check_walkable", None)
    if callable(probe):
        try:
            ok, _ = probe(float(x), float(y), mask, objs or [], npcs or [])
            return bool(ok)
        except Exception:
            return True
    return True


def _snap_walk_point(mask, x, y, max_r=48):
    if mask is None:
        return float(x), float(y)
    try:
        from engine import _snap_to_nearest_walk
        from data import CONFIG

        sn = _snap_to_nearest_walk(
            mask,
            float(x),
            float(y),
            max_r=int(CONFIG.get("TARGET_SNAP_MAX_R_PX", max_r) or max_r),
            step=int(CONFIG.get("TARGET_SNAP_STEP_PX", 2) or 2),
        )
        if sn is not None:
            return float(sn[0]), float(sn[1])
    except Exception:
        pass
    return None


def _pick_roam_walk_point(npc, mask, objs, npcs, hx, hy, radius, tries=14):
    """원점 반경 안에서 이동가능(마스크) 점 선택. 실패 시 None."""
    import random

    r = max(0.0, float(radius or 0))
    if r <= 0.5:
        if _point_walkable(npc, mask, objs, npcs, hx, hy):
            return float(hx), float(hy)
        return _snap_walk_point(mask, hx, hy)

    for _ in range(max(1, int(tries))):
        ang = random.random() * math.pi * 2
        dist = r * (0.25 + 0.75 * random.random())
        tx = float(hx) + math.cos(ang) * dist
        ty = float(hy) + math.sin(ang) * dist
        if _point_walkable(npc, mask, objs, npcs, tx, ty):
            return tx, ty
        sn = _snap_walk_point(mask, tx, ty, max_r=min(40, max(12, int(r * 0.35))))
        if sn is not None and _point_walkable(npc, mask, objs, npcs, sn[0], sn[1]):
            return sn

    # 최후: 홈 스냅
    if _point_walkable(npc, mask, objs, npcs, hx, hy):
        return float(hx), float(hy)
    return _snap_walk_point(mask, hx, hy)


def _pick_jump_land(npc, mask, objs, npcs, sx, sy, face, tries=8):
    """randomplay 점프 착지 — 마스크 walk 만."""
    import random

    for _ in range(max(1, int(tries))):
        dist = random.uniform(10.0, 28.0)
        tx = float(sx) + float(face) * dist
        ty = float(sy) + random.uniform(-8.0, 8.0)
        if _point_walkable(npc, mask, objs, npcs, tx, ty):
            return tx, ty
        sn = _snap_walk_point(mask, tx, ty, max_r=24)
        if sn is not None and _point_walkable(npc, mask, objs, npcs, sn[0], sn[1]):
            # 너무 가까운 스냅은 점프 의미 없음
            if math.hypot(sn[0] - float(sx), sn[1] - float(sy)) >= 6.0:
                return sn
    return None


def _set_roam_move_target(npc, tx, ty, mask, objs, npcs, move_mode="walk"):
    """
    roam 이동 목표. 경로 계획은 항상 walk(A*/마스크)로 잡고,
    run 이면 속도·애니만 달리기.
    """
    plan_mode = "walk"
    try:
        npc._move_mode = plan_mode
    except Exception:
        pass
    setter = getattr(npc, "set_new_target", None)
    if callable(setter) and mask is not None:
        setter(tx, ty, mask, objs, npcs)
    else:
        npc.target = [tx, ty]
        npc.path = [(tx, ty)]
        npc.state = "walk"
        return
    if str(move_mode or "walk") != "run":
        return
    try:
        npc._move_mode = "run"
    except Exception:
        pass
    try:
        npc.event_speed_mul = float(CONFIG.get("RUN_SPEED_MUL", 1.8))
        npc._click_run_restore = True
    except Exception:
        pass
    try:
        if getattr(npc, "path", None):
            npc.state = "run"
    except Exception:
        pass


def _tick_wander(npc, mask, objs, npcs, now_ms: int):
    """randomwalk — 배치 원점(_bh_home) 반경·이동가능 마스크 안을 걸어다님."""
    spec = npc.behavior_spec or {}
    st = npc._bh_state
    if now_ms < int(st.get("wander_next_ms") or 0):
        return
    if getattr(npc, "path", None):
        return
    radius = float(spec.get("radius", 64) or 64)
    hx, hy = _roam_home(npc)
    pt = _pick_roam_walk_point(npc, mask, objs, npcs, hx, hy, radius)
    if pt is None:
        interval = int(spec.get("interval_ms", 3000) or 3000)
        st["wander_next_ms"] = now_ms + interval
        return
    tx, ty = pt
    _set_roam_move_target(npc, tx, ty, mask, objs, npcs, move_mode="walk")
    interval = int(spec.get("interval_ms", 3000) or 3000)
    st["wander_next_ms"] = now_ms + interval


def _tick_randomplay(npc, mask, objs, npcs, now_ms: int):
    """
    randomplay — 이동가능 마스크(원점 반경)에서 서기/걷기/뛰기/점프를 랜덤으로.
    아이들 자유롭게 노는 ambient AI.
    """
    import random

    spec = npc.behavior_spec or {}
    st = npc._bh_state
    if now_ms < int(st.get("play_next_ms") or 0):
        return
    if getattr(npc, "path", None):
        return
    if getattr(npc, "_jump_arc", None) is not None:
        return
    if getattr(npc, "_anim_override", None) is not None:
        return

    radius = float(spec.get("radius", 80) or 80)
    action = random.choices(
        ("stand", "walk", "run", "jump"),
        weights=(0.28, 0.34, 0.24, 0.14),
        k=1,
    )[0]

    if action == "stand":
        sm = getattr(npc, "stop_moving", None)
        if callable(sm):
            try:
                sm()
            except Exception:
                pass
        try:
            npc.direction = random.choice(("left", "right"))
            npc.state = "idle"
        except Exception:
            pass
        st["play_next_ms"] = now_ms + random.randint(700, 2400)
        return

    if action == "jump":
        sm = getattr(npc, "stop_moving", None)
        if callable(sm):
            try:
                sm()
            except Exception:
                pass
        try:
            npc.direction = random.choice(("left", "right"))
        except Exception:
            pass

        hop_h = float(random.randint(24, 42))
        dur = int(random.randint(300, 520))
        # MaskWalkingCharacter: 실제 _jump_arc 포물선(발 그림자·공중 높이)
        if hasattr(npc, "_jump_arc"):
            try:
                x = float(npc.pos[0])
                y = float(npc.pos[1])
            except (TypeError, ValueError):
                x = y = 0.0
            face = -1.0 if str(getattr(npc, "direction", "left") or "left") == "left" else 1.0
            land = _pick_jump_land(npc, mask, objs, npcs, x, y, face)
            if land is None:
                # 착지 불가면 점프 대신 짧게 서기
                try:
                    npc.state = "idle"
                except Exception:
                    pass
                st["play_next_ms"] = now_ms + random.randint(400, 900)
                return
            tx, ty = land
            npc._jump_arc = {
                "t0": now_ms,
                "dur": dur,
                "sx": x,
                "sy": y,
                "ex": tx,
                "ey": ty,
                "arc_h": hop_h,
            }
            try:
                npc._jump_draw_lift = 0.0
            except Exception:
                pass
            npc.path = [(tx, ty, 1)]
            npc.target = [tx, ty]
            try:
                npc.state = "jump"
                npc.frame_idx = 0
            except Exception:
                pass
        else:
            # BaseCharacter 등: ACTION_ANIM jump 와 동일하게 height 로 띄움
            pa = getattr(npc, "play_anim", None)
            if callable(pa):
                try:
                    pa(
                        "jump",
                        duration_ms=dur,
                        loop=False,
                        release="idle",
                        temp_height=hop_h,
                    )
                except Exception:
                    pass
        st["play_next_ms"] = now_ms + dur + random.randint(120, 450)
        return

    move_mode = "run" if action == "run" else "walk"
    hx, hy = _roam_home(npc)
    pt = _pick_roam_walk_point(npc, mask, objs, npcs, hx, hy, radius)
    if pt is None:
        st["play_next_ms"] = now_ms + random.randint(500, 1200)
        return
    tx, ty = pt
    _set_roam_move_target(npc, tx, ty, mask, objs, npcs, move_mode=move_mode)
    interval = int(spec.get("interval_ms", 2200) or 2200)
    st["play_next_ms"] = now_ms + random.randint(max(500, interval // 2), interval + 900)


def _tick_follow(npc, player, mask, objs, npcs, now_ms: int):
    spec = npc.behavior_spec or {}
    trigger = float(spec.get("trigger_range", 120) or 120)
    stop_d = float(spec.get("stop_dist", 36) or 36)
    dist = math.hypot(float(player.pos[0]) - float(npc.pos[0]), float(player.pos[1]) - float(npc.pos[1]))
    if dist > trigger or dist <= stop_d:
        return
    if getattr(npc, "path", None):
        return
    dx = float(player.pos[0]) - float(npc.pos[0])
    dy = float(player.pos[1]) - float(npc.pos[1])
    ln = math.hypot(dx, dy) or 1.0
    tx = float(npc.pos[0]) + dx / ln * max(0, dist - stop_d)
    ty = float(npc.pos[1]) + dy / ln * max(0, dist - stop_d)
    setter = getattr(npc, "set_new_target", None)
    if callable(setter) and mask is not None:
        setter(tx, ty, mask, objs, npcs)


def _tick_flee(npc, player, mask, objs, npcs, now_ms: int):
    spec = npc.behavior_spec or {}
    trigger = float(spec.get("trigger_range", 80) or 80)
    safe = float(spec.get("safe_range", 140) or 140)
    dist = math.hypot(float(player.pos[0]) - float(npc.pos[0]), float(player.pos[1]) - float(npc.pos[1]))
    if dist > trigger:
        return
    if getattr(npc, "path", None):
        return
    dx = float(npc.pos[0]) - float(player.pos[0])
    dy = float(npc.pos[1]) - float(player.pos[1])
    ln = math.hypot(dx, dy) or 1.0
    tx = float(npc.pos[0]) + dx / ln * safe
    ty = float(npc.pos[1]) + dy / ln * safe
    setter = getattr(npc, "set_new_target", None)
    if callable(setter) and mask is not None:
        setter(tx, ty, mask, objs, npcs)


def tick_npc_behaviors(npcs, player, mask, objs, ev_mgr, map_id: str = ""):
    """
    ambient AI 틱.
    이벤트 중에도 randomwalk/randomplay 등은 계속 동작하되,
    MOVE/ACTION_ANIM 등으로 hold 된 NPC는 건너뛴다. 이벤트 종료 시 hold 해제.
    """
    event_active = bool(ev_mgr and getattr(ev_mgr, "active_event", None))
    try:
        import pygame

        now_ms = int(pygame.time.get_ticks())
    except Exception:
        now_ms = 0

    for npc in npcs or []:
        if not getattr(npc, "behavior_spec", None):
            continue
        if getattr(npc, "_in_npc_talk", False):
            continue
        if not event_active and getattr(npc, "_bh_event_hold", False):
            npc._bh_event_hold = False
        if getattr(npc, "_bh_event_hold", False):
            continue
        mode = _behavior_mode(npc)
        if mode == "frozen" or mode == "idle":
            continue
        # 이벤트 중에는 randomwalk/randomplay 만 ambient로 유지 (follow/flee/patrol은 컷신과 충돌)
        if event_active and mode not in ("wander", "randomplay"):
            continue
        if mode == "patrol":
            _tick_patrol(npc, mask, objs, npcs, now_ms)
        elif mode == "wander":
            _tick_wander(npc, mask, objs, npcs, now_ms)
        elif mode == "randomplay":
            _tick_randomplay(npc, mask, objs, npcs, now_ms)
        elif mode == "follow":
            _tick_follow(npc, player, mask, objs, npcs, now_ms)
        elif mode == "flee":
            _tick_flee(npc, player, mask, objs, npcs, now_ms)


def npc_entry_from_instance(npc) -> dict:
    """에디터 저장용 world_data npc dict."""
    d = {
        "name": npc.name,
        "pos": [int(npc.pos[0]), int(npc.pos[1])],
        "sprite_tilt": round(float(getattr(npc, "sprite_tilt", 1.0)), 4),
        "height": int(round(float(getattr(npc, "height", 0) or 0))),
        "ysort": str(getattr(npc, "ysort_mode", "ground") or "ground"),
        "layer": int(getattr(npc, "layer", 0) or 0),
    }
    iid = getattr(npc, "instance_id", None)
    if iid:
        d["instance_id"] = iid
    spec = getattr(npc, "behavior_spec", None) or {}
    wps = spec.get("waypoints")
    mode = display_behavior_mode(spec.get("mode") or "idle")
    if mode and mode != "idle":
        beh: dict = {"mode": mode}
        if wps:
            beh["waypoints"] = [[int(p[0]), int(p[1])] for p in wps]
        if mode in ("randomwalk", "randomplay", "wander"):
            if spec.get("radius") is not None:
                try:
                    beh["radius"] = float(spec.get("radius"))
                except (TypeError, ValueError):
                    pass
            if spec.get("interval_ms") is not None:
                try:
                    beh["interval_ms"] = int(spec.get("interval_ms"))
                except (TypeError, ValueError):
                    pass
        if mode == "patrol" and spec.get("wait_ms") is not None:
            try:
                beh["wait_ms"] = int(spec.get("wait_ms"))
            except (TypeError, ValueError):
                pass
        if mode == "follow":
            for k_src, k_dst in (("trigger_range", "trigger_range"), ("stop_dist", "stop_dist")):
                if spec.get(k_src) is not None:
                    try:
                        beh[k_dst] = float(spec.get(k_src))
                    except (TypeError, ValueError):
                        pass
        if mode == "flee":
            for k_src in ("trigger_range", "safe_range"):
                if spec.get(k_src) is not None:
                    try:
                        beh[k_src] = float(spec.get(k_src))
                    except (TypeError, ValueError):
                        pass
        d["behavior"] = beh
    elif wps:
        d["waypoints"] = [[int(p[0]), int(p[1])] for p in wps]
    inst = getattr(npc, "interact_instance", None)
    if isinstance(inst, dict) and inst:
        d["interact"] = inst
    we = getattr(npc, "_world_entry", None) or {}
    if isinstance(we.get("spawn_state"), dict) and we["spawn_state"]:
        d["spawn_state"] = dict(we["spawn_state"])
    if isinstance(we.get("progress_apply"), list) and we["progress_apply"]:
        d["progress_apply"] = list(we["progress_apply"])
    return d

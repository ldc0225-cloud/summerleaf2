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
    npc._bh_state = {
        "patrol_idx": 0,
        "wait_until_ms": 0,
        "wander_next_ms": 0,
        "wander_target": None,
    }
    wps = entry.get("waypoints")
    if wps:
        npc.behavior_spec.setdefault("waypoints", list(wps))
    if entry.get("mode"):
        npc.behavior_spec["mode"] = entry["mode"]
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
        npc.behavior_spec = dict(getattr(npc, "behavior_spec", {}) or {})
        npc.behavior_spec["mode"] = mode

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
        spec = getattr(entity, "behavior_spec", None)
        if isinstance(spec, dict):
            spec["mode"] = bm.strip().lower()
        elif hasattr(entity, "behavior_spec"):
            entity.behavior_spec = {"mode": bm.strip().lower()}

    if patch.get("anim") or patch.get("state"):
        _apply_char_anim(entity, patch)

    return remove


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
            row = {k: v for k, v in rule.items() if k not in ("when", "condition", "after")}
            if apply_state_patch(entity, row):
                return True
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
    return str(spec.get("mode") or "idle").strip().lower()


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


def _tick_wander(npc, mask, objs, npcs, now_ms: int):
    spec = npc.behavior_spec or {}
    st = npc._bh_state
    if now_ms < int(st.get("wander_next_ms") or 0):
        return
    if getattr(npc, "path", None):
        return
    radius = float(spec.get("radius", 64) or 64)
    import random

    ang = random.random() * math.pi * 2
    tx = float(npc.pos[0]) + math.cos(ang) * radius
    ty = float(npc.pos[1]) + math.sin(ang) * radius
    setter = getattr(npc, "set_new_target", None)
    if callable(setter) and mask is not None:
        setter(tx, ty, mask, objs, npcs)
    else:
        npc.target = [tx, ty]
        npc.path = [(tx, ty)]
        npc.state = "walk"
    interval = int(spec.get("interval_ms", 3000) or 3000)
    st["wander_next_ms"] = now_ms + interval


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
    if ev_mgr and ev_mgr.active_event:
        return
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
        mode = _behavior_mode(npc)
        if mode == "frozen" or mode == "idle":
            continue
        if mode == "patrol":
            _tick_patrol(npc, mask, objs, npcs, now_ms)
        elif mode == "wander":
            _tick_wander(npc, mask, objs, npcs, now_ms)
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
    mode = spec.get("mode")
    if mode and mode != "idle":
        d["behavior"] = {"mode": mode}
        if wps:
            d["behavior"]["waypoints"] = [[int(p[0]), int(p[1])] for p in wps]
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

"""NPC 타입 정의(char_defs) + 맵 인스턴스 + interact(bindings) / talk(progress 대사)."""
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
    return d

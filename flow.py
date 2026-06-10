import json, os, pygame, math
import re
from data import CONFIG, CHAR_ASSETS, OBJ_ASSETS

def merge_event_catalog(event_data):
    """
    events.json 실행 카탈로그(LOCAL / GLOBAL / SYNC)를 event_id -> 항목 dict로 합칩니다.
    FRAGMENTS 는 CALL_EVENT 로도 호출 가능하나, 여기서는 직접 실행 카탈로그만 합칩니다.
    동일 ID 충돌 시 뒤 섹션이 덮어씁니다: LOCAL < GLOBAL < SYNC.
    """
    merged = {}
    for section in ("LOCAL", "GLOBAL", "SYNC"):
        for eid, entry in (event_data.get(section) or {}).items():
            tagged = dict(entry)
            tagged["_event_category"] = section
            merged[eid] = tagged
    return merged


def merge_call_event_catalog(event_data):
    """
    CALL_EVENT 스텝 target 목록 — LOCAL / GLOBAL / SYNC / FRAGMENTS 전체.
    id -> {steps, result?, ...} (동일 ID 는 FRAGMENTS < SYNC < GLOBAL < LOCAL 순 덮어씀).
    """
    out = {}
    for section in ("FRAGMENTS", "SYNC", "GLOBAL", "LOCAL"):
        for eid, entry in (event_data.get(section) or {}).items():
            row = dict(entry or {})
            row["_call_event_section"] = section
            out[str(eid)] = row
    return out


def merge_fragment_catalog(event_data):
    """merge_call_event_catalog 별칭 (기존 main·engine 호출 호환)."""
    return merge_call_event_catalog(event_data)


def build_eval_ctx(save_data: dict, session_vars=None) -> dict:
    """조건식 evaluate_global_condition용 컨텍스트. save + 세션(gamestart 등)."""
    ctx = dict(save_data or {})
    if session_vars:
        ctx.update(session_vars)
    return ctx


def pick_sync_events(
    event_data: dict,
    save_data: dict,
    map_id: str,
    events_catalog: dict,
    session_vars=None,
):
    """
    맵 진입/로드 직후 실행할 SYNC 이벤트 ID 목록 (priority 오름차순, 같으면 id).
    work_map 이 있으면 현재 map_id 와 일치할 때만 후보.
    """
    ctx = build_eval_ctx(save_data, session_vars)
    sync_sec = event_data.get("SYNC") or {}
    candidates = []
    for eid, ev in sync_sec.items():
        if eid not in events_catalog:
            continue
        wm = str(ev.get("work_map") or "").strip()
        if wm and wm != str(map_id):
            continue
        cond = ev.get("condition")
        if not evaluate_global_condition(cond, ctx):
            continue
        pr = ev.get("priority", 100)
        try:
            pr = int(pr)
        except (TypeError, ValueError):
            pr = 100
        candidates.append((pr, eid))
    candidates.sort(key=lambda x: (x[0], x[1]))
    return [eid for _, eid in candidates]


def _parse_condition_rhs(raw: str, save_data: dict):
    """조건식 우변: 따옴표 문자열, 숫자(앞자리 0 진행도코드는 문자열로 유지)."""
    s = raw.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if s.isdigit() and len(s) > 1 and s.startswith("0"):
        return s
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def normalize_condition_expr(condition_expr) -> str:
    """
    조건 문자열 정리. 에디터/JSON 에서 흔한 오타 보정.
    예: "progress_x"==1001 → progress_x == 1001
    """
    s = str(condition_expr or "").strip()
    if not s:
        return ""
    s = re.sub(
        r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']\s*(==|!=|>=|<=|>|<)\s*',
        r"\1 \2 ",
        s,
    )
    return s.strip()


def evaluate_global_condition(condition_expr, eval_ctx: dict) -> bool:
    """
    eval_ctx 기준 조건식. 예: mainprogress == "010100"
    gamestart 는 세이브가 아니라 main에서 넘기는 세션 변수(session_vars)로만 쓰는 것을 권장.
    비어 있으면 True.
    """
    if condition_expr is None:
        return True
    s = normalize_condition_expr(condition_expr)
    if not s:
        return True
    m = re.match(
        r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(.+)\s*$",
        s,
    )
    if not m:
        return False
    key, op, rhs_raw = m.group(1), m.group(2), m.group(3).strip()
    lhs = eval_ctx.get(key)
    if lhs is None and str(key).startswith("progress_"):
        lhs = 0
    rhs = _parse_condition_rhs(rhs_raw, eval_ctx)

    try:
        if op == "==":
            return lhs == rhs
        if op == "!=":
            return lhs != rhs
        if op == ">=":
            return float(lhs) >= float(rhs)
        if op == "<=":
            return float(lhs) <= float(rhs)
        if op == ">":
            return float(lhs) > float(rhs)
        if op == "<":
            return float(lhs) < float(rhs)
    except (TypeError, ValueError):
        return False
    return False


def evaluate_event_step_condition(step: dict, eval_ctx: dict) -> bool:
    """
    이벤트 스텝 CONDITION 용.
    - condition(또는 expr): 전체 식 — progress_wateringcan == 1002
    - var + op: 축약 — var=progress_wateringcan, op=>=100 또는 ==1002
    둘 다 비어 있으면 True(통과).
    """
    if not isinstance(step, dict):
        return True
    full = str(step.get("condition") or step.get("expr") or "").strip()
    var = str(step.get("var") or "").strip()
    op_part = str(step.get("op") or "").strip()
    if full:
        return evaluate_global_condition(full, eval_ctx)
    if var and op_part:
        if re.match(r"^(==|!=|>=|<=|>|<)", op_part):
            return evaluate_global_condition(f"{var} {op_part}", eval_ctx)
    return True


def is_global_auto_trigger(entry: dict) -> bool:
    t = (entry.get("trigger") or "").strip().lower()
    if t in ("hotkey", "manual", "code", "none"):
        return False
    if not t:
        return True  # GLOBAL: 트리거 생략 시 메인 루프 자동 스캔 대상
    return t in ("auto", "global", "intercept")


def pick_global_auto_event(event_data: dict, save_data: dict, events_catalog: dict, session_vars=None):
    """
    GLOBAL 섹션에서 조건 만족·catalog에 있는 이벤트 하나 선택.
    session_vars: 세션 전용 값(예: {"gamestart": boot_phase}) — 세이브에 쓰이지 않음.
    priority 오름차순(작을수록 먼저), 그다음 event_id.
    """
    ctx = dict(save_data)
    if session_vars:
        ctx.update(session_vars)
    global_sec = event_data.get("GLOBAL", {})
    candidates = []
    for eid, ev in global_sec.items():
        if not is_global_auto_trigger(ev):
            continue
        if eid not in events_catalog:
            continue
        cond = ev.get("condition")
        if not evaluate_global_condition(cond, ctx):
            continue
        pr = ev.get("priority", 100)
        try:
            pr = int(pr)
        except (TypeError, ValueError):
            pr = 100
        candidates.append((pr, eid))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: (x[0], x[1]))
    eid = candidates[0][1]
    return eid, global_sec[eid]


def merge_interact_spec(type_asset: dict, world_entry: dict = None) -> dict:
    """
    object_defs / char_defs 의 interact 와 world_data 인스턴스 interact 를 병합합니다.
    인스턴스에 bindings 가 있으면 타입 목록을 통째로 덮어씁니다(char_behavior._deep_merge 규칙).
    """
    import copy

    from char_behavior import _deep_merge

    base = dict((type_asset or {}).get("interact") or {})
    entry = world_entry if isinstance(world_entry, dict) else {}
    inst = entry.get("interact")
    if isinstance(inst, dict) and inst:
        return _deep_merge(base, inst)
    return copy.deepcopy(base)


def parse_interact_bindings_text(text: str) -> list:
    """
    에디터 한 줄 형식: condition | event_id | priority(선택)
    condition 비우면 항상 참. 여러 줄 / 세미콜론 구분.
    """
    out = []
    if not text:
        return out
    blob = str(text).replace(";", "\n")
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        eid = parts[1].strip()
        if not eid:
            continue
        row = {"condition": parts[0].strip(), "event_id": eid}
        if len(parts) >= 3 and str(parts[2]).strip() != "":
            try:
                row["priority"] = int(parts[2].strip())
            except (TypeError, ValueError):
                row["priority"] = 100
        out.append(row)
    return out


def format_interact_bindings_text(bindings) -> str:
    lines = []
    for b in bindings or []:
        if not isinstance(b, dict):
            continue
        eid = str(b.get("event_id") or "").strip()
        if not eid:
            continue
        cond = str(b.get("condition") or "").strip()
        try:
            pr = int(b.get("priority", 100))
        except (TypeError, ValueError):
            pr = 100
        lines.append(f"{cond} | {eid} | {pr}")
    return "\n".join(lines)


def pick_interact_event(bindings, eval_ctx: dict, events_catalog: dict):
    """
    상호작용 시 progress 등 조건에 맞는 events.json 이벤트 1개 선택.
    pick_sync_events / pick_global_auto_event 와 동일: priority 오름차순, 같으면 event_id.
    """
    candidates = []
    for b in bindings or []:
        if not isinstance(b, dict):
            continue
        eid = str(b.get("event_id") or "").strip()
        if not eid or eid not in events_catalog:
            continue
        if not evaluate_global_condition(b.get("condition"), eval_ctx):
            continue
        try:
            pr = int(b.get("priority", 100))
        except (TypeError, ValueError):
            pr = 100
        candidates.append((pr, eid))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][1]


def entity_interact_spec(entity) -> dict:
    """런타임 엔티티(FieldItem / NPC)에서 병합된 interact dict."""
    if entity is None:
        return {}
    spec = getattr(entity, "interact_spec", None)
    if isinstance(spec, dict):
        return spec
    cdef = getattr(entity, "char_def", None)
    if isinstance(cdef, dict):
        return dict(cdef.get("interact") or {})
    return {}


def interact_spec_enabled(spec) -> bool:
    """
    interact.enabled 기본값은 False.
    JSON/에디터에서 enabled: true 를 명시한 경우에만 클릭·이벤트 상호작용 후보.
    """
    if not isinstance(spec, dict):
        return False
    return spec.get("enabled") is True


def entity_interact_enabled(entity) -> bool:
    """enabled 가 명시적 true 이고 bindings 가 있으면 클릭→events.json 상호작용 후보."""
    spec = entity_interact_spec(entity)
    if not interact_spec_enabled(spec):
        return False
    return bool(spec.get("bindings"))


# ---------------------------------------------------------------------------
# FLOW 에디터: progress 변수별 정적 흐름 (mainprogress·progress_* 동일 조건식)
# - 런타임: evaluate_global_condition + result 키 저장 (문자열/숫자 모두 == 비교)
# - 표시: progress_value_key() 로 화면·정렬용 문자열 통일
# ---------------------------------------------------------------------------

_PROGRESS_VAR_RE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(.+)\s*$")


def progress_value_key(val) -> str:
    """세이브·조건·result 값을 FLOW/조건 비교용 문자열로 통일."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, float) and val == int(val):
        return int(val)
    if isinstance(val, (int,)):
        return str(val)
    s = str(val).strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def parse_condition_for_var(condition_expr, var_name: str):
    """
    단일 변수 조건 파싱 (FLOW·binding 스캔 공통).
    반환: None | ("always", "") | ("eq"|"ge"|"gt"|"le"|"lt", value_str) | ("other", value_str)
    """
    target = str(var_name or "").strip()
    if not target:
        return None
    s = normalize_condition_expr(condition_expr)
    if not s:
        return ("always", "")
    m = _PROGRESS_VAR_RE.match(s)
    if not m:
        return None
    key, op, rhs_raw = m.group(1), m.group(2), m.group(3).strip()
    if key != target:
        return None
    rhs = progress_value_key(_parse_condition_rhs(rhs_raw, {}))
    if op == "==":
        return ("eq", rhs)
    if op == ">=":
        return ("ge", rhs)
    if op == ">":
        return ("gt", rhs)
    if op == "<=":
        return ("le", rhs)
    if op == "<":
        return ("lt", rhs)
    return ("other", rhs)


def _flow_collect_var_names_from_condition(condition_expr, names: set):
    s = normalize_condition_expr(condition_expr)
    if not s:
        return
    m = _PROGRESS_VAR_RE.match(s)
    if not m:
        return
    key = m.group(1)
    if key == "mainprogress" or str(key).startswith("progress_"):
        names.add(key)


def collect_progress_variables(event_data, obj_assets=None, char_assets=None, world_data=None):
    """
    events.json·interact·존에서 쓰인 progress 계열 변수 이름 목록.
    mainprogress 와 progress_* 를 같은 방식으로 수집 (저장 타입은 런타임에 이미 통일).
    """
    names = set()
    obj_assets = obj_assets or {}
    char_assets = char_assets or {}
    world_data = world_data if isinstance(world_data, dict) else {}

    for sec in ("GLOBAL", "LOCAL", "SYNC"):
        for eid, ev in (event_data.get(sec) or {}).items():
            if not isinstance(ev, dict):
                continue
            res = ev.get("result")
            if isinstance(res, dict):
                for k in res:
                    if k == "mainprogress" or str(k).startswith("progress_"):
                        names.add(str(k))
            _flow_collect_var_names_from_condition(ev.get("condition"), names)

    def _scan_interact(inter, entity_name, source):
        if not isinstance(inter, dict):
            return
        for b in inter.get("bindings") or []:
            if not isinstance(b, dict):
                continue
            _flow_collect_var_names_from_condition(b.get("condition"), names)

    for oname, oinfo in obj_assets.items():
        _scan_interact((oinfo or {}).get("interact"), oname, "object_defs")
    for cname, cinfo in char_assets.items():
        _scan_interact((cinfo or {}).get("interact"), cname, "char_defs")
    for mid, mdata in world_data.items():
        if not isinstance(mdata, dict):
            continue
        for o in mdata.get("objects") or []:
            if isinstance(o, dict):
                _scan_interact(o.get("interact"), str(o.get("name") or ""), f"map:{mid}")
        for n in mdata.get("npcs") or []:
            if isinstance(n, dict):
                _scan_interact(n.get("interact"), str(n.get("name") or ""), f"map:{mid}")
        if str(mid) and mdata.get("event_zones"):
            for z in mdata.get("event_zones") or []:
                if not isinstance(z, dict):
                    continue
                cond = z.get("conditions") or {}
                mp = cond.get("mainprogress")
                if mp is not None and str(mp).strip() != "":
                    names.add("mainprogress")

    out = sorted(names, key=lambda v: (0 if v == "mainprogress" else 1, v))
    return out


def _flow_sort_stage_values(values):
    def _key(v):
        if v == "__bootstrap__":
            return (0, "")
        try:
            return (1, int(str(v)))
        except (TypeError, ValueError):
            return (2, str(v))

    return sorted(set(values), key=_key)


def build_var_flow_graph(var_name, event_data, events_catalog, obj_assets=None, char_assets=None, world_data=None):
    """
    한 progress 변수에 대한 단계형 플로우 데이터 (에디터 FLOW 모드).
    stages[].triggers / outcomes 로 이벤트·오브젝트·캐릭터 연결.
    """
    var_name = str(var_name or "").strip()
    if not var_name:
        return {"var": "", "stages": [], "note": "변수 없음"}

    obj_assets = obj_assets or {}
    char_assets = char_assets or {}
    world_data = world_data if isinstance(world_data, dict) else {}
    stages = {}

    def _stage(val):
        k = str(val)
        if k not in stages:
            stages[k] = {"value": k, "triggers": [], "outcomes": []}
        return stages[k]

    def _add_outcome(from_val, event_id, to_val, via=""):
        if not to_val:
            return
        st = _stage(from_val)
        row = {"event_id": str(event_id), "to_value": progress_value_key(to_val), "via": via}
        if row not in st["outcomes"]:
            st["outcomes"].append(row)

    for sec in ("GLOBAL", "LOCAL", "SYNC"):
        for eid, ev in (event_data.get(sec) or {}).items():
            if not isinstance(ev, dict):
                continue
            cond_raw = str(ev.get("condition") or "").strip()
            parsed = parse_condition_for_var(ev.get("condition"), var_name)
            if parsed is None:
                continue
            kind, req = parsed
            if kind == "other":
                continue
            if kind == "always":
                # 조건 비어 있음 → binding 전용(manual) 이벤트는 interact 쪽만 표시
                if not cond_raw:
                    continue
                from_val = "__bootstrap__"
            else:
                from_val = req
            res = ev.get("result") if isinstance(ev.get("result"), dict) else {}
            to_val = progress_value_key(res.get(var_name)) if var_name in res else ""
            _stage(from_val)
            stages[from_val]["triggers"].append(
                {
                    "kind": "event",
                    "section": sec,
                    "event_id": eid,
                    "title": str(ev.get("title") or eid),
                    "condition": str(ev.get("condition") or "").strip() or "(항상)",
                    "trigger": str(ev.get("trigger") or ""),
                    "work_map": str(ev.get("work_map") or ""),
                }
            )
            _add_outcome(from_val, eid, to_val, via=sec)

    range_bind_queue = []

    def _attach_interact_binding(from_val, entity_name, entity_kind, source_label, eid, condition_text):
        eid = str(eid or "").strip()
        if not eid:
            return
        _stage(from_val)
        row = {
            "kind": "interact",
            "entity": str(entity_name),
            "entity_kind": entity_kind,
            "source": source_label,
            "event_id": eid,
            "condition": str(condition_text or ""),
        }
        if row not in stages[from_val]["triggers"]:
            stages[from_val]["triggers"].append(row)
        ev = events_catalog.get(eid) if events_catalog else None
        if isinstance(ev, dict):
            res = ev.get("result") if isinstance(ev.get("result"), dict) else {}
            _add_outcome(from_val, eid, res.get(var_name), via=f"interact {entity_name}")

    def _scan_entity_interact(inter, entity_name, entity_kind, source_label):
        if not isinstance(inter, dict):
            return
        for b in inter.get("bindings") or []:
            if not isinstance(b, dict):
                continue
            parsed = parse_condition_for_var(b.get("condition"), var_name)
            if not parsed:
                continue
            cmp_kind, req = parsed
            if cmp_kind == "other":
                continue
            eid = str(b.get("event_id") or "").strip()
            cond_txt = str(b.get("condition") or "")
            if cmp_kind == "eq":
                _attach_interact_binding(req, entity_name, entity_kind, source_label, eid, cond_txt)
            elif cmp_kind in ("ge", "gt", "le", "lt"):
                range_bind_queue.append(
                    {
                        "cmp_kind": cmp_kind,
                        "req": req,
                        "entity_name": entity_name,
                        "entity_kind": entity_kind,
                        "source_label": source_label,
                        "event_id": eid,
                        "condition": cond_txt,
                    }
                )

    def _flush_range_interact_binds():
        """>= 1002 등: 이미 수집된 단계 값 중 조건에 맞는 from_val 에 binding 복제."""
        numeric = []
        for k in stages.keys():
            if k == "__bootstrap__":
                continue
            try:
                numeric.append((int(str(k)), k))
            except (TypeError, ValueError):
                numeric.append((10**9, str(k)))
        for rb in range_bind_queue:
            cmp_kind = rb["cmp_kind"]
            try:
                thresh = int(str(rb["req"]))
            except (TypeError, ValueError):
                continue
            for num, raw in numeric:
                ok = False
                if cmp_kind == "ge" and num >= thresh:
                    ok = True
                elif cmp_kind == "gt" and num > thresh:
                    ok = True
                elif cmp_kind == "le" and num <= thresh:
                    ok = True
                elif cmp_kind == "lt" and num < thresh:
                    ok = True
                if ok:
                    _attach_interact_binding(
                        raw,
                        rb["entity_name"],
                        rb["entity_kind"],
                        rb["source_label"],
                        rb["event_id"],
                        rb["condition"],
                    )

    for oname, oinfo in obj_assets.items():
        _scan_entity_interact((oinfo or {}).get("interact"), oname, "obj", "object_defs")
    for cname, cinfo in char_assets.items():
        _scan_entity_interact((cinfo or {}).get("interact"), cname, "char", "char_defs")
    for mid, mdata in world_data.items():
        if not isinstance(mdata, dict):
            continue
        for o in mdata.get("objects") or []:
            if isinstance(o, dict) and o.get("name"):
                base = dict(obj_assets.get(o["name"], {}) or {})
                inst = o.get("interact") if isinstance(o.get("interact"), dict) else {}
                row = dict(base)
                row["interact"] = merge_interact_spec(
                    base, {"interact": inst} if inst else {}
                )
                _scan_entity_interact(row, o["name"], "obj", f"map:{mid}")
        for n in mdata.get("npcs") or []:
            if isinstance(n, dict) and n.get("name"):
                base = dict(char_assets.get(n["name"], {}) or {})
                inst = n.get("interact") if isinstance(n.get("interact"), dict) else {}
                row = dict(base)
                if inst:
                    from char_behavior import _deep_merge

                    row["interact"] = _deep_merge(dict(base.get("interact") or {}), inst)
                _scan_entity_interact(row, n["name"], "char", f"map:{mid}")

    if var_name == "mainprogress":
        for mid, mdata in world_data.items():
            if not isinstance(mdata, dict):
                continue
            for z in mdata.get("event_zones") or []:
                if not isinstance(z, dict):
                    continue
                cond = z.get("conditions") or {}
                mp = cond.get("mainprogress")
                if mp is None or str(mp).strip() == "":
                    continue
                from_val = progress_value_key(mp)
                eid = str(z.get("event_id") or "").strip()
                if not eid:
                    continue
                _stage(from_val)
                stages[from_val]["triggers"].append(
                    {
                        "kind": "zone",
                        "map_id": str(mid),
                        "zone_name": str(z.get("name") or eid),
                        "event_id": eid,
                        "condition": f'mainprogress == "{from_val}"',
                        "trigger": str(z.get("trigger") or "contact_player"),
                    }
                )
                ev = events_catalog.get(eid) if events_catalog else None
                if isinstance(ev, dict):
                    res = ev.get("result") if isinstance(ev.get("result"), dict) else {}
                    _add_outcome(from_val, eid, res.get(var_name), via="zone")

    def _seed_stages_from_outcomes():
        """result 로만 등장하는 값(예: 1003)도 >= binding 대상에 포함."""
        for st in list(stages.values()):
            for oc in st.get("outcomes") or []:
                to_v = progress_value_key(oc.get("to_value"))
                if to_v:
                    _stage(to_v)

    _seed_stages_from_outcomes()
    _flush_range_interact_binds()

    ordered = _flow_sort_stage_values(stages.keys())
    note = ""
    if not ordered:
        note = "이 변수를 쓰는 조건/result 가 없습니다."
    return {
        "var": var_name,
        "stages": [stages[v] for v in ordered],
        "note": note,
    }


def progress_var_defaults_from_config():
    """data.py CONFIG 에 있는 progress_* / mainprogress 초기값."""
    try:
        from data import CONFIG
    except ImportError:
        return {}
    out = {}
    for k, v in (CONFIG or {}).items():
        if k == "mainprogress" or str(k).startswith("progress_"):
            out[str(k)] = v
    return out


def _flow_stage_key(raw_val):
    if str(raw_val) == "__bootstrap__":
        return "__bootstrap__"
    return progress_value_key(raw_val)


def _flow_lanes_from_graph(graph: dict):
    """
    에디터 다이어그램용 연결 행(lane) 목록.
    한 행: 상태 → (오브젝트/NPC) → 이벤트 → 다음 상태
    """
    lanes = []
    for stage in graph.get("stages") or []:
        sk = _flow_stage_key(stage.get("value"))
        outcomes = {
            str(oc.get("event_id") or ""): oc for oc in (stage.get("outcomes") or [])
        }
        for tr in stage.get("triggers") or []:
            eid = str(tr.get("event_id") or "")
            oc = outcomes.get(eid, {})
            to_v = progress_value_key(oc.get("to_value")) if oc else ""
            lanes.append(
                {
                    "from": sk,
                    "to": to_v,
                    "event": eid,
                    "section": str(tr.get("section") or ""),
                    "condition": str(tr.get("condition") or "").strip() or "(항상)",
                    "kind": str(tr.get("kind") or ""),
                    "entity": str(tr.get("entity") or "") if tr.get("kind") == "interact" else "",
                    "entity_kind": str(tr.get("entity_kind") or "obj"),
                    "zone_name": str(tr.get("zone_name") or ""),
                    "map_id": str(tr.get("map_id") or ""),
                }
            )
    return lanes


def build_var_flow_diagram(
    var_name,
    event_data,
    events_catalog,
    obj_assets=None,
    char_assets=None,
    world_data=None,
    save_defaults=None,
):
    """
    FLOW 에디터: 박스·화살표 다이어그램용 데이터.
    build_var_flow_graph 결과 + lanes + default( data.py 등 ).
    """
    graph = build_var_flow_graph(
        var_name, event_data, events_catalog, obj_assets, char_assets, world_data
    )
    defaults = save_defaults if save_defaults is not None else progress_var_defaults_from_config()
    default_val = ""
    if var_name in defaults:
        default_val = progress_value_key(defaults[var_name])
    lanes = _flow_lanes_from_graph(graph)
    nodes, edges = _flow_build_network(
        var_name,
        lanes,
        default_val,
        event_data,
        obj_assets or {},
        char_assets or {},
        events_catalog or {},
    )
    return {
        "var": graph.get("var", ""),
        "note": graph.get("note", ""),
        "stages": graph.get("stages", []),
        "default": default_val,
        "lanes": lanes,
        "nodes": nodes,
        "edges": edges,
    }


def _flow_build_network(
    var_name,
    lanes,
    default_val,
    event_data,
    obj_assets,
    char_assets,
    events_catalog,
):
    """
    FLOW 작업화면용 노드·엣지 — 변수·상태·오브젝트/NPC·이벤트 상자를 모두 포함.
    lanes 로 화살표(조건·상호작용·result) 연결.
    """
    nodes = {}
    edges = []

    def _nid(kind, key):
        return f"{kind}:{key}"

    def _add_node(nid, kind, label, sublabel="", sort_key=None, hit=None):
        if nid in nodes:
            return
        nodes[nid] = {
            "id": nid,
            "kind": kind,
            "label": str(label or "")[:28],
            "sublabel": str(sublabel or "")[:24],
            "sort_key": sort_key if sort_key is not None else label,
            "hit": dict(hit or {}),
        }

    seen_edges = set()

    def _add_edge(frm, to, label="", cycle=False):
        if not frm or not to or frm == to:
            return
        key = (frm, to, str(label or "")[:36])
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append(
            {"from": frm, "to": to, "label": key[2], "cycle": bool(cycle)}
        )

    vn = _nid("var", var_name)
    _add_node(vn, "var", var_name, "progress 변수", var_name)

    if default_val:
        ds = _nid("state", default_val)
        _add_node(ds, "state", f"= {default_val}", "data.py 기본", default_val)
        _add_edge(vn, ds, "기본값")

    def _cycle_edge(to_val, from_val):
        if to_val and to_val == default_val:
            return True
        try:
            return int(to_val) <= int(from_val)
        except (TypeError, ValueError):
            return False

    for lane in lanes:
        fr = str(lane.get("from") or "")
        to = str(lane.get("to") or "")
        eid = str(lane.get("event") or "")
        ent = str(lane.get("entity") or "")
        ek = str(lane.get("entity_kind") or "obj")
        cond = str(lane.get("condition") or "")
        kind = str(lane.get("kind") or "")

        sid_fr = _nid("state", fr) if fr else ""
        sid_to = _nid("state", to) if to else ""
        if fr:
            _add_node(sid_fr, "state", f"= {fr}", "", fr)
        if to:
            _add_node(sid_to, "state", f"= {to}", "", to)

        nid_ent = ""
        if kind == "interact" and ent:
            nid_ent = _nid("ent", f"{ek}:{ent}")
            tag = "OBJ" if ek == "obj" else "NPC"
            _add_node(
                nid_ent,
                "entity",
                ent,
                tag,
                ent,
                {
                    "action": "entity",
                    "entity": ent,
                    "entity_kind": ek,
                },
            )
        elif kind == "zone":
            zkey = f"{lane.get('map_id', '')}:{lane.get('zone_name', '')}"
            nid_ent = _nid("zone", zkey)
            _add_node(
                nid_ent,
                "zone",
                str(lane.get("zone_name") or "zone")[:28],
                f"ZONE {lane.get('map_id', '')}",
                zkey,
            )

        nid_ev = _nid("evt", eid) if eid else ""
        if eid:
            sec = str(lane.get("section") or "")
            _add_node(
                nid_ev,
                "event",
                eid,
                f"[{sec}]" if sec else "이벤트",
                eid,
                {"action": "event", "event_id": eid, "section": sec},
            )

        if sid_fr and nid_ent:
            _add_edge(sid_fr, nid_ent, cond)
        if nid_ent and nid_ev:
            _add_edge(nid_ent, nid_ev, "상호작용")
        elif sid_fr and nid_ev:
            _add_edge(sid_fr, nid_ev, cond)
        if nid_ev and sid_to:
            _add_edge(nid_ev, sid_to, "result", _cycle_edge(to, fr))

    def _condition_mentions_var(cond_text):
        s = normalize_condition_expr(cond_text)
        return var_name in s and parse_condition_for_var(cond_text, var_name) is not None

    for sec in ("GLOBAL", "LOCAL", "SYNC"):
        for eid, ev in (event_data.get(sec) or {}).items():
            if not isinstance(ev, dict):
                continue
            res = ev.get("result") if isinstance(ev.get("result"), dict) else {}
            cond_raw = str(ev.get("condition") or "")
            touches = var_name in res or _condition_mentions_var(cond_raw)
            if not touches:
                continue
            nid_ev = _nid("evt", eid)
            _add_node(
                nid_ev,
                "event",
                eid,
                f"[{sec}]",
                eid,
                {"action": "event", "event_id": eid, "section": sec},
            )
            if var_name in res:
                to_v = progress_value_key(res[var_name])
                if to_v:
                    sid_to = _nid("state", to_v)
                    _add_node(sid_to, "state", f"= {to_v}", "result", to_v)
                    _add_edge(nid_ev, sid_to, "result", _cycle_edge(to_v, ""))

    def _scan_assets(assets, entity_kind):
        for name, info in (assets or {}).items():
            inter = (info or {}).get("interact")
            if not isinstance(inter, dict):
                continue
            for b in inter.get("bindings") or []:
                if not isinstance(b, dict):
                    continue
                if not _condition_mentions_var(b.get("condition")):
                    continue
                eid = str(b.get("event_id") or "").strip()
                nid_ent = _nid("ent", f"{entity_kind}:{name}")
                tag = "OBJ" if entity_kind == "obj" else "NPC"
                _add_node(
                    nid_ent,
                    "entity",
                    name,
                    tag,
                    name,
                    {"action": "entity", "entity": name, "entity_kind": entity_kind},
                )
                if eid and eid in events_catalog:
                    _add_node(
                        _nid("evt", eid),
                        "event",
                        eid,
                        "binding",
                        eid,
                        {"action": "event", "event_id": eid, "section": ""},
                    )

    _scan_assets(obj_assets, "obj")
    _scan_assets(char_assets, "char")

    return list(nodes.values()), edges


def entity_carry_click_allowed(entity) -> bool:
    """
    클릭으로 들기( begin_carry_pickup ).
    is_holdable 이고 interact.enabled 가 true 이어야 함.
    bindings 가 있으면 클릭은 이벤트만( try_start_interact_event ) — 직접 줍기 불가.
    이벤트 CARRY pick 은 interact 와 무관하게 is_holdable 만 검사.
    """
    from data import OBJ_ASSETS

    name = getattr(entity, "name", "")
    info = OBJ_ASSETS.get(name, {})
    holdable = bool(info.get("is_holdable") or getattr(entity, "is_holdable", False))
    if not holdable or getattr(entity, "is_held", False):
        return False
    spec = entity_interact_spec(entity)
    if not interact_spec_enabled(spec):
        return False
    if spec.get("bindings"):
        return False
    return True


def entity_interact_range(entity, *, default=40.0) -> float:
    """플레이어가 서 있어야 상호작용이 실행되는 거리(interact.range). 클릭 판정과는 별도."""
    spec = entity_interact_spec(entity)
    try:
        return float(spec.get("range", default))
    except (TypeError, ValueError):
        return float(default)


def interact_spec_offset(spec) -> tuple:
    """
    interact.offset — 발(origin) 기준 월드 px [x, y]. 비우면 (0, 0).
    +x 오른쪽, +y 아래(월드 좌표와 동일).
    """
    if not isinstance(spec, dict):
        return 0.0, 0.0
    off = spec.get("offset")
    if isinstance(off, (list, tuple)) and len(off) >= 2:
        try:
            return float(off[0]), float(off[1])
        except (TypeError, ValueError):
            return 0.0, 0.0
    try:
        ox = float(spec.get("offset_x", 0) or 0)
    except (TypeError, ValueError):
        ox = 0.0
    try:
        oy = float(spec.get("offset_y", 0) or 0)
    except (TypeError, ValueError):
        oy = 0.0
    return ox, oy


def entity_interact_anchor_xy(entity):
    """상호작용 접근 거리 원의 중심 — origin_pos + interact.offset."""
    op = getattr(entity, "origin_pos", None) or getattr(entity, "pos", None)
    if not op:
        return None
    try:
        dx, dy = interact_spec_offset(entity_interact_spec(entity))
        return float(op[0]) + dx, float(op[1]) + dy
    except (TypeError, ValueError):
        return float(op[0]), float(op[1])


def click_hits_entity_sprite(entity, wx, wy, *, pad_px=None) -> bool:
    """
    상호작용 '의도' 클릭 — 스프라이트(로직 rect) 안을 눌렀는지.
    interact.range(접근 거리)만으로는 지나가기용 이동 클릭이 interact 로 잡히므로 여기서 분리한다.
    """
    op = getattr(entity, "origin_pos", None) or getattr(entity, "pos", None)
    if not op:
        return False
    try:
        ox, oy = float(op[0]), float(op[1])
        cx, cy = float(wx), float(wy)
    except (TypeError, ValueError):
        return False
    if pad_px is None:
        try:
            pad_px = float(CONFIG.get("INTERACT_CLICK_HIT_PAD_PX", 4))
        except (TypeError, ValueError):
            pad_px = 4.0
    pad_px = max(0.0, float(pad_px))
    rw = getattr(entity, "rect_for_logic", None)
    if rw is not None:
        half_w = max(8, int(rw.width) // 2) + pad_px
        half_h = max(6, int(rw.height) // 2) + pad_px
        return abs(cx - ox) < half_w and abs(cy - oy) < half_h
    try:
        r = float(CONFIG.get("INTERACT_CLICK_HIT_RADIUS", 24))
    except (TypeError, ValueError):
        r = 24.0
    return math.hypot(cx - ox, cy - oy) <= max(8.0, r)


def start_catalog_event(
    ev_mgr,
    events_catalog: dict,
    event_id: str,
    player,
    npcs,
    objs,
    field_tilt_snapshot=None,
    *,
    is_sync=False,
) -> bool:
    """events_catalog 에서 ID 로 연출 시작(존/글로벌/상호작용 공통)."""
    ev = events_catalog.get(event_id)
    if not ev or ev_mgr.active_event:
        return False
    ev_mgr.reset_entity_event_zooms(player, npcs, objs)
    ev_mgr.start_event(
        ev.get("steps") or [],
        event_id,
        ev.get("result"),
        ev,
        is_sync=is_sync,
    )
    if field_tilt_snapshot is not None:
        ev_mgr.field_tilt_snapshot = field_tilt_snapshot
    return True


def try_start_interact_event(
    entity,
    flow,
    ev_mgr,
    events_catalog: dict,
    map_id: str,
    *,
    session_vars=None,
    field_tilt_snapshot=None,
    player=None,
    npcs=None,
    objs=None,
) -> bool:
    """
    NPC/오브젝트 상호작용 → progress 조건 → events.json 실행.
    조건에 맞는 binding 이 없으면 False (호출부에서 CARRY 등으로 폴백).
    """
    if ev_mgr.active_event or getattr(ev_mgr, "is_talking", False):
        return False
    spec = entity_interact_spec(entity)
    if not entity_interact_enabled(entity):
        return False
    ctx = build_eval_ctx(flow.save_data if flow else {}, session_vars)
    ctx["map_id"] = str(map_id or "")
    ctx["npc_name"] = str(getattr(entity, "name", "") or "")
    eid = pick_interact_event(spec.get("bindings"), ctx, events_catalog)
    if not eid:
        return False
    if player is not None:
        try:
            player.stop_moving()
        except Exception:
            pass
    ok = start_catalog_event(
        ev_mgr,
        events_catalog,
        eid,
        player,
        npcs,
        objs,
        field_tilt_snapshot,
    )
    if ok:
        print(f"[Interact] event '{eid}' via {getattr(entity, 'name', '?')}")
        if player is not None and getattr(entity, "char_def", None):
            try:
                from char_behavior import face_toward_player

                face_toward_player(entity, player)
            except Exception:
                pass
    return ok


def start_system_event(
    ev_mgr,
    events_catalog: dict,
    event_id: str,
    field_tilt_snapshot=None,
) -> bool:
    """코드에서 직접 호출하는 시스템 이벤트 (메뉴, 게임오버 등)."""
    ev = events_catalog.get(event_id)
    if not ev:
        print(f"[SystemEvent] unknown id: {event_id}")
        return False
    if ev_mgr.active_event:
        return False
    ev_mgr.start_event(ev.get("steps") or [], event_id, ev.get("result"), ev)
    # None이면 복원 안 함(핫키 한 스텝 DEV_CMD 등). 실제 연출 이벤트는 호출부에서 스냅샷을 넘길 것.
    if field_tilt_snapshot is not None:
        ev_mgr.field_tilt_snapshot = field_tilt_snapshot
    return True


def merge_save_defaults(save_data: dict, config) -> dict:
    """누락된 세이브 키를 채움. gamestart 등 온보딩 단계는 세이브에 두지 않음(구 파일에 있으면 제거)."""
    if not save_data:
        save_data = {}
    _spawn = config.get("NEW_GAME_SPAWN_POS") or [100, 100]
    defaults = {
        "mainprogress": "010100",
        "laugh_point": 0,
        "subprogress": {},
        "player_pos": list(_spawn),
        "current_map": config["START_MAP"],
        # "hide": 도랑 점프 등 중 그림자 없음 / "ground": 땅 위치에 작고 옅게 유지
        "jump_shadow_mode": "ground",
        "flags": {},
        "affinity": {},
    }
    for k, v in defaults.items():
        if k not in save_data:
            save_data[k] = v
    # data.py CONFIG 의 progress_* / mainprogress 초기값 (세이브에 없으면 채움)
    for k, v in (config or {}).items():
        if k == "mainprogress" or str(k).startswith("progress_"):
            if k not in save_data:
                save_data[k] = v
    save_data.pop("gamestart", None)
    return save_data

def _compact_steps_to_single_lines(json_text: str) -> str:
    """
    events.json에서 steps 배열 내부의 각 step dict를 한 줄로 압축합니다.
    - JSON 파싱/재덤프 없이 문자열 레벨에서 동작 (키 순서/indent는 유지)
    - steps 바깥의 일반 dict는 건드리지 않음
    """
    lines = json_text.splitlines()
    out: list[str] = []
    in_steps = False
    collecting = False
    buf: list[str] = []

    def flush_buf():
        nonlocal buf, collecting
        if not buf:
            return
        # 첫 줄의 indentation을 유지한 채, 내부는 공백으로 정리
        indent = re.match(r"^\s*", buf[0]).group(0)
        joined = " ".join(s.strip() for s in buf)
        # 과도한 공백 정리
        joined = re.sub(r"\s+", " ", joined)
        out.append(indent + joined.strip())
        buf = []
        collecting = False

    for line in lines:
        if not in_steps:
            out.append(line)
            if re.search(r'"steps"\s*:\s*\[', line):
                in_steps = True
            continue

        # steps 블록 안
        if collecting:
            buf.append(line)
            # step 객체 종료(대부분 "}," 또는 "}"로 끝남)
            if re.search(r"^\s*\},?\s*$", line):
                flush_buf()
            continue

        # steps 블록 종료 감지
        if re.search(r"^\s*\]\s*,?\s*$", line):
            out.append(line)
            in_steps = False
            continue

        # step 시작 감지: 보통 '{' 로 시작
        if re.search(r"^\s*\{\s*$", line):
            collecting = True
            buf = [line]
            continue

        # 그 외 (빈 줄/주석 없음/기타 라인)
        out.append(line)

    # 혹시 남아있으면 플러시
    if collecting:
        flush_buf()

    return "\n".join(out) + ("\n" if json_text.endswith("\n") else "")


def _compact_named_array_objects_to_single_lines(json_text: str, array_key: str) -> str:
    """
    world_data.json 등에서 "objects" / "npcs" 배열 안의 각 엔트리 dict를 한 줄로 압축합니다.
    json.dumps(indent=4) 결과에 대해 steps 압축과 동일한 상태 머신을 사용합니다.
    """
    lines = json_text.splitlines()
    out: list[str] = []
    trigger = re.compile(rf'^\s*"{re.escape(array_key)}"\s*:\s*\[')
    in_arr = False
    collecting = False
    buf: list[str] = []

    def flush_buf():
        nonlocal buf, collecting
        if not buf:
            return
        indent = re.match(r"^\s*", buf[0]).group(0)
        joined = " ".join(s.strip() for s in buf)
        joined = re.sub(r"\s+", " ", joined)
        out.append(indent + joined.strip())
        buf = []
        collecting = False

    for line in lines:
        if not in_arr:
            out.append(line)
            if trigger.search(line):
                in_arr = True
            continue

        if collecting:
            buf.append(line)
            if re.search(r"^\s*\},?\s*$", line):
                flush_buf()
            continue

        if re.search(r"^\s*\]\s*,?\s*$", line):
            out.append(line)
            in_arr = False
            continue

        if re.search(r"^\s*\{\s*$", line):
            collecting = True
            buf = [line]
            continue

        out.append(line)

    if collecting:
        flush_buf()

    return "\n".join(out) + ("\n" if json_text.endswith("\n") else "")


class GameFlow:
    def __init__(self, config=None): # 에디터 대응을 위해 None 허용
        self.config = config if config else CONFIG
        self.save_path = self.config.get("SAVE_FILE", "save.json")
        self.world_data = self.load_world_config()
        loaded = self.load_save_data()
        if not loaded:
            loaded = {}
        self.save_data = merge_save_defaults(loaded, self.config)
        # 매 실행: 0=인트로, 1=데모, 2=본편 (세이브 없음, pick_global 시 session_vars로만 전달)
        self.boot_phase = 0
        # contact_player: 존 안에 머무는 동안 매 프레임 재발동 방지 (진입 엣지에서만)
        self._zone_player_inside = {}
        if "mainprogress" not in self.save_data:
            _sp = list(self.config.get("NEW_GAME_SPAWN_POS") or [100, 100])
            self.save_data = merge_save_defaults(
                {
                    "mainprogress": "010100",
                    "laugh_point": 0,
                    "subprogress": {},
                    "player_pos": _sp,
                    "current_map": self.config["START_MAP"],
                },
                self.config,
            )

    def reset_zone_contact_state(self, map_id=None):
        """맵 전환 등: contact_player 엣지 추적 초기화."""
        if map_id is None:
            self._zone_player_inside = {}
        else:
            self._zone_player_inside.pop(str(map_id), None)

    def check_zone_trigger(
        self,
        map_id,
        player_pos,
        is_action_pressed=False,
        dt=0,
        objs=None,
        npcs=None,
        *,
        zone_click_world=None,
    ):
        m = self.world_data.get(map_id, {})
        zones = m.get("event_zones", [])
        save = self.save_data
        px, py = player_pos
        mid = str(map_id)
        prev_inside = self._zone_player_inside.get(mid, set())
        now_inside = set()

        for zi, z in enumerate(zones):
            zx, zy, zw, zh = z["rect"]
            if zx <= px <= zx + zw and zy <= py <= zy + zh:
                now_inside.add(zi)

        for zi, z in enumerate(zones):
            zx, zy, zw, zh = z["rect"]
            # 1. 위치 체크
            if zi not in now_inside:
                continue

            # 2. 조건 체크
            cond = z.get("conditions", {})
            
            # 메인 진행도 체크 (get을 써서 안전하게 비교)
            if cond.get("mainprogress") and cond["mainprogress"] != save.get("mainprogress"):
                continue
                
            # 웃음 포인트 체크
            if "min_laugh_point" in cond:
                if save.get("laugh_point", 0) < cond["min_laugh_point"]:
                    continue

            # 3. 트리거 체크 (json에 쓴 "contact_player" 대응)
            t_type = z.get("trigger", "contact")
            if t_type == "contact_player" or t_type == "contact":
                # 존에 머무는 동안(level)이 아니라, 처음 들어올 때(edge)만 발동
                if zi not in prev_inside:
                    self._zone_player_inside[mid] = now_inside
                    return z["event_id"]
                continue

            elif t_type == "contact_confirm":
                # 플레이어가 박스 안에 있을 때만: 이번 프레임 '상호작용 점'이 박스 안이면 발동.
                # 상호작용 점 = 좌클릭 월드좌표 또는 A/Space/Enter 시 커서(터치 포인터)의 월드좌표.
                # 박스 밖을 찍으면 이 분기는 통과하지 않고, 이동 처리만 된다.
                ok = False
                if zone_click_world is not None:
                    try:
                        cx = float(zone_click_world[0])
                        cy = float(zone_click_world[1])
                        if zx <= cx <= zx + zw and zy <= cy <= zy + zh:
                            ok = True
                    except Exception:
                        pass
                if ok:
                    self._zone_player_inside[mid] = now_inside
                    return z["event_id"]
                continue
            
            elif t_type == "contact_object":
                # 지정된 target(오브젝트/NPC name)과 접촉했을 때만 발동
                tgt = (z.get("target") or "").strip()
                if not tgt:
                    continue
                pool = []
                if objs: pool.extend(objs)
                if npcs: pool.extend(npcs)
                # "contact" 판정: 플레이어와 대상의 거리 기준(대략 상호작용 거리와 비슷하게)
                for o in pool:
                    if getattr(o, "name", None) != tgt:
                        continue
                    op = getattr(o, "origin_pos", None) or getattr(o, "pos", None)
                    if not op:
                        continue
                    try:
                        if math.dist((px, py), (op[0], op[1])) <= 30:
                            self._zone_player_inside[mid] = now_inside
                            return z["event_id"]
                    except:
                        pass

            elif t_type == "press_z" and is_action_pressed:
                self._zone_player_inside[mid] = now_inside
                return z["event_id"]

        self._zone_player_inside[mid] = now_inside
        return None

    def save_editor_data(self, map_id, objs, npcs):
        # 데이터 정리
        def _object_entry_from_instance(o):
            row = {
                "name": o.name,
                "pos": [int(o.pos[0]), int(o.pos[1])],
                "sprite_tilt": round(float(getattr(o, "sprite_tilt", 1.0)), 4),
                "height": int(round(float(getattr(o, "height", 0) or 0))),
                "ysort": str(getattr(o, "ysort_mode", "ground") or "ground"),
                "layer": int(getattr(o, "layer", 0) or 0),
            }
            inst = getattr(o, "interact_instance", None)
            if isinstance(inst, dict) and inst:
                row["interact"] = inst
            return row

        self.world_data[map_id]["objects"] = [_object_entry_from_instance(o) for o in objs]
        from char_behavior import npc_entry_from_instance

        self.world_data[map_id]["npcs"] = [npc_entry_from_instance(n) for n in npcs]

        try:
            raw_json = json.dumps(self.world_data, indent=4, ensure_ascii=False)
            
            # 1. [x, y] 좌표 한 줄로 만들기
            compact_json = re.sub(r'\[\s+(-?\d+\.?\d*),\s+(-?\d+\.?\d*)\s+\]', r'[\1, \2]', raw_json)
            # 2. [x, y, w, h] 구역 한 줄로 만들기
            compact_json = re.sub(r'\[\s+(-?\d+),\s+(-?\d+),\s+(-?\d+),\s+(-?\d+)\s+\]', r'[\1, \2, \3, \4]', compact_json)
            # 3. { "name": "...", "pos": [...] } 객체 전체를 한 줄로 만들기 (선택 사항)
            compact_json = re.sub(r'\{\s+"name":\s+"([^"]+)",\s+"pos":\s+\[([^\]]+)\]\s+\}', r'{"name": "\1", "pos": [\2]}', compact_json)
            # 4. 맵별 objects / npcs 배열의 각 오브젝트 dict를 한 줄로
            compact_json = _compact_named_array_objects_to_single_lines(compact_json, "objects")
            compact_json = _compact_named_array_objects_to_single_lines(compact_json, "npcs")
            # 5. bg_zones도 한 줄로(에디터에서 보기 편하게)
            compact_json = _compact_named_array_objects_to_single_lines(compact_json, "bg_zones")

            with open("world_data.json", "w", encoding="utf-8") as f:
                f.write(compact_json)
            print(f"[{map_id}] 가독성 최적화 저장 성공!")
        except Exception as e:
            print(f"저장 실패: {e}")

    def load_world_config(self):
        with open("world_data.json", "r", encoding="utf-8") as f:
            return json.load(f)

    def load_save_data(self):
        if os.path.exists(self.save_path):
            try:
                with open(self.save_path, "r") as f:
                    return json.load(f)
            except: return None
        return None

    def save_game(self, map_id, player_pos):
        self.save_data["current_map"] = map_id
        self.save_data["player_pos"] = [int(player_pos[0]), int(player_pos[1])]
        
        try:
            with open(self.save_path, "w", encoding="utf-8") as f:
                # 세이브 파일도 읽기 편하게 indent 줌
                json.dump(self.save_data, f, ensure_ascii=False, indent=4)
            print("플레이 데이터가 안전하게 저장되었습니다.")
        except Exception as e:
            print(f"세이브 실패: {e}")

    def load_map(self, save_data=None):
        # 1. 어떤 맵을 부를지 결정 (세이브 데이터 우선, 없으면 CONFIG 기본값)
        map_id = CONFIG["START_MAP"]
        if save_data and "current_map" in save_data:
            map_id = save_data["current_map"]
        
        m = self.world_data[map_id]
        
        # 2. 자산 로드 (경로도 world_data.json에 정의된 대로)
        bg = pygame.image.load(os.path.join("assets", "images", "bg", m["bg_img"])).convert()
        
        mask_path = os.path.join("assets", "images", "bg", m["mask_img"])
        if os.path.exists(mask_path):
            mask = pygame.image.load(mask_path).convert()
        else:
            mask = pygame.Surface(bg.get_size()); mask.fill((255, 255, 255))

        # 3. 플레이어 생성
        start_pos = m.get("start_pos", [100, 100]) # 맵 기본 시작점
        
        # [우선순위 결정]
        if map_id == CONFIG["START_MAP"]:
            # 인트로 맵은 무조건 맵 기본 시작점 사용
            player_initial_pos = start_pos
        elif save_data and save_data.get("player_pos"):
            # 전달된 좌표가 있으면 사용
            player_initial_pos = save_data["player_pos"]
        elif self.save_data.get("current_map") == map_id and self.save_data.get("player_pos"):
            # 전달된 좌표는 없지만, 세이브 파일에 저장된 맵이 현재 맵과 같다면 세이브 위치 사용
            player_initial_pos = self.save_data["player_pos"]
        else:
            # 그 외에는 맵 기본값 사용
            player_initial_pos = start_pos
            
        from engine import Player, FieldItem, BaseCharacter, MaskWalkingCharacter

        pc = str(self.config.get("DEFAULT_PLAYER_CHAR", "c1") or "c1")
        player = Player(pc, [player_initial_pos[0], player_initial_pos[1]], {})
        player.jump_pad_zones = m.get("jump_pads", [])
        
        # 4. 오브젝트/NPC 리스트 생성
        objs = []
        for o in m.get("objects", []):
            it = FieldItem(
                o["name"],
                o["pos"][0],
                o["pos"][1],
                sprite_tilt=o.get("sprite_tilt", 1.0),
                height=o.get("height"),
                ysort_mode=o.get("ysort", "ground"),
                layer=o.get("layer", None),
            )
            # Optional: auto scroll (e.g. fog/cloud background layers)
            # world_data.json:
            #   { "name":"fog1", "pos":[...], "auto_scroll": {"vx": 3.0, "wrap": "camera_view"} }
            # wrap 기본(camera_view 등): 가로 이음 타일(텍스처만 흐름, pos 고정). 예전 방식은 wrap:"legacy_wrap"|"teleport"
            try:
                it.auto_scroll = o.get("auto_scroll", None)
            except Exception:
                it.auto_scroll = None
            # 상호작용(progress→events.json): 타입(object_defs)+맵 인스턴스 병합
            it.interact_instance = dict(o.get("interact") or {}) if isinstance(o.get("interact"), dict) else {}
            it.interact_spec = merge_interact_spec(OBJ_ASSETS.get(o["name"], {}), o)
            objs.append(it)
        npcs = []
        for n in m.get("npcs", []):
            nm = n["name"]
            ch_info = {
                "sprite_tilt": n.get("sprite_tilt", 1.0),
                "ysort": n.get("ysort", "ground"),
                "layer": n.get("layer", 0),
            }
            if "height" in n:
                ch_info["height"] = n["height"]
            from char_behavior import attach_npc_from_entry

            if CHAR_ASSETS.get(nm, {}).get("mask_nav"):
                ch = MaskWalkingCharacter(nm, n["pos"], ch_info)
            else:
                ch = BaseCharacter(nm, n["pos"], ch_info)
            attach_npc_from_entry(ch, n)
            npcs.append(ch)

        return map_id, bg, mask, player, objs, npcs

    def load_events(self):
        """events.json 파일을 읽어옵니다. 없으면 기본 구조를 만듭니다."""
        file_path = "events.json" # data 폴더 안에 저장한다고 가정
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        for key in ("LOCAL", "GLOBAL", "SYNC", "FRAGMENTS"):
            if key not in data or not isinstance(data.get(key), dict):
                data[key] = {}
        return data

    def save_events(self, event_data):
        """현재 작업 중인 이벤트 데이터를 가독성 있게 저장합니다."""
        file_path = "events.json"
        try:
            # 1. 기본 JSON 문자열 생성
            raw_json = json.dumps(event_data, indent=4, ensure_ascii=False)
            
            # 2. 정규식을 이용해 [x, y] 좌표 등을 한 줄로 합치기 (world_data 저장 로직과 동일)
            compact_json = re.sub(r'\[\s+(-?\d+\.?\d*),\s+(-?\d+\.?\d*)\s+\]', r'[\1, \2]', raw_json)
            # 3. steps 내부의 각 step dict를 한 줄로 압축
            compact_json = _compact_steps_to_single_lines(compact_json)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(compact_json)
            print("이벤트 데이터가 가독성 최적화되어 저장되었습니다!")
        except Exception as e:
            print(f"이벤트 저장 실패: {e}")
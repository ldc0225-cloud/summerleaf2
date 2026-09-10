import json, os, pygame, math
import re
import copy
from data import (
    CONFIG,
    CHAR_ASSETS,
    OBJ_ASSETS,
    BASEBALL_DEFAULTS,
    RACING_DEFAULTS,
    BULLFROG_DEFAULTS,
)


def resolve_activity_arena_exit(world_data, map_id, config=None):
    """
    야구/레이싱/황소개구리 등 미니게임 전용 맵이면 (exit_map, exit_pos) 반환. 아니면 None.

    [언제 쓰나]
      - 게임 종료·세이브: 미니게임 맵 좌표를 영속화하지 않음
      - 세이브 로드: 미니게임 맵에 남아 있으면 exit 장소로 스폰

    [exit 출처 우선순위]
      1) world_data[map].baseball.exit_*
      2) world_data[map].racing.exit_*
      3) world_data[map].bullfrog.exit_*
      4) world_data[map] 루트 exit_*
      5) data.py BASEBALL_DEFAULTS / RACING_DEFAULTS / BULLFROG_DEFAULTS
    """
    mid = str(map_id or "").strip()
    if not mid or not isinstance(world_data, dict):
        return None
    m = world_data.get(mid)
    if not isinstance(m, dict):
        return None

    candidates = []
    bb = m.get("baseball")
    if isinstance(bb, dict):
        candidates.append((bb, BASEBALL_DEFAULTS if isinstance(BASEBALL_DEFAULTS, dict) else {}))
    rc = m.get("racing")
    if isinstance(rc, dict):
        candidates.append((rc, RACING_DEFAULTS if isinstance(RACING_DEFAULTS, dict) else {}))
    bf = m.get("bullfrog")
    if isinstance(bf, dict):
        candidates.append((bf, BULLFROG_DEFAULTS if isinstance(BULLFROG_DEFAULTS, dict) else {}))
    if m.get("exit_map") is not None or m.get("exit_pos") is not None:
        candidates.append((m, {}))

    for block, defaults in candidates:
        if not isinstance(block, dict):
            continue
        em = str(block.get("exit_map") or defaults.get("exit_map") or "").strip()
        ep = block.get("exit_pos")
        if not (isinstance(ep, (list, tuple)) and len(ep) >= 2):
            ep = defaults.get("exit_pos")
        if not em or em == mid:
            continue
        if not (isinstance(ep, (list, tuple)) and len(ep) >= 2):
            continue
        try:
            pos = [float(ep[0]), float(ep[1])]
        except (TypeError, ValueError, IndexError):
            continue
        return em, pos
    return None


def apply_activity_arena_save_location(world_data, map_id, player_pos, config=None):
    """세이브용 맵·좌표. 미니게임 전용 맵이면 exit 로 치환."""
    resolved = resolve_activity_arena_exit(world_data, map_id, config=config)
    if resolved is None:
        return str(map_id or ""), player_pos
    return resolved[0], resolved[1]


def normalize_activity_arena_in_save(save_data, world_data, config=None):
    """
    디스크/메모리 세이브에 미니게임 맵이 남아 있으면 exit 로 고쳐 씀.
    MAP 이벤트·의도적 맵 이동에는 쓰지 않는다 (load_map 가로채기 금지).
    변경했으면 True.
    """
    if not isinstance(save_data, dict):
        return False
    mid = save_data.get("current_map")
    resolved = resolve_activity_arena_exit(world_data, mid, config=config)
    if resolved is None:
        return False
    em, ep = resolved
    save_data["current_map"] = em
    save_data["player_pos"] = [int(ep[0]), int(ep[1])]
    return True


def resolve_continue_spawn(save_data, world_data, config=None):
    """이어하기 본편 스폰 맵·좌표.

    data.py CONTINUE_SPAWN_MODE:
      - "save" (기본): 세이브 current_map + player_pos (종료 직전 위치)
      - "map_start": 세이브 current_map + 해당 맵 world_data.start_pos
    반환: {"current_map": str, "player_pos": [x, y]} 또는 None(맵 없음).
    """
    cfg = config if isinstance(config, dict) else CONFIG
    if not isinstance(save_data, dict):
        return None
    mid = save_data.get("current_map")
    if not mid:
        return None
    mid = str(mid)
    try:
        mode = str(cfg.get("CONTINUE_SPAWN_MODE", "save") or "save").strip().lower()
    except Exception:
        mode = "save"
    wd = world_data if isinstance(world_data, dict) else {}
    m = wd.get(mid) if isinstance(wd.get(mid), dict) else {}
    start_pos = m.get("start_pos", [100, 100]) if isinstance(m, dict) else [100, 100]
    try:
        sp = [float(start_pos[0]), float(start_pos[1])]
    except (TypeError, ValueError, IndexError):
        sp = [100.0, 100.0]

    if mode in ("map_start", "start_pos", "map_default", "default"):
        return {"current_map": mid, "player_pos": [int(sp[0]), int(sp[1])]}

    # save: 종료 좌표 우선, 없으면 맵 start_pos
    pp = save_data.get("player_pos")
    if isinstance(pp, (list, tuple)) and len(pp) >= 2:
        try:
            return {
                "current_map": mid,
                "player_pos": [int(pp[0]), int(pp[1])],
            }
        except (TypeError, ValueError):
            pass
    return {"current_map": mid, "player_pos": [int(sp[0]), int(sp[1])]}


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


def eval_session_vars(flow, extra=None) -> dict:
    """
    조건식·존·interact 에 넘기는 세션 딕셔너리.
    gamestart(부팅 단계) + RESULT session:true 로 쓴 값.
    세이브 파일에는 안 들어감 — 프로세스 재시작 시 비어 있음.
    """
    out = {}
    if flow is not None:
        try:
            out["gamestart"] = getattr(flow, "boot_phase", None)
        except Exception:
            pass
        sp = getattr(flow, "session_progress", None)
        if isinstance(sp, dict):
            out.update(sp)
    if extra:
        out.update(extra)
    return out


def _zone_cond_values_equal(lhs, rhs) -> bool:
    """존 conditions 값 비교 — 숫자 1 과 \"1\" 을 같게 봄."""
    if lhs == rhs:
        return True
    try:
        if float(lhs) == float(rhs):
            return True
    except (TypeError, ValueError):
        pass
    return str(lhs) == str(rhs)


def zone_conditions_ok(zone: dict, save_data: dict, session_vars=None) -> bool:
    """
    event_zones / presence_zones 의 conditions 가 현재 진행과 맞는지.
    세션 변수가 같은 키의 세이브 값을 덮어쓴다 (RESULT session:true).
    지원:
      mainprogress, min_laugh_point
      when/condition/expr — 전체 조건식
      그 외 키 — ctx[key] == value (progress_flower1_ground: 1 등)
    """
    if not isinstance(zone, dict):
        return True
    cond = zone.get("conditions")
    if not cond:
        return True
    if not isinstance(cond, dict):
        return True
    ctx = build_eval_ctx(save_data, session_vars)
    mp = cond.get("mainprogress")
    if mp not in (None, ""):
        if str(mp) != str(ctx.get("mainprogress", "") or ""):
            return False
    if "min_laugh_point" in cond:
        try:
            if int(ctx.get("laugh_point", 0) or 0) < int(cond.get("min_laugh_point") or 0):
                return False
        except (TypeError, ValueError):
            return False
    expr = cond.get("when") or cond.get("condition") or cond.get("expr")
    if expr not in (None, "") and not evaluate_global_condition(expr, ctx):
        return False
    for k, v in cond.items():
        if k in ("mainprogress", "min_laugh_point", "when", "condition", "expr"):
            continue
        lhs = ctx.get(k)
        if lhs is None and str(k).startswith("progress_"):
            lhs = 0
        if not _zone_cond_values_equal(lhs, v):
            return False
    return True


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


def _split_condition_logic_clauses(expr: str, word: str) -> list:
    """조건식 and/or (또는 && / ||) 분리. 따옴표 안은 쪼개지 않음."""
    s = str(expr or "")
    if not s.strip():
        return []
    word = str(word or "").strip().lower()
    if word not in ("and", "or"):
        return [s.strip()]
    out = []
    buf = []
    i = 0
    n = len(s)
    quote = None
    while i < n:
        ch = s[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if word == "and" and s.startswith("&&", i):
            piece = "".join(buf).strip()
            if piece:
                out.append(piece)
            buf = []
            i += 2
            continue
        if word == "or" and s.startswith("||", i):
            piece = "".join(buf).strip()
            if piece:
                out.append(piece)
            buf = []
            i += 2
            continue
        m = re.match(rf"(?i)\s+{re.escape(word)}\s+", s[i:])
        if m:
            piece = "".join(buf).strip()
            if piece:
                out.append(piece)
            buf = []
            i += m.end()
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out or [s.strip()]


def _parse_condition_list(raw: str, save_data: dict) -> list:
    """in/notin 우변: 1005,1006 또는 (1005, 1006)."""
    s = str(raw or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "()[]":
        s = s[1:-1].strip()
    parts = []
    buf = []
    quote = None
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            piece = "".join(buf).strip()
            if piece:
                parts.append(piece)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return [_parse_condition_rhs(p, save_data) for p in parts]


def _eval_condition_atom(expr: str, eval_ctx: dict) -> bool:
    """단일 비교. in/notin 은 콤마 목록 멤버십."""
    s = str(expr or "").strip()
    if not s:
        return True
    s = re.sub(r"(?i)\s+not\s+in\s+", " notin ", s)
    m = re.match(
        r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(==|!=|>=|<=|>|<|notin|in)\s*(.+)\s*$",
        s,
        re.I,
    )
    if not m:
        return False
    key, op, rhs_raw = m.group(1), m.group(2).lower(), m.group(3).strip()
    lhs = eval_ctx.get(key)
    if lhs is None and str(key).startswith("progress_"):
        lhs = 0
    try:
        if op in ("in", "notin"):
            items = _parse_condition_list(rhs_raw, eval_ctx)
            hit = any(lhs == it for it in items)
            return (not hit) if op == "notin" else hit
        rhs = _parse_condition_rhs(rhs_raw, eval_ctx)
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


def evaluate_global_condition(condition_expr, eval_ctx: dict) -> bool:
    """
    eval_ctx 기준 조건식. 비어 있으면 True.
    예:
      mainprogress == "010100"
      progress_flower1_1 notin 1005,1006
      progress_x != 1 and progress_x != 2
      flag == 1 or progress_x == 1001
    gamestart 는 세이브가 아니라 session_vars 로만 쓰는 것을 권장.
    and 가 or 보다 먼저 묶임 (a or b and c → a or (b and c)).
    """
    if condition_expr is None:
        return True
    s = normalize_condition_expr(condition_expr)
    if not s:
        return True
    s = re.sub(r"(?i)\s+not\s+in\s+", " notin ", s)
    or_parts = _split_condition_logic_clauses(s, "or")
    if not or_parts:
        return True
    for or_clause in or_parts:
        and_parts = _split_condition_logic_clauses(or_clause, "and")
        if and_parts and all(_eval_condition_atom(p, eval_ctx) for p in and_parts):
            return True
    return False


def condition_step_chain_mode(step) -> str:
    """
    CONDITION 분기 방식. 기본 if.

    [작성 원칙]
      if   — 독립 if. 앞에서 맞았어도 다음 조건도 평가한다.
             물뿌리개처럼 앞 RESULT 가 다음 조건을 열어 주는 연쇄에 쓴다.
      elif — 같은 체인에서 앞 if/elif 가 이미 맞으면 이 블록은 건너뛴다.
             대화 디스패처처럼 '맞는 것 하나만' 탈 때 2번째부터 elif.
      else — 앞이 전부 거짓일 때만 본문. 조건식은 비워도 됨.

    [공통]
      각 본문은 CONDITION_SKIP 으로 닫는다.
      분기 뒤에 공통 스텝(RESULT 등)이 있으면 마지막 SKIP 다음에 둔다.
      CALL_EVENT 는 서브루틴 — 끝나면 부모의 다음 스텝(보통 SKIP)으로 돌아온다.

    JSON: { "elif": true } / { "else": true }  또는  "chain": "elif"|"else"
    """
    if not isinstance(step, dict):
        return "if"
    raw_else = step.get("else")
    if raw_else is True or raw_else == 1:
        return "else"
    if isinstance(raw_else, str) and raw_else.strip().lower() in ("1", "true", "yes", "on"):
        return "else"
    raw_elif = step.get("elif")
    if raw_elif is True or raw_elif == 1:
        return "elif"
    if isinstance(raw_elif, str) and raw_elif.strip().lower() in ("1", "true", "yes", "on"):
        return "elif"
    chain = str(step.get("chain") or step.get("cond_chain") or "").strip().lower()
    if chain in ("elif", "elseif", "else_if"):
        return "elif"
    if chain == "else":
        return "else"
    return "if"


def evaluate_event_step_condition(step: dict, eval_ctx: dict) -> bool:
    """
    이벤트 스텝 CONDITION 용.
    - condition(또는 expr): 전체 식 — progress_wateringcan == 1002
    - var + op: 축약 — var=progress_wateringcan, op=>=100 또는 ==1002
    둘 다 비어 있으면 True(통과). else 분기는 조건 없이 이 경로를 탄다.
    """
    if not isinstance(step, dict):
        return True
    full = str(step.get("condition") or step.get("expr") or "").strip()
    var = str(step.get("var") or "").strip()
    op_part = str(step.get("op") or "").strip()
    if full:
        return evaluate_global_condition(full, eval_ctx)
    if var and op_part:
        if re.match(r"(?i)^(==|!=|>=|<=|>|<|notin|in)", op_part.strip()):
            return evaluate_global_condition(f"{var} {op_part}", eval_ctx)
    return True


def evaluate_zone_block_condition(block, eval_ctx: dict) -> bool:
    """
    event_zones[].block 조건이 참이면 True (벽으로 막힘).

    지원 형태:
      true / 1 / "true"           → 항상 막음
      { "when": "flag != 1" }     → 전체 식 (condition/expr 도 동일)
      { "var":"flag", "op":"!=", "val":1 }  → 변수·연산자·값
    """
    if block is True or block == 1:
        return True
    if isinstance(block, (int, float)) and int(block) == 1:
        return True
    if isinstance(block, str):
        s = block.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
        # 문자열이면 조건식으로 해석
        return evaluate_global_condition(block, eval_ctx)
    if not isinstance(block, dict):
        return False
    # enabled:false 면 끔
    en = block.get("enabled", block.get("on", True))
    if isinstance(en, str):
        if en.strip().lower() in ("0", "false", "f", "no", "n", "off"):
            return False
    elif en is False or en == 0:
        return False

    full = str(block.get("when") or block.get("condition") or block.get("expr") or "").strip()
    if full:
        return evaluate_global_condition(full, eval_ctx)

    var = str(block.get("var") or block.get("key") or "").strip()
    op = str(block.get("op") or block.get("operator") or "").strip()
    if "val" in block:
        val = block.get("val")
    elif "value" in block:
        val = block.get("value")
    else:
        val = None
    if not var or not op:
        return False
    # op 가 "==" 만 있고 val 별도 → "!= 1" 형태로 합침
    if re.match(r"(?i)^(==|!=|>=|<=|>|<|notin|in)$", op):
        if val is None:
            return False
        op_part = f"{op} {val}"
    elif re.match(r"(?i)^(==|!=|>=|<=|>|<|notin|in)", op):
        # 이미 "!= 1" 형태
        op_part = op if val is None else (op if re.search(r"\d|\"|'", op) else f"{op} {val}")
    else:
        return False
    return evaluate_event_step_condition({"var": var, "op": op_part}, eval_ctx)


def collect_active_zone_blocks(world_data, map_id, save_data, session_vars=None) -> list:
    """
    현재 맵에서 block 조건이 참인 event_zones.
    반환: [{"rect":[x,y,w,h], "say":str, "who":str, "zone_index":int}, ...]
    """
    out = []
    try:
        m = (world_data or {}).get(str(map_id), {}) or {}
    except Exception:
        return out
    zones = m.get("event_zones") or []
    if not zones:
        return out
    ctx = build_eval_ctx(save_data, session_vars)
    for zi, z in enumerate(zones):
        if not isinstance(z, dict):
            continue
        block = z.get("block")
        if block is None:
            continue
        try:
            if not evaluate_zone_block_condition(block, ctx):
                continue
        except Exception:
            continue
        rect = z.get("rect")
        if not (isinstance(rect, (list, tuple)) and len(rect) >= 4):
            continue
        try:
            zx, zy, zw, zh = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
        except (TypeError, ValueError):
            continue
        if zw <= 0 or zh <= 0:
            continue
        say = ""
        who = "player"
        if isinstance(block, dict):
            say = str(block.get("say") or block.get("text") or block.get("message") or "").strip()
            who = str(block.get("who") or block.get("speaker") or "player").strip() or "player"
        if not say:
            say = str(z.get("block_say") or z.get("block_text") or "").strip()
        if z.get("block_who"):
            who = str(z.get("block_who") or "player").strip() or "player"
        out.append(
            {
                "rect": [zx, zy, zw, zh],
                "say": say,
                "who": who,
                "zone_index": int(zi),
                "name": str(z.get("name") or ""),
            }
        )
    return out


def collect_active_zone_block_rects(world_data, map_id, save_data, session_vars=None) -> list:
    """호환: rect 만 리스트로. 신규 코드는 collect_active_zone_blocks 권장."""
    return [list(b["rect"]) for b in collect_active_zone_blocks(world_data, map_id, save_data, session_vars)]


def point_in_zone_block_rects(x, y, rects) -> bool:
    """월드 좌표 (x,y) 가 block rect 안이면 True. rects 는 [x,y,w,h] 또는 {rect:[...]}."""
    return find_zone_block_at(x, y, rects) is not None


def find_zone_block_at(x, y, blocks, *, pad: float = 0.0):
    """
    blocks 안 어느 항목에 (x,y) 가 들어가면 그 항목 반환.
    pad>0 이면 rect 를 바깥으로 키워 '접촉' 판정.
    """
    try:
        px, py = float(x), float(y)
    except (TypeError, ValueError):
        return None
    try:
        p = max(0.0, float(pad))
    except (TypeError, ValueError):
        p = 0.0
    for b in blocks or []:
        if isinstance(b, dict):
            r = b.get("rect")
            item = b
        else:
            r = b
            item = {"rect": b}
        if not (isinstance(r, (list, tuple)) and len(r) >= 4):
            continue
        try:
            zx, zy, zw, zh = float(r[0]), float(r[1]), float(r[2]), float(r[3])
        except (TypeError, ValueError):
            continue
        if zw <= 0 or zh <= 0:
            continue
        if (zx - p) <= px <= (zx + zw + p) and (zy - p) <= py <= (zy + zh + p):
            return item
    return None


def try_trigger_zone_block_say(flow, ev_mgr, player, map_id, session_vars=None) -> bool:
    """
    BLOCK 벽에 막혀 이동이 실패했을 때(player._pending_zone_block_bump) 안내 대사.
    같은 존에 붙어 있는 동안 1회만, 떨어지면 다시 가능.
    """
    if flow is None or ev_mgr is None or player is None:
        return False
    if getattr(ev_mgr, "active_event", None) or bool(getattr(ev_mgr, "is_talking", False)):
        try:
            player._pending_zone_block_bump = None
        except Exception:
            pass
        return False

    bump = getattr(player, "_pending_zone_block_bump", None)
    try:
        player._pending_zone_block_bump = None
    except Exception:
        pass

    try:
        from data import CONFIG

        pad = float(CONFIG.get("ZONE_BLOCK_SAY_PAD_PX", 8) or 8)
    except Exception:
        pad = 8.0

    blocks = collect_active_zone_blocks(
        getattr(flow, "world_data", None),
        map_id,
        getattr(flow, "save_data", None),
        session_vars=session_vars,
    )
    # 떨어져 나간 존은 다시 말할 수 있게
    now_near = set()
    try:
        px, py = float(player.pos[0]), float(player.pos[1])
    except Exception:
        px = py = 0.0
    for b in blocks:
        if find_zone_block_at(px, py, [b], pad=pad) is not None:
            try:
                now_near.add(int(b.get("zone_index")))
            except Exception:
                pass
    said = getattr(flow, "_zone_block_say_said", None)
    if not isinstance(said, set):
        said = set()
    said = {zi for zi in said if zi in now_near}
    flow._zone_block_say_said = said

    if not isinstance(bump, dict):
        return False
    say = str(bump.get("say") or "").strip()
    if not say:
        return False
    try:
        zi = int(bump.get("zone_index"))
    except Exception:
        zi = None
    if zi is not None and zi in said:
        return False

    who = str(bump.get("who") or "player").strip() or "player"
    try:
        sm = getattr(player, "stop_moving", None)
        if callable(sm):
            sm()
    except Exception:
        pass
    try:
        ev_mgr.start_free_say({"who": who, "text": say, "show_name": True})
    except Exception:
        return False
    if zi is not None:
        said.add(zi)
        flow._zone_block_say_said = said
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


def normalize_interact_spec(spec) -> dict:
    """
    interact dict 정리.
    작성 편의: 최상위 event_id(+condition/when) 만 있으면 bindings 한 줄로 펼친다.
    대화·FX·분기는 events.json 스텝에서 편집하는 것이 권장 모델.
    """
    if not isinstance(spec, dict):
        return {}
    out = dict(spec)
    binds = out.get("bindings")
    if isinstance(binds, list) and binds:
        return out
    eid = str(out.get("event_id") or "").strip()
    if not eid:
        return out
    cond = str(out.get("condition") or out.get("when") or "").strip()
    try:
        pri = int(out.get("priority", 100))
    except (TypeError, ValueError):
        pri = 100
    row = {"event_id": eid, "priority": pri}
    if cond:
        row["condition"] = cond
    out["bindings"] = [row]
    return out


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
        merged = _deep_merge(base, inst)
    else:
        merged = copy.deepcopy(base)
    return normalize_interact_spec(merged)


def build_obj_def(name: str, world_entry=None) -> dict:
    """
    object_defs 타입 + world_data 인스턴스 병합.
    build_npc_def(char_behavior) 와 동일하게 spawn_state / progress_apply 를 합칩니다.
    """
    from char_behavior import _deep_merge

    base = dict(OBJ_ASSETS.get(name, {}) or {})
    entry = world_entry or {}
    merged = _deep_merge(base, entry.get("overrides") or {})
    if base.get("spawn_state") or entry.get("spawn_state"):
        merged["spawn_state"] = _deep_merge(
            base.get("spawn_state") or {}, entry.get("spawn_state") or {}
        )
    if entry.get("progress_apply"):
        merged["progress_apply"] = list(entry["progress_apply"])
    elif base.get("progress_apply"):
        merged["progress_apply"] = list(base["progress_apply"])
    return merged


def binding_has_inline_action(binding: dict) -> bool:
    """
    interact.binding 이 events.json 없이 state/after 만으로 동작하는지.
    try_start_interact_event 인라인 분기 판정용.
    """
    if not isinstance(binding, dict):
        return False
    if binding.get("after"):
        return True
    st = binding.get("state")
    if isinstance(st, dict) and st:
        return True
    inline_keys = (
        "visible",
        "spawn",
        "anim",
        "state",
        "anim_mode",
        "change_to",
        "behavior_mode",
        "behavior",
        "dir",
        "entity_fx",
    )
    return any(k in binding for k in inline_keys)


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


def pick_interact_binding(bindings, eval_ctx: dict, events_catalog: dict):
    """
    상호작용 binding 1개 선택. event_id 또는 state/after 인라인 액션.
    priority 오름차순, 같으면 event_id 문자열.
    """
    candidates = []
    for b in bindings or []:
        if not isinstance(b, dict):
            continue
        if not evaluate_global_condition(b.get("condition"), eval_ctx):
            continue
        eid = str(b.get("event_id") or "").strip()
        inline = binding_has_inline_action(b)
        if eid and eid not in events_catalog:
            continue
        if not eid and not inline:
            continue
        try:
            pr = int(b.get("priority", 100))
        except (TypeError, ValueError):
            pr = 100
        sort_key = eid or "__inline__"
        candidates.append((pr, sort_key, b))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]


def pick_interact_event(bindings, eval_ctx: dict, events_catalog: dict):
    """
    상호작용 시 progress 등 조건에 맞는 events.json 이벤트 1개 선택.
    pick_sync_events / pick_global_auto_event 와 동일: priority 오름차순, 같으면 event_id.
    """
    b = pick_interact_binding(bindings, eval_ctx, events_catalog)
    if not b:
        return None
    eid = str(b.get("event_id") or "").strip()
    return eid if eid else None


def entity_interact_spec(entity) -> dict:
    """런타임 엔티티(FieldItem / NPC)에서 병합된 interact dict."""
    if entity is None:
        return {}
    spec = getattr(entity, "interact_spec", None)
    if isinstance(spec, dict):
        return normalize_interact_spec(spec)
    cdef = getattr(entity, "char_def", None)
    if isinstance(cdef, dict):
        return normalize_interact_spec(dict(cdef.get("interact") or {}))
    return {}


def interact_spec_enabled(spec) -> bool:
    """
    interact.enabled 기본값은 False.
    JSON/에디터에서 enabled: true 를 명시한 경우에만 클릭·이벤트 상호작용 후보.
    """
    if not isinstance(spec, dict):
        return False
    return spec.get("enabled") is True


def entity_is_interact_visible(entity) -> bool:
    """
    화면에 보이는 엔티티만 상호작용(클릭·대화·안내 아이콘) 후보.
    TUNE visible / spawn visible / PLACE remove / 페이드 퇴장(alpha=0) 으로
    숨긴 NPC·오브젝트는 발 위치에 서도 푸쉬버튼이 뜨지 않고 동작도 안 한다.
    """
    if entity is None:
        return False
    if not bool(getattr(entity, "is_visible", True)):
        return False
    try:
        a = int(getattr(entity, "alpha", 255))
    except (TypeError, ValueError):
        a = 255
    return a > 0


def entity_interact_enabled(entity) -> bool:
    """enabled 가 명시적 true 이고 bindings(이벤트 또는 인라인 state/after)가 있으면 상호작용 후보."""
    if not entity_is_interact_visible(entity):
        return False
    spec = entity_interact_spec(entity)
    if not interact_spec_enabled(spec):
        return False
    binds = spec.get("bindings") or []
    if not binds:
        return False
    for b in binds:
        if not isinstance(b, dict):
            continue
        if str(b.get("event_id") or "").strip():
            return True
        if binding_has_inline_action(b):
            return True
    return False


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


def iter_save_progress_vars(save_data, session_progress=None):
    """
    세이브에 들어 있는 mainprogress / progress_* (이름 정렬, mainprogress 먼저).
    session_progress 가 있으면 같은 키는 세션 값으로 덮어 표시하고 (session) 을 붙인다.
    O키 HUD 오버레이에서 현재 값을 나열할 때 사용.
    """
    sd = save_data if isinstance(save_data, dict) else {}
    sp = session_progress if isinstance(session_progress, dict) else {}
    keys = []
    for k in sd:
        ks = str(k)
        if ks == "mainprogress" or ks.startswith("progress_"):
            keys.append(ks)
    for k in sp:
        ks = str(k)
        if ks == "mainprogress" or ks.startswith("progress_"):
            if ks not in keys:
                keys.append(ks)
    keys.sort(key=lambda v: (0 if v == "mainprogress" else 1, v.lower()))
    rows = []
    for k in keys:
        if k in sp:
            v = sp.get(k)
            if v is None:
                v = ""
            rows.append(f"{k}: {v} (session)")
        else:
            v = sd.get(k)
            if v is None:
                v = ""
            rows.append(f"{k}: {v}")
    return rows


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


def _flow_find_event_section(eid: str, event_data: dict) -> str:
    eid = str(eid or "").strip()
    for sec in ("LOCAL", "GLOBAL", "SYNC"):
        if eid in (event_data.get(sec) or {}):
            return sec
    return ""


def _flow_entity_catalog_entry(name, kind: str, *, char_assets=None, obj_assets=None) -> dict:
    """char_defs / object_defs 타입 한 개 — binding·대사 연결 요약 (맵 인스턴스 없음)."""
    name = str(name or "").strip()
    kind = "npc" if str(kind or "").lower() in ("npc", "char") else "obj"
    info = ((char_assets if kind == "npc" else obj_assets) or {}).get(name, {}) or {}
    inter = info.get("interact") or {}
    binds = [b for b in (inter.get("bindings") or []) if isinstance(b, dict)]
    event_ids = set()
    link_count = 0
    for b in binds:
        eid = str(b.get("event_id") or "").strip()
        if eid:
            event_ids.add(eid)
        cond = str(b.get("condition") or "").strip()
        if eid or binding_has_inline_action(b) or cond:
            link_count += 1
    talk_n = 0
    if kind == "npc":
        talk = (info.get("talk") or {}) if isinstance(info.get("talk"), dict) else {}
        talk_n = len(talk.get("lines") or [])
        if talk.get("fallback"):
            talk_n += 1
    has_links = bool(event_ids) or link_count > 0 or talk_n > 0
    tag = "NPC" if kind == "npc" else "OBJ"
    return {
        "name": name,
        "kind": kind,
        "node": None,
        "event_ids": event_ids,
        "link_count": link_count + talk_n,
        "has_links": has_links,
        "label": f"{tag} {name}",
    }


def _flow_entity_runtime_entry(ent, kind: str) -> dict:
    """맵에 배치된 NPC/오브젝트 한 개 — 이벤트·binding·대사 연결 요약."""
    name = str(getattr(ent, "name", "") or "")
    spec = entity_interact_spec(ent)
    binds = [b for b in (spec.get("bindings") or []) if isinstance(b, dict)]
    event_ids = set()
    link_count = 0
    for b in binds:
        eid = str(b.get("event_id") or "").strip()
        if eid:
            event_ids.add(eid)
        cond = str(b.get("condition") or "").strip()
        if eid or binding_has_inline_action(b) or cond:
            link_count += 1
    talk_n = 0
    if kind == "npc":
        talk = (getattr(ent, "char_def", None) or {}).get("talk") or {}
        talk_n = len(talk.get("lines") or [])
        if talk.get("fallback"):
            talk_n += 1
    has_links = bool(event_ids) or link_count > 0 or talk_n > 0
    tag = "NPC" if kind == "npc" else "OBJ"
    return {
        "name": name,
        "kind": kind,
        "node": ent,
        "event_ids": event_ids,
        "link_count": link_count + talk_n,
        "has_links": has_links,
        "label": f"{tag} {name}",
    }


def collect_flow_entities_on_map(objs, npcs):
    """
    현재 맵에 배치된 캐릭터/오브젝트 중 이벤트·binding·대사와 연결된 항목.
    연결된 것이 하나도 없으면 맵 전체 목록을 반환(설정 추가용).
    """
    entries = []
    for n in npcs or []:
        entries.append(_flow_entity_runtime_entry(n, "npc"))
    for o in objs or []:
        entries.append(_flow_entity_runtime_entry(o, "obj"))
    linked = [e for e in entries if e["has_links"]]
    out = linked if linked else entries
    name_counts = {}
    for e in out:
        key = (e["kind"], e["name"])
        name_counts[key] = name_counts.get(key, 0) + 1
    for e in out:
        key = (e["kind"], e["name"])
        n = e.get("node")
        if name_counts.get(key, 0) > 1 and n is not None and hasattr(n, "pos"):
            try:
                e["label"] = f"{e['label']} @{int(n.pos[0])},{int(n.pos[1])}"
            except (TypeError, ValueError):
                pass
    out.sort(key=lambda x: (0 if x["kind"] == "npc" else 1, x["name"].lower()))
    return out


def build_entity_flow_diagram(
    entity_name,
    entity_kind,
    event_data,
    events_catalog,
    *,
    entity_node=None,
    char_assets=None,
    obj_assets=None,
):
    """
    FLOW 에디터: 캐릭터/오브젝트 → binding/대사 → 이벤트 → progress 결과.
    맵 인스턴스(entity_node)가 있으면 병합된 interact·char_def 기준.
    """
    entity_name = str(entity_name or "").strip()
    entity_kind = "npc" if str(entity_kind or "").lower() in ("npc", "char") else "obj"
    char_assets = char_assets or {}
    obj_assets = obj_assets or {}
    nodes: dict = {}
    edges: list = []
    seen_edges: set = set()

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

    def _add_edge(frm, to, label=""):
        if not frm or not to or frm == to:
            return
        key = (frm, to, str(label or "")[:36])
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"from": frm, "to": to, "label": key[2], "cycle": False})

    on_map = entity_node is not None
    if on_map:
        spec = entity_interact_spec(entity_node)
        cdef = (
            getattr(entity_node, "char_def", None)
            if entity_kind == "npc"
            else getattr(entity_node, "obj_def", None)
        )
        cdef = cdef if isinstance(cdef, dict) else {}
    else:
        info = (char_assets if entity_kind == "npc" else obj_assets).get(entity_name, {}) or {}
        spec = merge_interact_spec(info, {})
        cdef = info

    ek_hit = "char" if entity_kind == "npc" else "obj"
    tag = "NPC" if entity_kind == "npc" else "OBJ"
    ent_id = _nid("ent", f"{entity_kind}:{entity_name}")
    _add_node(
        ent_id,
        "entity",
        entity_name,
        f"{tag} · {'맵' if on_map else '타입'}",
        entity_name,
        {
            "action": "entity",
            "entity": entity_name,
            "entity_kind": ek_hit,
            "on_map": on_map,
        },
    )

    bind_i = 0
    bindings = [b for b in (spec.get("bindings") or []) if isinstance(b, dict)]

    def _prio(b):
        try:
            return int(b.get("priority", 0) or 0)
        except (TypeError, ValueError):
            return 0

    bindings.sort(key=_prio, reverse=True)

    for b in bindings:
        bind_i += 1
        cond = str(b.get("condition") or "").strip() or "(항상)"
        bid = _nid("bind", str(bind_i))
        eid = str(b.get("event_id") or "").strip()
        if eid:
            sub = f"→ {eid}"[:24]
        elif binding_has_inline_action(b):
            sub = "인라인 state/after"
        else:
            sub = "binding"
        _add_node(
            bid,
            "bind",
            cond[:28],
            sub,
            bind_i,
            {
                "action": "binding",
                "entity": entity_name,
                "entity_kind": ek_hit,
                "binding_index": bind_i,
                "on_map": on_map,
            },
        )
        _add_edge(ent_id, bid, "상호작용")

        if eid:
            ev_id = _nid("evt", eid)
            sec = _flow_find_event_section(eid, event_data)
            ev_data = None
            if sec:
                ev_data = (event_data.get(sec) or {}).get(eid)
            if not isinstance(ev_data, dict):
                ev_data = (events_catalog or {}).get(eid)
            ev_title = ""
            if isinstance(ev_data, dict):
                ev_title = str(ev_data.get("title") or "")[:24]
            _add_node(
                ev_id,
                "event",
                eid,
                f"[{sec}]" if sec else "이벤트",
                eid,
                {"action": "event", "event_id": eid, "section": sec},
            )
            _add_edge(bid, ev_id, "실행")
            res = ev_data.get("result") if isinstance(ev_data, dict) else None
            if isinstance(res, dict):
                prog = [
                    k
                    for k in res
                    if k == "mainprogress" or str(k).startswith("progress_")
                ]
                if prog:
                    for pk in prog[:4]:
                        sv = progress_value_key(res.get(pk))
                        if not sv:
                            continue
                        sid = _nid("state", f"{pk}={sv}")
                        _add_node(sid, "state", str(pk)[:28], f"= {sv}", sv, {})
                        _add_edge(ev_id, sid, "result")
                elif res:
                    sid = _nid("state", "result")
                    _add_node(sid, "state", "result", str(res)[:24], 0, {})
                    _add_edge(ev_id, sid, "result")
            if ev_title:
                nodes[ev_id]["sublabel"] = ev_title[:24]
        elif binding_has_inline_action(b):
            after = b.get("after")
            if isinstance(after, dict):
                for pk, pv in after.items():
                    if pk == "mainprogress" or str(pk).startswith("progress_"):
                        sv = progress_value_key(pv)
                        sid = _nid("state", f"{pk}={sv}")
                        _add_node(sid, "state", str(pk)[:28], f"= {sv}", sv, {})
                        _add_edge(bid, sid, "after")

    if entity_kind == "npc":
        talk = cdef.get("talk") or {}
        for i, ln in enumerate(talk.get("lines") or []):
            if not isinstance(ln, dict):
                continue
            bind_i += 1
            when = str(ln.get("when") or "").strip() or "(항상)"
            say = ln.get("say") or {}
            txt = str(say.get("text") or "").strip()[:18] or f"line{i+1}"
            bid = _nid("bind", f"t{i}")
            _add_node(
                bid,
                "bind",
                f"대사: {txt}",
                when[:24],
                f"t{i}",
                {
                    "action": "binding",
                    "entity": entity_name,
                    "entity_kind": "char",
                    "binding_index": bind_i,
                    "talk_line": i,
                    "on_map": on_map,
                },
            )
            _add_edge(ent_id, bid, "대화")
            after = ln.get("after")
            if isinstance(after, dict):
                for pk, pv in after.items():
                    if pk == "mainprogress" or str(pk).startswith("progress_"):
                        sv = progress_value_key(pv)
                        sid = _nid("state", f"{pk}={sv}")
                        _add_node(sid, "state", str(pk)[:28], f"= {sv}", sv, {})
                        _add_edge(bid, sid, "after")

    note = ""
    if bind_i == 0:
        note = "bindings·대사 없음 — 상자 클릭 또는 우측 버튼으로 설정"

    return {
        "mode": "entity",
        "entity_name": entity_name,
        "entity_kind": entity_kind,
        "on_map": on_map,
        "var": entity_name,
        "note": note,
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def _flow_zone_entry(zone, zone_index: int, map_id: str) -> dict:
    """맵 event_zones 한 개 — FLOW 목록·차트용."""
    zone = zone if isinstance(zone, dict) else {}
    zi = int(zone_index)
    zname = str(zone.get("name") or f"zone_{zi + 1}").strip()
    eid = str(zone.get("event_id") or "").strip()
    event_ids = {eid} if eid else set()
    return {
        "name": zname,
        "kind": "zone",
        "zone_index": zi,
        "zone_data": dict(zone),
        "map_id": str(map_id or ""),
        "node": None,
        "event_ids": event_ids,
        "link_count": 1 if eid else 0,
        "has_links": bool(eid),
        "label": f"BOX {zname}",
    }


def build_zone_flow_diagram(
    zone,
    map_id,
    zone_index,
    event_data,
    events_catalog,
):
    """FLOW — 이벤트 박스 → 트리거/조건 → 이벤트 → progress 결과."""
    zone = zone if isinstance(zone, dict) else {}
    map_id = str(map_id or "")
    zi = int(zone_index)
    zname = str(zone.get("name") or f"zone_{zi + 1}").strip()
    eid = str(zone.get("event_id") or "").strip()
    trigger = str(zone.get("trigger") or "contact_player")
    target = str(zone.get("target") or "").strip()
    cond = zone.get("conditions") if isinstance(zone.get("conditions"), dict) else {}

    nodes: dict = {}
    edges: list = []
    seen_edges: set = set()

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

    def _add_edge(frm, to, label=""):
        if not frm or not to or frm == to:
            return
        key = (frm, to, str(label or "")[:36])
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"from": frm, "to": to, "label": key[2], "cycle": False})

    zid = _nid("zone", f"{map_id}:{zi}:{zname}")
    _add_node(
        zid,
        "zone",
        zname,
        f"맵 {map_id}"[:24] if map_id else "이벤트 박스",
        zname,
        {
            "action": "zone",
            "zone_name": zname,
            "map_id": map_id,
            "zone_index": zi,
        },
    )

    cond_bits = [trigger]
    if target:
        cond_bits.append(f"target={target}")
    mp = cond.get("mainprogress")
    if mp is not None and str(mp).strip():
        cond_bits.append(f'mp="{progress_value_key(mp)}"')
    mlp = cond.get("min_laugh_point")
    if mlp is not None and str(mlp).strip():
        cond_bits.append(f"laugh≥{mlp}")
    for ck, cv in cond.items():
        if ck in ("mainprogress", "min_laugh_point"):
            continue
        cond_bits.append(f"{ck}={cv}")

    cid = _nid("bind", "cond")
    _add_node(
        cid,
        "bind",
        " / ".join(cond_bits)[:28] or trigger,
        "트리거·조건",
        0,
        {
            "action": "zone",
            "zone_name": zname,
            "map_id": map_id,
            "zone_index": zi,
        },
    )
    _add_edge(zid, cid, "진입")

    note = ""
    if not eid:
        note = "event_id 없음 — 이벤트 박스 설정에서 연결하세요"
    else:
        ev_id = _nid("evt", eid)
        sec = _flow_find_event_section(eid, event_data)
        ev_data = None
        if sec:
            ev_data = (event_data.get(sec) or {}).get(eid)
        if not isinstance(ev_data, dict):
            ev_data = (events_catalog or {}).get(eid)
        ev_title = ""
        if isinstance(ev_data, dict):
            ev_title = str(ev_data.get("title") or "")[:24]
        _add_node(
            ev_id,
            "event",
            eid,
            f"[{sec}]" if sec else "이벤트",
            eid,
            {"action": "event", "event_id": eid, "section": sec},
        )
        _add_edge(cid, ev_id, "실행")
        res = ev_data.get("result") if isinstance(ev_data, dict) else None
        if isinstance(res, dict):
            prog = [
                k for k in res if k == "mainprogress" or str(k).startswith("progress_")
            ]
            if prog:
                for pk in prog[:4]:
                    sv = progress_value_key(res.get(pk))
                    if not sv:
                        continue
                    sid = _nid("state", f"{pk}={sv}")
                    _add_node(sid, "state", str(pk)[:28], f"= {sv}", sv, {})
                    _add_edge(ev_id, sid, "result")
            elif res:
                sid = _nid("state", "result")
                _add_node(sid, "state", "result", str(res)[:24], 0, {})
                _add_edge(ev_id, sid, "result")
        if ev_title:
            nodes[ev_id]["sublabel"] = ev_title[:24]

    return {
        "mode": "zone",
        "zone_name": zname,
        "map_id": map_id,
        "zone_index": zi,
        "entity_name": zname,
        "var": zname,
        "note": note,
        "nodes": list(nodes.values()),
        "edges": edges,
    }


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
    if not entity_is_interact_visible(entity):
        return False
    spec = entity_interact_spec(entity)
    if not interact_spec_enabled(spec):
        return False
    if spec.get("bindings"):
        return False
    return True


def entity_interact_asset_key(entity) -> str:
    """UI 아이콘 폴더명 — object_defs/char_defs 타입 키(name)."""
    return str(getattr(entity, "name", "") or "").strip()


def interact_prompt_set_from_spec(spec) -> str:
    """interact.prompt_set (또는 prompt.set) → 애니 세트 이름."""
    if not isinstance(spec, dict):
        return "pushbutton"
    raw = spec.get("prompt_set")
    if raw is None:
        raw = spec.get("prompt")
    if isinstance(raw, dict):
        raw = raw.get("set")
    ps = str(raw or "pushbutton").strip()
    return ps or "pushbutton"


def entity_interact_prompt_world_xy(entity):
    """
    안내 아이콘 월드 좌표 — 스프라이트 발(origin) 가로 중앙, 세로는 발 아래.
    interact.offset(접근 거리 원 중심)과 분리해 오브젝트에 겹치지 않게 둔다.
    """
    op = getattr(entity, "origin_pos", None) or getattr(entity, "pos", None)
    if not op:
        return None
    spec = entity_interact_spec(entity)
    try:
        default_offy = float(CONFIG.get("INTERACT_PROMPT_OFFSET_Y_PX", 14) or 14)
    except (TypeError, ValueError):
        default_offy = 14.0
    try:
        offx = float(spec.get("prompt_offset_x", 0) or 0)
    except (TypeError, ValueError):
        offx = 0.0
    try:
        offy = float(spec.get("prompt_offset_y", default_offy))
    except (TypeError, ValueError):
        offy = default_offy
    return float(op[0]) + offx, float(op[1]) + offy


def entity_in_interact_range(entity, player, *, is_npc: bool = False) -> bool:
    """플레이어가 interact.range 안에 있는지 (anchor 기준)."""
    anc = entity_interact_anchor_xy(entity)
    if not anc or player is None:
        return False
    try:
        default = float(
            CONFIG.get("NPC_INTERACT_RANGE", 48)
            if is_npc
            else CONFIG.get("OBJECT_INTERACT_RANGE", 16)
        )
    except (TypeError, ValueError):
        default = 48.0 if is_npc else 16.0
    rng = entity_interact_range(entity, default=default)
    try:
        return math.dist(player.pos, anc) < rng
    except (TypeError, ValueError):
        return False


def entity_interact_prompt_available(
    entity,
    flow,
    events_catalog: dict,
    map_id: str,
    player_pos,
    *,
    session_vars=None,
) -> bool:
    """
    거리 안내 아이콘을 띄울 상호작용이 있는지.
    bindings 조건·NPC 대화·들기( bindings 없는 enabled ) 중 현재 만족하는 것이 있을 때 True.
    """
    spec = entity_interact_spec(entity)
    if not interact_spec_enabled(spec):
        return False
    if not entity_is_interact_visible(entity):
        return False
    if spec.get("prompt_enabled") is False:
        return False
    ctx = build_eval_ctx(flow.save_data if flow else {}, session_vars)
    ctx["map_id"] = str(map_id or "")
    ctx["npc_name"] = str(getattr(entity, "name", "") or "")
    # 이벤트 bindings 우선 (대화·분기·FX 는 events.json)
    if entity_interact_enabled(entity):
        if pick_interact_binding(spec.get("bindings"), ctx, events_catalog):
            return True
    if getattr(entity, "char_def", None):
        from char_behavior import npc_interact_enabled, pick_talk_line

        # 구형 talk.lines — bindings 가 없을 때만 안내 아이콘
        if npc_interact_enabled(entity) and not (spec.get("bindings") or []):
            if pick_talk_line(entity, flow, map_id, player_pos, session_vars=session_vars):
                return True
    if entity_carry_click_allowed(entity):
        return True
    return False


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
    map_id=None,
) -> bool:
    """events_catalog 에서 ID 로 연출 시작(존/글로벌/상호작용 공통)."""
    ev = events_catalog.get(event_id)
    if not ev or ev_mgr.active_event:
        return False
    ev_mgr.reset_entity_event_zooms(player, npcs, objs)
    pos = getattr(player, "pos", None) if player is not None else None
    ev_mgr.start_event(
        ev.get("steps") or [],
        event_id,
        ev.get("result"),
        ev,
        is_sync=is_sync,
        map_id=map_id,
        player_pos=pos,
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
    binding = pick_interact_binding(spec.get("bindings"), ctx, events_catalog)
    if not binding:
        return False
    eid = str(binding.get("event_id") or "").strip()
    if player is not None:
        try:
            player.stop_moving()
        except Exception:
            pass
    if eid:
        ok = start_catalog_event(
            ev_mgr,
            events_catalog,
            eid,
            player,
            npcs,
            objs,
            field_tilt_snapshot,
            map_id=map_id,
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

    from char_behavior import apply_state_patch, apply_talk_after

    st = binding.get("state")
    if isinstance(st, dict):
        apply_state_patch(entity, st)
    else:
        row = {
            k: v
            for k, v in binding.items()
            if k not in ("condition", "event_id", "priority", "after", "entity_fx")
        }
        apply_state_patch(entity, row)
    if "entity_fx" in binding:
        from engine import apply_entity_visual_patch

        apply_entity_visual_patch(entity, binding.get("entity_fx"))
    apply_talk_after(binding.get("after"), flow, entity)
    if player is not None and getattr(entity, "char_def", None):
        try:
            from char_behavior import face_toward_player

            face_toward_player(entity, player)
        except Exception:
            pass
    print(f"[Interact] inline state via {getattr(entity, 'name', '?')}")
    return True


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


# ---------------------------------------------------------------------------
# PLACE persist — 이벤트 PLACE(persist:true)로 등장한 엔티티를 세이브에 유지
#   save_data["placed"] = [
#     {
#       "name": "girl1_k",          # CHAR_ASSETS / OBJ_ASSETS 키 (해석된 id)
#       "map_id": "bg_jjangpu",      # 현재 있는 맵 (travel 시 맵 전환마다 갱신)
#       "pos": [x, y],
#       "dir": "left"|"right",      # optional
#       "behavior": "follow"|{...}, # optional — ambient AI (BEHAVIOR/PLACE와 동일)
#       "follow_leader": "player",  # optional — FOLLOW 동행 리더 (세이브 보조)
#       "follow_dist": 40,          # optional — 슬롯 거리(px)
#       "follow_speed": 1.0,        # optional — 이동 속도 배율
#       "travel": true,             # optional — true면 맵 전환 시 플레이어 근처로 동행
#                                   #   (미지정 시 behavior=follow 이면 자동 travel)
#
# save_data["event_followers"]: FOLLOW 동행 전용 목록 (복원 소스). world_data 가 아님.
#   [ {"follower":"ally1","leader":"player","dist":40,"speed":1.0}, ... ]
#       "sprite_tilt"/"height"/"ysort"/"layer"/"zoom": optional 비주얼
#         zoom: 스프라이트 배율 (ENTITY_ZOOM_MIN~MAX, 기본 1, 2=두 배)
#       "entity_fx": optional — 세이브 시점 pulse/tint 등 (ENTITY_FX persist 결과)
#     },
#     ...
#   ]
#   · persist 없는 PLACE: 기존처럼 런타임 전용(맵 리로드 시 소멸)
#   · PLACE action:remove: 씬에서 제거 + placed 목록에서도 삭제
#   · CHANGE persist:true: placed.name 을 to 키로 바꿈 (안 바꾸면 재시작 시 옛 외형으로 복구)
# ---------------------------------------------------------------------------


def ensure_placed_list(save_data) -> list:
    """save_data['placed'] 리스트를 보장해 반환."""
    if not isinstance(save_data, dict):
        return []
    lst = save_data.get("placed")
    if not isinstance(lst, list):
        lst = []
        save_data["placed"] = lst
    return lst


def _placed_behavior_mode(beh) -> str:
    """placed.behavior → 내부 모드 문자열."""
    try:
        from char_behavior import normalize_behavior_mode
    except Exception:
        normalize_behavior_mode = None
    if isinstance(beh, dict):
        raw = beh.get("mode") or ""
    else:
        raw = beh or ""
    if normalize_behavior_mode:
        try:
            return normalize_behavior_mode(raw)
        except Exception:
            pass
    return str(raw or "").strip().lower()


def placed_entry_travels(entry) -> bool:
    """
    맵 전환 시 플레이어를 따라갈지.
    travel:true 명시, 또는 behavior 가 follow 이면 True.
    """
    if not isinstance(entry, dict):
        return False
    tr = entry.get("travel")
    if tr is True or (isinstance(tr, str) and tr.strip().lower() in ("1", "true", "t", "yes", "y", "on")):
        return True
    if tr is False or (isinstance(tr, str) and tr.strip().lower() in ("0", "false", "f", "no", "n", "off")):
        return False
    return _placed_behavior_mode(entry.get("behavior")) == "follow"


def _normalize_placed_behavior(behavior, *, radius=None, interval_ms=None):
    """세이브용 behavior 정규화 — str 또는 {mode,...}."""
    if behavior is None:
        return None
    if isinstance(behavior, dict):
        mode = str(behavior.get("mode") or "").strip()
        if not mode:
            return None
        out = {"mode": mode}
        rad = behavior.get("radius", radius)
        iv = behavior.get("interval_ms", interval_ms)
        if rad is not None:
            try:
                out["radius"] = float(rad)
            except (TypeError, ValueError):
                pass
        if iv is not None:
            try:
                out["interval_ms"] = int(iv)
            except (TypeError, ValueError):
                pass
        for k in ("trigger_range", "stop_dist"):
            if behavior.get(k) is not None:
                try:
                    out[k] = float(behavior.get(k))
                except (TypeError, ValueError):
                    pass
        return out
    mode = str(behavior or "").strip()
    if not mode:
        return None
    out = {"mode": mode}
    if radius is not None:
        try:
            out["radius"] = float(radius)
        except (TypeError, ValueError):
            pass
    if interval_ms is not None:
        try:
            out["interval_ms"] = int(interval_ms)
        except (TypeError, ValueError):
            pass
    return out


def find_placed_entry(save_data, name: str):
    """이름으로 placed 항목 찾기 (없으면 None)."""
    nm = str(name or "").strip()
    if not nm:
        return None
    for e in ensure_placed_list(save_data):
        if isinstance(e, dict) and str(e.get("name") or "").strip() == nm:
            return e
    return None


def mark_entity_placed_persist(ent, save_name=None) -> None:
    """PLACE/CHANGE persist 공통 — 세이브 키를 엔티티에 붙인다.

    _placed_save_name 은 CHANGE 가 persist 없이 외형(.name)만 바꿔도
    snapshot_placed_from_live 가 같은 엔티티를 찾게 한다.
    """
    if ent is None:
        return
    nm = str(save_name or getattr(ent, "name", "") or "").strip()
    try:
        ent._placed_persist = True
        if nm:
            ent._placed_save_name = nm
    except Exception:
        pass


def clear_entity_placed_persist(ent) -> None:
    if ent is None:
        return
    try:
        ent._placed_persist = False
        ent._placed_save_name = ""
    except Exception:
        pass


def rename_placed_entity(save_data, old_name: str, new_name: str) -> dict:
    """CHANGE persist: placed 항목 이름을 to 키로 맞춤.

    old 만 있으면 그 항목의 name 을 바꾸고, new 가 이미 있으면 old 를 지워
    재시작 시 옛·새 외형이 둘 다 스폰되지 않게 한다.
    둘 다 없으면 {} (호출부에서 upsert).
    """
    old_nm = str(old_name or "").strip()
    new_nm = str(new_name or "").strip()
    if not new_nm or new_nm.lower() == "player":
        return {}
    old = find_placed_entry(save_data, old_nm) if old_nm else None
    new = find_placed_entry(save_data, new_nm)
    if old is not None and (new is None or new is old):
        old["name"] = new_nm
        return old
    if old is not None and new is not None and old is not new:
        remove_placed_entity(save_data, old_nm)
        return new
    if new is not None:
        return new
    return {}


def _clear_placed_follow_meta(entry: dict) -> None:
    for k in ("follow_leader", "follow_dist", "follow_speed"):
        entry.pop(k, None)


def upsert_placed_entity(
    save_data,
    *,
    name: str,
    map_id: str,
    pos=None,
    dir=None,
    behavior=None,
    travel=None,
    follow_leader=None,
    follow_dist=None,
    follow_speed=None,
    sprite_tilt=None,
    height=None,
    ysort=None,
    layer=None,
    radius=None,
    interval_ms=None,
) -> dict:
    """
    PLACE persist / FOLLOW persist 공통 — save_data['placed'] 에 upsert.
    반환: 갱신된 entry dict.
    """
    nm = str(name or "").strip()
    if not nm or nm.lower() == "player":
        return {}
    lst = ensure_placed_list(save_data)
    entry = find_placed_entry(save_data, nm)
    if entry is None:
        entry = {"name": nm}
        lst.append(entry)
    mid = str(map_id or "").strip()
    if mid:
        entry["map_id"] = mid
    if pos is not None and isinstance(pos, (list, tuple)) and len(pos) >= 2:
        try:
            entry["pos"] = [float(pos[0]), float(pos[1])]
        except (TypeError, ValueError):
            pass
    if dir is not None:
        d = str(dir or "").strip().lower()
        if d in ("left", "l"):
            entry["dir"] = "left"
        elif d in ("right", "r"):
            entry["dir"] = "right"
    beh = _normalize_placed_behavior(behavior, radius=radius, interval_ms=interval_ms)
    if beh is not None:
        entry["behavior"] = beh
    if travel is not None:
        entry["travel"] = bool(travel)
    elif beh is not None and _placed_behavior_mode(beh) == "follow":
        # follow 이면 기본으로 맵 동행 (명시 travel:false 가 없을 때만)
        if "travel" not in entry:
            entry["travel"] = True
    if follow_leader is not None:
        fl = str(follow_leader or "").strip()
        if fl:
            entry["follow_leader"] = fl
        else:
            _clear_placed_follow_meta(entry)
    if follow_dist is not None:
        try:
            entry["follow_dist"] = float(follow_dist)
        except (TypeError, ValueError):
            pass
    if follow_speed is not None:
        try:
            entry["follow_speed"] = float(follow_speed)
        except (TypeError, ValueError):
            pass
    if beh is not None and _placed_behavior_mode(beh) not in ("follow",):
        _clear_placed_follow_meta(entry)
    if sprite_tilt is not None:
        try:
            entry["sprite_tilt"] = float(sprite_tilt)
        except (TypeError, ValueError):
            pass
    if height is not None:
        try:
            entry["height"] = float(height)
        except (TypeError, ValueError):
            pass
    if ysort is not None and str(ysort).strip():
        entry["ysort"] = str(ysort).strip()
    if layer is not None:
        try:
            entry["layer"] = int(float(layer))
        except (TypeError, ValueError):
            pass
    return entry


def remove_placed_entity(save_data, name: str) -> bool:
    """placed 목록에서 제거. 지웠으면 True."""
    nm = str(name or "").strip()
    if not nm or not isinstance(save_data, dict):
        return False
    lst = ensure_placed_list(save_data)
    before = len(lst)
    save_data["placed"] = [
        e for e in lst if not (isinstance(e, dict) and str(e.get("name") or "").strip() == nm)
    ]
    return len(save_data["placed"]) < before


def update_placed_behavior(save_data, name: str, behavior, *, radius=None, interval_ms=None, travel=None) -> bool:
    """이미 placed 인 엔티티의 behavior/travel 만 갱신. 없으면 False."""
    entry = find_placed_entry(save_data, name)
    if entry is None:
        return False
    beh = _normalize_placed_behavior(behavior, radius=radius, interval_ms=interval_ms)
    if beh is not None:
        entry["behavior"] = beh
        if travel is None and _placed_behavior_mode(beh) == "follow" and "travel" not in entry:
            entry["travel"] = True
        if _placed_behavior_mode(beh) not in ("follow",):
            _clear_placed_follow_meta(entry)
    if travel is not None:
        entry["travel"] = bool(travel)
    return True


def sync_event_followers_to_placed(save_data, followers) -> None:
    """ev_mgr._followers → placed follow_leader/dist/speed (세이브 직전, 기존 entry만)."""
    if not isinstance(save_data, dict) or not followers:
        return
    fol_map = {}
    for f in followers:
        if not isinstance(f, dict):
            continue
        nm = str(f.get("follower") or "").strip()
        if nm:
            fol_map[nm] = f
    for entry in ensure_placed_list(save_data):
        if not isinstance(entry, dict):
            continue
        nm = str(entry.get("name") or "").strip()
        f = fol_map.get(nm)
        if not f:
            continue
        entry["follow_leader"] = str(f.get("leader") or "player")
        try:
            entry["follow_dist"] = float(f.get("dist", 40))
        except (TypeError, ValueError):
            entry["follow_dist"] = 40.0
        try:
            entry["follow_speed"] = float(f.get("speed", 1.0))
        except (TypeError, ValueError):
            entry["follow_speed"] = 1.0
        # follow 모드·맵 동행 유지
        if _placed_behavior_mode(entry.get("behavior")) != "follow":
            entry["behavior"] = "follow"
        if "travel" not in entry:
            entry["travel"] = True


def dump_event_followers_list(followers) -> list:
    """세이브용 event_followers 배열 (이름·리더·거리·속도만)."""
    out = []
    for f in followers or []:
        if not isinstance(f, dict):
            continue
        nm = str(f.get("follower") or "").strip()
        if not nm:
            continue
        try:
            dist = float(f.get("dist", 40))
        except (TypeError, ValueError):
            dist = 40.0
        try:
            speed = float(f.get("speed", 1.0))
        except (TypeError, ValueError):
            speed = 1.0
        out.append(
            {
                "follower": nm,
                "leader": str(f.get("leader") or "player").strip() or "player",
                "dist": dist,
                "speed": speed,
            }
        )
    return out


def persist_active_followers_to_save(
    save_data,
    followers,
    *,
    map_id=None,
    objs=None,
    npcs=None,
) -> None:
    """
    활성 FOLLOW 동행을 세이브에 남긴다.
    - save_data['event_followers']: 누가 따라다니는지 (복원 소스, 좌표 없음)
    - save_data['placed']: travel+follow 만 — 좌표는 로드 시 플레이어 옆으로 재배치
    world_data.json 에는 쓰지 않는다.
    """
    if not isinstance(save_data, dict):
        return
    cleaned = dump_event_followers_list(followers)
    prev = dump_event_followers_list(save_data.get("event_followers"))
    save_data["event_followers"] = cleaned
    if not cleaned:
        if prev:
            clear_event_followers_from_save(
                save_data, [f.get("follower") for f in prev]
            )
        return

    mid = str(map_id or save_data.get("current_map") or "").strip()
    # 좌표는 저장 의미 없음 — load 시 prepare_traveling_placed 가 플레이어 옆으로 옮김
    stub = [0.0, 0.0]
    pp = save_data.get("player_pos")
    if isinstance(pp, (list, tuple)) and len(pp) >= 2:
        try:
            stub = [float(pp[0]), float(pp[1])]
        except (TypeError, ValueError):
            pass

    live = {}
    for ent in list(objs or []) + list(npcs or []):
        nm = str(getattr(ent, "name", "") or "").strip()
        if nm:
            live[nm] = ent

    for f in cleaned:
        nm = f["follower"]
        ent = live.get(nm)
        upsert_placed_entity(
            save_data,
            name=nm,
            map_id=mid,
            pos=stub,
            dir=None,
            behavior="follow",
            travel=True,
            follow_leader=f.get("leader"),
            follow_dist=f.get("dist"),
            follow_speed=f.get("speed"),
        )
        # 고정 좌표 의미를 남기지 않음 (로드 때 플레이어 옆 재배치)
        entry = find_placed_entry(save_data, nm)
        if isinstance(entry, dict):
            entry["pos"] = list(stub)
            entry["travel"] = True
            entry.pop("dir", None)
        if ent is not None:
            try:
                from char_behavior import set_npc_behavior

                set_npc_behavior(ent, "follow")
                mark_entity_placed_persist(ent)
            except Exception:
                pass


def clear_event_followers_from_save(save_data, stop_names=None) -> None:
    """FOLLOW_STOP: event_followers 비우고, 동행용 placed 항목은 제거(월드 고정 배치가 아님)."""
    if not isinstance(save_data, dict):
        return
    if stop_names is None:
        prev = {
            str(f.get("follower") or "").strip()
            for f in dump_event_followers_list(save_data.get("event_followers"))
            if str(f.get("follower") or "").strip()
        }
        # event_followers 비어 있어도 follow/travel placed 잔여분 정리
        for entry in ensure_placed_list(save_data):
            if not isinstance(entry, dict):
                continue
            nm = str(entry.get("name") or "").strip()
            if not nm:
                continue
            if (
                nm in prev
                or _placed_behavior_mode(entry.get("behavior")) == "follow"
                or entry.get("follow_leader")
            ):
                prev.add(nm)
        save_data["event_followers"] = []
        stop_set = prev
    else:
        stop_set = {str(n).strip() for n in stop_names if str(n).strip()}
        if not stop_set:
            return
        cur = dump_event_followers_list(save_data.get("event_followers"))
        save_data["event_followers"] = [f for f in cur if f.get("follower") not in stop_set]

    if not stop_set:
        return
    lst = ensure_placed_list(save_data)
    save_data["placed"] = [
        e
        for e in lst
        if not (
            isinstance(e, dict)
            and str(e.get("name") or "").strip() in stop_set
            and (
                _placed_behavior_mode(e.get("behavior")) == "follow"
                or e.get("follow_leader")
                or bool(e.get("travel"))
            )
        )
    ]


def build_event_followers_from_placed(save_data, map_id=None):
    """placed → ev_mgr._followers 형식 (하위호환)."""
    out = []
    if not isinstance(save_data, dict):
        return out
    mid = str(map_id or "").strip() if map_id is not None else ""
    for entry in ensure_placed_list(save_data):
        if not isinstance(entry, dict):
            continue
        if mid and str(entry.get("map_id") or "").strip() != mid:
            continue
        beh = entry.get("behavior")
        leader = str(entry.get("follow_leader") or "").strip()
        if _placed_behavior_mode(beh) != "follow" and not leader:
            continue
        nm = str(entry.get("name") or "").strip()
        if not nm:
            continue
        if not leader:
            leader = "player"
        try:
            dist = float(entry.get("follow_dist", 40))
        except (TypeError, ValueError):
            dist = 40.0
        try:
            speed = float(entry.get("follow_speed", 1.0))
        except (TypeError, ValueError):
            speed = 1.0
        out.append(
            {
                "follower": nm,
                "leader": leader,
                "dist": dist,
                "speed": speed,
                "slot": 0,
                "slots": 1,
            }
        )
    return out


def build_event_followers_from_save(save_data, map_id=None):
    """복원 우선순위: save_data.event_followers → placed follow 메타."""
    if not isinstance(save_data, dict):
        return []
    raw = save_data.get("event_followers")
    if isinstance(raw, list) and raw:
        out = []
        for f in dump_event_followers_list(raw):
            out.append(
                {
                    "follower": f["follower"],
                    "leader": f["leader"],
                    "dist": f["dist"],
                    "speed": f["speed"],
                    "slot": 0,
                    "slots": 1,
                }
            )
        return out
    return build_event_followers_from_placed(save_data, map_id)


def restore_event_followers_from_placed(
    ev_mgr, save_data, map_id=None, *, objs=None, npcs=None, player=None
) -> None:
    """세이브 기준 FOLLOW 동행 목록 복원 + 엔티티에 follow behavior 적용."""
    if ev_mgr is None:
        return
    followers = build_event_followers_from_save(save_data, map_id)
    if not followers:
        try:
            ev_mgr._followers = []
        except Exception:
            pass
        return
    try:
        ev_mgr._followers = list(followers)
        reindex = getattr(ev_mgr, "_reindex_follow_slots_for_leader", None)
        if callable(reindex):
            for lead in {str(f.get("leader") or "") for f in followers}:
                if lead:
                    reindex(lead)
    except Exception as e:
        print(f"[save] restore followers failed: {e}")
        return

    # placed 스폰만 하고 behavior 가 idle 이면 안 따라옴 → follow 로 맞춤
    try:
        from char_behavior import set_npc_behavior
        from data import resolve_story_target_id
    except Exception:
        return

    live = {}
    if player is not None:
        live["player"] = player
    for ent in list(npcs or []) + list(objs or []):
        nm = str(getattr(ent, "name", "") or "").strip()
        if nm:
            live[nm] = ent

    for f in followers:
        nm = str(f.get("follower") or "").strip()
        if not nm:
            continue
        try:
            nm_res = resolve_story_target_id(nm, save_data, None) or nm
        except Exception:
            nm_res = nm
        ent = live.get(nm_res) or live.get(nm)
        if ent is None:
            continue
        try:
            set_npc_behavior(ent, "follow")
            mark_entity_placed_persist(ent)
        except Exception:
            pass


def _serialize_entity_fx_for_save(fx) -> dict | None:
    """entity.entity_fx → JSON 친화 dict (없거나 비어 있으면 None)."""
    if not isinstance(fx, dict):
        return None
    mode = str(fx.get("mode") or "").strip().lower()
    if not mode or mode in ("off", "none", "clear", "stop"):
        return None
    out = {}
    for k, v in fx.items():
        if v is None:
            continue
        if k == "color" and isinstance(v, (tuple, list)) and len(v) >= 3:
            try:
                out["color"] = [int(v[0]), int(v[1]), int(v[2])]
            except (TypeError, ValueError):
                pass
        elif k in ("mode", "alpha", "cycle_sec", "phase_sec"):
            out[k] = v
    return out if out.get("mode") else None


def _deserialize_entity_fx_from_save(fx) -> dict | None:
    """placed entry entity_fx → 런타임 entity_fx dict."""
    if not isinstance(fx, dict):
        return None
    mode = str(fx.get("mode") or "").strip().lower()
    if not mode or mode in ("off", "none", "clear", "stop"):
        return None
    out = dict(fx)
    c = out.get("color")
    if isinstance(c, list) and len(c) >= 3:
        try:
            out["color"] = (int(c[0]), int(c[1]), int(c[2]))
        except (TypeError, ValueError):
            pass
    return out


def _snapshot_placed_visual_from_entity(ent, entry: dict) -> None:
    """세이브 직전: placed entry에 라이브 엔티티 비주얼 상태 반영."""
    if ent is None or not isinstance(entry, dict):
        return
    if hasattr(ent, "sprite_tilt"):
        try:
            entry["sprite_tilt"] = float(getattr(ent, "sprite_tilt", 1.0) or 1.0)
        except (TypeError, ValueError):
            pass
    if hasattr(ent, "height"):
        try:
            h = getattr(ent, "height", None)
            if h is not None:
                entry["height"] = float(h)
        except (TypeError, ValueError):
            pass
    ys = getattr(ent, "ysort_mode", None)
    if ys is not None and str(ys).strip():
        entry["ysort"] = str(ys).strip()
    if hasattr(ent, "layer"):
        try:
            ly = getattr(ent, "layer", None)
            if ly is not None:
                entry["layer"] = int(float(ly))
        except (TypeError, ValueError):
            pass
    try:
        from engine import clamp_entity_def_zoom

        dz = float(getattr(ent, "entity_def_zoom", 1.0) or 1.0)
        ez = float(getattr(ent, "event_entity_zoom", 1.0) or 1.0)
        combined = clamp_entity_def_zoom(dz * ez)
        if abs(combined - 1.0) > 1e-6:
            entry["zoom"] = combined
        else:
            entry.pop("zoom", None)
    except Exception:
        pass
    ser_fx = _serialize_entity_fx_for_save(getattr(ent, "entity_fx", None))
    if ser_fx:
        entry["entity_fx"] = ser_fx
    else:
        entry.pop("entity_fx", None)
    # ACTION_ANIM persist
    if bool(getattr(ent, "_action_anim_persist", False)):
        aa = getattr(ent, "_persisted_action_anim", None)
        if isinstance(aa, dict) and (aa.get("anim") or aa.get("name")):
            entry["action_anim"] = dict(aa)
        else:
            entry.pop("action_anim", None)
    else:
        entry.pop("action_anim", None)


def snapshot_placed_from_live(save_data, map_id, objs, npcs, *, event_followers=None) -> None:
    """
    현재 맵에 떠 있는 placed 엔티티의 pos/dir/behavior·비주얼 상태를 세이브에 반영.
    세이브 직전·맵 떠나기 직전에 호출.
    """
    mid = str(map_id or "").strip()
    if not mid or not isinstance(save_data, dict):
        return
    live = {}
    for ent in list(objs or []) + list(npcs or []):
        nm = str(getattr(ent, "name", "") or "").strip()
        if nm:
            live[nm] = ent
        # CHANGE persist 없이 외형만 바뀐 경우 — 세이브 키로도 찾는다
        save_nm = str(getattr(ent, "_placed_save_name", "") or "").strip()
        if save_nm:
            live[save_nm] = ent
    fol_keep = set()
    if event_followers is not None:
        fol_keep = {
            str(f.get("follower") or "").strip()
            for f in dump_event_followers_list(event_followers)
            if str(f.get("follower") or "").strip()
        }
    for entry in ensure_placed_list(save_data):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("map_id") or "").strip() != mid:
            continue
        nm = str(entry.get("name") or "").strip()
        # 동행은 좌표 스냅샷 안 함 — 로드 시 플레이어 옆 재배치
        if nm in fol_keep:
            continue
        ent = live.get(nm)
        if ent is None:
            continue
        try:
            entry["pos"] = [float(ent.pos[0]), float(ent.pos[1])]
        except Exception:
            pass
        d = str(getattr(ent, "direction", "") or "").strip().lower()
        if d in ("left", "right"):
            entry["dir"] = d
        spec = getattr(ent, "behavior_spec", None)
        if isinstance(spec, dict) and spec.get("mode"):
            entry["behavior"] = _normalize_placed_behavior(spec) or entry.get("behavior")
        _snapshot_placed_visual_from_entity(ent, entry)
    if event_followers is not None:
        persist_active_followers_to_save(
            save_data,
            event_followers,
            map_id=mid,
            objs=objs,
            npcs=npcs,
        )


def prepare_traveling_placed(save_data, map_id, player_pos, config=None, mask=None) -> None:
    """
    travel/follow placed 항목을 새 맵·플레이어 근처 좌표로 옮긴다.
    load_map 스폰 직전에 호출 (save_data 자체를 갱신).

    mask 가 있으면 이동 가능(walk) 픽셀만 고른다.
    선호 오프셋이 막히면 플레이어 주변 후보 → 최근접 walk 스냅 → 플레이어 발밑 순.
    """
    mid = str(map_id or "").strip()
    if not mid or not isinstance(save_data, dict):
        return
    cfg = config if isinstance(config, dict) else CONFIG
    try:
        base_off = float(cfg.get("PLACED_FOLLOW_SPAWN_OFFSET_PX", 28) or 28)
    except (TypeError, ValueError):
        base_off = 28.0
    try:
        spacing = float(cfg.get("PLACED_FOLLOW_SPAWN_SPACING_PX", 20) or 20)
    except (TypeError, ValueError):
        spacing = 20.0
    try:
        min_sep = float(cfg.get("PLACED_FOLLOW_SPAWN_MIN_SEP_PX", 14) or 14)
    except (TypeError, ValueError):
        min_sep = 14.0
    try:
        snap_r = int(cfg.get("PLACED_FOLLOW_SPAWN_SNAP_R_PX", cfg.get("TARGET_SNAP_MAX_R_PX", 64)) or 64)
    except (TypeError, ValueError):
        snap_r = 64
    try:
        snap_step = int(cfg.get("TARGET_SNAP_STEP_PX", 2) or 2)
    except (TypeError, ValueError):
        snap_step = 2
    try:
        px = float(player_pos[0])
        py = float(player_pos[1])
    except Exception:
        return

    snap_fn = None
    terrain_fn = None
    if mask is not None:
        try:
            from engine import _snap_to_nearest_walk, mask_terrain_class

            snap_fn = _snap_to_nearest_walk
            terrain_fn = mask_terrain_class
        except Exception:
            snap_fn = None
            terrain_fn = None

    used = []  # 이미 잡은 스폰점 (겹침 방지)

    def _far_enough(x, y) -> bool:
        for ux, uy in used:
            if math.hypot(float(x) - float(ux), float(y) - float(uy)) < min_sep:
                return False
        return True

    def _is_walk(x, y) -> bool:
        if terrain_fn is None:
            return True
        try:
            return terrain_fn(mask, float(x), float(y)) == "walk"
        except Exception:
            return True

    def _pick_near(x, y):
        """후보점 → walk 스냅. 실패 시 None."""
        cx, cy = float(x), float(y)
        if _is_walk(cx, cy) and _far_enough(cx, cy):
            return [cx, cy]
        if snap_fn is not None:
            sn = snap_fn(mask, cx, cy, max_r=snap_r, step=snap_step)
            if sn is not None:
                sx, sy = float(sn[0]), float(sn[1])
                if _far_enough(sx, sy):
                    return [sx, sy]
        return None

    def _candidates_for(i: int):
        """선호: 왼쪽 뒤 → 오른쪽/위/아래 → 플레이어 주변 링."""
        ox = base_off + i * spacing
        oy = (i % 2) * 6.0
        out = [
            (px - ox, py + oy),
            (px + ox, py + oy),
            (px - oy, py + ox),
            (px + oy, py - ox),
            (px - ox * 0.7, py - ox * 0.7),
            (px + ox * 0.7, py - ox * 0.7),
            (px - ox * 0.7, py + ox * 0.7),
            (px + ox * 0.7, py + ox * 0.7),
        ]
        # 더 넓은 링 (막힌 문 앞 등)
        for rmul in (1.5, 2.0, 2.5, 3.0):
            r = ox * rmul
            out.extend(
                [
                    (px - r, py),
                    (px + r, py),
                    (px, py - r),
                    (px, py + r),
                    (px - r * 0.7, py - r * 0.7),
                    (px + r * 0.7, py - r * 0.7),
                    (px - r * 0.7, py + r * 0.7),
                    (px + r * 0.7, py + r * 0.7),
                ]
            )
        out.append((px, py))
        return out

    travelers = [e for e in ensure_placed_list(save_data) if isinstance(e, dict) and placed_entry_travels(e)]
    for i, entry in enumerate(travelers):
        entry["map_id"] = mid
        picked = None
        for cx, cy in _candidates_for(i):
            picked = _pick_near(cx, cy)
            if picked is not None:
                break
        if picked is None:
            # 최후: 플레이어 발밑 (보통 walk) — 겹쳐도 움직임은 가능
            picked = [px, py]
            if snap_fn is not None:
                sn = snap_fn(mask, px, py, max_r=snap_r, step=snap_step)
                if sn is not None:
                    picked = [float(sn[0]), float(sn[1])]
        entry["pos"] = picked
        used.append((picked[0], picked[1]))


def _spawn_one_placed_entity(entry: dict, objs: list, npcs: list, save_data=None, config=None):
    """
    placed entry 1개를 씬에 생성하거나 기존 동명 엔티티에 적용.
    PLACE / load_map 과 동일한 FieldItem·MaskWalkingCharacter·attach_npc_from_entry 경로.
    """
    nm = str(entry.get("name") or "").strip()
    if not nm:
        return None
    # ally1 등 별칭 → 실제 id (세이브에 별칭이 남아 있을 수 있음)
    try:
        from data import resolve_story_target_id

        nm_res = resolve_story_target_id(nm, save_data, config) or nm
    except Exception:
        nm_res = nm
    pos = entry.get("pos") or [0, 0]
    try:
        pos_xy = [float(pos[0]), float(pos[1])]
    except Exception:
        pos_xy = [0.0, 0.0]

    existing = next(
        (x for x in list(npcs or []) + list(objs or []) if getattr(x, "name", "") == nm_res),
        None,
    )
    from engine import FieldItem, BaseCharacter, MaskWalkingCharacter

    st = entry.get("sprite_tilt")
    h = entry.get("height")
    ys = entry.get("ysort")
    ly = entry.get("layer")

    if existing is not None:
        ent = existing
        try:
            ent.pos = [pos_xy[0], pos_xy[1]]
            if hasattr(ent, "origin_pos"):
                ent.origin_pos = [pos_xy[0], pos_xy[1]]
        except Exception:
            pass
    elif nm_res in OBJ_ASSETS:
        ent = FieldItem(
            nm_res,
            pos_xy[0],
            pos_xy[1],
            sprite_tilt=float(st) if st is not None else 1.0,
            height=h,
            ysort_mode=ys,
            layer=ly,
            zoom=entry.get("zoom", None),
            wall_angle=entry.get("wall_angle", 0.0),
            wall_3d=entry.get("wall_3d", False),
        )
        objs.append(ent)
    else:
        ch_info = {}
        if st is not None:
            try:
                ch_info["sprite_tilt"] = float(st)
            except (TypeError, ValueError):
                pass
        if h is not None:
            ch_info["height"] = h
        if ys is not None:
            ch_info["ysort"] = ys
        if ly is not None:
            try:
                ch_info["layer"] = int(float(ly))
            except (TypeError, ValueError):
                pass
        from char_behavior import attach_npc_from_entry, spawn_as_mask_walker

        n_entry = {"name": nm_res, "pos": list(pos_xy)[:2]}
        beh = entry.get("behavior")
        if isinstance(beh, dict):
            n_entry["behavior"] = dict(beh)
        elif isinstance(beh, str) and beh.strip():
            n_entry["behavior"] = {"mode": beh.strip()}
        if spawn_as_mask_walker(nm_res, n_entry):
            ent = MaskWalkingCharacter(nm_res, pos_xy, ch_info)
        else:
            ent = BaseCharacter(nm_res, pos_xy, ch_info)
        try:
            attach_npc_from_entry(ent, n_entry)
        except Exception:
            pass
        npcs.append(ent)

    # 비주얼·방향·behavior 재적용 (기존 world 엔티티에도)
    if st is not None and hasattr(ent, "sprite_tilt"):
        try:
            ent.sprite_tilt = float(st)
        except (TypeError, ValueError):
            pass
    if h is not None and hasattr(ent, "height"):
        try:
            ent.height = float(h)
        except (TypeError, ValueError):
            pass
    if ys is not None and hasattr(ent, "ysort_mode"):
        ent.ysort_mode = ys
    if ly is not None and hasattr(ent, "layer"):
        try:
            ent.layer = int(float(ly))
        except (TypeError, ValueError):
            pass
    if "zoom" in entry and hasattr(ent, "entity_def_zoom"):
        try:
            from engine import clamp_entity_def_zoom

            ent.entity_def_zoom = clamp_entity_def_zoom(entry.get("zoom"))
        except Exception:
            pass
    d = str(entry.get("dir") or "").strip().lower()
    if d in ("left", "right") and hasattr(ent, "direction"):
        ent.direction = d
        try:
            from engine import _event_refresh_facing_image

            _event_refresh_facing_image(ent)
        except Exception:
            pass
    beh = entry.get("behavior")
    if beh and not (nm_res in OBJ_ASSETS):
        try:
            from char_behavior import set_npc_behavior, set_roam_home

            if isinstance(beh, dict):
                mode = beh.get("mode")
                kwargs = {}
                if beh.get("radius") is not None:
                    kwargs["radius"] = beh.get("radius")
                if beh.get("interval_ms") is not None:
                    kwargs["interval_ms"] = beh.get("interval_ms")
                if mode:
                    set_npc_behavior(ent, mode, **kwargs)
            else:
                set_npc_behavior(ent, beh)
            set_roam_home(ent, pos_xy[0], pos_xy[1])
        except Exception:
            pass
    fx = _deserialize_entity_fx_from_save(entry.get("entity_fx"))
    if fx:
        try:
            ent.entity_fx = fx
            ent._entity_fx_event_persist = True
        except Exception:
            pass
    aa = entry.get("action_anim")
    if isinstance(aa, dict) and (aa.get("anim") or aa.get("name")):
        try:
            from engine import apply_persisted_action_anim

            apply_persisted_action_anim(ent, aa, objs=objs, npcs=npcs)
        except Exception as e:
            print(f"[placed action_anim restore] {e}")
    mark_entity_placed_persist(ent, str(entry.get("name") or "").strip() or nm_res)
    # PLACE persist 복원 = 맵에 다시 등장. world_data 인스턴스가 spawn_state 로
    # 먼저 숨겨진 뒤 placed 가 같은 이름을 덮을 때도 보이게 한다.
    if hasattr(ent, "is_visible"):
        try:
            ent.is_visible = True
        except Exception:
            pass
    if hasattr(ent, "alpha"):
        try:
            ent.alpha = 255
        except Exception:
            pass
    return ent


def ensure_event_followers_in_placed(save_data, map_id=None) -> None:
    """event_followers → placed(travel/follow) 동기화. 로드 직전 호출(좌표는 prepare_traveling이 재배치)."""
    if not isinstance(save_data, dict):
        return
    fols = dump_event_followers_list(save_data.get("event_followers"))
    if not fols:
        return
    persist_active_followers_to_save(
        save_data,
        fols,
        map_id=str(map_id or save_data.get("current_map") or "").strip() or None,
        objs=None,
        npcs=None,
    )


def apply_placed_to_map(objs, npcs, save_data, map_id, *, player_pos=None, config=None, mask=None):
    """
    load_map 말미: travel 동행 좌표 갱신 후, 현재 맵의 placed 엔티티를 스폰/적용.
    반환 (objs, npcs).
    mask 가 있으면 동행 스폰을 walk 영역으로 스냅.
    """
    sd = save_data if isinstance(save_data, dict) else {}
    mid = str(map_id or "").strip()
    cfg = config if isinstance(config, dict) else CONFIG
    # 세이브 event_followers 만 있고 placed 가 비어 있어도 플레이어 옆에 스폰되게
    try:
        ensure_event_followers_in_placed(sd, mid)
    except Exception as e:
        print(f"[placed] follower sync failed: {e}")
    if player_pos is not None:
        prepare_traveling_placed(sd, mid, player_pos, config=cfg, mask=mask)
    for entry in list(ensure_placed_list(sd)):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("map_id") or "").strip() != mid:
            continue
        try:
            _spawn_one_placed_entity(entry, objs, npcs, save_data=sd, config=cfg)
        except Exception as e:
            print(f"[placed] spawn failed {entry.get('name')}: {e}")
    return objs, npcs


def merge_save_defaults(save_data: dict, config) -> dict:
    """누락된 세이브 키를 채움. gamestart 등 온보딩 단계는 세이브에 두지 않음(구 파일에 있으면 제거)."""
    if not save_data:
        save_data = {}
    _spawn = config.get("NEW_GAME_SPAWN_POS") or [100, 100]
    _default_pc = str(config.get("DEFAULT_PLAYER_CHAR", "summer_k") or "summer_k")
    # parent_char 는 player_char 확정 후 PLAYER_PARENTS 로 유도 (아래 동기화)
    # player_char_selected 는 defaults 에 넣지 않음 — 구 세이브 마이그레이션과 구분하기 위함
    _had_char_selected_key = "player_char_selected" in save_data
    defaults = {
        "mainprogress": "010100",
        "laugh_point": 0,
        "subprogress": {},
        "player_pos": list(_spawn),
        "current_map": config["START_MAP"],
        # 조작 주인공 (첫 시작 캐릭터 선택 결과). 없으면 DEFAULT_PLAYER_CHAR
        "player_char": _default_pc,
        # "hide": 도랑 점프 등 중 그림자 없음 / "ground": 땅 위치에 작고 옅게 유지
        "jump_shadow_mode": "ground",
        "flags": {},
        "affinity": {},
        # PLACE persist:true 로 등장한 오브젝트/NPC (remove 전까지 맵·세이브 유지)
        "placed": [],
        # 본편 부팅 auto(ev_gl_field_boot) 래치. 0이면 FADEIN·exit 등 필수 UI 1회 실행.
        # main() 이 매 실행 시작 시 0으로 리셋한다 (세션당 1회).
        "field_boot_ready": 0,
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
    # 구 세이브: here01 표시 중 progress_flower1_1==1002 를 파일에 남김.
    # 1002 는 세션 전용(휘발 마커). 심기 전(1003 미만)이면 1001 로 되돌려
    # 재시작 후 ev_flower1_1 을 다시 탈 수 있게 한다.
    try:
        p1 = save_data.get("progress_flower1_1")
        if p1 == 1002 or str(p1) == "1002":
            save_data["progress_flower1_1"] = 1001
            g = save_data.get("progress_flower1_ground")
            if g == 1 or str(g) == "1":
                save_data["progress_flower1_ground"] = 0
    except Exception:
        pass
    # player_char_selected:
    #   - 선택 UI 완료 시에만 True
    #   - 구 세이브에 키 없음: mainprogress 가 010100 이면 미선택, 그 외(본편 진행)면 완료로 간주
    if not _had_char_selected_key:
        mp = str(save_data.get("mainprogress") or "010100").strip()
        save_data["player_char_selected"] = bool(mp) and mp not in ("010100", "0", "")
    else:
        save_data["player_char_selected"] = bool(save_data.get("player_char_selected"))
    # 부모 id 동기화 — PLAYER_PARENTS[player_char] (역할 교체 시 항상 맞춤)
    try:
        from data import apply_player_char_choice, get_player_char_id

        pc = get_player_char_id(save_data, config)
        # selected 플래그는 건드리지 않음 (부모만 맞춤)
        apply_player_char_choice(save_data, pc, config, selected=False)
    except Exception:
        if not str(save_data.get("parent_char") or "").strip():
            save_data["parent_char"] = "carrot_a"
    return save_data


# ---------------------------------------------------------------------------
# 미니게임 기록 — minigame_records.json (save_data.json 과 분리)
#
# [왜 세이브와 분리?]
#   아케이드 HIGH SCORE 등은 세이브 초기화(D키·새 게임)와 무관하게 유지해야 함.
#
# [왜 flow.py?]
#   load_save_data / save_game 과 같은 영속화 계층. 별도 .py 파일은 만들지 않음.
#
# [파일 구조]  CONFIG["MINIGAME_RECORDS_FILE"] → 기본 minigame_records.json
#   {
#     "baseball": { "best_score": int, "history": [ {...}, ... ] },
#     "racing": {
#       "maps": {
#         "<map_id>": {
#           "by_laps": {
#             "<laps>": { "time_sec", "time_str", "char", "laps", "map_id" }
#           }
#         }
#       },
#       "history": [ { map_id, char, laps, time_sec, time_str, mode }, ... ]
#     }
#   }
# ---------------------------------------------------------------------------

_MINIGAME_RECORDS_DEFAULT: dict = {
    "baseball": {"best_score": 0, "history": []},
    "racing": {"maps": {}, "history": []},
}


def minigame_records_path(config=None) -> str:
    cfg = config if config is not None else CONFIG
    return str(cfg.get("MINIGAME_RECORDS_FILE", "minigame_records.json"))


def load_minigame_records(config=None) -> dict:
    path = minigame_records_path(config)
    if not os.path.isfile(path):
        return json.loads(json.dumps(_MINIGAME_RECORDS_DEFAULT))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return _normalize_minigame_records(data if isinstance(data, dict) else {})
    except Exception:
        return json.loads(json.dumps(_MINIGAME_RECORDS_DEFAULT))


def save_minigame_records(data: dict, config=None) -> None:
    path = minigame_records_path(config)
    normalized = _normalize_minigame_records(data if isinstance(data, dict) else {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=4)


def _normalize_minigame_records(data: dict) -> dict:
    out = json.loads(json.dumps(_MINIGAME_RECORDS_DEFAULT))
    bb = data.get("baseball")
    if isinstance(bb, dict):
        try:
            out["baseball"]["best_score"] = int(bb.get("best_score", 0) or 0)
        except (TypeError, ValueError):
            pass
        hist = bb.get("history")
        if isinstance(hist, list):
            out["baseball"]["history"] = [r for r in hist if isinstance(r, dict)]
    rc = data.get("racing")
    if isinstance(rc, dict):
        maps_in = rc.get("maps")
        maps_out: dict = {}
        if isinstance(maps_in, dict):
            for mid, mrow in maps_in.items():
                mid_s = str(mid or "").strip()
                if not mid_s or not isinstance(mrow, dict):
                    continue
                by_laps_in = mrow.get("by_laps")
                by_laps_out: dict = {}
                if isinstance(by_laps_in, dict):
                    for lk, brow in by_laps_in.items():
                        if not isinstance(brow, dict):
                            continue
                        try:
                            laps_i = int(brow.get("laps", lk) or lk)
                        except (TypeError, ValueError):
                            continue
                        try:
                            tsec = float(brow.get("time_sec", 0.0) or 0.0)
                        except (TypeError, ValueError):
                            tsec = 0.0
                        by_laps_out[str(laps_i)] = {
                            "map_id": mid_s,
                            "laps": laps_i,
                            "time_sec": tsec,
                            "time_str": str(
                                brow.get("time_str") or format_racing_time_sec(tsec)
                            ),
                            "char": str(brow.get("char") or ""),
                        }
                maps_out[mid_s] = {"by_laps": by_laps_out}
        out["racing"]["maps"] = maps_out
        hist_r = rc.get("history")
        if isinstance(hist_r, list):
            out["racing"]["history"] = [r for r in hist_r if isinstance(r, dict)]
    return out


def format_racing_time_sec(t: float) -> str:
    """초 → '분:초.소수2' (레이스 HUD와 동일 형식)."""
    t = max(0.0, float(t))
    m, s = divmod(t, 60.0)
    return f"{int(m)}:{s:05.2f}"


def migrate_baseball_records_from_save(save_data: dict, config=None) -> bool:
    """save_data.json 의 baseball_records / baseball_best_npc → minigame_records.json (1회 이전)."""
    if not isinstance(save_data, dict):
        return False
    old_hist = save_data.get("baseball_records")
    old_best = save_data.get("baseball_best_npc")
    if not isinstance(old_hist, list) and old_best is None:
        return False

    data = load_minigame_records(config)
    bb = data.setdefault("baseball", {"best_score": 0, "history": []})
    hist: list = list(bb.get("history") or [])
    existing = {json.dumps(r, sort_keys=True, ensure_ascii=False) for r in hist if isinstance(r, dict)}
    changed = False

    for row in old_hist or []:
        if not isinstance(row, dict):
            continue
        key = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if key not in existing:
            hist.append(dict(row))
            existing.add(key)
            changed = True

    try:
        prev_best = int(bb.get("best_score", 0) or 0)
        legacy_best = int(old_best or 0)
        if legacy_best > prev_best:
            bb["best_score"] = legacy_best
            changed = True
    except (TypeError, ValueError):
        pass

    for row in hist:
        try:
            sc = int(row.get("score", row.get("player", 0)) or 0)
        except (TypeError, ValueError):
            sc = 0
        if sc > int(bb.get("best_score", 0) or 0):
            bb["best_score"] = sc

    if len(hist) > 20:
        hist = hist[-20:]
        changed = True

    bb["history"] = hist
    path = minigame_records_path(config)
    if changed or (isinstance(old_hist, list) and old_hist and not os.path.isfile(path)):
        save_minigame_records(data, config)
        return True
    return False


def baseball_record_history(config=None) -> list:
    hist = load_minigame_records(config).get("baseball", {}).get("history")
    if not isinstance(hist, list):
        return []
    return [r for r in hist if isinstance(r, dict)]


def append_baseball_record(entry: dict, config=None) -> list:
    """야구 1P 기록 추가·즉시 저장. 점수 내림차순 상위 10개 반환."""
    data = load_minigame_records(config)
    bb = data.setdefault("baseball", {"best_score": 0, "history": []})
    hist: list = list(bb.get("history") or [])
    hist.append(dict(entry))
    hist = hist[-20:]
    bb["history"] = hist
    try:
        score = int(entry.get("score", entry.get("player", 0)) or 0)
    except (TypeError, ValueError):
        score = 0
    if score > int(bb.get("best_score", 0) or 0):
        bb["best_score"] = score
    save_minigame_records(data, config)
    ranked = sorted(
        hist,
        key=lambda r: int(r.get("score", r.get("player", 0)) or 0),
        reverse=True,
    )
    return ranked[:10]


def racing_record_bests(config=None) -> list:
    """맵·랩수별 최고 기록 목록 (레이스 메뉴 '기록 보기'). 맵 id → 랩 수 순."""
    maps = load_minigame_records(config).get("racing", {}).get("maps") or {}
    rows = []
    if not isinstance(maps, dict):
        return rows
    for mid, mrow in maps.items():
        if not isinstance(mrow, dict):
            continue
        by_laps = mrow.get("by_laps") or {}
        if not isinstance(by_laps, dict):
            continue
        for _lk, brow in by_laps.items():
            if isinstance(brow, dict):
                rows.append(dict(brow))

    def _sort_key(r):
        try:
            laps_i = int(r.get("laps") or 0)
        except (TypeError, ValueError):
            laps_i = 0
        return (str(r.get("map_id") or ""), laps_i)

    rows.sort(key=_sort_key)
    return rows


def racing_best_for_map(map_id: str, laps: int, config=None):
    """맵·랩수 조합의 최고 기록(최단 시간) dict 또는 None."""
    mid = str(map_id or "").strip()
    if not mid:
        return None
    try:
        laps_i = int(laps)
    except (TypeError, ValueError):
        return None
    maps = load_minigame_records(config).get("racing", {}).get("maps") or {}
    mrow = maps.get(mid) if isinstance(maps, dict) else None
    if not isinstance(mrow, dict):
        return None
    by_laps = mrow.get("by_laps") or {}
    if not isinstance(by_laps, dict):
        return None
    best = by_laps.get(str(laps_i))
    return dict(best) if isinstance(best, dict) else None


def append_racing_record(entry: dict, config=None) -> dict:
    """
    레이스 기록용(1인) 완주 기록 추가·즉시 저장.
    entry: map_id, char, laps, time_sec [, time_str, mode]
    반환: { "is_best": bool, "best": dict|None, "entry": dict }
    같은 맵·같은 랩수에서 time_sec 가 더 짧으면 신기록.
    """
    mid = str((entry or {}).get("map_id") or "").strip()
    try:
        laps_i = int((entry or {}).get("laps", 0) or 0)
    except (TypeError, ValueError):
        laps_i = 0
    try:
        tsec = float((entry or {}).get("time_sec", 0.0) or 0.0)
    except (TypeError, ValueError):
        tsec = 0.0
    tsec = max(0.0, tsec)
    row = {
        "mode": str((entry or {}).get("mode") or "record"),
        "map_id": mid,
        "char": str((entry or {}).get("char") or ""),
        "laps": laps_i,
        "time_sec": round(tsec, 3),
        "time_str": str((entry or {}).get("time_str") or format_racing_time_sec(tsec)),
    }
    data = load_minigame_records(config)
    racing = data.setdefault("racing", {"maps": {}, "history": []})
    if not isinstance(racing.get("maps"), dict):
        racing["maps"] = {}
    hist: list = list(racing.get("history") or [])
    hist.append(dict(row))
    racing["history"] = hist[-40:]

    is_best = False
    best_out = None
    if mid and laps_i > 0:
        mrow = racing["maps"].setdefault(mid, {"by_laps": {}})
        if not isinstance(mrow.get("by_laps"), dict):
            mrow["by_laps"] = {}
        prev = mrow["by_laps"].get(str(laps_i))
        prev_t = None
        if isinstance(prev, dict):
            try:
                prev_t = float(prev.get("time_sec"))
            except (TypeError, ValueError):
                prev_t = None
        if prev_t is None or tsec < prev_t:
            is_best = True
            mrow["by_laps"][str(laps_i)] = {
                "map_id": mid,
                "laps": laps_i,
                "time_sec": row["time_sec"],
                "time_str": row["time_str"],
                "char": row["char"],
            }
        best_out = dict(mrow["by_laps"].get(str(laps_i)) or row)

    save_minigame_records(data, config)
    return {"is_best": bool(is_best), "best": best_out, "entry": row}


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
        try:
            migrate_baseball_records_from_save(self.save_data, self.config)
        except Exception:
            pass
        # 강제 종료로 미니게임 맵이 세이브에 남은 경우만 exit 로 교정 (의도적 MAP 이동은 load_map 그대로)
        try:
            if normalize_activity_arena_in_save(self.save_data, self.world_data, self.config):
                with open(self.save_path, "w", encoding="utf-8") as f:
                    json.dump(self.save_data, f, ensure_ascii=False, indent=4)
                print(
                    "[save] activity arena spawn fixed → "
                    f"{self.save_data.get('current_map')} @ {self.save_data.get('player_pos')}"
                )
        except Exception:
            pass
        # 매 실행: 0=인트로, 1=데모, 15=캐릭터선택(세이브 없을 때), 2=본편
        # (세이브 없음 — pick_global 시 session_vars={"gamestart": boot_phase} 로만 전달)
        self.boot_phase = 0
        # 세이브 없이 데모 종료 후 캐릭터 선택→본편 스폰 대기
        self.pending_new_game_after_char_select = False
        # 이벤트 시작 직전 세이브 스냅샷 (중도 종료 시 이벤트 맵으로 덮어쓰지 않음)
        self._pre_event_save_snapshot = None
        # contact_player: 존 안에 머무는 동안 매 프레임 재발동 방지 (진입 엣지에서만)
        self._zone_player_inside = {}
        # RESULT session:true — 이번 실행만. 세이브에 안 씀 (here01 같은 휘발 마커).
        self.session_progress = {}
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

    def eval_session_vars(self, extra=None) -> dict:
        out = {"gamestart": getattr(self, "boot_phase", None)}
        sp = getattr(self, "session_progress", None)
        if isinstance(sp, dict):
            out.update(sp)
        if extra:
            out.update(extra)
        return out

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
        session_vars=None,
    ):
        m = self.world_data.get(map_id, {})
        zones = m.get("event_zones", [])
        save = self.save_data
        kwargs_session = session_vars if session_vars is not None else eval_session_vars(self)
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

            # 2. 조건 체크 (세션 RESULT 포함 — here01 점유 등)
            if not zone_conditions_ok(z, save, session_vars=kwargs_session):
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
                # 플레이어와 클릭 위치가 모두 존 안일 때만 발동한다.
                # 존 밖 클릭은 이동 의도로 남겨 이벤트가 가로채지 않게 한다.
                ok = False
                if zone_click_world is not None:
                    try:
                        cx, cy = zone_click_world
                        ok = zx <= float(cx) <= zx + zw and zy <= float(cy) <= zy + zh
                    except Exception:
                        ok = False
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
        """에디터 전용 world_data.json 저장.
        런타임 FOLLOW/PLACE persist 동행은 제외 — 그건 save_data.event_followers/placed.
        """
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
            try:
                from engine import clamp_entity_def_zoom

                z = float(getattr(o, "entity_def_zoom", 1.0) or 1.0)
                z = clamp_entity_def_zoom(z)
                if abs(z - 1.0) > 1e-4:
                    row["zoom"] = round(z, 4)
            except Exception:
                pass
            try:
                wa = float(getattr(o, "wall_angle", 0.0) or 0.0)
                if math.isfinite(wa):
                    wa = wa % 360.0
                    if wa < 0.0:
                        wa += 360.0
                    if min(wa, 360.0 - wa) > 0.05:
                        row["wall_angle"] = round(float(wa), 2)
            except Exception:
                pass
            try:
                from engine import field_wall_3d_flag

                if field_wall_3d_flag(getattr(o, "wall_3d", False)):
                    row["wall_3d"] = True
            except Exception:
                pass
            inst = getattr(o, "interact_instance", None)
            if isinstance(inst, dict) and inst:
                row["interact"] = inst
            we = getattr(o, "_world_entry", None) or {}
            if isinstance(we.get("spawn_state"), dict) and we["spawn_state"]:
                row["spawn_state"] = dict(we["spawn_state"])
            if isinstance(we.get("progress_apply"), list) and we["progress_apply"]:
                row["progress_apply"] = list(we["progress_apply"])
            if isinstance(we.get("text_label"), dict) and we["text_label"]:
                row["text_label"] = dict(we["text_label"])
            if we.get("scoreboard_zoom") is not None:
                row["scoreboard_zoom"] = float(we["scoreboard_zoom"])
            if isinstance(we.get("scoreboard_style"), dict) and we["scoreboard_style"]:
                row["scoreboard_style"] = dict(we["scoreboard_style"])
            bz = we.get("baseball_zone")
            if isinstance(bz, dict) and bz:
                row["baseball_zone"] = dict(bz)
            elif str(o.name or "").startswith("bbzone_"):
                from data import OBJ_ASSETS

                od = OBJ_ASSETS.get(o.name, {}) or {}
                def_bz = od.get("baseball_zone")
                if isinstance(def_bz, dict) and def_bz:
                    row["baseball_zone"] = dict(def_bz)
            return row

        def _is_runtime_party_entity(ent) -> bool:
            """세이브 동행/PLACE persist — world_data 정적 배치가 아님."""
            if bool(getattr(ent, "_placed_persist", False)):
                return True
            try:
                from char_behavior import normalize_behavior_mode

                spec = getattr(ent, "behavior_spec", None) or {}
                if normalize_behavior_mode(spec.get("mode")) != "follow":
                    return False
                # 이벤트 FOLLOW 는 mode 만 두는 경우가 많음(ambient follow 는 trigger_range 등)
                if spec.get("trigger_range") is None and spec.get("stop_dist") is None:
                    return True
            except Exception:
                pass
            return False

        safe_objs = [o for o in (objs or []) if not _is_runtime_party_entity(o)]
        safe_npcs = [n for n in (npcs or []) if not _is_runtime_party_entity(n)]

        self.world_data[map_id]["objects"] = [_object_entry_from_instance(o) for o in safe_objs]
        from char_behavior import npc_entry_from_instance

        self.world_data[map_id]["npcs"] = [npc_entry_from_instance(n) for n in safe_npcs]

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
            compact_json = _compact_named_array_objects_to_single_lines(compact_json, "presence_zones")

            with open("world_data.json", "w", encoding="utf-8") as f:
                f.write(compact_json)
            print(f"[{map_id}] 가독성 최적화 저장 성공!")
        except Exception as e:
            print(f"저장 실패: {e}")

    def load_world_config(self):
        # 외부 편집기에서 UTF-8 BOM으로 저장돼도 안전하게 읽는다.
        with open("world_data.json", "r", encoding="utf-8-sig") as f:
            return json.load(f)

    def load_save_data(self):
        if os.path.exists(self.save_path):
            try:
                # 기록은 항상 UTF-8(ensure_ascii=False). Windows 기본 cp949 로 읽으면
                # progress_status 등 한글이 들어간 뒤 UnicodeDecodeError → 빈 세이브로
                # 떨어져 캐릭터 선택/010100 초기화처럼 보인다.
                with open(self.save_path, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[save] load failed ({self.save_path}): {e}")
                return None
        return None

    def sync_runtime_location(self, map_id, player_pos):
        """
        필드 자유이동 중 메모리 세이브의 맵·좌표만 맞춘다 (디스크 미기록).
        이벤트 중에는 호출하지 않는다 — 이벤트 맵이 current_map 에 섞이지 않게.
        """
        if self._pre_event_save_snapshot is not None:
            return
        mid = str(map_id or "").strip()
        if mid:
            self.save_data["current_map"] = mid
        try:
            self.save_data["player_pos"] = [int(player_pos[0]), int(player_pos[1])]
        except (TypeError, ValueError, IndexError):
            pass

    def capture_pre_event_checkpoint(self, map_id=None, player_pos=None):
        """
        이벤트 시작 직전 상태를 디스크에 고정.
        이벤트 중 종료·크래시 시 이벤트용 맵이 세이브에 남지 않게 한다.
        본편(boot_phase==2)에서만 동작. (캐릭터선택 15 등은 온보딩 세이브 오염 방지)
        """
        try:
            bp = int(getattr(self, "boot_phase", 0) or 0)
        except (TypeError, ValueError):
            return
        if bp != 2:
            return
        if not isinstance(self.save_data, dict):
            self.save_data = {}
        mid = str(map_id or self.save_data.get("current_map") or "").strip()
        if mid:
            self.save_data["current_map"] = mid
        if player_pos is not None:
            try:
                self.save_data["player_pos"] = [int(player_pos[0]), int(player_pos[1])]
            except (TypeError, ValueError, IndexError):
                pass
        snap = copy.deepcopy(self.save_data)
        self._pre_event_save_snapshot = snap
        try:
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=4)
            print(
                "[save] pre-event checkpoint → "
                f"{snap.get('current_map')} @ {snap.get('player_pos')}"
            )
        except Exception as e:
            print(f"[save] pre-event checkpoint fail: {e}")

    def clear_pre_event_checkpoint(self):
        """최상위 이벤트 정상 종료 시 가드 해제 (이후 종료 세이브는 현재 위치 기록)."""
        self._pre_event_save_snapshot = None

    def is_event_save_guarded(self) -> bool:
        return self._pre_event_save_snapshot is not None

    def _write_save_data_to_disk(self):
        try:
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump(self.save_data, f, ensure_ascii=False, indent=4)
            print("플레이 데이터가 안전하게 저장되었습니다.")
            return True
        except Exception as e:
            print(f"세이브 실패: {e}")
            return False

    def save_game(
        self,
        map_id,
        player_pos,
        *,
        ignore_event_guard=False,
        objs=None,
        npcs=None,
        event_followers=None,
    ):
        # 이벤트 진행 중: 이벤트 맵·연출 좌표로 덮어쓰지 않음 (시작 시 체크포인트 유지)
        if self._pre_event_save_snapshot is not None and not ignore_event_guard:
            print("[save] skipped — event in progress (pre-event checkpoint kept)")
            return
        # 미니게임 전용 맵(야구장·서킷 등)은 현재 좌표를 저장하지 않고 exit_map/exit_pos 로 저장.
        try:
            map_id, player_pos = apply_activity_arena_save_location(
                self.world_data, map_id, player_pos, self.config
            )
        except Exception:
            pass
        # PLACE persist 엔티티 현재 위치·behavior 스냅샷 (objs/npcs 전달 시)
        if objs is not None or npcs is not None:
            try:
                snapshot_placed_from_live(
                    self.save_data,
                    map_id,
                    objs,
                    npcs,
                    event_followers=event_followers,
                )
            except Exception as e:
                print(f"[save] placed snapshot failed: {e}")
        elif event_followers is not None:
            try:
                persist_active_followers_to_save(
                    self.save_data,
                    event_followers,
                    map_id=map_id,
                    objs=objs,
                    npcs=npcs,
                )
            except Exception as e:
                print(f"[save] follower sync failed: {e}")
        self.save_data["current_map"] = map_id
        self.save_data["player_pos"] = [int(player_pos[0]), int(player_pos[1])]
        self._write_save_data_to_disk()

    def load_map(self, save_data=None, *, apply_placed=True):
        # apply_placed=False: 에디터 전용 — save_data.placed / event_followers 를
        # 맵 정적 배치(world_data)에 섞지 않음. (섞인 채 S저장하면 world_data 오염)
        # 1. 어떤 맵을 부를지 결정 (세이브 데이터 우선, 없으면 CONFIG 기본값)
        # 주의: 미니게임 맵(exit) 치환은 save_game / GameFlow 기동 시만 — 여기선 MAP 이벤트 진입을 막지 않음.
        map_id = CONFIG["START_MAP"]
        if save_data and "current_map" in save_data:
            map_id = save_data["current_map"]

        m = self.world_data[map_id]
        
        # 2. 자산 로드 (경로도 world_data.json에 정의된 대로)
        bg = pygame.image.load(os.path.join("assets", "images", "bg", m["bg_img"])).convert()
        try:
            from engine import invalidate_rotate3d_mode7_map_cache

            invalidate_rotate3d_mode7_map_cache()
        except Exception:
            pass
        
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

        # 세이브 player_char → CONFIG DEFAULT_PLAYER_CHAR (첫 시작 선택·이어하기 공통)
        try:
            from data import get_player_char_id

            pc = get_player_char_id(self.save_data, self.config)
            if isinstance(save_data, dict) and str(save_data.get("player_char") or "").strip():
                pc = get_player_char_id(save_data, self.config)
        except Exception:
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
                wall_angle=o.get("wall_angle", 0.0),
                wall_3d=o.get("wall_3d", False),
                zoom=o.get("zoom", None),
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
            it.obj_def = build_obj_def(o["name"], o)
            it._world_entry = dict(o)
            if isinstance(o.get("baseball_zone"), dict):
                it._world_entry["baseball_zone"] = dict(o["baseball_zone"])
            try:
                from activities.baseball_zones import (
                    apply_scoreboard_defaults,
                    is_scoreboard_object,
                    zone_uses_ellipse_fallback,
                )

                if is_scoreboard_object(it):
                    apply_scoreboard_defaults(it)
                elif zone_uses_ellipse_fallback(it):
                    it.is_visible = False
            except Exception:
                pass
            objs.append(it)
        npcs = []
        for n in m.get("npcs", []):
            # ally1~5 / *_parent → 실제 CHAR_ASSETS 키 (주인공 선택에 따라 바뀜)
            nm_raw = str(n.get("name") or "").strip()
            try:
                from data import resolve_story_target_id

                nm = resolve_story_target_id(nm_raw, self.save_data, self.config) or nm_raw
            except Exception:
                nm = nm_raw
            if not nm:
                continue
            ch_info = {
                "sprite_tilt": n.get("sprite_tilt", 1.0),
                "ysort": n.get("ysort", "ground"),
                "layer": n.get("layer", 0),
            }
            if "height" in n:
                ch_info["height"] = n["height"]
            from char_behavior import attach_npc_from_entry, spawn_as_mask_walker

            # attach·interact 은 원본 entry 유지하되, 생성·이름만 해석된 id 사용
            n_spawn = dict(n)
            n_spawn["name"] = nm
            if spawn_as_mask_walker(nm, n_spawn):
                ch = MaskWalkingCharacter(nm, n["pos"], ch_info)
            else:
                ch = BaseCharacter(nm, n["pos"], ch_info)
            attach_npc_from_entry(ch, n_spawn)
            npcs.append(ch)

        from char_behavior import apply_map_progress_states

        sd = dict(self.save_data or {})
        if save_data:
            sd.update(save_data)
        objs, npcs = apply_map_progress_states(
            objs, npcs, sd, session_vars=eval_session_vars(self)
        )

        # PLACE persist — travel/follow 동행 좌표 갱신 후 현재 맵 placed 스폰
        # (world_data 정적 배치 + progress 적용 뒤, 동일 이름이면 pos/behavior 만 덮어씀)
        # 에디터(apply_placed=False)는 세이브 동행을 맵 배치에 합치지 않음
        if apply_placed:
            try:
                ppos = list(player.pos) if player is not None else (sd.get("player_pos") or [0, 0])
                objs, npcs = apply_placed_to_map(
                    objs,
                    npcs,
                    self.save_data if isinstance(self.save_data, dict) else sd,
                    map_id,
                    player_pos=ppos,
                    config=self.config,
                    mask=mask,
                )
                # travel 로 바뀐 map_id/pos 를 self.save_data 에 유지 (위에서 self.save_data 를 넘김)
                # placed 로 새로 스폰된 엔티티에도 progress_apply 적용
                # (_placed_persist 는 spawn_state 숨김을 건너뜀)
                objs, npcs = apply_map_progress_states(
                    objs, npcs, sd, session_vars=eval_session_vars(self)
                )
            except Exception as e:
                print(f"[load_map] placed restore failed: {e}")

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
        """현재 작업 중인 이벤트 데이터를 가독성 있게 저장합니다.
        LOCAL/GLOBAL/SYNC/FRAGMENTS 각 섹션은 이벤트 ID(이름) 오름차순으로 정렬합니다.
        """
        file_path = "events.json"
        try:
            # 섹션별 이벤트를 ID 이름순으로 정렬 (에디터 저장 시 파일 가독성·diff 안정)
            ordered = {}
            for sec in ("LOCAL", "GLOBAL", "SYNC", "FRAGMENTS"):
                sec_data = event_data.get(sec) if isinstance(event_data, dict) else None
                if isinstance(sec_data, dict):
                    ordered[sec] = {
                        k: sec_data[k]
                        for k in sorted(sec_data.keys(), key=lambda s: str(s))
                    }
                else:
                    ordered[sec] = {}
            # 알 수 없는 최상위 키가 있으면 뒤에 유지
            if isinstance(event_data, dict):
                for k, v in event_data.items():
                    if k not in ordered:
                        ordered[k] = v

            # 1. 기본 JSON 문자열 생성
            raw_json = json.dumps(ordered, indent=4, ensure_ascii=False)
            
            # 2. 정규식을 이용해 [x, y] 좌표 등을 한 줄로 합치기 (world_data 저장 로직과 동일)
            compact_json = re.sub(r'\[\s+(-?\d+\.?\d*),\s+(-?\d+\.?\d*)\s+\]', r'[\1, \2]', raw_json)
            # 3. steps 내부의 각 step dict를 한 줄로 압축
            compact_json = _compact_steps_to_single_lines(compact_json)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(compact_json)
            print("이벤트 데이터가 가독성 최적화되어 저장되었습니다!")
        except Exception as e:
            print(f"이벤트 저장 실패: {e}")


# ---------------------------------------------------------------------------
# [Presence zones] 체류 존 — 플레이어가 rect 안에 있을 때만 상태 오버레이, 이탈 시 복구
#
# world_data.json: presence_zones[]
#   rect, conditions, field(틸트/쉬어), player(TUNE 필드), targets[{name, ...TUNE}]
#
# event_zones 와 달리 진입 엣지 이벤트가 아니라, 체류(level) 동안만 적용 후 복구합니다.
# ---------------------------------------------------------------------------


def _presence_nonempty_str(val) -> bool:
    return str(val or "").strip() != ""


def _presence_parse_opt_float(val):
    if not _presence_nonempty_str(val):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _presence_parse_opt_int(val):
    if not _presence_nonempty_str(val):
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _presence_parse_opt_bool(val):
    if isinstance(val, bool):
        return val
    if not _presence_nonempty_str(val):
        return None
    s = str(val).strip().lower()
    if s in ("0", "false", "f", "no", "n", "off", ""):
        return False
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    return None


def build_tune_patch_from_dict(src: dict) -> dict:
    """TUNE/ACTION_ANIM 과 동일 의미 — 비어 있지 않은 필드만."""
    if not isinstance(src, dict):
        return {}
    out = {}
    st = _presence_parse_opt_float(src.get("sprite_tilt"))
    if st is not None:
        out["sprite_tilt"] = max(0.0, min(1.0, float(st)))
    h = _presence_parse_opt_float(src.get("height"))
    if h is not None:
        out["height"] = max(0.0, float(h))
    ys = str(src.get("ysort") or "").strip().lower()
    if ys in ("ground", "visual"):
        out["ysort"] = ys
    ly = _presence_parse_opt_int(src.get("layer"))
    if ly is not None:
        out["layer"] = int(ly)
    vb = _presence_parse_opt_bool(src.get("visible"))
    if vb is not None:
        out["visible"] = bool(vb)
    al = _presence_parse_opt_int(src.get("alpha"))
    if al is not None:
        out["alpha"] = max(0, min(255, int(al)))
    anim = str(src.get("anim") or src.get("state") or "").strip()
    if anim:
        out["anim"] = anim
    d = str(src.get("dir") or src.get("face") or "").strip().lower()
    if d in ("left", "l", "right", "r"):
        out["dir"] = "left" if d in ("left", "l") else "right"
    return out


def build_field_patch_from_dict(src: dict) -> dict:
    """화면(틸트/쉬어) 패치 — 비어 있지 않은 필드만."""
    if not isinstance(src, dict):
        return {}
    out = {}
    tt = _presence_parse_opt_float(src.get("tilt_target"))
    if tt is not None:
        out["tilt_target"] = max(0.02, min(1.0, float(tt)))
    sh_on = _presence_parse_opt_bool(src.get("shear_on"))
    if sh_on is not None:
        out["shear_on"] = bool(sh_on)
    sh_st = _presence_parse_opt_float(src.get("shear_strength"))
    if sh_st is not None:
        out["shear_strength"] = max(0.0, min(1.0, float(sh_st)))
    sh_px = _presence_parse_opt_int(src.get("shear_max_px"))
    if sh_px is not None:
        out["shear_max_px"] = max(0, min(256, int(sh_px)))
    return out


def capture_entity_tune_baseline(entity, patch: dict) -> dict:
    """패치에 들어 있는 키만 스냅샷."""
    base = {}
    if not patch:
        return base
    if "sprite_tilt" in patch:
        base["sprite_tilt"] = float(getattr(entity, "sprite_tilt", 1.0) or 1.0)
    if "height" in patch:
        base["height"] = float(getattr(entity, "height", 0) or 0)
    if "ysort" in patch:
        base["ysort"] = str(getattr(entity, "ysort_mode", "ground") or "ground")
    if "layer" in patch:
        base["layer"] = int(getattr(entity, "layer", 0) or 0)
    if "visible" in patch:
        if hasattr(entity, "is_visible"):
            base["visible"] = bool(getattr(entity, "is_visible", True))
        elif hasattr(entity, "visible"):
            base["visible"] = bool(getattr(entity, "visible", True))
    if "alpha" in patch:
        base["alpha"] = int(getattr(entity, "alpha", 255) or 255)
    if "hide_feet_shadow" in patch:
        base["hide_feet_shadow"] = bool(getattr(entity, "_hide_feet_shadow", False))
    if "dir" in patch:
        base["dir"] = str(getattr(entity, "direction", "right") or "right")
    if "anim" in patch:
        base["anim"] = str(getattr(entity, "state", "idle") or "idle")
        ao = getattr(entity, "_anim_override", None)
        base["_anim_override"] = copy.deepcopy(ao) if isinstance(ao, dict) else None
    return base


def apply_entity_tune_patch(entity, patch: dict) -> None:
    """engine TUNE 스텝과 동일 필드 적용."""
    if not patch or not entity:
        return
    try:
        from engine import _clamp_sprite_tilt, _clamp_draw_height, _normalize_ysort_mode
    except Exception:
        _clamp_sprite_tilt = lambda v: v
        _clamp_draw_height = lambda v: v
        _normalize_ysort_mode = lambda v: v or "ground"
    if "sprite_tilt" in patch and hasattr(entity, "sprite_tilt"):
        entity.sprite_tilt = _clamp_sprite_tilt(patch["sprite_tilt"])
    if "height" in patch and hasattr(entity, "height"):
        entity.height = _clamp_draw_height(patch["height"])
    if "ysort" in patch and hasattr(entity, "ysort_mode"):
        entity.ysort_mode = _normalize_ysort_mode(patch.get("ysort"))
    if "layer" in patch and hasattr(entity, "layer"):
        entity.layer = int(patch["layer"])
    if "visible" in patch:
        v = bool(patch["visible"])
        if hasattr(entity, "is_visible"):
            entity.is_visible = v
        elif hasattr(entity, "visible"):
            entity.visible = v
    if "alpha" in patch and hasattr(entity, "alpha"):
        entity.alpha = max(0, min(255, int(patch["alpha"])))
    if "hide_feet_shadow" in patch:
        v = patch["hide_feet_shadow"]
        if isinstance(v, str):
            entity._hide_feet_shadow = v.strip().lower() not in ("0", "false", "f", "no", "n", "off", "")
        else:
            entity._hide_feet_shadow = bool(v)
    if "dir" in patch and hasattr(entity, "direction"):
        entity.direction = patch["dir"]
    if "anim" in patch:
        try:
            from char_behavior import _apply_char_anim
            _apply_char_anim(entity, patch)
        except Exception:
            if hasattr(entity, "state"):
                entity.state = str(patch["anim"])


def restore_entity_tune_baseline(entity, baseline: dict) -> None:
    if not baseline or not entity:
        return
    patch = {k: v for k, v in baseline.items() if k not in ("_anim_override",)}
    apply_entity_tune_patch(entity, patch)
    if "_anim_override" in baseline:
        ao = baseline.get("_anim_override")
        clr = getattr(entity, "clear_anim_override", None)
        if callable(clr):
            clr()
        if isinstance(ao, dict):
            pa = getattr(entity, "play_anim", None)
            if callable(pa):
                try:
                    pa(
                        ao.get("state") or ao.get("anim") or "idle",
                        hold=bool(ao.get("loop")),
                    )
                except Exception:
                    pass


def _find_entity_by_name(name, player, objs, npcs):
    """name 또는 instance_id(예: frog01@64_416) 로 엔티티 검색."""
    n = str(name or "").strip()
    if not n:
        return None
    if n.lower() == "player":
        return player
    nl = n.lower()
    for pool in (npcs or []), (objs or []):
        for x in pool:
            try:
                iid = str(getattr(x, "instance_id", "") or "").strip()
                if iid and (iid == n or iid.lower() == nl):
                    return x
                xn = str(getattr(x, "name", "") or "")
                if xn == n or xn.lower() == nl:
                    return x
            except Exception:
                continue
    return None


def presence_zone_conditions_ok(zone: dict, save_data: dict, session_vars=None) -> bool:
    return zone_conditions_ok(zone, save_data, session_vars=session_vars)


def pick_presence_zone_index(zones, map_id, player_pos, save_data) -> int:
    """플레이어 위치·조건 — 첫 매칭 존 인덱스 (없으면 -1)."""
    px, py = player_pos[0], player_pos[1]
    for zi, z in enumerate(zones or []):
        if not isinstance(z, dict):
            continue
        if not presence_zone_conditions_ok(z, save_data):
            continue
        rect = z.get("rect")
        if not (isinstance(rect, (list, tuple)) and len(rect) >= 4):
            continue
        try:
            zx, zy, zw, zh = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
        except (TypeError, ValueError):
            continue
        if zw <= 0 or zh <= 0:
            continue
        if zx <= px <= zx + zw and zy <= py <= zy + zh:
            return int(zi)
    return -1


def _presence_point_in_zone_rect(zone: dict, player_pos) -> bool:
    if not isinstance(zone, dict):
        return False
    rect = zone.get("rect")
    if not (isinstance(rect, (list, tuple)) and len(rect) >= 4):
        return False
    try:
        px, py = float(player_pos[0]), float(player_pos[1])
        zx, zy, zw, zh = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
    except (TypeError, ValueError, IndexError):
        return False
    if zw <= 0 or zh <= 0:
        return False
    return zx <= px <= zx + zw and zy <= py <= zy + zh


def compile_presence_zone_overlays(zone: dict) -> dict:
    """존 진입 시 1회 — build_tune_patch 반복 비용 제거."""
    if not isinstance(zone, dict):
        return {}
    player_patch = build_tune_patch_from_dict(zone.get("player") or {})
    target_patches = []
    for row in zone.get("targets") or []:
        if not isinstance(row, dict):
            continue
        tname = str(row.get("name") or "").strip()
        if not tname or tname.lower() == "player":
            continue
        tpatch = build_tune_patch_from_dict(row)
        if tpatch:
            target_patches.append((tname, tpatch))
    field_patch = build_field_patch_from_dict(zone.get("field") or {})
    return {
        "player": player_patch,
        "targets": target_patches,
        "field": field_patch,
    }


class PresenceZoneRuntime:
    """
    체류 존 런타임 — main 루프에서 매 프레임 tick.
    이벤트 진행 중·activity 중에는 적용하지 않고, 활성 존이 있으면 복구합니다.
    """

    __slots__ = ("_active_key", "_baseline", "_overlay_compiled")

    def __init__(self):
        self._active_key = None  # (map_id, zone_index) | None
        self._baseline = {}  # entity_id or "__field__" -> snapshot
        self._overlay_compiled = None  # compile_presence_zone_overlays 결과

    def reset(self, map_id=None):
        if map_id is None:
            self._active_key = None
            self._baseline = {}
            self._overlay_compiled = None
        elif self._active_key and str(self._active_key[0]) == str(map_id):
            self._active_key = None
            self._baseline = {}
            self._overlay_compiled = None

    def _restore_all(self, player, objs, npcs, ev_mgr, ui):
        for key, snap in list(self._baseline.items()):
            if key == "__field__":
                try:
                    if "tilt_target" in snap and ui is not None:
                        ui.tilt_target = float(snap["tilt_target"])
                    if "tilt_current" in snap and ui is not None:
                        pass  # caller may set tilt_current separately
                    if ev_mgr is not None and "shear_control" in snap:
                        ev_mgr.shear_control = copy.deepcopy(snap["shear_control"])
                except Exception:
                    pass
                continue
            ent = None
            if key == "__player__":
                ent = player
            else:
                ent = _find_entity_by_name(key, player, objs, npcs)
            if ent is not None:
                restore_entity_tune_baseline(ent, snap)
        self._baseline = {}
        self._active_key = None
        self._overlay_compiled = None

    def _apply_zone_field_patch(self, zone: dict, ev_mgr, ui, field_patch=None):
        """화면(틸트/쉬어) — 존 진입 시 1회만. 보간은 main 루프 shear_smooth가 담당."""
        if field_patch is None:
            if not isinstance(zone, dict):
                return
            field_patch = build_field_patch_from_dict(zone.get("field") or {})
        if not field_patch:
            return
        if "tilt_target" in field_patch and ui is not None:
            ui.tilt_target = float(field_patch["tilt_target"])
        if ev_mgr is not None and any(
            k in field_patch for k in ("shear_on", "shear_strength", "shear_max_px")
        ):
            sc = {}
            if field_patch.get("shear_on") is False:
                sc["enabled"] = False
            else:
                sc["enabled"] = True
                if "shear_strength" in field_patch:
                    sc["strength_mul"] = float(field_patch["shear_strength"])
                if "shear_max_px" in field_patch:
                    sc["max_px"] = int(field_patch["shear_max_px"])
            ev_mgr.shear_control = sc

    def _apply_zone_entity_overlay(
        self,
        zone: dict,
        player,
        objs,
        npcs,
        *,
        compiled=None,
    ):
        """플레이어·지정 오브젝트 — 체류 중 매 프레임 재적용(layer 등 마스크 덮어쓰기 상쇄)."""
        if compiled is not None:
            player_patch = compiled.get("player") or {}
            target_patches = compiled.get("targets") or []
        else:
            if not isinstance(zone, dict):
                return
            player_patch = build_tune_patch_from_dict(zone.get("player") or {})
            target_patches = []
            target_rows = zone.get("targets") or []
            if not isinstance(target_rows, list):
                target_rows = []
            for row in target_rows:
                if not isinstance(row, dict):
                    continue
                tname = str(row.get("name") or "").strip()
                if not tname or tname.lower() == "player":
                    continue
                tpatch = build_tune_patch_from_dict(row)
                if tpatch:
                    target_patches.append((tname, tpatch))

        if player_patch and player is not None:
            apply_entity_tune_patch(player, player_patch)

        for tname, tpatch in target_patches:
            ent = _find_entity_by_name(tname, player, objs, npcs)
            if ent is None:
                continue
            apply_entity_tune_patch(ent, tpatch)

    def _apply_zone_overlay(
        self,
        zone: dict,
        player,
        objs,
        npcs,
        ev_mgr,
        ui,
        *,
        apply_field=False,
        compiled=None,
    ):
        if apply_field:
            fp = None
            if compiled is not None:
                fp = compiled.get("field") or {}
            self._apply_zone_field_patch(zone, ev_mgr, ui, field_patch=fp)
        self._apply_zone_entity_overlay(zone, player, objs, npcs, compiled=compiled)

    def _capture_zone_baseline(self, zone: dict, player, objs, npcs, ev_mgr, ui):
        """존 진입 시 1회 — 복구용 스냅샷."""
        if not isinstance(zone, dict):
            return
        field_patch = build_field_patch_from_dict(zone.get("field") or {})
        player_patch = build_tune_patch_from_dict(zone.get("player") or {})
        target_rows = zone.get("targets") or []
        if not isinstance(target_rows, list):
            target_rows = []

        if field_patch:
            fsnap = {}
            if "tilt_target" in field_patch and ui is not None:
                fsnap["tilt_target"] = float(ui.tilt_target)
            if ev_mgr is not None and any(
                k in field_patch for k in ("shear_on", "shear_strength", "shear_max_px")
            ):
                fsnap["shear_control"] = copy.deepcopy(getattr(ev_mgr, "shear_control", None))
            if fsnap:
                self._baseline["__field__"] = fsnap

        if player_patch and player is not None:
            self._baseline["__player__"] = capture_entity_tune_baseline(player, player_patch)

        for row in target_rows:
            if not isinstance(row, dict):
                continue
            tname = str(row.get("name") or "").strip()
            if not tname or tname.lower() == "player":
                continue
            tpatch = build_tune_patch_from_dict(row)
            if not tpatch:
                continue
            ent = _find_entity_by_name(tname, player, objs, npcs)
            if ent is None:
                continue
            self._baseline[tname] = capture_entity_tune_baseline(ent, tpatch)

    def tick(
        self,
        map_id,
        player_pos,
        player,
        objs,
        npcs,
        ev_mgr,
        ui,
        world_data,
        save_data,
        *,
        blocked=False,
        tilt_current_holder=None,
    ):
        """
        blocked=True: 이벤트·activity 등 — 활성 오버레이 해제.
        tilt_current_holder: {"value": float} — 복구 시 tilt_current 동기화용(선택).
        """
        if blocked:
            if self._active_key is not None:
                field_snap = self._baseline.get("__field__")
                self._restore_all(player, objs, npcs, ev_mgr, ui)
                if (
                    tilt_current_holder is not None
                    and isinstance(field_snap, dict)
                    and "tilt_target" in field_snap
                ):
                    try:
                        tilt_current_holder["value"] = float(field_snap["tilt_target"])
                    except Exception:
                        pass
            return

        m = (world_data or {}).get(map_id, {}) if map_id else {}
        zones = m.get("presence_zones", []) or []
        if not zones:
            if self._active_key is not None:
                field_snap = self._baseline.get("__field__")
                self._restore_all(player, objs, npcs, ev_mgr, ui)
                if (
                    tilt_current_holder is not None
                    and isinstance(field_snap, dict)
                    and "tilt_target" in field_snap
                ):
                    try:
                        tilt_current_holder["value"] = float(field_snap["tilt_target"])
                    except Exception:
                        pass
            return

        hit = -1
        if self._active_key is not None and str(self._active_key[0]) == str(map_id):
            zi_prev = int(self._active_key[1])
            if 0 <= zi_prev < len(zones):
                z_prev = zones[zi_prev]
                if presence_zone_conditions_ok(z_prev, save_data) and _presence_point_in_zone_rect(
                    z_prev, player_pos
                ):
                    hit = zi_prev
        if hit < 0:
            hit = pick_presence_zone_index(zones, map_id, player_pos, save_data)
        new_key = (str(map_id), int(hit)) if hit >= 0 else None

        if new_key == self._active_key:
            if new_key is not None and 0 <= new_key[1] < len(zones):
                self._apply_zone_overlay(
                    zones[new_key[1]],
                    player,
                    objs,
                    npcs,
                    ev_mgr,
                    ui,
                    apply_field=False,
                    compiled=self._overlay_compiled,
                )
            return

        self._restore_all(player, objs, npcs, ev_mgr, ui)

        if new_key is None:
            self._overlay_compiled = None
            return

        zi = new_key[1]
        zone = zones[zi] if 0 <= zi < len(zones) else None
        if not isinstance(zone, dict):
            self._overlay_compiled = None
            return

        self._capture_zone_baseline(zone, player, objs, npcs, ev_mgr, ui)
        self._overlay_compiled = compile_presence_zone_overlays(zone)
        self._apply_zone_overlay(
            zone,
            player,
            objs,
            npcs,
            ev_mgr,
            ui,
            apply_field=True,
            compiled=self._overlay_compiled,
        )
        self._active_key = new_key

"""오브젝트·캐릭터 타입 정의(JSON) 로드/저장 및 에디터 배치 리스트 헬퍼."""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
OBJECT_DEFS_PATH = _ROOT / "object_defs.json"
CHAR_DEFS_PATH = _ROOT / "char_defs.json"

# 맵 배치 리스트: 단순·대량 배치 카테고리(풀·타일 등)를 먼저 묶음
PLACED_LIST_SIMPLE_CATEGORIES = frozenset({
    "자연/식물",
    "타일류",
    "UI",
})

_PLACED_LIST_CATEGORY_ORDER = [
    "자연/식물",
    "타일류",
    "UI",
    "ETC (기타)",
    "건축물류",
    "가구류",
    "나무류",
    "그네류",
    "차량류",
    "들 수 있는 물건",
    "슬롯",
    "미니게임",
]


def load_object_defs():
    with open(OBJECT_DEFS_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_char_defs():
    with open(CHAR_DEFS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_object_defs(data):
    with open(OBJECT_DEFS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_char_defs(data):
    with open(CHAR_DEFS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_object_category(name, obj_defs):
    info = obj_defs.get(name, {})
    return str(info.get("category") or "ETC (기타)")


def placed_list_category_order(categories):
    cats = set(categories)
    ordered = []
    for cat in _PLACED_LIST_CATEGORY_ORDER:
        if cat in cats:
            ordered.append(cat)
    for cat in sorted(cats):
        if cat not in ordered:
            ordered.append(cat)
    return ordered


def reload_entity_defs():
    """JSON 재로드 후 data 모듈 별칭 갱신."""
    import data

    data.OBJ_ASSETS.clear()
    data.OBJ_ASSETS.update(load_object_defs())
    data.CHAR_ASSETS.clear()
    data.CHAR_ASSETS.update(load_char_defs())
    return data.OBJ_ASSETS, data.CHAR_ASSETS


def _sort_nodes(nodes):
    return sorted(nodes, key=lambda n: (n.name, n.pos[0], n.pos[1]))


def _instance_labels(nodes):
    """동일 name이 여러 개면 name #1, #2 …"""
    counts = {}
    for n in nodes:
        counts[n.name] = counts.get(n.name, 0) + 1
    seen = {}
    labels = {}
    for n in nodes:
        if counts[n.name] <= 1:
            labels[id(n)] = n.name
            continue
        seen[n.name] = seen.get(n.name, 0) + 1
        labels[id(n)] = f"{n.name} #{seen[n.name]}"
    return labels


def build_editor_placed_list_rows(objs, npcs, obj_defs=None):
    """에디터 좌측 '맵 배치' 리스트용 행. kind: header | npc | obj."""
    if obj_defs is None:
        from data import OBJ_ASSETS
        obj_defs = OBJ_ASSETS

    rows = []

    npc_list = _sort_nodes(npcs)
    if npc_list:
        rows.append({"kind": "header", "label": "캐릭터 (NPC)"})
        labels = _instance_labels(npc_list)
        for n in npc_list:
            rows.append({
                "kind": "npc",
                "node": n,
                "label": labels[id(n)],
            })

    by_cat = {}
    for o in objs:
        cat = get_object_category(o.name, obj_defs)
        by_cat.setdefault(cat, []).append(o)

    for cat in placed_list_category_order(by_cat.keys()):
        nodes = _sort_nodes(by_cat[cat])
        if not nodes:
            continue
        rows.append({"kind": "header", "label": cat})
        labels = _instance_labels(nodes)
        for o in nodes:
            rows.append({
                "kind": "obj",
                "node": o,
                "label": labels[id(o)],
                "category": cat,
            })

    return rows


def editor_placed_list_row_count(rows):
    return len(rows)

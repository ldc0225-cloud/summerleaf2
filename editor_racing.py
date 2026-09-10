"""에디터 RACING 모드 — 레이스 경로(제어점→곡선) 맵 픽 + world_data.racing 설정.

editor.py 가 이벤트/그리기 훅으로 호출. 야구(editor_baseball)와 같은 패턴.

[편집 가능 항목]
  - 경로 path(제어점) / 루프 closed / curve_tension(코너 둥글기)
  - 아이템 items: kind(normal|secret|roulette|summon), type(speed|slow|swap), lane, s
  - 청정구간 clean_zones, 날씨 weather, 슬립스트림·시크릿 룰렛 등 (설정 모달)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import pygame

import editor_text as ed_txt

from data import (
    RACING_DEFAULTS,
    RACING_ITEM_TYPES,
    RACING_LANE_LETTERS,
    RACING_MYSTERY_EFFECT_POOL,
)

# 아이템 kind — 경로 배치 시 동작 분기 (activities.racing RaceItemPoint.kind)
RACING_ITEM_KINDS = ("normal", "secret", "roulette", "summon")
RACING_ITEM_KIND_LABELS = {
    "normal": "일반",
    "secret": "시크릿",
    "roulette": "룰렛발판",
    "summon": "소환발판",
}
# 시크릿/룰렛/소환에 쓰이는 실제 효과 type (speed/slow/swap)
RACING_EFFECT_TYPES = list(RACING_MYSTERY_EFFECT_POOL) or ["speed", "slow", "swap"]
_ROULETTE_PERIOD_PRESETS = (0.35, 0.5, 0.75, 1.0, 1.25)

EDITOR_RC_LINE_H = 22
HIT_PX = 14.0  # 맵 화면 기준 포인트 픽 반경(대략)


def new_state() -> dict:
    return {
        "tool": "PATH",  # PATH | POINTS | ITEMS | SETTINGS
        "path": [],
        "closed": True,
        "items": [],  # [{s, lane, type, strength, duration_sec, asset}, ...]
        "selected_ix": None,
        "selected_item_ix": None,
        "dragging": False,
        "dragging_item": False,
        "show_settings": False,
        "settings_fields": {},
        "pick_xy_key": None,  # exit_pos
        "settings_scroll": 0,
        "_edit_field": None,
        "dirty": False,
        "hint": "맵 클릭으로 경로 점 추가",
        "text_edit": ed_txt.EditSession(),
    }


def _te(state) -> ed_txt.EditSession:
    te = state.get("text_edit")
    if not isinstance(te, ed_txt.EditSession):
        te = ed_txt.EditSession()
        state["text_edit"] = te
    return te


# --- world_data.racing -----------------------------------------------------

RACING_EDITOR_SCALAR_KEYS = [
    ("laps", "랩 수", "int", 3),
    ("lane_width", "차선 폭(px)", "float", 30.0),
    ("start_s", "스타트 s", "float", 0.0),
    ("start_spacing", "스타트 간격", "float", 22.0),
    ("curve_tension", "곡선 장력(0둥글~1직선)", "float", 0.0),
    ("curve_samples_per_seg", "곡선 샘플/구간", "int", 20),
    ("max_speed", "최고속", "float", 130.0),
    ("min_corner_speed", "코너 최저속", "float", 42.0),
    ("accel", "가속", "float", 52.0),
    ("brake", "감속", "float", 95.0),
    ("corner_brake", "코너 감속계수", "float", 1.4),
    ("corner_lookahead_px", "코너 예견거리", "float", 90.0),
    ("cam_side_sign", "옆시야 부호(+1/-1)", "float", -1.0),
    ("cam_turn_rate_rad", "카메라 추종", "float", 3.4),
    ("countdown_sec", "카운트다운(초)", "float", 3.0),
    ("item_pick_radius", "아이템 획득반경", "float", 18.0),
    ("item_random_enabled", "랜덤아이템(1/0)", "bool", 0),
    ("item_random_count", "랜덤 개수", "int", 6),
    # --- 아이템/날씨/슬립스트림 (data.py RACING_DEFAULTS 와 동일 키) ---
    ("secret_spin_sec", "시크릿 룰렛(초)", "float", 1.35),
    ("roulette_lane_period_sec", "룰렛발판 기본주기", "float", 0.55),
    ("summon_flash_sec", "소환 번쩍(초)", "float", 1.6),
    ("slipstream_min_speed_frac", "슬립 최소속도비", "float", 0.90),
    ("slipstream_follow_s", "슬립 추종거리", "float", 72.0),
    ("slipstream_lane_tol", "슬립 레인허용", "float", 0.42),
    ("slipstream_hold_sec", "슬립 충전(초)", "float", 1.0),
    ("slipstream_boost_mul", "슬립 부스트배율", "float", 1.20),
    ("slipstream_accel_bonus", "슬립 가속보너스", "float", 18.0),
    ("afterburner_len_speed", "에프터길이(스피드업)", "float", 36.0),
    ("afterburner_len_slip", "에프터길이(최고속)", "float", 72.0),
    ("slipstream_bump_s", "추돌 거리", "float", 22.0),
    ("slipstream_bump_front_boost", "추돌 앞가속", "float", 1.35),
    ("slipstream_bump_rear_slow", "추돌 뒤감속", "float", 0.45),
    ("slipstream_bump_slow_sec", "추돌 둔화(초)", "float", 1.4),
]

# 날씨 — world_data.racing.weather 에 저장 (에디터는 평탄 필드로 편집)
RACING_EDITOR_WEATHER_KEYS = [
    ("weather_enabled", "날씨 사용", "bool", 1),
    ("weather_rain_chance", "비 확률/랩", "float", 0.45),
    ("weather_rain_zone_min", "비 구간최소(s)", "float", 70.0),
    ("weather_rain_zone_max", "비 구간최대(s)", "float", 160.0),
    ("weather_rain_slow_mul", "비 감속배율", "float", 0.72),
    ("weather_lightning_chance", "번개 확률/랩", "float", 0.22),
    ("weather_lightning_zone_min", "번개 구간최소", "float", 40.0),
    ("weather_lightning_zone_max", "번개 구간최대", "float", 90.0),
    ("weather_lightning_strike", "번개 진입명중(0~1)", "float", 1.0),
    ("weather_lightning_freeze", "번개 정지(초)", "float", 1.15),
]

RACING_EDITOR_XY_KEYS = [
    ("exit_pos", "퇴장 좌표"),
]

RACING_EDITOR_TEXT_KEYS = [
    ("exit_map", "퇴장 맵", "bg_jjangpu"),
    # 청정 구간: "0,140; 2850,2992" (s0,s1 쌍 · 세미콜론 구분) — 아이템·날씨 무효과
    ("clean_zones", "청정구간(아이템·날씨없음)", ""),
]


def _parse_float(s, default=0.0) -> float:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return float(default)


def _parse_int(s, default=0) -> int:
    try:
        return int(float(str(s).strip()))
    except (TypeError, ValueError):
        return int(default)


def _parse_xy(text: str, default=(0.0, 0.0)) -> Tuple[float, float]:
    t = str(text or "").strip().replace("[", "").replace("]", "")
    parts = [p.strip() for p in t.split(",") if p.strip()]
    if len(parts) >= 2:
        return _parse_float(parts[0], default[0]), _parse_float(parts[1], default[1])
    return default


def _xy_to_text(v) -> str:
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return f"{float(v[0]):g}, {float(v[1]):g}"
    return "0, 0"


def load_racing_cfg(flow, map_id: str) -> dict:
    """기본값 + world_data[map].racing 병합."""
    cfg = dict(RACING_DEFAULTS)
    try:
        row = (flow.world_data or {}).get(map_id, {}).get("racing") or {}
        if isinstance(row, dict):
            cfg.update(row)
    except Exception:
        pass
    return cfg


def _parse_bool(s, default=False) -> bool:
    if isinstance(s, bool):
        return s
    return str(s).strip().lower() in ("1", "true", "yes", "on")


def _clean_zones_to_text(zones) -> str:
    """[[s0,s1],...] → 에디터 문자열."""
    if not isinstance(zones, list):
        return ""
    parts = []
    for row in zones:
        try:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                a, b = float(row[0]), float(row[1])
                parts.append(f"{a:g},{b:g}")
        except (TypeError, ValueError):
            continue
    return "; ".join(parts)


def _text_to_clean_zones(text: str) -> List[List[float]]:
    """에디터 문자열 → [[s0,s1], ...]."""
    out: List[List[float]] = []
    raw = str(text or "").strip()
    if not raw:
        return out
    for chunk in raw.replace("\n", ";").split(";"):
        chunk = chunk.strip().replace("[", "").replace("]", "")
        if not chunk:
            continue
        nums = [p.strip() for p in chunk.split(",") if p.strip()]
        if len(nums) < 2:
            continue
        try:
            a, b = float(nums[0]), float(nums[1])
            if b < a:
                a, b = b, a
            out.append([round(a, 2), round(b, 2)])
        except (TypeError, ValueError):
            continue
    return out


def _weather_cfg_to_flat(cfg: dict) -> Dict[str, str]:
    """world_data.weather → 설정 모달용 평탄 필드."""
    w = cfg.get("weather") if isinstance(cfg.get("weather"), dict) else {}
    rain = w.get("rain") if isinstance(w.get("rain"), dict) else {}
    lig = w.get("lightning") if isinstance(w.get("lightning"), dict) else {}
    zr = rain.get("zone_len_s") or [70.0, 160.0]
    zl = lig.get("zone_len_s") or [40.0, 90.0]
    try:
        zr0 = float(zr[0]) if isinstance(zr, (list, tuple)) else 70.0
        zr1 = float(zr[1]) if isinstance(zr, (list, tuple)) and len(zr) > 1 else zr0
    except (TypeError, ValueError, IndexError):
        zr0, zr1 = 70.0, 160.0
    try:
        zl0 = float(zl[0]) if isinstance(zl, (list, tuple)) else 40.0
        zl1 = float(zl[1]) if isinstance(zl, (list, tuple)) and len(zl) > 1 else zl0
    except (TypeError, ValueError, IndexError):
        zl0, zl1 = 40.0, 90.0
    return {
        "weather_enabled": "1" if bool(w.get("enabled", True)) else "0",
        "weather_rain_chance": str(rain.get("chance_per_lap", 0.45)),
        "weather_rain_zone_min": str(zr0),
        "weather_rain_zone_max": str(zr1),
        "weather_rain_slow_mul": str(rain.get("slow_mul", 0.72)),
        "weather_lightning_chance": str(lig.get("chance_per_lap", 0.22)),
        "weather_lightning_zone_min": str(zl0),
        "weather_lightning_zone_max": str(zl1),
        "weather_lightning_strike": str(lig.get("strike_chance", 1.0)),
        "weather_lightning_freeze": str(lig.get("freeze_sec", 1.15)),
    }


def _flat_to_weather_cfg(fields: dict) -> dict:
    """설정 모달 평탄 필드 → world_data.weather."""
    return {
        "enabled": _parse_bool(fields.get("weather_enabled", "1"), True),
        "rain": {
            "chance_per_lap": _parse_float(fields.get("weather_rain_chance"), 0.45),
            "zone_len_s": [
                _parse_float(fields.get("weather_rain_zone_min"), 70.0),
                _parse_float(fields.get("weather_rain_zone_max"), 160.0),
            ],
            "slow_mul": _parse_float(fields.get("weather_rain_slow_mul"), 0.72),
        },
        "lightning": {
            "chance_per_lap": _parse_float(fields.get("weather_lightning_chance"), 0.22),
            "zone_len_s": [
                _parse_float(fields.get("weather_lightning_zone_min"), 40.0),
                _parse_float(fields.get("weather_lightning_zone_max"), 90.0),
            ],
            "strike_chance": _parse_float(fields.get("weather_lightning_strike"), 1.0),
            "freeze_sec": _parse_float(fields.get("weather_lightning_freeze"), 1.15),
        },
    }


def _item_kind_color(kind: str, type_id: str) -> Tuple[int, int, int]:
    """맵 오버레이용 아이템 색."""
    k = str(kind or "normal").lower()
    if k == "secret":
        return (255, 210, 80)
    if k == "roulette":
        return (100, 180, 255)
    if k == "summon":
        return (255, 160, 60)
    info = RACING_ITEM_TYPES.get(str(type_id or "speed")) or {}
    col = info.get("placeholder_color") or (180, 180, 200)
    return tuple(col[:3])  # type: ignore


def _normalize_item(raw) -> dict:
    """아이템 포인트 정규화 (kind · roulette_period_sec 포함)."""
    if not isinstance(raw, dict):
        raw = {}
    kind = str(raw.get("kind") or "normal").strip().lower() or "normal"
    if kind not in RACING_ITEM_KINDS:
        kind = "normal"
    tid = str(raw.get("type") or "speed").strip().lower() or "speed"
    if tid not in RACING_EFFECT_TYPES:
        if kind == "summon":
            tid = "speed"
        elif tid in RACING_ITEM_TYPES and str(RACING_ITEM_TYPES[tid].get("effect")) == "speed_mul":
            pass
        else:
            tid = "speed"
    info = RACING_ITEM_TYPES.get(tid) or RACING_ITEM_TYPES.get("speed") or {}
    lane = str(raw.get("lane") or "B").strip().upper() or "B"
    if lane not in RACING_LANE_LETTERS:
        lane = "B"
    try:
        s = float(raw.get("s", 0.0) or 0.0)
    except (TypeError, ValueError):
        s = 0.0
    try:
        strength = float(raw.get("strength", info.get("strength", 1.0)) or 1.0)
    except (TypeError, ValueError):
        strength = float(info.get("strength", 1.0) or 1.0)
    try:
        dur = float(raw.get("duration_sec", info.get("duration_sec", 2.0)) or 2.0)
    except (TypeError, ValueError):
        dur = 2.0
    asset = str(raw.get("asset") or info.get("asset") or "item_racing001").strip()
    try:
        rps = float(
            raw.get("roulette_period_sec")
            or raw.get("roulette_period")
            or RACING_DEFAULTS.get("roulette_lane_period_sec", 0.55)
            or 0.55
        )
    except (TypeError, ValueError):
        rps = 0.55
    rps = max(0.2, min(3.0, rps))
    consume = _parse_bool(
        raw.get("consume", raw.get("despawn", raw.get("remove_on_pickup", False))),
        False,
    )
    out = {
        "s": round(s, 2),
        "lane": lane,
        "type": tid,
        "kind": kind,
        "strength": round(strength, 3),
        "duration_sec": round(dur, 2),
        "asset": asset,
        "consume": bool(consume),
    }
    if kind == "roulette":
        out["roulette_period_sec"] = round(rps, 2)
    return out


def _default_item_at(s: float, *, lane: str = "B", type_id: str = "speed") -> dict:
    return _normalize_item({"s": s, "lane": lane, "type": type_id})


def _race_path_from_state(state):
    """에디터 path → RacePath (곡선 샘플·아이템 s 투영·오버레이용)."""
    from activities.racing import build_race_path

    path = state.get("path") or []
    fields = state.get("settings_fields") or {}
    cfg = {
        "curve_tension": fields.get(
            "curve_tension", RACING_DEFAULTS.get("curve_tension", 0.0)
        ),
        "curve_samples_per_seg": fields.get(
            "curve_samples_per_seg", RACING_DEFAULTS.get("curve_samples_per_seg", 20)
        ),
    }
    return build_race_path(path, closed=bool(state.get("closed", True)), cfg=cfg)


def _item_world_xy(state, item: dict) -> Optional[Tuple[float, float]]:
    path_pts = state.get("path") or []
    if len(path_pts) < 2:
        return None
    try:
        rp = _race_path_from_state(state)
        s = float(item.get("s", 0.0) or 0.0)
        x, y, tang, _ = rp.sample(s)
        lane = str(item.get("lane") or "B").upper()
        off = float(RACING_LANE_LETTERS.get(lane, 0.0))
        fields = state.get("settings_fields") or {}
        lane_w = _parse_float(
            fields.get("lane_width", RACING_DEFAULTS.get("lane_width", 30.0)),
            30.0,
        )
        nx = -math.sin(tang)
        ny = math.cos(tang)
        return float(x) + nx * off * lane_w, float(y) + ny * off * lane_w
    except Exception:
        return None


def load_path_into_state(state, flow, map_id: str) -> None:
    cfg = load_racing_cfg(flow, map_id)
    pts = []
    raw = cfg.get("path") or []
    for p in raw:
        try:
            pts.append([float(p[0]), float(p[1])])
        except (TypeError, ValueError, IndexError):
            continue
    state["path"] = pts
    state["closed"] = bool(cfg.get("closed", True))
    state["items"] = [_normalize_item(it) for it in (cfg.get("items") or [])]
    state["selected_ix"] = None
    state["selected_item_ix"] = None
    state["dragging"] = False
    state["dragging_item"] = False
    state["dirty"] = False
    state["settings_fields"] = load_settings_fields(flow, map_id)
    # 게임에서 실제로 생성할 도로 설정을 에디터 미리보기에 그대로 사용.
    state["_road_preview_cfg"] = {
        "road_draw_enabled": bool(cfg.get("road_draw_enabled", True)),
        "road_lane_colors": cfg.get(
            "road_lane_colors", RACING_DEFAULTS.get("road_lane_colors")
        ),
        "road_border_color": cfg.get(
            "road_border_color", RACING_DEFAULTS.get("road_border_color")
        ),
        "road_border_px": cfg.get(
            "road_border_px", RACING_DEFAULTS.get("road_border_px", 3.0)
        ),
    }
    state["hint"] = f"경로 {len(pts)}점 · 아이템 {len(state['items'])}개"


def load_settings_fields(flow, map_id: str) -> dict:
    cfg = load_racing_cfg(flow, map_id)
    fields: Dict[str, str] = {}
    for key, _label, typ, default in RACING_EDITOR_SCALAR_KEYS:
        v = cfg.get(key, default)
        if typ == "bool":
            if isinstance(v, str):
                fields[key] = "1" if v.strip().lower() in ("1", "true", "yes", "on") else "0"
            else:
                fields[key] = "1" if bool(v) else "0"
        else:
            fields[key] = str(v)
    for key, _label, typ, default in RACING_EDITOR_WEATHER_KEYS:
        flat = _weather_cfg_to_flat(cfg)
        v = flat.get(key)
        if v is None:
            v = default
        if typ == "bool":
            fields[key] = "1" if _parse_bool(v, bool(default)) else "0"
        else:
            fields[key] = str(v)
    for key, _label in RACING_EDITOR_XY_KEYS:
        fields[key] = _xy_to_text(cfg.get(key))
    for key, _label, default in RACING_EDITOR_TEXT_KEYS:
        if key == "clean_zones":
            fields[key] = _clean_zones_to_text(cfg.get("clean_zones"))
        else:
            fields[key] = str(cfg.get(key, default) or default)
    fields["closed"] = "1" if bool(cfg.get("closed", True)) else "0"
    return fields


def racing_config_to_world_row(cfg: dict) -> dict:
    """저장용 슬림 dict (path + items + 주요 키)."""
    row: Dict[str, Any] = {}
    pts = cfg.get("path") or []
    row["path"] = [[float(p[0]), float(p[1])] for p in pts if len(p) >= 2]
    row["closed"] = bool(cfg.get("closed", True))
    for key, _label, typ, default in RACING_EDITOR_SCALAR_KEYS:
        v = cfg.get(key, default)
        if typ == "int":
            row[key] = int(v)
        elif typ == "bool":
            if isinstance(v, str):
                row[key] = str(v).strip().lower() in ("1", "true", "yes", "on")
            else:
                row[key] = bool(v)
        else:
            row[key] = float(v)
    for key, _label in RACING_EDITOR_XY_KEYS:
        v = cfg.get(key)
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            row[key] = [float(v[0]), float(v[1])]
    for key, _label, default in RACING_EDITOR_TEXT_KEYS:
        if key == "clean_zones":
            cz = cfg.get("clean_zones")
            if isinstance(cz, list):
                row["clean_zones"] = cz
            else:
                row["clean_zones"] = _text_to_clean_zones(str(cz or ""))
        else:
            row[key] = str(cfg.get(key, default) or default).strip()
    w = cfg.get("weather")
    if isinstance(w, dict):
        row["weather"] = w
    # 에디터 저장 시 맵별 자동 도로 설정이 유실되지 않도록 보존.
    row["road_draw_enabled"] = bool(cfg.get("road_draw_enabled", True))
    row["road_lane_colors"] = cfg.get(
        "road_lane_colors", RACING_DEFAULTS.get("road_lane_colors")
    )
    row["road_border_color"] = cfg.get(
        "road_border_color", RACING_DEFAULTS.get("road_border_color")
    )
    row["road_border_px"] = float(
        cfg.get("road_border_px", RACING_DEFAULTS.get("road_border_px", 3.0))
    )
    row["items"] = [_normalize_item(it) for it in (cfg.get("items") or [])]
    return row


def apply_settings_fields(state, flow, map_id: str) -> None:
    """설정 필드 + 현재 path/items 를 world_data 에 기록."""
    fields = state.get("settings_fields") or load_settings_fields(flow, map_id)
    cfg = load_racing_cfg(flow, map_id)
    for key, _label, typ, default in RACING_EDITOR_SCALAR_KEYS:
        raw = fields.get(key, str(default))
        if typ == "int":
            cfg[key] = _parse_int(raw, default)
        elif typ == "bool":
            cfg[key] = str(raw).strip().lower() in ("1", "true", "yes", "on")
        else:
            cfg[key] = _parse_float(raw, default)
    cfg["weather"] = _flat_to_weather_cfg(fields)
    for key, _label in RACING_EDITOR_XY_KEYS:
        cfg[key] = list(_parse_xy(str(fields.get(key, "") or "0, 0")))
    for key, _label, default in RACING_EDITOR_TEXT_KEYS:
        if key == "clean_zones":
            cfg["clean_zones"] = _text_to_clean_zones(str(fields.get(key, "") or ""))
        else:
            cfg[key] = str(fields.get(key, default) or default).strip()
    closed_raw = str(fields.get("closed", "1") or "1").strip().lower()
    cfg["closed"] = closed_raw in ("1", "true", "yes", "on")
    # 에디터 path / items 우선
    path = state.get("path") or []
    if path:
        cfg["path"] = [[float(p[0]), float(p[1])] for p in path]
        cfg["closed"] = bool(state.get("closed", cfg["closed"]))
    cfg["items"] = [_normalize_item(it) for it in (state.get("items") or [])]
    row = racing_config_to_world_row(cfg)
    flow.world_data.setdefault(map_id, {})["racing"] = row
    state["closed"] = bool(row.get("closed", True))
    state["items"] = list(row.get("items") or [])
    state["dirty"] = False
    n_cz = len(row.get("clean_zones") or [])
    state["hint"] = (
        f"저장됨 · 경로 {len(row.get('path') or [])} · "
        f"아이템 {len(row.get('items') or [])} · 청정 {n_cz}"
    )


def commit_path_to_world(state, flow, map_id: str) -> None:
    """경로만 즉시 world_data 반영 (S 저장 전에도 메모리 유지)."""
    apply_settings_fields(state, flow, map_id)


def on_map_switch(state, flow, map_id: str) -> None:
    load_path_into_state(state, flow, map_id)
    state["show_settings"] = False
    state["pick_xy_key"] = None
    state["_edit_field"] = None


# --- layout / UI -----------------------------------------------------------

def left_list_tops(top_bar_h: int, state=None) -> dict:
    tb = int(top_bar_h)
    tools = tb + 38
    actions = tools + 32
    # tool=ITEMS 에서는 action 버튼이 10개.
    # 값이 작으면 리스트가 겹치며 폰트가 잘려/겹쳐 보일 수 있음.
    n_act = 10
    if state is not None and str(state.get("tool") or "") != "ITEMS":
        n_act = 5
    list_header = actions + n_act * 28 + 16
    return {
        "tools": tools,
        "actions": actions,
        "list_header": list_header,
        "list": list_header + 20,
    }


def sidebar_list_metrics(top_bar_h: int, state) -> Tuple[int, int]:
    tops = left_list_tops(top_bar_h, state)
    tool = str(state.get("tool") or "PATH")
    if tool == "ITEMS":
        n = len(state.get("items") or [])
    else:
        n = len(state.get("path") or [])
    return tops["list"], n * EDITOR_RC_LINE_H


def draw_left_panel(
    screen,
    font,
    title_font,
    state,
    map_id,
    top_bar_h,
    sidebar_w,
    map_view_h,
    *,
    list_scroll=0,
):
    tops = left_list_tops(top_bar_h, state)
    screen.blit(
        font.render(f"맵: {map_id}", True, (200, 220, 255)),
        (8, tops["tools"] - 22),
    )

    tool = str(state.get("tool") or "PATH")
    tw = max(36, (sidebar_w - 32) // 4)
    btn_p = pygame.Rect(8, tops["tools"], tw, 26)
    btn_e = pygame.Rect(btn_p.right + 4, tops["tools"], tw, 26)
    btn_i = pygame.Rect(btn_e.right + 4, tops["tools"], tw, 26)
    btn_s = pygame.Rect(btn_i.right + 4, tops["tools"], tw, 26)
    for b, lab, key in (
        (btn_p, "경로", "PATH"),
        (btn_e, "점", "POINTS"),
        (btn_i, "아이템", "ITEMS"),
        (btn_s, "설정", "SETTINGS"),
    ):
        pygame.draw.rect(screen, (70, 70, 70), b)
        if tool == key:
            pygame.draw.rect(screen, (255, 215, 0), b, 2)
        screen.blit(font.render(lab, True, (255, 255, 255)), (b.x + 4, b.y + 4))

    y = tops["actions"]
    bw = sidebar_w - 16
    if tool == "ITEMS":
        sel = state.get("selected_item_ix")
        items = state.get("items") or []
        cur = items[int(sel)] if sel is not None and 0 <= int(sel) < len(items) else None
        kind_lab = RACING_ITEM_KIND_LABELS.get(str((cur or {}).get("kind") or "normal"), "일반")
        type_lab = (cur or {}).get("type", "-")
        lane_set = _item_group_lane_set(items, sel)
        consume_on = bool((cur or {}).get("consume", False))
        actions = [
            ("cycle_item_kind", f"배치: {kind_lab}"),
            ("cycle_item_type", f"효과: {type_lab}"),
            ("toggle_consume", f"획득후소모: {'ON' if consume_on else 'OFF'}"),
            ("toggle_lane_A", f"[{'x' if 'A' in lane_set else ' '}] 레인 A"),
            ("toggle_lane_B", f"[{'x' if 'B' in lane_set else ' '}] 레인 B"),
            ("toggle_lane_C", f"[{'x' if 'C' in lane_set else ' '}] 레인 C"),
            ("cycle_roulette_period", "룰렛 주기(발판)"),
            ("delete_item", "선택 아이템 삭제"),
            ("save_racing", "아이템 적용(메모리)"),
            ("open_settings", "레이스 설정…"),
        ]
    else:
        actions = [
            ("toggle_closed", f"루프: {'ON' if state.get('closed') else 'OFF'}"),
            ("undo_point", "마지막 점 삭제"),
            ("clear_path", "경로 비우기"),
            ("save_racing", "경로 적용(메모리)"),
            ("open_settings", "레이스 설정…"),
        ]
    for i, (act, lab) in enumerate(actions):
        r = pygame.Rect(8, y + i * 28, bw, 24)
        pygame.draw.rect(screen, (50, 60, 80), r)
        screen.blit(font.render(lab[:28], True, (230, 240, 255)), (r.x + 6, r.y + 4))

    pygame.draw.line(
        screen,
        (70, 80, 70),
        (8, tops["list_header"]),
        (sidebar_w - 8, tops["list_header"]),
        1,
    )
    if tool == "ITEMS":
        n = len(state.get("items") or [])
        screen.blit(
            title_font.render(f"ITEMS ({n})", True, (255, 220, 160)),
            (10, tops["list_header"] + 2),
        )
        y0 = tops["list"] - int(list_scroll or 0)
        sel = state.get("selected_item_ix")
        for i, it in enumerate(state.get("items") or []):
            r = pygame.Rect(8, y0, sidebar_w - 16, EDITOR_RC_LINE_H)
            if r.bottom > top_bar_h and r.top < top_bar_h + map_view_h:
                if sel == i:
                    pygame.draw.rect(screen, (80, 70, 40), r)
                kind = str(it.get("kind") or "normal")
                klab = RACING_ITEM_KIND_LABELS.get(kind, kind)[:4]
                cons = "소모" if it.get("consume") else "유지"
                lab = (
                    f"{i:02d} {klab} {it.get('type','?')} "
                    f"{it.get('lane','B')} {cons} s={float(it.get('s',0)):.0f}"
                )
                screen.blit(
                    font.render(lab[:30], True, (220, 220, 220)),
                    (r.x + 4, r.y + 2),
                )
            y0 += EDITOR_RC_LINE_H
    else:
        n = len(state.get("path") or [])
        screen.blit(
            title_font.render(f"POINTS ({n})", True, (200, 255, 200)),
            (10, tops["list_header"] + 2),
        )
        y0 = tops["list"] - int(list_scroll or 0)
        sel = state.get("selected_ix")
        for i, p in enumerate(state.get("path") or []):
            r = pygame.Rect(8, y0, sidebar_w - 16, EDITOR_RC_LINE_H)
            if r.bottom > top_bar_h and r.top < top_bar_h + map_view_h:
                if sel == i:
                    pygame.draw.rect(screen, (80, 80, 40), r)
                screen.blit(
                    font.render(f"{i:02d}  {float(p[0]):.0f},{float(p[1]):.0f}", True, (220, 220, 220)),
                    (r.x + 4, r.y + 2),
                )
            y0 += EDITOR_RC_LINE_H

    hint = str(state.get("hint") or "")
    if hint:
        screen.blit(
            font.render(hint[:42], True, (255, 230, 140)),
            (8, top_bar_h + map_view_h - 22),
        )
    return tops


def _cycle_item_type(it: dict) -> None:
    keys = list(RACING_EFFECT_TYPES) or ["speed", "slow", "swap"]
    if not keys:
        return
    cur = str(it.get("type") or "speed")
    try:
        ix = keys.index(cur)
    except ValueError:
        ix = 0
    nxt = keys[(ix + 1) % len(keys)]
    info = RACING_ITEM_TYPES.get(nxt) or {}
    it["type"] = nxt
    it["strength"] = float(info.get("strength", 1.0) or 1.0)
    it["duration_sec"] = float(info.get("duration_sec", 2.0) or 2.0)
    it["asset"] = str(info.get("asset") or it.get("asset") or "item_racing001")


def _item_group_signature(it: dict) -> Tuple:
    """레인만 다른 동일 지점 아이템을 묶기 위한 서명."""
    return (
        round(float(it.get("s", 0.0) or 0.0), 2),
        str(it.get("kind") or "normal"),
        str(it.get("type") or "speed"),
        round(float(it.get("strength", 1.0) or 1.0), 3),
        round(float(it.get("duration_sec", 0.0) or 0.0), 2),
        str(it.get("asset") or ""),
        round(float(it.get("roulette_period_sec", 0.0) or 0.0), 2),
        bool(it.get("consume", False)),
    )


def _item_group_indices(items: List[dict], sel_ix: Optional[int]) -> List[int]:
    if sel_ix is None or not (0 <= int(sel_ix) < len(items)):
        return []
    sig = _item_group_signature(items[int(sel_ix)])
    out = []
    for i, it in enumerate(items):
        if _item_group_signature(it) == sig:
            out.append(i)
    return out


def _item_group_lane_set(items: List[dict], sel_ix: Optional[int]) -> set:
    lanes = set()
    for i in _item_group_indices(items, sel_ix):
        lanes.add(str(items[i].get("lane") or "B").upper())
    return lanes


def _cycle_item_kind(it: dict) -> None:
    cur = str(it.get("kind") or "normal")
    try:
        ix = RACING_ITEM_KINDS.index(cur)
    except ValueError:
        ix = 0
    nxt = RACING_ITEM_KINDS[(ix + 1) % len(RACING_ITEM_KINDS)]
    it["kind"] = nxt
    if nxt == "secret":
        it["type"] = "speed"
    elif nxt == "summon":
        it.pop("roulette_period_sec", None)
    elif nxt == "roulette":
        it.setdefault(
            "roulette_period_sec",
            float(RACING_DEFAULTS.get("roulette_lane_period_sec", 0.55) or 0.55),
        )


def _cycle_roulette_period(it: dict) -> None:
    if str(it.get("kind") or "") != "roulette":
        return
    try:
        cur = float(it.get("roulette_period_sec", 0.55) or 0.55)
    except (TypeError, ValueError):
        cur = 0.55
    presets = list(_ROULETTE_PERIOD_PRESETS)
    try:
        ix = presets.index(round(cur, 2))
    except ValueError:
        ix = -1
    nxt = presets[(ix + 1) % len(presets)]
    it["roulette_period_sec"] = float(nxt)


def _toggle_item_lane_in_group(state, lane: str) -> bool:
    """선택 아이템 묶음에서 lane 체크 on/off."""
    items = list(state.get("items") or [])
    sel_ix = state.get("selected_item_ix")
    if sel_ix is None or not (0 <= int(sel_ix) < len(items)):
        return False
    lane = str(lane or "B").upper()
    if lane not in ("A", "B", "C"):
        return False
    group_ixs = _item_group_indices(items, sel_ix)
    if not group_ixs:
        return False
    current_lanes = _item_group_lane_set(items, sel_ix)
    if lane in current_lanes:
        old_sig = _item_group_signature(items[int(sel_ix)])
        kept: List[dict] = []
        removed = False
        for i, it in enumerate(items):
            same_group = i in group_ixs
            same_lane = str(it.get("lane") or "B").upper() == lane
            if same_group and same_lane:
                removed = True
                continue
            kept.append(it)
        state["items"] = kept
        new_sel = None
        for i, it in enumerate(kept):
            if _item_group_signature(it) == old_sig:
                new_sel = i
                break
        state["selected_item_ix"] = new_sel
        return removed
    clone = dict(items[int(sel_ix)])
    clone["lane"] = lane
    items.append(_normalize_item(clone))
    state["items"] = items
    state["selected_item_ix"] = len(items) - 1
    return True


def handle_left_click(state, mx, my, tops, sidebar_w, flow, map_id, *, list_scroll=0) -> Optional[str]:
    """좌측 클릭. 반환: None 또는 액션 힌트."""
    tool = str(state.get("tool") or "PATH")
    tw = max(36, (sidebar_w - 32) // 4)
    btn_p = pygame.Rect(8, tops["tools"], tw, 26)
    btn_e = pygame.Rect(btn_p.right + 4, tops["tools"], tw, 26)
    btn_i = pygame.Rect(btn_e.right + 4, tops["tools"], tw, 26)
    btn_s = pygame.Rect(btn_i.right + 4, tops["tools"], tw, 26)
    if btn_p.collidepoint(mx, my):
        state["tool"] = "PATH"
        state["hint"] = "맵 클릭 → 경로 점 추가"
        return None
    if btn_e.collidepoint(mx, my):
        state["tool"] = "POINTS"
        state["hint"] = "점 선택·드래그 / Del 삭제"
        return None
    if btn_i.collidepoint(mx, my):
        state["tool"] = "ITEMS"
        state["hint"] = "기존 아이템 클릭=선택 · 빈 경로=추가 · 드래그=이동"
        return None
    if btn_s.collidepoint(mx, my):
        state["tool"] = "SETTINGS"
        state["settings_fields"] = load_settings_fields(flow, map_id)
        state["show_settings"] = True
        return "settings"

    y = tops["actions"]
    bw = sidebar_w - 16
    if tool == "ITEMS":
        actions = [
            "cycle_item_kind",
            "cycle_item_type",
            "toggle_consume",
            "toggle_lane_A",
            "toggle_lane_B",
            "toggle_lane_C",
            "cycle_roulette_period",
            "delete_item",
            "save_racing",
            "open_settings",
        ]
    else:
        actions = [
            "toggle_closed",
            "undo_point",
            "clear_path",
            "save_racing",
            "open_settings",
        ]
    for i, act in enumerate(actions):
        r = pygame.Rect(8, y + i * 28, bw, 24)
        if not r.collidepoint(mx, my):
            continue
        if act == "toggle_closed":
            state["closed"] = not bool(state.get("closed", True))
            state["dirty"] = True
            state["hint"] = f"루프 {'ON' if state['closed'] else 'OFF'}"
            return act
        if act == "undo_point":
            path = state.get("path") or []
            if path:
                path.pop()
                state["path"] = path
                state["selected_ix"] = None
                state["dirty"] = True
                state["hint"] = f"점 삭제 · 남은 {len(path)}"
            return act
        if act == "clear_path":
            state["path"] = []
            state["selected_ix"] = None
            state["dirty"] = True
            state["hint"] = "경로 비움"
            return act
        if act == "cycle_item_type":
            ix = state.get("selected_item_ix")
            items = state.get("items") or []
            if ix is not None and 0 <= int(ix) < len(items):
                for gi in _item_group_indices(items, ix):
                    _cycle_item_type(items[int(gi)])
                state["items"] = items
                state["dirty"] = True
                state["hint"] = f"효과 → {items[int(ix)].get('type')}"
            else:
                state["hint"] = "아이템을 먼저 선택"
            return act
        if act == "cycle_item_kind":
            ix = state.get("selected_item_ix")
            items = state.get("items") or []
            if ix is not None and 0 <= int(ix) < len(items):
                for gi in _item_group_indices(items, ix):
                    _cycle_item_kind(items[int(gi)])
                state["items"] = [_normalize_item(x) for x in items]
                state["dirty"] = True
                k = items[int(ix)].get("kind", "normal")
                state["hint"] = f"배치 → {RACING_ITEM_KIND_LABELS.get(k, k)}"
            else:
                state["hint"] = "아이템을 먼저 선택"
            return act
        if act == "toggle_consume":
            ix = state.get("selected_item_ix")
            items = state.get("items") or []
            if ix is not None and 0 <= int(ix) < len(items):
                for gi in _item_group_indices(items, ix):
                    it = items[int(gi)]
                    it["consume"] = not bool(it.get("consume", False))
                state["items"] = [_normalize_item(x) for x in items]
                state["dirty"] = True
                on = bool(items[int(ix)].get("consume", False))
                state["hint"] = f"획득 후 소모 {'ON' if on else 'OFF'}(기본 OFF=유지)"
            else:
                state["hint"] = "아이템을 먼저 선택"
            return act
        if act == "cycle_roulette_period":
            ix = state.get("selected_item_ix")
            items = state.get("items") or []
            if ix is not None and 0 <= int(ix) < len(items):
                it = items[int(ix)]
                if str(it.get("kind") or "") != "roulette":
                    state["hint"] = "룰렛 발판만 주기 변경"
                    return act
                for gi in _item_group_indices(items, ix):
                    _cycle_roulette_period(items[int(gi)])
                state["items"] = items
                state["dirty"] = True
                state["hint"] = f"룰렛 주기 → {it.get('roulette_period_sec')}s"
            else:
                state["hint"] = "아이템을 먼저 선택"
            return act
        if act in ("toggle_lane_A", "toggle_lane_B", "toggle_lane_C"):
            if state.get("selected_item_ix") is None:
                state["hint"] = "아이템을 먼저 선택"
                return act
            lane = act[-1]
            if _toggle_item_lane_in_group(state, lane):
                state["dirty"] = True
                lanes = sorted(_item_group_lane_set(state.get("items") or [], state.get("selected_item_ix")))
                state["hint"] = f"레인 체크 → {','.join(lanes) if lanes else '(없음)'}"
            else:
                state["hint"] = "레인 체크 변경 실패"
            return act
        if act == "delete_item":
            if delete_selected_item(state):
                return act
            state["hint"] = "삭제할 아이템 없음"
            return act
        if act == "save_racing":
            commit_path_to_world(state, flow, map_id)
            return act
        if act == "open_settings":
            state["settings_fields"] = load_settings_fields(flow, map_id)
            state["show_settings"] = True
            return "settings"

    # 리스트 선택
    y0 = tops["list"] - int(list_scroll or 0)
    if tool == "ITEMS":
        for i, _it in enumerate(state.get("items") or []):
            r = pygame.Rect(8, y0, sidebar_w - 16, EDITOR_RC_LINE_H)
            if r.collidepoint(mx, my):
                state["selected_item_ix"] = i
                state["tool"] = "ITEMS"
                state["hint"] = f"아이템 #{i}"
                return "select"
            y0 += EDITOR_RC_LINE_H
    else:
        for i, _p in enumerate(state.get("path") or []):
            r = pygame.Rect(8, y0, sidebar_w - 16, EDITOR_RC_LINE_H)
            if r.collidepoint(mx, my):
                state["selected_ix"] = i
                state["tool"] = "POINTS"
                state["hint"] = f"선택 #{i}"
                return "select"
            y0 += EDITOR_RC_LINE_H
    return None


# --- map pick --------------------------------------------------------------

def nearest_point_ix(path, wx, wy, *, max_dist=22.0) -> Optional[int]:
    best_i = None
    best_d = float(max_dist)
    for i, p in enumerate(path or []):
        try:
            d = ((float(p[0]) - float(wx)) ** 2 + (float(p[1]) - float(wy)) ** 2) ** 0.5
        except (TypeError, ValueError, IndexError):
            continue
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def nearest_segment_insert(path, wx, wy, *, max_dist=18.0, closed=True) -> Optional[int]:
    """가장 가까운 구간에 삽입할 인덱스(뒤쪽 점 index). 없으면 None."""
    pts = list(path or [])
    n = len(pts)
    if n < 2:
        return None
    best_i = None
    best_d = float(max_dist)
    segs = n if closed else (n - 1)
    for i in range(segs):
        a = pts[i]
        b = pts[(i + 1) % n]
        ax, ay = float(a[0]), float(a[1])
        bx, by = float(b[0]), float(b[1])
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-6:
            continue
        t = ((float(wx) - ax) * dx + (float(wy) - ay) * dy) / L2
        t = max(0.0, min(1.0, t))
        px, py = ax + t * dx, ay + t * dy
        d = ((float(wx) - px) ** 2 + (float(wy) - py) ** 2) ** 0.5
        if d < best_d:
            best_d = d
            best_i = i + 1  # insert before next (after i)
    return best_i


def handle_map_click(
    state,
    wx: float,
    wy: float,
    flow,
    map_id: str,
    *,
    shift=False,
) -> bool:
    """맵 클릭 처리. True면 소비."""
    if state.get("pick_xy_key"):
        return apply_xy_pick(state, wx, wy, flow, map_id)

    if state.get("show_settings"):
        return False

    tool = str(state.get("tool") or "PATH")
    path = list(state.get("path") or [])

    if tool == "ITEMS":
        return _handle_item_map_click(state, wx, wy)

    near = nearest_point_ix(path, wx, wy, max_dist=22.0)
    if tool == "POINTS" or (tool == "PATH" and near is not None and not shift):
        if near is not None:
            state["selected_ix"] = near
            state["dragging"] = True
            state["tool"] = "POINTS"
            state["hint"] = f"선택 #{near} · 드래그로 이동"
            return True
        if tool == "POINTS":
            state["selected_ix"] = None
            state["hint"] = "점 근처를 클릭하세요"
            return True

    # Shift+클릭: 구간 중간 삽입
    if shift and len(path) >= 2:
        ins = nearest_segment_insert(
            path, wx, wy, max_dist=24.0, closed=bool(state.get("closed", True))
        )
        if ins is not None:
            path.insert(ins, [float(wx), float(wy)])
            state["path"] = path
            state["selected_ix"] = ins
            state["dirty"] = True
            state["hint"] = f"삽입 #{ins}"
            return True

    # PATH: 끝에 추가
    if tool == "PATH":
        path.append([float(wx), float(wy)])
        state["path"] = path
        state["selected_ix"] = len(path) - 1
        state["dirty"] = True
        state["hint"] = f"추가 #{len(path) - 1} ({wx:.0f},{wy:.0f})"
        return True

    return False


def _lane_width_from_state(state) -> float:
    fields = state.get("settings_fields") or {}
    return max(
        8.0,
        _parse_float(
            fields.get("lane_width", RACING_DEFAULTS.get("lane_width", 30.0)),
            30.0,
        ),
    )


def _s_delta(rp, a: float, b: float) -> float:
    """경로 위 두 s 사이 최단 거리 (루프면 wrap)."""
    try:
        length = float(getattr(rp, "length", 0.0) or 0.0)
    except (TypeError, ValueError):
        length = 0.0
    da = abs(float(a) - float(b))
    if length > 1e-6 and bool(getattr(rp, "closed", True)):
        return min(da, length - da)
    return da


def _nearest_item_ix(state, wx: float, wy: float, *, max_dist=28.0) -> Optional[int]:
    best_i = None
    best_d = float(max_dist)
    for i, it in enumerate(state.get("items") or []):
        xy = _item_world_xy(state, it)
        if xy is None:
            continue
        d = math.hypot(float(xy[0]) - float(wx), float(xy[1]) - float(wy))
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def _pick_existing_item_ix(state, wx: float, wy: float) -> Optional[int]:
    """
    맵 클릭으로 기존 아이템 선택.
    화면 축소 시 월드 반경만으로는 마커를 못 잡을 수 있어
    1) 월드 거리 2) 경로 s 근접 순으로 판정한다.
    """
    items = state.get("items") or []
    if not items:
        return None
    lane_w = _lane_width_from_state(state)
    # 맵이 축소되면 12px 마커가 수십 월드유닛에 해당 → 넉넉히
    spatial = max(64.0, lane_w * 2.0 + 28.0)
    near = _nearest_item_ix(state, wx, wy, max_dist=spatial)
    if near is not None:
        return near
    path = state.get("path") or []
    if len(path) < 2:
        return None
    try:
        rp = _race_path_from_state(state)
        s_click = float(rp.nearest_s(wx, wy))
        px, py, _, _ = rp.sample(s_click)
    except Exception:
        return None
    # 도로에서 너무 멀면 경로 s 매칭하지 않음
    if math.hypot(float(wx) - float(px), float(wy) - float(py)) > max(48.0, lane_w * 2.5):
        return None
    max_ds = max(40.0, lane_w * 1.5)
    best_i = None
    best_ds = max_ds
    best_xy = None
    for i, it in enumerate(items):
        try:
            s_it = float(it.get("s", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        ds = _s_delta(rp, s_it, s_click)
        if ds > best_ds:
            continue
        xy = _item_world_xy(state, it)
        # 같은 s 묶음이면 클릭에 가장 가까운 레인 우선
        if ds < best_ds - 1e-6 or best_i is None:
            best_ds = ds
            best_i = i
            best_xy = xy
        elif abs(ds - best_ds) <= 1e-6 and xy is not None:
            prev_d = (
                math.hypot(float(best_xy[0]) - float(wx), float(best_xy[1]) - float(wy))
                if best_xy is not None
                else 1e9
            )
            cur_d = math.hypot(float(xy[0]) - float(wx), float(xy[1]) - float(wy))
            if cur_d < prev_d:
                best_i = i
                best_xy = xy
    return best_i


def _handle_item_map_click(state, wx: float, wy: float) -> bool:
    path = state.get("path") or []
    if len(path) < 2:
        state["hint"] = "먼저 경로를 2점 이상 만드세요"
        return True
    near = _pick_existing_item_ix(state, wx, wy)
    if near is not None:
        state["selected_item_ix"] = near
        state["dragging_item"] = True
        state["dragging"] = False
        it = (state.get("items") or [])[int(near)]
        kind = RACING_ITEM_KIND_LABELS.get(str(it.get("kind") or "normal"), "일반")
        state["hint"] = (
            f"아이템 #{near} 선택 ({kind}/{it.get('type')}/{it.get('lane')}) · "
            f"좌측에서 수정 · 드래그로 이동"
        )
        return True
    try:
        rp = _race_path_from_state(state)
        s = float(rp.nearest_s(wx, wy))
    except Exception:
        state["hint"] = "경로 s 계산 실패"
        return True
    items = list(state.get("items") or [])
    it = _default_item_at(s, lane="B", type_id="speed")
    items.append(it)
    state["items"] = items
    state["selected_item_ix"] = len(items) - 1
    state["dragging_item"] = False
    state["dirty"] = True
    state["hint"] = f"아이템 추가 s={s:.0f} · 배치/효과/레인은 좌측에서"
    return True


def handle_map_drag(state, wx: float, wy: float) -> bool:
    if state.get("dragging_item"):
        ix = state.get("selected_item_ix")
        items = list(state.get("items") or [])
        if ix is None or not (0 <= int(ix) < len(items)):
            return False
        path = state.get("path") or []
        if len(path) < 2:
            return False
        try:
            rp = _race_path_from_state(state)
            new_s = round(float(rp.nearest_s(wx, wy)), 2)
        except Exception:
            return False
        for gi in _item_group_indices(items, ix):
            items[int(gi)]["s"] = new_s
        state["items"] = items
        state["dirty"] = True
        state["hint"] = f"아이템 이동 s={new_s:.0f}"
        return True
    if not state.get("dragging"):
        return False
    ix = state.get("selected_ix")
    path = state.get("path") or []
    if ix is None or not (0 <= int(ix) < len(path)):
        return False
    path[int(ix)] = [float(wx), float(wy)]
    state["path"] = path
    state["dirty"] = True
    return True


def handle_map_mouseup(state) -> None:
    state["dragging"] = False
    state["dragging_item"] = False


def apply_xy_pick(state, wx: float, wy: float, flow, map_id: str) -> bool:
    key = state.get("pick_xy_key")
    if not key:
        return False
    fields = state.setdefault("settings_fields", load_settings_fields(flow, map_id))
    fields[key] = f"{float(wx):g}, {float(wy):g}"
    state["pick_xy_key"] = None
    state["show_settings"] = True
    state["hint"] = f"{key} = {fields[key]}"
    return True


def delete_selected_point(state) -> bool:
    ix = state.get("selected_ix")
    path = list(state.get("path") or [])
    if ix is None or not (0 <= int(ix) < len(path)):
        return False
    path.pop(int(ix))
    state["path"] = path
    state["selected_ix"] = None
    state["dragging"] = False
    state["dirty"] = True
    state["hint"] = f"삭제 · 남은 {len(path)}"
    return True


def delete_selected_item(state) -> bool:
    ix = state.get("selected_item_ix")
    items = list(state.get("items") or [])
    if ix is None or not (0 <= int(ix) < len(items)):
        return False
    items.pop(int(ix))
    state["items"] = items
    state["selected_item_ix"] = None
    state["dragging_item"] = False
    state["dirty"] = True
    state["hint"] = f"아이템 삭제 · 남은 {len(items)}"
    return True


# --- overlay draw ----------------------------------------------------------

def _parse_rgb(raw, default) -> Tuple[int, int, int]:
    try:
        return (
            max(0, min(255, int(raw[0]))),
            max(0, min(255, int(raw[1]))),
            max(0, min(255, int(raw[2]))),
        )
    except (TypeError, ValueError, IndexError):
        return tuple(default[:3])  # type: ignore


def _draw_generated_road_preview(map_surf, state, world_to_xy) -> None:
    """
    게임의 RacingActivity._paint_road_on_bg 와 같은 경로·법선·lane_width 식으로
    생성 예정인 3레인 도로를 반투명 미리보기한다.

    도로 테두리 → A(-1) / B(0) / C(+1) 레인 순서로 그리고,
    편집용 경로선·포인트·아이템은 draw_map_overlay 가 그 위에 표시한다.
    """
    path_pts = state.get("path") or []
    if len(path_pts) < 2:
        return
    cfg = state.get("_road_preview_cfg") or {}
    if not bool(cfg.get("road_draw_enabled", True)):
        return
    fields = state.get("settings_fields") or {}
    lane_w = max(
        6.0,
        _parse_float(
            fields.get("lane_width", RACING_DEFAULTS.get("lane_width", 30.0)),
            30.0,
        ),
    )
    border_px = max(
        0.0,
        _parse_float(
            cfg.get("road_border_px", RACING_DEFAULTS.get("road_border_px", 3.0)),
            3.0,
        ),
    )
    raw_cols = (
        cfg.get("road_lane_colors")
        or RACING_DEFAULTS.get("road_lane_colors")
        or []
    )
    defaults = ((210, 60, 60), (235, 205, 70), (70, 115, 230))
    lane_cols = [
        _parse_rgb(raw_cols[i] if i < len(raw_cols) else None, defaults[i])
        for i in range(3)
    ]
    border_col = _parse_rgb(
        cfg.get("road_border_color"),
        RACING_DEFAULTS.get("road_border_color", (40, 40, 46)),
    )

    try:
        # 경로/줌/팬/설정이 그대로면 매 프레임 다시 만들지 않고 캐시를 블릿한다.
        tr0 = world_to_xy(0.0, 0.0)
        trx = world_to_xy(1.0, 0.0)
        try_ = world_to_xy(0.0, 1.0)
        cache_key = (
            tuple((round(float(p[0]), 2), round(float(p[1]), 2)) for p in path_pts),
            bool(state.get("closed", True)),
            round(lane_w, 3),
            round(
                _parse_float(
                    fields.get("curve_tension", RACING_DEFAULTS.get("curve_tension", 0.0)),
                    0.0,
                ),
                3,
            ),
            int(
                _parse_float(
                    fields.get(
                        "curve_samples_per_seg",
                        RACING_DEFAULTS.get("curve_samples_per_seg", 20),
                    ),
                    20.0,
                )
            ),
            round(border_px, 3),
            tuple(lane_cols),
            border_col,
            map_surf.get_size(),
            tuple(round(float(v), 3) for pair in (tr0, trx, try_) for v in pair),
        )
        cached = state.get("_road_preview_cache")
        if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == cache_key:
            map_surf.blit(cached[1], (0, 0))
            return

        rp = _race_path_from_state(state)
        # 월드 1px이 현재 map_surf에서 차지하는 픽셀 수.
        x0, y0, _, _ = rp.sample(0.0)
        sx0, sy0 = world_to_xy(x0, y0)
        sx1, sy1 = world_to_xy(x0 + 1.0, y0)
        zoom = max(
            0.01,
            math.hypot(float(sx1) - float(sx0), float(sy1) - float(sy0)),
        )
        step = max(2.0, lane_w * 0.25)
        count = max(2, int(math.ceil(rp.length / step)))
        lane_lines = [[], [], []]
        center_line = []
        for i in range(count + 1):
            x, y, tang, _ = rp.sample(rp.length * (i / float(count)))
            csx, csy = world_to_xy(x, y)
            center_line.append((int(round(csx)), int(round(csy))))
            nx, ny = -math.sin(tang), math.cos(tang)
            for li, off in enumerate((-1.0, 0.0, 1.0)):
                sx, sy = world_to_xy(
                    x + nx * off * lane_w,
                    y + ny * off * lane_w,
                )
                lane_lines[li].append((int(round(sx)), int(round(sy))))
    except Exception:
        return

    preview = pygame.Surface(map_surf.get_size(), pygame.SRCALPHA)
    closed = bool(state.get("closed", True))
    border_w = max(
        1, int(round((lane_w * 3.0 + border_px * 2.0) * zoom))
    )
    lane_px = max(1, int(round(lane_w * zoom)) + 1)
    try:
        pygame.draw.lines(
            preview, (*border_col, 210), closed, center_line, border_w
        )
        for pts, col in zip(lane_lines, lane_cols):
            pygame.draw.lines(preview, (*col, 190), closed, pts, lane_px)
        state["_road_preview_cache"] = (cache_key, preview)
        map_surf.blit(preview, (0, 0))
    except Exception:
        pass


def draw_map_overlay(
    map_surf,
    state,
    *,
    world_to_xy,
    font=None,
):
    """map_surf 위에 경로 곡선·제어점·아이템 표시."""
    path = state.get("path") or []
    if not path:
        if state.get("tool") == "PATH":
            try:
                f = font or pygame.font.Font(None, 22)
                map_surf.blit(
                    f.render("맵 클릭으로 레이스 경로 점 추가", True, (255, 230, 120)),
                    (12, 12),
                )
            except Exception:
                pass
        return

    # 경로를 편집하는 동안 게임에서 생성될 도로를 즉시 확인한다.
    _draw_generated_road_preview(map_surf, state, world_to_xy)

    pts_s = []
    for p in path:
        try:
            sx, sy = world_to_xy(float(p[0]), float(p[1]))
            pts_s.append((int(sx), int(sy)))
        except Exception:
            continue
    if len(pts_s) >= 2:
        closed = bool(state.get("closed", True))
        # 제어점 연결(가이드) — 옅은 선
        try:
            pygame.draw.lines(map_surf, (60, 90, 120), closed, pts_s, 1)
        except Exception:
            pass
        # 실제 주행 곡선 — RacePath 호장 샘플
        try:
            rp = _race_path_from_state(state)
            if rp.length > 1.0:
                steps = max(32, int(rp.length / 6.0))
                curve_pts = []
                for i in range(steps + (0 if closed else 1)):
                    x, y, _, _ = rp.sample(rp.length * (i / float(steps)))
                    csx, csy = world_to_xy(float(x), float(y))
                    curve_pts.append((int(csx), int(csy)))
                if len(curve_pts) >= 2:
                    pygame.draw.lines(map_surf, (80, 200, 255), closed, curve_pts, 2)
        except Exception:
            try:
                pygame.draw.lines(map_surf, (80, 200, 255), closed, pts_s, 2)
            except Exception:
                pass
        for i in range(len(pts_s) - (0 if closed else 1)):
            a = pts_s[i]
            b = pts_s[(i + 1) % len(pts_s)]
            mx = (a[0] + b[0]) // 2
            my = (a[1] + b[1]) // 2
            pygame.draw.circle(map_surf, (255, 200, 80), (mx, my), 3)

    sel = state.get("selected_ix")
    for i, (sx, sy) in enumerate(pts_s):
        col = (255, 220, 80) if sel == i else (80, 220, 255)
        r = 7 if sel == i else 5
        pygame.draw.circle(map_surf, col, (sx, sy), r)
        pygame.draw.circle(map_surf, (255, 255, 255), (sx, sy), r, 1)
        try:
            f = font or pygame.font.Font(None, 18)
            map_surf.blit(f.render(str(i), True, col), (sx + 8, sy - 10))
        except Exception:
            pass

    # 청정 구간 s 마커 (녹색 원)
    try:
        cz_text = str((state.get("settings_fields") or {}).get("clean_zones", "") or "")
        cz_list = _text_to_clean_zones(cz_text)
        if cz_list and len(path) >= 2:
            rp = _race_path_from_state(state)
            for z0, z1 in cz_list:
                for s in (z0, z1):
                    x, y, _, _ = rp.sample(float(s))
                    csx, csy = world_to_xy(float(x), float(y))
                    pygame.draw.circle(map_surf, (120, 255, 160), (int(csx), int(csy)), 7, 2)
    except Exception:
        pass

    # 아이템 마커 (경로 법선 오프셋 반영)
    sel_it = state.get("selected_item_ix")
    for i, it in enumerate(state.get("items") or []):
        xy = _item_world_xy(state, it)
        if xy is None:
            continue
        try:
            sx, sy = world_to_xy(float(xy[0]), float(xy[1]))
            sx, sy = int(sx), int(sy)
        except Exception:
            continue
        kind = str(it.get("kind") or "normal")
        tid = str(it.get("type") or "speed")
        col = _item_kind_color(kind, tid)
        if sel_it == i:
            pygame.draw.rect(map_surf, (255, 255, 120), (sx - 9, sy - 9, 18, 18), 2)
        pygame.draw.rect(map_surf, col, (sx - 6, sy - 6, 12, 12))
        pygame.draw.rect(map_surf, (255, 255, 255), (sx - 6, sy - 6, 12, 12), 1)
        try:
            f = font or pygame.font.Font(None, 16)
            k0 = kind[0].upper() if kind != "normal" else tid[0].upper()
            lab = f"{k0}{it.get('lane', 'B')}"
            map_surf.blit(f.render(lab, True, col), (sx + 10, sy - 8))
        except Exception:
            pass

    if state.get("tool") == "ITEMS" and not (state.get("items") or []):
        try:
            f = font or pygame.font.Font(None, 20)
            map_surf.blit(
                f.render("경로 클릭 → 아이템 추가 · 기존 아이템 클릭 → 선택/수정", True, (255, 210, 140)),
                (12, 12),
            )
        except Exception:
            pass

    if state.get("pick_xy_key"):
        try:
            f = font or pygame.font.Font(None, 22)
            map_surf.blit(
                f.render(f"클릭: {state.get('pick_xy_key')} 좌표", True, (255, 255, 120)),
                (12, 12),
            )
        except Exception:
            pass


# --- settings modal --------------------------------------------------------

def layout_settings_modal_ui(state, sw, sh) -> dict:
    w, h = 440, 500
    rect = pygame.Rect(sw // 2 - w // 2, sh // 2 - h // 2, w, h)
    fields = {}
    y = rect.y + 48 - int(state.get("settings_scroll") or 0)
    keys = (
        [("closed", "루프(1/0)")]
        + [(k, lab) for k, lab, _t, _d in RACING_EDITOR_SCALAR_KEYS]
        + [(k, lab) for k, lab, _t, _d in RACING_EDITOR_WEATHER_KEYS]
        + list(RACING_EDITOR_XY_KEYS)
        + [(k, lab) for k, lab, _d in RACING_EDITOR_TEXT_KEYS]
    )
    for key, _lab in keys:
        fields[key] = pygame.Rect(rect.x + 160, y, rect.width - 180, 24)
        y += 28
    save = pygame.Rect(rect.x + 20, rect.bottom - 44, 100, 30)
    cancel = pygame.Rect(rect.x + 130, rect.bottom - 44, 100, 30)
    pick_exit = pygame.Rect(rect.x + 240, rect.bottom - 44, 150, 30)
    return {
        "rect": rect,
        "fields": fields,
        "save": save,
        "cancel": cancel,
        "pick_exit": pick_exit,
        "keys": keys,
    }


def draw_settings_modal(screen, font, state, sw, sh) -> dict:
    ui = layout_settings_modal_ui(state, sw, sh)
    rect = ui["rect"]
    dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 120))
    screen.blit(dim, (0, 0))
    pygame.draw.rect(screen, (40, 48, 60), rect, border_radius=8)
    pygame.draw.rect(screen, (200, 210, 230), rect, 2, border_radius=8)
    screen.blit(
        font.render("레이스 설정 (world_data.racing)", True, (255, 255, 200)),
        (rect.x + 14, rect.y + 12),
    )
    screen.blit(
        font.render("청정구간: 아이템·날씨 없음  예) 0,140; 2850,2992", True, (180, 200, 220)),
        (rect.x + 14, rect.y + 28),
    )
    fields_data = state.get("settings_fields") or {}
    clip = screen.get_clip()
    screen.set_clip(pygame.Rect(rect.x, rect.y + 40, rect.width, rect.height - 90))
    for key, lab in ui["keys"]:
        fr = ui["fields"][key]
        if fr.bottom < rect.y + 40 or fr.top > rect.bottom - 50:
            continue
        screen.blit(font.render(lab, True, (220, 230, 245)), (rect.x + 14, fr.y + 4))
        pygame.draw.rect(screen, (30, 35, 45), fr)
        active = state.get("_edit_field") == key
        pygame.draw.rect(screen, (255, 215, 0) if active else (120, 140, 170), fr, 1)
        val = str(fields_data.get(key, ""))
        ed_txt.blit_field_value(
            screen, font, val, fr, active=active, session=_te(state), color=(240, 248, 255), trunc_limit=28
        )
    screen.set_clip(clip)

    for b, lab, col in (
        (ui["save"], "저장", (50, 90, 60)),
        (ui["cancel"], "닫기", (70, 50, 50)),
        (ui["pick_exit"], "퇴장좌표 픽", (50, 70, 100)),
    ):
        pygame.draw.rect(screen, col, b, border_radius=4)
        screen.blit(font.render(lab, True, (240, 248, 255)), (b.x + 10, b.y + 6))
    return ui


def handle_settings_modal_click(state, mx, my, ui, flow, map_id) -> Optional[str]:
    if not ui:
        return None
    if ui["save"].collidepoint(mx, my):
        apply_settings_fields(state, flow, map_id)
        # path sync from state
        load_path_into_state(state, flow, map_id)
        state["show_settings"] = False
        return "saved"
    if ui["cancel"].collidepoint(mx, my):
        state["show_settings"] = False
        state.pop("_edit_field", None)
        return "closed"
    if ui["pick_exit"].collidepoint(mx, my):
        state["pick_xy_key"] = "exit_pos"
        state["show_settings"] = False
        state["hint"] = "맵 클릭: exit_pos"
        return "pick"
    for key, fr in (ui.get("fields") or {}).items():
        if fr.collidepoint(mx, my):
            state["_edit_field"] = key
            _te(state).focus(str((state.get("settings_fields") or {}).get(key, "")))
            return None
    return None


def handle_settings_modal_event(state, event, sw, sh, mx, my) -> bool:
    if not state.get("show_settings"):
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
    if ef and state.get("show_settings"):
        fields = state.setdefault("settings_fields", {})
        fields[ef] = _te(state).insert(str(fields.get(ef, "")), t)
        return True
    return False


def handle_keydown(state, event, flow, map_id) -> bool:
    if event.type != pygame.KEYDOWN:
        return False
    key = event.key
    if key == pygame.K_ESCAPE:
        if state.get("pick_xy_key"):
            state["pick_xy_key"] = None
            return True
        if state.get("show_settings"):
            state["show_settings"] = False
            state.pop("_edit_field", None)
            return True
        state["selected_ix"] = None
        return False
    if state.get("show_settings") and state.get("_edit_field"):
        ef = state["_edit_field"]
        fields = state.setdefault("settings_fields", {})
        if key == pygame.K_RETURN:
            state.pop("_edit_field", None)
            return True
        nt, handled = _te(state).keydown(str(fields.get(ef, "")), event)
        if handled:
            fields[ef] = nt
            return True
        return True
    if key in (pygame.K_DELETE, pygame.K_BACKSPACE) and not state.get("show_settings"):
        if str(state.get("tool") or "") == "ITEMS":
            if delete_selected_item(state):
                return True
        elif delete_selected_point(state):
            return True
    return False

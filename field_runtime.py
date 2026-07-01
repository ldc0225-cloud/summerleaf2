"""
필드 플레이 중 디버그 UI 상태, 구름 FX, 글로벌 핫키→이벤트, DEV_CMD 처리.
main.py 비대화를 줄이기 위해 분리.
"""
from __future__ import annotations

import math
import os
import random
import sys
from collections import OrderedDict

import pygame

from data import CONFIG


def ui_layout_width() -> float:
    try:
        return float(CONFIG.get("UI_LAYOUT_WIDTH", CONFIG.get("WIDTH", 320)) or 320)
    except Exception:
        return 320.0


def ui_text_reference_width() -> float:
    try:
        return float(CONFIG.get("UI_TEXT_REFERENCE_WIDTH", 320) or 320)
    except Exception:
        return 320.0


def ui_layout_scale(*, screen_w: int | None = None) -> float:
    """아이콘·말풍선·pushbutton 스케일. UI_LAYOUT_WIDTH(=논리 WIDTH) 기준 1:1 → 보통 1.0."""
    if screen_w is None:
        try:
            screen_w = int(CONFIG.get("WIDTH", 320) or 320)
        except Exception:
            screen_w = 320
    ref = max(1e-6, ui_layout_width())
    return max(0.5, min(4.0, float(screen_w) / ref))


def ui_text_scale(*, screen_w: int | None = None) -> float:
    """텍스트박스 RECT·폰트용 (320 설계 → 현재 논리 해상도)."""
    if screen_w is None:
        try:
            screen_w = int(CONFIG.get("WIDTH", 320) or 320)
        except Exception:
            screen_w = 320
    ref = max(1e-6, ui_text_reference_width())
    return max(0.5, min(4.0, float(screen_w) / ref))


def scale_ui_px(px, *, screen_w: int | None = None) -> float:
    return float(px) * ui_layout_scale(screen_w=screen_w)


def scale_ui_text_px(px, *, screen_w: int | None = None) -> float:
    return float(px) * ui_text_scale(screen_w=screen_w)


def find_entity_by_name(name, player, npcs=None, objs=None):
    """이벤트 target / CAMERA follow_entity용. 이름은 대소문자 무시."""
    n = str(name or "").strip()
    if not n:
        return None
    if n.lower() == "player":
        return player
    nl = n.lower()
    for pool in (npcs or []), (objs or []):
        for x in pool:
            try:
                xn = str(getattr(x, "name", "") or "")
                if xn == n or xn.lower() == nl:
                    return x
            except Exception:
                continue
    return None


class FieldRuntimeUI:
    """틸트/쉬어 디버그·오버레이 등 main 루프가 읽는 UI 상태."""

    __slots__ = (
        "show_mask",
        "show_overlay_text",
        "show_camera_focus",
        "tilt_bg_demo",
        "tilt_target",
        "shear_debug_on",
        "shear_suppressed",
        "zoom_idx",
    )

    def __init__(self):
        self.show_mask = False
        # 디버그 오버레이 기본값은 CONFIG에서 제어(기본: 꺼짐)
        self.show_overlay_text = bool(CONFIG.get("SHOW_OVERLAY_DEFAULT", False))
        self.show_camera_focus = False
        self.tilt_bg_demo = False
        self.tilt_target = 1.0  # 틸트 데모 목표 (이벤트 TILT와 공유)
        self.shear_debug_on = False
        # TILT_SHEAR_ENABLED=True일 때 핫키(R)로 필드 쉬어 끄기
        self.shear_suppressed = False
        self.zoom_idx = 2


FIELD_RUNTIME_UI = FieldRuntimeUI()


def _shear_strength_from_tilt(tilt_current):
    """틸트(1.0=평면)에 따른 쉬어 배율 0~1. TILT_SHEAR_SCALE_WITH_TILT=False면 항상 1."""
    try:
        scale_with_tilt = bool(CONFIG.get("TILT_SHEAR_SCALE_WITH_TILT", True))
    except Exception:
        scale_with_tilt = True
    if not scale_with_tilt:
        return 1.0
    try:
        on_f = float(CONFIG.get("TILT_BG_ON_FACTOR", 0.72))
    except Exception:
        on_f = 0.72
    denom = max(1e-6, (1.0 - float(on_f)))
    strength = (1.0 - float(tilt_current)) / denom
    return 0.0 if strength < 0.0 else (1.0 if strength > 1.0 else strength)


def tilt_shear_effective(ev_mgr, tilt_current, shear_debug=False):
    sc = getattr(ev_mgr, "shear_control", None) if ev_mgr is not None else None
    if isinstance(sc, dict) and sc.get("enabled") is False:
        return 0
    try:
        default_en = bool(CONFIG.get("TILT_SHEAR_ENABLED", True))
    except Exception:
        default_en = True

    if isinstance(sc, dict) and sc.get("enabled") is not False:
        # 이벤트/DEV에서 shear_control이 지정된 경우엔 전역 TILT_SHEAR_ENABLED가 꺼져 있어도(기본값 off)
        # 해당 명령을 "의도적으로 켠 것"으로 보고 적용한다.
        try:
            cfg_px_default = int(CONFIG.get("TILT_SHEAR_TOP_PX", 36) or 0)
        except Exception:
            cfg_px_default = 0
        max_px = sc.get("max_px")
        if max_px is not None and str(max_px).strip() != "":
            try:
                shear_px = max(0, min(256, int(max_px)))
            except (TypeError, ValueError):
                shear_px = max(0, min(256, int(cfg_px_default)))
        else:
            shear_px = max(0, min(256, int(cfg_px_default)))
        if shear_px <= 0:
            return 0
        try:
            smul = float(sc.get("strength_mul", 1.0))
        except (TypeError, ValueError):
            smul = 1.0
        smul = max(0.0, min(1.0, smul))
        bypass = bool(sc.get("bypass_strength"))
        if bypass:
            return int(round(float(shear_px) * smul))
        strength = _shear_strength_from_tilt(tilt_current)
        return int(round(float(shear_px) * strength * smul))

    try:
        if bool(getattr(FIELD_RUNTIME_UI, "shear_suppressed", False)):
            return 0
    except Exception:
        pass

    if shear_debug:
        try:
            px = int(CONFIG.get("TILT_SHEAR_TOP_PX", 36) or 0)
        except Exception:
            px = 0
        return max(0, min(256, px))

    shear_px = 0
    if default_en:
        try:
            shear_px = int(CONFIG.get("TILT_SHEAR_TOP_PX", 36) or 0)
        except Exception:
            shear_px = 0
    if shear_px <= 0:
        return 0
    strength = _shear_strength_from_tilt(tilt_current)
    return int(round(float(shear_px) * strength))


# --- 이벤트 스텝(TILT / SHEAR / ZOOM / CAMERA): on, strength(0~1), duration_sec ---


def parse_step_bool(val, default=None):
    if val is None or str(val).strip() == "":
        return default
    if val is True:
        return True
    if val is False:
        return False
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "t", "yes", "y", "on")
    return bool(val)


def parse_strength_01(val, default=1.0):
    if val is None or str(val).strip() == "":
        return max(0.0, min(1.0, float(default)))
    try:
        return max(0.0, min(1.0, float(val)))
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(default)))


def parse_duration_sec(step, *, default_sec=1.0):
    """이벤트 효과: duration_sec만 사용(초). 0이면 즉시."""
    if not isinstance(step, dict):
        return max(0.0, float(default_sec))
    for key in ("duration_sec", "duration", "dur"):
        raw = step.get(key)
        if raw is not None and str(raw).strip() != "":
            try:
                return max(0.0, min(30.0, float(raw)))
            except (TypeError, ValueError):
                pass
    if parse_step_bool(step.get("instant"), False):
        return 0.0
    return max(0.0, float(default_sec))


# 연속 배치 시 한 프레임에 같이 시작 (ZOOM·TILT·SHEAR·CAMERA)
PARALLEL_EFFECT_STEP_TYPES = frozenset(
    {"ZOOM", "TILT", "SHEAR", "CAMERA", "CONDITION", "CONDITION_SKIP"}
)


def effect_now_ms():
    return int(pygame.time.get_ticks())


def timed_effect_init(ctrl, start_value, target_value, duration_sec, *, now_ms=None):
    """ctrl dict에 시계 기반 선형 보간 상태를 기록."""
    if not isinstance(ctrl, dict):
        return
    now = effect_now_ms() if now_ms is None else int(now_ms)
    ctrl["start"] = float(start_value)
    ctrl["target"] = float(target_value)
    ctrl["duration_sec"] = max(0.0, min(30.0, float(duration_sec)))
    ctrl["t0_ms"] = now


def timed_effect_value(ctrl, fallback=None):
    if not isinstance(ctrl, dict):
        return fallback
    tgt = float(ctrl.get("target", fallback if fallback is not None else 0.0))
    dur = float(ctrl.get("duration_sec", 0.0) or 0.0)
    if dur <= 0.0:
        return tgt
    now = effect_now_ms()
    t0 = int(ctrl.get("t0_ms", now))
    elapsed_ms = max(0, now - t0)
    dur_ms = dur * 1000.0
    if dur_ms <= 0.0:
        return tgt
    u = min(1.0, elapsed_ms / dur_ms)
    start = float(ctrl.get("start", tgt))
    if u >= 1.0:
        return tgt
    return start + (tgt - start) * u


def timed_effect_finished(ctrl):
    if not isinstance(ctrl, dict):
        return True
    dur = float(ctrl.get("duration_sec", 0.0) or 0.0)
    if dur <= 0.0:
        return True
    now = effect_now_ms()
    t0 = int(ctrl.get("t0_ms", now))
    return (now - t0) >= dur * 1000.0 - 0.5


def auto_res_zoom_in_trigger():
    try:
        return float(CONFIG.get("AUTO_OUTPUT_MODE_ON_WORLD_ZOOM", 2.0))
    except (TypeError, ValueError):
        return 2.0


def auto_res_zoom_out_trigger():
    try:
        return float(CONFIG.get("AUTO_OUTPUT_MODE_OFF_WORLD_ZOOM", 1.0))
    except (TypeError, ValueError):
        return 1.0


def native_world_zoom_draw(zoom_equiv, output_mode, zoom_mul):
    """640(NATIVE) 기준 world_zoom → 실제 후처리 draw 배율. 320 모드에서는 2x를 해상도로 치환."""
    z = float(zoom_equiv)
    mul = float(zoom_mul) if float(zoom_mul) > 1.0 else 1.0
    if str(output_mode or "").strip().upper() == "UPSCALE_320" and mul > 1.0:
        return z / mul
    return z


def zoom_val_from_strength(strength_01, on=True, *, is_camera=True):
    if not on:
        return 1.0
    s = parse_strength_01(strength_01, 1.0)
    if is_camera:
        try:
            zmin = float(CONFIG.get("WORLD_ZOOM_MIN", 1.0))
            zmax = float(CONFIG.get("WORLD_ZOOM_MAX", 2.0))
        except (TypeError, ValueError):
            zmin, zmax = 1.0, 2.0
    else:
        try:
            zmin = float(CONFIG.get("ENTITY_ZOOM_MIN", 1.0))
            zmax = float(CONFIG.get("ENTITY_ZOOM_MAX", 2.0))
        except (TypeError, ValueError):
            zmin, zmax = 1.0, 2.0
    zmin = max(0.05, min(8.0, zmin))
    zmax = max(zmin, min(8.0, zmax))
    return max(zmin, min(zmax, zmin + s * max(0.0, zmax - zmin)))


def blend_scalar(current, target, dt_sec, duration_sec):
    c = float(current)
    t = float(target)
    if duration_sec is None or float(duration_sec) <= 0.0:
        return t
    d = float(duration_sec)
    dt = max(0.0, float(dt_sec))
    if abs(t - c) <= 1e-9:
        return t
    step = abs(t - c) / d * dt
    if step >= abs(t - c):
        return t
    return c + step if t > c else c - step


def _tilt_factor_min():
    try:
        v = float(CONFIG.get("TILT_FACTOR_MIN", 0.2))
    except (TypeError, ValueError):
        v = 0.2
    return max(0.02, min(0.99, v))


def tilt_factor_from_strength(strength_01, on=True):
    tf_lo = _tilt_factor_min()
    if not on:
        return 1.0
    s = parse_strength_01(strength_01, 1.0)
    return max(tf_lo, min(1.0, 1.0 - s * (1.0 - tf_lo)))


def tilt_strength_from_factor(factor):
    tf_lo = _tilt_factor_min()
    try:
        f = float(factor)
    except (TypeError, ValueError):
        return 1.0
    if f >= 1.0 - 1e-6:
        return 0.0
    denom = max(1e-6, 1.0 - tf_lo)
    return max(0.0, min(1.0, (1.0 - f) / denom))


def parse_tilt_step(step):
    on = parse_step_bool(step.get("on"), True)
    strength = step.get("strength")
    if strength is None or str(strength).strip() == "":
        fac = step.get("factor")
        if fac is not None and str(fac).strip() != "":
            try:
                strength = tilt_strength_from_factor(float(fac))
            except (TypeError, ValueError):
                strength = 1.0 if on else 0.0
        else:
            try:
                default_f = float(CONFIG.get("TILT_BG_ON_FACTOR", 0.72))
            except Exception:
                default_f = 0.72
            strength = tilt_strength_from_factor(default_f) if on else 0.0
    strength = parse_strength_01(strength, 1.0 if on else 0.0)
    target = tilt_factor_from_strength(strength, on=on)
    dur = parse_duration_sec(step, default_sec=float(CONFIG.get("TILT_DEFAULT_DURATION_SEC", 1.0) or 1.0))
    return {
        "on": bool(on),
        "strength": float(strength),
        "target": float(target),
        "duration_sec": float(dur),
        "instant": float(dur) <= 0.0,
    }


def parse_shear_step(step):
    on = parse_step_bool(step.get("on"), True)
    strength = step.get("strength")
    if strength is None or str(strength).strip() == "":
        mul = step.get("strength_mul", step.get("mul"))
        if mul is not None and str(mul).strip() != "":
            strength = mul
        elif parse_step_bool(step.get("full", step.get("bypass")), False):
            strength = 1.0
        else:
            strength = 1.0 if on else 0.0
    strength = parse_strength_01(strength, 1.0 if on else 0.0)
    dur = parse_duration_sec(step, default_sec=float(CONFIG.get("SHEAR_DEFAULT_DURATION_SEC", 1.0) or 1.0))
    out = {
        "on": bool(on),
        "strength": float(strength),
        "duration_sec": float(dur),
        "instant": float(dur) <= 0.0,
        "bypass_strength": bool(
            parse_step_bool(step.get("full", step.get("bypass")), False) or float(strength) >= 0.999
        ),
    }
    px = step.get("px")
    if px is not None and str(px).strip() != "":
        try:
            out["max_px"] = max(0, min(256, int(px)))
        except (TypeError, ValueError):
            pass
    return out


def parse_zoom_step(step):
    """ZOOM: on, strength(0~1), duration_sec(초)만 사용. val은 구형 호환 읽기만."""
    on = parse_step_bool(step.get("on"), True)
    raw_tgt = (step.get("target") or "").strip()
    lt = raw_tgt.lower()
    cam_aliases = ("", "camera", "cam", "screen", "global", "__global__")
    is_cam = lt in cam_aliases

    strength = step.get("strength")
    if strength is None or str(strength).strip() == "":
        val = step.get("val")
        if val is not None and str(val).strip() != "":
            try:
                v = float(val)
                if is_cam:
                    zmin = float(CONFIG.get("WORLD_ZOOM_MIN", 1.0))
                    zmax = float(CONFIG.get("WORLD_ZOOM_MAX", 2.0))
                else:
                    zmin = float(CONFIG.get("ENTITY_ZOOM_MIN", 1.0))
                    zmax = float(CONFIG.get("ENTITY_ZOOM_MAX", 2.0))
                span = max(1e-6, zmax - zmin)
                strength = max(0.0, min(1.0, (v - zmin) / span)) if on else 0.0
            except (TypeError, ValueError):
                strength = 1.0 if on else 0.0
        else:
            strength = 1.0 if on else 0.0
    strength = parse_strength_01(strength, 1.0 if on else 0.0)
    zoom_val = zoom_val_from_strength(strength, on=on, is_camera=is_cam)

    default_d = float(CONFIG.get("WORLD_ZOOM_DEFAULT_DURATION_SEC", 1.0) or 1.0)
    if not is_cam:
        default_d = float(CONFIG.get("ENTITY_ZOOM_DEFAULT_DURATION_SEC", 1.0) or 1.0)
    dur = parse_duration_sec(step, default_sec=default_d)

    return {
        "on": bool(on),
        "strength": float(strength),
        "val": float(zoom_val),
        "target": raw_tgt,
        "is_camera": bool(is_cam),
        "duration_sec": float(dur),
        "instant": float(dur) <= 0.0,
    }


def parse_camera_step(step):
    mode = (step.get("mode") or "follow_player").strip().lower()
    smooth = parse_step_bool(step.get("smooth"), True)
    dur = parse_duration_sec(step, default_sec=float(CONFIG.get("CAMERA_DEFAULT_DURATION_SEC", 0.5) or 0.5))
    lerp = step.get("lerp", step.get("speed"))
    lerp_f = None
    if lerp is not None and str(lerp).strip() != "":
        try:
            lerp_f = max(0.02, min(1.0, float(lerp)))
        except (TypeError, ValueError):
            lerp_f = None
    return {
        "mode": mode,
        "smooth": bool(smooth) if smooth is not None else True,
        "duration_sec": float(dur),
        "lerp": lerp_f,
        "slot": str(step.get("slot") or step.get("save_slot") or "default").strip() or "default",
        "target": (step.get("target") or step.get("name") or "").strip(),
        "x": step.get("x", step.get("wx")),
        "y": step.get("y", step.get("wy")),
    }


def _canonical_tilt_json(parsed):
    return {
        "type": "TILT",
        "on": bool(parsed["on"]),
        "strength": round(float(parsed["strength"]), 4),
        "duration_sec": round(float(parsed["duration_sec"]), 4),
    }


def _canonical_shear_json(parsed):
    j = {
        "type": "SHEAR",
        "on": bool(parsed["on"]),
        "strength": round(float(parsed["strength"]), 4),
        "duration_sec": round(float(parsed["duration_sec"]), 4),
    }
    if parsed.get("max_px") is not None:
        j["max_px"] = int(parsed["max_px"])
    return j


def _canonical_zoom_json(parsed):
    j = {
        "type": "ZOOM",
        "on": bool(parsed["on"]),
        "strength": round(float(parsed["strength"]), 4),
        "duration_sec": round(float(parsed["duration_sec"]), 4),
    }
    tgt = (parsed.get("target") or "").strip()
    if tgt:
        j["target"] = tgt
    return j


def fill_editor_fields_from_step(step_fields, step, step_type):
    t = (step_type or "").upper()
    if t == "TILT":
        p = parse_tilt_step(step)
        step_fields["tilt_on"] = "true" if p["on"] else "false"
        step_fields["tilt_strength"] = str(round(p["strength"], 4))
        step_fields["tilt_duration_sec"] = str(round(p["duration_sec"], 4))
    elif t == "SHEAR":
        p = parse_shear_step(step)
        step_fields["shear_on"] = "true" if p["on"] else "false"
        step_fields["shear_strength"] = str(round(p["strength"], 4))
        step_fields["shear_duration_sec"] = str(round(p["duration_sec"], 4))
        step_fields["shear_px"] = "" if p.get("max_px") is None else str(p["max_px"])
    elif t == "ZOOM":
        p = parse_zoom_step(step)
        step_fields["zoom_on"] = "true" if p["on"] else "false"
        step_fields["zoom_strength"] = str(round(p["strength"], 4))
        step_fields["zoom_duration_sec"] = str(round(p["duration_sec"], 4))
        step_fields["target"] = (p.get("target") or "").strip()
    elif t == "CAMERA":
        p = parse_camera_step(step)
        step_fields["cam_mode"] = str(p["mode"])
        step_fields["cam_slot"] = str(p["slot"])
        step_fields["cam_target"] = str(p.get("target") or "")
        step_fields["cam_x"] = "" if p.get("x") is None else str(p["x"])
        step_fields["cam_y"] = "" if p.get("y") is None else str(p["y"])
        step_fields["cam_smooth"] = "true" if p["smooth"] else "false"
        step_fields["cam_duration_sec"] = str(round(p["duration_sec"], 4))
        step_fields["cam_lerp"] = "" if p.get("lerp") is None else str(p["lerp"])


def build_step_from_editor_fields(step_fields, step_type):
    t = (step_type or "").upper()
    if t == "TILT":
        stub = {
            "on": step_fields.get("tilt_on"),
            "strength": step_fields.get("tilt_strength"),
            "duration_sec": step_fields.get("tilt_duration_sec"),
        }
        return _canonical_tilt_json(parse_tilt_step(stub))
    if t == "SHEAR":
        stub = {
            "on": step_fields.get("shear_on"),
            "strength": step_fields.get("shear_strength"),
            "duration_sec": step_fields.get("shear_duration_sec"),
        }
        px = step_fields.get("shear_px")
        if px and str(px).strip():
            stub["px"] = px
        return _canonical_shear_json(parse_shear_step(stub))
    if t == "ZOOM":
        stub = {
            "on": step_fields.get("zoom_on"),
            "strength": step_fields.get("zoom_strength"),
            "duration_sec": step_fields.get("zoom_duration_sec"),
            "target": step_fields.get("target"),
        }
        return _canonical_zoom_json(parse_zoom_step(stub))
    return None


def apply_pending_camera_command(cam, cmd, *, player=None, npcs=None, objs=None):
    if not isinstance(cmd, dict):
        return
    mode = (cmd.get("mode") or "follow_player").strip().lower()
    sm = cmd.get("smooth", True)
    if isinstance(sm, str):
        smooth_b = sm.strip().lower() not in ("0", "false", "f", "no", "n", "off")
    else:
        smooth_b = bool(sm)
    ler = cmd.get("lerp", cmd.get("speed"))
    dur = cmd.get("duration_sec")

    def _set_view_lock(wx, wy):
        try:
            cam._view_lock_world_x = float(wx)
            cam._view_lock_world_y = float(wy)
        except Exception:
            pass

    def _snap_cam_blend_if_at(fx, fy):
        try:
            if abs(float(cam.pos[0]) - float(fx)) <= 1e-3 and abs(float(cam.pos[1]) - float(fy)) <= 1e-3:
                cam.pos[0] = float(fx)
                cam.pos[1] = float(fy)
                cam._cam_blend_duration_sec = None
                cam._cam_blend_t0_ms = None
                cam._cam_blend_start = None
        except Exception:
            pass

    if mode in ("lock_here", "lock_current", "camera_lock_here", "lock", "고정", "현재_고정", "현재카메라위치고정"):
        try:
            cx = float(cam.pos[0])
            cy = float(cam.pos[1])
        except Exception:
            cx, cy = 0.0, 0.0
        # 쉬어/줌 렌더 앵커: 고정 직전(추적 대상) 스냅샷 — cam.pos와 다를 수 있음
        render_ax, render_ay = cx, cy
        try:
            render_ax, render_ay = cam.get_focus_world_point(player, npcs, objs)
        except Exception:
            pass
        cam.set_fixed_world(cx, cy, smooth=smooth_b, lerp=ler, duration_sec=dur)
        _set_view_lock(render_ax, render_ay)
        _snap_cam_blend_if_at(cx, cy)
    elif mode in ("fixed", "fixed_world", "world", "point"):
        try:
            x = float(cmd.get("x", 0))
            y = float(cmd.get("y", 0))
        except (TypeError, ValueError):
            x, y = 0.0, 0.0
        render_ax, render_ay = float(cam.pos[0]), float(cam.pos[1])
        try:
            render_ax, render_ay = cam.get_focus_world_point(player, npcs, objs)
        except Exception:
            pass
        try:
            blend_d = cam._norm_cam_duration(dur)
        except Exception:
            blend_d = None
        at_target = (
            abs(float(cam.pos[0]) - x) <= 1e-3
            and abs(float(cam.pos[1]) - y) <= 1e-3
        )
        cam.set_fixed_world(x, y, smooth=smooth_b, lerp=ler, duration_sec=dur)
        if blend_d is not None and not at_target:
            try:
                cam._view_lock_blend_from = [float(render_ax), float(render_ay)]
                cam._view_lock_blend_to = [float(x), float(y)]
            except Exception:
                cam._view_lock_blend_from = None
                cam._view_lock_blend_to = None
            _set_view_lock(render_ax, render_ay)
        else:
            cam._view_lock_blend_from = None
            cam._view_lock_blend_to = None
            _set_view_lock(x, y)
            _snap_cam_blend_if_at(x, y)
    elif mode in ("follow_entity", "follow", "entity"):
        tgt = (cmd.get("target") or cmd.get("name") or "").strip()
        cam.set_follow_entity(tgt or "player", smooth=smooth_b, lerp=ler, duration_sec=dur)
    else:
        cam.set_follow_player(smooth=smooth_b, lerp=ler, duration_sec=dur)


def _pygame_key_from_spec(spec) -> int | None:
    s = str(spec or "").strip()
    if not s:
        return None
    if s.upper().startswith("K_"):
        return getattr(pygame, s.upper(), None)
    low = s.lower()
    if len(low) == 1:
        return getattr(pygame, "K_" + low, None)
    if low.startswith("f") and low[1:].isdigit():
        return getattr(pygame, "K_F" + low[1:], None)
    return getattr(pygame, "K_" + low.upper(), None)


def build_global_hotkey_event_map():
    raw = CONFIG.get("GLOBAL_EVENT_HOTKEYS") or []
    out = {}
    if not isinstance(raw, (list, tuple)):
        return out
    for row in raw:
        if not isinstance(row, dict):
            continue
        kspec = row.get("key") or row.get("pygame_key")
        eid = str(row.get("event_id") or row.get("id") or "").strip()
        pk = _pygame_key_from_spec(kspec)
        if pk is not None and eid:
            out[int(pk)] = eid
    return out


def apply_dev_runtime_command(cmd, *, ev_mgr, cam, flow, map_id, player, step=None):
    """DEV_CMD / 핫키용: 필드에서 즉시 실행되는 디버그·시스템 동작.

    step: 이벤트 스텝 dict (선택). start_fishing 등에 pond·win_flag 전달.
    """
    rt = FIELD_RUNTIME_UI
    n = (cmd or "").strip().lower()
    if n == "toggle_show_mask":
        rt.show_mask = not rt.show_mask
    elif n == "toggle_show_overlay":
        rt.show_overlay_text = not rt.show_overlay_text
    elif n in ("toggle_camera_focus", "toggle_cam_focus"):
        rt.show_camera_focus = not rt.show_camera_focus
    elif n == "toggle_tilt_demo":
        if ev_mgr.active_event and isinstance(getattr(ev_mgr, "tilt_control", None), dict):
            return
        rt.tilt_bg_demo = not rt.tilt_bg_demo
        try:
            rt.tilt_target = float(CONFIG.get("TILT_BG_ON_FACTOR", 0.72)) if rt.tilt_bg_demo else 1.0
        except Exception:
            rt.tilt_target = 0.72 if rt.tilt_bg_demo else 1.0
        try:
            _tf_lo = float(CONFIG.get("TILT_FACTOR_MIN", 0.2))
        except Exception:
            _tf_lo = 0.2
        _tf_lo = max(0.02, min(0.99, _tf_lo))
        rt.tilt_target = max(_tf_lo, min(1.0, float(rt.tilt_target)))
    elif n == "toggle_shear_debug":
        if ev_mgr.active_event and isinstance(getattr(ev_mgr, "shear_control", None), dict):
            return
        try:
            default_shear = bool(CONFIG.get("TILT_SHEAR_ENABLED", False))
        except Exception:
            default_shear = False
        if default_shear:
            # 필드 기본 쉬어 ON 상태: 핫키는 끄기/켜기(억제) 토글
            rt.shear_suppressed = not bool(getattr(rt, "shear_suppressed", False))
            rt.shear_debug_on = False
        else:
            rt.shear_debug_on = not rt.shear_debug_on
            rt.shear_suppressed = False
    elif n == "cycle_zoom_debug":
        steps = CONFIG.get("DEBUG_ZOOM_STEPS", [2.0, 0.5, 1.0])
        if not isinstance(steps, (list, tuple)) or not steps:
            steps = [2.0, 0.5, 1.0]
        rt.zoom_idx = (int(rt.zoom_idx) + 1) % len(steps)
        try:
            # 새 줌 시스템: 카메라 줌이 아니라 main.py가 소비하는 "월드 줌 목표"를 요청한다.
            try:
                ev_mgr.pending_world_zoom = float(steps[int(rt.zoom_idx)])
            except Exception:
                pass
        except (TypeError, ValueError, IndexError):
            pass
    elif n == "toggle_jump_shadow":
        cur = (flow.save_data.get("jump_shadow_mode") or "ground").lower()
        flow.save_data["jump_shadow_mode"] = "hide" if cur == "ground" else "ground"
        flow.save_game(map_id, player.pos)
        print(
            "[그림자] 점프 중: "
            + (
                "숨김(도랑 등)"
                if flow.save_data["jump_shadow_mode"] == "hide"
                else "땅에 옅게(크기·투명도)"
            )
        )
    elif n == "toggle_fullscreen":
        pygame.display.toggle_fullscreen()
    elif n == "camera_follow_player":
        cam.set_follow_player(smooth=True)
    elif n == "start_swing_ride":
        # 이벤트 스텝에서 그네 탑승 데모를 시작시키기 위한 요청.
        # 실제 탑승 상태(swing_ride_mode)는 main.py가 안전하게 적용한다.
        try:
            ev_mgr.swing_ride_request = {"action": "start"}
        except Exception:
            pass
    elif n == "start_fishing":
        from activities import request_field_activity

        pond = "jjangpu_water1"
        params = {"await_tap": True}
        if isinstance(step, dict):
            pond = str(step.get("pond") or step.get("pond_id") or pond).strip()
            if step.get("win_flag"):
                params["win_flag"] = step.get("win_flag")
            if step.get("await_tap") is not None:
                params["await_tap"] = step.get("await_tap")
        request_field_activity(ev_mgr, "fishing", pond=pond, **params)
    elif n == "stop_fishing":
        try:
            ev_mgr.field_activity_stop_request = True
        except Exception:
            pass
        try:
            ev_mgr.remove_ui_overlay("fishing_exit")
        except Exception:
            pass
        try:
            ev_mgr.pending_camera_command = {
                "mode": "follow_player",
                "smooth": True,
                "duration_sec": 0.5,
            }
        except Exception:
            pass
    elif n.startswith("start_activity_"):
        # 범용: start_activity_fishing, start_activity_swing (추후)
        from activities import request_field_activity

        act_id = n[len("start_activity_") :].strip()
        params = {}
        if isinstance(step, dict):
            for k in ("pond", "pond_id", "win_flag"):
                if k in step and step.get(k) is not None:
                    params[k] = step.get(k)
        if act_id:
            request_field_activity(ev_mgr, act_id, **params)
    elif n == "restart_delete_save":
        try:
            if os.path.isfile(flow.save_path):
                os.remove(flow.save_path)
        except Exception as e:
            print(f"[DEBUG] save delete failed: {e}")
        try:
            pygame.quit()
        except Exception:
            pass
        os.execv(sys.executable, [sys.executable, os.path.abspath(sys.argv[0])])
    else:
        print(f"[DEV_CMD] unknown: {cmd}")


def try_start_hotkey_global_event(
    pygame_key_int,
    *,
    ev_mgr,
    events_catalog,
):
    """data.py GLOBAL_EVENT_HOTKEYS 에 매핑된 글로벌 이벤트를 시작. 성공 시 True."""
    if ev_mgr.active_event:
        return False
    table = build_global_hotkey_event_map()
    eid = table.get(int(pygame_key_int))
    if not eid:
        return False
    from flow import start_system_event

    # 스냅샷을 넘기면 end_event 시 pending_field_tilt_restore로 필드 틸트/쉬어가 되돌아가
    # 한 프레임짜리 핫키(DEV_CMD)는 토글이 즉시 취소되므로 복원 스냅샷 없이 시작한다.
    return start_system_event(ev_mgr, events_catalog, eid, field_tilt_snapshot=None)


class CloudShadowSystem:
    def __init__(self):
        self._base_imgs = None
        self._clouds = []
        self._spawn_acc = 0.0
        self._last_enabled = None
        self._active_dir_setting = None
        self._active_dir_vec = None
        self._render_cache = OrderedDict()

    def _cell_size(self, settings):
        g = settings.get("grid_cell") if isinstance(settings, dict) else None
        if g is not None and str(g).strip() != "":
            try:
                v = float(g)
                if v >= 24.0:
                    return v
            except (TypeError, ValueError):
                pass
        try:
            v = float(CONFIG.get("CLOUD_SHADOW_GRID_CELL_PX", 160) or 160)
        except Exception:
            v = 160.0
        return max(24.0, min(800.0, v))

    def _jitter_half(self, settings, cell):
        jr = settings.get("grid_jitter") if isinstance(settings, dict) else None
        if jr is None or str(jr).strip() == "":
            try:
                jr = float(CONFIG.get("CLOUD_SHADOW_GRID_JITTER_RATIO", 0.42) or 0.42)
            except Exception:
                jr = 0.42
        else:
            try:
                jr = float(jr)
            except (TypeError, ValueError):
                jr = 0.42
        jr = max(0.0, min(0.49, jr))
        return jr * float(cell)

    def _grid_max_clouds(self, settings):
        m = settings.get("grid_max") if isinstance(settings, dict) else None
        if m is not None and str(m).strip() != "":
            try:
                return max(8, min(400, int(m)))
            except (TypeError, ValueError):
                pass
        try:
            return max(8, min(400, int(CONFIG.get("CLOUD_SHADOW_GRID_MAX_CLOUDS", 200) or 200)))
        except Exception:
            return 200

    def _load_images(self):
        if self._base_imgs is not None:
            return
        imgs = []
        for i in (1, 2, 3):
            p = os.path.join("assets", "images", "fx", f"cloud{i}.png")
            try:
                imgs.append(pygame.image.load(p).convert_alpha())
            except Exception:
                pass
        self._base_imgs = imgs

    def _dir_vec(self, d):
        d = (d or "RANDOM").strip().upper()
        if d == "SE":
            return 1.0, 1.0
        if d == "SW":
            return -1.0, 1.0
        if d == "NE":
            return 1.0, -1.0
        if d == "NW":
            return -1.0, -1.0
        return None, None

    def _pick_dir_once(self, d):
        vx, vy = self._dir_vec(d)
        if vx is not None:
            return vx, vy
        return random.choice([(1.0, 1.0), (-1.0, 1.0), (1.0, -1.0), (-1.0, -1.0)])

    def _cache_get_render(self, img_i, scale, zoom, f_q, alpha, soften=0.0):
        qscale = round(float(scale), 2)
        qzoom = round(float(zoom), 2)
        qfq = round(float(f_q), 2)
        a = int(max(0, min(255, int(alpha))))
        try:
            sof = float(soften)
        except Exception:
            sof = 0.0
        sof = max(0.0, min(1.0, sof))
        qsof = round(sof, 2)
        key = (int(img_i), qscale, qzoom, qfq, a, qsof)
        surf = self._render_cache.get(key)
        if surf is not None:
            try:
                self._render_cache.move_to_end(key)
            except Exception:
                pass
            return surf
        base = self._base_imgs[int(img_i)]
        w0, h0 = base.get_size()
        w = max(8, int(round(w0 * qscale * qzoom)))
        h = max(8, int(round(h0 * qscale * qzoom * qfq)))
        s = pygame.transform.scale(base, (w, h)) if (w, h) != base.get_size() else base.copy()
        s.fill((0, 0, 0, a), special_flags=pygame.BLEND_RGBA_MULT)
        if qsof > 1e-6 and w >= 12 and h >= 12:
            shrink = 1.0 - 0.65 * qsof
            sw = max(8, int(round(w * shrink)))
            sh = max(8, int(round(h * shrink)))
            if sw < w or sh < h:
                try:
                    s2 = pygame.transform.scale(s, (sw, sh))
                    s = pygame.transform.scale(s2, (w, h))
                except Exception:
                    pass
        self._render_cache[key] = s
        try:
            self._render_cache.move_to_end(key)
        except Exception:
            pass
        while len(self._render_cache) > 160:
            try:
                self._render_cache.popitem(last=False)
            except Exception:
                break
        return s

    def _wind_velocity(self, speed):
        if not self._active_dir_vec:
            return 0.0, 0.0
        dx, dy = self._active_dir_vec
        s = float(speed) / max(1e-6, (2 ** 0.5))
        return dx * s, dy * s

    def _append_cloud(self, wx, wy, speed, scale_min, scale_max, age_sec=0.0):
        self._load_images()
        if not self._base_imgs:
            return
        vx, vy = self._wind_velocity(speed)
        if vx == 0.0 and vy == 0.0:
            return
        img_i = random.randrange(0, len(self._base_imgs))
        sc = random.uniform(float(scale_min), float(scale_max))
        try:
            t = max(0.0, float(age_sec))
        except Exception:
            t = 0.0
        wx = float(wx) + vx * t
        wy = float(wy) + vy * t
        self._clouds.append(
            {"img_i": int(img_i), "scale": float(sc), "wx": float(wx), "wy": float(wy), "vx": float(vx), "vy": float(vy)}
        )

    def _iter_fill_cells(self, vx0, vy0, vx1, vy1, margin, cell):
        ix0 = int(math.ceil((vx0 - margin) / cell - 0.5))
        ix1 = int(math.floor((vx1 + margin) / cell - 0.5))
        iy0 = int(math.ceil((vy0 - margin) / cell - 0.5))
        iy1 = int(math.floor((vy1 + margin) / cell - 0.5))
        if ix1 < ix0 or iy1 < iy0:
            return
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                yield ix, iy

    def _fill_view_grid(self, settings, map_w, map_h, speed, scale_min, scale_max, view_rect, margin):
        if not self._active_dir_vec or not view_rect or len(view_rect) < 4:
            return
        cell = self._cell_size(settings)
        jh = self._jitter_half(settings, cell)
        vx0, vy0, vw, vh = float(view_rect[0]), float(view_rect[1]), float(view_rect[2]), float(view_rect[3])
        vx1, vy1 = vx0 + vw, vy0 + vh
        cells = list(self._iter_fill_cells(vx0, vy0, vx1, vy1, margin, cell))
        cap = self._grid_max_clouds(settings)
        if len(cells) > cap:
            cells = random.sample(cells, cap)
        spd = max(1e-3, float(speed))
        t_max = (cell * 2.0) / spd
        for ix, iy in cells:
            cx = (ix + 0.5) * cell
            cy = (iy + 0.5) * cell
            wx = cx + random.uniform(-jh, jh)
            wy = cy + random.uniform(-jh, jh)
            wx = max(-margin, min(float(map_w) + margin, wx))
            wy = max(-margin, min(float(map_h) + margin, wy))
            self._append_cloud(wx, wy, speed, scale_min, scale_max, age_sec=random.uniform(0.0, t_max))

    def _spawn_edge_grid(self, settings, map_w, map_h, speed, scale_min, scale_max, view_rect, margin):
        if not self._active_dir_vec or not view_rect or len(view_rect) < 4:
            return
        dx, dy = self._active_dir_vec
        cell = self._cell_size(settings)
        jh = self._jitter_half(settings, cell)
        vx0, vy0, vw, vh = float(view_rect[0]), float(view_rect[1]), float(view_rect[2]), float(view_rect[3])
        vx1, vy1 = vx0 + vw, vy0 + vh
        ix_v0 = int(math.ceil(vx0 / cell - 0.5))
        ix_v1 = int(math.floor(vx1 / cell - 0.5))
        iy_v0 = int(math.ceil(vy0 / cell - 0.5))
        iy_v1 = int(math.floor(vy1 / cell - 0.5))
        iy_e0 = int(math.ceil((vy0 - margin) / cell - 0.5))
        iy_e1 = int(math.floor((vy1 + margin) / cell - 0.5))
        ix_e0 = int(math.ceil((vx0 - margin) / cell - 0.5))
        ix_e1 = int(math.floor((vx1 + margin) / cell - 0.5))
        strips = 2
        boundary = []
        if dx > 0:
            for k in range(1, strips + 1):
                ix = ix_v0 - k
                for iy in range(iy_e0, iy_e1 + 1):
                    boundary.append((ix, iy))
        elif dx < 0:
            for k in range(1, strips + 1):
                ix = ix_v1 + k
                for iy in range(iy_e0, iy_e1 + 1):
                    boundary.append((ix, iy))
        if dy > 0:
            for k in range(1, strips + 1):
                iy = iy_v0 - k
                for ix in range(ix_e0, ix_e1 + 1):
                    boundary.append((ix, iy))
        elif dy < 0:
            for k in range(1, strips + 1):
                iy = iy_v1 + k
                for ix in range(ix_e0, ix_e1 + 1):
                    boundary.append((ix, iy))
        if not boundary:
            return
        ix, iy = random.choice(boundary)
        wx = (ix + 0.5) * cell + random.uniform(-jh, jh)
        wy = (iy + 0.5) * cell + random.uniform(-jh, jh)
        wx = max(-margin, min(float(map_w) + margin, wx))
        wy = max(-margin, min(float(map_h) + margin, wy))
        self._append_cloud(wx, wy, speed, scale_min, scale_max, age_sec=0.0)

    def update_and_draw_world(self, screen, dt_sec, settings, cam_x, cam_y, zoom, y_transform=None, x_offset_fn=None, f_q=1.0, map_size=None):
        enabled = bool(settings.get("enabled", False))
        if self._last_enabled is None:
            self._last_enabled = enabled
        if not enabled:
            if self._last_enabled:
                self._clouds.clear()
                self._spawn_acc = 0.0
                self._render_cache.clear()
            self._last_enabled = False
            self._active_dir_setting = None
            self._active_dir_vec = None
            return

        dir_setting = str(settings.get("dir", "RANDOM") or "RANDOM").strip().upper()
        if not self._last_enabled:
            self._clouds.clear()
            self._spawn_acc = 0.0
            self._render_cache.clear()
            self._active_dir_setting = dir_setting
            self._active_dir_vec = self._pick_dir_once(dir_setting)
        elif self._active_dir_setting != dir_setting:
            self._clouds.clear()
            self._spawn_acc = 0.0
            self._render_cache.clear()
            self._active_dir_setting = dir_setting
            self._active_dir_vec = self._pick_dir_once(dir_setting)

        self._last_enabled = True
        self._load_images()
        if not self._base_imgs:
            return

        try:
            freq = max(0.0, float(settings.get("freq", 0.0)))
        except Exception:
            freq = 0.0
        try:
            speed = float(settings.get("speed", 20.0))
        except Exception:
            speed = 20.0
        alpha = int(settings.get("alpha", 70) or 70)
        scale_min = float(settings.get("scale_min", 0.8))
        scale_max = float(settings.get("scale_max", 1.4))
        if scale_max < scale_min:
            scale_min, scale_max = scale_max, scale_min
        scale_min = max(0.2, min(4.0, scale_min))
        scale_max = max(0.2, min(4.0, scale_max))

        if map_size and isinstance(map_size, (list, tuple)) and len(map_size) >= 2:
            map_w, map_h = float(map_size[0]), float(map_size[1])
        else:
            sw, sh = screen.get_size()
            map_w, map_h = float(sw) / max(1e-6, float(zoom)), float(sh) / max(1e-6, float(zoom))

        view_w = float(CONFIG["WIDTH"]) / max(1e-6, float(zoom))
        view_h = float(CONFIG["HEIGHT"]) / max(1e-6, float(zoom))
        view_rect = (float(cam_x), float(cam_y), float(view_w), float(view_h))

        if not self._clouds and freq > 0.0:
            self._fill_view_grid(settings, map_w, map_h, speed, scale_min, scale_max, view_rect, margin=220)

        self._spawn_acc += freq * max(0.0, float(dt_sec))
        while self._spawn_acc >= 1.0:
            self._spawn_acc -= 1.0
            self._spawn_edge_grid(settings, map_w, map_h, speed, scale_min, scale_max, view_rect, margin=220)

        dt = max(0.0, float(dt_sec))
        keep = []
        margin = 220
        for c in self._clouds:
            c["wx"] += c["vx"] * dt
            c["wy"] += c["vy"] * dt
            wx, wy = float(c["wx"]), float(c["wy"])
            if wx < -margin or wx > map_w + margin or wy < -margin or wy > map_h + margin:
                continue
            keep.append(c)
            # main.py 배경 blit과 동일: int(round((0-cam)*zoom)) 원점 + 월드*줌 (스프라이트/배경과 픽셀 정렬)
            try:
                zd = float(zoom)
                bdx = int(round((0.0 - float(cam_x)) * zd))
                bdy = int(round((0.0 - float(cam_y)) * zd))
            except Exception:
                zd = float(zoom)
                bdx = bdy = 0
            sx = float(bdx) + wx * zd
            sy = float(bdy) + wy * zd
            if callable(y_transform):
                try:
                    sy = float(y_transform(float(sy)))
                except Exception:
                    pass
            if callable(x_offset_fn):
                try:
                    sx = float(sx) + float(x_offset_fn(float(sy)))
                except Exception:
                    pass
            soft = settings.get("soften", 0.0)
            surf = self._cache_get_render(c["img_i"], c["scale"], zoom, f_q, alpha, soften=soft)
            screen.blit(surf, (int(round(sx)), int(round(sy))))
        self._clouds = keep

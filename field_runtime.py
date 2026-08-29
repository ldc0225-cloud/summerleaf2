"""
필드 플레이 중 디버그 UI 상태, 구름 FX, 글로벌 핫키→이벤트, DEV_CMD 처리.
main.py 비대화를 줄이기 위해 분리.
"""
from __future__ import annotations

import json
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
        "rotate3d_on",
        "rotate3d_target",
        "rotate3d_angle",
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
        self.zoom_idx = 1
        self.rotate3d_on = False
        self.rotate3d_target = 0.0
        self.rotate3d_angle = 0.0


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


def parse_step_persist(step, *, default=None) -> bool:
    """이벤트 ENTITY_FX·엔티티 ZOOM — 종료 후에도 유지할지."""
    if not isinstance(step, dict):
        if default is not None:
            return bool(default)
        try:
            return bool(CONFIG.get("ENTITY_FX_DEFAULT_PERSIST", False))
        except Exception:
            return False
    raw = step.get("persist")
    if raw is None:
        raw = step.get("keep_after_event", step.get("hold_after_event"))
    if raw is None:
        if default is not None:
            return bool(default)
        try:
            return bool(CONFIG.get("ENTITY_FX_DEFAULT_PERSIST", False))
        except Exception:
            return False
    return bool(parse_step_bool(raw, False))


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
    {"ZOOM", "TILT", "SHEAR", "CAMERA", "3D_ROTATE", "CONDITION", "CONDITION_SKIP"}
)


def effect_now_ms():
    return int(pygame.time.get_ticks())


# =============================================================================
# 시각 연출 시간 통일 (프레임 수가 아닌 실제 경과 초)
# 페이드·오버레이·틸트/쉬어/카메라 보간이 FPS·fixed timestep과 무관하게 동일 체감.
# =============================================================================

def visual_dt_ref_sec() -> float:
    """지수 보간 기준 프레임 길이(초). 60fps 1프레임 ≈ 0.0167."""
    try:
        v = float(CONFIG.get("VISUAL_DT_REF_SEC", 1.0 / 60.0) or (1.0 / 60.0))
    except Exception:
        v = 1.0 / 60.0
    return max(1e-6, v)


def visual_smooth_step(speed_01: float, dt_sec: float) -> float:
    """프레임율 무관 지수 보간 계수 (0~1). legacy step_ms/16.666 exponential과 60fps에서 동일."""
    dt = max(0.0, float(dt_sec))
    spd = max(0.0, min(1.0, float(speed_01)))
    k = dt / visual_dt_ref_sec()
    return 1.0 - pow(max(0.0, 1.0 - spd), k)


def fade_alpha_delta(span: float, duration_sec: float, dt_sec: float) -> float:
    """선형 알파 페이드 한 틱 변화량."""
    dur = max(1e-6, float(duration_sec))
    return (float(span) / dur) * max(0.0, float(dt_sec))


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


def world_zoom_hard_max():
    """월드 줌 절대 상한. strength 슬라이더는 WORLD_ZOOM_MAX, val 직접지정만 HARD_MAX까지."""
    try:
        soft = float(CONFIG.get("WORLD_ZOOM_MAX", 4.0))
    except (TypeError, ValueError):
        soft = 4.0
    try:
        hard = float(CONFIG.get("WORLD_ZOOM_HARD_MAX", 8.0))
    except (TypeError, ValueError):
        hard = 8.0
    soft = max(0.05, min(8.0, soft))
    return max(soft, min(8.0, hard))


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


def apply_map_screen_fx_defaults(ev_mgr, screen_fx_cfg) -> None:
    """맵 ambient SCREEN_FX (cloud/rain/vignette/tone) 적용. flash·shake 는 끔.

    screen_fx_cfg: { "cloud": {...}, "rain": {...}, ... } — kind 키가 있으면 ON.
    블록에 on:false 가 있으면 해당 kind 는 OFF.
    엔진 build_*_from_step 재사용 (이벤트 SCREEN_FX 와 동일 파라미터).
    """
    if ev_mgr is None:
        return
    from engine import (
        build_cloud_shadow_control_from_step,
        build_screen_rain_from_step,
        build_screen_vignette_from_step,
        build_screen_tone_from_step,
    )

    # 맵 전환 시 이전 맵·이벤트 ambient 잔상 제거 (번쩍/흔들도 초기화)
    try:
        if hasattr(ev_mgr, "clear_all_screen_fx"):
            ev_mgr.clear_all_screen_fx()
        else:
            ev_mgr.cloud_shadow_control = {"enabled": False}
            ev_mgr.screen_fx_flash = {"enabled": False}
            ev_mgr.screen_fx_shake = {"enabled": False}
            ev_mgr.screen_fx_rain = {"enabled": False}
            ev_mgr.screen_fx_vignette = {"enabled": False}
            ev_mgr.screen_fx_tone = {"enabled": False}
    except Exception:
        return

    if not isinstance(screen_fx_cfg, dict) or not screen_fx_cfg:
        return

    def _block_on(block) -> bool:
        if not isinstance(block, dict):
            return False
        if "on" in block:
            v = block.get("on")
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "t", "yes", "y", "on")
            return bool(v)
        return True

    cloud = screen_fx_cfg.get("cloud")
    if _block_on(cloud):
        try:
            ev_mgr.cloud_shadow_control = build_cloud_shadow_control_from_step(dict(cloud))
        except Exception:
            pass

    rain = screen_fx_cfg.get("rain")
    if _block_on(rain):
        try:
            ev_mgr.screen_fx_rain = build_screen_rain_from_step(dict(rain))
        except Exception:
            pass

    vig = screen_fx_cfg.get("vignette")
    if _block_on(vig):
        try:
            ev_mgr.screen_fx_vignette = build_screen_vignette_from_step(dict(vig))
        except Exception:
            pass

    tone = screen_fx_cfg.get("tone")
    if _block_on(tone):
        try:
            ev_mgr.screen_fx_tone = build_screen_tone_from_step(dict(tone))
        except Exception:
            pass


def apply_map_field_defaults(map_id, ui, ev_mgr=None, world_data=None, wave_ambient=None):
    """맵 진입 시 틸트·쉬어·화면 FX·물결 타일 을 world_data[map].field 에 맞게 설정.

    world_data: flow.world_data.
    - tilt_on / shear_on: 생략 시 CONFIG 전역 기본값.
    - screen_fx: cloud|rain|vignette|tone — 맵 ambient (이벤트 SCREEN_FX 와 동일 빌더).
    - wave_tiles: 공유 프레임 물결 타일 ambient (wave_ambient 인스턴스에 전달).
    스키마: data.resolve_map_field_defaults / data.py 주석.
    """
    from data import resolve_map_field_defaults

    cfg = resolve_map_field_defaults(map_id, world_data=world_data)
    tilt_on = bool(cfg.get("tilt_on", False))
    shear_on = bool(cfg.get("shear_on", False))

    ui.tilt_bg_demo = False
    if tilt_on:
        try:
            fac = float(CONFIG.get("TILT_BG_ON_FACTOR", 0.72))
        except (TypeError, ValueError):
            fac = 0.72
        ui.tilt_target = max(_tilt_factor_min(), min(1.0, fac))
    else:
        ui.tilt_target = 1.0

    try:
        ui.rotate3d_on = False
        ui.rotate3d_target = 0.0
        ui.rotate3d_angle = 0.0
    except Exception:
        pass

    if bool(CONFIG.get("TILT_SHEAR_ENABLED", False)):
        ui.shear_suppressed = not shear_on
        ui.shear_debug_on = False
    else:
        ui.shear_suppressed = False
        ui.shear_debug_on = bool(shear_on)

    if ev_mgr is not None:
        try:
            if not ev_mgr.active_event:
                ev_mgr.shear_control = None
                ev_mgr.tilt_control = None
        except Exception:
            pass

    # 화면 FX ambient (구름·비·비네팅·톤) — 맵마다 리셋 후 적용
    apply_map_screen_fx_defaults(ev_mgr, cfg.get("screen_fx"))
    # 물결 타일 ambient — 맵마다 재구성 (없으면 OFF)
    if wave_ambient is not None:
        try:
            wave_ambient.configure(cfg.get("wave_tiles"))
        except Exception:
            try:
                wave_ambient.configure(None)
            except Exception:
                pass
    return float(ui.tilt_target)


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


def parse_rotate3d_step(step):
    on = parse_step_bool(step.get("on"), True)
    strength = step.get("strength")
    if strength is None or str(strength).strip() == "":
        strength = 1.0 if on else 0.0
    strength = parse_strength_01(strength, 1.0 if on else 0.0)
    dur = parse_duration_sec(step, default_sec=float(CONFIG.get("ROTATE3D_DEFAULT_DURATION_SEC", 0.4) or 0.4))
    return {
        "on": bool(on),
        "strength": float(strength),
        "target": float(strength) if on else 0.0,
        "duration_sec": float(dur),
        "instant": float(dur) <= 0.0,
    }


def parse_zoom_step(step):
    """ZOOM 파싱.

    카메라(월드):
      - strength만: 0~1 → WORLD_ZOOM_MIN~MAX (기본 max=4)
      - val 명시: 직접 배율, WORLD_ZOOM_HARD_MAX까지 (기본 8). strength보다 우선.
    엔티티: val/strength = 직접 배율 (ENTITY_ZOOM_MIN~MAX).
    """
    on = parse_step_bool(step.get("on"), True)
    raw_tgt = (step.get("target") or "").strip()
    lt = raw_tgt.lower()
    cam_aliases = ("", "camera", "cam", "screen", "global", "__global__")
    is_cam = lt in cam_aliases

    default_d = float(CONFIG.get("WORLD_ZOOM_DEFAULT_DURATION_SEC", 1.0) or 1.0)
    if not is_cam:
        default_d = float(CONFIG.get("ENTITY_ZOOM_DEFAULT_DURATION_SEC", 1.0) or 1.0)
    dur = parse_duration_sec(step, default_sec=default_d)

    if not is_cam:
        if not on:
            zoom_val = 1.0
        else:
            val_raw = step.get("val")
            str_raw = step.get("strength")
            if val_raw is not None and str(val_raw).strip() != "":
                picked = val_raw
            elif str_raw is not None and str(str_raw).strip() != "":
                picked = str_raw
            else:
                picked = 1.0
            try:
                zmin = float(CONFIG.get("ENTITY_ZOOM_MIN", 0.5))
                zmax = float(CONFIG.get("ENTITY_ZOOM_MAX", 2.0))
            except (TypeError, ValueError):
                zmin, zmax = 0.5, 2.0
            zmin = max(0.05, min(8.0, zmin))
            zmax = max(zmin, min(8.0, zmax))
            try:
                zoom_val = float(picked)
            except (TypeError, ValueError):
                zoom_val = 1.0
            zoom_val = max(zmin, min(zmax, zoom_val))
        return {
            "on": bool(on),
            "strength": float(zoom_val),
            "val": float(zoom_val),
            "val_explicit": False,
            "target": raw_tgt,
            "is_camera": False,
            "duration_sec": float(dur),
            "instant": float(dur) <= 0.0,
        }

    # --- 카메라(월드) ---
    # val이 있으면 직접 배율(하드 상한까지). 없으면 strength 슬라이더(소프트 상한).
    val_raw = step.get("val")
    has_explicit_val = val_raw is not None and str(val_raw).strip() != ""
    try:
        zmin = float(CONFIG.get("WORLD_ZOOM_MIN", 1.0))
        soft_max = float(CONFIG.get("WORLD_ZOOM_MAX", 4.0))
    except (TypeError, ValueError):
        zmin, soft_max = 1.0, 4.0
    zmin = max(0.05, min(8.0, zmin))
    soft_max = max(zmin, min(8.0, soft_max))
    hard_max = world_zoom_hard_max()

    if has_explicit_val:
        if not on:
            zoom_val = 1.0
            strength = 0.0
        else:
            try:
                zoom_val = float(val_raw)
            except (TypeError, ValueError):
                try:
                    zoom_val = float(CONFIG.get("WORLD_ZOOM_DEFAULT", 1.0))
                except (TypeError, ValueError):
                    zoom_val = 1.0
            zoom_val = max(zmin, min(hard_max, zoom_val))
            span = max(1e-6, soft_max - zmin)
            # 에디터 strength 표시용(소프트 범위 밖이면 1.0으로 캡)
            strength = max(0.0, min(1.0, (zoom_val - zmin) / span))
        return {
            "on": bool(on),
            "strength": float(strength),
            "val": float(zoom_val),
            "val_explicit": True,
            "target": raw_tgt,
            "is_camera": True,
            "duration_sec": float(dur),
            "instant": float(dur) <= 0.0,
        }

    strength = step.get("strength")
    if strength is None or str(strength).strip() == "":
        strength = 1.0 if on else 0.0
    strength = parse_strength_01(strength, 1.0 if on else 0.0)
    zoom_val = zoom_val_from_strength(strength, on=on, is_camera=True)

    return {
        "on": bool(on),
        "strength": float(strength),
        "val": float(zoom_val),
        "val_explicit": False,
        "target": raw_tgt,
        "is_camera": True,
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


# RESULT 스텝 메타키 — 세이브에 쓰지 않음 (헤더 result 와 동일 페이로드 키만 반영)
_RESULT_STEP_META_KEYS = frozenset(
    {
        "type",
        "target",
        "who",
        "text",
        "name",
        "action",
        "wait",
        "instant",
        "key",
        "var",
        "value",
        "opt",
        "options",
        "extra",
        "patch",
    }
)


def parse_result_step(step):
    """RESULT 스텝 → events.json 헤더 result 와 같은 patch dict.

    사용 예:
      { "type":"RESULT", "mainprogress":"ev_xxx" }
      { "type":"RESULT", "key":"progress_flower1_1", "val":1004 }
      { "type":"RESULT", "add_laugh_point":5, "progress_flower1_1":1004 }
      { "type":"RESULT", "opt":"{\\"progress_x\\": 1002}" }  # JSON 추가키

    헤더 result 는 이벤트 종료 시 그대로 적용. 이 스텝은 중간에 같은 갱신을 수행.
    """
    out = {}
    if not isinstance(step, dict):
        return out

    # key/val (또는 var/value) 단축 — 진행 플래그 하나 갱신할 때
    k = str(step.get("key") or step.get("var") or "").strip()
    if k:
        if "val" in step and step.get("val") is not None and str(step.get("val")).strip() != "":
            out[k] = step.get("val")
        elif "value" in step and step.get("value") is not None and str(step.get("value")).strip() != "":
            out[k] = step.get("value")

    # opt/extra: JSON 객체 문자열 또는 dict
    for opt_key in ("opt", "options", "extra", "patch"):
        raw = step.get(opt_key)
        if raw is None or raw == "":
            continue
        if isinstance(raw, dict):
            for rk, rv in raw.items():
                sk = str(rk).strip()
                if sk:
                    out[sk] = rv
            continue
        try:
            parsed = json.loads(str(raw))
            if isinstance(parsed, dict):
                for rk, rv in parsed.items():
                    sk = str(rk).strip()
                    if sk:
                        out[sk] = rv
        except Exception:
            pass

    # 스텝에 직접 적은 키 (mainprogress, add_laugh_point, progress_* …)
    for rk, rv in step.items():
        if rk in _RESULT_STEP_META_KEYS:
            continue
        # key/val 단축을 썼을 때 단독 val 은 세이브 키로 취급하지 않음
        if rk == "val" and k:
            continue
        if rv is None:
            continue
        if isinstance(rv, str) and str(rv).strip() == "":
            continue
        out[str(rk)] = rv
    return out


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
        "duration_sec": round(float(parsed["duration_sec"]), 4),
    }
    # val 직접지정이면 val만 저장(하드 상한 배율 유지). 아니면 strength 슬라이더.
    if parsed.get("val_explicit"):
        j["val"] = round(float(parsed["val"]), 4)
    else:
        j["strength"] = round(float(parsed["strength"]), 4)
    tgt = (parsed.get("target") or "").strip()
    if tgt:
        j["target"] = tgt
    if parsed.get("persist"):
        j["persist"] = True
    return j


def _canonical_rotate3d_json(parsed):
    return {
        "type": "3D_ROTATE",
        "on": bool(parsed["on"]),
        "strength": round(float(parsed["strength"]), 4),
        "duration_sec": round(float(parsed["duration_sec"]), 4),
    }


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
    elif t == "3D_ROTATE":
        p = parse_rotate3d_step(step)
        step_fields["rotate3d_on"] = "true" if p["on"] else "false"
        step_fields["rotate3d_strength"] = str(round(p["strength"], 4))
        step_fields["rotate3d_duration_sec"] = str(round(p["duration_sec"], 4))
    elif t == "ZOOM":
        p = parse_zoom_step(step)
        step_fields["zoom_on"] = "true" if p["on"] else "false"
        step_fields["zoom_duration_sec"] = str(round(p["duration_sec"], 4))
        step_fields["target"] = (p.get("target") or "").strip()
        step_fields["zoom_persist"] = "true" if parse_step_persist(step) else "false"
        if bool(p.get("is_camera", True)) and p.get("val_explicit"):
            # 카메라 val 직접배율 — strength 필드는 비워 혼동 방지
            step_fields["val"] = str(round(float(p["val"]), 4))
            step_fields["zoom_strength"] = ""
        elif bool(p.get("is_camera", True)):
            step_fields["val"] = ""
            step_fields["zoom_strength"] = str(round(p["strength"], 4))
        else:
            # 엔티티: 직접 배율을 strength/val 양쪽에 표시
            mul = str(round(float(p["val"]), 4))
            step_fields["val"] = mul
            step_fields["zoom_strength"] = mul
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
    elif t == "FOLLOW_START":
        step_fields["follower"] = str(step.get("follower") or step.get("target") or "")
        step_fields["leader"] = str(step.get("leader") or step.get("follow") or "")
        d = step.get("dist")
        step_fields["dist"] = "" if d is None else str(d)
        sp = step.get("speed")
        step_fields["speed"] = "" if sp is None else str(sp)
        step_fields["persist"] = "true" if parse_step_persist(step, default=False) else ""
    elif t == "FOLLOW_STOP":
        step_fields["follower"] = str(step.get("follower") or step.get("target") or "")
        step_fields["persist"] = "true" if parse_step_persist(step, default=False) else ""


def _editor_optional_float(raw, default=None):
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


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
    if t == "3D_ROTATE":
        stub = {
            "on": step_fields.get("rotate3d_on"),
            "strength": step_fields.get("rotate3d_strength"),
            "duration_sec": step_fields.get("rotate3d_duration_sec"),
        }
        return _canonical_rotate3d_json(parse_rotate3d_step(stub))
    if t == "ZOOM":
        stub = {
            "on": step_fields.get("zoom_on"),
            "strength": step_fields.get("zoom_strength"),
            "duration_sec": step_fields.get("zoom_duration_sec"),
            "target": step_fields.get("target"),
        }
        val_f = step_fields.get("val")
        if val_f is not None and str(val_f).strip() != "":
            stub["val"] = val_f
        if parse_step_bool(step_fields.get("zoom_persist"), False):
            stub["persist"] = True
        return _canonical_zoom_json(parse_zoom_step(stub))
    if t == "FOLLOW_START":
        out = {"type": "FOLLOW_START"}
        fol = (step_fields.get("follower") or "").strip()
        if fol:
            out["follower"] = fol
        lea = (step_fields.get("leader") or "").strip()
        if lea:
            out["leader"] = lea
        d = _editor_optional_float(step_fields.get("dist"))
        if d is not None:
            out["dist"] = d
        sp = _editor_optional_float(step_fields.get("speed"))
        if sp is not None:
            out["speed"] = sp
        if parse_step_bool(step_fields.get("persist"), False):
            out["persist"] = True
        return out
    if t == "FOLLOW_STOP":
        out = {"type": "FOLLOW_STOP"}
        fol = (step_fields.get("follower") or "").strip()
        if fol:
            out["follower"] = fol
        if parse_step_bool(step_fields.get("persist"), False):
            out["persist"] = True
        return out
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


_APP_FORCE_QUIT_KEYS_CACHE = None


def _app_force_quit_key_sets():
    """CONFIG → (a_keys, x_keys, joy_combos)."""
    global _APP_FORCE_QUIT_KEYS_CACHE
    if _APP_FORCE_QUIT_KEYS_CACHE is not None:
        return _APP_FORCE_QUIT_KEYS_CACHE
    a_specs = CONFIG.get("APP_FORCE_QUIT_COMBO_KEYS_A") or ["a", "space", "return"]
    x_specs = CONFIG.get("APP_FORCE_QUIT_COMBO_KEYS_X") or ["x"]
    a_keys = set()
    x_keys = set()
    if isinstance(a_specs, (list, tuple)):
        for spec in a_specs:
            pk = _pygame_key_from_spec(spec)
            if pk is not None:
                a_keys.add(int(pk))
    if isinstance(x_specs, (list, tuple)):
        for spec in x_specs:
            pk = _pygame_key_from_spec(spec)
            if pk is not None:
                x_keys.add(int(pk))
    if not a_keys:
        a_keys.add(int(pygame.K_a))
    if not x_keys:
        x_keys.add(int(pygame.K_x))
    joy_combos = []
    raw_combos = CONFIG.get("APP_FORCE_QUIT_JOY_COMBOS")
    if isinstance(raw_combos, (list, tuple)):
        for row in raw_combos:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                try:
                    joy_combos.append((int(row[0]), int(row[1])))
                except (TypeError, ValueError):
                    pass
    if not joy_combos:
        raw_joy = CONFIG.get("APP_FORCE_QUIT_JOY_BUTTONS")
        if isinstance(raw_joy, (list, tuple)) and len(raw_joy) >= 2:
            try:
                joy_combos.append((int(raw_joy[0]), int(raw_joy[1])))
            except (TypeError, ValueError):
                pass
    if not joy_combos:
        joy_combos = [(0, 2), (1, 3), (0, 3)]
    _APP_FORCE_QUIT_KEYS_CACHE = (a_keys, x_keys, tuple(joy_combos))
    return _APP_FORCE_QUIT_KEYS_CACHE


class _AppForceQuitInput:
    """A+X 종료 — 이벤트 추적만(매 프레임 패드 폴링·부팅 시 joystick.init 금지)."""

    def __init__(self):
        self._held_keys: set = set()
        self._held_joy: set = set()  # (joy_id, button)
        self._joys: dict = {}
        self._combo_btns: set = set()

    def _combo_button_set(self):
        if self._combo_btns:
            return self._combo_btns
        _, _, joy_combos = _app_force_quit_key_sets()
        btns = set()
        for ba, bx in joy_combos:
            btns.add(int(ba))
            btns.add(int(bx))
        self._combo_btns = btns
        return btns

    def _ensure_joystick_module(self) -> None:
        if getattr(self, "_joy_module_ready", False):
            return
        self._joy_module_ready = True
        try:
            if not pygame.joystick.get_init():
                pygame.joystick.init()
            configure_pygame_input_event_filter()
        except Exception:
            pass

    def _ensure_joystick(self, joy_id: int) -> None:
        self._ensure_joystick_module()
        try:
            jid = int(joy_id)
        except (TypeError, ValueError):
            return
        j = self._joys.get(jid)
        if j is None:
            try:
                j = pygame.joystick.Joystick(jid)
                self._joys[jid] = j
            except Exception:
                return
        try:
            if not j.get_init():
                j.init()
        except Exception:
            pass

    def feed_event(self, event) -> None:
        if event is None:
            return
        try:
            if not bool(CONFIG.get("APP_FORCE_QUIT_COMBO_ENABLED", True)):
                return
        except Exception:
            return
        et = event.type
        try:
            if et == pygame.KEYDOWN:
                self._held_keys.add(int(event.key))
                try:
                    a_keys, x_keys, _ = _app_force_quit_key_sets()
                    if int(event.key) in a_keys or int(event.key) in x_keys:
                        self._ensure_joystick_module()
                except Exception:
                    pass
            elif et == pygame.KEYUP:
                self._held_keys.discard(int(event.key))
            elif et == pygame.JOYBUTTONDOWN:
                jid = int(event.joy)
                self._ensure_joystick(jid)
                self._held_joy.add((jid, int(event.button)))
            elif et == pygame.JOYBUTTONUP:
                self._held_joy.discard((int(event.joy), int(event.button)))
            elif et == pygame.JOYDEVICEADDED:
                jid = int(getattr(event, "device_index", 0))
                self._ensure_joystick(jid)
            elif et == pygame.JOYDEVICEREMOVED:
                jid = getattr(event, "instance_id", None)
                if jid is None:
                    jid = getattr(event, "device_index", None)
                if jid is not None:
                    jid = int(jid)
                    self._joys.pop(jid, None)
                    self._held_joy = {(j, b) for j, b in self._held_joy if j != jid}
        except Exception:
            pass

    def _keys_down(self, key_set, keys_pressed) -> bool:
        if not key_set:
            return False
        if keys_pressed is not None:
            try:
                if any(bool(keys_pressed[k]) for k in key_set):
                    return True
            except Exception:
                pass
        return any(k in self._held_keys for k in key_set)

    def a_held(self, keys_pressed=None) -> bool:
        a_keys, _, _ = _app_force_quit_key_sets()
        return self._keys_down(a_keys, keys_pressed)

    def has_combo_candidate(self, keys_pressed=None) -> bool:
        """A 또는 X(키·패드)가 하나라도 눌려 있을 때만 True — 매 프레임 종료 검사 생략."""
        try:
            if not bool(CONFIG.get("APP_FORCE_QUIT_COMBO_ENABLED", True)):
                return False
        except Exception:
            return False
        a_keys, x_keys, _ = _app_force_quit_key_sets()
        if self._keys_down(a_keys, keys_pressed) or self._keys_down(x_keys, keys_pressed):
            return True
        if not self._held_joy:
            return False
        combo_btns = self._combo_button_set()
        return any(int(b) in combo_btns for _, b in self._held_joy)

    def _joy_combo_from_events(self, joy_combos) -> bool:
        if not self._held_joy or not joy_combos:
            return False
        by_joy: dict = {}
        for jid, btn in self._held_joy:
            by_joy.setdefault(int(jid), set()).add(int(btn))
        for btns in by_joy.values():
            for ba, bx in joy_combos:
                if int(ba) in btns and int(bx) in btns:
                    return True
        return False

    def combo_pressed(self, keys_pressed=None) -> bool:
        try:
            if not bool(CONFIG.get("APP_FORCE_QUIT_COMBO_ENABLED", True)):
                return False
        except Exception:
            pass
        a_keys, x_keys, joy_combos = _app_force_quit_key_sets()
        if self._keys_down(a_keys, keys_pressed) and self._keys_down(x_keys, keys_pressed):
            return True
        return self._joy_combo_from_events(joy_combos)


_APP_FORCE_QUIT = _AppForceQuitInput()


def configure_pygame_input_event_filter() -> None:
    """조이스틱 축·hat 이벤트 폭주 차단(RG34XX 등에서 프레임 드랍 원인)."""
    try:
        pygame.event.set_blocked(
            [
                pygame.JOYAXISMOTION,
                pygame.JOYBALLMOTION,
                pygame.JOYHATMOTION,
            ]
        )
    except Exception:
        pass


def app_force_quit_feed_event(event) -> None:
    _APP_FORCE_QUIT.feed_event(event)


def app_force_quit_has_candidate(keys_pressed=None) -> bool:
    return _APP_FORCE_QUIT.has_combo_candidate(keys_pressed)


def app_force_quit_combo_a_held(keys_pressed=None) -> bool:
    return _APP_FORCE_QUIT.a_held(keys_pressed)


def app_force_quit_combo_pressed(keys_pressed=None) -> bool:
    """A+X(또는 설정 키·패드) 동시 입력 — 확인 없이 앱 종료용."""
    return _APP_FORCE_QUIT.combo_pressed(keys_pressed)


# =============================================================================
# 게임 종료 버튼 (OVERLAY_UI)
# events.json의 fishing_exit·낚시 그만두기와 동일한 EventManager 파이프라인 사용.
# - install_game_exit_button: 필드 진입 시 오른쪽 위 persist 버튼 등록
# - show/hide_game_exit_confirm: 확인 문구 + 응/아니 버튼
# - handle_overlay_ui_click_action: try_overlay_ui_click 반환값 일괄 처리
# =============================================================================

GAME_EXIT_BTN_ID = "game_exit_btn"
GAME_EXIT_CONFIRM_IDS = (
    "game_exit_confirm_msg",
    "game_exit_confirm_yes",
    "game_exit_confirm_no",
)


def _game_exit_overlay_enabled() -> bool:
    try:
        return bool(CONFIG.get("GAME_EXIT_OVERLAY_ENABLED", True))
    except Exception:
        return True


def _apply_overlay_ui_step_dict(ev_mgr, step: dict) -> None:
    """EventManager._apply_overlay_ui_step 래퍼 (OVERLAY_UI 스텝 dict 그대로 전달)."""
    fn = getattr(ev_mgr, "_apply_overlay_ui_step", None)
    if callable(fn):
        fn(step)


def _persist_overlay_ui_step(**fields) -> dict:
    """hold_forever persist OVERLAY_UI 공통 필드 (events.json OVERLAY_UI 스텝과 동일 키)."""
    step = {
        "type": "OVERLAY_UI",
        "action": "show",
        "persist": True,
        "hold_forever": True,
        "mode": "fade",
        "appear": 0.12,
        "disappear": 0.15,
    }
    step.update(fields)
    return step


def game_exit_confirm_open(ev_mgr) -> bool:
    """종료 확인창(문구 오버레이)이 떠 있는지."""
    try:
        for ov in list(getattr(ev_mgr, "_ui_overlays", None) or []):
            if ov.get("id") == GAME_EXIT_CONFIRM_IDS[0] and ov.get("phase") != "done":
                return True
    except Exception:
        pass
    return False


def install_game_exit_button(ev_mgr) -> None:
    """오른쪽 위 작은 exit 버튼 설치. ev_mgr.game_exit_button_visible 이 켜진 경우에만 표시."""
    if not _game_exit_overlay_enabled():
        return
    if not bool(getattr(ev_mgr, "game_exit_button_visible", False)):
        return
    _apply_overlay_ui_step_dict(
        ev_mgr,
        _persist_overlay_ui_step(
            content="button",
            text="exit",
            font="default",
            size=10,
            pad_x=6,
            pad_y=3,
            color="235,220,210",
            bg_color="48,42,42",
            overlay_id=GAME_EXIT_BTN_ID,
            anchor="top_right",
            margin_x=6,
            margin_y=6,
            clickable=True,
            click_action="game_exit_open",
        ),
    )


def hide_game_exit_button(ev_mgr) -> None:
    """오른쪽 위 exit 버튼과 확인창을 함께 제거."""
    rm = getattr(ev_mgr, "remove_ui_overlay", None)
    if callable(rm):
        try:
            rm(GAME_EXIT_BTN_ID)
        except Exception:
            pass
    hide_game_exit_confirm(ev_mgr)


def set_game_exit_button_visible(
    ev_mgr, visible: bool, *, persist: bool | None = None, with_debug: bool = True
) -> None:
    """이벤트 스텝에서 exit 버튼 표시 상태를 제어한다.
    with_debug=True(기본)면 debug 버튼도 같이 on/off (안드로이드 터치 디버그).
    """
    try:
        ev_mgr.game_exit_button_visible = bool(visible)
    except Exception:
        pass
    if persist is not None:
        try:
            ev_mgr._game_exit_button_persist = bool(persist)
        except Exception:
            pass
    if bool(visible):
        install_game_exit_button(ev_mgr)
    else:
        hide_game_exit_button(ev_mgr)
    if with_debug:
        set_game_debug_button_visible(ev_mgr, bool(visible), persist=persist)


def show_game_exit_confirm(ev_mgr) -> None:
    """'게임을 끝낼까요?' + 응/아니 (기존 OVERLAY_UI 버튼·텍스트 빌더 재사용)."""
    if not _game_exit_overlay_enabled():
        return
    _apply_overlay_ui_step_dict(
        ev_mgr,
        _persist_overlay_ui_step(
            content="text",
            text="게임을 끝낼까요?",
            font="default",
            size=13,
            color="245,245,250",
            overlay_id=GAME_EXIT_CONFIRM_IDS[0],
            anchor="center",
            margin_y=-22,
        ),
    )
    _apply_overlay_ui_step_dict(
        ev_mgr,
        _persist_overlay_ui_step(
            content="button",
            text="응",
            font="default",
            size=12,
            color="255,255,255",
            bg_color="52,110,72",
            overlay_id=GAME_EXIT_CONFIRM_IDS[1],
            anchor="center",
            margin_x=-36,
            margin_y=18,
            clickable=True,
            click_action="game_exit_yes",
        ),
    )
    _apply_overlay_ui_step_dict(
        ev_mgr,
        _persist_overlay_ui_step(
            content="button",
            text="아니",
            font="default",
            size=12,
            color="255,255,255",
            bg_color="90,58,58",
            overlay_id=GAME_EXIT_CONFIRM_IDS[2],
            anchor="center",
            margin_x=36,
            margin_y=18,
            clickable=True,
            click_action="game_exit_no",
        ),
    )


def hide_game_exit_confirm(ev_mgr) -> None:
    """종료 확인 오버레이 제거 (exit 버튼은 유지)."""
    rm = getattr(ev_mgr, "remove_ui_overlay", None)
    if not callable(rm):
        return
    for oid in GAME_EXIT_CONFIRM_IDS:
        try:
            rm(oid)
        except Exception:
            pass


# =============================================================================
# 디버그 버튼 + 설정 패널 (안드로이드 터치용 — 키보드 핫키 대체)
# - GAME_EXIT_BUTTON 과 함께 오른쪽 위에 "debug" 버튼
# - 누르면 주요 DEV_CMD / 이벤트 피커 on·off 패널
# =============================================================================

GAME_DEBUG_BTN_ID = "game_debug_btn"

_DEBUG_PANEL = {
    "open": False,
    "row_hit": [],
    "panel_rect": None,
    "close_rect": None,
    "confirm_restart": False,
}


def _debug_panel_rows() -> list:
    """디버그 패널 항목 — label / key 힌트 / kind(cmd|picker|restart)."""
    # 단축키 표기는 GLOBAL_EVENT_HOTKEYS·EVENT_PICKER 실제 매핑과 맞춤
    # (l=틸트, r=쉬어, z/x=줌 — CONFIG 의 zoom 키를 우선)
    zoom_key = "z"
    try:
        for row in CONFIG.get("GLOBAL_EVENT_HOTKEYS") or []:
            if str((row or {}).get("event_id") or "") == "ev_hotkey_zoom_cycle":
                zoom_key = str((row or {}).get("key") or "z").strip() or "z"
                break
    except Exception:
        pass
    return [
        {"id": "restart", "label": "초기화 (세이브 삭제)", "key": "d", "kind": "restart"},
        {"id": "events", "label": "이벤트 피커", "key": "e", "kind": "picker"},
        {"id": "overlay", "label": "HUD 오버레이", "key": "o", "kind": "cmd", "cmd": "toggle_show_overlay"},
        {"id": "rotate3d", "label": "3D_ROTATE", "key": "q", "kind": "cmd", "cmd": "toggle_3d_rotate"},
        {"id": "mask", "label": "이벤트존 마스크", "key": "m", "kind": "cmd", "cmd": "toggle_show_mask"},
        {"id": "shear", "label": "쉬어", "key": "r", "kind": "cmd", "cmd": "toggle_shear_debug"},
        {"id": "tilt", "label": "틸트", "key": "l", "kind": "cmd", "cmd": "toggle_tilt_demo"},
        {"id": "zoom", "label": "줌 순환", "key": zoom_key, "kind": "cmd", "cmd": "cycle_zoom_debug"},
    ]


def _debug_feature_on(row: dict) -> bool | None:
    """현재 on/off. 순환·피커·초기화는 None(상태 표시 없음)."""
    kind = str(row.get("kind") or "")
    if kind in ("restart",):
        return None
    if kind == "picker":
        try:
            return bool(event_picker_is_open())
        except Exception:
            return None
    cmd = str(row.get("cmd") or "").strip().lower()
    rt = FIELD_RUNTIME_UI
    if cmd == "toggle_show_overlay":
        return bool(getattr(rt, "show_overlay_text", False))
    if cmd == "toggle_3d_rotate":
        return bool(getattr(rt, "rotate3d_on", False)) or float(getattr(rt, "rotate3d_target", 0) or 0) > 0.02
    if cmd == "toggle_show_mask":
        return bool(getattr(rt, "show_mask", False))
    if cmd == "toggle_shear_debug":
        try:
            default_shear = bool(CONFIG.get("TILT_SHEAR_ENABLED", False))
        except Exception:
            default_shear = False
        if default_shear:
            return not bool(getattr(rt, "shear_suppressed", False))
        return bool(getattr(rt, "shear_debug_on", False))
    if cmd == "toggle_tilt_demo":
        return bool(getattr(rt, "tilt_bg_demo", False))
    if cmd == "cycle_zoom_debug":
        return None
    return None


def debug_panel_is_open() -> bool:
    return bool(_DEBUG_PANEL.get("open"))


def debug_panel_close() -> None:
    _DEBUG_PANEL["open"] = False
    _DEBUG_PANEL["row_hit"] = []
    _DEBUG_PANEL["panel_rect"] = None
    _DEBUG_PANEL["close_rect"] = None
    _DEBUG_PANEL["confirm_restart"] = False


def debug_panel_open() -> None:
    _DEBUG_PANEL["confirm_restart"] = False
    _DEBUG_PANEL["open"] = True


def debug_panel_toggle() -> bool:
    if debug_panel_is_open():
        debug_panel_close()
        return False
    debug_panel_open()
    return True


def install_game_debug_button(ev_mgr) -> None:
    """오른쪽 위 exit 아래 'debug' 버튼."""
    if not _game_exit_overlay_enabled():
        return
    if not bool(getattr(ev_mgr, "game_debug_button_visible", False)):
        return
    _apply_overlay_ui_step_dict(
        ev_mgr,
        _persist_overlay_ui_step(
            content="button",
            text="debug",
            font="default",
            size=10,
            pad_x=6,
            pad_y=3,
            color="210,230,255",
            bg_color="36,48,64",
            overlay_id=GAME_DEBUG_BTN_ID,
            anchor="top_right",
            margin_x=6,
            margin_y=28,
            clickable=True,
            click_action="game_debug_open",
        ),
    )


def hide_game_debug_button(ev_mgr) -> None:
    rm = getattr(ev_mgr, "remove_ui_overlay", None)
    if callable(rm):
        try:
            rm(GAME_DEBUG_BTN_ID)
        except Exception:
            pass
    debug_panel_close()


def set_game_debug_button_visible(ev_mgr, visible: bool, *, persist: bool | None = None) -> None:
    """GAME_DEBUG_BUTTON / GAME_EXIT_BUTTON 공통 — debug 버튼 표시."""
    try:
        ev_mgr.game_debug_button_visible = bool(visible)
    except Exception:
        pass
    if persist is not None:
        try:
            ev_mgr._game_debug_button_persist = bool(persist)
        except Exception:
            pass
    if bool(visible):
        install_game_debug_button(ev_mgr)
    else:
        hide_game_debug_button(ev_mgr)


def _debug_panel_layout(surf_w, surf_h):
    rows = _debug_panel_rows()
    row_h = 20
    pad = 8
    title_h = 22
    n = len(rows) + (1 if _DEBUG_PANEL.get("confirm_restart") else 0)
    panel_w = min(int(surf_w * 0.9), max(200, int(surf_w) - 16))
    list_h = max(row_h, n * row_h)
    panel_h = title_h + pad + list_h + pad + 14
    panel_h = min(panel_h, int(surf_h) - 12)
    px = max(4, (int(surf_w) - panel_w) // 2)
    py = max(4, (int(surf_h) - panel_h) // 2)
    panel = pygame.Rect(px, py, panel_w, panel_h)
    close_r = pygame.Rect(panel.right - 22, panel.top + 4, 18, 14)
    list_r = pygame.Rect(panel.left + pad, panel.top + title_h + 2, panel_w - pad * 2, panel_h - title_h - pad - 12)
    return panel, close_r, list_r, row_h


def draw_debug_panel(surf, *, font_title=None, font_row=None) -> None:
    """논리 해상도 surf 위 디버그 설정 패널."""
    if not debug_panel_is_open() or surf is None:
        return
    sw, sh = surf.get_width(), surf.get_height()
    panel, close_r, list_r, row_h = _debug_panel_layout(sw, sh)
    _DEBUG_PANEL["panel_rect"] = panel
    _DEBUG_PANEL["close_rect"] = close_r

    try:
        dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 150))
        surf.blit(dim, (0, 0))
    except Exception:
        pygame.draw.rect(surf, (0, 0, 0), surf.get_rect())

    pygame.draw.rect(surf, (28, 36, 48), panel, border_radius=6)
    pygame.draw.rect(surf, (100, 140, 180), panel, 1, border_radius=6)

    if font_title is None:
        try:
            font_title = pygame.font.SysFont("malgungothic", 12)
        except Exception:
            font_title = pygame.font.Font(None, 14)
    if font_row is None:
        font_row = font_title

    title = font_title.render("Debug", True, (220, 235, 255))
    surf.blit(title, (panel.left + 8, panel.top + 4))
    pygame.draw.rect(surf, (90, 50, 50), close_r, border_radius=3)
    xlbl = font_row.render("x", True, (255, 220, 220))
    surf.blit(xlbl, (close_r.centerx - xlbl.get_width() // 2, close_r.centery - xlbl.get_height() // 2))

    hits = []
    y = list_r.top
    rows = _debug_panel_rows()
    for row in rows:
        rr = pygame.Rect(list_r.left, y, list_r.width, row_h)
        on = _debug_feature_on(row)
        if on is True:
            pygame.draw.rect(surf, (40, 70, 55), rr, border_radius=3)
        elif on is False:
            pygame.draw.rect(surf, (40, 42, 48), rr, border_radius=3)
        else:
            pygame.draw.rect(surf, (38, 44, 56), rr, border_radius=3)
        key = str(row.get("key") or "")
        label = str(row.get("label") or "")
        if on is True:
            state = "ON"
            scolor = (140, 230, 160)
        elif on is False:
            state = "OFF"
            scolor = (160, 160, 170)
        else:
            state = "·"
            scolor = (180, 190, 210)
        left = f"[{key}] {label}"
        img = font_row.render(left, True, (230, 235, 245))
        max_w = rr.width - 36
        if img.get_width() > max_w:
            t = left
            while t and font_row.size(t + "…")[0] > max_w:
                t = t[:-1]
            img = font_row.render(t + "…", True, (230, 235, 245))
        surf.blit(img, (rr.left + 4, rr.top + max(0, (row_h - img.get_height()) // 2)))
        simg = font_row.render(state, True, scolor)
        surf.blit(simg, (rr.right - simg.get_width() - 4, rr.top + max(0, (row_h - simg.get_height()) // 2)))
        hits.append((rr, dict(row)))
        y += row_h

    if _DEBUG_PANEL.get("confirm_restart"):
        rr = pygame.Rect(list_r.left, y, list_r.width, row_h)
        pygame.draw.rect(surf, (90, 40, 40), rr, border_radius=3)
        img = font_row.render("세이브 삭제 후 재시작?  다시 탭", True, (255, 200, 190))
        surf.blit(img, (rr.left + 4, rr.top + max(0, (row_h - img.get_height()) // 2)))
        hits.append((rr, {"id": "restart_confirm", "kind": "restart_confirm"}))

    hint = font_row.render("탭=토글 · 바깥/× 닫기", True, (140, 150, 165))
    surf.blit(hint, (panel.left + 8, panel.bottom - 12))
    _DEBUG_PANEL["row_hit"] = hits


def debug_panel_handle(
    event,
    *,
    ev_mgr,
    cam=None,
    flow=None,
    map_id=None,
    player=None,
    event_data=None,
    logical_xy=None,
) -> str | None:
    """
    디버그 패널 입력.
    Returns: "consumed" | None
    """
    if not debug_panel_is_open():
        return None
    if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_e):
        # E 는 이벤트 피커와 겹칠 수 있어 패널만 닫음
        if event.key == pygame.K_ESCAPE:
            debug_panel_close()
            return "consumed"
    if event.type == pygame.MOUSEBUTTONDOWN and int(getattr(event, "button", 0) or 0) == 1:
        if logical_xy is not None:
            mx, my = int(logical_xy[0]), int(logical_xy[1])
        else:
            mx, my = int(event.pos[0]), int(event.pos[1])
        close_r = _DEBUG_PANEL.get("close_rect")
        panel = _DEBUG_PANEL.get("panel_rect")
        if close_r is not None and close_r.collidepoint(mx, my):
            debug_panel_close()
            return "consumed"
        for rr, row in list(_DEBUG_PANEL.get("row_hit") or []):
            if not rr.collidepoint(mx, my):
                continue
            kind = str(row.get("kind") or "")
            if kind == "restart_confirm" or (
                kind == "restart" and _DEBUG_PANEL.get("confirm_restart")
            ):
                _DEBUG_PANEL["confirm_restart"] = False
                apply_dev_runtime_command(
                    "restart_delete_save",
                    ev_mgr=ev_mgr,
                    cam=cam,
                    flow=flow,
                    map_id=map_id,
                    player=player,
                )
                return "consumed"
            if kind == "restart":
                _DEBUG_PANEL["confirm_restart"] = True
                return "consumed"
            if kind == "picker":
                debug_panel_close()
                try:
                    event_picker_open(event_data if event_data is not None else {})
                except Exception:
                    pass
                return "consumed"
            if kind == "cmd":
                cmd = str(row.get("cmd") or "").strip()
                if cmd:
                    apply_dev_runtime_command(
                        cmd,
                        ev_mgr=ev_mgr,
                        cam=cam,
                        flow=flow,
                        map_id=map_id,
                        player=player,
                    )
                _DEBUG_PANEL["confirm_restart"] = False
                return "consumed"
            return "consumed"
        if panel is not None and not panel.collidepoint(mx, my):
            debug_panel_close()
            return "consumed"
        return "consumed"
    if event.type in (
        pygame.MOUSEBUTTONDOWN,
        pygame.MOUSEBUTTONUP,
        pygame.MOUSEMOTION,
        pygame.MOUSEWHEEL,
    ):
        return "consumed"
    return None


# =============================================================================
# SELECTBOX: 이벤트 스텝 예/아니오 선택창
# - show_selectbox : 창 크기·이름·질문·예/아니오 글자 등 SELECTBOX 스텝 파라미터로 표시
# - hide_selectbox : 오버레이 제거
# - selectbox_open : 현재 선택창이 열려 있는지 확인
# 예/아니오 클릭 → handle_overlay_ui_click_action → ev_mgr.apply_selectbox_choice("yes"/"no")
# =============================================================================

SELECTBOX_IDS = (
    "selectbox_bg",     # 배경 패널 (배경색 박스)
    "selectbox_name",   # 창 이름(제목)
    "selectbox_msg",    # 질문 텍스트
    "selectbox_yes",    # 예 버튼
    "selectbox_no",     # 아니오 버튼
)


def selectbox_open(ev_mgr) -> bool:
    """SELECTBOX 창이 현재 열려 있는지.

    show_selectbox 는 name/msg/yes/no 를 띄운다(selectbox_bg 는 안 만들 수 있음).
    예전엔 SELECTBOX_IDS[0]==selectbox_bg 만 검사해서 항상 False → 클릭이 선택으로 안 이어짐.
    """
    try:
        if bool(getattr(ev_mgr, "_selectbox_is_selecting", False)):
            return True
        known = set(SELECTBOX_IDS) | {
            "selectbox_yes",
            "selectbox_no",
            "selectbox_msg",
            "selectbox_name",
        }
        for ov in list(getattr(ev_mgr, "_ui_overlays", None) or []):
            if ov.get("id") in known and ov.get("phase") != "done":
                return True
    except Exception:
        pass
    return False


def hide_selectbox(ev_mgr) -> None:
    """SELECTBOX 오버레이 전체 제거."""
    rm = getattr(ev_mgr, "remove_ui_overlay", None)
    if not callable(rm):
        return
    for oid in SELECTBOX_IDS:
        try:
            rm(oid)
        except Exception:
            pass


def show_selectbox(ev_mgr, step: dict) -> None:
    """SELECTBOX 스텝 파라미터로 예/아니오 창 표시.

    스텝 파라미터:
      name        : 창 상단 제목(선택, 비우면 표시 안 함)
      text / question : 질문 내용
      yes_text    : 예 버튼 글자 (기본 "예")
      no_text     : 아니오 버튼 글자 (기본 "아니오")
      text_size   : 질문 폰트 크기 (기본 12)
      name_size   : 이름 폰트 크기 (기본 12)
      btn_size    : 버튼 글자 크기 (기본 12)
      yes_color   : 예 버튼 배경색 "R,G,B" (기본 "52,110,72")
      no_color    : 아니오 버튼 배경색 "R,G,B" (기본 "90,58,58")
      margin_y    : 전체 수직 오프셋 (기본 0 → 화면 중앙)
    """
    # 기존 창이 있으면 먼저 제거
    hide_selectbox(ev_mgr)

    try:
        text_size   = int(step.get("text_size") or CONFIG.get("SELECTBOX_TEXT_SIZE", 12) or 12)
        name_size   = int(step.get("name_size") or CONFIG.get("SELECTBOX_NAME_SIZE", 12) or 12)
        btn_size    = int(step.get("btn_size")  or CONFIG.get("SELECTBOX_BTN_SIZE",  12) or 12)
        appear_sec  = float(step.get("appear") or 0.12)
        disapp_sec  = float(step.get("disappear") or 0.15)
        margin_y    = float(step.get("margin_y") or 0)
    except Exception:
        text_size, name_size, btn_size = 12, 12, 12
        appear_sec, disapp_sec, margin_y = 0.12, 0.15, 0.0

    question = str(step.get("text") or step.get("question") or "")
    name_text = str(step.get("name") or "").strip()
    yes_text  = str(step.get("yes_text")  or CONFIG.get("SELECTBOX_YES_TEXT",  "예"))
    no_text   = str(step.get("no_text")   or CONFIG.get("SELECTBOX_NO_TEXT",   "아니오"))
    yes_color = str(step.get("yes_color") or CONFIG.get("SELECTBOX_YES_COLOR", "52,110,72"))
    no_color  = str(step.get("no_color")  or CONFIG.get("SELECTBOX_NO_COLOR",  "90,58,58"))

    base_appear = dict(
        type="OVERLAY_UI", action="show",
        persist=True, hold_forever=True, mode="fade",
        appear=appear_sec, disappear=disapp_sec,
    )

    # ── 배경 패널 (반투명 검정, 화면 전체 가리지 않는 중앙 박스 역할)
    # 버튼들과 텍스트의 뒤에 깔리는 시각적 그룹핑 역할
    if name_text:
        # 이름이 있으면 이름 텍스트 먼저 표시 (질문 바로 위)
        name_step = dict(
            base_appear,
            content="text", text=name_text,
            font="default", size=name_size,
            color="230,230,230",
            overlay_id=SELECTBOX_IDS[1],
            anchor="center", margin_x=0, margin_y=margin_y - 30,
        )
        _apply_overlay_ui_step_dict(ev_mgr, name_step)

    # ── 질문 텍스트
    msg_step = dict(
        base_appear,
        content="text", text=question,
        font="default", size=text_size,
        color="245,245,250",
        overlay_id=SELECTBOX_IDS[2],
        anchor="center", margin_x=0, margin_y=margin_y - 10,
    )
    _apply_overlay_ui_step_dict(ev_mgr, msg_step)

    # ── 예 버튼 (왼쪽)
    yes_step = dict(
        base_appear,
        content="button", text=yes_text,
        font="default", size=btn_size,
        color="255,255,255", bg_color=yes_color,
        pad_x=14, pad_y=5,
        overlay_id=SELECTBOX_IDS[3],
        anchor="center", margin_x=-40, margin_y=margin_y + 20,
        clickable=True, click_action="selectbox_yes",
    )
    _apply_overlay_ui_step_dict(ev_mgr, yes_step)

    # ── 아니오 버튼 (오른쪽)
    no_step = dict(
        base_appear,
        content="button", text=no_text,
        font="default", size=btn_size,
        color="255,255,255", bg_color=no_color,
        pad_x=14, pad_y=5,
        overlay_id=SELECTBOX_IDS[4],
        anchor="center", margin_x=40, margin_y=margin_y + 20,
        clickable=True, click_action="selectbox_no",
    )
    _apply_overlay_ui_step_dict(ev_mgr, no_step)


# =============================================================================
# 이벤트 피커 (필드 E 키) — LOCAL/GLOBAL/SYNC/FRAGMENTS 목록 → 클릭/Enter 즉시 실행
# =============================================================================

_EVENT_PICKER = {
    "open": False,
    "scroll": 0,
    "selected": 0,
    "rows": [],  # [{id, section, title, label}]
    "row_hit": [],  # [(rect, index)] — draw 시 갱신
    "panel_rect": None,
    "close_rect": None,
    "list_rect": None,
}


def event_picker_is_open() -> bool:
    return bool(_EVENT_PICKER.get("open"))


def event_picker_close() -> None:
    _EVENT_PICKER["open"] = False
    _EVENT_PICKER["row_hit"] = []
    _EVENT_PICKER["panel_rect"] = None
    _EVENT_PICKER["close_rect"] = None
    _EVENT_PICKER["list_rect"] = None


def _event_picker_enabled() -> bool:
    try:
        return bool(CONFIG.get("EVENT_PICKER_HOTKEY_ENABLED", True))
    except Exception:
        return True


def event_picker_hotkey_code():
    """CONFIG EVENT_PICKER_HOTKEY → pygame key int (기본 K_e)."""
    pk = _pygame_key_from_spec(CONFIG.get("EVENT_PICKER_HOTKEY", "e"))
    return int(pk) if pk is not None else int(pygame.K_e)


def build_event_picker_rows(event_data) -> list:
    """events.json 섹션별 이벤트 목록 (표시용)."""
    rows = []
    if not isinstance(event_data, dict):
        return rows
    for section in ("LOCAL", "GLOBAL", "SYNC", "FRAGMENTS"):
        sec = event_data.get(section) or {}
        if not isinstance(sec, dict):
            continue
        for eid in sorted(sec.keys(), key=lambda s: str(s)):
            entry = sec.get(eid) or {}
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "").strip()
            label = f"[{section[0]}] {eid}"
            if title:
                label = f"{label} - {title}"
            rows.append(
                {
                    "id": str(eid),
                    "section": section,
                    "title": title,
                    "label": label,
                }
            )
    return rows


def event_picker_open(event_data) -> None:
    """목록을 새로 읽어 모달 오픈."""
    if not _event_picker_enabled():
        return
    rows = build_event_picker_rows(event_data)
    _EVENT_PICKER["rows"] = rows
    _EVENT_PICKER["scroll"] = 0
    _EVENT_PICKER["selected"] = 0 if rows else -1
    _EVENT_PICKER["open"] = True


def event_picker_toggle(event_data) -> bool:
    """토글. 열린 상태면 True."""
    if event_picker_is_open():
        event_picker_close()
        return False
    event_picker_open(event_data)
    return True


def _event_picker_layout(surf_w, surf_h):
    try:
        row_h = int(CONFIG.get("EVENT_PICKER_ROW_H", 18) or 18)
    except Exception:
        row_h = 18
    row_h = max(14, min(28, row_h))
    try:
        vis = int(CONFIG.get("EVENT_PICKER_VISIBLE_ROWS", 12) or 12)
    except Exception:
        vis = 12
    vis = max(4, min(20, vis))
    pad = 8
    title_h = 20
    panel_w = min(int(surf_w * 0.92), max(220, int(surf_w) - 16))
    list_h = vis * row_h
    panel_h = title_h + pad + list_h + pad + 16
    panel_h = min(panel_h, int(surf_h) - 12)
    list_h = max(row_h, panel_h - title_h - pad - 16)
    vis = max(1, list_h // row_h)
    px = max(4, (int(surf_w) - panel_w) // 2)
    py = max(4, (int(surf_h) - panel_h) // 2)
    panel = pygame.Rect(px, py, panel_w, panel_h)
    close_r = pygame.Rect(panel.right - 22, panel.top + 4, 18, 14)
    list_r = pygame.Rect(panel.left + pad, panel.top + title_h + 4, panel_w - pad * 2, list_h)
    return panel, close_r, list_r, row_h, vis


def _event_picker_clamp_scroll():
    rows = _EVENT_PICKER.get("rows") or []
    n = len(rows)
    vis = 1
    lr = _EVENT_PICKER.get("list_rect")
    rh = int(CONFIG.get("EVENT_PICKER_ROW_H", 18) or 18)
    if lr is not None:
        try:
            vis = max(1, int(lr.height) // max(1, rh))
        except Exception:
            vis = 12
    else:
        try:
            vis = int(CONFIG.get("EVENT_PICKER_VISIBLE_ROWS", 12) or 12)
        except Exception:
            vis = 12
    max_scroll = max(0, n - vis)
    sc = int(_EVENT_PICKER.get("scroll") or 0)
    sc = max(0, min(max_scroll, sc))
    _EVENT_PICKER["scroll"] = sc
    sel = int(_EVENT_PICKER.get("selected") or 0)
    if n <= 0:
        _EVENT_PICKER["selected"] = -1
    else:
        sel = max(0, min(n - 1, sel))
        _EVENT_PICKER["selected"] = sel
        # 선택이 보이도록 스크롤
        if sel < sc:
            _EVENT_PICKER["scroll"] = sel
        elif sel >= sc + vis:
            _EVENT_PICKER["scroll"] = sel - vis + 1
    return max_scroll, vis


def _event_picker_run_selected(
    ev_mgr,
    events_catalog,
    field_tilt_snapshot=None,
    call_catalog=None,
) -> bool:
    rows = _EVENT_PICKER.get("rows") or []
    sel = int(_EVENT_PICKER.get("selected") or -1)
    if sel < 0 or sel >= len(rows):
        return False
    eid = str(rows[sel].get("id") or "").strip()
    if not eid:
        return False
    from flow import start_system_event

    # 진행 중 이벤트 있으면 끊고 실행 (디버그 피커)
    if getattr(ev_mgr, "active_event", None):
        try:
            ev_mgr.end_event()
        except Exception:
            pass
    # FRAGMENTS 는 merge_event_catalog 에 없을 수 있음 → call catalog 폴백
    catalog = dict(events_catalog or {})
    if isinstance(call_catalog, dict):
        for k, v in call_catalog.items():
            if k not in catalog:
                catalog[k] = v
    ok = start_system_event(
        ev_mgr,
        catalog,
        eid,
        field_tilt_snapshot=field_tilt_snapshot,
    )
    if ok:
        event_picker_close()
        print(f"[EventPicker] start {eid}")
    else:
        print(f"[EventPicker] failed to start {eid}")
    return ok


def event_picker_handle(
    event,
    *,
    ev_mgr,
    events_catalog,
    event_data=None,
    logical_xy=None,
    field_tilt_snapshot=None,
    call_catalog=None,
) -> str | None:
    """
    피커 입력 처리.
    Returns:
      "consumed" — 입력 소비
      "started"  — 이벤트 시작함
      None       — 피커와 무관
    """
    if not _event_picker_enabled():
        return None

    # 토글 키 (닫혀 있어도 처리 — 호출부가 open 체크 없이도 E 전달 가능)
    if event.type == pygame.KEYDOWN and int(event.key) == event_picker_hotkey_code():
        if event_picker_is_open():
            event_picker_close()
        else:
            event_picker_open(event_data if event_data is not None else {})
        return "consumed"

    if not event_picker_is_open():
        return None

    if event.type == pygame.KEYDOWN:
        if event.key == pygame.K_ESCAPE:
            event_picker_close()
            return "consumed"
        if event.key in (pygame.K_UP, pygame.K_w):
            sel = int(_EVENT_PICKER.get("selected") or 0) - 1
            _EVENT_PICKER["selected"] = sel
            _event_picker_clamp_scroll()
            return "consumed"
        if event.key in (pygame.K_DOWN, pygame.K_s):
            sel = int(_EVENT_PICKER.get("selected") or 0) + 1
            _EVENT_PICKER["selected"] = sel
            _event_picker_clamp_scroll()
            return "consumed"
        if event.key in (pygame.K_PAGEUP,):
            _EVENT_PICKER["scroll"] = int(_EVENT_PICKER.get("scroll") or 0) - 5
            _event_picker_clamp_scroll()
            return "consumed"
        if event.key in (pygame.K_PAGEDOWN,):
            _EVENT_PICKER["scroll"] = int(_EVENT_PICKER.get("scroll") or 0) + 5
            _event_picker_clamp_scroll()
            return "consumed"
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_a, pygame.K_SPACE):
            if _event_picker_run_selected(
                ev_mgr, events_catalog, field_tilt_snapshot, call_catalog=call_catalog
            ):
                return "started"
            return "consumed"

    if event.type == pygame.MOUSEWHEEL:
        dy = int(getattr(event, "y", 0) or 0)
        if dy:
            _EVENT_PICKER["scroll"] = int(_EVENT_PICKER.get("scroll") or 0) - dy
            _event_picker_clamp_scroll()
        return "consumed"

    if event.type == pygame.MOUSEBUTTONDOWN:
        mx, my = None, None
        if logical_xy is not None and len(logical_xy) >= 2:
            mx, my = int(logical_xy[0]), int(logical_xy[1])
        else:
            try:
                mx, my = int(event.pos[0]), int(event.pos[1])
            except Exception:
                return "consumed"
        btn = int(getattr(event, "button", 1) or 1)
        if btn in (4, 5):  # 일부 환경 휠
            _EVENT_PICKER["scroll"] = int(_EVENT_PICKER.get("scroll") or 0) + (-1 if btn == 4 else 1)
            _event_picker_clamp_scroll()
            return "consumed"
        if btn != 1:
            return "consumed"
        cr = _EVENT_PICKER.get("close_rect")
        if cr is not None and cr.collidepoint(mx, my):
            event_picker_close()
            return "consumed"
        for rect, idx in list(_EVENT_PICKER.get("row_hit") or []):
            if rect.collidepoint(mx, my):
                _EVENT_PICKER["selected"] = int(idx)
                if _event_picker_run_selected(
                    ev_mgr, events_catalog, field_tilt_snapshot, call_catalog=call_catalog
                ):
                    return "started"
                return "consumed"
        pr = _EVENT_PICKER.get("panel_rect")
        if pr is not None and not pr.collidepoint(mx, my):
            event_picker_close()
            return "consumed"
        return "consumed"

    # 피커가 열려 있으면 그 외 입력도 필드로는 내려보내지 않음
    return "consumed"


def draw_event_picker(surf, *, font_title=None, font_row=None) -> None:
    """논리 해상도 surf 위에 이벤트 피커 모달 그리기."""
    if not event_picker_is_open() or surf is None:
        return
    sw, sh = surf.get_width(), surf.get_height()
    panel, close_r, list_r, row_h, vis = _event_picker_layout(sw, sh)
    _EVENT_PICKER["panel_rect"] = panel
    _EVENT_PICKER["close_rect"] = close_r
    _EVENT_PICKER["list_rect"] = list_r
    max_scroll, vis = _event_picker_clamp_scroll()
    rows = _EVENT_PICKER.get("rows") or []
    sc = int(_EVENT_PICKER.get("scroll") or 0)
    sel = int(_EVENT_PICKER.get("selected") or -1)

    # 딤
    try:
        dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        surf.blit(dim, (0, 0))
    except Exception:
        pygame.draw.rect(surf, (0, 0, 0), surf.get_rect())

    pygame.draw.rect(surf, (36, 34, 40), panel, border_radius=6)
    pygame.draw.rect(surf, (120, 110, 100), panel, 1, border_radius=6)

    if font_title is None:
        try:
            font_title = pygame.font.SysFont("malgungothic", 12)
        except Exception:
            font_title = pygame.font.Font(None, 14)
    if font_row is None:
        font_row = font_title

    title = font_title.render("Events (E/Esc 닫기)", True, (240, 230, 210))
    surf.blit(title, (panel.left + 8, panel.top + 4))
    pygame.draw.rect(surf, (90, 50, 50), close_r, border_radius=3)
    xlbl = font_row.render("x", True, (255, 220, 220))
    surf.blit(xlbl, (close_r.centerx - xlbl.get_width() // 2, close_r.centery - xlbl.get_height() // 2))

    # 리스트 클립
    prev_clip = surf.get_clip()
    surf.set_clip(list_r)
    hits = []
    y0 = list_r.top
    for i in range(sc, min(len(rows), sc + vis + 1)):
        row = rows[i]
        rr = pygame.Rect(list_r.left, y0 + (i - sc) * row_h, list_r.width, row_h)
        if i == sel:
            pygame.draw.rect(surf, (70, 90, 70), rr)
        elif i % 2 == 0:
            pygame.draw.rect(surf, (44, 42, 48), rr)
        else:
            pygame.draw.rect(surf, (40, 38, 44), rr)
        txt = str(row.get("label") or row.get("id") or "")
        # 너무 길면 자르기
        max_w = rr.width - 6
        img = font_row.render(txt, True, (230, 225, 215))
        if img.get_width() > max_w:
            # 대략 잘라 다시
            while txt and font_row.size(txt + "…")[0] > max_w:
                txt = txt[:-1]
            img = font_row.render(txt + "…", True, (230, 225, 215))
        surf.blit(img, (rr.left + 3, rr.top + max(0, (row_h - img.get_height()) // 2)))
        hits.append((rr, i))
    surf.set_clip(prev_clip)
    _EVENT_PICKER["row_hit"] = hits

    # 스크롤바
    if max_scroll > 0 and list_r.height > 8:
        track = pygame.Rect(list_r.right - 4, list_r.top, 3, list_r.height)
        pygame.draw.rect(surf, (60, 58, 64), track)
        thumb_h = max(10, int(list_r.height * vis / max(1, len(rows))))
        thumb_y = list_r.top + int((list_r.height - thumb_h) * (sc / max(1, max_scroll)))
        pygame.draw.rect(surf, (160, 150, 130), pygame.Rect(track.left, thumb_y, track.width, thumb_h))

    hint = font_row.render(f"{len(rows)} events  ↑↓/휠  Enter실행", True, (160, 155, 145))
    surf.blit(hint, (panel.left + 8, panel.bottom - 14))


def handle_overlay_ui_click_action(
    ov_act,
    *,
    ev_mgr,
    field_activities=None,
    cam=None,
):
    """try_overlay_ui_click 결과 처리 — 낚시 나가기·게임 종료 등 persist OVERLAY_UI.

    Returns:
        "quit"    — 메인 루프 종료
        "consumed" — 클릭 소비(필드 이동·이벤트 입력으로 내리지 않음)
        None      — 이 핸들러와 무관
    """
    act = (ov_act or "").strip()

    # --- SELECTBOX 선택창: 예/아니오 버튼 · 창 열린 동안 바깥 클릭 ---
    # act 가 selectbox_yes/no 이면 창 감지 실패해도 적용 (open 검사 버그 대비)
    if act in ("selectbox_yes", "selectbox_no") or selectbox_open(ev_mgr):
        choice_fn = getattr(ev_mgr, "apply_selectbox_choice", None)
        if callable(choice_fn):
            if act == "selectbox_yes":
                choice_fn("yes")
            else:
                # 아니오 버튼 또는 선택창 바깥 클릭 모두 "no" 처리
                choice_fn("no")
        return "consumed"

    # --- 종료 확인창 열림: 응/아니/바깥 클릭 ---
    if game_exit_confirm_open(ev_mgr):
        if act == "game_exit_yes":
            hide_game_exit_confirm(ev_mgr)
            return "quit"
        hide_game_exit_confirm(ev_mgr)
        return "consumed"

    if act == "game_exit_open":
        show_game_exit_confirm(ev_mgr)
        return "consumed"

    if act == "game_debug_open":
        debug_panel_toggle()
        return "consumed"

    if act == "stop_fishing":
        try:
            if field_activities is not None:
                field_activities.cancel()
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
        return "consumed"

    if act == "stop_baseball":
        try:
            if field_activities is not None:
                field_activities.cancel()
        except Exception:
            pass
        try:
            ev_mgr.remove_ui_overlay("baseball_exit")
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
        return "consumed"

    if act == "stop_racing":
        try:
            if field_activities is not None:
                field_activities.cancel()
        except Exception:
            pass
        try:
            ev_mgr.remove_ui_overlay("racing_exit")
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
        return "consumed"

    if act == "stop_lotus_cross":
        try:
            if field_activities is not None:
                field_activities.cancel()
        except Exception:
            pass
        try:
            ev_mgr.remove_ui_overlay("lotus_cross_exit")
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
        return "consumed"

    if act == "stop_bullfrog":
        try:
            if field_activities is not None:
                field_activities.cancel()
        except Exception:
            pass
        try:
            ev_mgr.remove_ui_overlay("bullfrog_exit")
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
        return "consumed"

    return None


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
    elif n == "toggle_3d_rotate":
        rt.rotate3d_on = not bool(getattr(rt, "rotate3d_on", False))
        try:
            d = float(CONFIG.get("ROTATE3D_DEFAULT_STRENGTH", 1.0) or 1.0)
        except Exception:
            d = 1.0
        d = max(0.0, min(1.0, float(d)))
        rt.rotate3d_target = float(d) if rt.rotate3d_on else 0.0
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
    elif n == "start_baseball":
        from activities import request_field_activity

        params = {"save_data": dict(flow.save_data) if flow else {}}
        if isinstance(step, dict):
            if step.get("map") or step.get("map_id"):
                params["map"] = step.get("map") or step.get("map_id")
            if step.get("mode"):
                params["mode"] = step.get("mode")
            if step.get("return_map"):
                params["return_map"] = step.get("return_map")
            if step.get("return_pos"):
                params["return_pos"] = step.get("return_pos")
        request_field_activity(ev_mgr, "baseball", **params)
    elif n == "stop_baseball":
        try:
            ev_mgr.field_activity_stop_request = True
        except Exception:
            pass
        try:
            ev_mgr.remove_ui_overlay("baseball_exit")
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
    elif n == "start_racing":
        from activities import request_field_activity

        params = {"save_data": flow.save_data if flow else {}, "flow": flow}
        if isinstance(step, dict):
            if step.get("map") or step.get("map_id"):
                params["map"] = step.get("map") or step.get("map_id")
            if step.get("return_map"):
                params["return_map"] = step.get("return_map")
            if step.get("return_pos"):
                params["return_pos"] = step.get("return_pos")
        request_field_activity(ev_mgr, "racing", **params)
    elif n == "stop_racing":
        try:
            ev_mgr.field_activity_stop_request = True
        except Exception:
            pass
        try:
            ev_mgr.remove_ui_overlay("racing_exit")
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
    elif n == "return_from_racing":
        target_map = ""
        target_pos = None
        try:
            sd = flow.save_data if flow else {}
            target_map = str(sd.pop("racing_exit_map", "") or "").strip()
            target_pos = sd.pop("racing_exit_pos", None)
        except Exception:
            target_map = ""
            target_pos = None
        if not target_map:
            target_map = "bg_jjangpu"
            target_pos = [850.0, 2310.0]
        if not (isinstance(target_pos, (list, tuple)) and len(target_pos) >= 2):
            target_pos = [850.0, 2310.0]
        try:
            ev_mgr.pending_map_change = {
                "map_id": target_map,
                "pos": [float(target_pos[0]), float(target_pos[1])],
            }
            if flow is not None:
                flow.save_data["current_map"] = target_map
                flow.save_data["player_pos"] = [
                    float(target_pos[0]),
                    float(target_pos[1]),
                ]
                try:
                    flow.save_game(
                        target_map,
                        [float(target_pos[0]), float(target_pos[1])],
                        ignore_event_guard=True,
                    )
                except Exception:
                    pass
        except Exception:
            pass
        try:
            ev_mgr.pending_camera_command = {
                "mode": "follow_player",
                "smooth": False,
            }
        except Exception:
            pass
    elif n == "return_from_baseball":
        target_map = ""
        target_pos = None
        try:
            sd = flow.save_data if flow else {}
            target_map = str(sd.pop("baseball_exit_map", "") or "").strip()
            target_pos = sd.pop("baseball_exit_pos", None)
        except Exception:
            target_map = ""
            target_pos = None
        if not target_map:
            try:
                bb = (flow.world_data or {}).get("bg_baseball1", {}).get("baseball", {})
                target_map = str(bb.get("exit_map") or "bg_jjangpu").strip()
                ep = bb.get("exit_pos")
                if isinstance(ep, (list, tuple)) and len(ep) >= 2:
                    target_pos = [float(ep[0]), float(ep[1])]
            except Exception:
                target_map = "bg_jjangpu"
                target_pos = [853.0, 2304.0]
        if not (isinstance(target_pos, (list, tuple)) and len(target_pos) >= 2):
            target_pos = [853.0, 2304.0]
        try:
            ev_mgr.pending_map_change = {
                "map_id": target_map,
                "pos": [float(target_pos[0]), float(target_pos[1])],
            }
            if flow is not None:
                flow.save_data["current_map"] = target_map
                flow.save_data["player_pos"] = [
                    float(target_pos[0]),
                    float(target_pos[1]),
                ]
                try:
                    flow.save_game(
                        target_map,
                        [float(target_pos[0]), float(target_pos[1])],
                        ignore_event_guard=True,
                    )
                except Exception:
                    pass
        except Exception:
            pass
        try:
            ev_mgr.pending_camera_command = {
                "mode": "follow_player",
                "smooth": False,
            }
        except Exception:
            pass
    elif n == "start_lotus_cross":
        from activities import request_field_activity

        params = {}
        if isinstance(step, dict):
            if step.get("map") or step.get("map_id"):
                params["map"] = step.get("map") or step.get("map_id")
            if step.get("from_side"):
                params["from_side"] = step.get("from_side")
        request_field_activity(ev_mgr, "lotus_cross", **params)
    elif n == "stop_lotus_cross":
        try:
            ev_mgr.field_activity_stop_request = True
        except Exception:
            pass
        try:
            ev_mgr.remove_ui_overlay("lotus_cross_exit")
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
    elif n == "start_bullfrog":
        from activities import request_field_activity

        params = {"save_data": dict(flow.save_data) if flow else {}}
        if isinstance(step, dict):
            if step.get("map") or step.get("map_id"):
                params["map"] = step.get("map") or step.get("map_id")
            if step.get("return_map"):
                params["return_map"] = step.get("return_map")
            if step.get("return_pos"):
                params["return_pos"] = step.get("return_pos")
        request_field_activity(ev_mgr, "bullfrog", **params)
    elif n == "stop_bullfrog":
        try:
            ev_mgr.field_activity_stop_request = True
        except Exception:
            pass
        try:
            ev_mgr.remove_ui_overlay("bullfrog_exit")
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
    elif n == "return_from_bullfrog":
        target_map = ""
        target_pos = None
        try:
            sd = flow.save_data if flow else {}
            target_map = str(sd.pop("bullfrog_exit_map", "") or "").strip()
            target_pos = sd.pop("bullfrog_exit_pos", None)
        except Exception:
            target_map = ""
            target_pos = None
        if not target_map:
            try:
                bf = (flow.world_data or {}).get("bg_pond01", {}).get("bullfrog", {})
                target_map = str(bf.get("exit_map") or "bg_jjangpu").strip()
                ep = bf.get("exit_pos")
                if isinstance(ep, (list, tuple)) and len(ep) >= 2:
                    target_pos = [float(ep[0]), float(ep[1])]
            except Exception:
                target_map = "bg_jjangpu"
                target_pos = [816.0, 2304.0]
        if not (isinstance(target_pos, (list, tuple)) and len(target_pos) >= 2):
            target_pos = [816.0, 2304.0]
        try:
            ev_mgr.pending_map_change = {
                "map_id": target_map,
                "pos": [float(target_pos[0]), float(target_pos[1])],
            }
            if flow is not None:
                flow.save_data["current_map"] = target_map
                flow.save_data["player_pos"] = [
                    float(target_pos[0]),
                    float(target_pos[1]),
                ]
                try:
                    flow.save_game(
                        target_map,
                        [float(target_pos[0]), float(target_pos[1])],
                        ignore_event_guard=True,
                    )
                except Exception:
                    pass
        except Exception:
            pass
        try:
            ev_mgr.pending_camera_command = {
                "mode": "follow_player",
                "smooth": False,
            }
        except Exception:
            pass
    elif n.startswith("start_activity_"):
        # 범용: start_activity_fishing, start_activity_bullfrog 등
        from activities import request_field_activity

        act_id = n[len("start_activity_") :].strip()
        params = {}
        if isinstance(step, dict):
            for k in ("pond", "pond_id", "win_flag", "map", "map_id", "mode", "return_map", "return_pos", "from_side"):
                if k in step and step.get(k) is not None:
                    params[k] = step.get(k)
        if act_id in ("baseball", "racing", "bullfrog"):
            params["save_data"] = dict(flow.save_data) if flow else {}
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
    # A 누른 채 X → 종료 조합. X 단독 핫키(줌 순환 등)가 먼저 먹지 않게
    try:
        _, x_keys, _ = _app_force_quit_key_sets()
        if int(pygame_key_int) in x_keys and app_force_quit_combo_a_held():
            return False
    except Exception:
        pass
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

    def _max_cloud_extent(self, scale_max, zoom, f_q=1.0):
        """가장 큰 구름 스프라이트의 월드(뷰) 크기 — 화면 밖 여백 계산용."""
        self._load_images()
        if not self._base_imgs:
            return 160.0
        try:
            zm = max(1e-6, float(zoom))
            sc = max(0.2, float(scale_max))
            fq = max(0.5, float(f_q))
        except Exception:
            zm, sc, fq = 1.0, 1.4, 1.0
        ext = 64.0
        for base in self._base_imgs:
            w0, h0 = base.get_size()
            ext = max(ext, float(w0) * sc * zm, float(h0) * sc * zm * fq)
        return ext

    def _spawn_margin_px(self, settings, scale_max, zoom, f_q=1.0):
        """구름이 화면 안에서 '뿅' 나타나지 않도록 하는 월드 여백."""
        try:
            base = float(CONFIG.get("CLOUD_SHADOW_SPAWN_MARGIN_PX", 96) or 96)
        except Exception:
            base = 96.0
        cell = self._cell_size(settings)
        return max(base, self._max_cloud_extent(scale_max, zoom, f_q) + cell * 0.35)

    def _spawn_at_cell(self, ix, iy, settings, map_w, map_h, speed, scale_min, scale_max, margin, age_sec=0.0):
        cell = self._cell_size(settings)
        jh = self._jitter_half(settings, cell)
        wx = (ix + 0.5) * cell + random.uniform(-jh, jh)
        wy = (iy + 0.5) * cell + random.uniform(-jh, jh)
        wx = max(-margin, min(float(map_w) + margin, wx))
        wy = max(-margin, min(float(map_h) + margin, wy))
        self._append_cloud(wx, wy, speed, scale_min, scale_max, age_sec=age_sec)

    def _collect_view_cells(self, view_rect, margin, cell):
        """현재 뷰(여백 포함)를 덮는 격자 셀 — 최초 켤 때 화면 채우기용."""
        if not view_rect or len(view_rect) < 4:
            return []
        vx0, vy0, vw, vh = float(view_rect[0]), float(view_rect[1]), float(view_rect[2]), float(view_rect[3])
        vx1, vy1 = vx0 + vw, vy0 + vh
        ix0 = int(math.floor((vx0 - margin) / cell - 0.5))
        ix1 = int(math.ceil((vx1 + margin) / cell - 0.5))
        iy0 = int(math.floor((vy0 - margin) / cell - 0.5))
        iy1 = int(math.ceil((vy1 + margin) / cell - 0.5))
        return [(ix, iy) for ix in range(ix0, ix1 + 1) for iy in range(iy0, iy1 + 1)]

    def _random_offscreen_spawn_xy(self, view_rect, margin, extent, cell):
        """바람이 불어오는 쪽 화면 밖 좌표 — 스트리밍 스폰용."""
        if not self._active_dir_vec or not view_rect or len(view_rect) < 4:
            return None, None
        vx0, vy0, vw, vh = float(view_rect[0]), float(view_rect[1]), float(view_rect[2]), float(view_rect[3])
        vx1, vy1 = vx0 + vw, vy0 + vh
        dx, dy = self._active_dir_vec
        pad = float(margin) + float(extent) * 1.2
        jitter = float(cell) * 0.5
        edges = []
        if dx > 0:
            edges.append("left")
        if dx < 0:
            edges.append("right")
        if dy > 0:
            edges.append("top")
        if dy < 0:
            edges.append("bottom")
        if not edges:
            return None, None
        edge = random.choice(edges)
        span_x = (vx1 - vx0) + pad * 0.5
        span_y = (vy1 - vy0) + pad * 0.5
        if edge == "left":
            wx = vx0 - pad - random.uniform(0.0, jitter)
            wy = vy0 + random.uniform(-pad * 0.2, span_y + pad * 0.2)
        elif edge == "right":
            wx = vx1 + pad + random.uniform(0.0, jitter)
            wy = vy0 + random.uniform(-pad * 0.2, span_y + pad * 0.2)
        elif edge == "top":
            wy = vy0 - pad - random.uniform(0.0, jitter)
            wx = vx0 + random.uniform(-pad * 0.2, span_x + pad * 0.2)
        else:
            wy = vy1 + pad + random.uniform(0.0, jitter)
            wx = vx0 + random.uniform(-pad * 0.2, span_x + pad * 0.2)
        return float(wx), float(wy)

    def _seed_on_enable(
        self, settings, map_w, map_h, speed, scale_min, scale_max, view_rect, margin, zoom, f_q=1.0
    ):
        """FX를 켠 직후 — 화면 안에 구름을 뿌려 자연스럽게 시작."""
        cell = self._cell_size(settings)
        cells = self._collect_view_cells(view_rect, margin * 0.35, cell)
        if not cells:
            return
        cap = self._grid_max_clouds(settings)
        target = min(cap, max(12, int(len(cells) * 0.55)))
        target = min(target, len(cells))
        chosen = random.sample(cells, target)
        spd = max(1.0, float(speed))
        for ix, iy in chosen:
            max_age = (cell / spd) * random.uniform(0.15, 1.8)
            self._spawn_at_cell(
                ix,
                iy,
                settings,
                map_w,
                map_h,
                speed,
                scale_min,
                scale_max,
                margin,
                age_sec=max_age,
            )

    def _spawn_streaming_cloud(
        self, settings, map_w, map_h, speed, scale_min, scale_max, view_rect, margin, zoom, f_q=1.0
    ):
        """주기 스폰 — 항상 화면 밖(바람 상류)에서 유입."""
        if not self._active_dir_vec or not view_rect or len(view_rect) < 4:
            return
        cell = self._cell_size(settings)
        extent = self._max_cloud_extent(scale_max, zoom, f_q)
        pos = self._random_offscreen_spawn_xy(view_rect, margin, extent, cell)
        if pos[0] is None:
            return
        wx, wy = pos
        wx = max(-margin, min(float(map_w) + margin, wx))
        wy = max(-margin, min(float(map_h) + margin, wy))
        self._append_cloud(wx, wy, speed, scale_min, scale_max, age_sec=0.0)

    def update_and_draw_world(
        self,
        screen,
        dt_sec,
        settings,
        cam_x,
        cam_y,
        zoom,
        y_transform=None,
        x_offset_fn=None,
        f_q=1.0,
        map_size=None,
        mode7_ctx=None,
    ):
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
        just_enabled = False
        if not self._last_enabled:
            self._clouds.clear()
            self._spawn_acc = 0.0
            self._render_cache.clear()
            self._active_dir_setting = dir_setting
            self._active_dir_vec = self._pick_dir_once(dir_setting)
            just_enabled = True
        elif self._active_dir_setting != dir_setting:
            self._clouds.clear()
            self._spawn_acc = 0.0
            self._render_cache.clear()
            self._active_dir_setting = dir_setting
            self._active_dir_vec = self._pick_dir_once(dir_setting)
            just_enabled = True

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
        spawn_margin = self._spawn_margin_px(settings, scale_max, zoom, f_q)

        if just_enabled:
            self._seed_on_enable(
                settings, map_w, map_h, speed, scale_min, scale_max, view_rect, spawn_margin, zoom, f_q
            )

        self._spawn_acc += freq * max(0.0, float(dt_sec))
        while self._spawn_acc >= 1.0:
            self._spawn_acc -= 1.0
            self._spawn_streaming_cloud(
                settings, map_w, map_h, speed, scale_min, scale_max, view_rect, spawn_margin, zoom, f_q
            )

        dt = max(0.0, float(dt_sec))
        keep = []
        cull_margin = spawn_margin
        for c in self._clouds:
            c["wx"] += c["vx"] * dt
            c["wy"] += c["vy"] * dt
            wx, wy = float(c["wx"]), float(c["wy"])
            if wx < -cull_margin or wx > map_w + cull_margin or wy < -cull_margin or wy > map_h + cull_margin:
                continue
            keep.append(c)
            soft = settings.get("soften", 0.0)
            # Mode7: 구름도 지면 투영 (평평한 맵 그림자 FX)
            if mode7_ctx:
                try:
                    from engine import rotate3d_mode7_bounds_visible, rotate3d_mode7_project

                    pr = rotate3d_mode7_project(wx, wy, mode7_ctx, height_off=0.0, zoom=float(zoom))
                    if not pr or not pr.get("valid", pr.get("visible")):
                        continue
                    sx = float(pr["sx"])
                    sy = float(pr["sy"])
                    depth_sc = max(0.08, min(4.0, float(pr.get("scale", 1.0) or 1.0)))
                    surf = self._cache_get_render(
                        c["img_i"], c["scale"] * depth_sc, zoom, f_q, alpha, soften=soft
                    )
                    # 앵커를 대략 구름 이미지 중심으로 — 크기 확정 후 bounds cull
                    if not rotate3d_mode7_bounds_visible(
                        sx,
                        sy,
                        surf.get_width(),
                        surf.get_height(),
                        mode7_ctx,
                        anchor="center",
                    ):
                        continue
                    screen.blit(
                        surf,
                        (
                            int(round(sx - surf.get_width() * 0.5)),
                            int(round(sy - surf.get_height() * 0.5)),
                        ),
                    )
                    continue
                except Exception:
                    pass
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
            surf = self._cache_get_render(c["img_i"], c["scale"], zoom, f_q, alpha, soften=soft)
            screen.blit(surf, (int(round(sx)), int(round(sy))))
        self._clouds = keep


# ---------------------------------------------------------------------------
# 맵 ambient 물결 타일
# - 프레임 Surface 는 1세트만 로드·공유 (_load_anim_dir_cached)
# - 타일마다 엔티티/상태를 두지 않음 (전역 t + 격자 인덱스만)
# - 카메라 뷰에 겹치는 칸만 blit
# - world_data[map].field.wave_tiles 로 ON (apply_map_field_defaults → configure)
# - polygons: 꼭짓점만 저장 → configure 시 타일 마스크로 1회 bake (마스크 파일 없음)
# ---------------------------------------------------------------------------


class WaveTileAmbient:
    """필드 물결 ambient — 공유 애니 프레임을 격자 반복 blit."""

    __slots__ = (
        "enabled",
        "_frames",
        "_fx_dir",
        "_t",
        "_fps",
        "_scale",
        "_alpha",
        "_phase_stagger",
        "_fill_map",
        "_rects",
        "_polygons",
        "_poly_mask",
        "_step_x",
        "_step_y",
        "_tile_w0",
        "_tile_h0",
        "_render_cache",
    )

    def __init__(self):
        self.enabled = False
        self._frames = []
        self._fx_dir = ""
        self._t = 0.0
        self._fps = 8.0
        self._scale = 1.0
        self._alpha = 220
        self._phase_stagger = True
        self._fill_map = False
        self._rects = []
        self._polygons = []  # list[list[(x,y), ...]]
        self._poly_mask = set()  # {(col, row)} 월드 격자, configure 시 bake
        self._step_x = 0.0
        self._step_y = 0.0
        self._tile_w0 = 0
        self._tile_h0 = 0
        self._render_cache = OrderedDict()

    @staticmethod
    def _parse_on(block) -> bool:
        if not isinstance(block, dict):
            return False
        if "on" in block:
            v = block.get("on")
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "t", "yes", "y", "on")
            return bool(v)
        # on 생략 + 영역 키가 있으면 ON
        if block.get("fill_map") or block.get("rects") or block.get("polygons") or block.get("polygon"):
            return True
        return False

    @staticmethod
    def _parse_rects(raw) -> list:
        out = []
        if not isinstance(raw, (list, tuple)):
            return out
        for it in raw:
            if not isinstance(it, (list, tuple)) or len(it) < 4:
                continue
            try:
                x, y, w, h = float(it[0]), float(it[1]), float(it[2]), float(it[3])
            except (TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            out.append((x, y, w, h))
        return out

    @staticmethod
    def _is_xy_point(p) -> bool:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return False
        if isinstance(p[0], (list, tuple)):
            return False
        try:
            float(p[0])
            float(p[1])
            return True
        except (TypeError, ValueError):
            return False

    @classmethod
    def _normalize_polygon(cls, raw) -> list:
        """[[x,y], ...] → [(x,y), ...] (꼭짓점 3개 이상)."""
        if not isinstance(raw, (list, tuple)):
            return []
        pts = []
        for p in raw:
            if not cls._is_xy_point(p):
                continue
            try:
                pts.append((float(p[0]), float(p[1])))
            except (TypeError, ValueError):
                continue
        if len(pts) < 3:
            return []
        # 닫힌 링의 중복 끝점 제거
        if pts[0][0] == pts[-1][0] and pts[0][1] == pts[-1][1]:
            pts = pts[:-1]
        return pts if len(pts) >= 3 else []

    @classmethod
    def _parse_polygons(cls, raw) -> list:
        """polygons / polygon 값 파싱.
        - 한 개: [[x,y],[x,y],...]
        - 여러 개: [ [[x,y],...], [[x,y],...] ]
        """
        out = []
        if not isinstance(raw, (list, tuple)) or not raw:
            return out
        if cls._is_xy_point(raw[0]):
            poly = cls._normalize_polygon(raw)
            if poly:
                out.append(poly)
            return out
        for item in raw:
            poly = cls._normalize_polygon(item)
            if poly:
                out.append(poly)
        return out

    @staticmethod
    def _point_in_polygon(x: float, y: float, poly) -> bool:
        """홀수-짝수 규칙 (경계 근처는 포함에 가깝게)."""
        n = len(poly)
        if n < 3:
            return False
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if (yi > y) != (yj > y):
                denom = yj - yi
                if abs(denom) > 1e-12 and x < (xj - xi) * (y - yi) / denom + xi:
                    inside = not inside
            j = i
        return inside

    def configure(self, cfg) -> None:
        """맵 field.wave_tiles 적용. None/빈 dict → OFF.
        polygons 는 이 시점에 타일 마스크로 bake (디스크 마스크 파일 없음).
        """
        self._t = 0.0
        self._render_cache.clear()
        self._polygons = []
        self._poly_mask = set()
        if not isinstance(cfg, dict) or not cfg:
            self.enabled = False
            self._frames = []
            self._fx_dir = ""
            self._rects = []
            self._fill_map = False
            return
        if not self._parse_on(cfg):
            self.enabled = False
            self._frames = []
            return

        fx_dir = str(cfg.get("fx_dir") or cfg.get("dir") or "").strip()
        fx_name = str(cfg.get("fx") or cfg.get("wave_fx") or "").strip()
        if not fx_dir and fx_name:
            fx_dir = f"assets/images/fx/{fx_name}"
        if not fx_dir:
            fx_dir = str(CONFIG.get("FIELD_WAVE_TILES_FX_DIR") or "assets/images/fx/wave01").strip()

        try:
            fps = float(cfg.get("fps", CONFIG.get("FIELD_WAVE_TILES_FPS", 8.0)))
        except (TypeError, ValueError):
            fps = 8.0
        self._fps = max(0.5, min(60.0, fps))

        try:
            sc = float(cfg.get("scale", CONFIG.get("FIELD_WAVE_TILES_SCALE", 1.0)))
        except (TypeError, ValueError):
            sc = 1.0
        self._scale = max(0.1, min(4.0, sc))

        try:
            a = int(cfg.get("alpha", CONFIG.get("FIELD_WAVE_TILES_ALPHA", 220)))
        except (TypeError, ValueError):
            a = 220
        self._alpha = max(0, min(255, a))

        if "phase_stagger" in cfg:
            v = cfg.get("phase_stagger")
            if isinstance(v, str):
                self._phase_stagger = v.strip().lower() in ("1", "true", "t", "yes", "y", "on")
            else:
                self._phase_stagger = bool(v)
        else:
            self._phase_stagger = bool(CONFIG.get("FIELD_WAVE_TILES_PHASE_STAGGER", True))

        fill = cfg.get("fill_map")
        if isinstance(fill, str):
            self._fill_map = fill.strip().lower() in ("1", "true", "t", "yes", "y", "on")
        else:
            self._fill_map = bool(fill) if fill is not None else False
        self._rects = self._parse_rects(cfg.get("rects"))
        polys = self._parse_polygons(cfg.get("polygons"))
        if not polys:
            polys = self._parse_polygons(cfg.get("polygon"))
        self._polygons = polys

        # 명시 step (월드 px). 0이면 스케일된 프레임 크기 사용
        try:
            self._step_x = float(cfg.get("step_x") or cfg.get("tile_w") or 0) or 0.0
        except (TypeError, ValueError):
            self._step_x = 0.0
        try:
            self._step_y = float(cfg.get("step_y") or cfg.get("tile_h") or 0) or 0.0
        except (TypeError, ValueError):
            self._step_y = 0.0

        self._ensure_frames(fx_dir)
        self._rebuild_poly_mask()
        self.enabled = bool(self._frames) and (
            self._fill_map or bool(self._rects) or bool(self._poly_mask)
        )

    def _rebuild_poly_mask(self) -> None:
        """polygons → (col,row) 집합.

        타일 중심만 쓰면 타일보다 얇은 다각형이 전부 누락되므로
        중심·모서리·변 중점 + 다각형 꼭짓점이 타일 안에 있는지도 본다.
        (디스크 마스크 파일 없음 — configure 시 1회 bake)
        """
        self._poly_mask = set()
        if not self._polygons or not self._frames:
            return
        step_x, step_y, _tw, _th = self._scaled_step()

        def _tile_hits(col: int, row: int, poly) -> bool:
            wx = col * step_x
            wy = row * step_y
            samples = (
                (wx + step_x * 0.5, wy + step_y * 0.5),
                (wx, wy),
                (wx + step_x, wy),
                (wx, wy + step_y),
                (wx + step_x, wy + step_y),
                (wx + step_x * 0.5, wy),
                (wx + step_x * 0.5, wy + step_y),
                (wx, wy + step_y * 0.5),
                (wx + step_x, wy + step_y * 0.5),
            )
            for sx, sy in samples:
                if self._point_in_polygon(sx, sy, poly):
                    return True
            # 다각형 꼭짓점이 이 타일 안에 있으면 포함
            for px, py in poly:
                if wx <= px <= wx + step_x and wy <= py <= wy + step_y:
                    return True
            return False

        for poly in self._polygons:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            minx, maxx = min(xs), max(xs)
            miny, maxy = min(ys), max(ys)
            col0 = int(math.floor(minx / step_x))
            col1 = int(math.floor(maxx / step_x))
            row0 = int(math.floor(miny / step_y))
            row1 = int(math.floor(maxy / step_y))
            for row in range(row0 - 1, row1 + 2):
                for col in range(col0 - 1, col1 + 2):
                    if _tile_hits(col, row, poly):
                        self._poly_mask.add((col, row))

    def _ensure_frames(self, fx_dir: str) -> None:
        d = os.path.normpath(str(fx_dir or "").strip())
        if not d:
            self._frames = []
            self._fx_dir = ""
            return
        if d == self._fx_dir and self._frames:
            return
        self._fx_dir = d
        self._frames = []
        self._tile_w0 = 0
        self._tile_h0 = 0
        try:
            from engine import _load_anim_dir_cached

            loaded = _load_anim_dir_cached(d)
            if loaded:
                self._frames = list(loaded)
                tw, th = self._frames[0].get_size()
                self._tile_w0 = int(tw)
                self._tile_h0 = int(th)
        except Exception:
            self._frames = []

    def _scaled_step(self):
        tw = max(1.0, float(self._tile_w0) * float(self._scale))
        th = max(1.0, float(self._tile_h0) * float(self._scale))
        sx = float(self._step_x) if self._step_x > 0 else tw
        sy = float(self._step_y) if self._step_y > 0 else th
        return max(4.0, sx), max(4.0, sy), tw, th

    def _cache_frame(self, frame_ix: int, zoom: float, f_q: float, alpha: int):
        qz = round(float(zoom) * float(self._scale), 3)
        qfq = round(float(f_q), 3)
        a = int(max(0, min(255, alpha)))
        key = (int(frame_ix), qz, qfq, a)
        hit = self._render_cache.get(key)
        if hit is not None:
            try:
                self._render_cache.move_to_end(key)
            except Exception:
                pass
            return hit
        base = self._frames[int(frame_ix) % len(self._frames)]
        w0, h0 = base.get_size()
        w = max(2, int(round(w0 * qz)))
        h = max(2, int(round(h0 * qz * qfq)))
        if (w, h) == (w0, h0) and a >= 255:
            surf = base
        else:
            surf = pygame.transform.scale(base, (w, h))
            if a < 255:
                if surf is base:
                    surf = base.copy()
                surf.fill((255, 255, 255, a), special_flags=pygame.BLEND_RGBA_MULT)
        self._render_cache[key] = surf
        try:
            self._render_cache.move_to_end(key)
        except Exception:
            pass
        while len(self._render_cache) > 64:
            try:
                self._render_cache.popitem(last=False)
            except Exception:
                break
        return surf

    def _iter_regions(self, map_w: float, map_h: float):
        if self._fill_map and map_w > 0 and map_h > 0:
            yield (0.0, 0.0, float(map_w), float(map_h))
        for r in self._rects:
            yield r

    def _blit_one_tile(
        self,
        screen,
        *,
        wx,
        wy,
        col,
        row,
        cam_origin_x,
        cam_origin_y,
        z,
        base_ix,
        n_fr,
        alpha,
        fq,
        y_transform,
        x_offset_fn,
    ):
        if self._phase_stagger:
            fix = (base_ix + col + row) % n_fr
        else:
            fix = base_ix
        surf = self._cache_frame(fix, z, fq, alpha)
        sx = (wx - float(cam_origin_x)) * z
        sy = (wy - float(cam_origin_y)) * z
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
        screen.blit(surf, (int(round(sx)), int(round(sy))))

    def update_and_draw(
        self,
        screen,
        dt_sec: float,
        *,
        cam_origin_x: float,
        cam_origin_y: float,
        zoom: float,
        map_size=None,
        y_transform=None,
        x_offset_fn=None,
        f_q: float = 1.0,
        mode7_ctx=None,
    ) -> None:
        """배경 위 · 캐릭터 아래. Mode7 활성 시에는 스킵(원근 샘플과 좌표계가 다름)."""
        if not self.enabled or not self._frames:
            return
        if mode7_ctx is not None:
            return
        try:
            self._t += max(0.0, float(dt_sec or 0.0))
        except Exception:
            pass

        try:
            mw = float(map_size[0]) if map_size else 0.0
            mh = float(map_size[1]) if map_size else 0.0
        except Exception:
            mw, mh = 0.0, 0.0

        step_x, step_y, tile_w, tile_h = self._scaled_step()
        z = max(1e-6, float(zoom or 1.0))
        try:
            view_w = float(screen.get_width())
            view_h = float(screen.get_height())
        except Exception:
            return
        # 카메라가 보는 월드 영역 (+ 타일 1칸 여유)
        vx0 = float(cam_origin_x) - step_x
        vy0 = float(cam_origin_y) - step_y
        vx1 = float(cam_origin_x) + view_w / z + step_x
        vy1 = float(cam_origin_y) + view_h / z + step_y

        n_fr = len(self._frames)
        base_ix = int(self._t * self._fps) % n_fr
        alpha = self._alpha
        fq = float(f_q) if f_q is not None else 1.0
        if fq <= 0:
            fq = 1.0

        blit_kw = dict(
            cam_origin_x=cam_origin_x,
            cam_origin_y=cam_origin_y,
            z=z,
            base_ix=base_ix,
            n_fr=n_fr,
            alpha=alpha,
            fq=fq,
            y_transform=y_transform,
            x_offset_fn=x_offset_fn,
        )

        # 1) fill_map / rects — 영역 격자
        for rx, ry, rw, rh in self._iter_regions(mw, mh):
            x0 = max(rx, vx0)
            y0 = max(ry, vy0)
            x1 = min(rx + rw, vx1)
            y1 = min(ry + rh, vy1)
            if x1 <= x0 or y1 <= y0:
                continue
            col0 = int(math.floor((x0 - rx) / step_x))
            row0 = int(math.floor((y0 - ry) / step_y))
            col1 = int(math.floor((x1 - rx) / step_x))
            row1 = int(math.floor((y1 - ry) / step_y))
            for row in range(row0, row1 + 1):
                wy = ry + row * step_y
                if wy + tile_h < y0 or wy > y1:
                    continue
                for col in range(col0, col1 + 1):
                    wx = rx + col * step_x
                    if wx + tile_w < x0 or wx > x1:
                        continue
                    self._blit_one_tile(screen, wx=wx, wy=wy, col=col, row=row, **blit_kw)

        # 2) polygons — bake 된 마스크 (월드 격자 col/row)
        if self._poly_mask:
            col0 = int(math.floor(vx0 / step_x))
            row0 = int(math.floor(vy0 / step_y))
            col1 = int(math.floor(vx1 / step_x))
            row1 = int(math.floor(vy1 / step_y))
            for row in range(row0, row1 + 1):
                wy = row * step_y
                if wy + tile_h < vy0 or wy > vy1:
                    continue
                for col in range(col0, col1 + 1):
                    if (col, row) not in self._poly_mask:
                        continue
                    wx = col * step_x
                    if wx + tile_w < vx0 or wx > vx1:
                        continue
                    self._blit_one_tile(screen, wx=wx, wy=wy, col=col, row=row, **blit_kw)

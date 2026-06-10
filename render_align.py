"""
에디터 / 런타임 공통: 배경 blit 정수 앵커와 스프라이트 정렬.

SDL/pygame은 blit 위치가 정수 픽셀이므로 '발(격자) → 화면'은 한 번만 반올림한 뒤,
가로 배치 규칙을 고정한다.

1) 배경 원점(맵 로컬 또는 화면): bg = int(round((0 - cam_wx) * z + origin_x)), y도 동일.
   런타임 전체화면은 origin_x = origin_y = 0.
   에디터 맵 서피스는 origin_x = map_area_w/2, origin_y = (map 높이)/2.

2) 발(월드 wx, wy, 높이 h)의 화면 float: foot_fx = bg_x + wx*z, foot_fy = bg_y + wy*z - h*z

3) 발이 놓일 **정수 픽셀** (배경 격자·타일과 동기): foot_px_x = int(round(foot_fx)), foot_px_y = int(round(foot_fy))

4) 바닥-중앙 앵커(캐릭터·필드 오브젝트) top-left:
   ideal_left = foot_px_x - img_w/2 (float). 짝수 폭: left = round(ideal_left). 홀수 폭: 가로 중심이
   항상 0.5px 경계이므로 배경과 재현 가능하게 한쪽으로만 붙임 — left = floor(ideal_left)(왼쪽으로 0.5px 당김).
   top = foot_px_y - img_h (그대로).

5) 화면 정수 '중심' 앵커(그림자·이펙트 등): cx,cy = int(round(·)) 후 ideal = c - size/2, 홀수 size는 floor(ideal).

역변환(맵 로컬 픽셀 → 월드): wx = (mx_local - bg_x) / z, wy = (my_local - bg_y) / z

6) 줌: 게임은 '낮은 해상도 화면 전체를 마지막에 2배'가 아니라, 배경·마스크·각 스프라이트를
   각각 pygame.transform.scale(원본, (int(w*z), int(h*z))) 로 스케일한다. 그래서 z가 정수가 아니면
   int(w*z)가 배경과 캐릭터에서 미세하게 달라질 수 있다. 정수 배에 가깝면 snap_render_zoom으로 z를 정수로 맞춘다.
"""

import math

_EPS = 1e-6


def snap_render_zoom(z: float, eps=None) -> float:
    """2.0·1.0처럼 정수 배율에 충분히 가까우면 그 정수로 스냅(배경/오브젝트 scale 크기 일치)."""
    try:
        z = float(z)
    except (TypeError, ValueError):
        return 1.0
    if z <= 0:
        return 1.0
    if eps is None:
        try:
            from data import CONFIG

            eps = float(CONFIG.get("RENDER_INTEGER_ZOOM_EPS", 0.004))
        except Exception:
            eps = 0.004
    zn = round(z)
    if abs(z - zn) <= float(eps) + 1e-9:
        zi = int(zn)
        return float(zi) if zi > 0 else z
    return z


def left_edge_bottom_center_x(foot_px_x: int, img_w: int) -> int:
    """발(바닥 중심) 정수 픽셀 foot_px_x 기준 스프라이트 왼쪽 끝 x. 홀수 폭은 floor(foot - w/2)."""
    iw = int(img_w)
    ideal_left = float(foot_px_x) - float(iw) * 0.5
    if iw % 2 == 1:
        return int(math.floor(ideal_left + _EPS))
    return int(round(ideal_left))


def bg_anchor(cam_wx: float, cam_wy: float, zoom: float, origin_x: float = 0.0, origin_y: float = 0.0):
    z = float(zoom)
    ax = int(round((0.0 - float(cam_wx)) * z + float(origin_x)))
    ay = int(round((0.0 - float(cam_wy)) * z + float(origin_y)))
    return ax, ay


def feet_screen_pixels(bg_x: int, bg_y: int, world_x: float, world_y: float, zoom: float, height_world: float = 0.0):
    z = float(zoom)
    foot_fx = float(bg_x) + float(world_x) * z
    foot_fy = float(bg_y) + float(world_y) * z - float(height_world) * z
    return int(round(foot_fx)), int(round(foot_fy))


def blit_topleft_bottom_center(foot_px_x: int, foot_px_y: int, img_w: int, img_h: int):
    ih = int(img_h)
    return left_edge_bottom_center_x(foot_px_x, img_w), foot_px_y - ih


def blit_topleft_center_on_pixel(center_px_x: int, center_px_y: int, img_w: int, img_h: int):
    """타원·이펙트 등: 정수 중심 픽셀 기준, 홀수 폭·높이는 floor로 0.5px 편향 고정."""
    iw = int(img_w)
    ih = int(img_h)
    ideal_left = float(center_px_x) - float(iw) * 0.5
    ideal_top = float(center_px_y) - float(ih) * 0.5
    if iw % 2 == 1:
        left = int(math.floor(ideal_left + _EPS))
    else:
        left = int(round(ideal_left))
    if ih % 2 == 1:
        top = int(math.floor(ideal_top + _EPS))
    else:
        top = int(round(ideal_top))
    return left, top


def map_local_to_world(mx_local: float, my_local: float, bg_x: int, bg_y: int, zoom: float):
    z = float(zoom)
    if z < 1e-12:
        z = 1e-12
    return (float(mx_local) - float(bg_x)) / z, (float(my_local) - float(bg_y)) / z


def world_to_map_surface_xy(
    bg_x: int,
    bg_y: int,
    world_x: float,
    world_y: float,
    orig_w: int,
    orig_h: int,
    scaled_w: int,
    scaled_h: int,
    height_world: float = 0.0,
):
    """
    배경과 동일한 scale(원본 ow×oh → scaled_w×scaled_h)일 때 월드 픽셀 → 맵 서피스 정수 좌표.
    wx*zoom 반올림과 달리, 실제 blit된 배경 비트맵 열/행과 일치한다.
    """
    ow = max(1, int(orig_w))
    oh = max(1, int(orig_h))
    sw = max(1, int(scaled_w))
    sh = max(1, int(scaled_h))
    bx = int(bg_x)
    by = int(bg_y)
    try:
        h = float(height_world)
    except (TypeError, ValueError):
        h = 0.0
    sx = int(round(float(world_x) * float(sw) / float(ow)))
    sy = int(round((float(world_y) - h) * float(sh) / float(oh)))
    return bx + sx, by + sy


def map_surface_to_world_xy(
    mx_local: float,
    my_local: float,
    bg_x: int,
    bg_y: int,
    orig_w: int,
    orig_h: int,
    scaled_w: int,
    scaled_h: int,
):
    """world_to_map_surface_xy 의 역(맵 로컬 픽셀 → 월드)."""
    ow = max(1, int(orig_w))
    oh = max(1, int(orig_h))
    sw = max(1, int(scaled_w))
    sh = max(1, int(scaled_h))
    rel_x = float(mx_local) - float(int(bg_x))
    rel_y = float(my_local) - float(int(bg_y))
    wx = rel_x * float(ow) / float(sw)
    wy = rel_y * float(oh) / float(sh)
    return wx, wy

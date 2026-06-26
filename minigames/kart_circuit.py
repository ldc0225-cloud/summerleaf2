"""
kart_circuit — SNES 마리오카트 느낌 Mode7 서킷 주행 (프로토타입).

[상태]
  - 본편 MINIGAME_PLAY 연동 전 단독 데모 단계.
  - 실행: python kart_circuit_demo.py  (루트 런처)
         또는 python -m minigames.kart_circuit

[에셋]
  assets/minigames/kart/images/circuit/circuit/01.png      회색=도로
  assets/minigames/kart/images/circuit/character/trashbin_0.png
"""

from __future__ import annotations

import math
import os
import sys

import pygame

from minigames._paths import minigame_asset

CIRCUIT_PATH = minigame_asset("kart", "images", "circuit", "circuit", "01.png")
CHAR_PATH = minigame_asset("kart", "images", "circuit", "character", "trashbin_0.png")

SCREEN_W = 320
SCREEN_H = 240
FPS = 60
HORIZON = 72
SKY_COLOR = (92, 148, 220)
GRASS_COLOR = (58, 118, 52)
DRIVE_SPEED = 145.0
CAMERA_BACK = 26.0
LOOKAHEAD_DIST = 22.0
HEADING_SMOOTH = 0.14
MINIMAP_SIZE = 78


def is_road_pixel(r: int, g: int, b: int, a: int = 255) -> bool:
    if a < 8:
        return False
    if r > 245 and g > 245 and b > 245:
        return False
    if r < 45 and g < 45 and b < 45:
        return False
    return abs(int(r) - int(g)) < 36 and abs(int(g) - int(b)) < 36 and r > 95


def build_road_mask(map_surf: pygame.Surface) -> list[list[bool]]:
    w, h = map_surf.get_size()
    mask = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            c = map_surf.get_at((x, y))
            mask[y][x] = is_road_pixel(c[0], c[1], c[2], c[3] if len(c) > 3 else 255)
    return mask


def extract_center_path(map_surf: pygame.Surface, mask: list[list[bool]], samples: int = 640):
    w, h = map_surf.get_size()
    cx = w * 0.5
    cy = h * 0.5

    buckets: list[list[tuple[float, float]]] = [[] for _ in range(samples)]
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                continue
            ang = math.atan2(y - cy, x - cx)
            idx = int((ang + math.pi) / (2.0 * math.pi) * samples) % samples
            dist = math.hypot(x - cx, y - cy)
            buckets[idx].append((dist, float(x), float(y)))

    path: list[tuple[float, float]] = []
    for bucket in buckets:
        if not bucket:
            continue
        bucket.sort(key=lambda t: t[0])
        mid = bucket[len(bucket) // 2]
        path.append((mid[1], mid[2]))

    if len(path) < 32:
        raise RuntimeError("도로 중심선을 추출하지 못했습니다. circuit/01.png 회색 영역을 확인하세요.")

    path.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    path.append(path[0])

    if len(path) >= 8:
        for _ in range(3):
            sm = [path[0]]
            for i in range(1, len(path) - 1):
                x0, y0 = path[i - 1]
                x1, y1 = path[i]
                x2, y2 = path[i + 1]
                sm.append(((x0 + x1 + x2) / 3.0, (y0 + y1 + y2) / 3.0))
            sm.append(sm[0])
            path = sm

    seg_lens: list[float] = []
    total = 0.0
    for i in range(len(path) - 1):
        dx = path[i + 1][0] - path[i][0]
        dy = path[i + 1][1] - path[i][1]
        ln = math.hypot(dx, dy)
        seg_lens.append(ln)
        total += ln

    if total < 1.0:
        raise RuntimeError("트랙 경로 길이가 너무 짧습니다.")

    return path, seg_lens, total


def sample_path(path, seg_lens, total_len: float, dist: float):
    d = dist % total_len
    acc = 0.0
    for i, ln in enumerate(seg_lens):
        if acc + ln >= d:
            t = 0.0 if ln <= 1e-6 else (d - acc) / ln
            x0, y0 = path[i]
            x1, y1 = path[i + 1]
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            heading = math.atan2(y1 - y0, x1 - x0)
            return x, y, heading
        acc += ln
    x0, y0 = path[0]
    x1, y1 = path[1]
    heading = math.atan2(y1 - y0, x1 - x0)
    return x0, y0, heading


def _angle_wrap_pi(a: float) -> float:
    while a <= -math.pi:
        a += 2.0 * math.pi
    while a > math.pi:
        a -= 2.0 * math.pi
    return a


def lerp_angle(a: float, b: float, t: float) -> float:
    da = _angle_wrap_pi(b - a)
    return _angle_wrap_pi(a + da * max(0.0, min(1.0, float(t))))


def render_mode7(
    screen: pygame.Surface,
    map_surf: pygame.Surface,
    mask: list[list[bool]],
    cam_x: float,
    cam_y: float,
    cam_angle: float,
):
    w, h = screen.get_size()
    mw, mh = map_surf.get_size()
    screen.fill(SKY_COLOR, (0, 0, w, HORIZON))

    fwd_x = math.cos(cam_angle)
    fwd_y = math.sin(cam_angle)
    lat_x = -fwd_y
    lat_y = fwd_x

    map_px = pygame.surfarray.array3d(map_surf)
    out = pygame.surfarray.pixels3d(screen)

    CAM_H = 60.0
    NEAR = 6.0
    DEPTH_MUL = 165.0
    LATERAL_MUL = 1.05

    for sy in range(HORIZON, h):
        p = CAM_H / (float(sy - HORIZON) + NEAR)
        depth = p * DEPTH_MUL
        lateral_scale = p * LATERAL_MUL
        row_cx = cam_x + fwd_x * depth
        row_cy = cam_y + fwd_y * depth

        for sx in range(w):
            lateral = (sx - w * 0.5) * lateral_scale
            mx = int(row_cx + lateral * lat_x)
            my = int(row_cy + lateral * lat_y)
            if 0 <= mx < mw and 0 <= my < mh and mask[my][mx]:
                out[sx, sy] = map_px[mx, my]
            else:
                out[sx, sy] = GRASS_COLOR

    del out


def draw_hud(screen: pygame.Surface, font: pygame.font.Font, driving: bool, dist: float, total: float):
    msg = "클릭: 주행 시작" if not driving else "주행 중… (다시 클릭: 정지)"
    screen.blit(font.render(msg, True, (255, 255, 255)), (8, 8))
    if total > 0:
        lap_pct = int((dist % total) / total * 100.0)
        screen.blit(font.render(f"track {lap_pct}%", True, (240, 240, 200)), (8, 22))


def draw_minimap(
    screen: pygame.Surface,
    minimap_img: pygame.Surface,
    *,
    px: float,
    py: float,
    heading: float,
    map_w: int,
    map_h: int,
):
    mm = minimap_img
    mw = max(1, int(map_w))
    mh = max(1, int(map_h))
    w, h = screen.get_size()
    s = mm.get_width()
    x0 = w - s - 6
    y0 = 6
    screen.blit(mm, (x0, y0))
    pygame.draw.rect(screen, (0, 0, 0), (x0 - 1, y0 - 1, s + 2, s + 2), 1)
    dx = int(x0 + (float(px) / mw) * s)
    dy = int(y0 + (float(py) / mh) * s)
    pygame.draw.circle(screen, (255, 80, 80), (dx, dy), 2)
    ax = int(dx + math.cos(heading) * 7)
    ay = int(dy + math.sin(heading) * 7)
    pygame.draw.line(screen, (255, 200, 80), (dx, dy), (ax, ay), 1)


def main():
    if not os.path.isfile(CIRCUIT_PATH):
        print(f"[ERROR] 서킷 이미지 없음: {CIRCUIT_PATH}", file=sys.stderr)
        sys.exit(1)

    pygame.init()
    pygame.display.set_caption("Kart Circuit Mode7 Demo")
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("malgungothic", 14) or pygame.font.SysFont("arial", 14)

    map_surf = pygame.image.load(CIRCUIT_PATH).convert()
    mask = build_road_mask(map_surf)
    path, seg_lens, total_len = extract_center_path(map_surf, mask)
    map_w, map_h = map_surf.get_size()

    minimap_img = pygame.transform.smoothscale(map_surf, (MINIMAP_SIZE, MINIMAP_SIZE))
    minimap_img.set_alpha(210)

    if os.path.isfile(CHAR_PATH):
        char_img = pygame.image.load(CHAR_PATH).convert_alpha()
    else:
        char_img = pygame.Surface((24, 32), pygame.SRCALPHA)
        pygame.draw.rect(char_img, (90, 95, 105), (4, 10, 16, 20), border_radius=2)

    driving = False
    track_dist = 0.0
    cam_angle_smoothed = 0.0
    cam_angle_inited = False

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                driving = not driving

        if driving:
            track_dist += DRIVE_SPEED * dt

        px, py, _h0 = sample_path(path, seg_lens, total_len, track_dist)
        nx, ny, _h1 = sample_path(path, seg_lens, total_len, track_dist + LOOKAHEAD_DIST)
        heading = math.atan2(ny - py, nx - px)
        if not cam_angle_inited:
            cam_angle_smoothed = heading
            cam_angle_inited = True
        else:
            k = 1.0 - pow(max(0.0, 1.0 - HEADING_SMOOTH), max(0.0, dt) * 60.0)
            cam_angle_smoothed = lerp_angle(cam_angle_smoothed, heading, k)

        fwd_x = math.cos(cam_angle_smoothed)
        fwd_y = math.sin(cam_angle_smoothed)
        cam_x = px - fwd_x * CAMERA_BACK
        cam_y = py - fwd_y * CAMERA_BACK
        cam_angle = cam_angle_smoothed

        render_mode7(screen, map_surf, mask, cam_x, cam_y, cam_angle)

        ch = pygame.transform.smoothscale(
            char_img, (max(18, char_img.get_width() * 2), max(24, char_img.get_height() * 2))
        )
        cx = SCREEN_W // 2 - ch.get_width() // 2
        cy = SCREEN_H - ch.get_height() - 18
        screen.blit(ch, (cx, cy))

        draw_hud(screen, font, driving, track_dist, total_len)
        draw_minimap(
            screen,
            minimap_img,
            px=px,
            py=py,
            heading=cam_angle_smoothed,
            map_w=map_w,
            map_h=map_h,
        )
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()

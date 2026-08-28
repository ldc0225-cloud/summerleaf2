"""
activities.char_select — 세이브 없이 첫 시작 시 짱짱어린이집 주인공 선택.

[흐름]
  welcome(환영+안내) → pick(6명 그리드) → confirm(응/아니) → farewell → 종료

[호환]
  선택 풀 = data.CONFIG["PLAYABLE_KIDS"] (야구 p2_chars·레이스 char_pick 과 동일)
  UI 톤 = 야구/레이스 캐릭터 선택(idle 스프라이트 + 응/아니)

[결과]
  result.save_patch = {player_char, parent_char}
  main.py 가 페이드아웃 → 검정 유지 본편 스폰 → boot_phase=2.
  밝히기는 본편 첫 auto 이벤트(FADEIN)가 담당.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pygame

from .base import BaseFieldActivity, FieldDrawContext

ST_WELCOME = "welcome"
ST_PICK = "pick"
ST_CONFIRM = "confirm"
ST_FAREWELL = "farewell"

_GRID_COLS = 3
_GRID_ROWS = 2
_IDLE_GRID_H = 48
_IDLE_CONFIRM_H = 72


class CharSelectActivity(BaseFieldActivity):
    """첫 실행 주인공 선택 (필드 활동 형태 — 미니게임 선택 UI와 톤 맞춤)."""

    activity_id = "char_select"

    def __init__(self):
        self._active = False
        self._finished = False
        self._state = ST_WELCOME
        self._opts: List[str] = []
        self._pick_ix = 0
        self._pending_ix: Optional[int] = None
        self._pick_rects: List[Tuple[pygame.Rect, int]] = []
        self._menu_rects: List[Tuple[pygame.Rect, str]] = []
        self._idle_cache: Dict[str, Dict[str, List]] = {}
        self._elapsed = 0.0
        self._chosen = ""
        self._player_vis_saved = True
        self._player_ref = None
        self._save_patch: Dict[str, Any] = {}

    @property
    def is_active(self) -> bool:
        return bool(self._active) and not self._finished

    @property
    def is_finished(self) -> bool:
        return bool(self._finished)

    def blocks_field_move(self) -> bool:
        return True

    def blocks_zone_confirm(self) -> bool:
        return True

    def begin(self, player, **params) -> bool:
        from data import CONFIG, apply_player_char_choice, get_playable_kids

        self._player_ref = player
        self._opts = [c for c in get_playable_kids(CONFIG) if c]
        if not self._opts:
            return False
        self._pick_ix = 0
        self._pending_ix = None
        self._chosen = ""
        self._save_patch = {}
        self._state = ST_WELCOME
        self._elapsed = 0.0
        self._finished = False
        self._active = True
        self._idle_cache = {}
        # 데모 직후 캐릭터가 보이면 선택 UI와 겹침 → 숨김
        try:
            self._player_vis_saved = bool(getattr(player, "is_visible", True))
            player.is_visible = False
        except Exception:
            self._player_vis_saved = True
        # 기본 하이라이트: 현재/기본 캐릭터
        cur = str(getattr(player, "name", "") or CONFIG.get("DEFAULT_PLAYER_CHAR", "") or "")
        for i, cid in enumerate(self._opts):
            if cid == cur:
                self._pick_ix = i
                break
        # idle 프리로드
        for cid in self._opts:
            self._idle_frames(cid, "right")
        return True

    def tick(self, dt_sec: float, player, now_ms: int) -> None:
        if not self._active or self._finished:
            return
        try:
            self._elapsed += max(0.0, float(dt_sec))
        except Exception:
            self._elapsed += 0.016

    def result(self) -> Dict[str, Any]:
        return {
            "activity": self.activity_id,
            "won": bool(self._chosen),
            "quit": False,
            "player_char": self._chosen,
            "save_patch": dict(self._save_patch),
            # return_map 없음 — main 이 NEW_GAME 스폰을 담당
        }

    def cancel(self) -> None:
        self._restore_player_vis()
        self._finished = True
        self._active = False

    def _restore_player_vis(self) -> None:
        p = self._player_ref
        if p is None:
            return
        try:
            p.is_visible = bool(self._player_vis_saved)
        except Exception:
            pass

    def _char_label(self, cid: str) -> str:
        from char_behavior import get_char_ui_name

        return get_char_ui_name(cid) or cid

    def _idle_frames(self, char_id: str, direction: str = "right") -> List:
        cid = str(char_id or "").strip()
        if not cid:
            return []
        face = "right" if str(direction) == "right" else "left"
        bucket = self._idle_cache.get(cid)
        if not isinstance(bucket, dict):
            bucket = {}
            self._idle_cache[cid] = bucket
        if face in bucket:
            return bucket[face]
        from engine import load_anim_auto

        frames = load_anim_auto(cid, "idle", face) or []
        if not frames or self._is_placeholder(frames):
            alt = "left" if face == "right" else "right"
            alt_frames = load_anim_auto(cid, "idle", alt) or []
            if alt_frames and not self._is_placeholder(alt_frames):
                frames = [pygame.transform.flip(f, True, False) for f in alt_frames]
            else:
                frames = []
        bucket[face] = frames
        return frames

    @staticmethod
    def _is_placeholder(frames: List) -> bool:
        if len(frames) != 1:
            return False
        s = frames[0]
        try:
            if s.get_size() != (24, 32):
                return False
            r, g, b, *_rest = s.get_at((0, 0))
            return r > 250 and g < 10 and b > 250
        except Exception:
            return False

    def _blit_idle(
        self, surf: pygame.Surface, frames: List, center_xy: Tuple[int, int], max_h: int
    ) -> None:
        if not frames:
            return
        fi = int(self._elapsed * 6.0) % len(frames)
        img = frames[fi]
        iw, ih = img.get_size()
        if ih <= 0:
            return
        sc = max_h / ih
        dw, dh = max(1, int(iw * sc)), max(1, int(ih * sc))
        if (dw, dh) != (iw, ih):
            img = pygame.transform.scale(img, (dw, dh))
        cx, cy = center_xy
        surf.blit(img, (cx - dw // 2, cy - dh // 2))

    def _layout_pick_rects(self, w: int, h: int) -> None:
        self._pick_rects = []
        opts = list(self._opts or [])
        if not opts:
            return
        n = len(opts)
        cols = _GRID_COLS
        rows = max(_GRID_ROWS, (n + cols - 1) // cols)
        pad_x = int(w * 0.06)
        pad_top = int(h * 0.28)
        pad_bot = int(h * 0.10)
        gap_x = max(4, int(w * 0.02))
        gap_y = max(4, int(h * 0.02))
        avail_w = w - pad_x * 2
        avail_h = h - pad_top - pad_bot
        cell_w = max(40, (avail_w - gap_x * max(0, cols - 1)) // cols)
        cell_h = max(48, (avail_h - gap_y * max(0, rows - 1)) // rows)
        total_w = cols * cell_w + max(0, cols - 1) * gap_x
        x0 = w // 2 - total_w // 2
        y0 = pad_top
        for i, _cid in enumerate(opts[:n]):
            col = i % cols
            row = i // cols
            rx = x0 + col * (cell_w + gap_x)
            ry = y0 + row * (cell_h + gap_y)
            self._pick_rects.append((pygame.Rect(rx, ry, cell_w, cell_h), i))

    def _rebuild_menu_rects(self, w: int, h: int) -> None:
        self._menu_rects = []
        if self._state == ST_WELCOME:
            bw, bh = int(w * 0.40), int(h * 0.10)
            r = pygame.Rect(w // 2 - bw // 2, int(h * 0.78), bw, bh)
            self._menu_rects.append((r, "welcome_next"))
            return
        if self._state == ST_PICK:
            self._layout_pick_rects(w, h)
            for rect, ix in self._pick_rects:
                self._menu_rects.append((rect, f"char_pick:{ix}"))
            return
        if self._state == ST_CONFIRM:
            bw, bh = int(w * 0.34), int(h * 0.09)
            gap = int(w * 0.04)
            cy = int(h * 0.72)
            total = bw * 2 + gap
            bx = w // 2 - total // 2
            self._menu_rects.append((pygame.Rect(bx, cy, bw, bh), "confirm_yes"))
            self._menu_rects.append((pygame.Rect(bx + bw + gap, cy, bw, bh), "confirm_no"))
            return
        if self._state == ST_FAREWELL:
            bw, bh = int(w * 0.40), int(h * 0.10)
            r = pygame.Rect(w // 2 - bw // 2, int(h * 0.78), bw, bh)
            self._menu_rects.append((r, "farewell_go"))

    def _commit_choice(self, ix: int) -> None:
        from data import CONFIG, apply_player_char_choice

        if ix < 0 or ix >= len(self._opts):
            return
        cid = str(self._opts[ix])
        self._chosen = cid
        patch = apply_player_char_choice({}, cid, CONFIG, selected=True)
        self._save_patch = dict(patch)
        self._state = ST_FAREWELL

    def _finish(self) -> None:
        # 본편 스폰은 검정 페이드 뒤에서 이뤄지므로 여기서 플레이어를 다시 보이지 않는다.
        self._finished = True
        self._active = False

    def on_pointer_down(self, screen_xy, world_xy, now_ms: int) -> bool:
        if not self.is_active:
            return False
        try:
            sx, sy = int(screen_xy[0]), int(screen_xy[1])
        except Exception:
            return True
        for rect, act in self._menu_rects:
            if rect.collidepoint(sx, sy):
                return self._handle_action(act)
        return True

    def on_primary_key(self, key: int) -> bool:
        if not self.is_active:
            return False
        # Enter/Space/A 계열 — 단계 진행
        if self._state == ST_WELCOME:
            self._state = ST_PICK
            return True
        if self._state == ST_PICK:
            self._pending_ix = int(self._pick_ix)
            self._state = ST_CONFIRM
            return True
        if self._state == ST_CONFIRM:
            if self._pending_ix is not None:
                self._commit_choice(int(self._pending_ix))
            return True
        if self._state == ST_FAREWELL:
            self._finish()
            return True
        return True

    def _handle_action(self, act: str) -> bool:
        a = str(act or "")
        if a == "welcome_next":
            self._state = ST_PICK
            return True
        if a.startswith("char_pick:"):
            try:
                ix = int(a.split(":", 1)[1])
            except Exception:
                return True
            self._pick_ix = ix
            self._pending_ix = ix
            self._state = ST_CONFIRM
            return True
        if a == "confirm_yes":
            if self._pending_ix is not None:
                self._commit_choice(int(self._pending_ix))
            return True
        if a == "confirm_no":
            self._pending_ix = None
            self._state = ST_PICK
            return True
        if a == "farewell_go":
            self._finish()
            return True
        return True

    def draw_screen(self, ctx: FieldDrawContext) -> None:
        if not self.is_active:
            return
        surf = ctx.surf
        w, h = surf.get_width(), surf.get_height()
        font = ctx.font_fn(13)
        small = ctx.font_fn(10)
        # 반투명 배경
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((8, 14, 28, 210))
        surf.blit(overlay, (0, 0))
        self._rebuild_menu_rects(w, h)

        from data import CONFIG

        if self._state == ST_WELCOME:
            welcome = str(CONFIG.get("CHAR_SELECT_WELCOME") or "")
            prompt = str(CONFIG.get("CHAR_SELECT_PROMPT") or "")
            t1 = font.render(welcome, True, (255, 248, 220))
            surf.blit(t1, (w // 2 - t1.get_width() // 2, int(h * 0.28)))
            t2 = small.render(prompt, True, (200, 220, 245))
            surf.blit(t2, (w // 2 - t2.get_width() // 2, int(h * 0.42)))
            for rect, act in self._menu_rects:
                if act != "welcome_next":
                    continue
                pygame.draw.rect(surf, (50, 90, 60), rect, border_radius=6)
                pygame.draw.rect(surf, (120, 180, 130), rect, 2, border_radius=6)
                lab = small.render("다음", True, (230, 255, 230))
                surf.blit(
                    lab,
                    (rect.centerx - lab.get_width() // 2, rect.centery - lab.get_height() // 2),
                )
            return

        if self._state == ST_PICK:
            short = small.render("모험을 떠날 친구를 골라 주세요", True, (255, 248, 220))
            surf.blit(short, (w // 2 - short.get_width() // 2, int(h * 0.08)))
            hint = small.render("캐릭터를 탭하세요", True, (180, 200, 220))
            surf.blit(hint, (w // 2 - hint.get_width() // 2, int(h * 0.16)))
            self._layout_pick_rects(w, h)
            for rect, ix in self._pick_rects:
                cid = str(self._opts[ix])
                selected = ix == self._pick_ix
                border = (255, 220, 120) if selected else (120, 140, 180)
                pygame.draw.rect(surf, (40, 50, 78), rect, border_radius=8)
                pygame.draw.rect(surf, border, rect, 2 if not selected else 3, border_radius=8)
                frames = self._idle_frames(cid, "right")
                sprite_h = min(_IDLE_GRID_H, max(16, int(rect.height * 0.55)))
                sy = rect.centery - int(sprite_h * 0.12)
                self._blit_idle(surf, frames, (rect.centerx, sy), sprite_h)
                lbl = small.render(self._char_label(cid), True, (210, 225, 245))
                ly = rect.bottom - lbl.get_height() - 3
                if ly >= rect.top:
                    surf.blit(lbl, (rect.centerx - lbl.get_width() // 2, ly))
            return

        if self._state == ST_CONFIRM:
            ix = int(self._pending_ix if self._pending_ix is not None else self._pick_ix)
            cid = str(self._opts[ix]) if self._opts else ""
            frames = self._idle_frames(cid, "right")
            full_h = min(int(h * 0.30), _IDLE_CONFIRM_H)
            cy = int(h * 0.36)
            self._blit_idle(surf, frames, (w // 2, cy), full_h)
            nm = self._char_label(cid)
            name_s = font.render(nm, True, (255, 248, 220))
            surf.blit(name_s, (w // 2 - name_s.get_width() // 2, int(h * 0.52)))
            fmt = str(CONFIG.get("CHAR_SELECT_CONFIRM_FMT") or "{name}로 선택 하시겠어요?")
            ask_txt = fmt.replace("{name}", nm)
            ask = font.render(ask_txt, True, (230, 240, 255))
            surf.blit(ask, (w // 2 - ask.get_width() // 2, int(h * 0.60)))
            for rect, act in self._menu_rects:
                if act == "confirm_yes":
                    pygame.draw.rect(surf, (50, 90, 60), rect, border_radius=6)
                    ty = small.render("응", True, (230, 255, 230))
                    surf.blit(
                        ty,
                        (rect.centerx - ty.get_width() // 2, rect.centery - ty.get_height() // 2),
                    )
                elif act == "confirm_no":
                    pygame.draw.rect(surf, (70, 50, 50), rect, border_radius=6)
                    tn = small.render("아니", True, (255, 230, 230))
                    surf.blit(
                        tn,
                        (rect.centerx - tn.get_width() // 2, rect.centery - tn.get_height() // 2),
                    )
            return

        if self._state == ST_FAREWELL:
            farewell = str(CONFIG.get("CHAR_SELECT_FAREWELL") or "")
            # 긴 문장 — 두 줄로 나눌 수 있으면 단순 중앙 표시
            lines = self._wrap_text(farewell, small, int(w * 0.88))
            y = int(h * 0.36)
            for line in lines:
                t = font.render(line, True, (255, 248, 220)) if len(lines) == 1 else small.render(
                    line, True, (255, 248, 220)
                )
                surf.blit(t, (w // 2 - t.get_width() // 2, y))
                y += t.get_height() + 6
            if self._chosen:
                tip = small.render(f"({self._char_label(self._chosen)})", True, (180, 210, 230))
                surf.blit(tip, (w // 2 - tip.get_width() // 2, y + 8))
            for rect, act in self._menu_rects:
                if act != "farewell_go":
                    continue
                pygame.draw.rect(surf, (50, 90, 60), rect, border_radius=6)
                pygame.draw.rect(surf, (120, 180, 130), rect, 2, border_radius=6)
                lab = small.render("출발!", True, (230, 255, 230))
                surf.blit(
                    lab,
                    (rect.centerx - lab.get_width() // 2, rect.centery - lab.get_height() // 2),
                )

    @staticmethod
    def _wrap_text(text: str, font: pygame.font.Font, max_w: int) -> List[str]:
        s = str(text or "").strip()
        if not s:
            return []
        if font.size(s)[0] <= max_w:
            return [s]
        lines: List[str] = []
        cur = ""
        for ch in s:
            trial = cur + ch
            if cur and font.size(trial)[0] > max_w:
                lines.append(cur)
                cur = ch
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines or [s]

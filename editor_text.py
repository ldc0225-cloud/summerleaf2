"""에디터 공통 텍스트 입력 — 커서·중간 수정·선택·클립보드.

기존 입력란은 문자열 끝 붙이기/끝 지우기만 지원했다.
이 모듈의 EditSession 을 쓰면:
  - 커서 위치에서 삽입/삭제
  - ←→ Home/End
  - 선택(Shift+이동, Ctrl+A)
  - Ctrl+C / X / V 붙여넣기
  - 활성 필드에 캐럿·선택 하이라이트 그리기

필드 값은 호출측 dict/변수에 그대로 두고, 커서·선택만 EditSession 이 보관한다.
"""
from __future__ import annotations

from typing import Optional, Tuple

import pygame

# 선택 구간: [start, end) — start <= end
Sel = Optional[Tuple[int, int]]


def clamp_cursor(text: str, cursor: int) -> int:
    t = str(text or "")
    try:
        c = int(cursor)
    except (TypeError, ValueError):
        c = len(t)
    return max(0, min(len(t), c))


def normalize_sel(text: str, sel: Sel) -> Sel:
    if not sel:
        return None
    t = str(text or "")
    a, b = sel
    try:
        a, b = int(a), int(b)
    except (TypeError, ValueError):
        return None
    a = max(0, min(len(t), a))
    b = max(0, min(len(t), b))
    if a == b:
        return None
    if a > b:
        a, b = b, a
    return (a, b)


def _sel_range(text: str, cursor: int, sel: Sel) -> Tuple[int, int]:
    """삭제/치환에 쓸 [lo, hi). 선택 없으면 커서 기준 빈 구간."""
    t = str(text or "")
    s = normalize_sel(t, sel)
    if s:
        return s
    c = clamp_cursor(t, cursor)
    return (c, c)


def clipboard_get() -> str:
    """클립보드 텍스트. pygame.scrap 우선, Windows 는 ctypes 폴백."""
    raw = None
    try:
        if not pygame.scrap.get_init():
            pygame.scrap.init()
        raw = pygame.scrap.get(pygame.SCRAP_TEXT)
    except Exception:
        raw = None
    if raw:
        if isinstance(raw, bytes):
            for enc in ("utf-8", "utf-16", "cp949", "latin-1"):
                try:
                    s = raw.decode(enc)
                    s = s.replace("\x00", "")
                    if s:
                        return s.replace("\r\n", "\n").replace("\r", "\n")
                except Exception:
                    continue
        else:
            s = str(raw).replace("\x00", "")
            if s:
                return s.replace("\r\n", "\n").replace("\r", "\n")
    # Windows CF_UNICODETEXT
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        CF_UNICODETEXT = 13
        if not user32.OpenClipboard(None):
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                s = ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
            return (s or "").replace("\r\n", "\n").replace("\r", "\n")
        finally:
            user32.CloseClipboard()
    except Exception:
        return ""


def clipboard_set(text: str) -> bool:
    s = str(text or "")
    try:
        if not pygame.scrap.get_init():
            pygame.scrap.init()
        pygame.scrap.put(pygame.SCRAP_TEXT, s.encode("utf-8"))
        return True
    except Exception:
        pass
    try:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            # +1 wchar null
            buf = ctypes.create_unicode_buffer(s)
            nbytes = (len(s) + 1) * 2
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, nbytes)
            if not handle:
                return False
            ptr = kernel32.GlobalLock(handle)
            ctypes.memmove(ptr, buf, nbytes)
            kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(CF_UNICODETEXT, handle)
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def insert_at(text: str, cursor: int, sel: Sel, chunk: str) -> Tuple[str, int, Sel]:
    """커서(또는 선택 구간)에 chunk 삽입. 개행은 공백으로 평탄화(한 줄 필드용)."""
    t = str(text or "")
    chunk = str(chunk or "").replace("\r\n", "\n").replace("\r", "\n")
    # 에디터 한 줄 칸: 실제 개행은 넣지 않음 (DIALOG 의 \\n 은 호출측에서 별도 처리)
    chunk = chunk.replace("\n", " ")
    lo, hi = _sel_range(t, cursor, sel)
    nt = t[:lo] + chunk + t[hi:]
    nc = lo + len(chunk)
    return nt, nc, None


def delete_sel_or_backspace(text: str, cursor: int, sel: Sel) -> Tuple[str, int, Sel]:
    t = str(text or "")
    s = normalize_sel(t, sel)
    if s:
        lo, hi = s
        return t[:lo] + t[hi:], lo, None
    c = clamp_cursor(t, cursor)
    if c <= 0:
        return t, 0, None
    return t[: c - 1] + t[c:], c - 1, None


def delete_sel_or_forward(text: str, cursor: int, sel: Sel) -> Tuple[str, int, Sel]:
    t = str(text or "")
    s = normalize_sel(t, sel)
    if s:
        lo, hi = s
        return t[:lo] + t[hi:], lo, None
    c = clamp_cursor(t, cursor)
    if c >= len(t):
        return t, c, None
    return t[:c] + t[c + 1 :], c, None


def move_cursor(
    text: str, cursor: int, sel: Sel, key, *, shift: bool
) -> Tuple[int, Sel]:
    t = str(text or "")
    c = clamp_cursor(t, cursor)
    anchor = None
    if shift:
        s = normalize_sel(t, sel)
        if s:
            # 커서 쪽이 확장 끝
            if c == s[0]:
                anchor = s[1]
            else:
                anchor = s[0]
        else:
            anchor = c

    if key == pygame.K_LEFT:
        c = max(0, c - 1)
    elif key == pygame.K_RIGHT:
        c = min(len(t), c + 1)
    elif key == pygame.K_HOME:
        c = 0
    elif key == pygame.K_END:
        c = len(t)
    else:
        return c, normalize_sel(t, sel)

    if shift and anchor is not None:
        a, b = (anchor, c) if anchor <= c else (c, anchor)
        return c, None if a == b else (a, b)
    return c, None


def cursor_from_click_x(text: str, font, local_x: float, *, pad: int = 5) -> int:
    """필드 왼쪽+pad 기준 x → 커서 인덱스."""
    t = str(text or "")
    x = float(local_x) - float(pad)
    if x <= 0:
        return 0
    # 누적 폭으로 가장 가까운 위치
    best_i, best_d = 0, abs(x)
    acc = 0
    for i, ch in enumerate(t):
        try:
            w = font.size(ch)[0]
        except Exception:
            w = 8
        acc += w
        d = abs(acc - x)
        if d < best_d:
            best_d, best_i = d, i + 1
    return best_i


def blit_editable_text(
    screen,
    font,
    text: str,
    cursor: int,
    sel: Sel,
    rect: pygame.Rect,
    *,
    color=(250, 250, 252),
    pad: int = 5,
    active: bool = True,
    trunc_limit: Optional[int] = None,
):
    """필드 값 + (활성 시) 선택 하이라이트·깜빡이 캐럿."""
    t = str(text or "")
    prev = screen.get_clip()
    screen.set_clip(rect)
    try:
        c = clamp_cursor(t, cursor)
        s = normalize_sel(t, sel) if active else None
        # 긴 문자열: 커서 근처가 보이도록 가로 스크롤
        try:
            full_w = font.size(t)[0] if t else 0
        except Exception:
            full_w = 0
        inner_w = max(1, rect.width - pad * 2)
        scroll = 0
        if active and full_w > inner_w:
            try:
                pre_w = font.size(t[:c])[0]
            except Exception:
                pre_w = 0
            scroll = max(0, pre_w - inner_w + 12)
            scroll = min(scroll, max(0, full_w - inner_w))

        base_x = rect.x + pad - scroll
        y = rect.y + 5

        if s and active:
            lo, hi = s
            try:
                x0 = base_x + font.size(t[:lo])[0]
                x1 = base_x + font.size(t[:hi])[0]
            except Exception:
                x0, x1 = base_x, base_x + 4
            hi_rect = pygame.Rect(x0, rect.y + 3, max(2, x1 - x0), rect.height - 6)
            pygame.draw.rect(screen, (60, 90, 140), hi_rect)

        draw_s = t
        if (not active) and trunc_limit is not None and len(draw_s) > trunc_limit:
            draw_s = draw_s[: max(0, trunc_limit - 3)] + "..."
            try:
                img = font.render(draw_s, True, color)
            except Exception:
                img = font.render(" ", True, color)
            screen.blit(img, (rect.x + pad, y))
        else:
            try:
                img = font.render(t if t else " ", True, color)
            except Exception:
                img = font.render(" ", True, color)
            screen.blit(img, (base_x, y))

        if active and (pygame.time.get_ticks() // 500) % 2 == 0:
            try:
                cx = base_x + (font.size(t[:c])[0] if t else 0)
            except Exception:
                cx = base_x
            pygame.draw.line(
                screen,
                (255, 230, 120),
                (cx, rect.y + 4),
                (cx, rect.bottom - 4),
                1,
            )
    finally:
        screen.set_clip(prev)


class EditSession:
    """한 번에 하나의 활성 입력란용 커서/선택 상태."""

    __slots__ = ("cursor", "sel")

    def __init__(self):
        self.cursor = 0
        self.sel: Sel = None

    def focus(self, text: str, *, at_end: bool = True, at: Optional[int] = None) -> None:
        t = str(text or "")
        if at is not None:
            self.cursor = clamp_cursor(t, at)
        elif at_end:
            self.cursor = len(t)
        else:
            self.cursor = 0
        self.sel = None

    def focus_click(self, text: str, font, local_x: float, *, pad: int = 5) -> None:
        t = str(text or "")
        self.cursor = cursor_from_click_x(t, font, local_x, pad=pad)
        self.sel = None

    def insert(self, text: str, chunk: str) -> str:
        nt, c, s = insert_at(text, self.cursor, self.sel, chunk)
        self.cursor, self.sel = c, s
        return nt

    def keydown(self, text: str, event) -> Tuple[str, bool]:
        """
        KEYDOWN 처리. (new_text, handled).
        Escape/Return 은 호출측에서 포커스 해제용으로 따로 다루는 것이 일반적 —
        여기서는 텍스트 편집 키만 handled=True.
        """
        if getattr(event, "type", None) != pygame.KEYDOWN:
            return str(text or ""), False
        key = event.key
        mods = pygame.key.get_mods()
        ctrl = bool(mods & pygame.KMOD_CTRL)
        shift = bool(mods & pygame.KMOD_SHIFT)
        t = str(text or "")

        # 클립보드 / 전체선택
        if ctrl and key == pygame.K_a:
            self.cursor = len(t)
            self.sel = (0, len(t)) if t else None
            return t, True
        if ctrl and key == pygame.K_c:
            s = normalize_sel(t, self.sel)
            if s:
                clipboard_set(t[s[0] : s[1]])
            return t, True
        if ctrl and key == pygame.K_x:
            s = normalize_sel(t, self.sel)
            if s:
                clipboard_set(t[s[0] : s[1]])
                t, self.cursor, self.sel = delete_sel_or_backspace(t, self.cursor, self.sel)
            return t, True
        if ctrl and key == pygame.K_v:
            clip = clipboard_get()
            if clip:
                t = self.insert(t, clip)
            return t, True

        if key == pygame.K_BACKSPACE:
            t, self.cursor, self.sel = delete_sel_or_backspace(t, self.cursor, self.sel)
            return t, True
        if key == pygame.K_DELETE:
            t, self.cursor, self.sel = delete_sel_or_forward(t, self.cursor, self.sel)
            return t, True
        if key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_HOME, pygame.K_END):
            self.cursor, self.sel = move_cursor(t, self.cursor, self.sel, key, shift=shift)
            return t, True

        return t, False

    def blit(self, screen, font, text: str, rect, *, color=(250, 250, 252), active=True, trunc_limit=None):
        blit_editable_text(
            screen,
            font,
            text,
            self.cursor,
            self.sel,
            rect,
            color=color,
            active=active,
            trunc_limit=trunc_limit,
        )


def blit_field_value(
    screen,
    font,
    text,
    rect,
    *,
    active: bool = False,
    session: Optional[EditSession] = None,
    color=(255, 255, 255),
    trunc_limit: Optional[int] = None,
):
    """입력란 값 그리기 — 활성이면 커서/선택, 아니면 일반(선택적 말줄임)."""
    s = str(text or "")
    if active and session is not None:
        session.blit(screen, font, s, rect, color=color, active=True, trunc_limit=None)
        return
    draw = s
    if trunc_limit is not None and len(draw) > trunc_limit:
        draw = draw[: max(0, trunc_limit - 3)] + "..."
    try:
        img = font.render(draw if draw else " ", True, color)
    except Exception:
        img = font.render(" ", True, color)
    screen.blit(img, (rect.x + 5, rect.y + 5))

"""에디터 DIALOG — events.json 전체 SAY 스텝을 한 줄 목록으로 보고 고친다.

상단바 DIALOG 버튼. 창은 에디터 화면을 꽉 채움.
행: 이벤트 이름 | 스텝번호 | who | 대사(한 줄). who·대사는 클릭해서 수정.
줄바꿈은 목록에서 \\n 으로 보이게 하고, 저장 때 실제 개행으로 되돌린다.
"""
from __future__ import annotations

from typing import Callable, Optional

import pygame

import editor_text as ed_txt

# editor.py EDITOR_EVENT_SECTIONS 과 동일. editor 를 import 하면 순환 참조.
_SECTIONS = ("LOCAL", "GLOBAL", "SYNC", "FRAGMENTS")

HEAD_H = 48
COL_HEAD_H = 26
ROW_H = 28
SB_W = 14
PAD = 8
# 가로가 긴 대사용 — 이보다 좁으면 안 됨, 긴 줄은 이보다 넓어져 가로 스크롤
TEXT_COL_MIN = 480
EVENT_COL_MIN = 200
EVENT_COL_MAX = 380
WHO_COL_MIN = 72
WHO_COL_MAX = 180
IDX_COL_W = 44


def new_state() -> dict:
    return {
        "show": False,
        "rows": [],
        "scroll_y": 0,
        "scroll_x": 0,
        "edit": None,  # (row_i, "who"|"text")
        "edit_text": "",
        "selected": -1,
        "msg": "",
        "_drag": None,  # "v" | "h" | None
        "_layout": None,
        "text_edit": ed_txt.EditSession(),
    }


def _event_display_name(eid, edata) -> str:
    return str((edata or {}).get("title") or "").strip() or str(eid)


def _text_w(font, text) -> int:
    try:
        return int(font.size(str(text or ""))[0])
    except Exception:
        return max(1, len(str(text or "")) * 7)


def _say_one_line(step) -> str:
    """목록·편집용: 개행을 \\n 한 토큰으로."""
    return str((step or {}).get("text") or "").replace("\r\n", "\n").replace("\n", "\\n")


def _say_from_one_line(s: str) -> str:
    return str(s or "").replace("\\n", "\n")


def collect_rows(all_events) -> list:
    """섹션 순 → 이벤트 이름 순 → 스텝 인덱스. step 은 all_events 안 live dict."""
    rows = []
    for sec in _SECTIONS:
        items = []
        for eid, edata in ((all_events or {}).get(sec) or {}).items():
            items.append((str(eid), edata or {}))
        items.sort(
            key=lambda pair: (
                _event_display_name(pair[0], pair[1]).casefold(),
                pair[0].casefold(),
            )
        )
        for eid, edata in items:
            steps = edata.get("steps") or []
            if not isinstance(steps, list):
                continue
            title = _event_display_name(eid, edata)
            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                if str(step.get("type") or "").upper() != "SAY":
                    continue
                rows.append(
                    {
                        "section": sec,
                        "event_id": eid,
                        "title": title,
                        "step_index": i,
                        "step": step,
                    }
                )
    return rows


def open_modal(state: dict, all_events) -> None:
    state["show"] = True
    state["rows"] = collect_rows(all_events)
    state["scroll_y"] = 0
    state["scroll_x"] = 0
    state["edit"] = None
    state["edit_text"] = ""
    state["selected"] = -1
    state["_drag"] = None
    n = len(state["rows"])
    state["msg"] = f"SAY {n}줄 · 칸 클릭해서 수정 · Esc 닫기"


def _commit_edit(state: dict, save_fn: Optional[Callable] = None) -> None:
    ed = state.get("edit")
    if not ed:
        return
    try:
        ri, key = ed
        row = (state.get("rows") or [])[int(ri)]
        step = row.get("step")
        if not isinstance(step, dict):
            state["edit"] = None
            return
        raw = str(state.get("edit_text") or "")
        if key == "text":
            step["text"] = _say_from_one_line(raw)
        elif key == "who":
            v = raw.strip()
            if v:
                step["who"] = v
            else:
                step.pop("who", None)
        state["msg"] = "반영됨 (events.json 저장)"
        if callable(save_fn):
            try:
                save_fn()
            except Exception as e:
                state["msg"] = f"저장 실패: {e}"
    except Exception as e:
        state["msg"] = f"수정 실패: {e}"
    state["edit"] = None
    state["edit_text"] = ""


def _begin_edit(state: dict, row_i: int, key: str) -> None:
    rows = state.get("rows") or []
    if row_i < 0 or row_i >= len(rows):
        return
    step = (rows[row_i] or {}).get("step") or {}
    if key == "text":
        state["edit_text"] = _say_one_line(step)
    elif key == "who":
        state["edit_text"] = str(step.get("who") or "")
    else:
        return
    state["edit"] = (int(row_i), key)
    state["selected"] = int(row_i)
    te = state.get("text_edit")
    if not isinstance(te, ed_txt.EditSession):
        te = ed_txt.EditSession()
        state["text_edit"] = te
    te.focus(str(state.get("edit_text") or ""))


def close_modal(state: dict, save_fn: Optional[Callable] = None) -> None:
    _commit_edit(state, save_fn)
    state["show"] = False
    state["_drag"] = None
    state["_layout"] = None


def _col_widths(font, rows) -> tuple:
    """이벤트·who·대사 칸 폭. 대사는 가장 긴 한 줄에 맞춤."""
    ev_w = EVENT_COL_MIN
    who_w = WHO_COL_MIN
    tx_w = TEXT_COL_MIN
    for row in rows or []:
        title = str(row.get("title") or "")
        eid = str(row.get("event_id") or "")
        sec = str(row.get("section") or "")
        lab = f"{sec}  {title}"
        if title != eid:
            lab = f"{sec}  {title}  [{eid}]"
        ev_w = max(ev_w, min(EVENT_COL_MAX, _text_w(font, lab) + 16))
        who = str((row.get("step") or {}).get("who") or "") or "player"
        who_w = max(who_w, min(WHO_COL_MAX, _text_w(font, who) + 16))
        tx_w = max(tx_w, _text_w(font, _say_one_line(row.get("step"))) + 24)
    return int(ev_w), int(who_w), int(tx_w)


def layout_ui(state, font, sw, sh) -> dict:
    sw, sh = int(sw), int(sh)
    rows = state.get("rows") or []
    ev_w, who_w, tx_w = _col_widths(font, rows)
    content_w = PAD + ev_w + IDX_COL_W + who_w + tx_w + PAD
    body = pygame.Rect(0, HEAD_H + COL_HEAD_H, sw - SB_W, sh - HEAD_H - COL_HEAD_H - SB_W)
    content_h = max(ROW_H, len(rows) * ROW_H)
    max_sy = max(0, content_h - max(1, body.height))
    max_sx = max(0, content_w - max(1, body.width))
    sy = max(0, min(max_sy, int(state.get("scroll_y") or 0)))
    sx = max(0, min(max_sx, int(state.get("scroll_x") or 0)))
    state["scroll_y"] = sy
    state["scroll_x"] = sx

    close_r = pygame.Rect(sw - 88, 8, 76, 32)
    vtrack = pygame.Rect(sw - SB_W, body.y, SB_W, body.height)
    htrack = pygame.Rect(0, sh - SB_W, body.width, SB_W)
    vthumb = None
    if max_sy > 0 and body.height > 0:
        th = max(24, int(body.height * body.height / max(1, content_h)))
        span = max(1, body.height - th)
        vthumb = pygame.Rect(vtrack.x, body.y + int(span * (sy / max_sy)), SB_W, th)
    hthumb = None
    if max_sx > 0 and body.width > 0:
        tw = max(24, int(body.width * body.width / max(1, content_w)))
        span = max(1, body.width - tw)
        hthumb = pygame.Rect(int(span * (sx / max_sx)), htrack.y, tw, SB_W)

    x0 = PAD - sx
    ev_r = pygame.Rect(x0, 0, ev_w, ROW_H)
    idx_r = pygame.Rect(ev_r.right, 0, IDX_COL_W, ROW_H)
    who_r = pygame.Rect(idx_r.right, 0, who_w, ROW_H)
    tx_r = pygame.Rect(who_r.right, 0, tx_w, ROW_H)
    return {
        "sw": sw,
        "sh": sh,
        "body": body,
        "close": close_r,
        "vtrack": vtrack,
        "htrack": htrack,
        "vthumb": vthumb,
        "hthumb": hthumb,
        "max_sy": max_sy,
        "max_sx": max_sx,
        "ev_w": ev_w,
        "who_w": who_w,
        "tx_w": tx_w,
        "content_w": content_w,
        "content_h": content_h,
        "ev_x": ev_r.x,
        "idx_x": idx_r.x,
        "who_x": who_r.x,
        "tx_x": tx_r.x,
    }


def _row_at(ui, state, mx, my):
    body = ui["body"]
    if not body.collidepoint(mx, my):
        return -1
    local_y = int(my) - int(body.y) + int(state.get("scroll_y") or 0)
    if local_y < 0:
        return -1
    i = local_y // ROW_H
    n = len(state.get("rows") or [])
    if i < 0 or i >= n:
        return -1
    return int(i)


def _field_at(ui, mx, row_i) -> Optional[str]:
    """클릭 x → who / text. 이벤트 칸은 None (선택만)."""
    if mx >= ui["tx_x"] and mx < ui["tx_x"] + ui["tx_w"]:
        return "text"
    if mx >= ui["who_x"] and mx < ui["who_x"] + ui["who_w"]:
        return "who"
    return None


def handle_event(state: dict, event, sw, sh, mx, my, font, save_fn=None) -> bool:
    """열려 있으면 입력을 전부 소비."""
    if not state.get("show"):
        return False
    ui = state.get("_layout") or layout_ui(state, font, sw, sh)
    state["_layout"] = ui

    if event.type == pygame.MOUSEWHEEL:
        mods = pygame.key.get_mods()
        dy = int(getattr(event, "y", 0) or 0)
        if mods & pygame.KMOD_SHIFT:
            state["scroll_x"] = max(
                0, min(int(ui["max_sx"]), int(state.get("scroll_x") or 0) - dy * 48)
            )
        else:
            state["scroll_y"] = max(
                0, min(int(ui["max_sy"]), int(state.get("scroll_y") or 0) - dy * ROW_H)
            )
        return True

    if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
        state["_drag"] = None
        return True

    if event.type == pygame.MOUSEMOTION:
        drag = state.get("_drag")
        if drag == "v" and ui.get("vthumb") and ui["max_sy"] > 0:
            track = ui["vtrack"]
            th = ui["vthumb"].height
            span = max(1, track.height - th)
            rel = max(0.0, min(1.0, (float(my) - track.y - th * 0.5) / span))
            state["scroll_y"] = int(rel * ui["max_sy"])
        elif drag == "h" and ui.get("hthumb") and ui["max_sx"] > 0:
            track = ui["htrack"]
            tw = ui["hthumb"].width
            span = max(1, track.width - tw)
            rel = max(0.0, min(1.0, (float(mx) - track.x - tw * 0.5) / span))
            state["scroll_x"] = int(rel * ui["max_sx"])
        return True

    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        if ui["close"].collidepoint(mx, my):
            close_modal(state, save_fn)
            return True
        if ui.get("vthumb") and ui["vthumb"].collidepoint(mx, my):
            state["_drag"] = "v"
            return True
        if ui.get("hthumb") and ui["hthumb"].collidepoint(mx, my):
            state["_drag"] = "h"
            return True
        if ui["vtrack"].collidepoint(mx, my) and ui["max_sy"] > 0:
            rel = (float(my) - ui["vtrack"].y) / max(1, ui["vtrack"].height)
            state["scroll_y"] = int(max(0.0, min(1.0, rel)) * ui["max_sy"])
            return True
        if ui["htrack"].collidepoint(mx, my) and ui["max_sx"] > 0:
            rel = (float(mx) - ui["htrack"].x) / max(1, ui["htrack"].width)
            state["scroll_x"] = int(max(0.0, min(1.0, rel)) * ui["max_sx"])
            return True
        ri = _row_at(ui, state, mx, my)
        if ri < 0:
            _commit_edit(state, save_fn)
            state["selected"] = -1
            return True
        fld = _field_at(ui, mx, ri)
        cur = state.get("edit")
        if cur and cur != (ri, fld):
            _commit_edit(state, save_fn)
        state["selected"] = ri
        if fld:
            _begin_edit(state, ri, fld)
        return True

    if event.type == pygame.TEXTINPUT:
        if state.get("edit"):
            te = state.get("text_edit")
            if not isinstance(te, ed_txt.EditSession):
                te = ed_txt.EditSession()
                state["text_edit"] = te
                te.focus(str(state.get("edit_text") or ""))
            state["edit_text"] = te.insert(str(state.get("edit_text") or ""), str(event.text or ""))
        return True

    if event.type == pygame.KEYDOWN:
        key = event.key
        mods = pygame.key.get_mods()
        if key == pygame.K_ESCAPE:
            if state.get("edit"):
                state["edit"] = None
                state["edit_text"] = ""
                state["msg"] = "수정 취소"
            else:
                close_modal(state, save_fn)
            return True
        if key == pygame.K_s and (mods & pygame.KMOD_CTRL):
            _commit_edit(state, save_fn)
            return True
        if key == pygame.K_TAB:
            rows = state.get("rows") or []
            n = len(rows)
            if n <= 0:
                return True
            cur = state.get("edit")
            sel = int(state.get("selected") or 0)
            if sel < 0:
                sel = 0
            nxt_field = "who"
            nxt_row = sel
            if cur:
                ri, fk = cur
                if fk == "who" and not (mods & pygame.KMOD_SHIFT):
                    nxt_row, nxt_field = ri, "text"
                elif fk == "text" and (mods & pygame.KMOD_SHIFT):
                    nxt_row, nxt_field = ri, "who"
                else:
                    nxt_row = (ri + (-1 if (mods & pygame.KMOD_SHIFT) else 1)) % n
                    nxt_field = "text" if (mods & pygame.KMOD_SHIFT) else "who"
            elif mods & pygame.KMOD_SHIFT:
                nxt_row, nxt_field = (sel - 1) % n, "text"
            _commit_edit(state, save_fn)
            _begin_edit(state, nxt_row, nxt_field)
            # 선택 행이 보이게 스크롤
            vis0 = int(state.get("scroll_y") or 0)
            vis1 = vis0 + ui["body"].height
            y0 = nxt_row * ROW_H
            if y0 < vis0:
                state["scroll_y"] = y0
            elif y0 + ROW_H > vis1:
                state["scroll_y"] = max(0, y0 + ROW_H - ui["body"].height)
            return True
        if state.get("edit"):
            te = state.get("text_edit")
            if not isinstance(te, ed_txt.EditSession):
                te = ed_txt.EditSession()
                state["text_edit"] = te
                te.focus(str(state.get("edit_text") or ""))
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if mods & pygame.KMOD_SHIFT:
                    # 한 줄 창이므로 Shift+Enter 도 \\n 삽입
                    state["edit_text"] = te.insert(str(state.get("edit_text") or ""), "\\n")
                else:
                    _commit_edit(state, save_fn)
                return True
            nt, handled = te.keydown(str(state.get("edit_text") or ""), event)
            if handled:
                state["edit_text"] = nt
                return True
            return True
        return True

    return True


def draw_modal(screen, font, title_font, state, sw, sh) -> dict:
    ui = layout_ui(state, font, sw, sh)
    state["_layout"] = ui
    rows = state.get("rows") or []
    sw, sh = ui["sw"], ui["sh"]

    pygame.draw.rect(screen, (28, 30, 38), (0, 0, sw, sh))
    pygame.draw.rect(screen, (42, 46, 58), (0, 0, sw, HEAD_H))
    pygame.draw.line(screen, (90, 100, 120), (0, HEAD_H), (sw, HEAD_H))
    title = title_font.render("DIALOG  —  전체 SAY 대화", True, (255, 240, 200))
    screen.blit(title, (14, 10))
    msg = str(state.get("msg") or "")
    if msg:
        screen.blit(font.render(msg, True, (170, 210, 180)), (14, 28))
    pygame.draw.rect(screen, (70, 50, 50), ui["close"], border_radius=4)
    pygame.draw.rect(screen, (200, 140, 140), ui["close"], 1, border_radius=4)
    screen.blit(font.render("닫기", True, (255, 230, 230)), (ui["close"].x + 18, ui["close"].y + 8))

    # 컬럼 헤더 (가로 스크롤과 같이 움직임)
    hdr = pygame.Rect(0, HEAD_H, sw - SB_W, COL_HEAD_H)
    pygame.draw.rect(screen, (36, 40, 52), hdr)
    prev = screen.get_clip()
    screen.set_clip(hdr)
    hy = HEAD_H + 5
    screen.blit(font.render("이벤트", True, (200, 210, 230)), (ui["ev_x"] + 6, hy))
    screen.blit(font.render("#", True, (200, 210, 230)), (ui["idx_x"] + 8, hy))
    screen.blit(font.render("who", True, (200, 210, 230)), (ui["who_x"] + 6, hy))
    screen.blit(font.render("대사 (한 줄, 줄바꿈은 \\n)", True, (200, 210, 230)), (ui["tx_x"] + 6, hy))
    screen.set_clip(prev)
    pygame.draw.line(screen, (80, 88, 104), (0, hdr.bottom), (sw, hdr.bottom))

    body = ui["body"]
    pygame.draw.rect(screen, (24, 26, 32), body)
    screen.set_clip(body)
    sy = int(state.get("scroll_y") or 0)
    y0 = body.y - sy
    edit = state.get("edit")
    sel = int(state.get("selected") if state.get("selected") is not None else -1)
    blink = (pygame.time.get_ticks() // 400) % 2 == 0
    for i, row in enumerate(rows):
        ry = y0 + i * ROW_H
        if ry + ROW_H < body.y or ry > body.bottom:
            continue
        step = row.get("step") or {}
        bg = (32, 36, 46) if i % 2 == 0 else (28, 32, 40)
        if i == sel:
            bg = (48, 56, 40)
        pygame.draw.rect(screen, bg, (body.x, ry, max(body.width, ui["content_w"]), ROW_H))
        title = str(row.get("title") or "")
        eid = str(row.get("event_id") or "")
        sec = str(row.get("section") or "")
        ev_lab = f"{sec}  {title}"
        if title != eid:
            ev_lab = f"{sec}  {title}  [{eid}]"
        idx_lab = str(int(row.get("step_index") or 0) + 1)
        who_lab = str(step.get("who") or "") or "player"
        tx_lab = _say_one_line(step)

        ev_cell = pygame.Rect(ui["ev_x"], ry, ui["ev_w"], ROW_H)
        idx_cell = pygame.Rect(ui["idx_x"], ry, IDX_COL_W, ROW_H)
        who_cell = pygame.Rect(ui["who_x"], ry, ui["who_w"], ROW_H)
        tx_cell = pygame.Rect(ui["tx_x"], ry, ui["tx_w"], ROW_H)

        def _cell_text(cell, text, color):
            clip0 = screen.get_clip()
            screen.set_clip(cell.clip(body))
            try:
                img = font.render(str(text if text else " "), True, color)
            except Exception:
                img = font.render(" ", True, color)
            screen.blit(img, (cell.x + 6, ry + 6))
            screen.set_clip(clip0)

        _cell_text(ev_cell, ev_lab, (220, 200, 160))
        _cell_text(idx_cell, idx_lab, (160, 170, 190))
        pygame.draw.rect(screen, (40, 48, 42), who_cell)
        pygame.draw.rect(screen, (40, 42, 52), tx_cell)
        pygame.draw.rect(screen, (70, 80, 70), who_cell, 1)
        pygame.draw.rect(screen, (70, 75, 90), tx_cell, 1)

        editing_who = edit == (i, "who")
        editing_tx = edit == (i, "text")
        if editing_who:
            pygame.draw.rect(screen, (255, 210, 80), who_cell, 2)
            vis = str(state.get("edit_text") or "")
            te = state.get("text_edit")
            if isinstance(te, ed_txt.EditSession):
                te.blit(screen, font, vis, who_cell.inflate(-2, -2), color=(255, 255, 220), active=True)
            else:
                if blink:
                    vis = vis + "|"
                _cell_text(who_cell, vis, (255, 255, 220))
        else:
            _cell_text(who_cell, who_lab, (210, 230, 210))
        if editing_tx:
            pygame.draw.rect(screen, (255, 210, 80), tx_cell, 2)
            vis = str(state.get("edit_text") or "")
            te = state.get("text_edit")
            if isinstance(te, ed_txt.EditSession):
                te.blit(screen, font, vis, tx_cell.inflate(-2, -2), color=(245, 248, 255), active=True)
            else:
                if blink:
                    vis = vis + "|"
                _cell_text(tx_cell, vis, (245, 248, 255))
        else:
            _cell_text(tx_cell, tx_lab, (235, 238, 245))

    screen.set_clip(prev)

    # 스크롤바
    pygame.draw.rect(screen, (20, 22, 28), ui["vtrack"])
    if ui.get("vthumb"):
        pygame.draw.rect(screen, (110, 120, 140), ui["vthumb"], border_radius=3)
    pygame.draw.rect(screen, (20, 22, 28), ui["htrack"])
    if ui.get("hthumb"):
        pygame.draw.rect(screen, (110, 120, 140), ui["hthumb"], border_radius=3)
    return ui

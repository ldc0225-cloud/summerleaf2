# Cursor 세션 핸드오프 (summerleaf2)

다른 PC에서 Cursor Agent를 열 때 이 파일을 `@docs/cursor-handoff.md` 로 참조하면 맥락을 이어갈 수 있습니다.

**최종 갱신:** 2026-07-03 (야구 데모 + 원터치 입력)  
**관련 브랜치/상태:** 로컬 작업 중 — `git pull` / USB 동기화 후 이 문서와 diff를 함께 확인하세요.

---

## 이 세션에서 한 일 (요약)

### 야구장 데모 (bg_jjangpu → bg_baseball1) — **구현 완료·입력 튜닝 중**

표지판 상호작용으로 야구장 입장 → 캐릭터 선택 → 5타 → 상위 3타 합산 → 「다시 할래요?」 → 아니오 시 jjangpu 복귀.

| 항목 | 내용 |
|------|------|
| 입장 | `bg_jjangpu` `signpost01` [880, 2304] 상호작용 → `ev_baseball_demo` |
| 맵 | `bg_baseball1` — `baseballbat1` + `ball1` [176, 512], ball `height: 15` |
| 타자 위치 | plate [152, 512], 오른쪽 방향 (`batter_face: right`) |
| 모드 | `DEV_CMD start_baseball` + `mode: "demo"`, `return_map: "bg_jjangpu"`, `return_pos: [880, 2320]` |
| 스윙 애니 | `swing` 있을 때만 재생, 없으면 **idle 유지** (attack 폴백 없음) |
| 공 연출 | 맵 `ball1` 숨김 → 배트 위에서 포물선 비행 → 타석마다 복원 |

### 입력 정책 (안드로이드 원터치) — **최신**

- 야구 맵/활동 중 **캐릭터 이동 불가** (`blocks_field_move`, `_pin_batter`, `main.py`에서 `player.move` 차단)
- **키보드 단축키 없음** (야구 `on_primary_key` 비활성)
- **캐릭터 선택·게임 시작**: 화면 **버튼만** (버튼 밖 탭 무시)
- **타격 2단계** 모두 **공 터치**로 확정:
  1. 방향 단계 — 부채꼴 게이지가 자동 스윕, 캐릭터 좌/우(맵상 위/아래) 방향 연동 → **공 터치**로 방향 확정
  2. 파워 단계 — 가로 게이지 스윕(느리게) → **공 터치**로 스윙
- 파워 게이지 속도: `PWR_SWEEP_HZ` **0.95** (기존 2.2에서 감속)
- 공 터치 판정: 월드 반경 `BALL_TOUCH_RADIUS_PX` 36 + 화면 `_ball_screen_rect` 이중 체크

### UI/클릭 버그 수정 (이전 턴)

- 필드 활동 클릭을 **OVERLAY_UI보다 먼저** 처리
- 야구 메뉴는 **월드 줌 이후** `draw_screen` (클릭 좌표와 일치)
- `_layout_menu_rects()` — 그리기 전에도 버튼 hit 영역 계산
- `field_activity_request` **입력 처리 전** 소비
- 야구 중 글로벌/존 이벤트 재시작 차단
- `return_map` 종료 시 `main.py`에서 맵 로드·카메라 복귀
- `contact_confirm` 존: 플레이어가 존 안에 있으면 **탭 위치 무관** 발동 (`flow.py`)

### 이전에 구현된 야구 골격 (메뉴 모드)

- `story` / `record_1p` / `record_2p` 메뉴 (`mode` 생략 시 오버레이 메뉴)
- NPC 5타 시뮬, 2P 교대, tilt 압축, `save_patch`

### 기타 (참고)

- pushbutton 상호작용 아이콘 발 기준 아래 (`INTERACT_PROMPT_OFFSET_Y_PX` +14)
- presence/성능/ENTITY_ZOOM persist 등 이전 세션

---

## 데모 플레이 흐름

```text
bg_jjangpu signpost01 상호작용
  → ev_baseball_demo (FADE → MAP bg_baseball1 → CAMERA → start_baseball demo)
  → 캐릭터 선택 UI (다음 캐릭터 / 게임 시작 버튼만)
  → 5타 × (방향 게이지 + 공 터치 → 파워 게이지 + 공 터치 → 스윙)
  → 결과 (상위 3타 합) → 탭 → 「다시 할래요?」 예/아니오
  → 아니오: bg_jjangpu [880, 2320] 복귀
```

---

## 맵·오브젝트 좌표 (`world_data.json`)

### bg_jjangpu
```json
"signpost01": { "pos": [880, 2304], "interact": { "enabled": true, "range": 36,
  "bindings": [{ "event_id": "ev_baseball_demo", "priority": 100 }] } }
```

### bg_baseball1
```json
"start_pos": [152, 512],
"objects": [
  { "name": "baseballbat1", "pos": [176, 512] },
  { "name": "ball1", "pos": [176, 512], "height": 15 }
],
"event_zones": [
  { "name": "야구장_플레이", "rect": [32, 480, 120, 80],
    "trigger": "contact_confirm", "event_id": "ev_baseball_play" }
]
```

### `data.py` → `BASEBALL_FIELDS["bg_baseball1"]`
```python
"plate": [152.0, 512.0],
"tee": [176.0, 497.0],   # ball pos y - height(15)
"batter_face": "right",
```

---

## 이벤트 (`events.json`)

### `ev_baseball_demo` (표지판 → 데모)
```json
"steps": [
  { "type": "FADEOUT", "val": 0.4 },
  { "type": "MAP", "target": "bg_baseball1", "pos": [152, 512], "dir": "right" },
  { "type": "FADEIN", "val": 0.4 },
  { "type": "CAMERA", "mode": "fixed", "x": 220.0, "y": 500.0, "smooth": true, "duration_sec": 0.4 },
  { "type": "INTERVAL", "val": 0.25 },
  { "type": "DEV_CMD", "cmd": "start_baseball", "map": "bg_baseball1",
    "mode": "demo", "return_map": "bg_jjangpu", "return_pos": [880, 2320] }
]
```

### 기타
- `ev_baseball_play` — 존 안에서 contact_confirm → MOVE/CAMERA/OVERLAY_UI/start_baseball (메뉴 모드)
- `ev_baseball_enter` — 맵만 이동
- `ev_baseball_story` — `mode: story`

---

## 야구 코드 구조

### 패키지
| 패키지 | 용도 |
|--------|------|
| **`activities/`** | 맵 유지 필드 플레이 (fishing, **baseball**, 향후 카트 등) |

(예전 외부 `minigames/` 패키지·단독 데모는 제거. 본체는 activities만 사용.)

### 모드 (`activities/baseball.py`)
| mode | 설명 |
|------|------|
| **`demo`** | 캐릭터 선택 → 5타 → 상위3 합 → 재플레이 질문 → `return_map` 복귀 |
| `story` | NPC 대전, `progress_baseball_story` + 씨앗 |
| `record_1p` | NPC 기록 갱신 |
| `record_2p` | 2P 교대 |
| (생략) | 오버레이 메뉴에서 모드 선택 |

### 상태 머신 (주요)
```text
ST_PICK_CHAR → ST_BAT_DIR → ST_BAT_PWR → ST_SWING → ST_FLIGHT → ST_TURN_WAIT
  → (5타 후) ST_DEMO_RESULT → ST_REPLAY_ASK → ST_PICK_CHAR | ST_QUIT(return_map)
```

### 그리기 분리
- `draw_world` — 월드 줌 **전**: 공 대기(펄스 링)·비행
- `draw_screen` — 월드 줌 **후**: 메뉴·부채꼴/파워 게이지·결과 HUD

### 방향 게이지 ↔ 캐릭터
- `_update_batter_facing_from_gauge()`: 게이지 각도 → `player.direction` left/right
- 부채꼴 UI는 **세로형** (맵 위/아래 = 캐릭터 좌/우 시각화)
- 타구 carry는 기존처럼 `_locked_dir_deg` 수평 거리에 반영

---

## 연동 (`field_runtime.py` / `main.py`)

```text
DEV_CMD start_baseball → field_activity_request
main.py (입력 전) consume_request(objs=objs) → end_event, remove baseball_exit overlay
매 프레임: tick / on_pointer_down(screen, world) / draw_world + draw_screen
blocks_field_move() → 클릭·키 이동 차단, player.move 스킵
종료: result(return_map?) → pop_finished_result → save_patch / 맵 복귀
```

`start_baseball` params: `map`, `mode`, `return_map`, `return_pos`, `save_data`  
`host.consume_request(..., objs=objs)` — `ball1` FieldItem 바인딩용

---

## 수정된 파일 목록 (이 대화 전체)

| 파일 | 변경 |
|------|------|
| `activities/baseball.py` | demo 모드, 터치 입력, 공 터치, 방향 연동, draw 분리 |
| `activities/host.py` | `objs`, `draw_world`/`draw_screen`, `on_primary_key` |
| `activities/__init__.py` | 등록 (변경 적음) |
| `data.py` | `BASEBALL_FIELDS` 좌표, `PWR_SWEEP_HZ`, `BALL_TOUCH_RADIUS_PX` |
| `world_data.json` | signpost interact, bg_baseball1 오브젝트·start_pos |
| `events.json` | `ev_baseball_demo` |
| `main.py` | 입력 우선순위, 이동 차단, return_map, 야구 draw_screen |
| `field_runtime.py` | `return_map`/`return_pos` DEV_CMD 전달 |
| `flow.py` | `contact_confirm` 존 탭 완화 |

---

## 세이브 키 (`data.py`)

- `progress_baseball_story` / `progress_baseball_seed` — 스토리 모드
- `baseball_best_npc` — 1P NPC 최고 합산(px)
- `baseball_records` — 경기 로그 리스트

데모 모드는 기록 저장 최소 (스토리 플래그 없음).

---

## 에셋

| 경로 | 상태 |
|------|------|
| `assets/images/bg/bg_baseball1.png` | 있음 |
| `assets/images/bg/bg_baseball1_mask.png` | 있음 |
| `object_defs.json` | `ball1`, `baseballbat1`, `signpost01` |
| `char_defs` **swing** 애니 | 캐릭터별 있으면 사용, 없으면 idle |

---

## 미완 / 다음 작업 제안

- [ ] 실기(안드로이드)에서 공 터치 hit 판정 미세 튜닝 (`BALL_TOUCH_RADIUS_PX`, `_ball_screen_rect` pad)
- [ ] 데모 외 `ev_baseball_play` 존과 데모 `signpost` 경로 정리 (중복 입장 방지 UX)
- [ ] 2P / 스토리 모드에도 원터치·공 터치 규칙 통일 여부 결정
- [ ] NPC 캐릭터 맵 배치·스토리 이벤트 연결
- [ ] `baseball_records` UI
- [ ] 2P 교대 시 2P 스프라이트 맵 표시
- [ ] swing 애니 없는 캐릭터에 swing 세트 추가 (에디터/char_defs)

---

## 설계 원칙 (`principle.txt`)

1. 파일 파편화 최소 — 야구는 **`activities/baseball.py` 단일 파일** 중심
2. 기존 패턴 재사용 — `BaseFieldActivity`, `DEV_CMD`, `field_runtime`, fishing `_world_to_screen`
3. 섹션 주석으로 역할 명시
4. Android 빌드는 GitHub 프리셋

---

## 다른 PC에서 이어가기

```text
1. git pull (또는 작업 폴더 통째로 복사)
2. Cursor → summerleaf2 열기
3. @docs/cursor-handoff.md 첨부 후 예시:
   "야구 데모 공 터치 판정이 안 맞아. 튜닝해 줘"
   "스토리 모드도 데모랑 같은 원터치 규칙으로 통일해 줘"
   "2P 모드에서 두 번째 캐릭터 스프라이트 보여 줘"
```

### 로컬 실행
```bash
py main.py
```
표지판(880, 2304 근처) → 야구장 → 버튼으로 캐릭터·시작 → 공 터치로 타격.

---

## 주요 파일 빠른 링크

| 경로 | 내용 |
|------|------|
| `activities/baseball.py` | 야구 로직·데모·터치 입력 |
| `activities/host.py` | 세션 호스트 |
| `main.py` | 루프, field_activities, 이동 차단, return_map |
| `field_runtime.py` | `start_baseball` / `stop_baseball` |
| `flow.py` | 존·interact·pushbutton 위치 |
| `data.py` | `BASEBALL_*` 튜닝 |
| `world_data.json` | 맵·오브젝트·signpost |
| `events.json` | `ev_baseball_demo` 등 |
| `object_defs.json` | ball1, baseballbat1 |
| `principle.txt` | 설계 대전제 |

---

## 알려진 이슈 (집 PC에서 확인할 것)

1. **클릭이 안 먹히던 문제** — 여러 겹 수정함; 여전히 이상하면 `render_xform_for_input`·논리 해상도(320/640) 불일치 의심
2. **이벤트 중 입력** — `active_event`여도 야구 `on_pointer_down` 우선 (이벤트 블록 안)
3. **`baseball_exit` OVERLAY** — `ev_baseball_play` 경로만 생성; 데모 시작 시 `remove_ui_overlay("baseball_exit")` 호출
4. **맵 ball1** — 비행 중 `is_visible=False`, `draw_world`에서 별도 그리기

---

*이 문서는 Cursor Agent 대화(야구 데모·입력·핸드오프) 내용을 바탕으로 작성됨.*

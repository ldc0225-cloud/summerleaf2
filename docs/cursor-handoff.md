# Cursor 세션 핸드오프 (summerleaf2)

다른 PC에서 Cursor Agent를 열 때 이 파일을 `@docs/cursor-handoff.md` 로 참조하면 맥락을 이어갈 수 있습니다.

**최종 갱신:** 2026-06-29  
**관련 브랜치/상태:** 로컬 작업 중 — `git pull` 후 이 문서와 diff를 함께 확인하세요.

---

## 이 세션에서 한 일 (요약)

### 기능·버그
1. **`presence_zones`** — 맵 체류 구역 (에디터 MAP 탭 **PRE**), 런타임·에디터 UI 완성
2. **presence 버그 수정** — `shear_on: false` bool 파싱, `player.move()` 후 layer 재적용, 구역 **진입 시 shear도 보간**(즉시 스냅 제거)
3. **`OVERLAY_UI` 트랙 타이밍** — `overlay_id` / `hold` / `delay` 의미 정리 및 엔진 구현
4. **`ev_gl_demo_02`** — 데모 이벤트 스텝 순서·target 수정
5. **에디터** — 이벤트 스텝 **맨 앞 `+` 삽입**
6. **낚시 HUD** — 빈 `_msg`일 때 `Font.render("")` 방지 (`Text has zero width` 에러)

### 성능 (기능·화면 100% 유지 전제)
7. **일반 렌더 루프** — dead code, presence 1× tick, 맵 캐시, draw `copy()` 축소, LRU 등 (`main.py` / `flow.py` / `engine.py` / `field_runtime.py`)
8. **쉬어(shear) 전용 2단계** — (1) dx 병합·공통 함수 (2) **뷰포트 스트립 쉬어** + pin 캐시 + 쉬어 캐시 우선 경로  
   → 1단계만으로는 **체감 거의 없음** (이미 캐시 히트 시 루프 미실행). 2단계가 실질 타겟.

---

## 1. presence_zones (체류 존)

### 목적
`event_zones`는 **진입 1회** 트리거. 플레이어가 rect 안에 **있는 동안** tilt/shear/캐릭터·오브젝트 상태를 유지하고, 나가면 복구.

### 데이터 (`world_data.json`)
```json
"presence_zones": [{
  "name": "...",
  "rect": [x, y, w, h],
  "conditions": {},
  "field": { "tilt_target", "shear_on", "shear_strength", "shear_max_px" },
  "player": { "layer", "sprite_tilt", "height", ... },
  "targets": [{ "name": "obj_name", ...TUNE 필드 }]
}]
```

- `field.shear_on: false` → 구역 안에서 shear **끔** (`bool false` 파싱 수정됨)
- `player.layer` 등 → 체류 중 **매 프레임** 재적용 (`player.move()`가 마스크 layer를 덮어쓰기 때문)
- **진입·이탈 모두** shear는 `SHEAR_SMOOTH_SPEED` 보간 (진입만 즉시 스냅하던 동작 제거)

### 주요 파일
| 파일 | 역할 |
|------|------|
| `flow.py` | `PresenceZoneRuntime`, `compile_presence_zone_overlays()`, `pick_presence_zone_index` |
| `char_editor_ui.py` | `PresenceZoneModal` (기본/화면/플레이어/지정 오브젝트 탭) |
| `editor.py` | PRE 도구, rect 드래그, 저장 |
| `main.py` | `presence_rt.tick()` — **`player.move()` 루프 후 1회** (이전 중복 tick 제거) |

### 설계 원칙 (`principle.txt`)
- 파일 쪼개기 최소화, `bg_zones` / TUNE / `_ConfigModal` 패턴 재사용
- `presence_zones` 키는 `event_zones`와 분리

### 테스트 맵
`bg_jjangpu` — `jjangpu_stair1`, `jjangpu_stair2` 등 (rect는 에디터에서 조정)

---

## 2. OVERLAY_UI 트랙 타이밍

### 의미 (중요)
| 필드 | 의미 |
|------|------|
| **`overlay_id`** | **트랙** 이름. 같은 id = 순서 재생, 다른 id = 병렬 |
| **`hold`** | 이 스텝에서 화면에 **보이는 시간** (appear/disappear 제외) |
| **`delay`** | **같은 id**에서 **이전 연출이 끝난 뒤** 기다리는 초. 스크립트는 **멈추지 않음** |

`WAIT` / `INTERVAL`은 이벤트 스텝 진행을 막음. 오버레이 연출만 예약하려면 `OVERLAY_UI` + `delay`/`hold` 사용.

### 엔진 (`engine.py`)
- `_overlay_track_free_at` — 트랙별 다음 스텝 가능 시각
- `_ui_overlay_pending` — 예약 큐
- `_dispatch_overlay_ui_step()` — 스텝 실행 시 트랙 스케줄만 등록, `next_step()` 즉시

---

## 3. ev_gl_demo_02 (데모 이벤트)

### 수정된 핵심
- **`CHANGE`** → 플레이어 **외형만** `char_defs`로 변경
- **`MAP` 뒤에 `CHANGE`** — `MAP`이 `load_map()`으로 플레이어를 재생성
- **MOVE/CAMERA/FOLLOW의 target** → 주인공은 **`"player"`**
- **뒷부분(루프·오버레이)** 은 사용자가 계속 손볼 예정

---

## 4. 에디터

- MAP 도구: **OBJ / EVT / BG / PRE** 네 가지
- 이벤트 스텝: **맨 앞 `+`**, 스텝 사이 `+`, 맨 아래 `+ ADD STEP`

---

## 5. 성능·쉬어 최적화 (2026-06-29)

### 현재 `data.py` 부담이 큰 조합
```text
TILT_SHEAR_ENABLED: True
TILT_SHEAR_SCALE_WITH_TILT: False   → 틸트 평면이어도 쉬어 100%
TILT_SHEAR_TOP_PX: 128              (주석 권장 24~48과 다름)
TILT_SHEAR_SLICE_H_PX: 2            → 캐시 미스 시 슬라이스 매우 촘촘
```
`bg_jjangpu` 맵: **1536×2560**. 화면 쉬어 128px → 맵 픽셀 기준 **약 683px** shear.

### 왜 “쉬어 최적화했는데 똑같다”고 느꼈는지
| 상황 | 병목 |
|------|------|
| **캐시 히트** (정지·좌우 팬, 줌 고정) | 쉬어 **재계산 루프는 안 돎** → blit 1~2회만. dx 병합은 **미스 때만** 효과 |
| **캐시 미스** (줌·쉬어 토글·LRU 축출) | **전체 2560px** tilt+shear 재빌드 + 마스크 알파 합성 |
| **원근 분기 ON** | 모든 스프라이트 `y_transform` / `x_offset_fn` (쉬어 끄기와 체감 차이의 주원인) |

### 적용된 코드 (요약)

**`engine.py`**
- `vertical_top_shear_merged_plan` / `apply_vertical_top_shear` — 배경·마스크 공통, **동일 dx 행 blit 병합** (픽셀 동일 검증됨)
- `vertical_top_shear_merged_plan_region` / `apply_vertical_top_shear_region` — **화면에 보이는 행 구간만** 쉬어
- `shear_strip_row_span()` — 스트립 `[r0,r1)` + bucket(기본 128px)으로 수직 팬 시 캐시 재사용
- `_SPRITE_FIELD_SHEAR_CACHE` — `sprite_tilt<1` 오브젝트 전역 LRU
- `_shear_surface_by_field_xoffset` — 슬라이스 blit 병합

**`main.py`**
- `_shear_pin_cache` — `bg_shear` / `mask_shear` (및 strip 키) LRU 축출 방지
- `_rc_zkey(z)` — 캐시 키에 스냅 줌 사용 (`cam.current_zoom` float 흔들림 완화)
- **쉬어 캐시 히트 시** tilt 단계·`tilt_bg_tmp` 대형 blit 생략
- **`bg_shear_strip` / `mask_shear_strip`** — 맵 높이 > `2×HEIGHT` 일 때 자동 (jjangpu 해당)
- `frame_shear_field_h` — 입력 역변환용 높이 (캐시 히트 시 `tilt_bg_tmp` 잔상 버그 방지)
- `shift_y` 하단 보정: `comp_h` = `sh2_est` (캐시 히트 시 `tilt_bg_tmp` 높이 0 버그 수정)

**`flow.py`**
- `compile_presence_zone_overlays()` — 존 패치 1회 컴파일
- 활성 존 rect short-circuit, `presence_zones` 없는 맵 early return

**`activities/fishing.py`**
- `if self._msg and str(self._msg).strip():` — 빈 HUD render 스킵

### 성능 측정 방법
```python
# data.py
"PERF_PROFILER_ENABLED": True,
"PERF_PROFILER_DETAIL": True,
"PERF_PROFILE_LOG_ENABLED": True,
"DRAW_TOPN_ENABLED": True,   # 선택: 무거운 FieldItem
```
- `bg_anim` / `mask_anim` — 쉬어·틸트 **재빌드** 구간
- `bg` / `mask` — 정상 플레이(캐시 히트) 구간
- 여전히 느리면 `obj_draw`, `world_zoom` 비교

### 선택 CONFIG (스트립, 기본값으로 jjangpu에 자동 ON)
| 키 | 기본 | 의미 |
|----|------|------|
| `TILT_SHEAR_STRIP_PAD_PX` | 64 | 스트립 상하 여유 |
| `TILT_SHEAR_STRIP_BUCKET_PX` | 128 | 수직 위치 양자화(캐시 키) |

### 아직 안 한 것 / 다음 후보
- [ ] `BG_VIEWPORT_BLIT_ENABLED: True` + 원근 — vp 좌표가 캐시 키에 들어가 **팬마다 미스** (별도 최적화 필요)
- [ ] `PERF_PROFILER`로 실측 후 `obj_draw` vs `bg` 병목 확정
- [ ] numpy 등 bulk shear (미스 시만, 선택)
- [ ] `DRAW_CULL` 기본 ON — 사용자 승인 전 비권장 (가장자리 이슈)

---

## 6. 알려진 제약 / 미완

- [ ] `ev_gl_demo_02` 두 번째 TITLE — `"delay": 2.0` 등 JSON 사용자 조정 중
- [ ] presence zone rect·layer — 맵/마스크에 맞게 에디터에서 재조정
- [ ] CHANGE 플레이어 캐릭터 영구 저장 미구현
- [ ] 쉬어 체감 — strip+pin 적용 후에도 느리면 **프로파일 로그** 공유 필요
- [ ] Cursor 채팅은 PC 간 동기화 없음 → **이 파일 + Git**

---

## 7. 다른 PC에서 이어가기

```text
1. git pull  (또는 clone)
2. Cursor로 summerleaf2 폴더 열기
3. 새 Agent 채팅에서:
   @docs/cursor-handoff.md 를 붙이고
   "이어서 ○○ 해줘" 라고 요청
```

예시 프롬프트:
> `@docs/cursor-handoff.md` 참고해서 PERF 로그 기준으로 쉬어가 여전히 느린 원인 더 줄여 줘.

> `@docs/cursor-handoff.md` 참고해서 `ev_gl_demo_02` 루프·오버레이 타이밍 마저 다듬어 줘.

---

## 8. 주요 파일 빠른 링크

| 경로 | 내용 |
|------|------|
| `flow.py` | PresenceZoneRuntime, overlay 패치, `compile_presence_zone_overlays` |
| `engine.py` | OVERLAY_UI, 쉬어 API (`apply_vertical_top_shear*`), 스프라이트 shear LRU |
| `main.py` | 게임 루프, `_render_cache`, `_shear_pin_cache`, bg/mask tilt·shear |
| `char_editor_ui.py` | PresenceZoneModal |
| `editor.py` | PRE, 이벤트 스텝 UI |
| `activities/fishing.py` | 낚시 HUD, empty msg 가드 |
| `activities/host.py` | activity draw 예외 → `[activity] draw error` |
| `events.json` | `ev_gl_demo_02` 등 |
| `world_data.json` | `presence_zones` per map |
| `data.py` | shear/tilt CONFIG, `PERF_PROFILER_*` |
| `principle.txt` | 파일 파편화 최소·기존 함수 재사용 |

---

## 9. 쉬어 렌더 파이프라인 (디버깅용)

```text
s_bg = full_scale(bg, z)           [_rc_get_full_scale]
  → s_bg2 = tilt scale (f_q)       [bg_tilt cache]
  → tilt_bg_tmp                    [쉬어 미스 때만 blit]
  → shear (전체 또는 strip)        [bg_shear / bg_shear_strip + pin]
  → render_surf.blit (blit_x, blit_y + strip_r0)

마스크: 동일 구조 (mask_tilt, mask_shear_strip), alpha 120
스프라이트: x_offset_fn 선형 필드 + shear_base_offset_px (SHEAR_SPRITE_STABILIZE)
```

캐시 키 (전체 맵): `("bg_shear", id(bg), zk, f_q, shear_eff, slice_h)`  
스트립: `("bg_shear_strip", id(bg), zk, f_q, shear_eff, slice_h, r0, r1)`

# 여름이 엔진 에디터 사용 메뉴얼

맵 배치, 이벤트(컷신·대화), NPC 설정을 하는 통합 에디터입니다.  
저장 대상은 주로 **`world_data.json`**, **`events.json`**, **`char_defs.json`** 입니다.

---

## 1. 실행

프로젝트 폴더에서:

```bash
python editor.py
```

창 제목: **「여름이 엔진 에디터 - 이벤트 기능 확장 버전」**

---

## 2. 화면 구성

```
┌──────────────┬─────────────────────────────┬──────────────┐
│  좌측 사이드  │      중앙 작업창 (맵)        │  우측 사이드  │
│  (도구/목록)  │      줌·팬·배치·존          │  (에셋/스텝)  │
├──────────────┴─────────────────────────────┴──────────────┤
│  상단: MAP / EVENT 모드 전환 · 맵 탭 · PNG보내기        │
└──────────────────────────────────────────────────────────┘
```

| 영역 | 역할 |
|------|------|
| **상단 왼쪽** | `MAP` / `EVENT` / `FLOW` 모드 전환 |
| **상단 중앙** | 맵 목록 탭 · **PNG보내기** 버튼 |
| **좌측 (MAP)** | OBJECTS / ZONES / BGZONES 도구, 배치 목록 |
| **좌측 (EVENT)** | 로컬·글로벌 이벤트 목록 |
| **좌측 (FLOW)** | 맵에 배치된 NPC·오브젝트 목록 (MAP과 동일 분류) |
| **중앙** | 맵 편집 / 이벤트 스텝 좌표 픽 / FLOW 차트 |
| **우측 (MAP)** | 오브젝트·NPC 카테고리·썸네일 |
| **우측 (EVENT)** | 스텝 타입·필드 편집·스텝 목록 |
| **우측 (FLOW)** | *(숨김 — 차트는 중앙)* |

---

## 3. 공통 조작

| 조작 | 설명 |
|------|------|
| **마우스 휠** | 좌·우 사이드바 목록 스크롤 · **설정 모달** 본문 스크롤 · FLOW 차트 세로 스크롤 |
| **Shift + 휠 (FLOW)** | FLOW 차트 가로 스크롤 |
| **작업창 드래그** | 맵 이동(팬) · FLOW 차트 이동 |
| **줌** | 우측/설정된 줌 단계 (게임과 동일 계열) |
| **Shift 누름** | 격자 스냅 해제(미세 배치·좌표 픽) |
| **S** | **맵 + 이벤트 통합 저장** (`world_data.json`, `events.json`) |
| **M** | 이동 마스크 표시 on/off |
| **F7** 또는 **Ctrl+Shift+E** | 현재 맵을 `exports/` 에 PNG로보내기 |
| **F8** | 우측 썸네일 스케일 방식 토글(픽셀 ↔ 부드럽게) |
| **Esc** | 모달·픽 모드·선택 해제 |

**목록 접기:** 좌측(MAP·FLOW)·우측(에셋) 카테고리 헤더 클릭으로 접기/펴기. 상태는 `editor_ui_state.json`에 저장되어 에디터를 다시 열어도 유지됩니다.

> 텍스트 입력 중에는 **S, F7** 등이 필드에 들어갈 수 있습니다. 단축키는 필드 포커스를 해제한 뒤 누르세요.

### 3.1 설정 창(모달) 스크롤 — 모든 창 동일

이벤트 설정, 이벤트 박스, NPC/오브젝트 설정, 스텝 설정 등 **모든 팝업**은 같은 방식입니다.

| 조작 | 동작 |
|------|------|
| **마우스 휠** | 창 위·본문·드롭다운 목록 위에서 위아래 스크롤 |
| **오른쪽 스크롤바 — 트랙 클릭** | 클릭한 위치로 바로 이동 |
| **오른쪽 스크롤바 — 썸 드래그** | 원하는 위치까지 끌어서 이동 |
| **List 버튼 드롭다운** | 목록이 길면 같은 방식으로 휠·스크롤바 사용 |

모달 하단에 `마우스 휠=위아래 스크롤 · 오른쪽 막대=클릭(이동) 또는 드래그` 안내가 표시됩니다.

---

## 4. MAP 모드 — 맵 편집

### 4.1 도구 (좌측 상단 3버튼)

| 도구 | 용도 |
|------|------|
| **OBJECTS** | 오브젝트·NPC 배치·이동·다중 선택 |
| **ZONES** | 이벤트 발생 **사각 영역** (플레이어 접촉 등) |
| **BGZONES** | 원경/배경 묶음 (틸트 시에만 그리기 등) |

### 4.2 OBJECTS

1. 우측에서 카테고리·에셋 선택  
2. 작업창에 **드래그**하여 배치  
3. 기존 것 **클릭** 후 드래그로 이동  
4. **Ctrl+클릭** 등으로 다중 선택 → **Delete** 로 삭제(확인 있음)  
5. NPC 선택 시 하단 **「타입 기본값」** / **「인스턴스」** 로 대화·행동 편집 (`char_defs.json`, `world_data.json`)

### 4.3 ZONES (이벤트 박스)

1. **Add Event Box** → 이름·이벤트 ID·트리거·조건 입력  
2. **영역 지정**으로 맵 위 사각형 드래그  
3. 트리거 예: `contact_player`, `contact_object` 등  
4. 저장 시 해당 맵의 `event_zones` 에 기록

### 4.4 BGZONES (배경 박스)

원경 오브젝트 묶음·레이어·틸트 시에만 그리기 등을 지정할 때 사용합니다.

### 4.5 맵 전환

상단 중앙 **맵 탭** 클릭 → `world_data.json` 에 등록된 맵 로드.

### 4.6 NPC·오브젝트 설정 모달 (초보자용 요약)

맵에서 NPC/오브젝트를 선택한 뒤 하단 버튼으로 엽니다. 각 섹션은 게임 흐름 순서 **[C]→[D]→[A]→[B]** 로 읽으면 이해하기 쉽습니다.

| 구분 | 의미 | 저장 위치 |
|------|------|-----------|
| **[C] spawn_state** | 맵을 **처음 열 때** 보이는 모습 (애니, 방향, visible) | `char_defs` / `object_defs` 또는 맵 인스턴스 |
| **[D] progress_apply** | **세이브의 progress 숫자**에 따라 자동으로 모습 변경 (`when` 조건) | 동일 |
| **[A] bindings** | **클릭**했을 때 조건 맞으면 `events.json` 이벤트 실행 | `interact.bindings` |
| **[B] talk** (NPC만) | 말 걸기 **일상 대사** (클릭 이벤트와 별개) | `talk` |

- **타입 기본값** = 이 NPC/오브젝트 종류 전체에 공통 (`char_defs.json`, `object_defs.json`)
- **맵 인스턴스** = 이 맵에만 덮어쓰기 (`world_data.json`). 비우면 타입 기본값 사용
- `visible: false` 인 NPC는 플레이 중 안 보이지만, 에디터에서는 **반투명 윤곽**으로 표시됩니다

### 4.7 FLOW 모드 — 연결 흐름 한눈에 보기

상단에서 **FLOW** 를 선택하면 맵에 있는 NPC·오브젝트와 이벤트·progress 의 관계를 **차트**로 봅니다.

1. **좌측** — `char_defs`·`object_defs` **전체 타입** + **현재 맵 event_zones** (이벤트 박스)
2. 맨 위 **「★ 이벤트 연결」** — bindings·event_id 가 있는 NPC·오브젝트·이벤트 박스만 모아 둔 카테고리 (접기/펴기·저장 가능)
3. **중앙** — 선택한 대상의 흐름도: `엔티티 → binding(클릭 조건) → 이벤트 → progress 결과`
4. 목록에서 항목 클릭 → 차트 갱신 · 차트의 상자 클릭 → 해당 **설정 모달** 열기
5. **휠** = 차트 세로 스크롤 · **Shift+휠** = 가로 · **드래그** = 차트 이동

우측 패널은 FLOW 에서 숨겨지고, 작업 공간은 중앙 차트가 사용합니다.

---

## 5. EVENT 모드 — 이벤트 편집

### 5.1 이벤트 종류

| 종류 | 설명 |
|------|------|
| **LOCAL** | 특정 맵·존에서만 쓰는 이벤트 |
| **GLOBAL** | `auto` / `global` / `intercept` 트리거, 조건식, 우선순위, `work_map`(에디터 미리보기 맵) |
| **SYNC** | **맵 로드·맵 변경 직후** progress 조건으로 자동 실행 (주로 `PLACE`로 월드 복원). `work_map`·`condition`·`priority` |
| **FRAGMENTS** | steps만 있는 **템플릿** (직접 자동 실행 없음). `CALL_EVENT` 로 호출 가능 |

**진행 변수 저장:** 이벤트 `result`의 **Result Opt(JSON)** 에 `"progress_flower_1": 1001` 처럼 임의 키를 넣으면 `save_data.json` 최상위에 저장됩니다. 맵에 개체 좌표는 저장하지 않고, 다음 실행 시 **SYNC** 이벤트가 조건에 맞으면 `PLACE`로 배치합니다.

### 상호작용 → progress → 이벤트 (이벤트존 없이)

NPC/오브젝트 클릭 시 `interact.bindings` 를 `mainprogress`·`progress_*` 등과 비교해 `events.json` 이벤트를 실행합니다.

| 설정 위치 | 에디터 |
|-----------|--------|
| NPC 타입 | 맵에서 NPC 선택 → **타입 기본값** → `Interact bindings` |
| NPC 맵만 | **인스턴스** → interact 필드 |
| 오브젝트 타입 | **타입 interact** → `object_defs.json` |
| 오브젝트 맵만 | **맵 interact** → `world_data` `objects[].interact` |

bindings 한 줄: `조건식 | event_id | priority` (조건 비우면 항상 참, priority 생략 시 100).  
조건 문법은 GLOBAL `condition` 과 동일 (`mainprogress == "010200"`, `progress_flower_1 == 1001` 등).  
매칭 없으면 NPC는 기존 `talk`, 오브젝트는 들기(CARRY)로 폴백합니다.

**CALL_EVENT 스텝:** `target` = `LOCAL` / `GLOBAL` / `SYNC` / `FRAGMENTS` 아무 이벤트 ID. 호출한 이벤트의 `result`는 끝날 때 세이브에 반영된 뒤 부모로 복귀합니다. 순환·깊이 초과는 런타임에서 감지합니다(최대 깊이 8).

**새 이벤트 / 설정** 버튼으로 ID·제목·결과(`result`)·조건을 편집합니다.

### 5.2 스텝 편집 흐름

1. 좌측에서 이벤트 선택  
2. 우측 **스텝 목록**에서 스텝 선택 또는 **타입 추가**  
3. 필드 입력 후 **저장(삽입/수정)**  
4. **S** 로 `events.json` 저장  

작업창에는 선택 스텝까지의 **MOVE·PLACE 경로 미리보기**가 표시됩니다.

### 5.3 좌표 찍기 (Pos / 웨이포인트)

- **Pos X/Y** 옆 **맵에서 찍기** → 작업창 클릭으로 좌표 설정  
- **WP+** → 웨이포인트를 맵에서 **연속 추가** (`;` 로 구분된 문자열로 저장)  
- **Esc** → 픽 모드 취소  

### 5.4 시간 단위 (중요)

대기·페이드·연출 전환은 **초(sec)** 기준입니다.

| 스텝 | 시간 필드 |
|------|-----------|
| WAIT / INTERVAL | `val` (초) |
| FADEIN / FADEOUT | `val` (초) |
| SAY | `val` (자동 진행 대기 등) |
| TILT / SHEAR / ZOOM | `duration_sec` (**0 = 즉시**) |
| CAMERA | `duration_sec` (이동·전환) |
| MUSIC_PLAY | `fade_in` |
| MUSIC_STOP | `fade_out` |

---

## 6. 연출 스텝 — TILT / SHEAR / ZOOM (통일 형식)

세 타입 모두 같은 개념으로 씁니다.

| 필드 | 의미 |
|------|------|
| **on** | `true` = 효과 켜기, `false` = 끄기(기본·평면·1x) |
| **strength** | `0.0` ~ `1.0` (0=없음, 1=최대) |
| **duration_sec** | 목표까지 걸리는 시간(초). **0이면 즉시** |

### TILT (세로 압축)

- **strength 0** → 화면 평면(압축 없음)  
- **strength 1** → `data.py`의 `TILT_FACTOR_MIN` 까지 최대 기울임  

에디터 필드: `tilt_on`, `tilt_strength`, `tilt_duration_sec`

### SHEAR (위쪽이 오른쪽으로 밀림)

- **strength** 가 쉬어 강도 (`TILT_SHEAR_TOP_PX` 에 비례)  
- 선택: `shear_px` 로 최대 픽셀 직접 지정  

에디터 필드: `shear_on`, `shear_strength`, `shear_duration_sec`, `shear_px`(선택)

### ZOOM

| Target | 동작 |
|--------|------|
| **비움** | **카메라(월드)** 전체 줌 |
| **player** / NPC·오브젝트 이름 | 해당 스프라이트만 줌 |

- **on** `false` → 1배(기본)로 복귀 → **640 출력** (`AUTO_OUTPUT_MODE` 켜져 있을 때)  
- **strength** `0`~`1` → 640 기준 줌 `1.0`~`WORLD_ZOOM_MAX`(기본 **2.0**)  
- **strength 1.0** = 줌 2.0 = **320 출력**(해상도 반감 + 업스케일, 체감 2배와 동일)  
- **strength 0 / on false** = 줌 1.0 = **640 출력**  
- **duration_sec** → **실제 시간(초)**. `1.0`이면 1초 후 목표에 도달  

에디터 필드: `zoom_on`, `zoom_strength`, `zoom_duration_sec`, `target`(선택)

**연속 배치:** `ZOOM` → `TILT` → `SHEAR` 처럼 `WAIT` 없이 이어 붙이면 **같은 시각에 시작**하고, 각각 `duration_sec` 후에 끝납니다.

### 예시

```json
{ "type": "TILT", "on": true, "strength": 0.8, "duration_sec": 1.0 }
{ "type": "SHEAR", "on": true, "strength": 0.5, "duration_sec": 1.0 }
{ "type": "ZOOM", "on": true, "strength": 1.0, "duration_sec": 1.0 }
```

> 구형 JSON (`val`, `factor`, `speed` 등)은 열 때 자동 변환됩니다. 저장 시 `on` / `strength` / `duration_sec` 만 남습니다.

---

## 7. CAMERA 스텝

| mode | 설명 |
|------|------|
| `follow_player` | 플레이어 추적 (기본) |
| `follow_entity` | `cam_target` 이름 추적 |
| `fixed` / `fixed_world` | `cam_x`, `cam_y` 고정 좌표 |
| `lock_here` / `camera_lock_here` | **현재 카메라 위치** 고정 |
| `save_camera` | 현재 위치를 `cam_slot` 에 저장 |
| `load_camera` | 저장된 슬롯 위치로 이동 |

| 필드 | 설명 |
|------|------|
| `smooth` | `true` / `false` |
| `duration_sec` | 목표까지 이동·전환 시간(초) |
| `lerp` | (구형) 0~1 보간. 비우면 `duration_sec` 우선 |

쉬어가 켜진 상태에서는 플레이어 가로 중앙 보정(`SHEAR_PLAYER_CENTER_CAM_ENABLED`)이 적용됩니다. `fixed_world` 일 때는 화면이 밀리지 않도록 보정이 꺼집니다.

---

## 8. 자주 쓰는 스텝 요약

| 타입 | 요약 |
|------|------|
| **MOVE** | 이동. `waypoints`, `move_sync`(같은 문자열이면 전원 도착까지 동시 진행), `speed` 배율 |
| **PLACE** | 등장. `action: remove` 로 제거 |
| **TUNE** | 이미 있는 대상의 tilt/height/layer/visible/alpha 만 변경 |
| **SAY** | 대화. `who`, `text`, `bubble` |
| **WAIT** | N초 대기 후 다음 스텝 |
| **FADEIN / FADEOUT** | 화면 페이드(논블로킹, 초) |
| **LOOP_START / LOOP_END** | 루프 |
| **FOLLOW_START / STOP** | NPC 따라가기 |
| **MUSIC_*** | BGM 재생·정지·페이드 |
| **DEV_CMD** | 디버그 명령 (필드 테스트용) |
| **EVT_STOP_BEGIN / END** | 이벤트 중 스킵 입력 허용 구간 |

---

## 9. NPC · 대화 설정

맵에서 **NPC 하나 선택** → 하단:

| 버튼 | 저장 위치 | 내용 |
|------|-----------|------|
| **타입 기본값** | `char_defs.json` | 타입 공통: 대화, 기본 behavior |
| **인스턴스** | `world_data.json` | 이 맵 배치만: waypoints, behavior 덮어쓰기 |

게임 중 NPC 클릭 대화는 `char_behavior.py` + 인스턴스 설정으로 동작합니다.

---

## 10. 필드 플레이 테스트

에디터는 **맵·이벤트 데이터 편집**이 주 목적입니다. 실제 플레이는:

```bash
python main.py
```

으로 실행한 뒤, 배치·존·이벤트가 의도대로인지 확인하세요.

**게임 중 디버그 핫키** (`data.py` → `GLOBAL_EVENT_HOTKEYS`, `events.json` 의 `ev_hotkey_*`):

| 키 | 기능 |
|----|------|
| L | 틸트 데모 토글 |
| R | 쉬어 on/off (필드 기본 쉬어가 켜져 있을 때 억제 토글) |
| X | 줌 순환 |
| M | 마스크 표시 |
| O | 오버레이 HUD |

---

## 11. data.py 와 연출 기본값

필드 **기본** 쉬어·틸트는 `data.py` 에서 조절합니다 (이벤트 스텝과 별개).

| 설정 | 의미 |
|------|------|
| `TILT_SHEAR_ENABLED` | 필드 기본 쉬어 |
| `TILT_SHEAR_SCALE_WITH_TILT` | `false`면 틸트 없이도 쉬어 전체 강도 적용 |
| `FIELD_PERSPECTIVE_DEFAULT_ON` | 시작 시 틸트 on |
| `TILT_SHEAR_TOP_PX` | 쉬어 최대 px |

이벤트 스텝은 **컷신·구간 연출**용, `data.py` 는 **평소 필드 화면**용으로 나누어 생각하면 됩니다.

---

## 12. 문제 해결

| 증상 | 확인 |
|------|------|
| 연출이 안 바뀜 | `on`, `strength`, `duration_sec` 확인. **S** 로 저장했는지 |
| TILT만 켰는데 쉬어가 안 보임 | `TILT_SHEAR_SCALE_WITH_TILT` / `TILT_SHEAR_ENABLED` |
| 핫키가 안 먹음 | 다른 이벤트(대화) 진행 중 · IME 포커스 |
| 좌표가 어긋남 | 틸트/쉬어 중에는 픽 시 **Shift** 로 미세 조정 |
| 구형 스텝이 섞임 | 에디터에서 해당 스텝 열고 다시 저장 → `on/strength/duration_sec` 형식으로 통일 |

---

## 13. 관련 파일

| 파일 | 내용 |
|------|------|
| `editor.py` | 에디터 본체 |
| `events.json` | 이벤트·스텝 |
| `world_data.json` | 맵·오브젝트·NPC·존 |
| `char_defs.json` | 캐릭터 타입·spawn_state·progress_apply·talk |
| `object_defs.json` | 오브젝트 타입·spawn_state·progress_apply |
| `char_behavior.py` | NPC 정의 병합·대사·**progress 상태 적용** |
| `flow.py` | 상호작용 bindings·`build_obj_def`·맵 로드 |
| `field_runtime.py` | 틸트/쉬어/줌 파싱·핫키·카메라 명령 |
| `data.py` | 전역 CONFIG |

---

## 14. Progress 상태 (spawn_state / progress_apply)

세이브 `progress_*` 기준으로 캐릭터·오브젝트 보이기/애니/외형을 맞춥니다.  
구현: `char_behavior.py` (`apply_map_progress_states`) · `flow.py` (`load_map`, `try_start_interact_event`).

**적용 시점:** 맵 로드 직후 · 이벤트 종료 후 · binding 인라인 클릭 시

### spawn_state — 초기값 (`progress_apply`보다 먼저)

`char_defs.json` / `object_defs.json` / `world_data` 인스턴스:

```json
"spawn_state": { "visible": false, "dir": "left" }
```

| 필드 | 설명 |
|------|------|
| `visible` | NPC·오브젝트 표시 여부 |
| `spawn` | `false`면 맵에서 제거 |
| `anim` / `anim_mode` | `hold` / `once` — ACTION_ANIM 과 동일 |
| `change_to` | 다른 char/object_defs 키로 외형 교체 |
| `behavior_mode` | NPC 행동 모드 |

### progress_apply — 로드 시 자동 상태

`talk.lines`의 `when`과 같이 **위에서 첫 매칭**:

```json
"progress_apply": [
  { "when": "progress_flower1_1 < 1003", "visible": false },
  { "when": "progress_flower1_1 == 1004", "visible": true, "anim": "walk", "anim_mode": "hold" }
]
```

### interact.bindings — 상호작용

- **이벤트:** `event_id` + `events.json` `result` (기존)
- **인라인:** `state` + `after` (`apply_talk_after` 재사용, `event_id` 없을 때)

```json
{
  "condition": "progress_example == 1",
  "state": { "visible": true },
  "after": { "progress_example": 2 },
  "priority": 10
}
```

### flower_fairy1 예시

| progress | 자동 상태 |
|----------|-----------|
| &lt; 1003 | 숨김 |
| 1003 | idle hold (시들) |
| 1004 | walk hold (싱싱) |
| ≥ 1005 | `fairy1` + walk hold |

**한계:** 손에 든 물건 미저장 · 카메라/CARRY/PLACE 등은 events.json 필요

---

*문서 버전: progress 상태(char_behavior/flow 통합) 기준*

import android_fix  # noqa: F401  # Android asset-path shim; must run before any asset load

CONFIG = {
    # --- Render output mode ---
    # UPSCALE_320: 320x240 논리 렌더 → 정수배(기본 2x)로 640x480 출력
    # NATIVE_640: 640x480 논리 렌더(업스케일 없음)
    #"OUTPUT_MODE": "UPSCALE_320",  # "UPSCALE_320" | "NATIVE_640"
    "OUTPUT_MODE": "NATIVE_640",  # "UPSCALE_320" | "NATIVE_640"
    "UPSCALE_FACTOR": 2,           # UPSCALE_320에서만 사용(정수배)
    "FULLSCREEN": False,
    # Android: 기기 해상도에 맞춰 640x480 비율 유지 스케일(레터박스). main.py가 런타임에 자동 적용.
    "ANDROID_DISPLAY_FIT": True,


    # --- 가변 해상도(자동 출력 모드 전환) ---
    # 기본은 640x480(NATIVE_640). world_zoom이 2.0에 "완료"되면 320x240(UPSCALE_320)로 바꾸고
    # world_zoom은 1.0으로 리셋해서 체감 줌(시야)을 유지하면서 후처리 스케일 비용을 줄인다.
    "AUTO_OUTPUT_MODE_ENABLED": True,
    "AUTO_OUTPUT_MODE_ON_WORLD_ZOOM": 2.0,
    "AUTO_OUTPUT_MODE_OFF_WORLD_ZOOM": 1.0,
    "AUTO_OUTPUT_MODE_COOLDOWN_MS": 900,
    # 3D_ROTATE(Mode7) 샘플 해상도 = CONFIG WIDTH×HEIGHT.
    # True면 Mode7 활성 중 논리 해상도를 320×240(UPSCALE_320)로 강제(해상도 재설정→깜빡임).
    # 기본 화면이 이미 zoom=2.0(UPSCALE_320)이면 False 권장 — 성능은 같고 깜빡임만 제거.
    "ROTATE3D_FORCE_LOGICAL_320": False,


    # 논리 해상도(게임 내부 좌표 기준)
    "WIDTH": 640, "HEIGHT": 480, "FPS": 30,
    # UI 아이콘(말풍선·pushbutton·이모트): 논리 px = 에셋 px (런타임에 WIDTH와 동기화)
    "UI_LAYOUT_WIDTH": 640,
    # 텍스트박스·폰트·RECT_*_320 값만 320 설계 기준 → WIDTH/320 으로 스케일
    "UI_TEXT_REFERENCE_WIDTH": 320,


    # 가변 FPS: 평소 FPS_IDLE / 틸트·쉬어·원근 분기·데모 토글·줌 보간 중에는 FPS_EFFECTS
    "DYNAMIC_FPS_ENABLED": True,
    "FPS_IDLE": 60,
    "FPS_EFFECTS": 60,


    # 렌더 FPS가 낮아져도 이동 속도를 유지하려면 True 권장(DYNAMIC_FPS로 15프레임일 때 체감 속도 유지)
    "FIXED_TIMESTEP_ENABLED": True,


    # None이면 FPS와 동일 Hz로 시뮬 스텝 길이를 잡음
    "FIXED_TIMESTEP_HZ": 60,
    "FIXED_TIMESTEP_MAX_STEPS": 12,
    "FIXED_TIMESTEP_MAX_FRAME_MS": 250.0,
    "EMBEDDED_LIGHTWEIGHT": False,

    # 메모리 워치독: RSS 증가 시 변환 캐시 정리. 전량 clear+gc는 주기적 멈칫 원인이 되기 쉬움.
    # True면: 렌더 FPS 캡이 FPS_EFFECTS 이하일 때(저프레임 변속 구간) '증가분' 트리거만 무시(절대 상한 HIGH_MB는 유지).
    "MEM_WATCHDOG_ENABLED": True,
    "MEM_WATCHDOG_INTERVAL_SEC": 5.0,
    "MEM_WATCHDOG_HIGH_MB": 500.0,
    "MEM_WATCHDOG_GROWTH_MB": 40.0,
    "MEM_WATCHDOG_SKIP_GROWTH_WHEN_FX_FPS": True,
    # RSS가 HIGH_MB 이상이면(절대 상한) 기존처럼 변환 캐시 전량 삭제. 그 외 '증가분'만 보려면 False.
    "MEM_WATCHDOG_GROWTH_TRIGGER_ENABLED": True,
    # 증가분(GROWTH_MB) 트리거 시: 통합 _render_cache만 LRU로 일부만 비움(캠/클라우드·gc 생략). 멈칫 완화에 유리.
    "MEM_WATCHDOG_SOFT_GROWTH_TRIM": True,
    # SOFT_GROWTH_TRIM 시 한 번에 비울 추정 비율(현재 render 캐시 추정 MB 기준).
    "MEM_WATCHDOG_GROWTH_TRIM_FRACTION": 0.2,
    # 전량 clear 경로에서만 gc.collect() — False면 끊김은 줄지만 RSS는 더 느리게 내려갈 수 있음.
    "MEM_WATCHDOG_GC_AFTER_FULL_CLEAR": True,

    # --- 렌더/쉬어 캐시 (RG35xx·PC 기본. Android 3GB는 ANDROID_RAM_PROFILE_* 가 덮어씀) ---
    "RENDER_CACHE_MB_LIMIT": 220.0,
    "RENDER_CACHE_MAX_ITEMS": 96,
    "TEMP_SURF_MB_LIMIT": 96.0,
    "SHEAR_PIN_CACHE_MAX_ITEMS": 12,
    "SPRITE_FIELD_SHEAR_CACHE_MB_LIMIT": 48.0,
    "SPRITE_FIELD_SHEAR_CACHE_MAX_ITEMS": 128,

    # --- Android APK: 3GB RAM 프로필 ---
    # True + 안드로이드 런타임이면 아래 기본값을 CONFIG에 merge (데스크톱·RG35xx 빌드는 영향 없음).
    # 빌드만 바꿀 때: data.py 수정 후 buildozer android debug.
    # 런타임만 바꿀 때: adb shell setprop 또는 앱 시작 전 환경변수 SUMMERLEAF_RAM_PROFILE_MB (선택).
    "ANDROID_RAM_PROFILE_ENABLED": True,
    "ANDROID_RAM_PROFILE_MB": 3072,
    # 비어 있으면 ANDROID_RAM_PROFILE_MB(기본 3072) 프리셋만 적용. 키를 넣으면 프리셋보다 우선.
    "ANDROID_RAM_PROFILE_OVERRIDES": {},

    # 디버그 오버레이(텍스트) 갱신 주기(초). 폰트 렌더/문자열 생성/OS RSS 조회 비용을 줄이기 위함.
    "OVERLAY_UPDATE_INTERVAL_SEC": 0.5,
    "PERF_PROFILER_ENABLED": False,
    # PERF가 켜져 있을 때만 적용: bg_zones / 풀·정렬 / 월드줌 분해(wz_*) / 월드 후단(world_tail) / 오버레이 캐시 갱신(overlay_build) 등
    "PERF_PROFILER_DETAIL": False,
    "PERF_PROFILER_PRINT_EVERY": 120,

    
    # PERF 덤프를 별도 파일에도 기록(기본: logs/perf_profile.log). rg35xx에서 병목만 모을 때 유리.
    # 로그 컬럼: dt_real_ms=clock.tick 반환(실제 프레임 간격), fps_pace_ms=tick 호출 벽시간(FPS 캡 대기 포함),
    # render_cpu=그리기~present까지( flip 제외 ).
    "PERF_PROFILE_LOG_ENABLED": False,
    "PERF_PROFILE_LOG_PATH": "logs/perf_profile.log",


    "START_MAP": "bg_title",  # 처음 시작할 맵 ID
    # 온보딩: 매 실행 인트로→데모 후 본편. 조건식의 gamestart는 세이브가 아니라 GameFlow.boot_phase(0/1/2)로만 평가
    "INTRO_EVENT_ID": "ev_intro_scene",
    "DEMO_EVENT_ID": "ev_gl_demo_02",
    "NEW_GAME_SPAWN_MAP": "bg_jjangpu",
    "NEW_GAME_SPAWN_POS": [653, 1360],
    "NPC_INTERACT_RANGE": 48,
    # FieldItem interact.bindings 클릭 판정(비우면 interact.range / 기본 16)
    "OBJECT_INTERACT_RANGE": 16,
    # interact.prompt_set / prompt_offset_y — 안내 아이콘 (assets/images/ui/{name}/{set}0.png)
    # 손에 든 물건 발(foot) 격자 — 플레이어 발 기준 월드 오프셋 (engine._held_item_foot_world_pos)
    # Y: 클수록 손 위치가 위로(플레이어 pos.y - Y). X: 바라보는 방향 옆 간격.
    "HELD_ITEM_FOOT_OFFSET_X": 12,
    "HELD_ITEM_FOOT_OFFSET_Y": 6,

    # 세이브 없음·merge 기본값 / load_map 플레이어 생성 시 CHAR_ASSETS 키
    "DEFAULT_PLAYER_CHAR": "summer_k",
    "CHAR_SPEED": 1.6, "CURSOR_SPEED": 3.5,
    # 클릭 이동
    "DOUBLE_CLICK_MS": 500,
    "DOUBLE_CLICK_DIST_PX": 18.0,
    # 더블클릭 달리기(직선 이동) 속도 배율
    "RUN_SPEED_MUL": 1.8,
    # 이동 중 좌/우 방향 전환 데드존(px). 작을수록 자주 뒤돌아봄(격자 경로에서 흔들림).
    "DIR_CHANGE_EPS_X": 0.28,
    # 소프트웨어 커서(빨간 점) 크기(논리 해상도 px). rg35xxsp/디버깅에서 너무 작으면 올리면 됨.
    "UI_CURSOR_SIZE": 4,

    # --- 이벤트 SAY 텍스트박스 (320x240 베이스) ---
    # - textbox 이미지는 OBJ_ASSETS(UI) 키로 로드 (기본: textbox01, 320x240 PNG)
    # - 640x480에서는 2배로 스케일되어 위치/비율은 동일하게 유지
    "SAY_USE_TEXTBOX_UI": True,
    "SAY_TEXTBOX_ASSET": "textbox01",
    # 320x240 기준 텍스트 영역 (x, y, w, h)
    "SAY_TEXTBOX_RECT_320": [30, 182, 284, 52],
    # 폰트 (UI_FONT_FILES 키)
    "SAY_FONT_KEY": "dialog",
    "SAY_FONT_SIZE_320": 10,
    "SAY_NAME_FONT_SIZE_320": 12,
    # 이름(Who) 표시 기본값
    "SAY_SHOW_NAME_DEFAULT": True,
    # 간격 (320 기준 px)
    "SAY_LINE_GAP_PX_320": 2,
    "SAY_NAME_GAP_PX_320": 4,
    # 타자 효과
    "SAY_TYPE_MS_PER_CHAR": 28,
    # 완전히 표시된 뒤 바로 닫히지 않게 최소 대기(초)
    "SAY_MIN_CLOSE_DELAY_SEC": 0.8,
    # SAY 시작 직후 입력 무시 시간(초): 타자 시작 직후 실수로 바로 넘기는 것 방지
    "SAY_MIN_OPEN_DELAY_SEC": 0.8,
    # 텍스트박스 등장/퇴장 페이드(초)
    "SAY_UI_FADE_ENABLED": True,
    "SAY_UI_FADE_IN_SEC": 0.2,
    "SAY_UI_FADE_OUT_SEC": 0.2,
    # PLACE/MOVE appear=fade 알파 보간 시간(초). 예전 5px/프레임@60fps ≈ 0.85초.
    "APPEAR_FADE_SEC": 0.85,
    # 시각 보간(틸트/쉬어/카메라 lerp) 기준 프레임 길이(초). 실제 경과 dt와 함께 사용.
    "VISUAL_DT_REF_SEC": 1.0 / 60.0,
    # 같은 이벤트 안에서 SAY가 연속일 때: 박스 페이드아웃/인 없이 다음 대사만 갱신
    "SAY_CHAIN_WITHIN_EVENT": True,
    # 색상 — 게임 텍스트 통일: 검정 글자 + 흰 테두리 (가독성)
    "SAY_NAME_COLOR": (0, 0, 0),
    "SAY_TEXT_COLOR": (0, 0, 0),
    # 폰트 테두리(스트로크): 가독성 개선용. (pygame 기본기능 아님 → 여러 번 찍는 방식)
    "SAY_FONT_OUTLINE_ENABLED": True,
    "SAY_FONT_OUTLINE_PX_320": 1,  # 320 기준 두께 (640에서는 2배)
    "SAY_FONT_OUTLINE_COLOR": (255, 255, 255),
    # 일반 UI(OutlinedUIFont) 채움색. True면 render() 인자색 무시하고 이 색 사용
    "UI_FONT_FILL_COLOR": (0, 0, 0),
    "UI_FONT_FORCE_FILL_COLOR": True,
    # 밝은 외곽선 + 밝은(거의 흰) 채움이 오면 대체할 채움색 (= UI_FONT_FILL_COLOR 권장)
    "UI_FONT_LIGHT_FILL_COLOR": (0, 0, 0),
    # 타이틀(logo) 제외 일반 UI 텍스트 테두리 — 대화창과 동일 규칙
    "UI_FONT_OUTLINE_ENABLED": True,
    "UI_FONT_OUTLINE_PX_320": 1,
    "UI_FONT_OUTLINE_COLOR": (255, 255, 255),

    # --- SAY 말풍선 (assets/{prefix}_0.png … 연속 번호) ---
    # SAY 스텝에 "bubble": true 및 bubble_target(비우면 who) 가 있을 때만 표시.
    "SAY_BUBBLE_DEFAULT": True,
    "SAY_BUBBLE_UI_PREFIX": "images/ui/speechbubble",
    "SAY_BUBBLE_MAX_FRAMES": 16,
    "SAY_BUBBLE_FRAME_MS": 140,
    # 말풍선 앵커: 스프라이트 머리(상단 중앙) 기준 오프셋(논리 px, UI_LAYOUT_WIDTH 기준 1:1)
    "SAY_BUBBLE_OFFSET_X_PX_320": 10,
    "SAY_BUBBLE_OFFSET_Y_PX_320": 10,

    # --- EMOTE (이벤트 스텝 type: EMOTE, assets/images/ui/{emotion}_0.png …) ---
    "EMOTE_MAX_FRAMES": 48,
    "EMOTE_DEFAULT_FRAME_MS": 120,
    "EMOTE_OFFSET_X_PX_320": 0,
    "EMOTE_OFFSET_Y_PX_320": -4,

    # --- 에디터: 이벤트 스텝 리스트 호버 툴팁 ---
    "EDITOR_STEP_LIST_TOOLTIP_ENABLED": True,
    # 툴팁 본문 최대 폭(우측 사이드바 220px × EDITOR_TOOLTIP_WIDTH_SIDEBAR_MUL)
    "EDITOR_TOOLTIP_MAX_BODY_WIDTH_PX": 330,
    "EDITOR_TOOLTIP_WIDTH_SIDEBAR_MUL": 1.5,
    "EDITOR_SIDEBAR_WIDTH_PX": 220,
    # 에디터 OBJECTS: 원본 스프라이트 긴 변 ≥ 이 값이면「큰것」숨김 시 이름 칩으로 표시
    "EDITOR_HIDE_LARGE_MIN_PX": 160,
    # 배경 알파(낮을수록 반투명 — 아래 리스트 선택이 비침)
    "EDITOR_TOOLTIP_BG_ALPHA": 185,

    # --- 이벤트 존(contact_confirm) 클릭 가능 표시(FX) ---
    "ZONE_CONFIRM_PROMPT_ENABLED": True,
    # assets/images/ui/pushbutton0.png ... pushbutton3.png
    "ZONE_CONFIRM_PROMPT_PREFIX": "assets/images/ui/pushbutton",
    "ZONE_CONFIRM_PROMPT_FRAMES": 4,
    "ZONE_CONFIRM_PROMPT_FRAME_MS": 110,
    # 존 중앙 기준 오프셋 (월드 px)
    "ZONE_CONFIRM_PROMPT_OFFSET_Y_PX": -6,

    # --- 엔티티(캐릭터·오브젝트) 상호작용 안내 아이콘 ---
    # assets/images/ui/{이름}/{prompt_set}0.png → 없으면 assets/images/ui/pushbutton/{prompt_set}0.png
    "INTERACT_PROMPT_ENABLED": True,
    "INTERACT_PROMPT_DEFAULT_SET": "pushbutton",
    "INTERACT_PROMPT_FRAMES": 4,
    "INTERACT_PROMPT_FRAME_MS": 110,
    "INTERACT_PROMPT_OFFSET_Y_PX": -28,
    # 디버그: 기존 사각형 대화 UI를 함께 그릴지 여부(main.py)
    "SAY_DEBUG_LEGACY_BOX": False,
    "ANIM_DELAY": 150, "INTERACT_DIST": 35,
    # OBJ_ASSETS path가 name_0.png 형식일 때 연속 프레임 자동 로드 상한 (flower1_0~7 등)
    "OBJ_ANIM_MAX_FRAMES": 64,

    # 길찾기(프레임 분할): 클릭 순간 멈칫 완화용
    "PATHFIND_BUDGET_MS_PER_FRAME": 1.8,
    # 길찾기 완료 시 경로 "붙이기" 튐 방지: 계획 시작점(sx,sy)과 현재 pos가 많이 달라지면 현재 pos로 재계획
    "PATHFIND_REBASE_START_DIST_PX": 18.0,
    # 길찾기 완료 시: 현재 pos에 가까운 지점부터 경로를 붙이는 허용 거리
    "PATHFIND_ATTACH_NEAR_CUT_PX": 12.0,

    
    # --- 줌(새 시스템) ---
    # 원칙: 개별 요소(배경/오브젝트/마스크)를 따로 스케일하지 않고,
    #       "오버레이를 제외한 월드 최종 결과물"을 1장으로 만든 뒤 그 1장만 스케일한다.
    # 장점: 저사양에서 훨씬 가볍고, 구현/튜닝 포인트가 단순하다.
    "WORLD_ZOOM_ENABLED": True,
    "WORLD_ZOOM_DEFAULT": 2.0,   # 1.0=기본, 2.0=2배 확대, 0.5=절반 축소
    "WORLD_ZOOM_MIN": 1.0,
    "WORLD_ZOOM_MAX": 4.0,
    "WORLD_ZOOM_SPEED": 3.0,     # zoom/sec (값이 클수록 더 빠르게 확대/축소)

    # --- 개별 오브젝트 줌(별개 기능) ---
    # 이벤트 ZOOM에서 target이 player/NPC/오브젝트인 경우에만 사용. (camera/global 대상 줌은 WORLD_ZOOM으로 처리)
    # val/strength = 직접 배율 (0.5=절반, 1.0=기본, 2.0=2배). on=false → 1.0
    "ENTITY_ZOOM_MIN": 0.5,
    "ENTITY_ZOOM_MAX": 2.0,
    "ENTITY_ZOOM_DEFAULT_DURATION_SEC": 1.0,
    "ENTITY_ZOOM_LERP": 0.12,  # 0~1, 클수록 더 빠름

    # --- 틸트/쉬어/캐시(줌과 무관) ---
    "RENDER_TILT_STEP": 0.01,  # 0.005~0.02 권장
    "RENDER_SCALE_CACHE_MAX": 48,  # 배경/마스크/틸트 스케일 캐시 상한


    # 배경: 맵 전체 스케일 대신 카메라 뷰만 크롭→스케일(저사양·대형 맵에 유리).
    # 틸트/쉬어(원근 변형)와 결합 시 배경/오브젝트가 어긋나 보일 수 있어 기본값은 원래 방식(전체 배경 스케일)으로 되돌림.
    "BG_VIEWPORT_BLIT_ENABLED": False,


    # 틸트/쉬어 시 월드 크롭 여유(px, 화면 기준으로 환산해 확장). 검은 가장자리가 보이면 12~24로 올려볼 것.
    "BG_VIEWPORT_TILT_PAD_PX": 12,


    # 줌 중에만 배경을 더 싸게: 뷰포트 크롭→스케일 강제 사용 (틸트/쉬어 OFF인 경우에만 적용)
    "ZOOM_LOD_BG_VIEWPORT_ENABLED": True,


    # (삭제) 기존 카메라 줌 업데이트/양자화 옵션들은 새 월드 줌 시스템에서 사용하지 않음.


    # --- 스프라이트 스케일 캐시 ---
    # STEP: 원근/줌 배율 양자화. 예전에 0.1이면 크기가 10%씩 탁탁 점프(Mode7에서 특히).
    # 0=끔 → 출력 가로·세로를 픽셀 단위로만 반올림(프레임당 최대 1px 변화).
    "SPRITE_SCALE_STEP": 0.0,
    # 픽셀 아트용 nearest scale. True=smoothscale(외곽 흐림) — 원근 크기 점프와는 별개.
    "SPRITE_SCALE_SMOOTH": False,
    "SPRITE_SCALE_CACHE_MAX_ITEMS": 512,
    "SPRITE_SCALE_CACHE_MB_LIMIT": 96.0,


    # --- 데모: 배경 세로 압축(3D 느낌) ---
    # 1.0=기본(압축 없음), 작을수록 더 "옆에서 보기"에 가까움
    # 틸트 켤 때 목표값으로 쓰임. 단, 아래 TILT_FACTOR_MIN 이하면 전부 그 최솟값으로 잘림(0.001≈0.1처럼 보이는 이유).
    "TILT_BG_ON_FACTOR": 0.5, #0.12가 최저
    # 렌더·이벤트 TILT factor 공통 하한(배경 세로 스케일 f_q). 더 과하게 기울이려면 0.05 등으로 낮춤(너무 낮으면 배경이 매우 납작).
    "TILT_FACTOR_MIN": 0.1,
    # 목표값으로 수렴하는 속도(0~1). 값이 클수록 더 빨리 수렴.
    # 감속(ease-out)은 사용하지 않음: 끝부분만 느리게 가면 저사양에서 체감/성능 복귀가 늦어짐.
    "TILT_BG_SPEED": 0.3,
    # 목표와 현재의 차이가 이 값 이하면 즉시 스냅(안정화). 작을수록 더 오래 "미세 수렴"함.
    "TILT_BG_EPS": 0.01,


    # --- 필드 기본 원근(틸트+쉬어) ---
    # FIELD_PERSPECTIVE_DEFAULT_ON: 시작 시 틸트(세로 압축) ON. False=평면(1.0)에서 시작.
    # TILT_SHEAR_ENABLED: 필드 기본 쉬어 ON.
    # TILT_SHEAR_SCALE_WITH_TILT: True면 쉬어가 틸트에 비례(평면이면 0). False면 틸트 없이도 TILT_SHEAR_TOP_PX 전체 적용.
    #   예) 쉬어만 켜고 틸트는 끄기: ENABLED=True, FIELD_PERSPECTIVE=False, SCALE_WITH_TILT=False.
    # TILT_SHEAR_TOP_PX: 최대 쉬어(px). 필드용 24~48 권장.
    "FIELD_PERSPECTIVE_DEFAULT_ON": False,
    "TILT_SHEAR_ENABLED": True,
    "TILT_SHEAR_SCALE_WITH_TILT": False,
    "TILT_SHEAR_TOP_PX": 128,
    # 화면 기준: 최상단이 밀리는 최대 px (0=끄기)
    # 배경/마스크 쉬어: 작을수록 부드럽지만 느림. rg35xxsp에서는 4~8 권장.
    "TILT_SHEAR_SLICE_H_PX": 2,

    # ─────────────────────────────────────────────────────────────────────
    # 틸트/쉬어 "transition(변환이 움직이는 중)" 경량화
    #  - 목적: tilt_current / shear_smoothed 가 목표로 수렴하는 짧은 구간 동안에만
    #    배경/마스크 변환 비용을 크게 줄인다. "정착(settle)"된 뒤에는 기존 풀품질
    #    경로(슬라이스 2px, 세밀 양자화)를 그대로 쓰므로 최종 정지 화면 품질은 동일.
    #  - 전후 성능 비교: TILT_SHEAR_FAST_TRANSITION 을 False 로 두면 예전(무최적화)
    #    동작과 100% 동일해지므로, PERF 로그의 bg_anim/mask_anim 수치를 ON/OFF 로
    #    각각 측정해 "얼마나 가벼워졌는지"를 ms 단위로 직접 비교할 수 있다.
    # ─────────────────────────────────────────────────────────────────────
    # 마스터 스위치(False=예전 동작과 동일, 전후 비교 기준).
    "TILT_SHEAR_FAST_TRANSITION": True,
    # (A) 변환 중 배경/마스크 쉬어 슬라이스 높이(px). 평소(TILT_SHEAR_SLICE_H_PX)보다
    #     굵게 자르면 blit 횟수는 줄지만 "계단현상"이 커진다. 그래서 기본은 평소와 같은
    #     2px(=LOD 사실상 끔)로 두어 화질을 유지하고, 속도는 (B)copy 제거 + (C)캐싱으로
    #     얻는다. 저사양에서 변환 중 프레임이 부족하면 3~4 정도로만 올린다(그 이상은 계단↑).
    "TILT_SHEAR_SLICE_H_PX_ANIM": 2,
    # (C) 변환 중 캐시 키 양자화. 키 개수를 적게 유지해, 변환 중에도 캐시를 켜도
    #     RSS 스파이크가 나지 않게 한다(1GB 기기 안전). 굵을수록 모션이 살짝 끊겨
    #     보일 수 있으니 부드러움 우선이면 작게 낮춘다(캐시 적중률은 약간 떨어짐).
    "RENDER_TILT_STEP_ANIM": 0.03,     # f_q(세로압축) 양자화 단위(변환 중)
    "TILT_SHEAR_PX_QUANT_ANIM": 3,     # shear_eff(px) 양자화 단위(변환 중)




    # 스프라이트 쉬어: 배경보다 더 굵게 잘라도 티가 덜 나고, 비용이 크게 줄어듦.
    "SPRITE_SHEAR_SLICE_H_PX": 1,
    # 스프라이트 쉬어 LOD: 줌/틸트/쉬어가 변하는 동안엔 더 거칠게(또는 생략)해서 프레임 유지
    "SPRITE_SHEAR_DURING_ANIM": True,
    "SPRITE_SHEAR_SLICE_H_PX_LOD": 2,
    # 쉬어 샘플 Y를 픽셀 단위로 양자화해 캐시 재사용/떨림 완화
    "SPRITE_SHEAR_Y_QUANT_PX": 1,
    "SPRITE_SHEAR_Y_QUANT_PX_LOD": 2,
    # 틸트/쉬어 중 카메라가 움직일 때 일부 캐릭터/오브젝트가 ±1px로 떨리는 현상 방지:
    # 쉬어 가로 오프셋을 '정수 + y격자 양자화'로 적용해 본체/그림자/필드가 lockstep 이동.
    # 끄면(=False) 예전처럼 연속 실수 오프셋(떨림 가능).
    "SHEAR_SPRITE_STABILIZE": True,
    # 쉬어 목표값→화면 반영 보간 (0~1). 값이 클수록 더 빨리 수렴.
    # 감속(ease-out)은 사용하지 않음(항상 일정 speed로 수렴).
    "SHEAR_SMOOTH_SPEED": 0.3,
    # 목표(px)와 현재(px)의 차이가 이 값 이하면 즉시 스냅(안정화)
    "SHEAR_SMOOTH_EPS": 0.01,
    "SHEAR_BRANCH_OFF_EPS": 0.01, # 이 값 이하면 원근 브랜치(마스크/스프라이트) 끔
    # 쉬어가 "px" 기준이라 줌이 커질수록 각도가 작아 보이는 문제 보정:
    # 렌더링에 사용하는 쉬어(px)를 zoom에 비례(또는 zoom^p)해서 키움.
    "SHEAR_SCALE_WITH_ZOOM": False,
    "SHEAR_ZOOM_REF": 0.25,       # 1.0 기준(보통 기본 줌)
    "SHEAR_ZOOM_POWER": 0.5,     # 1.0=선형, 0.5=완만, 2.0=강함
    "SHEAR_RENDER_PX_MAX": 512,  # 화면 기준 상한(폭 깨짐 방지)


    # 쉬어로 배경 좌측 빈 픽셀이 보일 때: 카메라 중심 X의 '맵 안 허용 범위'만 쉬어값에 맞게 줄임.
    # 플레이어는 평소 화면 중앙 추적 유지, 맵 좌/우 끝에 붙었을 때만 기존처럼 중심에서 벗어남.
    "SHEAR_CAMERA_CLAMP_ENABLED": False,
    "SHEAR_CAMERA_CLAMP_EPS": 0.25,       # 쉬어(px) 이하이면 클램프 생략
    "SHEAR_CAMERA_MARGIN_FRAC": 0.0,    # (쉬어px/줌) 월드 마진에 곱함 (0~2)
    # 쉬어로 스프라이트가 화면에서 오른쪽으로 밀릴 때, 카메라 X를 보정해 플레이어를 가로 중앙에 유지
    "SHEAR_PLAYER_CENTER_CAM_ENABLED": True,


    # --- 그네(프로토타입) ---   
    # 앞뒤(깊이) 움직임을 화면(월드 y 이동)으로 투영하는 비율. 시점 때문에 앞이 덜 가는 것처럼 보이면 forward를 올리면 됨.
    "SWING_DEPTH_TO_Y_FORWARD": 1.0,
    "SWING_DEPTH_TO_Y_BACK": 1.0,
    # 감쇠 진자 파라미터
    "SWING_HZ": 0.75,
    "SWING_DAMP_TAU_SEC": 10.0,
    "SWING_THETA0_RAD": 0.85,
    "SWING_BASE_XY": [810, 1915],
    "SWING_A_HEIGHT": 65.0,
    "SWING_B_REST_HEIGHT": 15.0,
    "SWING_SPRITE_SIZE": [36, 25],
    "SWING_IMG_IDLE": "assets/images/object/swing1.png",
    "SWING_IMG_FORWARD": "assets/images/object/swing2.png",
    "SWING_IMG_BACK": "assets/images/object/swing3.png",
    # 포즈 전환 임계값(깊이/L). 낮추면 swing2/3가 더 자주 보임.
    "SWING_POSE_THRESH_FORWARD": 0.45,
    "SWING_POSE_THRESH_BACK": 0.45,
    # 그네 그림자(캐릭터 그림자 설정 기반) 추가 스케일/알파
    "SWING_SHADOW_SIZE_MUL": 1.0,
    "SWING_SHADOW_ALPHA_MUL": 1.0,


    # --- 구름 그림자 FX (맵 월드 격자 + 지터) ---
    # 이벤트 FX 예: { "type":"FX","kind":"cloud_shadow","on":true,"dir":"SE","speed":22,"freq":0.08,"grid_cell":160,"grid_jitter":0.4,"grid_max":200 }
    # dir: "SE"|"SW"|"NE"|"NW"|"RANDOM"
    # 필드 디버그/테스트: events.json GLOBAL 에 trigger: hotkey + steps 에 DEV_CMD(cmd) 로 정의
    "CLOUD_SHADOW_ENABLED": False,
    "CLOUD_SHADOW_DIR": "RANDOM",
    "CLOUD_SHADOW_SPEED": 15.0,     # px/sec
    "CLOUD_SHADOW_FREQ": 0.5,      # spawns/sec (0.06 ≈ 1개/16초)
    "CLOUD_SHADOW_ALPHA": 30,       # 0~255 (진할수록 어두움)
    "CLOUD_SHADOW_SCALE_MIN": 0.8,
    "CLOUD_SHADOW_SCALE_MAX": 1.4,
    # 가장자리 부드러움(성능 안전): 0=그대로, 0.2~0.6 권장. (생성 시 1회 처리 + 캐시됨)
    "CLOUD_SHADOW_SOFTEN": 0.8,
    # 구름: 월드 고정 격자(바둑판) 셀마다 1개 + 셀 안 랜덤 흔들림. 셀 크기↑ = 구름 간격↑
    "CLOUD_SHADOW_GRID_CELL_PX": 320,
    # 0~0.49 권장. 셀 반지름 비율만큼 중심에서 좌표가 흔들림
    "CLOUD_SHADOW_GRID_JITTER_RATIO": 0.42,
    # 초기 격자가 너무 많을 때 상한(성능)
    "CLOUD_SHADOW_GRID_MAX_CLOUDS": 200,
    # 구름 스폰 시 화면 밖 최소 여백(px). 스프라이트 크기에 따라 자동 확장된다.
    "CLOUD_SHADOW_SPAWN_MARGIN_PX": 96,

    # --- 엔티티 FX ---
    # 예: { "type":"ENTITY_FX","target":"player","mode":"pulse","color":"255,220,100","alpha":160,"cycle_sec":1.2 }
    # action: stop 으로 해제. (구형: type=FX, kind=entity_fx)
    "ENTITY_FX_DEFAULT_CYCLE_SEC": 1.0,
    "ENTITY_FX_TINT_CACHE_MAX": 96,

    # 이벤트 SCREEN_FX — kind: cloud | flash | shake | rain (구형 type:FX 도 런타임 호환)
    # 예: { "type":"SCREEN_FX","kind":"cloud","on":true,"dir":"RANDOM","speed":15,"freq":0.5 }
    # 예: { "type":"SCREEN_FX","kind":"flash","on":true,"mode":"pulse","color":"255,255,255","alpha":140,"cycle_sec":0.7 }
    # 예: { "type":"SCREEN_FX","kind":"shake","on":true,"amp_px":8,"freq_hz":14 }
    # 예: { "type":"SCREEN_FX","kind":"rain","on":true,"density":0.4,"speed":300,"angle":78,... }
    # 예: { "type":"SCREEN_FX","kind":"vignette","on":true,"strength":0.55,"size":0.42,"softness":0.65,"color":"0,0,0" }
    # 예: { "type":"SCREEN_FX","kind":"tone","on":true,"preset":"warm","strength":0.35 }
    # (구형: SCREEN_FLASH, SCREEN_SHAKE, type=FX+kind=screen_*)
    "SCREEN_FX_FLASH_DEFAULT_ALPHA": 140,
    "SCREEN_FX_FLASH_DEFAULT_CYCLE_SEC": 0.7,
    "SCREEN_FX_SHAKE_DEFAULT_AMP_PX": 7,
    "SCREEN_FX_SHAKE_DEFAULT_FREQ_HZ": 14,
    "SCREEN_FX_RAIN_DEFAULT_DENSITY": 0.35,
    "SCREEN_FX_RAIN_DEFAULT_SPEED": 280.0,
    # 예: angle=0 수직, 45 대각, 82 기본(약간 기울어짐). 90은 순수 수평이라 vy=0 → 제외(최대 88).
    "SCREEN_FX_RAIN_DEFAULT_ANGLE": 82.0,
    "SCREEN_FX_RAIN_ANGLE_MIN": 0.0,
    "SCREEN_FX_RAIN_ANGLE_MAX": 88.0,
    "SCREEN_FX_RAIN_DEFAULT_DROP_LEN": 7,
    "SCREEN_FX_RAIN_DEFAULT_ALPHA": 170,
    # density→드롭 수 환산(뷰포트 면적 나눗셈). 작을수록 화면 전체가 더 촘촘해짐.
    "SCREEN_FX_RAIN_DENSITY_AREA_DIV": 280.0,
    "SCREEN_FX_RAIN_MAX_DROPS": 320,
    "SCREEN_FX_RAIN_MARGIN_X": 64.0,
    "SCREEN_FX_RAIN_SPAWN_ABOVE_MUL": 1.25,
    # 깊이감(원경/근경 2겹) — 근경(길고·진하고·빠름) 비율. 나머지는 원경(짧고·흐리고·느림).
    "SCREEN_FX_RAIN_NEAR_RATIO": 0.45,
    # vignette — strength 0~1, size=중앙 밝은 영역(0~1), softness=그라데이션 폭
    "SCREEN_FX_VIGNETTE_DEFAULT_STRENGTH": 0.55,
    "SCREEN_FX_VIGNETTE_DEFAULT_SIZE": 0.42,
    "SCREEN_FX_VIGNETTE_DEFAULT_SOFTNESS": 0.65,
    # tone — preset warm|cool|neutral|custom, strength 0~1
    "SCREEN_FX_TONE_DEFAULT_STRENGTH": 0.32,
    "SCREEN_FX_TONE_WARM_RGB": (255, 210, 170),
    "SCREEN_FX_TONE_COOL_RGB": (170, 205, 255),
    "SCREEN_FX_TONE_NEUTRAL_RGB": (255, 255, 255),

    # 에디터 R,G,B 필드용 색상 팔레트 (OVERLAY_UI color, ENTITY_FX/SCREEN_FX 등)
    "EDITOR_COLOR_PALETTE": [
        {"name": "흰색", "rgb": "255,255,255"},
        {"name": "검정", "rgb": "0,0,0"},
        {"name": "회색", "rgb": "160,160,160"},
        {"name": "금색", "rgb": "255,220,100"},
        {"name": "노랑", "rgb": "255,255,80"},
        {"name": "주황", "rgb": "255,160,60"},
        {"name": "빨강", "rgb": "255,80,80"},
        {"name": "분홍", "rgb": "255,120,180"},
        {"name": "보라", "rgb": "180,100,255"},
        {"name": "파랑", "rgb": "80,140,255"},
        {"name": "하늘", "rgb": "140,210,255"},
        {"name": "청록", "rgb": "80,220,200"},
        {"name": "초록", "rgb": "100,220,120"},
        {"name": "연두", "rgb": "180,255,120"},
        {"name": "갈색", "rgb": "140,90,50"},
        {"name": "크림", "rgb": "255,248,220"},
    ],

    
    # 카메라: 플레이어를 화면 중앙보다 아래로 배치(픽셀). 예: 50이면 플레이어가 화면에서 50px 아래에 보임
    "CAMERA_FOLLOW_OFFSET_Y_PX": 60,
    # 카메라 추적 보간(0.05~0.25). 이벤트/코드에서 instant면 1프레임 스냅
    "CAMERA_FOLLOW_LERP": 0.1,

    "SAVE_FILE": "save_data.json",

    # 키 한 번 → 글로벌 이벤트 ID (해당 이벤트는 trigger: hotkey, steps 에 DEV_CMD 등)
    # key: 한 글자/숫자 또는 F9 처럼 F숫자, 또는 K_ESCAPE 처럼 pygame 상수명
    "GLOBAL_EVENT_HOTKEYS": [
        {"key": "d", "event_id": "ev_hotkey_restart"},  # 세이브파일 삭제
        {"key": "g", "event_id": "ev_hotkey_fullscreen"},  # 전체 화면 토글
        {"key": "m", "event_id": "ev_hotkey_mask"},  # 마스크 토글
        {"key": "o", "event_id": "ev_hotkey_overlay"},  # 오버레이 토글
        {"key": "l", "event_id": "ev_hotkey_tilt"},  # 틸트 토글
        {"key": "r", "event_id": "ev_hotkey_shear"},  # 쉬어 토글
        {"key": "q", "event_id": "ev_hotkey_3d_rotate"},  # 3D_ROTATE 토글
        {"key": "F9", "event_id": "ev_hotkey_jump_shadow"},  # 점프 그림자 토글
        {"key": "x", "event_id": "ev_hotkey_zoom_cycle"},  # 줌 순환
        {"key": "y", "event_id": "ev_hotkey_cloud"},  # 구름 효과
    ],
    # --- 3D_ROTATE / Mode7 (레이싱 전용 맵 원근). 사다리꼴 레거시 키는 사용하지 않음. ---
    "ROTATE3D_DEFAULT_STRENGTH": 1.0,   # 이벤트/토글 on 시 목표 strength(0~1)
    "ROTATE3D_DEFAULT_DURATION_SEC": 0.4,  # 이벤트 스텝 기본 보간 시간(초)
    "ROTATE3D_SPEED": 0.14,            # 핫키 토글 등 duration 없을 때 매 프레임 보간 계수
    "ROTATE3D_EPS": 0.003,             # strength≈0 판정·각도키 활성 임계
    "ROTATE3D_ANGLE_SPEED": 2.2,       # Mode7 활성 시 < > 키 회전 속도 (rad/s). activity가 heading을 쓰면 이 키는 옵션
    # 배경 Mode7: p = CAM_H/(row+NEAR), depth = p*DEPTH_MUL, lat_scale = p*LATERAL_MUL
    # 스프라이트 크기(SNES 카트): scale = CAMERA_BACK/forward — 앞뒤만. 같은 깊이면 플레이어와 동일 크기.
    "ROTATE3D_HORIZON_FRAC": 0.30,     # 지평선 높이 = 화면높이×비율×strength   30
    "ROTATE3D_CAM_H": 90.0,            # p = CAM_H/(row+NEAR)   120
    "ROTATE3D_NEAR": 30.0,             # 작을수록 원근 강함(너무 작으면 하단이 광각처럼 보임)   30.0
    "ROTATE3D_DEPTH_MUL": 165.0,       # depth = p * DEPTH_MUL (PIVOT_FIT 켜면 런타임에 덮어씀) 165
    "ROTATE3D_LATERAL_MUL": 1.05,      # 도로 위치 샘플용. 스프라이트 크기에는 안 씀    1.05
    "ROTATE3D_CAMERA_BACK": 200.0,      # 플레이어 뒤 카메라 + 스프라이트 scale=1 기준 깊이 200 (가장 효과 큼)
    "ROTATE3D_BASE_HEADING": 1.5707963267948966,  # 기본 시선(+y). heading = BASE + ui.rotate3d_angle
    "ROTATE3D_PLAYER_BOTTOM_PAD": 50,  # 플레이어 하단 고정 여백(px)    50
    # Mode7 화면에서 플레이어(투영 중심) X 비율. 0.5=중앙, 1/3≈좌측 — 우측 시야에 트랙 전방이 더 넓게 들어옴
    "ROTATE3D_PLAYER_SCREEN_X_FRAC": 0.35,    #0.35
    # True면 DEPTH_MUL만 맞춰 발이 빌보드 Y에 오게 함(행별 원근 식은 그대로)
    "ROTATE3D_PIVOT_FIT_PLAYER": True,
    # 스프라이트: scale = ref_forward/forward (앞뒤만). 호출측에서 ×zoom
    "ROTATE3D_SPRITE_SCALE_ENABLED": True,
    "ROTATE3D_SPRITE_SCALE_MIN": 0.05,
    "ROTATE3D_SPRITE_SCALE_MAX": 8.0,
    # Mode7 스프라이트 bounds-aware cull 패딩(px). 발점이 아니라 스케일된 사각형이
    # 화면과 겹치는지 볼 때 좌우·상단(·동일 pad)·하단 여유. 지평선으로 발을 자르지 않음.
    "ROTATE3D_CULL_PAD_PX": 64,        # 좌우·상단 여유(스프라이트 몸통이 가장자리에 남아 있으면 유지)
    "ROTATE3D_CULL_BELOW_PAD_PX": 220, # 하단 여유(화면 아래 발·큰 스케일 빌보드)
    # Mode7 빈 공간 채움: 지평선 위=하늘, 아래(맵 밖)=바닥색. 파노라마 경로가 있으면 하늘만 360 원통 샘플.
    "ROTATE3D_SKY_COLOR": (135, 206, 235),      # 지평선 위 단색(파노라마 없거나 로드 실패 시)
    "ROTATE3D_GROUND_FILL_COLOR": (37, 159, 235),    # 지평선 아래·맵 밖 픽셀
    "ROTATE3D_SKY_PANORAMA": "",                 # 360 하늘 이미지 경로. 빈 문자열=단색. 예: assets/images/bg/sky_360.png
    "ROTATE3D_SKY_PANORAMA_YAW_OFFSET": 0.0,     # 파노라마 기준 yaw 보정(라디안). 이미지 정면 맞출 때
    "ROTATE3D_SKY_FOV_RAD": 1.2,                 # 화면 가로가 담는 하늘 시야각(라디안). 클수록 좌우로 더 많이 보임
    # --- Mode7 성능 ---
    # quality_scale: 1.0=전체 해상도 샘플, 0.75≈중간, 0.5=반해상도 후 확대.
    # cfg에 quality_scale 이 명시되면(레이스 옵션) 그 값을 쓰되, Android 는 CAP 로 상한.
    # H700급(RG34XX 등): Mode7 부하는 오브젝트가 아니라 바닥 픽셀 샘플 — 상한이 핵심.
    "ROTATE3D_QUALITY_SCALE": 1.0,              # PC·명시 없을 때 기본(전체)
    "ROTATE3D_ANDROID_QUALITY_SCALE": 0.50,     # Android에서 CONFIG만 1.0일 때 자동
    "ROTATE3D_ANDROID_QUALITY_CAP": 0.55,       # 640 논리일 때 레이스 '높음' 상한
    # 320 논리(Mode7 강제/UPSCALE)면 픽셀 수가 1/4 → 상한을 올려도 640@0.5와 비슷한 부하
    "ROTATE3D_ANDROID_QUALITY_CAP_320": 0.90,
    "ROTATE3D_SAMPLE_CHUNK_ROWS": 48,           # numpy 벡터화 청크(행). 32~64 권장
    # 행 인터레이스: 짝수/홀수 행을 프레임마다 번갈아 샘플(~2× 가벼움). 고속 회전 시 빗살 잔상 가능.
    "ROTATE3D_INTERLACE_ROWS": True,
    "ROTATE3D_FALLBACK_X_STEP": 2,              # numpy 없을 때 가로 샘플 간격(px)
    "ROTATE3D_FALLBACK_Y_STEP": 1,              # numpy 없을 때 세로 샘플 간격(px). 2면 줄 복제
    "ROTATE3D_ANDROID_FALLBACK_X_STEP": 3,      # Android get_at 폴백 가로 간격
    "ROTATE3D_ANDROID_FALLBACK_Y_STEP": 2,      # Android get_at 폴백 세로 간격
    # 시작 시 디버그 텍스트 오버레이(HUD) 기본 표시 여부. 런타임 토글은 'O' 키.
    "SHOW_OVERLAY_DEFAULT": False,
    # 오버레이(HUD)를 껐을 때도 RSS 메모리 표시를 남길지 여부.
    "SHOW_RSS_OVERLAY_WHEN_OFF": False,
    # 필드 플레이 중 오른쪽 위 게임 종료 버튼(OVERLAY_UI, events.json fishing_exit와 동일 파이프).
    "GAME_EXIT_OVERLAY_ENABLED": True,
    # RG34XX 등 터치 없는 기기: A+X 동시 입력 시 앱 즉시 종료 (확인창 없음).
    "APP_FORCE_QUIT_COMBO_ENABLED": True,
    "APP_FORCE_QUIT_COMBO_KEYS_A": ["a", "space", "return"],  # A 버튼(키보드 매핑)
    "APP_FORCE_QUIT_COMBO_KEYS_X": ["x"],                     # X 버튼(키보드 매핑)
    # RG34XX 등 패드: SDL JOYBUTTON 조합(여러 후보). 레거시 APP_FORCE_QUIT_JOY_BUTTONS 도 폴백.
    "APP_FORCE_QUIT_JOY_COMBOS": [[0, 2], [1, 3], [0, 3], [2, 3], [1, 0]],
    "APP_FORCE_QUIT_JOY_BUTTONS": [0, 2],
    # 감쇠로 멈춘 뒤 시뮬을 다시 시작하는 키. GLOBAL_EVENT_HOTKEYS와 동일: 한 글자, F9, K_ESCAPE 등 pygame 상수명.
    "SWING_RESTART_HOTKEY": "b",

    # --- 그네 타기(데모) ---
    # A(키 a) 연타로 파워(진폭)를 올리고, 멈추면 감쇠로 0까지 떨어지면 자동 하차
    "SWING_RIDE_INTERACT_DIST": 20.0,     # 그네 클릭 판정 반경(px, 월드)
    "SWING_RIDE_MOUNT_DIST": 26.0,        # 좌석 근처 도착 판정 반경(px, 월드)
    "SWING_RIDE_MOUNT_FRAMES": 4,         # 탑승 전 위치→그네 좌석 이동 프레임 수
    "SWING_RIDE_SEAT_HEIGHT_OFFSET_PX": -5.0,  # 좌석 기준 height 오프셋(px). -값이면 더 낮게(=아래로)
    "SWING_RIDE_PUMP_WINDOW_SEC": 0.8,    # 연타 속도 측정 창(초)
    "SWING_RIDE_PUMP_CPS": 4.5,           # 초당 입력수 임계치(이 이상이면 가속)
    "SWING_RIDE_ACCEL_PER_SEC": 0.55,     # 파워 상승 속도(0~1/sec)
    "SWING_RIDE_DECAY_PER_SEC": 0.18,     # 파워 감쇠 속도(0~1/sec)
    "SWING_RIDE_POWER_MAX": 1.0,          # 파워 상한
    "SWING_RIDE_STOP_POWER_EPS": 0.03,    # 이 값 이하 + 일정 시간 유지면 정지로 간주
    "SWING_RIDE_STOP_HOLD_SEC": 0.35,     # 정지 임계 유지 시간(초)
    "SWING_RIDE_MIN_RIDE_SEC": 3.0,       # 탑승 후 최소 유지 시간(자동 하차 방지)
    "SWING_CLICK_TO_RIDE_ENABLED": False, # True면 (구 방식) 그네 근처 클릭/키로 바로 탑승. 이벤트존 방식이면 False.

    # --- 그네 점프(드래그) 데모 ---
    "SWING_JUMP_POWER_THRESH": 0.75,          # 이 이상 파워에서만 점프 구간(화살표) 활성
    "SWING_JUMP_BACK_PEAK_FRAC": 0.88,        # 뒤 정점 판정: depth_n <= -depth_peak_n * frac
    "SWING_JUMP_FRONT_PEAK_FRAC": 0.70,       # 앞 정점 판정(완화): depth_n >= +depth_peak_n * frac
    "SWING_JUMP_MIN_DRAG_PX": 18.0,           # 드래그 최소 길이(스크린 px)
    "SWING_JUMP_DIST_MIN_PX": 24.0,           # 점프 최소 거리(월드 px)
    "SWING_JUMP_DIST_MAX_PX": 170.0,          # 점프 최대 거리(월드 px)
    "SWING_JUMP_ARROW_FX_DIR": "assets/images/fx/swingjumparrow",  # 화살표 FX 폴더
    "SWING_JUMP_RELEASE_ANY_FORWARD": True,   # True면 앞 정점 '근처'가 아니라 앞으로 가는 구간이면 릴리즈 허용
    "SWING_JUMP_ARROW_OFFSET_X_PX": 30.0,     # 그네 기준 오른쪽 오프셋(월드 px)
    "SWING_JUMP_ARROW_HEIGHT_PX": 80.0,       # 화살표 길이(스크린 px, 논리)
    "SWING_JUMP_ARROW_SHOW_PEAK_FRAC": 0.82,  # |depth_n| >= depth_peak_n*frac 일 때(최대 진폭 근처) 계속 표시
    "SWING_JUMP_EASY_MIN_POWER": 0.15,        # 이 이상이면 '짧은 점프'는 거의 항상 발동
    "SWING_JUMP_LEVELS": 10,                  # 거리 등급 개수
    "SWING_JUMP_DIST_MIN_STEP_PX": 12.0,      # 최단 점프(월드 px)
    "SWING_JUMP_DIST_MAX_STEP_PX": 120.0,     # 최장 점프(월드 px)
    "SWING_JUMP_PRESS_FRAC": 0.82,            # 누르기 판정: depth_n <= -depth_peak_n*frac
    "SWING_JUMP_RELEASE_FRAC": 0.82,          # 떼기 판정: depth_n >= +depth_peak_n*frac
    "SWING_JUMP_MIN_HOLD_MS": 220,            # 너무 짧게 누르면(펌프와 혼동) 점프 대신 펌프로 처리

    # cycle_zoom_debug(DEV_CMD) 시 순환할 줌 값
    "DEBUG_ZOOM_STEPS": [1.0, 2.0],

    # --- 점프(도랑) / 미니게임 확장 ---
    # 마스크에서 도랑: R,G 낮고 B 높은 픽셀(맵 제작 시 이 색으로 도랑 칠하기). 걷기 레이어 색과 겹치지 않게 조정.
    "DITCH_COLOR_R_MAX": 90,
    "DITCH_COLOR_G_MAX": 90,
    "DITCH_COLOR_B_MIN": 200,
    # 직선 이동 구간에서 이 거리(px) 이하의 도랑만 자동 점프로 건넜다가 목표까지 계속 걷기 (오카리나식)
    "JUMP_MAX_GAP_PX": 30,
    # 점프 높이(픽셀). 자동 조절 기본 최대치
    "JUMP_ARC_HEIGHT": 50,
    # 도랑 폭(span)에 따른 자동 점프 높이/시간 조절
    "JUMP_ARC_HEIGHT_MIN": 30, #10
    "JUMP_ARC_HEIGHT_MAX": 50,
    # dist(px) * 이 값 = 기본 점프 시간(ms) (최종은 MIN/MAX로 클램프)
    "JUMP_DUR_PER_PX": 12.0,
    # span 비율(0~1)에 따른 시간 배수 (좁으면 더 짧게, 넓으면 더 길게)
    "JUMP_DUR_SPAN_MUL_MIN": 0.85,
    "JUMP_DUR_SPAN_MUL_MAX": 1.15,
    "JUMP_MIN_DURATION_MS": 220,
    "JUMP_MAX_DURATION_MS": 520,
    "JUMP_PATH_MERGE_EPS": 1.6,
    "JUMP_LAND_GOAL_SNAP_PX": 4.0,
    # 도랑 점프 착지 보정: 착지점에서 진행 방향으로 추가 전진(px) 시도 (walk 위에서만)
    "JUMP_LAND_FORWARD_PX": 8.0,
    "JUMP_LAND_FORWARD_MAX_PX": 18.0,
    "JUMP_LAND_FORWARD_STEP_PX": 2.0,
    # 목표점 스냅: 클릭/목표가 도랑(또는 벽)일 때 주변 walk로 이동 목표를 자동 보정
    "TARGET_SNAP_TO_WALK": True,
    "TARGET_SNAP_MAX_R_PX": 48,
    "TARGET_SNAP_STEP_PX": 2,
    # 이벤트 MOVE: force 생략 시 마스크·이동불가 타일 무시(스크립트 연출). false 로 두면 A*·walkable 적용.
    "EVENT_MOVE_FORCE_DEFAULT": True,

    # 길찾기(A*): 큰 격자는 빠르지만 좁은 모서리에선 이웃이 전부 막혀 실패하기 쉬움 → 세밀 격자·코너 탈출 BFS
    "PATHFIND_GRID_PX": 5,
    "PATHFIND_GRID_FINE_PX": 3,
    "PATHFIND_GRID_ULTRA_PX": 0,
    "PATHFIND_MAX_VISITED": 3800,
    "PATHFIND_CORNER_ESCAPE_ENABLED": True,
    "PATHFIND_ESCAPE_STEP_PX": 2,
    "PATHFIND_ESCAPE_MAX_NODES": 3200,
    "PATHFIND_ESCAPE_MAX_DIST_PX": 96.0,
    "PATHFIND_ESCAPE_MIN_BEFORE_REPLAN_PX": 4.0,
    "PATHFIND_ESCAPE_MIN_OPEN_NEIGHBORS": 0,

    # 캐릭터/오브젝트 자연 회피: 이동 중 엔티티에 막히면 멈추지 않고 A* 재계획으로 우회.
    # 성능 위해 재계획은 쿨다운/누적횟수/포기시간으로 제한한다(밀어내기 separation 없음).
    "AVOID_ENABLED": True,
    "AVOID_REPLAN_COOLDOWN_MS": 350,  # 재계획 사이 최소 간격
    "AVOID_MAX_REPLANS": 4,           # 연속 막힘 동안 허용할 재계획 최대 횟수
    "AVOID_NPC_WAIT_MS": 250,         # 움직이는 NPC가 막으면 이만큼만 양보 후 비껴 감
    "AVOID_GIVEUP_MS": 1500,          # 이 시간 내내 못 뚫으면 정지
    # 스티어링(벽 슬라이드): 막히면 즉시 목표 방향 기준 좌우로 틀어 비껴 간다.
    "AVOID_STEER_STEP_DEG": 18,       # 각도 탐색 간격(작을수록 촘촘/부드럽지만 약간 더 연산)
    "AVOID_STEER_MAX_DEG": 105,       # 최대 비껴가기 각도(이보다 더 틀어야 하면 A*에 맡김)

    # FOLLOW 재경로계산(성능): 목표점이 바뀌어도 매 프레임 A* 하지 않도록 제한
    "FOLLOW_REPLAN_MS": 220, #220
    "FOLLOW_REPLAN_DIST_PX": 24.0, #24
    # 리더 뒤 목표점을 픽셀 격자로 반올림(미세 플로트 변동으로 인한 불필요 재계획·떨림 완화)
    "FOLLOW_SLOT_QUANTIZE_PX": 4, #4

    # 캐릭터 발밑 타원 그림자 (비스듬한 시점용). 점프 시 동작은 세이브 jump_shadow_mode
    "CHARACTER_SHADOW_ENABLED": True,
    "SHADOW_COLOR": (18, 18, 38),
    "SHADOW_BASE_ALPHA": 70,
    "SHADOW_ELLIPSE_RX": 12,
    "SHADOW_ELLIPSE_RY": 4,
    "SHADOW_OFFSET_X": 0,
    "SHADOW_OFFSET_Y": 0,
    # 점프 중 그림자: 높을수록 작고 옅어짐 (ground 모드)
    "SHADOW_JUMP_SIZE_MUL_MIN": 0.4,
    "SHADOW_JUMP_ALPHA_MUL_MIN": 0.22,




    # 초기값
    "progress_wateringcan":1001,
    "progress_frog_minigame_win": 0,
    "progress_frog_seed": 0,
    "progress_frog_minigame_tried": 0,
    "progress_fishing_win": 0,
    "score_frog_trial_best": 0,
    "score_frog_trial_last": 0,
}

# 맵별 필드 틸트·쉬어 기본값 (맵 진입 시 field_runtime.apply_map_field_defaults)
MAP_FIELD_DEFAULTS = {
    "default": {
        "tilt_on": None,
        "shear_on": None,
    },
    "bg_jjangpu": {
        "tilt_on": False,
        "shear_on": True,
    },
    "bg_baseball1": {
        "tilt_on": False,
        "shear_on": False,
    },
}


def resolve_map_field_defaults(map_id: str) -> dict:
    """맵 ID → {tilt_on: bool, shear_on: bool}."""
    out: dict = {}
    for src in (
        MAP_FIELD_DEFAULTS.get("default"),
        MAP_FIELD_DEFAULTS.get(str(map_id or "").strip()),
    ):
        if not isinstance(src, dict):
            continue
        for key in ("tilt_on", "shear_on"):
            val = src.get(key)
            if val is not None:
                out[key] = bool(val)
    if "tilt_on" not in out:
        out["tilt_on"] = bool(CONFIG.get("FIELD_PERSPECTIVE_DEFAULT_ON", False))
    if "shear_on" not in out:
        out["shear_on"] = bool(CONFIG.get("TILT_SHEAR_ENABLED", False))
    return out


# 야구장 필드 미니게임 — 전역 기본값 (snake_case).
# 맵별 좌표·밸런스는 world_data.json → [맵ID].baseball 에서 덮어씀.
# exit_map/exit_pos: 미니게임 맵에서 세이브·강제종료 시 이 장소로 저장/스폰 (flow.resolve_activity_arena_exit).
BASEBALL_DEFAULTS = {
    "default_map_id": "bg_baseball1",
    "default_player_char": "nachos_a",
    "story_win_flag": "progress_baseball_story",
    "story_seed_flag": "progress_baseball_seed",
    "p2_chars": [       
        "summer_k", "boy2_k", "boy3_k", "girl1_k", "girl2_k", "girl3_k"
    ],
    "exit_map": "bg_jjangpu",
    "exit_pos": [850.0, 2310.0],
    "swings": 5,
    "gauge_time_limit_sec": 5.0,
    "gauge_sweep_end_speed_mul": 1.5,
    "npc_skill": 0.62,
    "npc_flash_sec": 0.55,
    "tilt_compressed": 0.3,
    "result_hold_sec": 2.5,
    "fan_half_deg": 37.0,
    "fan_half_deg_auto": False,
    "fan_half_margin_deg": 1.5,
    "fan_half_guide_visible": True,
    "dir_sweep_hz": 2.0,
    "pwr_sweep_hz": 2.0,
    "pwr_sweet_spot_half_width": 0.05,
    "pwr_power_sweet_spot_half_width": 0.025,
    "pwr_trap_half_width_new": 0.02,
    # 난이도 배율: 쉬움은 게이지를 느리게 하고 장타 구간을 넓히며,
    # 어려움은 게이지를 빠르게 하고 함정 구간을 넓힙니다.
    "difficulty_easy_dir_speed_mul": 0.9,
    "difficulty_easy_pwr_speed_mul": 0.85,
    "difficulty_easy_sweet_width_mul": 1.2,
    "difficulty_easy_power_sweet_width_mul": 1.15,
    "difficulty_easy_trap_width_mul": 0.8,
    "difficulty_normal_dir_speed_mul": 1.0,
    "difficulty_normal_pwr_speed_mul": 1.0,
    "difficulty_normal_sweet_width_mul": 1.0,
    "difficulty_normal_power_sweet_width_mul": 1.0,
    "difficulty_normal_trap_width_mul": 1.0,
    "difficulty_hard_dir_speed_mul": 1.1,
    "difficulty_hard_pwr_speed_mul": 1.15,
    "difficulty_hard_sweet_width_mul": 0.85,
    "difficulty_hard_power_sweet_width_mul": 0.8,
    "difficulty_hard_trap_width_mul": 1.2,
    "pwr_sweet_spot_bonus_mul": 1.1,
    "pwr_power_sweet_spot_bonus_mul": 1.2,
    "pwr_confirm_hold_sec": 1.0,
    "normal_swing_pause_sec": 0.5,
    "power_swing_pause_sec": 1.5,
    "power_swing_zoom_value": 4.0,
    "power_swing_zoom_in_sec": 0.12,
    "power_swing_zoom_restore_sec": 0.12,
    "power_swing_shake_sec": 1.0,
    "power_swing_shake_amp_px": 50.0,
    "power_swing_shake_freq_hz": 16.0,
    "p2_switch_fade_out_sec": 0.25,
    "p2_switch_fade_hold_sec": 0.08,
    "p2_switch_fade_in_sec": 0.25,
    "swing_anim_base_sec": 0.45,
    "swing_speed_mul": 3.0,
    "pwr_trap_half_width": 0.01,
    "swing_dir_spread_ratio": 0.10,
    "swing_dir_spread_pwr_ratio": 0.02,
    "pop_foul_carry_px": 58.0,
    "pop_foul_angle_deg": 180.0,
    "pop_foul_angle_spread_deg": 12.0,
    "pop_foul_height_px": 36.0,
    "pop_foul_flight_dur_sec": 0.0,
    "foul_carry_px": 20.0,
    "max_carry_px": 960.0,
    "carry_distance_mul": 1.3,
    "flight_height_mul": 1.5,
    "ball_motion_speed_mul": 0.9,
    "px_per_meter": 12.39,
    "tee_height": 16.0,
    "bounce_duration_mul": 1.3,
    "bounce_travel_carry_ratio": 0.38,
    "bounce_count": 3,
    "bounce_height_carry_ratio": 0.028,
    "roll_travel_carry_ratio": 0.062,
    "roll_speed_max": 108.0,
    "roll_speed_min": 52.0,
    "roll_speed_exp": 0.55,
    "mask_infield_white_min": 200,
    "mask_foul_alpha_max": 128,
    "mask_landing_sample_radius_px": 6,
    "mask_fence_color": [255, 255, 0],
    "mask_fence_color_tol": 48,
    "fence_clear_height_px": 18.0,
    "fence_bounce_carry_ratio": 0.14,
    "fence_bounce_height_mul": 0.55,
    "fence_bounce_count_max": 2,
    "fence_trace_step_px": 4.0,
    "home_run_mask_blue_min": 170,
    "home_run_mask_chroma_max": 130,
    "fielder_chase_speed_mul": 0.7,
    "fielder_chase_repath_sec": 0.12,
    "fielder_chase_radius_px": 220.0,
    "fielder_catch_radius_px": 28.0,
    "fielder_catch_max_height_px": 6.0,
    "fielder_catch_hold_sec": 0.4,
    "fielder_stop_decay_sec": 0.2,
    "intro_field_tour_enabled": True,
    "intro_tilt_flat": 1.0,
    "intro_zoom_wide": 0.75,
    "intro_zoom_play": 2.0,
    "intro_zoom_dur_sec": 0.55,
    "intro_zoom_end_dur_sec": 0.12,
    "intro_pan_dur_sec": 0.0,
    "intro_hold_sec": 1.0,
    "bat_cam_return_sec": 0.3,
    "announce_wait_before_start_sec": 1.0,
    "announce_title_sec": 1.0,
    "announce_swing_sec": 1.0,
    "announce_result_sec": 2.0,
    "announce_pause_sec": 1.0,
    "announce_turn_sec": 1.0,
    "announce_match_end_sec": 2.0,
    "ball_touch_radius_px": 36.0,
    "turn_pause_sec": 1.35,
}

# 레이스 필드 미니게임 — 전역 기본값.
# 맵별 path·exit 는 world_data.json → [맵ID].racing 에서 덮어씀.
# exit_map/exit_pos: 서킷 맵 세이브 금지 → 여기(또는 맵별 racing.exit_*)로 저장/스폰.
# path: 월드 좌표 폴리라인(닫힌 루프 권장). 마스크 경로 대신 가벼움.
RACING_DEFAULTS = {
    "default_map_id": "bg_town",
    "default_player_char": "summer_k",
    "char_pick": [
        "summer_k", "boy1_k", "boy2_k", "boy3_k", "girl1_k", "girl2_k", "girl3_k",
    ],
    "exit_map": "bg_jjangpu",
    "exit_pos": [850.0, 2310.0],
    # bg_town(640x480) 임시 루프 — 도로가 생기면 world_data.racing.path 로 교체
    "path": [
        [120.0, 250.0],
        [220.0, 170.0],
        [360.0, 150.0],
        [500.0, 190.0],
        [560.0, 280.0],
        [480.0, 360.0],
        [320.0, 380.0],
        [180.0, 340.0],
    ],
    "closed": True,
    "start_s": 0.0,
    "start_spacing": 22.0,   # 스타트 그리드: 플레이어 뒤로 NPC 간격(px along path)
    "lane_width": 30.0,      # 상/하 차선 오프셋(경로 법선 방향, 월드 px) = 도로 레인 1개 폭
    # --- 경로 기반 도로 자동 그리기 ---
    # 레이스 시작 시 경로를 중심으로 bg에 3레인 도로를 덧그린다 (맵에 직접 그릴 필요 없음).
    # 레인 순서: 1=A(상) / 2=B(중) / 3=C(하). 색은 맵별 racing.road_lane_colors 로 덮어쓰기 가능.
    "road_draw_enabled": True,
    "road_lane_colors": [
        [210, 60, 60],    # 1번 레인(A) 빨강
        [235, 205, 70],   # 2번 레인(B) 노랑
        [70, 115, 230],   # 3번 레인(C) 파랑
    ],
    "road_border_color": [40, 40, 46],  # 도로 가장자리 테두리색
    "road_border_px": 3.0,              # 테두리 두께(월드 px)
    "laps": 3,
    "max_speed": 200.0,      # 직선 최고속 (월드 px/s)
    "min_corner_speed": 50.0,
    "accel": 80.0,           # 출발·가속 (서서히 붙는 느낌)
    "brake": 40.0,           # 코너 감속
    "corner_brake": 1.4,     # 앞 꺾임(rad)에 비례한 목표속도 감소
    "corner_lookahead_px": 90.0,  # 앞 경로점 chase 거리(클수록 일찍 돌기 시작)
    "turn_rate_rad": 2.2,    # 헤딩이 목표 방향으로 따라가는 각속도 — 코너 관성
    "lane_lerp": 4.2,        # 차선 목표로 붙는 속도
    # 같은 레인에 다른 레이서가 이 경로거리(px) 이내면 진입 불가(겹침 방지)
    "lane_occupy_s": 40.0,
    # 네임박스: 발 화면좌표에서 위로 올린 고정 px (Mode7 원근 스케일 없음 · 오버레이급)
    "namebox_head_off_px": 42.0,
    # --- 레인 화살표 HUD (캐릭터 기준 · 한 칸씩 A↔B↔C) ---
    # 에셋이 없으면 삼각형 화살표를 코드로 자동 생성.
    # 애니 세트(선택): assets/images/ui/racing/<lane_btn_*_anim>/ 폴더 PNG 시퀀스
    #   또는 assets/images/ui/racing/<name>_0.png … 번호 시퀀스 (_load_numbered_ui_sequence).
    # 카메라 옆: 캐릭터 뒤 ▲▼ / 카메라 뒤: 캐릭터 아래 ◀▶
    "lane_btn_up_anim": "lane_up",
    "lane_btn_down_anim": "lane_down",
    "lane_btn_left_anim": "lane_left",
    "lane_btn_right_anim": "lane_right",
    "lane_btn_anim_fps": 8.0,
    "lane_btn_size_px_320": 40.0,
    "lane_btn_gap_px_320": 10.0,
    "lane_btn_char_gap_px_320": 8.0,  # 캐릭터와 버튼 사이 간격
    "lane_btn_y_down_px_320": 40.0,   # 뒤/비스듬히 ◀▶ 를 캐릭터 기준 아래로
    "lane_btn_alpha": 128,            # 반투명 (~50%)
    "lane_btn_margin_x_frac": 0.03,   # (레거시·폴백) 화면 왼쪽 여백
    "lane_btn_center_y_frac": 0.55,   # (레거시·폴백) 세로 중심
    "path_pull": 2.2,        # 경로로 끌어당기는 힘(작을수록 코너에서 바깥으로 더 나감)
    "path_soft_follow": 0.5, # (레거시·미사용) path_pull 사용
    "cam_side_sign": -1.0,   # Mode7: heading + sign*π/2 = 진행 방향의 오른쪽에서 비춤
    "cam_oblique_rad": 0.4,  # 비스듬히: 뒤 추적 + 이 각만큼 yaw (≈45°)
    "cam_turn_rate_rad": 3.4,  # 카메라가 플레이어 heading을 따라 도는 각속도(스냅 방지)
    "rotate3d_strength": 1.0,
    "countdown_sec": 3.0,
    "finish_hold_sec": 2.2,
    "debug_draw_path": False,
    # --- 미니맵 오버레이 (마리오카트식) ---
    # 오른쪽 위 exit 버튼 밑에 전체 맵 축소판 + 레이서 위치 점 + 경과 시간 표시
    "minimap_enabled": True,
    "minimap_scale": 0.0625,     # 전체 맵 대비 축소 비율 (1/16 → 면적 기준 1/8의 1/4)
    "minimap_alpha": 215,        # 축소맵 투명도 (0~255)
    "minimap_margin_x_frac": 0.015,  # 화면 오른쪽 여백 (폭 비율)
    "minimap_top_frac": 0.075,   # exit 버튼 바로 밑 시작 y (높이 비율)
    # --- 경로 위 아이템 포인트 ---
    # items: [{s, lane:"A"|"B"|"C", type, kind?, consume?, ...}, ...]
    # kind: normal | secret | roulette | summon  (기본 normal)
    #   secret — 시크릿 상자(먹을 때 룰렛 UI 후 speed/slow/swap 중 랜덤)
    #   roulette — 발판 위 아이템이 A→B→C→A 로 이동 (roulette_period_sec)
    #   summon — 밟으면 경로 어딘가에 아이템 소환 + 번쩍 표시
    # consume: true면 획득 후 영구 제거. 기본 false → 숨김 후 item_respawn_sec 뒤 재등장
    # s = 경로 누적거리(px). lane A=상단 B=중앙 C=하단.
    "items": [],
    "item_pick_radius": 18.0,
    "item_draw_height": 10.0,
    "item_respawn_sec": 3.0,  # 고정 아이템 획득 후 재등장까지
    "item_random_enabled": False,
    "item_random_count": 6,
    # 청정 구간: [[s0,s1], ...] — 아이템(고정·랜덤·소환) / 날씨 완전 무효과
    "clean_zones": [],
    # 맵별 날씨 (전역 랜덤). enabled=false 면 비활성.
    # rain: 구간 통과 시 감속 / lightning: 구간 진입 시 1회 꽝!(정지)
    # 애니(선택): assets/images/ui/racing/<weather_*_anim>/ — 없으면 비=큰그림자, 번개=빨간깜빡
    "weather": {
        "enabled": True,
        "rain": {"chance_per_lap": 0.45, "zone_len_s": [70.0, 160.0], "slow_mul": 0.72},
        "lightning": {
            "chance_per_lap": 0.22,
            "zone_len_s": [40.0, 90.0],
            "strike_chance": 1.0,
            "freeze_sec": 1.15,
        },
    },
    "weather_rain_anim": "rain",
    "weather_lightning_anim": "lightning",
    # 슬립스트림 — 최고속 90%↑ 노란 에프터(길이=스피드업×2). 뒤차 1초 추종 시 ×1.2·초록 에프터
    "slipstream_min_speed_frac": 0.90,
    "afterburner_yellow_off_frac": 0.84,  # 노란 꼬리 끔(히스테리시스) — 깜빡임 방지
    "slipstream_follow_s": 72.0,  # 노란 꼬리 길이와 맞춤 (스피드업 기본 ~36의 2배)
    "slipstream_lane_tol": 0.42,
    "slipstream_hold_sec": 1.0,  # 노란 꼬리 밟는 시간 → 부스트 발동
    "slipstream_boost_mul": 1.20,  # 추종 부스트 (~+20%)
    "slipstream_accel_bonus": 18.0,
    "slipstream_bump_s": 22.0,
    "slipstream_bump_front_boost": 1.35,
    "slipstream_bump_rear_slow": 0.45,
    "slipstream_bump_slow_sec": 1.4,
    # 추돌 타격 FX (접촉점 빨간 스파크, 짧게·작게)
    "bump_hit_sec": 0.28,
    "bump_hit_radius_px": 7.0,
    # 에프터버너: 스피드업=빨강(짧음), 최고속=노랑(2배), 슬립부스트=초록
    "speed_afterburner_sec": 1.1,
    "afterburner_len_speed": 36.0,
    "afterburner_len_slip": 72.0,
    # 시크릿 상자 룰렛 UI
    "secret_spin_sec": 1.35,
    "roulette_lane_period_sec": 0.55,
    "summon_flash_sec": 1.6,
    # --- 레이스 탑승 애니 (몸=seat_idle + 뒤쪽 자벌레 underlay) ---
    # 에셋: assets/images/character/racing/<inchworm_anim>_left/
    # 자벌레 초당 프레임은 r.speed 에 비례 (0→정지, max_speed→inchworm_fps_at_max)
    "inchworm_anim": "moveinchworm_racing",  # load_racing_overlay_frames 애니 세트명
    "inchworm_fps_at_max": 14.0,             # 최고속(max_speed)일 때 자벌레 프레임/초
    "inchworm_speed_eps": 1.0,               # 이 속도(px/s) 이하면 애니 완전 정지(fps=0)
    # --- 메뉴: 맵·랩·난이도 ---
    # map_pick: bg_circuit01~04. 월드 키가 bg_circurt* 이면 aliases 로 매칭.
    "map_pick": [
        {"id": "bg_circuit01", "aliases": ["bg_circurt01"], "label": ""},
        {"id": "bg_circuit02", "aliases": ["bg_circurt02"], "label": ""},
        {"id": "bg_circuit03", "aliases": ["bg_circurt03"], "label": ""},
        {"id": "bg_circuit04", "aliases": ["bg_circurt04"], "label": ""},
    ],
    "lap_options": [1, 3, 5, 7],
    "difficulty_default": "normal",
    # --- 완주 세레모니 (마리오카트식) ---
    "ceremony_sec": 5.0,           # 계속 주행 + 카메라 정면 + 등수 표시
    "ceremony_cam_turn_rad": 1.35, # 세레모니 중 카메라가 정면으로 도는 각속도
    "ceremony_fade_sec": 0.55,     # 메뉴 전환 페이드아웃/인
    "ceremony_rank_msg": {
        "1": "1등이야 오예~",
        "2": "2등이야~",
        "3": "3등이다 힝~",
    },
    # Mode7 해상도 옵션 (레이스 옵션). quality_scale 만 변경 — 좌표·투영 동일, 시각만 거칠어짐.
    "mode7_quality": "medium",
    "mode7_quality_scales": {"high": 1.0, "medium": 0.72, "low": 0.50, "lowest": 0.35},
    "mode7_quality_scales_android": {"high": 0.50, "medium": 0.42, "low": 0.32, "lowest": 0.25},
}

# 레이스 난이도 — NPC AI 레인 변경 주기·속도 배율
RACING_DIFFICULTY = {
    "easy": {
        "label": "쉬움",
        "npc_speed_mul": 0.82,
        "ai_lane_min": 2.0,
        "ai_lane_max": 3.8,
    },
    "normal": {
        "label": "보통",
        "npc_speed_mul": 1.0,
        "ai_lane_min": 1.2,
        "ai_lane_max": 3.0,
    },
    "hard": {
        "label": "어려움",
        "npc_speed_mul": 1.18,
        "ai_lane_min": 0.55,
        "ai_lane_max": 1.5,
    },
}

# 레이스 아이템/효과 레지스트리 — type 키 → 기본 효과·에셋
# effect: speed_mul | swap | freeze (freeze 는 날씨 번개 등에도 사용)
RACING_ITEM_TYPES = {
    "speed": {
        "label": "속도 증가",
        "effect": "speed_mul",
        "strength": 1.45,
        "duration_sec": 2.2,
        "asset": "item_racing001",
        "placeholder_color": (60, 210, 110),
        "roulette_color": (80, 230, 130),
    },
    "slow": {
        "label": "속도 감소",
        "effect": "speed_mul",
        "strength": 0.55,
        "duration_sec": 2.0,
        "asset": "item_racing002",
        "placeholder_color": (220, 80, 70),
        "roulette_color": (240, 100, 90),
    },
    "swap": {
        "label": "위치 교환!",
        "effect": "swap",
        "strength": 1.0,
        "duration_sec": 0.0,
        "asset": "item_racing003",
        "placeholder_color": (200, 120, 240),
        "roulette_color": (220, 150, 255),
    },
    "secret": {
        "label": "???",
        "effect": "secret",
        "strength": 1.0,
        "duration_sec": 0.0,
        "asset": "item_racing_secret",
        "placeholder_color": (255, 210, 80),
        "roulette_color": (255, 230, 120),
    },
    "roulette_pad": {
        "label": "룰렛 발판",
        "effect": "roulette_pad",
        "strength": 1.0,
        "duration_sec": 0.0,
        "asset": "item_racing_roulette",
        "placeholder_color": (100, 180, 255),
        "roulette_color": (120, 200, 255),
    },
    "summon_pad": {
        "label": "소환 발판",
        "effect": "summon_pad",
        "strength": 1.0,
        "duration_sec": 0.0,
        "asset": "item_racing_summon",
        "placeholder_color": (255, 160, 60),
        "roulette_color": (255, 190, 90),
    },
}

# 시크릿 상자·소환 시 실제로 나올 수 있는 효과 풀
RACING_MYSTERY_EFFECT_POOL = ("speed", "slow", "swap")
# 추첨 가중치 — 기본 1.0, 위치 교환(swap)은 다른 아이템의 30%
RACING_MYSTERY_EFFECT_WEIGHTS = {
    "speed": 1.0,
    "slow": 1.0,
    "swap": 0.3,
}

# 차선 문자 → 경로 법선 오프셋 부호 (racing.LANE_*)
RACING_LANE_LETTERS = {
    "A": -1.0,  # 상단
    "B": 0.0,   # 중앙
    "C": 1.0,   # 하단
}

# 낚시터 정의 — 물 영역·낚시대 위치(이벤트박스와 별도).
# 이벤트박스는 world_data.json event_zones, 물가 좌표는 여기서 관리.
# (에디터: 존은 편집 가능, 물 rect는 추후 전용 레이어 추가 예정)
FISHING_PONDS = {
    "jjangpu_water1": {
        "map_id": "bg_jjangpu",
        # 왼쪽 물가에 서서 오른쪽으로 찌를 던지도록 시작 위치를 재배치.
        "stand": [459.0, 1094.0],
        "face": "right",
        # 물가 491,1049 — 620,1139
        "water_rect": [491.0, 1049.0, 129.0, 90.0],
        "cast_near": 36.0,
        "cast_far": 116.0,
        "success_dist": 24.0,
        "max_shadows": 4,
        "hook_radius": 20.0,
        "bite_shake_sec": 0.95,
        # --- 난이도 튜닝 (activities/fishing.py 가 읽음) ---
        # [연타 당기기] reel_tap_step_base + reel_tap_step_pull×pull / 연타 1회 이동량(px)
        "reel_tap_step_base": 2.0,
        "reel_tap_step_pull": 11.0,
        "reel_tap_pull_gain": 0.058,
        # [연타 안 할 때] 물고기가 다시 멀어지는 속도
        "reel_fish_drift_back": 0.012,
        "reel_pull_decay": 0.028,
        # [몸부림] struggle_drift_speed=캐릭터 반대로 밀림(px/s), duration=지속시간
        "struggle_drift_speed": 14.0,
        "struggle_duration_min": 0.9,
        "struggle_duration_max": 1.6,
        # [몸부림 빈도] cooldown 짧을수록 자주 반항. near_shore_freq=가까운 물가 입질 보너스
        "struggle_cooldown_min": 0.8,
        "struggle_cooldown_max": 1.4,
        "struggle_near_shore_freq": 0.55,
        "near_shore_cast_ratio": 0.45,
        # [줄 긴장] 1.0 넘으면 실패. struggle 중 연타 시 tension_tap_penalty_struggle 추가
        "tension_fail": 1.0,
        "tension_build_struggle": 0.1,
        "tension_decay_reel": 0.07,
        "tension_tap_relief": 0.035,
        "tension_tap_penalty_struggle": 0.2,
        "fish_types": [
            {"id": "잉어", "rarity": "common", "weight": 5, "surface_min": 10.0, "surface_max": 15.0, "bite_chance": 0.55},
            {"id": "붕어", "rarity": "common", "weight": 4, "surface_min": 9.0, "surface_max": 14.0, "bite_chance": 0.5},
            {"id": "송어", "rarity": "uncommon", "weight": 2, "surface_min": 7.0, "surface_max": 11.0, "bite_chance": 0.45},
            {"id": "금붕어", "rarity": "rare", "weight": 1, "surface_min": 5.0, "surface_max": 8.0, "bite_chance": 0.35},
        ],
    },
}

# UI 폰트 레지스트리: 논리 이름 → 프로젝트 루트 기준 .ttf 경로.
# 값이 None 이거나 파일이 없으면 런타임에서 pygame 기본 폰트를 씁니다.
# 에디터 FONT 창의「폰트 종류」는 이 키(default/dialog/logo)를 고릅니다.
UI_FONT_FILES = {
    "default": "assets/fonts/NanumGothic.ttf",
    "dialog": "assets/fonts/NanumGothic.ttf",
    "logo": "assets/fonts/Pinkfong Baby Shark Font_ Bold.ttf",
}


# ---------------------------------------------------------------------------
# 용도별 폰트 프로필 — 에디터 FONT 창에서 슬롯마다 수정
# font_key: UI_FONT_FILES 키
# size_320: 320 설계 기준 글자 크기 (WIDTH/320 으로 스케일)
# color / outline_*: 채움·테두리
# force_color: True면 render() 에 넘긴 색 무시하고 color 사용
# antialias: True면 글리프 가장자리 부드럽게(SDL_ttf AA). False면 단단한 픽셀 느낌
# soft_px_320: 테두리 외곽 번짐(글로우). 0=선명, 클수록 테두리가 부드럽게 퍼짐
# ---------------------------------------------------------------------------
UI_FONT_PROFILE_DEFAULTS = {
    "dialog": {
        "label": "대화 본문",
        "desc": "SAY 대사 텍스트(텍스트박스 안)",
        "font_key": "dialog",
        "size_320": 10,
        "color": (0, 0, 0),
        "outline_enabled": True,
        "outline_px_320": 1,
        "outline_color": (255, 255, 255),
        "force_color": True,
        "antialias": True,
        "soft_px_320": 0,
    },
    "dialog_name": {
        "label": "대화 이름",
        "desc": "SAY 화자 이름(Who)",
        "font_key": "dialog",
        "size_320": 12,
        "color": (0, 0, 0),
        "outline_enabled": True,
        "outline_px_320": 1,
        "outline_color": (255, 255, 255),
        "force_color": True,
        "antialias": True,
        "soft_px_320": 0,
    },
    "ui": {
        "label": "일반 UI / 오버레이",
        "desc": "OVERLAY_UI 버튼·문구, 나가기 확인 등",
        "font_key": "default",
        "size_320": 14,
        "color": (0, 0, 0),
        "outline_enabled": True,
        "outline_px_320": 1,
        "outline_color": (255, 255, 255),
        "force_color": True,
        "antialias": True,
        "soft_px_320": 0,
    },
    "object_label": {
        "label": "오브젝트 라벨",
        "desc": "맵 오브젝트 text_label (TV 등)",
        "font_key": "default",
        "size_320": 16,
        "color": (0, 0, 0),
        "outline_enabled": True,
        "outline_px_320": 1,
        "outline_color": (255, 255, 255),
        "force_color": True,
        "antialias": True,
        "soft_px_320": 0,
    },
    "hud_fishing": {
        "label": "낚시 HUD",
        "desc": "낚시 미니게임 화면 안내·성공 문구",
        "font_key": "default",
        "size_320": 12,
        "color": (0, 0, 0),
        "outline_enabled": True,
        "outline_px_320": 1,
        "outline_color": (255, 255, 255),
        "force_color": True,
        "antialias": True,
        "soft_px_320": 0,
    },
    "hud_baseball": {
        "label": "야구 HUD",
        "desc": "야구 메뉴·점수판·게이지 안내 등",
        "font_key": "default",
        "size_320": 12,
        "color": (0, 0, 0),
        "outline_enabled": True,
        "outline_px_320": 1,
        "outline_color": (255, 255, 255),
        "force_color": True,
        "antialias": True,
        "soft_px_320": 0,
    },
    "hud_racing": {
        "label": "레이스 HUD",
        "desc": "레이스 메뉴·카운트다운·완주 문구",
        "font_key": "default",
        "size_320": 14,
        "color": (0, 0, 0),
        "outline_enabled": True,
        "outline_px_320": 1,
        "outline_color": (255, 255, 255),
        "force_color": True,
        "antialias": True,
        "soft_px_320": 0,
    },
    "logo": {
        "label": "타이틀 / 로고",
        "desc": "TITLE·홈런 연출 등 logo 폰트",
        "font_key": "logo",
        "size_320": 36,
        "color": (0, 0, 0),
        "outline_enabled": True,
        "outline_px_320": 1,
        "outline_color": (255, 255, 255),
        "force_color": True,
        "antialias": True,
        "soft_px_320": 0,
    },
    "screen_caption": {
        "label": "화면 전환 자막",
        "desc": "SCREEN 스텝 hold 텍스트",
        "font_key": "default",
        "size_320": 14,
        "color": (0, 0, 0),
        "outline_enabled": True,
        "outline_px_320": 1,
        "outline_color": (255, 255, 255),
        "force_color": True,
        "antialias": True,
        "soft_px_320": 0,
    },
}

# 에디터 슬롯 목록 순서
UI_FONT_PROFILE_ORDER = (
    "dialog",
    "dialog_name",
    "ui",
    "object_label",
    "hud_fishing",
    "hud_baseball",
    "hud_racing",
    "logo",
    "screen_caption",
)

# CONFIG 에도 넣어 런타임·저장이 같은 객체를 쓰게 함
CONFIG["UI_FONT_PROFILES"] = {
    k: dict(v) for k, v in UI_FONT_PROFILE_DEFAULTS.items()
}









# path 규칙 (object_defs.json 주석용 요약):
# - 단일: images/object/tree1.png
# - 애니: images/object/flower1_0.png → flower1_1.png … / 폴더 images/object/grass01/
# - anim_delay_ms 생략 시 CONFIG["ANIM_DELAY"]
from entity_defs import load_char_defs, load_object_defs, reload_entity_defs

OBJ_ASSETS = load_object_defs()
CHAR_ASSETS = load_char_defs()


# ---------------------------------------------------------------------------
# Android RAM 프로필 — 3GB 기기에서 캐시·워치독을 넉넉히 (CPU 재계산↓)
# import data 시 CONFIG 로드 직후 1회 적용. main/engine 은 CONFIG.get 만 사용.
# ---------------------------------------------------------------------------

def _is_android_runtime():
    import os

    return bool(os.environ.get("ANDROID_ARGUMENT") or os.environ.get("ANDROID_PRIVATE"))


def _android_ram_profile_preset_3gb():
    """3072MB 기준. 앱+Python 여유를 두고 변환 캐시 위주로 ~0.5–0.7GB 사용."""
    return {
        "RENDER_CACHE_MB_LIMIT": 512.0,
        "RENDER_CACHE_MAX_ITEMS": 160,
        "TEMP_SURF_MB_LIMIT": 160.0,
        "SPRITE_SCALE_CACHE_MB_LIMIT": 192.0,
        "SPRITE_SCALE_CACHE_MAX_ITEMS": 768,
        "SPRITE_FIELD_SHEAR_CACHE_MB_LIMIT": 96.0,
        "SPRITE_FIELD_SHEAR_CACHE_MAX_ITEMS": 256,
        "SHEAR_PIN_CACHE_MAX_ITEMS": 32,
        "MEM_WATCHDOG_HIGH_MB": 900.0,
        "MEM_WATCHDOG_GROWTH_MB": 120.0,
        "MEM_WATCHDOG_GROWTH_TRIM_FRACTION": 0.12,
        "MEM_WATCHDOG_GC_AFTER_FULL_CLEAR": False,
        "TILT_SHEAR_STRIP_BUCKET_PX": 96,
        # Mode7: Android는 numpy 없이 get_at 폴백 → 저해상도 샘플이 필수
        # (레이스 옵션 '높음'도 ANDROID_QUALITY_CAP 로 막힘)
        "ROTATE3D_QUALITY_SCALE": 0.45,
        "ROTATE3D_ANDROID_QUALITY_SCALE": 0.45,
        "ROTATE3D_ANDROID_QUALITY_CAP": 0.50,
        "ROTATE3D_FALLBACK_X_STEP": 3,
        "ROTATE3D_FALLBACK_Y_STEP": 2,
        "ROTATE3D_ANDROID_FALLBACK_X_STEP": 3,
        "ROTATE3D_ANDROID_FALLBACK_Y_STEP": 2,
        # 인터레이스는 dst.copy() 비용이 H700에서 샘플 절감보다 클 수 있음
        "ROTATE3D_INTERLACE_ROWS": False,
    }


def _scale_android_ram_preset(preset, target_mb):
    """3072가 아닌 ANDROID_RAM_PROFILE_MB 일 때 캐시 상한만 비례 조정."""
    try:
        base = 3072.0
        t = float(target_mb)
    except (TypeError, ValueError):
        return dict(preset)
    if t <= 0.0:
        return dict(preset)
    scale = max(0.5, min(1.5, t / base))
    if abs(scale - 1.0) < 0.05:
        return dict(preset)
    scaled = dict(preset)
    for key in (
        "RENDER_CACHE_MB_LIMIT",
        "TEMP_SURF_MB_LIMIT",
        "SPRITE_SCALE_CACHE_MB_LIMIT",
        "SPRITE_FIELD_SHEAR_CACHE_MB_LIMIT",
        "MEM_WATCHDOG_HIGH_MB",
        "MEM_WATCHDOG_GROWTH_MB",
    ):
        if key in scaled:
            try:
                scaled[key] = float(scaled[key]) * scale
            except (TypeError, ValueError):
                pass
    for key in (
        "RENDER_CACHE_MAX_ITEMS",
        "SPRITE_SCALE_CACHE_MAX_ITEMS",
        "SPRITE_FIELD_SHEAR_CACHE_MAX_ITEMS",
        "SHEAR_PIN_CACHE_MAX_ITEMS",
    ):
        if key in scaled:
            try:
                scaled[key] = max(8, int(round(float(scaled[key]) * scale)))
            except (TypeError, ValueError):
                pass
    return scaled


def apply_android_ram_profile(config=None):
    """
    안드로이드에서만 CONFIG 에 RAM 프로필 merge.
    반환: 적용했으면 True, 아니면 False.
  """
    cfg = CONFIG if config is None else config
    if not _is_android_runtime():
        return False
    if not bool(cfg.get("ANDROID_RAM_PROFILE_ENABLED", True)):
        return False
    try:
        target_mb = float(cfg.get("ANDROID_RAM_PROFILE_MB", 3072) or 3072)
    except (TypeError, ValueError):
        target_mb = 3072.0
    env_mb = None
    try:
        import os

        raw = os.environ.get("SUMMERLEAF_RAM_PROFILE_MB", "").strip()
        if raw:
            env_mb = float(raw)
    except Exception:
        env_mb = None
    if env_mb is not None and env_mb > 0.0:
        target_mb = env_mb
    merged = _scale_android_ram_preset(_android_ram_profile_preset_3gb(), target_mb)
    overrides = cfg.get("ANDROID_RAM_PROFILE_OVERRIDES")
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            if k:
                merged[str(k)] = v
    for k, v in merged.items():
        cfg[k] = v
    cfg["_ANDROID_RAM_PROFILE_APPLIED"] = True
    cfg["_ANDROID_RAM_PROFILE_MB_EFFECTIVE"] = float(target_mb)
    try:
        print(
            "[CONFIG] Android RAM profile: "
            f"{int(target_mb)}MB ({len(merged)} keys, "
            f"RENDER_CACHE_MB_LIMIT={cfg.get('RENDER_CACHE_MB_LIMIT')})"
        )
    except Exception:
        pass
    return True


apply_android_ram_profile()


# ---------------------------------------------------------------------------
# 게임 UI 통합 상태 — ui.state.json
#   layout / profiles / say / activities / overlay_defaults
# 에디터 FONT 창도 여기로 저장. editor_ui_state.json 은 에디터 전용(제외).
# 구 ui_font_settings.json 은 없으면 무시, 있으면 최초 로드 폴백.
# ---------------------------------------------------------------------------

UI_STATE_PATH = "ui.state.json"
UI_FONT_SETTINGS_PATH = "ui_font_settings.json"  # 레거시 폴백(읽기 전용)

# 미니게임·오버레이 글자/레이아웃 기본값 (ui.state.json activities·overlay_defaults 가 덮어씀)
# *_px_320: 320 설계폭 기준 → scale_ui_text_px 로 스케일
UI_ACTIVITY_DEFAULTS = {
    "racing": {
        "menu_title_px_320": 14,       # 메뉴·캐릭터선택 제목 (구 하드코딩 22 → 과대)
        "menu_body_px_320": 11,        # 버튼·힌트·랩 HUD
        "countdown_px_320": 32,        # 3·2·1·GO
        "finish_px_320": 24,           # 골인
        "item_msg_px_320": 14,         # 아이템 획득 메시지
        "menu_button_width_frac": 0.72,
        "menu_button_height_frac": 0.10,
    },
    "baseball": {
        "menu_title_px_320": 14,
        "menu_body_px_320": 11,
    },
    "fishing": {
        "hud_max_px": 14,
        "success_max_px": 18,
    },
}

UI_OVERLAY_DEFAULTS = {
    "game_exit_btn": {"size": 10, "pad_x": 6, "pad_y": 3},
    "game_exit_confirm": {"text_size": 13, "button_size": 12},
}

# SAY 레이아웃 키 — ui.state.json say{} 에서 CONFIG 로 반영
UI_SAY_LAYOUT_KEYS = (
    "SAY_TEXTBOX_RECT_320",
    "SAY_LINE_GAP_PX_320",
    "SAY_NAME_GAP_PX_320",
    "SAY_BUBBLE_OFFSET_X_PX_320",
    "SAY_BUBBLE_OFFSET_Y_PX_320",
)


def ensure_ui_activity_settings(config=None) -> dict:
    """CONFIG.UI_ACTIVITY_SETTINGS 에 미니게임별 UI 수치를 채움."""
    cfg = CONFIG if config is None else config
    cur = cfg.get("UI_ACTIVITY_SETTINGS")
    if not isinstance(cur, dict):
        cur = {}
    out = {}
    for aid, defaults in UI_ACTIVITY_DEFAULTS.items():
        row = dict(defaults)
        raw = cur.get(aid)
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k in row or k.endswith("_px_320") or k.endswith("_frac") or k.endswith("_px"):
                    try:
                        if isinstance(defaults.get(k), float) or str(k).endswith("_frac"):
                            row[k] = float(v)
                        elif isinstance(defaults.get(k), int) or str(k).endswith("_px") or str(k).endswith("_px_320"):
                            row[k] = float(v)
                        else:
                            row[k] = v
                    except (TypeError, ValueError):
                        pass
        out[aid] = row
    for aid, raw in cur.items():
        if aid not in out and isinstance(raw, dict):
            out[aid] = dict(raw)
    cfg["UI_ACTIVITY_SETTINGS"] = out
    return out


def ensure_ui_overlay_defaults(config=None) -> dict:
    """CONFIG.UI_OVERLAY_DEFAULTS 채움."""
    cfg = CONFIG if config is None else config
    cur = cfg.get("UI_OVERLAY_DEFAULTS")
    if not isinstance(cur, dict):
        cur = {}
    out = {}
    for kid, defaults in UI_OVERLAY_DEFAULTS.items():
        row = dict(defaults)
        raw = cur.get(kid)
        if isinstance(raw, dict):
            row.update(raw)
        out[kid] = row
    for kid, raw in cur.items():
        if kid not in out and isinstance(raw, dict):
            out[kid] = dict(raw)
    cfg["UI_OVERLAY_DEFAULTS"] = out
    return out


def get_activity_ui(activity_id: str, key: str, default=None):
    """
    ui.state.json activities.<id>.<key> 조회.
    예: get_activity_ui('racing', 'menu_title_px_320')
    """
    ensure_ui_activity_settings()
    aid = str(activity_id or "").strip().lower()
    block = (CONFIG.get("UI_ACTIVITY_SETTINGS") or {}).get(aid) or {}
    if key in block:
        return block[key]
    fallback = (UI_ACTIVITY_DEFAULTS.get(aid) or {}).get(key, default)
    return fallback


def _rgb_tuple(value, default=(0, 0, 0)):
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return (int(value[0]), int(value[1]), int(value[2]))
        except (TypeError, ValueError):
            pass
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("(", "").replace(")", "").split(",")]
        if len(parts) >= 3:
            try:
                return (int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
            except (TypeError, ValueError):
                pass
    return (int(default[0]), int(default[1]), int(default[2]))


def _normalize_font_profile(slot_id: str, raw: dict | None) -> dict:
    """기본값 ⊕ raw → 정규 프로필 dict."""
    base = dict(UI_FONT_PROFILE_DEFAULTS.get(slot_id) or UI_FONT_PROFILE_DEFAULTS["ui"])
    if not isinstance(raw, dict):
        return base
    out = dict(base)
    if "label" in raw and str(raw.get("label") or "").strip():
        out["label"] = str(raw["label"]).strip()
    if "desc" in raw and str(raw.get("desc") or "").strip():
        out["desc"] = str(raw["desc"]).strip()
    if "font_key" in raw:
        out["font_key"] = str(raw.get("font_key") or base["font_key"]).strip() or base["font_key"]
    for num_key in ("size_320", "outline_px_320", "soft_px_320"):
        if num_key in raw:
            try:
                out[num_key] = float(raw[num_key])
            except (TypeError, ValueError):
                pass
    for col_key in ("color", "outline_color"):
        if col_key in raw:
            out[col_key] = _rgb_tuple(raw[col_key], base.get(col_key, (0, 0, 0)))
    for bkey in ("outline_enabled", "force_color", "antialias"):
        if bkey in raw:
            v = raw[bkey]
            if isinstance(v, str):
                out[bkey] = v.strip().lower() in ("1", "true", "yes", "on")
            else:
                out[bkey] = bool(v)
    # soft 클램프
    try:
        out["soft_px_320"] = max(0.0, min(8.0, float(out.get("soft_px_320", 0) or 0)))
    except (TypeError, ValueError):
        out["soft_px_320"] = 0.0
    return out


def ensure_ui_font_profiles(config=None) -> dict:
    """CONFIG.UI_FONT_PROFILES 가 슬롯을 모두 갖도록 채움."""
    cfg = CONFIG if config is None else config
    cur = cfg.get("UI_FONT_PROFILES")
    if not isinstance(cur, dict):
        cur = {}
    out = {}
    for sid in UI_FONT_PROFILE_ORDER:
        out[sid] = _normalize_font_profile(sid, cur.get(sid))
    # 알 수 없는 커스텀 슬롯도 유지
    for sid, raw in cur.items():
        if sid not in out and isinstance(raw, dict):
            out[sid] = _normalize_font_profile(sid, raw)
    cfg["UI_FONT_PROFILES"] = out
    return out


def sync_legacy_font_keys_from_profiles(config=None) -> None:
    """프로필 → 레거시 SAY_*/UI_FONT_* 키 (기존 코드 호환)."""
    cfg = CONFIG if config is None else config
    profiles = ensure_ui_font_profiles(cfg)
    d = profiles.get("dialog") or {}
    n = profiles.get("dialog_name") or {}
    u = profiles.get("ui") or {}
    cfg["SAY_FONT_KEY"] = str(d.get("font_key") or "dialog")
    cfg["SAY_FONT_SIZE_320"] = float(d.get("size_320", 10) or 10)
    cfg["SAY_NAME_FONT_SIZE_320"] = float(n.get("size_320", 12) or 12)
    cfg["SAY_TEXT_COLOR"] = _rgb_tuple(d.get("color"), (0, 0, 0))
    cfg["SAY_NAME_COLOR"] = _rgb_tuple(n.get("color"), (0, 0, 0))
    cfg["SAY_FONT_OUTLINE_ENABLED"] = bool(d.get("outline_enabled", True))
    cfg["SAY_FONT_OUTLINE_PX_320"] = float(d.get("outline_px_320", 1) or 1)
    cfg["SAY_FONT_OUTLINE_COLOR"] = _rgb_tuple(d.get("outline_color"), (255, 255, 255))
    fill = _rgb_tuple(u.get("color"), (0, 0, 0))
    cfg["UI_FONT_FILL_COLOR"] = fill
    cfg["UI_FONT_LIGHT_FILL_COLOR"] = fill
    cfg["UI_FONT_FORCE_FILL_COLOR"] = bool(u.get("force_color", True))
    cfg["UI_FONT_OUTLINE_ENABLED"] = bool(u.get("outline_enabled", True))
    cfg["UI_FONT_OUTLINE_PX_320"] = float(u.get("outline_px_320", 1) or 1)
    cfg["UI_FONT_OUTLINE_COLOR"] = _rgb_tuple(u.get("outline_color"), (255, 255, 255))


def _migrate_flat_font_settings_into_profiles(cfg: dict, raw: dict) -> None:
    """구 ui_font_settings.json (flat 키) → 프로필 반영."""
    profiles = ensure_ui_font_profiles(cfg)
    d = profiles["dialog"]
    n = profiles["dialog_name"]
    u = profiles["ui"]
    if "SAY_FONT_KEY" in raw:
        d["font_key"] = str(raw["SAY_FONT_KEY"] or "dialog")
        n["font_key"] = d["font_key"]
    if "SAY_FONT_SIZE_320" in raw:
        try:
            d["size_320"] = float(raw["SAY_FONT_SIZE_320"])
        except (TypeError, ValueError):
            pass
    if "SAY_NAME_FONT_SIZE_320" in raw:
        try:
            n["size_320"] = float(raw["SAY_NAME_FONT_SIZE_320"])
        except (TypeError, ValueError):
            pass
    if "SAY_TEXT_COLOR" in raw:
        d["color"] = _rgb_tuple(raw["SAY_TEXT_COLOR"], d["color"])
    if "SAY_NAME_COLOR" in raw:
        n["color"] = _rgb_tuple(raw["SAY_NAME_COLOR"], n["color"])
    if "SAY_FONT_OUTLINE_ENABLED" in raw:
        d["outline_enabled"] = bool(raw["SAY_FONT_OUTLINE_ENABLED"])
        n["outline_enabled"] = d["outline_enabled"]
    if "SAY_FONT_OUTLINE_PX_320" in raw:
        try:
            d["outline_px_320"] = float(raw["SAY_FONT_OUTLINE_PX_320"])
            n["outline_px_320"] = d["outline_px_320"]
        except (TypeError, ValueError):
            pass
    if "SAY_FONT_OUTLINE_COLOR" in raw:
        c = _rgb_tuple(raw["SAY_FONT_OUTLINE_COLOR"], (255, 255, 255))
        d["outline_color"] = c
        n["outline_color"] = c
    if "UI_FONT_FILL_COLOR" in raw:
        u["color"] = _rgb_tuple(raw["UI_FONT_FILL_COLOR"], u["color"])
    if "UI_FONT_FORCE_FILL_COLOR" in raw:
        u["force_color"] = bool(raw["UI_FONT_FORCE_FILL_COLOR"])
    if "UI_FONT_OUTLINE_ENABLED" in raw:
        u["outline_enabled"] = bool(raw["UI_FONT_OUTLINE_ENABLED"])
    if "UI_FONT_OUTLINE_PX_320" in raw:
        try:
            u["outline_px_320"] = float(raw["UI_FONT_OUTLINE_PX_320"])
        except (TypeError, ValueError):
            pass
    if "UI_FONT_OUTLINE_COLOR" in raw:
        u["outline_color"] = _rgb_tuple(raw["UI_FONT_OUTLINE_COLOR"], (255, 255, 255))
    # 다른 슬롯도 ui 스타일로 맞출지 — 최초 이관 시에만 비슷하게
    for sid in ("object_label", "hud_fishing", "hud_baseball", "hud_racing", "screen_caption"):
        p = profiles[sid]
        p["color"] = u["color"]
        p["outline_enabled"] = u["outline_enabled"]
        p["outline_px_320"] = u["outline_px_320"]
        p["outline_color"] = u["outline_color"]
        p["force_color"] = u["force_color"]
    cfg["UI_FONT_PROFILES"] = profiles


def _apply_ui_state_dict(cfg, raw: dict) -> int:
    """
    ui.state / 구 ui_font_settings dict → CONFIG.
    반환: 적용한 프로필 슬롯 수(대략).
    """
    n = 0
    # layout
    layout = raw.get("layout") if isinstance(raw.get("layout"), dict) else {}
    ref_w = raw.get("UI_TEXT_REFERENCE_WIDTH", layout.get("UI_TEXT_REFERENCE_WIDTH"))
    if ref_w is not None:
        try:
            cfg["UI_TEXT_REFERENCE_WIDTH"] = float(ref_w)
        except (TypeError, ValueError):
            pass

    # profiles
    if isinstance(raw.get("profiles"), dict):
        cur = ensure_ui_font_profiles(cfg)
        for sid, prow in raw["profiles"].items():
            cur[sid] = _normalize_font_profile(sid, prow if isinstance(prow, dict) else None)
            n += 1
        cfg["UI_FONT_PROFILES"] = cur
    elif any(k.startswith("SAY_") or k.startswith("UI_FONT_") for k in raw.keys()):
        _migrate_flat_font_settings_into_profiles(cfg, raw)
        n = 1

    # say layout → CONFIG
    say = raw.get("say") if isinstance(raw.get("say"), dict) else {}
    for k in UI_SAY_LAYOUT_KEYS:
        if k in say:
            cfg[k] = say[k]
        elif k in raw:
            cfg[k] = raw[k]

    # activities
    acts = raw.get("activities") if isinstance(raw.get("activities"), dict) else {}
    if acts:
        cfg["UI_ACTIVITY_SETTINGS"] = acts
    ensure_ui_activity_settings(cfg)

    # overlay_defaults
    od = raw.get("overlay_defaults") if isinstance(raw.get("overlay_defaults"), dict) else {}
    if od:
        cfg["UI_OVERLAY_DEFAULTS"] = od
    ensure_ui_overlay_defaults(cfg)

    sync_legacy_font_keys_from_profiles(cfg)
    return n


def apply_ui_state(config=None, path: str | None = None) -> bool:
    """
    ui.state.json → CONFIG (폰트 프로필·SAY 레이아웃·미니게임 UI·오버레이 기본).
    path 미지정 시 ui.state.json 우선, 없으면 구 ui_font_settings.json 폴백.
    """
    import json
    import os

    cfg = CONFIG if config is None else config
    ensure_ui_font_profiles(cfg)
    ensure_ui_activity_settings(cfg)
    ensure_ui_overlay_defaults(cfg)

    candidates = []
    if path:
        candidates.append(path)
    else:
        candidates.append(UI_STATE_PATH)
        candidates.append(UI_FONT_SETTINGS_PATH)

    p_used = None
    raw = None
    for p in candidates:
        if not p or not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw = loaded
                p_used = p
                break
        except Exception as e:
            try:
                print(f"[CONFIG] ui.state load fail ({p}): {e}")
            except Exception:
                pass

    if raw is None:
        sync_legacy_font_keys_from_profiles(cfg)
        return False

    n = _apply_ui_state_dict(cfg, raw)
    if n or p_used:
        try:
            print(f"[CONFIG] ui.state: {n} profile slots from {p_used}")
        except Exception:
            pass
    return True


def apply_ui_font_settings(config=None, path: str | None = None) -> bool:
    """하위호환 별칭 → apply_ui_state."""
    return apply_ui_state(config=config, path=path)


def save_ui_state(config=None, path: str | None = None) -> bool:
    """통합 UI 상태를 ui.state.json 에 저장 (에디터 FONT 저장도 여기로)."""
    import json

    cfg = CONFIG if config is None else config
    sync_legacy_font_keys_from_profiles(cfg)
    profiles = ensure_ui_font_profiles(cfg)
    activities = ensure_ui_activity_settings(cfg)
    overlays = ensure_ui_overlay_defaults(cfg)

    out_profiles = {}
    for sid, prow in profiles.items():
        row = {}
        for k, v in prow.items():
            if isinstance(v, tuple):
                row[k] = [int(v[0]), int(v[1]), int(v[2])] if len(v) >= 3 else list(v)
            else:
                row[k] = v
        out_profiles[sid] = row

    say_out = {}
    for k in UI_SAY_LAYOUT_KEYS:
        if k in cfg:
            val = cfg[k]
            if isinstance(val, tuple):
                say_out[k] = list(val)
            else:
                say_out[k] = val

    out = {
        "version": 1,
        "layout": {
            "UI_TEXT_REFERENCE_WIDTH": float(cfg.get("UI_TEXT_REFERENCE_WIDTH", 320) or 320),
        },
        "profiles": out_profiles,
        "say": say_out,
        "activities": activities,
        "overlay_defaults": overlays,
    }
    p = path or UI_STATE_PATH
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return True
    except Exception as e:
        try:
            print(f"[CONFIG] ui.state save fail: {e}")
        except Exception:
            pass
        return False


def save_ui_font_settings(config=None, path: str | None = None) -> bool:
    """하위호환 별칭 → save_ui_state (기본 경로 ui.state.json)."""
    return save_ui_state(config=config, path=path or UI_STATE_PATH)


ensure_ui_font_profiles()
ensure_ui_activity_settings()
ensure_ui_overlay_defaults()
sync_legacy_font_keys_from_profiles()
apply_ui_state()

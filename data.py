import android_fix  # noqa: F401  # Android asset-path shim; must run before any asset load

CONFIG = {
    # --- Render output mode ---
    # UPSCALE_320: 320x240 논리 렌더 → 정수배(기본 2x)로 640x480 출력
    # NATIVE_640: 640x480 논리 렌더(업스케일 없음)
    #"OUTPUT_MODE": "UPSCALE_320",  # "UPSCALE_320" | "NATIVE_640"
    "OUTPUT_MODE": "NATIVE_640",  # "UPSCALE_320" | "NATIVE_640"
    "UPSCALE_FACTOR": 2,           # UPSCALE_320에서만 사용(정수배)
    # 물리 창 크기 고정. None이면 기존처럼 논리×UPSCALE(보통 640×480).
    # "320x240": OS 창을 항상 320×240으로 유지(줌2/UPSCALE_320 시야에 맞춤).
    #   - 논리 320이면 1:1, 논리 640(NATIVE/줌아웃)이면 다운스케일 present.
    #   - AUTO_OUTPUT_MODE·F5 전환은 그대로 동작하되 창 크기만 바뀌지 않음.
    "FIXED_PHYSICAL_WINDOW": "320x240",  # None | "320x240" | "640x480"
    # "FIXED_PHYSICAL_WINDOW": None,  # None | "320x240" | "640x480"
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

    # 다운/프리즈 원인 추적 — 콘솔·logs/runtime.log [DIAG] (끄려면 DIAG_TRACE: False)
    "DIAG_TRACE": False,
    "DIAG_HEARTBEAT_EVERY": 30,           # 평상시 N프레임마다 하트비트
    "DIAG_VERBOSE_FRAMES_AFTER_BOOT": 240,  # field_boot 직후 이 프레임 수는 더 자주
    "DIAG_SLOW_FRAME_SEC": 1.5,             # 이보다 긴 구간이면 SLOW 로그


    "START_MAP": "bg_title",  # 처음 시작할 맵 ID
    # 온보딩: 매 실행 인트로→데모 후 본편. 세이브 없으면 데모 뒤 캐릭터 선택(boot_phase=15).
    # 조건식의 gamestart는 세이브가 아니라 GameFlow.boot_phase(0/1/15/2)로만 평가
    "INTRO_EVENT_ID": "ev_intro_scene",
    "DEMO_EVENT_ID": "ev_gl_demo_02",
    # 본편 진입 폴백 auto. 다른 auto가 없을 때 FADEIN·exit 등 필수 UI.
    # events.json condition: field_boot_ready == 0 / priority 후순위(큰 숫자).
    # main()이 매 실행 field_boot_ready=0 으로 리셋 → 세션당 1회.
    "FIELD_BOOT_EVENT_ID": "ev_gl_field_boot",
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
    # (세이브에 player_char 가 있으면 그쪽이 우선 — 첫 시작 캐릭터 선택 결과)
    "DEFAULT_PLAYER_CHAR": "summer_k",
    # 짱짱어린이집 조작 가능 아이들 — 첫 시작 선택·야구 p2_chars·레이스 char_pick 과 공유.
    # 조력자 별칭 ally1~ally5 는 이 목록에서 주인공을 뺀 순서(인덱스)로 매핑됨.
    "PLAYABLE_KIDS": [
        "summer_k",   # 여름이
        "dani_k",     # 단이
        "igyeong_k",  # 이경이
        "yuha_k",     # 유하
        "hyeon_k",    # 현이
        "rockie_k",   # 록희
    ],
    # 주인공(아이) → 부모(어른) CHAR_ASSETS 키.
    # 이벤트 PLACE/MOVE/SAY 의 target·bubble_target·who:
    #   "player_parent" / "ally1_parent"…"ally5_parent" / "summer_k_parent" 등
    #   → 이 맵으로 치환됨.
    # 짱짱 아이들 동료는 summer_k 등 직접 id 대신 "ally1"…"ally5" 를 쓴다.
    "PLAYER_PARENTS": {
        "summer_k": "carrot_a",        # 여름이 → 당근
        "igyeong_k": "redtilefish_a",  # 이경이 → 옥돔
        "dani_k": "jjanga_a",          # 단이 → 짱아
        "yuha_k": "firefly_a",         # 유하 → 반디
        "hyeon_k": "travel_a",         # 현이 → 여행
        "rockie_k": "sugar_a",         # 록희 → 슈가
    },
    # 세이브 키 player_char_selected: 캐릭터 선택 UI 완료 여부.
    # False/없음이면 데모 후 선택 화면 (세이브 파일이 데모 중 생겨도 동일).
    "CHAR_SELECT_BOOT_PHASE": 15,
    # 세이브 없이 첫 시작 시 캐릭터 선택 UI 문구 (activities/char_select.py)
    "CHAR_SELECT_WELCOME": "짱짱 어드벤처에 오신 것을 환영 합니다.",
    "CHAR_SELECT_PROMPT": "여러분과 함께 모험을 떠날 친구를 선택 해 주세요",
    "CHAR_SELECT_CONFIRM_FMT": "{name}로 선택 하시겠어요?",  # {name}=캐릭터 UI 이름
    "CHAR_SELECT_FAREWELL": "그럼 짱짱 친구들과 함께 신나는 모험의 세계로 떠나 볼까요~",
    # 캐릭터 선택 종료 → 본편 스폰 직전 페이드아웃 초. 밝히기는 본편 첫 auto 이벤트(FADEIN)에 맡긴다.
    "CHAR_SELECT_EXIT_FADEOUT_SEC": 1.0,
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
    "SAY_TYPE_MS_PER_CHAR": 35,
    # 완전히 표시된 뒤 바로 닫히지 않게 최소 대기(초)
    "SAY_MIN_CLOSE_DELAY_SEC": 0.3,
    # SAY 시작 직후 입력 무시 시간(초): 타자 시작 직후 실수로 바로 넘기는 것 방지
    "SAY_MIN_OPEN_DELAY_SEC": 0.3,
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
    # --- SAY 중 카메라 회피: 화자가 하단 대화창에 가리면 카메라를 아래로 밀어 캐릭터를 박스 위로 ---
    # true: 자동 회피. false: 끔 (스크립트 CAMERA 고정 연출은 fixed_world 일 때 자동 무시)
    "SAY_CAM_AVOID_COVER": True,
    # 대화창 상단(SAY_TEXTBOX_RECT_320.y)보다 이만큼(320 기준 px) 위에 화자(머리)를 유지
    "SAY_CAM_AVOID_PADDING_PX_320": 16,
    # 발→머리 추정(레거시). 가림 판정은 발 기준을 씀
    "SAY_CAM_AVOID_HEAD_OFFSET_PX_320": 28,
    # 한 번에 올릴 수 있는 최대량(320 기준 px) — 맵 가장자리에서 과한 패닝 방지
    "SAY_CAM_AVOID_MAX_PX_320": 90,
    # 회피 오프셋 lerp (0~1). 클수록 빨리 따라감
    "SAY_CAM_AVOID_LERP": 0.2,
    # 맵 끝이라 카메라를 못 올리면 대화창을 화면 위쪽으로 (차선책)
    "SAY_BOX_TOP_FALLBACK": True,
    # 카메라로 못 메우는 양(320 기준 px)이 이보다 크면 상단 박스
    "SAY_BOX_TOP_FALLBACK_SLACK_PX_320": 10,
    # 상단 텍스트 영역 [x,y,w,h]. null 이면 하단 RECT 대칭(y≈6 → 너무 위에 붙을 수 있음)
    # y 를 키우면 글자가 아래로, 줄이면 위로. (예: [30, 20, 284, 52])
    "SAY_TEXTBOX_RECT_TOP_320": [48, 38, 302, 70],
    # 상단 폴백일 때 뒤집은 textbox 이미지를 화면 위쪽에서 얼마나 내릴지(320 기준 px)
    # 0=맨 위 붙임. 글자 RECT 와 비슷하게 맞추려면 14~20 권장.
    "SAY_TEXTBOX_TOP_BLIT_Y_PX_320": 14,
    # 상단일 때 textbox 풀스크린 이미지를 세로 뒤집기 (하단용 아트 재사용)
    "SAY_TEXTBOX_FLIP_FOR_TOP": True,
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

    # --- SELECTBOX: 이벤트 스텝 예/아니오 선택창 기본값 ---
    # SELECTBOX 스텝 파라미터로 개별 오버라이드 가능.
    # SELECTBOX_YES_TEXT / NO_TEXT : 버튼 글자
    "SELECTBOX_YES_TEXT": "예",
    "SELECTBOX_NO_TEXT": "아니오",
    # 버튼 배경색 (R,G,B 문자열)
    "SELECTBOX_YES_COLOR": "52,110,72",
    "SELECTBOX_NO_COLOR": "90,58,58",
    # 폰트 크기 (320 논리 해상도 기준 px)
    "SELECTBOX_TEXT_SIZE": 12,    # 질문 텍스트
    "SELECTBOX_NAME_SIZE": 12,    # 창 이름(제목)
    "SELECTBOX_BTN_SIZE": 12,     # 버튼 글자

    # --- SAY 말풍선 (assets/images/ui/speechbubble0N/speechbubble0N_0.png …) ---
    # SAY_BUBBLE_DEFAULT True: 스텝에 bubble 을 안 적어도 speechbubble01 표시
    #   (bubble_target 비우면 who 머리 위). false 로 끄거나 스텝 bubble:false
    # SAY_BUBBLE_DEFAULT_SET: 기본/ true / "..." 일 때 쓸 세트 폴더명
    "SAY_BUBBLE_DEFAULT": True,
    "SAY_BUBBLE_DEFAULT_SET": "speechbubble01",
    # 구형 flat 연속번호 폴백 stem (폴더 로드 실패 시)
    "SAY_BUBBLE_UI_PREFIX": "images/ui/speechbubble01/speechbubble01",
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
    # event_zones[].block: 조건 참이면 해당 rect 를 벽처럼 막음
    #   예) "block": { "var": "gotothepond00", "op": "!=", "val": 1, "say": "아직 할 일이 남았어.", "who": "player" }
    #   또는 "block": { "when": "progress_x < 1002" } / "block": true (항상)
    # ZONE_BLOCK_SAY_PAD_PX: 벽에서 떨어져도 '같은 접촉'으로 볼 여유(px) — 떨어지면 대사 재발동 가능
    "ZONE_BLOCK_SAY_PAD_PX": 10,
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
    # strength(0~1) 슬라이더 상한. strength=1 → 이 배율. 기본 플레이/일반 ZOOM용.
    "WORLD_ZOOM_MAX": 4.0,
    # 이벤트 ZOOM의 val(직접 배율)만 이 값까지 허용. WORLD_ZOOM_MAX는 그대로 두고 특수 연출용.
    "WORLD_ZOOM_HARD_MAX": 8.0,
    "WORLD_ZOOM_SPEED": 3.0,     # zoom/sec (값이 클수록 더 빠르게 확대/축소)

    # --- 개별 오브젝트 줌(별개 기능) ---
    # 이벤트 ZOOM에서 target이 player/NPC/오브젝트인 경우에만 사용. (camera/global 대상 줌은 WORLD_ZOOM으로 처리)
    # val/strength = 직접 배율 (0.5=절반, 1.0=기본, 2.0=2배). on=false → 1.0
    # world_data.json objects[].zoom / object_defs zoom 에도 동일 범위 적용 (맵 배치 크기)
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

    # --- 맵 ambient 물결 타일 (field.wave_tiles) ---
    # 프레임 1세트만 로드·공유, 카메라에 보이는 칸만 blit (오브젝트 다수 배치보다 훨씬 가벼움).
    # world_data.json → [맵].field.wave_tiles 예:
    #   { "on": true, "fill_map": true, "fps": 8, "scale": 0.5, "phase_stagger": true }
    #   { "on": true, "rects": [[0,200,320,280]], "fx_dir": "assets/images/fx/wave01" }
    #   { "on": true, "polygons": [[[10,100],[300,100],[280,220],[40,240]]], "scale": 0.5 }
    #     → 꼭짓점만 저장. 맵 진입 시 타일 마스크로 1회 bake (마스크 파일 없음)
    "FIELD_WAVE_TILES_FX_DIR": "assets/images/fx/wave01",  # 기본 애니 폴더 (wave01_0.png …)
    "FIELD_WAVE_TILES_FPS": 8.0,       # 전역 프레임 속도
    "FIELD_WAVE_TILES_SCALE": 1.0,     # 스프라이트 스케일 (1=원본 px)
    "FIELD_WAVE_TILES_ALPHA": 220,     # 0~255
    "FIELD_WAVE_TILES_PHASE_STAGGER": True,  # (col+row)로 프레임 위상 어긋나 반복감 완화

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
    # 미니게임 아케이드 기록(야구·레이스). 세이브 초기화와 무관. Android도 cwd(앱 files)에 기록.
    "MINIGAME_RECORDS_FILE": "minigame_records.json",

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
        # e: 이벤트 피커(목록 모달) — GLOBAL_EVENT_HOTKEYS 가 아님. field_runtime EventPicker
    ],
    # 필드 플레이 중 E 키 — 등록 이벤트 목록 모달(클릭/Enter 즉시 실행). False면 비활성
    "EVENT_PICKER_HOTKEY_ENABLED": True,
    # EVENT_PICKER_HOTKEY: 피커 토글 키 (한 글자 / F키 / K_*). 기본 e
    "EVENT_PICKER_HOTKEY": "e",
    # EVENT_PICKER_ROW_H: 목록 한 줄 높이(논리 px)
    "EVENT_PICKER_ROW_H": 18,
    # EVENT_PICKER_VISIBLE_ROWS: 한 화면에 보이는 줄 수
    "EVENT_PICKER_VISIBLE_ROWS": 12,
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
    # cfg에 quality_scale 이 명시되면(레이스 옵션) 그 값을 우선 사용.
    # H700급(RG34XX 등): Mode7 부하는 오브젝트가 아니라 바닥 픽셀 샘플 — 상한이 핵심.
    "ROTATE3D_QUALITY_SCALE": 1.0,              # PC·명시 없을 때 기본(전체)
    "ROTATE3D_ANDROID_QUALITY_SCALE": 1.0,      # Android도 기본 동작은 PC와 동일
    "ROTATE3D_ANDROID_QUALITY_CAP": 1.0,        # Android에서도 사용자가 고른 품질을 그대로 허용
    "ROTATE3D_ANDROID_QUALITY_CAP_320": 1.0,
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
    # false: 터치 이동 중 도랑/짧은 갭 자동 점프 끔 (ACTION_ANIM hop·그네 점프는 유지)
    # true: JUMP_MAX_GAP_PX 이하 갭을 자동 hop
    "JUMP_AUTO_ENABLED": False,
    # 직선 이동 구간에서 이 거리(px) 이하의 갭만 자동 점프로 건넜다가 목표까지 계속 걷기 (오카리나식)
    # 징검다리(연꽃잎) 맵: 섬 사이 20~50px → 여유 포함 56
    "JUMP_MAX_GAP_PX": 26,
    # true: 흰색 walk 섬 사이 검정(wall)도 짧은 갭이면 자동 점프 (파란 ditch 안 칠해도 됨)
    # false: 예전처럼 파란 ditch 만 점프
    "JUMP_ALLOW_WALL_GAP": True,
    # 필드 연꽃잎(step_react) 기본 밟힘 반경(px). object_defs.step_radius 가 있으면 그쪽 우선
    "STEP_REACT_DEFAULT_RADIUS": 30,
    # 점프 높이(픽셀). 자동 조절 기본 최대치
    "JUMP_ARC_HEIGHT": 50,
    # 도랑 폭(span)에 따른 자동 점프 높이/시간 조절
    "JUMP_ARC_HEIGHT_MIN": 30, #10
    "JUMP_ARC_HEIGHT_MAX": 50,
    # dist(px) * 이 값 = 기본 점프 시간(ms) (최종은 MIN/MAX로 클램프)
    "JUMP_DUR_PER_PX": 15.0,
    # span 비율(0~1)에 따른 시간 배수 (좁으면 더 짧게, 넓으면 더 길게)
    "JUMP_DUR_SPAN_MUL_MIN": 0.85,
    "JUMP_DUR_SPAN_MUL_MAX": 1.15,
    "JUMP_MIN_DURATION_MS": 220,
    "JUMP_MAX_DURATION_MS": 520,
    # 제자리 hop(ACTION_ANIM jump 등): 도랑 점프 MIN(~220ms)과 별도 — 기본 연출 길이
    "JUMP_HOP_DURATION_MS": 750,
    "JUMP_HOP_DURATION_MAX_MS": 1800,
    # jump 스프라이트 프레임 간격(ms). 미지정 시 ANIM_DELAY(150) — 연출용으로 더 느리게
    "JUMP_ANIM_DELAY": 280,
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
    # 다중 target MOVE/PLACE: 앵커 좌표에서 멤버마다 떨어뜨릴 간격/반경(px)
    "EVENT_GROUP_SPACING_PX": 50,
    # 단체 배치 기본: circle | left | right | up | down
    "EVENT_GROUP_LAYOUT": "circle",

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
    # 0이면 BFS 거의 모든 노드에서 동기 A* → 프레임 수십 초 스톨 가능. 기본 1 유지.
    "PATHFIND_ESCAPE_MIN_OPEN_NEIGHBORS": 1,
    # 코너 탈출 동기 A* 상한 (한 프레임 hitch 방지)
    "PATHFIND_ESCAPE_MAX_ASTAR_TRIES": 6,
    "PATHFIND_ESCAPE_BUDGET_MS": 6.0,
    "PATHFIND_ESCAPE_ASTAR_MAX_VISITED": 900,

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
    # FOLLOW_START 여러 명이 같은 leader 를 따를 때: 세로 간격(px, 320 기준 아님 — 월드 px)
    "FOLLOW_MULTI_SPACING_PX": 18.0,
    # 슬롯 목표점까지 이 거리 이하면 정지
    "FOLLOW_SLOT_ARRIVE_PX": 12.0,

    # PLACE persist + behavior:follow(또는 travel:true) 동행 — 맵 전환 시 플레이어 근처 스폰
    # PLACED_FOLLOW_SPAWN_OFFSET_PX: 첫 동행 NPC를 플레이어 왼쪽으로 띄울 거리(px)
    "PLACED_FOLLOW_SPAWN_OFFSET_PX": 28,
    # PLACED_FOLLOW_SPAWN_SPACING_PX: 동행이 여러 명일 때 가로로 벌리는 간격(px)
    "PLACED_FOLLOW_SPAWN_SPACING_PX": 20,
    # PLACED_FOLLOW_SPAWN_MIN_SEP_PX: 동행끼리 최소 간격(겹쳐 스폰 방지)
    "PLACED_FOLLOW_SPAWN_MIN_SEP_PX": 14,
    # PLACED_FOLLOW_SPAWN_SNAP_R_PX: 막힌 칸일 때 주변 walk 탐색 반경(px)
    "PLACED_FOLLOW_SPAWN_SNAP_R_PX": 72,

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
    # 황소개구리 보스(activities/bullfrog) — 0=미도전, 1=승리, 2=패배(1회 이상)
    "progress_bullfrog_win": 0,
    "progress_fishing_win": 0,
    "score_frog_trial_best": 0,
    "score_frog_trial_last": 0,
}


# ---------------------------------------------------------------------------
# 주인공·조력자·부모 연동 (세이브 player_char / 이벤트 player_parent·ally1~5)
#
# [세이브]
#   player_char  — 조작 캐릭터 id (없으면 DEFAULT_PLAYER_CHAR)
#   parent_char  — 선택 시 같이 기록(없으면 PLAYER_PARENTS 로 유도)
#   조력자 5명은 세이브에 두지 않고 get_ally_char_ids() 로 유도
#     (PLAYABLE_KIDS 순서에서 주인공만 뺀 나머지 → ally1=첫 번째 … ally5=다섯 번째)
#
# [이벤트·맵]
#   짱짱 아이들 NPC는 summer_k 등 직접 id 대신 ally1~ally5 를 쓴다.
#   target / bubble_target / who / world_data npcs[].name:
#     "player_parent" → 주인공 부모 char id
#     "ally1"…"ally5" → 조력자 char id (주인공 제외 인덱스)
#     "ally1_parent"…"ally5_parent" → 해당 조력자의 부모
#     "summer_k_parent" 등 → PLAYABLE_KIDS/PLAYER_PARENTS 키의 부모
#   같은 name 복제 NPC(예: frog01×3): target 에 instance_id 사용
#     world_data npcs[].instance_id 예) "frog01@64_416"
#     → MOVE/PLACE/TUNE 등에서 그 개체만 지정
#   FOLLOW_START follower: 여러 명 쉼표 가능 ("ally1,ally2,ally3")
#     → 같은 leader 로 일괄 등록 + 슬롯 대형(겹침 완화)
#     → 이벤트 종료 후에도 FOLLOW_STOP 전까지 유지 (필드 동행)
#   FOLLOW_STOP 로 해제 (비우면 전부)
#   player 는 엔진이 엔티티로 특별 처리하므로 그대로 둔다.
#   SAY 문구 {player_name} {player_call} {parent_name} {parent_call}
#           {ally1_name}…{ally5_name} {ally1_call}…{ally5_call}
#           {ally1_parent_name}…{ally5_parent_call}
#           {summer_k_parent_name} 등 (아이 id + _parent_name/_parent_call)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SAY / EMOTE 말풍선 세트
# bubble 필드 토큰 → assets/images/ui/speechbubble0N/
#   ... → 01(말줄임)  !!! → 02  ??? → 03  ^^ → 04  ㅠㅠ → 05
# ---------------------------------------------------------------------------

# 에디터 SAY/EMOTE bubble 드롭다운 ("" = data 기본값 사용)
SAY_BUBBLE_EDITOR_CHOICES = (
    "",
    "false",
    "...",
    "!!!",
    "???",
    "^^",
    "ㅠㅠ",
    "01",
    "02",
    "03",
    "04",
    "05",
)

# 감정 토큰 → 세트 폴더명
SAY_BUBBLE_TOKEN_TO_SET = {
    "...": "speechbubble01",
    "…": "speechbubble01",
    "dots": "speechbubble01",
    "dot": "speechbubble01",
    "!!!": "speechbubble02",
    "!": "speechbubble02",
    "exclaim": "speechbubble02",
    "???": "speechbubble03",
    "?": "speechbubble03",
    "question": "speechbubble03",
    "^^": "speechbubble04",
    "^_^": "speechbubble04",
    "happy": "speechbubble04",
    "ㅠㅠ": "speechbubble05",
    "ㅜㅜ": "speechbubble05",
    "tt": "speechbubble05",
    "sad": "speechbubble05",
}


def resolve_say_bubble_set(bubble, config=None):
    """
    SAY/EMOTE 의 bubble 필드 → speechbubble0N 세트명.
    끄면 None 반환 (말풍선 미표시).

    - None / "" : CONFIG SAY_BUBBLE_DEFAULT 가 True 면 DEFAULT_SET(기본 speechbubble01)
    - false / off / 0 / no : 끔
    - true / on / 1 / yes : DEFAULT_SET
    - ... !!! ??? ^^ ㅠㅠ / 01~05 / speechbubble03 : 해당 세트
    """
    cfg = config if isinstance(config, dict) else CONFIG
    try:
        default_set = str(
            cfg.get("SAY_BUBBLE_DEFAULT_SET", "speechbubble01") or "speechbubble01"
        ).strip()
    except Exception:
        default_set = "speechbubble01"
    if not default_set:
        default_set = "speechbubble01"

    def _norm_set(name: str) -> str:
        sn = str(name or "").strip().replace("\\", "/").strip("/")
        if not sn:
            return default_set
        base = sn.split("/")[-1]
        # "3" / "03" → speechbubble03
        if base.isdigit():
            n = int(base)
            if 1 <= n <= 9:
                return f"speechbubble{n:02d}"
        low = base.lower()
        if low.startswith("speechbubble"):
            return low
        return base

    if bubble is None:
        if bool(cfg.get("SAY_BUBBLE_DEFAULT", True)):
            return _norm_set(default_set)
        return None

    if isinstance(bubble, bool):
        return _norm_set(default_set) if bubble else None

    if isinstance(bubble, (int, float)):
        try:
            v = float(bubble)
        except (TypeError, ValueError):
            return None
        if v == 0:
            return None
        if v == 1:
            return _norm_set(default_set)
        # 2~5 → speechbubble0N
        if 2 <= int(v) <= 9:
            return f"speechbubble{int(v):02d}"
        return _norm_set(default_set)

    raw = str(bubble).strip()
    if not raw:
        if bool(cfg.get("SAY_BUBBLE_DEFAULT", True)):
            return _norm_set(default_set)
        return None

    low = raw.lower()
    if low in ("0", "false", "f", "no", "n", "off", "none", "null", "hide", "clear"):
        return None
    if low in ("1", "true", "t", "yes", "y", "on", "default", "show"):
        return _norm_set(default_set)

    mapped = SAY_BUBBLE_TOKEN_TO_SET.get(raw) or SAY_BUBBLE_TOKEN_TO_SET.get(low)
    if mapped:
        return _norm_set(mapped)

    return _norm_set(raw)


def get_playable_kids(config=None) -> list:
    """조작·선택 가능한 짱짱어린이집 아이들 id 목록."""
    cfg = config if isinstance(config, dict) else CONFIG
    raw = cfg.get("PLAYABLE_KIDS") or []
    out = []
    for x in raw:
        cid = str(x or "").strip()
        if cid and cid not in out:
            out.append(cid)
    if out:
        return out
    return ["summer_k", "dani_k", "igyeong_k", "yuha_k", "hyeon_k", "rockie_k"]


def get_player_char_id(save_data=None, config=None) -> str:
    """세이브·CONFIG 에서 현재 주인공 캐릭터 id."""
    cfg = config if isinstance(config, dict) else CONFIG
    default = str(cfg.get("DEFAULT_PLAYER_CHAR", "summer_k") or "summer_k").strip()
    sd = save_data if isinstance(save_data, dict) else {}
    pc = str(sd.get("player_char") or "").strip()
    return pc or default


def get_player_parent_id(save_data=None, *, player_char=None, config=None) -> str:
    """주인공에 연동된 부모 캐릭터 id (PLAYER_PARENTS / 세이브 parent_char)."""
    cfg = config if isinstance(config, dict) else CONFIG
    sd = save_data if isinstance(save_data, dict) else {}
    stored = str(sd.get("parent_char") or "").strip()
    pc = str(player_char or "").strip() or get_player_char_id(sd, cfg)
    parents = cfg.get("PLAYER_PARENTS") if isinstance(cfg.get("PLAYER_PARENTS"), dict) else {}
    mapped = str((parents or {}).get(pc) or "").strip()
    # 선택 직후 맵을 우선 — 역할 교체 시 parent_char 와 일치 유지
    if mapped:
        return mapped
    if stored:
        return stored
    return str((parents or {}).get("summer_k") or "carrot_a").strip() or "carrot_a"


def get_parent_id_for_char(char_id, config=None) -> str:
    """아이 char id → PLAYER_PARENTS 부모 id. 없으면 빈 문자열."""
    cfg = config if isinstance(config, dict) else CONFIG
    cid = str(char_id or "").strip()
    if not cid:
        return ""
    parents = cfg.get("PLAYER_PARENTS") if isinstance(cfg.get("PLAYER_PARENTS"), dict) else {}
    return str((parents or {}).get(cid) or "").strip()


def get_ally_char_ids(player_char=None, save_data=None, config=None) -> list:
    """주인공을 제외한 나머지 짱짱 친구들(조력자) id 목록. PLAYABLE_KIDS 순서 유지."""
    cfg = config if isinstance(config, dict) else CONFIG
    pc = str(player_char or "").strip() or get_player_char_id(save_data, cfg)
    return [c for c in get_playable_kids(cfg) if c != pc]


def get_ally_char_id(slot, player_char=None, save_data=None, config=None) -> str:
    """
    1-based 조력자 슬롯(1..5) → 실제 char id.
    범위 밖이거나 해당 슬롯이 없으면 빈 문자열.
    """
    try:
        i = int(slot)
    except Exception:
        return ""
    allies = get_ally_char_ids(player_char=player_char, save_data=save_data, config=config)
    if 1 <= i <= len(allies):
        return str(allies[i - 1] or "").strip()
    return ""


def parse_ally_slot(token) -> int:
    """
    'ally1'…'ally5' → 1…5. 아니면 0.
    (대소문자 무시. ally01 같은 선행 0도 허용)
    """
    key = str(token or "").strip().lower()
    if not key.startswith("ally"):
        return 0
    rest = key[4:]
    if not rest.isdigit():
        return 0
    try:
        n = int(rest)
    except Exception:
        return 0
    if 1 <= n <= 5:
        return n
    return 0


def _is_known_kid_char_id(cid, config=None) -> bool:
    """PLAYABLE_KIDS 또는 PLAYER_PARENTS 키에 있는 아이 id인지."""
    cfg = config if isinstance(config, dict) else CONFIG
    key = str(cid or "").strip()
    if not key:
        return False
    if key in get_playable_kids(cfg):
        return True
    parents = cfg.get("PLAYER_PARENTS") if isinstance(cfg.get("PLAYER_PARENTS"), dict) else {}
    return key in (parents or {})


def parse_parent_alias_kid(token, save_data=None, config=None) -> str:
    """
    부모 별칭 → 아이 char id (부모 조회용).
    - player_parent / parent / mom / dad / guardian → 현재 주인공
    - ally1_parent…ally5_parent → 해당 조력자
    - summer_k_parent 등 → 그 아이 id
    매칭 실패 시 빈 문자열.
    """
    cfg = config if isinstance(config, dict) else CONFIG
    key = str(token or "").strip().lower()
    if not key:
        return ""
    if key in ("player_parent", "parent", "mom", "dad", "guardian"):
        return get_player_char_id(save_data, cfg)
    if not key.endswith("_parent"):
        return ""
    base = key[: -len("_parent")]
    if not base:
        return ""
    slot = parse_ally_slot(base)
    if slot:
        return get_ally_char_id(slot, save_data=save_data, config=cfg)
    # summer_k_parent 등 — 원본 대소문자 보존을 위해 token 쪽 base 사용
    raw_base = str(token or "").strip()
    if raw_base.lower().endswith("_parent"):
        raw_base = raw_base[: -len("_parent")]
    if _is_known_kid_char_id(raw_base, cfg) or _is_known_kid_char_id(base, cfg):
        # PLAYER_PARENTS / PLAYABLE_KIDS 에 있는 표기 우선
        for kid in get_playable_kids(cfg):
            if kid.lower() == base:
                return kid
        parents = cfg.get("PLAYER_PARENTS") if isinstance(cfg.get("PLAYER_PARENTS"), dict) else {}
        for kid in (parents or {}):
            if str(kid).lower() == base:
                return str(kid)
        return raw_base or base
    return ""


def is_story_target_alias(token, config=None) -> bool:
    """이벤트 target/who 가 스토리 별칭(해석 대상)인지."""
    key = str(token or "").strip().lower()
    if not key:
        return False
    if key in ("player_parent", "parent", "mom", "dad", "guardian"):
        return True
    if parse_ally_slot(key):
        return True
    if key.endswith("_parent"):
        base = key[: -len("_parent")]
        if parse_ally_slot(base):
            return True
        return _is_known_kid_char_id(base, config)
    return False


def apply_player_char_choice(save_data: dict, char_id: str, config=None, *, selected=False) -> dict:
    """
    캐릭터 선택 결과를 세이브 dict 에 기록.
    player_char / parent_char 설정. (조력자는 유도만 하므로 저장하지 않음)
    selected=True 일 때만 player_char_selected 를 켠다 (선택 UI 완료 표시).
    """
    cfg = config if isinstance(config, dict) else CONFIG
    sd = save_data if isinstance(save_data, dict) else {}
    cid = str(char_id or "").strip() or str(cfg.get("DEFAULT_PLAYER_CHAR", "summer_k") or "summer_k")
    sd["player_char"] = cid
    sd["parent_char"] = get_player_parent_id(sd, player_char=cid, config=cfg)
    if selected:
        sd["player_char_selected"] = True
    return sd


def needs_player_char_select(save_data=None, config=None) -> bool:
    """
    첫 주인공 선택 UI가 필요한지.
    player_char_selected 가 없으면/False 이면 True.
    (세이브 파일이 데모 중·강제종료로 생겨도, 선택을 안 했으면 다시 고르게 함)
    """
    sd = save_data if isinstance(save_data, dict) else {}
    return not bool(sd.get("player_char_selected"))


def resolve_story_target_id(target, save_data=None, config=None) -> str:
    """
    이벤트·맵 target / bubble_target / who / npc name 별칭 해석.
    player 는 엔진이 엔티티로 특별 처리하므로 그대로 두고,
    player_parent / allyN_parent / {kid}_parent → 부모 char id,
    ally1…ally5 → 주인공 제외 조력자 char id.
    매칭 실패 시 원문 반환.
    """
    t = str(target or "").strip()
    if not t:
        return t
    cfg = config if isinstance(config, dict) else CONFIG
    key = t.lower()
    kid_for_parent = parse_parent_alias_kid(t, save_data=save_data, config=cfg)
    if kid_for_parent:
        # player_parent 계열은 세이브 parent_char 보정 포함
        if key in ("player_parent", "parent", "mom", "dad", "guardian"):
            return get_player_parent_id(save_data, player_char=kid_for_parent, config=cfg)
        pid = get_parent_id_for_char(kid_for_parent, cfg)
        if pid:
            return pid
        # PLAYER_PARENTS 에 없으면 주인공 부모 조회 경로로 한 번 더
        return get_player_parent_id(save_data, player_char=kid_for_parent, config=cfg) or t
    slot = parse_ally_slot(key)
    if slot:
        cid = get_ally_char_id(slot, save_data=save_data, config=cfg)
        if cid:
            return cid
    return t


def resolve_story_who_label(who, save_data=None, config=None) -> str:
    """
    SAY who → 대화창에 찍히는 이름.

    - player → 세이브 주인공의 char_defs.name (예: 여름이)
    - ally1~5 / *_parent 별칭 → 실제 캐릭터 UI 이름
    - char_defs 키(summer_k, frog01 …) → 그 정의의 name (없으면 id)
    - 여러 명: "a,b,c" → 각각 풀어 ", " 로 연결
    - 이미 한글로 쓴 표시명·알 수 없는 토큰 → 원문 유지
    """
    raw = str(who or "").strip()
    if not raw:
        return raw
    cfg = config if isinstance(config, dict) else CONFIG

    # 여러 who: "player,ally1,summer_k"
    if "," in raw:
        parts = [p.strip() for p in raw.split(",") if str(p).strip()]
        if len(parts) > 1:
            labels = [resolve_story_who_label(p, save_data=save_data, config=cfg) for p in parts]
            return ", ".join(labels)

    key = raw.lower()
    try:
        from char_behavior import get_char_ui_name
    except Exception:
        def get_char_ui_name(cid):  # noqa: N802
            return str(cid or "")

    # player → 현재 주인공 표시 이름
    if key == "player":
        try:
            cid = get_player_char_id(save_data, cfg)
        except Exception:
            cid = ""
        if cid:
            return str(get_char_ui_name(cid) or cid)
        return raw

    # 스토리 별칭 (ally1, player_parent, summer_k_parent …)
    if is_story_target_alias(raw, cfg):
        cid = resolve_story_target_id(raw, save_data=save_data, config=cfg)
        if cid:
            return str(get_char_ui_name(cid) or cid)
        return raw

    # char_defs 에 있는 id → name (who: "summer_k" → "여름이")
    assets = CHAR_ASSETS if isinstance(CHAR_ASSETS, dict) else {}
    cid = raw if raw in assets else None
    if cid is None:
        for k in assets:
            if str(k).lower() == key:
                cid = k
                break
    if cid is not None:
        label = str(get_char_ui_name(cid) or "").strip()
        if label:
            return label

    return raw


def resolve_story_alias_ui_name(token, save_data=None, config=None) -> str:
    """
    스토리 별칭 → 표시 이름.
    player / ally1…ally5 / player_parent / allyN_parent / {kid}_parent 등.
    해석 불가면 빈 문자열.
    """
    raw = str(token or "").strip()
    if not raw:
        return ""
    cfg = config if isinstance(config, dict) else CONFIG
    key = raw.lower()
    try:
        from char_behavior import get_char_ui_name
    except Exception:
        def get_char_ui_name(cid):  # noqa: N802
            return str(cid or "")

    if key == "player":
        return str(get_char_ui_name(get_player_char_id(save_data, cfg)) or "")
    if not is_story_target_alias(raw, cfg):
        return ""
    cid = resolve_story_target_id(raw, save_data=save_data, config=cfg)
    if not cid:
        return ""
    if str(cid).strip().lower() == key and parse_ally_slot(key):
        return ""
    return str(get_char_ui_name(cid) or "")


def expand_story_text(text, save_data=None, config=None) -> str:
    """
    SAY 등 스토리 문구 템플릿.
    {player_name} {player_call} {parent_name} {parent_call}
    {ally1_name}…{ally5_name} {ally1_call}…{ally5_call}
    {ally1_parent_name}…{ally5_parent_call}
    {summer_k_parent_name} 등 (아이 id + _parent_name / _parent_call)
    call = 호칭(여름이→여름아, 유하→유하야).

    따옴표 별칭: "ally5" "player" "ally1_parent" → 표시 이름
      예: "\"ally5\"가 위험에 쳐했어!!" → "록희가 위험에 쳐했어!!"
    단축 중괄호: {ally5} {player} {parent} → 표시 이름 ({ally5_name} 과 동일)
    """
    import re

    raw = str(text or "")
    if not raw:
        return raw
    need_brace = "{" in raw
    need_quoted = '"' in raw
    if not need_brace and not need_quoted:
        return raw
    try:
        from char_behavior import get_char_call_name, get_char_ui_name
    except Exception:
        def get_char_ui_name(cid):  # noqa: N802
            return str(cid or "")

        get_char_call_name = get_char_ui_name
    cfg = config if isinstance(config, dict) else CONFIG
    sd = save_data if isinstance(save_data, dict) else {}
    pc = get_player_char_id(sd, cfg)
    parent = get_player_parent_id(sd, player_char=pc, config=cfg)
    mapping = {
        "player_name": get_char_ui_name(pc),
        "player_call": get_char_call_name(pc),
        "parent_name": get_char_ui_name(parent),
        "parent_call": get_char_call_name(parent),
        # 단축: {player} {parent}
        "player": get_char_ui_name(pc),
        "parent": get_char_ui_name(parent),
    }
    allies = get_ally_char_ids(player_char=pc, save_data=sd, config=cfg)
    for i in range(1, 6):
        cid = allies[i - 1] if i - 1 < len(allies) else ""
        mapping[f"ally{i}_name"] = get_char_ui_name(cid) if cid else ""
        mapping[f"ally{i}_call"] = get_char_call_name(cid) if cid else ""
        mapping[f"ally{i}"] = mapping[f"ally{i}_name"]
        pid = get_parent_id_for_char(cid, cfg) if cid else ""
        mapping[f"ally{i}_parent_name"] = get_char_ui_name(pid) if pid else ""
        mapping[f"ally{i}_parent_call"] = get_char_call_name(pid) if pid else ""
        mapping[f"ally{i}_parent"] = mapping[f"ally{i}_parent_name"]
    # 고정 아이 id 부모 템플릿
    kids = list(get_playable_kids(cfg))
    parents_map = cfg.get("PLAYER_PARENTS") if isinstance(cfg.get("PLAYER_PARENTS"), dict) else {}
    for kid in (parents_map or {}):
        ks = str(kid or "").strip()
        if ks and ks not in kids:
            kids.append(ks)
    for kid in kids:
        pid = get_parent_id_for_char(kid, cfg)
        mapping[f"{kid}_parent_name"] = get_char_ui_name(pid) if pid else ""
        mapping[f"{kid}_parent_call"] = get_char_call_name(pid) if pid else ""
    out = raw
    if need_brace:
        # 긴 키 먼저(ally1_parent_name 이 ally1_parent / ally1 보다 먼저)
        for key in sorted(mapping.keys(), key=len, reverse=True):
            out = out.replace("{" + key + "}", str(mapping.get(key) or ""))
    if need_quoted:
        # "ally5" / "player" / "ally1_parent" → 표시 이름 (스토리 별칭만)
        def _repl_quoted(m):
            tok = m.group(1)
            kl = str(tok or "").strip().lower()
            if kl in mapping and mapping.get(kl):
                return str(mapping[kl])
            name = resolve_story_alias_ui_name(tok, sd, cfg)
            return name if name else m.group(0)

        out = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)"', _repl_quoted, out)
    return out



# 맵별 필드 기본값 (틸트·쉬어·화면 FX·물결 타일 ambient)
# - 저장: world_data.json → [맵ID].field
#   예: "field": {
#         "tilt_on": false, "shear_on": true,
#         "screen_fx": {
#           "cloud": {"dir":"RANDOM","speed":15,"freq":0.5},
#           "rain": {"density":0.4,"speed":280,"angle":82},
#           "vignette": {"strength":0.55,"size":0.42,"softness":0.65},
#           "tone": {"preset":"warm","strength":0.35}
#         },
#         "wave_tiles": {
#           "on": true, "fill_map": true, "fps": 8, "scale": 0.5,
#           "fx_dir": "assets/images/fx/wave01", "phase_stagger": true
#         }
#         # 또는 부분: "rects": [[x,y,w,h], ...]
#         # 또는 다각형(마스크 파일 없이 꼭짓점만): "polygons": [[[x,y],...], ...]
#       }
# - 맵 진입 시 field_runtime.apply_map_field_defaults
# - tilt_on/shear_on 생략 → CONFIG (FIELD_PERSPECTIVE_DEFAULT_ON / TILT_SHEAR_ENABLED)
# - screen_fx 의 kind 키가 있으면 ON (엔진 build_*_from_step 과 동일 파라미터). 없으면 해당 FX OFF.
# - wave_tiles: 공유 프레임 + 뷰포트 컬링. polygons 는 configure 시 타일 마스크 bake.
# - presence_zones[].field 는 존 체류 중 틸트/쉬어만 덮어쓰기. 맵 루트 field 는 진입 시 1회.


def get_map_field_raw(map_id: str, world_data=None) -> dict:
    """world_data[map_id].field 원본 dict (없으면 {})."""
    mid = str(map_id or "").strip()
    if not isinstance(world_data, dict) or not mid:
        return {}
    row = world_data.get(mid)
    field = row.get("field") if isinstance(row, dict) else None
    return dict(field) if isinstance(field, dict) else {}


def resolve_map_field_defaults(map_id: str, world_data=None) -> dict:
    """맵 ID → {tilt_on: bool, shear_on: bool, screen_fx: dict, wave_tiles: dict|None}.

    screen_fx 는 kind→파라미터 dict (키가 있으면 해당 FX ON). 없으면 {}.
    wave_tiles 는 field.wave_tiles (없으면 None = OFF).
    """
    out: dict = {}
    field = get_map_field_raw(map_id, world_data)
    for key in ("tilt_on", "shear_on"):
        val = field.get(key)
        if val is None or (isinstance(val, str) and not str(val).strip()):
            continue
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("1", "true", "t", "yes", "y", "on"):
                out[key] = True
            elif s in ("0", "false", "f", "no", "n", "off"):
                out[key] = False
        else:
            out[key] = bool(val)
    if "tilt_on" not in out:
        out["tilt_on"] = bool(CONFIG.get("FIELD_PERSPECTIVE_DEFAULT_ON", False))
    if "shear_on" not in out:
        out["shear_on"] = bool(CONFIG.get("TILT_SHEAR_ENABLED", False))
    sfx = field.get("screen_fx")
    out["screen_fx"] = dict(sfx) if isinstance(sfx, dict) else {}
    wt = field.get("wave_tiles")
    out["wave_tiles"] = dict(wt) if isinstance(wt, dict) else None
    return out


# 야구장 필드 미니게임 — 전역 기본값 (snake_case).
# 맵별 좌표·밸런스는 world_data.json → [맵ID].baseball 에서 덮어씀.
# exit_map/exit_pos: 미니게임 맵에서 세이브·강제종료 시 이 장소로 저장/스폰 (flow.resolve_activity_arena_exit).
BASEBALL_DEFAULTS = {
    "default_map_id": "bg_baseball1",
    "default_player_char": "nachos_a",
    "story_win_flag": "progress_baseball_story",
    "story_seed_flag": "progress_baseball_seed",
    # CONFIG["PLAYABLE_KIDS"] 와 동일 풀 (첫 시작 캐릭터 선택과 호환)
    "p2_chars": list(CONFIG["PLAYABLE_KIDS"]) if "PLAYABLE_KIDS" in CONFIG else [
        "summer_k", "dani_k", "igyeong_k", "yuha_k", "hyeon_k", "rockie_k"
    ],
    "exit_map": "bg_jjangpu",
    "exit_pos": [850.0, 2310.0],
    "swings": 5,
    "gauge_time_limit_sec": 5.0,
    "gauge_sweep_end_speed_mul": 1.5,
    # NPC 기본 타격(레거시 폴백) + 플래시 연출
    "npc_skill": 0.62,
    "npc_flash_sec": 0.55,
    # NPC 타격 AI — 비거리 스케일 0~100 을 5등분(a~e) + 파울.
    # 가중치 순서: foul, a(0~20), b(21~40), c(41~60), d(61~80), e(81~100)
    # 기본(중급): d 최고, c·e 그다음, a·b·파울은 낮음. 쉬움은 단타·파울↑, 어려움은 장타↑.
    "difficulty_easy_npc_band_weights": [0.14, 0.20, 0.24, 0.18, 0.14, 0.10],
    "difficulty_normal_npc_band_weights": [0.08, 0.10, 0.12, 0.22, 0.30, 0.18],
    "difficulty_hard_npc_band_weights": [0.04, 0.06, 0.08, 0.20, 0.36, 0.26],
    "difficulty_easy_npc_skill": 0.45,
    "difficulty_normal_npc_skill": 0.62,
    "difficulty_hard_npc_skill": 0.80,
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
# path: 에디터 제어점 목록. 런타임은 Cardinal(Catmull-Rom) 곡선으로 잇고 호장 s 로 주행.
RACING_DEFAULTS = {
    "default_map_id": "bg_town",
    "default_player_char": "summer_k",
    # CONFIG["PLAYABLE_KIDS"] 와 동일 풀 (첫 시작 캐릭터 선택과 호환)
    "char_pick": list(CONFIG.get("PLAYABLE_KIDS") or [
        "summer_k", "dani_k", "igyeong_k", "yuha_k", "hyeon_k", "rockie_k"
    ]),
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
    # --- 경로 곡선 (제어점 → 스플라인) ---
    # curve_tension: 0=Catmull-Rom(가장 둥근 코너), 1에 가까울수록 제어점 사이 직선에 근접
    "curve_tension": 0.0,
    # curve_samples_per_seg: 제어점 한 구간당 호장 샘플 수(클수록 곡선·도로가 매끈, 비용↑)
    "curve_samples_per_seg": 20,
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
    "max_speed": 200.0,      # 직선 최고속 (월드 px/s, 레일 호장 진행)
    "min_corner_speed": 50.0,  # 급커브에서도 이 속도 이하로 안 떨어짐
    "accel": 80.0,           # 출발·가속 (서서히 붙는 느낌)
    "brake": 40.0,           # 목표속도보다 빠를 때 감속
    "corner_brake": 1.4,     # 앞 곡률(rad)에 비례한 목표속도 감소
    "corner_lookahead_px": 90.0,  # 앞쪽 곡률을 미리 보는 거리(클수록 일찍 감속)
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
    # (레거시·미사용) 예전 자유체 관성 주행용. 레일 고정 후 무시. world_data 옛 키 호환용으로만 남김.
    "turn_rate_rad": 2.2,
    "path_pull": 2.2,
    "path_soft_follow": 0.5,
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
    # 가속·정속(crawl): 자벌레 fps ∝ r.speed (0→정지, max_speed→inchworm_fps_at_max)
    #   프레임 1~coast = 관성(속도 유지), 이후 프레임 = 가속(속도 추가). 자벌레 구부림→펼침.
    # 감속(slide): fps는 속도에 맞춰 느려지다 inchworm_slide_freeze_sec 후 프레임 고정(미끄러짐)
    # 다시 가속할 때까지 frozen 유지. 물리 속도는 그대로 감속.
    "inchworm_anim": "moveinchworm_racing",  # load_racing_overlay_frames 애니 세트명
    "inchworm_fps_at_max": 14.0,             # 최고속(max_speed)일 때 자벌레 프레임/초
    "inchworm_speed_eps": 1.0,               # 이 속도(px/s) 이하면 애니 완전 정지(fps=0)
    "inchworm_drive_band": 1.0,              # target_spd 대비 이 이내면 hold(가속/감속 판정 데드존)
    "inchworm_slide_freeze_sec": 1.0,        # 감속 시작 후 이 시간 지나면 애니 고정(미끄러짐)
    "inchworm_coast_frames": 4,              # 앞 N프레임(1~N)=관성 유지, 나머지=가속 펄스
    "inchworm_thrust_accel_mul": 2.0,        # 가속 프레임에만 쓰이므로 평균 가속 보정 배율
    "inchworm_launch_fps": 5.0,              # 정지→출발 시 최소 자벌레 fps (프레임 게이트 시동)
    # 자벌레 0~7번 프레임별 seat_idle 상승량(px). 화면 Y좌표에서는 이 값을 빼서 몸만 위로 올린다.
    "inchworm_seat_lift_px": [8, 12, 16, 20, 24, 20, 16, 12],
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
    "mode7_quality_scales_android": {"high": 1.0, "medium": 0.72, "low": 0.50, "lowest": 0.35},
}

# 레이스 난이도 — NPC 속도 + 레인 AI(아이템 반응)
# npc_speed_mul: NPC 최고속 배율
# ai_lane_min/max: 레인 판단 주기(초). 짧을수록 아이템·위협에 빨리 반응
# ai_look_ahead_s: 앞쪽 아이템을 보는 호장 거리(px)
# ai_react_chance: 아이템 신호를 따를 확률(낮으면 자주 무시 → 쉬움)
# ai_idle_lane_chance: 앞 아이템이 없을 때 랜덤 레인 변경 확률
RACING_DIFFICULTY = {
    "easy": {
        "label": "쉬움",
        "npc_speed_mul": 0.9,
        "ai_lane_min": 2.0,
        "ai_lane_max": 3.8,
        "ai_look_ahead_s": 90.0,
        "ai_react_chance": 0.60,
        "ai_idle_lane_chance": 0.35,
    },
    "normal": {
        "label": "보통",
        "npc_speed_mul": 1.0,
        "ai_lane_min": 1.1,
        "ai_lane_max": 2.4,
        "ai_look_ahead_s": 150.0,
        "ai_react_chance": 0.78,
        "ai_idle_lane_chance": 0.12,
    },
    "hard": {
        "label": "어려움",
        "npc_speed_mul": 1.00,
        "ai_lane_min": 0.35,
        "ai_lane_max": 0.9,
        "ai_look_ahead_s": 220.0,
        "ai_react_chance": 0.96,
        "ai_idle_lane_chance": 0.04,
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

# ---------------------------------------------------------------------------
# 황소개구리 보스전 (activities/bullfrog) — 전역 기본값
# 맵별 덮어쓰기: world_data.json → [맵ID].bullfrog
# 진입: bg_jjangpu 이벤트존 → MAP bg_pond01 → start_bullfrog
# 퇴장: result.quit + return_map → ev_bullfrog_exit → return_from_bullfrog
# ---------------------------------------------------------------------------
BULLFROG_DEFAULTS = {
    # 기본 아레나 맵 ID (320×240 고정 화면)
    "default_map_id": "bg_pond01",
    # 세이브·강제종료 시 돌아갈 맵/좌표 (flow.resolve_activity_arena_exit)
    "exit_map": "bg_jjangpu",
    "exit_pos": [816.0, 2304.0],
    # 클리어 시 save_patch / win_flag 키
    "story_win_flag": "progress_bullfrog_win",
    # True면 보스 전투 없이 연꽃잎 점프만 (단계별 제작용). False면 물방울·반격 전투 ON
    "combat_enabled": True,
    # --- 타일 그리드 (논리 320×240 기준) ---
    # 화면 10×7.5타일 중 여백: 좌 32 / 우 32 / 위 16 → 플레이 그리드 8×7=56칸
    # 중앙 boss 4×3=12칸 제외 → 연꽃잎 44칸. 아래쪽은 16+7*32=240으로 여백 없음
    "tile_size": 32,
    "grid_cols": 8,
    "grid_rows": 7,
    "grid_origin_x": 32.0,   # 좌 여백 32px
    "grid_origin_y": 16.0,   # 위 여백 16px (배경·오브젝트 배치 공간)
    # 황소개구리 점유 타일 (col,row) 좌상단 + 폭·높이(칸)
    "boss_col": 2,
    "boss_row": 2,
    "boss_w": 4,
    "boss_h": 3,
    # 플레이어 시작 타일 (연꽃잎 칸). 화면 밖에서 이 칸으로 뛰어 들어옴
    "start_col": 0,
    "start_row": 6,
    # 카메라 고정 중심 (아레나 / 게임 화면)
    "cam_fixed": [160.0, 120.0],
    # 인트로 카메라: 맵 상단(풍경) → cam_fixed(게임 장소)로 이동 후 캐릭터 등장
    # intro_cam_from 생략 시 [cam_fixed.x, intro_cam_from_y]
    "intro_cam_from": None,
    "intro_cam_from_y": 60.0,   # 세로로 긴 맵(bg_pond01=480) 상단 쪽
    "intro_cam_hold_sec": 0.8,  # 상단에서 머무는 시간
    "intro_cam_pan_sec": 3.5,   # 상단 → 아레나 이동 시간
    # 논리 320맵을 화면에 맞추기 — world_zoom 2.0 (AUTO_OUTPUT → UPSCALED 320)
    "world_zoom_auto": True,
    # arena_world_zoom: 아레나 진입 시 목표 월드 줌 (2.0 = 타일 32px가 화면 1칸)
    "arena_world_zoom": 2.0,
    # 반격 prep(숙이기) 중 플레이어 중심 확대 — 야구 초강력타격과 동일 계열
    # (UPSCALE_320+줌2 상태에서 val=4 → 체감 2배 확대, 점프 시작 시 arena_world_zoom으로 복귀)
    "counter_zoom_value": 4.0,
    "counter_zoom_in_sec": 0.12,
    "counter_zoom_restore_sec": 0.12,
    "counter_zoom_cam_dur_sec": 0.12,
    # --- 에셋 키 (폴더: assets/images/character/<name>/) ---
    # bullfrog: idle / jump / splash / beattacked / lose
    "bullfrog_char": "bullfrog",
    # frog01: idle / jump — 반격 도움 개구리
    "ally_frog_char": "frog01",
    # 연꽃잎 3종(32×32). 기본 표시=land 루프, 캐릭터 착지 시 hit 1회 후 land 복귀
    # 폴더: character/lotusleaf1|2|3/land_left/ , hit_left/
    "lotus_leaf_sets": ["lotusleaf1", "lotusleaf2", "lotusleaf3"],
    # 연꽃잎은 바닥에 누운 타일 (야구 bbzone과 동일 — sprite_tilt 0 = 원근에 붙음)
    "lotus_sprite_tilt": 0.0,
    # hit 애니 길이(초). 0이면 프레임수/anim_fps 로 자동
    "leaf_hit_sec": 0.0,
    # 물방울 — fall(낙하) / impact(바닥 충돌·퍼짐)
    # waterdrop_char: character/ 폴더 캐릭터 방식 (fall_left, impact_left 서브폴더)
    "waterdrop_char": "waterdrop",
    # waterdrop_fx: 낙하 애니 (assets/images/fx/<name>/). 설정 시 fall에 우선
    "waterdrop_fx": "waterdrop01",
    "waterdrop_fx_dir": "assets/images/fx/waterdrop01",
    # waterdrop_impact_fx: 착지 퍼짐 애니. 설정 시 impact에 우선
    "waterdrop_impact_fx": "waterdrop02",
    "waterdrop_impact_fx_dir": "assets/images/fx/waterdrop02",
    # wave01 — 물결 FX. 폴더: assets/images/fx/wave01/wave01_0.png …
    "wave_fx": "wave01",
    "wave_fx_dir": "assets/images/fx/wave01",
    # splash01 — 착수 물튀김 (공격 착수 / 반격 후 낙하 공통)
    # splash02 준비되면 splash_counter_fx 만 바꾸면 됨
    # 폴더: assets/images/fx/splash01/
    "splash_attack_fx": "splash01",
    "splash_attack_fx_dir": "assets/images/fx/splash01",
    "splash_counter_fx": "splash01",
    "splash_counter_fx_dir": "assets/images/fx/splash01",
    # splash 위치/속도 보정
    # offset_y: 양수=아래, 음수=위
    "splash_fx_fps": 4.0,
    "splash_attack_offset_y": -30.0,
    "splash_counter_offset_y": -30.0,
    # 공격 착수: 물튀김 + 라이트블루 화면 페이드(물방울에 가려짐) 후 그림자→낙하
    "splash_fade_in_sec": 1.0,
    "splash_fade_hold_sec": 0.5,
    "splash_fade_out_sec": 1.5,
    "splash_fade_color": [160, 210, 255],
    "splash_fade_alpha_max": 255,
    # --- 전투 밸런스 ---
    # --- 진행 구조 ---
    # 1차·2차·3차 병렬 물방울 = 1턴(splash 1회)
    # 1턴→2턴→3턴(회피 성공) = 1세트 → 반격 기회
    # 1세트→2세트→3세트(반격 성공) = 게임 클리어
    # sets_to_win: 반격 성공(세트 클리어) 횟수 — 이만큼 성공하면 승리
    "sets_to_win": 3,
    # dodges_before_counter: 세트 안 반격 기회까지 필요한 "턴 회피 성공" 수
    # (물방울에 안 맞고 버틴 턴 수. 피격은 카운트되지 않음)
    # attacks_before_counter 는 구버전 호환 별칭
    "dodges_before_counter": 3,
    "attacks_before_counter": 3,
    # player_lives: 물방울에 맞으면 1 감소, 0이면 패배
    "player_lives": 3,
    # --- 물방울 다단 웨이브 (일반 공격 1회 = splash 1턴, 병렬) ---
    # 각 차는 독립 타이머: 그림자 예고 → 그 차 물방울 낙하.
    # n차 그림자 시작 시각 = (n-1) * drop_wave_gap_sec.
    # 예) gap=2, shadow=2.5 → t0:1차그림자 → t2:2차그림자 → t2.5:1차낙하 → t4:3차그림자 → t4.5:2차낙하 …
    # drop_wave_count: 한 턴에 띄울 병렬 웨이브 수 (반격 실패 전타일 패널티는 1파 고정)
    "drop_wave_count": 3,
    # drop_wave_gap_sec: 다음 차 그림자가 뜨기까지의 간격(초). 시험값 2.0
    "drop_wave_gap_sec": 2.0,
    # safe_tiles_by_set: 웨이브마다 "물방울이 안 떨어지는" 연꽃잎 개수 (난이도↑ = 수↓)
    # 액션성은 다단 회피로 올리고, 칸 수는 넉넉히 둬 회피 난이도는 낮춤.
    # 배치는 완전 랜덤이 아니라 맨해튼 거리 최대화로 화면 전체에 골고루 분산.
    "safe_tiles_by_set": [16, 14, 12],
    # shadow_sec_by_set: 각 차 그림자가 떠 있는 시간(초). 짧을수록 그 차 낙하가 빨리 옴
    # (페이드인·아웃 시간 포함 — 양끝 shadow_fade_sec 동안 서서히 나타나고 사라짐)
    "shadow_sec_by_set": [1.2, 1.2, 1.2],
    # shadow_fade_sec: 물방울 그림자 힌트 페이드인/아웃 각각 소요 시간(초)
    "shadow_fade_sec": 0.3,
    # 반격 실패(전타일 낙하) 그림자 예고 — 피할 수 없으므로 짧게 (단파)
    "counter_miss_shadow_sec": 0.5,
    # 황소개구리 일반 공격 1회: jump1(도약) → jump2(공중 대기) → jump3(복귀) → splash
    "boss_jump1_sec": 0.5,
    "boss_jump2_sec": 0.5,
    "boss_jump3_sec": 0.5,
    # (레거시) 공격 splash 페이즈는 splash_fade_in+hold+out 합으로 대체
    "boss_splash_sec": 2.4,
    # 반격 창: jump1(도약) 후 jumpfly를 counter_window_sec 끝날 때까지 유지 (창 중 하강 없음)
    # boss_jumpfly_sec 는 프레임 진행 스케일용(애니 길이 느낌). 체공 유지는 counter_window_sec.
    "boss_jumpfly_sec": 3.0,
    # 일반/반격 체공 높이 (월드 높이 px)
    "boss_jump_height": 80.0,
    "boss_jumpfly_height": 80.0,
    # 보스가 공중에 있을 때 화면 틸트 강도 (1.0=평평, 작을수록 더 강함)
    "boss_jump_tilt_factor": 0.30,
    # 틸트가 들어오고 빠지는 보간 시간(초)
    "boss_tilt_in_sec": 0.25,
    "boss_tilt_out_sec": 0.25,
    # 일반 공격 사이 휴식(초): 점프→다이빙→물방울 뒤 다음 점프까지
    "attack_interval_sec": 5.0,
    # 3회 공격 후 반격 예고: frog01 등장까지 / 등장 후 특수 점프까지
    "counter_spawn_delay_sec": 3.0,
    "counter_ready_delay_sec": 3.0,
    # 물방울 낙하·충돌 연출 시간
    "drop_fall_sec": 0.5,      # 기본 0.28 → 1.5× 느리게 (waterdrop01 fx 기준)
    "drop_impact_sec": 1.0,    # waterdrop02(5프레임) 1회 재생 분량
    # 물방울 낙하 시작 높이 (월드 좌표 기준, 양수 = 화면 위쪽 밖)
    # 카메라 뷰 높이보다 크면 화면 밖에서 시작
    "drop_start_height": 200.0,
    # 물방울 낙하 애니 fps (0 = 전역 anim_fps 사용)
    "drop_anim_fps": 5.0,       # 기본 anim_fps(10) 절반
    # 반격: 특수 점프 창 동안 frog01 타일 착지 → 반격 시퀀스 진입
    # (창 동안 보스는 jumpfly 체공 유지. 이 값을 늘리면 반격 가능 시간도 늘어남)
    "counter_window_sec": 3.0,
    # frog01 착지 후 idle 첫 프레임 고정(숙이기) 대기 — 줄이면 바로 같이 점프
    "counter_prep_sec": 1.2,
    # 보스 배(중앙)로 뛰어오르는 점프 / 원래 타일 복귀 점프 (frog01 제자리 점프도 동일 길이)
    "counter_ascent_sec": 0.8,
    "counter_return_sec": 0.8,
    # frog01이 플레이어를 밀어줄 때 제자리 점프 높이 (없으면 player_jump_height)
    "ally_boost_jump_height": 30.0,
    # 플레이어 tickle · 보스 down 전환은 여기부터 (반격 창/상승 중에는 jumpfly 유지)
    "tickle_sec": 1.2,
    # 보스 체공 높이보다 이만큼 낮게 = 배 위치
    "tickle_belly_height_below": 5.0,
    # 반격 성공 후 보스 하강(down) → sink → (잠수) → emerge
    "boss_down_sec": 1.0,
    "boss_counter_descend_sec": 0.55,
    "sink_sec": 1.0,
    "submerged_sec": 1.0,
    "rise_sec": 1.0,
    # 플레이어 타일 점프(인접 1칸) 시간·높이 (기존 0.22/14 → 1.5배)
    "player_jump_sec": 0.4,
    "player_jump_height": 25.0,
    # 점프 중 물방울 피격: 출발 칸으로 남는 시간 비율 (1.0=착지 전까지, 0.5=전반부만, 0=즉시 도착칸)
    # 예전에는 점프 전체가 무적이라 난이도가 낮았음. 착지 전까지는 출발 칸에 떨어진 물방울에 맞음.
    "jump_hit_origin_frac": 1.0,
    # 착지 후 다음 점프까지 쿨타임(초)
    "player_land_cooldown_sec": 0.05,
    # 착지 바운스: 연꽃잎이 가라앉았다가 튕기는 느낌. 휴식 발점 기준 Y오프셋(px, +아래)
    # 프레임 간격은 anim_fps (기본 10 → 0.1초/칸)
    "player_land_bob_y": [3, 1, 0, 0, -3, -1],
    # 인트로: 화면 밖에서 시작 타일로 뛰어 들어오는 시간
    "intro_enter_sec": 0.5,
    # 착지 후 큰 타이틀("게임 시작!") 표시 시간
    "intro_title_sec": 1.5,
    "intro_title_text": "게임 시작!",
    # 타이틀 끝난 뒤 첫 공격까지 쿨타임(초)
    "intro_cooldown_sec": 3.0,
    # 피격 — falldown 애니 총 길이(초). 끝나면 idle 복귀 후 진행
    "falldown_sec": 2.0,
    # 프레임별 지속시간(초) 목록. falldown은 2프레임: [0.5, 1.5]
    # 합계가 falldown_sec 와 다르면 falldown_sec 가 우선 (비율 유지로 스케일)
    "falldown_frame_sec": [0.5, 1.5],
    # (구버전 호환) falldown_sec 없을 때 사용
    "hit_stun_sec": 1.0,
    # 결과 화면 유지 후 자동 퇴장
    "result_hold_sec": 2.2,
    # 애니 FPS (에셋 있을 때)
    "anim_fps": 10.0,
}

# ---------------------------------------------------------------------------
# 징검다리 횡단 (activities/lotus_cross) — 황소개구리 축약판
# 맵별 덮어쓰기: world_data.json → [맵ID].lotus_cross
# 진입: bg_pond02 이벤트존 A/B → start_lotus_cross (from_side=a|b)
#       이벤트박스 발 위치에서 시작 타일로 점프 착지 (순간이동 없음)
# 타일: bullfrog 와 같이 origin + cols×rows 균일 그리드 (칸 개별 좌표 없음)
# 표시: 활동 시작 전에도 같은 그리드로 연꽃잎을 그림. world_data.objects 에 따로 깔지 말 것
# 퇴장: 끝 열에서 강가 쪽으로 한 칸 더 점프 → exit_pos_* 착지 후 필드 복귀
#       타일 위에서는 A·B 양쪽 모두 나갈 수 있음 (순간이동 없음)
# ---------------------------------------------------------------------------
LOTUS_CROSS_DEFAULTS = {
    # 기본 맵 (맵 전환 없이 그 자리에서 플레이)
    "default_map_id": "bg_pond02",
    # --- 그리드 (황소개구리 BULLFROG_DEFAULTS 와 같은 키) ---
    # tile_size: 한 칸 크기(px)
    "tile_size": 32,
    # grid_origin_x/y: 좌상단 타일의 왼쪽·위 모서리 (중심이 아님)
    "grid_origin_x": 590.5,
    "grid_origin_y": 46.5,
    # grid_cols / grid_rows: 가로·세로 칸 수. 전부 연꽃잎
    "grid_cols": 5,
    "grid_rows": 1,
    # 진입 시 시작 칸 (col, row). A=왼쪽, B=오른쪽
    "start_a": [0, 0],
    "start_b": [4, 0],
    # 이 열에서 그리드 밖으로 점프하면 해당 강가로 퇴장
    # exit_a_col: 더 왼쪽(←) → exit_pos_a / exit_b_col: 더 오른쪽(→) → exit_pos_b
    "exit_a_col": 0,
    "exit_b_col": 4,
    # 퇴장 착지 좌표 (이벤트박스 밖·걸어갈 수 있는 길)
    "exit_pos_a": [516.0, 78.0],
    "exit_pos_b": [824.0, 140.0],
    # 끝 열에서 exit_pos 를 직접 터치할 때 인정 반경 = tile_size * 이 값
    "exit_click_radius_ratio": 1.25,
    # --- 연꽃잎 ---
    # 타일마다 lotusleaf1~3 고정 순환 (col+row*cols). 필드 장식과 활동 중 동일
    "lotus_leaf_sets": ["lotusleaf1", "lotusleaf2", "lotusleaf3"],
    # pond02 는 tilt/shear 없음 → 1.0(세움). 황소개구리 아레나는 0.0(눕힘)
    "lotus_sprite_tilt": 1.0,
    # hit 애니 길이(초). 0이면 프레임수/anim_fps 자동
    "leaf_hit_sec": 0.0,
    "anim_fps": 10.0,
    # --- 점프 (황소개구리와 같은 값) ---
    "player_jump_sec": 0.4,
    "player_jump_height": 25.0,
    # 점프 중 물방울 피격: 출발 칸으로 남는 시간 비율 (1.0=착지 전까지, 0.5=전반부만)
    "jump_hit_origin_frac": 0.5,
    "player_land_cooldown_sec": 0.05,
    "player_land_bob_y": [3, 1, 0, 0, -3, -1],
    # 이벤트박스→시작타일 거리가 이 값(px) 이하면 점프 없이 스냅 (이미 칸 위)
    "enter_snap_px": 6.0,
    # follow NPC: 이벤트박스 진입 시 fadeout → exit_pos 착지 후 플레이어 근처 fadein (초). 0이면 즉시
    "follow_fade_sec": 0.5,
    # --- 튜토리얼 물방울 (황소개구리 축약, BULLFROG_DEFAULTS 의 drop/falldown 에셋 재사용) ---
    # drops_enabled: true 면 ST_PLAY 중 그림자→낙하 반복 (목숨·점수 없음)
    "drops_enabled": True,
    # drop_first_delay_sec: ST_PLAY 진입 후 첫 그림자까지 대기(초)
    "drop_first_delay_sec": 2.0,
    # drop_interval_sec: 한 번 낙하·착지 연출이 끝난 뒤 다음 그림자까지 대기(초)
    "drop_interval_sec": 4.0,
    # drop_shadow_sec: 그림자만 보이는 예고 시간(초)
    "drop_shadow_sec": 1.0,
    # drops_per_wave: 한 번에 떨어질 랜덤 칸 수
    "drops_per_wave": 1,
    # drop_exclude_player_tile: true 면 플레이어가 서 있는 칸은 후보에서 제외
    "drop_exclude_player_tile": False,
}

# 시크릿 상자·소환 시 실제로 나올 수 있는 효과 풀
RACING_MYSTERY_EFFECT_POOL = ("speed", "slow", "swap")
# 추첨 가중치 — 시크릿 룰렛·소환 아이템 공통 (_pick_mystery_effect)
# 기본 1.0, 위치 교환(swap)은 더 희귀하게 (예전 0.3 → 0.12 ≈ 5.7%)
RACING_MYSTERY_EFFECT_WEIGHTS = {
    "speed": 1.0,
    "slow": 1.0,
    "swap": 0.12,
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
# 폰트 파일은 assets/fonts 폴더에 있습니다.
# cafe24ssuround(16).ttf
# dunggeunmo(8).ttf
# galmuri11(8).ttf
# mulmaru(16).ttf
# NanumGothic.ttf
# Pinkfong Baby Shark Font_ Bold.ttf

UI_FONT_FILES = {
    "default": "assets/fonts/mulmaru(16).ttf",
    "dialog": "assets/fonts/mulmaru(16).ttf",
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
        "size_320": 12,
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
        "size_320": 12,
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
        "size_320": 12,
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
        "size_320": 12,
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
        "size_320": 12,
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









# ---------------------------------------------------------------------------
# 가상(파생) 캐릭터 애니 세트 — 디스크에 <state>_left/ 폴더가 없을 때
# 기존 세트를 변환해 런타임 생성. 실제 폴더가 있으면 폴더가 우선.
# 이벤트 ACTION_ANIM / 에디터 / 미니게임에서 동일하게 사용.
# ---------------------------------------------------------------------------
# frames: 프레임별 소스 지정
#   source: 원본 세트명 (idle, run, seat_idle …)
#   index: 프레임 번호 (없으면 전체 세트)
#   rotate_cw_deg: 시계방향 회전(도). 90 지원
#   align_feet: True면 원본 발(하단 중앙)이 결과 하단 중앙에 오도록 패딩
#   offset_y: 시각 Y 오프셋(원본 px). 양수=화면 아래, 음수=위 (발 월드 좌표는 유지)
# source_set: 세트 전체를 동일 변환으로 복사할 때
CHAR_DERIVED_ANIM_SETS = {
    # 피격 쓰러짐: seat_idle_4 → idle_4 (각 시계방향 90° + 발 정렬)
    # ACTION_ANIM: { "anim":"falldown", "mode":"hold" } — loop=false·release=stop 자동, frame_sec=BULLFROG_DEFAULTS
    "falldown": {
        "offset_y": 20,
        "frames": [
            {"source": "seat_idle", "index": 4, "rotate_cw_deg": 90, "align_feet": True},
            {"source": "idle", "index": 4, "rotate_cw_deg": 90, "align_feet": True},
        ],
    },
    # 간질: run 세트 전체 시계방향 90° + 발 정렬
    "tickle": {
        "source_set": "run",
        "rotate_cw_deg": 90,
        "align_feet": True,
    },
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
        # Mode7 품질은 Android에서도 사용자가 고른 레이스 옵션을 그대로 따른다.
        "ROTATE3D_QUALITY_SCALE": 1.0,
        "ROTATE3D_ANDROID_QUALITY_SCALE": 1.0,
        "ROTATE3D_ANDROID_QUALITY_CAP": 1.0,
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
    "bullfrog": {
        "hud_px_320": 11,              # 세트·목숨 HUD
        "announce_px_320": 16,         # 중앙 안내 문구
        "result_px_320": 22,           # 승리/패배
        "title_px_320": 32,            # 시작 타이틀(게임 시작!)
    },
}

UI_OVERLAY_DEFAULTS = {
    "game_exit_btn": {"size": 10, "pad_x": 6, "pad_y": 3},
    "game_exit_confirm": {"text_size": 13, "button_size": 12},
}

# SAY 레이아웃 키 — ui.state.json say{} 에서 CONFIG 로 반영
UI_SAY_LAYOUT_KEYS = (
    "SAY_TEXTBOX_RECT_320",
    "SAY_TEXTBOX_RECT_TOP_320",
    "SAY_TEXTBOX_TOP_BLIT_Y_PX_320",
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

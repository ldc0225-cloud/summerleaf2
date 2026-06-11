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
    "AUTO_OUTPUT_MODE_ENABLED": False,
    "AUTO_OUTPUT_MODE_ON_WORLD_ZOOM": 2.0,
    "AUTO_OUTPUT_MODE_OFF_WORLD_ZOOM": 1.0,
    "AUTO_OUTPUT_MODE_COOLDOWN_MS": 900,


    # 논리 해상도(게임 내부 좌표 기준)
    "WIDTH": 640, "HEIGHT": 480, "FPS": 30,
    # UI 아이콘(말풍선·이모트·존 클릭 FX): 논리 px = 에셋 px (NATIVE_640 기준 1:1)
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
    # 손에 든 물건 발(foot) 격자 — 플레이어 발 기준 월드 오프셋 (engine._held_item_foot_world_pos)
    # Y: 클수록 손 위치가 위로(플레이어 pos.y - Y). X: 바라보는 방향 옆 간격.
    "HELD_ITEM_FOOT_OFFSET_X": 12,
    "HELD_ITEM_FOOT_OFFSET_Y": 6,

    # 세이브 없음·merge 기본값 / load_map 플레이어 생성 시 CHAR_ASSETS 키
    "DEFAULT_PLAYER_CHAR": "c10",
    "CHAR_SPEED": 1.6, "CURSOR_SPEED": 3.5,
    # 클릭 이동
    "DOUBLE_CLICK_MS": 280,
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
    "SAY_FONT_SIZE_320": 9,
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
    # 같은 이벤트 안에서 SAY가 연속일 때: 박스 페이드아웃/인 없이 다음 대사만 갱신
    "SAY_CHAIN_WITHIN_EVENT": True,
    # 색상
    "SAY_NAME_COLOR": (0, 0, 0),
    "SAY_TEXT_COLOR": (50, 50, 50),
    # 폰트 테두리(스트로크): 가독성 개선용. (pygame 기본기능 아님 → 여러 번 찍는 방식)
    "SAY_FONT_OUTLINE_ENABLED": True,
    "SAY_FONT_OUTLINE_PX_320": 1,  # 320 기준 두께 (640에서는 2배)
    "SAY_FONT_OUTLINE_COLOR": (255, 255, 255),

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
    "WORLD_ZOOM_DEFAULT": 1.0,   # 1.0=기본, 2.0=2배 확대, 0.5=절반 축소
    "WORLD_ZOOM_MIN": 1.0,
    "WORLD_ZOOM_MAX": 2.0,
    "WORLD_ZOOM_SPEED": 3.0,     # zoom/sec (값이 클수록 더 빠르게 확대/축소)

    # --- 개별 오브젝트 줌(별개 기능) ---
    # 이벤트 ZOOM에서 target이 player/NPC/오브젝트인 경우에만 사용. (camera/global 대상 줌은 WORLD_ZOOM으로 처리)
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
    "SPRITE_SCALE_STEP": 0.1,
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




    # 스프라이트 쉬어: 배경보다 더 굵게 잘라도 티가 덜 나고, 비용이 크게 줄어듦.
    "SPRITE_SHEAR_SLICE_H_PX": 1,
    # 스프라이트 쉬어 LOD: 줌/틸트/쉬어가 변하는 동안엔 더 거칠게(또는 생략)해서 프레임 유지
    "SPRITE_SHEAR_DURING_ANIM": True,
    "SPRITE_SHEAR_SLICE_H_PX_LOD": 2,
    # 쉬어 샘플 Y를 픽셀 단위로 양자화해 캐시 재사용/떨림 완화
    "SPRITE_SHEAR_Y_QUANT_PX": 1,
    "SPRITE_SHEAR_Y_QUANT_PX_LOD": 2,
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
        {"key": "F9", "event_id": "ev_hotkey_jump_shadow"},  # 점프 그림자 토글
        {"key": "x", "event_id": "ev_hotkey_zoom_cycle"},  # 줌 순환
        {"key": "y", "event_id": "ev_hotkey_cloud"},  # 구름 효과
    ],
    # 시작 시 디버그 텍스트 오버레이(HUD) 기본 표시 여부. 런타임 토글은 'O' 키.
    "SHOW_OVERLAY_DEFAULT": False,
    # 오버레이(HUD)를 껐을 때도 RSS 메모리 표시를 남길지 여부.
    "SHOW_RSS_OVERLAY_WHEN_OFF": False,
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
    "DEBUG_ZOOM_STEPS": [2.0, 1.0],

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
    "progress_wateringcan":1001
}

# UI 폰트 레지스트리: 논리 이름 → 프로젝트 루트 기준 .ttf 경로.
# 값이 None 이거나 파일이 없으면 런타임에서 pygame 기본 폰트를 씁니다.
UI_FONT_FILES = {
    "default": "assets/fonts/NanumGothic.ttf",
    "dialog": "assets/fonts/NanumGothic.ttf",
    "logo": "assets/fonts/Pinkfong Baby Shark Font_ Bold.ttf",
}









# path 규칙 (object_defs.json 주석용 요약):
# - 단일: images/object/tree1.png
# - 애니: images/object/flower1_0.png → flower1_1.png … / 폴더 images/object/grass01/
# - anim_delay_ms 생략 시 CONFIG["ANIM_DELAY"]
from entity_defs import load_char_defs, load_object_defs, reload_entity_defs

OBJ_ASSETS = load_object_defs()
CHAR_ASSETS = load_char_defs()
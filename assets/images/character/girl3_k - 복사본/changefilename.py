import os
import shutil

# 변환 규칙 정의: (시작번호, 끝번호, 이름)
rules = [
    (1, 8, "walk_left"),
    (9, 16, "idle_left"),
    (17, 20, "seating_left"),
    (21, 28, "seat_idle_left"),
    (29, 36, "jump_left"),
    (37, 40, "run_left")
]

# 현재 작업 디렉토리의 파일 목록
files = os.listdir('.')

for start, end, new_name in rules:
    # 혹시 폴더가 없다면 자동으로 생성 (안전장치)
    if not os.path.exists(new_name):
        os.makedirs(new_name)
        print(f"폴더 생성됨: {new_name}")

    for i in range(start, end + 1):
        old_filename = f"c{i}.png"
        
        if old_filename in files:
            index = i - start
            new_filename = f"{new_name}_{index}.png"
            
            # 최종적으로 이동할 목적지 경로 (예: walk_left/walk_left_0.png)
            destination_path = os.path.join(new_name, new_filename)
            
            # 이름 변경과 동시에 폴더 안으로 이동
            shutil.move(old_filename, destination_path)
            print(f"이동 완료: {old_filename} -> {destination_path}")

print("\n모든 파일 이름 변경 및 폴더 이동 작업이 끝났습니다!")
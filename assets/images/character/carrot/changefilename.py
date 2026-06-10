import os

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
    for i in range(start, end + 1):
        old_filename = f"c{i}.png"
        
        if old_filename in files:
            index = i - start
            new_filename = f"{new_name}_{index}.png"
            
            os.rename(old_filename, new_filename)
            print(f"Done: {old_filename} -> {new_filename}")

print("\n모든 작업이 끝났습니다!")
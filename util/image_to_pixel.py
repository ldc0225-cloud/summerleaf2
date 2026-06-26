import os
from tkinter import messagebox
import tkinter as tk
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import Image
from collections import Counter

def get_center_dominant_color(image_chunk, sample_ratio=0.1):
    w, h = image_chunk.size
    margin_w = (w * (1 - sample_ratio)) / 2
    margin_h = (h * (1 - sample_ratio)) / 2
    left, top = max(0, margin_w), max(0, margin_h)
    right, bottom = min(w, w - margin_w), min(h, h - margin_h)
    if right <= left: right = left + 1
    if bottom <= top: bottom = top + 1
    center_chunk = image_chunk.crop((left, top, right, bottom))
    pixels = list(center_chunk.convert("RGB").getdata())
    return Counter(pixels).most_common(1)[0][0]

def process_image():
    # 윈도우에서 경로 드래그 시 생기는 중괄호와 따옴표 제거
    file_path = file_entry.get().strip().strip('{}').strip('"')
    try:
        blocks_x = int(blocks_entry.get())
        color_limit = int(color_entry.get())
    except ValueError:
        messagebox.showerror("에러", "블럭 수와 컬러 제한은 숫자로 입력해주세요.")
        return

    if not file_path or not os.path.exists(file_path):
        messagebox.showerror("에러", "파일을 선택하거나 드래그해 주세요.")
        return

    try:
        with Image.open(file_path) as img:
            if img.mode == 'RGBA':
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img_final = background
            else:
                img_final = img.convert("RGB")
            
            img_limited = img_final.quantize(colors=color_limit, method=2).convert("RGB")
            orig_w, orig_h = img_limited.size
            block_size = orig_w / blocks_x
            blocks_y = int(orig_h / block_size)
            
            new_img = Image.new("RGB", (blocks_x, blocks_y))
            for y in range(blocks_y):
                for x in range(blocks_x):
                    left, top = x * block_size, y * block_size
                    right, bottom = (x + 1) * block_size, (y + 1) * block_size
                    chunk = img_limited.crop((left, top, right, bottom))
                    new_img.putpixel((x, y), get_center_dominant_color(chunk))
            
            dir_name, full_name = os.path.split(file_path)
            file_name, file_ext = os.path.splitext(full_name)
            save_path = os.path.join(dir_name, f"{file_name}_edit{file_ext}")
            new_img.save(save_path)
            messagebox.showinfo("완료", f"저장 완료!\n{save_path}")
    except Exception as e:
        messagebox.showerror("에러", f"오류 발생: {e}")

def handle_drop(event):
    file_entry.delete(0, tk.END)
    # 중괄호 제거 후 입력
    clean_path = event.data.strip().strip('{}').strip('"')
    file_entry.insert(0, clean_path)

# GUI 설정
root = TkinterDnD.Tk()
root.title("Pixel Sprite Sampler")
root.geometry("500x380")

# 드래그 앤 드롭 영역 (relief="solid"로 수정)
drop_label = tk.Label(root, text="\n이미지 파일을 여기에 드래그 하세요\n", 
                      relief="solid", bd=1, bg="#f9f9f9", fg="#333333")
drop_label.pack(fill="x", padx=20, pady=20)
drop_label.drop_target_register(DND_FILES)
drop_label.dnd_bind('<<Drop>>', handle_drop)

# 경로 표시창
file_entry = tk.Entry(root, width=50)
file_entry.pack(padx=20)

# 설정값 입력 영역
config_frame = tk.Frame(root)
config_frame.pack(pady=20)

tk.Label(config_frame, text="가로 블럭 수:").grid(row=0, column=0, padx=5, pady=5)
blocks_entry = tk.Entry(config_frame, width=15)
blocks_entry.insert(0, "32")
blocks_entry.grid(row=0, column=1)

tk.Label(config_frame, text="컬러 제한:").grid(row=1, column=0, padx=5, pady=5)
color_entry = tk.Entry(config_frame, width=15)
color_entry.insert(0, "16")
color_entry.grid(row=1, column=1)

# 실행 버튼
btn = tk.Button(root, text="픽셀 추출 시작", command=process_image, 
                bg="#2196F3", fg="white", width=20, height=2, font=("Arial", 10, "bold"))
btn.pack(pady=10)

root.mainloop()
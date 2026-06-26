import os
from tkinter import Tk, Label
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import Image

def process_image(file_path):
    try:
        # 파일 경로 정제 (드래그 시 중괄호 제거)
        path = file_path.strip('{}')
        if not path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
            print("지원하지 않는 파일 형식입니다.")
            return

        with Image.open(path) as img:
            img = img.convert("RGBA")
            width, height = img.size
            
            # 새 이미지 너비 계산: 원본 너비 + (높이 - 1) 만큼 옆으로 밀리게 됨
            new_width = width + (height - 1)
            new_img = Image.new("RGBA", (new_width, height), (0, 0, 0, 0))

            for y in range(height):
                # 위쪽 줄(y=0)이 가장 많이 밀림: (height - 1 - y)
                # 아래쪽 줄(y=height-1)이 0만큼 밀림
                offset = (height - 1) - y
                
                for x in range(width):
                    pixel = img.getpixel((x, y))
                    new_img.putpixel((x + offset, y), pixel)

            # 저장 경로 설정 (_edit 붙이기)
            dir_name = os.path.dirname(path)
            base_name = os.path.splitext(os.path.basename(path))[0]
            save_path = os.path.join(dir_name, f"{base_name}_edit.png")
            
            new_img.save(save_path)
            print(f"저장 완료: {save_path}")
            label.config(text=f"완료: {base_name}_edit.png", fg="blue")

    except Exception as e:
        print(f"에러 발생: {e}")
        label.config(text="처리 중 오류 발생", fg="red")

# GUI 설정
root = TkinterDnD.Tk()
root.title("Pixel Shear Tool")
root.geometry("400x200")

label = Label(root, text="\n\n여기에 이미지 파일을\n끌어다 놓으세요 (Drag & Drop)", padx=10, pady=10)
label.pack(expand=True, fill="both")

# 드래그 앤 드롭 이벤트 바인딩
root.drop_target_register(DND_FILES)
root.dnd_bind('<<Drop>>', lambda e: process_image(e.data))

root.mainloop()
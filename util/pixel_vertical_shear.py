import os
from tkinter import Tk, Label
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import Image

def process_image_vertical(file_path):
    try:
        # 파일 경로 정제
        path = file_path.strip('{}')
        if not path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
            print("지원하지 않는 파일 형식입니다.")
            return

        with Image.open(path) as img:
            img = img.convert("RGBA")
            width, height = img.size
            
            # 새 이미지 높이 계산: 원본 높이 + (너비 - 1) 만큼 위로 밀리게 됨
            new_height = height + (width - 1)
            new_img = Image.new("RGBA", (width, new_height), (0, 0, 0, 0))

            for x in range(width):
                # 맨 왼쪽 줄(x=0)이 가장 아래(그대로)
                # 오른쪽으로 갈수록 위로 이동 (offset 증가)
                # y좌표에 (width - 1 - x)를 더해주면 상대적으로 위로 올라가는 효과
                offset = (width - 1) - x
                
                for y in range(height):
                    pixel = img.getpixel((x, y))
                    # offset만큼 위쪽 좌표에 픽셀을 배치
                    new_img.putpixel((x, y + offset), pixel)

            # 저장 경로 설정 (_v_edit 붙이기)
            dir_name = os.path.dirname(path)
            base_name = os.path.splitext(os.path.basename(path))[0]
            save_path = os.path.join(dir_name, f"{base_name}_v_edit.png")
            
            new_img.save(save_path)
            print(f"저장 완료: {save_path}")
            label.config(text=f"완료: {base_name}_v_edit.png", fg="blue")

    except Exception as e:
        print(f"에러 발생: {e}")
        label.config(text="처리 중 오류 발생", fg="red")

# GUI 설정
root = TkinterDnD.Tk()
root.title("Vertical Pixel Shear Tool")
root.geometry("400x200")

label = Label(root, text="\n\n세로 기울이기 (오른쪽이 위로)\n이미지를 끌어다 놓으세요", padx=10, pady=10)
label.pack(expand=True, fill="both")

root.drop_target_register(DND_FILES)
root.dnd_bind('<<Drop>>', lambda e: process_image_vertical(e.data))

root.mainloop()
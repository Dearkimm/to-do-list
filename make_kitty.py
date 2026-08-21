# -*- coding: utf-8 -*-
"""kitty_source.jpg(핀터레스트 월페이퍼)에서 키티 얼굴을 크롭해 아이콘/헤더 이미지 생성."""
from PIL import Image, ImageDraw

SRC = "kitty_source.jpg"
# 원본 1080x1920 기준, 상단 중앙의 반듯한 얼굴
FACE_BOX = (644, 328, 821, 492)      # 헤더용 크롭 (리본 포함 얼굴 중앙 정렬)
ICON_BOX = (618, 296, 846, 524)      # 아이콘용 정사각 크롭 (여백 포함)


def rounded(img, radius_ratio):
    mask = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(mask)
    r = int(min(img.size) * radius_ratio)
    d.rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], radius=r,
                        fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


if __name__ == "__main__":
    src = Image.open(SRC)

    icon = rounded(src.crop(ICON_BOX).resize((256, 256), Image.LANCZOS), 0.22)
    # 파일명을 바꾸면 Windows 아이콘 캐시를 우회한다
    icon.save("app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                (64, 64), (128, 128), (256, 256)])

    face = src.crop(FACE_BOX)
    h = 64  # 고해상도 마스터 — 앱에서 배율에 맞춰 축소
    w = int(h * face.size[0] / face.size[1])
    rounded(face.resize((w, h), Image.LANCZOS), 0.18).save("kitty.png")

    icon.save("preview_icon.png")
    print("saved", (w, h))

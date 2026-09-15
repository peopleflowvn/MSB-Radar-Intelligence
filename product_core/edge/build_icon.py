# -*- coding: utf-8 -*-
"""
Tạo file icon.ico chuẩn cho MSB Radar Edge từ logo gốc.

Vì sao cần script này thay vì đổi đuôi .png thành .ico:
  • Windows dùng NHIỀU cỡ icon khác nhau tuỳ chỗ hiển thị (16px ở thanh tiêu đề và
    Explorer dạng danh sách, 32px ở Alt+Tab, 48px ở màn hình nền, 256px ở xem trước
    cỡ lớn). File .ico phải NHÚNG SẴN từng cỡ, mỗi cỡ được thu nhỏ riêng bằng thuật
    toán chất lượng cao. Nếu chỉ nhúng 1 ảnh 256px, Windows phải tự thu nhỏ lúc chạy
    bằng thuật toán rẻ tiền -> icon bị nhoè, bệt màu ở taskbar.
  • Logo gốc là ảnh RGB KHÔNG có kênh alpha: vùng ngoài ô vuông bo góc là màu đen
    đặc, không phải trong suốt. Dùng thẳng thì icon sẽ là một hình vuông đen ở mọi
    cỡ — lộ rõ trên taskbar sáng màu. Script cắt đúng ô vuông rồi tự dựng lại viền
    bo góc trong suốt.

Cách dùng:
    python build_icon.py            # tạo app/assets/icon.ico
    python build_icon.py --preview  # xuất ảnh xem thử ở các cỡ thật để kiểm tra mắt
"""
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE_PNG = os.path.join(os.path.dirname(HERE), "MRadar.png")
OUT_ICO = os.path.join(HERE, "app", "assets", "icon.ico")

# Các cỡ Windows thực sự dùng. Thiếu cỡ nào, Windows tự thu nhỏ cỡ đó -> xấu.
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]

# Ngưỡng phân biệt nền đen ngoài ô với nền xám rất tối của chính ô (#18181a).
# Đặt thấp để không ăn mất viền khử răng cưa của ô.
BLACK_THRESHOLD = 8

# Bán kính bo góc theo tỉ lệ cạnh, đo từ chính logo gốc (~199px trên ô ~950px).
CORNER_RADIUS_RATIO = 0.21

# Vẽ mask ở độ phân giải gấp 4 rồi thu nhỏ, để viền cong mượt thay vì răng cưa.
SUPERSAMPLE = 4


def _tile_bbox(image):
    """Tìm ô vuông bo góc bên trong ảnh, bỏ phần nền đen bao quanh.

    Không dùng getbbox() của kênh alpha như bản trước: logo này không có alpha
    nên getbbox() luôn trả về nguyên khung ảnh và phần đen thừa vẫn còn nguyên.
    """
    pixels = image.load()
    width, height = image.size

    def has_content(x, y):
        return max(pixels[x, y][:3]) > BLACK_THRESHOLD

    columns = [x for x in range(width)
               if any(has_content(x, y) for y in range(0, height, 4))]
    rows = [y for y in range(height)
            if any(has_content(x, y) for x in range(0, width, 4))]
    if not columns or not rows:
        # Ảnh không có nền đen bao quanh; dùng nguyên khung.
        return (0, 0, width, height)
    return (columns[0], rows[0], columns[-1] + 1, rows[-1] + 1)


def load_tile():
    """Đọc logo, cắt đúng ô vuông và trả về ảnh RGBA đã bo góc trong suốt."""
    source = Image.open(SOURCE_PNG).convert("RGB")
    tile = source.crop(_tile_bbox(source)).convert("RGBA")

    # Ép về vuông: phép đo theo ngưỡng có thể lệch vài pixel giữa hai chiều, mà
    # icon lệch tỉ lệ sẽ bị Windows kéo méo.
    side = min(tile.size)
    left = (tile.size[0] - side) // 2
    top = (tile.size[1] - side) // 2
    tile = tile.crop((left, top, left + side, top + side))

    mask = Image.new("L", (side * SUPERSAMPLE, side * SUPERSAMPLE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, side * SUPERSAMPLE - 1, side * SUPERSAMPLE - 1],
        radius=round(side * SUPERSAMPLE * CORNER_RADIUS_RATIO), fill=255)
    tile.putalpha(mask.resize((side, side), Image.LANCZOS))
    return tile


def render(size, tile=None):
    """Dựng một cỡ icon từ ảnh gốc độ phân giải cao."""
    tile = tile if tile is not None else load_tile()
    return tile.resize((size, size), Image.LANCZOS)


def write_ico(out_path=OUT_ICO):
    """Tạo .ico nhúng sẵn đủ mọi cỡ, mỗi cỡ dựng riêng từ ảnh gốc."""
    tile = load_tile()
    # Dựng riêng từng cỡ từ ảnh gốc (KHÔNG thu nhỏ dây chuyền 256->128->64...,
    # vì thu nhỏ nhiều lần sẽ cộng dồn sai số làm mờ hình).
    frames = [render(s, tile) for s in ICO_SIZES]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    frames[-1].save(out_path, format="ICO",
                    sizes=[(s, s) for s in ICO_SIZES],
                    append_images=frames[:-1])
    return out_path


def make_preview(out_path):
    """Xuất ảnh so sánh các cỡ thật trên cả nền sáng và nền tối.

    Nền sáng là phép thử quan trọng nhất: đây là lúc lộ ra viền bo góc có thật
    sự trong suốt hay vẫn còn khối đen thừa.
    """
    show_sizes = [256, 128, 48, 32, 16]
    pad, gap, label_w = 24, 28, 110
    row_h = 256 + 44
    width = label_w + sum(show_sizes) + gap * len(show_sizes) + pad * 2
    height = pad * 2 + row_h * 2

    tile = load_tile()
    sheet = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(sheet)

    y = pad
    for name, background in (("nen sang", (245, 246, 248)), ("nen toi", (32, 33, 36))):
        draw.rectangle([pad, y, width - pad, y + row_h - 10], fill=background)
        ink = (110, 110, 110) if background[0] > 128 else (205, 205, 205)
        draw.text((pad + 10, y + row_h // 2 - 6), name, fill=ink)
        x = pad + label_w
        for size in show_sizes:
            sheet.alpha_composite(render(size, tile), (x, y + (row_h - 44 - size) // 2 + 10))
            draw.text((x, y + row_h - 34), f"{size}px", fill=ink)
            x += size + gap
        y += row_h

    sheet.convert("RGB").save(out_path)
    return out_path


if __name__ == "__main__":
    if not os.path.isfile(SOURCE_PNG):
        raise SystemExit(f"Không tìm thấy logo gốc: {SOURCE_PNG}")

    if "--preview" in sys.argv:
        index = sys.argv.index("--preview")
        target = (sys.argv[index + 1] if len(sys.argv) > index + 1
                  else os.path.join(HERE, "icon_preview.png"))
        print("Da xuat anh so sanh:", make_preview(target))
    else:
        path = write_ico()
        print(f"Da tao {path} ({len(ICO_SIZES)} co: "
              f"{', '.join(str(s) for s in ICO_SIZES)})")

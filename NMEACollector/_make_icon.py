"""Tạo icon cho NMEACollector — radar màn xanh hải quân + sóng tín hiệu."""

from PIL import Image, ImageDraw
import math, os

SIZE = 256

img  = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

cx, cy = SIZE // 2, SIZE // 2

# ── Nền tròn màu xanh đậm ──────────────────────────────────────────────
draw.ellipse([4, 4, SIZE-4, SIZE-4], fill="#0a1628", outline="#1a3a5c", width=6)

# ── Vòng tròn radar ────────────────────────────────────────────────────
for r, alpha in [(100, 80), (70, 110), (40, 140)]:
    color = (0, 200, 100, alpha)
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color, width=2)

# ── Đường kính ngang và dọc (lưới radar) ──────────────────────────────
grid_col = (0, 160, 80, 60)
draw.line([(cx-100, cy), (cx+100, cy)], fill=grid_col, width=1)
draw.line([(cx, cy-100), (cx, cy+100)], fill=grid_col, width=1)
draw.line([(cx-70, cy-70), (cx+70, cy+70)], fill=grid_col, width=1)
draw.line([(cx+70, cy-70), (cx-70, cy+70)], fill=grid_col, width=1)

# ── Tia quét (sweep) ──────────────────────────────────────────────────
angle = math.radians(40)
for fade, a_off, width in [(50, 15, 6), (90, 8, 4), (160, 3, 3), (220, 0, 2)]:
    a = angle - math.radians(a_off)
    ex = int(cx + 100 * math.cos(a))
    ey = int(cy - 100 * math.sin(a))
    draw.line([(cx, cy), (ex, ey)], fill=(0, 255, 120, fade), width=width)

# ── Mục tiêu (blip) ───────────────────────────────────────────────────
blips = [(cx+55, cy-30), (cx-40, cy+50), (cx+20, cy+65)]
for bx, by in blips:
    draw.ellipse([bx-5, by-5, bx+5, by+5], fill=(0, 255, 140, 255))
    draw.ellipse([bx-9, by-9, bx+9, by+9], outline=(0, 255, 140, 80), width=1)

# ── Tâm (tàu chủ) ─────────────────────────────────────────────────────
draw.ellipse([cx-5, cy-5, cx+5, cy+5], fill="#ffffff")
draw.ellipse([cx-10, cy-10, cx+10, cy+10], outline="#ffffff", width=2)

# ── Viền ngoài ────────────────────────────────────────────────────────
draw.ellipse([4, 4, SIZE-4, SIZE-4], outline="#2255aa", width=5)

# ── Xuất các kích thước ico ───────────────────────────────────────────
sizes = [256, 128, 64, 48, 32, 16]
imgs  = [img.resize((s, s), Image.LANCZOS) for s in sizes]

out = os.path.join(os.path.dirname(__file__), "icon.ico")
imgs[0].save(out, format="ICO", sizes=[(s, s) for s in sizes],
             append_images=imgs[1:])
print(f"Done: {out}")

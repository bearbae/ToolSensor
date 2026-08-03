"""Tạo icon cho Maritime Signal Simulator — anten phát + sóng vô tuyến hải sự."""

from PIL import Image, ImageDraw
import math, os

SIZE = 256
img  = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

cx, cy = SIZE // 2, SIZE // 2

# ── Nền tròn ────────────────────────────────────────────────────────────
draw.ellipse([4, 4, SIZE-4, SIZE-4], fill="#0a1628", outline="#1a3a5c", width=6)

# ── Sóng biển ở phần dưới ───────────────────────────────────────────────
wave_y = cy + 62
for i in range(5):
    x0 = 30 + i * 40
    x1 = x0 + 35
    draw.arc([x0, wave_y - 10, x1, wave_y + 10], 180, 0,
             fill=(0, 120, 200, 120), width=3)

# ── Thân tàu (thuyền nhỏ ở đáy) ────────────────────────────────────────
hull_pts = [
    (cx - 55, cy + 55),
    (cx + 55, cy + 55),
    (cx + 45, cy + 72),
    (cx - 45, cy + 72),
]
draw.polygon(hull_pts, fill="#1a3a5c")
draw.line(hull_pts + [hull_pts[0]], fill="#2255aa", width=2)

# ── Cột buồm (mast) ─────────────────────────────────────────────────────
mast_x = cx
draw.line([(mast_x, cy + 55), (mast_x, cy - 72)], fill="#ffa726", width=5)
# Ngang đỉnh cột
draw.line([(mast_x - 12, cy - 60), (mast_x + 12, cy - 60)], fill="#ffcc02", width=3)

# ── Sóng tín hiệu phát ra từ đỉnh cột (3 cặp đối xứng) ────────────────
tip_x, tip_y = mast_x, cy - 66
for r, alpha, width in [(28, 255, 4), (50, 180, 3), (74, 110, 2)]:
    # Trái
    draw.arc([tip_x - r, tip_y - r, tip_x + r, tip_y + r],
             200, 340, fill=(255, 180, 0, alpha), width=width)
    # Phải
    draw.arc([tip_x - r, tip_y - r, tip_x + r, tip_y + r],
             -20, 130, fill=(255, 180, 0, alpha), width=width)

# ── Chấm phát sóng ở đỉnh ───────────────────────────────────────────────
draw.ellipse([tip_x-6, tip_y-6, tip_x+6, tip_y+6], fill="#ffcc02")
draw.ellipse([tip_x-10, tip_y-10, tip_x+10, tip_y+10],
             outline=(255, 204, 2, 180), width=2)

# ── Viền ngoài ────────────────────────────────────────────────────────
draw.ellipse([4, 4, SIZE-4, SIZE-4], outline="#2255aa", width=5)

# ── Xuất ICO ──────────────────────────────────────────────────────────
sizes = [256, 128, 64, 48, 32, 16]
imgs  = [img.resize((s, s), Image.LANCZOS) for s in sizes]

out = os.path.join(os.path.dirname(__file__), "icon.ico")
imgs[0].save(out, format="ICO", sizes=[(s, s) for s in sizes],
             append_images=imgs[1:])
print(f"Done: {out}")

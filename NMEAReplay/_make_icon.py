"""Tạo icon cho NMEAReplay — nút play teal + sóng tín hiệu."""

from PIL import Image, ImageDraw
import math, os

SIZE = 256
img  = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

cx, cy = SIZE // 2, SIZE // 2

# ── Nền tròn xanh đậm ──────────────────────────────────────────────────
draw.ellipse([4, 4, SIZE-4, SIZE-4], fill="#0a1628", outline="#1a3a5c", width=6)

# ── Vòng tròn đồng tâm (sóng phát lại) ────────────────────────────────
for r, a in [(100, 40), (78, 65), (56, 90)]:
    draw.arc([cx-r, cy-r, cx+r, cy+r], -30, 210,
             fill=(0, 210, 180, a), width=2)

# ── Tam giác play ▶ ────────────────────────────────────────────────────
# Dịch sang trái 8px để trông cân hơn về mặt thị giác
ox = -8
pts = [
    (cx + ox - 52, cy - 60),   # trên-trái
    (cx + ox - 52, cy + 60),   # dưới-trái
    (cx + ox + 65, cy),         # phải-giữa
]
# Bóng đổ nhẹ
shadow_pts = [(x+4, y+4) for x, y in pts]
draw.polygon(shadow_pts, fill=(0, 80, 60, 100))
# Tam giác chính
draw.polygon(pts, fill="#00e5cc")
# Viền sáng
draw.line(pts + [pts[0]], fill="#80fff5", width=2)

# ── Mũi tên vòng tròn "replay" ở góc dưới-phải ──────────────────────
ar = 28
ax, ay = cx + 58, cy + 58
draw.arc([ax-ar, ay-ar, ax+ar, ay+ar], 30, 320,
         fill=(0, 230, 200, 200), width=5)
# Đầu mũi tên
angle = math.radians(320)
tip_x = int(ax + ar * math.cos(angle))
tip_y = int(ay + ar * math.sin(angle))
a1 = math.radians(320 - 140)
a2 = math.radians(320 + 30)
arrow_pts = [
    (tip_x, tip_y),
    (int(tip_x + 12*math.cos(a1)), int(tip_y + 12*math.sin(a1))),
    (int(tip_x + 12*math.cos(a2)), int(tip_y + 12*math.sin(a2))),
]
draw.polygon(arrow_pts, fill=(0, 230, 200, 220))

# ── Viền ngoài ────────────────────────────────────────────────────────
draw.ellipse([4, 4, SIZE-4, SIZE-4], outline="#0d4a6e", width=5)

# ── Xuất ICO ──────────────────────────────────────────────────────────
sizes = [256, 128, 64, 48, 32, 16]
imgs  = [img.resize((s, s), Image.LANCZOS) for s in sizes]

out = os.path.join(os.path.dirname(__file__), "icon.ico")
imgs[0].save(out, format="ICO", sizes=[(s, s) for s in sizes],
             append_images=imgs[1:])
print(f"Done: {out}")

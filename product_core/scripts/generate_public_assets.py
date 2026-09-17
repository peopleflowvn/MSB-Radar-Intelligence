# -*- coding: utf-8 -*-
"""Generate public assets using the exact icon configured in /settings (⚡ / MSB Theme):
- favicon.svg
- favicon-16x16.png, favicon-32x32.png
- apple-touch-icon.png (180x180)
- favicon.ico
- og-image.png (1200x630 Social Preview Card with ⚡ icon & MSB colors)
- site.webmanifest
"""
import os
import math
from PIL import Image, ImageDraw, ImageFont

PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "public")
os.makedirs(PUBLIC_DIR, exist_ok=True)

# 1. Generate favicon.svg using the ⚡ icon configured in /settings with MSB Gradient
svg_favicon = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
  <defs>
    <linearGradient id="msbGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#F59E0B" />
      <stop offset="50%" stop-color="#FF8A33" />
      <stop offset="100%" stop-color="#E65C00" />
    </linearGradient>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1E293B" />
      <stop offset="100%" stop-color="#0A0E1A" />
    </linearGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
  </defs>
  <!-- Background Squircle -->
  <rect x="4" y="4" width="120" height="120" rx="28" fill="url(#bgGrad)" stroke="#334155" stroke-width="2"/>
  <!-- Glowing radar ring -->
  <circle cx="64" cy="64" r="48" fill="none" stroke="#FF8A33" stroke-width="1.5" stroke-opacity="0.25" stroke-dasharray="4 3"/>
  <circle cx="64" cy="64" r="34" fill="none" stroke="#FF8A33" stroke-width="1.5" stroke-opacity="0.4"/>
  <!-- Central ⚡ icon -->
  <g filter="url(#glow)">
    <text x="50%" y="54%" text-anchor="middle" dominant-baseline="central" font-family="'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', sans-serif" font-size="70" fill="url(#msbGrad)">⚡</text>
  </g>
</svg>"""

with open(os.path.join(PUBLIC_DIR, "favicon.svg"), "w", encoding="utf-8") as f:
    f.write(svg_favicon)


def draw_lightning_bolt(draw, cx, cy, size):
    """Draw a crisp, stylized geometric lightning bolt ⚡ in MSB gradient."""
    # Unit coordinates normalized around center
    scale = size / 100.0
    # Stylized ⚡ polygon points relative to center
    pts = [
        (cx + 8 * scale, cy - 44 * scale),    # Top point
        (cx - 24 * scale, cy - 4 * scale),    # Left inner notch
        (cx - 4 * scale, cy - 4 * scale),     # Left mid
        (cx - 14 * scale, cy + 44 * scale),   # Bottom sharp point
        (cx + 22 * scale, cy + 4 * scale),    # Right inner notch
        (cx + 4 * scale, cy + 4 * scale),     # Right mid
    ]
    # Draw glow shadow
    shadow_pts = [(x + 2, y + 2) for (x, y) in pts]
    draw.polygon(shadow_pts, fill=(230, 92, 0, 120))
    # Draw gradient or vibrant fill
    draw.polygon(pts, fill=(255, 175, 45, 255), outline=(255, 255, 255, 200))


# 2. Generate PNG Icons (16, 32, 180, 512)
def create_app_icon(size):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    radius = int(size * 0.22)
    # Slate/Navy Background
    draw.rounded_rectangle([2, 2, size - 2, size - 2], radius=radius,
                           fill=(15, 23, 42, 255), outline=(51, 65, 85, 255), width=max(1, int(size * 0.025)))

    # Radar rings
    cx, cy = size // 2, size // 2
    r1 = int(size * 0.40)
    draw.ellipse([cx - r1, cy - r1, cx + r1, cy + r1], outline=(255, 138, 51, 70), width=max(1, int(size * 0.03)))
    r2 = int(size * 0.28)
    draw.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=(245, 158, 11, 110), width=max(1, int(size * 0.03)))

    # Draw the ⚡ icon in center
    draw_lightning_bolt(draw, cx, cy, int(size * 0.70))
    return im


icon_180 = create_app_icon(180)
icon_180.save(os.path.join(PUBLIC_DIR, "apple-touch-icon.png"), "PNG")

icon_32 = create_app_icon(32)
icon_32.save(os.path.join(PUBLIC_DIR, "favicon-32x32.png"), "PNG")

icon_16 = create_app_icon(16)
icon_16.save(os.path.join(PUBLIC_DIR, "favicon-16x16.png"), "PNG")

icon_180.save(os.path.join(PUBLIC_DIR, "favicon.ico"), format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])


# 3. Generate OG Image (1200 x 630) Social Preview Thumbnail
def create_og_thumbnail():
    W, H = 1200, 630
    im = Image.new("RGBA", (W, H), (8, 12, 22, 255))
    draw = ImageDraw.Draw(im)

    # Ambient subtle grid
    for x in range(0, W, 40):
        draw.line([x, 0, x, H], fill=(30, 41, 59, 35), width=1)
    for y in range(0, H, 40):
        draw.line([0, y, W, y], fill=(30, 41, 59, 35), width=1)

    # Ambient warm glow orbs in MSB Orange & Amber
    # Right side glow
    for r in range(400, 40, -20):
        alpha = int(34 * (1 - r / 400))
        draw.ellipse([930 - r, 315 - r, 930 + r, 315 + r], fill=(255, 138, 51, alpha))

    # Top-left small glow
    for r in range(250, 40, -20):
        alpha = int(18 * (1 - r / 250))
        draw.ellipse([200 - r, 120 - r, 200 + r, 120 + r], fill=(245, 158, 11, alpha))

    # Outer Glassmorphism Card Border
    draw.rounded_rectangle([24, 24, W - 24, H - 24], radius=24,
                           outline=(51, 65, 85, 180), width=2)

    # Right Side: Large Glowing MSB Badge with ⚡ Icon
    rcx, rcy = 930, 315
    # Concentric glowing radar rings
    for r, width, alpha in [(230, 2, 40), (180, 2, 70), (130, 2, 110), (80, 3, 160)]:
        draw.ellipse([rcx - r, rcy - r, rcx + r, rcy + r], outline=(255, 138, 51, alpha), width=width)

    # Center Badge Disk
    badge_radius = 110
    draw.ellipse([rcx - badge_radius, rcy - badge_radius, rcx + badge_radius, rcy + badge_radius],
                 fill=(15, 23, 42, 240), outline=(255, 138, 51, 220), width=3)

    # Big ⚡ Icon inside the right badge
    draw_lightning_bolt(draw, rcx, rcy, 180)

    # Left content block
    # 1. Badge: MSB RADAR HUB • ENTERPRISE AI
    badge_x, badge_y = 75, 80
    draw.rounded_rectangle([badge_x, badge_y, badge_x + 370, badge_y + 42], radius=21,
                           fill=(20, 28, 45, 230), outline=(255, 138, 51, 180), width=1)
    # Glowing dot
    draw.ellipse([badge_x + 18, badge_y + 16, badge_x + 28, badge_y + 26], fill=(255, 138, 51, 255))

    try:
        font_badge = ImageFont.truetype("arialbd.ttf", 14)
        font_title = ImageFont.truetype("arialbd.ttf", 46)
        font_subtitle = ImageFont.truetype("arial.ttf", 21)
        font_tags = ImageFont.truetype("arialbd.ttf", 16)
        font_footer = ImageFont.truetype("arial.ttf", 15)
    except Exception:
        font_badge = ImageFont.load_default()
        font_title = ImageFont.load_default()
        font_subtitle = ImageFont.load_default()
        font_tags = ImageFont.load_default()
        font_footer = ImageFont.load_default()

    draw.text((badge_x + 36, badge_y + 12), "MSB RADAR HUB  •  ENTERPRISE AI", fill=(255, 165, 70, 255), font=font_badge)

    # 2. Main Title (Two lines)
    title_line1 = "HỆ THỐNG TÌM KIẾM NHÂN TÀI"
    title_line2 = "& TĂNG TRƯỞNG KHÁCH HÀNG"
    draw.text((75, 155), title_line1, fill=(255, 255, 255, 255), font=font_title)
    draw.text((75, 215), title_line2, fill=(255, 138, 51, 255), font=font_title)

    # 3. Subtitle description
    desc_line1 = "Nền tảng Radar Hub tập trung dữ liệu ứng viên, khách hàng tiềm năng,"
    desc_line2 = "hỗ trợ AI Sourcing và điều phối săn nhân tài thông minh cho MSB."
    draw.text((75, 295), desc_line1, fill=(203, 213, 225, 240), font=font_subtitle)
    draw.text((75, 328), desc_line2, fill=(148, 163, 184, 240), font=font_subtitle)

    # 4. Feature Pills Grid
    pills = [
        ("⚡ Talent Radar", (245, 158, 11)),
        ("✨ AI Sourcing", (56, 189, 248)),
        ("🎯 Growth Radar", (52, 211, 153)),
        ("👤 Hồ sơ 360°", (168, 85, 247)),
        ("⚙️ Edge Ingestion", (251, 113, 133)),
    ]
    px, py = 75, 410
    for text, color in pills:
        pw = len(text) * 11 + 32
        draw.rounded_rectangle([px, py, px + pw, py + 38], radius=10,
                               fill=(15, 23, 42, 230), outline=(color[0], color[1], color[2], 140), width=1)
        draw.text((px + 14, py + 9), text, fill=(241, 245, 249, 255), font=font_tags)
        px += pw + 12

    # 5. Footer info line
    draw.line([75, 520, 680, 520], fill=(51, 65, 85, 180), width=1)
    draw.text((75, 545), "🔒 Chuẩn bảo mật Ngân hàng MSB   |   ⚡ Săn nhân tài & Khách hàng thông minh",
              fill=(148, 163, 184, 210), font=font_footer)

    im.save(os.path.join(PUBLIC_DIR, "og-image.png"), "PNG")


create_og_thumbnail()

print("Unified Settings Icon and MSB Branded Assets successfully generated in web/public!")

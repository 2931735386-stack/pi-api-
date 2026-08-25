# -*- coding: utf-8 -*-
"""以 "π" 为主题的渐变圆角图标生成器（打包及首次运行无图标时使用）。"""

from pathlib import Path


def generate_icon_ico(path: Path) -> bool:
    """生成以 "π" 字样为主题的渐变圆角图标 (.ico)。"""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:
        return False

    size = 256
    supersample = 2  # 2x 超采样抗锯齿，绘制在 512x512 再缩回 256
    SS = size * supersample

    # 1. 渐变圆角背景（深色系，呼应应用暗色主题）
    bg = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    top = (30, 30, 46, 255)        # #1e1e2e
    bottom = (49, 50, 68, 255)     # #313244
    for y in range(SS):
        t = y / SS
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        bd.line([(0, y), (SS, y)], fill=(r, g, b, 255))

    # 2. 顶部高光渐变条（青绿→靛蓝，作为“pi”主题的识别色带）
    hl = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hl)
    h_top = (45, 212, 191, 255)    # #2dd4bf 青绿 teal
    h_bottom = (99, 102, 241, 255) # #6366f1 靛蓝 indigo
    hl_h = 14 * supersample
    for y in range(0, hl_h):
        t = y / hl_h
        r = int(h_top[0] + (h_bottom[0] - h_top[0]) * t)
        g = int(h_top[1] + (h_bottom[1] - h_top[1]) * t)
        b = int(h_top[2] + (h_bottom[2] - h_top[2]) * t)
        hd.line([(0, y), (SS, y)], fill=(r, g, b, 255))

    # 3. 圆角遮罩应用到背景 + 高光
    radius = 56 * supersample
    mask = Image.new("L", (SS, SS), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, SS - 1, SS - 1], radius=radius, fill=255)

    final = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    final.paste(bg, (0, 0), mask)
    final.paste(hl, (0, 0), mask)

    d = ImageDraw.Draw(final)

    # 4. 中心 “π” 字符
    font_path = None
    for candidate in [
        "C:/Windows/Fonts/seguisb.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/simhei.ttf",
    ]:
        try:
            ImageFont.truetype(candidate, 100)
            font_path = candidate
            break
        except Exception:
            continue

    if font_path:
        glyph = "\u03c0"  # π
        target_h = 150 * supersample
        font = ImageFont.truetype(font_path, 200 * supersample)
        try:
            bbox = d.textbbox((0, 0), glyph, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if h > 0:
                scale = target_h / h
                font = ImageFont.truetype(font_path, int(200 * supersample * scale))
                bbox = d.textbbox((0, 0), glyph, font=font)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
        except Exception:
            w, h = 120 * supersample, 140 * supersample

        x = (SS - w) / 2 - bbox[0]
        y = (SS - h) / 2 - bbox[1]
        d.text((x, y), glyph, font=font, fill=(205, 214, 244, 255))  # #cdd6f4
    else:
        # 无字体时：手绘简化的 π
        cx, cy = SS // 2, SS // 2
        lw = 22 * supersample
        d.line([(cx - 60 * supersample, cy - 40 * supersample),
                (cx + 60 * supersample, cy - 40 * supersample)], fill=(205, 214, 244, 255), width=lw)
        d.line([(cx - 40 * supersample, cy - 40 * supersample),
                (cx - 40 * supersample, cy + 55 * supersample)], fill=(205, 214, 244, 255), width=lw)
        d.line([(cx + 40 * supersample, cy - 40 * supersample),
                (cx + 40 * supersample, cy + 55 * supersample)], fill=(205, 214, 244, 255), width=lw)

    # 5. 底部小圆点装饰（青绿/靛蓝两色）
    r = 10 * supersample
    d.ellipse([SS // 2 - 60 * supersample - r, SS - 30 * supersample - r,
               SS // 2 - 60 * supersample + r, SS - 30 * supersample + r],
              fill=(45, 212, 191, 255))
    d.ellipse([SS // 2 + 60 * supersample - r, SS - 30 * supersample - r,
               SS // 2 + 60 * supersample + r, SS - 30 * supersample + r],
              fill=(99, 102, 241, 255))

    # 缩回目标尺寸（超采样抗锯齿）
    final = final.resize((size, size), Image.LANCZOS)
    final = final.filter(ImageFilter.SMOOTH)
    final.save(path, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    return True

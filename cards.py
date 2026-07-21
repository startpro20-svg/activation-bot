from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path("/tmp/activation_cards")
OUT.mkdir(parents=True, exist_ok=True)

def font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except Exception:
        return ImageFont.load_default()

def points_card(name: str, delta: int, total: int, reason: str) -> str:
    image = Image.new("RGB", (1080, 1350), (17, 17, 20))
    draw = ImageDraw.Draw(image)

    draw.text((80, 100), "ACTIVATION", font=font(60), fill=(255, 255, 255))
    draw.text((80, 320), f"+{delta}", font=font(180), fill=(255, 255, 255))
    draw.text((80, 535), "БАЛЛОВ", font=font(70), fill=(255, 255, 255))
    draw.text((80, 780), name[:30], font=font(52), fill=(255, 255, 255))
    draw.text((80, 930), reason[:55], font=font(34), fill=(210, 210, 210))
    draw.text((80, 1160), f"ВСЕГО: {total}", font=font(46), fill=(255, 255, 255))

    path = OUT / f"points_{delta}_{total}.jpg"
    image.save(path, quality=93)
    return str(path)


def player_card(
    photo_path: str,
    name: str,
    occupation: str,
    point_a: str,
    goal_21: str,
) -> str:
    """Стартовая карта игрока в утверждённой визуальной системе ACTIVATION."""
    from PIL import ImageOps, ImageFilter

    W, H = 1080, 1350
    canvas = Image.new("RGB", (W, H), (238, 244, 245))

    # Мягкий холодный световой фон.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((650, -180, 1250, 420), fill=(65, 226, 230, 38))
    gd.ellipse((-250, 850, 450, 1550), fill=(70, 205, 218, 25))
    glow = glow.filter(ImageFilter.GaussianBlur(85))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), glow)

    draw = ImageDraw.Draw(canvas)

    # Верхний бренд-блок.
    draw.text((70, 62), "ACTIVATION", font=font(52), fill=(18, 28, 31, 255))
    draw.text((70, 126), "КАРТА ИГРОКА", font=font(25), fill=(62, 96, 100, 255))
    draw.rounded_rectangle((820, 62, 1010, 126), radius=28,
                           fill=(213, 250, 249, 230), outline=(86, 218, 218, 255), width=2)
    draw.text((860, 80), "21 ДЕНЬ", font=font(22), fill=(21, 101, 105, 255))

    # Стеклянная основная панель.
    panel = Image.new("RGBA", (940, 1080), (255, 255, 255, 155))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle((0, 0, 939, 1079), radius=42,
                         fill=(255, 255, 255, 165), outline=(255, 255, 255, 235), width=3)
    panel = panel.filter(ImageFilter.GaussianBlur(0.4))
    canvas.alpha_composite(panel, (70, 190))
    draw = ImageDraw.Draw(canvas)

    # Квадратное окно под фото — обязательная часть дизайн-системы.
    photo = Image.open(photo_path).convert("RGB")
    photo = ImageOps.fit(photo, (400, 400))
    photo_layer = Image.new("RGBA", (420, 420), (255, 255, 255, 0))
    photo_layer.paste(photo, (10, 10))
    mask = Image.new("L", (420, 420), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((10, 10, 410, 410), radius=30, fill=255)
    photo_layer.putalpha(mask)
    canvas.alpha_composite(photo_layer, (110, 245))
    draw.rounded_rectangle((120, 255, 520, 655), radius=30,
                           outline=(87, 218, 218, 220), width=3)

    # Имя и статус.
    draw.text((575, 270), name[:22].upper(), font=font(52), fill=(17, 29, 32, 255))
    draw.text((575, 345), occupation[:34], font=font(27), fill=(65, 89, 93, 255))

    draw.rounded_rectangle((575, 430, 925, 505), radius=24,
                           fill=(223, 251, 250, 205), outline=(109, 224, 222, 230), width=2)
    draw.text((605, 452), "УРОВЕНЬ 01  ·  ЛИЧНОСТЬ", font=font(23), fill=(25, 99, 103, 255))

    draw.text((575, 550), "0", font=font(64), fill=(18, 31, 34, 255))
    draw.text((655, 575), "БАЛЛОВ", font=font(23), fill=(69, 100, 103, 255))

    # Точка А.
    draw.text((120, 735), "ТОЧКА А", font=font(25), fill=(38, 119, 122, 255))
    draw.rounded_rectangle((110, 780, 970, 910), radius=28,
                           fill=(247, 252, 252, 205), outline=(206, 228, 229, 255), width=2)
    draw.text((145, 820), point_a[:78], font=font(28), fill=(29, 43, 46, 255))

    # Главная цель.
    draw.text((120, 960), "ГЛАВНАЯ ЦЕЛЬ НА 21 ДЕНЬ", font=font(25), fill=(38, 119, 122, 255))
    draw.rounded_rectangle((110, 1005, 970, 1155), radius=28,
                           fill=(247, 252, 252, 205), outline=(206, 228, 229, 255), width=2)
    draw.text((145, 1045), goal_21[:78], font=font(28), fill=(29, 43, 46, 255))

    # Нижняя линия системы.
    draw.line((110, 1205, 970, 1205), fill=(179, 220, 221, 220), width=2)
    draw.text((120, 1228), "ЛИЧНОСТЬ  →  ВИДИМОСТЬ  →  ВЛИЯНИЕ  →  МАСШТАБ",
              font=font(21), fill=(50, 99, 102, 255))

    out = canvas.convert("RGB")
    safe_name = "".join(ch for ch in name if ch.isalnum() or ch in "-_") or "player"
    path = OUT / f"player_card_{safe_name}.jpg"
    out.save(path, quality=95)
    return str(path)

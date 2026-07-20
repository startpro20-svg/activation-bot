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

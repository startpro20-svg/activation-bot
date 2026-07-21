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




def _wrap_text(draw, text, font_obj, max_width):
    words = (text or "").split()
    lines = []
    current = ""
    for word in words:
        # Break overly long single tokens too.
        if draw.textlength(word, font=font_obj) > max_width:
            if current:
                lines.append(current)
                current = ""
            chunk = ""
            for ch in word:
                test = chunk + ch
                if draw.textlength(test, font=font_obj) <= max_width:
                    chunk = test
                else:
                    if chunk:
                        lines.append(chunk)
                    chunk = ch
            if chunk:
                current = chunk
            continue

        test = word if not current else current + " " + word
        if draw.textlength(test, font=font_obj) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)
    return lines


def _fit_text(draw, text, font_factory, max_width, max_height,
              max_size=24, min_size=14, line_gap=8, max_lines=None):
    """
    Returns (font, lines, line_height) fitted to both width and height.
    """
    for size in range(max_size, min_size - 1, -1):
        font_obj = font_factory(size)
        lines = _wrap_text(draw, text, font_obj, max_width)
        if max_lines is not None:
            lines = lines[:max_lines]

        bbox = draw.textbbox((0, 0), "Ag", font=font_obj)
        line_height = (bbox[3] - bbox[1]) + line_gap
        total_height = line_height * len(lines)

        if total_height <= max_height:
            return font_obj, lines, line_height

    font_obj = font_factory(min_size)
    lines = _wrap_text(draw, text, font_obj, max_width)
    if max_lines is not None:
        lines = lines[:max_lines]
    bbox = draw.textbbox((0, 0), "Ag", font=font_obj)
    line_height = (bbox[3] - bbox[1]) + line_gap
    return font_obj, lines, line_height


def player_card(
    photo_path: str,
    name: str,
    occupation: str,
    point_a: str,
    goal_21: str,
    username: str = "",
    start_date: str = "",
) -> str:
    """
    Генерация карты игрока поверх утвержденного master-template ACTIVATION.
    Дизайн не рисуется с нуля: бот только заменяет данные на готовом шаблоне.
    """
    from PIL import ImageOps, ImageDraw, ImageFont
    from datetime import datetime

    template_path = Path(__file__).resolve().parent / "assets" / "player_card_template.png"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    canvas = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    # Шаблон 1248x1248. Координаты привязаны к согласованному макету.
    # Фото: квадрат слева сверху.
    photo = Image.open(photo_path).convert("RGB")
    photo = ImageOps.fit(photo, (430, 430))
    mask = Image.new("L", (430, 430), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, 430, 430), radius=34, fill=255)
    photo_rgba = photo.convert("RGBA")
    photo_rgba.putalpha(mask)
    canvas.alpha_composite(photo_rgba, (72, 132))

    # Фоновые плашки закрывают тестовые данные исходного макета,
    # сохраняя сам визуальный дизайн карточки.
    # Имя / ник / профессия
    draw.rounded_rectangle((548, 258, 1000, 438), radius=24, fill=(244, 248, 249, 245))
    # Уровень
    draw.rounded_rectangle((1008, 220, 1190, 452), radius=24, fill=(244, 248, 249, 238))
    # Прогресс и показатели
    draw.rounded_rectangle((545, 460, 1180, 690), radius=20, fill=(244, 248, 249, 240))
    # Точка А
    draw.rounded_rectangle((75, 690, 500, 1000), radius=26, fill=(244, 248, 249, 242))
    # Главная цель
    draw.rounded_rectangle((530, 730, 1185, 1005), radius=26, fill=(244, 248, 249, 242))
    # Нижняя подпись / дата
    draw.rounded_rectangle((70, 1030, 1180, 1188), radius=22, fill=(244, 248, 249, 236))

    # Fonts
    def f(size, bold=False):
        font_name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        font_path = Path(__file__).resolve().parent / "assets" / font_name
        if not font_path.exists():
            raise FileNotFoundError(f"Bundled font not found: {font_path}")
        return ImageFont.truetype(str(font_path), size)

    dark = (24, 34, 38, 255)
    muted = (71, 92, 97, 255)
    cyan = (33, 175, 190, 255)

    # Dynamic identity block
    draw.text((560, 280), name[:24].upper(), font=f(42, True), fill=dark)
    uname = username.strip()
    if uname and not uname.startswith("@"):
        uname = "@" + uname
    draw.text((560, 345), uname[:28] or "@PLAYER", font=f(25, False), fill=cyan)
    draw.text((560, 395), occupation[:42], font=f(22, False), fill=muted)

    # Level
    draw.text((1038, 250), "УРОВЕНЬ", font=f(18), fill=muted)
    draw.text((1070, 300), "1", font=f(56, True), fill=dark)
    draw.text((1028, 380), "ЛИЧНОСТЬ", font=f(18, True), fill=cyan)

    # Progress section
    draw.text((560, 485), "ТВОЙ ПРОГРЕСС", font=f(18, True), fill=muted)
    draw.text((1030, 485), "0 / 1000 XP", font=f(18), fill=cyan)
    draw.rounded_rectangle((560, 525, 1160, 538), radius=6, fill=(207, 221, 224, 255))
    draw.rounded_rectangle((560, 525, 585, 538), radius=6, fill=(56, 201, 210, 255))
    draw.text((620, 590), "0", font=f(38, True), fill=dark)
    draw.text((600, 640), "БАЛЛОВ", font=f(16), fill=muted)
    draw.text((820, 590), "0", font=f(38, True), fill=dark)
    draw.text((780, 640), "ДНЕЙ В ИГРЕ", font=f(16), fill=muted)
    draw.text((1055, 590), "—", font=f(38, True), fill=dark)
    draw.text((995, 640), "ТЕКУЩАЯ ЛИГА", font=f(16), fill=muted)

    # Point A — text always stays inside the glass block.
    draw.text((95, 710), "ТОЧКА А", font=f(24, True), fill=dark)
    point_font, point_lines, point_lh = _fit_text(
        draw,
        point_a,
        lambda s: f(s, False),
        max_width=355,
        max_height=205,
        max_size=21,
        min_size=13,
        line_gap=7,
        max_lines=9,
    )
    y = 760
    for idx, line in enumerate(point_lines):
        prefix = "• " if idx == 0 else "  "
        draw.text((105, y), prefix + line, font=point_font, fill=dark)
        y += point_lh

    # Goal — auto-wrap and auto-shrink to fit the target block.
    draw.text((555, 755), "ГЛАВНАЯ ЦЕЛЬ НА 21 ДЕНЬ", font=f(24, True), fill=dark)
    goal_font, goal_lines, goal_lh = _fit_text(
        draw,
        goal_21,
        lambda s: f(s, False),
        max_width=535,
        max_height=150,
        max_size=24,
        min_size=14,
        line_gap=8,
        max_lines=6,
    )
    y = 815
    for line in goal_lines:
        draw.text((585, y), line, font=goal_font, fill=dark)
        y += goal_lh

    # Footer
    draw.text((95, 1055), "ПОМНИ:", font=f(18), fill=muted)
    draw.text((95, 1090), "ТЫ НЕ ПРОХОДИШЬ ИГРУ.", font=f(23, True), fill=dark)
    draw.text((95, 1128), "ТЫ СОЗДАЁШЬ НОВУЮ РЕАЛЬНОСТЬ.", font=f(23, True), fill=cyan)

    if not start_date:
        start_date = datetime.now().strftime("%d.%m.%Y")
    draw.text((735, 1075), "ДАТА СТАРТА", font=f(18), fill=muted)
    draw.text((735, 1125), start_date, font=f(26, True), fill=cyan)

    safe_name = "".join(ch for ch in name if ch.isalnum() or ch in "-_") or "player"
    out_path = OUT / f"player_card_{safe_name}.jpg"
    canvas.convert("RGB").save(out_path, quality=96)
    return str(out_path)


def progress_card(
    level_number: int,
    level_name: str,
    points: int,
    target_points: int,
    day: int,
    streak: int,
    completed_tasks: int = 0,
) -> str:
    from PIL import ImageDraw, ImageFont

    template_path = Path(__file__).resolve().parent / "assets" / "progress_card_template.png"
    if not template_path.exists():
        raise FileNotFoundError(f"Progress template not found: {template_path}")

    canvas = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    def pf(size, bold=False):
        font_name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        font_path = Path(__file__).resolve().parent / "assets" / font_name
        return ImageFont.truetype(str(font_path), size)

    dark = (26, 34, 38, 255)
    cyan = (37, 177, 190, 255)
    muted = (77, 91, 96, 255)
    white = (246, 249, 250, 250)

    # Clean the active top level area while preserving the approved template.
    draw.rounded_rectangle((245, 55, 1065, 235), radius=26, fill=white)
    draw.ellipse((65, 55, 215, 205), fill=(246, 249, 250, 245))
    draw.rounded_rectangle((1020, 70, 1135, 190), radius=22, fill=(246, 249, 250, 245))

    draw.text((92, 88), f"{level_number:02d}", font=pf(56), fill=dark)
    draw.text((260, 70), "УРОВЕНЬ", font=pf(18, True), fill=cyan)
    draw.text((260, 102), level_name.upper(), font=pf(36, True), fill=dark)

    subtitles = {
        "ЛИЧНОСТЬ": "Ты создаёшь фундамент своей новой реальности",
        "ВИДИМОСТЬ": "Ты заявляешь о себе и притягиваешь внимание",
        "ВЛИЯНИЕ": "Тебя слышат. Твои действия начинают менять других",
        "МАСШТАБ": "Ты превращаешь внимание в возможности и рост",
    }
    draw.text(
        (260, 152),
        subtitles.get(level_name.upper(), "Ты продолжаешь двигаться дальше"),
        font=pf(18),
        fill=muted,
    )

    draw.text((820, 78), "ТВОЙ ПРОГРЕСС", font=pf(16, True), fill=muted)
    draw.text((820, 115), f"{points} / {target_points}", font=pf(34, True), fill=cyan)
    draw.text((820, 155), "БАЛЛОВ", font=pf(16), fill=muted)

    bar_x1, bar_y1, bar_x2, bar_y2 = 260, 192, 790, 210
    draw.rounded_rectangle((bar_x1, bar_y1, bar_x2, bar_y2), radius=8, fill=(207, 220, 223, 255))
    ratio = 0 if target_points <= 0 else max(0, min(1, points / target_points))
    fill_x = bar_x1 + int((bar_x2 - bar_x1) * ratio)
    if fill_x > bar_x1:
        draw.rounded_rectangle((bar_x1, bar_y1, fill_x, bar_y2), radius=8, fill=cyan)

    draw.text((270, 220), f"ДЕНЬ {day}/21", font=pf(15, True), fill=muted)
    draw.text((500, 220), f"СЕРИЯ {streak} ДН.", font=pf(15, True), fill=muted)
    draw.text((730, 220), f"ЗАДАНИЙ {completed_tasks}", font=pf(15, True), fill=muted)

    out_path = OUT / f"progress_{level_number}_{points}.jpg"
    canvas.convert("RGB").save(out_path, quality=96)
    return str(out_path)

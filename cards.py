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
    from PIL import ImageDraw, ImageFont
    from datetime import datetime

    template_path = Path(__file__).resolve().parent / "assets" / "player_card_template.png"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    canvas = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    # Шаблон 1248x1248. Координаты привязаны к согласованному макету.
    # Фото: квадрат слева сверху.
    photo = Image.open(photo_path).convert("RGB")
    # Фото уже проверено ботом как квадратное. Только уменьшаем/увеличиваем
    # до размера рамки — без crop, чтобы не обрезать лицо или голову.
    photo = photo.resize((430, 430), Image.Resampling.LANCZOS)
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

    # Dynamic identity block with hard visual boundaries.
    name_font, name_lines, name_lh = _fit_text(
        draw,
        (name or "").upper(),
        lambda s: f(s, True),
        max_width=405,
        max_height=58,
        max_size=42,
        min_size=20,
        line_gap=4,
        max_lines=1,
    )
    draw.text((560, 280), name_lines[0] if name_lines else "", font=name_font, fill=dark)

    uname = username.strip()
    if uname and not uname.startswith("@"):
        uname = "@" + uname
    username_font, username_lines, _ = _fit_text(
        draw,
        uname or "@PLAYER",
        lambda s: f(s, False),
        max_width=405,
        max_height=34,
        max_size=25,
        min_size=15,
        line_gap=2,
        max_lines=1,
    )
    draw.text((560, 345), username_lines[0] if username_lines else "", font=username_font, fill=cyan)

    occupation_font, occupation_lines, occupation_lh = _fit_text(
        draw,
        occupation or "",
        lambda s: f(s, False),
        max_width=405,
        max_height=48,
        max_size=22,
        min_size=13,
        line_gap=4,
        max_lines=2,
    )
    oy = 392
    for line in occupation_lines:
        draw.text((560, oy), line, font=occupation_font, fill=muted)
        oy += occupation_lh

    # Level
    draw.text((1038, 250), "УРОВЕНЬ", font=f(18), fill=muted)
    draw.text((1070, 300), "1", font=f(56, True), fill=dark)
    draw.text((1028, 380), "ЛИЧНОСТЬ", font=f(18, True), fill=cyan)

    # Progress section
    draw.text((560, 485), "ТВОЙ ПРОГРЕСС", font=f(18, True), fill=muted)
    draw.text((1080, 485), "0", font=f(22, True), fill=cyan)
    draw.text((1110, 489), "БАЛЛОВ", font=f(15), fill=cyan)
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
    """
    Progress card built on the approved ACTIVATION luxury-tech master visual.
    Decorative glass bubbles, icons and chrome details stay untouched.
    Only dynamic values are replaced.
    """
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

    dark = (25, 34, 38, 255)
    cyan = (35, 178, 190, 255)
    muted = (77, 91, 96, 255)
    pale = (238, 244, 246, 242)

    # Approved template coordinates for four main rows.
    rows = [
        {"y": 55,  "num": "01", "name": "ЛИЧНОСТЬ",  "threshold": 1000},
        {"y": 300, "num": "02", "name": "ВИДИМОСТЬ", "threshold": 2500},
        {"y": 545, "num": "03", "name": "ВЛИЯНИЕ",   "threshold": 4500},
        {"y": 790, "num": "04", "name": "МАСШТАБ",  "threshold": 7000},
    ]

    # Cover only demo progress values and demo bar fills.
    # Keep glass bubbles, rings, icons and decorative elements untouched.
    for idx, row in enumerate(rows, start=1):
        y = row["y"]

        # Right-side value area.
        draw.rounded_rectangle(
            (835, y + 55, 1005, y + 145),
            radius=18,
            fill=pale,
        )

        # Progress rail reset.
        draw.rounded_rectangle(
            (245, y + 132, 815, y + 154),
            radius=10,
            fill=(207, 221, 224, 255),
        )

        # Determine progress for each level.
        if idx < level_number:
            shown_points = row["threshold"]
            ratio = 1.0
        elif idx == level_number:
            shown_points = points
            ratio = 0 if row["threshold"] <= 0 else max(0, min(1, points / row["threshold"]))
        else:
            shown_points = 0
            ratio = 0.0

        # Fill bar.
        if ratio > 0:
            fill_x = 245 + int((815 - 245) * ratio)
            draw.rounded_rectangle(
                (245, y + 132, fill_x, y + 154),
                radius=10,
                fill=cyan,
            )

        # Dynamic label.
        if idx == level_number:
            draw.text((845, y + 60), "ТВОЙ ПРОГРЕСС", font=pf(15, True), fill=muted)
            value_text = f"{shown_points} / {row['threshold']}"
            value_font = pf(28, True)

            # Keep value safely inside the right block.
            while draw.textlength(value_text, font=value_font) > 145:
                size = value_font.size - 1
                if size < 16:
                    break
                value_font = pf(size, True)

            draw.text((845, y + 92), value_text, font=value_font, fill=cyan)
            draw.text((845, y + 126), "БАЛЛОВ", font=pf(14), fill=muted)
        else:
            draw.text((845, y + 60), "ПОРОГ", font=pf(15, True), fill=muted)
            draw.text((845, y + 92), str(row["threshold"]), font=pf(27, True), fill=dark)
            draw.text((845, y + 126), "БАЛЛОВ", font=pf(14), fill=muted)

    # Footer stats: cover demo footer values only.
    draw.rounded_rectangle((255, 1110, 945, 1180), radius=26, fill=(248, 251, 251, 244))
    draw.text((295, 1132), f"ДЕНЬ {day}/21", font=pf(16, True), fill=muted)
    draw.text((505, 1132), f"СЕРИЯ {streak} ДН.", font=pf(16, True), fill=muted)
    draw.text((735, 1132), f"ЗАДАНИЙ {completed_tasks}", font=pf(16, True), fill=muted)

    out_path = OUT / f"progress_{level_number}_{points}.jpg"
    canvas.convert("RGB").save(out_path, quality=96)
    return str(out_path)

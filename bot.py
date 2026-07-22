from pathlib import Path
import asyncio
import html
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, FSInputFile, ReplyKeyboardRemove

from config import load_config
from db import Database
from cards import points_card, player_card, public_player_card, progress_card
from keyboards import player_menu, admin_menu, confirm_task, confirm_broadcast, enter_game_keyboard, public_players_keyboard, submit_task_keyboard, task_review_keyboard, admin_player_actions, admin_confirm_delete_player, task_type_keyboard

logging.basicConfig(level=logging.INFO)

config = load_config()
db = Database(config.db_path)

bot = Bot(
    config.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


class CreateTask(StatesGroup):
    task_type = State()
    title = State()
    description = State()
    points = State()
    deadline = State()
    confirm = State()


class BroadcastMessage(StatesGroup):
    content = State()
    confirm = State()


class AddPlayerPoints(StatesGroup):
    amount = State()
    reason = State()


class TaskSubmission(StatesGroup):
    content = State()


class PlayerOnboarding(StatesGroup):
    name = State()
    occupation = State()
    point_a = State()
    goal_21 = State()
    photo = State()


def is_admin(user_id: int) -> bool:
    return user_id in config.admin_ids


def display_name(user) -> str:
    return user.full_name or user.username or str(user.id)


def public_level(points: int) -> tuple[int, str]:
    """Use the same currently configured level thresholds as the progress card."""
    if points < 1000:
        return 1, "ЛИЧНОСТЬ"
    if points < 2500:
        return 2, "ВИДИМОСТЬ"
    if points < 4500:
        return 3, "ВЛИЯНИЕ"
    return 4, "МАСШТАБ"


MOSCOW_TZ = ZoneInfo("Europe/Moscow")
TASK_TYPE_LABELS = {
    "main": "🎯 Основное задание",
    "media": "📱 Медиа-задание",
    "extra": "✨ Дополнительное задание",
}


def parse_deadline(value: str) -> datetime:
    """Parse a host-entered Moscow deadline and return an aware UTC datetime."""
    normalized = " ".join(value.replace(",", " ").split())
    formats = ("%d.%m.%Y %H:%M", "%d.%m %H:%M")
    parsed = None
    for date_format in formats:
        try:
            parsed = datetime.strptime(normalized, date_format)
            if date_format == "%d.%m %H:%M":
                parsed = parsed.replace(year=datetime.now(MOSCOW_TZ).year)
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError("invalid deadline")
    return parsed.replace(tzinfo=MOSCOW_TZ).astimezone(timezone.utc)


def deadline_to_db(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def format_deadline(value: str | None) -> str:
    if not value:
        return "без срока"
    deadline = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return deadline.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y в %H:%M МСК")


def deadline_expired(value: str | None) -> bool:
    if not value:
        return False
    deadline = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return deadline <= datetime.now(timezone.utc)


async def send_admin_players(message: Message):
    players = await db.all_players()
    if not players:
        await message.answer("Игроков пока нет.", reply_markup=admin_menu())
        return

    await message.answer("👥 <b>ИГРОКИ</b>", reply_markup=admin_menu())
    for player in players[:100]:
        name = player["first_name"] or player["username"] or str(player["tg_user_id"])
        username = f"@{player['username']}" if player["username"] else "не указан"
        await message.answer(
            f"<b>{name}</b>\n"
            f"Ник: {username}\n"
            f"Баллы: {player['points']}\n"
            f"День: {player['current_day']} / 21\n"
            f"ID: <code>{player['tg_user_id']}</code>",
            reply_markup=admin_player_actions(player["tg_user_id"]),
        )


async def send_latest_task_for_player(message: Message, tg_user_id: int):
    tasks = await db.active_tasks_for_player(tg_user_id)
    if not tasks:
        await message.answer(
            "📋 <b>ЗАДАНИЯ ДНЯ</b>\n\n"
            "Сейчас активных заданий нет. Новые задания появятся здесь, "
            "когда ведущая их опубликует.",
            reply_markup=player_menu(),
        )
        return

    status_labels = {
        "delivered": "Можно сдавать",
        "submitted": "На проверке у ведущей",
        "revision": "Нужна доработка",
        "accepted": "Принято",
    }
    await message.answer(
        "📋 <b>ЗАДАНИЯ ДНЯ</b>\n\n"
        f"Активных заданий: <b>{len(tasks)}</b>",
        reply_markup=player_menu(),
    )
    for task in tasks:
        status = task["status"]
        reply_markup = (
            submit_task_keyboard(task["task_id"])
            if status in {"delivered", "revision"}
            else None
        )
        await message.answer(
            f"{TASK_TYPE_LABELS.get(task['task_type'], TASK_TYPE_LABELS['extra'])}\n\n"
            f"<b>{html.escape(task['title'])}</b>\n\n"
            f"{html.escape(task['description'])}\n\n"
            f"Награда: <b>+{task['points']} баллов</b>\n"
            f"Дедлайн: <b>{format_deadline(task['deadline_at'])}</b>\n"
            f"Статус: <b>{status_labels.get(status, status)}</b>",
            reply_markup=reply_markup,
        )


async def ensure_player(message: Message):
    player = await db.upsert_player(message.from_user)
    if player["topic_id"]:
        return player

    topic = await bot.create_forum_topic(
        chat_id=config.admin_chat_id,
        name=display_name(message.from_user)[:120],
    )
    await db.set_topic(message.from_user.id, topic.message_thread_id)

    await bot.send_message(
        chat_id=config.admin_chat_id,
        message_thread_id=topic.message_thread_id,
        text=(
            "👤 <b>НОВЫЙ ИГРОК</b>\n\n"
            f"Имя: {display_name(message.from_user)}\n"
            f"ID: <code>{message.from_user.id}</code>\n"
            f"Username: @{message.from_user.username or '—'}\n\n"
            "Все сообщения из этой ветки бот отправляет игроку."
        ),
    )
    return await db.get_player(message.from_user.id)


@dp.message(CommandStart())
async def start(message: Message):
    if message.chat.type != "private":
        return

    # Администратор не регистрируется как игрок и видит только панель ведущей.
    if is_admin(message.from_user.id):
        await message.answer(
            "⚙️ <b>ACTIVATION — ПАНЕЛЬ ВЕДУЩЕЙ</b>\n\n"
            "Здесь ты управляешь заданиями, игроками и рейтингом.",
            reply_markup=admin_menu(),
        )
        return

    # Telegram user_id — постоянный ID игрока.
    # Повторный /start, удаление чата и повторный вход ничего не сбрасывают.
    existing_player = await db.get_player(message.from_user.id)
    if existing_player:
        if existing_player["profile_complete"]:
            await message.answer(
                "🔥 <b>ACTIVATION</b>\n\n"
                "Ты уже в игре. Продолжаем с того места, где ты остановилась.",
                reply_markup=player_menu(),
            )
            return

        # Профиль уже был начат, но не закончен. Не создаём нового игрока/ветку.
        await message.answer(
            "🔥 <b>ACTIVATION</b>\n\n"
            "Твой профиль уже создан. Давай закончим карту игрока.",
            reply_markup=enter_game_keyboard(),
        )
        return

    intro_text = (
        "🔥 <b>ACTIVATION</b>\n\n"
        "Ты входишь в игру.\n"
        "Каждое действие двигает тебя дальше.\n"
        "Задания, баллы, достижения и секретные миссии будут появляться здесь.\n\n"
        "21 день. Насколько далеко ты зайдёшь?\n\n"
        "За это время ты пройдёшь 4 уровня:\n"
        "<b>ЛИЧНОСТЬ → ВИДИМОСТЬ → ВЛИЯНИЕ → МАСШТАБ</b>\n\n"
        "За действия ты будешь получать баллы, открывать достижения "
        "и получать секретные миссии.\n\n"
        "<b>Готова войти в игру?</b>"
    )
    await message.answer(intro_text, reply_markup=enter_game_keyboard())


@dp.callback_query(F.data == "enter_game")
async def enter_game(callback: CallbackQuery, state: FSMContext):
    if is_admin(callback.from_user.id):
        await callback.answer()
        return

    # Старые кнопки «Войти в игру» могут оставаться в переписке.
    # Не позволяем завершённому игроку повторно запускать анкету.
    existing_player = await db.get_player(callback.from_user.id)
    if existing_player and existing_player["profile_complete"]:
        await state.clear()
        await callback.message.answer(
            "Твоя карта игрока уже создана. Ты уже в игре ✨",
            reply_markup=player_menu(),
        )
        await callback.answer("Анкета уже заполнена")
        return

    # Создаём черновую запись игрока, но личную ветку пока не создаём.
    await db.get_or_create_player(callback.from_user)

    await state.clear()
    await state.set_state(PlayerOnboarding.name)

    await callback.message.answer(
        "🎴 <b>СОЗДАЁМ ТВОЮ КАРТУ ИГРОКА</b>\n\n"
        "Для начала — как тебя зовут?\n"
        "Напиши имя, которое будет на твоей карточке."
    )
    await callback.answer()


@dp.message(PlayerOnboarding.name)
async def onboarding_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(PlayerOnboarding.occupation)
    await message.answer(
        "Чем ты занимаешься?\n\n"
        "Например: <i>эксперт по продвижению, фотограф, психолог, предприниматель</i>."
    )


@dp.message(PlayerOnboarding.occupation)
async def onboarding_occupation(message: Message, state: FSMContext):
    await state.update_data(occupation=message.text.strip())
    await state.set_state(PlayerOnboarding.point_a)
    await message.answer(
        "📍 <b>ТВОЯ ТОЧКА А</b>\n\n"
        "Опиши коротко, где ты сейчас в личном бренде.\n"
        "Например: <i>редко веду блог, 1200 подписчиков, почти нет заявок</i>."
    )


@dp.message(PlayerOnboarding.point_a)
async def onboarding_point_a(message: Message, state: FSMContext):
    await state.update_data(point_a=message.text.strip())
    await state.set_state(PlayerOnboarding.goal_21)
    await message.answer(
        "🎯 <b>ТВОЯ ЦЕЛЬ НА 21 ДЕНЬ</b>\n\n"
        "Что должно измениться за эти 21 день, чтобы ты сказала:\n"
        "<b>«Я реально активировалась»?</b>"
    )


@dp.message(PlayerOnboarding.goal_21)
async def onboarding_goal(message: Message, state: FSMContext):
    await state.update_data(goal_21=message.text.strip())
    await state.set_state(PlayerOnboarding.photo)
    await message.answer(
        "📸 <b>Добавь фотографию 1:1</b>\n\n"
        "Отправь квадратное фото. Оно станет частью твоей персональной карты игрока ACTIVATION."
    )


@dp.message(PlayerOnboarding.photo, F.photo)
async def onboarding_photo(message: Message, state: FSMContext):
    data = await state.get_data()

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)

    temp_dir = Path("/tmp/activation_onboarding")
    temp_dir.mkdir(parents=True, exist_ok=True)
    photo_path = temp_dir / f"{message.from_user.id}.jpg"

    await bot.download_file(file.file_path, destination=photo_path)

    # Принимаем только квадратное фото 1:1. Проверяем фактический файл после загрузки.
    from PIL import Image
    try:
        with Image.open(photo_path) as uploaded_photo:
            width, height = uploaded_photo.size
    except Exception:
        photo_path.unlink(missing_ok=True)
        await message.answer("Не удалось открыть фотографию. Отправь её ещё раз в формате JPG или PNG.")
        return

    if abs(width - height) > max(3, int(max(width, height) * 0.01)):
        photo_path.unlink(missing_ok=True)
        await message.answer(
            "❌ Фото не квадратное.\n\n"
            "Обрежь его до формата <b>1:1</b> и отправь снова. "
            "Лицо лучше расположить ближе к центру."
        )
        return

    # Сохраняем профиль.
    await db.save_player_profile(
        tg_user_id=message.from_user.id,
        first_name=data["name"],
        occupation=data["occupation"],
        point_a=data["point_a"],
        goal_21=data["goal_21"],
        photo_file_id=photo.file_id,
    )

    # Создаём личную ветку только после завершения карты игрока.
    player = await db.get_player(message.from_user.id)
    # Никогда не создаём вторую ветку для уже известного игрока.
    if not player["topic_id"]:
        topic = await bot.create_forum_topic(
            chat_id=config.admin_chat_id,
            name=data["name"][:120],
        )
        await db.set_topic(message.from_user.id, topic.message_thread_id)

        await bot.send_message(
            chat_id=config.admin_chat_id,
            message_thread_id=topic.message_thread_id,
            text=(
                "👤 <b>НОВЫЙ ИГРОК</b>\n\n"
                f"Имя: {data['name']}\n"
                f"Чем занимается: {data['occupation']}\n\n"
                f"📍 <b>Точка А:</b> {data['point_a']}\n\n"
                f"🎯 <b>Цель на 21 день:</b> {data['goal_21']}\n\n"
                f"ID: <code>{message.from_user.id}</code>\n"
                f"Username: @{message.from_user.username or '—'}"
            ),
        )

    card_path = player_card(
        str(photo_path),
        data["name"],
        data["occupation"],
        data["point_a"],
        data["goal_21"],
        username="",
    )

    await message.answer_photo(
        FSInputFile(card_path),
        caption=(
            "🎴 <b>ТВОЯ КАРТА ИГРОКА ГОТОВА</b>\n\n"
            "Уровень 01 — <b>ЛИЧНОСТЬ</b>\n"
            "Баллы: <b>0</b>\n\n"
            "🔥 <b>ТЫ В ИГРЕ</b>"
        ),
        reply_markup=player_menu(),
    )

    # Дублируем карточку в персональную ветку ведущей.
    player = await db.get_player(message.from_user.id)
    await bot.send_photo(
        chat_id=config.admin_chat_id,
        message_thread_id=player["topic_id"],
        photo=FSInputFile(card_path),
        caption="🎴 Стартовая карта игрока",
    )

    await state.clear()


@dp.message(PlayerOnboarding.photo)
async def onboarding_photo_invalid(message: Message):
    await message.answer("Пришли, пожалуйста, фотографию как фото 📸")


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if message.chat.type == "private" and is_admin(message.from_user.id):
        await message.answer("⚙️ <b>Панель ведущей</b>", reply_markup=admin_menu())


@dp.callback_query(F.data == "progress")
async def progress(callback: CallbackQuery):
    player = await db.get_player(callback.from_user.id)
    if not player:
        await callback.answer("Сначала нажми /start", show_alert=True)
        return

    points = player["points"]
    current_day = player["current_day"]
    streak = player["streak"]

    if points < 1000:
        level_number = 1
        level_name = "ЛИЧНОСТЬ"
        target_points = 1000
    elif points < 2500:
        level_number = 2
        level_name = "ВИДИМОСТЬ"
        target_points = 2500
    elif points < 4500:
        level_number = 3
        level_name = "ВЛИЯНИЕ"
        target_points = 4500
    else:
        level_number = 4
        level_name = "МАСШТАБ"
        target_points = 7000

    card_path = progress_card(
        level_number=level_number,
        level_name=level_name,
        points=points,
        target_points=target_points,
        day=current_day,
        streak=streak,
        completed_tasks=0,
    )

    await callback.message.answer_photo(
        FSInputFile(card_path),
        caption=(
            "🎮 <b>ТВОЙ ПРОГРЕСС</b>\n\n"
            f"День: <b>{current_day} / 21</b>\n"
            f"Баллы: <b>{points}</b>\n"
            f"🔥 Серия: <b>{streak} дней</b>\n"
            f"Уровень: <b>{level_number:02d} — {level_name}</b>"
        ),
    )
    await callback.answer()


@dp.callback_query(F.data.in_({"leaderboard", "admin_leaderboard"}))
async def leaderboard(callback: CallbackQuery):
    rows = await db.leaderboard()
    lines = ["🏆 <b>РЕЙТИНГ ACTIVATION</b>\n"]
    for i, row in enumerate(rows, 1):
        name = row["first_name"] or row["username"] or "Игрок"
        lines.append(f"{i}. {name} — <b>{row['points']}</b>")
    if len(lines) == 1:
        lines.append("Пока нет игроков.")
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=admin_menu() if is_admin(callback.from_user.id) else None,
    )
    await callback.answer()


@dp.callback_query(F.data == "achievements")
async def achievements(callback: CallbackQuery):
    await callback.message.answer(
        "🏅 <b>ТВОИ ДОСТИЖЕНИЯ</b>\n\n"
        "Некоторые награды скрыты и откроются неожиданно 👀"
    )
    await callback.answer()


@dp.callback_query(F.data == "players")
async def players(callback: CallbackQuery):
    viewer = await db.get_player(callback.from_user.id)
    if not viewer or not viewer["profile_complete"]:
        await callback.answer("Сначала создай карту игрока", show_alert=True)
        return

    rows = await db.public_players(exclude_tg_user_id=callback.from_user.id)
    if not rows:
        await callback.message.answer(
            "👥 <b>ИГРОКИ ACTIVATION</b>\n\n"
            "Другие участники появятся здесь после регистрации."
        )
        await callback.answer()
        return

    await callback.message.answer(
        "👥 <b>ИГРОКИ ACTIVATION</b>\n\n"
        "Выбери участника, чтобы посмотреть его публичную карточку.",
        reply_markup=public_players_keyboard(rows),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("public_player:"))
async def show_public_player(callback: CallbackQuery):
    viewer = await db.get_player(callback.from_user.id)
    if not viewer or not viewer["profile_complete"]:
        await callback.answer("Сначала создай карту игрока", show_alert=True)
        return

    try:
        player_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Карточка недоступна", show_alert=True)
        return

    public_player = await db.get_public_player(player_id)
    if not public_player or not public_player["photo_file_id"]:
        await callback.answer("Карточка игрока недоступна", show_alert=True)
        return

    photo_dir = Path("/tmp/activation_public_players")
    photo_dir.mkdir(parents=True, exist_ok=True)
    photo_path = photo_dir / f"{player_id}.jpg"

    try:
        telegram_file = await bot.get_file(public_player["photo_file_id"])
        await bot.download_file(telegram_file.file_path, destination=photo_path)

        level_number, level_name = public_level(public_player["points"])
        card_path = public_player_card(
            photo_path=str(photo_path),
            name=public_player["first_name"] or "Игрок",
            occupation=public_player["occupation"] or "Участник ACTIVATION 21",
            level_number=level_number,
            level_name=level_name,
            points=public_player["points"],
            day=public_player["current_day"],
            achievement_name=level_name,
            output_id=player_id,
        )
    except Exception:
        logging.exception("Public player card generation failed")
        await callback.answer("Не удалось открыть карточку. Попробуй ещё раз.", show_alert=True)
        return

    await callback.message.answer_photo(
        FSInputFile(card_path),
        caption=(
            "🎴 <b>ПУБЛИЧНАЯ КАРТА ИГРОКА</b>\n\n"
            f"Уровень: <b>{level_number:02d} — {level_name}</b>\n"
            f"Баллы: <b>{public_player['points']}</b>\n"
            f"Дней в игре: <b>{public_player['current_day']}</b>\n"
            f"Ачивка: <b>{level_name}</b>"
        ),
    )
    await callback.answer()


@dp.callback_query(F.data == "latest_task")
async def latest_task(callback: CallbackQuery):
    await send_latest_task_for_player(callback.message, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data.startswith("submit_task:"))
async def submit_task(callback: CallbackQuery, state: FSMContext):
    if is_admin(callback.from_user.id):
        return
    try:
        task_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Задание недоступно", show_alert=True)
        return

    delivery = await db.get_task_delivery(task_id, callback.from_user.id)
    if not delivery:
        await callback.answer("Задание не найдено", show_alert=True)
        return
    if delivery["status"] == "accepted":
        await callback.answer("Это задание уже принято", show_alert=True)
        return
    if delivery["status"] == "submitted":
        await callback.answer("Задание уже на проверке", show_alert=True)
        return
    if deadline_expired(delivery["deadline_at"]):
        await callback.answer("Срок сдачи этого задания истёк", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        delivery_id=delivery["delivery_id"],
        task_id=delivery["task_id"],
        task_title=delivery["title"],
        task_points=delivery["points"],
        previous_status=delivery["status"],
    )
    await state.set_state(TaskSubmission.content)
    await callback.message.answer(
        "📤 <b>СДАЧА ЗАДАНИЯ</b>\n\n"
        f"Задание: <b>{html.escape(delivery['title'])}</b>\n\n"
        "Отправь результат одним сообщением. Это может быть текст, "
        "фотография, видео или файл.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await callback.answer()


@dp.message(TaskSubmission.content)
async def task_submission_content(message: Message, state: FSMContext):
    if is_admin(message.from_user.id):
        return
    data = await state.get_data()
    delivery_id = data.get("delivery_id")
    if not delivery_id:
        await state.clear()
        await message.answer("Не удалось определить задание. Открой его заново.", reply_markup=player_menu())
        return

    player = await db.get_player(message.from_user.id)
    if not player:
        await state.clear()
        await message.answer("Сначала нажми /start")
        return
    if not player["topic_id"]:
        player = await ensure_player(message)

    # Reserve the submission before forwarding. The database checks the deadline
    # again, so a player cannot submit after it expires while this form is open.
    marked = await db.mark_task_submitted(
        delivery_id=delivery_id,
        tg_user_id=message.from_user.id,
        submission_chat_id=message.chat.id,
        submission_message_id=message.message_id,
    )
    if not marked:
        current = await db.get_task_delivery(data.get("task_id"), message.from_user.id)
        await state.clear()
        if current and deadline_expired(current["deadline_at"]):
            text = "⏰ Срок сдачи этого задания истёк. Работа не отправлена."
        else:
            text = "Эта работа уже была отправлена или принята."
        await message.answer(text, reply_markup=player_menu())
        return

    try:
        await bot.send_message(
            chat_id=config.admin_chat_id,
            message_thread_id=player["topic_id"],
            text=(
                "📥 <b>ЗАДАНИЕ НА ПРОВЕРКУ</b>\n\n"
                f"Игрок: <b>{html.escape(player['first_name'] or 'Игрок')}</b>\n"
                f"Задание: <b>{html.escape(data.get('task_title') or 'Задание')}</b>\n"
                f"Награда: <b>+{data.get('task_points', 0)} баллов</b>"
            ),
        )
        await bot.copy_message(
            chat_id=config.admin_chat_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=player["topic_id"],
        )
        await bot.send_message(
            chat_id=config.admin_chat_id,
            message_thread_id=player["topic_id"],
            text="Выбери результат проверки:",
            reply_markup=task_review_keyboard(delivery_id, data.get("task_points", 0)),
        )
    except Exception:
        logging.exception("Task submission forwarding failed")
        await db.restore_task_submission(
            delivery_id=delivery_id,
            tg_user_id=message.from_user.id,
            previous_status=data.get("previous_status", "delivered"),
            submission_chat_id=message.chat.id,
            submission_message_id=message.message_id,
        )
        await state.clear()
        await message.answer(
            "Не удалось отправить работу ведущей. Открой задание и попробуй ещё раз.",
            reply_markup=player_menu(),
        )
        return
    await state.clear()
    await message.answer(
        "✅ Работа отправлена ведущей на проверку.",
        reply_markup=player_menu(),
    )


@dp.callback_query(F.data == "admin_create_task")
async def admin_create_task(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(CreateTask.task_type)
    await callback.message.answer(
        "Выбери <b>тип задания</b>:",
        reply_markup=task_type_keyboard(),
    )
    await callback.answer()


@dp.message(
    F.chat.type == "private",
    F.from_user.id.in_(config.admin_ids),
    F.text == "➕ Создать задание",
)
async def admin_create_task_button(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(CreateTask.task_type)
    await message.answer("Выбери <b>тип задания</b>:", reply_markup=task_type_keyboard())


@dp.message(
    F.chat.type == "private",
    F.from_user.id.in_(config.admin_ids),
    F.text == "👥 Игроки",
)
async def admin_players_button(message: Message, state: FSMContext):
    await state.clear()
    await send_admin_players(message)


@dp.message(
    F.chat.type == "private",
    F.from_user.id.in_(config.admin_ids),
    F.text == "📣 Отправить сообщение всем",
)
async def admin_broadcast_button(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BroadcastMessage.content)
    await message.answer(
        "📣 <b>СООБЩЕНИЕ ВСЕМ ИГРОКАМ</b>\n\n"
        "Отправь сообщение, которое получат все игроки. "
        "Можно отправить текст, фотографию, видео или файл.",
        reply_markup=admin_menu(),
    )


@dp.message(
    F.chat.type == "private",
    F.from_user.id.in_(config.admin_ids),
    F.text == "🏆 Рейтинг",
)
async def admin_leaderboard_button(message: Message, state: FSMContext):
    await state.clear()
    rows = await db.leaderboard()
    lines = ["🏆 <b>РЕЙТИНГ ACTIVATION</b>\n"]
    for index, row in enumerate(rows, 1):
        name = row["first_name"] or row["username"] or "Игрок"
        lines.append(f"{index}. {name} — <b>{row['points']}</b>")
    if len(lines) == 1:
        lines.append("Пока нет игроков.")
    await message.answer("\n".join(lines), reply_markup=admin_menu())


@dp.message(
    F.chat.type == "private",
    F.text.in_({"📋 Задания дня", "🎯 Актуальное задание"}),
)
async def latest_task_button(message: Message):
    if is_admin(message.from_user.id):
        return
    player = await db.get_player(message.from_user.id)
    if not player:
        await message.answer("Сначала нажми /start")
        return
    await send_latest_task_for_player(message, message.from_user.id)


@dp.message(F.chat.type == "private", F.text == "🎮 Мой прогресс")
async def progress_button(message: Message):
    if is_admin(message.from_user.id):
        return
    player = await db.get_player(message.from_user.id)
    if not player:
        await message.answer("Сначала нажми /start")
        return

    points = player["points"]
    current_day = player["current_day"]
    streak = player["streak"]
    level_number, level_name = public_level(points)
    target_points = {1: 1000, 2: 2500, 3: 4500, 4: 7000}[level_number]

    card_path = progress_card(
        level_number=level_number,
        level_name=level_name,
        points=points,
        target_points=target_points,
        day=current_day,
        streak=streak,
        completed_tasks=0,
    )
    await message.answer_photo(
        FSInputFile(card_path),
        caption=(
            "🎮 <b>ТВОЙ ПРОГРЕСС</b>\n\n"
            f"День: <b>{current_day} / 21</b>\n"
            f"Баллы: <b>{points}</b>\n"
            f"🔥 Серия: <b>{streak} дней</b>\n"
            f"Уровень: <b>{level_number:02d} — {level_name}</b>"
        ),
        reply_markup=player_menu(),
    )


@dp.message(F.chat.type == "private", F.text == "🏆 Рейтинг")
async def leaderboard_button(message: Message):
    if is_admin(message.from_user.id):
        return
    player = await db.get_player(message.from_user.id)
    if not player:
        await message.answer("Сначала нажми /start")
        return

    rows = await db.leaderboard()
    lines = ["🏆 <b>РЕЙТИНГ ACTIVATION</b>\n"]
    for index, row in enumerate(rows, 1):
        name = row["first_name"] or row["username"] or "Игрок"
        lines.append(f"{index}. {name} — <b>{row['points']}</b>")
    if len(lines) == 1:
        lines.append("Пока нет игроков.")
    await message.answer("\n".join(lines), reply_markup=player_menu())


@dp.message(F.chat.type == "private", F.text == "🏅 Достижения")
async def achievements_button(message: Message):
    if is_admin(message.from_user.id):
        return
    player = await db.get_player(message.from_user.id)
    if not player:
        await message.answer("Сначала нажми /start")
        return
    await message.answer(
        "🏅 <b>ТВОИ ДОСТИЖЕНИЯ</b>\n\n"
        "Некоторые награды скрыты и откроются неожиданно 👀",
        reply_markup=player_menu(),
    )


@dp.message(F.chat.type == "private", F.text == "👥 Игроки")
async def players_button(message: Message):
    if is_admin(message.from_user.id):
        return
    player = await db.get_player(message.from_user.id)
    if not player:
        await message.answer("Сначала нажми /start")
        return

    rows = await db.public_players(exclude_tg_user_id=message.from_user.id)
    if not rows:
        await message.answer(
            "👥 <b>ИГРОКИ ACTIVATION</b>\n\n"
            "Другие участники появятся здесь после регистрации.",
            reply_markup=player_menu(),
        )
        return

    await message.answer(
        "👥 <b>ИГРОКИ ACTIVATION</b>\n\n"
        "Выбери участника, чтобы посмотреть его публичную карточку.",
        reply_markup=public_players_keyboard(rows),
    )


@dp.message(BroadcastMessage.content)
async def admin_broadcast_content(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.update_data(
        broadcast_chat_id=message.chat.id,
        broadcast_message_id=message.message_id,
    )
    await state.set_state(BroadcastMessage.confirm)
    await message.answer(
        "Проверь сообщение выше. Отправить его всем игрокам?",
        reply_markup=confirm_broadcast(),
    )


@dp.callback_query(F.data == "admin_send_broadcast")
async def admin_send_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    data = await state.get_data()
    source_chat_id = data.get("broadcast_chat_id")
    source_message_id = data.get("broadcast_message_id")
    if not source_chat_id or not source_message_id:
        await callback.answer("Сообщение потеряно. Создай рассылку заново.", show_alert=True)
        return

    # Clear first so a repeated click cannot launch the same broadcast twice.
    await state.clear()
    await callback.answer("Рассылка началась")

    players = await db.all_players()
    sent = 0
    failed = 0

    for player in players:
        try:
            await bot.copy_message(
                chat_id=player["tg_user_id"],
                from_chat_id=source_chat_id,
                message_id=source_message_id,
            )
            sent += 1
        except Exception:
            failed += 1
            logging.exception("Broadcast delivery failed")

    await callback.message.answer(
        "📣 Рассылка завершена.\n\n"
        f"Получили: <b>{sent}</b>\n"
        f"Ошибок: <b>{failed}</b>",
        reply_markup=admin_menu(),
    )


@dp.callback_query(F.data == "admin_cancel_broadcast")
async def admin_cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.answer("Рассылка отменена.", reply_markup=admin_menu())
    await callback.answer("Отменено")


@dp.callback_query(F.data.startswith("create_task_type:"))
async def create_task_type(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    task_type = callback.data.split(":", 1)[1]
    if task_type not in TASK_TYPE_LABELS:
        await callback.answer("Неизвестный тип задания", show_alert=True)
        return

    await state.update_data(task_type=task_type)
    await state.set_state(CreateTask.title)
    await callback.message.answer(
        f"{TASK_TYPE_LABELS[task_type]}\n\n"
        "✍️ Введи <b>название задания</b>:",
        reply_markup=admin_menu(),
    )
    await callback.answer()


@dp.message(CreateTask.title)
async def create_task_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(CreateTask.description)
    await message.answer("Теперь отправь <b>текст задания</b>:")


@dp.message(CreateTask.description)
async def create_task_description(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(description=message.text.strip())
    await state.set_state(CreateTask.points)
    await message.answer("Сколько баллов получает игрок? Отправь число, например <b>100</b>.")


@dp.message(CreateTask.points)
async def create_task_points(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        points = int(message.text.strip())
        if points <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Отправь положительное число, например <b>100</b>.")
        return

    await state.update_data(points=points)
    await state.set_state(CreateTask.deadline)
    await message.answer(
        "⏰ Введи <b>дедлайн по Москве</b>.\n\n"
        "Формат: <code>23.07.2026 18:00</code>\n"
        "Можно без года: <code>23.07 18:00</code>."
    )


@dp.message(CreateTask.deadline)
async def create_task_deadline(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        deadline = parse_deadline((message.text or "").strip())
    except ValueError:
        await message.answer(
            "Не удалось прочитать дату. Отправь её так: "
            "<code>23.07.2026 18:00</code> (время московское)."
        )
        return

    if deadline <= datetime.now(timezone.utc):
        await message.answer("Дедлайн уже прошёл. Укажи будущие дату и время.")
        return

    deadline_at = deadline_to_db(deadline)
    await state.update_data(deadline_at=deadline_at)
    data = await state.get_data()
    await state.set_state(CreateTask.confirm)

    await message.answer(
        f"{TASK_TYPE_LABELS[data['task_type']]}\n\n"
        f"<b>{html.escape(data['title'])}</b>\n\n"
        f"{html.escape(data['description'])}\n\n"
        f"Награда: <b>+{data['points']} баллов</b>\n"
        f"Дедлайн: <b>{format_deadline(deadline_at)}</b>",
        reply_markup=confirm_task(),
    )


@dp.callback_query(F.data == "admin_cancel_task")
async def admin_cancel_task(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.answer("Создание задания отменено.", reply_markup=admin_menu())
    await callback.answer()


@dp.callback_query(F.data == "admin_send_task")
async def admin_send_task(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    data = await state.get_data()
    if not all(
        k in data
        for k in ("task_type", "title", "description", "points", "deadline_at")
    ):
        await callback.answer("Данные задания потеряны. Создай заново.", show_alert=True)
        return

    if deadline_expired(data["deadline_at"]):
        await callback.answer(
            "Дедлайн уже прошёл. Создай задание заново с новым сроком.",
            show_alert=True,
        )
        return

    task_id = await db.create_task(
        data["title"],
        data["description"],
        data["points"],
        callback.from_user.id,
        task_type=data["task_type"],
        deadline_at=data["deadline_at"],
    )
    players = await db.all_players()

    sent = 0
    failed = 0
    text = (
        f"{TASK_TYPE_LABELS[data['task_type']]}\n\n"
        f"<b>{html.escape(data['title'])}</b>\n\n"
        f"{html.escape(data['description'])}\n\n"
        f"Награда: <b>+{data['points']} баллов</b>\n\n"
        f"Дедлайн: <b>{format_deadline(data['deadline_at'])}</b>\n\n"
        "Выполни задание и нажми «📤 Сдать задание»."
    )

    for player in players:
        try:
            await bot.send_message(
                player["tg_user_id"],
                text,
                reply_markup=submit_task_keyboard(task_id),
            )
            await db.mark_task_delivered(task_id, player["tg_user_id"])
            sent += 1
        except Exception:
            failed += 1
            logging.exception("Task delivery failed")

    await state.clear()
    await callback.message.answer(
        f"🚀 Задание отправлено.\n\nПолучили: <b>{sent}</b>\nОшибок: <b>{failed}</b>",
        reply_markup=admin_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_players")
async def admin_players(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await send_admin_players(callback.message)
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_add_points:"))
async def admin_add_points(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    try:
        user_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Игрок не найден", show_alert=True)
        return

    player = await db.get_player(user_id)
    if not player:
        await callback.answer("Игрок не найден", show_alert=True)
        return

    await state.clear()
    await state.update_data(points_user_id=user_id)
    await state.set_state(AddPlayerPoints.amount)
    name = player["first_name"] or player["username"] or str(user_id)
    await callback.message.answer(
        f"➕ <b>ДОБАВЛЕНИЕ БАЛЛОВ</b>\n\n"
        f"Игрок: <b>{html.escape(name)}</b>\n"
        "Сколько баллов добавить? Отправь положительное число.",
        reply_markup=admin_menu(),
    )
    await callback.answer()


@dp.message(AddPlayerPoints.amount)
async def admin_add_points_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amount = int((message.text or "").strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Отправь положительное число, например <b>100</b>.")
        return

    await state.update_data(points_amount=amount)
    await state.set_state(AddPlayerPoints.reason)
    await message.answer("Напиши причину начисления баллов:")


@dp.message(AddPlayerPoints.reason)
async def admin_add_points_reason(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    reason = (message.text or "").strip()
    if not reason:
        await message.answer("Напиши причину начисления текстом.")
        return

    data = await state.get_data()
    user_id = data.get("points_user_id")
    amount = data.get("points_amount")
    player = await db.get_player(user_id) if user_id else None
    if not player or not amount:
        await state.clear()
        await message.answer("Данные потеряны. Открой игрока и попробуй ещё раз.", reply_markup=admin_menu())
        return

    total = await db.add_points(user_id, amount, reason)
    await state.clear()
    name = player["first_name"] or player["username"] or str(user_id)
    await message.answer(
        "✅ <b>БАЛЛЫ НАЧИСЛЕНЫ</b>\n\n"
        f"Игрок: <b>{html.escape(name)}</b>\n"
        f"Начислено: <b>+{amount}</b>\n"
        f"Всего баллов: <b>{total}</b>\n"
        f"Причина: {html.escape(reason)}",
        reply_markup=admin_menu(),
    )

    try:
        await bot.send_message(
            chat_id=user_id,
            text=(
                "✨ <b>ТЕБЕ НАЧИСЛЕНЫ БАЛЛЫ</b>\n\n"
                f"+<b>{amount}</b> баллов\n"
                f"Причина: {html.escape(reason)}\n\n"
                f"Всего: <b>{total}</b> баллов"
            ),
            reply_markup=player_menu(),
        )
    except Exception:
        logging.exception("Player points notification failed")
        await message.answer("Баллы сохранены, но уведомление игроку не доставлено.")


@dp.callback_query(F.data.startswith("accept_task:"))
async def accept_task(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    try:
        delivery_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Работа не найдена", show_alert=True)
        return

    result = await db.accept_task_submission(delivery_id)
    if not result:
        await callback.answer("Работа не найдена", show_alert=True)
        return
    if "points" not in result:
        labels = {
            "accepted": "Эта работа уже принята",
            "revision": "Работа отправлена на доработку",
            "delivered": "Игрок ещё не сдал работу",
        }
        await callback.answer(labels.get(result["status"], "Работа уже обработана"), show_alert=True)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        logging.exception("Could not remove task review keyboard")

    await callback.message.answer(
        "✅ <b>ЗАДАНИЕ ПРИНЯТО</b>\n\n"
        f"Игрок: <b>{html.escape(result['first_name'] or 'Игрок')}</b>\n"
        f"Начислено: <b>+{result['points']} баллов</b>\n"
        f"Всего у игрока: <b>{result['total']}</b>"
    )
    try:
        await bot.send_message(
            chat_id=result["tg_user_id"],
            text=(
                "✅ <b>ЗАДАНИЕ ПРИНЯТО</b>\n\n"
                f"{html.escape(result['title'])}\n"
                f"Начислено: <b>+{result['points']} баллов</b>\n"
                f"Всего: <b>{result['total']}</b> баллов"
            ),
            reply_markup=player_menu(),
        )
    except Exception:
        logging.exception("Task acceptance notification failed")
    await callback.answer("Задание принято")


@dp.callback_query(F.data.startswith("revise_task:"))
async def revise_task(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    try:
        delivery_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Работа не найдена", show_alert=True)
        return

    result = await db.return_task_for_revision(delivery_id)
    if not result:
        await callback.answer("Работа не найдена", show_alert=True)
        return
    if result["status"] != "revision" or "tg_user_id" not in result:
        labels = {
            "accepted": "Эта работа уже принята",
            "revision": "Работа уже отправлена на доработку",
            "delivered": "Игрок ещё не сдал работу",
            "expired": "Дедлайн прошёл: работу можно принять, но нельзя вернуть на доработку",
        }
        await callback.answer(labels.get(result["status"], "Работа уже обработана"), show_alert=True)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        logging.exception("Could not remove task review keyboard")

    await callback.message.answer(
        "↩️ Работа отправлена на доработку.\n"
        "Комментарий можно написать в этой ветке — бот передаст его игроку."
    )
    try:
        await bot.send_message(
            chat_id=result["tg_user_id"],
            text=(
                "↩️ <b>ЗАДАНИЕ НУЖНО ДОРАБОТАТЬ</b>\n\n"
                f"{html.escape(result['title'])}\n\n"
                "Посмотри комментарий ведущей, затем открой «📋 Задания дня» "
                "и отправь работу повторно."
            ),
            reply_markup=player_menu(),
        )
    except Exception:
        logging.exception("Task revision notification failed")
    await callback.answer("Отправлено на доработку")


@dp.callback_query(F.data.startswith("admin_delete_player:"))
async def admin_delete_player(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    user_id = int(callback.data.split(":", 1)[1])
    player = await db.get_player(user_id)
    if not player:
        await callback.answer("Игрок уже удалён.", show_alert=True)
        return

    name = player["first_name"] or player["username"] or str(user_id)
    await callback.message.answer(
        f"🗑 <b>Удалить игрока {name}?</b>\n\n"
        "Будут удалены профиль, баллы, задания, достижения и секретные миссии.\n"
        "Личная ветка в админ-чате останется, чтобы история общения не потерялась.",
        reply_markup=admin_confirm_delete_player(user_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_confirm_delete_player:"))
async def admin_confirm_delete_player_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    user_id = int(callback.data.split(":", 1)[1])
    topic_id = await db.delete_player(user_id)

    if topic_id is None:
        await callback.answer("Игрок уже удалён.", show_alert=True)
        return

    await callback.message.answer(
        "✅ Игрок удалён из ACTIVATION.\n"
        "Его личная ветка сохранена в админ-чате."
    )
    await callback.answer("Игрок удалён")


@dp.callback_query(F.data == "admin_cancel_delete_player")
async def admin_cancel_delete_player(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.answer("Удаление отменено")


@dp.message(F.chat.type == "private")
async def private_to_topic(message: Message):
    if message.text and message.text.startswith("/"):
        return

    # Личка ведущей остаётся только админ-панелью.
    if is_admin(message.from_user.id):
        return

    player = await ensure_player(message)
    await bot.copy_message(
        chat_id=config.admin_chat_id,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
        message_thread_id=player["topic_id"],
    )


@dp.message(F.chat.id == config.admin_chat_id)
async def topic_to_player(message: Message):
    if not message.message_thread_id:
        return
    if message.from_user and message.from_user.is_bot:
        return

    player = await db.get_player_by_topic(message.message_thread_id)
    if not player:
        return

    await bot.copy_message(
        chat_id=player["tg_user_id"],
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )


async def main():
    await db.init()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

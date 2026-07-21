from pathlib import Path
import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, FSInputFile

from config import load_config
from db import Database
from cards import points_card, player_card
from keyboards import player_menu, admin_menu, confirm_task, enter_game_keyboard

logging.basicConfig(level=logging.INFO)

config = load_config()
db = Database(config.db_path)

bot = Bot(
    config.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


class CreateTask(StatesGroup):
    title = State()
    description = State()
    points = State()
    confirm = State()


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
        "📸 Теперь отправь <b>свою фотографию</b>.\n\n"
        "Она станет частью твоей персональной карты игрока ACTIVATION."
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
        username=message.from_user.username or "",
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
    await callback.message.answer(
        "🎮 <b>ТВОЙ ПРОГРЕСС</b>\n\n"
        f"День: <b>{player['current_day']} / 21</b>\n"
        f"Баллы: <b>{player['points']}</b>\n"
        f"🔥 Серия: <b>{player['streak']} дней</b>"
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
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@dp.callback_query(F.data == "achievements")
async def achievements(callback: CallbackQuery):
    await callback.message.answer(
        "🏅 <b>ТВОИ ДОСТИЖЕНИЯ</b>\n\n"
        "Некоторые награды скрыты и откроются неожиданно 👀"
    )
    await callback.answer()


@dp.callback_query(F.data == "latest_task")
async def latest_task(callback: CallbackQuery):
    await callback.message.answer(
        "🎯 Актуальные задания приходят тебе автоматически, как только ведущая открывает новую миссию."
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_create_task")
async def admin_create_task(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(CreateTask.title)
    await callback.message.answer("✍️ Введи <b>название задания</b>:")
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
    data = await state.get_data()
    await state.set_state(CreateTask.confirm)

    await message.answer(
        "🎯 <b>НОВОЕ ЗАДАНИЕ</b>\n\n"
        f"<b>{data['title']}</b>\n\n"
        f"{data['description']}\n\n"
        f"Награда: <b>+{points} баллов</b>",
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
    if not all(k in data for k in ("title", "description", "points")):
        await callback.answer("Данные задания потеряны. Создай заново.", show_alert=True)
        return

    task_id = await db.create_task(
        data["title"], data["description"], data["points"], callback.from_user.id
    )
    players = await db.all_players()

    sent = 0
    failed = 0
    text = (
        "🎯 <b>НОВАЯ МИССИЯ ACTIVATION</b>\n\n"
        f"<b>{data['title']}</b>\n\n"
        f"{data['description']}\n\n"
        f"Награда: <b>+{data['points']} баллов</b>\n\n"
        "Выполни задание и отправь результат сюда."
    )

    for player in players:
        try:
            await bot.send_message(player["tg_user_id"], text)
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
    players = await db.all_players()
    if not players:
        await callback.message.answer("Игроков пока нет.")
    else:
        lines = ["👥 <b>ИГРОКИ</b>\n"]
        for p in players[:50]:
            name = p["first_name"] or p["username"] or str(p["tg_user_id"])
            lines.append(f"• {name} — {p['points']} баллов")
        await callback.message.answer("\n".join(lines))
    await callback.answer()


@dp.message(Command("points"))
async def points_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        await message.answer("Формат: <code>/points USER_ID 100 причина</code>")
        return
    try:
        user_id = int(parts[1])
        delta = int(parts[2])
    except ValueError:
        await message.answer("USER_ID и количество баллов должны быть числами.")
        return

    reason = parts[3] if len(parts) > 3 else "Бонус ACTIVATION"
    try:
        total = await db.add_points(user_id, delta, reason)
        player = await db.get_player(user_id)
    except ValueError as e:
        await message.answer(str(e))
        return

    name = player["first_name"] or player["username"] or "Игрок"
    card = points_card(name, delta, total, reason)

    await bot.send_photo(
        user_id,
        FSInputFile(card),
        caption=(
            f"🔥 <b>+{delta} БАЛЛОВ</b>\n\n"
            f"{reason}\n\n"
            f"Всего: <b>{total}</b>"
        ),
    )
    await message.answer(f"Готово. Игроку начислено {delta} баллов.")


@dp.message(Command("secret"))
async def secret_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await message.answer(
            "Формат:\n"
            "<code>/secret USER_ID 200 Название | Текст секретной миссии</code>"
        )
        return

    try:
        user_id = int(parts[1])
        points = int(parts[2])
    except ValueError:
        await message.answer("USER_ID и количество баллов должны быть числами.")
        return

    payload = parts[3]
    if "|" in payload:
        title, description = [x.strip() for x in payload.split("|", 1)]
    else:
        title, description = "Секретная миссия", payload.strip()

    try:
        await db.create_secret_mission(user_id, title, description, points)
    except ValueError as e:
        await message.answer(str(e))
        return

    await bot.send_message(
        user_id,
        "🎴 <b>ТЕБЕ ОТКРЫТА СЕКРЕТНАЯ МИССИЯ</b>\n\n"
        f"<b>{title}</b>\n\n"
        f"{description}\n\n"
        f"Награда: <b>+{points} баллов</b>",
    )
    await message.answer("Секретная миссия отправлена.")


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

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

def player_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Задания дня")],
            [KeyboardButton(text="🎮 Мой прогресс"), KeyboardButton(text="🏆 Рейтинг")],
            [KeyboardButton(text="🏅 Достижения"), KeyboardButton(text="👥 Игроки")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Меню игрока",
    )


def public_players_keyboard(players):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=player["first_name"] or "Игрок",
                callback_data=f"public_player:{player['tg_user_id']}",
            )
        ]
        for player in players
    ])

def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Создать задание")],
            [KeyboardButton(text="📣 Отправить сообщение всем")],
            [KeyboardButton(text="👥 Игроки"), KeyboardButton(text="🏆 Рейтинг")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Панель ведущей",
    )

def confirm_task():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Отправить всем", callback_data="admin_send_task")],
        [InlineKeyboardButton(text="✏️ Отменить", callback_data="admin_cancel_task")],
    ])


def task_type_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Основное", callback_data="create_task_type:main")],
        [InlineKeyboardButton(text="📱 Медиа", callback_data="create_task_type:media")],
        [InlineKeyboardButton(text="✨ Дополнительное", callback_data="create_task_type:extra")],
        [InlineKeyboardButton(text="✏️ Отменить", callback_data="admin_cancel_task")],
    ])


def confirm_broadcast():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Отправить всем", callback_data="admin_send_broadcast")],
        [InlineKeyboardButton(text="✏️ Отменить", callback_data="admin_cancel_broadcast")],
    ])


def enter_game_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 ВОЙТИ В ИГРУ", callback_data="enter_game")]
    ])


def submit_task_keyboard(task_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Сдать задание", callback_data=f"submit_task:{task_id}")],
    ])


def task_review_keyboard(delivery_id: int, points: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"✅ Принять +{points}",
                callback_data=f"accept_task:{delivery_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="↩️ На доработку",
                callback_data=f"revise_task:{delivery_id}",
            )
        ],
    ])


def admin_player_actions(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить баллы", callback_data=f"admin_add_points:{user_id}")],
        [InlineKeyboardButton(text="🗑 Удалить игрока", callback_data=f"admin_delete_player:{user_id}")],
    ])

def admin_confirm_delete_player(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin_confirm_delete_player:{user_id}")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data="admin_cancel_delete_player")],
    ])

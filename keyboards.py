from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

def player_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Актуальное задание", callback_data="latest_task")],
        [InlineKeyboardButton(text="🎮 Мой прогресс", callback_data="progress")],
        [InlineKeyboardButton(text="🏆 Рейтинг", callback_data="leaderboard")],
        [InlineKeyboardButton(text="🏅 Достижения", callback_data="achievements")],
        [InlineKeyboardButton(text="👥 Игроки", callback_data="players")],
    ])


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


def confirm_broadcast():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Отправить всем", callback_data="admin_send_broadcast")],
        [InlineKeyboardButton(text="✏️ Отменить", callback_data="admin_cancel_broadcast")],
    ])


def enter_game_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 ВОЙТИ В ИГРУ", callback_data="enter_game")]
    ])


def admin_player_actions(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить игрока", callback_data=f"admin_delete_player:{user_id}")],
    ])

def admin_confirm_delete_player(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin_confirm_delete_player:{user_id}")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data="admin_cancel_delete_player")],
    ])

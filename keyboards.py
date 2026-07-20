from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def player_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Актуальное задание", callback_data="latest_task")],
        [InlineKeyboardButton(text="🎮 Мой прогресс", callback_data="progress")],
        [InlineKeyboardButton(text="🏆 Рейтинг", callback_data="leaderboard")],
        [InlineKeyboardButton(text="🏅 Достижения", callback_data="achievements")],
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать задание", callback_data="admin_create_task")],
        [InlineKeyboardButton(text="👥 Игроки", callback_data="admin_players")],
        [InlineKeyboardButton(text="🏆 Рейтинг", callback_data="admin_leaderboard")],
    ])

def confirm_task():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Отправить всем", callback_data="admin_send_task")],
        [InlineKeyboardButton(text="✏️ Отменить", callback_data="admin_cancel_task")],
    ])

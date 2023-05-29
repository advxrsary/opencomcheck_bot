# Local imports
from main import get_db, generate_keyboard

# Standart libraries
import logging
import time

# Third-party libraries
from datetime import datetime
from typing import List
from aiogram import types



BANNER = """
Welcome to the Channel Comment Checker Bot!

This bot can check if a Telegram channel has an open comments section. You can either send a list of channels or a file containing a list of channels, and the bot will check if they have open comments sections.

To use the bot:
1. Send a message with a list of channels (e.g. @channel1 @channel2 @channel3)
2. Or, upload a file containing a list of channels

-------------------------------------------


Добро пожаловать в бот проверки комментариев канала!

Этот бот может проверить, открыт ли раздел комментариев телеграм-канала. Вы можете отправить список каналов или файл, содержащий список каналов, и бот проверит, есть ли у них открытые разделы комментариев.

Как пользоваться ботом:
1. Отправьте сообщение со списком каналов (например, @channel1 @channel2 @channel3)
2. Или загрузите файл, содержащий список каналов
"""


def get_timestamp() -> str:
    logging.info("Getting timestamp...")
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def get_sleep_time(num_channels: int) -> int:
    logging.info("Getting sleep time...")
    if num_channels < 30:
        return 60
    elif num_channels < 90:
        return 600

def generate_progress_bar(current: int, total: int, length: int = 12) -> str:
    """Generates a progress bar as a string of blocks."""

    proportion = current / total
    progress = int(proportion * length)

    return '▓' * progress + '░' * (length - progress)

def generate_progress_message(current: int, total: int, elapsed_time: float):
    """Generates a progress message with the current progress and estimated time remaining."""

    estimated_time_remaining = (elapsed_time / current) * (total - current) if current > 0 else 0
    estimated_minutes, estimated_seconds = divmod(estimated_time_remaining, 60)

    percentage = int((current / total) * 100)

    progress_bar = generate_progress_bar(current, total)

    progress_message = f"{percentage}% {progress_bar} {current}/{total}\n"
    progress_message += f"ETA: {int(estimated_minutes)} min. {int(estimated_seconds)} s."

    return progress_message


async def add_user(user: types.User):
    async with get_db() as db:
        await db.execute('''
            INSERT OR IGNORE INTO users(id, username, first_name, last_name)
            VALUES(?, ?, ?, ?)
        ''', (user.id, user.username, user.first_name, user.last_name))
        await db.commit()


async def get_users() -> List[dict]:
    logging.info("Getting users from the database...")
    users = []
    async with get_db() as db:
        cursor = await db.cursor()
        await cursor.execute("SELECT * FROM users")
        rows = await cursor.fetchall()

    for row in rows:
        users.append(
            {"id": row[0], "username": row[1],
                "first_name": row[2], "last_name": row[3]}
        )
    logging.info("Finished getting users from the database.")
    return users


async def show_results(message: types.Message, latest_data, description: str):
    logging.info("Showing results...")
    text = f"{description}:\n\n"
    for channel in latest_data:
        text += f"{channel['title']} ({channel['username']}): {channel['link']}\n"
    await message.reply(text)
    logging.info("Finished showing results.")


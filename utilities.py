# Local imports
from main import get_db, generate_keyboard

# Standart libraries
import logging
import time
import asyncio

# Third-party libraries
from datetime import datetime
from typing import List
from dotenv import load_dotenv
from aiogram import types
from aiogram.types import InputFile


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
    if num_channels <= 50:
        return 10
    elif num_channels <= 90:
        return 60
    elif num_channels <= 150:
        return 120
    else:
        return 200

async def update_progress_message(i: int, total: int, start_time: float, progress_message, sleep_time: int):
    elapsed_time = time.time() - start_time 
    total_sleep_time = sleep_time * ((i + 1) // 30)  # Total sleep time is sleep_time for each group of 30 channels
    total_time = elapsed_time + total_sleep_time
    channels_remaining = total - (i + 1)
    estimated_time_remaining = (total_time / (i + 1)) * channels_remaining
    estimated_minutes, estimated_seconds = divmod(estimated_time_remaining, 60)
    
    keyboard = generate_keyboard()

    await progress_message.edit_text(
        f"Checked {i + 1} out of {total} channels...\n"
        f"Estimated time remaining: {int(estimated_minutes)} minutes {int(estimated_seconds)} seconds",
        reply_markup=keyboard  # Add the keyboard to the message
    )


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


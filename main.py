import os
import re
import logging
import sqlite3
import tempfile
import time
from datetime import datetime
from dotenv import load_dotenv
from typing import List
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.types import InputFile
from aiogram.utils.exceptions import NetworkError
from aiogram.utils import executor
from contextlib import asynccontextmanager
from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.errors.rpcerrorlist import UsernameNotOccupiedError


load_dotenv()

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

api_id = os.environ.get("TELEGRAM_API_ID")
api_hash = os.environ.get("TELEGRAM_API_HASH")
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")

if not TELEGRAM_USER_ID:
    TELEGRAM_USER_ID = input("TELEGRAM_USER_ID is unset in '.env'. Please enter TELEGRAM_USER_ID: ")


@asynccontextmanager
async def get_telethon_client():
    telethon_client = TelegramClient("anon", api_id, api_hash)
    await telethon_client.start(bot_token=bot_token)
    try:
        yield telethon_client
    finally:
        await telethon_client.disconnect()

bot = Bot(token=bot_token)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def init_db():
    conn = sqlite3.connect("bot_users.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            timestamp DATETIME
        )
    """)
    conn.commit()
    conn.close()

init_db()

def add_user(username: str):
    conn = sqlite3.connect("bot_users.db")
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        c.execute("""
            INSERT OR IGNORE INTO users (username, timestamp) 
            VALUES (?, ?)
        """, (username, timestamp))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error adding user {username}: {e}")
    finally:
        conn.close()

async def track_user_middleware(event: types.Update, next_call):
    if event.message and event.message.from_user.username:
        add_user(event.message.from_user.username)
    await next_call()

class UserTrackingMiddleware(BaseMiddleware):

    async def on_pre_process_message(self, message: types.Message, data: dict):
        if message.from_user.username:
            add_user(message.from_user.username)

dp.middleware.setup(UserTrackingMiddleware())


def get_users():
    conn = sqlite3.connect("bot_users.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    users = c.fetchall()
    conn.close()

    return "\n".join(f"{user[1]} (ID: {user[0]}, Timestamp: {user[2]})" for user in users)


@dp.message_handler(commands=['list_users'])
async def list_users(message: types.Message):
    if str(message.from_user.id) == TELEGRAM_USER_ID:
        users_data = get_users()
        await message.reply(f"Users:\n{users_data}")
    else:
        await message.reply("You are not authorized to use this command.")


async def on_startup(dp):
    pass


async def on_shutdown(dp):
    pass




@dp.message_handler(commands=['start', 'help'])
async def start_help(message: types.Message):
    await message.reply(BANNER)


async def check_channels(telethon_client, channels: List[str]) -> List[str]:
    open_comments = []
    not_existing_channels = []

    for channel_username in channels:
        try:
            channel = await telethon_client.get_entity(channel_username)
            full_channel = await telethon_client(GetFullChannelRequest(channel))
            if full_channel.full_chat.linked_chat_id:
                open_comments.append(channel_username)
        except ValueError as e:
            not_existing_channels.append(channel_username)
            print(f"Error checking channel {channel_username}: {e}")

    if not_existing_channels:
        print(f"Non-existing channels: {', '.join(not_existing_channels)}")

    return open_comments


async def send_open_comments_channels(chat_id: int, open_comments: List[str]):
    if not open_comments:
        await bot.send_message(chat_id=chat_id, text="No channels with open comments found.")
        return

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False) as f:
        f.write("\n".join(open_comments))
        f.flush()
    with open(f.name, "rb") as file_to_send:
        await bot.send_document(chat_id=chat_id, document=InputFile(file_to_send), caption="Channels with open comments section")

    os.remove(f.name)


@dp.message_handler(lambda message: message.text and "@" in message.text)
async def list_channels(message: types.Message):
    channels = re.findall(r"@[\w\d]+", message.text)
    await message.reply(f"Checking {len(channels)} channels. Please wait...")

    async with get_telethon_client() as telethon_client:
        open_comments = await check_channels(telethon_client, channels)

    await send_open_comments_channels(message.chat.id, open_comments)


@dp.message_handler(content_types=['document'])
async def handle_file(message: types.Message):
    document = message.document
    file_bytes = await bot.download_file_by_id(document.file_id)

    channels = [line.strip()
                for line in file_bytes.getvalue().decode().split('\n')]

    await message.reply(f"Checking {len(channels)} channels. Please wait...")

    async with get_telethon_client() as telethon_client:
        open_comments = await check_channels(telethon_client, channels)

    await send_open_comments_channels(message.chat.id, open_comments)



if __name__ == '__main__':
    while True:
        try:
            executor.start_polling(
                dp, on_startup=on_startup, on_shutdown=on_shutdown)
        except NetworkError as e:
            logging.error(
                f"NetworkError occurred: {e}. Retrying in 5 seconds...")
            time.sleep(5)
        else:
            break

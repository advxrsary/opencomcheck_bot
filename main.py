# Local import
from telethon.errors import FloodWaitError
from utilities import *

# Standard library imports
import asyncio
import logging
import os
import re
import signal
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List

# Third party imports
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.utils.exceptions import NetworkError
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors.rpcerrorlist import FloodWaitError, UsernameNotOccupiedError
from telethon.tl.functions.channels import GetFullChannelRequest

load_dotenv()

api_id = os.getenv("TELEGRAM_API_ID")
api_hash = os.getenv("TELEGRAM_API_HASH")
bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
user_id = os.environ.get("TELEGRAM_USER_ID")
db_name = os.environ.get("DB_NAME")
bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

bot = Bot(bot_token)
dp = Dispatcher(bot)
session_name = "anon"


class UserTrackingMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        await add_user(message.from_user)


dp.middleware.setup(UserTrackingMiddleware())
dp.middleware.setup(LoggingMiddleware())


if not user_id:
    user_id = input(
        "TELEGRAM_USER_ID is unset in '.env'. Please enter TELEGRAM_USER_ID: ")


@asynccontextmanager
async def get_telethon_client():
    logging.info("Getting Telethon client...")
    session_file_path = f"{session_name}.session"
    telethon_client = TelegramClient(session_name, api_id, api_hash)
    await telethon_client.start(bot_token=bot_token)

    def signal_handler(sig, frame):

        if os.path.exists(session_file_path):
            os.remove(session_file_path)
        sys.exit(0)

    # Register the signal handler for SIGINT
    signal.signal(signal.SIGINT, signal_handler)

    try:
        yield telethon_client
    except FloodWaitError as e:
        logging.error(f"FloodWaitError: {e.seconds} seconds.")
        raise e
    finally:
        await telethon_client.disconnect()
        if os.path.exists(session_file_path):
            os.remove(session_file_path)
        logging.info("Finished getting Telethon client.")


@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(db_name)
    try:
        yield db
    finally:
        await db.close()

db_lock = asyncio.Lock()


def generate_keyboard():
    # Create the keyboard
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton(
        "View checked", callback_data="view_checked"))
    keyboard.add(InlineKeyboardButton("Cancel", callback_data="cancel"))
    return keyboard


async def send_summary(chat_id: int, open_comments: List[str], closed_comments: List[str], errors: List[str]):
    logging.info("Sending summary...")
    summary = f"/opened {len(open_comments)}\n/closed: {len(closed_comments)}\n/errors: {len(errors)}"
    await bot.send_message(chat_id=chat_id, text=summary)
    logging.info("Finished sending summary.")


async def send_channels_file(message: types.Message, filename: str, channels: List[dict]):
    logging.info("Sending channels file...")
    with tempfile.NamedTemporaryFile(mode="w+t", delete=False) as f:
        for channel in channels:
            f.write(
                f"{channel['title']} ({channel['username']}): {channel['link']}\n")
        f.seek(0)
        await bot.send_document(chat_id=message.chat.id, document=InputFile(f), caption=filename)
    os.unlink(f.name)
    logging.info("Finished sending channels file.")


async def handle_channel_processing(channel_username: str, telethon_client, open_comments: dict, closed_comments: dict, errors: dict):
    try:
        channel = await telethon_client.get_entity(channel_username)
        full_channel = await telethon_client(GetFullChannelRequest(channel))
        if full_channel.full_chat.linked_chat_id:
            open_comments[channel_username] = channel
        else:
            closed_comments[channel_username] = channel
    except UsernameNotOccupiedError:
        logging.warning(f"Username {channel_username} not occupied")
        errors[channel_username] = "Username not occupied"
    except ValueError as e:
        logging.warning(f"ValueError while processing {channel_username}: {e}")
        errors[channel_username] = f"Error while processing {channel_username}: {e}"
        logger.warning(f"Error while processing {channel_username}: {e}")
    except FloodWaitError as e:
        logging.error(f"FloodWaitError: {e.seconds} seconds. Sleeping now.")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        logging.warning(f"Error while processing {channel_username}: {e}")
        errors[channel_username] = f"Error while processing {channel_username}: {e}"


async def check_channels(telethon_client, channels: List[str], message: types.Message):
    open_comments, closed_comments, errors = {}, {}, {}
    progress_message = await message.reply("Starting to check channels...")
    sleep_time = get_sleep_time(len(channels))
    start_time = time.time()
    logging.info(f"Checking {len(channels)} channels...")
    for i, channel_username in enumerate(channels):
        if re.match(r"@[\w\d]+", channel_username):  # Check if the username is valid
            await handle_channel_processing(channel_username, telethon_client, open_comments, closed_comments, errors)
        else:
            logging.warning(f"Invalid username: {channel_username}")
            errors[channel_username] = "Invalid username"

        await update_progress_message(i, len(channels), start_time, progress_message)
        await print_remaining_channels(i, len(channels), start_time)
    logging.info("Finished checking channels.")
    return open_comments, closed_comments, errors


class ChannelNotFoundError(Exception):
    def __init__(self, username):
        self.username = username
        super().__init__(f"No user has {username} as username")


async def track_user_middleware(event: types.Update, next_call):
    if event.message and event.message.from_user:
        print(event.message.from_user.username)  # Debug print statement
        await add_user(event.message.from_user)
    await next_call()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

latest_opened = {}
latest_closed = {}
latest_errors = {}


@dp.message_handler(commands=['start', 'help'])
async def start_help(message: types.Message):
    await message.reply(BANNER)


@dp.message_handler(commands=['opened'])
async def show_opened(message: types.Message):
    chat_id = message.chat.id
    if chat_id in latest_opened:
        open_list = "\n".join(latest_opened[chat_id])

        if len(latest_opened[chat_id]) > 50:
            with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
                tmp.write(
                    f"Channels with open comments from the latest request:\n{open_list}")
                tmp.flush()

            with open(tmp.name, "rb") as file:
                await message.reply_document(file, caption="Open channels from the latest request:")
            os.remove(tmp.name)
        else:
            await message.reply(f"Channels with open comments from the latest request:\n{open_list}")
    else:
        await message.reply("No open channels from the latest request.")


@dp.message_handler(commands=['closed'])
async def show_closed(message: types.Message):
    chat_id = message.chat.id
    if chat_id in latest_closed:
        closed_list = "\n".join(latest_closed[chat_id])

        if len(latest_closed[chat_id]) > 50:
            with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
                tmp.write(
                    f"Channels with closed comments from the latest request:\n{closed_list}")
                tmp.flush()

            with open(tmp.name, "rb") as file:
                await message.reply_document(file, caption="Closed channels from the latest request:")
            os.remove(tmp.name)
        else:
            await message.reply(f"Channels with closed comments from the latest request:\n{closed_list}")
    else:
        await message.reply("No closed channels from the latest request.")


@dp.message_handler(commands=['errors'])
async def show_errors(message: types.Message):
    chat_id = message.chat.id
    if chat_id in latest_errors:
        errors_list = "\n".join(latest_errors[chat_id])

        if len(latest_errors[chat_id]) > 50:
            with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
                tmp.write(f"Channel name does not exist:\n{errors_list}")
                tmp.flush()

            with open(tmp.name, "rb") as file:
                await message.reply_document(file, caption="Errors from the latest request:")
            os.remove(tmp.name)
        else:
            await message.reply(f"Channel name does not exist:\n{errors_list}")
    else:
        await message.reply("No errors from the latest request.")


@dp.message_handler(commands=['list_users'])
async def list_users(message: types.Message):
    if str(message.from_user.id) == user_id:
        users_data = await get_users()
        response = "Users:\n\n"
        for idx, user in enumerate(users_data, start=1):
            response += f"**User {idx}**\n"
            response += f"- ID: `{user['id']}`\n"
            response += f"- Username: `@{user['username']}`\n"
            response += f"- First Name: `{user['first_name']}`\n"
            response += f"- Last Name: `{user['last_name'] or 'None'}`\n"
            response += "\n"
        await message.reply(response, parse_mode='Markdown')
    else:
        await message.reply("You are not authorized to use this command.")


@dp.message_handler(lambda message: message.text and "@" in message.text)
async def handle_text(message: types.Message):
    pattern = r"(?:https?://tgstat\.ru/channel/)?@([\w\d]+)(?:/stat)?"
    channels = set("@" + match.group(1) if not match.group(1).startswith("@")
                   else match.group(1) for match in re.finditer(pattern, message.text))

    async with get_telethon_client() as telethon_client:
        try:
            open_comments, closed_comments, errors = await check_channels(telethon_client, channels, message)
        except ChannelNotFoundError as e:
            errors.append(e.username)

    latest_opened[message.chat.id] = open_comments
    latest_errors[message.chat.id] = errors
    latest_closed[message.chat.id] = closed_comments

    await send_summary(message.chat.id, open_comments, closed_comments, errors)
    if len(open_comments) > 50 or (message.text and message.text.startswith("/opened_file")):
        await send_channels_file(message.chat.id, open_comments, "opened")


@dp.message_handler(content_types=['document'])
async def handle_file(message: types.Message):
    document = message.document
    file_bytes = await bot.download_file_by_id(document.file_id)

    pattern = r"(?:https?://tgstat\.ru/channel/)?@([\w\d]+)(?:/stat)?"
    channels = set("@" + match.group(1) if not match.group(1).startswith("@") else match.group(1)
                   for match in re.finditer(pattern, file_bytes.getvalue().decode()))

    async with get_telethon_client() as telethon_client:
        try:
            open_comments, closed_comments, errors = await check_channels(telethon_client, channels, message)
        except ChannelNotFoundError as e:
            errors.append(e.username)

    latest_opened[message.chat.id] = open_comments
    latest_errors[message.chat.id] = errors
    latest_closed[message.chat.id] = closed_comments

    await send_summary(message.chat.id, open_comments, closed_comments, errors)
    if len(open_comments) > 50 or (message.text and message.text.startswith("/opened_file")):
        await send_channels_file(message.chat.id, open_comments, "opened")


async def on_startup(dp):
    async with aiosqlite.connect(db_name) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                chat_id INTEGER
            )
        """)
        await db.commit()


async def on_shutdown(dp):
    pass


def main():
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)


if __name__ == '__main__':
    while True:
        try:
            main()
        except (NetworkError, FloodWaitError) as e:
            logging.error(f"Error occurred: {e}. Retrying in 5 seconds...")
            time.sleep(5)
        else:
            break

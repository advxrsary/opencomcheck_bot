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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from aiogram.utils import executor
from aiogram.utils.exceptions import NetworkError
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors.rpcerrorlist import FloodWaitError, UsernameNotOccupiedError, UsernameInvalidError
from telethon.tl.functions.channels import GetFullChannelRequest

load_dotenv()


API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
USER_ID = os.environ.get("TELEGRAM_USER_ID")
DB_NAME = os.environ.get("DB_NAME")

BOT = Bot(BOT_TOKEN)
DP = Dispatcher(BOT)
SESSION_NAME = "anon"
CHECKED_CHANNELS, CANCELATION_FLAG = {}, {}

class UserTrackingMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        await add_user(message.from_user)


DP.middleware.setup(UserTrackingMiddleware())
DP.middleware.setup(LoggingMiddleware())


if not USER_ID:
    USER_ID = input(
        "TELEGRAM_USER_ID is unset in '.env'. Please enter TELEGRAM_USER_ID: ")


@asynccontextmanager
async def get_telethon_client():
    logging.info("Getting Telethon client...")
    session_file_path = f"{SESSION_NAME}.session"
    telethon_client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await telethon_client.start(bot_token=BOT_TOKEN)

    def signal_handler(sig, frame):

        if os.path.exists(session_file_path):
            os.remove(session_file_path)
        sys.exit(0)

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
    db = await aiosqlite.connect(DB_NAME)
    try:
        yield db
    finally:
        await db.close()

db_lock = asyncio.Lock()


def generate_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("View checked", callback_data="view_checked"), InlineKeyboardButton("Cancel", callback_data="cancel"))
    return keyboard


async def send_summary(chat_id: int, opened_comments: List[str], closed_comments: List[str], errors: List[str]):
    logging.info("Sending summary...")
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Opened", callback_data="opened"), InlineKeyboardButton("Closed", callback_data="closed"), InlineKeyboardButton("Errors", callback_data="errors"))
    await BOT.send_message(
        chat_id=chat_id, 
        text=f"*Summary:*\n\n*Opened:* {len(opened_comments)}\n*Closed:* {len(closed_comments)}\n*Errors:* {len(errors)}", 
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    logging.info("Finished sending summary.")


async def send_channels_file(message: types.Message, filename: str, channels: List[dict]):
    logging.info("Sending channels file...")
    with tempfile.NamedTemporaryFile(mode="w+t", delete=False) as f:
        for channel in channels:
            f.write(
                f"{channel['title']} ({channel['username']}): {channel['link']}\n")
        f.seek(0)
        await BOT.send_document(chat_id=message.chat.id, document=InputFile(f), caption=filename)
    os.unlink(f.name)
    logging.info("Finished sending channels file.")


async def handle_channel_processing(channel_username: str, telethon_client, opened_comments: dict, closed_comments: dict, errors: dict):
    try:
        channel = await telethon_client.get_entity(channel_username)
        full_channel = await telethon_client(GetFullChannelRequest(channel))
        if full_channel.full_chat.linked_chat_id:
            opened_comments[channel_username] = channel
        else:
            closed_comments[channel_username] = channel
    except UsernameNotOccupiedError:
        logging.warning(f"Username {channel_username} not occupied")
        errors[channel_username] = "Username not occupied"
    except UsernameInvalidError:
            logging.warning(f"Invalid username: {channel_username}")
            errors[channel_username] = "Invalid username"
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

async def update_checked_channels(chat_id, channel_username, opened_comments, closed_comments, errors):
    if channel_username in opened_comments:
        CHECKED_CHANNELS[chat_id]['opened_comments'].append(channel_username)
    elif channel_username in closed_comments:
        CHECKED_CHANNELS[chat_id]['closed_comments'].append(channel_username)
    elif channel_username in errors:
        CHECKED_CHANNELS[chat_id]['errors'].append(channel_username)


async def check_channels(telethon_client, channels: List[str], message: types.Message):
    opened_comments, closed_comments, errors = {}, {}, {}
    progress_message = await message.reply("Starting to check channels...")
    start_time = time.time()
    sleep_time = get_sleep_time(len(channels))
    CHECKED_CHANNELS[message.chat.id] = {
        'opened_comments': [],
        'closed_comments': [],
        'errors': []
    }
    logging.info(f"Checking {len(channels)} channels...")
    for i, channel_username in enumerate(channels):
        if CANCELATION_FLAG.get(message.chat.id):
            logging.info("Canceled by user. Stopping checking channels.")
            CANCELATION_FLAG[message.chat.id] = False
            return opened_comments, closed_comments, errors
        if re.match(r"@[\w\d]+", channel_username):
            await handle_channel_processing(channel_username, telethon_client, opened_comments, closed_comments, errors)
        else:
            logging.warning(f"Invalid username: {channel_username}")
            errors[channel_username] = "Invalid username"

        await update_progress_message(i, len(channels), start_time, progress_message, sleep_time)
        await update_checked_channels(message.chat.id, channel_username, opened_comments, closed_comments, errors)
        if (i + 1) % 30 == 0:
            print(f"Anti-flood sleep for {sleep_time} seconds")
            await asyncio.sleep(sleep_time)
            
    

    logging.info("Finished checking channels.")
    return opened_comments, closed_comments, errors


class ChannelNotFoundError(Exception):
    def __init__(self, username):
        self.username = username
        super().__init__(f"No user has {username} as username")


async def track_user_middleware(event: types.Update, next_call):
    if event.message and event.message.from_user:
        await add_user(event.message.from_user)
    await next_call()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

latest_opened = {}
latest_closed = {}
latest_errors = {}

@DP.callback_query_handler(lambda c: c.data == 'cancel')
async def cancel(callback_query: types.CallbackQuery):
    CANCELATION_FLAG[callback_query.message.chat.id] = True

@DP.message_handler(commands=['start', 'help'])
async def start_help(message: types.Message):
    await message.reply(BANNER)

@DP.callback_query_handler(lambda c: c.data == 'view_checked')
async def view_checked(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    username = callback_query.message.from_user.username
    if chat_id in CHECKED_CHANNELS:
        
        file_name = f"{username}_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"

        with tempfile.NamedTemporaryFile(mode="w+t", delete=False, suffix=".txt", prefix=file_name) as f:
            f.write("opened:\n\n")
            f.write('\n'.join(CHECKED_CHANNELS[chat_id]['opened_comments']))
            f.write("\n\nclosed:\n\n")
            f.write('\n'.join(CHECKED_CHANNELS[chat_id]['closed_comments']))
            f.write("\n\nerror:\n\n")
            f.write('\n'.join(CHECKED_CHANNELS[chat_id]['errors']))
            f.seek(0)
            file_path = f.name

        with open(file_path, 'rb') as f:
            await BOT.send_document(chat_id=chat_id, document=InputFile(f), caption="Checked channels")

        os.unlink(file_path)
    else:
        await BOT.send_message(chat_id, "No channels have been checked yet.")


@DP.callback_query_handler(lambda c: c.data == 'opened')
async def show_opened(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    if chat_id in latest_opened:
        opened_list = "\n".join(f"- {username}" for username in latest_opened[chat_id])


        if len(latest_opened[chat_id]) > 50:
            with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
                tmp.write(
                    f"Channels with opened comments from the latest request:\n\n{opened_list}")
                tmp.flush()

            with open(tmp.name, "rb") as file:
                await callback_query.message.reply_document(file, caption="Opened comments from the latest request:")
            os.remove(tmp.name)
        else:
            await callback_query.message.reply(f"Channels with opened comments from the latest request:\n\n{opened_list}")
    else:
        await callback_query.message.reply("No opened comments from the latest request.")


@DP.callback_query_handler(lambda c: c.data == 'closed')
async def show_closed(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    if chat_id in latest_closed:
        closed_list = "\n".join(f"- {username}" for username in latest_closed[chat_id])

        if len(latest_closed[chat_id]) > 50:
            with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
                tmp.write(
                    f"Channels with closed comments from the latest request:\n\n{closed_list}")
                tmp.flush()

            with open(tmp.name, "rb") as file:
                await callback_query.message.reply_document(file, caption="Closed channels from the latest request:")
            os.remove(tmp.name)
        else:
            await callback_query.message.reply(f"Channels with closed comments from the latest request:\n\n{closed_list}")
    else:
        await callback_query.message.reply("No closed channels from the latest request.")


@DP.callback_query_handler(lambda c: c.data == 'errors')
async def show_errors(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    if chat_id in latest_errors:
        errors_list = "\n".join(f"- {username}" for username in latest_errors[chat_id])

        if len(latest_errors[chat_id]) > 50:
            with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
                tmp.write(f"Channel name does not exist:\n\n{errors_list}")
                tmp.flush()

            with open(tmp.name, "rb") as file:
                await callback_query.message.reply_document(file, caption="Errors from the latest request:")
            os.remove(tmp.name)
        else:
            await callback_query.message.reply(f"Channel name does not exist:\n\n{errors_list}")
    else:
        await callback_query.message.reply("No errors from the latest request.")


@DP.message_handler(commands=['list_users'])
async def list_users(message: types.Message):
    if str(message.from_user.id) == USER_ID:
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


@DP.message_handler(lambda message: message.text and "@" in message.text)
async def handle_text(message: types.Message):
    CANCELATION_FLAG[message.chat.id] = False
    pattern = r"(?:https?://tgstat\.ru/channel/)?@([\w\d]+)(?:/stat)?"
    channels = set("@" + match.group(1) if not match.group(1).startswith("@")
                   else match.group(1) for match in re.finditer(pattern, message.text))
    
    async with get_telethon_client() as telethon_client:
        try:
            opened_comments, closed_comments, errors = await check_channels(telethon_client, channels, message)
        except ChannelNotFoundError as e:
            errors.append(e.username)

    latest_opened[message.chat.id] = opened_comments
    latest_errors[message.chat.id] = errors
    latest_closed[message.chat.id] = closed_comments

    await send_summary(message.chat.id, opened_comments, closed_comments, errors)
    if len(opened_comments) > 50 or (message.text and message.text.startswith("/opened_file")):
        await send_channels_file(message.chat.id, opened_comments, "opened")


@DP.message_handler(content_types=['document'])
async def handle_file(message: types.Message):
    CANCELATION_FLAG[message.chat.id] = False
    document = message.document
    file_bytes = await BOT.download_file_by_id(document.file_id)

    pattern = r"(?:https?://tgstat\.ru/channel/)?@([\w\d]+)(?:/stat)?"
    channels = set("@" + match.group(1) if not match.group(1).startswith("@") else match.group(1)
                   for match in re.finditer(pattern, file_bytes.getvalue().decode()))

    async with get_telethon_client() as telethon_client:
        try:
            opened_comments, closed_comments, errors = await check_channels(telethon_client, channels, message)
        except ChannelNotFoundError as e:
            errors.append(e.username)

    latest_opened[message.chat.id] = opened_comments
    latest_errors[message.chat.id] = errors
    latest_closed[message.chat.id] = closed_comments

    await send_summary(message.chat.id, opened_comments, closed_comments, errors)
    if len(opened_comments) > 50 or (message.text and message.text.startswith("/opened_file")):
        await send_channels_file(message.chat.id, opened_comments, "opened")


async def on_startup(dp):
    async with aiosqlite.connect(DB_NAME) as db:
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
    executor.start_polling(DP, on_startup=on_startup, on_shutdown=on_shutdown)


if __name__ == '__main__':
    while True:
        try:
            main()
        except (NetworkError, FloodWaitError) as e:
            logging.error(f"Error occurred: {e}. Retrying in 5 seconds...")
            time.sleep(5)
        else:
            break

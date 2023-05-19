import os
import re
import time
import logging
import aiosqlite
import tempfile
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from typing import List
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.types import InputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.exceptions import NetworkError
from aiogram.utils import executor
from contextlib import asynccontextmanager
from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.errors.rpcerrorlist import UsernameNotOccupiedError, FloodWaitError
from telethon.tl.types import InputPeerChannel


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

api_id = os.getenv("TELEGRAM_API_ID")
api_hash = os.getenv("TELEGRAM_API_HASH")
bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")
db_name = os.environ.get("DB_NAME")
semaphore = asyncio.Semaphore(10)
clients = TelegramClient("anon", api_id, api_hash)
bot = Bot(token=bot_token)
dp = Dispatcher(bot)
class UserTrackingMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        print("on_pre_process_message called!")  # Debug print statement
        await add_user(message.from_user)



dp.middleware.setup(UserTrackingMiddleware())
dp.middleware.setup(LoggingMiddleware())


if not TELEGRAM_USER_ID:
    TELEGRAM_USER_ID = input(
        "TELEGRAM_USER_ID is unset in '.env'. Please enter TELEGRAM_USER_ID: ")


@asynccontextmanager
async def get_telethon_client():
    logging.info("Getting Telethon client...")
    telethon_client = TelegramClient("anon", api_id, api_hash)
    await telethon_client.start(bot_token=bot_token)
    try:
        yield telethon_client
    except FloodWaitError as e:
        logging.info(f"FloodWaitError: {e.seconds} seconds.")
        await message.reply("The request limit was hit. Please try again after some time.")
        raise e
    finally:
        await telethon_client.disconnect()
    logging.info("Finished getting Telethon client.")


@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(db_name)
    try:
        yield db
    finally:
        await db.close()

async def create_db():
    async with get_db() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT
            )
        ''')
        await db.commit()

@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(db_name)
    try:
        yield db
    finally:
        await db.close()

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
            {"id": row[0], "username": row[1], "first_name": row[2], "last_name": row[3]}
        )
    logging.info("Finished getting users from the database.")
    return users



def get_timestamp() -> str:
    logging.info("Getting timestamp...")
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def get_sleep_time(num_channels: int) -> int:
    logging.info("Getting sleep time...")
    if num_channels <= 50:
        logging.info("Fast queue.")
        return 1
    elif num_channels <= 90:
        logging.info("Medium queue.")
        return 3
    elif num_channels <= 150:
        logging.info("Slow queue.")
        return 5
    else:
        logging.info("The slowest queue.")
        return 6


async def check_channels(telethon_client, channels: List[str], message: types.Message):
    open_comments = {}
    closed_comments = {}
    errors = {}
    logging.info("Checking channels...")
    progress_message = await message.reply("Starting to check channels...")
    sleep_time = get_sleep_time(len(channels))
    start_time = time.time()  # Record the start time

    for i, channel_username in enumerate(channels):
        logging.info(f"Checking channel {channel_username}...")
        if re.match(r"@[\w\d]+", channel_username):  # Check if the username is valid
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

        else:
            logging.warning(f"Invalid username: {channel_username}")
            errors[channel_username] = "Invalid username"

        if (i + 1) % 1 == 0:
            elapsed_time = time.time() - start_time  # Calculate the elapsed time
            channels_remaining = len(channels) - (i + 1)
            estimated_time_remaining = (elapsed_time / (i + 1)) * channels_remaining  # Estimate the remaining time

            # Convert the estimated time to minutes and seconds
            estimated_minutes, estimated_seconds = divmod(estimated_time_remaining, 60)

            await progress_message.edit_text(
                f"Checked {i + 1} out of {len(channels)} channels...\n"
                f"Estimated time remaining: {int(estimated_minutes)} minutes {int(estimated_seconds)} seconds"
            )
        
        await asyncio.sleep(sleep_time)
        
    logging.info("Finished checking channels.")
    return open_comments, closed_comments, errors



async def send_summary(chat_id: int, open_comments: List[str], closed_comments: List[str], errors: List[str]):
    logging.info("Sending summary...")
    summary = f"/opened {len(open_comments)}\n/closed: {len(closed_comments)}\n/errors: {len(errors)}"
    await bot.send_message(chat_id=chat_id, text=summary)
    logging.info("Finished sending summary.")


async def send_channels_file(message: types.Message, filename: str, channels: List[dict]):
    logging.info("Sending channels file...")
    with tempfile.NamedTemporaryFile(mode="w+t", delete=False) as f:
        for channel in channels:
            f.write(f"{channel['title']} ({channel['username']}): {channel['link']}\n")
        f.seek(0)
        await bot.send_document(chat_id=message.chat.id, document=InputFile(f), caption=filename)
    os.unlink(f.name)
    logging.info("Finished sending channels file.")

async def show_results(message: types.Message, latest_data, description: str):
    logging.info("Showing results...")
    text = f"{description}:\n\n"
    for channel in latest_data:
        text += f"{channel['title']} ({channel['username']}): {channel['link']}\n"
    await message.reply(text)
    logging.info("Finished showing results.")


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
                tmp.write(f"Channels with open comments from the latest request:\n{open_list}")
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
                tmp.write(f"Channels with closed comments from the latest request:\n{closed_list}")
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
    if str(message.from_user.id) == TELEGRAM_USER_ID:
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
async def list_channels(message: types.Message):
    channels = set(re.findall(r"@[\w\d]+", message.text))

    async with get_telethon_client() as telethon_client:
        try:
            open_comments, closed_comments, errors = await check_channels(telethon_client, channels, message)
        except ChannelNotFoundError as e:
            errors.append(e.username)

    latest_opened[message.chat.id] = open_comments
    latest_errors[message.chat.id] = errors
    latest_closed[message.chat.id] = closed_comments
    
    await send_summary(message.chat.id, open_comments, closed_comments, errors)
    if len(open_comments) > 50 or message.text.startswith("/opened_file"):
        await send_channels_file(message.chat.id, open_comments, "opened")


@dp.message_handler(content_types=['document'])
async def handle_file(message: types.Message):
    document = message.document
    file_bytes = await bot.download_file_by_id(document.file_id)

    channels = set(line.strip() for line in file_bytes.getvalue().decode().split('\n'))

    async with get_telethon_client() as telethon_client:
        try:
            open_comments, closed_comments, errors = await check_channels(telethon_client, channels, message)
        except ChannelNotFoundError as e:
            errors.append(e.username)
    
    latest_opened[message.chat.id] = open_comments
    latest_errors[message.chat.id] = errors
    latest_closed[message.chat.id] = closed_comments

    await send_summary(message.chat.id, open_comments, closed_comments, errors)
    if len(open_comments) > 50 or message.text.startswith("/opened_file"):
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

if __name__ == '__main__':
    while True:
        try:
            executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)
        except (NetworkError, FloodWaitError) as e:
            logging.error(f"Error occurred: {e}. Retrying in 5 seconds...")
            time.sleep(5)
        else:
            break
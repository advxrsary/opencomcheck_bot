import os
import asyncio
import re
import logging
import tempfile
from typing import List
from aiogram.utils.exceptions import BadRequest
from aiogram import Bot, Dispatcher, types
from aiogram.types import ParseMode, InputFile
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils import executor
from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.errors.rpcerrorlist import UsernameNotOccupiedError
from dotenv import load_dotenv

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

telethon_client = TelegramClient("anon", api_id, api_hash)

bot = Bot(token=bot_token)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

async def on_startup(dp):
    await telethon_client.start()

async def on_shutdown(dp):
    await telethon_client.disconnect()
    await bot.close()

@dp.message_handler(commands=['start', 'help'])
async def start_help(message: types.Message):
    await message.reply(BANNER)

async def check_channels(channels: List[str]) -> List[str]:
    open_comments = []
    not_existing_channels = []

    for channel_username in channels:
        try:
            channel = await telethon_client.get_entity(channel_username)
            if not channel.admin_rights or channel.admin_rights.post_messages:
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
        await bot.send_document(chat_id=chat_id, document=InputFile(file_to_send), caption="Channels with open comments:")

    os.remove(f.name)


@dp.message_handler(lambda message: message.text and "@" in message.text)
async def list_channels(message: types.Message):
    channels = re.findall(r"@[\w\d]+", message.text)
    await message.reply(f"Checking {len(channels)} channels. Please wait...")

    open_comments = await check_channels(channels)

    await send_open_comments_channels(message.chat.id, open_comments)


@dp.message_handler(content_types=['document'])
async def handle_file(message: types.Message):
    document = message.document
    file_bytes = await bot.download_file_by_id(document.file_id)

    channels = [line.strip() for line in file_bytes.getvalue().decode().split('\n')]

    await message.reply(f"Checking {len(channels)} channels. Please wait...")

    open_comments = await check_channels(channels)

    await send_open_comments_channels(message.chat.id, open_comments)


if __name__ == '__main__':
    from aiogram import executor
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)

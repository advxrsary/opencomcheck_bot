import os
import asyncio
import re
from aiogram import Bot, Dispatcher, types
from aiogram.types import ParseMode, InputFile
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils import executor
from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest

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

async def on_startup(dp):
    await telethon_client.start()

async def on_shutdown(dp):
    await telethon_client.disconnect()
    await bot.close()

@dp.message_handler(commands=['start', 'help'])
async def start_help(message: types.Message):
    await message.reply(BANNER)

@dp.message_handler(lambda message: message.text and "@" in message.text)
async def list_channels(message: types.Message):
    channels = re.findall(r"@[\w\d]+", message.text)
    open_comments = []
    
    for channel_username in channels:
        channel = await telethon_client.get_entity(channel_username)
        full_channel = await telethon_client(GetFullChannelRequest(channel))
        
        if full_channel.full_chat.linked_chat_id:
            open_comments.append(channel_username)

    output_filename = "open_comments_channels.txt"
    with open(output_filename, "w") as f:
        f.write("\n".join(open_comments))
    
    with open(output_filename, "rb") as f:
        await bot.send_document(chat_id=message.chat.id, document=InputFile(f), caption="Channels with open comments:")

@dp.message_handler(content_types=['document'])
async def handle_file(message: types.Message):
    document = message.document
    file_bytes = await bot.download_file_by_id(document.file_id)

    channels = [line.strip() for line in file_bytes.getvalue().decode().split('\n')]

    open_comments = []

    for channel_username in channels:
        channel = await telethon_client.get_entity(channel_username)
        full_channel = await telethon_client(GetFullChannelRequest(channel))

        if full_channel.full_chat.linked_chat_id:
            open_comments.append(channel_username)

    output_filename = "open_comments_channels.txt"
    with open(output_filename, "w") as f:
        f.write("\n".join(open_comments))

    with open(output_filename, "rb") as f:
        await bot.send_document(chat_id=message.chat.id, document=InputFile(f), caption="Channels with open comments:")


if __name__ == '__main__':
    from aiogram import executor
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)

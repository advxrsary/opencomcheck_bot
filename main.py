import os
import asyncio
import re
from aiogram import Bot, Dispatcher, types
from aiogram.types import ParseMode, InputFile
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils import executor
from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton



BANNER = """
Welcome to the Channel Comment Checker Bot!

This bot can check if a Telegram channel has an open comments section. You can use the following commands:

/start - Begins the interaction with the user (you already used it!)
/help - Shows this help message
/list - Send a list of channels to the bot, and it will check if they have open comments sections
/file - Send a file containing a list of channels, and the bot will check if they have open comments sections
"""

api_id = os.environ.get("TELEGRAM_API_ID")
api_hash = os.environ.get("TELEGRAM_API_HASH")
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")

telethon_client = TelegramClient("anon", api_id, api_hash)

bot = Bot(token=bot_token)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

def create_menu():
    menu = InlineKeyboardMarkup()
    menu.add(InlineKeyboardButton("Channels List", callback_data="list_channels"))
    menu.add(InlineKeyboardButton("Upload File", callback_data="upload_file"))
    return menu

def create_reply_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("/list"))
    keyboard.add(KeyboardButton("/file"))
    return keyboard

async def on_startup(dp):
    await telethon_client.start()

async def on_shutdown(dp):
    await telethon_client.disconnect()
    await bot.close()

@dp.message_handler(commands=['start', 'help'])
async def start_help(message: types.Message):
    menu = create_menu()
    await message.reply(BANNER, reply_markup=menu)

@dp.callback_query_handler(lambda callback_query: callback_query.data in ["list_channels", "upload_file"])
async def process_menu(callback_query: types.CallbackQuery):
    if callback_query.data == "list_channels":
        await bot.send_message(chat_id=callback_query.from_user.id, text="Please send me the list of channels (e.g. @channel1 @channel2 @channel3).")
    elif callback_query.data == "upload_file":
        await bot.send_message(chat_id=callback_query.from_user.id, text="Please upload a file containing the list of channels.")
    await callback_query.answer()


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

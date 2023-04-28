import asyncio
import os
from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest

api_id = os.environ.get("TELEGRAM_API_ID")
api_hash = os.environ.get("TELEGRAM_API_HASH")
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")


async def main():
    client = TelegramClient("anon", api_id, api_hash)
    await client.start(bot_token=bot_token)

    channel_username = "@tavernaf5"  # Replace with the channel's username
    channel = await client.get_entity(channel_username)
    full_channel = await client(GetFullChannelRequest(channel))
    
    if full_channel.full_chat.linked_chat_id:
        print(f"The channel {channel_username} has an open comments section.")
    else:
        print(f"The channel {channel_username} does not have an open comments section.")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())

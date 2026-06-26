import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from utils.db import init_db

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

class EchoSync(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        init_db()
        await self.load_extension('cogs.music')
        await self.load_extension('cogs.stats')
        await self.load_extension('cogs.misc')
        await self.tree.sync()
        print("Bot is ready and slash commands synced.")

bot = EchoSync()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')

if __name__ == '__main__':
    bot.run(TOKEN)

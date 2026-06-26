import discord
from discord import app_commands
from discord.ext import commands
from utils.db import get_top_users

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="Shows the top listeners")
    async def leaderboard(self, interaction: discord.Interaction):
        top_users = get_top_users(10)
        
        if not top_users:
            return await interaction.response.send_message("No stats recorded yet!")

        embed = discord.Embed(title="🎧 Top Listeners Leaderboard", color=discord.Color.blurple())
        
        for index, row in enumerate(top_users):
            user = self.bot.get_user(int(row['user_id']))
            username = user.name if user else f"User {row['user_id']}"
            embed.add_field(
                name=f"#{index + 1} {username}", 
                value=f"{row['songs_played']} songs played", 
                inline=False
            )
            
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Stats(bot))

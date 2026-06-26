import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
from utils.db import add_song_played
import imageio_ffmpeg
import random
import time

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
    'executable': imageio_ffmpeg.get_ffmpeg_exe()
}

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

class MusicPlayer:
    def __init__(self, interaction, cog):
        self.bot = interaction.client
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.cog = cog
        self.queue = asyncio.Queue()
        self._queue_list = []
        self.history = []
        self.next = asyncio.Event()
        self.np = None
        self.volume = 1.0
        self.current = None
        self.loop_mode = 0 # 0=off, 1=track, 2=queue
        self.start_time = 0

        self.bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            self.next.clear()

            try:
                if self.loop_mode == 1 and self.current:
                    item = self.current
                else:
                    item = await asyncio.wait_for(self.queue.get(), timeout=300)
                    if self._queue_list:
                        self._queue_list.pop(0)
            except asyncio.TimeoutError:
                return self.destroy(self.guild)

            self.current = item
            self.start_time = time.time()
            source = discord.FFmpegPCMAudio(item['url'], **FFMPEG_OPTIONS)
            source = discord.PCMVolumeTransformer(source, volume=self.volume)

            self.guild.voice_client.play(source, after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set))
            
            add_song_played(str(item['requester'].id))
            
            if self.loop_mode != 1:
                await self.channel.send(f"🎶 Now playing: **{item['title']}**")
            
            await self.next.wait()
            source.cleanup()

            if self.loop_mode != 1:
                self.history.insert(0, self.current)
                if len(self.history) > 10:
                    self.history.pop()

            if self.loop_mode == 2 and self.current:
                await self.queue.put(self.current)
                self._queue_list.append(self.current)

            if self.loop_mode != 1:
                self.current = None

    def destroy(self, guild):
        return self.bot.loop.create_task(self.cog.cleanup(guild))

class SearchDropdown(discord.ui.Select):
    def __init__(self, entries, player, original_interaction):
        self.entries = entries
        self.player = player
        self.original_interaction = original_interaction
        
        options = []
        for i, entry in enumerate(entries):
            title = entry.get('title', 'Unknown Title')[:90]
            duration = entry.get('duration', 0)
            if duration:
                dur_m, dur_s = divmod(int(duration), 60)
                desc = f"{dur_m}:{dur_s:02d} | {entry.get('uploader', 'Unknown')} "[:100]
            else:
                desc = f"Unknown duration | {entry.get('uploader', 'Unknown')}"[:100]
                
            options.append(discord.SelectOption(label=title, description=desc, value=str(i)))

        super().__init__(placeholder="Choose a track...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        index = int(self.values[0])
        entry = self.entries[index]
        
        item = {
            'url': entry['url'],
            'title': entry.get('title', 'Unknown Title'),
            'duration': entry.get('duration', 0),
            'requester': self.original_interaction.user
        }
        
        await self.player.queue.put(item)
        self.player._queue_list.append(item)
        
        for child in self.view.children:
            child.disabled = True
            
        await interaction.response.edit_message(content=f"✅ Added to queue: **{item['title']}**", view=self.view)

class SearchView(discord.ui.View):
    def __init__(self, entries, player, interaction):
        super().__init__(timeout=60)
        self.add_item(SearchDropdown(entries, player, interaction))

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}

    def get_player(self, interaction: discord.Interaction):
        try:
            player = self.players[interaction.guild.id]
        except KeyError:
            player = MusicPlayer(interaction, self)
            self.players[interaction.guild.id] = player
        return player

    async def cleanup(self, guild):
        try:
            await guild.voice_client.disconnect()
        except AttributeError:
            pass
        try:
            del self.players[guild.id]
        except KeyError:
            pass

    @app_commands.command(name="play", description="Plays a song from YouTube, SoundCloud, or Spotify")
    @app_commands.describe(query="The song to play")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        
        if not interaction.user.voice:
            return await interaction.followup.send("You are not connected to a voice channel.", ephemeral=True)
            
        channel = interaction.user.voice.channel

        if not interaction.guild.voice_client:
            await channel.connect()
        elif interaction.guild.voice_client.channel != channel:
            await interaction.guild.voice_client.move_to(channel)

        player = self.get_player(interaction)

        if not query.startswith('http'):
            search_query = f"scsearch5:{query}"
            
            loop = self.bot.loop
            try:
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=False))
            except Exception as e:
                return await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)
                
            if 'entries' in data and len(data['entries']) > 0:
                entries = data['entries']
                if len(entries) == 1:
                    entry = entries[0]
                else:
                    view = SearchView(entries, player, interaction)
                    return await interaction.followup.send("Select a track from the search results:", view=view)
            else:
                return await interaction.followup.send("❌ No results found.", ephemeral=True)
        else:
            loop = self.bot.loop
            try:
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
            except Exception as e:
                return await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)

            if 'entries' in data:
                entry = data['entries'][0]
            else:
                entry = data

        item = {
            'url': entry['url'],
            'title': entry.get('title', 'Unknown Title'),
            'duration': entry.get('duration', 0),
            'requester': interaction.user
        }

        await player.queue.put(item)
        player._queue_list.append(item)
        await interaction.followup.send(f"✅ Added to queue: **{item['title']}**")

    @app_commands.command(name="skip", description="Skips the current song")
    async def skip(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
            return await interaction.response.send_message("Not playing any music right now.", ephemeral=True)
        
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ Skipped the current song.")

    @app_commands.command(name="pause", description="Pauses the current song")
    async def pause(self, interaction: discord.Interaction):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.pause()
            await interaction.response.send_message("⏸️ Paused the music.")
        else:
            await interaction.response.send_message("Not playing any music right now.", ephemeral=True)

    @app_commands.command(name="resume", description="Resumes the current song")
    async def resume(self, interaction: discord.Interaction):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
            interaction.guild.voice_client.resume()
            await interaction.response.send_message("▶️ Resumed the music.")
        else:
            await interaction.response.send_message("Music is not paused.", ephemeral=True)
            
    @app_commands.command(name="stop", description="Stops music and clears the queue")
    async def stop(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            return await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
            
        player = self.get_player(interaction)
        player.queue._queue.clear()
        player._queue_list.clear()
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏹️ Stopped music and cleared the queue.")

    @app_commands.command(name="queue", description="Shows the current music queue")
    async def queue(self, interaction: discord.Interaction):
        try:
            player = self.players[interaction.guild.id]
        except KeyError:
            return await interaction.response.send_message("Not playing any music right now.", ephemeral=True)
            
        if not player._queue_list:
            return await interaction.response.send_message("The queue is currently empty.", ephemeral=True)
            
        embed = discord.Embed(title=f"Queue for {interaction.guild.name}", color=discord.Color.blue())
        desc = ""
        for i, item in enumerate(player._queue_list[:10]):
            desc += f"**{i+1}.** {item['title']} - Requested by {item['requester'].mention}\n"
            
        if len(player._queue_list) > 10:
            desc += f"\n*...and {len(player._queue_list) - 10} more*"
            
        embed.description = desc
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="history", description="Shows recently played songs")
    async def history(self, interaction: discord.Interaction):
        try:
            player = self.players[interaction.guild.id]
        except KeyError:
            return await interaction.response.send_message("No songs have been played yet.", ephemeral=True)
            
        if not player.history:
            return await interaction.response.send_message("No songs have been played yet.", ephemeral=True)
            
        embed = discord.Embed(title="Recently Played", color=discord.Color.purple())
        desc = ""
        for i, item in enumerate(player.history):
            desc += f"**{i+1}.** {item['title']}\n"
            
        embed.description = desc
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clear", description="Clears the current queue")
    async def clear(self, interaction: discord.Interaction):
        try:
            player = self.players[interaction.guild.id]
        except KeyError:
            return await interaction.response.send_message("Not playing any music right now.", ephemeral=True)
            
        player.queue._queue.clear()
        player._queue_list.clear()
        await interaction.response.send_message("🗑️ Cleared the queue.")

    @app_commands.command(name="shuffle", description="Shuffles the current queue")
    async def shuffle(self, interaction: discord.Interaction):
        try:
            player = self.players[interaction.guild.id]
        except KeyError:
            return await interaction.response.send_message("Not playing any music right now.", ephemeral=True)
            
        if len(player._queue_list) < 2:
            return await interaction.response.send_message("Not enough songs in the queue to shuffle.", ephemeral=True)
            
        random.shuffle(player._queue_list)
        player.queue._queue.clear()
        for item in player._queue_list:
            player.queue.put_nowait(item)
            
        await interaction.response.send_message("🔀 Shuffled the queue.")

    @app_commands.command(name="nowplaying", description="Shows information about the current song")
    async def nowplaying(self, interaction: discord.Interaction):
        try:
            player = self.players[interaction.guild.id]
        except KeyError:
            return await interaction.response.send_message("Not playing any music right now.", ephemeral=True)
            
        if not player.current:
            return await interaction.response.send_message("Not playing anything right now.", ephemeral=True)
            
        embed = discord.Embed(title="Now Playing 🎵", description=f"**{player.current['title']}**", color=discord.Color.green())
        
        elapsed = int(time.time() - player.start_time)
        duration = player.current.get('duration', 0)
        
        if duration > 0:
            progress = int((elapsed / duration) * 20)
            progress = min(max(progress, 0), 19)
            bar = "▬" * progress + "🔘" + "▬" * (20 - progress - 1)
            
            elapsed_m, elapsed_s = divmod(int(elapsed), 60)
            duration_m, duration_s = divmod(int(duration), 60)
            time_str = f"{elapsed_m}:{elapsed_s:02d} / {duration_m}:{duration_s:02d}"
            
            embed.add_field(name="Progress", value=f"```\n{bar}\n{time_str}\n```")
        
        embed.set_footer(text=f"Requested by {player.current['requester'].display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="Changes the player volume")
    @app_commands.describe(level="Volume level from 1 to 100")
    async def volume(self, interaction: discord.Interaction, level: int):
        if level < 1 or level > 100:
            return await interaction.response.send_message("Volume must be between 1 and 100.", ephemeral=True)
            
        try:
            player = self.players[interaction.guild.id]
        except KeyError:
            return await interaction.response.send_message("Not playing any music right now.", ephemeral=True)
            
        if interaction.guild.voice_client and interaction.guild.voice_client.source:
            interaction.guild.voice_client.source.volume = level / 100.0
            
        player.volume = level / 100.0
        await interaction.response.send_message(f"🔊 Volume set to **{level}%**")

    @app_commands.command(name="loop", description="Toggles loop mode")
    @app_commands.describe(mode="0: Off, 1: Track, 2: Queue")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Off", value=0),
        app_commands.Choice(name="Track", value=1),
        app_commands.Choice(name="Queue", value=2),
    ])
    async def loop(self, interaction: discord.Interaction, mode: int):
        try:
            player = self.players[interaction.guild.id]
        except KeyError:
            return await interaction.response.send_message("Not playing any music right now.", ephemeral=True)
            
        player.loop_mode = mode
        modes = {0: "Off", 1: "🔂 Track Loop", 2: "🔁 Queue Loop"}
        await interaction.response.send_message(f"Loop mode set to: **{modes[mode]}**")

async def setup(bot):
    await bot.add_cog(Music(bot))

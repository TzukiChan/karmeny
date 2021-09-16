import discord
from discord import message
from discord import channel
from discord.utils import get
from discord import FFmpegPCMAudio
import youtube_dl
import asyncio
from async_timeout import timeout
from functools import partial
from discord.ext import commands
import itertools
from discord.ext import commands
from discord import Embed

bot = commands.Bot(command_prefix='-') #กำหนด Prefix

youtube_dl.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0' # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    'options': '-vn',
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5" ## song will end if no this line
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):

    def __init__(self, source, *, data, requester):
        super().__init__(source)
        self.requester = requester

        self.title = data.get('title')
        self.web_url = data.get('webpage_url')

        # YTDL info dicts (data) have other useful information you might want
        # https://github.com/rg3/youtube-dl/blob/master/README.md

    def __getitem__(self, item: str):
        """Allows us to access attributes similar to a dict.
        This is only useful when you are NOT downloading.
        """
        return self.__getattribute__(item)

    @classmethod
    async def create_source(cls, ctx, search: str, *, loop, download=False):
        loop = loop or asyncio.get_event_loop()

        to_run = partial(ytdl.extract_info, url=search, download=download)
        data = await loop.run_in_executor(None, to_run)

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        # await ctx.send(f'```ini\n[Added {data["title"]} to the Queue.]\n```') #delete after can be added
        embed=discord.Embed(title= data['title'], url = data['webpage_url'] , description=f"Added to the Queue by {ctx.author}", color=0x70c1b3)
        await ctx.send(embed=embed, delete_after=10)

        if download:
            source = ytdl.prepare_filename(data)
        else:
            return {'webpage_url': data['webpage_url'], 'requester': ctx.author, 'title': data['title']}

        return cls(discord.FFmpegPCMAudio(source, **ffmpeg_options), data=data, requester=ctx.author)

    @classmethod
    async def regather_stream(cls, data, *, loop):
        """Used for preparing a stream, instead of downloading.
        Since Youtube Streaming links expire."""
        loop = loop or asyncio.get_event_loop()
        requester = data['requester']

        to_run = partial(ytdl.extract_info, url=data['webpage_url'], download=False)
        data = await loop.run_in_executor(None, to_run)

        return cls(discord.FFmpegPCMAudio(data['url'], **ffmpeg_options), data=data, requester=requester)

class MusicPlayer:
    """A class which is assigned to each guild using the bot for Music.
    This class implements a queue and loop, which allows for different guilds to listen to different playlists
    simultaneously.
    When the bot disconnects from the Voice it's instance will be destroyed.
    """

    __slots__ = ('bot', '_guild', '_channel', '_cog', 'queue', 'next', 'current', 'np', 'volume')

    def __init__(self, ctx):
        self.bot = ctx.bot
        self._guild = ctx.guild
        self._channel = ctx.channel
        self._cog = ctx.cog

        self.queue = asyncio.Queue()
        self.next = asyncio.Event()

        self.np = None  # Now playing message
        self.volume = .5
        self.current = None

        ctx.bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        """Our main player loop."""
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self.next.clear()

            try:
                # Wait for the next song. If we timeout cancel the player and disconnect...
                async with timeout(300):  # 5 minutes...
                    source = await self.queue.get()
            except asyncio.TimeoutError:
                return await self.destroy(self._guild)

            if not isinstance(source, YTDLSource):
                # Source was probably a stream (not downloaded)
                # So we should regather to prevent stream expiration
                try:
                    source = await YTDLSource.regather_stream(source, loop=self.bot.loop)
                except Exception as e:
                    await self._channel.send(f'There was an error processing your song.\n'
                                             f'```css\n[{e}]\n```')
                    continue

            source.volume = self.volume
            self.current = source

            self._guild.voice_client.play(source, after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set))
            self.np = await self._channel.send(f'**Now Playing:** `{source.title}` requested by 'f'`{source.requester}`')
            await self.next.wait()

            # Make sure the FFmpeg process is cleaned up.
            source.cleanup()
            self.current = None

            try:
                # We are no longer playing this song...
                await self.np.delete()
            except discord.HTTPException:
                pass

    async def destroy(self, guild):
        """Disconnect and cleanup the player."""
        del players[self._guild]
        await self._guild.voice_client.disconnect()
        return self.bot.loop.create_task(self._cog.cleanup(guild))


# wrapper / decorators
@bot.event
async def on_ready() : #เมื่อระบบพร้อมใช้งาน
    print(f"Logged in as {bot.user}")

@bot.command()
async def test(ctx, *, par):
    await ctx.channel.send("You typed {0}".format(par))


# test text
@bot.event
async def on_message(message) : #ดักรอข้อความใน Chat
    await bot.process_commands(message)
    if message.content.startswith('hi') : #เมื่อข้อความในตัวแรกมีคำว่า hi
        await message.channel.send('(^._.^)ﾉ Meow~ ') #ข้อความที่ต้องการตอบกลับ
       
    #ลิงก์เชิญ
    if message.content.startswith('link') :
        await message.channel.send('(^._.^)ﾉ https://bit.ly/3Ei9vmD')


# เช็คสเตตัสคนพิมพ์ (ใช้ได้)
@bot.event
async def getUserVoiceState(ctx):
    try:
        voice_member = ctx.member.voice
    except:
        voice_member = ctx.author.voice

    if voice_member is None:
        await ctx.message.add_reaction('😡')
        await ctx.send('**YOU HAVE TO JOIN VC FIRST!!!**')
        return None
    else:
        return voice_member.channel


# คำสั่งเข้าร่วมvc (ใช้ได้)
@bot.command()
async def join(ctx):
    channel = await getUserVoiceState(ctx)
    voice_client = get(bot.voice_clients, guild=ctx.guild)
    if voice_client == None and channel != None:
        await channel.connect()
    if voice_client and voice_client.is_connected():
        await voice_client.move_to(channel)
        await ctx.channel.send(f"I move to {channel}", delete_after=10)
    

# คำสั่งเล่นเพลง (ใช้ได้)
@bot.command() 
async def play(ctx,* ,search: str):
    channel = await getUserVoiceState(ctx)
    voice_client = get(bot.voice_clients, guild=ctx.guild)


    if voice_client == None and channel != None:
        await channel.connect()
        voice_client = get(bot.voice_clients, guild=ctx.guild)
    
    
    if voice_client.channel != channel:
        await ctx.message.add_reaction('❌')
        await ctx.channel.send("I'm currently connected to ** {0} channel** (=^‥^=)".format(voice_client.channel))
                
    elif voice_client != None and voice_client and voice_client.is_connected():
        await ctx.trigger_typing()
        _player = get_player(ctx)
        source = await YTDLSource.create_source(ctx, search, loop=bot.loop, download=False)

        await _player.queue.put(source)



players = {}
def get_player(ctx):
    try:
        player = players[ctx.guild.id]
    except:
        player = MusicPlayer(ctx)
        players[ctx.guild.id] = player
    
    return player


# คำสั่งหยุดเล่น (ใช้ได้)
@bot.command()
async def stop(ctx):
    channel = ctx.author.voice.channel
    voice_client = get(bot.voice_clients, guild=ctx.guild)

    if voice_client != channel:
        await getUserVoiceState(ctx)

    if voice_client == None:
        await ctx.channel.send("I'm not connected to vc (=ＴェＴ=)")
        return

    if voice_client.channel != channel:
        await ctx.message.add_reaction('❌')
        await ctx.channel.send("I'm currently connected to ** {0} channel** (=^‥^=)".format(voice_client.channel))
        return

    if voice_client != None and voice_client.channel == channel:
        voice_client.stop()
        await ctx.message.add_reaction('✅')
        await ctx.channel.send("~(=^‥^)/ MUSIC STOPS", delete_after=5)

# คำสั่งพัก (ใช้ได้)
@bot.command()
async def pause(ctx):
    channel = ctx.author.voice.channel
    voice_client = get(bot.voice_clients, guild=ctx.guild)

    if voice_client != channel:
        await getUserVoiceState(ctx)

    if voice_client == None:
        await ctx.channel.send("I'm is not connected to vc (=ＴェＴ=)")
        return

    if voice_client.channel != channel:
        await ctx.message.add_reaction('❌')
        await ctx.channel.send("I'm currently connected to ** {0} channel** (=^‥^=)".format(voice_client.channel))
        return

    if voice_client != None and voice_client.channel == channel:
        voice_client.pause()
        await ctx.message.add_reaction('✅')
        await ctx.channel.send("~(=^‥^)/ MUSIC PAUSE", delete_after=5)
    
# คำสั่งเล่นต่อ (ใช้ได้)
@bot.command()
async def resume(ctx):
    channel = ctx.author.voice.channel
    voice_client = get(bot.voice_clients, guild=ctx.guild)

    if voice_client != channel:
        await getUserVoiceState(ctx)

    if voice_client == None:
        await ctx.channel.send("I'm is not connected to vc (=^‥^=)")
        return

    if voice_client.channel != channel:
        await ctx.message.add_reaction('❌')
        await ctx.channel.send("I'm currently connected to ** {0} channel** (=^‥^=)".format(voice_client.channel))
        return

    if voice_client != None and voice_client.channel == channel:
        voice_client.resume()
    await ctx.message.add_reaction('✅')
    await ctx.channel.send("~(=^‥^)/ MUSIC CONTINUES", delete_after=5)

# คำสั่งออกจากvc (ใช้ได้)
@bot.command()
async def leave(ctx):
    voice_client = get(bot.voice_clients, guild=ctx.guild)
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await ctx.message.add_reaction('👋')
        await ctx.channel.send("Bye Bye ヽ(^‥^=ゞ)", delete_after=10)
    else:
        await getUserVoiceState(ctx)

# คำสั่งดูคิว (ใช้ได้)
@bot.command()
async def queue(ctx):
    channel = ctx.author.voice.channel
    voice_client = get(bot.voice_clients, guild=ctx.guild)

    if voice_client != channel:
        await getUserVoiceState(ctx)

    if voice_client == None or not voice_client.is_connected():
        await ctx.channel.send("I'm not connected to vc (=ＴェＴ=)", delete_after=10)
        return
    
    player = get_player(ctx)
    if player.queue.empty():
        return await ctx.send('The queue is EMPTY (=^‥^=)')
    
    # 1 2 3
    if voice_client != None and voice_client.channel == channel:
        upcoming = list(itertools.islice(player.queue._queue,0,player.queue.qsize()))
        
        fmt = '\n'.join(f'**`{_["title"]}`**' for _ in upcoming)
        embed = discord.Embed(title=f'There are {len(upcoming)} songs in the queue.', description=fmt)
        await ctx.send(embed=embed, delete_after=300)



# คำสั่งข้ามเพลง (ใช้ได้)
@bot.command()
async def skip(ctx):
    channel = ctx.author.voice.channel
    voice_client = get(bot.voice_clients, guild=ctx.guild)
    if voice_client != channel:
        await getUserVoiceState(ctx)

    if voice_client == None or not voice_client.is_connected():
        await ctx.channel.send("I'm not connected to vc (=ＴェＴ=)", delete_after=10)
        return

    if voice_client.channel != channel:
        await ctx.message.add_reaction('❌')
        await ctx.channel.send("I'm currently connected to ** {0} channel** (=^‥^=)".format(voice_client.channel))
        return
    
    if voice_client.is_paused():
        pass
    elif not voice_client.is_playing():
        return
    elif voice_client.is_playing():
        voice_client.stop()
        await ctx.message.add_reaction('✅')
        await ctx.send('~(=^‥^)/ SKIP SUCCESSFULLY ', delete_after=5)









bot.run('ODYxOTA2NTcwNTc1ODcyMDEw.YOQnCw.tisousxHAEu40Fh72qfJpazJrmI') #รันบอท (โดยนำ TOKEN จากบอทที่เราสร้างไว้นำมาวาง)
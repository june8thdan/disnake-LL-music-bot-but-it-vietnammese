# -*- coding: utf-8 -*-
import datetime
import json
import pprint
import traceback
import asyncio
from typing import Union, Optional
from random import shuffle

import aiofiles
import aiohttp
import disnake
import psutil
from aiohttp import ClientConnectorCertificateError
from disnake.ext import commands

import wavelink

from utils.client import BotCore
from utils.db import DBModel
from utils.music.errors import GenericError, MissingVoicePerms, NoVoice, PoolException, parse_error, EmptyFavIntegration
from utils.music.spotify import process_spotify, spotify_regex_w_user
from utils.music.checks import check_voice, has_player, has_source, is_requester, is_dj, \
    can_send_message_check, check_requester_channel, can_send_message, can_connect, check_deafen, check_pool_bots, \
    check_channel_limit, check_stage_topic
from utils.music.models import LavalinkPlayer, LavalinkTrack, LavalinkPlaylist
from utils.music.converters import time_format, fix_characters, string_to_seconds, URL_REG, \
    YOUTUBE_VIDEO_REG, google_search, percentage, music_source_image, perms_translations
from utils.music.interactions import VolumeInteraction, QueueInteraction, SelectInteraction
from utils.others import check_cmd, send_idle_embed, CustomContext, PlayerControls, fav_list, queue_track_index, \
    pool_command, string_to_file, CommandArgparse, music_source_emoji_url
from user_agent import generate_user_agent


class Music(commands.Cog):

    emoji = "🎶"
    name = "Âm nhạc"
    desc_prefix = f"[{emoji} {name}] | "

    search_sources_opts = [
        disnake.OptionChoice("Youtube", "ytsearch"),
        disnake.OptionChoice("Youtube Music", "ytmsearch"),
        disnake.OptionChoice("Soundcloud", "scsearch"),
    ]

    playlist_opts = [
        disnake.OptionChoice("Misturar Playlist", "shuffle"),
        disnake.OptionChoice("Inverter Playlist", "reversed"),
    ]

    sources = {
        "yt": "ytsearch",
        "y": "ytsearch",
        "ytb": "ytsearch",
        "youtube": "ytsearch",
        "ytm": "ytmsearch",
        "ytmsc": "ytmsearch",
        "ytmusic": "ytmsearch",
        "youtubemusic": "ytmsearch",
        "sc": "scsearch",
        "scd": "scsearch",
        "soundcloud": "scsearch",
    }

    audio_formats = ("audio/mpeg", "audio/ogg", "audio/mp4", "audio/aac")

    u_agent = generate_user_agent()

    def __init__(self, bot: BotCore):

        self.bot = bot

        self.extra_hints = bot.config["EXTRA_HINTS"].split("||")

        self.song_request_concurrency = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

        self.player_interaction_concurrency = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

        self.song_request_cooldown = commands.CooldownMapping.from_cooldown(rate=1, per=300,
                                                                            type=commands.BucketType.member)

        self.music_settings_cooldown = commands.CooldownMapping.from_cooldown(rate=3, per=15,
                                                                              type=commands.BucketType.guild)

        if self.bot.config["AUTO_ERROR_REPORT_WEBHOOK"]:
            self.error_report_queue = asyncio.Queue()
            self.error_report_task = bot.loop.create_task(self.error_report_loop())
        else:
            self.error_report_queue = None

    async def update_cache(self):

        async with aiofiles.open("./playlist_cache.json", "w") as f:
            await f.write(json.dumps(self.bot.pool.playlist_cache))

    @commands.is_owner()
    @commands.command(hidden=True, aliases=["ac"])
    async def addcache(self, ctx: CustomContext, url: str):

        url = url.strip("<>")

        async with ctx.typing():
            tracks, node = await self.get_tracks(url, ctx.author, use_cache=False)

        tracks_info = []

        try:
            tracks = tracks.tracks
        except AttributeError:
            pass

        for t in tracks:
            tinfo = {"track": t.id, "info": t.info}
            tinfo["info"]["extra"]["playlist"] = {"name": t.playlist_name, "url": t.playlist_url}
            tracks_info.append(tinfo)

        self.bot.pool.playlist_cache[url] = tracks_info

        await self.update_cache()

        await ctx.send("Các bài hát liên kết đã được thêm thành công trong bộ nhớ cache.", delete_after=30)

    @commands.is_owner()
    @commands.cooldown(1, 300, commands.BucketType.default)
    @commands.command(hidden=True, aliases=["uc"])
    async def updatecache(self, ctx: CustomContext, *args):

        if "-fav" in args:
            try:
                data = ctx.global_user_data
            except AttributeError:
                data = await self.bot.get_global_data(ctx.author.id, db_name=DBModel.users)
                ctx.global_user_data = data

            self.bot.pool.playlist_cache.update({url: [] for url in data["fav_links"].values()})

        try:
            if not self.bot.pool.playlist_cache:
                raise GenericError("**Bộ nhớ cache danh sách phát của bạn trống...**")
        except KeyError:
            raise GenericError(f"**Bạn chưa sử dụng lệnh: {ctx.prefix}{self.addcache.name}**")

        msg = None

        counter = 0

        amount = len(self.bot.pool.playlist_cache)

        txt = ""

        for url in list(self.bot.pool.playlist_cache):

            try:
                async with ctx.typing():
                    tracks, node = await self.get_tracks(url, ctx.author, use_cache=False)
            except:
                traceback.print_exc()
                tracks = None
                try:
                    del self.bot.pool.playlist_cache[url]
                except:
                    pass

            if not tracks:
                txt += f"[`❌ thất bại`]({url})\n"

            else:

                tracks_info = []

                try:
                    tracks = tracks.tracks
                except AttributeError:
                    pass

                for t in tracks:
                    tinfo = {"track": t.id, "info": t.info}
                    tinfo["info"]["extra"]["playlist"] = {"name": t.playlist_name, "url": t.playlist_url}
                    tracks_info.append(tinfo)

                self.bot.pool.playlist_cache[url] = tracks_info

                txt += f"[`{tracks_info[0]['info']['extra']['playlist']['name']}`]({url})\n"

            counter += 1

            embed = disnake.Embed(
                description=txt, color=self.bot.get_color(ctx.guild.me),
                title=f"Danh sách phát được xác minh: {counter}/{amount}"
            )

            if not msg:
                msg = await ctx.send(embed=embed)
            else:
                await msg.edit(embed=embed)

        await self.update_cache()

    @commands.is_owner()
    @commands.command(hidden=True, aliases=["rc"])
    async def removecache(self, ctx: CustomContext, url: str):

        try:
            del self.bot.pool.playlist_cache[url]
        except KeyError:
            raise GenericError("**Không có mục nào được lưu trong bộ nhớ cache với URL thông tin...**")

        await self.update_cache()

        await ctx.send("Các bài hát liên kết đã được xóa thành công khỏi bộ đệm.", delete_after=30)

    @commands.is_owner()
    @commands.command(hidden=True, aliases=["cc"])
    async def clearcache(self, ctx: CustomContext):

        try:
            self.bot.pool.playlist_cache.clear()
        except KeyError:
            raise GenericError("**Bạn đã không lưu các liên kết danh sách phát trong bộ đệm...**")

        await self.update_cache()

        await ctx.send("Bộ đệm danh sách phát đã được làm sạch thành công.", delete_after=30)

    @commands.is_owner()
    @commands.command(hidden=True, aliases=["ec"])
    async def exportcache(self, ctx: CustomContext):

        await ctx.send(file=disnake.File("playlist_cache.json"))

    @commands.is_owner()
    @commands.command(hidden=True, aliases=["ic"])
    async def importcache(self, ctx: CustomContext, url: str):

        async with ctx.typing():
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as r:
                    self.bot.pool.playlist_cache.update(json.loads((await r.read()).decode('utf-8')))

        await self.update_cache()

        await ctx.send("Tệp bộ nhớ cache đã được nhập thành công!", delete_after=30)

    stage_cd = commands.CooldownMapping.from_cooldown(2, 45, commands.BucketType.guild)
    stage_mc = commands.MaxConcurrency(1, per=commands.BucketType.guild, wait=False)

    @has_source()
    @commands.has_guild_permissions(manage_guild=True)
    @pool_command(
        only_voiced=True, name="stageannounce", aliases=["stagevc", "togglestageannounce"], hidden=True,
        description="Kích hoạt hệ thống thông báo sân khấu tự động với tên của bài hát.",
        cooldown=stage_cd, max_concurrency=stage_mc, extras={"exclusive_cooldown": True},
    )
    async def stageannounce_legacy(self, ctx: CustomContext, *, template: str = None):

        await self.stage_announce.callback(self=self, inter=ctx, template=template)

    @has_source()
    @commands.slash_command(
        description=f"{desc_prefix}Kích hoạt/chỉnh sửa hệ thống thông báo sân khấu tự động với tên của bài hát.",
        extras={"only_voiced": True, "exclusive_cooldown": True},
        default_member_permissions=disnake.Permissions(manage_guild=True), cooldown=stage_cd, max_concurrency=stage_mc
    )
    async def stage_announce(
            self,
            inter: disnake.AppCmdInter,
            template: str = commands.Param(
                name=disnake.Localized("template", data={disnake.Locale.pt_BR: "modelo"}),
                description=f"{desc_prefix}Kích hoạt hệ thống thông báo sân khấu tự động với tên của bài hát."
            )
    ):

        try:
            bot = inter.music_bot
            guild = inter.music_guild
        except AttributeError:
            bot = inter.bot
            guild = inter.guild

        if not isinstance(guild.me.voice.channel, disnake.StageChannel):
            raise GenericError("**Bạn phải ở trên một kênh sân khấu để kích hoạt/vô hiệu hóa hệ thống này.**")

        if not guild.me.guild_permissions.manage_guild:
            raise GenericError(f"{bot.user.mention} không có  cho phép của: **{perms_translations['manage_guild']}.**")

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if not template:
            template = player.stage_title_template

        elif not any(p in template for p in (
                '{track.title}', '{track.author}', '{track.duration}', '{track.source}', '{track.playlist}',
                '{requester.name}', '{requester.tag}', '{requester.id}'
        )):
            raise GenericError(
                "**Bạn nên sử dụng ít nhất một trình giữ chỗ hợp lệ trong tin nhắn.**\n\n"
                "**PLACEHOLDERS:** ```ansi\n"
                "[34;1m{track.title}[0m -> Tên của bài hát\n"
                "[34;1m{track.author}[0m -> Nghệ sĩ/người tải lên/tên tác giả.\n"
                "[34;1m{track.duration}[0m -> Thời lượng của âm nhạc.\n"
                "[34;1m{track.source}[0m -> Nguồn gốc/nguồn âm nhạc (YouTube/Spotify/SoundCloud, v.v.)\n"
                "[34;1m{track.playlist}[0m -> Tên của danh sách phát nguồn âm nhạc (nếu bạn có)\n"
                "[34;1m{requester.name}[0m -> Tên/Nick của thành viên đã đặt hàng âm nhạc\n"
                "[34;1m{requester.tag}[0m -> Tag/phân biệt đối xử của thành viên đã đặt hàng âm nhạc\n"
                "[34;1m{requester.id}[0m -> ID của thành viên đã yêu cầu âm nhạc\n```"
            )

        if player.stage_title_event and player.stage_title_template == template:

            raise GenericError("**Thông báo tự động của giai đoạn đã được kích hoạt (và không có thay đổi nào trong "
                               "Mẫu tiêu đề).\n"
                               "Nếu bạn muốn vô hiệu hóa, bạn có thể dừng người chơi (tất cả các thành viên giai đoạn sẽ"
                               "tự động ngắt kết nối trong quá trình này).**")

        player.stage_title_event = True
        player.stage_title_template = template
        player.start_time = disnake.utils.utcnow()

        txt = [f"Đã kích hoạt/thay đổi hệ thống thông báo sân khấu tự động.",
               f"📢 **⠂{inter.author.mention} đã kích hoạt/thay đổi hệ thống thông báo sân khấu tự động"
               f"{guild.me.voice.channel.mention}.**\n\n"
               f"`Lưu ý: Nếu người chơi bị tắt, tất cả các thành viên giai đoạn sẽ được ngắt kết nối tự động.`\n\n"
               f"**Mô hình đã sử dụng:** `{disnake.utils.escape_markdown(template)}`"]

        await self.interaction_message(inter, txt, emoji="📢", force=True)

    @stage_announce.autocomplete("template")
    async def stage_announce_autocomplete(self, inter: disnake.Interaction, query: str):

        return [
            "Đang chơi: {track.title} | {track.author}",
            "{track.title} | Được yêu cầu bởi: {requester.name}#{requester.tag}",
            "Đài 24/7 | {track.title}",
            "{track.title} | Danh sách phát: {track.playlist}",
        ]

    play_cd = commands.CooldownMapping.from_cooldown(3, 12, commands.BucketType.member)
    play_mc = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)


    @stage_announce.autocomplete("template")
    async def stage_announce_autocomplete(self, inter: disnake.Interaction, query: str):

        return [
            "Đang chơi: {track.title} | {track.author}",
            "{track.title} | Được yêu cầu bởi: {requester.name}#{requester.tag}",
            "Đài 24/7 | {track.title}",
            "{track.title} | Danh sách phát: {track.playlist}",
        ]

    play_cd = commands.CooldownMapping.from_cooldown(3, 12, commands.BucketType.member)
    play_mc = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @check_voice()
    @can_send_message_check()
    @commands.message_command(name="add to queue", extras={"check_player": False},
                              cooldown=play_cd, max_concurrency=play_mc)
    async def message_play(self, inter: disnake.MessageCommandInteraction):

        if not inter.target.content:
            emb = disnake.Embed(description=f"Không có văn bản trong [Tin nhắn]({inter.target.jump_url}) đã chọn..",
                                color=disnake.Colour.red())
            await inter.send(embed=emb, ephemeral=True)
            return

        await self.play.callback(
            self=self,
            inter=inter,
            query=inter.target.content,
            position=0,
            options="",
            manual_selection=False,
            source="ytsearch",
            repeat_amount=0,
            force_play="no",
        )

    @check_voice()
    @can_send_message_check()
    @commands.slash_command(name="search", extras={"check_player": False}, cooldown=play_cd, max_concurrency=play_mc,
                            description=f"{desc_prefix}Tìm kiếm âm nhạc và chọn một giữa các kết quả để chơi.")
    async def search(
            self,
            inter: disnake.AppCmdInter,
            query: str = commands.Param(name="search", desc="Tên hoặc liên kết bài hát."),
            *,
            position: int = commands.Param(name="position", description=f"{desc_prefix}Đặt âm nhạc ở một vị trí cụ thể",
                                           default=0),
            force_play: str = commands.Param(
                name="play_now",
                description="Phát nhạc ngay lập tức (thay vì thêm vào hàng đợi).",
                default="no",
                choices=[
                    disnake.OptionChoice(disnake.Localized("Yes", data={disnake.Locale.pt_BR: "Sim"}), "yes"),
                    disnake.OptionChoice(disnake.Localized("No", data={disnake.Locale.pt_BR: "Não"}), "no")
                ]
            ),
            options: str = commands.Param(name="option", description="Tùy chọn xử lý danh sách phát",
                                          choices=playlist_opts, default=False),
            source: str = commands.Param(name="source",
                                         description="Chọn Trang web để tìm kiếm âm nhạc (không có liên kết)",
                                         choices=search_sources_opts,
                                         default="ytsearch"),
            repeat_amount: int = commands.Param(name="repeat", description="Lặp lại.",
                                                default=0),
            server: str = commands.Param(name="server", desc="Sử dụng một máy chủ âm nhạc cụ thể",
                                         default=None)
    ):

        await self.play.callback(
            self=self,
            inter=inter,
            query=query,
            position=position,
            force_play=force_play,
            options=options,
            manual_selection=True,
            source=source,
            repeat_amount=repeat_amount,
            server=server
        )

    @search.autocomplete("search")
    async def search_autocomplete(self, inter: disnake.Interaction, current: str):

        if not current:
            return []

        if URL_REG.match(current):
            return [current] if len(current) < 100 else []

        try:
            await check_pool_bots(inter, only_voiced=True)
            bot = inter.music_bot
        except GenericError:
            return [current[:99]]
        except:
            bot = inter.bot

        try:
            if not inter.author.voice:
                return []
        except AttributeError:
            return [current[:99]]

        return await google_search(bot, current)

    @is_dj()
    @has_player()
    @can_send_message_check()
    @commands.max_concurrency(1, commands.BucketType.guild)
    @commands.slash_command(
        extras={"only_voiced": True},
        description=f"{desc_prefix}Kết nối (hoặc chuyển sang) một kênh thoại."
    )
    async def connect(
            self,
            inter: disnake.AppCmdInter,
            channel: Union[disnake.VoiceChannel, disnake.StageChannel] = commands.Param(
                name="kênh",
                description="Kênh để kết nối"
            )
    ):
        try:
            channel = inter.music_bot.get_channel(channel.id)
        except AttributeError:
            pass

        await self.do_connect(inter, channel)

    async def do_connect(
            self,
            ctx: Union[disnake.AppCmdInter, commands.Context, disnake.Message],
            channel: Union[disnake.VoiceChannel, disnake.StageChannel] = None,
            check_other_bots_in_vc: bool = False,
            bot: BotCore = None,
            me: disnake.Member = None,
            check_pool: bool = True,
    ):

        if not channel:
            try:
                channel = ctx.music_bot.get_channel(ctx.author.voice.channel.id) or ctx.author.voice.channel
            except AttributeError:
                channel = ctx.author.voice.channel

        if not bot:
            try:
                bot = ctx.music_bot
            except AttributeError:
                bot = self.bot

        if not me:
            try:
                me = ctx.music_guild.me
            except AttributeError:
                me = ctx.guild.me

        try:
            guild_id = ctx.guild_id
        except AttributeError:
            guild_id = ctx.guild.id

        try:
            text_channel = ctx.music_bot.get_channel(ctx.channel.id)
        except AttributeError:
            text_channel = ctx.channel

        try:
            player = bot.music.players[guild_id]
        except KeyError:
            print(f"Player debug test 20: {bot.user} | {self.bot.user}")
            raise GenericError(
                f"**O player do bot {bot.user.mention} foi finalizado antes de conectar no canal de voz "
                f"(ou o player não foi inicializado)...\nPor via das dúvidas tente novamente.**"
            )

        can_connect(channel, me.guild, check_other_bots_in_vc=check_other_bots_in_vc, bot=bot)

        deafen_check = True

        if isinstance(ctx, disnake.AppCmdInter) and ctx.application_command.name == self.connect.name:

            perms = channel.permissions_for(me)

            if not perms.connect or not perms.speak:
                raise MissingVoicePerms(channel)

            await player.connect(channel.id, self_deaf=True)

            if channel != me.voice and me.voice.channel:
                txt = [
                    f"me moveu para o canal <#{channel.id}>",
                    f"**Movido com sucesso para o canal** <#{channel.id}>"
                ]

                deafen_check = False


            else:
                txt = [
                    f"me conectou no canal <#{channel.id}>",
                    f"**Conectei no canal** <#{channel.id}>"
                ]

            await self.interaction_message(ctx, txt, emoji="🔈", rpc_update=True)

        else:
            await player.connect(channel.id, self_deaf=True)

        try:
            player.members_timeout_task.cancel()
        except:
            pass

        if deafen_check and bot.config["GUILD_DEAFEN_WARN"]:

            retries = 0

            while retries < 5:

                if me.voice:
                    break

                await asyncio.sleep(1)
                retries += 0

            if not await check_deafen(me):
                await text_channel.send(
                    embed=disnake.Embed(
                        title="Aviso:",
                        description="Para manter sua privacidade e me ajudar a economizar "
                                    "recursos, recomendo desativar meu áudio do canal clicando "
                                    "com botão direito sobre mim e em seguida marcar: desativar "
                                    "áudio no servidor.",
                        color=self.bot.get_color(me),
                    ).set_image(
                        url="https://cdn.discordapp.com/attachments/554468640942981147/1012533546386210956/unknown.png"
                    ), delete_after=20
                )

        if isinstance(channel, disnake.StageChannel):

            while not me.voice:
                await asyncio.sleep(1)

            stage_perms = channel.permissions_for(me)

            if stage_perms.mute_members:
                await me.edit(suppress=False)
            else:
                embed = disnake.Embed(color=self.bot.get_color(me))

                embed.description = f"**Preciso que algum staff me convide para falar no palco: " \
                                    f"[{channel.name}]({channel.jump_url}).**"

                embed.set_footer(
                    text="💡 Dica: para me permitir falar no palco automaticamente será necessário me conceder "
                         "permissão de silenciar membros (no servidor ou apenas no canal de palco escolhido).")

                await text_channel.send(ctx.author.mention, embed=embed, delete_after=45)

    @can_send_message_check()
    @check_voice()
    @commands.bot_has_guild_permissions(send_messages=True)
    @commands.max_concurrency(1, commands.BucketType.member)
    @pool_command(name="addposition", description="Thêm âm nhạc ở một vị trí cụ thể trong hàng đợi.",
                  aliases=["adp", "addpos"], check_player=False, cooldown=play_cd, max_concurrency=play_mc,
                  usage="{prefix}{cmd} [posição(Nº)] [nome|link]\nEx: {prefix}{cmd} 2 sekai - burn me down")
    async def addpos_legacy(self, ctx: CustomContext, position: int, *, query: str):

        if position < 1:
            raise GenericError("**Số vị trí hàng đợi phải từ 1 trở lên.**")

        await self.play.callback(self=self, inter=ctx, query=query, position=position, options=False,
                                 force_play="no", manual_selection=False,
                                 source="ytsearch", repeat_amount=0, server=None)

    play_flags = CommandArgparse()
    play_flags.add_argument('query', nargs='*', help="nome ou link da música")
    play_flags.add_argument('-position', '-pos', '-p', type=int, default=0, help='Colocar a música em uma posição específica.\nEx: -p 10')
    play_flags.add_argument('-next', '-proximo', action='store_true', help='Adicionar a música/playlist no topo da fila (equivalente ao: -pos 1)')
    play_flags.add_argument('-reverse', '-r', action='store_true', help='Inverter a ordem das músicas adicionadas (efetivo apenas ao adicionar playlist).')
    play_flags.add_argument('-shuffle', '-sl', action='store_true', help='Misturar as músicas adicionadas (efetivo apenas ao adicionar playlist).')
    play_flags.add_argument('-select', '-s', action='store_true', help='Escolher a música entre os resultados encontrados.')
    play_flags.add_argument('-source', '-scr', type=str, default="ytsearch", help='Fazer a busca da música usando uma fonte específica [youtube/soundcloud etc]')
    play_flags.add_argument('-force', '-now', '-n', '-f', action='store_true', help='Tocar a música adicionada imediatamente (efetivo apenas se houver uma música tocando atualmente.)')
    play_flags.add_argument('-loop', '-lp', type=int, default=0, help="Definir a quantidade de repetições da música escolhida.\nEx: -loop 5")
    play_flags.add_argument('-server', '-sv', type=str, default=None, help='Usar um servidor de música específico.')

    @can_send_message_check()
    @check_voice()
    @commands.bot_has_guild_permissions(send_messages=True)
    @commands.max_concurrency(1, commands.BucketType.member)
    @pool_command(name="play", description="Tocar música em um canal de voz.", aliases=["p"], check_player=False,
                  cooldown=play_cd, max_concurrency=play_mc, extras={"flags": play_flags},
                  usage="{prefix}{cmd} [nome|link]\nEx: {prefix}{cmd} sekai - burn me down")
    async def play_legacy(self, ctx: CustomContext, *, flags: str = ""):

        args, unknown = ctx.command.extras['flags'].parse_known_args(flags.split())

        await self.play.callback(
            self = self,
            inter = ctx,
            query = " ".join(args.query + unknown),
            position= 1 if args.next else args.position if args.position > 0 else 0,
            options = "shuffle" if args.shuffle else "reversed" if args.reverse else None,
            force_play = "yes" if args.force else "no",
            manual_selection = args.select,
            source = self.sources.get(args.source, "ytsearch"),
            repeat_amount = args.loop,
            server = args.server
        )

    @can_send_message_check()
    @check_voice()
    @commands.bot_has_guild_permissions(send_messages=True)
    @pool_command(name="search", description="Tìm kiếm âm nhạc và chọn một giữa các kết quả để chơi.",
                  aliases=["sc"], check_player=False, cooldown=play_cd, max_concurrency=play_mc,
                  usage="{prefix}{cmd} [nome]\nEx: {prefix}{cmd} sekai - burn me down")
    async def search_legacy(self, ctx: CustomContext, *, query):

        await self.play.callback(self=self, inter=ctx, query=query, position=0, options=False, force_play="no",
                                 manual_selection=True, source="ytsearch", repeat_amount=0, server=None)

    @can_send_message_check()
    @check_voice()
    @commands.slash_command(
        name="play_music_file",
        description=f"{desc_prefix}Phát tập tin nhạc trên kênh thoại.",
        extras={"check_player": False}, cooldown=play_cd, max_concurrency=play_mc
    )
    async def play_file(
            self,
            inter: Union[disnake.AppCmdInter, CustomContext],
            file: disnake.Attachment = commands.Param(
                name="file", description="Tệp âm thanh để phát hoặc thêm xếp hàng"
            ),
            position: int = commands.Param(name="position", description="Đặt âm nhạc ở một vị trí cụ thể",
                                           default=0),
            force_play: str = commands.Param(
                name="play_now",
                description="Phát bài hát ngay lập tức (thay vì thêm vào hàng đợi).",
                default="no",
                choices=[
                    disnake.OptionChoice(disnake.Localized("Yes", data={disnake.Locale.pt_BR: "Sim"}), "yes"),
                    disnake.OptionChoice(disnake.Localized("No", data={disnake.Locale.pt_BR: "Não"}), "no")
                ]
            ),
            repeat_amount: int = commands.Param(name="repeat", description="Lặp lại .",
                                                default=0),
            server: str = commands.Param(name="server", desc="Sử dụng một máy chủ âm nhạc cụ thể trong tìm kiếm.",
                                         default=None),
    ):

        class DummyMessage:
            attachments = [file]

        inter.message = DummyMessage()

        await self.play.callback(self=self, inter=inter, query="", position=position, options=False, force_play=force_play,
                                 manual_selection=False, source="ytsearch", repeat_amount=repeat_amount, server=server)

    @can_send_message_check()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Phát nhạc trên kênh giọng nói.",
        extras={"check_player": False}, cooldown=play_cd, max_concurrency=play_mc
    )
    async def play(
            self,
            inter: Union[disnake.AppCmdInter, CustomContext],
            query: str = commands.Param(name="search", desc="Tên hoặc liên kết âm nhạc."), *,
            position: int = commands.Param(name="position", description="Đặt âm nhạc ở một vị trí cụ thể",
                                           default=0),
            force_play: str = commands.Param(
                name="play_now",
                description="Phát bài hát ngay lập tức (thay vì thêm vào dòng).",
                default="no",
                choices=[
                    disnake.OptionChoice(disnake.Localized("Yes", data={disnake.Locale.pt_BR: "Sim"}), "yes"),
                    disnake.OptionChoice(disnake.Localized("No", data={disnake.Locale.pt_BR: "Não"}), "no")
                ]
            ),
            manual_selection: bool = commands.Param(name="select_manual",
                                                    description="Chọn một bài hát theo cách thủ công giữa các kết quả được tìm thấy",
                                                    default=False),
            options: str = commands.Param(name="option", description="Tùy chọn xử lý danh sách phát",
                                          choices=playlist_opts, default=False),
            source: str = commands.Param(name="source",
                                         description="Chọn Trang web để tìm kiếm âm nhạc (không có liên kết)",
                                         choices=search_sources_opts,
                                         default="ytsearch"),
            repeat_amount: int = commands.Param(name="repeat", description="Đặt số lượng lặp lại.",
                                                default=0),
            server: str = commands.Param(name="server", desc="Sử dụng một máy chủ âm nhạc cụ thể trong tìm kiếm.",
                                         default=None),
    ):

        try:
            bot = inter.music_bot
            guild = inter.music_guild
            channel = bot.get_channel(inter.channel.id)
        except AttributeError:
            bot = inter.bot
            guild = inter.guild
            channel = inter.channel

        can_send_message(channel, bot.user)

        if not guild.voice_client and not check_channel_limit(guild.me, inter.author.voice.channel):
            raise GenericError(f"**Kênh {inter.author.voice.channel.mention} nó đầy rồi!**")

        msg = None

        ephemeral = None

        warn_message = None

        attachment: Optional[disnake.Attachment] = None

        try:
            voice_channel = bot.get_channel(inter.author.voice.channel.id)
        except AttributeError:
            raise NoVoice()

        try:
            player = bot.music.players[guild.id]

            if not server:
                node = player.node
            else:
                node = bot.music.get_node(server) or player.node

            guild_data = {}

        except KeyError:

            node = bot.music.get_node(server)

            if not node:
                node = await self.get_best_node(bot)

            guild_data = None

            if inter.bot == bot:
                try:
                    guild_data = inter.guild_data
                except AttributeError:
                    guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)
                    try:
                        inter.guild_data = guild_data
                    except AttributeError:
                        pass

            if not guild_data:
                guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)

            if not guild.me.voice:
                can_connect(voice_channel, guild, guild_data["check_other_bots_in_vc"], bot=bot)

            static_player = guild_data['player_controller']

            if not inter.response.is_done():
                ephemeral = await self.is_request_channel(inter, data=guild_data, ignore_thread=True)
                await inter.response.defer(ephemeral=ephemeral)

            if static_player['channel']:
                channel, warn_message = await self.check_channel(guild_data, inter, channel, guild, bot)

        if ephemeral is None:
            ephemeral = await self.is_request_channel(inter, data=guild_data, ignore_thread=True)

        is_pin = None

        if not query:

            if self.bot.config["ENABLE_DISCORD_URLS_PLAYBACK"]:

                try:
                    attachment = inter.message.attachments[0]

                    if attachment.size > 18000000:
                        raise GenericError("**Tệp bạn đã gửi phải có kích thước từ 18mb trở xuống.**")

                    if attachment.content_type not in self.audio_formats:
                        raise GenericError("**Tệp bạn đã gửi không phải là một tệp nhạc hợp lệ...**")

                    query = attachment.url

                except IndexError:
                    pass

        if not query:

            try:
                user_data = inter.global_user_data
            except:
                user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
                inter.global_user_data = user_data

            db_favs = {}

            for k, v in user_data["integration_links"].items():
                db_favs[f"> itg: {k}"] = v

            for k, v in user_data["fav_links"].items():
                db_favs[f"> fav: {k}"] = v

            if not db_favs:
                raise EmptyFavIntegration()

            if len(db_favs) == 1:
                query = list(db_favs)[0]

            else:
                embed = disnake.Embed(
                    color=self.bot.get_color(guild.me),
                    description="**Chọn một yêu thích hoặc tích hợp dưới đây:**\n"
                                f'Lưu ý: bạn chỉ có <t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=45)).timestamp())}:R> chọn!'
                )

                try:
                    if bot.user.id != self.bot.user.id:
                        embed.set_footer(text=f"Sử dụng {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
                except AttributeError:
                    pass

                kwargs = {
                    "content": inter.author.mention,
                    "embed": embed
                }

                view = SelectInteraction(
                    user=inter.author,  timeout=45,
                    opts=[disnake.SelectOption(label=k, value=k, emoji=music_source_emoji_url(v)) for k, v in db_favs.items()]
                )

                if isinstance(inter, disnake.MessageInteraction) and not inter.response.is_done():
                    await inter.response.defer(ephemeral=ephemeral)

                try:
                    msg = await inter.followup.send(ephemeral=ephemeral, view=view, wait=True, **kwargs)
                except (disnake.InteractionTimedOut, AttributeError):
                    msg = await inter.channel.send(view=view, **kwargs)

                await view.wait()

                select_interaction = view.inter

                if not select_interaction or view.selected is False:

                    text = "### Thời gian lựa chọn được chọn!" if view.selected is not False else "### Bị người dùng hủy bỏ."

                    try:
                        await msg.edit(embed=disnake.Embed(description=text, color=self.bot.get_color(guild.me)), view=None)
                    except AttributeError:
                        traceback.print_exc()
                        pass
                    return

                if select_interaction.data.values[0] == "cancel":
                    await msg.edit(
                        embed=disnake.Embed(
                            description="**Hủy bỏ lựa chọn!**",
                            color=self.bot.get_color(guild.me)
                        ),
                        components=None
                    )
                    return

                try:
                    inter.store_message = msg
                except AttributeError:
                    pass

                inter.token = select_interaction.token
                inter.id = select_interaction.id
                inter.response = select_interaction.response
                query = select_interaction.data.values[0]

        if query.startswith("> pin: "):
            is_pin = True
            query = query[7:]

        if query.startswith(("> fav: ", "> itg: ")):
            try:
                user_data = inter.global_user_data
            except AttributeError:
                user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
                inter.global_user_data = user_data

            if query.startswith("> fav:"):
                query = user_data["fav_links"][query[7:]]

            else:

                query = user_data["integration_links"][query[7:]]

                if (matches := spotify_regex_w_user.match(query)):

                    if not self.bot.spotify:
                        raise GenericError("**Hỗ trợ Spotify không có sẵn...**")

                    url_type, user_id = matches.groups()

                    if url_type != "user":
                        raise GenericError("**Liên kết không được hỗ trợ bằng phương pháp này...**")

                    try:
                        await inter.response.defer(ephemeral=True)
                    except:
                        pass

                    result = await self.bot.spotify.get_user_playlists(user_id)

                    info = {"entries": [{"title": t.name, "url": t.external_urls["spotify"]} for t in result]}

                elif not self.bot.config["USE_YTDL"]:
                    raise GenericError("**Không có hỗ trợ cho loại yêu cầu này vào lúc này...**")

                else:

                    loop = self.bot.loop or asyncio.get_event_loop()

                    try:
                        await inter.response.defer(ephemeral=True)
                    except:
                        pass

                    info = await loop.run_in_executor(None, lambda: self.bot.pool.ytdl.extract_info(query, download=False))

                    try:
                        if not info["entries"]:
                            raise GenericError(f"**Nội dung không khả dụng (hoặc riêng tư):**\n{query}")
                    except KeyError:
                        raise GenericError("**Xảy ra lỗi khi cố gắng nhận kết quả cho tùy chọn đã chọn...**")

                if len(info["entries"]) == 1:
                    query = info["entries"][0]['url']

                else:

                    emoji = music_source_emoji_url(query)

                    view = SelectInteraction(
                        user=inter.author,
                        opts=[
                            disnake.SelectOption(label=e['title'][:90], value=f"entrie_select_{c}",
                                                 emoji=emoji) for c, e in enumerate(info['entries'])
                        ], timeout=30)

                    embed = disnake.Embed(
                        description="**Chọn một danh sách phát bên dưới:**\n"
                                    f'Chọn một tùy chọn theo <t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=30)).timestamp())}:R> để tiếp tục.',
                        color=self.bot.get_color(guild.me)
                    )

                    kwargs = {}

                    try:
                        func = msg.edit
                    except AttributeError:
                        try:
                            func = inter.edit_original_message
                        except AttributeError:
                            kwargs["ephemeral"] = True
                            try:
                                func = inter.followup.send
                            except AttributeError:
                                func = inter.send

                    msg = await func(embed=embed, view=view, **kwargs)

                    await view.wait()

                    if not view.inter or view.selected is False:

                        try:
                            func = msg.edit
                        except:
                            func = view.inter.response.edit_message

                        await func(embed=disnake.Embed(color=self.bot.get_color(guild.me),
                            description="**Thời gian đã hết!**" if not view.selected is False else "### Bị người dùng hủy bỏ."),
                            components=None
                        )
                        return

                    query = info["entries"][int(view.selected[14:])]["url"]

                    if not isinstance(inter, disnake.ModalInteraction):
                        inter.token = view.inter.token
                        inter.id = view.inter.id
                        inter.response = view.inter.response
                    else:
                        inter = view.inter

        else:

            query = query.strip("<>")

            urls = URL_REG.findall(query)

            if not urls:

                query = f"{source}:{query}"

            else:

                if not self.bot.config["ENABLE_DISCORD_URLS_PLAYBACK"] and "cdn.discordapp.com/attachments/" in query:
                    raise GenericError("**Sự hỗ trợ cho các liên kết Discord bị vô hiệu hóa.**")

                query = urls[0].split("&ab_channel=")[0]

                if "&list=" in query and (link_re := YOUTUBE_VIDEO_REG.match(query)):

                    view = SelectInteraction(
                        user=inter.author,
                        opts=[
                            disnake.SelectOption(label="Bài hát", emoji="🎵",
                                                 description="Chỉ tải nhạc từ liên kết.", value="music"),
                            disnake.SelectOption(label="Playlist", emoji="🎶",
                                                 description="Chơi danh sách phát hiện tại.", value="playlist"),
                        ], timeout=30)

                    embed = disnake.Embed(
                        description='**Liên kết chứa video với danh sách phát.**\n'
                                    f'Chọn một tùy chọn theo <t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=30)).timestamp())}:R> để tiếp tục.',
                        color=self.bot.get_color(guild.me)
                    )

                    try:
                        if bot.user.id != self.bot.user.id:
                            embed.set_footer(text=f"Sử dụng {bot.user.display_name}",
                                             icon_url=bot.user.display_avatar.url)
                    except AttributeError:
                        pass

                    msg = await inter.send(embed=embed, view=view, ephemeral=ephemeral)

                    await view.wait()

                    if not view.inter or view.selected is False:

                        try:
                            func = inter.edit_original_message
                        except AttributeError:
                            func = msg.edit

                        await func(
                            content=f"{inter.author.mention}, {'đã hủy bỏ hoạt động' if view.selected is not False else 'Thời gian đã hết'}" if view.selected is not False else "Bị người dùng hủy bỏ.",
                            embed=None, view=None
                        )
                        return

                    if view.selected == "music":
                        query = link_re.group()

                    try:
                        inter.store_message = msg
                    except AttributeError:
                        pass

                    if not isinstance(inter, disnake.ModalInteraction):
                        inter.token = view.inter.token
                        inter.id = view.inter.id
                        inter.response = view.inter.response
                    else:
                        inter = view.inter

        if not inter.response.is_done():
            await inter.response.defer(ephemeral=ephemeral)

        tracks, node = await self.get_tracks(query, inter.user, node=node, track_loops=repeat_amount)

        try:
            player = bot.music.players[inter.guild_id]
        except KeyError:
            await check_pool_bots(inter, check_player=False)

            try:
                bot = inter.music_bot
                guild = inter.music_guild
                channel = bot.get_channel(inter.channel.id)
            except AttributeError:
                bot = inter.bot
                guild = inter.guild
                channel = inter.channel

            try:
                player = bot.music.players[inter.guild_id]
            except KeyError:
                player = None

                guild_data = None

                if inter.bot == bot:
                    try:
                        guild_data = inter.guild_data
                    except AttributeError:
                        guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)
                        try:
                            inter.guild_data = guild_data
                        except AttributeError:
                            pass

                if not guild_data:
                    guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)

                static_player = guild_data['player_controller']

                if static_player['channel']:
                    channel, warn_message = await self.check_channel(guild_data, inter, channel, guild, bot)

        if not player:

            skin = guild_data["player_controller"]["skin"]
            static_skin = guild_data["player_controller"]["static_skin"]

            try:
                global_data = inter.global_guild_data
            except AttributeError:
                global_data = await self.bot.get_global_data(guild.id, db_name=DBModel.guilds)
                try:
                    inter.global_guild_data = global_data
                except:
                    pass

            if global_data["global_skin"]:
                skin = global_data["player_skin"] or skin
                static_skin = global_data["player_skin_static"] or guild_data["player_controller"]["static_skin"]

            try:
                invite = global_data["listen_along_invites"][str(inter.channel.id)]
            except KeyError:
                invite = None

            else:
                if not await self.bot.fetch_invite(invite):
                    invite = None
                    print(
                        f'{"-"*15}\n'
                        f'Loại bỏ lời mời: {invite} \n'
                        f'Máy chủ: {inter.guild.name} [{inter.guild_id}]\n'
                        f'Kênh: {inter.channel.name} [{inter.channel.id}]\n'
                        f'{"-" * 15}'
                    )
                    del global_data["listen_along_invites"][str(inter.channel.id)]
                    await self.bot.update_global_data(inter.guild_id, global_data, db_name=DBModel.guilds)

            player: LavalinkPlayer = bot.music.get_player(
                guild_id=inter.guild_id,
                cls=LavalinkPlayer,
                player_creator=inter.author.id,
                guild=guild,
                channel=channel or bot.get_channel(inter.channel_id),
                last_message_id=guild_data['player_controller']['message_id'],
                node_id=node.identifier,
                static=bool(static_player['channel']),
                skin=bot.check_skin(skin),
                custom_skin_data=global_data["custom_skins"],
                custom_skin_static_data=global_data["custom_skins_static"],
                skin_static=bot.check_static_skin(static_skin),
                extra_hints=self.extra_hints,
                restrict_mode=guild_data['enable_restrict_mode'],
                listen_along_invite=invite,
                volume=int(guild_data['default_player_volume']),
                autoplay=guild_data["autoplay"],
            )

            if static_player['channel']:

                if isinstance(player.text_channel, disnake.Thread):
                    channel_check = player.text_channel.parent
                else:
                    channel_check = player.text_channel

                bot_perms = channel_check.permissions_for(guild.me)

                if not bot_perms.read_message_history:

                    if not bot_perms.manage_permissions:

                        player.set_command_log(
                            emoji="⚠️",
                            text=f"Tớ không được phép xem tin nhắn trên kênh: {channel_check.mention} "
                                 f"(và không cho phép quản lý các quyền để tự động sửa chữa điều này), "
                                 f"Người chơi sẽ làm việc theo cách mặc định..."
                        )

                        player.static = False

                    else:

                        overwrites = {
                            guild.me: disnake.PermissionOverwrite(
                                embed_links=True,
                                send_messages=True,
                                send_messages_in_threads=True,
                                read_messages=True,
                                create_public_threads=True,
                                read_message_history=True,
                                manage_messages=True,
                                manage_channels=True,
                                attach_files=True,
                            )
                        }

                        await channel_check.edit(overwrites=overwrites)

                try:
                    message = await channel.fetch_message(int(static_player['message_id']))
                except TypeError:
                    message = None
                except:
                    message = await send_idle_embed(channel, bot=bot)

                player.message = message

        pos_txt = ""

        embed = disnake.Embed(color=disnake.Colour.red())

        embed.colour = self.bot.get_color(guild.me)

        position -= 1

        if isinstance(tracks, list):

            if manual_selection and len(tracks) > 1:

                embed.description = f"**Chọn các bài hát mong muốn bên dưới:**"

                try:
                    func = inter.edit_original_message
                except AttributeError:
                    func = inter.send

                try:
                    add_id = f"_{inter.id}"
                except AttributeError:
                    add_id = ""

                tracks = tracks[:25]

                msg = await func(
                    embed=embed,
                    components=[
                        disnake.ui.Select(
                            placeholder='Kết quả:',
                            custom_id=f"track_selection{add_id}",
                            min_values=1,
                            max_values=len(tracks),
                            options=[
                                disnake.SelectOption(
                                    label=f"{n+1}. {t.title[:96]}",
                                    value=f"track_select_{n}",
                                    description=f"{t.author} [{time_format(t.duration)}]")
                                for n, t in enumerate(tracks)
                            ]
                        )
                    ]
                )

                def check_song_selection(i: Union[CustomContext, disnake.MessageInteraction]):

                    try:
                        return i.data.custom_id == f"track_selection_{inter.id}" and i.author == inter.author
                    except AttributeError:
                        return i.author == inter.author and i.message.id == msg.id

                try:
                    select_interaction: disnake.MessageInteraction = await self.bot.wait_for(
                        "dropdown",
                        timeout=45,
                        check=check_song_selection
                    )
                except asyncio.TimeoutError:
                    raise GenericError("Thời gian đã hết!")

                if len(select_interaction.data.values) > 1:

                    indexes = set(int(v[13:]) for v in select_interaction.data.values)

                    selected_tracks = []

                    for i in indexes:
                        for n, t in enumerate(tracks):
                            if i == n:
                                selected_tracks.append(t)
                                break

                    tracks = selected_tracks

                else:

                    tracks = tracks[int(select_interaction.data.values[0][13:])]

                if isinstance(inter, CustomContext):
                    inter.message = msg

            else:

                tracks = tracks[0]

                if tracks.info.get("sourceName") == "http":

                    if tracks.title == "Unknown title":
                        if attachment:
                            tracks.info["title"] = attachment.filename
                        else:
                            tracks.info["title"] = tracks.uri.split("/")[-1]
                        tracks.title = tracks.info["title"]

                    tracks.uri = ""

            if not isinstance(tracks, list):

                if force_play == "yes":
                    player.queue.insert(0, tracks)
                elif position < 0:
                    player.queue.append(tracks)
                else:
                    player.queue.insert(position, tracks)
                    pos_txt = f" vị trí {position + 1} trong hàng"

                duration = time_format(tracks.duration) if not tracks.is_stream else '🔴 Livestream'

                log_text = f"{inter.author.mention} thêm [`{fix_characters(tracks.title, 20)}`]({tracks.uri or tracks.search_uri}){pos_txt} `({duration})`."

                embed.set_author(
                    name=fix_characters(tracks.title, 35),
                    url=tracks.uri or tracks.search_uri,
                    icon_url=music_source_image(tracks.info['sourceName'])
                )
                embed.set_thumbnail(url=tracks.thumb)
                embed.description = f"`{fix_characters(tracks.author, 15)}`**┃**`{time_format(tracks.duration) if not tracks.is_stream else '🔴 Livestream'}`**┃**{inter.author.mention}"
                emoji = "🎵"

            else:

                if options == "shuffle":
                    shuffle(tracks)

                if position < 0 or len(tracks) < 2:

                    if options == "reversed":
                        tracks.reverse()
                    for track in tracks:
                        player.queue.append(track)
                else:
                    if options != "reversed":
                        tracks.reverse()
                    for track in tracks:
                        player.queue.insert(position, track)

                    pos_txt = f" (Pos. {position + 1})"

                query = fix_characters(query.replace(f"{source}:", '', 1), 25)

                log_text = f"{inter.author.mention} thêm `{len(tracks)} Bài hát `thông qua tìm kiếm: `{query}`{pos_txt}."

                total_duration = 0

                for t in tracks:
                    if not t.is_stream:
                        total_duration += t.duration

                embed.set_author(name=f"Tìm kiếm: {query}", icon_url=music_source_image(tracks[0].info['sourceName']))
                embed.set_thumbnail(url=tracks[0].thumb)
                embed.description = f"`{len(tracks)} (Các) bài hát`**┃**`{time_format(total_duration)}`**┃**{inter.author.mention}"
                emoji = "🎶"

        else:

            if options == "shuffle":
                shuffle(tracks.tracks)

            if position < 0 or len(tracks.tracks) < 2:

                if options == "reversed":
                    tracks.tracks.reverse()
                for track in tracks.tracks:
                    player.queue.append(track)
            else:
                if options != "reversed":
                    tracks.tracks.reverse()
                for track in tracks.tracks:
                    player.queue.insert(position, track)

                pos_txt = f" (Pos. {position + 1})"

            log_text = f"{inter.author.mention} Đã thêm danh sách phát [`{fix_characters(tracks.name, 20)}`]({tracks.url}){pos_txt} `({len(tracks.tracks)})`."

            total_duration = 0

            for t in tracks.tracks:
                if not t.is_stream:
                    total_duration += t.duration

            try:
                embed.set_author(
                    name="⠂" + fix_characters(tracks.name, 35),
                    url=tracks.url,
                    icon_url=music_source_image(tracks.tracks[0].info['sourceName'])
                )
            except KeyError:
                embed.set_author(
                    name="⠂ Spotify Playlist",
                    icon_url=music_source_image(tracks.tracks[0].info['sourceName'])
                )
            embed.set_thumbnail(url=tracks.tracks[0].thumb)
            embed.description = f"`{len(tracks.tracks)} Các bài hát`**┃**`{time_format(total_duration)}`**┃**{inter.author.mention}"
            emoji = "🎶"

        embed.description += player.controller_link

        if not is_pin:

            if not player.is_connected:
                try:
                    embed.description += f"\n`Kênh giọng nói:` {voice_channel.mention}"
                except AttributeError:
                    pass

            try:
                func = inter.edit_original_message
            except AttributeError:
                if msg:
                    func = msg.edit
                elif inter.message.author.id == bot.user.id:
                    func = inter.message.edit
                else:
                    func = inter.send

            try:
                if bot.user.id != self.bot.user.id:
                    embed.set_footer(text=f"Sử dụng {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
            except AttributeError:
                pass

            await func(embed=embed, view=None)

        if not player.is_connected:

            try:
                guild_data["check_other_bots_in_vc"]
            except KeyError:
                guild_data = None

                if inter.bot == bot:
                    try:
                        guild_data = inter.guild_data
                    except AttributeError:
                        guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)
                        try:
                            inter.guild_data = guild_data
                        except AttributeError:
                            pass

                if not guild_data:
                    guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)

            if not inter.author.voice:
                raise NoVoice()

            await self.do_connect(
                inter, channel=voice_channel,
                check_other_bots_in_vc=guild_data["check_other_bots_in_vc"],
                bot=bot, me=guild.me, check_pool=True
            )

        if not player.current:
            if warn_message:
                player.set_command_log(emoji="⚠️", text=warn_message)
            await player.process_next()
        elif force_play == "yes":
            player.set_command_log(
                emoji="▶️",
                text=f"{inter.author.mention} Anh ấy đã thêm bài hát hiện tại để chơi ngay lập tức."
            )
            await player.track_end()
            await player.process_next()
        elif player.current.autoplay:
            player.set_command_log(text=log_text, emoji=emoji)
            await player.track_end()
            await player.process_next()
        else:
            if ephemeral:
                player.set_command_log(text=log_text, emoji=emoji)
            player.update = True

    @play.autocomplete("search")
    async def fav_add_autocomplete(self, inter: disnake.Interaction, query: str):

        if URL_REG.match(query):
            return [query] if len(query) < 100 else []

        favs: list = await fav_list(inter, query)

        if not inter.guild:
            try:
                await check_pool_bots(inter, return_first=True)
            except:
                return [query] if len(query) < 100 else []

        try:
            vc = inter.author.voice
        except AttributeError:
            vc = True

        if not vc or not query or (favs_size := len(favs)) >= 20:
            return favs[:20]

        return await google_search(self.bot, query, max_entries=20 - favs_size) + favs

    skip_back_cd = commands.CooldownMapping.from_cooldown(2, 13, commands.BucketType.member)
    skip_back_mc = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    case_sensitive_args = CommandArgparse()
    case_sensitive_args.add_argument('-casesensitive', '-cs', '-exactmatch', '-exact', action='store_true',
                             help="Tìm kiếm âm nhạc với lời bài hát chính xác thay vì tìm kiếm từng từ trong tên của âm nhạc")
    @check_stage_topic()
    @is_requester()
    @check_voice()
    @pool_command(name="skip", aliases=["next", "n", "s", "pular", "skipto"], cooldown=skip_back_cd,
                  max_concurrency=skip_back_mc, description=f"Bỏ qua bài hát hiện tại đang phát.",
                  only_voiced=True)
    async def skip_legacy(self, ctx: CustomContext, *, flags: str = ""):

        args, unknown = self.case_sensitive_args.parse_known_args(flags.split())

        if ctx.invoked_with == "skipto" and not unknown:
            raise GenericError("**Bạn phải thêm một tên để sử dụng Skipto.**")

        await self.skip.callback(self=self, inter=ctx, query=" ".join(unknown), case_sensitive=args.casesensitive)

    @check_stage_topic()
    @is_requester()
    @has_source()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Nhảy đến một dòng cụ thể trong dòng.",
        extras={"only_voiced": True}, cooldown=skip_back_cd, max_concurrency=skip_back_mc
    )
    async def skipto(
            self,
            inter: disnake.AppCmdInter,
            query: str = commands.Param(
                name="nome",
                description="Tên của bài hát (hoàn chỉnh hoặc một phần của nó)."
            ),
            case_sensitive: bool = commands.Param(
                name="nome_exato", default=False,
                description="Tìm kiếm lời bài hát chính xác thay vì tìm kiếm từ này trong tên của bài hát ",

            )
    ):

        await self.skip.callback(self=self, inter=inter, query=query, case_sensitive=case_sensitive)

    @check_stage_topic()
    @is_requester()
    @has_source()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Bỏ qua bài hát hiện tại đang phát.",
        extras={"only_voiced": True}, cooldown=skip_back_cd, max_concurrency=skip_back_mc
    )
    async def skip(
            self,
            inter: disnake.AppCmdInter, *,
            query: str = commands.Param(
                name="nome",
                description="Tên âm nhạc (hoàn thành hoặc một phần của nó).",
                default=None,
            ),
            play_only: str = commands.Param(
                name=disnake.Localized("play_only", data={disnake.Locale.pt_BR: "tocar_apenas"}),
                choices=[
                    disnake.OptionChoice(
                        disnake.Localized("Yes", data={disnake.Locale.pt_BR: "Sim"}), "yes"
                    ),
                    disnake.OptionChoice(
                        disnake.Localized("No", data={disnake.Locale.pt_BR: "Não"}), "no"
                    )
                ],
                description="Chỉ cần chơi nhạc ngay lập tức (mà không xoay flia)",
                default="no"
            ),
            case_sensitive: bool = commands.Param(
                name="nome_exato", default=False,
                description="Tìm kiếm âm nhạc với lời bài hát chính xác thay vì tìm kiếm từng từ trong tên của âm nhạc",

            )
    ):

        try:
            bot = inter.music_bot
            guild = inter.music_guild
        except AttributeError:
            bot = inter.bot
            guild = bot.get_guild(inter.guild_id)

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        ephemeral = await self.is_request_channel(inter)

        interaction = None

        if query:

            try:
                index = queue_track_index(inter, bot, query, case_sensitive=case_sensitive)[0][0]
            except IndexError:
                raise GenericError(f"**Không có bài hát nào phù hợp với tên: {query}**")

            track = player.queue[index]

            player.queue.append(player.last_track)
            player.last_track = None

            if player.loop == "current":
                player.loop = False

            if play_only == "yes":
                del player.queue[index]
                player.queue.appendleft(track)

            elif index > 0:
                player.queue.rotate(0 - index)

            player.set_command_log(emoji="⤵️", text="nhảy vào bài hát hiện tại.")

            embed = disnake.Embed(
                color=self.bot.get_color(guild.me),
                description= f"⤵<:verify:1134033164151566460> **⠂{inter.author.mention} nhảy vào bài hát:**\n"
                             f"╰[`{fix_characters(track.title, 43)}`]({track.uri or track.search_uri}){player.controller_link}"
            )

            try:
                if bot.user.id != self.bot.user.id:
                    embed.set_footer(text=f"Sử dụng {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
            except AttributeError:
                pass

            if isinstance(inter, disnake.MessageInteraction) and inter.data.custom_id == "queue_track_selection":
                await inter.response.edit_message(embed=embed, view=None)
            else:
                await inter.send(embed=embed, ephemeral=ephemeral)

        else:

            if isinstance(inter, disnake.MessageInteraction):
                player.set_command_log(text=f"{inter.author.mention} bỏ qua bài hát.", emoji="⏭️")
                await inter.response.defer()
                interaction = inter
            else:

                player.set_command_log(emoji="⏭️", text=f"{inter.author.mention} bỏ qua bài hát.")

                embed = disnake.Embed(
                    color=self.bot.get_color(guild.me),
                    description=f"<:verify:1134033164151566460> **⠂{inter.author.mention} đã bỏ qua bài hát:\n"
                                f"╰[`{fix_characters(player.current.title, 43)}`]({player.current.uri or player.current.search_uri})**"
                                f"{player.controller_link}"
                )

                try:
                    if bot.user.id != self.bot.user.id:
                        embed.set_footer(text=f"Sử dụng {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
                except AttributeError:
                    pass

                await inter.send(embed=embed, ephemeral=ephemeral)

            if player.loop == "current":
                player.loop = False

        player.current.info["extra"]["track_loops"] = 0

        await player.track_end()
        player.ignore_np_once = True
        await player.process_next(inter=interaction)

    @check_stage_topic()
    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(name="back", aliases=["b", "voltar"], description="Quay lại bài hát trước.", only_voiced=True,
                  cooldown=skip_back_cd, max_concurrency=skip_back_mc)
    async def back_legacy(self, ctx: CustomContext):
        await self.back.callback(self=self, inter=ctx)

    @check_stage_topic()
    @is_dj()
    @has_player()
    @check_voice()
    @commands.max_concurrency(1, commands.BucketType.member)
    @commands.slash_command(
        description=f"{desc_prefix}Quay lại bài hát trước.",
        extras={"only_voiced": True}, cooldown=skip_back_cd, max_concurrency=skip_back_mc
    )
    async def back(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if not len(player.queue) and (player.keep_connected or not len(player.played)):
            await player.seek(0)
            await self.interaction_message(inter, "đã trở lại đầu bài hát.", emoji="⏪")
            return

        if player.keep_connected:
            track = player.queue.pop()
            player.queue.appendleft(player.current)
        else:
            try:
                track = player.played.pop()
            except:
                track = player.queue.pop()

            if player.current and not player.current.autoplay:
                player.queue.appendleft(player.current)

        player.last_track = None

        player.queue.appendleft(track)

        if isinstance(inter, disnake.MessageInteraction):
            interaction = inter
            player.set_command_log(text=f"{inter.author.mention} trở lại với âm nhạc hiện tại.", emoji="⏮️")
            await inter.response.defer()
        else:

            interaction = None

            t = player.queue[0]

            txt = [
                "trở lại với bài hát hiện tại.",
                f"⏮️ **⠂{inter.author.mention} trở lại với bài hát:\n╰[`{fix_characters(t.title, 43)}`]({t.uri or t.search_uri})**"
            ]

            await self.interaction_message(inter, txt, emoji="⏮️", store_embed=True)

        if player.loop == "current":
            player.loop = False

        player.ignore_np_once = True

        if not player.current:
            await player.process_next(inter=interaction)
        else:
            player.is_previows_music = True
            await player.track_end()
            await player.process_next(inter=interaction)

    @check_stage_topic()
    @has_source()
    @check_voice()
    @commands.slash_command(
        name=disnake.Localized("voteskip", data={disnake.Locale.pt_BR: "votar_pular"}),
        description=f"{desc_prefix}Bỏ phiếu để bỏ qua âm nhạc hiện tại.",
        extras={"only_voiced": True}
    )
    async def voteskip(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
            guild = inter.music_guild
        except AttributeError:
            bot = inter.bot
            guild = inter.guild

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        embed = disnake.Embed()

        if inter.author.id in player.votes:
            raise GenericError("**Bạn đã bỏ phiếu để bỏ qua âm nhạc hiện tại.**")

        embed.colour = self.bot.get_color(guild.me)

        txt = [
            f"Được bình chọn để bỏ qua âm nhạc hiện tại (phiếu bầu: {len(player.votes) + 1}/{self.bot.config['VOTE_SKIP_AMOUNT']}).",
            f"{inter.author.mention} Được bình chọn để bỏ qua âm nhạc hiện tại (phiếu bầu: {len(player.votes) + 1}/{self.bot.config['VOTE_SKIP_AMOUNT']}).",
        ]

        if len(player.votes) < self.bot.config.get('VOTE_SKIP_AMOUNT', 3):
            embed.description = txt
            player.votes.add(inter.author.id)
            await self.interaction_message(inter, txt, emoji="✋")
            return

        await self.interaction_message(inter, txt, emoji="✋")
        await player.track_end()
        await player.process_next()

    volume_cd = commands.CooldownMapping.from_cooldown(1, 7, commands.BucketType.member)
    volume_mc = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @is_dj()
    @has_source()
    @check_voice()
    @pool_command(name="volume", description="Điều chỉnh âm lượng âm nhạc.", aliases=["vol", "v"], only_voiced=True,
                  cooldown=volume_cd, max_concurrency=volume_mc)
    async def volume_legacy(self, ctx: CustomContext, level: str = None):

        if not level:
            raise GenericError("**Bạn đã không ghi rõ âm lượng (từ 5-150).**")

        if not level.isdigit() or len(level) > 3:
            raise GenericError("*Âm lượng không hợp lệ!, chỉ được chọn từ 5-150**", self_delete=7)

        await self.volume.callback(self=self, inter=ctx, value=int(level))

    @is_dj()
    @has_source()
    @check_voice()
    @commands.slash_command(description=f"{desc_prefix}Điều chỉnh âm lượng âm nhạc.", extras={"only_voiced": True},
                            cooldown=volume_cd, max_concurrency=volume_mc)
    async def volume(
            self,
            inter: disnake.AppCmdInter, *,
            value: int = commands.Param(name="mức", description="Chọn từ 5 đến 150", min_value=5.0, max_value=150.0)
    ):

        try:
            bot = inter.music_bot
            guild = inter.music_guild
        except AttributeError:
            bot = inter.bot
            guild = inter.guild

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        embed = disnake.Embed(color=disnake.Colour.red())

        if value is None:

            view = VolumeInteraction(inter)

            embed.colour = self.bot.get_color(guild.me)
            embed.description = "**Chọn mức âm lượng bên dưới:**"

            try:
                if bot.user.id != self.bot.user.id:
                    embed.set_footer(text=f"Sử dụng {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
            except AttributeError:
                pass

            await inter.send(embed=embed, ephemeral=await self.is_request_channel(inter), view=view)
            await view.wait()
            if view.volume is None:
                return

            value = view.volume

        elif not 4 < value < 151:
            raise GenericError("Âm lượng phải nằm giữa ** 5 ** đến ** 150 **.")

        await player.set_volume(value)

        txt = [f"điều chỉnh Âm lượng thành **{value}%**", f"<:Play_With_Me:1128555926417330207> **⠂{inter.author.mention} điều chỉnh âm lượng thành {value}%**"]
        await self.interaction_message(inter, txt, emoji="<:Play_With_Me:1128555926417330207>")

    pause_resume_cd = commands.CooldownMapping.from_cooldown(2, 7, commands.BucketType.member)
    pause_resume_mc =commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @is_dj()
    @has_source()
    @check_voice()
    @pool_command(name="pause", aliases=["pausar"], description="Tạm dừng âm nhạc.", only_voiced=True,
                  cooldown=pause_resume_cd, max_concurrency=pause_resume_mc)
    async def pause_legacy(self, ctx: CustomContext):
        await self.pause.callback(self=self, inter=ctx)

    @is_dj()
    @has_source()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Tạm dừng âm nhạc.", extras={"only_voiced": True},
        cooldown=pause_resume_cd, max_concurrency=pause_resume_mc
    )
    async def pause(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if player.paused:
            raise GenericError("**Bài hát đã bị tạm dừng.**")

        await player.set_pause(True)

        txt = ["tạm dừng âm nhạc.", f"⏸️ **⠂{inter.author.mention} đã tạm dừng bài hát.**"]

        await self.interaction_message(inter, txt, rpc_update=True, emoji="⏸️")

    @is_dj()
    @has_source()
    @check_voice()
    @pool_command(name="resume", aliases=["unpause"], description="Trả lại/phân tán âm nhạc.", only_voiced=True,
                  cooldown=pause_resume_cd, max_concurrency=pause_resume_mc)
    async def resume_legacy(self, ctx: CustomContext):
        await self.resume.callback(self=self, inter=ctx)

    @is_dj()
    @has_source()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix} tiếp tục bài hát.",
        extras={"only_voiced": True}, cooldown=pause_resume_cd, max_concurrency=pause_resume_mc
    )
    async def resume(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if not player.paused:
            raise GenericError("**Âm nhạc không bị tạm dừng.**")

        await player.set_pause(False)

        txt = ["tiếp tục âm nhạc.", f"▶️ **⠂{inter.author.mention} đã tiếp tục bài hát**"]
        await self.interaction_message(inter, txt, rpc_update=True, emoji="▶️")

    seek_cd = commands.CooldownMapping.from_cooldown(2, 10, commands.BucketType.member)
    seek_mc =commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @check_stage_topic()
    @is_dj()
    @has_source()
    @check_voice()
    @pool_command(name="seek", aliases=["sk"], description="Tiến bộ/tiếp tục âm nhạc trong một thời gian cụ thể.",
                  only_voiced=True, cooldown=seek_cd, max_concurrency=seek_mc)
    async def seek_legacy(self, ctx: CustomContext, *, position: str = None):

        if not position:
            raise GenericError("**Bạn đã không nói thời gian để di chuyển/quay trở lại (ví dụ: 1:55 | 33 | 0:45).**")

        await self.seek.callback(self=self, inter=ctx, position=position)

    @check_stage_topic()
    @is_dj()
    @has_source()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Tiến bộ/tiếp tục âm nhạc trong một thời gian cụ thể.",
        extras={"only_voiced": True}, cooldown=seek_cd, max_concurrency=seek_mc
    )
    async def seek(
            self,
            inter: disnake.AppCmdInter,
            position: str = commands.Param(name="tempo", description="Thời gian để tiến / trở lại (ví dụ: 1:45 / 40/0: 30)")
    ):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if player.current.is_stream:
            raise GenericError("**Bạn không thể sử dụng lệnh này trong một livestream.**")

        position = position.split(" | ")[0].replace(" ", ":")

        seconds = string_to_seconds(position)

        if seconds is None:
            raise GenericError(
                "**Bạn đã sử dụng một thời gian không hợp lệ !Sử dụng giây (1 hoặc 2 chữ số) hoặc ở định dạng (phút) :(giây)**")

        milliseconds = seconds * 1000

        if milliseconds < 0:
            milliseconds = 0

        if milliseconds > player.position:

            emoji = "⏩"

            txt = [
                f"đã tua thời gian của bài hát đến `{time_format(milliseconds)}`",
                f"{emoji} **⠂{inter.author.mention} đã tua thời gian của bài hát đển:** `{time_format(milliseconds)}`"
            ]

        else:

            emoji = "⏪"

            txt = [
                f"Thời gian của bài hát đã trở lại: `{time_format(milliseconds)}`",
                f"{emoji} **⠂{inter.author.mention} đã đưa thời gian của bài hát trở lại:** `{time_format(milliseconds)}`"
            ]

        await player.seek(milliseconds)

        if player.paused:
            await player.set_pause(False)

        await self.interaction_message(inter, txt, emoji=emoji)

        await asyncio.sleep(2)
        await player.process_rpc()

    @seek.autocomplete("tempo")
    async def seek_suggestions(self, inter: disnake.Interaction, query: str):

        try:
            if query or not inter.author.voice:
                return
        except AttributeError:
            pass

        try:
            await check_pool_bots(inter, only_voiced=True)
            bot = inter.music_bot
        except:
            return

        try:
            player: LavalinkPlayer = bot.music.players[inter.guild_id]
        except KeyError:
            return

        if not player.current or player.current.is_stream:
            return

        seeks = []

        if player.current.duration >= 90000:
            times = [int(n * 0.5 * 10) for n in range(20)]
        else:
            times = [int(n * 1 * 10) for n in range(20)]

        for p in times:
            percent = percentage(p, player.current.duration)
            seeks.append(f"{time_format(percent)} | {p}%")

        return seeks

    loop_cd = commands.CooldownMapping.from_cooldown(3, 5, commands.BucketType.member)
    loop_mc =commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @is_dj()
    @has_source()
    @check_voice()
    @pool_command(
        description=f"Chọn Chế độ lặp lại giữa: Âm nhạc hiện tại / Line / Tắt / Số lượng (sử dụng số).",
        only_voiced=True, cooldown=loop_cd, max_concurrency=loop_mc,
        usage="{prefix}{cmd} <Số lượng | Chế độ>\nVí dụ: 1: {prefix}{cmd} 1\nVí dụ 2: {prefix}{cmd} Hàng")
    async def loop(self, ctx: CustomContext, mode: str = None):

        if not mode:

            embed = disnake.Embed(
                description="**Chọn chế độ lặp lại:**",
                color=self.bot.get_color(ctx.guild.me)
            )

            msg = await ctx.send(
                ctx.author.mention,
                embed=embed,
                components=[
                    disnake.ui.Select(
                        placeholder="Chọn một tùy chọn:",
                        custom_id="loop_mode_legacy",
                        options=[
                            disnake.SelectOption(label="Bài hát hiện tại", value="current"),
                            disnake.SelectOption(label="Hàng đợi", value="queue"),
                            disnake.SelectOption(label="Vô hiệu hóa", value="off")
                        ]
                    )
                ]
            )

            try:
                select: disnake.MessageInteraction = await self.bot.wait_for(
                    "dropdown", timeout=30,
                    check=lambda i: i.message.id == msg.id and i.author == ctx.author
                )
            except asyncio.TimeoutError:
                embed.description = "Đã hết thời gian!"
                try:
                    await msg.edit(embed=embed, view=None)
                except:
                    pass
                return

            mode = select.data.values[0]
            ctx.store_message = msg

        if mode.isdigit():

            if len(mode) > 2 or int(mode) > 10:
                raise GenericError(f"**Số lượng không hợp lệ: {mode}**\n"
                                   "`Số lượng cho phép tối đa: 10`")

            await self.loop_amount.callback(self=self, inter=ctx, value=int(mode))
            return

        if mode not in ('current', 'queue', 'off'):
            raise GenericError("Cách không hợp lệ! Chọn giữa: Hiện tại/Hàng đợi/TẮT")

        await self.loop_mode.callback(self=self, inter=ctx, mode=mode)

    @is_dj()
    @has_source()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Chọn Chế độ lặp lại giữa: bài hát hiện tại / Hàng đợi hoặc Tắt.",
        extras={"only_voiced": True}, cooldown=loop_cd, max_concurrency=loop_mc
    )
    async def loop_mode(
            self,
            inter: disnake.AppCmdInter,
            mode: str = commands.Param(
                name="mode",
                choices=[
                    disnake.OptionChoice(
                        disnake.Localized("Current", data={disnake.Locale.pt_BR: "Música Atual"}), "current"
                    ),
                    disnake.OptionChoice(
                        disnake.Localized("Queue", data={disnake.Locale.pt_BR: "Fila"}), "queue"
                    ),
                    disnake.OptionChoice(
                        disnake.Localized("Off", data={disnake.Locale.pt_BR: "Desativar"}), "off"
                    ),
                ]
            )
    ):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if mode == player.loop:
            raise GenericError("**Chế độ lặp lại được chọn đã hoạt động...**")

        if mode == 'off':
            mode = False
            player.current.info["extra"]["track_loops"] = 0
            emoji = "⭕"
            txt = ['Vô hiệu hóa lặp lại.', f"{emoji} **⠂{inter.author.mention}Vô hiệu hóa lặp lại.**"]

        elif mode == "current":
            player.current.info["extra"]["track_loops"] = 0
            emoji = "🔂"
            txt = ["Đã kích hoạt lặp lại của bài hát hiện tại.",
                   f"{emoji} **⠂{inter.author.mention} Đã kích hoạt lặp lại của bài hát hiện tại.**"]

        else:  # queue
            emoji = "🔁"
            txt = ["đã kích hoạt lặp lại của dòng.", f"{emoji} **⠂{inter.author.mention} đã kích hoạt lặp lại của hàng đợi.**"]

        player.loop = mode

        bot.loop.create_task(player.process_rpc())

        await self.interaction_message(inter, txt, emoji=emoji)

    @is_dj()
    @has_source()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Xác định số lượng lặp lại của âm nhạc hiện tại.",
        extras={"only_voiced": True}, cooldown=loop_cd, max_concurrency=loop_mc
    )
    async def loop_amount(
            self,
            inter: disnake.AppCmdInter,
            value: int = commands.Param(name="valor", description="Số lần lặp lại.")
    ):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        player.current.info["extra"]["track_loops"] = value

        txt = [
            f"xác định số lượng lặp lại của bài hát "
            f"[`{(fix_characters(player.current.title, 25))}`]({player.current.uri or player.current.search_uri}) para **{value}**.",
            f"🔄 **⠂{inter.author.mention} xác định số lượng lặp lại bài hát là [{value}]:**\n"
            f"╰[`{player.current.title}`]({player.current.uri or player.current.search_uri})"
        ]

        await self.interaction_message(inter, txt, rpc_update=True, emoji="🔄")

    remove_mc = commands.MaxConcurrency(1, per=commands.BucketType.guild, wait=False)

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(name="remove", aliases=["r", "del"], description="Hủy bỏ một dòng cụ thể khỏi dòng.",
                  only_voiced=True, max_concurrency=remove_mc, extras={"flags": case_sensitive_args},
                  usage="{prefix}{cmd} [nome]\nEx: {prefix}{cmd} sekai")
    async def remove_legacy(self, ctx: CustomContext, *, flags: str = ""):

        args, unknown = ctx.command.extras['flags'].parse_known_args(flags.split())

        if not unknown:
            raise GenericError("**Bạn đã không thêm tên của bài hát.**")

        await self.remove.callback(self=self, inter=ctx, query=" ".join(unknown), case_sensitive=args.casesensitive)

    @is_dj()
    @has_player()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Xóa một dòng cụ thể khỏi hàng đợi.",
        extras={"only_voiced": True}, max_concurrency=remove_mc
    )
    async def remove(
            self,
            inter: disnake.AppCmdInter,
            query: str = commands.Param(name="nome", description="Nome da música completo."),
            case_sensitive: bool = commands.Param(
                name="nome_exato", default=False,
                description="Tìm kiếm âm nhạc với lời bài hát chính xác thay vì tìm kiếm từng từ trong tên của âm nhạc",

            )
    ):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        try:
            index = queue_track_index(inter, bot, query, case_sensitive=case_sensitive)[0][0]
        except IndexError:
            raise GenericError(f"**Không có bài hát nào phù hợp với tên: {query}**")

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        track = player.queue[index]

        player.queue.remove(track)

        txt = [
            f"loại bỏ âm nhạc [`{(fix_characters(track.title, 25))}`]({track.uri or track.search_uri}) khỏi hàng.",
            f"♻️ **⠂{inter.author.mention} Đã loại bỏ âm nhạc khỏi dòng:**\n╰[`{track.title}`]({track.uri or track.search_uri})"
        ]

        await self.interaction_message(inter, txt, emoji="♻️")

        await player.update_message()

    queue_manipulation_cd = commands.CooldownMapping.from_cooldown(2, 15, commands.BucketType.guild)

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(name="readd", aliases=["readicionar", "rdd"], only_voiced=True, cooldown=queue_manipulation_cd,
                  max_concurrency=remove_mc, description="Đọc các bài hát được chơi trong hàng.")
    async def readd_legacy(self, ctx: CustomContext):
        await self.readd_songs.callback(self=self, inter=ctx)

    @is_dj()
    @has_player()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Đọc các bài hát được chơi trong hàng.",
        extras={"only_voiced": True}, cooldown=queue_manipulation_cd, max_concurrency=remove_mc
    )
    async def readd_songs(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if not player.played:
            raise GenericError("**Không có bài hát nào được chơi.**")
        qsize = len(player.played) + len(player.failed_tracks)

        player.played.reverse()
        player.failed_tracks.reverse()
        player.queue.extend(player.failed_tracks)
        player.queue.extend(player.played)
        player.played.clear()
        player.failed_tracks.clear()

        txt = [
            f"Thêm [{qsize}] Bài hát đã phát vào lại hàng chờ.",
            f"🎶 **⠂{inter.author.mention} đã thêm {qsize} bài hát vào lại hàng đợi.**"
        ]

        await self.interaction_message(inter, txt, emoji="🎶")

        await player.update_message()

        if not player.current:
            await player.process_next()
        else:
            await player.update_message()

    move_args = CommandArgparse()
    move_args.add_argument('-count', '-counter', '-amount', '-c', '-max', type=int, default=None,
                           help="Chỉ định một số bài hát để di chuyển với tên được chỉ định.")
    move_args.add_argument('-casesensitive', '-cs', '-exactmatch', '-exact', action='store_true',
                           help="Tìm kiếm lời bài hát chính xác thay vì tìm kiếm từng từ trong tên "
                                "từ âm nhạc")
    move_args.add_argument('-position', '-pos', help="Chỉ định vị trí đích", type=int, default=None)

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(name="move", aliases=["mv", "mover"], only_voiced=True, max_concurrency=remove_mc,
                  description="Di chuyển một bài hát đến vị trí được chỉ định trong hàng đợi.")
    async def move_legacy(self, ctx: CustomContext, position: Optional[int] = None, *, flags: str = ""):

        args, unknown = self.move_args.parse_known_args(args=flags.split())

        if args.position:
            if position:
                unknown.insert(0, str(position))
            position = args.position

        elif not position:
            raise GenericError("**Bạn đã không báo cáo một vị trí trong hàng đợi.**")

        if not unknown:
            raise GenericError("**Bạn đã không thêm tên của bài hát.**")

        await self.move.callback(self=self, inter=ctx, position=position, query=" ".join(unknown), match_count=args.count or 1, case_sensitive=args.casesensitive)

    @is_dj()
    @has_player()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Di chuyển một bài hát đến vị trí được chỉ định trong hàng đợi.",
        extras={"only_voiced": True}, max_concurrency=remove_mc
    )
    async def move(
            self,
            inter: disnake.AppCmdInter,
            query: str = commands.Param(name="nome", description="Tên của bài hát."),
            position: int = commands.Param(name="position", description="Vị trí đích theo dòng.", default=1),
            match_count: int = commands.Param(
                name="quantidade",
                description="Chỉ định một số bài hát để di chuyển với tên được chỉ định.",
                default=1, min_value=1, max_value=999,
            ),
            case_sensitive: bool = commands.Param(
                name="nome_exato", default=False,
                description="Tìm kiếm âm nhạc với lời bài hát chính xác thay vì tìm kiếm từng từ trong tên của âm nhạc",

            )
    ):

        if position < 1:
            raise GenericError(f"**Bạn đã sử dụng một vị trí không hợp lệ: {position}**.")

        try:
            bot = inter.music_bot
            guild = inter.music_guild
        except AttributeError:
            bot = inter.bot
            guild = inter.guild

        player: LavalinkPlayer = bot.music.players[guild.id]

        indexes = queue_track_index(inter, bot, query, match_count=match_count, case_sensitive=case_sensitive)

        if not indexes:
            raise GenericError(f"**Không có bài hát nào phù hợp với tên: {query}**")

        for index, track in reversed(indexes):
            player.queue.remove(track)

            player.queue.insert(int(position) - 1, track)

        if (i_size := len(indexes)) == 1:
            track = indexes[0][1]

            txt = [
                f"Chuyển bài hát [`{fix_characters(track.title, limit=25)}`]({track.uri or track.search_uri}) đến vị trí **[{position}]** trong hàng.",
                f"↪️ **⠂{inter.author.mention} đã di chuyển một bài hát đến vị trí [{position}]:**\n"
                f"╰[`{fix_characters(track.title, limit=43)}`]({track.uri or track.search_uri})"
            ]

            await self.interaction_message(inter, txt, emoji="↪️")

        else:

            tracklist = "\n".join(f"[`{fix_characters(t.title, 45)}`]({t.uri or t.search_uri})" for i, t in indexes[:10])

            position_text = position if i_size == 1 else (str(position) + '-' + str(position+i_size-1))

            embed = disnake.Embed(
                color=self.bot.get_color(guild.me),
                description=f"↪️ **⠂{inter.author.mention} di chuyển [{i_size}] Bài hát có tên \"{query}\" đến " \
                            f"vị trí [{position_text}] trong hàng:**\n\n{tracklist}"
            )

            embed.set_thumbnail(url=indexes[0][1].thumb)

            if i_size > 20:
                embed.description += f"\n\n`Và hơn thế nữa {i_size - 20} Các bài hát.`"

            if player.controller_link:
                embed.description += f" `|`{player.controller_link}"

            ephemeral = await self.is_request_channel(inter)

            if ephemeral:
                player.set_command_log(
                    text=f"{inter.author.mention} di chuyển **[{i_size}]** Bài hát có tên **{fix_characters(query, 25)}"
                         f"** đến vị trí **[{position_text}]** trong hàng.", emoji="↪️")

            try:
                if bot.user.id != self.bot.user.id:
                    embed.set_footer(text=f"Sử dụng {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
            except AttributeError:
                pass

            await inter.send(embed=embed, ephemeral=ephemeral)

        await player.update_message()

    is_dj()
    @has_player()
    @check_voice()
    @pool_command(name="rotate", aliases=["rt", "rotacionar"], only_voiced=True,
                  description="Xoay hàng đợi cho nhạc được chỉ định.",
                  cooldown=queue_manipulation_cd, max_concurrency=remove_mc)
    async def rotate_legacy(self, ctx: CustomContext, *, flags: str = ""):

        args, unknown = self.case_sensitive_args.parse_known_args(flags.split())

        if not unknown:
            raise GenericError("**Bạn đã không thêm tên của bài hát.**")

        await self.rotate.callback(self=self, inter=ctx, query=" ".join(unknown), case_sensitive=args.casesensitive)

    @is_dj()
    @has_player()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Xoay hàng đợi cho nhạc được chỉ định.",
        extras={"only_voiced": True}, cooldown=queue_manipulation_cd, max_concurrency=remove_mc
    )
    async def rotate(
            self,
            inter: disnake.AppCmdInter,
            query: str = commands.Param(name="nome", description="Hoàn thành tên âm nhạc."),
            case_sensitive: bool = commands.Param(
                name="nome_exato", default=False,
                description="Tìm kiếm âm nhạc với lời bài hát chính xác thay vì tìm kiếm từng từ trong tên của âm nhạc",
            )
    ):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        index = queue_track_index(inter, bot, query, case_sensitive=case_sensitive)

        if not index:
            raise GenericError(f"**Không có bài hát nào phù hợp với tên: {query}**")

        index = index[0][0]

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        track = player.queue[index]

        if index <= 0:
            raise GenericError(f"**Đến âm nhạc **[`{track.title}`]({track.uri or track.search_uri}) Nó đã là dòng tiếp theo.")

        player.queue.rotate(0 - (index))

        txt = [
            f"Xoay dòng sang âm nhạc [`{(fix_characters(track.title, limit=25))}`]({track.uri or track.search_uri}).",
            f"🔃 **⠂{inter.author.mention} đã Xoay dòng sang âm nhạc:**\n╰[`{track.title}`]({track.uri or track.search_uri})."
        ]

        await self.interaction_message(inter, txt, emoji="🔃")

        await player.update_message()

    song_request_thread_cd = commands.CooldownMapping.from_cooldown(1, 120, commands.BucketType.guild)

    @is_dj()
    @has_player()
    @check_voice()
    @commands.bot_has_guild_permissions(manage_threads=True)
    @pool_command(name="songrequesttread", aliases=["songrequest", "srt"], only_voiced=True,
                  description="Tạo một cuộc trò chuyện chủ đề/tạm thời cho các yêu cầu bài hát (yêu cầu âm nhạc)")
    async def song_request_thread_legacy(self, ctx: CustomContext):

        await self.song_request_thread.callback(self=self, inter=ctx)

    @is_dj()
    @has_player()
    @check_voice()
    @commands.bot_has_guild_permissions(manage_threads=True)
    @commands.slash_command(extras={"only_voiced": True}, cooldown=song_request_thread_cd,
                            description=f"{desc_prefix}Tạo một cuộc trò chuyện chủ đề/tạm thời cho các yêu cầu bài hát (yêu cầu âm nhạc)")
    async def song_request_thread(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
            guild = inter.music_guild
        except AttributeError:
            bot = inter.bot
            guild = inter.guild

        if not self.bot.intents.message_content:
            raise GenericError("**Tôi hiện không có ý định có nội dung tin nhắn để hội tụir "
                               "Nội dung tin nhắn**")

        player: LavalinkPlayer = bot.music.players[guild.id]

        if player.static:
            raise GenericError("**Bạn không thể sử dụng lệnh này với kênh yêu cầu bài hát được cấu hình.**")

        if player.has_thread:
            raise GenericError("**Đã có một cuộc trò chuyện chủ đề/hoạt động trên người chơi.**")

        if not isinstance(player.text_channel, disnake.TextChannel):
            raise GenericError(f"**Trình điều khiển người chơi đang hoạt động trên một kênh không tương thích với"
                               f"Chủ đề/cuộc trò chuyện tạo ra.**")

        if not player.controller_mode:
            raise GenericError("**Xuất hiện da/hiện tại không tương thích với song-request "
                               "thông qua chủ đề/cuộc trò chuyện\n\n"
                               "Lưu ý: ** `Hệ thống này yêu cầu một làn da sử dụng các nút.`")

        await inter.response.defer(ephemeral=True)

        thread = await player.message.create_thread(name=f"{bot.user.name} temp. song-request", auto_archive_duration=10080)

        txt = [
            "Đã kích hoạt hệ thống trò chuyện tạm thời/chủ đề cho yêu cầu âm nhạc.",
            f"💬 **⠂{inter.author.mention} Đã tạo [Chủ đề/cuộc trò chuyện]({thread.jump_url}) tạm thời cho yêu cầu âm nhạc.**"
        ]

        await self.interaction_message(inter, txt, emoji="💬", defered=True, force=True)

    @rotate.autocomplete("nome")
    @move.autocomplete("nome")
    @skip.autocomplete("nome")
    @skipto.autocomplete("nome")
    @remove.autocomplete("nome")
    async def queue_tracks(self, inter: disnake.AppCmdInter, query: str):

        try:
            if not inter.author.voice:
                return
        except AttributeError:
            pass

        try:
            if not await check_pool_bots(inter, only_voiced=True):
                return
        except PoolException:
            pass
        except:
            return

        try:
            player = inter.music_bot.music.players[inter.guild_id]
        except KeyError:
            return

        results = []

        count = 0

        for track in player.queue:

            if count == 20:
                break

            title = track.title.lower().split()

            query_words = query.lower().split()

            word_count = 0

            for query_word in query.lower().split():
                for title_word in title:
                    if query_word in title_word:
                        title.remove(title_word)
                        word_count += 1
                        break

            if word_count == len(query_words):
                results.append(f"{track.title[:81]} || ID > {track.unique_id}")
                count += 1

        return results or [f"{track.title[:81]} || ID > {track.unique_id}" for n, track in enumerate(player.queue)
                if query.lower() in track.title.lower()][:20]

    nightcore_cd = commands.CooldownMapping.from_cooldown(1, 7, commands.BucketType.guild)
    nightcore_mc = commands.MaxConcurrency(1, per=commands.BucketType.guild, wait=False)

    @is_dj()
    @has_source()
    @check_voice()
    @pool_command(name="nightcore", aliases=["nc"], only_voiced=True, cooldown=nightcore_cd, max_concurrency=nightcore_mc,
                  description="Kích hoạt/Vô hiệu hóa hiệu ứng Nightcore (Nhạc tăng tốc với âm sắc hơn).")
    async def nightcore_legacy(self, ctx: CustomContext):

        await self.nightcore.callback(self=self, inter=ctx)

    @is_dj()
    @has_source()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Kích hoạt/Vô hiệu hóa hiệu ứng Nightcore (Nhạc tăng tốc với âm sắc hơn).",
        extras={"only_voiced": True}, cooldown=nightcore_cd, max_concurrency=nightcore_mc,
    )
    async def nightcore(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        player.nightcore = not player.nightcore

        if player.nightcore:
            await player.set_timescale(pitch=1.2, speed=1.1)
            txt = "kích hoạt"
        else:
            await player.set_timescale(enabled=False)
            await player.update_filters()
            txt = "vô hiệu hóa"

        txt = [f"{txt} Hiệu ứng Nightcore.", f"🇳 **⠂{inter.author.mention} {txt} hiệu ứng nightcore.**"]

        await self.interaction_message(inter, txt, emoji="🇳")

    controller_cd = commands.CooldownMapping.from_cooldown(1, 10, commands.BucketType.member)
    controller_mc = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @has_source()
    @check_voice()
    @pool_command(name="controller", aliases=["np", "ctl"], only_voiced=True, cooldown=controller_cd,
                  max_concurrency=controller_mc, description="Gửi bộ điều khiển người chơi đến một kênh cụ thể/hiện tại.")
    async def controller_legacy(self, ctx: CustomContext):
        await self.controller.callback(self=self, inter=ctx)

    @has_source()
    @check_voice()
    @commands.slash_command(description=f"{desc_prefix}Gửi bộ điều khiển người chơi đến một kênh cụ thể/hiện tại.",
                            extras={"only_voiced": True}, cooldown=controller_cd, max_concurrency=controller_mc,)
    async def controller(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
            guild = inter.music_guild
            channel = bot.get_channel(inter.channel.id)
        except AttributeError:
            bot = inter.bot
            guild = inter.guild
            channel = inter.channel

        player: LavalinkPlayer = bot.music.players[guild.id]

        if player.static:
            raise GenericError("Lệnh này không thể được sử dụng trong chế độ trình phát cố định.")

        if player.has_thread:
            raise GenericError("**Lệnh này không thể được sử dụng với một cuộc trò chuyện tích cực trong "
                               f"[tin nhắn]({player.message.jump_url}) của người chơi.**")

        if not inter.response.is_done():
            await inter.response.defer(ephemeral=True)

        if channel != player.text_channel:

            await is_dj().predicate(inter)

            try:

                player.set_command_log(
                    text=f"{inter.author.mention} đã đưa bảng điều khuyển đến kênh {inter.channel.mention}.",
                    emoji="💠"
                )

                embed = disnake.Embed(
                    description=f"💠 **⠂{inter.author.mention} đã đưa bảng điều khuyển đến kênh:** {channel.mention}",
                    color=self.bot.get_color(guild.me)
                )

                try:
                    if bot.user.id != self.bot.user.id:
                        embed.set_footer(text=f"Sử dụng {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
                except AttributeError:
                    pass

                await player.text_channel.send(embed=embed)

            except:
                pass

        await player.destroy_message()

        player.text_channel = channel

        await player.invoke_np()

        if not isinstance(inter, CustomContext):
            await inter.edit_original_message("**Người chơi đã được gửi lại thành công!**")

    @is_dj()
    @has_player()
    @check_voice()
    @commands.user_command(name=disnake.Localized("Add DJ", data={disnake.Locale.pt_BR: "Adicionar DJ"}),
                           extras={"only_voiced": True})
    async def adddj_u(self, inter: disnake.UserCommandInteraction):
        await self.add_dj(inter, user=inter.target)

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(name="adddj", aliases=["adj"], only_voiced=True,
                  description="Thêm một thành viên vào danh sách của DJ vào phiên người chơi hiện tại.")
    async def add_dj_legacy(self, ctx: CustomContext, user: Optional[disnake.Member] = None):

        if not user:
            raise GenericError(f"**Bạn đã không báo cáo một thành viên (ID, đề cập, tên, v.v.).**")

        await self.add_dj.callback(self=self, inter=ctx, user=user)

    @is_dj()
    @has_player()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Thêm một thành viên vào danh sách của DJ vào phiên người chơi hiện tại.",
        extras={"only_voiced": True}
    )
    async def add_dj(
            self,
            inter: disnake.AppCmdInter, *,
            user: disnake.User = commands.Param(name="membro", description="Chi để được thêm vào.")
    ):

        error_text = None

        try:
            bot = inter.music_bot
            guild = inter.music_guild
            channel = bot.get_channel(inter.channel.id)
        except AttributeError:
            bot = inter.bot
            guild = inter.guild
            channel = inter.channel

        player: LavalinkPlayer = bot.music.players[guild.id]

        user = guild.get_member(user.id)

        if user == inter.author:
            error_text = "**Bạn không thể tự thêm vào danh sách của DJ.**"
        elif user.guild_permissions.manage_channels:
            error_text = f"Bạn không thể thêm thành viên {user.mention} Trong danh sách DJ (anh ấy / cô ấy có quyền quản lý các kênh **)."
        elif user.id == player.player_creator:
            error_text = f"**Các thành viên {user.mention} là người tạo ra người chơi ...**"
        elif user.id in player.dj:
            error_text = f"**Các thành viên {user.mention} đã nằm trong danh sách của DJ**"

        if error_text:
            raise GenericError(error_text)

        player.dj.add(user.id)

        text = [f"thêm {user.mention} vào danh sách DJ.",
                f"🎧 **⠂{inter.author.mention} đã thêm {user.mention} Vào danh sách DJ**"]

        if (player.static and channel == player.text_channel) or isinstance(inter.application_command,
                                                                            commands.InvokableApplicationCommand):
            await inter.send(f"{user.mention} Đã thêm vào danh sách của DJ!{player.controller_link}")

        await self.interaction_message(inter, txt=text, emoji="🎧")

    @is_dj()
    @has_player()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Hủy bỏ một thành viên khỏi danh sách của DJ tại phiên người chơi hiện tại.",
        extras={"only_voiced": True}
    )
    async def remove_dj(
            self,
            inter: disnake.AppCmdInter, *,
            user: disnake.User = commands.Param(name="membro", description="Thành viên được thêm vào.")
    ):

        try:
            bot = inter.music_bot
            guild = inter.music_guild
            channel = bot.get_channel(inter.channel.id)
        except AttributeError:
            bot = inter.bot
            guild = inter.guild
            channel = inter.channel

        player: LavalinkPlayer = bot.music.players[guild.id]

        user = guild.get_member(user.id)

        if user.id == player.player_creator:
            if inter.author.guild_permissions.manage_guild:
                player.player_creator = None
            else:
                raise GenericError(f"**Các thành viên {user.mention} là người tạo ra người chơi.**")

        elif user.id not in player.dj:
            GenericError(f"Các thành viên {user.mention}  không ở trong danh sách DJ's")

        else:
            player.dj.remove(user.id)

        text = [f"LOẠI BỎ {user.mention} khỏi danh sách DJ's.",
                f"🎧 **⠂{inter.author.mention} LOẠI BỎ {user.mention} khỏi danh sách DJ's.**"]

        if (player.static and channel == player.text_channel) or isinstance(inter.application_command,
                                                                            commands.InvokableApplicationCommand):
            await inter.send(f"{user.mention} Được thêm vào danh sách của DJ's!{player.controller_link}")

        await self.interaction_message(inter, txt=text, emoji="🎧")

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(name="stop", aliases=["leave", "parar"], only_voiced=True,
                  description="Dừng người chơi và ngắt kết nối tôi khỏi kênh giọng nói.")
    async def stop_legacy(self, ctx: CustomContext):
        await self.stop.callback(self=self, inter=ctx)

    @is_dj()
    @has_player()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Dừng người chơi và ngắt kết nối tôi khỏi kênh giọng nói.",
        extras={"only_voiced": True}
    )
    async def stop(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
            inter_destroy = inter if bot.user.id == self.bot.user.id else None
            guild = inter.music_guild
        except AttributeError:
            bot = inter.bot
            inter_destroy = inter
            guild = inter.guild

        player: LavalinkPlayer = bot.music.players[inter.guild_id]
        player.command_log = f"{inter.author.mention} **đã dừng người chơi!**"

        if isinstance(inter, disnake.MessageInteraction):
            await player.destroy(inter=inter_destroy)
        else:

            embed = disnake.Embed(
                color=self.bot.get_color(guild.me),
                description=f"🛑 **⠂{inter.author.mention} đã dừng người chơi.**"
            )

            try:
                if bot.user.id != self.bot.user.id:
                    embed.set_footer(text=f"Sử dụng {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
            except AttributeError:
                pass

            await inter.send(
                embed=embed,
                components=[
                    disnake.ui.Button(label="Yêu cầu một bài hát", emoji="🎶", custom_id=PlayerControls.add_song),
                    disnake.ui.Button(label="Yêu thích/tích hợp", emoji="⭐", custom_id=PlayerControls.enqueue_fav)
                ] if inter.guild else [],
                ephemeral=player.static and player.text_channel.id == inter.channel_id
            )
            await player.destroy()

    @has_player()
    @check_voice()
    @commands.slash_command(name="queue", extras={"only_voiced": True})
    async def q(self, inter):
        pass

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(name="shuffle", aliases=["sf", "shf", "sff", "misturar"], only_voiced=True,
                  description="Trộn nhạc trong hàng đợi", cooldown=queue_manipulation_cd, max_concurrency=remove_mc)
    async def shuffle_legacy(self, ctx: CustomContext):
        await self.shuffle_.callback(self, inter=ctx)

    @is_dj()
    @q.sub_command(
        name="shuffle",
        description=f"{desc_prefix}Trộn nhạc trong hàng đợi",
        extras={"only_voiced": True}, cooldown=queue_manipulation_cd, max_concurrency=remove_mc)
    async def shuffle_(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if len(player.queue) < 3:
            raise GenericError("**Dòng phải có ít nhất 3 bài hát để được trộn lẫn.**")

        shuffle(player.queue)

        await self.interaction_message(
            inter,
            ["Trộn các bài hát từ dòng.",
             f"🔀 **⠂{inter.author.mention} Trộn các bài hát từ dòng.**"],
            emoji="🔀"
        )

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(name="reverse", aliases=["invert", "inverter", "rv"], only_voiced=True,
                  description="Đảo ngược thứ tự của các bài hát trong hàng", cooldown=queue_manipulation_cd, max_concurrency=remove_mc)
    async def reverse_legacy(self, ctx: CustomContext):
        await self.reverse.callback(self=self, inter=ctx)

    @is_dj()
    @q.sub_command(
        description=f"{desc_prefix}Đảo ngược thứ tự của các bài hát trong hàng",
        extras={"only_voiced": True}, cooldown=queue_manipulation_cd, max_concurrency=remove_mc
    )
    async def reverse(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if len(player.queue) < 2:
            raise GenericError("**Dòng phải có ít nhất 2 bài hát để đảo ngược thứ tự.**")

        player.queue.reverse()
        await self.interaction_message(
            inter,
            txt=["Đảo ngược thứ tự của các bài hát trong hàng.",
                 f"🔄 **⠂{inter.author.mention} Anh ấy đã đảo ngược thứ tự của các bài hát trong hàng.**"],
            emoji="🔄"
        )

    queue_show_mc = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @check_voice()
    @has_player()
    @check_voice()
    @pool_command(name="queue", aliases=["q", "fila"], description="Hiển thị các bài hát phù hợp.",
                  only_voiced=True, max_concurrency=queue_show_mc)
    async def queue_show_legacy(self, ctx: CustomContext):
        await self.display.callback(self=self, inter=ctx)

    @commands.max_concurrency(1, commands.BucketType.member)
    @q.sub_command(
        description=f"{desc_prefix}Hiển thị các bài hát phù hợp.", max_concurrency=queue_show_mc
    )
    async def display(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if not player.queue:
            raise GenericError("**Không có bài hát trong dòng.**")

        view = QueueInteraction(player, inter.author)
        embed = view.embed

        try:
            if bot.user.id != self.bot.user.id:
                embed.set_footer(text=f"Sử dụng {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
        except AttributeError:
            pass

        await inter.response.defer(ephemeral=True)

        kwargs = {
            "embed": embed,
            "view": view
        }

        try:
            func = inter.followup.send
            kwargs["ephemeral"] = True
        except AttributeError:
            try:
                func = inter.edit_original_message
            except AttributeError:
                func = inter.send
                kwargs["ephemeral"] = True

        view.message = await func(**kwargs)

        await view.wait()

    clear_flags = CommandArgparse()
    clear_flags.add_argument('song_name', nargs='*', help="Bao gồm tên bạn có trong âm nhạc.")
    clear_flags.add_argument('-uploader', '-author', '-artist', nargs = '+', default="",
                             help="Bao gồm một cái tên bạn có trong tác giả âm nhạc.")
    clear_flags.add_argument('-member', '-user', '-u', nargs='+', default="",
                             help="Bao gồm âm nhạc được yêu cầu bởi người dùng đã chọn.")
    clear_flags.add_argument('-duplicates', '-dupes', '-duplicate', action='store_true',
                             help="Bao gồm các bài hát trùng lặp.")
    clear_flags.add_argument('-playlist', '-list', '-pl', nargs='+', default="",
                             help="Bao gồm tên bạn có trên danh sách phát.")
    clear_flags.add_argument('-minimal_time', '-mintime', '-min','-min_duration', '-minduration',  default=None,
                             help="Bao gồm các bài hát có thời lượng tối thiểu được chỉ định (ví dụ 1:23).")
    clear_flags.add_argument('-max_time', '-maxtime', '-max', '-max_duration', '-maxduration', default=None,
                             help="Bao gồm các bài hát dòng từ một vị trí dòng cụ thể.")
    clear_flags.add_argument('-start_position', '-startpos', '-start', type=int, default=None,
                             help="Bao gồm các bài hát dòng từ một vị trí dòng cụ thể.")
    clear_flags.add_argument('-end_position', '-endpos', '-end', type=int, default=None,
                             help="Bao gồm các bài hát dòng vào một vị trí dòng cụ thể.")
    clear_flags.add_argument('-absent', '-absentmembers', '-abs', action='store_true',
                             help="Bao gồm các bài hát được thêm vào của các thành viên ngoài kênh")

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(name="clear", aliases=["limpar"], description="Làm sạch dòng nhạc.", only_voiced=True,
                  cooldown=queue_manipulation_cd, max_concurrency=remove_mc)
    async def clear_legacy(self, ctx: CustomContext, *, flags: str = ""):

        args, unknown = self.clear_flags.parse_known_args(flags.split())

        await self.clear.callback(
            self=self, inter=ctx,
            song_name=" ".join(args.song_name + unknown),
            song_author=" ".join(args.uploader),
            user=await commands.MemberConverter().convert(ctx, " ".join(args.member)) if args.member else None,
            duplicates=args.duplicates,
            playlist=" ".join(args.playlist),
            min_duration=args.minimal_time,
            max_duration=args.max_time,
            range_start=args.start_position,
            range_end=args.end_position,
            absent_members=args.absent
        )

    @is_dj()
    @has_player()
    @check_voice()
    @commands.slash_command(
        name="clear_queue",
        description=f"{desc_prefix}Làm sạch hàng đợi.",
        extras={"only_voiced": True}, cooldown=queue_manipulation_cd, max_concurrency=remove_mc
    )
    async def clear(
            self,
            inter: disnake.AppCmdInter,
            song_name: str = commands.Param(name="nome_da_música", description="incluir nome que tiver na música.",
                                            default=None),
            song_author: str = commands.Param(name="nome_do_autor",
                                              description="Incluir nome que tiver no autor da música.", default=None),
            user: disnake.Member = commands.Param(name='usuário',
                                                  description="Incluir músicas pedidas pelo usuário selecionado.",
                                                  default=None),
            duplicates: bool = commands.Param(name="duplicados", description="Incluir músicas duplicadas",
                                              default=False),
            playlist: str = commands.Param(description="Incluir nome que tiver na playlist.", default=None),
            min_duration: str = commands.Param(name="duração_inicial",
                                               description="incluir músicas com duração acima/igual (ex. 1:23).",
                                               default=None),
            max_duration: str = commands.Param(name="duração_máxima",
                                               description="incluir músicas com duração máxima especificada (ex. 1:45).",
                                               default=None),
            range_start: int = commands.Param(name="posição_inicial",
                                              description="incluir músicas da fila a partir de uma posição específica "
                                                          "da fila.",
                                              min_value=1.0, max_value=500.0, default=None),
            range_end: int = commands.Param(name="posição_final",
                                            description="incluir músicas da fila até uma posição específica da fila.",
                                            min_value=1.0, max_value=500.0, default=None),
            absent_members: bool = commands.Param(name="membros_ausentes",
                                                  description="Incluir músicas adicionads por membros fora do canal",
                                                  default=False)
    ):

        if min_duration and max_duration:
            raise GenericError(
                "Bạn chỉ nên chọn một trong các tùy chọn: ** Thời lượng_abaixa_de ** hoặc ** Thời lượng_acima_de**.")

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if not player.queue:
            raise GenericError("**Không có bài hát trong hàng.**")

        filters = []
        final_filters = set()

        txt = []
        playlist_hyperlink = set()

        if song_name:
            filters.append('song_name')
        if song_author:
            filters.append('song_author')
        if user:
            filters.append('user')
        if playlist:
            filters.append('playlist')
        if min_duration:
            filters.append('time_below')
            min_duration = string_to_seconds(min_duration) * 1000
        if max_duration:
            filters.append('time_above')
            max_duration = string_to_seconds(max_duration) * 1000
        if absent_members:
            filters.append('absent_members')
        if duplicates:
            filters.append('duplicates')

        if not filters and not range_start and not range_end:
            player.queue.clear()
            txt = ['xóa dòng nhạc.', f'♻️ **⠂{inter.author.mention} Làm sạch dòng nhạc.**']

        else:

            if range_start and range_end:

                if range_start >= range_end:
                    raise GenericError("**Vị trí cuối cùng phải lớn hơn vị trí bắt đầu!**")

                song_list = list(player.queue)[range_start - 1: range_end - 1]
                txt.append(f"**Vị trí hàng đợi ban đầu:** `{range_start}`\n"
                           f"**Vị trí dòng cuối cùng:** `{range_end}`")

            elif range_start:
                song_list = list(player.queue)[range_start - 1:]
                txt.append(f"**Vị trí hàng đợi ban đầu:** `{range_start}`")
            elif range_end:
                song_list = list(player.queue)[:range_end - 1]
                txt.append(f"**Vị trí dòng cuối cùng:** `{range_end}`")
            else:
                song_list = list(player.queue)

            deleted_tracks = 0

            duplicated_titles = set()

            for t in song_list:

                temp_filter = list(filters)

                if 'duplicates' in temp_filter:
                    if (title:=f"{t.author} - {t.title}".lower()) in duplicated_titles:
                        temp_filter.remove('duplicates')
                        final_filters.add('duplicates')
                    else:
                        duplicated_titles.add(title)

                if 'time_below' in temp_filter and t.duration >= min_duration:
                    temp_filter.remove('time_below')
                    final_filters.add('time_below')

                elif 'time_above' in temp_filter and t.duration <= max_duration:
                    temp_filter.remove('time_above')
                    final_filters.add('time_above')

                if 'song_name' in temp_filter and song_name.lower() in t.title.lower():
                    temp_filter.remove('song_name')
                    final_filters.add('song_name')

                if 'song_author' in temp_filter and song_author.lower() in t.author.lower():
                    temp_filter.remove('song_author')
                    final_filters.add('song_author')

                if 'user' in temp_filter and user.id == t.requester:
                    temp_filter.remove('user')
                    final_filters.add('user')

                elif 'absent_members' in temp_filter and t.requester not in player.guild.me.voice.channel.voice_states:
                    temp_filter.remove('absent_members')
                    final_filters.add('absent_members')

                if 'playlist' in temp_filter:
                    if playlist == t.playlist_name:
                        playlist_hyperlink.add(f"[`{fix_characters(t.playlist_name)}`]({t.playlist_urrl})")
                        temp_filter.remove('playlist')
                        final_filters.add('playlist')
                    elif isinstance(inter, CustomContext) and playlist.lower() in t.playlist_name.lower():
                        playlist = t.playlist_name
                        playlist_hyperlink.add(f"[`{fix_characters(t.playlist_name)}`]({t.playlist_urrl})")
                        temp_filter.remove('playlist')
                        final_filters.add('playlist')

                if not temp_filter:
                    player.queue.remove(t)
                    deleted_tracks += 1

            duplicated_titles.clear()

            if not deleted_tracks:
                await inter.send("Không tìm thấy bài hát!", ephemeral=True)
                return

            try:
                final_filters.remove("song_name")
                txt.append(f"**Bao gồm tên:** `{fix_characters(song_name)}`")
            except:
                pass

            try:
                final_filters.remove("song_author")
                txt.append(f"**Bao gồm tên trong trình tải lên/nghệ sĩ:** `{fix_characters(song_author)}`")
            except:
                pass

            try:
                final_filters.remove("user")
                txt.append(f"**pedidoPelCácThànhViên:** {user.mention}")
            except:
                pass

            try:
                final_filters.remove("playlist")
                txt.append(f"**Playlist:** `{fix_characters(playlist)}`")
            except:
                pass

            try:
                final_filters.remove("time_below")
                txt.append(f"**Với thời lượng ban đầu/bằng nhau:** `{time_format(min_duration)}`")
            except:
                pass

            try:
                final_filters.remove("time_above")
                txt.append(f"**Với thời lượng tối đa:** `{time_format(max_duration)}`")
            except:
                pass

            try:
                final_filters.remove("duplicates")
                txt.append(f"**Bài hát trùng lặp**")
            except:
                pass

            try:
                final_filters.remove("absent_members")
                txt.append("`Các bài hát được yêu cầu bởi các thành viên rời khỏi kênh.`")
            except:
                pass

            txt = [f"LOẠI BỎ {deleted_tracks} các bài hát thông qua clear.",
                   f"♻️ **⠂{inter.author.mention} LOẠI BỎ {deleted_tracks} Các bài hát từ dòng sử dụng các bài hát sau "
                   f"bộ lọc:**\n\n" + '\n'.join(txt)]

        await self.interaction_message(inter, txt, emoji="♻️")

    @clear.autocomplete("playlist")
    async def queue_playlist(self, inter: disnake.Interaction, query: str):

        try:
            if not inter.author.voice:
                return
        except:
            pass

        try:
            await check_pool_bots(inter, only_voiced=True)
            bot = inter.music_bot
        except:
            traceback.print_exc()
            return

        try:
            player = bot.music.players[inter.guild_id]
        except KeyError:
            return

        return list(set([track.playlist_name for track in player.queue if track.playlist_name and
                         query.lower() in track.playlist_name.lower()]))[:20]

    @clear.autocomplete("nome_do_autor")
    async def queue_author(self, inter: disnake.Interaction, query: str):

        if not query:
            return

        try:
            await check_pool_bots(inter, only_voiced=True)
            bot = inter.music_bot
        except:
            return

        if not inter.author.voice:
            return

        try:
            player = bot.music.players[inter.guild_id]
        except KeyError:
            return

        return list(set([track.author for track in player.queue if query.lower() in track.author.lower()]))[:20]

    restrict_cd = commands.CooldownMapping.from_cooldown(2, 7, commands.BucketType.member)
    restrict_mc =commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(name="restrict", aliases=["rstc", "restrito"], only_voiced=True, cooldown=restrict_cd, max_concurrency=restrict_mc,
                  description="Kích hoạt/Vô hiệu hóa chế độ lệnh hạn chế yêu cầu DJ/nhân viên.")
    async def restrict_mode_legacy(self, ctx: CustomContext):

        await self.restrict_mode.callback(self=self, inter=ctx)

    @is_dj()
    @has_player()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Kích hoạt/Vô hiệu hóa chế độ lệnh hạn chế của các lệnh yêu cầu DJ/nhân viên.",
        extras={"only_voiced": True}, cooldown=restrict_cd, max_concurrency=restrict_mc)
    async def restrict_mode(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        player.restrict_mode = not player.restrict_mode

        msg = ["kích hoạt", "🔐"] if player.restrict_mode else ["vô hiệu hóa", "🔓"]

        text = [
            f"{msg[0]} Chế độ hạn chế của các lệnh người chơi (yêu cầu DJ/nhân viên).",
            f"{msg[1]} **⠂{inter.author.mention} {msg[0]} Chế độ hạn chế của các lệnh người chơi (yêu cầu DJ/nhân viên).**"
        ]

        await self.interaction_message(inter, text, emoji=msg[1])

    nonstop_cd = commands.CooldownMapping.from_cooldown(2, 15, commands.BucketType.member)
    nonstop_mc =commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @has_player()
    @check_voice()
    @commands.has_guild_permissions(manage_guild=True)
    @pool_command(name="247", aliases=["nonstop"], only_voiced=True, cooldown=nonstop_cd, max_concurrency=nonstop_mc,
                  description="Kích hoạt/Tắt chế độ 24/7 của trình phát (trong các thử nghiệm).")
    async def nonstop_legacy(self, ctx: CustomContext):
        await self.nonstop.callback(self=self, inter=ctx)

    @has_player()
    @check_voice()
    @commands.slash_command(
        name="247",
        description=f"{desc_prefix}Kích hoạt/Vô hiệu hóa Chế độ 24/7 của trình phát (trong các thử nghiệm).",
        default_member_permissions=disnake.Permissions(manage_guild=True),
        extras={"only_voiced": True}, cooldown=nonstop_cd, max_concurrency=nonstop_mc
    )
    async def nonstop(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        player.keep_connected = not player.keep_connected

        msg = ["kích hoạt", "♾️"] if player.keep_connected else ["vô hiệu hóa", "❌"]

        text = [
            f"{msg[0]} Chế độ trình phát 24/7 (cài đặt).",
            f"{msg[1]} **⠂{inter.author.mention} {msg[0]} Chế độ 24/7 (cài đặt) của người chơi.**"
        ]

        if not len(player.queue):
            player.queue.extend(player.played)
            player.played.clear()

        await player.process_save_queue()

        if player.current:
            await self.interaction_message(inter, txt=text, emoji=msg[1])
            return

        await self.interaction_message(inter, text)

        await player.process_next()

    autoplay_cd = commands.CooldownMapping.from_cooldown(2, 15, commands.BucketType.member)
    autoplay_mc = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @has_player()
    @check_voice()
    @pool_command(name="autoplay", aliases=["ap", "aplay"], only_voiced=True, cooldown=autoplay_cd, max_concurrency=autoplay_mc,
                  description="Kích hoạt/tắt phát lại tự động bằng cách hoàn thành các dòng trong hàng đợi.")
    async def autoplay_legacy(self, ctx: CustomContext):
        await self.autoplay.callback(self=self, inter=ctx)

    @has_player()
    @check_voice()
    @commands.slash_command(
        name="autoplay",
        description=f"{desc_prefix}Kích hoạt/tắt phát lại tự động bằng cách hoàn thành các dòng trong hàng đợi.",
        extras={"only_voiced": True}, cooldown=autoplay_cd, max_concurrency=autoplay_mc
    )
    async def autoplay(self, inter: disnake.AppCmdInter):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        player.autoplay = not player.autoplay

        msg = ["kích hoạt", "🔄"] if player.autoplay else ["vô hiệu hóa", "❌"]

        text = [f"{msg[0]}  Tự động phát.", f"{msg[1]} **⠂{inter.author.mention} {msg[0]}  Tự động phát.**"]

        if player.current:
            await self.interaction_message(inter, txt=text, emoji=msg[1])
            return

        await self.interaction_message(inter, text)

        await player.process_next()

    @check_voice()
    @has_player()
    @is_dj()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    @commands.slash_command(
        description=f"{desc_prefix}Di chuyển người chơi sang một máy chủ âm nhạc khác."
    )
    async def change_node(
            self,
            inter: disnake.AppCmdInter,
            node: str = commands.Param(name="server", description="Máy chủ âm nhạc")
    ):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        if node not in bot.music.nodes:
            raise GenericError(f"Máy chủ âm nhạc **{node}** không tìm thấy.")

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if node == player.node.identifier:
            raise GenericError(f"Người chơi đã ở trên máy chủ âm nhạc **{node}**.")

        await player.change_node(node)

        await self.interaction_message(
            inter,
            [f"Di chuyển trình phát sang máy chủ âm nhạc **{node}**",
             f"**Người chơi đã được di chuyển đến máy chủ âm nhạc:** `{node}`"],
            emoji="🌎"
        )

    @search.autocomplete("server")
    @play.autocomplete("server")
    @change_node.autocomplete("server")
    async def node_suggestions(self, inter: disnake.Interaction, query: str):

        try:
            await check_pool_bots(inter)
            bot = inter.music_bot
        except GenericError:
            return
        except:
            bot = inter.bot

        try:
            node = bot.music.players[inter.guild_id].node
        except KeyError:
            node = None

        if not query:
            return [n.identifier for n in bot.music.nodes.values() if
                    n != node and n.available and n.is_available]

        return [n.identifier for n in bot.music.nodes.values() if n != node
                and query.lower() in n.identifier.lower() and n.available and n.is_available]

    @commands.command(aliases=["puptime"], description="Xem thông tin thời gian mà người chơi đang hoạt động trên máy chủ.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def playeruptime(self, ctx: CustomContext):

        uptime_info = []
        for bot in self.bot.pool.bots:
            try:
                player = bot.music.players[ctx.guild.id]
                uptime_info.append(f"**Bot:** {bot.user.mention}\n"
                            f"**Uptime:** <t:{player.uptime}:R>\n"
                            f"**Kênh:** {player.guild.me.voice.channel.mention}")
            except KeyError:
                continue

        if not uptime_info:
            raise GenericError("**Không có người chơi tích cực trên máy chủ.**")

        await ctx.reply(
            embed=disnake.Embed(
                title="**Player Uptime:**",
                description="\n-----\n".join(uptime_info),
                color=self.bot.get_color(ctx.guild.me)
            )
        )

    @commands.Cog.listener("on_message_delete")
    async def player_message_delete(self, message: disnake.Message):

        if not message.guild:
            return

        try:

            player: LavalinkPlayer = self.bot.music.players[message.guild.id]

            if message.id != player.message.id:
                return

        except (AttributeError, KeyError):
            return

        thread = self.bot.get_channel(message.id)

        if not thread:
            return

        player.message = None
        await thread.edit(archived=True, locked=True, name=f"arquivado: {thread.name}")

    @commands.Cog.listener('on_ready')
    async def resume_players_ready(self):

        for guild_id in list(self.bot.music.players):

            try:

                player: LavalinkPlayer = self.bot.music.players[guild_id]

                try:
                    vc = player.guild.me.voice.channel
                except AttributeError:
                    vc = player.last_channel

                try:
                    player.guild.voice_client.cleanup()
                except:
                    pass

                await player.connect(vc.id)

                if not player.is_paused and not player.is_playing:
                    await player.process_next()
                print(f"{self.bot.user} - {player.guild.name} [{guild_id}] - Người chơi kết nối lại không có kênh giọng nói")
            except:
                traceback.print_exc()

    async def is_request_channel(self, ctx: Union[disnake.AppCmdInter, disnake.MessageInteraction, CustomContext], *,
                                 data: dict = None, ignore_thread=False) -> bool:

        if isinstance(ctx, (CustomContext, disnake.MessageInteraction)):
            return True

        try:
            bot = ctx.music_bot
            channel_ctx = bot.get_channel(ctx.channel_id)
        except AttributeError:
            bot = ctx.bot
            channel_ctx = ctx.channel

        if not self.bot.check_bot_forum_post(channel_ctx):
            return True

        try:
            player: LavalinkPlayer = bot.music.players[ctx.guild_id]

            if not player.static:
                return False

            if isinstance(channel_ctx, disnake.Thread) and player.text_channel == channel_ctx.parent:
                return not ignore_thread

            return player.text_channel == channel_ctx

        except KeyError:

            try:
                guild_data = ctx.guild_data
            except AttributeError:
                guild_data = data or await bot.get_data(ctx.guild_id, db_name=DBModel.guilds)

            try:
                channel = bot.get_channel(int(guild_data["player_controller"]["channel"]))
            except:
                channel = None

            if not channel:
                return False

            if isinstance(channel_ctx, disnake.Thread) and channel == channel_ctx.parent:
                return not ignore_thread

            return channel.id == channel_ctx.id

    async def check_channel(
            self,
            guild_data: dict,
            inter: Union[disnake.AppCmdInter, CustomContext],
            channel: Union[disnake.TextChannel, disnake.VoiceChannel, disnake.Thread],
            guild: disnake.Guild,
            bot: BotCore
    ):

        static_player = guild_data['player_controller']

        warn_message = None

        try:
            channel_db = bot.get_channel(int(static_player['channel'])) or await bot.fetch_channel(
                int(static_player['channel']))
        except (TypeError, disnake.NotFound):
            channel_db = None
        except disnake.Forbidden:
            channel_db = bot.get_channel(inter.channel_id)
            warn_message = f"Tôi không được phép truy cập kênh <#{static_player['channel']}>, Người chơi sẽ được sử dụng ở chế độ truyền thống."
            static_player["channel"] = None

        if not channel_db or channel_db.guild.id != inter.guild_id:
            await self.reset_controller_db(inter.guild_id, guild_data, inter)

        else:

            if channel_db.id != channel.id:

                try:
                    if isinstance(channel_db, disnake.Thread):

                        if not channel_db.parent:
                            await self.reset_controller_db(inter.guild_id, guild_data, inter)
                            channel_db = None

                        else:

                            if (channel_db.archived or channel_db.locked) and not channel_db.parent.permissions_for(
                                    guild.me).manage_threads:
                                raise GenericError(
                                    f"**{bot.user.mention} không có quyền quản lý các chủ đề "
                                    f"Tickook/Untit chủ đề: {channel_db.mention}**")

                            await channel_db.edit(archived=False, locked=False)
                except AttributeError:
                    pass

                if channel_db:

                    channel_db_perms = channel_db.permissions_for(guild.me)

                    if not channel_db_perms.send_messages:
                        raise GenericError(
                            f"**{bot.user.mention} không có quyền gửi tin nhắn trên kênh <#{static_player['channel']}>**\n"
                            "Nếu bạn muốn đặt lại cài đặt của kênh để đặt hàng, hãy sử dụng lệnh /reset hoặc /setup "
                            "lại..."
                        )

                    if not channel_db_perms.embed_links:
                        raise GenericError(
                            f"**{bot.user.mention} không có quyền đính kèm liên kết/nhúng trên kênh <#{static_player['channel']}>**\n"
                            "Nếu bạn muốn đặt lại cài đặt của kênh để đặt hàng, hãy sử dụng lệnh /reset hoặc /setup "
                            "lại..."
                        )

        return channel_db, warn_message

    async def process_player_interaction(
            self,
            interaction: Union[disnake.MessageInteraction, disnake.ModalInteraction],
            command: Optional[disnake.AppCmdInter],
            kwargs: dict
    ):

        if not command:
            raise GenericError("Lệnh không tìm thấy/thực hiện.")

        await check_cmd(command, interaction)

        await command(interaction, **kwargs)

        try:
            player: LavalinkPlayer = self.bot.music.players[interaction.guild_id]
            player.interaction_cooldown = True
            await asyncio.sleep(1)
            player.interaction_cooldown = False
            await command._max_concurrency.release(interaction)
        except (KeyError, AttributeError):
            pass

    @commands.Cog.listener("on_dropdown")
    async def guild_pin(self, interaction: disnake.MessageInteraction):

        if not self.bot.bot_ready:
            await interaction.send("ATôi đang khởi tạo...\nVui lòng đợi lâu hơn một chút...", ephemeral=True)
            return

        if interaction.data.custom_id != "player_guild_pin":
            return

        if not interaction.data.values:
            await interaction.response.defer()
            return

        if not interaction.user.voice:
            await interaction.send("Bạn phải nhập một kênh giọng nói để sử dụng điều này.", ephemeral=True)
            return

        try:
            guild_data = interaction.guild_data
        except AttributeError:
            guild_data = await self.bot.get_data(interaction.guild_id, db_name=DBModel.guilds)
            interaction.guild_data = guild_data

        try:
            query = guild_data["player_controller"]["fav_links"][interaction.data.values[0]]['url']
        except KeyError:
            raise GenericError("**Mục đã chọn không được tìm thấy trong cơ sở dữ liệu...**")

        kwargs = {
            "query": f"> pin: {query}",
            "position": 0,
            "options": False,
            "manual_selection": True,
            "source": "ytsearch",
            "repeat_amount": 0,
            "server": None,
            "force_play": "no"
        }

        try:
            await self.play.callback(self=self, inter=interaction, **kwargs)
        except Exception as e:
            self.bot.dispatch('interaction_player_error', interaction, e)

    @commands.Cog.listener("on_dropdown")
    async def player_dropdown_event(self, interaction: disnake.MessageInteraction):

        if not interaction.data.custom_id.startswith("musicplayer_dropdown_"):
            return

        if not interaction.values:
            await interaction.response.defer()
            return

        await self.player_controller(interaction, interaction.values[0])

    @commands.Cog.listener("on_button_click")
    async def player_button_event(self, interaction: disnake.MessageInteraction):

        if not interaction.data.custom_id.startswith("musicplayer_"):
            return

        await self.player_controller(interaction, interaction.data.custom_id)

    async def player_controller(self, interaction: disnake.MessageInteraction, control: str):

        if not self.bot.bot_ready:
            await interaction.send("Tôi vẫn bắt đầu...", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.edit_message(components=None)
            return

        kwargs = {}

        cmd: Optional[disnake.AppCmdInter] = None

        try:

            if control == "musicplayer_request_channel":
                cmd = self.bot.get_slash_command("setup")
                kwargs = {"target": interaction.channel}
                await self.process_player_interaction(interaction, cmd, kwargs)
                return

            if control == PlayerControls.fav_manageer:

                if str(interaction.user.id) not in interaction.message.content:
                    await interaction.send("Bạn không thể tương tác ở đây!", ephemeral=True)
                    return

                cmd = self.bot.get_slash_command("fav").children.get("manager")
                await self.process_player_interaction(interaction, cmd, kwargs)
                return

            if control == PlayerControls.integration_manageer:

                if str(interaction.user.id) not in interaction.message.content:
                    await interaction.send("Bạn không thể tương tác ở đây!", ephemeral=True)
                    return

                cmd = self.bot.get_slash_command("integration").children.get("manager") 
                await self.process_player_interaction(interaction, cmd, kwargs)
                return

            if control == PlayerControls.add_song:

                if not interaction.user.voice:
                    raise GenericError("**Bạn phải vào một kênh thoại để sử dụng nút này.**")

                await interaction.response.send_modal(
                    title="Yêu cầu một bài hát",
                    custom_id="modal_add_song",
                    components=[
                        disnake.ui.TextInput(
                            style=disnake.TextInputStyle.short,
                            label="Tên/liên kết âm nhạc.",
                            placeholder="Tên hoặc liên kết YouTube/Spotify/SoundCloud, v.v.",
                            custom_id="song_input",
                            max_length=150,
                            required=True
                        ),
                        disnake.ui.TextInput(
                            style=disnake.TextInputStyle.short,
                            label="Vị trí bài hát sẽ được thêm vào.",
                            placeholder="Tùy chọn, nếu không được sử dụng sẽ được thêm vào cuối.",
                            custom_id="song_position",
                            max_length=3,
                            required=False
                        ),
                    ]
                )

                return

            if control == PlayerControls.enqueue_fav:

                kwargs = {
                    "query": "",
                    "position": 0,
                    "options": False,
                    "manual_selection": True,
                    "source": "ytsearch",
                    "repeat_amount": 0,
                    "server": None,
                    "force_play": "no"
                }

                cmd = self.bot.get_slash_command("play")

            else:

                try:
                    player: LavalinkPlayer = self.bot.music.players[interaction.guild_id]
                except KeyError:
                    await interaction.send("Không có trình phát đang hoạt động trên máy chủ...", ephemeral=True)
                    await send_idle_embed(interaction.message, bot=self.bot)
                    return

                if interaction.message != player.message:
                    return

                if player.interaction_cooldown:
                    raise GenericError("Thao tác quá nhanh, hãy thao tác lại")

                try:
                    vc = player.guild.me.voice.channel
                except AttributeError:
                    self.bot.loop.create_task(player.destroy(force=True))
                    return

                if control == PlayerControls.help_button:
                    embed = disnake.Embed(
                        description="📘 **Thông tin nút** 📘\n\n"
                                    "⏯️ `= Tạm dừng/trả lại âm nhạc.`\n"
                                    "⏮️ `= Trở lại với âm nhạc được phát trước đó.`\n"
                                    "⏭️ `= Nhảy sang bài hát tiếp theo.`\n"
                                    "🔀 `=Trộn âm nhạc trong dòng.`\n"
                                    "🎶 `= Thêm nhạc/danh sách phát/yêu thích.`\n"
                                    "⏹️ `= Dừng người chơi và ngắt kết nối tôi khỏi kênh.`\n"
                                    "📑 `= Hiển thị dòng nhạc.`\n"
                                    "🛠️ `= Thay đổi một số cài đặt người chơi:`\n"
                                    "`Âm lượng / Hiệu ứng Nightcore / sự lặp lại / chế độ bị hạn chế.`\n",
                        color=self.bot.get_color(interaction.guild.me)
                    )

                    await interaction.response.send_message(embed=embed, ephemeral=True)    
                    return

                if not interaction.author.voice or interaction.author.voice.channel != vc:
                    raise GenericError(f"Bạn phải ở trên kênh <#{vc.id}> Để sử dụng các nút người chơi.")

                if control == PlayerControls.miniqueue:
                    await is_dj().predicate(interaction)
                    player.mini_queue_enabled = not player.mini_queue_enabled
                    player.set_command_log(
                        emoji="📑",
                        text=f"{interaction.author.mention} {'kích hoạt' if player.mini_queue_enabled else 'vô hiệu hóa'} "
                             f"Danh sách hàng chờ mini."
                    )
                    await player.invoke_np(interaction=interaction)
                    return

                if control == PlayerControls.volume:
                    kwargs = {"value": None}

                elif control == PlayerControls.queue:
                    cmd = self.bot.get_slash_command("queue").children.get("display")

                elif control == PlayerControls.shuffle:
                    cmd = self.bot.get_slash_command("queue").children.get("shuffle")

                elif control == PlayerControls.seek_to_start:
                    cmd = self.bot.get_slash_command("seek")
                    kwargs = {"position": "0"}

                elif control == PlayerControls.pause_resume:
                    control = PlayerControls.pause if not player.paused else PlayerControls.resume

                elif control == PlayerControls.loop_mode:

                    if player.loop == "current":
                        kwargs['mode'] = 'queue'
                    elif player.loop == "queue":
                        kwargs['mode'] = 'off'
                    else:
                        kwargs['mode'] = 'current'

                elif control == PlayerControls.skip:
                    kwargs = {"query": None, "play_only": "no"}

                try:
                    await self.player_interaction_concurrency.acquire(interaction)
                except commands.MaxConcurrencyReached:
                    raise GenericError(
                        "**Bạn có một tương tác mở!**\n`Nếu đó là một tin nhắn ẩn, tránh nhấp vào \"bỏ qua\".`")

            if not cmd:
                cmd = self.bot.get_slash_command(control[12:])

            await self.process_player_interaction(
                interaction=interaction,
                command=cmd,
                kwargs=kwargs
            )

            try:
                await self.player_interaction_concurrency.release(interaction)
            except:
                pass

        except Exception as e:
            try:
                await self.player_interaction_concurrency.release(interaction)
            except:
                pass
            self.bot.dispatch('interaction_player_error', interaction, e)

    @commands.Cog.listener("on_modal_submit")
    async def song_request_modal(self, inter: disnake.ModalInteraction):

        if inter.custom_id == "modal_add_song":

            try:

                query = inter.text_values["song_input"]
                position = inter.text_values["song_position"]

                if position:
                    if not position.isdigit():
                        raise GenericError("**Vị trí của dòng phải là một số.**")
                    position = int(position)

                    if position < 1:
                        raise GenericError("**Số vị trí Rinning phải là 1 hoặc cao hơn.**")

                kwargs = {
                    "query": query,
                    "position": position or 0,
                    "options": False,
                    "manual_selection": True,
                    "source": "ytsearch",
                    "repeat_amount": 0,
                    "server": None,
                    "force_play": "no",
                }

                await self.process_player_interaction(
                    interaction=inter,
                    command=self.bot.get_slash_command("play"),
                    kwargs=kwargs,
                )
            except Exception as e:
                self.bot.dispatch('interaction_player_error', inter, e)

    async def delete_message(self, message: disnake.Message, delay: int = None):

        try:
            is_forum = isinstance(message.channel.parent, disnake.ForumChannel)
        except AttributeError:
            is_forum = False

        if message.is_system() and is_forum:
            return

        if message.guild.me.guild_permissions.manage_messages:

            try:
                await message.delete(delay=delay)
            except:
                traceback.print_exc()

    @commands.Cog.listener("on_song_request")
    async def song_requests(self, ctx: Optional[CustomContext], message: disnake.Message):

        if ctx.command or message.mentions:
            return

        if message.author.bot and not isinstance(message.channel, disnake.StageChannel):
            return

        if message.content.startswith("/"):
            await self.delete_message(message)
            return

        try:
            data = await self.bot.get_data(message.guild.id, db_name=DBModel.guilds)
        except AttributeError:
            return

        player: Optional[LavalinkPlayer] = self.bot.music.players.get(message.guild.id)

        if player and isinstance(message.channel, disnake.Thread) and not player.static:

            if player.message.id != message.channel.id:
                return

            if not player.controller_mode:
                return

            text_channel = message.channel

        else:

            static_player = data['player_controller']

            channel_id = static_player['channel']

            if not channel_id or (
                    static_player['message_id'] != str(message.channel.id) and str(message.channel.id) != channel_id):
                return

            text_channel = self.bot.get_channel(int(channel_id))

            if not text_channel or not text_channel.permissions_for(message.guild.me).send_messages:
                return

            if not self.bot.intents.message_content:

                if self.song_request_cooldown.get_bucket(message).update_rate_limit():
                    return

                await message.channel.send(
                    message.author.mention,
                    embed=disnake.Embed(
                        description="Thật không may, tôi không thể kiểm tra nội dung của tin nhắn của bạn...\n"
                                    "Cố gắng thêm nhạc bằng cách sử dụng **/play ** hoặc nhấp vào một trong các nút bên dưới:",
                        color=self.bot.get_color(message.guild.me)
                    ),
                    components=[
                        disnake.ui.Button(emoji="🎶", custom_id=PlayerControls.add_song, label="Yêu cầu một bài hát"),
                        disnake.ui.Button(emoji="⭐", custom_id=PlayerControls.enqueue_fav, label="Chơi yêu thích/tích hợp ")
                    ],
                    delete_after=20
                )
                return

        try:
            if isinstance(message.channel, disnake.Thread):

                if isinstance(message.channel.parent, disnake.ForumChannel):

                    if data['player_controller']["channel"] != str(message.channel.id):
                        return
                    if message.is_system():
                        await self.delete_message(message)

        except AttributeError:
            pass

        msg = None
        error = None
        has_exception = None

        try:
            if message.author.bot:
                if message.is_system() and not isinstance(message.channel, disnake.Thread):
                    await self.delete_message(message)
                if message.author.id == self.bot.user.id:
                    await self.delete_message(message, delay=15)
                return

            if not message.content:

                if message.type == disnake.MessageType.thread_starter_message:
                    return

                if message.is_system():
                    await self.delete_message(message)
                    return

                try:
                    attachment = message.attachments[0]
                except IndexError:
                    await message.channel.send(f"{message.author.mention} Bạn phải gửi tên/tên âm nhạc.")
                    return

                else:

                    if attachment.size > 18000000:
                        await message.channel.send(f"{message.author.mention} Tệp bạn đã gửi phải có kích thướco "
                                                   f"kém hơn 18MB.")
                        return

                    if attachment.content_type not in self.audio_formats:
                        await message.channel.send(f"{message.author.mention} Tệp bạn đã gửi phải có kích thước "
                                                   f"kém hơn 18MB.")
                        return

                    message.content = attachment.url

            try:
                await self.song_request_concurrency.acquire(message)
            except:

                await message.channel.send(
                    f"{message.author.mention} Bạn phải đợi đơn hàng âm nhạc trước đây của bạn để tải...",
                )

                await self.delete_message(message)
                return

            message.content = message.content.strip("<>")

            urls = URL_REG.findall(message.content)

            if not urls:
                message.content = f"ytsearch:{message.content}"

            else:
                message.content = urls[0]

                if "&list=" in message.content:

                    view = SelectInteraction(
                        user=message.author,
                        opts=[
                            disnake.SelectOption(label="Bài hát", emoji="🎵",
                                                 description="Chỉ tải nhạc từ liên kết.", value="music"),
                            disnake.SelectOption(label="Playlist", emoji="🎶",
                                                 description="Chơi danh sách phát với âm nhạc hiện tại.", value="playlist"),
                        ], timeout=30)

                    embed = disnake.Embed(
                        description="**Liên kết chứa video với danh sách phát.**\n"
                                    f'Chọn một tùy chọn trong <t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=30)).timestamp())}:R> ',
                        color=self.bot.get_color(message.guild.me)
                    )

                    msg = await message.channel.send(message.author.mention, embed=embed, view=view)

                    await view.wait()

                    try:
                        await view.inter.response.defer()
                    except:
                        pass

                    if view.selected == "music":
                        message.content = YOUTUBE_VIDEO_REG.match(message.content).group()

            await self.parse_song_request(message, text_channel, data, response=msg)

        except GenericError as e:
            error = f"{message.author.mention}. {e}"

        except Exception as e:
            traceback.print_exc()
            has_exception = e
            error = f"{message.author.mention} **Đã xảy ra lỗi khi cố gắng nhận kết quả cho tìm kiếm của bạn:** ```py\n{e}```"

        if error:

            await self.delete_message(message)

            try:
                if msg:
                    await msg.edit(content=error, embed=None, view=None)
                else:
                    await message.channel.send(error)
            except:
                traceback.print_exc()

        await self.song_request_concurrency.release(message)

        if has_exception and self.bot.config["AUTO_ERROR_REPORT_WEBHOOK"]:

            cog = self.bot.get_cog("ErrorHandler")

            if not cog:
                return

            max_concurrency = cog.webhook_max_concurrency

            await max_concurrency.acquire(message)

            try:
                error_msg, full_error_msg, kill_process = parse_error(message, has_exception)

                embed = disnake.Embed(
                    title="Xảy ra lỗi trên máy chủ (song-request):",
                    timestamp=disnake.utils.utcnow(),
                    description=f"```py\n{repr(has_exception)[:2030].replace(self.bot.http.token, 'mytoken')}```"
                )

                embed.set_footer(
                    text=f"{message.author} [{message.author.id}]",
                    icon_url=message.author.display_avatar.with_static_format("png").url
                )

                embed.add_field(
                    name="Máy chủ:", inline=False,
                    value=f"```\n{disnake.utils.escape_markdown(ctx.guild.name)}\nID: {ctx.guild.id}```"
                )

                embed.add_field(
                    name="Nội dung yêu cầu âm nhạc:", inline=False,
                    value=f"```\n{message.content}```"
                )

                embed.add_field(
                    name="Kênh văn bản:", inline=False,
                    value=f"```\n{disnake.utils.escape_markdown(ctx.channel.name)}\nID: {ctx.channel.id}```"
                )

                if vc := ctx.author.voice:
                    embed.add_field(
                        name="Kênh thoại (người dùng):", inline=False,
                        value=f"```\n{disnake.utils.escape_markdown(vc.channel.name)}" +
                              (f" ({len(vc.channel.voice_states)}/{vc.channel.user_limit})"
                               if vc.channel.user_limit else "") + f"\nID: {vc.channel.id}```"
                    )

                if vcbot := ctx.guild.me.voice:
                    if vcbot.channel != vc.channel:
                        embed.add_field(
                            name="Kênh thoại (bot):", inline=False,
                            value=f"{vc.channel.name}" +
                                  (f" ({len(vc.channel.voice_states)}/{vc.channel.user_limit})"
                                   if vc.channel.user_limit else "") + f"\nID: {vc.channel.id}```"
                        )

                if ctx.guild.icon:
                    embed.set_thumbnail(url=ctx.guild.icon.with_static_format("png").url)

                await cog.send_webhook(
                    embed=embed,
                    file=string_to_file(full_error_msg, "error_traceback_songrequest.txt")
                )

            except:
                traceback.print_exc()

            await asyncio.sleep(20)

            try:
                await max_concurrency.release(message)
            except:
                pass


    async def parse_song_request(self, message, text_channel, data, *, response=None, attachment: disnake.Attachment=None):

        if not message.author.voice:
            raise GenericError("Bạn phải nhập một kênh giọng nói để yêu cầu một bài hát.")

        can_connect(
            channel=message.author.voice.channel,
            guild=message.guild,
            check_other_bots_in_vc=data["check_other_bots_in_vc"],
            bot=self.bot
        )

        try:
            if message.guild.me.voice.channel != message.author.voice.channel:
                raise GenericError(
                    f"Bạn phải vào kênh <#{message.guild.me.voice.channel.id}> Để đặt một bài hát.")
        except AttributeError:
            pass

        tracks, node = await self.get_tracks(message.content, message.author)

        try:
            message_id = int(data['player_controller']['message_id'])
        except TypeError:
            message_id = None

        try:
            player = self.bot.music.players[message.guild.id]
            destroy_message = True
        except KeyError:
            destroy_message = False
            skin = data["player_controller"]["skin"]
            static_skin = data["player_controller"]["static_skin"]

            global_data = await self.bot.get_global_data(message.guild.id, db_name=DBModel.guilds)

            if global_data["global_skin"]:
                skin = global_data["player_skin"] or skin
                static_skin = global_data["player_skin_static"] or static_skin

            try:
                invite = global_data["listen_along_invites"][str(message.author.voice.channel.id)]
            except (KeyError, AttributeError):
                invite = None

            else:
                if not await self.bot.fetch_invite(invite):
                    print(
                        f'{"-"*15}\n'
                        f'Loại bỏ lời mời: {invite} \n'
                        f'Máy chủ: {message.guild.name} [{message.guild.id}]\n'
                        f'Kênh: {message.channel.name} [{message.channel.id}]\n'
                        f'{"-" * 15}'
                    )
                    invite = None
                    del global_data["listen_along_invites"][str(message.author.voice.channel.id)]
                    await self.bot.update_global_data(message.guild.id, global_data, db_name=DBModel.guilds)

            player: LavalinkPlayer = self.bot.music.get_player(
                guild_id=message.guild.id,
                cls=LavalinkPlayer,
                player_creator=message.author.id,
                guild=message.guild,
                channel=text_channel,
                static=True,
                skin=self.bot.check_skin(skin),
                skin_static=self.bot.check_static_skin(static_skin),
                custom_skin_data=global_data["custom_skins"],
                custom_skin_static_data=global_data["custom_skins_static"],
                node_id=node.identifier,
                extra_hints=self.extra_hints,
                last_message_id=message_id,
                restrict_mode=data['enable_restrict_mode'],
                listen_along_invite=invite,
                volume=int(data['default_player_volume']),
                autoplay=data["autoplay"],
                prefix=global_data["prefix"] or self.bot.default_prefix,
            )

        if not player.message:
            try:
                cached_message = await text_channel.fetch_message(message_id)
            except:
                cached_message = await send_idle_embed(message, bot=self.bot)
                data['player_controller']['message_id'] = str(cached_message.id)
                await self.bot.update_data(message.guild.id, data, db_name=DBModel.guilds)

            player.message = cached_message

        embed = disnake.Embed(color=self.bot.get_color(message.guild.me))

        if not isinstance(tracks, list):
            player.queue.extend(tracks.tracks)
            if isinstance(message.channel, disnake.Thread) and not isinstance(message.channel.parent,
                                                                              disnake.ForumChannel):
                embed.description = f"✋ **⠂ Được yêu cầu bởi:** {message.author.mention}\n" \
                                    f"🎼 **⠂ Các bài hát:** `[{len(tracks.tracks)}]`"
                embed.set_thumbnail(url=tracks.tracks[0].thumb)
                embed.set_author(name="⠂" + fix_characters(tracks.tracks[0].playlist_name, 35), url=message.content,
                                 icon_url=music_source_image(tracks.tracks[0].info["sourceName"]))
                if response:
                    await response.edit(content=None, embed=embed, view=None)
                else:
                    await message.channel.send(embed=embed)

            else:
                player.set_command_log(
                    text=f"{message.author.mention} Đã thêm danh sách phát [`{fix_characters(tracks.data['playlistInfo']['name'], 20)}`]"
                         f"({tracks.tracks[0].playlist_url}) `({len(tracks.tracks)})`.",
                    emoji="🎶"
                )
                if destroy_message:
                    await self.delete_message(message)
                    if response:
                        await self.delete_message(response)

        else:
            track = tracks[0]

            if track.info.get("sourceName") == "http":

                if track.title == "Unknown title":
                    if attachment:
                        track.info["title"] = attachment.filename
                    else:
                        track.info["title"] = track.uri.split("/")[-1]
                    track.title = track.info["title"]

                track.uri = ""

            player.queue.append(track)
            if isinstance(message.channel, disnake.Thread) and not isinstance(message.channel.parent,
                                                                              disnake.ForumChannel):
                embed.description = f"💠 **⠂ Người tải lên:** `{track.author}`\n" \
                                    f"✋ **⠂ Được yêu cầu bởi:** {message.author.mention}\n" \
                                    f"⌛ **⠂ Thời lượng** `{time_format(track.duration) if not track.is_stream else '🔴 Livestream'}` "
                embed.set_thumbnail(url=track.thumb)
                embed.set_author(name=fix_characters(track.title, 35), url=track.uri or track.search_uri, icon_url=music_source_image(track.info["sourceName"]))
                if response:
                    await response.edit("<:verify:1134033164151566460> **Thêm bài hát thành công**", content=None, embed=embed, view=None)
                else:
                    await message.channel.send("<:verify:1134033164151566460> **Thêm bài hát thành công**", embed=embed)

            else:
                duration = time_format(tracks[0].duration) if not tracks[0].is_stream else '🔴 Livestream'
                player.set_command_log(
                    text=f"{message.author.mention} thêm [`{fix_characters(tracks[0].title, 20)}`]({tracks[0].uri or tracks[0].search_uri}) `({duration})`.",
                    emoji="🎵"
                )
                if destroy_message:
                    await self.delete_message(message)
                    if response:
                        await self.delete_message(response)

        if not player.is_connected:
            await self.do_connect(
                message,
                channel=message.author.voice.channel,
                check_other_bots_in_vc=data["check_other_bots_in_vc"]
            )

        if not player.current:
            await player.process_next()
        else:
            await player.update_message()

        await asyncio.sleep(1)

    async def cog_check(self, ctx: CustomContext) -> bool:

        return await check_requester_channel(ctx)

    async def interaction_message(self, inter: Union[disnake.Interaction, CustomContext], txt, emoji: str = "<:verify:1134033164151566460>",
                                  rpc_update: bool = False, data: dict = None, store_embed: bool = False, force=False,
                                  defered=False):

        try:
            txt, txt_ephemeral = txt
        except:
            txt_ephemeral = False

        try:
            bot = inter.music_bot
            guild = inter.music_guild
        except AttributeError:
            bot = inter.bot
            guild = inter.guild

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        component_interaction = isinstance(inter, disnake.MessageInteraction)

        ephemeral = await self.is_request_channel(inter, data=data)

        if ephemeral:
            player.set_command_log(text=f"{inter.author.mention} {txt}", emoji=emoji)
            player.update = True

        await player.update_message(interaction=inter if (bot.user.id == self.bot.user.id and component_interaction) \
            else False, rpc_update=rpc_update, force=force)

        if isinstance(inter, CustomContext):
            embed = disnake.Embed(color=self.bot.get_color(guild.me),
                                  description=f"{txt_ephemeral or txt}{player.controller_link}")

            try:
                if bot.user.id != self.bot.user.id:
                    embed.set_footer(text=f"Sử dụng {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
            except AttributeError:
                pass

            if store_embed and not player.controller_mode and len(player.queue) > 0:
                player.temp_embed = embed

            else:
                try:
                    await inter.store_message.edit(embed=embed, view=None, content=None)
                except AttributeError:
                    await inter.send(embed=embed)

        elif not component_interaction:

            if not inter.response.is_done():
                embed = disnake.Embed(
                    color=self.bot.get_color(guild.me),
                    description=(txt_ephemeral or f"{inter.author.mention} **{txt}**") + player.controller_link
                )

                try:
                    if bot.user.id != self.bot.user.id:
                        embed.set_footer(text=f"Sử dụng {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
                except AttributeError:
                    pass

                await inter.send(embed=embed, ephemeral=ephemeral)

        elif not component_interaction:

            if not inter.response.is_done():
                embed = disnake.Embed(
                    color=self.bot.get_color(guild.me),
                    description=(txt_ephemeral or f"{inter.author.mention} **{txt}**") + player.controller_link
                )

                try:
                    if bot.user.id != self.bot.user.id:
                        embed.set_footer(text=f"Via: {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
                except AttributeError:
                    pass

                await inter.send(embed=embed, ephemeral=ephemeral)

            elif defered:
                embed = disnake.Embed(
                    color=self.bot.get_color(guild.me),
                    description=(txt_ephemeral or f"{inter.author.mention} **{txt}**") + player.controller_link
                )

                try:
                    if bot.user.id != self.bot.user.id:
                        embed.set_footer(text=f"Thông qua: {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
                except AttributeError:
                    pass

                await inter.edit_original_response(embed=embed)

    async def process_nodes(self, data: dict, start_local: bool = False):

        await self.bot.wait_until_ready()

        if str(self.bot.user.id) in self.bot.config["INTERACTION_BOTS_CONTROLLER"]:
            return

        for k, v in data.items():
            self.bot.loop.create_task(self.connect_node(v))

        if start_local:
            self.bot.loop.create_task(self.connect_local_lavalink())

    @commands.Cog.listener("on_wavelink_node_connection_closed")
    async def node_connection_closed(self, node: wavelink.Node):

        retries = 0
        backoff = 7

        if not node.restarting:

            print(f"{self.bot.user} - [{node.identifier}] Kết nối bị mất - kết nối lại trong {int(backoff)} giây.")

            for player in list(node.players.values()):

                try:

                    try:
                        new_node: wavelink.Node = await self.get_best_node()
                    except:
                        try:
                            await player.text_channel.send(
                                "Người chơi đã tắt vì thiếu máy chủ âm nhạc...",
                                delete_after=11)
                        except:
                            pass
                        await player.destroy()
                        continue

                    await player.change_node(new_node.identifier)
                    await player.update_message()

                except:
                    traceback.print_exc()
                    continue

        await asyncio.sleep(backoff)

        while True:

            if retries == 30:
                print(f"{self.bot.user} - [{node.identifier}] Tất cả các nỗ lực để điều chỉnh lại thất bại...")
                return

            await self.bot.wait_until_ready()

            try:
                async with self.bot.session.get(node.rest_uri) as r:
                    if r.status in [401, 200, 400]:
                        await node.connect(self.bot)
                        return
                    error = r.status
            except Exception as e:
                error = repr(e)

            backoff *= 1.5
            print(
                f'{self.bot.user} - Không kết nối lại với máy chủ [{node.identifier}] thử lại su {int(backoff)}'
                f' giây.Lỗi: {error}')
            await asyncio.sleep(backoff)
            retries += 1
            continue

    @commands.Cog.listener("on_wavelink_websocket_closed")
    async def node_ws_voice_closed(self, node, payload: wavelink.events.WebsocketClosed):

        if payload.code == 1000:
            return

        player: LavalinkPlayer = payload.player

        if not player.guild.me:
            return

        try:
            vc = player.last_channel or player.guild.me.voice.channel
        except AttributeError:
            vc = None

        if payload.code == 4014 and player.guild.me.voice:
            pass
        else:
            print(
                ("-" * 15) +
                f"\nLỗi kênh thoại!"
                f"\nBot: {player.bot.user} [{player.bot.user.id}] | " + ("Online" if self.bot.is_ready() else "Offline") +
                f"\nMáy chủ: {player.guild.name} [{player.guild.id}]"
                f"\nKênh: {vc.name} [{vc.id}]"
                f"\nServer: {player.node.identifier} | code: {payload.code} | reason: {payload.reason}\n" +
                ("-" * 15)
            )

        if player.is_closing:
            return

        if payload.code in (
                4000,  # internal error
                1006,
                1001,
                4016,  # Connection started elsewhere
                4005,  # Already authenticated.
                4006,  # Session is no longer valid.
        ):
            try:
                vc_id = player.guild.me.voice.channel.id
            except AttributeError:
                vc_id = player.last_channel.id

            await asyncio.sleep(3)

            if player.is_closing:
                return

            await player.connect(vc_id)
            return

        if payload.code == 4014:

            if player.static:
                player.command_log = "Tôi đã tắt trình phát vì mất kết nối với kênh thoại."
                await player.destroy()

            else:
                embed = disnake.Embed(description="**Tôi đã tắt người chơi vì mất kết nối với kênh thoại.**",
                                      color=self.bot.get_color(player.guild.me))
                try:
                    self.bot.loop.create_task(player.text_channel.send(embed=embed, delete_after=7))
                except:
                    traceback.print_exc()
                await player.destroy()

            return

    @commands.Cog.listener('on_wavelink_track_exception')
    async def wavelink_track_error(self, node, payload: wavelink.TrackException):
        player: LavalinkPlayer = payload.player
        track = player.last_track
        embed = disnake.Embed(title=f"<:Amber_SaveMe:1135639250650542161> **Ối, một lỗi không mong muốn đã xảy ra** <:Amber_SaveMe:1135639250650542161>",
            description= f"Máy chủ bị lỗi rồi, bạn hãy dùng ```/change_node``` để thay đổi máy chủ nhé\n"
                         f"**Không chơi nhạc:\n[{track.title}]({track.uri or track.search_uri})** ```java\n{payload.message}```\n"
                         f"**Gây ra:** ```java\n{payload.cause}```\n"
                         f"**Mức độ:** `{payload.severity}`\n"
                         f"**Máy chủ âm nhạc:** `{player.node.identifier}`\n"
                         f"Hướng dẫn: ",
        color=disnake.Colour.green())
        
        embed.set_image(url="https://cdn.discordapp.com/attachments/1114279240909721630/1135655816691712141/New_Project_9_BE96059.gif")
        await player.text_channel.send(embed=embed, delete_after=10)

        error_format = pprint.pformat(payload.data)

        print(("-" * 50) + f"\nLỗi khi chơi nhạc: {track.uri or track.search_uri}\n"
              f"Servidor: {player.node.identifier}\n"
              f"{error_format}\n" + ("-" * 50))

        if self.error_report_queue:

            embed.description += f"\n**Máy chủ:** `{disnake.utils.escape_markdown(player.guild.name)} [{player.guild.id}]`"

            try:
                embed.description += f"\n**Kênh:** `{disnake.utils.escape_markdown(player.guild.me.voice.channel.name)} [{player.guild.me.voice.channel.id}]`\n"
            except:
                pass

            embed.description += f"**Data:** <t:{int(disnake.utils.utcnow().timestamp())}:F>"

            await self.error_report_queue.put({"embed": embed})

        if player.locked:
            return

        player.current = None

        if payload.error == "This IP address has been blocked by YouTube (429)":
            player.node.available = False
            newnode = [n for n in self.bot.music.nodes.values() if n != player.node and n.available and n.is_available]
            if newnode:
                player.queue.appendleft(player.last_track)
                await player.change_node(newnode[0].identifier)
            else:
                embed = disnake.Embed(
                    color=self.bot.get_color(player.guild.me),
                    description="**Người chơi đã tắt vì thiếu máy chủ có sẵn.**"
                )
                await player.text_channel.send(embed=embed, delete_after=15)
                await player.destroy(force=True)
                return

        if player.last_track:

            if payload.cause in (
                "java.net.SocketTimeoutException: connect timed out",
                "com.sedmelluq.discord.lavaplayer.tools.io.PersistentHttpStream$PersistentHttpException: Not success status code: 403"
            ):
                player.queue.appendleft(player.last_track)

            elif payload.cause == "java.lang.InterruptedException":
                player.queue.appendleft(player.last_track)

                if player.node.identifier == "LOCAL":
                    return
                else:
                    try:
                        n = await self.get_best_node()
                    except:
                        if player.static:
                            player.set_command_log(text="Người chơi đã bị tắt vì thiếu máy chủ âm nhạc...")
                        else:
                            await player.text_channel.send("**Người chơi đã bị tắt vì thiếu máy chủ âm nhạc...**")
                        await player.destroy()
                        return
                    await player.change_node(n.identifier)

            # TODO: Desativar esse recurso após a correção do lavaplayer ser efetuada.
            elif payload.cause == "java.lang.RuntimeException: Not success status code: 403" and player.node.identifier == "LOCAL":

                player.queue.appendleft(player.last_track)

                txt = "Máy chủ âm nhạc đã được khởi động lại để điều chỉnh và âm nhạc sẽ được nối lại trong một số " \
                      "giây (vui lòng đợi)..."

                for b in self.bot.pool.bots:

                    for n in b.music.nodes.values():

                        if n.identifier != "LOCAL" or n.restarting:
                            continue

                        for p in n.players.values():

                            p.locked = True

                            p.node.restarting = True

                            if p.static or p.controller_mode:
                                p.set_command_log(text=txt, emoji="🛠️")
                                self.bot.loop.create_task(p.invoke_np(force=True))
                            else:
                                self.bot.loop.create_task(
                                    p.text_channel.send(
                                        embed=disnake.Embed(
                                            color=self.bot.get_color(p.guild.me),
                                            description=f"🛠️ **⠂{txt}**"
                                        )
                                    )
                                )

                self.bot.pool.start_lavalink()
                player.locked = True
                return

            elif not track.track_loops:
                player.failed_tracks.append(player.last_track)

            elif player.keep_connected and not player.last_track.autoplay and len(player.queue) > 15:
                player.queue.append(player.last_track)

        player.locked = True
        await asyncio.sleep(10)

        try:
            player = player.bot.music.players[player.guild.id]
        except:
            return

        player.locked = False
        await player.process_next()

    @commands.Cog.listener("on_wavelink_node_ready")
    async def node_ready(self, node: wavelink.Node):
        msg = f'{self.bot.user} - Máy chủ âm nhạc: [{node.identifier}] đã sẵn sàng!'

        if node.restarting:

            print(msg + " Kết nối lại người chơi...")

            node.restarting = False

            for guild_id in list(node.players):
                try:
                    player = node.players[guild_id]
                    await player.change_node(node.identifier, force=True)
                    player.set_command_log(
                        text="Máy chủ âm nhạc đã được kết nối lại thành công!",
                        emoji="🔰"
                    )
                    player.locked = False
                    if player.current:
                        if not player.paused:
                            await player.play(player.current, start=player.position)
                        player.update = True
                    else:
                        await player.process_next()
                except:
                    traceback.print_exc()
                    continue

        else:
            print(msg)

    @commands.Cog.listener('on_wavelink_track_start')
    async def track_start(self, node, payload: wavelink.TrackStart):

        player: LavalinkPlayer = payload.player

        if not player.text_channel.permissions_for(player.guild.me).send_messages:
            try:
                print(f"{player.guild.name} [{player.guild_id}] - Chơi người chơi vì thiếu sự cho phép gửi "
                      f"mensagens no canal: {player.text_channel.name} [{player.text_channel.id}]")
            except Exception:
                traceback.print_exc()
            await player.destroy()
            return

        if not player.guild.me.voice:
            try:
                await self.bot.wait_for(
                    "voice_state_update", check=lambda m, b, a: m == player.guild.me and m.voice, timeout=7
                )
            except asyncio.TimeoutError:
                player.update = True
                return

        await player.process_save_queue()

    @commands.Cog.listener("on_wavelink_track_end")
    async def track_end(self, node: wavelink.Node, payload: wavelink.TrackEnd):

        player: LavalinkPlayer = payload.player

        if player.locked:
            return

        if payload.reason == "FINISHED":
            player.set_command_log()

        elif payload.reason == "STOPPED":

            if len(player.queue) == 0:
                return

            player.ignore_np_once = True

        else:
            return

        try:
            player.message_updater_task.cancel()
        except:
            pass

        try:
            player = self.bot.music.players[player.guild.id]
        except:
            return

        await player.track_end()

        player.update = False

        await player.process_next()

    async def connect_node(self, data: dict):

        if data["identifier"] in self.bot.music.nodes:
            node = self.bot.music.nodes[data['identifier']]
            if not node.is_connected:
                await node.connect(self.bot)
            return

        data['rest_uri'] = ("https" if data.get('secure') else "http") + f"://{data['host']}:{data['port']}"
        data['user_agent'] = self.u_agent
        search = data.pop("search", True)
        max_retries = data.pop('retries', 0)
        node_website = data.pop('website', '')
        region = data.pop('region', 'us_central')

        if max_retries:

            backoff = 7
            retries = 1

            print(f"{self.bot.user} - Máy chủ âm nhạc bắt đầu: {data['identifier']}")

            while not self.bot.is_closed():
                if retries >= max_retries:
                    print(
                        f"{self.bot.user} - Tất cả các nỗ lực kết nối với máy chủ [{data['identifier']}] falharam.")
                    return
                else:
                    try:
                        async with self.bot.session.get(data['rest_uri'], timeout=10) as r:
                            break
                    except Exception:
                        backoff += 2
                        # print(f'{self.bot.user} - Falha ao conectar no servidor [{data["identifier"]}], '
                        #       f'nova tentativa [{retries}/{max_retries}] em {backoff} segundos.')
                        await asyncio.sleep(backoff)
                        retries += 1
                        continue

        data["identifier"] = data["identifier"].replace(" ", "_")
        node = await self.bot.music.initiate_node(auto_reconnect=False, region=region, **data)
        node.search = search
        node.website = node_website

    async def get_tracks(
            self, query: str, user: disnake.Member, node: wavelink.Node = None,
            track_loops=0, use_cache=True):

        if not node:
            node = await self.get_best_node()

        tracks = await process_spotify(self.bot, user.id, query)

        if not tracks:

            if use_cache:
                try:
                    cached_tracks = self.bot.pool.playlist_cache[query]
                except KeyError:
                    pass
                else:

                    tracks = LavalinkPlaylist(
                        {
                            'loadType': 'PLAYLIST_LOADED',
                            'playlistInfo': {
                                'name': cached_tracks[0]["info"]["extra"]["playlist"]["name"],
                                'selectedTrack': -1
                            },
                            'tracks': cached_tracks
                        },
                        requester=user.id,
                        url=cached_tracks[0]["info"]["extra"]["playlist"]["url"]
                    )

            if not tracks:

                if node.search:
                    node_search = node
                else:
                    try:
                        node_search = \
                            sorted(
                                [n for n in self.bot.music.nodes.values() if
                                 n.search and n.available and n.is_available and not n.restarting],
                                key=lambda n: len(n.players))[0]
                    except IndexError:
                        node_search = node

                try:
                    tracks = await node_search.get_tracks(
                        query, track_cls=LavalinkTrack, playlist_cls=LavalinkPlaylist, requester=user.id
                    )
                except ClientConnectorCertificateError:
                    node_search.available = False

                    for n in self.bot.music.nodes.values():

                        if not n.available or not n.is_available or n.restarting:
                            continue

                        try:
                            tracks = await n.get_tracks(
                                query, track_cls=LavalinkTrack, playlist_cls=LavalinkPlaylist, requester=user.id
                            )
                            node_search = n
                            break
                        except ClientConnectorCertificateError:
                            n.available = False
                            continue

                    if not node_search:
                        raise GenericError("**Không có máy chủ âm nhạc có sẵn.**")

        if not tracks:
            raise GenericError("Não houve resultados para sua busca.")

        if isinstance(tracks, list):
            tracks[0].info["extra"]["track_loops"] = track_loops

        else:

            if (selected := tracks.data['playlistInfo']['selectedTrack']) > 0:
                tracks.tracks = tracks.tracks[selected:] + tracks.tracks[:selected]

        return tracks, node

    async def connect_local_lavalink(self):

        if 'LOCAL' not in self.bot.music.nodes:

            localnode = {
                'host': '127.0.0.1',
                'port': 8090,
                'password': 'youshallnotpass',
                'identifier': 'LOCAL',
                'region': 'us_central',
                'retries': 25
            }

            self.bot.loop.create_task(self.connect_node(localnode))

    @commands.Cog.listener("on_thread_create")
    async def thread_song_request(self, thread: disnake.Thread):

        try:
            player: LavalinkPlayer = self.bot.music.players[thread.guild.id]
        except KeyError:
            return

        if player.static or player.message.id != thread.id:
            return

        embed = disnake.Embed(color=self.bot.get_color(thread.guild.me))

        if self.bot.intents.message_content:
            embed.description = "**Bạn chỉ cần ném linh hoặc tên của bài hát vào đây là tui sẽ tự thêm cho bạn**" \

        elif not player.controller_mode:
            embed.description = "**Vùng da/hiện tại không tương thích với hệ thống yêu cầu bài hát " \
                               "thông qua chủ đề/cuộc trò chuyện\n\n" \
                               "Lưu ý: ** `Hệ thống này yêu cầu một làn da sử dụng các nút.`"

        else:
            embed.description = "**Để ý!Tôi không có ý định của message_content được kích hoạt bởi nhà phát triển của tôi...\n" \
                                "Chức năng yêu cầu âm nhạc ở đây có thể không có kết quả dự kiến...**"

        await thread.send(embed=embed)

    @commands.Cog.listener("on_voice_state_update")
    async def player_vc_disconnect(
            self,
            member: disnake.Member,
            before: disnake.VoiceState,
            after: disnake.VoiceState
    ):

        if before.channel == after.channel:
            return

        if member.bot and self.bot.user.id != member.id:
            # ignorar outros bots
            return

        try:
            player: LavalinkPlayer = self.bot.music.players[member.guild.id]
        except KeyError:
            return

        try:
            player.members_timeout_task.cancel()
            player.members_timeout_task = None
        except AttributeError:
            pass

        if member.id == self.bot.user.id and member.guild.voice_client and after.channel:
            # tempfix para channel do voice_client não ser setado ao mover bot do canal.
            player.guild.voice_client.channel = after.channel
            player.last_channel = after.channel

        try:
            check = any(m for m in player.guild.me.voice.channel.members if not m.bot)
        except:
            check = None

        player.members_timeout_task = self.bot.loop.create_task(player.members_timeout(check=check))

        # rich presence stuff

        if player.auto_pause:
            return

        if player.is_closing or (member.bot and not before.channel):
            return

        channels = set()

        try:
            channels.add(before.channel.id)
        except:
            pass

        try:
            channels.add(after.channel.id)
        except:
            pass

        try:
            try:
                vc = player.guild.me.voice.channel
            except AttributeError:
                vc = player.last_channel

            if vc.id not in channels:
                return
        except AttributeError:
            pass

        if not after or before.channel != after.channel:

            try:
                vc = player.guild.me.voice.channel
            except AttributeError:
                vc = before.channel

            if vc:

                try:
                    await player.process_rpc(vc, users=[member.id], close=not player.guild.me.voice or after.channel != player.guild.me.voice.channel, wait=True)
                except AttributeError:
                    traceback.print_exc()
                    pass

                await player.process_rpc(vc, users=[m for m in vc.voice_states if (m != member.id)])

    async def reset_controller_db(self, guild_id: int, data: dict, inter: disnake.AppCmdInter = None):

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        data['player_controller']['channel'] = None
        data['player_controller']['message_id'] = None

        try:
            player: LavalinkPlayer = bot.music.players[guild_id]
        except KeyError:
            return

        player.static = False

        try:
            if isinstance(inter.channel.parent, disnake.TextChannel):
                player.text_channel = inter.channel.parent
            else:
                player.text_channel = inter.channel
        except AttributeError:
            player.text_channel = inter.channel

        try:
            await bot.update_data(guild_id, data, db_name=DBModel.guilds)
        except Exception:
            traceback.print_exc()

    async def get_best_node(self, bot: BotCore = None):

        if not bot:
            bot = self.bot

        try:
            return sorted(
                [n for n in bot.music.nodes.values() if n.stats and n.is_available and n.available and not n.restarting],
                key=lambda n: n.stats.players
            )[0]

        except IndexError:
            try:
                node = bot.music.nodes['LOCAL']
            except KeyError:
                pass
            else:
                if not node._websocket.is_connected:
                    await node.connect(bot)
                return node

            raise GenericError("**Không có máy chủ âm nhạc có sẵn.**")

    async def error_report_loop(self):

        while True:

            data = await self.error_report_queue.get()

            async with aiohttp.ClientSession() as session:
                webhook = disnake.Webhook.from_url(self.bot.config["AUTO_ERROR_REPORT_WEBHOOK"], session=session)
                await webhook.send(username=self.bot.user.display_name, avatar_url=self.bot.user.display_avatar.url, **data)

            await asyncio.sleep(15)


def setup(bot: BotCore):
    bot.add_cog(Music(bot))

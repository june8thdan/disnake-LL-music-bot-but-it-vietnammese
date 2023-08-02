# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os.path
import traceback
from itertools import cycle
from random import shuffle
from os import getpid
import platform
import asyncio
from typing import TYPE_CHECKING

import aiofiles
import disnake
import psutil
import humanize
from disnake.ext import commands
from aiohttp import ClientSession

from utils.db import DBModel, db_models
from utils.music.checks import check_requester_channel
from utils.music.converters import time_format, URL_REG
from utils.others import select_bot_pool, CustomContext, paginator

if TYPE_CHECKING:
    from utils.client import BotCore


def remove_blank_spaces(d):

    for k, v in list(d.items()):

        new_k = k.strip()
        if new_k != k:
            d[new_k] = d.pop(k)

        if isinstance(v, str):
            new_v = v.strip()
            if new_v != v:
                d[new_k] = new_v
        elif isinstance(v, dict):
            remove_blank_spaces(v)


class Misc(commands.Cog):

    def __init__(self, bot: BotCore):
        self.bot = bot
        self.activities = None
        self.task = self.bot.loop.create_task(self.presences())
        self.extra_user_bots = []
        self.extra_user_bots_ids = [int(i) for i in bot.config['ADDITIONAL_BOT_IDS'].split() if i.isdigit()]

    desc_prefix = "🔰 [Ngoài lề] 🔰 | "

    def placeholders(self, text: str):

        if not text:
            return ""

        return text \
            .replace("{users}", f'{len([m for m in self.bot.users if not m.bot]):,}'.replace(",", ".")) \
            .replace("{playing}", f'{len(self.bot.music.players):,}'.replace(",", ".")) \
            .replace("{guilds}", f'{len(self.bot.guilds):,}'.replace(",", ".")) \
            .replace("{uptime}", time_format((disnake.utils.utcnow() - self.bot.uptime).total_seconds() * 1000,
                                             use_names=True))


    async def presences(self):

        if not self.activities:

            activities = []

            for i in self.bot.config["LISTENING_PRESENCES"].split("||"):
                if i:
                    activities.append({"name":i, "type": "listening"})

            for i in self.bot.config["WATCHING_PRESENCES"].split("||"):
                if i:
                    activities.append({"name": i, "type": "watching"})

            for i in self.bot.config["PLAYING_PRESENCES"].split("||"):
                if i:
                    activities.append({"name": i, "type": "playing"})

            for i in self.bot.config["STREAMING_PRESENCES"].split("|||"):
                if i:
                    try:
                        name, url = i.split("||")
                        activities.append({"name": name, "url": url.strip(" "), "type": "streaming"})
                    except Exception:
                        traceback.print_exc()

            shuffle(activities)

            self.activities = cycle(activities)

        while True:

            await self.bot.wait_until_ready()

            activity_data = next(self.activities)

            if activity_data["type"] == "listening":
                activity = disnake.Activity(
                    type=disnake.ActivityType.listening,
                    name=self.placeholders(activity_data["name"])
                )

            elif activity_data["type"] == "watching":
                activity = disnake.Activity(
                    type=disnake.ActivityType.watching,
                    name=self.placeholders(activity_data["name"])
                )

            elif activity_data["type"] == "streaming":
                activity = disnake.Activity(
                    type=disnake.ActivityType.streaming,
                    name=self.placeholders(activity_data["name"]),
                    url=activity_data["url"]
                )

            else:
                activity = disnake.Game(name=self.placeholders(activity_data["name"]))

            await self.bot.change_presence(activity=activity)

            await asyncio.sleep(self.bot.config["PRESENCE_INTERVAL"])


    @commands.Cog.listener("on_guild_join")
    async def guild_add(self, guild: disnake.Guild):

        if str(self.bot.user.id) in self.bot.config["INTERACTION_BOTS_CONTROLLER"]:
            await guild.leave()
            return

        interaction_invites = []

        bots_in_guild = []

        for bot in self.bot.pool.bots:

            if bot == self.bot:
                continue

            if bot.user in guild.members:
                bots_in_guild.append(bot)

        components = [disnake.ui.Button(custom_id="bot_invite", label="Cần thêm bot âm nhạc? Bấm vào đây.")] if [b for b in self.bot.pool.bots if b.appinfo and b.appinfo.bot_public] else []

        if not self.bot.command_sync_flags.sync_commands and self.bot.config["INTERACTION_BOTS"]:

            for b in self.bot.pool.bots:

                if str(b.user.id) not in self.bot.config["INTERACTION_BOTS"]:
                    continue

                interaction_invites.append(f"[`{disnake.utils.escape_markdown(str(b.user.name))}`]({disnake.utils.oauth_url(b.user.id, scopes=['applications.commands'])}) ")

        if cmd:=self.bot.get_command("setup"):
            cmd_text = f"Nếu muốn, hãy sử dụng lệnh **/{cmd.name}** Để tạo một kênh chuyên dụng để hỏi " \
                        "Các bài hát không có lệnh và để lại trình phát nhạc cố định trên một kênh chuyên dụng.\n\n"
        else:
            cmd_text = ""

        if self.bot.config["SUPPORT_SERVER"]:
            support_server = f"Nếu bạn có bất kỳ câu hỏi hoặc muốn theo dõi những tin tức mới nhất, bạn có thể tham gia [`máy chủ hỗ trợ`]({self.bot.config['SUPPORT_SERVER']})\n\n"
        else:
            support_server = ""

        if self.bot.default_prefix and not self.bot.config["INTERACTION_COMMAND_ONLY"]:
            guild_data = await self.bot.get_global_data(guild.id, db_name=DBModel.guilds)
            prefix = disnake.utils.escape_markdown(guild_data['prefix'] or self.bot.default_prefix, as_needed=True)
        else:
            prefix = ""

        image = "https://cdn.discordapp.com/attachments/554468640942981147/1082887587770937455/rainbow_bar2.gif"

        color = self.bot.get_color()

        try:
            channel = guild.system_channel if guild.system_channel.permissions_for(guild.me).send_messages else None
        except AttributeError:
            channel = None

        if not channel:

            if guild.me.guild_permissions.view_audit_log:

                async for entry in guild.audit_logs(action=disnake.AuditLogAction.integration_create, limit=50):

                    if entry.target.application_id == self.bot.user.id:

                        embeds = []

                        embeds.append(
                            disnake.Embed(
                                color=color,
                                description=f"Xin chào! Cảm ơn bạn rất nhiều vì đã thêm tôi vào máy chủ: **{guild.name}** :)"
                            ).set_image(url=image)
                        )

                        if interaction_invites:
                            embeds.append(
                                disnake.Embed(
                                    color=color,
                                    description=f"**Lưu ý quan trọng: ** lệnh thanh của tôi hoạt động " \
                                                 f"thông qua một trong các ứng dụng sau đây:\n" \
                                                 f"{' **|** '.join(interaction_invites)}\n\n" \
                                                 f"Nếu các lệnh ứng dụng ở trên không được hiển thị khi nhập " \
                                                 f" (**/**) Trên một kênh máy chủ **{guild.name}** Bạn sẽ có " \
                                                 f"Để nhấp vào tên trên để tích hợp các lệnh thanh trong " \
                                                 f"máy chủ **{guild.name}**."
                                ).set_image(url=image)
                            )
                        else:
                            embeds.append(
                                disnake.Embed(
                                    color=color,
                                    description=f"Để xem tất cả các lệnh của tôi sử dụng (**/**) trong máy chủ " \
                                                 f"**{guild.name}**"
                                ).set_image(url=image)
                            )

                        if prefix:
                            embeds.append(
                                disnake.Embed(
                                    color=color,
                                    description=f"Tôi cũng có các lệnh văn bản bằng prefix. " \
                                                 f"Để xem tất cả các lệnh văn bản của tôi sử dụng **{prefix}help* trên " \
                                                 f"Kênh máy chủ **{guild.name}**"
                                ).set_image(url=image)
                            )

                        if bots_in_guild:
                            embeds.append(
                                disnake.Embed(
                                    color=color,
                                    description=f"Tôi nhận thấy rằng có những bot khác trên máy chủ **{guild.name}** trong đó tôi tương thích với " \
                                                f"một hệ thống đa Vouc: {', '.join(b.user.mention for b in bots_in_guild)}\n\n"
                                                f"Khi sử dụng các lệnh âm nhạc (ví dụ: chơi) mà không có một trong những bot "
                                                f"kết nối với kênh, một trong những bot trong "
                                                f"máy chủ."
                                ).set_image(url=image)
                            )

                        if support_server:
                            embeds.append(disnake.Embed(color=color, description=support_server).set_image(url=image))

                        try:
                            return await entry.user.send(embeds=embeds, components=components)
                        except disnake.Forbidden:
                            pass
                        except Exception:
                            traceback.print_exc()
                        break

        if not channel:

            for c in (guild.public_updates_channel, guild.rules_channel):

                if c and c.permissions_for(guild.me).send_messages:
                    channel = c
                    break

            if not channel:
                return

        embeds = []

        if interaction_invites:

            embeds.append(
                disnake.Embed(
                    color=color,
                    description=f"Xin chào!Để xem tất cả các lệnh loại lệnh của tôi (**/**) và kiểm tra" \
                                 f"các lệnh của các ứng dụng sau đây:\n" \
                                 f"{' **|** '.join(interaction_invites)}\n\n" \
                                 f"Nếu các lệnh ứng dụng ở trên không được hiển thị khi nhập " \
                                 f" (**/**) Bạn sẽ phải nhấp vào tên ở trên để tích hợp các lệnh của " \
                                 f"tôi trên máy chủ của bạn."

                ).set_image(url=image)
            )

        else:
            embeds.append(
                disnake.Embed(
                    color=color, description="Xin chào!Để xem tất cả các lệnh của tôi sử dụng thanh (**/**)"
                ).set_image(url=image)
            )

        embeds.append(disnake.Embed(color=color, description=cmd_text).set_image(url=image))

        if prefix:
            embeds.append(
                disnake.Embed(
                    color=color,
                    description=f"Tôi cũng có các lệnh văn bản theo prefix. " \
                     f"Để xem tất cả các lệnh văn bản của tôi sử dụng **{prefix}help**"
                ).set_image(url=image)
            )

        if bots_in_guild:
            embeds.append(
                disnake.Embed(
                    color=color,
                    description=f"Tôi nhận thấy rằng có những bot khác trên máy chủ **{guild.name}** trong đó tôi tương thích với " \
                                f"một hệ thống muti-voice {', '.join(b.user.mention for b in bots_in_guild)}\n\n"
                                f"Khi sử dụng các lệnh âm nhạc (ví dụ: chơi) mà không có một trong những bot "
                                f"kết nối với kênh, một trong những bot trong "
                                f"máy chủ."
                ).set_image(url=image)
            )

        if support_server:
            embeds.append(disnake.Embed(color=color, description=support_server).set_image(url=image))

        kwargs = {"delete_after": 60} if channel == guild.rules_channel else {"delete_after": 300}

        try:
            await channel.send(embeds=embeds, components=components, **kwargs)
        except:
            print(f"Không gửi được tin nhắn máy chủ mới trên kênh: {channel}\n"
                  f"Id của kênh: {channel.id}\n"
                  f"Loại kênh: {type(channel)}\n"
                  f"{traceback.format_exc()}")

        await self.bot.update_appinfo()


    about_cd = commands.CooldownMapping.from_cooldown(1, 5, commands.BucketType.member)

    @commands.command(name="about", aliases=["sobre", "info", "botinfo"], description="Hiển thị thông tin về tôi.",
                      cooldown=about_cd)
    async def about_legacy(self, ctx: CustomContext):
        await self.about.callback(self=self, inter=ctx)


    @commands.slash_command(
        description=f"{desc_prefix}Hiển thị thông tin về tôi.", cooldown=about_cd
    )
    async def about(
            self,
            inter: disnake.AppCmdInter
    ):

        await inter.response.defer(ephemeral=True)

        inter, bot = await select_bot_pool(inter, first=True)

        if not bot:
            return

        ram_usage = humanize.naturalsize(psutil.Process(getpid()).memory_info().rss)

        guild = bot.get_guild(inter.guild_id) or inter.guild

        embed = disnake.Embed(
            description=f"**Thông tin hiện tại của {bot.user} :**\n\n",
            color=bot.get_color(inter.guild.me if inter.guild else guild.me)
        )

        active_players_other_bots = 0
        inactive_players_other_bots = 0
        paused_players_other_bots = 0

        all_guilds_ids = set()

        for b in bot.pool.bots:

            try:
                if str(b.user.id) in self.bot.config["INTERACTION_BOTS_CONTROLLER"]:
                    continue
            except:
                pass

            for g in b.guilds:
                all_guilds_ids.add(g.id)

        guilds_size = len(all_guilds_ids)

        embed.description += f"> <:Coder:1118048848670105711> **Số máy chủ mà tôi đang ở" + (" (Tất cả các bot)" if guilds_size > 1 else "") + \
                             f":** `{guilds_size}`\n"

        public_bot_count = 0
        private_bot_count = 0

        for b in bot.pool.bots:

            try:
                if str(b.user.id) in self.bot.config["INTERACTION_BOTS_CONTROLLER"]:
                    continue
            except:
                pass

            for p in b.music.players.values():

                if p.auto_pause:
                    inactive_players_other_bots += 1

                elif p.paused:
                    try:
                        if any(m for m in p.guild.me.voice.channel.members if not m.bot):
                            paused_players_other_bots += 1
                            continue
                    except AttributeError:
                        pass
                    inactive_players_other_bots += 1

                else:
                    active_players_other_bots += 1

            if not b.appinfo or not b.appinfo.bot_public:
                private_bot_count += 1
            else:
                public_bot_count += 1

        if public_bot_count:
            embed.description += f"> <:kokomiyay:1133778578606145576> **Bot công khai:** `{public_bot_count}`\n"

        if private_bot_count:
            embed.description += f"> <:kokomiyay:1133778578606145576> **Bot cá nhân :** `{private_bot_count}`\n"

        if active_players_other_bots:
            embed.description += f"> <:___:1119098209776709633> **Người chơi tích cực" + (" (Tất cả các bot)" if len(bot.pool.bots) > 1 else "") + \
                                 f":** `{active_players_other_bots}`\n"

        if paused_players_other_bots:
            embed.description += f">  <:___:1119098209776709633> **Người chơi tạm dừng" + (" (Tất cả các bot)" if len(bot.pool.bots) > 1 else "") + \
                                 f":** `{paused_players_other_bots}`\n"

        if inactive_players_other_bots:
            embed.description += f"> <:___:1119098209776709633> **Người chơi không hoạt động" + (" (Tất cả các bot)" if len(bot.pool.bots) > 1 else "") + \
                                 f":** `{inactive_players_other_bots}`\n"

        embed.description += f"> <:windows:1118520530627198997> **Phiên bản Python:** `{platform.python_version()}`\n" \
                             f"> <:finder:1118520640589279252> **Phiên bản disnake:** `{disnake.__version__}`\n" \
                             f"> <a:loading:1117802386333905017> **Độ trễ:** `{round(bot.latency * 100)}ms`\n" \
                             f"> <a:kurukuru_seseren:1118094291957465149> **Mức độ sử dụng Ram** `{ram_usage}`\n" \
                             f"> <:serverrack:1118521207944384592> **Lần khởi động lại cuối cùng:** <t:{int(bot.uptime.timestamp())}:R>\n"

        try:
            guild_data = inter.global_guild_data
        except AttributeError:
            guild_data = await bot.get_global_data(inter.guild_id, db_name=DBModel.guilds)
            inter.global_guild_data = guild_data

        prefix = guild_data["prefix"] or bot.default_prefix

        if bot.default_prefix and not bot.config["INTERACTION_COMMAND_ONLY"]:
            embed.description += f"> **Prefix:** `{disnake.utils.escape_markdown(prefix, as_needed=True)}`\n"

        links = "[`[Liên hệ chủ sở hữu]`](https://www.facebook.com/profile.php?id=100090123895777)"

        if bot.config["SUPPORT_SERVER"]:
            links += f" **|** [`[Máy chủ hỗ trợ]`]({bot.config['SUPPORT_SERVER']})"

        embed.description += f">  {links}\n"

        try:
            avatar = bot.owner.avatar.with_static_format("png").url
        except AttributeError:
            avatar = bot.owner.default_avatar.with_static_format("png").url

        embed.set_footer(
            icon_url=avatar,
            text=f"Vận hành bởi: {bot.owner}"
        )

        components = [disnake.ui.Button(custom_id="bot_invite", label="Thêm tui vào máy chủ của bạn ❤️")] if [b for b in bot.pool.bots if b.appinfo and b.appinfo.bot_public] else None

        try:
            await inter.edit_original_message(embed=embed, components=components)
        except (AttributeError, disnake.InteractionNotEditable):
            try:
                await inter.response.edit_message(embed=embed, components=components)
            except:
                await inter.send(embed=embed, ephemeral=True, components=components)


    @commands.Cog.listener("on_button_click")
    async def invite_button(self, inter: disnake.MessageInteraction, is_command=False):

        if not is_command and inter.data.custom_id != "bot_invite":
            return

        bots_invites = []
        bots_in_guild = []

        guild = inter.guild

        if not guild:
            for bot in self.bot.pool.bots:
                if (guild:=bot.get_guild(inter.guild_id)):
                    break

        for bot in sorted(self.bot.pool.bots, key=lambda b: len(b.guilds)):

            try:
                if not bot.appinfo.bot_public and not await bot.is_owner(inter.author):
                    continue
            except:
                continue

            if str(bot.user.id) in bot.config['INTERACTION_BOTS_CONTROLLER']:
                continue

            kwargs = {"redirect_uri": self.bot.config['INVITE_REDIRECT_URL']} if self.bot.config['INVITE_REDIRECT_URL'] else {}

            invite = f"[`{disnake.utils.escape_markdown(str(bot.user.name))}`]({disnake.utils.oauth_url(bot.user.id, permissions=disnake.Permissions(bot.config['INVITE_PERMISSIONS']), scopes=('bot', 'applications.commands'), **kwargs)})"

            if not str(bot.user.id) not in self.bot.config["INTERACTION_BOTS_CONTROLLER"] and bot.appinfo.flags.gateway_message_content_limited:
                invite += f" ({len(bot.guilds)}/100)"
            else:
                invite += f" ({len(bot.guilds)})"

            if guild and bot.user in guild.members:
                bots_in_guild.append(invite)
            else:
                bots_invites.append(invite)

        txt = ""

        if bots_invites:
            txt += "<:verify:1134033164151566460> **Bot có sẵn:**\n"
            for i in disnake.utils.as_chunks(bots_invites, 2):
                txt += " | ".join(i) + "\n"
            txt += "\n"

        if bots_in_guild:
            txt += "<:verify:1134033164151566460> **Bot đã có trên máy chủ hiện tại:**\n"
            for i in disnake.utils.as_chunks(bots_in_guild, 2):
                txt += " | ".join(i) + "\n"

        if not txt:
            await inter.send(
                embed=disnake.Embed(
                    colour=self.bot.get_color(
                        inter.guild.me if inter.guild else guild.me if guild else None
                    ),
                    title="⚠️ **Không có bot công khai có sẵn...**",
                ), ephemeral=True
            )
            return

        interaction_bots = ""

        if len(self.bot.pool.bots) > 1:

            for b in self.bot.pool.bots:

                if not b.interaction_id:
                    continue

                try:
                    interaction_bots += f"[`{disnake.utils.escape_markdown(b.user.name)}`]({disnake.utils.oauth_url(b.user.id, scopes=['applications.commands'])}) "
                except Exception:
                    traceback.print_exc()

        if interaction_bots:
            txt = f"**Ghi lại các lệnh thanh trên máy chủ:**\n{interaction_bots}\n\n" + txt

        color = self.bot.get_color(inter.guild.me if inter.guild else guild.me if guild else None)

        embeds = [
            disnake.Embed(
                colour=self.bot.get_color(inter.guild.me if inter.guild else guild.me if guild else None),
                description=p, color=color
            ) for p in paginator(txt)
        ]

        await inter.send(embeds=embeds, ephemeral=True)


    @commands.command(name="invite", aliases=["convidar"], description="Hiển thị liên kết lời mời của tôi để bạn thêm tôi vào máy chủ của bạn.")
    async def invite_legacy(self, ctx):
        await self.invite.callback(self=self, inter=ctx)


    @commands.slash_command(
        description=f"{desc_prefix}Hiển thị liên kết lời mời của tôi để bạn thêm tôi vào máy chủ của bạn."
    )
    async def invite(self, inter: disnake.AppCmdInter):

        await inter.response.defer(ephemeral=True)

        await self.invite_button(inter, is_command=True)

    @commands.user_command(name="avatar")
    async def avatar(self, inter: disnake.UserCommandInteraction):

        embeds = []

        assets = {}

        if self.bot.intents.members:
            user = (await self.bot.fetch_user(inter.target.id) if not inter.target.bot else self.bot.get_user(inter.target.id))
        else:
            user = inter.target

        try:
            if inter.target.guild_avatar:
                assets["Avatar (Server)"] = inter.target.guild_avatar.with_static_format("png")
        except AttributeError:
            pass
        assets["Avatar (User)"] = user.display_avatar.with_static_format("png")
        if user.banner:
            assets["Banner"] = user.banner.with_static_format("png")

        for name, asset in assets.items():
            embed = disnake.Embed(description=f"{inter.target.mention} **[{name}]({asset.with_size(2048).url})**",
                                  color=self.bot.get_color(inter.guild.me if inter.guild else None))
            embed.set_image(asset.with_size(256).url)
            embeds.append(embed)

        await inter.send(embeds=embeds, ephemeral=True)

    @commands.is_owner()
    @commands.max_concurrency(1, commands.BucketType.default)
    @commands.command(hidden=True, description="Lệnh tạm thời để sửa lỗi yêu thích với khoảng trống "
                                               "gây ra lỗi trong một số tình huống.")
    async def fixfavs(self, ctx: CustomContext):

        if not os.path.isdir("./local_database/fixfavs_backup"):
            os.makedirs("./local_database/fixfavs_backup")

        async with ctx.typing():

            for bot in self.bot.pool.bots:

                db_data = await bot.pool.database.query_data(collection=str(bot.user.id), db_name=DBModel.guilds, limit=300)
    
                async with aiofiles.open(f"./local_database/fixfavs_backup/guild_favs_{bot.user.id}.json", "w") as f:
                    await f.write(json.dumps(db_data, indent=4))

                for data in db_data:
                    try:
                        remove_blank_spaces(data["player_controller"]["fav_links"])
                    except KeyError:
                        continue
                    await bot.update_data(id_=data["_id"], data=data, db_name=DBModel.guilds)

            db_data = await self.bot.pool.database.query_data(collection="global", db_name=DBModel.users, limit=500)

            async with aiofiles.open("./local_database/fixfavs_backup/user_favs.json", "w") as f:
                await f.write(json.dumps(db_data, indent=4))

            for data in db_data:
                remove_blank_spaces(data["fav_links"])
                await self.bot.update_global_data(id_=data["_id"], data=data, db_name=DBModel.users)

            await ctx.send("Yêu thích đã được sửa thành công!")

    async def cog_check(self, ctx):
        return await check_requester_channel(ctx)

    def cog_unload(self):

        try:
            self.task.cancel()
        except:
            pass


class GuildLog(commands.Cog):

    def __init__(self, bot: BotCore):
        self.bot = bot
        self.hook_url: str = ""

        if bot.config["BOT_ADD_REMOVE_LOG"]:

            if URL_REG.match(bot.config["BOT_ADD_REMOVE_LOG"]):
                self.hook_url = bot.config["BOT_ADD_REMOVE_LOG"]
            else:
                print("URL Webhook không hợp lệ (để gửi nhật ký khi thêm/xóa bot).")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: disnake.Guild):

        if str(self.bot.user.id) in self.bot.config["INTERACTION_BOTS_CONTROLLER"]:
            return

        print(f"Bị xóa khỏi máy chủ: {guild.name} - [{guild.id}]")

        try:
            await self.bot.music.players[guild.id].destroy()
        except:
            pass

        if not self.hook_url:
            return

        embed = disnake.Embed(
            description=f"**Đã loại tôi khỏi máy chủ:**\n"
                        f"```{guild.name}```\n"
                        f"**ID:** `{guild.id}`",
            color=disnake.Colour.red()
        )

        try:
            guild_data = await self.bot.get_data(guild.id, db_name=DBModel.guilds)
            guild_data["player_controller"] = db_models[DBModel.guilds]["player_controller"]
            await self.bot.update_data(guild.id, guild_data, db_name=DBModel.guilds)
        except:
            traceback.print_exc()

        try:
            embed.set_thumbnail(url=guild.icon.replace(static_format="png").url)
        except AttributeError:
            pass

        try:
            owner_mention = self.bot.owner.mention
        except AttributeError:
            owner_mention = ""

        try:
            await self.send_hook(owner_mention, embed=embed)
        except:
            traceback.print_exc()

        await self.bot.update_appinfo()

    @commands.Cog.listener()
    async def on_guild_join(self, guild: disnake.Guild):

        if str(self.bot.user.id) in self.bot.config["INTERACTION_BOTS_CONTROLLER"]:
            return

        print(f"Máy chủ mới: {guild.name} - [{guild.id}]")

        try:
            guild_data = await self.bot.get_data(guild.id, db_name=DBModel.guilds)
            guild_data["player_controller"] = db_models[DBModel.guilds]["player_controller"]
            await self.bot.update_data(guild.id, guild_data, db_name=DBModel.guilds)
        except:
            traceback.print_exc()

        if not self.hook_url:
            return

        created_at = int(guild.created_at.timestamp())

        embed =disnake.Embed(
            description="__**Đã thêm tôi vào một máy chủ mới:**__\n"
                        f"```{guild.name}```\n"
                        f"**ID:** `{guild.id}`\n"
		                f"**Chủ:** `{guild.owner} [{guild.owner.id}]`\n"
                        f"**Được tạo ra vào:** <t:{created_at}:f> - <t:{created_at}:R>\n"
		                f"**Mức độ xác minh:** `{guild.verification_level or 'nenhuma'}`\n"
		                f"**Số thành viên:** `{len([m for m in guild.members if not m.bot])}`\n"
		                f"**Số lượng bot:** `{len([m for m in guild.members if m.bot])}`\n",
            color=disnake.Colour.green()
        )

        try:
            embed.set_thumbnail(url=guild.icon.replace(static_format="png").url)
        except AttributeError:
            pass

        try:
            owner_mention = self.bot.owner.mention
        except AttributeError:
            owner_mention = ""

        await self.send_hook(owner_mention, embed=embed)

    async def send_hook(self, content="", *, embed: disnake.Embed=None):

        async with ClientSession() as session:
            webhook = disnake.Webhook.from_url(self.hook_url, session=session)
            await webhook.send(
                content=content,
                username=self.bot.user.name,
                avatar_url=self.bot.user.display_avatar.replace(size=256, static_format="png").url,
                embed=embed
            )


def setup(bot: BotCore):
    bot.add_cog(Misc(bot))
    bot.add_cog(GuildLog(bot))

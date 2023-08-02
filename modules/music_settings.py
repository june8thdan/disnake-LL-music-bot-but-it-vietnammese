# -*- coding: utf-8 -*-
from __future__ import annotations
import asyncio
import os
import random
import string
from typing import TYPE_CHECKING, Union, Optional
import datetime
import traceback

import humanize
import disnake
from disnake.ext import commands

from utils.db import DBModel
from utils.music.converters import perms_translations, time_format
from utils.music.errors import GenericError, NoVoice
from utils.others import send_idle_embed, CustomContext, select_bot_pool, pool_command, CommandArgparse
from utils.music.models import LavalinkPlayer

if TYPE_CHECKING:
    from utils.client import BotCore

desc_prefix = "🔧 [Cài đặt] 🔧 | "


class SkinSelector(disnake.ui.View):

    def __init__(
            self,
            ctx: Union[disnake.AppCmdInter, CustomContext],
            embed: disnake.Embed,
            select_opts: list,
            static_select_opts: list,
            global_select_opts: list = None,
            global_static_select_opts: list = None,
            global_mode=False,
    ):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.interaction: Optional[disnake.MessageInteraction] = None
        self.global_mode = global_mode
        self.skin_selected = None
        self.static_skin_selected = None
        self.select_opts = select_opts
        self.static_select_opts = static_select_opts
        self.global_select_opts = global_select_opts
        self.global_static_select_opts = global_static_select_opts
        self.embed = embed

        if not global_mode:
            self.skin_selected = [s.value for s in select_opts if s.default][0]
            self.static_skin_selected = [s.value for s in static_select_opts if s.default][0]
        else:
            self.skin_selected = [s.value for s in global_select_opts if s.default][0]
            self.static_skin_selected = [s.value for s in global_static_select_opts if s.default][0]

        self.rebuild_selects()

    def rebuild_selects(self):

        self.clear_items()

        if not self.global_mode:
            self.embed.title = "Bộ chọn skin (cho bot đã chọn)"

            for s in self.select_opts:
                s.default = self.skin_selected == s.value

            for s in self.static_select_opts:
                s.default = self.static_skin_selected == s.value

            select_opts = self.select_opts
            static_select_opts = self.static_select_opts

        else:
            self.embed.title = "Bộ chọn skin (cho tất cả các bot máy chủ)"

            for s in self.global_select_opts:
                s.default = self.skin_selected == s.value

            for s in self.global_static_select_opts:
                s.default = self.static_skin_selected == s.value

            select_opts = self.global_select_opts
            static_select_opts = self.global_static_select_opts

        select_opts = disnake.ui.Select(options=select_opts, min_values=1, max_values=1)
        select_opts.callback = self.skin_callback
        self.add_item(select_opts)

        static_select_opts = disnake.ui.Select(options=static_select_opts, min_values=1, max_values=1)
        static_select_opts.callback = self.static_skin_callback
        self.add_item(static_select_opts)

        global_mode = disnake.ui.Button(label=("Vô hiệu hóa" if self.global_mode else "Cho phép") + " đường Global ", emoji="🌐")
        global_mode.callback = self.mode_callback
        self.add_item(global_mode)

        confirm_button = disnake.ui.Button(label="Để lưu", emoji="💾")
        confirm_button.callback = self.confirm_callback
        self.add_item(confirm_button)

        cancel_button = disnake.ui.Button(label="Hủy bỏ", emoji="❌")
        cancel_button.callback = self.stop_callback
        self.add_item(cancel_button)

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:

        if inter.author.id == self.ctx.author.id:
            return True

        await inter.send(f"Chỉ {self.ctx.author.mention} mới có thể tương tác ở đây!", ephemeral=True)
        return False

    async def skin_callback(self, inter: disnake.MessageInteraction):
        self.skin_selected = inter.data.values[0]
        self.rebuild_selects()
        await inter.response.edit_message(view=self)

    async def static_skin_callback(self, inter: disnake.MessageInteraction):
        self.static_skin_selected = inter.data.values[0]
        self.rebuild_selects()
        await inter.response.edit_message(view=self)

    async def mode_callback(self, inter: disnake.MessageInteraction):
        self.global_mode = not self.global_mode
        self.rebuild_selects()
        await inter.response.edit_message(view=self, embed=self.embed)

    async def confirm_callback(self, inter: disnake.MessageInteraction):
        self.interaction = inter
        self.stop()

    async def stop_callback(self, inter: disnake.MessageInteraction):
        self.interaction = inter
        self.skin_selected = None
        self.stop()


class PlayerSettings(disnake.ui.View):

    def __init__(self, ctx: Union[disnake.AppCmdInter, CustomContext], data: dict):
        super().__init__()
        self.ctx = ctx
        self.enable_autoplay = data["autoplay"]
        self.check_other_bots_in_vc = data['check_other_bots_in_vc']
        self.enable_restrict_mode = data['enable_restrict_mode']
        self.default_player_volume = data['default_player_volume']
        self.message: Optional[disnake.Message] = None
        self.load_buttons()

    def load_buttons(self):

        self.clear_items()

        player_volume_select = disnake.ui.Select(
            placeholder="Chọn một âm lượng mặc định.",
            options=[
                        disnake.SelectOption(label=f"Âm lượng mặc định: {i}", default=i == self.default_player_volume,
                                             value=str(i)) for i in range(5, 101, 5)
                    ] + [
                disnake.SelectOption(label=f"Âm lượng mặc định: {i}", default=i == self.default_player_volume,
                                     description="Lưu ý: Trên 100% âm thanh có thể trở nên rất LMAO.",
                                     value=str(i)) for i in range(110, 151, 10)
            ]
        )

        player_volume_select.callback = self.volume_callback
        self.add_item(player_volume_select)

        check_other_bots_button = disnake.ui.Button(label="Không kết nối với các bot không tương thích.",
                                                    emoji="✅" if self.check_other_bots_in_vc else "🚫")
        check_other_bots_button.callback = self.check_other_bots_callback
        self.add_item(check_other_bots_button)

        restrict_mode_button = disnake.ui.Button(label="Hạn chế",
                                                    emoji="✅" if self.enable_restrict_mode else "🚫")
        restrict_mode_button.callback = self.restrict_mode_callback
        self.add_item(restrict_mode_button)

        check_autoplay_button = disnake.ui.Button(label="Tự chạy.",
                                                    emoji="✅" if self.enable_autoplay else "🚫")
        check_autoplay_button.callback = self.autoplay_callback
        self.add_item(check_autoplay_button)

        close_button = disnake.ui.Button(label="Lưu/đóng", emoji="💾")
        close_button.callback = self.close_callback
        self.add_item(close_button)

    async def check_other_bots_callback(self, interaction: disnake.MessageInteraction):
        self.check_other_bots_in_vc = not self.check_other_bots_in_vc
        self.load_buttons()
        await interaction.response.edit_message(view=self)

    async def restrict_mode_callback(self, interaction: disnake.MessageInteraction):
        self.enable_restrict_mode = not self.enable_restrict_mode
        self.load_buttons()
        await interaction.response.edit_message(view=self)

    async def volume_callback(self, interaction: disnake.MessageInteraction):
        self.default_player_volume = int(interaction.data.values[0])
        self.load_buttons()
        await interaction.response.edit_message(view=self)

    async def autoplay_callback(self, interaction: disnake.MessageInteraction):
        self.enable_autoplay = not self.enable_autoplay
        self.load_buttons()
        await interaction.response.edit_message(view=self)

    async def close_callback(self, interaction: disnake.MessageInteraction):
        if isinstance(self.ctx, CustomContext):
            await interaction.message.delete()
        else:
            await interaction.response.edit_message(content="Thay đổi đã lưu thành công!", view=None, embed=None)
        await self.save_data()
        self.stop()

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:

        if inter.author.id == self.ctx.author.id:
            return True

        await inter.send(f"Chỉ {self.ctx.author.mention} mới có thể tương tác ở đây!", ephemeral=True)
        return False

    async def save_data(self):
        guild_data = await self.ctx.bot.get_data(self.ctx.guild_id, db_name=DBModel.guilds)
        guild_data['autoplay'] = self.enable_autoplay
        guild_data['check_other_bots_in_vc'] = self.check_other_bots_in_vc
        guild_data['enable_restrict_mode'] = self.enable_restrict_mode
        guild_data['default_player_volume'] = int(self.default_player_volume)
        await self.ctx.bot.update_data(self.ctx.guild_id, guild_data, db_name=DBModel.guilds)

    async def on_timeout(self):

        if isinstance(self.ctx, CustomContext):
            await self.message.edit(
                embed=disnake.Embed(description="**Đã hết thời gian...**", color=self.bot.get_color()), view=None
            )
        else:
            await self.ctx.edit_original_message(
                embed=disnake.Embed(description="**Đã hết thời gian...**", color=self.bot.get_color()), view=None
            )

        await self.save_data()

        self.stop()


class MusicSettings(commands.Cog):

    def __init__(self, bot: BotCore):
        self.bot = bot
        self.invite_cooldown = commands.CooldownMapping.from_cooldown(rate=1, per=45, type=commands.BucketType.guild)

    player_settings_cd = commands.CooldownMapping.from_cooldown(1, 5, commands.BucketType.guild)
    player_settings_mc = commands.MaxConcurrency(1, per=commands.BucketType.guild, wait=False)

    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(
        name="playersettings", aliases=["ps", "settings"],
        description="Thay đổi một số cài đặt tiêu chuẩn người chơi.",
        cooldown=player_settings_cd, max_concurrency=player_settings_mc
    )
    async def player_settings_legacy(self, ctx: CustomContext):
        await self.player_settings.callback(self=self, inter=ctx)

    @commands.slash_command(
        description=f"{desc_prefix}Thay đổi một số cài đặt tiêu chuẩn người chơi.",
        default_member_permissions=disnake.Permissions(manage_guild=True)
    )
    async def player_settings(self, inter: disnake.AppCmdInter):

        inter, bot = await select_bot_pool(inter)

        if not bot:
            return

        await inter.response.defer(ephemeral=True)

        guild_data = await self.bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        try:
            func = inter.store_message.edit
        except AttributeError:
            try:
                func = inter.edit_original_message
            except AttributeError:
                func = inter.send

        view = PlayerSettings(inter, guild_data)

        view.message = await func(
            embed=disnake.Embed(
                description="**Điều chỉnh cài đặt trình phát mặc định:**",
                color=self.bot.get_color()
            ).set_author(name=str(bot.user), icon_url=bot.user.display_avatar.url), view=view
        )

        await view.wait()

    setup_cd = commands.CooldownMapping.from_cooldown(1, 20, commands.BucketType.guild)
    setup_mc =commands.MaxConcurrency(1, per=commands.BucketType.guild, wait=False)

    setup_args = CommandArgparse()
    setup_args.add_argument('-reset', '--reset', '-purge', '--purge', action="store_true",
                             help="Xóa tin nhắn kênh đã chọn (tối đa 100 tin nhắn, không hiệu quả trong diễn đàn).")

    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(
        name="setup", aliases=["songrequestchannel", "sgrc"], usage="[id do canal ou #canal] [--reset]",
        description="Tạo/Chọn một kênh chuyên dụng để đặt hàng nhạc và tạo một trình phát cố định.",
        cooldown=setup_cd, max_concurrency=setup_mc
    )
    async def setup_legacy(
            self,
            ctx: CustomContext,
            channel: Union[disnake.TextChannel, disnake.VoiceChannel, disnake.ForumChannel, None] = None, *args
    ):

        args, unknown = self.setup_args.parse_known_args(args)

        await self.setup.callback(self=self, inter=ctx, target=channel,
                                  purge_messages=args.reset)

    @commands.slash_command(
        description=f"{desc_prefix}Tạo/chọn một kênh chuyên dụng để đặt hàng nhạc và để lại một trình phát cố định.",
        default_member_permissions=disnake.Permissions(manage_guild=True), cooldown=setup_cd, max_concurrency=setup_mc
    )
    async def setup(
            self,
            inter: disnake.AppCmdInter,
            target: Union[disnake.TextChannel, disnake.VoiceChannel, disnake.ForumChannel, disnake.StageChannel] = commands.Param(
                name="canal", default=None, description="Chọn một kênh hiện có"
            ),
            purge_messages: str = commands.Param(
                name="limpar_mensagens", default="no",
                description="Xóa tin nhắn kênh đã chọn (tối đa 100 tin nhắn, không hiệu quả trong diễn đàn).",
                choices=[
                    disnake.OptionChoice(
                        disnake.Localized("Yes", data={disnake.Locale.pt_BR: "Sim"}), "yes"
                    ),
                    disnake.OptionChoice(
                        disnake.Localized("No", data={disnake.Locale.pt_BR: "Não"}), "no"
                    )
                ],
            )
    ):

        inter, bot = await select_bot_pool(inter)

        if not bot:
            return

        guild = bot.get_guild(inter.guild_id)

        perms = (
            'manage_channels', 'send_messages', 'embed_links', 'send_messages_in_threads', 'read_messages',
            'create_public_threads', 'manage_messages'
        )

        missing_perms = [p for p, v in guild.me.guild_permissions if p in perms and not v]

        if missing_perms:
            raise GenericError(f"**{bot.user.mention} không có các quyền sau cần thiết dưới đây:** ```ansi\n" +
                               "\n".join(f"[0;33m{perms_translations.get(p,p)}[0m" for p in perms) + "```")

        channel = bot.get_channel(inter.channel.id)

        if target and bot != self.bot:
            target = bot.get_channel(target.id)

        perms_dict = {
            "embed_links": True,
            "send_messages": True,
            "send_messages_in_threads": True,
            "read_messages": True,
            "create_public_threads": True,
            "read_message_history": True,
            "manage_messages": True,
            "manage_channels": True,
            "attach_files": True,
        }

        if guild.me.guild_permissions.administrator:
            perms_dict["manage_permissions"] = True

        channel_kwargs = {
            "overwrites": {
                guild.me: disnake.PermissionOverwrite(**perms_dict)
            }
        }

        await inter.response.defer(ephemeral=True)

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

        original_message = None
        existing_channel = True

        try:
            player: LavalinkPlayer = bot.music.players[guild.id]
            if player.static:
                original_message = player.message
        except KeyError:
            player = None

        if not original_message:

            try:
                channel_db = bot.get_channel(int(guild_data["player_controller"]["channel"])) or \
                             await bot.fetch_channel(int(guild_data["player_controller"]["channel"]))
                original_message = await channel_db.fetch_message(int(guild_data["player_controller"]["message_id"]))
            except:
                pass

        embed_archived = disnake.Embed(
            description=f"**Kênh yêu cầu âm nhạc này được cấu hình lại bởi thành viên {inter.author.mention}.**",
            color=bot.get_color(guild.me)
        )

        async def get_message(original_message, target):

            if original_message and original_message.channel != target and original_message.guild.id == target.guild.id:

                try:
                    if isinstance(original_message.channel.parent, disnake.ForumChannel):
                        await original_message.thread.delete(reason=f"Người chơi được cấu hình lại bởi {inter.author}.")
                        return
                except AttributeError:
                    pass
                except Exception:
                    traceback.print_exc()
                    return

                try:
                    await original_message.edit(content=None, embed=embed_archived, view=None)
                except:
                    pass

                try:
                    await original_message.thread.edit(
                        archived=True,
                        locked=True,
                        reason=f"Người chơi được cấu hình lại bởi {inter.author}."
                    )
                except:
                    pass

            else:
                return original_message

        if not target:

            try:
                id_ = inter.id
            except AttributeError:
                id_ = ""

            kwargs_msg = {}
            try:
                func = inter.edit_original_message
            except:
                try:
                    func = inter.store_message.edit
                except:
                    try:
                        func = inter.response.edit_message
                    except:
                        func = inter.send
                        kwargs_msg = {"ephemeral": True}

            msg_select = await func(
                embed=disnake.Embed(
                    description="**Chọn một kênh bên dưới hoặc nhấp vào một trong các nút bên dưới để tạo một nút mới "
                                "Kênh để đặt hàng nhạc.**",
                    color=self.bot.get_color(guild.me)
                ).set_footer(text="Bạn chỉ có 30 giây để nhấp vào nút."),
                components=[
                    disnake.ui.ChannelSelect(
                        custom_id=f"existing_channel_{id_}",
                        min_values=1, max_values=1,
                        channel_types=[
                            disnake.ChannelType.text,
                            disnake.ChannelType.voice,
                            disnake.ChannelType.stage_voice,
                            disnake.ChannelType.forum
                        ]
                    ),
                    disnake.ui.Button(label="Tạo kênh văn bản ", custom_id=f"text_channel_{id_}", emoji="💬"),
                    disnake.ui.Button(label="Tạo kênh thoại", custom_id=f"voice_channel_{id_}", emoji="🔊"),
                    disnake.ui.Button(label="Tạo kênh sân khấu", custom_id=f"stage_channel_{id_}", emoji="<:stagechannel:1077351815533826209>"),
                    disnake.ui.Button(label="Hủy bỏ", custom_id=f"voice_channel_cancel_{id_}", emoji="❌")
                ],
                **kwargs_msg
            )

            if isinstance(inter, CustomContext):
                bot_inter = bot
                check = (lambda i: i.message.id == msg_select.id and i.author.id == inter.author.id)
            else:
                bot_inter = inter.bot
                check = (lambda i: i.data.custom_id.endswith(f"_{id_}") and i.author.id == inter.author.id)

            done, pending = await asyncio.wait([
                bot_inter.loop.create_task(bot_inter.wait_for('button_click', check=check)),
                bot_inter.loop.create_task(bot_inter.wait_for('dropdown', check=check))
            ],
                timeout=30, return_when=asyncio.FIRST_COMPLETED)

            for future in pending:
                future.cancel()

            if not done:

                try:
                    inter.application_command.reset_cooldown(inter)
                except AttributeError:
                    try:
                        inter.command.reset_cooldown(inter)
                    except:
                        pass

                if msg_select:
                    func = msg_select.edit
                else:
                    try:
                        func = (await inter.original_message()).edit
                    except:
                        func = inter.message.edit

                try:
                    await func(
                        embed=disnake.Embed(
                            description="**Đã hết thời gian!**",
                            color=disnake.Color.red()
                        ),
                        components=None
                    )
                except disnake.NotFound:
                    pass
                except Exception:
                    traceback.print_exc()

                return

            inter = done.pop().result()

            if inter.data.custom_id.startswith("voice_channel_cancel"):

                await inter.response.edit_message(
                    embed=disnake.Embed(
                        description="**Đã hủy bỏ hoạt động...**",
                        color=self.bot.get_color(guild.me),
                    ), components=None
                )
                return

            if channel.category and channel.category.permissions_for(guild.me).send_messages:
                target = channel.category
            else:
                target = guild

            if inter.data.custom_id.startswith("existing_channel_"):
                target = bot.get_channel(int(inter.data.values[0]))
            else:
                await inter.response.defer()
                if inter.data.custom_id.startswith("voice_channel_"):
                    target = await target.create_voice_channel(f"{bot.user.name} player controller", **channel_kwargs)
                elif inter.data.custom_id.startswith("stage_channel_"):
                    target = await target.create_stage_channel(f"{bot.user.name} player controller", **channel_kwargs)
                else:
                    target = await target.create_text_channel(f"{bot.user.name} player controller", **channel_kwargs)

            existing_channel = False

        if target == guild.public_updates_channel:
            raise GenericError("**Bạn không thể sử dụng kênh cập nhật Discord.**")

        if target == guild.rules_channel:
            raise GenericError("**Bạn không thể sử dụng kênh quy tắc.**")

        channel_name = f'{bot.user.name} Song Request'

        if isinstance(target, disnake.ForumChannel):

            channel_kwargs.clear()

            if not target.permissions_for(guild.me).create_forum_threads:
                raise GenericError(f"**{bot.user.mention} không có quyền đăng trên kênh {target.mention}.**")

            try:
                id_ = f"modal_{inter.id}"
            except AttributeError:
                id_ = f"modal_{inter.message.id}"

            await inter.response.send_modal(
                title="Xác định tên cho bài viết diễn đàn",
                custom_id=id_,
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Nome",
                        custom_id="forum_title",
                        min_length=4,
                        max_length=30,
                        value=channel_name,
                        required=True
                    )
                ]
            )

            try:
                inter: disnake.ModalInteraction = await inter.bot.wait_for("modal_submit", timeout=30, check=lambda i: i.custom_id == id_)
            except asyncio.TimeoutError:
                try:
                    func = inter.edit_original_message
                except AttributeError:
                    func = msg_select.edit
                await func(embed=disnake.Embed(description="### Đã hết thời gian!", color=bot.get_color(guild.me)), view=None)
                return

            try:
                await msg_select.delete()
            except:
                pass

            await inter.response.defer()

            channel_name = inter.text_values["forum_title"]

            thread_wmessage = await target.create_thread(
                name=channel_name,
                content="Đăng yêu cầu âm nhạc.",
                auto_archive_duration=10080,
                slowmode_delay=5,
            )

            message = await send_idle_embed(target=thread_wmessage.message, bot=bot, force=True,
                                            guild_data=guild_data)

            target = message.channel

            await get_message(original_message, target)

        else:

            if existing_channel and not guild.me.guild_permissions.administrator and not target.permissions_for(guild.me).manage_permissions:
                raise GenericError(f"**{guild.me.mention} không có sự cho phép của quản trị viên hoặc sự cho phép của "
                                   f"Quản lý quyền của kênh {target.mention}** Để chỉnh sửa các quyền "
                                   f"cần thiết cho hệ thống yêu cầu âm nhạc hoạt động đúng.\n\n"
                                   f"Nếu bạn không muốn cung cấp quyền quản trị viên hoặc chỉnh sửa các quyền của"
                                   f" kênh {target.mention} Để cho phép tôi quản lý các quyền, hãy sử dụng lại lệnh "
                                   f"mà không cần chọn một kênh đích.")

            if not target.permissions_for(guild.me).read_messages:
                raise GenericError(f"{bot.user.mention} Quyền đọc tin nhắn kênh {target.mention}")

            if purge_messages == "yes":
                await target.purge(limit=100, check=lambda m: m.author != guild.me or not m.thread)

            message = await get_message(original_message, target)

            if not message:

                async for m in target.history(limit=100):

                    if m.author == guild.me and m.thread:
                        message = m
                        break

        if existing_channel:
            try:
                await target.edit(**channel_kwargs)
            except:
                traceback.print_exc()

        channel = target

        msg = f"Kênh đặt hàng âm nhạc được xác định cho <#{channel.id}> thông qua bot: {bot.user.mention}"

        if player and player.text_channel != target:
            if player.static:
                try:
                    await player.message.thread.edit(
                        archived=True,
                        locked=True,
                        reason=f"Người chơi được cấu hình lại bởi {inter.author}."
                    )
                except:
                    pass
            else:
                try:
                    await player.message.delete()
                except:
                    pass
            if not message or message.channel.id != channel.id:
                message = await send_idle_embed(channel, bot=bot, force=True, guild_data=guild_data)
            player.message = message
            player.static = True
            player.text_channel = channel
            player.setup_hints()
            await player.invoke_np(force=True)

        elif not message or message.channel.id != channel.id:
            message = await send_idle_embed(channel, bot=bot, force=True, guild_data=guild_data)

        if not isinstance(channel, (disnake.VoiceChannel, disnake.StageChannel)):
            if not message.thread:
                await message.create_thread(name="Song-Requests", auto_archive_duration=10080)
            elif message.thread.archived:
                await message.thread.edit(archived=False, reason=f"Yêu cầu bài hát được kích hoạt lại bởi: {inter.author}.")
        elif player and player.guild.me.voice.channel != channel:
            await player.connect(channel.id)

        guild_data['player_controller']['channel'] = str(channel.id)
        guild_data['player_controller']['message_id'] = str(message.id)
        await bot.update_data(guild.id, guild_data, db_name=DBModel.guilds)

        reset_txt = f"{inter.prefix}reset" if isinstance(inter, CustomContext) else "/reset"

        embed = disnake.Embed(
            description=f"**{msg}**\n\nLưu ý: Nếu bạn muốn đảo ngược cấu hình này, chỉ cần sử dụng lệnh {reset_txt} hoặc "
                        f"Xóa kênh/bài đăng {channel.mention}",
            color=bot.get_color(guild.me)
        )
        try:
            await inter.edit_original_message(embed=embed, components=None)
        except (AttributeError, disnake.InteractionNotEditable):
            try:
                await inter.response.edit_message(embed=embed, components=None)
            except:
                await inter.send(embed=embed, ephemeral=True)

    @commands.has_guild_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(manage_threads=True)
    @commands.command(
        name="reset", usage="[--delete]",
        description="Đặt lại các cài đặt liên quan đến kênh yêu cầu bài hát.",
        cooldown=setup_cd, max_concurrency=setup_mc
    )
    async def reset_legacy(self, ctx: CustomContext, *, delete_channel: str = None):

        if delete_channel == "--delete":
            delete_channel = "sim"

        await self.reset.callback(self=self, inter=ctx, delete_channel=delete_channel)

    @commands.slash_command(
        description=f"{desc_prefix}Đặt lại các cài đặt liên quan đến kênh yêu cầu bài hát.",
        default_member_permissions=disnake.Permissions(manage_guild=True), cooldown=setup_cd, max_concurrency=setup_mc
    )
    async def reset(
            self,
            inter: disnake.AppCmdInter,
            delete_channel: str = commands.Param(
                name="deletar_canal",
                description="Xóa kênh điều khiển trình phát ", default=None, choices=["sim", "não"]
            )
    ):

        inter, bot = await select_bot_pool(inter)

        if not bot:
            return

        await inter.response.defer(ephemeral=True)

        guild = bot.get_guild(inter.guild_id) or inter.guild

        if not guild.me.guild_permissions.manage_threads:
            raise GenericError(f"Tôi không được phép **{perms_translations['manage_threads']}** trên máy chủ.")

        channel_inter = bot.get_channel(inter.channel.id)

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

        try:
            channel = bot.get_channel(int(guild_data['player_controller']['channel'])) or \
                      await bot.fetch_channel(int(guild_data['player_controller']['channel']))
        except:
            channel = None

        if not channel or channel.guild.id != inter.guild_id:
            raise GenericError(f"**Không có kênh đặt hàng âm nhạc được cấu hình (hoặc kênh đã bị xóa).**")

        try:
            if isinstance(channel.parent, disnake.ForumChannel):
                await channel.delete(reason=f"{inter.author.id} resetou player")
                if channel_inter != channel:
                    await inter.edit_original_message("Bài đăng đã bị xóa thành công!", embed=None, components=None)

                try:
                    player: LavalinkPlayer = bot.music.players[guild.id]
                except KeyError:
                    pass
                else:
                    player.static = False
                    player.message = None
                    player.text_channel = channel_inter
                    player.process_hint()
                    await player.invoke_np(force=True)

                return

        except AttributeError:
            pass

        try:
            original_message = await channel.fetch_message(int(guild_data["player_controller"]["message_id"]))
        except:
            original_message = None

        guild_data["player_controller"].update({
            "message_id": None,
            "channel": None
        })

        await self.bot.update_data(guild.id, guild_data, db_name=DBModel.guilds)

        try:
            func = inter.edit_original_message
        except AttributeError:
            try:
                func = inter.response.edit_message
            except AttributeError:
                func = inter.send

        await func(
            embed=disnake.Embed(
                color=self.bot.get_color(guild.me),
                description="**Kênh yêu cầu âm nhạc đã được thiết lập lại thành công.**"
            ), components=[]
        )

        try:
            player: LavalinkPlayer = bot.music.players[guild.id]
        except KeyError:
            pass
        else:
            player.static = False
            player.message = None
            player.text_channel = channel_inter
            player.process_hint()
            await player.invoke_np(force=True)

        try:
            if delete_channel == "sim":
                await channel.delete(reason=f"Đặt lại người chơi bởi: {inter.author}")

            elif original_message:
                await original_message.edit(
                    content=f"Kênh để đặt hàng nhạc được đặt lại bởi thành viên {inter.author.mention}.",
                    embed=None, components=[
                        disnake.ui.Button(label="Reconfigurar este canal", emoji="💠",
                                          custom_id="musicplayer_request_channel")
                    ]
                )
                await original_message.thread.edit(archived=True, reason=f"Đặt lại người chơi {inter.author}.")
        except Exception as e:
            traceback.print_exc()
            raise GenericError(
                "**Kênh yêu cầu âm nhạc đã được đặt lại của cơ sở dữ liệu nhưng xảy ra lỗi trong quá trình:** "
                f"```py\n{repr(e)}```"
            )

    djrole_cd = commands.CooldownMapping.from_cooldown(1, 7, commands.BucketType.guild)
    djrole_mc =commands.MaxConcurrency(1, per=commands.BucketType.guild, wait=False)

    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="adddjrole",description="Thêm một vị trí vào danh sách DJ của máy chủ.",
                      usage="[id / nome / @cargo]", cooldown=djrole_cd, max_concurrency=djrole_mc)
    async def add_dj_role_legacy(self, ctx: CustomContext, *, role: Optional[disnake.Role] = None):

        if not role:
            raise GenericError("**Bạn đã không chỉ định một vị trí.\n"
                               "Sử dụng lệnh bằng một trong các phương thức bên dưới:**\n\n"
                               f"{ctx.prefix}{ctx.invoked_with} id_do_cargo\n"
                               f"{ctx.prefix}{ctx.invoked_with} @cargo\n"
                               f"{ctx.prefix}{ctx.invoked_with} nome_do_cargo")

        await self.add_dj_role.callback(self=self,inter=ctx, role=role)

    @commands.slash_command(
        description=f"{desc_prefix}Thêm một vị trí vào danh sách DJ của máy chủ.",
        default_member_permissions=disnake.Permissions(manage_guild=True), cooldown=djrole_cd, max_concurrency=djrole_mc
    )
    async def add_dj_role(
            self,
            inter: disnake.ApplicationCommandInteraction,
            role: disnake.Role = commands.Param(name="cargo", description="Cargo")
    ):

        inter, bot = await select_bot_pool(inter)
        guild = bot.get_guild(inter.guild_id) or inter.guild
        role = guild.get_role(role.id)

        if role == guild.default_role:
            await inter.send("Bạn không thể thêm vị trí này.", ephemeral=True)
            return

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

        if str(role.id) in guild_data['djroles']:
            await inter.send(f"vị trí {role.mention} đã nằm trong danh sách của DJ", ephemeral=True)
            return

        guild_data['djroles'].append(str(role.id))

        await bot.update_data(guild.id, guild_data, db_name=DBModel.guilds)

        await inter.send(f"vị trí {role.mention} Nó đã được thêm vào danh sách của DJ.", ephemeral=True)

    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(description="Xóa một vị trí cho danh sách DJ của máy chủ.", usage="[id / nome / @cargo]",
                      cooldown=djrole_cd, max_concurrency=djrole_mc)
    async def remove_dj_role_legacy(self, ctx: CustomContext, *, role: disnake.Role):
        await self.remove_dj_role.callback(self=self, inter=ctx, role=role)

    @commands.slash_command(
        description=f"{desc_prefix}Xóa một vị trí cho danh sách DJ của máy chủ.",
        default_member_permissions=disnake.Permissions(manage_guild=True), cooldown=djrole_cd, max_concurrency=djrole_mc
    )
    async def remove_dj_role(
            self,
            inter: disnake.ApplicationCommandInteraction,
            role: disnake.Role = commands.Param(name="cargo", description="Cargo")
    ):

        inter, bot = await select_bot_pool(inter)

        if not bot:
            return

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

        if not guild_data['djroles']:

            await inter.send("Không có vị trí trong danh sách của DJ.", ephemeral=True)
            return

        guild = bot.get_guild(inter.guild_id) or inter.guild
        role = guild.get_role(role.id)

        if str(role.id) not in guild_data['djroles']:
            await inter.send(f"vị trí {role.mention} không có trong danh sách của DJ\n\n" + "Cargos:\n" +
                                              " ".join(f"<#{r}>" for r in guild_data['djroles']), ephemeral=True)
            return

        guild_data['djroles'].remove(str(role.id))

        await bot.update_data(guild.id, guild_data, db_name=DBModel.guilds)

        await inter.send(f"vị trí {role.mention} foi removido da lista de DJ's.", ephemeral=True)

    skin_cd = commands.CooldownMapping.from_cooldown(1, 20, commands.BucketType.guild)
    skin_mc =commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(description="Thay đổi ngoại hình/da.", name="changeskin", aliases=["skin"],
                      cooldown=skin_cd, max_concurrency=skin_mc)
    async def change_skin_legacy(self, ctx: CustomContext):

        await self.change_skin.callback(self=self, inter=ctx)

    @commands.slash_command(
        description=f"{desc_prefix}Thay đổi ngoại hình/da.", cooldown=skin_cd, max_concurrency=skin_mc,
        default_member_permissions=disnake.Permissions(manage_guild=True)
    )
    async def change_skin(self, inter: disnake.AppCmdInter):

        inter, bot = await select_bot_pool(inter)

        if not bot:
            return

        skin_list = [s for s in bot.player_skins if s not in bot.config["IGNORE_SKINS"].split()]
        static_skin_list = [s for s in bot.player_static_skins if s not in bot.config["IGNORE_STATIC_SKINS"].split()]

        await inter.response.defer(ephemeral=True)

        guild = bot.get_guild(inter.guild_id) or inter.guild

        add_skin_prefix = (lambda d: [f"> custom_skin: {i}" for i in d.keys()])

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

        try:
            global_data = inter.global_guild_data
        except AttributeError:
            global_data = await bot.get_global_data(guild.id, db_name=DBModel.guilds)
            inter.global_guild_data = global_data

        global_mode = global_data["global_skin"]

        selected = guild_data["player_controller"]["skin"] or bot.default_skin
        static_selected = guild_data["player_controller"]["static_skin"] or bot.default_static_skin

        global_selected = global_data["player_skin"] or bot.default_skin
        global_static_selected = global_data["player_skin_static"] or bot.default_static_skin

        skins_opts = [disnake.SelectOption(emoji="💠" if s.startswith("> custom_skin: ") else "🎨", label=f"Chế độ bình thường: {s.replace('> custom_skin: ', '')}", value=s, **{"default": True, "description": "skin atual"} if selected == s else {}) for s in skin_list + add_skin_prefix(global_data["custom_skins"])]
        static_skins_opts = [disnake.SelectOption(emoji="💠" if s.startswith("> custom_skin: ") else "🎨", label=f"Yêu cầu bài hát: {s.replace('> custom_skin: ', '')}", value=s, **{"default": True, "description": "skin atual"} if static_selected == s else {}) for s in static_skin_list + add_skin_prefix(global_data["custom_skins_static"])]

        global_skins_opts = [disnake.SelectOption(emoji="💠" if s.startswith("> custom_skin: ") else "🎨", label=f"Chế độ bình thường: {s.replace('> custom_skin: ', '')}", value=s, **{"default": True, "description": "skin atual"} if global_selected == s else {}) for s in skin_list + add_skin_prefix(global_data["custom_skins"])]
        global_static_skins_opts = [disnake.SelectOption(emoji="💠" if s.startswith("> custom_skin: ") else "🎨", label=f"Yêu cầu bài hát: {s.replace('> custom_skin: ', '')}", value=s, **{"default": True, "description": "skin atual"} if global_static_selected == s else {}) for s in static_skin_list + add_skin_prefix(global_data["custom_skins_static"])]

        embed = disnake.Embed(
            description="**Chế độ bình thường:**\n\n" + "\n".join(f"`{s}` [`(visualizar)`]({bot.player_skins[s].preview})" for s in skin_list) + "\n\n" 
                        "**Chế độ cố định (yêu cầu bài hát):**\n\n" + "\n".join(f"`{s}` [`(visualizar)`]({bot.player_static_skins[s].preview})" for s in static_skin_list) +
                        "\n\n`Lưu ý: Trong chế độ toàn cầu, tất cả các bot máy chủ đều sử dụng cùng một làn da.`",
            colour=bot.get_color(guild.me)
        )

        try:
            if bot.user.id != self.bot.user.id:
                embed.set_footer(text=f"Sử dụng: {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
        except AttributeError:
            pass

        select_view = SkinSelector(inter, embed, skins_opts, static_skins_opts, global_skins_opts, global_static_skins_opts, global_mode)

        try:
            func = inter.store_message.edit
        except:
            try:
                func = inter.edit_original_message
            except AttributeError:
                func = inter.send

        msg = await func(
            embed=embed,
            view=select_view
        )

        await select_view.wait()

        if select_view.skin_selected is None:
            await select_view.interaction.response.edit_message(
                view=None,
                embed=disnake.Embed(description="**Yêu cầu bị hủy bỏ.**", colour=bot.get_color(guild.me))
            )
            return

        if not select_view.interaction:
            try:
                msg = await inter.original_message()
            except AttributeError:
                pass
            await msg.edit(view=None, embed=disnake.Embed(description="**Đã hết thời gian!**", colour=bot.get_color(guild.me)))
            return

        inter = select_view.interaction

        try:
            global_data.update({"global_skin": select_view.global_mode})
        except:
            pass

        changed_skins_txt = ""

        if select_view.global_mode:
            try:
                global_data.update(
                    {
                        "player_skin": select_view.skin_selected,
                        "player_skin_static": select_view.static_skin_selected
                    }
                )
            except:
                pass
            else:
                await bot.update_global_data(inter.guild_id, global_data, db_name=DBModel.guilds)

            if global_selected != select_view.skin_selected:
                try:
                    changed_skins_txt += f"Global - Chế độ bình thường: [`{select_view.skin_selected}`]({self.bot.player_skins[select_view.skin_selected].preview})\n"
                except:
                    changed_skins_txt += f"Global - Chế độ bình thường: `{select_view.skin_selected.replace('> custom_skin: ', '[custom skin]: ')}`\n"

            if global_static_selected != select_view.static_skin_selected:
                try:
                    changed_skins_txt += f"Global - Yêu cầu bài hát: [`{select_view.static_skin_selected}`]({self.bot.player_static_skins[select_view.static_skin_selected].preview})\n"
                except:
                    changed_skins_txt += f"Global - Yêu cầu bài hát: `{select_view.static_skin_selected.replace('> custom_skin: ', '[custom skin]: ')}`\n"

        else:
            guild_data["player_controller"]["skin"] = select_view.skin_selected
            guild_data["player_controller"]["static_skin"] = select_view.static_skin_selected
            await bot.update_data(inter.guild_id, guild_data, db_name=DBModel.guilds)

            if selected != select_view.skin_selected:
                try:
                    changed_skins_txt += f"Chế độ bình thường: [`{select_view.skin_selected}`]({self.bot.player_skins[select_view.skin_selected].preview})\n"
                except:
                    changed_skins_txt += f"Chế độ bình thường: `{select_view.skin_selected.replace('> custom_skin: ', '[custom skin]: ')}`\n"

            if static_selected != select_view.static_skin_selected:
                try:
                    changed_skins_txt += f"Yêu cầu bài hát: [`{select_view.static_skin_selected}`]({self.bot.player_static_skins[select_view.static_skin_selected].preview})\n"
                except:
                    changed_skins_txt += f"Yêu cầu bài hát: `{select_view.static_skin_selected.replace('> custom_skin: ', '[custom skin]: ')}`\n"

        if global_mode != select_view.global_mode:
            changed_skins_txt += "Skin Global: `" + ("Kích hoạt" if select_view.global_mode else "Vô hiệu hóa") + "`\n"

        if not changed_skins_txt:
            txt = "**Không có thay đổi trong cài đặt da...**"
        else:
            txt = f"**Da máy chủ của máy chủ đã được thay đổi thành công.**\n{changed_skins_txt}"

        kwargs = {
            "embed": disnake.Embed(
                description=txt,
                color=bot.get_color(guild.me)
            ).set_footer(text=f"{bot.user} - [{bot.user.id}]", icon_url=bot.user.display_avatar.with_format("png").url)
        }

        if msg:
            await msg.edit(view=None, **kwargs)
        elif inter.response.is_done():
            await inter.edit_original_message(view=None, **kwargs)
        else:
            await inter.send(ephemeral=True, **kwargs)

        for b in self.bot.pool.bots:

            try:
                player = b.music.players[inter.guild_id]
            except KeyError:
                continue

            last_skin = str(player.skin)
            last_static_skin = str(player.skin_static)

            player.skin = select_view.skin_selected
            player.skin_static = select_view.static_skin_selected
            player.setup_features()

            if player.static:

                if select_view.static_skin_selected == last_static_skin:
                    continue

            elif select_view.skin_selected == last_skin:
                continue

            player.setup_hints()
            player.process_hint()
            player.set_command_log(text=f"{inter.author.mention} đã thay đổi giao diện của trình phát.", emoji="🎨")
            await player.invoke_np(force=True)
            await asyncio.sleep(1.5)

    @commands.cooldown(2, 10, commands.BucketType.member)
    @commands.has_guild_permissions(manage_channels=True)
    @pool_command(aliases=["la"], description="Kích hoạt việc gửi lời mời nghe cùng nhau qua RPC "
                                                                "(Hệ thống vẫn còn trong các thử nghiệm)")
    async def listenalong(self, ctx: CustomContext):

        try:
            bot = ctx.music_bot
            guild = ctx.music_guild
        except AttributeError:
            bot = ctx.bot
            guild = bot.get_guild(ctx.guild_id)

        if not guild.me.guild_permissions.create_instant_invite:
            raise GenericError(f"**{bot.user.mention} Không có quyền tạo lời mời tức thì...**")

        if not ctx.author.voice.channel:
            raise NoVoice()

        await ctx.reply(
            embed=disnake.Embed(
                description=f"**Tạo lời mời trên kênh {ctx.author.voice.channel.mention} Đánh dấu tùy chọn "
                            f"\"Đăng ký làm khách\" và sau đó nhấp vào nút bên dưới để gửi liên kết "
                            f"lời mời.**\n\n"
                            f"Cẩn thận!Nếu bạn không có tùy chọn này, điều đó có nghĩa là tính năng không có sẵn trong "
                            f"máy chủ và tôi không khuyên bạn nên tiến hành để tránh truy cập vĩnh viễn cho thành viên bạn sử dụng "
                            f"nút hoặc tránh các vấn đề về quyền, v.v.."
            ).set_image(url="https://cdn.discordapp.com/attachments/554468640942981147/1108943648508366868/image.png").
            set_footer(text="Lưu ý: Tạo một lời mời mà không có giới hạn như: ngày hết hạn, số lượng sử dụng hoặc "
                            "Chỉ cho người dùng sử dụng."),
            components=[disnake.ui.Button(label="Mời", custom_id=f"listen_along_{ctx.author.id}")]
        )

    @commands.Cog.listener("on_button_click")
    async def send_listen_along_invite(self, inter: disnake.MessageInteraction):

        if not inter.data.custom_id.startswith("listen_along_"):
            return

        if not inter.data.custom_id.endswith(str(inter.author.id)):
            return await inter.send("**Bạn không thể sử dụng nút này.**", ephemeral=True)

        if not inter.author.voice.channel:
            return await inter.send("**Bạn cần phải ở trên một kênh thoại để gửi lời mời.**", ephemeral=True)

        await inter.response.send_modal(
            title="Mời nghe cùng nhau",
            custom_id="listen_along_modal",
            components=[
                disnake.ui.TextInput(
                    style=disnake.TextInputStyle.short,
                    label="Dán lời mời trong lĩnh vực dưới đây:",
                    custom_id="invite_url",
                    min_length=25,
                    max_length=36,
                    required=True,
                ),
            ]
        )

    @commands.Cog.listener("on_modal_submit")
    async def listen_along_modal(self, inter: disnake.ModalInteraction):

        if inter.data.custom_id != "listen_along_modal":
            return

        if not inter.author.voice.channel:
            return await inter.send("**Bạn cần phải ở trên một kênh thoại để gửi lời mời.**", ephemeral=True)

        bucket = self.invite_cooldown.get_bucket(inter)
        retry_after = bucket.update_rate_limit()

        if retry_after:
            return await inter.send("**Bạn phải đợi {} Để gửi lời mời**".format(time_format(int(retry_after) * 1000, use_names=True)), ephemeral=True)

        await inter.response.defer(ephemeral=True)

        try:
            invite = await self.bot.fetch_invite(inter.text_values['invite_url'].strip(), with_expiration=True)
        except disnake.NotFound:
            return await inter.edit_original_message("Liên kết không hợp lệ hoặc lời mời không tồn tại/hết hạn")

        if invite.max_uses:
            return await inter.edit_original_message("Lời mời có thể có số lượng sử dụng tối đa")

        if invite.target_user:
            return await inter.edit_original_message("Lời mời không thể được cấu hình chỉ cho 1 người dùng sử dụng.")

        channel = None

        for bot in self.bot.pool.bots:

            channel = bot.get_channel(invite.channel.id)

            if not channel:
                continue

            if not isinstance(channel, disnake.VoiceChannel):
                return await inter.edit_original_message("**Tính năng này chỉ hoạt động trên các kênh thoại.**")

            break

        if not channel:
            return await inter.edit_original_message("**Không có bot tương thích được thêm vào máy chủ mời thông tin.**")

        try:
            global_data = inter.global_guild_data
        except AttributeError:
            global_data = await self.bot.get_global_data(inter.guild_id, db_name=DBModel.guilds)
            try:
                inter.global_guild_data = global_data
            except:
                pass

        if len(global_data["listen_along_invites"]) > 4:
            return await inter.edit_original_message(
                embed=disnake.Embed(
                    description="**Giới hạn lời mời vượt quá trên máy chủ hiện tại, xóa ít nhất một trong những lời mời"
                                "Bên dưới máy chủ:** ```ansi\n" +
                                ", ".join(f"[31;1m{c}[0m" for c in global_data["listen_along_invites"]) + "```",
                    color=self.bot.get_color()
                )
            )

        global_data["listen_along_invites"][str(inter.channel.id)] = invite.url

        await self.bot.update_global_data(inter.guild_id, global_data, db_name=DBModel.guilds)

        await inter.edit_original_message(
            f"**O liên kết {invite} đã được kích hoạt/cập nhật thành công để được gửi qua RPC khi có "
            f"Trình phát hoạt động trên kênh {inter.author.voice.channel.mention}.**\n"
            f"`Lưu ý: Nếu bạn muốn hiển thị trong trạng thái của mình và không có ứng dụng RPC, hãy sử dụng lệnh /Rich_presence để "
            f"Có thêm thông tin.`"
        )

        for bot in self.bot.pool.bots:

            try:
                p = bot.music.players[inter.guild_id]
            except KeyError:
                continue

            if p.guild.me.voice.channel == inter.author.voice.channel:
                p.listen_along_invite = invite.url
                await p.process_rpc()
                await p.process_save_queue()

    @commands.Cog.listener("on_modal_submit")
    async def rpc_create_modal(self, inter: disnake.ModalInteraction):

        if inter.data.custom_id != "rpc_token_create":
            return

        await inter.response.defer(ephemeral=True)

        data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        if inter.text_values["token_input"] == data["token"]:
            await inter.send("Seu token é igual ao token atual!", ephemeral=True)
            return

        await self.bot.get_cog("RPCCog").close_presence(inter)

        data["token"] = inter.text_values["token_input"]

        await self.bot.update_global_data(id_=inter.author.id, data=data, db_name=DBModel.users)

        await inter.edit_original_message(f"Mã thông báo của bạn đã được nhập/chỉnh sửa thành công!\n"
                                          f"Lưu ý: Thêm/Cập nhật mã thông báo trong ứng dụng RPC.")

    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.command(
        name="nodeinfo",
        aliases=["llservers", "ll"],
        description="Xem thông tin từ máy chủ âm nhạc."
    )
    async def nodeinfo_legacy(self, ctx: CustomContext):
        await self.nodeinfo.callback(self=self, inter=ctx)

    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.slash_command(
        description=f"{desc_prefix}Xem thông tin từ các máy chủ âm nhạc (máy chủ Lavalink)."
    )
    async def nodeinfo(self, inter: disnake.AppCmdInter):

        inter, bot = await select_bot_pool(inter)

        if not bot:
            return

        guild = bot.get_guild(inter.guild_id) or inter.guild

        em = disnake.Embed(color=bot.get_color(guild.me), title="Máy chủ âm nhạc:")

        if not bot.music.nodes:
            em.description = "**Không có máy chủ.**"
            await inter.send(embed=em)
            return

        failed_nodes = set()

        for identifier, node in bot.music.nodes.items():

            if not node.available: continue

            try:
                current_player = node.players[inter.guild_id]
            except KeyError:
                current_player = None

            if not node.stats or not node.is_available:
                failed_nodes.add(node.identifier)
                continue

            txt = f"Vùng `{node.region.title()}`\n"

            used = humanize.naturalsize(node.stats.memory_used)
            total = humanize.naturalsize(node.stats.memory_allocated)
            free = humanize.naturalsize(node.stats.memory_free)
            cpu_cores = node.stats.cpu_cores
            cpu_usage = f"{node.stats.lavalink_load * 100:.2f}"
            started = node.stats.players

            txt += f'RAM: `{used}/{free}`\n' \
                   f'Tổng RAM: `{total}`\n' \
                   f'Số nhân CPU: `{cpu_cores}`\n' \
                   f'Mức sử dụng CPU: `{cpu_usage}%`\n' \
                   f'Lần khởi động lại cuối cùng <t:{int((disnake.utils.utcnow() - datetime.timedelta(milliseconds=node.stats.uptime)).timestamp())}:R>\n'

            if started:
                txt += "Players: "
                players = node.stats.playing_players
                idle = started - players
                if players:
                    txt += f'`[▶️{players}]`' + (" " if idle else "")
                if idle:
                    txt += f'`[💤{idle}]`'

                txt += "\n"

            if node.website:
                txt += f'[`Trang web của máy chủ`]({node.website})\n'

            status = "🌟" if current_player else "✅"

            em.add_field(name=f'**{identifier}** `{status}`', value=txt)
            em.set_footer(text=f"{bot.user} - [{bot.user.id}]", icon_url=bot.user.display_avatar.with_format("png").url)

        embeds = [em]

        if failed_nodes:
            embeds.append(
                disnake.Embed(
                    title="**Các máy chủ lỗi** `❌`",
                    description=f"```ansi\n[31;1m" + "\n".join(failed_nodes) + "[0m\n```",
                    color=bot.get_color(guild.me)
                )
            )

        await inter.send(embeds=embeds, ephemeral=True)

class RPCCog(commands.Cog):

    def __init__(self, bot: BotCore):
        self.bot = bot

    rpc_cd = commands.CooldownMapping.from_cooldown(1, 30, commands.BucketType.user)

    @commands.command(description="Kích hoạt/Vô hiệu hóa hệ thống trình bày phong phú trong trạng thái của bạn.",
                      name="richpresence", aliases=["rich_presence", "rpc"], cooldown=rpc_cd)
    async def rich_presence_legacy(self, ctx: CustomContext):

        await self.rich_presence.callback(self=self, inter=ctx)

    @commands.slash_command(
        description=f"{desc_prefix}Kích hoạt/Vô hiệu hóa hệ thống trình bày phong phú trong trạng thái của bạn.", cooldown=rpc_cd
    )
    async def rich_presence(self, inter: disnake.AppCmdInter):

        if not self.bot.config["ENABLE_RPC_COMMAND"] and not any(await b.is_owner(inter.author) for b in self.bot.pool.bots):
            raise GenericError("**Lệnh này bị tắt trong cài đặt của tôi...**\n"
                               "Chỉ nhà phát triển của tôi mới có thể kích hoạt lệnh này công khai.")

        if not self.bot.config["RPC_PUBLIC_URL"] and not self.bot.config["RPC_SERVER"]:
            raise GenericError("**RPC_Server không được cấu hình trong env/môi trường (hoặc tệp .env)**")

        components = []

        embed = disnake.Embed(
            color=self.bot.get_color(),
            description="**Hướng dẫn nhỏ để sử dụng ứng dụng để hiển thị bài hát bạn đang nghe qua RPC:\n\n"
                        "Tải xuống ứng dụng (musicbot_rpc.zip) "
                        "[aqui](https://github.com/zRitsu/Discord-MusicBot-RPC/releases).\n\n"
                        "Trích xuất musicbot_rpc.zip và trong thư mục mở musicbot_rpc." \
                        "Thêm liên kết WebSocket bên dưới vào ứng dụng (tab: Socket Settings):** ```ansi\n" \
                        f"[34;1m{(self.bot.config['RPC_PUBLIC_URL'] or self.bot.config['RPC_SERVER']).replace('$PORT', os.environ.get('PORT', '80'))}[0m```"
        )

        embed.set_footer(text="Lưu ý: Hiện tại nó chỉ hoạt động trên Windows với Discord Desktop, không hoạt động trên thiết bị di động "
                              "hoặc Discord Web.")

        if self.bot.config["ENABLE_RPC_AUTH"]:

            embed.description += "\n**Bạn sẽ cần tạo/tạo/nhập mã thông báo để phát hành quyền truy cập RPC " \
                                 "(Kiểm tra các nút bên dưới), sao chép mã thông báo và ứng dụng (Tab: Cài đặt ổ cắm) " \
                                 "Nhấn nút \"Vòng cổ mã thông báo\"**"

            components.extend(
                [
                    disnake.ui.Button(label="Tạo/đặt lại token", custom_id=f"rpc_gen.{inter.author.id}", emoji="🔑",
                                      row=0),
                    disnake.ui.Button(label="Nhập/Chỉnh sửa/Xem token", custom_id=f"rpc_create.{inter.author.id}",
                                      emoji="✍️", row=0),
                    disnake.ui.Button(label="Xóa token (Tắt)", custom_id=f"rpc_remove.{inter.author.id}",
                                      emoji="♻️", row=1),
                ]
            )

        embed.description += "\n\n**Bây giờ chỉ cần nhấp vào nút \"Bắt đầu trên đường\" và nghe nhạc qua " \
                             "Một số bot tương thích.**"

        embed.set_author(
            name=f"{inter.author.display_name}#{inter.author.discriminator} - [ {inter.author.id} ]",
            icon_url=inter.author.display_avatar.with_static_format("png").url
        )

        if isinstance(inter, CustomContext):
            components.append(
                disnake.ui.Button(label="Đóng", custom_id=f"rpc_close.{inter.author.id}", emoji="❌", row=1),
            )

        await inter.send(
            embed=embed,
            components=components,
            ephemeral=True
        )

    @commands.Cog.listener("on_button_click")
    async def rpc_button_event(self, inter: disnake.MessageInteraction):

        if not inter.data.custom_id.startswith("rpc_"):
            return

        button_id, user_id = inter.data.custom_id.split(".")

        if user_id != str(inter.author.id):
            await inter.send(f"Chỉ <@{user_id}> mới có thể sử dụng các nút tin nhắn!", ephemeral=True)
            return

        if button_id == "rpc_gen":
            await inter.response.defer()

            try:
                data = inter.global_user_data
            except AttributeError:
                data = await self.bot.get_global_data(id_=user_id, db_name=DBModel.users)
                inter.global_user_data = data

            if data["token"]:
                await self.close_presence(inter)

            data["token"] = "".join(random.choice(string.ascii_letters + string.digits) for i in range(50))
            await self.bot.update_global_data(id_=user_id, data=data, db_name=DBModel.users)
            msg = f"token để sử dụng trên ứng dụng RPC (sự hiện diện phong phú) đã được tạo thành công!\n\n" \
                  f"`Token tạo ra:` ||{data['token']}||"

        elif button_id == "rpc_create":

            kwargs = {}

            try:

                try:
                    data = inter.global_user_data
                except AttributeError:
                    data = await self.bot.get_global_data(id_=user_id, db_name=DBModel.users)
                    inter.global_user_data = data

                if len(data["token"]) == 50:
                    kwargs["value"] = data["token"]
            except:
                pass

            await inter.response.send_modal(
                title="nhập token",
                custom_id="rpc_token_create",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Dán dây thông báo trên trường bên dưới:",
                        placeholder="Lưu ý: Đối với biện pháp an toàn, không bao giờ bao gồm mật khẩu cá nhân ở đây!",
                        custom_id="token_input",
                        min_length=50,
                        max_length=50,
                        required=True,
                        **kwargs
                    ),
                ]
            )

            if not inter.message.flags.ephemeral:
                await inter.message.delete()

            return

        elif button_id == "rpc_remove":

            await inter.response.defer()

            await self.close_presence(inter)

            try:
                data = inter.global_user_data
            except AttributeError:
                data = await self.bot.get_global_data(id_=user_id, db_name=DBModel.users)
                inter.global_user_data = data

            data["token"] = ""
            await self.bot.update_global_data(id_=user_id, data=data, db_name=DBModel.users)
            msg = "Mã thông báo đã được loại bỏ thành công!\n" \
                  "Bây giờ hệ thống RPC sẽ bị vô hiệu hóa trên người dùng của nó."

        else: # button_id == "rpc_close"
            await inter.message.delete()
            return

        if inter.message.flags.ephemeral:
            await inter.edit_original_message(content=msg, embeds=[], components=[])
        else:
            await inter.send(f"{inter.author.mention}: {msg}", embeds=[], components=[], ephemeral=True)
            await inter.message.delete()

    async def close_presence(self, inter: Union[disnake.MessageInteraction, disnake.ModalInteraction]):

        for b in self.bot.pool.bots:
            try:
                player: LavalinkPlayer = b.music.players[inter.guild_id]
            except KeyError:
                continue

            try:
                if inter.author.id not in player.guild.me.voice.channel.voice_states:
                    continue
            except AttributeError:
                continue

            stats = {
                "op": "close",
                "bot_id": self.bot.user.id,
                "bot_name": str(self.bot.user),
                "thumb": self.bot.user.display_avatar.replace(size=512, static_format="png").url,
            }

            await player._send_rpc_data([inter.author.id], stats)

def setup(bot: BotCore):

    bot.add_cog(MusicSettings(bot))
    bot.add_cog(RPCCog(bot))

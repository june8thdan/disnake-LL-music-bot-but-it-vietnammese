# -*- coding: utf-8 -*-
from __future__ import annotations

from io import BytesIO
import json
import traceback
from typing import TYPE_CHECKING, Union, Optional

import disnake
from disnake.ext import commands

from utils.music.converters import URL_REG, time_format
from utils.music.models import LavalinkPlayer
from utils.others import send_idle_embed, select_bot_pool, CustomContext, music_source_emoji_url
from utils.db import DBModel

if TYPE_CHECKING:
    from utils.client import BotCore


class GuildFavModal(disnake.ui.Modal):
    def __init__(self, bot: BotCore, name: Optional[str], description: Optional[str], url: Optional[str]):

        self.bot = bot
        self.name = name

        super().__init__(
            title="Thêm/Chỉnh sửa danh sách phát/yêu thích",
            custom_id="guild_fav_edit",
            timeout=180,
            components=[
                disnake.ui.TextInput(
                    label="Tên yêu thích/danh sách phát:",
                    custom_id="guild_fav_name",
                    min_length=2,
                    max_length=25,
                    value=name or None
                ),
                disnake.ui.TextInput(
                    label="Sự miêu tả:",
                    custom_id="guild_fav_description",
                    max_length=50,
                    value=description or None
                ),
                disnake.ui.TextInput(
                    label="Link/Url:",
                    custom_id="guild_fav_url",
                    min_length=10,
                    max_length=200,
                    value=url or None
                ),
            ]
        )

    async def callback(self, inter: disnake.ModalInteraction):

        url = inter.text_values["guild_fav_url"].strip()

        try:
            valid_url = URL_REG.findall(url)[0]
        except IndexError:
            await inter.send(
                embed=disnake.Embed(
                    description=f"**Không tìm thấy liên kết hợp lệ:** {url}",
                    color=disnake.Color.red()
                ), ephemeral=True
            )
            return

        await inter.response.defer(ephemeral=True)

        guild_data = await self.bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        if not guild_data["player_controller"]["channel"] or not self.bot.get_channel(int(guild_data["player_controller"]["channel"])):
            await inter.edit_original_message("**Không có người chơi được cấu hình trên máy chủ!Sử dụng lệnh /setup**")
            return

        name = inter.text_values["guild_fav_name"].strip()
        description = inter.text_values["guild_fav_description"].strip()

        if not guild_data["player_controller"]["channel"] or not self.bot.get_channel(
                int(guild_data["player_controller"]["channel"])):
            await inter.edit_original_message("**Không có người chơi được cấu hình trên máy chủ!Sử dụng lệnh /setup**")
            return

        try:
            if name != self.name:
                del guild_data["player_controller"]["fav_links"][self.name]
        except KeyError:
            pass

        guild_data["player_controller"]["fav_links"][name] = {'url': valid_url, "description": description}

        await self.bot.update_data(inter.guild_id, guild_data, db_name=DBModel.guilds)

        guild = inter.guild or self.bot.get_guild(inter.guild_id)

        await inter.edit_original_message(embed=disnake.Embed(description="**Liên kết được thêm/cập nhật thành công vào người chơi đã cố định!\n"
                         "Các thành viên có thể sử dụng nó trực tiếp trên bộ điều khiển người chơi khi không sử dụng.**",
                                                              color=self.bot.get_color(guild.me)), view=None)

        await self.bot.get_cog("PinManager").process_idle_embed(guild, guild_data=guild_data)

class GuildFavView(disnake.ui.View):

    def __init__(self, bot: BotCore, ctx: Union[disnake.AppCmdInter, CustomContext], data: dict):
        super().__init__(timeout=60)
        self.bot = bot
        self.ctx = ctx
        self.current = None
        self.data = data
        self.message = None

        if data["player_controller"]["fav_links"]:

            fav_select = disnake.ui.Select(options=[
                disnake.SelectOption(label=k, emoji=music_source_emoji_url(v['url']),description=v.get("description")) for k, v in data["player_controller"]["fav_links"].items()
            ], min_values=1, max_values=1)
            fav_select.callback = self.select_callback
            self.add_item(fav_select)

        favadd_button = disnake.ui.Button(label="Thêm", emoji="📌")
        favadd_button.callback = self.favadd_callback
        self.add_item(favadd_button)

        if data["player_controller"]["fav_links"]:

            edit_button = disnake.ui.Button(label="Chỉnh sửa", emoji="✍️")
            edit_button.callback = self.edit_callback
            self.add_item(edit_button)

            remove_button = disnake.ui.Button(label="Loại bỏ", emoji="♻️")
            remove_button.callback = self.remove_callback
            self.add_item(remove_button)

            export_button = disnake.ui.Button(label="Xuất", emoji="📤")
            export_button.callback = self.export_callback
            self.add_item(export_button)

        import_button = disnake.ui.Button(label="Nhập", emoji="📥")
        import_button.callback = self.import_callback
        self.add_item(import_button)

        cancel_button = disnake.ui.Button(label="Hủy", emoji="❌")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def on_timeout(self):

        if isinstance(self.ctx, CustomContext):
            try:
                await self.message.edit(
                    embed=disnake.Embed(description="**Đã hết thời gian...**", color=self.bot.get_color()), view=None
                )
            except:
                pass

        else:
            try:
                await self.ctx.edit_original_message(
                    embed=disnake.Embed(description="**Đã hết thời gian...**", color=self.bot.get_color()), view=None
                )
            except:
                pass
        self.stop()

    async def favadd_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(GuildFavModal(bot=self.bot, name=None, url=None, description=None))
        await inter.delete_original_message()
        self.stop()

    async def edit_callback(self, inter: disnake.MessageInteraction):

        if not self.current:
            await inter.send("Bạn phải chọn một mục!", ephemeral=True)
            return

        try:
            await inter.response.send_modal(
                GuildFavModal(
                    bot=self.bot, name=self.current,
                    url=self.data["player_controller"]["fav_links"][self.current]["url"],
                    description=self.data["player_controller"]["fav_links"][self.current]["description"]
                )
            )
        except KeyError:
            await inter.send(f"**Không có yêu thích với tên:** {self.current}", ephemeral=True)
            return

        if isinstance(self.ctx, disnake.AppCmdInter):
            await self.ctx.delete_original_message()
        else:
            await inter.message.delete()
        self.stop()

    async def remove_callback(self, inter: disnake.MessageInteraction):

        if not self.current:
            await inter.send("Bạn phải chọn một mục!", ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)

        try:
            guild_data = inter.guild_data
        except AttributeError:
            guild_data = await self.bot.get_data(inter.guild_id, db_name=DBModel.guilds)
            inter.guild_data = guild_data

        guild = self.bot.get_guild(inter.guild_id) or inter.guild

        try:
            del guild_data["player_controller"]["fav_links"][self.current]
        except KeyError:
            try:
                await self.bot.get_cog("PinManager").process_idle_embed(guild, guild_data=guild_data)
            except Exception:
                traceback.print_exc()

            await inter.edit_original_message(
                embed=disnake.Embed(
                    description=f"**Không có liên kết từ danh sách với tên:** {self.current}",
                    color=self.bot.get_color(guild.me)),
                view=None
            )

        await self.bot.update_data(inter.guild_id, guild_data, db_name=DBModel.guilds)

        await inter.edit_original_message(
            embed=disnake.Embed(description="**Liên kết đã loại bỏ thành công!**", color=self.bot.get_color(guild.me)),
            view=None)

        await self.bot.get_cog("PinManager").process_idle_embed(guild, guild_data=guild_data)
        self.stop()

    async def import_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(
            title="Nhập danh sách phát vào máy chủ",
            custom_id="guild_fav_import",
            components=[
                disnake.ui.TextInput(
                    style=disnake.TextInputStyle.long,
                    label="Chèn dữ liệu (ở định dạng JSON)",
                    custom_id="json_data",
                    min_length=20,
                    required=True
                )
            ]
        )
        await inter.delete_original_message()

    async def export_callback(self, inter: disnake.MessageInteraction):
        await self.bot.get_cog("PinManager").export_(inter)
        self.stop()

    async def cancel_callback(self, inter: disnake.MessageInteraction):
        await inter.response.edit_message(
            embed=disnake.Embed(
                description="**Hoạt động với các mục yêu thích của máy chủ bị hủy...**",
                color=self.bot.get_color(),
            ), view=None
        )
        self.stop()

    async def select_callback(self, inter: disnake.MessageInteraction):
        self.current = inter.values[0]
        await inter.response.defer()


class PinManager(commands.Cog):

    def __init__(self, bot: BotCore):
        self.bot = bot

    desc_prefix = "📌 [Danh sách phát máy chủ] 📌 | "

    async def process_idle_embed(self, guild: disnake.Guild, guild_data: dict = None):

        if not guild_data:
            guild_data = await self.bot.get_data(guild.id, db_name=DBModel.guilds)

        try:
            player: LavalinkPlayer = self.bot.music.players[guild.id]
            if not player.current:
                await player.process_idle_message()
            return
        except KeyError:
            pass

        try:
            channel = self.bot.get_channel(int(guild_data["player_controller"]["channel"]))
            message = await channel.fetch_message(int(guild_data["player_controller"]["message_id"]))

        except:
            return

        await send_idle_embed(message or channel, bot=self.bot, guild_data=guild_data)

    server_playlist_cd = commands.CooldownMapping.from_cooldown(3, 30, commands.BucketType.guild)

    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="serverplaylist", aliases=["spl", "svp", "svpl"],
                      description="Quản lý danh sách phát máy chủ/yêu thích.",
                      cooldown=server_playlist_cd)
    async def serverplaylist_legacy(self, ctx: CustomContext):
        await self.server_playlist.callback(self=self, inter=ctx)

    @commands.max_concurrency(1, commands.BucketType.guild, wait=False)
    @commands.slash_command(
        description=f"{desc_prefix}Quản lý danh sách phát máy chủ/yêu thích.",
        default_member_permissions=disnake.Permissions(manage_guild=True),
        cooldown=server_playlist_cd
    )
    async def server_playlist(self, inter: disnake.AppCmdInter):

        inter, bot = await select_bot_pool(inter)

        if not bot:
            return

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

        view = GuildFavView(bot=bot, ctx=inter, data=guild_data)

        embed = disnake.Embed(
            description="**Máy chủ yêu thích người quản lý.**",
            colour=self.bot.get_color(),
        )

        if isinstance(inter, CustomContext):
            try:
                view.message = inter.store_message
                await inter.store_message.edit(embed=embed, view=view)
            except:
                view.message = await inter.send(embed=embed, view=view)
        else:
            try:
                await inter.edit_original_message(embed=embed, view=view)
            except:
                await inter.response.edit_message(embed=embed, view=view)

        await view.wait()

    @commands.Cog.listener("on_modal_submit")
    async def modal_import(self, inter: disnake.ModalInteraction):

        if inter.custom_id != "guild_fav_import":
            return

        inter, bot = select_bot_pool(inter)

        try:
            json_data = json.loads(inter.text_values["json_data"])
        except Exception as e:
            await inter.send("**Một lỗi xảy ra khi phân tích dữ liệu hoặc dữ liệu không hợp lệ/không định dạng được gửi "
                               f"ở định dạng JSON.**\n\n`{repr(e)}`", ephemeral=True)
            return

        if retry_after:=self.server_playlist_cd.get_bucket(inter).update_rate_limit():
            if retry_after < 1:
                retry_after = 1
            await inter.send("**Bạn phải đợi {} để nhập.**".format(
                time_format(int(retry_after) * 1000, use_names=True)), ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)

        for name, data in json_data.items():

            if "> fav:" in name.lower():
                continue

            if len(data['url']) > (max_url_chars := bot.config["USER_FAV_MAX_URL_LENGTH"]):
                await inter.edit_original_message(f"**Một mục trong tệp của bạn vượt quá số lượng ký tự cho phép:{max_url_chars}\nURL:** {data['url']}")
                return

            if len(data['description']) > 50:
                await inter.edit_original_message(f"**Một mục trong tệp của bạn vượt quá số lượng ký tự cho phép:{max_url_chars}\nmiêu tả:** {data['description']}")
                return

            if not isinstance(data['url'], str) or not URL_REG.match(data['url']):
                await inter.edit_original_message(f"Tệp của bạn chứa liên kết không hợp lệ: ```ldif\n{data['url']}```")
                return

        guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        if not guild_data["player_controller"]["channel"] or not bot.get_channel(int(guild_data["player_controller"]["channel"])):
            await inter.edit_original_message("**Không có người chơi được cấu hình trên máy chủ!Sử dụng lệnh /setup**")
            return

        for name in json_data.keys():
            if len(name) > (max_name_chars := 25):
                await inter.edit_original_message(f"**Một mục từ tệp của bạn ({name}) vượt quá số lượng ký tự được phép:{max_name_chars}**")
                return
            try:
                del guild_data["player_controller"]["fav_links"][name]
            except KeyError:
                continue

        if (json_size:=len(json_data)) > 25:
            await inter.edit_original_message(f"Số lượng các mặt hàng trong tệp vượt quá số tiền tối đa được phép (25).")
            return

        if (json_size + (user_favs:=len(guild_data["player_controller"]["fav_links"]))) > 25:
            await inter.edit_original_message("Danh sách nhạc/danh sách phát của máy chủ không có đủ không gian để thêm tất cả các mục vào tệp của bạn...\n"
                                f"Giới hạn hiện tại: 25\n"
                                f"Số lượng liên kết đã lưu: {user_favs}\n"
                                f"Bạn cần phải: {(json_size + user_favs)-25}")
            return

        guild_data["player_controller"]["fav_links"].update(json_data)

        await self.bot.update_data(inter.guild_id, guild_data, db_name=DBModel.guilds)

        guild = bot.get_guild(inter.guild_id) or inter.guild

        cmd = f"</play:" + str(self.bot.pool.controller_bot.get_global_command_named("play", cmd_type=disnake.ApplicationCommandType.chat_input).id) + ">"

        await inter.edit_original_message(
            embed=disnake.Embed(
                color=self.bot.get_color(),
                description="**Các liên kết đã được nhập thành công!**\n"
                            f"**Sử dụng lệnh {cmd} Để kiểm tra (trong tìm kiếm tự động tìm kiếm).**",
            )
        )

        await self.process_idle_embed(guild, guild_data=guild_data)

    async def export_(self, inter: disnake.MessageInteraction):

        inter, bot = await select_bot_pool(inter)

        if not bot:
            return

        if retry_after:=self.server_playlist_cd.get_bucket(inter).update_rate_limit():
            if retry_after < 1:
                retry_after = 1
            await inter.send("**Bạn phải đợi {} để xuất.**".format(
                time_format(int(retry_after) * 1000, use_names=True)), ephemeral=True)
            return

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

        cmd = f"</{self.server_playlist.name}:" + str(self.bot.pool.controller_bot.get_global_command_named(self.server_playlist.name, cmd_type=disnake.ApplicationCommandType.chat_input).id) + ">"

        if not guild_data["player_controller"]["fav_links"]:
            await inter.edit_original_message(content=f"**Không có bài hát/danh sách phát được cố định trên máy chủ..\n"
                               f"Bạn có thể thêm bằng cách sử dụng lệnh: {cmd}**")

        fp = BytesIO(bytes(json.dumps(guild_data["player_controller"]["fav_links"], indent=4), 'utf-8'))

        guild = bot.get_guild(inter.guild_id) or inter.guild

        embed = disnake.Embed(
            description=f"**Dữ liệu của các liên kết nhạc/danh sách phát cố định của máy chủ ở đây.\n"
                        f"Bạn có thể nhập bằng lệnh:** {cmd}",
            color=self.bot.get_color(guild.me))

        await inter.edit_original_message(embed=embed, file=disnake.File(fp=fp, filename="guild_favs.json"), view=None)


def setup(bot: BotCore):
    bot.add_cog(PinManager(bot))

# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from io import BytesIO
from typing import TYPE_CHECKING, Union, Optional

import disnake
from disnake.ext import commands

from utils.db import DBModel
from utils.music.converters import URL_REG, time_format
from utils.others import CustomContext, music_source_emoji_url

if TYPE_CHECKING:
    from utils.client import BotCore


class UserFavModal(disnake.ui.Modal):
    def __init__(self, bot: BotCore, name: Optional[str], url: Optional[str]):

        self.bot = bot
        self.name = name

        super().__init__(
            title="Thêm/Chỉnh sửa danh sách phát/yêu thích",
            custom_id="user_fav_edit",
            timeout=180,
            components=[
                disnake.ui.TextInput(
                    label="Tên từ danh sách phát/yêu thích:",
                    custom_id="user_fav_name",
                    min_length=2,
                    max_length=25,
                    value=name or None
                ),
                disnake.ui.TextInput(
                    label="Link/Url:",
                    custom_id="user_fav_url",
                    min_length=10,
                    max_length=200,
                    value=url or None
                ),
            ]
        )

    async def callback(self, inter: disnake.ModalInteraction):

        url = inter.text_values["user_fav_url"].strip()

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

        user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        name = inter.text_values["user_fav_name"].strip()

        try:
            if name != self.name:
                del user_data["fav_links"][self.name]
        except KeyError:
            pass

        user_data["fav_links"][name] = valid_url

        await self.bot.update_global_data(inter.author.id, user_data, db_name=DBModel.users)

        try:
            me = (inter.guild or self.bot.get_guild(inter.guild_id)).me
        except AttributeError:
            me = None

        await inter.edit_original_message(
            embed=disnake.Embed(
                description="<:verify:1134033164151566460> **Liên kết được lưu/cập nhật thành công trong mục yêu thích của bạn!\n"
                            "Nó sẽ xuất hiện khi** ```\n"
                            "- Khi sử dụng lệnh /play (trong tìm kiếm tự động tìm kiếm)\n"
                            "- Khi nhấp vào nút chơi yêu thích của người chơi.\n"
                            "- Sử dụng lệnh !!aya p không có tên hoặc liên kết.```",
                color=self.bot.get_color(me)
            )
        )

class UserFavView(disnake.ui.View):

    def __init__(self, bot: BotCore, ctx: Union[disnake.AppCmdInter, CustomContext], data: dict):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        self.current = None
        self.data = data
        self.message = None

        if data["fav_links"]:

            fav_select = disnake.ui.Select(options=[
                disnake.SelectOption(label=k, emoji=music_source_emoji_url(v)) for k, v in data["fav_links"].items()
            ], min_values=1, max_values=1)
            fav_select.callback = self.select_callback
            self.add_item(fav_select)

        favadd_button = disnake.ui.Button(label="Thêm", emoji="⭐")
        favadd_button.callback = self.favadd_callback
        self.add_item(favadd_button)

        if data["fav_links"]:

            edit_button = disnake.ui.Button(label="Chỉnh sửa", emoji="✍️")
            edit_button.callback = self.edit_callback
            self.add_item(edit_button)

            remove_button = disnake.ui.Button(label="Loại bỏ", emoji="♻️")
            remove_button.callback = self.remove_callback
            self.add_item(remove_button)

            clear_button = disnake.ui.Button(label="Yêu thích", emoji="🚮")
            clear_button.callback = self.clear_callback
            self.add_item(clear_button)

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

        for c in self.children:
            c.disabled = True

        if isinstance(self.ctx, CustomContext):
            try:
                await self.message.edit(view=self)
            except:
                pass

        else:
            try:
                await self.ctx.edit_original_message(view=self)
            except:
                pass

    async def favadd_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(UserFavModal(bot=self.bot, name=None, url=None))
        await inter.delete_original_message()
        self.stop()

    async def edit_callback(self, inter: disnake.MessageInteraction):

        if not self.current:
            await inter.send("Bạn phải chọn một mục!", ephemeral=True)
            return

        try:
            await inter.response.send_modal(
                UserFavModal(
                    bot=self.bot, name=self.current,
                    url=self.data["fav_links"][self.current],
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
            user_data = inter.global_user_data
        except AttributeError:
            user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
            inter.global_user_data = user_data

        try:
            del user_data["fav_links"][self.current]
        except:
            await inter.edit_original_message(f"**Không có yêu thích trong danh sách với tên:** {self.current}")
            return

        await self.bot.update_global_data(inter.author.id, user_data, db_name=DBModel.users)

        await inter.edit_original_message(
            embed=disnake.Embed(
                description="**Liên kết/yêu thích đã được xóa thành công!**",
                color=self.bot.get_color()),
            view=None
        )
        self.stop()

    async def clear_callback(self, inter: disnake.MessageInteraction):

        await inter.response.defer(ephemeral=True)

        try:
            user_data = inter.global_user_data
        except AttributeError:
            user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
            inter.global_user_data = user_data

        if not user_data["fav_links"]:
            await inter.send("**Bạn không có liên kết yêu thích!**", ephemeral=True)
            return

        user_data["fav_links"].clear()

        await self.bot.update_global_data(inter.author.id, user_data, db_name=DBModel.users)

        embed = disnake.Embed(
            description="Danh sách yêu thích của bạn đã được làm sạch thành công!",
            color=self.bot.get_color()
        )

        await inter.edit_original_message(embed=embed, components=None)
        self.stop()

    async def import_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(
            title="Nhập yêu thích",
            custom_id="user_fav_import",
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
        await self.bot.get_cog("FavManager").export_(inter)
        self.stop()

    async def cancel_callback(self, inter: disnake.MessageInteraction):
        await inter.response.edit_message(
            embed=disnake.Embed(
                description="**Hoạt động với các mục yêu thích bị hủy...**",
                color=self.bot.get_color(),
            ), view=None
        )
        self.stop()

    async def select_callback(self, inter: disnake.MessageInteraction):
        self.current = inter.values[0]
        await inter.response.defer()


class FavManager(commands.Cog):

    def __init__(self, bot: BotCore):
        self.bot = bot

    desc_prefix = "⭐ [Yêu thích] ⭐ | "

    fav_cd = commands.CooldownMapping.from_cooldown(3, 15, commands.BucketType.member)

    @commands.command(name="favmanager", aliases=["favs", "favoritos", "fvmgr", "favlist"],
                      description="Quản lý danh sách phát/yêu thích của bạn.", cooldown=fav_cd)
    async def favmanager_legacy(self, ctx: CustomContext):
        await self.fav_manager.callback(self=self, inter=ctx)

    @commands.slash_command(description=f"{desc_prefix}Quản lý danh sách phát/yêu thích của bạn.", cooldown=fav_cd)
    async def fav_manager(self, inter: disnake.AppCmdInter):

        await inter.response.defer(ephemeral=True)

        try:
            user_data = inter.global_user_data
        except AttributeError:
            user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
            inter.global_user_data = user_data

        view = UserFavView(bot=self.bot, ctx=inter, data=user_data)

        embed = disnake.Embed(
            title="Quản lý yêu thích.",
            colour=self.bot.get_color(),
        )

        if user_data["fav_links"]:
            embed.description = f"**Yêu thích hiện tại của bạn:**\n\n" + "\n".join(
                f"> ` {n + 1} ` [`{f[0]}`]({f[1]})" for n, f in enumerate(user_data["fav_links"].items())
            )

            cog = self.bot.get_cog("Music")

            if cog:

                try:
                    global_data = inter.global_guild_data
                except AttributeError:
                    global_data = await self.bot.get_global_data(inter.guild_id, db_name=DBModel.guilds)
                    inter.global_guild_data = global_data

                cmd = f"</play:" + str(self.bot.pool.controller_bot.get_global_command_named("play",
                                                                                             cmd_type=disnake.ApplicationCommandType.chat_input).id) + ">"

                embed.add_field(name="**Làm thế nào để bạn sử dụng chúng?**", inline=False,
                                value=f"* Sử dụng lệnh {cmd} (Trong tìm kiếm tự động tìm kiếm)\n"
                                      "*Nhấp vào nút chơi yêu thích của người chơi.\n"
                                      f"* Sử dụng lệnh {global_data['prefix'] or self.bot.default_prefix}{cog.play_legacy.name}mà không sử dụng tên hoặc liên kết.")

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

    fav_import_export_cd = commands.CooldownMapping.from_cooldown(1, 15, commands.BucketType.member)

    @commands.Cog.listener("on_modal_submit")
    async def modal_import(self, inter: disnake.ModalInteraction):

        if inter.custom_id != "user_fav_import":
            return

        retry_after = self.fav_import_export_cd.get_bucket(inter).update_rate_limit()
        if retry_after:
            if retry_after < 1:
                retry_after = 1
            await inter.send("**Bạn phải đợi {} Nhập khẩu.**".format(
                time_format(int(retry_after) * 1000, use_names=True)), ephemeral=True)
            return

        try:
            json_data = json.loads(inter.text_values["json_data"])
        except Exception as e:
            await inter.send(
                "**Một lỗi xảy ra khi phân tích dữ liệu hoặc dữ liệu không hợp lệ/không định dạng được gửi "
                f"ở định dạng JSON.**\n\n`{repr(e)}`", ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)

        for name, url in json_data.items():

            if "> fav:" in name.lower():
                continue

            if len(url) > (max_url_chars := self.bot.config["USER_FAV_MAX_URL_LENGTH"]):
                await inter.edit_original_message(
                    f"**Một mục từ tệp của bạn {url} vượt quá số lượng ký tự cho phép:{max_url_chars}**")
                return

            if not isinstance(url, str) or not URL_REG.match(url):
                await inter.edit_original_message(f"Tệp của bạn chứa liên kết không hợp lệ: ```ldif\n{url}```")
                return

        user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        for name in json_data.keys():
            if len(name) > (max_name_chars := self.bot.config["USER_FAV_MAX_NAME_LENGTH"]):
                await inter.edit_original_message(
                    f"**Một mục từ tệp của bạn ({name}) vượt quá số lượng ký tự cho phép:{max_name_chars}**")
                return
            try:
                del user_data["fav_links"][name.lower()]
            except KeyError:
                continue

        if self.bot.config["MAX_USER_FAVS"] > 0 and not (await self.bot.is_owner(inter.author)):

            if (json_size := len(json_data)) > self.bot.config["MAX_USER_FAVS"]:
                await inter.edit_original_message(f"Số lượng các mặt hàng trong tệp yêu thích của bạn vượt quá "
                                 f"Số lượng tối đa được phép ({self.bot.config['MAX_USER_FAVS']}).")
                return

            if (json_size + (user_favs := len(user_data["fav_links"]))) > self.bot.config["MAX_USER_FAVS"]:
                await inter.edit_original_message(
                    "Bạn không có đủ không gian để thêm tất cả các mục yêu thích từ tệp của mình...\n"
                    f"Giới hạn hiện tại: {self.bot.config['MAX_USER_FAVS']}\n"
                    f"Số lượng yêu thích đã lưu: {user_favs}\n"
                    f"Bạn cần phải: {(json_size + user_favs) - self.bot.config['MAX_USER_FAVS']}")
                return

        user_data["fav_links"].update(json_data)

        await self.bot.update_global_data(inter.author.id, user_data, db_name=DBModel.users)

        cmd = f"</play:" + str(self.bot.pool.controller_bot.get_global_command_named("play", cmd_type=disnake.ApplicationCommandType.chat_input).id) + ">"

        await inter.edit_original_message(
            embed=disnake.Embed(
                color=self.bot.get_color(),
                description="**Các liên kết đã được nhập thành công!**\n"
                            f"**Sử dụng lệnh {cmd} Để kiểm tra (trong tìm kiếm tự động tìm kiếm).**",
            )
        )

    async def export_(self, inter: disnake.MessageInteraction):

        retry_after = self.fav_import_export_cd.get_bucket(inter).update_rate_limit()
        if retry_after:
            if retry_after < 1:
                retry_after = 1
            await inter.send("**Bạn phải đợi {} để xuất.**".format(
                time_format(int(retry_after) * 1000, use_names=True)), ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)

        try:
            user_data = inter.global_user_data
        except AttributeError:
            user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
            inter.global_user_data = user_data

        cmd = f"</{self.fav_manager.name}:" + str(
            self.bot.pool.controller_bot.get_global_command_named(self.fav_manager.name,
                                                                  cmd_type=disnake.ApplicationCommandType.chat_input).id) + ">"

        if not user_data["fav_links"]:
            await inter.send(f"**Bạn không có liên kết yêu thích..\n"
                               f"Bạn có thể thêm bằng cách sử dụng lệnh: {cmd}**", ephemeral=True)
            return

        fp = BytesIO(bytes(json.dumps(user_data["fav_links"], indent=4), 'utf-8'))

        embed = disnake.Embed(
            description=f"Yêu thích của bạn ở đây.\nBạn có thể nhập bằng lệnh: {cmd}",
            color=self.bot.get_color())

        await inter.send(embed=embed, file=disnake.File(fp=fp, filename="favoritos.json"), ephemeral=True)


def setup(bot: BotCore):
    bot.add_cog(FavManager(bot))

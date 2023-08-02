# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import datetime
import json
import re
import traceback
from io import BytesIO
from typing import TYPE_CHECKING, Union, Optional

import disnake
from disnake.ext import commands

from utils.db import DBModel
from utils.music.converters import URL_REG, fix_characters, time_format
from utils.music.interactions import SelectInteraction
from utils.music.spotify import spotify_regex_w_user
from utils.others import CustomContext, music_source_emoji_id

youtube_regex = r"^(?:https?:\/\/)?(?:www\.)?youtube\.com\/(?:@)?([a-zA-Z0-9_-]{1,})(?:\/|$)"
soundcloud_regex = r"^(?:https?:\/\/)?(?:www\.)?soundcloud\.com\/([a-zA-Z0-9_-]+)"

if TYPE_CHECKING:
    from utils.client import BotCore


class IntegrationModal(disnake.ui.Modal):
    def __init__(self, bot: BotCore, name: Optional[str], url: Optional[str]):

        self.bot = bot
        self.name = name

        super().__init__(
            title="Adicionar integração",
            custom_id="user_integration_add",
            timeout=180,
            components=[
                disnake.ui.TextInput(
                    label="Link/Url:",
                    custom_id="user_integration_url",
                    min_length=10,
                    max_length=200,
                    value=url or None
                ),
            ]
        )

    async def callback(self, inter: disnake.ModalInteraction):

        url = inter.text_values["user_integration_url"].strip()

        try:
            url = URL_REG.findall(url)[0]
        except IndexError:
            await inter.send(
                embed=disnake.Embed(
                    description=f"**Không tìm thấy liên kết hợp lệ:** {url}",
                    color=disnake.Color.red()
                ), ephemeral=True
            )
            return

        if (matches := spotify_regex_w_user.match(url)):

            if not self.bot.spotify:
                await inter.send(
                    embed=disnake.Embed(
                        description="**Hỗ trợ Spotify hiện không có sẵn...**",
                        color=disnake.Color.red()
                    ), ephemeral=True
                )
                return

            url_type, user_id = matches.groups()

            if url_type != "user":
                await inter.send(
                    embed=disnake.Embed(
                        description=f"**Bạn phải sử dụng một liên kết từ hồ sơ người dùng Spotify.** {url}",
                        color=disnake.Color.red()
                    ), ephemeral=True
                )
                return

            try:
                await inter.response.defer(ephemeral=True)
            except:
                pass

            try:
                result = await self.bot.spotify.get_user(user_id)
            except Exception as e:
                await inter.send(
                    embed=disnake.Embed(
                        description="**Đã xảy ra lỗi khi lấy thông tin từ Spotify:** ```py\n"
                                    f"{repr(e)}```",
                        color=self.bot.get_color()
                    )
                )
                traceback.print_exc()
                return

            if not result:
                await inter.send(
                    embed=disnake.Embed(
                        description="**Người dùng liên kết thông tin không có danh sách phát công khai...**",
                        color=self.bot.get_color()
                    )
                )
                return

            data = {"title": f"[SP]: {result.name[:90]}", "url": url}

        else:

            if not self.bot.config["USE_YTDL"]:
                await inter.send(
                    embed=disnake.Embed(
                        description="**Không có hỗ trợ cho loại liên kết này tại thời điểm này...**",
                        color=self.bot.get_color()
                    )
                )
                return

            match = re.search(youtube_regex, url)

            if match:
                group = match.group(1)
                base_url = f"https://www.youtube.com/@{group}/playlists"
                source = "[YT]:"
            else:
                match = re.search(soundcloud_regex, url)

                if match:
                    group = match.group(1)
                    base_url = f"https://soundcloud.com/{group}/sets"
                else:
                    await inter.send(
                        embed=disnake.Embed(
                            description=f"**Liên kết thông báo không được hỗ trợ:** {url}",
                            color=disnake.Color.red()
                        ), ephemeral=True
                    )
                    return

                source = "[SC]:"

            loop = self.bot.loop or asyncio.get_event_loop()

            try:
                await inter.response.defer(ephemeral=True)
            except:
                pass

            info = await loop.run_in_executor(None, lambda: self.bot.pool.ytdl.extract_info(base_url, download=False))

            if not info:

                msg = f"**Người dùng/kênh của liên kết thông tin không tồn tại:**\n{url}"

                if source == "[YT]:":
                    msg += f"\n\n`Lưu ý: Kiểm tra xem liên kết có chứa người dùng với @, Ex: @ytchannel`"

                await inter.send(
                    embed=disnake.Embed(
                        description=msg,
                        color=disnake.Color.red()
                    ), ephemeral=True
                )
                return

            if not info['entries']:
                await inter.send(
                    embed=disnake.Embed(
                        description=f"**Người dùng/kênh liên kết thông tin không có danh sách phát công khai...**",
                        color=disnake.Color.red()
                    ), ephemeral=True
                )
                return

            if info['entries'][0].get('id'):
                data = {"title": info["entries"][0]['title'], "url": base_url}

            else:

                if len(info['entries']) > 1:

                    view = SelectInteraction(
                        user=inter.author,
                        opts=[
                            disnake.SelectOption(label=e['title'][:90], value=f"entrie_select_{c}") for c, e in enumerate(info['entries'])
                        ], timeout=30)

                    embed = disnake.Embed(
                        description="**Chọn một danh mục danh sách phát bên dưới:**\n"
                                    f'Chọn một tùy chọn theo <t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=30)).timestamp())}:R> para prosseguir.',
                        color=self.bot.get_color()
                    )

                    await inter.edit_original_message(embed=embed, view=view)

                    await view.wait()

                    inter = view.inter

                    try:
                        await inter.response.defer()
                    except:
                        pass

                    data = info["entries"][int(view.selected[14:])]

                else:
                    data = info["entries"][0]

            data["title"] = f'{source} {info["channel"]} - {data["title"]}' if info['extractor'].startswith("youtube") else f"{source} {info['title']}"

        user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        title = fix_characters(data['title'], 80)

        user_data["integration_links"][title] = data['url']

        await self.bot.update_global_data(inter.author.id, user_data, db_name=DBModel.users)

        try:
            me = (inter.guild or self.bot.get_guild(inter.guild_id)).me
        except AttributeError:
            me = None

        await inter.edit_original_message(
            embed=disnake.Embed(
                description=f"**Tích hợp thêm/chỉnh sửa thành công:** [`{title}`]({data['url']})\n"
                            "**Nó sẽ xuất hiện trong những dịp sau:** ```\n"
                            "- Khi sử dụng lệnh /play (trong tìm kiếm tự động tìm kiếm)\n"
                            "- Khi nhấp vào nút chơi yêu thích của người chơi.\n"
                            "- Sử dụng lệnh chơi (tiền tố) không có tên hoặc liên kết.```",
                color=self.bot.get_color(me)
            ), view=None
        )


class IntegrationsView(disnake.ui.View):

    def __init__(self, bot: BotCore, ctx: Union[disnake.AppCmdInter, CustomContext], data: dict):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        self.current = None
        self.data = data
        self.message = None

        if data["integration_links"]:

            integration_select = disnake.ui.Select(options=[
                disnake.SelectOption(label=k, emoji=music_source_emoji_id(k)) for k, v in data["integration_links"].items()
            ], min_values=1, max_values=1)
            integration_select.callback = self.select_callback
            self.add_item(integration_select)

        integrationadd_button = disnake.ui.Button(label="Thêm", emoji="💠")
        integrationadd_button.callback = self.integrationadd_callback
        self.add_item(integrationadd_button)

        if data["integration_links"]:

            remove_button = disnake.ui.Button(label="Loại bỏ", emoji="♻️")
            remove_button.callback = self.remove_callback
            self.add_item(remove_button)

            clear_button = disnake.ui.Button(label="Dọn dẹp", emoji="🚮")
            clear_button.callback = self.clear_callback
            self.add_item(clear_button)

            export_button = disnake.ui.Button(label="Xuất", emoji="📤")
            export_button.callback = self.export_callback
            self.add_item(export_button)

        import_button = disnake.ui.Button(label="Nhập", emoji="📥")
        import_button.callback = self.import_callback
        self.add_item(import_button)

        cancel_button = disnake.ui.Button(label="Hủy bỏ", emoji="❌")
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

        self.stop()

    async def integrationadd_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(IntegrationModal(bot=self.bot, name=None, url=None))
        await inter.delete_original_message()
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
            del user_data["integration_links"][self.current]
        except:
            await inter.send(f"**Không có sự tích hợp trong danh sách với tên:** {self.current}", ephemeral=True)
            return

        await self.bot.update_global_data(inter.author.id, user_data, db_name=DBModel.users)

        await inter.edit_original_message(
            embed=disnake.Embed(
                description="**Tích hợp đã loại bỏ thành công!**",
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

        if not user_data["integration_links"]:
            await inter.response.edit_message(content="**Bạn không có tích hợp được lưu!**", view=None)
            return

        user_data["integration_links"].clear()

        await self.bot.update_global_data(inter.author.id, user_data, db_name=DBModel.users)

        embed = disnake.Embed(
            description="Danh sách tích hợp của bạn đã được làm sạch thành công!",
            color=self.bot.get_color()
        )

        await inter.edit_original_message(embed=embed, components=None)
        self.stop()

    async def import_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(
            title="Nhập tích hợp",
            custom_id="integration_import",
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
        await self.bot.get_cog("IntegrationManager").export_(inter)
        self.stop()

    async def cancel_callback(self, inter: disnake.MessageInteraction):
        await inter.response.edit_message(
            embed=disnake.Embed(
                description="**Hoạt động với các tích hợp bị hủy...**",
                color=self.bot.get_color(),
            ), view=None
        )
        self.stop()

    async def select_callback(self, inter: disnake.MessageInteraction):
        self.current = inter.values[0]
        await inter.response.defer()


class IntegrationManager(commands.Cog):

    def __init__(self, bot: BotCore):
        self.bot = bot

    desc_prefix = "💠 [Tích hợp] 💠 | "

    itg_cd = commands.CooldownMapping.from_cooldown(3, 15, commands.BucketType.member)

    async def integration(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @commands.command(name="integrations", aliases=["integrationmanager", "itg", "itgmgr", "itglist", "integrationlist"],
                      description="Quản lý tích hợp của bạn. ", cooldown=itg_cd)
    async def integratios_legacy(self, ctx: CustomContext):
        await self.integrations.callback(self=self, inter=ctx)

    @commands.max_concurrency(1, commands.BucketType.member, wait=False)
    @commands.slash_command(description=f"{desc_prefix}Quản lý tích hợp kênh/hồ sơ của bạn với danh sách phát công khai.", cooldown=itg_cd)
    async def integrations(self, inter: disnake.AppCmdInter):

        await inter.response.defer(ephemeral=True)

        try:
            user_data = inter.global_user_data
        except AttributeError:
            user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
            inter.global_user_data = user_data

        supported_platforms = []

        if self.bot.config["USE_YTDL"]:
            supported_platforms.extend(["[31;1mYoutube[0m", "[33;1mSoundcloud[0m"])

        if self.bot.spotify:
            supported_platforms.append("[32;1mSpotify[0m")

        if not supported_platforms:
            await inter.send("**Không có hỗ trợ cho tính năng này vào lúc này...**\n\n"
                               "`Hỗ trợ Spotify và YTDL không được kích hoạt.`", ephemeral=True)

        view = IntegrationsView(bot=self.bot, ctx=inter, data=user_data)

        embed = disnake.Embed(
            title="Trình quản lý tích hợp kênh/hồ sơ với danh sách phát công khai.",
            colour=self.bot.get_color(),
        )

        if user_data["integration_links"]:

            embed.description = f"**Tích hợp hiện tại của nó:**\n\n" + "\n".join(f"> ` {n+1} ` [`{f[0]}`]({f[1]})" for n, f in enumerate(user_data["integration_links"].items()))

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
                                      "* Bằng cách nhấp vào nút chạm yêu thích của người chơi.\n"
                                      f"* Sử dụng lệnh {global_data['prefix'] or self.bot.default_prefix}{cog.play_legacy.name} mà không cần sử dụng tên hoặc liên kết.")

        embed.add_field(
            name="Liên kết hồ sơ/kênh được hỗ trợ:", inline=False,
            value=f"```ansi\n{', '.join(supported_platforms)}```"
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

    integration_import_export_cd = commands.CooldownMapping.from_cooldown(1, 15, commands.BucketType.member)

    @commands.Cog.listener("on_modal_submit")
    async def modal_import(self, inter: disnake.ModalInteraction):

        if inter.custom_id != "integration_import":
            return

        try:
            json_data = json.loads(inter.text_values["json_data"])
        except Exception as e:
            await inter.send("**Đã xảy ra lỗi khi phân tích dữ liệu hoặc dữ liệu không hợp lệ/không định dạng được gửi "
                               f"ở định dạng JSON.**\n\n`{repr(e)}`", ephemeral=True)

        retry_after = self.integration_import_export_cd.get_bucket(inter).update_rate_limit()
        if retry_after:
            if retry_after < 1:
                retry_after = 1
            await inter.send("**Bạn phải đợi {} Nhập khẩu.**".format(
                time_format(int(retry_after) * 1000, use_names=True)), ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)

        for name, url in json_data.items():

            if "> itg:" in name.lower():
                continue

            if len(url) > (max_url_chars := 150):
                await inter.edit_original_message(
                    f"**Một mục từ tệp của bạn {url} vượt quá số lượng ký tự được phép:{max_url_chars}**")
                return

            if not isinstance(url, str) or not URL_REG.match(url):
                await inter.edit_original_message(f"Tệp của bạn chứa liên kết không hợp lệ: ```ldif\n{url}```")
                return

        user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        for name in json_data.keys():
            try:
                del user_data["integration_links"][name.lower()[:90]]
            except KeyError:
                continue

        if self.bot.config["MAX_USER_INTEGRATIONS"] > 0 and not (await self.bot.is_owner(inter.author)):

            if (json_size := len(json_data)) > self.bot.config["MAX_USER_INTEGRATIONS"]:
                await inter.edit_original_message(f"Số lượng mục trong tệp tích hợp của bạn vượt quá "
                                   f"Số lượng tối đa được phép ({self.bot.config['MAX_USER_INTEGRATIONS']}).")
                return

            if (json_size + (user_integrations := len(user_data["integration_links"]))) > self.bot.config[
                "MAX_USER_INTEGRATIONS"]:
                await inter.edit_original_message(
                    "Bạn không có đủ không gian để thêm tất cả các tích hợp của tệp của mình...\n"
                    f"Giới hạn hiện tại: {self.bot.config['MAX_USER_INTEGRATIONS']}\n"
                    f"Số lượng tích hợp được lưu: {user_integrations}\n"
                    f"Bạn cần phải: {(json_size + user_integrations) - self.bot.config['MAX_USER_INTEGRATIONS']}")
                return

        user_data["integration_links"].update(json_data)

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

        retry_after = self.integration_import_export_cd.get_bucket(inter).update_rate_limit()
        if retry_after:
            if retry_after < 1:
                retry_after = 1
            await inter.send("**Bạn phải đợi {} xuất .**".format(
                time_format(int(retry_after) * 1000, use_names=True)), ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)

        try:
            user_data = inter.global_user_data
        except AttributeError:
            user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
            inter.global_user_data = user_data

        cmd = f"</{self.integrations.name}:" + str(
            self.bot.pool.controller_bot.get_global_command_named(self.integrations.name,
                                                                  cmd_type=disnake.ApplicationCommandType.chat_input).id) + ">"

        if not user_data["integration_links"]:
            await inter.edit_original_message(f"**Bạn không có thêm tích hợp...\n"
                               f"Bạn có thể thêm bằng cách sử dụng lệnh: {cmd}**")
            return

        fp = BytesIO(bytes(json.dumps(user_data["integration_links"], indent=4), 'utf-8'))

        embed = disnake.Embed(
            description=f"Tích hợp của bạn ở đây.\nBạn có thể nhập bằng lệnh: {cmd}",
            color=self.bot.get_color())

        await inter.send(embed=embed, file=disnake.File(fp=fp, filename="integrations.json"), ephemeral=True)


def setup(bot: BotCore):

    if bot.config["USE_YTDL"] and not hasattr(bot.pool, 'ytdl'):

        from yt_dlp import YoutubeDL

        bot.pool.ytdl = YoutubeDL(
            {
                'extract_flat': True,
                'quiet': True,
                'no_warnings': True,
                'lazy_playlist': True,
                'simulate': True,
                'cachedir': False,
                'allowed_extractors': [
                    r'.*youtube.*',
                    r'.*soundcloud.*',
                ]
            }
        )

    bot.add_cog(IntegrationManager(bot))

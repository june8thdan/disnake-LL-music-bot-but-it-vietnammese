# -*- coding: utf-8 -*-
import asyncio
import gc
import os
import re
import shutil
import json
import traceback
from zipfile import ZipFile

from typing import Union, Optional
import disnake
import dotenv
import psutil
import wavelink
from disnake.ext import commands
from aiohttp import ClientSession

from utils.client import BotCore
from utils.db import DBModel
from utils.music.checks import check_voice, check_requester_channel
from utils.music.models import LavalinkPlayer
from utils.others import sync_message, CustomContext, string_to_file, token_regex, CommandArgparse
from utils.owner_panel import panel_command, PanelView
from utils.music.errors import GenericError
from config_loader import DEFAULT_CONFIG, load_config


def format_git_log(data_list: list):

    data = []

    for d in data_list:
        if not d:
            continue
        t = d.split("*****")
        data.append({"commit": t[0], "abbreviated_commit": t[1], "subject": t[2], "timestamp": t[3]})

    return data


async def run_command(cmd: str):

    p = await asyncio.create_subprocess_shell(
        cmd, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, stderr = await p.communicate()
    r = ShellResult(p.returncode, stdout, stderr)
    if r.status != 0:
        raise GenericError(f"{r.stderr or r.stdout}\n\nStatus Code: {r.status}")
    return str(r.stdout)


class ShellResult:

    def __init__(self, status: int, stdout: Optional[bytes], stderr: Optional[bytes]):
        self.status = status
        self.stdout = stdout.decode(encoding="utf-8", errors="replace") if stdout is not None else None
        self.stderr = stderr.decode(encoding="utf-8", errors="replace") if stderr is not None else None


class Owner(commands.Cog):

    os_quote = "\"" if os.name == "nt" else "'"
    git_format = f"--pretty=format:{os_quote}%H*****%h*****%s*****%ct{os_quote}"

    extra_files = [
        "./playlist_cache.json",
    ]

    additional_files = [
        "./lavalink.ini",
        "./application.yml",
        "./squarecloud.config",
        "./squarecloud.app",
        "./discloud.config",
    ]

    extra_dirs = [
        "local_database",
        ".player_sessions"
    ]

    def __init__(self, bot: BotCore):
        self.bot = bot
        self.git_init_cmds = [
            "git init",
            f'git remote add origin {self.bot.config["SOURCE_REPO"]}',
            'git fetch origin',
            'git checkout -b main -f --track origin/main'
        ]
        self.owner_view: Optional[PanelView] = None
        self.extra_hints = bot.config["EXTRA_HINTS"].split("||")

    def format_log(self, data: list):
        return "\n".join(f"[`{c['abbreviated_commit']}`]({self.bot.pool.remote_git_url}/commit/{c['commit']}) `- "
                         f"{(c['subject'][:40].replace('`', '') + '...') if len(c['subject']) > 39 else c['subject']}` "
                         f"(<t:{c['timestamp']}:R>)" for c in data)

    @commands.cooldown(1, 10, commands.BucketType.user)
    @commands.is_owner()
    @commands.command(
        hidden=True, aliases=["gls", "lavalink", "lllist", "lavalinkservers"],
        description="Tải xuống một tệp với danh sách máy chủ Lavalink để sử dụng chúng trong hệ thống âm nhạc."
    )
    async def getlavaservers(self, ctx: CustomContext):

        await ctx.defer()

        await self.download_lavalink_serverlist()

        await ctx.send(
            embed=disnake.Embed(
                description="**Tệp Lavalink.ini đã được tải xuống thành công!\n"
                            "Bạn sẽ cần khởi động lại để sử dụng các máy chủ của tệp này.**"
            )
        )

    updatelavalink_flags = CommandArgparse()
    updatelavalink_flags.add_argument('-force', '--force', action='store_true',
                                      help="Bỏ qua việc thực thi/sử dụng máy chủ cục bộ.")
    updatelavalink_flags.add_argument('-yml', '--yml', action='store_true',
                                      help="Tải tập tin application.yml.")
    updatelavalink_flags.add_argument("-resetids", "-reset", "--resetids", "--reset",
                                      help="Đặt lại thông tin ID âm nhạc (hữu ích để tránh các vấn đề với một số "
                                           "Lavaplayer/Lavalink thay đổi).")

    @commands.is_owner()
    @commands.max_concurrency(1, commands.BucketType.user)
    @commands.command(hidden=True, aliases=["ull", "updatell", "llupdate", "llu"], extras={"flags": updatelavalink_flags})
    async def updatelavalink(self, ctx: CustomContext, flags: str = ""):

        args, unknown = ctx.command.extras['flags'].parse_known_args(flags.split())

        node: Optional[wavelink.Node] = None

        for bot in self.bot.pool.bots:
            try:
                node = bot.music.nodes["LOCAL"]
                break
            except KeyError:
                continue

        if not node and not args.force:
            raise GenericError("**Máy chủ cục bộ không được sử dụng!**")

        download_urls = [self.bot.config["LAVALINK_FILE_URL"]]

        if args.yml:
            download_urls.append("https://github.com/zRitsu/LL-binaries/releases/download/0.0.1/application.yml")

        async with ctx.typing():

            for url in download_urls:
                async with ClientSession() as session:
                    async with session.get(url) as r:
                        lavalink_jar = await r.read()
                        with open(url.split("/")[-1], "wb") as f:
                            f.write(lavalink_jar)

        if node:

            for bot in self.bot.pool.bots:

                try:
                    node = bot.music.nodes["LOCAL"]
                except KeyError:
                    continue

                node.restarting = True

                for player in node.players.values():

                    txt = "Máy chủ âm nhạc đã được khởi động lại và âm nhạc sẽ tiếp tục trong vài giây (vui lòng chờ đợi)..."

                    if args.resetids:

                        if player.current:
                            player.queue.appendleft(player.current)
                            player.current = None

                        for t in player.queue:
                            t.id = ""

                        for t in player.played:
                            t.id = ""

                    if player.static or player.controller_mode:
                        player.set_command_log(text=txt, emoji="🛠️")
                        bot.loop.create_task(player.invoke_np(force=True))
                    else:
                        bot.loop.create_task(
                            player.text_channel.send(
                                embed=disnake.Embed(
                                    color=self.bot.get_color(player.guild.me),
                                    description=f"🛠️ **⠂{txt}**"
                                )
                            )
                        )

        self.bot.pool.start_lavalink()

        await ctx.send(
            embed=disnake.Embed(
                description="**Tệp Lavalink.jar đã được cập nhật thành công!**",
                color=self.bot.get_color(ctx.guild.me)
            )
        )

    @commands.is_owner()
    @panel_command(aliases=["rd", "recarregar"], description="Tải lại các module.", emoji="🔄",
                   alt_name="Tải lại thư mục module.")
    async def reload(self, ctx: Union[CustomContext, disnake.MessageInteraction]):

        data = self.bot.load_modules()

        await self.bot.sync_app_commands()

        for bot in self.bot.pool.bots:

            if bot.user.id != self.bot.user.id:
                bot.load_modules()
                await bot.sync_app_commands()

        self.bot.sync_command_cooldowns()

        txt = ""

        if data["loaded"]:
            txt += f'**Tải lên module** ```ansi\n[0;34m{" [0;37m| [0;34m".join(data["loaded"])}```\n'

        if data["reloaded"]:
            txt += f'**Tải lại các module:** ```ansi\n[0;32m{" [0;37m| [0;32m".join(data["reloaded"])}```\n'

        if not txt:
            txt = "**Không tìm thấy module...**"

        self.bot.pool.config = load_config()

        gc.collect()

        if isinstance(ctx, CustomContext):
            embed = disnake.Embed(colour=self.bot.get_color(ctx.me), description=txt)
            await ctx.send(embed=embed, view=self.owner_view)
        else:
            return txt

    update_flags = CommandArgparse()
    update_flags.add_argument("-force", "--force", action="store_true",
                              help="Buộc cập nhật bỏ qua trạng thái của kho lưu trữ cục bộ).")
    update_flags.add_argument("-pip", "--pip", action="store_true",
                              help="Cài đặt/Cập nhật phụ thuộc sau khi cập nhật.")

    @commands.is_owner()
    @commands.max_concurrency(1, commands.BucketType.default)
    @panel_command(aliases=["up", "atualizar"], description="Cập nhật mã của tôi bằng Git.",
                   emoji="<:git:944873798166020116>", alt_name="Cập nhật bot", extras={"flags": update_flags})
    async def update(self, ctx: Union[CustomContext, disnake.MessageInteraction], *,
                     opts: str = ""):  # TODO: Rever se há alguma forma de usar commands.Flag sem um argumento obrigatório, ex: --pip.

        out_git = ""

        git_log = []

        if shutil.which("poetry"):
            file = "./pyproject.toml"
            use_poetry = True
        else:
            file = "./requirements.txt"
            use_poetry = False

        requirements_old = ""
        try:
            with open(file) as f:
                requirements_old = f.read()
        except:
            pass

        args, unknown = self.bot.get_command("update").extras['flags'].parse_known_args(opts.split())

        if not os.path.isdir("./.git") or args.force:

            out_git += await self.cleanup_git(force=args.force)

        else:

            try:
                await ctx.response.defer()
            except:
                pass

            try:
                await run_command("git reset --hard")
            except:
                pass

            try:
                pull_log = await run_command("git pull --allow-unrelated-histories -X theirs")
                if "Already up to date" in pull_log:
                    raise GenericError("**Tôi đã cài đặt các bản cập nhật cuối cùng...**")
                out_git += pull_log

            except GenericError as e:
                raise e

            except Exception as e:

                if "Already up to date" in str(e):
                    raise GenericError("Tôi đã cài đặt các bản cập nhật cuối cùng...")

                elif not "Fast-forward" in str(e):
                    out_git += await self.cleanup_git(force=True)

            commit = ""

            for l in out_git.split("\n"):
                if l.startswith("Updating"):
                    commit = l.replace("Updating ", "").replace("..", "...")
                    break

            data = (await run_command(f"git log {commit} {self.git_format}")).split("\n")

            git_log += format_git_log(data)

        text = "`Bạn sẽ cần phải khởi động lại sau khi thay đổi.`"

        txt = f"`✅` **[Cập nhật thành công!]({self.bot.pool.remote_git_url}/commits/main)**"

        if git_log:
            txt += f"\n\n{self.format_log(git_log[:10])}"

        txt += f"\n\n`📄` **Log:** ```py\n{out_git[:1000].split('Fast-forward')[-1]}```\n{text}"

        if isinstance(ctx, CustomContext):
            embed = disnake.Embed(
                description=txt,
                color=self.bot.get_color(ctx.guild.me)
            )
            await ctx.send(embed=embed, view=self.owner_view)

            self.bot.loop.create_task(self.update_deps(ctx, requirements_old, args, use_poetry=use_poetry))

        else:
            self.bot.loop.create_task(self.update_deps(ctx, requirements_old, args, use_poetry=use_poetry))
            return txt

    async def update_deps(self, ctx, original_reqs, args, use_poetry=False):

        if use_poetry:
            cmd = "poetry install"
            file = "./pyproject.toml"
        else:
            cmd = "pip3 install -U -r requirements.txt --no-cache-dir"
            file = "./requirements.txt"

        if args.pip:

            embed = disnake.Embed(
                description="**Cài đặt các cơ sở.\nVui lòng chờ...**",
                color=self.bot.get_color(ctx.guild.me)
            )

            msg = await ctx.channel.send(embed=embed)

            await run_command(cmd)

            embed.description = "**Các cơ sở đã được cài đặt thành công!**"

            await msg.edit(embed=embed)

        else:

            with open(file) as f:
                requirements_new = f.read()

            if original_reqs != requirements_new:

                txt = ""

                if venv:=os.getenv("VIRTUAL_ENV"):
                    if os.name == "nt":
                        txt += "call " + venv.split('\\')[-1] + " && "
                    else:
                        txt += ". ./" + venv.split('/')[-1] + " && "

                try:
                    prefix = ctx.prefix if (not str(ctx.guild.me.id) in ctx.prefix) else f"@{ctx.guild.me.name}"
                except AttributeError:
                    prefix = self.bot.default_prefix if self.bot.intents.message_content else f"@{ctx.guild.me.name}"

                await ctx.send(
                    embed=disnake.Embed(
                        description="**Nó sẽ là cần thiết để cập nhật các phụ thuộc bằng cách sử dụng lệnh "
                                    "Dưới đây trên terminal/shell:**\n"
                                    f"```sh\n{txt}{cmd}```\nhoặc sử dụng lệnh: "
                                    f"```ansi\n[34;1m{prefix}update --force --pip[0m``` \n"
                                    f"**Lưu ý: ** Tùy thuộc vào lưu trữ (hoặc không 150MB RAM miễn phí "
                                    f"e 0.5vCPU) vBạn phải gửi tệp yêu cầu.txt thay vì "
                                    f"Sử dụng một trong các tùy chọn trên hoặc các nút cài đặt bên dưới...",
                        color=self.bot.get_color(ctx.guild.me)
                    ),
                    components=[
                        disnake.ui.Button(label="Download requirements.txt", custom_id="updatecmd_requirements"),
                        disnake.ui.Button(label="Cập nhật phụ thuộc",
                                          custom_id="updatecmd_installdeps_" + ("poetry" if use_poetry else "pip")),
                        disnake.ui.Button(label="Cập nhật phụ thuộc (lực lượng)",
                                          custom_id="updatecmd_installdeps_force_" + ("poetry" if use_poetry else "pip")),
                    ]
                )

    @commands.Cog.listener("on_button_click")
    async def update_buttons(self, inter: disnake.MessageInteraction):

        if not inter.data.custom_id.startswith("updatecmd_"):
            return

        if inter.data.custom_id.startswith("updatecmd_requirements"):

            try:
                os.remove('./update_reqs.zip')
            except FileNotFoundError:
                pass

            with ZipFile('update_reqs.zip', 'w') as zipObj:
                zipObj.write("requirements.txt")

            await inter.send(
                embed=disnake.Embed(
                    description="**Tải xuống tệp đính kèm và gửi nó đến lưu trữ của bạn thông qua cam kết, v.v.**",
                    color=self.bot.get_color(inter.guild.me)
                ),
                file=disnake.File("update_reqs.zip")
            )

            os.remove("update_reqs.zip")
            return

        # install installdeps

        if inter.data.custom_id.startswith("updatecmd_installdeps_force_"):
            await self.cleanup_git(force=True)

        await inter.message.delete()
        await self.update_deps(inter, "", "--pip", use_poetry=inter.data.custom_id.endswith("_poetry"))

    async def cleanup_git(self, force=False):

        if force:
            try:
                shutil.rmtree("./.git")
            except FileNotFoundError:
                pass

        out_git = ""

        for c in self.git_init_cmds:
            try:
                out_git += (await run_command(c)) + "\n"
            except Exception as e:
                out_git += f"{e}\n"

        self.bot.pool.commit = (await run_command("git rev-parse HEAD")).strip("\n")
        self.bot.pool.remote_git_url = self.bot.config["SOURCE_REPO"][:-4]

        return out_git

    @commands.max_concurrency(1, commands.BucketType.guild)
    @commands.cooldown(1, 10, commands.BucketType.user)
    @panel_command(aliases=["latest", "lastupdate"], description="Xem các bản cập nhật mới nhất của tôi.", emoji="📈",
                   alt_name="Cập nhật cuối cùng", hidden=False)
    async def updatelog(self, ctx: Union[CustomContext, disnake.MessageInteraction], amount: int = 10):

        if not os.path.isdir("./.git"):
            raise GenericError("Không có sự thay thế bắt đầu trong thư mục bot...\nLưu ý: Sử dụng lệnh cập nhật.")

        if not self.bot.pool.remote_git_url:
            self.bot.pool.remote_git_url = self.bot.config["SOURCE_REPO"][:-4]

        git_log = []

        data = (await run_command(f"git log -{amount or 10} {self.git_format}")).split("\n")

        git_log += format_git_log(data)

        txt = f"🔰 ** | [Cập nhật gần đây:]({self.bot.pool.remote_git_url}/commits/main)**\n\n" + self.format_log(
            git_log)

        if isinstance(ctx, CustomContext):

            embed = disnake.Embed(
                description=txt,
                color=self.bot.get_color(ctx.guild.me)
            )

            await ctx.send(embed=embed, view=self.owner_view if (await self.bot.is_owner(ctx.author)) else None)

        else:
            return txt

    @commands.is_owner()
    @commands.command(hidden=True, aliases=["menu"])
    async def panel(self, ctx: CustomContext):

        embed =disnake.Embed(
            title="BẢNG ĐIỀU KHIỂN.",
            color=self.bot.get_color(ctx.guild.me)
        )
        embed.set_footer(text="Nhấp vào một nhiệm vụ bạn muốn thực hiện.")
        await ctx.send(embed=embed, view=PanelView(self.bot))

    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(description="Đồng bộ hóa/đăng ký lệnh thanh trên máy chủ.", hidden=True)
    async def syncguild(self, ctx: Union[CustomContext, disnake.MessageInteraction]):

        embed = disnake.Embed(
            color=self.bot.get_color(ctx.guild.me),
            description="**Lệnh này không còn cần thiết để được sử dụng (việc đồng bộ hóa các lệnh bây giờ "
                        f"Nó là tự động).**\n\n{sync_message(self.bot)}"
        )

        await ctx.send(embed=embed)

    @commands.is_owner()
    @panel_command(aliases=["sync"], description="Đồng bộ hóa các lệnh thanh theo cách thủ công. ",
                   emoji="<:slash:944875586839527444>",
                   alt_name="Đồng bộ hóa các lệnh bằng tay.")
    async def synccmds(self, ctx: Union[CustomContext, disnake.MessageInteraction]):

        if self.bot.config["AUTO_SYNC_COMMANDS"] is True:
            raise GenericError(
                f"**Điều này không thể được sử dụng với đồng bộ hóa tự động được kích hoạt...**\n\n{sync_message(self.bot)}")

        await self.bot._sync_application_commands()

        txt = f"**Các lệnh thanh đã được đồng bộ hóa thành công!**\n\n{sync_message(self.bot)}"

        if isinstance(ctx, CustomContext):

            embed = disnake.Embed(
                color=self.bot.get_color(ctx.guild.me),
                description=txt
            )

            await ctx.send(embed=embed, view=self.owner_view)

        else:
            return txt

    @commands.has_guild_permissions(manage_guild=True)
    @commands.cooldown(1, 10, commands.BucketType.guild)
    @commands.command(
        aliases=["mudarprefixo", "prefix", "changeprefix"],
        description="Thay đổi tiền tố máy chủ",
        usage="{prefix}{cmd} [prefixo]\nEx: {prefix}{cmd} >>"
    )
    async def setprefix(self, ctx: CustomContext, prefix: str):

        if " " in prefix or len(prefix) > 5:
            raise GenericError("**Tiền tố không thể chứa khoảng trắng hoặc có trên 5 ký tự.**")

        try:
            guild_data = ctx.global_guild_data
        except AttributeError:
            guild_data = await self.bot.get_global_data(ctx.guild.id, db_name=DBModel.guilds)
            ctx.global_guild_data = guild_data

        guild_data["prefix"] = prefix
        await self.bot.update_global_data(ctx.guild.id, guild_data, db_name=DBModel.guilds)

        prefix = disnake.utils.escape_markdown(prefix)

        embed = disnake.Embed(
            description=f"**Tiền tố của máy chủ này bây giờ là:** `{prefix}`\n"
                        f"**Nếu bạn muốn khôi phục tiền tố mặc định, hãy sử dụng lệnh:** `{prefix}{self.resetprefix.name}`",
            color=self.bot.get_color(ctx.guild.me)
        )

        await ctx.send(embed=embed)

    @commands.has_guild_permissions(manage_guild=True)
    @commands.cooldown(1, 10, commands.BucketType.guild)
    @commands.command(
        description="Đặt lại tiền tố máy chủ (sử dụng tiền tố bot mặc định)"
    )
    async def resetprefix(self, ctx: CustomContext):

        try:
            guild_data = ctx.global_guild_data
        except AttributeError:
            guild_data = await self.bot.get_global_data(ctx.guild.id, db_name=DBModel.guilds)
            ctx.global_guild_data = guild_data

        if not guild_data["prefix"]:
            raise GenericError("**Không có tiền tố được định cấu hình trên máy chủ.**")

        guild_data["prefix"] = ""

        await self.bot.update_global_data(ctx.guild.id, guild_data, db_name=DBModel.guilds)

        embed = disnake.Embed(
            description=f"**Tiền tố máy chủ đã được đặt lại thành công.\n"
                        f"Tiền tố tiêu chuẩn bây giờ là:** `{disnake.utils.escape_markdown(self.bot.default_prefix)}`",
            color=self.bot.get_color(ctx.guild.me)
        )

        await ctx.send(embed=embed)

    @commands.cooldown(1, 10, commands.BucketType.guild)
    @commands.command(
        aliases=["uprefix", "spu", "setmyprefix", "spm", "setcustomprefix", "scp", "customprefix", "myprefix"],
        description="Thay đổi tiền tố người dùng của bạn (tiền tố mà tôi sẽ trả lời bạn độc lập "
                    "với tiền tố được định cấu hình trên máy chủ).",
        usage="{prefix}{cmd} [prefixo]\nEx: {prefix}{cmd} >>"
    )
    async def setuserprefix(self, ctx: CustomContext, prefix: str):

        if " " in prefix or len(prefix) > 5:
            raise GenericError("**Tiền tố không thể chứa khoảng trắng hoặc có trên 5 ký tự.**")

        try:
            user_data = ctx.global_user_data
        except AttributeError:
            user_data = await self.bot.get_global_data(ctx.author.id, db_name=DBModel.users)
            ctx.global_user_data = user_data

        user_data["custom_prefix"] = prefix
        self.bot.pool.user_prefix_cache[ctx.author.id] = prefix
        await self.bot.update_global_data(ctx.author.id, user_data, db_name=DBModel.users)

        prefix = disnake.utils.escape_markdown(prefix)

        embed = disnake.Embed(
            description=f"**Tiền tố người dùng của bạn bây giờ là:** `{prefix}`\n"
                        f"**Nếu bạn muốn xóa tiền tố người dùng của mình, hãy sử dụng lệnh:** `{prefix}{self.resetuserprefix.name}`",
            color=self.bot.get_color(ctx.guild.me)
        )

        await ctx.send(embed=embed)

    @commands.cooldown(1, 10, commands.BucketType.guild)
    @commands.command(description="Xóa tiền tố người dùng của bạn")
    async def resetuserprefix(self, ctx: CustomContext):

        try:
            user_data = ctx.global_user_data
        except AttributeError:
            user_data = await self.bot.get_global_data(ctx.author.id, db_name=DBModel.users)
            ctx.global_user_data = user_data

        if not user_data["custom_prefix"]:
            raise GenericError("**Bạn không có một cấu hình tiền tố. ** ")
        user_data["custom_prefix"] = ""
        self.bot.pool.user_prefix_cache[ctx.author.id] = ""
        await self.bot.update_global_data(ctx.author.id, user_data, db_name=DBModel.users)

        embed = disnake.Embed(
            description=f"**Tiền tố người dùng của bạn đã bị xóa thành công.**",
            color=self.bot.get_color(ctx.guild.me)
        )

        await ctx.send(embed=embed)

    @commands.is_owner()
    @commands.command(
        aliases=["guildprefix", "sgp", "gp"], hidden=True,
        description="Đặt tiền tố theo cách thủ công cho máy chủ với ID thông tin (hữu ích cho danh sách thực vật)",
        usage="{prefix}{cmd} [server id] <prefixo>\nEx: {prefix}{cmd} 1155223334455667788 >>\nLưu ý: Sử dụng lệnh mà không cần chỉ định tiền tố để xóa nó."
    )
    async def setguildprefix(self, ctx: CustomContext, server_id: int, prefix: str = None):

        if not 17 < len(str(server_id)) < 24:
            raise GenericError("**Lượng ký tự ID máy chủ phải nằm trong khoảng từ 18 đến 23.**")

        guild_data = await self.bot.get_global_data(server_id, db_name=DBModel.guilds)

        embed = disnake.Embed(color=self.bot.get_color(ctx.guild.me))

        if not prefix:
            guild_data["prefix"] = ""
            await ctx.bot.update_global_data(server_id, guild_data, db_name=DBModel.guilds)
            embed.description = "**Tiền tố sớm của máy chủ với ID được thông báo đã được thiết lập lại thành công.**"

        else:
            guild_data["prefix"] = prefix
            await self.bot.update_global_data(server_id, guild_data, db_name=DBModel.guilds)
            embed.description = f"**Tiền tố cho máy chủ có ID được thông báo bây giờ là:** {disnake.utils.escape_markdown(prefix)}"

        await ctx.send(embed=embed)

    @commands.is_owner()
    @panel_command(aliases=["expsource", "export", "exs"],
                   description="Xuất nguồn của tôi sang tệp zip.", emoji="💾",
                   alt_name="Xuất mã nguồn/nguồn.")
    async def exportsource(self, ctx:Union[CustomContext, disnake.MessageInteraction], *, flags: str = ""):

        if not os.path.isdir("./.git"):
            await self.cleanup_git(force=True)

        try:
            env_file = dotenv.dotenv_values("./.env")
        except:
            env_file = {}

        try:
            with open("config.json") as f:
                config_json = json.load(f)
        except FileNotFoundError:
            config_json = {}

        SECRETS = dict(DEFAULT_CONFIG)
        SECRETS.update({"TOKEN": ""})

        for env, value in os.environ.items():
            if (e:=env.lower()).startswith(("token_bot_", "test_guilds_", "lavalink_node_")) or e == "token":
                SECRETS[env] = os.environ[env]
                continue

            if not isinstance(value, str):
                continue

            tokens = []

            for string in value.split():
                if re.findall(token_regex, value) and len(string) < 91:
                    tokens.append(string)

            if tokens:
                SECRETS[env] = value

        for i in SECRETS:
            try:
                SECRETS[i] = os.environ[i]
            except KeyError:
                continue

        SECRETS.update(config_json)
        SECRETS.update(env_file)

        if any(f in flags.lower() for f in ("-autodll", "--autodll")):
            SECRETS["AUTO_DOWNLOAD_LAVALINK_SERVERLIST"] = True

        if any(f in flags.lower() for f in ("--externalservers", "-externalservers", "--llservers", "-llservers", "--lls", "-lls")):
            await self.download_lavalink_serverlist()

        if not os.path.isfile("./.env-temp"):
            shutil.copyfile("./.example.env", "./.env-temp")

        for i in SECRETS:
            if not isinstance(SECRETS[i], str):
                SECRETS[i] = str(SECRETS[i]).lower()
            dotenv.set_key("./.env-temp", i, SECRETS[i])

        filelist = await run_command("git ls-files --others --exclude-standard --cached")

        if any(f in flags.lower() for f in ("--extradirs", "-extradirs", "--ed", "-ed", "--extrafiles", "-extrafiles", "--ef", "-ef")):
            for extra_dir in self.extra_dirs:
                for dir_path, dir_names, filenames in os.walk(extra_dir):
                    filelist += "\n" + "\n".join(os.path.join(dir_path, file) for file in filenames)

            for file in self.extra_files:
                if os.path.isfile(file):
                    filelist += "\n" + file

        for file in self.additional_files:
            if os.path.isfile(file):
                filelist += "\n" + file

        await self.bot.loop.run_in_executor(None, self.zip_dir, filelist.split("\n"))

        os.remove("./.env-temp")

        try:
            embed = disnake.Embed(
                description="**Không gửi tệp Source.zip hoặc tệp .ENV cho bất kỳ ai và rất cẩn thận khi đăng "
                            "các nội dung trong tệp .env và không thêm tệp này ở những nơi công cộng như "
                            "github, repl.it, glitch.com,..v.v.**",
                color=self.bot.get_color(ctx.guild.me))
            embed.set_footer(text="Để an toàn, thông báo này sẽ bị xóa trong 2 phút.")

            msg = await ctx.author.send(
                embed=embed,
                file=disnake.File("./source.zip", filename=f"{self.bot.user}_source.zip"),
                delete_after=120
            )

            os.remove("./source.zip")

        except disnake.Forbidden:
            os.remove("./source.zip")
            raise GenericError("DM của bạn bị vô hiệu hóa!")

        if isinstance(ctx, CustomContext):
            await ctx.send(
                embed=disnake.Embed(
                    description=f"**Tệp [Source.zip]({msg.jump_url}) Nó đã được gửi trong riêng tư của bạn.**",
                    color=self.bot.get_color(ctx.guild.me)
                )
            )
        else:
            return f"Tệp [Source.zip]({msg.jump_url}) đã được gửi thành công trong DM của bạn."

    def zip_dir(self, filelist: list):

        try:
            os.remove("./source.zip")
        except:
            pass

        with ZipFile("./source.zip", 'a') as zipf:

            for f in filelist:
                if not f:
                    continue
                try:
                    if f == ".env-temp":
                        zipf.write('./.env-temp', './.env')
                    else:
                        zipf.write(f"./{f}")
                except FileNotFoundError:
                    continue

    @commands.is_owner()
    @commands.command(hidden=True)
    async def cleardm(self, ctx: CustomContext, amount: int = 20):

        counter = 0

        async with ctx.typing():

            async for msg in ctx.author.history(limit=int(amount)):
                if msg.author.id == self.bot.user.id:
                    await msg.delete()
                    await asyncio.sleep(0.5)
                    counter += 1

        if not counter:
            raise GenericError(f"**Không có tin nhắn nào bị xóa khỏi {amount} Được xác minh (các)...**")

        if counter == 1:
            txt = "**Một tin nhắn đã bị xóa khỏi DM của bạn.**"
        else:
            txt = f"**{counter} Tin nhắn đã bị xóa khỏi DM của bạn.**"

        await ctx.send(embed=disnake.Embed(description=txt, colour=self.bot.get_color(ctx.guild.me)))

    @commands.Cog.listener("on_button_click")
    async def close_shell_result(self, inter: disnake.MessageInteraction):

        if inter.data.custom_id != "close_shell_result":
            return

        if not await self.bot.is_owner(inter.author):
            return await inter.send("**Chỉ chủ sở hữu của tôi mới có thể sử dụng nút này!**", ephemeral=True)

        await inter.response.edit_message(
            content="```ini\n🔒 - [Shell Đóng!] - 🔒```",
            attachments=None,
            view=None,
            embed=None
        )

    @commands.is_owner()
    @commands.command(aliases=["sh"], hidden=True)
    async def shell(self, ctx: CustomContext, *, command: str):

        if command.startswith('```') and command.endswith('```'):
            if command[4] != "\n":
                command = f"```\n{command[3:]}"
            if command[:-4] != "\n":
                command = command[:-3] + "\n```"
            command = '\n'.join(command.split('\n')[1:-1])
        else:
            command = command.strip('` \n')

        try:
            async with ctx.typing():
                result = await run_command(command)
        except GenericError as e:
            kwargs = {}
            if len(e.text) > 2000:
                kwargs["file"] = string_to_file(e.text, filename="error.txt")
            else:
                kwargs["content"] = f"```py\n{e.text}```"

            try:
                await ctx.author.send(**kwargs)
                await ctx.message.add_reaction("⚠️")
            except disnake.Forbidden:
                traceback.print_exc()
                raise GenericError(
                    "**Đã xảy ra lỗi (kiểm tra nhật ký/thiết bị đầu cuối hoặc phát hành DM của bạn sang lần tiếp theo "
                    "Kết quả được gửi trực tiếp đến DM của bạn).**"
                )

        else:

            kwargs = {}
            if len(result) > 2000:
                kwargs["file"] = string_to_file(result, filename=f"shell_result_{ctx.message.id}.txt")
            else:
                kwargs["content"] = f"```py\n{result}```"

            await ctx.reply(
                components=[
                    disnake.ui.Button(label="Đóng Shell", custom_id="close_shell_result", emoji="♻️")
                ],
                mention_author=False,
                **kwargs
            )

    @check_voice()
    @commands.cooldown(1, 15, commands.BucketType.guild)
    @commands.command(description='Khởi động một người chơi trên máy chủ.', aliases=["spawn", "sp", "spw", "smn"])
    async def summon(self, ctx: CustomContext):

        try:
            self.bot.music.players[ctx.guild.id]  # type ignore
            raise GenericError("**Đã có một người chơi bắt đầu trên máy chủ.**")
        except KeyError:
            pass

        node: wavelink.Node = self.bot.music.get_best_node()

        if not node:
            raise GenericError("**Không có máy chủ âm nhạc có sẵn!**")

        try:
            guild_data = ctx.guild_data
        except AttributeError:
            guild_data = await self.bot.get_data(ctx.guild.id, db_name=DBModel.guilds)
            ctx.guild_data = guild_data

        try:
            global_data = ctx.global_guild_data
        except AttributeError:
            global_data = await self.bot.get_global_data(ctx.guild.id, db_name=DBModel.guilds)
            ctx.global_guild_data = global_data

        static_player = guild_data['player_controller']

        skin = guild_data["player_controller"]["skin"]
        static_skin = guild_data["player_controller"]["static_skin"]

        if global_data["global_skin"]:
            skin = global_data["player_skin"] or skin
            static_skin = global_data["player_skin_static"] or guild_data["player_controller"]["static_skin"]

        try:
            channel = self.bot.get_channel(int(static_player['channel'])) or await self.bot.fetch_channel(int(static_player['channel'])) or ctx.channel
        except (KeyError, TypeError, disnake.NotFound):
            channel = ctx.channel
            message = None
            static_player = False
        else:
            try:
                message = await channel.fetch_message(int(static_player.get('message_id')))
            except (TypeError, disnake.NotFound):
                message = None
            static_player = True

        try:
            invite = global_data["listen_along_invites"][str(ctx.channel.id)]
        except KeyError:
            invite = None

        else:
            if not await self.bot.fetch_invite(invite):
                invite = None
                del global_data["listen_along_invites"][str(ctx.channel.id)]
                await self.bot.update_global_data(ctx.guild_id, global_data, db_name=DBModel.guilds)

        player: LavalinkPlayer = self.bot.music.get_player(
            guild_id=ctx.guild_id,
            cls=LavalinkPlayer,
            player_creator=ctx.author.id,
            guild=ctx.guild,
            channel=channel or ctx.channel,
            last_message_id=guild_data['player_controller']['message_id'],
            node_id=node.identifier,
            static=static_player,
            skin=self.bot.check_skin(skin),
            custom_skin_data=global_data["custom_skins"],
            custom_skin_static_data=global_data["custom_skins_static"],
            skin_static=self.bot.check_static_skin(static_skin),
            extra_hints=self.extra_hints,
            restrict_mode=guild_data['enable_restrict_mode'],
            listen_along_invite=invite,
            volume=int(guild_data['default_player_volume']),
            autoplay=guild_data["autoplay"]
        )

        player.message = message

        channel = ctx.author.voice.channel

        await player.connect(channel.id)

        self.bot.loop.create_task(ctx.message.add_reaction("👍"))

        while not ctx.guild.me.voice:
            await asyncio.sleep(1)

        if isinstance(channel, disnake.StageChannel):

            stage_perms = channel.permissions_for(ctx.guild.me)
            if stage_perms.manage_permissions:
                await ctx.guild.me.edit(suppress=False)

            await asyncio.sleep(1.5)

        await player.process_next()

    async def cog_check(self, ctx: CustomContext) -> bool:
        return await check_requester_channel(ctx)

    async def cog_load(self) -> None:
        self.owner_view = PanelView(self.bot)

    async def download_lavalink_serverlist(self):
        async with ClientSession() as session:
            async with session.get(self.bot.config["LAVALINK_SERVER_LIST"]) as r:
                ini_file = await r.read()
                with open("lavalink.ini", "wb") as f:
                    f.write(ini_file)


def setup(bot: BotCore):
    bot.add_cog(Owner(bot))

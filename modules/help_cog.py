from __future__ import annotations

from typing import TYPE_CHECKING, Union, Optional

import disnake
import disnake as discord
from disnake.ext import commands

from utils.music.errors import GenericError
from utils.others import CustomContext

if TYPE_CHECKING:
    from utils.client import BotCore

category_icons = {}


class ViewHelp(discord.ui.View):

    def __init__(self, ctx, items, *, get_cmd, main_embed, cmd_list, category_cmd=None, timeout=180):
        self.message: Optional[discord.Message] = None
        self.page_index = 0
        self.cmd_lst = cmd_list
        self.category = category_cmd
        self.get_cmd = get_cmd
        self.items = items
        self.ctx = ctx
        self.main_embed = main_embed
        self.first_embed = main_embed
        super().__init__(timeout=timeout)
        self.process_buttons()

    async def interaction_check(self, interaction: discord.Interaction):

        if interaction.user != self.ctx.author:
            await interaction.response.send_message(f"Chỉ có thành viên {self.ctx.author.mention} mới có thể sử dụng các tùy chọn này.", ephemeral=True)
            return

        return True

    def process_buttons(self):

        options = []

        for category, emoji in self.items:

            b = discord.SelectOption(
                label=category, value=category, emoji=emoji, default=category == self.category,
                description="Xem chi tiết về các lệnh của danh mục này."
            )

            options.append(b)

        if options:
            sel = discord.ui.Select(placeholder='Chọn một danh mục để xem tất cả các lệnh:', options=options)
            sel.callback = self.callback_help
            self.add_item(sel)

        if self.category:

            if len(self.cmd_lst[self.category]['cmds']) > 1:
                left_button = discord.ui.Button(style=discord.ButtonStyle.grey, emoji='<:arrow_left:867934922944442368>', custom_id="left_page")
                left_button.callback = self.callback_left
                self.add_item(left_button)

                right_button = discord.ui.Button(style=discord.ButtonStyle.grey, emoji='<:arrow_right:867934922940235787>', custom_id="right_page")
                right_button.callback = self.callback_right
                self.add_item(right_button)

            back_button = discord.ui.Button(style=discord.ButtonStyle.grey, emoji='<:leftwards_arrow_with_hook:868761137703964692>', custom_id="back_page", label="Quay trở lại")
            back_button.callback = self.callback_back
            self.add_item(back_button)

    async def response(self, interaction):

        if not self.category and not self.page_index:
            self.clear_items()
            self.process_buttons()

        self.main_embed = await self.get_cmd(
            ctx=self.ctx,
            index=self.page_index,
            cmds=self.cmd_lst[self.category]['cmds'],
            emoji=self.cmd_lst[self.category]['emoji'],
            category=self.category)

        await interaction.response.edit_message(embed= self.main_embed, view=self)

    async def callback_left(self, interaction):

        if self.page_index == 0:
            self.page_index += len(self.cmd_lst[self.category]['cmds']) - 1
        else:
            self.page_index -= 1

        await self.response(interaction)

    async def callback_right(self, interaction):

        if self.page_index == len(self.cmd_lst[self.category]['cmds']) - 1:
            self.page_index -= len(self.cmd_lst[self.category]['cmds']) - 1
        else:
            self.page_index += 1

        await self.response(interaction)

    async def callback_back(self, interaction):

        self.page_index = 0
        self.category = None
        self.clear_items()
        self.process_buttons()

        await interaction.response.edit_message(embed=self.first_embed, view=self)

    async def callback_help(self, interaction: discord.MessageInteraction):

        self.category = interaction.data.values[0]

        self.page_index = 0
        self.clear_items()
        self.process_buttons()

        self.main_embed = await self.get_cmd(
            ctx=self.ctx,
            index=self.page_index,
            cmds=self.cmd_lst[self.category]['cmds'],
            emoji=self.cmd_lst[self.category]['emoji'],
            category=self.category)

        await interaction.response.edit_message(embed=self.main_embed, view=self)


async def check_perms(ctx: CustomContext, cmd: commands.Command):

    try:
        if cmd.hidden and not await ctx.bot.is_owner(ctx.author):
            return False
    except:
        return False

    return True


def check_cmd(cmd: commands.command):
    if hasattr(cmd, 'category') and cmd.category:
        return True


class HelpCog(commands.Cog, name="Ajuda"):

    def __init__(self, bot: BotCore):
        self.bot = bot
        self._original_help_command = bot.help_command
        bot.remove_command("help")
        self.task_users = {}
        self.mention_cd = commands.CooldownMapping.from_cooldown(1, 30, commands.BucketType.channel)

    async def get_cmd(self, ctx, cmds, index=0, category=None, emoji=None):

        cmd = cmds[index]

        if cmd.description:
            help_cmd = cmd.description
        else:
            help_cmd = "Không có mô tả ..."

        prefix = ctx.prefix if str(ctx.me.id) not in ctx.prefix else f"@{ctx.me.display_name} "

        if cmd.usage:
            usage_cmd = cmd.usage.replace("{prefix}", prefix).replace("{cmd}", cmd.name).replace("{parent}", cmd.full_parent_name).replace(f"<@!{ctx.bot.user.id}>", f"@{ctx.me.name}").replace(f"<@{ctx.bot.user.id}>", f"@{ctx.me.name}")
        else:
            usage_cmd = ""

        embed = discord.Embed(color=self.bot.get_color(ctx.guild.me))

        txt = f"### ⌨️ Lệnh {ctx.prefix}{cmd}\n```\n{help_cmd}```\n"
        if cmd.aliases:
            aliases = " | ".join([f"{ctx.prefix}{ali}" for ali in cmd.aliases])
            txt += f"🔄 **⠂ Lựa chọn thay thế:** ```\n{aliases}```\n"
        if hasattr(cmd, 'commands'):
            subs = " | ".join([c.name for c in cmd.commands if (await check_perms(ctx, c))])
            txt += f"🔢 **Lệnh phụ:** ```{subs}``` Sử dụng lệnh: `[ {ctx.prefix}help {cmd} Lệnh phụ ]` Để xem thêm chi tiết của lệnh phụ.\n\n"

        if usage_cmd:
            txt += f"📘 **⠂Cách sử dụng:** ```\n{usage_cmd}```\n" \
                   f"⚠️ **⠂Ghi chú về việc sử dụng các đối số trong lệnh:** ```\n" \
                   f"[] = Bắt buộc | <> = Không bắt buộc```\n"

        flags = cmd.extras.get("flags")

        if flags and (actions := flags._actions):

            t = []

            for a in actions:

                # if a.hidden:
                #    continue

                if not a.help or not a.option_strings:
                    continue

                s = " ".join(i for i in a.option_strings)

                s = f"[{s}] {a.help}"

                # s += f" = `{a.help}`"

                # if a.default is False:
                #	s += " `Padrão: Desativado`"
                # elif a.default is True:
                #	s += " `Padrão: Ativado`"
                # elif not a.default is None:
                #	s += f" `Padrão: {a.default}`"
                t.append(s)

            if t:
                txt += ("🚩 **⠂Cờ `(tùy chọn để thêm ở cuối lệnh)`:**```ini\n" + "\n\n".join(t) + "```")

        embed.set_author(name="Menu trợ giúp - Danh sách các lệnh (tiền tố)", icon_url=self.bot.user.display_avatar.url)

        embed.description = txt

        try:
            appinfo = ctx.bot.appinfo
        except AttributeError:
            appinfo = (await ctx.bot.application_info())
            ctx.bot.appinfo = appinfo
        try:
            owner = appinfo.team.owner
        except AttributeError:
            owner = appinfo.owner

        if (max_pages:=len(cmds)) > 1:
            embed.set_footer(icon_url=owner.display_avatar.replace(static_format="png"),
                             text=f"Trang: {index + 1} của {max_pages}")
        return embed

    @commands.cooldown(2, 5, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    @commands.command(hidden=True, name='help', aliases=['ajuda'])
    async def _help(self, ctx, *cmd_name):

        if cmd_name:
            await self.parse_direct(ctx, list(cmd_name))
            return

        cmdlst = {}

        for cmd in sorted(ctx.bot.commands, key=lambda c: c.name):

            if not await check_perms(ctx, cmd):
                continue

            if check_cmd(cmd):
                category_icon = category_icons.get(cmd.category)
            else:
                category_icon = None

            if category_icon:
                if not category_icon in cmdlst:
                    cmdlst[category_icon] = (cmd.category, [])
                cmdlst[category_icon][1].append(cmd)

            elif not cmd.cog or not hasattr(cmd.cog, 'name'):
                if not "🔰" in cmdlst:
                    cmdlst["🔰"] = ("Các lệnh xàm lul", [])
                cmdlst["🔰"][1].append(cmd)

            else:
                if not cmd.cog.emoji:
                    cmd.cog.emoji = "⁉"
                    cmd.cog.name = "Không có thể loại"
                if not cmd.cog.emoji in cmdlst:
                    cmdlst[cmd.cog.emoji] = (cmd.cog.name, [])
                cmdlst[cmd.cog.emoji][1].append(cmd)

        lst = []

        btn_id = []

        cmd_lst_new = {}

        for icon, data in cmdlst.items():
            cmd_lst_new[data[0]] = {"emoji": icon, "cmds": data[1]}

        for category, data in sorted(cmd_lst_new.items()):
            btn_id.append([category, data["emoji"]])

            cmds = ', '.join([c.name for c in sorted(data['cmds'], key=lambda c: c.name)])
            n = len(data['cmds'])
            lst.append(f"\n\n**{data['emoji']} ⠂{category} ({n} {'Các' if n > 1 else ''} Lệnh):**\n`{cmds}`")

        txt = f"{''.join(lst)}\n\n" \
              "Để biết thông tin từ một lệnh trực tiếp, hãy sử dụng: \n" \
              f"`{ctx.prefix}{ctx.invoked_with} <lệnh/bí danh>`"

        embed = discord.Embed(
            description=txt.replace(ctx.me.mention, f"@{ctx.me.display_name}").replace(f"<@!{ctx.bot.user.id}>",
                                                                                       f"@{ctx.me.display_name}"),
            color=self.bot.get_color(ctx.guild.me))
        embed.set_author(name=f"Menu trợ giúp - Danh sách các lệnh (tiền tố)",
                         icon_url=self.bot.user.display_avatar.replace(static_format="png").url)

        embed.set_footer(icon_url=self.bot.owner.display_avatar.replace(static_format="png").url,
                         text=f"Chủ sở hữu: {self.bot.owner} [{self.bot.owner.id}]")

        view = ViewHelp(ctx, btn_id, get_cmd=self.get_cmd, cmd_list=cmd_lst_new, category_cmd=None,
                 main_embed=embed, timeout=180)

        view.message = await ctx.send(embed=embed, mention_author=False,
                             view=view)

        await view.wait()

        eb = view.main_embed
        eb.clear_fields()

        for item in view.children:
            if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                item.disabled = True

        try:
            await view.message.edit(embed=eb, view=view)
        except disnake.NotFound:
            pass


    async def parse_direct(self, ctx: CustomContext, cmd_name: list):

        # TODO: corrigir modo recursivo de subcommands
        cmd: Union[commands.command, commands.Group] = None
        for cname in cmd_name:
            if cmd:
                if hasattr(cmd, "commands"):
                    c = cmd.get_command(cname)
                    if not c:
                        break
                    else:
                        cmd = c
            else:
                cmd = ctx.bot.get_command(cname)
                if not hasattr(cmd, "commands"):
                    break

        if not cmd or (not await check_perms(ctx, cmd)):
            b = "`" if len(cmd_name) > 1 else ''
            raise GenericError(f"Yêu cầu [{b}{' '.join(cmd_name[:-1])}{b}{' ' if len(cmd_name) > 1 else ''}**{cmd_name[-1]}**] không tìm thấy!")

        if any(c for c in cmd.cog.get_commands() if check_cmd(c)):
            name = cmd.category if cmd.category else cmd.cog.name
            emoji = category_icons.get(name) or cmd.cog.emoji
            cmds = [c for c in sorted(ctx.bot.commands, key=lambda cm: cm.name) if await check_perms(ctx, c) and (hasattr(c.cog, 'name') and not c.category and c.cog.name == name) or (hasattr(c, 'category') and c.category == name)]
            try:
                index = cmds.index(cmd)
            except:
                cmds = [cmd]
                index = 0
        else:
            cog = ctx.bot.get_cog(cmd.cog_name)
            name = cog.name if hasattr(cog, "name") else "Các lệnh xàm lul"
            emoji = cog.emoji if hasattr(cog, "emoji") else "🔰"

            cmds = [c for c in sorted(cog.get_commands(), key=lambda cm: cm.name) if await check_perms(ctx, c) or not c.hidden]
            try:
                index = cmds.index(cmd)
            except:
                cmds = [cmd]
                index = 0

        await ctx.reply(ctx.author.mention, embed=await self.get_cmd(ctx=ctx, cmds=cmds, index=index, category=name, emoji=emoji), mention_author = False)


    async def add_reactions(self, msg: discord.Message, reactions):
        for e in reactions:
            await msg.add_reaction(e)

    def cog_unload(self):
        self.bot.help_command = self._original_help_command

def setup(bot: BotCore):
    bot.add_cog(HelpCog(bot))

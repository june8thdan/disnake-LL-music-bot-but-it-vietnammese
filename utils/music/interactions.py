# -*- coding: utf-8 -*-
from typing import List, Union, Optional

import disnake
from disnake.ext import commands

from utils.music.converters import time_format, fix_characters
from utils.others import check_cmd


class VolumeInteraction(disnake.ui.View):

    def __init__(self, inter):
        self.inter = inter
        self.volume = None
        super().__init__(timeout=30)
        self.process_buttons()

    def process_buttons(self):

        opts = []

        for l in [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 101, 120, 150]:
            
            if l > 100:
                description = "Trên 100% âm thanh có thể rất tệ."
            else:
                description = None
            opts.append(disnake.SelectOption(label=f"{l}%", value=f"vol_{l}", description=description))

        select = disnake.ui.Select(placeholder='Mức:', options=opts)
        select.callback = self.callback
        self.add_item(select)

    async def callback(self, interaction: disnake.MessageInteraction):
        await interaction.response.edit_message(content=f"Đã thay đổi âm lượng!",embed=None, view=None)
        self.volume = int(interaction.data.values[0][4:])
        self.stop()


class QueueInteraction(disnake.ui.View):

    def __init__(self, player, user: disnake.Member, timeout=60):

        self.player = player
        self.bot = player.bot
        self.user = user
        self.pages = []
        self.select_pages = []
        self.current = 0
        self.max_page = len(self.pages) - 1
        self.message: Optional[disnake.Message] = None
        super().__init__(timeout=timeout)
        self.embed = disnake.Embed(color=self.bot.get_color(user.guild.me))
        self.update_pages()
        self.update_embed()

    def update_pages(self):

        counter = 1

        self.pages = list(disnake.utils.as_chunks(self.player.queue, max_size=12))
        self.select_pages.clear()

        self.clear_items()

        for n, page in enumerate(self.pages):

            txt = "\n"
            opts = []

            for t in page:

                duration = time_format(t.duration) if not t.is_stream else '🔴 Livestream'

                txt += f"`┌ {counter})` [`{fix_characters(t.title, limit=50)}`]({t.uri})\n" \
                       f"`└ ⏲️ {duration}`" + (f" - `Lặp lại: {t.track_loops}`" if t.track_loops else  "") + \
                       f" **|** `✋` <@{t.requester}>\n"

                opts.append(
                    disnake.SelectOption(
                        label=f"{counter}. {t.author}"[:25], description=f"[{duration}] | {t.title}"[:50],
                        value=f"queue_select_{t.unique_id}",
                    )
                )

                counter += 1

            self.pages[n] = txt
            self.select_pages.append(opts)

        track_select = disnake.ui.Select(
            placeholder="Phát một bài hát cụ thể trên trang:",
            options=self.select_pages[self.current],
            custom_id="queue_track_selection",
            max_values=1
        )

        track_select.callback = self.track_select_callback

        self.add_item(track_select)

        first = disnake.ui.Button(emoji='⏮️', style=disnake.ButtonStyle.grey)
        first.callback = self.first
        self.add_item(first)

        back = disnake.ui.Button(emoji='⬅️', style=disnake.ButtonStyle.grey)
        back.callback = self.back
        self.add_item(back)

        next = disnake.ui.Button(emoji='➡️', style=disnake.ButtonStyle.grey)
        next.callback = self.next
        self.add_item(next)

        last = disnake.ui.Button(emoji='⏭️', style=disnake.ButtonStyle.grey)
        last.callback = self.last
        self.add_item(last)

        stop_interaction = disnake.ui.Button(emoji='⏹️', style=disnake.ButtonStyle.grey)
        stop_interaction.callback = self.stop_interaction
        self.add_item(stop_interaction)

        update_q = disnake.ui.Button(emoji='🔄', label="Làm mới", style=disnake.ButtonStyle.grey)
        update_q.callback = self.update_q
        self.add_item(update_q)

        self.current = 0
        self.max_page = len(self.pages) - 1

    async def on_timeout(self) -> None:

        if not self.message:
            return

        embed = self.message.embeds[0]
        embed.set_footer(text="Thời gian để tương tác kiệt sức!")

        for c in self.children:
            c.disabled = True

        await self.message.edit(embed=embed, view=self)


    def update_embed(self):
        self.embed.title = f"**Bài hát Fila [{self.current+1} / {self.max_page+1}]**"
        self.embed.description = self.pages[self.current]
        self.children[2].options = self.select_pages[self.current]

        for n, c in enumerate(self.children):
            if isinstance(c, disnake.ui.StringSelect):
                self.children[n].options = self.select_pages[self.current]

    async def track_select_callback(self, interaction: disnake.MessageInteraction):

        track_id = interaction.values[0][13:]

        track = None

        for t in  self.player.queue:
            if t.unique_id == track_id:
                track = t
                break

        if not track:
            await interaction.send(f"Âm nhạc như id \"{track_id}\" Không tìm thấy trong dòng người chơi...", ephemeral=True)
            return

        command = self.bot.get_slash_command("skip")

        interaction.music_bot = self.bot
        interaction.music_guild = self.user.guild

        try:
            await check_cmd(command, interaction)
            await command(interaction, query=f"{track.title} || ID > {track.unique_id}")
            self.stop()
        except Exception as e:
            self.bot.dispatch('interaction_player_error', interaction, e)

    async def first(self, interaction: disnake.MessageInteraction):

        self.current = 0
        self.update_embed()
        await interaction.response.edit_message(embed=self.embed)

    async def back(self, interaction: disnake.MessageInteraction):

        if self.current == 0:
            self.current = self.max_page
        else:
            self.current -= 1
        self.update_embed()
        await interaction.response.edit_message(embed=self.embed, view=self)

    async def next(self, interaction: disnake.MessageInteraction):

        if self.current == self.max_page:
            self.current = 0
        else:
            self.current += 1
        self.update_embed()
        await interaction.response.edit_message(embed=self.embed, view=self)

    async def last(self, interaction: disnake.MessageInteraction):

        self.current = self.max_page
        self.update_embed()
        await interaction.response.edit_message(embed=self.embed)


    async def stop_interaction(self, interaction: disnake.MessageInteraction):

        await interaction.response.edit_message(content="Đóng", embed=None, view=None)
        self.stop()

    async def update_q(self, interaction: disnake.MessageInteraction):

        self.current = 0
        self.max_page = len(self.pages) - 1
        self.update_pages()
        self.update_embed()
        await interaction.response.edit_message(embed=self.embed, view=self)


class SelectInteraction(disnake.ui.View):

    def __init__(self, user: disnake.Member, opts: List[disnake.SelectOption], *, timeout=180):
        super().__init__(timeout=timeout)
        self.user = user
        self.selected = None
        self.item_pages = list(disnake.utils.as_chunks(opts, 25))
        self.current_page = 0
        self.max_page = len(self.item_pages)
        self.inter = None

        self.load_components()

    def load_components(self):

        self.clear_items()

        select_menu = disnake.ui.Select(placeholder='Chọn một tùy chọn:', options=self.item_pages[self.current_page])
        select_menu.callback = self.callback
        self.add_item(select_menu)
        self.selected = self.item_pages[self.current_page][0].value

        if len(self.item_pages) > 1:

            back_button = disnake.ui.Button(emoji="⬅")
            back_button.callback = self.back_callback
            self.add_item(back_button)

            next_button = disnake.ui.Button(emoji="➡")
            next_button.callback = self.next_callback
            self.add_item(next_button)

        button = disnake.ui.Button(label="Hủy bỏ", emoji="❌")
        button.callback = self.cancel_callback
        self.add_item(button)

    async def interaction_check(self, interaction: disnake.MessageInteraction) -> bool:

        if interaction.user.id == self.user.id:
            return True

        await interaction.send(f"Chỉ {self.user.mention} mới có thể tương tác ở đây.", ephemeral = True)

    async def back_callback(self, interaction: disnake.MessageInteraction):
        if self.current_page == 0:
            self.current_page = self.max_page
        else:
            self.current_page -= 1
        self.load_components()
        await interaction.response.edit_message(view=self)

    async def next_callback(self, interaction: disnake.MessageInteraction):
        if self.current_page == self.max_page:
            self.current_page = 0
        else:
            self.current_page += 1
        self.load_components()
        await interaction.response.edit_message(view=self)

    async def cancel_callback(self, interaction: disnake.MessageInteraction):
        self.selected = False
        self.inter = interaction
        self.stop()

    async def callback(self, interaction: disnake.MessageInteraction):
        self.selected = interaction.data.values[0]
        self.inter = interaction
        self.stop()


class AskView(disnake.ui.View):

    def __init__(self, *, ctx: Union[commands.Context, disnake.Interaction], timeout=None):
        super().__init__(timeout=timeout)
        self.selected = None
        self.ctx = ctx
        self.interaction_resp: Optional[disnake.MessageInteraction] = None

    async def interaction_check(self, interaction: disnake.MessageInteraction) -> bool:

        if interaction.user != self.ctx.author:
            await interaction.send("Bạn không thể sử dụng nút này!", ephemeral=True)
            return False

        return True

    @disnake.ui.button(label="Đồng ý", emoji="✅")
    async def allow(self, button, interaction: disnake.MessageInteraction):
        self.selected = True
        self.interaction_resp = interaction
        self.stop()

    @disnake.ui.button(label="KHÔNG", emoji="❌")
    async def deny(self, button, interaction: disnake.MessageInteraction):
        self.selected = False
        self.interaction_resp = interaction
        self.stop()

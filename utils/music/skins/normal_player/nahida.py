# -*- coding: utf-8 -*-
import datetime
import itertools

import disnake

from utils.music.converters import fix_characters, time_format, get_button_style, music_source_image
from utils.music.models import LavalinkPlayer
from utils.others import PlayerControls


class Nahida:

    __slots__ = ("name", "preview")

    def __init__(self):
        self.name = "nahida"
        self.preview = "https://media.discordapp.net/attachments/554468640942981147/1047184546531115078/skin_default.png?width=377&height=520"

    def setup_features(self, player: LavalinkPlayer):
        player.mini_queue_feature = True
        player.controller_mode = True
        player.auto_update = 0
        player.hint_rate = player.bot.config["HINT_RATE"]
        player.static = False

    def load(self, player: LavalinkPlayer) -> dict:

        data = {
            "content": None,
            "embeds": []
        }

        embed = disnake.Embed(color=player.bot.get_color(player.guild.me))
        embed_queue = None
        vc_txt = ""

        if not player.paused:
            embed.set_author(
                name="Đang phát:",
                icon_url=music_source_image(player.current.info["sourceName"])
            )

        else:
            embed.set_author(
                name="Tạm dừng:",
                icon_url="https://cdn.discordapp.com/attachments/480195401543188483/896013933197013002/pause.png"
            )

        if player.current_hint:
            embed.set_footer(text=f"💡 Gợi ý: {player.current_hint}")
        elif player.node.identifier != "LOCAL":
            embed.set_footer(
                text=str(player),
                icon_url="https://cdn.discordapp.com/emojis/1105722934317826088.gif?size=96&quality=lossless"
            )

        player.mini_queue_feature = True

        duration = "> 🔴 **⠂Độ dài ** `Livestream`" if player.current.is_stream else \
            (f"> ** Độ dài ** `{time_format(player.current.duration)} [`" +
            f"<t:{int((disnake.utils.utcnow() + datetime.timedelta(milliseconds=player.current.duration - player.position)).timestamp())}:R>`]`"
            if not player.paused else '')

        txt = f"[`{player.current.single_title}`]({player.current.uri})\n\n" \
              f"{duration}\n" \
              f"> **⠂Người tải lên: ** {player.current.authors_md}\n" \
              f"> **⠂Người mở: ** <@{player.current.requester}>\n" \
              f"> **⠂Âm lượng** `{player.volume}%`"
        if player.current.track_loops:
            txt += f"\n> **⠂Lặp lại còn lại:** `{player.current.track_loops}`"

        if player.loop:
            if player.loop == 'current':
                e = ''; m = 'âm nhạc hiện tại'
            else:
                e = ''; m = 'Hàng ngang'
            txt += f"\n> {e} **⠂Chế độ lặp lại:** `{m}`"

        if player.nightcore:
            txt += f"\n> 🇳 **Hiệu ứng Nightcore:** `Kích Hoạt`"

        if player.current.album_name:
            txt += f"\n> 💽 **⠂Album:** [`{fix_characters(player.current.album_name, limit=16)}`]({player.current.album_url})"

        if player.current.playlist_name:
            txt += f"\n> 📑 **⠂Playlist:** [`{fix_characters(player.current.playlist_name, limit=16)}`]({player.current.playlist_url})"

        if (qlenght:=len(player.queue)) and not player.mini_queue_enabled:
            txt += f"\n> **⠂Bài hát trong dòng:** `{qlenght}`"

        if player.keep_connected:
            txt += "\n> ♾️ **⠂Chế độ 24/7:** `Kích hoạt`"

        elif player.restrict_mode:
            txt += f"\n> 🔒 **⠂Chế độ hạn chế:** `Kích Hoạt`"

        txt += f"{vc_txt}\n"

        if player.command_log:
            txt += f"```ansi\n [34;1mTương tác cuối cùng[0m```**┕ {player.command_log_emoji} ⠂**{player.command_log}\n"

        if len(player.queue) and player.mini_queue_enabled:

            queue_txt = "\n".join(
                f"`{(n + 1):02}) [{time_format(t.duration) if not t.is_stream else '🔴 Livestream'}]` [`{fix_characters(t.title, 38)}`]({t.uri})"
                for n, t in (enumerate(itertools.islice(player.queue, 3)))
            )

            embed_queue = disnake.Embed(title=f"Bài hát trong dòng:{qlenght}", color=player.bot.get_color(player.guild.me),
                                        description=f"\n{queue_txt}")

            if not player.loop and not player.keep_connected and not player.paused:

                queue_duration = 0

                for t in player.queue:
                    if not t.is_stream:
                        queue_duration += t.duration

                embed_queue.description += f"\n`[⌛ Các bài hát kết thúc` <t:{int((disnake.utils.utcnow() + datetime.timedelta(milliseconds=(queue_duration + (player.current.duration if not player.current.is_stream else 0)) - player.position)).timestamp())}:R> `⌛]`"

            embed_queue.set_image(url="https://cdn.discordapp.com/attachments/1117523937912422422/1126039243135930488/nahida_dance_gif.gif")

        embed.description = txt
        embed.set_image(url="https://cdn.discordapp.com/attachments/1117523937912422422/1126039243135930488/nahida_dance_gif.gif")
        embed.set_thumbnail(url=player.current.thumb)

        data["embeds"] = [embed_queue, embed] if embed_queue else [embed]

        data["components"] = [
            disnake.ui.Button(emoji="⏯️", custom_id=PlayerControls.pause_resume, style=get_button_style(player.paused)),
            disnake.ui.Button(emoji="⏮️", custom_id=PlayerControls.back),
            disnake.ui.Button(emoji="<:terytery:1117800053365551165>", custom_id=PlayerControls.stop),
            disnake.ui.Button(emoji="⏭️", custom_id=PlayerControls.skip),
            disnake.ui.Button(emoji="<:music_queue:703761160679194734>", custom_id=PlayerControls.queue, label="[ Queue ]"),
            disnake.ui.Select(
                      placeholder="Các lựa chọn khác:",
                custom_id="musicplayer_dropdown_inter",
                min_values=0, max_values=1,
                options=[
                    disnake.SelectOption(
                        label="Thêm bài hát", emoji="<:add_music:588172015760965654>",
                        value=PlayerControls.add_song,
                        description="Thêm một bài hát/danh sách phát theo dòng."
                    ),
                    disnake.SelectOption(
                        label="Thêm bài hát vào yêu thích", emoji="⭐",
                        value=PlayerControls.enqueue_fav,
                        description="Thêm một trong những mục yêu thích của bạn trong dòng."
                    ),
                    disnake.SelectOption(
                        label="Tua về đầu", emoji="⏪",
                        value=PlayerControls.seek_to_start,
                        description="Trở lại thời gian của bài hát hiện tại đến đầu."
                    ),
                    disnake.SelectOption(
                        label="Âm lượng", emoji="🔊",
                        value=PlayerControls.volume,
                        description="Điều chỉnh âm lượng."
                    ),
                    disnake.SelectOption(
                        label="Pha trộn", emoji="🔀",
                        value=PlayerControls.shuffle,
                        description="Trộn ngẫu nhiên."
                    ),  
                    disnake.SelectOption(
                        label="Thêm lại bài hát", emoji="🎶",
                        value=PlayerControls.readd,
                        description="Thêm lại các bài hát đã phát lại vào hàng đợi."
                    ),
                    disnake.SelectOption(
                        label="Lặp lại bài hát", emoji="🔁",
                        value=PlayerControls.loop_mode,
                        description="Kích hoạt/Vô hiệu hóa nhạc/Hàng đợi lặp lại."
                    ),
                    disnake.SelectOption(
                        label="Nightcore", emoji="🇳",
                        value=PlayerControls.nightcore,
                        description="Sped up(có vậy thôi tự hiểu đi)"
                    ),
                    disnake.SelectOption(
                        label="Kích hoạt/Vô hiệu hóa chế độ bị hạn chế", emoji="🔐",
                        value=PlayerControls.restrict_mode,
                        description="Ngăn chế độ hạn chế"
                    ),
                ]
            ),
        ]

        if player.mini_queue_feature:
            data["components"][5].options.append(
                disnake.SelectOption(
                    label="Danh sách phát mini của người chơi", emoji="<:music_queue:703761160679194734>",
                    value=PlayerControls.miniqueue,
                    description="Kích hoạt/vô hiệu hóa Danh sách phát mini của người chơi."
                )
            )

        return data

def load():
    return Nahida()

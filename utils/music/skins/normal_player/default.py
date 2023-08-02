# -*- coding: utf-8 -*-
import datetime
import itertools

import disnake

from utils.music.converters import fix_characters, time_format, get_button_style, music_source_image
from utils.music.models import LavalinkPlayer
from utils.others import ProgressBar, PlayerControls


class DefaultSkin:

    __slots__ = ("name", "preview")

    def __init__(self):
        self.name = "default"
        self.preview = "https://cdn.discordapp.com/attachments/554468640942981147/1047184550230495272/skin_progressbar.png"

    def setup_features(self, player: LavalinkPlayer):
        player.mini_queue_feature = True
        player.controller_mode = True
        player.auto_update = 15
        player.hint_rate = player.bot.config["HINT_RATE"]
        player.static = False

    def load(self, player: LavalinkPlayer) -> dict:

        data = {
            "content": None,
            "embeds": []
        }

        embed = disnake.Embed(color=player.bot.get_color(player.guild.me))
        embed_queue = None

        if not player.paused:
            embed.set_author(
                name="Đang phát:",
                icon_url=music_source_image(player.current.info["sourceName"])
            )
        else:
            embed.set_author(
                name="Tạm dừng",
                icon_url="https://cdn.discordapp.com/attachments/480195401543188483/896013933197013002/pause.png"
            )

        if player.current_hint:
            embed.set_footer(text=f"💡 Gợi ý: {player.current_hint}")
        elif player.node.identifier != "LOCAL":
            embed.set_footer(
                text=str(player),
                icon_url="https://cdn.discordapp.com/emojis/1105722934317826088.gif?size=96&quality=lossless"
            )

        if player.current.is_stream:
            duration = "```ansi\n🔴 [31;1m Livestream[0m```"
        else:

            progress = ProgressBar(
                player.position,
                player.current.duration,
                bar_count=8
            )

            duration = f"```ansi\n[34;1m[{time_format(player.position)}] {('-'*progress.start)}[0m🔴️[36;1m{' '*progress.end} " \
                       f"[{time_format(player.current.duration)}][0m```\n"
            
            duration1 = "> 🔴 **Thời lượng:** `Livestream`\n" if player.current.is_stream else \
            (f"> ⏰ **Thời lượng:** `{time_format(player.current.duration)} [`" +
            f"<t:{int((disnake.utils.utcnow() + datetime.timedelta(milliseconds=player.current.duration - player.position)).timestamp())}:R>`]`\n"
            if not player.paused else '')

        vc_txt = ""

        txt = f"[`{player.current.single_title}`]({player.current.uri})\n\n" \
              f"{duration1}\n" \
              f"> <a:kurukuru_seseren:1118094291957465149>  **⠂Tác giả** {player.current.authors_md}\n" \
              f"> <:hutaolmao:1117802548032720926> **⠂Người gọi bài:** <@{player.current.requester}>\n" \
              f"> <a:aAngryPaimon:1121425831747649586> **⠂Âm lượng:** `{player.volume}%`\n " \

        if player.current.track_loops:
            txt += f"\n> <a:ricacdo:1118224548828024842> **⠂Lặp lại còn lại:** `{player.current.track_loops}`\n " \

        if player.current.autoplay:
            txt += f"> 🎵 **⠂Âm nhạc tự động:** `Bật`"

            try:
                txt += f" [`(link nhạc.)`]({player.current.info['extra']['related']['uri']})\n"
            except:
                txt += "\n"

        if player.loop:
            if player.loop == 'current':
                e = '<a:ricacdo:1118224548828024842>'
                m = 'Bài hát hiện tại'
            else:
                e = '<a:ricacdo:1118224548828024842>'
                m = 'Hàng'
            txt += f"\n> {e} **⠂Chế độ lặp lại:** `{m}`"

        if player.nightcore:
            txt += f"\n> 🇳 **⠂Hiệu ứng Nightcore:** `kích hoạt`"

        if player.current.album_name:
            txt += f"\n> <:CynoLOL:1117539934073540719> **⠂Album:** [`{fix_characters(player.current.album_name, limit=16)}`]({player.current.album_url})"

        if player.current.playlist_name:
            txt += f"\n> <:Youtube:1114392752269037708> **⠂Playlist:** [`{fix_characters(player.current.playlist_name, limit=16)}`]({player.current.playlist_url})"

        if (qlenght:=len(player.queue)) and not player.mini_queue_enabled:
            txt += f"\n> <a:raging:1117802405791268925> **⠂Bài hát trong dòng:** `{qlenght}`"

        if player.keep_connected:
            txt += f"\n> <:hutaoshame:1117802620522868767> **⠂Chế độ 24/7:** `Kích hoạt`"

        elif player.restrict_mode:
            txt += f"\n> <:xdd:1118053338110500925> **⠂Hạn chế:** `Kích hoạt`"

        if player.ping:
            txt += f"\n> <a:loading:1117802386333905017> **⠂Độ trễ:** `{player.ping}ms`"

        txt += f"{vc_txt}\n"

        if player.command_log:
            txt += f"> {player.command_log_emoji} **⠂Tương tác cuối cùng:** {player.command_log}\n"

        txt += duration

        if qlenght and player.mini_queue_enabled:

            queue_txt = "\n".join(
                f"`{(n + 1):02}) [{time_format(t.duration) if not t.is_stream else '🔴 Livestream'}]` [`{fix_characters(t.title, 38)}`]({t.uri})"
                for n, t in (enumerate(itertools.islice(player.queue, 3)))
            )

            embed_queue = disnake.Embed(title=f"Bài hát đang chờ:  {qlenght}", color=player.bot.get_color(player.guild.me),
                                        description=f"\n{queue_txt}")

            if not player.loop and not player.keep_connected and not player.paused and not player.current.is_stream:

                queue_duration = 0

                for t in player.queue:
                    if not t.is_stream:
                        queue_duration += t.duration

                if queue_duration:
                    embed_queue.description += f"\n`[⌛ Các bài hát kết thúc sau` <t:{int((disnake.utils.utcnow() + datetime.timedelta(milliseconds=(queue_duration + (player.current.duration if not player.current.is_stream else 0)) - player.position)).timestamp())}:R> `⌛]`"

            embed_queue.set_image(url="https://cdn.discordapp.com/attachments/1114279240909721630/1117715535417852037/tumblr_570c5224e28ef8793c5741aa8e7b5ccb_3efe9fa6_540.gif.gif")

        embed.description = txt
        embed.set_image(url="https://cdn.discordapp.com/attachments/1114279240909721630/1117715535417852037/tumblr_570c5224e28ef8793c5741aa8e7b5ccb_3efe9fa6_540.gif.gif")
        embed.set_thumbnail(url=player.current.thumb)

        data["embeds"] = [embed_queue, embed] if embed_queue else [embed]

        data["components"] = [
            disnake.ui.Button(emoji="<:ayaka_tea:1122325362702037022> ", custom_id=PlayerControls.stop, style=disnake.ButtonStyle.red),
            disnake.ui.Button(emoji="⏮️", custom_id=PlayerControls.back, style=disnake.ButtonStyle.green),
            disnake.ui.Button(emoji="⏯️", custom_id=PlayerControls.pause_resume, style=get_button_style(player.paused)),
            disnake.ui.Button(emoji="⏭️", custom_id=PlayerControls.skip, style=disnake.ButtonStyle.green),
            disnake.ui.Button(emoji="<:AyakaWao:1128237210710319154>", custom_id=PlayerControls.add_song, style=disnake.ButtonStyle.green, label="Thêm nhạc"),
            disnake.ui.Select(
                placeholder="Lựa chọn khác:",
                custom_id="musicplayer_dropdown_inter",
                min_values=0, max_values=1,
                options=[
                    disnake.SelectOption(
                        label="Thêm âm nhạc", emoji="<:add_music:588172015760965654>",
                        value=PlayerControls.add_song,
                        description="Thêm một bài hát/danh sách phát trong dòng."
                    ),
                    disnake.SelectOption(
                        label="Thêm yêu thích", emoji="⭐",
                        value=PlayerControls.enqueue_fav,
                        description="Thêm một trong những mục yêu thích của bạn theo dòng."
                    ),
                    disnake.SelectOption(
                        label="Tua về đầu bài", emoji="⏪",
                        value=PlayerControls.seek_to_start,
                        description="Tua thời gian bài nhạc hiện tại về 00:00."
                    ),
                    disnake.SelectOption(
                        label="Âm lượng", emoji="🔊",
                        value=PlayerControls.volume,
                        description="Điều chỉnh âm lượng"
                    ),
                    disnake.SelectOption(
                        label="Trộn các bài hát trong hàng", emoji="🔀",
                        value=PlayerControls.shuffle,
                        description="Trộn nhạc trong hàng đợi."
                    ),
                    disnake.SelectOption(
                        label="Chơi lại", emoji="🎶",
                        value=PlayerControls.readd,
                        description="Đưa các bài hát đã chơi trở lại hàng chờ."
                    ),
                    disnake.SelectOption(
                        label="Chế độ lặp lại", emoji="🔁",
                        value=PlayerControls.loop_mode,
                        description="Kích hoạt/Vô hiệu hóa nhạc/Hàng đợi lặp lại."
                    ),
                    disnake.SelectOption(
                        label=("Vô hiệu hóa" if player.autoplay else "Kích hoạt") + " chế độ tự thêm nhạc", emoji="🔄",
                        value=PlayerControls.autoplay,
                        description="Hệ thống bổ sung âm nhạc tự động khi dòng trống."
                    ),
                    disnake.SelectOption(
                        label="Nightcore", emoji="🇳",
                        value=PlayerControls.nightcore,
                        description="Kích hoạt/Vô hiệu hóa hiệu ứng Nightcore."
                    ),
                    disnake.SelectOption(
                        label="Kích hoạt/Vô hiệu hóa chế độ bị hạn chế", emoji="🔐",
                        value=PlayerControls.restrict_mode,
                        description="Chỉ DJ/Staff mới có thể sử dụng các lệnh bị hạn chế."
                    ),
                    disnake.SelectOption(
                        label="Danh sách bài hát", emoji="<:music_queue:703761160679194734>",
                        value=PlayerControls.queue,
                        description="Hiển thị cho bạn 1 danh sách mà chỉ có bạn mới nhìn thấy"
                    ),
                ]
            ),
        ]

        if player.mini_queue_feature:
            data["components"][5].options.append(
                disnake.SelectOption(
                    label="Danh sách phát mini", emoji="<:music_queue:703761160679194734>",
                    value=PlayerControls.miniqueue,
                    description="Kích hoạt/vô hiệu hóa danh sách phát mini của người chơi."
                )
            )

        if not player.static and not player.has_thread:
            data["components"][5].options.append(
                disnake.SelectOption(
                    label="Chủ đề yêu cầu bài hát", emoji="💬",
                    value=PlayerControls.song_request_thread,
                    description="Tạo một cuộc trò chuyện chủ đề/tạm thời để đặt hàng chỉ bằng cách chỉ bằng tên/liên kết."
                )
            )

        return data

def load():
    return DefaultSkin()

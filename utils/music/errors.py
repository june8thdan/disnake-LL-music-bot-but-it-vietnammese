# -*- coding: utf-8 -*-
import os
import traceback
from typing import Union, Optional

import disnake
from disnake.ext import commands
from disnake.utils import escape_mentions
from pymongo.errors import ServerSelectionTimeoutError

from utils.music.converters import time_format, perms_translations
from wavelink import WavelinkException, TrackNotFound


class PoolException(commands.CheckFailure):
    pass

class ArgumentParsingError(commands.CommandError):
    def __init__(self, message):
        super().__init__(escape_mentions(message))

class GenericError(commands.CheckFailure):

    def __init__(self, text: str, *, self_delete: int = None, delete_original: Optional[int] = None):
        self.text = text
        self.self_delete = self_delete
        self.delete_original = delete_original


class EmptyFavIntegration(commands.CheckFailure):
    pass

class MissingSpotifyClient(commands.CheckFailure):
    pass


class NoPlayer(commands.CheckFailure):
    pass


class NoVoice(commands.CheckFailure):
    pass


class MissingVoicePerms(commands.CheckFailure):

    def __init__(self, voice_channel: Union[disnake.VoiceChannel, disnake.StageChannel]):
        self.voice_channel = voice_channel


class DiffVoiceChannel(commands.CheckFailure):
    pass


class NoSource(commands.CheckFailure):
    pass


class NotDJorStaff(commands.CheckFailure):
    pass


class NotRequester(commands.CheckFailure):
    pass


def parse_error(
        ctx: Union[disnake.ApplicationCommandInteraction, commands.Context, disnake.MessageInteraction],
        error: Exception
):

    error_txt = None

    kill_process = False

    components = []

    error = getattr(error, 'original', error)

    if isinstance(error, NotDJorStaff):
        error_txt = "**Bạn phải nằm trong danh sách DJ hoặc được phép quản lý các kênh ** " \
                    "Để sử dụng lệnh này.**"

    elif isinstance(error, MissingVoicePerms):
        error_txt = f"**Tôi không được phép kết nối/nói chuyện với kênh:** {error.voice_channel.mention}"

    elif isinstance(error, commands.NotOwner):
        error_txt = "**Chỉ nhà phát triển của tôi mới có thể sử dụng lệnh này**"

    elif isinstance(error, commands.BotMissingPermissions):
        error_txt = "Tôi không có các quyền sau để thực thi lệnh này: ```\n{}```" \
            .format(", ".join(perms_translations.get(perm, perm) for perm in error.missing_permissions))

    elif isinstance(error, commands.MissingPermissions):
        error_txt = "Bạn không có các quyền sau để thực hiện lệnh này: ```\n{}```" \
            .format(", ".join(perms_translations.get(perm, perm) for perm in error.missing_permissions))

    elif isinstance(error, GenericError):
        error_txt = error.text

    elif isinstance(error, NotRequester):
        error_txt = "**Bạn phải yêu cầu âm nhạc hiện tại hoặc nằm trong danh sách DJ hoặc có quyền" \
                    "** Quản lý các kênh ** để nhảy nhạc.**"

    elif isinstance(error, DiffVoiceChannel):
        error_txt = "**Bạn phải ở trên kênh thoại hiện tại của tôi để sử dụng lệnh này.**"

    elif isinstance(error, NoSource):
        error_txt = "**Hiện tại không có bài hát trong máy nghe nhạc.**"

    elif isinstance(error, NoVoice):
        error_txt = "**Bạn phải tham gia một kênh thoại để sử dụng lệnh này.**"

    elif isinstance(error, NoPlayer):
        try:
            error_txt = f"**Không có người chơi đang hoạt động trên kênh {ctx.author.voice.channel.mention}.**"
        except AttributeError:
            error_txt = "**Không có trình phát nào được khởi tạo trên máy chủ.**"

    elif isinstance(error, commands.UserInputError) and ctx.command.usage:

        prefix = ctx.prefix if str(ctx.me.id) not in ctx.prefix else f"@{ctx.me.display_name} "

        error_txt = "### Bạn đã sử dụng lệnh không chính xác.\n" \
                    f'📘 **⠂Cách sử dụng:** ```\n{ctx.command.usage.replace("{prefix}", prefix).replace("{cmd}", ctx.command.name).replace("{parent}", ctx.command.full_parent_name)}```\n' \
                    f"⚠️ **⠂Lưu ý khi sử dụng đối số trong lệnh:** ```\n" \
                    f"[] = Bắt buộc | <> = Không bắt buộc```\n"

    elif isinstance(error, MissingSpotifyClient):
        error_txt = "**Liên kết Spotify không được hỗ trợ tại thời điểm này.**"

    elif isinstance(error, commands.NoPrivateMessage):
        error_txt = "Lệnh này không thể chạy trên tin nhắn riêng tư."

    elif isinstance(error, commands.CommandOnCooldown):
        remaing = int(error.retry_after)
        if remaing < 1:
            remaing = 1
        error_txt = "**Bạn phải đợi {} mới có thể sử dụng lệnh này.**".format(time_format(int(remaing) * 1000, use_names=True))

    elif isinstance(error, EmptyFavIntegration):

        if isinstance(ctx, disnake.MessageInteraction):
            error_txt = "**Bạn không có dấu trang/tích hợp**\n\n" \
                         "`Nếu muốn, bạn có thể thêm dấu trang hoặc nhúng để sử dụng " \
                         "lần sau nút này. Để làm như vậy, bạn có thể nhấp vào một trong các nút bên dưới.`"
        else:
            error_txt = "**Bạn đã sử dụng lệnh mà không bao gồm tên hoặc liên kết của bài hát hoặc video và bạn không có " \
                         "yêu thích hoặc tích hợp để sử dụng lệnh này theo cách này một cách trực tiếp...**\n\n" \
                         "`Nếu muốn, bạn có thể thêm dấu trang hoặc nhúng để sử dụng " \
                         "lệnh mà không bao gồm tên hoặc liên kết. Bạn có thể làm như vậy bằng cách nhấp vào một trong các nút bên dưới.`"

        components = [
            disnake.ui.Button(label="Mở trình quản lý yêu thích",
                              custom_id="musicplayer_fav_manager", emoji="⭐"),
            disnake.ui.Button(label="Mở Trình quản lý tích hợp",
                              custom_id="musicplayer_integration_manager", emoji="💠")
        ]

    elif isinstance(error, commands.MaxConcurrencyReached):
        txt = f"{error.number} vezes " if error.number > 1 else ''
        txt = {
            commands.BucketType.member: f"Bạn đã sử dụng lệnh này {txt}không phải máy chủ",
            commands.BucketType.guild: f"Lệnh này đã được sử dụng {txt}không phải máy chủ",
            commands.BucketType.user: f"Bạn đã sử dụng lệnh này {txt}",
            commands.BucketType.channel: f"Bạn đã sử dụng lệnh này rồi {txt}no canal atual",
            commands.BucketType.category: f"Bạn đã sử dụng lệnh này rồi {txt}na categoria do canal atual",
            commands.BucketType.role: f"Bạn đã sử dụng lệnh này rồi {txt}por um membro que possui o cargo permitido",
            commands.BucketType.default: f"Bạn đã sử dụng lệnh này rồi {txt}por alguém"
        }

        error_txt = f"{ctx.author.mention} **{txt[error.per]} Và nó đã không có{'s' if error.number > 1 else ''} " \
                    f"sử dụng{'s' if error.number > 1 else ''} hoàn thành{'s' if error.number > 1 else ''}!**"

    elif isinstance(error, TrackNotFound):
        error_txt = "**Không có kết quả cho tìm kiếm của bạn...**"

    if isinstance(error, ServerSelectionTimeoutError) and os.environ.get("REPL_SLUG"):
        error_txt = "Đã phát hiện lỗi dns trong repl.it khiến tôi không thể kết nối với cơ sở dữ liệu của mình" \
                     "từ mongo/atlas. Tôi sẽ khởi động lại và sẽ sớm hoạt động trở lại..."
        kill_process = True

    elif isinstance(error, WavelinkException):
        if "Unknown file format" in (wave_error := str(error)):
            error_txt = "**Không hỗ trợ cho liên kết được chỉ định...**"
        elif "This video is not available" in wave_error:
            error_txt = "**Video này không có sẵn hoặc riêng tư...**"
        elif "The playlist does not exist" in wave_error:
            error_txt = "**Danh sách phát không tồn tại (hoặc là riêng tư).**"
        elif "not made this video available in your country" in wave_error.lower() or \
                "who has blocked it in your country on copyright grounds" in wave_error.lower():
            error_txt = "**Nội dung của liên kết này không có sẵn trong khu vực nơi tôi đang làm việc...**"

    if not error_txt:
        full_error_txt = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        print(full_error_txt)
    else:
        full_error_txt = ""

    return error_txt, full_error_txt, kill_process, components
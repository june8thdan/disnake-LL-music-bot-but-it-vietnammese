# -*- coding: utf-8 -*-
from __future__ import annotations
import datetime
import random
import uuid
from itertools import cycle
from urllib.parse import quote

import disnake
import asyncio
import wavelink
from urllib import parse
from utils.music.converters import fix_characters, time_format, get_button_style
from utils.music.skin_utils import skin_converter
from utils.music.filters import AudioFilter
from utils.db import DBModel
from utils.others import send_idle_embed, PlayerControls
import traceback
from collections import deque
from typing import Optional, Union, TYPE_CHECKING, List

if TYPE_CHECKING:
    from utils.client import BotCore

exclude_tags = ["remix", "edit", "extend"]


class PartialPlaylist:

    __slots__ = ('data', 'url', 'tracks')

    def __init__(self, data: dict, url: str):
        self.data = data
        self.url = url
        self.tracks = []

    @property
    def name(self):
        try:
            return self.data["playlistInfo"]["name"]
        except KeyError:
            return


class PartialTrack:

    __slots__ = ('id', 'thumb', 'source_name', 'info', 'playlist', 'unique_id', 'ytid')

    def __init__(self, *, uri: str = "", title: str = "", author="", thumb: str = "", duration: int = 0,
                 requester: int = 0, track_loops: int = 0, source_name: str = "", autoplay: bool = False,
                 info: dict = None, playlist: PartialPlaylist = None):

        self.info = info or {
            "author": fix_characters(author)[:97],
            "title": title[:97],
            "uri": uri,
            "length": duration,
            "isStream": False,
            "isSeekable": True,
            "sourceName": source_name,
            "extra": {
                "requester": requester,
                "track_loops": track_loops,
                "thumb": thumb,
                "autoplay": autoplay
            }
        }

        self.id = ""
        self.ytid = ""
        self.unique_id = str(uuid.uuid4().hex)[:10]
        self.thumb = self.info["extra"]["thumb"]
        self.playlist: Optional[PartialPlaylist] = playlist

    def __repr__(self):
        return f"{self.info['sourceName']} - {self.duration} - {self.authors_string} - {self.title}"

    @property
    def uri(self) -> str:
        return self.info["uri"]

    @property
    def search_uri(self):
        return f"https://www.youtube.com/results?search_query={quote(self.title)}"

    @property
    def title(self) -> str:
        return f"{self.author} - {self.single_title}"

    @property
    def single_title(self) -> str:
        return self.info["title"]

    @property
    def author(self) -> str:
        return self.info["author"]

    @property
    def authors_string(self) -> str:
        try:
            return ", ".join(self.info["extra"]["authors"])
        except KeyError:
            return self.author

    @property
    def authors_md(self) -> str:
        try:
            return self.info["extra"]["authors_md"]
        except KeyError:
            return ""

    @property
    def authors(self) -> List[str]:
        try:
            return self.info["extra"]["authors"]
        except KeyError:
            return [self.author]

    @property
    def requester(self) -> int:
        return self.info["extra"]["requester"]

    @property
    def autoplay(self) -> bool:
        try:
            return self.info["extra"]["autoplay"]
        except KeyError:
            return False

    @property
    def track_loops(self) -> int:
        return self.info["extra"]["track_loops"]

    @property
    def is_stream(self) -> bool:
        return self.info["isStream"]

    @property
    def duration(self) -> int:
        return self.info["length"]

    @property
    def album_name(self) -> str:
        try:
            return self.info["extra"]["album"]["name"]
        except KeyError:
            return ""

    @property
    def album_url(self) -> str:
        try:
            return self.info["extra"]["album"]["url"]
        except KeyError:
            return ""

    @property
    def playlist_name(self) -> str:
        try:
            return self.playlist.name[:97]
        except AttributeError:
            return ""

    @property
    def playlist_url(self) -> str:
        try:
            return self.playlist.url
        except AttributeError:
            return ""


class LavalinkPlaylist:

    __slots__ = ('data', 'url', 'tracks')

    def __init__(self, data: dict, **kwargs):
        self.data = data
        self.url = kwargs.pop("url")
        try:
            if self.data['tracks'][0]['info'].get("sourceName") == "youtube":
                self.url = f"https://www.youtube.com/playlist?list={parse.parse_qs(parse.urlparse(self.url).query)['list'][0]}"
        except IndexError:
            pass
        self.tracks = [LavalinkTrack(
            id_=track['track'], info=track['info'], playlist=self, **kwargs) for track in data['tracks']]

    @property
    def name(self):
        return self.data["playlistInfo"]["name"]


class LavalinkTrack(wavelink.Track):

    __slots__ = ('extra', 'playlist', 'unique_id')

    def __init__(self, *args, **kwargs):
        try:
            args[1]['title'] = fix_characters(args[1]['title'])[:97]
        except IndexError:
            pass
        super().__init__(*args, **kwargs)
        self.title = fix_characters(self.title)
        self.info["title"] = self.title
        self.unique_id = str(uuid.uuid4().hex)[:10]

        try:
            self.info['sourceName']
        except:
            self.info['sourceName'] = 'LavalinkTrack'

        try:
            self.info["extra"]
        except KeyError:
            self.info["extra"] = {
                "track_loops": kwargs.pop('track_loops', 0),
                "requester": kwargs.pop('requester', ''),
                "autoplay": kwargs.pop("autoplay", '')
            }

        self.playlist: Optional[LavalinkPlaylist] = kwargs.pop(
            "playlist", None)

        if self.info["sourceName"] == "youtube":
            self.info["extra"]["thumb"] = f"https://img.youtube.com/vi/{self.ytid}/mqdefault.jpg"
            if "list=" not in self.uri:
                try:
                    self.uri = f"{self.uri}&list={parse.parse_qs(parse.urlparse(self.playlist_url).query)['list'][0]}"
                    self.info["uri"] = self.uri
                except KeyError:
                    pass

        elif self.info["sourceName"] == "soundcloud":

            self.info["extra"]["thumb"] = self.info.get(
                "artworkUrl", "").replace('large.jpg', 't500x500.jpg')

            if "?in=" not in self.uri:
                try:
                    self.uri = f"{self.uri}?in=" + self.playlist_url.split("soundcloud.com/")[1]
                    self.info["uri"] = self.uri
                except:
                    pass

        else:
            self.info["extra"]["thumb"] = self.info.get("artworkUrl", "")

        self.thumb = self.info["extra"]["thumb"] or ""

    def __repr__(self):
        return f"{self.info['sourceName']} - {self.duration if not self.is_stream else 'stream'} - {self.authors_string} - {self.title}"

    @property
    def single_title(self) -> str:
        return self.title

    @property
    def search_uri(self):
        return f"https://www.youtube.com/results?search_query={quote(self.title)}"

    @property
    def authors_md(self) -> str:
        return f"`{self.author}`"

    @property
    def authors_string(self) -> str:
        return f"{self.author}"

    @property
    def album_name(self) -> str:
        try:
            return self.info["extra"]["album"]["name"]
        except KeyError:
            return ""

    @property
    def album_url(self) -> str:
        try:
            return self.info["extra"]["album"]["url"]
        except KeyError:
            return ""

    @property
    def requester(self) -> int:
        return self.info["extra"]["requester"]

    @property
    def autoplay(self) -> bool:
        try:
            return self.info["extra"]["autoplay"]
        except KeyError:
            return False

    @property
    def track_loops(self) -> int:
        return self.info["extra"]["track_loops"]

    @property
    def playlist_name(self) -> str:
        try:
            return self.playlist.name[:97]
        except AttributeError:
            return ""

    @property
    def playlist_url(self) -> str:
        try:
            return self.playlist.url
        except AttributeError:
            return ""


class LavalinkPlayer(wavelink.Player):

    bot: BotCore

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.volume = kwargs.get("volume", 100)
        self.guild: disnake.Guild = kwargs.pop('guild')
        self.text_channel: Union[disnake.TextChannel,
                                 disnake.VoiceChannel, disnake.Thread] = kwargs.pop('channel')
        self.message: Optional[disnake.Message] = kwargs.pop('message', None)
        self.static: bool = kwargs.pop('static', False)
        self.skin: str = kwargs.pop("skin", None) or self.bot.default_skin
        self.skin_static: str = kwargs.pop("skin_static", None) or self.bot.default_static_skin
        self.custom_skin_data = kwargs.pop("custom_skin_data", {})
        self.custom_skin_static_data = kwargs.pop("custom_skin_static_data", {})
        self.queue: deque = deque()
        self.played: deque = deque(maxlen=20)
        self.queue_autoplay: deque = deque(maxlen=30)
        self.failed_tracks: deque = deque(maxlen=30)
        self.autoplay: bool = kwargs.pop("autoplay", False)
        self.nightcore: bool = False
        self.loop = False
        self.last_track: Optional[LavalinkTrack] = None
        self.locked: bool = False
        self.is_previows_music: bool = False
        self.interaction_cooldown: bool = False
        self.votes: set = set()
        self.dj: set = set()
        self.player_creator: Optional[int] = kwargs.pop('player_creator', None)
        self.filters: dict = {}
        self.idle_task: Optional[asyncio.Task] = None
        self.members_timeout_task: Optional[asyncio.Task] = None
        self.idle_timeout = self.bot.config["IDLE_TIMEOUT"]
        self.idle_endtime: Optional[datetime.datetime] = None
        self.hint_rate = self.bot.config["HINT_RATE"]
        self.command_log: str = ""
        self.command_log_emoji: str = ""
        self.is_closing: bool = False
        self.last_message_id: Optional[int] = kwargs.pop("last_message_id", None)
        self.keep_connected: bool = kwargs.pop("keep_connected", False)
        self.update: bool = False
        self.updating: bool = False
        self.stage_title_event = False
        self.stage_title_template = kwargs.pop("stage_title_template", None) or "Tocando: {track.title} | {track.author}"
        self.last_stage_title = ""
        self.auto_update: int = 0
        self.listen_along_invite = kwargs.pop("listen_along_invite", "")
        self.message_updater_task: Optional[asyncio.Task] = None
        # limitar apenas para dj's e staff's
        self.restrict_mode = kwargs.pop('restrict_mode', False)
        self.ignore_np_once = False  # não invocar player controller em determinadas situações
        self.allowed_mentions = disnake.AllowedMentions(users=False, everyone=False, roles=False)
        self.uptime = kwargs.pop("uptime", None) or int(disnake.utils.utcnow().timestamp())
        # ativar/desativar modo controller (apenas para uso em skins)
        self.controller_mode = True
        self.bot.loop.create_task(self.channel_cleanup())
        self.mini_queue_feature = False
        self.mini_queue_enabled = False
        self.is_resuming = False
        self.is_purging = False
        self.auto_pause = False

        self.last_channel: Optional[disnake.VoiceChannel] = None

        self._rpc_update_task: Optional[asyncio.Task] = None

        self.start_time = disnake.utils.utcnow()

        self.temp_embed: Optional[disnake.Embed] = None
        self.prefix_info = kwargs.pop("prefix", "")

        self.initial_hints = [
            f"Você pode alterar a skin/aparência do player usando o comando /change_skin ou {self.prefix_info}skin "
            f"(Apenas membros com permissão de gerenciar servidor pode usar esse comando).",

            f"Vcoê pode criar links favoritos para ter fácil acesso usá-los no comando /play ou {self.prefix_info}play "
            f"sem ter necessidade de copiar e colar os links no comando. Experimente usando o comando /fav_manager ou "
            f"{self.prefix_info}favmanager.",
        ]

        if self.bot.config["USE_YTDL"] or self.bot.spotify:
            self.initial_hints.append(
                "Você pode adicionar/integrar link de canais e perfis do youtube, soundcloud e spotify para tocar "
                "uma playlist pública que tem nesses canais/perfis de forma bem conveniente. "
                f"Experimente usando o comando /integrations ou {self.prefix_info}integrations."
            )

        try:
            self.initial_hints.extend(kwargs.pop("extra_hints"))
        except:
            pass

        if self.volume != 100:
            self.bot.loop.create_task(self.set_volume(self.volume))

        self.hints: cycle = []
        self.current_hint: str = ""
        self.last_data: dict = {}
        self.setup_features()
        self.setup_hints()

        self.bot.dispatch("player_create", player=self)

    def __str__(self) -> str:
        return f"Servidor de música atual: {self.node.identifier}"

    def __repr__(self):
        return f"<volume={self.volume} " \
               f"current_position={time_format(self.position) if self.position else 'Idling'} " \
               f"queue={len(self.queue)} loop={self.loop} EQ=\"{self.eq}\" guild=\"{self.guild.name}\" " \
               f"node=\"{self.node.identifier}\" keep_connected=\"{self.keep_connected}\">"

    @property
    def has_thread(self):
        return self.message and self.message.thread and not (self.message.thread.locked or self.message.thread.archived)

    @property
    def controller_link(self):
        try:
            if self.controller_mode:
                return f" [`🎛️`]({self.message.jump_url})"
        except AttributeError:
            pass
        return ""

    async def channel_cleanup(self):

        try:
            parent = self.text_channel.parent
        except AttributeError:
            pass
        else:
            if isinstance(parent, disnake.ForumChannel) and self.text_channel.owner_id == self.bot.user.id and \
                    self.text_channel.message_count > 1:
                try:
                    await self.text_channel.purge(check=lambda m: m.channel.id != m.id and (not m.pinned or not m.is_system()))
                except:
                    pass
                return

        try:
            self.last_message_id = int(self.last_message_id)
        except TypeError:
            return

        if self.static and self.last_message_id != self.text_channel.last_message_id:

            if isinstance(self.text_channel, disnake.Thread):
                check = (lambda m: m.id != self.last_message_id and (not m.pinned or not m.is_system()))
            else:
                check = (lambda m: m.id != self.last_message_id and not m.pinned)

            try:
                await self.text_channel.purge(check=check)
            except:
                traceback.print_exc()
                pass


    async def connect(self, channel_id: int, self_mute: bool = False, self_deaf: bool = False):
        self.last_channel = self.bot.get_channel(channel_id)
        await super().connect(channel_id, self_mute=self_mute, self_deaf=True)

    def process_hint(self):
        if random.choice([x for x in range(self.hint_rate)]) == 0:
            self.current_hint = next(self.hints)
        else:
            self.current_hint = ""

    def setup_features(self):

        try:
            (self.bot.player_static_skins[self.skin_static]
             if self.static else self.bot.player_skins[self.skin]).setup_features(self)
        except:
            # linha temporária para resolver possíveis problemas com skins custom criadas por usuarios antes desse commit.
            self.auto_update = 0
            self.controller_mode = True

    def setup_hints(self):

        hints = list(self.initial_hints)

        if self.static:
            hints.append("É possível fixar músicas/playlists na mensagem do player quando tiver no modo de "
                         "espera/oscioso pra permitir membros ouvi-las de forma pública. Pra isso use o "
                         f"comando /server_playlist ou {self.prefix_info}serverplaylist (apenas membros com permissão de gerenciar "
                         "servidor pode usar esse comando).")

        elif self.bot.intents.message_content and self.controller_mode:
            hints.append("Ao criar uma conversa/thread na mensagem do player, será ativado o modo de song-request "
                         "nela (possibilitando pedir música apenas enviando o nome/link da música na conversa).")

        if len([b for b in self.bot.pool.bots if b.appinfo and b.appinfo.bot_public]) > 1:
            hints.append("É possível ter bots de música adicionais no servidor compartilhando todos os seus favoritos/"
                         "integrações e funcionando com um único prefixo e comando slash de apenas um bot. "
                         f"Você pode usar o comando /invite ou {self.prefix_info}invite para adicioná-los.")

        if self.controller_mode:
            hints.append(
                "Ao clicar nesse emoji 🎛️ das mensagens de alguns comandos você será redirecionado para o player-controller."
            )

        random.shuffle(hints)
        self.hints = cycle(hints)

    async def members_timeout(self, check: bool, force: bool = False):

        if self.auto_pause and self.paused:
            if self.current:
                try:
                    await self.resolve_track(self.current)
                    self.paused = False
                    await self.play(self.current, start=self.position)
                except Exception:
                    traceback.print_exc()
            self.auto_pause = False
            update_log = True

        else:
            update_log = False

        if check:

            if update_log:
                self.set_command_log(emoji="🔰", text="A música foi retomada da pausa automática.")
                if self.current:
                    await self.invoke_np(rpc_update=True)
                else:
                    await self.process_next()
            return

        if not force:
            await asyncio.sleep(self.idle_timeout)

        if self.keep_connected:

            if self.paused:
                return

            await self.set_pause(True)

            self.auto_pause = True
            self.set_command_log(text=f"O player foi pausado por falta de membros no canal. A "
                                      f"música será retomada automaticamente quando um membro entrar no canal "
                                      f"<#{self.channel_id}>.", emoji="⚠️")
            await self.invoke_np()

        else:
            msg = f"**O player foi desligado por falta de membros no canal" + (f"<#{self.guild.me.voice.channel.id}>"
                                                                               if self.guild.me.voice else '') + "...**"
            self.command_log = msg
            if not self.static and not self.has_thread:
                embed = disnake.Embed(
                    description=msg, color=self.bot.get_color(self.guild.me))
                try:
                    await self.text_channel.send(embed=embed, allowed_mentions=self.allowed_mentions)
                except:
                    pass

            await self.destroy()

    async def get_autoqueue_tracks(self):

        try:
            return self.queue_autoplay.popleft()
        except:
            pass

        if self.locked:
            return

        try:
            track = self.current or self.last_track
        except:
            track = None

        if not track or not track.ytid or track.is_stream or track.duration < 90000:

            for t in self.played + self.queue_autoplay:
                if t.ytid and not t.is_stream and t.duration >= 90000:
                    track = t
                    break

        search_url = ""
        tracks = []

        if track and track.ytid:
            search_url =  f'https://www.youtube.com/watch?v={track.ytid}&list=RD{track.ytid}'
        else:
            try:
                track = self.played[0]
            except IndexError:
                try:
                    track = self.queue_autoplay[-1]
                except:
                    track = None

            if not track:
                track = self.current or self.last_track

            if track:
                search_url = f"ytmsearch:{track.author}"

        if search_url:

            self.locked = True

            retries = 3
            exception = None

            while retries:

                try:
                    tracks = await self.node.get_tracks(search_url)

                    try:
                        tracks = tracks.tracks
                    except AttributeError:
                        pass

                    if search_url.startswith("ytmsearch:"):
                        tracks.pop(0)

                    break

                except wavelink.TrackLoadError as e:
                    traceback.print_exc()
                    exception = e
                    if e.message == "Could not find tracks from mix.":
                        break
                except Exception as e:
                    traceback.print_exc()
                    exception = e

                retries -= 1

            if not tracks:
                self.locked = False

                if isinstance(exception, wavelink.TrackLoadError):
                    error_msg = f"**Causa:** ```java\n{exception.cause}```\n" \
                                f"**Mensagem:** `\n{exception.message}`\n" \
                                f"**Nível:** `{exception.severity}`\n" \
                                f"**Servidor de música:** `{self.node.identifier}`"
                else:
                    error_msg = f"**Detalhes:** ```py\n{repr(exception)}```"

                try:
                    embed = disnake.Embed(
                        description=f"**Falha ao obter dados do autoplay:\n"
                                    f"[{track.title}]({track.uri or track.search_uri})**\n"
                                    f"{error_msg}",
                        color=disnake.Colour.red())
                    await self.text_channel.send(embed=embed, delete_after=10)
                except:
                    traceback.print_exc()
                await asyncio.sleep(7)
                return

        if track:

            info = {
                "title": track.title,
                "uri": track.uri
            }

            tracks_final = []

            for t in tracks:

                if t.is_stream:
                    continue

                if t.duration < 90000:
                    continue

                lavalink_track = LavalinkTrack(id_=t.id, info=t.info, autoplay=True, requester=self.bot.user.id)
                lavalink_track.info["extra"]["related"] = info
                tracks_final.append(lavalink_track)

            tracks.clear()
            self.queue_autoplay.extend(tracks_final)

        try:
            return self.queue_autoplay.popleft()
        except:
            return None

    async def process_next(self, start_position: Union[int, float] = 0, inter: disnake.MessageInteraction = None):

        if self.locked or self.is_closing or self.auto_pause:
            return

        if not self.is_connected:
            self.bot.loop.create_task(self.destroy(force=True))
            return

        try:
            self.idle_task.cancel()
            self.idle_task = None
        except:
            pass

        if len(self.queue):
            track = self.queue.popleft()
            clear_autoqueue = bool(track.ytid)

        else:

            try:

                clear_autoqueue = False

                track = None

                if self.autoplay:
                    try:
                        track = await self.get_autoqueue_tracks()
                    except:
                        traceback.print_exc()

                if not track:
                    await self.stop()
                    self.idle_endtime = disnake.utils.utcnow() + datetime.timedelta(seconds=self.idle_timeout)
                    self.last_track = None
                    self.idle_task = self.bot.loop.create_task(self.idling_mode())
                    return

            except Exception as e:
                clear_autoqueue = False
                traceback.print_exc()
                print("test", type(e))
                track = None

        if not track:
            await self.process_next()
            return

        self.locked = True

        if isinstance(track, PartialTrack):

            if not track.id:
                try:
                    await self.resolve_track(track)
                except Exception as e:
                    try:
                        await self.text_channel.send(
                            embed=disnake.Embed(
                                description=f"Houve um problema ao tentar processar a música [{track.title}]({track.uri})... "
                                            f"```py\n{repr(e)}```",
                                color=self.bot.get_color()
                            )
                        )
                    except:
                        traceback.print_exc()

                    self.locked = False

                    await self.process_next()
                    return

            if not track.id:
                try:
                    await self.text_channel.send(
                        embed=disnake.Embed(
                            description=f"A música [{track.title}]({track.uri}) não está disponível...\n"
                                        f"Pulando para a próxima música...",
                            color=self.bot.get_color()
                        ), delete_after=30
                    )
                except:
                    traceback.print_exc()

                self.locked = False

                await self.process_next()
                return

        elif not track.id:

            t = await self.node.get_tracks(track.uri)

            if not t:
                try:
                    await self.text_channel.send(
                        embed=disnake.Embed(
                            description=f"A música [{track.title}]({track.uri}) não está disponível...\n"
                                        f"Pulando para a próxima música...",
                            color=self.bot.get_color()
                        ), delete_after=30
                    )
                except:
                    traceback.print_exc()

                self.locked = False

                await self.process_next()
                return

            track.id = t[0].id

        if clear_autoqueue:
            self.queue_autoplay.clear()

        self.last_track = track

        self.is_previows_music = False

        self.locked = False
        self.start_time = disnake.utils.utcnow()

        self.current = track
        self.last_update = 0
        self.last_position = 0
        self.position_timestamp = 0
        self.paused = False

        self.process_hint()

        # TODO: rever essa parte caso adicione função de ativar track loops em músicas da fila
        if self.loop != "current" or (not self.controller_mode and self.current.track_loops == 0):

            await self.invoke_np(
                interaction=inter,
                force=True if (self.static or not self.loop or not self.is_last_message()) else False,
                rpc_update=True)

        await self.play(track, start=start_position if not track.is_stream else 0)

    async def process_idle_message(self):

        if not self.static and not self.controller_mode:

            try:
                cmds = " | ".join(f"{self.bot.get_slash_command(c).name}" for c in [
                                  'play', 'back', 'readd_songs', 'stop'])

                embed = disnake.Embed(
                    description=f"**As músicas acabaram... Use um dos comandos abaixo para adicionar músicas ou parar "
                                f"o player.**\n\n`{cmds}`\n\n"
                                f"**Nota:** `O Player será desligado automaticamente` "
                                f"<t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=self.idle_timeout)).timestamp())}:R> "
                                f"`caso nenhum comando seja usado...`",
                    color=self.bot.get_color(self.guild.me)
                )

                embed.set_thumbnail(
                    url=self.guild.me.display_avatar.replace(size=256).url)

                self.message = await self.text_channel.send(embed=embed)
            except Exception:
                traceback.print_exc()
            return

        controller_opts = [
            disnake.SelectOption(
                emoji="<:add_music:588172015760965654>", value=PlayerControls.add_song, label="Adicionar música",
                description=f"Tocar nova música/playlist."
            ),
            disnake.SelectOption(
                emoji="⭐", value=PlayerControls.enqueue_fav, label="Adicionar favorito",
                description=f"Adicionar favorito na fila."
            ),
        ]

        if (played := len(self.played)) or self.last_track:
            controller_opts.append(
                disnake.SelectOption(
                    emoji="⏮️", value=PlayerControls.back, label="Voltar",
                    description=f"Ouvir novamente: {self.played[-1].title[:31]}"
                )
            )

        if played > 1:
            controller_opts.append(
                disnake.SelectOption(
                    emoji="↪️", value=PlayerControls.readd, label="Tocar novamente",
                    description=f"Tocar todas as músicas novamente ({played})"
                )
            )

        controller_opts.append(
            disnake.SelectOption(
                emoji="🛑", value=PlayerControls.stop, label="Finalizar",
                description=f"Finalizar o player e me desconectar do canal."
            ),
        )

        components = [
            disnake.ui.Select(
                placeholder="Executar uma ação:", options=controller_opts,
                custom_id="musicplayer_dropdown_idle", min_values=0, max_values=1
            )
        ]

        guild_data = await self.bot.get_data(self.guild.id, db_name=DBModel.guilds)

        opts = [disnake.SelectOption(label=k, value=k, description=v['description']) for k, v in
                guild_data["player_controller"]["fav_links"].items()]

        if opts:

            components.append(
                disnake.ui.Select(
                    placeholder="Tocar música/playlist do servidor.",
                    options=opts, custom_id="player_guild_pin"
                )
            )

        embed = disnake.Embed(
            description=f"**Não há músicas na fila... Adicione uma música ou use uma das opções abaixo.\n\n"
                        f"Nota:** `O Player será desligado automaticamente` "
                        f"<t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=self.idle_timeout)).timestamp())}:R> "
                        f"`caso nenhuma ação seja executada...`",
            color=self.bot.get_color(self.guild.me)
        )

        kwargs = {
            "embed": embed,
            "content": None,
            "components": components,
            "allowed_mentions": self.allowed_mentions
        }

        try:
            if isinstance(self.text_channel.parent, disnake.ForumChannel) and self.static:
                kwargs["content"] = "💤 Aguardando por novas músicas..."
        except:
            pass

        try:
            if self.has_thread or self.static or self.text_channel.last_message_id == self.message.id:
                await self.message.edit(**kwargs)
                send_message = False
            else:
                send_message = True
        except AttributeError:
            send_message = True

        if send_message:
            try:
                await self.message.delete()
            except:
                pass
            self.message = await self.text_channel.send(**kwargs)

    async def idling_mode(self):

        await self.process_rpc(self.guild.me.voice.channel)

        await self.process_idle_message()

        try:
            await self.update_stage_topic()
        except:
            pass

        await asyncio.sleep(self.idle_timeout)

        msg = "💤 **⠂O player foi desligado por inatividade...**"

        if self.static or self.has_thread:
            self.command_log = msg
        else:
            embed = disnake.Embed(
                description=msg, color=self.bot.get_color(self.guild.me))
            self.bot.loop.create_task(self.text_channel.send(
                embed=embed, delete_after=120, allowed_mentions=self.allowed_mentions))

        self.bot.loop.create_task(self.destroy())

    def set_command_log(self, text="", emoji=""):
        self.command_log = text
        self.command_log_emoji = emoji

    async def update_stage_topic(self):

        if not self.guild.me.voice:
            await self.connect(self.last_channel.id)
            return

        if not isinstance(self.guild.me.voice.channel, disnake.StageChannel):
            return

        if not self.guild.me.guild_permissions.manage_guild:
            return

        if not self.stage_title_event:
            return

        if not self.current:
            msg = "Status: Aguardando por novas músicas."

        else:

            requester = self.guild.get_member(self.current.requester)

            if requester:
                requester_name = str(requester.display_name)
                requester_tag = str(requester.discriminator)
            else:
                requester_name = "Membro desconhecido"
                requester_tag = "????"

            msg = self.stage_title_template\
                .replace("{track.title}", self.current.single_title)\
                .replace("{track.author}", self.current.authors_string)\
                .replace("{track.duration}", time_format(self.current.duration) if not self.current.is_stream else "Livestream")\
                .replace("{track.source}", self.current.info.get("sourceName", "desconhecido"))\
                .replace("{track.playlist}", self.current.playlist_name or "Sem playlist")\
                .replace("{requester.name}", requester_name) \
                .replace("{requester.tag}", requester_tag) \
                .replace("{requester.id}", str(self.current.requester))

            if len(msg) > 110:
                msg = msg[:107] + "..."

        if not self.guild.me.voice.channel.instance:
            func = self.guild.me.voice.channel.create_instance
        elif msg == self.last_stage_title:
            self.last_stage_title = msg
            return
        else:
            func = self.guild.me.voice.channel.instance.edit

        await func(topic=msg)
        self.last_stage_title = msg

    def start_message_updater_task(self):
        try:
            self.message_updater_task.cancel()
        except AttributeError:
            pass
        self.message_updater_task = self.bot.loop.create_task(self.message_updater())

    async def invoke_np(self, force=False, interaction=None, rpc_update=False):

        if not self.current or self.updating:

            try:
                if not interaction.response.is_done():
                    await interaction.response.defer()
            except:
                pass

            return

        if rpc_update:
            await self.process_rpc()

        try:
            if self.static:
                if self.skin_static.startswith("> custom_skin: "):
                    data = skin_converter(self.custom_skin_static_data[self.skin_static[15:]], player=self)
                else:
                    data = self.bot.player_static_skins[self.skin_static].load(self)

            else:
                if self.skin.startswith("> custom_skin: "):
                    data = skin_converter(self.custom_skin_data[self.skin[15:]], player=self)
                else:
                    data = self.bot.player_skins[self.skin].load(self)
        except OverflowError:
            await self.process_next()
            return

        if data == self.last_data:

            try:
                if not interaction.response.is_done():
                    await interaction.response.defer()
            except:
                pass
            return

        self.last_data = data

        if not self.controller_mode:

            self.message = None

            if self.temp_embed:
                self.last_data["embeds"].insert(0, self.temp_embed)
                self.temp_embed = None

            self.updating = True

            await self.text_channel.send(allowed_mentions=self.allowed_mentions, **self.last_data)

        else:

            # nenhum controle de botão foi definido na skin (será usado os botões padrões).
            if self.controller_mode and self.last_data.get("components") is None:

                # Aviso: Não modifique os components abaixo, prefira copiar uma das skins da pasta utils -> music -> skins
                # e deixá-la com outro nome (sem acentos, espaços, caracteres especiais) e modifique-as a seu gosto.
                # Caso queira deixar uma skin customizada por padrão adicione/modifique a config DEFAULT_SKIN="tuaskin"

                self.last_data["components"] = [
                    disnake.ui.Button(
                        emoji="⏯️", custom_id=PlayerControls.pause_resume, style=get_button_style(self.paused)),
                    disnake.ui.Button(
                        emoji="⏮️", custom_id=PlayerControls.back),
                    disnake.ui.Button(
                        emoji="⏹️", custom_id=PlayerControls.stop),
                    disnake.ui.Button(
                        emoji="⏭️", custom_id=PlayerControls.skip),
                    disnake.ui.Button(
                        emoji="<:music_queue:703761160679194734>", custom_id=PlayerControls.queue),
                    disnake.ui.Select(
                        placeholder="Mais opções:",
                        custom_id="musicplayer_dropdown_inter",
                        min_values=0, max_values=1,
                        options=[
                            disnake.SelectOption(
                                label="Adicionar música", emoji="<:add_music:588172015760965654>",
                                value=PlayerControls.add_song,
                                description="Adicionar uma música/playlist na fila."
                            ),
                            disnake.SelectOption(
                                label="Adicionar favorito", emoji="⭐",
                                value=PlayerControls.enqueue_fav,
                                description="Adicionar um de seus favoritos na fila."
                            ),
                            disnake.SelectOption(
                                label="Tocar do inicio", emoji="⏪",
                                value=PlayerControls.seek_to_start,
                                description="Voltar o tempo da música atual para o inicio."
                            ),
                            disnake.SelectOption(
                                label=f"Volume: {self.volume}%", emoji="🔊",
                                value=PlayerControls.volume,
                                description="Ajustar volume."
                            ),
                            disnake.SelectOption(
                                label="Misturar", emoji="🔀",
                                value=PlayerControls.shuffle,
                                description="Misturar as músicas da fila."
                            ),
                            disnake.SelectOption(
                                label="Readicionar", emoji="🎶",
                                value=PlayerControls.readd,
                                description="Readicionar as músicas tocadas de volta na fila."
                            ),
                            disnake.SelectOption(
                                label="Repetição", emoji="🔁",
                                value=PlayerControls.loop_mode,
                                description="Ativar/Desativar repetição da música/fila."
                            ),
                            disnake.SelectOption(
                                label=("Desativar" if self.nightcore else "Ativar") + " o efeito nightcore", emoji="🇳",
                                value=PlayerControls.nightcore,
                                description="Efeito que aumenta velocidade e tom da música."
                            ),
                            disnake.SelectOption(
                                label=("Desativar" if self.autoplay else "Ativar") + " a reprodução automática", emoji="🔄",
                                value=PlayerControls.autoplay,
                                description="Sistema de reprodução de música automática quando a fila tiver vazia."
                            ),
                            disnake.SelectOption(
                                label=("Desativar" if self.restrict_mode else "Ativar") + " o modo restrito",
                                emoji="🔐",
                                value=PlayerControls.restrict_mode,
                                description="Apenas DJ's/Staff's podem usar comandos restritos."
                            ),
                        ]
                    ),
                ]

                if self.mini_queue_feature:
                    self.last_data["components"][5].options.append(
                        disnake.SelectOption(
                            label="Mini-fila do player", emoji="<:music_queue:703761160679194734>",
                            value=PlayerControls.miniqueue,
                            description="Ativar/Desativar a mini-fila do player."
                        )
                    )

                if not self.static and not self.has_thread:
                    self.last_data["components"][5].options.append(
                        disnake.SelectOption(
                            label="Song-Request Thread", emoji="💬",
                            value=PlayerControls.song_request_thread,
                            description="Criar uma thread/conversa temporária para pedir músicas usando apenas o nome/link."
                        )
                    )

            self.updating = True

            try:
                if interaction.response.is_done():
                    await interaction.message.edit(allowed_mentions=self.allowed_mentions, **self.last_data)
                else:
                    await interaction.response.edit_message(allowed_mentions=self.allowed_mentions, **self.last_data)
                self.updating = False
                self.start_message_updater_task()
                return

            except Exception:
                if self.message and (self.ignore_np_once or self.has_thread or self.static or not force or self.is_last_message()):

                    self.ignore_np_once = False

                    try:

                        try:
                            await self.message.edit(allowed_mentions=self.allowed_mentions, **self.last_data)
                        except:
                            if not self.bot.get_channel(self.text_channel.id):
                                # canal não existe mais no servidor...
                                await self.destroy(force=True)
                                return

                        self.start_message_updater_task()
                        await self.update_stage_topic()
                        self.updating = False
                        return
                    except Exception as e:
                        self.updating = False
                        traceback.print_exc()
                        if self.static or self.has_thread:
                            self.set_command_log(
                                f"{(interaction.author.mention + ' ') if interaction else ''}houve um erro na interação: {repr(e)}", "⚠️")
                            self.update = True
                            return

            await self.destroy_message()

            try:
                self.message = await self.text_channel.send(allowed_mentions=self.allowed_mentions, **self.last_data)
            except:
                traceback.print_exc()

            self.start_message_updater_task()

        await self.update_stage_topic()

        self.updating = False

    async def set_pause(self, pause: bool) -> None:
        await super().set_pause(pause)

    async def destroy_message(self):

        try:
            self.message_updater_task.cancel()
        except:
            pass

        if not self.static and self.guild.me:
            try:
                await self.message.delete()
            except:
                pass

        self.message = None

    def is_last_message(self):

        try:
            return self.last_message_id == self.message.id
        except AttributeError:
            return

    async def message_updater(self):

        while True:

            if not self.controller_mode:
                pass

            elif self.auto_update:

                await asyncio.sleep(self.auto_update)

                try:
                    await self.invoke_np()
                except:
                    traceback.print_exc()

                continue

            elif self.update:

                try:
                    await self.invoke_np()
                except:
                    traceback.print_exc()

                self.update = False

                await asyncio.sleep(5)

            await asyncio.sleep(10)

    async def update_message(self, interaction: disnake.Interaction = None, force=False, rpc_update=False):

        if rpc_update:
            await self.process_rpc()

        if force or (interaction and not interaction.response.is_done()):
            if self.controller_mode:
                await self.invoke_np(interaction=interaction)

        else:
            self.update = True

    async def cleanup(self, inter: disnake.MessageInteraction = None):

        self.queue.clear()
        self.played.clear()

        try:
            vc = self.guild.voice_client.channel
        except:
            vc = self.last_channel

        await self.process_rpc(vc, close=True)

        try:
            await self.update_stage_topic()
        except:
            pass

        try:
            self.idle_task.cancel()
            self.idle_task = None
        except:
            pass

        try:
            self.message_updater_task.cancel()
        except:
            pass

        if self.guild.me:

            if self.static:
                try:
                    await send_idle_embed(inter or self.message, self.command_log, bot=self.bot)
                except:
                    pass

            else:

                if self.has_thread:

                    try:
                        await self.message.edit(
                            embed=disnake.Embed(
                                description=self.command_log,
                                color=self.bot.get_color(self.guild.me)
                            ), view=None, allowed_mentions=self.allowed_mentions
                        )
                        channel: disnake.Thread = self.bot.get_channel(self.message.id)
                        await channel.edit(archived=True, locked=True)
                    except Exception:
                        print(
                            f"Falha ao arquivar thread do servidor: {self.guild.name}\n{traceback.format_exc()}")

                elif inter:

                    await inter.response.edit_message(
                        content=None,
                        embed=disnake.Embed(
                            description=f"🛑 ⠂{self.command_log}",
                            color=self.bot.get_color(self.guild.me)),
                        components=[
                            disnake.ui.Button(
                                label="Pedir uma música", emoji="🎶", custom_id=PlayerControls.add_song),
                            disnake.ui.Button(
                                label="Tocar favorito/integração", emoji="⭐", custom_id=PlayerControls.enqueue_fav)

                        ]
                    )

                else:

                    await self.destroy_message()

        try:
            self.members_timeout_task.cancel()
        except:
            pass

    async def resolve_track(self, track: PartialTrack):

        if track.id:
            return

        try:

            try:
                to_search = track.info["search_uri"]
                check_duration = False
            except KeyError:
                to_search = f"{self.bot.config['SEARCH_PROVIDER']}:{track.single_title.replace(' - ', ' ')} - {track.authors_string}"
                check_duration = True

            try:
                tracks = (await self.node.get_tracks(to_search))
            except wavelink.TrackNotFound:
                tracks = None

            if not tracks and self.bot.config['SEARCH_PROVIDER'] not in ("ytsearch", "ytmsearch", "scsearch"):
                tracks = await self.node.get_tracks(f"ytsearch:{track.single_title.replace(' - ', ' ')} - {track.authors_string}")

            try:
                tracks = tracks.tracks
            except AttributeError:
                pass

            selected_track = None

            for t in tracks:

                if t.is_stream:
                    continue

                if any((i in t.title.lower() and i not in track.title.lower()) for i in exclude_tags):
                    continue

                if check_duration and ((t.duration - 10000) < track.duration < (t.duration + 10000)):
                    selected_track = t
                    break

            if not selected_track:
                selected_track = tracks[0]

            track.id = selected_track.id
            track.info["length"] = selected_track.duration

        except IndexError:
            return
        except Exception:
            traceback.print_exc()
            return

        return

    async def _send_rpc_data(self, users: List[int], stats: dict):

        for u in users:

            stats["user"] = u

            try:
                token = self.bot.pool.rpc_token_cache[u]
            except KeyError:
                data = await self.bot.get_global_data(id_=u, db_name=DBModel.users)
                token = data["token"]

            if self.bot.config["ENABLE_RPC_AUTH"] and not token:
                continue

            stats["token"] = token

            try:
                await self.bot.ws_client.send(stats)
            except Exception:
                print(traceback.format_exc())

    async def process_rpc(
            self,
            voice_channel: Union[disnake.VoiceChannel, disnake.StageChannel] = None,
            close=False,
            users: List[int] = None,
            wait: bool = False
    ):
        try:
            if not voice_channel and not close:

                try:
                    voice_channel = self.bot.get_channel(self.channel_id) or self.bot.get_channel(self.guild.voice_client.channel.id)
                except AttributeError:
                    voice_channel = self.last_channel

            if not users:
                try:
                    users = voice_channel.voice_states
                except AttributeError:
                    # TODO: Investigar possível bug ao mover o bot de canal pelo discord.
                    return

            thumb = self.bot.user.display_avatar.replace(
                size=512, static_format="png").url

            users = [u for u in users if u != self.bot.user.id]

            if close:

                stats = {
                    "op": "close",
                    "bot_id": self.bot.user.id,
                    "bot_name": str(self.bot.user),
                    "thumb": thumb,
                    "auth_enabled": self.bot.config["ENABLE_RPC_AUTH"]
                }

                if wait:
                    await self._send_rpc_data(users, stats)
                else:
                    try:
                        self._rpc_update_task.cancel()
                    except:
                        pass
                    self._rpc_update_task = self.bot.loop.create_task(self._send_rpc_data(users, stats))
                return

            if self.is_closing:
                return

            stats = {
                "op": "update",
                "track": None,
                "bot_id": self.bot.user.id,
                "bot_name": str(self.bot.user),
                "thumb": thumb,
                "auth_enabled": self.bot.config["ENABLE_RPC_AUTH"],
                "listen_along_invite": self.listen_along_invite
            }

            if not self.current:

                stats.update(
                    {
                        "op": "idle",
                        "bot_id": self.bot.user.id,
                        "invite_permissions": self.bot.config["INVITE_PERMISSIONS"],
                        "bot_name": str(self.bot.user),
                        "public": self.bot.appinfo.bot_public,
                        "support_server": self.bot.config["SUPPORT_SERVER"],
                    }
                )

                try:
                    stats["idle_endtime"] = int(self.idle_endtime.timestamp())
                except:
                    pass

            else:

                track: Union[LavalinkTrack, PartialTrack] = self.current

                stats["track"] = {
                    "source": track.info["sourceName"],
                    "thumb": track.thumb if len(track.thumb) < 257 else "",
                    "title": track.single_title,
                    "url": track.uri,
                    "author": track.authors_string,
                    "duration": track.duration,
                    "stream": track.is_stream,
                    "position": self.position,
                    "paused": self.is_paused,
                    "requester_id": track.requester,
                    "loop": self.current.track_loops or self.loop,
                    "queue": len(self.queue),
                    "247": self.keep_connected,
                    "autoplay": self.current.autoplay
                }

                if track.playlist_name:
                    stats["track"].update(
                        {
                            "playlist_name": track.playlist_name,
                            "playlist_url": track.playlist_url,
                        }
                    )

                if track.album_name:
                    stats["track"].update(
                        {
                            "album_name": track.album_name,
                            "album_url": track.album_url,
                        }
                    )

            if wait:
                await self._send_rpc_data(users, stats)
            else:

                try:
                    self._rpc_update_task.cancel()
                except:
                    pass

                self._rpc_update_task = self.bot.loop.create_task(self._send_rpc_data(users, stats))

        except Exception:
            traceback.print_exc()

    async def process_save_queue(self, create_task=True):

        cog = self.bot.get_cog("PlayerSession")

        if not cog:
            return

        try:
            self.queue_updater_task.cancel()
        except:
            pass

        await cog.save_info(self)

        if create_task:
            self.queue_updater_task = self.bot.loop.create_task(cog.queue_updater_task(self))

    async def track_end(self):

        self.votes.clear()

        self.locked = True

        await asyncio.sleep(0.5)

        if self.last_track:

            if self.loop == "current":
                self.queue.appendleft(self.last_track)
            elif self.is_previows_music:
                self.queue.insert(1, self.last_track)
                self.is_previows_music = False
            elif self.last_track.track_loops:
                self.last_track.info["extra"]["track_loops"] -= 1
                self.queue.insert(0, self.last_track)
            elif self.loop == "queue" or self.keep_connected:
                if self.is_previows_music:
                    self.queue.insert(1, self.last_track)
                    self.is_previows_music = False
                else:
                    self.queue.append(self.last_track)
            elif not self.last_track.autoplay:
                self.played.append(self.last_track)

        elif self.is_previows_music:
            self.is_previows_music = False

        self.locked = False

    async def destroy(self, *, force: bool = False, inter: disnake.MessageInteraction = None):

        await self.cleanup(inter)

        self.is_closing = True

        try:
            channel = self.guild.voice_client.channel
        except AttributeError:
            channel = self.last_channel

        if isinstance(channel, disnake.StageChannel) and self.stage_title_event and self.guild.me and self.guild.me.guild_permissions.manage_channels:

            if channel.instance:
                try:
                    await channel.instance.delete()
                except Exception:
                    traceback.print_exc()

        await super().destroy(force=force, guild=self.guild)

        self.bot.dispatch("player_destroy", player=self)

    #######################
    #### Filter Stuffs ####
    #######################

    async def change_node(self, identifier: str = None, force: bool = False):
        await super().change_node(identifier=identifier, force=force)
        await self.node._send(op="filters", **self.filters, guildId=str(self.guild_id))

    async def set_volume(self, vol: int) -> None:

        self.volume = max(min(vol, 1000), 0)
        await self.node._send(op='volume', guildId=str(self.guild_id), volume=self.volume)

    async def seek(self, position: int = 0) -> None:
        await super().seek(position=position)
        self.last_position = position

    async def set_distortion(self, sin_offset: float = 0, sin_scale: float = 1.0, cos_offset: float = 0,
                             cos_scale: float = 1.0, tan_offset: float = 0, tan_scale: float = 1.0,
                             offset: float = 0, scale: float = 1.0, enabled: bool = True):

        if enabled:
            return await self.set_filter(
                AudioFilter.distortion(sin_offset, sin_scale, cos_offset, cos_scale, tan_offset, tan_scale, offset,
                                       scale))

        try:
            del self.filters['distortion']
        except KeyError:
            pass

        await self.update_filters()

    async def set_timescale(self, speed: float = 1.0, pitch: float = 1.0, rate: float = 1.0, enabled: bool = True):
        if enabled:
            return await self.set_filter(AudioFilter.timescale(speed=speed, pitch=pitch, rate=rate))

        try:
            del self.filters['timescale']
        except KeyError:
            pass

        await self.update_filters()

    async def set_karaoke(self, level: float = 1.0, mono_level: float = 1.0, filter_band: float = 220.0,
                          filter_width: float = 100.0, enabled: bool = True):
        if enabled:
            return await self.set_filter(
                AudioFilter.karaoke(level=level, mono_level=mono_level, filter_band=filter_band,
                                    filter_width=filter_width))

        try:
            del self.filters['karaoke']
        except KeyError:
            pass

        await self.update_filters()

    async def set_tremolo(self, frequency: float = 2.0, depth: float = 0.0, enabled: bool = True):
        if enabled:
            return await self.set_filter(AudioFilter.tremolo(frequency=frequency, depth=depth))

        try:
            del self.filters['tremolo']
        except KeyError:
            pass

        await self.update_filters()

    async def set_vibrato(self, frequency: float = 2.0, depth: float = 0.0, enabled: bool = True):
        if enabled:
            return await self.set_filter(AudioFilter.vibrato(frequency=frequency, depth=depth))

        try:
            del self.filters['vibrato']
        except KeyError:
            pass

        await self.update_filters()

    async def set_rotation(self, sample_rate: int = 5, enabled: bool = True):
        if enabled:
            return await self.set_filter(AudioFilter.rotation(sample_rate=sample_rate))

        try:
            del self.filters['rotation']
        except KeyError:
            pass

        await self.update_filters()

    async def set_lowpass(self, smoothing: float = 20.0, enabled: bool = True):
        if enabled:
            return await self.set_filter(AudioFilter.low_pass(smoothing=smoothing))

        try:
            del self.filters['lowpass']
        except KeyError:
            pass

        await self.update_filters()

    async def set_channelmix(self, left_to_left: float = 1.0, left_to_right: float = 0, right_to_left: float = 0,
                             right_to_right: float = 1.0, enabled: bool = True):
        if enabled:
            return await self.set_filter(
                AudioFilter.channel_mix(left_to_left=left_to_left, left_to_right=left_to_right,
                                        right_to_left=right_to_left, right_to_right=right_to_right))

        try:
            del self.filters['channelmix']
        except KeyError:
            pass

        await self.update_filters()

    async def set_eq(self, equalizer: wavelink.Equalizer):

        await self.set_filter(AudioFilter.equalizer(bands=equalizer.eq))
        self._equalizer = equalizer

    async def update_filters(self):
        await self.node._send(op="filters", **self.filters, guildId=str(self.guild_id))

    async def set_filter(self, filter_type: AudioFilter):

        self.filters.update(filter_type.filter)
        await self.update_filters()

        return filter_type


def music_mode(bot: BotCore):
    return wavelink.Client(bot=bot)

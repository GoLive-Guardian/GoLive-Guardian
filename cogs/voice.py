from __future__ import annotations
from collections import defaultdict
from discord.ext import commands, tasks
from discord.utils import utcnow, format_dt
from typing import TYPE_CHECKING, Optional, Iterable
from utils import (
    get_stream_status,
    is_voice_channel,
    StreamerInfo,
    StreamerView,
    StreamConflictResolveView,
    BasicChannelInfo,
    ChannelInfo,
    SpawnViewFailed,
)

import asyncio
import discord
import logging
import random

if TYPE_CHECKING:
    from bot import GoLiveGuardian
    from utils import MongoClient, GoLiveGuildSetup


_log = logging.getLogger(__name__)


# noinspection SpellCheckingInspection
class Voice(commands.Cog):
    def __init__(self, app : GoLiveGuardian) -> None:
        self.app = app
        self.lock : asyncio.Lock = asyncio.Lock()

        # Pair of channel's id and channel info.
        # int would be channel_id
        self.channel_info : dict[int, ChannelInfo] = {}

        # this is used to ensure unhandled channels handled well.
        self.unhandled_channels : set[ChannelInfo] = set()

        # To prevent data inconsistency, all setup commands are unavailable until bot's channel task being done.
        self._check_init : bool = False

        self.event : asyncio.Event = asyncio.Event()
        self._channel_manager : asyncio.Task[None] = None
        self._get_unhandled_channels.start()

    @property
    def mongo(self) -> MongoClient:
        return self.app.pool

    @tasks.loop(count=1)
    async def _get_unhandled_channels(self):
        _log.info("Getting Data From DB")

        guilds = self.mongo.get_all_guilds_info(self.app.guilds)
        async for guild in guilds:
            if not guild.watch:
                continue

            info = guild.get_as_channel_info()
            self.unhandled_channels.update(info)

            _log.info(f"Found guild [%d] from DB and added [%d] unhandled channel(s)", guild.id, len(info))

        loop = self.app.loop
        loop.create_task(self.mongo._cleanup_db())
        self._channel_manager = loop.create_task(self._handle_conflict())

    @_get_unhandled_channels.before_loop
    async def before_get_unhandled_channels(self):
        await self.app.wait_until_ready()

    async def _handle_conflict(self) -> None:
        """It's used only once to handle Stream Conflicts after starting up.
        When a channel exceeds its Go Live stream limit, a message that requests to solve
        streamers' conflict is sent to the channel.

        The message updates when an event occurs related to the channel.
        if the channel is removed or changed bot can not see them,
        the conflict will be automatically resolved and its streamers won't be kicked from there.
        """

        while True:
            handled_info : list[ChannelInfo] = []
            removing_channel : list[ChannelInfo] = []
            count = 0

            for info in tuple(self.unhandled_channels):
                channel_id = info.id
                view: Optional[StreamConflictResolveView] = info.conflict_view

                if not info.watch :
                    handled_info.append(info)
                    if view:
                        view.stop()
                        info.conflict_view = None
                else:
                    try:
                        channel : discord.VoiceChannel = self.app.get_channel(channel_id) or await self.app.fetch_channel(channel_id)
                        existing_streamer: tuple[discord.Member] = tuple(m for m in channel.members if m.voice.self_stream)

                        if not existing_streamer:
                            _log.debug("[HANDLE CONFLICT] No conflict detected in channel [%d] before starting up.", channel_id)

                        else:
                            _log.debug("[HANDLE CONFLICT] %d Streamer(s) Detected in channel [%d]", len(existing_streamer), channel_id)

                            if len(existing_streamer) > info.stream_limit:
                                _log.warning("[HANDLE CONFLICT] Stream limit exceeded. Sent ConflicView to channel [%d]", channel_id)
                                await self._send_conflict_view(existing_streamer, channel, info, view)

                            if not info.streamers:
                                streamers = tuple(StreamerInfo(id=streamer.id) for streamer in existing_streamer)
                                info.streamers.update(streamers)

                    except SpawnViewFailed as e:
                        _log.warning("[HANDLE CONFLICT] %s", e)
                        continue

                    except (discord.NotFound, discord.Forbidden, discord.InvalidData) as e:
                        _log.warning(f"[HANDLE CONFLICT] Channel [%d] not found or forbidden or has invalid data. Removing from DB.", channel_id, exc_info=e)
                        removing_channel.append(info)
                        continue

                    except Exception as e:
                        _log.warning(f"[HANDLE CONFLICT] Fetch failed channel [%d]. Should be handled later.", channel_id, exc_info=e)
                        continue

                self.channel_info[channel_id] = info
                handled_info.append(info)
                _log.info("[HANDLE CONFLICT] Successfully handling channel [%d]", channel_id)

                # Sleeps to prevent blocking from context switching
                # if guild unhandled channels are collected too much.
                if count >= 10:
                    await asyncio.sleep(0)
                    count = 0
                else:
                    count += 1

            self.unhandled_channels.difference_update(handled_info)
            await self.mongo.remove_invalid_channels(removing_channel)

            if not self._check_init:
                self._check_init = True
                _log.info("All Preparing Task Done!")

            # Waits until any guild's setup is done.
            await self.event.wait()
            self.event.clear()

    async def _process_conflict_view(
        self,
        channel : discord.VoiceChannel,
        max_streamer : int,
        view : Optional[StreamConflictResolveView] = None
    ) -> None:
        if view is None:
            return

        if view.is_finished():
            self.channel_info[channel.id].conflict_view = None
            return

        view.channel = channel
        view.max_streamer = max_streamer
        await view.update()

    @staticmethod
    async def _send_conflict_view(
        streamers : Iterable[discord.Member],
        channel : discord.VoiceChannel,
        info : ChannelInfo,
        view : Optional[StreamConflictResolveView] = None,
    ) -> None:
        if view and not view.is_finished():
            return

        # if view is None then create new instace of conflict view
        view = StreamConflictResolveView(streamers, channel=channel, max_streamer=info.stream_limit)

        try:
            await view.start()
            info.conflict_view = view

        except Exception as e:
            view.stop()
            info.conflict_view = None
            raise e

    @staticmethod
    async def _send_warn_message(
        member : discord.Member,
        channel : discord.VoiceChannel,
        stream_info: Iterable[ChannelInfo],
        max_streamer : int
    ) -> None:

        if max_streamer > 1:
            stream_limit = f"{max_streamer} streams"
        else:
            stream_limit = f"{max_streamer} stream"

        content = f"{member.mention}, The channel's stream limitation has reached."
        description = (
            f"Only {stream_limit} is allowed per voice channel due to rule.\n"
            "Please consider to move to other channel or try again later."
        )
        embed = discord.Embed(description=description, color=discord.Color.blurple())

        view = StreamerView(member, stream_info, channel)
        kwargs = {"content": content, "embed": embed, "view": view}

        await view.send(**kwargs)

    async def _kick_from_channel(
        self,
        member : discord.Member,
        channel : discord.VoiceChannel,
        stream_info : Iterable[StreamerInfo],
        max_streamer : int,
    ) -> None:
        """Sends warning message to member. If it's impossible,
        then the message will be sent to ``channel``.

        :param member: The Member who will be kicked from channel and a warn message will be sent to.
        :param channel: An alternative way if a message was failed to Member.
        :param stream_info: An iterable object of Streamer Info.
        :param max_streamer: The stream limit.
        """

        try:
            await member.edit(voice_channel=None)
            await self._send_warn_message(member, channel, stream_info, max_streamer)

        except discord.Forbidden:
            try:
                mod = discord.utils.get(member.guild.roles, id=469459051105878016)
                mention = "" if mod is None else f" {mod.mention}"
                since = format_dt(utcnow(), "T")
                msg = f"{member.mention} is streaming while exceeding {channel.mention} stream limit since {since}. Please take a look.{mention}"
                await channel.send(msg)

            except discord.HTTPException:
                _log.warning("[SEND WARN MESSAGE] Failed to send warning message to member [%d]", member.id)

    def _remove_unnecessary_things(self, channels : Iterable[BasicChannelInfo]) -> None:
        if not channels:
            return

        count = len(channels)
        form = "Channels are" if count > 1 else "Channel is"

        self.unhandled_channels.difference_update(channels)
        for channel in channels:
            info = self.channel_info.pop(channel.id, None)
            if info is None:
                continue

            view = info.conflict_view
            if view:
                view.stop()

        _log.info("%d Voice %s not being unhandled from now.", count, form)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member : discord.Member, before : discord.VoiceState, after : discord.VoiceState) -> None:
        if member.guild is None or member.bot or not self._check_init:
            return

        # This event is handled after auto_conflict_task is being done
        # Filter to get valid voice channel
        is_live, vc_channel = get_stream_status(before, after)
        if vc_channel is None:
            return

        # Handle after starting up
        vc_id = vc_channel.id
        info = self.channel_info.get(vc_id, None)
        if info is None:
            return

        max_streamer = info.stream_limit
        view = info.conflict_view
        stream_info = info.streamers

        await self._process_conflict_view(vc_channel, max_streamer, view)

        if not is_live:
            stream_info.discard(StreamerInfo(id=member.id))

        else:
            stream_info.add(StreamerInfo(id=member.id, started_at=utcnow()))

            if len(stream_info) > max_streamer:
                _log.info("Stream limit reached. Forced Disconnection applies to [%d]", member.id)
                stream_info.discard(StreamerInfo(id=member.id))
                await self._kick_from_channel(member, vc_channel, stream_info.copy(), max_streamer)

        async with self.lock:
            info.streamers = stream_info
            self.channel_info[vc_id] = info

        _log.info("Successfully updated stream info of Channel [%d] : %s", vc_id, stream_info)

    @commands.Cog.listener()
    async def on_guild_join(self, guild : discord.Guild):
        _log.info("Joined guild [%d]", guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild : discord.Guild):
        if not self._check_init:
            return

        _log.info("Left guild [%d]", guild.id)

        data : GoLiveGuildSetup = await self.mongo.get_guild_info(guild)
        await self.mongo.leave_guild(guild)
        self._remove_unnecessary_things(data.get_as_channel_info())

        
async def setup(app : GoLiveGuardian) -> None:
    await app.add_cog(Voice(app))
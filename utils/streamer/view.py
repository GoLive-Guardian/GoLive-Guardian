from __future__ import annotations
from discord import ui, Interaction
from discord.ui import Item
from discord.utils import format_dt, utcnow
from typing import Any, Collection, Optional, Tuple
from utils.model import StreamerInfo
from utils.util import get_mentioned_streamers
from .button import ViewCloseDynamicButton

import asyncio
import datetime
import discord
import logging


__all__ = (
    "StreamConflictResolveView",
    "StreamerView"
)

from .. import SpawnViewFailed

_log = logging.getLogger(__name__)


class StreamerView(ui.View):
    def __init__(
        self,
        member: Optional[discord.Member] = None,
        stream_details: Optional[Collection[StreamerInfo]] = None,
        channel: Optional[discord.VoiceChannel] = None,
    ):
        super().__init__(timeout=None)
        self.clear_items()
        self.message : Optional[discord.Message] = None
        self.stream_embed: discord.Embed = self._get_embed(stream_details)

        self.channel = channel
        self.member = member
        self.owner_id: int = member.id if member else 0
        self.view_stream_info.custom_id = f"streamer_info:details:{self.owner_id}"

        self.close = ViewCloseDynamicButton(self.owner_id)
        self.add_item(self.view_stream_info)
        self.add_item(self.close)

    @staticmethod
    def _get_embed(stream_details: Collection[StreamerInfo] = None) -> discord.Embed:
        embed = discord.Embed(title="Stream Details", color=discord.Color.blurple())
        embed.set_footer(text="If I failed to manage streamer's start time, then it shows 'Unknown'. However, I'm sure these streamers' are earlier than yours.")
        
        if not stream_details:
            embed.description = "## Failed to get stream details"
            return embed

        for detail in stream_details:
            embed.add_field(name=f"Started : {detail.start_formatted}", value=detail.mention, inline=True)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is None or interaction.user.id == self.owner_id:
            return True

        await interaction.response.send_message("This message is not granted for you", ephemeral=True)
        return False

    async def send(self, **kwargs):
        count = kwargs.pop("count", 1)
        if count > 3:
            return

        try:
            self.message = await self.channel.send(**kwargs)

        except (discord.Forbidden, discord.NotFound):
            _log.warning("[ERROR DETECTED] Failed to notify to member [%d]", self.owner_id)

        except discord.DiscordServerError:
            _log.warning("[ERROR DETECTED] Failed to notify to member [%d]. Retrying.", self.owner_id)
            sleep = min(10,  count * 2 + random.uniform(0, 5) * 2)
            kwargs["count"] = count + 1
            await asyncio.sleep(sleep)
            await self.send(**kwargs)

    @ui.button(label="View Stream Info", style=discord.ButtonStyle.gray, custom_id="streamer_info:details:{user_id}")
    async def view_stream_info(self, interaction: discord.Interaction, _):
        self.view_stream_info.disabled = True
        
        if self.stream_embed is discord.utils.MISSING:
            self.stream_embed = self._get_embed()
            
        await interaction.response.edit_message(content=None, view=self, embed=self.stream_embed)

    async def on_timeout(self):
        if self.message:
            await self.message.delete()


class StreamConflictResolveView(ui.View):
    def __init__(
        self,
        existing_streamer: Collection[discord.Member],
        *,
        channel: discord.VoiceChannel,
        max_streamer: int,
    ):
        timeout = 180
        super().__init__(timeout=timeout)
        self.timeout_at = format_dt(utcnow() + datetime.timedelta(seconds=timeout), "R")
        self.channel: discord.VoiceChannel = channel

        self.max_streamer: int = max_streamer
        self.initial_streamer: Tuple[discord.Member] = tuple(existing_streamer)  # type: ignore
        self.current_streamer: Tuple[discord.Member] = tuple(existing_streamer)  # type: ignore
        self.agreed_streamer: Tuple[discord.Member] = tuple()

        self.message: Optional[discord.Message] = None
        self.initial_embed: Optional[discord.Embed] = None
        self.delete_after = 15

        self.__close: bool = False

    def __renew_streamer_status(self):
        self.current_streamer = tuple(m for m in self.channel.members if m.voice.self_stream if m in self.current_streamer)
        self.agreed_streamer = tuple(m for m in self.initial_streamer if m not in self.current_streamer)

    def __get_closure_kwargs(self):
        agreed_streamer = get_mentioned_streamers(self.agreed_streamer)
        if agreed_streamer:
            agreed_streamer = f" {agreed_streamer}"

        self.__close = True

        return {
            "content": f"Conflict is resolved. Thank you!{agreed_streamer}",
            "view": None,
            "embed": None,
            "delete_after": self.delete_after,
        }

    async def update(self) -> None:
        self.__renew_streamer_status()

        kwargs = self._get_status()
        
        if self.message is not None:
            await self.message.edit(**kwargs)

        else:
            conflict_streamer = get_mentioned_streamers(self.current_streamer)
            try:
                self.message = await self.channel.send(
                    f"Hey, {conflict_streamer}! You should resolve your stream conflicts.",
                    **kwargs,
                )
            except (discord.Forbidden, discord.NotFound) as e:
                raise e

            except discord.HTTPException:
                raise SpawnViewFailed(f"Failed to start handling conflict in channel [{self.channel.id}]")

            except Exception:
                raise Exception(f"Unexpected Error detected while handling conflict in channel [{self.channel.id}]")

        if self.__close:
            self.stop()

    def _get_status(self) -> dict[str, Any]:
        should_agree = len(self.current_streamer) - self.max_streamer
        agreed = len(self.agreed_streamer)

        embed = discord.Embed(
            title=f"Waiting agreements {agreed} / {should_agree}",
            color=discord.Color.blurple(),
        )

        if agreed < should_agree:
            kwargs = {
                "embeds": [self.initial_embed, embed],
                "view" : self
            }
        else:
            kwargs = self.__get_closure_kwargs()

        return kwargs

    async def start(self):
        content = (
            "Your stream may be forcibly closed by Discord Mods or me.\n"
            f"If you don't resolve it, all of streamers will be disconnected from this channel in {self.timeout_at}."
        )
        embed = discord.Embed(
            title=f"Stream limitation Reached in this channel",
            description=content,
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="This message may be sent when I failed to handle stream(s) after starting up.")
        self.initial_embed = embed

        try:
            await self.update()
        except Exception:
            raise

    async def _kick_streamers(self, *, reason: Optional[str] = None) -> None:
        async with asyncio.TaskGroup() as tg:
            for mem in self.current_streamer:
                if mem.voice is None:
                    continue

                tg.create_task(
                    mem.edit(voice_channel=None, reason=reason),
                    name=f"golive-force-kick: <guild:{mem.guild.id}, channel:{self.channel.id}, member:{mem.id}>"
                )
                await asyncio.sleep(0.1)

    async def on_timeout(self) -> None:
        if self.message:
            mentioned_streamer = get_mentioned_streamers(self.current_streamer)

            kwargs = {
                "content" : f"Conflict Not resolved. Disconnecting {mentioned_streamer}",
                "delete_after" : self.delete_after,
                "view" : None,
                "embed" : None,
            }

            await self.message.edit(**kwargs)
            await self._kick_streamers(reason=f"Stream conflict not resolved in {self.channel} (ID : {self.channel.id})")
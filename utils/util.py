from __future__ import annotations
from discord import ui
from discord.utils import _human_join
from typing import Collection, Iterable, Optional, Tuple, Union
from utils.model import StreamerInfo

import datetime
import discord
import logging


_log = logging.getLogger(__name__)


__all__ = (
    "ConfirmationView",
    "is_voice_channel",
    "get_stream_status",
    "get_mentioned_streamers",
    "has_basic_permissions",
    "verify_voice_channel",
    "merge_permissions",
    "is_channel_public"
)


def merge_permissions(
    overwrite: discord.PermissionOverwrite,
    permissions: discord.Permissions,
    **perms: bool
) -> None:
    for perm, value in perms.items():
        if getattr(permissions, perm):
            setattr(overwrite, perm, value)


def is_voice_channel(channel: Optional[discord.abc.GuildChannel]) -> bool:
    return channel is not None and channel.type is discord.ChannelType.voice


def get_stream_status(
    before: discord.VoiceState,
    after: discord.VoiceState
) -> Tuple[bool, Optional[discord.VoiceChannel]]:
    # Join VC first time
    if before.channel is None and after.channel is not None:
        return False, after.channel

    # Leave VC
    if before.channel is not None and after.channel is None:
        return False, before.channel

    # Both of member's before channel and after channel should be in voice channel.
    if not before.self_stream and after.self_stream:
        return True, after.channel

    if before.self_stream and not after.self_stream:
        return False, before.channel

    if before.self_stream and after.self_stream:
        if after.channel is None:
            return False, before.channel
        return True, after.channel

    return False, None


def _get_basic_permissions(perm: Union[discord.Permissions, discord.PermissionOverwrite]):
    return (
        perm.view_channel and
        perm.send_messages and
        perm.read_message_history and
        perm.move_members and
        perm.embed_links
    )


def has_basic_permissions(
    channel: discord.abc.GuildChannel,
    member: discord.Member,
) -> bool:
    ow = channel.overwrites
    default = discord.PermissionOverwrite()
    if ow.get(member, default).manage_roles:
        return True

    for role in member.roles:
        if ow.get(role, default).manage_roles:
            return True

    for role in member.roles:
        perm = channel.permissions_for(role)
        if _get_basic_permissions(perm):
            return True

    perm = channel.permissions_for(member)
    if _get_basic_permissions(perm):
        return True
    return False


def is_channel_public(channel : discord.abc.GuildChannel) -> bool:
    role = channel.guild.default_role
    perm = channel.permissions_for(role)

    return (
        perm.view_channel and
        perm.read_message_history
    )


def verify_voice_channel(
    channel: discord.abc.GuildChannel,
    member: discord.Member,
) -> bool:
    is_voice = is_voice_channel(channel)
    has_basic_perm = has_basic_permissions(channel, member)  # type: ignore

    return is_voice and has_basic_perm


def get_mentioned_streamers(
    existing_streamer: Collection[StreamerInfo] | Iterable[discord.Member],
) -> str:
    if not existing_streamer:
        return ""

    return _human_join(
        tuple(streamer.mention for streamer in existing_streamer),
        final='and'
    )


class ConfirmationView(ui.View):
    def __init__(self, show_embed : bool = False, *, timeout : float, author_id : int, delete_after : bool) -> None:
        super().__init__(timeout=timeout)
        self.value: Optional[bool] = False
        self.delete_after = delete_after
        self.author_id = author_id
        self.message : Optional[discord.Message] = None

        if show_embed:
            t = discord.utils.utcnow() + datetime.timedelta(seconds=self.timeout)
            timeout_at = discord.utils.format_dt(t, "R")

            description = (
                f"This Can not be Stopped if you press 'Yes' Button. Make sure your future setup is right.\n"
                f"This message will be expired in {timeout_at}"
            )
            self.embed = discord.Embed(
                title="Are you Sure?", description=description, color=discord.Colour.red()
            )
        else:
            self.embed = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.author_id:
            return True

        await interaction.response.send_message("This confirmation is not for you.", ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        if self.delete_after and self.message:
            await self.message.delete()

    @ui.button(label="Confirm", style=discord.ButtonStyle.gray)
    async def confirm(self, interaction: discord.Interaction, _):
        self.value = True
        await interaction.response.defer()
        if self.delete_after:
            await interaction.delete_original_response()

        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, _):
        self.value = False
        await interaction.response.defer()
        if self.delete_after:
            await interaction.delete_original_response()

        self.stop()



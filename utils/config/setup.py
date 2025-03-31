from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, replace
from discord import ui, Interaction
from discord.app_commands import AppCommandChannel
from typing import Callable, Optional, TYPE_CHECKING, Iterable

from utils.model import BasicChannelInfo, GoLiveGuildSetup, ChannelID, StreamLimit, ChannelInfo
from utils.util import ConfirmationView, merge_permissions, verify_voice_channel

if TYPE_CHECKING:
    from cogs.setup import Setup

import discord
import inspect
import logging


_log = logging.getLogger(__name__)

__all__ = (
    "StreamConfig",
)


class StreamChannelLimitModal(ui.Modal):
    def __init__(
        self,
        view : StreamConfig,
        *,
        values : list[tuple[int, str]],
    ) -> None:
        super().__init__(
            title="Fill Each Channel's Stream Limit",
            timeout=300,
        )
        self.view = view
        self.limit = limit = view.temp.stream_limit

        if limit <= 1:
            placeholder = "only 1"
        else:
            placeholder = f"from 1 to {limit}"

        length = len(str(limit))
        slice_length = 25
        items : list[discord.ui.TextInput] = []

        for value in values:
            channel_id, name = value
            if len(name) > slice_length:
                name = f"{name[:slice_length]}..."

            text_input = discord.ui.TextInput(
                label=name,
                style=discord.TextStyle.short,
                min_length=1,
                max_length=length,
                custom_id=f"{channel_id}",
                default=f"{limit}",
                placeholder=f"You can put number {placeholder}.",
            )
            self.add_item(text_input)
            items.append(text_input)

        self.items = items
        self.interaction = None

    def update_channels(self) -> tuple[str]:
        if all(0 < int(item.value) <= self.limit for item in self.items):
            self.view.temp.channels = {item.custom_id: item.value for item in self.items}
            return tuple()
        return tuple(f"[<#{item.custom_id}> : `{item.value}`]" for item in self.items if int(item.value) > self.limit or int(item.value) <= 0)

    async def on_submit(self, interaction : discord.Interaction):
        self.interaction = interaction
        self.stop()


class StreamChannelConfigSelect(ui.ChannelSelect["StreamConfig"]):
    def __init__(self, temp : _TempDataClass, func : Callable[..., discord.abc.GuildChannel]) -> None:
        if temp.channels:
            default = [
                channel for channel_id in temp.channels
                if (channel := func(channel_id)) is not None
            ]

        else:
            default = discord.utils.MISSING

        self.basic_limit = temp.stream_limit
        self.initial_status = default
        self.after_status = default

        super().__init__(
            custom_id=f"StreamChannelConfigSelect:{temp.id}",
            channel_types=[discord.ChannelType.voice],
            placeholder=f"Select max {temp.channel_limit} channels",
            min_values=1,
            max_values=temp.channel_limit,
            default_values=default,
            row=0
        )

    async def interaction_check(self, interaction : discord.Interaction):
        return await self.view.interaction_check(interaction)

    async def request_permission_sync(
        self,
        interaction : discord.Interaction,
        requested_channels : set[discord.VoiceChannel]
    ) -> bool:
        if not requested_channels:
            return True
        
        success : list[discord.VoiceChannel] = []
        failed : list[tuple[discord.VoiceChannel, str]] = []

        channels_mention = discord.utils._human_join(tuple(c.mention for c in requested_channels), final='and')
        msg = (
            f"Permission for {channels_mention} channel(s) seems not to be synced with my role, would you like me to set it/them up for you?\n\n"
            "If permission would not be synced, bot will do improper actions.\n"
            "And the bot and developer are not responsible for any issues arising from this issue, so highly recommend to sync.\n"
            "### [NOTE]\nTo ensure set my permission up properly, **Manage Roles** permission must be granted to me before getting it done.\n\n"
            "These channels are required permissions below:\n"
            "* View Channels / Read Message History : To edit my message\n"
            "* Send Messages : To send Conflict Resolve message or Warn message to members\n"
            "* Move Members : To kick members who try to turn on their streams in the channel where its stream limit has reached\n"
            "* Embed Links : To send embed message\n\n"
        )

        embed = discord.Embed(description=msg, colour=discord.Colour.red())
        embed.set_footer(text="This may happen when I don't have View Channel permission for the channels.")

        view = ConfirmationView(timeout=180.0, author_id=interaction.user.id, delete_after=False)
        await interaction.response.edit_message(view=view, embed=embed)
        await view.wait()
        
        if not view.value:
            msg = (
                "You chose to reject it.\n"
                "Then, please sync permissions manually and try again."
            )
            await interaction.followup.send(msg, ephemeral=True)
            self._before_update(self.after_status)
            return False
        
        guild = interaction.guild
        guild_perms = guild.me.guild_permissions
        my_role = [role for role in guild.me.roles if role.is_bot_managed() and role.tags.bot_id == interaction.client.user.id][0]
        reason = f"Permission sync confirmed by {interaction.user} (ID : {interaction.user.id})"
        
        for channel in requested_channels:
            perms = channel.permissions_for(guild.me)
            if perms.manage_roles :
                overwrite = channel.overwrites_for(my_role)
                perms = {
                    'view_channel' : True,
                    'send_messages' : True,
                    'read_message_history' : True,
                    'move_members' : True,
                    'embed_links' : True
                }
                merge_permissions(overwrite, guild_perms, **perms)

                try:
                    await channel.set_permissions(my_role, overwrite=overwrite, reason=reason)

                except discord.Forbidden as e:
                    _log.warning("", exc_info=e)
                    failed.append((channel, "Some required Permissions are missing."))

                except discord.HTTPException as e:
                    _log.warning("", exc_info=e)
                    failed.append((channel, "Unknown Error Occurred."))

                else:
                    success.append(channel)
            else:
                failed.append((channel, "This channel is not visible."))
        
        def get_string(values : list[str], delimiter : str = ", ", final : str = "or") :
            return discord.utils._human_join(values, delimiter=delimiter, final=final)
        
        success_str = get_string([channel.mention for channel in success])
        failed_str = get_string([f"{channel.mention} - {reason}" for channel, reason in failed], '\n', '\n')

        req_len = len(requested_channels)
        success_len = len(success)

        msg = (
            f"## [Task Done {success_len}/{req_len}]\n"
            f"### [Success]\n{success_str}\n"
            f"### [Failure]\n{failed_str}"
        )
        
        if failed:
            requested_channels.difference_update(failed)
            self.view.confirm_sync_channels = requested_channels

            failed = [channel.id for channel, _ in failed]
            channels = [value for value in self.values if value.id not in failed]
            self._before_update(channels)

        await interaction.followup.send(msg, ephemeral=True)
        return not failed

    def _before_update(self, channels : list[AppCommandChannel]):
        self.default_values = channels
        self.update_channel_selection(channels)

    def update_channel_selection(self, values : Iterable[discord.abc.GuildChannel]):
        if not values:
            return

        temp_channels = {}
        temp = self.view.temp

        for value in values:
            channel_id = value.id
            if channel_id in temp.channels:
                temp_channels[channel_id] = temp.channels[channel_id]
            else:
                temp_channels[channel_id] = temp.stream_limit

        self.view.temp.channels = temp_channels

    def verify_channel(self, interaction : discord.Interaction) -> set[discord.abc.GuildChannel]:
        client = interaction.client
        channels = [
            channel.resolve() or client.get_channel(channel.id)
            for channel in self.values.copy()
        ]

        return set(
            channel for channel in channels
            if not verify_voice_channel(channel, interaction.guild.me)
        )
        
    async def callback(self, interaction : discord.Interaction):
        assert self.view is not None

        has_conflict = self.verify_channel(interaction)
        is_normal = await self.request_permission_sync(interaction, has_conflict)
        if is_normal:
            self.after_status = self.values
            self._before_update(self.values)

        await self.view.update(interaction, content=None)


@dataclass
class _TempDataClass:
    id : int
    watch : bool
    channels : Mapping[ChannelID, StreamLimit]
    channel_limit : int
    stream_limit : int
    
    def finalize_setup(self) -> GoLiveGuildSetup:
        return GoLiveGuildSetup(
            id=self.id,
            watch=self.watch,
            channels=self.channels,            
            channel_limit=self.channel_limit,
            stream_limit=self.stream_limit,
        )
    
    def get_embed(self) -> discord.Embed:
        watching = "YES" if self.watch else "No"
        
        description = inspect.cleandoc(
            f"""* Watching Channels: {watching}
            * Channel Limit : {self.channel_limit}
            * Stream Limit Per Channel : {self.stream_limit}
            """
        )
        embed = discord.Embed(title="Current Setup", description=description, color=discord.Colour.blurple())
        
        if self.channels:
            value = "\n".join(f"* <#{channel}> : {limit}" for channel, limit in self.channels.items())
            embed.add_field(name="Channel Info", value=value, inline=False)

        return embed
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _TempDataClass):
            return False
        
        self_dict = {str(k) : str(v) for k, v in self.channels.items()}
        other_dict = {str(k) : str(v) for k, v in other.channels.items()}
        
        return (
            self_dict == other_dict and
            self.watch == other.watch and
            self.channel_limit == other.channel_limit and
            self.stream_limit == other.stream_limit
        )

    def is_same(self, other : _TempDataClass) -> bool:
        """Explicitly Compare other class"""
        return self.__eq__(other)


class StreamConfig(ui.View):
    def __init__(
        self,
        cog : Setup,
        *,
        data : GoLiveGuildSetup,
        owner_id : int
    ):
        super().__init__()
        self.cog = cog
        self.owner_id = owner_id
        
        self.temp = _TempDataClass(
            id=data.id,
            watch=data.watch,
            channels=data.channels,
            channel_limit=data.channel_limit,
            stream_limit=data.stream_limit
        )
        self.initial = replace(self.temp)
        self.message : Optional[discord.InteractionMessage] = None
        self.confirm_sync_channels : set[discord.VoiceChannel] = None
        self.select : Optional[StreamChannelConfigSelect] = None
        self.embed = self.temp.get_embed()
        self.is_done : bool = False

    @property
    def mention_owner(self) -> str:
        return f"<@{self.owner_id}>"
    
    def _refresh_components(self) -> None:
        watch_channels = self.temp.watch
        if watch_channels:
            self.watch_guilds.style = discord.ButtonStyle.green
        else:
            self.watch_guilds.style = discord.ButtonStyle.red

        if not self.temp.channels or self.initial.is_same(self.temp):
            self.revert.disabled = True
            self.save.disabled = True
        else:
            self.revert.disabled = False
            self.save.disabled = False

        if self.select.default_values:
            self.set_channel_stream_limit.disabled = False
        else:
            self.set_channel_stream_limit.disabled = True
        
    async def _do_temp_view(self, interaction : discord.Interaction, *, cancel_message : str, delete_after : bool = False) -> bool:
        view = ConfirmationView(True, timeout=180.0, author_id=self.owner_id, delete_after=delete_after)
        await interaction.response.edit_message(view=view, embed=view.embed)
        await view.wait()

        # Manually Closed view
        if not view.value:
            await self.update()
            await interaction.followup.send(cancel_message, ephemeral=True)
            return False

        return True

    async def start(self, interaction : discord.Interaction) -> None:
        if self.message is None:
            self.select = StreamChannelConfigSelect(self.initial, func=interaction.client.get_channel)
            self.add_item(self.select)
            await self.update(interaction)

    async def update(self, interaction : Optional[discord.Interaction] = None, **kwargs) -> None:
        is_revert: bool = kwargs.pop("is_revert", False)

        if is_revert:
            self.temp = replace(self.initial)
            self.select.default_values = self.select.initial_status
            self.embed = self.initial.get_embed()
        else:
            self.embed = self.temp.get_embed()

        if self.select:
            if not self.select.default_values:
                self.embed.set_footer(text="No channels selected. You have to select at least one channel.")
            else:
                self.embed.remove_footer()
        
        self._refresh_components()

        content = kwargs.pop("content", discord.utils.MISSING)
        kwargs = {"content" : content, "embed" : self.embed, "view" : self}

        if self.message is None:
            self.message = await interaction.edit_original_response(embed=self.embed, view=self)
            return

        if interaction is None:
            func = self.message.edit
        else:
            if interaction.response.is_done():
                func = interaction.edit_original_response
            else:
                func = interaction.response.edit_message

        await func(**kwargs)

    def _clean_up_cog_items(self) -> None:
        voice_cog = self.cog.voice_cog
        assert voice_cog is not None

        initial = self.initial
        final = self.temp

        before = frozenset(initial.channels.keys())
        after = frozenset(final.channels.keys())

        existing = before & after

        # Delete
        to_remove_set = before - after
        to_remove = [BasicChannelInfo(id=channel_id, guild_id=final.id) for channel_id in to_remove_set]

        try:
            if not final.watch:
                if initial.watch:
                    # remove update (existing)
                    func = voice_cog.channel_info.get
                    addition = [
                        BasicChannelInfo(id=channel_id, guild_id=final.id)
                        for channel_id in existing if func(channel_id, None)
                    ]
                    to_remove.extend(addition)
                return

            # Add Channels to be handled
            to_add = after - before
            to_add_list = []

            if not initial.watch:
                # do update (existing)
                for channel_id in existing:
                    info = voice_cog.channel_info.get(channel_id, None)
                    if info is None:
                        info = ChannelInfo(id=channel_id, guild_id=final.id)

                    info.watch = final.watch
                    info.stream_limit = final.channels[channel_id]
                    to_add_list.append(info)

            to_add_list.extend([
                ChannelInfo(id=channel_id, guild_id=final.id, stream_limit=final.channels[channel_id], watch=final.watch)
                for channel_id in to_add
            ])

            voice_cog.unhandled_channels.update(to_add_list)

        finally:
            voice_cog._remove_unnecessary_things(to_remove)
            if final.watch:
                voice_cog.event.set()

    @ui.button(label="Watch Channels", style=discord.ButtonStyle.green, row=1)
    async def watch_guilds(self, interaction : discord.Interaction, _) -> None:
        self.temp.watch = not self.temp.watch
        await self.update(interaction)

    @ui.button(label="Config Channel", style=discord.ButtonStyle.primary, row=1)
    async def set_channel_stream_limit(self, interaction : discord.Interaction, _) -> None:
        temp = []
        for channel in self.select.default_values:
            c = interaction.guild.get_channel(channel.id)
            temp.append((c.id, c.name))

        if not temp:
            await interaction.response.send_message("You didn't select any channels.", ephemeral=True)
            return

        modal = StreamChannelLimitModal(self, values=set(temp))
        await interaction.response.send_modal(modal)

        timeout = await modal.wait()
        if timeout:
            await interaction.followup.send("Time out. Channel config not updated.", ephemeral=True)
            return

        elif self.is_finished():
            await modal.interaction.response.send_message("Time out. Channel config not updated.", ephemeral=True)
            return

        all_digit = all(item.value.isdigit() for item in modal.items)
        if not all_digit:
            await modal.interaction.response.send_message("All inputs are must be number.", ephemeral=True)
            return

        result = modal.update_channels()
        if not result:
            await self.update(modal.interaction)
        else:
            content = discord.utils._human_join(result, final="and")

            if len(result) > 1:
                form = f"{content} channels didn't"
            else:
                form = f"{content} channel doesn't"

            content = inspect.cleandoc(
                f"""Channel config has not updated.
                {form} meet the requirements.
                """
            )
            await modal.interaction.response.send_message(content, ephemeral=True)

    @ui.button(label="Save", style=discord.ButtonStyle.gray, row=2)
    async def save(self, interaction : discord.Interaction, _) -> None:
        result = await self._do_temp_view(interaction, cancel_message="Save Canceled.")
        if not result:
            return

        final = self.temp.finalize_setup()
        result = await self.cog.mongo.update_guild_info(final)
        
        if not result:
            await interaction.followup.send("Sorry, Your Setup isn't saved for unknown reason. Please try again.", ephemeral=True)
            return

        self._clean_up_cog_items()
        await self.message.edit(content="Setup saved. You can close this message.", view=None, embed=None)

        self.is_done = True
        self.stop()

    @ui.button(label="Revert", style=discord.ButtonStyle.gray, row=2)
    async def revert(self, interaction : discord.Interaction, _):
        await self.update(interaction, is_revert=True)
        await interaction.followup.send("Revert Done. You can close this message.", ephemeral=True)

    @ui.button(label="Cancel", style=discord.ButtonStyle.gray, row=2)
    async def cancel(self, interaction : discord.Interaction, _):
        await interaction.response.edit_message(content="Setup Canceled. You can close this message.", view=None, embed=None)
        self.stop()

    async def on_timeout(self) -> None:
        if self.message:
            await self.message.edit(content="Time out. Setup Canceled. You can close this message.", view=None, embed=None)

    async def interaction_check(self, interaction: Interaction, /) -> bool:
        if interaction.user and self.owner_id == interaction.user.id:
            return True

        await interaction.response.send_message("This message is not for you", ephemeral=True)
        return False
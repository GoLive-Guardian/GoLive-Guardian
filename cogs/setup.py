from __future__ import annotations
from discord import app_commands
from discord.ext import commands
from typing import TYPE_CHECKING
from utils import  StreamConfig, ConfirmationView, GoLiveGuildSetup, is_channel_public
from utils.paginator import ChannelInfoPages

if TYPE_CHECKING:
    from bot import GoLiveGuardian
    from utils import ChannelInfo

import discord
import itertools
import logging


_log = logging.getLogger(__name__)



class Setup(commands.Cog):
    def __init__(self, app : GoLiveGuardian):
        self.app = app

    @property
    def voice_cog(self):
        return self.app.voice_cog

    @property
    def mongo(self):
        return self.app.pool

    async def interaction_check(self, interaction : discord.Interaction) -> bool:
        if not self.voice_cog._check_init:
            await interaction.response.send_message("I am not ready yet. You can run commands if I am.", ephemeral=True)
            return False

        return True

    @app_commands.command(name="reset")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.cooldown(rate=1.0, per=15.0, key=lambda i: i.guild_id)
    async def reset_setup(self, interaction : discord.Interaction):
        """Reset your server's setup"""
        ephemeral = is_channel_public(interaction.channel)

        guild_previous_setup : GoLiveGuildSetup = await self.mongo.get_guild_info(interaction.guild.id)
        dummy_setup = GoLiveGuildSetup(id=interaction.guild_id)

        if guild_previous_setup.compare(dummy_setup):
            await interaction.response.send_message("Your setup is already reset.", ephemeral=ephemeral)
            return

        await interaction.response.defer(thinking=True, ephemeral=ephemeral)

        view = ConfirmationView(True, timeout=180, author_id=interaction.user.id, delete_after=True)
        view.message = await interaction.edit_original_response(embed=view.embed, view=view)
        await view.wait()

        if not view.value:
            await interaction.followup.send("Reset Canceled. You can close this message.", ephemeral=ephemeral)
            return

        result = await self.mongo.update_guild_info(dummy_setup)

        if result:
            msg = "Reset Done. You can close this message."

            channel_info = self.voice_cog.channel_info
            to_delete = []

            for channel_id in guild_previous_setup.channels.keys():
                info = channel_info.get(channel_id, None)
                if info:
                    to_delete.append(info)

            self.voice_cog._remove_unnecessary_things(to_delete)
        else:
            msg = "Reset Failed. Try again later."

        await interaction.followup.send(msg, ephemeral=ephemeral)

    @app_commands.command(name="setup")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.cooldown(rate=1.0, per=30.0, key=lambda i: i.guild_id)
    async def start_setup(self, interaction : discord.Interaction):
        """Start your server configuration"""
        ephemeral = is_channel_public(interaction.channel)
        if not interaction.guild.voice_channels:
            await interaction.response.send_message("Your server doesn't have voice channel.", ephemeral=ephemeral)
            return
        
        await interaction.response.defer(thinking=True, ephemeral=ephemeral)

        data : GoLiveGuildSetup = await self.mongo.get_guild_info(interaction.guild.id)
        view = StreamConfig(self, data=data, owner_id=interaction.user.id)
        await view.start(interaction)

    @app_commands.command(name="status")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    async def get_status(self, interaction : discord.Interaction):
        """Get the stream status of your server"""
        ephemeral = is_channel_public(interaction.channel)
        await interaction.response.defer(thinking=True, ephemeral=ephemeral)

        data : GoLiveGuildSetup = await self.mongo.get_guild_info(interaction.guild.id)
        if not data.watch:
            await interaction.followup.send("I am not watching any voice channel in your server. Run `/setup` to enable watching channels.", ephemeral=ephemeral)
            return

        current_guild_status : list[ChannelInfo] = []
        for channel_id in data.channels:
            try:
                info = self.voice_cog.channel_info[channel_id]
                current_guild_status.append(info)

            except KeyError:
                pass

        if not current_guild_status:
            await interaction.followup.send("Your server doesn't have any data.", ephemeral=ephemeral)
            return

        view = ChannelInfoPages(current_guild_status, cog=self, per_page=2)
        await view.start(interaction, ephemeral=ephemeral)


async def setup(app : GoLiveGuardian) -> None:
    await app.add_cog(Setup(app))
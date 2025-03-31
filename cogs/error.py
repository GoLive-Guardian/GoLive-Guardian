from __future__ import annotations
from datetime import datetime, timedelta
from discord import app_commands, Embed, Interaction
from discord.ext import commands
from discord.utils import format_dt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import GoLiveGuardian

import asyncio
import discord
import inspect
import logging


_log = logging.getLogger(__name__)


class AppCommandErrorHandler(commands.Cog):
    def __init__(self, app: GoLiveGuardian) -> None:
        self.app = app
        self.default_message = "An error occurred. Please try again later or consider to contact support."

    async def cog_load(self) -> None:
        tree = self.app.tree
        self._old_tree_error = tree.on_error
        tree.on_error = self.on_app_command_error

    async def cog_unload(self) -> None:
        self.app.tree.on_error = self._old_tree_error

    async def on_app_command_error(self, interaction: Interaction, error: app_commands.AppCommandError):
        error_time = interaction.created_at
        embed = Embed(title='', description='', color=discord.Color.light_embed(), timestamp=error_time)

        _log.error("", exc_info=error)

        if isinstance(error, app_commands.CommandOnCooldown):
            retry_after = error_time + timedelta(seconds=error.retry_after)
            retry_after = format_dt(retry_after, 'T')
            command_mention = f"</{interaction.command.qualified_name}:{interaction.data['id']}>"

            embed.title = 'Please Be Patient!'
            embed.description = f"You are temporarily blocked using {command_mention} again until {retry_after}"

        elif isinstance(error, app_commands.CheckFailure):
            pass

        elif isinstance(error, app_commands.CommandInvokeError):
            e = error.original
            embed.title = "Failed to invoke command."
            embed.description = (
                f"* Error Type : {e.__class__.__name__}\n"
                f"* Error Summary : {e}\n"
                f"* Command : {error.command.qualified_name}\n"
                "Please run it again. If you are continuing get failure, consider to report."
            )

        elif isinstance(error, discord.DiscordServerError):
            embed.title = 'Discord Server error'
            embed.description = "This is Discord's fault, not me. So this will not be reported."
            await asyncio.sleep(5)

        elif isinstance(error, RuntimeError):
            embed.title = 'RuntimeError'
            embed.description = error

        await self.send_error(interaction, embed=embed)

    @staticmethod
    async def send_error(interaction: Interaction, *, embed: Embed):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception:
            pass


async def setup(app: GoLiveGuardian):
    await app.add_cog(AppCommandErrorHandler(app))
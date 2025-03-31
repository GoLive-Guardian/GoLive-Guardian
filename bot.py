from __future__ import annotations
from cogs.voice import Voice
from discord.ext import commands
from typing import Optional, Tuple
from utils.streamer import ViewCloseDynamicButton, StreamerView
from utils.db import MongoClient

import asyncio
import config
import discord
import logging


_extensions = (
    "cogs.setup",
    "cogs.voice",
    "cogs.error"
)

_views : Tuple[type[discord.ui.View]] = (
    StreamerView,
)

_log = logging.getLogger(__name__)


class GoLiveGuardian(commands.Bot):
    pool : MongoClient

    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True

        super().__init__(
            command_prefix=None,
            intents=intents,
            heartbeat_timeout=240.0,
            chunk_guild_at_startup=False,
            status=discord.Status.online
        )
        
        self.pool : Optional[MongoClient] = None
        self.is_closing : bool = False
        
    async def on_ready(self) -> None:
        _log.info('Logged in as {0.user}'.format(self))

    def add_views(self):
        for v in _views:
            try:
                self.add_view(v())
            except (TypeError, ValueError) as e:
                self.logger.warning("Failed to add view to {0}: {1}".format(v.__qualname__, e), exc_info=e)

    async def setup_hook(self) -> None:
        for extension in _extensions:
            try:
                await self.load_extension(extension)
                _log.info(f'Loaded extension {extension}')
            except commands.ExtensionError as e:
                _log.warning(f'Failed to load extension {extension}', exc_info=e)

        self.add_views()
        self.add_dynamic_items(ViewCloseDynamicButton, )
        # await self.tree.sync()

    async def start(self):
        await super().start(config.bot_token, reconnect=True)

    async def close(self) -> None:
        if self.is_closing:
            _log.info("Shutdown is already under progress.")
            return
        
        self.is_closing = True
        _log.info("Shutting Down...")
        
        await super().close()

        if bot_tasks := [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]:
            _log.debug(f'Canceling {len(bot_tasks)} outstanding tasks.')
            
            for task in bot_tasks:
                task.cancel()

            await asyncio.gather(*bot_tasks, return_exceptions=True)
            _log.debug('All Existing tasks cancelled.')
        
        try:
            _log.info("Shutting down Mongo Client.")
            await self.pool.close()
            _log.info("Mongo Client Shut down complete.")

        except Exception as e:
            _log.critical("Failed to gracefully shutdown Mongo Client", exc_info=e)

        _log.info('All Shutdown Complete.')
    
    @property
    def voice_cog(self) -> Optional[Voice]:
        return self.get_cog('Voice')

    @property
    def config(self):
        return __import__('config')
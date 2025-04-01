from __future__ import annotations
from collections import defaultdict
from motor.motor_asyncio import AsyncIOMotorClient
from typing import (
    Any,
    Coroutine,
    Union,
    Iterable,
    TypeVar,
    AsyncGenerator,
)
from pymongo.operations import DeleteOne, UpdateOne
from pymongo.errors import BulkWriteError
from .cache import cache
from .model import GoLiveGuildSetup, BasicChannelInfo

import asyncio
import config
import discord
import logging


__all__ = (
    "MongoClient",
)

_log = logging.getLogger(__name__)

MongoOperations = Union[DeleteOne, UpdateOne, ]
T = TypeVar("T")
Coro = Coroutine[Any, Any, T]


def determine_valid_channels(
    *,
    actual_vc_ids : Iterable[T],
    db_vc_ids : Iterable[T]
) -> tuple[Iterable[T], Iterable[T]]:
    actual_set = frozenset(actual_vc_ids)
    db_set = frozenset(db_vc_ids)

    valid_channels = db_set.intersection(actual_set)
    removal_channels = db_set.difference(valid_channels)

    return valid_channels, removal_channels


class MongoClient:
    def __init__(self):
        self._is_running : bool = True
        self.__client = AsyncIOMotorClient(config.mongo_uri)
        self.task = asyncio.create_task(self._test())
        self._loop = asyncio.get_event_loop()
        self.removable_guilds : list[int] = []
        self.removable_channels : list[BasicChannelInfo] = []

    async def get_all_guilds_info(self, guilds : Iterable[discord.Guild]) -> AsyncGenerator[GoLiveGuildSetup]:
        """Generally used for start up. So it should be used once."""
        guild_channels = {
            guild.id : tuple(channel.id for channel in guild.voice_channels)
            for guild in guilds
        }
        cursor = self._guild_setup.find({}, {"_id" : 0})

        async for data in cursor:
            guild = GoLiveGuildSetup.from_mongo(data)
            guild_id = guild.id

            if guild_id not in guild_channels:
                self.removable_guilds.append(guild_id)
                continue

            valid_channels, removal_channels = determine_valid_channels(
                actual_vc_ids=guild_channels[guild_id],
                db_vc_ids=guild.get_list_of_channel()
            )

            if removal_channels:
                to_extend = [
                    BasicChannelInfo(id=channel_id, guild_id=guild_id)
                    for channel_id in removal_channels
                ]
                self.removable_channels.extend(to_extend)

                guild = guild.refresh_channels(valid_channels)

            yield guild

    async def _cleanup_db(self):
        # Remove Guilds
        if self.removable_guilds:
            result = await self._guild_setup.delete_many({"id": {"$in": self.removable_guilds}})
            deleted = result.deleted_count
            remain = len(self.removable_guilds)

            if result.acknowledged and deleted > 0:
                _log.info("[DB MATCH] [%d] guild(s) deleted. [%d] guild(s) remaining", deleted, remain)

            if remain == 0:
                self.removable_guilds.clear()

        # Remove Invalid Channels
        if self.removable_channels:
            await self.remove_invalid_channels(self.removable_channels)

    @cache(maxsize=128)
    async def get_guild_info(self, guild : Union[discord.Guild, int]) -> GoLiveGuildSetup:
        if isinstance(guild, discord.Guild):
            guild = guild.id

        data = await self._guild_setup.find_one({"id" : guild}, {"_id" : 0})
        if data is None:
            return GoLiveGuildSetup(id=guild)
        return GoLiveGuildSetup.from_mongo(data)

    async def leave_guild(self, guild : GoLiveGuildSetup) -> bool:
        try:
            result = await self._guild_setup.delete_one({"id" : guild.id})
            deleted = result.deleted_count > 0
        except:
            deleted = False
                    
        await self.invalidate_cache(guild.id)
        return deleted
    
    async def update_guild_info(self, setup : GoLiveGuildSetup):
        payload = setup.transform_to_mongo()
        payload.pop("id")

        result = await self._guild_setup.update_one({"id" : setup.id}, {"$set" : payload}, upsert=True)
        done = result.acknowledged

        if done:
            await self.invalidate_cache(setup.id)
        return done

    async def _process_bulk(
        self,
        operations: dict[int, MongoOperations],
        get_results : bool = False
    ) -> frozenset[int] | None:
        if not operations:
            return

        retry_tasks : dict[int, MongoOperations] = {}

        try:
            to_write = list(operations.values())
            await self._guild_setup.bulk_write(to_write, ordered=False)

        except BulkWriteError as e:
            for error in e.details["writeErrors"]:
                failed_guild_id = error["op"]["id"]
                retry_tasks[failed_guild_id] = operations[failed_guild_id]

        before_guild_ids = frozenset(operations.keys())
        failed_guild_ids = frozenset(retry_tasks.keys())
        success_guild_ids = before_guild_ids - failed_guild_ids

        for guild_id in success_guild_ids:
            await self.invalidate_cache(guild_id)

        if get_results:
            return success_guild_ids

    async def remove_invalid_channels(self, infos : Iterable[BasicChannelInfo]) -> None:
        if not infos:
            return

        if not isinstance(infos, Iterable):
            infos = list(infos)

        temp : dict[int, list[int]] = defaultdict(list)
        op_dict = {}

        for info in infos:
            temp[info.guild_id].append(info.id)

        for guild_id, channels in temp.items():
            if not channels:
                continue

            unset_dict = {f"channels.{channel_id}": "" for channel_id in channels}
            task = UpdateOne({"id": guild_id}, {"$unset": unset_dict})

            op_dict[guild_id] = task

        await self._process_bulk(op_dict)

    async def invalidate_cache(self, guild : Union[BasicChannelInfo, int, discord.Guild]):
        if isinstance(guild, GoLiveGuildSetup):
            guild = guild.id
        elif isinstance(guild, discord.Guild):
            guild = guild.id

        if not isinstance(guild, int):
            raise TypeError(f"Invalid guild type: {type(guild)}")

        await self._loop.run_in_executor(
            None, self.get_guild_info.invalidate_containing, str(guild)
        )

    async def _test(self):
        _log.info("Mongo Client Test Started")

        attempt = 1
        while attempt <= 3:
            response = await self.__client.admin.command("ping")

            if response.get("ok") == 1:
                _log.info("Mongo Client Test Passed.")
                self._guild_setup = self.__client["setup"]["guild"]
                return

            attempt += 1

        raise RuntimeError("Failed to connect to MongoDB")

    async def close(self):
        self._is_running = False

        if self.__client is not None:
            self.__client.close()
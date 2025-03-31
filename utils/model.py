from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields, replace
from discord.utils import format_dt
from typing import Any, Optional, List, Mapping, TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from utils import StreamConflictResolveView
    from typing_extensions import Self

import datetime
import discord
import inspect


__all__ = (
    "ChannelID",
    "StreamLimit",
    "StreamerInfo",
    "BasicChannelInfo",
    "ChannelInfo",
    "GoLiveGuildSetup",
)


timestamp_format = inspect.cleandoc("""
    +-------------+----------------------------+-----------------+
    |    Style    |       Example Output       |   Description   |
    +=============+============================+=================+
    | t           | 22:57                      | Short Time      |
    +-------------+----------------------------+-----------------+
    | T           | 22:57:58                   | Long Time       |
    +-------------+----------------------------+-----------------+
    | d           | 17/05/2016                 | Short Date      |
    +-------------+----------------------------+-----------------+
    | D           | 17 May 2016                | Long Date       |
    +-------------+----------------------------+-----------------+
    | f (default) | 17 May 2016 22:57          | Short Date Time |
    +-------------+----------------------------+-----------------+
    | F           | Tuesday, 17 May 2016 22:57 | Long Date Time  |
    +-------------+----------------------------+-----------------+
    | R           | 5 years ago                | Relative Time   |
    +-------------+----------------------------+-----------------+

""")

class GuildID(int):
    pass


class ChannelID(int):
    pass


class StreamLimit(int):
    pass


@dataclass
class _EqualityComparable:

    id: int

    def __eq__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return self.id == other.id
        return NotImplemented


@dataclass
class _BaseStruct(_EqualityComparable):

    def __hash__(self) -> int:
        return self.id >> 22


@dataclass(unsafe_hash=True)
class StreamerInfo(_BaseStruct):

    started_at : Optional[datetime.datetime] = field(default=None, compare=False)

    @property
    def to_unix_time(self) -> Optional[float]:
        if self.started_at is None:
            return None
        return self.started_at.timestamp()

    @property
    def start_formatted(self) -> str:
        if self.started_at is None:
            return "Unknown"
        return format_dt(self.started_at, "T")

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"


@dataclass
class GoLiveGuildSetup(_BaseStruct):

    watch : bool = False
    channels : Mapping[ChannelID, StreamLimit] = field(default_factory=dict)
    stream_limit : StreamLimit = field(default=1)
    channel_limit: int = field(default=5)

    def compare(self, other : GoLiveGuildSetup) -> bool:
        return (
            self.id == other.id and
            self.watch == other.watch and
            self.channel_limit == other.channel_limit and
            self.stream_limit == other.stream_limit and
            not (self.channels or other.channels)
        )

    def transform_to_mongo(self) -> dict[str, Any]:
        self.channels = {str(channel_id): int(limit) for channel_id, limit in self.channels.items()}
        return asdict(self)

    def get_list_of_channel(self) -> List[ChannelID]:
        return list(self.channels.keys())

    @classmethod
    def from_mongo(cls, payload : dict[str, Any]) -> Self:
        try:
            channels : Mapping[ChannelID, StreamLimit] = payload["channels"]
            payload["channels"] = {int(k) : v for k, v in channels.items()}
        except KeyError:
            payload["channels"] = {}

        payload = {f.name : payload[f.name] for f in fields(cls)}
        return cls(**payload)

    def refresh_channels(self, channels : Iterable[ChannelID]):
        update = {channel_id : self.channels[channel_id] for channel_id in channels}
        return replace(self, channels=update)

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

        embed.set_footer(text="If you want to select same channel, ")
        return embed

    def get_as_channel_info(self) -> List[ChannelInfo]:
        return [
            ChannelInfo(
                id=channel_id, guild_id=self.id, watch=self.watch, stream_limit=limit
            ) for channel_id, limit in self.channels.items()
        ]


@dataclass(unsafe_hash=True)
class BasicChannelInfo(_BaseStruct):
    guild_id: int = field(compare=False)
    conflict_view: Optional[StreamConflictResolveView] = field(default=None, compare=False)


@dataclass(unsafe_hash=True)
class ChannelInfo(BasicChannelInfo):
    watch : bool = field(default=False, compare=False)
    stream_limit : int = field(compare=False, default=1)
    streamers : set[StreamerInfo] = field(default_factory=set, compare=False)
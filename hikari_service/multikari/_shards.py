# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2021, Faster Speeding
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

__all__: list[str] = ["Shard"]

import datetime
import typing

import hikari

from . import _receivers


class Shard(hikari.api.GatewayShard):
    __slots__ = ("_current_user_id", "_heartbeat_latency", "_id", "_intents", "_receiver", "_shard_count")

    def __init__(
        self,
        *,
        receiver: _receivers.abc.AbstractReceiver,
        shard_id: int,
        intents: hikari.Intents,
        shard_count: int,
        user_id: hikari.Snowflake,
        heartbeat_latency: float = float("nan"),
    ) -> None:
        self._current_user_id = user_id
        self._heartbeat_latency = heartbeat_latency
        self._id = shard_id
        self._intents = intents
        self._receiver = receiver
        self._shard_count = shard_count

    @property
    def is_connected(self) -> bool:
        return self._receiver.is_alive

    @property
    def heartbeat_latency(self) -> float:
        return self._heartbeat_latency

    @property
    def id(self) -> int:
        return self._id

    @property
    def intents(self) -> hikari.Intents:
        return self._intents

    @property
    def is_alive(self) -> bool:
        return self._receiver.is_alive

    @property
    def shard_count(self) -> int:
        return self._shard_count

    def get_user_id(self) -> hikari.Snowflake:
        return self._current_user_id

    async def close(self) -> None:
        raise NotImplementedError("This shard impl cannot be closed")

    async def join(self) -> None:
        raise NotImplementedError("This shard impl cannot be joined")

    async def start(self) -> None:
        raise NotImplementedError("This shard impl cannot be started")

    def update_metadata(self, *, heartbeat_latency: float = float("nan")) -> None:
        self._heartbeat_latency = heartbeat_latency

    async def update_presence(
        self,
        *,
        idle_since: hikari.UndefinedNoneOr[datetime.datetime] = hikari.UNDEFINED,
        afk: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        activity: hikari.UndefinedNoneOr[hikari.Activity] = hikari.UNDEFINED,
        status: hikari.UndefinedOr[hikari.Status] = hikari.UNDEFINED,
    ) -> None:
        ...

    async def update_voice_state(
        self,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        channel: typing.Optional[hikari.SnowflakeishOr[hikari.GuildVoiceChannel]],
        *,
        self_mute: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        self_deaf: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
    ) -> None:
        ...

    async def request_guild_members(
        self,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        *,
        include_presences: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        query: str = "",
        limit: int = 0,
        users: hikari.UndefinedOr[hikari.SnowflakeishSequence[hikari.User]] = hikari.UNDEFINED,
        nonce: hikari.UndefinedOr[str] = hikari.UNDEFINED,
    ) -> None:
        ...

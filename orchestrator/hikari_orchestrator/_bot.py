# -*- coding: utf-8 -*-
# BSD 3-Clause License
#
# Copyright (c) 2023, Faster Speeding
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

import asyncio
import concurrent.futures
import datetime
import math
from collections import abc as collections

import grpc  # type: ignore
import hikari
import hikari.impl.event_factory  # TODO: export at hikari.impl
import hikari.urls

from . import _client
from . import _protos


class _ShardProxy(hikari.api.GatewayShard):
    __slots__ = ("_close_event", "_shard_count", "_id", "_intents", "_manager", "_state")

    def __init__(self, manager: _client.Client, shard_id: int, intents: hikari.Intents, shard_count: int, /) -> None:
        self._close_event = asyncio.Event()
        self._shard_count = shard_count
        self._id = shard_id
        self._intents = intents
        self._manager = manager
        self._state: _protos.Shard | None = None

    @property
    def heartbeat_latency(self) -> float:
        return self._state.latency if self._state else float("nan")

    @property
    def id(self) -> int:
        return self._id

    @property
    def intents(self) -> hikari.Intents:
        return self._intents

    @property
    def is_alive(self) -> bool:
        return bool(self._state and self._state.state is not _protos.ShardState.STOPPED)

    @property
    def is_connected(self) -> bool:
        return bool(self._state and self._state.state is _protos.ShardState.STARTED)

    @property
    def shard_count(self) -> int:
        return self._shard_count

    def get_user_id(self) -> hikari.Snowflake:
        raise NotImplementedError

    async def close(self) -> None:
        raise RuntimeError("Cannot close proxied shard")

    async def join(self) -> None:
        if self._state is _protos.ShardState.STOPPED:
            raise hikari.ComponentStateConflictError("Shard isn't running")

        await self._close_event.wait()

    async def start(self) -> None:
        raise RuntimeError("Cannot start proxied shard")

    async def update_presence(
        self,
        *,
        idle_since: hikari.UndefinedNoneOr[datetime.datetime] = hikari.UNDEFINED,
        afk: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        activity: hikari.UndefinedNoneOr[hikari.Activity] = hikari.UNDEFINED,
        status: hikari.UndefinedOr[hikari.Status] = hikari.UNDEFINED,
    ) -> None:
        await self._manager.update_presence(idle_since=idle_since, afk=afk, activity=activity, status=status)

    async def update_voice_state(
        self,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        channel: hikari.SnowflakeishOr[hikari.GuildVoiceChannel] | None,
        *,
        self_mute: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        self_deaf: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
    ) -> None:
        await self._manager.update_voice_state(guild, channel, self_mute=self_mute, self_deaf=self_deaf)

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
        await self._manager.request_guild_members(
            guild, include_presences=include_presences, query=query, limit=limit, users=users, nonce=nonce
        )

    def update_state(self, state: _protos.Shard, /) -> None:
        self._state = state
        if self._state.state is not _protos.ShardState.STOPPED and state.state is _protos.ShardState.STOPPED:
            self._close_event.set()

        else:
            self._close_event.clear()


class Bot(hikari.GatewayBotAware):
    __slots__ = (
        "_cache_settings",
        "_cache",
        "_close_event",
        "_credentials",
        "_entity_factory",
        "_event_factory",
        "_event_manager",
        "_fetch_task",
        "_gateway_url",
        "_global_shard_count",
        "_http_settings",
        "_intents",
        "_local_shard_count",
        "_manager",
        "_manager_address",
        "_other_shards",
        "_proxy_settings",
        "_rest",
        "_shards",
        "_token",
        "_voice",
    )

    def __init__(
        self,
        manager_address: str,
        token: str,
        global_shard_count: int,
        local_shard_count: int,
        /,
        *,
        cache_settings: hikari.impl.CacheSettings | None = None,
        credentials: grpc.ChannelCredentials | None = None,
        gateway_url: str,
        http_settings: hikari.impl.HTTPSettings | None = None,
        intents: hikari.Intents | int = hikari.Intents.ALL_UNPRIVILEGED,
        proxy_settings: hikari.impl.ProxySettings | None = None,
        rest_url: str = hikari.urls.REST_API_URL,
    ) -> None:
        self._cache_settings = cache_settings or hikari.impl.CacheSettings()
        self._cache = hikari.impl.CacheImpl(self, self._cache_settings)
        self._close_event: asyncio.Event | None = None
        self._credentials = credentials
        self._intents = hikari.Intents(intents)
        self._entity_factory = hikari.impl.EntityFactoryImpl(self)
        # TODO: export at hikari.impl
        self._event_factory = hikari.impl.event_factory.EventFactoryImpl(self)
        self._event_manager = hikari.impl.EventManagerImpl(self._entity_factory, self._event_factory, self._intents)
        self._fetch_task: asyncio.Task[None] | None = None
        self._gateway_url = gateway_url
        self._global_shard_count = global_shard_count
        self._http_settings = http_settings or hikari.impl.HTTPSettings()
        self._local_shard_count = local_shard_count
        self._manager_address = manager_address
        self._other_shards: dict[int, _protos.Shard] = {}
        self._proxy_settings = proxy_settings or hikari.impl.ProxySettings()
        self._rest = hikari.impl.RESTClientImpl(
            cache=self._cache,
            executor=None,
            rest_url=rest_url,
            entity_factory=self._entity_factory,
            http_settings=self._http_settings,
            proxy_settings=self._proxy_settings,
            token=token,
            token_type=hikari.TokenType.BOT,
        )
        self._shards: dict[int, hikari.api.GatewayShard] = {}
        self._voice = hikari.impl.VoiceComponentImpl(self)
        self._token = token
        self._manager = _client.Client()

    @property
    def cache(self) -> hikari.api.Cache:
        return self._cache

    @property
    def event_factory(self) -> hikari.api.EventFactory:
        return self._event_factory

    @property
    def event_manager(self) -> hikari.api.EventManager:
        return self._event_manager

    @property
    def voice(self) -> hikari.api.VoiceComponent:
        return self._voice

    @property
    def entity_factory(self) -> hikari.api.EntityFactory:
        return self._entity_factory

    @property
    def rest(self) -> hikari.api.RESTClient:
        return self._rest

    @property
    def executor(self) -> concurrent.futures.Executor | None:
        return None

    @property
    def http_settings(self) -> hikari.api.HTTPSettings:
        return self._http_settings

    @property
    def proxy_settings(self) -> hikari.api.ProxySettings:
        return self._proxy_settings

    @property
    def intents(self) -> hikari.Intents:
        return self._intents

    @property
    def heartbeat_latencies(self) -> collections.Mapping[int, float]:
        return {shard.id: shard.heartbeat_latency for shard in self._shards.values()}

    @property
    def heartbeat_latency(self) -> float:
        latencies = [
            shard.heartbeat_latency for shard in self._shards.values() if not math.isnan(shard.heartbeat_latency)
        ]
        return sum(latencies) / len(latencies) if latencies else float("nan")

    @property
    def is_alive(self) -> bool:
        return self._close_event is not None

    @property
    def shards(self) -> collections.Mapping[int, hikari.api.GatewayShard]:
        return self._shards

    @property
    def shard_count(self) -> int:
        return self._global_shard_count

    def get_me(self) -> hikari.OwnUser | None:
        raise NotImplementedError

    def _get_shard(self, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> hikari.api.GatewayShard:
        guild = hikari.Snowflake(guild)
        return self._shards[hikari.snowflakes.calculate_shard_id(self.shard_count, guild)]

    async def update_presence(
        self,
        *,
        idle_since: hikari.UndefinedNoneOr[datetime.datetime] = hikari.UNDEFINED,
        status: hikari.UndefinedOr[hikari.Status] = hikari.UNDEFINED,
        activity: hikari.UndefinedNoneOr[hikari.Activity] = hikari.UNDEFINED,
        afk: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
    ) -> None:
        await asyncio.gather(
            *(
                shard.update_presence(idle_since=idle_since, afk=afk, activity=activity, status=status)
                for shard in self._shards.values()
            )
        )

    async def update_voice_state(
        self,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        channel: hikari.SnowflakeishOr[hikari.GuildVoiceChannel] | None,
        *,
        self_mute: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        self_deaf: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
    ) -> None:
        await self._get_shard(guild).update_voice_state(guild, channel, self_mute=self_mute, self_deaf=self_deaf)

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
        await self._get_shard(guild).request_guild_members(
            guild, include_presences=include_presences, query=query, limit=limit, users=users, nonce=nonce
        )

    async def join(self) -> None:
        if not self._close_event:
            raise hikari.ComponentStateConflictError("Not running")

        await self._close_event.wait()

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.start())
        loop.run_until_complete(self.join())

    async def close(self) -> None:
        if not self._close_event:
            raise hikari.ComponentStateConflictError("Not running")

        await self._event_manager.dispatch(self._event_factory.deserialize_stopping_event())
        await self._manager.stop()
        self._shards = {}
        self._close_event.set()
        self._close_event = None
        await self._event_manager.dispatch(self._event_factory.deserialize_stopped_event())

    def _make_shard(self, shard_id: int, /) -> hikari.impl.GatewayShardImpl:
        return hikari.impl.GatewayShardImpl(
            event_factory=self._event_factory,
            event_manager=self._event_manager,
            http_settings=self._http_settings,
            intents=self._intents,
            proxy_settings=self._proxy_settings,
            shard_id=shard_id,
            token=self._token,
            shard_count=self._global_shard_count,
            url=self._gateway_url,
        )

    async def _spawn_shard(self) -> None:
        shard = await self._manager.recommended_shard(self._make_shard)
        self._shards[shard.id] = shard

    async def _fetch_other_states(self, proxied_shards: dict[int, _ShardProxy], /) -> None:
        while True:
            await asyncio.sleep(10)
            for state in await self._manager.get_all_states():
                if shard := proxied_shards.get(state.shard_id):
                    shard.update_state(state)

    async def start(self) -> None:
        if self._close_event:
            raise hikari.ComponentStateConflictError("Already running")

        self._close_event = asyncio.Event()
        await self._manager.start(self._manager_address, credentials=self._credentials)

        proxied_shards: dict[int, _ShardProxy] = {}
        local_shards = range(self._local_shard_count)
        for shard_id in range(self._global_shard_count):
            if shard_id not in local_shards:
                self._shards[shard_id] = proxied_shards[shard_id] = _ShardProxy(
                    self._manager, shard_id, self._intents, self._global_shard_count
                )

        self._fetch_task = asyncio.create_task(self._fetch_other_states(proxied_shards))
        await self._event_manager.dispatch(self._event_factory.deserialize_starting_event())
        await asyncio.gather(*(self._spawn_shard() for _ in local_shards))
        await self._event_manager.dispatch(self._event_factory.deserialize_started_event())
